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

from . import capture, charselect, checks, ipc, launch, lease, procs, saves, skills, stash
# `input` shadows nothing at module scope here, but a bare `input` in this file
# would read as the builtin to every later reader of it.
from . import input as input_module

INSTRUCTIONS = (
    "Order for a verified test run: hs_lease_acquire -> hs_selfcheck -> "
    "hs_saves_backup -> hs_launch -> hs_command / hs_screenshot -> "
    "hs_stop_game -> hs_saves_inspect -> hs_saves_restore -> "
    "hs_lease_release. The lease is machine-wide: while another session "
    "holds it, the tools that drive or overwrite the game refuse `lease_held`. "
    "Every refusal carries `reason`; "
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

    Only three tools here can take something away that was not theirs:
    `hs_saves_restore` overwrites the live save directory, `hs_stop_game`
    can terminate a process, and `hs_lease_acquire` with `force` takes
    another session's game lease. Everything else writes only files of its
    own -- a backup, a screenshot, one line into `cmd.txt`, this server's
    own lease record.
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

    While this server holds the game lease, the backup's id is recorded in
    it and a restore is marked owed (`restore_pending`).

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

    Asks the game lease first: `lease_held` while another session holds it.
    A restore of the backup the lease recorded clears its `restore_pending`.

    Refusals: `lease_held`, `lease_unavailable`, `confirmation_mismatch`,
    `invalid_backup_id`, `engine_source_missing`, `engine_import_failed`, `game_running`,
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

    Refusals: `lease_held`, `lease_unavailable`, `engine_source_missing`,
    `engine_import_failed`, `forgepact_config_missing`,
    `mod_chain_incomplete`, `launcher_refused`, `game_state_unknown`.
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

    Refusals: `lease_held`, `lease_unavailable`, `not_launched_here`.
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

    Refusals: `lease_held`, `lease_unavailable`, `invalid_command`,
    `game_not_running`, `game_state_unknown`, `forgepact_config_missing`,
    `bp_ipc_missing`, `not_consumed`.
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

    Refusals: `lease_held`, `lease_unavailable`, `invalid_input`,
    `game_not_running`, `game_state_unknown`,
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

    Refusals: `lease_held`, `lease_unavailable`, `game_not_running`,
    `game_state_unknown`, `engine_source_missing`, `engine_import_failed`,
    `not_consumed`,
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


@server.tool(
    name="hs_skills_status",
    title="Read the skill bar and learned talents",
    description=(
        "Send ForgePact's read-only `skillstate` and return the skill bar's "
        "slots (talent id, abilityId, and the effect-object count that proves "
        "a toggle cast), the learned talent ids and each bar talent's "
        "sub-talent nodes. Reads no key, point count or level: none has a "
        "measured reader."),
    annotations=_read_only("Read the skill bar and learned talents"),
)
def hs_skills_status() -> dict[str, Any]:
    """`slots` (`row`, `index`, `talent_id`, `ability`, `timer`, `effect` or
    null), `learned` (`global.mySkills`), `subtalents` (`"<id>"` ->
    `{"s<NN>": level}`, `{}` without a node), `proof` (the reply's lines),
    `verb_trail` (`["skillstate"]`). The send is lease-gated like
    `hs_command`'s.

    Refusals: `lease_held`, `lease_unavailable`, `game_not_running`,
    `game_state_unknown`, `engine_source_missing`, `engine_import_failed`,
    `not_consumed`, `bp_ipc_missing`, `forgepact_config_missing`,
    `plugin_verb_missing` (the plugin predates `skillstate`, or answered in a
    format this server cannot read).
    """
    return skills.hs_skills_status()


@server.tool(
    name="hs_skill_cast",
    title="Cast a skill from the bar by its key",
    description=(
        "Press the key you name for one bar slot through the game's own input "
        "path (held send_input, 120 ms) and prove the cast by that slot's "
        "effect-object count changing in `skillstate`. The count is read "
        "three times, 0.5 s apart, before the press and must not move without "
        "one. The key is yours to supply: no per-slot key reader was found. A "
        "slot whose skill has no effect object is refused, not guessed."),
    annotations=_acts("Cast a skill from the bar by its key"),
)
def hs_skill_cast(
    key: Annotated[int, Field(
        description="The Windows virtual-key code that casts this slot, e.g. 81 "
                    "for Q (the HUD's own label for slot 0,3 - measured, live 3 "
                    "and live 4).",
        ge=1, le=254)],
    slot: Annotated[str | None, Field(
        description="The bar slot as \"row,index\" (row 0 is the drawn bar). "
                    "Give this or ability, not both.")] = None,
    ability: Annotated[str | None, Field(
        description="The abilityId as hs_skills_status prints it, e.g. "
                    "\"darkOath\". Give this or slot, not both.")] = None,
    timeout_s: Annotated[float, Field(
        description="How long to poll skillstate for the effect count to move "
                    "after the press.", ge=1, le=60)] = 10,
) -> dict[str, Any]:
    """`ok` with `confirmed: true`, `effect_before`/`effect_after`,
    `effect_samples_before` (the flat pre-press reads) and `proof` (the slot's
    line before and after) when the count moved; the key sent is in
    `injected`. No backup is asked: a cast is play, not a save write.

    Refusals: `lease_held`, `lease_unavailable`, `invalid_input`,
    `game_not_running`, `game_state_unknown`, `engine_source_missing`,
    `engine_import_failed`, `not_consumed`, `plugin_verb_missing`,
    `skill_not_on_bar` (no row-0 slot holds it, or the slot is empty),
    `proof_unavailable` (the slot has no effect= count), `proof_unstable` (the
    count moved with no key pressed; nothing injected), `no_visible_window_for_pid`,
    `window_minimized`, `foreground_not_game`, `key_not_delivered`,
    `cast_not_confirmed` (delivered, and the count never moved).
    """
    return skills.hs_skill_cast(key, slot=slot, ability=ability, timeout_s=timeout_s)


@server.tool(
    name="hs_skill_bind",
    title="Bind a skill to a bar slot (not measured: refuses)",
    description=(
        "Refuses route_not_measured and sends nothing: the skill research did "
        "not reproduce a bind by name (bindRoute: shape not reproduced). The "
        "signature is fixed for when a session measures it."),
    annotations=_acts("Bind a skill to a bar slot (not measured: refuses)"),
)
def hs_skill_bind(
    slot: Annotated[str, Field(description="The bar slot as \"row,index\".")],
    ability: Annotated[str, Field(description="The abilityId to bind there.")],
    backup_id: Annotated[str, Field(
        description="A save backup taken before hs_launch in this session.")],
) -> dict[str, Any]:
    """Refusals: `lease_held`, `lease_unavailable`, `route_not_measured`
    (always, with `verb_trail: []`)."""
    return skills.hs_skill_bind(slot, ability, backup_id)


@server.tool(
    name="hs_talent_allocate",
    title="Put one talent point in, by the game's own handler",
    description=(
        "Send ForgePact's `talentalloc`: open the talent screen if needed and "
        "run the talent's (or a sub-talent node's) own button handler by name, "
        "then confirm by re-reading skillstate - the id joining the learned "
        "list, or one node rising by one - and close the screen with T. "
        "Needs a save backup taken before this session's hs_launch."),
    annotations=_acts("Put one talent point in, by the game's own handler"),
)
def hs_talent_allocate(
    talent_id: Annotated[int, Field(
        description="The talent's numeric id, as hs_skills_status and the talent "
                    "screen's menulayout rows print it (e.g. 244 for Black Mass).",
        ge=1)],
    backup_id: Annotated[str, Field(
        description="A whole save backup taken with hs_saves_backup before "
                    "hs_launch in this session.")],
    sub: Annotated[int | None, Field(
        description="Put the point into the talent's nth sub-talent node instead "
                    "(1-based, in the order menulayout lists the open panel's "
                    "nodes; the nodes carry no name).", ge=1)] = None,
) -> dict[str, Any]:
    """`ok` with `confirmed: true`, `what` changed, `learned`, `subtalents`,
    `proof` (the re-read lines), `verb_lines` (the verb's own reply),
    `screen_closed` and `close_detail`. Only a talent not yet learned is
    allocated (only 0 -> 1 was measured).

    Refusals: `lease_held`, `lease_unavailable`, `invalid_input`,
    `game_not_running`, `game_state_unknown`, `engine_source_missing`,
    `engine_import_failed`, `invalid_backup_id`, `backup_incomplete`,
    `backup_corrupt`, `no_session_backup` (the backup is not older than the
    running game), `not_consumed`, `plugin_verb_missing`,
    `talent_screen_not_open`, `talent_not_allocatable` (no button carries the
    id, or it is already learned), `alloc_not_confirmed` (the re-read shows no
    change: no point count is readable, so a missing free point reads the
    same).
    """
    return skills.hs_talent_allocate(talent_id, backup_id, sub=sub)


@server.tool(
    name="hs_talent_reset",
    title="Reset the talent tree (not measured: refuses)",
    description=(
        "Refuses route_not_measured and sends nothing: the skill research's "
        "by-name reset dispatched and changed nothing (resetRoute: shape not "
        "reproduced). The signature is fixed for when a session measures it."),
    annotations=_acts("Reset the talent tree (not measured: refuses)"),
)
def hs_talent_reset(
    backup_id: Annotated[str, Field(
        description="A save backup taken before hs_launch in this session.")],
) -> dict[str, Any]:
    """Refusals: `lease_held`, `lease_unavailable`, `route_not_measured`
    (always, with `verb_trail: []`)."""
    return skills.hs_talent_reset(backup_id)


_BACKUP_FIELD = Field(description="A whole save backup taken with hs_saves_backup before "
                                  "hs_launch in this session.")


@server.tool(
    name="hs_give_item",
    title="Give the character a copy of an item it holds",
    description=(
        "Send ForgePact's `giveitem bag <template> <count>`: a copy of an item "
        "the character's map 0 already holds, made by the game's own loader and "
        "placed in the bag grid the game prefers for it. Confirmed only by the "
        "verb's own `giveitem: confirmed` line with one more item after than "
        "before; no window needs to be open. to=\"stash\" refuses "
        "route_not_measured. Needs a save backup taken before this session's "
        "hs_launch."),
    annotations=_acts("Give the character a copy of an item it holds"),
)
def hs_give_item(
    to: Annotated[str, Field(description="\"bag\" (measured) or \"stash\" (refuses route_not_measured).")],
    template: Annotated[str, Field(
        description="The fingerprint of an item map 0 holds, as a menulayout `cell=` row "
                    "prints it, e.g. 0-0-209564349884-14.")],
    backup_id: Annotated[str, _BACKUP_FIELD],
    count: Annotated[int, Field(
        description="Units for a stackable copy, 1 up to the template's own stack; a "
                    "non-stackable takes 1. Only 1 was measured.")] = 1,
) -> dict[str, Any]:
    """`ok` with `confirmed: true`, `key` (the new fingerprint), `before`
    and `after` (items in the destination cells), `o`, `verb_trail`,
    `layout_trail` and `proof` (the verb's lines, plus a `cell=` row when a
    listed grid shows the key).

    Refusals: the lease and process gates' (`lease_held`,
    `lease_unavailable`, `game_not_running`, `game_state_unknown`,
    `engine_source_missing`, `engine_import_failed`),`route_not_measured`, `invalid_input`,
    `count_unsupported`, `invalid_backup_id`, `backup_incomplete`,
    `backup_corrupt`, `no_session_backup`, `plugin_verb_missing`,
    `template_not_found`, `give_refused`, `give_not_confirmed`.
    """
    return stash.hs_give_item(to, template, backup_id, count=count)


@server.tool(
    name="hs_stash_open",
    title="Put the character at the town stash and open it",
    description=(
        "Warp the character beside the town stash with ForgePact's `playerwarp` "
        "(the stash's own position, 48 below), confirm the warp by re-reading "
        "Player_obj, press the interact key F, and poll menulayout until the "
        "stash window is listed. There is no by-name open. Needs a save backup "
        "taken before this session's hs_launch."),
    annotations=_acts("Put the character at the town stash and open it"),
)
def hs_stash_open(
    backup_id: Annotated[str, _BACKUP_FIELD],
    timeout_s: Annotated[float, Field(
        description="Budget for each poll (the warp, then the window), at most "
                    "30 reads 0.5 s apart.", gt=0)] = 60,
) -> dict[str, Any]:
    """`ok` with `phase: "stash_open"`, `route: "interact"`, `window_id`,
    `stash_tab_selected`, `target`, `verb_trail`, `layout_trail` (the key)
    and `proof`.

    Refusals: the lease and process gates' (`lease_held`,
    `lease_unavailable`, `game_not_running`, `game_state_unknown`,
    `engine_source_missing`, `engine_import_failed`),`invalid_backup_id`, `backup_incomplete`,
    `backup_corrupt`, `no_session_backup`, `layout_command_missing`,
    `stash_already_open`, `stash_not_reachable`, `plugin_verb_missing`,
    `warp_not_confirmed`, `click_not_delivered` (F not delivered whole),
    `stash_not_open`, and `hs_input`'s window refusals.
    """
    return stash.hs_stash_open(backup_id, timeout_s=timeout_s)


@server.tool(
    name="hs_stash_close",
    title="Close the stash by its own close button's handler",
    description=(
        "Send ForgePact's `stashclose` (UiACloseButton by name, the stash's "
        "close button as self and the window as other) and poll menulayout "
        "until no stash window is listed. The game's own close is what saves "
        "the stash, so a session that gave or switched anything closes before "
        "it stops. Takes no backup."),
    annotations=_acts("Close the stash by its own close button's handler"),
)
def hs_stash_close() -> dict[str, Any]:
    """`ok` with `phase: "stash_closed"`, `window_id`, `verb_trail`, `proof`.

    Refusals: the lease and process gates' (`lease_held`,
    `lease_unavailable`, `game_not_running`, `game_state_unknown`,
    `engine_source_missing`, `engine_import_failed`),`layout_command_missing`, `stash_not_open`,
    `plugin_verb_missing`, `stash_still_open`.
    """
    return stash.hs_stash_close()


@server.tool(
    name="hs_stash_tab",
    title="Switch the open stash to a tab",
    description=(
        "Send ForgePact's `stashtab <tabNumber>` (the tab button's own handler, "
        "by name) and poll menulayout until the stash window's stashTabSelected "
        "reads that tab. Needs a save backup taken before this session's "
        "hs_launch."),
    annotations=_acts("Switch the open stash to a tab"),
)
def hs_stash_tab(
    tab: Annotated[str, Field(
        description="socketable, materials, unique, personal, or shared1 to shared19.")],
    backup_id: Annotated[str, _BACKUP_FIELD],
) -> dict[str, Any]:
    """`ok` with `tab_number`, `selected_before`, `selected_after`,
    `handler` (or `already_selected: true` with nothing sent), `verb_trail`,
    `proof`.

    Refusals: the lease and process gates' (`lease_held`,
    `lease_unavailable`, `game_not_running`, `game_state_unknown`,
    `engine_source_missing`, `engine_import_failed`),`unknown_tab`, `invalid_backup_id`,
    `backup_incomplete`, `backup_corrupt`, `no_session_backup`,
    `layout_command_missing`, `stash_not_open`, `tab_not_listed`,
    `plugin_verb_missing`, `route_not_measured` (the tab's handler is not a
    shape live 2 reproduced), `tab_not_selected`.
    """
    return stash.hs_stash_tab(tab, backup_id)


@server.tool(
    name="hs_bag_tab",
    title="Switch the bag beside the open stash to a sub-tab",
    description=(
        "Send ForgePact's `bagtab materials|socket` (the sub-tab's own handler, "
        "by name) and poll menulayout until the stash window's tabSelected "
        "moves. Proves tabSelected, not the focus (activeNode). Any other "
        "sub-tab refuses route_not_measured, and the bag without the stash open "
        "refuses bag_not_open. Needs a save backup taken before this session's "
        "hs_launch."),
    annotations=_acts("Switch the bag beside the open stash to a sub-tab"),
)
def hs_bag_tab(
    tab: Annotated[str, Field(description="materials or socket (the two measured by name).")],
    backup_id: Annotated[str, _BACKUP_FIELD],
) -> dict[str, Any]:
    """`ok` with `selected_before`, `selected_after`, `activeNode_before`,
    `activeNode_after`, `focus_note`, `verb_trail`, `proof`.

    Refusals: the lease and process gates' (`lease_held`,
    `lease_unavailable`, `game_not_running`, `game_state_unknown`,
    `engine_source_missing`, `engine_import_failed`),`route_not_measured`, `invalid_backup_id`,
    `backup_incomplete`, `backup_corrupt`, `no_session_backup`,
    `layout_command_missing`, `bag_not_open`, `tab_not_listed`,
    `plugin_verb_missing`, `tab_not_selected`.
    """
    return stash.hs_bag_tab(tab, backup_id)


@server.tool(
    name="hs_lease_acquire",
    title="Take the machine-wide game lease",
    description=(
        "Take the one game lease on this machine before driving Hero Siege, "
        "so another session's launch, commands, input, stop or restore are "
        "refused while this one runs. Records the label, slot and the "
        "installed BloodPactPlugin.dll's SHA-256. A crashed holder's lease "
        "is recovered. force=true takes a live session's lease away and "
        "belongs to the owner's decision only."),
    annotations=_acts("Take the machine-wide game lease", destructive=True),
)
def hs_lease_acquire(
    label: Annotated[str, Field(
        description="Who is driving, as another session's refusal will name "
                    "it, e.g. <slug>-live-<n>. 1-80 characters from "
                    "A-Z a-z 0-9 . _ -",
        max_length=80)],
    slot: Annotated[int | None, Field(
        description="The save slot this session will load, if known.",
        ge=1)] = None,
    force: Annotated[bool, Field(
        description="Take the lease even though another live process holds "
                    "it. The previous holder is named in `took_over_from`.")] = False,
) -> dict[str, Any]:
    """Take the lease, or refuse naming who has it.

    A free or stale lease is taken; a stale one reports `recovered_stale`
    and `previous.outcome: "stale"`. Re-acquiring a lease this server holds
    refreshes `label` and `slot` and reports `already_held`. A released
    lease whose session still owed a restore is taken with a `warning`.

    Refusals: `lease_held` (another live process holds it; `detail` names
    its label, pid and when it took it), `lease_unavailable` (the record is
    unreadable or the lock could not be taken; `force` replaces an
    unreadable record), `invalid_label`.
    """
    return lease.acquire(label, slot=slot, force=force)


@server.tool(
    name="hs_lease_status",
    title="Report who holds the game lease",
    description=(
        "Report whether the machine-wide game lease is free, held by this "
        "session, held by another live session, stale (its holder is gone) "
        "or unreadable, and whether the installed BloodPactPlugin.dll has "
        "changed since it was taken. Reads only."),
    annotations=_read_only("Report who holds the game lease"),
)
def hs_lease_status() -> dict[str, Any]:
    """`state` is `free`, `held`, `held_by_me`, `stale` or `unavailable`.

    `record` is the lease while one is held or stale; `last` is the released
    record when the lease is free, so a restore the last session still owed
    shows as a `warning`. `dll_sha256_now` and `dll_changed_since_taken`
    compare the installed plugin with the one recorded at acquire.

    Refusals: none. An unreadable record is the state `unavailable`.
    """
    return lease.status()


@server.tool(
    name="hs_lease_release",
    title="Release the game lease",
    description=(
        "Release the game lease this session holds. The record is kept as "
        "released, so the next session can see whether a restore is still "
        "owed."),
    annotations=_acts("Release the game lease", idempotent=True),
)
def hs_lease_release() -> dict[str, Any]:
    """Mark this server's lease released and report `restore_pending`.

    When a backup was taken under the lease and no restore of it has been
    recorded, the release still succeeds and carries a `warning` naming the
    backup id.

    Refusals: `lease_not_held` (nobody holds it, it is already released, or
    its holder is gone -- `hs_lease_acquire` recovers a stale one),
    `lease_held` (another live process holds it), `lease_unavailable`.
    """
    return lease.release()


def main() -> None:
    """Serve over stdio. The only entry point; `__main__.py` calls it."""
    log.info("hs-drive starting; save dir %s, backup root %s",
             saves.save_dir(), saves.backup_root())
    server.run("stdio")
