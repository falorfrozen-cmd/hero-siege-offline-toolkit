"""The bridge to ForgePact's launch engine: pinned names, and no side effects.

Two claims are made every time this server starts, and both stop being true
quietly rather than loudly:

1. **The engine still defines what we call.** A ForgePact pointer bump that
   renames `launch_safety_blocker` would otherwise surface as an
   `AttributeError` at the first tool call, on the owner's machine, mid-task.
   `ENGINE_SYMBOLS` is asserted against the source text itself.
2. **Importing it starts nothing.** ForgePact's own
   `test_source_import_needs_no_separate_launcher_and_starts_nothing` proves
   this upstream; it is proved again from this side because the whole reason
   this server may import a launcher is that importing it is inert.

Nothing here is edited under `ForgePact/` -- the engine is read and imported,
never modified.
"""
import ast
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENGINE_RELPATH = "ForgePact/src/offline_launcher.py"
ENGINE_SOURCE = ROOT / "ForgePact" / "src" / "offline_launcher.py"

SKIP_REASON = None
if os.name != "nt":
    SKIP_REASON = (f"the engine imports ctypes.wintypes; os.name is "
                   f"{os.name!r}, so it cannot be loaded here")
elif not ENGINE_SOURCE.is_file():
    SKIP_REASON = (f"{ENGINE_SOURCE} is absent; run "
                   "`git submodule update --init ForgePact`")

from tools.hs_drive_mcp import launcher_bridge, results  # noqa: E402


def top_level_names(source: Path) -> set[str]:
    """Every name bound at module level, without importing the module."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets
                         if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class EngineSymbolTests(unittest.TestCase):
    """The pin, read off the source rather than off a loaded module."""

    def test_every_pinned_name_is_defined_in_the_engine(self):
        defined = top_level_names(ENGINE_SOURCE)
        missing = [name for name in launcher_bridge.ENGINE_SYMBOLS if name not in defined]
        self.assertEqual(missing, [],
                         f"{ENGINE_RELPATH} no longer defines {missing}; "
                         "ENGINE_SYMBOLS is stale against the ForgePact pointer")

    def test_the_pin_is_not_empty_and_has_no_duplicates(self):
        symbols = launcher_bridge.ENGINE_SYMBOLS
        self.assertTrue(symbols, "an empty pin would assert nothing")
        self.assertEqual(len(set(symbols)), len(symbols))

    def test_the_loaded_module_resolves_every_pinned_name(self):
        engine = launcher_bridge.load()
        self.assertFalse(results.is_refusal(engine), engine)
        for name in launcher_bridge.ENGINE_SYMBOLS:
            self.assertTrue(hasattr(engine, name), name)


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class InertImportTests(unittest.TestCase):
    """Loading the engine must not start anything."""

    def test_loading_the_bridge_spawns_no_process_and_starts_no_thread(self):
        with patch.object(launcher_bridge, "_LOADED", {}), \
             patch.object(subprocess, "Popen") as spawn, \
             patch.object(threading, "Thread") as thread:
            engine = launcher_bridge.load()
            self.assertFalse(results.is_refusal(engine), engine)
        spawn.assert_not_called()
        thread.assert_not_called()


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class MissingSourceTests(unittest.TestCase):
    """A checkout without the submodule refuses by name, it does not traceback."""

    def test_a_missing_engine_source_is_a_named_refusal(self):
        absent = ROOT / "ForgePact" / "src" / "offline_launcher-does-not-exist.py"
        with patch.object(launcher_bridge, "_LOADED", {}), \
             patch.object(launcher_bridge, "ENGINE_PATH", absent):
            refusal = launcher_bridge.load("hs_status")
        self.assertTrue(results.is_refusal(refusal), refusal)
        self.assertEqual(refusal["reason"], "engine_source_missing")
        self.assertIn(ENGINE_RELPATH, refusal["detail"])
        self.assertIn(str(absent), refusal["detail"])

    def test_the_mod_chain_reports_four_false_facts_without_the_engine(self):
        absent = ROOT / "ForgePact" / "src" / "offline_launcher-does-not-exist.py"
        with patch.object(launcher_bridge, "_LOADED", {}), \
             patch.object(launcher_bridge, "ENGINE_PATH", absent):
            chain = launcher_bridge.mod_chain(ROOT / "nowhere" / "Hero_Siege.exe")
        self.assertEqual(sorted(chain), ["aurieCore", "patched", "plugin", "yytk"])
        self.assertEqual(set(chain.values()), {False})


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class ConfigReadTests(unittest.TestCase):
    """`resolve_exe` reads ForgePact's panel config and never writes it."""

    def test_a_missing_configuration_is_a_named_refusal(self):
        with patch.object(launcher_bridge, "read_config", return_value={}):
            refusal = launcher_bridge.resolve_exe()
        self.assertTrue(results.is_refusal(refusal), refusal)
        self.assertEqual(refusal["reason"], "forgepact_config_missing")
        self.assertIn("game_exe", refusal["detail"])

    def test_a_configured_path_is_returned_unchanged(self):
        wanted = ROOT / "somewhere" / "bin" / "Hero_Siege.exe"
        with patch.object(launcher_bridge, "read_config",
                          return_value={"game_exe": str(wanted)}):
            self.assertEqual(launcher_bridge.resolve_exe(), wanted)


if __name__ == "__main__":
    unittest.main()
