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

1. **With the game running, a pending `cmd.txt` is waited out, never added to.**
   `ipc.ps1` overwrites it with a warning a person reads; nothing reads a
   warning here, and silently dropping a command the caller believes was sent is
   the worse failure. But adding to it is worse still: the plugin reads the whole
   file and *then* deletes it, so a line written in between is deleted unread
   **while the file still vanishes** -- which is this module's only signal for
   "consumed", so the send reports success and hands back the *earlier*
   command's output as this command's reply. Nothing downstream can tell that
   from a real answer. So the pending command is waited out, `out.txt` is allowed
   to settle, and this command is then written fresh into a file the plugin
   cannot already have opened; `pending_before` reports that it happened, and the
   success `detail` says so. A pending file nothing consumes is the same
   "nothing is reading this channel" state as an unconsumed send: the same
   `not_consumed` token, with `wrote_bytes: 0`, because writing after a
   timed-out wait is the `queue=True` behaviour the caller did not ask for.
   With the game closed and `queue=True` it still appends, because nothing can
   be mid-read of a file the game is not running to read. `timeout_s` is
   **split** between the two waits rather than spent first-come (see
   `PENDING_WAIT_SHARE`): a wait that inherits whatever is left of the budget
   reports a timeout it never made, and says the channel is unread when this
   same call had just watched the plugin read it.
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

from . import launcher_bridge, lease, procs, results

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

#: A send that finds a command already pending has two waits to make -- the
#: earlier command's and its own -- and `timeout_s` is split between them rather
#: than spent first-come. Measured before this split existed: a pending command
#: consumed at 0.1 s whose output then streamed into `out.txt` for 2 s left the
#: caller's own command **zero** budget, so `_await_consumption` refused on its
#: first pass and the envelope read `not_consumed`, "cmd.txt was still there
#: after 1.0 s" (it had been there for ~0 s), and named the only two explanations
#: this module knows for an unread channel -- both of which that same call had
#: disproved by watching the plugin consume the earlier command. A negative
#: produced by this module's own budget accounting is not evidence about the
#: game: `AGENTS.md` § "Prove the Instrument Before Trusting a Negative Result".
#: Half each, and the caller's own wait is never shorter than this share, so a
#: `not_consumed` refusal always reports a wait that actually happened.
PENDING_WAIT_SHARE = 0.5

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


def _configured_exe(tool: str) -> str:
    """The configured executable's path, for a refusal that has to name it.

    A `not_consumed` refusal has to say *which* install it was talking to: the
    gate matches by image name, while this channel came from the configured
    path, and the two can be different copies of the game.
    """
    exe = launcher_bridge.resolve_exe(tool)
    return "the configured executable" if results.is_refusal(exe) else str(exe)


def _not_observed(cmd: Path, exe: str) -> str:
    """Why nothing consuming `cmd.txt` is an observation, not a conclusion.

    Shared by both refusal shapes so they cannot drift apart. The gate says the
    game is running by *image name*; `bp_ipc\\` is resolved from the configured
    executable; and ForgePact's plugin derives its own channel from its own
    module path so that each copy of the game has a separate one. A second copy
    running -- the documented two-instance setup -- therefore produces this exact
    reading with the plugin fully loaded, which is why the text marks the plugin
    reading *this* channel as not observed and names both explanations.
    `AGENTS.md` § "Check a Permission Where It Is Used", last bullet.
    """
    return (f"Nothing consumed {cmd}, so the plugin reading this channel is "
            "not observed -- which is not the same as absent. Either "
            "BloodPactPlugin.dll was never loaded into the running process "
            f"(mods\\aurie\\BloodPactPlugin.dll), or the running "
            f"{procs.GAME_IMAGE} is a different copy from the configured "
            f"{exe}, because the plugin derives its own {DIR_NAME} from its own "
            "executable's location -- two copies, two channels. Compare that "
            "path with the running processes.")


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


def _await_consumption(cmd: Path, deadline: float,
                       abort: Callable[[], str] | None) -> tuple[bool, str]:
    """Poll until `cmd.txt` is gone: `(consumed, aborted)`.

    Called twice per send when a command was already pending -- once to wait
    that one out, once for ours -- so the two waits cannot drift apart in poll
    interval or abort handling. Their **deadlines are deliberately separate**:
    each is one wait with its own share of the budget, and a wait handed
    whatever the previous one left over reports a timeout nobody waited out
    (`PENDING_WAIT_SHARE`).
    """
    while True:
        if not cmd.exists():
            return True, ""
        aborted = (abort() or "") if abort is not None else ""
        if aborted:
            return False, aborted
        if time.monotonic() >= deadline:
            return False, ""
        time.sleep(CONSUME_POLL_S)


def _settle(out: Path, until: float) -> int:
    """Poll `out.txt`'s size until unchanged `SETTLE_POLLS` times; return it.

    Used twice, for the same reason in both places: the plugin appends while a
    command runs, so "the file stopped growing" is the only end-of-output signal
    this channel offers. After our command it ends the reply; *before* our
    command, when an earlier one was just consumed, it keeps that command's late
    output from being counted into our byte delta.
    """
    stable = 0
    last = -1
    while stable < SETTLE_POLLS and time.monotonic() < until:
        time.sleep(SETTLE_POLL_S)
        now = _size(out)
        stable = stable + 1 if now == last else 0
        last = now
    return _size(out)


def send(lines: Sequence[str], *, timeout_s: float = DEFAULT_TIMEOUT_S,
         queue: bool = False, gate: Gate | None = None,
         abort: Callable[[], str] | None = None,
         tool: str = "hs_command", lease_checked: bool = False) -> dict[str, Any]:
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

    The game lease is asked first, before the payload is even checked, so a
    second session sees `lease_held` and nothing is written; every other
    answer carries `lease: "held" | "none"`. `lease_checked=True` is for the
    callers inside this package that already asked (`hs_launch`,
    `hs_select_character`) or deliberately do not (`hs_wait_ready`'s ping).
    """
    if lease_checked:
        return _send(lines, timeout_s=timeout_s, queue=queue, gate=gate,
                     abort=abort, tool=tool)
    refusal = lease.guard(tool)
    if refusal:
        return refusal
    return lease.stamp(_send(lines, timeout_s=timeout_s, queue=queue, gate=gate,
                             abort=abort, tool=tool))


def _send(lines: Sequence[str], *, timeout_s: float, queue: bool,
          gate: Gate | None, abort: Callable[[], str] | None,
          tool: str) -> dict[str, Any]:
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

    budget = max(0.0, float(timeout_s))
    pending_before = cmd.exists()
    # Did this call watch the plugin take a command off this channel? The
    # `not_consumed` refusals below are different diagnoses with different fixes,
    # and this is the positive signal that tells them apart -- rather than a
    # field one of them happens to carry, which is how a reader ends up inferring
    # "the plugin is alive" from `wrote_bytes`.
    observed_consumption = False

    if state == procs.RUNNING and pending_before:
        # The plugin reads the whole of cmd.txt and *then* deletes it, so a line
        # appended in between is deleted unread while the file still vanishes --
        # which reads back as `consumed: true` with the *earlier* command's
        # output as this command's reply, and nothing downstream can tell that
        # from a real answer. So wait the pending command out and write ours
        # fresh into a file the plugin cannot already have opened. Only ever
        # creating a file is what closes the window; a label saying "this reply
        # may be wrong" would leave the wrong reply in the envelope.
        gone, aborted = _await_consumption(
            cmd, time.monotonic() + budget * PENDING_WAIT_SHARE, abort)
        if not gone:
            waited = round(time.monotonic() - started, 3)
            stopped = (f"The wait stopped after {waited} s because {aborted}"
                       if aborted else
                       f"An earlier command was still in {cmd} after {waited} s, "
                       f"the share of the {timeout_s} s budget this call spends "
                       "on a command that was already there")
            observed = _not_observed(cmd, _configured_exe(tool))
            return results.refuse(
                tool, "not_consumed",
                f"{stopped}, and nothing consumed it. This command was not "
                "written, because adding to a file the plugin may already "
                "have read loses it unread and would report the earlier "
                f"command's output as this command's reply. {observed} "
                "The earlier command was left in place; the plugin runs a "
                "pending file at its next start.",
                sent=cleaned, wrote_bytes=0, consumed=False, queued=False,
                pending_before=True, pending_left=True, aborted=aborted,
                observed_consumption=False, ipc_dir=str(directory),
                out_bytes_before=_size(out), elapsed_s=waited)
        observed_consumption = True
        # Let the earlier command's late output land before the offset is taken,
        # so it is not counted into this command's reply. Bounded by the settle
        # grace from here rather than out of this command's wait: how long
        # someone else's command prints for is not this caller's budget, and
        # taking it from there is what used to leave the wait below nothing.
        _settle(out, time.monotonic() + SETTLE_GRACE_S)

    # Computed *after* the pending file is gone and `out.txt` has settled, so
    # this is a wait for this command with its own share of the budget rather
    # than the remainder of someone else's. `timeout_s` therefore bounds each
    # wait; `pending_before`, `elapsed_s` and the success `detail` report when a
    # call spent two of them.
    deadline = max(started + budget,
                   time.monotonic() + budget * (1.0 - PENDING_WAIT_SHARE))
    settle_deadline = deadline + SETTLE_GRACE_S
    before = _size(out)

    # With the game running nothing can be pending here -- the wait above saw it
    # go -- so this only ever creates the file. With the game closed and
    # queue=true it appends, because nothing is going to read that file until the
    # game starts and dropping a command the caller believes was sent is the one
    # outcome they cannot see.
    with open(cmd, "ab") as handle:
        handle.write(raw)

    # What this command's own wait is, as the refusals below have to report it
    # rather than the caller's `timeout_s`: the two differ whenever an earlier
    # command had to be cleared first.
    own_wait = round(max(0.0, deadline - time.monotonic()), 1)

    if state != procs.RUNNING:
        # Queued by definition: nothing is going to consume this until the game
        # starts, so waiting for the timeout would only delay the answer.
        return results.ok(
            tool, sent=cleaned, wrote_bytes=len(raw), queued=True,
            consumed=False, pending_before=pending_before, pending_left=True,
            observed_consumption=False, ipc_dir=str(directory),
            game_state=state, aborted="", detail=(
                f"{why} The command was appended to {cmd} and the plugin will "
                "run it at its next start."),
            elapsed_s=round(time.monotonic() - started, 3))

    consumed, aborted = _await_consumption(cmd, deadline, abort)

    if not consumed:
        waited = round(time.monotonic() - started, 3)
        if aborted:
            return results.refuse(
                tool, "not_consumed",
                f"The wait stopped after {waited} s because {aborted}, so "
                f"nothing consumed cmd.txt at {cmd}. It was left in place; the "
                "plugin runs a pending file at its next start.",
                sent=cleaned, wrote_bytes=len(raw), consumed=False, queued=False,
                pending_before=pending_before, pending_left=True, aborted=aborted,
                observed_consumption=observed_consumption,
                ipc_dir=str(directory), out_bytes_before=before,
                elapsed_s=waited)
        if observed_consumption:
            # The plugin was watched taking the earlier command off this very
            # channel, in this call, so "nothing is reading it" is measurably
            # false and the two explanations `_not_observed` names are both
            # already disproved. A refusal that hands them back sends the reader
            # to compare install paths for a plugin that is demonstrably alive;
            # this state has a different fix, so it says something different.
            return results.refuse(
                tool, "not_consumed",
                f"The plugin on this channel was observed consuming an earlier "
                f"command from {cmd} during this call, and then did not take "
                f"this command within the {own_wait} s that were this command's "
                f"own wait (of a {timeout_s} s budget). So the channel is being "
                "read and it is this command's wait that expired -- not the same "
                "state as a channel nothing reads, and not the same fix: the "
                "plugin polls between commands, so the earlier one may still be "
                "running. Read out.txt with hs_ipc_tail to see what it is doing, "
                "or retry with a larger timeout_s. The command was left in "
                "place; the plugin runs a pending file at its next start.",
                sent=cleaned, wrote_bytes=len(raw), consumed=False, queued=False,
                pending_before=pending_before, pending_left=True, aborted="",
                observed_consumption=True, ipc_dir=str(directory),
                out_bytes_before=before,
                elapsed_s=round(time.monotonic() - started, 3))
        return results.refuse(
            tool, "not_consumed",
            f"cmd.txt was still there after {own_wait} s. "
            f"{_not_observed(cmd, _configured_exe(tool))} The command was left "
            "in place; the plugin runs a pending file at its next start.",
            sent=cleaned, wrote_bytes=len(raw), consumed=False, queued=False,
            pending_before=pending_before, pending_left=True, aborted="",
            observed_consumption=False, ipc_dir=str(directory),
            out_bytes_before=before,
            elapsed_s=round(time.monotonic() - started, 3))

    # The plugin appends while the command runs, so the reply is complete only
    # once out.txt has stopped growing.
    after = _settle(out, settle_deadline)
    rotated = after < before
    reply = _read_from(out, 0 if rotated else before)
    extra: dict[str, Any] = {}
    if pending_before:
        # The only success path that carries a detail: the caller cannot
        # otherwise tell that the ~0.6 s this took was a queued command being
        # cleared, nor that the reply below was measured after it.
        extra["detail"] = (
            "An earlier command was pending; it was consumed first and out.txt "
            "was allowed to settle before this command was written, so the "
            "reply is this command's own output and not the earlier one's. "
            f"That is why elapsed_s is longer than the {own_wait} s this "
            "command's own wait was given.")
    return results.ok(
        tool, sent=cleaned, wrote_bytes=len(raw), consumed=True, queued=False,
        reply=reply, reply_lines=reply.splitlines(), aborted="",
        pending_before=pending_before, pending_left=cmd.exists(),
        observed_consumption=True,
        ipc_dir=str(directory), out_bytes_before=before, out_bytes_after=after,
        rotated=rotated, game_state=state,
        elapsed_s=round(time.monotonic() - started, 3), **extra)


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
