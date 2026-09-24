"""Inject keystrokes and mouse events into the game's own window.

This is an *instrument*, not a feature. It exists so one question can be
measured -- can anything outside the game drive its main menu as far as a
loaded character -- and it makes no claim about the answer. What it does is
narrow and stated in full here:

* **Two routes, because they reach different depths.** `send_input` calls
  `SendInput`, which the operating system replays into the foreground window's
  input queue: indistinguishable from a keyboard or a mouse, and therefore
  visible to `GetAsyncKeyState`-style reads as well as to window messages.
  `post_message` calls `PostMessageW`, which appends a message to one window's
  queue and touches no OS key state at all. A runner that polls the device
  state sees the first and not the second, so measuring both separates "the OS
  saw it" from "the game saw it". Neither route is better; they answer
  different halves of the question.

* **Each route's delivery signal is read, because each route has exactly one.**
  `SendInput` returns how many records the system accepted; `PostMessageW`
  returns whether the message was queued at all, and nothing acknowledges it
  afterwards. A posted message is refused on precisely the cases that matter to
  this measurement -- a UIPI integrity mismatch (the game launched elevated for
  Aurie injection while this process is not), a window destroyed part way
  through a sequence, a full message queue -- so an unread BOOL would report
  "N of N action(s) sent" having delivered nothing, and the live procedure's
  `keyboard_check` reading false would then measure the instrument rather than
  the game (`AGENTS.md` § "Prove the Instrument Before Trusting a Negative
  Result"). A refusal stops the sequence, is counted in `records_rejected`, and
  names the message and the error code.

* **Nothing is sent unless the target is a window of a running game process.**
  The gate is `procs.gate()`, the window is `capture.resolve_game_window()`,
  and for `send_input` the foreground window is compared against the game's
  hwnd **immediately before every single `SendInput` call** rather than once at
  the start (`AGENTS.md` § "Check a Permission Where It Is Used": a permission
  checked at a convenient boundary is a permission the consumer has already
  spent). A sequence that loses the foreground half way through stops there and
  reports how far it got, because the alternative is typing the rest of it into
  whatever window took focus.

* **Every point is checked before anything is sent.** A click outside the
  client area is refused with nothing injected, so a partly-applied sequence
  cannot be produced by a coordinate typo.

Coordinates default to the **client area**, which is exactly what a
`hs_screenshot("game", capture_method="grab_window")` pixel is -- measured in
the game workorder's live gate on 2026-09-20, where a 1920x1080 client
captured as 1920x1080. So a point read off that screenshot can be passed
straight in. `space: "screen"` takes virtual-desktop coordinates instead, for
the caller that already has one.

Every Win32 entry point goes through `WIN32`, one table of plain Python
callables. The tests replace entries in that table, which is why this module
imports on a machine with no Windows and no Pillow, and why the assertions can
read the `INPUT` records that would have been injected rather than guessing
from a pointer. Nothing here imports the MCP SDK; `server.py` does the
registering.

What this module deliberately does **not** do:

* No forceful focus grab **by default, and never for `hs_input`.** Windows'
  foreground lock exists for the user's benefit, and stealing it is the kind
  of thing that is convenient once and unwelcome forever -- so `hs_input`
  never asks for more than the one `SetForegroundWindow` attempt below. Only
  the caller named in `force_focus`'s own doc (`hs_select_character`, a
  scripted flow started right after `hs_launch`) may opt in to the bounded
  escalation chain: `AttachThreadInput` to the foreground thread's input
  state, then one zero-effect `SendInput` unlock record, each followed by a
  re-read of the foreground before the next is tried. It sends no key,
  button or movement to whatever window was in front; the one input event it
  can produce there is the zero mouse record, and even that is only reached
  if the attach step did not already give the game focus. If every step
  fails, the answer is still `foreground_not_game`.
* No key-state writes, no hooks, no suspension of anything. Every event this
  module produces is one a keyboard or a mouse could have produced.
"""
from __future__ import annotations

import ctypes
import time
from typing import Any, Callable

from . import capture, lease, procs, results

TOOL = "hs_input"

ROUTE_SEND_INPUT = "send_input"
ROUTE_POST_MESSAGE = "post_message"
ROUTES = (ROUTE_SEND_INPUT, ROUTE_POST_MESSAGE)

#: `focus_via` step names, in escalation order (owner decision "Let the tool
#: force focus", 2026-09-21). `FOCUS_SET_FOREGROUND` is unchanged from before
#: this workorder and runs whether or not `force_focus` is set; the other two
#: run only when `force_focus` is true and the previous step did not take.
#: See the module docstring for what each one does.
FOCUS_SET_FOREGROUND = "set_foreground"
FOCUS_ATTACH_THREAD_INPUT = "attach_thread_input"
FOCUS_INPUT_UNLOCK = "input_unlock"
FOCUS_STEPS = (FOCUS_SET_FOREGROUND, FOCUS_ATTACH_THREAD_INPUT,
              FOCUS_INPUT_UNLOCK)

#: `focus_via` values outside the step chain: the game was already in front
#: (no step needed), or no step was ever relevant (`post_message`, or
#: `require_foreground=False`, which still means never take focus).
FOCUS_ALREADY_FOREGROUND = "already_foreground"
FOCUS_NOT_REQUIRED = "not_required"

#: How the foreground is re-read after each step, since `SetForegroundWindow`
#: can return before the switch is visible: a short, bounded settle rather
#: than one immediate read. Three reads 50 ms apart is 150 ms per step, so
#: all three steps together stay well under the 1 s the mechanism doc caps
#: the whole chain at.
FOCUS_SETTLE_READS = 3
FOCUS_SETTLE_INTERVAL_S = 0.05

ACTION_TYPES = ("key", "key_down", "key_up", "click", "move", "wait")
BUTTONS = ("left", "right")
SPACES = ("client", "screen")

#: One call is one short sequence. The cap is not about safety -- it is about
#: a caller being able to say what a call did when it comes back.
MAX_ACTIONS = 64

#: Ten seconds of holding or waiting. Longer than any menu needs, and short
#: enough that a mistake does not wedge a session behind a held key.
MAX_MS = 10000

DEFAULT_HOLD_MS = 60

#: `docs/character-select-research.md` C-1.10: a `click` with nothing between
#: its button-down and button-up lands both records inside one frame, which a
#: 144 fps sample loop never sees held -- it moves the cursor, lights the
#: button under it, reports `complete: true`, and activates nothing. 120 ms
#: between the records changed the room every time; 60 ms is what C-1.7
#: measured for a held *key*, not a button, so it is not reused here.
DEFAULT_CLICK_HOLD_MS = 120

# -- Win32 constants -------------------------------------------------------

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
}

MAPVK_VK_TO_VSC = 0

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205

BUTTON_MESSAGES = {
    "left": (WM_LBUTTONDOWN, WM_LBUTTONUP),
    "right": (WM_RBUTTONDOWN, WM_RBUTTONUP),
}

#: Names for the one place a message number would be unreadable: the line that
#: reports a post the system refused.
MESSAGE_NAMES = {
    WM_KEYDOWN: "WM_KEYDOWN", WM_KEYUP: "WM_KEYUP",
    WM_MOUSEMOVE: "WM_MOUSEMOVE", WM_LBUTTONDOWN: "WM_LBUTTONDOWN",
    WM_LBUTTONUP: "WM_LBUTTONUP", WM_RBUTTONDOWN: "WM_RBUTTONDOWN",
    WM_RBUTTONUP: "WM_RBUTTONUP",
}

MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002

BUTTON_KEYSTATE = {"left": MK_LBUTTON, "right": MK_RBUTTON}

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

#: The keys whose scan code needs the extended prefix: navigation cluster
#: (`VK_PRIOR` 33 through `VK_DOWN` 40), `VK_INSERT` 45 and `VK_DELETE` 46.
#: Without the bit the arrows arrive as their numeric-keypad twins, which is a
#: bug that looks like "the menu ignores arrow keys".
EXTENDED_KEYS = frozenset(range(33, 41)) | {45, 46}

#: `SendInput` refuses a virtual key of 0, and 255 is `VK__none_`.
MIN_VK = 1
MAX_VK = 254


# --------------------------------------------------------------------------
# Structures. Plain `ctypes.Structure`s, so they exist off Windows too and the
# tests can read back exactly what would have been injected.
# --------------------------------------------------------------------------

ULONG_PTR = ctypes.c_size_t


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ULONG_PTR)]


class _InputPayload(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    """One `SendInput` record. `record.ki` / `record.mi` reach the union."""
    _anonymous_ = ("payload",)
    _fields_ = [("type", ctypes.c_ulong), ("payload", _InputPayload)]


def keyboard_record(scan: int, flags: int) -> INPUT:
    """A keyboard record.

    `wVk` is 0 on purpose: MSDN requires it when `KEYEVENTF_SCANCODE` is set,
    and scan codes are what this module sends -- a scan code is what a keyboard
    puts on the wire, so the runtime's own translation produces the virtual key
    rather than this process asserting one.
    """
    record = INPUT(type=INPUT_KEYBOARD)
    record.ki = KEYBDINPUT(wVk=0, wScan=int(scan) & 0xFFFF, dwFlags=int(flags),
                           time=0, dwExtraInfo=0)
    return record


def mouse_record(flags: int, dx: int = 0, dy: int = 0) -> INPUT:
    record = INPUT(type=INPUT_MOUSE)
    record.mi = MOUSEINPUT(dx=int(dx), dy=int(dy), mouseData=0,
                           dwFlags=int(flags), time=0, dwExtraInfo=0)
    return record


# --------------------------------------------------------------------------
# Win32. One wrapper per call, resolved per call -- see `capture.user32()` for
# the same argument, and `_handle()` for why an HWND is never a bare int.
# --------------------------------------------------------------------------

def user32() -> Any:
    return ctypes.WinDLL("user32", use_last_error=True)


def kernel32() -> Any:
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _handle(hwnd: Any) -> ctypes.c_void_p:
    """An HWND as a pointer-sized argument, never a 32-bit `int`."""
    return ctypes.c_void_p(int(hwnd))


def _send_input(records: list[INPUT]) -> int:
    """Inject `records`; returns how many the system accepted."""
    array = (INPUT * len(records))(*records)
    return int(user32().SendInput(len(records), array, ctypes.sizeof(INPUT)))


def _post_message(hwnd: int, message: int, wparam: int,
                  lparam: int) -> tuple[bool, int]:
    """`(queued, the error code when it was not)`.

    The BOOL is this route's whole delivery signal, so it is returned rather
    than dropped, and `GetLastError` with it: `ERROR_ACCESS_DENIED` (5) is a
    UIPI integrity mismatch and `ERROR_NOT_ENOUGH_QUOTA` (1816) a full queue,
    two different machines that both look like "the game ignored it".
    `set_last_error(0)` first so the code read back belongs to this call and
    not to whatever ran before it.
    """
    ctypes.set_last_error(0)
    queued = bool(user32().PostMessageW(_handle(hwnd),
                                        ctypes.c_uint(int(message)),
                                        ctypes.c_size_t(int(wparam)),
                                        ctypes.c_ssize_t(int(lparam))))
    return queued, (0 if queued else ctypes.get_last_error())


def _get_foreground_window() -> int:
    """The foreground hwnd, or 0. `restype` is set because the default `c_int`
    truncates a 64-bit handle to something that is almost always wrong."""
    api = user32()
    api.GetForegroundWindow.restype = ctypes.c_void_p
    return int(api.GetForegroundWindow() or 0)


def _set_foreground_window(hwnd: int) -> bool:
    return bool(user32().SetForegroundWindow(_handle(hwnd)))


def _get_window_thread_id(hwnd: int) -> int:
    """The thread that owns `hwnd`, or 0. The process id out-parameter is
    not needed here, so it is passed as null."""
    return int(user32().GetWindowThreadProcessId(_handle(hwnd), None))


def _get_current_thread_id() -> int:
    return int(kernel32().GetCurrentThreadId())


def _attach_thread_input(this_id: int, other_id: int, attach: bool) -> bool:
    """Share (or stop sharing) input state between two threads. See the
    module docstring's escalation section for why this makes the foreground
    lock treat `this_id` as part of `other_id`'s input queue."""
    return bool(user32().AttachThreadInput(
        ctypes.c_ulong(int(this_id)), ctypes.c_ulong(int(other_id)),
        ctypes.c_int(1 if attach else 0)))


def _send_focus_unlock() -> int:
    """One zero-effect mouse record -- no move, no button, no wheel -- sent
    through its own entry rather than `SendInput`'s, so a test (and a reader
    of a captured trace) can tell it apart from a real click's records. It is
    the one input event this module ever sends to a window that is not the
    game, and it relies only on the documented "received the last input
    event" foreground condition."""
    array = (INPUT * 1)(mouse_record(0))
    return int(user32().SendInput(1, array, ctypes.sizeof(INPUT)))


def _client_to_screen(hwnd: int, x: int, y: int) -> tuple[int, int] | None:
    point = POINT(int(x), int(y))
    if not user32().ClientToScreen(_handle(hwnd), ctypes.pointer(point)):
        return None
    return int(point.x), int(point.y)


def _get_client_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    rect = capture.RECT()
    if not user32().GetClientRect(_handle(hwnd), ctypes.pointer(rect)):
        return None
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def _get_system_metrics(index: int) -> int:
    return int(user32().GetSystemMetrics(int(index)))


def _map_virtual_key(vk: int, map_type: int) -> int:
    return int(user32().MapVirtualKeyW(int(vk), int(map_type)))


def _get_dpi_for_window(hwnd: int) -> int | None:
    """The window's DPI, or None where the symbol is absent.

    Missing is not a failure: `GetDpiForWindow` arrived in Windows 10 1607, and
    a tool that refused without it would be refusing over a reporting field.
    """
    try:
        function = user32().GetDpiForWindow
    except (AttributeError, OSError):
        return None
    value = int(function(_handle(hwnd)))
    return value or None


#: The whole Win32 surface, in one place, so a test replaces it wholesale and
#: no call can slip past the replacement by being written inline somewhere.
WIN32: dict[str, Callable[..., Any]] = {
    "SendInput": _send_input,
    "PostMessageW": _post_message,
    "GetForegroundWindow": _get_foreground_window,
    "SetForegroundWindow": _set_foreground_window,
    "ClientToScreen": _client_to_screen,
    "GetClientRect": _get_client_rect,
    "GetSystemMetrics": _get_system_metrics,
    "MapVirtualKeyW": _map_virtual_key,
    "GetDpiForWindow": _get_dpi_for_window,
    "GetWindowThreadProcessId": _get_window_thread_id,
    "GetCurrentThreadId": _get_current_thread_id,
    "AttachThreadInput": _attach_thread_input,
    "SendFocusUnlock": _send_focus_unlock,
    "sleep": time.sleep,
}


# --------------------------------------------------------------------------
# Validation. All of it, before anything is injected.
# --------------------------------------------------------------------------

def _integer(value: Any, name: str, low: int, high: int) -> tuple[int, str]:
    """`(value, why not)`. `bool` is rejected: `True` is an `int` in Python,
    and `vk: true` silently meaning `vk: 1` is not a reading anyone wants."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0, f"{name} must be an integer, not {type(value).__name__}"
    if not low <= value <= high:
        return 0, f"{name} must be between {low} and {high}, not {value}"
    return int(value), ""


def normalise(actions: Any) -> tuple[list[dict[str, Any]], str]:
    """Turn the caller's list into a checked plan, or say what is wrong.

    Only shape is checked here. Whether a point lands inside the window needs
    the window, so it is checked in `inject()` -- still before anything is sent.
    """
    if not isinstance(actions, list) or not actions:
        return [], ("actions must be a non-empty list of action objects, e.g. "
                    "[{\"type\": \"key\", \"vk\": 13}].")
    if len(actions) > MAX_ACTIONS:
        return [], (f"at most {MAX_ACTIONS} actions per call; this call has "
                    f"{len(actions)}. Split it, so a reply says what ran.")

    plan: list[dict[str, Any]] = []
    for index, raw in enumerate(actions):
        where = f"action {index}"
        if not isinstance(raw, dict):
            return [], f"{where} is a {type(raw).__name__}, not an object."
        kind = raw.get("type")
        if kind not in ACTION_TYPES:
            return [], (f"{where} has type {kind!r}; the types are "
                        f"{', '.join(ACTION_TYPES)}.")
        entry: dict[str, Any] = {"type": kind}

        if kind in ("key", "key_down", "key_up"):
            vk, why = _integer(raw.get("vk"), f"{where} vk", MIN_VK, MAX_VK)
            if why:
                return [], why + "; vk is a Windows virtual-key code."
            entry["vk"] = vk
            if kind == "key":
                hold, why = _integer(raw.get("hold_ms", DEFAULT_HOLD_MS),
                                     f"{where} hold_ms", 0, MAX_MS)
                if why:
                    return [], why + "."
                entry["hold_ms"] = hold
        elif kind == "wait":
            milliseconds, why = _integer(raw.get("ms"), f"{where} ms", 0, MAX_MS)
            if why:
                return [], why + "."
            entry["ms"] = milliseconds
        else:  # click, move
            for axis in ("x", "y"):
                value, why = _integer(raw.get(axis), f"{where} {axis}",
                                      -1_000_000, 1_000_000)
                if why:
                    return [], why + "."
                entry[axis] = value
            space = raw.get("space", "client")
            if space not in SPACES:
                return [], (f"{where} space is {space!r}; it is one of "
                            f"{', '.join(SPACES)}.")
            entry["space"] = space
            if kind == "click":
                button = raw.get("button", "left")
                if button not in BUTTONS:
                    return [], (f"{where} button is {button!r}; it is one of "
                                f"{', '.join(BUTTONS)}.")
                entry["button"] = button
                hold, why = _integer(raw.get("hold_ms", DEFAULT_CLICK_HOLD_MS),
                                     f"{where} hold_ms", 0, MAX_MS)
                if why:
                    return [], why + "."
                entry["hold_ms"] = hold
        plan.append(entry)
    return plan, ""


# --------------------------------------------------------------------------
# The tool
# --------------------------------------------------------------------------

def _geometry(hwnd: int) -> tuple[dict[str, Any], str]:
    """Everything the injection needs to know about the window, or why not."""
    client = WIN32["GetClientRect"](hwnd)
    if client is None:
        return {}, (f"GetClientRect failed for hwnd {hwnd}, so the window's "
                    "client area is unknown and no point in it can be checked.")
    origin = WIN32["ClientToScreen"](hwnd, 0, 0)
    if origin is None:
        return {}, (f"ClientToScreen failed for hwnd {hwnd}, so where the "
                    "window's client area sits on screen is unknown.")
    width = max(0, client[2] - client[0])
    height = max(0, client[3] - client[1])
    virtual = tuple(WIN32["GetSystemMetrics"](metric) for metric in
                    (SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN,
                     SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN))
    if virtual[2] <= 0 or virtual[3] <= 0:
        return {}, (f"GetSystemMetrics reported a virtual screen of "
                    f"{virtual[2]}x{virtual[3]}, which cannot be normalised "
                    "over, so an absolute mouse position is unavailable.")
    return {
        "hwnd": hwnd,
        "client_size": [width, height],
        "client_origin": list(origin),
        "client_rect": [origin[0], origin[1], origin[0] + width,
                        origin[1] + height],
        "window_rect": list(capture.window_rect(hwnd) or []),
        "virtual": list(virtual),
        "dpi": WIN32["GetDpiForWindow"](hwnd),
    }, ""


def _points(plan: list[dict[str, Any]], geometry: dict[str, Any]) -> str:
    """Resolve every point to both spaces, or say which one is out of bounds.

    Both coordinates are computed for every point action up front, because the
    two routes need different ones -- `SendInput` normalises screen
    coordinates, a posted message carries client ones -- and because a point
    that cannot be resolved must be found before the first event is sent.
    """
    width, height = geometry["client_size"]
    origin_x, origin_y = geometry["client_origin"]
    vx, vy, vcx, vcy = geometry["virtual"]
    for index, entry in enumerate(plan):
        if entry["type"] not in ("click", "move"):
            continue
        x, y = entry["x"], entry["y"]
        if entry["space"] == "client":
            if not (0 <= x < width and 0 <= y < height):
                return (f"action {index} is at client ({x}, {y}), outside the "
                        f"game's {width}x{height} client area. A "
                        "grab_window screenshot pixel is a client coordinate.")
            screen = WIN32["ClientToScreen"](geometry["hwnd"], x, y)
            if screen is None:
                return (f"action {index}: ClientToScreen failed for "
                        f"({x}, {y}).")
            entry["client_point"] = [x, y]
            entry["screen_point"] = list(screen)
        else:
            if not (vx <= x < vx + vcx and vy <= y < vy + vcy):
                return (f"action {index} is at screen ({x}, {y}), outside the "
                        f"virtual screen {vcx}x{vcy} at ({vx}, {vy}).")
            entry["screen_point"] = [x, y]
            entry["client_point"] = [x - origin_x, y - origin_y]
    return ""


def _absolute(point: list[int], virtual: list[int]) -> tuple[int, int]:
    """A screen point as `SendInput`'s 0..65535 virtual-desktop coordinates."""
    vx, vy, vcx, vcy = virtual
    return ((point[0] - vx) * 65535 // vcx, (point[1] - vy) * 65535 // vcy)


def _raise_foreground(hwnd: int,
                      force_focus: bool) -> tuple[str | None, list[dict[str, Any]]]:
    """Bring `hwnd` to the foreground, escalating through `FOCUS_STEPS` only
    as far as `force_focus` allows. Returns the step that took (or `None` if
    every step tried still left some other window in front) and the trail of
    attempts: one `{"step", "foreground_after"}` per step actually tried,
    plus a `skipped` reason for `attach_thread_input` when it could not be
    attempted at all. `set_foreground` always runs, whether or not
    `force_focus` is set -- see the module docstring.
    """
    attempts: list[dict[str, Any]] = []

    def settle(step: str) -> bool:
        """Re-read the foreground, bounded, after `step`. `SetForegroundWindow`
        can return before the switch is visible, so one read is not trusted."""
        raised = WIN32["GetForegroundWindow"]()
        for _ in range(FOCUS_SETTLE_READS):
            if raised == hwnd:
                break
            WIN32["sleep"](FOCUS_SETTLE_INTERVAL_S)
            raised = WIN32["GetForegroundWindow"]()
        attempts.append({"step": step, "foreground_after": raised})
        return raised == hwnd

    WIN32["SetForegroundWindow"](hwnd)
    if settle(FOCUS_SET_FOREGROUND):
        return FOCUS_SET_FOREGROUND, attempts
    if not force_focus:
        return None, attempts

    # `attach_thread_input`: share input state with whatever thread owns the
    # foreground, so the lock treats this thread as part of its input queue.
    # Skip it, and say why, when there is nothing sane to attach to.
    foreground_hwnd = WIN32["GetForegroundWindow"]()
    this_id = WIN32["GetCurrentThreadId"]()
    other_id = (WIN32["GetWindowThreadProcessId"](foreground_hwnd)
               if foreground_hwnd else 0)
    if foreground_hwnd == 0:
        attempts.append({"step": FOCUS_ATTACH_THREAD_INPUT,
                         "foreground_after": foreground_hwnd,
                         "skipped": "no foreground window"})
    elif other_id == 0:
        attempts.append({"step": FOCUS_ATTACH_THREAD_INPUT,
                         "foreground_after": foreground_hwnd,
                         "skipped": "GetWindowThreadProcessId read 0 for the "
                                   "foreground window"})
    elif other_id == this_id:
        attempts.append({"step": FOCUS_ATTACH_THREAD_INPUT,
                         "foreground_after": foreground_hwnd,
                         "skipped": "the foreground window already belongs "
                                   "to this thread"})
    elif not WIN32["AttachThreadInput"](this_id, other_id, True):
        attempts.append({"step": FOCUS_ATTACH_THREAD_INPUT,
                         "foreground_after": foreground_hwnd,
                         "skipped": "AttachThreadInput returned FALSE"})
    else:
        # Only what actually attached is detached, and only in `finally`, so
        # an exception here still leaves the shared input state torn down.
        try:
            WIN32["SetForegroundWindow"](hwnd)
            attached_ok = settle(FOCUS_ATTACH_THREAD_INPUT)
        finally:
            WIN32["AttachThreadInput"](this_id, other_id, False)
        if attached_ok:
            return FOCUS_ATTACH_THREAD_INPUT, attempts

    # `input_unlock`: one zero-effect SendInput record, relying on the
    # documented "received the last input event" foreground condition. The
    # one input event this module ever sends to another window; it carries
    # no key, button or movement.
    WIN32["SendFocusUnlock"]()
    WIN32["SetForegroundWindow"](hwnd)
    if settle(FOCUS_INPUT_UNLOCK):
        return FOCUS_INPUT_UNLOCK, attempts
    return None, attempts


def inject(actions: Any, *, route: str = ROUTE_SEND_INPUT,
           require_foreground: bool = True,
           force_focus: bool = False,
           gate: Callable[[], tuple[str, str]] | None = None,
           tool: str = TOOL, lease_checked: bool = False) -> dict[str, Any]:
    """Send `actions` to the game window and report exactly what was sent.

    `force_focus` opts a caller in to the bounded `FOCUS_STEPS` escalation
    when the plain `SetForegroundWindow` attempt does not take; `hs_input`
    never sets it (see the module docstring). Every result names the step
    that gave the game focus in `focus_via`.

    The game lease is asked first, before the actions are even parsed, so a
    second session sees `lease_held` and nothing is sent; every other answer
    carries `lease: "held" | "none"`. `lease_checked=True` is for
    `hs_select_character`, which asked once for the whole sequence.

    Refusals: `lease_held`, `lease_unavailable`, `invalid_input`,
    `game_not_running`, `game_state_unknown`,
    `engine_source_missing`, `engine_import_failed`,
    `no_visible_window_for_pid`, `window_minimized`, `foreground_not_game`.
    """
    if lease_checked:
        return _inject(actions, route=route, require_foreground=require_foreground,
                       force_focus=force_focus, gate=gate, tool=tool)
    refusal = lease.guard(tool)
    if refusal:
        return refusal
    return lease.stamp(_inject(actions, route=route,
                               require_foreground=require_foreground,
                               force_focus=force_focus, gate=gate, tool=tool))


def _inject(actions: Any, *, route: str, require_foreground: bool,
            force_focus: bool, gate: Callable[[], tuple[str, str]] | None,
            tool: str) -> dict[str, Any]:
    started = time.monotonic()

    if route not in ROUTES:
        return results.refuse(
            tool, "invalid_input",
            f"route must be one of {', '.join(ROUTES)}, not {route!r}.")
    plan, why = normalise(actions)
    if why:
        return results.refuse(tool, "invalid_input", why)

    gate = procs.gate if gate is None else gate
    state, state_why = gate()
    if state == procs.NOT_RUNNING:
        return results.refuse(
            tool, "game_not_running",
            f"{state_why} There is no game window to send input to; launch the "
            "game with hs_launch first.")
    if state != procs.RUNNING:
        token = {procs.ENGINE_MISSING: "engine_source_missing",
                 procs.ENGINE_UNUSABLE: "engine_import_failed"}.get(
                     state, "game_state_unknown")
        return results.refuse(
            tool, token,
            f"{state_why} So which window would receive the input is unknown, "
            "and this tool never injects blind.")

    window = capture.resolve_game_window(procs.game_pids(), tool)
    if results.is_refusal(window):
        return window
    hwnd = int(window["hwnd"])

    geometry, why = _geometry(hwnd)
    if why:
        # The window was enumerated and then could not be measured. That is not
        # a usable window for this pid, whatever the reason, and the detail
        # names the read that failed rather than leaving the caller to guess.
        return results.refuse(tool, "no_visible_window_for_pid", why)

    why = _points(plan, geometry)
    if why:
        return results.refuse(tool, "invalid_input", why + " Nothing was sent.")

    report: dict[str, Any] = {
        "route": route,
        "pid": int(window["pid"]),
        "hwnd": hwnd,
        "window_rect": geometry["window_rect"],
        "client_rect": geometry["client_rect"],
        "client_size": geometry["client_size"],
        "dpi": geometry["dpi"],
    }
    foreground_before = WIN32["GetForegroundWindow"]()
    report["foreground_before"] = foreground_before

    focus_via: str | None = FOCUS_NOT_REQUIRED
    focus_attempts: list[dict[str, Any]] = []

    if route == ROUTE_SEND_INPUT:
        if foreground_before == hwnd:
            focus_via = FOCUS_ALREADY_FOREGROUND
        elif not require_foreground:
            focus_via = None
        else:
            focus_via, focus_attempts = _raise_foreground(hwnd, force_focus)

        if focus_via is None:
            if focus_attempts:
                raised = focus_attempts[-1]["foreground_after"]
                tried = ", ".join(entry["step"] for entry in focus_attempts)
                attempted = (
                    "; one SetForegroundWindow attempt did not take. "
                    if tried == FOCUS_SET_FOREGROUND else
                    f"; steps tried: {tried}; none of them took. ")
            else:
                raised = foreground_before
                attempted = ("; require_foreground=false, so no attempt was "
                            "made to raise it. ")
            detail = (
                f"the foreground window is {raised}, not the game's {hwnd}"
                + attempted
                + "SendInput goes to whatever is in front, so nothing was "
                  "sent.")
            if tool == TOOL:
                detail += ' Click the game, or use route="post_message".'
            else:
                detail += " Click the game, or call again once it is in front."
            return results.refuse(
                tool, "foreground_not_game", detail,
                **report, foreground_after=raised, focus_via=None,
                focus_attempts=focus_attempts, actions_done=0,
                actions_total=len(plan), records_sent=0, records_rejected=0,
                complete=False,
                elapsed_s=round(time.monotonic() - started, 3))

    done, rejected, sent = 0, 0, 0

    def emit(records: list[INPUT]) -> str:
        """Inject one record batch, re-proving the permission first."""
        nonlocal rejected, sent
        now = WIN32["GetForegroundWindow"]()
        if now != hwnd:
            return (f"the foreground window changed to {now} part way "
                    "through, so the rest of the sequence was not sent.")
        answer = WIN32["SendInput"](records)
        # A non-integer answer can only come from a replaced table entry, i.e.
        # a test's mock. Reading it as zero would let a mock manufacture a
        # rejection that never happened, so it counts as "no reading taken".
        accepted = (answer if isinstance(answer, int)
                    and not isinstance(answer, bool) else len(records))
        sent += len(records)
        rejected += max(0, len(records) - accepted)
        return ""

    def post(message: int, wparam: int, lparam: int) -> str:
        """Post one message, and read whether the system took it.

        Same contract as `emit`: "" or why the sequence stopped. The BOOL is
        the only answer this route ever gets -- see the module docstring for
        the three ways it comes back false while everything else looks healthy
        -- so a refusal is counted and stops the rest of the sequence rather
        than being posted over.
        """
        nonlocal rejected, sent
        sent += 1
        answer = WIN32["PostMessageW"](hwnd, message, wparam, lparam)
        # The real call answers `(queued, error)`. A replaced table entry may
        # answer with a bare bool, and that is read as a reading too: a test
        # that wants the failure path says so by returning false.
        queued, error = (answer if isinstance(answer, tuple)
                         else (bool(answer), 0))
        if queued:
            return ""
        rejected += 1
        name = MESSAGE_NAMES.get(message, hex(message))
        return (f"PostMessageW({name}) failed with error {error}; it and the "
                f"rest of the sequence did not reach hwnd {hwnd}.")

    lost = ""
    for entry in plan:
        lost = ""
        kind = entry["type"]
        if kind == "wait":
            WIN32["sleep"](entry["ms"] / 1000.0)
        elif kind in ("key", "key_down", "key_up"):
            lost = _do_key(entry, route, emit, post)
        else:
            lost = _do_pointer(entry, route, geometry, emit, post)
        if lost:
            break
        done += 1

    foreground_after = WIN32["GetForegroundWindow"]()
    detail = (f"{done} of {len(plan)} action(s) sent to hwnd {hwnd} via "
              f"{route}.")
    if lost:
        detail += " " + lost
    if rejected:
        api, noun = (("SendInput", "record") if route == ROUTE_SEND_INPUT
                     else ("PostMessageW", "message"))
        detail += (f" {api} rejected {rejected} of {sent} {noun}(s); the "
                   "events that carried them did not reach the game.")
    return results.ok(
        tool, **report, foreground_after=foreground_after, focus_via=focus_via,
        actions_done=done,
        actions_total=len(plan), records_sent=sent, records_rejected=rejected,
        complete=not lost and not rejected,
        elapsed_s=round(time.monotonic() - started, 3), detail=detail)


def _do_key(entry: dict[str, Any], route: str,
            emit: Callable[[list[INPUT]], str],
            post: Callable[[int, int, int], str]) -> str:
    """One key action. Returns "" or why the sequence stopped."""
    vk = entry["vk"]
    scan = int(WIN32["MapVirtualKeyW"](vk, MAPVK_VK_TO_VSC))
    extended = vk in EXTENDED_KEYS
    press = entry["type"] in ("key", "key_down")
    release = entry["type"] in ("key", "key_up")

    if route == ROUTE_SEND_INPUT:
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if extended else 0)
        if press:
            lost = emit([keyboard_record(scan, flags)])
            if lost:
                return lost
        if press and release:
            WIN32["sleep"](entry["hold_ms"] / 1000.0)
        if release:
            return emit([keyboard_record(scan, flags | KEYEVENTF_KEYUP)])
        return ""

    # Posted messages carry the state in lParam: bits 0-15 repeat count, 16-23
    # scan code, 24 extended, 30 previous key state, 31 transition (a key-up).
    down = 1 | (scan << 16) | ((1 << 24) if extended else 0)
    if press:
        lost = post(WM_KEYDOWN, vk, down)
        if lost:
            return lost
    if press and release:
        WIN32["sleep"](entry["hold_ms"] / 1000.0)
    if release:
        return post(WM_KEYUP, vk, down | (1 << 30) | (1 << 31))
    return ""


def _do_pointer(entry: dict[str, Any], route: str,
                geometry: dict[str, Any],
                emit: Callable[[list[INPUT]], str],
                post: Callable[[int, int, int], str]) -> str:
    """One `click` or `move`. Returns "" or why the sequence stopped."""
    click = entry["type"] == "click"
    button = entry.get("button", "left")

    if route == ROUTE_SEND_INPUT:
        dx, dy = _absolute(entry["screen_point"], geometry["virtual"])
        lost = emit([mouse_record(
            MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
            dx, dy)])
        if lost or not click:
            return lost
        down, up = BUTTON_FLAGS[button]
        lost = emit([mouse_record(down)])
        if lost:
            return lost
        if entry["hold_ms"] > 0:
            WIN32["sleep"](entry["hold_ms"] / 1000.0)
        return emit([mouse_record(up)])

    x, y = entry["client_point"]
    lparam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    lost = post(WM_MOUSEMOVE, 0, lparam)
    if lost or not click:
        return lost
    down, up = BUTTON_MESSAGES[button]
    lost = post(down, BUTTON_KEYSTATE[button], lparam)
    if lost:
        return lost
    if entry["hold_ms"] > 0:
        WIN32["sleep"](entry["hold_ms"] / 1000.0)
    return post(up, 0, lparam)
