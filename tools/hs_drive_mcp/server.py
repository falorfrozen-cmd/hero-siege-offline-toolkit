"""Tool registration for the `hs-drive` MCP server. No logic lives here.

This is the only module that imports the MCP SDK, which is why the domain
modules -- `saves`, `procs`, `launcher_bridge`, `checks` -- can be tested
without it and why the root suite runs on a CI image that has never installed
one.

**mcp 2.x, not 1.x.** The house mcp-builder guide's
`from mcp.server.fastmcp import FastMCP` is the 1.x API and raises
`ModuleNotFoundError` against the pinned `mcp==2.2.0`. The 2.x spelling is
`MCPServer`, `@server.tool(...)`, `server.run("stdio")`, and structured output
inferred from the `dict` return annotation.

The transport is stdio and stdout belongs to the protocol: anything written
there is a parse error at the other end. Diagnostics go to stderr through the
logger below, and nothing in this package writes to stdout.
"""
from __future__ import annotations

import logging
import sys
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from . import checks, procs, saves

INSTRUCTIONS = (
    "Order for a verified test run: hs_selfcheck -> hs_saves_backup -> "
    "(hs_launch -> hs_command / hs_screenshot -> hs_stop_game, once installed) "
    "-> hs_saves_inspect -> hs_saves_restore. Every refusal carries `reason`; "
    "a `skipped` self-check is not a pass."
)

# stderr only. On stdio, stdout is the protocol channel.
logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s hs-drive %(levelname)s %(message)s")
log = logging.getLogger("hs_drive")

server = MCPServer("hs_drive", instructions=INSTRUCTIONS)


def _read_only(title: str) -> ToolAnnotations:
    return ToolAnnotations(title=title, read_only_hint=True, destructive_hint=False,
                           idempotent_hint=True, open_world_hint=False)


@server.tool(
    name="hs_status",
    title="Hero Siege status",
    description=(
        "Report whether Hero Siege is running, whether EasyAntiCheat is "
        "inactive, and whether the modded copy is installed. Reads only."),
    annotations=_read_only("Hero Siege status"),
)
def hs_status() -> dict[str, Any]:
    """Compose the machine snapshot from ForgePact's launch engine.

    `game_state` is tri-state: `running`, `not_running`, or `unknown` when the
    Windows process snapshot could not be taken. `unknown` is never read as
    "not running" anywhere in this server.

    Refusals: `engine_source_missing`. A missing ForgePact panel configuration
    is reported through `exe_validation` rather than refusing, because the
    process and anti-cheat readings are still useful without it.
    """
    return procs.status()


@server.tool(
    name="hs_selfcheck",
    title="Prove the hs-drive instruments",
    description=(
        "Run each instrument this server depends on against a positive "
        "control, so a later 'nothing found' can be trusted. Reads only; the "
        "backup round trip runs entirely inside a temporary directory."),
    annotations=_read_only("Prove the hs-drive instruments"),
)
def hs_selfcheck() -> dict[str, Any]:
    """Run every registered check and report `pass` / `fail` / `skipped`.

    A `skipped` check is not a pass: its `detail` says why it did not run. A
    check whose code raised is reported as `fail` naming the exception.

    Refusals: none. A broken check is a `fail` row, not a refused tool.
    """
    return checks.run_checks()


@server.tool(
    name="hs_saves_backup",
    title="Back up the Hero Siege save directory",
    description=(
        "Copy every file in hs2saves into a new verified, manifested backup. "
        "Refuses unless the game is provably not running."),
    annotations=ToolAnnotations(
        title="Back up the Hero Siege save directory", read_only_hint=False,
        destructive_hint=False, idempotent_hint=False, open_world_hint=False),
)
def hs_saves_backup(
    label: Annotated[str, Field(
        description="Short name for this backup; becomes part of the directory "
                    "name. 1-40 characters from A-Z a-z 0-9 . _ -",
        max_length=40)] = "manual",
) -> dict[str, Any]:
    """Snapshot the live save directory. Nothing existing is ever modified.

    Refusals: `game_running`, `game_state_unknown`, `save_dir_missing`,
    `no_character_saves`, `save_dir_too_large`, `copy_verification_failed`,
    `invalid_label`.
    """
    return saves.backup(label, gate=procs.gate)


@server.tool(
    name="hs_saves_restore",
    title="Restore the Hero Siege save directory from a backup",
    description=(
        "Overwrite hs2saves with a verified backup, after first taking a "
        "pre-restore backup of whatever is there now. Requires the backup id "
        "twice. Refuses unless the game is provably not running."),
    annotations=ToolAnnotations(
        title="Restore the Hero Siege save directory from a backup",
        read_only_hint=False, destructive_hint=True, idempotent_hint=False,
        open_world_hint=False),
)
def hs_saves_restore(
    backup_id: Annotated[str, Field(
        description="Id of the backup to restore, as reported by hs_saves_list.")],
    confirm_backup_id: Annotated[str, Field(
        description="The same id again. They must match exactly; this is the "
                    "confirmation for a destructive tool.")],
    remove_extra: Annotated[bool, Field(
        description="Move files the backup does not contain out of the live "
                    "directory and into the pre-restore backup. They are moved, "
                    "never deleted.")] = False,
) -> dict[str, Any]:
    """Restore a backup over the live save directory.

    Every restore first writes and verifies a `pre-restore` backup, so the
    state being overwritten is always recoverable. Nothing is ever deleted.

    Refusals: `confirmation_mismatch`, `game_running`, `game_state_unknown`,
    `backup_incomplete`, `backup_corrupt`, `save_dir_missing`,
    `pre_restore_backup_failed`, `copy_verification_failed`.
    """
    return saves.restore(backup_id, confirm_backup_id, remove_extra=remove_extra,
                         gate=procs.gate)


@server.tool(
    name="hs_saves_list",
    title="List save backups",
    description=(
        "Page through the backups this server has taken, newest first. A "
        "directory without a manifest lists as incomplete. Reads only."),
    annotations=_read_only("List save backups"),
)
def hs_saves_list(
    limit: Annotated[int, Field(description="How many backups to return.",
                                ge=1, le=100)] = 20,
    offset: Annotated[int, Field(description="How many to skip.", ge=0)] = 0,
) -> dict[str, Any]:
    """List backups with `total`, `count`, `has_more` and `next_offset`.

    Refusals: none. An empty or absent backup root lists as zero backups.
    """
    return saves.list_backups(limit=limit, offset=offset)


@server.tool(
    name="hs_saves_inspect",
    title="Inspect a save backup",
    description=(
        "Return a backup's manifest and how the live save directory differs "
        "from it right now, by hash. Reads only."),
    annotations=_read_only("Inspect a save backup"),
)
def hs_saves_inspect(
    backup_id: Annotated[str, Field(
        description="Id of the backup to inspect, as reported by hs_saves_list.")],
) -> dict[str, Any]:
    """The manifest plus `changed`, `added` and `missing` versus the live dir.

    Refusals: `backup_incomplete`.
    """
    return saves.inspect_backup(backup_id)


def main() -> None:
    """Serve over stdio. The only entry point; `__main__.py` calls it."""
    log.info("hs-drive starting; save dir %s, backup root %s",
             saves.save_dir(), saves.backup_root())
    server.run("stdio")
