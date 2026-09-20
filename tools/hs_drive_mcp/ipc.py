"""ForgePact's file IPC: send a command to the running plugin, read its reply.

The plugin's channel is two files in `<dir of game_exe>\\bp_ipc\\`, created by
the plugin at load:

* `cmd.txt` -- one command per line, polled every few frames. The plugin reads
  it, **deletes it immediately**, then runs each line. Bytes are read raw and
  split on newlines, so what is written here is plain ASCII with CRLF endings
  and no BOM: a UTF-8 BOM corrupts the first command rather than failing
  visibly.
* `out.txt` -- append-only, and appended to by other features while a command
  runs. So a reply is the **byte delta** after the pre-send length, never the
  last N lines, which would drift.

`ForgePact/tools/ipc.ps1` already established both halves and this module is the
same algorithm with two differences, each of which exists because a model rather
than a person is driving:

1. **It appends to a pending `cmd.txt` instead of overwriting it.** `ipc.ps1`
   overwrites with a warning a person reads; nothing reads a warning here, and
   silently dropping a command the caller believes was sent is the worse
   failure. `pending_before` reports that it happened.
2. **A send that was never consumed is a refusal, not a printed message.**
   `not_consumed` with the timeout in the detail, and the command deliberately
   left on disk -- the plugin runs a pending file at its next start, which is
   what `queue=True` exists for.

The gate is injected (`procs.gate`), and only `running` lets a command through
unless the caller asked to queue it. `unknown` refuses either way: a queued
command against a game that might be running is a command that might run
immediately, and `AGENTS.md` § "Check a Permission Where It Is Used" is explicit
that a sentinel meaning *unknown* must never compare equal to a real value.

Nothing in this module removes `out.txt`, truncates it, or writes anywhere
except `cmd.txt`.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from . import launcher_bridge, procs, results

DIR_NAME = "bp_ipc"
CMD_NAME = "cmd.txt"
OUT_NAME = "out.txt"

#: One command per line, and a cap on both dimensions. The plugin reads the
#: whole file in one go; these keep a model's mistake (a pasted document, a
#: runaway loop) from becoming a multi-megabyte cmd.txt the game then splits
#: into thousands of commands.
MAX_LINES = 64
MAX_BYTES = 4096

DEFAULT_TIMEOUT_S = 10.0

#: How often `cmd.txt`'s disappearance is checked. ForgePact's panel polls at
#: 0.25 s; 0.1 s here costs nothing and makes a `ping` round trip feel prompt.
CONSUME_POLL_S = 0.1

#: The settle rule, from `ipc.ps1`: after consumption, poll `out.txt`'s size
#: until it has been unchanged for four consecutive reads, bounded by the
#: timeout plus a grace period. A full instance dump is a few hundred `Out()`
#: calls, so "the file stopped growing" is the only honest end-of-reply signal
#: the channel offers.
SETTLE_POLL_S = 0.15
SETTLE_POLLS = 4
SETTLE_GRACE_S = 10.0

#: `hs_ipc_tail` bounds, and how much of the file's end is read to satisfy
#: them. `out.txt` reaches megabytes before the plugin rotates it at load.
TAIL_MAX_LINES = 500
TAIL_READ_BYTES = 512 * 1024

#: A gate answers `(state, why)`; the `why` becomes the refusal detail verbatim.
Gate = Callable[[], tuple[str, str]]

#: Every state this module branches on, asserted against `procs.GATE_STATES` by
#: the suite so a sixth state added there cannot fall through here silently.
HANDLED_GATE_STATES = (procs.RUNNING, procs.NOT_RUNNING, procs.UNKNOWN,
                       procs.ENGINE_MISSING, procs.ENGINE_UNUSABLE)


def resolve_dir(tool: str = "hs_command") -> Path | dict[str, Any]:
    """`<dir of game_exe>\\bp_ipc`, or a refusal naming what is missing.

    Two different fixes, so two different tokens: a panel that was never
    pointed at the game (`forgepact_config_missing`) and a modded copy that has
    never been launched (`bp_ipc_missing`, because the plugin creates the
    directory at load).
    """
    exe = launcher_bridge.resolve_exe(tool)
    if results.is_refusal(exe):
        return exe
    directory = launcher_bridge.ipc_dir(exe)
    if directory is None or not directory.is_dir():
        return results.refuse(
            tool, "bp_ipc_missing",
            f"No {DIR_NAME} directory at {directory}. The plugin creates it at "
            "load, so launch the modded game once with BloodPactPlugin.dll "
            "installed, then retry.")
    return directory


def _gate_reading(tool: str, gate: Gate, queue: bool) -> tuple[str, str, dict[str, Any] | None]:
    """Ask the gate once: `(state, why, refusal or None)`.

    `running` proceeds; `not_running` proceeds only to queue. The detail is the
    gate's own `why`, not a sentence composed here -- the core workorder made
    that a rule after two refusals named a subsystem nobody had reached.

    Once, deliberately: a second reading taken after the write, to decide
    whether to wait, would report a game that closed in between as "queued" and
    swallow the fact that it had been running when the caller asked. The
    disappearing-process case belongs to `abort` below, which says so.
    """
    state, why = gate()
    if state == procs.RUNNING:
        return state, why, None
    if state == procs.NOT_RUNNING:
        if queue:
            return state, why, None
        return state, why, results.refuse(
            tool, "game_not_running",
            f"{why} Launch the game first, or pass queue=true to leave the "
            "command in cmd.txt for the plugin to run at its next start.")
    if state == procs.ENGINE_MISSING:
        return state, why, results.refuse(
            tool, "engine_source_missing",
            f"{why} So whether the game is running cannot be determined, and "
            "no command was written.")
    if state == procs.ENGINE_UNUSABLE:
        return state, why, results.refuse(
            tool, "engine_import_failed",
            f"{why} So whether the game is running cannot be determined, and "
            "no command was written.")
    # Catch-all rather than an `unknown` branch: an unrecognised state must
    # refuse, not fall through into a write.
    return state, why, results.refuse(
        tool, "game_state_unknown",
        f"{why} Refusing rather than assuming the game is closed; queue=true "
        "does not relax this, because a queued command against a game that "
        "might be running is a command that might run immediately.")


def _payload(lines: Any, tool: str) -> tuple[list[str], bytes] | dict[str, Any]:
    """Validate and encode, or refuse `invalid_command` naming which rule."""
    if isinstance(lines, str) or lines is None:
        # A bare string is almost always a model passing "ping stat" as one
        # line; refusing is better than guessing where the command boundary is.
        return results.refuse(
            tool, "invalid_command",
            "Pass a list of command lines, e.g. [\"ping\"]; a bare string or "
            "null is not a command list.")
    try:
        cleaned = [str(line).strip() for line in lines]
    except TypeError:
        return results.refuse(
            tool, "invalid_command", f"{lines!r} is not a sequence of lines.")
    cleaned = [line for line in cleaned if line]
    if not cleaned:
        return results.refuse(
            tool, "invalid_command",
            "There is nothing to send: every line was empty or whitespace.")
    if len(cleaned) > MAX_LINES:
        return results.refuse(
            tool, "invalid_command",
            f"{len(cleaned)} lines is over the {MAX_LINES}-line limit for one "
            "cmd.txt write. Send them in batches.")
    for line in cleaned:
        if any(character in line for character in "\r\n"):
            return results.refuse(
                tool, "invalid_command",
                f"{line!r} contains a line break. The plugin splits cmd.txt on "
                "newlines, so this would silently become more than one "
                "command; pass one command per list entry instead.")
        try:
            line.encode("ascii")
        except UnicodeEncodeError as exc:
            return results.refuse(
                tool, "invalid_command",
                f"{line!r} is not ASCII ({exc.reason} at position {exc.start}). "
                "The plugin reads cmd.txt as raw bytes, so anything outside "
                "ASCII arrives corrupted rather than failing visibly.")
    payload = ("\r\n".join(cleaned) + "\r\n").encode("ascii")
    if len(payload) > MAX_BYTES:
        return results.refuse(
            tool, "invalid_command",
            f"{len(payload)} bytes is over the {MAX_BYTES}-byte limit for one "
            "cmd.txt write.")
    return cleaned, payload


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _read_from(path: Path, offset: int) -> str:
    """The bytes after `offset`, decoded leniently.

    `out.txt` is open for writing in the game while this reads it. Python's
    `open` shares read and write on Windows, which is the same share mode
    `ipc.ps1` asks for explicitly.
    """
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def send(lines: Sequence[str], *, timeout_s: float = DEFAULT_TIMEOUT_S,
         queue: bool = False, gate: Gate | None = None,
         abort: Callable[[], str] | None = None,
         tool: str = "hs_command") -> dict[str, Any]:
    """Write `lines` to `cmd.txt` and return exactly what the plugin appended.

    The reply is the byte delta of `out.txt` after the pre-send length. If
    `out.txt` shrank in between -- the plugin rotates it to `out.prev.txt` at
    load when it is over 2 MB -- the offset is stale, so the whole file is read
    and `rotated: true` says the reply may carry more than this command's own
    output. Reporting that beats reading from an offset that no longer means
    anything.

    `abort` is polled while waiting for the game to consume the command and
    returns a short token (or an empty string) each time. It exists because the
    longest wait this server does is the one for a plugin that is still loading,
    and a wait that cannot notice the game died runs its full budget after a
    startup crash. The reason it returned travels back as `aborted`; ForgePact's
    own `wait_for_plugin_ready` stops on the same condition.
    """
    gate = procs.gate if gate is None else gate
    started = time.monotonic()

    payload = _payload(lines, tool)
    if results.is_refusal(payload):
        return payload
    cleaned, raw = payload

    state, why, refusal = _gate_reading(tool, gate, queue)
    if refusal:
        return refusal

    directory = resolve_dir(tool)
    if results.is_refusal(directory):
        return directory
    cmd = directory / CMD_NAME
    out = directory / OUT_NAME

    before = _size(out)
    pending_before = cmd.exists()

    # Append, never overwrite: a pending cmd.txt is a command the game has not
    # read yet, and dropping it is the one outcome the caller cannot see.
    with open(cmd, "ab") as handle:
        handle.write(raw)

    if state != procs.RUNNING:
        # Queued by definition: nothing is going to consume this until the game
        # starts, so waiting for the timeout would only delay the answer.
        return results.ok(
            tool, sent=cleaned, wrote_bytes=len(raw), queued=True,
            consumed=False, pending_before=pending_before, pending_left=True,
            ipc_dir=str(directory), game_state=state, aborted="", detail=(
                f"{why} The command was appended to {cmd} and the plugin will "
                "run it at its next start."),
            elapsed_s=round(time.monotonic() - started, 3))

    deadline = time.monotonic() + max(0.0, float(timeout_s))
    consumed = False
    aborted = ""
    while True:
        if not cmd.exists():
            consumed = True
            break
        aborted = (abort() or "") if abort is not None else ""
        if aborted:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(CONSUME_POLL_S)

    if not consumed:
        waited = round(time.monotonic() - started, 3)
        if aborted:
            return results.refuse(
                tool, "not_consumed",
                f"The wait stopped after {waited} s because {aborted}, so the "
                f"plugin never read cmd.txt at {cmd}. It was left in place; the "
                "plugin runs a pending file at its next start.",
                sent=cleaned, wrote_bytes=len(raw), consumed=False, queued=False,
                pending_before=pending_before, pending_left=True, aborted=aborted,
                ipc_dir=str(directory), out_bytes_before=before,
                elapsed_s=waited)
        return results.refuse(
            tool, "not_consumed",
            f"cmd.txt at {cmd} was still there after {timeout_s} s, so the "
            "plugin never read it. Is Hero_Siege.exe running with "
            "BloodPactPlugin.dll loaded (mods\\aurie\\BloodPactPlugin.dll)? "
            "The command was left in place; the plugin runs a pending file at "
            "its next start.",
            sent=cleaned, wrote_bytes=len(raw), consumed=False, queued=False,
            pending_before=pending_before, pending_left=True, aborted="",
            ipc_dir=str(directory), out_bytes_before=before,
            elapsed_s=round(time.monotonic() - started, 3))

    # The plugin appends while the command runs, so the reply is complete only
    # once out.txt has stopped growing.
    settle_deadline = deadline + SETTLE_GRACE_S
    stable = 0
    last = -1
    while stable < SETTLE_POLLS and time.monotonic() < settle_deadline:
        time.sleep(SETTLE_POLL_S)
        now = _size(out)
        stable = stable + 1 if now == last else 0
        last = now

    after = _size(out)
    rotated = after < before
    reply = _read_from(out, 0 if rotated else before)
    return results.ok(
        tool, sent=cleaned, wrote_bytes=len(raw), consumed=True, queued=False,
        reply=reply, reply_lines=reply.splitlines(), aborted="",
        pending_before=pending_before, pending_left=cmd.exists(),
        ipc_dir=str(directory), out_bytes_before=before, out_bytes_after=after,
        rotated=rotated, game_state=state,
        elapsed_s=round(time.monotonic() - started, 3))


def tail(n: int = 40, tool: str = "hs_ipc_tail") -> dict[str, Any]:
    """The last `n` lines of `out.txt`, with the file's total size.

    An absent `out.txt` reports `exists: false` and carries **no** `lines` key.
    An empty list there would read as "the plugin answered nothing", which is a
    different machine state with a different fix, and this server's whole
    posture is that those two must not be confusable.
    """
    directory = resolve_dir(tool)
    if results.is_refusal(directory):
        return directory
    out = directory / OUT_NAME
    if not out.is_file():
        return results.ok(
            tool, exists=False, path=str(out), bytes_total=0, detail=(
                f"{out} does not exist yet. The plugin creates it at load and "
                "appends to it for every reply, so this means the modded game "
                "has not run since the directory was last cleared."))

    requested = max(1, min(int(n), TAIL_MAX_LINES))
    total = _size(out)
    offset = max(0, total - TAIL_READ_BYTES)
    text = _read_from(out, offset)
    lines = text.splitlines()
    if offset and lines:
        # The read started mid-line; that fragment is not a line the plugin
        # wrote, so it is dropped rather than reported.
        lines = lines[1:]
    return results.ok(
        tool, exists=True, path=str(out), bytes_total=total,
        requested=requested, truncated=bool(offset), lines=lines[-requested:])
