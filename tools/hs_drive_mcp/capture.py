"""Find the game's window, and turn it into a PNG a human can look at.

Two jobs, both Win32 reads plus Pillow, and one rule shared with the rest of
this server: **a capture that shows nothing is reported as such, never returned
as if it were a picture of the game.**

*Identification.* `procs.game_pids()` says which processes are the game;
`EnumWindows` plus `GetWindowThreadProcessId` says which windows belong to them.
The window class is deliberately not used: GameMaker's class name is unverified
for this build and the PID already answers the question. Of the visible,
non-minimized top-level windows of those PIDs, the largest by area is the game
-- a splash or tool window is smaller. Minimized is its own refusal
(`window_minimized`), because a minimized window has a rectangle and would
otherwise capture as whatever is behind it.

*Capture.* Two methods, both reported as `capture_method` so a later reader
knows which one produced a given file:

* `grab_bbox` -- `ImageGrab.grab(bbox=…, all_screens=True)`. The screen region
  the window occupies. `all_screens` is on only when a bbox is given, because
  window rectangles live in virtual-desktop coordinates (a second monitor to the
  left has negative ones), while a bare `grab()` means "the primary monitor",
  which is what `target="screen"` asks for.
* `grab_window` -- `ImageGrab.grab(window=hwnd)`, which asks the window for its
  own contents.

Which of them works depends on how the game is presenting itself, and exclusive
fullscreen may yield a single flat colour under both. That is measured live, per
display mode, rather than assumed -- and a flat result comes back with
`warning: "image_is_flat"` attached, which is the difference between "the
instrument captured black" and "the game is black".

`target="screen"` is this module's positive control: it captures something that
is certainly there, so a flat *game* capture beside a non-flat *screen* capture
localises the problem to the window rather than to Pillow. That is what the
`screenshot_screen` self-check runs.

Pillow is imported inside the functions that need it so this module imports on a
machine that has neither Pillow nor Windows -- `checks.py` imports it, and the
root suite runs on CI's `ubuntu-latest`.
"""
from __future__ import annotations

import ctypes
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import launcher_bridge, procs, results

#: `%LOCALAPPDATA%\HSDriveMcp\screenshots` unless this names somewhere else.
#: Every test sets it, for the same reason the save tools have their overrides:
#: a suite that wrote into the owner's real directory would be one mistake away
#: from a mess nobody asked for.
SCREENSHOT_DIR_ENV = "HS_DRIVE_SCREENSHOT_DIR"

CAPTURE_METHODS = ("grab_bbox", "grab_window")

#: The file keeps its full resolution; only the copy that travels over the
#: transport is shrunk. A 2560-wide screenshot is ~4 MB of base64 in a message
#: that also has to carry a result the model can read.
MAX_TRANSPORT_WIDTH = 1280

FLAT_WARNING = "image_is_flat"

TARGETS = ("game", "screen")


# --------------------------------------------------------------------------
# Win32. One thin wrapper per call, and `user32()` is resolved per call so a
# test can replace the whole surface with a fake that fills the same pointers.
# --------------------------------------------------------------------------

class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def user32() -> Any:
    return ctypes.WinDLL("user32", use_last_error=True)


def _handle(hwnd: Any) -> ctypes.c_void_p:
    """A window handle as a pointer-sized argument.

    Not an int: an unprototyped ctypes call passes a Python int as a 32-bit
    `int`, which truncates a 64-bit HWND. The bug that produces is a call that
    works for years and then does not.
    """
    return ctypes.c_void_p(int(hwnd))


def _enum_proc() -> Any:
    """`WNDENUMPROC`, built on demand -- `WINFUNCTYPE` is Windows-only."""
    return ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)


def window_handles() -> list[int]:
    """Every top-level window handle, in `EnumWindows` order."""
    found: list[int] = []

    def collect(hwnd: Any, _lparam: Any) -> bool:
        if hwnd:
            found.append(int(hwnd))
        return True

    user32().EnumWindows(_enum_proc()(collect), None)
    return found


def window_pid(hwnd: int) -> int:
    """The process id owning `hwnd`, or 0 when it cannot be read."""
    pid = ctypes.c_ulong(0)
    user32().GetWindowThreadProcessId(_handle(hwnd), ctypes.pointer(pid))
    return int(pid.value)


def window_is_visible(hwnd: int) -> bool:
    return bool(user32().IsWindowVisible(_handle(hwnd)))


def window_is_minimized(hwnd: int) -> bool:
    return bool(user32().IsIconic(_handle(hwnd)))


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    rect = RECT()
    if not user32().GetWindowRect(_handle(hwnd), ctypes.pointer(rect)):
        return None
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def post_message(hwnd: int, message: int) -> tuple[bool, str]:
    """Post a message with no parameters, and say whether it was accepted.

    `PostMessageW` rather than `SendMessageW`: posting queues the message and
    returns, so a game that takes a while to shut down cannot block this server
    inside a Win32 call.
    """
    api = user32()
    if api.PostMessageW(_handle(hwnd), int(message), 0, 0):
        return True, ""
    return False, (f"PostMessageW to window {hwnd} failed "
                   f"(GetLastError {ctypes.get_last_error()})")


def visible_windows_for_pids(pids: list[int] | set[int]) -> list[dict[str, Any]]:
    """Every visible top-level window belonging to one of `pids`.

    Minimized windows are included and flagged, not dropped: closing one is
    perfectly reasonable, and capturing one is not, so the two callers apply
    their own policy to the same reading rather than each enumerating windows
    its own way.
    """
    wanted = {int(pid) for pid in pids}
    if not wanted:
        return []
    found: list[dict[str, Any]] = []
    for hwnd in window_handles():
        if not window_is_visible(hwnd):
            continue
        pid = window_pid(hwnd)
        if pid not in wanted:
            continue
        rect = window_rect(hwnd)
        if rect is None:
            continue
        left, top, right, bottom = rect
        found.append({
            "hwnd": hwnd,
            "pid": pid,
            "bbox": (left, top, right, bottom),
            "area": max(0, right - left) * max(0, bottom - top),
            "minimized": window_is_minimized(hwnd),
        })
    return found


# --------------------------------------------------------------------------
# Pillow
# --------------------------------------------------------------------------

def pillow_status() -> tuple[bool, str]:
    """(available, why not). Used by the self-check so a missing Pillow is
    `skipped` with a reason rather than a `fail` naming an ImportError."""
    try:
        import PIL  # noqa: F401
        from PIL import ImageGrab  # noqa: F401
    except ImportError as exc:
        return False, (f"Pillow is not importable ({exc}); run "
                       "`py -3 -m pip install -r tools/hs_drive_mcp/requirements.txt`")
    return True, ""


def grab_bbox(bbox: tuple[int, int, int, int] | None) -> Any:
    """A screen region, or the primary monitor when `bbox` is None."""
    from PIL import ImageGrab
    return ImageGrab.grab(bbox=bbox, all_screens=bbox is not None)


def grab_window(hwnd: int) -> Any:
    """The window's own contents. Pillow >= 11 accepts `window=`."""
    from PIL import ImageGrab
    return ImageGrab.grab(window=int(hwnd))


def is_flat(image: Any) -> bool:
    """True when every pixel is the same value.

    `getextrema()` per band rather than counting colours: it is one pass, it
    needs no bound on the number of distinct values, and "min equals max in
    every band" is exactly "one distinct pixel value".
    """
    return all(low == high for low, high in image.convert("RGB").getextrema())


def screenshot_dir() -> Path:
    override = os.environ.get(SCREENSHOT_DIR_ENV)
    if override:
        return Path(override)
    return launcher_bridge.local_app_data() / "HSDriveMcp" / "screenshots"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _write_png(image: Any, label: str) -> Path:
    directory = screenshot_dir()
    directory.mkdir(parents=True, exist_ok=True)
    suffix = f"_{label}" if label else ""
    path = directory / f"{_stamp()}{suffix}.png"
    image.save(path, format="PNG")
    return path


def transport_image(path: Path, max_width: int = MAX_TRANSPORT_WIDTH) -> tuple[bytes, int, int]:
    """PNG bytes for the message, downscaled if wide. `(data, width, height)`.

    The file on disk keeps its full resolution -- it is the artefact a human
    opens afterwards -- and only this copy is shrunk. Returned as bytes from a
    separate call rather than as a field of the result envelope, because the
    envelope is serialised as JSON and bytes in it would fail the whole tool
    call rather than one field of it.
    """
    import io

    from PIL import Image

    with Image.open(path) as image:
        image.load()
        copy = image.convert("RGB")
    if copy.width > max_width:
        height = max(1, round(copy.height * max_width / copy.width))
        from PIL.Image import Resampling
        copy = copy.resize((max_width, height), Resampling.LANCZOS)
    buffer = io.BytesIO()
    copy.save(buffer, format="PNG")
    return buffer.getvalue(), copy.width, copy.height


# --------------------------------------------------------------------------
# The tool
# --------------------------------------------------------------------------

def resolve_game_window(pids: list[int], tool: str) -> dict[str, Any]:
    """The window to capture, or a refusal naming which of the three states."""
    windows = visible_windows_for_pids(pids)
    if not windows:
        return results.refuse(
            tool, "no_visible_window_for_pid",
            f"Hero Siege is running as pid(s) {pids} but none of them owns a "
            "visible top-level window. If the game has only just started, wait "
            "for its window to appear and try again.")
    candidates = [window for window in windows if not window["minimized"]]
    if not candidates:
        return results.refuse(
            tool, "window_minimized",
            f"The only visible window of pid(s) {pids} is minimized "
            f"(hwnd {windows[0]['hwnd']}), so capturing its rectangle would "
            "photograph whatever is behind it. Restore the window first.")
    return max(candidates, key=lambda window: window["area"])


def screenshot(target: str = "game", *, label: str = "",
               method: str = "grab_bbox", gate: Callable[[], tuple[str, str]] | None = None,
               tool: str = "hs_screenshot") -> dict[str, Any]:
    """Capture `target` to a PNG and report where it went and what it shows."""
    if target not in TARGETS:
        return results.refuse(
            tool, "invalid_command",
            f"target must be one of {TARGETS}, not {target!r}.")
    if method not in CAPTURE_METHODS:
        return results.refuse(
            tool, "invalid_command",
            f"method must be one of {CAPTURE_METHODS}, not {method!r}.")
    available, why = pillow_status()
    if not available:
        return results.refuse(tool, "capture_unavailable", why)

    gate = procs.gate if gate is None else gate
    window: dict[str, Any] | None = None
    if target == "game":
        state, state_why = gate()
        if state == procs.NOT_RUNNING:
            return results.refuse(
                tool, "game_not_running",
                f"{state_why} There is no game window to capture; pass "
                "target=\"screen\" to capture the desktop instead.")
        if state != procs.RUNNING:
            token = {procs.ENGINE_MISSING: "engine_source_missing",
                     procs.ENGINE_UNUSABLE: "engine_import_failed"}.get(
                         state, "game_state_unknown")
            return results.refuse(tool, token, f"{state_why} So which windows "
                                               "belong to the game is unknown.")
        window = resolve_game_window(procs.game_pids(), tool)
        if results.is_refusal(window):
            return window

    if target == "screen":
        image = grab_bbox(None)
        used, hwnd, pid = "grab_bbox", 0, 0
        bbox = (0, 0, image.width, image.height)
    elif method == "grab_window":
        image = grab_window(window["hwnd"])
        used, hwnd, pid = "grab_window", window["hwnd"], window["pid"]
        bbox = window["bbox"]
    else:
        image = grab_bbox(window["bbox"])
        used, hwnd, pid = "grab_bbox", window["hwnd"], window["pid"]
        bbox = window["bbox"]

    flat = is_flat(image)
    path = _write_png(image, label)
    return results.ok(
        tool, target=target, path=str(path), width=image.width,
        height=image.height, bbox=list(bbox), capture_method=used, hwnd=hwnd,
        pid=pid, flat=flat, bytes_written=path.stat().st_size,
        warning=FLAT_WARNING if flat else "",
        detail=(f"{image.width}x{image.height} {used} capture of {target}"
                + (". Every pixel is the same value: this is a picture of "
                   "nothing, not a picture of a black game. Try the other "
                   "capture_method, or run the game windowed or borderless."
                   if flat else ".")))
