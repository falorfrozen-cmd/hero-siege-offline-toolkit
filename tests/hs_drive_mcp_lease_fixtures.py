"""A game-lease directory of a suite's own, for every suite that calls a gated tool.

`hs_launch`, `hs_stop_game`, `hs_command`, `hs_input`, `hs_select_character`
and `hs_saves_restore` ask the machine-wide game lease (`tools/hs_drive_mcp/
lease.py`) before they do anything. Without this, those suites would read the
real `%LOCALAPPDATA%\\HSDriveMcp\\lease.json` -- and on a machine where another
session is holding the lease for a live run, every gated call in them would be
refused `lease_held` for a reason that has nothing to do with the code under
test. `HS_DRIVE_LEASE_DIR` points the lease at a temporary directory for the
whole module instead, so no suite reads or writes the real one.
"""
import os
import tempfile
import unittest
from unittest.mock import patch


def isolate_lease_dir() -> None:
    """Call from `setUpModule`. Undone by module cleanups, newest first."""
    directory = tempfile.TemporaryDirectory(prefix="hs-drive-lease-")
    unittest.addModuleCleanup(directory.cleanup)
    patcher = patch.dict(os.environ, {"HS_DRIVE_LEASE_DIR": directory.name})
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)
