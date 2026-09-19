# ADR 0002 — The modified YYToolkit is a patch series in the hub

**Status:** accepted, 2026-09-19
**Supersedes:** nothing. It replaces a practice, not a decision: whole-file
copies under each submodule's `yytoolkit-modified/`.
**Context:** [`third_party/yytoolkit/`](../../third_party/yytoolkit/README.md),
[`docs/agents/yytoolkit-provenance.md`](../agents/yytoolkit-provenance.md)

---

## The question

ForgePact and HS-Offline-Tracker both distribute a modified `YYToolkit.dll`.
Where does the source for it live, and in what form?

The question is open because the previous answer failed. Each of the two
repositories carried a `NOTICE.md` and two whole-file copies of changed upstream
sources, and that was taken to be the complete source. It was not: the
distributed binary's strings show changes that neither file contains, the tree
it was built from was not kept, and a fresh build of the documented source did
not get the game started. The
[story file](../agents/yytoolkit-provenance.md) has the evidence. Whatever
replaces that arrangement has to make *what we changed* the thing a reader
sees first, and has to make a binary that does not match it fail something.

## The options, and what decided between them

### Keep whole-file copies in each submodule — rejected, it is what failed

A copied file shows the result and hides the delta: nothing in it says which
lines are ours, so nothing showed that the list of changed files was short. Two
repositories held content-identical copies (differing only in line endings)
with no mechanism keeping them that way, and neither could build the DLL.

### Vendor the upstream tree into the hub — rejected

- **It trips the hub's own legal hook.** Pristine upstream v4.0.1 carries
  IDA-style auto-generated symbol names in its own comments
  (`Generic-RunnerInterfaceNew.cpp`, `Generic-RunnerInterfaceOld.cpp`, the
  Zydis amalgamation) and one line shaped like a Ghidra type declaration in
  `YYTK_Shared_Types.hpp`. `.claude/hooks/decompiled_output.py` blocks those
  signatures in any watched file; its docstring already records this class of
  hit for a vendored YYToolkit file. Vendoring would mean carrying a standing
  exemption to the rule that matters most in this repository.
- **Size.** 12,795,860 bytes of tracked files, 11,817,015 of them one file
  (`Zydis.c`), to carry changes that fit in seven patches.
- **`MAX_PATH`.** A hub worktree prefix here is 97 characters, upstream's
  longest tracked path is 87, and MSBuild's intermediate directories add more
  below that. This repository has already hit `Filename too long`
  (`tests/test_claude_hooks.py` records it).
- **It still hides the delta** — 49 upstream files with ours mixed in, which is
  the original failure at a larger scale.

### Fork upstream and add the fork as a submodule — rejected for now

- It needs a new remote and an eleventh submodule, wired through
  `submodule-dispatch.yml`, `tools/merge_submodule_pointer.py`, the guide index
  and the skill that routes to guides — machinery built for tools that publish
  releases, which this is not.
- The reasons for each change would live in another repository's commit
  history, not beside the rules (`AGENTS.md`) and the tools that depend on
  them.
- Submodule paths inside a worktree are deeper still, so the `MAX_PATH`
  problem gets worse, not better.
- **It is not foreclosed.** A patch series can be `git am`-ed onto a fork later
  without loss. The opposite direction — turning an undocumented tree back
  into reasons — is the work that just had to be done.

## Decision

The modified YYToolkit is **one pinned upstream commit plus a patch series**,
kept in the hub under `third_party/yytoolkit/`:

| File | What it is |
| --- | --- |
| `upstream.json` | The pin: repository, tag v4.0.1, the full commit id (abbreviated `5a95e46` everywhere else), that commit's tree id, and `series_revision`. The commit id is written in this file and nowhere else. |
| `patches/*.patch` + `patches/series` | One `git format-patch` file per reason, applied in `series` order. Each message carries `Why`, `Evidence`, `Fails-safe`, `Log-markers` and `Upstream-status`. Host tests travel inside the patches, under `YYToolkit/hs-tests/`. |
| `LICENSE`, `NOTICE.md` | Upstream's AGPL-3.0 text, byte for byte (a test pins its git blob id), and the modification notice. |
| `README.md` | The guide: what each patch does, how to build, the verification table, the launch gate, how to add or refresh a patch. |

[`tools/build_yytoolkit.py`](../../tools/build_yytoolkit.py) is the only
supported way to produce a binary. It exports the pinned commit *object* from a
local clone — never that clone's working tree — into a short work directory
outside the repository, refuses a tree id or blob that does not match the pin,
proves the whole series applies before touching the tree it builds, builds
`Release|x64` through upstream's project file, runs the host tests, and then
requires every declared log marker to occur in the DLL and **not** in unpatched
upstream. It records the toolchain in `YYToolkit-BUILD-INFO.json` and always
writes `live_gameplay_verified: false`; it never launches the game.

Rules that follow:

- **A change to the distributed YYToolkit is a new documented patch** — never
  an edited tree, never a replaced file.
- **A binary is never built from a tree that is not the pin plus the series.**
- **The series does not touch the plugin-facing files**
  (`YYToolkit/source/YYTK/Shared/`, `ExamplePlugin/`). Plugins compile against
  unmodified pinned headers, so a patch there would be a silent header/binary
  mismatch.
- **Patches are LF.** Upstream's blobs are LF and `git apply` compares context
  byte for byte; `.gitattributes` stops git converting the patches, and the
  tool refuses a series file or patch containing a CR byte.
- **Licence.** The hub has no root licence and the `hub/` app is MIT;
  `third_party/yytoolkit/` is a directory-scoped AGPL-3.0 aggregate with its own
  `LICENSE` and `NOTICE.md`, and the patches are original work under AGPL-3.0.
  Corresponding source for a build is upstream at the pinned commit, `patches/`
  in `series` order, and the build tool. This is an engineering reading, not
  legal advice.

`tests/test_yytoolkit_patch_series.py` enforces the mechanical part of this
offline; `tests/test_build_yytoolkit.py` tests the tool against a synthetic
upstream.

## What this gives up

Honestly stated, because it is a real cost:

- **A patch is harder to edit than a file.** Changing one means materialising
  the tree, editing, and regenerating the patch — with LF endings, and with the
  trailing TAB that terminates a patch-header path containing a space, which a
  whitespace-stripping editor destroys.
- **Offline tests prove the series is well-formed, not that it compiles.** Hub
  CI runs on Linux and does not build the DLL; a well-formed patch that breaks
  the build is caught only by running the tool on Windows.
- **The DLL's hash is meaningful on one toolset.** The build is reproducible
  there; another MSVC produces different bytes, so the hash is a check on a
  rebuild, not an identity.
- **A build needs a local clone of upstream** (or an explicit
  `--allow-network`). Nothing upstream-shaped lives in this repository.

## Consequences

- **The hub cannot change what players receive.** `.gitignore` bans `*.dll`, so
  no binary is committed, and both carriers are submodule repositories:
  ForgePact through `tools/toolchain-pins.json`, HS-Offline-Tracker through a
  git-tracked `aurie-loader/YYToolkit.dll`. Moving them to a build of this
  series is a follow-up PR in each. Both install to `mods/aurie/YYToolkit.dll`
  with overwrite semantics, so the two have to land together — otherwise
  whichever tool installs last puts its DLL back.
- **Until then the earlier DLL stays in distribution**, and the submodules'
  `yytoolkit-modified/NOTICE.md` files remain the statement for it. The hub's
  guides now say those notices are incomplete rather than implying otherwise.
- **As of this decision the series has been built, host-tested, and launched
  twice against the game (2026-09-19): first YYToolkit alone, no plugin
  loaded, then a second, idle session with ForgePact's plugin and the
  HS-Offline-Tracker producer both loaded.** In the first session the startup
  fault did not reproduce, and lag was not observed either; in the second,
  both plugins initialized and an IPC smoke test exercised the
  plugin-to-runner interface, but no gameplay was played. Neither is settled
  as fixed from one or two short sessions on one machine. The no-hint-file
  path, the verbose-dump control, gameplay with mods active, the
  error-report path with a plugin loaded, and a second machine or game build
  are still open. The launch gate in the directory's README is where the
  record and what remains open both live, and it is a person's step.
- **If a build is ever attached to a hub GitHub release, that release must be
  created with `--latest=false`.** The hub's updater reads
  `releases/latest/download/latest.json`, so any other release becoming
  "latest" silently breaks self-update — the hazard
  `.github/workflows/catalog-publish.yml` already documents for the catalog.
  How the binary travels is not decided here.
- **`ForgePact/src/forgepact.py`'s `ensure_ri_cache` table becomes
  unnecessary** once the new DLL is what players run: patch `0001` treats
  `<exe>.yytkcache` as a scan hint and never as a hook address. Deleting the
  table is a ForgePact follow-up.

**Added 2026-09-19.** Both follow-up PRs named above have been written and
committed — ForgePact's and HS-Offline-Tracker's own `claude/yytoolkit-hs1-distribution`
branches move each pin to a build of this series (sha256
`51a393d7e5291ad76bdb85b9f44faf5178b6b20e0ce8432fa26bdaf9e21eadf8`) and delete
the `ensure_ri_cache` table. **Neither branch is opened as a pull request,
neither is merged to its `origin`, and no hub GitHub release carries the
binary yet** — the decision above still holds, and players still receive the
earlier DLL. A second launch (2026-09-19) has now loaded a plugin and passed
that row of the launch gate; publishing still needs the owner's decision on
which account creates the release, plus the items that second launch left
unexercised (gameplay with mods active, the error-report path with a plugin
loaded) (`third_party/yytoolkit/README.md`, "Where the binary is published").

**Added 2026-09-19, later the same day.** The hub GitHub release named above
now exists and is published (`yytoolkit-v4.0.1-hs.1`, `--latest=false`, so the
repository's latest release is still `hub-v1.0.5`). ForgePact's pin resolves
against it: an anonymous `GET` on the asset URL returns HTTP 200 with the
expected sha256, and ForgePact's own toolchain fetcher verified all eleven
pins, including the DLL, from it. That is the library release only. Both
follow-up pull requests above are still open and neither is merged, the hub's
own ForgePact and HS-Offline-Tracker gitlinks have not moved, no tool release
has shipped the new DLL, and players still receive the earlier one. Publishing
the library release does not change any of that
(`third_party/yytoolkit/README.md`, "Where the binary is published").
