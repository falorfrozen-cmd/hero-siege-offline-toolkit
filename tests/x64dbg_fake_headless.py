"""A stand-in for headless x64dbg, for tests/test_x64dbg_mcp.py.

    python x64dbg_fake_headless.py <workdir>            # headless x64dbg
    python x64dbg_fake_headless.py probe <workdir> <pid>  # the keeper's probe seam
    python x64dbg_fake_headless.py frames <workdir> <pid> <timeout>  # the keeper's frames seam

As headless, it reads commands on stdin, records each line in
`<workdir>/stdin.txt`, and prints on stdout (the session log) what x64dbg
prints, as measured live, by the Replan 3 probe against a throwaway process,
or as read from x64dbg's source (docs/tools/x64dbg-mcp.md): `[STATE] <name>`
on every debug-state change, once at once and again shortly after; on
`attach`, `[STATE] initialized`, `[STATE] running` (twice) and `Attached to
process!`, and never `[STATE] paused`, since headless x64dbg takes no attach
break; the `log` markers, `bph`'s success line, nothing for a `Set*` step
that succeeds, `bplist` rows, the deletion lines, `Detached!`, a log line
per hit of a hot logging breakpoint, and a break line plus `[STATE] paused`
for every break. A hot breakpoint whose condition is not 0 breaks on its
next hit: a breaking `bph`'s first hit (how the control logpoint holds the
game) and a held change's hold alike. Synthetic text of our own, not
x64dbg's source.

As the probe seam, it prints the outside check of the game it last wrote to
`<workdir>/verdict.json` (`running` until it writes one), as
`py -3 -m tools.thread_state <pid>` would.

As the frames seam, it prints one reading of the stand-in game's frame
counter in `tools/x64dbg_mcp.py`'s `game_frames` shape, as ForgePact's
`ping` plus `incident stat` would answer it. The counter advances
(`FRAMES_PER_SECOND`) while the stand-in runs and stops while it is paused,
and every reading taken while it runs is above the last one, so two quick
readings never tie. While paused it prints `not_consumed` at once, with
`elapsed_s` the timeout it was given: it never sleeps the timeout.

Files in `<workdir>`:
- `stdin.txt`: every line read on stdin, in order;
- `bps.json`: the breakpoint list, shared with the stand-in plugin;
- `modes.json`: the modes below, re-read every tick, so a test can change one
  mid-session;
- `verdict.json`: the outside check the probe prints;
- `pause_request`: left by the stand-in plugin's asynchronous PauseDebug;
- `breaks.txt` and `probes.txt`: the wall-clock time of each break (written
  before its `[STATE] paused`) and of each probe-seam call, one per line, so
  a test can tell how long after a break the keeper's check came;
- `frames.json`: the frame counter (`paused`, and the count `base` it had at
  `since`), written by the stand-in at every break, resume and detach;
- `frames_last.json`: the last count the frames seam printed;
- `frames_gone`: left at `detach` under `frames_gone_after_detach`, after
  which the frames seam reads `gone`.

Modes:
- `tls_breaks` N: N breaks right after attach, one after each run, each on an
  x64dbg TLS-callback breakpoint (the pauses the keeper resumes after
  attach; there is no attach break);
- `late_break` S: one unprompted break S seconds after the last command (the
  asynchronous pause landing late, as Live 2 measured);
- `breaks` N: N breaks in a row from now on, one after each run (a storm);
- `break_after` <verb>: one break right after the first command with that verb;
- `stale_db` <addr>: on `attach`, restore one hardware breakpoint from x64dbg's
  "database" before any command (`Set hardware breakpoint on <16 hex>!` and a
  row), as x64dbg restores a module's saved breakpoints;
- `condition_ignored`: an armed hot breakpoint breaks on every hit, and on
  the hit right after every `run` (in the same handler, so x64dbg never
  settles at running while it is armed, however the stand-in is scheduled);
- `never_running`: a break right after attach, and another after every run
  (x64dbg never settles at running);
- `race`: a command that changes debug registers, arriving while the game is
  not held and a hot logpoint is armed, silences that logpoint (the lost DR7
  update);
- `leak_on_detach`: after `detach`, every game thread but one stays suspended,
  and the frame counter stops;
- `leak_threads_only`: the threads leak after `detach` as `leak_on_detach`
  leaves them, but the frame counter advances (the game loop runs);
- `frames_never_stall`: the frame counter advances while paused (a hold the
  game loop does not notice);
- `frames_answer_held`: the frames seam answers while paused, with the
  frozen count;
- `frames_dead`: the frames seam always prints `not_consumed` (a channel
  nothing reads);
- `frames_slow` S: the frames seam's readings while running report
  `elapsed_s` S;
- `threads_gone_after_detach`: after a clean `detach` the probe reads `gone`
  (thread_state's pid-only verdict) while the game runs on, frame counter
  and all;
- `frames_gone_after_detach`: after `detach` the frames seam reads `gone`
  (the identity-checked verdict of a game that exited), while the probe
  still reads `running`;
- `fail_condition`: `SetHardwareBreakpointCondition` prints its failure;
- `listed_as` [enabled, type]: the row's enabled flag and type;
- `false_success`: `bph` prints success, and no row follows;
- `exception_hold`: a breaking `bph` on a hot address hits at once and is
  reported as a first-chance single-step exception, in the order Live 3
  rerun 3 measured: x64dbg's `[TODO] Not implemented GUI_SET_LAST_EXCEPTION
  (37)` notice, `[STATE] paused`, `First chance exception on <A> (80000004,
  EXCEPTION_SINGLE_STEP)!`, and only then `bph`'s success line;
- `plugin_hold`: setting an armed breakpoint's break condition to 1 holds
  the game at its next hit at once, in the order Live 3 rerun 5 measured
  for a held change: no break line, `[STATE] paused` twice, the plugin's
  `[PLUGIN, MCP - Agent Smithers] Breakpoint <hex> in hero_siege.exe` line,
  then the breakpoint's own log line (`"no_log"`: no log line after the
  plugin's);
- `hot` [addr, ...]: the armed breakpoints the game hits, every 50 ms;
- `blind_probe`: the probe never reads `frozen` (an instrument that cannot
  see a held game);
- `empty_lists`: the probe reads `frozen` at a break but names no suspended or
  stopped thread (an instrument that read no thread at all);
- `breaking_thread` N: at a break the probe reads the first N game threads
  suspended, in `executive_waits` and not in `stopped` (the breaking thread
  the Replan 3 probe measured waiting in an Executive wait at the hold);
- `real_os`: suspend the stand-in game's threads for real at every break (a
  breaking breakpoint's first-hit hold among them) and under
  `leak_on_detach`, and resume them on `run` and on a clean `detach`, never
  on `attach` (`spare_tid` is the one `leak_on_detach` leaves running);
- `context_reads` S, with `real_os`: while paused, every S seconds from the
  break, read the context of each thread the stand-in suspended, through a
  handle with get-context access on the test's own child, as x64dbg's
  memory-map refresh does about once a second (measured on a throwaway,
  2026-10-11): each read schedules a held thread once without running it.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
from pathlib import Path

HIT_EVERY = 0.05
TICK = 0.02
REPEAT_AFTER = 0.2       # x64dbg's rate-limited repeat of the latest state
ASYNC_PAUSE_AFTER = 2.0  # how late the plugin's PauseDebug lands
FAKE_TIDS = (9001, 9002)  # the probe seam's game threads, "suspended" at a break and under leak_on_detach
DR_VERBS = {"bph", "bphws", "sethardwarebreakpoint", "bphc", "bphwc", "deletehardwarebreakpoint",
            "bphe", "bphwe", "enablehardwarebreakpoint", "bphd", "bphwd", "disablehardwarebreakpoint"}
DELETE_VERBS = {"bphc", "bphwc", "deletehardwarebreakpoint"}
ENABLE_VERBS = {"bphe", "bphwe", "enablehardwarebreakpoint"}
DISABLE_VERBS = {"bphd", "bphwd", "disablehardwarebreakpoint"}


def check(verdict: str, detail: str, suspended=(), stopped=(), tids=FAKE_TIDS, executive=()) -> dict:
    """A check in tools/thread_state.py's shape."""
    return {"verdict": verdict, "threads": len(tids), "progress": 0 if verdict == "frozen" else 120,
            "suspended": [{"tid": t, "suspend_count": 1} for t in suspended], "stopped": list(stopped),
            "unreadable_counts": [], "tids": list(tids), "executive_waits": list(executive), "touched": [],
            "samples": 3, "interval": 0.4, "detail": f"stand-in probe: {detail}"}


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    for _ in range(50):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.01)
    os.replace(tmp, path)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


FRAMES_PER_SECOND = 60
FRAMES_START = 1000


def frame_count(work: Path) -> int:
    """The stand-in game's frame counter now: frozen at `base` while paused,
    running on from it otherwise, and never below the last count printed."""
    st = read_json(work / "frames.json", None) or {}
    base = int(st.get("base", FRAMES_START))
    if not st.get("paused"):
        base += int(FRAMES_PER_SECOND * max(0.0, time.time() - float(st.get("since", time.time()))))
    return max(base, int((read_json(work / "frames_last.json", None) or {}).get("last", 0)))


def set_counter(work: Path, paused: bool) -> None:
    """Freeze (`paused`) or run the counter on from where it is now."""
    write_atomic(work / "frames.json", json.dumps({"paused": paused, "since": time.time(),
                                                   "base": frame_count(work)}))


def parse_addr(text: str) -> int | None:
    t = text.strip().strip('"')
    if t.lower().startswith("0x"):
        t = t[2:]
    try:
        return int(t, 16)
    except ValueError:
        return None


class Threads:
    """Real suspension of the stand-in game's threads (`real_os`): a child
    process the test started itself, which the test kills at cleanup."""

    def __init__(self, pid: int):
        from ctypes import wintypes
        self.w = wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k.OpenThread.restype = wintypes.HANDLE
        k.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.SuspendThread.restype = wintypes.DWORD
        k.SuspendThread.argtypes = [wintypes.HANDLE]
        k.ResumeThread.restype = wintypes.DWORD
        k.ResumeThread.argtypes = [wintypes.HANDLE]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.k = k
        self.pid = pid
        self.suspended: set[int] = set()

    def tids(self) -> list[int]:
        w = self.w

        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ThreadID", w.DWORD),
                        ("th32OwnerProcessID", w.DWORD), ("tpBasePri", w.LONG), ("tpDeltaPri", w.LONG),
                        ("dwFlags", w.DWORD)]

        k = self.k
        k.Thread32First.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
        k.Thread32Next.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
        snap = k.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
        if not snap or snap == w.HANDLE(-1).value:
            return []
        out = []
        try:
            e = Entry()
            e.dwSize = ctypes.sizeof(Entry)
            ok = k.Thread32First(snap, ctypes.byref(e))
            while ok:
                if e.th32OwnerProcessID == self.pid:
                    out.append(int(e.th32ThreadID))
                ok = k.Thread32Next(snap, ctypes.byref(e))
        finally:
            k.CloseHandle(snap)
        return out

    def _do(self, tid: int, suspend: bool) -> bool:
        h = self.k.OpenThread(0x0002, False, tid)  # THREAD_SUSPEND_RESUME
        if not h:
            return False
        try:
            r = (self.k.SuspendThread if suspend else self.k.ResumeThread)(h)
            return r != 0xFFFFFFFF
        finally:
            self.k.CloseHandle(h)

    def read_contexts(self) -> int:
        """One GetThreadContext on each thread this stand-in suspended, as
        x64dbg's memory-map refresh reads each thread's instruction pointer
        while it holds the game; how many reads succeeded."""
        w, k = self.w, self.k
        k.GetThreadContext.argtypes = [w.HANDLE, ctypes.c_void_p]
        k.GetThreadContext.restype = w.BOOL
        buf = ctypes.create_string_buffer(0x4D0 + 16)  # an x64 CONTEXT, 16-byte aligned
        at = (ctypes.addressof(buf) + 15) & ~15
        done = 0
        for tid in sorted(self.suspended):
            h = k.OpenThread(0x0008, False, tid)  # THREAD_GET_CONTEXT
            if not h:
                continue
            try:
                ctypes.c_uint32.from_address(at + 0x30).value = 0x00100001  # ContextFlags: CONTEXT_CONTROL
                done += bool(k.GetThreadContext(h, ctypes.c_void_p(at)))
            finally:
                k.CloseHandle(h)
        return done

    def suspend_all(self, spare: int | None = None) -> None:
        for tid in self.tids():
            if tid != spare and tid not in self.suspended and self._do(tid, True):
                self.suspended.add(tid)

    def resume(self, only: set[int] | None = None) -> None:
        for tid in sorted(self.suspended):
            if only is None or tid in only:
                self._do(tid, False)
                self.suspended.discard(tid)


class Fake:
    def __init__(self, work: Path):
        self.work = work
        self.record = work / "stdin.txt"
        self.bps_file = work / "bps.json"
        self.modes_file = work / "modes.json"
        self.verdict_file = work / "verdict.json"
        self.pause_file = work / "pause_request"
        self.lock = threading.RLock()
        self.modes: dict = {}
        self.bps: list[dict] = []
        self.attached = False
        self.paused = False
        self.state = None
        self.repeat_at: float | None = None
        self.runs = 0
        self.tls_left = 0
        self.late_fired = False
        self.break_after_fired = False
        self.breaks_done = 0
        self.counters: dict[int, int] = {}
        self.silenced: set[int] = set()
        self.next_hit = 0.0
        self.last_command = time.monotonic()
        self.threads: Threads | None = None
        self.next_read: float | None = None
        self.done = False

    # output

    def out(self, line: str) -> None:
        print(line, flush=True)

    def announce(self, state: str) -> None:
        self.state = state
        self.out(f"[STATE] {state}")
        self.repeat_at = time.monotonic() + REPEAT_AFTER

    def verdict(self, c: dict) -> None:
        if self.modes.get("blind_probe") and c["verdict"] == "frozen":
            c = check("running", "blind: progress seen while held")
        write_atomic(self.verdict_file, json.dumps(c))

    def brk(self, line: str | None) -> None:
        """A break: its line (None: none before the pause), then the state
        change. Every game thread is held, as the Replan 3 probe measured at
        a hardware breakpoint's hit, before x64dbg reports the pause."""
        if self.threads is not None:
            self.threads.suspend_all()
        set_counter(self.work, True)
        reads = self.modes.get("context_reads")
        self.next_read = time.monotonic() + float(reads) if reads and self.threads is not None else None
        with (self.work / "breaks.txt").open("a", encoding="utf-8") as f:
            f.write(f"{time.time()!r}\n")
        if line is not None:
            self.out(line)
        self.paused = True
        self.announce("paused")
        held = () if self.modes.get("empty_lists") else FAKE_TIDS
        # breaking_thread N: the first N threads wait in an Executive wait,
        # suspended but not stopped, as the thread that raised the hit did.
        executive = held[:int(self.modes.get("breaking_thread") or 0)]
        stopped = [t for t in held if t not in executive]
        self.verdict(check("frozen", "held at a break", held, stopped, executive=executive))

    def resume(self) -> None:
        self.paused = False
        self.next_read = None
        self.announce("running")
        if self.threads is not None:
            self.threads.resume()
        set_counter(self.work, False)
        self.verdict(check("running", "running"))

    # breakpoints

    def load_bps(self) -> None:
        data = read_json(self.bps_file, None)
        if isinstance(data, list):
            self.bps = [dict(b) for b in data if isinstance(b, dict)]

    def save_bps(self) -> None:
        write_atomic(self.bps_file, json.dumps(self.bps))

    def find(self, arg: str) -> dict | None:
        a = parse_addr(arg)
        for b in self.bps:
            if (a is not None and b["addr"] == a) or b.get("name") == arg.strip().strip('"'):
                return b
        return None

    def armed(self, b: dict) -> bool:
        return int(b.get("enabled", 1)) == 1 and str(b.get("type", "HW")).upper() == "HW"

    def race(self, verb: str, target: int | None) -> None:
        if self.modes.get("race") and verb in DR_VERBS and not self.paused:
            hot = {int(h) for h in self.modes.get("hot", [])}
            for b in self.bps:
                if b["addr"] in hot and b["addr"] != target and self.armed(b):
                    self.silenced.add(b["addr"])

    def hw_break_line(self, b: dict) -> str:
        name = f'"{b["name"]}" ' if b.get("name") else ""
        return f"Hardware breakpoint (byte, execute) {name}at hero_siege.exe+{b['addr'] & 0xFFFFFF:X} ({b['addr']:016X})!"

    def plugin_hold(self, b: dict, logged: bool) -> None:
        """A held change's hold as Live 3 rerun 5 printed it: no break line,
        both state lines at once, the plugin's breakpoint line, then the held
        breakpoint's own log line."""
        self.brk(None)
        self.out("[STATE] paused")
        self.repeat_at = None
        self.out(f"[PLUGIN, MCP - Agent Smithers] Breakpoint {b['addr']:X} in hero_siege.exe")
        if logged:
            self.counters[b["addr"]] = self.counters.get(b["addr"], 0) + 1
            self.out(f"{b.get('log') or 'hit'} #{self.counters[b['addr']]}")

    # stdin

    def handle(self, line: str) -> None:
        text = line.strip()
        if not text:
            return
        verb, _, rest = text.partition(" ")
        low = verb.lower()
        first, _, value = rest.partition(",")
        value = value.strip()
        self.load_bps()
        if low == "attach":
            # No attach break: the Replan 3 probe saw only these states after
            # `attach`, four times out of four, and never `[STATE] paused`.
            self.attached = True
            pid = parse_addr(rest)
            if self.modes.get("real_os") and pid:
                self.threads = Threads(pid)  # read only: nothing is suspended on attach
            self.out("[STATE] initialized")
            self.announce("running")
            self.out("Attached to process!")
            stale = self.modes.get("stale_db")
            if stale:
                a = int(stale) if not isinstance(stale, bool) else 0x7FF6A0427460
                if not any(b["addr"] == a for b in self.bps):
                    self.bps.append({"addr": a, "enabled": 1, "type": "HW"})
                self.out(f"Set hardware breakpoint on {a:016X}!")
            self.tls_left = int(self.modes.get("tls_breaks", 0))
            self.verdict(check("running", "running after attach"))
        elif low == "run":
            if not self.paused:
                return  # x64dbg ignores a run while the game runs
            self.resume()
            self.runs += 1
            if self.modes.get("condition_ignored"):
                # The next hit follows the run at once, in this handler rather
                # than on the ticker, so no scheduling delay can show x64dbg
                # settled at running while the condition is ignored.
                hot = {int(h) for h in self.modes.get("hot", [])}
                for b in self.bps:
                    if b["addr"] in hot and self.armed(b) and b["addr"] not in self.silenced:
                        self.brk(self.hw_break_line(b))
                        break
        elif low == "pause":
            write_atomic(self.pause_file, str(time.time()))
        elif low == "log":
            self.out(rest.strip().strip('"'))
        elif low in ("bph", "bphws", "sethardwarebreakpoint"):
            a = parse_addr(first)
            if a is None:
                self.out("Not enough arguments!")
            elif any(b["addr"] == a for b in self.bps):
                self.out("Hardware breakpoint already set!")
            elif sum(1 for b in self.bps if str(b.get("type", "HW")).upper() == "HW") >= 4:
                self.out("You can only set 4 hardware breakpoints")
            else:
                self.race(low, a)
                if not self.modes.get("false_success"):
                    enabled, kind = self.modes.get("listed_as", [1, "HW"])
                    self.bps.append({"addr": a, "enabled": enabled, "type": kind})
                    self.counters[a] = 0
                hot = {int(h) for h in self.modes.get("hot", [])}
                if self.modes.get("exception_hold") and a in hot and not self.paused:
                    # the hit lands before x64dbg reports the bph set
                    self.out("[TODO] Not implemented GUI_SET_LAST_EXCEPTION (37)")
                    self.brk(None)
                    self.out(f"First chance exception on {a:016X} (80000004, EXCEPTION_SINGLE_STEP)!")
                self.out(f"Hardware breakpoint at {a:016X} set!")
        elif low.startswith("sethardwarebreakpoint") and low != "sethardwarebreakpoint":
            b = self.find(first)
            field = {"sethardwarebreakpointcondition": "cond", "sethardwarebreakpointlog": "log",
                     "sethardwarebreakpointlogcondition": "logcond", "sethardwarebreakpointname": "name"}.get(low)
            if not first.strip() or not value:
                self.out("Not enough arguments!")
            elif b is None:
                self.out(f'No such breakpoint "{first.strip()}"')
            elif field == "cond" and self.modes.get("fail_condition"):
                self.out(f'Can\'t set break condition on breakpoint "{first.strip()}"')
            elif field:
                b[field] = value.strip('"')
                held = self.modes.get("plugin_hold")
                if field == "cond" and value == "1" and held and self.armed(b) and self.attached and not self.paused:
                    self.plugin_hold(b, held != "no_log")
        elif low == "resethardwarebreakpointhitcount":
            b = self.find(first)
            if b is None:
                self.out(f'No such breakpoint "{first.strip()}"')
            else:
                self.counters[b["addr"]] = 0
        elif low in DELETE_VERBS:
            target = parse_addr(first) if first.strip() else None
            self.race(low, target)
            if not self.bps:
                self.out("No hardware breakpoints to delete!")
            elif first.strip():
                b = self.find(first)
                if b is None:
                    self.out(f'No such breakpoint "{first.strip()}"')
                else:
                    self.bps.remove(b)
                    self.out("Hardware breakpoint deleted!")
            else:
                self.bps = []
                self.out("All hardware breakpoints deleted!")
        elif low in ENABLE_VERBS or low in DISABLE_VERBS:
            b = self.find(first)
            self.race(low, b["addr"] if b else None)
            if b is None:
                self.out(f'No such breakpoint "{first.strip()}"')
            else:
                b["enabled"] = 1 if low in ENABLE_VERBS else 0
        elif low == "bplist":
            for b in self.bps:
                name = f':"{b["name"]}"' if b.get("name") else ""
                self.out(f"{int(b.get('enabled', 1))}:{b.get('type', 'HW')}:{b['addr']:016X}{name}")
        elif low == "detach":
            self.announce("stopped")
            self.out("Detached!")
            self.attached = False
            self.paused = False
            # leak_on_detach: the game stays held, so its counter stops;
            # leak_threads_only: the same threads leak, and the game loop runs
            set_counter(self.work, bool(self.modes.get("leak_on_detach")))
            if self.modes.get("leak_on_detach") or self.modes.get("leak_threads_only"):
                if self.threads is not None:
                    spare = self.modes.get("spare_tid")
                    self.threads.suspend_all(spare)
                    if spare in self.threads.suspended:
                        self.threads.resume({spare})
                    self.threads.suspended.clear()  # left suspended on purpose: the test kills the child
                self.verdict(check("threads-suspended", "threads left suspended after detach",
                                   FAKE_TIDS, FAKE_TIDS))
            else:
                if self.threads is not None:
                    self.threads.resume()
                if self.modes.get("threads_gone_after_detach"):
                    self.verdict(check("gone", "stand-in: no process with this pid (pid only)", tids=()))
                else:
                    self.verdict(check("running", "running after detach"))
            if self.modes.get("frames_gone_after_detach"):
                write_atomic(self.work / "frames_gone", "detach")
        elif low == "exit":
            self.done = True
        else:
            self.out(f"Unknown command: \"{verb}\"")
        self.save_bps()
        if (self.modes.get("break_after") or "").lower() == low and not self.break_after_fired and self.attached:
            self.break_after_fired = True
            if not self.paused:
                self.brk("paused!")

    # the game's side, on a timer

    def tick(self) -> None:
        now = time.monotonic()
        self.modes = read_json(self.modes_file, self.modes) or {}
        if self.repeat_at is not None and now >= self.repeat_at:
            self.repeat_at = None
            self.out(f"[STATE] {self.state}")
        if self.paused and self.next_read is not None and now >= self.next_read and self.threads is not None:
            self.threads.read_contexts()
            self.next_read += float(self.modes.get("context_reads") or 1.0)
        if not self.attached or self.paused:
            return
        settled = self.repeat_at is None  # the last state change has been repeated
        if self.tls_left > 0 and settled:
            n = int(self.modes.get("tls_breaks", 0)) - self.tls_left + 1
            self.tls_left -= 1
            self.brk(f'INT3 breakpoint "TLS Callback 1 (x{n}.dll)" at x{n}.dll+1000 (00007FFB2000{n:04X})!')
            return
        if self.modes.get("never_running") and settled:
            self.brk("INT3 breakpoint at 00007FF6A0001000!")
            return
        if self.pause_file.exists():
            try:
                at = float(self.pause_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                at = 0.0
            if time.time() >= at + ASYNC_PAUSE_AFTER:
                self.pause_file.unlink(missing_ok=True)
                self.brk("paused!")
                return
        late = self.modes.get("late_break")
        if late and not self.late_fired and now - self.last_command >= float(late):
            self.late_fired = True
            self.brk("paused!")
            return
        if self.breaks_done < int(self.modes.get("breaks", 0)):
            self.breaks_done += 1
            self.brk(f'INT3 breakpoint "storm {self.breaks_done}" at 00007FF6A0001000!')
            return
        if now < self.next_hit:
            return
        self.next_hit = now + HIT_EVERY
        hot = {int(h) for h in self.modes.get("hot", [])}
        for b in self.bps:
            if b["addr"] not in hot or not self.armed(b) or b["addr"] in self.silenced:
                continue
            cond = b.get("cond")
            if self.modes.get("condition_ignored") or cond is None or str(cond).strip() != "0":
                self.brk(self.hw_break_line(b))
                return
            self.counters[b["addr"]] = self.counters.get(b["addr"], 0) + 1
            self.out(f"{b.get('log') or 'hit'} #{self.counters[b['addr']]}")

    def ticker(self) -> None:
        while not self.done:
            with self.lock:
                self.tick()
            time.sleep(TICK)

    def run(self) -> None:
        self.modes = read_json(self.modes_file, {}) or {}
        threading.Thread(target=self.ticker, daemon=True).start()
        self.out("fake headless: reading commands")
        for raw in sys.stdin.buffer:
            line = raw.decode("utf-8").rstrip("\r\n")
            with self.record.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            with self.lock:
                self.last_command = time.monotonic()
                # a mode a test set just before this command applies to it,
                # however late the ticker runs on a loaded machine
                self.modes = read_json(self.modes_file, self.modes) or {}
                self.handle(line)
                if self.done:
                    break


def probe(work: Path) -> int:
    with (work / "probes.txt").open("a", encoding="utf-8") as f:
        f.write(f"{time.time()!r}\n")
    c = read_json(work / "verdict.json", None) or check("running", "running (nothing written yet)")
    print(json.dumps(c))
    return 0 if c.get("verdict") == "running" else 1


def frames(work: Path, timeout: float) -> int:
    """One reading of the stand-in's frame counter, as the frames seam."""
    modes = read_json(work / "modes.json", None) or {}
    paused = bool((read_json(work / "frames.json", None) or {}).get("paused"))
    held = paused and not modes.get("frames_never_stall")
    if (work / "frames_gone").exists():  # frames_gone_after_detach
        print(json.dumps({"answered": False, "frames": None, "pong": False, "reason": "gone", "elapsed_s": 0.0,
                          "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                          "detail": "stand-in counter: the game exited"}))
        return 0
    reading = {"answered": False, "frames": None, "pong": False, "reason": "not_consumed", "elapsed_s": timeout,
               "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "detail": "stand-in counter: nothing consumed the command"}
    if not modes.get("frames_dead") and (not held or modes.get("frames_answer_held")):
        last = int((read_json(work / "frames_last.json", None) or {}).get("last", 0))
        now = frame_count(work)
        n = now if held else (now if now > last else last + 1)
        write_atomic(work / "frames_last.json", json.dumps({"last": n}))
        reading.update(answered=True, frames=n, pong=True, reason="answered",
                       elapsed_s=0.4 if held else float(modes.get("frames_slow") or 0.4),
                       detail=f"stand-in counter: incident: frames {n}")
    print(json.dumps(reading))
    return 0


if __name__ == "__main__":
    if sys.argv[1] == "probe":
        sys.exit(probe(Path(sys.argv[2])))
    if sys.argv[1] == "frames":
        sys.exit(frames(Path(sys.argv[2]), float(sys.argv[4])))
    Fake(Path(sys.argv[1])).run()
