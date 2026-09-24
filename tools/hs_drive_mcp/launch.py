"""Launch the modded game, wait until it can be driven, and close it politely.

**The launch is ForgePact's, not this server's.** `ForgePact/src/offline_launcher.py`
already owns the whole sequence -- PE validation, the anti-cheat and
already-running checks, the Steam runtime lookup and environment, the `Popen`,
and a delayed verification that reports "the game exited during startup" -- and
`launcher_bridge` imports it rather than copying it. This module supplies the two
things that engine deliberately leaves to its caller:

* the executable's path, from ForgePact's own `forgepact.json`. An explicit
  `exe_path` overrides it for one call and **persists nothing**: writing a path
  into the user's launcher configuration is the side effect that ruled out
  HS-Offline-Launcher's module for this job;
* the plugin preflight, as the `validate_extra` callable the engine invokes
  inside its own validation. Doing it there rather than here is what makes
  "`Popen` was never reached" true by construction: the engine refuses before it
  starts anything, and this module only has to translate that refusal.

**Readiness is four answers, never one.** "the process is up" is not "the
plugin answered", and neither is "the plugin consumed the ping and said
nothing" or "nothing consumed it at all". Each is its own `phase`, and `ready`
is the single field that says whether the game can be driven. An earlier
feature in this toolkit reported itself armed while being structurally unable
to do anything, which is why `AGENTS.md` § "Prove the Instrument" asks for a
positive control: here the control is the plugin's own `ping`/`pong`, sent
through the same channel `hs_command` uses. `ready` is therefore exactly "the
control fired" -- a consumed ping that came back without a `pong` is
`plugin_consumed_without_pong, ready: false`, because a channel whose replies
are not arriving makes every later `hs_command` reply unreadable rather than
empty, and this module must not be the thing that hides that.

**Closing is `WM_CLOSE`.** That is the user pressing X: the game runs its own
exit path and writes its saves, which is what makes a save comparison after a
test session mean anything. `TerminateProcess` is reachable only with
`force=true`, only for a PID this server's own `hs_launch` started in this
process, and only after the graceful wait has already timed out -- `AGENTS.md`
§ "Drive a Tauri App Yourself" (never kill a process you did not start), applied
to a game instead of a dev server. Nothing here suspends, freezes or restores
runtime state; § "Don't Suspend the Game's Own Runtime" was checked and this
module stays on the read-or-ask-nicely side of it.

The envelope's `ok` says whether the tool did its job; `ready`, `exited` and
`phase` say what the game did. A launch that ran and then sat at a channel
nothing consumed is `ok: true, ready: false, phase:
"timeout_waiting_for_plugin"` -- not a refusal, because nothing was refused, and
not a success either. That phase is deliberately *not* reported as "the plugin
is absent": the gate matches by image name while `bp_ipc\\` is resolved from the
configured executable, and the plugin derives its own channel from its own
module path, so a second copy of the game running produces the same reading with
the plugin fully loaded. The detail names both explanations -- **unless the wait
itself watched the plugin consume an earlier command on that channel**, which is
what `hs_command(queue=true)` followed by this wait produces. Then neither
explanation is available: the channel is read, the ping's own wait is what
expired, and the detail says so instead, because sending the reader off to
compare install paths for a plugin this call just watched working is the
mislabelled negative § "Prove the Instrument" is about.
"""
from __future__ import annotations

import ctypes
import time
from pathlib import Path
from typing import Any, Callable

from . import capture, ipc, launcher_bridge, lease, procs, results

WM_CLOSE = 0x0010
PROCESS_TERMINATE = 0x0001

#: How often the process gate is re-read while waiting. The engine's own
#: startup verification sleeps 5 s before it reports, so nothing here is faster
#: than the thing it is waiting for.
PROCESS_POLL_S = 0.5

DEFAULT_LAUNCH_TIMEOUT_S = 90.0
DEFAULT_STOP_TIMEOUT_S = 30.0

#: The plugin's positive control. `pong (YYTK a.b.c)` comes back from the
#: running plugin and from nothing else.
PING = "ping"
PONG = "pong"

#: PIDs this process launched. The only PIDs `force=true` may terminate, and the
#: reason it is a module-level set rather than a file: a PID from an earlier run
#: of this server has no claim on the process wearing that number now.
_LAUNCHED: set[int] = set()

Gate = Callable[[], tuple[str, str]]


def launched_pids() -> set[int]:
    """A copy, so a caller cannot widen what `force=true` is allowed to kill."""
    return set(_LAUNCHED)


def kernel32() -> Any:
    return ctypes.WinDLL("kernel32", use_last_error=True)


def terminate(pid: int) -> tuple[bool, str]:
    """`TerminateProcess` on one PID. Callers enforce whether that is allowed."""
    api = kernel32()
    handle = api.OpenProcess(PROCESS_TERMINATE, False, int(pid))
    if not handle:
        return False, (f"OpenProcess(PROCESS_TERMINATE, {pid}) failed "
                       f"(GetLastError {ctypes.get_last_error()})")
    try:
        if not api.TerminateProcess(handle, 1):
            return False, (f"TerminateProcess({pid}) failed "
                           f"(GetLastError {ctypes.get_last_error()})")
    finally:
        api.CloseHandle(handle)
    return True, ""


class ModChainPreflight:
    """The four install facts, as the callable the engine validates with.

    It remembers its own verdict because the engine returns only a message, and
    the tool has to tell "this is not a modded copy" (`mod_chain_incomplete`,
    fixed by installing the plugin) from every other reason a launch is refused
    (`launcher_refused`, fixed by closing the game or EAC). One string compare
    against the engine's wording would have been the fragile way to do that.
    """

    def __init__(self, exe: Path):
        self.exe = Path(exe)
        self.chain: dict[str, bool] = {}
        self.missing: list[str] = []
        self.message = ""

    def __call__(self) -> str:
        self.chain = launcher_bridge.mod_chain(self.exe)
        self.missing = [key for key in launcher_bridge.MOD_CHAIN_KEYS
                        if not self.chain.get(key)]
        if not self.missing:
            self.message = ""
            return ""
        self.message = (
            f"{self.exe} is not a complete ForgePact install: "
            f"{', '.join(self.missing)} missing. Install the mod from the "
            "ForgePact panel, then launch again.")
        return self.message


def _engine(tool: str) -> tuple[Any, dict[str, Any] | None]:
    """The engine module, or the refusal that says which fix applies."""
    engine, blocked, why = procs.load_engine()
    if blocked == procs.ENGINE_MISSING:
        return None, results.refuse(tool, "engine_source_missing", why,
                                    phase="preflight")
    if blocked:
        return None, results.refuse(tool, "engine_import_failed", why,
                                    phase="preflight")
    return engine, None


def _report(tool: str, *, engine: Any, phase: str, ready: bool, plugin: str,
            detail: str, pid: int, state: str, started: float,
            plugin_reply: str = "", **extra: Any) -> dict[str, Any]:
    """One shape for every readiness answer, so none of them can omit a field."""
    return results.ok(
        tool, phase=phase, ready=ready, plugin=plugin, plugin_reply=plugin_reply,
        detail=detail, pid=pid, pids=procs.game_pids(), game_state=state,
        launch=dict(engine.launch_status()),
        elapsed_s=round(time.monotonic() - started, 3), **extra)


def wait_ready(*, engine: Any, gate: Gate, timeout_s: float, require_plugin: bool,
               tool: str, pid: int = 0, started: float | None = None) -> dict[str, Any]:
    """Poll until the process is up and, optionally, the plugin answers.

    Split in two on purpose. The process poll is cheap and its failure means
    "nothing started"; the plugin probe writes a real command into the real
    channel and its failure means "started, but not driveable". Reporting one as
    the other is what makes a caller act on the wrong thing.
    """
    started = time.monotonic() if started is None else started
    deadline = started + max(0.0, float(timeout_s))

    state, why = gate()
    while state != procs.RUNNING:
        if state == procs.ENGINE_MISSING:
            return results.refuse(tool, "engine_source_missing", why,
                                  phase="readiness")
        if state == procs.ENGINE_UNUSABLE:
            return results.refuse(tool, "engine_import_failed", why,
                                  phase="readiness")
        if state != procs.NOT_RUNNING:
            # `unknown`, or anything a later procs.py adds. Refusing beats
            # polling a reading that is not an answer.
            return results.refuse(
                tool, "game_state_unknown",
                f"{why} Refusing rather than reporting a readiness phase "
                "derived from a process snapshot that did not work.",
                phase="readiness")
        if time.monotonic() >= deadline:
            return _report(
                tool, engine=engine, phase="timeout_waiting_for_process",
                ready=False, plugin="not_checked", pid=pid, state=state,
                started=started,
                detail=(f"No {procs.GAME_IMAGE} process appeared within "
                        f"{timeout_s} s. {why}"))
        time.sleep(PROCESS_POLL_S)
        state, why = gate()

    pids = procs.game_pids()
    pid = pid or (pids[0] if pids else 0)

    if not require_plugin:
        return _report(
            tool, engine=engine, phase="process_running", ready=True,
            plugin="not_checked", pid=pid, state=state, started=started,
            detail=(f"{why} The plugin was not probed, because require_plugin "
                    "is false; nothing here says a command would be answered."))

    directory = ipc.resolve_dir(tool)
    if results.is_refusal(directory):
        plugin = ("no_bp_ipc" if directory["reason"] == "bp_ipc_missing"
                  else "config_missing")
        return _report(
            tool, engine=engine, phase="process_running", ready=False,
            plugin=plugin, pid=pid, state=state, started=started,
            detail=(f"The process is up but its command channel is not usable. "
                    f"{directory['detail']}"))

    checked = [time.monotonic()]
    #: The gate reading that stopped the wait, if one did: `(state, why)`.
    stopped: list[tuple[str, str]] = []

    def watch() -> str:
        """Stop waiting the moment the process is no longer there -- or the
        moment the gate stops giving an answer.

        Throttled to the process poll interval rather than run on every
        consumption poll: each gate reading is a whole Win32 process snapshot,
        and taking ten a second while the game is loading is this server
        competing with the thing it is waiting for.

        Only `not_running` means the process went away. `unknown` (a snapshot
        that failed) and the engine states are not an answer either way, so
        they stop the wait too -- the same "refusing beats polling a reading
        that is not an answer" rule as the pre-wait check above -- but they are
        recorded, so the abort branch below reports them as what they are
        rather than as an exit.
        """
        now = time.monotonic()
        if now - checked[0] < PROCESS_POLL_S:
            return ""
        checked[0] = now
        state_now, now_why = gate()
        if state_now == procs.RUNNING:
            return ""
        stopped.append((state_now, now_why))
        if state_now == procs.NOT_RUNNING:
            return f"the game is no longer running ({now_why})"
        return f"the process gate stopped answering ({state_now}: {now_why})"

    remaining = max(1.0, deadline - time.monotonic())
    # `lease_checked`: `hs_launch` asked the lease before it launched, and
    # `hs_wait_ready` is deliberately not gated -- it drives nothing but one
    # ping, for a game somebody else started.
    sent = ipc.send([PING], timeout_s=remaining, gate=gate, abort=watch, tool=tool,
                    lease_checked=True)

    if results.is_refusal(sent):
        if stopped and stopped[-1][0] != procs.NOT_RUNNING:
            # The wait stopped on a reading that is not an answer. Whether the
            # game is still up is unknown, so this is neither `process_exited`
            # nor a plugin timeout: it is the same refusal the pre-wait check
            # gives, carrying the state the gate actually reported.
            state_now, now_why = stopped[-1]
            reason = {procs.ENGINE_MISSING: "engine_source_missing",
                      procs.ENGINE_UNUSABLE: "engine_import_failed"}.get(
                          state_now, "game_state_unknown")
            return results.refuse(
                tool, reason,
                f"{now_why} The process gate stopped answering while waiting "
                "for the plugin, so whether the game is still running is "
                "unknown; refusing rather than reporting it as exited. "
                f"{sent['detail']}",
                phase="readiness", game_state=state_now, pid=pid,
                aborted=sent.get("aborted", ""))
        if sent.get("aborted") or sent["reason"] == "game_not_running":
            message = str(engine.launch_status().get("message", ""))
            return _report(
                tool, engine=engine, phase="process_exited", ready=False,
                plugin="process_exited", pid=pid, state=procs.NOT_RUNNING,
                started=started,
                detail=(f"The process disappeared while waiting for the plugin. "
                        f"{message}"))
        if sent["reason"] == "not_consumed":
            if sent.get("observed_consumption"):
                # The send watched the plugin take an earlier command off this
                # channel during this same wait -- the queued-command case, which
                # `hs_command(queue=true)` then `hs_wait_ready` produces -- so the
                # channel is read and the ping's own wait is what expired. Saying
                # "not observed" here would send the reader to compare install
                # paths for a plugin this wait had just watched working.
                detail = (f"{procs.GAME_IMAGE} is running and the ping was not "
                          f"answered, but this channel is not unread: "
                          f"{sent['detail']}")
            else:
                detail = (f"{procs.GAME_IMAGE} is running, but nothing consumed "
                          f"{directory / ipc.CMD_NAME} within "
                          f"{round(remaining, 1)} s. That makes the plugin "
                          "reading this channel not observed rather than absent: "
                          "either BloodPactPlugin.dll was never loaded into the "
                          f"running process, or the running {procs.GAME_IMAGE} is "
                          "a different copy from the one this channel belongs to, "
                          f"since the plugin derives its own {ipc.DIR_NAME} from "
                          "its own executable's location -- two copies, two "
                          "channels, and `pids` says which processes are live. "
                          f"{sent['detail']}")
            return _report(
                tool, engine=engine, phase="timeout_waiting_for_plugin",
                ready=False, plugin="not_consumed", pid=pid, state=state,
                started=started, detail=detail)
        # Anything else the channel refuses is that refusal, not a phase.
        return {**sent, "phase": "readiness"}

    reply = str(sent.get("reply", ""))
    answered = PONG in reply.lower()
    if answered:
        detail = "The plugin consumed a ping and answered: " + reply.strip()
    else:
        # Consumed, but the positive control did not fire. `ready` means "a
        # command would be answered", and nothing here has shown that -- the
        # plugin's `Out()` writes can be failing (the panel holding out.txt open
        # is a recorded case), in which case every later reply is empty and
        # indistinguishable from a command that did nothing. § "Prove the
        # Instrument Before Trusting a Negative Result" forbids trusting
        # anything downstream of a control that did not fire, so this is its own
        # phase rather than `plugin_ready` with the flag turned off.
        gained = (int(sent.get("out_bytes_after", 0))
                  - int(sent.get("out_bytes_before", 0)))
        detail = (f"The plugin consumed a ping but did not answer pong, so its "
                  f"positive control did not fire. out.txt gained {gained} "
                  f"byte(s): {reply.strip() or '(nothing was appended)'}. "
                  "Replies from hs_command cannot be trusted until a ping "
                  "answers -- an empty reply cannot be told apart from a "
                  "command that did nothing.")
    return _report(
        tool, engine=engine,
        phase="plugin_ready" if answered else "plugin_consumed_without_pong",
        ready=answered, plugin="ready" if answered else "consumed_without_pong",
        plugin_reply=reply, pid=pid, state=state, started=started,
        detail=detail, ipc_dir=sent.get("ipc_dir", ""))


def hs_launch(exe_path: str | None = None, wait_for_plugin: bool = True,
              timeout_s: float = DEFAULT_LAUNCH_TIMEOUT_S, *,
              gate: Gate | None = None, tool: str = "hs_launch") -> dict[str, Any]:
    """Launch the modded game through ForgePact's engine, then wait for it.

    The game lease is asked first, before the engine loads, so a second
    session sees `lease_held` rather than whatever the game's own state would
    have made it; every other answer carries `lease: "held" | "none"`.
    """
    refusal = lease.guard(tool)
    if refusal:
        return refusal
    return lease.stamp(_launch(exe_path, wait_for_plugin, timeout_s, gate=gate,
                               tool=tool))


def _launch(exe_path: str | None, wait_for_plugin: bool, timeout_s: float, *,
            gate: Gate | None, tool: str) -> dict[str, Any]:
    gate = procs.gate if gate is None else gate
    started = time.monotonic()

    engine, refusal = _engine(tool)
    if refusal:
        return refusal

    override = bool(exe_path)
    if override:
        exe = Path(str(exe_path))
    else:
        resolved = launcher_bridge.resolve_exe(tool)
        if results.is_refusal(resolved):
            return {**resolved, "phase": "preflight"}
        exe = Path(resolved)

    preflight = ModChainPreflight(exe)
    outcome = engine.launch_game(exe, validate_extra=preflight)
    reported = dict(outcome.get("launch") or {})

    if "err" in outcome:
        error = str(outcome["err"])
        if preflight.missing:
            return results.refuse(
                tool, "mod_chain_incomplete", preflight.message,
                phase="preflight", missing=list(preflight.missing),
                mod_chain=dict(preflight.chain), error=error, launch=reported,
                exe_path=str(exe), exe_path_override=override)
        return results.refuse(
            tool, "launcher_refused",
            f"ForgePact's launch engine refused: {error}",
            phase="launch", error=error, launch=reported, exe_path=str(exe),
            exe_path_override=override, mod_chain=dict(preflight.chain))

    pid = int(outcome.get("pid") or 0)
    if pid:
        # Recorded before the wait: a launch that times out waiting for the
        # plugin is still a process this server started.
        _LAUNCHED.add(pid)

    report = wait_ready(engine=engine, gate=gate, timeout_s=timeout_s,
                        require_plugin=wait_for_plugin, tool=tool, pid=pid,
                        started=started)
    return {**report, "exe_path": str(exe), "exe_path_override": override,
            "launched_here": bool(pid), "launch_message": str(outcome.get("ok", ""))}


def hs_wait_ready(timeout_s: float = DEFAULT_LAUNCH_TIMEOUT_S,
                  require_plugin: bool = True, *, gate: Gate | None = None,
                  tool: str = "hs_wait_ready") -> dict[str, Any]:
    """The same poll without launching, for a game the human started."""
    gate = procs.gate if gate is None else gate
    engine, refusal = _engine(tool)
    if refusal:
        return refusal
    return wait_ready(engine=engine, gate=gate, timeout_s=timeout_s,
                      require_plugin=require_plugin, tool=tool)


def hs_stop_game(force: bool = False, timeout_s: float = DEFAULT_STOP_TIMEOUT_S,
                 *, gate: Gate | None = None,
                 tool: str = "hs_stop_game") -> dict[str, Any]:
    """Post `WM_CLOSE` to every visible game window and wait for the exit.

    Gated by the lease like `hs_launch`: closing a game another session is
    driving loses that session's run as surely as launching over it.
    """
    refusal = lease.guard(tool)
    if refusal:
        return refusal
    return lease.stamp(_stop_game(force, timeout_s, gate=gate, tool=tool))


def _stop_game(force: bool, timeout_s: float, *, gate: Gate | None,
               tool: str) -> dict[str, Any]:
    gate = procs.gate if gate is None else gate
    started = time.monotonic()

    def done(**fields: Any) -> dict[str, Any]:
        fields.setdefault("terminated", [])
        fields.setdefault("errors", [])
        return results.ok(tool, elapsed_s=round(time.monotonic() - started, 3),
                          **fields)

    state, why = gate()
    if state == procs.NOT_RUNNING:
        return done(exited=True, pids_closed=[], forced=False, game_state=state,
                    windows_found=0,
                    detail=f"{why} There was nothing to close.")
    if state != procs.RUNNING:
        # Reported rather than refused: "I could not tell" is the answer, and
        # the caller asked a question about the machine, not for a write.
        return done(exited=False, pids_closed=[], forced=False, game_state=state,
                    windows_found=0,
                    detail=(f"{why} No window was posted to and nothing was "
                            "terminated."))

    pids = procs.game_pids()
    windows = capture.visible_windows_for_pids(pids)
    posted: list[int] = []
    errors: list[str] = []
    for window in windows:
        sent, error = capture.post_message(window["hwnd"], WM_CLOSE)
        if sent:
            posted.append(window["pid"])
        else:
            errors.append(error)
    pids_closed = sorted(set(posted))

    deadline = started + max(0.0, float(timeout_s))
    state, why = gate()
    while state == procs.RUNNING and time.monotonic() < deadline:
        time.sleep(PROCESS_POLL_S)
        state, why = gate()

    if state == procs.NOT_RUNNING:
        return done(exited=True, pids_closed=pids_closed, forced=False,
                    game_state=state, windows_found=len(windows), errors=errors,
                    detail=(f"WM_CLOSE to {len(windows)} window(s) of pid(s) "
                            f"{pids_closed} and the process exited. {why}"))

    if state != procs.RUNNING:
        # The snapshot stopped working mid-wait. Reporting "still running" here
        # would be a sentinel compared equal to a real value -- the bug
        # `AGENTS.md` § "Check a Permission Where It Is Used" names -- and the
        # force path below must not run against a PID list that is empty only
        # because nothing could be read.
        return done(exited=False, pids_closed=pids_closed, forced=False,
                    game_state=state, windows_found=len(windows), errors=errors,
                    detail=(f"WM_CLOSE was posted to {len(windows)} window(s) of "
                            f"pid(s) {pids_closed}, but whether the game exited "
                            f"can no longer be determined. {why}"))

    if not force:
        return done(exited=False, pids_closed=pids_closed, forced=False,
                    game_state=state, windows_found=len(windows), errors=errors,
                    detail=(f"WM_CLOSE was posted to {len(windows)} window(s) of "
                            f"pid(s) {pids_closed} but the process was still "
                            f"there after {timeout_s} s. The game may be showing "
                            "a confirmation prompt. force=true will terminate "
                            "it, and only for a process this server launched."))

    remaining = procs.game_pids()
    foreign = sorted(pid for pid in remaining if pid not in _LAUNCHED)
    if foreign:
        return results.refuse(
            tool, "not_launched_here",
            f"force=true will not terminate pid(s) {foreign}: this server did "
            "not start them, and killing a process someone else started can "
            "lose whatever it had not written yet. Close the game from its own "
            "window, or from Task Manager if it is wedged.",
            exited=False, pids_closed=pids_closed, forced=False,
            terminated=[], errors=errors, game_state=state,
            windows_found=len(windows), launched_here=sorted(_LAUNCHED),
            elapsed_s=round(time.monotonic() - started, 3))

    terminated: list[int] = []
    for pid in remaining:
        killed, error = terminate(pid)
        if killed:
            terminated.append(pid)
        else:
            errors.append(error)

    state, why = gate()
    if state == procs.RUNNING and terminated:
        time.sleep(PROCESS_POLL_S)
        state, why = gate()
    return done(exited=state == procs.NOT_RUNNING, pids_closed=pids_closed,
                forced=bool(terminated), terminated=terminated, errors=errors,
                game_state=state, windows_found=len(windows),
                detail=(f"The graceful close timed out, so pid(s) {terminated} "
                        f"were terminated. {why}"))
