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

import json
import logging
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Image, MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from . import capture, charselect, checks, ipc, launch, procs, saves
# `input` shadows nothing at module scope here, but a bare `input` in this file
# would read as the builtin to every later reader of it.
from . import input as input_module

INSTRUCTIONS = (
    "Order for a verified test run: hs_selfcheck -> hs_saves_backup -> "
    "hs_launch -> hs_command / hs_screenshot -> hs_stop_game -> "
    "hs_saves_inspect -> hs_saves_restore. Every refusal carries `reason`; "
    "a `skipped` self-check is not a pass. hs_launch and hs_wait_ready report a "
    "`phase` and a `ready` flag: `process_running` is not `plugin_ready`, and "
    "most gameplay commands act only once a character is loaded, which a human "
    "still has to do."
)

# stderr only. On stdio, stdout is the protocol channel.
logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s hs-drive %(levelname)s %(message)s")
log = logging.getLogger("hs_drive")

server = MCPServer("hs_drive", instructions=INSTRUCTIONS)


def _read_only(title: str) -> ToolAnnotations:
    return ToolAnnotations(title=title, read_only_hint=True, destructive_hint=False,
                           idempotent_hint=True, open_world_hint=False)


def _acts(title: str, *, destructive: bool = False,
          idempotent: bool = False) -> ToolAnnotations:
    """A tool that changes something. `destructive` is claimed sparingly.

    Only two tools here can take something away that was not theirs:
    `hs_saves_restore` overwrites the live save directory, and `hs_stop_game`
    can terminate a process. Everything else writes only files of its own --
    a backup, a screenshot, one line into `cmd.txt`.
    """
    return ToolAnnotations(title=title, read_only_hint=False,
                           destructive_hint=destructive, idempotent_hint=idempotent,
                           open_world_hint=False)


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

    Refusals: `engine_source_missing`, `engine_import_failed`. A missing
    ForgePact panel configuration is reported through `exe_validation` rather
    than refusing, because the process and anti-cheat readings are still
    useful without it.
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

    Refusals: `engine_source_missing`, `engine_import_failed`, `game_running`,
    `game_state_unknown`, `save_dir_missing`, `no_character_saves`,
    `save_dir_too_large`, `copy_verification_failed`, `invalid_label`.
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

    Refusals: `confirmation_mismatch`, `invalid_backup_id`,
    `engine_source_missing`, `engine_import_failed`, `game_running`,
    `game_state_unknown`, `backup_incomplete`, `backup_corrupt`,
    `save_dir_missing`, `restore_target_unrelated`,
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

    Refusals: `invalid_backup_id`, `backup_incomplete`.
    """
    return saves.inspect_backup(backup_id)


@server.tool(
    name="hs_launch",
    title="Launch the modded Hero Siege",
    description=(
        "Launch the ForgePact-modded game through ForgePact's own embedded "
        "HS Offline Launcher engine and wait until the plugin answers. Refuses "
        "unless the mod chain is complete. Persists nothing."),
    annotations=_acts("Launch the modded Hero Siege"),
)
def hs_launch(
    exe_path: Annotated[str | None, Field(
        description="Override the executable for this one call. Nothing is "
                    "written to ForgePact's configuration. Leave unset to use "
                    "the path the ForgePact panel already knows.")] = None,
    wait_for_plugin: Annotated[bool, Field(
        description="Wait for the BloodPact plugin to answer a ping, not just "
                    "for the process to exist.")] = True,
    timeout_s: Annotated[int, Field(
        description="Total budget for the process and plugin wait.",
        ge=5, le=600)] = 90,
) -> dict[str, Any]:
    """Launch, then report one of six readiness phases.

    `phase` is `plugin_ready` (driveable), `plugin_consumed_without_pong` (the
    ping was read and not answered, so the positive control did not fire and no
    reply from this channel can be trusted), `process_running` (up, but nobody
    asked or `bp_ipc\\` is absent), `timeout_waiting_for_plugin`,
    `timeout_waiting_for_process` or `process_exited`. `ready` is the single
    flag that says whether a command would be answered, and it is true only for
    `plugin_ready`; `ok` only says the tool ran. The game starts at its main
    menu: most gameplay commands act once a character is loaded, which nothing
    here can do.

    Refusals: `engine_source_missing`, `engine_import_failed`,
    `forgepact_config_missing`, `mod_chain_incomplete`, `launcher_refused`,
    `game_state_unknown`.
    """
    return launch.hs_launch(exe_path=exe_path, wait_for_plugin=wait_for_plugin,
                            timeout_s=float(timeout_s))


@server.tool(
    name="hs_wait_ready",
    title="Wait until Hero Siege can be driven",
    description=(
        "Poll until a Hero Siege process exists and, unless asked otherwise, "
        "until the BloodPact plugin answers a ping with pong; a ping that is "
        "consumed and not answered is reported, not treated as ready. For a "
        "game a human started. Sends one ping; starts nothing."),
    annotations=_acts("Wait until Hero Siege can be driven", idempotent=True),
)
def hs_wait_ready(
    timeout_s: Annotated[int, Field(
        description="Total budget for the wait.", ge=5, le=600)] = 90,
    require_plugin: Annotated[bool, Field(
        description="Require the plugin's ping to be consumed. With this false "
                    "the tool reports the process only, and says so.")] = True,
) -> dict[str, Any]:
    """The same poll as `hs_launch`, without launching anything.

    Refusals: `engine_source_missing`, `engine_import_failed`,
    `game_state_unknown`.
    """
    return launch.hs_wait_ready(timeout_s=float(timeout_s),
                                require_plugin=require_plugin)


@server.tool(
    name="hs_stop_game",
    title="Close Hero Siege",
    description=(
        "Post WM_CLOSE to every visible game window -- the same thing pressing "
        "X does, so the game writes its saves on the way out -- and wait for "
        "the process to exit. force=true terminates, and only a process this "
        "server launched."),
    annotations=_acts("Close Hero Siege", destructive=True, idempotent=True),
)
def hs_stop_game(
    force: Annotated[bool, Field(
        description="If the graceful close times out, terminate the process. "
                    "Refused unless this server's own hs_launch started it.")] = False,
    timeout_s: Annotated[int, Field(
        description="How long to wait for the exit before reporting or forcing.",
        ge=1, le=300)] = 30,
) -> dict[str, Any]:
    """Close the game and report `exited`, `pids_closed` and `forced`.

    `TerminateProcess` is reachable only with `force=true`, only for a PID this
    server started in this process, and only after the graceful wait has already
    timed out. A process this server did not start is refused, because killing
    one can lose whatever it had not written yet.

    Refusals: `not_launched_here`.
    """
    return launch.hs_stop_game(force=force, timeout_s=float(timeout_s))


@server.tool(
    name="hs_command",
    title="Send a ForgePact command",
    description=(
        "Write command lines to the BloodPact plugin's cmd.txt and return "
        "exactly what the plugin appended to out.txt. Try `ping` first; a "
        "player build accepts only its own command list and says so."),
    annotations=_acts("Send a ForgePact command"),
)
def hs_command(
    lines: Annotated[list[str], Field(
        description="One command per entry, e.g. [\"ping\"] or "
                    "[\"droprate 2\", \"stat\"]. ASCII only, no line breaks, "
                    "at most 64 lines and 4096 bytes.")],
    timeout_s: Annotated[int, Field(
        description="How long to wait for the plugin to consume cmd.txt. A "
                    "command already pending is waited out first and gets its "
                    "own share of this, so a call can take longer; elapsed_s "
                    "and pending_before report when it did.",
        ge=1, le=120)] = 10,
    queue: Annotated[bool, Field(
        description="With the game closed, leave the command in cmd.txt for "
                    "the plugin to run at its next start instead of refusing.")] = False,
) -> dict[str, Any]:
    """Send commands and return the reply, as the bytes appended by this command.

    The reply is a byte delta of `out.txt`, not its last lines: the plugin
    appends to that file continuously. `consumed` says whether the game read the
    command at all, and `observed_consumption` whether the plugin was watched
    reading *anything* on this channel during the call -- which is what separates
    a channel nothing reads from one that was busy running an earlier command.

    Refusals: `invalid_command`, `game_not_running`, `game_state_unknown`,
    `forgepact_config_missing`, `bp_ipc_missing`, `not_consumed`.
    """
    return ipc.send(lines, timeout_s=float(timeout_s), queue=queue)


@server.tool(
    name="hs_ipc_tail",
    title="Read the plugin's log",
    description=(
        "Return the last lines of the plugin's out.txt, including its load "
        "banner. Reads only."),
    annotations=_read_only("Read the plugin's log"),
)
def hs_ipc_tail(
    lines: Annotated[int, Field(
        description="How many trailing lines to return.", ge=1, le=500)] = 40,
) -> dict[str, Any]:
    """The tail of `out.txt`, with `exists` and `bytes_total`.

    An absent `out.txt` reports `exists: false` and carries no `lines` key at
    all: an empty list there would read as a plugin that answered nothing.

    Refusals: `forgepact_config_missing`, `bp_ipc_missing`.
    """
    return ipc.tail(lines)


@server.tool(
    name="hs_screenshot",
    title="Screenshot the game or the screen",
    description=(
        "Capture the game window (or the whole primary screen) to a PNG and "
        "return it as an image, so a human can confirm from the transcript what "
        "the game was actually showing. A capture with only one pixel value is "
        "reported as such rather than passed off as a picture."),
    annotations=_acts("Screenshot the game or the screen", idempotent=True),
)
def hs_screenshot(
    target: Annotated[Literal["game", "screen"], Field(
        description="`game` for the largest visible game window, `screen` for "
                    "the primary monitor. `screen` is the positive control: it "
                    "captures something certainly present.")] = "game",
    method: Annotated[Literal["grab_bbox", "grab_window"], Field(
        description="`grab_bbox` grabs the screen region the window occupies; "
                    "`grab_window` asks the window for its own contents. Which "
                    "works depends on the game's display mode.")] = "grab_bbox",
    label: Annotated[str, Field(
        description="Optional suffix for the file name.", max_length=40)] = "",
) -> CallToolResult:
    """Return the result envelope as text and structured output, plus the PNG.

    Two content blocks, envelope first: a client with structured output reads
    `structuredContent`, one without reads the same JSON as text, and both then
    see the image. The file on disk keeps full resolution; only the copy in the
    message is downscaled.

    Refusals: `capture_unavailable`, `invalid_command`, `game_not_running`,
    `game_state_unknown`, `no_visible_window_for_pid`, `window_minimized`.
    """
    payload = capture.screenshot(target=target, method=method,
                                 label="".join(character for character in label
                                               if character.isalnum() or character in "._-"))
    blocks: list[Any] = []
    if payload.get("ok"):
        try:
            data, width, height = capture.transport_image(Path(payload["path"]))
        except (OSError, ValueError) as exc:  # noqa: BLE001 - reported, not raised
            payload["transport_error"] = f"{type(exc).__name__}: {exc}"
        else:
            payload["transport_width"] = width
            payload["transport_height"] = height
            blocks.append(Image(data=data, format="png").to_image_content())
    blocks.insert(0, TextContent(type="text", text=json.dumps(payload, indent=2)))
    return CallToolResult(content=blocks, structured_content=payload)


@server.tool(
    name="hs_input",
    title="Send keyboard and mouse input to the game window",
    description=(
        "Inject keystrokes, clicks and waits into the Hero Siege window, "
        "either as OS-level input (SendInput, needs the game in front) or as "
        "posted window messages. An instrument for measuring what can drive "
        "the game's menus -- it makes no claim that the game reacts. Refuses "
        "unless the target window belongs to a running game process."),
    annotations=_acts("Send keyboard and mouse input to the game window"),
)
def hs_input(
    actions: Annotated[list[dict[str, Any]], Field(
        description="Up to 64 actions, in order. `{\"type\":\"key\",\"vk\":13,"
                    "\"hold_ms\":60}`, `key_down`/`key_up` with `vk`, "
                    "`{\"type\":\"click\",\"x\":100,\"y\":50,\"button\":"
                    "\"left\",\"hold_ms\":120}` (the button is held between "
                    "down and up; 0 sends down/up back to back with no "
                    "hold), `move` with `x`/`y`, `{\"type\":\"wait\","
                    "\"ms\":300}`. Click and move coordinates are client "
                    "coordinates by default -- a pixel of hs_screenshot("
                    "\"game\", capture_method=\"grab_window\") -- or virtual "
                    "screen coordinates with `\"space\":\"screen\"`.")],
    route: Annotated[Literal["send_input", "post_message"], Field(
        description="`send_input` replays the events through the OS, so they "
                    "reach device-state reads as well as window messages, and "
                    "needs the game in the foreground. `post_message` puts "
                    "messages straight on the window's queue, changes no OS "
                    "key state, and needs no foreground.")] = "send_input",
    require_foreground: Annotated[bool, Field(
        description="With `send_input`, try one SetForegroundWindow when the "
                    "game is not in front. False means never take focus: the "
                    "call is refused instead unless the game already has it. "
                    "Either way input is never sent to another window.")] = True,
) -> dict[str, Any]:
    """Inject `actions` into the game window and report what was sent.

    The result names the route, the window and its client rectangle, the
    foreground window before and after, and how many actions were performed --
    `actions_done` below `actions_total` means the sequence stopped, and
    `detail` says why. Nothing here reads the game's reaction: pair it with
    `hs_command(["roomprobe"])` or `hs_screenshot` for that.

    Refusals: `invalid_input`, `game_not_running`, `game_state_unknown`,
    `engine_source_missing`, `engine_import_failed`,
    `no_visible_window_for_pid`, `window_minimized`, `foreground_not_game`.
    """
    return input_module.inject(actions, route=route,
                               require_foreground=require_foreground)


@server.tool(
    name="hs_select_character",
    title="Select a character and reach a loaded game",
    description=(
        "Drive a freshly launched game from its main menu to a loaded "
        "character: held send_input clicks through Play local, a save slot "
        "and Play, each at the point ForgePact's read-only menulayout "
        "listing reports for that button, proved by orbpickup stat's own "
        "player-resolution field, which this tool arms and restores "
        "itself. A button the listing does not carry is refused, never "
        "guessed."),
    annotations=_acts("Select a character and reach a loaded game"),
)
def hs_select_character(
    slot: Annotated[int, Field(
        description="The save slot to load, 1-based and row-major on page "
                    "1 of the save-slot screen: slot 1 is the top-left "
                    "card, slot 2 the card to its right. A slot the "
                    "listing does not carry refuses slot_not_listed.",
        ge=1)] = 1,
    timeout_s: Annotated[float, Field(
        description="How long to keep polling orbpickup stat after the "
                    "Play click before giving up and reporting phase "
                    "\"timeout\".", ge=1, le=600)] = 60,
) -> dict[str, Any]:
    """Take a freshly launched game from its main menu to a loaded
    character, `slot`, and prove it.

    `phase` is one of `main_menu`, `local`, `slot`, `play`,
    `character_loaded`, `proof_ambiguous`, `timeout`. `character_loaded` is
    the only phase that proves a character loaded; `proof_ambiguous` means
    the save-slot screen already showed a resolver route before Play was
    clicked, so the tool stopped rather than claim a load it could not back;
    `timeout` means no route appeared within `timeout_s` of the Play click.
    `proof` is the `orbpickup stat` reply line that decided the outcome (or
    the last one read, on `timeout`); `proof_trail` is every screen's own
    reply, in the order main_menu, local, slot, play. `layout_trail` is the
    `menulayout` row each click used (`screen`, `obj`, `id`, `win`, `text`);
    every click's point is that row's `win`, verbatim. Before each click this
    tool takes focus through a bounded chain (one `SetForegroundWindow`
    attempt, then, only here and not in `hs_input`, `AttachThreadInput` and a
    zero-effect input unlock) so an unattended session's clicks still reach
    the game; `focus_trail` names which step took, per click, in click
    order. `orbpickup` is `restored_off` or `left_on`, whichever the pre-arm
    read decided -- this tool arms `orbpickup` itself to get the proof and
    restores it only if its own pre-arm read showed the mod was off before
    it started.

    Refusals: `game_not_running`, `game_state_unknown`,
    `engine_source_missing`, `engine_import_failed`, `not_consumed`,
    `no_visible_window_for_pid`, `window_minimized`, `foreground_not_game`,
    `invalid_input`, `proof_not_armed`, `character_already_loaded`,
    `layout_command_missing` (the plugin has no `menulayout`),
    `window_size_mismatch` (a listing's window never agreed with the
    client's measured size within the poll budget; a disagreement alone
    just keeps polling, since the window can still be settling to its
    configured size right after plugin_ready),
    `button_not_found` (a screen's button was never listed; the refusal's
    `last_listing` holds what was), `slot_not_listed` (fewer cards than
    `slot`), `click_not_delivered` (the injection answered but did not
    deliver the whole click -- `complete` false or `records_rejected` > 0 --
    so it is not counted in `actions_sent` or `layout_trail`).
    """
    return charselect.hs_select_character(slot=slot, timeout_s=timeout_s,
                                          tool="hs_select_character")


def main() -> None:
    """Serve over stdio. The only entry point; `__main__.py` calls it."""
    log.info("hs-drive starting; save dir %s, backup root %s",
             saves.save_dir(), saves.backup_root())
    server.run("stdio")
