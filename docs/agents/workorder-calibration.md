Story and evidence behind the budgets in `tools/workorder_audit.py` and the
model tiers in `.claude/skills/workorder/SKILL.md` § "Model tiers", as set on
2026-09-22. Backs `AGENTS.md` § ["Some of These Rules Are Enforced, Not Just Written"](../../AGENTS.md#some-of-these-rules-are-enforced-not-just-written).

# Recalibrating `/workorder` on 22 real runs (2026-09-22)

## The question

The pipeline's last substantive change was the restricted scribe (R16, commit
`a2a3b07`, 2026-09-19). Between then and 2026-09-22 `/workorder` was invoked
26 times in 22 sessions across 7 worktrees: 9 `resume`, 1 `plan`, one review
of an outside package, the rest full runs — most of them ForgePact skill-timer
and toggle-row work with live game sessions, and from 2026-09-22 mostly
started from a GitHub issue link. About 18 reached `PASS` (several pending a
live session), 4 hit the round cap and were split, 1 was superseded.

`tools/workorder_audit.py` over all 22 said the pipeline mostly failed its
own budgets:

| Rule | Sessions failing |
|---|---|
| R7 reviewer budget | 17 / 22 |
| R13 round budget | 16 / 22 |
| R8 implementer budget | 14 / 22 |
| R10 driver discipline | 10 / 22 |
| R2 verifier scope, R3 guide read whole, R5 blocking call, R12 plan size | 8 each |
| R11 replans | 8-9 |
| R15 edit-guard workaround, R16 scribe scope | **0** |

The two newest guards held. Everything else needed reading one rule at a time,
because "fails most runs" can mean the runs are bad, the budget is wrong, or
the instrument is.

## What each failure turned out to be

**The instrument, twice.** R13 and R10 keyed rounds by round *number* across
the whole session. A session drives several workorders, each with its own
round 0, so one session's seven workflow launches audited as a single
127M-token "round 0", and every driver turn between two workorders counted
against it. Keyed by (workflow launch, round), the driver's turns per round
fell to p50 1 / p90 6 — the remaining R10 failures are real (a driver editing
`ForgePact/src/forgepact.py`, running builds). And a second `## Log` heading,
which a driver's `cat >>` heredoc had appended, ended the Log for R12, so
everything under it counted as planner-authored.

**The budget.** The previous budgets were set just above a pre-update
average, deliberately, so that a run at the old baseline would fail. After the
changes they were meant to force, they still failed most runs: docs-sync
reviewers ran 26-37 turns against a shared limit of 25 that
`decompile-output-guard` (p90 17) never came near. A rule that fails most runs
is read as noise and then catches nothing. Each budget now sits at about the
90th percentile of what its role did over these runs, per reviewer type,
round 0 apart from later rounds. R5 no longer times `AskUserQuestion`: 7 of
its 8 failing sessions cited a driver's question left open 260-26,642s — the
user thinking — and for 5 it was the only evidence.

**The guide, not the reader.** R3's eight failures were agents that *did*
read ForgePact's guide by section, with 20-to-100-line windows, and still
pulled 68-124KB. The guide is 334KB and 23 of its lines hold 128KB of it —
single list items of 3-23KB in Repository Layout and Command Reference — so a
20-line `Read` returned 45.6KB. `section.py` gained `--toc` (each section's
size) and `--grep` (only the matching items, an oversized one windowed around
the match): the 78KB Repository Layout grepped for `toggleborder` is 3KB.

**The dispatch.** R2's eight were verifiers told only "Workorder: <path>",
reading a 30-42KB plan whole to find its criteria. The dispatch now hands them
the two `section.py` extractions that are their whole mandate.

**An unowned phase.** The drivers that failed R10 hardest were the ones that
ran live game sessions themselves — `ipc.ps1` commands, log parsing, DLL
installs, heredoc appends to the Log — at 250-300K context a turn: up to 325
turns, 99.5M tokens and about $60 of list price, against a median driver of
$12. Drivers were 30% of all spend. Nothing in the pipeline owned the live
session, so the most expensive context did it. `live-operator` now does, from
a planner-written `### Live procedure <n>`, with R17 auditing that it writes
only its capture file and never installs a build.

**Collisions in the Log.** Seven context files carried two `### Round 0`
headings: the planner's template logged the plan under `### Round 0`, and the
scribe logged the round under the same heading. The planner now writes
`### Plan` and `### Replan <k>`.

## Where Opus 5.5 fits

`opus` resolved to Claude Opus 5.5 for the last sessions of the set with no
file changed; the tier aliases were chosen so that would happen. What changed
is price. At list prices ($/MTok in / out / cache read): Fable 5.1 10 / 50 /
0.25, Opus 5.5 4 / 20 / 0.20, Opus 5 5 / 25 / 0.50, Sonnet 5 2 / 10 / 0.20,
Haiku 4.5 1 / 5 / 0.10. 92-99% of every role's tokens are cache reads, so for
this pipeline Opus 5.5 costs about what Sonnet 5 does and roughly half what
Opus 5 did.

The 22 sessions came to about $1,160 at list price: implementer 32%, driver
30%, planner 22%, reviewers 10%, verifier 2%. Implementers by model:

| Model | Runs | Mean tokens | Mean $ | Max $ |
|---|---|---|---|---|
| Sonnet 5 | 43 | 17.4M | 4.65 | 18.90 |
| Opus 5 | 17 | 11.2M | 8.76 | 24.64 |
| Opus 5.5 | 4 | 10.7M | 4.82 | 7.99 |

Opus-tier implementers used about a third fewer tokens while carrying the
triage table's hard rows, and the Sonnet tail (p90 46.8M, max 78.9M) is the
set of runs that hit round caps. At Opus 5.5's price that is the same money
without the tail, so the implementer's default moved to `opus`; `sonnet`
stays for docs/tests/config-only changes. Reviewers stay `sonnet` and the
verifier and scribe `haiku` — on the same tokens Opus 5.5 would cost them
1.2× and 2.9×, with no missed finding of theirs measured. Planning is not the
cheap phase SKILL.md used to call it: 22% of spend, and a Fable 5.1 plan
averaged $10.38 against $4.00 on Opus 5, so Fable stays where the triage table
and the second replan put it and nowhere else.

Every agent that takes one now pins `effort:` — a subagent without one
inherits the session's, and Opus 5.5 defaults to `medium`.

## Not yet observed

Recorded as "not observed", per `AGENTS.md` § "Prove the Instrument":

- `live-operator` has not run a session yet. Its limits are tested (R17's
  fixtures), its behaviour against the game is not.
- The effort pins (`high`, `xhigh` for `consultant`) are chosen, not
  measured.
- Opus 5.5 as the implementer rests on four runs; the Opus 5 runs are the
  larger sample and a different price.

`py -3 tools/workorder_audit.py --calibrate <list>` reprints every number
above from a list of session ids, per role and per role and model. The set
used here was `e651e4ce a4ed5c2e 87070e3b bfdee718 ff2e18fc 687670f2 a27ab079
b6a72c77 7b6e833f d61d18d5 1149765d bd2015b9 6d82062b c089f4c1 ece90d97
fc166594 f90ad632 21d58ac6 2e7a06dd 433734b7 8b014920 fa082d95`; the next
calibration should use sessions from after this change and say whether each
percentile still holds.

## A multi-phase feature: forgepact-issue-14 (2026-09-22..24)

The second measurement was one feature rather than many: ForgePact #14,
crafting from stash materials, run as 16 workorders and 10 live sessions
over 42.4 h (26.5 h active, $469 at list price) in sessions `fa082d95`,
`fe6fc695` and `6db2260e`. The question was whether more agents could work
in parallel. Mostly they cannot:

- **The chain is serial by its nature.** 6 of the 11 transitions between
  workorders waited on a live result or an owner decision. Implementing was
  11.5% of active time and builds 10 minutes in total, so splitting one
  research workorder across agents saves little and collides on the same
  lines of the module guide.
- **Live sessions do not merge into one launch.** 9 sessions used 7
  different DLLs, each procedure pins the save state the previous restore
  left, and 2 crashed the game. One sitting can hold several sessions back
  to back; one launch cannot.
- **What was recoverable** was about 3.5-6.5 h and $55-105, mostly not
  parallelism: a record round and the next plan run at the same time (up to
  about 2 h), a same-DLL follow-up kept as a second session instead of a new
  phase (about 1.8 h, both cases before Ghidra), bookkeeping defects (about
  1.3-1.6 h), and a verifier re-running suites after the 120 s Bash timeout
  (about 1 h of verifier time).

What changed as a result: `tools/live_checks.py` reads a capture's check
lines instead of a hand-written grep; `tools/plan_lint.py` catches four
criterion defects before a round is spent on them; only `live-operator`
writes a capture (R20); the verifier runs a command as written (R21) and a
suite once (R22); a reviewer finding that would leave a pending live check
uninterpretable is BLOCKING; the operator batches consecutive person-only
steps into one hand-back; NON-BLOCKING Log lines drop their evidence; and
SKILL.md Step 4.5 asks the owner's next decision at `LIVE-DONE`, overlaps
the record with the next plan, and offers a fresh session after a live
session.

Not adopted, with the reason: a queue that composes several procedures into
one launch (the three points above); folding the record into the next
phase's first round (it delays the tracked record of a measurement and
shares one round cap between two jobs); a cached test-suite result shared
between implementer and verifier (it would let the verifier report a green
it never observed); and replacing the owner's on-screen counts with a tool
(the only tool reads the save with the game closed, and the owner's eye is
the independent check on the instrument under test). The live-session
contention between worktrees — four incidents where two sessions wanted the
one game — is left to a machine-wide game lease in hs-drive, a separate
change.

## Lanes: independent steps on parallel implementers (issue #176)

The measurement above found a feature's chain of workorders serial, but not
always the steps inside one workorder. Round 0 of
`forgepact-issue-14-player-build` (2026-09-24) ran five build steps one after
another in a single implementer. After about 25 minutes it had written 1,800
lines in 5 files and was still in the first two steps; the whole round was
expected to take one to two hours. Several of those steps touched files the
others never read. Lanes let a plan say so, and let the workflow run them at
once.

What was decided, and why:

- **Syntax (D1).** A lane is a `### Lane: <name>` heading directly under
  `## Steps`, with a `files:` line of backticked paths or globs. One
  `### Join` follows the lanes. Steps above the first lane are preconditions
  for all of them. There is no fixed number of lanes: the Workflow tool runs
  at most min(16, CPUs−2) agents at once and queues the rest.
  `tools/plan_lint.py` refuses overlapping file sets over every pair of lanes
  (conservatively: a glob whose fixed prefix contains another lane's path
  overlaps it), a lane without files, lanes without a join, and a duplicate
  or bad name. `--lanes-json` prints the lane table only when the lint is
  clean, and the driver passes that line to the workflow unchanged.
- **Lanes never write to git; the join commits per lane (D2).** Two
  processes committing in one repository race on `.git/index.lock`, and git
  fails the second at once instead of waiting. So a lane runs no git write,
  no build and no full suite. The join runs alone after the lanes and commits
  each lane's file set as its own commit (`git add -- <paths>`, per
  repository), then does its own steps. `round_delta.py delta` already finds
  committed and uncommitted paths alike, so reviewers do not depend on who
  committed when. A worktree per lane was rejected: every edit would land
  outside the session's checkout, and a submodule's gitdir is per checkout.
- **Stopping is cooperative (D3).** A workflow script cannot cancel a running
  agent. A lane about to return `PLAN-DEFECT` or `ADVICE-NEEDED` writes a stop
  marker (`round_delta.py stop`). Every lane checks it before each step
  (`round_delta.py stopped`, exit 4) and returns `STOPPED` with its progress.
  The join is skipped, and the round goes back to the driver with every
  lane's verdict and progress.
- **Only a launch's first round is laned (D4).** A defect round is a fix on a
  small delta, and nothing attributes a failed criterion or a reviewer
  finding to a lane, so later rounds run one implementer. A laned round
  counts as one round against the cap of three.
- **Reviewers read the round's whole delta (D5)**, whichever lane wrote it.
  Per-lane attribution is in the plan's file sets and the join's commits.
- **The audit reports each lane (D6).** `tools/workorder_audit.py` shows a
  `lane` column, and for each round with two or more implementers, each
  lane's wall minutes and cost, the round's span (earliest lane start to
  latest lane end) against its serial sum (the lanes' wall minutes added up),
  and the join's wall minutes. The same figures are under `lanes` in
  `--json`. R13 scales the round budget by the number of implementers in the
  round, since R8 already holds each one to its own budget. R23 fails a lane
  that ran a git write.
- **The wall-time measurement is gated (D7).** It needs a real laned plan run
  in a real session, which no implement round can produce.

How it will be measured: run `py -3 tools/workorder_audit.py --session <id>
--json` on the first real laned workorder and read its `lanes` entry. The
saving is `serial_minutes` minus `span_minutes`. The join's minutes are the
cost of committing and building once at the end. The before row is round 0
of `forgepact-issue-14-player-build`, from the same tool's table. The after
rows are every laned round `tools/workorder_speed.py` found in the 22-session
baseline (2026-09-27, § "Measuring where the pipeline spends its time"
below), one row per launch, named by its slug. That was the default of the
workorder-speedup plan's owner question, which the owner left standing;
deleting rows undoes it.

| | workorder (launch) | round 0 implement wall time | implementer minutes, added up | join minutes |
|---|---|---|---|---|
| before | `forgepact-issue-14-player-build` (`wf_a1b7b8b6-31b`), one implementer | 47.2 | 47.2 | no join |
| after | `forgepact-ui-features` (`wf_57bb18ae-0e7`), 3 lanes | 20.0 | 30.3 | 24.1 |
| after | `forgepact-ui-port` (`wf_9dd420f2-9c2`), 3 lanes | 46.8 | 63.7 | none in the lane summary |
| after | `forgepact-ui-restyle-prep` (`wf_d360fa54-00b`), 3 lanes | 14.0 | 21.7 | 14.4 |
| after | `forgepact-ui-restyle` (`wf_f137ae4e-2cd`), 2 lanes | 72.5 | 74.9 | 13.2 |
| after | `hs-drive-skill-actions` (`wf_1bc765d2-f84`), 2 lanes | 6.5 | 13.0 | 7.6 |
| after | `hs-drive-skill-actions` (`wf_414054ee-e13`), 2 lanes | 22.2 | 24.3 | 8.3 |
| after | `hs-drive-skill-actions` (`wf_65b0bf5b-381`), 2 lanes | 9.7 | 15.2 | none in the lane summary |

The before row's round 0 was relaunched once after a replan
(`wf_92baf19d-fa0`, one implementer, 4.7 minutes); the row is the first
launch, the one this section's opening paragraph describes. Over the seven
laned rounds the lanes' span was 191.7 minutes against 243.1 added up, so
running them at once saved 51.4 minutes. In the five rounds that recorded a
join, the joins took 67.6 minutes against a 29.0-minute saving. How much of
that join time a one-implementer round would have spent anyway, building and
committing, is not established.

Lanes have now run in the seven real rounds above, and the fan-out and the
join are measured. Whether a real lane keeps to its file set, checks the
marker before each step and leaves git alone is not established, and R23 is
the instrument that will show it.

# The cheap routes (2026-09-25)

## The question

The owner asked whether the pipeline wastes time on defects whose problem and
fix are already known: a reviewer finding that names the edit, or a plan
defect that is one wrong criterion. Each one cost a full implement-verify
round, or a fresh replan, and each counted against the cap.

## What was measured

`tools/workorder_audit.py --json` over the 29 sessions whose transcripts
spawned a `planner` (started 2026-09-19..24), with each agent sorted by its
label. The sort is rough: labels are free text, and fix rounds that ran
inside a workflow launch as `workflow-subagent` are not counted, so the
defect figures are a floor.

| Agents | Spawns | Agent-minutes | List price |
|---|---|---|---|
| fix-round implementers (round 1 and later) | 69 | 711 | $191 |
| replanning planners | 37 | 462 | $170 |
| reviewer re-runs | 212 | 449 | $96 |
| all subagents | | | $1,858 |

That is about $457, or a quarter of all subagent spend. Median wall time is
7.4 minutes for a fix-round implementer and 9.0 for a replan. 32 of the 69
fix rounds, and 17 of the 37 replans, ran for 7 minutes or less. The planner
labels include "Fix buildout criterion 14 flag" (0.9 minutes), "Replan 2: fix
criterion 11 anchoring", "Replan: fix M3 row id collision" and "Replan:
reconcile ADR criteria". Each of those counted as a replan, so the next real
replan went to Fable or to the owner. Whether a fix round's change had
already been written out by its reviewer was not recorded, and is not
established.

## What changed

- **Patch rounds** (SKILL.md Step 4, `workorder-rounds.js` 2i). A round
  whose only defects are BLOCKING reviewer findings that all carry a `fix`
  is followed by a patch round. In it a `patch-implementer` applies the
  fixes, the verifier runs every criterion, and only the finding reviewers
  and `decompile-output-guard` re-run. `round_delta.py size` then checks the
  round: at most 20 changed lines, no new file, and no instrument path or
  release note. A patch that passes is not counted against the cap.
- **Amendments** (SKILL.md Step 2). A `PLAN-DEFECT` that states its own
  correction goes to a fresh `amendment:` planner. `tools/amend_check.py`
  then decides from the files whether it was one: the Goal, scope and human
  questions are unchanged, no section came or went, and at most 20 lines
  changed. An amendment that passes is neither a replan nor a step up the
  tier ladder.
- **The verifier's criteria runner** (`tools/run_criteria.py`). Over 124
  verifiers, 697 of 1,042 wall minutes went on shell commands and 346 on the
  model's turns between them, at a median of 38 tool calls. Exact repeats of
  one command cost only 3 minutes, so running a command once saves little.
  The saving is the turns: the runner runs every command-shaped criterion in
  one call and prints what each printed, and the verifier judges from that.
  A root suite a criterion already ran also stops being run again as
  `verifier.md` step 3's own suite. Caching a result across agents stays
  rejected, as above.
- **R24** fails an amendment with no `save` or `check` around it, two
  amendments with no implementer between them, and two patch rounds back to
  back. **R11** stops counting an amendment whose `check` passed.

## Not yet measured

None of the three has run on a real workorder. The routing, the size check and
the amendment check are tested against stub agents, throwaway repositories
and synthetic transcripts only. For the runner, read a verifier's turns and
wall minutes against the 38-call, 7.6-minute median above. For the routes,
read after the first few real runs:
how many rounds a `next: patch round` Log line saved, how many patches came
back `not held`, and whether a patch that held let a defect through that an
ordinary round's reviewers would have caught. Count that last one from the
next round's findings. If patches often come back `not held`, the fix field
is being used for work that is not a patch, and the prompt needs tightening
rather than the limit raising.

# Spending each check once: the ForgePact UI redesign (2026-09-26)

## The question

The ForgePact UI redesign (hub branch `claude/forgepact-ui-redesign`) ran as
14 workorders over about 48 hours: a port, Figma directions and buildout, a
restyle with its prep, features, gems and loot, polish, sandbox ports,
responsive, a ship workorder, and three workorders that did nothing but merge
`origin/main`. Watching its ETA stretch, the owner said: *"Make sure we
parallelize efficiently as well as save time. If some checks can be done once
for 2 things it's better than checking twice after each change"*, then
*"Let's put some rules in .md files"*, then, about review and fixes: *"Waiting
for something to end completely before picking it up sounds like a waste of
time."*

## What was measured

Read from the 14 plan and context files (gitignored, on the machine that ran
them), not from transcripts:

- **The full verify is the cost.** For the ForgePact panel it is the Python
  suite (11-17 minutes), the behaviour-oracle replay (about 4) and its
  negative control (about 4), six e2e suites (about 6) and `e2e:perf` (about
  8): 25-35 minutes. The feature paid it at least 15 times, often for a
  round whose change could reach one screen.
- **Read-only work queued behind the verifier.** Work such as a finish
  review, the documenter or the Figma mirror was started after a verify
  ended, though it read only a committed tree or wrote only its own file.
- **Review, then fix, in series.** A finish review ran to completion, and
  only then did the first fix start. Its findings arrived over its whole run.
- **Main merges were workorders.** Plans said "main moved, stop", so each
  main update became its own workorder at 1-2.5 hours. Once, the driver
  merged a clean main by hand instead of opening one.
- **No planner took lanes.** Every one that considered them declined because
  the suites must run after the edits, which is what a `### Join` does.
- **Plans pinned moving heads.** Across the 14 context files there were 12
  `### Amendment` and 29 `### Replan` entries. About ten corrections came
  from three defects: a criterion that pinned the hash `HEAD` or
  `origin/main` had at planning time, backticked prose that
  `tools/run_criteria.py` executed as a command, and a heading slice that
  raised when its section was the last in the file. Run over all 14 plans,
  the new `pinned-sha` rule matched 60-odd spans and every match was a real
  commit hash.
- **A flake was retried, not fixed.** The polish workorder reached its cap
  on a Chromium `net::ERR_UNSAFE_PORT` failure: a sandbox server took a port
  Chromium refuses to open.
- **Owner decisions are plan inputs.** A question put to the owner after a
  plan is written comes back as a replan; asked before it, with a build to
  look at, the answer is an input.

## What changed

- `.claude/skills/workorder/SKILL.md` § "Spend each check once, and overlap
  what does not wait": one round and one verify for everything ready
  together; independent read-only or disjoint-file work started beside the
  verifier; review findings streamed to fixers; a clean main merge that
  misses the plan's files done in place; the owner's questions batched with
  a snapshot build to look at; a flake fixed in the round that saw it. Step
  0.5 says a chain of small dependent workorders is the wrong way to split.
- **Streaming is a driver procedure, not a change to `workorder-rounds.js`.**
  Reviewers split by dimension or screen run in parallel, each appending
  findings as JSON lines to a scratch file outside the repository trees,
  against a pinned snapshot (`git worktree add --detach` or `git archive`),
  since fixers are changing the live tree. The driver watches the files with
  `Monitor` and gives each finding to a fixer at once. Fixers run one at a
  time, or in parallel on disjoint files, and one full verify runs after the
  stream drains. The round driver was left alone because a workflow's
  `agent()` returns only when the agent ends, so a script cannot see a
  finding before its reviewer finishes. Handing each finished reviewer to a
  fixer through `pipeline()` would put fixers in the tree while the round's
  verifier reads it, and the verify's evidence would then belong to no
  commit.
- `.claude/agents/planner.md` § "Spend each check once": fewer, larger
  workorders with lanes; tiered criteria (what the change can reach in a
  middle workorder, the full set at a join and in the final workorder); tags
  or merge-base expressions instead of hashes; backticks only on what should
  run; slices safe at the end of a file; the "main moved" precondition that
  merges when `git merge-tree --write-tree` is clean and main touches none of
  the plan's files; a known flake fixed as a step.
- `tools/plan_lint.py` gained `pinned-sha`, with a positive and a negative
  test in `tests/test_workorder_plan_tools.py`.
- The owner narrowed the merge-before-planning practice the same day: merge
  `origin/main` before a plan when it touches files the plan will edit (or
  the workorder tooling), and otherwise once before the pull requests.

## Not yet measured

None of this has run on a real workorder. The saving to look for next time
is the number of full verifies a feature pays against the workorders and
review passes it runs, the wall time from a finish review's first finding to
its first fix, and whether a streamed fix ever collides with another. A fixer
pair that touched the same file, or a pinned review that reported a finding
the live tree had already fixed, would say the procedure needs tightening.

# Streamed items: the round engine without hard gates (2026-09-26)

## The question

After the ForgePact UI redesign (the section above), the owner said: *"Going
back to streamed workorder pipeline instead of hard gates. This could speed
things up significantly."*, and asked *"do workorder/workflow agents spawn
subagents? subagents can also speed up processes"*. The section above changed
the driver's procedures. This one changes `workorder-rounds.js`, which still
ran every workorder as implement everything, verify everything, route.

## What was measured

Read from the redesign's 14 plan and context files (gitignored, on the
machine that ran them). None of them records a round's start or end time, only
dates, so there is no per-round wall clock to compare against. What they do
record:

- **The gate was paid again and again.** 15 `verifier:` verdicts appear in
  the Logs, and a 16th re-verify is recorded in the polish plan's header. The
  ForgePact Python suite alone ran 1,037 s (1,616 tests) and 1,147 s (1,621
  tests) in the ship workorder; that run includes the oracle tests, which
  drive the e2e suites. `e2e:perf` ran 487-489 s. Both are longer than a
  Bash call's 10-minute ceiling, and the Python run is longer than
  `run_criteria.py`'s 900 s default per command, so the ship plan had to pass
  `--timeout 1800`.
- **Green items waited on one item.** Polish carried 9 owner items over three
  rounds. In round 0, items 1-8 passed but stayed uncommitted while item 9's
  design question went back to the owner. In round 2, a single flaky
  criterion (`net::ERR_UNSAFE_PORT` on port 1719) took the whole workorder to
  its cap "with one open finding". Every other item had already passed, and
  the fix became a separate workorder followed by a full re-verify.
- **Fixes waited for the whole review.** The ship workorder's finish review
  started after the round in which every ungated criterion passed, returned
  eight findings (F1-F8), and all eight went to the owner as one batch before
  one implementer applied them and one full verify ran.
- **Owner questions blocked unrelated work.** Besides polish round 0, polish
  round 2 was reopened for two owner answers (F1, F6) and paid a whole
  implement-and-verify round. In ship, three owner items became their own
  round while steps 14-17 waited.
- **The browser suites can run side by side.** Each ForgePact panel e2e
  suite starts its own sandbox on an OS-assigned port (`port 0`, re-bound off
  Chromium's restricted ports), with its own temp config and its own browser
  profile, and none of them builds. They share only `panel/dist`, which a Vite
  build empties and rewrites, and the CPU. Two suites assert wall-clock
  budgets (`e2e:polish` expects the next tooltip within 50 ms, and
  `e2e:review` checks a freeze bound), and `e2e:perf` is a timing benchmark.
  Established by reading `panel/tests/lib/browser.mjs`,
  `tests/panel_sandbox_server.py` and `tests/test_satanic_panel.py` on the
  redesign branch; nothing was run.

## What changed

- **Items instead of rounds** (`workorder-rounds.js` 3a/3b). A plan's
  `## Steps` may declare `### Item: <id>` groups, each with `files:` and
  `checks:` (and optional `after:`, `shares:`, `owner:`). Each item flows
  implement, then targeted checks by an independent verifier, then done, the
  moment its files are free. Items on disjoint files run as parallel
  implementers spawned by the engine, and items sharing a file queue in plan
  order. Reviewers read committed ranges pinned to the `HEAD` they start from,
  and each finished reviewer's BLOCKING findings become a fix item at once.
  The `## Acceptance criteria` run once, when nothing is left: the only full
  verify. An item that needs someone parks alone, and a PLAN-DEFECT holds only
  the items its files, links or check commands overlap. Budgets are per item
  (three attempts) under a launch ceiling (agents, and output tokens when
  set). A plan without items runs in rounds exactly as before, and all 83
  existing engine tests pass unchanged.
- **Only the engine fans out agents.** Phase agents have no `Agent` tool, and
  that stays so, because verifier and reviewer independence depends on it.
  Every agent-level parallel step is in the engine (`nextToStart`, the event
  loop, `reviewScopes`). Inside one agent, work runs in parallel as concurrent
  processes: the implementer now starts independent suites with
  `run_in_background` and waits on them with `Monitor`, and
  `run_criteria.py --jobs` does the same for the verifier.
- **Parallel criteria.** `run_criteria.py --jobs N|auto` runs builds first and
  alone. After that it runs at most one whole suite, two browser suites
  (`--browser-jobs`) and the file checks side by side. `e2e:perf`, anything
  that drives the oracle, and any command it does not recognise act as a
  barrier at their place in the plan. The report is unchanged: plan order, the
  serial run's log numbers. A test pins that the parallel output of the
  existing fixture plan equals the serial one line for line. The verifier uses
  it by default, and without `--jobs` the tool runs serially as before.
- **Locks across processes.** `tools/workorder_lock.py` holds an OS file lock
  under the checkout's git dir, which the OS drops when its holder exits.
  `tools/item_commit.py` commits one item's paths under the `commit` lock.
  `run_criteria.py` takes `build` around a build and one of
  `browser-0..browser-<n-1>` around a browser suite, so two items' checks
  together still build one at a time and run at most `n` browser suites.
- `tools/plan_lint.py` checks items (`item-overlap` unless declared,
  `item-no-files`, `item-no-checks`, `item-dup-id`, `item-bad-id`,
  `item-unknown-ref`, `item-cycle`, `items-and-lanes`). `--items-json` prints
  the table the driver passes, and `--known ... --wait S` lets the engine pick
  up items a streaming planner (`planning: streaming`) releases while the
  first ones are already being implemented.

What was tested: the scheduler as pure functions (disjoint items in
parallel, shared-file items serialised in plan order, a parked item not
blocking others, an item parked before it started not blocking its
file-sharers, a fix with unknown files running alone, a PLAN-DEFECT holding
only what it may invalidate). The engine was tested against stub agents that
take a few milliseconds each, so overlap is observable: disjoint items
overlapped, shared-file items never did, the gate ran once and only after the
queue drained, a parked item kept the gate from running, a failed targeted
check retried with its evidence and parked at three attempts, a finding became
a fix that its reviewer re-read, a gate failure became one fix and a second
gate, and a streaming plan's late item was picked up. Mutating the parallel
cap, the file lock or the park check fails these tests.

## Not yet measured

The first plan of items to run for real was `forgepact-dev2-bug-batch`
(2026-09-27), in three launches (rounds 0, 1 and 2). Its row, from
`tools/workorder_speed.py` (§ "Measuring where the pipeline spends its time"
below), against the redesign's:

| | workorder | items | full verifies | launch wall-clock | item implementer minutes, added up | first finding to its fix starting |
|---|---|---|---|---|---|---|
| before | `forgepact-ui-polish` (rounds) | 9 | 3 rounds, a split workorder, 1 re-verify | not recorded | not recorded | no reviewer stream |
| before | `forgepact-ui-ship` (rounds) | 8 fixes | 1 per round | not recorded | not recorded | the whole review, then an owner batch |
| after | `forgepact-dev2-bug-batch` (items, 3 launches) | 8 in the plan, 9 item starts (2 + 2 + 5) | 2, both gate runs of round 2 | 157.1 min (48.4 + 37.3 + 71.4) | 100.5 (32.6 + 14.5 + 53.4, fixers included) | 0.04-5.4 min over 11 fixes, 8 of them under 1 min |

At most 3 items ran at once, against a cap of 4, and no start waited on the
cap. The launch figures come from each launch's `launches` entry; the same
numbers can be read from `py -3 tools/workorder_audit.py --session <id>
--json`: the launch's span (first agent start to last agent end), the item
implementers' wall minutes added up (their sum against the span is the
parallelism bought), the count of `verifier:` gate runs, and each
`fix-implementer`'s start against the end of the reviewer pass that raised
it. The redesign recorded no round times, so this pilot also sets the first
measured baseline. Three things would show the design needs tightening:

- two items whose declared file sets missed a file both edited, which
  `item_commit.py` would then commit with the wrong item or leave out;
- a targeted check failed by another item's half-finished edit, visible as an
  `other_defects` entry naming a file outside the item;
- an e2e wall-clock check (`e2e:polish`'s 50 ms tooltip) failing only when it
  runs beside the Python suite.

`tools/workorder_audit.py` does not yet know the item labels
(`item-implementer:`, `item-verifier:`, `fix-implementer:`,
`<reviewer>:p<k>:`). They parse as ordinary roles in round `n`, so the audit
reads them, but no rule is specific to them yet.

# Re-verifying only what a fix reaches (2026-09-27)

## The question

In the ForgePact UI redesign's ship workorder, the second patch of round 2
found a real panel bug: a used undo toast's resumed timer hid the next toast
early. The fix was one file, `panel/src/lib/enabled-mods-undo.js`, plus one
regression check in `review-fixes.e2e.mjs`. The rules as written sent it to
another full verify, behind a Python suite of about 20 minutes, because
SKILL.md said the verifier "runs every criterion as usual, because nothing
says which criteria a change can reach". The owner said: *"run relevant tests
only if possible"*.

## What was measured

Read from the ship workorder's context file (gitignored, on the machine that
ran it), not from transcripts:

- **The driver chose the criteria by hand.** For a panel JavaScript fix it
  ran the rebuild, `npm test`, the one or two e2e suites that cover the file
  (`e2e:review` 28/28, and `e2e:perf` 26/26 alone because it was the
  suite that had timed out), the oracle replay, and the frozen-file and docs
  criteria. It skipped the full Python run. Its only tests that could see a
  panel change wrap those same npm suites. The recorded scope was criteria
  1-5, 7, 9-11, 16, 18, 19 and 23-25 of the plan's 29, plus `plan_lint`.
- **The same scoping held for the next fix.** The PR review's Restore
  defaults icon fix re-ran `npm test`, `e2e:finish` 14/14, `e2e` 32/32, the
  oracle replay ("817 steps, 0 mismatches") and the two docs criteria.
  Criterion 22 was not re-run.
- **About 40 minutes saved per fix round**, the driver's estimate: the
  Python suite and the e2e suites the fix could not reach.
- **No independence lost.** A fresh verifier still ran every criterion it
  reported. Only the set was smaller.

The gap was that nothing written down said which criteria a change could
reach. `implementer.md` already told a re-entered implementer to re-run
"only what the defect touches". AGENTS.md's "a middle workorder's criteria
run what its change can reach" is about writing a plan's criteria, not about
re-checking them after a fix.

## What changed

- **A reach map on each criterion.** `(reads `<glob>`, ...)` names the files
  whose change can alter the criterion's result. `tools/plan_lint.py` warns
  `no-reads` on a criterion without one, and prints the paths its commands
  mention as a starting point. It warns `reads-nothing` on a glob that
  matches no tracked file. Warnings never fail the lint, so an old plan still
  lints clean.
- **`tools/run_criteria.py --changed-since <ref>`** (`DIR=<ref>` per
  submodule, or `--changed-from <file>` for `round_delta.py delta`'s output)
  and `--failed <k,...>` select the criteria a changed path reaches, plus the
  failed ones, any criterion with no map, and any criterion a selected one
  runs `(after ...)`. It prints the scope, meaning each criterion as `run` or
  `skip` with its reason, before running anything. The selection is a pure
  function (`select`). The runner falls back to every criterion when the
  delta is unknown, and when a changed path is a shared contract:
  `hs-game-sdk/`, `third_party/yytoolkit/`, `.gitmodules`, the selection's own
  code, or the plan's `shared contract:` line.
- **`workorder-rounds.js` (2j)** gives a round's fresh verifier the scoped
  command when the previous verify left every criterion at `pass`, `fail` or
  gated. The bases are the round's own snapshot heads, and `--failed` lists
  the criteria that failed. The verifier reports each criterion's plan
  number (`k`) and each skipped one as `not-selected`. A PASS reached this
  way returns `verifyScope: 'reach'`.
- **Rule text**: SKILL.md Step 4, "Re-verify what the fix reaches", with the
  patch route's verifier bullet changed to match, and Step 5's `PASS
  (scoped)`; verifier.md, "When you re-verify a fix"; planner.md, "Say what
  each criterion reads"; and one line in AGENTS.md § "Spend Each Check Once".
  The full set still runs at the final gate before a push. It also runs when
  the delta is unknown (`round_delta.py` exit 3), when a shared contract
  changed, when a criterion's standing is unknown, or when the verifier
  cannot tell whether the fix reaches a skipped criterion.
- Tests: `tests/test_workorder_plan_tools.py` (`ReachSelectionTests`,
  `ReachRunTests`, `PlanLintReachTests`). The negative control is a change
  outside every criterion's reads, which selects only the failed criteria.
  A change to a file that several criteria declare selects each of them. One
  run goes through a real hub and a submodule. The engine's route and its
  four full-set fallbacks are in `.claude/workflows/workorder-rounds.test.mjs`.

## Not yet measured

No plan has carried a reach map yet, so the saving above comes from one
hand-scoped workorder, not from the tool. Next time, measure the criteria a
scoped verify ran against the plan's total, and the wall time per fix round
against a full verify. One outcome would mean a map was too narrow: a
criterion that a scoped verify skipped and the final gate then failed. When
that happens, record the criterion, its `(reads ...)` and the path that
reached it.

# Checking the panel's browser suites once (2026-09-27)

## The question

After the redesign merged, ForgePact's full parallel Python run took about
19 minutes, although all but two of its modules finished in the first
minute. A verify that ran the panel's browser suites as their own criteria
and then the full Python suite ran every one of those suites twice. The
owner's rule from 2026-09-26 applies: *"If some checks can be done once for
2 things it's better than checking twice after each change"*.

## What was measured

On one 12-logical-core machine, with `panel/dist` built so every browser
suite ran. Every run was OK.

| run | tests | wall |
|---|---|---|
| serial, `py -3 -m unittest discover -s tests` (`510f21e`) | 1635 | 1292 s |
| serial, `forgepact-release.yml` Contract tests (`510f21e`, run 36307787871) | 1635 | 1449 s |
| parallel, before the split (`0f613b3`) | 1642 | 1143 s |
| parallel, split, browser cap 2 | 1650 | 778 s |
| parallel, split, browser cap 3 | 1650 | 723 s |
| parallel, split, browser cap 4 (the default) | 1650 | 650 s |
| parallel, split, the browser modules excluded (two runs) | 1643 | 55.5 s |

- **One module was most of the run.** `tools/run_tests_parallel.py`
  parallelises by module, and `test_panel_oracle` ran the oracle replay and
  five e2e suites back to back: 735 s on one worker. `test_panel_perf`
  (`e2e:perf`, `PARALLEL_EXCLUSIVE`) then ran alone for 396 s.
- **At a cap of 4 the browser suites cost one replay.** Split into one module
  each, the six took about 259 s side by side, which is `oracle:replay` alone
  (259 s at every cap). The others slowed under contention (polish 198 s at a
  cap of 3 and 244 s at 4, motion 151 s at 3 and 158 s at 4), but none
  failed. So a higher cap cannot help.
- **`e2e:perf` is now the floor.** Its 391-395 s runs alone by design, and
  its budgets do not change, so the full parallel run stays at about 11
  minutes.
- The serial number was not re-measured after the split. The split does not
  change what a serial run executes, so the baseline and the CI run stand for
  it.

## What changed

- ForgePact: one module per browser suite (`test_panel_oracle_replay`,
  `test_panel_e2e*`), sharing `tests/panel_browser.py`'s skip check and npm
  helper, each in `PARALLEL_GROUP = "panel-browser"`, which defaults to a cap
  of 4. `run_tests_parallel.py --exclude-module` leaves named modules out,
  says which, and checks the id set against discovery less those modules.
- `.claude/agents/planner.md` § "Spend each check once" ("Run each suite once
  per verify") and SKILL.md rule 1: a plan whose criteria run the panel's
  browser suites directly runs its full Python suite with `--exclude-module`
  for the modules that wrap them. Release CI still runs everything serially. (Later the same day, `forgepact-release.yml` was split to use this runner's `--only-group`/`--skip-group` in two parallel jobs, and now leaves `test_panel_perf` to the local run; see `docs/submodules/ForgePact/instructions.md`, "The build half (forgepact-release.yml)".)

## Not yet measured

Each cap was measured once. If `e2e:polish`'s 50 ms tooltip check or another
wall-clock assertion fails at a cap of 4 without a code cause, lower the
default to 3 (723 s) rather than retrying. Checked, not changed:
`run_criteria.py` classifies `py -3 -m unittest tests.test_panel_e2e_gems`
as `test`, not `browser`, because `\be2e\b` does not match inside
`test_panel_e2e_gems`, and `tests.test_panel_oracle_replay` as `exclusive`
(safe, but alone). A criterion that names these modules directly should say
`(class browser)`.

# Why the ForgePact UI redesign took 60 hours (2026-09-27)

## The question

With the redesign merged (hub PR #244, ForgePact PR #100), the owner asked
why it took so long, and whether the fixes already made (the sections above)
cover every cause. Those sections were written from the 14 plan and context
files, which record dates only. This one adds the wall clock, read from the
driver's and every subagent's transcript timestamps, and the git and CI
history.

## What was measured

- **The span**: first commit 09-24 20:11 UTC to both merges 09-27 08:56,
  60.75 hours, driven from one session (`039722c8`) through 230 subagents
  and 32 workflow launches, at $582 list price.
- **Where it went**: 40.0 h (66%) with at least one subagent running; 19.1 h
  (31%) with a question to the owner open and nothing running, 15.2 h of it
  in four gaps of over two hours (380, 273, 256 and 111 minutes); 1.7 h of
  the driver alone. Two or more agents ran at once for only 6.8 h (11%).
- **Agent time**: implementers 43 runs, 20.2 wall-hours; the full verify 22
  runs, 9.7 h at 15-55 minutes each; planners 10 plans, 13 replans and 13
  amendments. Of the 32 launches, 11 passed, 14 ended `PLAN-DEFECT` (599
  minutes), 4 `STATE-LOST` (145 minutes) and 2 `CAP`.
- **GitHub was not the cost**: no CI test or build workflow ran on either
  branch; the one AI review took 9-15 minutes and its findings were fixed
  within 15 minutes. `origin/main` was merged into the branch six times.
- **Causes, from the context Logs** (about 75 events):
  - criteria that could never pass, about 15;
  - the owner's own scope or design changing mid-stream, about 16, which
    the cap and the tier ladder counted as failures four times;
  - the Figma export disagreeing with the panel, 7, found only at restyle;
  - plans written before their inputs existed, about 15 replans with no
    implementer between them;
  - flakes, 4;
  - non-blocking docs findings carried from one workorder to the next, 9.
- **The four STATE-LOSTs lost nothing.** Three flagged a multi-line
  `decisions in force:` entry whose continuation lines the scribe reported
  indented differently before and after its Edit; one flagged `round base:
  <none yet>` reported back as `&lt;none yet&gt;`.
- **The driver's context**: 504 of its 697 turns ran above 300K tokens,
  peaking at 966K.

Covered already (sections above, none yet run on a real workorder): the
repeated full verify (reach-scoped re-verify, `--jobs`, one verify for
changes ready together), main merges as workorders (merge in place), the
flake (fixed in the round), pinned heads (`pinned-sha`), and the serial
chain (items).

## What changed

- **A question never idles the pipeline** (SKILL.md rule 8, AGENTS.md):
  start what the answer cannot change before asking, spin off an
  out-of-scope bug, apply the default to a reversible choice.
- **Owner scope is not a failure** (SKILL.md Step 4):
  - `tools/amend_check.py` prints `SCOPE:` and exits 0 when a change that
    would otherwise be a replan follows an `owner, <date>:` decision the
    context gained since `save`. A change within the amendment limits
    prints `AMENDMENT` as before.
  - `workorder-rounds.js` adds State's `scope rounds:` to the cap, at most 3.
  - `tools/workorder_audit.py` R25 fails a `SCOPE:` verdict with no owner
    message behind it.
- **Plan when the inputs exist** (planner.md, SKILL.md Step 1): a dependent
  plan is `status: DRAFT` with `depends on:`, and `plan_lint` refuses it
  (`plan-draft`).
- **Design review first** (SKILL.md rule 9, planner.md): detector and
  critique on the comps, the finish reviewer after the first restyle round,
  an export structure check when the export is made, and class-wide checks
  for design fixes.
- **Two more lint rules**: `eof-slice` and `merge-walk`. Over the redesign's
  14 plans they match 15 and 2 criteria respectively.
- **Timeouts**: `run_criteria.py` gives a `suite` or `exclusive` command
  1800 s by default (the Python suite ran 1,037-1,302 s against the old
  900 s).
- **STATE-LOST compares words, not layout**: whitespace runs and HTML
  entities are normalised before an entry counts as lost.
- **Round headings carry their start time**: `round_delta.py snapshot`
  records and prints `taken_utc`, and the engine writes `### Round <n>
  (started <time>)`. Round wall time and owner waits can then be read from
  the Log next time.
- **A fresh driver session** is offered at any workorder boundary once the
  driver is past about 300K tokens, not only after a live session.

## Not yet measured

None of this has run on a real workorder. For the next multi-workorder
feature, compare against this section's rows:
- hours with a question open and nothing running;
- `PLAN-DEFECT` launches and replans before round 0;
- cap hits on owner scope;
- STATE-LOST stops;
- the share of wall time with two or more agents running.

A `SCOPE:` verdict that R25 accepted but which reads as a failed plan would
mean the owner-line test is too loose.

Not done here:
- The export structure check itself belongs in ForgePact's
  `design-match.mjs`, a separate change in that repository.
- Landing behaviour-identical foundations on main early, so a long branch
  does not have to port main's new features (the redesign's `main-merge` and
  `main-merge-3` did), was considered and not made a rule. It is a
  feature-planning choice to weigh each time.

# Measuring where the pipeline spends its time (2026-09-27)

## The question

The owner asked for `/workorder` to go faster without weakening any check,
and for the measurement to come first: a goal would be dropped or shrunk
where the numbers showed its problem was gone. The five goals were a
re-runnable report, background criteria runs, owner questions that carry a
default, a higher parallel cap, and consultations and amendments inside the
launch. Until then, "where did the time go" had been answered by throwaway
transcript scripts, run once for a study of 22 sessions. The question for
this section is what those sessions and the first real plan of items, the
ForgePact bug batch, spent their time on, and which goals that leaves.

## What was measured

`tools/workorder_speed.py` now answers it. It reuses
`tools/workorder_audit.py`'s parser and session discovery, opens files for
reading only, and its module docstring defines each figure. `--until` drops
every record after a time, so a snapshot of a session that was still running
can be reproduced once it has finished. It was run on:

- **the baseline**: the study's 22 sessions in four project directories, up
  to 2026-09-27T21:30:00Z;
- **the snapshot**: the bug batch (`forgepact-dev2-bug-batch`, driver session
  `a7e6f66d`) at 2026-09-27T21:21:31Z, while a fifth launch
  (`forgepact-pet-loot-stuck`) was still running. The workorder-speedup plan
  was scoped from this snapshot;
- **the fresh run**: the same session read at 2026-09-27T22:12Z, its last
  event at 22:12:10Z, still running.

| measure | baseline (22 sessions) | bug batch, snapshot | bug batch, fresh |
|---|---|---|---|
| span / busy minutes (busy leaves out gaps of 2 h or more with no agent) | 16,171.9 / 10,071.1 | 410.1 / 410.1 | 460.7 / 460.7 |
| agent minutes, added up | 9,663.1 | 601.9 | 709.8 |
| concurrency (agent minutes / busy) | 0.96 | 1.47 | 1.54 |
| busy time with one agent / with two or more | 63% / 13% | 61% / 30% | 58% / 32% |
| `run_criteria` calls, killed at the limit, longest, longest `--item` | 253, 25, 605.3 s, none | 37, 0, 369.5 s, 61.4 s | 45, 0, 369.5 s, 79.1 s |
| owner waits: count, minutes, largest | 80, 4,975.4 (3,912.6 in gaps over 2 h); 1,062.9, 552.8, 444.0 | 3, 23.1; 16.2 | 4, 25.9; 16.2 |
| verifies: full / reach / item | 126 / 0 / 0 | 2 / 0 / 9 | 2 / 0 / 11 |
| items: most at once, starts that waited on the cap | none ran | 3, 0 | 3, 0 |
| implementers whose check failed and who then edited | 83 of the 144 that ran one (58%) | 8 of 20 (40%) | 10 of 26 (38%) |
| amendments / replans / consultations | 23 / 32 / 1 | 5 / 0 / 0 | 7 / 0 / 0 |

In the snapshot, the minutes with only one kind of agent running were:
planner 102.7 (the plan and a Ghidra research run), live-operator 81.4,
amendment 20.9, verifier 17.9, reviewer 9.9, record 9.5 and implementer 6.6.

Three readings from the bug batch's timeline decided the scope:

- **An amendment waited 41 minutes for a driver turn.** Item
  `research-build` returned `PLAN-DEFECT` at 15:47:44Z. Its launch kept
  running reviewers and fixes until 16:22:20Z, about 30 minutes after its
  last item, and only then could the driver amend the plan (16:23:44Z to
  16:26:14Z) and relaunch it (16:28:32Z).
- **Its three `owner:` items waited on a live capture, not on a person's
  decision.**
- **A question with a default was still asked.** At 71.3 minutes the owner
  answered one the driver put while a launch ran: *"Don't ask me, you can
  reserve live spot for hs drive mcp"*.

An owner wait is a gap of at least 120 s in the driver's records, with no
subagent running at its midpoint, that ends in a message the owner typed or
an `AskUserQuestion` answer. The study quoted 699, 453 and 401 minutes for
its largest waits. This definition gives 1,062.9, 552.8 and 444.0, and where
the study cut its gaps is not known. The baseline's `run_criteria` counts
are the tool's (any shell call naming `run_criteria`), and differ slightly
from the study's 24 of 237.

To re-run it (the first two reproduce the figures above; the others read
sessions that were still running, so their numbers grow):

```
py -3 tools/workorder_speed.py --until 2026-09-27T21:30:00Z --project-dir "C:/Users/stann/.claude/projects/C--Users-stann-Projects-hero-siege-offline-toolkit--claude-worktrees-hero-siege-issue-121-fcc1fd" --project-dir "C:/Users/stann/.claude/projects/C--Users-stann-Projects-hero-siege-offline-toolkit--claude-worktrees-workorder-parallelization-2d890c" --project-dir "C:/Users/stann/.claude/projects/C--Users-stann-Projects-hero-siege-offline-toolkit--claude-worktrees-forgepact-issue-52-0d1b54" --project-dir "C:/Users/stann/.claude/projects/C--Users-stann-Projects-hero-siege-offline-toolkit--claude-worktrees-hero-siege-offline-toolkit-72f6fd" --json
py -3 tools/workorder_speed.py --until 2026-09-27T21:21:31Z --transcript "C:/Users/stann/.claude/projects/C--Users-stann-Projects-hero-siege-offline-toolkit--claude-worktrees-bridge-cse-01BPATbZGkDAktH2cu2P7ZZC/a7e6f66d-c830-5af9-a8a0-f7f95fe846b7.jsonl" --plan "C:/Users/stann/Projects/hero-siege-offline-toolkit/.claude/worktrees/bridge-cse_01BPATbZGkDAktH2cu2P7ZZC/.claude/workorders/forgepact-dev2-bug-batch-plan.md" --json
py -3 tools/workorder_speed.py --transcript "C:/Users/stann/.claude/projects/C--Users-stann-Projects-hero-siege-offline-toolkit--claude-worktrees-bridge-cse-01BPATbZGkDAktH2cu2P7ZZC/a7e6f66d-c830-5af9-a8a0-f7f95fe846b7.jsonl" --plan "C:/Users/stann/Projects/hero-siege-offline-toolkit/.claude/worktrees/bridge-cse_01BPATbZGkDAktH2cu2P7ZZC/.claude/workorders/forgepact-dev2-bug-batch-plan.md" --json
py -3 tools/workorder_speed.py --transcript "C:/Users/stann/.claude/projects/C--Users-stann-Projects-hero-siege-offline-toolkit--claude-worktrees-hero-siege-issue-121-fcc1fd/74b6b5dd-a6bc-4c71-883a-0c7cf47aab9d.jsonl" --json
```

The last is `forgepact-issue-14-player-build`, the lanes table's before row.
The lanes table's after rows and the items table's after row (§ "Lanes" and
§ "Streamed items" above) come from the baseline's and the fresh run's
`lanes` and `launches` entries.

## What changed

Each goal kept what the snapshot still showed a problem for. The workorder's
gate re-checks every rule against a fresh run of the report, and a rule that
stops holding fails with a message naming its goal. That failure means the
scope is wrong and the plan must change; it is not a code defect.

- **Goal 1, the report: in full.** `tools/workorder_speed.py`, above.
- **Goal 2, background runs: shrunk to whole-tree runs.** No `run_criteria`
  call in the bug batch reached the 10-minute limit: the whole-tree gate took
  6.2 minutes at most, and an item check 1.0 minute. So only whole-tree runs
  go to the background: the rounds verifier, the reach re-verify, the items
  gate, and an implementer's run of the plan's whole criteria set. Each run
  keeps `<out>/status.json` and `<out>/report.txt`, and `run_criteria.py
  --status <out> --wait 220` polls it (exit 0 finished, 3 running, 4 stale, 2
  no status file). No wait can exceed 220 s, which keeps every poll under
  R5's 240-second limit. The UI redesign's suite, which ran 1,037-1,302 s in
  one command, is why the protection is kept at all. Item checks
  (`--item`) stay in the foreground. Rule: the fresh report's
  `run_criteria.item_max_seconds` is under 300 (79.1 s).
- **Goal 3, owner defaults: in full.** Every `owner:` item and every entry of
  `## Needs human judgement` carries `default:` and `reversible: yes|no`, and
  `tools/plan_lint.py` refuses one without them (`owner-no-default`,
  `owner-no-reversible`, `owner-reversible-no-default`). A legal or
  decompile-output question can never be defaulted (`owner-legal-default`).
  The engine runs an unanswered reversible item on its default and lists it
  under `defaulted` with its commits and how to undo it. Every result that
  waits on a person lists, under `unblocked`, the parked work that does not
  wait on them. The bug batch waited only 23 minutes, because the owner stayed
  at the keyboard through two live sessions. The baseline waited 4,975, and
  the 71.3-minute message shows a question with a default still being asked.
  There is no rule for this goal.
- **Goal 4, the parallel cap: shrunk to validation.** At most 3 items ran
  at once, against a cap of 4, and no start waited on it. So the default
  stays 4, named `DEFAULT_MAX_PARALLEL` in `workorder-rounds.js`, and a
  `maxParallel` that is not a whole number from 1 to 16 is refused with
  `BAD-ARGS`. Raising it to min(8, CPUs−2) was rejected, and the engine
  cannot see the CPU count anyway. Rule: the fresh report's
  `items.queued_behind_cap` is 0.
- **Goal 5: amendments moved into the launch, consultations stay with the
  driver.** An item implementer's, a fixer's or a rounds implementer's
  `PLAN-DEFECT` whose `CORRECTION:` is not `none` is amended inside the
  launch: `amend-save:<id>:r<n>`, a planner labelled `amendment: <slug>
  <id>:r<n>`, then `amend-check:<id>:r<n>`. Only `AMENDMENT` re-runs the work.
  One amendment runs at a time, and a second `PLAN-DEFECT` after one is a
  replan. The audit's R24 and R11 accept the save and check calls from the
  same launch. There were no consultations in the bug batch and one
  (4.7 minutes) in 22 sessions, and moving them would need the engine to
  resume an implementer, which a workflow script cannot do. Rule: the fresh
  report's `routes.consultations` is 0.

The reviewer tail after the last item (about 30 minutes in the bug batch's
first launch) is recorded here and nothing was changed for it.

## Not yet measured

None of goals 2 to 5 has run on a real workorder. On the next plan of items,
compare with this section's rows:

- the time from an item's `PLAN-DEFECT` to its re-run, against the
  41 minutes above, and `routes.amendments_in_workflow`;
- owner-wait minutes, and how many owner items ran on their defaults;
- whether a whole-tree verify polled in the background ever met R5 or the
  Bash limit;
- `items.queued_behind_cap`, which reopens goal 4 the first time it is not
  0.

The implementers' check catch rate (38-58% above) is measured only, and
nothing here changes their own check run. What the joins cost against the
lanes' saving (§ "Lanes") is not established.

# The full suite once, before the pull request; the diff after a write (2026-10-02)

## The question

The owner asked for two more cuts: *"full suite runs shouldnt be run so
frequently. it should be reserved to the last step before the pr. during
development only relevant subset should be run"*, and, since agents *"seem to
spend lots of times on reads"* after each write, *"make sure only difference
or relevant things are read after every write instead"*.

## What was measured

Over the 491 subagent transcripts of the 14 days before (`agentType` from
each `.meta.json`):

- Only a fix round after an otherwise clean verify was scoped (the
  2026-09-27 section above). Every round 0 and every items gate ran the full
  set, and the verifier's step 3 ran the hub's root suite on top of it.
- Reads after writes did not go where expected. Whole-file re-reads of a
  file the same agent had just edited were rare: at most one per implementer
  or planner, none over two. The volume was elsewhere. The scribe, which
  pastes one Log entry and a few State lines, read both workorder files
  whole every round: 13 MB over 228 runs, 69 KB a run. Fix-round
  implementers, fresh agents with no memory of round 0, averaged 22 reads and
  134 KB each; 105 of their reads were the whole plan and 253 were ranges of
  the context file, against 90 `section.py` calls.

## What changed

- `run_criteria.py --dev` runs every criterion except a whole suite
  (`unittest discover`, `run_tests_parallel.py`, a bare `pytest`) and any
  marked `(final)`; a reach run (`--changed-since`) defers the same ones
  unless `--failed` names them. `workorder-rounds.js` gives a launch's first
  verify and the items gate `--dev`, counts a deferred criterion as a known
  standing so the next fix round can still go by reach, and reports
  `verifyScope: 'dev'` with a note to run the full set at the final gate.
  `fullVerify: true` makes a launch the final gate. The verifier skips its
  step-3 root suite on any development verify. A first verify is `--dev`
  rather than a reach selection on purpose: a criterion about a file the
  change forgot to touch would not be selected by reach, and would first
  fail at the final gate.
- The scribe reads the `## State` range and the Log's last 30 lines through
  `Grep` and ranged `Read`s; it now has `Grep`, still no shell. A re-entered
  implementer is told to read the failed criteria, what the evidence names
  and `git diff <base> -- <path>` for what earlier rounds changed, not the
  plan or the files whole. A replanning planner reads the Log since its last
  plan, not all of it, and no agent reads back a file it just edited.
- `tools/workorder_audit.py` R26 fails an implementer or planner with more
  than two whole-file reads of files it wrote.

## Not yet measured

- How much a development verify saves per round. It is the suite's own
  time (ForgePact's Python suite 11-17 minutes in the UI redesign, the hub's
  150-170 s) for each round before the final gate, if the plan carries
  targeted criteria beside it.
- What deferring finds late: a regression only a whole suite catches now
  shows at the final gate. Count the final-gate failures a development
  verify would have caught.
- The scribe's and the fix-round implementers' read volume after the
  change, against 69 KB and 134 KB a run above. R26 is calibrated to fail
  none of the 527 implementer and planner runs measured, so it guards
  against a regression rather than measuring this one.

# A build is re-run after a fix lands on its sources (2026-10-02)

## The question

In streamed items, a build item (`build-dev`, check `cd ForgePact && cmd //c
"plugin_build\build.bat dev"`) was marked done the moment its check passed.
Reviewers keep reading commits after that, and their `BLOCKING` findings
become fix items that commit to the very sources the build compiled. Nothing
sent the build back, so a launch could return `PARKED` with
`build-dev=done` and a DLL older than the last fix.

## What was measured

In workorder `forgepact-124-pet-relics` on 2026-10-02 this happened three
times in one day. Each time the DLL was a few minutes older than the fix
commit: 17:50 against 17:53, 18:33 against 18:36, 19:33 against 19:35. Each
one cost the driver a hand edit of State (`build-dev=held`) and a relaunch.

## What changed

- `plan_lint.py --items-json` adds `build_reads` to every item: the
  `(reads ...)` globs of its `build`/`exclusive` checks (a declared
  `(class ...)`, or a command `run_criteria.py` recognises as a build or a
  barrier; a command it calls `exclusive` only because it does not know it
  does not count). A build check that declares no `(reads ...)` gives `["*"]`.
  An item with no such check gives `[]` and is scheduled as before.
- `workorder-rounds.js` will not start an item with `build_reads` while a fix
  that may land on those globs is queued or running, or while any other item
  editing them runs. Waiting for a plan item that is only pending is left to
  `after:`. A fix with unknown files no longer queues behind a build that is
  waiting for it, so the two cannot deadlock.
- When any other item or fix commits a path those globs cover, a done build
  goes back to pending, and a running one goes back as soon as it finishes.
  Its implementer is told which commit and paths made it stale, its attempt
  budget starts over, and its result row carries `rebuilds`. A sixth re-run
  parks it instead, so two builds that commit into what the other reads
  cannot loop. This also
  applies to a build that State's `items:` line carried in as done from an
  earlier launch.
- The planner's item rules ask for `(reads ...)` on a build check.
  `workorder-rounds.test.mjs` replays the sequence with the fix landing after
  the build and during it, plus a relaunch. With the change switched off,
  five of the new tests fail.

## Not yet measured

- How many rebuilds a real launch pays. It is one build per fix that lands
  on the build's sources after the build ran. A build check with no
  `(reads ...)` pays one for every commit, so watch the `rebuilds` counts in
  the next plans of items.
- Whether holding a build behind an overlapping running item costs more
  wall time than it saves in builds that would have gone stale.
