# `hs-drive` — a local MCP server for driving Hero Siege from a session

`tools/hs_drive_mcp/` is a developer-only stdio MCP server. It lets a Claude
Code session ask whether Hero Siege is running, whether EasyAntiCheat is
inactive and whether the modded copy is installed; prove its own instruments
work; and back up and restore the player's `hs2saves\` directory without ever
being able to lose a file.

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
`starlette`, `pywin32` and the rest of its own tree. `Pillow==12.1.0` is not
used by anything in this workorder — it is pinned now so the follow-on
screenshot tooling adds no dependency to an install that has already been
verified.

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

Every test sets both. That is the whole reason they exist: a suite that ran
against the owner's real saves would be one mistake away from a bug report
nobody can undo.

## Tools

Six now; the follow-on workorder adds six more. One tool per action, `hs_`
prefixed, with annotations on every one.

| Tool | Hints | Inputs | Returns |
| --- | --- | --- | --- |
| `hs_status` | read-only | — | `game_state`, `game_pids`, `eac_service`, `exe_path`, `exe_valid`, `exe_validation`, `mod_chain`, `ipc_dir`, `bp_ipc_exists`, `launch` |
| `hs_selfcheck` | read-only | — | `checks[]`, `summary` |
| `hs_saves_backup` | writes | `label` | `backup_id`, `files`, `total_bytes`, `path`, `skipped_links` |
| `hs_saves_restore` | **destructive** | `backup_id`, `confirm_backup_id`, `remove_extra=false` | `restored`, `files`, `pre_restore_backup_id`, `moved_extras`, `extras_not_moved` |
| `hs_saves_list` | read-only | `limit` 1–100 = 20, `offset` | `total`, `count`, `has_more`, `next_offset`, `backups[]` |
| `hs_saves_inspect` | read-only | `backup_id` | `manifest`, `changed[]`, `added[]`, `missing[]` |

`hs_saves_restore` is the only tool with `destructiveHint: true`, and that is
asserted rather than assumed.

Server `instructions`, which a client shows to the model:

> Order for a verified test run: `hs_selfcheck` → `hs_saves_backup` →
> (`hs_launch` → `hs_command` / `hs_screenshot` → `hs_stop_game`, once
> installed) → `hs_saves_inspect` → `hs_saves_restore`. Every refusal carries
> `reason`; a `skipped` self-check is not a pass.

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

Reserved for the `hs-drive-mcp-game` workorder, listed here so nobody invents
a second spelling: `game_not_running`, `bp_ipc_missing`, `invalid_command`,
`not_consumed`, `no_visible_window_for_pid`, `window_minimized`,
`not_launched_here`, `launcher_refused`, `mod_chain_incomplete`.

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

A check whose code raised is `fail` with the exception name, never `skipped`.
`skipped` always carries its reason in `detail`, because "we did not look" and
"we looked and it broke" must not be confusable. `checks.py` is a registry, so
the game workorder appends `screenshot_screen` and `ipc_ping` with
`register()` rather than editing any logic there.

`summary.healthy` is **not** "nothing failed". It requires every check
registered with `positive_control=True` — `process_snapshot` and
`backup_roundtrip` today — to have *passed*. A run where everything was
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
| A3/A4/A7 | Tool surface over stdio, self-check, status, `healthy` semantics | `py -3 -m unittest tests.test_hs_drive_mcp_server -v` | `OK`, 16 tests, no skips — 2026-09-20 |
| A5 | Engine pin, inert import, missing-source refusal | `py -3 -m unittest tests.test_hs_drive_mcp_engine_bridge -v` | `OK`, 8 tests, no skips — 2026-09-20 |
| A6 | No stdout, no listener, no shell | `Select-String -Path tools/hs_drive_mcp/*.py -Pattern 'shell=True\|os\.system\(\|socket\.\|\.bind\(\|HTTPServer\|uvicorn\|streamable\|^\s*print\('` | no matches — 2026-09-20 |
| B1–B10 | Save backup and restore, the wiped-directory recovery case and its negative control | `py -3 -m unittest tests.test_hs_drive_mcp_saves -v` | `OK`, 36 tests, no skips — 2026-09-20 |
| C6 | Release boundary, including the mechanical no-deletion check | `py -3 -m unittest tests.test_hs_drive_mcp_release_boundary -v` | `OK`, 7 tests, no skips — 2026-09-20 |
| C7 | Whole root suite | `py -3 -m unittest discover -s tests` | `Ran 741 tests`, `OK (skipped=9)` — all nine skips pre-existing in other suites — 2026-09-20 |
| C7 | This change touches no submodule | `git -C ForgePact status --porcelain`, `git -C HS-Offline-Launcher status --porcelain` | both printed nothing — 2026-09-20. (An unrelated ` M HS-Offline-Tracker` gitlink drift predates this work; `git diff --stat 589246f HEAD` touches no submodule.) |
| — | Self-check on this machine | `hs_selfcheck` over stdio | all five checks `pass` (137 files, 48 characters in the live dir; snapshot sees own PID; EAC `stopped`) — 2026-09-20 |
| C1 | `hs-drive` connects in a fresh session | `/mcp` in a new Claude Code session at the repo root | **not yet run** — owner-run; the working-directory assumption above is unconfirmed |

## Planned in `hs-drive-mcp-game`

The follow-on workorder adds six tools, bringing the surface to twelve:
`hs_launch`, `hs_wait_ready`, `hs_stop_game`, `hs_command`, `hs_ipc_tail` and
`hs_screenshot`. It also appends `screenshot_screen` and `ipc_ping` to the
`checks.py` registry and creates `ipc.py` and `capture.py`, which is why this
workorder leaves neither behind even as an empty stub — a stub would make that
work look partly done. Character select is a third, research-shaped workorder
described there.

## Changing any of this

```powershell
py -3 -m unittest tests.test_hs_drive_mcp_server -v            # the surface a client sees
py -3 -m unittest tests.test_hs_drive_mcp_engine_bridge -v     # the ForgePact pin
py -3 -m unittest tests.test_hs_drive_mcp_saves -v             # the fail-closed save contract
py -3 -m unittest tests.test_hs_drive_mcp_release_boundary -v  # nothing shipped knows it exists
py -3 -m unittest discover -s tests                            # all of the above, plus the rest
```

Adding a tool means adding its refusal tokens to `results.REASONS` (the
envelope refuses an unknown token outright), its annotations in `server.py`,
its row in the Tools table above, and its name to the expected set in
`tests/test_hs_drive_mcp_server.py`. Adding a self-check means one
`checks.register(...)` call and a row in the table above.
