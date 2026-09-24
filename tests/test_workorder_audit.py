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


def user_text(offset, text, origin_kind="human", is_meta=False, as_blocks=False):
    """A `user` record that is not a tool result: a typed message
    (`origin.kind == "human"`), a task notification, or -- with
    `origin_kind=None` -- an older transcript that carries no `origin`."""
    rec = {
        "type": "user",
        "timestamp": ts(offset),
        "message": {"content": [{"type": "text", "text": text}] if as_blocks else text},
    }
    if origin_kind:
        rec["origin"] = {"kind": origin_kind}
    if is_meta:
        rec["isMeta"] = True
    return rec


WORKORDER_CMD = "<command-message>workorder</command-message>\n<command-name>/workorder</command-name>\n<command-args>resume zz</command-args>"


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

    def _verifier_shell(self, command):
        records = tool_turn(0, 0, "Bash", {"command": command}, result="x")
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("verifier", "verifier:r0", records)
        _, results = b.evaluate()
        return get_rule(results, "R2")

    def test_fail_context_file_opened_through_the_shell(self):
        # `Read` is not the only way in; the Log leaks just as well through cat.
        for command in ('cat "C:/x/foo-context.md"', "cd C:/x && sed -n '1,400p' foo-context.md",
                        "Get-Content C:\\x\\foo-context.md | Select-Object -First 300",
                        "git status && head -50 a/foo-context.md",
                        # The sanctioned tool with the one flag verifier.md forbids.
                        "py -3 .claude/skills/workorder/section.py C:/x/foo-context.md --log '## Log'"):
            with self.subTest(command=command):
                self.assertFalse(self._verifier_shell(command).passed)

    def test_pass_the_sanctioned_routes_into_a_context_file(self):
        for command in ('py -3 .claude/skills/workorder/section.py "C:/x/foo-context.md" "Syntax check"',
                        "grep -n '^## \\|^### ' C:/x/foo-context.md",
                        "cat C:/x/notes.md; py -3 .claude/skills/workorder/section.py C:/x/foo-context.md 'A'",
                        # A reader's name inside the slug or the worktree's name is a path, not a command.
                        "py -3 .claude/skills/workorder/section.py \".claude/workorders/forgepact-head-label-hook-context.md\" 'A'",
                        "py -3 .claude/skills/workorder/section.py \"C:/r/.claude/worktrees/no-more-leaks-1a2b/.claude/workorders/relic-type-check-context.md\" 'A'"):
            with self.subTest(command=command):
                self.assertTrue(self._verifier_shell(command).passed)


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

    def _mixed(self, runs, run_len, spaced):
        """`runs` qualifying runs of `run_len` small shell calls, then `spaced`
        far-apart Read turns; returns (records, total_turns, batchable)."""
        records, off, idx = [], 0, 0
        for _ in range(runs):
            r, off = self._small_shell_run(off, run_len, gap=5, start_idx=idx)
            records += r
            idx += run_len
            off += 60
        for _ in range(spaced):
            records += tool_turn(off, idx, "Read", {"file_path": "some/file.py"}, result="x" * 4000)
            off += 60
            idx += 1
        return records, runs * run_len + spaced, runs * (run_len - 1)

    def test_fail_over_the_share_cap(self):
        # 3 runs of 5 (12 batchable) + 18 spaced reads = 30 turns, 40% > 30%.
        records, total, batchable = self._mixed(3, 5, 18)
        self.assertGreaterEqual(total, wa.BATCHABLE_MIN_TURNS)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent(
            "implementer", "implementer:r0", records)
        _, results = b.evaluate()
        r = get_rule(results, "R4")
        self.assertFalse(r.passed)
        self.assertTrue(any(f"{batchable / total:.0%}" in e for e in r.evidence))

    def test_pass_under_the_share_cap(self):
        # 2 runs of 4 (6 batchable) + 24 spaced reads = 32 turns, 19% < 30%.
        records, total, _ = self._mixed(2, 4, 24)
        self.assertGreaterEqual(total, wa.BATCHABLE_MIN_TURNS)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent(
            "implementer", "implementer:r0", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R4").passed)

    def test_pass_no_run_forms_when_calls_are_spaced(self):
        records, off = [], 0
        for i in range(wa.BATCHABLE_MIN_TURNS):
            records += tool_turn(off, i, "Bash", {"command": f"echo {i}"}, result="ok")
            off += 30
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent(
            "implementer", "implementer:r0", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R4").passed)

    def test_short_run_is_not_judged(self):
        # 100% batchable, but under BATCHABLE_MIN_TURNS: the share is noise.
        records, _ = self._small_shell_run(0, wa.BATCHABLE_MIN_TURNS - 1, gap=5)
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

    def test_a_question_the_user_takes_time_to_answer_is_not_a_hung_call(self):
        # 2026-09-22 calibration: 7 of R5's 8 failing sessions cited a
        # driver's AskUserQuestion open for 260-26,642s.
        records = tool_turn(0, 0, "AskUserQuestion", {"questions": []}, result="answered",
                             result_offset=3600)
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
    def _review(self, agent_type, turns, sub="a"):
        b = SessionBuilder(self.tmp_path / sub).driver([turn(0, 9000)]).subagent(
            agent_type, f"{agent_type}:r0", make_turns(turns))
        _, results = b.evaluate()
        return get_rule(results, "R7")

    def test_fail_over_turn_budget(self):
        max_turns, _ = wa.reviewer_budget("docs-sync-reviewer")
        self.assertFalse(self._review("docs-sync-reviewer", max_turns + 1).passed)

    def test_pass_under_budget(self):
        max_turns, _ = wa.reviewer_budget("docs-sync-reviewer")
        self.assertTrue(self._review("docs-sync-reviewer", max_turns - 1).passed)

    def test_each_reviewer_type_is_held_to_its_own_budget(self):
        # One shared budget failed 17 of 22 sessions, mostly on docs-sync,
        # while never coming near decompile-output-guard's real range.
        self.assertTrue(self._review("docs-sync-reviewer", 28, "a").passed)
        self.assertFalse(self._review("decompile-output-guard", 28, "b").passed)

    def test_a_type_without_its_own_budget_gets_the_default(self):
        self.assertEqual(wa.reviewer_budget("tauri-command-reviewer"),
                         (wa.REVIEWER_MAX_TURNS, wa.REVIEWER_MAX_TOKENS))
        self.assertEqual(set(wa.REVIEWER_BUDGETS) - wa.REVIEWER_TYPES, set(), "a budget for no reviewer")


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

    def test_driver_turns_between_two_launches_count_against_neither(self):
        # Two launches' round 0s, far apart; the driver's turns sit between
        # them. One window per round *number* spanned both and counted them.
        n = wa.DRIVER_MAX_TURNS_PER_ROUND + 5
        driver_records = make_turns(n, start_idx=0, gap=1)  # t = 0..n-1
        b = SessionBuilder(self.tmp_path).driver(driver_records)
        b.workflow_agent("wf_a", "implementer", "implementer:r0", self._round_window_turns(9000, -10, -5))
        b.workflow_agent("wf_b", "implementer", "implementer:r0", self._round_window_turns(9100, n + 5, n + 10))
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R10").passed)

    def test_pass_few_driver_turns_per_round(self):
        driver_records = make_turns(3, start_idx=0, gap=1)
        b = SessionBuilder(self.tmp_path).driver(driver_records).workflow_agent(
            "wf_a", "implementer", "implementer:r0", self._round_window_turns(9000, -1, 3))
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R10").passed)

    # --- the driver is judged only while it is driving ----------------------
    #
    # Shape of the real session that prompted this (2026-09-18): chat, then
    # `/workorder`, rounds at 100-200s, the workflow's task notification, the
    # driver's report, and only then the user's "build the release plugin".

    BUILD = {"command": "cmd /c build.bat release"}

    def _windowed(self, driver_records):
        return SessionBuilder(self.tmp_path).driver(driver_records).workflow_agent(
            "wf_a", "implementer", "implementer:r0", self._round_window_turns(9000, 100, 200))

    def test_fail_build_while_the_workorder_is_running(self):
        records = [user_text(50, WORKORDER_CMD)] + tool_turn(150, 0, "PowerShell", self.BUILD)
        _, results = self._windowed(records).evaluate()
        self.assertFalse(get_rule(results, "R10").passed)

    def test_fail_build_in_the_report_step_before_the_user_speaks_again(self):
        # A task notification is a `user` record too; it must not close the
        # window, or the driver's own post-round checking would go unjudged.
        records = ([user_text(50, WORKORDER_CMD),
                    user_text(210, "<task-notification>done</task-notification>", origin_kind="task-notification")]
                   + tool_turn(220, 0, "PowerShell", self.BUILD))
        _, results = self._windowed(records).evaluate()
        self.assertFalse(get_rule(results, "R10").passed)

    def test_pass_build_the_user_asked_for_after_the_workorder_ended(self):
        records = ([user_text(50, WORKORDER_CMD),
                    user_text(210, "<task-notification>done</task-notification>", origin_kind="task-notification"),
                    user_text(300, "build the release plugin for the in-game check")]
                   + tool_turn(310, 0, "PowerShell", self.BUILD))
        _, results = self._windowed(records).evaluate()
        self.assertTrue(get_rule(results, "R10").passed)

    def test_pass_shell_work_before_the_workorder_was_invoked(self):
        records = (tool_turn(10, 0, "Bash", {"command": "npm test"})
                   + [user_text(50, WORKORDER_CMD, as_blocks=True)])
        _, results = self._windowed(records).evaluate()
        self.assertTrue(get_rule(results, "R10").passed)

    def test_fail_a_message_typed_mid_round_does_not_close_the_window(self):
        records = ([user_text(50, WORKORDER_CMD), user_text(150, "we will do the in-game check first")]
                   + tool_turn(160, 0, "PowerShell", self.BUILD))
        _, results = self._windowed(records).evaluate()
        self.assertFalse(get_rule(results, "R10").passed)

    def test_fail_a_second_workorder_invocation_keeps_the_window_open(self):
        records = ([user_text(50, WORKORDER_CMD), user_text(300, WORKORDER_CMD)]
                   + tool_turn(310, 0, "PowerShell", self.BUILD))
        _, results = self._windowed(records).evaluate()
        self.assertFalse(get_rule(results, "R10").passed)

    def test_pass_what_the_user_asked_for_between_two_workorders(self):
        # One window per invocation. With a single session-wide window the
        # second workorder's subagents kept the first one's window open, and
        # everything asked for in between still counted.
        records = ([user_text(50, WORKORDER_CMD), user_text(300, "build the release plugin")]
                   + tool_turn(310, 0, "PowerShell", self.BUILD)
                   + [user_text(400, WORKORDER_CMD)])
        b = self._windowed(records).workflow_agent(
            "wf_b", "implementer", "implementer:r0", self._round_window_turns(9100, 500, 600))
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R10").passed)

    def test_fail_build_during_the_second_of_two_workorders(self):
        records = ([user_text(50, WORKORDER_CMD), user_text(300, "thanks"), user_text(400, WORKORDER_CMD)]
                   + tool_turn(550, 0, "PowerShell", self.BUILD))
        b = self._windowed(records).workflow_agent(
            "wf_b", "implementer", "implementer:r0", self._round_window_turns(9100, 500, 600))
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R10").passed)

    def test_fail_harness_records_without_origin_do_not_close_the_window(self):
        # Real transcripts that carry `origin` also hold origin-less `user`
        # records the harness wrote. None is the user speaking, so the
        # driver's own build after them is still the driver's.
        for text in ("<ci-monitor-event>checks passed</ci-monitor-event>", "[Request interrupted by user]",
                     "<local-command-stdout>ok</local-command-stdout>", "/model"):
            with self.subTest(text=text):
                records = ([user_text(50, WORKORDER_CMD), user_text(210, text, origin_kind=None)]
                           + tool_turn(220, 0, "PowerShell", self.BUILD))
                _, results = self._windowed(records).evaluate()
                self.assertFalse(get_rule(results, "R10").passed)

    def test_pass_an_adhoc_agent_the_user_asks_for_later_does_not_reopen_the_window(self):
        records = ([user_text(50, WORKORDER_CMD), user_text(300, "have an agent look at the launcher, then build")]
                   + tool_turn(500, 0, "PowerShell", self.BUILD))
        b = self._windowed(records).subagent("Explore", "Look at the launcher", self._round_window_turns(9200, 310, 400))
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R10").passed)

    def test_fail_a_pipeline_agent_outside_a_workflow_still_holds_the_window(self):
        # Driver mode: phases are plain Agent calls, not workflow agents.
        records = ([user_text(50, WORKORDER_CMD)] + tool_turn(450, 0, "PowerShell", self.BUILD))
        b = self._windowed(records).subagent("verifier", "Verify round 0", self._round_window_turns(9200, 310, 400))
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R10").passed)

    def test_a_call_with_no_timestamp_is_judged_not_a_crash(self):
        use, res = tool_turn(0, 0, "PowerShell", self.BUILD)
        del use["timestamp"]
        del res["timestamp"]
        _, results = self._windowed([use, res, user_text(50, WORKORDER_CMD)]).evaluate()
        self.assertFalse(get_rule(results, "R10").passed)

    def test_transcripts_without_origin_fall_back_to_the_record_shape(self):
        records = ([user_text(50, WORKORDER_CMD, origin_kind=None),
                    user_text(210, "<task-notification>done</task-notification>", origin_kind=None),
                    user_text(215, "Base directory for this skill: x", origin_kind=None, is_meta=True)]
                   + tool_turn(220, 0, "PowerShell", self.BUILD))
        _, results = self._windowed(records).evaluate()
        self.assertFalse(get_rule(results, "R10").passed, "neither a notification nor a skill expansion is the user speaking")
        records = records[:3] + [user_text(216, "now build it", origin_kind=None)] + records[3:]
        _, results = self._windowed(records).evaluate()
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

    # --- only what the planner authored counts -------------------------------

    def _context_result(self, body: bytes):
        real_ctx = self.tmp_path / "foo-context.md"
        real_ctx.write_bytes(body)
        records = tool_turn(0, 0, "Read", {"file_path": str(real_ctx), "offset": 1, "limit": 5}, result="x")
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)]).subagent("implementer", "impl", records)
        _, results = b.evaluate()
        return get_rule(results, "R12")

    def test_pass_context_file_whose_bulk_is_the_pipelines_own_log(self):
        # 12KB authored + 18KB of round Log, CRLF as this worktree writes it.
        body = (b"## Context the implementer needs\r\n" + b"c" * (12 * 1024)
                + b"\r\n## Log\r\n\r\n### Round 0\r\n" + b"l" * (18 * 1024))
        self.assertTrue(self._context_result(body).passed)

    def test_fail_authored_part_over_budget_whatever_the_log_holds(self):
        body = (b"## Context the implementer needs\n" + b"c" * (21 * 1024)
                + b"\n## Log\n" + b"l" * 1024)
        r = self._context_result(body)
        self.assertFalse(r.passed)
        self.assertIn("authored", r.evidence[0])

    def test_fail_a_heading_that_only_starts_with_log_is_not_the_log(self):
        body = b"## Logistics\n" + b"c" * (21 * 1024)
        self.assertFalse(self._context_result(body).passed)

    def test_log_in_the_middle_of_a_legacy_plan_is_cut_out_not_everything_after_it(self):
        authored, log = wa.authored_and_log_kb(
            b"## Goal\n" + b"g" * 1024 + b"\n## Log\n" + b"l" * 2048 + b"\n## Steps\n" + b"s" * 4096)
        self.assertAlmostEqual(log, 2.0, delta=0.05)
        self.assertAlmostEqual(authored, 5.0, delta=0.05)

    def test_a_fenced_log_heading_in_the_authored_part_hides_nothing(self):
        body = (b"## Context the implementer needs\n```markdown\n## Log\n```\n" + b"c" * (21 * 1024)
                + b"\n## Needs human judgement\nx\n## Log\n### Round 0\nl\n")
        self.assertFalse(self._context_result(body).passed)

    def test_a_fenced_h2_inside_the_log_does_not_end_the_log(self):
        # Four backticks quoting three: only the matching run closes it.
        body = (b"## Context the implementer needs\nshort\n## Log\n### Round 0\n````\n```\n## Summary of test output\n```\n"
                + b"l" * (30 * 1024) + b"\n````\n")
        self.assertTrue(self._context_result(body).passed)

    def test_a_second_log_heading_continues_the_log(self):
        # Measured 2026-09-22: a driver appended a second `## Log` at the end
        # of a context file, and what followed it was audited as authored.
        authored, log = wa.authored_and_log_kb(
            b"## Context\n" + b"c" * 1024 + b"\n## Log\n" + b"l" * 1024 + b"\n## Log\n" + b"m" * 4096)
        self.assertAlmostEqual(authored, 1.0, delta=0.05)
        self.assertAlmostEqual(log, 5.0, delta=0.05)

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
        # Two subagents in round 0 together exceed round 0's budget.
        half = wa.round_budget(0) // 6 + 1000
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

    def test_round_zeros_of_different_workflow_launches_are_not_added_together(self):
        # Measured 2026-09-22: a session with seven launches audited as one
        # 127M-token "round 0". Each launch's round 0 is its own round.
        per_turn = wa.round_budget(0) * 2 // 3 // 3  # two thirds of the budget per launch, over 3 turns
        b = SessionBuilder(self.tmp_path / "split").driver([turn(0, 0)])
        b.workflow_agent("wf_a", "implementer", "implementer:r0", make_turns(3, start_idx=100, cache_read=per_turn))
        b.workflow_agent("wf_b", "implementer", "implementer:r0", make_turns(3, start_idx=200, cache_read=per_turn))
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R13").passed)
        # Control: the same tokens inside one launch are over.
        b = SessionBuilder(self.tmp_path / "control").driver([turn(0, 0)])
        b.workflow_agent("wf_a", "implementer", "implementer:r0", make_turns(3, start_idx=100, cache_read=per_turn))
        b.workflow_agent("wf_a", "verifier", "verifier:r0", make_turns(3, start_idx=200, cache_read=per_turn))
        _, results = b.evaluate()
        r = get_rule(results, "R13")
        self.assertFalse(r.passed)
        self.assertIn("[wf_a]", r.evidence[0])

    def test_later_rounds_have_their_own_smaller_budget(self):
        self.assertLess(wa.round_budget(1), wa.round_budget(0))
        per_turn = wa.round_budget(1) // 3 + 1000
        b = SessionBuilder(self.tmp_path / "r1").driver([turn(0, 0)])
        b.workflow_agent("wf_a", "implementer", "implementer:r1", make_turns(3, start_idx=100, cache_read=per_turn))
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R13").passed)
        b = SessionBuilder(self.tmp_path / "r0").driver([turn(0, 0)])
        b.workflow_agent("wf_a", "implementer", "implementer:r0", make_turns(3, start_idx=100, cache_read=per_turn))
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R13").passed, "the same spend is inside round 0's budget")


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


# --------------------------------------------------------------------------
# R15 edit-guard-workaround
# --------------------------------------------------------------------------

# The harness's own words, 2026-09-18, for an Edit into the main checkout from
# a session opened in a worktree.
GUARD_REFUSAL = (
    "This session is running in an isolated git worktree at `C:\\repo\\.claude\\worktrees\\wt`, but "
    "`C:\\repo\\ForgePact\\plugin\\ModuleMain.cpp` is in the base repo checkout. Edits there do not land on "
    "this session's branch and may corrupt the user's primary working copy. Use the worktree path instead: "
    "`C:\\repo\\.claude\\worktrees\\wt\\ForgePact\\plugin\\ModuleMain.cpp`"
)


class R15Tests(TempDirMixin, unittest.TestCase):
    MAIN = {"file_path": "C:/repo/ForgePact/plugin/ModuleMain.cpp", "old_string": "a", "new_string": "b"}

    def _implementer(self, records):
        return SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).workflow_agent(
            "wf_a", "implementer", "implementer:r0", records)

    def _shell_calls(self, count, start_idx):
        records = []
        for i in range(count):
            records += tool_turn(100 + i * 30, start_idx + i, "Bash", {"command": f"py patch_bytes.py {i}"}, result="replaced 1")
        return records

    def test_fail_refused_edit_then_the_work_carries_on_through_the_shell(self):
        records = (tool_turn(0, 0, "Edit", self.MAIN, result=GUARD_REFUSAL)
                   + self._shell_calls(wa.GUARD_REFUSAL_MAX_FOLLOWUP_CALLS + 1, 1))
        _, results = self._implementer(records).evaluate()
        r = get_rule(results, "R15")
        self.assertFalse(r.passed)
        self.assertIn("implementer:r0", r.evidence[0])
        self.assertIn("ModuleMain.cpp", r.evidence[0])

    def test_pass_refused_edit_then_plan_defect_within_the_allowance(self):
        # The whole allowance, then the return: the return is how the
        # PLAN-DEFECT travels, so it is not one of the calls being rationed.
        records = (tool_turn(0, 0, "Edit", self.MAIN, result=GUARD_REFUSAL)
                   + self._shell_calls(wa.GUARD_REFUSAL_MAX_FOLLOWUP_CALLS, 1)
                   + tool_turn(900, 50, "StructuredOutput", {"verdict": "PLAN-DEFECT"}, result="ok"))
        _, results = self._implementer(records).evaluate()
        self.assertTrue(get_rule(results, "R15").passed)

    def test_pass_a_mistyped_path_corrected_into_the_worktree(self):
        # The guard's message names the right path; an agent that takes it and
        # carries on with Edit has worked around nothing.
        here = {**self.MAIN, "file_path": "C:\\repo\\.claude\\worktrees\\wt\\ForgePact\\plugin\\ModuleMain.cpp"}
        records = (tool_turn(0, 0, "Edit", self.MAIN, result=GUARD_REFUSAL)
                   + tool_turn(10, 1, "Edit", here, result="The file has been updated.")
                   + self._shell_calls(40, 2))
        _, results = self._implementer(records).evaluate()
        self.assertTrue(get_rule(results, "R15").passed)

    def test_fail_a_scratch_copy_with_the_same_name_is_the_workaround_not_a_correction(self):
        # The real run: refused, wrote the file to its scratchpad, cp'd it over.
        scratch = {"file_path": "C:/Temp/claude/scratchpad/ModuleMain.cpp", "content": "x"}
        records = (tool_turn(0, 0, "Edit", self.MAIN, result=GUARD_REFUSAL)
                   + tool_turn(10, 1, "Write", scratch, result="File created successfully")
                   + self._shell_calls(40, 2))
        _, results = self._implementer(records).evaluate()
        self.assertFalse(get_rule(results, "R15").passed)

    def test_fail_a_same_named_file_elsewhere_in_the_worktree_is_not_a_correction(self):
        refused = {**self.MAIN, "file_path": "C:/repo/ForgePact/README.md"}
        other = {**self.MAIN, "file_path": "C:/repo/.claude/worktrees/wt/hub/README.md"}
        records = (tool_turn(0, 0, "Edit", refused, result=GUARD_REFUSAL)
                   + tool_turn(10, 1, "Edit", other, result="The file has been updated.")
                   + self._shell_calls(40, 2))
        _, results = self._implementer(records).evaluate()
        self.assertFalse(get_rule(results, "R15").passed)

    def test_fail_the_retry_in_the_worktree_did_not_land_either(self):
        # What the real run did: the worktree had no such file, the retry
        # errored, and the patch scripts followed.
        here = {**self.MAIN, "file_path": "C:/repo/.claude/worktrees/wt/ForgePact/plugin/ModuleMain.cpp"}
        use, res = tool_turn(10, 1, "Edit", here, result="<tool_use_error>File does not exist.</tool_use_error>")
        res["message"]["content"][0]["is_error"] = True
        records = tool_turn(0, 0, "Edit", self.MAIN, result=GUARD_REFUSAL) + [use, res] + self._shell_calls(40, 2)
        _, results = self._implementer(records).evaluate()
        self.assertFalse(get_rule(results, "R15").passed)

    def test_pass_many_calls_and_no_refusal(self):
        records = tool_turn(0, 0, "Edit", self.MAIN, result="The file has been updated.") + self._shell_calls(40, 1)
        _, results = self._implementer(records).evaluate()
        self.assertTrue(get_rule(results, "R15").passed)

    def test_pass_the_guard_text_in_a_shell_result_is_not_a_refusal(self):
        # e.g. an agent grepping a transcript, or this test file, for the text.
        records = tool_turn(0, 0, "Bash", {"command": "grep -rn 'base repo checkout' ."}, result=GUARD_REFUSAL) + self._shell_calls(40, 1)
        _, results = self._implementer(records).evaluate()
        self.assertTrue(get_rule(results, "R15").passed)

    def test_the_followup_count_starts_at_the_first_refusal(self):
        records = (self._shell_calls(40, 100)
                   + tool_turn(2000, 0, "Write", {"file_path": "C:/repo/ForgePact/x.md", "content": "x"}, result=GUARD_REFUSAL)
                   + tool_turn(2030, 1, "StructuredOutput", {"verdict": "PLAN-DEFECT"}, result="ok"))
        _, results = self._implementer(records).evaluate()
        self.assertTrue(get_rule(results, "R15").passed, "calls made before the refusal are not a workaround")


# --------------------------------------------------------------------------
# R16 scribe-scope
# --------------------------------------------------------------------------

def with_cwd(records, cwd="C:\\repo"):
    """Sets the top-level `cwd` real transcripts carry (COST-GATE-SPEC.md /
    the R16 plan's "How R16 decides" section) on every record a helper
    returned, so `parse_transcript` can capture it."""
    for rec in records:
        rec["cwd"] = cwd
    return records


class R16Tests(TempDirMixin, unittest.TestCase):
    SOURCE_EDIT = {"file_path": "C:/repo/ForgePact/plugin/ModuleMain.cpp", "old_string": "a", "new_string": "b"}
    HOME_WRITE = {"file_path": "C:\\Users\\Administrator\\.claude\\workorders\\zz-context.md", "content": "x"}
    OK_CONTEXT_EDIT = {"file_path": "C:\\repo\\.claude\\workorders\\zz-context.md", "old_string": "a", "new_string": "b"}
    OK_PLAN_EDIT = {"file_path": "C:\\repo\\.claude\\workorders\\zz-plan.md", "old_string": "a", "new_string": "b"}
    OK_CONTEXT_EDIT_REL = {"file_path": ".claude/workorders/zz-context.md", "old_string": "a", "new_string": "b"}
    OK_PLAN_EDIT_REL = {"file_path": ".claude/workorders/zz-plan.md", "old_string": "a", "new_string": "b"}

    def _scribe(self, records, label="scribe:r1", agent_type="workflow-subagent", wf_id="wf_95c37e59-d40"):
        return SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).workflow_agent(
            wf_id, agent_type, label, with_cwd(records))

    def test_fail_the_real_evidence_sequence(self):
        # Modeled on the 2026-09-19 run: failed Reads of a home-directory
        # workorder path, a Write that creates one there, three Edits of
        # ForgePact source and docs, then git add + git commit.
        records = (
            tool_turn(0, 0, "Read", {"file_path": "C:\\Users\\Administrator\\.claude\\workorders\\zz-context.md"},
                      result="<tool_use_error>File does not exist.</tool_use_error>")
            + tool_turn(10, 1, "Write", self.HOME_WRITE, result="File created successfully")
            + tool_turn(20, 2, "Edit", self.SOURCE_EDIT, result="The file has been updated.")
            + tool_turn(30, 3, "Edit", {"file_path": "C:/repo/ForgePact/docs/prospect-window-research.md",
                                         "old_string": "a", "new_string": "b"}, result="The file has been updated.")
            + tool_turn(40, 4, "Bash", {"command": "git add ForgePact && git commit -m 'fix(ForgePact): x'"}, result="ok")
            + tool_turn(50, 5, "StructuredOutput", {"written": True, "note": ""}, result="ok")
        )
        _, results = self._scribe(records).evaluate()
        r = get_rule(results, "R16")
        self.assertFalse(r.passed)
        joined = " ".join(r.evidence)
        self.assertIn("scribe:r1", joined)
        self.assertIn("wf_95c37e59-d40", joined)
        self.assertIn("ModuleMain.cpp", joined)
        self.assertIn("git commit", joined)
        for line in r.evidence:
            self.assertIn("wf_95c37e59-d40", line)

    def test_fail_home_directory_write_alone(self):
        records = tool_turn(0, 0, "Write", self.HOME_WRITE, result="File created successfully")
        _, results = self._scribe(records).evaluate()
        self.assertFalse(get_rule(results, "R16").passed)

    def test_fail_source_edit_alone(self):
        records = tool_turn(0, 0, "Edit", self.SOURCE_EDIT, result="The file has been updated.")
        _, results = self._scribe(records).evaluate()
        self.assertFalse(get_rule(results, "R16").passed)

    def test_fail_git_add_and_commit_chained_after_cd_in_bash(self):
        records = tool_turn(0, 0, "Bash", {
            "command": "cd /c/repo/ForgePact && git add docs/x.md && git commit -m x"}, result="ok")
        _, results = self._scribe(records).evaluate()
        self.assertFalse(get_rule(results, "R16").passed)

    def test_fail_git_dash_c_commit_in_powershell(self):
        records = tool_turn(0, 0, "PowerShell", {"command": 'git -C "C:\\repo\\ForgePact" commit -m x'}, result="ok")
        _, results = self._scribe(records).evaluate()
        self.assertFalse(get_rule(results, "R16").passed)

    def test_fail_scribe_identified_by_agent_type_not_just_label(self):
        records = tool_turn(0, 0, "Edit", self.SOURCE_EDIT, result="The file has been updated.")
        _, results = self._scribe(records, label="scribe:r2", agent_type="scribe").evaluate()
        self.assertFalse(get_rule(results, "R16").passed)

    def test_pass_reads_and_edits_only_its_own_workorder_files(self):
        records = (tool_turn(0, 0, "Read", {"file_path": "C:\\repo\\.claude\\workorders\\zz-context.md"}, result="...")
                   + tool_turn(10, 1, "Read", {"file_path": "C:\\repo\\.claude\\workorders\\zz-plan.md"}, result="...")
                   + tool_turn(20, 2, "Edit", self.OK_CONTEXT_EDIT, result="The file has been updated.")
                   + tool_turn(30, 3, "Edit", self.OK_PLAN_EDIT, result="The file has been updated.")
                   + tool_turn(40, 4, "StructuredOutput", {"written": True, "note": ""}, result="ok"))
        _, results = self._scribe(records).evaluate()
        self.assertTrue(get_rule(results, "R16").passed)

    def test_pass_relative_workorder_paths(self):
        records = (tool_turn(0, 0, "Edit", self.OK_CONTEXT_EDIT_REL, result="The file has been updated.")
                   + tool_turn(10, 1, "Edit", self.OK_PLAN_EDIT_REL, result="The file has been updated."))
        _, results = self._scribe(records).evaluate()
        self.assertTrue(get_rule(results, "R16").passed)

    def test_pass_read_only_git(self):
        records = (tool_turn(0, 0, "Bash", {"command": "git status"}, result="ok")
                   + tool_turn(10, 1, "Bash", {"command": "git diff HEAD"}, result="ok"))
        _, results = self._scribe(records).evaluate()
        self.assertTrue(get_rule(results, "R16").passed)

    def test_fail_any_git_write_not_just_add_and_commit(self):
        # Review of PR #111: `push` is what would have made the incident
        # unrecoverable; the rest write as surely. Each alone must fail.
        for cmd in ("git push origin HEAD", "git reset --hard HEAD~1", "git checkout -- ForgePact",
                    "git restore docs/x.md", "git stash", "git merge main", "git tag v1",
                    "git submodule update", 'git -C "C:\\repo\\ForgePact" push',
                    "git -c user.name=x --no-pager commit -m x"):
            with self.subTest(cmd=cmd):
                records = tool_turn(0, 0, "Bash", {"command": cmd}, result="ok")
                _, results = self._scribe(records).evaluate()
                r = get_rule(results, "R16")
                self.assertFalse(r.passed)
                self.assertIn("ran git", " ".join(r.evidence))

    def test_pass_other_read_only_git(self):
        records = tool_turn(0, 0, "Bash", {
            "command": "git log --oneline -3 && git show HEAD && git rev-parse HEAD && git -C ForgePact ls-files"},
            result="ok")
        _, results = self._scribe(records).evaluate()
        self.assertTrue(get_rule(results, "R16").passed)

    def test_fail_relative_workorder_path_resolved_against_a_home_cwd(self):
        # Review of PR #111: the relative spelling of the incident -- the
        # right-looking path, written from the wrong directory.
        records = with_cwd(tool_turn(0, 0, "Edit", self.OK_CONTEXT_EDIT_REL, result="The file has been updated."),
                           cwd="C:\\Users\\Administrator")
        # The session's own checkout (the driver's cwd) is C:\repo; the scribe
        # ran from the home directory, so its relative write landed there.
        b = SessionBuilder(self.tmp_path).driver(with_cwd([turn(0, 9000)])).workflow_agent(
            "wf_95c37e59-d40", "workflow-subagent", "scribe:r1", records)
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R16").passed)
        # Control: the same relative edit from the checkout itself passes.
        ok = with_cwd(tool_turn(0, 0, "Edit", self.OK_CONTEXT_EDIT_REL, result="The file has been updated."))
        b2 = SessionBuilder(self.tmp_path / "ok").driver(with_cwd([turn(0, 9000)])).workflow_agent(
            "wf_95c37e59-d40", "workflow-subagent", "scribe:r1", ok)
        _, results2 = b2.evaluate()
        self.assertTrue(get_rule(results2, "R16").passed)

    def test_fail_relative_path_escaping_with_dotdot(self):
        records = tool_turn(0, 0, "Edit", {"file_path": ".claude/workorders/../../ForgePact/x.cpp",
                                           "old_string": "a", "new_string": "b"}, result="ok")
        _, results = self._scribe(records).evaluate()
        self.assertFalse(get_rule(results, "R16").passed)

    def test_pass_implementer_editing_source_and_committing_is_not_this_rule(self):
        records = (tool_turn(0, 0, "Edit", self.SOURCE_EDIT, result="The file has been updated.")
                   + tool_turn(10, 1, "Bash", {"command": "git add ForgePact && git commit -m x"}, result="ok"))
        b = SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).workflow_agent(
            "wf_a", "implementer", "implementer:r0", with_cwd(records))
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R16").passed)

    # --- round 1: shell-side writes, the route the git-only check missed ---

    def test_fail_bash_heredoc_overwrites_scribe_md(self):
        # The measured shape: `wf_a2bac07a-62e` `scribe:r1` overwrote
        # `.claude/agents/scribe.md` with a Bash heredoc after its `Write`
        # was refused for not having read the file first.
        cmd = (
            "cat > /c/repo/.claude/agents/scribe.md << 'EOF'\n"
            "---\n"
            "name: scribe\n"
            "tools: Read, Edit\n"
            "model: haiku\n"
            "---\n"
            "EOF"
        )
        records = tool_turn(0, 0, "Bash", {"command": cmd}, result="ok")
        _, results = self._scribe(records).evaluate()
        r = get_rule(results, "R16")
        self.assertFalse(r.passed)
        joined = " ".join(r.evidence)
        self.assertIn("Bash", joined)
        self.assertIn("scribe.md", joined)
        self.assertIn("wf_95c37e59-d40", joined)

    def test_fail_powershell_set_content_write(self):
        records = tool_turn(0, 0, "PowerShell", {
            "command": "Set-Content -Path .claude/agents/scribe.md -Value 'x'"}, result="ok")
        _, results = self._scribe(records).evaluate()
        self.assertFalse(get_rule(results, "R16").passed)

    def test_fail_tee_pipe_write(self):
        records = tool_turn(0, 0, "Bash", {"command": "echo x | tee .claude/agents/scribe.md"}, result="ok")
        _, results = self._scribe(records).evaluate()
        self.assertFalse(get_rule(results, "R16").passed)

    def test_fail_python_open_write_mode(self):
        records = tool_turn(0, 0, "Bash", {
            "command": "py -3 -c \"open('.claude/agents/scribe.md', 'w').write('x')\""}, result="ok")
        _, results = self._scribe(records).evaluate()
        self.assertFalse(get_rule(results, "R16").passed)

    def test_fail_restricted_scribe_type_runs_any_shell_at_all(self):
        # tools: Read, Edit has no shell tool at all, so any shell call from
        # the restricted `scribe` agent type disproves the restriction --
        # even a read-only one that the git/write checks would let through.
        records = tool_turn(0, 0, "Bash", {"command": "git status"}, result="ok")
        _, results = self._scribe(records, label="scribe:r2", agent_type="scribe").evaluate()
        self.assertFalse(get_rule(results, "R16").passed)

    def test_pass_cd_and_tail_of_its_own_files(self):
        # The real wf_8314c0d6-acc scribe:r1 shape (session 42eeea81).
        records = tool_turn(0, 0, "Bash", {
            "command": 'cd "C:\\repo" && tail -20 ".\\.claude\\workorders\\zz-plan.md"'}, result="...")
        _, results = self._scribe(records).evaluate()
        self.assertTrue(get_rule(results, "R16").passed)

    def test_pass_fd_duplication_and_null_redirects_and_pipe_to_head(self):
        records = tool_turn(0, 0, "Bash", {
            "command": "node --test .claude/workflows/workorder-rounds.test.mjs 2>&1 2>/dev/null | head -5"},
            result="ok")
        _, results = self._scribe(records).evaluate()
        self.assertTrue(get_rule(results, "R16").passed)

    def test_pass_python_heredoc_that_only_reads_with_a_ge_comparison(self):
        cmd = (
            "python3 << 'EOF'\n"
            "n = 11\n"
            "assert n >= 11\n"
            "EOF"
        )
        records = tool_turn(0, 0, "Bash", {"command": cmd}, result="ok")
        _, results = self._scribe(records).evaluate()
        self.assertTrue(get_rule(results, "R16").passed)


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


# --------------------------------------------------------------------------
# Model, cost, session lookup and calibration
# --------------------------------------------------------------------------

def with_model(records, model):
    for rec in records:
        if rec.get("type") == "assistant":
            rec["message"]["model"] = model
    return records


class ModelAndCostTests(TempDirMixin, unittest.TestCase):
    def test_the_model_an_alias_resolved_to_is_reported_and_priced(self):
        records = with_model(make_turns(2, input_tokens=0, cache_read=1_000_000, output_tokens=0), "claude-opus-5-5")
        b = SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).subagent("implementer", "implementer:r0", records)
        session, _ = b.evaluate()
        row = [r for r in wa.build_table(session) if r["agent_type"] == "implementer"][0]
        self.assertEqual(row["model"], "opus-5-5")
        self.assertAlmostEqual(row["cost_usd"], 0.40, places=2)  # 2M cache reads at $0.20

    def test_an_unpriced_model_is_not_given_a_cost(self):
        records = with_model(make_turns(2), "claude-some-future-model")
        b = SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).subagent("implementer", "implementer:r0", records)
        session, _ = b.evaluate()
        row = [r for r in wa.build_table(session) if r["agent_type"] == "implementer"][0]
        self.assertEqual(row["cost_usd"], "-")
        self.assertEqual(wa.session_cost(session)[1], 2, "driver and implementer are both unpriced")

    def test_opus_5_5_reads_cache_at_sonnet_5_s_price(self):
        # The fact the implementer's tier move rests on.
        self.assertEqual(wa.MODEL_PRICES["claude-opus-5-5"][2], wa.MODEL_PRICES["claude-sonnet-5"][2])


class LocateSessionTests(TempDirMixin, unittest.TestCase):
    def test_a_session_in_another_worktree_of_the_same_repo_is_found(self):
        main = "C--repo"
        wt = main + "--claude-worktrees-feature-1"
        b = SessionBuilder(self.tmp_path, project=wt, session_id="abcd1234-0000")
        b.driver([turn(0, 0)]).build()
        (b.projects_dir / main).mkdir(parents=True, exist_ok=True)
        other = b.projects_dir / "C--other-repo--claude-worktrees-x"
        write_jsonl(other / "abcd9999-0000.jsonl", [turn(0, 0)])
        project, sid, _ = wa.locate_session(b.projects_dir, main + "--claude-worktrees-here", "abcd", False)
        self.assertEqual((project, sid), (wt, "abcd1234-0000"), "another repository's session is not a candidate")

    def test_an_unknown_prefix_is_still_a_usage_error(self):
        b = SessionBuilder(self.tmp_path, project="C--repo")
        b.driver([turn(0, 0)]).build()
        with self.assertRaises(SystemExit):
            wa.locate_session(b.projects_dir, "C--repo", "zzzz", False)


class CalibrationTests(TempDirMixin, unittest.TestCase):
    def test_percentile_interpolates(self):
        self.assertEqual(wa.percentile([], 0.9), 0.0)
        self.assertAlmostEqual(wa.percentile([10, 20, 30, 40, 50], 0.9), 46.0)
        self.assertEqual(wa.percentile([7], 0.5), 7)

    def test_calibration_spans_sessions_and_counts_rule_failures(self):
        a = SessionBuilder(self.tmp_path, session_id="aaaa0000-0000")
        a.driver([turn(0, 0)]).workflow_agent("wf_a", "implementer", "implementer:r0",
                                              make_turns(wa.IMPLEMENTER_MAX_TURNS + 1, start_idx=100))
        a.build()
        b = SessionBuilder(self.tmp_path, session_id="bbbb0000-0000")
        b.driver([turn(0, 0)]).workflow_agent("wf_b", "implementer", "implementer:r0",
                                              make_turns(3, start_idx=100))
        b.build()
        listing = self.tmp_path / "sessions.txt"
        listing.write_text("# calibration set\nproj aaaa\nbbbb\n", encoding="utf-8")
        sessions = [wa.discover_session(a.projects_dir, "proj", sid, a.projects_dir / "proj" / f"{sid}.jsonl")
                    for sid in ("aaaa0000-0000", "bbbb0000-0000")]
        cal = wa.calibrate(sessions)
        self.assertEqual(cal["sessions"], 2)
        self.assertEqual(cal["roles"]["implementer"]["turns"]["n"], 2)
        self.assertEqual(cal["roles"]["implementer"]["turns"]["max"], wa.IMPLEMENTER_MAX_TURNS + 1)
        self.assertEqual(cal["rule_fails"].get("R8"), 1)
        self.assertEqual(cal["round0_tokens"]["n"], 2)
        self.assertEqual(wa.read_session_list(listing), ["aaaa", "bbbb"])
        rc = wa.main(["--calibrate", str(listing), "--projects-dir", str(a.projects_dir), "--project", "proj"])
        self.assertEqual(rc, 0)


# --------------------------------------------------------------------------
# R17 live-operator-scope
# --------------------------------------------------------------------------

class R17Tests(TempDirMixin, unittest.TestCase):
    def _operator(self, *calls, sub="a"):
        records = []
        for i, (name, tool_input) in enumerate(calls):
            records += tool_turn(i * 10, i, name, tool_input, result="ok")
        b = SessionBuilder(self.tmp_path / sub).driver([turn(0, 9000)]).subagent(
            "live-operator", "live session 2", records)
        _, results = b.evaluate()
        return get_rule(results, "R17")

    CAPTURE = "C:/repo/.claude/workorders/forgepact-x-live-2.md"

    def test_pass_the_session_it_is_meant_to_run(self):
        r = self._operator(
            ("mcp__hs-drive__hs_lease_acquire", {"label": "x-live-2"}),
            ("mcp__hs-drive__hs_selfcheck", {}),
            ("Bash", {"command": "cp -r \"$LOCALAPPDATA/Hero_Siege/hs2saves\" \"$USERPROFILE/HeroSiege-manual-save-backup/x\""}),
            ("mcp__hs-drive__hs_command", {"lines": ["toggleborder stat"]}),
            ("Write", {"file_path": self.CAPTURE}),
            ("Edit", {"file_path": self.CAPTURE}),
            ("mcp__hs-drive__hs_stop_game", {}),
            ("mcp__hs-drive__hs_lease_release", {}),
            ("Bash", {"command": "git status --porcelain"}))
        self.assertTrue(r.passed, r.evidence)

    def test_fail_writing_anywhere_but_its_capture_file(self):
        for path in ("C:/repo/ForgePact/plugin/ModuleMain.cpp",
                     "C:/repo/.claude/workorders/forgepact-x-context.md"):
            with self.subTest(path=path):
                r = self._operator(("Edit", {"file_path": path}), sub=path[-12:].replace("/", "_"))
                self.assertFalse(r.passed)

    def test_fail_installing_a_build(self):
        for cmd in ('cp ForgePact/build/BloodPactPlugin_ship.dll "C:/Games/HeroSiege/mods/aurie/"',
                    'Copy-Item .\\x.dll -Destination "$game\\mods\\aurie"',
                    'curl -X POST http://127.0.0.1:8765/api/installmod'):
            with self.subTest(cmd=cmd):
                self.assertFalse(self._operator(("Bash", {"command": cmd}), sub=str(abs(hash(cmd)))).passed)

    def test_fail_git_writes_restores_and_force_stops(self):
        self.assertFalse(self._operator(("Bash", {"command": "git commit -am x"}), sub="g").passed)
        self.assertFalse(self._operator(("mcp__hs-drive__hs_saves_restore", {"backup_id": "b"}), sub="r").passed)
        self.assertFalse(self._operator(("mcp__hs-drive__hs_stop_game", {"force": True}), sub="f").passed)

    def test_fail_a_forced_lease_takeover(self):
        # A held lease is another session's live run; taking it is the
        # owner's decision, made through the driver, never the operator's.
        r = self._operator(("mcp__hs-drive__hs_lease_acquire",
                            {"label": "x-live-2", "force": True}), sub="lease")
        self.assertFalse(r.passed)
        self.assertTrue(any("forced a lease takeover" in line for line in r.evidence),
                        r.evidence)

    def test_other_agents_are_not_held_to_it(self):
        records = tool_turn(0, 0, "Edit", {"file_path": "C:/repo/ForgePact/plugin/ModuleMain.cpp"})
        b = SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).subagent("implementer", "implementer:r0", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R17").passed)


# --------------------------------------------------------------------------
# R18 scribe-state-preserved
# --------------------------------------------------------------------------

class R18Tests(TempDirMixin, unittest.TestCase):
    PLAN = "C:\\repo\\.claude\\workorders\\zz-plan.md"
    # The phase1d scribe's Edit on 2026-09-23, shortened: the whole block in,
    # the four computed lines out.
    OLD_STATE = ("## State\nround: 0        phase: plan\ngates: live1d: run; live1d: recorded\n"
                 "round base: <none yet>\nagents: planner-tier=fable\nreviewers: <none yet>\n"
                 "open defects: none\ndecisions in force: none")
    DROPPED = ("## State\nround: 1\nphase: implement\n"
               "reviewers: docs-sync-reviewer: clean\nopen defects: none")

    def _scribe(self, *edits, agent_type="scribe"):
        records = []
        for i, tool_input in enumerate(edits):
            records += tool_turn(i * 10, i, "Edit", tool_input, result="The file has been updated.")
        b = SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).workflow_agent(
            "wf_0fbe61d0-6c3", agent_type, "scribe:r0", with_cwd(records))
        _, results = b.evaluate()
        return get_rule(results, "R18")

    def test_fail_the_measured_whole_block_replacement(self):
        r = self._scribe({"file_path": self.PLAN, "old_string": self.OLD_STATE, "new_string": self.DROPPED})
        self.assertFalse(r.passed)
        joined = " ".join(r.evidence)
        for key in ("gates:", "round base:", "agents:", "decisions in force:"):
            self.assertIn(key, joined)
        self.assertNotIn("reviewers:", joined)
        self.assertIn("wf_0fbe61d0-6c3", joined)

    def test_fail_blocked_verdict_dropping_reviewers(self):
        # phase1c's implementer-verdict scribe: only round/phase were handed over.
        old = "round: 0\nphase: plan\nreviewers: <none yet>\nopen defects: none"
        r = self._scribe({"file_path": self.PLAN, "old_string": old, "new_string": "round: 0\nphase: blocked"})
        self.assertFalse(r.passed)
        self.assertIn("reviewers:, open defects:", " ".join(r.evidence))

    def test_pass_whole_block_with_every_key_kept(self):
        kept = self.OLD_STATE.replace("round: 0        phase: plan", "round: 1\nphase: implement")
        self.assertTrue(self._scribe({"file_path": self.PLAN, "old_string": self.OLD_STATE, "new_string": kept}).passed)

    def test_pass_one_line_edits(self):
        self.assertTrue(self._scribe(
            {"file_path": self.PLAN, "old_string": "round: 0", "new_string": "round: 1"},
            {"file_path": self.PLAN, "old_string": "phase: plan", "new_string": "phase: implement"}).passed)

    def test_log_edits_to_the_context_file_are_not_state(self):
        ctx = {"file_path": "C:\\repo\\.claude\\workorders\\zz-context.md",
               "old_string": "## Log\nverifier: PASS", "new_string": "## Log\n### Round 0"}
        self.assertTrue(self._scribe(ctx).passed)

    def test_other_agents_are_not_held_to_it(self):
        records = tool_turn(0, 0, "Edit", {"file_path": self.PLAN, "old_string": self.OLD_STATE, "new_string": self.DROPPED})
        b = SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).subagent("planner", "planner", records)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R18").passed)

    def test_state_keys_splits_a_two_key_line(self):
        self.assertEqual(wa.state_keys("## State\nround: 0        phase: plan\n- note\nround base: x"),
                         ["round", "phase", "round base"])


# --------------------------------------------------------------------------
# R19 gates-template
# --------------------------------------------------------------------------

class R19Tests(TempDirMixin, unittest.TestCase):
    PLAN = "C:\\repo\\.claude\\workorders\\zz-plan.md"
    # forgepact-issue-14-phase1j's planner line on 2026-09-24, shortened.
    TEMPLATE = ("## State\nround: 0        phase: plan\n"
                "gates: build: complete | live1: complete | record: complete | save-route: proven|not-observed\n"
                "open defects: none")

    def _run(self, tool, tool_input, agent_type="planner"):
        records = tool_turn(0, 0, tool, tool_input, result="ok")
        b = SessionBuilder(self.tmp_path).driver([turn(0, 9000)]).subagent(agent_type, agent_type, records)
        _, results = b.evaluate()
        return get_rule(results, "R19")

    def test_fail_the_measured_template_line(self):
        r = self._run("Write", {"file_path": self.PLAN, "content": self.TEMPLATE})
        self.assertFalse(r.passed)
        self.assertIn("live1: complete |", " ".join(r.evidence))

    def test_fail_a_placeholder_in_an_edit(self):
        r = self._run("Edit", {"file_path": self.PLAN, "old_string": "gates: none",
                               "new_string": "gates: <tokens a criterion conditions on>"}, agent_type="implementer")
        self.assertFalse(r.passed)

    def test_fail_or_between_backticked_tokens(self):
        content = "## State\ngates: `live1: complete` or `record: complete`"
        self.assertFalse(self._run("Write", {"file_path": self.PLAN, "content": content}).passed)

    def test_pass_or_inside_a_token_or_parenthetical(self):
        content = "## State\ngates: `route: error or skip` (set after run or rerun)"
        self.assertTrue(self._run("Write", {"file_path": self.PLAN, "content": content}).passed)

    def test_pass_set_gates_pending_and_route_tokens(self):
        content = ("## State\ngates: `build: complete` (set 2026-09-24 | after round 0)\n"
                   "gates pending: `live1: complete` | `record: complete`\n"
                   "route tokens: `save-route: proven` or `save-route: not-observed`")
        self.assertTrue(self._run("Write", {"file_path": self.PLAN, "content": content}).passed)
        self.assertTrue(self._run("Write", {"file_path": self.PLAN, "content": "## State\ngates: none"}).passed)

    def test_context_file_is_not_state(self):
        ctx = {"file_path": "C:\\repo\\.claude\\workorders\\zz-context.md", "content": self.TEMPLATE}
        self.assertTrue(self._run("Write", ctx).passed)


# --------------------------------------------------------------------------
# R20 live-capture-author / R21 verifier-interpreter / R22 verifier-suite-once
# --------------------------------------------------------------------------

def _one_agent_rule(tmp_path, rule_id, agent_type, *calls, label=None):
    records = []
    for i, (name, tool_input) in enumerate(calls):
        records += tool_turn(i * 10, i, name, tool_input, result="ok")
    b = SessionBuilder(tmp_path).driver([turn(0, 9000)]).subagent(agent_type, label or agent_type, records)
    _, results = b.evaluate()
    return get_rule(results, rule_id)


class R20Tests(TempDirMixin, unittest.TestCase):
    CAPTURE = r"C:\repo\.claude\workorders\forgepact-x-live-1.md"

    def test_fail_an_implementer_repairing_the_capture(self):
        # forgepact-issue-14-phase1h r2 renamed checks in the operator's capture.
        r = _one_agent_rule(self.tmp_path, "R20", "implementer",
                            ("Edit", {"file_path": self.CAPTURE, "old_string": "take-material (dropped)",
                                      "new_string": "take-material"}), label="implementer:r2")
        self.assertFalse(r.passed)
        self.assertIn("forgepact-x-live-1.md", " ".join(r.evidence))

    def test_pass_the_operator_writing_it(self):
        r = _one_agent_rule(self.tmp_path, "R20", "live-operator", ("Write", {"file_path": self.CAPTURE}))
        self.assertTrue(r.passed, r.evidence)

    def test_pass_other_workorder_files(self):
        r = _one_agent_rule(self.tmp_path, "R20", "implementer",
                            ("Edit", {"file_path": r"C:\repo\.claude\workorders\forgepact-x-context.md"}))
        self.assertTrue(r.passed, r.evidence)


class R21Tests(TempDirMixin, unittest.TestCase):
    def test_fail_python_in_command_position(self):
        for cmd in ('cd "C:/repo" && python -3 -c "print(1)"', "python3 << 'EOF'\nprint(1)\nEOF",
                    "python -m unittest tests.test_x"):
            with self.subTest(cmd=cmd):
                sub = self.tmp_path / str(abs(hash(cmd)))
                self.assertFalse(_one_agent_rule(sub, "R21", "verifier", ("Bash", {"command": cmd})).passed)

    def test_pass_py_and_mentions(self):
        for cmd in ('py -3 -c "print(1)"', "ps aux | grep -i python | head -5",
                    "py -3 -m unittest discover -s tests"):
            with self.subTest(cmd=cmd):
                sub = self.tmp_path / str(abs(hash(cmd)))
                self.assertTrue(_one_agent_rule(sub, "R21", "verifier", ("Bash", {"command": cmd})).passed)

    def test_other_agents_are_not_held_to_it(self):
        r = _one_agent_rule(self.tmp_path, "R21", "implementer", ("Bash", {"command": "python -c 1"}))
        self.assertTrue(r.passed)


class R22Tests(TempDirMixin, unittest.TestCase):
    def test_fail_the_same_suite_twice(self):
        # The 120 s default killed the hub suite and the verifier ran it again.
        r = _one_agent_rule(self.tmp_path, "R22", "verifier",
                            ("Bash", {"command": "py -3 -m unittest discover -s tests 2>&1 | tail -5"}),
                            ("Bash", {"command": "py -3 -m unittest discover -s tests 2>&1 | grep FAIL"}))
        self.assertFalse(r.passed)
        self.assertIn("2 times", " ".join(r.evidence))

    def test_pass_two_different_suites_once_each(self):
        r = _one_agent_rule(self.tmp_path, "R22", "verifier",
                            ("Bash", {"command": "py -3 -m unittest discover -s tests > s.txt 2>&1"}),
                            ("Bash", {"command": "cd ForgePact && py -m unittest discover -s tests > f.txt 2>&1"}))
        self.assertTrue(r.passed, r.evidence)

    def test_suite_key(self):
        self.assertEqual(wa.suite_key("cd ForgePact && py -m unittest discover -s tests 2>&1"), "ForgePact -s tests")
        self.assertIsNone(wa.suite_key("py -3 -m unittest tests.test_x"))


# --------------------------------------------------------------------------
# Lanes (issue #176): per-lane columns and summary, R13 scaling, R23
# --------------------------------------------------------------------------

def _span(start_s, end_s, start_idx, model=None, cache_read=0):
    """Two turns, at `start_s` and `end_s` seconds past BASE: a transcript
    whose wall time is exactly that span."""
    records = [turn(start_s, start_idx, cache_read=cache_read), turn(end_s, start_idx + 1, cache_read=cache_read)]
    return with_model(records, model) if model else records


class LaneTests(TempDirMixin, unittest.TestCase):
    def test_single_implementer_round_budget_unchanged(self):
        self.assertEqual(wa.round_budget(0), wa.ROUND0_MAX_TOKENS)
        self.assertEqual(wa.round_budget(1), wa.ROUND_MAX_TOKENS)
        # One implementer over round 0's budget still fails R13 as it did.
        per_turn = wa.ROUND0_MAX_TOKENS // 2 + 1000
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)])
        b.workflow_agent("wf_a", "implementer", "implementer:r0", _span(0, 60, 100, cache_read=per_turn))
        _, results = b.evaluate()
        r = get_rule(results, "R13")
        self.assertFalse(r.passed)
        self.assertIn(f"budget {wa.ROUND0_MAX_TOKENS:,}", r.evidence[0])

    def test_pass_the_join_and_a_laneless_implementer_committing(self):
        commit = ("Bash", {"command": 'git add -- "tools/x.py" && git commit -m "lane code"'})
        for label in ("implementer:r0", "implementer:join:r0"):
            with self.subTest(label=label):
                r = _one_agent_rule(self.tmp_path / label.replace(":", "_"), "R23", "implementer", commit, label=label)
                self.assertTrue(r.passed, r.evidence)

    def test_fail_a_lane_that_ran_a_git_write(self):
        # D2: lanes never write to git -- `.git/index.lock` is fail-fast.
        for cmd, sub in (('git add -- "tools/x.py"', "add"), ('git -C "C:/repo" stash push -m wip', "stash"),
                         ("git status --porcelain && git commit -m x", "commit")):
            with self.subTest(cmd=cmd):
                r = _one_agent_rule(self.tmp_path / sub, "R23", "implementer", ("Bash", {"command": cmd}),
                                    label="implementer:code:r0")
                self.assertFalse(r.passed)
                self.assertIn("implementer:code:r0", r.evidence[0])
                self.assertIn(f"git {sub}", r.evidence[0])
                self.assertIn(cmd[:40], r.evidence[0])
        # control: a lane's read-only git and its stop check are fine
        r = _one_agent_rule(self.tmp_path / "reads", "R23", "implementer",
                            ("Bash", {"command": "git status --porcelain -uall && git diff HEAD -- tools/x.py"}),
                            ("Bash", {"command": "py -3 .claude/skills/workorder/round_delta.py stopped zz 0"}),
                            label="implementer:code:r0")
        self.assertTrue(r.passed, r.evidence)

    def test_lane_column_from_label(self):
        self.assertEqual(wa.lane_of("implementer:code:r0"), "code")
        self.assertEqual(wa.lane_of("implementer:plan-tools:r2"), "plan-tools")
        self.assertEqual(wa.lane_of("implementer:join:r0"), "join")
        for label in ("implementer:r0", "verifier:r0", "docs-sync-reviewer:r1", "scribe:r0", "", None):
            self.assertIsNone(wa.lane_of(label), label)
        b = SessionBuilder(self.tmp_path).driver([turn(0, 0)])
        b.workflow_agent("wf_a", "implementer", "implementer:code:r0", _span(0, 60, 100))
        b.workflow_agent("wf_a", "implementer", "implementer:r1", _span(100, 160, 200))
        session, _ = b.evaluate()
        lanes = {r["label"]: r["lane"] for r in wa.build_table(session)}
        self.assertEqual(lanes["implementer:code:r0"], "code")
        self.assertEqual(lanes["implementer:r1"], "-")

    def _laned_round(self, b, wf="wf_a", round_=0, cache_read=0):
        # code runs 0-600 s, docs 60-1260 s, the join 1300-1600 s.
        b.workflow_agent(wf, "implementer", f"implementer:code:r{round_}", _span(0, 600, 100, "claude-opus-5-5", cache_read))
        b.workflow_agent(wf, "implementer", f"implementer:docs:r{round_}", _span(60, 1260, 200, "claude-opus-5-5", cache_read))
        b.workflow_agent(wf, "implementer", f"implementer:join:r{round_}", _span(1300, 1600, 300, "claude-opus-5-5", cache_read))
        return b

    def test_lane_summary_span_versus_serial(self):
        b = self._laned_round(SessionBuilder(self.tmp_path).driver([turn(0, 0)]))
        b.workflow_agent("wf_a", "verifier", "verifier:r0", _span(1700, 1800, 400))
        b.workflow_agent("wf_b", "implementer", "implementer:r0", _span(0, 60, 500))  # laneless: no summary
        session, _ = b.evaluate()
        summary = wa.lane_summary(session)
        self.assertEqual(len(summary), 1, summary)
        s = summary[0]
        self.assertEqual((s["workflow"], s["round"]), ("wf_a", 0))
        self.assertEqual([x["lane"] for x in s["lanes"]], ["code", "docs"])
        self.assertEqual([x["wall_minutes"] for x in s["lanes"]], [10.0, 20.0])
        self.assertTrue(all(isinstance(x["cost_usd"], float) for x in s["lanes"]), s)
        self.assertEqual(s["span_minutes"], 21.0)  # 0 s .. 1260 s
        self.assertEqual(s["serial_minutes"], 30.0)
        self.assertEqual(s["join_minutes"], 5.0)
        # --json carries it under `lanes`; the text report prints it after the table
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            b.run_main(["--json"])
        self.assertEqual(json.loads(buf.getvalue())["lanes"], summary)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            b.run_main()
        text = buf.getvalue()
        self.assertIn("span 21.0 min vs serial 30.0 min", text)
        self.assertLess(text.index("implementer:join:r0"), text.index("span 21.0 min"))

    def test_round0_budget_scales_with_implementers_in_the_round(self):
        self.assertEqual(wa.round_budget(0, 3), 3 * wa.ROUND0_MAX_TOKENS)
        self.assertEqual(wa.round_budget(1, 2), 2 * wa.ROUND_MAX_TOKENS)
        self.assertEqual(wa.round_budget(0, 1), wa.ROUND0_MAX_TOKENS)
        # Two lanes and a join, each at 2/3 of the one-implementer round budget:
        # 2x over the old figure, under 3x.
        per_turn = wa.ROUND0_MAX_TOKENS // 3
        b = self._laned_round(SessionBuilder(self.tmp_path / "laned").driver([turn(0, 0)]), cache_read=per_turn)
        _, results = b.evaluate()
        self.assertTrue(get_rule(results, "R13").passed, get_rule(results, "R13").evidence)
        # control: the same tokens spent by one implementer and two verifiers are over
        b = SessionBuilder(self.tmp_path / "single").driver([turn(0, 0)])
        b.workflow_agent("wf_a", "implementer", "implementer:r0", _span(0, 600, 100, cache_read=per_turn))
        b.workflow_agent("wf_a", "verifier", "verifier:r0", _span(0, 600, 200, cache_read=per_turn))
        b.workflow_agent("wf_a", "verifier", "verifier:r0", _span(0, 600, 300, cache_read=per_turn))
        _, results = b.evaluate()
        self.assertFalse(get_rule(results, "R13").passed)
