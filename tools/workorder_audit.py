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

A laned round (issue #176: `implementer:<lane>:r<n>` transcripts plus an
`implementer:join:r<n>`) gets a `lane` column in the table, a summary after
it -- each lane's wall minutes and cost, the round's span against the lanes'
serial sum, the join's wall minutes -- and the same under `lanes` in `--json`.

Exit code: 0 all rules pass, 1 a rule failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

# --------------------------------------------------------------------------
# Budgets. Recalibrated 2026-09-22 against the 22 sessions that ran
# `/workorder` between 2026-09-19 and 2026-09-22 (533 agents, 61 rounds,
# ~$1,160 at list price); `--calibrate <session list>` reprints every
# distribution below, and the evidence note is
# `docs/agents/workorder-calibration.md`.
#
# The rule: a budget sits at about the 90th percentile of what that role
# actually did, so a FAIL means "this run is in the slowest tenth -- look at
# it". The previous budgets were set just above a pre-update average so that
# a run at the old baseline would fail; after the pipeline changes they were
# meant to force, R7 still failed 17 of 22 sessions, R13 16 and R8 14 -- a
# rule that fails most runs gets read as noise, and then it catches nothing.
# --------------------------------------------------------------------------

# R8, set from the Opus-tier implementers (n=21: 17 on Opus 5, 4 on Opus 5.5)
# because `opus` is now the implementer's default tier: p90 123 turns, 27.6M
# tokens, 205K context per turn. For comparison Sonnet 5 implementers (n=43)
# ran p75 25.2M but p90 46.8M and max 78.9M -- the tail that hit round caps.
IMPLEMENTER_MAX_TURNS = 125
IMPLEMENTER_MAX_TOKENS = 28_000_000
IMPLEMENTER_MAX_CONTEXT_PER_TURN = 210_000

# R9: verifier (Haiku 4.5, n=61) p90 58 turns / 3.1M tokens -- the budget
# set on 2026-09-18 already sat there, and is kept.
VERIFIER_MAX_TURNS = 60
VERIFIER_MAX_TOKENS = 3_500_000

# R7, per reviewer type, p90 of each (turns / tokens): docs-sync 30 / 1.9M
# (n=60), decompile-output-guard 17 / 1.1M (n=59), sdk-contract 31 / 2.7M
# (n=28), instrument-blindness 21 / 1.3M (n=53). One budget for all five
# failed 17 of 22 sessions, almost always docs-sync at 26-37 turns, while
# holding decompile-output-guard to a limit it never came near. A type with
# too few runs to calibrate (tauri-command-reviewer, n=1) keeps the default.
REVIEWER_MAX_TURNS = 25
REVIEWER_MAX_TOKENS = 3_000_000
REVIEWER_BUDGETS = {
    "docs-sync-reviewer": (30, 2_500_000),
    "decompile-output-guard": (18, 1_500_000),
    "sdk-contract-reviewer": (32, 3_000_000),
    "instrument-blindness-reviewer": (22, 2_000_000),
}

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
# `AskUserQuestion` waits for a person to answer: 7 of R5's 8 failing
# sessions in the 2026-09-22 calibration cited a driver's question left open
# for 260-26,642s, and for 5 of them it was the only evidence -- the user
# thinking, not a hung call.
BLOCKING_EXEMPT_TOOLS = {"Agent", "Task", "AskUserQuestion"}

# R12: no plan/context should carry the implementation (see planner.md rule);
# these are size smells, not hard limits on what a plan may describe. Only
# the bytes the planner authored count: `## Log` is appended by the scribe,
# the implementer and the driver while the rounds run, so measuring it failed
# every multi-round run for the pipeline's own bookkeeping (measured
# 2026-09-18: an 11.7KB context file audited as 29.3KB, 18.3KB of it Log).
PLAN_MAX_KB = 30.0
CONTEXT_MAX_KB = 20.0
LOG_HEADING_RE = re.compile(rb"^## Log[ \t]*$")
H2_RE = re.compile(rb"^## ")
# A fence closes only on the same character, a run at least as long as the
# opener, and nothing after it -- the rule `section.py` uses, so the two
# agree on what is structure and what is quoted markdown.
FENCE_RE = re.compile(rb"^ {0,3}(`{3,}|~{3,})(.*)$")

# R13, per (workflow launch, round) -- see `_round_windows`. Round 0 carries
# the whole change and later rounds a defect, so they are budgeted apart:
# round 0 measured p50 22.5M / p75 32.7M / p90 56.7M (n=30), later rounds
# p50 7.5M / p75 14.7M / p90 22.8M (n=31). ROUND0 is the per-role budgets of a
# round-0 roster added up (implementer 28M + verifier 3.5M + about four
# reviewers at ~2M), so a round over it has at least one role over its own
# budget; later rounds sit at ~p85. The old single 15M budget failed 16 of 22.
ROUND0_MAX_TOKENS = 40_000_000
ROUND_MAX_TOKENS = 20_000_000

# R10: driver turns per round; a driver that needs more than this per round
# is doing the subagents' job instead of dispatching it.
DRIVER_MAX_TURNS_PER_ROUND = 20
DRIVER_BUILD_TEST_PATTERNS = (
    r"build\.bat", r"\bmsbuild\b", r"\bcargo\b", r"\bunittest\b",
    r"\bpytest\b", r"\bnpm\s", r"\bnode --test\b",
)
DRIVER_ALLOWED_EDIT_PREFIX = ".claude/workorders/"
# R10 judges the driver only while it is driving: from the first `/workorder`
# invocation to the first human message after the last subagent finished.
# Measured 2026-09-18: a user's "build the release plugin" request, typed
# after the workorder had passed, failed R10 for the run it followed.
WORKORDER_COMMAND_MARKER = "<command-name>/workorder</command-name>"

# R14: the reviewer replay on 2026-09-18 (same change, fixed dispatch) showed
# docs-sync and instrument-blindness each re-running test suites 5-6 times --
# work the verifier does in parallel. Two runs covers "one targeted test, once
# more after a look"; the two reviewers whose own files tell them to build and
# test are exempt.
REVIEWER_MAX_TEST_RUNS = 2
REVIEWER_TEST_RUN_EXEMPT = {"sdk-contract-reviewer", "tauri-command-reviewer"}

# R15: a session opened in a git worktree has every `Edit`/`Write` outside
# that worktree refused by the harness. Measured 2026-09-18 on a plan whose
# `repoRoot` was the main checkout: the implementer met the refusal three
# times and routed every edit through scratch byte-patch scripts instead --
# ~57 of its 142 turns and ~9.4M of its 22.6M tokens, plus a guard protecting
# the user's primary working copy bypassed. A refusal is a PLAN-DEFECT; the
# follow-up allowance covers gathering that verdict's evidence, nothing more.
WORKTREE_GUARD_MARKER = "is in the base repo checkout"
GUARD_REFUSAL_MAX_FOLLOWUP_CALLS = 5
RETURN_TOOL = "StructuredOutput"

# R16: measured 2026-09-19 (run wf_95c37e59-d40, workorder
# forgepact-prospect-materials-to-bag, round 1, session 42eeea81): the
# `Record`-phase scribe -- an unrestricted `workflow-subagent` labelled
# `scribe:r1` -- read reviewer/implementer findings next to the harness's
# relayed user message and acted on them instead of only recording them. It
# resolved the prompt's *relative* `.claude/workorders/...` paths against the
# user's home directory (creating files there, never touching the real
# workorder), edited `ForgePact/plugin/ModuleMain.cpp` and a docs file, and
# ran `git add`/`git commit` on both ForgePact and the hub's ForgePact
# pointer -- with no build, test or review. A scribe may only `Edit`/`Write`
# inside its own `.claude/workorders/`, and must never touch git.
#
# Round 1, measured 2026-09-19 on this very workorder's own session
# (141e6fb2, workflow wf_a2bac07a-62e): a second unrestricted `scribe:r1`
# repeated the incident on a route the git check above never sees at all --
# it tried `Write .claude/agents/scribe.md` (refused, not read), then
# overwrote the file anyway with a Bash heredoc (`cat > ... << 'EOF'`). Two
# more checks close that gap: any scribe's shell command with a file-write
# shape FAILs regardless of target (a scribe has no legitimate reason to
# write through a shell -- its two edits go through the `Edit` tool), and the
# restricted `scribe` agent type's `tools:` line carries no shell at all, so
# *any* shell call from that type is a live disproof of the restriction.
SCRIBE_ALLOWED_EDIT_PREFIX = ".claude/workorders/"
# Any git subcommand that is not on this read-only allow-list counts: `push`
# after the incident's `add`/`commit` is what would have made it
# unrecoverable, and `reset`/`checkout`/`restore`/`stash`/`merge`/`tag`/
# `submodule` write just as surely. Block by default, allow only reads.
GIT_READ_ONLY_SUBCOMMANDS = frozenset({
    "status", "diff", "log", "show", "rev-parse", "ls-files", "ls-tree",
    "cat-file", "blame", "grep", "describe", "merge-base", "shortlog",
})
# `git`, then any global options (`-C <path>`, `-c k=v`, `--no-pager`,
# `--git-dir=...`), then the subcommand word.
GIT_SUBCOMMAND_RE = re.compile(
    r"\bgit\b((?:\s+(?:-C\s+(?:\"[^\"]+\"|'[^']+'|\S+)|-c\s+\S+|--[\w-]+(?:=\S+)?))*)\s+([A-Za-z][\w-]*)",
    re.IGNORECASE)


def _git_mutations(cmd: str) -> List[str]:
    """Every git subcommand in `cmd` that is not a known read-only one."""
    return [m.group(2).lower() for m in GIT_SUBCOMMAND_RE.finditer(cmd)
            if m.group(2).lower() not in GIT_READ_ONLY_SUBCOMMANDS]

SHELL_WRITE_VERB_RE = re.compile(
    r"\b(tee|cp|mv|rm)\b|\bsed\s+-i\w*\b|"
    r"\b(Set-Content|Add-Content|Out-File|New-Item|Copy-Item|Move-Item|Remove-Item)\b",
    re.IGNORECASE)
PY_FILE_WRITE_RE = re.compile(r"open\([^)\n]*?[\"'][wxa][b]?[\"']|\.write_text\(|\.write_bytes\(")
_NON_WRITE_REDIRECT_TARGETS = {"/dev/null", "$null", "nul"}
# `[ \t]*`, not `\s*`, between the redirect and its target: the planner's
# prototype matched a `>` at the end of an email address straight through the
# following newline into the next line's text as the "target" -- a false hit
# in a commit message, harmless there but the wrong shape to build on.
REDIRECT_WRITE_RE = re.compile(r"(?<![\-=])>{1,2}(?!&|=)[ \t]*(\"[^\"\n]+\"|'[^'\n]+'|[^\s|;&\n]+)")

# R2: `Read` is not the only way to open a file. The verifier's one sanctioned
# route into the context file is `section.py`, which refuses the Log unless
# it is passed `--log` -- which `verifier.md` forbids, so that is flagged too.
# The reader list is a heuristic, not a fence: it names the commands seen in
# real transcripts. Each must stand as a command token -- `head` inside the
# slug `forgepact-head-label-hook-context.md` is a path, not a reader.
CONTEXT_SHELL_READ_RE = re.compile(
    r"(?<![\w./\\-])(cat|type|sed|awk|head|tail|less|more|Get-Content|gc)\s+[^|;&\n]*-context\.md", re.IGNORECASE)
SECTION_LOG_FLAG_RE = re.compile(r"section\.py\b[^|;&\n]*(?<!\S)--log\b", re.IGNORECASE)

# R10: the agents a `/workorder` invocation itself spawns. Only these keep
# its window open -- an ad-hoc agent the user asks for afterwards is
# conversation, like the message that asked for it.
PIPELINE_AGENT_TYPES = {"planner", "implementer", "verifier", "consultant", "workflow-subagent", "live-operator"}

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

# List prices, $ per million tokens: (input, output, cache read), as published
# 2026-09 (the `claude-api` skill's model table). A cache write bills
# CACHE_WRITE_MULTIPLIER x input. These are for comparing roles and tiers with
# each other, not an invoice: a subscription does not bill per token. Price is
# why the tiers are where they are -- 92-99% of every role's tokens here are
# cache reads, and Opus 5.5 reads cache at Sonnet 5's price.
MODEL_PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-haiku-4-5-20251001": (1.0, 5.0, 0.10),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
CACHE_WRITE_MULTIPLIER = 1.25


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


# What the harness writes as a `user` record with no `origin`, in transcripts
# that otherwise carry one: none of these is the user speaking.
HARNESS_USER_PREFIXES = ("<task-notification>", "<ci-monitor-event>", "<local-command-stdout>",
                         "<local-command-stderr>", "[Request interrupted")


def _user_message_candidate(rec: dict, content) -> Optional[tuple]:
    """(text, origin kind or None) for a `user` record that could be the user
    typing, else None. Tool results, skill expansions (`isMeta`) and
    compaction summaries never are."""
    if rec.get("isMeta") or rec.get("isCompactSummary"):
        return None
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        text = _tool_result_text(content)
    elif isinstance(content, str):
        text = content
    else:
        return None
    origin = rec.get("origin")
    kind = origin.get("kind") if isinstance(origin, dict) else None
    return text, (kind or None)


def _human_messages(candidates: list) -> list:
    """[(ts, text)] the user typed. A transcript that records `origin.kind`
    anywhere is believed: only `human` counts, and its origin-less records
    (CI monitor events, interrupts, local command output) are the harness. A
    transcript from before `origin` existed falls back to the record's shape."""
    if any(kind for _, _, kind in candidates):
        return [(t, text) for t, text, kind in candidates if kind == "human"]
    return [(t, text) for t, text, _ in candidates
            if not text.lstrip().startswith(HARNESS_USER_PREFIXES)]


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
    guard_refused: bool = False  # the harness refused it: target outside the session's worktree

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
    models: dict = field(default_factory=lambda: defaultdict(int))  # model id -> assistant records
    tool_calls: list = field(default_factory=list)      # ToolCall, in order
    read_kb: dict = field(default_factory=lambda: defaultdict(float))  # kind -> KB
    write_paths: list = field(default_factory=list)     # (path, ts) for Write calls
    human_messages: list = field(default_factory=list)  # (ts, text) typed by the user, in order
    ts_first: Optional[datetime] = None
    ts_last: Optional[datetime] = None
    cwd: Optional[str] = None  # first non-empty top-level "cwd" this transcript's records carry

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
    def model(self) -> Optional[str]:
        """The model that produced most of this transcript's turns: what a
        tier alias (`opus`, `sonnet`) actually resolved to on the day."""
        return max(self.models, key=self.models.get) if self.models else None

    @property
    def cost_usd(self) -> Optional[float]:
        """List-price cost of this transcript's tokens, or None for a model
        MODEL_PRICES does not know."""
        price = MODEL_PRICES.get(self.model or "")
        if price is None:
            return None
        inp, out, read = price
        t = self.turns.values()
        return (sum(x.input_tokens for x in t) * inp
                + sum(x.cache_creation_tokens for x in t) * inp * CACHE_WRITE_MULTIPLIER
                + sum(x.cache_read_tokens for x in t) * read
                + sum(x.output_tokens for x in t) * out) / 1e6

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


# A lane implementer is labelled `implementer:<lane>:r<n>` and the join
# `implementer:join:r<n>` (`.claude/workflows/workorder-rounds.js` 2h); a
# plan without lanes keeps `implementer:r<n>`. Lane names are what
# `tools/plan_lint.py` accepts.
LANE_LABEL_RE = re.compile(r"^implementer:([a-z0-9-]+):r\d+$")


def lane_of(label: Optional[str]) -> Optional[str]:
    """The lane an implementer's label names (`join` for the join), or None."""
    m = LANE_LABEL_RE.match(label or "")
    return m.group(1) if m else None


def parse_transcript(path: Path, agent_type: str, label: str, session_id: str,
                      round_: Optional[int] = None, workflow_id: Optional[str] = None,
                      is_driver: bool = False) -> AgentTranscript:
    agent = AgentTranscript(
        agent_type=agent_type, label=label, session_id=session_id, path=path,
        round=round_, workflow_id=workflow_id, is_driver=is_driver,
    )
    pending: dict = {}  # tool_use_id -> ToolCall
    user_candidates: list = []  # (ts, text, origin kind), resolved once the whole transcript is read

    for rec in iter_jsonl(path):
        rec_type = rec.get("type")
        ts_raw = rec.get("timestamp")
        ts = parse_ts(ts_raw) if ts_raw else None
        if agent.cwd is None:
            rec_cwd = rec.get("cwd")
            if rec_cwd:
                agent.cwd = rec_cwd
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
            model = message.get("model")
            if model and model != "<synthetic>":
                agent.models[model] += 1
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
            candidate = _user_message_candidate(rec, content)
            if candidate is not None and ts is not None:
                user_candidates.append((ts, *candidate))
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
                call.guard_refused = call.name in EDIT_TOOLS and WORKTREE_GUARD_MARKER in text
                if call.name == "Read":
                    fp = call.tool_input.get("file_path")
                    if fp:
                        kind = read_kind(fp)
                        agent.read_kb[kind] += call.result_bytes / 1024.0

    agent.human_messages = _human_messages(user_candidates)
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


WORKTREE_PROJECT_MARKER = "--claude-worktrees-"


def sibling_projects(projects_dir: Path, project: str) -> list:
    """Every project directory of the same repository: the main checkout's
    and each `.claude/worktrees/<name>` session's, which Claude Code files
    under separate mangled names."""
    base = project.split(WORKTREE_PROJECT_MARKER, 1)[0]
    if not projects_dir.is_dir():
        return []
    return sorted(p.name for p in projects_dir.iterdir()
                  if p.is_dir() and (p.name == base or p.name.startswith(base + WORKTREE_PROJECT_MARKER)))


def locate_session(projects_dir: Path, project: str, session_prefix: Optional[str],
                   latest: bool) -> tuple:
    """(project, session id, transcript path). A `--session` prefix not found
    under `project` is looked for in the repository's other checkouts: every
    /workorder session in this repo runs in a worktree, and auditing one from
    another checkout otherwise needs its mangled name typed by hand."""
    try:
        return (project, *find_session_dir(projects_dir, project, session_prefix, latest))
    except SystemExit:
        if not session_prefix:
            raise
    hits = []
    for other in sibling_projects(projects_dir, project):
        if other == project:
            continue
        hits.extend((other, p) for p in (projects_dir / other).glob(f"{session_prefix}*.jsonl"))
    if len(hits) == 1:
        other, path = hits[0]
        return other, path.stem, path
    if hits:
        raise SystemExit(f"usage error: session prefix '{session_prefix}' is ambiguous: "
                         + ", ".join(f"{p.stem} ({o})" for o, p in hits))
    raise SystemExit(f"usage error: no session matching '{session_prefix}' in any checkout of this repository")


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
            if call.name in SHELL_TOOLS:
                cmd = _cmd_text(call)
                if CONTEXT_SHELL_READ_RE.search(cmd):
                    evidence.append(f"{agent.label} shell read of a context file at {call.ts_start}: {cmd[:120]}")
                if SECTION_LOG_FLAG_RE.search(cmd):
                    evidence.append(f"{agent.label} passed --log to section.py at {call.ts_start}: {cmd[:120]}")
                continue
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


def reviewer_budget(agent_type: str) -> tuple:
    """(max turns, max tokens) for one reviewer type."""
    return REVIEWER_BUDGETS.get(agent_type, (REVIEWER_MAX_TURNS, REVIEWER_MAX_TOKENS))


def rule_r7_reviewer_budget(session: Session) -> RuleResult:
    evidence = []
    for agent in all_subagents(session):
        if agent.agent_type not in REVIEWER_TYPES:
            continue
        max_turns, max_tokens = reviewer_budget(agent.agent_type)
        if agent.turn_count > max_turns or agent.total_tokens > max_tokens:
            evidence.append(
                f"{agent.label}: {agent.turn_count} turns, {agent.total_tokens:,} tokens "
                f"(budget {max_turns} turns / {max_tokens:,} tokens)"
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


def _workorder_windows(session: Session) -> list:
    """[(start, end), ...]: the spans in which the driver is driving a
    workorder; None on a side means unbounded. One span per `/workorder`
    invocation: it starts there and ends at the first human message, other
    than another `/workorder`, typed after the last pipeline agent that
    invocation started had finished (a phase agent, a reviewer, anything in a
    workflow run; an ad-hoc agent the user asks for later does not hold it
    open) -- what the user asks for once the pipeline has
    reported is conversation, not driving -- or at the next invocation,
    whichever comes first. One span for the whole session was not enough:
    with two workorders in a session, everything the user asked for between
    them still counted. A session with no invocation on record is judged
    whole, as before."""
    human = session.driver.human_messages
    starts = [t for t, text in human if WORKORDER_COMMAND_MARKER in text]
    if not starts:
        return [(None, None)]
    pipeline = PIPELINE_AGENT_TYPES | REVIEWER_TYPES
    subagents = [a for a in all_subagents(session)
                 if a.ts_first and a.ts_last and (a.workflow_id or a.agent_type in pipeline)]
    windows = []
    for i, start in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else None
        mine = [a.ts_last for a in subagents if a.ts_first >= start and (nxt is None or a.ts_first < nxt)]
        after = max(mine, default=start)
        end = next((t for t, text in human
                    if t > after and WORKORDER_COMMAND_MARKER not in text), None)
        if nxt is not None and (end is None or end > nxt):
            end = nxt
        windows.append((start, end))
    return windows


def rule_r10_driver_discipline(session: Session) -> RuleResult:
    evidence = []
    driver = session.driver
    patterns = [re.compile(p, re.IGNORECASE) for p in DRIVER_BUILD_TEST_PATTERNS]
    windows = _workorder_windows(session)
    for call in driver.tool_calls:
        # A call with no timestamp cannot be placed, so it is judged, as it
        # was before there were windows.
        ts = call.ts_start
        if ts is not None and not any((s is None or ts >= s) and (e is None or ts < e) for s, e in windows):
            continue
        if call.name in SHELL_TOOLS:
            cmd = _cmd_text(call)
            if any(p.search(cmd) for p in patterns):
                evidence.append(f"driver {call.name} builds/tests at {call.ts_start}: {cmd[:120]}")
        elif call.name in EDIT_TOOLS:
            fp = str(call.tool_input.get("file_path", "")).replace("\\", "/")
            if DRIVER_ALLOWED_EDIT_PREFIX not in fp:
                evidence.append(f"driver {call.name} outside {DRIVER_ALLOWED_EDIT_PREFIX} at {call.ts_start}: {fp}")

    for key, count in driver_turns_per_round(session).items():
        if count > DRIVER_MAX_TURNS_PER_ROUND:
            evidence.append(f"driver: {count} turns during {_round_name(key)} (budget {DRIVER_MAX_TURNS_PER_ROUND})")

    return RuleResult("R10", "driver-discipline", passed=not evidence, evidence=evidence)


def _round_name(key: tuple) -> str:
    workflow_id, round_ = key
    return f"round {round_}" + (f" [{workflow_id}]" if workflow_id else "")


def _round_windows(session: Session) -> dict:
    """(workflow id or None, round number) -> (earliest ts, latest ts) spanned
    by that round's subagents, used to attribute driver turns to a round.

    Keyed by workflow as well as round: a session drives several workorders,
    each with its own round 0, and one window per round *number* stretched
    from the first workorder's round 0 to the last one's -- measured
    2026-09-22, a session with seven workflow launches audited as one
    127M-token "round 0", and every driver turn between two workorders counted
    against it."""
    windows: dict = {}
    for agent in all_subagents(session):
        if agent.round is None or agent.ts_first is None or agent.ts_last is None:
            continue
        key = (agent.workflow_id, agent.round)
        lo, hi = windows.get(key, (agent.ts_first, agent.ts_last))
        windows[key] = (min(lo, agent.ts_first), max(hi, agent.ts_last))
    return windows


def driver_turns_per_round(session: Session) -> dict:
    """(workflow id or None, round) -> driver turns inside that round's window."""
    turns = session.driver.turns.values()
    return {key: sum(1 for t in turns if lo <= t.ts <= hi)
            for key, (lo, hi) in _round_windows(session).items()}


def round_totals(session: Session) -> dict:
    """(workflow id or None, round) -> subagent tokens spent in that round."""
    totals: dict = defaultdict(int)
    for agent in all_subagents(session):
        if agent.round is not None:
            totals[(agent.workflow_id, agent.round)] += agent.total_tokens
    return dict(totals)


def rule_r11_replans(session: Session) -> RuleResult:
    planners = [a for a in all_agents(session) if a.agent_type == "planner" and a.ts_first]
    planners.sort(key=lambda a: a.ts_first)
    verdicts = amendment_verdicts(session)
    evidence = []
    for p in planners[1:]:
        # An amendment `tools/amend_check.py check` passed is not a replan
        # (SKILL.md Step 2); one it failed, or that nobody checked, is.
        if verdicts.get(id(p)) is True:
            continue
        evidence.append(f"{p.label}: {p.total_tokens:,} tokens (replan)")
    passed = len(evidence) < 2  # "two or more [replans] fails"; a checked amendment is not one
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


def authored_and_log_kb(data: bytes) -> tuple[float, float]:
    """(planner-authored KB, `## Log` KB). The Log section runs from its
    heading to the next `## ` heading or the end of the file -- last in a
    context file, not necessarily last in a legacy single-file plan."""
    log_start = log_end = None
    fence = None
    offset = 0
    for raw in data.splitlines(keepends=True):
        line = raw.rstrip(b"\r\n")
        f = FENCE_RE.match(line)
        if f and fence is None and f.group(1)[:1] == b"`" and b"`" in f.group(2):
            f = None  # inline ```code``` opening a prose line, not a fence
        if f:
            run, rest = f.group(1), f.group(2)
            if fence is None:
                fence = run
            elif run[:1] == fence[:1] and len(run) >= len(fence) and not rest.strip():
                fence = None
        elif fence is None:
            if log_start is None:
                if LOG_HEADING_RE.match(line):
                    log_start = offset
            elif H2_RE.match(line) and not LOG_HEADING_RE.match(line):
                # A second `## Log` continues the first: measured
                # 2026-09-22, a driver appended one at the end of a context
                # file, and everything under it was audited as authored.
                log_end = offset
                break
        offset += len(raw)
    if log_start is None:
        return len(data) / 1024.0, 0.0
    log_bytes = (log_end if log_end is not None else len(data)) - log_start
    return (len(data) - log_bytes) / 1024.0, log_bytes / 1024.0


def rule_r12_plan_size(session: Session) -> RuleResult:
    evidence = []
    for fp in sorted(_plan_context_paths(session).values()):
        p = Path(fp)
        if not p.is_file():
            continue
        try:
            kb, log_kb = authored_and_log_kb(p.read_bytes())
        except OSError:
            continue
        low = fp.replace("\\", "/").lower()
        budget = PLAN_MAX_KB if low.endswith("-plan.md") else CONTEXT_MAX_KB
        if kb > budget:
            evidence.append(f"{fp}: {kb:.1f}KB authored (> {budget}KB; its ## Log, {log_kb:.1f}KB, is not counted)")
    return RuleResult("R12", "plan-size", passed=not evidence, evidence=evidence)


def round_budget(round_: int, implementers: int = 1) -> int:
    """A round's token budget. Both figures were calibrated on one implementer
    per round; a laned round runs k implementers (its lanes and the join),
    each already held to its own budget by R8, so it gets k times the figure."""
    base = ROUND0_MAX_TOKENS if round_ == 0 else ROUND_MAX_TOKENS
    return base * implementers if implementers > 1 else base


def round_implementers(session: Session) -> dict:
    """(workflow id or None, round) -> implementer transcripts in that round."""
    counts: dict = defaultdict(int)
    for agent in all_subagents(session):
        if agent.round is not None and agent.agent_type == "implementer":
            counts[(agent.workflow_id, agent.round)] += 1
    return dict(counts)


def rule_r13_round_budget(session: Session) -> RuleResult:
    evidence = []
    implementers = round_implementers(session)
    for key, total in sorted(round_totals(session).items(), key=lambda kv: (kv[0][0] or "", kv[0][1])):
        budget = round_budget(key[1], implementers.get(key, 1))
        if total > budget:
            evidence.append(f"{_round_name(key)}: {total:,} subagent tokens (budget {budget:,})")
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


WORKTREE_DIR_MARKER = "/.claude/worktrees/"


def _same_file_edit_landed(refused: ToolCall, later: ToolCall) -> bool:
    """Did `later` make the refused edit where it belongs: inside a worktree,
    at the same repo-relative path? A same-named file anywhere else is not a
    correction -- the real run wrote `release-notes-v1.4.2.md` to its
    scratchpad and `cp`'d it over the main checkout's, which is the
    workaround itself."""
    if later.name not in EDIT_TOOLS or later.guard_refused or later.is_error:
        return False
    norm = lambda c: str(c.tool_input.get("file_path", "")).replace("\\", "/").lower()
    was, now = norm(refused), norm(later)
    if not was or WORKTREE_DIR_MARKER not in now:
        return False
    tail = now.split(WORKTREE_DIR_MARKER, 1)[1].split("/", 1)  # [worktree name, repo-relative path]
    return len(tail) == 2 and bool(tail[1]) and was.endswith("/" + tail[1])


def rule_r15_edit_guard_workaround(session: Session) -> RuleResult:
    evidence = []
    for agent in all_subagents(session):
        calls = agent.tool_calls
        # A refusal the agent answered by making the same edit inside its own
        # worktree (it mistyped the path; the guard's message names the right
        # one) is the guard working, not a workaround.
        refused = [i for i, c in enumerate(calls)
                   if c.guard_refused and not any(_same_file_edit_landed(c, later) for later in calls[i + 1:])]
        if not refused:
            continue
        # The agent's own return is a tool call in workflow mode; it is how
        # the PLAN-DEFECT travels, not work done after the refusal.
        followups = sum(1 for c in calls[refused[0] + 1:] if c.name != RETURN_TOOL)
        if followups > GUARD_REFUSAL_MAX_FOLLOWUP_CALLS:
            first = calls[refused[0]]
            evidence.append(
                f"{agent.label}: {first.name} of {first.tool_input.get('file_path', '?')} refused by the "
                f"worktree guard at {first.ts_start} ({len(refused)} refusal(s)), then {followups} more tool "
                f"calls (a refusal is a PLAN-DEFECT; allowance {GUARD_REFUSAL_MAX_FOLLOWUP_CALLS})"
            )
    return RuleResult("R15", "edit-guard-workaround", passed=not evidence, evidence=evidence)


def _is_scribe(agent: AgentTranscript) -> bool:
    if agent.agent_type == "scribe":
        return True
    role, _round = parse_label(agent.label)
    return role == "scribe"


SCRIBE_ALLOWED_EDIT_SUFFIX = SCRIBE_ALLOWED_EDIT_PREFIX.rstrip("/")  # ".claude/workorders"


def _scribe_edit_allowed(file_path: str, cwd: Optional[str], anchor: Optional[str] = None) -> bool:
    """Relative and under `.claude/workorders/`, or absolute and under
    `<cwd>/.claude/workorders/` -- with `<cwd>` itself allowed to already
    *be* a `.claude/workorders` directory (measured on the real 2026-09-19
    session: a clean scribe from an earlier workorder in the same session ran
    with its `cwd` already scoped to `.claude/workorders`, not the repo
    root, and edited its own two files directly inside it). A stray write to
    a *different* directory that happens to contain `.claude/workorders/`
    (the real run's home-directory files) is still a violation -- it is
    judged against this transcript's own `cwd`, not a bare substring test
    (that is R10's weaker fallback, used here only when no `cwd` was recorded
    at all)."""
    low = str(file_path).replace("\\", "/").lower()
    if cwd:
        norm_cwd = cwd.replace("\\", "/").rstrip("/").lower()
        # The workorder directory is anchored on the session's own checkout
        # (the driver's `cwd`) when it is known, so a scribe running from the
        # wrong directory cannot make that directory its own allowed root.
        root = (anchor or cwd).replace("\\", "/").rstrip("/").lower()
        if root == SCRIBE_ALLOWED_EDIT_SUFFIX or root.endswith("/" + SCRIBE_ALLOWED_EDIT_SUFFIX):
            base = root
        else:
            base = root + "/" + SCRIBE_ALLOWED_EDIT_SUFFIX
        # A relative path is resolved against this transcript's own `cwd`
        # too: `.claude/workorders/x` written from a home directory lands in
        # the home directory, the incident's own spelling.
        is_abs = low.startswith("/") or re.match(r"^[a-z]:/", low) is not None
        full = low if is_abs else posixpath.normpath(norm_cwd + "/" + low)
        return full.startswith(base + "/")
    if low.startswith(SCRIBE_ALLOWED_EDIT_PREFIX):
        return True
    return f"/{SCRIBE_ALLOWED_EDIT_PREFIX}" in low


def _shell_write_evidence(cmd: str) -> bool:
    """True if `cmd` writes a file through the shell -- a write verb/cmdlet,
    a Python file write, or an output redirect whose target is not one of
    the null-device spellings. Not flagged: `2>&1`/`>&2` fd duplication,
    `>=`/`->`/`=>` operators, `| head`/`| grep`/`| tail`, and heredoc *input*
    (`<<`)."""
    if SHELL_WRITE_VERB_RE.search(cmd) or PY_FILE_WRITE_RE.search(cmd):
        return True
    for m in REDIRECT_WRITE_RE.finditer(cmd):
        target = m.group(1).strip("\"'")
        if target.lower() not in _NON_WRITE_REDIRECT_TARGETS:
            return True
    return False


def rule_r16_scribe_scope(session: Session) -> RuleResult:
    evidence = []
    for agent in all_subagents(session):
        if not _is_scribe(agent):
            continue
        tag = f"{agent.label} [{agent.workflow_id}]" if agent.workflow_id else agent.label
        restricted = agent.agent_type == "scribe"
        for call in agent.tool_calls:
            if call.name in EDIT_TOOLS:
                fp = str(call.tool_input.get("file_path", ""))
                if not _scribe_edit_allowed(fp, agent.cwd, getattr(session.driver, "cwd", None)):
                    evidence.append(f"{tag} {call.name} outside {SCRIBE_ALLOWED_EDIT_PREFIX} at {call.ts_start}: {fp}")
            elif call.name in SHELL_TOOLS:
                cmd = _cmd_text(call)
                if restricted:
                    evidence.append(
                        f"{tag} {call.name} shell call by restricted scribe type at {call.ts_start}: {cmd[:120]}")
                    continue
                mutations = _git_mutations(cmd)
                if mutations:
                    evidence.append(
                        f"{tag} {call.name} ran git {'/'.join(dict.fromkeys(mutations))} at {call.ts_start}: {cmd[:120]}")
                elif _shell_write_evidence(cmd):
                    evidence.append(f"{tag} {call.name} shell write at {call.ts_start}: {cmd[:120]}")
    return RuleResult("R16", "scribe-scope", passed=not evidence, evidence=evidence)


LIVE_CAPTURE_RE = re.compile(r"(^|/)\.claude/workorders/[^/]+-live-\d+\.md$", re.IGNORECASE)
DLL_INSTALL_RE = re.compile(
    r"\b(cp|mv|copy|xcopy|robocopy|Copy-Item|Move-Item)\b[^|;&\n]*\.dll\b|\binstallmod\b", re.IGNORECASE)


def rule_r17_live_operator_scope(session: Session) -> RuleResult:
    """`live-operator` runs the owner's game: it may write its own capture
    file and nothing else, never installs a build (the owner decides when the
    DLL their game loads changes), never runs a writing git command, never
    restores saves or force-stops the game on its own, and never takes over
    another session's game lease: `hs_lease_acquire` with `force` is the
    owner's decision, made through the driver, and a held lease is the
    operator's `LIVE-ABORTED`."""
    evidence = []
    for agent in all_subagents(session):
        if agent.agent_type != "live-operator":
            continue
        for call in agent.tool_calls:
            if call.name in EDIT_TOOLS:
                fp = str(call.tool_input.get("file_path", "")).replace("\\", "/")
                if not LIVE_CAPTURE_RE.search(fp):
                    evidence.append(f"{agent.label} {call.name} outside its capture file at {call.ts_start}: {fp}")
            elif call.name in SHELL_TOOLS:
                cmd = _cmd_text(call)
                mutations = _git_mutations(cmd)
                if mutations:
                    evidence.append(f"{agent.label} ran git {'/'.join(dict.fromkeys(mutations))} at {call.ts_start}: {cmd[:120]}")
                if DLL_INSTALL_RE.search(cmd):
                    evidence.append(f"{agent.label} installed a build at {call.ts_start}: {cmd[:120]}")
            elif call.name.endswith("hs_saves_restore"):
                evidence.append(f"{agent.label} restored saves at {call.ts_start}")
            elif call.name.endswith("hs_stop_game") and call.tool_input.get("force"):
                evidence.append(f"{agent.label} force-stopped the game at {call.ts_start}")
            elif call.name.endswith("hs_lease_acquire") and call.tool_input.get("force"):
                evidence.append(f"{agent.label} forced a lease takeover at {call.ts_start}")
    return RuleResult("R17", "live-operator-scope", passed=not evidence, evidence=evidence)


# R18: measured 2026-09-23 (forgepact-issue-14-phaseA, -phaseA-record,
# -phase1h; phase1c/phase1d the same week). Handed four State lines to
# "replace", the haiku scribe used the whole `## State` block as its Edit's
# old_string and wrote back only those four, so `gates:`, `round base:`,
# `agents:` and `decisions in force:` vanished and the next verifier reported
# gated criteria pending instead of running them. `workorder-rounds.js` 2e now
# hands the scribe the merged block and stops the launch as STATE-LOST when
# its before/after report shows a dropped line; this rule is the transcript
# side of the same check -- a scribe Edit to a `-plan.md` whose old_string
# carries a `key:` entry that its new_string no longer has.
STATE_KEY_RE = re.compile(r"^([a-z][a-z0-9 _-]*?):(\s|$)", re.IGNORECASE)
STATE_KEY_SPLIT_RE = re.compile(r"\s{2,}(?=[a-z][a-z0-9 _-]*?:\s)", re.IGNORECASE)


def state_keys(text: str) -> list:
    """The `key:` entries in a State fragment, in order -- one per line, and
    a hand-written line carrying two (`round: 0        phase: plan`) counts
    both. Headings and lines with no key are not entries."""
    keys = []
    for line in str(text or "").splitlines():
        line = line.rstrip()
        if not line.strip() or line.startswith("#") or not STATE_KEY_RE.match(line):
            continue
        for seg in STATE_KEY_SPLIT_RE.split(line):
            m = STATE_KEY_RE.match(seg)
            if m:
                keys.append(m.group(1).lower())
    return keys


def rule_r18_scribe_state_preserved(session: Session) -> RuleResult:
    evidence = []
    for agent in all_subagents(session):
        if not _is_scribe(agent):
            continue
        tag = f"{agent.label} [{agent.workflow_id}]" if agent.workflow_id else agent.label
        for call in agent.tool_calls:
            if call.name not in EDIT_TOOLS or call.is_error or call.guard_refused:
                continue
            fp = str(call.tool_input.get("file_path", "")).replace("\\", "/")
            if not fp.lower().endswith("-plan.md") or "old_string" not in call.tool_input:
                continue
            new_keys = set(state_keys(call.tool_input.get("new_string", "")))
            dropped = [k for k in dict.fromkeys(state_keys(call.tool_input.get("old_string", ""))) if k not in new_keys]
            if dropped:
                evidence.append(f"{tag} {call.name} dropped State {', '.join(k + ':' for k in dropped)} at {call.ts_start}: {fp}")
    return RuleResult("R18", "scribe-state-preserved", passed=not evidence, evidence=evidence)

# R19: measured 2026-09-24 (forgepact-issue-14-phase1j). The planner wrote
# `gates:` as a template of every gate and every possible value joined with
# `|` ("build: complete | live1: complete | record: complete | ..."). The
# verifier read it as every gate set and failed the live-session criteria for
# three rounds, and the launch went to CAP with no real defect open after
# round 0. `gates:` lists only the gates set, or `none`; the rest go on
# `gates pending:` / `route tokens:` (planner.md). `workorder-rounds.js` 2f
# treats such a line as no gate set; this rule catches whoever wrote it.
GATES_LINE_RE = re.compile(r"^gates:(.*)$", re.IGNORECASE | re.MULTILINE)
GATES_TEMPLATE_RE = re.compile(r"\||<[^>]*>")
GATES_OR_RE = re.compile(r"\bor\b", re.IGNORECASE)


def gates_template(text: str) -> Optional[str]:
    """The first `gates:` line in `text` whose value holds alternatives (`|`,
    or an "or" outside a backticked token) or a `<placeholder>`,
    parentheticals aside, else None."""
    for m in GATES_LINE_RE.finditer(str(text or "")):
        value = re.sub(r"\([^)]*\)", "", m.group(1))
        if GATES_TEMPLATE_RE.search(value) or GATES_OR_RE.search(re.sub(r"`[^`]*`", "", value)):
            return m.group(0).strip()
    return None


def rule_r19_gates_template(session: Session) -> RuleResult:
    evidence = []
    for agent in all_agents(session):
        for call in agent.tool_calls:
            if call.name not in EDIT_TOOLS or call.is_error or call.guard_refused:
                continue
            fp = str(call.tool_input.get("file_path", "")).replace("\\", "/")
            if not fp.lower().endswith("-plan.md"):
                continue
            line = gates_template(call.tool_input.get("content", call.tool_input.get("new_string", "")))
            if line:
                evidence.append(f"{agent.label} {call.name} wrote a template gates: line at {call.ts_start}: {fp}: {line[:120]}")
    return RuleResult("R19", "gates-template", passed=not evidence, evidence=evidence)


# R20: measured 2026-09-22..24 (forgepact-issue-14 phase1c r2, phaseA-record
# r0, phase1h r2). A capture whose check lines did not match the criterion's
# grep was "fixed" by the record-round implementer editing the operator's
# capture -- 9 Edit calls, in 1h renaming two checks and appending a whole
# check line with a verdict. The capture is the session's evidence and
# `live-operator` its only author; a line that does not parse is reported,
# never repaired (implementer.md). R17 holds the operator to its capture;
# this holds everyone else off it.
def rule_r20_live_capture_author(session: Session) -> RuleResult:
    evidence = []
    for agent in all_agents(session):
        if agent.agent_type == "live-operator":
            continue
        for call in agent.tool_calls:
            if call.name not in EDIT_TOOLS or call.is_error or call.guard_refused:
                continue
            fp = str(call.tool_input.get("file_path", "")).replace("\\", "/")
            if LIVE_CAPTURE_RE.search(fp):
                evidence.append(f"{agent.label} {call.name} on a live capture at {call.ts_start}: {fp}")
    return RuleResult("R20", "live-capture-author", passed=not evidence, evidence=evidence)


# R21: measured 2026-09-24 (forgepact-issue-14-phase1j-record r0): a verifier
# ran a criterion's `py -3 -c ...` as `python -c ...` and reported a false
# verdict; `python` is at least three times in the verifier transcripts.
# This repository's commands are `py -3`, and the verifier runs a criterion
# exactly as written (verifier.md step 2).
# Only in command position: `grep -i python` names it, it does not run it.
VERIFIER_BARE_PYTHON_RE = re.compile(r"(?:^|[;&|(\n])\s*python3?(?:\.exe)?\s")


def rule_r21_verifier_interpreter(session: Session) -> RuleResult:
    evidence = []
    for agent in all_subagents(session):
        if agent.agent_type != "verifier":
            continue
        for call in agent.tool_calls:
            cmd = _cmd_text(call)
            if cmd and VERIFIER_BARE_PYTHON_RE.search(cmd):
                evidence.append(f"{agent.label} ran python, not py -3, at {call.ts_start}: {cmd[:120]}")
    return RuleResult("R21", "verifier-interpreter", passed=not evidence, evidence=evidence)


# R22: measured over forgepact-issue-14's verifiers (2026-09-22..24): suite
# plus polling took 165 min, of which about 61 were a suite run again -- after
# the Bash tool's 120 s default killed the 150-170 s hub suite (37 of 60 hub
# runs), or to read another slice of the same output. verifier.md step 3 now
# runs each suite once with a 240 s timeout into a scratch file.
SUITE_RUN_RE = re.compile(
    r"(?:\bcd\s+(?P<cd>[^\s;&|]+)\s*(?:&&|;)\s*)?[^;&|]*?unittest\s+discover(?P<args>[^;&|>]*)", re.IGNORECASE)


def suite_key(cmd: str) -> Optional[str]:
    """Which suite a shell command runs -- the directory it `cd`s to, plus
    discover's own arguments -- or None if it runs none."""
    m = SUITE_RUN_RE.search(cmd)
    if not m:
        return None
    where = m.group("cd") or "."
    args = re.sub(r"\s\d$", "", m.group("args").rstrip())  # the `2` of a `2>&1`
    return f"{where.strip(chr(34) + chr(39)).rstrip('/')} {' '.join(args.split())}".strip()


def rule_r22_verifier_suite_once(session: Session) -> RuleResult:
    evidence = []
    for agent in all_subagents(session):
        if agent.agent_type != "verifier":
            continue
        runs: dict = defaultdict(list)
        for call in agent.tool_calls:
            key = suite_key(_cmd_text(call)) if call.name in SHELL_TOOLS else None
            if key:
                runs[key].append(call)
        for key, calls in runs.items():
            if len(calls) > 1:
                evidence.append(f"{agent.label} ran suite `{key}` {len(calls)} times, first at {calls[0].ts_start}")
    return RuleResult("R22", "verifier-suite-once", passed=not evidence, evidence=evidence)


# R23: lanes (issue #176) run as concurrent implementers in one checkout, and
# git's `.git/index.lock` is fail-fast: a second `git add`/`git commit` while
# another holds it fails at once instead of waiting. So a lane runs no git
# command that writes, and the join -- which runs alone, after every lane --
# commits each lane's file set. A lane transcript with any git write breaks
# the contract that makes running lanes together safe. The join and a
# laneless implementer commit as they always have.
def rule_r23_lane_git_mutation(session: Session) -> RuleResult:
    evidence = []
    for agent in all_subagents(session):
        lane = lane_of(agent.label)
        if lane is None or lane == "join":
            continue
        tag = f"{agent.label} [{agent.workflow_id}]" if agent.workflow_id else agent.label
        for call in agent.tool_calls:
            if call.name not in SHELL_TOOLS:
                continue
            cmd = _cmd_text(call)
            mutations = _git_mutations(cmd)
            if mutations:
                evidence.append(
                    f"{tag} ran git {'/'.join(dict.fromkeys(mutations))} at {call.ts_start}: {cmd[:120]}")
    return RuleResult("R23", "lane-git-mutation", passed=not evidence, evidence=evidence)


# R24: the two cheap routes for a defect whose fix is already known
# (SKILL.md Step 2 "Amend, or replan" and Step 4 "The patch route"). Each is
# cheap because it skips work, so each is only allowed where something other
# than the agent taking it has checked it applies:
#
#   * an amendment is a planner the driver labelled `amendment: ...` (a
#     distinct prefix: drivers have long written "Amend ..." for ordinary
#     replans, measured in session 039722c8). The driver
#     runs `tools/amend_check.py save` before spawning it and `check` after it
#     returns; `check` exits non-zero when the change reached the Goal, the
#     scope or the human questions, or grew past its line limit, and the
#     amendment then counts as a replan (R11). An amendment with no `save`
#     before it or no `check` after it was never checked at all, and two
#     amendments with no implementer between them are one replan in two parts.
#   * a patch round is `patch-implementer:r<n>`, spawned only by
#     `workorder-rounds.js`, which never runs two back to back; two in
#     consecutive rounds of one workflow launch mean that guard failed.
AMEND_LABEL_RE = re.compile(r"^\s*amendment:", re.I)
PATCH_LABEL_RE = re.compile(r"^patch-implementer:r(\d+)$")


def is_amendment(agent: AgentTranscript) -> bool:
    return agent.agent_type == "planner" and bool(AMEND_LABEL_RE.match(agent.label or ""))


def _driver_amend_calls(session: Session, verb: str) -> list:
    """The driver's shell calls running `amend_check.py <verb>`, in order."""
    pattern = re.compile(rf"amend_check\.py\"?\s+{verb}\b")
    return [c for c in session.driver.tool_calls
            if c.name in SHELL_TOOLS and pattern.search(_cmd_text(c))]


def amendment_verdicts(session: Session) -> dict:
    """`id(amendment planner)` -> True when the driver's first `amend_check.py
    check` after it ended passed, False when it failed, None when there was
    none."""
    checks = _driver_amend_calls(session, "check")
    out = {}
    for agent in all_subagents(session):
        if not is_amendment(agent) or agent.ts_last is None:
            continue
        after = [c for c in checks if c.ts_start >= agent.ts_last]
        out[id(agent)] = (not after[0].is_error) if after else None
    return out


def rule_r24_cheap_routes(session: Session) -> RuleResult:
    evidence = []
    verdicts = amendment_verdicts(session)
    saves = _driver_amend_calls(session, "save")
    planners = sorted((a for a in all_subagents(session) if a.agent_type == "planner" and a.ts_first),
                      key=lambda a: a.ts_first)
    implementers = [a for a in all_subagents(session) if a.agent_type == "implementer" and a.ts_first]
    for i, agent in enumerate(planners):
        if not is_amendment(agent):
            continue
        prev = planners[i - 1] if i else None
        since = prev.ts_first if prev else None
        if not any(c.ts_start <= agent.ts_first and (since is None or c.ts_start >= since) for c in saves):
            evidence.append(f"{agent.label}: no `amend_check.py save` before it")
        if verdicts.get(id(agent)) is None:
            evidence.append(f"{agent.label}: no `amend_check.py check` after it")
        if prev is not None and is_amendment(prev) and prev.ts_last and not any(
                prev.ts_last <= a.ts_first <= agent.ts_first for a in implementers):
            evidence.append(f"{agent.label}: a second amendment after {prev.label} with no implementer between")
    for wf_id, group in session.workflow_runs.items():
        rounds = sorted(int(m.group(1)) for a in group for m in [PATCH_LABEL_RE.match(a.label or "")] if m)
        for a, b in zip(rounds, rounds[1:]):
            if b == a + 1:
                evidence.append(f"[{wf_id}] patch rounds {a} and {b} ran back to back")
    return RuleResult("R24", "cheap-routes", passed=not evidence, evidence=evidence)


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
    rule_r15_edit_guard_workaround,
    rule_r16_scribe_scope,
    rule_r17_live_operator_scope,
    rule_r18_scribe_state_preserved,
    rule_r19_gates_template,
    rule_r20_live_capture_author,
    rule_r21_verifier_interpreter,
    rule_r22_verifier_suite_once,
    rule_r23_lane_git_mutation,
    rule_r24_cheap_routes,
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
        "lane": lane_of(agent.label) or "-",
        "model": (agent.model or "-").replace("claude-", ""),
        "turns": agent.turn_count,
        "tokens": agent.total_tokens,
        "output_tokens": agent.total_output_tokens,
        "context_per_turn": round(agent.avg_context_per_turn),
        "peak_context": agent.peak_context,
        "wall_minutes": round(agent.wall_minutes, 1),
        "longest_tool_call_s": round(agent.longest_tool_call_seconds, 1),
        "cost_usd": round(agent.cost_usd, 2) if agent.cost_usd is not None else "-",
    }


def session_cost(session: Session) -> tuple:
    """(list-price $ for every priced transcript, how many had no price)."""
    costs = [a.cost_usd for a in all_agents(session)]
    return sum(c for c in costs if c is not None), sum(1 for c in costs if c is None)


def lane_summary(session: Session) -> list:
    """One entry per (workflow, round) that ran two or more implementer
    transcripts: each lane's wall minutes and cost, the round's
    `span_minutes` (earliest lane start to latest lane end), its
    `serial_minutes` (the lanes' wall minutes added up) and the join's wall
    minutes. `span` against `serial` is the wall time the lanes saved, which
    is what docs/agents/workorder-calibration.md § "Lanes" measures."""
    groups: dict = defaultdict(list)
    for agent in all_subagents(session):
        if agent.round is not None and agent.agent_type == "implementer":
            groups[(agent.workflow_id, agent.round)].append(agent)
    out = []
    for (wf_id, round_), agents in sorted(groups.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])):
        if len(agents) < 2:
            continue
        lanes = sorted((a for a in agents if lane_of(a.label) != "join"), key=lambda a: (a.ts_first.timestamp() if a.ts_first else 0.0, a.label))
        joins = [a for a in agents if lane_of(a.label) == "join"]
        starts = [a.ts_first for a in lanes if a.ts_first]
        ends = [a.ts_last for a in lanes if a.ts_last]
        out.append({
            "workflow": wf_id or "-",
            "round": round_,
            "lanes": [{
                "lane": lane_of(a.label) or "-",
                "label": a.label,
                "wall_minutes": round(a.wall_minutes, 1),
                "cost_usd": round(a.cost_usd, 2) if a.cost_usd is not None else None,
            } for a in lanes],
            "span_minutes": round((max(ends) - min(starts)).total_seconds() / 60.0, 1) if starts and ends else 0.0,
            "serial_minutes": round(sum(a.wall_minutes for a in lanes), 1),
            "join_minutes": round(sum(a.wall_minutes for a in joins), 1) if joins else None,
        })
    return out


def format_lane_summary(summary: list) -> list:
    lines = []
    for s in summary:
        join = f"; join {s['join_minutes']} min" if s["join_minutes"] is not None else "; no join"
        lines.append(f"lanes, {_round_name((None if s['workflow'] == '-' else s['workflow'], s['round']))}: "
                     f"span {s['span_minutes']} min vs serial {s['serial_minutes']} min{join}")
        for x in s["lanes"]:
            cost = f"${x['cost_usd']:,.2f}" if x["cost_usd"] is not None else "unpriced"
            lines.append(f"  {x['lane']}  {x['label']}  {x['wall_minutes']} min  {cost}")
    return lines


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
    lanes = format_lane_summary(lane_summary(session))
    if lanes:
        out.append("")
        out.extend(lanes)
    cost, unpriced = session_cost(session)
    out.append(f"list-price cost: ${cost:,.2f}" + (f" ({unpriced} transcript(s) on an unpriced model)" if unpriced else ""))
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
        "lanes": lane_summary(session),
        "cost_usd": round(session_cost(session)[0], 2),
        "rules": [
            {"rule_id": r.rule_id, "name": r.name, "passed": r.passed, "evidence": r.evidence}
            for r in results
        ],
        "comparison": comparison,
        "exit_code": 0 if all(r.passed for r in results) else 1,
    }


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------

def percentile(values: list, p: float) -> float:
    """Linear-interpolated percentile, p in [0, 1]; 0 for no values."""
    xs = sorted(values)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _spread(values: list) -> dict:
    return {"n": len(values), "p50": percentile(values, .5), "p75": percentile(values, .75),
            "p90": percentile(values, .9), "max": max(values, default=0)}


def calibrate(sessions: list) -> dict:
    """The distributions the budgets above are set from, over many sessions:
    per role (and per reviewer type, and per role and model) turns, tokens,
    context per turn and list-price cost; per-round subagent tokens, round 0
    apart from later rounds; driver turns per round; and how many sessions
    each rule fails as the constants stand. Each budget's comment names the
    percentile it was set at, so re-running this on newer sessions says
    whether that still holds."""
    by_role: dict = defaultdict(list)
    by_role_model: dict = defaultdict(list)
    rounds0, rounds_later, driver_rounds, costs = [], [], [], []
    fails: dict = defaultdict(int)
    for session in sessions:
        for agent in all_subagents(session):
            by_role[agent.agent_type].append(agent)
            by_role_model[(agent.agent_type, agent.model or "?")].append(agent)
        by_role["driver"].append(session.driver)
        by_role_model[("driver", session.driver.model or "?")].append(session.driver)
        for (_wf, round_), total in round_totals(session).items():
            (rounds0 if round_ == 0 else rounds_later).append(total)
        driver_rounds.extend(driver_turns_per_round(session).values())
        costs.append(session_cost(session)[0])
        for result in evaluate(session):
            if not result.passed:
                fails[result.rule_id] += 1

    def role_row(agents: list) -> dict:
        priced = [a.cost_usd for a in agents if a.cost_usd is not None]
        return {"turns": _spread([a.turn_count for a in agents]),
                "tokens": _spread([a.total_tokens for a in agents]),
                "context_per_turn": _spread([a.avg_context_per_turn for a in agents]),
                "cost_usd": round(sum(priced), 2)}

    return {
        "sessions": len(sessions),
        "cost_usd": round(sum(costs), 2),
        "roles": {k: role_row(v) for k, v in sorted(by_role.items())},
        "roles_by_model": {f"{k[0]} / {k[1]}": role_row(v) for k, v in sorted(by_role_model.items())},
        "round0_tokens": _spread(rounds0),
        "later_round_tokens": _spread(rounds_later),
        "driver_turns_per_round": _spread(driver_rounds),
        "rule_fails": dict(sorted(fails.items(), key=lambda kv: int(kv[0][1:]))),
    }


def format_calibration(cal: dict) -> str:
    def fmt(s: dict, scale: float = 1.0, unit: str = "") -> str:
        return (f"n={s['n']:<3} p50={s['p50'] / scale:,.1f}{unit} p75={s['p75'] / scale:,.1f}{unit} "
                f"p90={s['p90'] / scale:,.1f}{unit} max={s['max'] / scale:,.1f}{unit}")
    out = [f"{cal['sessions']} sessions, list-price cost ${cal['cost_usd']:,.2f}", ""]
    for title, rows in (("per role", cal["roles"]), ("per role and model", cal["roles_by_model"])):
        out.append(f"{title}:")
        for name, r in rows.items():
            out.append(f"  {name}  (${r['cost_usd']:,.2f})")
            out.append(f"    turns   {fmt(r['turns'])}")
            out.append(f"    tokens  {fmt(r['tokens'], 1e6, 'M')}")
            out.append(f"    ctx     {fmt(r['context_per_turn'], 1e3, 'K')}")
        out.append("")
    out.append(f"round 0 subagent tokens   {fmt(cal['round0_tokens'], 1e6, 'M')}")
    out.append(f"later-round tokens        {fmt(cal['later_round_tokens'], 1e6, 'M')}")
    out.append(f"driver turns per round    {fmt(cal['driver_turns_per_round'])}")
    out.append("")
    out.append("sessions failing each rule at the current constants: "
               + (", ".join(f"{k} {v}/{cal['sessions']}" for k, v in cal["rule_fails"].items()) or "none"))
    return "\n".join(out)


def read_session_list(path: Path) -> list:
    """Session id prefixes, one per line (a leading project name is allowed
    and ignored; `#` starts a comment)."""
    prefixes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        words = line.split("#", 1)[0].split()
        if words:
            prefixes.append(words[-1])
    return prefixes


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
    group.add_argument("--session", metavar="ID-PREFIX",
                       help="session id prefix to audit; looked for in every checkout of this repository")
    group.add_argument("--calibrate", metavar="FILE", type=Path,
                       help="print the budget distributions over the sessions listed in FILE (one id prefix per line)")
    parser.add_argument("--projects-dir", type=Path, default=None, help="override ~/.claude/projects (for tests)")
    parser.add_argument("--project", default=None, help="project directory name; defaults to cwd's mangled name")
    parser.add_argument("--json", action="store_true", help="emit one JSON object instead of the text report")
    args = parser.parse_args(argv)

    if not args.latest and not args.session and not args.calibrate:
        parser.error("one of --latest, --session or --calibrate is required")

    projects_dir = args.projects_dir or default_projects_dir()
    project = args.project or default_project_dir()

    if args.calibrate:
        try:
            sessions = []
            for prefix in read_session_list(args.calibrate):
                found_project, session_id, session_path = locate_session(projects_dir, project, prefix, False)
                sessions.append(discover_session(projects_dir, found_project, session_id, session_path))
        except (SystemExit, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        cal = calibrate(sessions)
        print(json.dumps(cal, indent=2) if args.json else format_calibration(cal))
        return 0

    try:
        project, session_id, session_path = locate_session(projects_dir, project, args.session, args.latest)
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
