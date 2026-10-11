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
planner(opus) → implementer(opus) → verifier+reviewers(haiku,opus) → PASS ─→ report
  ▲ PLAN-DEFECT ◄───────┘ ◄──────────────────── IMPL-DEFECT / BLOCKING
                                    PASS-PENDING-HUMAN → live-operator(opus) → report
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
| **introduces or changes concurrency** — threads, async boundaries, a new `#[tauri::command]` that touches disk or network, anything that can deadlock or race | planner `planner-xhigh`, implementer `implementer` |
| must **establish an unknown game mechanism**, not verify a suspected one — the "which of N candidates does X" shape | planner `planner-xhigh`, implementer `implementer` |
| falls in the **suspend-the-game-loop class** (`AGENTS.md`) | stop — read `ForgePact/docs/menu-pause-plan.md` §0 with the user before planning at all |
| touches **only docs, tests or config** — no product source, no hook, no binding | planner `planner-medium`, implementer `implementer-medium` |
| everything else — including hook attachment and three-binding contracts, which had their own `opus`/`opus` rows when the default implementer was `sonnet` | the agents' own pins (`planner` and `implementer`, both opus/high) |

**A tier is an agent name, and sometimes a model.** The names are effort
variants: `planner-xhigh` is `planner` at `xhigh` effort, generated from
`planner.md`'s `effort-variants:` by `tools/sync_agent_tooling.py`, with the
same instructions word for word. Spawn the variant as the `subagent_type`;
the `Agent` tool takes a `model` per call but no effort, so the name is the
only way to choose one. In workflow mode the args carry `implementerEffort`
(`high` or `medium`) and `implementerModel`, set with `--launch-args`'
`--implementer-effort` and `--implementer-model`. Every variant runs on `opus`
unless a row names another model. `fable` is not a tier: the owner's
license dropped it on 2026-10-05, so the pipeline escalates effort on
`opus` wherever it once escalated to `fable` (§ "Model tiers").

The implementer's default is `opus` since 2026-09-22 (see "Model tiers"):
Opus 5.5 reads cache at Sonnet 5's price, and 99% of an implementer's tokens
are cache reads, so the tier costs about the same per token while the Sonnet
tail (p90 46.8M tokens, max 78.9M) was what hit the round caps. The docs row
ran `sonnet` until 2026-10-06; it now runs `implementer-medium` on `opus`
too, because at medium effort Opus 5.5 scores ahead of Sonnet 5.5 for about
the same cost on cache-read work ([`model-tiers.md`](model-tiers.md),
"Reviewers, live-operator and the docs row → `opus`/`medium`").
`implementerModel: 'sonnet'` (`--implementer-model sonnet`) still
works for a run the owner asks to put on it.

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
so lanes a lint rejected can never be launched. `workorder_brief.py
--launch-args` puts the same `lanes` and `join` into the workflow's args
(see "Driver discipline"), and refuses to print args at all while the lint
has a finding.

**A plan of items streams instead** (Step 2, "Items", and
[`items.md`](items.md)). Run `py -3
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
3. **Apply any launch the last session left unrecorded**, then **read the
   plan file in full, `## Needs human judgement` and all of `## Log`** — the
   one point the driver reads the whole Log, for consultations and what each
   round found; replans and launches are counted in State (`replans:`,
   `launches:`). `py -3 tools/workorder_record.py apply --latest --slug
   <slug>` applies this workorder's newest saved run, and changes nothing
   when State's `last run:` already names it. Grep `## Context` for what step 2 needs rather than reading
   it whole. Re-run the step 0.25 checkout check against the plan's
   `repoRoot:` and preconditions, then the step 0.5 triage — a task property,
   not a session one, though the repo may have moved under a week-old plan.
4. **Check it is self-sufficient.** Every step must be actionable from the file
   alone. A step that assumes a decision made only in conversation, names a file
   that no longer exists, or says "as discussed" is a `PLAN-DEFECT` now — cheaper
   to route back before an implementer has spent a round discovering it.

Snapshot before each round: `py -3 .claude/skills/workorder/round_delta.py
snapshot <slug> <round>` — step 3 diffs against it. In workflow mode the
round's implementer runs it as its first command and `delta` as its last
(the launch tells it how), so the driver runs neither; in driver mode you run
it before spawning or re-entering the implementer. The workorder's base is
its earliest snapshot, `.rounds/<slug>/round-<k>.json`, which
`--launch-args` reads as `baseHeads`.

**A laned plan** (Step 1's `--lanes-json` printed lanes) runs its lanes only
on the first implementation of the plan's steps: round 0, or the relaunch
after a replan. `workorder_brief.py --launch-args` puts `lanes` and `join` in
the args then (round 0, or `--first-implementation` after a replan), and
never when relaunching after an `IMPL-DEFECT` or on a fresh `resume` past
round 0: a defect round is a fix
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

**Items: a plan that streams** (Step 1's `--items-json` printed items) runs
steps 2-4 as one workflow launch with no rounds inside it: each item is
implemented, checked and committed on its own, reviewers read commits as
they land, and one whole-tree gate runs when the queue drains. **Read
[`items.md`](items.md) before launching or routing a plan of items**: the
scheduling, owner defaults, rebuilds, in-launch amendments, `PARKED`
routing, budgets and the args and result shapes are there.

Spawn `implementer` with the plan and context paths and its brief command:
`py -3 tools/workorder_brief.py "<plan>" --round <n>`, plus `--since-round
<n-1>` past round 0 (and `--amended` on the re-run after an amendment). The
implementer runs it first: one call prints the Goal, Out of scope, State,
the steps and criteria, every Context subsection a step cites by `ctx:`, the
Decisions, the previous round's Log entry and the `git diff` pointers since
that round's snapshot. The full files stay named as the fallback, read by
section for what the brief lacks. Over the 18 sessions after 2026-10-02 the
plan and context files were the two most-read files of the pipeline: 915
`Read` calls and 12 MB, plus 400 shell reads by implementers
(docs/agents/workorder-calibration.md, 2026-10-03). Three outcomes:

- **`IMPL-DONE`** → go to step 3.
- **`ADVICE-NEEDED`** → see "Consultation" below — not a failure, doesn't count
  against any cap; the cheap path so one hard decision doesn't cost a whole
  escalated phase.
- **`PLAN-DEFECT`** → the round's `### Round <n>` Log entry carries the
  evidence (the launch's record writes it; in driver mode you append it), and
  State's `replans:` counts it — the launch adds one for every `PLAN-DEFECT`
  it returns, before a verify or after one. Then spawn `planner` fresh (a
  replan is always fresh — see "Re-entering a phase" below). This is the loop
  working.

  **Amend, or replan.** First decide whether this defect needs a replan at
  all: it does not when the evidence names what is wrong *and* states the
  correction (the implementer's `CORRECTION:` line, or a reviewer's
  `plan_defect` finding carrying a `fix`). Then it is an **amendment**:
  `amend_check.py save`, a fresh `planner-medium` on opus labelled
  `amendment: <slug> <what>`, `amend_check.py check`. An amendment planner
  always runs as planner-medium on opus, never escalated. A confirmed
  amendment is not a replan: take the one `replans:` the launch added back
  off (`replans: <k-1>`). In workflow mode the launch runs this route itself
  for an implementer's `CORRECTION:`, so a `PLAN-DEFECT` whose result carries
  `amendment` already had its amendment tried, and is a replan. **Read
  [`amendments.md`](amendments.md) before you amend**: the exact steps, what
  `check` accepts, the R24/R27 audit rules, and when two amendments in a row
  are a replan.

  **Escalate the planner's model as it fails, rather than only counting.** A
  `PLAN-DEFECT` is the pipeline telling you this problem is harder than the tier
  you assigned it. Count from State's `replans:`, not from memory: since
  2026-10-11 a `PLAN-DEFECT` that came back before any verify counts too,
  where before it kept `round: n` and was counted nowhere (the /workorder
  audit, F13):

  | Replan (`replans:`) | Spawn `planner` with | Because |
  |---|---|---|
  | 1st | the first plan's tier (`planner`, or `planner-xhigh` on a hard triage row) | most wrong plans are wrong about one fact, not about the mechanism |
  | 2nd | `planner-max` | cheaper reasoning has now demonstrably failed twice on the same problem |
  | 3rd | — stop, ask the user | a goal that survives two replans is usually not well posed |

  Spend money where it's earned, not guessed. Planning is *not* cheap: over
  2026-09-19..22 the planner was 22% of list-price spend, and a planner
  writes more output than any other phase, so more thinking per turn costs
  most here. This ladder escalated to Fable 5.1 until 2026-10-05, when the
  owner's license dropped it; `max` effort on `opus` takes its place, and is
  the *second* replan's tier rather than the first plan's for the same
  reason Fable was: one expensive replan costs less than the round it saves,
  but not less than a plan that needed no escalation.

  Record the escalation under the round's heading in the context file's
  `## Log` (`planner escalated to planner-max after 2nd PLAN-DEFECT`), and
  write the tier into `## State` › `agents:` as `planner-tier=planner-max`.
  A `planner-max` failure signals the problem is under-specified, not
  difficult — say so to the user when you stop.

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

**Spawn `consultant`** (opus/xhigh) by default. For a question in the
`planner-xhigh` rows of the triage table, spawn `consultant-max` — one
focused question is the cheapest place in this pipeline to buy the most
thinking, far cheaper than running a whole phase at `max`.

**Cap: 2 consultations per round.** A third is a signal, not a quota to spend:
triage was wrong, so escalate the *phase* — re-spawn it a tier up with what's
been learned in the `## Log` — rather than buying answers one at a time.
Record that you did, and why.

If `consultant` returns `ESCALATE`, do that immediately without waiting for the
cap.

### Step 3 — verify, in parallel

`py -3 .claude/skills/workorder/round_delta.py delta <slug> <round>`,
against step 2's snapshot, says what this round touched — it records each
repo's HEAD too, so work the implementer commits mid-round is in the delta,
not only what it leaves dirty. Exit 3 means the snapshot is missing,
unreadable, or a recorded head can no longer be trusted — treat everything as
changed. In workflow mode the implementer runs it last, with the two content
greps and `py -3 tools/decompile_check.py <slug> <round>`, and reports all
three; in driver mode you run them.

**Reviewers run by measured yield** (the 2026-10-11 /workorder audit, F03:
rounds with a BLOCKING finding, out of rounds the reviewer ran in —
`instrument-blindness-reviewer` 30%, `sdk-contract-reviewer` 7%,
`docs-sync-reviewer` 4%, `decompile-output-guard` 1%,
`tauri-command-reviewer` 0%):

- **Every round:** `verifier`, and `instrument-blindness-reviewer` when it
  applies — on round 0, or when it was `BLOCKING` last round, or when the
  delta matches its trigger (table's second column), or when `delta` exited 3.
- **Every round, deterministically:** `tools/decompile_check.py`, the
  PostToolUse hook's own signatures over the lines the round (or, with
  `--base`, the workorder) added. A hit is a `BLOCKING` finding under
  `decompile-check`, with no `fix`. When the check did not run (no report, or
  an exit other than 0 and 1) `decompile-output-guard` reviews that round
  instead: a legal check is never skipped.
- **Once, at the final gate** (Step 5): `docs-sync-reviewer`,
  `sdk-contract-reviewer` and `tauri-command-reviewer`, each when it applies
  (table's first column), over the whole change since the workorder's base,
  plus `decompile-output-guard` when the branch touches `docs/` or a `.md` —
  a paraphrase that follows the decompiled original needs a reader, and it
  lands in prose.
- **A deferred reviewer that the final gate found `BLOCKING`** re-runs every
  round of the fix launch, to confirm its own finding, until it is clean.

Record each skip in `## State` › `reviewers:` (`<name>: clean, not re-run`,
or `<name>: never, deferred` for one waiting for the final gate), reported
the same way in step 5.

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
every verify of the launch is the full set, and a `finalGate: true` launch
is that full verify alone, with no snapshot and no implementer. A criterion about a file the
change forgot to touch still runs under `--dev`, which is why a first verify
is not a reach selection.

**The verifier runs the criteria through `tools/run_criteria.py <plan> --jobs
auto`**, in the background for a whole-tree run, polled with `--status` and
judged from `--digest`; it runs every command itself and judges each
criterion from what the runner printed. In workflow mode the launch hands it
that procedure; in driver mode **read
[`verify-mechanics.md`](verify-mechanics.md)** before you dispatch one.

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

| Reviewer | Applicable when the change touches | When it runs |
|---|---|---|
| `instrument-blindness-reviewer` | `ForgePact/plugin`, a hook install, a resolved-pointer call, a `docs/` research finding | every round: round 0, then when `BLOCKING` or the delta contains `ForgePact/plugin/**`, hook/installer code under `hs-game-sdk/**`, any `*-research.md`, any `docs/submodules/*/instructions.md`, any other doc recording a measured result, or text matching `Rva\|GetModuleHandle\|MmCreateHook\|HookOneScript\|InstallScriptHook` |
| `decompile-output-guard` | `docs/`, research notes, decompiler-read comments | `tools/decompile_check.py` every round; the agent in a round whose check did not run (its trigger: any `.md .cpp .hpp .py .rs .ts .js` file), and at the final gate when the branch touches `docs/` or a `.md`; a legal finding is always blocking |
| `docs-sync-reviewer` | always | the final gate |
| `sdk-contract-reviewer` | `hs-game-sdk/`, `tests/cpp/`, any relic/item/stat scanner, any live `CInstance` or decoded save tree | the final gate |
| `tauri-command-reviewer` | `hub/src-tauri/src/`, the updater, anything the hub's interface reads | the final gate |

A re-run reviewer reads the delta paths; round 0 and the final gate read the
whole change since the workorder's base.

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
- **Any `IMPL-DEFECT`, or any BLOCKING finding** → in workflow mode the launch
  goes straight on to the next round itself, up to the cap: a fresh
  implementer gets the round's Log block and the merged State inline, since
  the files are written only once the launch returns. Such a round never
  reaches you; only `PLAN-DEFECT`, `ADVICE-NEEDED`, `CAP`, `PASS`,
  `PASS-PENDING-HUMAN` and `AGENT-FAILED` do (and, for items, `PARKED` and
  `CEILING`). Until 2026-10-11 the scribe's bookkeeping stops made a launch
  one round in practice (median 1; the /workorder audit, F08). In driver mode:
  append it to the context file's `## Log` under a new `### Round <n>`
  heading, bump `round:` in `## State`, snapshot the new round (step 2), and
  re-enter the implementer per "Re-entering a phase" — normally a resume,
  same tier, pointed at that heading. Send the **evidence** in the Log entry,
  not the message: the failing command and its real output, the reviewer's
  `path:line`. A defect report the implementer has to re-derive wastes the
  round you spent finding it.

  Carry the round's non-blocking findings along **as context, not as work** —
  the implementer may fix one cheaply while it is already in that file, and
  must not spend the round on them.

  Cap: **3 implement→verify rounds.** On a fourth, stop and bring it to the
  user with everything tried so far. Ping-ponging past three means the pipeline
  has lost the thread and more rounds will not find it. The cap counts rounds,
  not implementers: a laned round — every lane plus the join, then one
  verify — is one round. A patch round that held (below) is not counted.

  **Owner scope is not a failure.** A round or a plan change that exists only
  because the owner added or changed the work spends neither the cap nor the
  tier ladder: a plan change goes through `amend_check.py` (which prints
  `SCOPE:` for it), and a relaunch that only carries owner decisions adds one
  to State's `scope rounds:` (at most 3). An amendment planner always runs as
  planner-medium on opus, never escalated, here too. The exact procedure and
  the R25 audit are in [`amendments.md`](amendments.md) § "Owner scope is
  not a failure".

  **The patch route.** When a round's only defects are `BLOCKING` reviewer
  findings and *every* one carries its reviewer's `fix`, the next round is a
  patch round instead. "Only" means no failed criterion, no structural or
  NOT DONE finding from the verifier, no `PLAN-DEFECT`, and no finding from
  `instrument-blindness-reviewer`, because what a hook sees is not settled by
  applying an edit someone wrote down. In a patch round:

  - one implementer (`patch-implementer:r<n>`), spawned as
    `implementer-medium` whatever the triaged implementer, applies those
    fixes and nothing else: the fixes are written down already, and the size
    check below measures whether applying them stayed that small;
  - `verifier`, fresh as always, re-verifies only the criteria the patch can
    reach (below, "Re-verify what the fix reaches"): the previous verify
    failed no criterion, so nothing else is owed;
  - only the reviewers that raised the findings re-run, to confirm their own;
    `decompile_check.py` runs as in every round, and `decompile-output-guard`
    stands in when its trigger matches and that check did not run.

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

  **Re-verify what the fix reaches.** A fix round, patch or ordinary, after a
  verify that passed every criterion but the failed ones re-verifies only the
  criteria the fix can reach plus the failed ones (`run_criteria.py
  --changed-since <this round's base heads> --failed <k,...>`), and defers the
  whole suites and `(final)` criteria; the full set still runs at the final
  gate, when the delta is unknown, when the change touches a shared contract,
  when a criterion's standing is unknown, or when the verifier cannot tell.
  `workorder-rounds.js` hands a round's verifier this command itself (2j) and
  records `verify scope:` in the Log. The rules and the evidence are in
  [`verify-mechanics.md`](verify-mechanics.md).

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

A live session is a phase like the others, and the driver does not run it:
`live-operator` does, from the context file's `### Live procedure <n>`, and
the driver checks the game lease, asks the owner before installing a build,
relays each `NEEDS-HUMAN` verbatim, and routes `LIVE-DONE`,
`INSTRUMENT-BLIND` and `LIVE-ABORTED`. **Read [`live-gate.md`](live-gate.md)
before the first step of a live gate**: the lease states, the install
question, the relay rules, how each operator verdict routes, the teardown
restore, and the R17/R20 audit rules are there.

A live gate waits on a person, so it is also where the driver session should
end rather than idle (Driver discipline, "End the session at a gate").

### Step 5 — report

Set `status: PASS` in the workorder and tell the user:

- what changed, and the acceptance criteria with their **real** output;
- when the last verify was scoped (`verifyScope: 'reach'`, or `verify
  scope:` in the round's Log), `PASS (scoped)` and the criteria it ran and
  skipped, as the runner printed them. Every PASS before the final gate is
  scoped (`verifyScope: 'dev'` or `'reach'`);
- **the final gate, as the last step before the pull request** is opened or
  pushed to: a launch with the args of `py -3 tools/workorder_brief.py
  --launch-args <slug> --final-gate` (`finalGate: true`). It spawns no
  snapshot and no implementer: a fresh `verifier` on the whole plan with no
  `--dev`, `--changed-since` or `--item`, so the whole suites, `(final)`
  criteria and the root suite run once, beside the reviewers deferred to the
  final gate (Step 3) over the whole change since the workorder's base, and
  `decompile-output-guard` when `branchPaths` touches `docs/` or a `.md`. In
  driver mode, spawn that verifier and those reviewers yourself. It is the
  only full verify of the feature: a middle workorder whose result a later
  one builds on does not run it, and says which workorder does. It returns
  `PASS`, `PASS-PENDING-HUMAN`, `PLAN-DEFECT` or `IMPL-DEFECT`: a failure
  there is fixed in a rounds launch (its State already says the next round,
  and a deferred reviewer that found something enters it `blocking`), which
  re-verifies by reach plus `--failed`, and then the final gate runs again;
- every reviewer that ran and what it concluded, including the clean ones, and
  every reviewer skipped this round as `clean@round<n>, not re-run`, or
  deferred to the final gate;
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
better than checking twice after each change"*. Independence stays as it
is: the verifier and every reviewer still run fresh; a check is **shared**
between changes, never skipped. In short:

1. **One round and one verify for everything that is ready together** —
   owner feedback, a review's findings, a clean main merge — not a round
   each; and one verify's criteria run a shared suite once.
2. **Start independent work as soon as its input is committed**, in the same
   message as the launch or the verify.
3. **Stream a review's findings into fixers** against a pinned snapshot, and
   verify once after the stream drains.
4. **Main moved: merge it** when it is clean and misses the plan's files.
5. **Batch the owner's decisions** before the next plan.
6. **A flaky test is fixed the round it is seen**, never re-run for a green.
7. **During development run the relevant subset**; the full set runs once,
   at the final gate. 7b. **After a write, read the diff, not the file.**
8. **A question never idles the pipeline** (below).
9. **Review the design before building it**, not at ship.

**Read [`checks-and-overlap.md`](checks-and-overlap.md)** when several
changes are ready at once, when a review runs as its own pass, when main
moved, before a UI chain, or before you ask the owner anything: each rule's
procedure and evidence is there. Rule 8 there, **"A question never idles the
pipeline"**, applies to every owner question: start everything the answer
cannot change in the same message as the question, apply the default to a
reversible choice and say how to undo it, spin an out-of-scope bug off
instead of asking about it, and route a result's `unblocked` list first.

## Driver discipline

**The driver never implements.** Its tool use is limited to: reading the
workorder, `tools/workorder_brief.py --launch-args`, `tools/workorder_record.py
apply` after each launch, `round_delta.py` (driver mode),
`tools/amend_check.py save`/`check` around an
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

**Build the args with one command, and pass them through.**

```bash
py -3 tools/workorder_brief.py --launch-args <slug> [--reviewers <name,...>] \
    [--implementer-effort high|medium] [--implementer-model opus|sonnet] \
    [--research-headings '<heading>'] [--first-implementation] [--answered <id,...>] [--final-gate]
```

```
Workflow({ scriptPath: ".claude/workflows/workorder-rounds.js", args: <the JSON it printed> })
```

It prints `slug`, `planPath`, `contextPath`, `checkoutRoot`, `goalExcerpt`
(`## Goal` and `## Out of scope`), `state` (`## State` as `section.py`
prints it), `round`, `reviewers` (State's `reviewers:` line, plus each
`--reviewers` name it lacks, entering as `never`), `priorFindings` (each
blocking reviewer's findings, from the newest Log round that lists BLOCKING
ones), `baseHeads` (the workorder's earliest snapshot), `submodules` (the
plan's `module:` line, plus `--submodules`), `lanes`/`join` on a first
implementation, and `items`/`streaming` for a plan of items, all from the
files and from `plan_lint`. Do not read State, the Log or the lint JSON into
your own context to assemble args: drivers made 1,171 shell reads of the
workorder files and 536 `section.py` calls doing that by hand (the
2026-10-11 /workorder audit, F04/F16). Add to the JSON only what no file
holds: `reviewScopes` and the items budgets ([`items.md`](items.md)). Exit 1
means `plan_lint` has a finding: it goes back to the planner, as in Step 1.

`--reviewers` names the reviewers that apply to this change (Step 3 table,
first column) and that State does not list yet; the Step 0.5 triage row
gives `--implementer-effort`/`--implementer-model`; `--research-headings`
names the context file's `###` heading(s) recording a research finding, for
`instrument-blindness-reviewer`; `--answered` lists the items whose owner
question now has an answer under `### Decisions`. Lanes, and args that could
not have come from `plan_lint` (`join` not true, a lane with no files, a bad
or duplicate name or item id), are refused with `BAD-ARGS` before anything
is spawned. The script still accepts a `repoRoot`, and nothing passes it: it
re-points the git commands agents are handed, never where `Edit` lands, so
it cannot make another checkout workable — Step 0.25 stops that case.

**After every launch, apply its record before anything else.**

```bash
py -3 tools/workorder_record.py apply --run <runId>
```

The launch writes no file. Its result carries `record`: every round it
finished, each with the State lines it changed and its Log block. The tool
reads the run record Claude Code saved for the launch
(`~/.claude/projects/<project>/<session>/workflows/wf_<runId>.json`; the run
id is the one the Workflow tool reported), merges each round's State lines
into `## State` by key, leaving every other line as it is, and appends each
Log block under `## Log`, marked `<!-- workorder-record run=<runId>
round=<n> -->`, so a second apply changes nothing. Run it before you read
the result's routing, before any replan, consultation, relaunch or report,
and before you end the session: everything after it reads the files. Until
2026-10-11 a haiku `scribe` made this write inside the launch and reported
it back, and 92 of 353 launches (26%) ended `STATE-LOST`, `LOG-DAMAGED` or
`SCRIBE-FAILED` on that bookkeeping, several of them false alarms (F01);
those outcomes no longer exist.

If it exits nonzero it wrote nothing:

- **3** — no run record by that id, or one without a `record` (a launch
  started before 2026-10-11, one that never returned, or a `BAD-ARGS`
  refusal, which ran nothing and has nothing to write). Check the run id
  first (`--project-dir` points it at another project directory). For a
  launch with no record, write that round's `### Round <n>` Log entry and its
  `round:`/`phase:` State lines by hand with `Edit` from what its result shows,
  as in driver mode, then go on.
- **4** — the record is another workorder's, or a workorder file cannot be
  read. You have the wrong run id or the wrong checkout; find the right one.
  Never edit the files to make it fit.

**What a launch returns.** A plan without items loops implement →
verify + per-round reviewer → route as code, with the same 3-round cap, and
returns `PASS`, `PASS-PENDING-HUMAN`, `PLAN-DEFECT`, `ADVICE-NEEDED`,
`AGENT-FAILED` or `CAP`; an `IMPL-DEFECT` or BLOCKING round goes on to the
next round inside the launch. A `finalGate` launch returns `PASS`,
`PASS-PENDING-HUMAN`, `PLAN-DEFECT`, `IMPL-DEFECT` or `AGENT-FAILED`. A plan
of items: [`items.md`](items.md). A laned round that ends before its join
returns `PLAN-DEFECT`, `ADVICE-NEEDED` or `AGENT-FAILED` with `lanes:` beside
it — every lane's `name`, `verdict` (`IMPL-DONE`, `PLAN-DEFECT`,
`ADVICE-NEEDED`, `STOPPED`, or null for a lane that returned nothing) and
`progress_so_far`, the same list the round's Log block records. Hand the
replan or the consultant every lane's progress, not only the lane that
stopped the round: the lanes that finished left their work uncommitted in the
tree. A rounds-mode result whose implementer's `CORRECTION:` was tried
carries `amendment` (`amended`, `why`, `verdict`), and a
`PASS-PENDING-HUMAN` carries `unblocked`, empty when nothing else is left.

An amendment that `amend_check.py` confirms runs inside the launch (Step 2,
"Amend, or replan"). Replans (including every amendment that did not hold),
consultations, owner questions and the step 5 report stay with the driver: a
workflow script cannot resume an implementer, and in 22 sessions there was
one consultation. Every re-entry inside is a fresh spawn (no resume) —
measured no worse than a resumed implementer. The round's snapshot,
`round_delta.py delta`, its two content greps, `round_delta.py size` (patch
rounds) and `tools/decompile_check.py` are the implementer's own first and
last commands, reported in its result; only a laned first round still
spends a haiku agent on the snapshot, because every lane would race to write
it. The amendment's `amend_check.py save`/`check`/`restore` stay separate
haiku agents of the launch: `workorder_audit.py` R24 wants a `save` before
the amendment planner and a `check` after it, and a check the planner ran on
its own edit would be the planner's account of what it changed, which the
check exists to replace.

**State the script reads and writes.** `state` is the plan's `## State` as
`section.py` prints it. Each round's record carries only the keys it
changes — `round:`, `phase:`, `reviewers:`, `open defects:`, `patch rounds:`
once a patch held, `items:` for a plan of items, `launches:`, `replans:`
after a `PLAN-DEFECT`, `final gate:` from a final gate — and
`workorder_record.py` adds `last run:`; every line only the driver writes
(`gates:`, `agents:`, `decisions in force:` and any other) stays as it is.
The script also reads `gates:` itself. Only tokens literally on that line
count as set. `gates pending:` and `route tokens:` set nothing, and a value
with `|` or "or" alternatives, or a `<placeholder>`, is a template that sets
nothing. A round with no BLOCKING finding and no verifier `other_defects` (a
structural finding, or a non-empty NOT DONE or DEVIATIONS), whose every
failed criterion names a gate that is not set, returns `PASS-PENDING-HUMAN`
and does not spend another round. The Log entry records what the verifier
said, and each such criterion appears as `- PENDING (gate <x> not set)`. With
no `gates:` line in State, nothing is reclassified. On 2026-09-24,
forgepact-issue-14-phase1j lost three rounds to a template `gates:` line,
which the verifier read as every gate set, and ended at `CAP` with no real
defect open after round 0.

It runs Step 4's patch route itself. It asks each reviewer for a `fix`,
decides when the next round is a patch (the round's Log gets `next: patch
round` and State `phase: patch`), has that round's implementer run
`round_delta.py size`, and writes `patch: held` or `patch: not held (<why>)`
under its Log heading. It keeps `patch rounds: <k>` in State and reads it
back on the next launch, so a patch that held stays uncounted across
launches. A patch decided just before a launch ends is not carried over; the
relaunch runs an ordinary round.

**Count launches; stop at six.** Every launch's record sets `launches: <k>`
in State, one past the last. Rounds are capped per workorder, but relaunches
after `PARKED` or `CEILING`, after a replan or after a consultation were
counted nowhere (F13). After the sixth launch of one workorder, stop and
bring it to the owner before a seventh — go on, split it, or change the plan
— with what each launch ended on. `replans:` is the replan ladder's count
(Step 2): a launch adds one for every `PLAN-DEFECT` it returns, and a
confirmed amendment takes it back off.

**End the session at a gate; resume rebuilds from the files.** An owner
question, or a live gate waiting on the owner, leaves the driver idle for
hours, and the next turn then re-caches its whole context: 48% of driver
cache writes followed an idle gap over an hour, about 300K tokens each, and
the median driver peaked at 294K (F04). So, at such a gate:

1. Apply the last launch's record, and start everything the answer cannot
   change, in the same message as the question (rule 8 above).
2. Make the files say what is pending — the question under `## Needs human
   judgement` or on the item's `owner:` line, `gates pending:` for a live
   gate — and write nothing else new into your own context.
3. Ask, print the exact `/workorder resume <slug>` command, and end the
   session. Do not wait idle for the answer.

`/workorder resume <slug>` rebuilds everything from the files (Step 2,
"Entering here from `resume`?"), at about 56K tokens of known context
against the ~300K it would re-cache; the answer goes under `### Decisions`
there. The plan already has to survive a session split (§ "Modes"), so
nothing is lost that is not lost already. A live session itself needs a
session to relay the operator: end at the install question when the owner
cannot play now, and run the session from a fresh `resume` when they can.

**Fall back to driver turns** (steps 2–4 by hand, above) when the Workflow
tool is unavailable, the launch fails, or the user says "driver mode" or "no
workflow". In driver mode you run what the launch would: the snapshot before
each round, `round_delta.py delta` and `tools/decompile_check.py` after it,
the Step 3 reviewers by the same yield rule, State and Log with `Edit`, and
the final gate as a fresh verifier beside the deferred reviewers.

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

Each tier is pinned in its agent's frontmatter (`model:` and `effort:`), and
an effort variant (`planner-xhigh`, `implementer-medium`, ...) is the same
agent at another effort, generated by `tools/sync_agent_tooling.py` from the
source's `effort-variants:` line. Spawn the variant by name, in a driver's
`Agent` call and in `workorder-rounds.js` alike: the `Agent` tool takes no
effort, and the name is the one spelling the audit can see. `fable` is not a
tier (the owner's license dropped it on 2026-10-05). Fixed tiers:
`verifier` haiku/medium, `instrument-blindness-reviewer` opus/high, the other
reviewers and `live-operator` opus/medium. The driver is the session itself:
run it on `opus` at `medium`, `high` for a session whose product is the
driver's own judgement.

| Spawn | Model / effort | When |
|---|---|---|
| `planner-medium` | opus / medium | every amendment; the docs/tests/config triage row |
| `planner` | opus / high | the default first plan and first replan |
| `planner-xhigh` | opus / xhigh | the concurrency and unknown-mechanism triage rows |
| `planner-max` | opus / max | the second replan |
| `implementer-medium` | opus / medium | every patch round; the docs/tests/config triage row |
| `implementer` | opus / high | everything else |
| `consultant` | opus / xhigh | the default consultation |
| `consultant-max` | opus / max | a question from a `planner-xhigh` triage row |

**Read [`model-tiers.md`](model-tiers.md)** before changing a tier, adding an
effort level, or answering a cost question: the prices, the measurements
behind each choice (implementer → opus, the amendment planner's pin and its
R27 audit, reviewers at medium, verifier on haiku), and when to reach for
`planner-xhigh` or `consultant-max` beyond the automatic escalation are
there.
