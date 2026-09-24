"""One machine-wide game lease, so two sessions never drive one install at once.

Each worktree has its own `.claude/workorders/`, so nothing a checkout keeps can
tell one Claude session that another is already driving the one Hero Siege
install on this machine. This module keeps that fact where `saves.py` and
`capture.py` already keep their machine-wide state -- under
`%LOCALAPPDATA%\\HSDriveMcp\\` -- as one record, `lease.json`, plus an empty
`lease.lock` that exists only to be locked.

**Two different things hold two different lifetimes.** The *lease* lives in the
record, from `acquire` to `release`, across as many tool calls and hours as a
live session takes. The *OS lock* on `lease.lock` is held only for the
milliseconds of one read-modify-write, so that acquire-vs-acquire,
acquire-vs-force and a holder's own update-vs-force are each atomic. It is a
kernel lock (`msvcrt.locking` on Windows, `fcntl.flock` elsewhere), released
when the handle closes, so a crashed server can never leave it held and
nothing here ever has to "break" a lock.

**A crashed holder is detected by process identity, not by age.** A `held`
record names its holder as `(pid, pid_start)`: the PID and the moment that
process was created. The holder is alive only if a process with that PID
exists, has not exited, and was created at that same moment -- so a PID the
system has since handed to something else reads as gone. A stale record is
recovered by the next `acquire`, which summarises it under `previous`.

**"Held by me" is an in-memory fact.** `acquire` generates a random `lease_id`
and this process remembers it; a record carrying that id is this server's,
whatever PID it names. A record carrying another id is somebody else's, even
when a test (or a reused PID) makes the PIDs agree.

**A record that cannot be read never reads as free.** `guard` refuses
`lease_unavailable` for a present but unparseable `lease.json` -- `AGENTS.md`
§ "Check a Permission Where It Is Used", a sentinel meaning *unknown* must not
compare equal to a real value -- and `acquire(force=True)` is the way out.

**Windows: `os.replace` fails against an open reader.** Measured 2026-09-24:
replacing `lease.json` raises `PermissionError` (winerror 5) while another
process has it open for reading, and succeeds once that handle closes. So
readers read and close in one call (`Path.read_bytes`) and writers retry the
replace within the same bound as the lock loop before answering
`lease_unavailable`.

The lease is advisory between hs-drive processes. Anything that reaches the
game another way -- `ForgePact/tools/ipc.ps1`, the ForgePact panel, a person at
the keyboard -- does not ask it. Nothing here deletes a file, and nothing here
writes to stdout: diagnostics go to the `hs_drive` logger, which `server.py`
points at stderr.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import launcher_bridge, results, saves

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes
else:
    import fcntl

log = logging.getLogger("hs_drive")

SCHEMA = "hs-drive-lease/1"
RECORD_NAME = "lease.json"
LOCK_NAME = "lease.lock"
TEMP_SUFFIX = ".hsdrive-tmp"

#: The lock is taken non-blocking in a bounded loop; past the bound the answer
#: is `lease_unavailable`, never a wait with no end. The same bound applies to
#: the `os.replace` retry and to a read that meets a writer mid-replace.
LOCK_TIMEOUT_S = 5.0
LOCK_STEP_S = 0.025

#: Record states.
HELD = "held"
RELEASED = "released"

#: `hs_lease_status` states. It never refuses; `unavailable` is a state.
FREE = "free"
HELD_BY_ME = "held_by_me"
STALE = "stale"
UNAVAILABLE = "unavailable"

#: `previous.outcome`: how the record before this one ended.
OUTCOME_STALE = "stale"
OUTCOME_TAKEN_OVER = "taken_over"
OUTCOME_RELEASED = "released"

#: A label names a session in someone else's refusal, so it is kept short and
#: plain. `<slug>-live-<n>` fits.
LABEL_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")

DLL_NAME = "BloodPactPlugin.dll"

#: `OpenProcess` access right that is enough for `GetExitCodeProcess` and
#: `GetProcessTimes`, and is granted for any process of the same user.
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259

#: The `lease_id` this process took, or None. Module level on purpose: "held by
#: me" is this server process's own memory, and a record on disk can only
#: agree with it, never establish it.
_HELD_ID: str | None = None

#: `process_identity()`, computed once per process.
_IDENTITY: dict[str, Any] | None = None


class _Busy(Exception):
    """The lock or the replace did not succeed within `LOCK_TIMEOUT_S`."""


# --------------------------------------------------------------------------
# Locations. `HS_DRIVE_LEASE_DIR` exists so no test touches the real one.
# --------------------------------------------------------------------------

def lease_dir() -> Path:
    """`HS_DRIVE_LEASE_DIR` when set, else `%LOCALAPPDATA%\\HSDriveMcp`.

    The override is for test isolation. Set per worktree, it would give each
    session a lease of its own and defeat the point of having one.
    """
    override = os.environ.get("HS_DRIVE_LEASE_DIR")
    if override:
        return Path(override)
    return launcher_bridge.local_app_data() / "HSDriveMcp"


def record_path() -> Path:
    return lease_dir() / RECORD_NAME


def _lock_path() -> Path:
    return lease_dir() / LOCK_NAME


# --------------------------------------------------------------------------
# Process identity
# --------------------------------------------------------------------------

def _windows_start(pid: int) -> int | None:
    """The process's creation `FILETIME` as one integer, or None when no live
    process has this PID.

    A handle alone is not proof of life -- measured: a child killed by its
    parent still opened, because the parent's `Popen` handle keeps the process
    object, and reported exit code 1 -- so the exit code is read too.
    """
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.restype = wintypes.HANDLE
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    api.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        if not api.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None
        if code.value != STILL_ACTIVE:
            return None
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not api.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                   ctypes.byref(kernel), ctypes.byref(user)):
            return None
        return (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
    finally:
        api.CloseHandle(handle)


def _linux_start(pid: int) -> str | None:
    """`<boot_id>:<starttime>`, or None when no live process has this PID.

    `starttime` is `/proc/<pid>/stat` field 22, in clock ticks since boot, so
    the boot id goes with it: after a reboot the same tick count names a
    different process. A zombie (state `Z`) or a dead task (`X`) has exited.
    """
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass  # someone else's process, but it exists
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    # The command name (field 2) is in parentheses and may itself contain
    # spaces or parentheses; everything after the last `)` is fields 3 onward.
    fields = stat[stat.rindex(")") + 1:].split()
    if len(fields) < 20 or fields[0] in ("Z", "X", "x"):
        return None
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        boot = ""
    return f"{boot}:{fields[19]}"


def _has_start_time() -> bool:
    return os.name == "nt" or sys.platform.startswith("linux")


def process_start_for(pid: int) -> Any:
    """When process `pid` was created, or None when no live process has it.

    Windows: the creation `FILETIME`. Linux: boot id plus `starttime`. Any
    other platform has no reader here and answers None.
    """
    if os.name == "nt":
        return _windows_start(pid)
    if sys.platform.startswith("linux"):
        return _linux_start(pid)
    return None


def process_identity() -> dict[str, Any]:
    """This process: `{pid, pid_start, platform}`, computed once."""
    global _IDENTITY
    if _IDENTITY is None:
        pid = os.getpid()
        _IDENTITY = {"pid": pid, "pid_start": process_start_for(pid),
                     "platform": sys.platform}
    return dict(_IDENTITY)


def process_alive(identity: Any) -> bool:
    """True only when the process `identity` names is still that process.

    The PID must be live and its creation stamp must equal the recorded one,
    so a PID reused by another process reads as gone. Where there is no
    creation-stamp reader, `os.kill(pid, 0)` is all there is.
    """
    if not isinstance(identity, dict):
        return False
    try:
        pid = int(identity.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if not _has_start_time():
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True
    start = process_start_for(pid)
    return start is not None and start == identity.get("pid_start")


# --------------------------------------------------------------------------
# The record on disk
# --------------------------------------------------------------------------

def _now_utc() -> str:
    return saves._utc_stamp()[1]  # noqa: SLF001 - one timestamp format


def _valid(record: Any) -> bool:
    return (isinstance(record, dict)
            and record.get("schema") == SCHEMA
            and record.get("state") in (HELD, RELEASED)
            and isinstance(record.get("lease_id"), str)
            and isinstance(record.get("holder"), dict))


def _read_bytes(path: Path) -> bytes | None:
    """The whole file, opened and closed in one call, or None when absent.

    A reader that keeps `lease.json` open is what makes a writer's
    `os.replace` fail on Windows, so nothing here holds it. A read that meets
    a writer mid-replace is retried within the lock bound.
    """
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(LOCK_STEP_S)


def read_record(tool: str = "hs_lease_status") -> dict[str, Any] | None:
    """The parsed record; None when there is none; a `lease_unavailable`
    refusal when a file is there and cannot be read as one."""
    path = record_path()
    try:
        raw = _read_bytes(path)
    except OSError as exc:
        return results.refuse(
            tool, "lease_unavailable",
            f"The lease record {path} could not be read ({type(exc).__name__}: "
            f"{exc}), so whether another session holds the game is unknown. "
            "hs_lease_acquire(force=true) replaces it.",
            lease_path=str(path))
    if raw is None:
        return None
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        record, why = None, f"{type(exc).__name__}: {exc}"
    else:
        why = f"it is not an {SCHEMA} record"
    if record is None or not _valid(record):
        return results.refuse(
            tool, "lease_unavailable",
            f"The lease record {path} is present but unreadable ({why}), so "
            "whether another session holds the game is unknown and it is not "
            "treated as free. hs_lease_acquire(force=true) replaces it.",
            lease_path=str(path))
    return record


def _classify(record: dict[str, Any] | None) -> str:
    if record is None or record.get("state") == RELEASED:
        return FREE
    if _HELD_ID is not None and record.get("lease_id") == _HELD_ID:
        return HELD_BY_ME
    if process_alive(record.get("holder")):
        return HELD
    return STALE


@contextmanager
def _locked() -> Iterator[None]:
    """Hold the OS lock on `lease.lock` for one read-modify-write."""
    lock_path = _lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                # Both branches raise an OSError subclass when contended:
                # PermissionError (errno 13) from msvcrt, BlockingIOError
                # from flock.
                if time.monotonic() >= deadline:
                    raise _Busy(f"{lock_path} stayed locked for "
                                f"{LOCK_TIMEOUT_S} s") from None
                time.sleep(LOCK_STEP_S)
        try:
            yield
        finally:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass  # closing the handle below releases it regardless
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _write(record: dict[str, Any]) -> None:
    """Temp file beside the record, then `os.replace`, retried while a reader
    has the record open (the Windows hazard in the module docstring)."""
    path = record_path()
    staging = path.with_name(RECORD_NAME + TEMP_SUFFIX)
    staging.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            os.replace(staging, path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise _Busy(f"{path} could not be replaced for {LOCK_TIMEOUT_S} s; "
                            "another process kept it open") from None
            time.sleep(LOCK_STEP_S)


def _unavailable(tool: str, exc: BaseException) -> dict[str, Any]:
    return results.refuse(
        tool, "lease_unavailable",
        f"The lease at {lease_dir()} could not be updated "
        f"({type(exc).__name__}: {exc}). Nothing was changed.",
        lease_path=str(record_path()))


def _holder_detail(record: dict[str, Any]) -> str:
    holder = record.get("holder") or {}
    return (f"held by {record.get('label')} (pid {holder.get('pid')}) since "
            f"{record.get('taken_utc')}")


def _held_refusal(tool: str, record: dict[str, Any], what: str) -> dict[str, Any]:
    return results.refuse(
        tool, "lease_held",
        f"The game lease is {_holder_detail(record)}. {what} "
        "hs_lease_status shows the record; only the owner decides a takeover.",
        holder_label=record.get("label"),
        holder_pid=(record.get("holder") or {}).get("pid"),
        taken_utc=record.get("taken_utc"), lease_path=str(record_path()))


def _summary(record: dict[str, Any], outcome: str, at_utc: str) -> dict[str, Any]:
    return {"label": record.get("label"),
            "pid": (record.get("holder") or {}).get("pid"),
            "taken_utc": record.get("taken_utc"),
            "backup_id": record.get("backup_id"),
            "restore_pending": bool(record.get("restore_pending")),
            "outcome": outcome, "at_utc": at_utc}


def _dll_facts() -> tuple[str | None, str | None, str]:
    """`(path, sha256, status)` for the installed plugin, the same path
    `launcher_bridge.mod_chain()` checks. `status` is `hashed`, or why not."""
    exe = launcher_bridge.resolve_exe("hs_lease_acquire")
    if results.is_refusal(exe):
        return None, None, exe["reason"]
    dll = Path(exe).parent / "mods" / "aurie" / DLL_NAME
    if not dll.is_file():
        return str(dll), None, "dll_missing"
    try:
        return str(dll), saves.file_sha256(dll), "hashed"
    except OSError as exc:
        return str(dll), None, f"unreadable: {type(exc).__name__}: {exc}"


def _restore_warning(record: dict[str, Any]) -> str:
    return (f"{record.get('label')} backed up the saves as "
            f"{record.get('backup_id')} and no restore of that backup has been "
            "recorded, so the live saves may still carry that session's "
            "changes. Restore it with hs_saves_restore before relying on them.")


# --------------------------------------------------------------------------
# The three tools
# --------------------------------------------------------------------------

def status(tool: str = "hs_lease_status") -> dict[str, Any]:
    """Who holds the lease, read without the lock. Never refuses.

    `state` is `free` (no record, or a released one -- returned as `last`),
    `held`, `held_by_me`, `stale` or `unavailable`. The installed plugin is
    hashed again now, so a DLL swapped since the lease was taken shows as
    `dll_changed_since_taken`.
    """
    path = record_path()
    dll_path, dll_sha, dll_status = _dll_facts()
    fields: dict[str, Any] = {
        "lease_path": str(path), "dll_path_now": dll_path,
        "dll_sha256_now": dll_sha, "dll_status_now": dll_status,
        "dll_changed_since_taken": None, "record": None, "last": None,
    }
    record = read_record(tool)
    if results.is_refusal(record):
        return results.ok(tool, state=UNAVAILABLE, detail=record["detail"], **fields)
    state = _classify(record)
    if record is not None and dll_sha and record.get("dll_sha256"):
        fields["dll_changed_since_taken"] = dll_sha != record["dll_sha256"]
    if state == FREE:
        fields["last"] = record
        detail = "Nobody holds the game lease."
        if record is not None:
            detail += (f" The last holder, {record.get('label')}, released it at "
                       f"{record.get('released_utc')}.")
            if record.get("restore_pending"):
                fields["warning"] = _restore_warning(record)
        return results.ok(tool, state=state, detail=detail, **fields)
    fields["record"] = record
    if state == HELD_BY_ME:
        detail = f"This server holds the game lease as {record.get('label')}."
    elif state == HELD:
        detail = f"The game lease is {_holder_detail(record)}, a live process."
    else:
        detail = (f"The game lease was {_holder_detail(record)}, and that "
                  "process is gone. hs_lease_acquire recovers it.")
    return results.ok(tool, state=state, detail=detail, **fields)


def acquire(label: str, slot: int | None = None, force: bool = False,
            tool: str = "hs_lease_acquire") -> dict[str, Any]:
    """Take the lease for this process, or refuse naming who has it.

    Free and stale records are taken. A live holder refuses `lease_held`
    unless `force`, which replaces the record and returns `took_over_from`.
    Re-acquire by the holder refreshes `label` and `slot` and keeps the rest.
    """
    global _HELD_ID
    if not isinstance(label, str) or not LABEL_PATTERN.match(label):
        return results.refuse(
            tool, "invalid_label",
            f"{label!r} is not a usable lease label. Use 1-80 characters from "
            "A-Z a-z 0-9 . _ - , such as <slug>-live-<n>: it is how another "
            "session's refusal names this one.")
    if slot is not None and (isinstance(slot, bool) or not isinstance(slot, int)
                             or slot < 1):
        return results.refuse(
            tool, "invalid_label",
            f"slot {slot!r} is not a save slot. A slot is 1-based; leave it "
            "unset when the session loads none.")

    dll_path, dll_sha, dll_status = _dll_facts()
    try:
        with _locked():
            record = read_record(tool)
            unreadable = results.is_refusal(record)
            if unreadable and not force:
                return record
            if unreadable:
                record = None
            state = _classify(record)
            now = _now_utc()

            if state == HELD_BY_ME:
                assert record is not None
                record["label"] = label
                record["slot"] = slot
                _write(record)
                return results.ok(
                    tool, state=HELD_BY_ME, already_held=True,
                    recovered_stale=False, took_over_from=None,
                    **_public(record))

            if state == HELD and not force:
                assert record is not None
                return _held_refusal(tool, record, "Nothing was changed.")

            previous = None
            took_over_from = None
            warning = ""
            if record is not None and state == HELD:
                previous = _summary(record, OUTCOME_TAKEN_OVER, now)
                took_over_from = {key: previous[key] for key in
                                  ("label", "pid", "taken_utc", "backup_id",
                                   "restore_pending")}
            elif record is not None and state == STALE:
                previous = _summary(record, OUTCOME_STALE, now)
            elif record is not None:
                previous = _summary(record, OUTCOME_RELEASED,
                                    record.get("released_utc") or now)
            if previous and previous["restore_pending"]:
                warning = _restore_warning(record)

            fresh = {
                "schema": SCHEMA,
                "lease_id": secrets.token_hex(16),
                "state": HELD,
                "label": label,
                "slot": slot,
                "holder": process_identity(),
                "taken_utc": now,
                "released_utc": None,
                "dll_path": dll_path,
                "dll_sha256": dll_sha,
                "dll_status": dll_status,
                "backup_id": None,
                "restore_pending": False,
                "previous": previous,
            }
            _write(fresh)
            _HELD_ID = fresh["lease_id"]
    except (_Busy, OSError) as exc:
        return _unavailable(tool, exc)

    if state == STALE:
        log.info("lease: recovered a stale lease from %s (pid %s) for %s",
                 previous["label"], previous["pid"], label)
    elif took_over_from is not None:
        log.info("lease: %s took the lease over from %s (pid %s) with force",
                 label, took_over_from["label"], took_over_from["pid"])
    extra: dict[str, Any] = {"warning": warning} if warning else {}
    if unreadable:
        extra["replaced_unreadable"] = True
    return results.ok(
        tool, state=HELD_BY_ME, already_held=False,
        recovered_stale=state == STALE, took_over_from=took_over_from,
        **_public(fresh), **extra)


def release(tool: str = "hs_lease_release") -> dict[str, Any]:
    """Mark this process's lease `released`. The record is kept, not removed,
    so the next session sees a restore still owed."""
    global _HELD_ID
    try:
        with _locked():
            record = read_record(tool)
            if results.is_refusal(record):
                return record
            state = _classify(record)
            if state == HELD:
                assert record is not None
                return _held_refusal(tool, record,
                                     "This server does not hold it, so it "
                                     "was not released.")
            if state == STALE:
                assert record is not None
                return results.refuse(
                    tool, "lease_not_held",
                    f"The lease record is stale: it was {_holder_detail(record)}, "
                    "and that process is gone. This server does not hold it; "
                    "hs_lease_acquire recovers it.",
                    lease_path=str(record_path()))
            if state == FREE:
                what = ("There is no lease record" if record is None else
                        f"The lease was already released by {record.get('label')} "
                        f"at {record.get('released_utc')}")
                return results.refuse(
                    tool, "lease_not_held",
                    f"{what}, so there is nothing for this server to release.",
                    lease_path=str(record_path()))
            assert record is not None
            record["state"] = RELEASED
            record["released_utc"] = _now_utc()
            _write(record)
            _HELD_ID = None
    except (_Busy, OSError) as exc:
        return _unavailable(tool, exc)
    extra: dict[str, Any] = {}
    if record.get("restore_pending"):
        extra["warning"] = _restore_warning(record)
    return results.ok(tool, released=True, **_public(record), **extra)


def _public(record: dict[str, Any]) -> dict[str, Any]:
    """The record's fields a tool result carries at the top level."""
    return {key: record.get(key) for key in (
        "lease_id", "label", "slot", "holder", "taken_utc", "released_utc",
        "dll_path", "dll_sha256", "dll_status", "backup_id", "restore_pending",
        "previous")} | {"lease_path": str(record_path())}


# --------------------------------------------------------------------------
# What the six gated tools and the save tools call
# --------------------------------------------------------------------------

def guard(tool: str) -> dict[str, Any] | None:
    """None when this call may drive the game; otherwise the refusal.

    Refuses `lease_held` while another live process holds the lease, and
    `lease_unavailable` when the record cannot be read. Nobody holding, a
    stale holder and this process holding all let the call through: a caller
    with no lease while nobody holds one is allowed, and its result says
    `lease: "none"`.
    """
    record = read_record(tool)
    if results.is_refusal(record):
        return record
    if _classify(record) == HELD:
        assert record is not None
        return _held_refusal(tool, record,
                             "This call was refused before it touched the game.")
    return None


def lease_field() -> str:
    """`held` when this process holds the lease, else `none`."""
    record = read_record()
    if results.is_refusal(record):
        return "none"
    return "held" if _classify(record) == HELD_BY_ME else "none"


def stamp(result: dict[str, Any]) -> dict[str, Any]:
    """A gated tool's own result, carrying `lease: "held" | "none"`."""
    return {**result, "lease": lease_field()}


def _update_mine(change) -> bool:
    """Apply `change(record)` to this process's held record under the lock.
    False when this process does not hold it. A failure is logged, never
    raised: a note is bookkeeping and must not turn a finished backup,
    restore or character load into an error."""
    if _HELD_ID is None:
        return False
    try:
        with _locked():
            record = read_record()
            if results.is_refusal(record) or _classify(record) != HELD_BY_ME:
                return False
            change(record)
            _write(record)
            return True
    except (_Busy, OSError) as exc:
        log.warning("lease: could not update %s: %s", record_path(), exc)
        return False


def note_backup(backup_id: str) -> bool:
    """The holder backed up the live saves: record the id; a restore is owed."""
    def change(record: dict[str, Any]) -> None:
        record["backup_id"] = backup_id
        record["restore_pending"] = True
    return _update_mine(change)


def note_slot(slot: int) -> bool:
    """The holder loaded a character from `slot`."""
    def change(record: dict[str, Any]) -> None:
        record["slot"] = int(slot)
    return _update_mine(change)


def note_restore(backup_id: str) -> dict[str, Any]:
    """A restore of `backup_id` finished. Clears `restore_pending` when it is
    the backup the lease recorded -- on this process's held record, or on a
    `released` one, which is how a session that restores after the operator
    released still settles the debt. Returns the fields the restore result
    carries about it (empty when no lease recorded a backup)."""
    record = read_record()
    if results.is_refusal(record) or record is None:
        return {}
    state = _classify(record)
    if state not in (HELD_BY_ME, FREE) or not record.get("restore_pending"):
        return {}
    owed = record.get("backup_id")
    if owed != backup_id:
        return {"lease_restore_pending": True,
                "lease_detail": (f"The lease recorded {owed} as the backup "
                                 f"owed a restore; this restored {backup_id}, "
                                 "so the lease still says a restore is pending.")}
    try:
        with _locked():
            record = read_record()
            if (results.is_refusal(record) or record is None
                    or _classify(record) not in (HELD_BY_ME, FREE)
                    or record.get("backup_id") != backup_id):
                return {}
            record["restore_pending"] = False
            _write(record)
    except (_Busy, OSError) as exc:
        log.warning("lease: could not update %s: %s", record_path(), exc)
        return {"lease_restore_pending": True,
                "lease_detail": (f"The restore of {backup_id} finished but the "
                                 f"lease record could not be updated ({exc}).")}
    return {"lease_restore_pending": False,
            "lease_detail": (f"The lease recorded {backup_id} as owed a "
                             "restore; this restore settles it.")}
