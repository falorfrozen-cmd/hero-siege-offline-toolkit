# /workorder: model tiers, and why

Read this when choosing or changing a tier, or when a cost question comes up. `SKILL.md` § "Model tiers" keeps the spawn table every launch needs.

Set in each agent's frontmatter, with an `effort:` beside every tier that
takes one: `planner` opus/high, `implementer` opus/high, `consultant`
opus/xhigh, `instrument-blindness-reviewer` opus/high, the other reviewers and
`live-operator` opus/medium, `verifier` haiku/medium, `scribe` haiku/low.
Override the model for one run by passing `model` on the Agent call.
Effort has no per-call override on the Agent tool, which is why it is pinned
— an agent without one inherits whatever the session runs at.

**Effort variants choose effort per spawn.** An agent's
`effort-variants:` line lists the other levels /workorder runs it at, and
`py -3 tools/sync_agent_tooling.py` writes one `<agent>-<level>.md` for each,
same body, own `name:` and `effort:`; `tests/test_agent_tooling_sync.py`
fails a variant that drifted from its source. Today: `planner-medium`,
`planner-xhigh`, `planner-max`, `implementer-medium`, `consultant-max`.
Spawn the variant by name, in a driver's `Agent` call and in
`workorder-rounds.js` alike. A Workflow `agent()` call does accept an
`effort` option, but whether it beats the agent's own pinned `effort:` is
not documented, and a transcript records no effort level at all, so the
name is the one spelling that both runs at that effort and lets
`workorder_audit.py` see it (`split_effort_variant`; `--calibrate` reports
per role, model *and* effort). To add a level, add it to the source's
`effort-variants:`, re-run the sync, and name it in a table here.



**The driver is the session itself**, so no frontmatter pins it: run the
session that runs /workorder on `opus` at `medium` effort, and raise it to
`high` for a session whose product is the driver's own judgement (triaging a
bug batch into items, deciding how to split a plan). Drivers were 30% of the
calibration set's spend over hundreds of turns, many above 300K tokens, and
effort is paid on every one of them. Their job is routing by written rules;
the hard calls already go to `consultant` and replans to the planner, and the
driver failures the audit recorded (R10) were discipline, not reasoning,
which more effort does not fix. Chosen 2026-10-06 (#436), not measured.

**Fable left this pipeline on 2026-10-05**, when the owner's license
stopped carrying it. Every place it held — the two hard triage rows, the
second replan, the consultant on a hard row — now holds the `opus` variant
one or two effort levels up, per the table above. Its price row below
stays, because `workorder_audit.py` still prices older transcripts that
ran it.

**Where Opus 5.5 fits (2026-09-22).** `opus` resolves to Claude Opus 5.5; it
did so already for the last sessions of the calibration set, with no file
changed. What it changes is the price, and price is what the tiers were
chosen by. List prices per million tokens (input / output / cache read):

| Model | In | Out | Cache read |
|---|---|---|---|
| Fable 5.1 (`fable`) | $10 | $50 | $0.25 |
| Opus 5.5 (`opus`) | $4 | $20 | $0.20 |
| Opus 5 (was `opus`) | $5 | $25 | $0.50 |
| Sonnet 5.5 (`sonnet`) | $2 | $10 | $0.20 |
| Sonnet 5 (was `sonnet`) | $2 | $10 | $0.20 |
| Haiku 5.5 (`haiku`), prompt ≤ 100K tokens | $0.10 | $0.50 | $0.01 |
| Haiku 5.5 (`haiku`), prompt > 100K tokens | $0.50 | $2.50 | $0.05 |
| Haiku 4.5 (was `haiku`) | $1 | $5 | $0.10 |

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
  cheaper. Until 2026-10-05 `fable` kept the two hard triage rows plus the
  second replan; those are now `planner-xhigh` and `planner-max`.
- **amendment planner → always `planner-medium`, with `model: opus` passed explicitly.**
  An amendment planner always runs as planner-medium on opus, never escalated.
  It applies one correction someone already stated, so the replan ladder
  does not reach it: spawn it as `planner-medium` whatever `planner-tier=`
  the State records. In the 18 sessions after 2026-10-02 one amendment ran
  fable because the driver carried an escalated tier over; fable planners
  averaged 8.49M input tokens a run there. `workorder_audit.py` R27
  (`amendment-tier`) fails an `amendment:` planner whose transcript ran
  fable or that ran as `planner-xhigh`/`planner-max`, and
  `workorder-rounds.js` spawns its own amendments as `planner-medium` with
  `model: 'opus'`.
- **Reviewers, live-operator and the docs row → `opus`/`medium`
  (2026-10-06, #436).** Until then `sdk-contract-reviewer`,
  `tauri-command-reviewer`, `docs-sync-reviewer`, `decompile-output-guard`
  and `live-operator` ran sonnet/high, and the docs triage row's implementer
  ran `sonnet`. Artificial Analysis's Intelligence Index against cost per
  task (read 2026-10-06) puts Opus 5.5 ahead of Sonnet 5.5 at every effort
  level for about the same price: Opus medium about 51 at $1.40 a task,
  Sonnet high about 47 at $1.10, Sonnet xhigh about 52 at $2.75 against Opus
  high's 53.5 at $1.85. That benchmark prices mostly output and thinking;
  here 92-99% of tokens are cache reads at $0.20 on both, so the model step
  costs less still, and effort is what moves the bill, hence `medium`
  rather than the `high` they had. On the calibration set's tokens Opus 5.5
  costs the reviewers about 1.2× what Sonnet did. No reviewer finding was
  ever measured as missed on `sonnet`, so this is a capability bet chosen
  from a benchmark, not a measured fix; `--calibrate` will say whether it
  holds.
- **verifier and scribe stay `haiku`, now with an effort pinned
  (2026-10-08).** They run commands and paste text. Haiku 5.5 (released
  2026-10-07) honours `effort` where Haiku 4.5 ignored it, so an unpinned
  one would run at the driver's level: `verifier` is pinned `medium`
  (Haiku 5.5's own default; a false verdict costs a round, and at about
  $0.02 a run the step down to `low` saves nothing worth that), `scribe`
  `low` (it pastes precomputed text). Haiku 5.5 bills a turn whose prompt
  is over 100K tokens at 5×, and both stay under it: on 87 sessions since
  2026-09-22 the verifier's p90 prompt was 64K with no turn over 100K, the
  scribe's 70K with 1%. Repriced on those tokens a verifier run costs
  about $0.02 against $0.55 on Opus 5.5. Not moved to Haiku: the
  reviewers, live-operator, planner and implementer. Artificial
  Analysis (read 2026-10-08) puts Haiku 5.5's best Coding Agent Index (41,
  at `xhigh`; `max` scores 36 at four times the cost) below Sonnet 5.5 at
  `low` (42), and its Intelligence Index at `xhigh` (41) well below Opus
  5.5 at `medium` (51); those roles' prompts also sit mostly over 100K
  (implementer and planner 67% of turns). The `haiku` alias still
  resolved to Haiku 4.5 on 2026-10-07; it moves by itself.
- **Effort.** Opus 5.5 defaults to `medium` and thinks more per turn than
  Opus 5 at the same level; `high` is pinned for the phases that carry long
  agentic work and `xhigh` for the one narrow question `consultant` answers.
  `medium` is used where the correction is already written (amendments,
  patch rounds) or the change is docs only, and `max` only where cheaper
  reasoning has failed twice. None of these levels is measured yet:
  `tools/workorder_audit.py --calibrate` reports per role, model *and*
  effort, so the next recalibration says whether they hold.

`tools/workorder_audit.py` prices every transcript at these rates
(`MODEL_PRICES`), so a report's cost line tracks a tier change without anyone
redoing this arithmetic.

**Tier aliases, not pinned version IDs.** `opus` names the tier, not a
version. Pinning `claude-opus-5` across eight files buys reproducibility this
pipeline doesn't need (a broken model fails a *test*, not a review) and costs
a stale-ID sweep every generation — not the `*Rva*` case from `AGENTS.md`,
since an alias is a documented moving pointer, not a silently-drifted
constant.

**When to reach for `planner-xhigh` or `consultant-max` yourself,** beyond the
automatic escalation above (these were the reasons to reach for `fable`):

- The plan must establish an **unknown** game mechanism, not verify a
  suspected one — the "which of 34 candidates does X" shape, where a wrong
  mechanism model has cost whole sessions rather than one round.
- The change falls in the class `AGENTS.md` § "Don't Suspend the Game's Own
  Runtime" warns about — the failure mode inverts, and the blast radius is the
  player's session.

Not on a routine change, or the implementer or a reviewer — those run at high
volume, where more thinking per turn is real money for no measured gain —
and not as the default planner, which is 22% of spend already.
