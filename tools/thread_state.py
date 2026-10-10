#!/usr/bin/env python3
"""thread_state.py -- read one process's threads from the OS, and touch nothing.

    py -3 -m tools.thread_state <pid> [--samples N] [--interval S]

prints `check(pid)` as one JSON object and exits 0 for `running`, 1 for any
other verdict, and 2 for a usage error. It is the check from outside the
debugger that the `x64dbg` tools (tools/x64dbg_mcp.py) and the live procedure
use to tell a running game from a held one, and a clean detach from one that
left threads suspended (docs/tools/x64dbg-mcp.md).

**Read-only.** Each sample is one `NtQuerySystemInformation
(SystemProcessInformation)` snapshot, which gives every thread's id,
scheduling state, wait reason and context-switch count, plus one
`NtQueryInformationThread(ThreadSuspendCount)` per thread, through a handle
opened with `THREAD_QUERY_LIMITED_INFORMATION` only. Nothing here suspends,
resumes, signals or writes to any process. Off Windows it answers
`unsupported`; a read that fails answers `unreadable`, never `running`.

Measured on this machine (Windows 11 build 26300, x64), 2026-10-10:
- both queries work with query-limited access;
- in a process entry the process id sits at 0x50 and the thread array starts
  at 0x100; each thread entry is 0x50 bytes, with the owner pid at 40, the
  thread id at 48, context switches at 64, state at 68 and wait reason at 72.
  State 5 is Waiting and wait reason 5 is Suspended. A thread entry whose
  owner is not the process is refused as a layout mismatch;
- a child with three threads sleeping 2 ms switched about 700 times in 0.5 s;
  one `SuspendThread`-ed thread sat in Waiting/Suspended with no switch and
  suspend count 1 while the others went on;
- held at a pending debug event, the child switched 0 times and every
  original thread read Waiting/Suspended with suspend count 2; after
  `DebugActiveProcessStop` every thread ran again with count 0.

The verdicts, in order: no such process is `gone`; not Windows is
`unsupported`; a failed sample is `unreadable`; no context switch across the
window is `frozen` (an idle process reads `frozen` too, and the game renders
every frame, so it never idles); a thread that did not switch across the
window and was suspended in *every* sample, or in Waiting/Suspended in every
sample, is `threads-suspended`; a thread whose suspend count could not be
read in some sample makes it `unreadable`; otherwise `running`. Neither the
samples nor the instants are enough on their own: x64dbg suspends every other
thread for each logpoint hit's step and holds the game at each hit, so under
a hot logpoint every sample can land inside a hit and catch a thread
suspended that still runs hundreds of times between them. A thread left suspended cannot be
scheduled, so its own context-switch count is the positive signal. A suspend
count that cannot be read is never read as 0: its tid is listed in
`unreadable_counts`, and the check does not answer `running` while any is.
`tids` lists every thread present in every sample, so a caller can tell
whether `suspended` and `stopped` cover the threads it expected.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import struct
import sys
import time
from typing import Iterable, NamedTuple

VERDICTS = ("running", "frozen", "threads-suspended", "gone", "unreadable", "unsupported")

# SYSTEM_PROCESS_INFORMATION / SYSTEM_THREAD_INFORMATION on x64, as measured above.
PROC_NEXT_OFF = 0x00
PROC_NTHREADS_OFF = 0x04
PROC_PID_OFF = 0x50
PROC_THREADS_OFF = 0x100
THREAD_SIZE = 0x50
THREAD_OWNER_OFF = 40
THREAD_TID_OFF = 48
THREAD_CS_OFF = 64
THREAD_STATE_OFF = 68
THREAD_WAIT_OFF = 72
STATE_WAITING = 5
WAIT_SUSPENDED = 5

SYSTEM_PROCESS_INFORMATION = 5
THREAD_SUSPEND_COUNT = 35
THREAD_QUERY_LIMITED_INFORMATION = 0x0800
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004


class ThreadSample(NamedTuple):
    tid: int
    context_switches: int
    state: int
    wait_reason: int
    suspend_count: int | None  # None: could not be read, which is never 0


class LayoutError(ValueError):
    """The snapshot does not match the layout this reader was measured against."""


def parse_process_threads(buf: bytes, pid: int) -> list[ThreadSample] | None:
    """The threads of `pid` in one SystemProcessInformation buffer, or None when
    `pid` is not listed. Raises LayoutError on anything out of bounds or a thread
    entry owned by another pid."""
    off = 0
    while True:
        if off + PROC_THREADS_OFF > len(buf):
            raise LayoutError(f"process entry at {off:#x} runs past the {len(buf)}-byte buffer")
        nxt, count = struct.unpack_from("<II", buf, off + PROC_NEXT_OFF)
        (entry_pid,) = struct.unpack_from("<Q", buf, off + PROC_PID_OFF)
        if entry_pid == pid:
            base = off + PROC_THREADS_OFF
            if base + count * THREAD_SIZE > len(buf):
                raise LayoutError(f"pid {pid}'s {count} thread entries run past the buffer")
            out = []
            for i in range(count):
                t = base + i * THREAD_SIZE
                (owner,) = struct.unpack_from("<Q", buf, t + THREAD_OWNER_OFF)
                (tid,) = struct.unpack_from("<Q", buf, t + THREAD_TID_OFF)
                cs, state, wait = struct.unpack_from("<III", buf, t + THREAD_CS_OFF)
                if owner != pid:
                    raise LayoutError(f"thread {tid} in pid {pid}'s entry names owner {owner}")
                out.append(ThreadSample(tid, cs, state, wait, None))
            return out
        if nxt == 0:
            return None
        off += nxt


def _held(t: ThreadSample) -> bool:
    return t.state == STATE_WAITING and t.wait_reason == WAIT_SUSPENDED


def _result(pid: int, verdict: str, detail: str, *, threads: int = 0, progress: int = 0,
            suspended: list | None = None, stopped: list | None = None,
            unreadable_counts: list | None = None, tids: list | None = None,
            samples: int = 0, interval: float = 0.0) -> dict:
    return {"verdict": verdict, "threads": threads, "progress": progress,
            "suspended": suspended or [], "stopped": stopped or [],
            "unreadable_counts": unreadable_counts or [], "tids": tids or [],
            "samples": samples, "interval": interval, "detail": detail}


def classify(pid: int, samples: list[list[ThreadSample]], interval: float = 0.4,
             baseline: Iterable[int] = ()) -> dict:
    """The verdict over two or more readable samples of one live process."""
    skip = {int(t) for t in baseline}
    by_tid = [{t.tid: t for t in s} for s in samples]
    first, last = by_tid[0], by_tid[-1]
    everywhere = [tid for tid in sorted(last) if all(tid in s for s in by_tid)]
    progress = sum((last[tid].context_switches - first[tid].context_switches) % (1 << 32)
                   for tid in last if tid in first)
    suspended, stopped, unknown = [], [], []
    for tid in everywhere:
        if tid in skip:
            continue
        seen = [s[tid] for s in by_tid]
        if any(t.suspend_count is None for t in seen):
            unknown.append(tid)
        # A thread left suspended cannot be scheduled, so its own switches stand
        # still. One that switched between the samples was only caught suspended
        # at each instant, as while x64dbg holds the game at logpoint hits.
        ran = seen[-1].context_switches != seen[0].context_switches
        if not ran and all(t.suspend_count is not None and t.suspend_count >= 1 for t in seen):
            suspended.append({"tid": tid, "suspend_count": seen[-1].suspend_count})
        if not ran and all(_held(t) for t in seen):
            stopped.append(tid)
    if progress == 0:
        verdict = "frozen"
    elif suspended or stopped:
        verdict = "threads-suspended"
    elif unknown:
        # A count that could not be read is never read as 0, so it cannot read running.
        verdict = "unreadable"
    else:
        verdict = "running"
    detail = (f"pid {pid}: {verdict}; {len(last)} threads, {progress} context switches across "
              f"{len(samples)} samples {interval} s apart; {len(suspended)} suspended in every "
              f"sample with no switch, {len(stopped)} stopped in Waiting/Suspended")
    if skip:
        detail += f", {len(skip)} left out as baseline"
    if unknown:
        detail += (f"; the suspend count of {len(unknown)} thread"
                   f"{'' if len(unknown) == 1 else 's'} could not be read")
    return _result(pid, verdict, detail + ".", threads=len(last), progress=progress,
                   suspended=suspended, stopped=stopped, unreadable_counts=unknown, tids=everywhere,
                   samples=len(samples), interval=interval)


# ---- the OS reads -----------------------------------------------------------------

def _supported() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, f"thread states are read through ntdll, and this is {sys.platform}"
    if struct.calcsize("P") != 8:
        return False, "the snapshot layout was measured on x64; this Python is 32-bit"
    return True, ""


def _exists(pid: int) -> bool:
    """Whether `pid` names a live process, read without touching it."""
    if sys.platform == "win32":
        return parse_process_threads(_snapshot(), pid) is not None
    try:
        os.kill(pid, 0)  # signal 0 on POSIX only checks; on Windows os.kill terminates
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@functools.lru_cache(maxsize=1)
def _ntdll():
    import ctypes
    from ctypes import wintypes
    nt = ctypes.WinDLL("ntdll")
    nt.NtQuerySystemInformation.argtypes = [wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG,
                                           ctypes.POINTER(wintypes.ULONG)]
    nt.NtQuerySystemInformation.restype = wintypes.LONG
    nt.NtQueryInformationThread.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p,
                                           wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    nt.NtQueryInformationThread.restype = wintypes.LONG
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenThread.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    return ctypes, nt, k


def _snapshot() -> bytes:
    """One SystemProcessInformation buffer. Raises OSError when the query fails."""
    ctypes, nt, _ = _ntdll()
    size = 1 << 20
    for _ in range(8):
        buf = ctypes.create_string_buffer(size)
        need = ctypes.c_ulong(0)
        status = nt.NtQuerySystemInformation(SYSTEM_PROCESS_INFORMATION, buf, size,
                                             ctypes.byref(need)) & 0xFFFFFFFF
        if status == 0:
            return buf.raw[:need.value or size]
        if status != STATUS_INFO_LENGTH_MISMATCH:
            raise OSError(f"NtQuerySystemInformation failed: {status:#010X}")
        size = max(size * 2, need.value + (1 << 16))
    raise OSError("NtQuerySystemInformation kept asking for a larger buffer")


def _suspend_count(tid: int) -> int | None:
    """The thread's suspend count through a query-only handle, or None if unreadable."""
    ctypes, nt, k = _ntdll()
    h = k.OpenThread(THREAD_QUERY_LIMITED_INFORMATION, False, tid)
    if not h:
        return None
    try:
        count = ctypes.c_ulong(0)
        status = nt.NtQueryInformationThread(h, THREAD_SUSPEND_COUNT, ctypes.byref(count),
                                             ctypes.sizeof(count), None)
        return int(count.value) if status == 0 else None
    finally:
        k.CloseHandle(h)


def _sample(pid: int) -> list[ThreadSample] | None:
    threads = parse_process_threads(_snapshot(), pid)
    if threads is None:
        return None
    return [t._replace(suspend_count=_suspend_count(t.tid)) for t in threads]


def check(pid: int, samples: int = 3, interval: float = 0.4, baseline: Iterable[int] = ()) -> dict:
    """Sample `pid`'s threads `samples` times, `interval` seconds apart, and classify them.
    Threads listed in `baseline` (tids) are left out of `suspended`, `stopped` and
    `unreadable_counts`."""
    if samples < 2:
        raise ValueError("samples must be 2 or more: progress is measured first to last")
    if interval <= 0:
        raise ValueError("interval must be above 0")
    baseline = tuple(baseline)
    try:
        exists = _exists(pid)
    except (OSError, LayoutError) as e:
        return _result(pid, "unreadable", f"pid {pid}: the process list could not be read: {e}.")
    if not exists:
        return _result(pid, "gone", f"pid {pid}: no such process.")
    ok, why = _supported()
    if not ok:
        return _result(pid, "unsupported", f"pid {pid}: {why}.")
    taken = []
    for i in range(samples):
        if i:
            time.sleep(interval)
        try:
            s = _sample(pid)
        except (OSError, LayoutError) as e:
            return _result(pid, "unreadable", f"pid {pid}: sample {i + 1} failed: {e}.",
                           samples=i, interval=interval)
        if s is None:
            return _result(pid, "gone", f"pid {pid}: the process exited during sample {i + 1}.",
                           samples=i, interval=interval)
        taken.append(s)
    return classify(pid, taken, interval, baseline)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="thread_state", description=__doc__.splitlines()[0])
    ap.add_argument("pid", type=int)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--interval", type=float, default=0.4)
    a = ap.parse_args(argv)
    if a.pid <= 0:
        ap.error("pid must be above 0")
    if a.samples < 2:
        ap.error("--samples must be 2 or more")
    if a.interval <= 0:
        ap.error("--interval must be above 0")
    r = check(a.pid, samples=a.samples, interval=a.interval)
    print(json.dumps(r))
    return 0 if r["verdict"] == "running" else 1


if __name__ == "__main__":
    sys.exit(main())
