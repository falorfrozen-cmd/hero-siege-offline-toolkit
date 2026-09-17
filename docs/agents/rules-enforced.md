Story and evidence behind `AGENTS.md` § ["Some of These Rules Are Enforced, Not Just Written"](../../AGENTS.md#some-of-these-rules-are-enforced-not-just-written).

> **Historical wording, kept verbatim.** This is the section as it read before
> 2026-09-17. Two things it says have since changed, and `AGENTS.md` and
> [`.claude/README.md`](../../.claude/README.md) describe the current shape: the
> four `PostToolUse` checks now run inside one dispatcher
> (`.claude/hooks/post_tool_use.py`), and a phase only "keeps its context" when
> the driver *resumes* it — a fresh spawn starts empty.

## What the enforcement layer is, in full

[`.claude/`](.claude/README.md) carries the subset of this file that a machine
can check or run, so those rules stop depending on whether the right section was
read first. Four `PostToolUse` hooks (the catalog signature, the Tauri command
threading rules, the hub's frontend tests, and decompiled output reaching a
tracked file) and a `Stop` hook that reports processes this session started and
left running, five review agents (`sdk-contract-reviewer`,
`tauri-command-reviewer`, `decompile-output-guard`, `docs-sync-reviewer`,
`instrument-blindness-reviewer`), three phase agents that run a change through
plan → implement → verify at three different model tiers (`planner`,
`implementer`, `verifier`), a `consultant` a phase can put one hard decision to
without escalating the whole phase, and three skills (`/catalog-rebuild`,
`/workorder`
which drives those phases and routes defects back to the phase that caused them,
and a `submodule-context` skill that loads the guide named above). MCP servers
are in [`.mcp.json`](.mcp.json).

(Links above are copied verbatim from `AGENTS.md` and are root-relative from
there, not from this file.)

## Why the phase split exists

The phase split exists because the expensive failures in this file are not
planning failures — they are an implementer meeting something the plan did not
anticipate and writing something plausible instead of stopping. So the
`implementer` is required to return `PLAN-DEFECT` with evidence rather than
improvise, and the `verifier` runs the acceptance criteria and reports what they
actually printed rather than judging whether the code looks right. Both rules
are this file's "evidence before assertions" applied to a handover.

## Why ADVICE-NEEDED exists, and how the escalation tier is chosen

A phase that is merely *stuck* on one decision has a cheaper move than failing:
`ADVICE-NEEDED` puts that question to the `consultant` and resumes with the
answer, keeping its context and its progress. It must state what it would do
unaided, so the answer confirms or corrects a position rather than replacing the
thinking — a consultation that skips that field is a handoff wearing a question
mark, and the driver sends it back. Which problems start a tier higher is
decided up front from **observable properties of the task** (does it introduce
concurrency, must it establish an unknown mechanism, does it change how a hook
attaches), never from a model's self-reported confidence: a model that cannot
solve something is also badly calibrated about whether it can, which is the same
reason this file does not accept an unproven negative.
