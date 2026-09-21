"""`hs_select_character` -- the click sequence, the proof, and the refusals.

`hs_input.inject` and `ipc.send` are patched at module level with a scripted
fake plugin; nothing here starts a game, touches `%LOCALAPPDATA%`, or calls
the real Win32 input functions. `_sleep` (the one seam every wait in
`charselect.py` goes through -- the settle after a click, the blind-instrument
retry, the poll interval) is patched to a no-op that records what it was
asked to wait, so these tests finish in milliseconds regardless of `SETTLE_S`
or `timeout_s`.

S2 is the baseline (`AGENTS.md` § "Mod Development Workflow"): the game never
loads, so the tool has to time out having sent exactly the scripted commands
and nothing more -- a tool that keeps clicking a screen it cannot see is the
failure this pins. S3 is the target: the same fake, except the resolver
answers a route after the third click.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.hs_drive_mcp import capture, charselect, procs, results  # noqa: E402
from tools.hs_drive_mcp import input as input_module  # noqa: E402

HWND = 0x1234ABCD
PID = 4242
CLIENT_W, CLIENT_H = 1920, 1080

RUNNING = ("running", "1 hero_siege.exe process(es) are live: [4242].")
NOT_RUNNING = ("not_running", "the process snapshot returned 0 rows.")
UNKNOWN = ("unknown", "the Windows process snapshot could not be created.")

GEOMETRY = {"client_size": [CLIENT_W, CLIENT_H]}
WINDOW = {"hwnd": HWND, "pid": PID, "bbox": (0, 0, CLIENT_W, CLIENT_H),
         "area": CLIENT_W * CLIENT_H, "minimized": False}

#: `ForgePact/docs/character-select-research.md` C-1.15's measured client
#: points, computed here the same way `charselect.py` does (`round(fraction *
#: client dimension)`), so the assertions pin the formula rather than agree
#: with it. At CLIENT_W=1920, CLIENT_H=1080 these are (336, 534), (243, 225)
#: and (583, 346).
LOCAL_POINT = (round(charselect.FRACTION_LOCAL[0] * CLIENT_W),
              round(charselect.FRACTION_LOCAL[1] * CLIENT_H))
SLOT_POINT = (round(charselect.FRACTION_SLOT_1[0] * CLIENT_W),
             round(charselect.FRACTION_SLOT_1[1] * CLIENT_H))
PLAY_POINT = (round(charselect.FRACTION_PLAY[0] * CLIENT_W),
             round(charselect.FRACTION_PLAY[1] * CLIENT_H))

NOT_TRIED_LINE = ("orbpickup stat: globe objs=0 | seen=0 noplayer=0 "
                  "outofreach=0 uncacheable=0 pulled=0 | nearest=-1 px "
                  "(reach 64 px) | player via (not tried)")
NONE_LINE = ("orbpickup stat: globe objs=0 | seen=0 noplayer=0 outofreach=0 "
            "uncacheable=0 pulled=0 | nearest=-1 px (reach 64 px) | "
            "player via none")
GET_MY_PLAYER_LINE = ("orbpickup stat: globe objs=0 | seen=0 noplayer=0 "
                      "outofreach=0 uncacheable=0 pulled=0 | nearest=-1 px "
                      "(reach 64 px) | player via GetMyPlayer")
INSTANCE_FIND_LINE = ("orbpickup stat: globe objs=0 | seen=0 noplayer=0 "
                      "outofreach=0 uncacheable=0 pulled=0 | nearest=-1 px "
                      "(reach 64 px) | player via instance_find(Player_obj)")
ARM_ACK_LINE = ("orbpickup -> globes pulled from 64 px (player obj=1, "
                "globe objs=0, pulled=0)")
PING_REPLY = "pong (YYTK 4.0.1)"


class ScriptedIpc:
    """`ipc.send`, replaced. `script` maps a command line to a list of
    reply lines, consumed one at a time; once only one is left it repeats,
    which is what lets one script represent both "answers changed after the
    third click" (S3) and "this command's reply never changes" (S2's ping
    and its own steady-state `orbpickup stat`).

    `refusals` maps a command line to a one-shot `(reason, detail)`: the
    next call for that line is refused instead of scripted, and every call
    after that reads the script again.
    """

    def __init__(self, script, refusals=None):
        self.script = {line: list(replies) for line, replies in script.items()}
        self.refusals = dict(refusals or {})
        self.calls: list[str] = []

    def send(self, lines, *, tool="hs_command", **kwargs):
        line = lines[0]
        self.calls.append(line)
        if line in self.refusals:
            reason, detail = self.refusals.pop(line)
            return results.refuse(tool, reason, detail)
        queue = self.script[line]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        return results.ok(tool, sent=[line], reply=reply,
                          reply_lines=reply.splitlines(), consumed=True,
                          queued=False, wrote_bytes=len(reply))


class ScriptedInject:
    """`hs_input.inject`, replaced. Records every call; refuses the call at
    `refuse_at` (0-indexed among *click-carrying* calls) once, if set."""

    def __init__(self, refuse_at=None, refusal=("foreground_not_game",
                                                "test refusal")):
        self.calls: list[dict] = []
        self.refuse_at = refuse_at
        self.refusal = refusal

    def __call__(self, actions, *, route="send_input",
                require_foreground=True, tool="hs_input", **kwargs):
        index = len(self.calls)
        self.calls.append({"actions": actions, "route": route})
        if self.refuse_at is not None and index == self.refuse_at:
            reason, detail = self.refusal
            return results.refuse(tool, reason, detail)
        return results.ok(tool, actions_done=len(actions),
                          actions_total=len(actions), complete=True)


class ScriptedScreenshot:
    def __init__(self):
        self.labels: list[str] = []

    def __call__(self, *, target="game", label="", method="grab_bbox",
                tool="hs_screenshot", **kwargs):
        self.labels.append(label)
        return results.ok(tool, path=f"/fake/{label}.png", target=target)


class CharselectTestCase(unittest.TestCase):
    """One running game, one 1920x1080 client, every side effect scripted."""

    def arrange(self, *, game_state=RUNNING, geometry=GEOMETRY,
               ipc_script=None, ipc_refusals=None, inject_refuse_at=None):
        self.doCleanups()
        self.ipc = ScriptedIpc(ipc_script or {}, ipc_refusals)
        self.inject = ScriptedInject(refuse_at=inject_refuse_at)
        self.screenshot = ScriptedScreenshot()
        self.sleeps: list[float] = []
        self.saves_calls: list[tuple] = []

        self.enterContext(patch.object(procs, "gate", lambda: game_state))
        self.enterContext(patch.object(
            procs, "game_pids", lambda engine=None: [PID]))
        self.enterContext(patch.object(
            capture, "resolve_game_window", lambda pids, tool: dict(WINDOW)))
        self.enterContext(patch.object(
            input_module, "_geometry", lambda hwnd: (dict(geometry), "")))
        self.enterContext(patch.object(charselect.ipc, "send", self.ipc.send))
        self.enterContext(patch.object(
            charselect.input_module, "inject", self.inject))
        self.enterContext(patch.object(
            charselect.capture, "screenshot", self.screenshot))
        self.enterContext(patch.object(
            charselect, "_sleep", lambda seconds: self.sleeps.append(seconds)))

        from tools.hs_drive_mcp import saves
        self.enterContext(patch.object(
            saves, "backup",
            lambda *a, **k: self.saves_calls.append(("backup", a, k))))
        self.enterContext(patch.object(
            saves, "restore",
            lambda *a, **k: self.saves_calls.append(("restore", a, k))))

    def setUp(self):
        self.arrange()

    def call(self, **kwargs):
        return charselect.hs_select_character(**kwargs)


def baseline_script():
    """S2: the mod never sees a player, forever."""
    return {
        "ping": [PING_REPLY],
        "orbpickup stat": [NOT_TRIED_LINE, NONE_LINE],
        "orbpickup 1": [ARM_ACK_LINE],
        "orbpickup 0": ["orbpickup -> off"],
    }


def target_script(final_line=GET_MY_PLAYER_LINE):
    """S3: `none` at the menu, `local` and `slot`, a route right after `play`."""
    return {
        "ping": [PING_REPLY],
        "orbpickup stat": [NOT_TRIED_LINE, NONE_LINE, NONE_LINE, NONE_LINE,
                           final_line],
        "orbpickup 1": [ARM_ACK_LINE],
        "orbpickup 0": ["orbpickup -> off"],
    }


class HasRouteTests(unittest.TestCase):
    """`_has_route` is an allowlist of the routes `HhResolveLocalPlayer`
    actually writes, not `via not in (NONE_VIA, BLIND)` -- the shape the
    instrument-blindness review measured accepting a missing field as a
    resolved route."""

    def test_an_empty_via_is_not_a_route(self):
        self.assertFalse(charselect._has_route(""))

    def test_a_reply_with_no_player_via_field_parses_to_an_empty_via(self):
        via, globe_objs = charselect._parse_stat("orbpickup: usage")
        self.assertEqual(via, "")
        self.assertIsNone(globe_objs)
        self.assertFalse(charselect._has_route(via))

    def test_the_known_routes_are_routes(self):
        for route in charselect.KNOWN_ROUTES:
            self.assertTrue(charselect._has_route(route), route)

    def test_none_and_blind_are_not_routes(self):
        self.assertFalse(charselect._has_route(charselect.NONE_VIA))
        self.assertFalse(charselect._has_route(charselect.BLIND))


class BaselineTests(CharselectTestCase):
    """S2: the game never loads."""

    def test_a_never_loading_game_times_out_having_sent_exactly_the_script(self):
        self.arrange(ipc_script=baseline_script())
        report = self.call(slot=1, timeout_s=0.05)

        self.assertEqual(report["phase"], "timeout", report)
        self.assertEqual(len(self.inject.calls), 3,
                         "exactly three click calls: local, slot, play")
        for call in self.inject.calls:
            self.assertEqual(call["route"], "send_input")
            self.assertEqual(len(call["actions"]), 1)
            action = call["actions"][0]
            self.assertEqual(action["type"], "click")
            self.assertEqual(action["hold_ms"], 120,
                             "the hold is explicit, not the default")
        self.assertEqual(
            [(a["actions"][0]["x"], a["actions"][0]["y"])
             for a in self.inject.calls],
            [LOCAL_POINT, SLOT_POINT, PLAY_POINT])

        self.assertEqual(set(self.ipc.calls),
                         {"ping", "orbpickup stat", "orbpickup 1",
                          "orbpickup 0"})
        self.assertEqual(self.ipc.calls[0], "ping")
        self.assertEqual(self.ipc.calls[1], "orbpickup stat")
        self.assertEqual(self.ipc.calls[2], "orbpickup 1")
        self.assertEqual(self.ipc.calls[-1], "orbpickup 0")
        self.assertGreaterEqual(self.ipc.calls.count("orbpickup stat"), 2)

        self.assertEqual(report["orbpickup"], "restored_off")
        self.assertEqual(self.saves_calls, [],
                         "hs_select_character never touches saves")


class TargetTests(CharselectTestCase):
    """S3: the game loads, right after the third click."""

    def test_the_resolver_answering_after_play_is_a_character_loaded_result(self):
        self.arrange(ipc_script=target_script(GET_MY_PLAYER_LINE))
        report = self.call(slot=1, timeout_s=5)

        self.assertEqual(report["phase"], "character_loaded", report)
        self.assertEqual(report["proof"], GET_MY_PLAYER_LINE)
        self.assertEqual(
            [pair[0] for pair in report["proof_trail"]],
            ["main_menu", "local", "slot", "play"])
        for screen, line in report["proof_trail"][:3]:
            self.assertTrue(line.endswith("player via none"),
                            f"{screen}: {line}")
        self.assertTrue(report["proof_trail"][3][1]
                        .endswith("player via GetMyPlayer"))
        self.assertEqual(len(report["screenshots"]), 4)
        self.assertEqual(self.screenshot.labels,
                         ["main_menu", "local", "slot", "play"])
        self.assertEqual(report["orbpickup"], "restored_off")
        self.assertEqual(len(self.inject.calls), 3)

    def test_instance_find_player_obj_is_accepted_the_same_way(self):
        self.arrange(ipc_script=target_script(INSTANCE_FIND_LINE))
        report = self.call(slot=1, timeout_s=5)
        self.assertEqual(report["phase"], "character_loaded", report)
        self.assertEqual(report["proof"], INSTANCE_FIND_LINE)


class UnresolvedReadAfterPlayTests(CharselectTestCase):
    """The exact case the instrument-blindness review measured: a reply with
    no `player via ` field lands right where a resolved route would --
    after the third (Play) click -- and must not be mistaken for one."""

    def test_an_empty_reply_after_play_does_not_report_character_loaded(self):
        self.arrange(ipc_script=target_script(final_line=""))
        report = self.call(slot=1, timeout_s=0.05)

        self.assertNotEqual(report.get("phase"), "character_loaded", report)
        self.assertEqual(report["phase"], "timeout", report)


class RefusalTests(CharselectTestCase):
    """S4: every refusal happens before anything past it is sent."""

    def test_game_not_running_refuses_before_anything(self):
        self.arrange(game_state=NOT_RUNNING)
        report = self.call()
        self.assertEqual(report["reason"], "game_not_running", report)
        self.assertEqual(self.ipc.calls, [])
        self.assertEqual(self.inject.calls, [])

    def test_game_state_unknown_refuses_before_anything(self):
        self.arrange(game_state=UNKNOWN)
        report = self.call()
        self.assertEqual(report["reason"], "game_state_unknown", report)
        self.assertEqual(self.ipc.calls, [])

    def test_a_slot_other_than_one_refuses_before_any_command(self):
        self.arrange(ipc_script=baseline_script())
        report = self.call(slot=2)
        self.assertEqual(report["reason"], "layout_not_measured", report)
        self.assertIn("C-1.15", report["detail"])
        self.assertEqual(self.ipc.calls, [])
        self.assertEqual(self.inject.calls, [])

    def test_a_non_sixteen_by_nine_client_refuses_before_any_inject(self):
        self.arrange(ipc_script=baseline_script(),
                     geometry={"client_size": [1024, 768]})
        report = self.call()
        self.assertEqual(report["reason"], "layout_not_measured", report)
        self.assertIn("1024x768", report["detail"])
        self.assertEqual(self.ipc.calls, [])
        self.assertEqual(self.inject.calls, [])

    def test_ping_not_consumed_is_propagated(self):
        self.arrange(ipc_script=baseline_script(),
                     ipc_refusals={"ping": ("not_consumed", "no reply")})
        report = self.call()
        self.assertEqual(report["reason"], "not_consumed", report)
        self.assertEqual(self.ipc.calls, ["ping"])
        self.assertEqual(self.inject.calls, [])

    def test_an_unacknowledged_arm_refuses_proof_not_armed_before_any_click(self):
        script = baseline_script()
        script["orbpickup 1"] = ["nothing happened"]
        self.arrange(ipc_script=script)
        report = self.call()
        self.assertEqual(report["reason"], "proof_not_armed", report)
        self.assertEqual(self.inject.calls, [])

    def test_a_still_blind_instrument_after_two_reads_refuses_proof_not_armed(self):
        script = baseline_script()
        script["orbpickup stat"] = [NOT_TRIED_LINE, NOT_TRIED_LINE,
                                    NOT_TRIED_LINE]
        self.arrange(ipc_script=script)
        report = self.call()
        self.assertEqual(report["reason"], "proof_not_armed", report)
        self.assertIn("(not tried)", report["detail"])
        self.assertEqual(self.inject.calls, [])
        # The retry sleep is the observable proof the second read was really
        # spaced out, not fired back to back.
        self.assertIn(charselect.BLIND_RETRY_S, self.sleeps)

    def test_a_menu_read_missing_the_player_via_field_refuses_proof_not_armed(self):
        # An empty reply (or one cut off before the last field, or an
        # unrelated line landing in its place) must be treated the same as
        # the instrument-blind case, not silently accepted as the "none"
        # negative control.
        script = baseline_script()
        script["orbpickup stat"] = [NOT_TRIED_LINE, "", ""]
        self.arrange(ipc_script=script)
        report = self.call()
        self.assertEqual(report["reason"], "proof_not_armed", report)
        self.assertEqual(self.inject.calls, [])
        self.assertIn(charselect.BLIND_RETRY_S, self.sleeps)

    def test_a_route_already_at_the_menu_refuses_character_already_loaded(self):
        script = baseline_script()
        script["orbpickup stat"] = [NOT_TRIED_LINE, GET_MY_PLAYER_LINE]
        self.arrange(ipc_script=script)
        report = self.call()
        self.assertEqual(report["reason"], "character_already_loaded", report)
        self.assertEqual(self.inject.calls, [],
                         "no click is sent once a character already appears "
                         "loaded")
        self.assertEqual(report["orbpickup"], "restored_off",
                         "orbpickup is restored per the pre-arm rule even on "
                         "this refusal")


class RestoreRuleTests(CharselectTestCase):
    def test_a_pre_arm_read_with_globes_out_leaves_orbpickup_on(self):
        script = baseline_script()
        script["orbpickup stat"][0] = script["orbpickup stat"][0].replace(
            "globe objs=0", "globe objs=3")
        self.arrange(ipc_script=script)
        report = self.call(timeout_s=0.05)
        self.assertEqual(report["orbpickup"], "left_on", report)
        self.assertNotIn("orbpickup 0", self.ipc.calls)

    def test_a_pre_arm_read_with_no_globes_restores_orbpickup_off(self):
        self.arrange(ipc_script=baseline_script())
        report = self.call(timeout_s=0.05)
        self.assertEqual(report["orbpickup"], "restored_off", report)
        self.assertIn("orbpickup 0", self.ipc.calls)


class ProofAmbiguousTests(CharselectTestCase):
    """S5: a route on the slot screen stops the tool before Play."""

    def test_a_route_on_the_slot_screen_stops_before_play(self):
        script = baseline_script()
        script["orbpickup stat"] = [NOT_TRIED_LINE, NONE_LINE, NONE_LINE,
                                    GET_MY_PLAYER_LINE]
        self.arrange(ipc_script=script)
        report = self.call(timeout_s=5)

        self.assertEqual(report["phase"], "proof_ambiguous", report)
        self.assertEqual([pair[0] for pair in report["proof_trail"]],
                         ["main_menu", "local", "slot"])
        self.assertEqual(len(self.inject.calls), 2,
                         "local and slot only -- Play is never clicked")
        self.assertEqual(set(self.ipc.calls) - {"orbpickup 0"},
                         {"ping", "orbpickup stat", "orbpickup 1"})

    def test_the_restore_rule_holds_in_the_ambiguous_case_too(self):
        script = baseline_script()
        script["orbpickup stat"] = [NOT_TRIED_LINE.replace(
            "globe objs=0", "globe objs=2"), NONE_LINE, NONE_LINE,
            GET_MY_PLAYER_LINE]
        self.arrange(ipc_script=script)
        report = self.call(timeout_s=5)
        self.assertEqual(report["phase"], "proof_ambiguous", report)
        self.assertEqual(report["orbpickup"], "left_on")
        self.assertNotIn("orbpickup 0", self.ipc.calls)


class InjectRefusalTests(CharselectTestCase):
    def test_an_inject_refusal_propagates_with_actions_sent_so_far(self):
        self.arrange(ipc_script=baseline_script(), inject_refuse_at=1)
        report = self.call(timeout_s=5)
        self.assertEqual(report["reason"], "foreground_not_game", report)
        self.assertEqual(report["actions_sent"], 1,
                         "local succeeded; slot is the one that refused")
        self.assertEqual(len(self.inject.calls), 2)


if __name__ == "__main__":
    unittest.main()
