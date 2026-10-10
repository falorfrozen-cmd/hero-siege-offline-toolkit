# Workflow runs

runs: 345; agents: 4496

- n: median 9, mean 13.03, p90 27, max 46
- wall: median 1633, mean 1994, p90 3930, max 8711
- busy: median 2065, mean 2546, p90 5200, max 1.256e+04
- conc: median 1.216, mean 1.282, p90 1.716, max 5.684
- bill: median 1.558e+07, mean 2.066e+07, p90 4.52e+07, max 1.276e+08
- total run wall h 191.1; total agent-busy h 244.0

## Agents by role (workflow)

| role | n | median req | median dur s | total busy h | billed | share of wf billed | first ctx med | models |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| implementer | 856 | 23 | 255 | 120.8 | 4700M | 66.0% | 53k | claude-opus-5-5:755, claude-sonnet-5:59 |
| docs-sync-reviewer | 508 | 11 | 66 | 16.5 | 449M | 6.3% | 34k | claude-sonnet-5-5:208, claude-sonnet-5:203 |
| sdk-contract-reviewer | 380 | 12 | 97 | 15.5 | 406M | 5.7% | 34k | claude-sonnet-5-5:190, claude-sonnet-5:132 |
| instrument-blindness-reviewer | 497 | 11 | 91 | 16.1 | 396M | 5.6% | 34k | claude-opus-5-5:443, claude-opus-5:41 |
| verifier | 536 | 9 | 151 | 43.8 | 391M | 5.5% | 31k | claude-haiku-4-5-20251001:485, claude-haiku-5-5:36 |
| decompile-output-guard | 500 | 6 | 35 | 7.8 | 232M | 3.3% | 34k | claude-sonnet-5-5:204, claude-sonnet-5:201 |
| scribe | 383 | 7 | 100 | 12.1 | 134M | 1.9% | 24k | claude-haiku-4-5-20251001:355, deepseek-flash:15 |
| untyped:delta | 246 | 5 | 28 | 2.3 | 90M | 1.3% | 52k | claude-haiku-4-5-20251001:226, deepseek-flash:15 |
| untyped:snapshot | 406 | 3 | 13 | 1.5 | 65M | 0.9% | 52k | claude-haiku-4-5-20251001:372, claude-haiku-5-5:19 |
| untyped:analyse | 8 | 46 | 715 | 1.6 | 56M | 0.8% | 61k | claude-fable-5-1:8 |
| untyped:impl | 4 | 62 | 1243 | 1.3 | 47M | 0.7% | 62k | claude-fable-5-1:4 |
| untyped:fix | 4 | 57 | 843 | 1.0 | 37M | 0.5% | 67k | claude-fable-5-1:4 |
| untyped:review | 9 | 31 | 272 | 1.0 | 34M | 0.5% | 68k | claude-fable-5-1:9 |
| planner | 28 | 7 | 41 | 0.4 | 14M | 0.2% | 57k | claude-opus-5-5:28 |
| untyped:write | 2 | 46 | 574 | 0.3 | 14M | 0.2% | 62k | claude-fable-5-1:2 |
| untyped:refute | 6 | 14 | 248 | 0.4 | 12M | 0.2% | 81k | claude-fable-5-1:6 |
| untyped:pin | 1 | 40 | 1283 | 0.4 | 8M | 0.1% | 67k | claude-fable-5-1:1 |
| untyped:measure | 4 | 14 | 113 | 0.2 | 7M | 0.1% | 76k | claude-opus-5-5:4 |
| untyped:hub | 1 | 30 | 1540 | 0.4 | 6M | 0.1% | 60k | claude-fable-5-1:1 |
| tauri-command-reviewer | 12 | 4 | 27 | 0.2 | 5M | 0.1% | 34k | claude-sonnet-5-5:6, claude-sonnet-5:5 |
| implementer-medium | 3 | 21 | 149 | 0.1 | 5M | 0.1% | 51k | claude-opus-5-5:2, claude-sonnet-5-5:1 |
| untyped:amend-items | 19 | 2 | 6 | 0.1 | 5M | 0.1% | 58k | claude-haiku-4-5-20251001:18, claude-haiku-5-5:1 |
| untyped:amend-save | 31 | 2 | 6 | 0.0 | 4M | 0.1% | 57k | claude-haiku-4-5-20251001:29, claude-haiku-5-5:2 |
| untyped:amend-check | 31 | 2 | 5 | 0.0 | 4M | 0.1% | 57k | claude-haiku-4-5-20251001:29, claude-haiku-5-5:2 |
| untyped:critic | 1 | 12 | 161 | 0.0 | 2M | 0.0% | 117k | claude-opus-5-5:1 |
| untyped:scribe | 6 | 4 | 67 | 0.1 | 2M | 0.0% | 46k | claude-haiku-4-5-20251001:6 |
| planner-medium | 3 | 5 | 28 | 0.0 | 2M | 0.0% | 65k | claude-opus-5-5:3 |
| untyped:amend-restore | 8 | 2 | 6 | 0.0 | 1M | 0.0% | 57k | claude-haiku-4-5-20251001:7, claude-haiku-5-5:1 |
| untyped:design | 3 | 2 | 21 | 0.0 | 1M | 0.0% | 96k | claude-opus-5-5:3 |

## Untyped (workflow-subagent) description patterns

- `snapshot:rN`: 406
- `delta:rN`: 246
- `amend-save:implementer:rN`: 9
- `amend-check:implementer:rN`: 9
- `scribe:rN`: 6
- `amend-restore:implementer:rN`: 4
- `amend-save:plugin:rN`: 4
- `amend-check:plugin:rN`: 4
- `design:N`: 3
- `amend-items:plugin:rN`: 3
- `amend-restore:fix-N:rN`: 2
- `amend-check:fix-N:rN`: 2
- `amend-save:fix-N:rN`: 2
- `amend-items:panel:rN`: 2
- `amend-check:panel:rN`: 2
- `amend-save:panel:rN`: 2
- `amend-items:merge-main:rN`: 1
- `amend-check:merge-main:rN`: 1
- `amend-save:merge-main:rN`: 1
- `amend-check:hook:rN`: 1
- `amend-save:hook:rN`: 1
- `amend-items:hook:rN`: 1
- `measure:timing`: 1
- `measure:history`: 1
- `critic`: 1

## Typed workflow agent description patterns

- `scribe:rN`: 383
- `instrument-blindness-reviewer:pN:rN`: 284
- `verifier:rN`: 278
- `implementer:rN`: 276
- `docs-sync-reviewer:pN:rN`: 269
- `decompile-output-guard:pN:rN`: 265
- `docs-sync-reviewer:rN`: 238
- `decompile-output-guard:rN`: 234
- `sdk-contract-reviewer:pN:rN`: 217
- `instrument-blindness-reviewer:rN`: 212
- `fix-implementer:fix-N:rN`: 193
- `sdk-contract-reviewer:rN`: 163
- `item-implementer:plugin:aN:rN`: 20
- `item-implementer:docs:aN:rN`: 18
- `implementer:join:rN`: 17
- `item-implementer:panel:aN:rN`: 16
- `item-verifier:docs:aN:rN`: 15
- `item-verifier:plugin:aN:rN`: 14
- `item-verifier:build-dev:aN:rN`: 14
- `item-implementer:build-dev:aN:rN`: 14
- `implementer:plugin:rN`: 13
- `item-implementer:record-N:aN:rN`: 13
- `implementer:docs:rN`: 11
- `item-verifier:panel:aN:rN`: 10
- `verifier:gN:rN`: 9
- `fix-implementer:gate-fix-N:rN`: 9
- `tauri-command-reviewer:rN`: 9
- `implementer:panel:rN`: 9
- `item-implementer:build-release:aN:rN`: 8
- `item-verifier:build-release:aN:rN`: 8