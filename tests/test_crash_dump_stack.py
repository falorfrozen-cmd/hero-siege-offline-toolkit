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
producer's stack. The rest pin the refusals (no cdb, no dump) and that the
symbol path is an empty local directory, so the tool never asks a symbol server.
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

    def test_missing_cdb_exits_2_and_says_where_it_looked(self):
        path = self.dump()
        nowhere = self.root / "nowhere"
        with patch.dict(os.environ, {"CDB_PATH": str(nowhere / "cdb.exe"), "ProgramFiles(x86)": str(nowhere)}), \
                patch.object(cds.shutil, "which", return_value=None):
            code, out, err = run(["--dump", str(path), "--cdb", str(nowhere / "explicit-cdb.exe")])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn(str(nowhere / "explicit-cdb.exe"), err)
        self.assertIn(f"CDB_PATH: {nowhere / 'cdb.exe'}", err)
        self.assertIn(str(nowhere / "Windows Kits" / "10" / "Debuggers" / "x64" / "cdb.exe"), err)
        self.assertIn("PATH: cdb not found", err)

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
            self.assertTrue(cds._wait_stable(path, 30))
        self.assertEqual(len(sleeps), 2)

    def test_unparsed_transcript_exits_4(self):
        path = self.dump()
        code, out, err = run(["--dump", str(path), "--cdb", str(self.cdb)], "Could not open dump file\nquit:\n")
        self.assertEqual(code, 4)
        self.assertEqual(out, "")
        self.assertIn("no exception record", err)

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
