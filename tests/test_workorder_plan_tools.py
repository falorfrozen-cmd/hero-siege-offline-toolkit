"""Tests for tools/live_checks.py, tools/plan_lint.py, tools/amend_check.py,
tools/run_criteria.py, tools/workorder_lock.py and tools/item_commit.py.

The first two are the static readers `/workorder` criteria use instead of a
hand-written grep over a live capture and a before-the-round guess at whether
a criterion can run; amend_check decides whether a plan change was an
amendment or a replan, and run_criteria runs a plan's criteria for the verifier.

The fixture lines are shortened from forgepact-issue-14's real captures and
plans (2026-09-22..24), each the shape that cost a round.
"""

import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import amend_check  # noqa: E402
import item_commit  # noqa: E402
import live_checks  # noqa: E402
import plan_lint  # noqa: E402
import run_criteria  # noqa: E402
import workorder_lock  # noqa: E402


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

    def test_fail_a_pinned_commit_hash(self):
        # ForgePact UI redesign (2026-09-24..26): criteria that pinned the sha
        # a moving head had at plan time cost amendments once it moved.
        for span in ("git -C ForgePact diff --quiet 3aa95f6e99a2c97a3bee72d7a359df9b86f07f3a HEAD -- panel/",
                     "git -C ForgePact merge-base --is-ancestor e448110 HEAD",
                     "py -3 -c \"import subprocess; M='2b127efadf097d829653235a2ab1636f23d7ab79'; print(M)\"",
                     "git log --oneline HEAD..f1e2f57"):
            with self.subTest(span=span):
                self.assertEqual(plan_lint.lint_criterion(f"`{span}` exits 0"), [("pinned-sha", span)])

    def test_pass_what_only_looks_like_a_hash(self):
        # Negative control: the remedies the rule names, and hex that is not a
        # commit, lint clean.
        for span in ("git diff --quiet forgepact-ui-polish-base HEAD -- panel/",
                     "git diff --quiet $(git merge-base HEAD origin/main) HEAD -- docs/",
                     "certutil -hashfile x.dll SHA256 | grep 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
                     "grep -c 0x1a2b3c4d plugin/ModuleMain.cpp",
                     "grep -c '#a1b2c3' panel/src/app.css",
                     "ls .claude/worktrees/workorder-parallelization-2d890c",
                     "ls scratchpad/726ab7f9-55f8-459a-ab56-15cbfc7ee6f7",
                     "grep -c deadbeef x.log",
                     "grep -c 20260926 x.log"):
            with self.subTest(span=span):
                self.assertEqual(plan_lint.lint_criterion(f"`{span}` exits 0"), [])

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
        for bad in ("0", "many", "-2"):
            self.assertEqual(self.runner("--jobs", bad)[0], 2, bad)
        self.assertEqual(self.runner("--item", "nope")[0], 2, "no such item")

    def test_jobs_prints_what_a_serial_run_prints(self):
        # The verifier reads the parallel report exactly as the serial one:
        # same criteria, same order, same cmd-<n>.log numbers, same tails.
        _, serial = self.runner()
        shutil.rmtree(self.tmp_path / "logs")
        for name in ("count.txt", "built.txt", "sub/where.txt", "sub/where2.txt", "multi.txt"):
            (self.tmp_path / name).unlink(missing_ok=True)
        rc, parallel = self.runner("--jobs", "4")
        self.assertEqual(rc, 0, parallel)
        self.assertIn("jobs: 4 (browser suites at most 2)", parallel)

        def norm(text):
            text = re.sub(r"\(\d+s\)", "(Ns)", text.replace("\r", ""))
            return [l for l in text.splitlines() if not l.startswith(("checkout:", "logs:", "shell:", "jobs:"))]
        self.assertEqual(norm(parallel), norm(serial))
        self.assertEqual((self.tmp_path / "count.txt").read_text().count("once"), 1, "a shared command ran once")

    def test_independent_commands_overlap_under_jobs(self):
        spans = "\n".join(f"- [ ] (class pure) `bash -c \"sleep 2; echo {k}\"` exits 0" for k in range(3))
        plan = self.write("p-plan.md", f"## Acceptance criteria\n\n{spans}\n")
        started = time.monotonic()
        rc, out = run(run_criteria.main, [plan, "--jobs", "3", "--out", str(self.tmp_path / "p")])
        self.assertEqual(rc, 0, out)
        self.assertLess(time.monotonic() - started, 5, "three 2 s pure checks ran one after another")
        # Control: the same plan without --jobs is serial.
        started = time.monotonic()
        run(run_criteria.main, [plan, "--out", str(self.tmp_path / "q")])
        self.assertGreaterEqual(time.monotonic() - started, 6)

    def test_a_worker_that_raises_is_reported_not_hung(self):
        # PR #239 review: an exception in a worker thread never reached the
        # result queue, and the main loop waited on it forever.
        real = run_criteria._run_one

        def boom(bash, cmd, root, timeout):
            if "explode" in cmd:
                raise OSError("simulated spawn failure")
            return real(bash, cmd, root, timeout)
        run_criteria._run_one = boom
        self.addCleanup(setattr, run_criteria, "_run_one", real)
        plan = self.write("e-plan.md", "## Acceptance criteria\n\n- [ ] (class pure) `bash -c \"echo explode\"` ok\n"
                                       "- [ ] (class pure) `bash -c \"echo after\"` ok\n")
        box = {}
        t = threading.Thread(target=lambda: box.update(r=run(run_criteria.main, [plan, "--jobs", "2", "--out",
                                                                                  str(self.tmp_path / "e")])))
        t.start()
        t.join(30)
        self.assertFalse(t.is_alive(), "the parallel run hung on a worker's exception")
        rc, out = box["r"]
        self.assertEqual(rc, 0, out)
        self.assertIn("-> exit ERROR", out)
        self.assertIn("simulated spawn failure", out)
        self.assertIn("after", out, "the criterion after the failure was never printed")

    def test_a_shell_that_does_not_exist_is_a_usage_error(self):
        self.assertEqual(self.runner("--jobs", "2", "--shell", str(self.tmp_path / "no-such-bash.exe"))[0], 2)

    def test_item_runs_that_items_checks(self):
        plan = self.write("i-plan.md", ITEM_PLAN)
        rc, out = run(run_criteria.main, [plan, "--item", "toolbar", "--out", str(self.tmp_path / "i")])
        self.assertEqual(rc, 0, out)
        self.assertIn("criterion 1: `bash -c \"echo toolbar-check\"` exits 0", out)
        self.assertIn("toolbar-check", out)
        self.assertNotIn("tokens-check", out, "another item's check ran")
        self.assertNotIn("acceptance-check", out, "the whole-tree criteria ran")

    def test_list_with_jobs_names_each_class(self):
        rc, out = self.runner("--jobs", "2", "--list")
        self.assertEqual(rc, 0)
        self.assertIn("would run: ls count.txt [class pure]", out)
        self.assertIn('[class exclusive]', out, "an unrecognised command runs alone")
        self.assertFalse((self.tmp_path / "count.txt").exists(), "--list ran something")


class RunCriteriaSchedulingTests(unittest.TestCase):
    """`startable` is the whole scheduling policy, as a pure function."""

    def job(self, jid, cls, after=()):
        return {"id": jid, "cmd": f"c{jid}", "cls": cls, "after": set(after)}

    def drain(self, jobs, cap=8, browser=2):
        """Start everything startable, finish all running together, repeat;
        return the waves."""
        done, waves = set(), []
        while len(done) < len(jobs):
            wave = run_criteria.startable(jobs, done, set(), cap, browser)
            self.assertTrue(wave, f"stuck with {done}")
            # Admit whatever else becomes startable while this wave runs.
            running = set(wave)
            more = run_criteria.startable(jobs, done, running, cap, browser)
            while more:
                running |= set(more)
                more = run_criteria.startable(jobs, done, running, cap, browser)
            waves.append(sorted(running))
            done |= running
        return waves

    def test_classify(self):
        cases = {
            "cd ForgePact; build.bat dev": "build",
            "npm --prefix ForgePact/panel run build": "build",
            "cd ForgePact/panel && npm run e2e:perf": "exclusive",
            "py -3 -m unittest tests.test_panel_oracle": "exclusive",
            "cd ForgePact/panel && npm run e2e:gems": "browser",
            "node ForgePact/panel/tests/ui.e2e.mjs": "browser",
            "cd ForgePact && py -3 tools/run_tests_parallel.py": "suite",
            "py -3 -m unittest discover -s tests": "suite",
            "py -3 -m unittest tests.test_workorder_plan_tools": "test",
            "node --test .claude/workflows/workorder-rounds.test.mjs": "test",
            "cd ForgePact/panel && npm test": "test",
            "grep -c x docs/a.md": "pure",
            "git log --oneline -1": "pure",
            'py -3 -c "print(1)"': "pure",
            "py -3 tools/plan_lint.py x-plan.md": "pure",
            "some-tool --flag": "exclusive",
        }
        for cmd, cls in cases.items():
            with self.subTest(cmd=cmd):
                self.assertEqual(run_criteria.classify(cmd), cls)

    def test_builds_run_first_and_one_at_a_time(self):
        jobs = [self.job(1, "pure"), self.job(2, "build"), self.job(3, "build"), self.job(4, "test")]
        self.assertEqual(self.drain(jobs), [[2], [3], [1, 4]])

    def test_one_suite_and_capped_browsers_beside_pure_checks(self):
        jobs = [self.job(1, "suite"), self.job(2, "suite"), self.job(3, "browser"), self.job(4, "browser"),
                self.job(5, "browser"), self.job(6, "pure")]
        waves = self.drain(jobs, browser=2)
        self.assertEqual(waves[0], [1, 3, 4, 6], "one suite, two browsers and the pure check together")
        self.assertEqual(waves[1], [2, 5])

    def test_the_jobs_cap_holds(self):
        jobs = [self.job(k, "pure") for k in range(1, 6)]
        self.assertEqual(self.drain(jobs, cap=2), [[1, 2], [3, 4], [5]])

    def test_exclusive_is_a_barrier_at_its_place_in_the_plan(self):
        # What comes before it runs together; it runs alone; what follows waits.
        jobs = [self.job(1, "pure"), self.job(2, "browser"), self.job(3, "exclusive"),
                self.job(4, "pure"), self.job(5, "test")]
        self.assertEqual(self.drain(jobs), [[1, 2], [3], [4, 5]])
        self.assertEqual(run_criteria.startable(jobs, {1, 2}, {3}, 8, 2), [], "something started beside it")

    def test_after_holds_a_job_and_cannot_deadlock(self):
        jobs = [self.job(1, "pure"), self.job(2, "pure", after=[1])]
        self.assertEqual(self.drain(jobs), [[1], [2]])
        # A build declared after a pure check: builds-first alone would wait forever.
        jobs = [self.job(1, "pure"), self.job(2, "build", after=[1]), self.job(3, "test")]
        self.assertEqual(self.drain(jobs), [[1], [2], [3]])

    def test_a_shared_command_takes_the_stricter_class_and_after_maps_to_commands(self):
        items = ["(class pure) `grep a x` exits 0",
                 "(class build) `grep a x` exits 0, then `git log -1` (after 1)"]
        rows, jobs = run_criteria.build_jobs(items, 1, None)
        self.assertEqual([r["jobs"] for r in rows], [[1], [1, 2]])
        self.assertEqual(jobs[0]["cls"], "build")
        self.assertEqual(jobs[0]["after"], set(), "a job never waits on itself")
        self.assertEqual(jobs[1]["after"], {1})
        items = ["`grep a x` exits 0", "`git log -1` (after 1)"]
        _, jobs = run_criteria.build_jobs(items, 1, None)
        self.assertEqual(jobs[1]["after"], {1})


ITEM_PLAN = """# x

## State
planning: complete
gates: none

## Acceptance criteria
- [ ] `bash -c "echo acceptance-check"` exits 0

## Steps

Preconditions: work in this checkout.

### Item: tokens — colour tokens
files: `panel/src/tokens.css`
checks: `bash -c "echo tokens-check"` exits 0

1. Add the tokens.

### Item: toolbar — toolbar restyle
files: `panel/src/toolbar.css`, `panel/src/toolbar.js`
after: `tokens`
checks:
- `bash -c "echo toolbar-check"` exits 0
- `grep -c toolbar panel/src/toolbar.js` prints `1`

1. Restyle it.
"""


def itemised(*specs, lanes=False):
    """ITEM_PLAN's Steps replaced by one `### Item:` per (id, fields) pair."""
    body = ["## Steps", ""]
    for iid, fields in specs:
        body.append(f"### Item: {iid}")
        body += [f"{k}: {v}" for k, v in fields.items()]
        body += ["", "1. Do it.", ""]
    if lanes:
        body += ["### Lane: extra", "files: `x/y.py`", "", "1. More.", "", "### Join", "2. Join.", ""]
    return ITEM_PLAN.split("## Steps")[0] + "\n".join(body)


class PlanLintItemTests(TempDirMixin, unittest.TestCase):
    def lint(self, text, *extra):
        return run(plan_lint.main, [self.write("x-plan.md", text), *extra])

    def test_items_parse_fields_and_bullet_checks(self):
        found = plan_lint.items(ITEM_PLAN)
        self.assertEqual([it["id"] for it in found], ["tokens", "toolbar"])
        self.assertEqual(found[1]["title"], "toolbar restyle")
        self.assertEqual(found[1]["files"], ["panel/src/toolbar.css", "panel/src/toolbar.js"])
        self.assertEqual(found[1]["after"], ["tokens"])
        self.assertEqual(len(found[1]["checks"]), 2)
        self.assertEqual(found[0]["checks"], ['`bash -c "echo tokens-check"` exits 0'])
        # Control: a laneless, itemless plan has no items.
        self.assertEqual(plan_lint.items(PLAN), [])

    def test_pass_a_clean_item_plan_and_print_the_item_table(self):
        rc, out = self.lint(ITEM_PLAN, "--items-json")
        self.assertEqual(rc, 0, out)
        table = json.loads(out.strip().splitlines()[-1])
        self.assertTrue(table["complete"])
        self.assertEqual([it["id"] for it in table["items"]], ["tokens", "toolbar"])

    def test_fail_an_undeclared_overlap_and_pass_a_declared_one(self):
        overlapping = {"files": "`panel/src/app.css`", "checks": "`grep a b` exits 0"}
        rc, out = self.lint(itemised(("one", overlapping), ("two", overlapping)))
        self.assertEqual(rc, 1, out)
        self.assertIn("item one: item-overlap: `panel/src/app.css` overlaps item two", out)
        for link in ("shares", "after"):
            with self.subTest(link=link):
                rc, out = self.lint(itemised(("one", overlapping), ("two", {**overlapping, link: "`one`"})))
                self.assertEqual(rc, 0, out)

    def test_fail_each_item_shape_defect(self):
        rc, out = self.lint(itemised(
            ("nofiles", {"checks": "`grep a b` exits 0"}),
            ("nochecks", {"files": "`a/1.py`"}),
            ("Bad_Id", {"files": "`a/2.py`", "checks": "`grep a b` exits 0"}),
            ("dup", {"files": "`a/3.py`", "checks": "`grep a b` exits 0"}),
            ("dup", {"files": "`a/4.py`", "checks": "`grep a b` exits 0"}),
            ("ref", {"files": "`a/5.py`", "checks": "`python -c 1` exits 0", "after": "`ghost`"}),
        ))
        self.assertEqual(rc, 1, out)
        for expected in ("item nofiles: item-no-files", "item nochecks: item-no-checks",
                         "item Bad_Id: item-bad-id", "item dup: item-dup-id",
                         "item ref: item-unknown-ref: `ghost`", "item ref: bare-python"):
            self.assertIn(expected, out)

    def test_fail_an_after_cycle_and_items_beside_lanes(self):
        rc, out = self.lint(itemised(("a", {"files": "`a.py`", "checks": "`grep a b` ok", "after": "`b`"}),
                                     ("b", {"files": "`b.py`", "checks": "`grep a b` ok", "after": "`a`"})))
        self.assertEqual(rc, 1, out)
        self.assertIn("item-cycle", out)
        rc, out = self.lint(itemised(("a", {"files": "`a.py`", "checks": "`grep a b` ok"}), lanes=True))
        self.assertEqual(rc, 1, out)
        self.assertIn("items-and-lanes", out)

    def test_known_and_wait_return_only_new_items_and_streaming_is_incomplete(self):
        text = ITEM_PLAN.replace("planning: complete", "planning: streaming")
        rc, out = self.lint(text, "--items-json", "--known", "tokens")
        self.assertEqual(rc, 0, out)
        table = json.loads(out.strip().splitlines()[-1])
        self.assertFalse(table["complete"])
        self.assertEqual([it["id"] for it in table["items"]], ["toolbar"])
        # Nothing new and still streaming: --wait polls until its limit.
        started = time.monotonic()
        rc, out = self.lint(text, "--items-json", "--known", "tokens,toolbar", "--wait", "1")
        self.assertGreaterEqual(time.monotonic() - started, 0.9)
        self.assertEqual(json.loads(out.strip().splitlines()[-1]), {"items": [], "complete": False})
        # Control: a complete plan returns at once.
        started = time.monotonic()
        self.lint(ITEM_PLAN, "--items-json", "--known", "tokens,toolbar", "--wait", "30")
        self.assertLess(time.monotonic() - started, 5)


class WorkorderLockTests(TempDirMixin, unittest.TestCase):
    def test_a_held_lock_excludes_and_a_semaphore_hands_out_slots(self):
        with workorder_lock.held("build", self.tmp_path, timeout=0) as first:
            self.assertEqual(first, "build")
            with workorder_lock.held("build", self.tmp_path, timeout=0.3) as second:
                self.assertIsNone(second, "a second holder got the mutex")
        with workorder_lock.held("build", self.tmp_path, timeout=0) as again:
            self.assertEqual(again, "build", "released on exit")
        slots = ["browser-0", "browser-1"]
        with workorder_lock.held(slots, self.tmp_path, timeout=0) as a, \
                workorder_lock.held(slots, self.tmp_path, timeout=0) as b:
            self.assertEqual({a, b}, set(slots))
            with workorder_lock.held(slots, self.tmp_path, timeout=0.3) as c:
                self.assertIsNone(c, "a third browser suite got a slot")


class ItemCommitTests(TempDirMixin, unittest.TestCase):
    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.tmp_path), *args], capture_output=True, text=True, check=True)

    def setUp(self):
        super().setUp()
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.invalid")
        self.git("config", "user.name", "t")
        self.write("mine.py", "x = 1\n")
        self.write("theirs.py", "y = 1\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def test_commits_only_the_items_paths(self):
        self.write("mine.py", "x = 2  # MmCreateHook\n")
        self.write("new.py", "z = 1\n")
        self.write("theirs.py", "y = 2\n")
        self.git("add", "theirs.py")  # staged by someone else: must not ride along
        rc, out = run(item_commit.main, ["--message", "item a", "--root", str(self.tmp_path), "--",
                                         "mine.py", "new.py", "never-created.py"])
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"commit\t\.\t[0-9a-f]{40}")
        self.assertIn("path\tmine.py", out)
        self.assertIn("path\tnew.py", out)
        self.assertIn("flags\tinstrument", out)
        shown = self.git("show", "--name-only", "--format=", "HEAD").stdout.split()
        self.assertEqual(sorted(shown), ["mine.py", "new.py"])
        self.assertIn("theirs.py", self.git("diff", "--cached", "--name-only").stdout, "someone else's stage was lost")

    def test_a_rename_inside_the_items_paths_commits_both_sides(self):
        # PR #239 review: `diff --name-only` printed only the new path, so the
        # old path's deletion stayed staged for someone else's commit.
        (self.tmp_path / "d").mkdir()
        self.write("d/a.txt", "a\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "d")
        (self.tmp_path / "d" / "a.txt").rename(self.tmp_path / "d" / "b.txt")
        rc, out = run(item_commit.main, ["--message", "item r", "--root", str(self.tmp_path), "--", "d/"])
        self.assertEqual(rc, 0, out)
        shown = self.git("show", "--name-status", "--no-renames", "--format=", "HEAD").stdout.split()
        self.assertEqual(shown, ["D", "d/a.txt", "A", "d/b.txt"])
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout.strip(), "", "a deletion was left staged")

    def test_a_whole_submodule_path_is_every_path_inside_it_never_the_gitlink(self):
        # PR #239 review: `ForgePact/` sliced to an empty pathspec, and a bare
        # `ForgePact` went to the hub as a hand-made gitlink bump.
        split = item_commit.split_by_repo(["ForgePact/", "ForgePact", "ForgePact/a.py", "docs/x.md", "docs/"],
                                          ["ForgePact"])
        self.assertEqual(split, {"ForgePact": [".", ".", "a.py"], ".": ["docs/x.md", "docs"]})
        self.assertNotIn("", sum(split.values(), []))

    def test_nothing_to_commit_is_not_an_error(self):
        rc, out = run(item_commit.main, ["--message", "item a", "--root", str(self.tmp_path), "--", "mine.py"])
        self.assertEqual(rc, 0, out)
        self.assertNotIn("commit\t", out)
        self.assertIn("flags\t", out)


# The ForgePact UI redesign's ship workorder (2026-09-27), shortened: a
# one-file panel fix reaches the panel's npm tests and the e2e suite that
# covers the file, not the Python suite or the docs check.
REACH_PLAN = """# x

## State
gates: none

## Acceptance criteria

- [ ] (reads `ForgePact/panel/src/**`, `ForgePact/panel/package.json`) `npm --prefix ForgePact/panel test` exits 0
- [ ] (reads `ForgePact/panel/src/lib/**`, `ForgePact/panel/tests/review-fixes.e2e.mjs`) `npm --prefix ForgePact/panel run e2e:review` exits 0
- [ ] (reads `ForgePact/src/**`, `ForgePact/tests/**`) `cd ForgePact; py -3 tools/run_tests_parallel.py` exits 0
- [ ] (reads `docs/submodules/ForgePact/instructions.md`) `grep -c e2e:review docs/submodules/ForgePact/instructions.md` prints a number
- [ ] (reads `ForgePact/panel/src/app.css`) (after 1) `grep -c toast ForgePact/panel/dist/app.css` prints a number
"""


class ReachSelectionTests(unittest.TestCase):
    """`select` is the whole reach policy, as a pure function: what a change
    can reach, plus what failed, and everything whenever that is unknown."""

    def setUp(self):
        self.items = run_criteria.criteria(REACH_PLAN)

    def chosen(self, changed, failed=()):
        full, _, scope = run_criteria.select(self.items, changed, set(failed))
        self.assertFalse(full)
        return {k for k, (selected, _) in scope.items() if selected}

    def test_a_change_outside_every_reads_selects_only_the_failed(self):
        # Negative control: nothing any criterion reads changed.
        self.assertEqual(self.chosen(["README.md", "ForgePact/plugin/ModuleMain.cpp"], failed=[4]), {4})
        self.assertEqual(self.chosen(["README.md"]), set(), "a change nothing reads selected a criterion")
        _, _, scope = run_criteria.select(self.items, ["README.md"], {4})
        self.assertEqual(scope[4][1], "failed last time (--failed)")
        self.assertIn("nothing it reads changed (reads `ForgePact/src/**`, `ForgePact/tests/**`)", scope[3][1])

    def test_a_change_to_a_shared_file_selects_every_criterion_that_declares_it(self):
        self.assertEqual(self.chosen(["ForgePact/panel/src/lib/enabled-mods-undo.js"]), {1, 2})
        self.assertEqual(self.chosen(["ForgePact/panel/src/app.css"]), {1, 5},
                         "the glob and the literal that both cover app.css")
        self.assertEqual(self.chosen(["ForgePact/tests/test_x.py"]), {3}, "control: one reader, one criterion")

    def test_a_criterion_without_reads_runs_whatever_changed(self):
        # An old plan, with no map at all, still verifies fully.
        items = run_criteria.criteria(RUNNER_PLAN)
        full, _, scope = run_criteria.select(items, ["README.md"])
        self.assertFalse(full)
        self.assertTrue(all(selected for selected, _ in scope.values()))
        self.assertIn("declares no (reads ...)", scope[1][1])

    def test_an_unknown_delta_or_a_shared_contract_runs_everything(self):
        full, why, scope = run_criteria.select(self.items, None, unknown="git cannot diff ForgePact from abc")
        self.assertTrue(full)
        self.assertIn("delta unknown: git cannot diff ForgePact", why)
        self.assertEqual({k for k, (s, _) in scope.items() if s}, {1, 2, 3, 4, 5})
        full, why, _ = run_criteria.select(self.items, ["README.md", "hs-game-sdk/python/hs_game_sdk/items.py"])
        self.assertTrue(full)
        self.assertIn("shared contract changed: reads `hs-game-sdk/**` <- hs-game-sdk/python", why)
        # The plan can name its own contract; control: without the line, a
        # change to that file reaches nothing.
        text = REACH_PLAN.replace("gates: none", "gates: none\nshared contract: `ForgePact/panel/src/protocol.js`")
        self.assertTrue(run_criteria.select(self.items, ["ForgePact/panel/src/protocol.js"], set(),
                                            run_criteria.contract_globs(text))[0])
        self.assertEqual(self.chosen(["ForgePact/panel/src/protocol.js"]), {1})

    def test_a_selected_criterion_brings_the_one_it_runs_after(self):
        full, _, scope = run_criteria.select(self.items, ["ForgePact/panel/src/app.css"])
        self.assertEqual(scope[1][1], "reads `ForgePact/panel/src/**` <- ForgePact/panel/src/app.css")
        items = self.items[:4] + ["(reads `ForgePact/panel/dist/**`) (after 1) `grep -c x ForgePact/panel/dist/a.css` ok"]
        _, _, scope = run_criteria.select(items, ["ForgePact/panel/dist/a.css"])
        self.assertEqual(scope[1], (True, "criterion 5 runs after it"))

    def test_reads_path(self):
        rp = plan_lint.reads_path
        self.assertTrue(rp("ForgePact/panel/", "ForgePact/panel/src/a.js"))
        self.assertTrue(rp("ForgePact/panel", "ForgePact/panel/src/a.js"), "a literal directory covers what is under it")
        self.assertFalse(rp("ForgePact/panel", "ForgePact/panel-old/a.js"), "a prefix of a name is not its directory")
        self.assertTrue(rp("**/*.md", "README.md"))
        # PR #256 review: a mid-pattern `**/` matches no directory too.
        self.assertTrue(rp("ForgePact/panel/src/**/*.ts", "ForgePact/panel/src/main.ts"))
        self.assertTrue(rp("ForgePact/panel/src/**/*.ts", "ForgePact/panel/src/sub/main.ts"))
        self.assertTrue(rp("a/**/b/**/*.py", "a/b/x.py"))
        self.assertFalse(rp("ForgePact/panel/src/**/*.ts", "ForgePact/panel/main.ts"), "control: not above the dir")
        self.assertFalse(rp("ForgePact/panel/src/**/*.ts", "ForgePact/panel/src/main.js"), "control: not another type")
        self.assertTrue(rp("**", "anything/at/all"))
        self.assertTrue(rp("tools\\plan_lint.py", "tools/plan_lint.py"))
        self.assertFalse(rp("docs/*.md", "tools/x.md"))

    def test_an_empty_declaration_is_no_declaration(self):
        self.assertIsNone(plan_lint.reads("(reads ) `grep -c x a.md` ok"))
        self.assertEqual(plan_lint.reads("(reads `a/**`, `b (1).md`) `ls` ok"), ["a/**", "b (1).md"])

    def test_a_declared_path_is_never_run_as_a_command(self):
        item = "(reads `tools/setup.sh`, `docs/x.md`) `grep -c x docs/x.md` prints 1"
        self.assertEqual(run_criteria.commands(item), ["grep -c x docs/x.md"])
        self.assertEqual([rule for rule, _ in plan_lint.lint_criterion("(reads `docs/x.md`) the file says so")],
                         ["prose"], "a declaration is not a check")


class ReachRunTests(TempDirMixin, unittest.TestCase):
    """`--changed-since` end to end, in a throwaway hub with one submodule."""

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), "-c", "protocol.file.allow=always", *args],
                              capture_output=True, text=True, check=True)

    def init(self, path):
        path.mkdir(parents=True, exist_ok=True)
        self.git(path, "init", "-q")
        self.git(path, "config", "user.email", "t@example.invalid")
        self.git(path, "config", "user.name", "t")

    def setUp(self):
        super().setUp()
        self.bash = run_criteria.find_bash(None)
        if not self.bash:
            self.skipTest("no bash on this machine")
        source = self.tmp_path / "source"
        self.init(source)
        (source / "panel").mkdir()
        (source / "panel" / "a.js").write_text("a\n", encoding="utf-8")
        (source / "py.txt").write_text("p\n", encoding="utf-8")
        self.git(source, "add", "-A")
        self.git(source, "commit", "-q", "-m", "sub base")
        self.hub = self.tmp_path / "hub"
        self.init(self.hub)
        (self.hub / "docs").mkdir()
        (self.hub / "docs" / "guide.md").write_text("g\n", encoding="utf-8")
        self.git(self.hub, "submodule", "add", "-q", str(source), "Mod")
        self.git(self.hub / "Mod", "config", "user.email", "t@example.invalid")
        self.git(self.hub / "Mod", "config", "user.name", "t")
        self.git(self.hub, "add", "-A")
        self.git(self.hub, "commit", "-q", "-m", "hub base")
        self.git(self.hub, "tag", "base")
        crit = [
            "(reads `Mod/panel/**`) `bash -c \"echo 1 >> ran.txt\"` exits 0",
            "(reads `Mod/py.txt`) `bash -c \"echo 2 >> ran.txt\"` exits 0",
            "(reads `docs/**`) `bash -c \"echo 3 >> ran.txt\"` exits 0",
            "(reads `tools/**`) `bash -c \"echo 4 >> ran.txt\"` exits 0",
        ]
        self.plan = self.hub / "x-plan.md"
        self.plan.write_text("## Acceptance criteria\n\n" + "".join(f"- [ ] {c}\n" for c in crit), encoding="utf-8")

    def runner(self, *extra):
        (self.hub / "ran.txt").unlink(missing_ok=True)
        rc, out = run(run_criteria.main, [str(self.plan), "--out", str(self.tmp_path / "logs"), *extra])
        ran = (self.hub / "ran.txt").read_text().split() if (self.hub / "ran.txt").exists() else []
        return rc, out, sorted(ran)

    def test_runs_only_what_the_change_reaches_plus_the_failed(self):
        (self.hub / "Mod" / "panel" / "a.js").write_text("a2\n", encoding="utf-8")
        self.git(self.hub / "Mod", "commit", "-q", "-am", "panel fix")
        rc, out, ran = self.runner("--changed-since", "base", "--failed", "4")
        self.assertEqual(rc, 0, out)
        self.assertEqual(ran, ["1", "4"], out)
        self.assertIn("  Mod/panel/a.js", out)
        self.assertIn("scope: running 2 of 4 criteria", out)
        self.assertIn("run  criterion 1: reads `Mod/panel/**` <- Mod/panel/a.js", out)
        self.assertIn("skip criterion 3: nothing it reads changed (reads `docs/**`)", out)
        self.assertIn("NOT SELECTED (nothing it reads changed (reads `Mod/py.txt`))", out)
        # The same under --jobs, which schedules only the selected commands.
        rc, out, ran = self.runner("--changed-since", "base", "--failed", "4", "--jobs", "2")
        self.assertEqual(ran, ["1", "4"], out)

    def test_uncommitted_and_untracked_work_is_in_the_change(self):
        (self.hub / "docs" / "new.md").write_text("n\n", encoding="utf-8")
        (self.hub / "Mod" / "py.txt").write_text("p2\n", encoding="utf-8")
        rc, out, ran = self.runner("--changed-since", "base")
        self.assertEqual(ran, ["2", "3"], out)
        self.assertNotIn("  Mod\n", out.replace("\r", ""), "the gitlink line is not a changed file")

    def test_a_submodule_base_of_its_own_narrows_its_delta(self):
        # The hub's base records the submodule's first commit; a round base
        # after the first fix sees only the second.
        self.git(self.hub / "Mod", "commit", "-q", "--allow-empty", "-m", "noop")
        (self.hub / "Mod" / "panel" / "a.js").write_text("a2\n", encoding="utf-8")
        self.git(self.hub / "Mod", "commit", "-q", "-am", "first fix")
        round_base = self.git(self.hub / "Mod", "rev-parse", "HEAD").stdout.strip()
        (self.hub / "Mod" / "py.txt").write_text("p2\n", encoding="utf-8")
        self.git(self.hub / "Mod", "commit", "-q", "-am", "second fix")
        self.assertEqual(self.runner("--changed-since", "base")[2], ["1", "2"], "control: from the hub's record")
        rc, out, ran = self.runner("--changed-since", "base", "--changed-since", f"Mod={round_base}")
        self.assertEqual(ran, ["2"], out)

    def test_a_base_git_cannot_diff_from_runs_everything(self):
        rc, out, ran = self.runner("--changed-since", "no-such-ref")
        self.assertEqual(rc, 0, out)
        self.assertIn("scope: full -- delta unknown:", out)
        self.assertEqual(ran, ["1", "2", "3", "4"])

    def test_changed_from_reads_a_round_delta(self):
        delta = self.tmp_path / "delta.txt"
        delta.write_text("docs/guide.md\n", encoding="utf-8")
        self.assertEqual(self.runner("--changed-from", str(delta))[2], ["3"])
        rc, out, ran = self.runner("--changed-from", str(self.tmp_path / "missing.txt"))
        self.assertIn("scope: full -- delta unknown: cannot read", out)
        self.assertEqual(ran, ["1", "2", "3", "4"])

    def test_usage_errors_exit_2(self):
        for argv in (["--failed", "1"], ["--changed-since", "base", "--failed", "9"],
                     ["--changed-since", "base", "--failed", "one"], ["--changed-since", "Mod=base"],
                     ["--changed-since", "base", "--item", "a"], ["--changed-since", "base", "--changed-from", "-"],
                     ["--changed-since", "base", "--changed-since", "base"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.runner(*argv)[0], 2)
        self.assertEqual(self.runner()[2], ["1", "2", "3", "4"], "control: no flag runs every criterion")


class PlanLintReachTests(TempDirMixin, unittest.TestCase):
    def test_warn_a_criterion_with_no_reads_and_suggest_from_its_commands(self):
        rc, out = run(plan_lint.main, [self.write("x-plan.md", PLAN)])
        self.assertEqual(rc, 0, "a warning never fails the lint")
        self.assertIn("criterion 1: warning no-reads: declare (reads `<glob>`, ...); inferred from its commands, "
                      "check before copying: `tests/test_x.py`", out)
        self.assertIn("criterion 4: warning no-reads", out)
        self.assertIn("`ForgePact/plugin/ModuleMain.cpp`", out)
        self.assertIn("5 criteria, 0 finding(s), 5 warning(s)", out)
        rc, out = run(plan_lint.main, [self.write("r-plan.md", REACH_PLAN)])
        self.assertEqual(rc, 0, out)
        self.assertNotIn("warning", out, "control: a mapped plan warns about nothing")

    def test_infer_reads(self):
        self.assertEqual(plan_lint.infer_reads("`cd ForgePact; py -3 tools/run_tests_parallel.py` exits 0"),
                         ["ForgePact/**"])
        self.assertEqual(plan_lint.infer_reads("`npm --prefix ForgePact/panel run e2e:review` exits 0"),
                         ["ForgePact/panel/**"])
        self.assertEqual(plan_lint.infer_reads("`py -3 -m unittest tests.test_hub_x -v` exits 0"),
                         ["tests/test_hub_x.py"])
        self.assertEqual(plan_lint.infer_reads("`py -3 -m unittest discover -s tests` exits 0"), [])
        self.assertEqual(plan_lint.infer_reads("`docs/x.md` records it"), ["docs/x.md"])

    def test_warn_a_glob_that_names_no_tracked_file(self):
        subprocess.run(["git", "-C", self._tmp, "init", "-q"], check=True)
        (self.tmp_path / "docs").mkdir()
        self.write("docs/a.md", "a\n")
        subprocess.run(["git", "-C", self._tmp, "add", "-A"], check=True)
        # An uninitialized submodule: git lists its gitlink, not its files.
        subprocess.run(["git", "-C", self._tmp, "update-index", "--add", "--cacheinfo",
                        "160000,1111111111111111111111111111111111111111,Mod"], check=True)
        plan = self.write("x-plan.md", "## Acceptance criteria\n- [ ] (reads `docs/*.md`, `doc/*.md`) "
                                       "`grep -c a docs/a.md` prints 1\n"
                                       "- [ ] (reads `Mod/panel/src/**`) `grep -c x Mod/panel/src/a.js` prints 1\n"
                                       "- [ ] `git log --oneline origin/main..HEAD -- docs/a.md falorfrozen-cmd/ForgePact` "
                                       "lists commits\n")
        rc, out = run(plan_lint.main, [plan])
        self.assertEqual(rc, 0, out)
        self.assertIn("warning reads-nothing: `doc/*.md` names no tracked file", out)
        self.assertNotIn("`docs/*.md` names no", out, "control: a glob that matches is not flagged")
        self.assertNotIn("`Mod/panel/src/**` names no", out, "a submodule git cannot list is unknown, not empty")
        self.assertIn("criterion 3: warning no-reads: declare (reads `<glob>`, ...); inferred from its commands, "
                      "check before copying: `docs/a.md`\n", out.replace("\r", ""),
                      "a ref, a range and a repo slug are not paths in this checkout")


if __name__ == "__main__":
    unittest.main()
