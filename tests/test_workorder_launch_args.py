"""`tools/workorder_brief.py --launch-args <slug>`: the driver's Workflow args.

Measured (the 2026-10-11 /workorder audit, F04/F16): drivers made 1,171 shell
reads of the plan and context files and 536 `section.py` calls, largely to
copy State, lint JSON, prior findings and base heads into each launch's args
by hand. The tool prints them as one JSON object the driver passes through.
Driven as a subprocess on a throwaway git checkout.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tools" / "workorder_brief.py"
sys.path.insert(0, str(REPO / ".claude" / "skills" / "workorder"))
import round_delta  # noqa: E402


def plan_text(state, steps="1. Do the thing.\n", criteria="- [ ] `py -3 -c \"print(1)\"` exits 0\n"):
    return ("# zz\n\nstatus: READY\nmodule: hub\n\n## State\n" + state + "\n\n## Goal\n\nGOAL-MARK\n\n"
            "## Out of scope\n\n- SCOPE-MARK\n\n## Acceptance criteria\n\n" + criteria + "\n## Steps\n\n" + steps)


CONTEXT = """## Context the implementer needs

### A
a

## Needs human judgement

none

## Log

### Plan
planned

### Round 0 (started 2026-10-11T10:00:00Z)

verifier: PASS

BLOCKING (2)
- [docs-sync-reviewer] docs/x.md:3: stale flag — evidence: line 3 says --a — fix: change it
- [instrument-blindness-reviewer] ForgePact/plugin/a.cpp:9: no positive control — evidence: e

NON-BLOCKING (1)
- [docs-sync-reviewer] docs/y.md: nit

### Round 1

PLAN-DEFECT

ev
"""


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


class LaunchArgsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "t")
        (self.root / "README.md").write_text("x\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "base")
        self.base = git(self.root, "rev-parse", "HEAD")
        self.wo = self.root / ".claude" / "workorders"
        self.wo.mkdir(parents=True)

    def write(self, state, ctx=CONTEXT, **kw):
        (self.wo / "zz-plan.md").write_text(plan_text(state, **kw), encoding="utf-8")
        if ctx is not None:
            (self.wo / "zz-context.md").write_text(ctx, encoding="utf-8")

    def launch(self, *argv):
        r = subprocess.run([sys.executable, str(SCRIPT), "--launch-args", "zz", "--checkout", str(self.root), *argv],
                           capture_output=True)
        out = r.stdout.decode("utf-8")
        return r.returncode, (json.loads(out) if r.returncode == 0 else None), r.stderr.decode("utf-8")

    def test_the_args_come_from_the_files(self):
        self.write("round: 2        phase: implement\ngates: none\nreviewers: docs-sync-reviewer: blocking; "
                   "instrument-blindness-reviewer: clean, not re-run; sdk-contract-reviewer: never, deferred\nlaunches: 3")
        code, args, err = self.launch("--reviewers", "tauri-command-reviewer,docs-sync-reviewer", "--implementer-effort", "medium")
        self.assertEqual(code, 0, err)
        self.assertEqual(args["slug"], "zz")
        self.assertEqual(args["planPath"], ".claude/workorders/zz-plan.md")
        self.assertEqual(args["contextPath"], ".claude/workorders/zz-context.md")
        self.assertEqual(Path(args["checkoutRoot"]), self.root.resolve())
        self.assertEqual(args["round"], 2)
        self.assertIn("GOAL-MARK", args["goalExcerpt"])
        self.assertIn("SCOPE-MARK", args["goalExcerpt"])
        self.assertNotIn("Acceptance criteria", args["goalExcerpt"])
        self.assertTrue(args["state"].startswith("## State\nround: 2"))
        self.assertIn("launches: 3", args["state"])
        self.assertEqual(args["reviewers"], {"docs-sync-reviewer": "blocking", "instrument-blindness-reviewer": "clean",
                                             "sdk-contract-reviewer": "never", "tauri-command-reviewer": "never"})
        # The newest round that lists BLOCKING findings is round 0 (round 1 was a PLAN-DEFECT);
        # only reviewers entering as blocking get theirs.
        self.assertEqual(args["priorFindings"], {"docs-sync-reviewer": [{"where": "docs/x.md:3", "problem": "stale flag"}]})
        self.assertEqual(args["implementerEffort"], "medium")
        self.assertNotIn("submodules", args, "module: hub names no submodule")
        self.assertNotIn("baseHeads", args, "no snapshot yet")
        self.assertNotIn("lanes", args)
        self.assertNotIn("items", args)

    def test_base_heads_are_the_earliest_snapshots(self):
        self.write("round: 1\nphase: implement\nreviewers: <none yet>")
        with open(self.root / "dummy.txt", "w") as fh:
            fh.write("y")
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            round_delta.cmd_snapshot(self.root, "zz", "0")
        (self.root / "dummy.txt").unlink()
        (self.root / "b.txt").write_text("z", encoding="utf-8")
        git(self.root, "add", "b.txt")
        git(self.root, "commit", "-qm", "round 0")
        with contextlib.redirect_stdout(io.StringIO()):
            round_delta.cmd_snapshot(self.root, "zz", "1")
        code, args, err = self.launch()
        self.assertEqual(code, 0, err)
        self.assertEqual(args["baseHeads"], {".": self.base})
        code, args, err = self.launch("--final-gate")
        self.assertEqual(code, 0, err)
        self.assertTrue(args["finalGate"])
        self.assertIn("b.txt", args["branchPaths"])
        self.assertIn(".claude/workorders/zz-plan.md", args["branchPaths"], "untracked files count too")
        self.assertNotIn("README.md", args["branchPaths"], "a file unchanged since the base is not on the branch")

    def test_lanes_only_on_a_first_implementation(self):
        steps = ("Preconditions.\n\n### Lane: a\nfiles: `a.py`\n\n1. A.\n\n### Lane: b\nfiles: `b.py`\n\n1. B.\n\n"
                 "### Join\n\n1. Join.\n")
        self.write("round: 0\nphase: plan", steps=steps)
        code, args, err = self.launch()
        self.assertEqual(code, 0, err)
        self.assertEqual(args["lanes"], [{"name": "a", "files": ["a.py"]}, {"name": "b", "files": ["b.py"]}])
        self.assertIs(args["join"], True)
        self.write("round: 1\nphase: implement", steps=steps)
        code, args, err = self.launch()
        self.assertNotIn("lanes", args, "a defect round runs one implementer")
        code, args, err = self.launch("--first-implementation")
        self.assertIn("lanes", args, "the relaunch after a replan is a first implementation")

    def test_a_lint_finding_goes_back_to_the_planner(self):
        self.write("round: 0\nphase: plan", criteria="- [ ] it looks right\n")
        code, args, err = self.launch()
        self.assertEqual(code, 1)
        self.assertIn("send them back to the planner", err)

    def test_a_single_file_plan_is_its_own_context_and_a_missing_plan_exits_2(self):
        self.write("round: 0\nphase: plan", ctx=None)
        code, args, err = self.launch()
        self.assertEqual(code, 0, err)
        self.assertEqual(args["contextPath"], args["planPath"])
        self.assertEqual(args["priorFindings"], {})
        r = subprocess.run([sys.executable, str(SCRIPT), "--launch-args", "nope", "--checkout", str(self.root)], capture_output=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
