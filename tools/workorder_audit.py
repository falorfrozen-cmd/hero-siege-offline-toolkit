#!/usr/bin/env python3
"""Audit a /workorder session's transcripts against the cost/behavior rules
`AGENTS.md` states for that pipeline (batching, per-role budgets, plan/context
scope, driver discipline, round budgets, replans).

Until this tool existed, "did this run actually save time and tokens, and did
it break a rule" was answered by hand with one-off transcript scripts; see
`.claude/workorders/COST-GATE-SPEC.md` §0. This makes that judgement runnable
and repeatable.

Transcript layout (see COST-GATE-SPEC.md §2):
    ~/.claude/projects/<project>/<session>.jsonl                        driver
    ~/.claude/projects/<project>/<session>/subagents/agent-*.jsonl      ad-hoc
    .../subagents/workflows/wf_*/agent-*.jsonl                         in-round
Each subagent `agent-*.jsonl` has a sibling `agent-*.meta.json` carrying
`agentType` and a `description` (workflow labels look like `implementer:r1`).

Usage:
    py -3 tools/workorder_audit.py [--latest | --session <id-prefix>]
        [--projects-dir DIR] [--project NAME] [--json]

Exit code: 0 all rules pass, 1 a rule failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Optional

# --------------------------------------------------------------------------
# Budgets. Each constant names the section 1 measurement it is drawn from
# (see `.claude/workorders/COST-GATE-SPEC.md`, or its post-merge home).
# --------------------------------------------------------------------------

# §1 pre-update per-run averages: implementer 117 turns / 21.8M tokens / 188K
# context per turn. R8 budgets sit just above that average so a run at the
# old baseline already fails.
IMPLEMENTER_MAX_TURNS = 120
IMPLEMENTER_MAX_TOKENS = 15_000_000
IMPLEMENTER_MAX_CONTEXT_PER_TURN = 200_000

# §1: verifier 53 turns / 3.1M tokens pre-update; post-update driver-run
# sessions measured 1.5M (-52%). R9 sits between the two.
VERIFIER_MAX_TURNS = 60
VERIFIER_MAX_TOKENS = 3_500_000

# §1: reviewers 20-22 turns / 0.74-2.0M tokens pre-update; workflow-mode
# reviewers ran 23-59 turns / 1.2-4.3M only because their dispatch pointed at
# an empty diff (a bug, since fixed). R7 sits above the fixed pre-update band.
REVIEWER_MAX_TURNS = 25
REVIEWER_MAX_TOKENS = 3_000_000

# R3: no §1 number pins this one; it is a guard against reading the whole
# submodule guide instead of the section that applies.
GUIDE_MAX_KB = 60.0

# R4: §1 measured 26-39% of implementer turns are small sequential shell
# calls (result under 1.5KB, issued within 20s of the previous one, no edit
# between; longest observed run 11) that one batched call could replace.
# Calibrated on the first real run with the batching rule in place
# (2026-09-18): 24% on a 59-turn round, 38% on a 16-turn one. A quarter of an
# implementer's turns being check-then-act shell calls looks inherent; and on
# a short round a handful of calls swings the share wildly, so runs under
# BATCHABLE_MIN_TURNS are reported, not judged.
BATCHABLE_SHARE_MAX = 0.30
BATCHABLE_MIN_TURNS = 30
BATCHABLE_RESULT_MAX_BYTES = 1536
BATCHABLE_WINDOW_SECONDS = 20
BATCHABLE_MIN_RUN = 3

# R5: a tool call this long is either hung or should have been backgrounded.
# `Agent`/`Task` dispatch a subagent and wait for it by design (a
# `requestShape: "foreground"` dispatch is meant to block for minutes) and
# are not the "should have polled instead of blocking" smell this rule is
# for (see AGENTS.md "no single wait ... for more than about four minutes").
BLOCKING_CALL_MAX_SECONDS = 240
BLOCKING_EXEMPT_TOOLS = {"Agent", "Task"}

# R12: no plan/context should carry the implementation (see planner.md rule);
# these are size smells, not hard limits on what a plan may describe.
PLAN_MAX_KB = 30.0
CONTEXT_MAX_KB = 20.0

# R13: §1 first workflow-mode run measured ~21M tokens per round.
ROUND_MAX_TOKENS = 15_000_000

# R10: driver turns per round; a driver that needs more than this per round
# is doing the subagents' job instead of dispatching it.
DRIVER_MAX_TURNS_PER_ROUND = 20
DRIVER_BUILD_TEST_PATTERNS = (
    r"build\.bat", r"\bmsbuild\b", r"\bcargo\b", r"\bunittest\b",
    r"\bpytest\b", r"\bnpm\s", r"\bnode --test\b",
)
DRIVER_ALLOWED_EDIT_PREFIX = ".claude/workorders/"

# R14: the reviewer replay on 2026-09-18 (same change, fixed dispatch) showed
# docs-sync and instrument-blindness each re-running test suites 5-6 times --
# work the verifier does in parallel. Two runs covers "one targeted test, once
# more after a look"; the two reviewers whose own files tell them to build and
# test are exempt.
REVIEWER_MAX_TEST_RUNS = 2
REVIEWER_TEST_RUN_EXEMPT = {"sdk-contract-reviewer", "tauri-command-reviewer"}

REVIEWER_TYPES = {
    "docs-sync-reviewer",
    "decompile-output-guard",
    "instrument-blindness-reviewer",
    "sdk-contract-reviewer",
    "tauri-command-reviewer",
}

# §1 pre-update per-run averages, used for the role comparison section.
PRE_UPDATE_AVG = {
    "implementer": {"turns": 117, "tokens": 21_800_000, "context_per_turn": 188_000},
    "verifier": {"turns": 53, "tokens": 3_100_000, "context_per_turn": 60_000},
    "docs-sync-reviewer": {"turns": 22, "tokens": 2_000_000},
    "instrument-blindness-reviewer": {"turns": 20, "tokens": 1_640_000},
    "decompile-output-guard": {"turns": 11, "tokens": 740_000},
    "planner": {"turns": 25, "tokens": 2_500_000},
}

SHELL_TOOLS = {"Bash", "PowerShell"}
EDIT_TOOLS = {"Edit", "Write"}


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def mangle_project_dir(path: str) -> str:
    """Reproduce the `~/.claude/projects/<mangled>` directory name Claude Code
    derives from a working directory: every non-alphanumeric character
    becomes `-` (so `C:\\Users\\x` -> `C--Users-x`, `.claude` -> `-claude`)."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def default_project_dir(cwd: Optional[str] = None) -> str:
    return mangle_project_dir(cwd or os.getcwd())


def parse_ts(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _tool_result_text(content) -> str:
    """A tool_result's `content` is a plain string in the common case, but
    the Anthropic message format also allows a list of content blocks."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def iter_jsonl(path: Path) -> Iterator[dict]:
    """Stream a transcript line by line; never load the whole file as one
    string. Malformed lines are skipped rather than aborting the audit."""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


@dataclass
class ToolCall:
    tool_use_id: str
    name: str
    tool_input: dict
    ts_start: datetime
    message_id: Optional[str] = None
    ts_end: Optional[datetime] = None
    result_bytes: int = 0
    is_error: bool = False

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.ts_end is None:
            return None
        return (self.ts_end - self.ts_start).total_seconds()


@dataclass
class TurnUsage:
    message_id: str
    ts: datetime
    input_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.cache_creation_tokens + self.cache_read_tokens


def read_kind(file_path: str) -> str:
    p = file_path.replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    if name.lower().endswith("-plan.md"):
        return "plan"
    if name.lower().endswith("-context.md"):
        return "context"
    if name.lower() == "instructions.md":
        return "instructions"
    return "source"


@dataclass
class AgentTranscript:
    """One parsed `agent-*.jsonl` (or the top-level driver session)."""

    agent_type: str
    label: str
    session_id: str
    path: Path
    round: Optional[int] = None
    workflow_id: Optional[str] = None
    is_driver: bool = False

    turns: dict = field(default_factory=dict)          # message_id -> TurnUsage
    tool_calls: list = field(default_factory=list)      # ToolCall, in order
    read_kb: dict = field(default_factory=lambda: defaultdict(float))  # kind -> KB
    write_paths: list = field(default_factory=list)     # (path, ts) for Write calls
    ts_first: Optional[datetime] = None
    ts_last: Optional[datetime] = None

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def total_tokens(self) -> int:
        return sum(t.total_tokens for t in self.turns.values())

    @property
    def total_output_tokens(self) -> int:
        return sum(t.output_tokens for t in self.turns.values())

    @property
    def avg_context_per_turn(self) -> float:
        n = self.turn_count
        return (self.total_tokens / n) if n else 0.0

    @property
    def peak_context(self) -> int:
        return max((t.total_tokens for t in self.turns.values()), default=0)

    @property
    def wall_minutes(self) -> float:
        if not self.ts_first or not self.ts_last:
            return 0.0
        return (self.ts_last - self.ts_first).total_seconds() / 60.0

    @property
    def longest_tool_call_seconds(self) -> float:
        durations = [c.duration_seconds for c in self.tool_calls if c.duration_seconds is not None]
        return max(durations, default=0.0)


ROUND_RE = re.compile(r":r(\d+)$")


def parse_label(description: Optional[str]) -> tuple[str, Optional[int]]:
    """Split a workflow label like `implementer:r1` into (role, round)."""
    if not description:
        return "", None
    m = ROUND_RE.search(description)
    if not m:
        return description, None
    return description[: m.start()], int(m.group(1))


def parse_transcript(path: Path, agent_type: str, label: str, session_id: str,
                      round_: Optional[int] = None, workflow_id: Optional[str] = None,
                      is_driver: bool = False) -> AgentTranscript:
    agent = AgentTranscript(
        agent_type=agent_type, label=label, session_id=session_id, path=path,
        round=round_, workflow_id=workflow_id, is_driver=is_driver,
    )
    pending: dict = {}  # tool_use_id -> ToolCall

    for rec in iter_jsonl(path):
        rec_type = rec.get("type")
        ts_raw = rec.get("timestamp")
        ts = parse_ts(ts_raw) if ts_raw else None
        if ts is not None:
            if agent.ts_first is None or ts < agent.ts_first:
                agent.ts_first = ts
            if agent.ts_last is None or ts > agent.ts_last:
                agent.ts_last = ts

        if rec_type == "assistant":
            message = rec.get("message") or {}
            message_id = message.get("id")
            usage = message.get("usage") or {}
            content = message.get("content") or []
            if message_id and ts is not None:
                turn = agent.turns.get(message_id)
                if turn is None:
                    turn = TurnUsage(message_id=message_id, ts=ts)
                    agent.turns[message_id] = turn
                # Last-write-wins: input/cache figures repeat per block,
                # output_tokens is cumulative and only final on the last one.
                turn.input_tokens = usage.get("input_tokens", 0) or 0
                turn.cache_creation_tokens = usage.get("cache_creation_input_tokens", 0) or 0
                turn.cache_read_tokens = usage.get("cache_read_input_tokens", 0) or 0
                out = usage.get("output_tokens")
                if out is not None:
                    turn.output_tokens = out
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                tool_use_id = block.get("id")
                name = block.get("name", "")
                tool_input = block.get("input") or {}
                call = ToolCall(
                    tool_use_id=tool_use_id, name=name, tool_input=tool_input,
                    ts_start=ts or agent.ts_last, message_id=message_id,
                )
                agent.tool_calls.append(call)
                if tool_use_id:
                    pending[tool_use_id] = call
                if name == "Write":
                    fp = tool_input.get("file_path")
                    if fp:
                        agent.write_paths.append((fp, ts))

        elif rec_type == "user":
            message = rec.get("message") or {}
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                tool_use_id = block.get("tool_use_id")
                call = pending.get(tool_use_id)
                if call is None:
                    continue
                text = _tool_result_text(block.get("content"))
                call.ts_end = ts
                call.result_bytes = len(text.encode("utf-8", errors="replace"))
                call.is_error = bool(block.get("is_error"))
                if call.name == "Read":
                    fp = call.tool_input.get("file_path")
                    if fp:
                        kind = read_kind(fp)
                        agent.read_kb[kind] += call.result_bytes / 1024.0

    return agent


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

@dataclass
class Session:
    session_id: str
    project: str
    projects_dir: Path
    driver: AgentTranscript
    subagents: list  # AgentTranscript, ad-hoc (workflow_id is None)
    workflow_runs: dict  # workflow_id -> list[AgentTranscript]


def find_session_dir(projects_dir: Path, project: str, session_prefix: Optional[str],
                      latest: bool) -> tuple[str, Path]:
    project_dir = projects_dir / project
    if not project_dir.is_dir():
        raise SystemExit(f"usage error: no such project directory: {project_dir}")

    candidates = sorted(project_dir.glob("*.jsonl"))
    if session_prefix:
        matches = [p for p in candidates if p.stem.startswith(session_prefix)]
        if not matches:
            raise SystemExit(f"usage error: no session matching '{session_prefix}' under {project_dir}")
        if len(matches) > 1:
            raise SystemExit(
                f"usage error: session prefix '{session_prefix}' is ambiguous: "
                + ", ".join(m.stem for m in matches)
            )
        chosen = matches[0]
    elif latest:
        if not candidates:
            raise SystemExit(f"usage error: no sessions under {project_dir}")
        chosen = max(candidates, key=lambda p: p.stat().st_mtime)
    else:
        raise SystemExit("usage error: one of --latest or --session is required")

    return chosen.stem, chosen


def discover_session(projects_dir: Path, project: str, session_id: str,
                      session_path: Path) -> Session:
    driver = parse_transcript(session_path, agent_type="driver", label="driver",
                               session_id=session_id, is_driver=True)

    session_dir = projects_dir / project / session_id
    subagents_dir = session_dir / "subagents"

    subagents: list = []
    workflow_runs: dict = defaultdict(list)

    if subagents_dir.is_dir():
        for jsonl_path in sorted(subagents_dir.glob("agent-*.jsonl")):
            meta_path = jsonl_path.with_suffix("").with_suffix(".meta.json")
            agent_type, description = _read_meta(meta_path)
            role, round_ = parse_label(description)
            transcript = parse_transcript(
                jsonl_path, agent_type=agent_type or role or "unknown",
                label=description or jsonl_path.stem, session_id=session_id,
                round_=round_, workflow_id=None,
            )
            subagents.append(transcript)

        workflows_dir = subagents_dir / "workflows"
        if workflows_dir.is_dir():
            for wf_dir in sorted(p for p in workflows_dir.iterdir() if p.is_dir()):
                for jsonl_path in sorted(wf_dir.glob("agent-*.jsonl")):
                    meta_path = jsonl_path.with_suffix("").with_suffix(".meta.json")
                    agent_type, description = _read_meta(meta_path)
                    role, round_ = parse_label(description)
                    transcript = parse_transcript(
                        jsonl_path, agent_type=agent_type or role or "unknown",
                        label=description or jsonl_path.stem, session_id=session_id,
                        round_=round_, workflow_id=wf_dir.name,
                    )
                    workflow_runs[wf_dir.name].append(transcript)

    return Session(session_id=session_id, project=project, projects_dir=projects_dir,
                    driver=driver, subagents=subagents, workflow_runs=dict(workflow_runs))


def _read_meta(meta_path: Path) -> tuple[Optional[str], Optional[str]]:
    if not meta_path.is_file():
        return None, None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, None
    return data.get("agentType"), data.get("description")


def all_subagents(session: Session) -> list:
    out = list(session.subagents)
    for group in session.workflow_runs.values():
        out.extend(group)
    return out


def all_agents(session: Session) -> list:
    return [session.driver] + all_subagents(session)


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

@dataclass
class RuleResult:
    rule_id: str
    name: str
    passed: bool
    evidence: list = field(default_factory=list)


def _cmd_text(call: ToolCall) -> str:
    if call.name in SHELL_TOOLS:
        return str(call.tool_input.get("command", ""))
    return ""


def rule_r1_reviewer_reads_workorder(session: Session) -> RuleResult:
    evidence = []
    for agent in all_subagents(session):
        if agent.agent_type not in REVIEWER_TYPES:
            continue
        for call in agent.tool_calls:
            if call.name == "Read":
                fp = str(call.tool_input.get("file_path", ""))
                if fp.lower().endswith("-plan.md"):
                    evidence.append(f"{agent.label} Read {fp} at {call.ts_start}")
            elif call.name in SHELL_TOOLS:
                cmd = _cmd_text(call)
                if "grep" in cmd and re.search(r"-plan\.md\b", cmd):
                    evidence.append(f"{agent.label} grep of a -plan.md at {call.ts_start}: {cmd[:120]}")
    return RuleResult("R1", "reviewer-reads-workorder", passed=not evidence, evidence=evidence)


def rule_r2_verifier_scope(session: Session) -> RuleResult:
    evidence = []
    for agent in all_subagents(session):
        if agent.agent_type != "verifier":
            continue
        for call in agent.tool_calls:
            if call.name != "Read":
                continue
            fp = str(call.tool_input.get("file_path", ""))
            whole_file = "offset" not in call.tool_input and "limit" not in call.tool_input
            if not whole_file:
                continue
            kind = read_kind(fp)
            if kind == "context":
                evidence.append(f"{agent.label} whole-file Read of context {fp} at {call.ts_start}")
            elif kind == "plan" and (call.result_bytes / 1024.0) > PLAN_MAX_KB:
                evidence.append(
                    f"{agent.label} whole-file Read of {fp} "
                    f"({call.result_bytes / 1024.0:.1f}KB > {PLAN_MAX_KB}KB) at {call.ts_start}"
                )
    return RuleResult("R2", "verifier-scope", passed=not evidence, evidence=evidence)


def rule_r3_guide_whole(session: Session) -> RuleResult:
    evidence = []
    for agent in all_agents(session):
        kb = agent.read_kb.get("instructions", 0.0)
        if kb > GUIDE_MAX_KB:
            evidence.append(f"{agent.label}: {kb:.1f}KB of instructions.md Read results")
    return RuleResult("R3", "guide-whole", passed=not evidence, evidence=evidence)


def _batchable_runs(agent: AgentTranscript) -> list:
    """Runs of >=BATCHABLE_MIN_RUN consecutive small shell calls, each within
    BATCHABLE_WINDOW_SECONDS of the previous one, uninterrupted by any other
    tool call (which is what "no edit between" reduces to when walking the
    full ordered tool-call list)."""
    runs = []
    current: list = []
    for call in agent.tool_calls:
        is_small_shell = (
            call.name in SHELL_TOOLS
            and call.ts_end is not None
            and call.result_bytes < BATCHABLE_RESULT_MAX_BYTES
        )
        if is_small_shell and current and (call.ts_start - current[-1].ts_start).total_seconds() <= BATCHABLE_WINDOW_SECONDS:
            current.append(call)
        elif is_small_shell:
            if len(current) >= BATCHABLE_MIN_RUN:
                runs.append(current)
            current = [call]
        else:
            if len(current) >= BATCHABLE_MIN_RUN:
                runs.append(current)
            current = []
    if len(current) >= BATCHABLE_MIN_RUN:
        runs.append(current)
    return runs


def rule_r4_batching(session: Session) -> RuleResult:
    evidence = []
    for agent in all_subagents(session):
        if agent.agent_type != "implementer":
            continue
        if agent.turn_count < BATCHABLE_MIN_TURNS:
            continue
        runs = _batchable_runs(agent)
        batchable = sum(len(r) - 1 for r in runs)
        share = batchable / agent.turn_count
        if share > BATCHABLE_SHARE_MAX:
            longest = max((len(r) for r in runs), default=0)
            evidence.append(
                f"{agent.label}: batchable share {share:.0%} "
                f"({batchable}/{agent.turn_count} turns, longest run {longest})"
            )
    return RuleResult("R4", "batching", passed=not evidence, evidence=evidence)


def rule_r5_blocking_call(session: Session) -> RuleResult:
    evidence = []
    for agent in all_agents(session):
        for call in agent.tool_calls:
            if call.name in BLOCKING_EXEMPT_TOOLS:
                continue
            d = call.duration_seconds
            if d is not None and d > BLOCKING_CALL_MAX_SECONDS:
                cmd = _cmd_text(call) or str(call.tool_input.get("file_path", ""))
                evidence.append(f"{agent.label} {call.name} took {d:.0f}s at {call.ts_start}: {cmd[:120]}")
    return RuleResult("R5", "blocking-call", passed=not evidence, evidence=evidence)


def rule_r6_planner_rewrite(session: Session) -> RuleResult:
    evidence = []
    for agent in all_agents(session):
        if agent.agent_type != "planner":
            continue
        seen: dict = {}
        for fp, ts in agent.write_paths:
            low = fp.replace("\\", "/").lower()
            if not (low.endswith("-plan.md") or low.endswith("-context.md")):
                continue
            if fp in seen:
                evidence.append(f"{agent.label} rewrote {fp} (first at {seen[fp]}, again at {ts})")
            else:
                seen[fp] = ts
    return RuleResult("R6", "planner-rewrite", passed=not evidence, evidence=evidence)


def rule_r7_reviewer_budget(session: Session) -> RuleResult:
    evidence = []
    for agent in all_subagents(session):
        if agent.agent_type not in REVIEWER_TYPES:
            continue
        if agent.turn_count > REVIEWER_MAX_TURNS or agent.total_tokens > REVIEWER_MAX_TOKENS:
            evidence.append(
                f"{agent.label}: {agent.turn_count} turns, {agent.total_tokens:,} tokens "
                f"(budget {REVIEWER_MAX_TURNS} turns / {REVIEWER_MAX_TOKENS:,} tokens)"
            )
    return RuleResult("R7", "reviewer-budget", passed=not evidence, evidence=evidence)


def rule_r8_implementer_budget(session: Session) -> RuleResult:
    evidence = []
    for agent in all_subagents(session):
        if agent.agent_type != "implementer":
            continue
        over_turns = agent.turn_count > IMPLEMENTER_MAX_TURNS
        over_tokens = agent.total_tokens > IMPLEMENTER_MAX_TOKENS
        over_ctx = agent.avg_context_per_turn > IMPLEMENTER_MAX_CONTEXT_PER_TURN
        if over_turns or over_tokens or over_ctx:
            evidence.append(
                f"{agent.label}: {agent.turn_count} turns, {agent.total_tokens:,} tokens, "
                f"{agent.avg_context_per_turn:,.0f} context/turn "
                f"(budget {IMPLEMENTER_MAX_TURNS} / {IMPLEMENTER_MAX_TOKENS:,} / {IMPLEMENTER_MAX_CONTEXT_PER_TURN:,})"
            )
    return RuleResult("R8", "implementer-budget", passed=not evidence, evidence=evidence)


def rule_r9_verifier_budget(session: Session) -> RuleResult:
    evidence = []
    for agent in all_subagents(session):
        if agent.agent_type != "verifier":
            continue
        if agent.turn_count > VERIFIER_MAX_TURNS or agent.total_tokens > VERIFIER_MAX_TOKENS:
            evidence.append(
                f"{agent.label}: {agent.turn_count} turns, {agent.total_tokens:,} tokens "
                f"(budget {VERIFIER_MAX_TURNS} turns / {VERIFIER_MAX_TOKENS:,} tokens)"
            )
    return RuleResult("R9", "verifier-budget", passed=not evidence, evidence=evidence)


def rule_r10_driver_discipline(session: Session) -> RuleResult:
    evidence = []
    driver = session.driver
    patterns = [re.compile(p, re.IGNORECASE) for p in DRIVER_BUILD_TEST_PATTERNS]
    for call in driver.tool_calls:
        if call.name in SHELL_TOOLS:
            cmd = _cmd_text(call)
            if any(p.search(cmd) for p in patterns):
                evidence.append(f"driver {call.name} builds/tests at {call.ts_start}: {cmd[:120]}")
        elif call.name in EDIT_TOOLS:
            fp = str(call.tool_input.get("file_path", "")).replace("\\", "/")
            if DRIVER_ALLOWED_EDIT_PREFIX not in fp:
                evidence.append(f"driver {call.name} outside {DRIVER_ALLOWED_EDIT_PREFIX} at {call.ts_start}: {fp}")

    for round_, window in _round_windows(session).items():
        start, end = window
        count = sum(1 for t in driver.turns.values() if start <= t.ts <= end)
        if count > DRIVER_MAX_TURNS_PER_ROUND:
            evidence.append(f"driver: {count} turns during round {round_} (budget {DRIVER_MAX_TURNS_PER_ROUND})")

    return RuleResult("R10", "driver-discipline", passed=not evidence, evidence=evidence)


def _round_windows(session: Session) -> dict:
    """round number -> (earliest ts, latest ts) spanned by that round's
    subagents, used to attribute driver turns to a round."""
    windows: dict = {}
    for agent in all_subagents(session):
        if agent.round is None or agent.ts_first is None or agent.ts_last is None:
            continue
        lo, hi = windows.get(agent.round, (agent.ts_first, agent.ts_last))
        windows[agent.round] = (min(lo, agent.ts_first), max(hi, agent.ts_last))
    return windows


def rule_r11_replans(session: Session) -> RuleResult:
    planners = [a for a in all_agents(session) if a.agent_type == "planner" and a.ts_first]
    planners.sort(key=lambda a: a.ts_first)
    evidence = []
    for p in planners[1:]:
        evidence.append(f"{p.label}: {p.total_tokens:,} tokens (replan)")
    passed = len(planners) - 1 < 2  # "two or more [replans] fails"
    return RuleResult("R11", "replans", passed=passed, evidence=evidence)


def _plan_context_paths(session: Session) -> dict:
    """Distinct plan/context paths, keyed by a normalized form so the same
    file mentioned with forward and back slashes is only checked once."""
    paths: dict = {}

    def consider(fp: Optional[str]) -> None:
        if not fp:
            return
        low = fp.replace("\\", "/").lower()
        if low.endswith("-plan.md") or low.endswith("-context.md"):
            key = os.path.normcase(os.path.normpath(fp))
            paths.setdefault(key, fp)

    for agent in all_agents(session):
        for call in agent.tool_calls:
            consider(call.tool_input.get("file_path"))
        for fp, _ts in agent.write_paths:
            consider(fp)
    return paths


def rule_r12_plan_size(session: Session) -> RuleResult:
    evidence = []
    for fp in sorted(_plan_context_paths(session).values()):
        p = Path(fp)
        if not p.is_file():
            continue
        kb = p.stat().st_size / 1024.0
        low = fp.replace("\\", "/").lower()
        if low.endswith("-plan.md") and kb > PLAN_MAX_KB:
            evidence.append(f"{fp}: {kb:.1f}KB (> {PLAN_MAX_KB}KB)")
        elif low.endswith("-context.md") and kb > CONTEXT_MAX_KB:
            evidence.append(f"{fp}: {kb:.1f}KB (> {CONTEXT_MAX_KB}KB)")
    return RuleResult("R12", "plan-size", passed=not evidence, evidence=evidence)


def rule_r13_round_budget(session: Session) -> RuleResult:
    totals: dict = defaultdict(int)
    for agent in all_subagents(session):
        if agent.round is not None:
            totals[agent.round] += agent.total_tokens
    evidence = []
    for round_, total in sorted(totals.items()):
        if total > ROUND_MAX_TOKENS:
            evidence.append(f"round {round_}: {total:,} subagent tokens (budget {ROUND_MAX_TOKENS:,})")
    return RuleResult("R13", "round-budget", passed=not evidence, evidence=evidence)


def rule_r14_reviewer_reruns_suite(session: Session) -> RuleResult:
    evidence = []
    patterns = [re.compile(p, re.IGNORECASE) for p in DRIVER_BUILD_TEST_PATTERNS]
    for agent in all_subagents(session):
        if agent.agent_type not in REVIEWER_TYPES or agent.agent_type in REVIEWER_TEST_RUN_EXEMPT:
            continue
        runs = [c for c in agent.tool_calls
                if c.name in SHELL_TOOLS and any(p.search(_cmd_text(c)) for p in patterns)]
        if len(runs) > REVIEWER_MAX_TEST_RUNS:
            evidence.append(
                f"{agent.label}: {len(runs)} test/build runs (budget {REVIEWER_MAX_TEST_RUNS}), "
                f"first at {runs[0].ts_start}: {_cmd_text(runs[0])[:100]}"
            )
    return RuleResult("R14", "reviewer-reruns-suite", passed=not evidence, evidence=evidence)


ALL_RULES = [
    rule_r1_reviewer_reads_workorder,
    rule_r2_verifier_scope,
    rule_r3_guide_whole,
    rule_r4_batching,
    rule_r5_blocking_call,
    rule_r6_planner_rewrite,
    rule_r7_reviewer_budget,
    rule_r8_implementer_budget,
    rule_r9_verifier_budget,
    rule_r10_driver_discipline,
    rule_r11_replans,
    rule_r12_plan_size,
    rule_r13_round_budget,
    rule_r14_reviewer_reruns_suite,
]


def evaluate(session: Session) -> list:
    return [rule(session) for rule in ALL_RULES]


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def _agent_row(agent: AgentTranscript) -> dict:
    return {
        "label": agent.label,
        "agent_type": agent.agent_type,
        "workflow": agent.workflow_id or "-",
        "round": agent.round if agent.round is not None else "-",
        "turns": agent.turn_count,
        "tokens": agent.total_tokens,
        "output_tokens": agent.total_output_tokens,
        "context_per_turn": round(agent.avg_context_per_turn),
        "peak_context": agent.peak_context,
        "wall_minutes": round(agent.wall_minutes, 1),
        "longest_tool_call_s": round(agent.longest_tool_call_seconds, 1),
    }


def build_table(session: Session) -> list:
    rows = [_agent_row(session.driver)]
    for agent in session.subagents:
        rows.append(_agent_row(agent))
    for wf_id in sorted(session.workflow_runs):
        for agent in sorted(session.workflow_runs[wf_id], key=lambda a: (a.round if a.round is not None else -1, a.label)):
            rows.append(_agent_row(agent))
    return rows


def build_comparison(session: Session) -> list:
    totals: dict = defaultdict(lambda: {"turns": 0, "tokens": 0, "count": 0, "context_sum": 0.0})
    for agent in all_subagents(session):
        role = agent.agent_type
        if role not in PRE_UPDATE_AVG:
            continue
        t = totals[role]
        t["turns"] += agent.turn_count
        t["tokens"] += agent.total_tokens
        t["context_sum"] += agent.avg_context_per_turn
        t["count"] += 1

    out = []
    for role, avg in PRE_UPDATE_AVG.items():
        t = totals.get(role)
        if not t or t["count"] == 0:
            continue
        n = t["count"]
        row = {
            "role": role,
            "runs": n,
            "turns_pct": round(100.0 * (t["turns"] / n) / avg["turns"], 1) if avg.get("turns") else None,
            "tokens_pct": round(100.0 * (t["tokens"] / n) / avg["tokens"], 1) if avg.get("tokens") else None,
        }
        if "context_per_turn" in avg:
            row["context_per_turn_pct"] = round(100.0 * (t["context_sum"] / n) / avg["context_per_turn"], 1)
        out.append(row)
    return out


def format_table(rows: list) -> str:
    if not rows:
        return "(no agents found)"
    cols = list(rows[0].keys())
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    lines = ["  ".join(c.ljust(widths[c]) for c in cols)]
    lines.append("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        lines.append("  ".join(str(r[c]).ljust(widths[c]) for c in cols))
    return "\n".join(lines)


def format_report(session: Session, results: list, comparison: list) -> str:
    out = []
    out.append(f"Session {session.session_id}  (project {session.project})")
    out.append("")
    out.append(format_table(build_table(session)))
    out.append("")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        out.append(f"{r.rule_id} {r.name}: {status}")
        for line in r.evidence:
            out.append(f"    {line}")
    out.append("")
    out.append("vs. pre-update §1 averages:")
    for row in comparison:
        parts = [f"turns {row['turns_pct']}%"] if row.get("turns_pct") is not None else []
        if row.get("tokens_pct") is not None:
            parts.append(f"tokens {row['tokens_pct']}%")
        if row.get("context_per_turn_pct") is not None:
            parts.append(f"context/turn {row['context_per_turn_pct']}%")
        out.append(f"  {row['role']} ({row['runs']} runs): " + ", ".join(parts))
    return "\n".join(out)


def to_json(session: Session, results: list, comparison: list) -> dict:
    return {
        "session_id": session.session_id,
        "project": session.project,
        "table": build_table(session),
        "rules": [
            {"rule_id": r.rule_id, "name": r.name, "passed": r.passed, "evidence": r.evidence}
            for r in results
        ],
        "comparison": comparison,
        "exit_code": 0 if all(r.passed for r in results) else 1,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def default_projects_dir() -> Path:
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())
    return home / ".claude" / "projects"


def main(argv: Optional[list] = None) -> int:
    # Windows consoles / redirected files often use a legacy codepage that
    # cannot encode "§"; force UTF-8 so the report is byte-identical whether
    # printed or saved.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--latest", action="store_true", help="use the most recently modified session")
    group.add_argument("--session", metavar="ID-PREFIX", help="session id prefix to audit")
    parser.add_argument("--projects-dir", type=Path, default=None, help="override ~/.claude/projects (for tests)")
    parser.add_argument("--project", default=None, help="project directory name; defaults to cwd's mangled name")
    parser.add_argument("--json", action="store_true", help="emit one JSON object instead of the text report")
    args = parser.parse_args(argv)

    if not args.latest and not args.session:
        parser.error("one of --latest or --session is required")

    projects_dir = args.projects_dir or default_projects_dir()
    project = args.project or default_project_dir()

    try:
        session_id, session_path = find_session_dir(projects_dir, project, args.session, args.latest)
        session = discover_session(projects_dir, project, session_id, session_path)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2

    results = evaluate(session)
    comparison = build_comparison(session)

    if args.json:
        print(json.dumps(to_json(session, results, comparison), indent=2))
    else:
        print(format_report(session, results, comparison))

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
