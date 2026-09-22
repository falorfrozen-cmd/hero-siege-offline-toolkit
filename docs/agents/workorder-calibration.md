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
