"""`hs_select_character` -- the click sequence, the proof, and the refusals.

`hs_input.inject` and `ipc.send` are patched at module level with a scripted
fake plugin; nothing here starts a game, touches `%LOCALAPPDATA%`, or calls
the real Win32 input functions. `_sleep` (the one seam every wait in
`charselect.py` goes through -- the listing polls, the blind-instrument
retry, the orbpickup poll interval) is patched to a no-op that records what
it was asked to wait, so these tests finish in milliseconds regardless of
the poll budgets or `timeout_s`. `_now` (the clock every deadline reads) is
left real except in `PlayTimeoutTests`, which drives it from the `_sleep`
double so navigation can be made to consume more than `timeout_s`.

The fake plugin answers `menulayout` with the three listings phase 0
captured from a running game, verbatim (`hs_drive_mcp_menulayout_fixtures`),
and which one it answers depends on how many clicks have landed: the main
menu before any, `Chose_rm` after `Play local`, the character panel after a
card. So every click point these tests see is a `win=` field a real game
printed, and a click the tool should not have sent changes what it reads
next -- the way the game would.

S2 is the baseline (`AGENTS.md` § "Mod Development Workflow"): the game never
loads, so the tool has to time out having sent exactly the scripted commands
and nothing more -- a tool that keeps clicking a screen it cannot see is the
failure this pins. S3 is the target: the same fake, except the resolver
answers a route after the third click.
"""
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.hs_drive_mcp import capture, charselect, layout, procs, results  # noqa: E402
from tools.hs_drive_mcp import input as input_module  # noqa: E402
from tests.hs_drive_mcp_menulayout_fixtures import (  # noqa: E402
    CHOSE_RM_REPLY, MAIN_MENU_REPLY, PANEL_REPLY)

HWND = 0x1234ABCD
PID = 4242
CLIENT_W, CLIENT_H = 1920, 1080

RUNNING = ("running", "1 hero_siege.exe process(es) are live: [4242].")
NOT_RUNNING = ("not_running", "the process snapshot returned 0 rows.")
UNKNOWN = ("unknown", "the Windows process snapshot could not be created.")

GEOMETRY = {"client_size": [CLIENT_W, CLIENT_H]}
WINDOW = {"hwnd": HWND, "pid": PID, "bbox": (0, 0, CLIENT_W, CLIENT_H),
         "area": CLIENT_W * CLIENT_H, "minimized": False}

#: The `win=` fields of the rows phase 0's listings carry for `Play local`,
#: slot 1, slot 2 and `PLAY`, copied from the fixture text by hand so the
#: assertions pin what the game printed rather than agree with the matcher.
LOCAL_POINT = (336, 534)
SLOT_1_POINT = (177, 174)
SLOT_2_POINT = (381, 174)
PLAY_POINT = (584, 345)

#: What the fake plugin lists after 0, 1 and 2+ clicks.
SCREENS = (MAIN_MENU_REPLY, CHOSE_RM_REPLY, PANEL_REPLY)

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

#: `orbpickup 1`'s reply exactly as `ipc.send` returned it from a running
#: game at the L-1 live gate (2026-09-21, player build `24020eac`) -- the
#: reply the tool refused `proof_not_armed` on, because the handler's line
#: arrives framed and the framing was never part of any fixture above.
LIVE_ARM_REPLY = ("---- running command file ----\r\n"
                  "orbpickup -> globes pulled from 480 px (player obj=3553, "
                  "globe objs=2, pulled every frame, found by a scan at most "
                  "every 15 frames)\r\n"
                  "---- done ----\r\n")


def framed(line):
    """Wrap one handler line the way the plugin writes every command's
    output to `out.txt` (`LIVE_ARM_REPLY`), which is what `ipc.send`
    returns as `reply`. A double that hands back the bare line cannot
    represent the input L-1 failed on."""
    return f"---- running command file ----\r\n{line}\r\n---- done ----\r\n"


class ScriptedIpc:
    """`ipc.send`, replaced. `script` maps a command line to a list of
    handler lines, consumed one at a time and returned `framed` as the real
    plugin frames them (a script entry that is already framed, such as
    `LIVE_ARM_REPLY`, is returned verbatim); once only one is left it repeats,
    which is what lets one script represent both "answers changed after the
    third click" (S3) and "this command's reply never changes" (S2's ping
    and its own steady-state `orbpickup stat`).

    `refusals` maps a command line to a one-shot `(reason, detail)`: the
    next call for that line is refused instead of scripted, and every call
    after that reads the script again.

    A script entry may instead be a callable taking no arguments: its return
    value is the reply, every time. That is how `menulayout` answers with
    whichever screen the clicks so far have reached.

    `order`, if given, is a list shared with `ScriptedInject`: every call
    appends `("ipc", line)` to it, so a test can recover the interleaving of
    `menulayout` reads and clicks that `self.calls` and `self.inject.calls`
    alone cannot (`WindowSettleTests`).
    """

    def __init__(self, script, refusals=None, order=None):
        self.script = {line: (replies if callable(replies) else list(replies))
                       for line, replies in script.items()}
        self.refusals = dict(refusals or {})
        self.calls: list[str] = []
        self.order = order

    def send(self, lines, *, tool="hs_command", **kwargs):
        line = lines[0]
        self.calls.append(line)
        if self.order is not None:
            self.order.append(("ipc", line))
        if line in self.refusals:
            reason, detail = self.refusals.pop(line)
            return results.refuse(tool, reason, detail)
        queue = self.script[line]
        if callable(queue):
            reply = queue()
        else:
            reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if not reply.startswith("---- running command file ----"):
            reply = framed(reply)
        return results.ok(tool, sent=[line], reply=reply,
                          reply_lines=reply.splitlines(), consumed=True,
                          queued=False, wrote_bytes=len(reply))


#: `focus_via` for each landed `ScriptedInject` call, in call order (0-indexed
#: among click-carrying calls, the same indexing `refuse_at` uses); the last
#: entry repeats once exhausted, the same convention `ScriptedIpc` uses.
DEFAULT_FOCUS_VIA = ("already_foreground",)


class ScriptedInject:
    """`hs_input.inject`, replaced. Records every call, including
    `force_focus`; refuses the call at `refuse_at` (0-indexed among
    *click-carrying* calls) once, if set; answers the call at
    `undelivered_at` with `ok: true` but `complete: false` and every record
    rejected -- the shape the real `inject` returns when `SendInput` accepts
    the call and UIPI drops its records -- and does not count it as landed,
    since the game never saw it; answers `focus_via` from
    `focus_via_sequence`."""

    def __init__(self, refuse_at=None, refusal=("foreground_not_game",
                                                "test refusal"), order=None,
                focus_via_sequence=DEFAULT_FOCUS_VIA, undelivered_at=None):
        self.calls: list[dict] = []
        self.landed = 0
        self.refuse_at = refuse_at
        self.undelivered_at = undelivered_at
        self.refusal = refusal
        self.order = order
        self.focus_via_sequence = list(focus_via_sequence)

    def __call__(self, actions, *, route="send_input",
                require_foreground=True, force_focus=False,
                tool="hs_input", **kwargs):
        index = len(self.calls)
        self.calls.append({"actions": actions, "route": route,
                           "force_focus": force_focus})
        if self.order is not None:
            self.order.append(("inject", index))
        if self.refuse_at is not None and index == self.refuse_at:
            reason, detail = self.refusal
            return results.refuse(tool, reason, detail)
        focus_via = (self.focus_via_sequence.pop(0)
                    if len(self.focus_via_sequence) > 1
                    else self.focus_via_sequence[0])
        if self.undelivered_at is not None and index == self.undelivered_at:
            return results.ok(
                tool, actions_done=len(actions), actions_total=len(actions),
                records_sent=2, records_rejected=2, complete=False,
                focus_via=focus_via,
                detail=("1 of 1 action(s) sent to hwnd 1 via send_input. "
                        "SendInput rejected 2 of 2 record(s); the events "
                        "that carried them did not reach the game."))
        self.landed += 1
        return results.ok(tool, actions_done=len(actions),
                          actions_total=len(actions), records_sent=2,
                          records_rejected=0, complete=True,
                          focus_via=focus_via)

    def points(self):
        return [(c["actions"][0]["x"], c["actions"][0]["y"])
                for c in self.calls]


class ScriptedScreenshot:
    def __init__(self):
        self.labels: list[str] = []

    def __call__(self, *, target="game", label="", method="grab_bbox",
                tool="hs_screenshot", **kwargs):
        self.labels.append(label)
        return results.ok(tool, path=f"/fake/{label}.png", target=target)


class CharselectTestCase(unittest.TestCase):
    """One running game, one 1920x1080 client, every side effect scripted."""

    @staticmethod
    def _geometry_fn(geometry):
        """`_geometry`, replaced. `geometry` is a single `{"client_size":
        [...]}` dict -- the original, one-size-for-every-read behaviour --
        or a sequence of them, consumed one per call the same way
        `ScriptedIpc` consumes a scripted command's replies: the next value
        each call, and the last one repeating once only one is left. The
        call-start check consumes the first value, so a sequence models
        "the window was still N at launch and settled to M by the time the
        listing was read" (`WindowSettleTests`)."""
        values = [geometry] if isinstance(geometry, dict) else list(geometry)
        def _geometry(hwnd):
            value = values.pop(0) if len(values) > 1 else values[0]
            return dict(value), ""
        return _geometry

    def arrange(self, *, game_state=RUNNING, geometry=GEOMETRY,
               ipc_script=None, ipc_refusals=None, inject_refuse_at=None,
               screens=SCREENS, inject_undelivered_at=None):
        """`screens[n]` is what `menulayout` lists once `n` clicks have
        landed (the last one repeats), unless `ipc_script` scripts
        `menulayout` itself."""
        self.doCleanups()
        self.order: list[tuple[str, Any]] = []
        self.inject = ScriptedInject(refuse_at=inject_refuse_at,
                                     order=self.order,
                                     undelivered_at=inject_undelivered_at)
        script = dict(ipc_script or {})
        script.setdefault("menulayout", lambda: screens[
            min(self.inject.landed, len(screens) - 1)])
        self.ipc = ScriptedIpc(script, ipc_refusals, order=self.order)
        self.screenshot = ScriptedScreenshot()
        self.sleeps: list[float] = []
        self.saves_calls: list[tuple] = []

        self.enterContext(patch.object(procs, "gate", lambda: game_state))
        self.enterContext(patch.object(
            procs, "game_pids", lambda engine=None: [PID]))
        self.enterContext(patch.object(
            capture, "resolve_game_window", lambda pids, tool: dict(WINDOW)))
        self.enterContext(patch.object(
            input_module, "_geometry", self._geometry_fn(geometry)))
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
        self.assertEqual(self.inject.points(),
                         [LOCAL_POINT, SLOT_1_POINT, PLAY_POINT])

        self.assertEqual(set(self.ipc.calls),
                         {"ping", "orbpickup stat", "orbpickup 1",
                          "orbpickup 0", "menulayout"})
        self.assertEqual(self.ipc.calls.count("menulayout"), 3,
                         "one read per screen: each target was listed on "
                         "the first poll")
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
        self.assertEqual(
            report["layout_trail"],
            [{"screen": "local", "obj": "UI_Button_obj", "id": 257029,
              "win": [336, 534], "text": "Play local"},
             {"screen": "slot", "obj": "Choose_Parent_obj", "id": 257048,
              "win": [177, 174], "text": ""},
             {"screen": "play", "obj": "UI_Button_obj", "id": 257591,
              "win": [584, 345], "text": "Play"}])

    def test_instance_find_player_obj_is_accepted_the_same_way(self):
        self.arrange(ipc_script=target_script(INSTANCE_FIND_LINE))
        report = self.call(slot=1, timeout_s=5)
        self.assertEqual(report["phase"], "character_loaded", report)
        self.assertEqual(report["proof"], INSTANCE_FIND_LINE)


class FramedReplyTests(CharselectTestCase):
    """The replies a real game sends: the handler's line between the
    plugin's own framing lines. L-1 refused `proof_not_armed` on exactly
    `LIVE_ARM_REPLY`; the same framing, parsed as one line, would also have
    made every `player via` read a route plus `---- done ----`, and so never
    a route."""

    def test_the_live_arm_reply_is_an_acknowledgement(self):
        script = target_script(GET_MY_PLAYER_LINE)
        script["orbpickup 1"] = [LIVE_ARM_REPLY]
        self.arrange(ipc_script=script)
        report = self.call(slot=1, timeout_s=5)

        self.assertEqual(report["phase"], "character_loaded", report)
        self.assertEqual(report["proof"], GET_MY_PLAYER_LINE)
        for _screen, line in report["proof_trail"]:
            self.assertNotIn("----", line)

    def test_framing_with_no_acknowledgement_line_is_not_armed(self):
        script = baseline_script()
        script["orbpickup 1"] = [framed("orbpickup: usage")]
        self.arrange(ipc_script=script)
        report = self.call()
        self.assertEqual(report["reason"], "proof_not_armed", report)
        self.assertEqual(self.inject.calls, [])

    def test_a_framed_stat_line_parses_to_the_bare_route(self):
        line = charselect._reply_line(
            {"reply": framed(GET_MY_PLAYER_LINE)}, charselect.STAT_PREFIX)
        self.assertEqual(line, GET_MY_PLAYER_LINE)
        self.assertEqual(charselect._parse_stat(line)[0], "GetMyPlayer")


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

    def test_a_listing_for_another_window_size_refuses_before_any_click(self):
        # The live listings say window=1920x1080; this client measures
        # 2560x1440 on every read, so it never settles: the poll budget
        # runs out on a mismatch every time, not just the call-start read.
        self.arrange(ipc_script=baseline_script(),
                     geometry={"client_size": [2560, 1440]})
        report = self.call()
        self.assertEqual(report["reason"], "window_size_mismatch", report)
        self.assertIn("1920x1080", report["detail"])
        self.assertIn("2560x1440", report["detail"])
        self.assertIn("room=Main_Menu_rm", report["detail"])
        self.assertEqual(self.inject.calls, [])
        self.assertEqual(self.ipc.calls.count("menulayout"),
                         charselect.LAYOUT_POLL_ATTEMPTS)
        self.assertEqual(report["orbpickup"], "restored_off")

    def test_an_older_plugin_refuses_layout_command_missing_before_any_click(self):
        script = baseline_script()
        script["menulayout"] = [
            "command unavailable in player build: menulayout"]
        self.arrange(ipc_script=script)
        report = self.call()
        self.assertEqual(report["reason"], "layout_command_missing", report)
        self.assertIn("command unavailable in player build: menulayout",
                      report["detail"])
        self.assertEqual(self.inject.calls, [])
        self.assertEqual(report["orbpickup"], "restored_off")

    def test_a_reply_with_no_listing_header_is_layout_command_missing(self):
        script = baseline_script()
        script["menulayout"] = ["unknown command"]
        self.arrange(ipc_script=script)
        report = self.call()
        self.assertEqual(report["reason"], "layout_command_missing", report)
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


class WindowSettleTests(CharselectTestCase):
    """The defect this workorder fixes: `hs_launch` returns `plugin_ready`
    before the game window necessarily reaches its configured size, so the
    client measured once at the top of the call can be stale by the time a
    listing is read. Every listing check now re-measures the client at that
    same read, and a disagreement alone is "not settled yet" -- it keeps
    polling within the existing budget rather than refusing at once. The
    negative control (fe9ef17's single call-start measurement) is expected
    to fail these tests: see the acceptance criteria's negative-control
    step."""

    def test_a_resized_window_settles_by_the_first_listing_read(self):
        # The call-start read (stale) sees 1024x576; every listing read
        # after it -- main menu included -- already sees the settled
        # 1920x1080 the live listings report, so nothing is ever refused.
        self.arrange(ipc_script=target_script(),
                     geometry=[{"client_size": [1024, 576]},
                              {"client_size": [1920, 1080]}])
        report = self.call(slot=1, timeout_s=5)
        self.assertEqual(report["phase"], "character_loaded", report)
        self.assertNotIn("reason", report)
        self.assertEqual(self.inject.points(),
                         [LOCAL_POINT, SLOT_1_POINT, PLAY_POINT])

    def test_a_resizing_window_settles_mid_poll_before_the_first_click(self):
        # The call-start read and the main menu's first two listing reads
        # all still see 1024x576 (mismatched); the third listing read sees
        # 1920x1080 and the poll accepts it -- exercising the settle poll
        # itself, not just a single stale-then-fresh pair.
        self.arrange(ipc_script=target_script(),
                     geometry=[{"client_size": [1024, 576]},
                              {"client_size": [1024, 576]},
                              {"client_size": [1024, 576]},
                              {"client_size": [1920, 1080]}])
        report = self.call(slot=1, timeout_s=5)
        self.assertEqual(report["phase"], "character_loaded", report)
        self.assertNotIn("reason", report)
        self.assertEqual(self.inject.points(),
                         [LOCAL_POINT, SLOT_1_POINT, PLAY_POINT])

        first_inject_at = next(i for i, (kind, _) in enumerate(self.order)
                               if kind == "inject")
        menulayout_before_first_click = sum(
            1 for kind, value in self.order[:first_inject_at]
            if kind == "ipc" and value == "menulayout")
        self.assertGreater(menulayout_before_first_click, 1,
                           "the settle poll itself was exercised: more than "
                           "one menulayout read happened before any click")

    def test_a_window_that_agrees_only_through_local_then_never_settles_again(self):
        # The main menu's own read agrees (Play local is clicked), but
        # every listing read after that click -- while waiting for the
        # save-slot screen -- measures a client the listing never agrees
        # with again. Unlike a persistent mismatch from the very start,
        # this proves the fix re-measures at *each* read rather than
        # trusting the first agreement for the rest of the call.
        self.arrange(ipc_script=baseline_script(),
                     geometry=[{"client_size": [1920, 1080]},
                              {"client_size": [1920, 1080]},
                              {"client_size": [1024, 576]}])
        report = self.call()
        self.assertEqual(report["reason"], "window_size_mismatch", report)
        self.assertEqual(report["actions_sent"], 1,
                         "Play local landed; nothing after it did")
        self.assertEqual(len(self.inject.calls), 1,
                         "no second click was ever sent")


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
                         {"ping", "orbpickup stat", "orbpickup 1",
                          "menulayout"})
        self.assertEqual(self.inject.points(), [LOCAL_POINT, SLOT_1_POINT])

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


def one_card_listing():
    """Phase 0's `Chose_rm` listing with every card row but slot 1's
    removed: a page holding one save."""
    kept = [line for line in CHOSE_RM_REPLY.split("\r\n")
            if "obj=Choose_Parent_obj" not in line or " slot=1 text=" in line]
    return "\r\n".join(kept)


class ListedPointTests(CharselectTestCase):
    """Every click lands on a `win=` field the game printed, verbatim."""

    def test_every_click_is_the_win_field_of_the_row_the_matcher_chose(self):
        self.arrange(ipc_script=target_script())
        report = self.call(slot=1, timeout_s=5)
        self.assertEqual(report["phase"], "character_loaded", report)
        chosen = [
            layout.match_play_local(layout.parse({"reply": MAIN_MENU_REPLY})),
            layout.match_slot(layout.parse({"reply": CHOSE_RM_REPLY}), 1),
            layout.match_play(layout.parse({"reply": PANEL_REPLY})),
        ]
        self.assertEqual(self.inject.points(),
                         [tuple(row.win) for row in chosen])
        self.assertEqual(self.inject.points(),
                         [LOCAL_POINT, SLOT_1_POINT, PLAY_POINT])
        for point, trail in zip(self.inject.points(), report["layout_trail"]):
            self.assertEqual(list(point), trail["win"])

    def test_slot_2_clicks_the_card_right_of_slot_1(self):
        self.arrange(ipc_script=target_script())
        report = self.call(slot=2, timeout_s=5)
        self.assertEqual(report["phase"], "character_loaded", report)
        self.assertEqual(self.inject.points(),
                         [LOCAL_POINT, SLOT_2_POINT, PLAY_POINT])
        slot_row = report["layout_trail"][1]
        self.assertEqual(slot_row["win"], list(SLOT_2_POINT))
        self.assertGreater(slot_row["win"][0], SLOT_1_POINT[0])
        self.assertEqual(slot_row["win"][1], SLOT_1_POINT[1])

    def test_a_client_of_any_shape_is_fine_when_the_listing_agrees(self):
        # No aspect-ratio rule any more: the listing's own window= is the
        # check. A 1024x768 client whose listing says 1024x768 proceeds.
        screens = tuple(text.replace("window=1920x1080", "window=1024x768")
                        for text in SCREENS)
        self.arrange(ipc_script=target_script(),
                     geometry={"client_size": [1024, 768]}, screens=screens)
        report = self.call(slot=1, timeout_s=5)
        self.assertEqual(report["phase"], "character_loaded", report)


class ListingRefusalTests(CharselectTestCase):
    """A button the listing does not carry is refused, never guessed."""

    def test_no_play_local_on_the_main_menu_refuses_before_any_click(self):
        text = MAIN_MENU_REPLY.replace("text=Play local", "text=Play elsewhere")
        self.arrange(ipc_script=baseline_script(), screens=(text,))
        report = self.call()
        self.assertEqual(report["reason"], "button_not_found", report)
        self.assertIn("Play local", report["detail"])
        self.assertIn("room=Main_Menu_rm", report["detail"])
        self.assertEqual(self.inject.calls, [])
        self.assertEqual(report["orbpickup"], "restored_off")

    def test_a_slot_screen_that_never_appears_refuses_button_not_found(self):
        # The main menu keeps being listed after the Play local click: the
        # poll budget runs out, the last listing is quoted, and no second
        # click is sent.
        self.arrange(ipc_script=baseline_script(),
                     screens=(MAIN_MENU_REPLY,))
        report = self.call()
        self.assertEqual(report["reason"], "button_not_found", report)
        self.assertEqual(report["phase"], "local")
        self.assertIn("room=Main_Menu_rm", report["detail"])
        self.assertEqual(report["last_listing"][0],
                         MAIN_MENU_REPLY.splitlines()[1])
        self.assertEqual(self.inject.points(), [LOCAL_POINT])
        self.assertEqual(self.ipc.calls.count("menulayout"),
                         1 + charselect.LAYOUT_POLL_ATTEMPTS)
        self.assertEqual(self.sleeps.count(charselect.LAYOUT_POLL_S),
                         charselect.LAYOUT_POLL_ATTEMPTS)

    def test_a_play_button_that_never_appears_refuses_button_not_found(self):
        self.arrange(ipc_script=baseline_script(),
                     screens=(MAIN_MENU_REPLY, CHOSE_RM_REPLY))
        report = self.call()
        self.assertEqual(report["reason"], "button_not_found", report)
        self.assertEqual(report["phase"], "slot")
        self.assertIn("Play", report["detail"])
        self.assertEqual(self.inject.points(), [LOCAL_POINT, SLOT_1_POINT])
        self.assertEqual([row["screen"] for row in report["layout_trail"]],
                         ["local", "slot"])

    def test_a_slot_beyond_the_listed_cards_refuses_slot_not_listed(self):
        self.arrange(ipc_script=baseline_script())
        report = self.call(slot=99)
        self.assertEqual(report["reason"], "slot_not_listed", report)
        self.assertIn("24", report["detail"])
        self.assertEqual(self.inject.points(), [LOCAL_POINT],
                         "Play local only -- no card is guessed")
        self.assertEqual(report["orbpickup"], "restored_off")

    def test_a_short_page_is_not_refused_on_one_read(self):
        # The screen may still be filling in: one read listing fewer cards
        # than `slot` is polled again, and slot 2 is clicked once listed.
        # Only the same short count read twice running is `slot_not_listed`.
        slot_screens = iter([one_card_listing()])

        def listing():
            if self.inject.landed == 0:
                return MAIN_MENU_REPLY
            if self.inject.landed >= 2:
                return PANEL_REPLY
            return next(slot_screens, CHOSE_RM_REPLY)

        script = target_script()
        script["menulayout"] = listing
        self.arrange(ipc_script=script)
        report = self.call(slot=2, timeout_s=5)
        self.assertEqual(report["phase"], "character_loaded", report)
        self.assertEqual(self.inject.points()[1], SLOT_2_POINT)

    def test_a_page_that_stays_short_refuses_slot_not_listed(self):
        self.arrange(ipc_script=baseline_script(),
                     screens=(MAIN_MENU_REPLY, one_card_listing()))
        report = self.call(slot=2)
        self.assertEqual(report["reason"], "slot_not_listed", report)
        self.assertIn("1 visible", report["detail"])
        self.assertEqual(self.inject.points(), [LOCAL_POINT])
        self.assertEqual(self.ipc.calls.count("menulayout"), 3,
                         "the main menu, then the same short page twice")


class InjectRefusalTests(CharselectTestCase):
    def test_an_inject_refusal_propagates_with_actions_sent_so_far(self):
        self.arrange(ipc_script=baseline_script(), inject_refuse_at=1)
        report = self.call(timeout_s=5)
        self.assertEqual(report["reason"], "foreground_not_game", report)
        self.assertEqual(report["actions_sent"], 1,
                         "local succeeded; slot is the one that refused")
        self.assertEqual(len(self.inject.calls), 2)


class UndeliveredClickTests(CharselectTestCase):
    """PR #122 review: `inject` answering `ok: true` with records rejected
    (UIPI dropping `SendInput` records) is a click that never reached the
    game. It must refuse `click_not_delivered` at that click -- not be
    counted in `actions_sent` or `layout_trail`, and not surface one screen
    later as a `button_not_found` that points at the listing."""

    def test_a_click_with_rejected_records_refuses_click_not_delivered(self):
        self.arrange(ipc_script=baseline_script(), inject_undelivered_at=1)
        report = self.call(timeout_s=5)
        self.assertTrue(results.is_refusal(report), report)
        self.assertEqual(report["reason"], "click_not_delivered", report)
        self.assertEqual(report["phase"], "slot", report)
        self.assertEqual(report["actions_sent"], 1,
                         "only the local click landed; the slot click did not")
        self.assertEqual([row["screen"] for row in report["layout_trail"]],
                         ["local"])
        self.assertEqual(len(self.inject.calls), 2,
                         "nothing is clicked after an undelivered click")
        self.assertIn("records_rejected=2", report["detail"])
        self.assertIn("did not reach the game", report["detail"])
        self.assertEqual(report["orbpickup"], "restored_off",
                         "the restore rule still applies on this refusal")

    def test_an_undelivered_first_click_sends_nothing_further(self):
        self.arrange(ipc_script=baseline_script(), inject_undelivered_at=0)
        report = self.call(timeout_s=5)
        self.assertEqual(report["reason"], "click_not_delivered", report)
        self.assertEqual(report["phase"], "local", report)
        self.assertEqual(report["actions_sent"], 0)
        self.assertEqual(report["layout_trail"], [])
        self.assertEqual(len(self.inject.calls), 1)

    def test_the_token_is_a_registered_refusal(self):
        self.assertIn("click_not_delivered", results.SELECT_CHARACTER_REASONS)


class PlayTimeoutTests(CharselectTestCase):
    """PR #122 review: `timeout_s` counts from the `Play` click, as
    `server.py` documents, not from the call's start. The clock here is
    advanced only by `_sleep`, so navigation (the blind-instrument retry and
    the post-click listing polls) consumes simulated time exceeding
    `timeout_s` before `Play` is clicked."""

    def arrange_clock(self):
        self.clock = [1000.0]
        self.play_sleeps: list[float] = []

        def sleep(seconds):
            self.sleeps.append(seconds)
            self.clock[0] += seconds

        self.enterContext(patch.object(charselect, "_now",
                                       lambda: self.clock[0]))
        self.enterContext(patch.object(charselect, "_sleep", sleep))
        # Slow listing polls, so the three screens' navigation alone (plus
        # the blind retry) outlasts the timeout_s these tests pass.
        self.enterContext(patch.object(charselect, "LAYOUT_POLL_S", 2.0))

    def test_navigation_longer_than_timeout_s_still_polls_for_the_load(self):
        # pre-arm (not tried), menu (not tried -> blind retry, 1 s), menu
        # again (none), local (none), slot (none), then after Play: none on
        # the first read and a route on the second.
        script = {
            "ping": [PING_REPLY],
            "orbpickup stat": [NOT_TRIED_LINE, NOT_TRIED_LINE, NONE_LINE,
                               NONE_LINE, NONE_LINE, NONE_LINE,
                               GET_MY_PLAYER_LINE],
            "orbpickup 1": [ARM_ACK_LINE],
            "orbpickup 0": ["orbpickup -> off"],
        }
        self.arrange(ipc_script=script)
        self.arrange_clock()
        timeout_s = 2.5
        report = self.call(slot=1, timeout_s=timeout_s)

        play_at = len(self.sleeps) - 2
        navigation = sum(self.sleeps[:play_at])
        self.assertGreater(navigation, timeout_s,
                           "the fixture must spend more than timeout_s "
                           "before Play for this test to mean anything")
        self.assertEqual(report["phase"], "character_loaded", report)
        self.assertEqual(report["proof"], GET_MY_PLAYER_LINE)
        self.assertEqual(self.sleeps[play_at:],
                         [charselect.POLL_INTERVAL_S,
                          timeout_s - charselect.POLL_INTERVAL_S],
                         "after Play the whole timeout_s is available: one "
                         "full poll interval, then the rest of the budget")

    def test_the_timeout_after_play_waits_out_timeout_s_from_the_click(self):
        self.arrange(ipc_script=baseline_script())
        self.arrange_clock()
        timeout_s = 5.0
        report = self.call(slot=1, timeout_s=timeout_s)
        self.assertEqual(report["phase"], "timeout", report)
        # Every sleep after the third click belongs to the Play poll; they
        # add up to exactly timeout_s whatever navigation consumed.
        clicks = [i for i, entry in enumerate(self.order)
                  if entry[0] == "inject"]
        self.assertEqual(len(clicks), 3)
        stat_reads_after_play = sum(
            1 for entry in self.order[clicks[-1]:]
            if entry == ("ipc", "orbpickup stat"))
        post_play = self.sleeps[-stat_reads_after_play:]
        self.assertAlmostEqual(sum(post_play), timeout_s)
        self.assertGreater(stat_reads_after_play, 1,
                           "a budget spent by navigation would allow only "
                           "one zero-wait read")


class FocusTrailTests(CharselectTestCase):
    """`hs-drive-mcp-force-focus`: every click escalates focus, and the
    step that took is reported per click."""

    def test_every_click_carries_force_focus(self):
        self.arrange(ipc_script=target_script())
        report = self.call(slot=1, timeout_s=5)
        self.assertEqual(report["phase"], "character_loaded", report)
        self.assertEqual(len(self.inject.calls), 3)
        for call in self.inject.calls:
            self.assertTrue(call["force_focus"], call)

    def test_a_successful_run_reports_a_three_row_focus_trail(self):
        self.arrange(ipc_script=target_script())
        report = self.call(slot=1, timeout_s=5)
        self.assertEqual(report["phase"], "character_loaded", report)
        self.assertEqual([row["screen"] for row in report["focus_trail"]],
                         ["local", "slot", "play"])
        for row in report["focus_trail"]:
            self.assertIn("focus_via", row)

    def test_the_focus_via_of_each_click_is_carried_through(self):
        self.arrange(ipc_script=target_script())
        self.inject.focus_via_sequence = ["set_foreground",
                                          "attach_thread_input",
                                          "input_unlock"]
        report = self.call(slot=1, timeout_s=5)
        self.assertEqual(report["phase"], "character_loaded", report)
        self.assertEqual([row["focus_via"] for row in report["focus_trail"]],
                         ["set_foreground", "attach_thread_input",
                          "input_unlock"])

    def test_a_refusal_also_carries_a_focus_trail(self):
        self.arrange(ipc_script=baseline_script(), inject_refuse_at=1)
        report = self.call(timeout_s=5)
        self.assertEqual(report["reason"], "foreground_not_game", report)
        self.assertEqual([row["screen"] for row in report["focus_trail"]],
                         ["local"], "the one click that landed before the "
                         "refusal")


if __name__ == "__main__":
    unittest.main()
