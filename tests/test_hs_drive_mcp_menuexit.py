"""`hs_exit_to_menu` -- Escape, the pause menu's Exit row, and the refusals.

`ipc.send` and `input.inject` are replaced by one fake game: it answers each
`menulayout <Obj>` line with the listing of the stage the inputs so far have
reached (before Escape, the pause menu open, the menu room after the Exit
click), so a key or click the tool should not have sent changes what it reads
next, the way the game would. `_sleep` is a no-op that advances `_now`, so
the poll budgets and `timeout_s` cost nothing. Nothing here starts a game or
calls Win32.

The listings are synthetic (`hs_drive_mcp_pausemenu_fixtures`): no
pause-menu listing has been captured yet. These tests pin the tool's rules --
the row it clicks is a new row of this open, picked by its text or
`uiNodeCallstack`, at its listed point -- not what the game's menu says.

Baseline (`AGENTS.md` § "Mod Development Workflow"): outside the world, with
a disagreeing window or with a menu that never lists, nothing is clicked.
Target: the one new Exit row is clicked at its `win` point and the menu room
is reported. Negative control: a row listed before Escape whose text reads
like an exit is never clicked.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.hs_drive_mcp import menuexit, results  # noqa: E402
from tests.hs_drive_mcp_lease_fixtures import isolate_lease_dir  # noqa: E402
from tests.hs_drive_mcp_pausemenu_fixtures import (  # noqa: E402
    EXIT_ID, EXIT_POINT, HUD_BUTTONS, PAUSE_BUTTONS, SECOND_EXIT, TOWN_ROOM,
    framed, listing, pause_row)


def setUpModule():
    isolate_lease_dir()


RUNNING = ("running", "1 hero_siege.exe process(es) are live: [4242].")
NOT_RUNNING = ("not_running", "the process snapshot returned 0 rows.")
WINDOW = {"hwnd": 0x1234, "pid": 4242, "bbox": (0, 0, 1920, 1080),
          "area": 1920 * 1080, "minimized": False}

#: The stages the fake game moves through, one per landed input.
IN_WORLD = {"UI_Button_obj": HUD_BUTTONS}
PAUSE_OPEN = {"UI_Pause_obj": [pause_row()],
              "UI_Button_obj": HUD_BUTTONS + PAUSE_BUTTONS}
CHARACTER_SELECT = {"room": "Chose_rm"}


class FakeGame:
    """`ipc.send` and `input.inject` in one. `stages[n]` is what the game
    lists once `n` inputs have landed (the last stage repeats); a stage may
    be a list of answers, consumed one per read, the last repeating."""

    def __init__(self, stages, *, undelivered_at=None):
        self.stages = [list(s) if isinstance(s, list) else [s] for s in stages]
        self.landed = 0
        self.sent: list[list[str]] = []
        self.injected: list[dict] = []
        self.undelivered_at = undelivered_at

    def stage(self) -> dict:
        answers = self.stages[min(self.landed, len(self.stages) - 1)]
        return answers.pop(0) if len(answers) > 1 else answers[0]

    def send(self, lines, *, tool="hs_command", **kwargs):
        self.sent.append(list(lines))
        stage = self.stage()
        listings = []
        for line in lines:
            command, _, obj = line.partition(" ")
            assert command == "menulayout", line
            listings.append(listing(
                list(stage.get(obj, [])), room=stage.get("room", TOWN_ROOM),
                window=stage.get("window", "1920x1080"),
                capped=stage.get("capped", {}).get(obj, 0)))
        reply = framed(*listings)
        return results.ok(tool, sent=list(lines), reply=reply,
                          reply_lines=reply.splitlines(), consumed=True)

    def inject(self, actions, *, route="send_input", force_focus=False,
               tool="hs_input", **kwargs):
        index = len(self.injected)
        self.injected.append({"actions": actions, "route": route,
                              "force_focus": force_focus})
        if self.undelivered_at == index:
            return results.ok(tool, complete=False, records_sent=2,
                              records_rejected=2, focus_via="set_foreground",
                              detail="SendInput rejected 2 of 2 record(s).")
        self.landed += 1
        return results.ok(tool, complete=True, records_sent=2,
                          records_rejected=0, focus_via="already_foreground")

    def clicks(self):
        return [(a["x"], a["y"]) for call in self.injected
                for a in call["actions"] if a["type"] == "click"]

    def keys(self):
        return [a["vk"] for call in self.injected
                for a in call["actions"] if a["type"] == "key"]


class MenuExitTestCase(unittest.TestCase):

    def run_tool(self, stages, *, client=(1920, 1080), label=None,
                 timeout_s=5, undelivered_at=None, gate=RUNNING):
        game = FakeGame(stages, undelivered_at=undelivered_at)
        clock = [0.0]

        def sleep(seconds):
            clock[0] += max(0.0, seconds)

        with patch.object(menuexit.ipc, "send", game.send), \
             patch.object(menuexit.input_module, "inject", game.inject), \
             patch.object(menuexit.input_module, "_geometry",
                          lambda hwnd: ({"client_size": list(client)}, "")), \
             patch.object(menuexit.procs, "gate", lambda: gate), \
             patch.object(menuexit.procs, "game_pids", lambda: [4242]), \
             patch.object(menuexit.capture, "resolve_game_window",
                          lambda pids, tool: dict(WINDOW)), \
             patch.object(menuexit, "_sleep", sleep), \
             patch.object(menuexit, "_now", lambda: clock[0]):
            result = menuexit.hs_exit_to_menu(timeout_s=timeout_s, label=label)
        return result, game


class RefusalTests(MenuExitTestCase):

    def test_refuses_outside_the_world(self):
        for room in ("Main_Menu_rm", "Chose_rm"):
            with self.subTest(room=room):
                result, game = self.run_tool([{"room": room, **IN_WORLD}])
                self.assertEqual(result["reason"], "not_in_world", result)
                self.assertIn(room, result["detail"])
                self.assertEqual(game.injected, [])
                self.assertEqual(result["lease"], "none")

    def test_refuses_when_the_pause_menu_never_lists(self):
        result, game = self.run_tool([IN_WORLD, IN_WORLD])
        self.assertEqual(result["reason"], "pause_menu_not_open", result)
        self.assertEqual(game.keys(), [menuexit.ESCAPE_VK])
        self.assertEqual(game.clicks(), [])
        self.assertTrue(result["last_listing"], result)
        self.assertEqual(len(game.sent), 1 + menuexit.POLL_ATTEMPTS)

    def test_refuses_two_exit_rows(self):
        two = {**PAUSE_OPEN,
               "UI_Button_obj": HUD_BUTTONS + PAUSE_BUTTONS + [SECOND_EXIT]}
        result, game = self.run_tool([IN_WORLD, two])
        self.assertEqual(result["reason"], "exit_button_ambiguous", result)
        self.assertEqual(game.clicks(), [])
        ids = sorted(c["id"] for c in result["candidates"])
        self.assertEqual(ids, [EXIT_ID, 300109])
        for field in ("obj", "id", "text", "uiNodeCallstack", "win"):
            self.assertIn(field, result["candidates"][0])

    def test_refuses_when_no_menu_room_is_reached(self):
        result, game = self.run_tool([IN_WORLD, PAUSE_OPEN, IN_WORLD],
                                     timeout_s=3)
        self.assertEqual(result["reason"], "menu_not_reached", result)
        self.assertEqual(game.clicks(), [EXIT_POINT])
        self.assertIn(TOWN_ROOM, result["detail"])
        # Polled within timeout_s and no further: 3 s at 0.5 s a read.
        self.assertLessEqual(len(game.sent), 2 + 6 + 1)

    def test_a_pause_menu_still_listed_in_a_menu_room_is_not_reached(self):
        still_open = {"room": "Chose_rm", "UI_Pause_obj": [pause_row()]}
        result, _ = self.run_tool([IN_WORLD, PAUSE_OPEN, still_open],
                                  timeout_s=2)
        self.assertEqual(result["reason"], "menu_not_reached", result)

    def test_window_size_mismatch_refuses_before_any_input(self):
        result, game = self.run_tool([{**IN_WORLD, "window": "1280x720"}])
        self.assertEqual(result["reason"], "window_size_mismatch", result)
        self.assertEqual(game.injected, [])
        # Positive control: the same stage at the client's own size presses.
        result, game = self.run_tool([IN_WORLD, PAUSE_OPEN, CHARACTER_SELECT])
        self.assertTrue(result["ok"], result)
        self.assertEqual(game.keys(), [menuexit.ESCAPE_VK])

    def test_a_mismatched_listing_after_the_key_clicks_nothing(self):
        result, game = self.run_tool(
            [IN_WORLD, {**PAUSE_OPEN, "window": "1280x720"}])
        self.assertEqual(result["reason"], "window_size_mismatch", result)
        self.assertEqual(game.clicks(), [])

    def test_a_capped_listing_is_never_used_to_pick_a_row(self):
        before = {**IN_WORLD, "capped": {"UI_Button_obj": 1}}
        result, game = self.run_tool([before, PAUSE_OPEN])
        self.assertEqual(result["reason"], "exit_button_not_found", result)
        self.assertIn("capped=1", result["detail"])
        self.assertEqual(game.injected, [])
        after = {**PAUSE_OPEN, "capped": {"UI_Button_obj": 1}}
        result, game = self.run_tool([IN_WORLD, after])
        self.assertEqual(result["reason"], "exit_button_not_found", result)
        self.assertIn("capped=1", result["detail"])
        self.assertEqual(game.clicks(), [])

    def test_an_undelivered_escape_is_not_counted_and_nothing_is_polled(self):
        result, game = self.run_tool([IN_WORLD, PAUSE_OPEN], undelivered_at=0)
        self.assertEqual(result["reason"], "click_not_delivered", result)
        self.assertEqual(len(game.sent), 1)
        self.assertEqual(result["layout_trail"], [])

    def test_no_game_sends_nothing(self):
        result, game = self.run_tool([IN_WORLD], gate=NOT_RUNNING)
        self.assertEqual(result["reason"], "game_not_running", result)
        self.assertEqual((game.sent, game.injected), ([], []))


class ExitRowTests(MenuExitTestCase):

    def test_clicks_the_one_new_exit_row_at_its_listed_point(self):
        result, game = self.run_tool([IN_WORLD, PAUSE_OPEN, CHARACTER_SELECT])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["phase"], "menu_reached")
        self.assertEqual(result["pause_opened_by"], "key")
        # Escape first, held 60 ms; then one held click at the listed point.
        key, click = game.injected
        self.assertEqual(key["actions"], [{"type": "key", "vk": 27, "hold_ms": 60}])
        self.assertEqual(click["actions"], [{"type": "click", "x": EXIT_POINT[0],
                                             "y": EXIT_POINT[1], "hold_ms": 120}])
        for call in game.injected:
            self.assertEqual(call["route"], "send_input")
            self.assertTrue(call["force_focus"])
        self.assertEqual(result["exit_row"]["id"], EXIT_ID)
        self.assertEqual(result["exit_row"]["uiNodeCallstack"], "PauseExit")
        self.assertEqual([step["step"] for step in result["layout_trail"]],
                         ["escape", "exit"])
        self.assertEqual(len(result["focus_trail"]), 2)
        # "Join Discord" carries "Exit" in its callstack and is excluded.
        self.assertNotIn((960, 674), game.clicks())

    def test_label_picks_the_row_with_that_exact_text(self):
        two = {**PAUSE_OPEN,
               "UI_Button_obj": HUD_BUTTONS + PAUSE_BUTTONS + [SECOND_EXIT]}
        result, game = self.run_tool([IN_WORLD, two, CHARACTER_SELECT],
                                     label="Exit Game")
        self.assertTrue(result["ok"], result)
        self.assertEqual(game.clicks(), [(960, 870)])
        self.assertEqual(result["exit_row"]["text"], "Exit Game")
        # Exact text, not a substring and not the callstack.
        result, game = self.run_tool([IN_WORLD, two, CHARACTER_SELECT],
                                     label="exit")
        self.assertEqual(result["reason"], "exit_button_not_found", result)
        self.assertEqual(game.clicks(), [])

    def test_reports_the_menu_room_it_reached(self):
        for room in ("Chose_rm", "Main_Menu_rm"):
            with self.subTest(room=room):
                loading = {"room": "Loading_rm"}
                result, _ = self.run_tool(
                    [IN_WORLD, PAUSE_OPEN, [loading, loading, {"room": room}]])
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["room"], room)
                self.assertIn(f"room={room}", result["proof"][-1])
                self.assertIn(f"room={TOWN_ROOM}", result["proof"][0])

    def test_negative_control_a_row_listed_before_the_key_is_never_clicked(self):
        # The HUD's "Exit Portal" reads like an exit row and is listed before
        # Escape: it is not this open's row, so the new Exit row is clicked.
        result, game = self.run_tool([IN_WORLD, PAUSE_OPEN, CHARACTER_SELECT])
        self.assertTrue(result["ok"], result)
        self.assertEqual(game.clicks(), [EXIT_POINT])
        self.assertNotIn((1860, 40), game.clicks())
        # With no new Exit row at all, the old one is still not clicked.
        no_exit = {**PAUSE_OPEN, "UI_Button_obj": HUD_BUTTONS + PAUSE_BUTTONS[:3]}
        result, game = self.run_tool([IN_WORLD, no_exit])
        self.assertEqual(result["reason"], "exit_button_not_found", result)
        self.assertEqual(game.clicks(), [])

    def test_an_open_pause_menu_skips_the_key_and_says_so(self):
        open_alone = {**PAUSE_OPEN,
                      "UI_Button_obj": HUD_BUTTONS[:1] + PAUSE_BUTTONS}
        result, game = self.run_tool([open_alone, CHARACTER_SELECT])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["pause_opened_by"], "already_open")
        self.assertEqual(game.keys(), [])
        self.assertEqual(game.clicks(), [EXIT_POINT])
        # Already open, so there is no "before the key" to tell this open's
        # rows from the rest: every listed row is judged, and the HUD's
        # "Exit Portal" beside the menu's Exit is two candidates, refused.
        result, game = self.run_tool([PAUSE_OPEN, CHARACTER_SELECT])
        self.assertEqual(result["reason"], "exit_button_ambiguous", result)
        self.assertEqual(result["pause_opened_by"], "already_open")
        self.assertEqual(game.injected, [])

    def test_the_exit_row_can_list_a_read_or_two_after_the_pause_menu(self):
        building = {"UI_Pause_obj": [pause_row()], "UI_Button_obj": HUD_BUTTONS}
        result, game = self.run_tool(
            [IN_WORLD, [building, building, PAUSE_OPEN], CHARACTER_SELECT])
        self.assertTrue(result["ok"], result)
        self.assertEqual(game.clicks(), [EXIT_POINT])


if __name__ == "__main__":
    unittest.main()
