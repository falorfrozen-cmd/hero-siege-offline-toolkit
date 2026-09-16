#!/usr/bin/env python3
"""Stop hook: report processes this session started and left running.

`AGENTS.md` section "Clean Up the Processes You Started Before Ending a Reply"
is the rule this enforces. A Bash/PowerShell/Monitor tool call can start a dev
server, a `cargo` build, a `tauri-mcp driver-session`, or a detached child that
outlives the reply that started it. Over a long day those pile up and fill
memory. This hook never fixes that -- it only tells Claude, once, so a reply
either kills what it started or says why it is being left running.

## Mechanism: a per-call snapshot diff, plus a session ledger

Run in three modes, chosen by `sys.argv[1]`:

  - `pre` (PreToolUse, matcher `Bash|PowerShell|Monitor`): snapshot every live
    process and stash it for this call.
  - `post` (PostToolUse, same matcher): snapshot again, diff against `pre`, and
    admit the processes that this call's own tool use can be blamed for into
    the session's ledger. See "Admission rules" below.
  - `stop` (Stop, no matcher): snapshot once more, extend the ledger with live
    descendants of live ledger entries, then report whichever ledger entries
    are still alive and have not been reported before.

A process is identified by the pair **(pid, creation time)**, never PID alone,
because Windows reuses PIDs quickly. `GetProcessTimes` supplies the creation
time; a parent link is only trusted when the parent's creation time is at or
before the child's -- otherwise the PPID has been recycled and the process is
treated as an orphan instead. Any process this hook cannot open with
`PROCESS_QUERY_LIMITED_INFORMATION` is skipped outright: it belongs to another
user or is protected, and a process this session started is never either.

### Rejected alternatives (recorded so nobody re-proposes them)

1. **Report every live descendant of the session's `claude.exe` at Stop.**
   MCP servers are exactly such descendants, and without command lines the
   only way to exclude them is name matching -- fragile, since
   `tauri-mcp driver-session` (which *should* be reported) contains "mcp".
   It also misses the case that matters most: `Start-Process`, `cmd /c start`
   and detached `npm` scripts leave a child whose parent has already exited,
   so no descendant walk from a living ancestor ever reaches it.
2. **Report every orphan created since the session started.** Multiple
   sessions can run at once. Timing alone cannot tell one session's orphan
   from another's, and a process belonging to a session that did not start it
   must never be reported.
3. **Read another process's environment for a session marker.** That means
   `ReadProcessMemory` against someone else's PEB -- a layout assumption about
   memory this hook does not own, for a reporting tool that does not need it.
4. **`psutil`.** Not installed on the machines this runs on; every hook here
   uses only the standard library.

### Admission rules (`post` mode)

A process P newly alive at `post` (its (pid, creation) was not present at
`pre`) is admitted into the ledger when at least one holds:

  (a) P's valid-parent chain reaches the session root R (the nearest `claude.exe`
      ancestor of this hook process), and every ancestor strictly between P and
      R is *also* new this call. A child of an MCP server, or of any other
      process that predates the call, is not admitted -- its chain passes
      through something that already existed.
  (b) P is an orphan (its PPID is dead, or alive with a *later* creation time,
      meaning the PID was recycled) **and** that PPID was not present at `pre`
      either. The parent was born and died inside this call's window, which is
      the `Start-Process` / `cmd /c start` shape rule (a) cannot see.
  (c) P's valid parent already has a ledger entry (live, or dead with a
      creation time earlier than P's).

Rule (b) carries a known, accepted risk: if some *other* session's short-lived
shell starts and exits during this call and happens to leave an orphan behind,
rule (b) attributes it here. The window is one tool call wide, not the whole
session, which is why this was accepted over alternative 2 above. Because this
hook only ever reports, the cost of a wrong attribution is one line Claude can
answer with "not mine" -- never a kill.

The hook's own ancestor chain up to R, any `conhost.exe` (which dies with its
owner and is pure noise), and any chain that is actually *running* one of this
repo's `.claude/hooks/*` scripts, are never admitted. The last one exists
because a concurrent sibling hook (a `PostToolUse` group runs in parallel with
this one) spawns its own new `bash -> bash -> py -> python` chain that reaches
R through processes that are, from this call's point of view, indistinguishable
from a real leftover under rule (a) -- a live Stop on 2026-09-16 10:51 reported
eleven of them. Rules (b) and (c) apply the same command-line check for the
same reason.

"Actually running" is load-bearing, not a bare mention. The first version of
this check matched any command line containing the substring `.claude/hooks/`
anywhere at all, which also matches a Bash tool call that merely *talks about*
that path -- `echo .claude/hooks/ >/dev/null; py -3 -c "..."` hid its own
`py`/`python` and every wrapping shell from the ledger, live A/B confirmed. The
fix matches against the actual `$CLAUDE_PROJECT_DIR/.claude/hooks/<name>.py`
fragments read from `.claude/settings.json`'s own hook `command` strings, in
both the form a wrapping shell hop still carries unexpanded and the form a
`py`/`python` descendant shows once that shell has substituted the real
project directory in -- never a bare substring of the directory name, which
arbitrary command text can contain without invoking anything there.

Two more identity details, both found the same way -- a live Stop misreporting
something that was not actually a leftover:

  - `snapshot()` drops any PID it cannot `OpenProcess` (a SYSTEM service, a
    protected process). Do not read "not in the openable snapshot" as "does
    not exist": `dllhost.exe`/`audiodg.exe` under an unopenable `svchost.exe`
    looked exactly like orphans under rule (b) until the raw Toolhelp32 PID
    list -- unfiltered by openability -- was consulted to tell "unopenable"
    apart from "gone".
  - A ledger entry's PID can be reused by an unrelated process before `Stop`
    runs. Rule (c) must not trust `entry.creation <= proc.creation` against a
    *dead* ledger entry on its own -- that comparison is true for any later
    process, reused PID or not -- so it is only trusted when the PID is either
    still alive with the *same* creation time, or died during this same call
    (present at `pre`, gone by `post`).

### Known limitation -- not observed, not "cannot happen"

If a whole parent chain back to a ledger entry dies between two observations
(for example `cargo` exits while the `hub.exe` it started survives, with
neither `post` nor `stop` running in between), the survivor cannot be
attributed through this ledger and will not be reported. `AGENTS.md`'s
"verify with a command" is the backstop for exactly this gap.

Separately, `Stop`'s liveness check trusts `GetExitCodeProcess`
(`STILL_ACTIVE`, 259) over Toolhelp32 membership: a just-terminated PID can
still appear in a Toolhelp32Snapshot for a brief window after the process
object is gone (observed as an intermittent false report of an already-killed
test process), and the exit code is the authoritative answer.

## Two environment variables

  - `HSTK_PROC_LEDGER_DIR`: where the ledger lives. Defaults to
    `<tempfile.gettempdir()>/hstk-leftover-processes`. Deliberately never
    inside the repository -- `decompiled_output.py` scans every untracked
    file, and a ledger in the worktree would show up in `git status` on every
    tool call.
  - `HSTK_PROC_SESSION_ROOT_PID`: use this PID as the session root instead of
    searching for the nearest `claude.exe` ancestor. Exists for tests. If no
    `claude.exe` ancestor can be found and this is unset, `post` admits
    nothing and `stop` says so once on stderr rather than staying silently
    blind.

Never kills anything: no Win32 call that ends a process, no signal sent from
Python, no `taskkill`/`Stop-Process`, and it never spawns a child process of
its own. It reports; the reply (or
the human) decides what to do about it.
"""

import ctypes
import functools
import json
import os
import re
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SKIP_HINT, skip_requested  # noqa: E402

# -- Win32 plumbing -----------------------------------------------------

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None
ntdll = ctypes.WinDLL("ntdll", use_last_error=True) if sys.platform == "win32" else None

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_COMMAND_LINE_INFORMATION = 60
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
STILL_ACTIVE = 259

_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"

# The unexpanded fragment every configured hook `command` string carries, e.g.
# `$CLAUDE_PROJECT_DIR/.claude/hooks/decompiled_output.py`. No quoting or
# `py -3` prefix is included on purpose: this repo's hooks are invoked through
# a shell wrapper, and matching only the fragment lets a substring search find
# it regardless of how that wrapper's own command line quotes the rest.
_HOOK_FRAGMENT_RE = re.compile(r"\$CLAUDE_PROJECT_DIR/\.claude/hooks/[^\s\"]+\.py")


@functools.lru_cache(maxsize=1)
def _hook_path_fragments():
    """Every `$CLAUDE_PROJECT_DIR/.claude/hooks/<name>.py` fragment configured
    in `.claude/settings.json`'s own hook `command` strings, unexpanded."""
    try:
        settings = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    fragments = set()
    for groups in settings.get("hooks", {}).values():
        for group in groups:
            for entry in group.get("hooks", []):
                match = _HOOK_FRAGMENT_RE.search(entry.get("command", "") or "")
                if match:
                    fragments.add(match.group(0))
    return tuple(fragments)


@functools.lru_cache(maxsize=1)
def _hook_process_markers():
    """Every string that identifies a hop as genuinely running one of this
    repo's hooks -- never a bare mention of the hooks directory.

    Two forms per configured hook, both observed live: the fragment as written
    (`$CLAUDE_PROJECT_DIR/...`), which the wrapping shell hop still carries
    unexpanded, and the same fragment with `$CLAUDE_PROJECT_DIR` replaced by
    the real project directory (both slash styles), which is what a `py`/
    `python` descendant's own command line shows once that shell has expanded
    it. `CLAUDE_PROJECT_DIR` is the same environment variable `settings.json`
    itself references, and it is inherited down this hook's own ancestry the
    same way it reaches every hop below the shell that first resolved it.
    """
    fragments = _hook_path_fragments()
    markers = set(fragments)
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir:
        for fragment in fragments:
            expanded = fragment.replace("$CLAUDE_PROJECT_DIR", project_dir)
            markers.add(expanded)
            markers.add(expanded.replace("/", "\\"))
    return tuple(marker.lower() for marker in markers)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("MaximumLength", ctypes.c_ushort),
        ("Buffer", ctypes.c_void_p),
    ]


def _iter_processes():
    """Yield (pid, ppid, image_name) for every process Toolhelp32 can see."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE or snap == 0:
        return
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return
        while True:
            yield entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile
            if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snap)


def _creation_time(pid):
    """FILETIME (as a 64-bit int) the process was created, or None if unreadable.

    A process this hook cannot open belongs to another user or is protected --
    never a process this session started -- so it is left out of the snapshot
    entirely rather than guessed at.
    """
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        ok = kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        )
        if not ok:
            return None
        return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    finally:
        kernel32.CloseHandle(handle)


def _command_line(pid):
    """Best-effort full command line via NtQueryInformationProcess. None on failure."""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf_len = 8192
        buf = ctypes.create_string_buffer(buf_len)
        returned = wintypes.ULONG(0)
        status = ntdll.NtQueryInformationProcess(
            handle,
            PROCESS_COMMAND_LINE_INFORMATION,
            buf,
            buf_len,
            ctypes.byref(returned),
        )
        if status != 0:
            return None
        info = UNICODE_STRING.from_buffer(buf)
        if not info.Buffer or info.Length == 0:
            return ""
        offset = info.Buffer - ctypes.addressof(buf)
        if not (0 <= offset < buf_len):
            return None
        return ctypes.wstring_at(ctypes.addressof(buf) + offset, info.Length // 2)
    except OSError:
        return None
    finally:
        kernel32.CloseHandle(handle)


def _is_still_active(pid):
    """True only when `GetExitCodeProcess` reports `STILL_ACTIVE` (259).

    Toolhelp32Snapshot can keep listing a PID for a brief window after it has
    already terminated -- observed as an intermittent false report of a test
    process this suite had just killed and waited on. The exit code is the
    authoritative check; a PID a snapshot still lists but has already exited
    must never be reported as a leftover.
    """
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return bool(ok) and code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def snapshot():
    """(procs, raw_pids): the openable process table, plus every PID seen.

    `procs` is `{pid: {"pid", "ppid", "image", "creation"}}`, filtered to
    processes this hook could open (a process this session started never
    requires privileges this hook lacks). `raw_pids` is the unfiltered PID set
    Toolhelp32 reported, kept so admission logic can tell "this PID does not
    exist" apart from "this PID exists but this hook could not open it" (a
    SYSTEM service, a protected process) -- collapsing the two made an
    unopenable *live* parent look exactly like a dead one.
    """
    procs = {}
    raw_pids = set()
    for pid, ppid, image in _iter_processes():
        raw_pids.add(pid)
        creation = _creation_time(pid)
        if creation is None:
            continue
        procs[pid] = {"pid": pid, "ppid": ppid, "image": image, "creation": creation}
    return procs, raw_pids


# -- ledger bookkeeping ---------------------------------------------------


def _sanitize(value):
    return re.sub(r"[^A-Za-z0-9_-]", "_", value or "")


def _ledger_root():
    base = os.environ.get("HSTK_PROC_LEDGER_DIR") or os.path.join(
        tempfile.gettempdir(), "hstk-leftover-processes"
    )
    return Path(base)


def _session_dir(session_id, create=True):
    d = _ledger_root() / _sanitize(session_id)
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _load_snapshot_file(path):
    """Load a ledger file (`post-*.json`): a flat `{pid: entry}` map."""
    data = _read_json(path, {})
    return {int(pid): entry for pid, entry in data.items()}


def _write_pre_snapshot(path, procs, raw_pids):
    """`pre-*.json` carries both the openable snapshot and the raw PID set
    `_is_orphan_admissible` needs -- see `snapshot()`."""
    _write_json(
        path,
        {"procs": {str(pid): entry for pid, entry in procs.items()}, "raw_pids": sorted(raw_pids)},
    )


def _load_pre_snapshot(path):
    """The inverse of `_write_pre_snapshot`, or `None` if the file is missing
    or not in that shape. Callers must treat `None` as "no usable baseline",
    not as an empty one -- an empty baseline would make every live process on
    the machine look new since `pre` (see `cmd_post`)."""
    data = _read_json(path, None)
    if not isinstance(data, dict) or "procs" not in data:
        return None
    procs = {int(pid): entry for pid, entry in data.get("procs", {}).items()}
    raw_pids = {int(pid) for pid in data.get("raw_pids", [])}
    return procs, raw_pids


def _load_ledger(sdir):
    """Merge every `post-*.json` in the session directory into one dict."""
    ledger = {}
    if not sdir.exists():
        return ledger
    for path in sorted(sdir.glob("post-*.json")):
        ledger.update(_load_snapshot_file(path))
    return ledger


def _prune_old_sessions(root, max_age_days=7):
    if not root.exists():
        return
    cutoff = time.time() - max_age_days * 86400
    for child in root.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                for item in sorted(child.glob("**/*"), reverse=True):
                    try:
                        if item.is_file():
                            item.unlink()
                        else:
                            item.rmdir()
                    except OSError:
                        pass
                child.rmdir()
        except OSError:
            pass


# -- identity and admission logic -----------------------------------------


def _valid_parent(child, parent):
    """A PPID link is only trusted when the parent predates the child."""
    if child.get("creation") is None or parent.get("creation") is None:
        return False
    return parent["creation"] <= child["creation"]


def _locate_root_and_chain(hook_pid, snap):
    """Nearest `claude.exe` ancestor of the hook process, and the chain to it.

    The chain (excluding the root itself) is returned so callers can exclude
    the hook's own invocation from admission -- the `py -3 ... post` call
    itself is a newly created process relative to `pre` and must never be
    reported as a leftover of the tool call it is inspecting.
    """
    override = os.environ.get("HSTK_PROC_SESSION_ROOT_PID")
    if override:
        try:
            return int(override), set()
        except ValueError:
            return None, set()

    chain = set()
    seen = set()
    pid = hook_pid
    while True:
        if pid in seen:
            return None, chain
        seen.add(pid)
        proc = snap.get(pid)
        if proc is None:
            return None, chain
        if proc["image"].lower() == "claude.exe":
            return pid, chain
        chain.add(pid)
        parent_pid = proc["ppid"]
        parent = snap.get(parent_pid)
        if parent is None or not _valid_parent(proc, parent):
            return None, chain
        pid = parent_pid


def _is_hook_process_cmdline(cmdline):
    if not cmdline:
        return False
    lowered = cmdline.lower()
    return any(marker in lowered for marker in _hook_process_markers())


def _is_hook_chain(pid, snap, root):
    """True when `pid`, or an ancestor strictly between it and `root`, is
    itself running one of this repo's `.claude/hooks/*` scripts.

    A concurrent sibling `PostToolUse` hook spawns its own new
    `bash -> bash -> py -> python .claude/hooks/*.py` chain during this
    call's window, which reaches `root` through processes that are otherwise
    indistinguishable from a real leftover under rules (a)/(b)/(c) -- a live
    Stop on 2026-09-16 10:51 reported eleven of them this way. This is checked
    against every admission rule, not just (a): rule (b)'s orphan test and
    rule (c)'s ledger-parent test do not themselves look at command lines.
    """
    seen = set()
    cur = pid
    while True:
        if cur == root or cur in seen:
            return False
        seen.add(cur)
        proc = snap.get(cur)
        if proc is None:
            return False
        if _is_hook_process_cmdline(_command_line(cur)):
            return True
        parent_pid = proc["ppid"]
        parent = snap.get(parent_pid)
        if parent is None or not _valid_parent(proc, parent):
            return False
        cur = parent_pid


def _chain_reaches_root(pid, post_snap, new_pids, root):
    """Rule (a): every hop strictly between `pid` and `root` is itself new."""
    seen = set()
    cur = pid
    first = True
    while True:
        if cur == root:
            return True
        if cur in seen:
            return False
        seen.add(cur)
        proc = post_snap.get(cur)
        if proc is None:
            return False
        if not first and cur not in new_pids:
            return False
        parent_pid = proc["ppid"]
        parent = post_snap.get(parent_pid)
        if parent is None or not _valid_parent(proc, parent):
            return False
        cur = parent_pid
        first = False


def _is_orphan_admissible(proc, post_snap, pre_snap, post_raw_pids, pre_raw_pids):
    """Rule (b): a parent born and killed inside this call's own window.

    `post_raw_pids`/`pre_raw_pids` are the unfiltered Toolhelp32 PID sets from
    `snapshot()`, not the openable `post_snap`/`pre_snap` maps: a PPID this
    hook could not open (a SYSTEM service, a protected process) is a live
    parent, not a missing one, and `post_snap`/`pre_snap` cannot tell the two
    apart -- `dllhost.exe`/`audiodg.exe` under an unopenable `svchost.exe`
    looked exactly like orphans until this distinction was added.
    """
    parent_pid = proc["ppid"]
    parent = post_snap.get(parent_pid)
    if parent is not None:
        if _valid_parent(proc, parent):
            return False  # a live, valid parent -- not an orphan at all
        # Openable, but its creation postdates the child: the original PPID
        # died and this PID has already been reused by something else.
        return parent_pid not in pre_snap
    if parent_pid in post_raw_pids:
        return False  # exists at post, just unopenable -- not an orphan
    return parent_pid not in pre_raw_pids


def _parent_in_ledger(proc, ledger, post_snap, pre_snap):
    """Rule (c): the parent already has a ledger entry that predates `proc`.

    `entry.creation <= proc.creation` is true for *any* later process once the
    ledger entry is dead, reused PID or not, so a dead entry is only trusted
    when it can be shown to have died during *this* call (present at `pre`,
    gone by `post`). A live entry must match the *current* occupant of that
    PID exactly, not merely predate it.
    """
    parent_pid = proc["ppid"]
    entry = ledger.get(parent_pid)
    if entry is None or entry.get("creation") is None or proc.get("creation") is None:
        return False
    live_parent = post_snap.get(parent_pid)
    if live_parent is not None:
        return live_parent["creation"] == entry["creation"]
    return any(
        p["pid"] == parent_pid and p["creation"] == entry["creation"]
        for p in pre_snap.values()
    )


def _parent_is_live_ledger_entry(proc, ledger, live_snap):
    """Stricter form of rule (c) used only to extend the ledger at Stop:
    the parent must still be alive and match its recorded identity, not merely
    have died with an earlier creation time."""
    parent_pid = proc["ppid"]
    entry = ledger.get(parent_pid)
    live_parent = live_snap.get(parent_pid)
    if entry is None or live_parent is None:
        return False
    return live_parent["creation"] == entry["creation"] and _valid_parent(proc, live_parent)


def _admit_new(
    new_procs, post_snap, pre_snap, post_raw_pids, pre_raw_pids, root, hook_chain, ledger
):
    admitted = {}
    for pid, proc in new_procs.items():
        if pid in hook_chain:
            continue
        if proc["image"].lower() == "conhost.exe":
            continue
        if _is_hook_chain(pid, post_snap, root):
            continue
        if (
            _chain_reaches_root(pid, post_snap, new_procs, root)
            or _is_orphan_admissible(proc, post_snap, pre_snap, post_raw_pids, pre_raw_pids)
            or _parent_in_ledger(proc, ledger, post_snap, pre_snap)
        ):
            admitted[pid] = proc
    return admitted


def _extend_ledger_with_live_descendants(ledger, live_snap, root):
    """A grandchild spawned after `post`, of a parent this ledger already owns."""
    added = {}
    combined = dict(ledger)
    changed = True
    while changed:
        changed = False
        for pid, proc in live_snap.items():
            if pid in combined:
                continue
            if proc["image"].lower() == "conhost.exe":
                continue
            if _is_hook_chain(pid, live_snap, root):
                continue
            if _parent_is_live_ledger_entry(proc, combined, live_snap):
                added[pid] = proc
                combined[pid] = proc
                changed = True
    return added


# -- the three modes --------------------------------------------------------


def cmd_pre(payload):
    session = _sanitize(payload.get("session_id"))
    tool_use_id = _sanitize(payload.get("tool_use_id"))
    if not session or not tool_use_id:
        return 0
    sdir = _session_dir(session)
    procs, raw_pids = snapshot()
    _write_pre_snapshot(sdir / f"pre-{tool_use_id}.json", procs, raw_pids)
    return 0


def cmd_post(payload):
    session = _sanitize(payload.get("session_id"))
    tool_use_id = _sanitize(payload.get("tool_use_id"))
    if not session or not tool_use_id:
        return 0
    sdir = _session_dir(session)
    pre_path = sdir / f"pre-{tool_use_id}.json"
    loaded = _load_pre_snapshot(pre_path) if pre_path.exists() else None
    if loaded is None:
        # No usable baseline for this call -- record nothing rather than
        # treating every live process on the machine as "new since pre".
        pre_path.unlink(missing_ok=True)
        _write_json(sdir / f"post-{tool_use_id}.json", {})
        return 0
    pre_snap, pre_raw_pids = loaded

    post_snap, post_raw_pids = snapshot()
    root, hook_chain = _locate_root_and_chain(os.getpid(), post_snap)
    if root is None:
        pre_path.unlink(missing_ok=True)
        return 0

    pre_keys = {(p["pid"], p["creation"]) for p in pre_snap.values()}
    new_procs = {
        pid: p for pid, p in post_snap.items() if (pid, p["creation"]) not in pre_keys
    }
    ledger = _load_ledger(sdir)
    admitted = _admit_new(
        new_procs, post_snap, pre_snap, post_raw_pids, pre_raw_pids, root, hook_chain, ledger
    )

    _write_json(sdir / f"post-{tool_use_id}.json", admitted)
    pre_path.unlink(missing_ok=True)
    return 0


def _format_time(filetime):
    # FILETIME: 100ns ticks since 1601-01-01. Convert to a Unix timestamp.
    unix_ts = (filetime - 116444736000000000) / 10_000_000
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(unix_ts))
    except (OverflowError, OSError, ValueError):
        return "unknown time"


def cmd_stop(payload):
    if payload.get("stop_hook_active"):
        return 0
    if skip_requested():
        return 0

    session = _sanitize(payload.get("session_id"))
    if not session:
        return 0

    root_dir = _ledger_root()
    _prune_old_sessions(root_dir)
    sdir = _session_dir(session)

    live_snap, _live_raw_pids = snapshot()
    root, _chain = _locate_root_and_chain(os.getpid(), live_snap)
    if root is None:
        sys.stderr.write("leftover_processes: no claude.exe ancestor; not tracking\n")
        return 0

    ledger = _load_ledger(sdir)
    extended = _extend_ledger_with_live_descendants(ledger, live_snap, root)
    if extended:
        seq = len(list(sdir.glob("post-stop-*.json")))
        _write_json(sdir / f"post-stop-{seq}.json", extended)
        ledger.update(extended)

    reported_path = sdir / "reported.json"
    reported = _read_json(reported_path, {})
    reported = {int(pid): creation for pid, creation in reported.items()}

    leftovers = {}
    for pid, entry in ledger.items():
        live = live_snap.get(pid)
        if live is None or live["creation"] != entry["creation"]:
            continue
        if not _is_still_active(pid):
            continue
        if reported.get(pid) == entry["creation"]:
            continue
        leftovers[pid] = live

    if not leftovers:
        return 0

    for pid, entry in leftovers.items():
        reported[pid] = entry["creation"]
    _write_json(reported_path, reported)

    lines = [
        "Processes this session's tool calls started are still running:",
        "",
    ]
    for pid, entry in sorted(leftovers.items()):
        cmdline = _command_line(pid) or entry["image"]
        lines.append(
            f"  PID {pid}  {entry['image']}  started {_format_time(entry['creation'])}"
        )
        lines.append(f"    {cmdline}")
    lines += [
        "",
        "Stop it (for example `taskkill /PID <pid> /T /F`), unless it is a",
        "background agent or shell of this session that is still working --",
        "that is a valid reason to leave it, so say so and name the PID rather",
        "than treating this report as an error. If the user asked for it to keep",
        "running, say that instead, naming the PID. Attribution here is by call",
        "window, not a certainty -- see AGENTS.md's leftover-processes section",
        "if this looks wrong.",
        "",
        SKIP_HINT,
    ]
    sys.stderr.write("\n".join(lines) + "\n")
    return 2


def main():
    if sys.platform != "win32":
        return 0
    if len(sys.argv) < 2:
        return 0
    mode = sys.argv[1]
    if mode not in ("pre", "post", "stop"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    if mode == "pre":
        return cmd_pre(payload)
    if mode == "post":
        return cmd_post(payload)
    return cmd_stop(payload)


if __name__ == "__main__":
    sys.exit(main())
