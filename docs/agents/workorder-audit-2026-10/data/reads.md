# Reads and commands by role (workorder sessions)

## Read calls by category: count / chars returned

| role | .claude agents/skills | AGENTS/CLAUDE.md | docs/ | persisted tool output | source/other | submodule instructions.md | workorder -context.md | workorder -plan.md | whole-file reads of workorder files |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| implementer | 64 / 0.4M | 5 / 0.0M | 790 / 5.6M | 152 / 4.7M | 3113 / 27.3M | 289 / 2.3M | 720 / 9.2M | 545 / 11.9M | 330 |
| reviewer | 6 / 0.0M | 0 / 0.0M | 411 / 3.1M | 654 / 24.3M | 1364 / 17.1M | 62 / 1.0M | 572 / 4.7M | 1 / 0.0M | 9 |
| scribe | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 935 / 13.2M | 748 / 7.8M | 481 |
| verifier | 2 / 0.0M | 0 / 0.0M | 89 / 0.7M | 266 / 0.8M | 936 / 5.3M | 18 / 0.3M | 18 / 0.2M | 329 / 8.1M | 201 |
| planner | 29 / 0.5M | 1 / 0.0M | 41 / 0.4M | 35 / 1.3M | 268 / 2.7M | 36 / 0.5M | 189 / 3.2M | 179 / 2.9M | 130 |
| unknown | 0 / 0.0M | 0 / 0.0M | 13 / 0.0M | 10 / 0.5M | 112 / 1.0M | 2 / 0.0M | 44 / 0.6M | 42 / 1.0M | 26 |
| driver | 6 / 0.2M | 4 / 0.0M | 6 / 0.0M | 24 / 0.7M | 62 / 0.3M | 8 / 0.1M | 50 / 0.3M | 46 / 0.8M | 31 |
| general-purpose | 1 / 0.0M | 1 / 0.0M | 6 / 0.0M | 9 / 0.2M | 155 / 0.6M | 12 / 0.1M | 6 / 0.1M | 7 / 0.2M | 6 |
| live-operator | 1 / 0.0M | 0 / 0.0M | 16 / 0.1M | 11 / 0.2M | 141 / 0.9M | 3 / 0.0M | 3 / 0.0M | 0 / 0.0M | 0 |
| untyped:analyse | 0 / 0.0M | 0 / 0.0M | 6 / 0.0M | 1 / 0.0M | 95 / 0.6M | 5 / 0.1M | 0 / 0.0M | 0 / 0.0M | 0 |
| untyped:review | 0 / 0.0M | 0 / 0.0M | 2 / 0.0M | 0 / 0.0M | 32 / 0.6M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 |
| untyped:impl | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 36 / 0.5M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 |
| untyped:scribe | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 6 / 0.2M | 6 / 0.2M | 12 |
| untyped:fix | 0 / 0.0M | 0 / 0.0M | 1 / 0.0M | 1 / 0.0M | 30 / 0.3M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 |
| untyped:write | 1 / 0.0M | 0 / 0.0M | 7 / 0.0M | 2 / 0.1M | 13 / 0.1M | 8 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 |
| Explore | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 2 / 0.1M | 11 / 0.2M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 |
| untyped:refute | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 19 / 0.1M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 |
| untyped:pin | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 8 / 0.1M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 |
| untyped:delta | 4 / 0.0M | 0 / 0.0M | 1 / 0.0M | 1 / 0.0M | 13 / 0.0M | 0 / 0.0M | 0 / 0.0M | 1 / 0.0M | 1 |
| untyped:hub | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 8 / 0.1M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 |
| consultant | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 16 / 0.1M | 0 / 0.0M | 1 / 0.0M | 0 / 0.0M | 0 |
| impeccable:impeccable-documenter | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 1 / 0.1M | 1 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 |
| untyped:amend-items | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 1 / 0.0M | 1 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 / 0.0M | 0 |

## Workorder-file Read calls per context (median / mean)

- consultant: n=2 median 1 mean 0.5 max 1
- driver: n=103 median 0 mean 0.9 max 7
- general-purpose: n=33 median 0 mean 0.4 max 3
- implementer: n=964 median 0 mean 1.3 max 10
- live-operator: n=104 median 0 mean 0.0 max 3
- planner: n=364 median 0 mean 1.0 max 11
- reviewer: n=2018 median 0 mean 0.3 max 6
- scribe: n=383 median 4 mean 4.4 max 14
- unknown: n=118 median 0 mean 0.7 max 10
- untyped:delta: n=246 median 0 mean 0.0 max 1
- untyped:scribe: n=6 median 2 mean 2.0 max 2
- verifier: n=625 median 0 mean 0.6 max 5

## Commands by role

| role | cargo | cat/sed/head on plan | cmake/msbuild build | git diff | npm/node test | plan_lint | pytest/unittest | round_delta | run_criteria | section.py |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Explore | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| consultant | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| driver | 1 | 1171 | 1 | 298 | 13 | 259 | 192 | 346 | 24 | 536 |
| general-purpose | 0 | 31 | 0 | 46 | 0 | 0 | 47 | 0 | 12 | 27 |
| implementer | 7 | 646 | 0 | 1428 | 106 | 65 | 2269 | 375 | 923 | 1069 |
| live-operator | 0 | 21 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 179 |
| planner | 1 | 1467 | 3 | 269 | 26 | 910 | 369 | 9 | 255 | 1305 |
| reviewer | 0 | 220 | 0 | 4499 | 6 | 18 | 334 | 2 | 13 | 151 |
| unknown | 0 | 29 | 0 | 90 | 0 | 0 | 65 | 13 | 39 | 65 |
| untyped:amend-items | 0 | 0 | 0 | 0 | 0 | 39 | 0 | 0 | 0 | 0 |
| untyped:analyse | 0 | 0 | 7 | 5 | 0 | 0 | 1 | 0 | 0 | 0 |
| untyped:delta | 1 | 0 | 0 | 15 | 0 | 0 | 0 | 383 | 3 | 3 |
| untyped:fix | 0 | 0 | 0 | 21 | 0 | 0 | 3 | 0 | 0 | 0 |
| untyped:hub | 0 | 0 | 1 | 1 | 0 | 0 | 7 | 0 | 0 | 0 |
| untyped:impl | 0 | 0 | 0 | 22 | 0 | 0 | 0 | 0 | 0 | 0 |
| untyped:pin | 0 | 0 | 0 | 1 | 0 | 0 | 10 | 0 | 0 | 0 |
| untyped:refute | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| untyped:review | 0 | 0 | 2 | 4 | 0 | 0 | 0 | 0 | 0 | 0 |
| untyped:snapshot | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 872 | 0 | 0 |
| untyped:write | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 0 | 0 | 0 |
| verifier | 0 | 259 | 0 | 286 | 7 | 7 | 885 | 3 | 1189 | 735 |