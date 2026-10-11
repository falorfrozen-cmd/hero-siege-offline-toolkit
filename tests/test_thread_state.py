"""tools/thread_state.py: the read-only reader of one process's threads.

The pure cases run everywhere: the snapshot parser against a synthetic buffer
built at the measured x64 offsets, the verdict rules over synthetic samples,
a pid that does not exist, and the CLI's JSON and exit codes. Each verdict has
a negative control beside it: a suspension seen in one sample only, or every
thread suspended for one sample while the process keeps switching, reads
`running`; a thread already suspended at the baseline is not reported.
The `touched` cases count a debugger's context reads at a hold (1 to
CONTEXT_READS switches, suspended in every sample) as held, beside controls a
running process cannot pass; the `retake` cases sample again a held thread
caught outside its wait.

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
import threading
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


# The Replan 3 probe's run2 readings at the control's first-hit hold (measured
# 2026-10-10 on a throwaway process, not the game): two samples, identical, per
# thread (context switches, state, wait reason, suspend count). 6320 raised the
# hardware-breakpoint exception and waits for the debugger's reply in an
# Executive wait; the six others read Waiting/Suspended.
RUN2_HELD = {6320: (1717, WAITING, EXECUTIVE, 1), 31564: (39, WAITING, SUSPENDED, 1),
             25024: (39, WAITING, SUSPENDED, 1), 10656: (40, WAITING, SUSPENDED, 1),
             22076: (65, WAITING, SUSPENDED, 1), 32248: (78, WAITING, SUSPENDED, 1),
             11216: (76, WAITING, SUSPENDED, 1)}


def run2_held(**second):
    """The two run2 held samples; `second` replaces a thread's reading in the second
    one, keyed `t<tid>`."""
    first = [T(tid, *r) for tid, r in RUN2_HELD.items()]
    last = [T(tid, *second.get(f"t{tid}", r)) for tid, r in RUN2_HELD.items()]
    return [first, last]


class ExecutiveWaitTest(unittest.TestCase):
    def test_executive_run2_hold_names_the_breaking_thread_only(self):
        r = ts.classify(77, run2_held())
        self.assertEqual(r["verdict"], "frozen")
        self.assertEqual(sorted(s["tid"] for s in r["suspended"]), sorted(RUN2_HELD))
        self.assertEqual(r["stopped"], sorted(set(RUN2_HELD) - {6320}))
        self.assertEqual(r["executive_waits"], [6320])

    def test_executive_baseline_leaves_the_thread_out(self):
        r = ts.classify(77, run2_held(), baseline=[6320])
        self.assertEqual(r["executive_waits"], [])
        self.assertEqual(r["verdict"], "frozen")

    def test_executive_negative_controls(self):
        # The debugger's break-in thread (count 0, measured), a thread that switched,
        # and one in Executive in one sample only are not executive waits.
        cases = {"count 0": run2_held(t6320=(1717, WAITING, EXECUTIVE, 0)),
                 "switching": run2_held(t6320=(1720, WAITING, EXECUTIVE, 1)),
                 "one sample": run2_held(t6320=(1717, WAITING, SUSPENDED, 1))}
        cases["count 0"][0][0] = T(6320, 1717, WAITING, EXECUTIVE, 0)
        for name, s in cases.items():
            with self.subTest(name):
                self.assertEqual(ts.classify(77, s)["executive_waits"], [])

    def test_executive_waits_is_empty_on_a_gone_or_unreadable_result(self):
        self.assertEqual(ts.check(MISSING_PID)["executive_waits"], [])
        self.assertEqual(ts._result(1, "unreadable", "x")["executive_waits"], [])


def rerun4(step, n=69, executive=1, count=1, over=None):
    """Live 3 rerun 4's shape at the control hold: `n` held threads, three
    samples, each thread's own switches rising by `step` from the first sample
    on, tid `executive` in an Executive wait and the rest Waiting/Suspended,
    each at suspend count `count`. `over` maps (sample index, tid) to a
    replacement suspend count."""
    over = over or {}
    return [[T(tid, 100 + (step if k else 0), WAITING, EXECUTIVE if tid == executive else SUSPENDED,
               over.get((k, tid), count)) for tid in range(1, n + 1)] for k in range(3)]


class TouchedTest(unittest.TestCase):
    """A debugger's context reads at a hold schedule each held thread once
    without running its code (measured on a throwaway, 2026-10-11): 1 to
    CONTEXT_READS switches with a suspend count of 1 or more in every sample
    count as held, and nothing a running process does meets that."""

    def test_touched_rerun4_shape_reads_frozen(self):
        r = ts.classify(77, rerun4(1))
        self.assertEqual(r["verdict"], "frozen", r)
        self.assertEqual(r["progress"], 69)
        self.assertEqual(r["touched"], list(range(1, 70)))
        self.assertEqual(len(r["suspended"]), 69)
        self.assertEqual(r["stopped"], list(range(2, 70)))
        self.assertEqual(r["executive_waits"], [1])
        self.assertIn("69 touched", r["detail"])

    def test_touched_two_reads_each_reads_frozen(self):
        r = ts.classify(77, rerun4(ts.CONTEXT_READS))
        self.assertEqual(r["verdict"], "frozen", r)
        self.assertEqual(len(r["touched"]), 69)

    def test_touched_control_three_switches_each_is_running(self):
        r = ts.classify(77, rerun4(ts.CONTEXT_READS + 1))
        self.assertEqual(r["verdict"], "running", r)
        self.assertEqual((r["suspended"], r["stopped"], r["executive_waits"], r["touched"]), ([], [], [], []))

    def test_touched_control_a_count_of_0_or_unread_in_one_sample_is_not_touched(self):
        for name, count in (("count 0", 0), ("unread", None)):
            with self.subTest(name):
                r = ts.classify(77, rerun4(1, over={(1, 5): count}))
                self.assertNotIn(5, r["touched"], r)
                self.assertNotEqual(r["verdict"], "frozen", r)
                self.assertNotIn(5, [s["tid"] for s in r["suspended"]])

    def test_touched_control_logging_shape_suspended_at_every_sample_is_running(self):
        # While a logpoint logs, a sample can land inside a hit at every instant;
        # those threads switched 499 or more times in the window (measured).
        r = ts.classify(77, rerun4(500))
        self.assertEqual(r["verdict"], "running", r)
        self.assertEqual((r["touched"], r["suspended"], r["stopped"]), ([], [], []))

    def test_touched_control_idle_threads_switching_at_count_0_are_running(self):
        s = [[T(1, 10), T(2, 20)], [T(1, 11), T(2, 21)], [T(1, 11), T(2, 22)]]
        r = ts.classify(77, s)
        self.assertEqual(r["verdict"], "running", r)
        self.assertEqual(r["touched"], [])

    def test_touched_includes_baseline_threads_and_is_empty_on_other_results(self):
        r = ts.classify(77, rerun4(1, n=3), baseline=[2])
        self.assertEqual(r["touched"], [1, 2, 3])
        self.assertNotIn(2, r["stopped"])
        self.assertEqual(r["verdict"], "frozen")
        self.assertEqual(ts.check(MISSING_PID)["touched"], [])
        self.assertEqual(ts._result(1, "unreadable", "x")["touched"], [])
        with mock.patch.object(ts, "_supported", return_value=(False, "not Windows")), \
             mock.patch.object(ts, "_exists", return_value=True):
            self.assertEqual(ts.check(123, samples=2, interval=0.01)["touched"], [])


class RetakeTest(unittest.TestCase):
    """A sample that catches a held thread outside its wait (a context read in
    progress) is taken again, RETAKE_DELAY later, at most RETAKES times."""

    def check_with(self, takes, samples=3):
        calls = []

        def sample(pid):
            calls.append(pid)
            return takes[min(len(calls), len(takes)) - 1]
        with mock.patch.object(ts, "_supported", return_value=(True, "")), \
             mock.patch.object(ts, "_exists", return_value=True), \
             mock.patch.object(ts, "_sample", side_effect=sample):
            return ts.check(123, samples=samples, interval=0.01), len(calls)

    def test_retake_a_held_thread_caught_mid_read(self):
        mid = [T(1, 10, RUNNING_STATE, 0, 1), T(2, 20, WAITING, SUSPENDED, 1)]
        held = [T(1, 10, WAITING, SUSPENDED, 1), T(2, 20, WAITING, SUSPENDED, 1)]
        r, calls = self.check_with([mid, held, held, held])
        self.assertEqual(calls, 4)
        self.assertEqual(r["verdict"], "frozen", r)
        self.assertEqual(r["stopped"], [1, 2], r)

    def test_retake_control_a_running_thread_at_count_0_is_not_retaken(self):
        run = [[T(1, 10 + 40 * i, RUNNING_STATE, 0, 0)] for i in range(3)]
        r, calls = self.check_with(run)
        self.assertEqual(calls, 3)
        self.assertEqual(r["verdict"], "running", r)

    def test_retake_is_bounded_and_the_last_take_stands(self):
        mid = [T(1, 10, RUNNING_STATE, 0, 1)]
        r, calls = self.check_with([mid] * 20, samples=2)
        self.assertEqual(calls, 2 * (1 + ts.RETAKES))
        self.assertEqual(r["stopped"], [], r)  # never seen in its wait
        self.assertEqual(r["verdict"], "frozen", r)

    def test_retake_a_pid_gone_during_a_retake_is_gone(self):
        mid = [T(1, 10, RUNNING_STATE, 0, 1)]
        r, calls = self.check_with([mid, None])
        self.assertEqual((r["verdict"], calls), ("gone", 2))


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
                                  "unreadable_counts", "tids", "executive_waits", "touched", "samples",
                                  "interval", "detail"})

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

    def read_context(self, tid) -> bool:
        """One GetThreadContext on a thread of our own child, as x64dbg's
        memory-map refresh reads each thread's instruction pointer."""
        from ctypes import wintypes
        k, ctypes = self.k32, self.ctypes
        k.GetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        k.GetThreadContext.restype = wintypes.BOOL
        h = k.OpenThread(0x0008, False, tid)  # THREAD_GET_CONTEXT
        if not h:
            return False
        try:
            buf = ctypes.create_string_buffer(0x4D0 + 16)  # an x64 CONTEXT, 16-byte aligned
            at = (ctypes.addressof(buf) + 15) & ~15
            ctypes.c_uint32.from_address(at + 0x30).value = 0x00100001  # ContextFlags: CONTEXT_CONTROL
            return bool(k.GetThreadContext(h, ctypes.c_void_p(at)))
        finally:
            k.CloseHandle(h)

    def test_real_os_touched_context_reads_of_a_held_child_read_frozen(self):
        pid = self.child.pid
        tids = [t.tid for t in ts._sample(pid)]
        handles = []
        try:
            for tid in tids:
                h = self.k32.OpenThread(0x0002, False, tid)  # THREAD_SUSPEND_RESUME, on our own child
                self.assertTrue(h, self.ctypes.get_last_error())
                handles.append(h)
                self.assertNotEqual(self.k32.SuspendThread(h), 0xFFFFFFFF)
            time.sleep(0.1)
            # One context read per thread between two samples: each thread +1.
            first = ts._sample(pid)
            read = sum(self.read_context(tid) for tid in tids)
            last = ts._sample(pid)
            self.assertEqual(read, len(tids))
            r = ts.classify(pid, [first, last])
            self.assertEqual(r["verdict"], "frozen", r)
            self.assertEqual(r["progress"], read, r)
            self.assertEqual(r["touched"], sorted(tids), r)
            # A reader every 0.6 s while the check runs, as x64dbg's refresh reads.
            stop = threading.Event()

            def reader():
                while not stop.wait(0.6):
                    for tid in tids:
                        self.read_context(tid)
            t = threading.Thread(target=reader, daemon=True)
            t.start()
            try:
                r = ts.check(pid)
            finally:
                stop.set()
                t.join(5)
            self.assertEqual(r["verdict"], "frozen", r)
            self.assertTrue(r["touched"], r)
            for tid in self.workers:
                self.assertIn(tid, r["stopped"], r)
        finally:
            for h in handles:
                self.k32.ResumeThread(h)
                self.k32.CloseHandle(h)
        time.sleep(0.2)
        r = ts.check(pid)
        self.assertEqual(r["verdict"], "running", r)
        self.assertEqual(r["touched"], [], r)

    def test_real_os_cli_reads_the_child_as_running(self):
        r = subprocess.run([sys.executable, "-m", "tools.thread_state", str(self.child.pid)],
                           cwd=ROOT, capture_output=True, text=True, timeout=60, **NO_WINDOW)
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        self.assertEqual(json.loads(r.stdout)["verdict"], "running")


if __name__ == "__main__":
    unittest.main()
