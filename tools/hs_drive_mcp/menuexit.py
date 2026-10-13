"""`hs_exit_to_menu` -- take a loaded character back to a menu the way a player does.

Escape opens the in-game pause menu; its Exit button saves the character and
goes to the character select. A static reading (ForgePact #201, `docs/
RUNTIME_DATA_MODELS.md` § 8.4, "The pause menu's Exit") says the Exit
activation saves through the game's own `SaveLocalFile`, then changes room to
`Chose_rm`; it does not end the game. This tool exists so a live session can
compare a window close after that path with one straight from the world.

The rules are `hs_select_character`'s (`charselect.py`):

- **The game says where the button is.** The Exit click goes to the `win=`
  point of a row in ForgePact's read-only `menulayout` listing, verbatim. A
  listing whose `window=` is not the client size this server measured at the
  same read is `window_size_mismatch`: its points are for another window, so
  nothing is pressed or clicked. A listing whose footer says `capped=1` is
  never used to pick a row (its id set may be incomplete).
- **The row is this open's.** The pause menu builds new `UI_Button_obj` rows
  on every open (§ 8.4, measured 2026-09-22), so the ids listed before Escape
  are kept and a candidate is a visible row whose id is new. With `label`,
  the candidate whose text is exactly `label`; without one, the candidates
  whose `uiNodeCallstack` or text contains `exit` (case-insensitive) and
  neither contains `join`. One row is clicked; none is
  `exit_button_not_found` and several `exit_button_ambiguous`, each quoting
  the candidates. When the pause menu is already listed at the start the key
  is skipped (`pause_opened_by: "already_open"`), and with no "before the
  key" every listed row is a candidate.
- **The same instrument.** Escape (VK 27, held 60 ms) and the click (held
  120 ms, C-1.10) both go through `input.inject(..., route="send_input",
  force_focus=True)`, the focus chain `hs_select_character` uses; which step
  took is recorded per input in `focus_trail`. An input `inject` answered
  without delivering whole is `click_not_delivered` and is not counted.
- **The result is read, not assumed.** After the click the tool polls until
  the header names `Chose_rm` or `Main_Menu_rm` and no `UI_Pause_obj` is
  listed, within `timeout_s`; otherwise `menu_not_reached` quoting the last
  listing. `proof` is every header that decided a step.

Measured 2026-10-13 in #201's Live 1 cell C and Live 2 cell G: the injected
Escape opened the pause menu, the Exit row is a `UI_Button_obj` reading
"Save & Exit" with `uiNodeCallstack` `PauseSaveExit`, a click at its point
activates it with no confirmation, and the game reaches `Chose_rm`;
`menu_reached` on the first call each time. The tests' listings are still
synthetic, built to that shape.

Only `menulayout` is sent over IPC. Nothing here suspends the game: it presses
one key and clicks one button a player would. No MCP import: `server.py`
registers it.
"""
from __future__ import annotations

import time
from typing import Any, Iterable

from . import capture, ipc, layout, lease, procs, results
from . import input as input_module

TOOL = "hs_exit_to_menu"

#: Escape, held as `hs_input`'s default key hold.
ESCAPE_VK = 27
KEY_HOLD_MS = 60
#: C-1.10: a zero-hold click activates nothing; 120 ms worked every time.
CLICK_HOLD_MS = 120

#: `charselect`'s listing poll: 0.5 s between reads, 30 reads.
POLL_S = 0.5
POLL_ATTEMPTS = 30

#: Without `label`, a row is an Exit row when its `uiNodeCallstack` or text
#: contains `EXIT_WORD` and neither contains `EXCLUDE_WORD`, both
#: case-insensitive.
EXIT_WORD = "exit"
EXCLUDE_WORD = "join"

CALLSTACK = "uiNodeCallstack"


def _sleep(seconds: float) -> None:
    """The one seam every wait here goes through, so a test finishes in
    milliseconds whatever the poll budget or `timeout_s`."""
    time.sleep(seconds)


def _now() -> float:
    """The clock `timeout_s` and `elapsed_s` read; a seam like `_sleep`."""
    return time.monotonic()


def _callstack(row: layout.Row) -> str:
    return row.extra.get(CALLSTACK) or ""


def describe_row(row: layout.Row) -> dict[str, Any]:
    """The fields a refusal quotes for a candidate, and `exit_row` reports."""
    return {"obj": row.obj, "id": row.id, "text": row.text,
            CALLSTACK: _callstack(row), "win": list(row.win)}


def exit_candidates(rows: Iterable[layout.Row], label: str | None) -> list[layout.Row]:
    """The rows among `rows` (this open's visible buttons) that name the Exit
    button: the exact `label` text, or by default `exit` in the
    `uiNodeCallstack` or text with `join` in neither."""
    rows = list(rows)
    if label is not None:
        return [row for row in rows if row.text == label]
    out = []
    for row in rows:
        words = (_callstack(row).lower(), row.text.lower())
        if any(EXIT_WORD in w for w in words) and not any(EXCLUDE_WORD in w for w in words):
            out.append(row)
    return out


def _rows(listing: layout.Listing, obj: str) -> list[layout.Row]:
    return [row for row in listing.rows if row.obj == obj]


def hs_exit_to_menu(timeout_s: float = 60, label: str | None = None,
                    tool: str = TOOL,
                    gate=None) -> dict[str, Any]:
    """Escape, then the pause menu's Exit row, then prove a menu room is
    reached. See the module docstring. The game lease is asked once, first;
    the reads and inputs inside pass `lease_checked=True`."""
    refusal = lease.guard(tool)
    if refusal:
        return refusal
    return lease.stamp(_exit_to_menu(timeout_s, label, tool, gate))


def _process_refusal(tool: str, gate) -> dict[str, Any] | None:
    state, why = (procs.gate if gate is None else gate)()
    if state == procs.RUNNING:
        return None
    if state == procs.NOT_RUNNING:
        return results.refuse(tool, "game_not_running",
                              f"{why} There is no game to leave; nothing was sent.")
    token = {procs.ENGINE_MISSING: "engine_source_missing",
             procs.ENGINE_UNUSABLE: "engine_import_failed"}.get(state, "game_state_unknown")
    return results.refuse(tool, token, f"{why} So no window can be resolved and "
                          "nothing was sent.")


def _exit_to_menu(timeout_s: float, label: str | None, tool: str, gate) -> dict[str, Any]:
    started = _now()
    refusal = _process_refusal(tool, gate)
    if refusal:
        return refusal
    window = capture.resolve_game_window(procs.game_pids(), tool)
    if results.is_refusal(window):
        return window
    hwnd = int(window["hwnd"])

    layout_trail: list[dict[str, Any]] = []
    focus_trail: list[dict[str, Any]] = []
    proof: list[str] = []
    last_listing: list[str] = []
    state = {"phase": "in_world", "opened_by": None}

    def finish(refusal: dict[str, Any] | None = None, **more: Any) -> dict[str, Any]:
        common = dict(phase=state["phase"], pause_opened_by=state["opened_by"],
                      layout_trail=list(layout_trail), focus_trail=list(focus_trail),
                      proof=list(proof), elapsed_s=round(_now() - started, 3))
        if refusal is not None:
            return results.refuse(tool, refusal["reason"], refusal["detail"],
                                  last_listing=list(last_listing), **common, **more)
        return results.ok(tool, **common, **more)

    def read(objects: tuple[str, ...], *, check_window: bool
             ) -> tuple[list[layout.Listing] | None, dict[str, str] | None]:
        """One send carrying one `menulayout <Obj>` line per object, and its
        listings in order. With `check_window`, every listing's `window=` must
        equal the client size measured at this same read."""
        client = None
        if check_window:
            geometry, why = input_module._geometry(hwnd)  # noqa: SLF001 - shared seam
            if why:
                return None, {"reason": "no_visible_window_for_pid", "detail": why}
            client = tuple(int(v) for v in geometry["client_size"])
        lines = [f"{layout.COMMAND} {obj}" for obj in objects]
        reply = ipc.send(lines, tool=tool, lease_checked=True)
        if results.is_refusal(reply):
            return None, {"reason": reply["reason"], "detail": reply["detail"]}
        text = layout.reply_lines(reply)
        last_listing[:] = [l for l in text if l and not l.startswith("----")]
        if any(l.startswith(layout.UNAVAILABLE) for l in text):
            return None, {"reason": layout.LAYOUT_COMMAND_MISSING, "detail": (
                f"the installed ForgePact plugin answered {layout.UNAVAILABLE!r}: it "
                "predates the read-only `menulayout` this tool clicks by, so nothing "
                "was pressed or clicked.")}
        listings = layout.parse_all(reply)
        if len(listings) != len(objects):
            return None, {"reason": layout.LAYOUT_COMMAND_MISSING, "detail": (
                f"{len(lines)} `menulayout` line(s) ({lines!r}) answered "
                f"{len(listings)} listing(s), so which rows belong to which "
                "object is unknown and nothing was pressed or clicked.")}
        if client is not None:
            for one in listings:
                if one.window != client:
                    return None, {"reason": layout.WINDOW_SIZE_MISMATCH, "detail": (
                        f"the listing was computed for a {one.window[0]}x{one.window[1]} "
                        f"window (header {one.header!r}) but this window's client "
                        f"area measures {client[0]}x{client[1]}, so its `win` points "
                        "are for a different window and nothing was pressed or clicked.")}
        return listings, None

    def deliver(step: str, action: dict[str, Any]) -> dict[str, str] | None:
        """One key or click through the focus chain. `None` when it landed
        whole; a refusal dict otherwise (not counted in either trail)."""
        result = input_module.inject([action], route=input_module.ROUTE_SEND_INPUT,
                                     force_focus=True, tool=tool, lease_checked=True)
        if results.is_refusal(result):
            return {"reason": result["reason"], "detail": result["detail"]}
        rejected = int(result.get("records_rejected") or 0)
        if result.get("complete") is not True or rejected > 0:
            return {"reason": "click_not_delivered", "detail": (
                f"the {step} input {action!r} was not delivered whole (complete="
                f"{result.get('complete')!r}, records_rejected={rejected} of "
                f"{result.get('records_sent')!r}), so it is not counted as landed and "
                f"nothing further was sent. inject said: {result.get('detail', '')}")}
        focus_trail.append({"step": step, "focus_via": result.get("focus_via")})
        return None

    def quote(rows: list[layout.Row]) -> str:
        return "; ".join(f"{r.obj} id={r.id} text={r.text!r} {CALLSTACK}="
                         f"{_callstack(r)!r} win={r.win[0]},{r.win[1]}" for r in rows) or "none"

    # 1. Where are we, and which buttons are already listed?
    objects = (layout.PAUSE_OBJECT, layout.MENU_BUTTON_OBJECT)
    listings, refusal = read(objects, check_window=True)
    if refusal is not None:
        return finish(refusal)
    pause_listing, button_listing = listings
    proof.append(pause_listing.header)
    if pause_listing.room in layout.MENU_ROOMS:
        return finish({"reason": "not_in_world", "detail": (
            f"the listing's room is {pause_listing.room} (header "
            f"{pause_listing.header!r}): a menu room, with no character in the world "
            "to take back, so nothing was pressed or clicked.")}, room=pause_listing.room)
    if any(one.capped for one in listings):
        return finish({"reason": "exit_button_not_found", "detail": (
            "the listing before Escape says capped=1, so the ids listed before the key "
            "may be incomplete and a new row could not be told from an old one. "
            "Nothing was pressed or clicked.")})
    if _rows(pause_listing, layout.PAUSE_OBJECT):
        state["opened_by"] = "already_open"
        before: set[int | None] = set()
    else:
        before = {row.id for row in _rows(button_listing, layout.MENU_BUTTON_OBJECT)}
        state["phase"] = "escape"
        refusal = deliver("escape", {"type": "key", "vk": ESCAPE_VK, "hold_ms": KEY_HOLD_MS})
        if refusal is not None:
            return finish(refusal)
        state["opened_by"] = "key"
        layout_trail.append({"step": "escape", "key": ESCAPE_VK, "hold_ms": KEY_HOLD_MS})

    # 2. Poll until the pause menu is listed and one new row is its Exit.
    state["phase"] = "pause_menu"
    pause_seen = False
    candidates: list[layout.Row] = []
    new_rows: list[layout.Row] = []
    target = None
    first = state["opened_by"] == "already_open"
    for attempt in range(POLL_ATTEMPTS):
        if first and attempt == 0:
            current = listings
        else:
            _sleep(POLL_S)
            current, refusal = read(objects, check_window=True)
            if refusal is not None:
                return finish(refusal)
        pauses, buttons = current
        if not _rows(pauses, layout.PAUSE_OBJECT):
            continue
        if not pause_seen:
            pause_seen = True
            proof.append(pauses.header)
        if buttons.capped:
            return finish({"reason": "exit_button_not_found", "detail": (
                f"the `{layout.MENU_BUTTON_OBJECT}` listing with the pause menu open "
                "says capped=1, so its rows may be incomplete and it is not used to "
                "pick a row. Nothing was clicked.")})
        new_rows = [row for row in _rows(buttons, layout.MENU_BUTTON_OBJECT)
                    if row.visible and row.id is not None and row.id not in before]
        candidates = exit_candidates(new_rows, label)
        if len(candidates) > 1:
            return finish({"reason": "exit_button_ambiguous", "detail": (
                f"{len(candidates)} new visible {layout.MENU_BUTTON_OBJECT} rows match "
                f"{'the label ' + repr(label) if label is not None else 'exit'}: "
                f"{quote(candidates)}. Nothing was clicked; pass `label` with one row's "
                "exact text.")}, candidates=[describe_row(r) for r in candidates])
        if len(candidates) == 1:
            target = candidates[0]
            break
    if not pause_seen:
        return finish({"reason": "pause_menu_not_open", "detail": (
            f"no {layout.PAUSE_OBJECT} was listed within {POLL_ATTEMPTS} reads {POLL_S} s "
            "apart after Escape was delivered, so nothing was clicked. The last listing "
            "is in last_listing.")})
    if target is None:
        wanted = (f"text exactly {label!r}" if label is not None else
                  f"{EXIT_WORD!r} in its {CALLSTACK} or text and {EXCLUDE_WORD!r} in neither")
        return finish({"reason": "exit_button_not_found", "detail": (
            f"no new visible {layout.MENU_BUTTON_OBJECT} row with {wanted} was listed "
            f"within {POLL_ATTEMPTS} reads {POLL_S} s apart; the new rows were: "
            f"{quote(new_rows)}. Nothing was clicked.")},
            candidates=[describe_row(r) for r in new_rows])
    if None in target.win:
        return finish({"reason": "exit_button_not_found", "detail": (
            f"the Exit row ({quote([target])}) has no readable `win` point, so it was "
            "not clicked.")}, candidates=[describe_row(target)])

    # 3. Click it, at its listed point.
    state["phase"] = "exit_click"
    x, y = target.win
    refusal = deliver("exit", {"type": "click", "x": x, "y": y, "hold_ms": CLICK_HOLD_MS})
    if refusal is not None:
        return finish(refusal, exit_row=describe_row(target))
    layout_trail.append({"step": "exit", **describe_row(target), "hold_ms": CLICK_HOLD_MS})

    # 4. Poll for a menu room with no pause menu, within `timeout_s`.
    deadline = _now() + max(0.0, float(timeout_s))
    last_header = ""
    while True:
        _sleep(max(0.0, min(POLL_S, deadline - _now())))
        current, refusal = read((layout.PAUSE_OBJECT,), check_window=False)
        if refusal is not None:
            return finish(refusal, exit_row=describe_row(target))
        here = current[0]
        last_header = here.header
        if here.room in layout.MENU_ROOMS and not _rows(here, layout.PAUSE_OBJECT):
            proof.append(here.header)
            state["phase"] = "menu_reached"
            return finish(room=here.room, exit_row=describe_row(target))
        if _now() >= deadline:
            proof.append(here.header)
            return finish({"reason": "menu_not_reached", "detail": (
                f"the Exit click landed and within {timeout_s} s no listing named "
                f"{' or '.join(layout.MENU_ROOMS)} without a {layout.PAUSE_OBJECT} "
                f"(last header {last_header!r}). The last listing is in last_listing.")},
                room=here.room, exit_row=describe_row(target))
