"""Which window gets captured, and what comes back when the capture shows nothing.

Two halves, and the second is the one that matters. Finding the window is
ordinary Win32 bookkeeping. *Not lying about the result* is the part this suite
exists for: a capture of a black rectangle and a capture of a game that happens
to be dark are the same bytes, and the difference between them is a warning this
module either attaches or does not. `AGENTS.md` § "Prove the Instrument Before
Trusting a Negative Result" is the general rule; `target="screen"` is the
positive control that makes a flat game capture attributable to the window
rather than to Pillow.

Nothing here captures the real screen except one deliberately marked positive
control, and nothing here writes outside a temporary directory:
`HS_DRIVE_SCREENSHOT_DIR` is repointed for every test, the same way the save
tools' two overrides exist so no suite can reach the owner's real files.
"""
import base64
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENGINE_SOURCE = ROOT / "ForgePact" / "src" / "offline_launcher.py"

SKIP_REASON = None
if os.name != "nt":
    SKIP_REASON = (f"window enumeration and ImageGrab are Windows-only here; "
                   f"os.name is {os.name!r}")
elif not ENGINE_SOURCE.is_file():
    SKIP_REASON = (f"{ENGINE_SOURCE} is absent; run "
                   "`git submodule update --init ForgePact`")
else:
    try:
        import mcp  # noqa: F401
        import PIL  # noqa: F401
    except ImportError as exc:
        SKIP_REASON = (f"{exc.name} is not installed; run "
                       "`py -3 -m pip install -r tools/hs_drive_mcp/requirements.txt`")

if SKIP_REASON is None:
    from PIL import Image

    from tools.hs_drive_mcp import capture, procs, results, server


def png_header_size(path: Path) -> tuple[int, int]:
    """Width and height out of the PNG IHDR, without decoding the image.

    Read from the file's own bytes on purpose: the claim under test is that the
    *file* keeps full resolution while only the transported copy is shrunk, and
    asking Pillow to reopen it would test Pillow's agreement with itself.
    """
    raw = path.read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    width, height = struct.unpack(">II", raw[16:24])
    return width, height


def hwnd_of(handle):
    """The integer a real Win32 call receives from our `c_void_p` argument."""
    return int(getattr(handle, "value", handle) or 0)


class FakeUser32:
    """user32 with a fixed window list, filling the real pointers.

    `GetWindowRect` writes through the pointer the way the API does rather than
    returning a tuple, so the marshalling in `capture.window_rect` is under test
    and not stubbed past.
    """

    def __init__(self, windows):
        self.windows = list(windows)

    def _window(self, hwnd):
        for window in self.windows:
            if window["hwnd"] == hwnd_of(hwnd):
                return window
        raise AssertionError(f"the code under test invented hwnd {hwnd}")

    def EnumWindows(self, callback, extra):  # noqa: N802 - the Win32 name
        for window in self.windows:
            callback(window["hwnd"], extra)
        return 1

    def GetWindowThreadProcessId(self, hwnd, pointer):  # noqa: N802
        pointer.contents.value = self._window(hwnd)["pid"]
        return 99

    def IsWindowVisible(self, hwnd):  # noqa: N802
        return 1 if self._window(hwnd)["visible"] else 0

    def IsIconic(self, hwnd):  # noqa: N802
        return 1 if self._window(hwnd)["minimized"] else 0

    def GetWindowRect(self, hwnd, pointer):  # noqa: N802
        left, top, right, bottom = self._window(hwnd)["rect"]
        rect = pointer.contents
        rect.left, rect.top, rect.right, rect.bottom = left, top, right, bottom
        return 1


def window(hwnd, pid, rect, *, visible=True, minimized=False):
    return {"hwnd": hwnd, "pid": pid, "rect": rect, "visible": visible,
            "minimized": minimized}


def gate_running():
    return "running", "1 hero_siege.exe process(es) are live: [4242]."


def gate_not_running():
    return "not_running", "the process snapshot returned 71 rows and none of them is hero_siege.exe."


def gate_unknown():
    return "unknown", "the Windows process snapshot could not be created or read."


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class WindowResolutionTests(unittest.TestCase):
    """E2 -- the largest visible window, and three separate refusals."""

    def resolve(self, windows, pids=(4242,)):
        with patch.object(capture, "user32", return_value=FakeUser32(windows)):
            return capture.resolve_game_window(list(pids), "hs_screenshot")

    def test_the_largest_visible_window_of_a_game_pid_wins(self):
        chosen = self.resolve([
            window(1, 4242, (0, 0, 640, 480)),
            window(2, 4242, (0, 0, 1920, 1080)),
            window(3, 4242, (0, 0, 2000, 2000), visible=False),
            window(4, 99, (0, 0, 3000, 3000)),
        ])
        self.assertEqual(chosen["hwnd"], 2)
        self.assertEqual(chosen["bbox"], (0, 0, 1920, 1080))
        self.assertEqual(chosen["pid"], 4242)

    def test_a_window_on_a_second_monitor_keeps_its_negative_coordinates(self):
        # Virtual-desktop coordinates are why grab_bbox passes all_screens=True;
        # a monitor to the left of the primary one has negative x.
        chosen = self.resolve([window(5, 4242, (-1920, 0, 0, 1080))])
        self.assertEqual(chosen["bbox"], (-1920, 0, 0, 1080))
        self.assertEqual(chosen["area"], 1920 * 1080)

    def test_no_visible_window_is_its_own_refusal(self):
        refusal = self.resolve([window(6, 4242, (0, 0, 100, 100), visible=False)])
        self.assertTrue(results.is_refusal(refusal))
        self.assertEqual(refusal["reason"], "no_visible_window_for_pid")
        self.assertIn("4242", refusal["detail"])

    def test_a_minimized_window_is_refused_rather_than_photographed(self):
        refusal = self.resolve([window(7, 4242, (-32000, -32000, -31840, -31972),
                                       minimized=True)])
        self.assertEqual(refusal["reason"], "window_minimized")
        self.assertIn("behind it", refusal["detail"])

    def test_a_game_that_is_not_running_never_reaches_window_resolution(self):
        with patch.object(capture, "user32", side_effect=AssertionError(
                "user32 was touched for a game that is not running")):
            refusal = capture.screenshot("game", gate=gate_not_running)
        self.assertEqual(refusal["reason"], "game_not_running")
        self.assertIn("target=\"screen\"", refusal["detail"])

    def test_an_unknown_process_state_refuses_with_the_gates_own_reason(self):
        refusal = capture.screenshot("game", gate=gate_unknown)
        self.assertEqual(refusal["reason"], "game_state_unknown")
        self.assertIn("could not be created", refusal["detail"])


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class CaptureTests(unittest.TestCase):
    """E3 -- the file, the envelope, the transported copy and the warning."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="hs-drive-shots-")
        self.addCleanup(temp.cleanup)
        self.shots = Path(temp.name).resolve() / "screenshots"
        self.enterContext(patch.dict(
            os.environ, {capture.SCREENSHOT_DIR_ENV: str(self.shots)}))
        self.user = FakeUser32([window(11, 4242, (100, 50, 2660, 1490))])
        self.enterContext(patch.object(capture, "user32", return_value=self.user))
        self.enterContext(patch.object(procs, "game_pids",
                                       side_effect=lambda *a, **k: [4242]))

    @staticmethod
    def picture(width, height, flat=False):
        """A synthetic capture. Not flat unless asked: one differing pixel is
        the whole difference between "a picture" and "a picture of nothing"."""
        image = Image.new("RGB", (width, height), (12, 12, 12))
        if not flat:
            image.putpixel((width - 1, height - 1), (255, 128, 0))
        return image

    def grabbing(self, image, method="grab_bbox"):
        return patch.object(capture, method, return_value=image)

    def test_a_game_capture_writes_a_full_size_png_and_reports_the_window(self):
        with self.grabbing(self.picture(2560, 1440)):
            result = capture.screenshot("game", label="test", gate=gate_running)
        self.assertTrue(result["ok"], result)
        path = Path(result["path"])
        self.assertEqual(path.parent, self.shots)
        self.assertTrue(path.name.endswith("_test.png"), path.name)
        self.assertEqual(png_header_size(path), (2560, 1440))
        self.assertEqual((result["width"], result["height"]), (2560, 1440))
        self.assertEqual(result["bbox"], [100, 50, 2660, 1490])
        self.assertEqual(result["capture_method"], "grab_bbox")
        self.assertEqual(result["hwnd"], 11)
        self.assertEqual(result["pid"], 4242)
        self.assertEqual(result["warning"], "")
        self.assertFalse(result["flat"])

    def test_the_bbox_handed_to_pillow_is_the_windows_own_rectangle(self):
        with patch.object(capture, "grab_bbox",
                          return_value=self.picture(2560, 1440)) as grab:
            capture.screenshot("game", gate=gate_running)
        grab.assert_called_once_with((100, 50, 2660, 1490))

    def test_grab_window_is_selectable_and_reported_as_the_method_used(self):
        with patch.object(capture, "grab_window",
                          return_value=self.picture(800, 600)) as grab:
            result = capture.screenshot("game", method="grab_window",
                                        gate=gate_running)
        grab.assert_called_once_with(11)
        self.assertEqual(result["capture_method"], "grab_window")
        self.assertEqual(png_header_size(Path(result["path"])), (800, 600))

    def test_a_screen_capture_needs_no_game_and_is_its_own_method(self):
        with patch.object(capture, "grab_bbox",
                          return_value=self.picture(1280, 800)) as grab:
            result = capture.screenshot("screen", gate=gate_not_running)
        grab.assert_called_once_with(None)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["target"], "screen")
        self.assertEqual(result["bbox"], [0, 0, 1280, 800])
        self.assertEqual(result["hwnd"], 0)

    def test_a_flat_capture_carries_the_warning_rather_than_looking_fine(self):
        with self.grabbing(self.picture(1920, 1080, flat=True)):
            result = capture.screenshot("game", gate=gate_running)
        self.assertTrue(result["ok"])
        self.assertTrue(result["flat"])
        self.assertEqual(result["warning"], capture.FLAT_WARNING)
        self.assertIn("windowed or borderless", result["detail"])

    def test_the_flat_predicate_has_a_negative_control(self):
        self.assertTrue(capture.is_flat(self.picture(4, 4, flat=True)))
        self.assertFalse(capture.is_flat(self.picture(4, 4)))

    def test_an_unknown_target_or_method_is_refused_not_guessed(self):
        for kwargs in ({"target": "windows"}, {"target": "game", "method": "print"}):
            refusal = capture.screenshot(gate=gate_running, **kwargs)
            self.assertEqual(refusal["reason"], "invalid_command", kwargs)

    def test_the_transported_copy_is_downscaled_and_the_file_is_not(self):
        with self.grabbing(self.picture(2560, 1440)):
            result = capture.screenshot("game", gate=gate_running)
        path = Path(result["path"])
        data, width, height = capture.transport_image(path)
        self.assertEqual(width, capture.MAX_TRANSPORT_WIDTH)
        self.assertEqual(height, 720)
        with Image.open(io.BytesIO(data)) as shrunk:
            self.assertEqual(shrunk.size, (1280, 720))
        self.assertEqual(png_header_size(path), (2560, 1440),
                         "the file on disk was downscaled; only the copy that "
                         "travels should be")

    def test_an_image_already_narrow_enough_travels_untouched(self):
        with self.grabbing(self.picture(800, 600)):
            result = capture.screenshot("game", gate=gate_running)
        data, width, height = capture.transport_image(Path(result["path"]))
        self.assertEqual((width, height), (800, 600))

    def test_the_default_directory_is_under_local_app_data(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(capture.SCREENSHOT_DIR_ENV)
            with patch.object(capture.launcher_bridge, "local_app_data",
                              return_value=Path("C:/fixture/LocalAppData")):
                directory = capture.screenshot_dir()
        self.assertEqual(directory,
                         Path("C:/fixture/LocalAppData/HSDriveMcp/screenshots"))


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class ToolResultTests(CaptureTests):
    """E3 -- what the tool hands back: the envelope *and* an image block."""

    def call(self, **kwargs):
        # The tool takes no gate argument -- it is the shared `procs.gate`, which
        # is the point: this exercises the wiring a client actually reaches.
        with patch.object(procs, "gate", side_effect=gate_running):
            with self.grabbing(kwargs.pop("image", self.picture(2560, 1440))):
                return server.hs_screenshot(**kwargs)

    def test_the_result_carries_a_json_text_block_and_a_png_image_block(self):
        result = self.call(target="game")
        kinds = [block.type for block in result.content]
        self.assertEqual(kinds, ["text", "image"],
                         "the envelope must come first so a client without "
                         "structured output still reads the result")
        payload = json.loads(result.content[0].text)
        self.assertTrue(payload["ok"], payload)
        for key in ("path", "width", "height", "bbox", "capture_method"):
            self.assertIn(key, payload)
        self.assertEqual(result.structured_content, payload)
        self.assertEqual(result.content[1].mime_type, "image/png")

    def test_the_image_block_is_the_downscaled_copy_of_the_full_size_file(self):
        result = self.call(target="game")
        payload = result.structured_content
        with Image.open(io.BytesIO(base64.b64decode(result.content[1].data))) as shrunk:
            self.assertEqual(shrunk.width, capture.MAX_TRANSPORT_WIDTH)
        self.assertEqual(png_header_size(Path(payload["path"])), (2560, 1440))
        self.assertEqual(payload["transport_width"], 1280)
        self.assertEqual(payload["transport_height"], 720)

    def test_the_envelope_is_json_serialisable_with_no_bytes_in_it(self):
        # A bytes value anywhere in the envelope fails the whole tool call
        # rather than one field of it, so the image never travels as a field.
        payload = self.call(target="game").structured_content
        json.dumps(payload)
        for key, value in payload.items():
            self.assertNotIsInstance(value, bytes, key)

    def test_the_screen_target_returns_the_same_two_blocks(self):
        # The positive control has to be reachable through the tool, not only
        # through the module: it is what a caller runs when a game capture looks
        # wrong, and it must need no game to be running.
        with patch.object(procs, "gate", side_effect=gate_not_running):
            with self.grabbing(self.picture(1600, 900)):
                result = server.hs_screenshot(target="screen")
        self.assertEqual([block.type for block in result.content], ["text", "image"])
        payload = result.structured_content
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["target"], "screen")
        self.assertEqual(Path(payload["path"]).parent, self.shots)
        self.assertEqual(png_header_size(Path(payload["path"])), (1600, 900))
        self.assertEqual(payload["transport_width"], 1280)

    def test_a_refusal_comes_back_as_one_text_block_and_no_image(self):
        with patch.object(procs, "gate", side_effect=gate_not_running):
            result = server.hs_screenshot(target="game")
        self.assertEqual([block.type for block in result.content], ["text"])
        self.assertEqual(result.structured_content["reason"], "game_not_running")
        self.assertFalse(result.is_error,
                         "a refusal is a normal result, not a protocol error")


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class PositiveControlTests(unittest.TestCase):
    """The one test here that captures the real screen.

    `screenshot_screen` is a positive control: it points the instrument at
    something certainly present. If this fails, every flat *game* capture on this
    machine is uninterpretable, which is exactly the situation
    `AGENTS.md` § "Prove the Instrument" says not to reason from.
    """

    def test_the_real_primary_screen_captures_more_than_one_colour(self):
        image = capture.grab_bbox(None)
        self.assertGreater(image.width, 0)
        self.assertFalse(capture.is_flat(image),
                         "the real screen captured as a single flat colour; the "
                         "capture instrument cannot be trusted on this machine")

    def test_the_self_check_agrees_with_that_reading(self):
        from tools.hs_drive_mcp import checks
        status, detail = checks.check_screenshot_screen()
        self.assertEqual(status, "pass", detail)
        self.assertIn("distinct", detail)


if __name__ == "__main__":
    unittest.main()
