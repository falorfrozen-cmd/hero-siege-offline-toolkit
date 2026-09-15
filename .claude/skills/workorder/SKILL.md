---
name: workorder
description: Run a change through plan -> implement -> verify with each phase at its own model tier, routing defects back to the phase that caused them. Use for any multi-step change; for a one-line fix, just make the fix.
disable-model-invocation: true
---

# Run a change as a workorder

You are the driver. You do not plan, implement or verify yourself — you dispatch
each phase to its own agent, read the verdict it returns, and decide where the
work goes next. Keeping that separation is the point: the verifier's value comes
from never having seen the implementer's reasoning, and it loses that the moment
you do the checking inline.

## The loop

```
                  ┌──────────────── PLAN-DEFECT ◄──────────────┐
                  ▼                                            │
   ┌──────────┐      ┌───────────────┐      ┌──────────────────┴─┐
   │ planner  │─────►│  implementer  │─────►│ verifier +         │
   │  opus    │      │    sonnet     │◄─────│ domain reviewers   │
   └──────────┘      └───────────────┘      └────────────────────┘
                          IMPL-DEFECT         haiku + sonnet/opus
                                                        │
                                                      PASS
                                                        ▼
                                                  report to human
```

### Step 0 — decide whether this is worth a workorder

A single-file fix, a typo, a question: just do it. The pipeline costs three
agent spawns minimum. Use it when the change spans files, touches a submodule,
or would ship a bug that is expensive to find later.

### Step 0.5 — triage the starting tier

**Do this before spawning anything.** The escalation ladder in step 2 is a
recovery mechanism, not a router: using it as the router means discovering a
hard problem by failing at it twice, which is the most expensive way to learn
something you could have read off the request.

Triage on **observable properties of the task**, never on a model's own sense of
how confident it feels. A model that cannot solve something is also poorly
calibrated about whether it can, so self-assessed confidence is the least
reliable signal in this system. These are checkable:

| The change… | Start at |
|---|---|
| **introduces or changes concurrency** — threads, async boundaries, a new `#[tauri::command]` that touches disk or network, anything that can deadlock or race | planner `fable`, implementer `opus` |
| must **establish an unknown game mechanism**, not verify a suspected one — the "which of N candidates does X" shape | planner `fable`, implementer `opus` |
| changes **how a hook attaches** — install routes, trampolines, what a hook can see | planner `opus`, implementer `opus` |
| changes a **contract three bindings must agree on** (C++ / Python / TypeScript) | planner `opus`, implementer `opus` |
| falls in the **suspend-the-game-loop class** (`AGENTS.md`) | stop — read `ForgePact/docs/menu-pause-plan.md` §0 with the user before planning at all |
| everything else | the agents' own pins (planner `opus`, implementer `sonnet`) |

Say which row you matched and why, in one line, before you spawn. A triage
nobody can see is a triage nobody can correct — and the user is the cheapest
source of "no, this one is harder than it looks" you will ever have.

### Step 1 — plan

Spawn `planner` at the tier triage chose, with the request and the repository
context. It writes `.claude/workorders/<slug>-plan.md` and returns `PLAN-READY`
— or `ADVICE-NEEDED`, if the research hit one decision it cannot settle, which
routes to "Consultation" below and does not count as a replan.

`*-plan.md` is gitignored at any depth, which is deliberate — `AGENTS.md`
§ "Documentation & Instructions Maintenance" wants the plan to stay on the
author's machine and the durable reasoning folded into `docs/` or the module's
`instructions.md` once the work lands.

Read the workorder yourself before continuing. If `## Acceptance criteria`
contains anything that is not a runnable command or a checkable file, send it
back now — an unrunnable criterion costs a full implement round to discover.
If it has a `## Needs human judgement` section, show that to the user and get an
answer before spawning the implementer.

### Step 2 — implement

Spawn `implementer` with the workorder path. Three outcomes:

- **`IMPL-DONE`** → go to step 3.
- **`ADVICE-NEEDED`** → see "Consultation" below. This is not a failure and does
  not count against any cap; it is the cheap path that exists so one hard
  decision does not cost a whole escalated phase.
- **`PLAN-DEFECT`** → append the evidence block to the workorder's `## Log`,
  increment nothing, and re-spawn `planner` with it. This is the loop working.

  **Escalate the planner's model as it fails, rather than only counting.** A
  `PLAN-DEFECT` is the pipeline telling you this problem is harder than the tier
  you assigned it:

  | Replan | Spawn `planner` with | Because |
  |---|---|---|
  | 1st | `model: opus` (its default) | most wrong plans are wrong about one fact, not about the mechanism |
  | 2nd | `model: fable` | cheaper reasoning has now demonstrably failed twice on the same problem |
  | 3rd | — stop, ask the user | a goal that survives two replans is usually not well posed |

  Spend the money where it has been earned, not where it was guessed. Planning
  is the lowest-token-volume phase in this pipeline — a plan is a few thousand
  output tokens against an implementation's hundred thousand — so one Fable
  replan costs less than the implement round it saves, and far less than the
  live game session a wrong mechanism model costs.

  Record the escalation in the `## Log` (`planner escalated to fable after 2nd
  PLAN-DEFECT`). If Fable's plan also fails, that is a strong signal the problem
  is under-specified rather than difficult, and it is worth saying so to the
  user explicitly when you stop.

### Consultation — one hard decision, not a whole escalated phase

A phase agent can return **`ADVICE-NEEDED`** instead of finishing: it has hit a
single decision above its tier and wants a stronger model to settle it. Both
`planner` and `implementer` may do this. `verifier` may not, deliberately — it is
scoped to what it can execute, and giving it a route to a judgement call reopens
exactly the door its design closes. An uncertain verifier reports `UNATTEMPTED`.

Note the mechanism, because it constrains the shape: an agent cannot spawn
another agent. The phase returns its question to you, you spawn `consultant`
with it, and you re-spawn the phase with the answer appended to the workorder's
`## Log`. The phase keeps its own context and its progress — that is the whole
point, and it is what makes this cheaper than escalating the phase, which throws
away everything done so far.

**Refuse a malformed question.** The request must carry `QUESTION`, `WHAT I
WOULD DO WITHOUT HELP`, `WHY I AM UNSURE` and `CONTEXT`. If the second field is
empty, send it back rather than forwarding it. An asker that has not formed a
view has not thought about the problem, and answering that is how a consultation
quietly becomes delegation — the weaker model stops deciding anything and the
pipeline pays two tiers for one phase.

**Spawn `consultant` at `opus`** by default. For a question in the `fable` rows
of the triage table, pass `model: fable` — one focused question with a short
answer is the cheapest place in this entire pipeline to buy the strongest model,
far cheaper than running a whole phase there.

**Cap: 2 consultations per round.** A third is a signal, not a quota to spend:
triage was wrong, so escalate the *phase* — re-spawn it one tier up with
everything learned so far in the `## Log` — rather than continuing to buy
answers one at a time. Record that you did, and why.

If `consultant` returns `ESCALATE`, do that immediately without waiting for the
cap.

Append every answer to the `## Log` verbatim. The next round must not re-ask a
question that has already been paid for, and a later reader needs to know which
decisions were made at which tier.

### Step 3 — verify, in parallel

Spawn `verifier` **and** every applicable domain reviewer in a single message so
they run concurrently. Wall-clock is one agent; only tokens add up.

Give each the workorder path and tell it to read the change from
`git diff` — never paste the implementer's transcript.

Which reviewers apply:

| Run when the change touches | Reviewer |
|---|---|
| always | `verifier` (mechanical), `docs-sync-reviewer` |
| `docs/`, research notes, comments written while reading a decompiler | `decompile-output-guard` |
| `hs-game-sdk/`, `tests/cpp/`, any relic/item/stat scanner, any live `CInstance` or decoded save tree | `sdk-contract-reviewer` |
| `hub/src-tauri/src/`, the updater, anything the hub's interface reads | `tauri-command-reviewer` |
| `ForgePact/plugin`, a hook install, a call through a resolved pointer, a research finding in `docs/` | `instrument-blindness-reviewer` |

When in doubt, run it. A reviewer that finds nothing costs one spawn; a bug
class that ships costs a live session.

### Step 4 — route the verdicts

Merge everything into one decision:

- **`verifier` PASS and no reviewer finding** → go to step 5.
- **Any `IMPL-DEFECT`, or any reviewer finding** → append all of it to the
  workorder's `## Log`, bump `round:`, and re-spawn `implementer`. Send the
  **evidence**, not a summary: the failing command and its real output, the
  reviewer's `path:line`. A defect report the implementer has to re-derive
  wastes the round you spent finding it.
  Cap: **3 implement→verify rounds.** On a fourth, stop and bring it to the
  user with everything tried so far. Ping-ponging past three means the pipeline
  has lost the thread and more rounds will not find it.
- **Any `PLAN-DEFECT`** → back to step 1, under the replan cap.
- **Anything under `UNATTEMPTED` that needs a human** — a live game session, a
  rebuild, eyes on a window — → stop and ask. Never record an unchecked
  criterion as passed.

### Step 5 — report

Set `status: PASS` in the workorder and tell the user:

- what changed, and the acceptance criteria with their **real** output;
- every reviewer that ran and what it concluded, including the clean ones;
- anything left under `NOT DONE` or `Needs human judgement`;
- how many rounds it took, and what each round caught. That last line is how
  the pipeline earns its keep or shows it is not.

Then fold what is still true out of the workorder and into the document that
describes the result — `docs/hub/design.md`, a `docs/adr/` entry, or the
submodule's `instructions.md`. Leave the plan file where it is; it is ignored.

## Two rules that make this work rather than just look like it works

**Evidence travels, opinions do not.** Every verdict that moves work backwards
carries the command and its output, or a `path:line`. This is the same rule
`AGENTS.md` applies to research: a negative without a positive control is not a
result, and "it failed" without the failure is not a defect report.

**Never let a phase paper over the previous one.** An implementer that works
around a wrong plan, or a verifier that substitutes its judgement for an
unrunnable criterion, produces a change that looks finished and is not. Routing
backwards is cheap and correct. That is the whole design.

## Model tiers

Set in each agent's frontmatter: `planner` opus, `implementer` sonnet,
`verifier` haiku, reviewers sonnet except `instrument-blindness-reviewer` at
opus. Override for one run by passing `model` on the Agent call.

**Tier aliases, not pinned version IDs.** `opus` means the current generation of
that tier, which is the contract wanted here: the tier is the design decision,
the version is not. Pinning `claude-opus-5` across eight agent files would buy
reproducibility the pipeline does not need — the acceptance criteria are
mechanical, so a model change that breaks something fails a *test*, not a review
— and cost a stale-ID sweep every generation, ending in a retired model that
breaks the agent outright. This is not the `*Rva*` case from `AGENTS.md`: an
alias is a documented moving pointer, not a constant whose meaning silently
moved underneath it.

**When to reach for `fable` yourself,** beyond the automatic escalation above:

- The plan must establish an **unknown** game mechanism, not verify a suspected
  one — the "which of 34 candidates does X" shape, where a wrong mechanism model
  has historically cost whole sessions rather than one round.
- The change falls in the class `AGENTS.md` § "Don't Suspend the Game's Own
  Runtime" warns about, where the failure mode inverts and the blast radius is
  the player's session.

Do **not** reach for it on a routine change, and do not put it on the
implementer or a reviewer. Those run at high token volume on every change, where
2× is real money for no measured gain; the planner is the one phase cheap enough
that the upgrade is nearly free.
