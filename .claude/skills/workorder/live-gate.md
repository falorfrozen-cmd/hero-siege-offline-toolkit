# /workorder: the live gate (Step 4.5)

Read this only when a `PASS-PENDING-HUMAN` names a `### Live procedure <n>`. It is part of `SKILL.md`, moved out because most workorders never take this path.

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
0b. **Check the procedure puts "which code" questions to the debugger.**
   Read the procedure's **debugger** field and its checks (`py -3 .claude/skills/workorder/section.py
   <context> "Live procedure <n>"`). Send it back to the planner as a
   `PLAN-DEFECT`, before the install question, when the field is missing, or
   when a check asks whether a function fires, which code does something, or
   with what arguments or how often, and the field reads `none` with no
   reason that rules the debugger out (planner.md "Ask 'which code' of the
   debugger"). `live-operator` alone carries the x64dbg tools and attaches
   only when the procedure names debugger steps, so nothing later in the
   session adds them: ForgePact #197's Live 1 (2026-10-11) logged a research
   hook's `calls=0` against an observed merge, with no logpoint to show which
   code did it.
1. **Ask before anything changes on the owner's machine.** One question:
   install this build now, and is a session convenient now? Never install on
   your own — the owner decides when the DLL their game loads changes. On a
   yes, install it yourself with the module's documented install command (one
   call), and nothing else.
2. **Spawn `live-operator`** with: the slug, the session number `<n>`, the
   context file and the `### Live procedure <n>` heading, the character slot,
   and which build is installed. When the procedure's **debugger** field
   names steps, say so in the brief and name `live-operator.md` § "When the
   procedure names debugger steps". Record its agent id in `## State` ›
   `agents:`.
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
