"""One result envelope for every hs-drive tool.

A refusal is a normal, successful tool result carrying `refused: true` and a
`reason` token -- never an exception thrown across the transport. An exception
reaches the caller as a protocol error with a stack trace attached, which is
exactly the shape a model cannot act on; a token it can branch on is the point.

`REASONS` is the vocabulary this workorder defines. `RESERVED_REASONS` are the
tokens the follow-on hs-drive-mcp-game workorder will add; they are listed
here so nobody invents a second spelling for one of them.
"""
from __future__ import annotations

from typing import Any

REASONS = (
    "engine_source_missing",
    "forgepact_config_missing",
    "game_running",
    "game_state_unknown",
    "save_dir_missing",
    "no_character_saves",
    "save_dir_too_large",
    "copy_verification_failed",
    "backup_incomplete",
    "backup_corrupt",
    "pre_restore_backup_failed",
    "confirmation_mismatch",
    "invalid_label",
)

RESERVED_REASONS = (
    "game_not_running",
    "bp_ipc_missing",
    "invalid_command",
    "not_consumed",
    "no_visible_window_for_pid",
    "window_minimized",
    "not_launched_here",
    "launcher_refused",
    "mod_chain_incomplete",
)


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
