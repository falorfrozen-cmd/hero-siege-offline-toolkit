# Toolkit Hub — design

One window that installs, launches and updates the ten tools in the Hero Siege
Offline Toolkit. Tauri 2 + Svelte 5, in [`hub/`](../../hub).

This document describes what was built, and why each decision went the way it
did. The topology question has its own record in
[`docs/adr/0001-repo-topology.md`](../adr/0001-repo-topology.md).

---

## Shape

```
falorfrozen-cmd/<tool>  ──release──►  GitHub Releases (unchanged, ten repos)
         │ repository_dispatch: release-published
         ▼
  .github/workflows/catalog.yml → tools/build_catalog.py
         │        catalog.json + catalog.json.minisig, on the `catalog` release tag
         ▼
  Toolkit Hub (hub/)
    ├─ catalog.rs   fetch → minisign-verify → cache; embedded copy as the floor
    ├─ verify.rs    SHA-256 over artifacts, minisign over the catalog
    ├─ install.rs   download → hash → extract → versioned dir → activate → roll back
    ├─ launch.rs    spawn (elevated when declared) → health probe → track the PID
    ├─ game.rs      is Hero Siege up, is EAC up
    ├─ procs.rs     one process-table snapshot, and the questions asked of it
    ├─ state.rs     installed set, settings, staged installs
    └─ lib.rs       the Tauri commands, and the worker threads they start
```

## It is a library, not a browser

Five of the ten tools are hardened loopback web applications that refuse to be
framed — `hero-siege-item-editor/hs_item_editor_gui.py:7808` sets
`frame-ancestors 'none'` and `X-Frame-Options: DENY`, and
`HS-Offline-Launcher/src/hs_offline_launcher.py` does the same plus an HMAC
API token bound per process. Two more (`HSSaveEditor`, `hs-stat-forge`) are
Tkinter and cannot be embedded in a webview at all.

A proxy in front of them would break the `Host`/`Origin` checks and the
per-process token — deliberate anti-DNS-rebinding defences dismantled to get a
cosmetic tab bar. So the hub owns processes and windows, not documents. Uniform
chrome across heterogeneous tools is not achievable and is not attempted.

---

## What is on disk

```
%LOCALAPPDATA%\Hero Siege Toolkit\
  tools\<id>\<version>\      extracted artifact
  tools\<id>\current.json    which version is live, and what to roll back to
  cache\downloads\           hash-verified before anything uses them
  cache\catalog.json         the last catalog that verified, with its signature
  state.json                 installed set, settings, starred tools, last check
  logs\hub.log
  bundle\                    optional offline-bundle payload, consulted first
```

**Program files only.** `%LOCALAPPDATA%\Hero_Siege\forgepact.json`,
`%LOCALAPPDATA%\HSCraftSim\session.json`, `%LOCALAPPDATA%\HS Offline
Tracker\events.ndjson` and every tool's saves and backups stay exactly where the
tool puts them. Uninstalling the hub never costs a player their settings, and a
tool started outside the hub behaves identically.

`current.json` lives beside the version directories it arbitrates between,
separately from `state.json`, so a hub whose state file is lost can still tell
which of two version directories is live.

---

## Installing

1. **Download** into `cache\downloads\<name>.part`, streaming, with progress.
2. **Verify** against the SHA-256 the catalog pins. A mismatch deletes the file
   and stops — leaving it invites a later run to find it, skip the download and
   trust it.
3. **Extract** into `tools\<id>\.staging-<version>`, stripping the archive's
   wrapping directory. Entries that would write outside the destination are
   refused.
4. **Check the entry point exists** in what was extracted. A tool that installs
   but cannot launch is worse than one that refuses to install.
5. **Write a manifest** of every file's hash into the staging tree, so Verify
   can answer offline later.
6. **Activate** by renaming staging into `tools\<id>\<version>`, then updating
   `current.json`.

The rename is the commit point. An install interrupted anywhere before it leaves
rubbish in a staging directory and a working installation untouched — and the
next attempt clears that staging directory rather than building on it.

Only the live version and the one behind it are kept. Rollback is then a pointer
change rather than a re-download, and rolling back twice goes forward again.

### The verification chain

None of the ten tools is code-signed. SmartScreen will warn about every one of
them and Authenticode has nothing to say. What stands in for it:

```
embedded public key  (compiled into the hub; rotating it is a hub release)
        │ verifies
catalog.json.minisig ──covers── catalog.json
                                    │ pins
                              sha256 per artifact
                                    │ checked before
                              anything is extracted
```

A release asset swapped after the catalog was built fails at the hash check. A
catalog edited after it was signed fails at the signature. The signature check
covers **both** of minisign's signatures — the one over the content and the one
over `signature || trusted comment` — so the trusted comment shown in About has
actually been signed.

---

## Launching

Each tool is spawned as its own process, with the working directory set to its
install directory: several resolve data relative to it (ForgePact looks for
`modfiles/` next to the executable), so that is load-bearing.

**Elevation.** `hs-stat-forge`, `HS-ValueEditor` and `Hs-Offline-Loot-Forge` need
`SeDebugPrivilege`. The hub itself runs non-elevated and elevates per launch
through `ShellExecuteExW` with the `runas` verb — `CreateProcess` cannot elevate,
and a non-elevated parent asking for an elevated child gets
`ERROR_ELEVATION_REQUIRED`. `SEE_MASK_NOCLOSEPROCESS` is what makes
`ShellExecuteExW` hand back a process handle, so an elevated tool can still show
as *Running* and still be stopped. A declined UAC prompt (`ERROR_CANCELLED`,
1223) is reported as a decision, not a failure.

**Health.** The hub reuses each tool's existing endpoint rather than inventing a
protocol that would need a commit to all ten repositories:
`hero-siege-item-editor` answers `/api/instance` with `{version, pid, port}`,
`HSCraftSim` answers `/_health` with `{application, version}`. HS Offline
Launcher gets `any_status`, because its per-process HMAC token answers an
unauthenticated probe with 401 — and "something is listening" is the only
question being asked. Tools with no HTTP surface fall back to "the process is
still alive", which is all a Tkinter app can offer.

**Noticing a tool the hub did not start.** `Hub.running` is in memory, so every
tracked PID is lost when the hub restarts. Three signals are tried, strongest
first, all from the one process-table snapshot `build_view` already takes:

1. **A tracked PID that is still alive** — this hub started it.
2. **A process whose executable lies inside the tool's install directory**
   ([`procs::is_under`](../../hub/src-tauri/src/procs.rs)). That process *is*
   that tool, whatever it is called and whoever started it, so the hub has a PID
   it can still stop. This is the only signal that works for `hssaveeditor`,
   `hs-value-editor`, `hs-offline-loot-forge` and `hs-stat-forge`, which declare
   no health endpoint and no ports — before it, they went invisible on restart
   and their cards offered Launch for something already open, which for the
   single-instance ones then failed.
3. **The health endpoint answering** — something is up but it is not the copy the
   hub installed, so there is no PID to act on. The card says so and offers
   nothing.

The match is case-insensitive because Windows paths are, and it checks a path
*component* boundary so `…\forgepact\1.3.16` cannot match a process under
`…\forgepact\1.3.160`.

Signals 1 and 2 both yield a PID, and 2 sets *Running (outside the hub)* as
well — the hub can stop it, and should still say it was not the one that started
it. `stop_tool` re-detects by install path for exactly that case: offering Stop
for a PID the hub had not recorded would be the same lie as offering Launch for
something already running.

---

## Updating

Policy: check on launch and on a button; a setting for auto-download; and, nested
under it, auto-install. `Settings::effective_auto_install()` enforces the nesting
in Rust as well as in the UI, so a hand-edited `state.json` cannot get past it.

### The two interlocks

Both produce a *staged* install — downloaded, verified, and waiting — with the
reason shown on the Updates screen.

- **Never over a running tool.**
- **Never while `Hero_Siege.exe` is running.** ForgePact patches the game's PE
  and holds file IPC through `bp_ipc/cmd.txt`; HSSaveEditor documents a
  game-closed requirement. Writing over either mid-session is how a player loses
  a character.

Staged installs are applied when the blocking condition clears: on Stop, and at
startup before the network is touched — a pending install the user already agreed
to should not wait on a check succeeding.

**Every path that writes over an installation checks them**, not only the
automatic one. `install_tool` — the command behind a card's *Update* button and
behind *Update all* — stages rather than refusing, because the reader has
already asked for the update and the download is the slow part. The checks were
once on the auto-install path alone, which left *Update all* free to write over
a tool whose own card had just withheld its button for being open.

**"Is this tool running" is answered from a process snapshot**, the way
`build_view` answers it: a tracked PID still alive, *or* any process whose
executable sits inside the tool's install directory. `Hub.running` alone is not
enough — it lives in memory, so a restart empties it, and `apply_staged` runs at
startup. The moment the interlock mattered most was the moment it could see
nothing.

**The interlock is read after the download, never only before it.** Every path
is download → ask → activate or stage, and `activate_or_stage` takes the answer
as an argument so its caller has to say *when* it asked. Asking only beforehand
is worthless here: the download runs for minutes, so an install begun against a
closed game went on to overwrite a running one, with a check that had been true
when it was made and meaningless by the time it was used.

**Every path that emits progress reaches a terminal event.** A card counts
itself busy from `Started` until one arrives, and nothing else clears that — not
a rejected command, not `library-changed` — so a path that returns without one
disables that card's button until the hub is restarted. There are four terminal
phases, and they are distinguishable on purpose: `done` installed a version,
`failed` installed nothing and offers *Try again*, `staged` downloaded and
verified but is waiting on an interlock, `downloaded` fetched the bytes because
that is all auto-download was asked to do. `staged` is emphatically not `done`,
or the card claims a version it does not have. The frontend's copy of that list
lives in one place (`TERMINAL_PHASES`) because it had three, and the two new
phases would otherwise have been unknown to all of them.

Guaranteeing it is structural rather than remembered: `ProgressStream` notices

**A finished row leaves the drawer after a moment, and only its own timer may remove it.** Every progress event takes ownership of that tool's row, and a scheduled cleanup fires only if it still holds it. Removing by id alone meant a tool that finished one operation and began another inside that moment — auto-download completing, then *Update all* clicked — had the new operation's row deleted by the old one's timer, so the card stopped looking busy and offered its button back mid-install.

That bookkeeping lives in `hub/src/progress-rows.js`, free of Svelte runes so `node --test` can execute it. Three frontend bugs in a row lived in logic nothing could run; `npm test` now runs those tests before the Rust ones.
terminal events passing through and emits `Failed` if it is dropped without one.
Four exits lost their terminal event simultaneously when orchestration moved out
of `install::install`, which had been emitting it on the way out — which is the
argument against relying on remembering at each `return`.

**A staged update that can never be applied is dropped, not retried.**
`install_artifact` verifies against the hash the catalog carries *now*, so a
tool that releases again while its update waits behind a running game leaves
bytes that can no longer pass — and the check would fail on every startup,
forever, with an error toast each time and nothing in the interface able to
clear it. Same for an entry whose download has been cleared out of the cache.
Dropping it leaves the tool showing "an update is available", which is true and
which the reader can act on.

**One install per tool at a time**, held in Rust from before the download until
after the activation. Two installs of one tool share a `.part` download and a
staging directory: the second writes over the first's download, then races it to
the rename that commits the install. The claim covers the download because the
download is the part that collides — taking it only around the activation left
*Update all* free to start a second download into the same file while the launch
check's was still running. Uninstall and rollback take the same claim: the first
deletes the directory an install is writing into, and the second rewrites the
`current.json` an install rewrites when it activates.

Uninstall also asks whether the tool is running the same way everything else
does, from a process snapshot. It used to consult only the in-memory PID map,
so after a restart it saw nothing and deleted the directory a running tool was
executing from. `install_tool` also runs the install *before* it resolves,
so awaiting it means the install finished — it used to return as soon as a
worker thread had been spawned, which is what let *Update all* clear its own
button while ten downloads were still running.

### Work offline

A master switch that disables every outbound request including the launch check.
`HS-Offline-Tracker/src/About.svelte:6` states the project's value plainly: the
check is "never something the app does on its own... the only request the app
ever makes". A hub whose *job* is distribution cannot keep that literally, but it
keeps the part that matters — nothing is contacted before the first-run screen is
answered, and Work offline is one click away on that screen.

`Settings::may_reach_network()` is `!work_offline && first_run_done`, and every
command that would fetch checks it — **including the hub's own self-update**,
which is the largest request it makes. That one used to escape: the install ran
in the frontend, calling the updater plugin directly, so turning Work offline on
with an update pending left *Download and install* downloading and installing.
It now runs in Rust behind `install_hub_update`, and `updater:default` has been
removed from the window's capability, so the frontend route is closed rather
than merely unused.

### The hub itself

Tauri's updater plugin, driven entirely from Rust — `check_hub_update` asks,
`install_hub_update` downloads and installs, and the handle the updater returns
never has to cross the boundary because the side that obtains it is the side
that uses it. `latest.json` is published by `tauri-action` with
`includeUpdaterJson: true` and signed with `TAURI_SIGNING_PRIVATE_KEY`; the
matching public key is in `tauri.conf.json`.

A manual dry run of `hub-release.yml` builds the bundle and uploads it as a
workflow artifact, with no release inputs at all. It once passed `--no-bundle`
while still supplying `tagName`, which cannot work: `tauri-action` fails with
`No artifacts were found.` when a tag is given and nothing was bundled. The step
whose whole job is to prove a release will build was the one that could never
finish.

A failed check -- offline, a release page with no `latest.json` because the
newest release is still a draft, a signature that does not verify -- comes
back from `check_hub_update` as `Err("Could not check for updates. Please try
again.")`, distinct from a successful check that simply found nothing newer
(`Ok(None)`). The two used to be indistinguishable: a rejected promise was
caught, logged as a toast, and read back as `null`, so the About screen said
"This is the newest release" after a check that never completed
(issue #44). Only a successful check earns that sentence now. A failure
leaves whatever was previously cached in `hub.hub_update` untouched -- a
request that could not reach the release page is no evidence that a
previously-found release went away, and `install_hub_update` already refuses
with "no longer being offered" if it really did. The launch check
(`startup_check`) stays silent on failure either way: no toast, no "hub
checked at" timestamp, and the cache is left as it was.

Every manual hub check -- About's button and the general "Check for updates" /
"Check now" on Library and Updates -- goes through the one `hub-check.js`
state, so About always shows the outcome of the latest check, whichever screen
ran it. Before that, a success from About followed by a failure from Updates
left About saying "This is the newest release" (PR #56 review). A failure from
Library or Updates also raises a toast, since those screens have no inline
place for it; About shows it inline only.

### Cutting one

**Actions > Hub tag > Run workflow**, type the tag, and `hub-tag.yml` does the
four things that otherwise happen by hand and in the wrong order: it checks the
tag is one this repository can release, moves the version to match, pushes the
tag, and starts `hub-release.yml` against it. Nothing is tagged on a merge; a
release happens when someone asks for one.

The typed tag is the one place in the release path where a human hand reaches
straight into CI, and everything downstream trusts it -- the tree is rewritten
to match, the commit is pushed to `main`, the release is signed against it. So
`tools/hub_tag.py` decides whether the tag is usable before any of that has
happened, and refuses three things.

A tag that already exists. Tagging into one that has a release gives that tag
two release objects, and `releases/latest/download/latest.json` then resolves to
whichever of the two GitHub calls latest -- which is what hub-v0.1.1 did to
every installed hub's update check.

A version below one already tagged. `releases/latest` would point at it, and
every hub asking what the newest version is would be handed something older than
what it is running. Releasing an older line on purpose means pushing that tag by
hand, which `hub-release.yml` still builds. The comparison is numeric: this
repository's tags are ragged -- `0.1.x` and `1.0.x` both exist -- and
`hub-v0.1.4` sorts after `hub-v1.0.0` in any lexical order.

Anything that is not three canonical numbers, with or without the `hub-v`. The
string ends up in a shell and in `git tag`, so the check is not politeness about
formatting. For the same reason the input reaches the shell only through `env:`;
interpolated into a `run:` line, `${{ inputs.tag }}` is whatever was typed,
executed. Canonical rules out a leading zero: `01.0.2` is three numbers, passes
the six-field check, and is then refused by Cargo — `invalid leading zero in
major version number` — by which point the tree is rewritten and the tag is
pushed. It also rules out `\d`: Python matches Arabic-Indic and fullwidth
digits with it, so `1.0.2` followed by U+0663 passed a `\d`-based check and
every version field in the tree then held it, until Cargo refused the build
with `unexpected character after patch version number`. The pattern says
`[0-9]`. `hub_tag.py` reuses `cut_release.VERSION` rather than keeping a second
one, so the gate and the bumper cannot disagree about what is writable.

Those checks are worth nothing if the answer they are measured against is
wrong, which is the other thing this step gets right. `git ls-remote | cut | tr`
exits with `tr`'s status, so a failed query reported success and an empty tag
list — and every comparison against existing tags then passed vacuously. A
downgrade to 0.5.0 was accepted that way with `hub-v1.0.1` present. `pipefail`
makes the step stop instead, because "no tags" and "could not ask" are not the
same answer.

**Everything that can say no runs before anything is written.** The draft guard
was originally after the rewrite, which meant a draft release sitting on an
unpushed tag — the one case that guard exists for, and the one case
`hub_tag.py` and `git` both structurally cannot see — was discovered only after
the bump had been committed and pushed, leaving `main` claiming a version with
no release and no tag behind it.

Three more things about that workflow are less obvious than they look.

It refuses to run anywhere but `main`, because the bump it pushes would
otherwise put a feature branch's tree on `main` and tag code that was never
merged.

It dispatches the release rather than relying on the tag push. A tag pushed with
`GITHUB_TOKEN` does not start another workflow run: GitHub blocks that to stop
workflows triggering themselves, so `hub-release.yml`'s `on: push: tags:` never
fires and the tag would sit there with nothing building it. `workflow_dispatch`
is one of the two documented exceptions that always create a run.

And it dispatches against the tag. Every guard in `hub-release.yml` is written
`if: startsWith(github.ref, 'refs/tags/hub-v')`, so `--ref main` would still
build, sign and publish -- with the six-field version check, the
duplicate-release guard and the draft notice all silently skipped. `--ref "$TAG"`
is what makes this run the same checks a hand-pushed tag does.
`tests/test_hub_tag_workflow.py` fails if any of that drifts, and
`tests/test_hub_tag.py` covers the tag checks themselves.

What it deliberately does not do is publish. `releaseDraft: true` stands, so
what it leaves behind is an installer, a signature and `latest.json` sitting in
a draft, and a person still decides when that becomes the version every
installed hub updates itself to.

---

## The interface

1180×760, `decorations: false`, custom title bar. `theme.css` is copied verbatim
from HS-Offline-Tracker and the three skins (`obsidian`, `ember`, `void`) come
with it.

| Screen | What it is for |
| --- | --- |
| Library | The grid. Card per tool: name, one line, state chip, one primary button, and a star plus an overflow menu on the title's line. |
| Updates | Everything with a newer release, *Update all*, and the staged queue with its reasons. |
| Game | Whether Hero Siege and EAC are running — so the interlocks are legible rather than mysterious — and a way to start the game through HS Offline Launcher. |
| Settings | Work offline, check on launch, auto-download, auto-install (nested), skin, developer mode. |
| About | Versions, the catalog's signature, the log, the toolkit's Discord, and the hub's own updater. |
| Downloads drawer | Per-file progress with *Verifying* as a step of its own. |
| First run | What the hub will contact, before it contacts it. |

### Starred tools

A star on each card, persisted in `state.json` as a set of ids, lifts that tool
into a **Starred** row above the rest of the grid. Ten tools is enough that the
two or three anyone actually uses are worth putting first, and short enough that
hiding the others would be worse than ordering them.

Three things follow from it being a set of ids and not an ordering:

- The starred row is catalog order with the rest taken out, so starring never
  has to decide what a tool ranks *against*.
- A star for an id that later leaves the catalog matches nothing and draws
  nothing. It is not an error and it leaves no hole.
- The split is applied **after** the filter, not instead of it. A star says
  where a card sits, not that it ignores what the reader asked to see — so
  *Updates* with one starred tool waiting shows that one on top, and shows
  nothing at all if the starred tool is current.

`set_favorite` refuses to star an id the catalog does not have, so a stale
frontend cannot write one; unstarring is allowed for any id, because a tool that
has since left the catalog must still be removable. A click that changes nothing
returns without writing `state.json` or rebuilding the view.

### One button on a card, and two glyphs

The star and the overflow menu share the title's line, right-aligned and
borderless; the primary button below has the footer to itself.

The overflow menu used to sit in that footer as a 38px bordered square, and it
read as a second control of equal weight beside *Install* — which it is not; it
is a place to put the six things a card cannot show. It was also visibly taller
than the button next to it, because `skin-button`'s sprite insets its plate
7/64 from the top and bottom while a plain CSS border does not, so two elements
of identical height looked mismatched.

The two glyphs are the same weight: `more` is the one icon drawn without
`icon()`'s disc, because a circle around one of a pair reads as a border --
the border that was just taken off the button around it.

The two are drawn to the same weight. The overflow glyph is the one icon in
`skin.svelte.js` without `icon()`'s disc behind it: a circle around one of a
pair beside a heading reads as a border — the border that was just taken off
the button around it.

`.corner`'s offsets are `.card`'s **padding**, not its padding plus its border.
An absolutely positioned child is placed against the padding box, so counting
the 11px nine-slice border into `top` put the glyphs exactly that far below the
title. The fix is checkable rather than eyeballed: the heading's client rect and
`.corner`'s are now the same box, top and bottom.

Both glyphs sit outside `.body`. `.body` is itself a button — the whole card
opens the detail view — and a button inside a button does not give you two
separate clicks. `.corner` is positioned but carries **no `z-index`**: being
positioned is enough to paint it over `.body`, and a stacking context there
would trap the open menu's `z-index` inside a 42px box, where the next card's
glyphs would paint over it.

### Two things about the sprites

`skin.svelte.js` is HS-Offline-Tracker's, with two deliberate differences and
two bugs fixed that are worth knowing about because both fail *silently*:

- The Tracker imports two PNGs for its backdrop and app mark; the hub draws both
  as SVG. The root `.gitignore` bans `*.png` (it exists to keep extracted game
  sprites out of the repository), and a hub whose art is entirely generated needs
  no exception to it. The six icon squares Tauri demands are the only PNGs, and
  `hub/.gitignore` re-includes exactly those.
- `encodeURIComponent` does not encode `(` or `)`, and every sprite refers to its
  own gradient as `url(#p)`. Unquoted inside a CSS `url(...)`, those parentheses
  close the token early and the sprite does not paint — while working perfectly
  in an `<img src>`, which is what makes it easy to miss.
- These are nine-slice marks. Painted as `background-image` at
  `background-size: 100% 100%` they stretch, so a 620px panel gets a 100px corner
  radius and its gold corner ticks become bars. `skin.css` uses `border-image`
  with a slice instead; the sprite comes in as `--skin-src` so a hover state can
  swap it without a second class.

### Developer mode

`source_launch` in the catalog is what makes the hub exercisable before any
release exists: with the submodules checked out, a tool can be run from source.
Eight of the ten have one; `HS-ValueEditor` and `Hs-Offline-Loot-Forge` ship a
built executable and nothing else.

`bridge.js` does the same thing one level up — with Tauri absent it answers from
the embedded catalog, so `npm run dev` draws the real ten-tool library in a plain
browser and the whole frontend is workable without the Rust side running. A
command added to the desktop side wants an answer here too, or the preview
throws where the hub works: `set_favorite` is the newest one.

### Driving the running window

`tauri-plugin-mcp-bridge` is a dependency of `src-tauri`, started **only** under
`#[cfg(debug_assertions)]`, bound to `127.0.0.1:9223`, with a dev-only capability
naming the `hub` window. So a debug build can be clicked, screenshotted and
queried from a terminal instead of by hand.

The `cfg` is the whole point. The bridge can invoke any command this application
has, over a socket, with no authentication — which is exactly what makes it
useful for verifying an interface change and exactly why a release build must
never start one.

```bash
npm start                                                     # wait for :9223
npx -y -p @hypothesi/tauri-mcp-cli tauri-mcp driver-session start --port 9223
npx -y -p @hypothesi/tauri-mcp-cli tauri-mcp webview-screenshot --window-id hub --file-path shot.png --format png
npx -y -p @hypothesi/tauri-mcp-cli tauri-mcp webview-interact  --window-id hub --action click --selector "button[aria-label='Star ForgePact']"
```

Four things about it are worth writing down, because each makes the bridge look
broken while it is working:

- **The window label is `hub`, not `main`.** Every tool defaults to `main` and
  fails with `Window 'main' not found`. Pass `--window-id hub`.
- **The package's binary is `tauri-mcp`**, so `npx` needs `-p`:
  `npx -y -p @hypothesi/tauri-mcp-cli tauri-mcp <subcommand>`.
- **`--script` must be one line.** A multi-line script fails with
  `Script execution timeout` even when it would return instantly.
- **Long work needs two calls** — the transport gives up well before `--timeout`
  says it will. Start the work, stash the result on `window`, read it back.

Prefer a selector to a coordinate: a selector re-queries after the grid has
re-laid itself out, which is what a click that moves a card between the *Starred*
row and the grid below guarantees will happen. The starring rows in *Confirmed by
hand* were driven this way, and checked against `state.json` rather than against
the screenshot alone.

---

## CI

| Workflow | Trigger | What it does |
| --- | --- | --- |
| `.github/workflows/catalog.yml` | `repository_dispatch: release-published/submodule-updated`, manual | Rebuilds and re-signs the catalog, then **opens a pull request**. Publishes nothing. |
| `.github/workflows/catalog-publish.yml` | push to `main` touching `catalog/`, manual | Verifies the signature and uploads the catalog to the `catalog` release tag. |
| `.github/workflows/hub-tag.yml` | manual, with the tag typed in | Checks the tag is one this repository can release, moves the version to match, tags it, then dispatches the release against the tag. Publishes nothing. |
| `.github/workflows/hub-release.yml` | `hub-v*` tag, dispatch, manual dry run | Tests, builds, signs, and uploads the hub plus `latest.json` to a **draft** release. |
| `.github/workflows/ai-review.yml` | the `ai-review` label, or a `@claude review` comment | Reviews the pull request and posts findings as inline comments. Opt-in only. |
| `.github/workflow-templates/notify-hub-release.example.yml` | — | The sending half, to copy into a tool repository. |

The catalog workflow opens a pull request rather than pushing, matching the rule
`submodule-dispatch.yml` already set: an event anyone can fire should not move
the default branch.

Proposing and publishing are separate workflows because they answer to different
events. Publishing was once a step inside the regenerate job, conditioned on the
rebuild finding *nothing to change* -- which made the release tag a side effect
of a no-op, and meant merging a catalog change published nothing until some
later run happened to find no further change. Merging is the event that should
publish, so merging is what triggers it.

`catalog-publish.yml` passes `--latest=false` when it creates the release, and
that flag is load-bearing. GitHub picks the latest release by date unless told
otherwise, and the hub's updater endpoint is
`releases/latest/download/latest.json` -- so a catalog release allowed to become
"latest" would quietly stop the hub being able to update itself until the next
hub release displaced it.

### Which repository a build trusts

Four things have to agree: the catalog URL, its signature URL, the updater
endpoint, and the documentation links. They are all derived from one value,
`HUB_REPO` in [`hub/src-tauri/src/catalog.rs`](../../hub/src-tauri/src/catalog.rs),
read through `option_env!` with the canonical repository as its default.

They did not always agree. The four were separate literals pointing at a fork
while the release-notification template told tool repositories to notify the
canonical repository -- so a new tool release would have rebuilt one catalog
while every installed hub read another. Merged upstream, it would have been
worse than a broken link: every upstream user's hub would have fetched its
catalog *and its own updates* from a personal fork's release assets.

`hub-release.yml` sets `HUB_REPO` and rewrites the updater endpoint from
`github.repository`, so whichever repository publishes a hub builds one that
points back at itself. A fork's release checks the fork; the canonical release
checks the canonical repository; neither needs a source edit. The endpoint is
patched rather than templated because `tauri.conf.json` cannot read an
environment variable.

`build.rs` emits `cargo:rerun-if-env-changed=HUB_REPO`. Cargo does not track
`option_env!` as an input by itself, and CI caches the build directory -- without
that line a cached artifact compiled against the previous value could be handed
back, and a fork's release would ship a hub pointing at whoever built last.

To build a hub for a fork locally:

```bash
cd hub
HUB_REPO=owner/hero-siege-offline-toolkit npm run release
```

A plain local build points at the canonical repository, which is correct for
anything published and means "Check for updates" fails until that repository has
a `catalog` release.

### Repository secrets

| Secret | Used by | What happens without it |
| --- | --- | --- |
| `HUB_MINISIGN_SECRET_KEY` | `catalog.yml` | The job fails deliberately. An unsigned catalog is one the hub refuses, so publishing one would ship a hub that cannot update. |
| `TAURI_SIGNING_PRIVATE_KEY` | `hub-release.yml` | The installer builds but its updates can never be verified. |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | `hub-release.yml` | Only if the key has one. |
| `HUB_DISPATCH_TOKEN` | each tool repository | Release notification fails visibly. Configure the secret and rerun the notifier; there is no scheduled fallback. |
| `CLAUDE_CODE_OAUTH_TOKEN` | `ai-review.yml`, here and in `ForgePact` | The review run fails to authenticate. Nothing else is affected, because no other workflow uses it and review is opt-in. |

`CLAUDE_CODE_OAUTH_TOKEN` is not an API key and spends no API billing. It comes
from `claude setup-token`, authenticates against a Claude subscription, and is
tied to whoever generated it — which is why it is a per-repository secret here
rather than an organisation-level one. The alternative, an `ANTHROPIC_API_KEY`
from the Console, opens a second, separately-billed account and is not what this
is set up to use.

**The secret is only half of the setup.** The [Claude GitHub
App](https://github.com/apps/claude) also has to be installed on the repository,
because the action exchanges the workflow's OIDC token for an app token before
it does anything else. Without the app that exchange returns `401 Unauthorized`
with "Claude Code is not installed on this repository", and the job fails having
reviewed nothing — a secret that is present and correct does not save it. Install
the app once for the organisation and grant it both repositories. This was
learned the direct way: ForgePact's first review run failed on exactly that,
with the secret already in place.

### Asking for a review

`ai-review.yml` has no `on: pull_request` trigger on purpose. Two workflows in
this repository open pull requests by themselves — `submodule-dispatch.yml`
bumps a pointer, `catalog.yml` regenerates the catalog — and a one-line SHA
change has nothing to review. Reviewing on open would spend a review on every
one of them, so the request is the trigger instead:

- add the **`ai-review`** label in the pull request sidebar, or
- comment **`@claude review`** on the pull request.

Either works again later for a fresh review after pushing; the label does not
re-run by itself on subsequent pushes. The action additionally requires the
requester to have write access and rejects bot actors, so automation cannot
start a review by applying the label.

Concurrency is declared on the job, not the workflow, and its group is only
shared by a real request. Every comment and every label starts a run of this
workflow, and at workflow level those runs joined the pull request's group
before the job's `if` rejected them -- so an ordinary "thanks" comment cancelled
a review already in progress. Unrequested events now get a group unique to their
own run. `tests/test_ai_review_workflow.py` pins that, pins the opt-in triggers,
and fails if the two written-out copies of the request predicate drift apart.

`--allowedTools` in `claude_args` is the **whole** allow-list for the run; it
replaces the code-review command's own `allowed-tools` rather than adding to it.
The first version listed only the inline-comment tool, so on hub #56 the review
was denied `gh pr view` and `gh pr diff` (it could not read the pull request) and
`gh pr comment` (it could not post its "No issues found" summary). The job went
green with `permission_denials_count: 5` and nothing on the PR. The list now
names every tool that command declares, the test checks it against that list,
and `pull-requests: write` matches Anthropic's own review example. `Skill` is
on the list too, because the prompt is a plugin command and the model loads it
through that tool.

The code-review command does its work through subagents, and agents run in the
background by default. A headless run ends when the model ends its turn, so on
hub #59 the model started its eligibility check in the background, ended its
turn to wait for the result, and the session ended there: four turns, nothing
reviewed, nothing posted, job green. The action step now sets
`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`, which keeps every agent in the
foreground. Twice now a review has posted nothing and still passed, so the job
also checks what actually happened: a last step counts the comments and inline
comments created on the pull request after the review started, and fails,
printing the review's last message, if there are none. That also turns a
deliberate stop red: the command skips a pull request that is closed, a draft,
or already commented on by Claude. That is on purpose, since a review was
requested and none was posted, and the printed message says why.

The action's log shows a trimmed result -- no per-model token counts, and a
denial *count* but not which tools were denied. The full result is written to
`${{ runner.temp }}/claude-execution-output.json` and deleted with the runner, so
the workflow uploads it as the `claude-execution-output` artifact (14 days,
uploaded even when the review fails). It includes the review transcript, visible
to anyone with read access to the repository.

### Tool notifications

The push notifier is installed in all ten tool repositories, keyed to each
one's default branch — `hero-siege-item-editor` is `master`, not `main`.
`HUB_DISPATCH_TOKEN` was configured in all ten on 2026-09-14 and dispatches
were verified. The hub opens pointer-update PRs and automatically merges
validated bumps through `submodule-dispatch.yml`; these push notifications
are operational.

`notify-hub-release.yml` supplies the second notification in each tool
repository: a published stable release sends `release-published`, which
rebuilds the catalog from the latest published release. A manual run from
Actions sends the same notification without creating or editing a release.
Prerelease publication is ignored. Missing credentials fail the notifier
rather than pretending an absent nightly job will recover it.

The two stay separate files rather than one workflow with two jobs. They answer
to different events, they can be adopted independently, and a repository that
wants only the release half should not have to take the push half with it.

`submodule-dispatch.yml` deliberately does **not** accept `release-published`:
it bumps submodule pointers, which is a question about commits.
[`catalog.yml`](../../.github/workflows/catalog.yml) takes that event directly,
and takes `submodule-updated` as well, so one dispatch can have two
consequences.

---

## Verification


```bash
py -3 -m unittest discover -s tests   # catalog generation and signing
cd hub && npm test                    # node --test, then cargo: rows, install, interlocks
cd hub && npm run build               # the frontend
cd hub && npm start                   # the app
```

`tests/install_e2e.rs` drives the whole install pipeline over real HTTP against a
server the test owns, so the loop needs no release and works offline.

### Against the real releases

Ignored by default, because `cargo test` should not download 210 MB on every run.
They exist because the fixtures can only prove the pipeline is self-consistent —
they cannot prove `sources.toml` still describes the releases correctly, and that
is the part most likely to rot.

```bash
cd hub
cargo test --manifest-path src-tauri/Cargo.toml --test real_release -- --ignored --nocapture
```

`forgepact_installs_from_its_real_release` additionally asserts the extracted tree
is `ForgePact.exe` beside `modfiles/{AurieCore,YYToolkit,BloodPactPlugin}.dll` and
`AuriePatcher.exe`, which is what `build_release.py` documents.

Last run: all ten installed, and every entry point was where the catalog said.

### Confirmed by hand

Driven through the real window on 2026-09-12. Recorded because these are the
checks a test cannot make, and because three of them found defects.

| Check | Outcome |
| --- | --- |
| Install ForgePact from its release | Extracted tree matches `build_release.py`; hash pinned in the catalog matched the bytes |
| Launch, health, Running, Stop | `127.0.0.1:8766` answered 200; card tracked state correctly |
| Stop leaves nothing behind | **Found a defect.** See "Stop kills a tree" below |
| Elevation, prompt declined | Reported as a sentence, card returns to Launch |
| Elevation, prompt accepted | Card reads Running against the elevated PID |
| Stop on an elevated tool | Refused by Windows, as it must be; the card no longer offers it |
| A catalog pinning the wrong hash | Install refused, nothing written, both hashes named |
| Work offline | `Check for updates` refused by the Rust guard, not merely a disabled button |
| Verify files | Re-hashed the install against its manifest, offline |
| `kind: "html"` | Opened in the browser rather than spawned |
| Uninstall | Removed, back to *Not installed* |
| Star two tools, unstar one | Cards moved into the *Starred* row and back; `state.json` held exactly the starred ids after each click (2026-09-13) |
| *Join the Discord* | Invite resolves and does not expire (`expires_at: null`); opened through `open_url`, which hands it to the system browser (2026-09-13) |
| Card controls after the move | Heading and `.corner` measured to the same client rect (198.3–218.3), both glyphs centred on it; menu opens downward and paints over the card below it; primary button has the footer to itself (2026-09-13) |
| First canonical installer candidate | Extracted the actual NSIS application, verified its updater signature and manifest, opened it in an isolated WebView2 profile; all ten tools appeared, offline first run and favorites persisted, and the Steam Deck editor installed from its real release (2026-09-15) |
| Manual hub update check after packaging | **Found a defect before publication:** the catalog refreshed but the hub check stayed on `Checking...`. Async Tauri commands nested `block_on` inside the runtime. Converted both updater commands to async/await and bounded the metadata check to 30 seconds. The 1.0.1 candidate resolves a missing release JSON, logs the error, restores the button, and retains the installed tool and favorite after restart (2026-09-15) |

#### Stop kills a tree

Worth keeping because it will recur. The PID the hub spawns is not always the
application: a PyInstaller one-file build runs a bootloader that unpacks itself,
spawns the real program as a child and waits. ForgePact 1.3.16 gave tracked pid
55212 (8 MB bootloader) and pid 15952 (102 MB, the process actually serving
8766). Killing the tracked PID reported success while the window stayed open and
the port kept answering. `stop` now kills the tree children-first.

#### Elevation cannot be tested from a sandbox

The first attempt produced a bare Windows dialog saying "The specified path does
not exist" over a path that plainly did. The cause was not the hub: the dev app
had been started from a sandboxed shell where `%LOCALAPPDATA%\Hero Siege
Toolkit` is a redirect into an app-container LocalCache. The hub installed there;
the elevation broker, running as SYSTEM outside the container, resolved the
literal path and found nothing.

Run the hub from an ordinary terminal when testing elevation. (The dialog itself
was a real defect and is fixed -- `SEE_MASK_FLAG_NO_UI` -- so the failure now
comes back as a value the hub reports and logs.)

### Still blocked

**The game-running interlock.** Auto-download only runs after a successful
remote catalog fetch, and there is no published `catalog` release tag to fetch
from yet, so staging cannot be reached through the interface. The mechanism is
covered by `a_blocked_update_waits_with_its_reason_and_then_applies` in
`tests/install_e2e.rs`; redo it by hand after Phase 4's first publish.

**Rollback through the interface**, for the same reason -- it needs two versions
of a tool, which needs a catalog that offers a second one. Covered by
`an_update_keeps_the_previous_version_and_can_be_rolled_back`.

`tools/freeze_probe.ps1` remains the instrument if a hub-launched tool is ever
suspected of stalling the game.


## Out of scope

No changes to any tool's own UI or behaviour: v1 requires zero commits to the ten
submodules. No monorepo migration (ADR 0001). No code-signing certificate. No
Linux or Steam Deck hub build — the Steam Deck editor stays a browser page the
hub can open.
