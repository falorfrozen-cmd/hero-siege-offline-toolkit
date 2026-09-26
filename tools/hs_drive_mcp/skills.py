"""The skill bar and the talent tree: five tools for a test session.

ForgePact's skill research (`ForgePact/docs/skill-actions-research.md`,
toolkit issue #147) measured, in two live sessions, what a cast, a binding, a
talent allocation and a reset go through. These tools are written against its
`## Decision` lines and against the plugin's verbatim replies, not against
what was expected before the sessions ran:

- `hs_skills_status` reads the bar, the learned talents and the sub-talent
  nodes through the player build's read-only `skillstate`.
- `hs_skill_cast` presses the key the **caller** names through `hs_input`'s
  own injection (no reader for a slot's key was found: `castKeyRule: not
  measured`) and proves the cast from game state: the instance count of the
  ability's effect object, which `skillstate` prints as `effect=` for an
  ability `kSkillTimerNames` lists (the toggle research's rule, `castProof`).
  Before the press it reads the count `PRE_PRESS_READS` times and refuses
  `proof_unstable` if it moves with no key pressed; the samples come back as
  `effect_samples_before`. That table is a generated name match, not a
  measured list, and the rule was measured on toggles with the aura family as
  its negative controls, so for an aura such as `darkOath` a count that never
  moves may mean the rule does not reach it, not that the key failed.
  A cast is play, not a save write, so it takes no backup. It is also the
  thing a test exercises, so it goes through the game's input path, never a
  by-name `TalentUse`.
- `hs_talent_allocate` is setup, so it goes through the game's own handlers by
  name (`talentalloc`, `allocRoute`/`subAllocRoute: byname`), behind
  `saves.session_backup_gate`, and confirms itself by re-reading
  `skillstate`: the id joining the learned list, or one sub-talent node
  rising by one. Nothing reads a point count or a level (`pointsReader: not
  measured`).
- `hs_skill_bind` and `hs_talent_reset` refuse `route_not_measured` before
  anything is sent: live 2 did not reproduce either route by name
  (`bindRoute`, `resetRoute: shape not reproduced`). Their signatures carry
  `backup_id` already, so they do not change when a session measures them.

Every tool asks `lease.guard` first and returns through `lease.stamp`; the
sends and the injection inside pass `lease_checked=True`. Every result carries
`verb_trail` (the command lines sent, in order) and `proof` (the `skillstate`
lines a confirmation read). No MCP import: `server.py` registers these.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from . import ipc, layout, lease, procs, results, saves
from . import input as input_module

COMMAND = "skillstate"
HEADER = "skillstate:"
#: The research build's reader prints the same body lines under this header
#: (`SpState` takes them from the `skillstate` readers), and live 2's verbatim
#: replies are of that command, so the parser takes both.
RESEARCH_HEADER = "skillprobe state:"
FOOTER_SUFFIX = "talent(s) on the bar"
#: What a player build that predates a verb prints (`RunCommand`'s allowlist).
UNAVAILABLE = "command unavailable in player build:"
ALLOC_PREFIX = "talentalloc:"

#: The bar that is drawn is row 0 (`slotRule`); row 1 lists the owned skills.
BAR_ROW = 0
#: C-1.10's hold, the one `hs_select_character` and live 2's K2 press used.
KEY_HOLD_MS = 120
#: The key that opens and closes the talent screen (`talentScreenOpenRoute`).
TALENT_SCREEN_KEY = 84
TALENT_SCREEN_OBJECT = "UI_Talent_Screen_obj"
POLL_S = 0.5
#: `skillstate` reads before a cast's key, `POLL_S` apart (so they span
#: 2 x `POLL_S`). The effect count must hold still across them with no key
#: pressed, or a change after the press says nothing about the press.
PRE_PRESS_READS = 3

_SLOT_RE = re.compile(r"^slot=(\d+),(\d+) (.*)$")
_WHOLE_ROW_RE = re.compile(r"^slot=(\d+,\*|unreadable) ")
_SUB_RE = re.compile(r"^sub=(\d+) (.*)$")
_NODE_RE = re.compile(r"^(s\d+)=(-?\d+(?:\.\d+)?)$")
_INT_RE = re.compile(r"^-?\d+$")

#: Lines only the research build's `skillprobe state` prints.
_RESEARCH_ONLY = ("hud.playerSlot.bind_skill=", "bind ", "level=", "points? ")


def _sleep(seconds: float) -> None:
    """The one seam every wait here goes through, so a test finishes in
    milliseconds whatever the poll budget."""
    time.sleep(seconds)


def _now() -> float:
    return time.monotonic()


class SkillStateError(ValueError):
    """A reply that is not the `skillstate` format; the message says which
    line and why."""


@dataclass(frozen=True)
class Slot:
    """One `slot=<row>,<i>` line. `talent_id` is `None` for `none` or an
    unreadable id; `effect` is `None` when the line has no `effect=` field
    (`has_effect` false) or it read `unreadable`."""
    row: int
    index: int
    talent_id: int | None
    ability: str | None
    timer: int | str | None
    has_effect: bool
    effect: int | None
    line: str

    def public(self) -> dict[str, Any]:
        return {"row": self.row, "index": self.index, "talent_id": self.talent_id,
                "ability": self.ability, "timer": self.timer, "effect": self.effect}


@dataclass(frozen=True)
class SkillState:
    header: str
    slots: tuple[Slot, ...]
    learned: tuple[int, ...] | None
    subtalents: dict[int, dict[str, float] | None]
    lines: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def slot(self, row: int, index: int) -> Slot | None:
        return next((s for s in self.slots if s.row == row and s.index == index), None)

    def subtalents_public(self) -> dict[str, dict[str, int | float] | None]:
        out: dict[str, dict[str, int | float] | None] = {}
        for talent, nodes in self.subtalents.items():
            out[str(talent)] = None if nodes is None else {
                k: (int(v) if float(v).is_integer() else v) for k, v in nodes.items()}
        return out


def _number(text: str) -> int | None:
    return int(text) if _INT_RE.match(text) else None


def _parse_slot(line: str) -> Slot:
    match = _SLOT_RE.match(line)
    if not match:
        raise SkillStateError(f"not a slot line: {line!r}")
    row, index, rest = int(match.group(1)), int(match.group(2)), match.group(3)
    if not rest.startswith("talent="):
        raise SkillStateError(f"slot line without talent=: {line!r}")
    effect_at = rest.rfind(" effect=")
    has_effect = effect_at >= 0
    effect_text = rest[effect_at + len(" effect="):] if has_effect else ""
    if has_effect:
        rest = rest[:effect_at]
    timer_at = rest.rfind(" timer=")
    if timer_at < 0:
        raise SkillStateError(f"slot line without timer=: {line!r}")
    timer_text = rest[timer_at + len(" timer="):]
    head = rest[:timer_at]
    ability = None
    ability_at = head.find(" ability=")
    if ability_at >= 0:
        ability = head[ability_at + len(" ability="):]
        head = head[:ability_at]
    talent_text = head[len("talent="):]
    if talent_text == "none":
        talent_id = None
    else:
        talent_id = _number(talent_text)
        if talent_id is None and not talent_text.startswith("unreadable"):
            raise SkillStateError(f"slot line whose talent= is not a number: {line!r}")
    if talent_id is not None and ability is None:
        raise SkillStateError(f"slot line with a talent id and no ability=: {line!r}")
    effect = None
    if has_effect:
        effect = _number(effect_text)
        if effect is None and effect_text != "unreadable":
            raise SkillStateError(f"slot line whose effect= is not a count: {line!r}")
    timer: int | str | None = _number(timer_text)
    if timer is None:
        timer = timer_text or None
    return Slot(row, index, talent_id, ability, timer, has_effect, effect, line)


def _parse_nodes(text: str, line: str) -> dict[str, float] | None:
    if text == "none" or text == "(no members)":
        return {}
    if text.startswith("unreadable"):
        return None
    nodes: dict[str, float] = {}
    for token in text.split(" "):
        match = _NODE_RE.match(token)
        if not match:
            raise SkillStateError(f"sub line with a token that is not s<NN>=<n>: {line!r}")
        nodes[match.group(1)] = float(match.group(2))
    return nodes


def parse(reply: dict[str, Any] | str) -> SkillState:
    """The `skillstate` (or research `skillprobe state`) reply in one
    `ipc.send` result or text. Raises `SkillStateError` naming the line for
    anything else: every line between the header and the footer must be one
    of the verb's own shapes, so a reply this was not written for is never
    read as an empty bar."""
    if isinstance(reply, dict):
        lines = layout.reply_lines(reply)
    else:
        lines = [raw.strip() for raw in reply.splitlines()]
    if not any(lines):
        raise SkillStateError("the reply is empty")
    unavailable = next((l for l in lines if l.startswith(UNAVAILABLE)), None)
    if unavailable:
        raise SkillStateError(unavailable)
    start = next((i for i, l in enumerate(lines) if l in (HEADER, RESEARCH_HEADER)), None)
    if start is None:
        raise SkillStateError(f"no {HEADER!r} header line in the reply: {lines[:3]!r}")
    header = lines[start]
    research = header == RESEARCH_HEADER
    footer_prefix = header + " "
    slots: list[Slot] = []
    notes: list[str] = []
    learned: tuple[int, ...] | None = None
    seen_learned = False
    subtalents: dict[int, dict[str, float] | None] = {}
    body: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith(footer_prefix) and line.endswith(FOOTER_SUFFIX):
            return SkillState(header, tuple(slots), learned, subtalents,
                              tuple([header] + body + [line]), tuple(notes))
        body.append(line)
        if line.startswith("slot="):
            if _WHOLE_ROW_RE.match(line):
                notes.append(line)   # the verb could not list a whole row
            else:
                slots.append(_parse_slot(line))
        elif line.startswith("global.mySkills="):
            seen_learned = True
            value = line[len("global.mySkills="):]
            if value.startswith("[") and value.endswith("]"):
                inner = value[1:-1]
                ids = [_number(t) for t in inner.split(",")] if inner else []
                if any(i is None for i in ids):
                    raise SkillStateError(f"global.mySkills holds something other than ids: {line!r}")
                learned = tuple(int(i) for i in ids)  # type: ignore[arg-type]
            elif not value.startswith("unreadable"):
                raise SkillStateError(f"global.mySkills is not a list: {line!r}")
        elif line.startswith("sub="):
            match = _SUB_RE.match(line)
            if not match:
                raise SkillStateError(f"not a sub line: {line!r}")
            subtalents[int(match.group(1))] = _parse_nodes(match.group(2), line)
        elif research and line.startswith(_RESEARCH_ONLY):
            continue
        else:
            raise SkillStateError(f"a line {HEADER!r} does not print: {line!r}")
    raise SkillStateError(f"the reply ends without the {footer_prefix}<n> {FOOTER_SUFFIX} footer"
                          + ("" if seen_learned else " (and has no global.mySkills line)"))


# --------------------------------------------------------------------------
# Shared by the tools
# --------------------------------------------------------------------------

def _process_refusal(tool: str, gate: Callable[[], tuple[str, str]] | None,
                     **fields: Any) -> dict[str, Any] | None:
    state, why = (procs.gate if gate is None else gate)()
    if state == procs.RUNNING:
        return None
    if state == procs.NOT_RUNNING:
        return results.refuse(tool, "game_not_running",
                              f"{why} There is no game to read or drive; launch "
                              "it with hs_launch first. Nothing was sent.", **fields)
    token = {procs.ENGINE_MISSING: "engine_source_missing",
             procs.ENGINE_UNUSABLE: "engine_import_failed"}.get(state, "game_state_unknown")
    return results.refuse(tool, token, f"{why} Nothing was sent.", **fields)


class _Session:
    """The sends of one tool call: every command line goes through here, so
    `verb_trail` is exactly what was sent, in order."""

    def __init__(self, tool: str):
        self.tool = tool
        self.trail: list[str] = []

    def fields(self, **more: Any) -> dict[str, Any]:
        return {"verb_trail": list(self.trail), **more}

    def refuse(self, reason: str, detail: str, **more: Any) -> dict[str, Any]:
        more.setdefault("proof", [])
        return results.refuse(self.tool, reason, detail, **self.fields(**more))

    def send(self, line: str) -> dict[str, Any]:
        self.trail.append(line)
        result = ipc.send([line], tool=self.tool, lease_checked=True)
        if results.is_refusal(result):
            return result
        verb = line.split(" ", 1)[0]
        unavailable = next((l for l in layout.reply_lines(result) if l.startswith(UNAVAILABLE)), None)
        if unavailable:
            return self.refuse(
                "plugin_verb_missing",
                f"the installed ForgePact plugin answered {unavailable!r}: it predates "
                f"the `{verb}` verb this tool needs. Install a ForgePact build that has it.")
        return result

    def state(self) -> SkillState | dict[str, Any]:
        result = self.send(COMMAND)
        if results.is_refusal(result):
            return result if "verb_trail" in result else {**result, **self.fields(proof=[])}
        try:
            return parse(result)
        except SkillStateError as exc:
            return self.refuse(
                "plugin_verb_missing",
                f"`{COMMAND}` answered with a reply this server cannot read ({exc}); a "
                "plugin whose reader prints another format is not the verb this tool was "
                "written for, so nothing is inferred from it.")


def _stamped(result: dict[str, Any]) -> dict[str, Any]:
    return lease.stamp(result)


# --------------------------------------------------------------------------
# hs_skills_status
# --------------------------------------------------------------------------

def hs_skills_status(tool: str = "hs_skills_status",
                     gate: Callable[[], tuple[str, str]] | None = None) -> dict[str, Any]:
    """The bar, the learned talents and each bar talent's sub-talent nodes,
    as `skillstate` printed them. Reads only; the one send is lease-gated like
    `hs_command`'s."""
    refusal = lease.guard(tool)
    if refusal:
        return refusal
    return _stamped(_skills_status(tool, gate))


def _skills_status(tool: str, gate) -> dict[str, Any]:
    session = _Session(tool)
    refusal = _process_refusal(tool, gate, **session.fields(proof=[]))
    if refusal:
        return refusal
    state = session.state()
    if isinstance(state, dict):
        return state
    return results.ok(tool, slots=[s.public() for s in state.slots],
                      learned=None if state.learned is None else list(state.learned),
                      subtalents=state.subtalents_public(), notes=list(state.notes),
                      **session.fields(proof=list(state.lines)))


# --------------------------------------------------------------------------
# hs_skill_cast
# --------------------------------------------------------------------------

def _slot_spec(slot: Any) -> tuple[int, int] | None:
    match = re.match(r"^\s*(\d+)\s*,\s*(\d+)\s*$", str(slot)) if slot is not None else None
    return (int(match.group(1)), int(match.group(2))) if match else None


def hs_skill_cast(key: Any, slot: Any = None, ability: Any = None, timeout_s: float = 10,
                  tool: str = "hs_skill_cast",
                  gate: Callable[[], tuple[str, str]] | None = None) -> dict[str, Any]:
    """Press `key` for one bar slot and prove the cast by the slot's
    `effect=` count moving. See the module docstring."""
    refusal = lease.guard(tool)
    if refusal:
        return refusal
    return _stamped(_skill_cast(key, slot, ability, timeout_s, tool, gate))


def _skill_cast(key, slot, ability, timeout_s, tool, gate) -> dict[str, Any]:
    session = _Session(tool)
    if isinstance(key, bool) or not isinstance(key, int) or not 1 <= key <= 254:
        return session.refuse("invalid_input", f"key must be a Windows virtual-key code 1-254, not {key!r}. "
                              "Nothing was sent.")
    if (slot is None) == (ability is None):
        return session.refuse("invalid_input", "give exactly one of slot (\"row,index\") or ability "
                              "(an abilityId as skillstate prints it). Nothing was sent.")
    wanted = _slot_spec(slot) if slot is not None else None
    if slot is not None and wanted is None:
        return session.refuse("invalid_input", f"slot must read \"row,index\", not {slot!r}. Nothing was sent.")
    refusal = _process_refusal(tool, gate, **session.fields(proof=[]))
    if refusal:
        return refusal
    before_state = session.state()
    if isinstance(before_state, dict):
        return before_state
    bar = [s for s in before_state.slots if s.row == BAR_ROW]
    if wanted is not None:
        target = next((s for s in bar if (s.row, s.index) == wanted), None)
        what = f"slot {wanted[0]},{wanted[1]}"
    else:
        target = next((s for s in bar if s.ability == ability and s.talent_id), None)
        what = f"ability {ability!r}"
    if target is None or not target.talent_id:
        return session.refuse(
            "skill_not_on_bar",
            f"no row-{BAR_ROW} bar slot holds {what} with a talent (the drawn bar is row "
            f"{BAR_ROW}; row 1 is the owned-skills list). Bar read: "
            f"{[s.line for s in bar]}. No key was pressed.", proof=list(before_state.lines))
    if not target.has_effect or target.effect is None:
        return session.refuse(
            "proof_unavailable",
            f"{target.line!r} carries no readable effect= count: its ability is not an "
            "entry of ForgePact's kSkillTimerNames (or the count was unreadable), so the "
            "player build has nothing to prove this cast by. No key was pressed.",
            proof=[target.line])
    # The negative control the rule lacked: the count, read again with no key
    # pressed, must not move. A double-cast proc, an earlier effect expiring or
    # an object that respawns would otherwise read as this cast.
    samples: list[Slot | None] = [target]
    stable = True
    while stable and len(samples) < PRE_PRESS_READS:
        _sleep(POLL_S)
        again = session.state()
        if isinstance(again, dict):
            return again
        now = again.slot(target.row, target.index)
        samples.append(now)
        stable = (now is not None and now.talent_id == target.talent_id
                  and now.effect == target.effect)
    effect_samples_before = [None if s is None else s.effect for s in samples]
    sample_lines = [f"slot={target.row},{target.index} (not printed)" if s is None else s.line
                    for s in samples]
    if not stable:
        return session.refuse(
            "proof_unstable",
            f"slot {target.row},{target.index}'s effect= count did not hold still with no key "
            f"pressed (reads {POLL_S} s apart: {effect_samples_before}), so a change after a "
            "press could not be told from one without it. No key was pressed.",
            proof=sample_lines, effect_samples_before=effect_samples_before)
    injected = [{"type": "key", "vk": key, "hold_ms": KEY_HOLD_MS}]
    pressed = input_module.inject(injected, route=input_module.ROUTE_SEND_INPUT,
                                  force_focus=True, tool=tool, lease_checked=True)
    if results.is_refusal(pressed):
        return {**pressed, **session.fields(proof=[target.line], injected=injected,
                                            effect_samples_before=effect_samples_before)}
    rejected = int(pressed.get("records_rejected") or 0)
    if pressed.get("complete") is not True or rejected > 0:
        return session.refuse(
            "key_not_delivered",
            f"vk {key} was not delivered whole (complete={pressed.get('complete')!r}, "
            f"records_rejected={rejected}); inject said: {pressed.get('detail', '')}",
            proof=[target.line], injected=injected, focus_via=pressed.get("focus_via"),
            effect_samples_before=effect_samples_before)
    deadline = _now() + max(0.0, float(timeout_s))
    last = target
    while True:
        _sleep(POLL_S)
        after_state = session.state()
        if isinstance(after_state, dict):
            return {**after_state, "injected": injected,
                    "effect_samples_before": effect_samples_before}
        now = after_state.slot(target.row, target.index)
        if now is not None:
            last = now
            if (now.talent_id == target.talent_id and now.effect is not None
                    and now.effect != target.effect):
                return results.ok(tool, confirmed=True, slot=f"{target.row},{target.index}",
                                  talent_id=target.talent_id, ability=target.ability,
                                  effect_before=target.effect, effect_after=now.effect,
                                  effect_samples_before=effect_samples_before,
                                  injected=injected, focus_via=pressed.get("focus_via"),
                                  **session.fields(proof=[target.line, now.line]))
        if _now() >= deadline:
            return session.refuse(
                "cast_not_confirmed",
                f"vk {key} was delivered, and slot {target.row},{target.index}'s effect= count "
                f"did not move from {target.effect} within {timeout_s} s (last read "
                f"{last.line!r}; flat before the press: {effect_samples_before}). The skill "
                "may be on cooldown, refused by the game, or the key may not be this slot's; "
                "or the effect-count rule does not reach this ability (it was measured on "
                "toggles, with auras as the negative controls, and kSkillTimerNames is a name "
                "match, not a measured list).", proof=[target.line, last.line], injected=injected,
                effect_samples_before=effect_samples_before)


# --------------------------------------------------------------------------
# hs_skill_bind, hs_talent_reset: not measured
# --------------------------------------------------------------------------

BIND_NOT_MEASURED = (
    "Binding a skill to a bar slot has no measured by-name route: in live 2 of "
    "the skill research the game ran UiATalentChange on the expanded bar's popup "
    "button, and the replay was refused because that button no longer existed "
    "(bindRoute: shape not reproduced - ForgePact docs/skill-actions-research.md, "
    "Decision). No skillbind verb exists, so nothing was sent.")
RESET_NOT_MEASURED = (
    "Resetting the talent tree has no measured by-name route: in live 2 of the "
    "skill research the reset button's UiATalentScreenResetTalents and its "
    "confirm dialog's ClearPersistSkill both dispatched by name and changed "
    "nothing (resetRoute: shape not reproduced - ForgePact "
    "docs/skill-actions-research.md, Decision). No talentreset verb exists, so "
    "nothing was sent.")


def hs_skill_bind(slot: Any, ability: Any, backup_id: Any,
                  tool: str = "hs_skill_bind") -> dict[str, Any]:
    """Refuses `route_not_measured` after the lease, before anything is sent."""
    refusal = lease.guard(tool)
    if refusal:
        return refusal
    return _stamped(results.refuse(tool, "route_not_measured", BIND_NOT_MEASURED,
                                   verb_trail=[], proof=[]))


def hs_talent_reset(backup_id: Any, tool: str = "hs_talent_reset") -> dict[str, Any]:
    """Refuses `route_not_measured` after the lease, before anything is sent."""
    refusal = lease.guard(tool)
    if refusal:
        return refusal
    return _stamped(results.refuse(tool, "route_not_measured", RESET_NOT_MEASURED,
                                   verb_trail=[], proof=[]))


# --------------------------------------------------------------------------
# hs_talent_allocate
# --------------------------------------------------------------------------

def _sub_rose(before: dict[str, float] | None, after: dict[str, float] | None) -> str | None:
    """The node that rose by exactly one, or None. A node absent before
    counts as 0: the map adds a talent's node on its first allocation."""
    if after is None:
        return None
    was = before or {}
    for node, level in after.items():
        if level == was.get(node, 0.0) + 1.0:
            return node
    return None


def hs_talent_allocate(talent_id: Any, backup_id: Any, sub: Any = None,
                       tool: str = "hs_talent_allocate",
                       gate: Callable[[], tuple[str, str]] | None = None,
                       pids: Iterable[int] | None = None,
                       start_reader: Callable[[int], Any] | None = None) -> dict[str, Any]:
    """One talent point, or one sub-talent node (`sub`, 1-based in the
    listing's order), by the game's own handlers; confirmed by re-reading.
    See the module docstring."""
    refusal = lease.guard(tool)
    if refusal:
        return refusal
    return _stamped(_talent_allocate(talent_id, backup_id, sub, tool, gate, pids, start_reader))


def _talent_allocate(talent_id, backup_id, sub, tool, gate, pids, start_reader) -> dict[str, Any]:
    session = _Session(tool)
    if isinstance(talent_id, bool) or not isinstance(talent_id, int) or talent_id < 1:
        return session.refuse("invalid_input", f"talent_id must be a positive integer, not {talent_id!r}. "
                              "Nothing was sent.")
    if sub is not None and (isinstance(sub, bool) or not isinstance(sub, int) or sub < 1):
        return session.refuse("invalid_input", f"sub must be a 1-based node number, not {sub!r}. "
                              "Nothing was sent.")
    refusal = _process_refusal(tool, gate, **session.fields(proof=[]))
    if refusal:
        return refusal
    refusal = saves.session_backup_gate(tool, backup_id, pids=pids, start_reader=start_reader)
    if refusal:
        return {**refusal, **session.fields(proof=[])}
    before = session.state()
    if isinstance(before, dict):
        return before
    verb = f"talentalloc {talent_id}" + (f" sub {sub}" if sub is not None else "")
    reply = session.send(verb)
    if results.is_refusal(reply):
        return reply if "verb_trail" in reply else {**reply, **session.fields(proof=[])}
    verb_lines = [l for l in layout.reply_lines(reply) if l.startswith(ALLOC_PREFIX)]
    # The verb opens the screen when it is closed; if the screen's buttons are
    # built a frame later than the open (not measured), the first call finds
    # none. It says so, and one more send finds them.
    if any("not allocatable" in l and "opened by this call" in l for l in verb_lines):
        reply = session.send(verb)
        if results.is_refusal(reply):
            return reply if "verb_trail" in reply else {**reply, **session.fields(proof=[])}
        verb_lines += [l for l in layout.reply_lines(reply) if l.startswith(ALLOC_PREFIX)]
    last = verb_lines[-2:]
    refused = verb_lines[-1] if verb_lines and "refused - " in verb_lines[-1] else None
    if refused:
        closed = _close_screen(session)
        if "screen not open" in refused:
            return session.refuse("talent_screen_not_open", f"talentalloc answered {refused!r}.",
                                  verb_lines=verb_lines, **closed)
        if "not allocatable" in refused:
            return session.refuse("talent_not_allocatable", f"talentalloc answered {refused!r}.",
                                  verb_lines=verb_lines, **closed)
    after = session.state()
    if isinstance(after, dict):
        return {**after, "verb_lines": verb_lines}
    closed = _close_screen(session)
    # An unreadable before-read is not an empty one: it can confirm nothing,
    # or an id (or node) that was already there would count as new.
    if sub is None:
        was = set(before.learned or ())
        now = set(after.learned or ())
        confirmed = (before.learned is not None and after.learned is not None
                     and talent_id in now and talent_id not in was)
        proof = [_line(before, "global.mySkills="), _line(after, "global.mySkills=")]
        what = f"global.mySkills gained {talent_id}"
    else:
        unreadable_before = talent_id in before.subtalents and before.subtalents[talent_id] is None
        node = None if unreadable_before else _sub_rose(before.subtalents.get(talent_id),
                                                        after.subtalents.get(talent_id))
        confirmed = node is not None
        proof = [_line(before, f"sub={talent_id} "), _line(after, f"sub={talent_id} ")]
        what = f"node {node} of sub={talent_id} rose by one" if node else ""
    if not confirmed:
        return session.refuse(
            "alloc_not_confirmed",
            f"after `{verb}` a re-read of skillstate shows no change "
            + ("in global.mySkills" if sub is None else f"of one node of sub={talent_id} by one")
            + f" (verb said {last!r}). No point count is readable, so a missing free point "
            "reads the same as any other refusal of the game's own.",
            verb_lines=verb_lines, proof=proof, **closed)
    return results.ok(tool, confirmed=True, talent_id=talent_id, sub=sub, what=what,
                      learned=list(after.learned or ()),
                      subtalents=after.subtalents_public(), verb_lines=verb_lines,
                      **closed, **session.fields(proof=proof))


def _line(state: SkillState, prefix: str) -> str:
    return next((l for l in state.lines if l.startswith(prefix)), f"{prefix}(not printed)")


def _close_screen(session: _Session) -> dict[str, Any]:
    """Close the talent screen the verb left open: T, the key that opens and
    closes it (no by-name close was measured). Pressed only when
    `menulayout` lists the screen, so a verb that never opened it is not
    answered by opening it. `screen_closed` is what the listing says after."""
    def listed() -> bool | None:
        reply = session.send(f"{layout.COMMAND} {TALENT_SCREEN_OBJECT}")
        if results.is_refusal(reply):
            return None
        listing = layout.parse(reply)
        if listing is None:
            return None
        return any(row.obj == TALENT_SCREEN_OBJECT for row in listing.rows)

    before = listed()
    if before is None:
        return {"screen_closed": False, "close_detail": "menulayout could not list the talent screen"}
    if not before:
        return {"screen_closed": True, "close_detail": "the talent screen was not listed; nothing pressed"}
    pressed = input_module.inject([{"type": "key", "vk": TALENT_SCREEN_KEY, "hold_ms": KEY_HOLD_MS}],
                                  route=input_module.ROUTE_SEND_INPUT, force_focus=True,
                                  tool=session.tool, lease_checked=True)
    if results.is_refusal(pressed) or pressed.get("complete") is not True:
        return {"screen_closed": False,
                "close_detail": f"the T press was not delivered: {pressed.get('detail', '')}"}
    _sleep(POLL_S)
    after = listed()
    return {"screen_closed": after is False,
            "close_detail": "T pressed; " + ("the screen is no longer listed" if after is False
                                             else "the screen is still listed (an open sub-panel "
                                                  "closes only by its own close button)")}
