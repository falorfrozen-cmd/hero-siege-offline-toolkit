"""Tests for tools/workorder_speed.py, the /workorder speed report, and for
the `until` cutoff it adds to tools/workorder_audit.py's parser.

Every session here is synthetic, built in a temp directory with
tests/test_workorder_audit.py's helpers, in the real
`<projects>/<project>/<session>[...]` layout. Each measure gets a case that
counts and a control beside it that must not. Nothing reads `~/.claude`.
"""

import contextlib
import io
import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import test_workorder_audit as twa  # noqa: E402
import workorder_audit as wa  # noqa: E402
import workorder_speed as ws  # noqa: E402


def span(start, end, first_idx):
    """An agent that runs from `start` to `end` seconds after BASE."""
    return [twa.turn(start, first_idx), twa.turn(end, first_idx + 1)]


def shell(offset, idx, command, result="ok", duration=1.0, is_error=False, name="Bash"):
    mid, tuid = f"msg-{idx:04d}", f"tool-{idx:04d}"
    return [twa.assistant_tool_use(offset, mid, tuid, name, {"command": command}),
            twa.user_tool_result(offset + duration, tuid, result, is_error=is_error)]


def edit(offset, idx):
    return twa.tool_turn(offset, idx, "Edit", {"file_path": "x.py", "old_string": "a", "new_string": "b"})


def prompt(offset, text):
    """A subagent's first record: its prompt, which carries no `origin`."""
    return twa.user_text(offset, text, origin_kind=None)


class SpeedCase(twa.TempDirMixin, unittest.TestCase):
    def builder(self, session_id="ssn00000-0000-0000-0000-000000000000"):
        return twa.SessionBuilder(self.tmp_path, session_id=session_id)

    def transcript(self, b):
        projects = b.build()
        return projects / b.project / f"{b.session_id}.jsonl"

    def launch_file(self, b, wf_id, args):
        path = b.projects_dir / b.project / b.session_id / "workflows" / f"{wf_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"runId": wf_id, "workflowName": "workorder-rounds", "args": args}),
                        encoding="utf-8")

    def report(self, b, until=None, plan=None):
        return ws.build([self.transcript(b)], [], until, plan)

    def aggregate(self, b, **kw):
        return self.report(b, **kw)["aggregate"]

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ws.main(argv)
        return code, out.getvalue(), err.getvalue()


class ConcurrencyTests(SpeedCase):
    def test_overlapping_agents_raise_concurrency_and_the_parallel_share(self):
        b = self.builder().driver([twa.turn(0, 0), twa.turn(1000, 1)])
        b.subagent("planner", "Plan it", span(100, 500, 10))
        b.subagent("implementer", "implementer:r0", span(300, 700, 20))
        a = self.aggregate(b)
        self.assertEqual(a["busy_minutes"], round(1000 / 60, 1))
        self.assertEqual(a["serial_minutes"], round(800 / 60, 1))
        self.assertEqual(a["concurrency"], 0.8)
        self.assertEqual(a["single_agent_share"], 0.4)
        self.assertEqual(a["parallel_share"], 0.2)
        self.assertEqual(a["phases"]["plan"]["sole_minutes"], round(200 / 60, 3))
        self.assertEqual(a["phases"]["implement"]["agents"], 1)

    def test_serial_agents_never_count_as_parallel(self):
        b = self.builder().driver([twa.turn(0, 0), twa.turn(1000, 1)])
        b.subagent("planner", "Plan it", span(100, 300, 10))
        b.subagent("implementer", "implementer:r0", span(400, 600, 20))
        a = self.aggregate(b)
        self.assertEqual(a["concurrency"], 0.4)
        self.assertEqual(a["single_agent_share"], 0.4)
        self.assertEqual(a["parallel_share"], 0.0)

    def test_a_long_away_gap_leaves_busy_time(self):
        away = 3 * 3600
        b = self.builder().driver([twa.turn(0, 0), twa.user_text(away, "back"), twa.turn(away + 60, 1)])
        b.subagent("planner", "Plan it", span(away + 10, away + 50, 10))
        a = self.aggregate(b)
        self.assertEqual(a["span_minutes"], round((away + 60) / 60, 1))
        self.assertEqual(a["busy_minutes"], 1.0)
        self.assertIn("waiting human [>2h]", a["phases"]["waits"])

    def test_the_aggregate_divides_the_sums(self):
        one = self.builder("ssn11111-0000-0000-0000-000000000000").driver([twa.turn(0, 0), twa.turn(1000, 1)])
        one.subagent("planner", "Plan it", span(0, 1000, 10))
        two = self.builder("ssn22222-0000-0000-0000-000000000000").driver([twa.turn(0, 0), twa.turn(3000, 1)])
        two.subagent("planner", "Plan it", span(0, 1000, 10))
        report = ws.build([self.transcript(one), self.transcript(two)], [], None, None)
        self.assertEqual(report["aggregate"]["sessions"], 2)
        self.assertEqual(report["aggregate"]["concurrency"], 0.5)  # 2000 s of agents over 4000 s busy
        self.assertEqual([s["concurrency"] for s in report["sessions"]], [1.0, 0.333])


class OwnerWaitTests(SpeedCase):
    def test_a_typed_message_ends_an_owner_wait(self):
        b = self.builder().driver([twa.turn(0, 0), twa.user_text(600, "go on"), twa.turn(610, 1)])
        b.subagent("planner", "Plan it", span(1000, 1100, 10))
        blocks = self.aggregate(b)["owner_blocks"]
        self.assertEqual(blocks["count"], 1)
        self.assertEqual(blocks["total_minutes"], 10.0)
        self.assertEqual(blocks["top"], [10.0])

    def test_an_ask_user_question_answer_ends_an_owner_wait(self):
        b = self.builder().driver(
            twa.tool_turn(0, 0, "AskUserQuestion", {"questions": []}, result_offset=900) + [twa.turn(910, 1)])
        b.subagent("planner", "Plan it", span(1000, 1100, 10))
        blocks = self.aggregate(b)["owner_blocks"]
        self.assertEqual((blocks["count"], blocks["total_minutes"]), (1, 15.0))

    def test_a_queued_typed_message_ends_an_owner_wait(self):
        queued = {"type": "queue-operation", "operation": "enqueue", "timestamp": twa.ts(300), "content": "stop"}
        b = self.builder().driver([twa.turn(0, 0), queued, twa.turn(310, 1)])
        b.subagent("planner", "Plan it", span(1000, 1100, 10))
        self.assertEqual(self.aggregate(b)["owner_blocks"]["count"], 1)

    def test_controls_a_gap_while_an_agent_runs_a_shell_result_and_a_short_gap(self):
        b = self.builder().driver(
            [twa.turn(0, 0), twa.user_text(600, "go on")]
            + shell(700, 1, "sleep 200", duration=300)
            + [twa.user_text(1060, "quick")])
        b.subagent("planner", "Plan it", span(100, 700, 10))
        blocks = self.aggregate(b)["owner_blocks"]
        self.assertEqual(blocks["count"], 0)


class QueueTests(SpeedCase):
    def items_session(self, c_start, args):
        b = self.builder().driver([twa.turn(0, 0), twa.turn(400, 1)])
        b.workflow_agent("wf_q", "implementer", "item-implementer:a:a1:r0", span(0, 100, 10))
        b.workflow_agent("wf_q", "implementer", "item-implementer:b:a1:r0", span(0, 200, 20))
        b.workflow_agent("wf_q", "implementer", "item-implementer:c:a1:r0", span(c_start, 300, 30))
        if args is not None:
            self.launch_file(b, "wf_q", args)
        return b

    def test_a_start_right_after_an_end_at_the_cap_is_queued(self):
        a = self.aggregate(self.items_session(102, {"slug": "zz", "round": 0, "maxParallel": 2}))
        launch = a["launches"][0]
        self.assertEqual((launch["slug"], launch["round"], launch["cap"]), ("zz", 0, 2))
        self.assertEqual(a["items"], {"max_concurrent": 2, "queued_behind_cap": 1})
        self.assertEqual(launch["minutes_at_cap"], round(198 / 60, 3))
        self.assertEqual(launch["items"], 3)

    def test_a_start_while_a_slot_is_free_is_not_queued(self):
        a = self.aggregate(self.items_session(150, {"slug": "zz", "round": 0, "maxParallel": 2}))
        self.assertEqual(a["items"]["queued_behind_cap"], 0)

    def test_without_a_launch_file_the_cap_is_the_engine_default(self):
        a = self.aggregate(self.items_session(102, None))
        launch = a["launches"][0]
        self.assertEqual((launch["cap"], launch["slug"], launch["round"]), (ws.DEFAULT_CAP, None, None))
        self.assertEqual(a["items"]["queued_behind_cap"], 0)

    def test_an_item_window_runs_to_its_verifier_and_fixes_count(self):
        b = self.builder().driver([twa.turn(0, 0), twa.turn(400, 1)])
        b.workflow_agent("wf_q", "implementer", "item-implementer:a:a1:r0", span(0, 100, 10))
        b.workflow_agent("wf_q", "verifier", "item-verifier:a:a1:r0", span(101, 200, 20))
        b.workflow_agent("wf_q", "implementer", "fix-implementer:fix-1:r0", span(150, 250, 30))
        launch = self.aggregate(b)["launches"][0]
        self.assertEqual(launch["max_concurrent"], 2)
        self.assertEqual(launch["items"], 1)


class VerifyTests(SpeedCase):
    def test_item_reach_and_full_verifies(self):
        b = self.builder().driver([twa.turn(0, 0), twa.turn(900, 1)])
        b.workflow_agent("wf_v", "verifier", "item-verifier:a:a1:r0", [prompt(10, "check item a")] + span(11, 20, 10))
        b.workflow_agent("wf_v", "verifier", "verifier:r1",
                         [prompt(30, "run_criteria.py plan --changed-since base")] + span(31, 40, 20))
        b.workflow_agent("wf_v", "verifier", "verifier:r0", [prompt(50, "run every criterion")] + span(51, 60, 30))
        b.workflow_agent("wf_v", "implementer", "item-implementer:a:a1:r0",
                         [prompt(1, "use --changed-since")] + span(2, 9, 40))
        b.workflow_agent("wf_v", "verifier", "verifier:g2:r1", [prompt(90, "gate")] + span(91, 99, 50))
        a = self.aggregate(b)
        self.assertEqual(a["verifies"], {"full": 2, "reach": 1, "item": 1})
        self.assertEqual(a["launches"][0]["gate_runs"], 3)


class RunCriteriaTests(SpeedCase):
    def test_killed_calls_against_one_that_finished(self):
        records = (span(0, 1, 10)
                   + shell(10, 1, "py -3 tools/run_criteria.py p.md --jobs auto", duration=600)
                   + shell(700, 2, "py -3 tools/run_criteria.py p.md --jobs auto", duration=12,
                           result="Command did not complete within its 600s timeout and was moved to the background")
                   + shell(800, 3, "py -3 tools/run_criteria.py p.md --jobs auto", duration=30)
                   + shell(900, 4, "py -3 tools/run_criteria.py p.md --item a --jobs auto", duration=61)
                   + shell(1000, 5, "git status", duration=700))
        b = self.builder().driver([twa.turn(0, 0), twa.turn(2000, 1)])
        b.subagent("implementer", "implementer:r0", records)
        rc = self.aggregate(b)["run_criteria"]
        self.assertEqual(rc, {"calls": 4, "killed": 2, "max_seconds": 600.0, "item_max_seconds": 61.0})


class CaughtTests(SpeedCase):
    def test_a_failing_check_then_an_edit_is_caught_and_the_controls_are_not(self):
        b = self.builder().driver([twa.turn(0, 0), twa.turn(2000, 1)])
        b.subagent("implementer", "implementer:a:r0",
                   shell(10, 1, "py -3 -m unittest tests.x", result="FAILED (failures=1)") + edit(20, 2))
        b.subagent("implementer", "implementer:b:r0",
                   shell(10, 1, "npm test", result="boom", is_error=True) + twa.tool_turn(20, 2, "Read", {"file_path": "x"}))
        b.subagent("implementer", "implementer:c:r0",
                   shell(10, 1, "py -3 -m pytest", result="Ran 3 tests\nOK EXIT=0") + edit(20, 2))
        b.subagent("implementer", "implementer:d:r0",
                   edit(5, 1) + shell(10, 2, "py -3 tools/run_criteria.py p.md", result="  `x` -> exit 1 (3s)"))
        b.subagent("implementer", "implementer:e:r0", edit(5, 1))
        b.subagent("verifier", "verifier:r0",
                   shell(10, 1, "py -3 -m unittest", result="FAILED") + edit(20, 2))
        checks = self.aggregate(b)["implementer_checks"]
        self.assertEqual(checks, {"implementers": 5, "ran_check": 4, "caught": 1, "rate": 0.25})


class UntilTests(SpeedCase):
    def test_until_drops_later_records_agents_and_launches(self):
        b = self.builder().driver([twa.turn(0, 0), twa.turn(500, 1), twa.turn(2000, 2)])
        b.subagent("planner", "Plan it", span(100, 400, 10))
        b.subagent("planner", "amendment: zz later", span(1500, 1800, 20))
        b.workflow_agent("wf_late", "implementer", "item-implementer:a:a1:r0", span(1600, 1700, 30))
        b.subagent("implementer", "implementer:r0", span(900, 1200, 40))
        until = twa.BASE + timedelta(seconds=1000)
        report = self.report(b, until=until)
        a = report["aggregate"]
        self.assertEqual(report["until"], "2026-09-18T12:16:40Z")
        self.assertEqual(report["sessions"][0]["last_event"], "2026-09-18T12:15:00Z")
        self.assertEqual(a["serial_minutes"], 5.0)  # 300 s planned, the implementer cut at 900 s
        self.assertEqual(a["routes"]["amendments"], 0)
        self.assertEqual(a["launches"], [])
        full = self.aggregate(b)
        self.assertEqual(full["routes"]["amendments"], 1)
        self.assertEqual(len(full["launches"]), 1)

    def test_parse_transcript_cutoff_and_its_default(self):
        path = self.tmp_path / "t.jsonl"
        twa.write_jsonl(path, span(0, 100, 0) + shell(200, 5, "ls") + [{"type": "summary", "summary": "x"}])
        whole = wa.parse_transcript(path, "implementer", "x", "s")
        cut = wa.parse_transcript(path, "implementer", "x", "s", until=twa.BASE + timedelta(seconds=150))
        self.assertEqual((whole.turn_count, len(whole.tool_calls)), (3, 1))
        self.assertEqual((cut.turn_count, len(cut.tool_calls)), (2, 0))
        self.assertEqual(cut.ts_last, twa.BASE + timedelta(seconds=100))

    def test_a_project_dir_session_whose_agents_all_start_later_is_left_out(self):
        early = self.builder("ssn11111-0000-0000-0000-000000000000").driver([twa.turn(0, 0), twa.turn(50, 1)])
        early.subagent("planner", "Plan it", span(10, 40, 10))
        early.build()
        late = self.builder("ssn22222-0000-0000-0000-000000000000").driver([twa.turn(0, 0), twa.turn(900, 1)])
        late.subagent("planner", "Plan it", span(600, 800, 10))
        late.build()
        bare = self.builder("ssn33333-0000-0000-0000-000000000000").driver([twa.turn(0, 0)])
        bare.build()
        project_dir = self.tmp_path / "projects" / "proj"
        self.assertEqual(ws.build([], [project_dir], None, None)["aggregate"]["sessions"], 2)
        until = twa.BASE + timedelta(seconds=100)
        self.assertEqual(ws.build([], [project_dir], until, None)["aggregate"]["sessions"], 1)


class RoutesAndPhasesTests(SpeedCase):
    def test_routes_and_record_phase(self):
        b = self.builder().driver([twa.turn(0, 0), twa.turn(900, 1)])
        b.subagent("planner", "amendment: zz fix path", span(10, 20, 10))
        b.subagent("planner", "Replan zz after defect", span(30, 40, 20))
        b.subagent("planner", "Plan zz", span(50, 60, 30))
        b.subagent("consultant", "Consult on hook", span(70, 80, 40))
        b.workflow_agent("wf_r", "planner", "amendment: zz a:r0", span(90, 100, 50))
        b.workflow_agent("wf_r", "workflow-subagent", "snapshot:r0", span(110, 120, 60))
        b.workflow_agent("wf_r", "workflow-subagent", "amend-check:a:r0", span(130, 140, 70))
        b.workflow_agent("wf_r", "workflow-subagent", "something:r0", span(150, 160, 80))
        a = self.aggregate(b)
        self.assertEqual(a["routes"], {"amendments": 2, "amendments_in_workflow": 1, "replans": 1, "consultations": 1})
        phases = a["phases"]
        self.assertEqual([phases[p]["agents"] for p in ("plan", "amend", "replan", "consult", "record", "other")],
                         [1, 2, 1, 1, 2, 1])

    def test_finding_to_fix_minutes(self):
        b = self.builder().driver([twa.turn(0, 0), twa.turn(900, 1)])
        b.workflow_agent("wf_f", "implementer", "item-implementer:a:a1:r0", span(0, 50, 10))
        b.workflow_agent("wf_f", "docs-sync-reviewer", "docs-sync-reviewer:p1:r0", span(55, 100, 20))
        b.workflow_agent("wf_f", "implementer", "fix-implementer:fix-1:r0", span(160, 200, 30))
        b.workflow_agent("wf_f", "implementer", "fix-implementer:gate-fix-1:r0", span(300, 320, 40))
        self.assertEqual(self.aggregate(b)["launches"][0]["finding_to_fix_minutes"], [1.0])


PLAN = """# x

## Goal
owner: not an item

## Steps

### Item: a — first
files: `a.py`
owner: which colour
default: blue
reversible: yes

1. do it
   owner: a step line, not a field

### Item: b — second
files: `b.py`
owner: which size
default:

### Item: c — third
files: `c.py`

## Log
"""


class PlanTests(SpeedCase):
    def test_owner_items_with_default_and_reversible(self):
        plan = self.tmp_path / "zz-plan.md"
        plan.write_text(PLAN, encoding="utf-8")
        b = self.builder().driver([twa.turn(0, 0), twa.turn(10, 1)])
        block = self.report(b, plan=plan)["plan"]
        self.assertEqual({k: block[k] for k in ("items", "owner_items", "with_default", "with_reversible")},
                         {"items": 3, "owner_items": 2, "with_default": 1, "with_reversible": 1})


class CliTests(SpeedCase):
    def test_json_output_keys(self):
        b = self.builder().driver([twa.turn(0, 0), twa.turn(100, 1)])
        b.subagent("planner", "Plan it", span(10, 40, 10))
        code, out, _ = self.run_main(["--transcript", str(self.transcript(b)), "--json"])
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(set(report), {"generated_utc", "until", "sessions", "aggregate"})
        keys = {"span_minutes", "busy_minutes", "serial_minutes", "concurrency", "single_agent_share",
                "parallel_share", "phases", "launches", "items", "verifies", "run_criteria",
                "owner_blocks", "implementer_checks", "routes", "lanes"}
        self.assertLessEqual(keys, set(report["aggregate"]))
        self.assertLessEqual(keys | {"path", "first_event", "last_event"}, set(report["sessions"][0]))

    def test_text_output(self):
        b = self.builder().driver([twa.turn(0, 0), twa.turn(100, 1)])
        code, out, _ = self.run_main(["--transcript", str(self.transcript(b))])
        self.assertEqual(code, 0)
        self.assertIn("aggregate over 1 session(s)", out)

    def test_usage_errors_exit_2(self):
        b = self.builder().driver([twa.turn(0, 0), twa.turn(100, 1)])
        good = str(self.transcript(b))
        empty_dir = self.tmp_path / "empty"
        empty_dir.mkdir()
        cases = [
            [],
            ["--transcript", str(self.tmp_path / "missing.jsonl")],
            ["--project-dir", str(self.tmp_path / "nowhere")],
            ["--project-dir", str(empty_dir)],
            ["--transcript", good, "--until", "yesterday"],
            ["--transcript", good, "--until", "2026-01-01T00:00:00Z"],
            ["--transcript", good, "--plan", str(self.tmp_path / "no-plan.md")],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                code, out, err = self.run_main(argv)
                self.assertEqual(code, 2)
                self.assertIn("usage error", err)
                self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
