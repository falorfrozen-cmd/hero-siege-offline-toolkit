# Workflow results (353 records)

Outcomes: PASS-PENDING-HUMAN:74, STATE-LOST:71, PASS:60, PLAN-DEFECT:51, PARKED:38, CAP:21, LOG-DAMAGED:12, SCRIBE-FAILED:9, None:4, AGENT-FAILED:4, BAD-ARGS:3, ADVICE-NEEDED:3
Verifier verdict per round: PASS-PENDING-HUMAN:117, PASS:75, IMPL-DEFECT:45, PLAN-DEFECT:7
Rounds per launch: median 1.0, max 3
Launch duration min: median 26, p90 63; agents/launch median 9
Blocking-item keys: reviewer:120, where:120, problem:120, evidence:120, fix:77

| reviewer | rounds where configured | rounds with ≥1 BLOCKING from it | yield | blocking items | non-blocking items |
|---|---:|---:|---:|---:|---:|
| docs-sync-reviewer | 243 | 10 | 4% | 10 | 257 |
| decompile-output-guard | 240 | 3 | 1% | 3 | 37 |
| instrument-blindness-reviewer | 215 | 65 | 30% | 93 | 532 |
| sdk-contract-reviewer | 179 | 12 | 7% | 14 | 255 |
| tauri-command-reviewer | 36 | 0 | 0% | 0 | 5 |