"""`hs_input` -- what actually leaves the process, and what stops it.

Nothing here calls Windows. Every Win32 entry point the module uses lives in
its `WIN32` table, and these tests replace that table wholesale, so the
assertions read the `INPUT` records and the posted messages that *would* have
been injected. That is the only way to assert the thing that matters: a
keyboard record with the wrong flags still "works" against a real machine in
the sense that no error is raised, and then the game ignores it.

Two arrangements are worth explaining.

**The game state is mocked at `procs._readings`,** the one function the gate,
`game_state()` and `game_pids()` all derive their answer from. Mocking them
separately would let the fixture put the module in a state the real module
cannot reach -- a gate saying `not_running` while `game_pids()` returns a pid
-- and `procs.py`'s own docstring records that two tools disagreeing about one
machine is a defect it has been corrected for twice. One mock, one machine.

**The baseline tests come first and assert an absence.** `AGENTS.md`
§ "Mod Development Workflow" asks for the unmodified behaviour to be pinned
before the new one: here the unmodified behaviour is *nothing is injected*,
and a fake that cannot record an injection could not catch the bug, so the
same fake that proves the refusals is the one that proves the sends.

The module is importable and these tests run on any platform: the structures
are plain `ctypes.Structure`s and every Windows call is behind the table.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.hs_drive_mcp import capture, input as hs_input, procs, results  # noqa: E402

HWND = 0x1234ABCD
OTHER_HWND = 0x7FFF0001
PID = 4242

#: A windowed 1920x1080 client inside a 1936x1119 frame, on a 2560x1440
#: virtual screen whose origin is (0, 0) -- the geometry the game workorder's
#: live gate measured on 2026-09-20.
CLIENT_W, CLIENT_H = 1920, 1080
ORIGIN_X, ORIGIN_Y = 8, 31
WINDOW_RECT = (0, 0, 1936, 1119)
VIRTUAL = {
    hs_input.SM_XVIRTUALSCREEN: 0,
    hs_input.SM_YVIRTUALSCREEN: 0,
    hs_input.SM_CXVIRTUALSCREEN: 2560,
    hs_input.SM_CYVIRTUALSCREEN: 1440,
}

#: Scan codes for the keys the live procedure uses. Values a US keyboard
#: really produces, so a reader can check them against a scan code table
#: rather than against this file.
SCAN = {16: 0x2A, 13: 0x1C, 27: 0x01, 33: 0x49, 40: 0x50, 46: 0x53}

VK_SHIFT = 16
VK_DOWN = 40


class FakeWin32:
    """Every call the module can make, recorded rather than performed."""

    def __init__(self, foreground=(HWND,), raise_succeeds=True, dpi=96,
                 accepted=None, post_queued=True, post_error=0):
        self.foreground = list(foreground)
        self.raise_succeeds = raise_succeeds
        self.dpi = dpi
        #: How many records SendInput claims to have accepted; None means
        #: "all of them", which is what a healthy machine reports.
        self.accepted = accepted
        #: Whether PostMessageW queues the message, and the error code it
        #: reports when it does not. A stub that can only answer "queued"
        #: cannot catch a route that never reads the answer, and this route's
        #: refusals are the interesting machines: 5 is ERROR_ACCESS_DENIED,
        #: what an elevated game's window gives a process that is not.
        self.post_queued = post_queued
        self.post_error = post_error
        self.sent = []
        self.posted = []
        self.slept = []
        self.raises = []
        self.converted = []
        self.foreground_reads = 0

    # -- reads --
    def get_foreground_window(self):
        self.foreground_reads += 1
        if len(self.foreground) > 1:
            return self.foreground.pop(0)
        return self.foreground[0]

    def set_foreground_window(self, hwnd):
        self.raises.append(hwnd)
        if self.raise_succeeds:
            self.foreground = [hwnd]
        return self.raise_succeeds

    def client_to_screen(self, hwnd, x, y):
        self.converted.append((hwnd, x, y))
        return (x + ORIGIN_X, y + ORIGIN_Y)

    def get_client_rect(self, hwnd):
        return (0, 0, CLIENT_W, CLIENT_H)

    def get_system_metrics(self, index):
        return VIRTUAL[index]

    def map_virtual_key(self, vk, map_type):
        assert map_type == hs_input.MAPVK_VK_TO_VSC, map_type
        return SCAN[vk]

    def get_dpi_for_window(self, hwnd):
        return self.dpi

    # -- writes --
    def send_input(self, records):
        self.sent.append(list(records))
        return len(records) if self.accepted is None else self.accepted

    def post_message(self, hwnd, message, wparam, lparam):
        self.posted.append((hwnd, message, wparam, lparam))
        return self.post_queued, (0 if self.post_queued else self.post_error)

    def sleep(self, seconds):
        self.slept.append(seconds)

    def table(self):
        return {
            "SendInput": self.send_input,
            "PostMessageW": self.post_message,
            "GetForegroundWindow": self.get_foreground_window,
            "SetForegroundWindow": self.set_foreground_window,
            "ClientToScreen": self.client_to_screen,
            "GetClientRect": self.get_client_rect,
            "GetSystemMetrics": self.get_system_metrics,
            "MapVirtualKeyW": self.map_virtual_key,
            "GetDpiForWindow": self.get_dpi_for_window,
            "sleep": self.sleep,
        }

    #: Only the two calls that leave this process. "Nothing was sent" is
    #: asserted against this, never against one of them.
    @property
    def injections(self):
        return self.sent + self.posted


RUNNING = ("running", "1 hero_siege.exe process(es) are live: [4242].")

GAME_WINDOW = {"hwnd": HWND, "pid": PID, "bbox": WINDOW_RECT,
               "area": 1936 * 1119, "minimized": False}


class InputTestCase(unittest.TestCase):
    """The fixture: one running game, one window, one fake Win32.

    `arrange()` runs in `setUp` with the healthy arrangement, and a test that
    needs a different machine calls it again with what it wants. Re-arranging
    replaces the patches rather than layering on them, so a test can never be
    reading a state an earlier `arrange()` left behind.
    """

    def setUp(self):
        self.arrange()

    def arrange(self, state=RUNNING, windows=(GAME_WINDOW,)):
        self.doCleanups()
        self.win32 = FakeWin32()
        rows = [(PID, "Hero_Siege.exe")] if state[0] == "running" else []
        self.enterContext(patch.object(
            procs, "_readings", lambda engine=None: (*state, rows)))
        self.enterContext(patch.object(
            capture, "visible_windows_for_pids", lambda pids: list(windows)))
        self.enterContext(patch.object(capture, "window_rect",
                                       lambda hwnd: WINDOW_RECT))
        self.enterContext(patch.dict(hs_input.WIN32, self.win32.table()))

    def inject(self, actions, **kwargs):
        return hs_input.inject(actions, **kwargs)


# --------------------------------------------------------------------------
# A2 -- baseline. The unmodified behaviour is that nothing is injected.
# --------------------------------------------------------------------------

class GateBaselineTests(InputTestCase):
    """No running game, no injection -- on either route.

    The assertion that matters is the second one in each test. A refusal token
    is easy to get right and easy to get right *while* having already sent the
    events, which is why the fake records both routes and both are asserted
    empty.
    """

    def test_a_game_that_is_not_running_refuses_and_sends_nothing(self):
        for route in hs_input.ROUTES:
            with self.subTest(route=route):
                self.arrange(state=("not_running", "the process snapshot "
                                    "returned 91 rows and none of them is "
                                    "hero_siege.exe."))
                report = self.inject([{"type": "key", "vk": VK_SHIFT}],
                                     route=route)
                self.assertTrue(report["refused"], report)
                self.assertEqual(report["reason"], "game_not_running")
                self.assertEqual(self.win32.injections, [])

    def test_an_unknown_game_state_refuses_and_sends_nothing(self):
        for route in hs_input.ROUTES:
            with self.subTest(route=route):
                self.arrange(state=("unknown", "the Windows process snapshot "
                                    "could not be created or read."))
                report = self.inject([{"type": "click", "x": 10, "y": 10}],
                                     route=route)
                self.assertTrue(report["refused"], report)
                self.assertEqual(report["reason"], "game_state_unknown")
                self.assertNotEqual(report["reason"], "game_not_running",
                                    "unknown must never read as not running")
                self.assertEqual(self.win32.injections, [])

    def test_a_missing_engine_names_the_engine_not_the_process_table(self):
        self.arrange(state=(procs.ENGINE_MISSING, "ForgePact/src is absent."))
        report = self.inject([{"type": "wait", "ms": 1}])
        self.assertEqual(report["reason"], "engine_source_missing")
        self.assertEqual(self.win32.injections, [])


class WindowBaselineTests(InputTestCase):
    def test_no_visible_window_refuses_and_sends_nothing(self):
        self.arrange(windows=())
        report = self.inject([{"type": "key", "vk": VK_SHIFT}])
        self.assertEqual(report["reason"], "no_visible_window_for_pid")
        self.assertEqual(self.win32.injections, [])

    def test_a_minimized_window_refuses_and_sends_nothing(self):
        self.arrange(windows=({"hwnd": HWND, "pid": PID, "bbox": WINDOW_RECT,
                               "area": 1, "minimized": True},))
        report = self.inject([{"type": "key", "vk": VK_SHIFT}])
        self.assertEqual(report["reason"], "window_minimized")
        self.assertEqual(self.win32.injections, [])

    def test_an_unmeasurable_window_refuses_rather_than_guessing(self):
        with patch.dict(hs_input.WIN32,
                        {"GetClientRect": lambda hwnd: None}):
            report = self.inject([{"type": "click", "x": 1, "y": 1}])
        self.assertEqual(report["reason"], "no_visible_window_for_pid")
        self.assertIn("GetClientRect", report["detail"])
        self.assertEqual(self.win32.injections, [])


# --------------------------------------------------------------------------
# A3 -- target: SendInput keyboard
# --------------------------------------------------------------------------

class SendInputKeyboardTests(InputTestCase):
    def test_a_key_is_a_scan_code_down_then_a_scan_code_up(self):
        report = self.inject([{"type": "key", "vk": VK_SHIFT, "hold_ms": 100}])
        self.assertTrue(report["ok"], report)

        records = [record for batch in self.win32.sent for record in batch]
        self.assertEqual(len(records), 2, "a press is exactly down then up")
        for record in records:
            self.assertEqual(record.type, hs_input.INPUT_KEYBOARD)
            self.assertEqual(record.ki.wScan, SCAN[VK_SHIFT],
                             "wScan must be MapVirtualKeyW(vk, 0)")
            self.assertTrue(record.ki.dwFlags & hs_input.KEYEVENTF_SCANCODE)
            self.assertEqual(record.ki.wVk, 0,
                             "MSDN requires wVk == 0 with KEYEVENTF_SCANCODE")
        self.assertFalse(records[0].ki.dwFlags & hs_input.KEYEVENTF_KEYUP)
        self.assertTrue(records[1].ki.dwFlags & hs_input.KEYEVENTF_KEYUP)

    def test_the_hold_is_a_sleep_between_the_two_records(self):
        self.inject([{"type": "key", "vk": VK_SHIFT, "hold_ms": 100}])
        self.assertEqual(len(self.win32.slept), 1)
        self.assertGreaterEqual(self.win32.slept[0], 0.1)

    def test_the_extended_bit_is_set_for_the_navigation_cluster_only(self):
        """One of each, because a bit that is always set and a bit that is
        never set both pass a test that only looks at one key."""
        self.inject([{"type": "key", "vk": VK_DOWN}])
        self.assertTrue(self.win32.sent[0][0].ki.dwFlags
                        & hs_input.KEYEVENTF_EXTENDEDKEY,
                        "vk 40 (VK_DOWN) is an extended key")

        self.win32.sent.clear()
        self.inject([{"type": "key", "vk": VK_SHIFT}])
        self.assertFalse(self.win32.sent[0][0].ki.dwFlags
                         & hs_input.KEYEVENTF_EXTENDEDKEY,
                         "vk 16 (VK_SHIFT) is not")

        for vk in (33, 46):
            self.win32.sent.clear()
            self.inject([{"type": "key_down", "vk": vk}])
            self.assertTrue(self.win32.sent[0][0].ki.dwFlags
                            & hs_input.KEYEVENTF_EXTENDEDKEY, vk)

    def test_key_down_and_key_up_send_one_record_each_and_never_sleep(self):
        self.inject([{"type": "key_down", "vk": VK_SHIFT}])
        self.assertEqual(len(self.win32.sent), 1)
        self.assertFalse(self.win32.sent[0][0].ki.dwFlags
                         & hs_input.KEYEVENTF_KEYUP)
        self.assertEqual(self.win32.slept, [],
                         "a key_down with no matching up must not block")

        self.win32.sent.clear()
        self.inject([{"type": "key_up", "vk": VK_SHIFT}])
        self.assertTrue(self.win32.sent[0][0].ki.dwFlags
                        & hs_input.KEYEVENTF_KEYUP)

    def test_a_wait_sleeps_and_sends_nothing(self):
        report = self.inject([{"type": "wait", "ms": 300}])
        self.assertTrue(report["ok"], report)
        self.assertEqual(self.win32.injections, [])
        self.assertEqual(self.win32.slept, [0.3])


# --------------------------------------------------------------------------
# A4 -- target: SendInput mouse
# --------------------------------------------------------------------------

class SendInputMouseTests(InputTestCase):
    @staticmethod
    def absolute(screen_x, screen_y):
        """A4's formula, spelled out here rather than imported, so the test
        pins the arithmetic instead of agreeing with it."""
        return ((screen_x - VIRTUAL[hs_input.SM_XVIRTUALSCREEN]) * 65535
                // VIRTUAL[hs_input.SM_CXVIRTUALSCREEN],
                (screen_y - VIRTUAL[hs_input.SM_YVIRTUALSCREEN]) * 65535
                // VIRTUAL[hs_input.SM_CYVIRTUALSCREEN])

    def test_a_client_click_converts_then_moves_then_presses_then_releases(self):
        report = self.inject([{"type": "click", "x": 100, "y": 50,
                               "button": "left"}])
        self.assertTrue(report["ok"], report)
        self.assertIn((HWND, 100, 50), self.win32.converted,
                      "the click point is converted with the game's hwnd")

        records = [record for batch in self.win32.sent for record in batch]
        self.assertEqual(len(records), 3)
        for record in records:
            self.assertEqual(record.type, hs_input.INPUT_MOUSE)

        expected = self.absolute(100 + ORIGIN_X, 50 + ORIGIN_Y)
        self.assertEqual((records[0].mi.dx, records[0].mi.dy), expected)
        self.assertTrue(records[0].mi.dwFlags & hs_input.MOUSEEVENTF_ABSOLUTE)
        self.assertTrue(records[0].mi.dwFlags & hs_input.MOUSEEVENTF_VIRTUALDESK)
        self.assertTrue(records[0].mi.dwFlags & hs_input.MOUSEEVENTF_MOVE)
        self.assertEqual(records[1].mi.dwFlags, hs_input.MOUSEEVENTF_LEFTDOWN)
        self.assertEqual(records[2].mi.dwFlags, hs_input.MOUSEEVENTF_LEFTUP)

    def test_a_right_click_uses_the_right_button_flags(self):
        self.inject([{"type": "click", "x": 0, "y": 0, "button": "right"}])
        records = [record for batch in self.win32.sent for record in batch]
        self.assertEqual(records[1].mi.dwFlags, hs_input.MOUSEEVENTF_RIGHTDOWN)
        self.assertEqual(records[2].mi.dwFlags, hs_input.MOUSEEVENTF_RIGHTUP)

    def test_a_move_sends_the_move_and_no_button(self):
        self.inject([{"type": "move", "x": 5, "y": 6}])
        records = [record for batch in self.win32.sent for record in batch]
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].mi.dwFlags & hs_input.MOUSEEVENTF_MOVE)

    def test_a_click_outside_the_client_area_is_refused_with_nothing_sent(self):
        for point in ((CLIENT_W, 10), (10, CLIENT_H), (-1, 10), (10, -1)):
            with self.subTest(point=point):
                self.win32.sent.clear()
                report = self.inject([{"type": "click", "x": point[0],
                                       "y": point[1]}])
                self.assertEqual(report["reason"], "invalid_input", report)
                self.assertEqual(self.win32.injections, [])

    def test_a_bad_point_late_in_a_sequence_stops_the_whole_sequence(self):
        """Every point is checked before the first event, not as it is reached.

        Checking them one at a time would leave the game holding whatever the
        earlier actions did -- here a pressed mouse button -- which is a state
        a coordinate typo should not be able to produce.
        """
        report = self.inject([{"type": "click", "x": 10, "y": 10},
                              {"type": "click", "x": 99999, "y": 10}])
        self.assertEqual(report["reason"], "invalid_input")
        self.assertIn("Nothing was sent", report["detail"])
        self.assertEqual(self.win32.injections, [])

    def test_screen_space_skips_the_client_conversion(self):
        report = self.inject([{"type": "click", "x": 2000, "y": 1200,
                               "space": "screen"}])
        self.assertTrue(report["ok"], report)
        self.assertEqual(self.win32.converted, [(HWND, 0, 0)],
                         "the only conversion is the one that locates the "
                         "client area for the result; the point is already "
                         "in screen coordinates")
        records = [record for batch in self.win32.sent for record in batch]
        self.assertEqual((records[0].mi.dx, records[0].mi.dy),
                         self.absolute(2000, 1200))

    def test_a_screen_point_off_the_virtual_desktop_is_refused(self):
        report = self.inject([{"type": "move", "x": 5000, "y": 10,
                               "space": "screen"}])
        self.assertEqual(report["reason"], "invalid_input")
        self.assertEqual(self.win32.injections, [])


# --------------------------------------------------------------------------
# A5 -- the foreground permission, and the post_message route
# --------------------------------------------------------------------------

class ForegroundTests(InputTestCase):
    def test_a_foreground_that_is_not_the_game_is_raised_once_then_accepted(self):
        self.win32.foreground = [OTHER_HWND]
        self.win32.raise_succeeds = True
        report = self.inject([{"type": "key", "vk": VK_SHIFT}])
        self.assertTrue(report["ok"], report)
        self.assertEqual(self.win32.raises, [HWND])
        self.assertEqual(report["foreground_before"], OTHER_HWND)
        self.assertEqual(report["foreground_after"], HWND)

    def test_a_raise_that_does_not_take_refuses_with_nothing_sent(self):
        self.win32.foreground = [OTHER_HWND]
        self.win32.raise_succeeds = False
        report = self.inject([{"type": "key", "vk": VK_SHIFT}])
        self.assertEqual(report["reason"], "foreground_not_game")
        self.assertEqual(self.win32.raises, [HWND],
                         "exactly one attempt; there is no second, more "
                         "forceful route by design")
        self.assertEqual(self.win32.injections, [])
        self.assertEqual(report["actions_done"], 0)

    def test_require_foreground_false_never_takes_focus(self):
        self.win32.foreground = [OTHER_HWND]
        report = self.inject([{"type": "key", "vk": VK_SHIFT}],
                             require_foreground=False)
        self.assertEqual(report["reason"], "foreground_not_game")
        self.assertEqual(self.win32.raises, [],
                         "require_foreground=false means never steal focus")
        self.assertEqual(self.win32.injections, [])

    def test_the_foreground_is_proved_again_before_every_send(self):
        """`AGENTS.md` § "Check a Permission Where It Is Used".

        The game is in front when the call starts and loses focus after the
        first record. A tool that checked once would type the rest of the
        sequence into whatever took focus; this one stops and says so.
        """
        self.win32.foreground = [HWND, HWND, OTHER_HWND]
        report = self.inject([{"type": "key_down", "vk": VK_SHIFT},
                              {"type": "key_down", "vk": 13},
                              {"type": "key_down", "vk": 27}])
        self.assertTrue(report["ok"], report)
        self.assertEqual(len(self.win32.sent), 1,
                         "only the record sent while the game was in front")
        self.assertEqual(report["actions_done"], 1)
        self.assertEqual(report["actions_total"], 3)
        self.assertFalse(report["complete"])
        self.assertIn("foreground window changed", report["detail"])


class PostMessageTests(InputTestCase):
    def test_post_message_performs_no_foreground_check(self):
        self.win32.foreground = [OTHER_HWND]
        report = self.inject([{"type": "key", "vk": VK_SHIFT}],
                             route="post_message")
        self.assertTrue(report["ok"], report)
        self.assertEqual(self.win32.raises, [])
        self.assertEqual(self.win32.sent, [], "no SendInput on this route")
        self.assertEqual(report["foreground_before"], OTHER_HWND,
                         "it is still reported, just not enforced")

    def test_a_posted_key_carries_the_scan_code_and_the_transition_bits(self):
        self.inject([{"type": "key", "vk": VK_SHIFT}], route="post_message")
        self.assertEqual(len(self.win32.posted), 2)
        (hwnd, down_msg, down_wparam, down_lparam) = self.win32.posted[0]
        (_, up_msg, up_wparam, up_lparam) = self.win32.posted[1]

        self.assertEqual(hwnd, HWND)
        self.assertEqual(down_msg, 0x0100)
        self.assertEqual(up_msg, 0x0101)
        self.assertEqual(down_wparam, VK_SHIFT)
        self.assertEqual(up_wparam, VK_SHIFT)
        self.assertEqual((down_lparam >> 16) & 0xFF, SCAN[VK_SHIFT])
        self.assertEqual((up_lparam >> 16) & 0xFF, SCAN[VK_SHIFT])
        self.assertEqual(down_lparam & 0xFFFF, 1, "repeat count")
        self.assertFalse(down_lparam & (1 << 30))
        self.assertFalse(down_lparam & (1 << 31))
        self.assertTrue(up_lparam & (1 << 30), "previous state: was down")
        self.assertTrue(up_lparam & (1 << 31), "transition: this is a key-up")

    def test_a_posted_extended_key_sets_bit_twenty_four(self):
        self.inject([{"type": "key_down", "vk": VK_DOWN}],
                    route="post_message")
        self.assertTrue(self.win32.posted[0][3] & (1 << 24))

    def test_a_posted_click_is_move_down_up_in_client_coordinates(self):
        report = self.inject([{"type": "click", "x": 100, "y": 50}],
                             route="post_message")
        messages = [message for _, message, _, _ in self.win32.posted]
        self.assertEqual(messages, [0x0200, 0x0201, 0x0202])
        for _, _, _, lparam in self.win32.posted:
            self.assertEqual(lparam, (50 << 16) | 100)
        self.assertEqual(report["records_sent"], 3,
                         "on this route a record is a posted message")
        self.assertEqual(report["records_rejected"], 0)
        self.assertTrue(report["complete"])

    def test_a_posted_screen_space_click_is_converted_back_to_client(self):
        self.inject([{"type": "click", "x": 100 + ORIGIN_X,
                      "y": 50 + ORIGIN_Y, "space": "screen"}],
                    route="post_message")
        for _, _, _, lparam in self.win32.posted:
            self.assertEqual(lparam, (50 << 16) | 100,
                             "a posted message always carries client "
                             "coordinates, whatever the caller supplied")

    def test_a_post_the_system_refused_stops_the_sequence_and_says_so(self):
        """The mirror of the `SendInput` rejection test, on the route whose
        positive controls never exercise delivery.

        `PostMessageW` returns FALSE having queued nothing on a UIPI integrity
        mismatch (the game elevated for Aurie injection, this process not), on
        a window destroyed part way through, and on a full message queue.
        Unread, all three come back `complete: true` with "N of N action(s)
        sent" -- and the live procedure's `keyboard_check` of false would then
        be measuring this tool, not the game.
        """
        self.win32.post_queued = False
        self.win32.post_error = 5  # ERROR_ACCESS_DENIED
        report = self.inject([{"type": "click", "x": 100, "y": 50},
                              {"type": "key", "vk": VK_SHIFT}],
                             route="post_message")
        self.assertTrue(report["ok"], report)
        self.assertEqual(len(self.win32.posted), 1,
                         "the refused move ends it; nothing after is posted")
        self.assertEqual(report["actions_done"], 0)
        self.assertEqual(report["actions_total"], 2)
        self.assertEqual(report["records_sent"], 1)
        self.assertEqual(report["records_rejected"], 1)
        self.assertFalse(report["complete"])
        self.assertIn("PostMessageW(WM_MOUSEMOVE)", report["detail"])
        self.assertIn("error 5", report["detail"])
        self.assertNotIn("SendInput", report["detail"],
                         "the route that failed is the one named")

    def test_a_refused_key_down_is_not_followed_by_a_key_up(self):
        self.win32.post_queued = False
        self.win32.post_error = 1816  # ERROR_NOT_ENOUGH_QUOTA
        report = self.inject([{"type": "key", "vk": VK_SHIFT}],
                             route="post_message")
        self.assertEqual([message for _, message, _, _ in self.win32.posted],
                         [0x0100], "no WM_KEYUP for a WM_KEYDOWN that was "
                                   "never queued")
        self.assertEqual(self.win32.slept, [],
                         "and no hold, because there is nothing being held")
        self.assertIn("PostMessageW(WM_KEYDOWN)", report["detail"])
        self.assertIn("1816", report["detail"])
        self.assertFalse(report["complete"])

    def test_a_bare_true_from_a_replaced_entry_is_read_as_queued(self):
        """`emit`'s rule applied to this route: an answer that is not the real
        call's `(queued, error)` shape still counts as a reading taken, so a
        stub cannot manufacture a refusal that never happened."""
        with patch.dict(hs_input.WIN32, {"PostMessageW": lambda *args: True}):
            report = self.inject([{"type": "key_down", "vk": VK_SHIFT}],
                                 route="post_message")
        self.assertTrue(report["complete"], report)
        self.assertEqual(report["records_rejected"], 0)
        self.assertEqual(report["records_sent"], 1)


# --------------------------------------------------------------------------
# A6 -- limits, shape and the reported result
# --------------------------------------------------------------------------

class ShapeTests(InputTestCase):
    def refusal(self, actions, **kwargs):
        report = self.inject(actions, **kwargs)
        self.assertTrue(report["refused"], report)
        self.assertEqual(report["reason"], "invalid_input", report)
        self.assertEqual(self.win32.injections, [])
        return report

    def test_more_than_sixty_four_actions_is_refused(self):
        self.inject([{"type": "wait", "ms": 0}] * 64)  # the cap itself is fine
        self.refusal([{"type": "wait", "ms": 0}] * 65)

    def test_an_empty_or_non_list_actions_argument_is_refused(self):
        self.refusal([])
        self.refusal("key")
        self.refusal([{"type": "key", "vk": 13}, "key"])

    def test_a_hold_or_wait_over_ten_seconds_is_refused(self):
        self.refusal([{"type": "key", "vk": 13, "hold_ms": 10001}])
        self.refusal([{"type": "wait", "ms": 10001}])
        self.refusal([{"type": "wait", "ms": -1}])

    def test_an_unknown_action_type_is_refused(self):
        report = self.refusal([{"type": "scroll", "amount": 3}])
        self.assertIn("scroll", report["detail"])
        self.refusal([{"vk": 13}])

    def test_a_vk_outside_one_to_two_hundred_and_fifty_four_is_refused(self):
        for vk in (0, 255, 256, -1):
            with self.subTest(vk=vk):
                self.refusal([{"type": "key", "vk": vk}])

    def test_a_boolean_is_not_an_integer_here(self):
        """`True == 1` in Python, so `vk: true` would otherwise be VK_LBUTTON."""
        self.refusal([{"type": "key", "vk": True}])

    def test_an_unknown_route_button_or_space_is_refused(self):
        self.refusal([{"type": "wait", "ms": 1}], route="sendinput")
        self.refusal([{"type": "click", "x": 1, "y": 1, "button": "middle"}])
        self.refusal([{"type": "click", "x": 1, "y": 1, "space": "window"}])


class ResultShapeTests(InputTestCase):
    def test_a_successful_result_carries_every_documented_field(self):
        report = self.inject([{"type": "key", "vk": VK_SHIFT},
                              {"type": "wait", "ms": 1}])
        for key in ("route", "pid", "hwnd", "window_rect", "client_rect",
                    "client_size", "dpi", "foreground_before",
                    "foreground_after", "actions_done", "elapsed_s"):
            self.assertIn(key, report)
        self.assertEqual(report["route"], "send_input")
        self.assertEqual(report["pid"], PID)
        self.assertEqual(report["hwnd"], HWND)
        self.assertEqual(report["window_rect"], list(WINDOW_RECT))
        self.assertEqual(report["client_rect"],
                         [ORIGIN_X, ORIGIN_Y, ORIGIN_X + CLIENT_W,
                          ORIGIN_Y + CLIENT_H],
                         "client_rect is in screen coordinates")
        self.assertEqual(report["client_size"], [CLIENT_W, CLIENT_H])
        self.assertEqual(report["dpi"], 96)
        self.assertEqual(report["actions_done"], 2)
        self.assertIsInstance(report["elapsed_s"], float)

    def test_a_machine_without_the_dpi_symbol_reports_null_not_a_refusal(self):
        with patch.dict(hs_input.WIN32, {"GetDpiForWindow": lambda hwnd: None}):
            report = self.inject([{"type": "wait", "ms": 1}])
        self.assertTrue(report["ok"], report)
        self.assertIsNone(report["dpi"])

    def test_records_the_system_rejected_are_reported_not_hidden(self):
        """A `SendInput` that accepts nothing is a silent no-op otherwise."""
        self.win32.accepted = 0
        report = self.inject([{"type": "key_down", "vk": VK_SHIFT}])
        self.assertTrue(report["ok"])
        self.assertEqual(report["records_rejected"], 1)
        self.assertFalse(report["complete"])
        self.assertIn("rejected", report["detail"])


class TokenTests(unittest.TestCase):
    def test_the_two_new_tokens_are_registered_and_no_others(self):
        self.assertEqual(results.INPUT_REASONS,
                         ("foreground_not_game", "invalid_input"))
        for token in results.INPUT_REASONS:
            self.assertIn(token, results.REASONS)
        for reserved in ("layout_not_measured", "research_build_required"):
            self.assertNotIn(reserved, results.REASONS,
                             f"{reserved} belongs to hs-drive-mcp-charselect-"
                             "ship; defining it here would let a tool refuse "
                             "with a token nothing implements")


if __name__ == "__main__":
    unittest.main()
