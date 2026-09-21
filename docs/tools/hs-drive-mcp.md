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

Fourteen. One tool per action, `hs_` prefixed, with annotations on every one.

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
| `hs_command` | writes | `lines[]`, `timeout_s` 1–120 = 10, `queue=false` | `consumed`, `reply`, `reply_lines`, `queued`, `pending_before`, `pending_left`, `observed_consumption`, `out_bytes_before`, `out_bytes_after`, `rotated`, `sent`, `wrote_bytes`, `aborted` |
| `hs_ipc_tail` | read-only | `lines` 1–500 = 40 | `exists`, `lines[]`, `bytes_total`, `requested`, `truncated`, `path` |
| `hs_screenshot` | writes | `target` `game`\|`screen` = `game`, `method` `grab_bbox`\|`grab_window` = `grab_bbox`, `label` | `path`, `width`, `height`, `bbox`, `capture_method`, `hwnd`, `pid`, `flat`, `warning`, `bytes_written`, `transport_width`, `transport_height` — **plus** a JSON text block and a PNG image block |
| `hs_input` | writes | `actions[]` (≤ 64), `route` `send_input`\|`post_message` = `send_input`, `require_foreground=true` | `route`, `pid`, `hwnd`, `window_rect`, `client_rect`, `client_size`, `dpi`, `foreground_before`, `foreground_after`, `focus_via`, `actions_done`, `actions_total`, `records_sent`, `records_rejected`, `complete`, `elapsed_s` |
| `hs_select_character` | writes | `slot` ≥ 1 = 1, `timeout_s` 1–600 = 60 | `phase`, `proof`, `proof_trail`, `layout_trail`, `focus_trail`, `screenshots`, `orbpickup`, `actions_sent`, `elapsed_s` (a refusal after the arm also carries `last_listing`) |

`hs_input`'s actions are objects, in order, each with a `type`:

| `type` | Fields | What it sends |
| --- | --- | --- |
| `key` | `vk` 1–254, `hold_ms` 0–10000 = 60 | press, wait, release |
| `key_down` / `key_up` | `vk` | one half of a press; a `key_down` with no matching `key_up` leaves the key down, which is the caller's business |
| `click` | `x`, `y`, `button` `left`\|`right` = `left`, `space` `client`\|`screen` = `client`, `hold_ms` 0–10000 = 120 | move, button down, wait, button up |
| `move` | `x`, `y`, `space` | the move only |
| `wait` | `ms` 0–10000 | nothing; it sleeps |

Coordinates default to the **client area**, which is exactly what a pixel of
`hs_screenshot("game", capture_method="grab_window")` is — measured 2026-09-20,
a 1920×1080 client captured as 1920×1080 — so a point read off that screenshot
can be passed straight in. `space: "screen"` takes virtual-desktop coordinates
instead. Every point is checked against the client rectangle **before anything
is sent**, so a coordinate typo cannot leave a half-applied sequence.

The two routes reach different depths, which is the point of having both.
`send_input` replays events through the operating system, so they are visible
to device-state reads as well as to window messages, and it needs the game in
the foreground; `post_message` puts messages straight on the window's queue,
touches no OS key state, and needs no foreground. A runner that polls the
device state sees the first and not the second.

On `send_input`, `focus_via` says how the game got the foreground:
`already_foreground` (it already had it), `set_foreground` (the one
`SetForegroundWindow` attempt every caller gets), `not_required`
(`post_message`, or `require_foreground=false`), or `null` on a
`foreground_not_game` refusal. `hs_input` never asks for more than that one
attempt — see "What is deliberately not here" for why, and for the caller
that does escalate further.

`records_sent` and `records_rejected` count whichever unit the route deals in —
`SendInput` records on `send_input`, posted messages on `post_message` — and
both routes read their own delivery signal, because each has exactly one.
`SendInput` reports how many records the system accepted; `PostMessageW`
reports only whether the message was queued, and it answers false without
queueing anything on a UIPI integrity mismatch (the game launched elevated,
this process not), on a window destroyed part way through a sequence, and on a
full message queue. Any refusal stops the rest of the sequence, counts in
`records_rejected`, clears `complete`, and puts the message name and the
`GetLastError` code in `detail` — `PostMessageW(WM_KEYDOWN) failed with error
5`. Without that reading the route would answer `complete: true` having
delivered nothing, and a `keyboard_check` of false afterwards would be
measuring this tool rather than the game (`AGENTS.md` § "Prove the Instrument
Before Trusting a Negative Result").

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
| `not_consumed` | `cmd.txt` was still on disk when the wait expired. One token, three shapes, and the detail says which — because they have different fixes. (a) Nothing consumed anything: the plugin reading *this* channel is **not observed**, not absent (see "The command channel" for the second-copy case), `observed_consumption: false`. (b) A command was *already* pending when `hs_command` was called and never went away: `wrote_bytes: 0`, and the detail says this command was not written at all. (c) The pending command **was** consumed and this one then was not: `observed_consumption: true`, and the detail says the plugin was watched reading this channel and that this command's own wait is what expired — the second-copy paragraph is deliberately absent, because the same call disproved it. In every shape the file is deliberately **left** there; the plugin runs a pending file at its next start, and `aborted` says so when the wait stopped early because the process disappeared. |
| `no_visible_window_for_pid` | The game is running but owns no visible top-level window — usually a window that has not appeared yet. |
| `window_minimized` | The game's only visible window is minimized, so capturing its rectangle would photograph whatever is behind it. |
| `not_launched_here` | `force=true` on a PID this server's own `hs_launch` did not start. Killing a process someone else started can lose whatever it had not written. |
| `capture_unavailable` | Pillow is not importable, so nothing can be captured. Not `invalid_command`: the arguments were fine and the install is not. |
| `foreground_not_game` | `route="send_input"` found some other window in front and could not raise the game. `SendInput` goes to whatever is in front, so the keystrokes would have landed somewhere that never asked for them. `hs_input` gets one `SetForegroundWindow` attempt (`require_foreground: false` skips even that); `hs_select_character` escalates through the bounded chain in `focus_attempts` — `set_foreground`, then, only if that did not take, `attach_thread_input` and `input_unlock` — and the refusal's `detail` names every step tried. The same comparison runs again immediately before **every** injection, so a sequence that loses the foreground half way through stops there and reports `actions_done` — `AGENTS.md` § "Check a Permission Where It Is Used". |
| `invalid_input` | `hs_input`'s own arguments: more than 64 actions, an empty list, an unknown `type`, `button` or `space`, a `vk` outside 1–254, a `hold_ms` or `ms` outside 0–10000, or a point outside the client rectangle (or the virtual screen, with `space: "screen"`). Nothing was sent. Deliberately separate from `invalid_command`, which means "the plugin would not accept that" and sends a reader to the wrong place. |
| `layout_command_missing` | `hs_select_character` asked ForgePact's `menulayout` where the main-menu buttons are and got no listing: the installed plugin answered `command unavailable in player build: menulayout` (it predates the command), or replied with no `menulayout: room=` header at all. There is nothing to click from, so nothing is clicked. |
| `window_size_mismatch` | A `menulayout` listing's `window=` disagreed with the client size this server re-measures at that same read, on every read within the poll budget (30 reads 0.5 s apart) — the window never settled to the listing's size. A single disagreeing read is not this refusal by itself: `hs_launch`'s `plugin_ready` can precede the window reaching its configured size, so one mismatch just keeps the poll going. Its `win` points were computed for a different window, so none of them is clicked. Checked on the main menu's listing, before the first click, and on every listing read after. |
| `button_not_found` | The button `hs_select_character` needed on a screen was not listed within the poll budget (30 reads 0.5 s apart): no single visible `UI_Button_obj` reading exactly `Play local` on the main menu, or save slot `slot` / the character panel's `Play` after the previous click. The detail quotes the last listing's header and the visible rows it did offer; the refusal's `last_listing` holds that listing whole. No click is sent for that screen. |
| `slot_not_listed` | `Chose_rm` listed fewer visible save-slot cards than `slot` on two reads in a row. Only page 1 of the save-slot screen is reachable; no card is guessed. |
| `proof_not_armed` | `hs_select_character` armed `orbpickup` (`orbpickup 1`) and either got no acknowledgement, or `orbpickup stat` still read `player via (not tried)` on two reads at least a second apart. The resolver never ran; the instrument is blind, not the game — the same trap an earlier revision of this doc's own "`orbpickup stat` does not prove a character is loaded" section fell into. No click is sent. |
| `character_already_loaded` | `hs_select_character`'s menu-time read of `orbpickup stat` already named a resolver route before any click was sent. |

One shape does **not** come back as a refusal: a `route` that is neither
`send_input` nor `post_message` is rejected by the SDK's own `Literal`
validation before any code here runs, and arrives as a protocol error —
measured 2026-09-20 over a real stdio session: `Error executing tool
hs_input: 1 validation error for hs_inputArguments … Input should be
'send_input' or 'post_message'`. That is the same SDK layer as the dropped
unknown argument in "Known limitations", and it is a better outcome than a
refusal; the module still answers `invalid_input` for an in-process caller,
which is what its own tests exercise.

`research_build_required` is **not** a token this server defines. It was
reserved for a branch (shipping a player verb behind a research-build check)
that the character-select measurement did not select; `mcp-only` shipped
instead, so nothing here ever needs it, and `tests.test_hs_drive_mcp_input`
asserts it stays absent from `results.REASONS`.

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

### Readiness is four answers, and they are never merged

| `phase` | `ready` | What it means |
| --- | --- | --- |
| `plugin_ready` | true | A `ping` was consumed **and answered** `pong`. The game is driveable. |
| `plugin_consumed_without_pong` | false | The ping was consumed and the answer was not a `pong` — nothing, or something else. The plugin's positive control did not fire, so no reply from this channel can be trusted: an empty `hs_command` reply cannot be told apart from a command that did nothing. `plugin_reply` carries whatever was appended and the detail says how many bytes. |
| `process_running` | true only with `require_plugin=false` | The process exists. With `plugin: "no_bp_ipc"` the channel is not there at all; with `plugin: "not_checked"` nobody asked. |
| `timeout_waiting_for_plugin` | false | The process is up and the ping was not consumed. If nothing was consumed at all, the plugin reading *this* channel is **not observed** — see below for why that is not the same as "not installed". If the wait watched the plugin clear an *earlier* (queued) command first, the detail says that instead: the channel is read and the ping's own wait expired. |
| `timeout_waiting_for_process` | false | No `hero_siege.exe` appeared. |
| `process_exited` | false | It was there and went away; the detail carries the engine's own `launch_status()` message, which names a startup exit. |

`ok` says the tool ran; `ready` says whether a command would be answered, and it
is true only for `plugin_ready`. A launch that ended at
`timeout_waiting_for_plugin` is `ok: true, ready: false` — nothing was refused,
and nothing is ready either. Reporting that as success is the "armed but blind"
shape `AGENTS.md` § "Prove the Instrument Before Trusting a Negative Result"
exists to catch, and the plugin's `ping`/`pong` is the positive control that
separates the two — which is exactly why a consumed ping that came back without
a `pong` is **not** `ready`. That state used to report `plugin_ready, ready:
true`, and the plugin's `Out()` writes failing is a recorded case (the panel
holding `out.txt` open), so it is a state that really happens and really does
make every later reply unreadable.

The two `not_consumed` answers — this phase and `hs_command`'s refusal — say
what was *observed*: nothing consumed `cmd.txt` at the named path within N s.
They deliberately stop there rather than concluding the plugin is absent, and
name both explanations, because the two halves of that inference come from
different installs: the process gate matches by **image name**, while `bp_ipc\`
is resolved from the **configured** executable, and ForgePact's plugin derives
its own channel from its own module path so that each copy of the game gets a
separate one. A second copy running — the documented two-instance co-op setup —
produces this exact reading with the plugin fully loaded. The detail names the
configured path so it can be compared with the `pids` in the same envelope.
`AGENTS.md` § "Check a Permission Where It Is Used" (write a negative down as
"not observed", not "does not happen").

That paragraph is withheld when the same call **watched** the plugin take a
command off this channel — `observed_consumption: true`, the state
`hs_command(queue=true)` then `hs_wait_ready` produces, since the plugin runs the
queued command at load. Both of its explanations are disproved by that
observation, so repeating them would send the reader to compare install paths for
a plugin that is demonstrably alive; what the envelope says instead is that the
channel is being read and that this command's own wait expired, which has a
different fix (the earlier command may still be running — read `out.txt` with
`hs_ipc_tail`, or retry with a larger `timeout_s`). This is also why `timeout_s`
is **split** between the two waits rather than spent first-come: a wait handed
whatever the previous one left over can end up with ~0 s and then report the
caller's `timeout_s` as though it had waited that long. The refusals report the
wait that actually happened.

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

1. **With the game running, a pending `cmd.txt` is waited out — never added to,
   never overwritten.** `ipc.ps1` overwrites it with a warning a person reads;
   nothing reads a warning here, and silently dropping a command the caller
   believes was sent is the worse failure. But adding to it is worse still. The
   plugin reads the whole file and *then* deletes it, so a line written in
   between is deleted unread **while the file still vanishes** — and the file
   vanishing is this server's only signal for "consumed", so the send would
   report `consumed: true` and hand back the *earlier* command's `out.txt` delta
   as this command's reply. Nothing downstream can tell that from a real answer,
   which is why a warning on the reply was not enough: it would leave the wrong
   reply in the envelope. So the pending command is waited out, `out.txt` is
   allowed to settle, and this command is then written fresh into a file the
   plugin cannot already have opened. `pending_before: true` reports that it
   happened and the success `detail` says so; it costs about 0.6 s, and only
   when something was pending. A pending file nothing ever consumes is
   `not_consumed` with `wrote_bytes: 0` — writing after a timed-out wait would
   be the `queue=true` behaviour the caller did not ask for. With the game
   **closed** and `queue=true` it still appends, because nothing can be
   mid-read of a file the game is not running to read.

   That makes two waits in one call, so `timeout_s` is **split** between them
   (half each, and this command's own wait is never shorter than its half)
   rather than spent first-come. Clearing a queued `citrace collect` can take
   seconds of `out.txt` settling; when that came out of the same deadline, the
   command was written with the budget already gone and refused `not_consumed`
   on the first poll — a wait of ~0 s reported as the caller's whole `timeout_s`,
   with the "never loaded, or a different copy" pair attached to a channel the
   same call had just watched the plugin read. `elapsed_s` and `pending_before`
   report when a call made both waits, and the refusals quote the wait that
   actually happened.
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
control, and `hs_wait_ready` is the one tool that runs it — see `hs_selfcheck`
below for why that control does not also live in the self-check.

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

## Character select

After `hs_launch` the game sits at its main menu, and most ForgePact gameplay
commands act only once a character is loaded. Getting from one to the other --
main menu -> Play local -> save slot -> Play -- was the one step a human had to
take. **It was measured on 2026-09-21, and it can be taken by injected input.**

The measurement, its controls and every reply are in
[`ForgePact/docs/character-select-research.md`](../../ForgePact/docs/character-select-research.md).
Its `## Decision` section is the record, and it now reads:

```
finding: a-sendinput, a-postmessage, d
shipRoute: mcp-only
```

`hs_input` driving `send_input` took a freshly launched game from its main menu
to a loaded character in `Town_01_rm`, proven by a live `Player_obj` instance,
with no human hand. The posted-message route reaches `keyboard_check` but not
`keyboard_check_direct`; the engine's own `keyboard_key_press` reaches both and
needs no foreground, but is keys only, and keyboard navigation is **not
observed** at this menu. `event_perform` on the menu's own buttons is **not
observed** for `UI_Button_obj` and the seven events tried, with its enumeration
control passing. The warm-script route is **unmeasured** -- its positive
control raised, so nothing it reported could be told from a blind instrument.

**Branch M shipped: `hs_select_character`, over `hs_input` and IPC only.**
Three other shapes were on the table and none of them did:

- **P (a player-visible ForgePact change)** -- a new `kPlayerCommands` verb
  and a release. The owner declined it (`shipRoute: mcp-only`): the mechanism
  already works without touching the plugin, and a player-visible change is
  not worth taking on for this. (A later workorder did add one read-only
  player command, `menulayout`, for a different reason: so the clicks land
  where the game says the buttons are instead of at measured fractions. See
  "Where to click" below.)
- **R (shipping the research build)** -- `menuprobe`'s `event`/`script`
  routes change gameplay by design (a real event performed, a real script
  called) and the research docs say never to ship that build to a player.
- **N (nothing works)** -- ruled out by the measurement itself: `a-sendinput`
  drove the whole path to a loaded character.

### The click had to be held, and now it is (fixed 2026-09-21)

`hs_input`'s `click` action used to emit the button-down and the button-up
back to back with nothing between them. Both landed inside a single frame,
and at 144 fps the game's sample loop never observed a frame with the button
held -- so the click moved the cursor, lit the button underneath it, reported
`complete: true`, and activated nothing. The identical click with **120 ms
between the two records** changed the room every time
(`ForgePact/docs/character-select-research.md` C-1.10).

**Fixed 2026-09-21.** `click` now takes `hold_ms` (0–10000, default
`DEFAULT_CLICK_HOLD_MS = 120` -- the measured value) the same way `key`
already did, and sleeps between the button-down and the button-up on both
routes. `hold_ms: 0` still sends move/button-down/button-up back to back with
no sleep -- the pre-fix shape, kept reachable on purpose as the baseline a
caller can still ask for. `key`'s own default, 60 ms, was measured for a held
*key* (C-1.7); it was never re-measured for a *button*, so `click` does not
reuse it. This was an instrument that reported armed and did nothing, found
by measurement rather than by review -- see
[`docs/agents/prove-the-instrument.md`](../agents/prove-the-instrument.md).

### `orbpickup stat` proves a character is loaded -- while `orbpickup` is on

An earlier version of this section said the field answers regardless of that
state. **That was wrong**, and a live read falsified it: with `orbpickup`
never turned on, `orbpickup stat` replies `globe objs=0 ... player via (not
tried)`, in a town with a `Player_obj` provably live. The static reason is in
`ModuleMain.cpp`: `g_OrbPlayerHow` is written only inside `FrameCallback`'s
`if (g_OrbPickupRadius.load())` branch, which runs only while `orbpickup` is
on -- so `(not tried)` and `globe objs=0` both mean "the mod has never been on
in this process", not "the resolver ran and found nothing".

`hs_select_character` is the fix: it arms `orbpickup` itself, reads the field
while armed (`none` at the menu is the negative control -- the resolver ran
and found no player; a route is the proof once a character loads), and
restores `orbpickup` to off only if its own pre-arm read showed the mod was
never on. See `docs/agents/prove-the-instrument.md` for the general shape --
a field that answers only under a precondition nobody arms is a blind
instrument, not evidence the mechanism does not exist.

The on state was measured at the live gate (2026-09-21, player build
`24020eac`, Verification row L1): with `orbpickup` armed, the reading was
`player via none` at the main menu, after `Play local` and on the save-slot
screen, then `player via GetMyPlayer` on the first read after `Play`. Every
one of those reads also said `globe objs=2`, the menu's included, so the globe
count is no sign of where the game is.

### Where to click: ForgePact's `menulayout` listing

`hs_select_character` first clicked three client fractions measured by the
research session: `Play local`, slot 1 and `Play`, at 16:9 only. A game patch
or another layout could move a button and the tool would still click the old
spot. It now clicks where the running game says each button is.

ForgePact has a read-only player command, `menulayout`
(`ForgePact/docs/menu-layout-research.md`, noted in its
`release-notes-v1.4.5.md`). It lists every live instance of its candidate
menu objects, and the UI children they reach. Each row gives the object name,
instance id, on-screen text, visibility, and a `win=` point in **window
(client) coordinates**. The plugin computes that point from the game's own GUI
and window sizes. The header names the room and the `window=` size the points
were computed for. `tools/hs_drive_mcp/layout.py` parses one reply. The
plugin lists and the hub picks, using the rules phase 0 measured on
2026-09-21 (that doc's `## Decision`):

| Screen | Row clicked | Rule |
|---|---|---|
| main menu | `UI_Button_obj` | `visible=1`, text exactly `Play local`, exactly one such row |
| `Chose_rm` | `Choose_Parent_obj` | the `slot`-th of the `visible=1` rows, sorted by `win` y then `win` x. This is row-major: slot 2 is the card right of slot 1 on the same row. The game's own `slot` variable agreed with this order on all 24 page-1 cards. The screen also lists a hidden duplicate at every card's point, which is why `visible=1` is required. |
| character panel | `UI_Button_obj` | `visible=1`, text exactly `Play` (not `Play local`; case-sensitive), exactly one such row. The row is not listed until a card has been clicked. |

Every click's `x`,`y` is the chosen row's `win` field, copied as is, with no
arithmetic in the hub. `layout_trail` records the row each click used. Every
listing check — the main menu's included — re-measures the client size at
that same read and compares it against the listing's `window=`. `hs_launch`
reports `plugin_ready` before the game window necessarily reaches its
configured size, so a disagreement alone is "not settled yet": it keeps
polling (0.5 s, up to 30 reads) instead of refusing at once, exactly the way
the tool already polled after each click for the next screen's button. Only
a budget that runs out on a disagreement refuses `window_size_mismatch`. A
button that is never listed within the budget refuses `button_not_found` and
quotes the listing. Fewer cards than `slot` on two reads in a row refuses
`slot_not_listed`. A plugin without the command refuses
`layout_command_missing`. No path clicks a guessed point. The `orbpickup
stat` proof below is unchanged, and `none` at the menu is still its negative
control.

The main-menu point is proven by a click: `Play local` listed at `win=336,534`
on a 1920x1080 windowed client, the point C-1.15 measured by hand, and
clicking it reached `Chose_rm`. The slot-1 card was also clicked in phase 0
and opened the panel. `Play`'s listed point had not been clicked by the
listing when this was written. The live gate (Verification `M-L2`) is its
first test, and `M-L2b` is slot 2's.

### Calling `hs_select_character`

```json
{"slot": 1, "timeout_s": 60}
```

Call it any time after `hs_launch` reports `phase: plugin_ready` and before
anything that needs a loaded character. It clicks `Play local`, save slot
`slot` (1-based, row-major on page 1) and `Play` itself. Each is a held
`send_input` click at the point `menulayout` lists (above), and before each
click this tool takes focus through the escalation chain in "What is
deliberately not here" — `hs_input` never does this on its own. `focus_trail`
names which step took, per click, in click order. It then polls
`orbpickup stat` until a resolver route appears or `timeout_s` runs out.
`phase` moves through `main_menu`, `local`, `slot` and
`play` as each screen is reached; `character_loaded` is the only outcome
that proves a load; `proof` and `proof_trail` carry the `orbpickup stat`
reply that decided it, one line per screen. `proof_ambiguous` means the
save-slot screen already showed a resolver route before `Play` was clicked
-- a live `Player_obj` on the character panel would make the proof
unspecific to a *loaded* character, so the tool stops rather than claim one;
`timeout` means no route appeared within `timeout_s` of the `Play` click.
The timeout counts from the call's start, so the listing polls come out of
the same budget. A client of any size works if the listing's `window=`
matches it. There is no aspect-ratio rule any more.

At the first live gate (2026-09-21, fraction clicks, Verification row L1),
the tool waited a fixed 3 s after each click. That was enough on every
screen, and the whole call took 17.5 s from the main menu to
`character_loaded`. The fixed wait is gone. Each screen now takes as long as
the game needs to list its next button.

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

This server has since produced that shape twice in its own Python — `hs_selfcheck` computing `healthy` from `fail == 0`, so an all-`skipped` run reported healthy, and `hs_input` reporting a refused `PostMessageW` as delivered. Both are written up in [`docs/agents/prove-the-instrument.md`](../agents/prove-the-instrument.md) § "The same shape outside C++, in a Python MCP server", together with what they have in common: a test double that could not represent the failing return. Read it before adding a check or a tool here.

| Check | Passes when | Skipped when |
| --- | --- | --- |
| `engine_import` | The engine loads and every `ENGINE_SYMBOLS` name resolves | never — a missing source is `fail`, naming the path |
| `process_snapshot` | The snapshot returns rows **including this server's own PID** | non-Windows |
| `eac_service` | `eac_service_status()` is not `unknown` | non-Windows |
| `save_dir` | The live directory exists and holds ≥ 1 `herosiege*.hss` (count in `detail`) | never |
| `backup_roundtrip` | A temp fixture backs up, is damaged, and restores byte-identical through the real `saves` functions | never |
| `screenshot_screen` | A capture of the primary screen holds more than one distinct pixel value | non-Windows, or Pillow not importable |

A check whose code raised is `fail` with the exception name, never `skipped`.
`skipped` always carries its reason in `detail`, because "we did not look" and
"we looked and it broke" must not be confusable. `checks.py` is a registry, which
is how `screenshot_screen` was added with one `register()` call and no change to
any logic there.

**No check writes anywhere but a temporary directory of its own**, and the
plugin's `ping`/`pong` control therefore lives in `hs_wait_ready` alone.
`hs_selfcheck` is annotated `readOnlyHint: true` — the flag a client uses to
auto-approve a tool without prompting — and it is the tool this server's own
instructions say to run *first*, so it is the one most likely to run unattended.
A plugin ping was briefly a check here, and it wrote a `ping` into the live
install's `bp_ipc\cmd.txt` and made the running game execute it; an unconsumed
one was left on disk, so the game ran it at its **next** start. That is a
delayed write into the game directory from a tool nobody would be asked about.
`check_backup_roundtrip` builds its own fixture tree for exactly this reason, so
the principle already existed. `hs_wait_ready` sends the identical ping, is
annotated honestly (`readOnlyHint: false`, "Sends one ping; starts nothing"),
and returns a far richer envelope — including `plugin_consumed_without_pong`,
the verdict the removed check was the only thing reporting correctly.
`tests/test_hs_drive_mcp_server.py::SelfCheckSideEffectTests` pins it: the real
registry runs against a fixture install a patched gate reports as **running**,
and nothing may appear in that install's `bp_ipc\` afterwards.

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

- **A mistyped argument name is silently ignored, and you get the default
  instead.** `hs_ipc_tail(n=5)` returns the default 40 lines rather than
  refusing, because the parameter is called `lines`. Measured 2026-09-20 during
  the live run and then traced: this is the MCP SDK, not this server.
  `mcp.server.mcpserver.utilities.func_metadata.ArgModelBase` sets
  `ConfigDict(arbitrary_types_allowed=True)` and never sets `extra`, so
  pydantic's default `extra='ignore'` applies; `validate_arguments` drops the
  unknown key at `model_validate`, and `model_dump_one_level` enumerates
  declared fields only. Every tool here registers through `@server.tool(...)`
  → `Tool.from_function` → `func_metadata`, so all twelve behave identically
  and **no code in `tools/hs_drive_mcp/` can see the dropped key** — by the
  time a tool body runs, the evidence is gone. Reproduced on a toy signature
  mirroring `hs_ipc_tail`: `{"lines": 5}` → `lines=5`, `{"n": 5}` → `lines=40`,
  `{"lines": 5, "n": 99}` → `lines=5`, `{"LINES": 5}` → `lines=40` (it is
  case-sensitive too). The published input schemas carry no
  `additionalProperties: false`, so a client is not told either — arguably the
  real gap, and not reachable from here.

  Not fixable at the tool layer, each measured rather than assumed: `**kwargs`
  does not act as a catch-all (`func_metadata` turns `**rest` into a
  *required* field, so every ordinary call then fails validation);
  `func_metadata(func, skip_names, structured_output)` takes no `extra` or
  config parameter; and `Tool.from_function(...)` takes no input-schema
  parameter, so `additionalProperties: false` cannot be published. The one
  hook that exists is `MCPServer.middleware`, which can refuse a message
  before any handler sees it — but the SDK's own docstring calls it
  "Provisional - the signature may change in a 2.x minor release", and it
  would mean wrapping the whole request path to catch a typo. If this is ever
  enforced, that middleware is the single place to do it; **not** twelve tool
  bodies, none of which can. Until then: check the parameter names in
  `## Tools` above, and treat a suspiciously default-looking answer as a
  possible misspelling.

- **`hs_select_character` reaches page 1 of the save-slot screen only, needs
  a ForgePact build with `menulayout`, and runs windowed or borderless.** It
  clicks where ForgePact's `menulayout` listing says each button is, so a
  slot on another page refuses `slot_not_listed`, and an older plugin refuses
  `layout_command_missing`. Nothing falls back to a guessed point. The slot
  and `Play` rules are phase 0's measurement of one game build (2026-09-21).
  A patch that renames `Choose_Parent_obj` or relabels `Play` shows up as
  `button_not_found` quoting the listing, not as a wrong click. Exclusive
  fullscreen is minimized by Windows when the game loses focus (see the
  capture caveat below), so run windowed or borderless. The proof of a
  load is the plugin's own player resolver -- `orbpickup stat`'s `player via`
  field, armed and read by the tool itself, the same resolver every other
  player-gated feature in the plugin already gates on -- not a screenshot or
  a room read. See "Character select" above.
- **Exclusive fullscreen captures fine, but only while the game holds the
  foreground.** Measured on 2026-09-20 (see the Verification table): in
  windowed, borderless and exclusive fullscreen alike, both `grab_bbox` and
  `grab_window` returned real, non-flat game frames — the anticipated flat
  capture never happened in any mode. What does happen in exclusive fullscreen
  is that Windows minimizes the game the moment it loses focus, so every
  capture taken after you switch to the agent's window refuses with
  `window_minimized` rather than photographing the desktop. That refusal is the
  window resolver working, not a capture failure, and it makes exclusive
  fullscreen unusable for the ordinary agent loop, where the human is reading a
  transcript in another window. **Run the game windowed or borderless while
  driving it**; keep exclusive fullscreen for captures timed to fire while the
  game is in front. A flat result, if one ever occurs, is still reported as
  such (`warning: "image_is_flat"`) rather than passed off as a picture.
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
| A3/A4/A7 | Tool surface over stdio, self-check, status, `healthy` semantics | `py -3 -m unittest tests.test_hs_drive_mcp_server -v` | `OK`, 17 tests, no skips — all twelve tools listed, `screenshot_screen` `pass`, `ipc_ping` `skipped` ("the game is not running") — 2026-09-20. **Pre-change row:** measured against the round-0 tree, whose `hs_selfcheck` still carried `ipc_ping`; the registry is six checks since PD2 removed it, so read this row as evidence from the pre-change tree. |
| A5 | Engine pin, inert import, missing-source refusal | `py -3 -m unittest tests.test_hs_drive_mcp_engine_bridge -v` | `OK`, 8 tests, no skips — 2026-09-20 |
| A6 | No stdout, no listener, no shell | `Select-String -Path tools/hs_drive_mcp/*.py -Pattern 'shell=True\|os\.system\(\|socket\.\|\.bind\(\|HTTPServer\|uvicorn\|streamable\|^\s*print\('` | no matches — 2026-09-20 |
| B1–B10 | Save backup and restore, the wiped-directory recovery case and its negative control | `py -3 -m unittest tests.test_hs_drive_mcp_saves -v` | `OK`, 36 tests, no skips — 2026-09-20 |
| C6 | Release boundary, including the mechanical no-deletion check | `py -3 -m unittest tests.test_hs_drive_mcp_release_boundary -v` | `OK`, 7 tests, no skips — 2026-09-20 |
| C7 | Whole root suite, with the first six tools | `py -3 -m unittest discover -s tests` | `Ran 741 tests`, `OK (skipped=9)` — all nine skips pre-existing in other suites — 2026-09-20 (superseded by the F3 row below) |
| C7 | This change touches no submodule | `git -C ForgePact status --porcelain`, `git -C HS-Offline-Launcher status --porcelain` | both printed nothing — 2026-09-20. (An unrelated ` M HS-Offline-Tracker` gitlink drift predates this work; `git diff --stat 589246f HEAD` touches no submodule.) |
| — | Self-check on this machine, first five checks | `hs_selfcheck` over stdio | all five `pass` (137 files, 48 characters in the live dir; snapshot sees own PID; EAC `stopped`) — 2026-09-20 |
| — | Self-check on this machine, all seven (pre-change) | `hs_selfcheck` over stdio, in `tests.test_hs_drive_mcp_server` | six `pass` including `screenshot_screen`; `ipc_ping` `skipped` naming "the game is not running", with no game up. `summary.healthy` therefore rests on three proven positive controls — 2026-09-20. **Pre-change row:** measured against the round-0 tree, whose `hs_selfcheck` still carried `ipc_ping`; the registry is six checks since PD2 removed it, so read this row as evidence from the pre-change tree. |
| C1–C6 | Launch through ForgePact's engine, the three readiness phases, `WM_CLOSE`, and `TerminateProcess`'s three conditions with its negative control | `py -3 -m unittest tests.test_hs_drive_mcp_launch -v` | `OK`, 29 tests, no skips — 2026-09-20 |
| D1–D6 | The IPC channel: ASCII/CRLF/no BOM, append-not-overwrite, byte-delta reply, `not_consumed`, the gate, `bp_ipc` resolution, `tail` | `py -3 -m unittest tests.test_hs_drive_mcp_ipc -v` | `OK`, 27 tests, no skips — runs in full on CI too, since it needs neither Windows nor a submodule — 2026-09-20 |
| E1–E3 | Window resolution and its three refusals, both capture methods, the flat-image warning with a negative control, the downscaled transport copy, the image block | `py -3 -m unittest tests.test_hs_drive_mcp_screenshot -v` | `OK`, 33 tests, no skips — 2026-09-20 |
| — | Real screen capture on this machine (positive control) | `PositiveControlTests` in that suite, and `hs_selfcheck`'s `screenshot_screen` | 2560×1440, more than 4 distinct pixel values, `pass` — 2026-09-20 |
| F3 | Whole root suite, after the six new tools | `py -3 -m unittest discover -s tests` | `Ran 831 tests`, `OK (skipped=9)` — the same nine pre-existing skips in other suites; the 90 added here skip nowhere on this machine — 2026-09-20 |
| F3 | This change touches no submodule | `git -C ForgePact status --porcelain`, `git -C HS-Offline-Launcher status --porcelain` | both printed nothing — 2026-09-20 |
| — | The six new tools over a real stdio session, with the game **closed** (fixture save/backup/screenshot directories) | one-off client script; the same argv `.mcp.json` carries | `list_tools` returned all twelve. `hs_selfcheck`: six `pass`, `ipc_ping` `skipped` ("the game is not running"), `healthy: true` on three proven controls. `hs_ipc_tail`: `exists: true`, `bytes_total: 34256` against the real `bp_ipc\out.txt`. `hs_command ["ping"]`: refused `game_not_running`. `hs_screenshot("screen")`: `text` + `image` blocks, 2560×1440 file, `transport_width: 1280`, not flat. `hs_stop_game`: `exited: true`, `pids_closed: []`, `forced: false` — 2026-09-20. **Pre-change row:** measured against the round-0 tree, whose `hs_selfcheck` still carried `ipc_ping`; the registry is six checks since PD2 removed it, so read this row as evidence from the pre-change tree. |
| F4 | Live sequence: `hs_selfcheck` → `hs_saves_backup` → `hs_launch` → `hs_screenshot` → `hs_command ping` → `hs_stop_game` → `hs_saves_inspect` → `hs_saves_restore` | owner-run, over a real MCP stdio session against `py -3 -m tools.hs_drive_mcp` at the repo root | **pass — 2026-09-20**, against Hero Siege 7.0.13.0 with BloodPact v1.4.4 / YYTK 4.0.1. `hs_selfcheck`: six `pass`, `ipc_ping` `skipped` ("the game is not running"), `healthy: true`. `hs_saves_backup("pre-test")`: `20260920T180727Z_pre-test`, 137 files, 1289192 bytes. `hs_launch()`: `phase: plugin_ready`, `ready: true`, pid 45852, `elapsed_s: 19.342`, `launch.phase: verified`, `plugin_reply` ending `pong (YYTK 4.0.1)`. `hs_command(["ping"])`: `consumed: true`, reply `pong (YYTK 4.0.1)`, `elapsed_s: 0.874`, `pending_before` and `pending_left` both false, `out.txt` 34863 → 34930 bytes. `hs_stop_game()`: `exited: true`, `pids_closed: [45852]`, `forced: false`, `windows_found: 1`, `elapsed_s: 1.051`. `hs_saves_inspect`: `changed`, `added` and `missing` all empty — the session never loaded a character, so the game rewrote nothing on exit. `hs_saves_restore`: `restored: 137`, equal to the manifest's count, with its own `pre_restore_backup_id: 20260920T181317Z_pre-restore` and `moved_extras: 0`; `hs_saves_inspect` afterwards clean. Since the restored bytes were identical, the write itself was confirmed by mtime: `controls2.ini` went from the live copy's 2026-09-20 20:07:39 back to the backup's 2026-09-19 15:14:21. Measured against the round-0 tree, whose `hs_selfcheck` still carried `ipc_ping`; the registry is six checks since PD2 removed it, so read this row as evidence from the pre-change tree. |
| F4 | Capture in `windowed` — `hs_screenshot("game")` with both `capture_method`s | owner-run, display mode set from the game's own Options menu | **pass — 2026-09-20**, a 1920×1080 client on a 2560×1440 screen. `grab_bbox`: 1936×1119, the frame with its title bar, `warning` empty. `grab_window`: 1920×1080, the client area, `warning` empty. Both show the main menu, confirmed by eye. Files `...180805854313Z_asis-bbox.png` and `...180806142006Z_asis-window.png` |
| F4 | Capture in `borderless` — the same two calls | owner-run | **pass — 2026-09-20** (the game spells it "Windowed fullscreen"). Both methods returned 2560×1440 with `warning` empty, showing the Video options page itself. Files `...180946903053Z_borderless-bbox.png` and `...180947123396Z_borderless-window.png` |
| F4 | Capture in `exclusive_fullscreen` — the same two calls | owner-run | **pass, with one condition — 2026-09-20.** Neither method is flat: with the game in the foreground both returned 2560×1440 frames of the real main menu, and two rounds 15 s apart show different animation frames, so these are live captures rather than a cached surface. Files `...181151420400Z_fs-fg-bbox.png`, `...181151766370Z_fs-fg-window.png` and `...181206744076Z_fs-fg-bbox.png`. The condition: the first attempt, made right after the human switched back to the agent's window, refused `window_minimized` under **both** methods — Windows minimizes an exclusive-fullscreen window when it loses focus, and the `screen` positive control taken in the same call proved the point by capturing the desktop. Captures in this mode must therefore be timed to fire while the game is in front; see Known limitations |
| G1 | Baseline before the "report what it did" change, on its round base `28b4c5c` | `py -3 -m unittest discover -s tests` | `Ran 831 tests in 137.923s`, `OK (skipped=9)` — 2026-09-20 |
| G2 | The red run: every target for findings 1, 2, 3 and 6 against the **unchanged** code, with every baseline still `ok` | the three suites below, before the implementation | `FAILED (failures=3)`, `(failures=3)` and `(failures=1)` — `'plugin_ready' != 'plugin_consumed_without_pong'`; `'not observed' not found in …` — the old detail concluded the plugin was absent instead of unobserved; `'prev reply' unexpectedly found in 'prev reply\r\n'` (the consumption race, reproduced deterministically); `6 != 0` for `wrote_bytes`; `Lists differ: ['cmd.txt'] != []` for the self-check's write into a fixture install's `bp_ipc\` — 2026-09-20 |
| G3 | `ready` is the control firing: a consumed ping with no `pong` is `plugin_consumed_without_pong, ready: false`, for both `hs_launch` and `hs_wait_ready`, and an unconsumed one reports "not observed" naming both installs | `py -3 -m unittest tests.test_hs_drive_mcp_launch -v` | `OK`, 31 tests, no skips — 2026-09-20 |
| G4 | A pending `cmd.txt` is waited out, `out.txt` settled, and this command written fresh; a pending one nobody consumes is `not_consumed` with `wrote_bytes: 0`; `queue=true` against a closed game still appends | `py -3 -m unittest tests.test_hs_drive_mcp_ipc -v` | `OK`, 31 tests, no skips — runs on CI too — 2026-09-20 |
| G5 | `hs_selfcheck` is read-only against a *running* game, and the read-only set over the wire is exactly the documented five | `py -3 -m unittest tests.test_hs_drive_mcp_server -v` | `OK`, 18 tests, no skips — the whole real registry ran with the gate reporting `running` and left nothing in the fixture `bp_ipc\` — 2026-09-20 |
| G6 | Whole root suite after the change | `py -3 -m unittest discover -s tests` | `Ran 838 tests`, `OK (skipped=9)` — the same nine pre-existing skips; the seven added here skip nowhere on this machine — 2026-09-20 |
| H1 | The red run for the budget fix: a queued command cleared first must not leave the caller's own command 0 s, and a channel watched being read must not be reported unobserved | the three new tests against the pre-fix accounting | all three failed as intended — `False is not true : clearing the earlier command spent this command's own wait …` with `elapsed_s: 0.646` against `timeout_s=0.3`, `wrote_bytes: 6`; `'timeout_waiting_for_plugin' != 'plugin_ready'` for `hs_wait_ready` after a queued command; `'observed consuming an earlier command' not found in "… is not observed … a different copy …"` — 2026-09-20 |
| H2 | `timeout_s` is split, so a `not_consumed` refusal always reports a wait that happened | `py -3 -m unittest tests.test_hs_drive_mcp_ipc -v` | `OK`, 33 tests, no skips — runs on CI too — 2026-09-20 |
| H3 | `hs_wait_ready` after `hs_command(queue=true)` reaches `plugin_ready`, and a live channel that ignored the ping is not reported as a missing plugin | `py -3 -m unittest tests.test_hs_drive_mcp_launch -v` | `OK`, 33 tests, no skips — 2026-09-20 |
| H4 | Negative control for H2/H3: the same tests with `ipc.PENDING_WAIT_SHARE` patched to `1.0`, which is exactly the pre-fix accounting | one-off script, `unittest` loader + `patch.object` | 2 of 3 failed, and the refusal then read "did not take this command within the **0.0 s** that were this command's own wait (of a 0.3 s budget)" — the tests measure the split, not something else — 2026-09-20 |
| H5 | Whole root suite after the budget fix | `py -3 -m unittest discover -s tests` | `Ran 842 tests in 139.390s`, `OK (skipped=9)` — the same nine pre-existing skips; the four added here skip nowhere on this machine — 2026-09-20 |
| C1 | `hs-drive` connects in a fresh session | `/mcp` in a new Claude Code session at the repo root | **pass**, owner-run 2026-09-20: listed as connected. The working-directory assumption holds — `args: ["-3", "-m", "tools.hs_drive_mcp"]` resolves as a namespace package from the repo root, so no absolute-path fallback and no `os.chdir` were needed. Note the session must *start* at the repo root: a session already running when this entry was added does not pick it up, and shows the server as absent rather than failed. |
| — | Unknown arguments are dropped by the SDK, not by this server (Known limitations) | `py -3 -m unittest tests.test_hs_drive_mcp_server -v` | `OK`, 21 tests, no skips. `UnknownArgumentTests` pins it on a toy signature mirroring `hs_ipc_tail`: `{"n": 5}` → `lines=40`, `{"LINES": 5}` → `lines=40`, no `additionalProperties` in the published schema. The pin is inverted on purpose — if a later `mcp` release starts refusing unknown arguments it **fails**, and that failure is the signal to delete the limitation. Whole suite: `Ran 845 tests in 147.299s`, `OK (skipped=9)` — 2026-09-20 |

The rows below belong to `hs-drive-mcp-charselect`, the workorder that added
`hs_input`. Its ids restart at A1; they are not the A-rows above.

| # | Check | Command | Result |
| --- | --- | --- | --- |
| A1 (charselect) | `hs_input`: the baseline refusals with nothing injected, both routes; scan-code down/up with the extended bit; the absolute-mouse conversion; the foreground permission re-proved before every send; the posted-message `lParam` bits; a post the system refuses, which stops the sequence and names the message and error code; every limit | `py -3 -m unittest tests.test_hs_drive_mcp_input -v` | `OK`, 41 tests, no skips — 2026-09-20. Every Win32 call goes through the module's `WIN32` table, which the fixture replaces wholesale, so the assertions read the `INPUT` records that would have been injected rather than a return code |
| A7 (charselect) | Thirteen tools over the real stdio transport, `hs_input` among them with `readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: false` | `py -3 -m unittest tests.test_hs_drive_mcp_server -v` | `OK`, 23 tests, no skips — 2026-09-20. The twelve-tool assertion is kept under its old name as the baseline: a later workorder registering its own tool must not quietly drop one |
| A8 (charselect) | Release boundary still holds with `input.py` present: it imports no MCP SDK, and the no-stdout/no-listener pattern still has no match | `py -3 -m unittest tests.test_hs_drive_mcp_release_boundary -v` | `OK`, 7 tests — 2026-09-20. One skip, `test_no_shipped_build_input_mentions_the_server`, because `HS-Offline-Launcher/` is not checked out in this worktree; it is environmental and predates this change |
| F1 (charselect) | Whole root suite after `hs_input` | `py -3 -m unittest discover -s tests` | `Ran 888 tests in 154.174s`, `OK (skipped=10)` — 2026-09-20. All ten skips are environmental (three uninitialized submodules, `hs-game-sdk/data` gitignored, one non-Windows branch); the 43 tests added here skip nowhere |
| — (charselect) | `hs_input` **called** over a real stdio session, game closed — registered is not the same as callable | one-off client, the same argv `.mcp.json` carries | 2026-09-20: `list_tools` returned 13 tools including `hs_input`, schema properties `actions`, `require_foreground`, `route`. `{"actions":[{"type":"key","vk":16,"hold_ms":100}]}` → a refusal envelope, `reason: game_not_running`, `is_error: false`. `{"actions":[{"type":"key","vk":0}]}` → `reason: invalid_input`, detail `action 0 vk must be between 1 and 254, not 0`. `route: "sendinput"` → `is_error: true`, an SDK `Literal` validation error before any code here ran (see the note under the token table) |
| B (charselect) | The plugin half: the `menuprobe` contract, the research document, and both builds | `py -m unittest discover -s tests` and `plugin_build\build.bat dev` / `release`, in `ForgePact/` | `Ran 609 tests in 25.626s`, `OK (skipped=2)` — 2026-09-20, after the three review amendments (the same-instrument enumeration control in the research document's steps 6 and 13, `MpWhere`'s `<destroyed>` marker, and both comments saying that a command runs inside `PollCommands()` on the frame thread rather than claiming it does not). Both skips are `HS-Offline-Launcher/` not being checked out. Both builds exit 0; `BloodPactPlugin_rel.dll` contains `menuprobe` and not `command unavailable in player build`, and `BloodPactPlugin_ship.dll` the reverse |
| C (charselect) | **The live session** — the four candidates measured against the real game, each behind its own positive control | owner-run, `ForgePact/docs/character-select-research.md` § Live procedure | **not run — 2026-09-20.** Deferred to a later session by the owner. Every row of that document's § Results is empty, and its § Decision reads `finding: pending` / `shipRoute: pending`. Nothing here has measured whether injected input reaches this game |

The rows below belong to `hs-drive-mcp-charselect-ship`, the workorder that
shipped `hs_select_character`. Its ids restart at I1; they are not the
A/B/C rows above, which belong to `hs-drive-mcp-charselect` and are its own
dated record.

| # | Check | Command | Result |
| --- | --- | --- | --- |
| I1–I3 (ship) | `hs_input`'s `click` holds the button: `hold_ms` 0–10000 = 120, a sleep between down and up on both routes, the ordered move → down → sleep → up pin, `hold_ms: 0` still reachable with no sleep, a refused button-down followed by neither a sleep nor an up, `key`'s own hold unaffected | `py -3 -m unittest tests.test_hs_drive_mcp_input -v` | `OK`, 49 tests, no skips — 2026-09-21. The new ordered assertion ran red against the unmodified `_do_pointer` first (2 failures, 1 error: no `DEFAULT_CLICK_HOLD_MS`, `['move','down','up'] != ['move','down','sleep','up']`) |
| S1–S7 (ship) | `hs_select_character`: the S2 baseline (game never loads → `timeout` having sent exactly the scripted commands), the S3 target (a route right after the third click → `character_loaded`, both resolver routes), every refusal, both branches of the restore rule, the `proof_ambiguous` stop before `Play`, fourteen tools registered with `hs_select_character`'s hints, and the docstring/hub-doc phase and refusal-token coverage | `py -3 -m unittest tests.test_hs_drive_mcp_charselect tests.test_hs_drive_mcp_server tests.test_hs_drive_mcp_release_boundary -v` | `OK`, 16 + 27 + 7 tests, no skips (one skip in the release-boundary suite, `HS-Offline-Launcher/` not checked out) — 2026-09-21. `results.REASONS` gained exactly three tokens: the slot/aspect-ratio refusal (removed by M1 below), `proof_not_armed`, `character_already_loaded`; `research_build_required` still absent |
| S8 (ship) | Replies are read the way the plugin writes them: `ipc.send`'s `reply` is the handler's line framed by `---- running command file ----` / `---- done ----`, so the arm acknowledgement and the `orbpickup stat` line are picked out by prefix (`_reply_line`) rather than tested against the whole reply. The test double now frames every reply, and `LIVE_ARM_REPLY` is the exact reply L-1's first attempt refused on | `py -3 -m unittest tests.test_hs_drive_mcp_charselect tests.test_hs_drive_mcp_server tests.test_hs_drive_mcp_release_boundary -v` | `OK`, 25 + 27 + 7 tests (one release-boundary skip, as above) — 2026-09-21. Negative control: the same tests against the pre-fix `charselect.py` give `FAILED (failures=11, errors=1)` |
| L1 (ship) | **The live gate** — `hs_select_character` through a fresh MCP session against the real modded install, with the server-identity controls first | owner-run, per the workorder's Group L step | **Attempt 1, 2026-09-21 — failed, tool defect (fixed in S8).** Server identity proven: `hs_input` `hold_ms: 99999` → `invalid_input` naming `hold_ms`; `hs_select_character(slot=99)` → `game_not_running` with the game closed (the tool checks for a running game before the slot) and the then-current slot refusal (since removed, M1) once it was running. DLL `24020eac` (a research build, `9dcd5fb1`, was installed and was swapped out for the run and back afterwards); `hs_selfcheck` six `pass`; backup `20260921T100906Z_pre-charselect-ship`; `hs_launch` `plugin_ready` in 14.9 s; `hs_select_character(1)` → `proof_not_armed`, `actions_sent: 0`, `orbpickup: restored_off`, because the framed arm reply failed a whole-reply `startswith`; `hs_stop_game` `exited: true, forced: false`; `hs_saves_inspect` `changed: []`, `missing: []`. **Attempt 2, 2026-09-21 — pass** (server restarted with `3b701d2`): server identity — `hs_input` `hold_ms: 99999` → `invalid_input` naming `hold_ms`, `hs_select_character(slot=99)` → `game_not_running` (closed) then the same slot refusal (running, before any input); DLL `24020eac` (swapped in over `9dcd5fb1` and back afterwards); `hs_selfcheck` six `pass`; backup `20260921T101547Z_pre-charselect-ship-2`, 137 files; `hs_launch` `plugin_ready` in 15.8 s; `hs_select_character(1)` → `phase: character_loaded`, `proof` `… | player via GetMyPlayer`, `proof_trail` `main_menu` / `local` / `slot` each `player via none` with `orbpickup` on (the negative control: the on-state menu reading, previously `not observed`) and `play` `player via GetMyPlayer`; four screenshots; `orbpickup: restored_off`; `actions_sent: 3`; `elapsed_s: 17.538`. Settle: every screen waited the then-fixed 3 s settle and the route answered on the first read after `Play`, so 3 s was enough for each screen; nothing shorter was tried. Every `orbpickup stat` line read `globe objs=2`, the menu's included. `hs_screenshot` (`grab_window`) shows the slot-1 character in the Town of Inoya; `hs_stop_game` `exited: true, forced: false`; `hs_saves_inspect` before the restore `changed: [herosiege0.hss, shop.ini]` (the game's own writes on exit), after it `changed: []`, `added: []`, `missing: []`, and the live directory hash-identical to an out-of-band copy taken before either attempt. |

The rows below belong to `hs-drive-mcp-charselect-buttons`, the workorder
that replaced the measured click fractions with ForgePact's `menulayout`
listing. Its ids start at M1.

| # | Check | Command | Result |
| --- | --- | --- | --- |
| M-P0 | **Phase 0**: the live `menulayout` listing of the main menu, `Chose_rm` and the character panel, with the dev build (`BloodPactPlugin_rel.dll` from ForgePact `f9889a6`) | owner-authorized, run by a live agent, per `ForgePact/docs/menu-layout-research.md` § Live procedure | **pass — 2026-09-21** (that doc's § Results, P0-1 to P0-9). Positive control: `Play local` listed at `win=336,534` on a 1920x1080 windowed client (C-1.15's hand-measured point), and one held click there reached `Chose_rm`. Slot 1 listed at `win=177,174`, and a click there opened the character panel. `PLAY` listed only after that click, at `win=584,345`. Decision: `slotObject: Choose_Parent_obj`, `playObject: UI_Button_obj`, both `point:origin`. Saves `changed: []` before and after restore, and the installed DLL was restored to `22371422…fabc33`. The three framed replies are the hub's fixtures, verbatim (`tests/hs_drive_mcp_menulayout_fixtures.py`). |
| M1 | `layout.py` on the three phase-0 listings: header, rows, `text` to end of line, `<read-failed>` as `None`, `layout_command_missing` for an older plugin or no header, `window_size_mismatch`. The `Play local`, slot and `PLAY` matchers are checked against those listings. Slot 2 is the card right of slot 1 on the same row (`381,174` vs `177,174`), and slot 9 is the card below. The hidden duplicate cards are dropped. The game's `slot` variable agrees with the row-major order. Negative controls: a hidden or look-alike `Play local`, `PLAY` vs `Play`, and two candidates. | `py -3 -m unittest tests.test_hs_drive_mcp_layout -v` | `OK`, 35 tests, no skips — 2026-09-21 |
| M2 | `hs_select_character` from the listing. The fake plugin answers `menulayout` with whichever phase-0 listing the clicks so far have reached. Covered: the S2 baseline, the S3 target with `layout_trail`, every click equal to the chosen row's `win`, slot 2's click at `381,174`, a 1024x768 client whose listing agrees, `window_size_mismatch` and `layout_command_missing` before any click, `button_not_found` on each of the three screens (one quoting the last listing after exactly 30 polls), `slot_not_listed` for `slot=99` and for a page that stays short, and one short read not refused. Proof, restore and `proof_ambiguous` rules are unchanged. | `py -3 -m unittest tests.test_hs_drive_mcp_charselect -v` | `OK`, 35 tests, no skips — 2026-09-21. Negative control: the same 35 tests with the previous (fraction-clicking) `charselect.py` loaded in its place give `FAILED (failures=3, errors=12)` |
| M3 | Tool surface: `slot`'s published schema has `minimum: 1`, and the description names `menulayout` and no fraction, 16:9 or removed token. `REFUSAL_TOKENS` is the new set, each in the docstring and in this doc. The release boundary lists `layout.py`. | `py -3 -m unittest tests.test_hs_drive_mcp_server tests.test_hs_drive_mcp_release_boundary -v` | `OK`, 28 + 7 tests (one release-boundary skip, `HS-Offline-Launcher/` not checked out) — 2026-09-21 |
| M4 | Whole root suite after the change | `py -3 -m unittest discover -s tests` | `Ran 973 tests`, `OK (skipped=10)`. All ten skips are the pre-existing environmental ones. — 2026-09-21 |
| M5 | Resize fix: `WindowSettleTests` — two `resiz` tests (settled by the first listing read; settled mid-poll before the first click), the after-`Play local` mismatch, and the persistent-mismatch test (updated to `LAYOUT_POLL_ATTEMPTS` reads) | `py -3 -m unittest tests.test_hs_drive_mcp_charselect -v` | `OK`, 38 tests, no skips — 2026-09-21. Negative control: the same command against the pre-fix `charselect.py` (`fe9ef17`) on `WindowSettleTests` alone gives `FAILED (failures=2, errors=1)` |
| M6 | Force-focus escalation (`hs-drive-mcp-force-focus`): `tests.test_hs_drive_mcp_input`'s `ForceFocusTests` — the attached retry taking after the plain attempt fails, the input-unlock step taking once attach is skipped, every step failing and naming all three in `detail`/`focus_attempts`, an exception inside the attached step still detaching, `require_foreground=false` ignoring `force_focus`, `focus_via` `already_foreground`/`not_required`, and the tool-aware refusal text — plus `tests.test_hs_drive_mcp_charselect`'s `FocusTrailTests` — every click carrying `force_focus=True`, a three-row `focus_trail` in click order, and a refusal still carrying one | `py -3 -m unittest tests.test_hs_drive_mcp_input tests.test_hs_drive_mcp_charselect -v` | `OK`, 59 + 42 tests, no skips — 2026-09-21. Negative control: `tests.test_hs_drive_mcp_input.ForceFocusTests` against `input.py` at `76a607d` gives `FAILED (errors=8)` (`force_focus` does not exist there); `tests.test_hs_drive_mcp_charselect.FocusTrailTests` against `charselect.py` at `76a607d` gives `FAILED (failures=1, errors=3)` (no `focus_trail`, and `click` never passes `force_focus`). Both files restored afterwards |
| M-L2 | **The live gate**: `hs_select_character(1)` against the player build carrying `menulayout`, in a fresh session, with identity controls (`slot=0` → schema error; `slot=99` → `slot_not_listed` naming 24 cards) | owner-run, per the workorder's L-2 step | **Attempt 1, 2026-09-21 — failed, tool defect (fixed in M5 as far as its unit tests show; the cause below is the leading hypothesis, not confirmed by a live pass).** Player build `d627486c…` (`ForgePact/plugin_build/BloodPactPlugin_ship.dll`, sha256 `d627486c33f54b140d3ebceb611e158153eef1e221bf2f6d57ae4fb3863ec815`). Fresh stdio client of the worktree's server. Closed-game `slot=0` → validation error `greater_than_equal`; `hs_selfcheck` six `pass`; `hs_launch` → `plugin_ready`, then **immediately** `hs_select_character(slot=99)` → `window_size_mismatch`, `actions_sent: 0`, `phase: main_menu`, `elapsed_s: 6.302` — the header read `window=1920x1080` while the client measured `1024x576`, the leading hypothesis being that the tool measured the client once before `plugin_ready`'s window had settled. The listing itself was correct: `Play local` `win=336,534`, `listed=19 absent=none`; `proof_trail` `main_menu` `player via none`. Saves restored clean (`changed: []`, `missing: []`, identical to the out-of-band copy `hs2saves-20260921-pre-menulayout-L2`); DLL restored to `22371422…`. **Attempt 2, 2026-09-21 16:31–16:34 — stopped at the identity control, `foreground_not_game`; not a pass.** Pre-flight: `hs_status` `not_running`, `game_pids: []`, no `Hero_Siege.exe` in `tasklist`. Installed DLL pre-run sha256 `bea8cc00b4aadb16ad22755c9379b686770cbb99a6f668c9525f4ffdb135ec64` (set aside as `BloodPactPlugin.dll.pre-L2a2-bea8cc00`), re-hashed unchanged right before the copy; after the copy the installed file hashed `d627486c33f54b140d3ebceb611e158153eef1e221bf2f6d57ae4fb3863ec815` (`menulayout` present, `menuprobe` absent, plugin source older than the DLL). Out-of-band copy `hs2saves-20260921-pre-menulayout-L2-attempt2` (137 files), then `hs_saves_backup` `20260921T143246Z_pre-menulayout-L2-a2`. Fresh stdio client of the worktree's server at hub `05e031e`. Closed-game `slot=0` → validation error `greater_than_equal`; `hs_selfcheck` six `pass`, 0 skipped. `hs_launch` → `plugin_ready` (`elapsed_s: 15.914`, pid 132112), then **immediately** `hs_select_character(slot=99)` → `foreground_not_game`, `actions_sent: 0`, `phase: local`, `elapsed_s: 6.384`, detail "the foreground window is 853428, not the game's 38733986; one SetForegroundWindow attempt did not take. SendInput goes to whatever is in front, so nothing was sent." The main-menu listing (`window=1920x1080`, `Play local` `win=336,534`, `listed=19 absent=none`) was accepted at the timing that failed attempt 1 — no `window_size_mismatch` — and the refusal came from the `Play local` click, before it was sent, so the `slot_not_listed` positive was never reached. `proof_trail` `main_menu` `player via none`; `layout_trail` empty; `orbpickup: left_on`; screenshot `%LOCALAPPDATA%\HSDriveMcp\screenshots\20260921T143347523844Z_main_menu.png`. `hs_stop_game` `exited: true`, `forced: false`. Inspect `changed: []`, `added: []`, `missing: []`; restored (pre-restore `20260921T143415Z_pre-restore`), inspect clean, and all 137 live files hash-identical to the out-of-band copy. DLL restored to `bea8cc00…` and re-hashed equal. Per the procedure, no retry: slot 1 and slot 2 were not run. Leading hypothesis for the refusal, not verified: the run was driven from a background session, so Windows' foreground lock refused the single `SetForegroundWindow` attempt while another window held the foreground. Note that the detail's hint `route="post_message"` is an `hs_input` option; `hs_select_character` takes no route. **Attempt 3, 2026-09-21 16:48–16:54 — stopped again at the identity control, `foreground_not_game`; not a pass.** The owner stayed off the PC. Pre-flight: `hs_status` `not_running`, no `Hero_Siege.exe` in `tasklist`; installed DLL pre-run sha256 `bea8cc00…ec64` (set aside as `BloodPactPlugin.dll.pre-L2a3-bea8cc00`). The owner copied the player build in by hand; installed sha256 re-checked `d627486c33f54b140d3ebceb611e158153eef1e221bf2f6d57ae4fb3863ec815` and the game still not running. Out-of-band copy `hs2saves-20260921-pre-menulayout-L2-attempt3` (137 files), `hs_saves_backup` `20260921T144915Z_pre-menulayout-L2-a3`, then `20260921T145347Z_pre-L2a3-identity` before the launch. Fresh stdio client of the worktree's server at hub `05e031e`. Closed-game `slot=0` → validation error `greater_than_equal`; `hs_selfcheck` six `pass`, 0 skipped. `hs_launch` → `plugin_ready` (`elapsed_s: 18.287`, pid 126072), then **immediately** `hs_select_character(slot=99)` → `foreground_not_game`, `actions_sent: 0`, `phase: local`, `elapsed_s: 6.257`, detail "the foreground window is 1968114, not the game's 7800362; one SetForegroundWindow attempt did not take." As in attempt 2 the main-menu listing (`window=1920x1080`, `listed=19 absent=none`) was accepted with no `window_size_mismatch`; the refusal came at the `Play local` click before it was sent. `proof_trail` `main_menu` `player via none`; `layout_trail` empty; `orbpickup: left_on`; screenshot `%LOCALAPPDATA%\HSDriveMcp\screenshots\20260921T145411161235Z_main_menu.png`. Measured after the run: window 1968114 belongs to the Claude Code terminal (process `claude`, title `Terminal`) and still held the foreground, so the game launched by a background MCP server never received focus even with nobody at the PC. `hs_stop_game` `exited: true`, `forced: false`. Inspect `changed: []`, `added: []`, `missing: []`; restored (pre-restore `20260921T145427Z_pre-restore`), inspect clean against both backups, all 137 live files hash-identical to the out-of-band copy. No retry; slot 1 and slot 2 were not run. At the end the installed DLL still hashed `d627486c…ec815`; the owner restores `bea8cc00…` from the aside copy. Conclusion: re-running will not pass while the tool's only way to focus the game is one `SetForegroundWindow` call from a process Windows does not let take the foreground; that is a tool/plan question, not a timing one. **Attempt 4, 2026-09-21 16:55–16:57 — driven through the Claude Code session's own `hs-drive` server (the `mcp__hs-drive__*` tools; server pid 132456, not a stdio server started by a driver script); stopped at the identity control, `foreground_not_game` again; not a pass.** The owner stayed off the PC and had installed the player build by hand; installed sha256 verified `d627486c33f54b140d3ebceb611e158153eef1e221bf2f6d57ae4fb3863ec815` before launching. Pre-flight: `hs_status` `not_running`, no `Hero_Siege.exe` in `tasklist`; live saves hash-identical to the out-of-band copy `hs2saves-20260921-pre-menulayout-L2-attempt3` (137 files). Server identity: closed-game `slot=0` → server-side validation error `greater_than_equal` (the new code's `ge=1`); `hs_selfcheck` six `pass`, 0 skipped. `hs_saves_backup` `20260921T145556Z_pre-L2a4-identity`. `hs_launch` → `plugin_ready` (`elapsed_s: 17.241`, pid 127116), then **immediately** `hs_select_character(slot=99)` → `foreground_not_game`, `actions_sent: 0`, `phase: local`, `elapsed_s: 6.247`, detail "the foreground window is 1968114, not the game's 854564; one SetForegroundWindow attempt did not take." The main-menu listing (`window=1920x1080`, `Play local` `win=336,534`, `listed=19 absent=none`) was again accepted with no `window_size_mismatch`. `proof_trail` `main_menu` `player via none`; `layout_trail` empty; `orbpickup: left_on`; screenshot `%LOCALAPPDATA%\HSDriveMcp\screenshots\20260921T145625717580Z_main_menu.png`. Measured while the game was still up: the foreground window 1968114 is owned by pid 43312, process `claude` (`Claude.exe`, the Claude desktop app), window title `Terminal`, parent `explorer`. So which MCP server ran the tool is not the variable: in attempts 2–4 the Claude app's terminal window held the foreground and Windows refused the tool's single `SetForegroundWindow`. `hs_stop_game` `exited: true`, `forced: false`. Inspect `changed: []`, `added: []`, `missing: []`; restored (pre-restore `20260921T145646Z_pre-restore`), inspect clean, all 137 live files hash-identical to the out-of-band copy. No retry; slot 1 and slot 2 were not run. Installed DLL at the end: `d627486c…ec815` (the owner restores `bea8cc00…`). **Attempt 5: pending.** |
| M-L2b | **Second launch**: `hs_select_character(2)`. Its `layout_trail` slot row must have a greater `win` x than M-L2's and the same `win` y, and the screenshot must show a different character. | owner-run, same step | **Not run at attempts 2, 3 and 4** (all stopped at the identity control's `foreground_not_game`, see M-L2). **pending** |

## What is deliberately not here

- **Character creation, class, difficulty, season, and anything past a
  loaded character; gameplay.** `hs_select_character` takes an existing
  save from the main menu to a loaded character and stops there. It does
  not create one or turn to a page other than the first, and nothing here
  plays the game. See "Character select" and "Known limitations".
- **Synthetic input anywhere but the game's own window.** Both tools refuse
  unless the target window belongs to a running `hero_siege.exe`, and on the
  `send_input` route both re-prove that the game holds the foreground
  immediately before every injection. `hs_input` never asks for more than one
  `SetForegroundWindow` attempt, then `foreground_not_game` — Windows'
  foreground lock exists for the user's benefit, and a caller that may run at
  any moment while a human is typing elsewhere is not the one that should be
  able to override it (`hs-drive-mcp-force-focus`, owner decision "Let the
  tool force focus", 2026-09-21). `hs_select_character` is the one exception,
  because it is a scripted, unattended flow started right after `hs_launch`
  and expects the game in front: when the plain attempt does not take, it
  escalates through `AttachThreadInput` (shares input state with whatever
  thread owns the foreground, so the lock treats this thread as part of its
  queue) and then one zero-effect `SendInput` record (no move, no button, no
  wheel — the one input event this module ever sends to a window that is not
  the game). Both steps only re-read the foreground they already hold; no
  global setting is changed, nothing is typed into another window, and every
  result names which step took in `focus_via` / `focus_trail`. M-L2 attempts
  2–4 (Verification, below) are the live evidence this exists to fix: a
  background session's single `SetForegroundWindow` call was refused by the
  foreground lock every time, with nobody at the PC.
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
py -3 -m unittest tests.test_hs_drive_mcp_input -v             # what actually leaves the process
py -3 -m unittest tests.test_hs_drive_mcp_charselect -v        # hs_select_character: clicks, proof, refusals
py -3 -m unittest tests.test_hs_drive_mcp_layout -v            # ForgePact's menulayout listing and the three matchers
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
