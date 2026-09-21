"""`hs_select_character` -- take a freshly launched game to a loaded character.

`hs-drive-mcp-charselect` measured that held `send_input` clicks, at fixed
client fractions, drive a freshly launched game from its main menu through
`Play local` -> a save slot -> `Play` to a loaded character
(`ForgePact/docs/character-select-research.md`, `finding: a-sendinput,
a-postmessage, d`, `shipRoute: mcp-only`). This module is the one call that
does it: no player-visible ForgePact change, no research verb, nothing
outside `kPlayerCommands`.

**The proof.** `orbpickup stat`'s `player via <route>` field names the
resolver every player-gated feature in this plugin already gates on -- but
only while `orbpickup` is on: `g_OrbPlayerHow` is written only inside
`FrameCallback`'s `orbpickup`-on branch (measured statically, and the
falsified assumption this module replaces is recorded in the workorder's own
Log). So this tool arms the mod itself, reads the menu (expect `none`: the
negative control -- the resolver ran and found nothing) before any click,
reads again after each screen, and restores `orbpickup` to whatever the
pre-arm read implies it should be: `orbpickup 0` if the pre-arm read showed
`globe objs=0` (the mod was never on), nothing otherwise (someone else turned
it on; leaving it alone is the only honest choice, since the plugin prints no
on/off state of its own).

**Layout data is measured, not derived.** The three client fractions, the
120 ms click hold and the `send_input` route all come from
`ForgePact/docs/character-select-research.md` (C-1.10, C-1.15, C-1.17) --
copied here as data, dated, never re-derived. Slot 1 and a 16:9 client are
the only shapes that document measured; anything else refuses
`layout_not_measured` before a single input is sent.

Only `ping`, `orbpickup stat`, `orbpickup 1` and `orbpickup 0` are ever sent
over IPC, and every click goes through `input.inject(..., route="send_input")`
-- the same instrument `hs_input` is, with the same foreground and window
checks. `saves` is never touched. Nothing here suspends the game; every event
is one a mouse and the IPC channel could already send.
"""
from __future__ import annotations

import re
import time
from typing import Any

from . import capture, ipc, procs, results
from . import input as input_module

TOOL = "hs_select_character"

#: `g_OrbPlayerHow`'s declared default (`ModuleMain.cpp:5073`): the resolver
#: has not run this process, either because `orbpickup` has never been
#: turned on, or -- at the menu, once it is on -- because it ran and found
#: nothing. Two reads at least `BLIND_RETRY_S` apart still reading this after
#: `orbpickup 1` was acknowledged means the branch itself never ran: the
#: instrument is blind, not the game.
BLIND = "(not tried)"

#: The resolver ran and found no player -- the negative control this tool
#: reads at the main menu before any click.
NONE_VIA = "none"

#: The literal prefix `orbpickup 1`'s handler prints when it arms
#: (`ModuleMain.cpp:17491`, `sprintf_s(ob, "orbpickup -> globes pulled ...`).
#: Anything else means the mod did not arm.
ARM_ACK_PREFIX = "orbpickup -> globes pulled"

_PLAYER_VIA = "player via "
_GLOBE_OBJS_RE = re.compile(r"globe objs=(\d+)")

#: `ForgePact/docs/character-select-research.md` C-1.15, C-1.17, dated so a
#: later re-measurement is a data change here, not a code change. Client
#: fractions only -- both measured display modes (1920x1080 windowed,
#: 2560x1440 fullscreen) are 16:9, and the fractions were shown stable across
#: them for `Play local` only; slot 1 and PLAY were measured windowed only.
LAYOUT_MEASURED_DATE = "2026-09-21"
FRACTION_LOCAL = (0.175, 0.4944)
FRACTION_SLOT_1 = (0.1266, 0.2083)
FRACTION_PLAY = (0.3036, 0.3204)

#: C-1.10: a zero-hold click activates nothing; 120 ms between button-down
#: and button-up changed the room every time. `hs_input`'s own default
#: (`DEFAULT_CLICK_HOLD_MS`) is the same value; it is repeated here
#: explicitly rather than relied on, because the mechanism *is* the hold and
#: a caller reading this module should not have to open another one to see
#: the number that makes it work.
CLICK_HOLD_MS = 120

#: UNVERIFIED upper bound (`ForgePact/docs/character-select-research.md` only
#: records "settle time under 3 s" for the town load, C-1.16). L-1's live
#: gate measures what each screen actually needs; until then this is the
#: number every screen waits, labelled as the bound it is.
SETTLE_S = 3.0

#: How often `orbpickup stat` is re-read after the `Play` click while waiting
#: for a route. Bounded against the caller's own `timeout_s` at each
#: iteration (`_poll_sleep`), so a short `timeout_s` does not have to wait
#: out a full interval it will never get to use.
POLL_INTERVAL_S = 2.0

#: How far apart the two menu-time reads that decide `proof_not_armed` have
#: to be -- long enough that two reads landing in the same frame cannot look
#: like "the resolver ran twice and found nothing" when it never ran once.
BLIND_RETRY_S = 1.0

#: The three screens a held click has to cross, in order, each with the
#: fraction that lands the click.
SCREENS = (("local", FRACTION_LOCAL),
          ("slot", FRACTION_SLOT_1),
          ("play", FRACTION_PLAY))


def _sleep(seconds: float) -> None:
    """The one seam every wait in this module goes through, so a test can
    replace it and finish in milliseconds regardless of `SETTLE_S` or
    `timeout_s` -- the same reason `input.py` routes every Win32 call
    through one table rather than calling `ctypes` directly."""
    time.sleep(seconds)


def _parse_stat(line: str) -> tuple[str, int | None]:
    """`(player via <route>, globe objs=<n>)` from one `orbpickup stat` reply
    line. `player via` is always the format string's last field
    (`ModuleMain.cpp:5600`), so the text after its last occurrence is the
    whole route, not a prefix of something else on the line."""
    idx = line.rfind(_PLAYER_VIA)
    via = line[idx + len(_PLAYER_VIA):].strip() if idx >= 0 else ""
    match = _GLOBE_OBJS_RE.search(line)
    globe_objs = int(match.group(1)) if match else None
    return via, globe_objs


def _read_stat(tool: str) -> dict[str, Any]:
    """One `orbpickup stat` read. A refusal from `ipc.send` is returned as
    is; a successful read gains `line`, `via` and `globe_objs`."""
    result = ipc.send(["orbpickup stat"], tool=tool)
    if results.is_refusal(result):
        return result
    line = (result.get("reply") or "").strip()
    via, globe_objs = _parse_stat(line)
    result = dict(result)
    result["line"] = line
    result["via"] = via
    result["globe_objs"] = globe_objs
    return result


def _has_route(via: str) -> bool:
    """A resolved player, as opposed to "never tried" or "tried, found none"."""
    return via not in (NONE_VIA, BLIND)


def hs_select_character(slot: int = 1, timeout_s: float = 60,
                        tool: str = TOOL) -> dict[str, Any]:
    """Drive a freshly launched game from its main menu to a loaded
    character, `slot`, and prove it. See the module docstring for the
    mechanism and `docs/tools/hs-drive-mcp.md` for the field-by-field
    contract `server.py` documents to the caller.
    """
    started = time.monotonic()

    state, why = procs.gate()
    if state == procs.NOT_RUNNING:
        return results.refuse(
            tool, "game_not_running",
            f"{why} There is no game to select a character in; launch it "
            "with hs_launch first.")
    if state != procs.RUNNING:
        token = {procs.ENGINE_MISSING: "engine_source_missing",
                 procs.ENGINE_UNUSABLE: "engine_import_failed"}.get(
                     state, "game_state_unknown")
        return results.refuse(tool, token, f"{why} So no window can be "
                              "resolved and nothing was sent.")

    if slot != 1:
        return results.refuse(
            tool, "layout_not_measured",
            f"slot {slot} was never measured -- "
            "ForgePact/docs/character-select-research.md C-1.15 measured "
            f"slot 1 only, on {LAYOUT_MEASURED_DATE}. Only slot=1 is "
            "supported until a session measures another slot's click "
            "point.")

    window = capture.resolve_game_window(procs.game_pids(), tool)
    if results.is_refusal(window):
        return window
    hwnd = int(window["hwnd"])
    geometry, why = input_module._geometry(hwnd)  # noqa: SLF001 - shared seam
    if why:
        return results.refuse(tool, "no_visible_window_for_pid", why)
    client_w, client_h = geometry["client_size"]
    if client_w * 9 != client_h * 16:
        return results.refuse(
            tool, "layout_not_measured",
            f"the client area is {client_w}x{client_h}, not 16:9. The "
            f"measured fractions ({LAYOUT_MEASURED_DATE}) are only known "
            "good at 16:9 -- both display modes the research session tried "
            "(1920x1080 windowed, 2560x1440 fullscreen) were. Run the game "
            "windowed or borderless at a 16:9 resolution.")

    ping_result = ipc.send(["ping"], tool=tool)
    if results.is_refusal(ping_result):
        return ping_result

    pre_arm = _read_stat(tool)
    if results.is_refusal(pre_arm):
        return pre_arm
    restore_needed = pre_arm["globe_objs"] == 0

    actions_sent = 0
    proof_trail: list[list[str]] = []
    screenshots: list[str] = []

    def finish(phase: str, *, proof: str = "",
              refusal: dict[str, str] | None = None) -> dict[str, Any]:
        """Every return path after the pre-arm read goes through here, so
        the restore rule (D26) and the envelope shape apply exactly once."""
        orbpickup_state = "left_on"
        if restore_needed:
            ipc.send(["orbpickup 0"], tool=tool)
            orbpickup_state = "restored_off"
        common = dict(phase=phase, proof_trail=list(proof_trail),
                     screenshots=list(screenshots), orbpickup=orbpickup_state,
                     actions_sent=actions_sent,
                     elapsed_s=round(time.monotonic() - started, 3))
        if refusal is not None:
            return results.refuse(tool, refusal["reason"], refusal["detail"],
                                  **common)
        return results.ok(tool, proof=proof, **common)

    def shoot(label: str) -> None:
        shot = capture.screenshot(target="game", label=label,
                                  method="grab_window", tool=tool)
        if not results.is_refusal(shot):
            screenshots.append(shot.get("path", ""))

    arm = ipc.send(["orbpickup 1"], tool=tool)
    if results.is_refusal(arm):
        return finish("main_menu",
                      refusal={"reason": arm["reason"], "detail": arm["detail"]})
    arm_line = (arm.get("reply") or "").strip()
    if not arm_line.startswith(ARM_ACK_PREFIX):
        return finish("main_menu", refusal={
            "reason": "proof_not_armed",
            "detail": (f"orbpickup 1 replied {arm_line!r}, not the "
                      f"{ARM_ACK_PREFIX!r} acknowledgement the handler "
                      "prints when it arms. The resolver may not be "
                      "running, so no click was sent.")})

    menu = _read_stat(tool)
    if results.is_refusal(menu):
        return finish("main_menu",
                      refusal={"reason": menu["reason"], "detail": menu["detail"]})
    if menu["via"] == BLIND:
        _sleep(BLIND_RETRY_S)
        menu = _read_stat(tool)
        if results.is_refusal(menu):
            return finish("main_menu", refusal={
                "reason": menu["reason"], "detail": menu["detail"]})
        if menu["via"] == BLIND:
            return finish("main_menu", refusal={
                "reason": "proof_not_armed",
                "detail": ("orbpickup stat still read "
                          f"'player via {BLIND}' on two reads at least "
                          f"{BLIND_RETRY_S} s apart, after orbpickup 1 was "
                          "acknowledged. The resolver never ran this "
                          "process; the instrument is blind. No click was "
                          "sent.")})
    if _has_route(menu["via"]):
        return finish("main_menu", refusal={
            "reason": "character_already_loaded",
            "detail": (f"orbpickup stat already read 'player via "
                      f"{menu['via']}' at the main menu, before any click "
                      "was sent. A character already appears to be "
                      "loaded.")})
    proof_trail.append(["main_menu", menu["line"]])
    shoot("main_menu")

    last_line = menu["line"]
    for screen, fraction in SCREENS:
        x = round(fraction[0] * client_w)
        y = round(fraction[1] * client_h)
        click = input_module.inject(
            [{"type": "click", "x": x, "y": y, "hold_ms": CLICK_HOLD_MS}],
            route="send_input", tool=tool)
        if results.is_refusal(click):
            return finish(screen, refusal={
                "reason": click["reason"], "detail": click["detail"]})
        actions_sent += 1
        _sleep(SETTLE_S)
        shoot(screen)

        read = _read_stat(tool)
        if results.is_refusal(read):
            return finish(screen, refusal={
                "reason": read["reason"], "detail": read["detail"]})
        proof_trail.append([screen, read["line"]])
        last_line = read["line"]

        if screen == "slot" and _has_route(read["via"]):
            # A live Player_obj on the character panel would make the proof
            # unspecific to a *loaded* character -- unmeasured, so this stops
            # rather than clicking Play and claiming a load it cannot back.
            return finish("proof_ambiguous", proof=read["line"])
        if screen == "play" and _has_route(read["via"]):
            return finish("character_loaded", proof=read["line"])

    deadline = started + max(0.0, float(timeout_s))
    while True:
        now = time.monotonic()
        if now >= deadline:
            return finish("timeout", proof=last_line)
        _sleep(min(POLL_INTERVAL_S, deadline - now))
        read = _read_stat(tool)
        if results.is_refusal(read):
            return finish("play", refusal={
                "reason": read["reason"], "detail": read["detail"]})
        last_line = read["line"]
        if _has_route(read["via"]):
            return finish("character_loaded", proof=read["line"])
