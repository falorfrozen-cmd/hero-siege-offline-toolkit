"""`tools/hs_drive_mcp/skills.py` -- the skill bar and talent tree tools.

`ipc.send` and `input.inject` are replaced by scripted doubles and `_sleep`/
`_now` by a fake clock; nothing here starts a game, sends a key or reads the
real `%LOCALAPPDATA%`. Every reply the doubles hand back is either a frame
the plugin printed in live 2 of the skill research, byte for byte
(`tests/hs_drive_mcp_skillstate_fixtures.py`), or one built from such a frame
in the `skillstate` format the player verb prints: the same body lines under
a `skillstate:` header, the research-only lines dropped, and an `effect=`
field on a slot whose ability has an effect object (`as_skillstate` below
does exactly that and nothing else). `talentalloc`'s own lines follow the
shape `ForgePact/tests/test_skill_actions_contract.py` pins.

The baseline and target pairs (`AGENTS.md` § "Mod Development Workflow"):
a cast whose effect count never moves is `cast_not_confirmed` and one whose
count moves is confirmed; an allocation whose `global.mySkills` frame is
`[236]` before and after is `alloc_not_confirmed`, and `[236]` then
`[236,239]` is confirmed -- live 2's own before and after frames -- and the
same for a sub-talent node on the `sub=239` line.
"""
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.hs_drive_mcp import results, saves, skills  # noqa: E402
from tests import hs_drive_mcp_skillstate_fixtures as fx  # noqa: E402
from tests.hs_drive_mcp_lease_fixtures import isolate_lease_dir  # noqa: E402


def setUpModule():
    isolate_lease_dir()


RUNNING = ("running", "1 hero_siege.exe process(es) are live: [4242].")
NOT_RUNNING = ("not_running", "the process snapshot returned 0 rows.")
PIDS = [4242]


def as_skillstate(frame: str, effects: dict[tuple[int, int], str] | None = None) -> str:
    """A live-2 `skillprobe state` frame in `skillstate`'s format: the header
    and footer word changed, the research-only lines dropped, and ` effect=<n>`
    appended to the slot lines `effects` names. Every other byte is the
    frame's own."""
    effects = effects or {}
    out = []
    for line in frame.split("\r\n"):
        stripped = line.strip()
        if stripped.startswith(skills._RESEARCH_ONLY):
            continue
        if line == "skillprobe state:":
            line = "skillstate:"
        elif line.startswith("skillprobe state: "):
            line = "skillstate: " + line[len("skillprobe state: "):]
        elif stripped.startswith("slot="):
            where = stripped.split(" ", 1)[0][len("slot="):]
            row, index = where.split(",")
            if (int(row), int(index)) in effects:
                line += " effect=" + effects[(int(row), int(index))]
        out.append(line)
    return "\r\n".join(out)


def verb(*lines: str) -> str:
    """`talentalloc`'s reply, framed as every command's output is."""
    return "---- running command file ----\r\n" + "".join(l + "\r\n" for l in lines) + "---- done ----\r\n"


class ScriptedIpc:
    """`ipc.send`, replaced. `script` maps a command line to a list of framed
    replies, consumed one at a time; the last one repeats."""

    def __init__(self, script):
        self.script = {line: list(replies) for line, replies in script.items()}
        self.calls: list[str] = []

    def send(self, lines, *, tool="hs_command", **kwargs):
        line = lines[0]
        self.calls.append(line)
        if line not in self.script:
            raise AssertionError(f"unscripted send {line!r}")
        queue = self.script[line]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        return results.ok(tool, sent=[line], reply=reply, reply_lines=reply.splitlines(),
                          consumed=True, queued=False)


class ScriptedInject:
    """`input.inject`, replaced. Records every call; `undelivered` answers
    `ok` with `complete: false`, the shape UIPI dropping records gives."""

    def __init__(self, undelivered=False, on_press=None):
        self.calls: list[dict] = []
        self.undelivered = undelivered
        self.on_press = on_press

    def __call__(self, actions, *, route="send_input", force_focus=False, tool="hs_input", **kwargs):
        self.calls.append({"actions": actions, "route": route, "force_focus": force_focus,
                           "lease_checked": kwargs.get("lease_checked")})
        if self.on_press:
            self.on_press(actions)
        if self.undelivered:
            return results.ok(tool, records_sent=2, records_rejected=2, complete=False,
                              detail="SendInput rejected 2 of 2 record(s).")
        return results.ok(tool, records_sent=2, records_rejected=0, complete=True,
                          focus_via="already_foreground")


class Clock:
    def __init__(self):
        self.t = 1000.0

    def sleep(self, seconds):
        self.t += seconds

    def now(self):
        return self.t


class SkillsBase(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.enterContext(patch.object(skills, "_sleep", self.clock.sleep))
        self.enterContext(patch.object(skills, "_now", self.clock.now))

    def use(self, script, inject=None):
        self.ipc = ScriptedIpc(script)
        self.inject = inject or ScriptedInject()
        self.enterContext(patch.object(skills.ipc, "send", self.ipc.send))
        self.enterContext(patch.object(skills.input_module, "inject", self.inject))


# --------------------------------------------------------------------------
# The parser
# --------------------------------------------------------------------------

class ParserTests(unittest.TestCase):
    def test_every_live_2_state_frame_parses(self):
        k1 = skills.parse(fx.SKILLPROBE_STATE_K1)
        self.assertEqual(k1.header, "skillprobe state:")
        self.assertEqual(len(k1.slots), 29)
        first = k1.slot(0, 0)
        self.assertEqual((first.talent_id, first.ability, first.timer), (242, "darkOath", 127))
        self.assertFalse(first.has_effect)
        self.assertEqual(k1.learned, (236, 237, 239, 240, 242, 245, 246, 247, 250, 251, 252, 253))
        self.assertEqual(k1.subtalents[242], {"s3": 5, "s4": 5, "s1": 5, "s8": 2, "s11": 3,
                                              "s12": 0, "s13": 0, "s10": 0})
        self.assertEqual(k1.subtalents[252], {})
        # An empty slot is the game's own 0 with an unreadable ability.
        self.assertEqual((k1.slot(0, 1).talent_id, k1.slot(0, 1).ability), (0, "unreadable"))
        self.assertEqual(skills.parse(fx.SKILLPROBE_STATE_AFTER_RESET).learned, (236,))
        self.assertEqual(skills.parse(fx.SKILLPROBE_STATE_AFTER_ALLOC).subtalents[239], {"s2": 0})
        self.assertEqual(skills.parse(fx.SKILLPROBE_STATE_AFTER_SUB).subtalents[239], {"s1": 1, "s2": 0})

    def test_the_skillstate_format_parses_with_and_without_effect(self):
        state = skills.parse(as_skillstate(fx.SKILLPROBE_STATE_K1, {(0, 0): "1"}))
        self.assertEqual(state.header, "skillstate:")
        self.assertEqual((state.slot(0, 0).has_effect, state.slot(0, 0).effect), (True, 1))
        self.assertFalse(state.slot(0, 2).has_effect)
        self.assertEqual(state.learned, skills.parse(fx.SKILLPROBE_STATE_K1).learned)
        unreadable = skills.parse(as_skillstate(fx.SKILLPROBE_STATE_K1, {(0, 0): "unreadable"}))
        self.assertEqual((unreadable.slot(0, 0).has_effect, unreadable.slot(0, 0).effect), (True, None))

    def test_a_bare_line_is_refused(self):
        text = as_skillstate(fx.SKILLPROBE_STATE_AFTER_RESET).replace(
            "  global.mySkills=", "  hello there\r\n  global.mySkills=")
        with self.assertRaisesRegex(skills.SkillStateError, "hello there"):
            skills.parse(text)

    def test_a_slot_line_without_talent_is_refused(self):
        text = as_skillstate(fx.SKILLPROBE_STATE_AFTER_RESET).replace(
            "  slot=0,1 talent=1 ability=basicAttack", "  slot=0,1 ability=basicAttack")
        with self.assertRaisesRegex(skills.SkillStateError, "without talent="):
            skills.parse(text)

    def test_an_empty_reply_is_refused(self):
        for empty in ("", "---- running command file ----\r\n---- done ----\r\n"):
            with self.subTest(empty=empty), self.assertRaises(skills.SkillStateError):
                skills.parse(empty)

    def test_research_only_lines_are_refused_under_the_player_header(self):
        # Negative control for the research header's allowance: the player
        # verb never prints a level or points line.
        text = fx.SKILLPROBE_STATE_AFTER_RESET.replace("skillprobe state:", "skillstate:")
        with self.assertRaisesRegex(skills.SkillStateError, "does not print"):
            skills.parse(text)

    def test_a_reply_cut_before_its_footer_is_refused(self):
        cut = as_skillstate(fx.SKILLPROBE_STATE_AFTER_RESET).split("skillstate: 4")[0]
        with self.assertRaisesRegex(skills.SkillStateError, "footer"):
            skills.parse(cut)

    def test_every_live_3_skillstate_frame_parses(self):
        # LIVE3_FIXTURES are the player build's own `skillstate` replies
        # (live 3, 2026-09-26), not the research build's `skillprobe state`:
        # the parser is exercised on the real header here, not `as_skillstate`.
        for frame in fx.LIVE3_FIXTURES:
            state = skills.parse(frame)
            self.assertEqual(state.header, "skillstate:")

    def test_live_3_w1_first_read_darkoath_0_0_effect_0(self):
        w1 = skills.parse(fx.SKILLSTATE_W1_FIRST_READ)
        slot = w1.slot(0, 0)
        self.assertEqual((slot.talent_id, slot.ability), (242, "darkOath"))
        self.assertTrue(slot.has_effect)
        self.assertEqual(slot.effect, 0)

    def test_live_3_post_q_press_moves_0_3_manaorb_not_0_0(self):
        after = skills.parse(fx.SKILLSTATE_POST_Q_PRESS)
        slot_0_3 = after.slot(0, 3)
        self.assertEqual((slot_0_3.talent_id, slot_0_3.ability, slot_0_3.effect), (253, "manaOrb", 1))
        slot_0_0 = after.slot(0, 0)
        self.assertEqual((slot_0_0.talent_id, slot_0_0.effect), (242, 0))

    def test_live_3_post_main_alloc_learned_236_244_sub_244_empty(self):
        after = skills.parse(fx.SKILLSTATE_POST_MAIN_ALLOC)
        self.assertEqual(after.learned, (236, 244))
        self.assertEqual(after.subtalents[244], {})

    def test_live_3_post_sub_alloc_and_post_reload_sub_244_s1_1(self):
        post_sub = skills.parse(fx.SKILLSTATE_POST_SUB_ALLOC)
        self.assertEqual(post_sub.subtalents[244], {"s1": 1})
        post_reload = skills.parse(fx.SKILLSTATE_POST_RELOAD_W6)
        self.assertEqual(post_reload.learned, (236, 244))
        self.assertEqual(post_reload.subtalents[244], {"s1": 1})

    def test_live_3_emptied_slot_reads_talent_0_with_no_effect(self):
        after = skills.parse(fx.SKILLSTATE_POST_MAIN_ALLOC)
        slot = after.slot(0, 0)
        self.assertEqual(slot.talent_id, 0)
        self.assertFalse(slot.has_effect)


# --------------------------------------------------------------------------
# hs_skills_status
# --------------------------------------------------------------------------

class StatusTests(SkillsBase):
    def test_status_reports_the_bar_the_learned_ids_and_the_nodes(self):
        self.use({"skillstate": [as_skillstate(fx.SKILLPROBE_STATE_K1, {(0, 0): "0"})]})
        result = skills.hs_skills_status(gate=lambda: RUNNING)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["slots"][0], {"row": 0, "index": 0, "talent_id": 242,
                                              "ability": "darkOath", "timer": 127, "effect": 0})
        self.assertEqual(result["learned"][:3], [236, 237, 239])
        self.assertEqual(result["subtalents"]["242"]["s3"], 5)
        self.assertEqual(result["subtalents"]["252"], {})
        self.assertEqual(result["verb_trail"], ["skillstate"])
        self.assertEqual(result["proof"][0], "skillstate:")
        self.assertEqual(result["lease"], "none")
        self.assertEqual(self.inject.calls, [])

    def test_plugin_verb_missing_when_the_build_predates_the_verb(self):
        self.use({"skillstate": [verb("command unavailable in player build: skillstate")]})
        result = skills.hs_skills_status(gate=lambda: RUNNING)
        self.assertEqual(result["reason"], "plugin_verb_missing", result)
        self.assertIn("predates", result["detail"])

    def test_an_unreadable_format_is_not_read_as_an_empty_bar(self):
        self.use({"skillstate": [verb("skillstate:", "  hello")]})
        result = skills.hs_skills_status(gate=lambda: RUNNING)
        self.assertEqual(result["reason"], "plugin_verb_missing", result)

    def test_no_game_is_refused_before_any_send(self):
        self.use({})
        result = skills.hs_skills_status(gate=lambda: NOT_RUNNING)
        self.assertEqual(result["reason"], "game_not_running", result)
        self.assertEqual(self.ipc.calls, [])


# --------------------------------------------------------------------------
# hs_skill_cast
# --------------------------------------------------------------------------

K1_OFF = as_skillstate(fx.SKILLPROBE_STATE_K1, {(0, 0): "0"})
K1_ON = as_skillstate(fx.SKILLPROBE_STATE_K1, {(0, 0): "1"})
Q = 81


class CastTests(SkillsBase):
    def assert_pressed_q(self):
        self.assertEqual(len(self.inject.calls), 1, self.inject.calls)
        call = self.inject.calls[0]
        self.assertEqual(call["actions"], [{"type": "key", "vk": Q, "hold_ms": 120}])
        self.assertEqual(call["route"], "send_input")
        self.assertTrue(call["force_focus"])
        self.assertTrue(call["lease_checked"])

    def use_cast(self, before, after=None, undelivered=False):
        """`skillstate` answers `before` until the key is pressed and `after`
        from then on, so the count moves because of the press and only then.
        Each send's clock time is kept in `self.sent_at`."""
        self.sent_at: list[float] = []

        def pressed(actions):
            if after is not None:
                self.ipc.script["skillstate"] = [after]

        self.use({"skillstate": [before]}, ScriptedInject(undelivered=undelivered, on_press=pressed))
        send = self.ipc.send

        def timed(lines, **kwargs):
            self.sent_at.append(self.clock.t)
            return send(lines, **kwargs)
        self.enterContext(patch.object(skills.ipc, "send", timed))

    def test_baseline_an_effect_count_that_never_moves_is_cast_not_confirmed(self):
        self.use_cast(K1_OFF)
        result = skills.hs_skill_cast(Q, slot="0,0", timeout_s=2, gate=lambda: RUNNING)
        self.assertEqual(result["reason"], "cast_not_confirmed", result)
        self.assert_pressed_q()
        self.assertIn("effect=0", result["proof"][0])
        self.assertEqual(result["effect_samples_before"], [0] * skills.PRE_PRESS_READS)
        self.assertGreater(len(self.ipc.calls), skills.PRE_PRESS_READS + 1)   # it did poll

    def test_target_an_effect_count_that_moves_is_confirmed(self):
        self.use_cast(K1_OFF, K1_ON)
        result = skills.hs_skill_cast(Q, slot="0,0", timeout_s=5, gate=lambda: RUNNING)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["confirmed"])
        self.assertEqual((result["effect_before"], result["effect_after"]), (0, 1))
        self.assertEqual(len(result["proof"]), 2)
        self.assertIn("effect=0", result["proof"][0])
        self.assertIn("effect=1", result["proof"][1])
        self.assert_pressed_q()
        self.assertEqual(result["injected"], [{"type": "key", "vk": Q, "hold_ms": 120}])
        # The count was flat without a press, and it moved after one.
        samples = result["effect_samples_before"]
        self.assertGreaterEqual(len(samples), 2)
        self.assertEqual(set(samples), {0})

    def test_the_pre_press_reads_span_at_least_two_polls(self):
        self.use_cast(K1_OFF, K1_ON)
        result = skills.hs_skill_cast(Q, slot="0,0", gate=lambda: RUNNING)
        self.assertTrue(result["confirmed"], result)
        pre = self.sent_at[:skills.PRE_PRESS_READS]
        self.assertGreaterEqual(len(pre), 2)
        self.assertGreaterEqual(pre[-1] - pre[0], 2 * skills.POLL_S)

    def test_proof_unstable_when_the_count_moves_with_no_press(self):
        # The count changes between the pre-press reads: whatever moves it,
        # it is not this cast, so no key is pressed and the samples are kept.
        self.use({"skillstate": [K1_OFF, K1_ON, K1_OFF]})
        result = skills.hs_skill_cast(Q, slot="0,0", gate=lambda: RUNNING)
        self.assertEqual(result["reason"], "proof_unstable", result)
        self.assertEqual(self.inject.calls, [])
        self.assertEqual(result["effect_samples_before"][:2], [0, 1])
        self.assertTrue(any("effect=0" in l for l in result["proof"]), result["proof"])
        self.assertTrue(any("effect=1" in l for l in result["proof"]), result["proof"])
        self.assertEqual(self.ipc.calls, ["skillstate"] * len(result["effect_samples_before"]))

    def test_proof_unstable_when_the_count_turns_unreadable_before_the_press(self):
        self.use({"skillstate": [K1_OFF, as_skillstate(fx.SKILLPROBE_STATE_K1, {(0, 0): "unreadable"})]})
        result = skills.hs_skill_cast(Q, slot="0,0", gate=lambda: RUNNING)
        self.assertEqual(result["reason"], "proof_unstable", result)
        self.assertEqual(self.inject.calls, [])

    def test_the_slot_can_be_named_by_its_ability(self):
        self.use_cast(K1_OFF, K1_ON)
        result = skills.hs_skill_cast(Q, ability="darkOath", gate=lambda: RUNNING)
        self.assertTrue(result["confirmed"], result)
        self.assertEqual(result["slot"], "0,0")

    def test_skill_not_on_bar_is_returned_before_any_key(self):
        self.use({"skillstate": [K1_OFF]})
        for kwargs in ({"slot": "0,1"},            # an empty slot (talent 0)
                       {"slot": "1,4"},            # row 1 is the owned list, not the bar
                       {"ability": "shadowBolt"}):  # learned, not on row 0
            with self.subTest(**kwargs):
                result = skills.hs_skill_cast(Q, gate=lambda: RUNNING, **kwargs)
                self.assertEqual(result["reason"], "skill_not_on_bar", result)
        self.assertEqual(self.inject.calls, [])

    def test_proof_unavailable_is_returned_before_any_key(self):
        # chainOfHolyLight at 0,2 has no kSkillTimerNames object: no effect=.
        self.use({"skillstate": [K1_OFF]})
        result = skills.hs_skill_cast(Q, slot="0,2", gate=lambda: RUNNING)
        self.assertEqual(result["reason"], "proof_unavailable", result)
        self.assertEqual(self.inject.calls, [])

    def test_key_not_delivered_is_returned_before_any_poll(self):
        self.use_cast(K1_OFF, K1_ON, undelivered=True)
        result = skills.hs_skill_cast(Q, slot="0,0", gate=lambda: RUNNING)
        self.assertEqual(result["reason"], "key_not_delivered", result)
        self.assertEqual(self.ipc.calls, ["skillstate"] * skills.PRE_PRESS_READS)

    def test_bad_arguments_are_refused_before_any_send(self):
        self.use({})
        for kwargs in ({"key": Q}, {"key": Q, "slot": "0,0", "ability": "darkOath"},
                       {"key": 0, "slot": "0,0"}, {"key": Q, "slot": "zero"}):
            with self.subTest(**kwargs):
                result = skills.hs_skill_cast(gate=lambda: RUNNING, **kwargs)
                self.assertEqual(result["reason"], "invalid_input", result)
        self.assertEqual(self.ipc.calls, [])


# --------------------------------------------------------------------------
# hs_talent_allocate
# --------------------------------------------------------------------------

RESET = as_skillstate(fx.SKILLPROBE_STATE_AFTER_RESET)       # mySkills=[236]
ALLOC = as_skillstate(fx.SKILLPROBE_STATE_AFTER_ALLOC)       # mySkills=[236,239], sub=239 s2=0
SUB = as_skillstate(fx.SKILLPROBE_STATE_AFTER_SUB)           # sub=239 s1=1 s2=0
SCREEN_QUERY = "menulayout UI_Talent_Screen_obj"


class AllocateBase(SkillsBase):
    def setUp(self):
        super().setUp()
        temp = tempfile.TemporaryDirectory(prefix="hs-drive-skills-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        live = root / "hs2saves"
        live.mkdir()
        (live / "herosiege14.hss").write_bytes(b"character")
        self.enterContext(patch.dict(os.environ, {"HS_DRIVE_SAVE_DIR": str(live),
                                                  "HS_DRIVE_BACKUP_DIR": str(root / "backups")}))
        made = saves.backup("live-3", gate=lambda: NOT_RUNNING)
        self.assertTrue(made["ok"], made)
        self.backup_id = made["backup_id"]
        self.created = saves._parse_utc(made["created_utc"])

    def allocate(self, talent_id=239, sub=None, started=None, backup_id=None):
        start = self.created + timedelta(minutes=1) if started is None else started
        return skills.hs_talent_allocate(talent_id, backup_id or self.backup_id, sub=sub,
                                         gate=lambda: RUNNING, pids=PIDS,
                                         start_reader=lambda pid: start)

    def screen(self, *listings):
        return {SCREEN_QUERY: list(listings)}


class AllocateTests(AllocateBase):
    def test_baseline_learned_unchanged_is_alloc_not_confirmed(self):
        self.use({"skillstate": [RESET, RESET],
                  "talentalloc 239": [verb("talentalloc: before=mySkills=[236] after=mySkills=[236]",
                                           "talentalloc: not confirmed - global.mySkills did not gain 239 "
                                           "(the game's own refusal, a talent with no free point to take, say)")],
                  **self.screen(fx.MENULAYOUT_TALENT_SCREEN_OPEN, fx.MENULAYOUT_TALENT_SCREEN_CLOSED)})
        result = self.allocate()
        self.assertEqual(result["reason"], "alloc_not_confirmed", result)
        self.assertEqual(result["proof"], ["global.mySkills=[236]", "global.mySkills=[236]"])
        self.assertEqual(result["verb_trail"][:3], ["skillstate", "talentalloc 239", "skillstate"])

    def test_target_learned_gains_the_id_is_confirmed_and_the_screen_closed(self):
        self.use({"skillstate": [RESET, ALLOC],
                  "talentalloc 239": [verb("talentalloc: before=mySkills=[236] after=mySkills=[236,239]",
                                           "talentalloc: confirmed - global.mySkills gained 239")],
                  **self.screen(fx.MENULAYOUT_TALENT_SCREEN_OPEN, fx.MENULAYOUT_TALENT_SCREEN_CLOSED)})
        result = self.allocate()
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["proof"], ["global.mySkills=[236]", "global.mySkills=[236,239]"])
        self.assertTrue(result["screen_closed"], result)
        self.assertEqual(result["verb_trail"], ["skillstate", "talentalloc 239", "skillstate",
                                                SCREEN_QUERY, SCREEN_QUERY])
        # T pressed once, between the two listings.
        self.assertEqual([c["actions"] for c in self.inject.calls],
                         [[{"type": "key", "vk": 84, "hold_ms": 120}]])

    def test_an_unreadable_baseline_is_never_confirmed(self):
        # An unreadable before-read is not an empty one: an id that was
        # already there must not "join" it. Positive control beside it:
        # the target test above, same after-read, readable baseline.
        unreadable = RESET.replace("global.mySkills=[236]", "global.mySkills=unreadable")
        self.use({"skillstate": [unreadable, ALLOC],
                  "talentalloc 239": [verb("talentalloc: refused - global.mySkills is unreadable")],
                  **self.screen(fx.MENULAYOUT_TALENT_SCREEN_CLOSED)})
        self.assertEqual(self.allocate()["reason"], "alloc_not_confirmed")
        unreadable_sub = ALLOC.replace("sub=239 s2=0", "sub=239 unreadable")
        self.use({"skillstate": [unreadable_sub, SUB],
                  "talentalloc 239 sub 2": [verb("talentalloc: before=sub=239 unreadable after=sub=239 s1=1 s2=0")],
                  **self.screen(fx.MENULAYOUT_TALENT_SCREEN_CLOSED)})
        self.assertEqual(self.allocate(sub=2)["reason"], "alloc_not_confirmed")

    def test_the_verbs_own_confirmation_is_not_trusted_over_the_re_read(self):
        self.use({"skillstate": [RESET, RESET],
                  "talentalloc 239": [verb("talentalloc: confirmed - global.mySkills gained 239")],
                  **self.screen(fx.MENULAYOUT_TALENT_SCREEN_CLOSED)})
        self.assertEqual(self.allocate()["reason"], "alloc_not_confirmed")

    def test_sub_baseline_and_target_on_the_sub_239_line(self):
        self.use({"skillstate": [ALLOC, ALLOC],
                  "talentalloc 239 sub 2": [verb("talentalloc: before=sub=239 s2=0 after=sub=239 s2=0")],
                  **self.screen(fx.MENULAYOUT_TALENT_SCREEN_CLOSED)})
        self.assertEqual(self.allocate(sub=2)["reason"], "alloc_not_confirmed")
        self.use({"skillstate": [ALLOC, SUB],
                  "talentalloc 239 sub 2": [verb("talentalloc: before=sub=239 s2=0 after=sub=239 s1=1 s2=0",
                                                 "talentalloc: confirmed - a node of sub=239 rose by one")],
                  **self.screen(fx.MENULAYOUT_TALENT_SCREEN_OPEN, fx.MENULAYOUT_TALENT_SCREEN_OPEN)})
        result = self.allocate(sub=2)
        self.assertTrue(result["confirmed"], result)
        self.assertEqual(result["proof"], ["sub=239 s2=0", "sub=239 s1=1 s2=0"])
        self.assertEqual(result["subtalents"]["239"], {"s1": 1, "s2": 0})
        # A screen that stays listed after T is reported, not refused.
        self.assertFalse(result["screen_closed"])
        self.assertIn("still listed", result["close_detail"])

    def test_talent_not_allocatable_from_the_verbs_refusal(self):
        for line in ("talentalloc: refused - 239 is already learned (global.mySkills=[236,239]; only a "
                     "first level is measured), not allocatable; nothing was called",
                     "talentalloc: refused - not allocatable (no UI_Button_Talent_Player_obj carries "
                     "talentId=239); nothing further was called"):
            with self.subTest(line=line[:40]):
                self.use({"skillstate": [RESET], "talentalloc 239": [verb(line)],
                          **self.screen(fx.MENULAYOUT_TALENT_SCREEN_CLOSED)})
                result = self.allocate()
                self.assertEqual(result["reason"], "talent_not_allocatable", result)
                # Never re-sent; the closed screen is not opened by a T press.
                self.assertEqual(self.ipc.calls.count("talentalloc 239"), 1)
                self.assertEqual(self.inject.calls, [])

    def test_a_screen_opened_by_this_call_is_sent_once_more(self):
        opened = ("talentalloc: refused - not allocatable (no UI_Button_Talent_Player_obj carries "
                  "talentId=239; the screen was opened by this call); nothing further was called")
        self.use({"skillstate": [RESET, ALLOC],
                  "talentalloc 239": [verb(opened),
                                      verb("talentalloc: before=mySkills=[236] after=mySkills=[236,239]",
                                           "talentalloc: confirmed - global.mySkills gained 239")],
                  **self.screen(fx.MENULAYOUT_TALENT_SCREEN_OPEN, fx.MENULAYOUT_TALENT_SCREEN_CLOSED)})
        result = self.allocate()
        self.assertTrue(result["confirmed"], result)
        self.assertEqual(self.ipc.calls.count("talentalloc 239"), 2)

    def test_talent_screen_not_open_from_the_verbs_refusal(self):
        self.use({"skillstate": [RESET],
                  "talentalloc 239": [verb("talentalloc: refused - screen not open (UiAOpenTalents ran, but "
                                           "no UI_Talent_Screen_obj is listed after it); nothing further was called")],
                  **self.screen(fx.MENULAYOUT_TALENT_SCREEN_CLOSED)})
        result = self.allocate()
        self.assertEqual(result["reason"], "talent_screen_not_open", result)

    def test_plugin_verb_missing_when_the_build_predates_talentalloc(self):
        self.use({"skillstate": [RESET],
                  "talentalloc 239": [verb("command unavailable in player build: talentalloc")]})
        result = self.allocate()
        self.assertEqual(result["reason"], "plugin_verb_missing", result)
        self.assertEqual(self.ipc.calls, ["skillstate", "talentalloc 239"])

    def test_no_session_backup_is_returned_before_any_send(self):
        self.use({})
        result = self.allocate(started=self.created - timedelta(minutes=1))
        self.assertEqual(result["reason"], "no_session_backup", result)
        self.assertEqual(result["verb_trail"], [])
        self.assertEqual(self.ipc.calls, [])

    def test_a_missing_backup_is_refused_before_any_send(self):
        self.use({})
        result = self.allocate(backup_id="no-such-backup")
        self.assertIn(result["reason"], ("invalid_backup_id", "backup_incomplete"), result)
        self.assertEqual((result["verb_trail"], self.ipc.calls), ([], []))

    def test_bad_arguments_are_refused_before_any_send(self):
        self.use({})
        for kwargs in ({"talent_id": 0}, {"talent_id": "239"}, {"talent_id": 239, "sub": 0}):
            with self.subTest(**kwargs):
                result = self.allocate(**kwargs)
                self.assertEqual(result["reason"], "invalid_input", result)
        self.assertEqual(self.ipc.calls, [])


# --------------------------------------------------------------------------
# Not measured: bind and reset
# --------------------------------------------------------------------------

class NotMeasuredTests(SkillsBase):
    def test_bind_and_reset_refuse_route_not_measured_with_nothing_sent(self):
        self.use({})
        for result in (skills.hs_skill_bind("0,6", "shadowBolt", "anything"),
                       skills.hs_talent_reset("anything")):
            with self.subTest(tool=result["tool"]):
                self.assertEqual(result["reason"], "route_not_measured", result)
                self.assertEqual(result["verb_trail"], [])
                self.assertIn("shape not reproduced", result["detail"])
                self.assertEqual(result["lease"], "none")
        self.assertEqual(self.ipc.calls, [])
        self.assertEqual(self.inject.calls, [])


class VocabularyTests(unittest.TestCase):
    def test_every_token_this_module_can_answer_is_in_the_vocabulary(self):
        for token in results.SKILL_REASONS + results.ACTION_REASONS:
            self.assertIn(token, results.REASONS)
        source = (ROOT / "tools" / "hs_drive_mcp" / "skills.py").read_text(encoding="utf-8")
        for token in results.SKILL_REASONS + ("plugin_verb_missing", "route_not_measured"):
            self.assertIn(f'"{token}"', source, token)


if __name__ == "__main__":
    unittest.main()
