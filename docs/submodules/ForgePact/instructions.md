# ForgePact Module Development Guide

## Module Overview & Metadata
- **Module Name:** ForgePact (Hero Siege Season 10 Offline Mod Panel & BloodPactPlugin)
- **Submodule Path:** `ForgePact`
- **Reviewed Git Revision (upstream, `origin`):** `2751679` (Tag: `v1.3.16`, Branch: `main`) — `falorfrozen-cmd/ForgePact`.
- **Revision Date:** `2026-09-10 09:21:05 +0300`
- **Commit Message:** `Prepare ForgePact 1.3.16 Headhunter release` — includes upstream's independent fix for the `VALUE_REF` player-resolution bug class in the Headhunter kill/steal path (`HhResolveInstance`, commits `7743a99`/`4ae4e30`), the same bug class described below.
- **Fork & Branch:** This guide additionally tracks work rebased onto that revision and pushed to `fork` (`S-Borkowski/ForgePact`) as **`release/v1.3.17`** — the version is 1.3.17, not 1.3.16, precisely because upstream had already shipped 1.3.16 by the time this branch was rebased onto it. See `release-notes-v1.3.17.md`. The branch has since grown a second release, **1.3.18** (`release-notes-v1.3.18.md`: the map-reveal pack pass and the Pet Quest Collector); the branch name is kept as-is because the open PR to origin tracks it.
- **Source Availability:** Full application source is present (Python control panel `src/forgepact.py`, C++20 native mod plugin `plugin/ModuleMain.cpp`, modified YYToolkit patches `yytoolkit-modified/`, build scripts `plugin_build/build.bat` and `build_release.py`, Python contract tests `tests/`, and reverse-engineering research notes `docs/`).
- **CI / Pipeline Availability:** `notify-hub.yml` (push to `main`, bumps the hub's submodule pointer), `notify-hub-release.yml` (fires on a published release, skips prereleases), `forgepact-notes-cleanup.yml` (fires on a published release, skips prereleases; deletes the `release-notes-v*.md` files at or below that version from `main`), `forgepact-tag.yml` (`workflow_dispatch`, tags a release, leaves a draft, and dispatches the build) and `forgepact-release.yml` (`workflow_dispatch` against `main` with a `tag` input; fetches the pinned toolchain, compiles and packages the tagged tree, and uploads the zip to that tag's draft — see "Tagging a release (forgepact-tag.yml)" below, "The build half (forgepact-release.yml)"). Verification is otherwise conducted locally via Python unittest test suites and static build audits.
- **Purpose & Scope:** Standalone offline control panel and native runtime hook plugin providing runtime modifiers for Hero Siege single-player sessions. Controls monster density, special content spawns (Rift Portals, Battlefields, Cursed Orbs, Chaos Tower, Shadow Realm, etc.), drop rate multipliers and gated drop families (Keys, Relics, Angelic/Unholy uniques), gameplay mods (relic drop pool filter excluding maxed 10/10 relics, orb pickup radius, pet-driven quest item collection), player/combat stat scaling, full map reveal (fog, plus an optional pass that makes each new zone's spawners create their packs on arrival so monsters appear on the revealed map), and custom forge mechanics (Headhunter, Tyrant's Crown, Beacon, Item Editor base stat export) without permanently altering save files or the base game executable. Integrated with `hs-game-sdk`.
- **Fork Branch vs. This Guide:** `release/v1.3.17` (`fork`) carries the Mods tab (relic filter, orb pickup, the Headhunter/Tyrant's Crown/Beacon/Map Reveal relocation), the build-order packaging guard, the stall watchdog, the `SafeF()` crash guard, and a second, complementary `VALUE_REF` player-resolution fix (`HhUsableInstance`, used by orb pickup and the relic filter's `HhResolveLocalPlayer` calls — distinct from upstream's `HhResolveInstance`, which fixed the same bug class for the Headhunter kill/steal path only). All covered by `tests/test_relic_filter_contract.py` (updated to match the merge) and documented in Known Limitations items 4-9 below; none are optional cleanup, all were needed to reach a working build.

---

## Architecture & Repository Map

### Repository Layout
- `src/`: Python application frontend and control panel runtime.
  - `forgepact.py`: Single-file local web/desktop application (`http://127.0.0.1:8766`). Manages port selection, configuration persistence (`%LOCALAPPDATA%\Hero_Siege\forgepact.json`), background game process detection / auto-apply watcher, PE binary patching / backup / restoration via `AuriePatcher.exe`, and file-based IPC dispatch to `bp_ipc/cmd.txt`.
- `plugin/`: Native GameMaker mod plugin implementation.
  - `ModuleMain.cpp`: C++20 dynamic library source for `BloodPactPlugin`. Implements Aurie module lifecycle (`ModuleInitialize`), hooks GameMaker engine routines via YYToolkit, manages frame event callbacks (`EVENT_FRAME`), polls commands from `bp_ipc/cmd.txt`, logs responses to `bp_ipc/out.txt`, applies throttled density/spawn overrides, manipulates drop tables and LoadDrops gates, projects HUD head labels, and exports live item statistics to `bp_ipc/itemstats.json`.
  - `BUILD.md`: Build requirements, compilation instructions, and differences between shipping (`/DFORGEPACT_RELEASE`) and research builds.
- `plugin_build/`: Plugin compiler script and build workspace.
  - `build.bat`: MSVC x64 batch script compiling `plugin/ModuleMain.cpp` into `BloodPactPlugin_ship.dll` (player build) or `BloodPactPlugin_rel.dll` (research build).
- `modfiles_shipped/`: Shipped binaries deployed to the game's `bin/` directory upon mod installation.
  - `AurieCore.dll`: Aurie Framework core loader binary (unmodified AGPL-3.0).
  - `AuriePatcher.exe`: Aurie PE import/bootstrap patcher (unmodified AGPL-3.0).
  - `YYToolkit.dll`: GameMaker runtime interface library built with modified startup cache and disabled `ExecuteIt` hook (AGPL-3.0).
  - `BloodPactPlugin.dll`: Pre-compiled release build of the mod plugin.
  - `HSOfflineTrackerProducer.dll` (Optional): Read-only telemetry sensor for the companion HS Offline Tracker tool.
- `yytoolkit-modified/`: AGPL-3.0 compliance source notices and patches for the modified YYToolkit library.
  - `NOTICE.md`: Detailed rationale, file listing, and rebuild instructions for modified YYToolkit files.
  - `Generic-RunnerInterfaceNew.cpp`: Adds a disk cache (`<exe>.yytkcache`) and density-sorted `.text` page pre-filter to make the RunnerInterface search instantaneous instead of a ~1 minute full `.text` disassembly.
  - `source/YYTK/Hooks.cpp`: Disables the buggy `ExecuteIt` hook (`EVENT_OBJECT_CALL`), eliminating Hero Siege Season 10 crash loops and instance lookup corruptions while preserving `EVENT_FRAME` via `HkPresent`.
- `tests/`: Automated Python contract test suites validating plugin source invariants and panel logic without requiring a running game instance.
  - `test_density_reentry_contract.py`: Validates spawner object name lookups, stable spatial identity keys, and density placement guards.
  - `test_enemy_speed_contract.py`: Verifies enemy speed multipliers, Chaos Tower scoping, and release command accessibility.
  - `test_mod_backup.py`: Tests clean PE backup verification, build mismatch detection, stale backup archival, and atomic restore rollbacks.
  - `test_necro_balance_contract.py`: Validates Necromancer balance formulas, fail-closed runtime contracts, and panel visibility.
  - `test_map_reveal_contract.py`: Validates the map-reveal mod and its `map_reveal_packs` sub-toggle - defaults, `build_cmds` parent/child emission, the release-guarded `reveal stat`, and the guardrails that keep it from unlocking waypoints, writing the player's minimap options, or sweeping `isDiscovered`. Also pins the 2026-09-11 regression: the pack pass must wait for a creator to report a real `enemyCreatorTimer` before lying about distance, because firing during zone load leaves the spawners inert and the zone emptier than vanilla.
  - `test_map_reveal_behavior.py` + `map_reveal_harness.cpp`: **Behavioral** regression suite for the pack pass - compiles the real `MapRevealManager` and the real `Hook_distance_to_object` against controlled game-API responses and calls the hook at the point in the frame order where it matters (before the next `OnFrame`). Exists because the source-string assertions in `test_map_reveal_contract.py` passed throughout the period when the authorization was checked at the wrong point in the frame; see Known Limitations item 13. Skips without a C++ toolchain, like `test_headhunter_dispatch.py`.
  - `test_pet_quest_collector_contract.py`: Validates the Pet Quest Collector — the panel toggle and its `build_cmds`/live dispatch, the target set (`Quest_Object_Parent_obj` descendants minus a static exclusion list, checked against `hs-game-sdk`'s real hierarchy so a future SDK change cannot silently widen it), and the invariants that keep the shipped collect honest: exactly one call shape and it is the measured one, the game's own `canPickup`/`lootType == 0` gates re-read per item rather than cached from selection, `other` = `Loot_Manager_obj` rather than the player (the static read guessed the player and was wrong), one item at a time with a cooldown, and no pet means no collecting. Also pins every `citrace` research command as release-guarded, absent from `kPlayerCommands`, and — for the mutating ones — behind the `confirm` gate that fails closed (56 tests; the largest suite).
  - `test_release_hook_contract.py`: Validates zero eager gameplay hooks in release builds, all-off pass-through behavior, and telemetry exclusions.
  - `test_repo_bounds_contract.py`: Tests boundary protection and index validation against Season 10 item/relic categories.
  - `test_relic_filter_contract.py`: Validates the relic drop pool filter, orb pickup radius mod, build-order packaging guard, player-resolution against `VALUE_REF`, the stall watchdog's research-build presence/ordering, and the Map Reveal / Headhunter / Tyrant's Crown / Beacon panel relocation (29 tests, covering everything fixed 2026-09-09/10).
- `docs/`: Reverse-engineering research logs, memory audits, and drop rate analysis.
  - `S10-special-content-notes.md`: Detailed Season 10 reverse-engineering log for special content spawners, gate mechanisms, crash thresholds, and investigated workarounds.
  - `dungeon-key-research.md`: Documentation of the two-stage key/relic drop architecture (`LoadDrops` outer gate + `droprate.base` inner roll).
  - `angelic-drop-research.md`: Analysis of Angelic/Unholy drop rates and synthetic drop roll implementation.
  - `blood-pact-values-research.md`: Research findings on Blood Pact modifiers and stat calculations.
  - `satanic-zone-mods-research.md`: Live-tested findings on the Satanic Zone buff/debuff pool - why the originally-planned routine hook (`LoadSatanicZone`) doesn't work, and the poll-and-correct mechanism that shipped instead.
  - `pet-quest-collector-plan.md`, `pet-quest-collector-research.md`: The original Pet Quest Collector plan (mechanisms B1/B2) and its research log - 34 hooked call sites reporting 0 calls on multiple confirmed collects. **Read with the correction in the Plan C log:** that 0 was the instrument, not the game (see the `HookOneScript` note below); the conclusions drawn from it about the game's behaviour do not hold.
  - `pet-quest-collector-plan-b4-input-simulation.md`, `pet-quest-collector-b4-research.md`: Plan B4 (fake the player's hover + keypress) and its research log. Disproven live: the GML-visible input state is a downstream mirror of real device input, so writing it changes nothing.
  - `pet-quest-collector-plan-c-direct-invocation.md`, `pet-quest-collector-c-research.md`: **The plan that worked, and the log that closed it.** Invoke the quest item's own `m_Quest*` bound methods rather than any named routine - name-free, so unaffected by the named-routine-table wall that closed B1/B2 - with Ghidra as an explicit, anchored fallback (Phase C1), which is the half that actually found the mechanism. Confirmed by reproduction on 2026-09-11 (a plugin-invoked collect advanced a quest counter 7/15 -> 8/15), then shipped as Phase C2 and live-measured as the mod (`collected=3` and `collected=6` across two sessions, every failure counter at zero). The research doc also carries the correction that matters most to future work here: **`HookOneScript` is blind against this build's compiled GML** - it swaps a pointer inside the script-table entry, and compiled GML calls another script with a direct `call rel32` that never reads that table, so every "0 calls" result from a named-script hook in these notes measured the instrument, not the game. Use `MmCreateHook` on the resolved address (`citrace nativetrace`) when a named-script hook reports zero.
  - `menu-pause-plan.md`: A complete design for "pause the world while a menu is open" (freeze monsters, player, mercenary, pet, damage and every timer), researched to the point where the mechanism was clear - and **closed as not recommended**, which is why it is worth keeping. Its §0 is the general rule: features that suspend or take over the game's own runtime loop (pause, time scaling, save-state/rewind, wholesale instance deactivation) invert this plugin's failure mode from "does nothing" to "player's session is stuck", cannot be verified by the contract tests, and tax every future game patch. See `AGENTS.md`, "Don't Suspend the Game's Own Runtime". Nothing in it was measured in-game; its Phase 0 costs one session and no rebuild (the research build's `cb` command already calls the builtins involved) and is the right first step if the feature is ever wanted anyway.
- `build_release.py`: Packaging script creating the frozen PyInstaller distribution at `dist/ForgePact/` with release guard checks.
- `tools/`: Developer-loop helpers (not shipped to players).
  - `ghidra/ImportSymbols.java`: Names a stripped `Hero_Siege.exe` in Ghidra from the game's own runtime script table. `Hero_Siege.exe` is a YYC build (~280 MB, every GML script compiled to native code, no symbols), so a decompiler shows `FUN_14xxxxxxx` everywhere - three research sessions stalled on exactly that. The fix needs no disassembler: the running game already knows every script's name (`script_get_name(i)`) and address (`GetNamedRoutinePointer`). Run `citrace symdump` in the research build to write `bp_ipc\symbols.csv`, then run this headless with `-noanalysis` to create and name a function at each RVA. Covers the runtime-only `anon@N@gml_Object_..._Create_0` closures that `hs-game-sdk`'s static table does not have. Reusable by any tool or mod that needs to read this binary, not just the one it was built for - see `ForgePact/docs/pet-quest-collector-c-research.md`.
  - `ipc.ps1`: Sends a command to the *running* plugin and prints only its reply. Resolves `bp_ipc` from the panel's own `forgepact.json`, records `out.txt`'s byte length before writing `cmd.txt`, waits for the game to actually consume it, then prints just the appended lines. Replaces the hand-driven "edit cmd.txt, then scroll a multi-megabyte out.txt" loop every research session used before 2026-09-11 - see `AGENTS.md`'s "Limit Rebuilds & Reruns". Usage: `.\ForgePact\tools\ipc.ps1 citrace methods`, `-Lines "petquest 1","petquest stat"` to batch, `-Tail 40` to just read. A timeout means the game is not running or the plugin did not load.

---

## Component Architecture & IPC Pipeline

```text
+---------------------------------------------------------------------------------------+
|                                  FORGEPACT PANEL (Python)                             |
|                                                                                       |
|   +------------------------------------+      +-----------------------------------+   |
|   |          src/forgepact.py          |      |         Process Watcher           |   |
|   |  - HTTP Server (127.0.0.1:8766)    |      |  - Background thread (5s poll)    |   |
|   |  - Web UI / Sliders / Settings     |      |  - Auto-applies on game start     |   |
|   |  - Mod Installer & Exe Backup      |      |  - Detects new process boot count |   |
|   +-----------------+------------------+      +-----------------+-----------------+   |
|                     |                                           |                     |
|                     +---------------------+---------------------+                     |
|                                           |                                           |
|                                           v                                           |
|                           [ Writes lines to bp_ipc/cmd.txt ]                          |
+-------------------------------------------|-------------------------------------------+
                                            |
                                            v (File-based IPC in <game>/bin/bp_ipc/)
+---------------------------------------------------------------------------------------+
|                                    GAME PROCESS (Hero_Siege.exe)                      |
|                                                                                       |
|   +-------------------------------------------------------------------------------+   |
|   | AurieCore.dll  --->  YYToolkit.dll  --->  BloodPactPlugin.dll                 |   |
|   +-------------------------------------------------------------------------------+   |
|                                           |                                           |
|                                           v (FrameCallback / PollCommands)            |
|   - Reads & clears bp_ipc/cmd.txt every 30 frames (~2x/second at 60 fps)              |
|   - Appends status/replies to bp_ipc/out.txt                                          |
|   - Writes current item stats to bp_ipc/itemstats.json (max once every 2 seconds)     |
|                                           |                                           |
|               +---------------------------+---------------------------+               |
|               |                           |                           |               |
|               v                           v                           v               |
|     [ Spawner Throttling ]       [ Drop Gating & Rates ]     [ Stat / Combat Hooks ]  |
|     - Multiplies markers         - Scales droprate.base      - Hooks GetBloodPactInfo |
|     - Clears Chaos Tower /       - Opens LoadDrops gates     - Enemy speed scaling    |
|       Shadow Realm run flags       (Keys, Relics only)       - Headhunter / Tyrant /  |
|     - Queued spawn per frame     - Gated synthetic rolls       Beacon mechanics       |
+---------------------------------------------------------------------------------------+
```

---

## Representative Change Workflow

To add or modify a gameplay modifier or runtime command:

1. **Update Plugin Implementation (`plugin/ModuleMain.cpp`):**
   - Add or modify the command parser inside `DoCommand(const std::string& line)`.
   - Implement the corresponding hook or memory override. Ensure hot-path diagnostic counters are wrapped in `#ifndef FORGEPACT_RELEASE` (`BP_DIAG_INCREMENT`).
   - If introducing a functional hook, ensure it is installed lazily only when non-vanilla values are requested (preserving zero-overhead all-off baseline).
2. **Compile Native Plugin (`plugin_build/build.bat`):**
   - Build the release DLL:
     ```cmd
     plugin_build\build.bat release
     ```
   - Copy the output binary to the shipped staging directory:
     ```powershell
     Copy-Item plugin_build\BloodPactPlugin_ship.dll modfiles_shipped\BloodPactPlugin.dll
     ```
3. **Update Panel UI & Command Builder (`src/forgepact.py`):**
   - If adding a new setting, define its metadata in `SPAWNERS`, `KEYS`, `STATS`, or `PERCENT_STATS`.
   - Update `build_cmds(cfg)` and any specialized command generators (e.g. `build_key_cmds`).
   - Update the HTML/JavaScript UI templates within `src/forgepact.py`.
4. **Execute Contract Tests:**
   - Run the full Python test suite to verify contract adherence:
     ```powershell
     py -m unittest discover -s tests -v
     ```
5. **Package Release Distribution (`build_release.py`):**
   - Run the packaging script:
     ```powershell
     py build_release.py
     ```
  - The packaging guard requires `plugin_build\BloodPactPlugin_ship.dll` to exist and confirms that `modfiles_shipped\BloodPactPlugin.dll` matches it. A missing or stale staged plugin stops packaging so the Install button cannot ship an older DLL.
6. **Write Release Notes (`release-notes-vX.Y.Z.md`, preferred but no longer a gate on tagging):**
   - Every version with player-visible changes should still get a `release-notes-vX.Y.Z.md` file at the ForgePact repo root, written in the PR that makes the change. This is the **preferred source**: it is player language, written by whoever made the change, while the change is fresh.
   - **The files are temporary, and deleting them is automatic.** Publishing a (non-pre)release runs `forgepact-notes-cleanup.yml`, which asks `forgepact_tag.py --published-notes --version <v>` for every notes file at or below that version (the release's own and every skipped version it rolled up; anything older was carried by an earlier release), `git rm`s them and commits to `main` as the bot, rebasing and retrying up to three times if `main` moved. The published release page is then the record (git history keeps the file), and `--compose-notes` only reads versions newer than the previous tag, so nothing reads a published version's file again. It refuses a tag whose release is still a draft. Only unpublished versions' notes are ever at the repo root; v1.3.1–v1.3.16's were deleted by hand before the workflow existed (ForgePact#27). Its bot push does not fire `notify-hub.yml`, so the hub pointer picks the deletion up with the next ordinary merge. If a run fails, re-run "ForgePact notes cleanup" from Actions with the tag; don't delete the files by hand. A release event runs the workflows **in the tagged commit**, so a tag cut before a commit that carries this workflow does not start it on publish (v1.3.20 is the one such tag); run it by hand for that release. Verified live 2026-09-16: a manual run with the draft `v1.3.20` refused at "The release is published", and one with `v1.3.16` reported nothing to delete and committed nothing.
   - It is no longer a prerequisite to tagging or releasing. `forgepact-tag.yml` composes the draft release body from whatever notes files exist at tag time — the tagged version's own file if it exists, otherwise GitHub's generated notes under a "rewrite for players before publishing" banner, plus every skipped version's own file concatenated in newest-first order. See "Tagging a release (forgepact-tag.yml)" below for the full composition rules. `cut_release.py --check` still fails on a missing notes file by default; only `--allow-missing-notes`, which only the tag workflow passes, relaxes that.
   - If the top file is missing at tag time, the draft's top section is generated notes under that banner, and it **must be rewritten into player language before publishing** — generated notes are pull-request titles, not something written for a player deciding whether to update.
   - Player-facing only, in plain language — what was broken and what changed *for the player*, not internal refactors, build-script fixes, or debugging history (that belongs in this instructions.md, e.g. Known Limitations, not in release notes). Match the tone of the existing files: name the symptom before the fix ("Tyrant's Crown and Monster Rarity did nothing in 1.3.14" before explaining why), and give a measured before/after number when one exists.
   - Standard sections, in order: `## New`, `## Fixed` (either may be omitted if empty, but at least one must be present), then `## How to update` with the standard boilerplate (see any existing file). A `## Changed` section is used for reorganizations (e.g. a control moving to a different panel tab) that are neither strictly new nor a bug fix.
   - Never claim something is "Fixed" that is not actually resolved. If an investigation concluded the *reported* symptom is not this project's bug (e.g. a freeze traced to a display driver / GPU stall with a control run proving the plugin was not involved), that finding belongs in this instructions.md's Known Limitations, not in release notes as a fix — release notes are read by players deciding whether to update, and an overclaimed fix erodes trust in every note that follows it.

---

## Supported Platforms & Prerequisites

### Supported Platforms
- **Operating System:** Windows 10 / Windows 11 (64-bit x86_64).
- **Target Game:** Hero Siege Season 10 (offline, EAC disabled / single-player copy).

### Build & Development Prerequisites
- **Python:** Python 3.10+ (standard `py` launcher on Windows).
- **C++ Compiler:** Microsoft Visual C++ (MSVC) supporting `/std:c++20`. `build.bat` finds it
  itself, in order: an already-initialised `vcvars` environment (`VSCMD_VER` defined and `cl`
  on `PATH`), then `vswhere -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64`
  (what finds VS 18.9 Enterprise on the `forgepact-release.yml` runner, `windows-2025-vs2026`,
  which none of the four legacy hardcoded paths below it match), then those four hardcoded
  paths (VS 18 BuildTools, VS 18 Community, VS 2022 Community, VS 2022 BuildTools) as a last
  resort. No manual setup needed if any of the three applies.
- **YYToolkit Headers and third-party binaries:** the `YYToolkit/`, `Aurie/`, `FunctionWrapper/`
  include trees, `YYTK_Shared_Types.cpp` (all under `plugin_build/include/`), and
  `modfiles_shipped/{AurieCore.dll,AuriePatcher.exe,YYToolkit.dll,HSOfflineTrackerProducer.dll}`.
  `py tools/fetch_toolchain.py` places all eleven pinned files, downloading each from a pinned
  commit or release and verifying its SHA-256 before writing anything (all-or-nothing: one bad
  hash writes nothing at all). `--verify-only` checks what's already there without downloading;
  `--force` replaces a hand-placed file that differs from the pin (the common case: a
  maintainer's own CRLF `Aurie/shared.hpp` copied in before this tool existed). See
  `tools/toolchain-pins.json` for exactly where each file comes from, and "The build half
  (forgepact-release.yml)" below for the full pin table.
- **hs-game-sdk:** required by **both** builds, not just the plugin. `build.bat` compiles against `hs-game-sdk/cpp/include` (`/I ..\..\hs-game-sdk\cpp\include`), and since 2026-09-14 `build_release.py` also puts `hs-game-sdk/python` on PyInstaller's analysis path — the panel imports `hs_game_sdk` for the Satanic Zone buff/debuff pool, and a package built without it ships that section empty. Building from inside a full toolkit checkout (ForgePact sits next to `hs-game-sdk/`) needs no extra setup; building ForgePact standalone means checking the hub out alongside it.
- **Python Packages (Optional / Packaging):**
  - `pyinstaller` (required for running `build_release.py`).
  - `pywebview` (optional; if installed, panel launches in a native desktop window, otherwise falls back to the default web browser).
  - `requirements-build.txt` pins the exact versions CI builds with (`pyinstaller==6.22.2`, `pywebview==6.2.1`); `py -3 -m pip install -r requirements-build.txt` reproduces them locally when matching a CI-built zip.

---

## Command Reference

| Command | Working Directory | Shell / Platform | Prerequisites | Expected Result | Side Effects | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `py src/forgepact.py` | `ForgePact/` | PowerShell / CMD | Python 3.10+ | Launches local control panel HTTP server (`http://127.0.0.1:8766`). | Opens web browser / desktop window; watches for game process | Verified |
| `py -m unittest discover -s tests -v` | `ForgePact/` | PowerShell / CMD | Python 3.10+ | Executes all 442 Python contract tests (including the three native behavior harnesses, which skip without a C++ toolchain). | Read-only test execution; all tests pass | Verified 2026-09-16 |
| `py tools/perf_panel.py` | `ForgePact/` | PowerShell / CMD | Python 3.10+ | Times the panel's two per-poll costs - the boot count and the process scan - against reference copies of the pre-1.3.20 implementations, and exits non-zero if either regressed below its floor. No game, no network. `--log-mb`, `--iterations`, `--min-speedup`. | Writes and deletes a synthetic log in a temp directory | Verified 2026-09-15 |
| `py tools/cut_release.py --check --expect <version>` | `ForgePact/` | PowerShell / CMD | Python 3.10+ | Reports the version at every site and fails if they disagree, or if the release notes are missing and `--allow-missing-notes` was not given. `py tools/cut_release.py <version>` moves them. `--allow-missing-notes` (only `--check`; only used by `forgepact-tag.yml`) reports a missing notes file without failing. **Do not hand-edit the version sites** - a mismatch here is the signal, not a nuisance. Touches no git, runs no build, stages no DLL. | `--check` is read-only; a bump rewrites two files | Verified 2026-09-16 |
| `py tools/forgepact_tag.py --tag <version> --existing <tags…>` | `ForgePact/` | PowerShell / CMD (Git Bash for the real examples below) | Python 3.10+ | Checks a typed tag/version against the existing `v*` tags and the tree, and prints `version=`, `tag=`, `bump=`, `previous=`. Refuses a taken tag, a downgrade against the highest tag, a version below the tree, or a malformed input. | Read-only | Verified 2026-09-16 |
| `py tools/forgepact_tag.py --compose-notes --version <v> --previous <tag> --generated <file> --out <file>` | `ForgePact/` | PowerShell / CMD | Python 3.10+ | Composes the draft release body: the tagged version's own `release-notes-vX.Y.Z.md` if present (else the generated notes at `--generated`, under a banner), plus every skipped version's file, newest first. Prints `source=` and `versions=`. | Writes `--out`; reads notes files under `--root` (default: repo root) | Verified 2026-09-16 |
| `py tools/forgepact_tag.py --published-notes --version <v>` | `ForgePact/` | PowerShell / CMD | Python 3.10+ | Prints the bare filenames of every `release-notes-vX.Y.Z.md` at or below `<v>`, oldest first, one per line; empty when there are none. What `forgepact-notes-cleanup.yml` deletes after `<v>` is published. A malformed version exits 1 with empty stdout. | Read-only; lists `--root` (default: repo root) | Verified 2026-09-16 |
| `plugin_build\build.bat` / `plugin_build\build.bat release` | `ForgePact/` | CMD / PowerShell (Windows x64) | MSVC v143+ (VS 2022), YYToolkit headers in `plugin_build\include\` | Compiles `BloodPactPlugin_ship.dll` with `/DFORGEPACT_RELEASE`. Equivalent commands - `build.bat` only special-cases `dev`; anything else (including no argument) takes this branch. | Generates `plugin_build\BloodPactPlugin_ship.dll` and `obj_ship\` | Verified 2026-09-10 |
| `plugin_build\build.bat dev` | `ForgePact/` | CMD / PowerShell (Windows x64) | MSVC v143+ (VS 2022), YYToolkit headers in `plugin_build\include\` | Compiles `BloodPactPlugin_rel.dll` (research build with inspection commands, and `satmods` diagnostics). | Generates `plugin_build\BloodPactPlugin_rel.dll` and `obj_dev\` | Verified 2026-09-10 |
| `py build_release.py` | `ForgePact/` | PowerShell / CMD | PyInstaller installed, matching `BloodPactPlugin_ship.dll` | Builds complete release bundle in `dist/ForgePact/`. | Terminates existing `ForgePact.exe` processes; generates onefile executable | Inspected |
| `py tools/fetch_toolchain.py [--verify-only] [--force]` | `ForgePact/` | PowerShell / CMD | Python 3.10+, network (unless `--verify-only`) | Fetches/verifies the eleven pinned headers and third-party binaries in `tools/toolchain-pins.json` (all-or-nothing: one bad hash writes nothing and exits 1). `--verify-only` hashes what's on disk and downloads nothing; an empty root always fails it. `--force` replaces a hand-placed file that differs from the pin. | Writes under `plugin_build/include/` and `modfiles_shipped/` (both gitignored) | Verified 2026-09-16 |
| `py tools/release_ci.py package --root . --version <v> --out <dir> --info k=v ...` | `ForgePact/` | PowerShell / CMD | Python 3.10+, `dist/ForgePact/` already built | Zips `dist/ForgePact/` into `ForgePact-<v>.zip` under a `ForgePact-<v>/` root (the shape `tools/build_catalog.py` expects), with a generated `SHA256SUMS.txt` and `BUILD-INFO.json` (`live_gameplay_verified` always `false`). Also writes `ForgePact-<v>.zip.sha256`. Refuses if `dist/ForgePact/` is incomplete or its version disagrees with `--version`. | Writes `--out` | Verified 2026-09-16 |

*Status notes:* Commands marked **Verified** have been executed and validated in the current environment. Commands marked **Inspected** have been audited against build script source declarations and compiler flags.

---

## Data Formats, Persistence & IPC Contracts

### 1. Panel Configuration (`%LOCALAPPDATA%\Hero_Siege\forgepact.json`)
Stores user UI settings in JSON format:
```json
{
  "exe": "C:\\Games\\HeroSiege\\Hero_Siege.exe",
  "auto_apply": true,
  "density": 1.5,
  "rift": 5,
  "battlefield": 1,
  "dungeon": 2,
  "relic": 1,
  "exp": 2.0,
  "magicfind": 1.5,
  "movespeed": 1.0,
  "damage": 25,
  "map_reveal": true,
  "map_reveal_packs": true,
  "headhunter": true,
  "tyrant": false,
  "beacon": false,
  "mod_filter_max_relics": false,
  "mod_orb_pickup_radius": false,
  "mod_pet_quest_pickup": false
}
```

Note `map_reveal_packs`: it is the only key that defaults to **true** while its
parent (`map_reveal`) defaults to false, because the plugin also defaults its
pack flag on. `build_cmds` therefore emits `reveal packs 0` only to turn it
*off*, and the panel restates the child whenever the parent is switched back on
(otherwise a player who turned packs off would silently get them back).

### 2. IPC Command File (`<game>\bin\bp_ipc\cmd.txt`)
UTF-8 / ASCII plain-text command queue. The panel appends lines to `cmd.txt`; the plugin reads, executes, and clears the file every few frames.
- Example commands:
  - `ping`: Keepalive and synchronization probe.
  - `density 2.0`: Sets enemy density multiplier to 2.0x.
  - `specialrate rift 5`: Sets Rift Portal spawner multiplier to 5x.
  - `droprate group dungeon 2`: Sets Dungeon Key drop multiplier.
  - `dungeonkey add 12 1` / `dungeonkey on`: Opens outer LoadDrops gate for Dungeon Keys (type 12).
  - `stat damage 1.25`: Sets damage multiplier to 1.25 (+25%).
  - `mapreveal on` / `mapreveal off`: Toggles full map fog of war clearing.
  - `relicfilter 1` / `relicfilter 0`: Toggles the relic drop pool filter to exclude relics already at maximum level (10/10) in player equipped slots, backpack, or inventory. Safe to send at launch: it arms the mod and the `DropRelic` hook is installed later, once a player instance exists.
  - `orbpickup 10` / `orbpickup 0` / `orbpickup stat`: Widens the experience / magic-find globe pickup radius by 10x. Since 1.3.20 `FrameCallback` *scans* for globe instances every `kOrbScanFrames` (15) frames — or sooner once the player has travelled the whole approach budget, which is what keeps the scan correct at 10x Movement Speed — and *pulls* the cached ones every frame toward the player at a constant `kGlobePullSpeed` (6 px/frame — tuned down from an accelerating ramp per user feedback 2026-09-10, which snapped the last stretch in a single frame and read as an unnatural teleport); the game's own pickup logic then fires normally once close enough. `orbpickup stat` (also printed when the mod is switched off) reads as a decision tree: `seen=0` while standing next to globes means the object indices are wrong, `noplayer>0` means the player never resolved, and only `outofreach` means the radius is too small — `nearest=` says by how much. `seen`, `noplayer` and `outofreach` are each counted once per globe per **scan** so they stay comparable with one another; `pulled` is per frame. See "Orb pickup: the scan is throttled, the pull is not" below.
  - `headhunter force` / `tyrant force` / `beacon force`: Activates custom forge mechanic overrides.
  - `enemyspeed 1.5 ct`: Scales enemy movement speed by 1.5x scoped exclusively to Chaos Tower.
  - `satmods buff 3,12` / `satmods debuff 7`: Disables the given Satanic Zone buff/debuff ids (comma-separated) from the pool the game can roll onto a future zone; empty csv clears that polarity. `satmods status` reports the current disabled counts and the poll's hit/change counters. Filtering is poll-driven, not a routine hook - see `docs/satanic-zone-mods-research.md`.
  - `reveal 1` / `reveal 0`, `reveal packs 1` / `reveal packs 0` (+ `reveal stat` in the research build only): Map reveal. `reveal` clears the zone's minimap fog grid once per zone identity - measured 2026-09-11 to be all that static icons need (waypoints, dungeon entrances, chests, shrines and mining nodes are fog-gated, **not** gated by `isDiscovered`, so no per-object sweep exists or is needed). `reveal packs` is the monster half and the only part that adds work: most packs do not exist until the player walks within ~1050 px of their `Enemy_Creator_*`, so it opens a bounded 900-frame window per zone during which `distance_to_object` answers 0 for creators, letting the game's own creator logic populate the map (measured 148 → 866 and 208 → 1273 enemies; ~7.8 ms frame average, plugin 2.3%). The window only opens once a live creator reports a real `enemyCreatorTimer` - firing during zone load leaves spawners permanently inert. **The authorization is then re-checked per creator, inside `Hook_distance_to_object`, at the moment the distance would be changed** - not at a frame boundary: `EVENT_FRAME` is dispatched from `HkPresent` at the end of the frame, while creators consume the permission in their step events earlier in the same frame, so a window invalidated at Present is too late for the first call in a new zone. A creator that has not initialised keeps its real distance however stale the window is; a ready one is still served, so the pass keeps working across a transition instead of failing closed. The same guard covers the Beacon's lie. The window is additionally bound to the full zone identity (room + minimap instance + grid), re-checked every frame as defence in depth, and is never opened against an identity that could not be read. Turning `reveal packs` on arms the **current** zone's readiness-gated pass rather than waiting for the next zone change. Panel: `map_reveal` with the nested `map_reveal_packs` checkbox. See `ForgePact/docs/map-reveal-research.md`.
  - `petquest 1` / `petquest 0` (+ `petquest stat` in the research build only): Pet Quest Collector. Working and live-measured 2026-09-11. While enabled and a `Companion_obj` exists, `FrameCallback` runs a two-phase tick: `Idle` enumerates `Quest_Object_Parent_obj` descendants inside the camera view (minus a static exclusion list, 64-instance budget), picks the nearest collectable one, and `Travel` writes the pet's `x`/`y` toward it at 11 px/frame until it arrives (or 240 frames elapse, which collects anyway - the walk is cosmetic, the credit is the point), then invokes the collect and waits 24 frames. The collect: with the item as `self` and `Loot_Manager_obj` as `other`, invoke the item's own `m_Questpickup` method value with one real argument, reached via `InvokeMethodValue` (the callable read off the method value's own `CScriptRef`, validated before the call — no game addresses; see Known Limitations item 11); it calls `update_quest` -> `QuestSaveUpdate` internally, so the objective credit is inside the call and nothing is faked. The game's own gates (`canPickup`, `lootType == 0`) are re-read from the live instance at collect time. `petquest arg <n>` (both builds) changes the one argument that was reproduced rather than understood. **Not implemented:** an accepted-quest gate, and the loot-system side effects a real collect performs (sound, pickup effect, inventory log) - so a pet collect is silent. See `ForgePact/docs/pet-quest-collector-c-research.md` and Known Limitations item 11.

### 3. IPC Log & Output File (`<game>\bin\bp_ipc\out.txt`)
Append-only log containing plugin startup notifications, command responses, and runtime diagnostic dumps. The panel reads `out.txt` to track process boot counts (`BloodPact plugin loaded`).

### 4. Live Item Stats File (`<game>\bin\bp_ipc\itemstats.json`)
Exported by the plugin at most once every 2 seconds when custom forge hooks are active. Contains actual rolled `itemStatStruct` records keyed by `itemTimeStamp`. Consumed by the companion `hero-siege-item-editor` to display live rolled base stats.

---

## AI Code Review (`ai-review.yml`)

`.github/workflows/ai-review.yml` runs an AI code review of a pull request and
posts findings as inline comments. It is **opt-in, never automatic**: add the
`ai-review` label, or comment `@claude review` on the pull request. The label
does not re-run by itself on later pushes; request again for a fresh review.
A comment trigger only works once the workflow is on `main`, because GitHub runs
`issue_comment` workflows from the default branch.

It needs two things, not one:

- the `CLAUDE_CODE_OAUTH_TOKEN` repository secret, from `claude setup-token`,
  which authenticates against a Claude subscription rather than a
  separately-billed API key; **and**
- the [Claude GitHub App](https://github.com/apps/claude) installed on the
  repository. Without it the run fails at the OIDC-to-app-token exchange with
  `401 Unauthorized`, "Claude Code is not installed on this repository", before
  any review happens -- a correct secret does not help.

Concurrency is on the job and shared only by a real request, so an ordinary
comment or unrelated label cannot cancel a review in progress. The request
predicate is written out twice in the file (in the job `if` and in the
concurrency group); change both together. The hub carries the same workflow and
its `tests/test_ai_review_workflow.py` pins that shape.

`--allowedTools` must name every tool the code-review command declares
(`gh pr view`, `gh pr diff`, `gh pr comment` and the rest), because it replaces
that command's own list. With only the inline-comment tool listed, a review runs,
is denied the calls it needs, posts nothing, and still goes green. `Skill` is
listed as well, because the prompt is a plugin command.

The action step sets `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`. The code-review
command works through subagents, which otherwise run in the background, and a
headless run ends when the model ends its turn while waiting for one: hub #59
went green after four turns with nothing reviewed. A final step fails the job
when no comment appeared on the pull request after the review started, and
prints the review's last message; a deliberate stop (closed, draft, or already
commented on by Claude) goes red there too, with its reason. Each run
uploads its full result as the `claude-execution-output` artifact, which is
where per-model token counts and the names of any denied tools can be read.

This lives in its own section rather than on the "CI / Pipeline Availability"
line above because that line is rewritten whenever a release workflow changes,
and every such rewrite conflicted with it.

## Safety, Installation & Backup Lifecycle

### Safe Mod Installation & Restoration
1. **Pre-flight Check:** Verifies `Hero_Siege.exe` exists, the game is not currently running, and required binaries (`AurieCore.dll`, `YYToolkit.dll`, `BloodPactPlugin.dll`, `AuriePatcher.exe`) exist.
2. **Clean Backup Archival & Refresh:**
   - If `Hero_Siege.exe.aurie_backup` does not exist, a byte-for-byte copy of the unpatched game executable is created.
   - If an existing backup belongs to an older game build (detected via PE headers and `.text` section hash comparisons), the old backup is archived as `Hero_Siege.exe.aurie_backup.stale-<timestamp>` and a fresh clean backup is created from the new executable.
3. **PE Import Patching:** `AuriePatcher.exe` injects a `.aurie` section into `Hero_Siege.exe` so the game automatically bootstraps `AurieCore.dll` on startup.
4. **Atomic Rollback:** If `AuriePatcher` fails or produces an invalid binary, the clean verified backup is immediately restored atomically over `Hero_Siege.exe`.
5. **Safe Mod Removal:** `op_remove_mod` validates that `Hero_Siege.exe.aurie_backup` matches the base build before restoring it over `Hero_Siege.exe`, and unlinks mod DLLs (`AurieCore.dll`, `mods/aurie/YYToolkit.dll`, `mods/aurie/BloodPactPlugin.dll`, `mods/aurie/HSOfflineTrackerProducer.dll`).

### Anti-Cheat & Offline Enforcement
- ForgePact is strictly designed for **single-player / offline** play with Easy Anti-Cheat (EAC) disabled.
- It does not contain EAC bypass mechanisms; launching an EAC-enabled online client will bounce back to the clean executable and fail to load Aurie mods.

---

## Packaging Hazards & Guardrails

The packaging script (`build_release.py`) includes explicit fail-closed safety checks:
1. **Plugin Sync Guard:** Compares `modfiles_shipped\BloodPactPlugin.dll` against `plugin_build\BloodPactPlugin_ship.dll`. If they differ or the ship DLL is missing, packaging is aborted to prevent shipping stale plugin binaries.
2. **Process Lock Prevention:** Uses `taskkill /F /IM ForgePact.exe` before rebuilding to avoid locked executable errors in `dist/ForgePact/`.
3. **Module Exclusion:** Excludes heavy or unused packages (`tkinter`, `PIL`, `numpy`, `pandas`, `PyQt5`, `IPython`, `pytest`) from the PyInstaller onefile package, keeping bundle size small.
4. **SDK Bundling Guard (added 2026-09-14):** `hs-game-sdk/python` goes on PyInstaller's analysis path via `--paths`, packaging is refused outright if that directory is missing, and the build fails if PyInstaller's own `warn-ForgePact.txt` still reports `missing module named hs_game_sdk` afterwards. Fail-closed on purpose: `src/forgepact.py` catches that ImportError and falls back to empty Satanic pools, and its runtime `sys.path` fallback cannot help a frozen build (PyInstaller resolves imports at build time; the exe unpacks to a temp directory with no toolkit checkout above it). Every package built before this shipped a World tab whose Satanic Zone section rendered a heading with no rows — it built, started, and looked fine, which is exactly why the check is a hard error rather than a warning.


---

## Performance Pass (1.3.20) - What Changed, and the Numbers

Seven source-read findings across the panel, the plugin and the launcher, all of
the shape "this got heavier the longer you played". None of them were measured
before the change; part of the deliverable was the measurement, which is why
each one now has either a timing harness or a call-count assertion in a native
behaviour harness.

### Measured before/after

`py tools/perf_panel.py` (this machine, 2026-09-15, 64 MB synthetic log):

| Path | Before | After | Ratio |
| --- | --- | --- | --- |
| `plugin_boot_count`, one poll | 35.2 ms | 3.5 ms | ~10x |
| `running_paths`, one poll | 357.2 ms | 21.3 ms | ~17x |

The absolute milliseconds move between runs on a machine doing other work, and
so does the ratio, by less. Nine runs, same machine, same afternoon - the first
four recorded while writing this section, the last five by independent
verification passes afterwards:

| Run | `plugin_boot_count` | `running_paths` |
| --- | --- | --- |
| 1 | 35.2 / 3.5 ms = 10.1x | 357.2 / 21.3 ms = 16.8x |
| 2 | 40.1 / 4.0 ms = 10.0x | 481.0 / 26.8 ms = 17.9x |
| 3 | 37.7 / 3.7 ms = 10.1x | 574.8 / 39.1 ms = 14.7x |
| 4 | 36.5 / 4.2 ms = 8.7x | 582.8 / 39.4 ms = 14.8x |
| 5 | 13.0x | 12.9x |
| 6 | 11.3x | 13.6x |
| 7 | 11.0x | 16.0x |
| 8 | 10.2x | 16.0x |
| 9 | 8.7x | 16.1x |

So the honest statement is a **range**, not a figure: boot-count 8.7-13.0x,
process-scan 12.9-17.9x. Note that the first four runs alone gave 8.7-10.1x and
14.7-17.9x, and stating *those* as the range was wrong within hours - run 5 came
in above the boot-count ceiling and below the process-scan floor. A range from
one sitting is a sample, not a bound, which is the same "not observed is not
does not happen" rule this file applies to behaviour, applied to a number. That
is why `perf_panel.py` gates on a speedup *floor*
(5x and 1.5x) rather than on an absolute time or on reproducing a number - a
floor is the claim the measurement actually supports. The boot-count ratio also
understates the win over a session: the "before" column grows with the log, the
"after" column does not, because the scan resumes from the previous offset.

### Map reveal's pack pass was dead, and why nothing said so (2026-09-15)

`reveal` cleared the fog and never spawned a single pack, in any zone, on any
build carrying this code. Diagnosed live: `reveal stat` read
`zonesPopulated=0 pending=yes(721 ticks) creatorLies=0` against a zone with 92
ready creators, so the pass was arming and then failing a gate every poll for
four minutes, giving up silently at 1800 ticks.

The gate was `ReadIdentity()`, which refuses when `RoomKey()` returns
`INT64_MIN`. `RoomKey()` read `room` with `GetInstanceMember` on the global
instance - but **`room` is a GameMaker built-in, not a user global**, so that
read never answers and the key was always the "unreadable" sentinel. `Tick()`
stores whatever `RoomKey()` returns *without checking it*, which is why the
fog-clearing half kept working and hid the other half being dead.

`roomprobe` (research build) established the fix by trying every candidate in
one build with controls either side, rather than one guess per relaunch:

| | call | result |
| --- | --- | --- |
| 1 | instance-member read of `room` | FAILED - the bug |
| 2 | `GetBuiltinVariableIndex("room")` | index 118 |
| 3 | `GetBuiltin("room", nullptr)` | `kind=15` `ref room Act_06_01` |
| 5 | `variable_global_exists("room")` | false - negative control |
| 6 | `GetBuiltin("fps", nullptr)` | `real:129` - positive control |

Row 6 is what makes row 3 mean anything: it proves `GetBuiltin` works on this
runtime, so row 1's failure is a fact about `room` rather than about the call.

Two things the probe stopped us getting wrong. `room` comes back as a **ref,
not a real**, so `llround(ToDouble())` would still have been wrong after
switching APIs - the key now takes a number only when the kind *is* a number
and otherwise hashes the ref's own text, masked positive so a valid key can
never collide with the `INT64_MIN` sentinel. And the same read backs
`CurrentRoomKey()`, so finding 5's room gating had been inert too: correct, but
always via its 15-frame safety re-poll, never on the room-change frame.

Confirmed live after the fix: `CurrentRoomKey() -> 6242359296347299236`,
`zonesPopulated=1 pending=no creatorLies=92`, and the zone went from 42 to 547
enemies.

**The harness stubs were complicit.** All three faked `room` as a convenient
real via `GetInstanceMember`, so every scenario passed over a function that
returned `INT64_MIN` in production - `AGENTS.md`'s "a stub that cannot represent
the failing input cannot catch the bug", exactly. They now return a `VALUE_REF`
by default, keep `GetInstanceMember` permanently failing as a negative control,
and carry a `roomIsReal` switch so the numeric branch is not dead code.

Native harness call counts. **Rows 2-4 are measured** against a runnable copy of
the pre-change shape in the same run (`est_force_harness.cpp`'s `PreChangeTick`,
`orb_pickup_harness.cpp`'s `PreChangeOrbTick`), so both columns come out of one
execution. **Rows 1 and 5 are the "after" measured and the "before" derived**
from the removed code, because no runnable pre-change copy exists for either:
`map_reveal_harness.cpp` has no pre-change hook, and `PullOneGlobe` no longer
counts `outofreach` at all. Both derived values were later reproduced by
mutation, but that is a separate run, not this table's:

| Path | Before | After | Harness | Before is |
| --- | --- | --- | --- | --- |
| `enemyCreatorTimer` reads per lied-to creator | 2 | 1 | `ready_zone/timer_reads` | derived |
| `array_get` over 60 idle frames (`eSt`) | 60 | 4 | `idle60/array_get_before` / `_after` | measured |
| `instance_number` over 15 frames (orb) | 30 | 2 | `scan15/instance_number_*` | measured |
| `instance_find` over 15 frames (orb) | 15 | 1 | `scan15/instance_find_*` | measured |
| `outofreach` over 15 frames, one globe in the band | 15 | 1 | `counters/outofreach_once_per_scan` | derived |

The lied-to path's total per-creator cost is also printed, because it is finding
8's input: `liedto/callbuiltins got=2`, `liedto/object_index_share_pct got=50`.

What the throttles cost, measured in the same runs rather than reasoned about:

| Case | Result | Harness |
| --- | --- | --- |
| player crossing the orb band at ~10x speed | still pulled | `fastplayer/was_pulled` |
| globe still stationary when the player resolves again | pulled the next frame | `playervalid/pulled_on_next_frame` |
| what that costs, over 15 frames | 5 scans, vs 15 unthrottled | `fastplayer/scan_cost_bounded` |
| ordinary walk, 15 frames | 1 scan | `walk/one_scan_only` |
| Special Content toggled off and on in one room | corrected next frame | `toggle_off_on/*` |

**Which of these were observed red, and which are only bounds.** An assertion
that has never been seen to fail is a regression bound, not evidence, and the
difference has to be written down rather than implied — it is `AGENTS.md`'s
positive-control rule applied to a test.

*Observed failing first, with the measured line.* "Frame-counted scan" below
means the intermediate shape this change passed through: the throttle in place,
but the scan forced only by the frame counter and a room change.

| Assertion | Seen failing against | Reported |
| --- | --- | --- |
| `fastplayer/was_pulled` | the fixed 24 px/frame band, no travel forcing | `got=0 want=1` |
| `counters/outofreach_once_per_scan` | `outofreach` counted in the per-frame pull | `got=15 want=1` |
| `toggle_off_on/est0` | `EstForceTick` not dropping the room key on a mutation | `got=35 want=-1` (35 = the closed vanilla gate) |
| `playervalid/pulled_on_next_frame` | the frame-counted scan | `got=16 want=2` |
| `uncacheable/refusal_counted` | the frame-counted scan, no handle validation | `got=0 want=1` |

*Bounds, not witnesses — and the distinction matters enough to name them.*
`fastplayer/scan_cost_bounded` (`5 <= 15`) and `walk/one_scan_only` (`1 == 1`)
are both satisfied by the pre-1.3.20 per-frame enumeration, which never
rescanned early at all: they bound what the travel-forced rescan is allowed to
**cost**, they do not witness that it works. The way to see them fail is to
shrink `kOrbApproachMargin` (`walk/one_scan_only got=15 want=1`).
`band/was_pulled` is in the same class — it is the guard that stops
`pulled_within_scan_period` reading `-1 <= 15` as a pass, and its failing
direction is reachable (`got=0 want=1` with the cache disabled), but it does
**not** fail against the unthrottled code, where the player's move is picked up
by the next scan and the scenario passes end to end. `bareid/pulled` and
`bareid/not_refused` likewise passed before the handle check existed; they are
the control saying the refusal did not narrow what is accepted, not evidence
that it was needed.

### The `eSt` correction is gated on the room, NOT throttled

`EstForceApply()` ran on every frame while Special Content was on - three
`CallBuiltin`s for `GlobalArray("eSt")` plus one `array_get` per forced entry,
almost always to discover the value was already correct.

**The obvious fix, a flat `kSatanicPollFrames`-style throttle, is unsafe here,
and `docs/S10-special-content-notes.md` is why.** The game refills all eleven
`eSt` entries at Room Start, and the special-content mechanic bodies read
`global.eSt` **directly, at step time**, inside that same room-load sequence. A
throttled correction puts up to ~250 ms of vanilla gate value exactly where the
mechanics evaluate - the "Check a Permission Where It Is Used" defect from the
repo-root `AGENTS.md`, and the same shape as Known Limitations item 13, where
the first call in a new zone is the one that does the damage. The symptom would
be Special Content silently producing less, intermittently.

So `EstForceTick(fc)` reads the room key once per frame (`CurrentRoomKey()`, one
member read, no `CallBuiltin`) and:

- **room key changed** -> full apply on that frame, identical timing to the
  per-frame write it replaces, zero added latency;
- **otherwise** -> apply every `kEstPollFrames` (15) frames, as a safety
  re-poll, because nobody has proven the game only writes `eSt` at Room Start
  and an unproven negative stays unproven;
- **room key unreadable** -> falls through to the periodic path. It never
  suppresses the correction, and `INT64_MIN` is never stored, so "unknown"
  cannot compare equal to a real room.

**Worst-case correction latency, stated:** room-start overwrite -> unchanged
(same frame as before); any other overwrite (none observed, none ruled out) ->
up to 15 frames (~250 ms) instead of 1.

**Changing *what* is forced also has to re-open the gate, and that is not free
with a room gate.** `EstForceTick` only applies on the frame the room key
changes, so turning Special Content off and on again *without leaving the room*
looked like no change at all and waited for the next re-poll - ~250 ms of the
closed vanilla gate (`eSt[0] = 35`) immediately after the user switched the
feature on, in a feature whose consumers read `eSt` at step time. The per-frame
write this design replaced had no such gap. So every mutation of `g_EstForce`
goes through one of exactly three mutators - `EstForceSet`, `EstForceErase`,
`EstForceClear` - each of which drops `g_EstLastRoom` back to `INT64_MIN`, the
same "unknown" sentinel the tick already refuses to store, which makes the next
frame look like a room change. A source test asserts there is no fourth way to
touch the map and that each mutator carries the drop; the harness scenarios
`toggle_off_on/*` and `toggle_erase/*` measure the timing. Adding a call that
writes `g_EstForce` directly is what those tests exist to catch.

**Two hard constraints, from the crash history in the same document.** Every
attempt to write `eSt` from anywhere other than the frame callback crashed the
game ("Room Start'ta global eSt override -> cokme", the same from a mechanic
scope, and zeroing `ReturnSpecificStat`'s return). So: the write happens **only**
from `FrameCallback`, and the room change is detected by a **read**, never a
hook. The experimental gates those attempts lived behind
(`kEstOverrideEnabled`, `gEstGateEnabled`, `gStatGateEnabled`) are **not in this
plugin at all** - `tests/test_est_force_behavior.py` asserts their continued
absence rather than that they default to false.

Residual unknown, for a live session rather than a plan: whether the mechanic
bodies evaluate *before* the first frame callback of a new room, in which case
the per-frame write was already too late and the feature works for some other
reason. This change cannot make that worse - it preserves the old timing
exactly - and `eststat`'s `yazma=` counter is the instrument.

### Orb pickup: the scan is throttled, the pull is not

`OrbPickupTick()` enumerated every instance of every globe type on every frame -
worst case ~196 `CallBuiltin`s per frame under the 64-instance budget.

The **pull** genuinely needs per-frame work: globes glide toward the player at a
constant `kGlobePullSpeed` (6 px/frame), and that constant speed was a
deliberate fix to a user report (the old proportional step "read as an unnatural
teleport right before pickup"). The **enumeration** does not.

- `OrbScan()` runs every `kOrbScanFrames` (15) frames and caches the handles of
  globes inside `reach + kOrbScanFrames * kOrbApproachMargin`.
- **`kOrbApproachMargin` is 24 px/frame**, and it is a *budget*, not a claim
  about how fast the player can move. Globes are not observed to move on their
  own - they are dropped and sit still until the plugin pulls them - so the gap
  is closed by the *player* walking into it, and 24 px/frame (~1440 px/s, four
  times `kGlobePullSpeed`) is what each scan allows for that.
- **The budget is enforced, not assumed, and this is the part that matters.**
  The panel's own Movement Speed control multiplies total movement speed by up
  to **10x** (`src/forgepact.py`, the `movespeed` slider), so a fixed margin is
  a bound nothing holds the player to. Above it a globe crosses into reach
  between two scans, is never cached and is never pulled - and because `seen`
  and `pulled` both stay non-zero, `orbpickup stat` goes on looking healthy
  while the widened radius applies only some of the time. So `OrbPickupTick`
  records where the player stood at the last scan and **forces a rescan once
  the player has travelled the whole budget**, whatever the frame counter says.
  The bound then holds by construction at any speed. It costs no `CallBuiltin`:
  `g_PlayerX`/`g_PlayerY` are refreshed in `FrameCallback` immediately before
  the tick runs. Cost of holding it: more scans while sprinting, never more
  than the per-frame enumeration this replaced (harness:
  `fastplayer/scan_cost_bounded got=5 limit=15`), and an ordinary walk still
  buys one scan per 15 frames (`walk/one_scan_only`).
- **A rescan is also forced when the player resolves again.** A scan that runs
  while the player is unresolved caches nothing - it has no position to measure
  reach against - and the transition back to resolved is not something a frame
  counter can see. Without forcing one, every resolution dropout that lands on
  a scan frame leaves the cache empty for up to 15 frames, on the one feature
  whose documented failure mode *is* intermittent player resolution (Known
  Limitations item 7). `orbpickup stat` cannot show it either: `noplayer` ticks
  once and the next scan reads healthy. The pre-1.3.20 per-frame enumeration
  resumed on the very next frame, so this does too
  (`playervalid/pulled_on_next_frame`).
- The pull runs every frame over the cached handles, with `PullOneGlobe`'s
  movement maths untouched, guarded by one `instance_exists` per handle because
  a globe can be collected between scans.
- **Caching instance handles across frames is safe here**, and the reason is
  worth writing down once: `instance_find` returns a `VALUE_REF` id that the
  runtime itself validates (`docs/RUNTIME_DATA_MODELS.md`), so a stale one
  fails the `instance_exists` guard rather than dereferencing freed memory.
  That is *not* true of raw struct pointers - `g_ForgedItems` holds those and
  carries its own hazard note - so the distinction is the kind of value, not
  the act of caching.
- **...and that kind is now validated rather than assumed.** The sentence above
  is a *measured property of this runner*, and the cache is the only cross-frame
  instance lifetime this change introduces, so `OrbCacheableHandle()` checks
  each handle where it is stored, refuses anything that cannot outlive the frame
  (a `VALUE_OBJECT` is a `CInstance*` - the `g_ForgedItems` hazard), and counts
  the refusal into `orbpickup stat` as `uncacheable=`. That is `AGENTS.md`'s
  validate-refuse-and-count shape: a runtime that changed reports a number
  instead of a crash dump. It accepts a **set** - `VALUE_REF` plus the bare
  instance ids an older runner returns (`VALUE_REAL`/`INT32`/`INT64`, the same
  ones `HhResolveLocalPlayer`'s fallback handles) - because every accessor the
  cache feeds takes any of them straight through, so the check may decide only
  whether a handle can be *stored*, never whether the work happens at all.
  `uncacheable=` is expected to stay 0 forever; the harness has both controls,
  `uncacheable/refusal_counted` and `bareid/pulled`.
- The cache is dropped when `orbpickup` is switched off and on a room change.
  Asset re-resolution is deliberately **not** a third point: nothing ever
  clears `g_OrbAssetsResolved`, so `ResolveOrbAssets()` runs once per process
  and a reset there could only ever fire against an already-empty cache. A call
  that reads as an invalidation point while being unreachable is worse than its
  absence, so the comment says so instead.

**Accepted cost:** a globe entering the band between scans starts gliding up to
15 frames (~250 ms) later than before. It is never *missed* - the next scan
picks it up - and the glide itself is byte-for-byte the same motion.

**`g_OrbGlobesSeen` is deliberately NOT wrapped in `BP_DIAG_INCREMENT`**, and
this is a documented exception to step 1 of the Representative Change Workflow.
`orbpickup` is in the **player-build** command set (`kPlayerCommands`),
`orbpickup stat` is handled in every build, and Known Limitations item 7 depends
on it - it is the diagnostic that turned `seen=176993 noplayer=176993` into a
diagnosis. Stripping it in release would recreate exactly the "a mod that fails
silently is a mod nobody can debug from a bug report" failure. `BP_DIAG_INCREMENT`'s
own comment scopes it to telemetry on hot combat/drop paths; a player-facing stat
command is not that. The counters also stop being a hot-path cost once the
enumeration is throttled, because they then fire once per globe per **scan**.

That changes their *meaning* - globe-frames to globe-scans - so `orbpickup stat`
now says so in its own output. Zero-versus-nonzero, which is what the decision
tree actually uses, is unchanged.

**It does not change them by a fixed factor, and the printed line must not
suggest one.** 15 frames is a *ceiling* on the scan period, not the period: the
travel-forced rescan above fires sooner, measured at 5 scans per 15 frames at
~10x movement speed (`fastplayer/scan_cost_bounded`). Anyone reconstructing
elapsed frames from a pasted `orbpickup stat` would be wrong by up to 5x in
exactly the high-Movement-Speed case the fix exists for, so the line reads
"once per globe per scan, not per frame; a scan runs at most every 15 frames,
sooner while the player is moving fast". The *ratio* between the three counters
is what the decision tree reads, and that is still sound.

**All three scan-clock counters are incremented in `OrbScan`, and none of them
in `PullOneGlobe`.** Known Limitations item 7 was diagnosed from a *ratio* -
`seen=176993 noplayer=176993` - so counters printed under one label have to be
counted the same way. Moving only `seen` into the scan while `noplayer` and
`outofreach` stayed in the per-frame pull would have put them on two different
clocks under a line claiming they shared one: a single globe parked inside the
band but outside reach reports ~15 `outofreach` per 1 `seen`, and the next
person to read a pasted `orbpickup stat` mis-reads it. `outofreach` is measured
against **reach**, not the band, because "cached but still not being pulled" is
exactly what "the radius is too small" means. `pulled` is the one number still
on the frame clock - pulling is the part that still happens every frame - and
the printed line names it as such rather than leaving it to be assumed.

### The readiness check runs once per creator, not twice

`Hook_distance_to_object` asked `MapRevealManager::CreatorIsReady(inst)` and
then `MayPopulate(inst)`, which **is** `window > 0 && CreatorIsReady(creator)` -
so the same `enemyCreatorTimer` read happened twice for every creator on an open
pack window, deciding nothing new, on the builtin every spawner polls.

Fixed by inversion rather than by adding API: `MayPopulate` stays the reveal
path's single authorization, and the standalone `CreatorIsReady` moved **into
the Beacon branch**, which `MayPopulate` does not cover. Known Limitations item
13's guard survives intact on both paths. Four cases, all decisions identical:

| Case | Before | After |
| --- | --- | --- |
| reveal window open, ready creator | 2 | **1** |
| Beacon only (reveal off) | 1 | 1 |
| window open, unready creator, Beacon off | 1 | 1 |
| window open, unready creator, Beacon on | 1 | 2 (transient zone-load, accepted) |

**Scope the claim correctly:** `revealOk = revealWants && MayPopulate(inst)`
short-circuits and `revealWants` is a relaxed atomic load, so with reveal off
the Beacon path already paid exactly one readiness read. The saving is on the
900-frame pack window after each zone change, not "continuously while the Beacon
is active".

The last row is the behaviour harness's **positive control** for the new call
counter (`beacon_and_window/timer_reads got=2`): without a scenario that expects
something other than 1, a counter stuck at 1 would look like a pass everywhere.

### The dead IPC-poll condition

`FrameCallback`'s command poll was `if (((fc++) % 30) == 0 && g_Setup)` wrapping
`if ((g_RuntimeFrame % 6) == 0)`. The inner test was **dead**: `g_RuntimeFrame = fc`
is assigned at the top of the same callback, *before* the `fc++`, so whenever the
outer test passed `g_RuntimeFrame` equalled `fc` and was a multiple of 30, hence
always a multiple of 6. The real rate was, and still is, **every 30 frames**
(~2x/second at 60 fps). The dead condition is gone, and the architecture diagram
above - which claimed the six-frame rate this file had documented since the
condition was written - is corrected.

### The adaptive poll policy, shared with HS-Offline-Launcher

Both UIs polled on a fixed timer with no hidden-window gate - the panel every
5 s, the launcher every 2 s. A fixed interval forces a trade nobody wins: fast
costs poll work for the whole session, slow costs feedback latency at exactly the
moments somebody is watching. **The trade only exists because the interval is
fixed**, and both clients can already tell when a change is plausible.

`POLL_POLICY_JS` is a named Python string constant in each app, concatenated
into `HTML`, holding one pure `pollDelayMs(hidden, msSinceChange)` plus the
watched-field comparison. Three tiers:

| Tier | Constant | What it is for |
| --- | --- | --- |
| Fast | `POLL_FAST_MS` = 2000 | Something just happened and the user is watching: a control moved, Apply or Launch was pressed, or a watched field in the payload changed. |
| Idle | `POLL_IDLE_MS` = 30000 | Nothing has changed for `POLL_FAST_WINDOW_MS` = 15000 ms. Play continues, nothing moves, the poll gets out of the way. |
| Suspended | `pollDelayMs` returns `null` | `document.hidden`: no poll is scheduled at all. `visibilitychange` resumes with an immediate poll and resets the change clock, so a returning user sees fresh state and the fast tier covers the time they look. |

**Both apps use the same three constant names and the same values, on purpose**,
and a test in each suite parses both files and fails if they drift. The earlier
"constants deliberately differ" idea was withdrawn: the `last applied` lag it was
pricing does not arise, because the moments needing fast feedback are exactly the
ones the client can detect.

`gameRunning` is deliberately **not** a parameter. Its flip *is* an observed
change, so it engages the fast tier by itself; while play continues nothing
changes and the scheme idles on its own; and a user adjusting sliders mid-game
generates local actions, which is when the panel must stay responsive - a
"gameRunning forces idle" rule would have made that case worse.

**Known gap, documented rather than special-cased:** a window *occluded* by a
fullscreen game is not necessarily `document.hidden`, so it idles rather than
suspending. That costs one poll per 30 s.

Watched fields: the panel watches `gameRunning`, `ipcOk`, `lastApplied`,
`queued`; the launcher watches `gameRunning`, `safe`, `ready`, `eacService`,
`blocker`, `steamRunning`, `steamFound`, `game.build`, `game.path`. Each list is
a named constant so a test can assert its contents.

### Two deliberate duplications, and why neither is a shared component

- **`snapshot_processes()` in `src/forgepact.py` is a second copy of
  `HS-Offline-Launcher/src/hs_offline_launcher.py`'s `processes()`.** The
  launcher is by design a standalone single-file application with **no**
  `hs_game_sdk` dependency; adding one changes its PyInstaller packaging and its
  stated "no external tools" property. ForgePact's `hs_game_sdk` import is
  optional with a silent fallback, and the SDK only reaches a frozen panel
  because `build_release.py` puts it on PyInstaller's analysis path and fails
  closed if it is missing - routing a Win32 process helper through that adds a
  packaging failure mode for zero functional gain. `AGENTS.md`'s "a correction in
  one submodule is not done until the shared SDK has it too" is about a *bug
  class* in a copy of a shared installer or scanner; this is neither a bug fix
  nor a copy of an SDK component. Keep the two in step by hand.

  **The fail direction differs on purpose.** The launcher's snapshot failure is
  fail-*closed* because it gates a safety decision. The panel's yields an empty
  list, i.e. "the game is not running", which makes the panel *queue* commands
  into `cmd.txt` instead of sending them live - harmless, and the pre-existing
  behaviour. Do not import the launcher's posture into the panel.

  **No cache, either.** `game_running()` decides whether a command goes out live
  or is queued; a cached "running" is a command sent to a dead game, a cached
  "not running" silently queues one the player expected to apply now. The fix is
  a cheaper enumeration, not a memoised one, and a test asserts the scan is
  re-run every call.

- **`tools/cut_release.py` deliberately mirrors the superproject's rather than
  importing it.** ForgePact is a separate git repository and this guide says it
  can be built standalone; a tool that only ran from inside a superproject
  checkout would mean a standalone clone could neither bump nor verify its own
  version, and `build_release.py` - which runs from inside ForgePact - could not
  consult it. The superproject's copy is hub-specific by construction (its
  `ROOT` and its site list are hardcoded to `hub/`). Same cross-repo constraint
  as the process helper.

### Where ForgePact's version lives (new in 1.3.20)

Until 1.3.20 there was **no version anywhere** - no `__version__`, no `#define`,
nothing in the panel UI. The version existed only as a release-notes filename, a
git tag and prose, so "bump the version" could only mean "create a file".

Two real sites, both moved by `tools/cut_release.py`:

1. `src/forgepact.py` - `__version__`. **Canonical**: `current()` reads it,
   because the panel is the always-present entry point and works with no
   compiled DLL at all.
2. `plugin/include/ForgePact/Version.hpp` - `#define FORGEPACT_VERSION`. A
   dedicated header gives an unambiguous regex anchor, and `plugin/include` is
   already on the compiler's include path.

Two derived checks, asserted by `--check` and never rewritten:
`release-notes-v<version>.md` must exist, and the plugin's boot line must
reference `FORGEPACT_VERSION` rather than a literal. The notes check can be
relaxed with `--allow-missing-notes` (`--check` only) - **only
`forgepact-tag.yml` passes it**, because that workflow composes the release
body itself (falling back to generated notes under a banner when the file is
missing) rather than requiring the file to exist before tagging. Every other
caller keeps the default, so a version landing on `main` by hand still needs
its notes file.

**Do not hand-edit those files.** A mismatch fails `--check`, and `cut()` refuses
to write anything at all if the tree does not already agree, because a
half-bumped tree is worse than an un-bumped one.

**The plugin stamps its version into `out.txt`**, next to its boot marker, and
the panel renders its own from `/api/state` (not from a literal in `HTML`, so
there is nothing to go stale). The two are installed separately and can be
different builds - Known Limitations item 12 makes that concrete - so "which
build produced this log" is load-bearing for any report about rates or timing.

**The boot marker is the trap.** `plugin_boot_count()` counts occurrences of the
literal `BloodPact plugin loaded`, and `watcher()`'s new-process detection is
built on a *change* in that count. The version is appended **after** the marker,
keeping the substring contiguous; interpolating it (`BloodPact 1.3.20 plugin
loaded`) would silently break auto-apply after a game restart with no error
anywhere. Two tests pin this.

`build_release.py` now generates its PyInstaller `--version-file` content from
`__version__` into `build/` at package time, so the Windows version resource is
**derived** rather than becoming a third site to sync. There is deliberately no
tracked `version_info.txt` under `ForgePact/` (HS-Offline-Launcher keeps one;
see its guide for why it is not covered yet).

### Finding 8: the `object_index` struct read is research-only, with a destination

`Hook_distance_to_object` reads `object_index` through
`CallBuiltin("variable_instance_get", ...)`. Reading it off the `CInstance`
instead would remove **50%** of what the lied-to path still costs after the
dedup (the harness prints that share). It is **not shipped**, and the reason is a
rule, not a preference:

- Without `YYTK_DEFINE_INTERNAL`, `CInstance` is opaque - accessors only. With
  it (which `plugin_build/build.bat` passes), `CInstance` holds an **anonymous
  union of three layouts** and the only way in is `GetMembers()`.
- `GetMembers()` is not a field read: it calls `GetBuiltin("id")` on **every**
  invocation and compares `m_ID` in each arm to pick one. If none match it prints
  an error and returns a layout that is not this build's.
- The failure mode is the bad one: a garbage index makes `IsCreatorObject()`
  return false, and map reveal and the Beacon silently stop lying - a feature
  that reports armed and does nothing.
- `GetMembers()` is used nowhere else in the plugin, so there is no positive
  control on this runtime, and `AGENTS.md` requires one before a struct read
  ships. The behaviour harness cannot supply one either: it stubs `CInstance` as
  a plain struct with an `int object`, which cannot represent the union question
  at all.

**What 1.3.20 plants is the instrument.** A research-build-only probe
(`objidxprobe`, absent from `kPlayerCommands`, inside `#ifndef FORGEPACT_RELEASE`)
compares `GetMembers().m_ObjectIndex` against the `variable_instance_get` answer
the hook computed anyway, counts agreements / disagreements / `GetMembers()`
failures, logs one line naming the first mismatch, and **times both reads** so it
can print medians. The shipped path uses the `CallBuiltin` answer on every path;
the probe reads, times and counts, and decides nothing. A contract test asserts
`GetMembers(` is absent from `strip_research_blocks(plugin_source)`.

**It is off until you ask for it: `objidxprobe on`.** `off` stops it and keeps
the counters; `reset` clears the counters and does *not* stop it; a bare
`objidxprobe` reports, and the report names `ON`/`OFF` so a run of zeros cannot
be misread as "no disagreements". The gate exists because the failure this probe
is measuring for is the one it could itself trigger: `GetMembers()` picking an
arm this build does not have is documented to return a wrong layout, and if the
real `CInstance` is smaller than that arm, reading `m_ObjectIndex` is a read past
the allocation — which `/EHsc` means the probe's own `catch (...)` will not
catch. Backing out of that should cost a command, not a rebuild.

**Two things its numbers do not say, because both read the other way round.**
The probe prints them itself, and they belong here too, since this is where the
session's results get written down.

- **The counts are instances reaching the hook while a lie is wanted, not
  creators.** The probe runs *after* the `(!beaconWants && !revealWants)`
  early-out and *before* `IsCreatorObject`, so it samples everything
  `Hook_distance_to_object` gets as far as identifying — not every call the
  game makes, and not only creators. Record the figure that way; calling it a
  creator count would promote it into a claim the measurement does not make.
- **`getmembers-failed` counts thrown exceptions only.** The documented failure
  mode of `GetMembers()` is to match no arm, print an error and return a layout
  that is not this build's - which does **not** throw. So a zero there is not
  evidence that `GetMembers()` succeeded; that failure arrives as a
  *disagreement* instead. (Related, and also not evidence either way: the plugin
  compiles with `/EHsc`, so the probe's `catch (...)` cannot catch an access
  violation from a wrong union arm. No input demonstrating one has been seen;
  that is "not observed", not "does not happen". Research build only.)

**The destination - the design a later workorder would implement.** "Is this
layout correct on every future game build" is unanswerable. "Is it correct in
this process, right now" is answerable cheaply, every run. So the eventual
shipped shape is a **self-validating fast path that fails safe**:

- for the first `kObjIdxValidations` creators of a session (64 is a reasonable
  start), compute **both** values and compare, using the `CallBuiltin` answer for
  the decision while validating;
- all agree -> use the struct read for the remainder of the session;
- **any** disagreement, ever - including a `GetMembers()` failure or a throw ->
  fall back permanently to `CallBuiltin` **for that session**, log exactly one
  line naming what mismatched (expected, got, which creator), and increment a
  counter surfaced by `reveal stat`;
- never silently prefer the fast answer.

That is `AGENTS.md`'s validate-refuse-and-count discipline applied to a layout
rather than an address, the same shape as `SetRelicGate`'s refusal and
`InvokeMethodValue`'s one-line failure log.

**The go/no-go threshold, so this closes on a number.** Both conditions required:

1. **Share of the hot path** - the `object_index` read must be **at or above
   33%** of what the lied-to path costs. The harness prints it: 1 of 2 calls,
   **50%**. This condition **passes**, which deliberately moves the decision onto
   the second one.
2. **Measured cost ratio** - the struct read's median must be **at or below 50%**
   of the `variable_instance_get` median. This is the condition genuinely in
   doubt, because `GetMembers()` itself calls `GetBuiltin("id")` once per
   invocation, so it may be no cheaper at all. Only the live session can answer
   it.

If either fails, or the probe cannot produce timings, **finding 8 closes as
"measured, not worth it"**: the probe is removed in a follow-up and the negative
is written here with its numbers. If both pass and the session shows agreements
> 0 with **zero** disagreements, the later workorder builds the self-validating
path above. `0/0` has measured nothing - the probe says so itself rather than
letting it read as "no disagreements found".

### `InstallHeadLabelHook()` - not changed, measured live

`InstallHeadLabelHook()` is still called unconditionally from `ModuleInitialize`,
and 1.3.20 does not change that, not even behind a flag. The open question is
whether it should be *armed* instead, and it is an open question - **"leave it
alone" is a legitimate outcome.**

- The per-frame cost is almost certainly nil: `HhDrawHeadLabels()` opens with one
  atomic load plus a vector-empty check. The real question is load-time work plus
  an eager binary patch in release builds, not frame time.
- **The detour timing is the part that is easy to miss.** Since the PR #2 fix,
  `HookOneScript` installs both the table swap and an inline detour, and the
  detour is attempted only on the **first** install - the one moment the table
  still holds the game's own function. An armed install must still be the first
  one for that target or it silently degrades to table-only. The log says which:
  `HOOK INSTALLED on DrawHudBuffs` versus `hook DrawHudBuffs: TABLE-ONLY (<reason>)`.
- "Later is safer" is an **inference**, not a measurement. Known Limitations item
  8 records that installing the `DropRelic` hook during character selection
  stalled the runner, which is the same direction - plausible, not established.
- The instrument exists in **both** builds: `hhlabel` is in `kPlayerCommands` and
  its reply prints `callback ok|missing`, `hudCalls=`, `draws=` and `lastErr=`.

A contract test pins the eager install unchanged, so this change cannot drift
into it.

### 1.3.20 is written but NOT released

The version is set and `release-notes-v1.3.20.md` exists; **no release action was
performed**. Nothing was built, nothing was staged into `modfiles_shipped/`,
nothing was packaged into `dist/`, and no tag was created. An untouched `build/`,
`modfiles_shipped/`, `plugin_build/` and `dist/` is the deliberate consequence.

#### Live session verification (human-run, before the release)

Every step names a **positive control**, per `AGENTS.md` § "Prove the Instrument
Before Trusting a Negative Result": a reading of "no change" means nothing until
the same instrument has produced a non-zero somewhere in the same session. A
failed control voids the measurement; it does not mean the fix did nothing.

1. Build and stage the research DLL: `plugin_build\build.bat dev`, then copy
   `plugin_build\BloodPactPlugin_rel.dll` into the game's `mods\aurie\`. Do
   **not** restage `modfiles_shipped\`. Drive it with
   `.\ForgePact\tools\ipc.ps1 <command>`; `-Tail 40` reads recent `out.txt`
   lines without sending anything.
2. **Confirm the build identity first.** `-Tail 40` right after launch should show
   the `BloodPact plugin loaded` line carrying 1.3.20, and the panel should show
   the same version. If they disagree, stop - that is a mixed install and every
   measurement below would be ambiguous. Ending that confusion is what finding 9
   is for.
3. **Frame cost, all three plugin findings at once.** `ipc.ps1 perf reset`, play
   ~60 s of ordinary combat with Special Content, Orb Pickup and Map Reveal
   (packs on) enabled, then `ipc.ps1 perf`. Record `avg`/`max` frame interval and
   the `FrameCallback body` / `PollCommands` buckets. *Control:* a non-zero frame
   count and non-zero time in at least one bucket. All zeros means the profiler is
   not running (wrong DLL, or a release build).
4. **`eSt`.** Enable a Special Content type, `ipc.ps1 eststat`, record `yazma=` and
   the `guncel eSt` line. Change rooms and read it again: `yazma=` must have
   increased and `guncel eSt[0]` must read the forced value. *Control:* `yazma=`
   increasing across a room change proves the room-gated caller fires. If it does
   not move, the room key read is blind - that is a defect-grade result, not a
   pass. Repeat over three or four room changes including a Chaos Tower / Shadow
   Realm entry, and confirm Special Content still appears at the rate it did.
5. **Orb pickup.** `ipc.ps1 orbpickup 1`, kill until globes drop, walk near them,
   `orbpickup stat`. Expect `seen>0`, `pulled>0`, `noplayer=0`, and a glide that
   looks the same as before. *Control:* `pulled>0` with a globe visibly
   travelling. `seen=0` while standing next to globes means the scan is blind.
   Confirm `seen=` is much smaller than the pre-change value for a comparable
   stretch - at rest it lands near 1/15th, but the travel-forced rescan makes
   the real factor depend on how much you moved, so do not treat a higher number
   as a fault. `uncacheable=` must be **0**; anything else means this runner
   stopped returning a handle kind the cache can hold, and the scan is refusing
   globes rather than crashing on them.
   Then **do it again with Movement Speed at 10x**, which is the case the
   throttle had to be made safe for: run past a field of globes at full speed and
   confirm every one of them still glides in. *Control:* the same run with the
   multiplier at 1x - if globes are picked up at 1x and missed at 10x, the
   travelled-distance rescan is not firing, and that is a defect-grade result
   rather than a tuning question. `orbpickup stat` cannot show this on its own:
   `seen>0`/`pulled>0` stay healthy either way, which is precisely why it is
   watched by eye here and pinned by `fastplayer/*` in the harness.
6. **Map reveal.** Enable Map Reveal with packs, enter a new zone, `reveal stat`:
   a window opens (900) and zones-populated increases. *Control:* the zone
   visibly fills with packs - `docs/map-reveal-research.md` records 208 -> 1273
   enemies in one zone.
7. **Panel and launcher.** With the panel open, close and reopen the game:
   settings must be re-applied automatically. *Control:* this is the direct test
   of the incremental boot counter **and** of the version stamp on that same log
   line - if the stamp had broken the marker, this is where it shows. Time
   Launch-to-applied before and after. Then exercise the poll tiers in both apps:
   move a control and confirm an update within a couple of seconds; leave the
   window visible and untouched for a minute and confirm updates slow; switch away
   for ten minutes and confirm near-zero CPU in Task Manager; switch back and
   confirm an immediate refresh.
8. **The `object_index` probe.** Turn it on first - `objidxprobe on`; it does
   nothing until you do, and the report's `ON`/`OFF` field is how you check. Then
   with Map Reveal packs on, enter a zone, and read
   `objidxprobe`. **Required:** agreements **> 0** and disagreements **= 0**.
   *Control:* the agreement count itself - `0/0` has measured nothing and settles
   nothing; do not record it as "no disagreements found". If the game misbehaves
   while it is on, `objidxprobe off` is the way out. Record the counts as
   *instances through the hook while a lie was wanted*, not creators, and do not read
   `getmembers-failed=0` as "`GetMembers()` worked" - it counts throws only, and
   the documented wrong-layout return does not throw. Then apply the two
   thresholds above and **write down which way it fell**, with both medians, the
   ratio, the game build and the date, in this file.
9. **`InstallHeadLabelHook()`.** Establish the control on the eager path first:
   enable Headhunter, steal an affix, `hhlabel 1` - require `callback ok`,
   `hudCalls > 0` and `draws > 0` before anything else. Record whether `out.txt`
   says `HOOK INSTALLED on DrawHudBuffs` or `TABLE-ONLY`. Then ask whether a
   deferred install works at all, and whether the eager one costs anything
   measurable (compare process-start-to-plugin-ready with head labels never
   enabled). **Write the decision down either way**, here, with the numbers and
   the log lines. "Measured, costs nothing, left eager, here is the evidence" is a
   complete outcome.
10. Restore the shipped DLL in `mods\aurie\` so the tester is not left running a
    research build, and fold any surprises into this file and, if a
    player-visible number changed, into `release-notes-v1.3.20.md`.

#### Manual release checklist (human, after the live session)

Run in this order; the order is the guardrail.

1. Confirm the live session passed and its numbers are already in the release
   notes and in this file.
2. From `ForgePact/`: `py -m unittest discover -s tests` - green.
3. From `ForgePact/`: `py tools/cut_release.py --check --expect 1.3.20`.
4. Tag it: Run Actions > ForgePact tag on `main`, per "Tagging a release
   (forgepact-tag.yml)" below. This bumps the version if needed, pushes the
   tag, leaves a **draft** release carrying the composed notes, and starts
   "ForgePact release" against that tag.
5. Wait for the "ForgePact release" run to finish (~15 minutes).
6. Download `ForgePact-1.3.20.zip` from the draft, check it against the
   `.zip.sha256` asset, install from it, and run the **CI build launch gate**
   (see "The build half (forgepact-release.yml)" below). Record the row in
   that section's table before doing anything else.
7. **Fallback, only if CI is unavailable:** build locally instead --
   `plugin_build\build.bat release` (compiles and auto-stages
   `BloodPactPlugin_ship.dll`), confirm the staged DLL matches
   (`build_release.py`'s guard aborts otherwise; Known Limitations item 4 -
   the most common "build keeps failing" report), `py build_release.py`,
   sanity-check the bundle (panel reports 1.3.20, Properties -> Details shows
   the stamped version resource, the World tab's Satanic Zone section has
   rows, the Mods tab toggles still send), start the game once with the
   shipped DLL and confirm `out.txt`'s `BloodPact plugin loaded` line carries
   1.3.20, then zip it by hand (the CI shape: root `ForgePact-1.3.20/`) and
   upload it to the draft yourself before running the same launch gate
   against that upload.
8. Review the draft's composed body, and rewrite any section under the
   generated-notes banner into player language.
9. Publish. That fires `notify-hub-release.yml`.
10. Check that the "ForgePact notes cleanup" run publishing started has
    deleted the `release-notes-v*.md` files this release carried from `main`.
    If it failed, re-run it with the tag. See Representative Change Workflow
    §6. **For v1.3.20 it will not start on its own:** that tag was cut before
    the workflow existed, and a release event runs the workflows in the
    tagged commit. Run "ForgePact notes cleanup" by hand with `v1.3.20` after
    publishing; it deletes 1.3.17, 1.3.18, 1.3.19 and 1.3.20.
11. HS-Offline-Launcher is **not** part of this release; see its own guide.

---

## Tagging a release (forgepact-tag.yml)

`forgepact-tag.yml` (`workflow_dispatch`, "ForgePact tag" in the Actions tab)
automates everything up to a running build: type a version (`1.3.21` or
`v1.3.21`), and it checks the tag is one this repository can actually
release, moves the version to match with `tools/cut_release.py`, pushes the
tag, leaves a **draft** release whose body `tools/forgepact_tag.py`
composes, and starts "ForgePact release" (`forgepact-release.yml`) against
that tag. It still never publishes — see "The build is dispatched, never
inlined" and "The build half (forgepact-release.yml)" below.

### How to run it

Actions > ForgePact tag > Run workflow, on `main`, with the version typed
into the `tag` box. Read the job summary afterward: it says whether a bump
was made, where the draft notes came from (`source=file` / `files` /
`generated` / `mixed`), and — when any section is generated — a bold
reminder to rewrite it before publishing.

### The five refusals

Everything downstream trusts the tag, so anything wrong with it is decided
before any write:

1. **The tag has the wrong shape.** Not three plain numbers, optionally
   `v`-prefixed (`vv1.3.21`, `V1.3.21`, `hub-v1.3.21`, a leading zero, a
   suffix like `-rc1`, and non-ASCII digits are all refused).
2. **The tag already exists.** A second release on one tag makes
   `releases/latest` ambiguous.
3. **The version is below the highest existing `v*` tag.** `releases/latest`
   would point backwards.
4. **The version is below what `main` already holds.** ForgePact does not tag
   every version it ships — `main` moved from 1.3.16 straight through
   1.3.17–1.3.20 with no tag for any of them — so the highest *tag* and the
   tree's actual version can disagree. Without this check, tagging `v1.3.17`
   today would relabel 1.3.20's code as 1.3.17.
5. **The version already has a release, drafts included.** Catches a draft
   sitting on a tag that was never pushed, which the tag-existence check
   alone cannot see.

Release notes are **never** a refusal — see the composition rules below and
`AGENTS.md`.

### The draft and how its body is composed

The workflow always calls GitHub's `releases/generate-notes` before any
write (so the YAML has no branch on whether the top notes file exists — that
decision belongs entirely to `tools/forgepact_tag.py`, which has tests for
it), then calls `forgepact_tag.py --compose-notes`:

- **The tagged version's own `release-notes-vX.Y.Z.md`**, if it exists, is
  the top section, byte-identical (normalised to `\n`, one trailing newline)
  to today's one-file practice.
- **Otherwise**, the top section is GitHub's generated notes (pull-request
  titles since the previous tag) under a visible banner:
  `> **Draft notes, generated from pull request titles.** Rewrite the
  ForgePact <version> section for players before publishing: the Toolkit Hub
  shows this text to players.` That section must be rewritten into player
  language before the draft is published.
- **Every skipped version's notes file** — strictly above the previous `v*`
  tag and below the tagged version — is concatenated after the top section,
  **newest first**. Tagging `v1.3.20` today needs no bump (the tree is
  already there) and carries 1.3.20, 1.3.19, 1.3.18 and 1.3.17, because none
  of those four was ever tagged or released on its own.
- **With no previous `v*` tag at all**, there is nothing to bound "skipped"
  with, so it is empty by definition rather than walking the whole history.
  Not reachable for ForgePact today.
- **`## How to update` is kept only once**, in the first file-sourced
  section, and stripped from every later one — it is identical boilerplate
  every time, and repeating it once per concatenated version would spend
  roughly 800 characters of the hub's catalog budget per repetition for no
  new information.

**Why newest first matters.** The hub's `tools/build_catalog.py` truncates a
release body at **8000 characters** and appends a "see the release page"
notice (`docs/hub/catalog-schema.md`). ForgePact's notes for 1.3.17–1.3.20
alone already total over 11000 characters, so tagging a version with several
skipped predecessors is routinely going to get truncated in the catalog —
newest-first means the cut lands on the oldest skipped version, never on the
version players are actually updating to. This is a known, accepted
trade-off; the hub is not changed and notes are not trimmed to fit.

### The build is dispatched, never inlined

`forgepact-tag.yml` itself still never builds, uploads or publishes: no
`build_release.py`, no `build.bat`, no `upload-artifact`, no
`gh release upload`, no `--draft=false`, no `gh release edit` anywhere in
this workflow's own steps. The one exception to "never touches the build" is
the dispatch itself — a `gh workflow run forgepact-release.yml --ref main
-f tag="$TAG" -f dry_run=false` step named "Start the build", right after the
draft is created, needing `actions: write` for the same documented reason the
hub's tagger does (starting another workflow run with `GITHUB_TOKEN` is
normally blocked; `workflow_dispatch` is one of the two exceptions). Publishing
the draft stays a human act at
`https://github.com/falorfrozen-cmd/ForgePact/releases`, and it is what fires
`notify-hub-release.yml`.

### The `GITHUB_TOKEN` bump does not notify the hub

The version-bump commit this workflow pushes is authored by
`github-actions[bot]` using the workflow's own `GITHUB_TOKEN`, and a push
made that way does not trigger another workflow run on this repository —
so `notify-hub.yml` (which watches pushes to `main` to open the hub's
submodule-pointer bump PR) does not fire from it. The hub's pointer bump
simply waits for the next push made by a human merge to `main`. This is a
known gap, not a bug to fix.

### Tag-without-release recovery

If the final "Leave a draft release carrying the notes" step fails, the tag
has already been pushed and no release exists on it — the same state a
hand-made `git tag` + `git push` leaves. Recovery is creating the release by
hand from the composed notes (they are still in the job's logs and in
`$RUNNER_TEMP`, which does not survive past the run — regenerate with
`tools/forgepact_tag.py --compose-notes` if needed). There is no retry
machinery.

### The build half (forgepact-release.yml)

`modfiles_shipped/` tracks only `.keep`, so `build_release.py`'s own guard —
`ERROR: modfiles_shipped is incomplete` — used to stop a CI checkout
immediately, and `plugin_build/include/` (the YYToolkit/Aurie headers the
plugin compiles against) is gitignored. `forgepact-release.yml` is what fills
both gaps: `tools/fetch_toolchain.py` places the pinned headers and binaries
(all-or-nothing, verified by SHA-256), and the workflow runs on a Windows
runner with MSVC.

**Trigger shape, and why it differs from the hub's.** `hub-tag.yml` dispatches
`hub-release.yml --ref "$TAG"` — against the tag itself, because every guard
in that workflow is keyed on `github.ref`. `forgepact-release.yml` is
dispatched against **`main`**, with the tag passed as a `tag` **input**
instead, for two reasons: a tag cut before this workflow existed (every
version through v1.3.20) carries none of it — no `forgepact-release.yml`, no
fetch script, no vswhere-aware compiler discovery — so `--ref v1.3.20` could
not run at all; and a fix made to the build workflow could never apply to an
already-tagged version otherwise. Every guard is keyed on the validated `tag`
input, never on `github.ref`, so the hub's "dispatched against a branch skips
its tag guards" failure class cannot occur here — a test pins that the
workflow refuses to run unless `github.ref_name == main`. It also takes a
`dry_run` input (default `true`, like `hub-release.yml`) and an optional
`hub_ref` input (default `main`) that lets a rebuild reproduce an earlier
one's `hs-game-sdk` snapshot.

**Two draft guards, not one.** Every run requires exactly one release on the
tag, and it must be a draft — checked once as the first step (before any
checkout of the tag, so a bad tag or an already-published release fails fast
on a cheap step) and again immediately before `gh release upload`, because a
human can publish the draft during the build's ~15 minutes. `--clobber` on
the upload is only safe because of those two guards; it exists so re-running
a draft's build replaces its assets. The messages distinguish "no release —
run ForgePact tag first", "already published — refusing to replace a
published release's assets", and "more than one".

**What comes from the tag, what comes from `main`, and the compile-line
guard.** The plugin and panel source, `build_release.py`, `tools/cut_release.py`,
`tests/` and the compile line all come from the **tag** (checked out into
`ForgePact/`). The pins, the fetch/package scripts and `build.bat`'s compiler
discovery come from **`main`**'s own checkout (`forgepact-ci/`), because a
tagged tree's `build.bat` cannot find MSVC on this runner. So the CI job
copies `main`'s `plugin_build\build.bat` over the tag's own copy — but only
after `tools/release_ci.py compile-line` proves the two files' `cl ` line and
their `set "FLAGS=…"` / `set "OUTPUT=…"` lines are byte-identical. If they are
not, the job fails rather than silently compiling something other than what
the tag says it ships. Discovery may differ between the two files; what gets
compiled may not.

**The pin table**, from `tools/toolchain-pins.json`:

| File | Source | Commit / release | SHA-256 (prefix) | Provenance |
| --- | --- | --- | --- | --- |
| `YYToolkit/YYTK_Shared*.hpp`, `.cpp` (5 files) | `AurieFramework/YYToolkit`, `ExamplePlugin/include/` | commit `5a95e46` (tag v4.0.1) | `6d6666f1…`, `ab64a23e…`, `bec19a3f…`, `93531e2d…`, `7d3ad542…` | YYToolkit v4.0.1, unmodified |
| `FunctionWrapper/FunctionWrapper.hpp` | `AurieFramework/YYToolkit`, same commit | commit `5a95e46` | `e72e263d…` | YYToolkit v4.0.1, unmodified |
| `Aurie/shared.hpp` | `AurieFramework/Aurie`, `Aurie/source/framework/shared.hpp` | commit `5c4839e` (tag v2.0.2) | `c830652f…` | **Aurie v2.0.2's own header — not YYToolkit v4.0.1's bundled `include/Aurie/shared.hpp`**, which is a different (older, 1.x) header; players run AurieCore 2.0.2, so this is the one that has to match |
| `modfiles_shipped/AurieCore.dll` | `AurieFramework/Aurie` release | v2.0.2 | `18e3a1de…` | Aurie Framework, unmodified |
| `modfiles_shipped/AuriePatcher.exe` | `AurieFramework/Aurie` release | v2.0.2 | `4d3aec43…` | Aurie Framework, unmodified |
| `modfiles_shipped/YYToolkit.dll` | `falorfrozen-cmd/ForgePact` release zip | `ForgePact-1.3.16.zip` (v1.3.16) | `bb113eef…` | Modified YYToolkit (`yytoolkit-modified/NOTICE.md`); byte-identical in every release v1.3.1 through v1.3.16, so extracting it from the published v1.3.16 zip ships exactly what has already been launched against the game, rather than a fresh CI build against a different MSVC that nobody has run |
| `modfiles_shipped/HSOfflineTrackerProducer.dll` | same v1.3.16 zip | v1.3.16 | `36608aa0…` | HS-Offline-Tracker's live sensor (optional); a 2026-09-07-or-earlier build, present in every release since v1.3.10 |

**hs-game-sdk comes from the hub's `main`, sparse-checked-out**, not from any
hub commit whose `ForgePact` gitlink happens to equal the tagged commit — at
dispatch time that commit usually does not exist yet (the bot's version-bump
push never fires `notify-hub.yml`, and a human merge's bump PR is often still
open). The resolved hub commit SHA is recorded in `BUILD-INFO.json`
(`hub_commit`) and the job summary. Local manual builds already use whatever
hub checkout the maintainer has, normally `main`, so this matches existing
practice; an incompatible SDK fails the contract tests or the compile rather
than shipping.

**CI DLLs are not byte-identical to a local build**, even from the same
source: the runner's MSVC (VS 18.9 on `windows-2025-vs2026`) is not
necessarily the same `cl` version as a maintainer's machine. `BUILD-INFO.json`
records `cl_version` for exactly this reason — a launch-gate regression that
does not reproduce locally is a place to look.

**Dispatch-failure recovery.** If `forgepact-tag.yml`'s "Start the build" step
fails, the draft exists with no build behind it — recovery is running
"ForgePact release" by hand from the Actions tab with the same `tag` and
`dry_run=false`.

**Refusals this workflow enforces, besides the two draft guards:** it never
contains `gh release create`, `gh release edit`, `--draft=false`, `--latest`
or `gh workflow run` — a test asserts none of those five appear anywhere in
the file — and no job in it carries `actions: write`, since it starts nothing
else.

#### CI build launch gate

Before publishing **any** CI-built zip — not only the first — a human
downloads `ForgePact-X.Y.Z.zip` from the draft, checks it against the
`.zip.sha256` asset, extracts it, installs with "Install Mod Plugin" from that
folder, launches the game, and confirms three things: `out.txt`'s
`BloodPact plugin loaded` line carries X.Y.Z, the panel shows X.Y.Z, and one
player-build smoke command responds (e.g. `orbpickup 1` then `orbpickup 0`
printing its stat line, or `hhlabel` printing `callback ok`). Record a row
here before pressing Publish.

| tag | run URL | zip sha256 | installed from zip | out.txt boot line + version | panel version | mod smoke check | launch gate result | date | tester |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v1.3.20 | | | | | | | | | |

---

## Known Limitations & Gaps

1. **The Abyss Spawner (`Spawn_Abyss_obj`):**
   - `Spawn_Abyss_obj` is currently **unsupported**. It sets `discoverable = true`, placing it behind an unmapped two-stage discover-then-activate gate that fails to place objects even when forced. Full investigation details are documented in `docs/S10-special-content-notes.md`.
2. **Equipped Item Detection for Custom Mechanics:**
   - Active mechanics like Headhunter, Beacon, and Tyrant's Crown currently rely on `force` commands sent by the panel rather than dynamically reading equipped inventory slots in C++.
3. **Release vs. Research Command Separation:**
   - Diagnostic commands (`readmem`, `census`, `enemylog`, `probestruct`, `structdump`) are excluded from release builds (`/DFORGEPACT_RELEASE`) to protect performance and stability.
4. **Build order matters since `build_release.py`'s plugin-sync guard:**
   - `build_release.py` now refuses to package unless `plugin_build\BloodPactPlugin_ship.dll` exists and byte-matches `modfiles_shipped\BloodPactPlugin.dll` (see `build_release.py`). Always run `plugin_build\build.bat release` (which now auto-stages the DLL into `modfiles_shipped\` and, if present, `dist\ForgePact\modfiles\`) *before* `py build_release.py`. Running the packaging script first, or after editing `plugin/ModuleMain.cpp` without rebuilding, is the most common "build keeps failing" report.
5. **Hot builtins must stay allocation-free (`distance_to_object`):**
   - `distance_to_object` is called by every spawner's periodic proximity check, so a hook body that calls into the runner (`asset_get_index`, `object_get_name`) or allocates per call collapses the frame rate. Any builtin hook should follow the shape of `HookICD`: cheap pass-through first, cached integer comparisons after.
   - Note the calling convention: for a builtin hook, `Args[N]` holds the GML arguments. `Other` is the GML `other` context, **not** the argument — matching an object argument against `Other` silently never fires.
   - **Measured 2026-09-09:** the globes do **not** reach the player through `distance_to_object` at all. With the player and all four globe objects resolved correctly, a full session shortened **0** distance checks.
   - **Measured 2026-09-10:** hooking the globe step scripts does not work either. `HookOneScript` reported both `ExpGlobeStepMain` and `MFGlobeStepMain` installed, and the hook body ran **0** times — the globes' step logic is not dispatched through those script-table entries. After two failed interception points, `orbpickup` is driven from `FrameCallback` instead (`OrbPickupTick`), enumerating globe instances with `instance_number` / `instance_find`. The frame callback is known to run because the stall watchdog heartbeats from it. **Prefer this pattern when an interception point is unproven:** drive from the frame callback, which cannot silently not-fire.
6. **Diagnose stalls with the built-in watchdog, do not guess:**
   - A multi-second freeze on the character screen was attributed twice to the wrong cause. `ModuleMain.cpp` carries a stall watchdog in the **research build only** (`build.bat dev`; since 1.3.21 it is inside `#ifndef FORGEPACT_RELEASE`, heartbeat included, so the player DLL starts no thread and suspends nothing — enforced by `test_release_hook_contract.py::test_stall_watchdog_never_reaches_the_player_build`): a background thread notices when `FrameCallback` stops ticking for 3 s, suspends the frame thread just long enough to read its instruction pointer, and appends `STALL <ms> - frame thread at <module>+<rva>` to `bp_ipc/out.txt`, plus disk bytes and free RAM across the stall. That separates "stuck in BloodPactPlugin" from "stuck in the game" and "machine-wide thrashing" from "waiting on the GPU", with no debugger.
   - The frame thread is resumed **before** any allocation or formatting. Suspending a thread and then allocating is how this class of tool deadlocks on a heap/CRT/loader lock the stalled thread is holding; keep that ordering if you touch it.
   - **Measured 2026-09-09, character-select freeze (up to 85 s):** no sample landed in `BloodPactPlugin.dll`. The frame thread was blocked in `ZwWaitForSingleObject`, `ZwQuerySystemInformation`, `NtDxgkSubmitPresentToHwQueue` and `NtGdiDdDDIGetDeviceState` — kernel waits and GPU present/device-state calls — with no display-driver timeout (event 4101) logged. Resolve such addresses by parsing the export table of the named DLL and taking the nearest preceding export; the consistent `+0x14` offset is the syscall stub's return address.
   - **CONCLUDED — the freeze is not ForgePact.** A control run with `BloodPactPlugin.dll` removed from `mods/aurie/` (Aurie module list: YYToolkit + the game only) froze on the same screen. The same run also still produced the four `Unable to find any instance for object index ...` entries in `YYToolkit.log`, with identical indices and stacks, confirming those are game/YYToolkit noise and not caused by the plugin. Removing the plugin also removes the watchdog, so further measurement needs the out-of-process probe below.
   - **Measured 2026-09-10, with I/O and memory attached to each stall:** two stalls of ~65 s each showed **0 KB and 1 KB** of game disk reads, and free RAM *rising* by 1.1 GB and 843 MB respectively; sampled instruction pointers were `ZwWaitForSingleObject`, `NtGdiDdDDIGetDeviceState` and `ZwFreeVirtualMemory`. So the freeze is neither disk/anti-virus nor memory pressure — the process is blocked releasing memory and querying GPU device state. Remaining suspects are the display driver / GPU resource teardown, not the game's asset loading and not ForgePact.
   - **Probe for freezes that are not ours:** `tools/freeze_probe.ps1` (repo root) samples the game from outside — `Process.Responding` to bracket the freeze exactly, plus the game's disk I/O, free RAM and machine-wide CPU busy/idle, ranking processes once per freeze. Its verdict line separates *the machine is thrashing* (AV / paging / disk) from *the game is waiting on the GPU*. Note that per-process CPU via `TotalProcessorTime` or `Get-Counter` costs 1.5–6 s per sweep on a normal machine, which is why the continuous loop uses `GetSystemTimes`/`GetProcessIoCounters` instead.
7. **`instance_find` returns a REFERENCE, not a number (this broke every player-gated feature):**
   - **Measured 2026-09-10.** `HhResolveLocalPlayer`'s fallback accepted only `VALUE_REAL`/`VALUE_INT32`/`VALUE_INT64` from `instance_find(Player_obj, 0)`. This runner returns `VALUE_REF` (kind 15), so the fallback **always** failed, and with `GetMyPlayer` also returning a non-`VALUE_OBJECT` value the whole resolver returned false on every call. Everything gated on the local player then silently did nothing: `orbpickup` logged `seen=176993 noplayer=176993`, the relic filter never armed, and the Headhunter head labels reported "local player not found".
   - An instance reference is passed straight through — `variable_instance_get` accepts it. `HhUsableInstance()` now validates a candidate by *reading a variable from it*, which is what every caller does next, rather than trusting a kind tag. `orbpickup stat` reports `player via GetMyPlayer` / `instance_find(Player_obj)` / `none` so this can never fail silently again.
   - **Reading that output since 1.3.20:** `seen`, `noplayer` and `outofreach` are each counted once per globe per *scan*, not per frame, so the numbers above would be much smaller today for identical behaviour — but they are still counted the same way **as each other**, which is what made `seen=176993 noplayer=176993` a diagnosis rather than two unrelated figures. `pulled` is the one counter still on the frame clock. Do **not** convert a scan count back into frames: 15 frames is the ceiling on the scan period, not the period — a rescan is forced early by distance travelled and by the player resolving again, measured at 5 scans per 15 frames at ~10x movement speed. The printed line names both clocks and says the period is a maximum; see "Orb pickup: the scan is throttled, the pull is not".
   - `uncacheable=` on the same line is a fourth branch of the tree, added in 1.3.20 with the handle cache: a globe whose handle could not be held across frames was refused rather than stored. It is expected to stay 0 on this runner, and a non-zero means the runtime changed what `instance_find` hands back — the feature degrades to refusing globes instead of dereferencing freed memory.
   - **Independently, upstream hit the same bug class** in the Headhunter kill/steal path (origin `v1.3.16`, commits `7743a99`/`4ae4e30`/`8005249`) and fixed it there with `HhResolveInstance()` — a `CInstance*` resolver that also accepts `VALUE_REF`, verifies the resolved instance still exists, and checks its `id` matches. The two fixes are complementary, not duplicates: `HhUsableInstance()` validates an `RValue` for callers that only need to read variables from it (orb pickup, the relic filter); `HhResolveInstance()` converts to an actual `CInstance*` for callers that need one (`HhSteal`). `HhSteal`'s own fallback now calls `HhResolveInstance()` on `HhResolveLocalPlayer`'s result rather than the old `p.ToInstance()` (which silently dropped a `VALUE_REF`, same failure mode) — see the merge commit on `release/v1.3.17` for the full reconciliation.
8. **Mods that install a hook must be armed, not hooked, at launch:**
   - Installing the `DropRelic` hook while character selection is still running stalls the runner. `relicfilter 1` therefore only sets `g_RelicFilterPending`; `FrameCallback` installs the hook once the `fc > 300` setup gate has passed and `HhResolveLocalPlayer` succeeds. This is what lets `build_cmds` emit the command at launch — an earlier workaround withheld it from `build_cmds` entirely, so the panel toggle stayed on but the mod silently did nothing after a game restart.
9. **Another instance of lesson 5 (unproven interception point → drive from the frame callback):**
   - **Live-tested 2026-09-10.** `LoadSatanicZone` looked like the obvious hook target for filtering the Satanic Zone buff/debuff pool (`satmods`) - it resolves and is hookable via `HookOneScript`. An unconditional call counter added to the hook stayed at **0** through a normal zone load, 30+ seconds of walking, and an explicit waypoint/portal travel, while `Controller_obj.satanicZoneBuff`/`satanicZoneDebuff` visibly changed on their own in that same window: the game does not call it during normal play. (Rereading `HS-Offline-Tracker`'s README: it is *their* diagnostic code that calls `LoadSatanicZone(room)`, not something the game calls internally.) Same fix as lesson 5: `SatanicPollTick()` samples the two arrays every 15 frames from `FrameCallback` and corrects any disabled id the instant the content differs from what was last seen, needing no knowledge of which routine performs the roll. Confirmed live correcting a disabled id within one poll tick, twice, across two separate ingame rolls. Full writeup: `docs/satanic-zone-mods-research.md`.
10. **`%f`-family `sprintf_s` on a game-memory-read `double` can abort the process (0xC0000409):**
   - A stale asset/script index or offset can make a `RValue::ToDouble()` read off game memory (e.g. an item's `droprate.base`) come back as `inf`/`NaN`/an astronomically large finite value. Formatting that with `%f`/`%.Nf` into a fixed `sprintf_s` buffer overruns it and the CRT fast-fails the whole game (`ucrtbase.dll`, exception `0xC0000409` / `STATUS_STACK_BUFFER_OVERRUN`) — this is what shows up as a hard "YYToolkit crash" with no other symptom. `ModuleMain.cpp` has a `SafeF()` helper (clamps non-finite doubles to `0.0`) used at every `droprate`/`dungeonkey` status-print call site and inside `VanilyaBase()` for exactly this reason; if a new command formats a game-read or `std::stod`-parsed double with `%f`, route it through `SafeF()` (or validate with `std::isfinite`) first.
11. **RESOLVED 2026-09-11 — the Pet Quest Collector no longer ships a hardcoded native address, the player build now contains none at all, and the replacement route is confirmed live (quest counter advanced):**
    - **What it was:** `PetQuestCollectOne()` reached the game's call-a-method-value helper as `GetModuleHandleA(nullptr) + 0xB489070`, called through the resulting pointer, and **validated nothing** — not the module, not the bytes, not the game build. Every other shipped mechanism in `ModuleMain.cpp` resolves by *name* (`HookOneScript`, `HookBuiltin`, `asset_get_index`), which fails loudly and harmlessly against an unfamiliar build. That one did not: on a build where the address is something else, the call transfers control into whatever is there. `relicgate` had already been deleted from this plugin for the same pattern (it still answers `bu ozellik kaldirildi (sabit adres oyun guncellemeleriyle kayiyor)`), so this was the second occurrence, in a player-facing mod that auto-applies its saved settings on every launch.
    - **Why the "no name-based route is known" justification was wrong:** the method value is anonymous, so `HookOneScript` indeed cannot see it — but the *call* never needed a name for the method itself. `CallBuiltinEx` supplies `self` and `other` to any builtin, so the runtime's own `script_execute` can be handed the value and dispatch it. That builtin is resolved by name; the value's internals are never inspected.
    - **The fix (third attempt — the first two are instructive):** `InvokeMethodValue` calls `CallBuiltinEx(res, "script_execute", item, lootManager, {methodValue, 1})`. No address **and no struct layout**. The call *shape* is unchanged and still the measured one (`self` = the item, `other` = `Loot_Manager_obj`, one real argument); only the route changed. Confirmed live: `collected=1`, `call route=script_execute (name-resolved, no layout)`, `dispatched-but-item-remained=0`, zero structural refusals, and the quest counter advanced in the UI.
    - **The attempt in between, and why it matters:** the first replacement read the callable off the method value's own `CScriptRef`. That needs no address, but it shipped broken — on this game's runner `m_Questpickup` is **not** a `CScriptRef` (`m_ObjectKind = 0`, `m_CallScript`/`m_CallYYC` both zero, `method_get_index` returns nothing, while sibling `s_lootDrawData` resolves to script `#105134`). It produced 309 counted refusals, 0 collects, 0 crashes. **A struct layout is the quiet version of a hardcoded address** — see the repo-root `AGENTS.md`. The `CScriptRef` route survives as a validated fallback, reached only if `script_execute` fails to dispatch, never as a retry of a call that already ran. Requires `/DYYTK_DEFINE_INTERNAL=1`, which `build.bat` now passes; see `plugin/BUILD.md`.
    - **The old shape survives as research only:** `citrace collect confirm native` (dev build) reproduces it for A/B against `scriptref`, the shipped default, and is itself address-checked now. `kCiCallMethodFnRva` lives inside `#ifndef FORGEPACT_RELEASE`.
    - **Enforced mechanically:** `tests/test_release_hook_contract.py::test_player_binary_calls_no_hand_resolved_game_address` strips the research blocks and fails if anything reachable from the player build names a `*Rva*` constant or computes a call target from a module base plus a literal. The rule it enforces is written up in the repo-root `AGENTS.md`, "Never Call an Address You Resolved by Hand".
    - **Diagnostics — `petquest 0` prints these in the shipped build too**, not just `petquest stat` in the research build. Alongside `collected`, the gameplay skip counters, lost targets and travel timeouts, it reports `call route=` (which of the two routes ran), `dispatched-but-item-remained=` (the call went through but the item was still there — the "quietly no-ops" failure `script_execute` was warned about), and a `REFUSED (structural)` line if a route was refused. The first structural refusal of a session also logs one line naming the exact field that failed. Between them these separate the three failure modes — *nothing ran*, *ran with no effect*, *ran and worked* — in a single launch, without a research build. A nonzero refusal count on a future build means the runtime is not shaped the way this build assumes; the answer is to re-check the route, **not** to go hunting for an address.

12. **RESOLVED 2026-09-12 — a table-only hook install is not just a blind instrument, it is a feature that reports armed and does nothing:**
    - **What it was:** `HookOneScript` installed by swapping the pointer inside the script-table entry and nothing else. This build's compiled GML calls another script with a direct `call rel32` bound at compile time, which never reads that table — the same finding that invalidated the Pet Quest research's "34 hooked call sites, 0 calls" (item 11's neighbours above, and `AGENTS.md`). Origin's review of PR #2 pointed out that the consequence is not confined to research: read-only inspection of the shipped executable found **direct native callers for `StatMovementSpeed`, `StatAttackSpeed`, `DropRelic`, `DropMonsterGold` and `DropGold`** (e.g. `StatMovementSpeed` caller RVA `0x59914ed` → target `0x5b06870`; `DropGold` with 12 verified direct callers). So stat scaling, the drop multipliers and the max-level relic filter could all log `HOOK INSTALLED` while the game ran straight past them.
    - **The fix:** the interception moved into the installer rather than onto the names that happened to get verified. `HookOneScript` now installs **both** — the table swap *and* an inline detour at the function's own address (`MmCreateHook`) — and sets `*origOut` to the **trampoline**, so a hook body reaches the real original from either route and never re-enters itself. Every present and future gameplay hook gets this; fixing only the five reported names would have left the rest blind.
    - **Three guards make repeat installation safe** (it matters: shared chokepoints like `DropRelic` are installed from more than one call site, and re-install is how this file makes that idempotent). The detour is attempted only on the **first** install (`!*origOut`), the one moment the table still holds the game's own function — a later install would read our own detour out of the table and patch that, an infinite loop. The target must lie **inside `Hero_Siege.exe`** (`AddrIsExecutableInModule`), so an entry another hook already swapped is never patched. And a failed detour is **not fatal**: `*origOut` falls back to the table entry, the hook stays table-only exactly as before, and the log says `TABLE-ONLY (<reason>)` rather than pretending.
    - **The Headhunter's hand-rolled supplemental detour is gone**, and had to be: it would now patch the trampoline `HookOneScript` just returned, detouring our own code instead of the game's.
    - **`HookOneScriptTable` still exists, for one reason.** `citrace nativetrace` runs a native detour beside a table hook on the same target and prints both counters; that comparison is what proved the blindness in the first place, and it only means anything while one side really is table-only. All 58 research-only hook installs use it. A contract test fails if it becomes reachable from the player build.
    - **Expect real behaviour change.** These multipliers and filters now apply on paths where they previously, silently, did not — so effective drop rates, stat scaling and relic filtering can differ from the previous build even with identical settings. That is the bug being fixed, but it is not a no-op.
    - **Enforced by** `tests/test_release_hook_contract.py`: `test_gameplay_hooks_intercept_direct_native_calls`, `test_native_detour_is_installed_once_and_only_on_the_real_target`, `test_hook_bodies_call_through_the_trampoline`, `test_research_hooks_stay_table_only`.

13. **RESOLVED 2026-09-12 — a permission consumed during step events cannot be validated at `EVENT_FRAME`:**
    - **What it was:** the map-reveal pack window's "lie about distance" permission was invalidated in `OnFrame` when the zone changed. `EVENT_FRAME` is dispatched from `HkPresent` (see `yytoolkit-modified/source/YYTK/Hooks.cpp`) — the **end** of the frame — while the creators that consume the permission run their step events earlier in the same frame. So the first distance call in a newly-entered zone still received the previous zone's permission, and the window closed only afterwards. That first call is exactly the one that leaves a spawner inert. Reported by origin's review with a production-class reproduction: `new_room_before_present window=900 wants=1 creator_ready=0 distance=0`.
    - **Why more tracking at `OnFrame` would not have fixed it:** the problem is ordering, not information. A render-time check can make no guarantee about a step-time consumer.
    - **The fix:** the authorization moved to the consumer and to the thing that actually decides the outcome. The damage is specific — answering 0 to a creator that has not finished initialising makes it take its spawn branch once, early, and come out inert — and that is a property of *the creator in hand*, not of the zone. `Hook_distance_to_object` now asks the creator (`MayPopulate` → `CreatorIsReady`, a real `enemyCreatorTimer`) at the moment it would change the result. A stale window becomes a performance question rather than a correctness one, and a *ready* creator in a new zone is still served, so the pass keeps working across a transition instead of failing closed. The same guard covers the Beacon's lie — the spawner comes out inert whichever feature answered — with its wake radius and continuous behaviour otherwise unchanged.
    - **Two related gaps, same report:** the per-frame check compared only the room key, so a replaced or removed minimap with an unchanged room key kept the window alive; it now compares the full identity (room + minimap instance + grid). And `TryOpenSpawnWindow` stored `INT64_MIN` when the room was unreadable and opened anyway, so every later failed read compared *equal* to it — "unreadable closes the window" only held when the window had been opened with a valid key. `ReadIdentity` now fails as a unit and a window is never opened against an identity that could not be read.
    - **The testing lesson, which is the durable part:** the source-string assertions passed the entire time this was broken. `tests/test_map_reveal_behavior.py` compiles the real class and the real hook and calls the hook *before* the next `OnFrame`. Every scenario was verified to fail against the code it describes before being relied on — reverting the authorization to the countdown alone reproduces `got=0 want=2500` on exactly the cases reported. One of those controls also caught a bad control: removing the hook's standalone readiness guard changed nothing, because `MayPopulate` checks readiness too, so that guard got its own Beacon scenario rather than remaining a line no test could fail without.

---

## Maintenance Triggers

- **Game Executable Updates:** When a new Season 10 patch releases, verify that spawner object names, GML function names, and `LoadDrops` drop family indices remain valid. The player build contains **no raw game addresses** to re-verify (Known Limitations item 11) — everything resolves by name or off a YYToolkit struct — so a new build should surface as named lookups failing, not as a crash. The dev-only `kCiCallMethodFnRva` does need re-verifying before anyone runs `citrace collect confirm native`; `citrace dispatchdump` / `citrace symdump` in the research build are the tools for re-locating it.
- **YYToolkit Header / Binary Sync:** Any rebuild of `YYToolkit.dll` requires recompiling `BloodPactPlugin` against matching headers in `plugin_build\include\` to prevent vtable mismatch crashes. Because the plugin now reads `CScriptRef` directly (under `/DYYTK_DEFINE_INTERNAL=1`), a header update also has to keep those layouts truthful — the headers' own `static_assert(sizeof(YYObjectBase) == 0x88)` is the compile-time check, and `petquest stat`'s `REFUSED (structural)` line is the runtime one.
- **Dependency Upgrades:** Check `yytoolkit-modified/NOTICE.md` if updating upstream YYToolkit; the custom disk cache and `ExecuteIt` hook disablement must be preserved.

---

## Source Documents & Evidence References
- Submodule Readme: `../../../ForgePact/README.md`
- Plugin Build Specifications: `../../../ForgePact/plugin/BUILD.md`
- Plugin Build Script: `../../../ForgePact/plugin_build/build.bat`
- Release Packaging Script: `../../../ForgePact/build_release.py`
- Modified YYToolkit Notice: `../../../ForgePact/yytoolkit-modified/NOTICE.md`
- Credits & License Notices: `../../../ForgePact/CREDITS.md`
- Season 10 Special Content Notes: `../../../ForgePact/docs/S10-special-content-notes.md`
- Dungeon Key & Drop Research: `../../../ForgePact/docs/dungeon-key-research.md`
- Angelic Drop Research: `../../../ForgePact/docs/angelic-drop-research.md`
- Satanic Zone Mods Research: `../../../ForgePact/docs/satanic-zone-mods-research.md`
- Map Reveal Research (why a revealed map had no monsters, and the spawner regression): `../../../ForgePact/docs/map-reveal-research.md`
- Pet Quest Collector (active plan + findings log): `../../../ForgePact/docs/pet-quest-collector-plan-c-direct-invocation.md`, `../../../ForgePact/docs/pet-quest-collector-c-research.md`
- Menu Pause (planned, **not recommended** - read §0 before proposing anything in this class): `../../../ForgePact/docs/menu-pause-plan.md`
- Satanic Zone SDK Data (shared, not ForgePact-specific): `../../../hs-game-sdk/curated/satanic_zone.json`
- Live Plugin IPC Driver: `../../../ForgePact/tools/ipc.ps1` (send a command to the running game, print only the reply)
- Ghidra Symbol Importer: `../../../ForgePact/tools/ghidra/ImportSymbols.java` (name the stripped game binary from its own script table)
- Out-of-Process Freeze Probe: `../../../tools/freeze_probe.ps1` (toolkit root, not ForgePact-specific)
- Release Notes: `../../../ForgePact/release-notes-v*.md` (one per not-yet-published version, deleted once published; preferred source for every version bump, see Representative Change Workflow §6)
- Tag & Release-Notes Composition Tool: `../../../ForgePact/tools/forgepact_tag.py` (plans a tag, composes a draft release body from whatever notes files exist, lists the notes a published version made redundant)
- Notes Cleanup Workflow: `../../../ForgePact/.github/workflows/forgepact-notes-cleanup.yml` (deletes a published release's notes files from `main`)
- Tag Workflow: `../../../ForgePact/.github/workflows/forgepact-tag.yml` (see "Tagging a release (forgepact-tag.yml)" above)
- Build Workflow: `../../../ForgePact/.github/workflows/forgepact-release.yml` (see "The build half (forgepact-release.yml)" above)
- Toolchain Pins & Fetcher: `../../../ForgePact/tools/toolchain-pins.json`, `../../../ForgePact/tools/fetch_toolchain.py` (all-or-nothing, SHA-256-verified headers/binaries)
- Release CI Helpers: `../../../ForgePact/tools/release_ci.py` (tag normalisation, the `build.bat` compile-line contract, and zip packaging — `tag`, `compile-line`, `package` subcommands)
