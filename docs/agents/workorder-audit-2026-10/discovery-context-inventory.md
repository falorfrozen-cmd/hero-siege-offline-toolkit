# Discovery: context inventory and fixed context budget (/workorder)

Scope: worktree `audit-workorder-architecture` @ c4529da, Claude Code 2.1.296, 2026-10-11. Read-only discovery; no model calls.

**Token method (applies to every token figure):** bytes / 4, rounded, reported with a ±20% range. These are ESTIMATED, never measured. Labels: **SV** = statically verified (file read / observed in this subagent's own context), **EST** = estimated, **HYP** = hypothesis.

## 1. What loads, where, when

| Item | Bytes | Est. tok (±20%) | When | Contexts | Label |
|---|---|---|---|---|---|
| `CLAUDE.md` (imports `@AGENTS.md`, CLAUDE.md:1) | 1,711 | 0.4k | session start / subagent start | main + every subagent (observed in this general-purpose subagent) | SV |
| `AGENTS.md` | 62,146 | 15.5k (12.4–18.6k) | same, via import | same | SV |
| **CLAUDE.md + AGENTS.md** | 63,857 | **16.0k (12.8–19.2k)** | | | SV/EST |
| Nested submodule `CLAUDE.md`+`AGENTS.md` (main checkout only; submodules not initialised in this worktree — `git submodule status` all `-`) | 460 + 2.8–4.4KB each (HS-AFK-Expedition 7,892) | 0.8–2.1k each | lazily, when a file under that dir is read | whichever context reads there | SV (sizes) / HYP (lazy-load trigger) |
| `.claude/rules/` | absent | 0 | — | — | SV |
| User `~/.claude/CLAUDE.md` | absent | 0 | — | — | SV |
| Auto memory `MEMORY.md` index | 5,891 | 1.5k (1.2–1.8k) | session start | main; **also this general-purpose subagent** (it is in my system-reminder) | SV for general-purpose; HYP for custom agents |
| Memory topic files (39 + index = 40 files, 67,504 B total) | 61,613 excl. index | 15.4k if all read | on demand only | — | SV |
| Skill listing (descriptions) | ~17KB observed in this context | ~4.3k | session start | main + contexts with `Skill` tool (planner, implementer have `Skill`) | EST / HYP for custom agents |
| Agent-type listing (Agent tool description) | ~18KB (custom agent frontmatter alone sums 15,250 B; ghidra tool lists ~1.2KB each ×8 agents) | ~4.5k | session start | contexts with the `Agent` tool (main, general-purpose); not planner/implementer/verifier etc. (no `Agent` in `tools:`) | EST |
| Deferred-tool name list (~470 names) | ~14KB | ~3.5k | session start | observed in this subagent | EST; tool search **observed active** (tools shown as deferred); no `ENABLE_TOOL_SEARCH` set anywhere (grep: none) |
| MCP server instructions block (github, hs-drive, clauth, context7, Claude Docs) | ~4.5KB | ~1.1k | session start | observed in this subagent | EST |
| `/workorder` `SKILL.md` | 101,654 | **25.4k (20.3–30.5k)** | per invocation | main (driver) | SV/EST |
| `submodule-context` `SKILL.md` | 5,657 | 1.4k | per invocation (by planner/implementer) | invoking agent | SV; reads guides by section (submodule-context/SKILL.md:31-37) — important because `docs/submodules/ForgePact/instructions.md` is **1,254,866 B / 5,190 lines (~314k tok)** |
| Other project skills (13, design/animation) | 4.4–27.8KB bodies | 1.1–7k each | on invocation only | — | SV |
| `.claude/README.md` | 99,985 | 25k | only if Read | — | SV |
| `.claude/workflows/workorder-rounds.js` | 146,312 | (not model context) | runs as code; its `meta` appears in skill listing as `workorder-rounds` | — | SV (listing observed) |
| `.codex/` (agents/*.toml ×16, config.toml, hooks.json) | — | 0 for Claude | never for Claude Code | Codex only | SV |
| `.agents/skills/` (source; mirrored to `.claude/skills/`) | — | 0 directly | — | Codex | SV |

User scope: `~/.claude/skills/` has 13 skills; 11 share names with project skills (animate, apple-design, …, byte-identical sizes) plus `animate-expo` (18,154) and `write-swift` (42,841); listing shows each name once (SV, observed). No user `agents/`, `commands/`, `workflows/`, `settings.local.json`, `CLAUDE.md`. No managed settings (`C:\ProgramData\ClaudeCode` absent). `policy-limits.json` / `remote-settings.json` carry no model/context settings.

## 2. Agents (`.claude/agents/`, 16 files, 325,670 B)

All have `name, description, tools, model, effort, color`; sources also carry **`effort-variants:`** (unknown to Claude Code, consumed by `tools/sync_agent_tooling.py`). Generated variants carry a `# Generated …` YAML comment inside frontmatter. **None has `maxTurns`, `omitClaudeMd`, `skills`, `mcpServers`, `memory`, `hooks`, `isolation`.** No description contains "proactively"/"always"/"whenever"; live-operator's contains "must" (in "a person must take"), not a trigger word.

| Agent | model | effort | #tools (ghidra/hs-drive) | desc chars | body B | body tok |
|---|---|---|---|---|---|---|
| planner (+medium/xhigh/max) | opus | high (medium/xhigh/max) | 33 (23 ghidra) + Skill, Write, Edit | 223 (315–321 variants) | 42,682 | 10.7k |
| implementer (+medium) | opus | high (medium) | 34 (23 ghidra) + Skill, Monitor | 255 / 361 | 25,254 | 6.3k |
| verifier | **haiku** | medium | 4 | 268 | 19,113 | 4.8k |
| consultant (+max) | opus | xhigh (max) | 30 (23 ghidra + Bash) | 318 / 416 | 6,353 | 1.6k |
| scribe | haiku | low | 3 (Read, Grep, Edit) | 196 | 2,953 | 0.7k |
| live-operator | opus | medium | 33 (27 hs-drive) | 514 | 9,268 | 2.3k |
| decompile-output-guard | opus | medium | 4 | 341 | 7,544 | 1.9k |
| docs-sync-reviewer | opus | medium | 4 | 298 | 8,637 | 2.2k |
| instrument-blindness-reviewer | opus | high | 4 | 364 | 10,054 | 2.5k |
| sdk-contract-reviewer | opus | medium | 4 | 343 | 7,156 | 1.8k |
| tauri-command-reviewer | opus | medium | 4 | 291 | 6,153 | 1.5k |

Flags (SV):
- No `omitClaudeMd` on any agent while CLAUDE.md+AGENTS.md is ~16k tok — scribe (0.7k body) and every reviewer pay 16k of hub rules first.
- No `maxTurns` anywhere (only prose turn budgets).
- Variants are generated duplicates: `diff planner.md planner-{medium,xhigh,max}.md` = 12 diff lines each (name, description, `effort`, removal of `effort-variants`, added comment); same 12 lines for implementer/implementer-medium and consultant/consultant-max. Bodies byte-identical (42,682 / 25,254 / 6,353). Cost: 4 planner + 2 implementer + 2 consultant entries in the agent listing, each repeating a ~1.2KB ghidra tool list (~8 × 1.4KB ≈ 11KB ≈ 2.8k tok of listing duplication, EST).
- Bodies restating AGENTS.md (path:line both sides):
  - planner.md:75-82 ↔ AGENTS.md:286-294 (empty callers/xrefs = "not observed", FindCallers E8/E9 blindness). **Drift**: planner states the reference table "is mostly empty" as fact; AGENTS.md:288-290 says it is inferred from one probe.
  - planner.md:212-221 and implementer.md:46 ↔ AGENTS.md:188-194 ("After a write, read the diff, not the file").
  - planner.md:250-262 ↔ AGENTS.md:153-176 (Spend each check once; full-verify cost figures).
  - planner.md:586 ↔ AGENTS.md "A question never idles the pipeline" (AGENTS.md:§Spend Each Check Once).
  - planner.md:711-724 ↔ AGENTS.md Legal (decompiled output), "Never Call an Address", "Don't Suspend the Game's Own Runtime", "Prove the Instrument" (shared-SDK correction, AGENTS.md:525ff).
  - consultant.md:67-75,103,115 and instrument-blindness-reviewer.md:81,97,113 ↔ AGENTS.md:525ff (positive control, "not observed").
  - decompile-output-guard.md:42 ↔ AGENTS.md Legal ("door script rolls the same die" paraphrase example, verbatim).
- Skills preloaded: none (`skills:` unused).
- `planner`/`implementer` carry `Skill`: they will see the full skill listing (~4.3k, includes ~30 irrelevant design/taste skills) — HYP.

## 3. Hooks (every scope)

| Source | Event | Matcher / filter | Type | Timeout | Sync | Does | Injects | In subagents? |
|---|---|---|---|---|---|---|---|---|
| `.claude/settings.json:19-31` | PostToolUse | `Edit\|Write\|Bash\|PowerShell\|NotebookEdit` | command `py -3 post_tool_use.py` | 60 s | sync | 4 tree checks (below) | stderr only; exit 2 blocks (feeds message back) | HYP yes (settings PostToolUse hooks apply to subagent tool calls) |
| impeccable plugin `hooks/hooks.json` | PostToolUse | `Edit\|Write` | command `impeccable hook` | 5 s | sync | design detector | possible stderr | HYP yes |
| impeccable plugin | **Stop** | — | command `impeccable hook` | 30 s | sync | "Design deep pass" | possible block/feedback at turn end | HYP main only (Stop ≠ SubagentStop) |
| clauth plugin (user) | SessionStart ×2 | — | `clauth hook-profile-changed-note`, `clauth self-heal` | 10 s / 60 s | sync | profile note, self-heal | may add context | — |
| clauth | UserPromptSubmit | — | `clauth hook-profile-changed-note` | 10 s | sync | | may add context | main |
| clauth | PostToolUse | **no matcher → every tool call** | `clauth hook-profile-changed-note` | 10 s | sync | | may add context | HYP yes |
| clauth | PostToolUse | `^mcp__(plugin_clauth_)?clauth__delegate$` | `clauth mcp-await-job` | 4260 s | `asyncRewake` | waits on delegate | rewake message | — |
| `.codex/hooks.json` | PostToolUse | `Bash\|apply_patch\|Edit\|Write` | same dispatcher | 60 s | — | Codex only | | n/a |

`post_tool_use.py` per matching call (SV from source): starts Python, `git rev-parse --show-toplevel` (_common.py:151), one hub `git status --porcelain -z -uall` (_common.py:87-88) plus **one parallel `git status` per submodule** (_common.py:104-114; 11 submodules), then:
1. `catalog_signature` — if `catalog/` dirty: runs `tools/minisign.py verify` (catalog_signature.py:42-55).
2. `tauri_command_guard` — parses dirty `hub/src-tauri/src` files.
3. `hub_frontend_tests` — if any top-level `hub/src/*.js` is dirty: **runs `node --test` over every `hub/src/*.test.js`** (hub_frontend_tests.py:35-56; "about a fifth of a second"/"a second", docstring).
4. `decompiled_output` — `git diff HEAD --unified=0` per dirty watched file (decompiled_output.py:166-167), scans added lines.

Key property (SV): checks key off **working-tree dirtiness, not the edited file** (hub_frontend_tests.py:31-33, catalog_signature.py:34-37). Once `hub/src/*.js` or `catalog/` is dirty, *every* subsequent Edit/Write/Bash/PowerShell call in every context (incl. verifier's Bash runs) re-runs node tests / minisign. Cost per call EST 0.2–2 s (process start + ≥12 git processes), unmeasured. Skip switch: `HSTK_SKIP_HOOKS`.

## 4. MCP

- `.mcp.json`: 7 servers — tauri-hub, hs-drive, ghidra, context7, playwright, figma, github (SV). `settings.local.json` lists 4 in `enabledMcpjsonServers` **but sets `enableAllProjectMcpServers: true`**, so all 7 load (observed: ghidra/playwright/figma tools present in this context).
- Plugin: clauth (4 tools). claude.ai connectors: ~19 servers × auth stubs + Claude Docs (~8 tools).
- Approx tool counts observed in this context's deferred list (EST, hand count): ghidra ~225, github ~46, hs-drive 27, playwright 25, tauri-hub 19, context7 2, figma 2, clauth 4, claude.ai ~46 → **~470 tool names**.
- Tool search / deferred loading: **observed active** in this subagent (tools listed as deferred). Not set explicitly in any settings/env (SV grep). Whether custom agents with explicit `tools:` lists get the 23 ghidra / 27 hs-drive schemas eagerly or deferred: HYP / INSUFFICIENT EVIDENCE.

## 5. Model / effort / settings

- No `model` in user or project settings; no `CLAUDE_CODE_SUBAGENT_MODEL` (SV, env + grep). Observed env `CLAUDE_EFFORT=medium` in this subagent.
- `permissions.defaultMode: auto` (user settings). `outputStyle: Concise`, `skipWorkflowUsageWarning: true`, `worktree.baseRef: fresh`, `remoteControlAtStartup: true`.
- Absent (SV grep): `cleanupPeriodDays`, cache TTL settings, `workflowSizeGuideline`, `maxTurns`, `omitClaudeMd`.
- User `env: {}`. Process env carries a plaintext `GITHUB_MCP_PAT` (expected from `tools/setup_agent_secrets.py`; value not reproduced).

## 6. Anti-pattern grep (§0.8) across `.claude/`, `tools/`, `.agents/`, `.codex/`

| Pattern | Result | Evidence |
|---|---|---|
| `claude -p` from scripts | none | SV grep |
| Stop / SubagentStop hooks in repo | none in repo; **impeccable plugin adds a Stop hook (30 s)** | plugin hooks.json |
| prompt/agent-type hooks | none (all `type: command`) | SV |
| `@file` / `!cmd` injection in SKILL.md bodies | none found (regex scan, 14 skills) | SV |
| Agent bodies told to spawn subagents | none; implementer.md:237 says it *cannot* spawn; planner/verifier only describe being spawned | SV |
| Subagents told to return full output | **yes, in workflow**: `"its whole output in 'raw_output'"` workorder-rounds.js:1065, 1083, 1102, 1443, 1551 (schemas :346-365, :1045, :1201). Mitigated: results go to JS, which uses `tail()` (:1068, :1086, :1110, :1445); but `lintFailure = r.raw_output` (:1555) keeps the whole output. Also "IMPL-DONE report handed to the join verbatim" implementer.md:318 | SV |
| Untyped workflow agents | 8 `agent()` call sites with `model: 'haiku'` and **no `agentType`** (:1066, :1084, :1103, :1267, :1444, :1552, :1786, :1864) — "Run exactly <one command>" jobs that load as the default agent type with full CLAUDE.md/AGENTS.md, memory, listings | SV (call sites) / HYP (default type) |

## 7. FIXED CONTEXT BUDGET (per spawn, before any task work)

System prompt + built-in tool schemas: **INSUFFICIENT EVIDENCE** (not readable from disk); only known parts given. All tok = bytes/4, ±20%, ESTIMATED.

| Context | Sys prompt + tools (known part) | CLAUDE.md+AGENTS.md | Memory | Agent/skill descriptions | MCP listing | Agent body | Preloaded / invoked skill | **Known total** |
|---|---|---|---|---|---|---|---|---|
| Main session (/workorder driver) | INSUFF. EVID. + all MCP deferred | 16.0k | 1.5k | skills 4.3k + agents 4.5k | names 3.5k + instr 1.1k | — | /workorder SKILL 25.4k | **56.3k (45–68k)** |
| planner (×4 variants) | INSUFF. + 23 ghidra schemas (HYP 3–8k) | 16.0k | 1.5k (HYP) | skills 4.3k (HYP, has Skill) | ghidra (in tools col) | 10.7k | submodule-context 1.4k when invoked | **33.9k (27–41k)** + ghidra |
| implementer (×2) | INSUFF. + 23 ghidra (HYP 3–8k) | 16.0k | 1.5k (HYP) | skills 4.3k (HYP) | — | 6.3k | submodule-context 1.4k | **29.5k (24–35k)** + ghidra |
| verifier (haiku) | INSUFF. (4 tools) | 16.0k | 1.5k (HYP) | — | — | 4.8k | — | **22.3k (18–27k)** |
| consultant (×2) | INSUFF. + 23 ghidra (HYP) | 16.0k | 1.5k (HYP) | — | — | 1.6k | — | **19.1k (15–23k)** + ghidra |
| scribe (haiku) | INSUFF. (3 tools) | 16.0k | 1.5k (HYP) | — | — | 0.7k | — | **18.2k (15–22k)**; 96% is hub rules + memory |
| reviewers (5) | INSUFF. (4 tools) | 16.0k | 1.5k (HYP) | — | — | 1.5–2.5k | — | **19.0–20.0k each** |
| live-operator | INSUFF. + 27 hs-drive schemas (HYP 3–6k) | 16.0k | 1.5k (HYP) | — | hs-drive instr ~0.2k | 2.3k | — | **20.0k (16–24k)** + hs-drive |
| workflow untyped haiku agents (8 sites) | INSUFF. + all tools deferred (HYP general-purpose) | 16.0k | 1.5k | skills 4.3k + agents 4.5k (HYP) | 3.5k + 1.1k | — | — | **30.9k (25–37k)** to run one command (HYP) |

Observations: CLAUDE.md+AGENTS.md (16.0k) is the single largest fixed cost in every subagent and ≥70% of the known budget for scribe, verifier, consultant, reviewers and live-operator. The driver additionally carries 25.4k of `/workorder` SKILL.md.
