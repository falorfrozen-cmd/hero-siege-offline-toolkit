"""tools/crash_dump_stack.py: which module raised the crash a WER dump recorded.

ForgePact #201 asks why `hs_stop_game` reports `0xC0000409`. The kept dumps
answer it through cdb, and this tool turns cdb's transcript into one line,
`dump: ... code=0x... subcode=... raised-in=<module>`, so a live procedure can
assert on it. cdb is stubbed throughout: every case hands the tool a
transcript shaped like the 2026-10-12 dumps (the exit-time abort raised from
`HSOfflineTrackerProducer`'s `std::thread` destructor, under the loader's
teardown), so no debugger and no real dump is needed. The game's own frames in
the fixtures carry made-up offsets below 0x10000; nothing here is a reading of
the game.

The baseline is the negative control - the same shape with `BloodPactPlugin`
as the first non-runtime frame must fail `--expect-module
HSOfflineTrackerProducer` - and the target is the producer named on the
producer's stack. The rest pin the refusals (no cdb, no dump, a dump still
being written), that `--frames` cuts only what is printed and never what
`raised-in` is judged over, that a stack which is not the exception's (`.ecxr`
failed, or frame 0 in another module than the exception address) is said so
rather than mixed in, and that the symbol path is an empty local directory, so
the tool never asks a symbol server.
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import crash_dump_stack as cds  # noqa: E402

# Module bases are made up; the game image's frames sit below 0x10000 in it.
LM = """\
start             end                 module name
00007ff7`10000000 00007ff7`18000000   Hero_Siege   (deferred)
00007ff8`16b30000 00007ff8`16b98000   HSOfflineTrackerProducer   (deferred)
00007ff8`20000000 00007ff8`20400000   BloodPactPlugin   (deferred)
00007ff8`6f3f0000 00007ff8`6f53c000   ucrtbase   (export symbols)       ucrtbase.dll
00007ff8`71c60000 00007ff8`71d30000   kernel32   (export symbols)       kernel32.dll
00007ff8`720c0000 00007ff8`72330000   ntdll      (export symbols)       ntdll.dll

Unloaded modules:
00007ff8`30000000 00007ff8`30010000   SomethingUnloaded.dll
"""


def transcript(raising_module: str = "HSOfflineTrackerProducer", raising_base: int = 0x7FF816B30000,
               pid_hex: str = "50a4") -> str:
    """A cdb transcript shaped like the 2026-10-12 producer-abort dumps."""
    ra = raising_base + 0x1AA03
    ra_text = f"{ra >> 32:08x}`{ra & 0xFFFFFFFF:08x}"
    return f"""\
Microsoft (R) Windows Debugger Version 10.0.19041.1 AMD64

Loading Dump File [C:\\fake\\Hero_Siege.exe.20644.dmp]
User Mini Dump File: Only registers, stack and portions of memory are available

Symbol search path is: C:\\fake\\symbols
This dump file has an exception of interest stored in it.
({pid_hex}.3a10): Security check failure or stack buffer overrun - code c0000409 (first/second chance not available)
ucrtbase!abort+0x4e:
00007ff8`6f49527e cd29            int     29h
0:000> cdb: Reading initial command '...'
{cds.MARK_EXR}
ExceptionAddress: 00007ff86f49527e (ucrtbase!abort+0x000000000000004e)
   ExceptionCode: c0000409 (Security check failure or stack buffer overrun)
  ExceptionFlags: 00000001
NumberParameters: 1
   Parameter[0]: 0000000000000007
Subcode: 0x7 FAST_FAIL_FATAL_APP_EXIT
{cds.MARK_STACK}
rax=0000000000000001 rbx=000001b9a6cdf748 rcx=0000000000000007
ucrtbase!abort+0x4e:
00007ff8`6f49527e cd29            int     29h
 # Child-SP          RetAddr           Call Site
00 00000054`fe75f2a0 00007ff8`6f4b218e ucrtbase!abort+0x4e
*** WARNING: Unable to verify checksum for {raising_module}.dll
01 00000054`fe75f2d0 {ra_text} ucrtbase!terminate+0x1e
02 00000054`fe75f300 00007ff8`6f439c85 {raising_module}!_AurieFrameworkInit+0xc0d3
03 00000054`fe75f330 00007ff8`6f4398a7 ucrtbase!bsearch_s+0x255
04 00000054`fe75f380 00007ff8`7214027f ucrtbase!execute_onexit_table+0x87
05 00000054`fe75f790 00007ff8`71c7147b ntdll!LdrShutdownProcess+0x17f
06 00000054`fe75f8d0 00007ff7`100040ed kernel32!FatalExit+0xb
07 00000054`fe75f900 00007ff7`100020a3 Hero_Siege+0x40ed
08 00000054`fe75f930 00000000`00000286 Hero_Siege+0x20a3
09 00000054`fe75f9d8 00000000`00000000 0x286
{cds.MARK_LM}
{LM}{cds.MARK_END}
quit:
"""


# Another thread's stack, as `kn` walks it when `.ecxr` could not set the
# exception's context: frame 0 is not at the exception address.
OTHER_THREAD_ROWS = """\
 # Child-SP          RetAddr           Call Site
00 00000054`fe700000 00007ff8`20001234 ntdll!NtWaitForSingleObject+0x14
01 00000054`fe700030 00007ff8`71c7147b BloodPactPlugin!SomeExport+0x10
02 00000054`fe700060 00000000`00000000 kernel32!BaseThreadInitThunk+0x1d
"""


def with_stack(stack_block: str) -> str:
    """The producer transcript with its stack section replaced."""
    whole = transcript()
    head, rest = whole.split(cds.MARK_STACK + "\n", 1)
    _, tail = rest.split(cds.MARK_LM + "\n", 1)
    return f"{head}{cds.MARK_STACK}\n{stack_block}{cds.MARK_LM}\n{tail}"


def run(argv, cdb_output=None, captured=None):
    """main() with run_cdb stubbed; returns (exit code, stdout, stderr)."""
    def fake_run(command, env, timeout):
        if captured is not None:
            captured.append((command, env, timeout))
        return cdb_output if cdb_output is not None else transcript()

    out, err = io.StringIO(), io.StringIO()
    with patch.object(cds, "run_cdb", fake_run), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cds.main(argv)
    return code, out.getvalue(), err.getvalue()


class CrashDumpStackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cdb = self.root / "cdb.exe"
        self.cdb.write_bytes(b"stub")
        self.local = self.root / "Local"
        (self.local / "CrashDumps").mkdir(parents=True)
        env = patch.dict(os.environ, {"LOCALAPPDATA": str(self.local)})
        env.start()
        self.addCleanup(env.stop)

    def dump(self, name: str = "Hero_Siege.exe.20644.dmp") -> Path:
        path = self.local / "CrashDumps" / name
        path.write_bytes(b"MDMP" + b"\0" * 64)
        return path

    def test_parses_the_fast_fail_and_the_module_that_raised_it(self):
        path = self.dump()
        code, out, err = run(["--dump", str(path), "--cdb", str(self.cdb)])
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertEqual(
            lines[0],
            f"dump: {path} pid={0x50a4} code=0xc0000409 subcode=7 raised-in=HSOfflineTrackerProducer")
        # Frames are module-relative: the producer's return address is its own
        # offset 0x1aa03, the game's frames their (made-up) offsets in its image.
        self.assertIn("  #00 ucrtbase+0xa527e  (ucrtbase!abort+0x4e)", lines)
        self.assertIn("  #02 HSOfflineTrackerProducer+0x1aa03  (HSOfflineTrackerProducer!_AurieFrameworkInit+0xc0d3)", lines)
        self.assertIn("  #07 Hero_Siege+0x40ed", lines)
        self.assertIn("  #09 <no module> 0x286", lines)
        self.assertEqual(len(lines), 1 + 10)

    def test_frames_limits_the_stack_printed(self):
        path = self.dump()
        code, out, _ = run(["--dump", str(path), "--cdb", str(self.cdb), "--frames", "3"])
        self.assertEqual(code, 0)
        self.assertEqual(len(out.splitlines()), 1 + 3)
        self.assertIn("raised-in=HSOfflineTrackerProducer", out)

    def test_frames_never_changes_raised_in(self):
        # The producer is frame #02. Printing one or two frames must not hide
        # it from the attribution, nor from --expect-module.
        path = self.dump()
        for frames in ("1", "2"):
            with self.subTest(frames=frames):
                code, out, err = run(["--dump", str(path), "--cdb", str(self.cdb), "--frames", frames,
                                      "--expect-module", "HSOfflineTrackerProducer"])
                self.assertEqual(code, 0, err)
                lines = out.splitlines()
                self.assertTrue(lines[0].endswith("raised-in=HSOfflineTrackerProducer"), lines[0])
                self.assertEqual(len(lines), 1 + int(frames))
                self.assertNotIn("HSOfflineTrackerProducer+", out)
        report = cds.parse_transcript(transcript())
        self.assertEqual(report.raised_in, "HSOfflineTrackerProducer")
        self.assertEqual(len(report.frames), 10)

    def test_expect_module_passes_on_the_producer_stack(self):
        path = self.dump()
        for spelling in ("HSOfflineTrackerProducer", "hsofflinetrackerproducer.dll", "HSOfflineTrackerProducer.DLL"):
            code, _, err = run(["--dump", str(path), "--cdb", str(self.cdb), "--expect-module", spelling])
            self.assertEqual(code, 0, f"{spelling}: {err}")

    def test_negative_control_another_module_fails_expect_module(self):
        path = self.dump()
        other = transcript("BloodPactPlugin", 0x7FF820000000)
        code, out, err = run(["--dump", str(path), "--cdb", str(self.cdb),
                              "--expect-module", "HSOfflineTrackerProducer"], other)
        self.assertEqual(code, 1)
        self.assertIn("raised-in=BloodPactPlugin", out)
        self.assertIn("expected raised-in=HSOfflineTrackerProducer, got BloodPactPlugin", err)

    def test_runtime_modules_never_count_as_the_raiser(self):
        for name in ("ucrtbase", "ucrtbased", "ntdll", "KERNEL32", "kernelbase.dll",
                     "vcruntime140", "vcruntime140_1", "msvcp140", "msvcp140_atomic_wait"):
            self.assertTrue(cds.is_runtime_module(name), name)
        for name in ("HSOfflineTrackerProducer", "BloodPactPlugin", "YYToolkit", "Hero_Siege"):
            self.assertFalse(cds.is_runtime_module(name), name)

    def test_missing_cdb_exits_5_and_says_where_it_looked(self):
        path = self.dump()
        nowhere = self.root / "nowhere"
        with patch.dict(os.environ, {"CDB_PATH": str(nowhere / "cdb.exe"), "ProgramFiles(x86)": str(nowhere)}), \
                patch.object(cds.shutil, "which", return_value=None):
            code, out, err = run(["--dump", str(path), "--cdb", str(nowhere / "explicit-cdb.exe")])
        self.assertEqual(code, cds.EXIT_NO_CDB)
        self.assertEqual(code, 5)
        self.assertEqual(out, "")
        self.assertIn(str(nowhere / "explicit-cdb.exe"), err)
        self.assertIn(f"CDB_PATH: {nowhere / 'cdb.exe'}", err)
        self.assertIn(str(nowhere / "Windows Kits" / "10" / "Debuggers" / "x64" / "cdb.exe"), err)
        self.assertIn("PATH: cdb not found", err)

    def test_a_usage_error_is_not_the_no_cdb_code(self):
        # argparse exits 2 on a usage error; "no cdb" must not share it.
        path = self.dump()
        for argv in (["--dump", str(path), "--pid", "1"], ["--cdb", str(self.cdb)]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    cds.main(argv)
                self.assertEqual(caught.exception.code, 2)
        codes = (cds.EXIT_OK, cds.EXIT_MODULE_MISMATCH, cds.EXIT_NO_DUMP, cds.EXIT_NOT_PARSED,
                 cds.EXIT_NO_CDB, cds.EXIT_DUMP_GROWING)
        self.assertEqual(len(set(codes)), len(codes))
        self.assertNotIn(2, codes)

    def test_pid_finds_the_crashdumps_file(self):
        path = self.dump("Hero_Siege.exe.20644.dmp")
        self.dump("Hero_Siege.exe.111.dmp")
        captured = []
        code, out, err = run(["--pid", "20644", "--cdb", str(self.cdb)], captured=captured)
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith(f"dump: {path} "))
        command = captured[0][0]
        self.assertEqual(command[command.index("-z") + 1], str(path))
        # --exe-name changes the prefix it looks for.
        other = self.dump("Other.exe.20644.dmp")
        code, out, _ = run(["--pid", "20644", "--exe-name", "Other.exe", "--cdb", str(self.cdb)])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith(f"dump: {other} "))

    def test_latest_reads_the_newest_dump(self):
        old = self.dump("Hero_Siege.exe.1.dmp")
        new = self.dump("Hero_Siege.exe.2.dmp")
        os.utime(old, (1_000_000, 1_000_000))
        os.utime(new, (2_000_000, 2_000_000))
        code, out, _ = run(["--latest", "--cdb", str(self.cdb)])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith(f"dump: {new} "))

    def test_latest_skips_a_dump_rotated_out_after_the_glob(self):
        # WER can delete the oldest dump between the glob and the stat: that
        # file is skipped, not a traceback.
        folder = self.local / "CrashDumps"
        present = self.dump("Hero_Siege.exe.2.dmp")
        vanished = folder / "Hero_Siege.exe.1.dmp"
        with patch.object(cds.Path, "glob", lambda self, pattern: iter([vanished, present])):
            code, out, err = run(["--latest", "--cdb", str(self.cdb)])
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith(f"dump: {present} "))
        # Every match gone by the stat: no dump, exit 3.
        with patch.object(cds.Path, "glob", lambda self, pattern: iter([vanished])):
            code, out, err = run(["--latest", "--cdb", str(self.cdb)])
        self.assertEqual(code, cds.EXIT_NO_DUMP)
        self.assertEqual(out, "")

    def test_no_dump_for_the_pid_exits_3(self):
        self.dump("Hero_Siege.exe.111.dmp")
        captured = []
        code, out, err = run(["--pid", "222", "--cdb", str(self.cdb)], captured=captured)
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertIn("Hero_Siege.exe.222.dmp", err)
        self.assertEqual(captured, [], "cdb must not run without a dump")
        with patch.object(cds.time, "sleep", lambda s: None):
            code, _, err = run(["--pid", "222", "--wait", "0.01", "--cdb", str(self.cdb)])
        self.assertEqual(code, 3)
        self.assertIn("after waiting", err)
        for leftover in (self.local / "CrashDumps").glob("*.dmp"):
            leftover.unlink()
        code, _, err = run(["--latest", "--cdb", str(self.cdb)])
        self.assertEqual(code, 3)

    def test_wait_returns_once_the_size_holds(self):
        # WER is still writing on the first poll: the file grows once, then holds.
        path = self.dump()
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 1:
                with open(path, "ab") as fh:
                    fh.write(b"\0" * 32)

        with patch.object(cds.time, "sleep", fake_sleep):
            self.assertEqual(cds._wait_stable(path, 30), (cds.DUMP_STABLE, 68 + 32))
        self.assertEqual(len(sleeps), 2)

    def test_a_dump_still_growing_when_the_wait_ends_is_refused(self):
        # WER is still writing at every poll: the tool refuses with its own
        # code and never hands the half-written file to cdb.
        path = self.dump()
        clock = [0.0]

        def growing_sleep(seconds):
            clock[0] += seconds
            with open(path, "ab") as fh:
                fh.write(b"\0" * 16)

        captured = []
        with patch.object(cds.time, "sleep", growing_sleep), \
                patch.object(cds.time, "monotonic", lambda: clock[0]):
            self.assertEqual(cds._wait_stable(path, 2)[0], cds.DUMP_GROWING)
            code, out, err = run(["--pid", "20644", "--wait", "2", "--cdb", str(self.cdb)], captured=captured)
        self.assertEqual(code, cds.EXIT_DUMP_GROWING)
        self.assertEqual(code, 6)
        self.assertEqual(out, "")
        self.assertIn("still growing after 2s", err)
        self.assertEqual(captured, [], "cdb must not run on a dump still being written")
        # Positive control: the same wait on a dump that holds still reads it.
        clock[0] = 0.0
        with patch.object(cds.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s)), \
                patch.object(cds.time, "monotonic", lambda: clock[0]):
            code, out, err = run(["--pid", "20644", "--wait", "2", "--cdb", str(self.cdb)])
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith(f"dump: {path} "))

    def test_unparsed_transcript_exits_4(self):
        path = self.dump()
        code, out, err = run(["--dump", str(path), "--cdb", str(self.cdb)], "Could not open dump file\nquit:\n")
        self.assertEqual(code, 4)
        self.assertEqual(out, "")
        self.assertIn("no exception record", err)

    def test_a_failed_ecxr_is_said_and_never_mixed_into_the_attribution(self):
        # `.ecxr` failed, so `kn` walked another thread: frame 0 must not be
        # pinned to the exception address, and the header says so.
        path = self.dump()
        failed = with_stack("Unable to get exception context, HRESULT 0x80004002\n" + OTHER_THREAD_ROWS)
        code, out, err = run(["--dump", str(path), "--cdb", str(self.cdb)], failed)
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertTrue(lines[0].endswith("raised-in=BloodPactPlugin context=unverified"), lines[0])
        self.assertTrue(lines[1].startswith("  context: .ecxr failed (Unable to get exception context"), lines[1])
        self.assertEqual(lines[2], "  #00 ntdll  (ntdll!NtWaitForSingleObject+0x14)")
        self.assertNotIn("ucrtbase+0xa527e", out)
        self.assertIn("  #01 BloodPactPlugin+0x1234  (BloodPactPlugin!SomeExport+0x10)", lines)
        # --expect-module never matches an unverified stack, even its own raiser.
        code, _, err = run(["--dump", str(path), "--cdb", str(self.cdb), "--expect-module", "BloodPactPlugin"],
                           failed)
        self.assertEqual(code, cds.EXIT_MODULE_MISMATCH)
        self.assertIn("not verified", err)

    def test_frame_zero_outside_the_exception_module_is_unverified(self):
        # No failure text, but frame 0 is in ntdll while the exception
        # address is in ucrtbase: the same verdict.
        path = self.dump()
        code, out, err = run(["--dump", str(path), "--cdb", str(self.cdb)], with_stack(OTHER_THREAD_ROWS))
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertTrue(lines[0].endswith(" context=unverified"), lines[0])
        self.assertIn("frame 0 is in ntdll", lines[1])
        self.assertIn("is in ucrtbase", lines[1])
        # Negative control: the producer's own stack, frame 0 in ucrtbase at
        # the exception address, is verified and carries no context field.
        self.assertIsNone(cds.parse_transcript(transcript()).context_problem)
        code, out, _ = run(["--dump", str(path), "--cdb", str(self.cdb)])
        self.assertNotIn("context", out)

    def test_symbol_path_is_local_and_offline(self):
        path = self.dump()
        captured = []
        temp_root = self.root / "systemp"
        temp_root.mkdir()
        with patch.dict(os.environ, {"_NT_SYMBOL_PATH": "srv*C:\\sym*https://msdl.microsoft.com/download/symbols",
                                     "_NT_ALT_SYMBOL_PATH": "srv*https://example.invalid"}), \
                patch.object(cds.tempfile, "gettempdir", return_value=str(temp_root)):
            code, _, err = run(["--dump", str(path), "--cdb", str(self.cdb)], captured=captured)
        self.assertEqual(code, 0, err)
        command, env, timeout = captured[0]
        symbols = Path(command[command.index("-y") + 1])
        self.assertEqual(symbols.parent, temp_root)
        self.assertTrue(symbols.is_dir())
        self.assertEqual(list(symbols.iterdir()), [])
        self.assertIn("-sins", command)
        joined = " ".join(command).lower()
        for marker in ("srv*", "http", "symsrv", ".sympath", ".symfix"):
            self.assertNotIn(marker, joined)
        for key in env:
            self.assertNotIn(key.upper(), ("_NT_SYMBOL_PATH", "_NT_ALT_SYMBOL_PATH"))
        self.assertGreater(timeout, 0)


if __name__ == "__main__":
    unittest.main()
