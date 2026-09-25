"""Tests for tools/live_checks.py, tools/plan_lint.py, tools/amend_check.py
and tools/run_criteria.py.

The first two are the static readers `/workorder` criteria use instead of a
hand-written grep over a live capture and a before-the-round guess at whether
a criterion can run; amend_check decides whether a plan change was an
amendment or a replan, and run_criteria runs a plan's criteria for the verifier.

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

import amend_check  # noqa: E402
import live_checks  # noqa: E402
import plan_lint  # noqa: E402
import run_criteria  # noqa: E402


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

    def test_pass_a_laneless_plan_prints_no_lanes(self):
        # Baseline: a plan with no `### Lane:` heading lints exactly as before,
        # and the lane table the driver passes to the workflow is empty.
        rc, out = run(plan_lint.main, [self.write("x-plan.md", PLAN), "--lanes-json"])
        self.assertEqual(rc, 0, out)
        self.assertIn("5 criteria, 0 finding(s)", out)
        self.assertEqual(out.strip().splitlines()[-1], '{"lanes": [], "join": false}')


def laned(*lanes, join=True):
    """PLAN with `## Steps` holding one `### Lane:` per (name, files-line)
    pair, a `files:` line only when the pair's second item is not None."""
    body = ["## Steps", "", "Preconditions for every step: work in this checkout.", ""]
    for k, (name, files) in enumerate(lanes, 1):
        body.append(f"### Lane: {name}")
        if files is not None:
            body.append(f"files: {files}")
        body += ["", f"{k}. **Step {k}.** Edit the lane's files.", ""]
    if join:
        body += ["### Join", f"{len(lanes) + 1}. Run the full suite and commit.", ""]
    return PLAN.replace("## Steps\n", "\n".join(body))


class PlanLintLaneTests(TempDirMixin, unittest.TestCase):
    def lint(self, text, *extra):
        return run(plan_lint.main, [self.write("x-plan.md", text), *extra])

    def test_fail_overlapping_lane_file_sets(self):
        for a, b in (("`tools/a.py`, `tests/test_a.py`", "`tools/a.py`"),
                     ("`docs/**`", "`docs/agents/*.md`"),
                     ("`docs/agents/*.md`", "`docs/agents/*.md`"),
                     ("`ForgePact/docs/`", "`ForgePact/docs/x.md`"),
                     # fnmatch's `*` crosses `/`, so `docs/readme.md` is in both.
                     ("`docs/`", "`*.md`"),
                     ("`docs/agents/`", "`docs/*.md`")):
            with self.subTest(a=a, b=b):
                rc, out = self.lint(laned(("code", a), ("docs", b)))
                self.assertEqual(rc, 1, out)
                self.assertIn("lane code: lane-overlap:", out)
                self.assertIn("lane docs", out)
                self.assertIn("5 criteria, 1 finding(s)", out)

    def test_fail_overlap_between_non_adjacent_lanes_of_three(self):
        # Only lanes 1 and 3 share a path: an adjacent-pairs check misses it.
        rc, out = self.lint(laned(("one", "`x/1.py`"), ("two", "`y/2.py`"),
                                  ("three", "`z/3.py`, `x/1.py`")))
        self.assertEqual(rc, 1, out)
        self.assertIn("lane one: lane-overlap: `x/1.py` overlaps lane three `x/1.py`", out)
        self.assertNotIn("lane two", out)
        self.assertIn("1 finding(s)", out)

    def test_fail_a_literal_inside_another_lanes_glob(self):
        rc, out = self.lint(laned(("docs", "`docs/agents/*.md`"),
                                  ("calib", "`docs/agents/workorder-calibration.md`")))
        self.assertEqual(rc, 1, out)
        self.assertIn("lane docs: lane-overlap: `docs/agents/*.md` overlaps lane calib "
                      "`docs/agents/workorder-calibration.md`", out)

    def test_fail_lanes_without_a_join(self):
        rc, out = self.lint(laned(("code", "`tools/a.py`"), ("docs", "`docs/a.md`"), join=False))
        self.assertEqual(rc, 1, out)
        self.assertIn(": lane-no-join:", out)
        self.assertIn("1 finding(s)", out)

    def test_fail_a_lane_without_files(self):
        rc, out = self.lint(laned(("code", None), ("docs", ""), ("tools", "`tools/a.py`")))
        self.assertEqual(rc, 1, out)
        self.assertIn("lane code: lane-no-files:", out)
        self.assertIn("lane docs: lane-no-files:", out)
        self.assertNotIn("lane tools", out)
        self.assertIn("2 finding(s)", out)

    def test_fail_a_duplicate_or_bad_lane_name(self):
        rc, out = self.lint(laned(("code", "`tools/a.py`"), ("code", "`tools/b.py`"),
                                  ("Code_X", "`tools/c.py`"), ("join", "`tools/d.py`")))
        self.assertEqual(rc, 1, out)
        self.assertIn("lane code: lane-dup-name:", out)
        self.assertIn("lane Code_X: lane-bad-name:", out)
        self.assertIn("lane join: lane-bad-name:", out)
        self.assertIn("3 finding(s)", out)

    def test_lanes_json_prints_the_lane_table(self):
        # Three lanes, and two globs whose literal prefixes diverge
        # (`tools/a*` / `tools/b*`) - the negative control for the prefix rule.
        text = laned(("code", "`tools/a*.py`, `tests/test_a.py`"),
                     ("audit", "`tools/b*.py`"),
                     ("docs", "`docs/agents/*.md`"))
        rc, out = self.lint(text, "--lanes-json")
        self.assertEqual(rc, 0, out)
        self.assertIn("5 criteria, 0 finding(s)", out)
        self.assertEqual(out.strip().splitlines()[-1],
                         '{"lanes": [{"name": "code", "files": ["tools/a*.py", "tests/test_a.py"]}, '
                         '{"name": "audit", "files": ["tools/b*.py"]}, '
                         '{"name": "docs", "files": ["docs/agents/*.md"]}], "join": true}')
        # A lint finding withholds the table, so a rejected plan never fans out.
        rc, out = self.lint(laned(("code", "`tools/a.py`"), ("docs", "`tools/a.py`")), "--lanes-json")
        self.assertEqual(rc, 1, out)
        self.assertNotIn('{"lanes"', out)


AMEND_PLAN = """---
slug: x
---
# x

## State
round: 1

## Goal
Make the flag right.

## Out of scope
- the launcher

## Acceptance criteria
- [ ] `py -3 -m unittest tests.test_x` prints `OK`
- [ ] `grep -n -- '--b' docs/x.md` prints one line

## Steps
1. Change docs/x.md.

```md
## Not a heading, inside a fence
```
"""

AMEND_CONTEXT = """# x context

## Context the implementer needs
### Where
docs/x.md

## Needs human judgement
none

## Log
### Plan
written
"""


class AmendCheckTests(TempDirMixin, unittest.TestCase):
    """Each REPLAN case beside an AMENDMENT control: a check that always says
    AMENDMENT would let any replan skip the tier escalation, and one that
    always says REPLAN would save nothing."""

    def setUp(self):
        super().setUp()
        self.plan = self.write("x-plan.md", AMEND_PLAN)
        self.context = self.write("x-context.md", AMEND_CONTEXT)
        rc, _ = run(amend_check.main, ["save", self.plan, self.context])
        self.assertEqual(rc, 0)

    def edit(self, path, old, new):
        text = Path(path).read_text(encoding="utf-8")
        self.assertIn(old, text)
        Path(path).write_text(text.replace(old, new, 1), encoding="utf-8")

    def check(self):
        return run(amend_check.main, ["check", self.plan, self.context])

    def test_unchanged_is_an_amendment_of_zero_lines(self):
        rc, out = self.check()
        self.assertEqual(rc, 0, out)
        self.assertIn("lines_changed: 0", out)

    def test_a_corrected_criterion_is_an_amendment(self):
        self.edit(self.plan, "prints one line", "prints exactly one line")
        rc, out = self.check()
        self.assertEqual(rc, 0, out)
        self.assertIn("x-plan.md: ## acceptance criteria: +1 -1", out)
        self.assertIn("AMENDMENT", out)

    def test_a_context_fact_and_a_log_entry_are_an_amendment(self):
        self.edit(self.context, "docs/x.md\n", "docs/y.md\n")
        self.edit(self.context, "written\n", "written\n### Amendment 1\n" + "a line\n" * 40)
        rc, out = self.check()
        self.assertEqual(rc, 0, out)
        self.assertIn("lines_changed: 2", out)  # the Log is not compared

    def test_state_edits_are_not_compared(self):
        self.edit(self.plan, "round: 1\n", "round: 2\nphase: implement\n" + "x: y\n" * 30)
        self.assertEqual(self.check()[0], 0)

    def test_goal_out_of_scope_or_human_judgement_changed_is_a_replan(self):
        for path, old, new in [
            (self.plan, "Make the flag right.", "Make the flag and the launcher right."),
            (self.plan, "- the launcher", "- nothing"),
            (self.context, "## Needs human judgement\nnone", "## Needs human judgement\nwhich flag?"),
        ]:
            with self.subTest(old=old):
                original = Path(path).read_text(encoding="utf-8")
                self.edit(path, old, new)
                rc, out = self.check()
                self.assertEqual(rc, 1, out)
                self.assertIn("REPLAN:", out)
                Path(path).write_text(original, encoding="utf-8")

    def test_a_section_added_or_removed_is_a_replan(self):
        self.edit(self.plan, "## Steps\n", "## Lanes\nnew\n\n## Steps\n")
        rc, out = self.check()
        self.assertEqual(rc, 1, out)
        self.assertIn("## lanes added", out)

    def test_a_heading_inside_a_fence_is_content(self):
        self.edit(self.plan, "## Not a heading, inside a fence", "## Still not a heading")
        rc, out = self.check()
        self.assertEqual(rc, 0, out)
        self.assertIn("## steps: +1 -1", out)

    def test_over_the_line_limit_is_a_replan(self):
        self.edit(self.plan, "1. Change docs/x.md.\n", "".join(f"{k}. step\n" for k in range(1, 21)))
        rc, out = self.check()
        self.assertEqual(rc, 1, out)
        self.assertIn("21 lines changed (limit 20)", out)

    def test_twenty_lines_is_still_an_amendment(self):
        self.edit(self.plan, "1. Change docs/x.md.\n", "".join(f"{k}. step\n" for k in range(1, 20)))
        rc, out = self.check()
        self.assertEqual(rc, 0, out)
        self.assertIn("lines_changed: 20", out)

    def test_check_without_save_and_bad_usage_exit_2(self):
        other = self.write("y-plan.md", AMEND_PLAN)
        self.assertEqual(run(amend_check.main, ["check", other])[0], 2)
        self.assertEqual(run(amend_check.main, ["diff", self.plan])[0], 2)
        self.assertEqual(run(amend_check.main, [])[0], 2)

    def test_the_copy_lands_beside_the_plan_under_rounds(self):
        base = self.tmp_path / ".rounds" / "x"
        self.assertTrue((base / "amend-base-plan.md").is_file())
        self.assertTrue((base / "amend-base-context.md").is_file())


RUNNER_PLAN = """# x

## State
round: 0
gates: `build: complete`

## Acceptance criteria

- [ ] `bash -c "echo once >> count.txt; echo ok"` prints `ok`
- [ ] `ls count.txt` lists the file, and `bash -c "echo once >> count.txt; echo ok"` prints `ok` again
- [ ] `bash -c "exit 3"` exits 3
- [ ] `docs/x.md` records the decision in its own words
- [ ] (gate `live1: complete`) `bash -c "echo live >> gated.txt"` exits 0
- [ ] (gate `build: complete`) `bash -c "echo built >> built.txt"` exits 0
- [ ] `cd sub; bash -c "pwd > where.txt"` exits 0 and `bash -c "pwd > where2.txt"` exits 0
- [ ] `bash -c "
printf 'a\\\\nb\\\\n' > multi.txt
wc -l < multi.txt"` prints `2`
"""


class RunCriteriaTests(TempDirMixin, unittest.TestCase):
    """The runner judges nothing, so what these pin is that it runs exactly
    what the plan says, once, where the plan says -- each with a control."""

    def setUp(self):
        super().setUp()
        self.bash = run_criteria.find_bash(None)
        if not self.bash:
            self.skipTest("no bash on this machine")
        (self.tmp_path / "sub").mkdir()
        self.plan = self.write("x-plan.md", RUNNER_PLAN)

    def runner(self, *extra):
        return run(run_criteria.main, [self.plan, "--out", str(self.tmp_path / "logs"), *extra])

    def test_commands_prose_and_expected_output_are_told_apart(self):
        items = run_criteria.criteria(RUNNER_PLAN)
        self.assertEqual(len(items), 8)
        self.assertEqual(run_criteria.commands(items[3]), [], "a path is not a command")
        self.assertEqual(run_criteria.commands(items[0]), ['bash -c "echo once >> count.txt; echo ok"'],
                         "`ok` is expected output, not a command")
        self.assertEqual(run_criteria.commands(items[1])[0], "ls count.txt")

    def test_a_later_span_keeps_the_criterion_cd(self):
        cmds = run_criteria.commands(run_criteria.criteria(RUNNER_PLAN)[6])
        self.assertEqual(cmds, ['cd sub; bash -c "pwd > where.txt"', 'cd sub; bash -c "pwd > where2.txt"'])

    def test_a_multi_line_span_keeps_its_newlines(self):
        (cmd,) = run_criteria.commands(run_criteria.criteria(RUNNER_PLAN)[7])
        self.assertIn("\nwc -l < multi.txt", cmd)

    def test_runs_each_command_once_from_the_checkout_and_reports_exit_codes(self):
        rc, out = self.runner()
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.tmp_path / "count.txt").read_text().count("once"), 1,
                         "the repeated command ran once")
        self.assertIn("same command as cmd-1.log, run once", out)
        self.assertIn("-> exit 3", out)
        self.assertIn("-> exit 0", out)
        self.assertIn("criterion 4: `docs/x.md`", out)
        self.assertIn("no command -- check by reading", out)
        self.assertTrue((self.tmp_path / "sub" / "where.txt").is_file())
        self.assertTrue((self.tmp_path / "sub" / "where2.txt").is_file(), "the cd carried to the second span")
        last = out.replace("\r", "").split("criterion 8:")[1]
        self.assertRegex(last, r"-> exit 0 .*\n\s*2\s*$", "the multi-line script ran as written")
        self.assertTrue((self.tmp_path / "logs" / "cmd-1.log").read_text(encoding="utf-8").startswith("$ bash -c"))

    def test_a_gate_not_set_is_skipped_and_a_set_one_runs(self):
        rc, out = self.runner()
        self.assertIn("SKIPPED (gate live1: complete not set)", out)
        self.assertFalse((self.tmp_path / "gated.txt").exists())
        self.assertTrue((self.tmp_path / "built.txt").exists(), "control: `build: complete` is on gates:")

    def test_a_template_gates_line_sets_nothing_and_no_gates_line_skips_nothing(self):
        text = RUNNER_PLAN.replace("gates: `build: complete`", "gates: build: complete | live1: complete")
        self.assertEqual(run_criteria.gates_set(text), set())
        self.assertIsNone(run_criteria.gates_set(RUNNER_PLAN.replace("gates: `build: complete`\n", "")))
        self.assertEqual(run_criteria.gates_set(RUNNER_PLAN), {"build: complete"})

    def test_start_resumes_and_list_runs_nothing(self):
        rc, out = self.runner("--list")
        self.assertEqual(rc, 0)
        self.assertIn("would run: ls count.txt", out)
        self.assertFalse((self.tmp_path / "count.txt").exists(), "--list ran something")
        rc, out = self.runner("--start", "3")
        self.assertNotIn("criterion 1:", out)
        self.assertIn("criterion 3:", out)
        self.assertFalse((self.tmp_path / "count.txt").exists())

    def test_a_command_over_its_timeout_is_reported_not_hung(self):
        plan = self.write("t-plan.md", "## Acceptance criteria\n\n- [ ] `bash -c \"sleep 5\"` exits 0\n")
        rc, out = run(run_criteria.main, [plan, "--timeout", "1", "--out", str(self.tmp_path / "t")])
        self.assertEqual(rc, 0)
        self.assertIn("-> exit TIMEOUT", out)

    def test_usage_errors_exit_2(self):
        self.assertEqual(run(run_criteria.main, [str(self.tmp_path / "missing-plan.md")])[0], 2)
        self.assertEqual(run(run_criteria.main, [self.write("y-plan.md", "## Goal\nx\n")])[0], 2)


if __name__ == "__main__":
    unittest.main()
