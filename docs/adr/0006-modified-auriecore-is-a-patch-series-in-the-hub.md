# ADR 0006 — The modified AurieCore is a patch series in the hub

**Status:** accepted, 2026-10-06
**Supersedes:** nothing. ForgePact shipped Aurie v2.0.2's release
`AurieCore.dll` unmodified until this decision.
**Context:** ForgePact #151 (the start-up hold and the in-play hitch when
hooks install), [`third_party/aurie/`](../../third_party/aurie/README.md),
`ForgePact/docs/setup-stall-research.md` (§ Live 1, the measurement this
decision rests on), and [ADR 0002](0002-modified-yytoolkit-is-a-patch-series-in-the-hub.md),
whose arrangement this one reuses.

---

## The question

Every hook ForgePact installs goes through Aurie's `MmCreateHook`, and
ForgePact #151's Live 1 (2026-10-06) measured what that costs: about 69 ms a
hook, 97.5% of a 1268.7 ms start-up setup that installed 18 hooks, and a
1546.5 ms frame in town when `dropmult relic 2` installed 20 hooks on demand.
Almost all of it is the freeze around the hook write. Read from upstream's own
source (AGPL, not game code), the freeze takes a thread snapshot of the whole
system to suspend the game's threads and a second one to resume them, so its
cost grows with every thread on the machine, not with the game. A system-wide
snapshot measured 32.8 ms (median) in the same session, about half of each
detour.

Two questions follow. Which fix removes that cost without changing how hooks
attach? And if the fix is a change to Aurie, where does the source for the
changed `AurieCore.dll` live, in what form, and how does it reach players?

## The options, and what decided between them

### How to remove the cost

Five routes were compared after Live 1 (forgepact-151-setup-stall, "Fix route
after Live 1"). The owner chose the first.

- **(a) Patch Aurie's freeze so it walks only the game's threads — chosen.**
  It removes the cost at its source, for every hook and every plugin that
  loads through this `AurieCore.dll`, and leaves the plugin untouched:
  `MmCreateHook` keeps its signature and call sites, and the table swap plus
  inline detour stay exactly as they are.
- **(b) Install hooks through a SafetyHook vendored in ForgePact — rejected.**
  It changes how every hook attaches, and Aurie would no longer know about
  the hooks it did not create.
- **(c) Spread installs over several frames — rejected.** It defers hooks past
  calls they must see (`CreateItemNew` before the first item, the save load on
  a slot click), and installing `DropRelic` at character select once stalled
  the runner for a minute.
- **(d) Move item truth's text hooks to the first tooltip — rejected.** It only
  moves a one-second hitch to the first tooltip.
- **(e) Accept the cost — rejected.** It leaves Case C's 1.5 s in-play hitch.

Within (a), the alternatives to a per-process thread walk through
`NtGetNextThread` (resolved by name from ntdll, the way Aurie already resolves
`NtQueryInformationThread`) were:

- **`PssCaptureSnapshot(PSS_CAPTURE_THREADS)`** — documented and per-process,
  but it returns thread ids, so every thread needs `OpenThread` again, and its
  internal cost was not measured. `NtGetNextThread` hands back handles.
- **`NtQuerySystemInformation(SystemProcessInformation)`** — it lists the whole
  system, so it scales the way the snapshot does.
- **Rewriting `ElForEachThread`** — early launch uses it too, so the patch
  would reach beyond hooks.
- **A lock serialising concurrent freezes** — it would fix one hazard upstream
  already has, but it changes blocking for every plugin thread, unmeasured.
  Upstream's behaviour when two threads freeze at once is kept, and listed as
  a known limitation.

### Where the modified source lives

The same three choices ADR 0002 weighed for YYToolkit, and the same reasons
decide them: whole-file copies in a submodule hide the delta, a vendored
upstream tree is large and pushes paths past `MAX_PATH` in a worktree, and a
fork plus an eleventh submodule needs machinery built for tools that publish
releases. A pinned commit plus a patch series keeps each change and its reason
side by side in the hub, beside the rules and the tests that check it.

### How it is built

- **Extend the YYToolkit build tool — chosen.** Every step of
  `tools/build_yytoolkit.py` is independent of the product: exporting the
  pinned commit object, verifying the tree and blobs, proving the whole series
  applies, the `/Brepro` build with a stripped environment, host tests, the
  marker check against pristine upstream, BUILD-INFO and the source zip. Only
  about ten constants differ, so the tool gains a product profile and
  `tools/build_aurie.py` is a thin entry point.
- **Copy the tool — rejected.** A provenance fix to one copy would miss the
  other, which is the failure `third_party/` exists to end.
- **Rename the tool — rejected.** ADR 0002, the guides and the tests name
  `build_yytoolkit.py`.
- **Build AurieCore in ForgePact's CI — rejected.** The toolkit ships the exact
  binary that was launched against the game (`ForgePact/tools/fetch_toolchain.py`).

## Decision

The modified `AurieCore.dll` is **Aurie v2.0.2 (`5c4839e`) plus a patch series**,
kept in the hub under `third_party/aurie/`, under ADR 0002's rules:

| File | What it is |
| --- | --- |
| `upstream.json` | The pin: repository, tag v2.0.2, the full commit and tree ids, and `series_revision` (`hs.1`). The commit id is written there and nowhere else. |
| `patches/*.patch` + `patches/series` | One patch per reason, LF, applied in `series` order, each carrying `Why`, `Evidence`, `Fails-safe`, `Log-markers` and `Upstream-status`. Patch 0001 logs the series identity after Aurie's `loaded at` line; patch 0002 is the per-process freeze, its unit and its host test. |
| `LICENSE`, `NOTICE.md` | Upstream's AGPL-3.0 text byte for byte, and the modification notice. |
| `README.md` | The guide: patch table, how to build, the launch gate, known limitations. |

Rules that follow, in addition to ADR 0002's:

- **The series stays inside `Aurie/`** and never touches the plugin-facing
  `Aurie/source/framework/shared.hpp`, `AuriePatcher/`, `AurieInstaller/` or
  `TestModule/`. Plugins compile against unmodified pinned headers.
- **The patched freeze keeps its contract.** `MmpFreezeCurrentProcess` and
  `MmpResumeCurrentProcess` keep their names, signatures and call sites; no
  exported function changes; the `AURIE_FWK_*` version numbers do not move. It
  resumes exactly the threads it suspended, waits for each suspension to take
  effect, allocates, logs and takes the loader lock only outside the frozen
  window, and falls back to upstream's system-wide walk, with one log line,
  when `NtGetNextThread` cannot be resolved.
- **The build travels as a hub library release**, tag `aurie-v2.0.2-hs.1`,
  created with `--latest=false` (the hub's updater reads the latest release,
  and `hub-v*` is reserved). ForgePact's `tools/toolchain-pins.json` pins its
  `AurieCore.dll` asset, and ForgePact ships `AurieCore-NOTICE.md` and
  `AurieCore-BUILD-INFO.json` beside it from `ForgePact/aurie-modified/`.

`tests/test_aurie_patch_series.py` enforces the series' shape offline;
`tests/test_build_aurie.py` tests the Aurie profile and the shared authoring
path against a synthetic upstream.

## What this gives up

- **Everything ADR 0002 gives up applies here too:** a patch is harder to edit
  than a file, offline tests prove the series well-formed rather than
  compilable, the DLL's hash is meaningful on one toolset, and a build needs
  upstream's source.
- **`NtGetNextThread` is undocumented.** It has been stable since Vista and is
  resolved by name, and the fallback keeps upstream's behaviour when it is
  missing, but a future Windows could change it.
- **Upstream's remaining hazards stay.** Two threads freezing at once, a thread
  suspended while holding the heap or loader lock, a thread suspended inside
  the bytes being overwritten, and threads injected after the last pass are
  all kept as upstream has them, not observed, and listed in the series
  README's Known limitations.

## Consequences

- **Players receive the patched build with ForgePact's next release** (2.2.0)
  and must press Install Mod Plugin once: the launch-time plugin update refuses
  to replace an `AurieCore.dll` that differs from the bundled one.
- **The hub library release has to exist before any ForgePact release**, since
  `fetch_toolchain.py` fetches every pin or none.
- **HS-Offline-Tracker keeps upstream's `AurieCore.dll`.** Its installer leaves
  a copy it does not recognise alone, so it never reverts ForgePact's; a player
  with only the Tracker keeps upstream's freeze cost. Shipping the patched build
  there is a follow-up issue in that repository.
- **Whether the patched build is faster in the game is a measurement, not this
  decision.** The series README's launch gate and
  `ForgePact/docs/setup-stall-research.md` record the live result against
  Live 1's baseline.
- **Offering the patch upstream** to AurieFramework is the owner's call; every
  patch says `Upstream-status: not submitted` until it is.

**Added 2026-10-06.** The hub library release now exists and is published
(`aurie-v2.0.2-hs.1`, `--latest=false`, so the repository's latest release is
still `hub-v1.0.6`), tagged at hub commit `b650302`, the commit its DLL's
BUILD-INFO names. ForgePact's pin resolves against it, so the consequence
above that the release must precede any ForgePact release is met. That is the
library release only: no ForgePact release has shipped the DLL yet, and the
HS-Offline-Tracker follow-up is falorfrozen-cmd/HS-Offline-Tracker#13
(`third_party/aurie/README.md`, "Where the binary is published").
