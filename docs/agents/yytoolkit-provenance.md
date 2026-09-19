Story and evidence behind `AGENTS.md` § ["YYToolkit Integration"](../../AGENTS.md#yytoolkit-integration).

## A binary nobody could rebuild

Every ForgePact release from v1.3.1 to v1.3.16, and HS-Offline-Tracker's
`aurie-loader/`, distributed the same modified `YYToolkit.dll`: SHA-256
`bb113eefc9a5d485231ced1dc85d773dbc6b762ee680214851c56541359ad297`, 904,192
bytes. Both repositories carried a `yytoolkit-modified/NOTICE.md` beside it
that named two changed files — a runner-interface disk cache and the
`ExecuteIt` hook left uninstalled — and said everything else was unmodified
upstream v4.0.1.

A fresh build of exactly that — pristine v4.0.1 plus the two documented files
— did not get the game started. Its `YYToolkit.log` ends on the
`YYC::GmpFindFunctionsArray() => AURIE_SUCCESS` line and never prints the
`m_FunctionEntrySize` line that follows it; the only code between the two is
`YkDetermineFunctionEntrySize`, which dereferences the candidate it was handed
without checking it. That is the **likely** fault site — inferred from a log
that is flushed per line. No crash dump exists.

The distributed DLL was not built from the documented source alone. What shows
that is its own content, not how it behaved: it holds things that are in
neither upstream nor the two documented files — read from the PE header, the
Rich header, the import table and the string table, with nothing disassembled.
The behavioural comparison is **not controlled** and proves nothing by itself:
the fresh build differed from the distributed DLL in four variables at once
(toolset 14.44 against 14.51, optimisation off, whole-program optimisation on,
and `UNICODE` defined), and ForgePact's notes record an earlier modified build
of unoptimised size reaching `Stage 2 init OK!` on an earlier Season 10
executable — whether that build already had the filter below is unknown, so
whether the filter was always needed may depend on the game build.

- **A candidate filter in `YYC::GmpFindFunctionsArrayX64`** (`rejected
  candidate` / `accepted candidate` log lines that exist neither upstream nor
  in the two documented files). It filters the very value the rebuild most
  likely died dereferencing, so it is most likely what let the distributed DLL
  get past that point — and its source was not kept.
- **A startup breadcrumb tracer**: numbered messages written with `CreateFileA`
  / `WriteFile` to a hardcoded absolute path under the builder's user profile,
  present in every distributed copy.
- **An import of `VirtualQuery`** that nothing in the documented source calls.
- **The lea/mov page pre-filter**, which *was* in the committed
  `Generic-RunnerInterfaceNew.cpp` (since deleted from ForgePact's tree, see
  `docs/submodules/ForgePact/instructions.md`'s repository map) but was never
  listed in the notice.
- **A build without `UNICODE`**: it imports `SetWindowLongPtrA`, while
  upstream's project is Unicode. The notice did not mention it.
- **An absolute `__FILE__` string under the builder's user profile**, which
  names the source directory that was not kept — a second path leak beside the
  tracer's target. The Rich header lists 19 C++ objects and 1 C object, the
  same set as upstream's project file, so the tracer lived in existing files
  and no source file was added.

The notice's build recipe was wrong as well. It says MSVC toolset 14.50 and
`cl /std:c++latest /MD /LD`; the PE header says linker 14.51 (timestamp
2026-08-26 07:13:32 UTC, export-table name `YYToolkit_noexec.dll`), and the
binary's pooled strings, missing `.rsrc` section and size — within about 9 KB
of a plain `cl /O2` build of the documented tree, about 276 KB under one
without `/O2` — make a hand-written `/O2` command line **likely**, not
upstream's project file and not the recipe as written.

Whether the DLL carries further changes that left no string **cannot be
determined** without the source it was built from. That is the actual cost: not
that the binary was bad — it was the one that worked — but that nobody can say
what is in it, no repository holds its complete corresponding source, and the
only way to change it was to start again.

## Two reasons that did not survive being checked

Re-creating the series meant writing each change's reason down next to its
evidence, and two of the old reasons did not hold:

- **`ExecuteIt`.** The notice says the hook corrupted instance references and
  caused `Unable to find any instance for object index`. ForgePact's own
  `docs/S10-special-content-notes.md` records the same error with the hook
  removed. What stands is narrower: no plugin in this toolkit consumes
  `EVENT_OBJECT_CALL`, and project notes record the per-event hook
  crash-looping on Season 10 — not re-measured here. Patch `0003` says that,
  logs the off state, and refuses the registration with `AURIE_UNAVAILABLE`
  rather than accepting a callback that can never fire.
- **The cache file.** `<exe>.yytkcache` was described as a startup
  optimisation. It was also trusted: on a cache hit the old code planted a
  mid-function hook at an address read from disk, checking only the
  executable's size — and `ForgePact/src/forgepact.py`'s `ensure_ri_cache`
  pre-seeds that file from a table of hand-measured RVAs. That is a
  hand-resolved address reaching a player by way of a text file (see
  ["Never Call an Address You Resolved by Hand"](../../AGENTS.md#never-call-an-address-you-resolved-by-hand)).
  With patch `0001` the file is only a hint for which pages to scan first; the
  hook address always comes from the scan. The legacy three-number line stays
  readable, so the panel keeps working and its table is harmless rather than
  load-bearing.

## What exists now

[`third_party/yytoolkit/`](../../third_party/yytoolkit/README.md) holds one
pinned upstream commit (`upstream.json`: tag v4.0.1, `5a95e46`, with the
commit's tree id) and seven patches, each a `git format-patch` file whose message
carries `Why`, `Evidence`, `Fails-safe`, `Log-markers` and `Upstream-status`.
Their host tests travel inside the patches, under `YYToolkit/hs-tests/`.
`tools/build_yytoolkit.py` exports the pinned commit from a local clone,
verifies the tree id and every blob, applies the series, builds the patched
tree through upstream's own project file, runs the host tests, and then checks
that every declared log marker occurs in the DLL and does **not** occur in
unpatched upstream.

The functions-array validation (`0004`) is an original re-implementation, not
a reconstruction: the lost filter's acceptance rule is unknown, so the new one
states its own and logs the reason for every candidate it rejects.

Measured on 2026-09-19, on one machine (VS 2022 Build Tools 17.14,
`VCToolsVersion` 14.44.35207, Windows SDK 10.0.26100.0):

- `py -3 tools/build_yytoolkit.py all --upstream <local clone>` produced a
  950,784-byte DLL, SHA-256
  `51a393d7e5291ad76bdb85b9f44faf5178b6b20e0ce8432fa26bdaf9e21eadf8`. The
  build is reproducible on that toolset (`/Brepro` through an injected props
  file); the hash means nothing on another one.
- 7 of 7 host tests passed.
- 46 log markers are present in the DLL and absent from unpatched upstream.
- **Negative control:** `verify-dll --dll` pointed at `bb113eef…` fails and
  names the markers that file lacks. A marker check that cannot fail would have
  proved nothing — this is the same rule as
  ["Prove the Instrument"](../../AGENTS.md#prove-the-instrument-before-trusting-a-negative-result),
  applied to a build instead of a hook.
- **Launched twice against the game, 2026-09-19.** First, YYToolkit alone, no
  plugin loaded, one session (menu, about two minutes in Chaos Tower): the
  startup fault did not reproduce on that build and that machine, and lag was
  not observed either. Second, an idle session with ForgePact's
  `BloodPactPlugin` (v1.4.4) and the HS-Offline-Tracker producer both loaded
  alongside it: both initialized, and an IPC smoke test exercised the
  plugin-to-runner interface, but no gameplay was played. Full record,
  including what each session does and does not cover:
  `third_party/yytoolkit/README.md`, "Launch gate", "First launch results
  (2026-09-19)" and "Second launch results (2026-09-19, plugin loaded)".

## What is not known

- **The new DLL has been launched twice: once without a plugin, once with
  two.** The startup fault did not reproduce in the first session (2026-09-19,
  YYToolkit alone). The second session (2026-09-19) loaded ForgePact's
  `BloodPactPlugin` and the HS-Offline-Tracker producer alongside it; both
  initialized, and an IPC smoke test exercised the plugin-to-runner
  interface, but it was an idle session — no gameplay, so the error-report
  path with a plugin loaded is still unexercised. The build tool still writes
  `live_gameplay_verified: false` and always will — that field records
  nothing about a launch, by design; the launch gate in
  `third_party/yytoolkit/README.md` is the record instead. Not yet run: the
  no-hint-file path, the verbose-dump control, gameplay with mods active, a
  second game build or machine.
- **The lag was observed once, not measured as fixed.** An earlier session
  observed vanilla smooth, offline without mods smooth, and YYToolkit alone
  lagging, with about 142 caught game errors in about two minutes, each
  producing a full stack-trace report on the previous DLL. It is structurally
  certain from upstream's source that `GmResolveGameSymbolFromAddress`
  rebuilds a map of every script and builtin once per stack *frame* of every
  one of those reports. Patch `0005` caches the table, reports each distinct
  message once (32 tracked; further ones rate-limited to one report per
  30 s), counts repeats in O(1), and writes cost lines so a launch measures
  it rather than assuming it. The first launch of this series (2026-09-19,
  YYToolkit alone, ~2 minutes in Chaos Tower) logged 133 caught errors — the
  same order of magnitude — of which only one was a distinct message: its
  full report cost 527 ms, almost all of it spent symbolising YYToolkit's own
  stack frames rather than the 0.018 ms the cached game-symbol table cost,
  and the other 132 repeats cost 0.252 ms combined. The person playing
  reported "no lags whatsoever." That is one session on one machine, not a
  controlled comparison (the old DLL also differed in compiler version and in
  whatever else its lost source held), and it raised no second distinct
  message to compare against — so "not observed" is the correct word here,
  not "fixed." Full numbers: `third_party/yytoolkit/README.md`, "First launch
  results (2026-09-19)."
- **Other lag candidates are neither addressed nor measured:** the console
  YYToolkit allocates (synchronous writes, if the runner prints each error to
  it), and plugin-side per-call allocations in `CallBuiltinEx`. Upstream's
  `Release|x64` compiles with optimisation disabled; patch `0006` sets it
  explicitly, and no frame-time effect of that has been measured.
- **Players still receive `bb113eef…`.** The hub's `.gitignore` bans `*.dll`,
  so no binary is committed here, and both carriers are submodule
  repositories: ForgePact through `tools/toolchain-pins.json`, the Tracker
  through a git-tracked `aurie-loader/YYToolkit.dll`. Both install to
  `mods/aurie/YYToolkit.dll` with overwrite semantics, so their follow-up PRs
  have to release together. **Recorded 2026-09-19: both follow-ups have
  merged to their own `origin`** (ForgePact PR 53, HS-Offline-Tracker PR 3)
  — the pin moved to sha256
  `51a393d7e5291ad76bdb85b9f44faf5178b6b20e0ce8432fa26bdaf9e21eadf8`, and the
  notice pair rewritten to point here. **Also recorded 2026-09-19, later the
  same day: the hub release that carries the binary now exists and is
  published** (`yytoolkit-v4.0.1-hs.1`, not marked `--latest`; see
  `third_party/yytoolkit/README.md`, "Where the binary is published"), and
  ForgePact's pin resolves against it. Merging and publishing the library
  release are not the same as shipping the DLL: **neither repository has
  tagged or cut a tool release carrying the new pin**, so no player has
  received it yet. The two `yytoolkit-modified/NOTICE.md` files now on
  `origin` describe this series accurately, but the last *released* copy of
  each tool carries the earlier, incomplete notice alongside `bb113eef…` —
  that older notice is the one still authoritative for what a player's
  installed copy actually carries, until a release ships the new pin.

## The rule this produced

A modified third-party binary is described by what was done to upstream, one
reviewable change at a time, in the repository that builds it. So:

- **One patch per reason**, with the header fields above. A whole-file copy
  hides the delta; here it hid that the delta was incomplete.
- **Each patch declares the log lines it adds, and the build refuses a DLL
  that lacks them.** "Binary does not match documented source" stayed
  invisible from v1.3.1 through v1.3.16 because nothing compared the two. Patch
  `0006` also writes the series revision (`hs.1`, the same literal as
  `upstream.json`'s `series_revision`) into the first line of `YYToolkit.log`,
  so a log from the field names the source it came from.
- **Never build from a tree that is not the pin plus the series.** The tool
  exports the commit *object*, not a working tree, and refuses a tree id that
  does not match.
- **A notice describes the binary it sits beside.** When it is known to be
  incomplete, it says so, and so does every guide that points at it.
- **Write the reason down with its evidence, and label what is inferred.** A
  reason that cannot be backed — the old `ExecuteIt` rationale — gets replaced
  by the narrower one that can.
