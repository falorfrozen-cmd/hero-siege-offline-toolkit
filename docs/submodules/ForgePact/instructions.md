# ForgePact Module Development Guide

## Module Overview & Metadata
- **Module Name:** ForgePact (Hero Siege Season 10 Offline Mod Panel & BloodPactPlugin)
- **Submodule Path:** `ForgePact`
- **Reviewed Git Revision (upstream, `origin`):** `2751679` (Tag: `v1.3.16`, Branch: `main`) — `falorfrozen-cmd/ForgePact`.
- **Revision Date:** `2026-09-10 09:21:05 +0300`
- **Commit Message:** `Prepare ForgePact 1.3.16 Headhunter release` — includes upstream's independent fix for the `VALUE_REF` player-resolution bug class in the Headhunter kill/steal path (`HhResolveInstance`, commits `7743a99`/`4ae4e30`), the same bug class described below.
- **Fork & Branch:** This guide additionally tracks work rebased onto that revision and pushed to `fork` (`S-Borkowski/ForgePact`) as **`release/v1.3.17`** — the version is 1.3.17, not 1.3.16, precisely because upstream had already shipped 1.3.16 by the time this branch was rebased onto it. See `release-notes-v1.3.17.md`. The branch has since grown a second release, **1.3.18** (`release-notes-v1.3.18.md`: the map-reveal pack pass and the Pet Quest Collector); the branch name is kept as-is because the open PR to origin tracks it.
- **Source Availability:** Full application source is present (Python control panel `src/forgepact.py`, C++20 native mod plugin `plugin/ModuleMain.cpp`, modified YYToolkit patches `yytoolkit-modified/`, build scripts `plugin_build/build.bat` and `build_release.py`, Python contract tests `tests/`, and reverse-engineering research notes `docs/`).
- **CI / Pipeline Availability:** **No build or test pipeline.** Verification is still conducted locally via the Python unittest suites and static build audits — nothing runs the tests on a push. Three workflows do exist in `.github/workflows/`, none of which build or test: `notify-hub.yml` and `notify-hub-release.yml` fire a `repository_dispatch` at the hub so its recorded submodule pointer and catalog refresh (see `docs/hub/design.md`, "Tool notifications"), and `ai-review.yml` runs an opt-in AI code review on a pull request. Review is requested, never automatic — add the `ai-review` label or comment `@claude review` on the pull request. It needs the `CLAUDE_CODE_OAUTH_TOKEN` repository secret, which comes from `claude setup-token` and authenticates against a Claude subscription rather than a separately-billed API key.
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
  - `test_relic_filter_contract.py`: Validates the relic drop pool filter, orb pickup radius mod, build-order packaging guard, player-resolution against `VALUE_REF`, the stall watchdog's presence/ordering, and the Map Reveal / Headhunter / Tyrant's Crown / Beacon panel relocation (29 tests, covering everything fixed 2026-09-09/10).
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
|   - Reads & clears bp_ipc/cmd.txt every 6 frames                                      |
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
6. **Write Release Notes (REQUIRED — `release-notes-vX.Y.Z.md`):**
   - Every version that ships gets a `release-notes-vX.Y.Z.md` file at the ForgePact repo root (`v1.3.1` through `v1.3.15` are the existing precedent — do not skip this for a version bump, however small). Not optional: a version with player-visible changes and no release notes file is an incomplete change.
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
- **C++ Compiler:** Microsoft Visual C++ (MSVC) from Visual Studio 2022 / Build Tools supporting `/std:c++20`.
- **YYToolkit Headers:** YYToolkit C++ headers (`YYToolkit/`, `Aurie/`, `FunctionWrapper/`, and `YYTK_Shared_Types.cpp`) located in `plugin_build/include/`.
- **hs-game-sdk:** required by **both** builds, not just the plugin. `build.bat` compiles against `hs-game-sdk/cpp/include` (`/I ..\..\hs-game-sdk\cpp\include`), and since 2026-09-14 `build_release.py` also puts `hs-game-sdk/python` on PyInstaller's analysis path — the panel imports `hs_game_sdk` for the Satanic Zone buff/debuff pool, and a package built without it ships that section empty. Building from inside a full toolkit checkout (ForgePact sits next to `hs-game-sdk/`) needs no extra setup; building ForgePact standalone means checking the hub out alongside it.
- **Python Packages (Optional / Packaging):**
  - `pyinstaller` (required for running `build_release.py`).
  - `pywebview` (optional; if installed, panel launches in a native desktop window, otherwise falls back to the default web browser).

---

## Command Reference

| Command | Working Directory | Shell / Platform | Prerequisites | Expected Result | Side Effects | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `py src/forgepact.py` | `ForgePact/` | PowerShell / CMD | Python 3.10+ | Launches local control panel HTTP server (`http://127.0.0.1:8766`). | Opens web browser / desktop window; watches for game process | Verified |
| `py -m unittest discover -s tests -v` | `ForgePact/` | PowerShell / CMD | Python 3.10+ | Executes all 188 Python contract tests (including the native behavior harnesses, which skip without a C++ toolchain). | Read-only test execution; all tests pass | Verified |
| `plugin_build\build.bat` / `plugin_build\build.bat release` | `ForgePact/` | CMD / PowerShell (Windows x64) | MSVC v143+ (VS 2022), YYToolkit headers in `plugin_build\include\` | Compiles `BloodPactPlugin_ship.dll` with `/DFORGEPACT_RELEASE`. Equivalent commands - `build.bat` only special-cases `dev`; anything else (including no argument) takes this branch. | Generates `plugin_build\BloodPactPlugin_ship.dll` and `obj_ship\` | Verified 2026-09-10 |
| `plugin_build\build.bat dev` | `ForgePact/` | CMD / PowerShell (Windows x64) | MSVC v143+ (VS 2022), YYToolkit headers in `plugin_build\include\` | Compiles `BloodPactPlugin_rel.dll` (research build with inspection commands, and `satmods` diagnostics). | Generates `plugin_build\BloodPactPlugin_rel.dll` and `obj_dev\` | Verified 2026-09-10 |
| `py build_release.py` | `ForgePact/` | PowerShell / CMD | PyInstaller installed, matching `BloodPactPlugin_ship.dll` | Builds complete release bundle in `dist/ForgePact/`. | Terminates existing `ForgePact.exe` processes; generates onefile executable | Inspected |

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
  - `orbpickup 10` / `orbpickup 0` / `orbpickup stat`: Widens the experience / magic-find globe pickup radius by 10x. `FrameCallback` enumerates the globe instances each frame and pulls any inside the widened radius toward the player at a constant `kGlobePullSpeed` (6 px/frame — tuned down from an accelerating ramp per user feedback 2026-09-10, which snapped the last stretch in a single frame and read as an unnatural teleport); the game's own pickup logic then fires normally once close enough. `orbpickup stat` (also printed when the mod is switched off) reads as a decision tree: `seen=0` while standing next to globes means the object indices are wrong, `noplayer>0` means the player never resolved, and only `outofreach` means the radius is too small — `nearest=` says by how much.
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
   - A multi-second freeze on the character screen was attributed twice to the wrong cause. `ModuleMain.cpp` now carries a stall watchdog in **every** build: a background thread notices when `FrameCallback` stops ticking for 3 s, suspends the frame thread just long enough to read its instruction pointer, and appends `STALL <ms> - frame thread at <module>+<rva>` to `bp_ipc/out.txt`, plus disk bytes and free RAM across the stall. That separates "stuck in BloodPactPlugin" from "stuck in the game" and "machine-wide thrashing" from "waiting on the GPU", with no debugger.
   - The frame thread is resumed **before** any allocation or formatting. Suspending a thread and then allocating is how this class of tool deadlocks on a heap/CRT/loader lock the stalled thread is holding; keep that ordering if you touch it.
   - **Measured 2026-09-09, character-select freeze (up to 85 s):** no sample landed in `BloodPactPlugin.dll`. The frame thread was blocked in `ZwWaitForSingleObject`, `ZwQuerySystemInformation`, `NtDxgkSubmitPresentToHwQueue` and `NtGdiDdDDIGetDeviceState` — kernel waits and GPU present/device-state calls — with no display-driver timeout (event 4101) logged. Resolve such addresses by parsing the export table of the named DLL and taking the nearest preceding export; the consistent `+0x14` offset is the syscall stub's return address.
   - **CONCLUDED — the freeze is not ForgePact.** A control run with `BloodPactPlugin.dll` removed from `mods/aurie/` (Aurie module list: YYToolkit + the game only) froze on the same screen. The same run also still produced the four `Unable to find any instance for object index ...` entries in `YYToolkit.log`, with identical indices and stacks, confirming those are game/YYToolkit noise and not caused by the plugin. Removing the plugin also removes the watchdog, so further measurement needs the out-of-process probe below.
   - **Measured 2026-09-10, with I/O and memory attached to each stall:** two stalls of ~65 s each showed **0 KB and 1 KB** of game disk reads, and free RAM *rising* by 1.1 GB and 843 MB respectively; sampled instruction pointers were `ZwWaitForSingleObject`, `NtGdiDdDDIGetDeviceState` and `ZwFreeVirtualMemory`. So the freeze is neither disk/anti-virus nor memory pressure — the process is blocked releasing memory and querying GPU device state. Remaining suspects are the display driver / GPU resource teardown, not the game's asset loading and not ForgePact.
   - **Probe for freezes that are not ours:** `tools/freeze_probe.ps1` (repo root) samples the game from outside — `Process.Responding` to bracket the freeze exactly, plus the game's disk I/O, free RAM and machine-wide CPU busy/idle, ranking processes once per freeze. Its verdict line separates *the machine is thrashing* (AV / paging / disk) from *the game is waiting on the GPU*. Note that per-process CPU via `TotalProcessorTime` or `Get-Counter` costs 1.5–6 s per sweep on a normal machine, which is why the continuous loop uses `GetSystemTimes`/`GetProcessIoCounters` instead.
7. **`instance_find` returns a REFERENCE, not a number (this broke every player-gated feature):**
   - **Measured 2026-09-10.** `HhResolveLocalPlayer`'s fallback accepted only `VALUE_REAL`/`VALUE_INT32`/`VALUE_INT64` from `instance_find(Player_obj, 0)`. This runner returns `VALUE_REF` (kind 15), so the fallback **always** failed, and with `GetMyPlayer` also returning a non-`VALUE_OBJECT` value the whole resolver returned false on every call. Everything gated on the local player then silently did nothing: `orbpickup` logged `seen=176993 noplayer=176993`, the relic filter never armed, and the Headhunter head labels reported "local player not found".
   - An instance reference is passed straight through — `variable_instance_get` accepts it. `HhUsableInstance()` now validates a candidate by *reading a variable from it*, which is what every caller does next, rather than trusting a kind tag. `orbpickup stat` reports `player via GetMyPlayer` / `instance_find(Player_obj)` / `none` so this can never fail silently again.
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
- Release Notes: `../../../ForgePact/release-notes-v*.md` (one per shipped version, v1.3.1 onward; required for every version bump, see Representative Change Workflow)
