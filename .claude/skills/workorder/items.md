# /workorder: a plan of items

Read this only when `plan_lint.py --items-json` (or `--launch-args`) printed items. It is part of `SKILL.md`, moved out because most workorders never take this path.

## Step 2 for items

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
  [`amendments.md`](amendments.md) does it: `amend_check.py save` through
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
- `ADVICE-NEEDED` → `SKILL.md` "Consultation", the answer under `### Decisions`,
  then relaunch.
- `PLAN-DEFECT` → [`amendments.md`](amendments.md), for that item only: tell the
  planner which item it is. An item that carries `replan` (the launch tried
  its amendment, or its `CORRECTION:` was `none`; the Log's `amendments`
  list says why) is a replan, counted and escalated: do not amend it a
  second time. Otherwise (no `CORRECTION:` line, or a reviewer's plan
  defect) decide as `amendments.md` says. The items held with it are relaunched with it.
- `budget: ...` → the item failed its checks three times. Bring it to the
  user with the evidence and offer to split it into its own workorder.

The launch-wide ceiling is `maxAgents` (default 120) spawned agents and,
when set, `tokenCeiling` output tokens. At the ceiling the launch finishes
what is running and returns `CEILING`; relaunch, or stop and report. Pushing,
installing and anything destructive stay gated on the owner's word exactly as
before: nothing in items mode pushes.

## Launch args for items

`items` comes from `py -3 tools/plan_lint.py <plan> --items-json`, which
`workorder_brief.py --launch-args <slug>` runs and copies unchanged, on every
launch of a plan of items (the relaunch reads which are done from `state`'s
`items:` line). `streaming: true` while the plan's State says `planning:
streaming` or the lint says planning is not complete (`--launch-args` sets
it): the workflow then runs a `refill` agent that waits
on `plan_lint.py --items-json --known <ids> --wait 480` and adds each item
the planner releases, and it runs no gate before planning is complete.
`answered` lists the items whose `owner:` question now has an answer under
`### Decisions` (`--launch-args <slug> --answered <id,...>`); an unanswered
item with `reversible: true` and a default runs on that default and comes
back under `defaulted`. The rest no file holds, so add them to the printed
JSON yourself when you want them. `reviewScopes` splits
a reviewer into several that each read only their paths, run as separate
reviewers. `maxParallel` (`DEFAULT_MAX_PARALLEL`, 4; a whole number from 1
to 16, anything else is `BAD-ARGS`), `maxAgents` (120), `tokenCeiling`
(none) and `itemAttempts` (3) are the
budgets in Step 2, "Items"; `reviewPassCap` (4) is how many passes a
reviewer makes as commits land before it waits for one final catch-up pass
once nothing else is running. Items that could not have come from that output
(a bad or duplicate id, no files, an `after:` naming no item, items beside
lanes) are refused with `BAD-ARGS` before anything is spawned. A launch with
no `items` runs in rounds (`SKILL.md` "Driver discipline").

## What a launch of items returns

A plan of items returns `PASS`, `PASS-PENDING-HUMAN`, `PARKED`, `PLAN-DEFECT`
(a reviewer's plan defect, the gate's unrunnable criterion, or a refill that
`plan_lint` refused), `CEILING`, `CAP` (the gate failed three times),
`AGENT-FAILED`, always with `items:` beside
it (each item's `id`, `status`, `reason`, `attempts`, `commits`, `evidence`
and `progress`, and `replan` when an amendment was tried and did not hold)
and `gate:` (each gate run). It also carries `defaulted` (each owner item
that ran on its default: `id`, `question`, `default`, `status`, `commits`
and `undo`), `amendments` (each amendment the launch tried, and whether it
held), and, on a result that waits on a person (`PARKED` with an owner item,
or `PASS-PENDING-HUMAN`), `unblocked` (Step 2, "Items"). Like every launch
it carries `record`, which `tools/workorder_record.py apply` writes: its Log
entry is `### Round <n> (items)`, with `unblocked:`, `defaulted (k):` and
`amendments (k):` lines when they apply, and State gains `items:
<id>=<status>; ...`, where an item done on its default reads `defaulted`.

Items mode keeps its own reviewer passes on every landed commit, all
reviewers included (the yield rule in `SKILL.md` Step 3 is for rounds), and
still spends one haiku agent on the launch's snapshot and one per `refill`
poll and per amendment command. Each item's checks run twice, by its
implementer and by an independent item-verifier; the verifier passes
`--reuse` with the implementer's own run
(`.claude/workorders/.rounds/<slug>/criteria/item-<id>-a<k>`), so
`run_criteria.py` re-runs only a check whose commit or `(reads ...)` hash
changed (the owner, 2026-10-11, on sharing results: "if it makes sense").
