"""Nothing shipped to a player knows `hs-drive` exists.

`tests/test_hub_release_dev_tooling.py` pins the same boundary for the hub's
MCP bridge, which needs two gates because the bridge is *inside* a binary that
ships. This server has no in-binary equivalent to gate: it is a Python package
under `tools/`, imported by nothing that is packaged, so the boundary is an
absence -- and an absence is exactly the kind of property that is true until
someone adds one convenient line, which is why it is asserted rather than
assumed.

The three claims:

1. No release or packaging input mentions it. If `build_release.py` ever put
   this package on PyInstaller's analysis path, the panel would start shipping
   an MCP SDK and a save-overwriting tool to players.
2. `.mcp.json`'s entry is the stdio one this workorder specified -- a
   `command`/`args` pair, with no `url` and no `type`, because a remote
   transport would put a tool that rewrites save files behind something other
   than a local process this machine started.
3. The package writes to no stdout, opens no listener and runs nothing through
   a shell. The same pattern the acceptance criteria grep for, kept here so it
   runs in the suite rather than only in a reviewer's terminal.
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "tools" / "hs_drive_mcp"
MCP_CONFIG = ROOT / ".mcp.json"

#: Every input to something a player installs.
SHIPPED_INPUTS = (
    ROOT / ".github" / "workflows" / "hub-release.yml",
    ROOT / "ForgePact" / "build_release.py",
    ROOT / "HS-Offline-Launcher" / "build.ps1",
    ROOT / "hub" / "package.json",
    ROOT / "hub" / "src-tauri" / "Cargo.toml",
)

#: Both spellings: the package is `hs_drive_mcp`, the server is `hs-drive`.
FORBIDDEN = ("hs_drive", "hs-drive")

#: The pattern acceptance criterion A6 runs by hand.
UNSAFE = re.compile(
    r"shell=True|os\.system\(|socket\.|\.bind\(|HTTPServer|uvicorn|streamable|^\s*print\(",
    re.IGNORECASE | re.MULTILINE)

EXPECTED_ENTRY = {"command": "py", "args": ["-3", "-m", "tools.hs_drive_mcp"]}


class ReleaseBoundaryTests(unittest.TestCase):
    def test_no_shipped_build_input_mentions_the_server(self):
        checked = 0
        for path in SHIPPED_INPUTS:
            if not path.is_file():
                self.skipTest(f"{path.relative_to(ROOT)} is absent; run "
                              "`git submodule update --init` for the full check")
            text = path.read_text(encoding="utf-8", errors="replace")
            for token in FORBIDDEN:
                self.assertNotIn(token, text,
                                 f"{path.relative_to(ROOT)} mentions {token!r}; "
                                 "developer tooling must not reach a release input")
            checked += 1
        self.assertEqual(checked, len(SHIPPED_INPUTS))


class McpConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))

    def test_the_entry_is_a_local_stdio_server(self):
        entry = self.config["mcpServers"]["hs-drive"]
        self.assertEqual(entry["command"], EXPECTED_ENTRY["command"])
        self.assertEqual(entry["args"], EXPECTED_ENTRY["args"])
        self.assertNotIn("url", entry)
        self.assertNotIn("type", entry)

    def test_the_entry_points_at_a_package_that_exists(self):
        self.assertTrue((PACKAGE / "__main__.py").is_file())
        self.assertTrue((PACKAGE / "server.py").is_file())

    def test_the_game_workorders_modules_are_not_here_yet(self):
        # Empty stubs would make `hs-drive-mcp-game` look partly done.
        for name in ("ipc.py", "capture.py"):
            self.assertFalse((PACKAGE / name).exists(),
                             f"{name} belongs to the hs-drive-mcp-game workorder")


class PackageSurfaceTests(unittest.TestCase):
    def test_the_package_opens_no_listener_and_writes_no_stdout(self):
        sources = sorted(PACKAGE.glob("*.py"))
        self.assertTrue(sources, "no sources found; this test is measuring nothing")
        for path in sources:
            text = path.read_text(encoding="utf-8")
            match = UNSAFE.search(text)
            if match is not None:
                line = text.count("\n", 0, match.start()) + 1
                self.fail(f"{path.relative_to(ROOT)}:{line} matches "
                          f"{match.group(0)!r}; a stdio server writes only to "
                          "stderr and opens nothing")

    def test_only_the_registration_module_imports_the_sdk(self):
        for path in sorted(PACKAGE.glob("*.py")):
            if path.name in ("server.py", "__main__.py"):
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(
                text, r"(?m)^\s*(import mcp|from mcp)",
                f"{path.relative_to(ROOT)} imports the MCP SDK; the domain "
                "modules are tested without it")


if __name__ == "__main__":
    unittest.main()
