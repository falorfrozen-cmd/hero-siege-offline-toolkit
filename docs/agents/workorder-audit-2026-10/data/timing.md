# Timing (workorder sessions)

## Driver wall-clock decomposition (sum over 106 driver contexts)

| bucket | hours | share |
|---|---:|---:|
| human | 292.5 | 35.7% |
| bg-notification | 208.6 | 25.5% |
| model | 101.8 | 12.4% |
| tool:AskUserQuestion | 90.3 | 11.0% |
| tool:Agent | 44.6 | 5.4% |
| other-user | 36.6 | 4.5% |
| system-event | 34.7 | 4.2% |
| tool:Bash | 7.8 | 0.9% |
| tool:PowerShell | 0.4 | 0.0% |
| tool:Edit | 0.3 | 0.0% |
| tool:SendMessage | 0.2 | 0.0% |
| tool:Workflow | 0.2 | 0.0% |
| tool:mcp__hs-drive__hs_launch | 0.0 | 0.0% |
| tool:mcp__hs-drive__hs_command | 0.0 | 0.0% |
| total | 818.2 | |

## Tool durations

| context | tool | n | median s | p90 s | total h |
|---|---|---:|---:|---:|---:|
| workflow | Bash | 47329 | 1.7 | 4.6 | 93.4 |
| main | AskUserQuestion | 277 | 84.3 | 1375.7 | 90.3 |
| subagent | Bash | 22994 | 1.7 | 6.5 | 45.5 |
| main | Agent | 806 | 3.2 | 776.7 | 45.2 |
| workflow | Edit | 11716 | 1.6 | 9.6 | 12.0 |
| main | Bash | 5762 | 2.3 | 7.0 | 7.9 |
| subagent | Edit | 4429 | 2.5 | 9.4 | 5.6 |
| subagent | mcp__hs-drive__hs_command | 2385 | 2.4 | 8.6 | 2.6 |
| workflow | PowerShell | 1741 | 2.6 | 4.4 | 1.4 |
| subagent | mcp__hs-drive__hs_launch | 122 | 20.6 | 24.9 | 0.7 |
| subagent | mcp__hs-drive__hs_select_character | 120 | 20.2 | 23.6 | 0.7 |
| main | Edit | 804 | 1.9 | 6.3 | 0.7 |
| workflow | Read | 11312 | 0.0 | 0.3 | 0.5 |
| subagent | PowerShell | 342 | 2.9 | 8.0 | 0.5 |
| main | PowerShell | 206 | 3.6 | 11.6 | 0.4 |
| subagent | mcp__hs-drive__hs_input | 342 | 2.2 | 7.6 | 0.4 |
| subagent | mcp__6738bf42-a15b-4cc7-86bd-231d7248c4ea__use_figma | 183 | 6.3 | 10.1 | 0.4 |
| subagent | Write | 643 | 1.3 | 3.3 | 0.3 |
| subagent | mcp__hs-drive__hs_screenshot | 440 | 1.9 | 3.8 | 0.3 |
| main | mcp__ccd_session__spawn_task | 26 | 0.1 | 0.6 | 0.2 |
| main | SendMessage | 494 | 1.3 | 2.7 | 0.2 |
| subagent | SubagentHandback | 780 | 0.6 | 2.0 | 0.2 |
| subagent | mcp__hs-drive__hs_stash_tab | 132 | 5.0 | 6.5 | 0.2 |
| subagent | mcp__ghidra__decompile_function | 31 | 1.6 | 135.5 | 0.2 |
| main | Workflow | 367 | 1.3 | 3.2 | 0.2 |
| workflow | Write | 481 | 0.5 | 2.1 | 0.2 |
| subagent | mcp__hs-drive__hs_stash_open | 39 | 6.6 | 47.4 | 0.1 |
| subagent | Read | 2495 | 0.0 | 0.3 | 0.1 |
| subagent | mcp__hs-drive__hs_skill_cast | 43 | 8.5 | 18.1 | 0.1 |
| subagent | mcp__hs-drive__hs_stop_game | 113 | 3.4 | 6.6 | 0.1 |

## Subagent Bash time by command head

| cmd | n | median s | total h |
|---|---:|---:|---:|
| `cd` | 51504 | 1.7 | 82.8 |
| `py` | 3382 | 2.1 | 18.6 |
| `S="C:/Users/stann/AppData/Local/Temp/claude/C--Users-stann-P` | 960 | 3.9 | 11.0 |
| `F="C:/Users/stann/AppData/Local/Temp/claude/C--Users-stann-P` | 121 | 169.9 | 5.0 |
| `until` | 78 | 46.9 | 2.3 |
| `git` | 3921 | 1.6 | 2.3 |
| `for` | 217 | 2.6 | 1.8 |
| `timeout` | 54 | 14.5 | 1.6 |
| `grep` | 2799 | 1.2 | 1.4 |
| `SP="C:/Users/stann/AppData/Local/Temp/claude/C--Users-stann-` | 100 | 2.1 | 0.9 |
| `cat` | 921 | 1.8 | 0.8 |
| `sed` | 1404 | 1.1 | 0.6 |
| `ls` | 688 | 1.4 | 0.5 |
| `#` | 49 | 2.7 | 0.5 |
| `mkdir` | 146 | 2.1 | 0.5 |
| `f="$USERPROFILE/tools/hs-decomp/issue16/hosts3/decomp.log";` | 7 | 241.9 | 0.5 |
| `f="C:/Users/stann/AppData/Local/Temp/claude/C--Users-stann-P` | 16 | 77.2 | 0.5 |
| `L="C:/Users/stann/AppData/Local/Temp/claude/C--Users-stann-P` | 9 | 196.3 | 0.4 |
| `SPW='C:\Users\stann\AppData\Local\Temp\claude\C--Users-stann` | 7 | 9.3 | 0.3 |
| `sleep` | 195 | 2.5 | 0.3 |

## Agent tool: delegation prompt and returned result sizes (chars)

| subagent_type | n | prompt median | prompt p90 | result median | result p90 |
|---|---:|---:|---:|---:|---:|
| planner | 313 | 3268 | 5338 | 1146 | 4248 |
| live-operator | 105 | 1673 | 2332 | 1147 | 2123 |
| verifier | 89 | 1157 | 2527 | 1145 | 1153 |
| implementer | 83 | 2883 | 4263 | 1145 | 1152 |
| instrument-blindness-reviewer | 45 | 1844 | 3679 | 1149 | 1153 |
| decompile-output-guard | 41 | 734 | 1989 | 1149 | 1152 |
| general-purpose | 35 | 3462 | 5616 | 1151 | 4523 |
| docs-sync-reviewer | 28 | 1341 | 3260 | 1148 | 1152 |
| planner-medium | 25 | 2768 | 3596 | 1145 | 1149 |
| implementer-medium | 23 | 2632 | 4068 | 1132 | 1149 |
| sdk-contract-reviewer | 6 | 1752 | 3587 | 1146 | 4879 |
| planner-xhigh | 5 | 4420 | 7022 | 1132 | 1148 |
| Explore | 3 | 1988 | 2629 | 1153 | 6371 |
| consultant | 2 | 3194 | 3878 | 4192 | 7230 |
| planner-max | 2 | 4730 | 4984 | 1124 | 1149 |
| impeccable:impeccable-finish-reviewer | 1 | 1990 | 1990 | 1151 | 1151 |
| impeccable:impeccable-documenter | 1 | 1462 | 1462 | 1151 | 1151 |

Workflow tool results: n=367 median 1296 chars, p90 1320, max 1612

Workflow invocations by name/script: .claude/workflows/workorder-rounds.js:327, fd\.claude\workflows\workorder-rounds.js:14, cp\.claude\workflows\workorder-rounds.js:7, 0c\.claude\workflows\workorder-rounds.js:7, inline:3, ll\.claude\workflows\workorder-rounds.js:2, 83\.claude\workflows\workorder-rounds.js:2, 79a417/scratchpad/workorder-rounds-r3.js:2, 54\.claude\workflows\workorder-rounds.js:1, b9/.claude/workflows/workorder-rounds.js:1

Skill invocations: submodule-context:154, impeccable:impeccable:8, emil-design-eng:4, .claude/worktrees/forgepact-v2.2.1-hotfix:submodule-context:2, workflow-authoring:1, code-review:1, update-config:1, taste-skill:redesign-skill:1, taste-skill:taste-skill:1, apple-design:1