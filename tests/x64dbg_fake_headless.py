"""A stand-in for headless x64dbg, for tests/test_x64dbg_mcp.py.

    python x64dbg_fake_headless.py <workdir>            # headless x64dbg
    python x64dbg_fake_headless.py probe <workdir> <pid>  # the keeper's probe seam

As headless, it reads commands on stdin, records each line in
`<workdir>/stdin.txt`, and prints on stdout (the session log) what x64dbg
prints, as measured live or as read from x64dbg's source
(docs/tools/x64dbg-mcp.md): `[STATE] <name>` on every debug-state change,
once at once and again shortly after, the `log` markers, `bph`'s success
line, nothing for a `Set*` step that succeeds, `bplist` rows, the deletion
lines, `Detached!`, a log line per hit of a hot logging breakpoint, and a
break line plus `[STATE] paused` for every break. Synthetic text of our own,
not x64dbg's source.

As the probe seam, it prints the outside check of the game it last wrote to
`<workdir>/verdict.json` (`running` until it writes one), as
`py -3 -m tools.thread_state <pid>` would.

Files in `<workdir>`:
- `stdin.txt`: every line read on stdin, in order;
- `bps.json`: the breakpoint list, shared with the stand-in plugin;
- `modes.json`: the modes below, re-read every tick, so a test can change one
  mid-session;
- `verdict.json`: the outside check the probe prints;
- `pause_request`: left by the stand-in plugin's asynchronous PauseDebug.

Modes:
- `tls_breaks` N: N breaks right after the first run, each on an x64dbg
  TLS-callback breakpoint;
- `late_break` S: one unprompted break S seconds after the last command (the
  asynchronous pause landing late, as Live 2 measured);
- `breaks` N: N breaks in a row from now on, one after each run (a storm);
- `break_after` <verb>: one break right after the first command with that verb;
- `window_break`: a hit between `bph` and its condition breaks, when the game
  is not held;
- `condition_ignored`: an armed hot breakpoint breaks on every hit;
- `never_running`: every run is followed by a new break;
- `race`: a command that changes debug registers, arriving while the game is
  not held and a hot logpoint is armed, silences that logpoint (the lost DR7
  update);
- `leak_on_detach`: after `detach`, every game thread but one stays suspended;
- `fail_condition`: `SetHardwareBreakpointCondition` prints its failure;
- `listed_as` [enabled, type]: the row's enabled flag and type;
- `false_success`: `bph` prints success, and no row follows;
- `hot` [addr, ...]: the armed breakpoints the game hits, every 50 ms;
- `blind_probe`: the probe never reads `frozen` (an instrument that cannot
  see a held game);
- `empty_lists`: the probe reads `frozen` at the attach break but names no
  suspended or stopped thread (an instrument that read no thread at all);
- `real_os`: suspend the stand-in game's threads for real at the attach break
  and under `leak_on_detach`, and resume them on `run` (`spare_tid` is the
  one left running).
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
FAKE_TIDS = (9001, 9002)  # the probe seam's game threads, "suspended" under leak_on_detach
BREAKIN_TID = 9003  # the debugger's break-in thread, first seen at the attach break
DR_VERBS = {"bph", "bphws", "sethardwarebreakpoint", "bphc", "bphwc", "deletehardwarebreakpoint",
            "bphe", "bphwe", "enablehardwarebreakpoint", "bphd", "bphwd", "disablehardwarebreakpoint"}
DELETE_VERBS = {"bphc", "bphwc", "deletehardwarebreakpoint"}
ENABLE_VERBS = {"bphe", "bphwe", "enablehardwarebreakpoint"}
DISABLE_VERBS = {"bphd", "bphwd", "disablehardwarebreakpoint"}


def check(verdict: str, detail: str, suspended=(), stopped=(), tids=FAKE_TIDS) -> dict:
    """A check in tools/thread_state.py's shape."""
    return {"verdict": verdict, "threads": len(tids), "progress": 0 if verdict == "frozen" else 120,
            "suspended": [{"tid": t, "suspend_count": 1} for t in suspended], "stopped": list(stopped),
            "unreadable_counts": [], "tids": list(tids),
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

    def brk(self, line: str) -> None:
        """A break: its line, then the state change."""
        self.out(line)
        self.paused = True
        self.announce("paused")
        self.verdict(check("frozen", "held at a break"))

    def resume(self) -> None:
        self.paused = False
        self.announce("running")
        if self.threads is not None:
            self.threads.resume()
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
            self.attached = True
            pid = parse_addr(rest)
            self.out("Attached to process!")
            if self.modes.get("real_os") and pid:
                self.threads = Threads(pid)
                self.threads.suspend_all()
            self.paused = True
            self.announce("paused")
            # Every game thread held, as the child probe measured a pending debug
            # event, and the break-in thread new and not suspended.
            held = () if self.modes.get("empty_lists") else FAKE_TIDS
            self.verdict(check("frozen", "held at the attach break", held, held, (*FAKE_TIDS, BREAKIN_TID)))
        elif low == "run":
            if not self.paused:
                return  # x64dbg ignores a run while the game runs
            self.resume()
            self.runs += 1
            if self.runs == 1:
                self.tls_left = int(self.modes.get("tls_breaks", 0))
            if self.tls_left > 0:
                n = int(self.modes.get("tls_breaks", 0)) - self.tls_left + 1
                self.tls_left -= 1
                self.brk(f'INT3 breakpoint "TLS Callback 1 (x{n}.dll)" at x{n}.dll+1000 (00007FFB2000{n:04X})!')
            elif self.modes.get("never_running"):
                self.brk("INT3 breakpoint at 00007FF6A0001000!")
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
                self.out(f"Hardware breakpoint at {a:016X} set!")
                if self.modes.get("window_break") and not self.paused and not self.modes.get("false_success"):
                    self.brk(self.hw_break_line(self.bps[-1]))
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
            if self.modes.get("leak_on_detach"):
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
                self.verdict(check("running", "running after detach"))
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
        if not self.attached or self.paused:
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
                self.handle(line)
                if self.done:
                    break


def probe(work: Path) -> int:
    c = read_json(work / "verdict.json", None) or check("running", "running (nothing written yet)")
    print(json.dumps(c))
    return 0 if c.get("verdict") == "running" else 1


if __name__ == "__main__":
    if sys.argv[1] == "probe":
        sys.exit(probe(Path(sys.argv[2])))
    Fake(Path(sys.argv[1])).run()
