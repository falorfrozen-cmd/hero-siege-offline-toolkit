# Modified YYToolkit (patch series)

This directory is the source of the modified `YYToolkit.dll` that ForgePact and
HS-Offline-Tracker install beside their Aurie plugins. It holds no YYToolkit
source and no binary - only what turns upstream into our build:

| Path | What it is |
| --- | --- |
| `upstream.json` | THE pin: upstream repo, tag `v4.0.1`, full commit id, tree id, and `series_revision` (`hs.1`). The commit id lives here and nowhere else. |
| `patches/series` | Patch filenames, one per line, in application order. |
| `patches/*.patch` | One `git format-patch` file per change. Each message carries `Why` / `Evidence` / `Fails-safe` / `Log-markers` / `Upstream-status`. **The patch messages are the primary source; this guide summarises them.** Host tests travel inside the patches under `YYToolkit/hs-tests/` (7 files). |
| `LICENSE` | Upstream's AGPL-3.0 text, byte for byte (a test pins its git blob id). |
| `NOTICE.md` | The AGPL modification notice that ships beside the binary. |
| [`tools/build_yytoolkit.py`](../../tools/build_yytoolkit.py) | Pin + series -> DLL, host tests, marker check, provenance files. |

> **State on 2026-09-19:** built, host-tested, marker-checked, and now
> **launched once against the game** - YYToolkit alone (no ForgePact or
> Tracker plugin loaded), one session, menu plus about two minutes in Chaos
> Tower. The startup crash did not reproduce on this build and this machine,
> and lag was not observed either; see the [launch gate](#launch-gate) for
> exactly what that one session does and does not cover (a plugin loaded, the
> no-hint-file path and the verbose-dump control are all still open). Players
> still receive the previous DLL until the [follow-ups](#follow-ups-in-the-submodule-repos) land.

## Why this exists

From ForgePact v1.3.1 to v1.3.16, and in HS-Offline-Tracker's `aurie-loader/`,
the toolkit distributed one modified `YYToolkit.dll` (904,192 bytes, sha256
`bb113eefc9a5d485231ced1dc85d773dbc6b762ee680214851c56541359ad297`). Its notice
listed two changes and called everything else unmodified upstream. The binary's
own strings say otherwise: a candidate filter in the functions-array finder, a
startup breadcrumb tracer writing to a hardcoded absolute path under the
builder's user profile, a `VirtualQuery` import with no caller in the documented
source, and a page pre-filter that was in the committed file but never listed.
Its import table also shows a build without `UNICODE` (it imports
`SetWindowLongPtrA`; upstream's project is Unicode), and an absolute `__FILE__`
string under the builder's user profile names the source directory that was
not kept - neither was in the notice.
The source for those changes is lost, and a fresh build of the *documented*
source crashes during startup on Hero Siege (likely in
`YkDetermineFunctionEntrySize`; inferred from where the log stops, no dump
exists). A patch series is the list of changes, one file per reason, and the
build tool fails any DLL that does not contain what the series documents.
`NOTICE.md` has the full statement about the previous binary.

## The patches

| # | Patch | What it changes | Why |
| --- | --- | --- | --- |
| 1 | `0001-runner-interface-scan-hint.patch` | Ranks `.text` pages with a byte-level lea/mov-to-stack density pass so upstream's unchanged page scan visits likely pages first. `<exe>.yytkcache` becomes a hint for which two pages to scan first; the hook address always comes from the scan, never from disk. | Upstream disassembles `.text` page by page from the start on every launch until it reaches the chain, which on this game sits about 190 MB into the image (RVA 0xB5557E2; the section size itself was not read). The previous DLL skipped that by hooking at an address read from a file it checked only by exe size. |
| 2 | `0002-runner-interface-quiet-init-dump.patch` | The runner-interface hook's register / instruction / stack dump is written only with `YYTK_RI_VERBOSE=1`; otherwise one `RI init summary:` line. | The dump is 723 of the 736 lines in the measured log - nearly the whole log a player attaches. Log noise only; no performance claim. |
| 3 | `0003-executeit-hook-off-by-design.patch` | The ExecuteIt detour is a named build switch (`YYTK_HOOK_EXECUTEIT`, default 0). Init says so in one line, `CreateCallback(EVENT_OBJECT_CALL)` is refused with `AURIE_UNAVAILABLE`, and a failed ExecuteIt lookup no longer aborts stage 1. | No plugin in this toolkit consumes the event, and project notes record the hook crash-looping on Season 10 (not re-measured). Before, the off state was invisible: registration succeeded for a callback that could never fire. |
| 4 | `0004-functions-array-validation.patch` | Every RIP-relative `mov r64, [mem]` candidate in `Code_Function_Find` is validated before it is trusted as the functions array, in both the YYC and the VM finder; `YkDetermineFunctionEntrySize` reads through guarded copies and says which check refused. | A fresh build of v4.0.1 plus the two previously documented files dies in stage 2 on Hero Siege. Likely cause, inferred from where the log stops (no dump exists): upstream takes the first matching mov unvalidated and dereferences it unguarded. The previous DLL had a filter for this whose source is lost; this is an original re-implementation. |
| 5 | `0005-yyerror-report-once-and-measure.patch` | `HkYYError` builds the game symbol table once and keeps it, gives each distinct message one full report, counts repeats on a count-only path, writes cost and summary lines, and forwards to the runner as `("%s", text)`. | The game raises caught errors by the hundred per session; upstream answers each with a full stack-trace report and rebuilds a map of every script and builtin per game frame of each trace. Certain from source; magnitude not measured. |
| 6 | `0006-release-build-optimised-and-series-identity.patch` | The Release x64 configuration compiles with `MaxSpeed`, whole-program optimisation off and the exception model stated; the first line of `YYToolkit.log` names the build and the series revision. | Upstream's Release x64 has optimisation disabled. The previous DLL was likely a plain `cl /O2` build, which its notice never recorded, and no log could be matched to a source. |
| 7 | `0007-runner-interface-refuse-unfound-interface.patch` | The runner-interface hook checks every emulated store and the final copy against its private stack buffer, and publishes the interface only if the walk ended on the closing lea, the interface lies inside the buffer and no store was refused. Otherwise it logs one `REFUSED to publish the runner interface` line and stage 2 fails with a status. | Upstream writes each store wherever the instruction's displacement points and copies the interface from offset 0 even when the walk never found it - a heap write outside the buffer followed by calls through whatever bytes were there. Found by review of 0002. |

### 0001 - runner interface: rank pages, keep a scan hint

- **Does.** A byte pass ranks up to 64 pages; upstream's page scan visits those
  first and every other page after, each once, in address order. The hint line
  is `<exe size> <hook rva> <chain rva>` plus, in the new form,
  `<TimeDateStamp> <SizeOfImage> <CheckSum>` from the mapped headers (the file
  is never hashed). The hook RVA is written so legacy readers still parse the
  line and is used only to compare a stored line with a fresh one; it is never
  turned into an address. Only the chain RVA is used, to pick the pages scanned
  first: the hinted page and the page before it. The legacy three-number line
  that ForgePact's panel pre-seeds stays readable. Also guards an upstream
  `(iterator - 1)` dereference and sets `m_RunnerInterfaceBase` before the hook
  can fire.
- **When it does not match.** Nothing read from the file can place the hook.
  Garbage, overlong, signed, hex or truncated lines, or an RVA outside `.text`:
  one `RI scan hint miss` line, then the ranked scan. A key mismatch is only
  logged; the hinted pages are still tried. A wrong hint costs two pages of
  disassembly. Pages the ranker misses are still scanned. If the PE headers
  cannot be queried or `.text` is not committed, readable memory end to end,
  hint and pre-filter are refused with one line and upstream's order runs. A
  hook that cannot be created on a hinted page returns its status at once.
- **Markers.** `RI scan hint hit|miss|key mismatch|refused|written|not written|unchanged|hook failed`,
  `RI pre-filter ranked|hit|miss`, `RI scan found no chain`.
- **Measured vs assumed.** Host tests `ri_scan_test.cpp` (166 checks, also under
  ASan) and `ri_memory_test.cpp` (42 checks against real `VirtualAlloc`
  regions); 12 single-line mutations each fail a check. Not measured: scan
  duration with or without the pre-filter, whether the ranker puts this game's
  chain page among its 64, whether any build's chain crosses a page boundary
  (the page-before rule is reasoned), whether Aurie's `MmCreateMidfunctionHook`
  validates its target. Residual: visiting pages in another order changes which
  site wins if more than one passes upstream's lea test (upstream's own TODO);
  and because the line stays legacy-compatible, the previous DLL - which does
  trust the hook RVA - keeps trusting it for as long as that DLL is installed.

### 0002 - runner interface: quiet init dump

- **Does.** Gates upstream's dump on `YYTK_RI_VERBOSE=1` (blanks and tabs around
  the value ignored, because cmd's `set X=1 && game` stores `1 `). The summary
  line is always written: instruction count, emulated stores, stack rows and how
  many are non-zero, interface offset, whether the chain ended where it should,
  and which of three answers the environment gave (not set / set but not 1 / 1)
  with the value's length.
- **When it does not match.** Unset, empty, any other or an overlong value
  leaves the dump off, and the summary tells those cases apart. A chain that did
  not end on the rsp-relative lea is named in the summary. What the hook
  emulates and copies is unchanged by this patch; only what it logs. Acting on
  a walk that did not find the chain end is a second reason, so it is its own
  patch: 0007.
- **Markers.** `RI init summary:`, `YYTK_RI_VERBOSE is`, `the dump stays off`.
- **Measured vs assumed.** `ri_dump_test.cpp` (39 checks, also under ASan; 4
  mutations each fail). The expected numbers (202 instructions, 100 stores, 512
  rows of which 25 non-zero, `rsp+0x60`) are counted from one measured log, not
  seen live. Not measured: whether the launcher hands its environment on to the
  game.

### 0003 - ExecuteIt hook off by design

- **Does.** `YYTK_HOOK_EXECUTEIT` (default 0) lives in the DLL-private
  `ObjectCallGate.hpp`. A runtime flag is raised only beside a successful
  `MmCreateHook`. Refusals are logged for the first 8, then stop; the counter
  sticks at its maximum instead of wrapping.
- **When it does not match.** The flag defaults to false, so every failure mode
  refuses the registration instead of accepting a dead callback. A failed
  ExecuteIt lookup leaves `m_CodeExecute` null and the init line says crash-report
  frames may be mislabelled. An unresolvable owner prints `<unknown>`; the
  plugin-supplied module pointer is never dereferenced. A third-party plugin
  that treats the refusal as fatal now fails to load where it used to load and
  do nothing - intended, and logged.
- **Markers.** `ExecuteIt hook NOT installed by design`, `REFUSED EVENT_OBJECT_CALL`,
  `further refusals will not be logged`, `crash-report frames may be mislabelled Code_Execute`.
- **Measured vs assumed.** Builds with the switch at 0 and at 1;
  `ObjectCallGateTest.cpp` passes 45 checks and fails 7 under an off-by-one
  mutation. **Not observed either way:** whether the hook is harmful on Season
  10. The previous notice's reason (the hook corrupting instance references and
  causing `Unable to find any instance for object index`) is contradicted by
  ForgePact's own notes, which record the same error with the hook removed. With
  the switch at 1, upstream's `FWCodeEvent` parameter-order mismatch returns; do
  not consume the event without fixing that first. The shared plugin headers are
  untouched, so their `CreateCallback` comment does not list `AURIE_UNAVAILABLE`;
  this guide does.

### 0004 - functions array validation

- **Does.** A candidate is accepted only if it lies in the game image and holds
  an aligned pointer, its first 8 entries parse under ONE layout (24-byte
  referential or 80-byte embedded) with a terminated graphic-ASCII name and a
  routine that is executable game-image code, and the game's own
  `Code_Function_Find` agrees on at least one of those names and contradicts
  none. Each distinct candidate is looked at once; both finders share
  `GmpiSelectFunctionsArray`. The scan window grows from 0x200 to at most 0x400
  bytes, clamped to readable memory. The x86 variant is left as upstream.
- **When it does not match.** One rejection line per distinct candidate with its
  reason, one summary line, `AURIE_OBJECT_NOT_FOUND`, OUT parameter untouched.
  The VM fallback rejects the same candidates under its own prefix and init ends
  with `Failed to determine function array size!` - a refusal, not a fault.
  Every validator read is a `VirtualQuery` region walk followed by
  `ReadProcessMemory` on the current process; guard pages are refused untouched.
  A failed search is run at most 3 times in total (the repeats are announced as
  `Functions array search attempt 2` and `attempt 3`). After that, each further
  stage-2 entry logs one `Functions array search not repeated` line.
- **Markers.** `GmpFindFunctionsArrayX64()` / `VM::GmpFindFunctionsArray()` +
  `rejected candidate`, `accepted candidate`, `=> none of`, `refused to disassemble`
  (VM also `=> no candidate in`); `YkDetermineFunctionEntrySize() refused`,
  `names confirmed by Code_Function_Find`, `Functions array search attempt`,
  `Functions array search not repeated`.
- **Measured vs assumed.** `fnarray_validation_test.cpp` (118 checks; 16
  mutations of the selector each fail; a vtable-bearing object and a struct that
  starts like one entry are both rejected). For the validator itself, 11 of 12
  mutations fail a check; the twelfth - removing the `VirtualQuery` pre-check in
  front of `ReadProcessMemory` - changes nothing observable on the build host
  and survives, so that pre-check is belt and braces, not tested behaviour.
  Which instructions become candidates was verified by reading only (the patch
  message: it needs Zydis). The fault site was **inferred** from the log
  before the first launch. **Measured on the first launch (2026-09-19):** on
  this exe, `GmpFindFunctionsArrayX64()` rejected three candidates before
  accepting the fourth - not the four rejections the previous binary's notes
  assumed - and the first rejection ("global does not hold an aligned
  pointer") named the same candidate the earlier crashing fresh build had
  accepted as the functions array, which turns the fault site from *inferred*
  to **observed on this build**. See
  [First launch results](#first-launch-results-2026-09-19); addresses
  themselves are not repeated in docs, only the reasons and counts, per
  ["Never Call an Address You Resolved by Hand"](../../AGENTS.md#never-call-an-address-you-resolved-by-hand).
  Still unknown: whether the real mov is inside the disassembly window on a
  different exe. Assumed: the first 8 builtins all have a routine inside the
  game image. The other stage 2 finders use the same first-match heuristic,
  unvalidated - unlike the functions-array finder, 0004 does not check their
  output. The crashing fresh build never reached them; this launch's stage 2
  did, for the first time, and every one of them (`code_is_compiled`,
  `GmpGetBuiltinInformation`, `GmpFindRVArrayOffset`, `GmpFindScriptData`,
  `GmpFindRoomData`, `GmpFindCurrentRoomData`) reported `AURIE_SUCCESS`. That
  they succeeded is measured; whether each picked the *right* candidate the
  same fragile, unvalidated way is not - nothing checked their output the way
  0004 checks the functions array.

### 0005 - HkYYError: report once, count repeats, measure

- **Does.** `GmPrepareGameSymbolTable` builds the table once (at most 2
  attempts, each in a different report; builtin walk capped at 0x10000 slots,
  each slot judged from its own two pointers BEFORE its name is read). A fixed
  ledger of 32 messages plus one overflow slot gives a message's first sighting
  one full report, written verbatim through `CmWriteLogOutputRaw`; a repeat is
  one pass over the text and at most 32 compares - no stack trace, no symbol
  lookup, no file write. With all 32 records in use, a new message is still
  reported from the overflow slot, but at most once per 30 s, so a first
  sighting can then be counted without a report. A record is marked reported
  only after the log accepted the report; a failed report is retried once and
  then counted under `report_failures=`. Messages match after runs of digits
  fold to `#`. The original `YYError` is called on every path, last. The `YYToolkit is loaded...`
  banner is appended only on the call that really wrote a report.
- **When it does not match.** No functions array: the builtin walk is skipped
  and the build line says so. A slot whose name pointer is outside the image
  ends the walk unread with one line. A table that cannot be built logs the
  reason and what was supplied; the report is still written with the C++
  runtime's frame descriptions. The ledger gate is a bounded spin, never an OS
  lock; a caller that cannot get in takes the count-only path (`busy=`). No
  trampoline: the error is counted (`dropped=`) and dropped with one line, where
  upstream would call a null pointer. Nothing diagnostic can stop the forward.
- **Markers.** All start `[hs] `: `YYError summary: total=`, `YYError report cost`,
  `YYError hook install`, `YYError report #`, `YYError summary unavailable`,
  `YYError: Aurie returned no trampoline`, `YYError message truncated`,
  `YYError message not expanded`, `game symbol table: built in|build attempt|builtin walk stopped at slot|given up`.
- **Measured vs assumed.** `yyerror_ledger_test.cpp` (94 checks) and
  `game_symbol_walk_test.cpp` (36 checks); 20 header mutations each fail.
  Reported from another session, not re-measured: about 142 full reports in
  about two minutes of play on the previous DLL. **Measured on the first
  launch (2026-09-19, YYToolkit alone), for one distinct message:** the game
  symbol table built once in 6.189 ms; the one full report cost 527.383 ms
  total, of which game-symbol resolution was 0.018 ms and symbolising
  YYToolkit's own (non-game) stack frames was 520.868 ms; the other 132
  repeats of that message cost 0.252 ms combined. `returned=0` and
  `dropped=0` together indicate the runner's `YYError` left by unwinding
  rather than returning, on every one of those 133 calls in this session (see
  [First launch results](#first-launch-results-2026-09-19)). **Still not
  measured:** the cost of a *second* distinct message in the same session (none
  was raised), and whether the reports are what made the previous DLL lag -
  this session did not lag with a similar error count, which is consistent
  with but does not prove that. Known limitation: a fatal error whose text was
  already reported shows no banner and gets no fresh stack trace. Inherited:
  the slot itself is still read unchecked, and logging stays as
  thread-unsafe as upstream.

### 0006 - Release build optimised, series identity

- **Does.** `Optimization=MaxSpeed`, `WholeProgramOptimization=false`,
  `ExceptionHandling=Sync` for Release x64, and one log line:
  `[hs] YYToolkit 4.0.1, Hero Siege patch series hs.1 (hero-siege-offline-toolkit, third_party/yytoolkit)`.
- **When it does not match.** A build-configuration change cannot fall back at
  run time. If the optimised build misbehaves, drop this patch from the series:
  per its message, every other patch builds and passes its host tests at
  upstream's setting too.
- **Markers.** `Hero Siege patch series`.
- **Measured vs assumed.** A plain `cl /O2` build of the previously documented
  tree is 894,976 bytes against the distributed 904,192; without `/O2` it is
  1,180,160. Not known: why upstream turned optimisation off. No frame-time
  effect of the optimisation level has been isolated on its own. The exception
  model is stated because `HkYYError`'s frame holds C++ objects that rely on
  it **if** the runner's `YYError` leaves by unwinding - 0005's `returned=` /
  `dropped=` counters are what the first launch reads it from, and on the
  first launch (2026-09-19) both stayed at 0 across all 133 caught errors in
  the session: `dropped=0` means a trampoline was present and `YYError` was
  called every time, `returned=0` means none of those calls came back to the
  hook, so in this one session the runner's `YYError` left by unwinding, not
  by returning. See [First launch results](#first-launch-results-2026-09-19)
  for the reasoning; this is one session's reading, not a verified general
  fact about the runner.

### 0007 - runner interface: refuse an interface the walk did not find

- **Does.** The hook replays the game's interface-construction chain into a
  private 4-page copy of the stack. Each store and the final copy are now
  checked against that buffer (`RiScan::IsInsideBuffer`), and the interface is
  published only if the walk ended on the rsp-relative lea, the interface lies
  inside the buffer and no store of the chain was refused.
- **When it does not match.** `m_RunnerInterface` stays zeroed, one
  `REFUSED to publish the runner interface: <which condition>` line is written,
  and the waiting stage 2 is still signalled - it then fails with a status,
  because both functions-array finders return `AURIE_MODULE_INTERNAL_ERROR` on
  a null `Code_Function_Find`. The `RI init summary:` line gains the
  refused-store count.
- **Markers.** `REFUSED to publish the runner interface`.
- **Measured vs assumed.** The frame measured on Hero Siege (rsp = rbp - 0x100,
  stores from `rsp+0x60` to `rbp+0x248`) fits with room to spare, so on that
  build only the summary line changes. `ri_dump_test.cpp` gains 16 checks of
  the bounds predicate (55 in total) with the measured offsets as the positive
  control. That a refusal ends in a status rather than a fault is read from
  source; the one launch so far (2026-09-19: `0 refused`, no `REFUSED` line)
  did not produce a refusal either, so it is still **not observed**.

## How to build

Prerequisites: Windows; Visual Studio 2022 (17.x, Build Tools is enough) with
the C++ x64 tools component and a Windows SDK; git on `PATH`; Python 3 (stdlib
only); a local clone of upstream that contains the pinned commit.

```bat
py -3 tools/build_yytoolkit.py all --upstream C:\src\YYToolkit --work-dir C:\yk
```

`all` runs `materialise`, `apply`, `build`, `hosttests`, `verify-dll`; each is
also a command of its own, and the tool's docstring is the reference for options
and exit codes (0 done, 1 a step failed, 2 refused before doing anything, 3
toolchain missing). What matters in practice:

- **`--upstream` is only read.** The pinned commit OBJECT is exported, so the
  clone's HEAD and local edits are irrelevant. The tree id is checked against
  `upstream.json` first and every exported file is re-hashed against the
  commit's blob ids. No network unless `--upstream` is omitted AND
  `--allow-network` is passed.
- **The work directory must be short and outside the repository.** Upstream's
  longest path is 92 characters below it and a hub worktree's own prefix was 97
  on the build host, so `MAX_PATH` (260) is a real limit. An absolute path over 40 characters is
  refused, not warned about; so is one inside the hub, one that contains or is
  contained by `--upstream`, and a non-empty directory the tool did not create
  (every step deletes what it is about to rebuild). Default:
  `%LOCALAPPDATA%\hstk\yk`, falling back to `%SystemDrive%\hstk\yk`.
- **The build is upstream's own `YYToolkit.vcxproj`, Release x64, unedited**
  apart from the series. `/Brepro` and `/PDBALTPATH` arrive through an injected
  props file, and `CL`, `_CL_`, `LINK`, `_LINK_` are stripped from the
  environment, so two builds on one toolchain are byte-identical.
- **`verify-dll`** requires every `Log-markers:` literal in the DLL as ASCII and
  absent from unpatched upstream. `verify-dll --dll <file>` checks any binary
  read-only - point it at a DLL of unknown origin to see which documented
  changes it lacks.

Expected result for `hs.1`: **950,784 bytes, sha256
`51a393d7e5291ad76bdb85b9f44faf5178b6b20e0ce8432fa26bdaf9e21eadf8`**, 7 of 7
host tests, 46 markers. That hash is only meaningful on the toolset that
produced it - VS 2022 Build Tools 17.14, `VCToolsVersion` 14.44.35207, Windows
SDK 10.0.26100.0. On another toolset expect another hash; compare the
`toolchain` block of the two BUILD-INFO files, and rely on the host tests and
the marker check. `--expected-sha256` enforces a hash when you want it enforced.

Outputs, all in `<work>\o\` (the tool never copies the DLL anywhere else):

- `YYToolkit.dll` and `YYToolkit.dll.sha256`.
- `YYToolkit-BUILD-INFO.json` - the provenance record that travels with the
  binary: upstream pin, hub commit and whether this directory was dirty,
  per-patch sha256 and markers, toolchain versions, DLL size and hash, host-test
  results, the source zip's id. It has no timestamp, so a re-run writes
  identical bytes. `live_gameplay_verified` is always `false`: the tool cannot
  know, and the table below is the record.
- `yytoolkit-source-<12 hex>.zip` - a deterministic zip of this directory, named
  by its content, so the corresponding-source pointer goes wherever the DLL
  goes. It does not contain upstream's source or the build tool; `NOTICE.md`
  says where those are.

## Launch gate

| Step | How | Result | Status | Date |
| --- | --- | --- | --- | --- |
| Build | `build_yytoolkit.py all` on the toolset above, from an uncommitted working tree (`patch_directory_dirty: true`) | 950,784 bytes, the sha256 under [How to build](#how-to-build); `warnings: 2` in BUILD-INFO; reproducible on that toolset | Verified | 2026-09-19 |
| Host tests | `hosttests` step | 7 of 7 passed | Verified | 2026-09-19 |
| Marker check | `verify-dll` step | 46 markers in the DLL, none in unpatched upstream | Verified | 2026-09-19 |
| Marker check, negative control | `verify-dll --dll <previously distributed DLL>` | Fails, naming the markers it lacks | Verified | 2026-09-19 |
| First launch against the game | checklist below | Reached town; stage 1 and stage 2 both OK. Scope: YYToolkit alone, no plugin loaded, one launch on the existing legacy hint line (see [First launch results](#first-launch-results-2026-09-19)) | Verified | 2026-09-19 |
| Lag measurement | 0005's cost and summary lines, plus play | ~2 min in Chaos Tower, "no lags whatsoever"; 133 caught errors (1 distinct), 132 handled in 0.252 ms total (see [First launch results](#first-launch-results-2026-09-19)) | Observed once | 2026-09-19 |
| First launch with a plugin loaded (ForgePact or the Tracker producer) | checklist below | - | NOT RUN | - |
| Launch A (no hint file) | checklist below | - | NOT RUN | - |
| Launch C (`YYTK_RI_VERBOSE=1`) | checklist below | - | NOT RUN | - |

No submodule pin should move to a build of this series until the "First
launch against the game" and "Lag measurement" rows above carry a date, the
game build, the DLL's sha256 and the kept logs. The one launch recorded here
ran YYToolkit alone; no plugin has been loaded against this series yet (see
the three NOT RUN rows above), so neither the ForgePact nor the
HS-Offline-Tracker pin has moved.

**Launches.** Copy `<work>\o\YYToolkit.dll` over `mods\aurie\YYToolkit.dll` in an
offline install and keep the old file. Both tools' installers overwrite that
path, so trust the first log line, not the file date, for which DLL ran. Keep
each `YYToolkit.log`.

- **A - no hint file.** Delete `<exe>.yytkcache` and start the game without
  ForgePact's panel: its `ensure_ri_cache` runs before every panel launch, writes
  a legacy three-number line when it knows the exe size and deletes the file
  when it does not. Play a few minutes (the error summary appears at most once
  per 30 s).
- **B - second launch**, with the hint A wrote.
- **C - `YYTK_RI_VERBOSE=1`** in the game's environment: the positive control
  for the dump gate.

**Checklist.** 0006's line comes first in the log; the rest follow init order.

| Patch | The log must show | A failure looks like | Observed, 2026-09-19 (YYToolkit alone, no plugin, existing hint line) |
| --- | --- | --- | --- |
| 0006 | First line: `[hs] YYToolkit 4.0.1, Hero Siege patch series hs.1 (hero-siege-offline-toolkit, third_party/yytoolkit)` | No such line: the DLL that ran is not a build of this series. Any item below failing only with 0006 applied: drop 0006 and rebuild. | Matched: log line 1. |
| 0001 (A) | `RI pre-filter ranked N of M pages to be scanned first`, then `RI pre-filter hit: chain on page ...`, then `RI scan hint written ...`. Time the gap between upstream's `.text section spans` and `breakpoint at` lines. | `RI pre-filter miss: chain on page ...` - the game still starts, but the ranker contributed nothing and no timing may be credited to it. `RI scan hint refused, pre-filter refused: .text is not committed, readable memory from start to end` - the allow-list or the section bounds refused the shortcut. `RI scan hint not written`. `RI scan found no chain`. | NOT RUN. A hint file already existed, so this launch took the "B" path, not "A". |
| 0001 (B) | `RI scan hint hit: the scan of page P found the chain at rva ... , K of M pages scanned` with K = 2, then `RI scan hint unchanged, file left alone`; no "Please wait" console message. | `RI scan hint miss: no chain on hinted page P or the page before it (2 scanned), scanning the other pages` or `RI scan hint key mismatch` on an unchanged exe. `RI scan hint hook failed: the chain is on page` (must not be followed by a hint-miss line). | Hit, K = 2 of 51925 pages. But the file was rewritten, not left alone - see the next row; the pre-existing hint was still a legacy 3-token line, so writing it back out upgraded the format. |
| 0001 (panel launch, legacy line) | `RI scan hint key mismatch: stored size/timestamp/image/checksum` when the size differs, then a hit or a miss line, then `RI scan hint written for chain rva ... (replacing a line that said something else)`. | Neither a hit nor a miss line before upstream's `breakpoint at ... =>` line - the file must never decide the address. | Partial match: hit, then `RI scan hint written ... (replacing a line that said something else)` as the legacy 3-token line was upgraded to the current 6-token form. No key-mismatch line, because the exe size matched. |
| 0002 (A, B) | One `RI init summary: 202 instructions walked ..., 100 stores emulated, 0 refused, 512 stack rows of which 25 are non-zero, interface at rsp+0x60, the chain ended on the rsp-relative lea` ending `YYTK_RI_VERBOSE is not set - ... (its value has 0 characters)`. The numbers come from one measured build; other numbers on another game build are not by themselves a failure. | A summary saying the chain did NOT end on the rsp-relative lea (0007 then refuses the interface, see its row). The dump present without the variable. | Matched exactly: the predicted numbers, `YYTK_RI_VERBOSE` reported not set. |
| 0002 (C) | About 723 dump lines, then `RI init summary: ... YYTK_RI_VERBOSE is 1 - the full dump is above (its value has 1 characters)` (2 characters when set with cmd's `set X=1 && game`). | Still `not set` although the launcher was given the variable: the launcher does not hand its environment on. `set, but to something other than 1 - the dump stays off`: the wrong value arrived. | NOT RUN. `YYTK_RI_VERBOSE` was not set this launch. |
| 0007 | No `REFUSED to publish the runner interface` line, and the summary says `0 refused`. | `REFUSED to publish the runner interface: <reason> (N stores refused ...)` followed by stage 2 failing with a status: the walk misread this game build - run once with `YYTK_RI_VERBOSE=1` and keep the dump. A fault instead of a status after that line means the "zeroed interface fails cleanly" reading of the source is wrong - record it. | Matched: `0 refused`, no `REFUSED` line. The refusal path is still not observed on any launch. |
| 0003 | Exactly once, before `HkPreinitialize() => AURIE_SUCCESS` and `Stage 1 init OK!`: `HkPreinitialize() => ExecuteIt hook NOT installed by design (YYTK_HOOK_EXECUTEIT=0): ... ExecuteIt lookup => AURIE_SUCCESS, 0x<non-null>`. Zero `REFUSED EVENT_OBJECT_CALL` lines with only ForgePact and the Tracker producer loaded. This patch is unrelated to the startup crash - stage 1 already succeeded in the crash log. | The suffix ` - lookup FAILED, init continues, but crash-report frames may be mislabelled Code_Execute`. Any `REFUSED EVENT_OBJECT_CALL from '<leaf>.dll'` line: it names the plugin that registered the event. | Matched: exactly one such line, before `Stage 1 init OK!`. Zero `REFUSED EVENT_OBJECT_CALL` lines - expected here, since no plugin was loaded to register the event; this row is not yet exercised with a plugin present. |
| 0004 | One or more `GmpFindFunctionsArrayX64() rejected candidate 0x... (mov at 0x...): <reason>`, then exactly one `GmpFindFunctionsArrayX64() accepted candidate 0x...` carrying `entry size 24` and `names confirmed by Code_Function_Find`, then `m_FunctionEntrySize = 24`. If the accept is for the first mov with no rejection before it, the inferred crash cause is wrong - record that. Count `Functions array search attempt` / `not repeated` lines (zero of both: stage 2 was entered once). | The log ending right after the finder line (the original crash shape). `m_FunctionEntrySize = 0` with `YkDetermineFunctionEntrySize() refused: ...`. `GmpFindFunctionsArrayX64() => none of N distinct candidate(s) ...` then `VM::GmpFindFunctionsArray() => none of` (or `=> no candidate in`) and `Failed to determine function array size! (AURIE_OBJECT_NOT_FOUND)`; 255 instructions in that line means the disassembler cap ended the scan. `... entry N ('name') has a routine that is not executable game image code`: the first-8-builtins assumption is wrong. Any `VM::GmpFindFunctionsArray() rejected candidate 0x0000000000000000`. | Three rejections then one accept (`entry size 24`, 8 of 8 names confirmed); zero `attempt`/`not repeated` lines. The previous binary's notes assumed four rejections - this exe shows three. See [First launch results](#first-launch-results-2026-09-19) for what the first rejection reason confirms about the fault site. |
| 0005 | `[hs] YYError hook install: MmCreateHook => AURIE_SUCCESS`. At the first caught error, `[hs] game symbol table: built in ... builtins=A accepted of S slots (K outside the game image; walk ended on <reason>)` with A in the hundreds or thousands, ending on `a null routine` or `a name the runner does not know`. Every full report ends with `[hs] YYError report cost: report #N (... bytes, written) \| total X ms \| stacktrace capture ... \| ...`. `[hs] YYError summary: total=T distinct=D/32 reports=R report_failures=0 ...`: expect T in the hundreds while R stays near D, and `count_only_ms` small next to `report_ms_total`. Record T, R, `report_ms_total`, `report_ms_max`, `variants=`, `returned=`, `dropped=`. | `NO builtin symbol was accepted: this is what the wrong functions array looks like`. `builtin walk stopped at slot N` with a small N. `build attempt N of 2 refused after X ms: <reason>` or `given up`. `dropped=` above 0 with `[hs] YYError: Aurie returned no trampoline`. `truncated=` or `unexpandable=` above 0. `expired=` or `stale=` above 0: a report took longer than 30 s. `[hs] YYError summary unavailable`. **The silent one:** no `[hs] YYError` line beyond the install line. No error was raised in this session, so the ledger, the report path and the count-only path were not exercised - the row measures nothing and the run does not count toward the launch gate. A quiet log is not "the lag is gone". Re-run until `[hs] YYError summary: total=` appears at least once. | Not silent: install OK, table built in 6.189 ms (8,893 symbols), one full report, `total=133 distinct=1/32 reports=1 report_failures=0 report_ms_total=527.405 repeats=132 variants=132 count_only_ms=0.252 returned=0 dropped=0 runner_ms=0.000`. See [First launch results](#first-launch-results-2026-09-19) for the report-cost breakdown and the `returned=`/`dropped=` reading. |

### First launch results, 2026-09-19

**Setup.** Only `YYToolkit.dll` in `mods/aurie` - no plugin loaded (no
ForgePact `BloodPactPlugin`, no Tracker producer). Launched through
ForgePact's offline launcher module. An existing legacy 3-token
`<exe>.yytkcache` line for this exe size was already present, so this ran the
"B" path, not "A". `YYTK_RI_VERBOSE` was not set. Game exe size
281,751,552 bytes. One session: menu, about two minutes in Chaos Tower, back
to town. The full log is kept locally, not committed, as
`%LOCALAPPDATA%\hstk\yytoolkit-evidence\YYToolkit.log.hs1-first-launch-full`
(83 lines, 9,998 bytes) - see [Known limitations](#known-limitations-and-what-is-not-measured)
for why local logs are not in the repository and how to re-derive one.

**Startup (log lines 1-43).** Line 1 is the 0006 identity line. 0001 took the
"B" path off the pre-existing legacy hint: one `RI scan hint hit` (2 of 51925
pages scanned), then `RI scan hint written ... (replacing a line that said
something else)` as the file was upgraded from the legacy 3-token form to the
current 6-token one; no key-mismatch line, because the exe size matched.
Still not exercised: launch A (no hint file), a stale or wrong hint, a
read-only install. 0003 logged exactly one `ExecuteIt hook NOT installed by
design` line before `Stage 1 init OK!`, and zero `REFUSED EVENT_OBJECT_CALL`
lines - expected, since no plugin was loaded to ask for the event. 0002/0007's
`RI init summary:` line carried exactly the predicted numbers (202
instructions, 100 stores, 512 stack rows of which 25 non-zero, interface at
`rsp+0x60`, chain ended on the rsp-relative lea), `YYTK_RI_VERBOSE` reported
not set, and no `REFUSED to publish the runner interface` line - so 0007's
refusal path is still **not observed**. The startup portion of the log is 43
lines, against 736 for the unpatched dump. 0004 rejected three candidates
before accepting one (`entry size 24`, 8 of 8 names confirmed by
`Code_Function_Find`, `m_FunctionEntrySize = 24`); the previous binary's notes
assumed four rejections, which this exe does not match - three were rejected
here. The first rejection's reason, "global does not hold an aligned
pointer", named the same candidate the earlier crashing fresh build had
accepted as the functions array (its log's last line) - which moves the
startup-crash fault site from *likely* to **observed on this build**.
(Addresses are deliberately not repeated here: they are ASLR run-time values,
not stable across launches - the reasons and counts are the finding, per
["Never Call an Address You Resolved by Hand"](../../AGENTS.md#never-call-an-address-you-resolved-by-hand).)
Zero `Functions array search attempt` / `not repeated` lines: stage 2 was
entered once. The rest of stage 2 - `code_is_compiled`,
`GmpGetBuiltinInformation`, `GmpFindRVArrayOffset`, `GmpFindScriptData`,
`GmpFindRoomData`, `GmpFindCurrentRoomData`, the YYError `MmCreateHook`
install - all reported `AURIE_SUCCESS`, ending `Stage 2 init OK!`. So: **the
startup crash did not reproduce, on this game build and this machine, in this
one launch.**

**Error reports (log lines 44-83).** The game symbol table built once, in
6.189 ms on the first attempt: 8,893 symbols, 6,254 of 6,254 returned scripts
usable (0 rejected), 2,867 of 2,868 builtin slots accepted (0 outside the
game image; the walk ended on a null routine). Exactly one distinct message
was raised all session - `Unable to find any instance for object index
'<number>' name '<undefined>'`, first raised at the menu from the game's own
timer-update script - and it got one full report: 1,708 bytes written,
527.383 ms total, of which stacktrace capture cost 0.149 ms, game-symbol
resolution 0.018 ms over 15 game frames, and symbolising 4 *non-game* frames
(YYToolkit's own frames plus one null one) cost 520.868 ms - the great
majority of the report. The session's final summary line: `total=133
distinct=1/32 reports=1 report_failures=0 overflow_hits=0
report_ms_total=527.405 report_ms_max=527.405 repeats=132 variants=132
count_only_ms=0.252 returned=0 dropped=0 runner_ms=0.000 reentered=0 busy=0
truncated=0`. So the 132 repeats of that one message cost 0.252 ms combined,
not 132 more full reports.

*What `returned=0`, `dropped=0` and `runner_ms=0.000` together show.* Per
patch `0005`
(`third_party/yytoolkit/patches/0005-yyerror-report-once-and-measure.patch`),
`dropped=` only moves when Aurie handed back no trampoline, so the original
`YYError` was never reachable and was never called; `returned=` (and, in the
same branch, `runner_ms=`) only move when that call *returns* to the hook
instead of unwinding through it. The patch forwards to the original on every
one of the 133 calls, not only the one that got a full report. `dropped=0`
across all 133 calls means a trampoline was present and the original
`YYError` was called every time; `returned=0` (and `runner_ms=0.000`,
which is timed in the same branch as `returned=` and so can only move
together with it) across the same 133 means none of those calls came back to
the hook. Read together, in this one session the runner's own `YYError` left
by unwinding rather than by returning, every time it was raised - which
answers 0006's open question (`returned=`/`dropped=` are what the first
launch reads it from) **for this one session**, not as a general fact about
the runner.

**What the split shows.** The cost this series assumed beforehand -
rebuilding the game-symbol map per stack frame - was not what dominated this
report: with the table cached, game-symbol resolution cost 0.018 ms. Almost
all of the 527 ms went into the C++ runtime's own symbolisation of the 4
non-game frames. Whether that is a one-time cost (the debug-symbol engine's
own first-use initialisation) or is paid again by the next distinct message
is **not known**: this session produced only one distinct message, so there
was no second data point. Known limitation going forward: the first sighting
of each distinct message can cost on the order of half a second on this
build. (Printing non-game frames as module+offset instead of going through
the debug engine is a candidate this reading raises, not a patch that is
planned or built.)

**Play observation (a person's report, not an instrument).** About two
minutes in Chaos Tower with this DLL: "no lags whatsoever"; a few error lines
appeared on the console when returning to town. A previous session with the
same content and the previous DLL lagged heavily and logged about 142 caught
errors, each with a full report, in a session of similar length. This session
logged 133 caught errors - the same order of magnitude - and handled 132 of
them in 0.252 ms combined. So: similar error volume, and lag was not observed
this time. This is one session, one machine, YYToolkit alone, and the
comparison is not controlled for everything that differed between the two
DLLs (the old binary also differed in compiler version and in whatever else
was lost with its source).

**Still not run or not observed.** Any launch with a plugin loaded
(ForgePact's `BloodPactPlugin`, the Tracker producer) - the plugin ABI
headers are untouched by the series, but no plugin has been loaded against a
build of it yet; launch A (no hint file); launch C (`YYTK_RI_VERBOSE=1`); a
second distinct error message; 0007's refusal path and 0003's optional
refusal control below; a different game build; a second machine or toolset.
The ForgePact and HS-Offline-Tracker pins have not moved - players still
receive `bb113eef…`.

Optional control for 0003's refusal path (NOT RUN): a throwaway plugin that
registers `EVENT_OBJECT_CALL` ten times should get ten `AURIE_UNAVAILABLE`
returns and exactly eight lines, `refusal 1` to `refusal 8`, the eighth ending
` - further refusals will not be logged`, with the plugin's DLL leaf name as
owner; its `EVENT_FRAME` registration must still succeed and fire.

**The lag question is two observations, not one.** The log says what reports
cost; whether the game stops lagging is seen by playing, against the previous
DLL in the same kind of session. Both are now in hand for one session - see
"First launch results" above. Write "not observed" rather than "fixed" for a
single session, and treat a second session the same way before calling
anything settled.

## How to change the series

1. **A new change is a new numbered patch** (`NNNN-<slug>.patch`, next number),
   added as the last line of `patches/series`. Never replace an upstream file
   wholesale, and never fold a second reason into an existing patch.
2. **Generate it, do not edit it.** Apply the series to a scratch clone of
   upstream at the pin (`git am`), commit the change, and write the file with
   `git format-patch`. A hand-edited diff has wrong hunk counts and `index`
   lines and fails in ways that do not say why. Patches are LF only
   (`.gitattributes` keeps them `-text`); the tool refuses a CR.
3. **The message carries the five fields**: `Why:`, `Evidence:`, `Fails-safe:`
   (what happens when the heuristic does not match: fall back to upstream
   behaviour, or refuse with a line that says why), `Log-markers:` and
   `Upstream-status:`. Markers are double-quoted literals of at least 8
   printable ASCII characters, or `none`; each must end up in the DLL and must
   not occur in unpatched upstream.
4. **Host tests go inside the patch**, under `YYToolkit/hs-tests/`. No patch
   touches upstream's plugin-facing shared headers - plugins compile against the
   unmodified pinned ones.
5. **Document it in the same change**: a row in the patch table above, a
   section, a launch-gate row, and a dated entry in `NOTICE.md`.
6. **Bump `series_revision`** in `upstream.json` AND the literal in the patch
   that defines it (`g_HeroSiegeSeriesRevision` in 0006) - the same string in
   both, or a log stops identifying its source. Changing an existing patch is a
   revision bump too, with that patch regenerated.
7. **Rebuild with `all`**, update the expected size and hash here, and reset the
   two launch rows to NOT RUN. A new binary has not been launched.

`tests/test_yytoolkit_patch_series.py` enforces the mechanical part of this list
offline; extend it rather than working around it. With `HSTK_YYTK_UPSTREAM` set
to a local clone that contains the pinned commit, it also exports the pin and
applies the series for real through the build tool; without it that one test
skips and says so. Moving the upstream pin is the same procedure with every
patch regenerated against the new commit.

## Known limitations and what is not measured

- **Launched once, YYToolkit alone.** On 2026-09-19 the built DLL ran one
  session against the game with no plugin loaded; the startup crash did not
  reproduce and lag was not observed - see
  [Launch gate](#launch-gate) and
  [First launch results](#first-launch-results-2026-09-19). Every "fixes"
  claim in the patch messages beyond that one session - with a plugin loaded,
  on the no-hint-file path, with the verbose dump on, on a different game
  build or machine - is still a design intent, not a measured result.
- **Lag candidates this series does not fully address, or has only partly
  measured:** the console YYToolkit allocates (synchronous console writes if
  the runner prints each error) and plugin-side per-call allocations in
  `CallBuiltinEx` are still unaddressed and unmeasured. The report path
  (0005) and the unoptimised build (0006) are addressed; 0005's cost is now
  measured for one distinct message in one session (527.383 ms for the full
  report, of which 520.868 ms went into symbolising YYToolkit's own frames,
  not game-symbol resolution) - whether that cost recurs on a second distinct
  message is not known, because this session raised only one. No frame-time
  effect of 0006's optimisation level has been isolated on its own.
- **The expected hash holds on one toolset only.**
- The tool builds Release x64 only. Its off-Windows path (`materialise`,
  `apply`) is reasoned, not run.
- Later upstream history was not available offline and was not checked; no
  patch has been submitted upstream.
- Whether the previous DLL carried further changes that left no strings cannot
  be determined without its lost source.
- **The evidence files the patch messages cite are not in the repository.**
  `evidence/fresh-build-crash.YYToolkit.log`, `shipped-strings.txt` and
  `documented/...` in the `Evidence:` fields, and
  `%LOCALAPPDATA%\hstk\yytoolkit-evidence\YYToolkit.log.hs1-first-launch-full`
  (the first launch's full log, cited under
  [First launch results](#first-launch-results-2026-09-19)) name files kept on
  the researcher's machine. They are not committed because they carry
  build-host and user-profile paths, and this directory holds no logs (a test
  enforces both). Each can be re-derived: the first is the `YYToolkit.log` of
  an unpatched v4.0.1 build with the two previously documented files applied,
  launched against the game; the second is a strings listing of the
  `bb113eef...` DLL; the third is the two whole-file copies in the
  submodules' `yytoolkit-modified/` directories; the fourth is this series's
  own DLL (see [How to build](#how-to-build) for its size and hash) launched
  the same way - YYToolkit alone, an existing legacy hint file, one session in
  Chaos Tower. The line numbers in the citations hold for those local copies
  only. The counts taken from them (736 log lines, 723 of them dump; 202 /
  100 / 512 / 25; `rsp+0x60`; 133 / 1 / 132 / 527.383 ms) are repeated in the
  patch messages and in this guide, so the launch gate can be read without
  the files.
- Per-patch residuals are listed in the sections above and in full in each
  patch's `Fails-safe:` field.

## Follow-ups in the submodule repos

The hub `.gitignore` bans `*.dll`, so no binary is committed here, and this
change alters nothing a player receives. Both carriers of the DLL are submodule
repositories:

- **ForgePact** - pins the DLL in `tools/toolchain-pins.json` and carries
  `yytoolkit-modified/NOTICE.md`. Follow-up PR: move the pin and its sha256,
  rewrite that notice to point here and list every patch, ship the notice and
  BUILD-INFO in the release zip, add release notes. The panel's
  `KNOWN_RI_CACHE` table of hand-measured RVAs is harmless with 0001 (the file
  is only a hint) and can be deleted; its delete-when-unknown branch also
  removes the hint before every panel launch on builds the table does not know.
- **HS-Offline-Tracker** - carries a git-tracked `aurie-loader/YYToolkit.dll`
  and a copy of the same notice. Follow-up PR: replace both.

Both install to `mods/aurie/YYToolkit.dll` with overwrite semantics, so the two
must move together, after the launch gate. Until they land, players still
receive the previous DLL, and those two notice files remain the (incomplete)
statement for it.
