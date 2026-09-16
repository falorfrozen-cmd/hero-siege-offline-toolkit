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

**R1-A narrows rule (b) to `DETACHED_ORPHAN_IMAGES`**, a named allowlist of
images a session's own tool calls plausibly start (interpreters, shells,
`git`/`cargo`/`rustc`, the hub debug build) -- a live Stop on 2026-09-16 15:05
attributed two `DiscordSystemHelper.exe` orphans to this session, whose
short-lived relaunch launcher happened to die inside this call's window, which
is exactly the risk above but for an image nobody's tool calls ever start.
Rules (a) and (c) are unchanged: a child reachable through this session's own
live tree is admitted whatever its name, because that chain already proves
the session's own ancestry, not an image guess. Not observed: an unlisted
detached dev tool is still missed, the same as any other orphan rule (b) was
never going to attribute.

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
`py`/`python` and every wrapping shell from the ledger, live A/B confirmed. A
second version matched the *unexpanded* `$CLAUDE_PROJECT_DIR/.claude/hooks/...`
fragment plus its two expanded slash-style spellings -- still a substring
search, and calling that matcher directly against the three spellings (a
function-level check, not a live process tree) found it still hid all three whenever `CLAUDE_PROJECT_DIR` happened to be
in forward-slash form, because the fragment itself is a substring of a mention
that never invokes anything.

The structural replacement parses each hop's command line the same way the OS
itself split it -- `shell32.CommandLineToArgvW` via `ctypes` -- and asks a
narrower, shape-specific question instead of a substring search:

  - A shell hop (`bash.exe`/`sh.exe`): its `-c` argument, once parsed, equals
    one of the `command` strings configured in `.claude/settings.json` or
    `.claude/settings.local.json`, exactly.
  - A `py`/`python` hop (`py.exe`, or `python[0-9.]*w?.exe`): its first
    non-flag argument -- after `py.exe`'s own optional version selector such
    as `-3` -- is, once normalised (quotes stripped, backslashes turned to
    forward slashes, `posixpath.normpath`, lower case), one of the script
    paths those same `command` strings invoke. `-c`, `-m`, or any other
    leading interpreter flag is deliberately never a match: an unusual flag
    makes the hook over-report a real leftover, the safe direction, rather
    than hide one.

Both live-measured facts this depends on: both bash hops' `-c` argument is the
configured `command` string verbatim (checked directly against
`CommandLineToArgvW`'s own parse), and a `py`/`python` descendant's own command
line shows the fully expanded path with forward slashes, spelling
`CLAUDE_PROJECT_DIR` however the shell that substituted it happened to -- never
assumed, always normalised before comparing.

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
test process), and the exit code is the authoritative answer. Toolhelp cannot
be made to list an exited PID on demand, so this gate is proven at unit level
instead, in `TestLeftoverProcessesStaleToolhelp`: a fabricated ledger entry
plus a stubbed `snapshot()`/`_command_line` that still "sees" a since-exited
PID, with `_is_still_active` stubbed both ways. The positive case reports it;
the negative case, with the gate telling the truth, does not. The mutant this
catches: replacing `cmd_stop`'s gate with an unconditional pass turns the
paired test's failure into a silent success.

Separately, rule (b) (orphan admission) is narrowed to
`DETACHED_ORPHAN_IMAGES`, a named allowlist of images a session's own tool
calls plausibly start (R1-A, after a live Stop on 2026-09-16 15:05 attributed
two `DiscordSystemHelper.exe` orphans to this session -- see
`_is_orphan_admissible`'s docstring). **Not observed:** a detached dev tool
outside that list -- an unusual build helper, say -- is still missed by rule
(b), silently, the same as any other process rule (b) was never going to
attribute in the first place.

## Fail-open, and what a session cannot see

Both of the following go through `systemMessage` on stdout, printed once by
`stop` for whatever this Stop noticed, alongside the same text on stderr.
Stderr from a hook that exits 0 goes to Claude Code's debug log only, never
the transcript (confirmed against
[the hooks docs](https://code.claude.com/docs/en/hooks), 2026-09-16) -- so a
plain stderr note is invisible on every path that does not also report a
leftover, which is most of them, including the previous version of both notes
below.

  - **No configured hook commands found** (an unreadable or oddly shaped
    `.claude/settings.json`/`settings.local.json`): the structural matcher
    (`_is_hook_invocation`) then cannot recognise *any* sibling hook chain, so
    leftovers may be over-reported. `_configured_hooks` never raises on a
    malformed shape -- it skips what it cannot parse and keeps going -- so
    this is a warning, not a crash. Shown **once per session**, not on every
    reply while the configuration stays broken, tracked in its own
    `hookwarn-reported.json` next to `reported.json`.
  - **No `claude.exe` ancestor found**, at `post` or at `stop`. `stop` says so
    directly, every time its own lookup fails. A `post` call that could not
    find its root records nothing but leaves a `noroot-<tool_use_id>.json`
    marker; a later `stop` whose own lookup *does* succeed counts those
    markers and reports the total once per newly blind call, in
    `noroot-reported.json` -- the same "report once, not every reply" shape
    `reported.json` already uses for a leftover process.

## Two environment variables

  - `HSTK_PROC_LEDGER_DIR`: where the ledger lives. Defaults to
    `<tempfile.gettempdir()>/hstk-leftover-processes`. Deliberately never
    inside the repository -- `decompiled_output.py` scans every untracked
    file, and a ledger in the worktree would show up in `git status` on every
    tool call.
  - `HSTK_PROC_SESSION_ROOT_PID`: use this PID as the session root instead of
    searching for the nearest `claude.exe` ancestor. Exists for tests. If no
    `claude.exe` ancestor can be found and this is unset, `post` admits
    nothing and `stop` says so visibly (see "Fail-open" above) rather than
    staying silently blind.

Never kills anything: no Win32 call that ends a process, no signal sent from
Python, no `taskkill`/`Stop-Process`, and it never spawns a child process of
its own. It reports; the reply (or
the human) decides what to do about it.
"""

import ctypes
import functools
import json
import os
import posixpath
import re
import shlex
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
shell32 = ctypes.WinDLL("shell32", use_last_error=True) if sys.platform == "win32" else None

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_COMMAND_LINE_INFORMATION = 60
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
STILL_ACTIVE = 259

_CLAUDE_DIR = Path(__file__).resolve().parent.parent

if shell32 is not None:
    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    # HANDLE-returning calls need a pointer-width restype: the c_int default
    # truncates INVALID_HANDLE_VALUE to -1, which never equals the constant
    # above, so a failed snapshot would slip past its guard.
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]


def _argv(cmdline):
    """Parse a command line into argv the way Win32 itself does, via
    `shell32.CommandLineToArgvW` -- the same parser every process on this
    system was launched through, so it agrees with how the OS itself split
    quoting and escaping, rather than a hand-rolled approximation of it."""
    if not cmdline:
        return []
    count = ctypes.c_int(0)
    raw = shell32.CommandLineToArgvW(cmdline, ctypes.byref(count))
    if not raw:
        return []
    try:
        return [raw[i] for i in range(count.value)]
    finally:
        kernel32.LocalFree(raw)


def _normalize_script_path(value):
    """Fold quoting and slash-style differences out of a script path so a
    fragment read from `settings.json` (which may carry `$CLAUDE_PROJECT_DIR`
    with forward slashes) compares equal to what a live `py`/`python` hop's
    own command line shows once its shell has substituted and, on Windows,
    mixed slash styles into it (fact 2 of the round-0 research)."""
    if value is None:
        return None
    value = value.strip().strip('"').strip("'")
    value = value.replace("\\", "/")
    return posixpath.normpath(value).lower()


def _configured_hooks(claude_dir, project_dirs):
    """Every hook `command` string, and every script path it invokes,
    configured in `<claude_dir>/settings.json` and `settings.local.json`
    (both optional). Never raises -- an unreadable or oddly shaped settings
    file yields two empty sets rather than crashing `stop`, per F3."""
    commands = set()
    scripts = set()
    for name in ("settings.json", "settings.local.json"):
        try:
            settings = json.loads((claude_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(settings, dict):
            continue
        hooks = settings.get("hooks")
        if not isinstance(hooks, dict):
            continue
        for groups in hooks.values():
            if not isinstance(groups, list):
                continue
            for group in groups:
                if not isinstance(group, dict):
                    continue
                entries = group.get("hooks")
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    command = entry.get("command")
                    if not isinstance(command, str):
                        continue
                    command = command.strip()
                    if not command:
                        continue
                    commands.add(command)
                    try:
                        tokens = shlex.split(command)
                    except ValueError:
                        continue
                    for token in tokens:
                        if not token.endswith(".py"):
                            continue
                        for project_dir in project_dirs:
                            if token.startswith("$CLAUDE_PROJECT_DIR"):
                                resolved = project_dir + token[len("$CLAUDE_PROJECT_DIR"):]
                            elif token.startswith("${CLAUDE_PROJECT_DIR}"):
                                resolved = project_dir + token[len("${CLAUDE_PROJECT_DIR}"):]
                            elif re.match(r"^[A-Za-z]:[\\/]", token) or token.startswith(("/", "\\")):
                                resolved = token
                            else:
                                resolved = project_dir.rstrip("\\/") + "/" + token
                            scripts.add(_normalize_script_path(resolved))
                            if re.match(r"^[A-Za-z]:[\\/]", token) or token.startswith(("/", "\\")):
                                break  # absolute -- project_dirs are irrelevant, do not repeat
    return frozenset(commands), frozenset(scripts)


@functools.lru_cache(maxsize=1)
def _hooks():
    """`(commands, scripts)` configured for this repository's own session,
    cached for the life of this process. `project_dirs` includes both the
    live `CLAUDE_PROJECT_DIR` (its spelling is not guaranteed -- see fact 2)
    and this file's own resolved repository root, so a script token resolves
    the same way regardless of which one a hop's shell actually substituted."""
    project_dirs = []
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir:
        project_dirs.append(env_dir)
    project_dirs.append(str(Path(__file__).resolve().parents[2]))
    return _configured_hooks(_CLAUDE_DIR, project_dirs)


_PY_VERSION_SELECTOR_RE = re.compile(r"^-\d[\d.\-]*$")
_PYTHON_IMAGE_RE = re.compile(r"^python[0-9.]*w?\.exe$")


def _is_python_interpreter_image(lowered_image):
    """True for every Python interpreter image name a py/python hop's own
    command line can show: `py.exe`/`pyw.exe` (the Python launcher, with or
    without its windowed variant) or `python[0-9.]*w?.exe`
    (`python.exe`/`python3.exe`/`python3.14.exe`/`pythonw.exe`, ...). One
    helper, shared by both call sites that need "is this a Python hop at
    all": `_is_hook_invocation` below (which additionally strips a
    `py.exe`/`pyw.exe` launcher's own version selector before matching a
    hook's configured script path) and R2-1's rule (b) orphan allowlist
    (`_is_orphan_admissible`), which used to carry a second, narrower copy of
    this same regex that only recognised the literal names
    `python.exe`/`pythonw.exe` and missed every versioned interpreter
    (`python3.exe`) a real detached build could use."""
    return lowered_image in ("py.exe", "pyw.exe") or bool(_PYTHON_IMAGE_RE.match(lowered_image))


def _is_hook_invocation(image, cmdline, commands, scripts):
    """True only when this hop is *actually running* a configured hook --
    never merely mentioning one. Two shapes, both measured live:

      - A shell hop (`bash.exe`/`sh.exe`): its `-c` argument, parsed the same
        way the shell itself will parse it, equals a configured `command`
        string exactly.
      - A `py`/`python` hop: its first non-flag argument (after
        `py.exe`/`pyw.exe`'s own optional version selector, e.g. `-3` -- the
        two Python launchers, not every interpreter image) is, once
        normalised, one of the configured script paths.

    Any other shape -- including `-c`, `-m`, or any other leading option on a
    py/python hop -- returns False. That is deliberately strict: an unusual
    interpreter flag makes the hook over-report a real leftover, which is the
    safe direction, rather than hide one the way the substring matcher did.
    """
    if not cmdline:
        return False
    argv = _argv(cmdline)
    if not argv:
        return False
    lowered_image = image.lower() if image else ""

    if lowered_image in ("bash.exe", "sh.exe"):
        for i in range(1, len(argv)):
            if argv[i] == "-c" and i + 1 < len(argv):
                return argv[i + 1].strip() in commands
        return False

    if _is_python_interpreter_image(lowered_image):
        i = 1
        if (
            lowered_image in ("py.exe", "pyw.exe")
            and len(argv) > 1
            and _PY_VERSION_SELECTOR_RE.match(argv[1])
        ):
            i = 2
        if i >= len(argv):
            return False
        candidate = argv[i]
        if candidate.startswith("-"):
            return False
        return _normalize_script_path(candidate) in scripts

    return False


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
    if not snap or snap == INVALID_HANDLE_VALUE:
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


def _creation_time_from_handle(handle):
    """FILETIME (as a 64-bit int) the process behind `handle` was created, or
    None if unreadable. Factored out of `_creation_time` so `_process_identity`
    can read it through a handle it already owns, rather than opening a
    second one."""
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
        return _creation_time_from_handle(handle)
    finally:
        kernel32.CloseHandle(handle)


def _command_line_from_handle(handle):
    """Best-effort full command line via NtQueryInformationProcess, read
    through `handle`. None on failure. Factored out of `_command_line` so
    `_process_identity` can read it through a handle it already owns, rather
    than opening a second one."""
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


def _command_line(pid):
    """Best-effort full command line via NtQueryInformationProcess. None on failure."""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        return _command_line_from_handle(handle)
    finally:
        kernel32.CloseHandle(handle)


def _process_identity(pid):
    """(creation, cmdline) for `pid`, both read through the *same* open
    `OpenProcess` handle -- the one direct `OpenProcess` call in this
    function's own body.

    An open handle keeps the underlying process object, and so this PID,
    from being reused until the handle is closed. That is why one handle
    closes both races `_creation_time`/`_command_line` were separately
    exposed to: a PID recycled by an unrelated process between two separate
    `OpenProcess` calls, and a process that exits between them. `(None, None)`
    when the handle itself could not be opened -- another user's process, a
    protected one, or a PID nothing occupies any more. After the process has
    exited (but before the handle is closed), `GetProcessTimes` still
    succeeds; the command-line query may legitimately return `None`, and
    callers that need to trust the line still compare the returned creation
    time against their own expectation (`_capture_new` does this)."""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None, None
    try:
        return _creation_time_from_handle(handle), _command_line_from_handle(handle)
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


def _read_count_marker(path):
    """R1-B item 4: `noroot-reported.json`'s `{"count": N}` shape, or `0` for
    anything else -- missing, unreadable, not a dict, or a `count` that is not
    an int. `noroot_count > noroot_reported` (in `cmd_stop`) would otherwise
    raise on a corrupt marker (`.get` on a non-dict, or comparing an int
    against a non-int), turning a broken marker file into a crashed `stop`
    instead of one more thing this hook fails open on."""
    data = _read_json(path, {})
    if not isinstance(data, dict):
        return 0
    count = data.get("count", 0)
    return count if isinstance(count, int) and not isinstance(count, bool) else 0


def _read_reported_marker(path):
    """R1-B item 4: `reported.json`'s `{pid: creation}` shape, tolerating a
    corrupt file (not a dict) or a corrupt entry (a key or value that will not
    coerce to `int`) the same way -- skip what cannot be trusted rather than
    raising, so a hand-edited or truncated marker degrades to "nothing was
    reported before", not a crashed `stop`. R2-2: `int()` on a JSON `Infinity`
    (valid JSON to Python's own parser, and easy to produce by hand-editing)
    raises `OverflowError`, not `ValueError` -- `{"1": Infinity}` used to crash
    this before that was also caught."""
    data = _read_json(path, {})
    if not isinstance(data, dict):
        return {}
    reported = {}
    for pid, creation in data.items():
        try:
            reported[int(pid)] = int(creation)
        except (TypeError, ValueError, OverflowError):
            continue
    return reported


def _load_snapshot_file(path):
    """Load a ledger file (`post-*.json`): a flat `{pid: entry}` map. R2-2: a
    hand-edited or truncated file can be the wrong shape throughout -- a
    top-level list instead of a `{pid: entry}` map, or an entry that is not
    itself a dict, or a `creation` that is missing or will not coerce to
    `int` -- so each layer is checked and the offending pid is skipped rather
    than letting `.items()`/`int()`/a later `entry["creation"]` read raise."""
    data = _read_json(path, {})
    if not isinstance(data, dict):
        return {}
    result = {}
    for pid, entry in data.items():
        if not isinstance(entry, dict):
            continue
        creation = entry.get("creation")
        if not isinstance(creation, int) or isinstance(creation, bool):
            continue
        try:
            result[int(pid)] = entry
        except (TypeError, ValueError):
            continue
    return result


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
    the machine look new since `pre` (see `cmd_post`).

    R2-2: `procs` itself not being a dict (a top-level list, say) is treated
    the same as a missing file -- `None`, no usable baseline -- since there is
    no way to tell which entries were meant. An individual entry within an
    otherwise-good `procs` dict that is not itself a dict, or is missing a
    valid `ppid`/`creation`, is instead just skipped: every downstream
    chain-walk (`_valid_parent`, `_locate_root_and_chain`, ...) reads
    `proc["ppid"]`/`proc["creation"]` by direct indexing, so a half-shaped
    entry would otherwise raise deep inside one of those instead of simply
    being treated as absent from the baseline.

    An entry missing a valid int `pid` is skipped the same way -- `cmd_post`'s
    `pre_keys` comprehension and `_parent_in_ledger`'s `pre_snap` scan both
    read `p["pid"]` by direct indexing over every value this function returns,
    so a hand-edited entry with no `pid` field would otherwise raise a
    `KeyError` deep inside one of those instead of being treated as absent.
    The `raw_pids` loop also catches `OverflowError` alongside
    `TypeError`/`ValueError`: `int(float("inf"))` (a hand-edited `Infinity`,
    valid JSON to Python's own parser) raises `OverflowError`, not
    `ValueError`.
    """
    data = _read_json(path, None)
    if not isinstance(data, dict) or "procs" not in data:
        return None
    raw_procs = data.get("procs")
    if not isinstance(raw_procs, dict):
        return None
    procs = {}
    for pid, entry in raw_procs.items():
        if not isinstance(entry, dict):
            continue
        proc_pid = entry.get("pid")
        ppid = entry.get("ppid")
        creation = entry.get("creation")
        if not isinstance(proc_pid, int) or isinstance(proc_pid, bool):
            continue
        if not isinstance(ppid, int) or isinstance(ppid, bool):
            continue
        if not isinstance(creation, int) or isinstance(creation, bool):
            continue
        try:
            procs[int(pid)] = entry
        except (TypeError, ValueError):
            continue
    raw_pids_field = data.get("raw_pids", [])
    if not isinstance(raw_pids_field, list):
        raw_pids_field = []
    raw_pids = set()
    for raw_pid in raw_pids_field:
        try:
            raw_pids.add(int(raw_pid))
        except (TypeError, ValueError, OverflowError):
            continue
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


def _is_hook_chain(pid, snap, root, cmdlines=None):
    """True when `pid`, or an ancestor strictly between it and `root`, is
    itself running one of this repo's `.claude/hooks/*` scripts.

    A concurrent sibling `PostToolUse` hook spawns its own new
    `bash -> bash -> py -> python .claude/hooks/*.py` chain during this
    call's window, which reaches `root` through processes that are otherwise
    indistinguishable from a real leftover under rules (a)/(b)/(c) -- a live
    Stop on 2026-09-16 10:51 reported eleven of them this way. This is checked
    against every admission rule, not just (a): rule (b)'s orphan test and
    rule (c)'s ledger-parent test do not themselves look at command lines.

    `cmdlines` (F2) is a command line captured earlier in the same `post`
    call, before a sibling's short-lived hops could exit -- used in place of
    a fresh `_command_line(pid)` read when available, since that read can
    return `None` for a process that has since died.

    Membership in `cmdlines` is authoritative even when the stored value is
    `None`: `_capture_new` now gives every new pid a key, and `None` there
    means "captured, and not trustworthy or not readable" -- re-reading it
    here would be exactly the PID-reuse race `_capture_new` already resolved
    against. A pid that is *not* in `cmdlines` was never captured by
    `_capture_new` at all (an ancestor that predates the call, or any hop at
    Stop, since `_extend_ledger_with_live_descendants` passes no `cmdlines`)
    -- that fallback `_command_line(cur)` read is still a bare, creation-time-
    unaware read; see the README's Known Limitations.
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
        line = cmdlines[cur] if cmdlines is not None and cur in cmdlines else _command_line(cur)
        if _is_hook_invocation(proc["image"], line, *_hooks()):
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


# R2-1: every Python interpreter name is matched by `_is_python_interpreter_image`
# instead of being listed here literally -- `python.exe`/`py.exe`/`pythonw.exe`
# used to be the only three admitted, which missed a versioned interpreter
# (`python3.exe`, `python3.14.exe`) or the windowed launcher (`pyw.exe`), all of
# which the hook-invocation matcher above already treats as "a Python hop".
# Everything else a session's own tool calls plausibly start still lives here.
DETACHED_ORPHAN_IMAGES = frozenset(
    {
        "node.exe",
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "bash.exe",
        "sh.exe",
        "sleep.exe",
        "git.exe",
        "cargo.exe",
        "rustc.exe",
        "hub.exe",
    }
)


def _is_orphan_admissible(proc, post_snap, pre_snap, post_raw_pids, pre_raw_pids):
    """Rule (b): a parent born and killed inside this call's own window.

    R1-A narrows this to a named allowlist of images a session's own tool
    calls plausibly start (`DETACHED_ORPHAN_IMAGES`) -- a live Stop on
    2026-09-16 15:05 attributed two `DiscordSystemHelper.exe` orphans to this
    session: Discord had (re)started, its own short-lived relaunch helper
    happened to die inside this call's window, and rule (b)'s timing test
    alone cannot tell that apart from a real leftover. This does not remove
    the risk rule (b) always carried (see the module docstring); it only
    bounds it to processes a session is actually expected to start. Rules (a)
    and (c) are unchanged -- a child already reachable through this session's
    own live tree is still admitted whatever its name. Not observed: a
    detached dev tool outside this list (an unusual build helper, say) is
    still missed by rule (b), silently, the same as any other orphan rule (b)
    was never going to attribute.

    R2-1: the image check accepts `DETACHED_ORPHAN_IMAGES` **or** anything
    `_is_python_interpreter_image` recognises, so a versioned or windowed
    Python interpreter (`python3.exe`, `python3.14.exe`, `pyw.exe`) is
    admitted the same way `python.exe` always was, through the one shared
    pattern the hook-invocation matcher already uses -- not a second,
    narrower copy of it that only knew the literal names.

    `post_raw_pids`/`pre_raw_pids` are the unfiltered Toolhelp32 PID sets from
    `snapshot()`, not the openable `post_snap`/`pre_snap` maps: a PPID this
    hook could not open (a SYSTEM service, a protected process) is a live
    parent, not a missing one, and `post_snap`/`pre_snap` cannot tell the two
    apart -- `dllhost.exe`/`audiodg.exe` under an unopenable `svchost.exe`
    looked exactly like orphans until this distinction was added.
    """
    image = (proc.get("image") or "").lower()
    if image not in DETACHED_ORPHAN_IMAGES and not _is_python_interpreter_image(image):
        return False
    parent_pid = proc["ppid"]
    parent = post_snap.get(parent_pid)
    if parent is not None:
        if _valid_parent(proc, parent):
            return False  # a live, valid parent -- not an orphan at all
        # Openable, but its creation postdates the child: the original PPID
        # died and this PID has already been reused by something else. Ask the
        # raw set, as below: an unopenable parent at `pre` is absent from
        # `pre_snap` but still existed.
        return parent_pid not in pre_raw_pids
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


def _capture_new(new_procs):
    """(alive, cmdlines) for every pid in `new_procs`. F2: called immediately
    after the diff against `pre`, before `_load_ledger` or any admission-rule
    walk -- both of which can take long enough (hundreds of ledger files)
    that a short-lived sibling hook hop has already exited by the time its
    command line would otherwise be read, which is what made every one of
    that sibling's hops (and its `git` grandchildren) look like an ordinary
    leftover instead of a hook chain.

    `cmdlines` keeps a pid's line whenever it could be read at all, live or
    already exited by the time `_is_still_active` ran a moment later -- a
    short-lived intermediate hop (the outer `bash.exe` hop of a sibling hook
    chain, say) is exactly the case F2 exists for, and it is usually dead
    before this call even gets to check it, so restricting `cmdlines` to
    `alive` pids would drop the one line `_is_hook_chain` needs most. `alive`
    is unaffected -- it still reflects only whether the pid is a live
    admission *candidate*, which is orthogonal to whether its line was
    readable.

    R2-4: a pid can be recycled in the moment between `snapshot()`'s post read
    (which supplied `new_procs[pid]["creation"]`) and this function's own
    identity read a little later -- if some unrelated process has already
    taken that PID, its command line would otherwise be captured and handed
    to `_is_hook_chain`/the leftover report under the *old* process's
    identity. `_process_identity(pid)` reads the creation time and the
    command line through the *same* handle, so neither a PID reuse nor the
    process exiting in between can split the two apart the way two separate
    `_command_line`/`_creation_time` calls could. The reported creation is
    compared against `new_procs[pid]["creation"]`; the line is kept only on a
    match, and `cmdlines` gets a key -- `None` on a mismatch or an unreadable
    line -- for *every* pid in `new_procs`, not only the ones that matched.
    That key is what lets `_is_hook_chain` treat "captured, untrustworthy" as
    final instead of falling through to a second, unprotected read. `alive`
    is unaffected by any of this -- a recycled pid is still a real, live
    process and stays a legitimate admission candidate, it simply is not the
    same identity whose command line was captured."""
    alive = set()
    cmdlines = {}
    for pid in new_procs:
        creation, line = _process_identity(pid)
        cmdlines[pid] = line if creation == new_procs[pid]["creation"] else None
        if _is_still_active(pid):
            alive.add(pid)
    return alive, cmdlines


def _admit_new(
    new_procs, post_snap, pre_snap, post_raw_pids, pre_raw_pids, root, hook_chain, ledger,
    cmdlines, alive,
):
    """`alive` restricts which pids are *considered* for admission -- a pid
    that was already dead at `post` cannot be a ledger parent of anything, so
    dropping it here loses no attribution (see F2 in the hook's docstring).
    `new_procs` itself stays unfiltered for `_chain_reaches_root`: rule (a)
    asks whether every ancestor is new, and an intermediate shell that died
    before `_capture_new` checked it is still new relative to `pre`."""
    admitted = {}
    for pid in alive:
        proc = new_procs[pid]
        if pid in hook_chain:
            continue
        if proc["image"].lower() == "conhost.exe":
            continue
        if _is_hook_chain(pid, post_snap, root, cmdlines):
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
    if not procs:
        # An empty snapshot is a failed read, never a real machine state (this
        # hook's own process is always in it). Written as a baseline it would
        # make every live process look new at `post`; leaving no file sends
        # `cmd_post` down its "no usable baseline" path instead.
        return 0
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
    pre_keys = {(p["pid"], p["creation"]) for p in pre_snap.values()}
    new_procs = {
        pid: p for pid, p in post_snap.items() if (pid, p["creation"]) not in pre_keys
    }
    # F2: capture each new pid's command line and liveness immediately, before
    # `_locate_root_and_chain`/`_load_ledger` (which can take long enough,
    # across hundreds of ledger files, that a short-lived sibling hook hop
    # has already exited by the time it would otherwise be read).
    alive, cmdlines = _capture_new(new_procs)

    root, hook_chain = _locate_root_and_chain(os.getpid(), post_snap)
    if root is None:
        pre_path.unlink(missing_ok=True)
        # F4: one marker file per blind call, so `stop` can count and report
        # them once, the same race-free per-file pattern as `post-*.json`.
        _write_json(sdir / f"noroot-{tool_use_id}.json", {})
        return 0

    ledger = _load_ledger(sdir)
    admitted = _admit_new(
        new_procs, post_snap, pre_snap, post_raw_pids, pre_raw_pids, root, hook_chain, ledger,
        cmdlines, alive,
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


def _emit_notes(notes):
    """F3/F4's only visible channel. Stderr from a hook that exits 0 goes to
    the debug log only, never the transcript (confirmed against the hooks
    docs, 2026-09-16) -- so a plain stderr note is invisible whenever nothing
    else makes this `stop` exit 2. `systemMessage` on stdout is what the docs
    say is shown to the user, and Stop is not one of the events that discard
    it. Each note is still also written to stderr, since that channel is what
    an exit-2 leftover report already reads, and the user asked for it kept.
    Nothing is printed when there are no notes -- an ordinary tracked call
    with nothing to say stays as silent as it always was."""
    if not notes:
        return
    for note in notes:
        sys.stderr.write(note + "\n")
    print(json.dumps({"systemMessage": " | ".join(notes)}))


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

    notes = []

    # F3: `_hooks()` found no configured hook commands at all (an unreadable
    # or oddly shaped settings.json) -- the structural matcher above then
    # cannot recognise any sibling hook chain, so leftovers may be
    # over-reported. Fails open (never crashes) and says so once per session,
    # not on every reply while the configuration stays broken, tracked in its
    # own marker file next to `reported.json`.
    commands, _scripts = _hooks()
    if not commands:
        hookwarn_path = sdir / "hookwarn-reported.json"
        if not hookwarn_path.exists():
            notes.append(
                "leftover_processes: no hook commands found in .claude/settings.json "
                "or .claude/settings.local.json; sibling hook processes may be "
                "over-reported"
            )
            _write_json(hookwarn_path, {"warned": True})

    live_snap, _live_raw_pids = snapshot()
    root, _chain = _locate_root_and_chain(os.getpid(), live_snap)
    if root is None:
        notes.append(
            "leftover_processes: no claude.exe ancestor at Stop; not tracking this session"
        )
        _emit_notes(notes)
        return 0

    # F4: every `post` call this session that could not find its own root
    # left a `noroot-*.json` marker instead of tracking anything. Report the
    # count once per newly blind call, not once per reply, the same way
    # `reported.json` already does for a leftover process.
    noroot_reported_path = sdir / "noroot-reported.json"
    noroot_count = len(
        [p for p in sdir.glob("noroot-*.json") if p.name != noroot_reported_path.name]
    )
    noroot_reported = _read_count_marker(noroot_reported_path)
    if noroot_count > noroot_reported:
        notes.append(
            f"leftover_processes: {noroot_count} PostToolUse call(s) found no "
            "claude.exe ancestor and recorded nothing"
        )
        _write_json(noroot_reported_path, {"count": noroot_count})

    ledger = _load_ledger(sdir)
    extended = _extend_ledger_with_live_descendants(ledger, live_snap, root)
    if extended:
        seq = len(list(sdir.glob("post-stop-*.json")))
        _write_json(sdir / f"post-stop-{seq}.json", extended)
        ledger.update(extended)

    reported_path = sdir / "reported.json"
    reported = _read_reported_marker(reported_path)

    leftovers = {}
    for pid, entry in ledger.items():
        # R2-2: `_load_snapshot_file` already drops a non-dict entry or one
        # missing a valid `creation`, but a ledger can also be built up
        # in-process (`_extend_ledger_with_live_descendants`) -- so this is
        # checked again at the point of use rather than trusted from upstream.
        if not isinstance(entry, dict):
            continue
        creation = entry.get("creation")
        if not isinstance(creation, int) or isinstance(creation, bool):
            continue
        live = live_snap.get(pid)
        if live is None or live["creation"] != creation:
            continue
        if not _is_still_active(pid):
            continue
        if reported.get(pid) == creation:
            continue
        leftovers[pid] = live

    if not leftovers:
        _emit_notes(notes)
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
    _emit_notes(notes)
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
