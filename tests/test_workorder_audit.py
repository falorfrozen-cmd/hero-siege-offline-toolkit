"""Tests for tools/workorder_audit.py -- the /workorder cost-rule gate
(`.claude/workorders/COST-GATE-SPEC.md` §2 / `AGENTS.md`).

Every rule gets a synthetic FAIL fixture and a synthetic PASS control built
from the same helpers, plus dedicated coverage for message-id dedupe (the
thing `COST-GATE-SPEC.md` §1 warns rows repeat per content block) and
workflow-subdirectory discovery. Fixtures are built in code, in a temp
directory, matching the real `~/.claude/projects/<project>/<session>...`
layout closely enough for the parser to treat them exactly like a real
transcript -- nothing here special-cases "test mode" in the tool itself.
"""

import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import workorder_audit as wa  # noqa: E402


BASE = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)


def ts(seconds_offset: float) -> str:
    t = BASE + timedelta(seconds=seconds_offset)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def assistant_text(offset, message_id, input_tokens=100, cache_creation=0,
                    cache_read=0, output_tokens=50, block_index=0):
    return {
        "type": "assistant",
        "timestamp": ts(offset),
        "apiBlockIndex": block_index,
        "message": {
            "id": message_id,
            "usage": {
                "input_tokens": input_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
                "output_tokens": output_tokens,
            },
            "content": [{"type": "text", "text": "..."}],
        },
    }


def assistant_tool_use(offset, message_id, tool_use_id, name, tool_input,
                        input_tokens=100, cache_creation=0, cache_read=0,
                        output_tokens=50, block_index=0):
    return {
        "type": "assistant",
        "timestamp": ts(offset),
        "apiBlockIndex": block_index,
        "message": {
            "id": message_id,
            "usage": {
                "input_tokens": input_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
                "output_tokens": output_tokens,
            },
            "content": [{"type": "tool_use", "id": tool_use_id, "name": name, "input": tool_input}],
        },
    }


def user_tool_result(offset, tool_use_id, content, is_error=False):
    return {
        "type": "user",
        "timestamp": ts(offset),
        "message": {
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": content, "is_error": is_error}],
        },
    }


def turn(offset, idx, **kw):
    """One assistant text-only turn with a fresh message id."""
    return assistant_text(offset, f"msg-{idx:04d}", **kw)


def tool_turn(offset, idx, name, tool_input, result="ok", result_offset=None,
              input_tokens=100, cache_creation=0, cache_read=0, output_tokens=50):
    """A tool_use turn plus its paired tool_result, as a 2-record list."""
    mid = f"msg-{idx:04d}"
    tuid = f"tool-{idx:04d}"
    use = assistant_tool_use(offset, mid, tuid, name, tool_input,
                              input_tokens=input_tokens, cache_creation=cache_creation,
                              cache_read=cache_read, output_tokens=output_tokens)
    res = user_tool_result(result_offset if result_offset is not None else offset + 0.5, tuid, result)
    return [use, res]


def write_jsonl(path: Path, records) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def write_meta(path: Path, agent_type, description) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"agentType": agent_type, "description": description}), encoding="utf-8")


class SessionBuilder:
    """Builds a `<projects_dir>/<project>/<session>[...]` tree matching the
    real layout COST-GATE-SPEC.md §2 describes."""

    def __init__(self, tmp_path: Path, project="proj", session_id="ssn00000-0000-0000-0000-000000000000"):
        self.tmp_path = Path(tmp_path)
        self.projects_dir = self.tmp_path / "projects"
        self.project = project
        self.session_id = session_id
        self.driver_records = []
        self._n = 0

    def _next_agent_id(self) -> str:
        self._n += 1
        return f"a{self._n:016x}"

    def driver(self, records):
        self.driver_records = records
        return self

    def subagent(self, agent_type, description, records, agent_id=None):
        agent_id = agent_id or self._next_agent_id()
        session_dir = self.projects_dir / self.project / self.session_id
        write_jsonl(session_dir / "subagents" / f"agent-{agent_id}.jsonl", records)
        write_meta(session_dir / "subagents" / f"agent-{agent_id}.meta.json", agent_type, description)
        return self

    def workflow_agent(self, wf_id, agent_type, description, records, agent_id=None):
        agent_id = agent_id or self._next_agent_id()
        session_dir = self.projects_dir / self.project / self.session_id
        base = session_dir / "subagents" / "workflows" / wf_id / f"agent-{agent_id}"
        write_jsonl(base.with_suffix(".jsonl"), records)
        write_meta(Path(str(base) + ".meta.json"), agent_type, description)
        return self

    def build(self):
        write_jsonl(self.projects_dir / self.project / f"{self.session_id}.jsonl", self.driver_records)
        return self.projects_dir

    def evaluate(self):
        projects_dir = self.build()
        session_path = projects_dir / self.project / f"{self.session_id}.jsonl"
        session = wa.discover_session(projects_dir, self.project, self.session_id, session_path)
        return session, wa.evaluate(session)

    def run_main(self, extra_args=()):
        self.build()
        return wa.main([
            "--session", self.session_id,
            "--projects-dir", str(self.projects_dir),
            "--project", self.project,
            *extra_args,
        ])


def get_rule(results, rule_id):
    for r in results:
        if r.rule_id == rule_id:
            return r
    raise AssertionError(f"no such rule: {rule_id}")


class TempDirMixin:
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="workorder_audit_test_")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.tmp_path = Path(self._tmp)


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------

class MangleProjectDirTests(unittest.TestCase):
    def test_main_checkout(self):
        self.assertEqual(
            wa.mangle_project_dir(r"C:\Users\Administrator\PycharmProjects\hero-siege-offline-toolkit"),
            "C--Users-Administrator-PycharmProjects-hero-siege-offline-toolkit",
        )

    def test_worktree(self):
        self.assertEqual(
            wa.mangle_project_dir(
                r"C:\Users\Administrator\PycharmProjects\hero-siege-offline-toolkit\.claude\worktrees\foo-1a2b3c"
            ),
            "C--Users-Administrator-PycharmProjects-hero-siege-offline-toolkit--claude-worktrees-foo-1a2b3c",
        )


class ReadKindTests(unittest.TestCase):
    def test_plan(self):
        self.assertEqual(wa.read_kind("C:/x/foo-plan.md"), "plan")

    def test_context(self):
        self.assertEqual(wa.read_kind("C:/x/foo-context.md"), "context")

    def test_instructions(self):
        self.assertEqual(wa.read_kind("docs/submodules/ForgePact/instructions.md"), "instructions")

    def test_source(self):
        self.assertEqual(wa.read_kind("ForgePact/plugin/ModuleMain.cpp"), "source")


class ParseLabelTests(unittest.TestCase):
    def test_with_round(self):
        self.assertEqual(wa.parse_label("implementer:r1"), ("implementer", 1))

    def test_without_round(self):
        self.assertEqual(wa.parse_label("Plan prospectprobe idcheck pin hardening"), (
            "Plan prospectprobe idcheck pin hardening", None))

    def test_none(self):
        self.assertEqual(wa.parse_label(None), ("", None))


# --------------------------------------------------------------------------
# Message-id dedupe
# --------------------------------------------------------------------------

class DedupeTests(TempDirMixin, unittest.TestCase):
    def test_repeated_message_id_counts_as_one_turn(self):
        """Same message.id across multiple content-block lines (as real
        transcripts stream them) must count as ONE turn, with output_tokens
        taken from the last (cumulative) block, not summed across blocks."""
        records = [
            assistant_text(0, "msg-A", input_tokens=5, cache_creation=1000, cache_read=0,
                            output_tokens=5, block_index=0),
            assistant_text(0.2, "msg-A", input_tokens=5, cache_creation=1000, cache_read=0,
                            output_tokens=240, block_index=1),
            assistant_text(1, "msg-B", input_tokens=5, cache_creation=500, cache_read=0, output_tokens=10),
        ]
        b = SessionBuilder(self.tmp_path).driver(records).subagent(
            "implementer", "impl", records)
        session, _ = b.evaluate()
        impl = session.subagents[0]
        self.assertEqual(impl.turn_count, 2)
        self.assertEqual(impl.total_tokens, (5 + 1000) + (5 + 500))
        self.assertEqual(impl.total_output_tokens, 240 + 10)

    def test_driver_dedupe_too(self):
        records = [
            assistant_text(0, "msg-A", input_tokens=2, cache_creation=100, output_tokens=1, block_index=0),
            assistant_text(0.1, "msg-A", input_tokens=2, cache_creation=100, output_tokens=99, block_index=1),
        ]
        b = SessionBuilder(self.tmp_path).driver(records)
        session, _ = b.evaluate()
        self.assertEqual(session.driver.turn_count, 1)
        self.assertEqual(session.driver.total_output_tokens, 99)


# --------------------------------------------------------------------------
# Workflow-subdirectory discovery
# --------------------------------------------------------------------------

class DiscoveryTests(TempDirMixin, unittest.TestCase):
    def test_direct_and_workflow_subagents_both_found(self):
        b = SessionBuilder(self.tmp_path)
        b.driver([turn(0, 0)])
        b.subagent("planner", "Plan the thing", [turn(0, 1)])
        b.workflow_agent("wf_aaa", "implementer", "implementer:r0", [turn(0, 2)])
        b.workflow_agent("wf_aaa", "verifier", "verifier:r0", [turn(0, 3)])
        b.workflow_agent("wf_bbb", "implementer", "implementer:r1", [turn(0, 4)])
        session, _ = b.evaluate()

        self.assertEqual(len(session.subagents), 1)
        self.assertEqual(session.subagents[0].agent_type, "planner")
        self.assertEqual(session.subagents[0].round, None)

        self.assertEqual(set(session.workflow_runs.keys()), {"wf_aaa", "wf_bbb"})
        self.assertEqual(len(session.workflow_runs["wf_aaa"]), 2)
        rounds = {a.round for a in session.workflow_runs["wf_aaa"]}
        self.assertEqual(rounds, {0})
        self.assertEqual(session.workflow_runs["wf_bbb"][0].round, 1)

    def test_no_subagents_dir_is_fine(self):
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)])
        session, results = b.evaluate()
        self.assertEqual(session.subagents, [])
        self.assertEqual(session.workflow_runs, {})
        # Every rule should still evaluate cleanly with nothing to flag.
        for r in results:
            self.assertTrue(r.passed, f"{r.rule_id} unexpectedly failed with no subagents")


# --------------------------------------------------------------------------
# R1 reviewer-reads-workorder
# --------------------------------------------------------------------------

class R1Tests(TempDirMixin, unittest.TestCase):
    def test_fail_reviewer_reads_plan(self):
        records = tool_turn(0, 0, "Read", {"file_path": "C:/x/foo-plan.md"}, result="plan text")
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent(
            "docs-sync-reviewer", "docs-sync-reviewer:r0", records)
        _, results = b.evaluate()
        r = get_rule(results, "R1")
        self.assertFalse(r.passed)
        self.assertTrue(any("foo-plan.md" in e for e in r.evidence))

    def test_fail_reviewer_greps_plan(self):
        records = tool_turn(0, 0, "Bash", {"command": "grep -n TODO foo-plan.md"}, result="1:TODO")
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent(
            "decompile-output-guard", "decompile-output-guard:r0", records)
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R1").passed)

    def test_pass_instrument_blindness_reads_context(self):
        records = tool_turn(0, 0, "Read", {"file_path": "C:/x/foo-context.md"}, result="context text")
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent(
            "instrument-blindness-reviewer", "instrument-blindness-reviewer:r0", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R1").passed)

    def test_pass_reviewer_reads_source(self):
        records = tool_turn(0, 0, "Read", {"file_path": "ForgePact/plugin/ModuleMain.cpp"}, result="source")
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent(
            "docs-sync-reviewer", "docs-sync-reviewer:r0", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R1").passed)


# --------------------------------------------------------------------------
# R2 verifier-scope
# --------------------------------------------------------------------------

class R2Tests(TempDirMixin, unittest.TestCase):
    def test_fail_whole_context_read(self):
        records = tool_turn(0, 0, "Read", {"file_path": "C:/x/foo-context.md"}, result="x" * 100)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("verifier", "verifier:r0", records)
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R2").passed)

    def test_fail_whole_plan_read_over_30kb(self):
        big = "x" * (31 * 1024)
        records = tool_turn(0, 0, "Read", {"file_path": "C:/x/foo-plan.md"}, result=big)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("verifier", "verifier:r0", records)
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R2").passed)

    def test_pass_context_read_with_offset(self):
        records = tool_turn(0, 0, "Read", {"file_path": "C:/x/foo-context.md", "offset": 100}, result="x" * 100)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("verifier", "verifier:r0", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R2").passed)

    def test_pass_small_whole_plan_read(self):
        records = tool_turn(0, 0, "Read", {"file_path": "C:/x/foo-plan.md"}, result="x" * 1024)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("verifier", "verifier:r0", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R2").passed)


# --------------------------------------------------------------------------
# R3 guide-whole
# --------------------------------------------------------------------------

class R3Tests(TempDirMixin, unittest.TestCase):
    def test_fail_over_60kb_instructions(self):
        big = "x" * (61 * 1024)
        records = tool_turn(0, 0, "Read", {"file_path": "docs/submodules/ForgePact/instructions.md"}, result=big)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("implementer", "impl", records)
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R3").passed)

    def test_pass_under_60kb_instructions(self):
        small = "x" * (10 * 1024)
        records = tool_turn(0, 0, "Read", {"file_path": "docs/submodules/ForgePact/instructions.md"}, result=small)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("implementer", "impl", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R3").passed)


# --------------------------------------------------------------------------
# R4 batching
# --------------------------------------------------------------------------

class R4Tests(TempDirMixin, unittest.TestCase):
    def _small_shell_run(self, start_offset, count, gap=5, start_idx=0):
        records = []
        off = start_offset
        for i in range(count):
            records += tool_turn(off, start_idx + i, "Bash", {"command": f"echo {i}"}, result="ok")
            off += gap
        return records, off

    def test_fail_over_20pct_batchable(self):
        # 10 turns total: 5 form one qualifying run (4 of them "batchable"),
        # 5 are unrelated single Read calls far apart -> 4/10 = 40% > 20%.
        shell_records, off = self._small_shell_run(0, 5, gap=5, start_idx=0)
        other = []
        idx = 5
        for _ in range(5):
            other += tool_turn(off, idx, "Read", {"file_path": "some/file.py"}, result="x" * 4000)
            off += 60  # far apart, and Read isn't a shell tool -> breaks/no run
            idx += 1
        records = shell_records + other
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent(
            "implementer", "implementer:r0", records)
        _, results = b.evaluate()
        r = get_rule(results, "R4")
        self.assertFalse(r.passed)
        self.assertTrue(any("40%" in e for e in r.evidence))

    def test_pass_under_20pct_batchable(self):
        # Same 5 shell calls, but spaced >20s apart -> no run forms at all.
        records = []
        off = 0
        for i in range(10):
            records += tool_turn(off, i, "Bash", {"command": f"echo {i}"}, result="ok")
            off += 30
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent(
            "implementer", "implementer:r0", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R4").passed)

    def test_edit_between_breaks_the_run(self):
        records = []
        off = 0
        idx = 0
        for i in range(2):
            records += tool_turn(off, idx, "Bash", {"command": f"echo {i}"}, result="ok")
            off += 5
            idx += 1
        records += tool_turn(off, idx, "Edit", {"file_path": "x.py"}, result="edited")
        off += 5
        idx += 1
        for i in range(2):
            records += tool_turn(off, idx, "Bash", {"command": f"echo {i}"}, result="ok")
            off += 5
            idx += 1
        # Two runs of length 2 each (below BATCHABLE_MIN_RUN=3) -> nothing counted.
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent(
            "implementer", "implementer:r0", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R4").passed)

    def test_non_implementer_not_checked(self):
        shell_records, _ = self._small_shell_run(0, 5, gap=5)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent(
            "verifier", "verifier:r0", shell_records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R4").passed)


# --------------------------------------------------------------------------
# R5 blocking-call
# --------------------------------------------------------------------------

class R5Tests(TempDirMixin, unittest.TestCase):
    def test_fail_call_over_240s(self):
        records = tool_turn(0, 0, "Bash", {"command": "sleep 300"}, result="done", result_offset=300)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("implementer", "impl", records)
        _, results = b.evaluate()
        r = get_rule(results, "R5")
        self.assertFalse(r.passed)
        self.assertTrue(any("300s" in e for e in r.evidence))

    def test_pass_call_under_240s(self):
        records = tool_turn(0, 0, "Bash", {"command": "echo hi"}, result="hi", result_offset=10)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("implementer", "impl", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R5").passed)

    def test_agent_dispatch_exempt(self):
        records = tool_turn(0, 0, "Agent", {"subagent_type": "implementer"}, result="IMPL-DONE",
                             result_offset=900)
        b = SessionBuilder(self.tmp_path).driver(records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R5").passed)


# --------------------------------------------------------------------------
# R6 planner-rewrite
# --------------------------------------------------------------------------

class R6Tests(TempDirMixin, unittest.TestCase):
    def test_fail_rewrites_same_plan(self):
        records = (
            tool_turn(0, 0, "Write", {"file_path": "C:/x/foo-plan.md", "content": "v1"}, result="ok")
            + tool_turn(10, 1, "Write", {"file_path": "C:/x/foo-plan.md", "content": "v2"}, result="ok")
        )
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("planner", "planner", records)
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R6").passed)

    def test_pass_writes_plan_and_context_once_each(self):
        records = (
            tool_turn(0, 0, "Write", {"file_path": "C:/x/foo-plan.md", "content": "v1"}, result="ok")
            + tool_turn(10, 1, "Write", {"file_path": "C:/x/foo-context.md", "content": "v1"}, result="ok")
        )
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("planner", "planner", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R6").passed)


# --------------------------------------------------------------------------
# R7 / R8 / R9 budgets
# --------------------------------------------------------------------------

def make_turns(count, start_idx=0, input_tokens=1000, cache_creation=0, cache_read=0, output_tokens=100, gap=1):
    return [turn(i * gap, start_idx + i, input_tokens=input_tokens, cache_creation=cache_creation,
                  cache_read=cache_read, output_tokens=output_tokens)
            for i in range(count)]


class R7Tests(TempDirMixin, unittest.TestCase):
    def test_fail_over_turn_budget(self):
        records = make_turns(wa.REVIEWER_MAX_TURNS + 1)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).subagent(
            "docs-sync-reviewer", "docs-sync-reviewer:r0", records)
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R7").passed)

    def test_pass_under_budget(self):
        records = make_turns(wa.REVIEWER_MAX_TURNS - 1)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).subagent(
            "docs-sync-reviewer", "docs-sync-reviewer:r0", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R7").passed)


class R8Tests(TempDirMixin, unittest.TestCase):
    def test_fail_over_turns(self):
        records = make_turns(wa.IMPLEMENTER_MAX_TURNS + 1)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).subagent(
            "implementer", "implementer:r0", records)
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R8").passed)

    def test_fail_over_context_per_turn(self):
        records = make_turns(5, cache_read=wa.IMPLEMENTER_MAX_CONTEXT_PER_TURN + 1000)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).subagent(
            "implementer", "implementer:r0", records)
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R8").passed)

    def test_pass_under_budget(self):
        records = make_turns(5, cache_read=1000)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).subagent(
            "implementer", "implementer:r0", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R8").passed)


class R9Tests(TempDirMixin, unittest.TestCase):
    def test_fail_over_tokens(self):
        records = make_turns(5, cache_read=wa.VERIFIER_MAX_TOKENS)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).subagent(
            "verifier", "verifier:r0", records)
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R9").passed)

    def test_pass_under_budget(self):
        records = make_turns(5, cache_read=1000)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).subagent(
            "verifier", "verifier:r0", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R9").passed)


# --------------------------------------------------------------------------
# R10 driver-discipline
# --------------------------------------------------------------------------

class R10Tests(TempDirMixin, unittest.TestCase):
    def test_fail_driver_runs_tests(self):
        records = tool_turn(0, 0, "Bash", {"command": "py -3 -m unittest discover -s tests"}, result="OK")
        b = SessionBuilder(self.tmp_path).driver(records)
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R10").passed)

    def test_fail_driver_edits_outside_workorders(self):
        records = tool_turn(0, 0, "Edit", {"file_path": "C:/repo/ForgePact/plugin/ModuleMain.cpp"}, result="ok")
        b = SessionBuilder(self.tmp_path).driver(records)
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R10").passed)

    def test_pass_driver_edits_workorder_file(self):
        records = tool_turn(0, 0, "Edit", {"file_path": "C:/repo/.claude/workorders/foo-plan.md"}, result="ok")
        b = SessionBuilder(self.tmp_path).driver(records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R10").passed)

    def test_pass_driver_dispatches_only(self):
        records = tool_turn(0, 0, "Agent", {"subagent_type": "implementer"}, result="IMPL-DONE")
        b = SessionBuilder(self.tmp_path).driver(records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R10").passed)

    def _round_window_turns(self, start_idx, lo_offset, hi_offset):
        """Two turns bracketing [lo_offset, hi_offset] so `_round_windows`
        sees that whole span for the round."""
        return [turn(lo_offset, start_idx), turn(hi_offset, start_idx + 1)]

    def test_fail_more_than_budget_driver_turns_in_one_round(self):
        n = wa.DRIVER_MAX_TURNS_PER_ROUND + 1
        driver_records = make_turns(n, start_idx=0, gap=1)
        b = SessionBuilder(self.tmp_path).driver(driver_records).workflow_agent(
            "wf_a", "implementer", "implementer:r0", self._round_window_turns(9000, -1, n))
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R10").passed)

    def test_pass_few_driver_turns_per_round(self):
        driver_records = make_turns(3, start_idx=0, gap=1)
        b = SessionBuilder(self.tmp_path).driver(driver_records).workflow_agent(
            "wf_a", "implementer", "implementer:r0", self._round_window_turns(9000, -1, 3))
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R10").passed)


# --------------------------------------------------------------------------
# R11 replans
# --------------------------------------------------------------------------

class R11Tests(TempDirMixin, unittest.TestCase):
    def test_fail_two_replans(self):
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)])
        b.subagent("planner", "Plan the thing", make_turns(3, start_idx=100))
        b.subagent("planner", "Replan after round 0 PLAN-DEFECT", make_turns(3, start_idx=200))
        b.subagent("planner", "Replan after round 1 PLAN-DEFECT", make_turns(3, start_idx=300))
        _, results = b.evaluate()
        r = get_rule(results, "R11")
        self.assertFalse(r.passed)
        self.assertEqual(len(r.evidence), 2)

    def test_pass_one_replan(self):
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)])
        b.subagent("planner", "Plan the thing", make_turns(3, start_idx=100))
        b.subagent("planner", "Replan after round 0 PLAN-DEFECT", make_turns(3, start_idx=200))
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R11").passed)

    def test_pass_no_replan(self):
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)])
        b.subagent("planner", "Plan the thing", make_turns(3, start_idx=100))
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R11").passed)


# --------------------------------------------------------------------------
# R12 plan-size
# --------------------------------------------------------------------------

class R12Tests(TempDirMixin, unittest.TestCase):
    def test_fail_plan_file_over_30kb(self):
        real_plan = self.tmp_path / "foo-plan.md"
        real_plan.write_text("x" * (31 * 1024), encoding="utf-8")
        records = tool_turn(0, 0, "Read", {"file_path": str(real_plan)}, result="whatever was read")
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("verifier", "verifier:r0", records)
        _, results = b.evaluate()
        r = get_rule(results, "R12")
        self.assertFalse(r.passed)
        self.assertTrue(any("foo-plan.md" in e for e in r.evidence))

    def test_fail_context_file_over_20kb(self):
        real_ctx = self.tmp_path / "foo-context.md"
        real_ctx.write_text("x" * (21 * 1024), encoding="utf-8")
        records = tool_turn(0, 0, "Read", {"file_path": str(real_ctx)}, result="whatever")
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("implementer", "impl", records)
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R12").passed)

    def test_pass_small_plan_file(self):
        real_plan = self.tmp_path / "small-plan.md"
        real_plan.write_text("x" * 1024, encoding="utf-8")
        records = tool_turn(0, 0, "Read", {"file_path": str(real_plan)}, result="whatever")
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("verifier", "verifier:r0", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R12").passed)

    def test_pass_missing_file_is_silently_skipped(self):
        # The referenced worktree no longer exists -- must not crash or fail.
        records = tool_turn(0, 0, "Read", {"file_path": "C:/gone/nowhere-plan.md"}, result="whatever")
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("verifier", "verifier:r0", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R12").passed)


# --------------------------------------------------------------------------
# R13 round-budget
# --------------------------------------------------------------------------

class R13Tests(TempDirMixin, unittest.TestCase):
    def test_fail_round_over_budget(self):
        # Two subagents in round 0 together exceed ROUND_MAX_TOKENS.
        half = wa.ROUND_MAX_TOKENS // 2 + 1000
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)])
        b.workflow_agent("wf_a", "implementer", "implementer:r0", make_turns(3, start_idx=100, cache_read=half))
        b.workflow_agent("wf_a", "verifier", "verifier:r0", make_turns(3, start_idx=200, cache_read=half))
        _, results = b.evaluate()
        r = get_rule(results, "R13")
        self.assertFalse(r.passed)
        self.assertTrue(any("round 0" in e for e in r.evidence))

    def test_pass_round_under_budget(self):
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)])
        b.workflow_agent("wf_a", "implementer", "implementer:r0", make_turns(3, start_idx=100, cache_read=1000))
        b.workflow_agent("wf_a", "verifier", "verifier:r0", make_turns(3, start_idx=200, cache_read=1000))
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R13").passed)


# --------------------------------------------------------------------------
# CLI / exit codes
# --------------------------------------------------------------------------

class R14Tests(TempDirMixin, unittest.TestCase):
    def _reviewer(self, agent_type, runs):
        records = []
        for i in range(runs):
            records += tool_turn(i * 30, i, "Bash", {"command": "py -3 -m unittest tests.test_x"}, result="OK")
        return SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).subagent(
            agent_type, f"{agent_type}:r1", records)

    def test_fail_reviewer_reruns_the_suite(self):
        _, results = self._reviewer("docs-sync-reviewer", wa.REVIEWER_MAX_TEST_RUNS + 1).evaluate()
        r = get_rule(results, "R14")
        self.assertFalse(r.passed)
        self.assertIn("docs-sync-reviewer", r.evidence[0])

    def test_pass_a_targeted_test_or_two(self):
        _, results = self._reviewer("docs-sync-reviewer", wa.REVIEWER_MAX_TEST_RUNS).evaluate()
        self.assertTrue(get_rule(results, "R14").passed)

    def test_pass_reviewers_told_to_build_and_test_are_exempt(self):
        _, results = self._reviewer("tauri-command-reviewer", wa.REVIEWER_MAX_TEST_RUNS + 4).evaluate()
        self.assertTrue(get_rule(results, "R14").passed)

    def test_pass_a_non_reviewer_running_tests_is_not_this_rule(self):
        _, results = self._reviewer("implementer", wa.REVIEWER_MAX_TEST_RUNS + 4).evaluate()
        self.assertTrue(get_rule(results, "R14").passed)


class CliTests(TempDirMixin, unittest.TestCase):
    def test_exit_0_when_all_pass(self):
        records = tool_turn(0, 0, "Bash", {"command": "echo hi"}, result="hi")
        b = SessionBuilder(self.tmp_path).driver(records).subagent("implementer", "impl", make_turns(3, start_idx=100))
        code = b.run_main()
        self.assertEqual(code, 0)

    def test_exit_1_when_a_rule_fails(self):
        records = tool_turn(0, 0, "Bash", {"command": "py -3 -m unittest discover"}, result="ok")
        b = SessionBuilder(self.tmp_path).driver(records)
        code = b.run_main()
        self.assertEqual(code, 1)

    def test_exit_2_missing_selector(self):
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)])
        b.build()
        with self.assertRaises(SystemExit) as cm:
            wa.main(["--projects-dir", str(b.projects_dir), "--project", b.project])
        self.assertEqual(cm.exception.code, 2)

    def test_exit_2_unknown_session(self):
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)])
        b.build()
        code = wa.main([
            "--session", "doesnotexist",
            "--projects-dir", str(b.projects_dir),
            "--project", b.project,
        ])
        self.assertEqual(code, 2)

    def test_exit_2_unknown_project(self):
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)])
        b.build()
        code = wa.main([
            "--latest",
            "--projects-dir", str(b.projects_dir),
            "--project", "no-such-project",
        ])
        self.assertEqual(code, 2)

    def test_json_output_matches_exit_code(self):
        records = tool_turn(0, 0, "Bash", {"command": "py -3 -m unittest discover"}, result="ok")
        b = SessionBuilder(self.tmp_path).driver(records)
        b.build()
        session_path = b.projects_dir / b.project / f"{b.session_id}.jsonl"
        session = wa.discover_session(b.projects_dir, b.project, b.session_id, session_path)
        results = wa.evaluate(session)
        payload = wa.to_json(session, results, wa.build_comparison(session))
        self.assertEqual(payload["exit_code"], 1)
        self.assertFalse(all(r["passed"] for r in payload["rules"]))


if __name__ == "__main__":
    unittest.main()
