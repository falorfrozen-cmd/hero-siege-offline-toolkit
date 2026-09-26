"""The town stash and the bag: five tools that set up game state for a test.

ForgePact's stash and bag research (`ForgePact/docs/stash-bag-layout-research.md`,
toolkit #147) measured, in two live sessions, what opening, closing, switching
a tab and creating an item go through. These tools are written against its
`## Decision` lines and against the plugin's verbatim replies, not against
what was expected before the sessions ran. They exist to *set up* state for
other tests, so each goes through the game's own routine by name wherever
live 2 measured one, and proves what it did by re-reading:

- `hs_stash_open` warps the character to the stash with the player verb
  `playerwarp` (`warpRoute`: the stash's own room position, 48 below it),
  confirms the warp by re-reading `Player_obj`, then presses the interact
  key F (`stashOpenRoute: interact`) through `hs_input`'s own injection and
  polls for a listed `UI_Stash_obj`. There is no by-name open: the one
  by-name `UiCreate` open live 2 made was followed by the game dying on the
  next command (causality not established), so it is not shipped.
- `hs_stash_close` sends `stashclose` (`UiACloseButton` by name,
  `stashCloseRoute`) and polls for the window's absence. It takes no backup:
  the game's own close is what saves the stash.
- `hs_stash_tab` sends `stashtab <tabNumber>` (the tab button's own handler,
  `stashTabRoute`) and polls `stashTabSelected` on the window.
- `hs_bag_tab` sends `bagtab materials|socket` (`bagTabRoute`) and polls
  `tabSelected` on the stash window (`bagTabState` - not `stashTabSelected`).
  It proves that member, the one the game's own handler writes; it does not
  prove `activeNode` (the focus), which live 2 did not observe following a
  by-name call, and says so in `proof`. Every other bag tab refuses
  `route_not_measured` before anything is sent, and so does the bag with no
  stash window beside it (`bag_not_open`): only that case was measured.
- `hs_give_item` sends `giveitem bag <template> <count>`: a copy of an item
  map 0 already holds, made by the game's own loader (`giveItemRoute: bag:
  json`), confirmed by the verb's own re-read of map 0 and of the
  destination cells - its `giveitem: confirmed` line with one more item after
  than before. No window needs to be open. The stash destination refuses
  `route_not_measured`: it is `hs-drive-stash-move-research`'s.

Every writing tool (all but `hs_stash_close`) takes a `backup_id` and applies
`saves.session_backup_gate` before its first send. Every tool asks
`lease.guard` first and returns through `lease.stamp`; the sends and the
injection inside pass `lease_checked=True`. Every result carries
`verb_trail` (each verb line sent, with its own reply lines), `layout_trail`
(the key that was pressed, when one was) and `proof` (the listing and verb
lines that decided it).

No listing read here is checked against the client size
(`window_size_mismatch`): these tools click nothing, so a `win=` point
computed for another window size changes nothing they read - ids, tab
numbers and tab state are the same at any size.

No MCP import: `server.py` registers these.
"""
from __future__ import annotations

import math
import re
import time
from typing import Any, Callable, Iterable

from . import ipc, layout, lease, procs, results, saves
from . import input as input_module

#: `charselect`'s poll: 0.5 s between reads, 30 reads.
POLL_S = 0.5
POLL_ATTEMPTS = 30
#: `warpRoute`: the player lands this far below the stash's own `y`.
WARP_OFFSET_Y = 48
#: A warp is confirmed when the re-read player is within this of the target.
WARP_TOLERANCE_PX = 2
#: `stashOpenRoute: interact`: F, held as live 1 P0-3 and live 2 P2-2 held it.
INTERACT_KEY = 70
KEY_HOLD_MS = 120

#: `stashTabRule`: the tab number a stash tab row carries (`tabNumber`).
STASH_TABS = {"socketable": -2, "materials": -4, "unique": -5, "personal": 0,
              **{f"shared{n}": n for n in range(1, 20)}}
#: `bagTabRule`: the two bag sub-tabs live 2 measured by name, by the
#: `uiNodeCallstack` their rows carry.
BAG_TABS = {"materials": "InventoryTabMaterial", "socket": "InventoryTabSocket"}

UNAVAILABLE = "command unavailable in player build:"

BAG_NOT_MEASURED = (
    "Only the bag's Materials and Socket sub-tabs have a by-name route that "
    "was measured (live 2 P2-4, with the stash window open: "
    "UiAInventoryMaterialTabClick; UiAInventorySocketTabClick takes the same "
    "path). The page tabs and the vault, key, tarot and relic sub-tabs were "
    "never switched by name (the main sub-tab was restored by a click in live "
    "2, not by name - ForgePact docs/stash-bag-layout-research.md, Decision, "
    "bagTabRoute), so nothing was sent.")
GIVE_STASH_NOT_MEASURED = (
    "Giving an item into the stash has no measured route: live 2's attempt "
    "stopped at the loader with a key shape that was not the proven one "
    "(giveItemRoute: stash: not-observed - ForgePact "
    "docs/stash-bag-layout-research.md, Decision); it belongs to "
    "hs-drive-stash-move-research. Nothing was sent.")


def _sleep(seconds: float) -> None:
    """The one seam every wait here goes through, so a test finishes in
    milliseconds whatever the poll budget."""
    time.sleep(seconds)


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
    """The sends of one tool call. Every verb line goes through `verb`, so
    `verb_trail` is exactly the verbs sent, in order, each with its reply;
    every listing read goes through `read`."""

    def __init__(self, tool: str):
        self.tool = tool
        self.verb_trail: list[dict[str, Any]] = []
        self.layout_trail: list[dict[str, Any]] = []
        self.proof: list[str] = []

    def fields(self, **more: Any) -> dict[str, Any]:
        out = {"verb_trail": list(self.verb_trail), "layout_trail": list(self.layout_trail),
               "proof": list(self.proof)}
        out.update(more)
        return out

    def refuse(self, reason: str, detail: str, **more: Any) -> dict[str, Any]:
        return results.refuse(self.tool, reason, detail, **self.fields(**more))

    def ok(self, **more: Any) -> dict[str, Any]:
        return results.ok(self.tool, **self.fields(**more))

    def passthrough(self, refusal: dict[str, Any]) -> dict[str, Any]:
        """An inner refusal (IPC, injection, backup gate) with this call's
        trails attached."""
        return {**refusal, **self.fields()}

    def read(self, objects: Iterable[str]) -> list[layout.Listing] | dict[str, Any]:
        """One send carrying one `menulayout <Obj>` line per object; every
        listing of the reply, in order."""
        lines = [f"{layout.COMMAND} {obj}" for obj in objects]
        reply = ipc.send(lines, tool=self.tool, lease_checked=True)
        if results.is_refusal(reply):
            return self.passthrough(reply)
        text = layout.reply_lines(reply)
        if any(l.startswith(layout.UNAVAILABLE) for l in text):
            return self.refuse("layout_command_missing",
                               f"the installed ForgePact plugin answered {layout.UNAVAILABLE!r}: it "
                               "predates the read-only `menulayout` these tools prove every action "
                               "by, so nothing was changed.")
        listings = layout.parse_all(reply)
        if not listings:
            return self.refuse("layout_command_missing",
                               f"`{lines[0]}` replied with no `menulayout:` listing "
                               f"({[l for l in text if l][:3]!r}), so there is nothing to prove an "
                               "action by and nothing was changed.")
        return listings

    def verb(self, line: str) -> layout.VerbReply | dict[str, Any]:
        """One verb line, and its own reply lines into `verb_trail`.
        `plugin_verb_missing` when the installed build predates the verb."""
        name = line.split(" ", 1)[0]
        reply = ipc.send([line], tool=self.tool, lease_checked=True)
        if results.is_refusal(reply):
            self.verb_trail.append({"sent": line, "reply": [], "refused": reply.get("reason")})
            return self.passthrough(reply)
        parsed = layout.parse_verb(reply, name)
        self.verb_trail.append({"sent": line, "reply": list(parsed.lines)})
        if parsed.unavailable:
            return self.refuse(
                "plugin_verb_missing",
                f"the installed ForgePact plugin answered '{UNAVAILABLE} {name}': it predates "
                f"the `{name}` verb this tool needs. Install a ForgePact build that has it.")
        return parsed

    def poll(self, objects: Iterable[str], done: Callable[[list[layout.Listing]], Any],
             attempts: int = POLL_ATTEMPTS) -> tuple[Any, list[layout.Listing] | None, dict[str, Any] | None]:
        """Re-read the listings every `POLL_S`, up to `attempts` reads, until
        `done(listings)` answers something truthy. `(answer, listings, None)`,
        or `(None, last_listings, None)` when the budget ran out, or
        `(None, None, refusal)` when a read was refused."""
        objects = list(objects)
        last = None
        for _ in range(max(1, attempts)):
            _sleep(POLL_S)
            listings = self.read(objects)
            if isinstance(listings, dict):
                return None, None, listings
            last = listings
            answer = done(listings)
            if answer:
                return answer, listings, None
        return None, last, None


def _stamped(result: dict[str, Any]) -> dict[str, Any]:
    return lease.stamp(result)


def _gate_and_backup(session: _Session, gate, backup_id, pids, start_reader) -> dict[str, Any] | None:
    refusal = _process_refusal(session.tool, gate, **session.fields())
    if refusal:
        return refusal
    refusal = saves.session_backup_gate(session.tool, backup_id, pids=pids, start_reader=start_reader)
    return session.passthrough(refusal) if refusal else None


def _finite(pair: tuple[float | None, float | None]) -> bool:
    return all(v is not None and math.isfinite(v) for v in pair)


def _nothing_called(verb: layout.VerbReply) -> bool:
    return bool(verb.refused) and "nothing was called" in verb.refused


# --------------------------------------------------------------------------
# hs_stash_open
# --------------------------------------------------------------------------

def hs_stash_open(backup_id: Any, timeout_s: float = 60, tool: str = "hs_stash_open",
                  gate: Callable[[], tuple[str, str]] | None = None,
                  pids: Iterable[int] | None = None,
                  start_reader: Callable[[int], Any] | None = None) -> dict[str, Any]:
    """Warp beside the town stash, press F, and prove the window is listed.
    See the module docstring."""
    refusal = lease.guard(tool)
    if refusal:
        return refusal
    return _stamped(_stash_open(backup_id, timeout_s, tool, gate, pids, start_reader))


def _stash_open(backup_id, timeout_s, tool, gate, pids, start_reader) -> dict[str, Any]:
    session = _Session(tool)
    refusal = _gate_and_backup(session, gate, backup_id, pids, start_reader)
    if refusal:
        return refusal
    objects = (layout.STASH_OBJECT, layout.PLAYER_OBJECT, layout.TOWN_STASH_OBJECT)
    listings = session.read(objects)
    if isinstance(listings, dict):
        return listings
    window = layout.match_stash_window(listings)
    if window is not None:
        session.proof.append(window.line)
        return session.refuse("stash_already_open",
                              f"UI_Stash_obj id={window.id} is already listed, so nothing was "
                              "sent. Close it with hs_stash_close first if a fresh open is wanted.")
    player, stash = layout.match_player(listings), layout.match_town_stash(listings)
    for row in (player, stash):
        if row is not None:
            session.proof.append(row.line)
    if player is None or stash is None or not _finite(player.gui) or not _finite(stash.gui):
        missing = [name for name, row in ((layout.PLAYER_OBJECT, player), (layout.TOWN_STASH_OBJECT, stash))
                   if row is None or not _finite(row.gui)]
        return session.refuse("stash_not_reachable",
                              f"menulayout listed no single {' / '.join(missing)} row with a finite "
                              "room position (the town stash exists only in town), so there is "
                              "nowhere to warp to and nothing was sent.")
    target = (stash.gui[0], stash.gui[1] + WARP_OFFSET_Y)
    warp = session.verb(f"playerwarp {target[0]:.1f} {target[1]:.1f}")
    if isinstance(warp, dict):
        return warp
    session.proof.extend(warp.lines)
    if warp.refused:
        return session.refuse("warp_not_confirmed", f"playerwarp answered 'refused - {warp.refused}'.",
                              target=list(target))
    attempts = max(1, min(POLL_ATTEMPTS, int(float(timeout_s) / POLL_S)))

    def landed(ls):
        row = layout.match_player(ls)
        if row is not None and _finite(row.gui) and \
                abs(row.gui[0] - target[0]) <= WARP_TOLERANCE_PX and abs(row.gui[1] - target[1]) <= WARP_TOLERANCE_PX:
            return row
        return None

    at, last, refusal = session.poll((layout.PLAYER_OBJECT,), landed, attempts)
    if refusal:
        return refusal
    if at is None:
        seen = layout.match_player(last or [])
        return session.refuse("warp_not_confirmed",
                              f"after playerwarp the re-read Player_obj is not within {WARP_TOLERANCE_PX} px "
                              f"of {target} (last read: {seen.line if seen else 'no single Player_obj row'!r}). "
                              "No key was pressed.", target=list(target))
    session.proof.append(at.line)
    injected = [{"type": "key", "vk": INTERACT_KEY, "hold_ms": KEY_HOLD_MS}]
    pressed = input_module.inject(injected, route=input_module.ROUTE_SEND_INPUT, force_focus=True,
                                  tool=tool, lease_checked=True)
    if results.is_refusal(pressed):
        return session.passthrough(pressed)
    rejected = int(pressed.get("records_rejected") or 0)
    if pressed.get("complete") is not True or rejected > 0:
        return session.refuse("click_not_delivered",
                              f"the interact key F (vk {INTERACT_KEY}) was not delivered whole "
                              f"(complete={pressed.get('complete')!r}, records_rejected={rejected}); "
                              f"inject said: {pressed.get('detail', '')}", target=list(target))
    session.layout_trail.append({"key": INTERACT_KEY, "hold_ms": KEY_HOLD_MS,
                                 "focus_via": pressed.get("focus_via")})
    opened, last, refusal = session.poll((layout.STASH_OBJECT,), layout.match_stash_window, attempts)
    if refusal:
        return refusal
    if opened is None:
        return session.refuse("stash_not_open",
                              f"F was delivered beside the stash and no UI_Stash_obj was listed within "
                              f"{attempts} reads {POLL_S} s apart. The game refuses the open while an "
                              "interface is open or loot blocks the use key.", target=list(target))
    session.proof.append(opened.line)
    return session.ok(phase="stash_open", route="interact", window_id=opened.id,
                      stash_tab_selected=opened.number("stashTabSelected"), target=list(target))


# --------------------------------------------------------------------------
# hs_stash_close
# --------------------------------------------------------------------------

def hs_stash_close(tool: str = "hs_stash_close",
                   gate: Callable[[], tuple[str, str]] | None = None) -> dict[str, Any]:
    """Close the stash by its own close button's handler and prove the window
    is gone. No backup: the game's own close is what saves the stash."""
    refusal = lease.guard(tool)
    if refusal:
        return refusal
    return _stamped(_stash_close(tool, gate))


def _stash_close(tool, gate) -> dict[str, Any]:
    session = _Session(tool)
    refusal = _process_refusal(tool, gate, **session.fields())
    if refusal:
        return refusal
    listings = session.read((layout.STASH_OBJECT,))
    if isinstance(listings, dict):
        return listings
    window = layout.match_stash_window(listings)
    if window is None:
        return session.refuse("stash_not_open", "menulayout lists no single UI_Stash_obj, so there is "
                                                "nothing to close and nothing was sent.")
    session.proof.append(window.line)
    verb = session.verb("stashclose")
    if isinstance(verb, dict):
        return verb
    session.proof.extend(verb.lines)
    if verb.refused and _nothing_called(verb):
        token = "stash_not_open" if "stash not open" in verb.refused else "stash_still_open"
        return session.refuse(token, f"stashclose answered 'refused - {verb.refused}'.")
    closed, _, refusal = session.poll((layout.STASH_OBJECT,),
                                      lambda ls: not any(r.obj == layout.STASH_OBJECT
                                                         for l in ls for r in l.rows))
    if refusal:
        return refusal
    if not closed:
        return session.refuse("stash_still_open",
                              f"after stashclose UI_Stash_obj was still listed for {POLL_ATTEMPTS} reads "
                              f"{POLL_S} s apart (verb said {list(verb.lines)!r}).")
    return session.ok(phase="stash_closed", window_id=window.id)


# --------------------------------------------------------------------------
# hs_stash_tab
# --------------------------------------------------------------------------

def _stash_tab_number(tab: Any) -> int | None:
    return STASH_TABS.get(tab.strip().lower()) if isinstance(tab, str) else None


def hs_stash_tab(tab: Any, backup_id: Any, tool: str = "hs_stash_tab",
                 gate: Callable[[], tuple[str, str]] | None = None,
                 pids: Iterable[int] | None = None,
                 start_reader: Callable[[int], Any] | None = None) -> dict[str, Any]:
    """Switch the open stash to `tab` by the tab button's own handler and
    prove `stashTabSelected` reached it."""
    refusal = lease.guard(tool)
    if refusal:
        return refusal
    return _stamped(_stash_tab(tab, backup_id, tool, gate, pids, start_reader))


def _stash_tab(tab, backup_id, tool, gate, pids, start_reader) -> dict[str, Any]:
    session = _Session(tool)
    number = _stash_tab_number(tab)
    if number is None:
        return session.refuse("unknown_tab", f"{tab!r} is not a stash tab: use socketable, materials, "
                                             "unique, personal or shared1 to shared19. Nothing was sent.")
    refusal = _gate_and_backup(session, gate, backup_id, pids, start_reader)
    if refusal:
        return refusal
    listings = session.read((layout.STASH_OBJECT, layout.STASH_TAB_OBJECT))
    if isinstance(listings, dict):
        return listings
    window = layout.match_stash_window(listings)
    if window is None:
        return session.refuse("stash_not_open", "menulayout lists no single UI_Stash_obj; open the stash "
                                                "with hs_stash_open first. Nothing was sent.")
    session.proof.append(window.line)
    button = layout.match_stash_tab(listings, number)
    if button is None:
        return session.refuse("tab_not_listed", f"no single UI_Button_Stash_Tab_obj row carries "
                                                f"tabNumber={number} ({tab}); nothing was sent.")
    session.proof.append(button.line)
    before = window.number("stashTabSelected")
    if before == number:
        return session.ok(tab=tab, tab_number=number, selected_before=before, selected_after=before,
                          already_selected=True)
    verb = session.verb(f"stashtab {number}")
    if isinstance(verb, dict):
        return verb
    session.proof.extend(verb.lines)
    if verb.refused and _nothing_called(verb):
        if "stash not open" in verb.refused:
            return session.refuse("stash_not_open", f"stashtab answered 'refused - {verb.refused}'.")
        if "not a measured shape" in verb.refused:
            return session.refuse("route_not_measured", f"stashtab answered 'refused - {verb.refused}': "
                                  "the tab's handler is none of the shapes live 2 reproduced by name.")
        return session.refuse("tab_not_selected", f"stashtab answered 'refused - {verb.refused}'.")

    def reached(ls):
        row = layout.match_stash_window(ls)
        return row if row is not None and row.number("stashTabSelected") == number else None

    row, last, refusal = session.poll((layout.STASH_OBJECT,), reached)
    if refusal:
        return refusal
    if row is None:
        seen = layout.match_stash_window(last or [])
        return session.refuse("tab_not_selected",
                              f"after `stashtab {number}` stashTabSelected did not read {number} within "
                              f"{POLL_ATTEMPTS} reads (last: {seen.line if seen else 'no window row'!r}; "
                              f"verb said {list(verb.lines)!r}).",
                              selected_before=before)
    session.proof.append(row.line)
    return session.ok(tab=tab, tab_number=number, selected_before=before,
                      selected_after=row.number("stashTabSelected"), handler=verb.fields.get("handler"))


# --------------------------------------------------------------------------
# hs_bag_tab
# --------------------------------------------------------------------------

def hs_bag_tab(tab: Any, backup_id: Any, tool: str = "hs_bag_tab",
               gate: Callable[[], tuple[str, str]] | None = None,
               pids: Iterable[int] | None = None,
               start_reader: Callable[[int], Any] | None = None) -> dict[str, Any]:
    """Switch the bag beside the open stash to its Materials or Socket
    sub-tab by that tab's own handler, and prove `tabSelected` changed."""
    refusal = lease.guard(tool)
    if refusal:
        return refusal
    return _stamped(_bag_tab(tab, backup_id, tool, gate, pids, start_reader))


def _bag_tab(tab, backup_id, tool, gate, pids, start_reader) -> dict[str, Any]:
    session = _Session(tool)
    name = tab.strip().lower() if isinstance(tab, str) else None
    if name not in BAG_TABS:
        return session.refuse("route_not_measured", f"{tab!r}: {BAG_NOT_MEASURED}")
    refusal = _gate_and_backup(session, gate, backup_id, pids, start_reader)
    if refusal:
        return refusal
    listings = session.read((layout.STASH_OBJECT, layout.BAG_SUBTAB_OBJECT))
    if isinstance(listings, dict):
        return listings
    window = layout.match_stash_window(listings)
    if window is None:
        return session.refuse("bag_not_open",
                              "menulayout lists no single UI_Stash_obj: the bag's sub-tabs were measured "
                              "only beside the open stash (the handler's other was the stash window), so "
                              "nothing was sent. Open the stash with hs_stash_open first.")
    session.proof.append(window.line)
    button = layout.match_bag_subtab(listings, BAG_TABS[name])
    if button is None:
        return session.refuse("tab_not_listed", f"no single UI_Button_Inventory_Tab_Small_obj row carries "
                                                f"uiNodeCallstack={BAG_TABS[name]}; nothing was sent.")
    session.proof.append(button.line)
    before = window.number("tabSelected")
    if before is None:
        # The proof is tabSelected moving; a build that does not print it
        # (the live-2 research build) cannot confirm a switch, so send nothing.
        return session.refuse("route_not_measured",
                              "the stash window row carries no readable tabSelected, so a switch could "
                              "not be confirmed; nothing was sent.")
    verb = session.verb(f"bagtab {name}")
    if isinstance(verb, dict):
        return verb
    session.proof.extend(verb.lines)
    focus = {"activeNode_before": verb.fields.get("activeNode_before"),
             "activeNode_after": verb.fields.get("activeNode_after"),
             "focus_note": ("activeNode (the focus) is read, not proven: live 2 did not observe it follow "
                            "a by-name sub-tab call. What is proven is tabSelected.")}
    if verb.refused and _nothing_called(verb):
        token = "bag_not_open" if "bag not open" in verb.refused else \
            "route_not_measured" if "route_not_measured" in verb.refused else "tab_not_selected"
        return session.refuse(token, f"bagtab answered 'refused - {verb.refused}'.", **focus)
    verb_after = layout._int(verb.after) if verb.after is not None else None  # noqa: SLF001

    def changed(ls):
        row = layout.match_stash_window(ls)
        if row is None:
            return None
        now = row.number("tabSelected")
        if now is None or before is None or now == before:
            return None
        return row if verb_after is None or now == verb_after else None

    row, last, refusal = session.poll((layout.STASH_OBJECT,), changed)
    if refusal:
        return refusal
    if row is None:
        seen = layout.match_stash_window(last or [])
        return session.refuse("tab_not_selected",
                              f"after `bagtab {name}` tabSelected on the stash window did not move from "
                              f"{before} within {POLL_ATTEMPTS} reads (last: "
                              f"{seen.line if seen else 'no window row'!r}; verb said {list(verb.lines)!r}). "
                              "A sub-tab already on show reads the same as a call that did nothing: "
                              "both leave tabSelected where it was.",
                              selected_before=before, **focus)
    session.proof.append(row.line)
    return session.ok(tab=name, selected_before=before, selected_after=row.number("tabSelected"), **focus)


# --------------------------------------------------------------------------
# hs_give_item
# --------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"^\S+$")


def hs_give_item(to: Any, template: Any, backup_id: Any, count: Any = 1, tool: str = "hs_give_item",
                 gate: Callable[[], tuple[str, str]] | None = None,
                 pids: Iterable[int] | None = None,
                 start_reader: Callable[[int], Any] | None = None) -> dict[str, Any]:
    """A copy of an item map 0 holds, made by the game's own loader into the
    bag, confirmed by the verb's own re-read. See the module docstring."""
    refusal = lease.guard(tool)
    if refusal:
        return refusal
    return _stamped(_give_item(to, template, backup_id, count, tool, gate, pids, start_reader))


def _give_item(to, template, backup_id, count, tool, gate, pids, start_reader) -> dict[str, Any]:
    session = _Session(tool)
    where = to.strip().lower() if isinstance(to, str) else None
    if where == "stash":
        return session.refuse("route_not_measured", GIVE_STASH_NOT_MEASURED)
    if where != "bag":
        return session.refuse("invalid_input", f"to must be 'bag' or 'stash', not {to!r}. Nothing was sent.")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        return session.refuse("count_unsupported", f"count must be a whole number 1 or more, not {count!r}. "
                                                   "Nothing was sent.")
    if not isinstance(template, str) or not _TEMPLATE_RE.match(template):
        return session.refuse("invalid_input", f"template must be one item fingerprint as a `cell=` row "
                                               f"prints it (no spaces), not {template!r}. Nothing was sent.")
    refusal = _gate_and_backup(session, gate, backup_id, pids, start_reader)
    if refusal:
        return refusal
    verb = session.verb(f"giveitem bag {template} {count}")
    if isinstance(verb, dict):
        return verb
    session.proof.extend(verb.lines)
    if verb.refused:
        text = verb.refused
        token = ("template_not_found" if text.startswith("template not found") else
                 "count_unsupported" if text.startswith("count ") else
                 "route_not_measured" if text.startswith("route_not_measured") else "give_refused")
        return session.refuse(token, f"giveitem answered 'refused - {text}'.")
    key = verb.fields.get("key")
    before, after = layout._int(verb.before), layout._int(verb.after)  # noqa: SLF001
    confirmed = (verb.confirmed is not None and verb.not_confirmed is None and key is not None
                 and before is not None and after is not None and after == before + 1)
    if not confirmed:
        return session.refuse("give_not_confirmed",
                              "giveitem printed no `giveitem: confirmed` line with one more item after "
                              f"than before (lines: {list(verb.lines)!r}), so the item is not counted as "
                              "given.", key=key, before=before, after=after)
    # Optional proof: with a window open, the bag's grids list the new key in
    # a cell row. With none open only the HUD belt grid is listed, so this is
    # never required.
    listings = session.read((layout.GRID_OBJECT,))
    if not isinstance(listings, dict):
        session.proof.extend(cell.line for cell in layout.cells_holding(listings, key))
    o = verb.fields.get("o")
    return session.ok(confirmed=True, to="bag", template=template, key=key, before=before, after=after,
                      count=count, o=None if o in (None, "none") else layout._int(o))  # noqa: SLF001
