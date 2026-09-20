# `hs-drive` — a local MCP server for driving Hero Siege from a session

`tools/hs_drive_mcp/` is a developer-only stdio MCP server. It lets a Claude
Code session ask whether Hero Siege is running, whether EasyAntiCheat is
inactive and whether the modded copy is installed; prove its own instruments
work; back up and restore the player's `hs2saves\` directory without ever being
able to lose a file; launch the ForgePact-modded game through ForgePact's own
launch engine and wait until the BloodPact plugin answers; send any ForgePact
command and read back exactly the plugin's reply; screenshot the game window;
and close the game politely enough that its exit-time save write completes.

What it cannot do is play the game. There is no synthetic input of any kind, and
the game comes up at its main menu — **most ForgePact gameplay commands act only
once a character is loaded**, which still takes a human click. See "Known
limitations".

Nothing here ships to a player. It is a Python package under `tools/`, the way
`freeze_probe.ps1` and `source_index.py` are — imported by no binary, named in
no packaging input, and pinned as absent from every release input by
`tests/test_hs_drive_mcp_release_boundary.py`.

## Why it lives in the hub

- **Not in `HS-Offline-Launcher`.** Its guide records that the launcher is *by
  design* a standalone, single-file, stdlib-only application; an `mcp`
  dependency changes its PyInstaller packaging. It is also a separate
  repository with its own release cadence.
- **Not in `ForgePact`**, for the same packaging reason — `build_release.py`
  bundles `src/` with PyInstaller and excludes `PIL` deliberately.
- **Not a new submodule.** Nothing is player-facing, packaged or catalogued,
  and `.mcp.json` lives at the hub root anyway.

`tools/` has no `__init__.py`; `py -3 -m tools.hs_drive_mcp` resolves under
namespace-package rules with the repo root as the working directory, and the
root suite imports the package the same way `tests/test_source_index.py`
imports `tools/`.

## Install

```powershell
py -3 -m pip install -r tools/hs_drive_mcp/requirements.txt
```

Two pins, and only two. `mcp==2.2.0` pulls `pydantic`, `anyio`, `httpx`,
`starlette`, `pywin32` and the rest of its own tree. `Pillow==12.1.0` is what
`hs_screenshot` captures and downscales with; `PIL.ImageGrab.grab` on this pin
accepts both `all_screens=` and `window=`, which is why both capture methods
exist.

**`mcp` 2.x is not `mcp` 1.x.** The widely-copied
`from mcp.server.fastmcp import FastMCP` is the 1.x API and raises
`ModuleNotFoundError` against this pin, by design. The 2.x spelling is:

```python
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
server = MCPServer("hs_drive", instructions=...)
@server.tool(name=..., title=..., description=..., annotations=ToolAnnotations(...))
def hs_status() -> dict[str, Any]: ...
server.run("stdio")
```

Structured output is inferred from the `dict` return annotation. The test
client ships in the same wheel (`mcp.client.stdio.stdio_client`), which is how
`tests/test_hs_drive_mcp_server.py` interrogates a real running server rather
than the decorators.

## Wiring

`.mcp.json` carries it as a sibling of `tauri-hub`:

```json
"hs-drive": {
  "command": "py",
  "args": ["-3", "-m", "tools.hs_drive_mcp"]
}
```

That argv assumes Claude Code starts a project-scoped stdio server with the
project root as its working directory. The other entries are `npx` packages
and prove nothing about it, so **this assumption is confirmed by opening a
fresh session and running `/mcp`**, not by anything in the suite. If
`hs-drive` does not appear connected, replace `args` with
`["-3", "<absolute path to this checkout>/tools/hs_drive_mcp/__main__.py"]`;
if that connects, the working-directory assumption was wrong and
`__main__.py` needs to re-root itself before relative resolution will work.
Record the outcome in the Verification table below.

### One sharp edge, measured

Do not repoint `LOCALAPPDATA` at a temporary directory for the server's
process. The `py` launcher keeps its installed runtimes under
`%LOCALAPPDATA%\Python`; with that variable moved it concludes no runtime is
installed, begins downloading one, and writes `Downloading: ...` to **stdout**
— which on a stdio transport is the protocol channel. The client then dies on
`Invalid JSON: expected value at line 1 column 1`, which names nothing useful.
Use `HS_DRIVE_SAVE_DIR` and `HS_DRIVE_BACKUP_DIR` instead; they redirect
everything this server writes.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `HS_DRIVE_SAVE_DIR` | `%LOCALAPPDATA%\Hero_Siege\hs2saves` | The live save directory. Also covers an install whose saves sit directly in `%LOCALAPPDATA%\Hero_Siege`; nothing auto-detects that layout. |
| `HS_DRIVE_BACKUP_DIR` | `%LOCALAPPDATA%\HSDriveMcp\save-backups` | Where backups accumulate. |
| `HS_DRIVE_SCREENSHOT_DIR` | `%LOCALAPPDATA%\HSDriveMcp\screenshots` | Where `hs_screenshot` writes its full-resolution PNGs. |

Every test sets the ones it can reach. That is the whole reason they exist: a
suite that ran against the owner's real saves would be one mistake away from a
bug report nobody can undo.

## Tools

Twelve. One tool per action, `hs_` prefixed, with annotations on every one.

| Tool | Hints | Inputs | Returns |
| --- | --- | --- | --- |
| `hs_status` | read-only | — | `game_state`, `game_pids`, `eac_service`, `exe_path`, `exe_valid`, `exe_validation`, `mod_chain`, `ipc_dir`, `bp_ipc_exists`, `launch` |
| `hs_selfcheck` | read-only | — | `checks[]`, `summary` |
| `hs_saves_backup` | writes | `label` | `backup_id`, `files`, `total_bytes`, `path`, `skipped_links` |
| `hs_saves_restore` | **destructive** | `backup_id`, `confirm_backup_id`, `remove_extra=false` | `restored`, `files`, `pre_restore_backup_id`, `moved_extras`, `extras_not_moved` |
| `hs_saves_list` | read-only | `limit` 1–100 = 20, `offset` | `total`, `count`, `has_more`, `next_offset`, `backups[]` |
| `hs_saves_inspect` | read-only | `backup_id` | `manifest`, `changed[]`, `added[]`, `missing[]` |
| `hs_launch` | writes | `exe_path=null`, `wait_for_plugin=true`, `timeout_s` 5–600 = 90 | `phase`, `ready`, `plugin`, `plugin_reply`, `pid`, `pids`, `launch`, `exe_path`, `exe_path_override`, `launched_here`, `launch_message`, `elapsed_s` |
| `hs_wait_ready` | writes (one ping) | `timeout_s` 5–600 = 90, `require_plugin=true` | the same readiness fields, without the launch ones |
| `hs_stop_game` | **destructive** | `force=false`, `timeout_s` 1–300 = 30 | `exited`, `pids_closed`, `forced`, `terminated`, `windows_found`, `errors`, `game_state` |
| `hs_command` | writes | `lines[]`, `timeout_s` 1–120 = 10, `queue=false` | `consumed`, `reply`, `reply_lines`, `queued`, `pending_before`, `pending_left`, `out_bytes_before`, `out_bytes_after`, `rotated`, `sent`, `wrote_bytes`, `aborted` |
| `hs_ipc_tail` | read-only | `lines` 1–500 = 40 | `exists`, `lines[]`, `bytes_total`, `requested`, `truncated`, `path` |
| `hs_screenshot` | writes | `target` `game`\|`screen` = `game`, `method` `grab_bbox`\|`grab_window` = `grab_bbox`, `label` | `path`, `width`, `height`, `bbox`, `capture_method`, `hwnd`, `pid`, `flat`, `warning`, `bytes_written`, `transport_width`, `transport_height` — **plus** a JSON text block and a PNG image block |

`hs_saves_restore` and `hs_stop_game` are the only tools with
`destructiveHint: true`, and that is asserted rather than assumed: they are the
two that can take away something that was not theirs — the live save directory,
and a process. Everything else writes only files of its own.

`hs_screenshot` is also the only tool that does not return a plain dict. It
returns a `CallToolResult` carrying the envelope twice — as `structuredContent`
and as a JSON text block, first, so a client without structured output reads the
same thing — and then the image. The file on disk keeps its full resolution;
only the copy in the message is downscaled (to 1280 px wide).

Server `instructions`, which a client shows to the model:

> Order for a verified test run: `hs_selfcheck` → `hs_saves_backup` →
> `hs_launch` → `hs_command` / `hs_screenshot` → `hs_stop_game` →
> `hs_saves_inspect` → `hs_saves_restore`. Every refusal carries `reason`; a
> `skipped` self-check is not a pass. `hs_launch` and `hs_wait_ready` report a
> `phase` and a `ready` flag: `process_running` is not `plugin_ready`, and most
> gameplay commands act only once a character is loaded, which a human still has
> to do.

## The result envelope

Every tool returns a dict with at least `ok`, `tool` and `refused`. A refusal
is a normal, successful result carrying `refused: true`, a `reason` token and
a `detail` that names the file, path or state it tripped over. **A refusal is
never an exception thrown across the transport**: an exception arrives as a
protocol error with a stack trace, which is the one shape a model cannot
branch on.

Tokens this server can return today:

| Token | Meaning |
| --- | --- |
| `engine_source_missing` | `ForgePact/src/offline_launcher.py` is not in this checkout, so there is no engine to take a process snapshot with. The save tools return this too, not `game_state_unknown`: a clone without `--recursive` is fixed by `git submodule update --init ForgePact`, and a refusal naming a Win32 call that was never attempted sends the reader to the wrong subsystem. |
| `engine_import_failed` | That file is present but will not import — a partial checkout, or a Python that cannot load `ctypes.wintypes`. A different machine state with a different fix, so it does not borrow the name above. |
| `forgepact_config_missing` | `game_exe` is not set in `%LOCALAPPDATA%\Hero_Siege\forgepact.json`. |
| `game_running` | A `hero_siege.exe` process is live. |
| `game_state_unknown` | The process snapshot was attempted and failed, or could not be attempted on this platform. The detail is the gate's own account of which. |
| `save_dir_missing` | No directory at the resolved save path. |
| `no_character_saves` | The directory holds no `herosiege*.hss`, so it is not a save directory. |
| `save_dir_too_large` | Over the 256 MB ceiling — almost always a mis-set `HS_DRIVE_SAVE_DIR`. |
| `restore_target_unrelated` | The directory to restore *into* is neither empty, nor a save directory, nor made only of files this backup names — so it is not where this backup came from. |
| `copy_verification_failed` | A copy did not re-hash equal to its source. |
| `backup_incomplete` | The backup directory has no readable `manifest.json`. |
| `backup_corrupt` | A file in the backup no longer matches its manifest hash, or a manifest entry names something that is not a plain file name; the detail names it. |
| `invalid_backup_id` | A `backup_id` that is not one bare directory name — a path, `..`, or empty. |
| `pre_restore_backup_failed` | The restore could not first back up what is live, so it did not start. |
| `confirmation_mismatch` | `confirm_backup_id` did not equal `backup_id`. |
| `invalid_label` | A backup label outside `^[A-Za-z0-9._-]{1,40}$`. |
| `mod_chain_incomplete` | One of the four install facts is false — the exe carries no `.aurie` section, or `AurieCore.dll`, `YYToolkit.dll` or `BloodPactPlugin.dll` is missing. The detail names which. The engine refused before starting anything. |
| `launcher_refused` | ForgePact's launch engine refused for any of its own reasons — the game is already running, EAC is active or unreadable, `steam_api64.dll` is missing, a launch is already in progress. `error` carries the engine's message verbatim. |
| `game_not_running` | A tool that needs a live game did not find one. `hs_command` accepts `queue=true` to leave the command for the next start instead. |
| `bp_ipc_missing` | `<game>\bin\bp_ipc\` does not exist. The plugin creates it at load, so the modded game has never run. |
| `invalid_command` | Something about the call cannot be sent or done: non-ASCII, an embedded line break, over 64 lines, over 4096 bytes, or a `target`/`method` that is not one of the documented values. |
| `not_consumed` | `cmd.txt` was still on disk when the timeout expired, so the plugin never read it. The command is deliberately **left** there; the plugin runs a pending file at its next start. `aborted` says so when the wait stopped early because the process disappeared. |
| `no_visible_window_for_pid` | The game is running but owns no visible top-level window — usually a window that has not appeared yet. |
| `window_minimized` | The game's only visible window is minimized, so capturing its rectangle would photograph whatever is behind it. |
| `not_launched_here` | `force=true` on a PID this server's own `hs_launch` did not start. Killing a process someone else started can lose whatever it had not written. |
| `capture_unavailable` | Pillow is not importable, so nothing can be captured. Not `invalid_command`: the arguments were fine and the install is not. |

## The process gate

`procs.game_state()` is tri-state: `running`, `not_running`, or `unknown` when
the engine's `processes()` raised `OSError` or the platform has no Windows
process table to read. `unknown` refuses every gated tool exactly as hard as
`running` does. That is `AGENTS.md` § "Check a Permission Where It Is Used"
applied here — a sentinel meaning *unknown* must never compare equal to a real
value — and it matches the engine's own fail direction, where a failed snapshot
makes `launch_safety_blocker()` say the launch was blocked.

The **gate** the save tools ask has five states, not three. `game_state()`
collapses the two engine ones to `unknown` so `hs_status` keeps the shape it
was specified against, but the gate keeps them apart because they have
different fixes, and a refusal that names the wrong one costs a session:

| Gate state | Refusal token | What is actually wrong |
| --- | --- | --- |
| `running` | `game_running` | Close the game. |
| `not_running` | — | The only state that lets a write through. |
| `unknown` | `game_state_unknown` | The snapshot failed, or this is not Windows. |
| `engine_missing` | `engine_source_missing` | `git submodule update --init ForgePact`. |
| `engine_unusable` | `engine_import_failed` | The engine file is there but will not import. |

A gate answers `(state, why)` — it cannot report a state without reporting how
it got there — and the refusal detail *is* that `why`, not a sentence composed
at the point of refusal. That is the correction, and it was needed twice: a
checkout missing `ForgePact/` refused every save operation with a detail about
a Win32 call nobody attempted, while `hs_status`, which asks the bridge
directly, correctly said `engine_source_missing` about the same machine; then
the non-Windows and unimportable cases did the same thing one layer down. Two
tools disagreeing about one machine state is the bug. Carrying the reason with
the answer makes them agree by construction rather than by each caller
remembering to re-derive it.

Matching is by image name. ForgePact's panel additionally matches the full
image path, because a Steam copy and an offline copy can be open at once; this
server reports `game_pids` and leaves that distinction to the caller instead
of guessing which one was meant.

## Launching: ForgePact's engine, not a second copy of it

`hs_launch` calls `ForgePact/src/offline_launcher.py::launch_game(path,
validate_extra=…)` and does none of that work itself. The engine owns the PE
validation, the already-running and anti-cheat checks (three times, around the
Steam start), the `steam_api64.dll` lookup, the `SteamAppId`/`SteamGameId`
environment, the `Popen`, and a delayed check that reports "the game exited
during startup". Owner decision, 2026-09-20: *"For launcher use forgepact."*

This server supplies the two things that engine deliberately leaves to its
caller:

- **The path**, from `forgepact.json` (see "The engine is ForgePact's" below).
  `exe_path` overrides it for one call and **persists nothing** — a test
  compares a fixture `%LOCALAPPDATA%` tree byte for byte across a launch to keep
  that true.
- **The plugin preflight**, as the `validate_extra` callable the engine invokes
  inside its own validation. Doing it there rather than here is what makes
  "`Popen` was never reached" true by construction rather than by inspection:
  the engine refuses first, and this server only has to translate the refusal —
  `mod_chain_incomplete` when the preflight is what failed, `launcher_refused`
  for everything else, with `error` carrying the engine's words. The preflight
  object remembers its own verdict, so the two are told apart by what happened
  rather than by matching the engine's wording.

### Readiness is three answers, and they are never merged

| `phase` | `ready` | What it means |
| --- | --- | --- |
| `plugin_ready` | true | A `ping` was consumed and answered. The game is driveable. |
| `process_running` | true only with `require_plugin=false` | The process exists. With `plugin: "no_bp_ipc"` the channel is not there at all; with `plugin: "not_checked"` nobody asked. |
| `timeout_waiting_for_plugin` | false | The process is up and nothing consumed `cmd.txt`: the plugin is not loaded. |
| `timeout_waiting_for_process` | false | No `hero_siege.exe` appeared. |
| `process_exited` | false | It was there and went away; the detail carries the engine's own `launch_status()` message, which names a startup exit. |

`ok` says the tool ran; `ready` says whether a command would be answered. A
launch that ended at `timeout_waiting_for_plugin` is `ok: true, ready: false` —
nothing was refused, and nothing is ready either. Reporting that as success is
the "armed but blind" shape `AGENTS.md` § "Prove the Instrument Before Trusting a
Negative Result" exists to catch, and the plugin's `ping`/`pong` is the positive
control that separates the two.

The plugin wait hands `ipc.send` an `abort` callback that watches the process
gate, because the longest wait here is for a plugin that is still loading and a
wait that cannot notice the game died would burn its whole 90 s budget after a
startup crash and then report a timeout — sending the reader to the wrong
subsystem. ForgePact's own `wait_for_plugin_ready` stops on the same condition.

### Stopping: `WM_CLOSE`, and almost never anything else

`hs_stop_game` posts `WM_CLOSE` to every visible top-level window of every game
PID. That is the user pressing X: the game runs its own exit path and **writes
its saves**, which is what makes `hs_saves_inspect` after a session meaningful
(`docs/submodules/HSSaveEditor/instructions.md` § "Process Boundaries").

`TerminateProcess` is reachable only when all three of these hold: `force=true`,
the PID is in the set this server's own `hs_launch` started **in this process**,
and the graceful wait has already timed out. Any other PID is
`not_launched_here` — `AGENTS.md` § "Drive a Tauri App Yourself" ("never kill a
process you did not start") applied to a game instead of a dev server. The
launched set is in memory on purpose: a PID from an earlier run of this server
has no claim on whatever process wears that number now.

Nothing here pauses, freezes, time-scales or restores runtime state.
`AGENTS.md` § "Don't Suspend the Game's Own Runtime" was checked against this
whole workorder; `WM_CLOSE` is a request the game is free to handle its own way,
which is the opposite of taking its loop away.

## The command channel

ForgePact's IPC is two files in `<dir of game_exe>\bp_ipc\`, created by the
plugin at load. `hs_command` and `hs_ipc_tail` are the MCP counterparts of
`ForgePact/tools/ipc.ps1` and run the same algorithm:

- `cmd.txt` — one command per line, polled every few frames. The plugin reads
  it, **deletes it**, then runs each line. Written as plain ASCII with CRLF
  endings and **no BOM**: the plugin reads raw bytes and splits on newlines, so a
  UTF-8 BOM corrupts the first command instead of failing visibly. Limits are 64
  lines and 4096 bytes; a line break inside one entry is `invalid_command`
  rather than a silent split into commands the caller never wrote.
- `out.txt` — append-only, and appended to by other features while a command
  runs. The reply is therefore the **byte delta** after the pre-send length, not
  the last N lines. After consumption the size is polled every 150 ms until it
  has been unchanged four times running (bounded by the timeout plus 10 s),
  because a big command appends for a while after `cmd.txt` disappears. If
  `out.txt` *shrank* — the plugin rotates it to `out.prev.txt` at load when it is
  over 2 MB — the offset is stale, so the whole file is read and `rotated: true`
  says the reply may carry more than this command's output.

Two deliberate differences from `ipc.ps1`, both because a model rather than a
person is driving:

1. **A pending `cmd.txt` is appended to, not overwritten.** `ipc.ps1` overwrites
   with a warning a person reads; nothing reads a warning here, and silently
   dropping a command the caller believes was sent is the worse failure.
   `pending_before: true` reports that it happened.
2. **An unconsumed command is a refusal token**, `not_consumed`, with the
   timeout in the detail — and the file is left in place, because the plugin
   runs a pending file at its next start. That is also what `queue=true` is for:
   with the game closed it writes the command and returns immediately instead of
   refusing `game_not_running`. `unknown` refuses either way — a queued command
   against a game that might be running is a command that might run immediately.

The server does not allow-list commands; it forwards them and returns the reply.
A **player (release) plugin build** accepts only `kPlayerCommands` and answers
anything else with `command unavailable in player build: <cmd>`, which arrives as
the reply rather than as a refusal. A research build (`plugin_build\build.bat
dev`) accepts far more. `ping` → `pong (YYTK a.b.c)` is the channel's positive
control and what the `ipc_ping` self-check and the readiness probe both use.

`hs_ipc_tail` reports `exists: false` and **no `lines` key at all** when
`out.txt` is absent. An empty list there would read as "the plugin answered
nothing", which is a different machine state with a different fix.

## Screenshots

`hs_screenshot` identifies the window by PID, never by window class: the
GameMaker class name is unverified for this build and `procs.game_pids()`
already answers the question. Of the visible, non-minimized top-level windows of
those PIDs, the largest by area is the game — a splash or tool window is
smaller. Minimized is its own refusal, because a minimized window still has a
rectangle and would otherwise capture whatever is behind it.

Two capture methods, both reported as `capture_method` so a later reader knows
which produced a given file:

| `capture_method` | Call | Notes |
| --- | --- | --- |
| `grab_bbox` (default) | `ImageGrab.grab(bbox=…, all_screens=True)` | The screen region the window occupies. `all_screens` is on only when a bbox is given, because window rectangles are in virtual-desktop coordinates — a monitor left of the primary one has negative x. |
| `grab_window` | `ImageGrab.grab(window=hwnd)` | Asks the window for its own contents. |
| — | `ImageGrab.grab()` | What `target="screen"` uses: the primary monitor, and this module's positive control. |

**A capture whose every pixel is the same value comes back with `warning:
"image_is_flat"` and says so in `detail`.** A picture of nothing and a picture of
a dark game are the same bytes; the difference is this warning. That is why
`target="screen"` exists as a control — a flat *game* capture beside a non-flat
*screen* capture localises the problem to the window rather than to Pillow — and
why `screenshot_screen` is a registered positive control rather than a
convenience.

Files land in `%LOCALAPPDATA%\HSDriveMcp\screenshots\<UTC stamp>[_label].png` at
full resolution and nothing prunes them.

## Saves: what the tools guarantee

The live directory is a snapshot target, not a guessed subset: **every regular
file directly in it** is copied, with no recursion and no links. On this
machine that is 137 files and 1.5 MB.

Both backup and restore are gated. Restore is obvious; backup is gated because
`docs/submodules/HSSaveEditor/instructions.md` § "Process Boundaries" records
that the game rewrites these files on exit, so a backup taken mid-session is
superseded before it could ever be restored. HS-Offline-Tracker's watcher
needs two identical reads to trust a changed file for the same reason.

A backup directory looks like this:

```
<backup root>/<UTC yyyymmddTHHMMSSZ>_<label>/
    files/<every copied file>
    manifest.json
```

The copies sit in `files/` rather than beside the manifest so a save directory
that happens to contain a `manifest.json` cannot collide with the backup's own
metadata.

`manifest.json` carries `schema: "hs-drive-save-backup/1"`, `id`, `label`,
`created_utc`, `source_dir`, `game_state_at_backup`, `total_bytes`, and
`files: [{name, size, sha256}]`. It is written **last**, through a temp file
and `os.replace`, so a directory without one is unambiguously incomplete
rather than half-trustworthy — and that is exactly what `hs_saves_list`
reports it as.

Four rules hold everywhere:

1. **Nothing is ever deleted.** A backup that fails verification is *renamed*
   `<id>.failed`. Extras are *moved* into the pre-restore backup. A failed
   copy leaves its `.hsdrive-tmp` file beside the target and the refusal names
   it. There is no code path in `saves.py` that removes a file, which is what
   makes "could it have deleted a save?" answerable by reading it — and
   `test_the_save_module_calls_nothing_that_removes_a_file` keeps that
   answerable, by walking the parsed module for a call to `unlink`, `remove`,
   `rmdir`, `removedirs`, `rmtree` or `shutil.move`. It reads the tree rather
   than the text because `saves.py` discusses all of those in its own comments,
   explaining why it uses none of them, and a grep would trip on the
   explanation instead of the code.
2. **The gate is asked twice** — at the start, and again immediately before
   the first write, because everything in between is file reads and the game
   can start during them.
3. **A copy counts only once it has been re-read.** Every file is hashed at
   the source, copied, and hashed again from the copy; a restore is
   additionally re-verified from the live directory afterwards.
4. **Every restore first writes and verifies a `pre-restore` backup.** If that
   backup is refused or fails verification, the restore refuses
   `pre_restore_backup_failed` and the live directory is untouched.

`hs_saves_backup` refuses a directory holding no `herosiege*.hss` — that check
guards against backing up a directory the caller *guessed at*, almost always a
mis-set `HS_DRIVE_SAVE_DIR`. The pre-restore backup does **not** apply it: its
target was chosen by the restore rather than guessed, and it has to work on a
directory that has been wiped or corrupted. That is the case
`hs_saves_restore` exists for, and requiring a character save there made the
tool refuse exactly when it was needed. The 256 MB ceiling is not relaxed with
it; that guard is about a path pointing somewhere enormous and still applies to
both.

Relaxing it needed a replacement, though, because that check was also the only
thing stopping a restore *into* a directory that had never held a save — and
with `remove_extra=true` that directory's own files would be moved into the
pre-restore backup. So `hs_saves_restore` asks its own question about the
target, and accepts it three ways:

1. **it is empty** — there is nothing there to be wrong about;
2. **it holds at least one `herosiege*.hss`** — the same positive signal
   `hs_saves_backup` identifies a save directory by, so an ordinary live
   directory with unrelated extras in it restores exactly as it always did;
3. **every file in it is one this backup names** — a partially wiped save
   directory, where the characters are gone and `shop.ini` is all that is left.

Anything else is `restore_target_unrelated`, and nothing is read or written.
The post-wipe recovery case and a directory of unrelated files are tested
beside each other on purpose: widening what is accepted must not be able to
drift into accepting anything.

`backup_id` is model-chosen and becomes a path component, and a manifest
`name` is joined to both the backup and the live directory. Both must be one
bare path component — `saves.is_bare_name()` checks POSIX *and* Windows
flavours, because on Linux `..\x` is an ordinary filename and a POSIX-only
check would let a Windows traversal through the very test meant to catch it.

## `hs_selfcheck` — proving the instrument

`AGENTS.md` § "Prove the Instrument Before Trusting a Negative Result" exists
because 34 hooked call sites once reported zero calls across confirmed,
observed events: every zero measured the instrument, not the game. The same
trap is open here — `hs_status` reporting `not_running` is indistinguishable
from a process snapshot that never worked.

| Check | Passes when | Skipped when |
| --- | --- | --- |
| `engine_import` | The engine loads and every `ENGINE_SYMBOLS` name resolves | never — a missing source is `fail`, naming the path |
| `process_snapshot` | The snapshot returns rows **including this server's own PID** | non-Windows |
| `eac_service` | `eac_service_status()` is not `unknown` | non-Windows |
| `save_dir` | The live directory exists and holds ≥ 1 `herosiege*.hss` (count in `detail`) | never |
| `backup_roundtrip` | A temp fixture backs up, is damaged, and restores byte-identical through the real `saves` functions | never |
| `screenshot_screen` | A capture of the primary screen holds more than one distinct pixel value | non-Windows, or Pillow not importable |
| `ipc_ping` | The running plugin consumes a `ping` and answers `pong` within 10 s | the game is not running (the detail says so) |

A check whose code raised is `fail` with the exception name, never `skipped`.
`skipped` always carries its reason in `detail`, because "we did not look" and
"we looked and it broke" must not be confusable. `checks.py` is a registry, which
is how `screenshot_screen` and `ipc_ping` were added with two `register()` calls
and no change to any logic there.

`ipc_ping` is deliberately **not** a positive control: it can only run with the
modded game up, and a check that is usually skipped cannot be what `healthy`
rests on. When the game *is* running it is a real one, and a `fail` there means
the game is running without the plugin loaded.

`summary.healthy` is **not** "nothing failed". It requires every check
registered with `positive_control=True` — `process_snapshot`,
`backup_roundtrip` and `screenshot_screen` — to have *passed*. A run where everything was
skipped has zero failures and has proved nothing, and `healthy` is the field a
caller branches on; a self-check that reports itself armed while blind is the
one failure this tool cannot delegate. `summary` also carries
`positive_controls` and `positive_controls_proven` so the difference is
visible, not inferred. A check added with `register(name, fn)` and no flag
counts toward `failed` but never props `healthy` up.

## The engine is ForgePact's, imported

`launcher_bridge.py` loads `ForgePact/src/offline_launcher.py` by path and
uses it as it is. That module already owns every Win32 helper this server
needs — the process snapshot, the EAC service query, the PE validation, the
Steam runtime lookup — and ForgePact's own suite pins those helpers against
the HS-Offline-Launcher revision they were audited from
(`UPSTREAM_REVISION = 5910880`, exactly the commit checked out here). A second
copy would be a third copy in the toolkit.

Nothing under `ForgePact/`, `HS-Offline-Launcher/` or `hs-game-sdk/` is
modified by any of this.

`ENGINE_SYMBOLS` names what this server calls, and
`tests/test_hs_drive_mcp_engine_bridge.py` asserts every one is still defined
in the engine source, so a ForgePact pointer bump that renames one fails in
the suite instead of at the owner's first tool call.

Two things the engine deliberately leaves to its caller are filled in here
rather than by falling back to another launcher:

- **The executable's path.** `resolve_exe()` reads `game_exe` from
  `%LOCALAPPDATA%\Hero_Siege\forgepact.json` — the same file
  `ForgePact/tools/ipc.ps1` reads — and writes nothing back. Persisting a path
  into the user's own launcher configuration is the side effect that ruled out
  HS-Offline-Launcher's module. Its loopback API was ruled out too: the token
  is `secrets.token_urlsafe(32)` per boot and injected only into the served
  HTML, so using it means scraping it and needing the GUI running.
- **The plugin preflight.** `mod_chain(exe)` reports `patched` (an `.aurie`
  section in the PE), `aurieCore`, `yytk` and `plugin` — the same four facts
  `ForgePact/src/forgepact.py::mod_chain()` checks. That module is not
  imported: it is a three-thousand-line panel that pulls in its own icon
  module and an optional SDK.

## Known limitations

- **Nothing here can select a character or enter a zone, and most ForgePact
  gameplay commands only act once one is loaded.** After `hs_launch` the game
  sits at its main menu. Static research on 2026-09-20 found no
  name-resolvable route to character select that could be trusted without a live
  research round, and this server has no synthetic keyboard or mouse input by
  design, so an in-game verification still needs a human to load a character
  once — after which every tool here works against that session. A third,
  research-shaped workorder (`hs-drive-mcp-charselect`) is where that belongs.
- **Exclusive fullscreen may capture flat.** Which of `grab_bbox` and
  `grab_window` returns a real image depends on the game's display mode; the
  measurement is in the Verification table below, per mode. A flat result is
  always reported as such (`warning: "image_is_flat"`) rather than passed off as
  a picture. If both methods come back flat in a mode, the workaround is to run
  the game windowed or borderless while driving it.
- **Screenshots accumulate too**, at full resolution, under
  `%LOCALAPPDATA%\HSDriveMcp\screenshots\`. Nothing prunes them, for the same
  reason nothing prunes backups: no tool in this server has removal as its
  effect.
- **A forced stop is not available for a game you started yourself.** That is
  the point of `not_launched_here`, not an oversight. Close it from its own
  window.
- **Backups accumulate and nothing prunes them.** Removal is deliberately out
  of scope — no tool in this server has removal as its effect. Each backup is
  about 1.5 MB, and a restore writes two (the pre-restore one, plus whatever
  it restored from). Delete old directories under
  `%LOCALAPPDATA%\HSDriveMcp\save-backups\` by hand. Whether a prune tool with
  its own confirmation is wanted is an open decision.
- **A save layout outside `hs2saves\` is not auto-detected.** If saves sit
  directly in `%LOCALAPPDATA%\Hero_Siege`, set `HS_DRIVE_SAVE_DIR`.
- **`remove_extra` cannot move a file across volumes.** Extras are moved with
  `os.replace` only, because `shutil.move`'s cross-volume fallback is a copy
  followed by an unlink *inside the live save directory*, which nothing in
  this module is allowed to do. When the backup root is on another drive the
  extra is left in place and reported in `extras_not_moved` with the operating
  system's reason. Both defaults are under `%LOCALAPPDATA%`, so this only
  arises with a redirected `HS_DRIVE_BACKUP_DIR`.
- **Backups while the game is running are not supported and never will be**,
  for the reason in "Saves" above.
- **Windows only.** The engine imports `ctypes.wintypes`; the tests skip with
  a named reason elsewhere, which is what lets the root suite run on CI's
  `ubuntu-latest` without any submodule checked out.

## Verification

| # | Check | Command | Result |
| --- | --- | --- | --- |
| A1 | Dependencies install and are pinned | `py -3 -m pip install -r tools/hs_drive_mcp/requirements.txt` | exit 0; `mcp==2.2.0` and `Pillow==12.1.0` both found — 2026-09-20 |
| A2 | `.mcp.json` entry | parsed in `tests.test_hs_drive_mcp_release_boundary` | `command: py`, `args: ["-3","-m","tools.hs_drive_mcp"]`, no `url`/`type` — 2026-09-20 |
| A3/A4/A7 | Tool surface over stdio, self-check, status, `healthy` semantics | `py -3 -m unittest tests.test_hs_drive_mcp_server -v` | `OK`, 17 tests, no skips — all twelve tools listed, `screenshot_screen` `pass`, `ipc_ping` `skipped` ("the game is not running") — 2026-09-20 |
| A5 | Engine pin, inert import, missing-source refusal | `py -3 -m unittest tests.test_hs_drive_mcp_engine_bridge -v` | `OK`, 8 tests, no skips — 2026-09-20 |
| A6 | No stdout, no listener, no shell | `Select-String -Path tools/hs_drive_mcp/*.py -Pattern 'shell=True\|os\.system\(\|socket\.\|\.bind\(\|HTTPServer\|uvicorn\|streamable\|^\s*print\('` | no matches — 2026-09-20 |
| B1–B10 | Save backup and restore, the wiped-directory recovery case and its negative control | `py -3 -m unittest tests.test_hs_drive_mcp_saves -v` | `OK`, 36 tests, no skips — 2026-09-20 |
| C6 | Release boundary, including the mechanical no-deletion check | `py -3 -m unittest tests.test_hs_drive_mcp_release_boundary -v` | `OK`, 7 tests, no skips — 2026-09-20 |
| C7 | Whole root suite, with the first six tools | `py -3 -m unittest discover -s tests` | `Ran 741 tests`, `OK (skipped=9)` — all nine skips pre-existing in other suites — 2026-09-20 (superseded by the F3 row below) |
| C7 | This change touches no submodule | `git -C ForgePact status --porcelain`, `git -C HS-Offline-Launcher status --porcelain` | both printed nothing — 2026-09-20. (An unrelated ` M HS-Offline-Tracker` gitlink drift predates this work; `git diff --stat 589246f HEAD` touches no submodule.) |
| — | Self-check on this machine, first five checks | `hs_selfcheck` over stdio | all five `pass` (137 files, 48 characters in the live dir; snapshot sees own PID; EAC `stopped`) — 2026-09-20 |
| — | Self-check on this machine, all seven | `hs_selfcheck` over stdio, in `tests.test_hs_drive_mcp_server` | six `pass` including `screenshot_screen`; `ipc_ping` `skipped` naming "the game is not running", with no game up. `summary.healthy` therefore rests on three proven positive controls — 2026-09-20 |
| C1–C6 | Launch through ForgePact's engine, the three readiness phases, `WM_CLOSE`, and `TerminateProcess`'s three conditions with its negative control | `py -3 -m unittest tests.test_hs_drive_mcp_launch -v` | `OK`, 29 tests, no skips — 2026-09-20 |
| D1–D6 | The IPC channel: ASCII/CRLF/no BOM, append-not-overwrite, byte-delta reply, `not_consumed`, the gate, `bp_ipc` resolution, `tail` | `py -3 -m unittest tests.test_hs_drive_mcp_ipc -v` | `OK`, 27 tests, no skips — runs in full on CI too, since it needs neither Windows nor a submodule — 2026-09-20 |
| E1–E3 | Window resolution and its three refusals, both capture methods, the flat-image warning with a negative control, the downscaled transport copy, the image block | `py -3 -m unittest tests.test_hs_drive_mcp_screenshot -v` | `OK`, 33 tests, no skips — 2026-09-20 |
| — | Real screen capture on this machine (positive control) | `PositiveControlTests` in that suite, and `hs_selfcheck`'s `screenshot_screen` | 2560×1440, more than 4 distinct pixel values, `pass` — 2026-09-20 |
| F3 | Whole root suite, after the six new tools | `py -3 -m unittest discover -s tests` | `Ran 831 tests`, `OK (skipped=9)` — the same nine pre-existing skips in other suites; the 90 added here skip nowhere on this machine — 2026-09-20 |
| F3 | This change touches no submodule | `git -C ForgePact status --porcelain`, `git -C HS-Offline-Launcher status --porcelain` | both printed nothing — 2026-09-20 |
| — | The six new tools over a real stdio session, with the game **closed** (fixture save/backup/screenshot directories) | one-off client script; the same argv `.mcp.json` carries | `list_tools` returned all twelve. `hs_selfcheck`: six `pass`, `ipc_ping` `skipped` ("the game is not running"), `healthy: true` on three proven controls. `hs_ipc_tail`: `exists: true`, `bytes_total: 34256` against the real `bp_ipc\out.txt`. `hs_command ["ping"]`: refused `game_not_running`. `hs_screenshot("screen")`: `text` + `image` blocks, 2560×1440 file, `transport_width: 1280`, not flat. `hs_stop_game`: `exited: true`, `pids_closed: []`, `forced: false` — 2026-09-20 |
| F4 | Live sequence: `hs_selfcheck` → `hs_saves_backup` → `hs_launch` → `hs_screenshot` → `hs_command ping` → `hs_stop_game` → `hs_saves_inspect` → `hs_saves_restore` | owner-run from a Claude Code session with `hs-drive` connected | **not yet run** — owner-run against the real modded install; the independent manual save copy it needs already exists at `C:\Users\stann\HeroSiege-manual-save-backup\hs2saves-20260920-pre-hs-drive` |
| F4 | Capture in `windowed` — `hs_screenshot("game")` with both `capture_method`s | owner-run, display mode set from the game's own Options menu | **not yet run** — record which method returned a non-flat image, any `warning`, and the file path |
| F4 | Capture in `borderless` — the same two calls | owner-run | **not yet run** — as above |
| F4 | Capture in `exclusive_fullscreen` — the same two calls | owner-run | **not yet run** — if both are flat, the documented workaround (already in Known limitations) is to run the game windowed or borderless while driving it |
| C1 | `hs-drive` connects in a fresh session | `/mcp` in a new Claude Code session at the repo root | **pass**, owner-run 2026-09-20: listed as connected. The working-directory assumption holds — `args: ["-3", "-m", "tools.hs_drive_mcp"]` resolves as a namespace package from the repo root, so no absolute-path fallback and no `os.chdir` were needed. Note the session must *start* at the repo root: a session already running when this entry was added does not pick it up, and shows the server as absent rather than failed. |

## What is deliberately not here

- **Character select, and anything that needs one.** See "Known limitations".
- **Synthetic keyboard or mouse input**, of any kind, by any route. Nothing in
  this server presses a key.
- **Pause, freeze, time-scale, save-state or forced state restore** —
  `AGENTS.md` § "Don't Suspend the Game's Own Runtime", and
  `ForgePact/docs/menu-pause-plan.md` § 0 for the worked example of why.
- **Installing, removing or building the plugin, or patching the exe.** The
  server assumes an installed modded copy and refuses `mod_chain_incomplete`
  otherwise. Those are the ForgePact panel's job.
- **Reading game memory, `itemstats.json`, or hooking anything.**
- **Video capture, multi-monitor stitching, OCR of screenshots.**

## Changing any of this

```powershell
py -3 -m unittest tests.test_hs_drive_mcp_server -v            # the surface a client sees
py -3 -m unittest tests.test_hs_drive_mcp_engine_bridge -v     # the ForgePact pin
py -3 -m unittest tests.test_hs_drive_mcp_saves -v             # the fail-closed save contract
py -3 -m unittest tests.test_hs_drive_mcp_launch -v            # launch, readiness, WM_CLOSE, force
py -3 -m unittest tests.test_hs_drive_mcp_ipc -v               # the bp_ipc command channel
py -3 -m unittest tests.test_hs_drive_mcp_screenshot -v        # window resolution and capture
py -3 -m unittest tests.test_hs_drive_mcp_release_boundary -v  # nothing shipped knows it exists
py -3 -m unittest discover -s tests                            # all of the above, plus the rest
```

Adding a tool means adding its refusal tokens to `results.REASONS` (the
envelope refuses an unknown token outright), its annotations in `server.py`,
its row in the Tools table above, and its name to the expected set in
`tests/test_hs_drive_mcp_server.py`. Adding a self-check means one
`checks.register(...)` call and a row in the table above.

`server.py` is still the only module that imports the MCP SDK — `ipc.py`,
`capture.py` and `launch.py` import none of it, which is what lets the IPC suite
run on CI with neither the SDK nor a submodule present. The release-boundary
suite asserts that, and it also asserts that these three modules *exist*: until
this workorder landed it asserted the opposite, because an empty stub would have
made the work look partly done.
