"""`hs_select_character` -- take a freshly launched game to a loaded character.

`hs-drive-mcp-charselect` measured that held `send_input` clicks drive a
freshly launched game from its main menu through `Play local` -> a save
slot -> `Play` to a loaded character (`ForgePact/docs/character-select-
research.md`, `finding: a-sendinput, a-postmessage, d`, `shipRoute:
mcp-only`). This module is the one call that does it, using only commands
in ForgePact's `kPlayerCommands`.

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

**The game says where each button is.** Every click point is the `win=`
field of a row in ForgePact's read-only `menulayout` listing (`layout.py`),
which the plugin computes in the game from its own GUI and window sizes --
no fraction, no arithmetic here. The listing's `window=` must equal the
client size this server re-measures at that same read; a disagreement is
"not settled yet" (the window can still be reaching its configured size
right after `hs_launch`'s `plugin_ready`) and polls on within the listing's
budget, refusing `window_size_mismatch` only if the two never agree within
it. A button the listing does not carry is refused (`button_not_found`,
`slot_not_listed`), never guessed. A plugin without the command refuses
`layout_command_missing`. Each screen's next button is polled for rather
than waited for: the game lists it when the screen is ready. The 120 ms
click hold and the `send_input` route still come from the research doc
(C-1.10, C-1.17).

Only `ping`, `orbpickup stat`, `orbpickup 1`, `orbpickup 0` and `menulayout`
are ever sent over IPC, and every click goes through
`input.inject(..., route="send_input")`
-- the same instrument `hs_input` is, with the same foreground and window
checks. `saves` is never touched. Nothing here suspends the game; every event
is one a mouse and the IPC channel could already send.
"""
from __future__ import annotations

import re
import time
from typing import Any

from . import capture, ipc, layout, procs, results
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

#: The only three values `HhResolveLocalPlayer` writes into `g_OrbPlayerHow`
#: when it resolves a player (`ModuleMain.cpp`, § "The proof" in the
#: workorder's context file). `_has_route` allowlists exactly these -- never
#: "anything that isn't `none` or `(not tried)`" -- because that denylist
#: also counted `""` as a route: a reply with no `player via ` field at all
#: (an empty read, one cut off before the last field, or an unrelated line
#: landing in its place) has an empty `via`, and `"" not in (NONE_VIA,
#: BLIND)` is true.
KNOWN_ROUTES = ("GetMyPlayer", "instance_find(Player_obj)",
               "instance_find(Player_obj) id")

#: The literal prefix `orbpickup 1`'s handler prints when it arms
#: (`ModuleMain.cpp:17491`, `sprintf_s(ob, "orbpickup -> globes pulled ...`).
#: Anything else means the mod did not arm.
ARM_ACK_PREFIX = "orbpickup -> globes pulled"

#: The literal prefix of `orbpickup stat`'s one reply line
#: (`ModuleMain.cpp:5600`).
STAT_PREFIX = "orbpickup stat:"

_PLAYER_VIA = "player via "
_GLOBE_OBJS_RE = re.compile(r"globe objs=(\d+)")

#: C-1.10: a zero-hold click activates nothing; 120 ms between button-down
#: and button-up changed the room every time. `hs_input`'s own default
#: (`DEFAULT_CLICK_HOLD_MS`) is the same value; it is repeated here
#: explicitly rather than relied on, because the mechanism *is* the hold and
#: a caller reading this module should not have to open another one to see
#: the number that makes it work.
CLICK_HOLD_MS = 120

#: How often `menulayout` is re-read after a click while waiting for the next
#: screen's button to be listed, and how many reads that gets (0.5 s x 30 =
#: about 15 s). A count rather than a clock deadline, so the budget is the
#: same number of reads however long each IPC round trip takes. At L-1's
#: live gate every screen was ready within 3 s of its click.
LAYOUT_POLL_S = 0.5
LAYOUT_POLL_ATTEMPTS = 30

#: How often `orbpickup stat` is re-read after the `Play` click while waiting
#: for a route. Bounded against the caller's own `timeout_s` at each
#: iteration (`_poll_sleep`), so a short `timeout_s` does not have to wait
#: out a full interval it will never get to use.
POLL_INTERVAL_S = 2.0

#: How far apart the two menu-time reads that decide `proof_not_armed` have
#: to be -- long enough that two reads landing in the same frame cannot look
#: like "the resolver ran twice and found nothing" when it never ran once.
BLIND_RETRY_S = 1.0

def _sleep(seconds: float) -> None:
    """The one seam every wait in this module goes through, so a test can
    replace it and finish in milliseconds regardless of the poll budgets or
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


def _reply_line(result: dict[str, Any], prefix: str) -> str:
    """The one line of an `ipc.send` reply that starts with `prefix`, or `""`.

    `reply` is everything the plugin appended to `out.txt` for the command,
    which is the handler's line *framed* by `---- running command file ----`
    and `---- done ----` (L-1 live gate, 2026-09-21). Testing the whole reply
    with `startswith`, or parsing it as one line, can therefore never match
    on a real game -- only on a test double that returns the bare line."""
    lines = result.get("reply_lines")
    if lines is None:
        lines = (result.get("reply") or "").splitlines()
    for raw in lines:
        line = raw.strip()
        if line.startswith(prefix):
            return line
    return ""


def _read_stat(tool: str) -> dict[str, Any]:
    """One `orbpickup stat` read. A refusal from `ipc.send` is returned as
    is; a successful read gains `line`, `via` and `globe_objs`. Only the
    handler's own line is parsed; when the reply has none, `via` is `""`
    (never a route) and `line` keeps the raw reply so a refusal can quote
    what actually came back."""
    result = ipc.send(["orbpickup stat"], tool=tool)
    if results.is_refusal(result):
        return result
    stat_line = _reply_line(result, STAT_PREFIX)
    via, globe_objs = _parse_stat(stat_line)
    line = stat_line or (result.get("reply") or "").strip()
    result = dict(result)
    result["line"] = line
    result["via"] = via
    result["globe_objs"] = globe_objs
    return result


def _has_route(via: str) -> bool:
    """A resolved player: `via` is one of the exact routes the resolver
    writes (`KNOWN_ROUTES`), not merely something other than "never tried"
    or "tried, found none". An allowlist, on purpose -- see `KNOWN_ROUTES`
    for the false positive the equivalent denylist produced."""
    return via in KNOWN_ROUTES


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

    window = capture.resolve_game_window(procs.game_pids(), tool)
    if results.is_refusal(window):
        return window
    hwnd = int(window["hwnd"])
    _, why = input_module._geometry(hwnd)  # noqa: SLF001 - shared seam
    if why:
        return results.refuse(tool, "no_visible_window_for_pid", why)

    ping_result = ipc.send(["ping"], tool=tool)
    if results.is_refusal(ping_result):
        return ping_result

    pre_arm = _read_stat(tool)
    if results.is_refusal(pre_arm):
        return pre_arm
    restore_needed = pre_arm["globe_objs"] == 0

    actions_sent = 0
    proof_trail: list[list[str]] = []
    layout_trail: list[dict[str, Any]] = []
    screenshots: list[str] = []
    last_listing: list[str] = []

    def finish(phase: str, *, proof: str = "",
              refusal: dict[str, str] | None = None) -> dict[str, Any]:
        """Every return path after the pre-arm read goes through here, so
        the restore rule (D26) and the envelope shape apply exactly once."""
        orbpickup_state = "left_on"
        if restore_needed:
            ipc.send(["orbpickup 0"], tool=tool)
            orbpickup_state = "restored_off"
        common = dict(phase=phase, proof_trail=list(proof_trail),
                     layout_trail=list(layout_trail),
                     screenshots=list(screenshots), orbpickup=orbpickup_state,
                     actions_sent=actions_sent,
                     elapsed_s=round(time.monotonic() - started, 3))
        if refusal is not None:
            # The last listing read, whole, so a refusal about a button
            # carries what the game did list instead of it.
            return results.refuse(tool, refusal["reason"], refusal["detail"],
                                  last_listing=list(last_listing), **common)
        return results.ok(tool, proof=proof, **common)

    def read_layout() -> tuple[layout.Listing | None, dict[str, str] | None]:
        """One `menulayout` read, checked against the client size measured
        at this same read -- never the call-start size, which can predate
        the window reaching its configured size after `hs_launch`'s
        `plugin_ready`. `(listing, None)` for a listing whose window agrees
        with that fresh measurement, or `(None, refusal)` for a `_geometry`
        failure, an IPC refusal, a plugin without the command, or a listing
        computed for a window other than the one just measured. That last
        case (`window_size_mismatch`) means "not settled yet"; `poll`
        decides whether it is terminal, not this function."""
        geometry, why = input_module._geometry(hwnd)  # noqa: SLF001
        if why:
            return None, {"reason": "no_visible_window_for_pid", "detail": why}
        client_w, client_h = geometry["client_size"]
        reply = ipc.send([layout.COMMAND], tool=tool)
        if results.is_refusal(reply):
            return None, {"reason": reply["reason"], "detail": reply["detail"]}
        lines = layout.reply_lines(reply)
        start = next((i for i, line in enumerate(lines)
                      if line.startswith(layout.HEADER_PREFIX)), None)
        end = next((i for i, line in enumerate(lines)
                    if line.startswith(layout.FOOTER_PREFIX)), len(lines) - 1)
        last_listing[:] = (lines[start:end + 1] if start is not None
                           else [line for line in lines if line])
        listing, reason, detail = layout.read(reply, (client_w, client_h))
        if reason:
            return None, {"reason": reason, "detail": detail}
        return listing, None

    def poll(match, *, sleep_first: bool = True
            ) -> tuple[layout.Row | None, layout.Listing | None,
                       dict[str, str] | None]:
        """Re-read `menulayout` every `LAYOUT_POLL_S`, up to
        `LAYOUT_POLL_ATTEMPTS` reads, until `match(listing)` returns a row
        or a refusal. A `window_size_mismatch` read is treated exactly like
        a "button not listed yet" read: it does not end the poll on its
        own, and is only surfaced if the budget ends on it -- meaning the
        window never settled to agreement within the budget. Any other
        refusal (missing command, IPC, `_geometry`) ends the poll at once.
        `(None, last_listing, None)` means the budget ran out on an
        agreeing read with the button never listed. `sleep_first=False`
        (the main menu's use, which has no click of its own to wait out)
        reads once immediately and sleeps only between the retries after
        that; every post-click poll keeps sleeping before its first read
        too, since that first read is what gives the click time to land."""
        listing = None
        last_mismatch: dict[str, str] | None = None
        for attempt in range(LAYOUT_POLL_ATTEMPTS):
            if sleep_first or attempt > 0:
                _sleep(LAYOUT_POLL_S)
            listing, refusal = read_layout()
            if refusal is not None:
                if refusal["reason"] == layout.WINDOW_SIZE_MISMATCH:
                    last_mismatch = refusal
                    listing = None
                    continue
                return None, None, refusal
            last_mismatch = None
            row, refusal = match(listing)
            if row is not None or refusal is not None:
                return row, listing, refusal
        if last_mismatch is not None:
            detail = (last_mismatch["detail"] + " It never agreed with this "
                      f"client within {LAYOUT_POLL_ATTEMPTS} reads "
                      f"{LAYOUT_POLL_S} s apart, so nothing was clicked.")
            return None, None, {"reason": last_mismatch["reason"],
                                "detail": detail}
        return None, listing, None

    def not_found(what: str, obj: str,
                  listing: layout.Listing | None) -> dict[str, str]:
        quoted = (layout.describe(listing, obj) if listing is not None
                  else "no listing was read")
        return {"reason": "button_not_found",
                "detail": (f"{what} was not listed by menulayout within "
                           f"{LAYOUT_POLL_ATTEMPTS} reads "
                           f"{LAYOUT_POLL_S} s apart, so it was not "
                           f"clicked. Last listing: {quoted}. The whole "
                           "listing is in last_listing.")}

    def click(screen: str, row: layout.Row) -> dict[str, str] | None:
        """One held click at `row`'s `win` point, verbatim -- no arithmetic.
        `None` when it landed; a refusal dict when `inject` refused."""
        nonlocal actions_sent
        x, y = row.win
        result = input_module.inject(
            [{"type": "click", "x": x, "y": y, "hold_ms": CLICK_HOLD_MS}],
            route="send_input", tool=tool)
        if results.is_refusal(result):
            return {"reason": result["reason"], "detail": result["detail"]}
        actions_sent += 1
        layout_trail.append({"screen": screen, **row.summary()})
        return None

    def shoot(label: str) -> None:
        shot = capture.screenshot(target="game", label=label,
                                  method="grab_window", tool=tool)
        if not results.is_refusal(shot):
            screenshots.append(shot.get("path", ""))

    arm = ipc.send(["orbpickup 1"], tool=tool)
    if results.is_refusal(arm):
        return finish("main_menu",
                      refusal={"reason": arm["reason"], "detail": arm["detail"]})
    if not _reply_line(arm, ARM_ACK_PREFIX):
        return finish("main_menu", refusal={
            "reason": "proof_not_armed",
            "detail": (f"orbpickup 1 replied "
                      f"{(arm.get('reply') or '').strip()!r} with no line "
                      "starting with the "
                      f"{ARM_ACK_PREFIX!r} acknowledgement the handler "
                      "prints when it arms. The resolver may not be "
                      "running, so no click was sent.")})

    menu = _read_stat(tool)
    if results.is_refusal(menu):
        return finish("main_menu",
                      refusal={"reason": menu["reason"], "detail": menu["detail"]})
    if menu["via"] in (BLIND, ""):
        _sleep(BLIND_RETRY_S)
        menu = _read_stat(tool)
        if results.is_refusal(menu):
            return finish("main_menu", refusal={
                "reason": menu["reason"], "detail": menu["detail"]})
        if menu["via"] in (BLIND, ""):
            return finish("main_menu", refusal={
                "reason": "proof_not_armed",
                "detail": ("orbpickup stat still had no resolved 'player "
                          f"via' field (raw reply: {menu['line']!r}) on two "
                          f"reads at least {BLIND_RETRY_S} s apart, after "
                          "orbpickup 1 was acknowledged. Either the "
                          "resolver never ran this process and the "
                          "instrument is blind, or the reply was empty or "
                          "malformed. No click was sent.")})
    if _has_route(menu["via"]):
        return finish("main_menu", refusal={
            "reason": "character_already_loaded",
            "detail": (f"orbpickup stat already read 'player via "
                      f"{menu['via']}' at the main menu, before any click "
                      "was sent. A character already appears to be "
                      "loaded.")})
    proof_trail.append(["main_menu", menu["line"]])
    shoot("main_menu")

    # Main menu: polled the same way every later screen is. The window
    # check and the missing-command check both happen on every read; a
    # mismatch just keeps the poll going (the window can still be settling
    # right after `plugin_ready`), and only an exhausted budget on a
    # mismatch refuses `window_size_mismatch`.
    def match_main_menu(listing: layout.Listing):
        return layout.match_play_local(listing), None

    target, listing, refusal = poll(match_main_menu, sleep_first=False)
    if refusal is not None:
        return finish("main_menu", refusal=refusal)
    if target is None:
        found = len(layout.play_local_rows(listing))
        return finish("main_menu", refusal={
            "reason": "button_not_found",
            "detail": (f"the main menu's listing carries {found} visible "
                       f"{layout.PLAY_LOCAL_OBJECT} with text exactly "
                       f"{layout.PLAY_LOCAL_TEXT!r} and a readable point "
                       "(exactly one is clickable), so nothing was clicked. "
                       "Listing: "
                       f"{layout.describe(listing, layout.PLAY_LOCAL_OBJECT)}."
                       " The whole listing is in last_listing.")})

    # `local`: click Play local, then wait for card `slot` to be listed.
    refusal = click("local", target)
    if refusal is not None:
        return finish("local", refusal=refusal)

    short_count: list[int | None] = [None]

    def match_card(listing: layout.Listing):
        """Card `slot`, once `Chose_rm` lists it. The same short card count
        on two reads running is `slot_not_listed` -- one short read may be a
        screen still filling in, so it alone refuses nothing."""
        if listing.room != layout.SLOT_ROOM:
            short_count[0] = None
            return None, None
        row = layout.match_slot(listing, slot)
        if row is not None:
            return row, None
        count = len(layout.slot_rows(listing))
        if count and count == short_count[0]:
            return None, {
                "reason": "slot_not_listed",
                "detail": (f"{layout.SLOT_ROOM} listed {count} visible "
                           f"{layout.SLOT_OBJECT} card(s) on two reads in a "
                           f"row, fewer than slot {slot}; only page 1 of the "
                           "save-slot screen is reachable, so no card was "
                           "clicked.")}
        short_count[0] = count
        return None, None

    target, listing, refusal = poll(match_card)
    shoot("local")
    if refusal is not None:
        return finish("local", refusal=refusal)
    if target is None:
        return finish("local", refusal=not_found(
            f"save slot {slot} (a visible {layout.SLOT_OBJECT} in "
            f"{layout.SLOT_ROOM})", layout.SLOT_OBJECT, listing))
    read = _read_stat(tool)
    if results.is_refusal(read):
        return finish("local", refusal={
            "reason": read["reason"], "detail": read["detail"]})
    proof_trail.append(["local", read["line"]])

    # `slot`: click the card, then wait for the panel's PLAY to be listed
    # (phase 0: it does not exist until a card is clicked).
    refusal = click("slot", target)
    if refusal is not None:
        return finish("slot", refusal=refusal)

    def match_play(listing: layout.Listing):
        if listing.room != layout.SLOT_ROOM:
            return None, None
        return layout.match_play(listing), None

    target, listing, refusal = poll(match_play)
    shoot("slot")
    if refusal is not None:
        return finish("slot", refusal=refusal)
    if target is None:
        return finish("slot", refusal=not_found(
            f"the character panel's {layout.PLAY_TEXT!r} button (one visible "
            f"{layout.PLAY_OBJECT} with exactly that text)",
            layout.PLAY_OBJECT, listing))
    read = _read_stat(tool)
    if results.is_refusal(read):
        return finish("slot", refusal={
            "reason": read["reason"], "detail": read["detail"]})
    proof_trail.append(["slot", read["line"]])
    if _has_route(read["via"]):
        # A live Player_obj on the character panel would make the proof
        # unspecific to a *loaded* character -- unmeasured, so this stops
        # rather than clicking Play and claiming a load it cannot back.
        return finish("proof_ambiguous", proof=read["line"])

    # `play`: click PLAY, then poll `orbpickup stat` for a resolver route.
    refusal = click("play", target)
    if refusal is not None:
        return finish("play", refusal=refusal)

    deadline = started + max(0.0, float(timeout_s))
    last_line = read["line"]
    first = True
    while True:
        _sleep(max(0.0, min(POLL_INTERVAL_S, deadline - time.monotonic())))
        read = _read_stat(tool)
        if results.is_refusal(read):
            return finish("play", refusal={
                "reason": read["reason"], "detail": read["detail"]})
        if first:
            proof_trail.append(["play", read["line"]])
            first = False
        last_line = read["line"]
        if _has_route(read["via"]):
            shoot("play")
            return finish("character_loaded", proof=read["line"])
        if time.monotonic() >= deadline:
            shoot("play")
            return finish("timeout", proof=last_line)
