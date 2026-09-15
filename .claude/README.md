# `.claude/` — the automated half of `AGENTS.md`

`AGENTS.md` holds this repository's rules in prose. This directory holds the
subset that a machine can enforce or execute, so they stop depending on whether
an agent happened to read the right section of a 482-line file first.

Everything here is committed on purpose. Only `settings.local.json`
(per-machine overrides) is gitignored.

## Hooks — `settings.json` + `hooks/`

All three are `PostToolUse`, exit 0 silently when nothing is wrong, and exit 2
with an explanation when something is. They run through `py -3`; on a
non-Windows machine change that to `python3` in `settings.json`.

| Hook | Fires on | Catches |
|---|---|---|
| `catalog_signature.py` | `Edit`/`Write`/`Bash`/`PowerShell`, but only when `catalog/` actually differs from HEAD | `catalog/catalog.json` no longer verifying against its minisign signature, with CRLF called out by name when that is the cause |
| `tauri_command_guard.py` | edits under `hub/src-tauri/src/` | `block_on` inside a `#[tauri::command]`, and `#[tauri::command(async)]` on an `async fn` |
| `hub_frontend_tests.py` | edits to top-level `hub/src/*.js` | the hub's frontend tests failing |

Why these three and not others: each one guards a failure that has already
shipped, and each is cheap. The catalog check is a signature verification; the
command guard is a parse; the frontend tests are, in `hub/scripts/test.mjs`'s
own words, "a second of Node against a twelve-minute Windows build". **Nothing
here ever invokes `cargo`** — that is the twelve-minute path and it belongs in
`npm run check`, not in a hook that fires on every edit.

The catalog hook keys off the working tree rather than off which tool ran,
because a catalog can be rewritten by `Edit`, by a build script under `Bash`, or
by a rebuild this session never saw the path of.

## Agents — `agents/`

| Agent | Reviews |
|---|---|
| `sdk-contract-reviewer` | `hs-game-sdk/`, `tests/cpp/`, and anything reading runtime values: identity-by-positive-signal, instance-handle kind gates, cross-binding parity and test-stub fidelity |
| `tauri-command-reviewer` | `hub/src-tauri/src/`: command threading annotations, `announce()` after state changes, independent failure paths, and the debug-only MCP bridge gate |

Both exist because their bug class has recurred. `sdk-contract-reviewer` covers
four separate rediscoveries of one defect; `tauri-command-reviewer` covers three
shipped hangs. Each agent's file records the incidents, because the reason these
are hard to catch in ordinary review is that the code reads as correct.

The hook and the agent overlap deliberately on `hub/src-tauri/`: the hook takes
the two violations that are a grep, the agent takes the one that is a judgement
call ("does this synchronous command touch disk or the network?").

## Skills — `skills/`

| Skill | Invocation | Purpose |
|---|---|---|
| `catalog-rebuild` | user-only (`/catalog-rebuild`) | rebuild → sign → verify → test, with the signing-key and CRLF rules attached |
| `submodule-context` | Claude-only | loads the right `docs/submodules/<name>/instructions.md` before work starts |

`catalog-rebuild` is user-only because it has side effects and needs a signing
key that is deliberately not in this repository. `submodule-context` is
Claude-only because it is background knowledge, not an action anyone invokes.

## MCP servers — `../.mcp.json`

| Server | For |
|---|---|
| `tauri-hub` | driving a running debug hub through its bridge on `127.0.0.1:9223` |
| `context7` | live library documentation; `AGENTS.md` § "YYToolkit Integration" already assumes it |
| `github` | releases, dispatches and pointer PRs across the eleven repositories |

`tauri-hub` is pinned to `@hypothesi/tauri-mcp-server@0.13.0` to match
`tauri-plugin-mcp-bridge = "0.13"` in `hub/src-tauri/Cargo.toml`. Keep those two
in step: some tools (the desktop `manage_window` actions) return a version error
against an older plugin.

The bridge only exists in a **debug** build — it is registered under
`#[cfg(debug_assertions)]` because it can invoke any command in the application.
Start the hub with `npm start` in `hub/` and wait for `:9223` before expecting
`tauri-hub` to connect. `AGENTS.md` § "Drive a Tauri App Yourself Instead of
Asking Someone to Click It" has the rest, including the window label (`hub`, not
the `main` every tool defaults to).

`github` is a remote server and will ask you to authenticate on first use.

## Changing any of this

Run the hook scripts directly to test them — they read the Claude Code hook
payload on stdin and take an absolute `file_path`:

```bash
py -3 -c "import json,os;json.dump({'tool_name':'Edit','tool_input':{'file_path':os.path.abspath('hub/src-tauri/src/lib.rs')}},open('payload.json','w'))"
py -3 .claude/hooks/tauri_command_guard.py < payload.json; echo $?
```

A hook that exits 0 on a file you *know* is broken is the failure mode to watch
for — verify against a deliberately broken copy, not only against a clean tree.
