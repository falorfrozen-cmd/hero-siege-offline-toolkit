# Toolkit Hub — development guide

## Module overview & metadata

- **Module name:** Toolkit Hub (`Hero Siege Toolkit`)
- **Path:** `hub/` — **not a submodule.** It lives in this repository, so a
  change here is an ordinary commit rather than a pointer move.
- **Stack:** Tauri 2 + Svelte 5 (runes) frontend, Rust 2021 backend
  (`rust-version = "1.88"`), Vite 8, Node 20.19+.
- **Bundle:** NSIS, per-user, Windows x64 only. Identifier
  `io.falorfrozen.herosiegetoolkithub`.
- **Purpose:** Install, launch, update and roll back the ten tools in the
  toolkit from a signed, hash-pinned catalog, without changing how any of them
  behaves when started by hand.
- **CI:** `.github/workflows/hub-tag.yml` (manual: type the tag) validates it,
  moves the version and tags it; `hub-release.yml` (tag `hub-v*`) builds, tests,
  signs and leaves a **draft** release for a human to publish. `catalog.yml` /
  `catalog-publish.yml` feed it the catalog.

**Why each decision went the way it did is in
[`docs/hub/design.md`](../docs/hub/design.md), and the catalog's fields are in
[`docs/hub/catalog-schema.md`](../docs/hub/catalog-schema.md).** This guide is
how to work on the code; it deliberately does not restate the reasoning.

---

## Repository map

### `src/` — the Svelte 5 frontend

| File | What it is |
| --- | --- |
| `main.js` | Mounts `App`, and carries the bail-out panel for a frontend that fails to start. |
| `App.svelte` | The shell: sidebar, routing between screens, `connect()` on mount. |
| `Library.svelte` | Search, category/status filters, grid/list layouts, all ten tools in one list and full-card quick launch. |
| `ToolCard.svelte` | One tool: icon, requirements, status, shared primary action, star and keyboard-accessible overflow menu. |
| `ToolAction.svelte`, `tool-presentation.js` | Shared action/status rendering; display-only names, categories and search. |
| `ToolIcon.svelte`, `Icon.svelte` | Original SVG tool artwork and interface glyphs. |
| `action-gate.js` | Allows one pending mutation per tool, coalesces identical requests and rejects conflicting commands/options with a busy error. |
| `ToolDetail.svelte` | One tool in full, including *Verify files*. |
| `Updates.svelte`, `Downloads.svelte`, `Game.svelte`, `Settings.svelte`, `About.svelte`, `FirstRun.svelte` | The other screens. |
| `TitleBar.svelte`, `StatusBar.svelte`, `Toasts.svelte` | Window chrome and notices. |
| `library.svelte.js` | **The one copy of what the hub knows.** Every screen reads it; nothing recomputes it. |
| `hub-update.svelte.js` | The hub's own updater, kept apart from the tools' catalog. |
| `hub-check.js` | The runes-free state for `check_hub_update` -- checking/current/available/failed -- so `node --test` can run it; tested by `hub-check.test.js`. `library.svelte.js` copies it into `$state`. `checkAll` is the general catalog-then-hub check, so every manual hub check updates the same state. |
| `bridge.js` | The only file that knows whether Tauri is underneath. |
| `skin.svelte.js`, `skin.css`, `theme.css` | Legacy sprite lookups, CSS surfaces and the Obsidian/Ember/Void palettes. |

### `src-tauri/src/` — the Rust side

Each module opens with a doc comment saying what it is for; read that first.

| File | What it is |
| --- | --- |
| `lib.rs` | The commands, `ToolView`/`LibraryView`, `build_view`, `announce`, and the probe ticker. |
| `catalog.rs` | The catalog's shape, where it comes from (bundle → cache → embedded), and `HUB_REPO`. |
| `install.rs` | Download → verify → extract → activate, and rollback. |
| `launch.rs` | Starting tools, noticing they started, stopping them, elevation. |
| `verify.rs` | SHA-256 over artifacts, minisign over the catalog. |
| `state.rs` | `state.json`: installed set, settings, starred tools, staged queue. |
| `paths.rs` | Everything the hub writes, and the rule that it writes nothing else. |
| `procs.rs` | One process-table snapshot, and the three questions asked of it. |
| `game.rs` | Is Hero Siege up, is EAC up. |
| `version.rs` | Comparing two version strings (`0.9.10` beats `0.9.8`). |
| `log.rs` | The log file, including everything the web side reports. |

---

## Commands

```bash
cd hub
npm install
npm start           # the desktop app against a Vite dev server
npm run dev         # the frontend alone, in a plain browser
npm test            # frontend tests, then cargo test (the Rust engine)
npm run build       # the frontend bundle
npm run release     # the NSIS installer
npm run check       # build + test, what CI runs
```

- **Frontend tests run first**, using explicit file paths so the test command
  also works on supported Node 20.19+. Passing arguments to `npm test` runs only
  the requested Rust tests.
- **`npm test` shells out to Rustup's `cargo.exe` directly** (`scripts/test.mjs`)
  rather than through `cmd`, because a checkout path containing a space stopped
  at the first word. Same for `npm run tauri` (`scripts/tauri.mjs`).
- **Cargo needs PowerShell on this machine**, not the POSIX shell.
- **`npm run dev` is the fast loop.** With Tauri absent, `bridge.js` answers
  from the embedded catalog with everything stubbed as not installed, so the
  grid, the cards, the detail view and the settings screen are all workable
  without building the Rust side at all.

---

## Working on it

### Adding a command

1. Use `#[tauri::command(async)]` for a synchronous function that touches disk
   or the network, so it does not run on the WebView2 UI thread. For async APIs
   such as the updater, use `#[tauri::command] async fn` and `.await` instead.
   Never call `tauri::async_runtime::block_on` from a command running on that
   runtime: it panics and leaves the frontend's IPC promise unresolved. The
   startup worker may use `block_on` because it is a separate OS thread.
   `hub_info`, `get_settings` and `report` remain synchronous commands because
   they only read memory.
2. Register it in `invoke_handler![...]` at the bottom of `run()`.
3. **If it changes what a screen shows, call `announce(&app, &hub)`** before
   returning. Announcing is the rule: the backend pushes a freshly built view
   through `library-changed`, and no caller re-reads. A command that changes the
   view without announcing must call `refresh()` at its own call site rather
   than putting the cost on every other command.
4. **Add an answer to `browserAnswers` in `bridge.js`**, or `npm run dev`
   throws where the desktop build works.

### Adding something to the view

Decide it in Rust and carry it as a field on `ToolView`. `update_available` and
`favorite` are both there for the same reason: one implementation, not one per
screen.

### Touching `build_view`

**It must not make a network call.** Every tool that declares a health endpoint
used to be probed here, and a loopback connect to a closed port costs its whole
timeout on a machine that does not refuse promptly — 2.8 s for one view, built
on the UI thread, on a ten-second poll. Probing now happens on the ticker and
`build_view` reads its cache. `building_the_view_never_touches_the_network`
fails if that creeps back.

### Driving the running window

`npm start` starts an MCP bridge on `127.0.0.1:9223` — an optional dependency
behind the `mcp-bridge` feature (which only `npm start` passes) and
`#[cfg(debug_assertions)]`, because it can invoke any command the app has. A
release build does not compile it:

```bash
npx -y -p @hypothesi/tauri-mcp-cli tauri-mcp driver-session start --port 9223
npx -y -p @hypothesi/tauri-mcp-cli tauri-mcp webview-screenshot --window-id hub --file-path shot.png --format png
npx -y -p @hypothesi/tauri-mcp-cli tauri-mcp webview-interact  --window-id hub --action click --selector "button[aria-label='Star ForgePact']"
```

The window label is **`hub`**, not the `main` every tool defaults to. The other
sharp edges are in [`docs/hub/design.md`](../docs/hub/design.md#driving-the-running-window)
and in `AGENTS.md`.

---

## Testing

| Suite | Command | What it covers |
| --- | --- | --- |
| Rust unit | `npm test` | Version comparison, state round-trips, verification, paths, the view budget. |
| Install e2e | `npm test` | `src-tauri/tests/install_e2e.rs` drives the whole pipeline over real HTTP against a local server: hash mismatch, path traversal, missing entry point, interrupted install, rollback, both interlocks. |
| Against real releases | `npm test -- --ignored` | `src-tauri/tests/real_release.rs`. Downloads ~210 MB of genuine releases; ignored by default. |
| The catalog | `py -3 -m unittest discover -s tests` (repo root) | Catalog generation, minisign, `cut_release`. |

A change to the interface is not verified by the frontend compiling. Drive it
through the bridge, assert against what it actually wrote (`state.json`, the
log), and add a row to *Confirmed by hand* in `docs/hub/design.md`.

---

## Releasing

Tool repositories use `notify-hub-release.yml` to notify this hub when a stable
release is published. Run that workflow manually to verify or recover a missed
notification. It reuses `HUB_DISPATCH_TOKEN`; there is no nightly fallback.

Cut a release from **Actions > Hub tag > Run workflow**, typing the tag it
should go out as (`hub-v1.0.2`, or just `1.0.2`). It must be run from `main`.
The workflow checks the tag, moves the version to match and commits that to
`main`, pushes the tag, and starts the build. What comes out is a **draft**;
publishing it is the one manual step left, and until someone does, every
installed hub's update check gets a 404.

Three tags are refused before anything happens: one that already exists, one
below a version already tagged, and anything that is not three canonical
numbers (`01.0.2` is refused — Cargo will not build it).
`tools/hub_tag.py` has the reasoning, and `py -3 tools/hub_tag.py --tag 1.0.2
--existing $(git tag --list 'hub-v*')` answers "would this be accepted" without
running the workflow.

`py -3 tools/cut_release.py <version>` moves the version in all six places at
once and `--check` is what CI verifies against the tag, but the release workflow
calls it for you — bump by hand only when you want the commit separate from the
release. **Do not hand-edit those files**; a mismatch fails the release.

`HUB_REPO` in `src-tauri/src/catalog.rs` decides where the catalog, the hub's
own updates and the documentation links point. `hub-release.yml` sets it from
`github.repository`, so whichever repository publishes a hub builds one that
points back at itself. To build for a fork:
`HUB_REPO=owner/hero-siege-offline-toolkit npm run release`.

---

## Gotchas

- **`*.png` is banned by the root `.gitignore`** (it exists to keep extracted
  game sprites out of the repository). Every sprite the hub draws is generated
  SVG in `skin.svelte.js`. The six icon squares Tauri demands are the only PNGs,
  and `hub/.gitignore` re-includes exactly those.
- **`encodeURIComponent` does not encode `(` or `)`**, and every sprite refers
  to its own gradient as `url(#p)`. Unquoted inside a CSS `url(...)` those close
  the token early and the sprite silently does not paint — while working fine in
  an `<img src>`, which is what makes it easy to miss. `svg()` encodes all three.
- **Library artwork is inline SVG.** `ToolIcon.svelte` uses `$props.id()` for
  unique gradients when a tool appears in both quick launch and the grid.
  Legacy `.skin-*` classes now use CSS surfaces with their existing insets.
- **A signature failure is usually a stale worktree, not a signing problem.**
  `.gitattributes` marks the catalog and its signature `-text`; a checkout that
  rewrote `catalog.json` with CRLF is a catalog the hub refuses to load.
- **The worktree is CRLF.** A script that rewrites a file in Python text mode
  flips the whole file to LF and buries the real change in the diff. Use binary
  I/O.
- **`node_modules` is often missing** after a fresh clone of this repository;
  `npm install` first.
