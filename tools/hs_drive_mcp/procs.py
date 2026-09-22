"""The process gate, and the machine snapshot `hs_status` reports.

The gate never guesses. `processes()` raises `OSError` when the Windows
snapshot cannot be created or read, and the engine's own
`launch_safety_blocker()` turns that into "launch was blocked" rather than
into "nothing is running" -- the same fail direction is kept here.
`AGENTS.md` § "Check a Permission Where It Is Used" spells out why: a sentinel
that means *unknown* must never compare equal to a real value, and the save
tools ask this gate before they write. So `unknown` refuses exactly as hard as
`running` does, and the only state that lets a write through is a snapshot
that was actually taken and actually contained no game.

For the same reason the gate has **four** states rather than three: a checkout
without `ForgePact/` has no engine to take a snapshot with, which is neither
`unknown` in the Win32 sense nor anything a `sc` query could answer. It is
`engine_missing`, it refuses just as hard, and it names the one command that
fixes it. `game_state()` still reports the tri-state `hs_status` was specified
against; the extra state exists so a refusal cannot name a subsystem that was
never reached.

Matching is by image name alone. ForgePact's panel additionally matches the
full image path, because a Steam copy and an offline copy can be open at the
same time; this server reports `game_pids` and leaves that distinction to the
caller rather than guessing which one the caller meant.

`status()` lives here rather than in `server.py` because it is a snapshot of
this machine's process, anti-cheat and install state -- `server.py` stays
registration only, which is how the launch, IPC and screenshot tools were added
there without touching any logic.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from . import launcher_bridge, results

GAME_IMAGE = "hero_siege.exe"

RUNNING = "running"
NOT_RUNNING = "not_running"
UNKNOWN = "unknown"

#: A fourth gate state, and deliberately not a fourth `game_state()`.
#:
#: "the snapshot failed" and "there is no engine to take a snapshot with" are
#: different machine states with different fixes -- one is a Win32 failure, the
#: other is `git submodule update --init ForgePact`. Collapsing them into
#: `unknown` made the save tools refuse with a detail naming a Win32 call that
#: was never attempted, while `hs_status`, which asks the bridge directly,
#: correctly said `engine_source_missing`. Two tools disagreeing about one
#: machine is the bug; both refuse either way, but a refusal that names the
#: wrong subsystem costs a session.
ENGINE_MISSING = "engine_missing"

#: And a fifth, for an engine file that is present but will not import -- a
#: partial checkout, a Python that cannot load `ctypes.wintypes`. Same argument
#: as above: the fix is not the one `engine_missing` names, so it does not
#: borrow that name.
ENGINE_UNUSABLE = "engine_unusable"

#: What a gate may return. Only `not_running` lets a write through.
GATE_STATES = (RUNNING, NOT_RUNNING, UNKNOWN, ENGINE_MISSING, ENGINE_UNUSABLE)


def _snapshot(engine: Any) -> list[tuple[int, str]] | None:
    """Process rows, or None when the snapshot itself failed."""
    try:
        return list(engine.processes())
    except OSError:
        return None


def load_engine() -> tuple[Any, str, str]:
    """(engine, blocking state, why). `state` is empty when the engine loaded.

    The one place the engine is obtained, so the gate and `hs_status` cannot
    describe the same machine differently -- which is the defect this module
    has now been corrected for twice.
    """
    try:
        engine = launcher_bridge.load()
    except Exception as exc:  # noqa: BLE001 - an unimportable engine is a state
        return None, ENGINE_UNUSABLE, (
            f"{launcher_bridge.ENGINE_RELPATH} is present but could not be "
            f"imported ({type(exc).__name__}: {exc}).")
    if results.is_refusal(engine):
        return None, ENGINE_MISSING, engine["detail"]
    return engine, "", ""


def _readings(engine: Any = None) -> tuple[str, str, list[tuple[int, str]]]:
    """(state, why, matching rows). The one place the distinction is made."""
    if engine is None:
        engine, blocked, why = load_engine()
        if blocked:
            return blocked, why, []
    if results.is_refusal(engine):
        return ENGINE_MISSING, engine["detail"], []
    if os.name != "nt":
        # The engine's processes() returns [] off Windows rather than raising.
        # Reading that as "not running" would be the sentinel-equals-real-value
        # bug this module's docstring says it does not have.
        return UNKNOWN, (
            f"the Windows process table cannot be read on os.name {os.name!r}, "
            "so whether the game is running is unknown."), []
    rows = _snapshot(engine)
    if rows is None:
        return UNKNOWN, (
            "the Windows process snapshot could not be created or read, so "
            "whether the game is running is unknown."), []
    matches = [(int(pid), str(name)) for pid, name in rows
               if str(name).lower() == GAME_IMAGE]
    if matches:
        return RUNNING, (f"{len(matches)} {GAME_IMAGE} process(es) are live: "
                         f"{[pid for pid, _ in matches]}."), matches
    return NOT_RUNNING, (f"the process snapshot returned {len(rows)} rows and "
                         f"none of them is {GAME_IMAGE}."), []


def game_state_detail(engine: Any = None) -> tuple[str, str]:
    """The gate state and, in words, how it was arrived at."""
    state, why, _ = _readings(engine)
    return state, why


def game_rows(engine: Any = None) -> list[tuple[int, str]] | None:
    """Rows whose image name is the game, or None when the state is not known."""
    state, _, matches = _readings(engine)
    return matches if state in (RUNNING, NOT_RUNNING) else None


def game_state(engine: Any = None) -> str:
    """`running` | `not_running` | `unknown` -- the tri-state `hs_status` reports.

    The two engine states collapse to `unknown` here on purpose: `hs_status`
    asks for the engine before it ever reaches this function and returns
    `engine_source_missing` / `engine_import_failed` itself, so this field
    keeps the shape its callers and its acceptance criterion were written
    against.
    """
    state, _, _ = _readings(engine)
    return UNKNOWN if state in (ENGINE_MISSING, ENGINE_UNUSABLE) else state


def game_pids(engine: Any = None) -> list[int]:
    """PIDs of every running game image; empty unless the state is `running`."""
    rows = game_rows(engine)
    return [] if rows is None else [int(pid) for pid, _ in rows]


def gate() -> tuple[str, str]:
    """The callable the save tools inject: `(state, why)`.

    The gate cannot answer without also saying how it arrived there. That is
    not decoration -- it is what makes "the refusal names the subsystem that
    actually failed" true by construction rather than by each caller
    remembering to re-derive it. Twice now the reason has been recomputed at
    the point of refusal and got it wrong, so the reason travels with the
    answer instead.

    `state` is one of `GATE_STATES`; only `not_running` lets a write through.
    """
    return game_state_detail()


def status(tool: str = "hs_status") -> dict[str, Any]:
    """Compose the report from the engine's own readings.

    Nothing here is cached. A cached "not running" is a save write against a
    live game, which is the one outcome the whole gate exists to prevent.
    """
    engine, blocked, why = load_engine()
    if blocked == ENGINE_MISSING:
        return results.refuse(tool, "engine_source_missing", why)
    if blocked:
        # Present but unimportable. A traceback across the transport is not a
        # result a caller can branch on; this module's own rule is that a
        # refusal is never an exception.
        return results.refuse(
            tool, "engine_import_failed",
            f"{why} Reinstall or re-check out ForgePact, and confirm this "
            "Python can import ctypes.wintypes on this platform.")

    state = game_state(engine)
    pids = game_pids(engine)

    try:
        eac = engine.eac_service_status()
    except OSError as exc:
        eac = f"unknown ({type(exc).__name__})"

    exe = launcher_bridge.resolve_exe(tool)
    if results.is_refusal(exe):
        exe_path: Path | None = None
        exe_valid = False
        exe_validation = exe["detail"]
    else:
        exe_path = exe
        # use_cache=False: this reading is what a caller decides from, and a
        # status poll's memory of the file is not the file.
        exe_valid, exe_validation = engine.validate_game(exe_path, use_cache=False)

    directory = launcher_bridge.ipc_dir(exe_path)
    return results.ok(
        tool,
        game_state=state,
        game_pids=pids,
        eac_service=eac,
        exe_path=None if exe_path is None else str(exe_path),
        exe_valid=bool(exe_valid),
        exe_validation=str(exe_validation),
        mod_chain=launcher_bridge.mod_chain(exe_path),
        ipc_dir=None if directory is None else str(directory),
        bp_ipc_exists=bool(directory is not None and directory.is_dir()),
        launch=dict(engine.launch_status()),
    )


#: The gate signature the save tools take, spelled once so both ends agree.
Gate = Callable[[], str]
