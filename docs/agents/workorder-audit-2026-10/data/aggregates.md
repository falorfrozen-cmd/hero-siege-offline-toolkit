# Transcript aggregates

Contexts: 5656; sessions: 199; workorder sessions (spawned a phase agent): 106
Window: 2026-09-18 .. 2026-10-10
All: requests 116617, input 9.91M, cache-read 15346.45M, cache-write 549.30M (1h 70.22M), output 66.31M
Workorder sessions: requests 110766 (95%), billed tokens 14937.72M (94% of all)

## By context type (workorder sessions)

| agent | contexts | requests | req/ctx med | input | cache-read | cache-write | cw-1h | output | first-ctx med | max-ctx med | dur med (min) | tool calls med | tool-result chars med | models | efforts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| implementer (wf) | 856 | 29290 | 23 | 1.66M | 4569.15M | 109.88M | 0 | 19.46M | 53k | 111k | 4.2 | 29 | 97k | claude-opus-5-5:755, claude-sonnet-5:59, claude-opus-5:16 | high:856 |
| main | 106 | 11441 | 90 | 1.43M | 3232.56M | 56.00M | 56.00M | 7.67M | 112k | 294k | 233.3 | 75 | 132k | claude-opus-5-5:81, claude-opus-5:19, deepseek-v4-pro:5 | medium:83, high:25, xhigh:1 |
| planner | 306 | 11651 | 29 | 779k | 1764.36M | 64.78M | 0 | 8.69M | 48k | 165k | 10.6 | 45 | 151k | claude-opus-5-5:203, claude-fable-5-1:69, claude-opus-5:27 | high:303, xhigh:3 |
| live-operator | 104 | 6838 | 50 | 301k | 1144.55M | 26.04M | 0 | 1.69M | 46k | 160k | 13.3 | 65 | 139k | claude-sonnet-5-5:44, claude-sonnet-5:37, claude-opus-5-5:20 | high:84, medium:20 |
| implementer | 83 | 3897 | 35 | 141k | 525.49M | 13.12M | 0 | 1.57M | 53k | 113k | 8.5 | 43 | 80k | claude-opus-5-5:67, claude-sonnet-5:10, claude-sonnet-5-5:3 | high:78, xhigh:5 |
| docs-sync-reviewer (wf) | 508 | 7082 | 11 | 801k | 412.99M | 32.26M | 0 | 3.23M | 34k | 63k | 1.1 | 12 | 49k | claude-sonnet-5-5:208, claude-sonnet-5:203, claude-opus-5-5:84 | high:423, medium:84, xhigh:1 |
| sdk-contract-reviewer (wf) | 380 | 5569 | 12 | 1.01M | 374.56M | 27.92M | 0 | 2.84M | 34k | 70k | 1.6 | 13 | 65k | claude-sonnet-5-5:190, claude-sonnet-5:132, claude-opus-5-5:45 | high:335, medium:45 |
| instrument-blindness-reviewer (wf) | 497 | 6260 | 11 | 736k | 358.29M | 33.20M | 0 | 3.30M | 34k | 67k | 1.5 | 12 | 59k | claude-opus-5-5:443, claude-opus-5:41, deepseek-v4-pro:13 | high:496, xhigh:1 |
| verifier (wf) | 536 | 8680 | 9 | 471k | 360.90M | 26.82M | 0 | 3.26M | 31k | 51k | 2.5 | 10 | 39k | claude-haiku-4-5-20251001:485, claude-haiku-5-5:36, deepseek-flash:15 | None:500, medium:36 |
| workflow-subagent (wf) | 782 | 4346 | 3 | 702k | 335.19M | 43.58M | 0 | 2.96M | 54k | 58k | 0.2 | 3 | 297.0 | claude-haiku-4-5-20251001:687, claude-fable-5-1:35, claude-haiku-5-5:30 | None:717, low:30, xhigh:24 |
| general-purpose | 34 | 1477 | 38 | 3k | 239.70M | 7.19M | 0 | 1.39M | 68k | 165k | 8.4 | 43 | 132k | claude-opus-5-5:18, claude-sonnet-5:10, claude-opus-5:6 | high:21, xhigh:8, medium:5 |
| decompile-output-guard (wf) | 500 | 3935 | 6 | 446k | 200.20M | 29.80M | 0 | 1.38M | 34k | 55k | 0.6 | 7 | 42k | claude-sonnet-5-5:204, claude-sonnet-5:201, claude-opus-5-5:82 | high:417, medium:82, xhigh:1 |
| planner-xhigh | 5 | 736 | 129 | 1k | 194.95M | 3.37M | 0 | 13k | 57k | 420k | 39.8 | 138 | 326k | claude-opus-5-5:5 | xhigh:5 |
| unknown | 118 | 1894 | 12 | 5k | 150.57M | 8.94M | 0 | 115k | 35k | 67k | 2.5 | 12 | 46k | claude-opus-5-5:49, claude-sonnet-5:45, claude-haiku-4-5-20251001:24 | high:94, None:24 |
| scribe (wf) | 383 | 2919 | 7 | 300k | 110.84M | 19.84M | 0 | 3.18M | 24k | 50k | 1.7 | 9 | 44k | claude-haiku-4-5-20251001:355, deepseek-flash:15, claude-haiku-5-5:13 | None:370, low:13 |
| planner-max | 2 | 332 | 166 | 664 | 104.29M | 2.12M | 0 | 72k | 61k | 591k | 124.8 | 183 | 483k | claude-opus-5-5:2 | max:2 |
| verifier | 89 | 1858 | 16 | 87k | 86.27M | 6.99M | 0 | 474k | 30k | 62k | 6.1 | 15 | 53k | claude-haiku-4-5-20251001:80, claude-haiku-5-5:8, deepseek-flash:1 | None:81, medium:8 |
| planner-medium | 24 | 507 | 17 | 1k | 53.16M | 2.42M | 0 | 13k | 61k | 93k | 1.8 | 20 | 50k | claude-opus-5-5:24 | medium:24 |
| instrument-blindness-reviewer | 45 | 598 | 12 | 41k | 37.33M | 3.55M | 0 | 322k | 33k | 80k | 3.1 | 15 | 82k | claude-opus-5-5:36, claude-opus-5:8, deepseek-v4-pro:1 | high:45 |
| implementer-medium | 22 | 278 | 11 | 562 | 19.19M | 1.68M | 0 | 54k | 53k | 74k | 1.3 | 14 | 19k | claude-opus-5-5:22 | medium:22 |
| docs-sync-reviewer | 28 | 369 | 13 | 71k | 18.46M | 1.62M | 0 | 138k | 32k | 58k | 1.3 | 12 | 49k | claude-sonnet-5:10, claude-opus-5-5:8, claude-sonnet-5-5:8 | high:20, medium:8 |
| planner (wf) | 28 | 208 | 7 | 416 | 11.97M | 1.93M | 0 | 36k | 57k | 68k | 0.7 | 8 | 10k | claude-opus-5-5:28 | high:28 |
| decompile-output-guard | 41 | 192 | 4 | 37k | 7.77M | 1.95M | 0 | 44k | 32k | 42k | 0.2 | 4 | 29k | claude-opus-5-5:15, claude-sonnet-5-5:14, claude-sonnet-5:10 | high:26, medium:15 |
| sdk-contract-reviewer | 6 | 109 | 19 | 85k | 6.95M | 371k | 0 | 90k | 30k | 78k | 3.7 | 18 | 82k | claude-sonnet-5:2, claude-sonnet-5-5:2, claude-opus-5-5:1 | high:5, medium:1 |
| tauri-command-reviewer (wf) | 12 | 93 | 4 | 186 | 4.86M | 604k | 0 | 24k | 34k | 40k | 0.5 | 4 | 2k | claude-sonnet-5-5:6, claude-sonnet-5:5, claude-opus-5-5:1 | high:11, medium:1 |
| Explore | 3 | 56 | 14 | 112 | 5.00M | 371k | 0 | 21k | 38k | 104k | 1.3 | 16 | 151k | claude-opus-5-5:2, claude-opus-5:1 | medium:2, high:1 |
| implementer-medium (wf) | 3 | 66 | 21 | 132 | 4.54M | 216k | 0 | 22k | 51k | 77k | 2.5 | 28 | 35k | claude-opus-5-5:2, claude-sonnet-5-5:1 | medium:3 |
| consultant | 2 | 29 | 14 | 268 | 1.64M | 186k | 0 | 25k | 28k | 95k | 4.0 | 24 | 93k | claude-opus-5-5:1, claude-fable-5-1:1 | xhigh:2 |
| planner-medium (wf) | 3 | 21 | 5 | 42 | 1.28M | 224k | 0 | 4k | 65k | 72k | 0.5 | 7 | 4k | claude-opus-5-5:3 | medium:3 |
| impeccable:impeccable-documenter | 1 | 16 | 16 | 32 | 1.13M | 120k | 0 | 35k | 27k | 120k | 6.2 | 18 | 119k | claude-opus-5-5:1 | medium:1 |
| impeccable:impeccable-finish-reviewer | 1 | 19 | 19 | 38 | 1.04M | 185k | 0 | 16k | 30k | 93k | 201.0 | 29 | 54k | claude-opus-5-5:1 | high:1 |

## Per workorder session

| project/session | start | wall h | main reqs | main max ctx | main cr | main cw | spawns | wf agents | phase spawns | reviewer spawns | billed total | out total | compactions | human msgs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hubwt:hub-forge-pact-update-a9a4ee/c327c8fe | 09-19 08:04 | 8.1 | 220 | 621k | 80.33M | 1.02M | 55 | 38 | 9 | 3 | 471.52M | 3.16M | 0 | 22 |
| hubwt:workorder-resume-yytoolkit-4ed084/e651e4ce | 09-19 16:14 | 1.2 | 33 | 148k | 3.92M | 104k | 18 | 17 | 6 | 4 | 44.52M | 264k | 0 | 5 |
| hubwt:workorder-resume-tracker-release-4a2a1a/a4ed5c2e | 09-19 16:14 | 4.4 | 117 | 254k | 21.66M | 198k | 21 | 21 | 6 | 6 | 81.77M | 417k | 0 | 18 |
| hubwt:workorder-resume-yytoolkit-4ed084/87070e3b | 09-20 10:24 | 11.2 | 163 | 457k | 42.58M | 862k | 34 | 0 | 13 | 21 | 160.21M | 1.08M | 0 | 51 |
| hubwt:workorder-resume-yytoolkit-4ed084/bfdee718 | 09-20 16:24 | 3.2 | 126 | 303k | 25.22M | 237k | 26 | 24 | 11 | 9 | 107.93M | 868k | 0 | 14 |
| hubwt:forgepact-issue-52-0d1b54/ff2e18fc | 09-20 17:39 | 0.5 | 33 | 143k | 3.73M | 96k | 10 | 9 | 4 | 4 | 10.60M | 119k | 0 | 3 |
| hubwt:forgepact-issue-52-0d1b54/687670f2 | 09-20 18:16 | 14.0 | 202 | 458k | 59.24M | 1.29M | 66 | 58 | 27 | 24 | 193.27M | 1.23M | 0 | 45 |
| hubwt:workorder-hs-background-session-3cc870/b6a72c77 | 09-20 19:38 | 11.8 | 192 | 440k | 51.80M | 1.03M | 24 | 21 | 11 | 8 | 127.35M | 797k | 0 | 14 |
| hubwt:forgepact-issue-52-0d1b54/7b6e833f | 09-21 07:08 | 0.8 | 19 | 116k | 1.91M | 73k | 9 | 8 | 4 | 3 | 8.61M | 74k | 0 | 4 |
| hubwt:workorder-hs-background-session-3cc870/d61d18d5 | 09-21 08:18 | 1.8 | 23 | 154k | 2.83M | 185k | 16 | 16 | 6 | 6 | 78.88M | 326k | 0 | 4 |
| hubwt:forgepact-issue-52-0d1b54/1149765d | 09-21 08:18 | 1.6 | 87 | 200k | 13.02M | 153k | 11 | 8 | 5 | 3 | 33.60M | 227k | 0 | 22 |
| hubwt:forgepact-issue-52-0d1b54/bd2015b9 | 09-21 09:55 | 1.9 | 45 | 144k | 5.34M | 162k | 19 | 18 | 7 | 8 | 98.92M | 486k | 0 | 4 |
| hubwt:workorder-hs-background-session-3cc870/6d82062b | 09-21 10:50 | 3.4 | 41 | 172k | 4.90M | 139k | 37 | 32 | 16 | 11 | 89.00M | 666k | 0 | 8 |
| hubwt:workorder-hs-background-session-3cc870/c089f4c1 | 09-21 10:50 | 6.2 | 126 | 278k | 24.24M | 245k | 14 | 8 | 4 | 3 | 73.22M | 364k | 0 | 28 |
| hubwt:forgepact-issue-52-0d1b54/ece90d97 | 09-21 11:57 | 10.4 | 325 | 507k | 98.57M | 928k | 72 | 65 | 30 | 27 | 330.97M | 1.60M | 0 | 63 |
| hubwt:forgepact-issue-52-0d1b54/fc166594 | 09-21 15:05 | 7.3 | 238 | 366k | 55.34M | 550k | 47 | 44 | 20 | 16 | 173.05M | 983k | 0 | 52 |
| hubwt:forgepact-issue-52-0d1b54/f90ad632 | 09-21 22:29 | 16.6 | 230 | 392k | 57.63M | 765k | 33 | 30 | 14 | 12 | 231.66M | 997k | 0 | 40 |
| hubwt:hs-drive-mcp-game-live-gate-8eb3cb/21d58ac6 | 09-22 13:23 | 8.9 | 233 | 485k | 72.29M | 624k | 55 | 48 | 21 | 22 | 170.46M | 1.08M | 0 | 56 |
| hubwt:forgepact-issue-63-08d6b9/2e7a06dd | 09-22 13:26 | 1.8 | 99 | 237k | 16.82M | 193k | 10 | 8 | 5 | 3 | 47.79M | 243k | 0 | 16 |
| hubwt:hero-siege-issue-121-fcc1fd/433734b7 | 09-22 13:26 | 0.7 | 26 | 121k | 2.64M | 76k | 9 | 8 | 4 | 3 | 10.26M | 69k | 0 | 5 |
| hubwt:forgepact-issue-63-08d6b9/8b014920 | 09-22 18:46 | 2.0 | 57 | 212k | 8.64M | 167k | 17 | 14 | 9 | 4 | 60.94M | 434k | 0 | 8 |
| hubwt:hero-siege-issue-121-fcc1fd/fa082d95 | 09-22 18:50 | 22.2 | 371 | 733k | 170.79M | 982k | 166 | 148 | 70 | 62 | 518.88M | 3.14M | 0 | 129 |
| hubwt:workorder-usage-update-349b41/ab564206 | 09-22 21:01 | 13.2 | 121 | 276k | 24.01M | 340k | 45 | 39 | 22 | 13 | 102.05M | 804k | 0 | 25 |
| hubwt:hero-siege-offline-toolkit-72f6fd/afe85552 | 09-23 14:11 | 53.5 | 190 | 500k | 52.90M | 1.92M | 131 | 118 | 62 | 41 | 298.23M | 2.51M | 0 | 33 |
| hubwt:hero-siege-issue-121-fcc1fd/fe6fc695 | 09-23 17:08 | 13.9 | 233 | 587k | 82.87M | 1.03M | 121 | 111 | 48 | 46 | 294.22M | 2.04M | 0 | 70 |
| hubwt:hero-siege-issue-121-fcc1fd/6db2260e | 09-24 07:01 | 9.7 | 219 | 455k | 62.51M | 524k | 113 | 107 | 41 | 48 | 345.41M | 2.16M | 0 | 72 |
| hubwt:workorder-parallelization-2d890c/71f454f3 | 09-24 14:39 | 1.0 | 34 | 159k | 4.50M | 111k | 8 | 7 | 4 | 2 | 34.59M | 238k | 0 | 4 |
| hubwt:affectionate-robinson-d8d594/439ca624 | 09-24 15:45 | 1.2 | 20 | 159k | 2.45M | 113k | 19 | 18 | 7 | 8 | 32.97M | 311k | 0 | 4 |
| hubwt:hero-siege-issue-121-fcc1fd/74b6b5dd | 09-24 16:43 | 3.2 | 177 | 363k | 45.18M | 305k | 37 | 30 | 17 | 12 | 151.31M | 858k | 0 | 46 |
| hubwt:affectionate-robinson-d8d594/f33bf8bc | 09-24 17:41 | 1.1 | 46 | 182k | 6.68M | 133k | 12 | 10 | 7 | 2 | 25.59M | 217k | 0 | 10 |
| hubwt:workorder-parallelization-2d890c/039722c8 | 09-24 20:12 | 60.7 | 697 | 966k | 319.36M | 6.78M | 230 | 160 | 136 | 33 | 1399.10M | 7.27M | 1 | 142 |
| hubwt:hero-siege-offline-toolkit-72f6fd/76440fd6 | 09-25 12:42 | 7.1 | 97 | 355k | 22.22M | 433k | 10 | 3 | 8 | 0 | 147.63M | 427k | 0 | 13 |
| hubwt:hero-siege-offline-toolkit-72f6fd/69c85bf3 | 09-25 20:25 | 9.0 | 74 | 300k | 14.78M | 967k | 32 | 30 | 13 | 12 | 138.89M | 710k | 0 | 8 |
| hubwt:hero-siege-offline-toolkit-72f6fd/3e896cf1 | 09-25 20:26 | 9.0 | 56 | 268k | 11.22M | 519k | 28 | 26 | 11 | 11 | 115.12M | 639k | 0 | 5 |
| hubwt:hero-siege-offline-toolkit-72f6fd/8fc1d54c | 09-26 10:12 | 24.5 | 191 | 503k | 63.46M | 1.89M | 48 | 36 | 23 | 17 | 217.61M | 1.13M | 0 | 18 |
| hubwt:bridge-cse-01BPATbZGkDAktH2cu2P7ZZC/a7e6f66d | 09-27 14:31 | 23.1 | 293 | 724k | 124.10M | 2.89M | 336 | 199 | 101 | 103 | 654.62M | 1.10M | 0 | 76 |
| hubwt:ai-review-workflow-multi-ai-8f2384/30defa84 | 09-27 21:19 | 9.7 | 45 | 228k | 8.41M | 354k | 36 | 31 | 25 | 10 | 84.94M | 141k | 0 | 11 |
| hubwt:forgepact-68-move-all-feab95/0bf5d870 | 09-27 21:49 | 62.1 | 266 | 568k | 90.24M | 2.28M | 167 | 148 | 74 | 54 | 735.99M | 926k | 0 | 61 |
| hubwt:ai-review-workflow-multi-ai-8f2384/03c760ac | 09-28 13:42 | 4.9 | 121 | 330k | 26.86M | 284k | 72 | 65 | 34 | 31 | 176.83M | 300k | 0 | 20 |
| hubwt:issue-tracking-workflow-d1e1d6/5da00fb3 | 09-28 14:04 | 4.4 | 94 | 297k | 19.96M | 354k | 74 | 69 | 32 | 30 | 157.68M | 319k | 0 | 22 |
| hubwt:forgepact-68-move-all-feab95/2f36110f | 09-28 18:54 | 10.2 | 100 | 318k | 23.12M | 1.02M | 52 | 45 | 22 | 20 | 192.27M | 285k | 0 | 10 |
| hubwt:forgepact-68-move-all-feab95/db8c5756 | 09-30 12:25 | 45.0 | 144 | 385k | 37.32M | 751k | 150 | 136 | 60 | 59 | 323.36M | 901k | 0 | 24 |
| hubwt:forgepact-68-move-all-feab95/b735bf95 | 10-02 09:26 | 0.7 | 47 | 210k | 8.41M | 160k | 21 | 18 | 9 | 8 | 21.81M | 69k | 0 | 8 |
| hubwt:issue-tracking-workflow-d1e1d6/59e99632 | 10-02 10:23 | 4.0 | 190 | 445k | 58.10M | 386k | 76 | 55 | 40 | 33 | 133.10M | 314k | 0 | 33 |
| hubwt:ai-review-workflow-multi-ai-8f2384/35e9a1fb | 10-02 10:24 | 5.5 | 146 | 465k | 49.06M | 737k | 109 | 97 | 48 | 50 | 159.85M | 541k | 0 | 17 |
| hubwt:workorder-test-optimization-2395e1/a11816c4 | 10-02 10:24 | 3.8 | 51 | 201k | 7.49M | 270k | 2 | 0 | 2 | 0 | 31.62M | 32k | 0 | 8 |
| hubwt:workorder-test-optimization-2395e1/707873bf | 10-02 11:00 | 2.3 | 87 | 310k | 19.80M | 259k | 93 | 85 | 36 | 51 | 106.09M | 419k | 0 | 14 |
| hubwt:forgepact-workorder-11001d/b82ba883 | 10-02 13:42 | 0.3 | 8 | 136k | 912k | 88k | 1 | 0 | 1 | 0 | 6.83M | 6k | 0 | 1 |
| hubwt:workorder-plan-bdcc3c/ff4212bd | 10-02 13:45 | 0.5 | 6 | 144k | 707k | 96k | 1 | 0 | 1 | 0 | 8.24M | 6k | 0 | 1 |
| hubwt:workorder-plan-7d9295/f60952d0 | 10-02 13:46 | 0.7 | 11 | 152k | 1.47M | 103k | 2 | 0 | 2 | 0 | 8.49M | 8k | 0 | 1 |
| hubwt:workorder-test-optimization-2395e1/f449ad27 | 10-02 14:31 | 6.2 | 140 | 485k | 43.09M | 437k | 196 | 186 | 82 | 104 | 324.51M | 1.18M | 0 | 24 |
| hubwt:workorder-plan-7d9295/7ec90977 | 10-02 14:32 | 5.6 | 164 | 532k | 57.55M | 483k | 182 | 172 | 84 | 77 | 243.92M | 846k | 0 | 20 |
| hubwt:workorder-plan-bdcc3c/b753e32a | 10-02 14:32 | 17.7 | 195 | 702k | 83.78M | 2.29M | 235 | 219 | 116 | 106 | 420.97M | 1.16M | 0 | 29 |
| hubwt:forgepact-workorder-11001d/ecb27cce | 10-02 14:32 | 8.2 | 173 | 523k | 60.54M | 474k | 167 | 151 | 82 | 68 | 300.44M | 973k | 0 | 20 |
| hubwt:workorder-test-optimization-2395e1/5706ebd7 | 10-02 20:44 | 12.4 | 203 | 637k | 84.94M | 1.10M | 94 | 78 | 51 | 32 | 210.52M | 469k | 0 | 33 |
| hubwt:workorder-test-optimization-2395e1/f7268c76 | 10-03 09:10 | 2.8 | 17 | 143k | 2.06M | 187k | 1 | 0 | 1 | 0 | 8.78M | 8k | 0 | 3 |
| hubwt:workorder-plan-bdcc3c/5b96e20f | 10-03 09:11 | 2.8 | 24 | 147k | 3.06M | 192k | 2 | 0 | 2 | 0 | 24.11M | 12k | 0 | 4 |
| hubwt:workorder-performance-audit-5e5fd4/c4555e99 | 10-03 10:23 | 0.4 | 27 | 182k | 3.33M | 134k | 1 | 0 | 1 | 0 | 12.17M | 24k | 0 | 1 |
| hubwt:workorder-performance-audit-5e5fd4/592eb043 | 10-03 11:16 | 0.7 | 34 | 177k | 5.29M | 129k | 13 | 12 | 9 | 2 | 31.12M | 112k | 0 | 5 |
| hubwt:workorder-plan-bdcc3c/73c5f9e9 | 10-03 12:00 | 8.5 | 77 | 325k | 18.32M | 676k | 55 | 48 | 29 | 13 | 130.28M | 390k | 0 | 17 |
| hubwt:workorder-test-optimization-2395e1/ef12c82b | 10-03 12:00 | 8.6 | 97 | 291k | 20.50M | 410k | 67 | 60 | 33 | 17 | 109.25M | 334k | 0 | 12 |
| hubwt:workorder-test-optimization-2395e1/bf987e73 | 10-03 20:38 | 9.9 | 169 | 365k | 46.11M | 623k | 74 | 69 | 31 | 41 | 111.62M | 348k | 0 | 38 |
| hubwt:workorder-plan-bdcc3c/3a62ecda | 10-03 20:38 | 10.8 | 118 | 368k | 30.63M | 711k | 59 | 53 | 27 | 20 | 172.69M | 490k | 0 | 31 |
| hubwt:workorder-performance-audit-5e5fd4/937f03c0 | 10-03 22:12 | 1.2 | 46 | 168k | 6.71M | 120k | 11 | 9 | 5 | 4 | 26.61M | 55k | 0 | 8 |
| hubwt:workorder-stat-forge-values-65fd8d/0bfc6dbe | 10-03 22:14 | 12.8 | 146 | 428k | 42.03M | 597k | 64 | 42 | 34 | 21 | 278.76M | 428k | 0 | 12 |
| hubwt:workorder-plan-bdcc3c/e499739f | 10-04 07:36 | 3.4 | 101 | 310k | 23.53M | 262k | 40 | 36 | 16 | 16 | 106.32M | 256k | 0 | 11 |
| hubwt:workorder-plan-6c5a07/cc986b6f | 10-04 10:38 | 0.3 | 6 | 130k | 648k | 82k | 1 | 0 | 1 | 0 | 12.44M | 6k | 0 | 1 |
| hubwt:workorder-stat-forge-values-65fd8d/69554828 | 10-04 11:03 | 4.4 | 108 | 386k | 31.84M | 614k | 81 | 73 | 40 | 32 | 143.61M | 363k | 0 | 11 |
| hubwt:workorder-plan-bdcc3c/69c43a31 | 10-04 11:04 | 1.3 | 54 | 235k | 10.07M | 187k | 27 | 26 | 10 | 11 | 41.55M | 135k | 0 | 9 |
| hubwt:workorder-plan-6c5a07/cb95c9b0 | 10-04 11:06 | 1.5 | 79 | 259k | 16.00M | 212k | 34 | 26 | 17 | 11 | 41.76M | 156k | 0 | 15 |
| hubwt:workorder-plan-6c5a07/402d3820 | 10-04 12:36 | 4.1 | 136 | 418k | 38.63M | 370k | 76 | 66 | 38 | 23 | 142.94M | 414k | 0 | 16 |
| hubwt:goburins-head-charm-9a0ec8/9ea53f4e | 10-04 12:37 | 3.9 | 110 | 314k | 25.77M | 379k | 42 | 29 | 18 | 18 | 114.88M | 359k | 0 | 17 |
| hubwt:goburins-head-charm-9a0ec8/9740863c | 10-04 16:34 | 1.5 | 59 | 252k | 11.65M | 205k | 37 | 33 | 18 | 12 | 85.92M | 281k | 0 | 5 |
| hubwt:workorder-plan-6c5a07/34649ff7 | 10-04 16:40 | 1.4 | 53 | 227k | 9.99M | 180k | 27 | 23 | 13 | 7 | 73.84M | 151k | 0 | 12 |
| hubwt:workorder-plan-6c5a07/504140ea | 10-04 18:44 | 0.8 | 21 | 196k | 3.27M | 0 | 9 | 9 | 3 | 4 | 26.90M | 277k | 0 | 2 |
| hubwt:goburins-head-charm-9a0ec8/064dcd5c | 10-04 18:48 | 11.6 | 122 | 415k | 32.75M | 0 | 37 | 34 | 17 | 12 | 126.77M | 1.37M | 0 | 17 |
| hubwt:workorder-plan-6c5a07/e84d6142 | 10-04 19:55 | 0.9 | 70 | 304k | 15.64M | 0 | 13 | 5 | 5 | 6 | 27.35M | 341k | 0 | 12 |
| hubwt:goburins-head-charm-9a0ec8/4a5be2cc | 10-05 06:38 | 1.7 | 55 | 263k | 10.49M | 0 | 29 | 27 | 11 | 12 | 51.75M | 761k | 0 | 8 |
| hubwt:goburins-head-charm-9a0ec8/bb7cccbc | 10-05 08:43 | 5.7 | 71 | 371k | 18.72M | 0 | 60 | 54 | 24 | 24 | 257.46M | 2.26M | 0 | 10 |
| hubwt:goburins-head-charm-9a0ec8/50448e7f | 10-05 15:23 | 0.5 | 32 | 202k | 5.01M | 201k | 6 | 0 | 3 | 3 | 18.87M | 70k | 0 | 9 |
| hubwt:goburins-head-charm-9a0ec8/45b76f80 | 10-05 18:08 | 0.7 | 22 | 102k | 2.00M | 70k | 1 | 0 | 1 | 0 | 21.55M | 11k | 0 | 5 |
| hubwt:goburins-head-charm-9a0ec8/f074af34 | 10-05 18:08 | 18.2 | 283 | 520k | 88.66M | 1.16M | 46 | 0 | 28 | 16 | 342.44M | 460k | 0 | 60 |
| hubwt:forgepact-167-satzone-pin/ee5f1aa6 | 10-05 18:40 | 1.6 | 25 | 182k | 3.72M | 149k | 9 | 6 | 6 | 1 | 15.04M | 38k | 0 | 5 |
| hubwt:workorder-plan-6c5a07/57fc144c | 10-05 18:42 | 3.2 | 85 | 284k | 18.39M | 353k | 28 | 18 | 14 | 13 | 44.86M | 126k | 0 | 14 |
| hubwt:forgepact-177-force-color/945656c4 | 10-05 20:21 | 1.8 | 48 | 204k | 8.03M | 202k | 9 | 6 | 6 | 1 | 13.70M | 39k | 0 | 7 |
| hubwt:forgepact-176-ci-history-pins/9f67c6dc | 10-06 12:36 | 1.4 | 55 | 285k | 12.56M | 253k | 14 | 11 | 9 | 4 | 25.00M | 63k | 0 | 11 |
| hubwt:forgepact-151-setup-stall/f2fcefba | 10-06 12:37 | 2.2 | 52 | 207k | 8.18M | 202k | 21 | 17 | 10 | 6 | 78.56M | 129k | 0 | 5 |
| hubwt:forgepact-173-dropmult-gold-crash/78cd48df | 10-06 12:39 | 20.6 | 147 | 427k | 45.58M | 707k | 59 | 42 | 27 | 31 | 143.76M | 294k | 0 | 40 |
| hubwt:forgepact-181-map-reveal-icons/bf13adb6 | 10-06 12:41 | 6.4 | 70 | 310k | 14.77M | 518k | 35 | 28 | 13 | 19 | 56.68M | 155k | 0 | 11 |
| hubwt:forgepact-181-map-reveal-icons/24c5d3b2 | 10-06 14:46 | 4.9 | 112 | 313k | 23.12M | 487k | 45 | 30 | 22 | 22 | 125.54M | 261k | 0 | 24 |
| hubwt:forgepact-151-setup-stall/6a6c233a | 10-06 14:48 | 4.2 | 94 | 286k | 19.29M | 477k | 59 | 54 | 32 | 25 | 85.22M | 364k | 0 | 11 |
| hubwt:forgepact-181-map-reveal-icons/b71c68a9 | 10-06 19:43 | 12.7 | 116 | 361k | 27.41M | 576k | 80 | 70 | 36 | 41 | 93.90M | 287k | 0 | 29 |
| hubwt:forgepact-181-map-reveal-icons/f29c9b5c | 10-07 08:28 | 0.7 | 37 | 185k | 5.79M | 185k | 3 | 0 | 3 | 0 | 8.34M | 23k | 0 | 3 |
| hubwt:forgepact-183/fc13056d | 10-07 09:57 | 0.7 | 11 | 139k | 1.31M | 106k | 1 | 0 | 1 | 0 | 27.25M | 12k | 0 | 3 |
| hubwt:forgepact-183/5d6c856e | 10-07 11:56 | 1.6 | 94 | 339k | 23.37M | 307k | 56 | 45 | 26 | 24 | 59.57M | 266k | 0 | 20 |
| hubwt:forgepact-183/2f3aee09 | 10-07 13:34 | 1.2 | 22 | 171k | 2.89M | 169k | 2 | 0 | 1 | 0 | 54.19M | 22k | 0 | 6 |
| hub/d5a2db65 | 10-07 13:50 | 1.0 | 51 | 224k | 8.70M | 191k | 50 | 42 | 22 | 26 | 40.52M | 156k | 0 | 10 |
| hubwt:forgepact-183/f525c4f3 | 10-07 15:28 | 3.8 | 103 | 387k | 27.15M | 664k | 56 | 46 | 29 | 24 | 81.35M | 284k | 0 | 16 |
| hubwt:forgepact-183/feec553b | 10-07 19:15 | 1.6 | 33 | 173k | 4.72M | 252k | 2 | 0 | 2 | 0 | 107.91M | 26k | 0 | 10 |
| hubwt:forgepact-moveall-loot-satanic/a8dbc0f8 | 10-08 08:09 | 0.4 | 6 | 135k | 674k | 101k | 1 | 0 | 1 | 0 | 25.54M | 5k | 0 | 1 |
| hubwt:forgepact-moveall-loot-satanic/68c4bad4 | 10-08 08:34 | 2.3 | 92 | 366k | 22.90M | 334k | 83 | 74 | 46 | 33 | 118.88M | 380k | 0 | 8 |
| hubwt:forgepact-moveall-loot-satanic/b9f65b2b | 10-08 12:01 | 0.7 | 40 | 199k | 6.36M | 165k | 6 | 0 | 3 | 3 | 8.77M | 26k | 0 | 5 |
| hubwt:forgepact-183/0fec11f1 | 10-08 12:50 | 0.9 | 34 | 205k | 5.81M | 173k | 33 | 30 | 19 | 13 | 64.97M | 257k | 0 | 2 |
| hubwt:forgepact-183/8064c6d5 | 10-08 12:50 | 23.1 | 45 | 247k | 8.15M | 388k | 3 | 3 | 1 | 1 | 11.30M | 48k | 0 | 4 |
| hubwt:forgepact-v2-2-1-hotfix/c75cd805 | 10-09 18:02 | 15.4 | 145 | 346k | 35.86M | 572k | 73 | 62 | 32 | 34 | 145.70M | 351k | 0 | 19 |
| hubwt:tooling-484-x64dbg-mcp/a5ca621c | 10-10 11:24 | 9.4 | 142 | 384k | 33.63M | 791k | 92 | 78 | 47 | 28 | 231.28M | 726k | 0 | 22 |

## Distribution across workorder sessions

- wall: n=106 median=3.934 mean=7.707 p90=17.67 max=62.13
- billed: n=106 median=9.892e+07 mean=1.409e+08 p90=3.234e+08 max=1.399e+09
- out: n=106 median=3.257e+05 mean=5.862e+05 p90=1.181e+06 max=7.27e+06
- spawns: n=106 median=35 mean=50.96 p90=121 max=336
- ph: n=106 median=16 mean=23.08 p90=51 max=136
- rv: n=106 median=12 mean=19.03 p90=48 max=106
- main_req: n=106 median=92 mean=107.9 p90=220 max=697
- main-context share of billed tokens: 22%; subagent+workflow share: 78%

## Spawn tax (first request of each context = fixed spawn context)

| agent | n | first-ctx median | first-ctx p10 | first-ctx p90 | sum of first-ctx | first-request cache-read share |
|---|---:|---:|---:|---:|---:|---:|
| implementer | 939 | 53k | 38k | 55k | 47.42M | 21% |
| workflow-subagent | 782 | 54k | 45k | 61k | 42.47M | 13% |
| verifier | 625 | 30k | 21k | 32k | 17.94M | 15% |
| instrument-blindness-reviewer | 542 | 34k | 25k | 37k | 17.71M | 10% |
| docs-sync-reviewer | 536 | 34k | 27k | 36k | 17.57M | 10% |
| decompile-output-guard | 541 | 33k | 27k | 35k | 17.53M | 9% |
| planner | 334 | 49k | 33k | 57k | 15.91M | 7% |
| sdk-contract-reviewer | 386 | 34k | 28k | 36k | 12.68M | 10% |
| scribe | 383 | 24k | 16k | 32k | 8.95M | 2% |
| live-operator | 104 | 46k | 35k | 47k | 4.57M | 7% |
| unknown | 118 | 35k | 28k | 50k | 4.48M | 18% |
| general-purpose | 34 | 68k | 49k | 71k | 2.21M | 5% |
| planner-medium | 27 | 61k | 53k | 65k | 1.60M | 4% |
| implementer-medium | 25 | 53k | 50k | 61k | 1.37M | 5% |
| tauri-command-reviewer | 12 | 34k | 33k | 35k | 400k | 1% |
| planner-xhigh | 5 | 57k | 54k | 66k | 290k | 7% |
| planner-max | 2 | 61k | 56k | 66k | 122k | 0% |
| Explore | 3 | 38k | 36k | 40k | 115k | 0% |
| consultant | 2 | 28k | 25k | 31k | 56k | 7% |
| impeccable:impeccable-finish-reviewer | 1 | 30k | 30k | 30k | 30k | 0% |
| impeccable:impeccable-documenter | 1 | 27k | 27k | 27k | 27k | 0% |

## Cache health (workorder sessions)

| context | cache-read | cache-write | read:write | uncached input | requests with cw>20k after first |
|---|---:|---:|---:|---:|---:|
| main | 3232.56M | 56.00M | 57.7 | 1.43M | 152 |
| subagent | 4361.84M | 145.01M | 30.1 | 1.55M | 511 |
| workflow | 6744.78M | 326.28M | 20.7 | 6.13M | 774 |

## Main (driver) context: idle gaps

- driver contexts: 106; gaps >5 min between consecutive driver requests: 1073 totalling 739.8 h; driver compactions: 1