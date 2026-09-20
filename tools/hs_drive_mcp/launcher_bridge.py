"""Import ForgePact's embedded launch engine. Never copy it, never edit it.

`ForgePact/src/offline_launcher.py` already owns every Win32 helper this server
needs -- the process snapshot, the EAC service query, the PE validation, the
Steam runtime lookup -- and ForgePact's own suite pins those helpers against
the HS-Offline-Launcher revision they were audited from. A second copy here
would be a third copy in the toolkit and would drift the first time one of
them was fixed, so the engine is loaded by path and used as it is.

Two things the engine deliberately does not do, because ForgePact's panel
supplies them, are filled in here instead of by falling back to another
launcher:

- **the executable's path.** `resolve_exe()` reads `game_exe` out of
  `%LOCALAPPDATA%\\Hero_Siege\\forgepact.json`, the same file
  `ForgePact/tools/ipc.ps1` reads. Nothing is ever written back: persisting a
  path into the user's own configuration is the side effect that ruled out
  HS-Offline-Launcher's module.
- **the plugin preflight.** `mod_chain()` reports the same four facts
  `ForgePact/src/forgepact.py::mod_chain()` checks. That module is not
  imported: it is a three-thousand-line panel that pulls in its own icon
  module and an optional SDK.

Importing the engine starts nothing. ForgePact's
`test_source_import_needs_no_separate_launcher_and_starts_nothing` proves that
upstream; `tests/test_hs_drive_mcp_engine_bridge.py` proves it again from this
side, because "it did not spawn anything" is the kind of claim that stops
being true quietly.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any

from . import results

#: Repo root: tools/hs_drive_mcp/launcher_bridge.py -> tools -> <root>.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Patched by the bridge test to prove the missing-source refusal fires.
ENGINE_PATH = REPO_ROOT / "ForgePact" / "src" / "offline_launcher.py"

#: The spelling used in every refusal detail, so a reader who has only the
#: message knows which checkout is incomplete.
ENGINE_RELPATH = "ForgePact/src/offline_launcher.py"

#: The engine surface this server depends on. Nine are called or read today
#: (`processes`, `eac_service_status`, `validate_game`, `_exe_facts`,
#: `launch_status`, `launch_safety_blocker`, `UPSTREAM_REVISION`,
#: `UPSTREAM_DEFINITIONS`, plus the module itself); the remaining six --
#: `launch_game`, `start_steam_if_needed`, `find_steam_runtime`,
#: `eac_is_inactive`, `LAUNCH_LOCK`, `APP_ID` -- are what `hs-drive-mcp-game`
#: will use, pinned now so a rename is caught by the suite rather than by that
#: workorder's first launch attempt.
#: `tests/test_hs_drive_mcp_engine_bridge.py` asserts every one is still
#: defined in the engine, so a ForgePact bump that renames one fails here
#: instead of at a tool call.
ENGINE_SYMBOLS = (
    "launch_game",
    "launch_status",
    "processes",
    "eac_service_status",
    "eac_is_inactive",
    "validate_game",
    "_exe_facts",
    "launch_safety_blocker",
    "find_steam_runtime",
    "start_steam_if_needed",
    "LAUNCH_LOCK",
    "EAC_PROCESS_NAMES",
    "UPSTREAM_REVISION",
    "UPSTREAM_DEFINITIONS",
    "APP_ID",
)

#: The four files ForgePact's panel checks before it will launch a modded game.
MOD_CHAIN_KEYS = ("patched", "aurieCore", "yytk", "plugin")

CONFIG_NAME = "forgepact.json"
CONFIG_KEY = "game_exe"

# Keyed by resolved path so a test that patches ENGINE_PATH gets a fresh answer
# rather than the module a previous call cached under a different path.
_LOADED: dict[str, ModuleType] = {}


def local_app_data() -> Path:
    """`%LOCALAPPDATA%`, which every test patches before it reaches here."""
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))


def config_path() -> Path:
    return local_app_data() / "Hero_Siege" / CONFIG_NAME


def load(tool: str = "engine") -> ModuleType | dict[str, Any]:
    """Return the engine module, or an `engine_source_missing` refusal.

    The submodule is frequently not checked out -- CI runs the root suite
    without any of them -- so a missing file is an expected state with a named
    reason, not a traceback.
    """
    path = Path(ENGINE_PATH)
    key = str(path)
    cached = _LOADED.get(key)
    if cached is not None:
        return cached
    if not path.is_file():
        return results.refuse(
            tool,
            "engine_source_missing",
            f"{ENGINE_RELPATH} was not found at {path}. "
            "Run `git submodule update --init ForgePact` in the toolkit checkout.",
        )
    spec = importlib.util.spec_from_file_location("offline_launcher", path)
    if spec is None or spec.loader is None:
        return results.refuse(
            tool,
            "engine_source_missing",
            f"{ENGINE_RELPATH} at {path} could not be loaded as a Python module.",
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _LOADED[key] = module
    return module


def read_config() -> dict[str, Any]:
    """Read ForgePact's panel configuration. Mocked in the status test."""
    path = config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_exe(tool: str = "hs_status") -> Path | dict[str, Any]:
    """The game executable ForgePact was last pointed at, or a refusal.

    Read-only by construction: this server never writes `forgepact.json`.
    """
    config = read_config()
    raw = config.get(CONFIG_KEY)
    if not raw:
        return results.refuse(
            tool,
            "forgepact_config_missing",
            f"{CONFIG_KEY!r} is not set in {config_path()}. "
            "Open the ForgePact panel once and select the game location.",
        )
    return Path(str(raw))


def mod_chain(exe: Path | None) -> dict[str, bool]:
    """The four install facts, all False when the executable is unknown.

    `patched` is read from the PE section table through the engine's own
    `_exe_facts`, which is where ForgePact reads it too -- the `.aurie` section
    is what AuriePatcher adds, so it is a property of the file rather than of
    anything this server remembers.
    """
    chain = dict.fromkeys(MOD_CHAIN_KEYS, False)
    if exe is None:
        return chain
    engine = load()
    if results.is_refusal(engine):
        return chain
    exe = Path(exe)
    if exe.is_file():
        try:
            chain["patched"] = ".aurie" in engine._exe_facts(exe)["sections"]
        except OSError:
            chain["patched"] = False
    aurie = exe.parent / "mods" / "aurie"
    chain["aurieCore"] = (exe.parent / "AurieCore.dll").is_file()
    chain["yytk"] = (aurie / "YYToolkit.dll").is_file()
    chain["plugin"] = (aurie / "BloodPactPlugin.dll").is_file()
    return chain


def ipc_dir(exe: Path | None) -> Path | None:
    """ForgePact's file IPC directory, beside the executable."""
    return None if exe is None else Path(exe).parent / "bp_ipc"
