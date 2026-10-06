# Modified Aurie (patch series)

This directory is the source of the modified `AurieCore.dll` that ForgePact
installs beside its plugin. It holds no Aurie source and no binary - only what
turns upstream into our build. It is kept exactly the way
[`third_party/yytoolkit/`](../yytoolkit/README.md) keeps the modified YYToolkit
([ADR 0002](../../docs/adr/0002-modified-yytoolkit-is-a-patch-series-in-the-hub.md)),
for the reasons [ADR 0006](../../docs/adr/0006-modified-auriecore-is-a-patch-series-in-the-hub.md)
gives.

| Path | What it is |
| --- | --- |
| `upstream.json` | THE pin: upstream repo, tag `v2.0.2`, full commit id, tree id, and `series_revision` (`hs.1`). The commit id lives here and nowhere else. |
| `patches/series` | Patch filenames, one per line, in application order. |
| `patches/*.patch` | One `git format-patch` file per change. Each message carries `Why` / `Evidence` / `Fails-safe` / `Log-markers` / `Upstream-status`. **The patch messages are the primary source; this guide summarises them.** Host tests travel inside the patches under `Aurie/hs-tests/` (1 file). |
| `LICENSE` | Upstream's AGPL-3.0 text, byte for byte (a test pins its git blob id). |
| `NOTICE.md` | The AGPL modification notice that ships beside the binary (as `AurieCore-NOTICE.md` in ForgePact). |
| [`tools/build_aurie.py`](../../tools/build_aurie.py) | Pin + series -> DLL, host tests, marker check, provenance files. An entry point to `tools/build_yytoolkit.py`'s Aurie profile: the same steps, refusals and exit codes. |

> **State on 2026-10-06:** built, host-tested and marker-checked; upstream's
> release DLL fails the marker check, as it should. **Launched against the
> game on 2026-10-06** (Live procedure 1 of workorder
> `forgepact-151-aurie-freeze`, capture
> `.claude/workorders/forgepact-151-aurie-freeze-live-1.md`): every in-game row
> of the [launch gate](#launch-gate) passed, and ForgePact's start-up setup
> measured 47.8 ms against 1268.7 ms with upstream's DLL. ForgePact pins this
> build for its 2.2.0 release; no published ForgePact release carries it yet.

## Why this exists

Every hook ForgePact installs goes through Aurie's `MmCreateHook`, and
ForgePact #151's Live 1 (2026-10-06, `ForgePact/docs/setup-stall-research.md`
§ "Live 1") measured what that costs: a start-up setup of 1268.7 ms of which
1237.0 ms (97.5%) was 18 hook detours, 68.7 ms each, against a median of
32.8 ms for one system-wide thread snapshot timed in the same session; and in
town, `dropmult relic 2` installed 20 hooks and the frame monitor judged a
1546.5 ms frame.

The cost is the freeze around the hook write. Read from upstream's own source
(Aurie is AGPL; this is not game code), `MmpFreezeCurrentProcess` and
`MmpResumeCurrentProcess` each walk `ElForEachThread`, whose
`CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, ...)` ignores its process id and
lists every thread on the machine. Two such walks a hook is about 2 x 33 ms, so
the cost grows with every thread on the system, not with the game. Patch 0002
replaces those walks with one over this process's own threads.

## The patches

| # | Patch | What it changes | Why |
| --- | --- | --- | --- |
| 1 | `0001-series-identity.patch` | One log line after upstream's `loaded at` line names the upstream version and the series revision. | Without it no `aurie.log` tells an upstream build from this one, so a log could not be matched to the source that built the DLL. |
| 2 | `0002-per-process-hook-freeze.patch` | The freeze around every hook write and removal lists this process's threads through `NtGetNextThread`, walks until no new thread appears, waits until each suspension lands, and resumes exactly the threads it suspended. Upstream's walk stays, unchanged, as the fallback. Adds the unit `thread_freeze.cpp`/`.hpp`, its vcxproj lines and the host test. | Upstream's freeze takes two thread snapshots of the whole system per hook: 97.5% of ForgePact's 1268.7 ms start-up setup in Live 1, and a 1546.5 ms frame for 20 on-demand installs. |

### 0001 - series identity

- **Does.** Straight after upstream's `Aurie Core v2.0.2 loaded at <address>`,
  one `LOG_SEVERITY_INFO` line:
  `[hs] Aurie Core 2.0.2, Hero Siege patch series hs.1 (hero-siege-offline-toolkit, third_party/aurie)`.
  The revision is the literal `g_HeroSiegeSeriesRevision` in `AurieMain.cpp`,
  which `tests/test_aurie_patch_series.py` holds equal to `series_revision`.
- **When it does not match.** It cannot: one informational line, written after
  the logger exists and before any module loads.
- **Markers.** `Hero Siege patch series`, `(hero-siege-offline-toolkit, third_party/aurie)`.
- **Measured vs assumed.** The marker check finds both in the built DLL and in
  neither upstream's source nor its release DLL. That the line is written
  where `aurie.log` shows it is NOT RUN (launch gate).

### 0002 - per-process hook freeze

- **Does.** `MmpFreezeCurrentProcess` and `MmpResumeCurrentProcess` keep their
  names, their argument-less `void` signatures and every call site (in
  `MmCreateHook`, `MmCreateUnsafeHook`, `MmCreateMidfunctionHook` and the
  three `MmpRemove*Hook`); their bodies call `HsFreeze::Freeze` and
  `HsFreeze::Resume` in the new unit
  `Aurie/source/framework/Memory Manager/thread_freeze.cpp`, which needs
  Windows SDK headers only, so the host test includes the very file the DLL
  compiles. The freeze:
  1. resolves `NtGetNextThread` from ntdll by name (once, through
     `InitOnceExecuteOnce`) and reserves its handle storage (1024 entries, one
     heap block per call, kept on a thread-local stack so two threads freezing
     at once never share a set) **before** it suspends anything;
  2. walks this process's threads with `NtGetNextThread`, suspending each one
     other than the caller (recognised by thread id) and keeping the handle of
     every thread whose `SuspendThread` succeeded;
  3. calls `GetThreadContext` on each new suspension, which returns only once
     the thread has actually stopped (`SuspendThread` only queues it);
  4. walks again until a pass meets no thread an earlier pass did not, with a
     cap of 8 passes, so a thread started during a pass is caught by the next.
  The resume resumes exactly the handles the freeze kept, once each, closes
  them, and then hands out at most one log line per process. Between the first
  `SuspendThread` and the last `ResumeThread` the pair's own code allocates
  nothing, logs nothing and takes no loader lock.
- **When it does not match.** If `NtGetNextThread` is not exported, no
  thread-local slot or storage can be had, the process has more than 1024
  threads, or `NtGetNextThread` returns an error-severity status before the end
  of the list (a thread it cannot open would hide the ones after it), that call
  gives back what it suspended and runs upstream's walk, moved into the unit
  unchanged. The first such call writes, after its threads are resumed,
  `[hs] MmCreateHook freeze: FELL BACK to the system-wide thread snapshot: <reason>`.
  The first per-process freeze writes
  `[hs] MmCreateHook freeze: per-process thread walk, first freeze suspended N thread(s) in P pass(es), K not suspendable`.
- **Markers.** `MmCreateHook freeze: per-process thread walk`,
  `FELL BACK to the system-wide thread snapshot`.
- **Measured vs assumed.** The host test below, on the build machine. In the
  game, measured on 2026-10-06 (launch gate): the first freeze suspended
  N = 4 threads in 2 passes, 0 not suspendable, and a detour cost 1.56 ms
  against upstream's 68.7 ms. How many threads each later freeze suspends is
  not logged, so not observed. The fallback is compiled and
  marker-checked, but no host test forces it: the test can neither unexport
  `NtGetNextThread` nor deny the process access to its own thread.

#### The host test, `Aurie/hs-tests/thread_freeze_test.cpp`

One executable runs both walks of the unit against the same threads: 4 workers
that each spin on a counter of their own, and a child process (the same
executable, relaunched with `--child`) holding 1100 idle threads, so the
system's thread count rises while this process's own does not. It reads suspend
counts from what `SuspendThread` and `ResumeThread` return and ends the child it
started. A seam compiled only into the host test (`AURIE_HS_FREEZE_TEST_SEAM`)
starts a thread between two passes.

| Case | Expects | Upstream's walk only | Per-process walk |
| --- | --- | --- | --- |
| `baseline-suspends-others` | every worker counter stops while frozen, moves again after resume | pass | pass |
| `baseline-scales-with-system` | the snapshot walk visits at least the child's 1100 entries | pass (7352 entries) | pass |
| `baseline-resumes-unseen` | a thread created `CREATE_SUSPENDED` inside the window ends with suspend count 0 (upstream starts it) | pass | pass |
| `baseline-misses-late-thread` | a thread started between passes is still running when the freeze returns | pass | pass |
| `target-suspends-others` | as the baseline, through the per-process route, and a worker the test suspended beforehand is suspended exactly once after resume | FAIL (route not per-process) | pass |
| `target-own-threads-only` | entries visited equal this process's thread count; the child makes no difference | FAIL (0 visited) | pass (8 of 8) |
| `target-leaves-unseen` | that `CREATE_SUSPENDED` thread keeps suspend count 1 | FAIL (0) | pass |
| `target-catches-late-thread` | the thread started between passes is suspended when the freeze returns | FAIL (running) | pass |
| `target-cost` | over 9 runs with the child running, the per-process freeze+resume median is under a fifth of the snapshot median | FAIL (122.7 against 126.2 ms) | pass (0.211 against 125.5 ms) |
| `target-logs-once` | the first per-process freeze hands out the `per-process thread walk` line, once | FAIL (no line) | pass |

The "upstream's walk only" column is the red run the plan asked for before the
per-process walk existed: the same test compiled against the unit with
`Freeze`/`Resume` bound to upstream's walk, 2026-10-06, 4 of 10 passed. The
last column is `hosttests` on the build below, 2026-10-06, 10 of 10. Over the
three runs that day the snapshot pair's median was 118 to 126 ms and the
per-process pair's 0.21 ms; both are one machine's, with about 7,300 to 7,700
threads on the system.

## How to build

Prerequisites: Windows; Visual Studio 2022 (17.x, Build Tools is enough) with
the C++ x64 tools component and a Windows SDK; git on `PATH`; Python 3 (stdlib
only); either network access or a local clone of upstream that contains the
pinned commit.

```bat
py -3 tools/build_aurie.py all --allow-network
py -3 tools/build_aurie.py all --upstream C:\src\Aurie
```

`all` runs `materialise`, `apply`, `build`, `hosttests`, `verify-dll`; each is
also a command of its own. Everything `third_party/yytoolkit/README.md` § "How
to build" says about the tool holds here, with the Aurie profile's values:

- **Work directory** `%LOCALAPPDATA%\hstk\au` (falling back to
  `%SystemDrive%\hstk\au`), short, outside the repository, marked
  `.hstk-aurie-work`.
- **The build is upstream's own `Aurie/AurieCore.vcxproj`, Release x64,
  unedited** apart from the series. `/Brepro`, `/PDBALTPATH` and
  `/d1trimfile:<project dir>` arrive through an injected props file: upstream's
  project does not trim `__FILE__`, and the work directory sits under the
  builder's profile, so without it a path naming them would be compiled in.
  The DLL holds no `\Users\` path (checked on the build below).
- **Runtime.** Like upstream's release, the build links against
  `MSVCP140`/`VCRUNTIME140` (`MultiThreadedDLL`).
- **`verify-dll`** requires every `Log-markers:` literal in the DLL as ASCII
  and absent from unpatched upstream. `verify-dll --dll <file>` checks any
  binary read-only.

Expected result for `hs.1`: **968,704 bytes, sha256
`3cf98af99a0ef38dea1a2d4627e6466631f6e7dd2b254b1a80e5438ac06800cb`**, 1 of 1
host test files passing, 4 markers. That hash is only meaningful on the toolset
that produced it - VS 2022 Build Tools 17.14, `VCToolsVersion` 14.44.35207,
Windows SDK 10.0.26100.0. On another toolset expect another hash; compare the
`toolchain` block of the two BUILD-INFO files, and rely on the host test and
the marker check. `--expected-sha256` enforces a hash when you want it
enforced. The DLL's bytes depend on the pin and the patches, not on this README
or the hub commit, so the clean build a release is made from reproduces it.

Outputs, all in `<work>\o\` (the tool never copies the DLL anywhere else):
`AurieCore.dll` and `AurieCore.dll.sha256`; `AurieCore-BUILD-INFO.json`, the
provenance record (upstream pin, hub commit and whether this directory was
dirty, per-patch sha256 and markers, toolchain, DLL size and hash, host-test
results, the source zip's id; `live_gameplay_verified` is always `false`); and
`aurie-source-<12 hex>.zip`, a deterministic zip of this directory.

## Launch gate

| Step | How | Result | Status | Date |
| --- | --- | --- | --- | --- |
| Build | `build_aurie.py all --allow-network` on the toolset above, twice: from the uncommitted working tree (`patch_directory_dirty: true`), then from the committed series (`false`) | 968,704 bytes and the sha256 under [How to build](#how-to-build) both times, so the build reproduces; `warnings: 0` | Verified | 2026-10-06 |
| Host test, red | the host test against the unit holding upstream's walk only | 4 baseline cases pass, all 6 target cases fail | Verified | 2026-10-06 |
| Host test | `hosttests` step | 1 of 1 files, 10 of 10 cases | Verified | 2026-10-06 |
| Marker check | `verify-dll` step | 4 markers in the DLL, none in unpatched upstream | Verified | 2026-10-06 |
| Marker check, negative control | `verify-dll --dll ForgePact/modfiles_shipped/AurieCore.dll` (upstream's v2.0.2 release, 967,680 bytes, sha256 `18e3a1de980f487a6b3858b673d2030e96984dd96de3a047b43a263a5ba829ae`) | Exit 1, naming all 4 markers as NOT in the DLL | Verified | 2026-10-06 |
| Identity and freeze lines in `aurie.log`, and the freeze suspended threads in the game | Live procedure 1, step 3: the identity line, the `per-process thread walk` line and no `FELL BACK` line (live check `marker`). Parse N, P and K from `first freeze suspended N thread(s) in P pass(es), K not suspendable`, and record N beside the game's thread count from the same session, `(Get-Process Hero_Siege).Threads.Count` at `plugin_ready`. The first freeze may come from an early YYToolkit or Aurie hook, while the game has fewer threads than at `plugin_ready`, so N is recorded beside that count, not required to equal it less one | Measured: both `[hs]` lines, no `FELL BACK`; N = 4, P = 2, K = 0 beside 77 threads at `plugin_ready` (the first freeze runs before YYToolkit is mapped). The required live check `freeze-suspends` decides this row: it passes only with N >= 1, and N = 0 fails it, because the freeze would have reported itself armed while the game's threads kept running as SafetyHook rewrote the bytes. `marker` checks only the lines | Verified | 2026-10-06 |
| Hooks attach as before (18 at the setup, 20 on demand, no `TABLE-ONLY`) | Live procedure 1, steps 2 and 6 (live check `hooks-attach`) | Measured: Live 1's 18 hooks at the setup and 20 on demand by name, no `TABLE-ONLY` line in the session, `untagged 0` | Verified | 2026-10-06 |
| Case A: start-up setup cost against Live 1 (detour ms per hook at most a quarter of the snapshot median) | Live procedure 1, steps 2 and 4 (live check `setup-detour`). A fast detour counts only with `freeze-suspends` passing (N >= 1), because a freeze that suspended nothing would also be fast; with `freeze-suspends` failed, `setup-detour` fails too | Measured with `freeze-suspends` passing: `installs 18, detours 18`, detour 28.1 ms, 1.56 ms a hook against a 37.9 ms snapshot median (0.041x; Live 1 2.10x, 68.7 ms a hook). Setup 47.8 ms, `hooks` 47.4 ms (Live 1: 1268.7 / 1268.3 ms) | Verified | 2026-10-06 |
| Case C: 20 on-demand installs in town (`ipc` worst under 250 ms) | Live procedure 1, steps 5 to 7 (live check `on-demand`) | Measured: detours 19 -> 39, 35.0 ms for the 20; `ipc` worst 122.12 ms (Live 1: 1542.58 ms); `reports written 0` (Live 1: 1) | Verified | 2026-10-06 |
| Clean exit | Live procedure 1, step 8 (live check `clean-exit`) | Measured: the process exited without force; `out.txt` ended `==== clean shutdown ====` | Verified | 2026-10-06 |

The in-game rows ran against the DLL of sha256 `3cf98af9...ac06800cb` (the
`hs.1` build above; live check `aurie-hash`) and ForgePact's ship plugin of
Live 1, unchanged (`dll-hash`). The kept capture is
`.claude/workorders/forgepact-151-aurie-freeze-live-1.md` in the hub (a local
workorder file, not committed); `ForgePact/docs/setup-stall-research.md`
§ "Live 2" records it. Case B (item truth off) is not run, by the owner's
choice, and the fallback path did not run in the game (no `FELL BACK` line), so
both are not observed. A new series revision resets these rows to NOT RUN. The
live procedure installs `<work>\o\AurieCore.dll` over the game's
`AurieCore.dll` (ForgePact's Install Mod Plugin path), keeping upstream's copy
aside; the first `[hs]` line of `aurie.log`, not the file date, says which DLL
ran.

## How to change the series

The procedure is `third_party/yytoolkit/README.md` § "How to change the
series", with `tools/build_aurie.py` for the tool and these values:

1. A new change is a new numbered patch, the last line of `patches/series`.
2. Generate it with the authoring path, never by hand:

   ```bash
   py -3 tools/build_aurie.py materialise --allow-network
   py -3 tools/build_aurie.py overlay --overlay build/aurie-overlay "Aurie/source/framework/Memory Manager/memory.cpp"
   # edit the copies under build/aurie-overlay/ (create new files there too)
   py -3 tools/build_aurie.py make-patch --overlay build/aurie-overlay --name NNNN-<slug>.patch --message <file>
   ```

   `--regenerate-last` rewrites the last patch from the overlay instead. Every
   path stays under `Aurie/`; the tool refuses
   `Aurie/source/framework/shared.hpp`, which ForgePact compiles against
   unmodified.
3. The message carries `Why:`, `Evidence:`, `Fails-safe:`, `Log-markers:` and
   `Upstream-status:`.
4. Host tests go inside the patch, under `Aurie/hs-tests/`, and are never
   added to the vcxproj.
5. Document it in the same change: a row in the patch table, a section, a
   launch-gate row, and an entry in `NOTICE.md`.
6. Bump `series_revision` in `upstream.json` AND `g_HeroSiegeSeriesRevision`
   in patch 0001, the same string in both. Changing an existing patch is a
   revision bump too.
7. Rebuild with `all`, update the expected size and hash here, and reset the
   in-game launch rows to NOT RUN.

`tests/test_aurie_patch_series.py` enforces the mechanical part of this list
offline. With `HSTK_AURIE_UPSTREAM` set to a local clone that contains the
pinned commit, it also exports the pin and applies the series for real through
the build tool; without it that one test skips and says so.

## Known limitations and what is not measured

Kept from upstream, unchanged, and **not observed** in this toolkit:

- **Two threads freezing at once can suspend each other.** Each freeze has its
  own set, so the sets are never corrupted, but thread A can suspend thread B
  in the middle of B's own freeze, and the patch adds no lock (a lock a frozen
  thread could hold would be worse). ForgePact installs and removes hooks from
  its frame thread only.
- **A thread suspended while it holds the heap lock or the loader lock** stalls
  the caller if SafetyHook's `create_rp` then allocates or loads. The freeze's
  own code does neither inside the window; SafetyHook's is upstream's.
- **A thread suspended with its instruction pointer inside the bytes being
  overwritten** resumes into the middle of the new instruction. SafetyHook's
  `trap_threads` moves only a thread that faults on the page.
- **Threads another process injects** into the game after the last pass are not
  suspended.
- **`NtGetNextThread` is undocumented.** It has been exported by ntdll since
  Windows Vista and is resolved by name; if it is missing, the fallback runs
  upstream's walk and says so.

Added or narrowed by this patch:

- **The fallback is upstream's walk**, cost and gaps included: its resume
  snapshot is taken while the process is frozen, and it resumes every thread
  of the process, as upstream does.
- **Thread identity is by id.** A thread that exits during the freeze and whose
  id is reused by a new thread within the same freeze would be taken for the
  old one and not suspended. Not observed; the window is a few milliseconds.
- **The pass cap is 8.** A process that keeps creating threads from another
  thread faster than one pass completes ends the freeze with the newest
  threads running, as upstream always does.
- **The host test's numbers are one machine's.** The red and green runs were on
  the build machine, about 7,300 threads on the system. The cost in the game is
  the launch gate's, measured on one machine in one session (2026-10-06,
  about 6,660 threads on the system, 77 in the game).
- **HS-Offline-Tracker keeps upstream's `AurieCore.dll`.** A player with only
  the Tracker keeps upstream's freeze cost; shipping this build there is a
  follow-up in that repository.

## Where the binary is published

As a hub library release, tag `aurie-v2.0.2-hs.1`, titled `Modified Aurie
2.0.2, series hs.1 (library release - not a hub build)`, never marked latest
(the hub's updater reads the latest release, and `hub-v*` is reserved). Its
assets are the DLL, its `.sha256`, `AurieCore-BUILD-INFO.json`, the source zip
and `NOTICE.md`. ForgePact's `tools/toolchain-pins.json` pins the DLL at
`https://github.com/falorfrozen-cmd/hero-siege-offline-toolkit/releases/download/aurie-v2.0.2-hs.1/AurieCore.dll`.
**Not yet published** on 2026-10-06: the launch gate passed that day, and
publishing is a separate step.
