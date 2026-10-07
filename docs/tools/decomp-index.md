# `decomp_index.py` — which game scripts are already decompiled, and slot names

`tools/decomp_index.py` answers one question before anyone opens Ghidra: has
this script already been decompiled for the game build in hand, and where is
the file? During ForgePact #160 the local decompiles had no index, so scripts
were decompiled again without the earlier output being found, and a live
session was planned around a script the cast never reached (hub issue #413).
The same tool also carries the slot-name technique #160 used to name globals
the decompiler had left unnamed.

Nothing here ships to a player. It is a stdlib script under `tools/`, like
`source_index.py` and `stash_tab_counts.py`, and it needs no Ghidra run.

The index covers files written by a headless run. A decompile through the
`ghidra` MCP server ([ghidra-mcp.md](ghidra-mcp.md)) writes no file, so it has
nothing to `scan`, and asking the server again is cheap.

## Where the index lives, and why never in a repository

The index is one JSON Lines file on the researcher's machine, next to the
decompiles: `%USERPROFILE%\tools\hs-decomp\decomp-index.jsonl` by default. It
holds one record per (file path, build): the name, the variant, the address
from the file's header line, the build, the path, the size, the file's
modification time, when it was recorded, and a note. It never holds a line of
a decompile's body.

The decompiles themselves may never reach any origin (`AGENTS.md` § "Legal:
Decompiled Output Never Reaches Any Origin"), and an index of them belongs with
them. So the tool refuses, with exit 2 and nothing written, to put the index or
an annotated copy anywhere that has a `.git` entry (a directory, or the file a
worktree uses) in itself or any parent. That check runs no git process, so it
also catches a checkout other than this one. `.gitignore` lists
`decomp-index*.jsonl` as a second, mechanical backstop.

## Environment overrides

- `HS_DECOMP_INDEX`: the index file, instead of the default above. `--index`
  overrides it per call.
- `HS_DECOMP_EXE`: the game executable whose sha256 is the build, instead of
  `%USERPROFILE%\tools\hs-bin\Hero_Siege.exe` (the copy the local Ghidra project
  was imported from). `--exe` overrides it per call, and `--build <sha|text>`
  skips hashing altogether. When no build can be found, the tool exits 2 and
  names both options.

## Subcommands

Every example runs from this checkout's root.

- **`has QUERY`**: is it decompiled for this build? The query is normalised the
  way the file labels are (a leading `gml_Script_` dropped, characters outside
  `[A-Za-z0-9_.-]` mapped to `_`) and matched exactly; `--contains` makes it a
  case-insensitive substring, and a `0x<hex>` query matches the header address.
  Exit 0 prints one line per record (name, variant, short build, date, path,
  note). Exit 1 means no record for this build: matches for another build are
  still printed, marked `[other build]`, so a stale decompile reads as stale
  rather than missing. A missing index also exits 1 and says to run `scan`.

  ```powershell
  py -3 tools/decomp_index.py has LoadProjectileSettings
  ```

- **`scan PATH... [--note TEXT]`**: record every `.c` file under the given files
  or folders. It is idempotent: a second scan adds nothing, and a file whose
  size or modification time changed is updated. It prints the added, updated and
  unchanged counts and names every file it could not name.

  ```powershell
  py -3 tools/decomp_index.py scan "$env:USERPROFILE\tools\hs-decomp\issue160"
  ```

- **`build-hash [--exe PATH]`**: print the executable's sha256, the build id
  every record carries.

  ```powershell
  py -3 tools/decomp_index.py build-hash
  ```

- **`slot-name ADDR...`**: name variable-slot globals by their slot address.
  Prints `ADDR name`, or `ADDR ?` when it cannot tell, and exits 1 if any
  address stayed `?`.

  ```powershell
  py -3 tools/decomp_index.py slot-name 0x<slot address from a decompile>
  ```

- **`find-name NAME...`**: the reverse: the slot address of each global with that
  name, or `NAME ?` (exit 1).

  ```powershell
  py -3 tools/decomp_index.py find-name projEffect maxScale
  ```

- **`annotate IN OUT`**: copy a decompile, replacing each unnamed global data
  token whose slot resolves with `V_<name>`, and leaving every other token as it
  was. OUT must be outside any git tree.

  ```powershell
  py -3 tools/decomp_index.py annotate Foo.c Foo.n.c
  ```

## How a file is named

The `DecompileTo*.java` reading scripts in `ForgePact/tools/ghidra/` (see
[its README](../../ForgePact/tools/ghidra/README.md)) start each `.c` file with our own
header line, `// <label> @ <hex address> size=<n>`, where the label is the
function's name with every character outside `[A-Za-z0-9_.-]` mapped to `_`. The
label is the record's name. A label with spaces (the "function containing ..."
form one script writes) is not a name, so the file name gives it instead.
Derived copies, `Name.s.c`, `Name.s.n.c`, `Name.s.r.c`, `Name.a.c` and
`Name.n.c`, index under `Name`, with the dotted suffix kept as the variant.
Only `.c` files are indexed, and only their first line is read.

## Recording after a headless run

The four decompiling scripts in `ForgePact/tools/ghidra/` (`DecompileTo`,
`DecompileToLong`, `DecompileToHuge`, `DecompileAround`) end each run by printing
the `scan` line for the directory they wrote, to run from this checkout's root.
They only print it: no Ghidra script calls the index or reads a hub path. To make
the record automatic, add the same line after the `analyzeHeadless` call in the
run wrapper (`.cmd`) that wrote the output:

```bat
py -3 "<this checkout>\tools\decomp_index.py" scan "%OUTDIR%"
```

The run wrappers are each researcher's own, since they carry that machine's
Ghidra, JDK and project paths, so this is a line each researcher adds to their
own wrappers; nothing here installs it.

## The backfill, and its caveat

The first index on the owner's machine was written by one `scan` over the whole
local store, attributed to the sha256 of `%USERPROFILE%\tools\hs-bin\Hero_Siege.exe`,
the executable the `HeroSiege` Ghidra project was imported from. Every `.c` file
in the store is dated after that import. Two folders' wrappers named a different
project, both apparently copies made to get around Ghidra's project lock; that
they hold the same executable is **not verified**, which is what the backfill's
`--note` records. If that is ever in doubt, rescan those two folders with
`--build unknown`.

## The slot-name technique

The game's runtime keeps each variable-slot global in a 16-byte table entry. The
first 8 bytes point at the variable's name, a NUL-terminated ASCII string inside
the executable; the next 8 bytes are the slot itself. So, for a slot at address
A, the little-endian pointer stored at A-8 names it. A decompiler shows these
globals as bare data addresses; in #160 this named `projEffect`, `maxScale`,
`image_xscale`, `image_yscale` and `loadSettings` in bodies the decompiler had
left unnamed (ForgePact `docs/skill-sliders-research.md`).

The tool reads the executable as a PE32+ file itself (image base, section table,
address-to-file-offset mapping) and accepts nothing else. `slot-name` answers
only when the pointer at A-8 lies inside a section and points at the start of a
string (the byte before is NUL) that is an identifier
(`[A-Za-z_][A-Za-z0-9_]{0,62}`, NUL-terminated); otherwise it prints `?`, never
a guess. A pointer into the middle of a longer string is a `?`, not the
string's tail. `find-name` looks for `NAME` followed by a NUL at the start of a
string by the same rule, then for every 8-byte pointer to it, and prints each
pointer's location plus 8, so the two subcommands agree. `annotate` uses
`slot-name`'s check and keeps every token it cannot name. No address of any build is written into the tool:
addresses are measured on the executable in hand each time.

The technique was first written as throwaway scripts in the #160 research
folder. Those scripts loaded each other at run time and carried one build's
addresses, so the technique was rewritten here rather than copied. Three other
helpers from that folder stay local, outside every repository: `ripscan.py`
(needs numpy), `calls.py` (reads `symbols.csv` and three build-specific
values) and `regionvars.py` (correct only inside one build's slot range).

## The decompiler's ceiling

Some functions do not decompile within the decompiler's default limits, and
raising the limits did not help. See
[`docs/agents/static-model-workflow.md`](../agents/static-model-workflow.md#tooling-findings)
for the case, the settings that were tried, and what to do instead.

## Its controls

`tests/test_decomp_index.py` runs on temp-directory fixtures and a minimal PE32+
the test builds with an image base far below the game's, never on the real store
or executable. It pins the empty store (`has` exits 1), lookups by name, prefix,
address, substring and build, variant naming, idempotent scans, that the index
holds no body text (a sentinel string in the fixture body), the git-tree refusals
for the index and for `annotate`, and, for the slot technique, a resolvable slot,
unresolvable ones, and a pointer into a string that only ends with the name,
which `find-name` does not list and `slot-name` and `annotate` do not name.

```powershell
py -3 -m unittest tests.test_decomp_index -v
```
