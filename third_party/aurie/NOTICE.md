# NOTICE - this is a MODIFIED Aurie

The `AurieCore.dll` this notice accompanies is **Aurie (Aurie Core), modified**
by the Hero Siege Offline Toolkit project. It is not upstream's binary, and
upstream did not make, review or endorse the changes. Problems with this build
belong in the toolkit's issue tracker, not upstream's.

| | |
| --- | --- |
| Work | Aurie, the Aurie Framework project's module loader (`AurieCore.dll`) |
| Upstream | https://github.com/AurieFramework/Aurie |
| Base | tag `v2.0.2`, commit `5c4839e` (the full commit id and tree id are in `upstream.json` and in `AurieCore-BUILD-INFO.json`) |
| Licence | AGPL-3.0 (GNU Affero General Public License, version 3). `LICENSE` beside this file is upstream's text, byte for byte. |
| Our changes | Original work of the Hero Siege Offline Toolkit project, licensed AGPL-3.0, dated 2026-10-06 |
| Series revision | `hs.1` - the same string is in `upstream.json` and in the line this DLL writes to `aurie.log` straight after Aurie's own `loaded at` line |

Copyright in Aurie remains with its upstream authors. This directory is an
AGPL-3.0 aggregate inside the toolkit's hub repository: its licence does not
extend to the rest of that repository, and theirs does not extend to it. The
program comes with no warranty, as set out in the licence.

## What we changed

Every change is one patch file under `third_party/aurie/patches/`, applied in
the order given by `patches/series`. Both are dated **2026-10-06**. Each patch's
message states why it exists, the evidence, what happens when it cannot do its
job, the log lines it adds, and its upstream status; the directory's
`README.md` is the guide.

1. `0001-series-identity.patch` - One log line after upstream's
   `Aurie Core v2.0.2 loaded at <address>` names the upstream version and this
   series' revision:
   `[hs] Aurie Core 2.0.2, Hero Siege patch series hs.1 (hero-siege-offline-toolkit, third_party/aurie)`.
   Nothing else changes.
2. `0002-per-process-hook-freeze.patch` - While a hook is written or removed
   (`MmCreateHook`, `MmCreateUnsafeHook`, `MmCreateMidfunctionHook` and the
   three removals), Aurie suspends every other thread of the process. Upstream
   finds those threads with two thread snapshots of the whole system; the
   patched freeze lists only this process's threads, through ntdll's
   `NtGetNextThread` resolved by name, repeats the walk until no new thread
   appears, waits until each suspension has taken effect, and resumes exactly
   the threads it suspended. When it cannot do that, it runs upstream's walk
   unchanged and says so in one log line. The new code is in a new file,
   `thread_freeze.cpp`; `MmpFreezeCurrentProcess` and `MmpResumeCurrentProcess`
   keep their names, signatures and call sites, and no exported function
   changes.

The plugin-facing header `Aurie/source/framework/shared.hpp` is not modified,
and neither are `AuriePatcher`, `AurieInstaller` or the `AURIE_FWK_*` version
numbers: a plugin built against upstream's v2.0.2 headers loads as before. The
host test for patch 0002 is added under `Aurie/hs-tests/` by the patch itself;
it is not part of the DLL.

## Corresponding source

The complete corresponding source of this binary is:

1. upstream Aurie at the commit pinned in `third_party/aurie/upstream.json`
   (repository URL above; the tree id in the same file lets you verify the
   export);
2. the patches in `third_party/aurie/patches`, applied in the order of
   `patches/series`;
3. the build tool `tools/build_aurie.py` from the same hub commit (an entry
   point to `tools/build_yytoolkit.py`'s Aurie profile), which exports the pin,
   applies the series, builds upstream's own `Aurie/AurieCore.vcxproj`
   (Release, x64) and checks the result.

`AurieCore-BUILD-INFO.json`, shipped beside the binary, records the upstream
commit and tree, the hub commit, the sha256 of every patch, the compiler and
toolset versions and the DLL's size and sha256. The `aurie-source-<id>.zip`
published with it is a copy of `third_party/aurie/` (item 2 and the pin of item
1). It does not contain upstream's source or the build tool: the first is
public at the upstream URL above, the second in the toolkit's hub repository
(`hero-siege-offline-toolkit`, the name this DLL prints in its identity line)
at the hub commit BUILD-INFO records.

## State of verification on 2026-10-06

Built, host-tested (1 of 1 host test files, every case passing) and checked
for every log line the patches declare; upstream's v2.0.2 release DLL fails
the same marker check, as it should. **Not yet launched against the game.**
The directory's `README.md` carries the launch gate; until its rows carry a
date, this build's effect in the game is not established.
