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

## Modes

| Invocation | Runs | Stops after |
|---|---|---|
| `/workorder <task>` | the whole pipeline | `PASS`, or a cap |
| `/workorder plan <task>` | step 0 → step 1 only | the plan, reviewed and handed back |
| `/workorder resume <slug>` | steps 2 → 5 | `PASS`, or a cap |

**`plan` is not a degraded run — it is a checkpoint.** It exists so a plan can
be read, argued with and revised before any code is written, and picked up in a
*different session* later. Stop cleanly when asked for it: write the workorder,
summarise it, print the exact `resume` command, and spawn nothing else. Do not
start implementing because the plan looks correct — the user asked for a plan
because they intend to decide that themselves.

**`resume` is the test of whether the plan was real.** A new session has none of
the planning conversation — not the alternatives weighed, not something said in
passing, not why a path was abandoned. The workorder files are the only
channel, so on resume, check they can carry the work alone: a step that depends
on context not written down is a `PLAN-DEFECT` before the implementer is ever
spawned, far cheaper to catch here than three steps in.

That constraint is a feature. A plan that cannot survive a fresh session was
never a plan; it was a conversation someone was still holding in their head.

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

**Do this before spawning anything.** The escalation ladder in step 2 recovers
from a wrong tier, not a router — using it as the router discovers a hard
problem by failing at it twice, the most expensive way to learn something
readable off the request.

Triage on **observable properties of the task**, never a model's own
confidence — a model that cannot solve something is also poorly calibrated
about whether it can. These are checkable:

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

**Also check the plan's size, and say so before spawning.** The caps are per
*workorder*, not per finding, so an oversized plan puts unrelated work on one
shared three-round budget — and one stubborn finding then stops every finding
that was already green.

Count the `## Acceptance criteria` checkboxes. Warn the user, in one line,
before spawning the implementer if any of these hold:

- more than **30 acceptance criteria**;
- more than **3 independent findings** — independent meaning a later one does
  not depend on an earlier one being right;
- more than **one submodule**, unless the change is a single contract they must
  agree on.

The panel-and-launcher pass — 116 criteria, 9 findings, 2 submodules, 1,524
lines — hit this cap with seven items still open, closed by hand outside the
phase separation: too many findings sharing one budget, none individually
hard.

Recommend splitting into one workorder per independent finding, or per
submodule. Say it and let the user decide — a plan this size is usually
deliberate, and the warning is worth more than a refusal.

### Step 1 — plan

If the request touches a submodule not initialized in this checkout, run
`py -3 .claude/skills/workorder/ensure_submodule.py <module>` first — it gives
this checkout its own submodule gitdir, so two linked worktrees never share
one, and the planner's own "Load the module's guide" step needs files inside
it either way. From here, all work on that module — reading, editing,
building, committing, the work branch — stays in this checkout's copy; if the
script names unpushed work sitting in the main checkout, bring it across with
the `git -C <module> fetch` command it prints. Removing this worktree later
needs `git worktree remove --force` once it carries a submodule.

Spawn `planner` at the tier triage chose, with the request and the repository
context. It writes `.claude/workorders/<slug>-plan.md` (frontmatter, `## State`,
`## Goal`, `## Out of scope`, `## Acceptance criteria`, `## Steps`) and
`<slug>-context.md` (`## Context the implementer needs` by stable `###`
subsection, `## Needs human judgement`, `## Log`), and returns `PLAN-READY` —
or `ADVICE-NEEDED` if the research hit one decision it cannot settle (see
"Consultation" below; not a replan). Nine existing single-file plans stay
valid, same sections in one `-plan.md` — locate a section with
`grep -n '^## \|^### '`, never assume the split.

Both files are gitignored at any depth (legacy plans too) — `AGENTS.md`
§ "Documentation & Instructions Maintenance" wants the plan to stay on the
author's machine and the durable reasoning folded into `docs/` or the module's
`instructions.md` once the work lands.

Read the plan file, `## Needs human judgement` and `## Log` yourself — grep
`## Context the implementer needs` for what you need rather than reading it
front-to-back. If `## Acceptance criteria` contains anything that is not a
runnable command or a checkable file, send it back now — an unrunnable
criterion costs a full implement round to discover. If `## Needs human
judgement` is non-empty, show it to the user and get an answer before spawning
the implementer.

**In `plan` mode, stop here.** Report:

- the goal and what is explicitly out of scope;
- the acceptance criteria, so the user can object to a check before it costs an
  implement round;
- anything under `## Needs human judgement`;
- which triage row matched and therefore what tier implementation will start at;
- the exact command to continue, including in a fresh session:
  `/workorder resume <slug>`.

Then stop. Spawn nothing further, and do not begin implementing.

### Step 2 — implement

**Entering here from `resume`?** Do three things first, because this session
did not write the plan and knows nothing it does not say:

1. **Repeat the submodule check from Step 1**, against the plan's `module:`
   field — a week-old plan may name a module this fresh checkout hasn't
   initialized.
2. **Read the plan file in full, `## Needs human judgement` and all of `## Log`**
   — the one point the driver reads the whole Log, to re-count replans and
   consultations. Grep `## Context` for what step 2 needs rather than reading
   it whole. Re-run the step 0.5 triage — it's a property of the task, not the
   session, so it reaches the same row, but the repository may have moved
   under a week-old plan.
3. **Check it is self-sufficient.** Every step must be actionable from the file
   alone. A step that assumes a decision made only in conversation, names a file
   that no longer exists, or says "as discussed" is a `PLAN-DEFECT` now — cheaper
   to route back before an implementer has spent a round discovering it.

Snapshot before spawning: `py -3 .claude/skills/workorder/round_delta.py
snapshot <slug> <round>`, recorded in `## State` › `round base:` — step 3
diffs against it, and every later round repeats this before re-entering.

Spawn `implementer` with the plan and context paths. Three outcomes:

- **`IMPL-DONE`** → go to step 3.
- **`ADVICE-NEEDED`** → see "Consultation" below — not a failure, doesn't count
  against any cap; the cheap path so one hard decision doesn't cost a whole
  escalated phase.
- **`PLAN-DEFECT`** → append the evidence to the context file's `## Log` under
  the round's `### Round <n>` heading, increment nothing, and spawn `planner`
  fresh (a replan is always fresh — see "Re-entering a phase" below). This is
  the loop working.

  **Escalate the planner's model as it fails, rather than only counting.** A
  `PLAN-DEFECT` is the pipeline telling you this problem is harder than the tier
  you assigned it:

  | Replan | Spawn `planner` with | Because |
  |---|---|---|
  | 1st | `model: opus` (its default) | most wrong plans are wrong about one fact, not about the mechanism |
  | 2nd | `model: fable` | cheaper reasoning has now demonstrably failed twice on the same problem |
  | 3rd | — stop, ask the user | a goal that survives two replans is usually not well posed |

  Spend money where it's earned, not guessed: planning is the lowest-
  token-volume phase (a few thousand output tokens against an implementation's
  hundred thousand), so one Fable replan costs less than the implement round
  it saves, and far less than a wrong mechanism model's live game session.

  Record the escalation under the round's heading in the context file's
  `## Log` (`planner escalated to fable after 2nd PLAN-DEFECT`). A Fable
  failure signals the problem is under-specified, not difficult — say so to
  the user when you stop.

### Re-entering a phase: resume, or fresh spawn

Record each phase agent's `agentId` in `## State` › `agents:`. Same-phase,
same-tier re-entry — an answered `ADVICE-NEEDED`, an `IMPL-DEFECT`, or the
implementer once its own `PLAN-DEFECT` is fixed — is a `SendMessage` to that
agent id (ToolSearch `select:SendMessage` if deferred), naming the `## Log`
heading and pasting nothing else: the send is what keeps the context, not a
claim the driver makes about it.

Spawn fresh when: the tier changes; it's a planner replan (always fresh — the
point is a fresh look at what the earlier plan assumed, and a resumed planner
is that assumption's own context); the agent id doesn't resolve (`/workorder
resume` in a new session) or the send fails; or it's already been resumed
twice. A fresh implementer or planner gets a `PROGRESS SO FAR` block (steps
done, files touched, what's half-finished) instead of history. `verifier` and
every reviewer are **always fresh** — independence is their value.

### Consultation — one hard decision, not a whole escalated phase

A phase agent can return **`ADVICE-NEEDED`** instead of finishing: it has hit a
single decision above its tier and wants a stronger model to settle it. Both
`planner` and `implementer` may do this. `verifier` may not, deliberately — it is
scoped to what it can execute, and giving it a route to a judgement call reopens
exactly the door its design closes. An uncertain verifier reports `UNATTEMPTED`.

Note the mechanism, because it constrains the shape: an agent cannot spawn
another agent. The phase returns its question to you, you spawn `consultant`
with it, and append the answer to `## Log` under `### Decisions` — verbatim, so
the next round does not re-ask a question already paid for and a later reader
knows which decisions were made at which tier. Then re-enter the phase per
"Re-entering a phase" above: same tier, so this is a resume, which is what
makes a consultation cheaper than escalating the phase and throwing away
everything done so far.

**Refuse a malformed question.** The request must carry `QUESTION`, `WHAT I
WOULD DO WITHOUT HELP`, `WHY I AM UNSURE` and `CONTEXT`. An empty second field
goes back unforwarded — an asker with no view has not thought about the
problem, and answering it turns consultation into delegation: the weaker model
stops deciding and the pipeline pays two tiers for one phase.

**Spawn `consultant` at `opus`** by default. For a question in the `fable` rows
of the triage table, pass `model: fable` — one focused question with a short
answer is the cheapest place in this pipeline to buy the strongest model, far
cheaper than running a whole phase there.

**Cap: 2 consultations per round.** A third is a signal, not a quota to spend:
triage was wrong, so escalate the *phase* — re-spawn it one tier up with
everything learned so far in the `## Log` — rather than continuing to buy
answers one at a time. Record that you did, and why.

If `consultant` returns `ESCALATE`, do that immediately without waiting for the
cap.

### Step 3 — verify, in parallel

Run `py -3 .claude/skills/workorder/round_delta.py delta <slug> <round>`
against step 2's snapshot to see what this round touched — it records each
repo's HEAD too, so work the implementer commits mid-round is in the delta,
not only what it leaves dirty. Exit 3 means the snapshot is missing,
unreadable, or a recorded head can no longer be trusted — treat everything as
changed.

- **Round 0:** spawn every applicable reviewer (table's first column) plus
  `verifier` — when in doubt, run it, cheap even when clean.
- **Round ≥ 1:** spawn `verifier` always, plus every applicable reviewer
  `BLOCKING` last round or matching the delta (table's second column). Record
  a skip as `<name>=clean@round<n>, not re-run` in `## State`, reported the
  same way in step 5. Run everything if `delta` exited 3.

**Reviewers get no workorder path** — paste `## Goal`, `## Out of scope`, the
diff commands below, and this round's paths (whole change on round 0, delta
after). `instrument-blindness-reviewer` also gets the context file's path and
the `###` heading(s) recording the research finding. Never paste the
implementer's transcript.

**Diff from the round base, never from `HEAD`** — implementers commit during
the round, so `git diff HEAD` is empty afterwards. Take each repo's base sha
from `round_delta.py heads <slug> <round>` (or `## State` › `round base:`):

```bash
git status --porcelain -uall     # untracked, named individually
git log --oneline <base>..HEAD   # this round's commits
git diff <base>                  # working tree vs base: committed and uncommitted
git -C <submodule> status --porcelain -uall
git -C <submodule> diff <its base>   # the hub's diff shows only the pointer
```

| Reviewer | Applicable when the change touches | Re-run on round ≥ 1 when the delta contains |
|---|---|---|
| `docs-sync-reviewer` | always | anything other than test files |
| `decompile-output-guard` | `docs/`, research notes, decompiler-read comments | any `.md .cpp .hpp .py .rs .ts .js` file (tests included) — never skipped for any other reason; a legal finding is always blocking |
| `sdk-contract-reviewer` | `hs-game-sdk/`, `tests/cpp/`, any relic/item/stat scanner, any live `CInstance` or decoded save tree | its own table's paths |
| `tauri-command-reviewer` | `hub/src-tauri/src/`, the updater, anything the hub's interface reads | its own table's paths |
| `instrument-blindness-reviewer` | `ForgePact/plugin`, a hook install, a call through a resolved pointer, a research finding in `docs/` | `ForgePact/plugin/**`, hook/installer code under `hs-game-sdk/**`, any `*-research.md`, any `docs/submodules/*/instructions.md`, any other doc recording a measured result, or delta text matching `Rva\|GetModuleHandle\|MmCreateHook\|HookOneScript\|InstallScriptHook` |

A re-run reviewer reads the delta paths; round 0 reads the whole change.
`decompile-output-guard` on round ≥ 1 reads every line added since it last
passed, plus the whole contents of any file added since.

**Require the severity label.** Every finding is `BLOCKING` or `NON-BLOCKING`,
leading with "no blocking findings" when true — restate this in the dispatch so
an unlabelled report is obviously incomplete, not something to classify
yourself.

### Step 4 — route the verdicts

Merge everything into one decision:

**A round is for defects, not for improvements.** Every reviewer labels each
finding `BLOCKING` or `NON-BLOCKING`; only blocking ones spend a round. The
panel-and-launcher pass hit the cap on a round whose instrument reviewer opened
*"nothing here blocks shipping"* and then listed five follow-ups and three nits
— costing the workorder its last round and shutting down eight findings already
green. A cap that counts polish as failure turns "found something worth doing"
into "the pipeline stops".

The line, when a reviewer's label looks wrong to you:

| Blocking | Non-blocking |
|---|---|
| a failed acceptance criterion | a test that could be sharper |
| ships inert or wrong — the `HOOK INSTALLED`-and-does-nothing class | a follow-up idea for later |
| a legal finding from `decompile-output-guard` — **always** | a naming or wording nit |
| an overclaim in **release notes** — `AGENTS.md` is explicit that one wrong "Fixed" erodes every note after it | an overclaim in a research doc or a test comment |
| | an internal doc that is merely incomplete |
| | a player-visible ForgePact change with no `release-notes-vX.Y.Z.md` — `forgepact-tag.yml` falls back to generated notes under a rewrite banner; flag it, don't spend a round |

- **`verifier` PASS and no blocking finding** → go to step 5, carrying every
  non-blocking finding into the report.
- **`verifier` PASS-PENDING-HUMAN and no blocking finding** → everything
  runnable passed and something needs a person: a live game session, a
  twelve-minute rebuild, eyes on a window. Go to step 5 and report it as such.
  **Do not spend a round on it** — the implementer cannot fix a criterion that
  is not broken — and do not quietly upgrade it to `PASS`. Set `status: PASS
  (pending <what)` in the workorder so the gap survives the session.
- **Any `IMPL-DEFECT`, or any BLOCKING reviewer finding** → append it to the
  context file's `## Log` under a new `### Round <n>` heading, bump `round:` in
  `## State`, snapshot the new round (step 2), and re-enter the implementer per
  "Re-entering a phase" — normally a resume, same tier, pointed at that
  heading. Send the **evidence** in the Log entry, not the message: the failing
  command and its real output, the reviewer's `path:line`. A defect report the
  implementer has to re-derive wastes the round you spent finding it.

  Carry the round's non-blocking findings along **as context, not as work** —
  the implementer may fix one cheaply while it is already in that file, and
  must not spend the round on them.

  Cap: **3 implement→verify rounds.** On a fourth, stop and bring it to the
  user with everything tried so far. Ping-ponging past three means the pipeline
  has lost the thread and more rounds will not find it.

  **At the cap, split — never close it by hand.** Three failed rounds mean the
  pipeline lost the thread, regardless of plan size or how close it looks to
  done. Finishing it yourself makes the driver the implementer at the wrong
  tier (see "Driver discipline" below) — the failure this cap exists to
  prevent, not a shortcut past it. Open a *new* workorder with only the
  still-open findings and its own fresh three rounds; say which findings are
  already closed so the split does not re-litigate passed work.
- **Any `PLAN-DEFECT`** → back to step 1, under the replan cap.
- **Anything under `UNATTEMPTED` that needs a human** — a live game session, a
  rebuild, eyes on a window — → stop and ask. Never record an unchecked
  criterion as passed.

### Step 5 — report

Set `status: PASS` in the workorder and tell the user:

- what changed, and the acceptance criteria with their **real** output;
- every reviewer that ran and what it concluded, including the clean ones, and
  every reviewer skipped this round as `clean@round<n>, not re-run`;
- anything left under `NOT DONE` or `Needs human judgement`;
- how many rounds it took, and what each round caught. That last line is how
  the pipeline earns its keep or shows it is not.

Then fold what is still true out of the workorder and into the document that
describes the result — `docs/hub/design.md`, a `docs/adr/` entry, or the
submodule's `instructions.md`. Leave both workorder files where they are; they
are ignored.

## Driver discipline

**The driver never implements.** Its tool use is limited to: reading the
workorder, `round_delta.py`, `git status`/`git diff` for a dispatch, `Edit` on
`## State`/`## Log`, `Agent`, `SendMessage`, `AskUserQuestion`. Running builds
or tests, or editing source, makes it the implementer at the wrong tier and the
largest context in the pipeline — stop and dispatch instead. Measured: the
driver that closed a capped workorder by hand made 236 Bash calls and 47 edits
at a median 425K-token context, reading 157M cached tokens for that resume.

**Workflow mode is the default way steps 2–4 run.** `/workorder <task>` and
`/workorder resume <slug>` call it — the user's own invocation is the opt-in
the Workflow tool requires, so don't ask again. It carried
`prospect-idcheck-pin-hardening` through three rounds to `PASS` on
2026-09-17.

```
Workflow({ scriptPath: ".claude/workflows/workorder-rounds.js",
           args: { slug, planPath, contextPath, goalExcerpt, implementerModel, round,
                   reviewers: { '<name>': 'never' | 'clean' | 'blocking', ... },
                   submodules: ['<dir>', ...], researchHeadings, baseHeads, repoRoot } })
```

`reviewers`/`submodules` are as in Step 3. `researchHeadings` names the
context file's `###` heading(s) for `instrument-blindness-reviewer`.
`baseHeads` is `{ '.': sha, '<submodule>': sha }`, copied from `## State` ›
`round base:`, so a `never` reviewer reads the whole change from the
workorder's own start rather than a later round's snapshot. `repoRoot` is
only an escape hatch for a workorder deliberately run against another
checkout; the default is absent now that Step 1's `ensure_submodule.py` gives
this checkout its own submodule copy.

It loops implement → verify+reviewers → route as code (same 3-round cap,
scribe for Log/State, reviewer table), returning `PASS`, `PASS-PENDING-HUMAN`,
`PLAN-DEFECT`, `ADVICE-NEEDED`, `AGENT-FAILED` or `CAP`. One launch may cover
several rounds; `PLAN-DEFECT` means relaunching after the replan. Replans,
consultations, human questions and the step 5 report stay with the driver;
every re-entry inside is a fresh spawn (no resume) — measured no worse than a
resumed implementer.

**Fall back to driver turns** (steps 2–4 by hand, above) when the Workflow
tool is unavailable, the launch fails, or the user says "driver mode" or "no
workflow".

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
that tier — the design decision, not the version. Pinning `claude-opus-5`
across eight files buys reproducibility this pipeline does not need (a broken
model fails a *test*, not a review) and costs a stale-ID sweep every
generation. Not the `*Rva*` case from `AGENTS.md`: an alias is a documented
moving pointer, not a constant whose meaning silently moved underneath it.

**When to reach for `fable` yourself,** beyond the automatic escalation above:

- The plan must establish an **unknown** game mechanism, not verify a suspected
  one — the "which of 34 candidates does X" shape, where a wrong mechanism
  model has cost whole sessions rather than one round.
- The change falls in the class `AGENTS.md` § "Don't Suspend the Game's Own
  Runtime" warns about — the failure mode inverts, and the blast radius is the
  player's session.

Do **not** reach for it on a routine change, or put it on the implementer or a
reviewer — those run at high token volume where 2× is real money for no
measured gain; the planner is the one phase cheap enough for the upgrade to be
nearly free.
