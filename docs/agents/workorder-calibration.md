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
of `forgepact-issue-14-player-build`, from the same tool's table. Which
workorder provides the after row is the owner's choice, still open. The
table stays `not yet measured` until then, and the plan's gate
`measured: complete` is set only when both rows hold numbers.

| | workorder | round 0 implement wall time | implementer minutes, added up |
|---|---|---|---|
| before | `forgepact-issue-14-player-build`, one implementer | not yet measured | not yet measured |
| after | first real laned workorder (to be chosen) | not yet measured | not yet measured |

Not yet observed: lanes have not run on a real workorder. The fan-out, the
join, the stop marker and the audit summary are tested against stub agents
and synthetic transcripts only. Whether a real lane keeps to its file set,
checks the marker before each step and leaves git alone is not established,
and R23 is the instrument that will show it.
