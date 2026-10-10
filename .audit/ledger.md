# Findings ledger

Evidence labels: M = measured (transcripts, `.audit/data/*`), SV = statically verified (code), E = estimated, H = hypothesis.
WF = `.claude/workflows/workorder-rounds.js`, SK = `.claude/skills/workorder/SKILL.md`.

| ID | Pri | Finding | Evidence | Label | Status |
|---|---|---|---|---|---|
| F01 | P0 | LLM "scribe" does deterministic State/Log writes; 92/353 launches (26%) end STATE-LOST / LOG-DAMAGED / SCRIBE-FAILED and need a driver repair + relaunch | WF:679-702, 740-780; data/wfresults.md:3 | M+SV | open |
| F02 | P1 | Every shell command in a round is a Haiku agent (snapshot, delta, amend-save/check/restore, refill): 652+ spawns at ~52k spawn context each, serial on the critical path | WF:868-870, 1782-1786, 1855-1864, 1066-1103; data/wfruns.md | M+SV | open |
| F03 | P1 | Reviewers run every round regardless of yield: decompile-output-guard 1%, docs-sync 4%, sdk-contract 7%, tauri 0%, instrument-blindness 30% rounds with a BLOCKING | WF:1910-1917; data/wfresults.md:9-15; data/cost.md | M | open |
| F04 | P0 | Driver context: median 92 turns, median peak 294k (max 966k); 22% of list cost; 48% of its cache writes are re-warms after >1h idle (94 events) | data/aggregates.md:13,196; data/cachew.md | M | open |
| F05 | P1 | Spawn tax: every spawn loads CLAUDE.md+AGENTS.md (~16k est.) and an agent body; no agent sets omitClaudeMd; workflow spawn writes = 45% of workflow cache writes | discovery-context-inventory.md; data/aggregates.md:166-190; data/cachew.md | M+SV+E | open |
| F06 | P1 | Implementer = 31% of list cost; always a fresh Opus/high spawn per round (939 contexts), re-reading brief and files | WF:876-911; data/cost.md; data/reads.md | M+SV | open |
| F07 | P1 | Wall clock dominated by owner wait (human 35.7% + AskUserQuestion 11.0%) and background launches (25.5%); model time 12.4% of driver wall | data/timing.md | M | open |
| F08 | P1 | Launch = 1 round (median); each round needs a driver turn + relaunch; achieved concurrency inside launches 1.22 median | data/wfresults.md:5; data/wfruns.md | M | open |
| F09 | P1 | Planner = 20% of list cost; 334 contexts (replans, amendments); planners run plan_lint 910x and read plan files 1,467x via shell | data/cost.md; data/reads.md | M | open |
| F10 | P2 | Criteria run twice per round (implementer 923 run_criteria / 2,269 pytest; verifier 1,189 / 885); identical item checks in items mode | WF:1316 vs 1331; data/reads.md | M+SV | open |
| F11 | P2 | Prompt bulk: SK 102 KB (~25k tok) resident in driver; AGENTS.md 62 KB in every spawn; planner body 43 KB repeats AGENTS.md sections (drifted) | discovery-context-inventory.md | SV+E | open |
| F12 | P2 | Untyped utility agents get unrestricted tools + full listings for one command | WF:1786 etc. (no agentType) | SV | open |
| F13 | P2 | Uncapped loops: PLAN-DEFECT before verify not counted; relaunch after PARKED/CEILING uncapped; rebuild resets item attempts | WF:1844-1848, 1157, 1386-1388; SK:381-411 | SV | open |
| F14 | P3 | 4 planner / 2 implementer / 2 consultant files are byte-identical bodies; listing repeats ghidra tool lists ~8x (~2.8k tok est.) | discovery-context-inventory.md | SV+E | open |
| F15 | P3 | PostToolUse dispatcher runs ~12 git status per Bash/Edit; recorded hook durations small (median 75-276 ms, n=22) | .claude/hooks/post_tool_use.py; data/peek2 output | SV+M(small n) | open |
| F16 | P3 | Driver used 1,171 shell reads of plan files and 536 section.py calls (copying State/lint JSON into launch args) | data/reads.md; SK:1270-1325 | M+SV | open |
| S01 | — | Security (outside scope): GITHUB_MCP_PAT value printed into a subagent transcript during discovery; rotate it | discovery agent report | M | reported to owner |
