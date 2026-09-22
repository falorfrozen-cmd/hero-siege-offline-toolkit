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

#: The twelve the core and game workorders shipped, kept as their own set so
#: the regression "a later workorder registers one and drops another" is
#: asserted separately from the current total.
CORE_AND_GAME_TOOLS = {
    # hs-drive-mcp-core
    "hs_status", "hs_selfcheck", "hs_saves_backup",
    "hs_saves_restore", "hs_saves_list", "hs_saves_inspect",
    # hs-drive-mcp-game
    "hs_launch", "hs_wait_ready", "hs_stop_game",
    "hs_command", "hs_ipc_tail", "hs_screenshot",
}

#: Plus `hs_input`, from `hs-drive-mcp-charselect`.
THIRTEEN_TOOLS = CORE_AND_GAME_TOOLS | {"hs_input"}

#: Plus `hs_select_character`, from `hs-drive-mcp-charselect-ship`.
EXPECTED_TOOLS = THIRTEEN_TOOLS | {"hs_select_character"}

#: Two tools can take away something that was not theirs: a restore overwrites
#: the live save directory, and a forced stop terminates a process. Everything
#: else writes only files of its own.
EXPECTED_DESTRUCTIVE = {"hs_saves_restore", "hs_stop_game"}

#: `readOnlyHint` is the flag a client auto-approves on without prompting, so
#: it is the one annotation a tool must not overstate. Nothing in this set may
#: write anywhere but a temporary directory of its own -- which is why the
#: plugin ping is not a self-check any more: it wrote into the live install's
#: `bp_ipc\\cmd.txt`, and an unconsumed ping is left there for the game to run
#: at its next start.
EXPECTED_READ_ONLY = {"hs_status", "hs_selfcheck", "hs_saves_list",
                      "hs_saves_inspect", "hs_ipc_tail"}

#: Every registered check, in registry order. Asserted as a whole rather than
#: by absence, so a check that writes into the live game directory cannot be
#: registered again under a different name.
EXPECTED_CHECKS = [
    "engine_import", "process_snapshot", "eac_service", "save_dir",
    "backup_roundtrip", "screenshot_screen",
]

#: `save_dir` is left out on purpose: it reports on whatever directory the
#: environment points at, which is a fixture here, so it is asserted by name
#: below rather than by its status.
MUST_PASS_ON_WINDOWS = ["engine_import", "process_snapshot", "eac_service",
                        "backup_roundtrip", "screenshot_screen"]

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

    def test_all_twelve_tools_are_registered(self):
        """Baseline: none of the original twelve went away.

        Kept under its original name now that `hs_input` makes the total
        thirteen, because the regression it catches is the one a rename would
        hide -- a later workorder registering its own tool and quietly
        dropping one of these.
        """
        missing = CORE_AND_GAME_TOOLS - {tool.name for tool in self.tools}
        self.assertEqual(missing, set())
        self.assertEqual(len(CORE_AND_GAME_TOOLS), 12)

    def test_all_thirteen_tools_are_registered(self):
        """Baseline: none of the thirteen `hs-drive-mcp-charselect` shipped
        went away. Kept under its old name now that `hs_select_character`
        makes the total fourteen, for the same reason
        `test_all_twelve_tools_are_registered` was kept: the regression this
        catches is a later workorder registering its own tool and quietly
        dropping one of these.
        """
        missing = THIRTEEN_TOOLS - {tool.name for tool in self.tools}
        self.assertEqual(missing, set())
        self.assertEqual(len(THIRTEEN_TOOLS), 13)

    def test_all_fourteen_tools_are_registered(self):
        self.assertEqual({tool.name for tool in self.tools}, EXPECTED_TOOLS)
        self.assertEqual(len(self.tools), 14)

    def test_hs_input_is_not_read_only_not_destructive_not_idempotent(self):
        """All three false, and each for its own reason.

        Not read-only: it injects events into a live game. Not destructive:
        it removes nothing and writes no file -- claiming otherwise would put
        it in the same class as a save restore and devalue that claim. Not
        idempotent: sending the same click twice is two clicks.
        """
        tool = next(tool for tool in self.tools if tool.name == "hs_input")
        hints = tool.annotations.model_dump(by_alias=True)
        self.assertFalse(hints["readOnlyHint"])
        self.assertFalse(hints["destructiveHint"])
        self.assertFalse(hints["idempotentHint"])

    def test_hs_select_character_is_not_read_only_not_destructive_not_idempotent(self):
        """Not read-only: it injects clicks and sends IPC commands. Not
        destructive: it removes nothing and writes no file of its own. Not
        idempotent: calling it again after a character is loaded is a
        different sequence, not a repeat of this one."""
        tool = next(tool for tool in self.tools
                   if tool.name == "hs_select_character")
        hints = tool.annotations.model_dump(by_alias=True)
        self.assertFalse(hints["readOnlyHint"])
        self.assertFalse(hints["destructiveHint"])
        self.assertFalse(hints["idempotentHint"])

    def test_hs_select_character_slot_is_one_based_and_clicks_no_fraction(self):
        """The published schema refuses `slot < 1` before the tool runs
        (`ge=1`), and the description no longer promises fixed fractions or
        a 16:9-only client: every point comes from the `menulayout`
        listing now."""
        tool = next(tool for tool in self.tools
                   if tool.name == "hs_select_character")
        schema = tool.model_dump(by_alias=True)["inputSchema"]
        slot = schema["properties"]["slot"]
        self.assertEqual(slot.get("minimum"), 1, schema)
        self.assertIn("menulayout", tool.description)
        for stale in ("fraction", "16:9", "measured"):
            self.assertNotIn(stale, tool.description)
            self.assertNotIn(stale, slot["description"])

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
        self.assertEqual(set(destructive), EXPECTED_DESTRUCTIVE)

    def test_the_read_only_tools_are_exactly_the_documented_five(self):
        """Baseline: the read-only set, over the wire, as a client sees it.

        `test_every_tool_carries_a_title_and_both_behaviour_hints` pins only the
        destructive set, so nothing pinned the read-only claim -- which is how a
        check that writes into the live game directory ended up behind
        `readOnlyHint: true`.
        """
        read_only = {tool.name for tool in self.tools
                     if tool.annotations.model_dump(by_alias=True)["readOnlyHint"]}
        self.assertEqual(read_only, EXPECTED_READ_ONLY)

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


class SelfCheckSideEffectTests(unittest.TestCase):
    """A read-only tool must be read-only against a *running* game too.

    `hs_selfcheck` carries `readOnlyHint: true`, which is what a client uses to
    auto-approve without prompting -- and a plugin-ping check registered here
    appended a `ping` into the live install's `bp_ipc\\cmd.txt` and made the
    running plugin execute it. An unconsumed one was deliberately left on disk,
    so the game ran it at its *next* start: a delayed write, from a tool a
    session was told to run first and would never be prompted about.

    The whole **real** registry runs here, against a fixture install a patched
    gate reports as running -- the one arrangement in which that write happened.
    Like `SelfCheckSummaryTests` it needs neither Windows nor the MCP SDK: the
    gate is patched and every path is a temporary directory.
    """

    def setUp(self):
        from tools.hs_drive_mcp import launcher_bridge, procs
        temp = tempfile.TemporaryDirectory(prefix="hs-drive-selfcheck-writes-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()

        self.exe = self.base / "game" / "bin" / "Hero_Siege.exe"
        self.exe.parent.mkdir(parents=True)
        self.exe.write_bytes(b"not a real PE, and nothing here reads it")
        self.ipc_dir = self.exe.parent / "bp_ipc"
        self.ipc_dir.mkdir()

        live = self.base / "hs2saves"
        live.mkdir()
        (live / "herosiege1.hss").write_bytes(b"fixture character")

        self.enterContext(patch.object(launcher_bridge, "read_config",
                                       return_value={"game_exe": str(self.exe)}))
        self.enterContext(patch.object(
            procs, "gate",
            lambda: ("running", "1 hero_siege.exe process(es) are live: [4242].")))
        self.enterContext(patch.dict(os.environ, {
            "HS_DRIVE_SAVE_DIR": str(live),
            "HS_DRIVE_BACKUP_DIR": str(self.base / "save-backups")}))

    def test_the_selfcheck_writes_nothing_into_bp_ipc_even_with_the_game_running(self):
        from tools.hs_drive_mcp import checks
        report = checks.run_checks()
        self.assertTrue(report["ok"], report)
        left = sorted(path.name for path in self.ipc_dir.iterdir())
        self.assertEqual(left, [],
                         f"hs_selfcheck wrote {left} into the live install's "
                         "bp_ipc while annotated readOnlyHint=true")
        # The whole registry, not the absence of one name: a check that writes
        # into the live install must not come back under a different one.
        self.assertEqual([name for name, _, _ in checks.registered()],
                         EXPECTED_CHECKS,
                         "the registry changed; hs_wait_ready is the one "
                         "instrument for the plugin's ping, because it is the "
                         "one annotated as writing something")


class SelfCheckSummaryTests(unittest.TestCase):
    """`summary.healthy` must never be true on a run that proved nothing.

    This is the instrument reporting on itself, so it is the one place where
    "armed but blind" cannot be caught by anything downstream. It needs neither
    Windows nor the SDK -- the registry is replaced with stub checks -- so it
    runs everywhere, including on the CI image where the real checks would all
    be skipped.
    """

    @staticmethod
    def registry(*rows):
        from tools.hs_drive_mcp import checks
        entries = [(name, (lambda s=status, d=detail: (s, d)), control)
                   for name, status, detail, control in rows]
        return patch.object(checks, "_REGISTRY", entries)

    def run_with(self, *rows):
        from tools.hs_drive_mcp import checks
        with self.registry(*rows):
            return checks.run_checks()

    def test_an_all_skipped_run_is_not_healthy(self):
        report = self.run_with(
            ("process_snapshot", "skipped", "not Windows", True),
            ("backup_roundtrip", "skipped", "not Windows", True),
            ("save_dir", "skipped", "no directory", False))
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertFalse(report["summary"]["healthy"],
                         "a run that proved nothing reported itself healthy")
        self.assertEqual(report["summary"]["positive_controls_proven"], [])

    def test_a_skipped_positive_control_alone_is_enough_to_withhold_healthy(self):
        report = self.run_with(
            ("process_snapshot", "pass", "saw own pid", True),
            ("backup_roundtrip", "skipped", "no temp space", True),
            ("save_dir", "pass", "137 files", False))
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertFalse(report["summary"]["healthy"])
        self.assertEqual(report["summary"]["positive_controls_proven"],
                         ["process_snapshot"])

    def test_every_control_passing_and_nothing_failing_is_healthy(self):
        report = self.run_with(
            ("process_snapshot", "pass", "saw own pid", True),
            ("backup_roundtrip", "pass", "byte-identical", True),
            ("eac_service", "skipped", "not Windows", False))
        self.assertTrue(report["summary"]["healthy"])
        self.assertEqual(report["summary"]["positive_controls"],
                         ["process_snapshot", "backup_roundtrip"])

    def test_a_failure_anywhere_withholds_healthy(self):
        report = self.run_with(
            ("process_snapshot", "pass", "saw own pid", True),
            ("backup_roundtrip", "pass", "byte-identical", True),
            ("engine_import", "fail", "no such file", False))
        self.assertFalse(report["summary"]["healthy"])

    def test_a_registry_with_no_positive_control_is_never_healthy(self):
        report = self.run_with(("save_dir", "pass", "137 files", False))
        self.assertFalse(report["summary"]["healthy"],
                         "nothing was pointed at a known-present target")

    def test_a_raising_check_is_a_fail_naming_the_exception(self):
        from tools.hs_drive_mcp import checks

        def explode():
            raise RuntimeError("the instrument broke")

        with patch.object(checks, "_REGISTRY",
                          [("process_snapshot", explode, True)]):
            report = checks.run_checks()
        row = report["checks"][0]
        self.assertEqual(row["status"], "fail",
                         "a check that raised must never be reported as skipped")
        self.assertIn("RuntimeError", row["detail"])
        self.assertFalse(report["summary"]["healthy"])

    def test_the_real_registry_marks_every_positive_control(self):
        from tools.hs_drive_mcp import checks
        self.assertEqual(checks.positive_controls(),
                         ["process_snapshot", "backup_roundtrip",
                          "screenshot_screen"])
        self.assertTrue(set(checks.positive_controls()) <= set(EXPECTED_CHECKS),
                        "a control that is not a registered check cannot have "
                        "run, so `healthy` would rest on nothing")


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class SelectCharacterDocstringTests(unittest.TestCase):
    """`hs_select_character`'s docstring is the contract a caller reads over
    the wire (its MCP `description` is the short blurb; the Python docstring
    is where the phase values and refusal tokens actually live, following
    `hs_input`'s own convention). Every one of them has to be backed by the
    hub doc too, or a caller reading one and not the other gets a different
    answer -- in process, so this needs no subprocess, only `mcp` importable
    for `server.py` itself."""

    DOC = ROOT / "docs" / "tools" / "hs-drive-mcp.md"

    PHASES = ("main_menu", "local", "slot", "play", "character_loaded",
              "proof_ambiguous", "timeout")
    REFUSAL_TOKENS = ("game_not_running", "game_state_unknown",
                      "engine_source_missing", "engine_import_failed",
                      "not_consumed", "no_visible_window_for_pid",
                      "window_minimized", "foreground_not_game",
                      "invalid_input", "proof_not_armed",
                      "character_already_loaded", "layout_command_missing",
                      "button_not_found", "slot_not_listed",
                      "window_size_mismatch", "click_not_delivered")

    @classmethod
    def setUpClass(cls):
        from tools.hs_drive_mcp import server
        cls.docstring = server.hs_select_character.__doc__ or ""
        cls.hub_doc = cls.DOC.read_text(encoding="utf-8")

    def test_every_phase_value_is_in_the_docstring_and_the_hub_doc(self):
        for phase in self.PHASES:
            with self.subTest(phase=phase):
                self.assertIn(phase, self.docstring,
                             f"{phase} is not named in hs_select_character's "
                             "own docstring")
                self.assertIn(phase, self.hub_doc,
                             f"{phase} is not documented in {self.DOC}")

    def test_every_refusal_token_is_in_the_docstring_and_the_hub_doc(self):
        for token in self.REFUSAL_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, self.docstring,
                             f"{token} is not named in hs_select_character's "
                             "own docstring")
                self.assertIn(token, self.hub_doc,
                             f"{token} is not documented in {self.DOC}")


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class UnknownArgumentTests(unittest.TestCase):
    """What the SDK does with an argument name no tool declares.

    This pins a measured property of `mcp==2.2.0`, not of this server, and it
    exists because the behaviour is silent: a live run on 2026-09-20 called
    `hs_ipc_tail` with `n=5` instead of `lines=5` and got the default 40 lines
    back with nothing saying an argument had been dropped.
    `ArgModelBase` sets `ConfigDict(arbitrary_types_allowed=True)` and never
    sets `extra`, so pydantic's default `extra="ignore"` applies and the key is
    gone before any tool body runs -- which is why no fix belongs in
    `tools/hs_drive_mcp/`. See `docs/tools/hs-drive-mcp.md` Known limitations.

    If a later `mcp` release starts refusing unknown arguments, this test fails
    and the documented limitation should be deleted -- that is the point of
    pinning it rather than only writing it down.
    """

    def _metadata(self):
        from mcp.server.mcpserver.utilities.func_metadata import func_metadata

        def toy_tail(lines: int = 40) -> dict:
            """Mirrors `hs_ipc_tail`'s real signature."""
            return {"lines": lines}

        return func_metadata(toy_tail)

    def test_an_unknown_argument_is_dropped_and_the_default_substituted(self):
        metadata = self._metadata()
        self.assertEqual(metadata.validate_arguments({"lines": 5}), {"lines": 5},
                         "the declared name must still work, or this test is "
                         "measuring a broken fixture rather than the SDK")
        self.assertEqual(metadata.validate_arguments({"n": 5}), {"lines": 40},
                         "an unknown argument is dropped and the default "
                         "substituted; see this class's docstring")
        self.assertEqual(metadata.validate_arguments({"lines": 5, "n": 99}),
                         {"lines": 5})
        self.assertEqual(metadata.validate_arguments({"LINES": 5}), {"lines": 40},
                         "the drop is case-sensitive")

    def test_the_published_schema_does_not_forbid_extra_properties(self):
        schema = self._metadata().arg_model.model_json_schema()
        self.assertEqual(set(schema["properties"]), {"lines"})
        self.assertNotIn("additionalProperties", schema,
                         "were this false, a client could reject the typo "
                         "itself and the limitation would not need documenting")

    def test_the_limitation_is_documented_where_a_caller_would_look(self):
        text = (ROOT / "docs" / "tools" / "hs-drive-mcp.md").read_text(
            encoding="utf-8")
        limitations = text.split("## Known limitations", 1)
        self.assertEqual(len(limitations), 2, "the section was renamed")
        self.assertIn("hs_ipc_tail(n=5)", limitations[1],
                      "the worked example is what makes this findable")
        self.assertIn("extra='ignore'", limitations[1])


if __name__ == "__main__":
    unittest.main()
