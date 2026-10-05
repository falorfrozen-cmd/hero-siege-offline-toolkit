"""Tests for the hub's two installers and the update path between them.

Every hub up to hub-v1.0.6 was installed from the NSIS `-setup.exe`. The MSI
was added beside it (issue #427), and two settings keep an NSIS install from
being handed the MSI by its own updater:

**`nsis` stays in `bundle.targets`.** An installed hub asks `latest.json` for
the entry of its own installer format, then for plain `windows-x86_64`. With
the MSI as the only target there is no NSIS entry, so an NSIS hub falls back
to the plain one and runs the MSI on top of a per-user install.

**The plain entry is the NSIS one.** `tauri-action` gives it to the MSI unless
`updaterJsonPreferNsis` is true, and the plain entry is what a hub that cannot
name its own format falls back to.

`docs/hub/design.md` § "Two installers" has the reasoning.
"""

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TAURI_CONF = REPO / "hub" / "src-tauri" / "tauri.conf.json"
RELEASE_WORKFLOW = REPO / ".github" / "workflows" / "hub-release.yml"


def _publish_step() -> str:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Build, sign and publish")
    end = text.find("\n      - name:", start + 1)
    return text[start : end if end != -1 else len(text)]


class BothInstallersAreBuilt(unittest.TestCase):
    def test_nsis_and_msi_are_both_targets(self):
        targets = json.loads(TAURI_CONF.read_text(encoding="utf-8"))["bundle"]["targets"]
        self.assertIn("nsis", targets, "existing hubs are NSIS installs and update through it")
        self.assertIn("msi", targets)

    def test_updater_artifacts_are_still_made(self):
        bundle = json.loads(TAURI_CONF.read_text(encoding="utf-8"))["bundle"]
        self.assertIs(bundle["createUpdaterArtifacts"], True)


class TheFallbackUpdaterEntryIsNsis(unittest.TestCase):
    def test_the_publish_step_prefers_nsis(self):
        step = _publish_step()
        self.assertRegex(step, re.compile(r"^\s+includeUpdaterJson:\s*true\s*$", re.M))
        self.assertRegex(step, re.compile(r"^\s+updaterJsonPreferNsis:\s*true\s*$", re.M))


if __name__ == "__main__":
    unittest.main()
