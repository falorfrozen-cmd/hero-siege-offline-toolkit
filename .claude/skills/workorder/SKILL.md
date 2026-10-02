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
be read, argued with and revised before any code is written, and picked up in
a *different session* later. Stop cleanly: write the workorder, summarise it,
print the exact `resume` command, and spawn nothing else. Do not start
implementing because the plan looks correct — the user asked for a plan
because they intend to decide that themselves.

**`resume` is the test of whether the plan was real.** A new session has none
of the planning conversation — not the alternatives weighed, not something
said in passing, not why a path was abandoned. The workorder files are the
only channel, so on resume check they can carry the work alone: a step that
depends on context not written down is a `PLAN-DEFECT` before the implementer
is ever spawned, cheaper to catch here than three steps in.

That constraint is a feature: a plan that cannot survive a fresh session was
never a plan, just a conversation someone was still holding in their head.

## The loop

```
planner(opus) → implementer(opus) → verifier+reviewers(haiku,sonnet/opus) → PASS ─→ report
  ▲ PLAN-DEFECT ◄───────┘ ◄──────────────────── IMPL-DEFECT / BLOCKING
                                    PASS-PENDING-HUMAN → live-operator(sonnet) → report
```

### Step 0 — decide whether this is worth a workorder

A single-file fix, a typo, a question: just do it. The pipeline costs three
agent spawns minimum. Use it when the change spans files, touches a submodule,
or would ship a bug that is expensive to find later.

### Step 0.25 — the work must be in this checkout

Before triage, in every mode: does the request — or, on `resume`, the plan's
`repoRoot:` line — put the work in a checkout other than this session's own
(`git rev-parse --show-toplevel`)? "Main checkout", a path outside this one,
a branch that exists only over there. If so, **stop and say so; spawn
nothing.** A session opened in a worktree has every `Edit` and `Write` outside
it refused by the harness, so no implementer can carry such a plan out as
written. The one that tried (`forgepact-closure-names-current-game`,
2026-09-18) patched files through shell scripts instead: 57 of 142 implementer
turns, a 31M-token round against a 15M budget, and a guard on the user's main
working copy bypassed along the way.

Offer the two ways forward and let the user pick:

- **open the session in that checkout** and run `/workorder` there — right
  when the state that matters is uncommitted (a dirty guide, a stash, an
  unstaged gitlink);
- **bring the work here** — `git -C <module> fetch "<main checkout>/<module>"
  <branch>` carries an unpushed submodule branch across (Step 1's
  `ensure_submodule.py` prints it, filled in, the first time it initializes
  the module here); a hub branch is `git merge --ff-only <branch>` away, the
  object store being shared.

`tools/workorder_audit.py` R15 fails any run in which an agent met that
refusal and kept going.

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
| falls in the **suspend-the-game-loop class** (`AGENTS.md`) | stop — read `ForgePact/docs/menu-pause-plan.md` §0 with the user before planning at all |
| touches **only docs, tests or config** — no product source, no hook, no binding | planner `opus`, implementer `sonnet` |
| everything else — including hook attachment and three-binding contracts, which had their own `opus`/`opus` rows when the default implementer was `sonnet` | the agents' own pins (planner `opus`, implementer `opus`) |

The implementer's default is `opus` since 2026-09-22 (see "Model tiers"):
Opus 5.5 reads cache at Sonnet 5's price, and 99% of an implementer's tokens
are cache reads, so the tier costs about the same per token while the Sonnet
tail (p90 46.8M tokens, max 78.9M) was what hit the round caps. `sonnet` is
kept for the one row where its median run (8.2M tokens, $2.62) is all the
work there is.

Say which row you matched and why, in one line, before you spawn — a triage
nobody can see is a triage nobody can correct, and the user is the cheapest
"no, this one is harder than it looks" you will ever get.

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

The panel-and-launcher pass — 116 criteria, 9 findings, 2 submodules — hit
this cap with seven items still open: too many findings sharing one budget,
none individually hard.

Recommend splitting into one workorder per independent finding, or per
submodule — say it and let the user decide; a plan this size is usually
deliberate, and the warning is worth more than a refusal.

A plan of items (Step 2, "Items") does not share one cap: each item has its
own three attempts, and an item that stops parks alone. The count warnings
below do not apply to it.

The warning is about findings sharing one round cap, not about size as such.
Where the work is a sequence of small dependent changes, the opposite advice
holds: one larger workorder whose independent parts are lanes with disjoint
`files:` and one join verify costs one full verify, where a chain of small
workorders costs one each (planner.md "Fewer, larger workorders").

### Step 1 — plan

If the request touches a submodule not initialized in this checkout, run
`py -3 .claude/skills/workorder/ensure_submodule.py <module>` first — it gives
this checkout its own submodule gitdir, so worktrees never share one, and the
planner's own "Load the module's guide" step needs files inside it either
way. From here, all work on that module — reading, editing,
building, committing, the work branch — stays in this checkout's copy; if the
script names unpushed work sitting in the main checkout, bring it across with
the `git -C <module> fetch` command it prints. It also copies each module's
local-only build prerequisites (`.claude/skills/workorder/local_prereqs.json`,
e.g. ForgePact's `plugin_build/include/`) from the main checkout when missing
here, printing `copied prerequisite: <path>`. Removing this worktree later
needs `git worktree remove --force` once it carries a submodule.

**Bring `origin/main` in first when it reaches the plan's files.** Before
every planner spawn (first plan, replan or amendment), `git fetch origin` in
the hub and in each touched submodule and read `git diff --name-only
HEAD...origin/main`. If it names a file the plan will edit, or the workorder
tooling this pipeline runs on (`.claude/`, `tools/`), merge `origin/main`
into the feature branch now: a merge, never a rebase, between rounds, never
while an implementer may be committing. Otherwise do not merge for this plan;
merge once before the pull requests open. Say which you did and what came in.
The owner narrowed this on 2026-09-26 from "merge before every plan", which
spent a merge and a re-read on commits that touched nothing the plan used.

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
criterion costs a full implement round to discover. `py -3
tools/plan_lint.py <plan>` checks that statically, running no criterion:
prose, a heading slice not anchored on `\n`, a grep over a live capture
instead of `tools/live_checks.py`, `python` for `py -3`, a bare commit hash
where a per-workorder tag or a merge-base belongs, a `.index` of "the next
heading" that raises when the section is last (`eof-slice`), a range walk
without `--first-parent` in a plan that merges main (`merge-walk`), and a
plan still `status: DRAFT` (`plan-draft`). A finding goes back
to the planner with the tool's output before any implementer is spawned.

**Plan a workorder when its inputs exist.** A plan that depends on another
workorder's result is written `status: DRAFT` with `depends on: <slug>, ...`
(planner.md, "Spend each check once"), and `plan_lint` refuses it until it
is re-planned against the finished result and set `READY`. The redesign's
restyle and ship plans were rewritten nine times between them before either
ran a round, each time because an earlier workorder had since changed what
they were written against. If `## Needs human
judgement` is non-empty, show it to the user and get an answer before spawning
the implementer.

Then run `py -3 tools/plan_lint.py <plan> --lanes-json` and keep its last
line, `{"lanes": [...], "join": true|false}`. A plan whose `## Steps`
declares `### Lane: <name>` groups (each with a `files:` line) and a
`### Join` gets its steps implemented by one implementer per lane at once,
then the join (Step 2); a plan without them prints `{"lanes": [], "join":
false}` and runs exactly as it always has. The JSON is only printed when
the lint is clean — overlapping file sets (`lane-overlap`), a lane without
files, lanes without a join, a duplicate or bad name all exit 1 without it —
so lanes a lint rejected can never be launched. Paste its `lanes` and `join`
into the workflow's args unchanged (see "Driver discipline").

**A plan of items streams instead** (Step 2, "Items"). Run `py -3
tools/plan_lint.py <plan> --items-json` and keep its last line, `{"items":
[...], "complete": true|false}`; like the lane table it is printed only when
the lint is clean (`item-overlap` and the other item rules exit 1 without
it). Items suit a workorder of several changes that can each be finished and
checked alone. When the request already has that shape, ask the planner for
a streamed plan: it writes `planning: streaming`, then each item as it
settles. Spawn it in the background, poll `plan_lint.py <plan> --items-json`
(with `--wait 240`, re-issued) until the first item appears and the lint is
clean, and launch the workflow with `streaming: true` then, while the planner
keeps writing. Read `## Needs human judgement` first as always; a question
that concerns one item belongs on that item's `owner:` line, where it parks
only that item. `plan` mode never streams: there the plan is the product.

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

**Entering here from `resume`?** Do four things first, because this session
did not write the plan and knows nothing it does not say:

1. **Repeat the submodule check from Step 1**, against the plan's `module:`
   field — a week-old plan may name a module this fresh checkout hasn't
   initialized.
2. **Check the plan is not already finished.** A `status:` of `PASS`,
   `DONE`, `CAP`, `SPLIT` or `SUPERSEDED` stops here — say so, spawn nothing.
   A `DRAFT` goes back to Step 1 instead: check its `depends on:` workorders
   passed, then spawn the planner to re-plan it against what they produced.
   A `READY` plan that arrived by copy (its header says "they travel by
   copy") may be a stale handover: ask the user whether it already ran
   before resuming it. Measured 2026-09-22: the main checkout held two
   `READY` plans that had both run to completion on 2026-09-19 in worktrees
   since removed, and every new worktree was created with a copy of both.
3. **Read the plan file in full, `## Needs human judgement` and all of `## Log`**
   — the one point the driver reads the whole Log, to re-count replans and
   consultations. Grep `## Context` for what step 2 needs rather than reading
   it whole. Re-run the step 0.25 checkout check against the plan's
   `repoRoot:` and preconditions, then the step 0.5 triage — a task property,
   not a session one, though the repo may have moved under a week-old plan.
4. **Check it is self-sufficient.** Every step must be actionable from the file
   alone. A step that assumes a decision made only in conversation, names a file
   that no longer exists, or says "as discussed" is a `PLAN-DEFECT` now — cheaper
   to route back before an implementer has spent a round discovering it.

Snapshot before spawning: `py -3 .claude/skills/workorder/round_delta.py
snapshot <slug> <round>`, recorded in `## State` › `round base:` — step 3
diffs against it, and every later round repeats this before re-entering.

**A laned plan** (Step 1's `--lanes-json` printed lanes) runs its lanes only
on the first implementation of the plan's steps: round 0, or the relaunch
after a replan. Pass `lanes` and `join` to the workflow then, and never when
relaunching after an `IMPL-DEFECT` (a `continue` from `STATE-LOST` or
`SCRIBE-FAILED`, or a fresh `resume` past round 0): a defect round is a fix
on a small delta, and no failed criterion or reviewer finding says which
lane it belongs to, so it runs one implementer that owns every file set.
Each lane implementer works only inside its `files:`, runs no git command
that writes and no full build or suite, and checks `py -3
.claude/skills/workorder/round_delta.py stopped <slug> <round>` before each
step; a lane about to return `PLAN-DEFECT` or `ADVICE-NEEDED` first writes
the marker with `round_delta.py stop`, and the others return `STOPPED` with
their progress. The join runs only when every lane returned `IMPL-DONE`: it
commits each lane's file set as its own commit, then does the `### Join`
steps. A lane that is not done skips the join and hands the round back with
every lane's verdict and progress — `PLAN-DEFECT` if any lane returned it,
else `ADVICE-NEEDED` — and what the lanes finished stays uncommitted in the
tree for the relaunch. Lanes run in workflow mode only; in driver mode a
laned plan gets one implementer that owns every file set, as a defect round
does.

**Items: a plan that streams** (Step 1's `--items-json` printed items). Its
steps 2-4 run as one workflow launch with no rounds inside it
(`workorder-rounds.js` 3b; workflow mode only):

- Each item's implementer starts the moment no running item holds its files,
  up to `maxParallel` at once; items that share a file run one after another
  in plan order. It commits only its own files through
  `tools/item_commit.py`, under the checkout's commit lock. The default cap
  is `DEFAULT_MAX_PARALLEL` in `workorder-rounds.js`, 4, and a `maxParallel`
  that is not a whole number from 1 to 16 is refused with `BAD-ARGS` before
  anything is spawned. Pass more only when `tools/workorder_speed.py` shows
  `queued_behind_cap > 0` for your plans: in the first real plan of items no
  start ever waited on the cap (docs/agents/workorder-calibration.md,
  2026-09-27).
- An unanswered `owner:` item that the plan marks `reversible: yes`, with a
  default that is not `none`, is not parked. Its implementer is told the
  question and proceeds on the default, and the result lists it under
  `defaulted` with the question, the default, its commits and how to undo it.
  Every other unanswered owner item parks.
- The moment an implementer returns, an independent `verifier` runs that
  item's `checks:` (`run_criteria.py --item <id>`). A failure sends the item
  back to a fresh implementer with the evidence, up to three attempts.
- Reviewers read the commits as they land, each pinned to the `HEAD` it
  started from, never the working tree. A reviewer re-runs when new commits
  match its trigger, and its `BLOCKING` findings become a fix item at once,
  on the files the findings name (or, with no path, run alone once the rest
  are done). A reviewer may be split by screen or dimension with
  `reviewScopes`, and its scopes run as separate reviewers.
- A build is never trusted past a later commit on what it reads. An item
  whose `build`/`exclusive` checks declare `(reads ...)` (`plan_lint.py
  --items-json` hands the workflow their globs as `build_reads`; a build
  check with no `(reads ...)` reads everything) does not start while a fix
  that may land on those globs is queued or running, or while another item
  editing them runs. That wait never starves the queue: a pass it would
  leave with nothing running and nothing started runs without it. If a commit by any other item or fix lands on them after
  the build passed, the build goes back to pending and runs again once that
  commit is in (a build still running when it lands runs again when it
  finishes); its attempt budget starts over, and the result's row carries
  `rebuilds`; a sixth re-run parks it instead (`REBUILD_CAP`), so two builds
  that commit into what the other reads cannot loop. In
  forgepact-124-pet-relics (2026-10-02) a reviewer's fix landed minutes after
  `build-dev` passed, three times, and each launch came back `PARKED` with
  `build-dev=done` and a DLL older than the fix. So give a build check its
  `(reads ...)`: without one any commit re-runs it.
- When nothing is left to run, the `## Acceptance criteria` run once, as a
  development verify (`--dev`: whole suites and `(final)` criteria wait for
  the final gate before the pull request). A failure becomes one fix that
  runs alone, and the gate runs again, three times at most.
- An item that stops parks alone. What depends on it is held, and
  everything else keeps flowing. The launch returns `PARKED` once nothing
  else can run, before the gate, with every item's status, reason and
  evidence.
- An item implementer's or a fixer's `PLAN-DEFECT` whose evidence carries a
  `CORRECTION:` other than `none` is amended inside the launch, the way
  "Amend, or replan" below does it: `amend_check.py save` through
  `amend-save:<id>:r<n>`, a fresh `planner` labelled `amendment: <slug>
  <id>:r<n>` with the correction verbatim, then `amend_check.py check`
  through `amend-check:<id>:r<n>`. Only exit 0 with `AMENDMENT` re-runs the
  item and releases what it held. One amendment runs at a time, since
  `amend_check.py` keeps one saved copy per slug, and it counts only toward
  `maxAgents`. `NOT AN AMENDMENT`, `REPLAN`, `SCOPE`, a `CORRECTION: none`,
  or a second `PLAN-DEFECT` after the item's amendment parks the item for you
  as a replan, with the reason. A reviewer's plan defect stays yours. No
  item or fix starts while an amendment is queued or running, and every
  outcome but a confirmed one first puts the plan and context back from the
  saved copy (`amend_check.py restore`, `amend-restore:<id>:r<n>`), so no
  item reads a rejected edit; if that restore fails, nothing else starts in
  the launch and the pending items come back held, naming why.

Route a `PARKED` result item by item, and relaunch once for all of them.
Pass `state` as always: its `items:` line tells the relaunch which items are
done (or `defaulted`), and they are not run again.

- **Route `unblocked` first.** A result that waits on a person (`PARKED`
  with an owner item, or `PASS-PENDING-HUMAN`) carries `unblocked`: every
  parked or held item that waits on no owner question, each `{ id, reason,
  route }` with `route` one of `amend-or-replan`, `replan`, `consult`,
  `split` or `relaunch`. Start those routes in the same message as the
  question (rule 8), so the answer lands on work already moving.
- `owner: <question>`, or an item's question for the person → one
  `AskUserQuestion` batch for every parked item. Record each answer under
  `### Decisions`, then relaunch with those ids in `answered`. A
  `defaulted` item the owner answers differently: revert its listed commits,
  record the answer, and relaunch with its id in `answered`.
- `ADVICE-NEEDED` → "Consultation" below, the answer under `### Decisions`,
  then relaunch.
- `PLAN-DEFECT` → "Amend, or replan" below, for that item only: tell the
  planner which item it is. An item that carries `replan` (the launch tried
  its amendment, or its `CORRECTION:` was `none`; the Log's `amendments`
  list says why) is a replan, counted and escalated: do not amend it a
  second time. Otherwise (no `CORRECTION:` line, or a reviewer's plan
  defect) decide as below. The items held with it are relaunched with it.
- `budget: ...` → the item failed its checks three times. Bring it to the
  user with the evidence and offer to split it into its own workorder.

The launch-wide ceiling is `maxAgents` (default 120) spawned agents and,
when set, `tokenCeiling` output tokens. At the ceiling the launch finishes
what is running and returns `CEILING`; relaunch, or stop and report. Pushing,
installing and anything destructive stay gated on the owner's word exactly as
before: nothing in items mode pushes.

Spawn `implementer` with the plan and context paths. Three outcomes:

- **`IMPL-DONE`** → go to step 3.
- **`ADVICE-NEEDED`** → see "Consultation" below — not a failure, doesn't count
  against any cap; the cheap path so one hard decision doesn't cost a whole
  escalated phase.
- **`PLAN-DEFECT`** → append the evidence to the context file's `## Log` under
  the round's `### Round <n>` heading, increment nothing, and spawn `planner`
  fresh (a replan is always fresh — see "Re-entering a phase" below). This is
  the loop working.

  **Amend, or replan.** First decide whether this defect needs a replan at
  all. It does not when the evidence already names what is wrong *and*
  states the correction: the implementer's `CORRECTION:` line, or a
  reviewer's `plan_defect` finding carrying a `fix`. Typical cases are a
  criterion's command or anchor, a path that moved, or one wrong fact in
  `## Context`. Then it is an **amendment**:

  1. `py -3 tools/amend_check.py save <plan> <context>`;
  2. spawn `planner` fresh at its default tier, with the description
     `amendment: <slug> <what>` and the correction verbatim (planner.md "When
     you are spawned as an amendment");
  3. `py -3 tools/amend_check.py check <plan> <context>` once it returns.

  Exit 0 (`AMENDMENT`) means Goal, Out of scope and Needs human judgement are
  untouched, no section came or went, and at most 20 lines changed outside
  `## State` and `## Log`. The amendment is then not a replan: it does not
  count toward the cap below and does not move the next replan up a tier.
  Exit 1 (`REPLAN: <why>`), or a planner returning `NOT AN AMENDMENT`, makes it
  a replan like any other, counted and escalated. Relaunch the rounds from
  the same round number either way.

  **In workflow mode the launch runs this route itself** for an
  implementer's, a fixer's or an item implementer's `CORRECTION:` (never a
  lane's, never a reviewer's), with the same three steps as agents of the
  launch (`amend-save:<id>:r<n>`, `amendment: <slug> <id>:r<n>`,
  `amend-check:<id>:r<n>`, where `<id>` is the item, or `implementer` in
  rounds mode), and re-runs the work, uncounted, only on `AMENDMENT`. So a
  rounds-mode `PLAN-DEFECT` whose result carries `amendment` has already had
  its amendment tried: `amendment.why` says why it did not hold, and it is a
  replan. In the ForgePact bug batch (2026-09-27), item `research-build` sat
  parked for 41 minutes waiting for the driver's turn to make a 2.5-minute
  amendment (docs/agents/workorder-calibration.md).

  No two amendments run back to back: a second `PLAN-DEFECT` with no
  implementer round between it and the first amendment is a replan. The
  test is the files, never the planner's account of what it changed. Over
  2026-09-19..24, labels such as "fix criterion 11 anchoring" and "fix M3 row
  id collision" each counted as a full replan. `tools/workorder_audit.py` R24
  fails an `amendment:` planner that has no `save` before it or no `check`
  after it (the driver's, or for a planner a launch spawned, one from an
  agent of that same launch), and R11 counts it as a replan unless its
  `check` passed.

  **Escalate the planner's model as it fails, rather than only counting.** A
  `PLAN-DEFECT` is the pipeline telling you this problem is harder than the tier
  you assigned it:

  | Replan | Spawn `planner` with | Because |
  |---|---|---|
  | 1st | `model: opus` (its default) | most wrong plans are wrong about one fact, not about the mechanism |
  | 2nd | `model: fable` | cheaper reasoning has now demonstrably failed twice on the same problem |
  | 3rd | — stop, ask the user | a goal that survives two replans is usually not well posed |

  Spend money where it's earned, not guessed. Planning is *not* cheap: over
  2026-09-19..22 the planner was 22% of list-price spend, and a Fable 5.1
  plan averaged $10.38 against $4.00 on Opus 5 (about $2.60 on Opus 5.5) —
  Fable's output costs 2.5× Opus 5.5's, and a planner writes more output than
  any other phase. One Fable replan still costs less than the round it saves
  and far less than a wrong mechanism model's live session, which is why it
  is the *second* replan's tier and not the first plan's.

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
is that assumption's own context) or an amendment (fresh and labelled
`amendment: ...`, which is how the audit tells it from a replan); the agent id doesn't resolve (`/workorder
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

An agent cannot spawn another agent, which is the shape: the phase returns its
question to you, you spawn `consultant`, and append the answer to `## Log`
under `### Decisions` — verbatim, so the next round doesn't re-ask a question
already paid for and a later reader knows which decisions were made at which
tier. Then re-enter the phase per "Re-entering a phase" above: same tier, a
resume — cheaper than escalating the phase and losing everything done so far.

**Refuse a malformed question.** The request must carry `QUESTION`, `WHAT I
WOULD DO WITHOUT HELP`, `WHY I AM UNSURE` and `CONTEXT`. An empty second field
goes back unforwarded — an asker with no view hasn't thought about the
problem, and answering it turns consultation into delegation: the weaker model
stops deciding and the pipeline pays two tiers for one phase.

**Spawn `consultant` at `opus`** by default. For a question in the `fable` rows
of the triage table, pass `model: fable` — one focused question is the
cheapest place in this pipeline to buy the strongest model, far cheaper than
running a whole phase there.

**Cap: 2 consultations per round.** A third is a signal, not a quota to spend:
triage was wrong, so escalate the *phase* — re-spawn it a tier up with what's
been learned in the `## Log` — rather than buying answers one at a time.
Record that you did, and why.

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
implementer's transcript. Two sentences go with the paste, both measured on
one `docs-sync-reviewer` that ran 40 turns twice:

- **Out of scope is a list of things not to report as missing, not a list to
  police.** Say so. Proving each item was left untouched is the verifier's
  criteria, and took about 20 of that reviewer's round-0 calls.
- **A re-run reviewer that was `BLOCKING` gets its own finding back** — the
  `where` and `problem`, from the round's Log entry — with "confirm from this
  diff whether it is resolved; earlier rounds reviewed the rest". Handed a
  one-file delta and not told what it had found, it re-read the whole
  round-0 commit to work that out.

**The verifier gets the plan path and the context path**, and the reminder
that the context file is opened one cited heading at a time with
`section.py`, never whole.

**Every verify before the pull request is a development verify.** The
owner, 2026-10-02: *"full suite runs shouldnt be run so frequently. it should
be reserved to the last step before the pr. during development only relevant
subset should be run."* So a round's first verify, and the items gate, run
`run_criteria.py <plan> --jobs auto --dev`: every criterion except a whole
suite (`unittest discover`, `run_tests_parallel.py`, a bare `pytest`) or one
marked `(final)`, which it prints as `NOT SELECTED (final gate only: ...)`;
the verifier skips its step-3 root suite. A fix round runs by reach (Step 4,
"Re-verify what the fix reaches"), which defers the same criteria. The full
set runs once, as the final gate before the pull request (Step 5).
`workorder-rounds.js` hands each verifier its scope; under `fullVerify: true`
every verify of the launch is the full set. A criterion about a file the
change forgot to touch still runs under `--dev`, which is why a first verify
is not a reach selection.

**The verifier starts with `tools/run_criteria.py <plan> --jobs auto`.** The
script runs every command-shaped criterion in one call, exactly as written,
once per distinct command, and skips gated ones. With `--jobs` it runs
independent commands at the same time by resource class: builds first and
alone, then at most one whole suite, two browser suites and any number of
file checks side by side, while a timing benchmark (`e2e:perf`) and any
command it does not recognise run alone in their place in the plan. It
prints criteria in plan order with the serial run's `cmd-<n>.log` numbers,
each exit code with the tail of the command's output, and judges nothing, so
the verifier still decides every criterion and reads the prose ones.
Verifiers spent about a third of their time on model turns between commands,
so this cuts per-command turns and nothing the verifier observes. A root
suite a criterion already ran is not run a second time for step 3 of
`verifier.md`.

**A whole-tree run goes to the background** (the rounds verifier, the reach
re-verify, the items gate). The verifier starts `run_criteria.py <plan>
--jobs auto --out <its scratchpad>/criteria` with `run_in_background: true`,
so no Bash limit can kill it, then re-issues `py -3 tools/run_criteria.py
--status <out> --wait 220` at a Bash timeout of 300000 while it exits 3, and
reads `<out>/report.txt` once it exits 0. The runner keeps
`<out>/status.json` current (each criterion's state and each command's exit
code and seconds) and writes everything it prints to `report.txt`. Exit 4
means the run went stale (not finished, and not updated for 1,900 s): the
verifier re-runs the criteria not yet done in the background, with
`--start`. Exit 2 means there is no status file. `--wait` can never exceed
220 s, so a poll stays under audit R5's 240-second limit. The verifier still
runs every command itself and never reads an out directory it did not
start. One item's checks (`--item`) stay in the foreground: none took more
than 1.0 minute in the bug batch, so a poll would only add turns.

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
| `instrument-blindness-reviewer` | `ForgePact/plugin`, a hook install, a resolved-pointer call, a `docs/` research finding | `ForgePact/plugin/**`, hook/installer code under `hs-game-sdk/**`, any `*-research.md`, any `docs/submodules/*/instructions.md`, any other doc recording a measured result, or delta text matching `Rva\|GetModuleHandle\|MmCreateHook\|HookOneScript\|InstallScriptHook` |

A re-run reviewer reads the delta paths; round 0 reads the whole change.
`decompile-output-guard` on round ≥ 1 reads every line added since it last
passed, plus the whole contents of any file added since.

**Require the severity label.** Every finding is `BLOCKING`, `NON-BLOCKING` or
`PLAN-DEFECT`, leading with "no blocking findings" when true — restate this in
the dispatch so an unlabelled report is obviously incomplete, not something to
classify yourself. `PLAN-DEFECT` only when no implementation of the plan as
written could satisfy its Goal — say that explicitly; a missing assert, pin,
or sentence the plan didn't forbid is `BLOCKING`, for the implementer, not the
planner.

**Ask for the fix.** A `BLOCKING` finding whose resolution the reviewer can
state exactly, as the edit itself at its `path:line`, carries it as `fix`. A
finding that needs judgement or research leaves `fix` out. Step 4's patch
route runs only when every `BLOCKING` finding has one.

### Step 4 — route the verdicts

Merge everything into one decision:

**A round is for defects, not for improvements.** Every reviewer labels each
finding `BLOCKING` or `NON-BLOCKING`; only blocking ones spend a round. The
panel-and-launcher pass hit the cap on a round whose instrument reviewer opened
*"nothing here blocks shipping"* then listed five follow-ups and three nits —
costing the workorder its last round and shutting down eight findings already
green. A cap that counts polish as failure turns "found something worth doing"
into "the pipeline stops".

The line, when a reviewer's label looks wrong to you:

| Blocking | Non-blocking |
|---|---|
| a failed acceptance criterion | a test that could be sharper |
| ships inert or wrong — the `HOOK INSTALLED`-and-does-nothing class | a follow-up idea for later |
| a legal finding from `decompile-output-guard` — **always** | a naming or wording nit |
| an overclaim in **release notes** — `AGENTS.md` is explicit that one wrong "Fixed" erodes every note after it | an overclaim in a research doc or a test comment |
| an overclaim in `docs/RUNTIME_DATA_MODELS.md` or `hs-game-sdk/curated/`, which every module reads as settled | an internal doc that is merely incomplete |
| before a pending live session, anything that leaves one of its checks uninterpretable — a measured route with no positive control, an instrument that cannot see what the check reads. A round costs 13-23 min; a wasted session costs the owner a sitting | |
| | a player-visible ForgePact change with no `release-notes-vX.Y.Z.md` — `forgepact-tag.yml` falls back to generated notes under a rewrite banner; flag it, don't spend a round |

- **`verifier` PASS and no blocking finding** → go to step 5, carrying every
  non-blocking finding into the report.
- **`verifier` PASS-PENDING-HUMAN and no blocking finding** → everything
  runnable passed and something needs a person: a live game session, a
  twelve-minute rebuild, eyes on a window. When what is pending is a live game
  session the context file writes out as a `### Live procedure <n>`, go to
  step 4.5; otherwise go to step 5 and report it as such.
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
  has lost the thread and more rounds will not find it. The cap counts rounds,
  not implementers: a laned round — every lane plus the join, then one
  verify — is one round. A patch round that held (below) is not counted.

  **Owner scope is not a failure.** A round or a plan change that exists only
  because the owner added or changed the work is the owner deciding, not the
  pipeline failing, and it spends neither the cap nor the tier ladder:

  - **A plan change:** run `tools/amend_check.py save`, *then* record the
    owner's answer under `### Decisions` as `owner, <YYYY-MM-DD>: "<their
    words>"`, then spawn the planner (labelled `amendment: <slug> owner
    scope ...`), then `check`. When the change would otherwise be a replan
    (the Goal or scope moved, a section came or went, more than 20 lines
    changed) and the context gained an owner line since `save`, `check`
    prints `SCOPE: <k> new owner decision(s)` and exits 0. A change small
    enough to be an amendment anyway prints plain `AMENDMENT`. Either way it
    is not a replan and costs no tier step.
  - **A round:** when a relaunch exists only to carry owner decisions (the
    finish review's approved fixes, a rename, a new tab), add one to `scope
    rounds: <k>` in `## State` before the launch. `workorder-rounds.js` adds
    it to the cap, at most 3 in all.

  The audit keeps this honest: R25 fails a `SCOPE:` verdict with no message
  typed by the owner behind it, so the exemption cannot relabel a failed plan.
  In the ForgePact UI redesign, restyle's Amendment 1 (the owner's own ask)
  counted as its third replan, polish met the cap on owner items and split
  into `sandbox-ports`, and ship's round 3 was refused although rounds 1-2
  were owner scope.

  **The patch route.** When a round's only defects are `BLOCKING` reviewer
  findings and *every* one carries its reviewer's `fix`, the next round is a
  patch round instead. "Only" means no failed criterion, no structural or
  NOT DONE finding from the verifier, no `PLAN-DEFECT`, and no finding from
  `instrument-blindness-reviewer`, because what a hook sees is not settled by
  applying an edit someone wrote down. In a patch round:

  - one implementer (`patch-implementer:r<n>`) applies those fixes and
    nothing else;
  - `verifier`, fresh as always, re-verifies only the criteria the patch can
    reach (below, "Re-verify what the fix reaches"): the previous verify
    failed no criterion, so nothing else is owed;
  - only the reviewers that raised the findings re-run, to confirm their own,
    plus `decompile-output-guard` whenever its trigger matches.

  Whether the round was a patch is decided afterwards, from the tree:
  `round_delta.py size <slug> <n>` must report at most 20 changed lines and
  no new file, and the delta must not reach `ForgePact/plugin/`, hook or
  installer code under `hs-game-sdk/`, a `*-research.md`, a
  `release-notes-v*.md`, or instrument-shaped text. A patch that holds is not
  counted against the cap, and `## State` carries `patch rounds: <k>`. One that
  does not hold is an ordinary round: its reviewers are chosen by the Step 3
  table, and it counts. Two patch rounds never run back to back, and a patch
  decided on the third round still runs.

  Measured over the 29 sessions that ran a planner (started 2026-09-19..24):
  fix rounds, replans and reviewer re-runs took about a quarter of all
  subagent spend. 32 of the 69 fix-round implementers ran for 7 minutes or
  less, each inside a 13–23 minute round that also used one of the three the
  cap allows. How many of them applied a fix the reviewer had already written
  out was not recorded; the `fix` field makes that countable. Details:
  [`docs/agents/workorder-calibration.md`](../../../docs/agents/workorder-calibration.md#the-cheap-routes-2026-09-25).

  **Re-verify what the fix reaches.** The owner, 2026-09-27, as a one-file
  panel fix in the ForgePact UI redesign's ship workorder was about to pay
  another full verify behind a ~20-minute Python suite: *"run relevant tests
  only if possible"*. A fix round, patch or ordinary, that follows a verify
  which passed every criterion but the failed ones re-verifies only the
  criteria the fix can reach, plus the failed ones. A criterion the earlier
  verify deferred to the final gate counts as a known standing here, not an
  unknown one (2026-10-02), and the runner defers it again unless `--failed`
  names it:

  ```bash
  py -3 tools/run_criteria.py <plan> --jobs auto --changed-since <hub base> \
      --changed-since <submodule>=<its base> --failed <k,...> --out <scratch>/criteria
  ```

  The bases are this round's, from `round_delta.py heads <slug> <round>`.
  The runner selects each criterion whose `(reads ...)` (planner.md, "Spend
  each check once") a changed path matches, each failed one, each one that
  declares no `(reads ...)` and each one a selected criterion runs `(after
  ...)`, and prints what it selected and skipped and why, so the report
  shows the scope. The verifier reports a skipped criterion as
  `not-selected`, never `pass`, and skips its step-3 root suite unless a
  selected criterion runs it. `workorder-rounds.js` hands a round's verifier
  this command itself (2j) and records `verify scope:` in the Log. The full
  set still runs:

  - **at the final gate before a push**, once: a PASS reached through a
    scoped verify is `PASS (scoped)` in step 5 until a full verify covers
    it, in this workorder or in the feature's final one;
  - **when the delta is unknown**: `round_delta.py` exited 3, the base heads
    are missing, or the runner itself prints `scope: full -- delta unknown`;
  - **when the change touches a shared contract**: the runner falls back by
    itself for `hs-game-sdk/`, `third_party/yytoolkit/`, `.gitmodules` and
    its own selection code, and for any glob on the plan's `## State`
    `shared contract:` line;
  - **when a criterion's standing is not known**: it was unattempted for any
    reason but an unset gate, or the last verify reported it without its
    plan number;
  - **when the verifier cannot tell** from the printed scope whether the
    fix could reach a criterion the runner skipped. It then runs the full
    set and says why.

  Independence is unchanged: the verifier is still fresh, never sees the
  implementer's reasoning, and runs every criterion it reports. The re-check
  is smaller, not shared. In the ship workorder, run by hand, it saved about
  40 minutes per fix round (evidence in
  [`workorder-calibration.md`](../../../docs/agents/workorder-calibration.md#re-verifying-only-what-a-fix-reaches-2026-09-27)).

  **At the cap, split — never close it by hand.** Three failed rounds mean the
  pipeline lost the thread, regardless of plan size or how close it looks to
  done; finishing it yourself makes the driver the implementer at the wrong
  tier (see "Driver discipline" below) — the failure this cap exists to
  prevent, not a shortcut past it. Open a *new* workorder with only the
  still-open findings and its own fresh three rounds, saying which findings
  are already closed so the split doesn't re-litigate passed work.
- **Empty delta after a PASS** (the implementer confirmed a finding does not
  hold and changed nothing) → the previous PASS stands; re-run only the
  reviewers that were BLOCKING, to confirm with evidence or withdraw.
- **Any `PLAN-DEFECT`** — from implementer, verifier, or a reviewer finding
  labelled that way — → Step 2's "Amend, or replan": an amendment when the
  correction is stated, else back to step 1, under the replan cap.
- **Anything under `UNATTEMPTED` that needs a human** — a live game session, a
  rebuild, eyes on a window — → stop and ask. Never record an unchecked
  criterion as passed.
- **Every failed criterion names a gate that `gates:` does not literally
  carry, and there is no BLOCKING finding** → treat it as `PASS-PENDING-HUMAN`,
  not `IMPL-DEFECT`. The verifier ran something that was not due yet, and
  nothing the implementer does can make it pass. Check the State first: a
  `gates:` value with `|` or "or" alternatives is a template that sets nothing. Rewrite
  it as the gates actually set plus a `gates pending:` line.

### Step 4.5 — live gate: `live-operator` runs the session, you talk to the person

A live session is a phase like the others, and the driver does not run it.
Across 2026-09-19..22 every live session was run by the driver itself —
`ipc.ps1` commands, log parsing, DLL installs, heredoc appends to the Log —
and the sessions that did so were the most expensive drivers measured: up to
325 turns, 99.5M tokens and $60 of list price, at 250-300K context a turn,
against a median driver of $12.

0. **Look at the game lease first.** Call `hs_lease_status` yourself — the
   one `hs_*` call item 3's rule allows, because it only reads. There is one
   Hero Siege install and one machine-wide lease on it, and the lease cannot
   stop an install (hs-drive never installs), so you are the one who has to
   look before asking to change the DLL:
   - `held` by another process → do not ask to install and do not launch.
     Tell the user the holder's `label` and `taken_utc` (from `record`) and
     stop, or wait for their word. A `force` takeover happens only when the
     owner says so: you do it, through `hs_lease_acquire` with `force: true`,
     and log it under `### Live <n>` as a takeover naming the previous
     holder from `took_over_from`. Never pass `force` on anyone's say-so but
     the owner's, and never ask the operator to.
   - `stale` → say so (the holder's process is gone) and carry on; the
     operator's acquire recovers it.
   - `free`, `held_by_me` → carry on. A `warning` on a free lease means the
     last session backed up and never restored, which a session's own
     teardown restore (step 5) should now prevent: say so before the install
     question, and restore that backup yourself (lease, restore, inspect,
     release) when it is this workorder's; another workorder's goes to the
     owner.
   - `unavailable` → report its `detail` and stop.
1. **Ask before anything changes on the owner's machine.** One question:
   install this build now, and is a session convenient now? Never install on
   your own — the owner decides when the DLL their game loads changes. On a
   yes, install it yourself with the module's documented install command (one
   call), and nothing else.
2. **Spawn `live-operator`** with: the slug, the session number `<n>`, the
   context file and the `### Live procedure <n>` heading, the character slot,
   and which build is installed. Record its agent id in `## State` › `agents:`.
3. **Relay, do not operate.** A `NEEDS-HUMAN` comes back with one `ASK` (it may number several actions): put
   it to the user verbatim, then `SendMessage` the operator their answer
   (ToolSearch `select:SendMessage` if deferred). Do not run `hs_*` tools
   (item 0's lease calls aside), `ipc.ps1` or log reads yourself — you would be the operator at the most
   expensive context in the pipeline.
4. **Put the next decision to the owner first.** At `LIVE-DONE`, show the
   operator's `CHECKS` lines verbatim and ask whatever the next phase needs
   decided, before any record or docs work starts. The answer usually
   depends only on the session's result. In forgepact-issue-14, Phase B's
   four design questions depended only on Live 1i, known at 01:06, and went
   out at 02:33, after a record round and a 64-minute docs workorder; the
   owner answered them at 08:59.
5. **Route what it returns.** Append at most a short summary and the capture
   path — never the capture — under a `### Live <n>` Log heading, then:
   - every check `pass` → the pending criteria are met. Move the session's
     gate token (for example `live1: complete`) from `gates pending:` to
     `gates:` in `## State`, so a later verifier treats that gate as set and
     runs the criteria it guards. Then go to step 5, or, if criteria gated on
     it still need a mechanical run, relaunch the rounds.
   - a check `fail` with the mechanism as the plan described it → an
     `IMPL-DEFECT` round (step 4), the capture path as its evidence.
   - a `fail` or `not-observed` that contradicts the plan's model of the
     mechanism → `PLAN-DEFECT`; the replan cites the capture.
   - `INSTRUMENT-BLIND` → the instrument could not see its own positive
     control. Nothing was measured, so nothing is concluded; it goes to the
     planner as an instrument defect, never into a doc as "does not happen".
   - `LIVE-ABORTED` → report its `WHY` to the user and stop. A `lease_held`
     `WHY` is another session driving the game: the user decides whether to
     wait or have you take the lease over (item 0).

   The operator restores its own backup at teardown (the owner's standing
   rule, 2026-09-26: a test changed the state, so the test puts it back), so
   do not ask the owner about a restore. Report its `RESTORE:` line. A
   `LEASE:` line still showing `restore_pending: true`, or a `RESTORE:` line
   that is not clean or was skipped, means the saves still carry the session's
   changes: say so, and restore that backup yourself (lease, restore, inspect,
   release) unless the procedure deliberately kept the state.

   A capture `tools/live_checks.py` cannot read — a renamed, missing or
   unreadable check — is not repaired by anyone: report it, and re-run the
   session or replan. The capture is the session's evidence.

**Record this phase while the next one is planned.** When the owner's answer
from 4 means another phase, launch this workorder's record round and, in the
same message, spawn `planner` for the next phase's own slug (that
workorder's Step 1, stopping at the plan), telling it the record is running.
Record and plan share no files: the planner writes only its own workorder
files and reads the result from the capture. The next implementer starts
only after this record round has returned `PASS`, because both edit the
research doc. Merge `origin/main` into the branch only between rounds —
before the record launches or after it returns — never while one runs:
`round_delta.py` and every reviewer diff from the round base, so a merge
mid-round puts main's commits into this round's review. The overlap is up to
about 2 h over forgepact-issue-14's nine research phases (`min(record,
next plan)` summed). This is not folding the record into the next phase's
first round: the record keeps its own rounds, review and commit, so the
measurement is in a tracked file before anything else depends on it.

**Same build, more to measure: a second session, not a new phase.** If the
result raises a question the installed DLL can already answer, have the
planner add `### Live procedure <n+1>` to this workorder (planner.md "A live
session is a procedure") and run it as session `<n+1>`: its own capture, a
fresh operator, a relaunch when the procedure needs one, with the
`instrument-blindness-reviewer` reading only the new procedure first. Ask the
owner once, as in 1. Twice in forgepact-issue-14 (1c→1d and 1e→1f) this was a
new workorder instead, costing about 1.8 h between them. Since Ghidra came
into use every phase has needed a new build, so expect this rarely.

**One sitting, several sessions — never one launch.** When the owner has time
for more than one ready procedure, run them back to back in that sitting, each
with its own install question, launch, backup, operator and capture, and a
stop and restore between any two that write saves. Do not merge procedures
into one launch: nine forgepact-issue-14 sessions used seven different DLLs,
each procedure pins the counts the previous restore left, and two of the nine
crashed the game on stash close.

**Offer a fresh session at the next phase boundary** when this session has
already driven a live session, **or at any workorder boundary once the
driver's context is past about 300K tokens**. The driver relays every
hand-back at its own context size: in forgepact-issue-14, relays at 605-680K
tokens a turn cost about $13 in one 22-hour session, where a fresh session
starts near 90K. The ForgePact UI redesign drove all 14 workorders from one
session: 504 of its 697 driver turns ran above 300K (peak 966K), and the
driver alone cost $108. Say so in one line with the `resume` or `plan`
command, and let the owner decide.

`tools/workorder_audit.py` R17 fails a session whose operator wrote anything
but its `<slug>-live-<n>.md`, installed a build, ran a writing git command,
restored a backup it did not take itself, force-stopped the game, or took
over another holder's lease.
R20 fails any other agent's edit to a capture, the driver's included.

### Step 5 — report

Set `status: PASS` in the workorder and tell the user:

- what changed, and the acceptance criteria with their **real** output;
- when the last verify was scoped (`verifyScope: 'reach'`, or `verify
  scope:` in the round's Log), `PASS (scoped)` and the criteria it ran and
  skipped, as the runner printed them. Every PASS before the final gate is
  scoped (`verifyScope: 'dev'` or `'reach'`);
- **the final gate, as the last step before the pull request** is opened or
  pushed to: a fresh `verifier` on the whole plan with no `--dev`,
  `--changed-since` or `--item` (or a launch with `fullVerify: true`), so
  the whole suites, `(final)` criteria and the root suite run once. It is
  the only full verify of the feature: a middle workorder whose result a
  later one builds on does not run it, and says which workorder does. A
  failure there is fixed and re-verified by reach plus `--failed`, which
  re-runs the failed suite itself;
- every reviewer that ran and what it concluded, including the clean ones, and
  every reviewer skipped this round as `clean@round<n>, not re-run`;
- anything left under `NOT DONE` or `Needs human judgement`;
- how many rounds it took, and what each round caught. That last line is how
  the pipeline earns its keep or shows it is not;
- run `py -3 tools/workorder_audit.py --latest` and report every `FAIL` line
  verbatim beside the round summary, with its `list-price cost` line — a
  workorder that passes its criteria and fails its cost budget says so, not
  silence;
- for a plan of items, or when the owner asks where the time went, run `py -3
  tools/workorder_speed.py --transcript <this session's .jsonl> --json` and
  report its `concurrency`, owner-wait minutes, `items.queued_behind_cap`
  and `routes`. A `queued_behind_cap` above 0 is the only evidence that
  justifies a larger `maxParallel`. The figures and their definitions are in
  the tool's docstring, and the baseline to compare against is in
  docs/agents/workorder-calibration.md, "Measuring where the pipeline spends
  its time";
- if this plan came from a handover copy in another checkout, say that copy
  still reads `READY` and name its path — the harness will not let you edit it,
  and left alone it is cloned into every new worktree as work still to do;
- if the work opened pull requests in more than one module, end with the merge
  order and each PR's link, per `AGENTS.md` § "One Branch and One Pull Request
  per Module, per Feature": submodule PRs first, then the hub PR once
  `submodule-dispatch.yml` has bumped each pointer on hub `main`.

Then fold what is still true out of the workorder and into the document that
describes the result — `docs/hub/design.md`, a `docs/adr/` entry, or the
submodule's `instructions.md`. Leave both workorder files where they are; they
are ignored.

**When the owner says they are leaving,** list in one line what could run
without them — a plan for a phase whose decisions they have already made, a
record round — and start only what they approve. A plan written before the
owner's answer to its own design question is likely a replan: in
forgepact-issue-14 the design moved under the owner's answers four times.
"Plan only" still means plan only.

## Spend each check once, and overlap what does not wait

The owner, 2026-09-26: *"If some checks can be done once for 2 things it's
better than checking twice after each change"*, and *"Waiting for something
to end completely before picking it up sounds like a waste of time."* In the
ForgePact UI redesign (14 workorders over about 48 hours) a full panel verify
cost 25-35 minutes and was paid at least 15 times. The evidence is in
[`workorder-calibration.md`](../../../docs/agents/workorder-calibration.md#spending-each-check-once-the-forgepact-ui-redesign-2026-09-26).
Independence stays as it is: the verifier and every reviewer still run fresh
and never see the implementer's reasoning. A check is **shared** between
changes, never skipped.

**1. One round and one verify for everything that is ready together.**
Pending changes that are ready at the same time go into one implementer
round and one full verify: owner feedback, the findings a review produced,
a conflict-free main merge that touches none of the plan's files. Do not give
each its own implement-and-verify round. The patch route (Step 4) and the
3-round cap are unchanged; this is about not starting a second round while
the first one's input is still arriving.

The same goes for one verify's criteria: a check two criteria would both run
is run by one of them. ForgePact's Python suite re-runs the panel's browser
suites, so a plan whose criteria run those suites directly runs its full
Python suite with `--exclude-module` for the modules that wrap them
(`planner.md` § "Spend each check once", "Run each suite once per verify").

**2. Start independent work as soon as its input is committed.** A read-only
agent (`impeccable-finish-reviewer`, a design audit), a documenter writing
only to a scratch path, or a Figma mirror does not wait behind the verifier.
Launch it in the same message as the workflow or the verify, as a background
`Agent` call, pointed at the commit it reads. Work that edits files runs
alongside only when its files are disjoint from everything else in flight.

**3. Stream review findings into fixes.** When a review is its own pass
(a finish review, a design audit, owner feedback worked through by agents),
do not wait for the whole review before fixing:

- **Pin what the reviewer reads.** Fixers will be changing the tree, so the
  reviewer reads a snapshot of one commit: `git worktree add --detach
  <scratch>/review-<sha> <sha>`, or `git archive <sha> | tar -x -C <dir>`,
  with the scratch path outside every repository tree. Remove the worktree
  afterwards.
- **Split the review, run the parts at once.** Several narrower reviewers,
  one per dimension or per screen, in parallel, instead of one broad
  reviewer. Each one appends every finding to its own file in one scratch
  directory the moment it has it, as one JSON line: `{"id", "severity",
  "files": [...], "where", "problem", "fix"}`. A reviewer whose contract says
  it edits nothing writes only there, outside the repository trees; that is
  its report, not an edit.
- **Watch and dispatch.** The driver watches that directory with `Monitor`
  and hands each new finding to a fixer (`implementer`, the finding as its
  whole brief) at once. Fixers run one at a time, or in parallel only when
  their `files` are disjoint from every fixer in flight; a file several
  findings share (`app.css` and the like) serialises them. A fixer runs no
  git write while another fixer is in flight; when one finishes with none
  other running, it commits each finished finding's files as its own commit
  (`git add -- <files>`), the way a lane join does. A finding that needs a
  decision goes into the owner batch (5), never to a fixer.
- **Verify once, after the stream drains.** A fixer runs at most a test
  inside its own files. When every reviewer has returned and every fixer is
  done, one full verify (plus the reviewers that raised blocking findings,
  re-reading the fixed commit) covers every fix together, per rule 1.

A plan of items (Step 2, "Items") gets this from `workorder-rounds.js`
itself: reviewers read pinned commits, each finished reviewer's findings go
to a fixer at once, and one gate runs after the queue drains. The streaming
is per reviewer, not per finding, because `agent()` returns only when an
agent ends, so split a big review into narrower reviewers (`reviewScopes`)
to get findings sooner. The gate reads a tree nobody is editing, because it
runs only when no implementer is left. A plan with no items still runs in
rounds, where no fixer may touch the tree the round's verifier is reading;
for it, and for a review that is not a workorder's own reviewer pass, this
driver procedure is the way to stream.

**4. Main moved: merge it when it is clean and misses the plan's files.** A
plan's precondition is "main moved → merge it when `git merge-tree
--write-tree HEAD origin/main` shows no conflict and `git diff --name-only
HEAD...origin/main` names none of the plan's files; stop only otherwise"
(`planner.md`). The implementer does that merge and records it in `## Log`.
A separate main-merge workorder cost 1-2.5 hours each time in the redesign.

**5. Batch the owner's decisions.** After a round that changed what the owner
sees, serve a snapshot for them to look at, and collect every question the
next plan needs into one `AskUserQuestion` batch before that plan is
written, so the answers are plan inputs rather than mid-round replans. The
snapshot is built from `git archive <sha>` into a scratch directory, never
the working tree, and served through the module's own sandbox server with
its stdin held open (for example `tail -f /dev/null | <serve command>`, run
in the background), so the server does not exit when its input closes.

**6. A flaky test is fixed the round it is seen.** A test that fails once
without a code cause (a port the browser refuses, a timing race) is a defect
for this round's implementer, or a split right away; it is never re-run in
the hope of a green. The redesign's polish workorder spent its cap on a
Chromium `ERR_UNSAFE_PORT` flake.

**7. During development run the relevant subset; the full set runs once,
before the pull request.** A first verify and the items gate run `--dev`, a
fix round after a verify that passed every other criterion runs the
criteria the fix reaches plus the failed ones (`run_criteria.py
--changed-since`), and both defer the whole suites and `(final)` criteria.
The full set runs once at the final gate before the push (Step 5). The
conditions and fallbacks are in Step 3 and Step 4, "Re-verify what the fix
reaches".

**7b. After a write, read the diff, not the file.** The owner, 2026-10-02:
after each write, agents *"spend lots of times on reads ... make sure only
difference or relevant things are read after every write instead"*. An agent
checks its own edit with `git diff -- <path>`, a grep or a ranged read, and
every agent downstream of a write reads the diff since its base: reviewers
already get `git diff <base> -- <paths>`, a re-entered implementer gets the
failed criteria, the evidence and `git diff <base> -- <path>` for what
earlier rounds changed, a replanning planner reads the Log since its last
plan and the sections the defect names, and the scribe reads the `## State`
range and the Log's tail. Measured over the 14 days before: scribes read
both workorder files whole every round (about 13 MB over 228 runs), and
fix-round implementers averaged 22 reads and 134 KB each, 105 of them the
whole plan. `tools/workorder_audit.py` R26 fails an implementer or planner
that reads a file it wrote whole more than twice.

**8. A question never idles the pipeline.** In the ForgePact UI redesign 19
of 60.75 hours passed with a question open and nothing running; the four
longest waits were 380, 273, 256 and 111 minutes, mostly overnight. Two of
those questions did not need the owner at all. So, before you ask:

- **Start everything the answer cannot change**, in the same message as the
  question: the other items or findings, a record round, the final gate on
  what is already settled, the next plan when its decisions are made. The
  answer then lands on finished work, not on an idle queue.
- **An out-of-scope bug is a spin-off, not a question.** Flag it as a
  separate task (the app's spawn-task chip, or a one-line note in the
  report) and carry on; the redesign waited 256 minutes on a port-fallback
  bug that was spun off anyway.
- **A reversible choice gets its default, not a wait.** A P2 or nit, or a
  choice where one option is plainly the plan's: apply it, say so in one line
  with how to undo it, and let the owner overrule it. The redesign's longest
  wait, 380 minutes, was a P2 icon question asked before the push.
- **Only a decision that changes what gets built, and cannot be undone
  cheaply, stops the work it gates** — and only that work, as an item's
  `owner:` line parks only its item.
- **Every owner question in a plan carries `default:` and `reversible:
  yes|no`**, an item's `owner:` and each `## Needs human judgement` entry
  alike, and `plan_lint.py` refuses one without them (`owner-no-default`,
  `owner-no-reversible`, `owner-reversible-no-default`). A legal or
  decompile-output question is `reversible: no` with a default of `none`
  (`owner-legal-default`). So is a wait on a live capture or on data that does
  not exist yet: the bug batch's three `owner:` items were of that kind. A
  reversible one runs on its default inside the launch and comes back under
  `defaulted`, with how to undo it; tell the owner in one line and move on.
- **Route `unblocked` before you ask.** A result that waits on a person lists
  under `unblocked` the parked work that does not wait on them, each with its
  route. Start those routes in the same message as the question.
- **Start what an `ASK` answer cannot change before relaying it.** A
  `live-operator`'s `NEEDS-HUMAN` or a phase's question for the person goes
  out with the independent work already started, not ahead of it. In the
  bug batch the owner answered a question the driver asked while a launch
  ran with *"Don't ask me, you can reserve live spot for hs drive mcp"*.

**9. Review the design before building it, not at ship.** For a chain of
UI workorders:

- Run the design tools on the direction comps before anything is bundled or
  downloaded: the impeccable detector (its overused-font check included) and
  a critique. The redesign bundled Geist, then the owner moved to IBM Plex,
  costing three replans across prep, buildout and restyle.
- Run `impeccable-finish-reviewer` after the first restyle round, not after
  the last workorder: the redesign's eight finish findings (F1-F8) arrived
  in ship and reopened a component choice already built.
- A design export gets a structure check against the current panel when it
  is made (its texts present in the page, its selectors inside the component
  they name, no runtime values such as a version baked in), not at restyle,
  where seven mismatches cost two restyle rounds and two Figma rounds.
- A design finding names its class and checks the class ("every text glyph
  on every tab"), not only the instances listed: PR #100's review found an
  icon the F6 fix had missed.

## Driver discipline

**The driver never implements.** Its tool use is limited to: reading the
workorder, `round_delta.py`, `tools/amend_check.py save`/`check` around an
amendment, `git status`/`git diff` for a dispatch, `Edit` on
`## State`/`## Log`, `Agent`, `SendMessage`, `AskUserQuestion`, step
4.5's one approved install, `plan_lint.py --items-json` while a streamed plan
is being written, and the speed procedures above: `Monitor` on a
findings directory, a pinned review snapshot (`git worktree add --detach`,
`git archive`), a `git fetch`/`git merge-tree`/`git merge` of `origin/main`
between rounds, and building and serving the owner's snapshot, which checks
nothing and is for the owner's eyes only. Log entries go in with `Edit`, under the one
`## Log` — not `cat >>` heredocs, which is how a context file ended up with two
`## Log` headings and rounds recorded under the planner's. Running builds
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
           args: { slug, planPath, contextPath, checkoutRoot, goalExcerpt, implementerModel, round,
                   reviewers: { '<name>': 'never' | 'clean' | 'blocking', ... },
                   submodules: ['<dir>', ...], researchHeadings, baseHeads, priorFindings, state,
                   lanes: [{ name, files: [...] }, ...], join,
                   items: [{ id, title, files, checks, after, shares, owner, default, reversible, build_reads }, ...], streaming, answered: ['<id>', ...],
                   reviewScopes: { '<reviewer>': [{ label, paths: [...] }, ...] },
                   maxParallel, maxAgents, tokenCeiling, itemAttempts, reviewPassCap } })
```

`items` is pasted from `py -3 tools/plan_lint.py <plan> --items-json`
unchanged, on every launch of a plan of items (the relaunch reads which are
done from `state`'s `items:` line). `streaming: true` while the plan's State
says `planning: streaming`: the workflow then runs a `refill` agent that waits
on `plan_lint.py --items-json --known <ids> --wait 480` and adds each item
the planner releases, and it runs no gate before planning is complete.
`answered` lists the items whose `owner:` question now has an answer under
`### Decisions`; an unanswered item with `reversible: true` and a default
runs on that default and comes back under `defaulted`. `reviewScopes` splits
a reviewer into several that each read only their paths, run as separate
reviewers. `maxParallel` (`DEFAULT_MAX_PARALLEL`, 4; a whole number from 1
to 16, anything else is `BAD-ARGS`), `maxAgents` (120), `tokenCeiling`
(none) and `itemAttempts` (3) are the
budgets in Step 2, "Items"; `reviewPassCap` (4) is how many passes a
reviewer makes as commits land before it waits for one final catch-up pass
once nothing else is running. Items that could not have come from that output
(a bad or duplicate id, no files, an `after:` naming no item, items beside
lanes) are refused with `BAD-ARGS` before anything is spawned. A launch with
no `items` runs in rounds exactly as below.

`lanes` and `join` are pasted from `py -3 tools/plan_lint.py <plan>
--lanes-json` (Step 1), and only for the first implementation of the plan's
steps (Step 2); leave them out otherwise. Lanes that could not have come from
that output (no `join: true`, a lane with no files, a bad or duplicate name)
are refused with `BAD-ARGS` before anything is spawned.

`checkoutRoot` is this session's `git rev-parse --show-toplevel`; the script
hands the scribe `planPath`/`contextPath` joined under it, and refuses with
`BAD-ARGS` without it unless both paths are already absolute. On 2026-09-24
(`hs-drive-game-lease`, run from a worktree) a scribe given relative paths
resolved them against the main checkout, found neither file, and wrote
nothing. `reviewers`/`submodules` are as in Step 3. `researchHeadings` names the
context file's `###` heading(s) for `instrument-blindness-reviewer`.
`baseHeads` is `{ '.': sha, '<submodule>': sha }`, copied from `## State` ›
`round base:`, so a `never` reviewer reads the whole change from the
workorder's own start rather than a later round's snapshot. `priorFindings`
is `{ '<reviewer>': [{ where, problem }, ...] }` for each reviewer entering as
`blocking`, copied from the most recent `### Round <n>` Log entry that carries
a `BLOCKING (k)` list (an entry written for an implementer's `PLAN-DEFECT` or
`ADVICE-NEEDED` has none, so that is the round before it) — a fresh launch
has no memory of what that reviewer found, and a reviewer not told re-derives
the whole change to find out (measured: 46 calls on a one-file delta). Rounds
inside one launch carry it themselves. The script still accepts a `repoRoot`,
and nothing here passes it: it re-points the git commands agents are handed,
never where `Edit` lands, so it cannot make another checkout workable — Step
0.25 stops that case before it gets here.

`state` is the plan's `## State` section exactly as `py -3
.claude/skills/workorder/section.py <plan> 'State'` prints it. The script
merges each round's `round:`/`phase:`/`reviewers:`/`open defects:` (and,
once a patch round has held, `patch rounds:`) into it and hands the scribe the whole block, so the lines only the driver writes —
`gates:`, `round base:`, `agents:`, `decisions in force:` and any other —
are pasted back verbatim rather than left to the scribe to preserve. On
2026-09-23 a scribe handed only the four computed lines replaced the whole
block with them in several workorders, and the next verifier, reading no
`gates:`, reported gated criteria pending instead of running them.

The script also reads `gates:` itself. Only tokens literally on that line
count as set. `gates pending:` and `route tokens:` set nothing, and a value
with `|` or "or" alternatives, or a `<placeholder>`, is a template that sets nothing. A
round with no BLOCKING finding and no verifier `other_defects` (a structural
finding, or a non-empty NOT DONE or DEVIATIONS), whose every failed criterion
names a gate that is not set, returns `PASS-PENDING-HUMAN` and does not spend another round. The
Log entry records what the verifier said, and each such criterion appears as
`- PENDING (gate <x> not set)`. With no `gates:` line in State, nothing is
reclassified. On 2026-09-24, forgepact-issue-14-phase1j lost three rounds to a
template `gates:` line, which the verifier read as every gate set, and ended at
`CAP` with no real defect open after round 0.

It runs Step 4's patch route itself. It asks each reviewer for a `fix`,
decides when the next round is a patch (the round's Log gets `next: patch
round` and State `phase: patch`), runs `round_delta.py size` in that round,
and writes `patch: held` or `patch: not held (<why>)` under its Log heading.
It keeps `patch rounds: <k>` in State and reads it back on the next launch,
so a patch that held stays uncounted across launches. A patch decided just
before a launch ends is not carried over; the relaunch runs an ordinary round.

A plan of items returns `PASS`, `PASS-PENDING-HUMAN`, `PARKED`, `PLAN-DEFECT`
(a reviewer's plan defect, the gate's unrunnable criterion, or a refill that
`plan_lint` refused), `CEILING`, `CAP` (the gate failed three times),
`AGENT-FAILED`, `STATE-LOST` or `SCRIBE-FAILED`, always with `items:` beside
it (each item's `id`, `status`, `reason`, `attempts`, `commits`, `evidence`
and `progress`, and `replan` when an amendment was tried and did not hold)
and `gate:` (each gate run). It also carries `defaulted` (each owner item
that ran on its default: `id`, `question`, `default`, `status`, `commits`
and `undo`), `amendments` (each amendment the launch tried, and whether it
held), and, on a result that waits on a person (`PARKED` with an owner item,
or `PASS-PENDING-HUMAN`), `unblocked` (Step 2, "Items"). Its Log entry is
`### Round <n> (items)`, with `unblocked:`, `defaulted (k):` and
`amendments (k):` lines when they apply, and State gains `items:
<id>=<status>; ...`, where an item done on its default reads `defaulted`.

A plan without items loops implement → verify+reviewers → route as code (same 3-round cap,
scribe for Log/State, reviewer table), returning `PASS`, `PASS-PENDING-HUMAN`,
`PLAN-DEFECT`, `ADVICE-NEEDED`, `AGENT-FAILED`, `STATE-LOST`, `SCRIBE-FAILED` or `CAP`. One
launch may cover several rounds; `PLAN-DEFECT` means relaunching after the
replan. `STATE-LOST` means the scribe's own before/after report shows a
State line gone that the round did not replace; the launch stops there, before
a verifier can read the damaged block. Paste the result's `state` back under
`## State` (its `lost` lists what went), then act on its `then` exactly as if
that had been the outcome — `continue` means relaunch at the State's `round:`.
A laned round that ends before its join returns `PLAN-DEFECT`,
`ADVICE-NEEDED` or `AGENT-FAILED` with `lanes:` beside it — every lane's
`name`, `verdict` (`IMPL-DONE`, `PLAN-DEFECT`, `ADVICE-NEEDED`, `STOPPED`, or
null for a lane that returned nothing) and `progress_so_far`, the same list
the scribe wrote under the round's Log heading. Hand the replan or the
consultant every lane's progress, not only the lane that stopped the round:
the lanes that finished left their work uncommitted in the tree.
`SCRIBE-FAILED` means the scribe wrote nothing (`written: false`, or no
result), so no State was lost and nothing is compared: append the result's
`log` under `## Log` in the context file, replace `## State` with its `state`,
then act on its `then` the same way. Before this outcome existed, the
`hs-drive-game-lease` scribe's "N/A - files do not exist" report was read as a
State with every driver-owned line gone and returned `STATE-LOST` for a round
that had lost nothing.
A rounds-mode result whose implementer's `CORRECTION:` was tried carries
`amendment` (`amended`, `why`, `verdict`), and a `PASS-PENDING-HUMAN` carries
`unblocked`, empty when nothing else is left.
An amendment that `amend_check.py` confirms now runs inside the launch
(Step 2, "Amend, or replan"). Replans (including every amendment that did
not hold), consultations, owner questions and the step 5 report stay with
the driver: a workflow script cannot resume an implementer, and in 22
sessions there was one consultation. Every re-entry inside is a fresh spawn
(no resume) — measured no worse than a resumed implementer. The scribe runs as the restricted `scribe` agent type
(`Read`, `Edit` only), never the unrestricted `workflow-subagent` every other
Record-phase agent here still is; `tools/workorder_audit.py` R16 fails a run
whose scribe edited outside `.claude/workorders/`, ran `git add`/`git commit`,
wrote a file through a shell command (a redirect/heredoc, `tee`, a
PowerShell content cmdlet, ...) instead, or — for the restricted `scribe`
type — ran any shell command at all.

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

Set in each agent's frontmatter, with an `effort:` beside every tier that
takes one: `planner` opus/high, `implementer` opus/high, `consultant`
opus/xhigh, `instrument-blindness-reviewer` opus/high, the other reviewers and
`live-operator` sonnet/high, `verifier` and `scribe` haiku (Haiku 4.5 takes no
effort). Override the model for one run by passing `model` on the Agent call;
effort has no per-call override, which is why it is pinned — an agent without
one inherits whatever the session runs at.

**Where Opus 5.5 fits (2026-09-22).** `opus` resolves to Claude Opus 5.5; it
did so already for the last sessions of the calibration set, with no file
changed. What it changes is the price, and price is what the tiers were
chosen by. List prices per million tokens (input / output / cache read):

| Model | In | Out | Cache read |
|---|---|---|---|
| Fable 5.1 (`fable`) | $10 | $50 | $0.25 |
| Opus 5.5 (`opus`) | $4 | $20 | $0.20 |
| Opus 5 (was `opus`) | $5 | $25 | $0.50 |
| Sonnet 5 (`sonnet`) | $2 | $10 | $0.20 |
| Haiku 4.5 (`haiku`) | $1 | $5 | $0.10 |

92-99% of every role's tokens here are cache reads, so for this pipeline
Opus 5.5 costs about what Sonnet 5 does, and 40-60% less than Opus 5 did:
the 20 Opus 5 drivers and the Opus-5 planners of the calibration set would
have cost about half as much. Hence:

- **implementer → `opus`.** Measured on the 22 sessions: Sonnet 5
  implementers averaged $4.65 a run with a tail to $18.90 (p90 46.8M tokens,
  max 78.9M — the runs that hit round caps); Opus-tier ones used 36% fewer
  tokens on average (11.2M against 17.4M) while carrying the hard triage
  rows, and the four Opus 5.5 runs averaged $4.82. Same money, no tail.
- **planner, consultant, instrument-blindness-reviewer stay `opus`**, now
  cheaper. `fable` keeps the two rows above plus the second replan.
- **reviewers stay `sonnet`, verifier and scribe `haiku`.** On the same
  tokens Opus 5.5 would cost the reviewers 1.2× and the verifier 2.9×, with no
  finding of theirs measured as missed.
- **Effort.** Opus 5.5 defaults to `medium` and thinks more per turn than
  Opus 5 at the same level; `high` is pinned for the phases that carry long
  agentic work and `xhigh` for the one narrow question `consultant` answers.
  Neither is measured yet: `tools/workorder_audit.py --calibrate` reports
  per role *and model*, so the next recalibration says whether they hold.

`tools/workorder_audit.py` prices every transcript at these rates
(`MODEL_PRICES`), so a report's cost line tracks a tier change without anyone
redoing this arithmetic.

**Tier aliases, not pinned version IDs.** `opus` names the tier, not a
version. Pinning `claude-opus-5` across eight files buys reproducibility this
pipeline doesn't need (a broken model fails a *test*, not a review) and costs
a stale-ID sweep every generation — not the `*Rva*` case from `AGENTS.md`,
since an alias is a documented moving pointer, not a silently-drifted
constant.

**When to reach for `fable` yourself,** beyond the automatic escalation above:

- The plan must establish an **unknown** game mechanism, not verify a
  suspected one — the "which of 34 candidates does X" shape, where a wrong
  mechanism model has cost whole sessions rather than one round.
- The change falls in the class `AGENTS.md` § "Don't Suspend the Game's Own
  Runtime" warns about — the failure mode inverts, and the blast radius is the
  player's session.

Not on a routine change, or the implementer or a reviewer — those run at high
volume where 2.5× is real money for no measured gain — and not as the
default planner: at 22% of spend with Fable averaging 2.6× an Opus 5 plan, it
is no longer "nearly free".
