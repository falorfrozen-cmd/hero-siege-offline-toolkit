"""One result envelope for every hs-drive tool.

A refusal is a normal, successful tool result carrying `refused: true` and a
`reason` token -- never an exception thrown across the transport. An exception
reaches the caller as a protocol error with a stack trace attached, which is
exactly the shape a model cannot act on; a token it can branch on is the point.

`REASONS` is the whole vocabulary. It is spelled as two tuples because the two
halves were defined by two workorders -- `CORE_REASONS` by the one that built
the status, self-check and save tools, `GAME_REASONS` by the one that added
launch, IPC and screenshot -- and keeping the split visible is what stops a
third workorder inventing `not_running` beside `game_not_running`.
"""
from __future__ import annotations

from typing import Any

CORE_REASONS = (
    "engine_source_missing",
    "engine_import_failed",
    "forgepact_config_missing",
    "game_running",
    "game_state_unknown",
    "save_dir_missing",
    "no_character_saves",
    "save_dir_too_large",
    "restore_target_unrelated",
    "copy_verification_failed",
    "backup_incomplete",
    "backup_corrupt",
    "invalid_backup_id",
    "pre_restore_backup_failed",
    "confirmation_mismatch",
    "invalid_label",
)

#: Added by `hs-drive-mcp-game` for launch, IPC and screenshot. Each one names
#: a state a caller can act on: the inverse of `game_running` for the tools
#: that need a live game, the two ways `bp_ipc\` can be unusable, and the two
#: refusals that exist to stop this server doing something it should not --
#: `not_launched_here` (never terminate a process this server did not start)
#: and `mod_chain_incomplete` (never launch an unmodded copy and call it ready).
GAME_REASONS = (
    "game_not_running",
    "bp_ipc_missing",
    "invalid_command",
    "not_consumed",
    "no_visible_window_for_pid",
    "window_minimized",
    "not_launched_here",
    "launcher_refused",
    "mod_chain_incomplete",
    # Not on that workorder's reserved list, and added rather than borrowed:
    # "the imaging library this server pins is not installed" is not
    # `invalid_command`, and telling a caller its arguments were wrong when the
    # install is incomplete sends it to fix the one thing that is fine.
    "capture_unavailable",
)

#: Added by `hs-drive-mcp-charselect` for `hs_input`, and only these two.
#: `foreground_not_game` is the permission this server will not inject
#: without -- `SendInput` reaches whatever window is in front, so a mismatch
#: means the keystrokes would land somewhere that never asked for them.
#: `invalid_input` is separate from `invalid_command` on purpose: the latter
#: means "that is not a ForgePact command", which sends a caller looking at the
#: plugin, and an action list the tool itself rejected has nothing to do with
#: the plugin.
INPUT_REASONS = (
    "foreground_not_game",
    "invalid_input",
)

#: `hs_select_character`'s own tokens. `proof_not_armed` and
#: `character_already_loaded` came with `hs-drive-mcp-charselect-ship`:
#: the first is the instrument-blind case D17 fell into, now a named
#: refusal -- `orbpickup 1` was not acknowledged, or `orbpickup stat` still
#: read `player via (not tried)` on a second read at least a second later, so
#: the resolver never ran and no click was sent; the second means the
#: menu-time read already named a resolver route before any click.
#:
#: The other four came with `hs-drive-mcp-charselect-buttons`, which replaced
#: the measured click points (and their unmeasured-slot refusal) with
#: ForgePact's `menulayout` listing. Each names a way the listing cannot
#: be clicked from, so nothing is: `layout_command_missing` (the plugin
#: predates the command, or answered with no listing), `button_not_found`
#: (the screen's button was not listed within the poll budget),
#: `slot_not_listed` (the save-slot screen listed fewer cards than `slot`),
#: `window_size_mismatch` (the listing's `window=` is not this client, so its
#: points are for a different window).
#:
#: `click_not_delivered` came with the PR #122 review: `inject` answered `ok`
#: for a click but did not deliver it whole (`complete` false or
#: `records_rejected > 0` -- UIPI dropping `SendInput` records, or the
#: foreground moving part way through), so the click is not counted as landed.
SELECT_CHARACTER_REASONS = (
    "proof_not_armed",
    "character_already_loaded",
    "layout_command_missing",
    "button_not_found",
    "slot_not_listed",
    "window_size_mismatch",
    "click_not_delivered",
)

#: Added by `hs-drive-game-lease` for the machine-wide game lease (`lease.py`).
#: `lease_held` is what the six tools that drive or overwrite the game answer
#: while another live hs-drive process holds the lease, and what
#: `hs_lease_acquire` answers without `force`; `lease_not_held` is a release
#: by a process that has nothing to release; `lease_unavailable` is a record
#: that cannot be read or a lock that cannot be taken -- never read as "free".
#: There is deliberately no `lease_required`: a caller with no lease while
#: nobody holds one is allowed, and its result says `lease: "none"`.
#: A bad lease label reuses `invalid_label`.
LEASE_REASONS = (
    "lease_held",
    "lease_not_held",
    "lease_unavailable",
)

#: Added by `hs-drive-skill-actions` for its five skill tools (`skills.py`),
#: and only these eight. `skill_not_on_bar` is a slot or ability no bar slot
#: lists; `proof_unavailable` is a slot whose ability has no effect object the
#: player build can count (no `effect=` field), so a cast could not be
#: proven; `proof_unstable` is a count that moved between the reads taken
#: before the key with no key pressed (added after round 0's review: without
#: that control a moving count proves nothing about the press);
#: `key_not_delivered` is an injection that did not deliver the whole
#: key press; `cast_not_confirmed` a delivered press whose effect count never
#: moved within the budget. `talent_not_allocatable` (no button carries the
#: id, or the talent is already learned) and `talent_screen_not_open` are
#: `talentalloc`'s own refusals, mapped by their words; `alloc_not_confirmed`
#: is a re-read that shows no change, whatever the verb's line said. There is
#: no points, level or key token: no reader for any of them was measured.
SKILL_REASONS = (
    "skill_not_on_bar",
    "proof_unavailable",
    "proof_unstable",
    "key_not_delivered",
    "cast_not_confirmed",
    "talent_not_allocatable",
    "talent_screen_not_open",
    "alloc_not_confirmed",
)

#: Defined by `hs-drive-skill-actions` for **every** hs-drive tool that writes
#: game state, not only its own; `hs-drive-stash-bag-actions` reuses these
#: three and adds nothing beside them. `plugin_verb_missing` is a player build
#: that answers `command unavailable` for the verb a tool needs (it predates
#: the verb); `route_not_measured` is a tool whose game route was not
#: reproduced by name in a live session, so it refuses before sending
#: anything; `no_session_backup` is answered by `saves.session_backup_gate`:
#: the `backup_id` given is not a whole backup taken before the running game
#: process started, so nothing this session writes could be undone from it.
ACTION_REASONS = (
    "plugin_verb_missing",
    "route_not_measured",
    "no_session_backup",
)

#: Added by `hs-drive-stash-bag-actions` for its five stash and bag tools
#: (`stash.py`), and only these thirteen; the three `ACTION_REASONS` above are
#: reused, never spelled again. `stash_not_open`/`stash_already_open`: whether
#: `menulayout` lists a `UI_Stash_obj`; `stash_not_reachable`: no `Player_obj`
#: or `Town_Stash_obj` row with a finite position to warp by;
#: `warp_not_confirmed`: `playerwarp` ran and the re-read player is not within
#: 2 px of the target; `stash_still_open`: `stashclose` ran and the window is
#: still listed. `bag_not_open`: no stash window, beside which the bag's
#: sub-tabs were measured. `unknown_tab`: a tab name outside the tool's list;
#: `tab_not_listed`: no tab row carries that tab; `tab_not_selected`: the
#: state the game's handler writes did not reach the tab. `count_unsupported`,
#: `template_not_found`, `give_refused` and `give_not_confirmed` are
#: `hs_give_item`'s: a count it cannot make, a fingerprint map 0 does not
#: hold, any other refusal of the verb's, and no `giveitem: confirmed` line
#: with one more item after than before.
STASH_REASONS = (
    "stash_not_open",
    "stash_already_open",
    "stash_not_reachable",
    "stash_still_open",
    "bag_not_open",
    "unknown_tab",
    "tab_not_listed",
    "tab_not_selected",
    "count_unsupported",
    "warp_not_confirmed",
    "template_not_found",
    "give_refused",
    "give_not_confirmed",
)

REASONS = (CORE_REASONS + GAME_REASONS + INPUT_REASONS + SELECT_CHARACTER_REASONS
           + LEASE_REASONS + SKILL_REASONS + ACTION_REASONS + STASH_REASONS)


def ok(tool: str, **fields: Any) -> dict[str, Any]:
    """A successful result. `ok` and `tool` are always present."""
    result: dict[str, Any] = {"ok": True, "tool": tool, "refused": False}
    result.update(fields)
    return result


def refuse(tool: str, reason: str, detail: str, **fields: Any) -> dict[str, Any]:
    """A refusal. `reason` is a token from REASONS; `detail` says why in words.

    The detail is not decoration: a refusal that does not name the file, path
    or state it tripped over is a bug report nobody can act on.
    """
    if reason not in REASONS:
        raise ValueError(f"unknown refusal token: {reason!r}")
    result: dict[str, Any] = {
        "ok": False,
        "tool": tool,
        "refused": True,
        "reason": reason,
        "detail": detail,
    }
    result.update(fields)
    return result


def is_refusal(value: Any) -> bool:
    """True for a refusal envelope, so a caller can pass one straight through."""
    return isinstance(value, dict) and bool(value.get("refused"))
