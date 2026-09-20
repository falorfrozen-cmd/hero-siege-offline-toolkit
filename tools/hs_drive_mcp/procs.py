"""The process gate, and the machine snapshot `hs_status` reports.

The gate is tri-state on purpose. `processes()` raises `OSError` when the
Windows snapshot cannot be created or read, and the engine's own
`launch_safety_blocker()` turns that into "launch was blocked" rather than
into "nothing is running" -- the same fail direction is kept here.
`AGENTS.md` § "Check a Permission Where It Is Used" spells out why: a sentinel
that means *unknown* must never compare equal to a real value, and the save
tools ask this gate before they write. So `unknown` refuses exactly as hard as
`running` does, and the only state that lets a write through is a snapshot
that was actually taken and actually contained no game.

Matching is by image name alone. ForgePact's panel additionally matches the
full image path, because a Steam copy and an offline copy can be open at the
same time; this server reports `game_pids` and leaves that distinction to the
caller rather than guessing which one the caller meant.

`status()` lives here rather than in `server.py` because it is a snapshot of
this machine's process, anti-cheat and install state -- `server.py` stays
registration only, so the game workorder can add tools there without touching
any logic.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from . import launcher_bridge, results

GAME_IMAGE = "hero_siege.exe"

RUNNING = "running"
NOT_RUNNING = "not_running"
UNKNOWN = "unknown"


def _snapshot(engine: Any) -> list[tuple[int, str]] | None:
    """Process rows, or None when the snapshot itself failed."""
    try:
        return list(engine.processes())
    except OSError:
        return None


def game_rows(engine: Any = None) -> list[tuple[int, str]] | None:
    """Rows whose image name is the game, or None when unknown."""
    if engine is None:
        engine = launcher_bridge.load()
    if results.is_refusal(engine):
        return None
    rows = _snapshot(engine)
    if rows is None:
        return None
    return [(pid, name) for pid, name in rows if str(name).lower() == GAME_IMAGE]


def game_state(engine: Any = None) -> str:
    """`running` | `not_running` | `unknown`. Never guesses in either direction."""
    rows = game_rows(engine)
    if rows is None:
        return UNKNOWN
    return RUNNING if rows else NOT_RUNNING


def game_pids(engine: Any = None) -> list[int]:
    """PIDs of every running game image; empty when running or unknown is false."""
    rows = game_rows(engine)
    return [] if rows is None else [int(pid) for pid, _ in rows]


def gate() -> str:
    """The callable the save tools inject. A named function, so a test can see it."""
    return game_state()


def status(tool: str = "hs_status") -> dict[str, Any]:
    """Compose the report from the engine's own readings.

    Nothing here is cached. A cached "not running" is a save write against a
    live game, which is the one outcome the whole gate exists to prevent.
    """
    engine = launcher_bridge.load(tool)
    if results.is_refusal(engine):
        return engine

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
