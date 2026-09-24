# ADR 0004 — ForgePact's panel frontend is Svelte 5 + Vite, built to static files that its Python backend serves

**Status:** accepted, 2026-09-24
**Supersedes:** nothing
**Context:** the ForgePact UI redesign (branch `claude/forgepact-ui-redesign` in
this hub and in ForgePact). Its first step moves the existing page out of Python
one-for-one; the restyle against the Figma file comes after it.
[ForgePact's guide](../submodules/ForgePact/instructions.md) describes the result.

---

## The question

ForgePact's control panel was about 1,500 lines of HTML, CSS and JavaScript held
in one raw string, `HTML`, in `ForgePact/src/forgepact.py`, with the poll policy
(`POLL_POLICY_JS`) and the icon sprite from `src/panel_icons.py` concatenated in.
The owner wants the panel redesigned against a Figma file. Where should the
frontend live, and in what stack?

Three things are fixed and have to survive the answer:
- The backend is Python. `src/forgepact.py` owns the HTTP server and its `/api`
  routes, the config file, the backups and every plugin command;
  `src/offline_launcher.py` owns the launch engine.
- A player gets one onefile `ForgePact.exe`, built by PyInstaller.
- pywebview opens the panel in a native window, and the default browser is the
  fallback when WebView2 or pywebview is missing.

## The options

### Tauri, the hub's stack: ruled out

- The launcher, backup and plugin-command code is Python. Tauri would mean
  rewriting it in Rust, or shipping Python as a sidecar next to a Rust shell:
  two runtimes where there is one today.
- The hub's `hs-drive` MCP server imports `ForgePact/src/offline_launcher.py` by
  path (`tools/hs_drive_mcp/launcher_bridge.py`, pinned by the hub's
  `tests/test_hs_drive_mcp_engine_bridge.py`). Moving the engine out of Python
  breaks that server.
- A player would see no difference for any of that cost.

### Keep the HTML in the Python string: ruled out

1,500 lines of markup, CSS and script inside a raw string get no editor
tooling, no component model and no build step, and there is nothing to design
against. The contract tests read the string with regular expressions because
there was no other way in.

### Svelte 5 + Vite on the existing Python backend: chosen

- The same versions as `hub/package.json` (`svelte ^5.46.4`, `vite ^8.2.2`,
  `@sveltejs/vite-plugin-svelte ^7.3.0`), so the toolkit keeps one frontend
  stack to know.
- It builds to static files. The existing `ThreadingHTTPServer` serves them,
  PyInstaller bundles them with `--add-data`, and pywebview (or the browser
  fallback) loads the same local URL as before. Nothing about how ForgePact
  starts, where it listens or what it sends changes.

## Decision

1. The frontend lives at `ForgePact/panel/` and builds to `panel/dist/`, which
   is gitignored. `panel/package.json` is private, carries version `0.0.0` and
   has devDependencies only. ForgePact's version stays in one place,
   `__version__` in `src/forgepact.py`, and the page reads it from `/api/state`.
2. `forgepact.py` resolves `PANEL_DIST`: `sys._MEIPASS/panel` when frozen,
   `panel/dist` from source, and the `FORGEPACT_PANEL_DIST` environment variable
   overrides both. `/` serves `index.html`; any other path outside `/api` serves
   a file only when its resolved path is inside `PANEL_DIST`.
3. The `/api` contract does not change. The frontend never composes a plugin
   command; `/api/set` decides every live command from the saved config. That
   is what makes the port provable by recording POST bodies and `cmd.txt` lines.
4. The first step is a one-for-one port: the same ids, classes, data attributes,
   text, CSS and commands. Three things prove it: a behaviour oracle recorded
   from the legacy page (`panel/tests/behaviour-oracle.json`) and replayed
   against the new build, the ported contract tests, and a screenshot comparison
   of every tab at two widths within a 1% pixel tolerance. The restyle is
   separate work that starts from a port already shown to be equivalent.

## What this gives up

- A contributor who builds or packages the panel now needs Node (20.19+ or
  22.12+) as well as Python, and the browser tests need Microsoft Edge.
- The panel is no longer readable, or patchable, from the one Python file.
- A package can now be built without its page. The guard below exists because
  of that.

## Consequences

- **Node in release CI.** `forgepact-release.yml` sets up Node and runs `npm ci`
  and `npm run build` in `ForgePact/panel` after the tree-agrees-with-the-tag
  check and before the contract tests.
- **A fail-closed `panel/dist` guard.** `build_release.py` refuses to package
  when `panel/dist/index.html` is missing, in the same shape as the Satanic-pool
  guard (packaging hazard 4 in ForgePact's guide): a PyInstaller build without
  the panel would still build and start, and serve nothing. Once the port has
  landed, a missing build answers `/` with a 503 naming the command to run
  rather than the old page.
- **Tests read the panel source.** Contract tests that pinned the `HTML` string
  now read `panel/src` through `ForgePact/tests/panel_source.py`, and keep every
  fact they asserted. Browser checks run on `playwright-core` against the
  installed Edge (no browser download), against a sandbox server that imports
  `forgepact.py` with its sends mocked; no test route is added to the product.
- **An offline bundle.** Every asset the page uses (scripts, CSS, icons, fonts)
  is built into `panel/dist` and shipped in the exe. No CDN and no Google Fonts
  at runtime: the panel has to work on a machine with no network.
- **Fonts are licence-checked and shipped.** A font the redesign adds must carry
  a licence compatible with shipping it inside ForgePact (SIL OFL or similar),
  and its licence text ships with it.
- **The dev loop** is `py src/forgepact.py` beside `npm --prefix panel run dev`:
  Vite serves on port 5178 and proxies `/api` to the backend on 8766. 5178 keeps
  clear of the hub's 5177 and HS-Offline-Tracker's 5176.
- **Where the design lives.** The Figma file is "ForgePact redesign",
  <https://www.figma.com/design/75EleO8U3zngY8JU9adWpk>. It is a design
  reference, not a build input: nothing in the package or its build reads
  Figma.
