"""tools/workorder_record.py: a launch's State and Log, written from its run record.

The Workflow script cannot write a file, so each launch returns its rounds'
State lines and Log blocks in `result.record`, and this tool applies them once
the launch has returned. These tests build a run record the way Claude Code
saves one (`workflows/wf_<runId>.json`, top-level `runId`, `args`, `result`)
and two temporary workorder files.
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import workorder_record  # noqa: E402

PLAN = """# zz

status: READY

## State
round: 0        phase: plan
gates: `build: complete`
round base: <none yet>
agents: planner-tier=planner
reviewers: <none yet>
open defects: none
decisions in force: D1 both repositories take `origin/main` by a merge
  commit (never a rebase)

## Goal
g
"""
CONTEXT = """# zz context

## Context the implementer needs

### A
a

## Log

### Plan
planned it
"""
ROUND0 = {"round": 0, "stateLines": "round: 1\nphase: implement\nreviewers: docs-sync-reviewer: never, deferred\nopen defects: none\nlaunches: 1",
          "logBlock": "### Round 0 (started 2026-10-11T10:00:00Z)\n\nverifier: IMPL-DEFECT\n- FAILED c: e\n\nBLOCKING (0)\n\nNON-BLOCKING (0)"}
ROUND1 = {"round": 1, "stateLines": "round: 1\nphase: pass\nreviewers: docs-sync-reviewer: never, deferred\nopen defects: none\nlaunches: 1",
          "logBlock": "### Round 1\n\nverifier: PASS\n\nBLOCKING (0)\n\nNON-BLOCKING (0)"}


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.wo = self.tmp / "checkout" / ".claude" / "workorders"
        self.wo.mkdir(parents=True)
        self.plan = self.wo / "zz-plan.md"
        self.ctx = self.wo / "zz-context.md"
        self.plan.write_text(PLAN, encoding="utf-8", newline="\n")
        self.ctx.write_text(CONTEXT, encoding="utf-8", newline="\n")
        self.projects = self.tmp / "projects" / "C--x" / "session-1" / "workflows"
        self.projects.mkdir(parents=True)

    def save_run(self, run_id="wf_abc12345-678", slug="zz", rounds=(ROUND0, ROUND1), record=True, args_slug=None):
        result = {"outcome": "PASS", "round": 1}
        if record:
            result["record"] = {"slug": slug, "planPath": ".claude/workorders/zz-plan.md",
                                "contextPath": ".claude/workorders/zz-context.md",
                                "checkoutRoot": str(self.tmp / "checkout"), "launch": 1,
                                "rounds": list(rounds), "state": ""}
        data = {"runId": run_id, "workflowName": "workorder-rounds", "status": "completed",
                "args": {"slug": args_slug or slug, "planPath": ".claude/workorders/zz-plan.md"}, "result": result}
        path = self.projects / f"{run_id}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def apply(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = workorder_record.main(["apply", *argv])
        return code, out.getvalue(), err.getvalue()

    def state(self):
        text = self.plan.read_text(encoding="utf-8")
        return text.split("## State\n")[1].split("\n## ")[0]

    def test_apply_merges_state_and_appends_each_log_block_once(self):
        path = self.save_run()
        code, out, err = self.apply("--run", str(path))
        self.assertEqual(code, 0, err)
        self.assertIn("applied round(s) 0, 1", out)
        state = self.state()
        lines = state.split("\n")
        self.assertIn("round: 1", lines)
        self.assertIn("phase: pass", lines, "the later round's value wins")
        self.assertNotIn("phase: plan", state, "the combined `round: 0  phase: plan` line is replaced, not kept")
        for kept in ("gates: `build: complete`", "round base: <none yet>", "agents: planner-tier=planner",
                     "decisions in force: D1 both repositories take `origin/main` by a merge\n  commit (never a rebase)"):
            self.assertIn(kept, state, "a line no round writes stays as it was")
        self.assertIn("launches: 1", lines)
        self.assertIn("last run: wf_abc12345-678", lines)
        self.assertIn("## Goal\ng\n", self.plan.read_text(encoding="utf-8"), "the section after State is intact")
        ctx = self.ctx.read_text(encoding="utf-8")
        self.assertTrue(ctx.startswith(CONTEXT.rstrip("\n")), "nothing before the append moved")
        self.assertIn("### Plan\nplanned it\n\n<!-- workorder-record run=wf_abc12345-678 round=0 -->\n### Round 0 (started", ctx)
        self.assertLess(ctx.index("round=0 -->"), ctx.index("round=1 -->"))
        self.assertTrue(ctx.rstrip("\n").endswith("NON-BLOCKING (0)"), "the last block is the end of the file")

    def test_reapplying_the_same_run_changes_nothing(self):
        path = self.save_run()
        self.assertEqual(self.apply("--run", str(path))[0], 0)
        plan, ctx = self.plan.read_bytes(), self.ctx.read_bytes()
        code, out, err = self.apply("--run", str(path))
        self.assertEqual(code, 0, err)
        self.assertIn("applied round(s) none; already present: 0, 1", out)
        self.assertEqual(self.plan.read_bytes(), plan)
        self.assertEqual(self.ctx.read_bytes(), ctx)

    def test_a_half_applied_run_is_completed_not_duplicated(self):
        # A crash after round 0's Log write: round 0 is skipped, round 1 lands.
        path = self.save_run()
        self.save_run(rounds=(ROUND0,))
        self.assertEqual(self.apply("--run", str(path).replace(".json", "") + ".json")[0], 0)
        ctx = self.ctx.read_text(encoding="utf-8")
        self.assertEqual(ctx.count("round=0 -->"), 1)
        self.save_run(rounds=(ROUND0, ROUND1))
        self.assertEqual(self.apply("--run", str(path))[0], 0)
        ctx = self.ctx.read_text(encoding="utf-8")
        self.assertEqual((ctx.count("round=0 -->"), ctx.count("round=1 -->")), (1, 1))

    def test_a_run_id_is_found_under_the_project_dir(self):
        self.save_run()
        for run in ("wf_abc12345-678", "abc12345-678"):
            self.plan.write_text(PLAN, encoding="utf-8", newline="\n")
            self.ctx.write_text(CONTEXT, encoding="utf-8", newline="\n")
            code, out, err = self.apply("--run", run, "--project-dir", str(self.tmp / "projects"))
            self.assertEqual(code, 0, err)
            self.assertIn("round=1 -->", self.ctx.read_text(encoding="utf-8"))

    def test_latest_takes_the_newest_run_of_this_workorder(self):
        import os
        import time
        old = self.save_run(run_id="wf_old00000-000", rounds=(ROUND0,))
        other = self.save_run(run_id="wf_oth00000-000", slug="yy", args_slug="yy")
        new = self.save_run(run_id="wf_new00000-000")
        now = time.time()
        os.utime(old, (now - 30, now - 30))
        os.utime(new, (now - 10, now - 10))
        os.utime(other, (now, now))  # the newest run overall is another workorder's
        code, out, err = self.apply("--latest", "--slug", "zz", "--project-dir", str(self.tmp / "projects"))
        self.assertEqual(code, 0, err)
        self.assertIn("wf_new00000-000", out)
        self.assertIn("last run: wf_new00000-000", self.state())
        code, _, err = self.apply("--latest", "--project-dir", str(self.tmp / "projects"))
        self.assertEqual(code, 2, "--latest needs --slug")
        code, _, err = self.apply("--latest", "--slug", "none", "--project-dir", str(self.tmp / "projects"))
        self.assertEqual(code, 3)

    def test_slug_mismatch_writes_nothing(self):
        path = self.save_run()
        code, _, err = self.apply("--run", str(path), "--slug", "other")
        self.assertEqual(code, 4)
        self.assertIn("'zz', not 'other'", err)
        path = self.save_run(args_slug="elsewhere")
        code, _, err = self.apply("--run", str(path))
        self.assertEqual(code, 4)
        self.assertEqual(self.plan.read_text(encoding="utf-8"), PLAN)
        self.assertEqual(self.ctx.read_text(encoding="utf-8"), CONTEXT)
        # The record's plan file must be the slug's own.
        path = self.save_run(slug="yy", args_slug="yy")
        code, _, err = self.apply("--run", str(path))
        self.assertEqual(code, 4)
        self.assertIn("not workorder 'yy'", err)

    def test_missing_record_is_refused(self):
        code, _, err = self.apply("--run", "wf_nope-000", "--project-dir", str(self.tmp / "projects"))
        self.assertEqual(code, 3)
        self.assertIn("no run record wf_nope-000.json", err)
        path = self.save_run(record=False)
        code, _, err = self.apply("--run", str(path))
        self.assertEqual(code, 3)
        self.assertIn("carries no `record`", err)
        self.assertEqual(self.ctx.read_text(encoding="utf-8"), CONTEXT)

    def test_crlf_files_stay_crlf_and_a_single_file_plan_takes_both(self):
        single = self.wo / "zz-plan.md"
        single.write_bytes((PLAN + "\n" + CONTEXT.split("# zz context\n\n", 1)[1]).replace("\n", "\r\n").encode("utf-8"))
        path = self.save_run()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["result"]["record"]["contextPath"] = ".claude/workorders/zz-plan.md"
        path.write_text(json.dumps(data), encoding="utf-8")
        code, out, err = self.apply("--run", str(path))
        self.assertEqual(code, 0, err)
        raw = single.read_bytes()
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""), "a bare LF crept into a CRLF file")
        text = raw.decode("utf-8").replace("\r\n", "\n")
        self.assertIn("phase: pass", text.split("## State\n")[1].split("\n## ")[0])
        self.assertIn("round=1 -->\n### Round 1", text)

    def test_state_merge_matches_the_scripts(self):
        old = workorder_record.state_entries("round: 0        phase: plan\ngates: none\nopen defects: a\n  more")
        self.assertEqual([k for k, _ in old], ["round", "phase", "gates", "open defects"])
        self.assertEqual(old[3][1], "open defects: a\n  more")
        merged = workorder_record.merge_state(old, workorder_record.state_entries("phase: pass\nround: 1\nlaunches: 2"))
        self.assertEqual([t for _, t in merged], ["round: 1", "phase: pass", "gates: none", "open defects: a\n  more", "launches: 2"])

    def test_apply_prints_what_the_launch_came_back_with(self):
        # #540: drivers wrote 68 inline scripts in a week to read run records.
        path = self.save_run()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["result"].update({
            "outcome": "AGENT-FAILED", "detail": "no result from: b: the implementer returned nothing",
            "items": [{"id": "a", "status": "done", "reason": ""},
                      {"id": "b", "status": "pending", "reason": ""},
                      {"id": "c", "status": "parked", "reason": "owner: which token?"},
                      {"id": "d", "status": "held", "reason": "after c, which is parked"}],
            "blocking": [{"reviewer": "instrument-blindness-reviewer", "where": "x"}],
            "unblocked": [{"id": "d", "reason": "after c", "route": "relaunch"}],
        })
        data["logs"] = ["[snapshot:r1] ok",
                        "[item-implementer:b:a1:r1] failed: You've hit your session limit · resets 1:40pm (Europe/Warsaw)"]
        path.write_text(json.dumps(data), encoding="utf-8")
        code, out, err = self.apply("--run", str(path))
        self.assertEqual(code, 0, err)
        self.assertIn("outcome: AGENT-FAILED -- no result from: b: the implementer returned nothing", out)
        self.assertIn("items: 1 done, 1 pending, 1 parked, 1 held", out)
        self.assertIn("  c: parked -- owner: which token?", out)
        self.assertNotIn("  a: done", out, "a done item is counted, not listed")
        self.assertIn("unblocked: d (after c -> relaunch)", out)
        self.assertIn("blocking: instrument-blindness-reviewer 1", out)
        self.assertIn("session limit: 1 agent(s) stopped on it, resets 1:40pm (Europe/Warsaw)", out)

    def test_no_session_limit_line_without_one_in_the_log(self):
        path = self.save_run()
        code, out, _ = self.apply("--run", str(path))
        self.assertEqual(code, 0)
        self.assertIn("outcome: PASS", out)
        self.assertNotIn("session limit", out, "control: a clean run's log names no limit")


if __name__ == "__main__":
    unittest.main()
