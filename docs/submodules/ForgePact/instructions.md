# ForgePact Module Development Guide

## Module Overview & Metadata
- **Module Name:** ForgePact (Hero Siege Season 10 Offline Mod Panel & BloodPactPlugin)
- **Submodule Path:** `ForgePact`
- **Reviewed Git Revision (upstream, `origin`):** `2751679` (Tag: `v1.3.16`, Branch: `main`) — `falorfrozen-cmd/ForgePact`.
- **Revision Date:** `2026-09-10 09:21:05 +0300`
- **Commit Message:** `Prepare ForgePact 1.3.16 Headhunter release` — includes upstream's independent fix for the `VALUE_REF` player-resolution bug class in the Headhunter kill/steal path (`HhResolveInstance`, commits `7743a99`/`4ae4e30`), the same bug class described below.
- **Fork & Branch:** This guide additionally tracks work rebased onto that revision and pushed to `fork` (`S-Borkowski/ForgePact`) as **`release/v1.3.17`** — the version is 1.3.17, not 1.3.16, precisely because upstream had already shipped 1.3.16 by the time this branch was rebased onto it. See `release-notes-v1.3.17.md`. The branch has since grown a second release, **1.3.18** (`release-notes-v1.3.18.md`: the map-reveal pack pass and the Pet Quest Collector); the branch name is kept as-is because the open PR to origin tracks it.
- **Source Availability:** Full application source is present (Python control panel `src/forgepact.py`, C++20 native mod plugin `plugin/ModuleMain.cpp`, build scripts `plugin_build/build.bat` and `build_release.py`, Python contract tests `tests/`, and reverse-engineering research notes `docs/`). **The one exception is the distributed `YYToolkit.dll`:** the source of truth for the toolkit's modified YYToolkit is the hub's patch series, [`third_party/yytoolkit/`](../../../third_party/yytoolkit/README.md), not this repository. The pull request that moved this repository's pin to a build of that series and replaced `yytoolkit-modified/`'s two whole-file copies with a pointer at it (`NOTICE.md` plus `YYToolkit-BUILD-INFO.json`) has merged to `origin` (see the pin table under "The build half"), but **no ForgePact release has shipped it yet** — the hub library release its pin names is itself published; a tool release is a separate, still-outstanding step (see the pin table's provenance note for the distinction).
- **CI / Pipeline Availability:** `notify-hub.yml` (push to `main`, bumps the hub's submodule pointer), `notify-hub-release.yml` (fires on a published release, skips prereleases), `forgepact-notes-cleanup.yml` (fires on a published release, skips prereleases; deletes the `release-notes-v*.md` files at or below that version from `main`), `forgepact-tag.yml` (`workflow_dispatch`, tags a release, leaves a draft, and dispatches the build) and `forgepact-release.yml` (`workflow_dispatch` against `main` with a `tag` input; fetches the pinned toolchain, compiles and packages the tagged tree, and uploads the zip to that tag's draft — see "Tagging a release (forgepact-tag.yml)" below, "The build half (forgepact-release.yml)"). Verification is otherwise conducted locally via Python unittest test suites and static build audits.
- **Purpose & Scope:** Standalone offline control panel and native runtime hook plugin providing runtime modifiers for Hero Siege single-player sessions. Controls monster density, special content spawns (Rift Portals, Battlefields, Cursed Orbs, Chaos Tower, Shadow Realm, etc.), drop rate multipliers and gated drop families (Keys, Relics, Angelic/Unholy uniques), gameplay mods (relic drop pool filter excluding maxed 10/10 relics, orb pickup radius, pet-driven quest item collection), player/combat stat scaling, full map reveal (fog, plus an optional pass that makes each new zone's spawners create their packs on arrival so monsters appear on the revealed map), and custom forge mechanics (Headhunter, Tyrant's Crown, Beacon, Item Editor base stat export) without permanently altering save files or the base game executable. Integrated with `hs-game-sdk`.
- **Fork Branch vs. This Guide:** `release/v1.3.17` (`fork`) carries the Mods tab (relic filter, orb pickup, the Headhunter/Tyrant's Crown/Beacon/Map Reveal relocation), the build-order packaging guard, the stall watchdog, the `SafeF()` crash guard, and a second, complementary `VALUE_REF` player-resolution fix (`HhUsableInstance`, used by orb pickup and the relic filter's `HhResolveLocalPlayer` calls — distinct from upstream's `HhResolveInstance`, which fixed the same bug class for the Headhunter kill/steal path only). All covered by `tests/test_relic_filter_contract.py` (updated to match the merge) and documented in Known Limitations items 4-9 below; none are optional cleanup, all were needed to reach a working build.

---

## Architecture & Repository Map

### Repository Layout
- `src/`: Python application frontend and control panel runtime.
  - `forgepact.py`: Single-file local web/desktop application (`http://127.0.0.1:8766`). Manages port selection, configuration persistence (`%LOCALAPPDATA%\Hero_Siege\forgepact.json`), background game process detection / auto-apply watcher, PE binary patching / backup / restoration via `AuriePatcher.exe`, and file-based IPC dispatch to `bp_ipc/cmd.txt`.
  - `offline_launcher.py`: The HS Offline Launcher engine embedded in ForgePact (MIT; `UPSTREAM_REVISION` pins the HS-Offline-Launcher commit its audited helpers came from, and `UPSTREAM_DEFINITIONS` lists them). It owns the Win32 process snapshot (`processes`), the EAC service query (`eac_service_status`), PE validation (`validate_game`, `_exe_facts`), the Steam runtime lookup, the safety gate (`launch_safety_blocker`) and the single launch lock. The standalone UI, config discovery and polling loop are deliberately absent — the caller supplies the executable path. **Importing this module starts nothing**, which `tests/test_offline_launcher.py::test_source_import_needs_no_separate_launcher_and_starts_nothing` pins.

    The superproject's `tools/hs_drive_mcp/launcher_bridge.py` **imports this file by path** — it never copies or modifies it — and the superproject's `tests/test_hs_drive_mcp_engine_bridge.py` pins the names it calls as `ENGINE_SYMBOLS`, asserts the import still spawns no process and starts no thread, and asserts a checkout without this file refuses by name rather than raising. So a rename here fails that suite rather than surfacing at a tool call: when changing a public name in `offline_launcher.py`, update `ENGINE_SYMBOLS` in the same change. `docs/tools/hs-drive-mcp.md` describes the server.
- `plugin/`: Native GameMaker mod plugin implementation.
  - `ModuleMain.cpp`: C++20 dynamic library source for `BloodPactPlugin`. Implements Aurie module lifecycle (`ModuleInitialize`), hooks GameMaker engine routines via YYToolkit, manages frame event callbacks (`EVENT_FRAME`), polls commands from `bp_ipc/cmd.txt`, logs responses to `bp_ipc/out.txt`, applies throttled density/spawn overrides, manipulates drop tables and LoadDrops gates, projects HUD head labels, and exports live item statistics to `bp_ipc/itemstats.json`.
  - `BUILD.md`: Build requirements, compilation instructions, and differences between shipping (`/DFORGEPACT_RELEASE`) and research builds.
  - `include/ForgePact/AutoProspectMod.hpp`: The auto-prospect decision core (issue #9, Stage B) - when an insert into the ProspectGrid counts, when to invoke, when to refuse and what to say, plus the recorded shape's names (`activationFunc`, `activationArgs`, `"ProspectGrid"`). Stage C adds the move pass: when to ask for it (`MoveMaterials`, once per landed insert, just before the invoke), which cells (those the adapter flagged as materials - the core has no item-type value), and what each cell's report means (`ClassifyMove`). Game-independent (names no runtime interface), so `tests/auto_prospect_harness.cpp` compiles it whole; `ModuleMain.cpp`'s `Hook_AutoProspectInsert`/`AutoProspectTick`/`ApMovePass` are the only code that touches the game for it.
  - `include/ForgePact/RestartAnytimeMod.hpp`: The "Restart zone at any time" decision core (issue #8, `restartanytime`) - the site script (`UiSetFocus`), the identifying member and value (`uiNodeCallstack` = `PauseRestart`), the gate member and its ready value (`manualDisable` = false), `RestartAnytimeModel::Decide` (Pass or Write) and the armed/pending/blind flags and four counters. Game-independent: no `RValue`, no builtin call.
- `plugin_build/`: Plugin compiler script and build workspace.
  - `build.bat`: MSVC x64 batch script compiling `plugin/ModuleMain.cpp` into `BloodPactPlugin_ship.dll` (player build) or `BloodPactPlugin_rel.dll` (research build).
- `modfiles_shipped/`: Shipped binaries deployed to the game's `bin/` directory upon mod installation.
  - `AurieCore.dll`: Aurie Framework core loader binary (unmodified AGPL-3.0).
  - `AuriePatcher.exe`: Aurie PE import/bootstrap patcher (unmodified AGPL-3.0).
  - `YYToolkit.dll`: GameMaker runtime interface library, a modified build of YYToolkit v4.0.1 (AGPL-3.0). `origin`'s pin now names a build of the hub's patch series in `third_party/yytoolkit/` (sha256 `51a393d7…`, see the pin table below), merged via the pull request that also rewrote `yytoolkit-modified/`. The version this replaces was SHA-256 `bb113eef…` (904,192 bytes); its notice listed two changes — a runner-interface disk cache and the `ExecuteIt` hook left uninstalled — but the binary contained more than that, and the source it was built from was not kept; see the provenance row in the pin table below. No ForgePact release has shipped the new pin yet, so this is still the DLL a player's installed copy carries.
  - `BloodPactPlugin.dll`: Pre-compiled release build of the mod plugin.
  - `HSOfflineTrackerProducer.dll` (Optional): Read-only telemetry sensor for the companion HS Offline Tracker tool.
- `yytoolkit-modified/`: On `origin`, an AGPL-3.0 `NOTICE.md` pointing at the hub's [`third_party/yytoolkit/`](../../../third_party/yytoolkit/README.md) plus a `YYToolkit-BUILD-INFO.json` — the pull request that rewrote this directory to that pointer has merged, replacing the two whole-file copies it used to hold. **Not the complete source for the DLL, and not where a change to YYToolkit is made** — that is the hub's patch series. No ForgePact release has shipped the new pin yet, so a player's installed copy still carries the earlier DLL (SHA-256 `bb113eef…`) and the notice that accompanied it, which was incomplete.
  - `NOTICE.md`: Now a rationale and pointer at the hub series, not a rebuild recipe. The notice it replaced described a rebuild recipe for the two files below that said everything else was unmodified upstream, which the binary's own strings contradicted; its recipe (`MSVC toolset 14.50`, `cl /std:c++latest /MD /LD`) did not match the DLL's PE header (linker 14.51), and it omitted `/O2` although the DLL was **likely** built with it: a plain `cl /O2` build of the documented tree is 894,976 bytes against the DLL's 904,192, one without `/O2` is 1,180,160, and the DLL has pooled strings and no `.rsrc` section, unlike a build through upstream's `vcxproj`.
  - The two whole-file copies this directory used to hold, `Generic-RunnerInterfaceNew.cpp` and `source/YYTK/Hooks.cpp`, are gone from `origin`'s tree; they accompanied the previous, still-distributed DLL. `Generic-RunnerInterfaceNew.cpp` added a disk cache (`<exe>.yytkcache`) and a density-sorted `.text` page pre-filter so the RunnerInterface search did not disassemble all of `.text` on every launch — the pre-filter was in the file but never listed in `NOTICE.md`. On a cache hit that version planted the mid-function hook at the address read from the file, validating nothing but the executable's size — and `src/forgepact.py`'s `ensure_ri_cache` pre-seeded that file from a table of hand-measured RVAs keyed by exe size; that table has since been deleted (see Known Limitations). `source/YYTK/Hooks.cpp` left the `ExecuteIt` hook (`EVENT_OBJECT_CALL`) uninstalled; `EVENT_FRAME` via `HkPresent` was unaffected. The reason `NOTICE.md` gave — the hook corrupting instance references and producing `Unable to find any instance for object index` — was contradicted by `docs/S10-special-content-notes.md`, which records the same error with the hook removed. What stood: no plugin in this toolkit consumes `EVENT_OBJECT_CALL`, and project notes record the per-event hook crash-looping on Season 10 (not re-measured since). Both behaviours are now reproduced by the hub's patch series instead — `0001` keeps the exe-size hint but always takes the hook address from the scan, and `0003` makes the `ExecuteIt`-off state a named build switch, logs it once, and refuses the registration with `AURIE_UNAVAILABLE` instead of accepting a callback that can never fire.
- `tests/`: Automated Python contract test suites validating plugin source invariants and panel logic without requiring a running game instance.
  - `test_density_reentry_contract.py`: Validates spawner object name lookups, stable spatial identity keys, and density placement guards.
  - `test_enemy_speed_contract.py`: Verifies enemy speed multipliers, Chaos Tower scoping, and release command accessibility.
  - `test_kill_drop_contract.py`: Pins where the angelic and signature kill drops run inside `Hook_EnemyDestroyKillProc` - both before the original kill proc, handed the live enemy, inside a catch-all, and nothing naming `S` after the trampoline (Known Limitations item 14). The behaviour itself is exercised by the drop scenarios in `test_headhunter_dispatch.py` + `headhunter_dispatch_harness.cpp`, which compile the real drop functions and skip without a C++ toolchain. Since #63 (Known Limitations item 21) that dispatch test's kill-drop scenarios split into `test_signature_drop_baseline` (the seven kill-order scenarios listed in Known Limitations item 14 - must still pass against the pre-#63 source) and `test_signature_drop_target` (`signature_pool_append`, `angelic_pick_crown_spawns_signature`, `angelic_pick_belt_spawns_signature`, `signature_equal_share`, `sigdrop_force_belt`, `sigdrop_force_no_alternation` - the pool-membership behaviour, each shown failing against the pre-#63 source).
  - `test_signature_drop_contract.py`: Source contract for Headhunter/Tyrant's Crown joining the Angelic pool (#63) - pins that the six standalone-die identifiers (`kSigDropAngelicPct`, `g_SigDropPct`, `g_SigDropAncientPct`, `g_SigDropPity`, `g_SigDropSinceLast`, `g_SigDropNext`) are gone, that `BuildAngelicPool`'s body calls `AppendSignatureCandidates(`, that `AngelicDropOnKill`'s body calls `SpawnSignatureItem(`, and that the panel's `angelicCard` hint names both items. Honours `FORGEPACT_TEST_PLUGIN_SOURCE` like the dispatch test, so it fails against the pre-#63 source.
  - `test_forge_hash_contract.py`: Validates the Custom Forge's `itemDataHash` refresh chain (`RefreshItemHash`, with `+itemcheck`/`+method`/`+direct` split into named `HashRouteItemCheck`/`HashRouteMethod`/`HashRouteDirect` helpers and `+routine` kept inline in `RefreshItemHash` itself behind a `routineOnly` flag, so its `AddrIsExecutableInModule` guard stays where `test_release_hook_contract.py` pins it) - the SDK-constant fix for the stale `@anon@4638@` script name, `+direct`'s before/after hash compare and its `+direct-nohash` refusal, that the route helpers never touch the shared counters, that `hashprobe`'s single-route line leads with the `wrote=` verdict rather than the route's own (misleading, post-sentinel) return, that its no-write restore uses the raw original `RValue` rather than a reconstructed string, and that `hashprobe`/`forgehash stat` (both research-build only, per Known Limitations item 15) stay out of `kPlayerCommands` and out of a release build entirely.
  - `test_mod_backup.py`: Tests clean PE backup verification, build mismatch detection, stale backup archival, and atomic restore rollbacks.
  - `test_necro_balance_contract.py`: Validates Necromancer balance formulas, fail-closed runtime contracts, and panel visibility.
  - `test_map_reveal_contract.py`: Validates the map-reveal mod and its `map_reveal_packs` sub-toggle - defaults, `build_cmds` parent/child emission, the release-guarded `reveal stat`, and the guardrails that keep it from unlocking waypoints, writing the player's minimap options, or sweeping `isDiscovered`. Also pins the 2026-09-11 regression: the pack pass must wait for a creator to report a real `enemyCreatorTimer` before lying about distance, because firing during zone load leaves the spawners inert and the zone emptier than vanilla.
  - `test_map_reveal_behavior.py` + `map_reveal_harness.cpp`: **Behavioral** regression suite for the pack pass - compiles the real `MapRevealManager` and the real `Hook_distance_to_object` against controlled game-API responses and calls the hook at the point in the frame order where it matters (before the next `OnFrame`). Exists because the source-string assertions in `test_map_reveal_contract.py` passed throughout the period when the authorization was checked at the wrong point in the frame; see Known Limitations item 13. Skips without a C++ toolchain, like `test_headhunter_dispatch.py`.
  - `test_menu_probe_contract.py`: Pins the research stage of the character-select question - whether anything can drive the game's own main menu as far as a loaded character (`docs/character-select-research.md`; live session run 2026-09-21).
    - `menuprobe` is research-build only (the literal disappears from `strip_research_blocks`, header comment included), absent from `kPlayerCommands`, dispatched from `HandleMenuProbeCommand` as the third adjacent call after the Headhunter's and the prospect window's rather than a new top-level `else if` (C1061; the chain's length is pinned against `f5a3515`), and the literal occurs exactly once in `ModuleMain.cpp`.
    - The `event` and `script` subcommands check the literal token `confirm` - and print a usage line - before any `CallBuiltinEx`/`CallGameScriptEx`, each makes exactly one such call with no loop around it, and each prints the object, `nth`, instance `id`, position and the room index before *and* after, so a refusal, a no-op and a fault stay three outcomes.
    - `list` needs no token.
    - Instances are reached through `asset_get_index`, `instance_find` and `HhResolveInstance`; the new code contains no `Rva`, `GetModuleHandle`, `MmCreateHook` or `HookOneScript`, and `FrameCallback`'s own body mentions neither the verb nor any of its helpers (the verb still *runs* on that thread, inside `PollCommands()` like every other command - the header comment has to say so, and a test asserts it does).
    - `MpWhere` asks `instance_exists` before reading variables off a handle and prints one `<destroyed>` marker rather than three empty fields, so "this instance has no such variable" and "the call destroyed this instance" stay two outcomes.
    - The doc tests pin the headings, the CRLF encoding, every SDK name in the static search, the five rejected verbs, a `## Results` row per live step, the same-instrument enumeration control in steps 6 and 13 and in the `C-1.13` results row, and that `## Decision` is answered rather than `pending`.
    - Those last assertions required the literal `pending` until the live session ran on 2026-09-21, so that an invented finding could not be mistaken for a measured one before there was anything to measure; they were replaced rather than relaxed, and now pin the rule they were protecting - a candidate may be named in `finding:` only if its own `## Decision` line is labelled `works`, a candidate whose control failed is `unmeasured` and `unmeasured` is not a result, and the verdict is read as the bolded label after the dash rather than as a substring, because a bullet cites other steps' findings in its prose and matching anywhere reads a citation as a verdict.
  - `test_menu_layout_contract.py`: Pins `menulayout`, the read-only player command that lists every live instance of thirteen candidate menu objects with its window position (`docs/menu-layout-research.md`): `"menulayout"` is in `kPlayerCommands` and dispatched from `HandleMenuLayoutCommand`, called from `RunCommand` beside `HandleProspectCommand` (C1061), not a new `else if`; no `MenuLayout*` helper mentions a hook installer, `CallGameScriptEx`, `event_perform`, an `Rva`, `GetModuleHandle`, `instance_create`/`instance_destroy` or `variable_instance_set`, and `FrameCallback` mentions none of them; the candidate table is exactly the research doc's thirteen `GameObject` names, each an `hs-game-sdk` enumerator; the header, row and footer format strings (the hub's parse contract) in order; the window point read from `window_get_width`/`window_get_height` over `display_get_gui_width`/`display_get_gui_height` by name; the 200-row cap; `release-notes-v1.4.5.md` names the command; and the research doc's five headings and its four `## Decision` lines, which phase 0 filled on 2026-09-21. None may read `pending` now.
  - `test_prospect_window_behavior.py` + `prospect_window_harness.cpp`: **Behavioral** suite for the prospect window sizing core (ForgePact issue #9, research stage). Splices the real `plugin/include/ForgePact/ProspectWindowMod.hpp` in at `// PRODUCTION_PROSPECTWINDOW` - the header is game-independent by contract, so no runtime stub is needed. Baseline scenarios (`baseline/*`: off returns the vanilla size and applies to nothing) and target scenarios (`target/*`: scales by the declared factor, clamps to the declared cap, never shrinks, applies once per window instance through a bounded latch, refuses and counts a nonsense vanilla size, disabling clears the latch but keeps the counters, and the stat line names what was done). Each target scenario's observed failing line against a vanilla-returning stub is recorded in the harness. Skips without a C++ toolchain.
  - `test_auto_prospect_behavior.py` + `auto_prospect_harness.cpp`: **Behavioral** suite for the auto-prospect decision core (issue #9, Stage B).
    - Splices the real `plugin/include/ForgePact/AutoProspectMod.hpp` in at `// PRODUCTION_AUTOPROSPECT` - game-independent by contract, so no runtime stub.
    - Baseline scenarios (`baseline/*`: off by default, off never invokes whatever it is fed), target scenarios (`target/*`: one invoke per landed insert into the ProspectGrid; nothing for an insert elsewhere, a rearrangement, an insert made inside our own invoke or one pending on a replaced node; coalescing; the `grid-full`, `no-window`, `no-button`, `no-args` refusals; the settled count following a new node and a removal; a click-in whose cell was filled before its hook, in the same frame or an earlier one; nothing for moving a material or a refused item; `ran-no-effect` one frame later; each refusal reported once; the stat line; the player-log `first prospect` line once) and `adapter/*` scenarios (the recorded shape's names, and the measured Phase 1 session replayed).
    - Stage C adds `baseline/bag_off_never_moves` and `baseline/parent_off_never_moves`, and targets for the move pass: `bag` on by default and kept across the parent toggle; one pass before the invoke, naming material cells only; a pass only when an insert lands; the landed insert staying landed across a pass that empties cells; a refused move (`not-added`, `move-failed`, and a has-a-stack "no" - its own outcome in Stage C, `no-preferred-grid` since Stage D) leaving the material and named once; `vanished` and `cell-kept` turning the pass off for the session; and the player-log `first move to bag` line once.
    - Round 1 (after Phase 3 live on e63eed5 moved an inserted ore to the tab unprospected) adds `target/first_prospect_of_a_session_moves_nothing`, `target/ore_insert_moves_only_the_previous_batch`, `target/hand_placed_material_is_never_moved`, `target/batch_forgotten_on_a_new_node_or_the_parent_toggle`, `target/batch_forgotten_after_a_removal_or_an_unlanded_insert`, `target/a_batch_is_moved_at_most_once` and `target/success_with_an_unreadable_cell_turns_the_move_pass_off`, and re-seeds the round-0 move targets through a prospect that records the batch (`SeedBatch`).
    - Stage D (first-of-type materials, after the c27cdad re-run) adds `baseline/existing_stack_route_is_unchanged` and the targets `target/new_type_placed_and_cleared_counts_as_moved`, `target/new_type_without_a_preferred_grid_stays_and_is_logged_once`, `target/new_type_not_placed_stays_and_is_logged_once`, `target/new_type_vanished_or_kept_turns_the_move_pass_off` and `target/stat_line_names_the_new_type_route`, and the closing round adds `target/preferred_lookup_not_run_is_move_failed` (a lookup that never ran is `move-failed`, with a lookup that ran and named no grid as its `no-preferred-grid` negative control; its failing line is recorded against 20fc518), and PR prep adds `target/move_failed_names_the_step_that_failed` (each of the seven `move-failed` causes names its step in the line, one line for two different steps, `not-added`'s line unchanged as the control; failing line recorded against c229cb5); `Report()` gains the new-type route's parameters (`PlaceReport` for a named grid and a place), and the two Stage C targets that used a has-a-stack "no" as their refusal (`refused_move_leaves_the_material_and_is_logged_once`, `a_batch_is_moved_at_most_once`) now expect `no-preferred-grid`.
    - Each target's failing line is recorded in the harness - against a never-invoking stub for the first set, against the previous core for the insert-timing set, against the unchanged core shimmed with Stage C's names for the move-pass set, against the round-0 core (e63eed5) for the round-1 set, and against the c27cdad core shimmed inert with Stage D's names for the Stage D set.
    - Skips without a C++ toolchain.
  - `test_auto_prospect_contract.py`: Pins the auto-prospect adapter on comment-stripped source: the core header names no runtime interface; the hook goes in through `HookOneScript(SdkShortScriptName(...anon_15345...))` with both routes (`HookOneScript`'s `nativeOut`), once, from `FrameCallback` after setup, and a table-only install turns the mod off; the hook body runs the trampoline first, reads nothing while off and never invokes; the grid is identified by `object_index` plus a `uiNodeCallstack` naming `"ProspectGrid"`, the button by the window link plus an `activationFunc` whose `method_get_index` is the handler's; the invoke is in `AutoProspectTick` after everything it reads is re-found, with exactly the recorded shape by name (no `Rva`, `CScriptRef`, captured argument or research helper); nothing of the mod runs in `FrameCallback` while it is off; `autoprospect` is a player command and `autoprospect stat` research-only; refusals, a failed dispatch and the first prospect are logged once in the player build; the panel toggle defaults off and emits `autoprospect 1|0`; and the release notes, README and research doc record it.
    - Stage C: `test_material_identified_by_its_item_type_through_the_sdk` (`ApIsMaterial` compares `itemType` with `HeroSiege::Items::ItemType::Material`, no local constant, no fingerprint suffix, no item type in the core, identity read only when `NeedsMaterials()`), `test_move_uses_the_recorded_shape_by_name_only` (the four M7 scripts by SDK name through `script_execute` with the grid node as self and other, the recorded arguments, no research helper), `test_move_pass_runs_at_the_point_of_use_before_the_invoke` (`ApMovePass`, a second read and `Decide` in the same frame, then the invoke; the invoking flag held across the pass), `test_clear_only_after_success_on_the_same_fingerprint`, `test_bag_is_a_sub_option_of_autoprospect` (`autoprospect bag 1|0`, on by default, untouched by the parent toggle, nested in the panel), `test_move_refusals_and_vanished_are_logged_once`, `test_release_notes_and_docs_record_the_bag_move`, and (round 1) `test_move_set_is_the_recorded_batch_not_every_material` (the `d.moves` append is conditioned on `m_Batch` membership as well as `material`; `OnInvoked` records it from `after`; the first-sight, removal and `not-landed` branches empty it; `NeedsMaterials()` reads it; `ApReadCells` fills `printList`).
  - `test_prospect_window_contract.py`: Pins the research stage of the bigger prospect window (Stage C's M7 instrument too: `test_itemfp_resolves_the_item_through_the_games_own_lookup`, `test_stackmove_is_research_only_and_confirm_gated`, `test_stackmove_refuses_before_any_call`, `test_stackmove_clears_only_after_add_was_entered`, `test_stackmove_calls_by_name_only` and `test_stackmove_prints_item_type_and_verdict`; and Stage D's: `test_stackmove_new_type_route_by_name_only`, `test_stackmove_new_type_clears_only_on_a_success_signal`, `test_stackmove_clear_is_confirm_gated_and_research_only`, `test_probe_logs_the_return_value_of_every_logged_call` and `test_autoprospect_research_log_is_research_only` - each shown failing against c27cdad's source before the change): `prospectprobe` is research-build only, absent from `kPlayerCommands` (where `autoprospect` is the only prospect verb), and dispatched from `HandleProspectCommand` (not a new top-level `else if` - C1061);
    - no `prospectsize` command or window-sizing panel row exists (the human chose auto-prospect on insert instead);
    - of Stage B, `FrameCallback` carries only the enabled-gated auto-prospect block;
    - every target-table row is an `hs-game-sdk` constant whose runtime name appears in the research doc;
    - the resolver refuses an address outside `Hero_Siege.exe` before `MmCreateHook`;
    - `prospectprobe set` checks the object, the instance, the variable and the numeric kind before its one write and never gates on the instance kind;
    - `override` refuses a row that is not detoured, gates its write on the selector and prints `self`/`other`/arguments on the applied line;
    - `arm` takes a budget and label filters and `show` reports unlogged calls;
    - `FrameCallback` carries nothing of the instrument;
    - the core header names no runtime interface;
    - and the research doc keeps its hook-free steps first and pins the two sentences that decide H1/H2, plus the rule that H3 needs non-empty, fully logged R2/R4 and an override matched to the R4 call - matched with `@id` ignored and the grid observation recorded beside the verdict - and that `show` flags an unselected row that fired.
    - Phase 0b additions: `target_table_covers_every_sdk_closure_of_the_ui_objects` reads the SDK's `scripts.hpp` and fails, naming the missing constants, if any Create-event closure of the ten UI/prospect objects is not a row (so a regeneration fails a test, not a live session);
    - `grid_snapshot_is_hook_free_and_budgeted` (builtins only, the node found by `uiNodeCallstack`, taken only after the log budget admits the call and only with `watch` on, nothing in `FrameCallback`);
    - `watch_post_line_exists_and_is_gated_on_logged` (the detour runs `PpObserve`, the trampoline, then `PpAfter`);
    - `call_invokes_method_values_by_name_only` (`script_execute` through `CallBuiltinEx`, no `CScriptRef`/`MethodValueFunction`/address);
    - `resize_requires_via_and_reverts_when_the_builder_does_not_follow` (refusals before any write, `nodeGrid` measured over every row, both sizes restored in the same handler unless every row followed);
    - `resize_restore_never_exceeds_the_store` (the restore is capped per axis at what `nodeGrid` still covers and prints `restore unsafe` when that is below vanilla; a method that replaced the node prints `rebuilt`/`destroyed`);
    - `call_and_resize_prove_the_method_body_ran` (`script_execute` succeeding proves the dispatch, not the body: the closure's own detoured row is counted across the invoke and `invoked=yes|NO|unproven`, `self=` and `args=` ride on every outcome line; `resize` takes trailing numeric arguments);
    - `setat_requires_a_detoured_row_and_an_existing_variable`;
    - and the doc tests `research_doc_records_phase0a_as_instrument_failure`, `research_doc_closure_rows_have_a_positive_control` (L4: the four closures read live - `anon@1065/2806/3657/36159` - must print `detoured`; `detoured` proves resolution only, a count needs `invoked=yes`), `research_doc_pins_the_three_sentences` (the third: a `CHANGED` snapshot names the builder's extent, not the builder) and `research_doc_pins_the_resize_revert_rule` (a `reverted` counts toward H3 only with `invoked=yes` and the call shape L5 logged for the game's own call, else `not observed (call shape unknown)`; and only on a grow - GML's element assignment grows an array and never truncates it, so a shrink's `reverted` is `not observed (shrink only - an assignment-built store never truncates)`; L9 shrinks every method first, then grows every method whose shrink kept **and** every method whose shrink reverted with `invoked=yes` and an unchanged store, arms the method's row before each `resize` so the detour logs what it received, and voids every `resize` of the session if the closure-name matcher prints `invoked=unproven (no detoured row …)` for a detoured row; L5's "no `CHANGED`" needs a resolved `grid-post`).
    - `watch_post_line_exists_and_is_gated_on_logged` also pins that a failed read on either side prints `UNREADABLE`, never `same`, and that `none` on both sides prints `same (no node)`; `resize_restore_never_exceeds_the_store` also pins `size exceeds store` on `kept`/`rebuilt` and the `probe=shrink` note; `call_and_resize_refuse_while_a_rewrite_is_pending` pins that neither runs while an `override` or `setat` is pending, since one would fire inside the invoke and rewrite what the method received.
    - Phase 0c additions: `backing_captures_getter_returns_without_invoking` (the four profile/inventory getters are rows; every `PpBacking*` function is free of `CallGameScript`, `script_execute`, `callnum` and `call`/`resize`; the capture runs inside `PpAfter` on the value the trampoline returned, budgeted and never nested, serialises nothing and roots each kept value through a research global, while `backing dump` writes json only after a depth-capped walk; `backing` is off by default, `reset` turns it off and releases what it kept, and nothing reaches `FrameCallback` or the player build);
    - `idcheck_runs_a_positive_control_before_its_verdict` (on arrays the instrument builds itself, a kept reference must see a later write and the scanner must find the sentinel through it but not in a separate array - both before `nodeGrid` is touched, returning on failure - and `copy` needs a complete walk, else `scan incomplete`; a reference, method or pointer counts as unwalked, and a kept return of a profile getter (`GetProfileInventoryData`/`GetPlayerProfileObj`) holding the sentinel decides `reference-identical (via ...)`, a non-profile getter’s hit only a lead);
    - `idcheck_a_profile_getter_hit_from_one_call_only_is_a_lead` (a profile getter’s CLEAN hits - paths through no UI-looking field - must span `kPpBackingProfileCallsToDecide` (two) distinct calls to decide save-backed; each verdict literal is pinned to its own branch of the collapsed verdict body by slicing on `if (decisive) {`/`} else if (uiReached) {`/`} else {`, not just to text order; the decisive/uiReached selection block is pinned whole after comment-stripping and whitespace-collapsing, none of the five names it reads - the stash list, the threshold, `PpBackingIsProfileGetter` and the two call maps - may be redeclared, rebound or `#define`d (the maps are declared once, above it), and an in-file, in-memory mutation control proves the pin rejects 23 keyword-free restrictions that passed the earlier asserts, M24's first-stash wrap among them);
    - `idcheck_a_decisive_identity_through_a_ui_looking_field_is_a_lead` (`PpBackingUiLookingField` classifies a hit path’s struct-member names against `ui`/`window`/`node`/`panel`/`menu`, case-insensitive; a profile getter whose hits reach the two-call threshold only through such a field prints a `reached through a UI-looking field` lead instead of deciding save-backed, pinned in the doc’s § Instrument, C5, the gate’s Save-backed/Inconclusive bullets and the § Results row);
    - `idcheck_one_call_only_lead_names_every_profile_getter_that_hit` (the `one call only` lead names every profile getter whose kept returns held the sentinel, not just the first in stash order);
    - `idcheck_refuses_unless_a_kept_return_came_from_the_open_window` (window-self returns are kept with their `@id`, an unreadable id never matches, the open-window refusal comes before the one write, and the live procedure runs `idcheck` (C3) before C2b places any item);
    - `idcheck_never_reads_copy_after_a_window_return_was_dropped` (the first 8 window returns per getter are kept and never overwritten, the rest counted; the research global is set before the slot's value, call, `self` and `@id`; `idcheck` reads the dropped count before `copy`, prints it on the `kept returns from the open window` line and answers `not observed` while it is non-zero, and the doc's C5 and gate carry "no window return dropped");
    - `idcheck_names_each_incomplete_walk_and_only_profile_getters_decide` (each incomplete walk printed with its reason, identity through `GetProfileInventoryData`/`GetPlayerProfileObj` kept apart from a lead through the other two getters, and the doc says a top-level instance return counts against `copy`, a `K/N` shortfall is not copy evidence, and C5/the gate decide save-backed only through those two getters);
    - `structural_agreement_counts_only_non_empty_cells_and_is_a_lead` (only `nodeGrid`'s non-empty cells count, objects agree by identity, and the dump says agreement never picks a gate branch);
    - `idcheck_restores_the_cell_and_only_writes_an_empty_one` (exactly one sentinel write and one restore on the live row, the empty-cell check and the `no empty cell`/`never captured`/`no ProspectGrid node` refusals before the write, a write that `did not land` never read as a copy, the restore before the verdict);
    - `research_doc_records_phase0b_and_the_ghidra_reading` (the Phase 0b column filled, a Phase 0c column and its rows, the paraphrased Ghidra read, the `callnum` attempt as an instrument misuse, the fixed `Craft_Grid_Large_spr` background, the Phase 0c live procedure C1-C8 and the three `backing` commands after the hook-free reads);
    - `research_doc_states_the_decision_gate` (save-backed / not save-backed / inconclusive read in that order with structural agreement never a branch, what the instrument counts as unwalked, the stranded-item and `ValidateInventory` risks, the `prospect all` and auto-prospect alternatives with the leftover-material statements as claims to verify, and H2'');
    - and `research_doc_carries_no_decompiler_tokens` / `contract_tests_carry_no_decompiler_tokens`.
  - `test_pet_quest_collector_contract.py`: Validates the Pet Quest Collector — the panel toggle and its `build_cmds`/live dispatch, the target set (`Quest_Object_Parent_obj` descendants minus a static exclusion list, checked against `hs-game-sdk`'s real hierarchy so a future SDK change cannot silently widen it), and the invariants that keep the shipped collect honest: exactly one call shape and it is the measured one, the game's own `canPickup`/`lootType == 0` gates re-read per item rather than cached from selection, `other` = `Loot_Manager_obj` rather than the player (the static read guessed the player and was wrong), one item at a time with a cooldown, and no pet means no collecting. Also pins every `citrace` research command as release-guarded, absent from `kPlayerCommands`, and — for the mutating ones — behind the `confirm` gate that fails closed (56 tests; the largest suite).
  - `test_rarity_boss_exclusion_contract.py`: Validates that the Monster Rarity sliders (`g_RarRarePct`/`g_RarAncientPct` in `EnemyRaritySettings`'s hook) skip bosses before rolling. The signal is GameMaker's own object ancestry - `HeroSiege::Objects::IsDescendantOf` against `Enemy_Child_Boss_obj`, the ancestor hs-game-sdk's own parent-index table gives every named boss (Anubis, Damien, Cthulhu, the `Uber_*` variants) - checked against hs-game-sdk's own hierarchy so a future SDK regeneration that moves it fails a test rather than silently going blind, and pinned as *not* an HP threshold or a name substring. Also pins that the check runs before the die is rolled, that an ordinary rarity-1 monster's tier assignment is unchanged, that the skip counter stays out of the release build, and that Tyrant's Crown (a separate mechanic sharing the same hook) is untouched - this fix is scoped to the sliders only. Fixes a player report (v1.4.1, ForgePact 1.4.3): an Anubis boss reported going from ~500k to ~4.5M HP with 20% rare + 20% ancient set, because nothing checked whether the rarity-1 instance being rolled was a boss that already has its own scripted health and affixes.
  - `test_release_hook_contract.py`: Validates zero eager gameplay hooks in release builds, all-off pass-through behavior, and telemetry exclusions.
    - `ClosureNameContractTests` is the closure-name contract: every `anon@N@...` GameMaker closure the player build compiles (raw literal or `HeroSiege::Scripts::` constant) is parsed against hs-game-sdk's own `scripts.hpp` and must be a name the SDK still has, with a positive control on the research build's own literals and a synthetic negative control proving the check catches a stale name.
    - It also rejects ways of reaching an SDK constant the wrong way even when the name itself is fine: an unqualified `using namespace HeroSiege::Scripts`/alias, the same misuse one namespace level up (`using namespace HeroSiege;` or a namespace alias of the parent — `HeroSiege::Objects` and the other non-`Scripts` sub-namespaces stay unflagged, since they don't expose script names), a `HookOneScript`/`HookOneScriptTable` call given the constant's already-prefixed full value instead of going through `SdkShortScriptName`, and a full-name API (`CallGameScriptEx`/`GetNamedRoutinePointer`/`CallGameScript`/`HookRawNamedRoutine`) given the short form instead of the full one — each with its own negative-control case.
    - These misuse rules run over the research build too, not only what the player build compiles, because a doubled-prefix research-only `HookOneScriptTable` call (one of the 58 research-only installs) would never resolve and its `citrace nativetrace` table counter would read a false zero next to the native counter — indistinguishable from the blindness that comparison exists to detect.
    - A call-shape regex still can't see a leading `::`, a `using`-declaration, or a name reached through a variable or a data-table initializer (`HookOneScriptTable(k.ad, ...)`, `CINAT_ENTRY(...)`); those stay out of scope.
    - `test_routine_fallback_validates_the_pointer_before_calling_it` separately pins that `RefreshItemHash`'s function-pointer fallback validates the address with `AddrIsExecutableInModule` before calling it — the call must sit inside the guard's braced then-block in comment-stripped source, not merely come after it textually.
  - `test_player_hook_names_in_sdk.py`: A companion to `ClosureNameContractTests` for plain (non-closure) script names: every string literal the player build passes to `HookOneScript`/`HookOneScriptTable`/`InstallScriptHook`, plus every `"gml_Script_"`-prefixed literal passed to `GetNamedRoutinePointer`, must be a name hs-game-sdk's `scripts.hpp` still has. A positive control (`EnemyDestroyKillProc`, `EnemyRaritySettings`) proves the scan cannot pass blind, and a synthetic negative control proves it both reports a stale name the player build would hook and ignores the same call written behind `#ifndef FORGEPACT_RELEASE`. Written after finding `HookHitReg`, a one-off diagnostic, hooked `"EnemyHitRegDamageParent"` — a name absent from the current SDK — with nothing to catch it because the hook was research-build only; it and its `InstallHitRegHook()`/`InstallHook()` call site are now removed.
  - `test_repo_bounds_contract.py`: Tests boundary protection and index validation against Season 10 item/relic categories.
  - `test_toggle_skill_contract.py`: `ToggleProbeContractTests` pins the `tgprobe` research instrument for issue #11 (toggle skills): research build only (every mention, including the four one-line entry notes inside `Hook_DrawHudBuffs`, `HookTalentUse`, `HookBuffAdd` and, since T1, `HookTalentUseClass`, is stripped from the player build), not in `kPlayerCommands`, exactly the candidate script/event set from `docs/toggle-skills-research.md` (including the `Player_obj` `Step_0` positive control for the event rows) with every name an `hs-game-sdk` constant or `GameObject` enumerator (checked against the headers), no Room Start / Room End event row on any object (the crash guard in `test_est_force_behavior.py` stays as it is), no table hooks, one resolver (`TgProbeAttach`) that checks every pointer with `AddrIsExecutableInModule` before its single `MmCreateHook` call, `calls=n/a` rather than `0` for a row it could not attach, the zone-change state read (`firstHud=`) taken inside the draw hook on the draw where the room key changes, and `InstallHeadLabelHook()` / `InstallBuffHooks()` / `CoopRenderTick()` byte-for-byte equal to `origin/main` (skips if git cannot read it).
    - `ToggleDeepReadContractTests` pins `tgprobe deep`, the session-2 non-scalar read: every `TgProbeDeep*` mention inside the research block and stripped from the player build, every subcommand dispatched, a walker that expands arrays, structs, ds_maps and ds_lists within the pinned caps (depth 3, 200 elements), a member loop whose **every member read has its own try** (session 1's scalar reader wrapped the whole loop in one, so a throw silently dropped the rest) with `names=`/`read=`/`unreadable=` coverage printed per scope, globals enumerated both with `EnumInstanceMembers` and `variable_instance_get_names`, objects named only through `GameObject::` enumerators, the talent scope read through `N1GetTalentMap`/`N1GetTalentStruct`, a builtin-only `selftest` fixture with an `OK`/`FAIL` verdict, and no `%f` and no new hook of any kind.
    - It also pins the four gaps a pre-session review found, each of which could fake a Q3 negative: a live `ref instance` handle is followed one level (identified by its own description plus `instance_exists`, no kind comparison; each member in its own try; never re-entering an instance already read, scope roots included) and counted as `instRefs=`; the leaf budget is per scope with `truncated=` on every scope line, so `global` cannot be starved; `deep diff` takes a path filter, so a known line is never lost past the 300-line cap; and `selftest` covers a `ds_list` plus a separate read-only instance-handle check on `Controller_obj` (`OK`/`FAIL`/`SKIP`).
    - `deep get` names a bad index instead of reporting a builtin throw.
    - A second review pinned three more: a value is taken for an instance, `ds_map` or `ds_list` handle only when its description *starts* with that text (`TgProbeDeepDescribesRef`), so a string that merely contains `ref instance ` is never passed to `instance_exists` or `ds_exists`; members read through a followed handle have their own 250,000-leaf budget per scope (as large as the scope budget, since a smaller one could be spent by one large handle and void a Q3 negative for the whole session), printed as `followLeaves=`/`followTruncated=`, and `deep drop <name>` frees a retained snapshot; and a non-struct object that names no method is counted as `objNonStruct=` without any instance builtin being called on it.
    - `ToggleIndicatorReadContractTests` pins the P1b indicator research control (Track B): the production read (`ToggleIndicatorResolveRowObject`/`ToggleIndicatorReadRow`/`ToggleIndicatorCountMark`/`ToggleIndicatorDraw`) sits outside every research block, while row 0's two aliases (`ToggleIndicatorResolveAoeObject`/`ToggleIndicatorRead`) are research-only since phase S's review - the shipped draw walks the table, so a player build would otherwise compile both with no caller at all; the read takes ownership from each instance's own `isMyClient` and the Purgatory marker from `purgatory` (no `HhResolveLocalPlayer`, no `playerNumber`, no `myHealthBar` - session 3 measured `Player_obj` has neither), and use only two-argument `CallBuiltin` (no `CallBuiltinEx`, no `5759` literal); `Hook_DrawHudBuffs` calls the research sampler right after `HhDrawHeadLabels()`, in its own `#ifndef FORGEPACT_RELEASE` pair; the sampler calls the production read by name; `tgprobe` dispatches `spurn` and `mark`; `TgProbeSpurnCommand` dispatches `spurn fields` (the latched snapshot) and `spurn as foreign` (P1b's non-mutating negative control) and prints `markedOn=`/`lastTransitionFrame=`; `targetNumber`/`purgatoryTimer`/`destroyTimer` (the snapshot-only fields) stay research-only; the mark routine saves colour/alpha before its first `draw_set_` and restores both after its last draw, and counts `draws=`/`drawExc=` separately (both surfaced by `tgprobe mark` and by `tgprobe spurn`'s `markDraws=`/`markDrawExc=`) so "never drew" is never mistaken for "drew in the wrong place" - the fix for the pre-round-1 instrument-blindness finding that a silent draw exception could close the whole slot-location question on an untested instrument; no `TgProbeSpurn`/`TgProbeMark` name survives stripping; and `kPlayerCommands` is unchanged from `7aa3c66` (P1b) plus `toggleborder` (P2) and `toggleguard` (T1), see below.
    - `ToggleIndicatorShipContractTests` pins the shipped indicator (P2): `toggleborder` is in `kPlayerCommands` with the `v == "off" || v == "0"` idiom, additionally dispatches a read-only `stat` (`ToggleBorderStats()`, never touches `g_ToggleBorderOn`), and installs no new hook; `Hook_DrawHudBuffs` calls `ToggleIndicatorDraw()` right after `HhDrawHeadLabels()`, outside any research block; `ToggleIndicatorDraw`'s first statement is the atomic enabled-check; `FrameCallback` never calls it; the slot routine (`ToggleIndicatorFindSlot`) names every field the research doc's "Slot geometry fields" line records; the draw saves and restores colour/alpha; both the `0` and `stat` outputs share `ToggleBorderCountersLine()` and so name every counter (`drawn=`/`on=`/`off=`/`unreadable=`/`noHud=`/`noRow0=`/`noTalent=`/`foreign=`/`drawExc=`, `stat` additionally `enabled=`); the old combined `g_TibNoSlot` counter is gone (`test_no_slot_counter_removed`); and the panel (`mod_toggle_indicator`, default off, `DEFAULTS`/`build_cmds`/the Mods-tab HTML row/the live-apply `f"toggleborder …"` send) mirrors every `mod_pet_quest_pickup` site.
    - Follow-up tests: `test_toggleborder_dispatches_stat`, `test_toggleborder_outputs_name_every_counter`, `test_no_slot_counter_removed`, `test_draw_exception_is_counted` (the catch after `ToggleIndicatorDraw`'s outline loop increments `g_TibDrawExc` rather than swallowing the exception uncounted).
    - `toggle_skill_harness.cpp`'s `indicator_*` scenarios (behind `test_toggle_skill_behavior.py`) run the real `ToggleIndicatorDraw`/`ToggleIndicatorFindSlot` against a controlled `UI_Hud_Talent_obj.row0` and draw-call log: OFF makes no runtime call at all; ON draws exactly once when own+marked and the slot resolves, emitting one rectangle per marker band (the scenario asserts `kToggleMarkerBands`, ten since D-U13, never a literal - T1's three gold passes are gone); Off, foreign-only, an unresolved AOE, a missing slot and an unmarked own instance (the plain-cast flash, session 4's `flash: purgatory`) all draw nothing, the last three counted separately (`unreadable=`, one of `noHud=`/`noRow0=`/`noTalent=` depending on which of `ToggleIndicatorFindSlot`'s three return points failed (`indicator_on/slot_failures_are_split/noHud`|`noRow0`|`noTalent`, each leaving the other two counters at zero), `foreign=` respectively); a throwing `draw_rectangle` is counted as `drawExc=` rather than `drawn=` (`indicator_on/draw_exception_counts`); nothing is cached across draws; and colour/alpha are restored to their pre-draw values.
    - `ToggleGuardContractTests` pins the re-cast guard (T1, issue #11, Track A): `ToggleGuardModel` is a two-valued (`Pass`/`Refuse`) decision on the enabled flag, whether the caller is the double-cast object and the talent id, in a header that includes only `Common.hpp`, and `ToggleIndicatorModel::Decide` is byte-identical to `ab6fed5`; `toggleguard` is in `kPlayerCommands`, treats `0` as off, dispatches a read-only `stat` and installs nothing itself; exactly one `HookOneScript("TalentUseClass"` call exists, inside `FrameCallback` behind the `relicfilter` gate (`g_Setup`, `HhResolveLocalPlayer`, `(fc % 60) == 0`); `HookTalentUseClass` runs, in order, its research entry note (own `#ifndef` pair), the off fast path straight to the trampoline, the caller's `"object_index"`, `GameObject::Universal_Double_Cast_obj` and `kToggleIndicatorTalentId`, and contains no `GetMembers(`, `CallBuiltinEx`, `5318`, `240`, `instance_number`/`instance_find` or `ToggleIndicatorRead`; both the caller's `object_index` and the double-cast object's index are read through `N1ObjectIndex` (twice, no raw `m_Kind` check and no `ToDouble()` before the decision), because this runner returns `object_index` as `VALUE_REF`; a refusal returns the result without the original; `HookTalentUse` is byte-identical to `ab6fed5`; the `tgprobe` `TalentUseClass` row binds `&g_OrigTalentUseClass`/`"HookTalentUseClass"` with `kTgRet`; the counters line (`refused=`/`passed=`/`procSeen=`/`selfUnreadable=`/`objUnresolved=`/`hook=`) survives stripping while `lastProcRet=` does not; and the panel's `mod_toggle_guard` mirrors every `mod_toggle_indicator` site.
    - The `git show ab6fed5` comparisons skip if git cannot read that commit.
    - `ToggleTableProbeContractTests` pins the session-6 research instrument for the generalisation to every toggle skill (research build only): `tgprobe` dispatches `talents` and `tgl`; `TgProbeTalentsCommand` walks `"talentStructMap"` with `ds_map_find_first`/`ds_map_find_next` and prints `abilityId`/`abilityAura`/`abilityDuration`/`abilityCooldown`/`abilityLength`/`abilityTags` per id (`absent`/`unreadable`, never a default) and `ids=`/`shown=`; the `tgl` handler dispatches `add`/`list`/`clear`/`slots`/`fields`/`sub`/`timer`, `clear` keeps row 0, and `add` resolves its object with `asset_get_index` and prints `unresolved` before storing anything; the runtime table is capped at 16 and prefilled with exactly the seven rows of the research doc's static candidate table (row 0 `White_Mage_Soul_Spurn_AOE_obj`/`kToggleIndicatorTalentId`/`"purgatory"`/`"destroyTimer"`, every other row an SDK `GameObject::` enumerator from that row's candidates with its `abilityId` and predicted sub-talent slot); the generalised read takes object index, marker, ownership and timer as parameters and keeps the shipped read's shape (`instance_number`, `instance_find`, `isMyClient` as the default ownership field, no `CallBuiltinEx`); the per-draw sampler reads row 0 through the shipped `ToggleIndicatorRead` on the same draw and counts `agree=`/`disagree=`; `tgl sub` reads `"subTalentMap"` with `array_length`; `tgl timer` prints `first=`/`last=`/`min=`/`max=`/`unreadable=`/`atPredicted=`; `tgprobe mark` has no `ring` subcommand and the table code makes no draw call (no countdown, D-U9); no `TgProbeTgl*`/`TgProbeTalents*` name survives stripping; and `ToggleIndicatorRead`, `ToggleIndicatorFindSlot`, `ToggleIndicatorDraw`, `HookTalentUseClass`, `Hook_DrawHudBuffs`, `FrameCallback` and `kPlayerCommands` are byte-identical to `62a67d2` (skips if git cannot read it).
    - The harness's `table/*` scenarios run the pure parts: row 0 through the generalised read matches the shipped read on twelve worlds (with a negative control that the comparison sees a difference), a row without a marker lights on any own instance and one without an ownership field counts every instance as own, an unresolved object is Unreadable with no enumeration call, and the timer sampler reports the first and last draw's value (`atPredicted=` for a timer held at `-1`) and prints `unreadable` - never `-1` or `0` - for an undefined, throwing or string timer.
    - `SkillTimerProbeContractTests` pins the issue-#55 phase-A additions to the same instrument (research build only, no new hook): `tgprobe talents` reads `game_get_speed`/the `fps` builtin by name and prints `speed=`/`fps=` plus a per-row `predictedTotal=` gated on the speed read; `tgprobe sprite style` dispatches the four countdown-look candidates `arc`/`bar`/`number`/`fade` (eight style names total) and `tgprobe sprite frac [f]` sets the fraction they draw against, clamped `0.0..1.0`; `fade` reuses the shipped `soft` draw rather than duplicating its bands; and none of the new symbols (`TgProbeSpriteDrawArc`/`Bar`/`Number`/`Fade`, `TgProbeSpriteDrawRectOutlineFraction`, `TgProbeSpriteFracText`, `g_TgSpriteFraction`) survive stripping to the player build.
    - **The follow-up round's coverage** (same class): `TgProbeSpriteDrawNumber` anchors its `draw_text` below the box (no `y + h / 2.0` expression anywhere in the body) and captures `prevFont`/`prevColour`/`prevAlpha`/`prevHalign`/`prevValign` before the first `draw_set_*`, draws inside its own inner `try`, and restores each of the five in its own `try` on both the drew and the threw path; the font is resolved with `asset_get_index` and applied only when the index is `>= 0`; `font list` checks each font builtin's existence through `CallBuiltinEx` and prints the `draw_get_font` positive control; `style` parses an optional `[talentId]` and falls back to `kToggleIndicatorTalentId`; `TgProbeSpriteDrawBar` returns without drawing below one pixel of width; `frac` refuses a token whose numeric prefix does not cover the whole token and a non-finite value (reusing the shared `ParseFiniteNumber` helper); and every new symbol (`g_TgSpriteTextOffsetDx`/`Dy`, `g_TgSpriteTextAlpha`, `g_TgSpriteTextColourSet`, `g_TgSpriteFontName`, `TgProbeSpriteTextColour`, `TgProbeSpriteFontListCommand`, `TgProbeSpriteBuiltinExists`, among others) is present in the tgprobe block and absent from the stripped player build.
    - `ForgePact/docs/toggle-skills-research.md`'s `## Issue #55` section names the three candidate total sources for the countdown's fraction, the pre-committed decision rule between them and the live procedure the author runs to settle it.
    - Since the route-A decision-rule rewrite the rule itself is not prose but an exhaustive state-to-outcome table (`### Decision rule`, five tables under their own caption lines), and `SkillTimerProbeContractTests` checks it for completeness (every id present exactly once), unique ids, and the two outcome vocabularies (`measured`/`not observed`/`blocked` for a route's status, `route C`/`route A`/`route B`/`none - session repeats` for what the selection table picks).
  - `test_toggle_skill_behavior.py` + `toggle_skill_harness.cpp`: **Behavioral** suite for the toggle-skill active indicator's read (issue #11, Track B, P1b).
    - Splices the real `ToggleSkillMod.hpp` (game-independent decision) and the real `ToggleIndicatorResolveAoeObject`/`ToggleIndicatorReadTruth`/`ToggleIndicatorRead` from `ModuleMain.cpp` against a controlled game API.
    - Pins the read end to end, before any drawing code exists: zero instances answers Off without reading any instance's own fields at all; an AOE lights the indicator only if its own `isMyClient` reads true (a `VALUE_BOOL`, or a numeric kind whose value reads numeric > 0); an AOE whose own `isMyClient` cannot be read is unattributed and never lights it, and instances present but all unattributed answer Unreadable rather than guessing; the AOE object itself failing to resolve by name is a stronger failure (Unreadable) than "resolved but zero instances" (Off); a threw `instance_number` call is a failed read, not a measured zero, and counts as `countReadFailed` rather than deciding a silent Off; the scan is capped and still decides correctly on what it visited; nothing is cached across calls; the `spurn as foreign` override excludes every real own AOE without ever writing anything to the game; the read makes no player-resolving call in any scenario (`read/no_player_lookup`); and a second pass over the same evidence, `ToggleIndicatorModel::Decide(detail, requireMarker=true)`, decides On only from an own instance whose own `purgatory` reads numeric > 0, Off from an own instance that is readably unmarked, and Unreadable (never guessed as Off) from an own instance whose own marker could not be read with none marked - a foreign instance's own marker is never read at all.
    - Since T1 (issue #11, Track A) it also splices the real `HookTalentUseClass` (the re-cast guard, compiled as the player build sees it: `FORGEPACT_RELEASE` defined) with a counting trampoline and a caller whose `object_index` the stand-in runner answers: `guard_off/proc_passes_and_no_runtime_call` (the baseline - off by default, a double-cast proc of Soul Spurn reaches the original and no builtin is called), `guard_on/proc_of_guarded_talent_refused` (the original is not called and the result comes back untouched), `guard_on/proc_of_other_talent_passes` (Healing Zone, 252), `guard_on/player_cast_passes`, `guard_on/player_chain_passes` (243), `guard_on/self_unreadable_passes_and_counts` and `guard_on/double_cast_object_unresolved_passes_and_counts` (both fail open and count; a failed resolve is never cached, a successful one is), `guard_on/state_not_consulted` (no `instance_number`/`instance_find` call: the guard never reads the toggle's state, D-N1), `guard_on/counters`, `guard_on/self_object_index_kinds/{ref,real,int32,int64,ref_flagged}` (the double-cast caller is recognised and refused whichever numeric kind `object_index` comes back as, including `VALUE_REF` with a flag bit above the kind) and, as their negative control, `guard_on/self_object_index_not_an_index_passes/{undefined,string,bool}` (counted `selfUnreadable`, the call passes).
    - The stand-in answers `object_index` as `VALUE_REF` by default, the kind this runner returns: an earlier stand-in that only answered `VALUE_REAL` let a guard that rejected `VALUE_REF` - and so failed open on every live call - pass every scenario.
    - Every refused-path scenario was run red first against a decision that always passed, and the `VALUE_REF` scenarios red against that plain-number-only check.
    - Skips without a C++ toolchain, like `test_orb_pickup_behavior.py`.
  - `test_restart_anytime_contract.py`: Pins `restartprobe`, the research-build instrument for issue #8 (the pause-menu Restart gate), and its research doc.
    - `RestartProbeContractTests`: research build only (one `"restartprobe"` literal, in `HandleRestartProbeCommand`, stripped from the player build and absent from `kPlayerCommands`); the 22 rows are exactly the doc's static-search set, every one an `hs-game-sdk` constant, attached by one resolver that checks `AddrIsExecutableInModule` before its single `MmCreateHook` (no table hook); `set` refuses before its one write and reads back `wrote=`/`changed=`; every write builtin sits in one helper with two callers; `show` prints `control=` first and `n/a`, never `0`, for an unattached row; nothing of the probe is on `FrameCallback`; `dump` captures inside the Restart draw on that call's self; `argset` is budgeted and confirm-gated; `path` resolves through `TgProbeDeepGet`. The hold (round 2, extended in round 3) writes only inside a site row's detour before the trampoline, in the kind read at entry, with `entryHeld`/`entryOther`/`readbackOk` decided there; scope `arg0` checks the call's argument count and argument 0 before `HhUsableInstance`, before the member read, before the write, and every instance target is labelled from the instance it resolved to (no `"button."` literal); there are two slots (`kRpHoldSlots`), a third hold refuses `two holds armed`, `hold off` clears both, and `hold stat` prints each slot's run-length ring (`kRpHoldRing` entries); the 3-frame gap disarm applies only at the draw row, any other site disarms on the draw row's `lastCallFrame`/gap (`menu not drawing since frame …`), and arming there refuses `needs the Restart draw attached` while the draw row is not `native`.
    - `RestartResearchDocTests`: the doc's headings, the six `## Decision` lines pinned literally (round 3's, with `override: works` allowed only while the round-3 rows record C1 and C5 as passes), every round's result rows quoting the printed fragments, the procedure tables' bolded step names (a plain `| S1 |` row is a result), C1-C5 named before the procedure, and the round-3 procedure rows C5, T1-T6.
    - `RestartAnytimeContractTests` (the shipped mod, `restartanytime`): a player command dispatched as a standalone early return; one `UiSetFocus` install, in `FrameCallback` behind `IsPending()`/`g_Setup`/`(fc % 60) == 0`/`HhResolveLocalPlayer`, through `HookOneScript` with its `nativeOut` read; a `TABLE-ONLY` install calls `MarkBlind()` and says so; the off fast path is the hook's first statement and reads nothing; the button is identified by its own `uiNodeCallstack` after `HhUsableInstance`, before the gate read, before the write, never by `self`, `selfIds` or an instance id; `0` and `stat` print every counter; `mod_restart_anytime` appears in `forgepact.py` exactly as often as `mod_toggle_guard`; the release notes, README and this guide record the mod.
  - `test_restart_anytime_behavior.py` + `restart_anytime_harness.cpp`: **Behavioral** suite for `restartanytime` (issue #8). Splices the real `RestartAnytimeMod.hpp`, `HhUsableInstance`, `RestartAnytimeReadGate` and `HookRestartAnytimeSetFocus` against a stand-in runner that answers the kinds this runner was measured to hand over (`VALUE_REF` for the button, `VALUE_BOOL` for its members, `VALUE_STRING` for `uiNodeCallstack`) and a counting trampoline.
    - Scenarios: `baseline/off_by_default`, `baseline/off_calls_original_and_writes_nothing` (no builtin call at all while off), `target/on_writes_only_when_arg0_is_the_restart_button`, `target/on_leaves_every_other_node_untouched` (a Resume-shaped negative control, a node without the key, a numeric key, a non-instance argument, no argument, and the Restart button as `self` rather than `a0`), `target/on_unreadable_member_passes_and_counts`, `target/on_calls_the_original_exactly_once` (the game's body sees the written value), `target/on_preserves_the_kind_read_at_entry` (bool stays bool, real stays real), `target/on_gate_already_open_writes_nothing` and `target/blind_install_stays_off`; the first-write line appears exactly once.
    - Every `target/*` scenario was run red first against a pass-through body; each failing line is recorded beside it in the harness. Skips without a C++ toolchain, like `test_orb_pickup_behavior.py`.
  - `test_relic_filter_contract.py`: Validates the relic drop pool filter, orb pickup radius mod, build-order packaging guard, player-resolution against `VALUE_REF`, the stall watchdog's research-build presence/ordering, and the Map Reveal / Headhunter / Tyrant's Crown / Beacon panel relocation (29 tests, covering everything fixed 2026-09-09/10).
  - `test_out_log_rotation_contract.py`: Source-contract tests for the `out.txt` / `itemdrops.jsonl` size rotation (2026-09-18) - both rotation helpers exist with their own size thresholds, `RotateOutLogIfNeeded` survives stripping research-only code (compiled in both builds) while `RotateItemDropsLogIfNeeded` does not (research build only, since the player build never writes `itemdrops.jsonl` at all), both move via `MoveFileExW(..., MOVEFILE_REPLACE_EXISTING)` rather than copy or delete, `out.txt` is never opened with `std::ios::trunc` (checked as the code token, not the English word, since the fallback comment legitimately says "truncate"), and `ForgePact::ModManager::Initialize()` creates `bp_ipc\` before rotating and rotates before the `BloodPact plugin loaded` banner, with the `itemdrops.jsonl` call site itself (not just the function) guarded by `#ifndef FORGEPACT_RELEASE`. No native harness (see the file's own docstring for why: the rotation helpers call `GetModuleFileNameA`/`MoveFileExW` directly rather than being game-independent by contract like `ProspectWindowMod.hpp`'s core, so faking the Win32 calls would be a bigger lift than a rotation fix justifies) - the two real `build.bat dev`/`release` runs are the compile-time check.
  - `test_research_docs_no_decompiler_output.py`: Keeps every `docs/*.md` free of decompiler output, per the repo-root `AGENTS.md` "Legal: Decompiled Output Never Reaches Any Origin". Globs the whole `docs/` directory, so a new research doc is covered the day it lands. Every doc must carry no decompiler tokens or Ghidra data labels, no IDA-style `sub_` names, no disassembly lines and no hex byte signatures; the docs on its `STRICT_DOCS` list (`S10-special-content-notes.md`, `dungeon-key-research.md`, `angelic-drop-research.md`, the ones rewritten to this standard) must also carry no code addresses, RVAs, register names, per-event byte sizes, offset listings, pseudo-code call forms, code-form calls (a routine quoted in backticks with two or more arguments, a comparison, or an assignment from a call - inline backtick spans only, so a fenced block or unquoted prose is not checked) or numbered steps that follow a routine call by call. Each category has a positive control (a known-bad sample, built in pieces, that must be flagged) and a negative control (ordinary prose that must not be); failures name the doc, the line and the category. When another doc is rewritten to the strict standard, add it to `STRICT_DOCS`.
- `docs/`: Reverse-engineering research logs, memory audits, and drop rate analysis.
  - `S10-special-content-notes.md`: Detailed Season 10 reverse-engineering log for special content spawners, gate mechanisms, crash thresholds, and investigated workarounds - written in our own words (names, indices, measured values and our own code; no addresses or decompiled text).
  - `dungeon-key-research.md`: Documentation of the two-stage key/relic drop architecture (`LoadDrops` outer gate + `droprate.base` inner roll).
  - `angelic-drop-research.md`: Analysis of Angelic/Unholy drop rates and synthetic drop roll implementation.
  - `blood-pact-values-research.md`: Research findings on Blood Pact modifiers and stat calculations.
  - `satanic-zone-mods-research.md`: Live-tested findings on the Satanic Zone buff/debuff pool - why the originally-planned routine hook (`LoadSatanicZone`) doesn't work, and the poll-and-correct mechanism that shipped instead.
  - `pet-quest-collector-plan.md`, `pet-quest-collector-research.md`: The original Pet Quest Collector plan (mechanisms B1/B2) and its research log - 34 hooked call sites reporting 0 calls on multiple confirmed collects. **Read with the correction in the Plan C log:** that 0 was the instrument, not the game (see the `HookOneScript` note below); the conclusions drawn from it about the game's behaviour do not hold.
  - `pet-quest-collector-plan-b4-input-simulation.md`, `pet-quest-collector-b4-research.md`: Plan B4 (fake the player's hover + keypress) and its research log. Disproven live: the GML-visible input state is a downstream mirror of real device input, so writing it changes nothing.
  - `pet-quest-collector-plan-c-direct-invocation.md`, `pet-quest-collector-c-research.md`: **The plan that worked, and the log that closed it.** Invoke the quest item's own `m_Quest*` bound methods rather than any named routine - name-free, so unaffected by the named-routine-table wall that closed B1/B2 - with Ghidra as an explicit, anchored fallback (Phase C1), which is the half that actually found the mechanism. Confirmed by reproduction on 2026-09-11 (a plugin-invoked collect advanced a quest counter 7/15 -> 8/15), then shipped as Phase C2 and live-measured as the mod (`collected=3` and `collected=6` across two sessions, every failure counter at zero). The research doc also carries the correction that matters most to future work here: **`HookOneScript` is blind against this build's compiled GML** - it swaps a pointer inside the script-table entry, and compiled GML calls another script with a direct `call rel32` that never reads that table, so every "0 calls" result from a named-script hook in these notes measured the instrument, not the game. Use `MmCreateHook` on the resolved address (`citrace nativetrace`) when a named-script hook reports zero.
  - `toggle-skills-research.md`: Issue #11 (toggle skills: a re-cast guard and an active-slot border).
    - The author's definition (White Mage Soul Spurn with the Purgatory sub-talent; no tag; ends on recast or zone change), the complete static search (no `*Purgat*` / `*Spurn*` script exists; `White_Mage_Soul_Spurn_obj` is a `Player_Ability_Parent_obj` child), the `tgprobe` instrument reference, and the two-session live procedure.
    - **Two live sessions run (2026-09-17). Track B (active indicator) UNBLOCKED; Track A (re-cast guard) was BLOCKED on Q2; since T1 (2026-09-19) it is built (`toggleguard`, off by default) by caller identity instead, without Q2, and is no longer awaiting session 5 - that rerun measured it live on a research build (2026-09-20, White Mage only: `refused=9 procSeen=9 passed=61`) and session 7 confirmed it in the ship build (`## Decision` → `### Track A design (D-N1)`, `## Live procedure` → `### Session 5`, `## Results` → `### Session 7 — ship-build confirmation (phase S, 2026-09-20)`). See Known Limitations item 17 for what that does and does not cover.**
    - Session 1 measured: the cast path (`TalentUse` → `TalentUseClass` → `TalentsWhiteMage`, Soul Spurn = talent 240), the HUD draw order (`DrawHudBuffs` draws after the ability buttons), and three sources of accidental re-casts: the double-cast proc (which calls `TalentUseClass` directly, bypassing `TalentUse`), key auto-repeat every 57 frames, and real re-presses; not observed where the on/off state lives in any scalar (not in `Player_obj`, global, the HUD object, ability objects or player buffs; buff 86 is the Martyr passive).
    - Object-event rows do not resolve by name on this build.
    - **Session 2 measured Q3-D**, the non-scalar read: with `tgprobe deep` (snapshots of `Player_obj`, the talent structs, `Controller_obj`, the HUD slot object, `Skill_Controller_obj`, every global and a live-instance census, diffed across OFF → ON → OFF, checked against controls C2–C5 (all FIRED) and C1's mechanics half (FIRED; C1's instance-handle check FAILed on a check-expectation defect, not a walker defect)) the ON/OFF state is not a member of any scope but a live-instance count — `White_Mage_Soul_Spurn_AOE_obj` (SDK index `GameObject 5759`) exists while ON, does not exist while OFF; that call **shape** — `CallBuiltin("asset_get_index", ...)` then `CallBuiltin("instance_number", ...)`, with no `self` supplied at all (the global-context form, not the `self`-taking `CallBuiltinEx`) — is confirmed to resolve and return a number, not the bare `unreadable` token (`n/a` prints only when no snapshot has ever been taken — a different code path, not an answer from this call), in the global context, via `TgProbeCountByName`, twice this session, at room attach before any cast existed, on two other objects (`White_Mage_Soul_Spurn_obj`, `Player_Ability_Parent_obj`); **the read `instance_number(asset_get_index(GetObjectName(...))) > 0` itself was never called on `White_Mage_Soul_Spurn_AOE_obj`**, and where the shape did run it only ever returned `0`, so the indicator workorder must run its own ON=1 positive control, in the context it actually plans to use, before trusting it; so the local Ghidra fallback (Q3-G) was not needed.
    - Two candidate storage locations exist for the Purgatory sub-talent level (`global.subTalentMap[1].t240.{s2,s6,s7,s9,s10,s12}` and a mirrored HUD-object map), but which sub-index is Purgatory's is not identified.
    - `## Decision` → `### After session 2` carries the read, and what it is untested on (co-op/per-player scoping, a non-Purgatory cast, zone change, OFF lag, HP self-cancel, more than one instance), as the indicator workorder's input.
    - **Session 3 (2026-09-18, the indicator workorder's P1-LIVE) recorded `read: GO` and `slotgeom: row0[5].talentId + navBboxX/navBboxY/navBboxWidth/navBboxHeight` (the Soul Spurn hotbar slot), but `scope: BLOCKED`** — `Player_obj` has no `playerNumber` member; the only hit for the ownership key is a followed instance handle, `Player_obj.myHealthBar.playerNumber`, a different key than the P1 ownership design assumed (`## Decision` → `### After session 3`).
    - **Replan 1 answered it: ownership is read from each AOE instance's own `isMyClient` instead, with no local-player read at all** (`## Decision` → `### Co-op / ownership after session 3: isMyClient`); P1b's session 4 proves it from the draw hook and measures the Purgatory marker before P2 starts.
    - **Since 2026-09-19 the doc also carries the generalisation to every toggle skill:**
    - `## Static search` → `### Other toggle skills: the static candidate table` lists six more candidates beside Soul Spurn (Exo Lunar Orbit, Plague Doctor Crematus, Shield Lancer Counter, Butcher Submerged Knives, and the second-tier Prophet Maelstrom of Frost and Butcher Blender), found from the game's translation-file keys (paraphrased, never quoted) and the SDK object table, with the static negatives labelled; `### Session 6` measures each one with `tgprobe talents`/`tgprobe tgl`, and `## Results` → `### Toggle skill table` recorded (2026-09-19) four more rows shippable in the outline — Exo Lunar Orbit, Plague Doctor Crematus, Butcher Submerged Knives and Prophet Maelstrom of Frost, three of them (Lunar Orbit, Crematus, Submerged Knives) on a measured ON object different from the row's prefilled candidate — while Shield Lancer Counter's toggle state turned out to be a player buff, not an instance, and Butcher Blender is `blocked` (`## Decision` → `### After session 6`).
    - **Since phase S (2026-09-20) the outline and the guard cover five skills** - Soul Spurn, Lunar Orbit, Crematus, Submerged Knives and Maelstrom of Frost - from one table whose talent ids are resolved at runtime by `abilityId`, with the marker changed to D-U13's `deepred` soft bands at D-U12's derived box and the guard's refusal gated on the row's toggle sub-talent; `counter` and `blender` do not ship.
    - **Confirmed in a ship build on 2026-09-20** (`## Results` → `### Session 7 — ship-build confirmation (phase S, 2026-09-20)`, at ForgePact `9d88156`): all five talent ids resolved in one walk, the tester's verdict "all five skills work, guard refused correctly, tgprobe unavailable", and a second plain Maelstrom cast in which the marker was not observed to light.
    - See the `toggleborder`/`toggleguard` bullets and Known Limitations items 16-17.
  - `prospect-window-research.md`: ForgePact issue #9 (the prospect window is too small for the inventory beside it).
    - **Stage B, auto-prospect on insert, is built (2026-09-18; `autoprospect`, above, and Known Limitations item 19): Phase 1 is complete (`phase1-status: complete`) with the one shippable shape recorded, and § Stage B ship design, § Stage B Phase 3 live procedure and the `S-*` rows of § Stage B results (recorded 2026-09-18, all passed by eye) describe what shipped and how it was checked live. Stage C, the previous batch of materials to the materials tab before each prospect, is built too (2026-09-19; `autoprospect bag`, above): `stage-c-status: complete` with the nine `M-*` rows filled and `move-shape: stackmove route (plus success check)` recorded, § Stage C ship design describes what shipped, and § Stage C Phase 3 live procedure / § Stage C Phase 3 results (`phase3c-status: complete`, the eight `T-*` rows, filled from the 2026-09-19 re-run on 20fc518) are the human's live check. Stage D (2026-09-19, after the c27cdad re-run found the first-of-type material refused and an ore sometimes returned to the backpack): § Stage D static search / hypotheses / instrument / live procedure (N0-N6) and § Stage D results (`stage-d-status: complete`, nine `N-*` rows), § Stage D ship design, and § Stage D Phase 3 live procedure / § Stage D Phase 3 results (`phase3d-status: complete`, five `D-*` rows).**
    - The history below is the research stage.
    - **Phase 0a+0b ran 2026-09-17: H = not observed** (0a instrument blind: stale SDK closure names, SDK regenerated at hub `4539e68`; 0b not blind: `nodeGrid` is built inside `m_SetInventoryLocalPlayer` and follows neither a `nodeGridWidth` written before it nor any re-run builder).
    - **Phase 0b lead = the ProspectGrid store is profile inventory data (unconfirmed; a local Ghidra read, paraphrased). Phase 0c tests it read-only (`prospectprobe backing`, a controlled save test R7, the auto-prospect call shape R12); decision gate D5 pending** - a profile-backed store would make "bigger" a save-data change, so the human picks the branch before any Stage B build.
    - Phase 0a did establish that the input grid is a 9 × 6 `UI_Inventory_Grid_obj` node named `"ProspectGrid"` whose size lives in `nodeGridWidth`/`nodeGridHeight`, and that writing `nodeGridWidth` bare crashes the node's `Draw_64` within a frame because its cell store `nodeGrid` was sized at build time (R5b).
    - Records the static search (the objects, the prospect / `UiFuncs` / inventory-grid script candidates and the 45 Create-event closures of the ten UI/prospect objects, re-derived from the regenerated SDK, and the sourced negatives), the hypotheses (H1: a named call receives the grid size as arguments; H2: a bare variable write - ruled out by R5b; H2': the game's own builder reads variables a write before it, or a re-run after it, can change; H3: fixed) with the evidence each one needs, the `prospectprobe` instrument, the Phase 0b live procedure (hook-free `grid` read and write controls first, the four live-read closure rows that must install, the logged open with grid snapshots, then `override`, `setat` and - last - `resize … via`: every method shrunk first, then grown if its shrink kept or reverted with `invoked=yes` and an unchanged store, each given the call shape the game used; only a grow's `reverted` counts toward H3), the Results table with filled Phase 0a and Phase 0b columns (plus the paraphrased Ghidra read, the blind `callnum` recorded as an instrument misuse, and the fixed 9×6 `Craft_Grid_Large_spr` background) and an empty Phase 0c column, the Phase 0c live procedure (C1-C8), and the decision gate (save-backed / not save-backed / inconclusive, read in that order - `reference-identical` via an identity found in **two distinct calls of the same profile getter** (`GetProfileInventoryData`/`GetPlayerProfileObj`) at a path through no **UI-looking field**, or R7 kept, decides save-backed (a `one call only` identity, or one reached only through a UI-looking field, is a lead that decides no branch); `copy` (every walk complete, no window return dropped) with R7 returned decides not save-backed, anything else is inconclusive, and structural agreement is only a lead -, the save-data risks, and the `prospect all` and auto-prospect alternatives).
  - `character-select-research.md`: Can anything drive the game's own main menu as far as a loaded character (main menu, Local, save slot, Play)? The hub's `hs-drive` MCP server launches the modded game and talks to this plugin, but a human still has to click that path before most gameplay commands do anything. **Instruments built 2026-09-20; live session run 2026-09-21**, so every `## Results` row carries its measured reply and `## Decision` reads `finding: a-sendinput, a-postmessage, d` / `shipRoute: mcp-only`. Injected `send_input` drove a freshly launched game from its main menu to a loaded character in `Town_01_rm` with no human hand - **provided the click is held**: a button-down and button-up emitted back to back land in one frame and a 144 fps sample loop never sees the button pressed, which is a defect in `hs_input`'s own `click` action rather than a fact about the game. The script route is `unmeasured` (its positive control raised) and the event route is `not observed`, scoped to the object and the seven events actually tried. Records the static search (the SDK's room, script and object names for the path; the five existing verbs that sound right and are not - `forceslot`, `forcelogin`, `puppetinput`, `roomprobe`, `coopstart`; the research verbs reused unchanged), four candidate mechanisms each with its own positive control, the two-part instrument (`menuprobe` here, `hs_input` in the hub), the live procedure, the filled results table, and the negatives it relies on with their sources. Shipping anything on the result is a separate workorder, `hs-drive-mcp-charselect-ship`, whose first step reads those two literal lines out of this file.
  - `menu-layout-research.md`: Where, in window (client) coordinates, are the buttons a tool presses to get from the main menu to a loaded character (`Play local`, save slot N, `PLAY`), as the running game reports them? Records the static search (the thirteen SDK objects `menulayout` lists: the `UI_Node_Parent_obj`, `UI_Parent_obj` and `UI_List_Item_Parent_obj` roots, five leaves and five unparented save/menu objects), the instrument (`menulayout`, its output format and the GUI-to-window mapping, with its positive control: `Play local` at `win=336,534` on a 1920x1080 windowed client), the phase 0 live procedure (dev build, never clicks `PLAY`), its `## Results` (run 2026-09-21), and four `## Decision` lines. The save-slot cards are the `visible=1` `Choose_Parent_obj` rows, listed through a UI root although not in the table. They are ordered by `win` y then x, and the game's own `slot` variable agreed on all 24 page-1 cards. A hidden duplicate sits at every card's point, so `visible=1` is required. `PLAY` is the `UI_Button_obj` whose text is exactly `Play`, and it is listed only after a card is clicked. Both are clicked at their listed origin. The slot order is owner-stated and was confirmed there: row-major, so slot 2 is the card to the right of slot 1.
  - `menu-pause-plan.md`: A complete design for "pause the world while a menu is open" (freeze monsters, player, mercenary, pet, damage and every timer), researched to the point where the mechanism was clear - and **closed as not recommended**, which is why it is worth keeping. Its §0 is the general rule: features that suspend or take over the game's own runtime loop (pause, time scaling, save-state/rewind, wholesale instance deactivation) invert this plugin's failure mode from "does nothing" to "player's session is stuck", cannot be verified by the contract tests, and tax every future game patch. See `AGENTS.md`, "Don't Suspend the Game's Own Runtime". Nothing in it was measured in-game; its Phase 0 costs one session and no rebuild (the research build's `cb` command already calls the builtins involved) and is the right first step if the feature is ever wanted anyway.
- `build_release.py`: Packaging script creating the frozen PyInstaller distribution at `dist/ForgePact/` with release guard checks.
- `tools/`: Developer-loop helpers (not shipped to players).
  - `ghidra/ImportSymbols.java`: Names a stripped `Hero_Siege.exe` in Ghidra from the game's own runtime script table. `Hero_Siege.exe` is a YYC build (~280 MB, every GML script compiled to native code, no symbols), so a decompiler shows `FUN_14xxxxxxx` everywhere - three research sessions stalled on exactly that. The fix needs no disassembler: the running game already knows every script's name (`script_get_name(i)`) and address (`GetNamedRoutinePointer`). Run `citrace symdump` in the research build to write `bp_ipc\symbols.csv`, then run this headless with `-noanalysis` to create and name a function at each RVA. Covers the runtime-only `anon@N@gml_Object_..._Create_0` closures that `hs-game-sdk`'s static table does not have. Reusable by any tool or mod that needs to read this binary, not just the one it was built for - see `ForgePact/docs/pet-quest-collector-c-research.md`.
  - `ipc.ps1`: Sends a command to the *running* plugin and prints only its reply. Resolves `bp_ipc` from the panel's own `forgepact.json`, records `out.txt`'s byte length before writing `cmd.txt`, waits for the game to actually consume it, then prints just the appended lines. Replaces the hand-driven "edit cmd.txt, then scroll a multi-megabyte out.txt" loop every research session used before 2026-09-11 - see `AGENTS.md`'s "Limit Rebuilds & Reruns". Usage: `.\ForgePact\tools\ipc.ps1 citrace methods`, `-Lines "petquest 1","petquest stat"` to batch, `-Tail 40` to just read. A timeout means the game is not running or the plugin did not load. Its MCP counterpart is the hub's `hs_command` tool (`tools/hs_drive_mcp/ipc.py`, documented in `../../tools/hs-drive-mcp.md`), which runs the same byte-offset algorithm from a Claude Code session and pairs with `hs_ipc_tail` for `-Tail`; the two differ in two places on purpose - with the game running, `hs_command` **waits a pending `cmd.txt` out** and then writes its own fresh, instead of overwriting it with a warning nothing reads (the plugin reads the whole file before deleting it, so a line added in between is deleted unread while the file still vanishes, and the previous command's output would come back as this command's reply; the timeout is split between that wait and this command's own, so a refusal never reports a wait longer than the one it made), and an unconsumed command comes back as a refusal token rather than a printed message - one that says whether the plugin was watched reading this channel at all, because "nothing reads it" and "it was busy with the earlier command" have different fixes.

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
   - **Check the version is still unpublished before you leave notes sitting in a long-lived PR**, with `git tag --list vX.Y.Z` (and, if in doubt, `gh release list`). A branch that has been open across a release ends up carrying notes for a version that already shipped: the cleanup above then deletes them without them ever reaching a release page, and `--compose-notes` never selects them because it only reads the tagged version's own file plus versions newer than the previous tag. Re-file them under the next unpublished patch instead — and prefer the version another open PR is already using, so both features' notes ship with the release that carries the code; a textual conflict in one markdown file is cheaper than notes that go out silently missing. (2026-09-20: the toggle-skills PR's notes were on `v1.4.4`, published the day before, and moved to `v1.4.5`.)
   - It is no longer a prerequisite to tagging or releasing. `forgepact-tag.yml` composes the draft release body from whatever notes files exist at tag time — the tagged version's own file if it exists, otherwise GitHub's generated notes under a "rewrite for players before publishing" banner, plus every skipped version's own file concatenated in newest-first order. See "Tagging a release (forgepact-tag.yml)" below for the full composition rules. `cut_release.py --check` still fails on a missing notes file by default; only `--allow-missing-notes`, which only the tag workflow passes, relaxes that.
   - If the top file is missing at tag time, the draft's top section is generated notes under that banner, and it **must be rewritten into player language before publishing** — generated notes are pull-request titles, not something written for a player deciding whether to update.
   - Player-facing only, in plain language — what was broken and what changed *for the player*, not internal refactors, build-script fixes, or debugging history (that belongs in this instructions.md, e.g. Known Limitations, not in release notes). Match the tone of the existing files: name the symptom before the fix ("Tyrant's Crown and Monster Rarity did nothing in 1.3.14" before explaining why), and give a measured before/after number when one exists.
   - Standard sections, in order: `## New`, `## Fixed` (either may be omitted if empty, but at least one must be present), then `## How to update` with the standard boilerplate (see any existing file). A `## Changed` section is used for reorganizations (e.g. a control moving to a different panel tab) that are neither strictly new nor a bug fix.
   - Never claim something is "Fixed" that is not actually resolved. If an investigation concluded the *reported* symptom is not this project's bug (e.g. a freeze traced to a display driver / GPU stall with a control run proving the plugin was not involved), that finding belongs in this instructions.md's Known Limitations, not in release notes as a fix — release notes are read by players deciding whether to update, and an overclaimed fix erodes trust in every note that follows it.
7. **Write the panel's mod descriptions for the player, not as a coverage report:**
   - The small grey text under each mod in the panel (`src/forgepact.py`) says, in one or two plain sentences, what the mod does for the player, plus at most one caveat a player would act on (off by default, toggles excluded, and the like). Keep it to about 300 characters.
   - Measurement status, which skills were tested or covered by rule, measured values, edge cases and mid-cast quirks belong in the README row, the release notes and `docs/*-research.md`, which is where the honesty tests require them. Do not add tests that force that detail into the panel span; pin the span short, name-free and without overclaim instead.
   - Why: on 2026-09-22 the owner read the Timed skill countdown's panel text, which listed every coverage tier, the 0.2 s hit refresh and the mid-cast latch, and asked for it to "say what it should be not what it is exactly to the t with all the dev logs". The span became: "Shows how much time a timed skill has left, over that skill's slot on the skill bar, in the look you pick below. Works for most timed skills; toggles and companions (turrets, totems) don't get one. Off by default." (`SkillTimerRuleContractTests.test_player_text_states_behaviour_without_overclaim` scopes the detail words to README and release notes; `SkillTimerBuffContractTests.test_player_text_says_measured_buff_skills_are_covered_without_names` caps the panel span at 300 characters).

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
  (forgepact-release.yml)" below for the full pin table. `origin`'s pin now names a `YYToolkit.dll`
  built from the hub's `third_party/yytoolkit/` series with `tools/build_yytoolkit.py`; the pull
  request that moved it from the previous `bb113eef…` file has merged (see the pin table's
  provenance note), but no ForgePact release has shipped a package built against the new pin yet,
  so a player's installed copy still runs `bb113eef…`.
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
| `py -m unittest discover -s tests -v` | `ForgePact/` | PowerShell / CMD | Python 3.10+ | Executes all 1232 Python contract tests (including the native behavior harnesses, which skip without a C++ toolchain). | Read-only test execution; all tests pass | Verified 2026-09-22 |
| `py tools/perf_panel.py` | `ForgePact/` | PowerShell / CMD | Python 3.10+ | Times the panel's two per-poll costs - the boot count and the process scan - against reference copies of the pre-1.3.20 implementations, and exits non-zero if either regressed below its floor. No game, no network. `--log-mb`, `--iterations`, `--min-speedup`. | Writes and deletes a synthetic log in a temp directory | Verified 2026-09-15 |
| `py tools/cut_release.py --check --expect <version>` | `ForgePact/` | PowerShell / CMD | Python 3.10+ | Reports the version at every site and fails if they disagree, or if the release notes are missing and `--allow-missing-notes` was not given. `py tools/cut_release.py <version>` moves them. `--allow-missing-notes` (only `--check`; only used by `forgepact-tag.yml`) reports a missing notes file without failing. **Do not hand-edit the version sites** - a mismatch here is the signal, not a nuisance. Touches no git, runs no build, stages no DLL. | `--check` is read-only; a bump rewrites two files | Verified 2026-09-16 |
| `py tools/forgepact_tag.py --tag <version> --existing <tags…>` | `ForgePact/` | PowerShell / CMD (Git Bash for the real examples below) | Python 3.10+ | Checks a typed tag/version against the existing `v*` tags and the tree, and prints `version=`, `tag=`, `bump=`, `previous=`. Refuses a taken tag, a downgrade against the highest tag, a version below the tree, or a malformed input. | Read-only | Verified 2026-09-16 |
| `py tools/forgepact_tag.py --compose-notes --version <v> --previous <tag> --generated <file> --out <file>` | `ForgePact/` | PowerShell / CMD | Python 3.10+ | Composes the draft release body: the tagged version's own `release-notes-vX.Y.Z.md` if present (else the generated notes at `--generated`, under a banner), plus every skipped version's file, newest first. Prints `source=` and `versions=`. | Writes `--out`; reads notes files under `--root` (default: repo root) | Verified 2026-09-16 |
| `py tools/forgepact_tag.py --published-notes --version <v>` | `ForgePact/` | PowerShell / CMD | Python 3.10+ | Prints the bare filenames of every `release-notes-vX.Y.Z.md` at or below `<v>`, oldest first, one per line; empty when there are none. What `forgepact-notes-cleanup.yml` deletes after `<v>` is published. A malformed version exits 1 with empty stdout. | Read-only; lists `--root` (default: repo root) | Verified 2026-09-16 |
| `plugin_build\build.bat` / `plugin_build\build.bat release` | `ForgePact/` | CMD / PowerShell (Windows x64) | MSVC v143+ (VS 2022), YYToolkit headers in `plugin_build\include\` | Compiles `BloodPactPlugin_ship.dll` with `/DFORGEPACT_RELEASE`. Equivalent commands - `build.bat` only special-cases `dev`; anything else (including no argument) takes this branch. The staging check afterwards is `fc.exe /b plugin_build\BloodPactPlugin_ship.dll modfiles_shipped\BloodPactPlugin.dll`, expected to report `no differences encountered` - note that this build **writes** that copy and the path is gitignored, so a match is automatic and confirms only that the copy step ran, not that the binary is right. | Generates `plugin_build\BloodPactPlugin_ship.dll` and `obj_ship\`, and refreshes `modfiles_shipped\BloodPactPlugin.dll` | Verified 2026-09-20 (ForgePact `9d88156`; exit 0, staging check `no differences encountered`, and the resulting player build confirmed in-game: all five toggle skills marked, the guard refused a double-cast proc, and `tgprobe` answered `command unavailable`) |
| `plugin_build\build.bat dev` | `ForgePact/` | CMD / PowerShell (Windows x64) | MSVC v143+ (VS 2022), YYToolkit headers in `plugin_build\include\` | Compiles `BloodPactPlugin_rel.dll` (research build with inspection commands, and `satmods` diagnostics). | Generates `plugin_build\BloodPactPlugin_rel.dll` and `obj_dev\` | Verified 2026-09-20 (ForgePact `9d88156`, exit 0; this build is where session 7 measured the toggle table's live id resolution and the Maelstrom timer control) |
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
  "mod_pet_quest_pickup": false,
  "mod_toggle_indicator": false,
  "mod_toggle_guard": false
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
  - `reveal 1` / `reveal 0`, `reveal packs 1` / `reveal packs 0` (+ `reveal stat` in the research build only): Map reveal.
    - `reveal` clears the zone's minimap fog grid once per zone identity - measured 2026-09-11 to be all that static icons need (waypoints, dungeon entrances, chests, shrines and mining nodes are fog-gated, **not** gated by `isDiscovered`, so no per-object sweep exists or is needed).
    - `reveal packs` is the monster half and the only part that adds work: most packs do not exist until the player walks within ~1050 px of their `Enemy_Creator_*`, so it opens a bounded 900-frame window per zone during which `distance_to_object` answers 0 for creators, letting the game's own creator logic populate the map (measured 148 → 866 and 208 → 1273 enemies; ~7.8 ms frame average, plugin 2.3%).
    - The window only opens once a live creator reports a real `enemyCreatorTimer` - firing during zone load leaves spawners permanently inert.
    - **The authorization is then re-checked per creator, inside `Hook_distance_to_object`, at the moment the distance would be changed** - not at a frame boundary: `EVENT_FRAME` is dispatched from `HkPresent` at the end of the frame, while creators consume the permission in their step events earlier in the same frame, so a window invalidated at Present is too late for the first call in a new zone.
    - A creator that has not initialised keeps its real distance however stale the window is; a ready one is still served, so the pass keeps working across a transition instead of failing closed.
    - The same guard covers the Beacon's lie.
    - The window is additionally bound to the full zone identity (room + minimap instance + grid), re-checked every frame as defence in depth, and is never opened against an identity that could not be read.
    - Turning `reveal packs` on arms the **current** zone's readiness-gated pass rather than waiting for the next zone change.
    - Panel: `map_reveal` with the nested `map_reveal_packs` checkbox.
    - See `ForgePact/docs/map-reveal-research.md`.
  - `petquest 1` / `petquest 0` (+ `petquest stat` in the research build only): Pet Quest Collector. Working and live-measured 2026-09-11. While enabled and a `Companion_obj` exists, `FrameCallback` runs a two-phase tick: `Idle` enumerates `Quest_Object_Parent_obj` descendants inside the camera view (minus a static exclusion list, 64-instance budget), picks the nearest collectable one, and `Travel` writes the pet's `x`/`y` toward it at 11 px/frame until it arrives (or 240 frames elapse, which collects anyway - the walk is cosmetic, the credit is the point), then invokes the collect and waits 24 frames. The collect: with the item as `self` and `Loot_Manager_obj` as `other`, invoke the item's own `m_Questpickup` method value with one real argument, reached via `InvokeMethodValue` (the callable read off the method value's own `CScriptRef`, validated before the call — no game addresses; see Known Limitations item 11); it calls `update_quest` -> `QuestSaveUpdate` internally, so the objective credit is inside the call and nothing is faked. The game's own gates (`canPickup`, `lootType == 0`) are re-read from the live instance at collect time. `petquest arg <n>` (both builds) changes the one argument that was reproduced rather than understood. **Not implemented:** an accepted-quest gate, and the loot-system side effects a real collect performs (sound, pickup effect, inventory log) - so a pet collect is silent. See `ForgePact/docs/pet-quest-collector-c-research.md` and Known Limitations item 11.
  - `toggleborder 1` / `toggleborder 0` / `toggleborder stat`: shipped toggle-skill active indicator (issue #11, Track B).
    - Covers **eight** skills since session 12 (Meteor Storm and Bushido added in session 9; Shield Lancer Counter in session 12), one table row each (`plugin/include/ForgePact/ToggleSkillMod.hpp`'s `kToggleSkillRows`, the only place any of these runtime names appears): White Mage **Soul Spurn** (`White_Mage_Soul_Spurn_AOE_obj`, ownership `isMyClient`, ON when its own `purgatory` reads numeric > 0), Exo **Lunar Orbit** (`Exo_Lunar_Orbit_Crescent_Moon_obj`, no ownership field, ON on any instance - session 6 measured that a plain cast creates none), Plague Doctor **Crematus** (`Plague_Doctor_Crematus_Controller_obj`, no ownership field, ON when its own `skillContamination` reads numeric > 0), Butcher **Submerged Knives** (`Butcher_Submerged_Knives_Knifehoarder_obj`, no ownership field, ON on any instance), Prophet **Maelstrom of Frost** (`Prophet_Maelstrom_obj`, ownership `isMyClient`, ON only while its own `destroyTimer` reads **exactly** `-1.000000`), Shaman **Meteor Storm** (`Shaman_Meteor_Storm_Controller_obj`, no ownership field, ON when its own `skillAstroHeated` reads a `VALUE_BOOL` true or numeric > 0 - a plain cast reads `real:0.000000`) and Samurai **Bushido** (`Samurai_Bushido_obj`, ownership `isMyClient`, ON on any own instance - it has no plain form at all, session 9) and Shield Lancer **Counter** (the one `ToggleOnMark::PlayerBuff` row: ON while player buff slot `[104]` is present in `global.playerBuff[1][0]` with its own `buffType` equal to 104 AND the Give No Quarter sub-talent - Counter t301 slot 13, measured live 1 allocated / 0 removed - reads Allocated; without Give No Quarter Counter is a timed buff and the row stays off, counting `subOff=`; session 12).
    - Talent ids are not stored: `FrameCallback` resolves each row's id from its `abilityId` in `global.talentStructMap`, once a second at most, at most one walk per room, and stops once every row is resolved - never in a draw or a hook.
    - Confirmed live 2026-09-20 (session 7): one walk resolved all five rows shipped up to that session (`resolveWalks=1 unresolvedRows=0`, ids 240/358/283/377/430) and the per-row counters charged every ON draw to the row that was actually toggled.
    - While on, `ToggleIndicatorDraw()` runs right after `HhDrawHeadLabels()` inside the existing `DrawHudBuffs` hook (no new hook installed) and re-reads every resolved row every draw, caching nothing.
    - For each row it decides On, it finds that row's slot (`UI_Hud_Talent_obj` instance 0's own `row0` array, the element whose own `talentId` equals the resolved id) and draws D-U13's marker: ten nested single-pixel `draw_rectangle` outline bands in `deepred (140,24,28)`, alpha falling linearly from full at the innermost band to zero at the outermost, saving and restoring `draw_get_colour`/`draw_get_alpha`.
    - The box is **derived** from that slot's own live `navBboxX`/`navBboxY`/`navBboxWidth`/`navBboxHeight` (`x + 2.3`, `y` unchanged, `w - 4.7`, `h - 13.2`) and rounded to whole pixels per Known Limitations item 18 - the accepted `120 x 126 @388,1711` is evidence for one slot at one HUD scale, not a constant.
    - `toggleborder 0` prints `drawn=`/`on=`/`off=`/`unreadable=`/`noHud=`/`noRow0=`/`noTalent=`/`foreign=`/`drawExc=`/`unresolved=` - `noHud`/`noRow0`/`noTalent` are the three meaningfully different reasons `ToggleIndicatorFindSlot` can fail to find the slot (follow-up from the indicator's reviews; replaces a single `noSlot=`), `drawExc` counts a swallowed exception from the marker draw itself, and `unresolved` counts a row skipped because its `abilityId` has not been matched yet.
    - **Every counter on that line is a sum over every shipped row** - the draw visits each row once, so a player with nothing toggled reads `off=` at the row count times the number of draws - and both outputs say so, the line ending `(summed over 8 rows)`.
    - `toggleborder stat` (read-only, stores nothing) prints the same counters plus `enabled=on|off`, a second line with `<abilityId>:talentId=<n|unresolved>` per row, `resolveWalks=` and `unresolvedRows=`, and then **one line per row** naming it by its `abilityId` with that row's own `drawn=`/`on=`/`off=`/`unreadable=`/`unresolved=`/`noSlot=`/`subOff=`/`subUnreadable=` (the last two count draws where a sub-talent-gated row - today only Counter - read its sub-talent as not allocated or unreadable; they appear on the per-row lines only, not in the summed line) - which is what answers "which row was ON" and "which row lost its slot" (`noSlot` is the row-level view of the three HUD-side failures the summed line splits into `noHud`/`noRow0`/`noTalent`).
    - Off by default; panel key `mod_toggle_indicator`.
    - See Known Limitations item 16 for what a plain cast does, which skills are *not* covered, and the exact-equality risk on Maelstrom of Frost.
  - `toggleguard 1` / `toggleguard 0` / `toggleguard stat`: shipped toggle-skill re-cast guard (issue #11, Track A, T1, generalised in phase S).
    - `1` only arms it; `FrameCallback` installs `HookOneScript("TalentUseClass", …)` (`HookTalentUseClass`, both routes) once the setup gate has passed and `HhResolveLocalPlayer` succeeds, checked once a second - the `relicfilter` shape (Known Limitations item 8), so it is safe to send at launch.
    - While on, a `TalentUseClass` call whose caller's own `object_index` (read with `variable_instance_get` and `N1ObjectIndex`, which accepts the `VALUE_REF` this runner returns) equals `asset_get_index("Universal_Double_Cast_obj")` **and** whose first argument is the runtime-resolved talent id of one of the same seven rows the indicator covers (Soul Spurn, Lunar Orbit, Crematus, Submerged Knives, Maelstrom of Frost, Meteor Storm, Bushido) reaches the guard.
    - Six of the seven rows have a toggle sub-talent; **the refusal is gated on that sub-talent being allocated, read at the call** with the talent the call itself named: `global.subTalentMap[<index>]` → `t<talentId>` → `s<NN>` (the slot per row: `s12` Soul Spurn, `s11` Lunar Orbit, `s13` Crematus, `s13` Submerged Knives, `s11` Maelstrom of Frost, `s11` Meteor Storm).
    - **The array index is selected, not assumed**: session 6's measured index 1 is tried first and, if its entry carries no `t<talentId>` struct, the other indices (cap 16) are tried in turn and the first that does carry one answers - the struct's own presence is the positive signal, so an index that turns out to be a character or player slot on another save cannot leave the guard silently inert.
    - Each index is judged on its own (its entry's kind checked before it is read, its own `try`), so one junk entry in front of the real one costs that index and not the walk.
    - A numeric > 0 refuses - the hook returns without calling the original, the co-op puppet's early-return shape.
    - The measured unallocated form (`0.000000`, key present) passes and counts `subOff=`; the global missing, not an array, no index carrying `t<id>`, `s<NN>` absent or non-numeric, or a throw anywhere passes and counts `subUnreadable=`.
    - Everything else passes, and the toggle's own state is still never read (`docs/toggle-skills-research.md`, "Track A design (D-N1)" and "S design").
    - **Bushido (session 9, D-B1) is the seventh row and has no sub-talent at all - a toggle on its own** - so it is refused unconditionally, every time it is the caller and the double-cast proc names it, without ever reading `global.subTalentMap`: feeding a real slot's key space the row's `kToggleNoSubTalent` constant (0) would find no `t<id>` struct there and answer Unreadable, which would pass the proc through - the exact "reports armed and does nothing" shape.
    - Its refusals count in both `refused=` and a separate `baseForm=`.
    - A caller or object that cannot be read passes (fails open) and is counted; an unresolved row is not guarded at all.
    - `toggleguard 0` clears the flag only; the hook stays and passes every call through.
    - `toggleguard 0` and `toggleguard stat` (read-only) print `refused=`/`passed=`/`procSeen=`/`selfUnreadable=`/`objUnresolved=`/`subOff=`/`subUnreadable=`/`baseForm=`/`subIndex=<n|none>` (which `global.subTalentMap` index actually answered, so a moved map and an unallocated sub-talent are never the same silent counter)/`hook=not installed|installed|TABLE-ONLY`, `stat` also `enabled=` and the same per-row `talentId=` line `toggleborder stat` prints; the research build adds `lastProcRet=` (what the last passed proc call returned).
    - Off by default; panel key `mod_toggle_guard`.
    - See Known Limitations item 17.
  - `restartanytime 1` / `restartanytime 0` (or `off`) / `restartanytime stat`: shipped "Restart zone at any time" (issue #8, 1.4.5, off by default; panel key `mod_restart_anytime`).
    - `1` only arms it (`ON` or `ON (armed, applies once you are in-game)`); `FrameCallback` installs `HookOneScript` on `UiSetFocus` (`HookRestartAnytimeSetFocus`, both routes) once the setup gate has passed and `HhResolveLocalPlayer` succeeds, checked once a second - the `toggleguard` shape, so it is safe to send at launch. The install logs `restartanytime: hook installed -> ON`; a `TABLE-ONLY` install (or `UiSetFocus` not found) logs why and turns the mod off for the session, and a later `restartanytime 1` says so instead of reporting ON.
    - While on, each `UiSetFocus` call's first argument is checked at the call: present, readable through `HhUsableInstance` (it arrives as `VALUE_REF`), and its own `uiNodeCallstack` reading the string `PauseRestart` - the Restart button, never identified by position, instance id or `self`. On that button only, `manualDisable` is read and, if it is closed (`true`), written `false` in the kind it was read in (the game's bool stays a bool), before the game's own body runs; `enabled` is never touched. Nothing is restored after the call: the game recomputes the member every frame. The first write logs `restartanytime: first write - …` once per session.
    - `restartanytime 0` clears the flag only; the hook stays and passes every call straight through without reading anything. `0` and `stat` (read-only) print `written=` (gate written open) / `passed=` (Restart's gate was already open) / `otherNode=` (any other node, or no usable argument) / `unreadable=` (the gate member absent, not a bool or real, or the write threw - never written) / `hook=not installed|installed|TABLE-ONLY|FAILED`; `stat` also `enabled=`.
    - See Known Limitations item 22.
  - `skilltimer off|arc|bar|number|fade|stat`: shipped skill-timer countdown (issue #55, 1.4.5, off by default), drawn over a skill's own hotbar slot in one of four looks inside the existing `DrawHudBuffs` hook, reading the game's own timer and changing nothing. Three tiers, checked in this order: **object rows** (`kSkillTimerRows` in `plugin/include/ForgePact/SkillTimerMod.hpp`, measured cast objects whose `destroyTimer` carries the duration, sessions 8 and 10), **buff rows** (`kSkillTimerBuffRows`, session 12: Counter `[104]`, Last Stand `[107]`, Defensive Shout `[9]`, Berserk `[1]`, read from `global.playerBuff[1][0][<buffId>].destroyTimer` with a per-draw `buffType` identity check, so a renumbered id draws nothing and counts `identityMismatch=`), and the **rule tier** (untested cast objects, D-S4). A row whose skill is currently a toggle draws no countdown (`toggleOn=`): Counter draws only while Give No Quarter is NOT allocated, the same sub-talent read the toggle border uses, never cached across draws. First sight latches the full value and a refresh that rises re-latches (Berserk refreshes to 720 per stack; Defensive Shout is re-added to full for ~90 frames after the cast). `skilltimer stat` prints one line per object row and per buff row (`drawn=`/`noBuff=`/`unreadable=`/`identityMismatch=`/`expired=`/`toggleOn=`/`toggleUnreadable=`/`unresolved=`/`noSlot=`/`latched=`/`unlatched=`) plus the rule-tier totals. Live smoke on the ship build (2026-09-22): `counter drawn=1037 toggleOn=838 noSlot=0` with the border's `subOff=1037` (countdown and outline never overlap), `defensiveShout drawn=1125 noSlot=0`; Last Stand and Berserk are not observed live on the ship build. Research and rows: `ForgePact/docs/toggle-skills-research.md` (`### Buff-carried countdown (session 12)`).
  - `autoprospect 1` / `autoprospect 0` (+ `autoprospect stat` in the research build only; `autoprospect` is in `kPlayerCommands`, dispatched from `HandleProspectCommand`): Auto-prospect on insert (issue #9, Stage B; panel key `mod_auto_prospect`, off by default, `build_cmds` emits `autoprospect 1` only when it is on).
    - While on, every item moved into the Prospect Cube's grid - drag or click - is prospected at once by the game's own Prospect handler.
    - The decision is `ForgePact::AutoProspectMod` (`plugin/include/ForgePact/AutoProspectMod.hpp`, game-independent); the adapter in `ModuleMain.cpp` is a hook on `m_MoveItemToGrid` (`UI_Inventory_Grid_obj anon@15345`, through the SDK constant and `HookOneScript`'s two routes, installed once from `FrameCallback` after setup; it only tells the core an insert into the node whose `uiNodeCallstack` names `"ProspectGrid"` happened, and never invokes) plus `AutoProspectTick` in `FrameCallback`, entered only while the mod is on, which re-finds the window, the grid and - only while an insert is pending - the Prospect button (the `UI_Button_Small_obj` linked to the window whose `activationFunc` is a method of `UiAProspectButton`), and invokes the one shape Phase 1 recorded: `script_execute` through `CallBuiltinEx`, the handler's `asset_get_index` value and the button's own `activationArgs` array, `self` = the button, `other` = the window.
    - An insert invokes when the grid's filled count is above the count the core last *settled* (first sight, re-read straight after an invoke, a refused insert, an expired one - lowered by removals, never raised by an unreported fill), because a click-in's cell is filled before the insert closure runs (`contents=6->6`).
    - Replies: `autoprospect: armed - ...` then `autoprospect: hook installed -> ON`; a `TABLE-ONLY` or failed install turns it off (`autoprospect: hook TABLE-ONLY -> OFF: ...`), and `autoprospect 1` then answers `unavailable this session`.
    - Both builds log each refusal once per session (`no-window`, `no-grid`, `unreadable`, `node-changed`, `no-button`, `no-args`, `grid-full` - `holding back - N free cells, needs 6; empty some of the grid`), a failed dispatch once, `autoprospect: first prospect - invoked=… prospected=…` once, and once each the first invoke that dispatched but left the grid unchanged (`autoprospect: the Prospect ran but the grid did not change - invoked=… ran-no-effect=…`) and the first whose effect could not be read (`autoprospect: the Prospect ran but the grid could not be read afterwards - …`).
    - The drag-in fills its cells after the insert closure returns (`contents=0->0`, Phase 3 S1) and the click-in before it; the settled count covers both.
    - `autoprospect stat` prints `StatLine()` (`invoked`, `prospected`, `ran-no-effect`, `unverified`, `failed`, inserts with `coalesced`/`while-invoking`/`elsewhere`/`while-off`, `not-landed`, the refusal counts) and the hook state.
    - The research build also logs, unasked, five **`autoprospect research:`** lines (Stage D, for the ore that came back - `prospected` cannot tell an ore that went back to the bag from one that was prospected): `insert` (from the hook: `frame=`, whether it went into the ProspectGrid, `invoking=`, `self`/`other`, the argument kinds, the grid's filled count and fingerprints at hook time), `decide` (a move-pass decision: the view, the recorded batch before the decision consumed it - `AutoProspectMod::BatchList()`, a copy - and the named cells), `move` (per cell: fingerprint, `itemType`, `itemDefinitionStruct`, CanAdd's return, `route=stack|place|none`, `preferred=` - the new-type route's `GetItemPreferredGrid` return - the Add's or the place's return, clear, final read, outcome), `invoke` (dispatched, the view, the after-read, the new batch, the `inserted` fingerprints, the bag grid's count) and `fate` (the next tick: each inserted fingerprint `gone`/`still`, what `GetItemFromFingerprint(fp, 0)` returns for it now, whether the bag grid `InventoryGrid` holds it, and the bag's gained/lost fingerprints).
    - They are `ApResearch*` functions inside `#ifndef FORGEPACT_RELEASE`, each called from one research-only line of the adapter; the player build has none of them (`test_autoprospect_research_log_is_research_only`).
    - See Known Limitations item 19 and `ForgePact/docs/prospect-window-research.md` § Stage B ship design / § Stage B Phase 3 live procedure.
    - **`bp_ipc\modstate.json`** (both builds, written from the frame callback only when its text changes): `{"schemaVersion":1,"autoprospect":{"enabled","hookBlind","bagPreference","movePass","reason"}}`. The panel reads it (`plugin_mod_state`, `/api/state.pluginMods`) and paints `off (plugin)` with the reason beside a switch the plugin is refusing, and both auto-prospect change handlers re-read it before they toast - so a move pass that shut itself down for the session, or an insert hook that went in table-only, is visible in the panel instead of only in `out.txt` (review of ForgePact #54). The renderer's healthy branches repaint too - the parent label from its own switch, the child through `syncProspectBag` - so the poll clears `off (plugin)` by itself once a new session reports healthy, which is what the refusal's own message promises (follow-up review, ForgePact a604aa7).
- `autoprospect bag 1` / `autoprospect bag 0`: Auto-prospect's sub-option (issue #9, Stage C; panel key `mod_auto_prospect_bag`, nested under `mod_auto_prospect` the way `map_reveal_packs` sits under `map_reveal`; **on by default** in the core and the panel, so `build_cmds` emits `autoprospect bag 0` after `autoprospect 1` only when it is off, and turning the parent on live restates it; `autoprospect 1|0` leaves it alone).
  - With it on, the frame a landed insert is about to be prospected - only the free-cell check left - first moves the previous prospect's batch to the player's materials tab, then prospects in the same frame, so the newest batch stays visible.
  - The batch is what the core's own last invoke produced (round 1): `OnInvoked` records the fingerprints in the grid read straight after the call that were not in the invoking view (both reads share the frame, and `ApReadCells` fills the view's `printList` for each), so nothing the player inserts - an ore included, though it is a material - is in it, with one accepted corner (not observed): a batch stack the player swaps out and drops back in within `kAutoProspectLandFrames` keeps its batch fingerprint, so it goes to the tab rather than being prospected.
  - It is forgotten on first sight of a node (new node, window or grid gone, parent toggled), a removal, or a `not-landed` expiry, and consumed by the pass; a forgotten batch moves nothing.
  - The core returns `MoveMaterials` naming only the batch's cells that the adapter also flagged as materials, one per fingerprint (the item behind each filled cell's `nodeFingerprint`, looked up by the game's own `GetItemFromFingerprint`, with `itemType` equal to the SDK's `HeroSiege::Items::ItemType::Material`; read only on frames with a pending insert, the pass on and a recorded batch); `ApMovePass` then runs the route M7 recorded, per cell, by name through `script_execute` with self = other = the ProspectGrid node: the cell re-read and still holding the viewed fingerprint, `InventoryGridCanAddToStack(1, undefined, item)`, then - when it is truthy (an existing stack) - `InventoryGridAddToStack(1, item)` returning `success == true`, or - when it is falsy, which it is for every material whose type the tab holds no stack of (Stage D, the new-type route the game's own click-move takes, `prospect-window-research.md` § Stage D results) - `GetItemPreferredGrid(1, item)`, whose result must be a plain struct with an array `grid` member (`ApPreferredGrid`), then `GridAddItem(that grid, item, 0, undefined)` returning `success == true` (the same `ApAddSucceeded`), and only then, on the cell still holding the same fingerprint, `InvGridClearItemNode(cell, undefined)` - one clear site for both routes.
  - A new-type material lands in the **main bag grid** (`tabType` 0), where a click puts it, not the materials tab.
  - `g_AutoProspectInvoking` is held across the pass.
  - After it the tick re-reads everything and asks the core again; the landed insert stays landed even when the read is now at or below the settled count.
  - Outcomes, each counted and each non-moved reason logged once per session in both builds (the prospect still runs in every case): `moved` (and `moved-new` when the new-type route placed it), `no-preferred-grid` (a new type whose preferred-grid lookup ran and named no grid of the recorded shape; a lookup that never ran is `move-failed`), `not-placed` (the place ran without `success` and the cell is unchanged), `not-added`, `move-failed`, and `vanished` (the cell lost the material without `success`) or `cell-kept` (success, but the final read still holds it or could not be made) - either of the last two turns the pass off for the session with a line saying so, after which `autoprospect bag 1` answers `bag unavailable this session`.
  - The player build logs `autoprospect: first move to bag - …` once; `autoprospect stat` adds `moved=`, `moved-new=`, `passes=`, the six reason counts (`no-preferred-grid=`, `not-placed=`, `not-added=`, `move-failed=`, `vanished=`, `cell-kept=`; Stage C's count for a has-a-stack "no" is retired, since that "no" is now a route), `batch=N` (the recorded batch's size) and `bag=on|off|off-this-session`.
  - See Known Limitations item 19 and `prospect-window-research.md` § Stage C ship design / § Stage C Phase 3 live procedure.
  - `menulayout` / `menulayout <ObjectName>` (**player build**, in `kPlayerCommands`, dispatched from `HandleMenuLayoutCommand`; read-only): lists every live instance of thirteen candidate menu objects, with its window position, so a tool that drives the game (the hub's `hs-drive`) can click where the game says a button is, or refuse.
    - The listing also reaches UI children of the roots: that is how phase 0 found the save-slot cards (`Choose_Parent_obj`).
    - The hub's `hs_select_character` takes every click point from this listing: `Play local`, save slot N and `PLAY`.
    - See `ForgePact/docs/menu-layout-research.md`.
    - For each of thirteen `hs-game-sdk` object names (the UI node/panel/list-item roots, `UI_Button_obj`, `UI_Button_Small_obj`, `UI_Character_obj`, `UI_Create_Character_obj`, `UI_Main_Menu_obj` and five unparented save/menu objects) it resolves the object by name (`asset_get_index`, confirmed by `object_get_name` round-tripping), walks `instance_number`/`instance_find`, skips an instance id already printed, and reads through the handle `instance_find` returns.
    - Output, exact bytes (the hub's parse contract, pinned by `tests/test_menu_layout_contract.py`): a header `menulayout: room=<Room> gui=<W>x<H> window=<W>x<H> fullscreen=<0|1> view=<x>,<y>,<w>,<h>`; one row per instance, two-space indent, `obj=<Obj> id=<id> gui=<x>,<y> win=<cx>,<cy> bbox=<l>,<t>,<r>,<b> visible=<0|1> sprite=<Sprite|none>`, then whichever of `label`, `name`, `slot`, `index`, `page`, `selected` the instance carries, then always last `text=<to end of line>` (empty when it has none); and a footer `menulayout: listed=<n> absent=<names|none> capped=<0|1>` (200 rows at most; a name that does not resolve is listed in `absent=`).
    - `win` is the instance's GUI position scaled by `window_get_width`/`window_get_height` over `display_get_gui_width`/`display_get_gui_height` and rounded - measured (with `menuprobe`, before this command existed) to map `Play local` to client (336, 534) windowed and (448, 712) fullscreen; `gui`/`bbox`/`view` print one decimal.
    - A failed read prints `<read-failed>` in that field rather than stopping the listing, and no double is formatted with a bare `%f` (Known Limitations item 10).
    - `menulayout <ObjectName>` lists that one object in the same format.
    - Nothing is hooked, performed, called, created, destroyed or written, and nothing of it is on the per-frame path.
    - A player build older than the command answers `command unavailable in player build: menulayout`.
    - First run against the game in phase 0, 2026-09-21, with the dev build: `Play local` was listed at `win=336,534`, and clicks at the listed `Play local` and slot-1 points both worked.
    - The player build's first live run is the hub's L-2 gate.
  - `menuprobe list <Obj>` / `event <Obj> <nth> <type> <number> [Obj2] confirm` / `script <Script> <Obj> <nth> [args ...] confirm` (**research build only**, not in `kPlayerCommands`, dispatched from `HandleMenuProbeCommand`): the character-select instrument; see `ForgePact/docs/character-select-research.md`.
    - `list` is read-only and needs no token: one line per live instance of that object with `nth`, `id`, `x`, `y`, `visible`, `sprite_index`, `image_index` and whichever of `text`, `label`, `action`, `script`, `selected` the instance actually carries, capped at 64, then a count.
    - It is also the **enumeration control** for the other two: a `list` that finds nothing at the main menu means the event and script candidates were *not measured*, not that they failed.
    - Menu-room instances were first shown to enumerate on this runner on 2026-09-21 - `UI_Button_obj` returned 13 live instances at the main menu with the control `Menu_Controller_obj` returning 1 - which closes that as an open question, but the control is still run each session rather than assumed.
    - The control has to be this same command over an object the session has just seen live (`menuprobe list Menu_Controller_obj`, `Profile_Manager_obj` as the fallback): both listings empty measures the instrument rather than the button.
    - The reason is *not* that `citrace dumpobj` reaches an instance by a different path - reviewed 2026-09-21, `CiDumpNamedObject`, `MpResolve` and `MpList` run the same `asset_get_index` / `instance_number` / `instance_find` / `HhResolveInstance` sequence and differ only in how they read an instance once resolved.
    - The reason is that `list` exercises the same *read* path (`variable_instance_get`) the other two subcommands depend on.
    - `event` performs exactly one `event_perform` (or `event_perform_object` when an `<Obj2>` is given) on the chosen instance with it as both `self` and `other`; `script` makes exactly one `CallGameScriptEx` of `gml_Script_<Script>` the same way, numeric arguments as reals, `true`/`false` as bools, anything else as a string.
    - Both refuse with a usage line unless the last token is the literal word `confirm` (the `citrace` precedent: a half-written `cmd.txt` fails closed instead of firing), and both print the object, `nth`, instance `id`, position and the room index **before and after** the call, plus the result or the exception - so "refused", "ran and changed nothing" and "faulted" stay three distinguishable outcomes rather than one.
    - A `performed -> bool:true` proves the builtin ran, never that the event did anything.
    - Every instance is reached by name (`asset_get_index`, `instance_number`, `instance_find`, `HhResolveInstance`), no loop encloses either call and nothing is hooked.
    - Like every ForgePact command these run inside `PollCommands()`, which `FrameCallback` calls every 30 frames once `g_Setup` is set - which is exactly what makes calling `CallBuiltinEx`/`CallGameScriptEx` from them safe, the runtime being between frames and owned by that thread.
    - What the contract test pins is the narrower claim: nothing `menuprobe` adds sits *in* the per-frame path, so nothing of it runs unasked.
    - Expect faults from `script`: every cold call shape measured 2026-09-11 faulted and the process survived each one - what was never tried is a UI-action script with a real button as `self`, which is the only reason the subcommand exists.
  - `prospectprobe grid` / `hook [substr ...]` / `arm [budget=N] [substr ...]` / `watch on|off` / `show` / `reset` / `set <Obj> <nth> <var> <number>` / `override <label> <argIndex> <number> [calls=1] [self=<Obj>] [other=<Obj>] [when=<number>]` / `override clear` / `call window|grid <m_Method> [number ...]` / `resize <cols> <rows> via [window:]<m_Method> [number ...]` / `setat <label> pre|post window|grid <var> <number> [self=<Obj>] [other=<Obj>] [arg<i>=<text>]` / `setat clear` / `backing on|off` / `backing dump` / `backing idcheck` / `contents` / `button` / `press show` / `press <route> <argsrc> [self=found|captured] confirm` / `grids` / `cell <grid> <row> <col>` / `move <self> <callable> [arg ...] [other=<sel>] [member=<name>] [bag=<k|text>] confirm` (an `arg` may be `itemfp:<grid>,<r>,<c>`) / `stackmove <row> <col> [a0=<member>] confirm` / `stackmove clear <row> <col> confirm` (**research build only**, not in `kPlayerCommands`, dispatched from `HandleProspectCommand`): the bigger-prospect-window (issue #9) Phase 0 instrument, plus the Stage B Phase 1 (auto-prospect) additions; see `ForgePact/docs/prospect-window-research.md`.
    - **Stage B Phase 1 additions (§ Stage B Phase 1 live procedure):**
    - `prospectprobe contents` (hook-free) prints the ProspectGrid's cell counts (`filled=`/`empty=`), the filled columns per row and the distinct `nodeFingerprint` values, and says `unreadable` rather than printing a failed read as an empty grid.
    - `prospectprobe button` (hook-free) lists every `UI_Button_Small_obj` with its links to the open window, its handler variables (`index-match=`/`method-index-match=`) and any array matching the captured argument, then `chosen=@id` / `none` / `ambiguous (N)`, and `captured-self=@id same|DIFFERENT` once a press was captured - the control on the finder.
    - A button **qualifies** only when it is linked to the open window **and** one of its variables is the handler itself (a method value whose `method_get_index` is the handler's index, or one resolving to the handler's row; a plain number equal to the index is printed as a lead and never counted), and `chosen=` needs exactly one qualifying button.
    - The first Phase 1 build chose by the window link alone and printed `ambiguous (3)` live, because all three small buttons link to the window through `masterUi`/`parent` and only the Prospect button carries the handler (`activationFunc`); `press ... self=found` uses the same finder.
    - `prospectprobe press show` reports the game's own last `UiAProspectButton` call (`self`, `other`, the argument, rooted through the research global `__pp_press_arg` so the kept copy stays alive).
    - `prospectprobe press <route> <argsrc> [self=found|captured] confirm` makes **one** by-name invoke of the Prospect handler, `self` = the button and `other` = the window (routes `exec-index` / `exec-var:<var>` / `scriptex`; argument sources `captured` / `copy` / `button:<var>` / `empty`).
    - Every refusal prints `no call made` and comes before any call: no `confirm`, a pending `override`/`setat`, a `UiAProspectButton` row that is not detoured (run `prospectprobe hook` first - without it `invoked=` could not be proven), no open window, a missing or ambiguous button, an unavailable argument source, or a grid with no filled cell.
    - The outcome line carries `st=`, `res=`, `invoked=` (the `UiAProspectButton` row's count across the call), `inner=` (the `___struct___123@UiAProspectButton` row's), `self=`, `other=`, `route=` and `args=`, then the contents before and after and a verdict decided by the `invoked=` count, never by `st=` alone: `prospected (filled K->K', ...)` (grid changed and the handler entered), `grid changed but handler not entered (invoked=NO)`, `handler entered, grid unchanged`, `dispatched but handler not entered (invoked=NO)` or `not dispatched`.
    - A shape qualifies for shipping only with `prospected`, `invoked=yes`, `inner=yes`, `self=found`, an argument source of `button:<var>` or `empty`, and the item seen turning into materials.
    - Phase 1 is complete (2026-09-18): the re-run chose the button by its handler variable (`chosen=@261471`) and `press exec-index button:activationArgs self=found confirm` qualified - the shape `autoprospect` ships.
    - `prospectprobe hook` detours the same address as `autoprospect`'s hook; measured once on c27cdad, `prospectprobe hook` after `autoprospect 1` refused that one row before patching (`142 detoured, 1 failed`) and left the auto-prospect detour in place - whether auto-prospect still sees inserts afterwards is Stage D's N0 control (Known Limitations item 19).
    - **Phase 0c additions (`prospectprobe backing`) - read-only, no invoke:** four getter rows (`GetProfileInventoryData`, `GetPlayerItemOwner`, `GetInventoryArray`, `GetPlayerProfileObj`; table 91 rows) are detoured and **never called by the instrument** - a blind `callnum GetProfileInventoryData` without the window as `self` crashed the game in Phase 0b.
    - `backing on` (off by default; `reset` turns it off and releases what it kept, and `on` itself also releases every earlier capture and zeroes the counters, so running it again mid-session discards them) keeps the value each getter's own call returned, after the game's function ran: **the first 8 calls per getter whose `self` is the `UI_Prospect_obj` window**, each with that window's `@id`, never overwritten (the window holds two grids and every open calls the getters again, so the last call is not necessarily the one the ProspectGrid was built from, and a ring would evict the build-time returns first); later window calls are counted as not kept, and any not kept rules out `copy`.
    - The latest call from any other `self` goes in a separate slot.
    - An `RValue` copy holds a counted reference only for an array, so each kept value is also rooted through a research global (`__pp_backing_<getter>_window<k>` / `_other`), set before the slot is updated and cleared on release.
    - The first 6 calls per getter are logged with `self` and a shallow shape; **nothing is serialised inside the getter's call** (a cyclic struct would overflow `json_stringify` there).
    - `backing off` stops capturing and keeps the values.
    - `backing dump` prints the open window's `@id`, the live `nodeGrid` and every kept return (marked `(the open window)`, `(a window that is not open now)` or `(not the window)`), writes the json files - each only after a depth-capped walk of the value finished without the cap, else `not written (walk ...)` - and walks each kept value for a `nodeGrid`-shaped sub-array, counting `non-empty nodeGrid cells agreeing K/N` (only non-empty cells; objects compared by identity, not by how they print; `nodeGrid holds no item - nothing to compare` on an empty grid).
    - **Structural agreement is a lead only and never picks a gate branch** - a copy agrees by construction.
    - `backing idcheck` runs its **positive control first** on arrays it builds itself (a kept reference must see a later write, and the scanner must find the sentinel through it but not in a separate array; otherwise `not observed (stash does not track live arrays on this runner)` and nothing touches the game), refuses with no write when nothing was captured, no open window has a readable `@id`, **no kept window return came from the open window** (run it right after opening, before any item is moved), there is no node, or there is **no empty cell** (`undefined` or 0 - an item is never written over), then writes one sentinel into that empty `nodeGrid` cell, confirms it landed by a fresh read, walks **every** kept return of every getter for it, **restores the cell and reads it back before printing the verdict**.
    - Its `kept returns from the open window` line carries the `window returns dropped` count per getter, and every incomplete walk is named with its reason (e.g. `root VALUE_REF ..., nothing to walk`).
    - Verdicts, in order: `reference-identical (via <getter> <slot> call #n ... self=... at <path>; sentinel in N calls of <getter>: #a #b - outlived one call)` when the sentinel is found in the kept returns of **two distinct calls of the same profile getter** (`GetProfileInventoryData` or `GetPlayerProfileObj` - the only identity the decision gate reads as save-backed) at a path through no UI-looking field - the decided line's own `at <path>` list belongs to one kept return, the one its `via` clause names, and lists every path on which the sentinel was found in that return, not every path across the deciding calls; it may still contain a UI-looking one, because the branch turns on how many calls were clean, not on what the line prints.
    - The `ui`/`window`/`node`/`panel`/`menu` test is a name rule standing in for `reached through the window's own state`, not a measurement: it can only demote a would-be save-backed identity to a lead, never promote one, and a decided save-backed still rests on the two-call rule plus R7, not on the name rule.
    - Two calls prove the array outlives one call, not that it is saved data, and an identity reached only through the window's own state may be the window's own array; `reference-identical (via <getter> <slot> call #n ... self=... at <path>; sentinel in N calls of <getter>: #a #b but only M of them reached on a path with no UI-looking field, fewer than 2 - reached through a UI-looking field (<member>) - the array may be the window's own, a lead that decides no gate branch)` when fewer than two of them reached it on a path with no UI-looking field (a struct member on the path named `ui`-prefixed or containing `window`/`node`/`panel`/`menu`, case-insensitive); `reference-identical (via <getter> <slot> call #n ... self=... at <path>; one call only - the getter may build this array per call, a lead that decides no gate branch)` when only **one** distinct call of a profile getter holds it - a single return proves only that `nodeGrid` is that call's own array, not that the array outlives the call - naming every profile getter that hit; `reference-identical (via ...; not a profile getter ...)` when only a `GetPlayerItemOwner`/`GetInventoryArray` return does (a lead); `not observed (scan incomplete ...)`; `not observed (N window returns not kept ...)`; and `copy` only when every walk completed, no window return was dropped and none holds it - so a getter that returns an instance makes `copy` unreachable.
    - A walk is complete only if nothing was left unwalked: any value that is not a number, bool, string, `undefined`, `null` or unset and not a walkable array or struct - an instance reference (`VALUE_REF`), a method value, a pointer - counts as unwalked.
    - A `ds_*` id held as a plain number is indistinguishable from a number and is not followed.
    - **Phase 0b additions:**
    - `prospectprobe grid` is hook-free - it finds the ProspectGrid node as the `UI_Inventory_Grid_obj` whose `uiNodeCallstack` names `"ProspectGrid"` (object indices resolved through the SDK names and `asset_get_index`, never a literal), prints `grid=@<id> w= h= rows= cols0= cell= bbox= scale=` (a missing variable prints `?`, `grid=none` when there is no node), then every live-window variable equal to 9 or 6 and every `m_*` method on the window and the node with the closure it resolves to.
    - `watch on|off` (off by default, off after `reset`) makes each **logged** call - same budget and selection as its log line, never on the frame path - append `grid-pre=<snapshot>` and log `grid-post=<snapshot> same|CHANGED|UNREADABLE contents=<K>-><K'>` after the game's function returns (`contents=` is the ProspectGrid's filled count before and after the game's function, a Stage B Phase 1 addition; `UNREADABLE` when either read failed, so two failed reads never print `same`; `same (no node)` when both read `none`, which also covers a node that has not set `uiNodeCallstack` yet, so it brackets nothing), which is how the call that builds `nodeGrid` is bracketed when no argument carries the size.
    - `call` invokes a method value stored on the live window or node through `script_execute` by name (`CallBuiltinEx`, the instance as `self`/`other`), refusing with no call made while an `override` or `setat` is pending (it would fire inside the invoke and rewrite what the method received), or when there is no instance, no such variable, or a value that is not a method value (an unresolvable method value is still invoked), and prints the resolution, a snapshot before and after, and **`invoked=`**: `script_execute` succeeding proves only the dispatch, so the closure's own row in the probe table is counted across the invoke - `invoked=yes (<label> +N)` / `invoked=NO (<label> +0)`, or `invoked=unproven (…)` when that row is not detoured or the closure has no row - together with `self=` and `args=(…)`, what was supplied.
    - **`prospectprobe resize` requires `via`** - a bare size write crashed the node's `Draw_64` in Phase 0a (R5b: `nodeGrid` does not follow the write) - takes trailing numeric arguments for the method as `call` does, and does the write, the named builder call and the check in one handler, so no Draw runs between them: refusals (an `override` or `setat` pending, no node, no such method value, sizes missing or not numeric) come before any write; `nodeGrid` is then measured over every row, and unless every row now measures the requested columns with the requested row count the sizes are written back before it returns - capped per axis at what the store still covers, with `restore unsafe` when that is below vanilla (close the window) - as `reverted (…)`; else `kept (…)`; a method that replaced the node prints `rebuilt (…)` with the new node's shape against the request, or `destroyed (…)`; `kept` and `rebuilt` also print `size=` (`nodeGridWidth`x`nodeGridHeight` read after the call) and `size exceeds store` when that is wider or taller than `nodeGrid` covers.
    - Every outcome line carries `probe=shrink|grow|same|mixed`, `invoked=`, `self=` and `args=`, and a `reverted` counts toward H3 only on a grow, with `invoked=yes` and the call shape L5 logged for the game's own call of that row - otherwise it is `not observed`.
    - A shrink's `reverted` never counts: GML's element assignment grows an array and never truncates it, so an assignment builder answers `resize 8 5` with an unchanged store.
    - The live procedure shrinks every method first (`resize 8 5`), then grows (`resize 18 6`) every method whose shrink printed `kept` and every method whose shrink printed `reverted` with `invoked=yes` and an unchanged store.
    - **`prospectprobe setat`** is a one-shot write at a hook point: it refuses a label that is not a row, a row not detoured (`hook it first`) and a `when=` selector; on the next call of the row in that phase that matches `self=`/`other=`/`arg<i>=<text>` (argument `i`'s printed value contains the text, e.g. `arg4=ProspectGrid`), it writes one existing numeric variable of the window or the node (the `set` checks, read back) and logs the call's `self`/`other`/arguments; a non-matching call, a missing target or a missing/non-numeric variable is `not applied (…)` (budgeted, counted in `show`) and the write stays pending.
    - `hook` native-detours (`MmCreateHook`) every candidate from that doc's static search - the prospect family, the 45 Create-event closures of the window, its grid node, their parents and siblings (re-derived from the regenerated SDK; the four read off the live instances in Phase 0a - `UI_Prospect_obj anon@1065/2806/3657` and `UI_Inventory_Grid_obj anon@36159` - must print `detoured` or the session stops, and the rest are recorded; `detoured` proves only that a name resolved, and a count on a closure row is controlled once `call`/`resize via` printed `invoked=yes` for it), the `UiFuncs` framework and the inventory-grid family - plus `CheckPlayerInteraction` as the control and `PlayerMouseAction` as a candidate (its one earlier native measurement read 0, so it proves nothing about the instrument); each address is refused before hooking unless it is executable code inside `Hero_Siege.exe` (`AddrIsExecutableInModule`), which also refuses an entry a table hook already swapped for a plugin detour; substrings restrict the set to bisect a crash; it prints `detoured <label> at exe+0x…` / `not found st=…` / `refused (<why>)` per row and `N detoured, M failed`.
    - Do not run `citrace nativetrace` in the same session: it detours two of the same addresses.
    - `arm` zeroes the counters and logs the next `budget` calls (default 6, 1..5000, anything else refused and nothing armed) of each selected row - every row except the `CheckPlayerInteraction` control when no substring is given, else only rows whose label contains one - (`self`, `other`, each argument; a `self` without a numeric `object_index`, such as a struct constructor's, prints as `(not an instance: …)` and is never handed to `object_get_name`).
    - `show` prints `calls` and `since` per row and, while armed, `logged=L` plus `UNLOGGED=K (budget spent - not observed)` for a row that made more calls than it logged, or `UNLOGGED=<calls> (not selected - not observed)` for a row the last `arm` left out that fired anyway - the research doc's decision rule records such a row as `not observed (budget spent)` (by design, too, for a row that exceeds the 5000 maximum on one open), and H3 requires R2-window, R4' and R9 all measured with every row that fired fully logged (a row fully logged in an earlier pass keeps that pass); a pending override shows its `left` and `notApplied` counts; its last line, `CheckPlayerInteraction: calls=N`, is the control, and `0` voids every row above.
    - `reset` zeroes and disarms.
    - **`set` is one of two writes:** it refuses an unknown object (including an asset name that is not an object, via `object_exists`), an `nth` outside `instance_number`, a variable `variable_instance_exists` denies (it never creates one - except the fixed built-ins `x`, `y`, `depth`, `visible`, `image_xscale`, `image_yscale`, `image_alpha`, accepted either way because whether that builtin answers true for a built-in is unmeasured on this runner, so the output prints `exists=`), and a current value that is not a finite real/int32/int64 - each with no write made; otherwise it writes, reads back and prints `was=… now=… (readback ok|MISMATCH)`.
    - The instance goes through with whatever kind `instance_find` returns.
    - **`override` is the other:** for the next `calls` calls of an already-detoured row (`hook it first` otherwise) it replaces argument `argIndex` when that argument exists, is numeric and the call matches every selector given (`self=`/`other=`: the object name alone - `self=UI_Prospect_obj`, not the `#object_index@id` form the log prints - which a struct never matches; `when=`: the argument currently equals that number), logging `was`/`now` together with the call's own `self`, `other` and every argument, so the live procedure can confirm it landed on the R4' call - same object and `#object_index` on `self`/`other` with `@id` ignored (a reopen re-runs Create, so the right call always has a new id), the other numeric arguments equal except instance ids or handles - and records the drawn-grid observation beside that verdict every time (a mismatch is `not observed (override landed elsewhere; grid <changed|unchanged>)`, never R5a = no); a missing or non-numeric argument or a failed selector is logged `not applied (<reason>)`, counted as `notApplied`, and does not use up the count.
    - Labels may contain a space (`UI_Prospect_obj anon@2806`).
    - **Stage C additions (materials to the bag, research doc § Stage C):**
    - `prospectprobe grids` (hook-free) lists every `UI_Inventory_Grid_obj` as `bag:<k>` with its `uiNodeCallstack`; `cell <grid> <row> <col>` (hook-free, read-only) dumps one cell; `move <self> <callable> [arg ...] [other=<sel>] [member=<name>] [bag=<k|text>] confirm` is one by-name `script_execute` invoke with both grids read around it.
    - A grid cell holds only a `nodeFingerprint`, no item instance, so `move` also takes **`itemfp:<grid>,<r>,<c>`**: the item the game's own `GetItemFromFingerprint(fp, 0)` returns for that cell, called by SDK name (the one game call a selector makes, a lookup), with the item's `itemType` printed against `HeroSiege::Items::ItemType::Material`.
    - **`prospectprobe stackmove <row> <col> confirm`** runs the game's own click-move of one ProspectGrid material as one command, self = the ProspectGrid: the item from the fingerprint, `InventoryGridCanAddToStack(1, undefined, item)`, `InventoryGridAddToStack(1, item)` only when CanAdd's own body ran and returned true, and `InvGridClearItemNode(cell, undefined)` only when the Add's own body ran and the re-read cell still holds the same fingerprint.
    - All three rows must be detoured (`prospectprobe hook` first) and every refusal before the lookup says `no call made`; the verdict is `moved`, `added-but-cell-kept`, `not dispatched`, `refused` or `POSSIBLE LOSS`, and since the materials tab is not a grid node, the tab's count is checked by eye.
    - **Stage D additions (a material whose type has no stack in the tab yet, and the ore that came back - research doc § Stage D):** every call a row logs now also prints **`prospectprobe <label> #n ret=<value>`** - the game function's return, shallowly, whether or not `watch` is on and within the same budget as the call line - with an array printed as `array len=N id=0x…` (its length and the runtime's own array pointer as an identity token), and the call line gains an `ids:` segment naming each array argument the same way, so one hand move can show whether `GridAddItem`'s first argument is the array `GetItemPreferredGrid` returned.
    - `stackmove` is now **`stackmove <row> <col> [a0=<member>] confirm`**: all five rows it may call (`InventoryGridCanAddToStack`, `InventoryGridAddToStack`, `InvGridClearItemNode`, `GetItemPreferredGrid`, `GridAddItem`) must be detoured before anything is called; a truthy CanAdd takes the existing-stack route unchanged, and a falsy one - a type with no stack yet, which it refused before - takes the new-type route the c27cdad click-move showed: `GetItemPreferredGrid(1, item)` (return printed), its return handed on as `GridAddItem`'s first argument (an array as it is; a struct only as the member `a0=` names, and without `a0=` it prints the members and stops with `no call made to GridAddItem (give a0=<member>)`; anything else stops), then `GridAddItem(a0, item, 0, undefined)` (return printed), and the clear only on a success signal - a struct whose `success` is true, or a plain `true`.
    - Without the signal nothing is cleared and the verdict is `placed-unconfirmed (ret=…) - the cell is kept; check the tab by eye`; if the tab gained it by eye, **`prospectprobe stackmove clear <row> <col> confirm`** runs `InvGridClearItemNode(cell, undefined)` on that one cell (clear row detoured, every refusal before the call) so the session carries no duplicate.
    - No `prospectsize` command exists yet.

- Research-build-only commands (not in `kPlayerCommands`; the player build answers `command unavailable`):
  - `tgprobe hook [substr…]` / `show` / `reset` / `verbose on|off` / `slots` / `buffs` / `abilities` / `vars <Obj|global>` / `snap <Obj|global>` / `diff` / `room`: the toggle-skills research instrument (issue #11).
    - `hook` attaches a native detour to every candidate script and object event in one go and prints `N native, P via hook, B blocked, F not found`; the rows ForgePact's own installers already hold (`DrawHudBuffs`, `BuffAdd`, and `TalentUse` if co-op rendering ran first) are counted from a research-only note at the top of that hook body instead, and a row nothing can reach prints `calls=n/a`, never `0`.
    - Since T1 the `TalentUseClass` row is bound to the re-cast guard's hook: once `toggleguard 1` has installed it, the row is counted via `HookTalentUseClass` (`TalentUseClass: via HookTalentUseClass (native)`, refused calls included, since the note runs before the guard decides).
    - **`toggleguard 1` (and its `HOOK INSTALLED on TalentUseClass` line) must precede `tgprobe hook` in a session** - the other order leaves the probe's own native detour on the game body, which the guard's install would then patch a second time.
    - `not found` on an object-event row means the name did not resolve, not that the event is absent; `Player_obj` `Step_0` is the event rows' control.
    - `show` ends with `firstHud=`, the live Soul Spurn / ability instance counts taken on the first draw after the room key changed.
    - Run no `citrace` command and do not turn co-op rendering on in the same session.
    - `tgprobe spurn` / `spurn log on|off` / `spurn as foreign` / `spurn slots` / `spurn fields` / `mark <x> <y> <w> <h>|off` (issue #11, Track B, P1b): samples the production toggle-indicator read through `ToggleIndicatorRead` (row 0's alias, research-only since phase S's review, wrapping the shipped `ToggleIndicatorReadRow`) on every `DrawHudBuffs` draw and reports `n=`/`mine=`/`others=`/`unattributed=`/`state=` plus running `samples=`/`on=`/`off=`/`unreadable=`/`maxN=`/`transitions=`/`lastTransitionFrame=` counters and the marker-required counters `markedOn=`/`markedOff=`/`markedUnreadable=`.
    - Ownership is read from each AOE instance's own `isMyClient`, not a local player lookup (session 3 measured `Player_obj` has no `playerNumber`); `spurn as foreign` is the non-mutating negative control that re-interprets every own instance as foreign without writing anything; `spurn slots` prints every `UI_Hud_Talent_obj` `row0`/`row1`/`playerSlot.bind_skill`/`global.mySkills` entry whose value is talent 240, read-only; `spurn fields` prints the latched per-appearance snapshot (`isMyClient`/`playerNumber`/`targetNumber`/`purgatory`/`purgatoryTimer`/`destroyTimer`), taken on the appearance's first draw and refreshed on every draw while it is present; `mark` draws a static outline rectangle at GUI coordinates to find which candidate slot rectangle sits on Soul Spurn's button, saving and restoring `draw_get_colour`/`draw_get_alpha`.
    - `tgprobe sprite <SpriteName> [talentId|centre]|off|gold|style soft|halo|gradient|pulse|arc|bar|number|fade [talentId]|list|gallery [cols]|layer hud|buffs|scale [f]|colour [name|r g b]|box tuned|bbox|quad on|off|alpha [min] [max]|frac [f]|textoffset [dx] [dy]|textalpha [a]|textcolour [name|r g b|off]|font [name|index|off|list]` (issue #11, R rounds 3-10; `arc`/`bar`/`number`/`fade`, `frac`, the `[talentId]` on `style`, and `textoffset`/`textalpha`/`textcolour`/`font` are issue #55's countdown-look follow-up rounds): a look-only probe for whether a game sprite (or a look ForgePact draws itself) could replace the gold rectangle - resolves `<SpriteName>` by name (`asset_get_index`, `unresolved` and nothing stored on a negative index) and draws it scaled with `draw_sprite_ext` at the active layer, `scale` and `colour`, animating (a shared time base) when the sprite has more than one frame; `[talentId]` draws over that talent's hotbar slot (default Soul Spurn), `centre` draws one large fixed-size copy in the screen's middle instead (not affected by `scale`/`colour`); `gold` draws T1's three-rectangle gold look over the hotbar slot through the same probe path so it can be flipped against a candidate without arming `toggleborder` - it was the shipped look when the probe was built, and since D-U11/D-U13 it is the superseded baseline, not what ships; `off` stops drawing and prints `draws=`/`drawExc=`/`colour=`/`layer=`.
    - **Both layers measured (2026-09-20) to sit under the button's own art**: `buffs` (end of `DrawHudBuffs`) and `hud` (the existing `DrawHud` candidate row's own detour, `TgProbeDetourBody` - no new hook, the same single resolver every row already goes through, requires that row attached separately via `tgprobe hook`) both left two named candidates invisible while `gold` stayed visible only because its `navBbox` is bigger than the icon; the talent slot's own `Draw_0`/`Draw_64` event, where the button actually paints, reports `not found` to this build's object-event hook path - not reached from either draw site this build's probe can attach to.
    - **`scale [f]`** (round 5, default `1.0`, clamped `0.25..4.0`) is the resulting "surround" route: inflates the box `sprite`/`gold`/`style` draw into, centred on the slot, so a candidate reads around the icon instead of under it (no argument reports the current value) - `gradient` needed the same treatment (invisible at `scale 1.0`, its faded edge under the icon; visible and liked at `1.6`).
    - **`style soft|halo|gradient|pulse`** (round 6) draws a procedural look instead of a sprite - `soft` a 10-band alpha-ramped outline, `halo` a radial glow (`draw_ellipse_colour`), `gradient` nested filled rectangles (`draw_rectangle_colour`), `pulse` = `soft` with a slow sine-modulated alpha (period printed as `period=1.5s (90 frames)`); `list` also names these four.
    - **D-U11 (author, 2026-09-20): the shipped marker is red, not gold** - "that's how aura is indicated as working" in the game's own HUD, superseding D-U1's gold/3px; live candidates to judge in red: `soft` at `scale 1.0`, `gradient` at `1.6`, and `Talent_Aura_Frame_spr` at `1.4`; rejected on looks: `halo`, `pulse` ("too distracting"), `Skill_Frames_spr`, the flat rectangle.
    - **`colour [name|r g b]`** (round 8, default `gold`, unchanged until asked) is shared by every `style`, `sprite gold` and `tgprobe mark`; presets `gold`, `red` (a deep warm crimson near `Talent_Aura_Frame_spr`'s own tint, not `255,0,0` - the author's own steer), `brightred`/`deepred` either side of it, or a raw `r g b` triple - confirmation lines print the full `colour=name(r,g,b)`, not only the name; never tints a named sprite's own art.
    - **D-U12 (author, round 9): the accepted marker geometry for Soul Spurn's slot at this HUD scale is `388, 1711, 120 x 126`** (integer pixels, D-U11's rule), superseding an earlier, since-withdrawn `385, 1712, 125 x 125` - the shipped code derives the box from the slot's own `navBbox` (`x + ~2.3`, `y` unchanged, `w - ~4.7`, `h - ~13.2`, rounded), never hardcodes these numbers.
    - **Colour verdict (round 9): the author prefers `deepred (140,24,28)` for both `gradient` and `soft`** (having compared `red`/`brightred` on both); `soft` in `deepred` is the current front-runner overall.
    - **Round 10 decisions: `soft` is the chosen look; `gradient` is OUT of consideration entirely** - seen at alpha floors `25`, `100` and `60` (all `deepred` at `scale 1.6`), floor `100` judged "too heavy" and floor `60` given no verdict before the style was dropped; neither `halo`, `pulse` nor `gradient` remain live candidates.
    - **`box tuned|bbox`** (round 10, default `tuned`) is which box `sprite <Name>`, `gold` and every `style` draw into before `scale`, and what their `box=` readout reports: `tuned` is D-U12's derived box (`x + 2.3`, `y` unchanged, `w - 4.7`, `h - 13.2` off the slot's own live `navBbox`, rounded to whole pixels both before and after `scale`) - the shape the author actually tuned the look against, generalised from round 9's D-U12 finding rather than repeated as a one-off constant; `bbox` is the slot's raw `navBbox`, kept for side-by-side comparison.
    - Round 9 shipped every style/gold/named draw against the raw bbox even though D-U12 had already superseded it for the marker geometry itself - this round wires the tuned box in as the default so what a tester judges is the real shape; confirmation lines print the active kind (`box=tuned 120x126@388,1711`).
    - **`quad on|off`** (round 9, corrected round 10, default off) - "inside out", the author's own word.
    - Round 9's build (four *whole-sprite* copies, one scaled into each box quadrant) was rejected on sight as the wrong construction.
    - The fix instead splits the SOURCE sprite into its own four quadrants (`draw_sprite_part_ext`, new to this probe, reachability unconfirmed until a live `quad on` run) and rotates each 180 degrees about its own centre back into the matching destination quadrant - so a quadrant's inner corner ends up at the box's outer corner and the result stays a square, "the sprite's inner edges become its outer edges" (the author's alternative description - a diagonal split into four triangles, each flipped once vertically and once horizontally - was not built this round, since the source-rectangle route was preferred and attempted first); applies to `sprite <Name>`/`centre`, not `gold`/`style`/`gallery`.
    - **`alpha [min] [max]`** (round 9) is the floor/ceiling `soft`/`gradient`'s fade remaps between, replacing `0` as the floor (`gradient` "blends too well with the background" at `0`, the author's own words); `max` defaults to each style's own existing centre alpha, so leaving `alpha` unset reproduces both styles' pre-round-9 look exactly; accepts `0..255` or `0..1`.
    - `gallery [cols]` draws every named candidate plus a gold cell at once in a fixed grid away from the HUD - round 6 dropped its per-cell name label after one displaced the icon in a live session (cause not diagnosed); the index→name mapping goes to the log only, and the gallery itself is **not a trustworthy comparison** (a candidate visible over the button has read blank there) - `sprite <Name>` over the hotbar slot is the one to trust.
    - No candidate is confirmed to be the game's own aura-active visual, and no shipped draw changes.
    - **Issue #55 countdown-look follow-up (live-session capture `.claude/workorders/issue-55-live-session-2026-09-20-capture.md`):** the session found `number` drawn `draws=16890 drawExc=0` and never seen (it drew at the box's own centre, under the talent icon's own art - `draw_text` reachability at that draw site is **untested, not negative**) and `bar` leaving a visible stub at `frac 0.0` (the rectangle degenerates to zero width and the runtime still filled it).
    - This round adds settable placement/style controls for `number` and fixes both: `tgprobe sprite textoffset [dx] [dy]` (default `0,2` - `bar`'s own proven-visible gap) anchors `number` to the box's BOTTOM edge, centred horizontally, instead of its centre; `tgprobe sprite textalpha [a]` (0..255 or 0..1, default fully opaque) is `number`'s own flat opacity, independent of the band-ramp `alpha [min] [max]`; `tgprobe sprite textcolour [name|r g b|off]` (alias `textcolor`) is `number`'s own colour, defaulting to "follow the shared `colour`" so nothing changes until a tester asks; `tgprobe sprite font [name|index|off|list]` resolves a font by name at draw time exactly like the shipped `hhlabelfont`/`HhDrawHeadLabels` pair (`asset_get_index`, a numeric fallback, applied only when `>= 0`) - `font list` enumerates the runtime's own font indices (`font_exists`/`font_get_name`, each checked for existence through `CallBuiltinEx`'s status rather than assumed - `font_get_name` only ever against an index already confirmed real, never the bare literal `0.0`) with `draw_get_font`'s current value as a positive control, since no font asset name exists anywhere in this checkout, and its ten inferred `_fnt`-suffixed fallback candidates are printed with an explicit "unconfirmed" disclaimer so an all-unresolved run cannot be misread as "the runtime has no fonts." `tgprobe sprite style <name> [talentId]` now takes an optional trailing talent id (falling back to Soul Spurn, 240 when omitted; refused by name, through the shared `ParseFiniteNumber`, when given but unparseable, rather than silently substituting the default) so a look can be judged on any character, not only one carrying that exact talent.
    - `TgProbeSpriteDrawBar` now draws nothing when its width is below one pixel (the guard is on the drawn width, never on `fraction == 0.0` alone, so a sub-pixel remainder disappears too) - `number` still prints a legible `0%` at zero.
    - `tgprobe sprite frac [f]` now also refuses a token whose numeric prefix does not cover the whole token (`frac 0.5x`, `frac 1abc`) and a non-finite result (`frac nan`), reusing the file's shared `ParseFiniteNumber` helper; the "did not parse as a number" refusal for a token with no numeric prefix at all already shipped in an earlier round and is unchanged.
    - `tgprobe talents [substr|tags]` / `tgprobe tgl` / `tgl on|off` / `tgl add/list/clear/slots/fields/sub/timer` (issue #11, the generalisation to every toggle skill, session 6): `talents` walks `global.talentStructMap` and prints each talent id's `abilityId`, `abilityAura`, `abilityDuration`, `abilityCooldown`, `abilityLength` and `abilityTags` (filtered by `abilityId` substring, or `tags` for a count per tag id) and maps every table row's `abilityId` to its talent id; `tgl` is a runtime table of toggle-skill candidates (cap 16) prefilled with the seven rows of the research doc's static candidate table.
    - Its sampler is **off by default** and makes no builtin call until `tgl on` (session 6's first command; `tgl off`/`0` stops it, `list` prints `sampler=on|off`), so it costs other research sessions on the same DLL nothing; while on, every row is read on every `DrawHudBuffs` draw through the shipped read's shape with the object, marker, ownership and timer as parameters, and row 0 (Soul Spurn) also through `ToggleIndicatorRead` itself, counted as `agree=`/`disagree=` (the proof that the two reads are the same read).
    - `tgl add <abilityId> <ObjectName> [marker|none] [timer|none] [ownership|none] [sNN]` resolves the object by name and stores nothing (`unresolved`) when it does not; `fields [row]` keeps the first and last scalar snapshot of each appearance, taken on the own instance the row's read used (not instance 0), `last` retaken at most once every 30 draws, and prints `fields: no own instance` rather than another instance's fields (to find a row's marker field); `sub` prints `global.subTalentMap`'s entries per array index per row (to find the sub-talent slot); `slots` prints every hotbar slot's `talentId` and rectangle; `timer` prints the row's timer field over the current appearance (`first=`/`last=`/`min=`/`max=`/`unreadable=`/`atPredicted=`), an instrument for finding how a toggle is told from a plain cast, never a border input.
    - Full reference and the live procedure: `ForgePact/docs/toggle-skills-research.md`.
  - `tgprobe deep snap <name> [scope…] [talent=…]` / `deep diff <a> <b> [substr]` / `deep flip <base> <on> <off>` / `deep find <substr> [name]` / `deep get <path>` / `deep census` / `deep selftest` / `deep drop <name>`: the non-scalar read for where a toggle's ON state lives (issue #11, Q3).
    - Command-time only, no hook: named snapshots walk arrays, structs, ds_maps and ds_lists (depth 3, 200 elements per container, 250,000 leaves **per scope**, each scope line printing its own `truncated=`) under seven scopes — `Player_obj` (plus `alarm[]`), `global.talentStructMap{id}`, `Controller_obj`, `UI_Hud_Talent_obj`, every `Skill_Controller_obj`, every global, and an `instance_number` census — each member read on its own and the coverage printed as `names= read= unreadable=`.
    - A live `ref instance` handle met anywhere in the walk is followed one level (its variables read under the handle's path, once per instance per snapshot), and the handles left unfollowed are counted as the second number of `instRefs=` (an upper bound on unread state, not a disqualifier); followed members have their own 250,000-leaf budget per scope (`followLeaves=`, `followTruncated=`), a non-struct object that names no method is counted as `objNonStruct=`, and a string whose text merely contains `ref instance ` is never taken for a handle.
    - `deep drop <name>` frees a snapshot.
    - `diff` prints in path order up to 300 lines, so check a known leaf with the `substr` path filter; `flip` separates "flipped and reverted" leaves from "changed twice", and `get` resolves a path live by name.
    - A full snapshot is a deliberate stall (the watchdog may print `STALL`).
    - Its negatives count only with five controls in the same session and `truncated=0` and `followTruncated=0` on every compared snapshot: `deep selftest` → `OK leaves=5 changed=3` plus `selftest instance: OK followed=1 members=N`, `global.playerBuff[1][0][86]` in `deep diff base on playerBuff[1][0][86]` (the Martyr buff under Purgatory's drain), a `census.` row moving on a Healing Zone cast, a changed direct `Player_obj.<name>` member (not a followed `Player_obj.<handle>.<member>`) in base→on, and the `talent` scope reading `read=3` with no `<absent:` leaf.
  - `tgprobe buffwatch on|off|clear|show` (research build only, stripped from the player build like every `tgprobe` command): samples every non-empty `global.playerBuff[1][0]` slot on each `DrawHudBuffs` draw (no new hook) and keeps one record per buff id - `app=` appearances, `present=`, `first=`/`last=`/`min=`/`max=` of `destroyTimer`, `identityMismatch=` (the slot's own `buffType` differs from its index), `host=`, and from the `BuffAdd` note `adds=`/`lastAddFrames=`/`inUse=`/`useTalent=` (whether the buff was added inside a `TalentUse`/`TalentUseClass` call). `show` also prints records that were only added or only mismatched, so a failed positive control says why. Positive control: a timed Counter cast must produce `[104] app=1 first=` > 0. Session 12 used it to measure the four buff rows (`docs/toggle-skills-research.md`).
  - `restartprobe vars` / `hook` / `show` / `reset` / `set <scope> <name> <number> confirm` / `dump button|pause|show <label>` / `dump diff <a> <b>` / `hold <scope|button|arg0> <name> <number> [at <row>] confirm` / `hold off` / `hold stat` / `argset <row> a<i> <number> [calls=N] confirm` / `argset clear` / `argset stat` (**research build only**, not in `kPlayerCommands`, dispatched from `HandleRestartProbeCommand`): the pause-menu Restart gate instrument (issue #8); see `ForgePact/docs/restart-always-available-research.md`.
    - Round 1 (2026-09-22) found the gate upstream of the Restart activation - a refused press never calls `UiAIngameRestart` - and did not identify it. Round 2 (the same evening) did not identify it either: the Restart button's own `enabled`/`manualDisable` flip with combat, none of the four attached node-API setters was observed to be called, a draw-time hold of either member was rewritten before every next call (`entryHeld=0`), and a draw-time hold of `wasInCombat` stayed in place without unlocking the press; `UiSetFocus` is called (assumed at step time, not measured) every frame the cursor hovers Restart, with the button as `a0`. Round 3 (late the same evening) identified it: an `arg0` hold of `manualDisable 0` at `UiSetFocus` alone let an in-combat press reach `UiAIngameRestart` (`calls=1`, `wasInCombat=bool:true` at the call) and restart the zone, while `enabled 1` alone did not; that write is what `restartanytime` ships. Every write and point-of-use read happens inside a hooked call before the game's own body runs, or on the frame that consumes `cmd.txt`; nothing runs from `FrameCallback`. `vars`: hook-free, prints each candidate name on `global`, `Controller_obj`, `Player_obj` and `UI_Pause_obj` as `<scope>.<name>=<kind:value>|absent|unreadable`, plus the path `global.tupm[1].in_combat` as `path:…=<kind:value>|unresolved: <reason>` (resolved by `tgprobe deep get`'s reader). `hook`: attaches 22 rows (the Restart activation and draw, `ZoneGenRestart`, the six `UI_Pause_obj` closures and thirteen UI node-API scripts such as `UiSetRowEnabled`) each as a native detour, printing `native`, `blocked` with the reason, or `not found`; `prospectprobe hook` detours four of the same scripts, so run one of the two per session. `show`: `control=` (the draw's call count - **C1**, must be above 0 with the menu open;
    - **C3**, unchanged across two seconds with it closed), `selfIds=` (the distinct button instance ids that reached the Restart draw), the hold and `argset` status lines, per-row `calls=` (`n/a` when not attached, never 0), and the first 20 calls per row. `reset`: clears counters, logs and `selfIds`; keeps rows, dumps and an armed hold. `set`: the one command-time write, refused in order (unknown scope, no instance, absent, not a number, no `confirm`) and read back as `wrote=yes|no changed=yes|no`; scope `path` writes the path's last segment. `dump button <label>`: captures the Restart button's own instance inside its next draw call; `dump pause <label>`: the `UI_Pause_obj` instance now; `dump show` prints `<label>: kind= id= frame= names=` and every member; `dump diff` prints `~`/`+`/`-` lines per kind. `hold`: writes a number, in the kind it finds, on every call of a site row (default the Restart draw) before the trampoline, counting `entryHeld`/`entryOther` (whether the last write survived to this call), `readbackOk`, `writes`, `unreadable`, `skipped`; **C4** is `readbackOk` equal to `writes`. Scopes are `set`'s plus `button` (the call's self) and, since round 3, `arg0` (the call's first argument - the Restart button at `UiSetFocus` - checked on every call: argument present, readable through `HhUsableInstance`, member read by name, never a kind check); every instance target is labelled `<object name>#<id>.<member>` from the instance it resolved to.
    - There are two hold slots: `hold …` arms the first free one and refuses `two holds armed; hold off first` rather than replacing one, `hold off` disarms both, `show` prints one stat line per slot (`hold[0]: armed= …`), and `hold stat` also prints each slot's entry ring (1024 entries, one per write: frame, label, entry value, `held=yes|no`, written value, read-back), collapsed into `hold[<slot>] ring: frames <first>..<last> x<count> …` runs, newest 32. Disarm: at the draw site, a call more than 3 frames after the last write (menu closed); at any other site the draw row's own calls decide - no draw for more than 3 frames, or a draw gap since the slot's last write, prints `hold: disarmed (menu not drawing since frame …)`, so a hover gap on `UiSetFocus` disarms nothing; 20000 writes caps both. Arming at a non-draw site refuses `needs the Restart draw attached` while the draw row is not `native`. `argset`: replaces one numeric argument of one row for its next N calls, in the argument's own kind, and writes no variable.

### 3. IPC Log & Output File (`<game>\bin\bp_ipc\out.txt`)
Append-only log containing plugin startup notifications, command responses, and runtime diagnostic dumps. The panel reads `out.txt` to track process boot counts (`BloodPact plugin loaded`).

**Rotated by size at plugin load, in both builds** (2026-09-18; one player's copy reached 7.8 MB with nothing trimming it). Once, in `ForgePact::ModManager::Initialize()`, BEFORE the `BloodPact plugin loaded` banner is written and after `bp_ipc\` is confirmed to exist: if `out.txt` exceeds `kOutLogRotateBytes` (2 MB), it is moved to `out.prev.txt` via `MoveFileExW(..., MOVEFILE_REPLACE_EXISTING)`, replacing any earlier `out.prev.txt`, and the new session starts a fresh `out.txt` — so an oversized log is trimmed back at the next start and the **previous session's log always survives**. This stops old logs piling up but is not a size cap: several short sessions can share one `out.txt` until it passes 2 MB, and a single long session can grow it well past 2 MB, because rotation never runs mid-session; that whole file is then kept as `out.prev.txt`, which matters because a player who crashes relaunches, and the crash report needs the session that crashed. Rotation only ever runs at load, never mid-session. If the move fails (e.g. the panel has `out.txt` open without `FILE_SHARE_DELETE`), nothing is truncated — the plugin keeps appending to the oversized file and writes one line to the new session's log naming the failure and its `GetLastError()`. **A bug report should attach both `out.txt` and `out.prev.txt`** — the session that crashed may be the one that was just rotated into the `.prev` file. The research build additionally rotates `bp_ipc\itemdrops.jsonl` the same way, behind `#ifndef FORGEPACT_RELEASE` (its own 20 MB threshold, `out.prev.txt` equivalent named `itemdrops.prev.jsonl`) — the player build never writes that file at all (`BP_LOGDROP` is a no-op there), so it needed no rotation until now purely because a research session's copy reached 52 MB. See `tests/test_out_log_rotation_contract.py`.

Rotating `out.txt` changes its file identity (a new file, new inode), which the panel's restart detection must survive: `plugin_boot_count()`'s own incremental scan already treats an identity change as a reason to recount from scratch (see its docstring), but a *freshly rotated* `out.txt` always opens with exactly one boot banner, so its count can coincidentally equal the count the file it replaced held — a bare count comparison then reads e.g. `1 -> 1` and misses a close-and-relaunch that happened to land between two 5-second polls. `watcher()` therefore compares `plugin_boot_generation(cfg)`'s `(file identity, boot count)` pair rather than the raw count alone; see `tests/test_panel_performance.py`'s `BootGenerationTests`.

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
| `modfiles_shipped/YYToolkit.dll` | hub release asset | `yytoolkit-v4.0.1-hs.1` | `51a393d7…` | Modified YYToolkit, built from the hub's `third_party/yytoolkit/` patch series (`series_revision hs.1`) at hub commit `848a26e…`; see `yytoolkit-modified/NOTICE.md` and `yytoolkit-modified/YYToolkit-BUILD-INFO.json`. **This pin replaced the previous `falorfrozen-cmd/ForgePact` release-zip pin (`ForgePact-1.3.16.zip`, `bb113eef…`) when PR 53 merged to `origin`; see the note below the table. No ForgePact release has shipped a package built against this pin yet, so players still receive `bb113eef…`.** |
| `modfiles_shipped/HSOfflineTrackerProducer.dll` | same v1.3.16 zip | v1.3.16 | `36608aa0…` | HS-Offline-Tracker's live sensor (optional); a 2026-09-07-or-earlier build, present in every release since v1.3.10 |

**What the DLL players still receive is, and what its notice left out
(recorded 2026-09-19).** Until a ForgePact release ships a package built
against the new pin, players keep receiving SHA-256
`bb113eefc9a5d485231ced1dc85d773dbc6b762ee680214851c56541359ad297`, 904,192
bytes; HS-Offline-Tracker's `aurie-loader/YYToolkit.dll` was the same file
(compared by hash). Its PE header gives linker 14.51, a `TimeDateStamp` of
2026-08-26 07:13:32 UTC and the export-table name `YYToolkit_noexec.dll` —
all read from the header and the strings, nothing disassembled. The notice
that accompanied it documented two changes and said everything else was
unmodified upstream. Strings in the binary show that was not so:

- a candidate filter in `YYC::GmpFindFunctionsArrayX64` (`rejected candidate` /
  `accepted candidate` log lines, absent from upstream and from both documented
  files). Its source was not kept;
- a startup breadcrumb tracer: numbered messages written with `CreateFileA` /
  `WriteFile` to a hardcoded absolute path under the builder's user profile;
- an import of `VirtualQuery` that nothing in the documented source calls;
- the lea/mov page pre-filter, which *was* in the committed
  `Generic-RunnerInterfaceNew.cpp` (since deleted, see the repository map
  above) but was never listed in that notice.

Whether the DLL carries further changes that left no string cannot be
determined without the source it was built from. So **no repository holds
complete corresponding source for the binary players still receive**, and
"rebuild it from `yytoolkit-modified/`" was never a recovery path even while
that directory held whole-file copies: a fresh build of the documented tree
did not get the game started. Its `YYToolkit.log` ends
on `YYC::GmpFindFunctionsArray() => AURIE_SUCCESS` and never reaches the
`m_FunctionEntrySize` line; the only code between the two is
`YkDetermineFunctionEntrySize`, which dereferences the candidate unguarded.
That is the **likely** fault site — inferred from the log, which is flushed
per line; no crash dump exists.

The replacement is the hub's patch series,
[`third_party/yytoolkit/`](../../../third_party/yytoolkit/README.md): upstream
v4.0.1 (`5a95e46`) plus seven documented patches, built by
`tools/build_yytoolkit.py`. As of this note it has been built and host-tested
on one machine, its log markers checked in the DLL (with a negative control:
`verify-dll --dll` run against `bb113eef…` fails, naming the markers that file
lacks), and **launched twice against the game** (2026-09-19): first YYToolkit
alone, no plugin loaded — the startup fault did not reproduce in that
session, and lag was not observed either — then a second, idle session with
ForgePact's `BloodPactPlugin` (v1.4.4, built locally) and the
HS-Offline-Tracker producer both loaded alongside it: both initialized, and
an IPC smoke test exercised the plugin-to-runner interface, but no gameplay
was played, so the error-report path with a plugin loaded is still
unexercised (see `third_party/yytoolkit/README.md`, "Launch gate", "First
launch results (2026-09-19)" and "Second launch results (2026-09-19, plugin
loaded)", for the full record). Neither is settled from two short sessions on
one machine. Moving this row to a build of that series merged (PR 53) — the
pin table above now names the hub release asset URL for sha256
`51a393d7e5291ad76bdb85b9f44faf5178b6b20e0ce8432fa26bdaf9e21eadf8`, and the
same pull request rewrote `yytoolkit-modified/NOTICE.md` to point at the hub
series. HS-Offline-Tracker's equivalent (PR 3) has also merged. A launch
with a ForgePact plugin loaded has passed that row of the launch gate;
what remains is the owner's confirmation, plus gameplay with mods active and
the error-report path with a plugin loaded, both still unexercised
(`third_party/yytoolkit/README.md`, "Where the binary is
published"): both tools install to `mods/aurie/YYToolkit.dll` with overwrite
semantics (`src/forgepact.py` copies unconditionally), so whichever installs
last wins, and shipping the new DLL in a release of only one of them lets the
other put the old one back. **Neither tool has cut that release yet**, so
`bb113eef…` is still what a player's installed copy carries, even though
`origin`'s pin table row above and the `yytoolkit-modified/` notice it points
at have already moved past it. The hub release the pin names exists and is
published (not marked `--latest`), and the asset URL resolves (verified
2026-09-19: `py tools/fetch_toolchain.py --root <empty dir> --force` fetched
and verified all eleven pins, this one included, into an empty directory) —
but publishing that library release is a separate step from either
repository tagging and shipping a tool release.

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
   - Diagnostic commands (`readmem`, `census`, `enemylog`, `probestruct`, `structdump`, `hashprobe`, `forgehash`, `restartprobe`) are excluded from release builds (`/DFORGEPACT_RELEASE`) to protect performance and stability.
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
   - **"Noise" describes who causes those entries, not what they cost (added 2026-09-19).** Each one is a full YYToolkit error report: a stack trace, a symbol for every frame, the module list and a log write — and upstream's unpatched symbol resolver rebuilds its map of every script and builtin once per stack *frame* of every report; that cost, for unpatched upstream specifically, is read from its source and is structurally certain but not itself measured (nothing here runs unpatched upstream against the game). A separate session reported about 142 such reports in about two minutes of play with YYToolkit alone lagging the game (vanilla, and offline without mods, smooth) — reported, not re-measured here. Hub patch `0005` in `third_party/yytoolkit/` reports each distinct message once, counts repeats, and writes `[hs] YYError report cost` / `[hs] YYError summary: total=` lines so a launch of that DLL measures it. **That launch has now happened once** (2026-09-19, YYToolkit alone, no plugin loaded): 133 caught errors in about two minutes, only one of them a distinct message, whose full report cost 527 ms (520.868 ms of it symbolising YYToolkit's own frames, not the 0.018 ms the cached game-symbol table cost) while the other 132 repeats cost 0.252 ms combined; the person playing reported "no lags whatsoever." That is one session, not a controlled measurement of whether the reports are what lags the game, and it raised no second distinct message to compare against — see `third_party/yytoolkit/README.md`, "First launch results (2026-09-19)", for the full numbers. The other candidates remain neither measured nor ruled out: the console YYToolkit allocates (synchronous writes if the runner prints each error to it), per-call allocations in plugin-side `CallBuiltinEx`, and — for any build made through upstream's project file, which compiles `Release|x64` with optimisation disabled — the optimisation level, which patch `0006` sets explicitly.
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
    - **What it was:** the map-reveal pack window's "lie about distance" permission was invalidated in `OnFrame` when the zone changed. `EVENT_FRAME` is dispatched from `HkPresent` (see the hub's `third_party/yytoolkit/` series, which documents the same dispatch point) — the **end** of the frame — while the creators that consume the permission run their step events earlier in the same frame. So the first distance call in a newly-entered zone still received the previous zone's permission, and the window closed only afterwards. That first call is exactly the one that leaves a spawner inert. Reported by origin's review with a production-class reproduction: `new_room_before_present window=900 wants=1 creator_ready=0 distance=0`.
    - **Why more tracking at `OnFrame` would not have fixed it:** the problem is ordering, not information. A render-time check can make no guarantee about a step-time consumer.
    - **The fix:** the authorization moved to the consumer and to the thing that actually decides the outcome. The damage is specific — answering 0 to a creator that has not finished initialising makes it take its spawn branch once, early, and come out inert — and that is a property of *the creator in hand*, not of the zone. `Hook_distance_to_object` now asks the creator (`MayPopulate` → `CreatorIsReady`, a real `enemyCreatorTimer`) at the moment it would change the result. A stale window becomes a performance question rather than a correctness one, and a *ready* creator in a new zone is still served, so the pass keeps working across a transition instead of failing closed. The same guard covers the Beacon's lie — the spawner comes out inert whichever feature answered — with its wake radius and continuous behaviour otherwise unchanged.
    - **Two related gaps, same report:** the per-frame check compared only the room key, so a replaced or removed minimap with an unchanged room key kept the window alive; it now compares the full identity (room + minimap instance + grid). And `TryOpenSpawnWindow` stored `INT64_MIN` when the room was unreadable and opened anyway, so every later failed read compared *equal* to it — "unreadable closes the window" only held when the window had been opened with a valid key. `ReadIdentity` now fails as a unit and a window is never opened against an identity that could not be read.
    - **The testing lesson, which is the durable part:** the source-string assertions passed the entire time this was broken. `tests/test_map_reveal_behavior.py` compiles the real class and the real hook and calls the hook *before* the next `OnFrame`. Every scenario was verified to fail against the code it describes before being relied on — reverting the authorization to the countdown alone reproduces `got=0 want=2500` on exactly the cases reported. One of those controls also caught a bad control: removing the hook's standalone readiness guard changed nothing, because `MayPopulate` checks readiness too, so that guard got its own Beacon scenario rather than remaining a line no test could fail without.
14. **The kill drops moved ahead of the original kill proc (1.4.3) - a precaution; the x100 crash was not reproduced:**
    - **What moved:** `Hook_EnemyDestroyKillProc` used to call the trampoline (`g_Orig_EnemyDestroyKillProc`) first and then `SignatureDropOnKill(S)` and `AngelicDropOnKill(S)`, which read `enemyRarity`, `x` and `y` off the dying enemy and spawn through `LootGroundCreateFromItem` with that enemy as `self`. Both now run after the Headhunter steal and **before** the trampoline, inside a catch-all so a throwing drop cannot skip the original, and nothing below the trampoline touches `S`. The original still runs exactly once. Rates, pool, pity and the player-self call shape (no drop) are unchanged. `sigdrop` is on in every session at 1 in 7500 (`g_SigDropPct` defaults to `kSigDropAngelicPct`), so every player reached the old post-original read, not only those who raised the slider - until 1.4.5, see item 21.
    - **Why:** players reported crashes in fights with the Angelic / Unholy slider at x100 (`angelicdrop 76`) on 1.4.1. The only step that runs per hit and nowhere else is the spawn with the enemy as `self`, and it ran after the original kill proc had run (which the harness models as cleaning the enemy up; not measured). Spawning while the enemy is live is the only `self` with a live positive control; the global instance and the local player as `self` were rejected as unmeasured, and deferring to `FrameCallback` as a context no spawn has been measured in.
    - **What is unproven:** a destroyed-enemy `self` is plausible, not established. The one live measurement of this path (1.3.14, "122 kills = 122 drops", `ForgePact/docs/angelic-drop-research.md`) used the old post-original order without a crash. The tests pin the order, not that `LootGroundCreateFromItem` is safe with that `self` on the current build, nor that this was the crash.
    - **Tests:** `tests/test_headhunter_dispatch.py` now compiles the real drop functions (only the field read, dice, pool and spawns are stubbed; each spawn records its `self`, whether it was alive and whether the original had run): baseline `drops_off_no_spawn`, `drop_skips_non_monster`, `drop_hit_at_enemy_position`; target `angelic_spawns_before_cleanup`, `sigdrop_spawns_before_cleanup`, `drops_read_nothing_after_original`, `drop_throw_still_calls_original` - all four target scenarios failed against the pre-1.4.3 source. `tests/test_kill_drop_contract.py` pins the same order on comment-stripped source so it holds without a C++ toolchain.
    - **Live check (2026-09-18, current game build):** on the research build with the new order, `angelicdrop 1` gave `rolls=30 drops=30 fails=0` and `sigdrop 100 100` gave 17 = 17 (Headhunter and Tyrant's Crown alternating), every drop visible on the ground and pickable - checked by eye because `drops=` counts a successful `SpawnAngelicItem`/`SpawnSignatureItem` return, not a surviving item. 90 ordinary kills before that ran the new order with no crash. The control, the unmodified v1.4.1 player plugin (old post-original order, identical kill-drop code to 1.4.2), gave `angelicdrop 1` `rolls=30 drops=30 fails=0` with no crash either. The reported x100 crash was therefore **not reproduced**, and the release notes call this change a precaution, not a fix. Chasing the report further needs the reporter's enabled toggles and the last `out.txt` lines before the crash.

15. **The Custom Forge's `itemDataHash` refresh chain has three fallbacks that had never been observed to run, and one stale script name (2026-09-18):**
    - **The mechanism.**
      - After the Custom Forge dresses an item, `RefreshItemHash` tries four routes in order to re-stamp `itemDataHash`: `gml_Script_ItemCheckHash` (called plain, no method plumbing), a struct-bound `GenerateItemHash` method, a direct `CallGameScriptEx` on the anonymous `GenerateItemHash` closure, and finally that closure's own compiled routine resolved by `GetNamedRoutinePointer` and called like a hook trampoline.
      - ItemCheckHash has succeeded in every observed session since v1.3.13, so the other three routes have not been observed to run — nothing could show whether they work, or even whether the `+direct`/`+routine` script name was still correct.
      - It is now `@anon@4791@` (`HeroSiege::Scripts::gml_Script_GenerateItemHash_anon_4791_s_ItemInstanceStruct_InventoryV2Funcs`, the current game build's spelling; closure names move with every game patch, see Maintenance Triggers → Game Executable Updates below), replacing a stale `@anon@4638@` literal absent from the `hs-game-sdk` table current when this fallback chain was made observable — that table had the pre-patch build's `@anon@4645@` instead (see `docs/angelic-drop-research.md`'s relabelled negative — the `@anon@` name was *not observed* to resolve, not proven unresolvable).
      - `+direct` also now reads the hash before and after its call and refuses with `+direct-nohash` (falling through to `+routine`, same as a failed call) instead of reporting success on `AurieSuccess` alone.
      - What reaches the player build from this item: the `@anon@4791@` closure name used by `+direct` and `+routine`, the `+direct-nohash` refusal, and the pointer check before the `+routine` call described below.
      - The `hashprobe` and `forgehash stat` commands and their counters are research-build only.
      - The first three routes are named helpers (`HashRouteItemCheck`/`HashRouteMethod`/`HashRouteDirect`); `+routine` stays inlined in `RefreshItemHash` itself (a `routineOnly` flag lets `hashprobe routine` drive it alone) so the `AddrIsExecutableInModule` validation this fallback now runs before calling the resolved function pointer — the same address-validation discipline `HookOneScript` applies to a table entry — stays literally inside the function `test_routine_fallback_validates_the_pointer_before_calling_it` (`test_release_hook_contract.py`) checks.
    - **`hashprobe itemcheck|direct|routine`** — e.g. `hashprobe direct` — (research build only, `build.bat dev`) drives exactly one route against every remembered forged item, pre-writing a `hashprobe-sentinel` value first (a working route on an already-current hash would otherwise just rewrite the same value, which a plain before/after compare misreads as a refusal — see `AGENTS.md`, "Prove the Instrument"). It restores the original value when the route didn't write — the raw field read before the sentinel overwrite, not a string rebuilt from the read helper, so an item whose hash was never a string is restored as undefined rather than as an empty string — and reports `wrote=`/`matches-original=`/the returned value's kind. The printed line leads with the verdict from `wrote=`, not the route's own return: after the sentinel write, `itemcheck` and `routine` report success on *any* non-empty hash (the sentinel surviving untouched included), so the route's own answer is kept, separately, as `route-said=`. `itemcheck` is the positive control: proven live since v1.3.13, so a run that doesn't report `wrote=yes` for it means the probe is broken, not the other routes. Bare `hashprobe` is unchanged and still runs the whole chain. **`forgehash stat`** (also research-build only) prints the per-route counters next to the existing `g_CustomForgeHashMisses`. `direct-nohash` is labelled "unchanged (stored nothing, or hash already current)": it also fires when `+direct` correctly re-stores a hash the forge pass never actually changed (nothing added this pass, or a refresh that already ran once), not only when a route silently failed to write — so it is not itself a miss count. Neither command, nor the counters behind them, reaches the player build: `kPlayerCommands` is unchanged, and a player build compiles out all of it (decision: "release for end user should be clean") except the `+direct-nohash` compare itself.
    - **Left in place, same weakness as the old `+direct`:** `+method` returns true unconditionally, and `+routine` accepts any non-empty hash, including one that was already stored and never changed. `+method` isn't one of `hashprobe`'s three probed routes at all, and even `hashprobe routine`'s own before/after compare only proves *something* got written, not that it matches what ItemCheckHash would have computed — so a `+method` or `+routine` success in `forgehash stat`'s counters is not proof the hash is actually correct. Fixing that is a follow-up, not this change.
    - **What the probe answers:** does the 4791 name resolve (`+direct-fail(14)` means no), does `GenerateItemHash` store the hash or only return it (`wrote=no` with a 40-hex-character `ret=VALUE_STRING:…` means it only returns), and does `+routine` store it. A fallback no probe has shown working is "not observed working," not "broken."

16. **What the toggle-skill active indicator does not prove, and the one risk it accepts (issue #11, Track B, `toggleborder`):** six items — two about what is *inferred* rather than measured (`isMyClient`'s co-op meaning, the OFF lag), three about *what is covered and what each row draws on* (the eight skills, four of them with no readable ownership field; a plain cast and an unreadable discriminator drawing nothing; Blender not covered), and one **accepted risk** (Maelstrom of Frost's per-draw exact equality, decided by the author). Session 9 added Meteor Storm and Bushido to the covered set, and session 12 added Shield Lancer's Counter (eight skills). ForgePact ships offline-only (repo-root `AGENTS.md`, "this is the rule of ForgePact"), so the co-op inference is a limit on what has been observed rather than a risk to a player; the Maelstrom item is a real one, recorded here because it was accepted, not because it was ruled out.
    - **`isMyClient`'s co-op meaning is inferred, not measured against a second real player.** `ToggleIndicatorRead()` classifies every `White_Mage_Soul_Spurn_AOE_obj` instance as own or foreign from that instance's own `isMyClient` field (a `VALUE_BOOL`, or a numeric kind that counts true only when numeric > 0), with no local-player read at all — session 3 measured `Player_obj` has no `playerNumber` member at all, so there is no local-player value left to compare against (`docs/toggle-skills-research.md`, "Co-op / ownership after session 3: isMyClient"). Every session so far has been single-player; the foreign branch is checked only in `tests/toggle_skill_harness.cpp`'s scenarios and by `tgprobe spurn as foreign` (a non-mutating override that re-interprets every own instance as foreign, live, in the research build) — never against a second real player's own AOE.
    - **The OFF lag is measured once at 19 frames, not eliminated.** Session 4's S4 measured `lastTransitionFrame` (the draw where the ownership-only read flips to off) landing 19 frames after the `TalentUse` press that turns Soul Spurn off (`docs/toggle-skills-research.md`, "After session 4"). The outline can therefore lag the actual OFF press by that measured amount before it clears; this is not eliminated by any caching workaround (the read and the draw call are both point-of-use, never cached across frames — the map-reveal defect this guide's item 13 describes).
    - **Eight skills are covered, and four of them have no readable ownership field.** Since phase S the indicator covers Soul Spurn (White Mage), Lunar Orbit (Exo), Crematus (Plague Doctor), Submerged Knives (Butcher), Maelstrom of Frost (Prophet, second tier), and, since session 9, Meteor Storm (Shaman) and Bushido (Samurai) - the rows measured as persistent-instance toggles with a shippable ON discriminator - plus, since session 12, Counter (Shield Lancer), the one row read from the local player's own buff array (`global.playerBuff[1][0][104]`, whose `host` measured the local `Player_obj.id` on every record) rather than from an instance, ON only while Give No Quarter is allocated. No talent id is stored any more; each row's id is resolved at runtime from its `abilityId`, and an unresolved row is skipped and counted (`unresolvedRows=`). Lunar Orbit, Crematus, Submerged Knives and Meteor Storm ship on *controller* objects with **no readable ownership field** - a probe row reading `isMyClient` on the first three answered `unreadable` on every sample (4212 and 2586); Meteor Storm's controller carried no `isMyClient` field among the 17 scalars its own field dump listed at all, which is recorded as **not observed** rather than unreadable, a different case (`docs/toggle-skills-research.md`, "Meteor Storm's ownership: none, and what the indicator attributes") - so for all four every instance counts as own (D-N3). Bushido has **no plain form at all**: seven of its own instances exist per activation and none exist otherwise, so its row lights on any own instance the same way Lunar Orbit's and Submerged Knives' do, but WITH a readable `isMyClient` (unlike them). A zone change ends every row's ON state; the owner confirmed in-game (session 9) that both Meteor Storm and Bushido actually stopped. ForgePact is offline-only, so the ownership behaviour above is a documented limit rather than a co-op risk.
    - **A plain cast draws nothing, and an unreadable discriminator draws nothing.** Each row names one way to tell a toggle from a plain cast: a marker field read numeric > 0 (`purgatory`, `skillContamination`), a timer field read exactly at its measured held value, or nothing at all for a row whose plain form was measured to create no instance of that object. A field that throws, is absent or is not a number counts Unreadable and never lights the marker - it is never defaulted to a number that could match.
    - **Butcher's Blender is NOT covered, and that is a measured result; Shield Lancer's Counter was not covered until session 12 (see the `toggleborder` bullet: it now ships as a `PlayerBuff` row gated on Give No Quarter).** Session 6 observed no persistent ON instance for Counter over the one ON/OFF cycle measured: its toggle state lives on player buff 104 on the generic `Draw_Player_Buff_obj`, not on a per-skill instance, and `Charge_Controller_obj` appears on cast but is not removed on OFF. Blender's ON/OFF steps were never run at all (`blocked`); the tester's "not a toggle skill" is an impression, recorded as one, not a measurement. Blender is not a row and its name does not appear in the shipped table. Counter's own state was later found on buff 104 itself: session 12 ships it as the eighth row, a `PlayerBuff` row gated on Give No Quarter (see the `toggleborder` bullet).
    - **Maelstrom of Frost's discriminator is per-draw exact equality, and that is the known risk.** Its row lights only while `destroyTimer` reads exactly `-1.000000`. **Two plain casts have now been measured and the marker was not observed to light in either** - session 6's (`atPredicted=0` over 4288 draws) and session 7's, a full cast with Endless Blizzard respecced out that ran the timer down from `first=4320.000000` to `last=-0.977760` (`min=-0.977760`, `atPredicted=0`, 4290 draws) while the row's counters stood still at `drawn=5796 on=5796`. That is "not observed to light in two measured plain casts", **never** "cannot light": the check is per-draw exact equality with a decaying float sampled only on drawn frames, so a plain cast that happens to sit at exactly `-1.000000` on a drawn frame would light the marker for those frames. Lunar Orbit's plain form did read exactly `-1.000000` on 108 of 1341 sampled draws on a different object, which is why that object was rejected as a row. Requiring the held value across several draws would mean remembering a timer value between draws, which the design forbids. Accepted by the author as a recorded caveat (`maelstromplain: no marker seen`, session 7).

17. **The toggle-skill re-cast guard refuses by caller, not by state, and covers one source of accidental re-casts (issue #11, Track A, `toggleguard`):** ForgePact ships offline-only (repo-root `AGENTS.md`, "this is the rule of ForgePact"); nothing below is framed around co-op.
    - **The refusal is gated on the row's toggle sub-talent, read at the call - except for a base-form row, refused unconditionally (D-B1).**
      - T1 refused every double-cast proc re-cast of Soul Spurn with or without Purgatory (D-N1, accepted as a cost in D-U4), because the toggle's own state cannot tell "just turned off" from "never on".
      - Phase S removes that cost without consulting the toggle state: session 6 identified the sub-index, so the hook now reads `global.subTalentMap[<index>]` → `t<talentId>` → `s<NN>` for the matched row **at the call, with the talent the call named** - the point-of-use rule from item 13, since a permission read at a frame boundary answers for the previous frame.
      - A numeric > 0 refuses.
      - **The index is measured evidence, not an assumption**: session 6 read index 1 on one character on one build, so the hook tries that index first and then any other index (cap 16) until it finds the one whose `t<talentId>` struct is actually present, each attempt kind-checked and wrapped in its own `try` so one unusable entry skips that index rather than ending the walk.
      - Were the index a character or player slot elsewhere, a fixed `[1]` would have left the guard doing nothing with only a counter as the symptom; `toggleguard stat`'s `subIndex=<n|none>` reports which index answered.
      - The measured unallocated form (`0.000000`, key present) passes and counts `subOff=`, so a plain cast keeps its double-cast re-cast exactly as in the unmodded game.
      - Every unreadable shape - the global missing, not an array, no index carrying `t<id>`, `s<NN>` absent or non-numeric, a throw - passes and counts `subUnreadable=`: fail-open is vanilla behaviour, and both counters are in `toggleguard stat` so "refused nothing" and "could not read" are never confused.
      - Session 9 added a seventh row, Bushido, which has **no sub-talent at all** - a toggle on its own - and is refused every time, without the sub-talent read ever running: the hook tests `ToggleRowIsBaseFormToggle()` first and, for a base-form row, refuses unconditionally, counted in both `refused=` and a separate `baseForm=`, rather than feeding a real slot's key space `kToggleNoSubTalent` (0) and getting an Unreadable pass-through.
      - Meteor Storm, session 9's other new row, has a real sub-talent (`s11`) and is gated the ordinary way.
      - The guarded set is the same seven rows the indicator covers, by runtime-resolved id; an unresolved row is not guarded.
    - **Key auto-repeat is not covered.** A held key re-fires `TalentUse` every 57 frames (research doc Q5 (b)); that is the player's own input, and no clean discriminator exists short of the input layer. Real re-presses are never dropped.
    - **Live proof: confirmed on both builds for the White Mage / Soul Spurn path; the other four rows' refusals have never been observed live.** The hook's call shapes come from session 1 (three procs observed), and the harness (`guard_*` scenarios) proves the decision against those shapes rather than against the game - that part is unchanged. What is now measured: **research build** (session 5's rerun, 2026-09-20, White Mage only) counted `refused=9 procSeen=9 passed=61 selfUnreadable=0 objUnresolved=0` with the refused call itself logged (`TalentUseClass … self=Universal_Double_Cast_obj … a0=real:240.000000`) and the tester reporting the toggle always ending in the state they pressed; **ship build** (session 7, 2026-09-20) returned the tester's collective verdict on the player binary, "all five skills work, guard refused correctly, tgprobe unavailable". That verdict is **one collective sentence, not five per-skill observations** - the marker was confirmed for all five that way, but a refused proc has only ever been observed on Soul Spurn, so `lunarOrbit`, `crematus`, `submergedKnives` and `maelstromOfFrost` are covered by construction (same table, same runtime-resolved ids) and not by a measured refusal each. Still unrun: the guard-off baseline (V2) and `lastProcRet=` (V7) are `blocked` - with the guard off, the hook takes its off fast path before the caller check, so nothing is counted and neither can be measured that way - and a proc of a non-guarded talent (V4) is `not observed`. The sub-talent index caveat in the first sub-bullet stands on its own: the index was measured on one character on one build, and the fallback scan is what keeps a different layout from silently disarming the guard.
    - **One more research-session rule.** `toggleguard 1`'s `HOOK INSTALLED on TalentUseClass` must come before `tgprobe hook` (see the `tgprobe` bullet above).
18. **Hero Siege draws on a whole-pixel grid — any overlay ForgePact draws must use integer coordinates and integer sizes.** Measured live during the sprite-look-probe tuning (issue #11, R round 7): fractional screen positions like `12.5` or `75.1` do not occur; the tester, quoted, `'everything seems to be drawn in a whole number position'`. The fractional values a runtime read hands back for a talent slot (e.g. `navBboxX=385.700006 navBboxY=1711.000000 navBboxWidth=124.700000 navBboxHeight=139.200000`) are an artefact of the number type those fields are stored as, not the art's actual on-screen placement. **Derive a position or size from a read like that, then round to the nearest whole pixel before the draw call** — never pass the raw fractional read straight to `draw_rectangle`/`draw_sprite_ext`/`draw_ellipse_colour`/`draw_rectangle_colour` or any future draw call. `ForgePact/docs/toggle-skills-research.md` ("Sprite look probe") has the tuned example this rule came from (Soul Spurn's slot at this session's HUD scale: `120 x 126` at `388, 1711`, accepted by the author in D-U12 and derived from that slot's own live `navBbox` of `385.700006, 1711.000000, 124.700000 x 139.200000` by `x + 2.3`, `y` unchanged, `w - 4.7`, `h - 13.2`, each rounded — evidence for that slot at that scale, **not** a shipped constant; the shipped marker applies the offset to whatever `navBbox` it reads. This supersedes an earlier, since-withdrawn `125 x 125` at `385, 1712`).

19. **Auto-prospect runs the game's own Prospect at a moment the game did not choose - an accepted risk (2026-09-18; renumbered from 16 when the toggle-skill items merged in above it):**
    - **The risk class.** `autoprospect 1` invokes `UiAProspectButton` from `FrameCallback` when an insert lands, not when the player presses the button. That is the class the repo-root `AGENTS.md` "Don't Suspend the Game's Own Runtime" warns about: it changes *when* one of the game's operations runs, not one value inside a call the game is already making. The human accepted this risk for shipping on 2026-09-18, the same acceptance given for the Pet Quest Collector, gated on the Phase 1 proof - which is recorded: with a real hand press as the positive control, `press exec-index button:activationArgs self=found confirm` printed `prospected` with `invoked=yes`/`inner=yes` and was seen by eye (`ForgePact/docs/prospect-window-research.md`, § Stage B results).
    - **Material loss (R7).** Anything left in the prospect grid across a written save is destroyed - measured on the vanilla grid in Phase 0c, so it is the game's behaviour, not the mod's. With auto-prospect on, the newest batch of materials sits in the grid (all of them, with the `bag` sub-option off); the panel switch and `release-notes-v1.4.5.md` warn about it, and the human judged the warning enough to ship. Below `kAutoProspectMinFreeCells` (6) free cells the mod holds back (`grid-full`). 9 free cells is the fewest measured to still prospect; Phase 3 `S-grid-full` refused at 5 and 4 free (one line, then silent) and prospected at 16, so 6-8 are still not observed exactly.
    - **The move to the materials tab is a second game operation (Stage C, 2026-09-19), and it writes the save-backed inventory.**
      - With `autoprospect bag` on (the default under the parent), each landed insert first runs the game's own stack move on the previous prospect's batch - the material cells whose fingerprints the core's own last invoke produced - `InventoryGridCanAddToStack`, `InventoryGridAddToStack`, then `InvGridClearItemNode`, by name - again at a moment the game did not choose, and this one changes the player's inventory, not a UI grid.
      - **acceptance: accepted (human, 2026-09-19).**
      - It rests on M7 (`prospect-window-research.md` § Stage C results, `M-shapes`): one material moved by that route, `success:true`, materials-tab count 904→905 by eye.
      - The ship code checks what the research command did not: it clears a cell only after the add returned `success == true` and the cell still holds the same fingerprint, and a `vanished` (the cell emptied without success - a possible loss) or `cell-kept` (success, but the final read still holds it or cannot be made - a possible duplicate) turns the pass off for the session.
      - **M5 (a full bag) is not observed**: the human skipped it (their experience is that a click-move always reaches the materials tab), so the refusal path - no `success` from the add (`not-added`) or, for a new type, no grid named (`no-preferred-grid`) or no `success` from the place (`not-placed`), the material left in the grid - is designed but not seen live; Phase 3's `T-bag-full` is optional and was skipped on e63eed5.
      - **Round 0 moved every material cell, and that was wrong (Phase 3 live, 2026-09-19, e63eed5):** an inserted ore - itself a material - was moved back to the tab in the pass before its own prospect and never prospected (`moved` 3→6, `ran-no-effect=1`, ore count unchanged by eye).
      - Round 1 moves only the recorded batch, so an insert is not moved whatever it is, except the accepted corner below; its re-run adds `T-ore-insert` (T7).
      - The batch is forgotten on anything the core cannot account for, so the first prospect after reopening the cube, toggling the parent, a removal or a `not-landed` expiry moves nothing.
      - One corner is accepted and not observed: a swap onto a batch cell with that batch stack dropped back in within `kAutoProspectLandFrames` leaves the stack in the batch, so it goes to the tab rather than being prospected (nothing is lost).
      - The materials tab is not a grid node (`M-grids`), so nothing can read it arriving: the add's `success` is the only in-game confirmation.
    - **Found on the c27cdad re-run (2026-09-19, research DLL; T0, T1 and T7 passed), measured in Stage D (`newtype-live`, research DLL 67d2d9e), shipped on 20fc518** (`prospect-window-research.md` § Stage D results / § Stage D ship design).
      - **A - first-of-type materials (fixed in the ship code; not yet observed live - D-newtype-move):** a material whose type has no stack in the materials tab yet was refused by `InventoryGridCanAddToStack` (it answers with the existing stack, so falsy for a new type) and stayed in the grid - four gold-ore outputs piled up; the human required the mod to move these as a click does.
      - Measured: the game's own click-move of one runs `GetItemPreferredGrid(1, item)`, which returns `{gridBits, grid: <array>}`, then `GridAddItem(that .grid, item, 0, undefined)`, which returns `{tabNumber, x, y, tabType, success}`, then the same clear (`N-a0`, `N-gridadd-return`); `stackmove … a0=grid` reproduced it (`moved`).
      - The material lands in the **main bag grid** (`tabType` 0), not the materials tab - so "moves to the materials tab" is true only for a type that already has a stack there.
      - The adapter now takes that route after the check's "no", with the same success check and clear; its refusals are `no-preferred-grid` and `not-placed` (each logged once; neither observed live - a full bag, `not-placed`'s expected cause, was not tested), and `moved-new` counts what it moved.
      - **B - the ore that "came back" (not a mod defect):** with the bag pass not involved, ore invokes used the ore up and produced nothing; a vanilla hand press with auto-prospect off, on the same ore type and with the same call, did the same (press 1 gave materials, press 2 gave nothing), and the human confirmed that prospecting ore only has a chance to give materials.
      - No `fate` line showed an ore returning to the bag.
      - No code change; the release notes say it is the game.
      - `prospected` still cannot tell an ore used up for nothing from one that gave materials (it counts a changed grid).
      - **Phase 3 re-run on 20fc518 (2026-09-19; `phase3c-status` and `phase3d-status: complete`):** with the research DLL T0-T3 and T5 passed; the ore clicked in with leftovers (`D-ore-mixed`) moved only the batch (`moved` 1→2), was prospected (`prospected=3 ran-no-effect=0`; it gave nothing, the game's chance) and was not moved back; the ore dragged in (`D-ore-drag`) became three materials that stayed (`fate` `gone`, `in-bag=no`); and the player DLL (`D-player-dll`) logged `autoprospect: first move to bag - … moved=1 moved-new=0 …` with no research or `prospectprobe` line.
      - One 2×3 item of item type 3 (fingerprint ending `211440-3`) that the invoke left unchanged (`ran-no-effect=1`) was confirmed by hand as not prospectable - the game's behaviour for that item; observed once, not a claim about item type 3 as a class.
      - **Still unproven:** the new-type route from the auto-prospect pass itself (`D-newtype-move` not observed: no first-of-type material was available; `moved-new` stayed 0 throughout, and `stackmove … a0=grid` running the same calls is the stand-in), its refusals (`D-newtype-refusal`, a full bag), and T4/T6; the N5 bag-read positive control was not run, so "the bag did not gain the ore" is `not observed` rather than measured.
      - **The place route runs on any falsy answer from `InventoryGridCanAddToStack`**, not only for a type with no stack yet; a capped stack or a full materials tab answering no would send that material to the main bag the same way (with the same success check) - `not observed`, and the player-facing notes describe only the measured first-of-its-kind case.
      - Since the closing round, a new type whose `GetItemPreferredGrid` call never ran (a name that did not resolve, a failed `script_execute`) is `move-failed` ("a call did not run"), not `no-preferred-grid`, whose line says the game named no grid.
      - Seven different failures reach `move-failed` (the cell unreadable or changed before the first call, the item lookup, the has-a-stack check, the preferred-grid lookup, the add or the place not running, or an unreadable final read after calls that did not succeed); since PR prep the core's `FailedStep` names the earliest one and the once-per-session `move-failed` line carries it in parentheses - e.g. `… the move could not be made or checked (the preferred-grid lookup did not run)`.
      - Still one line per reason, not per step: it names the step of the first `move-failed` cell of the session (`target/move_failed_names_the_step_that_failed`, failing line recorded against c229cb5).
    - **With `prospectprobe hook` in the same session.** Both put an inline detour on `m_MoveItemToGrid`'s address. Measured once on c27cdad: with `autoprospect 1` installed first, `prospectprobe hook` printed `142 detoured, 1 failed` - the one failure `anon@15345`, refused before any patching because a table hook may hold that entry - so the auto-prospect detour was left in place. Stage D's N0 control (`N-coexist`) then verified that `autoprospect 1` still sees inserts afterwards: `autoprospect 1`, then `prospectprobe hook` (`142 detoured, 1 failed`), one junk insert gave `inserts=1 prospected=1` and the research log's lines, in one session (2026-09-19, research DLL 67d2d9e); the two-session fallback was not needed. The reverse order - `prospectprobe hook` first - leaves `autoprospect`'s own install to find that address taken. If `autoprospect`'s own install comes back `TABLE-ONLY` it turns itself off for the session and says so, rather than reporting ON while the game's direct calls bypass it (item 12). The same applies to `citrace nativetrace`.
    - **What is measured, and what is unproven.** Phase 3 is recorded (2026-09-18, `prospect-window-research.md` § Stage B results, the `S-*` rows): a drag-in and a click-in were each prospected once, moving a material inside the grid did not invoke, `autoprospect 0` left inserts alone, `grid-full` held back once and then stayed silent, and the player DLL prospected both a drag-in and a click-in by eye. A drag-in fills its cells after the insert closure returns (`contents=0->0`) and a click-in before it (`6->6`); the core does not depend on either order (an insert counts when the filled count is above the last *settled* count, not the count one frame earlier). Whether a click-in's fill can land a whole frame before its hook is not measured. A drag that empties its source cell while held and fills it again on drop would read as an insert; with the mod on, only materials and refused items sit in the grid, and one materials-only press was observed as a no-op (`P-materials-only`). The player DLL counted one `ran-no-effect` in S7 that the research DLL did not show: observed, cause not observed, and nothing was lost.
    - **Diagnostics.** `autoprospect stat` is research-build only (the user's rule that player builds carry no debug tooling). The player build logs `autoprospect: hook installed -> ON` or the table-only refusal, each refusal reason once per session, a failed dispatch once, `autoprospect: first prospect - invoked=… prospected=…` once - a line naming work done, not armed state - and once each `autoprospect: the Prospect ran but the grid did not change - …` (the first `ran-no-effect`) and `… could not be read afterwards - …` (the first `unverified`), so an invoke that did nothing is a line in `out.txt`, not a missing one. For the move pass it logs `autoprospect: first move to bag - …` once and each of `no-preferred-grid`/`not-placed`/`not-added`/`move-failed`/`vanished`/`cell-kept` once, the last two with the turn-off.

20. **Injected input can select a character; the hub's `hs_select_character` does it (measured and shipped 2026-09-21):**
    - **The gap.** The hub's `hs-drive` MCP server launches the modded game and drives this plugin over `bp_ipc`, but it leaves the game at its main menu, and most gameplay commands act only once a character is loaded. Getting from one to the other — main menu, Play local, save slot, Play — is drivable by injected input, and `hs_select_character` now does it (below).
    - **What exists.** The instrument, in two halves: `menuprobe` in this plugin (research build only; Data Formats § 2 above) and `hs_input` in the hub (`tools/hs_drive_mcp/input.py`, `docs/tools/hs-drive-mcp.md`), which injects keystrokes and clicks into the game's own window by either of two routes. Four candidate mechanisms are written up with a positive control each in `docs/character-select-research.md`: injected operating-system input, posted window messages, the engine's own key builtins through `cb`, an event performed on a menu button instance, and a warm script call on one.
    - **What the finding is.** `finding: a-sendinput, a-postmessage, d` and `shipRoute: mcp-only`, measured 2026-09-21 in one session against the real modded install. Injected operating-system input drove the whole path to a loaded character in `Town_01_rm`, proven by a live `Player_obj` instance with `Player_Parent_obj` — *not found* beside it as the negative control. **The click has to be held**: `hs_input`'s `click` emits button-down and button-up back to back, both land inside one frame, and at 144 fps the game never samples a frame with the button pressed — so it moves the cursor, lights the button under it, reports `complete: true` and activates nothing. The same click with 120 ms between the records worked every time. Posted window messages reach `keyboard_check` but not `keyboard_check_direct`. The engine's own `keyboard_key_press` reaches both and needs no foreground, but is keys only and keyboard navigation is *not observed* at this menu. `event_perform` on a button is *not observed*, scoped to `UI_Button_obj` and the seven events tried. The warm script call is **unmeasured** — its positive control raised, so nothing it reported could be told from a blind instrument.
    - **What the session falsified.** Two assumptions this repository was carrying. `orbpickup stat` alone does **not** prove a character is loaded: with no orbs nearby and `orbpickup` off, it reports `globe objs=0` and `player via (not tried)`, because `orbpickup` was off — the resolver runs only while the mod is on, and this session never armed it — and the shipping workorder's D17 assumed the field answers regardless of that state. And the room index is only a *partial* oracle: opening the character panel changes the screen without leaving `Chose_rm`, so a screenshot is the reliable check.
    - **The controls that decide whether a future negative means anything.** Two of them, both written down before the session so neither can be skipped and rationalised afterwards. (1) A human holds a key while the agent reads the engine's and the operating system's key state; if that read is not true, the key instrument is blind and the two input candidates are *unmeasured*, not negative. (2) `menuprobe list` must find button instances at the main menu; menu-room instances have never been shown to be enumerable on this runner, so an empty list means the event and script candidates were never measured either — and because that is the open question, the control is a `menuprobe list` of an object the same step's `citrace dumpobj` shows live (`Menu_Controller_obj`, `Profile_Manager_obj` as the fallback), read as a pair: control non-empty with `UI_Button_obj` empty is a real negative about the button object, both empty measures the instrument. `AGENTS.md`, "Prove the Instrument Before Trusting a Negative Result".
    - **Where it shipped.** `hs_select_character` in the hub's `hs-drive` server (`tools/hs_drive_mcp/charselect.py`, `docs/tools/hs-drive-mcp.md`), from the `hs-drive-mcp-charselect-ship` workorder, which reads the two literal `## Decision` lines out of `docs/character-select-research.md` and refuses a `pending`. Nothing player-visible was added to this plugin: no panel toggle, no allowlisted verb, no release notes. It solved the three open problems that document recorded. `hs_input`'s `click` takes a `hold_ms` (120 ms by default). The clicks first landed at measured client fractions, slot 1 on a 16:9 client only. **The hub now clicks the positions `menulayout` lists** (the `hs-drive-mcp-charselect-buttons` workorder, 2026-09-21). This plugin's read-only player command reports each button's window point. The hub clicks `Play local`, save slot N (row-major, page 1) and `PLAY` at those points and polls the listing for each next button instead of sleeping. A plugin without the command, a slot not listed, a button never listed, or a listing for another window size is refused by name (`layout_command_missing`, `slot_not_listed`, `button_not_found`, `window_size_mismatch`), so no guessed point is ever clicked. That change added one player-visible verb, `menulayout`, noted in `release-notes-v1.4.5.md`. The proof of a load is `orbpickup stat`'s `player via` field, read while the tool itself has `orbpickup` armed: `none` at the menu, and a resolver route once the character is in town. The live gate passed on 2026-09-21 against the player build `24020eac`, with `none` on the menu, `Play local` and slot screens and `GetMyPlayer` right after `Play`.

21. **Headhunter and Tyrant's Crown now drop through the Angelic pool instead of their own die (#63, 2026-09-22, owner-directed):**
    - **The mechanism.** `AppendSignatureCandidates` appends Tyrant's Crown and Headhunter to `g_AngelicPool`, called from `BuildAngelicPool` after the validation loop, and only onto an already non-empty (at least one validated unique) pool - an empty pool still stays empty, so `angelicdrop` keeps turning itself off rather than making a signature item a 1-in-2 drop. `AngelicDropOnKill`'s pick spawns through `SpawnSignatureItem` when the picked candidate is a signature entry, `SpawnAngelicItem` otherwise - same `OneIn` die, same Angelic hit/fail counters, same pool. The standalone die (`kSigDropAngelicPct`, `g_SigDropPct`, `g_SigDropAncientPct`, `g_SigDropPity`, `g_SigDropSinceLast`, `g_SigDropNext`) is gone, and the startup kill-hook gate no longer mentions signature drops at all, so a default session (Angelic/Unholy slider off, the default) installs no kill hook for either item.
    - **What changed for players.** Before: each item dropped on its own, roughly once per 15,000 kills, in every session, with no panel control (only the `sigdrop off` console command). Now: both are two more items in the Angelic / Unholy Drops pool, so at default settings (the slider off) neither drops, and every setting that raises Liquor Holster's chance raises theirs identically, because it is the same roll.
    - **`sigdrop` kept, repurposed as a test command.** `sigdrop status | crown | belt | off` forces the named item on every monster kill via `g_SigDropForce` (-1 off/default, 0 crown, 1 belt); it no longer sets a rate, an ancient-tier percentage or a pity counter - those concepts are gone, and the normal rate always follows `angelicdrop`.
    - **The vanilla-roll gap (accepted; a follow-up issue tracks it separately).** Liquor Holster can also drop from the game's own Angelic roll under an "Angelic item drop chance" effect (Blood Pact / dungeon modifier). Headhunter and Tyrant's Crown are not in the game's own unique loot list (`GetUniqueRepoStruct` has no entry for them; `SpawnSignatureItem` builds them through the forged-item path the Custom Forge uses instead), so that path can never drop them - only ForgePact's own die does. Magic Find's effect on the game's own roll was not measured either. Matching this would need a hook on the game's own Angelic roll.
    - **Dilution (accepted).** Joining the pool adds two more entries to whatever the validation loop accepted (the research doc recorded 47 at one point in time; the live pool size was never re-measured, so this is UNVERIFIED) - roughly 4% rarer for every existing Angelic/Unholy item. The owner accepted this as what "the same code path" means; a separate die at Liquor Holster's own per-item chance was rejected (it would duplicate the Angelic computation and need the pool size on every kill, so "same rate" would be a formula that could drift from the real path rather than the real path itself).
    - **What is unverified live.** The pool append, the per-pick dispatch, the equal three-way share (`signature_equal_share`, 3000 synthetic kills, 800-1200 hits per candidate out of a pool of one unique plus both signature entries) and the `sigdrop crown|belt` force path are all covered by `test_headhunter_dispatch.py`'s `test_signature_drop_target` (native harness, each scenario shown failing against the pre-#63 source) and `test_signature_drop_contract.py` (source contract, same). None of it has run against the real game since the change - `fetch_toolchain.py --verify-only` failed when this was written (`modfiles_shipped/*.dll` MISSING), so the build criterion and the in-game check below are both still open.
    - **The in-game check, once a build is available (human-pending; a DLL is only installed on the user's say-so).** `angelicdrop 1` then `angelicdrop status` - pool count two more than before; `angeliclist` lists both signature entries; `sigdrop belt` + one kill drops a dressed Headhunter, `sigdrop crown` a Tyrant's Crown, `sigdrop off` stops forcing; with `angelicdrop 1` running normally (no force), `bp_ipc\out.txt` shows a `sigdrop: <item> dropped at ...` line within roughly 150 kills.
    - **Tests:** `tests/test_headhunter_dispatch.py`'s `test_signature_drop_baseline` + `test_signature_drop_target` (+ `headhunter_dispatch_harness.cpp`), `tests/test_signature_drop_contract.py`.
22. **"Restart zone at any time" (`restartanytime`, issue #8) opens the Restart button's own gate while the mouse is on it - mouse only, and an accepted risk (2026-09-22):**
    - **What is measured.** Three research rounds (`ForgePact/docs/restart-always-available-research.md`) found that the pause menu's Restart is refused on the button's own `manualDisable`, which the game rewrote to `true` on every observed `UiSetFocus` call and every observed draw while in combat. Round 3 (2026-09-22, research DLL `d40a4f25…`, combat against the town training dummies) wrote it `false` inside the game's own `UiSetFocus` call, on the button that call is handed: with `wasInCombat=bool:true` at the call, the press reached `UiAIngameRestart` (`calls=1`) and the zone restarted (T2 with both members, T3 with `manualDisable` alone). `enabled` alone did not unlock it, so the mod never touches `enabled`.
    - **How it is shaped.** One value inside a call the game is already making, never a restart of our own: the hook writes, then hands the call to the game's body; nothing is restored afterwards, because the game recomputes the member the next frame. The button is identified by its own `uiNodeCallstack` (`PauseRestart`), never by position, instance id or the call's `self` - round 3's T5 showed the instrument's unfiltered `arg0` write landing on other buttons the cursor crossed, which the identity check exists to prevent.
    - **Mouse only (accepted by the owner, 2026-09-22).** `UiSetFocus` was not observed to be called with the mouse off the menu (`calls=0`); keyboard and controller were not tested. Keyboard navigation did not reach the pause menu's buttons at all in round 3's session, and no controller was available, so T4 was not run: a keyboard or controller path to Restart, if one exists, is not covered.
    - **Greyed until hovered (accepted by the owner, 2026-09-22).** The greyed look follows the value set before the draw (inferred from the draw-site hold, not measured at step time): a hold of both members at the Restart draw, with the cursor elsewhere, left Restart drawn greyed. So in combat Restart still looks greyed, lights up once the cursor is on it, and works when clicked. The panel sub-text and the release notes say so.
    - **Enemies alive (accepted risk).** Quoting the owner's decision of 2026-09-22: "**risk accepted** - a restart while enemies are alive is accepted". The mod lets the game's own Restart run in a state the game would have refused; the restart itself is the game's.
    - **Live confirmation (2026-09-22, player build `BloodPactPlugin_ship.dll` sha256 `242f1f10…`, ForgePact `00b95c6`).** `restartanytime 0`, in combat: Restart refused (nothing happened). `restartanytime 1`: hook installed on both of `HookOneScript`'s routes (`restartanytime: hook installed -> ON`, no `TABLE-ONLY`); an in-combat Restart on an ordinary zone restarted it (`written=88 passed=0 otherNode=50 unreadable=0`). `restartanytime 0` again: Restart refused, `written` unchanged at 88. The boss-room outlier was not run (the owner's choice, "no need"); round 3 fought in `Town_01_rm` only.
    - **Research probe and mod in one session (not run live).** From a static reading of `HookOneScript` and `RestartProbeAttach`: the mod hooks `UiSetFocus` through both routes, so its saved original is a trampoline and the table entry is our own hook, neither of them code inside `Hero_Siege.exe` - which is why the probe's `UiSetFocus` row stays unbound (unlike `ZoneGenRestart`, which attaches under table-only `zonegenlog`). With the mod's hook in first, a later `restartprobe hook` reports that one row `blocked` and attaches the other 21. With `restartprobe hook` first, the mod's install asks the hooking library to detour an address the probe already patched; `docs/prospect-window-research.md` says the second hook on an address fails, measured only in the other order, so this is unverified - if it fails, the mod logs `restartanytime: hook TABLE-ONLY -> OFF` and stays off for the session. Neither order was run. Run the probe or the mod in a session, not both. Players never meet either case: the player build has no probe (`restartprobe` is behind `#ifndef FORGEPACT_RELEASE`).
    - **Tests:** `tests/test_restart_anytime_contract.py` (`RestartAnytimeContractTests`, `RestartResearchDocTests`), `tests/test_restart_anytime_behavior.py` + `restart_anytime_harness.cpp`.

---

## Maintenance Triggers

- **Game Executable Updates:** When a new Season 10 patch releases, verify that spawner object names, GML function names, and `LoadDrops` drop family indices remain valid. The player build contains **no raw game addresses** to re-verify (Known Limitations item 11) — everything resolves by name or off a YYToolkit struct — so a new build should surface as named lookups failing, not as a crash. Player-build closure names (`anon@N@...`) come from `HeroSiege::Scripts` constants, so regenerating hs-game-sdk after a patch that moves one surfaces it as a compile error and a failing `test_player_build_closure_names_all_match_the_sdk`, instead of a silent runtime name-lookup failure. The dev-only `kCiCallMethodFnRva` does need re-verifying before anyone runs `citrace collect confirm native`; `citrace dispatchdump` / `citrace symdump` in the research build are the tools for re-locating it.
  - **Closure names move with every game patch.** The player build now spells them through `HeroSiege::Scripts` constants (above), so a regeneration surfaces as a compile error rather than a silent hook. Done (2026-09-18): player names now match hub `4539e68`'s SDK, regenerated for the current game build (`data.win` `07D864C9…`) - e.g. `GenerateItemHash@anon@4645` is `GenerateItemHash@anon@4791` there - on ForgePact branch `fix/closure-names-current-game`, merged into `feat/prospect-window-research`. The 25 research-only `citrace` closure literals moved with them; the seven `Quest_Object_Parent_obj` and ten `Profile_Manager_obj` closures were mapped by ordinal position within their Create event (equal counts, monotone offset growth), so the `m_Quest*` method-name labels the research code attaches carry over by inference only, not observed on the current build. `test_citrace_closure_hooks_cover_every_sdk_closure_of_their_objects` now fails the next regeneration loudly (naming which closures exist and which are hooked) instead of drifting silently. ForgePact's release CI (`forgepact-release.yml`) builds against hub `main`'s SDK, so hub #74 (the SDK regeneration) and this fix must land together - merging one without the other breaks the release build one way or the other. `prospectprobe`'s table already uses SDK constants.
- **YYToolkit Header / Binary Sync:** Any rebuild of `YYToolkit.dll` requires recompiling `BloodPactPlugin` against matching headers in `plugin_build\include\` to prevent vtable mismatch crashes. Because the plugin now reads `CScriptRef` directly (under `/DYYTK_DEFINE_INTERNAL=1`), a header update also has to keep those layouts truthful — the headers' own `static_assert(sizeof(YYObjectBase) == 0x88)` is the compile-time check, and `petquest stat`'s `REFUSED (structural)` line is the runtime one.
  - The hub's `third_party/yytoolkit/` series is pinned to the same upstream commit as these headers (`5a95e46`, tag v4.0.1) and touches none of the plugin-facing files (`YYToolkit/source/YYTK/Shared/`, `ExamplePlugin/`), so a DLL built from it is meant to keep working with a plugin compiled against the unmodified pinned headers. One behaviour does change for a plugin: `CreateCallback(EVENT_OBJECT_CALL)` returns `AURIE_UNAVAILABLE` instead of succeeding with a callback that never fires. `BloodPactPlugin` registers `EVENT_FRAME` only, so this is not expected to affect it — observed live on 2026-09-19: `BloodPactPlugin` v1.4.4 loaded and initialized against a build of this series, `EVENT_FRAME` kept firing (it drives the plugin's IPC poll), and zero `REFUSED EVENT_OBJECT_CALL` lines were logged in that idle session (see `third_party/yytoolkit/README.md`, "Second launch results (2026-09-19, plugin loaded)").
- **Dependency Upgrades (YYToolkit):** A change to the distributed YYToolkit — a new upstream version, a fix, a build flag — is made in the hub, not here: move the pin in `third_party/yytoolkit/upstream.json`, refresh or add patches under `third_party/yytoolkit/patches/` (each with its mandatory header), and rebuild with `tools/build_yytoolkit.py`; that directory's README has the procedure and the launch gate. What has to survive an upstream bump is the whole of `patches/series`, not "the disk cache and the `ExecuteIt` change" — that two-item list described the old notice, and the old notice did not describe the binary. Never rebuild `YYToolkit.dll` from `yytoolkit-modified/` or from any tree that is not the pinned commit plus the series.
- **Moving the `YYToolkit.dll` pin (merged, PR 53; not yet shipped in a release):** PR 53 (1) repointed `tools/toolchain-pins.json` at the hub release asset for a launch-gated build of the hub series, with its SHA-256 and the hub commit as provenance — the pin count stays eleven; (2) rewrote `yytoolkit-modified/NOTICE.md` to point at the hub directory and deleted the two whole-file copies in the same commit; (3) corrected `CREDITS.md` and `README.md`, which used to say "one modified source file"; (4) ships the notice and `YYToolkit-BUILD-INFO.json` with the binary — `build_release.py` now copies both into `modfiles/` alongside `README.md`, `CREDITS.md` and `LICENSE`; (5) carries `release-notes-v1.4.4.md`, naming what was and was not launch-tested rather than claiming a settled fix; (6) deleted `ensure_ri_cache`'s hand-measured RVA table from `src/forgepact.py`, which patch `0001` made unnecessary. It merged to `origin` after the launch gate carried a plugin-loaded row and the owner's confirmation, together with HS-Offline-Tracker's equivalent (PR 3) — see `third_party/yytoolkit/README.md`, "Where the binary is published". The hub release its pin names exists and is published (not marked `--latest`), and the asset URL it points at resolves. **What remains is the owner's decision to tag and release ForgePact 1.4.4** (and HS-Offline-Tracker 0.1.3 alongside it, since both install to `mods/aurie/YYToolkit.dll` with overwrite semantics) — that is a separate, still-outstanding step from either the merge or the published library release.

---

## Source Documents & Evidence References
- Submodule Readme: `../../../ForgePact/README.md`
- Plugin Build Specifications: `../../../ForgePact/plugin/BUILD.md`
- Plugin Build Script: `../../../ForgePact/plugin_build/build.bat`
- Release Packaging Script: `../../../ForgePact/build_release.py`
- Modified YYToolkit, source of truth (hub patch series, build tool, provenance story): `../../../third_party/yytoolkit/README.md`, `../../../third_party/yytoolkit/NOTICE.md`, `../../../tools/build_yytoolkit.py`, `../../adr/0002-modified-yytoolkit-is-a-patch-series-in-the-hub.md`, `../../agents/yytoolkit-provenance.md`
- `../../../ForgePact/yytoolkit-modified/NOTICE.md` now points at the hub series above, not at the `bb113eef…` DLL a player's installed copy still carries; for that DLL's own notice and what it left out, see the pin table above and [`docs/agents/yytoolkit-provenance.md`](../../agents/yytoolkit-provenance.md).
- Credits & License Notices: `../../../ForgePact/CREDITS.md`
- Season 10 Special Content Notes: `../../../ForgePact/docs/S10-special-content-notes.md`
- Dungeon Key & Drop Research: `../../../ForgePact/docs/dungeon-key-research.md`
- Angelic Drop Research: `../../../ForgePact/docs/angelic-drop-research.md`
- Satanic Zone Mods Research: `../../../ForgePact/docs/satanic-zone-mods-research.md`
- Map Reveal Research (why a revealed map had no monsters, and the spawner regression): `../../../ForgePact/docs/map-reveal-research.md`
- Pet Quest Collector (active plan + findings log): `../../../ForgePact/docs/pet-quest-collector-plan-c-direct-invocation.md`, `../../../ForgePact/docs/pet-quest-collector-c-research.md`
- Prospect Window Research (issue #9, Phase 0 pending): `../../../ForgePact/docs/prospect-window-research.md`
- Restart-Always-Available Research (issue #8; round 1 measured 2026-09-22 - the gate is upstream of the Restart activation, not identified; round 2 measured the same evening - the Restart button's own `enabled`/`manualDisable` flip with combat and a draw-time hold of either is rewritten before use, not identified; round 3 measured the same night - the Restart button's own `manualDisable` written false inside `UiSetFocus` unlocks an in-combat press, shipped as `restartanytime`): `../../../ForgePact/docs/restart-always-available-research.md`
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
