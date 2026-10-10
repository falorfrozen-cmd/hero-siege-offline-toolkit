# /workorder: amend, or replan; owner scope

Read this when a `PLAN-DEFECT` reaches you (Step 2 or Step 4), or when the owner changes the work. It is part of `SKILL.md`, moved out because a launch now runs most amendments itself.

## Amend, or replan

**Amend, or replan.** First decide whether this defect needs a replan at
all. It does not when the evidence already names what is wrong *and*
states the correction: the implementer's `CORRECTION:` line, or a
reviewer's `plan_defect` finding carrying a `fix`. Typical cases are a
criterion's command or anchor, a path that moved, or one wrong fact in
`## Context`. Then it is an **amendment**:

1. `py -3 tools/amend_check.py save <plan> <context>`;
2. spawn `planner-medium` fresh with `model: opus`, with the description
   `amendment: <slug> <what>` and the correction verbatim (planner.md "When
   you are spawned as an amendment").
   An amendment planner always runs as planner-medium on opus, never escalated.
   That holds whatever `planner-tier=` the State records and whatever tier
   the last replan ran at: an amendment applies one stated correction, and
   the escalation ladder (`SKILL.md` Step 2) is for replans. `tools/workorder_audit.py`
   R27 fails an `amendment:` planner whose transcript ran fable, or that
   ran as `planner-xhigh` or `planner-max`;
3. `py -3 tools/amend_check.py check <plan> <context>` once it returns.

Exit 0 (`AMENDMENT`) means Goal, Out of scope and Needs human judgement are
untouched, no section came or went, and at most 20 lines changed outside
`## State` and `## Log`. The amendment is then not a replan: it does not
count toward the replan cap (`SKILL.md` Step 2) and does not move the next replan up a tier.
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

## Owner scope is not a failure

**Owner scope is not a failure.** A round or a plan change that exists only
because the owner added or changed the work is the owner deciding, not the
pipeline failing, and it spends neither the cap nor the tier ladder:

- **A plan change:** run `tools/amend_check.py save`, *then* record the
  owner's answer under `### Decisions` as `owner, <YYYY-MM-DD>: "<their
  words>"`, then spawn the planner (labelled `amendment: <slug> owner
  scope ...`, as `planner-medium` with `model: opus`), then `check`.
  An amendment planner always runs as planner-medium on opus, never escalated.
  Never pass the workorder's escalated `planner-tier=` here: the one fable
  amendment measured (forgepact-74, 2026-10-02) came by this route, and R27
  now fails it, and an amendment run as `planner-xhigh` or `planner-max`. When the change would otherwise be a replan
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
