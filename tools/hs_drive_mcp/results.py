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

REASONS = CORE_REASONS + GAME_REASONS + INPUT_REASONS


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
