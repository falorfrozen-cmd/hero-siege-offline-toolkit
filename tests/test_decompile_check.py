"""tools/decompile_check.py: the hook's decompiled-output signatures over a round.

A workorder implementer commits as it goes, so the PostToolUse hook's view
(lines added against HEAD) is empty by the end of a round. The tool reads the
lines added since the round's snapshot, or since a --base, with the hook's own
SIGNATURES. The signature texts below are assembled at run time, so this file
never carries one for the hook to flag.
"""

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import decompile_check  # noqa: E402

GHIDRA_SYMBOL = "FUN" + "_00401000"
GML_ARGUMENT = "argu" + "ment0"


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class DecompileCheckTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "t")
        git(self.root, "config", "core.autocrlf", "false")
        (self.root / "docs").mkdir()
        # A match already committed before the workorder is the hook's
        # grandfathered case: it must not be reported again.
        (self.root / "docs" / "old.md").write_text(f"legacy {GHIDRA_SYMBOL}\n", encoding="utf-8")
        (self.root / "README.md").write_text("hello\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "base")
        self.base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True).stdout.strip()

    def run_tool(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = decompile_check.main([*argv, "--root", str(self.root)])
        return code, out.getvalue(), err.getvalue()

    def snapshot(self, round_="0"):
        rd = decompile_check.round_delta
        with redirect_stdout(io.StringIO()):
            self.assertEqual(rd.cmd_snapshot(self.root, "zz", round_), 0)

    def test_a_committed_hit_in_the_round_is_reported(self):
        self.snapshot()
        (self.root / "docs" / "notes.md").write_text(f"ok line\nthe loop calls {GHIDRA_SYMBOL} first\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "round 0")
        code, out, err = self.run_tool("zz", "0")
        self.assertEqual(code, 1, out + err)
        self.assertIn(f"docs/notes.md:2  adds a Ghidra auto-generated symbol: '{GHIDRA_SYMBOL}'", out)
        self.assertNotIn("old.md", out, "a match committed before the round is not this round's")

    def test_a_clean_round_exits_0(self):
        self.snapshot()
        (self.root / "README.md").write_text("hello\nworld\n", encoding="utf-8")
        code, out, _ = self.run_tool("zz", "0")
        self.assertEqual(code, 0, out)
        self.assertIn("0 hit(s) in 1 path(s)", out)

    def test_a_base_keeps_an_earlier_rounds_hit_visible(self):
        # Round 0 added the hit; round 1 touched another file only.
        (self.root / "src.py").write_text(f"x = {GML_ARGUMENT}\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "round 0")
        self.snapshot("1")
        (self.root / "README.md").write_text("hello\nagain\n", encoding="utf-8")
        code, out, _ = self.run_tool("zz", "1")
        self.assertEqual(code, 0, "control: the round's own delta does not reach round 0's file")
        code, out, _ = self.run_tool("zz", "1", "--base", f".={self.base}")
        self.assertEqual(code, 1, out)
        self.assertIn("src.py:1  adds a GML positional argument", out)

    def test_paths_mode_and_the_hooks_own_exclusions(self):
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "x.md").write_text(f"{GHIDRA_SYMBOL}\n", encoding="utf-8")
        (self.root / "b.png").write_bytes(GHIDRA_SYMBOL.encode())
        (self.root / "c.md").write_text(f"{GHIDRA_SYMBOL}\n", encoding="utf-8")
        code, out, _ = self.run_tool("--paths", ".claude/x.md", "b.png", "c.md")
        self.assertEqual(code, 1)
        self.assertNotIn(".claude/x.md", out, "the hook's own machinery is skipped")
        self.assertNotIn("b.png", out, "an unwatched suffix is not read")
        self.assertIn("c.md:1  adds", out)

    def test_an_untrusted_snapshot_without_a_base_exits_3(self):
        code, _, err = self.run_tool("zz", "7")
        self.assertEqual(code, 3)
        self.assertIn("snapshot", err)
        code, _, err = self.run_tool("zz")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
