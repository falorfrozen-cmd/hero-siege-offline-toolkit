# Discovery: the actual execution path of a `/workorder`

Read-only reconstruction, 2026-10-11, worktree `audit-workorder-architecture` (HEAD `c4529da`).
Labels: **[SV]** statically verified from the cited lines; **[H]** hypothesis / inference not proven by the code.
Abbreviations: `SKILL` = `.claude/skills/workorder/SKILL.md`, `WF` = `.claude/workflows/workorder-rounds.js`,
`CAL` = `docs/agents/workorder-calibration.md`, `RD` = `.claude/skills/workorder/round_delta.py`.

---

## 1. Orchestration surface: who drives each step

| Step | Driven by | Plan / intermediate results held in | Evidence |
|---|---|---|---|
| 0, 0.25, 0.5 (worth it? checkout? triage tier, size warning) | main-session LLM ("driver") following SKILL prose | driver context only (triage row is said aloud, not written) | [SV] SKILL:48-155, "say which row you matched" SKILL:121-123 |
| 1 plan | driver spawns `planner*` via `Agent`; driver then runs `plan_lint.py` and reads plan | files: `.claude/workorders/<slug>-plan.md` + `<slug>-context.md` | [SV] SKILL:183-231 |
| 1 lint / lanes / items table | Python (`tools/plan_lint.py`), output JSON **copied by the driver LLM into Workflow args** | driver context → workflow args | [SV] SKILL:222-231, 1270-1294 |
| 2-4 (default) | `WF` JS script in the Workflow tool; every shell command goes through an agent because "This script cannot read a file or run a shell" | JS memory (`knownState`, `critState`, `reviewerState`, `rounds[]`) + files written by scribe | [SV] WF:868-870, SKILL:1253-1257 |
| 2-4 (fallback "driver mode") | driver LLM turns | driver context + driver `Edit`s of State/Log | [SV] SKILL:1412-1414, 1236-1251 |
| amendment (in-launch) | WF via 3 haiku/opus agents | files (`.rounds/<slug>/amend-base-*.md`) | [SV] WF:1076-1111 |
| replans, consultations, owner questions | driver LLM | driver context + Log `### Decisions` | [SV] WF:17-20, SKILL:1399-1404 |
| 4.5 live | driver relays; `live-operator` agent operates | `<slug>-live-<n>.md` capture | [SV] SKILL:874-1002 |
| 5 report, final gate, audit | driver LLM + `workorder_audit.py --latest` (Python) | stdout into driver context | [SV] SKILL:1004-1049 |

Key structural fact **[SV]**: the JS engine cannot execute anything itself; snapshot, delta, size, amend-save/check/restore, plan_lint refill are each a **haiku LLM agent asked to "Run exactly: ... report its exit code"** (WF:1782-1786, 1855-1864, 1082-1103, 1063-1066, 1442-1444, 1548-1552).

---

## 2. Step lists

### (a) `/workorder <task>` full run
1. Step 0 / 0.25 / 0.5 in driver context **[SV]** SKILL:48-155. No agent spawned.
2. `ensure_submodule.py <module>` if needed (Python, driver Bash) **[SV]** SKILL:159-170.
3. `git fetch` + `git diff --name-only HEAD...origin/main`; merge if it touches plan files **[SV]** SKILL:172-181.
4. Spawn planner at triaged tier (`planner-medium` / `planner` / `planner-xhigh`) **[SV]** SKILL:92-98, 183. Prompt: "the request and the repository context" — content unspecified, driver-composed **[SV]** SKILL:183-184. Returns `PLAN-READY` or `ADVICE-NEEDED`; writes the two workorder files **[SV]** SKILL:184-189; planner.md:24-26.
5. Driver reads plan, `## Needs human judgement`, `## Log`; greps Context **[SV]** SKILL:198-200. Runs `plan_lint.py <plan>`; finding → back to planner **[SV]** SKILL:202-210. Non-empty Needs-human-judgement → ask user **[SV]** SKILL:218-220.
   - [H] README says workflow mode runs "after the plan is approved" (.claude/README.md:529-530) but SKILL only gates on Needs-human-judgement (SKILL:218-220): inconsistent.
6. `plan_lint.py --lanes-json` / `--items-json`; last line pasted into WF args **[SV]** SKILL:222-245.
7. `Workflow({scriptPath: WF, args:{slug, planPath, contextPath, checkoutRoot, goalExcerpt, …, state, priorFindings, baseHeads, lanes|items}})` **[SV]** SKILL:1259-1268. Driver pastes: `goalExcerpt` (Goal + Out of scope), `state` (full `## State` via `section.py`), `priorFindings` (copied from Log), `baseHeads` (from State) **[SV]** SKILL:1303-1325.
8. Route result (PASS / PASS-PENDING-HUMAN / PLAN-DEFECT / ADVICE-NEEDED / CAP / STATE-LOST / SCRIBE-FAILED / LOG-DAMAGED / AGENT-FAILED / PARKED / CEILING) **[SV]** SKILL:1347-1398.
9. Step 4.5 live gate if a `### Live procedure` is pending **[SV]** SKILL:711-717, 874-1002.
10. Step 5: final gate = fresh verifier with no `--dev` (or launch with `fullVerify:true`), `workorder_audit.py --latest`, optional `workorder_speed.py` **[SV]** SKILL:1013-1037.
    - [H] A `fullVerify:true` launch in rounds mode still starts with snapshot + implementer before the verifier (WF:1778-1820 has no verify-only path), so the "final gate via launch" pays an implementer spawn.

### (b) `/workorder plan <task>`
Steps 0 → 1 only (items 1-6 above); report Goal/OOS/criteria/Needs-judgement/triage row/`resume` command; spawn nothing further **[SV]** SKILL:17-28, 247-257. Never streams **[SV]** SKILL:245.

### (c) `/workorder resume <slug>`
Steps 2 → 5 **[SV]** SKILL:19. Pre-checks: repeat submodule check; stop on status PASS/DONE/CAP/SPLIT/SUPERSEDED; DRAFT → replan; read plan **in full**, Needs-human-judgement and **all of `## Log`** (only point the driver reads the whole Log); re-run 0.25 and 0.5; self-sufficiency check **[SV]** SKILL:261-285. Then `round_delta.py snapshot` (driver mode) **[SV]** SKILL:287-289, then (a)7 onwards.

### (d) Workflow mode, rounds (no items) — per round `n`, WF:1778-1977
| # | Spawn (label) | agentType / model / effort | Prompt carries | Returns | Files |
|---|---|---|---|---|---|
| 1 | `snapshot:r<n>` | generic / haiku / low | 2 shell commands | `SNAPSHOT_SCHEMA` (exit, heads, raw_output) | writes `.rounds/<slug>/round-n.json` **[SV]** WF:1782-1786, 338-349; RD:37-39 |
| 2 | `implementer:r<n>` (or lanes ×L in `parallel()` + `implementer:join:r<n>` on first round; or `patch-implementer:r<n>`) | `implementer` (opus/high) or `implementer-medium`; model from args | plan/context **paths**, `workorder_brief.py` command, re-entry reading instructions, VERDICT_ASK; patch: findings+fix text; join: every lane's report pasted | `IMPL_SCHEMA` {verdict, report, evidence, progress_so_far, question} — free text, unbounded size | edits source, commits **[SV]** WF:916-920, 1794-1820, 315-325, 981-986, 937-943 |
| 2b | if PLAN-DEFECT with `CORRECTION:` → `amend-save` (haiku/low), `amendment: <slug> …` (`planner-medium`/opus), `amend-check` (haiku/low), `amend-restore` on reject (haiku/low); confirmed → re-spawn implementer | | correction + evidence verbatim | | **[SV]** WF:1821-1840, 1076-1111 |
| 2c | non-IMPL-DONE → scribe, return to driver | | | | **[SV]** WF:1844-1849 |
| 3 | `delta:r<n>` | generic / haiku / low | `round_delta.py delta` + 2 greps (+`size` in patch rounds) | `DELTA_SCHEMA` | **[SV]** WF:1855-1864 |
| 4 | `verifier:r<n>` ‖ each reviewer `<name>:r<n>` in one `parallel()` barrier | verifier haiku/medium; reviewers opus/medium, instrument-blindness opus/high | verifier: plan path + long boilerplate (section.py, run_criteria background poll, digest, gates, `--dev` or reach flags); reviewers: **goalExcerpt pasted**, diff commands, prior findings | `VERIFIER_SCHEMA` (per-criterion evidence) / `REVIEW_SCHEMA` (findings with optional `fix`) | **[SV]** WF:1907-1919, 815-838, 367-396; agents frontmatter |
| 5 | JS routing: gate reclassification, patch eligibility, reach scope | deterministic | | | **[SV]** WF:1929-1964 |
| 6 | `scribe:r<n>` | `scribe` / haiku / low | **precomputed** Log block + **whole merged State** fenced | `SCRIBE_SCHEMA` (written, state_before/after, log_anchor, log_tail) | edits plan `## State`, appends context `## Log` **[SV]** WF:679-702, 1968 |
| 7 | JS verifies scribe report → STATE-LOST / SCRIBE-FAILED / LOG-DAMAGED stop | deterministic | | | **[SV]** WF:740-780, 1972-1973 |

### (d') Workflow mode, items (WF:1234-1704)
`snapshot` once; event loop (`drain`, WF:1563-1611): per item `item-implementer:<id>:a<k>` (runs its own `--item` checks and commits via `item_commit.py`) → `item-verifier:<id>:a<k>` re-runs **the same** `run_criteria --item` **[SV]** WF:1316, 1330-1334, 1358; reviewers per landed commit `<rv>:p<k>:r<n>`; each BLOCKING set → `fix-<k>` item; `refill` haiku agent polling `plan_lint --items-json --wait 480` while streaming; amendments serialized; when drained → gate `verifier:r<n>` (`--dev`), failure → `gate-fix-<k>` → gate again; final scribe via `finish()` **[SV]** WF:1648-1703.

### Driver-mode spawns outside the engine
consultant / consultant-max (opus/xhigh|max) **[SV]** SKILL:547-550; live-operator (opus/medium) **[SV]** SKILL:909-911, live-operator.md frontmatter; replanning planner (fresh, escalating) **[SV]** SKILL:487-491, 517-520.

---

## 3. Loops, retries, caps

| Loop | Entry | Exit | Cap | Progress measured? | Evidence |
|---|---|---|---|---|---|
| implement→verify rounds | IMPL-DEFECT or BLOCKING | PASS / PPH / PLAN-DEFECT / CAP | `ROUND_CAP=3` counted rounds; `n` is the absolute State round, so the cap spans launches | No (only count) | [SV] WF:73, 1778; SKILL:733-737 |
| owner-scope rounds | driver bumps `scope rounds:` | — | +≤3 (`SCOPE_CAP`) | No | [SV] WF:74, 1756-1757; SKILL:756-759 |
| patch rounds | every BLOCKING has `fix`, no failed criterion | size check | uncounted if ≤20 lines/no new file; never back-to-back (`!isPatch` gate); one may follow the 3rd round | `round_delta.py size` lines | [SV] WF:974-997, 1961-1963, 1778 |
| PLAN-DEFECT before verify | implementer verdict | return to driver | **not counted** against rounds (State keeps `round: n`) | No | [SV] WF:1844-1848 (`round: ${n}`) |
| in-launch amendment | PLAN-DEFECT with CORRECTION ≠ none | AMENDMENT re-run / replan | 1 per implementer attempt; 2nd PLAN-DEFECT after it = replan | `amend_check` ≤20 lines | [SV] WF:1826-1838, 1022-1027; tools/amend_check.py:56 |
| replans | PLAN-DEFECT without amendment | PLAN-READY | 2 (3rd → ask user); tier: planner → planner-max | count only | [SV] SKILL:487-491 |
| consultations | ADVICE-NEEDED | answer → resume (driver) / relaunch (WF) | 2 per round; 3rd → escalate phase | No | [SV] SKILL:552-558 |
| items: attempts | item checks fail | pass / park | `ITEM_ATTEMPTS=3` (amendments uncharged) | No | [SV] WF:1154, 1365-1367 |
| items: rebuilds | commit lands on `build_reads` | done | `REBUILD_CAP=5`, **each rebuild resets the attempt budget** (`chargeFrom: s.attempts`) | No | [SV] WF:1157, 1386-1388 |
| items: reviewer fixes | BLOCKING | clean | `FIX_CAP=3` per reviewer (4th fix parks) | No | [SV] WF:1155, 1546 |
| items: reviewer passes | commits land | — | `REVIEW_PASS_CAP=4` then a final catch-up | No | [SV] WF:1172, 1497 |
| items: gate | whole-tree fail | pass | `GATE_CAP=3` | No | [SV] WF:1156, 1700 |
| items: refill polls | streaming | complete | `REFILL_CAP=40` | — | [SV] WF:1158, 1557 |
| items: launch ceiling | — | CEILING | `maxAgents=120`, optional `tokenCeiling` (output tokens) | agents counted | [SV] WF:1171, 1259-1261 |
| relaunches after PARKED/CEILING | driver | — | **no cap found** | — | [SV] SKILL:381-411 (no limit stated) |
| structured-output retries | — | — | **none in script**: a null `agent()` result → `AGENT-FAILED` immediately | — | [SV] WF:1800, 1809, 1816, 1819, 1925-1927. Any retry inside the Workflow runtime's schema enforcement is not visible here [H] |
| re-entry resume | same-phase same-tier | — | resumed ≤2× then fresh (driver mode); WF: always fresh | — | [SV] SKILL:510-524, 1403-1404 |

### Worst-case spawn count (rounds mode, one workorder) — arithmetic from the caps above [H: derived bound]
Per verify-round max: snapshot 1 + implementer 1 + amendment (save+planner+check) 3 + re-run 1 + delta 1 + verifier 1 + reviewers 5 + scribe 1 = **14** (round 0 with L lanes: +L).
- Verify-rounds: 3 counted + 3 patch (one after each) = 6; with 3 scope rounds: 6 counted + 6 patch = 12.
- Blocked (PLAN-DEFECT/ADVICE) rounds are uncounted: each ≤ snapshot+impl+save+planner+check+restore+scribe = 7.
- Driver: 1 plan + 2 replans + ≤2 consultants/round (+ relaunch snapshot+impl+scribe each in WF mode = 4 per consultation).

Worst (no scope): 3 planners + 2×7 blocked + 6×14 rounds + 6 rounds×2 consults×4 + 1 final-gate verifier ≈ 3 + 14 + 84 + 48 + 1 = **~150 agent spawns**; with scope rounds ≈ **~290**. Of these, per verify-round 4-7 are haiku "run one command" agents (snapshot, delta, scribe, amend ×3-4).
Items mode is bounded per launch by `maxAgents=120` [SV] but launches are uncapped; a single build item can consume (1+5 rebuilds)×3 attempts×2 agents = **36** spawns [H: derived from WF:1157, 1366, 1387].

---

## 4. Tier / effort selection
**Triage table** [SV] SKILL:92-98: concurrency or unknown mechanism → `planner-xhigh` + `implementer`; docs/tests/config only → `planner-medium` + `implementer-medium`; else `planner` + `implementer` (opus/high); suspend-loop class → stop.

**Spawn table** [SV] SKILL:1453-1462: planner-medium (amendments, docs row), planner (default + 1st replan), planner-xhigh (hard rows), planner-max (2nd replan), implementer-medium (patch rounds, docs row), implementer (else), consultant opus/xhigh, consultant-max (hard-row question). All opus.

**Frontmatter pins** [SV] `.claude/agents/*.md` lines 5-7: verifier haiku/medium; scribe haiku/low; reviewers opus/medium except instrument-blindness opus/high; live-operator opus/medium.

**Driver**: the session itself, recommended opus/medium ("Chosen 2026-10-06, not measured") [SV] SKILL:1464-1472.

**Mechanical steps** [SV]: snapshot, delta, size, amend-save/check/restore, amend-items, refill — `model:'haiku', effort:'low'`, no agentType (generic workflow-subagent, unrestricted tools) (WF:1786, 1864, 1066, 1084, 1103, 1444, 1552; SKILL:1404-1406). Scribe: restricted `scribe` type haiku/low (WF:701). Effort is chosen by agent **name** because the `effort` option's precedence is undocumented [SV] WF:423-428.

---

## 5. State
| File | Holds | Writers | Evidence |
|---|---|---|---|
| `.claude/workorders/<slug>-plan.md` | frontmatter, `## State` (round, phase, gates, gates pending, round base, agents, reviewers, open defects, patch rounds, scope rounds, items, decisions in force…), Goal, OOS, criteria, Steps | planner (sections); **scribe** (State, WF mode); driver `Edit` (driver mode + driver-owned lines `gates:`, `round base:`, `agents:`); amendment planner | [SV] planner.md:398-417; WF:556-562, 682-684; SKILL:1236-1246, 1320-1322 |
| `<slug>-context.md` | Context subsections, Needs human judgement, `## Log` (`### Decisions`, `### Plan`, `### Replan k`, `### Amendment k`, `### Round n (started t)`, `### Live n`) | planner, scribe (WF), driver (driver mode, live summaries, repairs), amendment planner | [SV] SKILL:184-189; planner.md:488-493, 614-619; WF:538 |
| `<slug>-live-<n>.md` | live capture | live-operator only (R17/R20) | [SV] live-operator.md:80-84; SKILL:998-1002 |
| `.claude/workorders/.rounds/<slug>/round-<n>.json`, `round-<n>.stop`, `amend-base-*.md` | snapshot hashes+heads; lane stop marker; amendment backup | `round_delta.py`, `amend_check.py` (via haiku agents in WF) | [SV] RD:37-48; tools/amend_check.py:35-37 |
| `<git-dir>/workorder-locks` | OS byte-range locks `commit`, `build`, `browser-k` (process locks, **not** workorder state locks) | `item_commit.py`, `run_criteria.py` | [SV] tools/workorder_lock.py:1-24 |
| verifier scratch `criteria/status.json`, `report.txt`, `cmd-n.log` | criteria run | `run_criteria.py` | [SV] tools/run_criteria.py:113-120 |

Both workorder files are gitignored [SV] SKILL:193-196.
**Duplicate state in memory** [SV]: WF keeps `knownState` and re-sends the **whole merged State** to the scribe each round (WF:626, 682, 760); driver must paste State back on STATE-LOST/SCRIBE-FAILED (SKILL:1368-1384).
**Re-read each round** [SV]: implementer runs `workorder_brief.py` (Goal, OOS, State, steps, all criteria, cited ctx, Decisions, previous Round Log entry) — fresh every round since WF re-entries are always fresh spawns (WF:876-880, 898-911; tools/workorder_brief.py:17-48); verifier runs `section.py` for criteria + State (WF:815); reviewers get `goalExcerpt` pasted every round (WF:1911); scribe reads State range + last 30 Log lines (WF:693-694).
**Re-pasted into prompts** [SV]: goalExcerpt (every reviewer, every pass, WF:1911, 1517); full State (scribe, WF:682); every lane's report (join, WF:943); patch findings (WF:983-984); amendment correction + evidence verbatim (WF:1089-1090); disputed-finding implementer report ≤1500 chars (WF:1901); item retry evidence (WF:1317); verifier boilerplate ~3 KB constant strings (WF:815-838).

---

## 6. Validation passes per round (rounds mode)
| Pass | LLM? | Evidence |
|---|---|---|
| implementer runs each criterion as it satisfies it (and on re-entry, failed + reached criteria via `run_criteria --changed-since`) | LLM-driven, commands deterministic | [SV] implementer.md:216-273 |
| verifier: `run_criteria.py --dev`/reach in background, poll, `--digest`, judge | LLM (haiku) wrapping deterministic runner | [SV] WF:815-835; verifier.md:73-121 |
| reviewers ≤5 in parallel, told not to re-run suites | LLM (opus) | [SV] WF:1910-1917, 1914 |
| JS gate reclassification, patch eligibility, reach scope, scribe-report diff | deterministic | [SV] WF:1936-1964, 740-780 |
| `round_delta.py size` patch check | deterministic (but invoked by haiku agent) | [SV] WF:1862, 988-997 |
| `amend_check.py check` | deterministic (via haiku agent) | [SV] WF:1101-1110 |
| `plan_lint.py` (driver, before rounds; amendment planner; items refill) | deterministic | [SV] SKILL:202-210; WF:1091, 1442 |
| `workorder_audit.py` R1-R27 — **post-hoc only, at Step 5** | deterministic | [SV] SKILL:1026-1029; tools/workorder_audit.py:903-1914 |
| final gate: full verifier once before PR | LLM | [SV] SKILL:1013-1020 |

Overlap [SV]: implementer and verifier both run the criteria (implementer.md:216, 262-273 vs verifier.md:68-79); in items mode the item implementer and the item-verifier run the **identical** `run_criteria.py --item <id>` (WF:1316 vs 1331). "Caching a result across agents stays rejected" (CAL:328-330, 174-176) — deliberate for independence. Measured implementer check catch rate 0.34-0.58 (CAL:885, 1179-1180).

---

## 7. Sequential vs parallel
- Rounds: snapshot → implementer → delta strictly sequential; verifier ‖ reviewers in one `parallel()` barrier; scribe after (WF:1782-1919, 1968). Barrier is deliberate: fixer streaming into the verified tree rejected (WF:1903-1906; CAL:415-420). **[SV]**
- Lanes: `parallel()` on the launch's first round only; join serial (WF:1795-1808). **[SV]**
- Items: event loop `Promise.race`; implementers ≤ `maxParallel` (default 4, 1-16) (WF:1163-1170, 1584); reviewers launched whenever due, **not** counted against `maxParallel` (WF:1599) **[SV]**; whole-runtime cap min(16, CPUs−2) (planner.md:515) **[SV, as documented; runtime not inspected]**.
- Serialization points: amendments block all new starts (WF:1580-1597); `files:'*'` fixes run alone (WF:120-122); `commit`/`build` locks (workorder_lock.py:1-24). **[SV]**
- Driver: replans, consultations, owner questions, final report always serial in driver context (WF:17-20). **[SV]**
- Measured concurrency: 0.96 baseline, 1.47-1.54 bug batch, 0.87 post-2026-10-02 (CAL:879, 1174-1175) **[SV as recorded]**.

---

## 8. Instrumentation
- `tools/workorder_audit.py`: parses `~/.claude/projects/<project>/<session>.jsonl` + `subagents/` + `workflows/wf_*/` (lines 11-16); per-turn `input/cache_creation/cache_read/output` tokens (lines 462-469, 663-669); list-price cost via `MODEL_PRICES` (326, 541-552, 2091); 27 rules R1-R27 (903-1914); budgets (IMPLEMENTER 125 turns/28M tokens, VERIFIER 60/3.5M, ROUND0 40M, ROUND 20M, DRIVER 20 turns/round; lines 64-145); `--calibrate`; **writes nothing**, stdout/`--json` only. **[SV]**
- `tools/workorder_speed.py`: wall-time report from the same transcripts; span/busy/serial minutes, concurrency, per-phase agent minutes, waits, launches, items queue, verify kinds, run_criteria kills, owner blocks, implementer check catch rate, routes, `workorder_reads` KB per role (lines 26-75); **no token figures**, reads only (lines 6-7). **[SV]**
- In-band: round heading carries `started <taken_utc>` (WF:533-538); items Log line `<k> agents` (WF:1621); `reviewer passes:` (WF:1644). No end-time, no tokens recorded in the workorder files **[SV]**. No persistent metrics store found **[H: none found by search]**.

---

## 9. Measured figures already recorded (quotes, one line each)
- 22 sessions, ~$1,160 list: "implementer 32%, driver 30%, planner 22%, reviewers 10%, verifier 2%" — CAL:93-94.
- Audit failures pre-recalibration: R7 17/22, R13 16/22, R8 14/22, R10 10/22 — CAL:20-28.
- Sonnet implementer p90 46.8M, max 78.9M tokens — CAL:102-104; SKILL:113-114.
- Live sessions run by driver: "up to 325 turns, 99.5M tokens and about $60" vs median driver $12 — CAL:71-73; SKILL:879-881.
- forgepact-issue-14: 16 workorders, 42.4 h (26.5 h active), $469 — CAL:138-139.
- Cheap-routes study (29 sessions): fix-round implementers 69 spawns $191, replans 37 $170, reviewer re-runs 212 $96, of $1,858 total ("about a quarter") — CAL:290-297.
- Verifiers: median 7.6 min / 38 tool calls; 346 of 1,042 min on model turns — CAL:322-325; tools/run_criteria.py:6-9.
- Full ForgePact panel verify 25-35 min, paid ≥15 times — CAL:369-373.
- UI redesign: 60.75 h, 230 subagents, 32 launches, $582; 19.1 h (31%) owner-question idle; ≥2 agents only 6.8 h (11%); 14 of 32 launches ended PLAN-DEFECT (599 min), 4 STATE-LOST (145 min, all false), 2 CAP; driver 504/697 turns >300K, peak 966K — CAL:753-781; SKILL:993-995 ("driver alone cost $108").
- Baseline speed: 9,663 agent-min, concurrency 0.96, 126 full verifies, owner waits 4,975 min, 23 amendments / 32 replans / 1 consultation — CAL:877-886.
- Bug batch amendment waited 41 min for a driver turn — CAL:894-898; WF:1001-1005.
- Post-2026-10-02: 1.53B input tokens; implementer 745M/283 runs; planner 272M; amend phase 1523 agent-min over 54 amendments (1008 sole) > plan's 430; review 1001 min over 649 agents — CAL:1145-1178.
- Plan/context files: 915 `Read` calls, 12 MB + 400 shell reads — SKILL:419-423; CAL:1161-1163.
- Scribes read both files whole: 13 MB over 228 runs — CAL:1019-1021.
- Lanes: span 191.7 vs 243.1 serial min (saved 51.4); joins 67.6 min — CAL:262-265.
- Per-role $/run (Opus 5.5 reprice): driver 11.79, live-operator 4.01, planner 2.52, implementer 2.20, verifier 0.55 (0.02 on Haiku 5.5), scribe 0.48 (0.01) — CAL:1375-1383.
- One real WF run: implementer 73-88 turns / 9-10.6M tokens per round, "nine haiku utility agents 1.8M total" — .claude/README.md:534-538.
- Driver closing a capped workorder by hand: 236 Bash, 47 edits, median 425K ctx, 157M cached tokens — SKILL:1249-1251.

Most items in CAL's "Not yet measured" sections remain unmeasured (patch/amend routes, reach, `--dev`, effort tiers, opus reviewers, Haiku verifier) — e.g. CAL:335-347, 1282-1290, 1336-1343, 1403-1409.

---

## 10. Deterministic work delegated to an LLM
| Work | Delegated to | Why (as documented) | Evidence |
|---|---|---|---|
| run `round_delta.py snapshot`+`heads`, parse into JSON | haiku agent, every round | script cannot run shell | [SV] WF:1782-1786, 868-870 |
| run `round_delta.py delta` + 2 greps (+`size`) | haiku agent, every round | same | [SV] WF:1855-1864 |
| run `amend_check.py save/check/restore`, `plan_lint --items-json` | haiku agents (3-5 per amendment) | same | [SV] WF:1063-1111, 1442-1444 |
| refill polling `plan_lint --wait 480` | haiku agent, up to 40× | same | [SV] WF:1548-1552, 1158 |
| paste precomputed Log/State into two files, then **report back** the State and Log tail so JS can detect damage | `scribe` haiku agent, every round | script cannot write files | [SV] WF:510-525, 679-702, 740-780; incidents: 4 false STATE-LOST, 145 min (CAL:763, 776-779), LOG-DAMAGED 2026-10-03 (WF:657-670) |
| run `workorder_brief.py` and read it | each implementer (fresh every WF round) | script cannot read files to paste the slice | [SV] WF:863-880 |
| run `run_criteria.py`, poll status, read digest, transcribe exit codes into `VERIFIER_SCHEMA` | verifier (haiku); exit-only criteria need no judgement (`--digest` collapses them) | independence | [SV] WF:815-819; verifier.md:94-101 |
| copy `plan_lint` JSON, `section.py State`, `priorFindings`, `baseHeads` into Workflow args | driver LLM | — | [SV] SKILL:1270-1325 |
| repair State/Log after STATE-LOST / SCRIBE-FAILED / LOG-DAMAGED | driver LLM `Edit` | — | [SV] SKILL:1368-1395 |
| move gate tokens `gates pending:` → `gates:` | driver LLM | — | [SV] SKILL:926-929 |
| duplicate item checks (implementer then item-verifier, same command) | two LLM agents | independence | [SV] WF:1316, 1331 |

---

## Mermaid: actual execution graph

```mermaid
flowchart TD
  U([User: /workorder task|plan|resume]) --> D0["DRIVER LLM (session, opus/medium)\nStep 0 / 0.25 / 0.5 triage"]
  D0 -->|resume| R0["DRIVER reads plan + whole Log\nre-triage, self-sufficiency"]
  D0 --> ES["py ensure_submodule / git fetch-merge"]
  ES --> P1[["LLM: planner tier\n(medium|high|xhigh)"]]
  P1 -->|ADVICE-NEEDED| C1[["LLM: consultant\n(xhigh|max) ≤2/round"]]
  C1 -->|SendMessage resume| P1
  P1 -->|PLAN-READY| L1["py plan_lint (+ --lanes-json/--items-json)"]
  L1 -->|finding| P1
  L1 -->|plan mode| STOP1([report + resume cmd; STOP])
  L1 --> WF{{"Workflow: workorder-rounds.js\n(args pasted by driver)"}}
  R0 --> WF
  subgraph ROUND["Rounds mode, per round n  (cap 3 counted + ≤3 scope; patches uncounted)"]
    S1[["haiku: snapshot+heads"]] --> I1[["LLM: implementer / lanes‖+join / patch-impl"]]
    I1 -->|PLAN-DEFECT + CORRECTION| AM[["haiku save → planner-medium → haiku check (→ haiku restore)"]]
    AM -->|AMENDMENT| I1
    I1 -->|IMPL-DONE| DL[["haiku: delta (+size)"]]
    DL --> PV{{"parallel(): verifier(haiku) ‖ ≤5 reviewers(opus)"}}
    PV --> JS["JS route: gates, patchable, reach"]
    JS --> SC[["haiku scribe: paste Log/State, report back"]]
    SC --> CHK["JS: STATE-LOST / LOG-DAMAGED / SCRIBE-FAILED?"]
    CHK -->|IMPL-DEFECT/BLOCKING, n<cap| S1
    CHK -->|patch eligible| S1
  end
  WF --> S1
  I1 -->|PLAN-DEFECT / ADVICE-NEEDED / lane stop| SCB[["haiku scribe"]] --> RET
  CHK -->|PASS / PPH / PLAN-DEFECT / CAP / STATE-LOST…| RET["return to DRIVER"]
  RET -->|PLAN-DEFECT| RP[["LLM: replan planner\n1st same tier, 2nd planner-max, 3rd → ask user"]]
  RP --> WF
  RET -->|ADVICE-NEEDED| C1b[["LLM consultant"]] --> WF
  RET -->|STATE-LOST etc| FIX["DRIVER Edit repair"] --> WF
  RET -->|PPH + live procedure| LV[["LLM: live-operator (opus/medium)\nNEEDS-HUMAN ↔ driver relay"]]
  LV -->|fail as modelled| WF
  LV -->|contradicts model| RP
  RET -->|PASS| FG[["LLM: final-gate verifier (full set)"]]
  FG --> AU["py workorder_audit --latest (post-hoc)"] --> DONE([report])
  WF -.items mode.-> IT["event loop: ≤maxParallel item-implementers;\nitem-verifier per attempt (≤3);\nreviewers per commit (≤4 passes);\nfix items (≤3/reviewer); gate (≤3);\nmaxAgents 120"]
  IT --> RET
```
