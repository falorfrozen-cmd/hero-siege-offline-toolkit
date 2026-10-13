# `crash_dump_stack.py` — which module raised a crash, read from its dump

`tools/crash_dump_stack.py` reads one Windows Error Reporting minidump through
the Windows debugger's console front end, `cdb.exe`, and names the module that
raised the crash. It exists for ForgePact issue #201: `hs_stop_game` closes the
game and reports exit code `0xC0000409`, a fast fail, and no log names who
raised it. The game's logs, YYToolkit's and ForgePact's all stop before process
teardown, which is where the abort happens. The dump's stored exception context
does name it.

Nothing here ships to a player. It is a stdlib script under `tools/`, like
`freeze_probe.ps1`, and ForgePact's plugin never runs or imports it.

## Which dump

Windows keeps the newest ten crash dumps per user in
`%LOCALAPPDATA%\CrashDumps\<exe>.<pid>.dmp`. Pick exactly one:

| Option | Reads |
|---|---|
| `--dump <path>` | that file |
| `--pid <n>` | `%LOCALAPPDATA%\CrashDumps\Hero_Siege.exe.<n>.dmp` |
| `--latest` | the newest `Hero_Siege.exe.*.dmp` there |

`--exe-name` changes the `Hero_Siege.exe` prefix. `--wait <s>` (default 0)
polls with `--pid` (or `--dump`) until the file exists and its size has stopped
changing. WER writes the dump a moment after the process has gone, so a live
procedure that has just read the exit code passes `--wait`. A dump that is
still growing when the wait runs out is refused with exit 6
(`dump at <path> still growing after <n>s`), never handed to cdb half-written;
run it again with a longer `--wait`. `--latest` skips a dump that WER rotated
out between listing the folder and reading its time.

## Where cdb comes from

cdb is part of the Windows SDK's Debugging Tools. The tool looks, in order, at
`--cdb <path>`, the `CDB_PATH` environment variable,
`%ProgramFiles(x86)%\Windows Kits\10\Debuggers\x64\cdb.exe` and `PATH`. With
none of them present it exits 5 and lists every place it looked.

The symbol path is an empty directory under the system temp directory
(`hs_crash_dump_stack_symbols`), passed with `-y`. `-sins` makes cdb ignore
`_NT_SYMBOL_PATH`, and the tool also drops that variable from cdb's
environment. So cdb never asks a symbol server and never touches the network.
Frames are named from each DLL's exports, which is why cdb's own name for a
frame can be a far-away export (`_AurieFrameworkInit+0xc0d3`). The tool prints
the frame's offset in its own module beside it, and that offset is the one to
compare with a build. cdb is bounded by `--timeout` (default 180 s). A run on
one of the kept 2026-10-13 dumps took under a second on the machine the tool
was written on.

cdb runs `.exr -1` (the exception record), `.ecxr` then `kn` (the faulting
thread's stack from the stored exception context), and `lm` (module bases, to
turn each address into a module and an offset).

If the dump has no usable exception context, `.ecxr` fails and `kn` walks
cdb's current thread instead, which need not be the exception's stack. The
tool checks for that: cdb's `.ecxr` refusal in the transcript, or a frame 0
whose call site names another module than the one holding the exception
address. Either way the header ends ` context=unverified`, a `context:` line
under it says which, frame 0 is named from its call site rather than pinned to
the exception address, and `--expect-module` exits 1 whatever `raised-in`
reads, since a match on another stack is no evidence.

## What it prints

```text
dump: C:\Users\...\CrashDumps\Hero_Siege.exe.9364.dmp pid=9364 code=0xc0000409 subcode=7 raised-in=HSOfflineTrackerProducer
  #00 ucrtbase+0xa527e  (ucrtbase!abort+0x4e)
  #01 ucrtbase+0xc218e  (ucrtbase!terminate+0x1e)
  #02 HSOfflineTrackerProducer+0x1aa03  (HSOfflineTrackerProducer!_AurieFrameworkInit+0xc0d3)
  #03 ucrtbase+0x49c85  (ucrtbase!bsearch_s+0x255)
  #04 ucrtbase+0x498a7  (ucrtbase!execute_onexit_table+0x87)
  ...
  #0a ntdll+0x8027f  (ntdll!LdrShutdownProcess+0x17f)
  #0b ntdll+0x7ef8e  (ntdll!RtlExitUserProcess+0x9e)
```

- `pid` comes from cdb's `(<pid>.<tid>)` line, or from the file name. It is
  `?` when neither has it.
- `code` is the exception code. `subcode` is the fast-fail code cdb decodes for
  `0xC0000409` (7 is `FAST_FAIL_FATAL_APP_EXIT`, what `abort()` raises). It is
  `none` for any other exception.
- `raised-in` is the topmost frame whose module is not one of the runtime's
  own: `ucrtbase` (and the debug `ucrtbased`), `ntdll`, `kernel32`,
  `kernelbase`, `vcruntime140*` and `msvcp140*`. Those only carry a fault raised
  elsewhere: the C runtime's `abort` and `terminate`, the loader's teardown,
  the exit call. It is `none` when every frame is the runtime's. It is judged
  over every frame cdb listed (at least 16), not only the ones printed, so
  `--frames 1` still names the producer at frame `#02`.
- One line per frame follows, `--frames` of them (default 12), as
  `<module>+0x<offset in that module>` with cdb's name in brackets when it
  differs. A frame outside every loaded module prints `<no module> 0x<addr>`.

The example is the tracker producer's exit-time abort. Every 2026-10-12/13
dump kept on the machine the tool was written on shows it. The producer's
static `std::thread` destructor runs from its `_execute_onexit_table` under
`LdrShutdownProcess` and calls `terminate`, which a `std::thread` destructor
does when its thread is still joinable (inferred from the stack, not measured).
The producer's return address is its own offset `0x1aa03`, inside the
destructor at `0x1a9f0` that ForgePact's guide already names.

`--expect-module <name>` compares `raised-in` with a name, case-insensitively
and with or without `.dll`, for a live procedure to assert on:

```powershell
py -3 tools/crash_dump_stack.py --latest
py -3 tools/crash_dump_stack.py --pid 20580 --wait 30 --expect-module HSOfflineTrackerProducer
py -3 tools/crash_dump_stack.py --dump <path.dmp> --frames 20
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | parsed, and `--expect-module` (if given) matched |
| 1 | `--expect-module` did not match, or was given and the stack was `context=unverified` (without `--expect-module`, an unverified stack exits 0 and is flagged only in the header). The output still prints, and stderr names both |
| 2 | usage error, from argparse: two of `--dump`/`--pid`/`--latest`, none of them, or a bad value |
| 3 | no dump: the `--pid` file is absent (after `--wait`), or `--latest` found none |
| 4 | cdb ran and no exception record was parsed. stderr carries cdb's last lines |
| 5 | no cdb. The message lists every place looked |
| 6 | the dump was still growing when `--wait` ran out; cdb was not run |

## What it never does

- **It writes only its temp symbol directory.** It never moves, deletes or
  edits a dump, and never opens or attaches to a running process. cdb opens the
  dump file only.
- **It never reaches the network.** See the symbol path above.
- **Its output stays on this machine when it names the game.** The frames are
  module names and offsets of our DLLs, third-party DLLs and the game's own
  image. Our and third-party module names and offsets are interoperability
  facts and fine to write down. A game offset (`Hero_Siege+0x...`) is a research
  reading for this build and is never pasted into a tracked file, commit
  message, issue or PR (AGENTS.md, "Legal: Decompiled Output Never Reaches Any
  Origin").

## Tests

`tests/test_crash_dump_stack.py` stubs cdb with a transcript shaped like the
2026-10-12 dumps, so it needs no debugger and no dump. The game frames in it
carry made-up offsets below `0x10000`. It covers parsing, `--expect-module`
with a negative control where another module raised the crash, `--frames 1`
and `2` still attributing the producer, a failed `.ecxr` and a frame 0 outside
the exception's module (each against the verified producer stack as control),
missing cdb and a usage error on different codes, `--pid`/`--latest`/`--wait`,
a dump still growing at the end of the wait, a `--latest` match that vanished
before its stat, no dump, an unparsed transcript, and that the symbol path is
local and offline:

```powershell
py -3 -m unittest tests.test_crash_dump_stack -v
```
