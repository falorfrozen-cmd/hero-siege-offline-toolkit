"""tools/thread_state.py: the read-only reader of one process's threads.

The pure cases run everywhere: the snapshot parser against a synthetic buffer
built at the measured x64 offsets, the verdict rules over synthetic samples,
a pid that does not exist, and the CLI's JSON and exit codes. Each verdict has
a negative control beside it: a suspension seen in one sample only, or every
thread suspended for one sample while the process keeps switching, reads
`running`; a thread already suspended at the baseline is not reported.

The `real_os` cases run on Windows only, against a child this test starts
(three threads sleeping 2 ms in a loop) and kills at cleanup. They suspend one
of that child's threads, then hold the child at a pending debug event, and
read it with the real reader each time. Nothing here touches any process the
test did not start.
"""
import contextlib
import io
import json
import os
import struct
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import thread_state as ts  # noqa: E402

# Every child these tests start runs without a console window on Windows.
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

MISSING_PID = 4194300  # above every pid this machine hands out; pinned by criterion 8 too
WAITING, SUSPENDED = 5, 5
RUNNING_STATE, EXECUTIVE = 2, 0

REAL_OS_SKIP = None
if sys.platform != "win32":
    REAL_OS_SKIP = "real_os cases read Windows threads through ntdll; this is not Windows"
elif struct.calcsize("P") != 8:
    REAL_OS_SKIP = "real_os cases need a 64-bit Python, whose layout the reader parses"


def T(tid, cs, state=WAITING, wait=6, suspend=0):
    """One thread in one sample. Wait reason 6 is an ordinary delay, not Suspended."""
    return ts.ThreadSample(tid=tid, context_switches=cs, state=state,
                           wait_reason=wait, suspend_count=suspend)


def process_entry(pid, threads, last):
    """A SYSTEM_PROCESS_INFORMATION entry at the offsets the module docstring names."""
    head = bytearray(0x100)
    body = bytearray()
    for tid, owner, cs, state, wait in threads:
        t = bytearray(0x50)
        struct.pack_into("<Q", t, 40, owner)
        struct.pack_into("<Q", t, 48, tid)
        struct.pack_into("<I", t, 64, cs)
        struct.pack_into("<I", t, 68, state)
        struct.pack_into("<I", t, 72, wait)
        body += t
    size = len(head) + len(body)
    struct.pack_into("<I", head, 0, 0 if last else size)
    struct.pack_into("<I", head, 4, len(threads))
    struct.pack_into("<Q", head, 0x50, pid)
    return bytes(head + body)


class ParseLayoutTest(unittest.TestCase):
    def test_parse_layout_reads_the_target_and_skips_another_pid(self):
        buf = (process_entry(4, [(8, 4, 111, 5, 0)], last=False)
               + process_entry(1234, [(1240, 1234, 70, 5, 5), (1244, 1234, 900, 2, 0)], last=True))
        got = ts.parse_process_threads(buf, 1234)
        self.assertEqual([(t.tid, t.context_switches, t.state, t.wait_reason) for t in got],
                         [(1240, 70, 5, 5), (1244, 900, 2, 0)])
        self.assertTrue(all(t.suspend_count is None for t in got))

    def test_parse_layout_answers_none_for_a_pid_not_listed(self):
        buf = process_entry(4, [(8, 4, 111, 5, 0)], last=True)
        self.assertIsNone(ts.parse_process_threads(buf, 1234))

    def test_parse_layout_refuses_a_thread_owned_by_another_pid(self):
        # Negative control: a layout that no longer matches must fail, never parse.
        buf = process_entry(1234, [(1240, 999, 70, 5, 5)], last=True)
        with self.assertRaises(ts.LayoutError):
            ts.parse_process_threads(buf, 1234)

    def test_parse_layout_refuses_a_truncated_buffer(self):
        buf = process_entry(1234, [(1240, 1234, 70, 5, 5), (1244, 1234, 9, 5, 5)], last=True)
        with self.assertRaises(ts.LayoutError):
            ts.parse_process_threads(buf[:-8], 1234)


class ClassifyTest(unittest.TestCase):
    def test_classify_running_when_threads_switch_and_none_is_held(self):
        r = ts.classify(77, [[T(1, 10), T(2, 20)], [T(1, 60), T(2, 90)], [T(1, 300), T(2, 400)]])
        self.assertEqual(r["verdict"], "running")
        self.assertEqual(r["progress"], 670)
        self.assertEqual((r["threads"], r["suspended"], r["stopped"]), (2, [], []))
        self.assertEqual((r["samples"], r["interval"]), (3, 0.4))
        self.assertIn("670", r["detail"])

    def test_classify_frozen_when_no_thread_switches(self):
        held = [T(1, 10, WAITING, SUSPENDED, 2), T(2, 20, WAITING, SUSPENDED, 2)]
        r = ts.classify(77, [held, held, held])
        self.assertEqual(r["verdict"], "frozen")
        self.assertEqual(r["progress"], 0)

    def test_classify_frozen_for_an_idle_process_too(self):
        idle = [T(1, 10), T(2, 20)]
        self.assertEqual(ts.classify(77, [idle, idle])["verdict"], "frozen")

    def test_classify_suspended_names_the_held_thread_and_its_count(self):
        s = [[T(1, 10), T(2, 5, WAITING, SUSPENDED, 1)],
             [T(1, 80), T(2, 5, WAITING, SUSPENDED, 1)],
             [T(1, 150), T(2, 5, WAITING, SUSPENDED, 1)]]
        r = ts.classify(77, s)
        self.assertEqual(r["verdict"], "threads-suspended")
        self.assertEqual(r["suspended"], [{"tid": 2, "suspend_count": 1}])
        self.assertEqual(r["stopped"], [2])
        self.assertEqual(r["progress"], 140)

    def test_classify_suspended_by_state_when_the_count_cannot_be_read(self):
        # An unreadable count is never read as 0: the thread is still caught as stopped,
        # and the detail counts it.
        s = [[T(1, 10), T(2, 5, WAITING, SUSPENDED, None)],
             [T(1, 80), T(2, 5, WAITING, SUSPENDED, None)]]
        r = ts.classify(77, s)
        self.assertEqual(r["verdict"], "threads-suspended")
        self.assertEqual((r["suspended"], r["stopped"]), ([], [2]))
        self.assertIn("1 thread", r["detail"])
        self.assertIn("could not be read", r["detail"])
        self.assertEqual(r["unreadable_counts"], [2])

    def test_classify_unreadable_count_on_a_switching_thread_is_not_running(self):
        # A count that could not be read is never read as 0: the threads switch,
        # nothing is caught held, and still the verdict is not `running`.
        s = [[T(1, 10), T(2, 20, suspend=None)], [T(1, 80), T(2, 90, suspend=None)]]
        r = ts.classify(77, s)
        self.assertEqual(r["verdict"], "unreadable")
        self.assertEqual(r["unreadable_counts"], [2])
        self.assertEqual(r["tids"], [1, 2])
        # Control: the same samples with the count read are running, and a
        # baseline thread's unread count is left out like the rest of it.
        s_read = [[T(1, 10), T(2, 20)], [T(1, 80), T(2, 90)]]
        self.assertEqual((ts.classify(77, s_read)["verdict"], ts.classify(77, s_read)["unreadable_counts"]),
                         ("running", []))
        r = ts.classify(77, s, baseline=[2])
        self.assertEqual((r["verdict"], r["unreadable_counts"]), ("running", []))

    def test_classify_transient_suspension_in_one_sample_reads_running(self):
        s = [[T(1, 10), T(2, 20)],
             [T(1, 40), T(2, 20, WAITING, SUSPENDED, 1)],
             [T(1, 90), T(2, 70)]]
        r = ts.classify(77, s)
        self.assertEqual(r["verdict"], "running")
        self.assertEqual((r["suspended"], r["stopped"]), ([], []))

    def test_classify_transient_whole_process_held_in_one_sample_reads_running(self):
        # A logpoint hit's step suspends every other thread for a moment; one sample can
        # catch them all, while the process keeps switching across the window.
        s = [[T(1, 10), T(2, 20)],
             [T(1, 30, WAITING, SUSPENDED, 1), T(2, 25, WAITING, SUSPENDED, 1)],
             [T(1, 90), T(2, 70)]]
        r = ts.classify(77, s)
        self.assertEqual(r["verdict"], "running")
        self.assertGreater(r["progress"], 0)

    def test_classify_transient_suspended_at_every_instant_while_switching_reads_running(self):
        # Negative control: x64dbg holding the game at each logpoint hit can catch a
        # thread with a suspend count of 1 in every sample, yet its own switches advance,
        # so it was scheduled between them and is not left suspended.
        s = [[T(1, 10), T(2, 20, WAITING, SUSPENDED, 1)],
             [T(1, 40), T(2, 45, WAITING, SUSPENDED, 1)],
             [T(1, 90), T(2, 70, WAITING, SUSPENDED, 2)]]
        r = ts.classify(77, s)
        self.assertEqual(r["verdict"], "running")
        self.assertEqual((r["suspended"], r["stopped"]), ([], []))

    def test_classify_suspended_in_every_sample_with_no_switch_reads_suspended(self):
        # Positive control beside it: the same suspend counts with the thread's own
        # switches standing still is a thread left suspended.
        s = [[T(1, 10), T(2, 20, WAITING, SUSPENDED, 1)],
             [T(1, 40), T(2, 20, WAITING, SUSPENDED, 1)],
             [T(1, 90), T(2, 20, WAITING, SUSPENDED, 2)]]
        r = ts.classify(77, s)
        self.assertEqual(r["verdict"], "threads-suspended")
        self.assertEqual(r["suspended"], [{"tid": 2, "suspend_count": 2}])
        self.assertEqual(r["stopped"], [2])

    def test_classify_baseline_leaves_out_a_thread_already_suspended(self):
        s = [[T(1, 10), T(2, 5, WAITING, SUSPENDED, 1)],
             [T(1, 80), T(2, 5, WAITING, SUSPENDED, 1)]]
        r = ts.classify(77, s, baseline=[2])
        self.assertEqual(r["verdict"], "running")
        self.assertEqual((r["suspended"], r["stopped"]), ([], []))
        # Control: the same samples without the baseline report it.
        self.assertEqual(ts.classify(77, s)["verdict"], "threads-suspended")

    def test_classify_counts_progress_only_over_threads_in_both_samples(self):
        s = [[T(1, 10), T(2, 20)], [T(1, 10), T(3, 5000)]]
        r = ts.classify(77, s)
        self.assertEqual(r["progress"], 0)
        self.assertEqual(r["verdict"], "frozen")


class GoneTest(unittest.TestCase):
    def test_gone_for_a_pid_that_does_not_exist(self):
        r = ts.check(MISSING_PID, samples=2, interval=0.05)
        self.assertEqual(r["verdict"], "gone")
        self.assertEqual(r["threads"], 0)
        self.assertIn(str(MISSING_PID), r["detail"])

    def test_gone_takes_precedence_over_unsupported(self):
        with mock.patch.object(ts, "_supported", return_value=(False, "not Windows")), \
             mock.patch.object(ts, "_exists", return_value=False):
            self.assertEqual(ts.check(123, samples=2, interval=0.01)["verdict"], "gone")
        with mock.patch.object(ts, "_supported", return_value=(False, "not Windows")), \
             mock.patch.object(ts, "_exists", return_value=True):
            self.assertEqual(ts.check(123, samples=2, interval=0.01)["verdict"], "unsupported")

    def test_gone_is_not_what_a_failed_read_answers(self):
        # A read that fails answers unreadable, never running and never gone.
        def boom():
            raise OSError("NtQuerySystemInformation failed: 0xC0000022")
        with mock.patch.object(ts, "_supported", return_value=(True, "")), \
             mock.patch.object(ts, "_exists", return_value=True), \
             mock.patch.object(ts, "_snapshot", side_effect=boom):
            r = ts.check(123, samples=2, interval=0.01)
        self.assertEqual(r["verdict"], "unreadable")
        self.assertIn("0xC0000022", r["detail"])


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "tools.thread_state", *args], cwd=ROOT,
                              capture_output=True, text=True, timeout=60, **NO_WINDOW)

    def main_with(self, verdict):
        fake = {"verdict": verdict, "threads": 3, "progress": 9, "suspended": [], "stopped": [],
                "samples": 3, "interval": 0.4, "detail": "x"}
        out = io.StringIO()
        with mock.patch.object(ts, "check", return_value=fake) as chk, contextlib.redirect_stdout(out):
            code = ts.main(["42", "--samples", "4", "--interval", "0.1"])
        chk.assert_called_once_with(42, samples=4, interval=0.1)
        return code, json.loads(out.getvalue())

    def test_cli_exits_0_only_for_running(self):
        code, d = self.main_with("running")
        self.assertEqual((code, d["verdict"]), (0, "running"))
        for verdict in ("frozen", "threads-suspended", "gone", "unreadable", "unsupported"):
            self.assertEqual(self.main_with(verdict)[0], 1, verdict)

    def test_cli_prints_one_json_object_for_a_missing_pid(self):
        r = self.run_cli(str(MISSING_PID))
        self.assertEqual(r.returncode, 1, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["verdict"], "gone")
        self.assertEqual(set(d), {"verdict", "threads", "progress", "suspended", "stopped",
                                  "unreadable_counts", "tids", "samples", "interval", "detail"})

    def test_cli_usage_errors_exit_2(self):
        for args in ((), ("notapid",), ("0",), ("42", "--samples", "1"), ("42", "--interval", "0")):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 2, (args, r.stdout, r.stderr))


CHILD = ("import json,sys,threading,time\n"
         "def work():\n"
         "    while True: time.sleep(0.002)\n"
         "ts=[threading.Thread(target=work,daemon=True) for _ in range(3)]\n"
         "[t.start() for t in ts]\n"
         "print(json.dumps([t.native_id for t in ts]),flush=True)\n"
         "time.sleep(120)\n")


@unittest.skipIf(REAL_OS_SKIP is not None, REAL_OS_SKIP or "")
class RealOsTest(unittest.TestCase):
    """The real reader, against a child this test starts, suspends and kills itself."""

    def setUp(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k32.OpenThread.restype = wintypes.HANDLE
        self.k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.k32.SuspendThread.argtypes = [wintypes.HANDLE]
        self.k32.SuspendThread.restype = wintypes.DWORD
        self.k32.ResumeThread.argtypes = [wintypes.HANDLE]
        self.k32.ResumeThread.restype = wintypes.DWORD
        self.k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.k32.DebugActiveProcess.argtypes = [wintypes.DWORD]
        self.k32.DebugActiveProcessStop.argtypes = [wintypes.DWORD]
        self.k32.DebugSetProcessKillOnExit.argtypes = [wintypes.BOOL]
        self.child = subprocess.Popen([sys.executable, "-I", "-c", CHILD],
                                      stdout=subprocess.PIPE, text=True, **NO_WINDOW)
        self.addCleanup(self._kill_child)
        self.workers = json.loads(self.child.stdout.readline())
        self.assertEqual(len(self.workers), 3)
        time.sleep(0.3)

    def _kill_child(self):
        self.child.kill()
        self.child.wait(timeout=30)
        self.child.stdout.close()

    def test_real_os_reads_a_running_child_as_running(self):
        r = ts.check(self.child.pid)
        self.assertEqual(r["verdict"], "running", r)
        self.assertGreater(r["progress"], 0)
        self.assertEqual((r["suspended"], r["stopped"]), ([], []))
        self.assertGreaterEqual(r["threads"], 4)

    def test_real_os_names_one_suspended_thread_then_running_after_resume(self):
        tid = self.workers[1]
        h = self.k32.OpenThread(0x0002, False, tid)  # THREAD_SUSPEND_RESUME, on our own child
        self.assertTrue(h, self.ctypes.get_last_error())
        resumed = False
        try:
            self.assertEqual(self.k32.SuspendThread(h), 0)
            time.sleep(0.1)
            r = ts.check(self.child.pid)
            self.assertEqual(r["verdict"], "threads-suspended", r)
            self.assertEqual(r["suspended"], [{"tid": tid, "suspend_count": 1}])
            self.assertIn(tid, r["stopped"])
            self.assertGreater(r["progress"], 0)
            self.assertEqual(self.k32.ResumeThread(h), 1)
            resumed = True
        finally:
            if not resumed:
                self.k32.ResumeThread(h)
            self.k32.CloseHandle(h)
        r = ts.check(self.child.pid)
        self.assertEqual(r["verdict"], "running", r)
        self.assertEqual(r["suspended"], [])

    def test_real_os_reads_a_pending_debug_event_as_frozen_then_running_after_stop(self):
        pid = self.child.pid
        self.assertTrue(self.k32.DebugActiveProcess(pid), self.ctypes.get_last_error())
        attached = True
        try:
            self.k32.DebugSetProcessKillOnExit(False)
            time.sleep(0.3)  # the first debug event is never continued: the child is held
            r = ts.check(pid)
            self.assertEqual(r["verdict"], "frozen", r)
            self.assertEqual(r["progress"], 0)
            held = {s["tid"]: s["suspend_count"] for s in r["suspended"]}
            for tid in self.workers:
                self.assertGreaterEqual(held.get(tid, 0), 1, r)
                self.assertIn(tid, r["stopped"], r)
                self.assertIn(tid, r["tids"], r)
            self.assertEqual(r["unreadable_counts"], [], r)
            self.assertTrue(self.k32.DebugActiveProcessStop(pid), self.ctypes.get_last_error())
            attached = False
        finally:
            if attached:
                self.k32.DebugActiveProcessStop(pid)
        time.sleep(0.3)
        r = ts.check(pid)
        self.assertEqual(r["verdict"], "running", r)
        self.assertEqual((r["suspended"], r["stopped"]), ([], []))

    def test_real_os_cli_reads_the_child_as_running(self):
        r = subprocess.run([sys.executable, "-m", "tools.thread_state", str(self.child.pid)],
                           cwd=ROOT, capture_output=True, text=True, timeout=60, **NO_WINDOW)
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        self.assertEqual(json.loads(r.stdout)["verdict"], "running")


if __name__ == "__main__":
    unittest.main()
