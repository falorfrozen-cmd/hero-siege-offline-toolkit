# HS-Offline-Tracker Module Development Guide

## Module Overview & Metadata
- **Module Name:** HS-Offline-Tracker (HS Offline Tracker)
- **Submodule Path:** `HS-Offline-Tracker`
- **Reviewed Git Revision:** `1ceda0eeff9b2043d2919f4369bb5096189192a1` (Tag: `v0.1.2`, Branch: `main`)
- **Revision Date:** `Sun Sep 6 05:25:45 2026 +0300`
- **Commit Message:** `fix: a re-picked alert sound plays, and listed weapons make a card`
- **Source Availability:** Full application source is present (Svelte 5 / Vite 8 frontend, Rust / Tauri 2 desktop shell, C++20 Aurie producer module, C++20 native bridge prototype, modified YYToolkit loader sources, demo fixtures, and Node.js workflow scripts).
- **CI / Pipeline Availability:** No build or test CI; validation is conducted locally via npm, Cargo, and CMake / CTest suites. GitHub Actions carries only automation: `notify-hub.yml` / `notify-hub-release.yml` tell the hub about new commits and releases, and `ai-review.yml` runs an opt-in AI code review (see [AI Code Review](#ai-code-review-ai-reviewyml)).
- **Purpose & Scope:** Standalone offline-first session journal, rarity drop alert engine, run history recorder, and compact always-on-top overlay for Hero Siege offline/single-player gameplay. Consumes versioned NDJSON event streams from local files or named pipes and monitors local read-only character save files.

---

## Architecture & Repository Map

### Repository Layout
- `src/`: Svelte 5 frontend user interface compiled with Vite 8.
  - `App.svelte`: Compact transparent always-on-top overlay window displaying active run counters, drop alerts, and live zone indicators.
  - `Dashboard.svelte`: Primary tabbed management window coordinating sub-views within `<svelte:boundary>` error boundaries.
  - `Stats.svelte`, `Runs.svelte`, `Shop.svelte`, `Codex.svelte`: Sub-views for session telemetry, run history, shopping wishlists, and Satanic zone codex tracking.
  - `SoundFilter.svelte`, `Settings.svelte`, `About.svelte`: Alert sound configuration, game link / sensor management, and application info.
  - `Flourish.svelte`, `Ticker.svelte`: Notification card stacks and compact status banners.
  - `skin.svelte.js`: Obsidian-themed visual definitions, SVG path catalogs, and responsive layout styling.
  - `audio.js`: Two-voice Web Audio synthesizer and procedural audio mixer handling rarity alert sounds.
  - `main.js`: Svelte 5 application mounting entry point (`mount(App, ...)` / `mount(Dashboard, ...)`).
  - `assets/`: Sound effects (`assets/sounds/`) and brand artwork (`assets/brand/`).
- `src-tauri/`: Tauri v2 desktop runtime written in Rust (2021 edition, `rust-version = "1.88"`).
  - `main.rs`, `lib.rs`: Application initialization, window management (`dashboard` and `main` overlay), system tray, single-instance plugin registration, autostart registry configuration, and IPC command handlers.
  - `sniffer.rs`: Transport ingestion layer; frames and parses NDJSON lines from `events.ndjson` and local named pipes (`\\.\pipe\HSOfflineTrackerBridge_<pid>`), validates Protocol v1 contracts, tracks sensor health, and monitors game process lifecycle via `sysinfo`.
  - `save_source.rs`: Passive local character save watcher (`%LOCALAPPDATA%\Hero_Siege\hs2saves\herosiegeN.hss`); handles XOR, zlib, and Base64 decoding with double-snapshot verification.
  - `stats.rs`: Core statistics engine computing session deltas, kill counters, currency purses, run times, and rarity tallies.
  - `items.rs`, `parser.rs`: Season 10 game item catalogs, stat models, drop fingerprinting, and item resolution.
  - `presence.rs`: Discord Rich Presence client (`discord-rich-presence`).
  - `log.rs`: Thread-safe file-backed logging.
  - `tauri.conf.json`: Tauri v2 configuration specifying dual-window geometry, asset protocol security scopes, resource bundling, and NSIS installer properties.
- `aurie-producer/`: Active native producer module compiled as a C++20 dynamic library (`HSOfflineTrackerProducer.dll`).
  - `src/module.cpp`: Aurie module lifecycle, GML named routine hook registration via YYToolkit (`gml_Script_GoldLogAdd`, `gml_Script_ExperienceUpdate`, `gml_Script_EnemyAddStatistics`, `gml_Script_LootGroundInit`, `gml_Script_RoomGoto`), fallback adaptive profiling, and non-blocking queueing.
  - `src/counter_validation.cpp`: Strict validation of GML call arguments (non-negative integral checks, rarity filters).
  - `profiles/`: Exact-match code profiles (`s10-code-1dde65e4.json`, `s10-code-c4dc91d9.json`) with PE timestamp and `.text` section SHA-256 validation.
  - `build.ps1`, `CMakeLists.txt`: PowerShell and CMake build configurations linking YYToolkit headers and bridge transport sources.
  - `tests/`: Native verification suites (`counter_validation_smoke.cpp`, `code_gate_smoke.cpp`).
- `aurie-loader/`: Bundled Aurie and YYToolkit loader dependencies distributed with the application.
  - `AurieCore.dll`, `YYToolkit.dll`, `AuriePatcher.exe`: Binaries deployed into game directories by the Game Link installer.
  - `yytoolkit-modified/`: AGPL-3.0 corresponding source code notice (`NOTICE.md`) and patch files (`Generic-RunnerInterfaceNew.cpp` disk cache, `Hooks.cpp` disabling problematic `ExecuteIt` hook).
- `bridge-native/`: Standalone native bridge prototype (research / proof-of-concept without Aurie/YYToolkit dependencies).
  - `src/sensor_runtime.cpp`, `src/event_protocol.cpp`, `src/named_pipe_transport_win32.cpp`, `src/build_fingerprint_win32.cpp`: C++20 drop sensor using MinHook.
  - `include/hsot/`: C++ header definitions (`event_protocol.h`, `bridge_export.h`, `named_pipe_transport.h`).
  - `tools/verify_profile.py`: Offline PE analysis script auditing target game binaries.
  - `tests/protocol_smoke.cpp`: Protocol serialization unit test.
- `scripts/`: Node.js development, testing, and packaging automation.
  - `tauri.mjs`: Tauri CLI invocation wrapper injecting cargo bin directory into the process `PATH`.
  - `test.mjs`: Direct launcher for `cargo test` supporting working directories with spaces.
  - `replay-demo.mjs`: Deterministic offline protocol stream replayer for UI and sound validation.
  - `generate-alerts.mjs`, `set-version.mjs`: Procedural sound generation and version synchronization.
- `fixtures/`: `demo-session.ndjson` protocol test fixture.
- `PROTOCOL.md`: Authoritative Protocol v1 specification for UTF-8 NDJSON records.

---

## Component Architecture & Data Pipeline

```text
+---------------------------------------------------------------------------------------+
|                                    GAME PROCESS                                       |
|  [gml_Script_GoldLogAdd]  [gml_Script_ExperienceUpdate]  [gml_Script_EnemyAddStatistics]   |
|  [gml_Script_LootGroundInit]                      [gml_Script_RoomGoto]              |
|                                         |                                             |
|                                         v (Aurie / YYToolkit Hooks)                   |
|                        +----------------------------------+                           |
|                        |   HSOfflineTrackerProducer.dll   |                           |
|                        |  - Non-blocking 2048-entry queue |                           |
|                        |  - 16ms background worker thread |                           |
|                        +----------------------------------+                           |
+------------------------------------------|--------------------------------------------+
                                           |
                                           v (Local Named Pipe: \\.\pipe\HSOfflineTrackerBridge_<pid>)
+---------------------------------------------------------------------------------------+
|                                 DESKTOP RUNTIME (Rust / Tauri)                        |
|                                                                                       |
|   +------------------------------------+      +-----------------------------------+   |
|   |          sniffer.rs                |      |         save_source.rs            |   |
|   |  - Named pipe client               |      |  - Passive .hss save watcher      |   |
|   |  - events.ndjson file tailing      |      |  - XOR/zlib/Base64 decode         |   |
|   |  - Protocol v1 validator           |      |  - Double-snapshot validation     |   |
|   +-----------------+------------------+      +-----------------+-----------------+   |
|                     |                                           |                     |
|                     +---------------------+---------------------+                     |
|                                           |                                           |
|                                           v                                           |
|                                 +--------------------+                                |
|                                 |      stats.rs      |                                |
|                                 | - Session deltas   |                                |
|                                 | - Reconciled stats |                                |
|                                 | - Run aggregation  |                                |
|                                 +---------+----------+                                |
|                                           |                                           |
|                       +-------------------+-------------------+                       |
|                       | (Tauri IPC Events / State Sync)       |                       |
|                       v                                       v                       |
|         +---------------------------+           +---------------------------+         |
|         |     Dashboard Window      |           |   Transparent Overlay     |         |
|         |  (Svelte 5 / Dashboard)   |           |    (Svelte 5 / App.svelte) |        |
|         +---------------------------+           +---------------------------+         |
+---------------------------------------------------------------------------------------+
```

---

## Representative Change Workflow

To modify or extend an event handler or user interface feature (for example, adding support for a new protocol field or updating the overlay UI):

1. **Protocol Contract Update (if changing data exchange):**
   - Update `PROTOCOL.md` to document the new field or record type under Protocol v1 specifications.
   - Update C++ definitions in `bridge-native/include/hsot/event_protocol.h` and serialization in `bridge-native/src/event_protocol.cpp`.
   - Update Rust deserialization in `src-tauri/src/sniffer.rs`.
2. **Backend Engine & State Logic:**
   - Update `src-tauri/src/stats.rs` or `src-tauri/src/parser.rs` to process the parsed event.
   - Run backend tests to verify deserialization and state calculation:
     ```powershell
     npm test
     ```
3. **Frontend Presentation (Svelte):**
   - Update UI components in `src/` (e.g., `src/App.svelte` or `src/Dashboard.svelte`).
   - Validate frontend bundling and syntax:
     ```powershell
     npm run build
     ```
4. **End-to-End Replay Verification:**
   - Launch the development application:
     ```powershell
     npm start
     ```
   - In a separate terminal, replay the deterministic test fixture:
     ```powershell
     npm run demo
     ```
   - Observe real-time updates in both the Dashboard and the compact Overlay window.
5. **Full Quality Gate:**
   - Execute the combined build and test gate:
     ```powershell
     npm run check
     ```

---

## Supported Platforms, Prerequisites & Dependencies

### Supported Platforms
- **Primary / Packaged Desktop:** Windows 10 / Windows 11 x64 with Microsoft Edge WebView2 Runtime (Evergreen).
- **Development Shell:** Windows PowerShell, PowerShell Core, or standard POSIX shells for frontend web tooling.
- **Experimental / Basic UI:** Linux x64 with Wayland / X11 (supports basic UI compilation and clipboard data control via `arboard`; native game sensors are Windows x64 only).

### Prerequisites & Tools
- **Node.js:** Node.js `^20.19.0` or `>=22.12.0` (matching Vite 8 engine constraints).
- **Rust Toolchain:** Rust `1.88.0` or newer installed via rustup (requires `is_multiple_of` and `is_none_or` features).
- **C++ Toolchain (Native Producer & Bridge):** Microsoft Visual Studio 2022 C++ Build Tools (MSVC v143 toolset) targeting `x64`.
- **CMake:** Version `3.24+` (for `aurie-producer` and `bridge-native` builds).
- **Microsoft Edge WebView2 Runtime:** Required for running the Tauri desktop application.

### Dependency Manifests
- **Frontend Dependencies (`package.json`):**
  - Production: `@tauri-apps/api: ^2.11.1`
  - Development: `@sveltejs/vite-plugin-svelte: ^7.3.0`, `@tauri-apps/cli: ^2.11.4`, `svelte: ^5.46.4`, `vite: ^8.2.2`
- **Desktop Backend Dependencies (`src-tauri/Cargo.toml`):**
  - `tauri: 2` (features: `tray-icon`, `image-png`, `protocol-asset`)
  - `tauri-plugin-global-shortcut: 2`, `tauri-plugin-dialog: 2`, `tauri-plugin-single-instance: 2`
  - `arboard: 3`, `serde: 1`, `serde_json: 1`, `flate2: 1`, `base64: 0.22`, `sysinfo: 0.33`, `discord-rich-presence: 1.1.0`
  - Windows specific: `winreg: 0.52`
- **Native Producer Dependencies (`aurie-producer/CMakeLists.txt`):**
  - Local YYToolkit SDK: headers from `../../ForgePact/plugin_build` (`include/YYToolkit`, `include/Aurie`, `YYTK_Shared_Types.cpp`).
  - System libraries: `bcrypt.lib`, `user32.lib`.

---

## Command Reference

| Command | Working Directory | Shell / Platform | Prerequisites | Expected Result | Side Effects | Status |
|---|---|---|---|---|---|---|
| `npm run dev` | `HS-Offline-Tracker/` | PowerShell / Bash | Node.js >= 20.19 | Starts Vite development server on `http://localhost:5176`. | Listens on local port 5176 | Inspected |
| `npm run build` | `HS-Offline-Tracker/` | PowerShell / Bash | Node.js >= 20.19 | Compiles Svelte 5 frontend into static assets in `dist/`. | Overwrites `dist/` contents | Inspected |
| `npm start` | `HS-Offline-Tracker/` | PowerShell / Bash | Node.js, Rust >= 1.88 | Launches Tauri v2 desktop application in development mode with hot reloading. | Opens Dashboard and Overlay windows | Inspected |
| `npm test` | `HS-Offline-Tracker/` | PowerShell / Bash | Node.js, Rust >= 1.88 | Executes `node scripts/test.mjs`, running all Rust unit tests in `src-tauri`. | Read-only test execution | Inspected |
| `npm run check` | `HS-Offline-Tracker/` | PowerShell / Bash | Node.js, Rust >= 1.88 | Executes `npm run build && npm test`. | Compiles `dist/` and runs tests | Inspected |
| `npm run demo` | `HS-Offline-Tracker/` | PowerShell / Bash | Node.js >= 20.19 | Executes `node scripts/replay-demo.mjs`, appending `fixtures/demo-session.ndjson` to `events.ndjson`. | Appends lines to `%LOCALAPPDATA%\HS Offline Tracker\events.ndjson` | Inspected |
| `npm run package` (or `npm run release`) | `HS-Offline-Tracker/` | PowerShell / Bash (Windows x64) | Node.js, Rust >= 1.88, WiX/NSIS | Builds release binaries and NSIS installer bundle in `src-tauri/target/release/bundle/nsis/`. | Generates release binaries and installer | Inspected |
| `npm run generate:sounds` | `HS-Offline-Tracker/` | PowerShell / Bash | Node.js >= 20.19 | Executes `node scripts/generate-alerts.mjs` to synthesize procedural alert audio. | Updates audio assets in `src/assets/sounds/` | Inspected |
| `powershell -File aurie-producer/build.ps1` | `HS-Offline-Tracker/` | PowerShell (Windows x64) | MSVC x64, CMake >= 3.24, YYToolkit SDK | Builds `HSOfflineTrackerProducer.dll` in `aurie-producer/build/bin/Release` and runs CTest unit tests. | Creates `aurie-producer/build/` artifacts | Inspected |
| `cmake -S bridge-native -B bridge-native/build -A x64` | `HS-Offline-Tracker/` | PowerShell / CMD (Windows x64) | MSVC x64, CMake >= 3.24 | Configures standalone native bridge prototype build. | Generates CMake build directory | Inspected |
| `cmake --build bridge-native/build --config Release` | `HS-Offline-Tracker/` | PowerShell / CMD (Windows x64) | CMake configured | Compiles `HSOfflineTrackerBridge.dll` and test binaries. | Outputs binaries in `bridge-native/build/` | Inspected |
| `ctest --test-dir bridge-native/build -C Release --output-on-failure` | `HS-Offline-Tracker/` | PowerShell / CMD (Windows x64) | Bridge built | Runs bridge prototype CTest suite (`hsot_protocol_smoke`). | Read-only test execution | Inspected |
| `python bridge-native/tools/verify_profile.py <path_to_exe>` | `HS-Offline-Tracker/` | PowerShell / CMD | Python 3 | Inspects PE headers, sections, and export tables of target game executable without running it. | Outputs static analysis report to console | Inspected |

*Status notes:* Commands marked **Inspected** have been statically verified against source code, manifests, and script declarations without invoking redundant release packaging.

---

## Protocol Specification & Persistence Models

### Protocol v1 (UTF-8 NDJSON)
All event streams delivered via named pipe (`\\.\pipe\HSOfflineTrackerBridge_<pid>`) or event files (`events.ndjson`) conform to Protocol v1. Each record is a single line of UTF-8 JSON terminated by `\n`. Every record must declare version 1 via `"protocol": "hs-offline-tracker/1"` or `"v": 1` (producers should provide both).

#### Canonical Record Types
1. **Heartbeat & Status (`heartbeat`, `bridge_status`):**
   ```json
   {"protocol":"hs-offline-tracker/1","v":1,"kind":"heartbeat"}
   {"protocol":"hs-offline-tracker/1","v":1,"kind":"bridge_status","state":"transport_ready"}
   ```
   - `state` values: `transport_ready` (ready), `scaffold_ready` (initializing), `blocked` / `transport_error` (fail-closed sensor errors).
2. **Session Deltas (`session_delta`):**
   ```json
   {"protocol":"hs-offline-tracker/1","v":1,"kind":"session_delta","gold":1250,"xp":42000,"kills":3,"source":"aurie_named_gml"}
   ```
   - Emitted by the live sensor after game routines finish. Gold, XP, and kills are positive incremental values.
3. **Ground Drops & Pickups (`ground_drop`, `item_picked_up`):**
   ```json
   {"protocol":"hs-offline-tracker/1","v":1,"kind":"ground_drop","event_id":"run-42-drop-7","source":"monster","item":{"name":"Astral Covenant","rarity":"Angelic","tier":6,"item_type":3,"item_id":1,"weapon_type":0,"seed":91,"amount":1,"magic_find_drop":true,"unscaled":false,"hash":"stable-item-hash","fingerprint":"stable-instance-id"}}
   {"protocol":"hs-offline-tracker/1","v":1,"kind":"item_picked_up","event_id":"run-42-drop-7-pickup","source":"monster","hash":"stable-item-hash","fingerprint":"stable-instance-id"}
   ```
   - Rarity IDs: `4` (Satanic), `6` (Angelic), `7` (Heroic), `9` (Unholy), `10` (Set). Sources like `vendor`, `trade`, `quest`, `craft`, or `player_drop` are ignored.
4. **Vitals & Zone Progression (`vitals`, `room`, `satanic_zone`):**
   ```json
   {"protocol":"hs-offline-tracker/1","v":1,"kind":"room","room":"Act_09_03"}
   {"protocol":"hs-offline-tracker/1","v":1,"kind":"satanic_zone","zone":"Satanic_9_3","buffs":[6,14,21],"debuffs":[3,12]}
   {"protocol":"hs-offline-tracker/1","v":1,"kind":"vitals","magic_find":12840,"level":100,"hero_level":300,"satanic_here":true}
   ```
5. **Sensor Diagnostics (`sensor_diagnostic`):**
   ```json
   {"protocol":"hs-offline-tracker/1","v":1,"kind":"sensor_diagnostic","gold_calls":2,"gold_accepted":2,"gold_rejected":0,"gold_delta_total":2500,"xp_calls":1,"xp_accepted":1,"xp_rejected":0,"xp_delta_total":42000,"kill_candidate_calls":3,"kill_emission_enabled":true,"kill_route":"gml_Script_EnemyAddStatistics"}
   ```

### Save File Reconciliation vs. Live Sensor Stream
- **Save Watcher Boundaries:** The passive watcher reads `%LOCALAPPDATA%\Hero_Siege\hs2saves\herosiegeN.hss`. It provides delayed snapshots of character levels, total experience, total monster kills, and boss/chest counters.
- **Reconciliation:** Absolute save snapshots are reconciled with live session deltas in `src-tauri/src/stats.rs` to ensure progress is never double-counted when both save files and the live sensor are active.
- **Fail-Closed Character Saves:** Changed save files require two identical snapshots, strict XOR/zlib checksums, and Base64 decoding. If a write is incomplete, the tracker discards it and maintains the last known good state.

---

## Native Components: Active Production vs. Research Prototype

### Active Production: Aurie Producer (`aurie-producer/`)
- **Integration Model:** Loaded by Aurie into the offline game process. Uses YYToolkit to dynamically resolve named GML routines (`gml_Script_GoldLogAdd`, `gml_Script_ExperienceUpdate`, `gml_Script_EnemyAddStatistics`, `gml_Script_LootGroundInit`, `gml_Script_RoomGoto`).
- **Resilience:** Operates across game updates via named routine lookup. If the executable `.text` hash matches a reviewed profile (`s10-code-c4dc91d9`), it enforces exact argument layouts and caller allowlists. Unrecognized builds fall back to the **adaptive profile** (dynamic argument typing and 1.5 s quiet window after room transitions).
- **Thread Safety:** Hooks only update atomics and push 3-integer POD snapshots into a fixed 2048-entry queue. A dedicated low-priority worker wakes every 16 ms to serialize JSON and send records through the named pipe. No blocking pipe I/O or JSON formatting occurs on game threads.
- **Packaging:** Built DLL (`aurie-producer/build/bin/Release/HSOfflineTrackerProducer.dll`) is bundled into the installer and deployed by the Game Link settings page.

### Bundled Loader & Modified YYToolkit (`aurie-loader/`)
- **Loader Files:** Distributes `AurieCore.dll`, `YYToolkit.dll`, and `AuriePatcher.exe`.
- **Modifications (AGPL-3.0 Compliance):**
  1. `Generic-RunnerInterfaceNew.cpp`: Adds a disk cache (`<exe>.yytkcache`) for runner interface lookup, eliminating a 1-minute startup disassembly scan.
  2. `Hooks.cpp`: Disables the `ExecuteIt` hook (`EVENT_OBJECT_CALL`), preventing instance index corruption (`Unable to find any instance for object index`) on Hero Siege Season 10. `EVENT_FRAME` via `HkPresent` remains intact.
- **Source Notice:** Full corresponding source notice is preserved in `aurie-loader/yytoolkit-modified/NOTICE.md`.

### Research Prototype: Native Bridge (`bridge-native/`)
- **Status:** Experimental research sensor without Aurie or YYToolkit dependencies; **not bundled** in end-user installers.
- **Mechanism:** Direct hook on `gml_Script_GetRareDropAnnouncement` via MinHook.
- **Strict Gating:** Deliberately locked to a single reviewed build fingerprint (SHA-256 `5F8085456A27109681403D8C57533E6999FBD0664752FF5F2856985B5FBBDE71`, size `303584768`, timestamp `0x6A8C4540`). Any mismatch installs **zero hooks**.

---

## Testing & Validation Classification

### 1. Game-Free / Offline Automated Checks
- **Svelte / Vite Build:** `npm run build` verifies frontend templates, component bindings, CSS styles, and asset imports.
- **Rust Desktop Test Suite:** `npm test` executes all unit tests in `src-tauri/` testing NDJSON parsing, protocol decoding, save file decoding, and stats aggregation.
- **Native C++ Smoke Tests:**
  - `hsot_counter_validation_smoke`: Verifies GML argument validation logic for gold, XP, and kills.
  - `hsot_aurie_code_gate_smoke`: Validates PE header parsing and SHA-256 `.text` fingerprinting.
  - `hsot_protocol_smoke`: Validates NDJSON serialization and Protocol v1 envelope compliance.
- **Offline Protocol Replay:** `npm run demo` feeds `fixtures/demo-session.ndjson` to the live UI without requiring a game instance.

### 2. Live-Game Dependent Checks (**Unverified in automated pipelines**)
- Live Aurie injection and named GML hook validation in running `Hero_Siege.exe` processes.
- Named pipe streaming under high-frequency combat loads.
- Active save file polling during live in-game saving intervals.

---

## Troubleshooting & Fail-Closed Scenarios

1. **Overlay Not Rendering / Solid Black Background:**
   - *Cause:* Transparent window composition is unsupported or hardware acceleration failed.
   - *Resolution:* Verify Microsoft Edge WebView2 Evergreen Runtime is installed. On Linux, ensure a compositor supporting Wayland / X11 transparency is active.
2. **Sensor State Shows "Blocked" or "Transport Error":**
   - *Cause:* An unrecognized game build was detected, or named pipe connection timed out.
   - *Resolution:* Check **Settings > Game link** to verify sensor status. Confirm that `Hero_Siege.exe` is an offline/single-player build (EAC-enabled Steam builds intentionally block sensor attachment).
3. **No Drop Alerts or Session Deltas During Play:**
   - *Cause:* Live sensor is not installed, or game was launched without Aurie.
   - *Resolution:* In **Settings > Game link**, click **Install live sensor** while the game is closed. Confirm `mods/aurie/HSOfflineTrackerProducer.dll` exists in the game directory.
4. **Duplicate Instance Refusal:**
   - *Cause:* `tauri-plugin-single-instance` detected an already running instance of HS Offline Tracker.
   - *Resolution:* Check the Windows notification area / system tray to restore the existing window, or terminate orphan processes via Task Manager.
5. **Character Save Snapshot Ignored:**
   - *Cause:* The save file was mid-write or failed XOR / zlib integrity validation.
   - *Resolution:* Normal fail-closed behavior. The tracker waits until the game produces two identical, valid file snapshots before updating session totals.

---

## AI Code Review (`ai-review.yml`)

`.github/workflows/ai-review.yml` runs an AI code review of a pull request and
posts findings as inline comments. It is the hub's workflow with only the
repository name changed, and is **opt-in, never automatic**: add the
`ai-review` label, or comment `@claude review` on the pull request. Text after
the phrase is passed to the reviewer as scoping instructions
(`@claude review only src-tauri`); the label always requests a full review and
does not re-run by itself on later pushes. A comment trigger only works once the
workflow is on `main`, because GitHub runs `issue_comment` workflows from the
default branch.

It needs the `CLAUDE_CODE_OAUTH_TOKEN` repository secret (from
`claude setup-token`) **and** the [Claude GitHub App](https://github.com/apps/claude)
installed on this repository; without the app the run fails with
`401 Unauthorized` before reviewing anything, whatever the secret.

The request predicate is written out twice (job `if` and concurrency group);
change both together. Everything else about the workflow's shape -- the full
`--allowedTools` list, `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`, the step that
fails a run which posted nothing -- is explained in the hub's
[`docs/hub/design.md`](../../hub/design.md) under "Asking for a review" and
pinned for the hub's copy by `tests/test_ai_review_workflow.py`. Change them
here and in the hub together.

---

## Known Gaps & Maintenance Triggers

- **Live Magic Find Reading:** Currently disabled (`kMagicFindRouteNamed.enabled = false`) in `aurie-producer/src/module.cpp` because `StatMagicFind` and `ReturnSpecificStat` crash Season 10 runtime builds. Magic Find is updated only via room/vitals events.
- **Game Update Fingerprints:** New game patches require updating `aurie-producer/profiles/` with new `.text` SHA-256 fingerprints, or verifying that adaptive profile fallbacks correctly resolve argument positions.
- **YYToolkit Context7 Integration:** Upstream YYToolkit references must be reviewed against local AGPL-3.0 modifications (`Generic-RunnerInterfaceNew.cpp` and `Hooks.cpp`). Upstream breaking changes must not override the local fixes.

---

## Source Documents & Evidence References
- Submodule Readme: `../../../HS-Offline-Tracker/README.md`
- Protocol Specification: `../../../HS-Offline-Tracker/PROTOCOL.md`
- Aurie Producer Readme: `../../../HS-Offline-Tracker/aurie-producer/README.md`
- Modified YYToolkit Notice: `../../../HS-Offline-Tracker/aurie-loader/yytoolkit-modified/NOTICE.md`
- Native Bridge Readme: `../../../HS-Offline-Tracker/bridge-native/README.md`
- Third-Party Notices: `../../../HS-Offline-Tracker/THIRD_PARTY_NOTICES.md`
- Tauri Configuration: `../../../HS-Offline-Tracker/src-tauri/tauri.conf.json`
- Desktop Manifest: `../../../HS-Offline-Tracker/src-tauri/Cargo.toml`
- Package Manifest: `../../../HS-Offline-Tracker/package.json`
- Aurie Producer CMake: `../../../HS-Offline-Tracker/aurie-producer/CMakeLists.txt`
- Bridge Native CMake: `../../../HS-Offline-Tracker/bridge-native/CMakeLists.txt`
- Demo Replay Script: `../../../HS-Offline-Tracker/scripts/replay-demo.mjs`
- Test Runner Script: `../../../HS-Offline-Tracker/scripts/test.mjs`
- Demo Session Fixture: `../../../HS-Offline-Tracker/fixtures/demo-session.ndjson`
