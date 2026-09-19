# NOTICE - this is a MODIFIED YYToolkit

The `YYToolkit.dll` this notice accompanies is **YYToolkit, modified** by the
Hero Siege Offline Toolkit project. It is not upstream's binary, and upstream
did not make, review or endorse the changes. Problems with this build belong in
the toolkit's issue tracker, not upstream's.

| | |
| --- | --- |
| Work | YYToolkit, by the Aurie Framework project |
| Upstream | https://github.com/AurieFramework/YYToolkit |
| Base | tag `v4.0.1`, commit `5a95e46` (the full commit id and tree id are in `upstream.json` and in `YYToolkit-BUILD-INFO.json`) |
| Licence | AGPL-3.0 (GNU Affero General Public License, version 3). `LICENSE` beside this file is upstream's text, byte for byte. |
| Our changes | Original work of the Hero Siege Offline Toolkit project, licensed AGPL-3.0, dated 2026-09-19 |
| Series revision | `hs.1` - the same string is in `upstream.json` and in the first line this DLL writes to `YYToolkit.log` |

Copyright in YYToolkit remains with its upstream authors. This directory is an
AGPL-3.0 aggregate inside the toolkit's hub repository: its licence does not
extend to the rest of that repository, and theirs does not extend to it.
The program comes with no warranty, as set out in the licence.

## What we changed

Every change is one patch file under `third_party/yytoolkit/patches/`, applied in
the order given by `patches/series`. All seven are dated **2026-09-19**. Each
patch's message states why it exists, the evidence, what happens when its
heuristic does not match, the log lines it adds, and its upstream status; the
directory's `README.md` is the guide.

1. `0001-runner-interface-scan-hint.patch` - Upstream's page-by-page scan for
   the runner interface now visits pages ranked by a byte-level pre-filter
   first. The file `<exe>.yytkcache` is only a hint for which pages to scan
   first; the hook address always comes from the scan and is never read from
   disk.
2. `0002-runner-interface-quiet-init-dump.patch` - The register, instruction and
   stack dump upstream writes on every launch is written only when
   `YYTK_RI_VERBOSE=1` is set in the game's environment; otherwise one summary
   line replaces it. Only logging changes.
3. `0003-executeit-hook-off-by-design.patch` - The ExecuteIt detour is not
   installed (build switch `YYTK_HOOK_EXECUTEIT`, default 0). The log says so,
   `CreateCallback(EVENT_OBJECT_CALL)` is refused with `AURIE_UNAVAILABLE`
   instead of accepting a callback that can never fire, and a failed ExecuteIt
   lookup no longer aborts initialisation.
4. `0004-functions-array-validation.patch` - Candidates for the runner's
   functions array are validated (location, layout of the first entries, names
   confirmed by the game's own lookup) before anything dereferences them, in
   both the YYC and the VM finder, and `YkDetermineFunctionEntrySize` reads
   through guarded copies. No candidate passing is a logged refusal, not a fault.
5. `0005-yyerror-report-once-and-measure.patch` - The `YYError` hook builds its
   game symbol table once, writes one full report per distinct error message
   (32 tracked; further ones share one slot and are reported at most once per
   30 s) and only counts repeats, logs what each report cost plus a periodic
   summary, and forwards the runner's text unchanged as `("%s", text)`.
6. `0006-release-build-optimised-and-series-identity.patch` - The Release x64
   configuration is compiled optimised (`MaxSpeed`, whole-program optimisation
   off, exception model stated), and the DLL's first log line names this patch
   series and its revision.
7. `0007-runner-interface-refuse-unfound-interface.patch` - The
   runner-interface hook checks every emulated store and the final copy against
   its private stack buffer, and refuses (one log line, stage 2 then fails with
   a status) to publish an interface its walk did not find, where upstream
   writes and copies unchecked.

The plugin-facing shared headers are not modified. Host tests for the changes
are added under `YYToolkit/hs-tests/` by the patches themselves.

## Corresponding source

The complete corresponding source of this binary is:

1. upstream YYToolkit at the commit pinned in `third_party/yytoolkit/upstream.json`
   (repository URL above; the tree id in the same file lets you verify the
   export);
2. the patches in `third_party/yytoolkit/patches`, applied in the order of
   `patches/series`;
3. the build tool `tools/build_yytoolkit.py` from the same hub commit, which
   exports the pin, applies the series, builds upstream's own
   `YYToolkit.vcxproj` (Release, x64) and checks the result.

`YYToolkit-BUILD-INFO.json`, shipped beside the binary, records the upstream
commit and tree, the hub commit, the sha256 of every patch, the compiler and
toolset versions and the DLL's size and sha256. The
`yytoolkit-source-<id>.zip` shipped with it is a copy of
`third_party/yytoolkit/` (items 2 and the pin of item 1). It does not contain
upstream's source or the build tool: the first is public at the upstream URL
above, the second in the toolkit's hub repository (`hero-siege-offline-toolkit`,
the name this DLL prints in its first log line) at the hub commit BUILD-INFO
records.

## State of verification on 2026-09-19

Built, host-tested (7 of 7) and checked for every log line the patches
declare. **Launched twice against the game, both sessions on 2026-09-19.**
Launch 1, YYToolkit alone (no plugin loaded): startup completed; about two
minutes of play logged 133 caught game errors (one distinct message, one
full report, the rest counted only), and the player saw no lag. Launch 2,
with ForgePact's `BloodPactPlugin` v1.4.4 (built locally) and the
HS-Offline-Tracker producer both loaded: all modules loaded, every patch's
hooks installed, no `REFUSED EVENT_OBJECT_CALL` line, and a few IPC commands
answered. That second session was idle, so it exercised neither the
error-report path with plugins loaded nor in-game mod behaviour. Neither
launch is a settled fix from one session on one machine. The directory's
`README.md` carries the launch gate and the full record ("First launch
results (2026-09-19)" and "Second launch results (2026-09-19, plugin
loaded)").

## About the previously distributed binary

Before this series, the toolkit distributed one modified `YYToolkit.dll`:
904,192 bytes, sha256
`bb113eefc9a5d485231ced1dc85d773dbc6b762ee680214851c56541359ad297`, the same
file in every ForgePact release from v1.3.1 to v1.3.16 (per ForgePact's
development guide) and in HS-Offline-Tracker's `aurie-loader/` (verified by
hash). Until the ForgePact and HS-Offline-Tracker repositories move to a build
of this series, that is still the file players receive.

The notice that accompanied it listed two changes - a disk cache for the runner
interface, and the ExecuteIt hook not being installed - and stated that
everything else was unmodified upstream. **That statement was incomplete.**
Reading the binary's strings, import table, PE header and Rich header (no
disassembly) shows what that notice left out:

- a candidate filter in `YYC::GmpFindFunctionsArrayX64` ("rejected candidate" /
  "accepted candidate" log strings) that appears in no documented source;
- a startup breadcrumb tracer: numbered messages written with `CreateFileA` /
  `WriteFile` to a hardcoded absolute path under the builder's user profile;
- an import of `VirtualQuery` with no caller in the documented source;
- a lea/mov page pre-filter that was present in the committed source file but
  was never listed in the notice;
- a build without `UNICODE` (it imports `SetWindowLongPtrA`; upstream's project
  is Unicode), which the notice did not mention;
- an absolute `__FILE__` string under the builder's user profile, which names
  the source directory that was not kept. The Rich header lists 19 C++ objects
  and 1 C object, the same set as upstream's project file, so the tracer was
  added to existing files and no source file was added.

Its build description was also wrong: the notice said MSVC toolset 14.50 and
`cl /std:c++latest /MD /LD`, while the PE header records linker 14.51
(timestamp 2026-08-26 07:13:32 UTC, export name `YYToolkit_noexec.dll`), and the
binary's shape - pooled strings, no resource section, a size within about 9 KB
of such a build - indicates a plain `cl /O2` build rather than upstream's
project file. The stated reason for leaving the ExecuteIt hook out (that it
corrupted instance references and caused a specific "unable to find any
instance" error) is contradicted by ForgePact's own research notes, which record
the same error with the hook removed.

**The source of that binary could not be fully recovered.** The source of the
filter and of the tracer is lost; a fresh build of the documented source
crashes during startup on Hero Siege; and whether the binary carried further
changes that left no strings cannot be determined without the lost source.

**This series replaces that binary; it does not reproduce it.** None of its
undocumented changes is carried forward as it was:

- the functions-array filter is rewritten from scratch as patch 0004, an
  original implementation, not a reconstruction;
- the breadcrumb tracer is dropped entirely - no patch contains it, and the only
  file the patches add a write to is the `<exe>.yytkcache` hint beside the game
  executable (everything else goes to upstream's own `YYToolkit.log`);
- the disk cache is replaced by patch 0001, in which the file can no longer
  decide where a hook is placed;
- the page pre-filter is re-created as original code in patch 0001, and listed;
- the ExecuteIt state is kept, but as a named, logged build switch with an
  honest reason (patch 0003);
- the optimisation level is now part of the series (patch 0006) instead of a
  property of whoever ran the compiler.
