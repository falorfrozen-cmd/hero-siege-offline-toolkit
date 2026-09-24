"""Tests for tools/live_checks.py and tools/plan_lint.py -- the two static
readers `/workorder` criteria use instead of a hand-written grep over a live
capture and a before-the-round guess at whether a criterion can run.

The fixture lines are shortened from forgepact-issue-14's real captures and
plans (2026-09-22..24), each the shape that cost a round.
"""

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import live_checks  # noqa: E402
import plan_lint  # noqa: E402


CAPTURE = """# forgepact-x live 1

## Step 1
craftprobe show -> CheckPlayerInteraction calls=18620

## Checks

- dll-hash | expected: ee896d9f | observed: EE896D9F (match) | pass
- marker | expected: craftprobe: phase1h rows=254 | observed: craftprobe: phase1h rows=254 | pass
- control | expected: calls=<n> n>0 | observed: calls=18620 | pass
- holders | expected: <M> named | observed: capped at 80 of 221 | not-observed (the var reply is capped)
- close-after-take | expected: game running | observed: pid changed | fail
"""


class TempDirMixin:
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="workorder_plan_tools_")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.tmp_path = Path(self._tmp)

    def write(self, name, text):
        path = self.tmp_path / name
        path.write_text(text, encoding="utf-8")
        return str(path)


def run(main, argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        rc = main(argv)
    return rc, out.getvalue()


class LiveChecksTests(TempDirMixin, unittest.TestCase):
    EXPECT = "dll-hash,marker,control,holders,close-after-take"

    def test_pass_a_note_after_the_verdict(self):
        # phase1c r2 and phaseA-record: `| not-observed (explanation)` failed a
        # `$`-anchored grep. A fail or not-observed is a finding, not an error.
        rc, out = run(live_checks.main, [self.write("c-live-1.md", CAPTURE), "--expect", self.EXPECT,
                                         "--require-pass", "dll-hash,marker,control"])
        self.assertEqual(rc, 0, out)
        self.assertIn("holders not-observed  (the var reply is capped)", out)
        self.assertIn("checks: 5 (pass 3, fail 1, not-observed 1)", out)

    def test_fail_a_renamed_check(self):
        # phase1h: the operator wrote `take-material (dropped)`.
        text = CAPTURE.replace("- holders |", "- holders (partial) |")
        rc, out = run(live_checks.main, [self.write("c-live-1.md", text), "--expect", self.EXPECT])
        self.assertEqual(rc, 1)
        self.assertIn("missing check: holders", out)
        self.assertIn("renamed?): holders (partial)", out)

    def test_fail_a_line_with_no_verdict_and_a_duplicate(self):
        text = CAPTURE + "- marker | expected: x | observed: y | looked fine\n"
        rc, out = run(live_checks.main, [self.write("c-live-1.md", text)])
        self.assertEqual(rc, 1)
        self.assertIn("marker UNREADABLE", out)
        self.assertIn("check listed twice: marker", out)

    def test_fail_a_control_that_did_not_pass(self):
        text = CAPTURE.replace("observed: calls=18620 | pass", "observed: nothing | not-observed")
        rc, out = run(live_checks.main, [self.write("c-live-1.md", text), "--require-pass", "control"])
        self.assertEqual(rc, 1)
        self.assertIn("control must be pass, read not-observed", out)

    def test_verdict_forms(self):
        self.assertEqual(live_checks.parse_line("- a | x | **pass**.")[1], "pass")
        self.assertEqual(live_checks.parse_line("- a | x | Not observed - timed out")[1:], ("not-observed", "- timed out"))
        self.assertIsNone(live_checks.parse_line("- a | x | passed")[1])

    def test_usage_errors_exit_2(self):
        self.assertEqual(run(live_checks.main, [str(self.tmp_path / "missing.md")])[0], 2)
        self.assertEqual(run(live_checks.main, [self.write("c-live-1.md", "## Step 1\n- a | pass\n")])[0], 2)


PLAN = """# x

## State
gates: none

## Acceptance criteria
- [ ] `py -3 -m unittest tests.test_x` exits 0
- [ ] `py -3 -c "t=open('d.md').read(); s=t[t.index('\\n### Results\\n'):t.index('\\n## Decision gate\\n')]; print(len(s))"` prints a number
- [ ] `py -3 -c "n=' '.join(open('d.md').read().split()); print(n.find('### Phase 1h rows') > 0)"` prints `True`
- [ ] `py -3 -c "t=open('ForgePact/plugin/ModuleMain.cpp').read(); print(t.index('#define CRAFTPROBE_TARGETS(X)') > 0)"` prints `True`
- [ ] `py -3 tools/live_checks.py .claude/workorders/x-live-1.md --expect a,b` exits 0

## Steps
"""


class PlanLintTests(TempDirMixin, unittest.TestCase):
    def test_pass_a_clean_plan(self):
        rc, out = run(plan_lint.main, [self.write("x-plan.md", PLAN)])
        self.assertEqual(rc, 0, out)
        self.assertIn("5 criteria, 0 finding(s)", out)

    def test_fail_each_measured_defect(self):
        bad = PLAN.replace("## Steps", "\n".join([
            # phase1c PLAN-DEFECT 2: the heading is mentioned in backticks above it.
            "- [ ] `py -3 -c \"t=open('d.md').read(); print(t[t.index('## Decision gate'):][:9])\"` prints `## Decisi`",
            "- [ ] `grep -c \"^- \\(dll-hash\\|marker\\) |.*| \\(pass\\|fail\\|not-observed\\)$\" "
            ".claude/workorders/x-live-1.md` prints `2`",
            "- [ ] `cd ForgePact && python -m unittest discover -s tests` exits 0",
            "- [ ] the scanner handles both value kinds correctly",
            "",
            "## Steps"]))
        rc, out = run(plan_lint.main, [self.write("x-plan.md", bad)])
        self.assertEqual(rc, 1)
        for want in ("criterion 6: unanchored-slice", "criterion 7: capture-grep",
                     "criterion 8: bare-python", "criterion 9: prose"):
            self.assertIn(want, out)
        self.assertIn("9 criteria, 4 finding(s)", out)

    def test_continuation_lines_join_their_item(self):
        text = "## Acceptance criteria\n- [ ] the file\n      `docs/x.md` records it\n"
        self.assertEqual(plan_lint.criteria(text), ["the file `docs/x.md` records it"])

    def test_usage_errors_exit_2(self):
        self.assertEqual(run(plan_lint.main, [str(self.tmp_path / "missing-plan.md")])[0], 2)
        self.assertEqual(run(plan_lint.main, [self.write("x-plan.md", "## Goal\nx\n")])[0], 2)
        self.assertEqual(run(plan_lint.main, [])[0], 2)


if __name__ == "__main__":
    unittest.main()
