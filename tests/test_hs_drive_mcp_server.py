"""The `hs-drive` MCP server, driven over its real stdio transport.

The tool surface is asserted through an actual client session started with the
exact argv `.mcp.json` carries, from the repo root, because a tool list that is
right in the module and wrong over the wire is the failure this server would
otherwise ship: `list_tools` is what a model sees, not the decorator.

`hs_status` is asserted in process instead. A stdio server is a separate
operating-system process, so nothing in this file could mock the engine inside
it -- and the tri-state gate's whole point is what it does when the process
snapshot *fails*, which cannot be arranged from outside.

The subprocess runs with `HS_DRIVE_SAVE_DIR` and `HS_DRIVE_BACKUP_DIR` pointed
at a fixture tree, so not even the read-only checks reach the real
`hs2saves\\`.

**`LOCALAPPDATA` is deliberately *not* overridden for the subprocess**, though
the in-process tests do override it. The `py` launcher keeps its installed
runtimes under `%LOCALAPPDATA%\\Python`; with that variable repointed at a temp
directory it concludes no runtime is installed, starts downloading one, and
writes `Downloading: ...` to **stdout** -- which on a stdio transport is the
protocol channel, so the client dies on `Invalid JSON: expected value at line 1
column 1`. Measured here on 2026-09-20. The two `HS_DRIVE_*` overrides already
redirect everything this server writes; `LOCALAPPDATA` is only read beyond them
for ForgePact's `forgepact.json`, which is read-only.
"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENGINE_SOURCE = ROOT / "ForgePact" / "src" / "offline_launcher.py"

#: The argv `.mcp.json` carries, and what the acceptance criteria pin.
SERVER_ARGV = ["-3", "-m", "tools.hs_drive_mcp"]

EXPECTED_TOOLS = {
    "hs_status", "hs_selfcheck", "hs_saves_backup",
    "hs_saves_restore", "hs_saves_list", "hs_saves_inspect",
}

EXPECTED_CHECKS = [
    "engine_import", "process_snapshot", "eac_service", "save_dir", "backup_roundtrip",
]

#: `save_dir` is left out on purpose: it reports on whatever directory the
#: environment points at, which is a fixture here, so it is asserted by name
#: below rather than by its status.
MUST_PASS_ON_WINDOWS = ["engine_import", "process_snapshot", "eac_service", "backup_roundtrip"]

SKIP_REASON = None
if os.name != "nt":
    SKIP_REASON = f"the hs-drive server is Windows-only; os.name is {os.name!r}"
elif not ENGINE_SOURCE.is_file():
    SKIP_REASON = (f"{ENGINE_SOURCE} is absent; run "
                   "`git submodule update --init ForgePact`")
else:
    try:
        import mcp  # noqa: F401
        import PIL  # noqa: F401
    except ImportError as exc:
        SKIP_REASON = (f"{exc.name} is not installed; run "
                       "`py -3 -m pip install -r tools/hs_drive_mcp/requirements.txt`")


def fixture_environment(base: Path) -> dict[str, str]:
    """A temporary save dir and backup root. See the module docstring for why
    `LOCALAPPDATA` is left alone for a subprocess started through `py`."""
    live = base / "hs2saves"
    live.mkdir(parents=True, exist_ok=True)
    (live / "herosiege1.hss").write_bytes(b"fixture character")
    (live / "shop.ini").write_bytes(b"[shop]\n")
    environment = dict(os.environ)
    environment.update({
        "HS_DRIVE_SAVE_DIR": str(live),
        "HS_DRIVE_BACKUP_DIR": str(base / "save-backups"),
        "PYTHONIOENCODING": "utf-8",
    })
    return environment


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class StdioSurfaceTests(unittest.TestCase):
    """A3/A4 -- what a client actually receives from the running server."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="hs-drive-server-")
        base = Path(cls.temp.name).resolve()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.tools, cls.selfcheck = asyncio.run(cls.interrogate(fixture_environment(base)))

    @staticmethod
    async def interrogate(environment):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        parameters = StdioServerParameters(
            command="py", args=SERVER_ARGV, cwd=str(ROOT), env=environment)
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                checked = await session.call_tool("hs_selfcheck")
                return listed.tools, checked

    def test_the_six_tools_of_this_workorder_are_registered(self):
        self.assertEqual({tool.name for tool in self.tools}, EXPECTED_TOOLS)

    def test_every_tool_carries_a_title_and_both_behaviour_hints(self):
        destructive = []
        for tool in self.tools:
            self.assertIsNotNone(tool.annotations, f"{tool.name} has no annotations")
            hints = tool.annotations.model_dump(by_alias=True)
            self.assertTrue(hints.get("title"), f"{tool.name} has no annotation title")
            self.assertIsInstance(hints.get("readOnlyHint"), bool,
                                  f"{tool.name} does not set readOnlyHint")
            self.assertIsInstance(hints.get("destructiveHint"), bool,
                                  f"{tool.name} does not set destructiveHint")
            if hints["destructiveHint"]:
                destructive.append(tool.name)
        self.assertEqual(destructive, ["hs_saves_restore"])

    def test_the_selfcheck_reports_every_instrument_by_name(self):
        self.assertFalse(self.selfcheck.is_error, self.selfcheck)
        payload = self.selfcheck.structured_content
        self.assertIsNotNone(payload, "hs_selfcheck returned no structured output")
        rows = {row["name"]: row for row in payload["checks"]}
        self.assertEqual(sorted(rows), sorted(EXPECTED_CHECKS))
        for name, row in rows.items():
            self.assertIn(row["status"], {"pass", "fail", "skipped"}, name)
            self.assertTrue(row["detail"].strip(), f"{name} reported no detail")

    def test_the_instruments_this_machine_can_prove_actually_pass(self):
        rows = {row["name"]: row for row in self.selfcheck.structured_content["checks"]}
        for name in MUST_PASS_ON_WINDOWS:
            self.assertEqual(rows[name]["status"], "pass",
                             f"{name}: {rows[name]['detail']}")


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class StatusCompositionTests(unittest.TestCase):
    """A7 -- hs_status, with the engine's readings under the test's control."""

    def setUp(self):
        from tools.hs_drive_mcp import launcher_bridge, procs, results
        self.procs, self.bridge, self.results = procs, launcher_bridge, results
        engine = launcher_bridge.load()
        self.assertFalse(results.is_refusal(engine), engine)
        self.engine = engine

        self.temp = tempfile.TemporaryDirectory(prefix="hs-drive-status-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.exe = self.root / "game" / "bin" / "Hero_Siege.exe"
        self.exe.parent.mkdir(parents=True)
        self.exe.write_bytes(b"not a real PE, and that is the point")
        aurie = self.exe.parent / "mods" / "aurie"
        aurie.mkdir(parents=True)
        for path in (self.exe.parent / "AurieCore.dll",
                     aurie / "YYToolkit.dll", aurie / "BloodPactPlugin.dll"):
            path.write_bytes(b"mod fixture")
        (self.exe.parent / "bp_ipc").mkdir()

        self.enterContext(patch.object(self.engine, "eac_service_status",
                                       return_value="stopped"))
        self.enterContext(patch.object(self.engine, "EXE_FACTS_CACHE", {}))
        self.enterContext(patch.object(launcher_bridge, "read_config",
                                       return_value={"game_exe": str(self.exe)}))

    def status(self, rows=None, error=None):
        if error is not None:
            context = patch.object(self.engine, "processes", side_effect=error)
        else:
            context = patch.object(self.engine, "processes", return_value=rows)
        with context:
            return self.procs.status()

    def test_a_running_game_is_reported_with_its_pids(self):
        report = self.status(rows=[(1, "steam.exe"), (42, "Hero_Siege.exe")])
        self.assertEqual(report["game_state"], "running")
        self.assertEqual(report["game_pids"], [42])

    def test_no_game_row_is_not_running(self):
        report = self.status(rows=[(1, "steam.exe")])
        self.assertEqual(report["game_state"], "not_running")
        self.assertEqual(report["game_pids"], [])

    def test_a_failed_process_snapshot_is_unknown_and_never_not_running(self):
        report = self.status(error=OSError("Windows process snapshot could not be created"))
        self.assertEqual(report["game_state"], "unknown")
        self.assertNotEqual(report["game_state"], "not_running")
        self.assertEqual(report["game_pids"], [])

    def test_the_report_carries_every_documented_field(self):
        report = self.status(rows=[(1, "steam.exe")])
        for key in ("game_state", "game_pids", "eac_service", "exe_path",
                    "exe_valid", "exe_validation", "mod_chain", "ipc_dir",
                    "bp_ipc_exists", "launch"):
            self.assertIn(key, report)
        self.assertEqual(report["eac_service"], "stopped")
        self.assertEqual(report["exe_path"], str(self.exe))
        self.assertIsInstance(report["exe_valid"], bool)
        self.assertTrue(report["exe_validation"])
        self.assertEqual(sorted(report["mod_chain"]),
                         ["aurieCore", "patched", "plugin", "yytk"])
        for name, value in report["mod_chain"].items():
            self.assertIsInstance(value, bool, name)
        self.assertTrue(report["mod_chain"]["aurieCore"])
        self.assertTrue(report["mod_chain"]["yytk"])
        self.assertTrue(report["mod_chain"]["plugin"])
        self.assertFalse(report["mod_chain"]["patched"],
                         "a file that is not a PE cannot carry an .aurie section")
        self.assertEqual(report["ipc_dir"], str(self.exe.parent / "bp_ipc"))
        self.assertTrue(report["bp_ipc_exists"])
        self.assertIn("phase", report["launch"])

    def test_a_missing_panel_configuration_reports_instead_of_refusing(self):
        with patch.object(self.bridge, "read_config", return_value={}):
            report = self.status(rows=[(1, "steam.exe")])
        self.assertTrue(report["ok"])
        self.assertIsNone(report["exe_path"])
        self.assertFalse(report["exe_valid"])
        self.assertIn("forgepact.json", report["exe_validation"])
        self.assertEqual(set(report["mod_chain"].values()), {False})
        self.assertIsNone(report["ipc_dir"])
        self.assertFalse(report["bp_ipc_exists"])


if __name__ == "__main__":
    unittest.main()
