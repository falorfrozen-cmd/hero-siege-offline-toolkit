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

| Hook | Fires when | Catches |
|---|---|---|
| `catalog_signature.py` | `catalog/` differs from HEAD | `catalog/catalog.json` no longer verifying against its minisign signature, with CRLF called out by name when that is the cause |
| `tauri_command_guard.py` | a `.rs` under `hub/src-tauri/src/` differs from HEAD | `block_on` inside a `#[tauri::command]`, and `#[tauri::command(async)]` on an `async fn` |
| `hub_frontend_tests.py` | a top-level `hub/src/*.js` differs from HEAD | the hub's frontend tests failing |

**All three key off the working tree, not the tool payload**, and that is the
single most important thing to preserve when editing them. A payload-shaped
hook only sees `Edit` and `Write`, and only when it can resolve
`tool_input.file_path` against the repository root. Both halves leak: a `sed -i`
or heredoc under `Bash` never produces a `file_path`, and a path the hook cannot
resolve returns "not my file" — which is indistinguishable from "nothing
wrong". That is not theoretical. During development all three exited 0 against
a harness feeding them POSIX-style paths Windows Python could not resolve, and
looked installed and healthy while guarding nothing. `git status --porcelain`
costs ~40 ms and has neither hole. `.claude/hooks/_common.py` holds the shared
parts.

**Escape hatch: `HSTK_SKIP_HOOKS=1`.** Every blocking message names it. There
are legitimate states these would otherwise wedge — most clearly a catalog
rebuilt *unsigned* on a machine without `$HUB_MINISIGN_SECRET_KEY`, which
`skills/catalog-rebuild/SKILL.md` explicitly contemplates. Because the trigger
is the working tree, that state would otherwise fail *every* later tool call,
including the ones needed to finish or undo the work. A blocking hook with no
way out is worse than no hook.

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

`github` does **not** authenticate interactively. Claude Code tries OAuth
dynamic client registration, that endpoint does not support it, and the session
reports *"Incompatible auth server: does not support dynamic client
registration"*. Probing directly confirms what it wants: a POST with a bearer
token returns 200, without one 401. So `.mcp.json` sends
`Bearer ${GITHUB_MCP_PAT}`, expanded from the environment — no token in the
repository.

Set it once, piping so the value is never displayed:

```powershell
[Environment]::SetEnvironmentVariable('GITHUB_MCP_PAT', (gh auth token), 'User')
```

**Claude Code must be restarted afterwards.** A process reads its environment at
launch, so the session that sets the variable is never the session that can use
it.

Three things worth knowing about that arrangement:

- **It is a copy, and copies go stale.** That is the `gh` CLI's own OAuth token.
  `gh auth refresh`, `gh auth logout` or a re-login rotates it, and this copy
  then 401s while `gh` itself keeps working — so the symptom is "the MCP server
  broke for no reason". Re-run the command above to resync.
- **It is plaintext at rest**, in the user's registry environment, readable by
  anything running as that user. `gh` keeps its own copy in the OS keyring, so
  this is a deliberate downgrade accepted for convenience.
- **It is broadly scoped**: gist, read:org, repo and workflow across *every*
  repository the account can reach, not just this one. A fine-grained PAT
  restricted to the `falorfrozen-cmd` repos narrows the blast radius
  considerably and drops into the same variable.

Until the variable is set the entry simply fails to connect, which is harmless —
the `gh` CLI covers the same ground and keeps its token in the keyring.

## A trap worth knowing: `#` in frontmatter

An agent or skill `description:` is a **plain YAML scalar**, so a space followed
by `#` opens a comment and everything after it is silently dropped — no error,
no warning, and the file still loads. `tauri-command-reviewer` shipped with
`adds or edits a #[tauri::command]` in its description and lost the last 86
characters, which were the trigger conditions that make the agent get picked at
all. It is now written as a **double-quoted scalar**, which is the right fix:
the attribute stays readable in the trigger text, and the quoting stops YAML
treating the `#` as a comment. Do the same for any `description:` containing
attribute syntax, a shell flag, or a URL with a fragment — quote the value
rather than rewording around the character, and never put authoring notes in
`description:` itself, since that text is what gets matched against.

To check a file: strip the frontmatter and look for an unquoted ` #` in it.

## Changing any of this

The hooks are covered by `tests/test_claude_hooks.py`, which runs with the rest
of the suite:

```bash
py -3 -m unittest discover -s tests
py -3 -m unittest tests.test_claude_hooks -v
```

Every test there is a **pair**: a positive control proving the hook fires on a
real violation, and a negative control proving it stays quiet on a clean tree.
A suite with only the negative half passes against hooks that do nothing, which
is exactly the failure this project keeps rediscovering — see `AGENTS.md`
§ "Prove the Instrument Before Trusting a Negative Result". If you add a check,
add both halves.

The rig builds a throwaway git repository in the system temp directory rather
than the session scratchpad, where `git init` fails with `Filename too long`.
