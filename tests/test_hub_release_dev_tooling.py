"""The released hub carries none of the development tooling.

`tauri-plugin-mcp-bridge` listens on a socket and can invoke any command the hub
has. It is how an agent drives a debug build, and it must never reach a player.
It used to be kept out by `#[cfg(debug_assertions)]` alone, which left the crate
compiled into every release and one careless edit away from starting there too.

So there are two gates, and both are pinned here: the dependency is optional
behind a `mcp-bridge` feature that is not a default (so `tauri build`, which is
what `tauri-action` runs, never enables it), and every registration site asks
for the feature *and* `debug_assertions`. Only `npm start` turns the feature on.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUB = ROOT / "hub"
CARGO = HUB / "src-tauri" / "Cargo.toml"
LIB = HUB / "src-tauri" / "src" / "lib.rs"
PACKAGE = HUB / "package.json"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "hub-release.yml"

GATE = '#[cfg(all(debug_assertions, feature = "mcp-bridge"))]'


class HubReleaseDevToolingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cargo = CARGO.read_text(encoding="utf-8")
        cls.lib = LIB.read_text(encoding="utf-8")
        cls.package = json.loads(PACKAGE.read_text(encoding="utf-8"))
        cls.workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    def test_bridge_dependency_is_optional(self):
        line = re.search(r"^tauri-plugin-mcp-bridge\s*=.*$", self.cargo, re.M)
        self.assertIsNotNone(line, "the bridge dependency is missing from Cargo.toml")
        self.assertIn("optional = true", line.group(0))

    def test_bridge_feature_is_not_a_default(self):
        self.assertRegex(self.cargo, r'(?m)^mcp-bridge\s*=\s*\["dep:tauri-plugin-mcp-bridge"\]')
        default = re.search(r"(?m)^default\s*=\s*\[(.*?)\]", self.cargo)
        if default:
            self.assertNotIn("mcp-bridge", default.group(1))

    def test_every_bridge_site_needs_the_feature_and_a_debug_build(self):
        code = re.sub(r"//[^\n]*", "", self.lib)
        uses = [m.start() for m in re.finditer(r"tauri_plugin_mcp_bridge|mcp-bridge:default", code)]
        self.assertTrue(uses, "no bridge registration found; this test is measuring nothing")
        for at in uses:
            gate_at = code.rfind("#[cfg(", 0, at)
            self.assertGreaterEqual(gate_at, 0)
            self.assertTrue(code.startswith(GATE, gate_at),
                            f"bridge use at offset {at} is not behind {GATE}")
        self.assertNotIn("#[cfg(debug_assertions)]\n    {\n        builder = builder.plugin(", code)

    def test_only_the_dev_script_enables_the_bridge(self):
        scripts = self.package["scripts"]
        self.assertIn("--features mcp-bridge", scripts["start"])
        for name, command in scripts.items():
            if name != "start":
                self.assertNotIn("mcp-bridge", command, f"npm script {name!r} enables the bridge")

    def test_release_workflow_never_enables_the_bridge(self):
        self.assertNotIn("mcp-bridge", self.workflow)
        self.assertNotIn("--features", self.workflow)
        self.assertNotIn("--debug", self.workflow)


if __name__ == "__main__":
    unittest.main()
