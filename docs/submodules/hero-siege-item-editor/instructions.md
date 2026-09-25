# Hero Siege Item Editor Module Development Guide

## Module Overview & Metadata
- **Module Name:** Hero Siege Item Editor (Season 10)
- **Submodule Path:** `hero-siege-item-editor`
- **Reviewed Git Revision:** `c9ceb1227448ac09c01bab78ae6cd10492a2efc9` (Tag: `v2.15.2-3-gc9ceb12`, Release: `v2.15.4`, Branch: `main`)
- **Revision Date:** `Mon Sep 7 19:02:12 2026 +0300`
- **Commit Message:** `v2.15.4: a stale "no forged-item file" report asks for a restart, not a user mismatch`
- **Source Availability:** Full application source is present (Python GUI/server `hs_item_editor_gui.py`, SQLite infinite vault `infinite_vault.py`, corrupted save recovery `hss_recovery.py`, Custom Item Forge validation `custom_item_forge.py`, ForgePact runtime bridge integration `custom_forge_runtime.py`, game build identity verification `game_build_identity.py`, exact tooltip rendering `exact_tooltip.py`, stat semantics dictionary `stat_semantics.py`, PRNG roll models `generated_pool_model.py` and `roll_profile_db.py`, socket solver `socket_chain.py`, skill/torch class solvers `dice_skill_selector.py` and `torch_class_selector.py`, frontend assets `item_forge_ui.js` and `item_forge_ui.css`, item icon sprites `item_icons/`, bundled JSON catalogs, catalog generator utilities, PyInstaller build spec `HeroSiegeItemEditor.spec`, and unittest suites `test_*.py`).
- **CI / Pipeline Availability:** GitHub Actions for hub notification (`notify-hub.yml`, `notify-hub-release.yml`), opt-in AI review (`ai-review.yml`), and a tag → draft → CI build release pipeline (`editor-tag.yml`, `editor-release.yml`); see "Release Automation" below. There is no per-PR test run: the suite runs locally and inside the release build.
- **Purpose & Scope:** Standalone offline save editor and custom item forge for Hero Siege Season 10. Allows players to browse, add, duplicate, socket, and transfer items across character inventories and Shared Stash tabs (`stash.hss`), store unlimited items in an SQLite-backed Infinite Vault, repair corrupted save files, calculate deterministic Perfect/Best roll seeds matching native game PRNG chains, and forge custom runtime statistics and mechanics (e.g. Headhunter, Tyrant's Crown) mediated via ForgePact runtime sidecars. Operates strictly offline and fails closed when Hero Siege is running.

---

## Architecture & Repository Map

### Repository Layout
- `hs_item_editor_gui.py`: Main application server and desktop entry point. Implements a single-threaded/threaded Python HTTP server (`http.server.ThreadingHTTPServer`) listening on loopback (`127.0.0.1:8765`), embedded HTML/CSS/JS frontend views, save discovery under `%LOCALAPPDATA%\Hero_Siege`, atomic save read/write routines, single-instance port reservation, and CSRF/Host verification guards.
- `infinite_vault.py`: SQLite-backed permanent storage engine (schema version 7). Manages unlimited item collections and 17×18 stash pages, automatic migrations with pre-migration backups, item transfers, deduplication, full-text search, and cross-process file locking.
- `hss_recovery.py`: Corrupted `.hss` save file recovery and sanitization engine. Decodes base64/XOR/zlib payloads, enforces memory and recursion boundaries (128 MB max decoded payload, 256 max JSON depth), extracts salvageable inventory and character data, and creates timestamped recovery manifests.
- `custom_item_forge.py`: Custom forge validation and mutation engine. Manages custom property presets, donor item unique mechanics, linked proc bundles, keep/replace native stat semantics, and serializes sidecars to `%LOCALAPPDATA%\Hero_Siege\hs_custom_item_forge.json` and `.runtime`.
- `custom_forge_runtime.py`: ForgePact runtime status watcher. Inspects ForgePact capability markers, reads status from `bp_ipc/customforge_status.json`, verifies timestamp ordering between runtime files and reports, and checks process user matching.
- `game_build_identity.py`: Game executable fingerprinting and build identity verification. Checks `Hero_Siege.exe` headers and hash fingerprints to enforce version constraints (e.g., Season 10 patch compatibility).
- `exact_tooltip.py`: Accurate in-game tooltip generator matching native GameMaker layout, affix coloring, roll range formatting, socket statuses, and custom forge annotations.
- `game_truth.py`: Game truth (2.16.0): reads ForgePact's Item Truth journal into `itemtruth\truth.sqlite3`, matches saved items to the game's records, writes build and drawing requests, and turns the game's drawn tooltip rows and stat table into the tooltip. Design: `GAME_TRUTH_DESIGN.md`; contract: "Game truth" at the end of this guide.
- `stat_semantics.py`: Season 10 stat semantic dictionary decoding 325 observed numeric stat keys into player-friendly names, category filters (Offense, Defense, Skills, Elements, Utility), units, and descriptions.
- `generated_pool_model.py`: CPR pseudo-random number generator (PRNG) model matching native GameMaker logic for variable affixes and roll pools.
- `roll_profile_db.py`: Solver and evaluator for Perfect/Best stat rolls against verified game roll profiles.
- `socket_chain.py`: PRNG socket roll solver targeting chain slots 2 and 3 of `gml_Script_CreateItemNew` to maximize native socket draw (stat 20).
- `torch_class_selector.py`: Hero class seed solver for Class Torch relics.
- `dice_skill_selector.py`: Loaded Dice and Overloaded Dice seed solver targeting skill IDs.
- `item_forge_ui.js` & `item_forge_ui.css`: Interactive Custom Item Forge web UI (item picker modals, category chips, property sliders, signature item templates, custom renaming, and special affixes).
- `item_icons/`: Sprite icon catalog containing item icons indexed by sprite name.
- `HeroSiegeItemEditor.spec`: PyInstaller one-file Windows executable packaging specification (`HeroSiegeItemEditor.exe`).
- `ItemEditor.bat`: Windows batch launcher executing `py -3 "%~dp0hs_item_editor_gui.py"`.
- `test_*.py` (at the repository root): 20 Python `unittest` test suites covering HTTP security, save recovery, infinite vault transactions, custom forge serialization, socket solvers, stat semantics, launch readiness, and the release tooling.
- **Data Catalogs & Models:**
  - `hs_full_catalog.json`: Base item definitions, item types, and catalog indices.
  - `hs_custom_forge_catalog.json`: 330 observed numeric stat keys, 932 active unique donor records, 8,877 property presets.
  - `hs_stat_semantics_s10.json`: Decoded stat names, units, and category metadata.
  - `hs_talent_table_s10.json`: Class talent mappings for skill bonuses.
  - `hs_socket_seeds.json`: Solved CPR seeds for maximum socket counts.
  - `hs_dice_skill_targets.json`: Solved CPR seeds for specific skill rolls on Dice items.
  - `hs_torch_classes.json`: Solved CPR seeds for Class Torch relics.
  - `hs_tooltip_roll_models.json`: Verified affix ranges and roll bounds.
  - `hs_runewords.json`: Runeword recipes, base requirements, and bonuses.
  - `hs_sets.json`: Set item definitions and piece bonuses.
  - `hs_signature_items.json`: Ready-made signature item templates (Headhunter, Tyrant's Crown, etc.).
  - `hs_perfect_roll_profiles.json`: Solved optimal roll profiles.
- **Generator & Build Scripts:**
  - `build_custom_forge_catalog.py`: Compiles `hs_custom_forge_catalog.json` from full catalog and tooltip roll models.
  - `build_socket_table.py`, `merge_socket_seeds.py`, `search_all_socket_seeds.py`: Solves and aggregates optimal socket seeds.
  - `build_tooltip_roll_models.py`: Aggregates observed runtime stat keys and roll ranges.

---

## Component Architecture & Data Flow

```text
+-----------------------------------------------------------------------------------------+
|                               HERO SIEGE ITEM EDITOR (Python)                           |
|                                                                                         |
|  +------------------------------------+       +--------------------------------------+  |
|  |       hs_item_editor_gui.py        |       |          item_forge_ui.js            |  |
|  | - Loopback HTTP (127.0.0.1:8765)   | <---> | - Item Catalog & Owned Pickers       |  |
|  | - Port Guard (8765-8774 identity)  |       | - Stat / Category Search Chips       |  |
|  | - CSRF & Host Header Verification  |       | - Signature Templates & Lore         |  |
|  +-----------------+------------------+       +--------------------------------------+  |
|                    |                                                                    |
|         +----------+----------+--------------------------+                              |
|         |                     |                          |                              |
|         v                     v                          v                              |
|  [ Save Management ]   [ Infinite Vault ]       [ Custom Item Forge ]                   |
|  - .hss decode/encode  - infinite_vault.py      - custom_item_forge.py                  |
|  - hss_recovery.py     - hs_infinite_vault      - custom_forge_runtime.py               |
|  - Atomic replace        .sqlite3 (schema 7)    - Validates stat keys & bundles         |
|  - Timestamped bak     - Migrations (v2->v7)    - Writes sidecars                       |
+---------|---------------------|--------------------------|------------------------------+
          |                     |                          |
          | (Writes .hss)       | (Direct SQLite)          | (Writes sidecars)
          v                     v                          v
+-----------------------------------------------------------------------------------------+
| LOCAL DISK STORAGE: %LOCALAPPDATA%\Hero_Siege\                                          |
|                                                                                         |
|  - Saves: hs2saves\*.hss  (stash.hss, <hero>_*.hss)                                     |
|  - Locks: stash.hss.itemeditor.lock, hs_infinite_vault.sqlite3.lock                     |
|  - Backups: stash.hss.guibak_<timestamp>, hs_infinite_vault.sqlite3.bak                 |
|  - Custom Forge: hs_custom_item_forge.json, hs_custom_item_forge.runtime                |
|  - IPC Status: bp_ipc\customforge_status.json, bp_ipc\itemstats.json                    |
|  - Game truth: itemtruth\ (journal, requests, tips, status.json)                        |
+-----------------------------------------------------------------------------------------+
                                                           |
                                                           | (Consumed during boot)
                                                           v
+-----------------------------------------------------------------------------------------+
| GAME RUNTIME (Hero_Siege.exe + ForgePact / BloodPactPlugin.dll)                         |
|                                                                                         |
|  - Hooks CreateItemNew / CreateItemInit / GenerateItemRandomStats                       |
|  - Matches item identity (t + itemDefinitionStruct)                                     |
|  - Injects forged numeric keys into native itemStatStruct                               |
|  - Exports active item stats to bp_ipc\itemstats.json every 2 seconds                   |
|  - Writes runtime status report to bp_ipc\customforge_status.json                       |
|  - Item Truth (1.4.5): journals finished items + drawn tooltips                         |
+-----------------------------------------------------------------------------------------+
```

---

## Process Boundaries, HTTP Security, & Save Safety

### 1. Loopback Binding & Port Range Guard
- The local server binds strictly to `127.0.0.1`, on `8765` unless another program already holds that port.
- At startup, the server acquires `editor-startup.itemeditor.lock` and inspects the port range `8765–8774`.
- If an existing instance of the same editor version is running, the launcher reuses it by opening the browser to that port.
- If a different editor version runs on any port in `8765–8774`, startup fails closed. A build older than v2.7.2 has no `/api/instance`; it is recognized on `8765`, the only port those builds ever used, by the `<title>Hero Siege Item Editor` its page starts with.
- Since 2.16.2, a port held by anything that is not an Item Editor is left to its owner, and startup takes the other ports. ForgePact's panel prefers `8766`; a range Windows reserved is skipped the same way. Before 2.16.2, startup refused ("occupied by an unidentified or legacy process").
- The servers are `EditorHTTPServer`, which leaves SO_REUSEADDR off on Windows. `ThreadingHTTPServer` turns it on, and on Windows that let the editor's bind succeed on a port another program already served (the other program kept the connections). Without it, an occupied port fails the bind and is identified as above.
- While active, the editor responds with its application identity on every port it holds, preventing legacy versions (v2.7.2 and older) from spawning concurrently. The runtime peer check before each write still probes the ports it left to other programs.

### 2. HTTP Security & CSRF Protection
- **Host Header Enforcement:** Every HTTP request must supply a `Host` header matching `127.0.0.1:<port>` or `localhost:<port>`, blocking DNS rebinding attacks.
- **Custom Header Requirement:** All mutating `POST` endpoints require the header `X-Hero-Siege-Item-Editor: 1`. Web browsers cannot send this header in cross-origin requests without triggering a CORS preflight, which the editor does not allow.
- **Origin Verification:** If an `Origin` header is present, it must strictly match the active loopback origin.
- **Bounded JSON Payloads:** Incoming POST bodies are parsed with bounded byte limits and recursion depth guards (`MAX_JSON_DEPTH = 256`).

### 3. Save File Protection & Invariants
- **Hero Siege Process Detection:** Write operations are blocked while `Hero_Siege.exe` is running. Process detection reads `tasklist` output with lenient locale parsing and falls back to PowerShell `Get-Process`.
- **Multi-Tier File Locking:** Save modifications acquire process `SAVE_WRITE_LOCK` followed by the target file lock (e.g. `stash.hss.itemeditor.lock` or `hs_infinite_vault.sqlite3.lock`).
- **Atomic File Replacement:** Save files and sidecars are written to temporary files (`*.tmp`), flushed to disk, and replaced atomically (`os.replace`).
- **Pre-Mutation Backups:** Prior to replacing any `.hss` file, a timestamped backup (`*.guibak_<timestamp>`) is generated. SQLite migrations generate a pre-migration `.bak` copy.
- **Non-Negotiable Invariant:** *At every crash boundary, at least one durable, valid copy of an item exists.* Cross-file transfers (e.g., character inventory to Shared Stash) always complete the destination write and backup before modifying the source file. In the event of a crash or power failure, temporary duplication is preserved; data is never silently dropped.

---

## ForgePact Integration & Custom Item Forge

### Why Save-Only Affix Injection Fails
Hero Siege does not store free-form affix arrays in `.hss` files. On load, the game reconstructs the runtime `itemStatStruct` dynamically from compact definition seeds (`a`, `b`, `c`, `j`, `i`, `s`). Modifying or appending custom stat fields directly in `.hss` causes the game to overwrite them during `CreateItemNew`.

Custom Item Forge solves this via two cooperating mechanisms:
1. **Item Editor** selects, validates, and writes the item definition and desired stats to a local sidecar file.
2. **ForgePact (`BloodPactPlugin.dll`)** hooks the game's item constructors and writes the numeric keys directly into `itemStatStruct` after native generation completes.

### Sidecar File Contracts
- **Source of Truth (JSON):** `%LOCALAPPDATA%\Hero_Siege\hs_custom_item_forge.json`
- **Consumed Runtime File:** `%LOCALAPPDATA%\Hero_Siege\hs_custom_item_forge.runtime` (Schema `HS_CUSTOM_ITEM_FORGE_V1`)
- **Runtime Line Format:**
  ```text
  item|t=<type>;a=<a>;b=<b>;c=<c>;j=<j>|keep=<0|1>|<statId>=<val>;<statId>=<val>...
  ```
- **Placement Field Exclusion:** Placement fields (`g`, `w`, `m`) are deliberately omitted from the identity string. Moving an item between bag tabs, equipping it, or placing it in the Shared Stash does not disconnect its Custom Forge setup.
- **Stat Overlays (`keep` flag):**
  - `keep=1`: Overlays custom stat keys on top of native generated stats.
  - `keep=0`: Strips native `itemStatStruct` fields before applying custom stats.
- **Linked Proc Bundles:** Proc mechanics (e.g. spell cast on strike) must maintain linked triplets (`identity`, `level`, `chance`) such as `116/117/118` (striking) or `113/114/115` (attacking). The Item Editor adds and removes these families atomically.

### Forge Runtime Status & Feedback Loop
- ForgePact periodically writes status to `bp_ipc\customforge_status.json`.
- **Timestamp Ordering:** When evaluating runtime status, `custom_forge_runtime.py` compares the file modification time of `hs_custom_item_forge.runtime` against `customforge_status.json`. If the status report is older than the forge file, the UI instructs the user to restart Hero Siege instead of displaying a false "different Windows user" error.
- **Live Stat Snapshots:** ForgePact exports the live runtime stat struct to `bp_ipc\itemstats.json` (at most once every 2 seconds). When editing an owned item, the editor reads this file to display verified in-game stat values. Since ForgePact 1.4.5 the snapshot is taken at the outermost `CreateItemNew` return. Taken earlier, inside `CreateItemInit`/`GenerateItemRandomStats`, it missed the socket count on 121 of 386 compared items. Since 2.16.0 the Item Forge reads an item's base stats from the game-truth store first (the end of this guide), and uses this file only as a fallback.

---

## Data Catalogs & Generation Provenance

### Checked-in Catalogs vs External Inputs
| Asset / Catalog | Description | Regeneration Utility | External Inputs Required |
| --- | --- | --- | --- |
| `hs_custom_forge_catalog.json` | 330 stat keys, 932 donor items, 8,877 property presets | `build_custom_forge_catalog.py` | `hs_tooltip_roll_models.json`, `hs_full_catalog.json` |
| `hs_stat_semantics_s10.json` | 325 decoded stat descriptions and category chips | Static / Reverse-engineered | Ghidra decompiler string extracts, game scripts |
| `hs_socket_seeds.json` | Solved seeds for max socket counts | `build_socket_table.py`, `merge_socket_seeds.py` | Native CPR algorithm, catalog max sockets |
| `hs_dice_skill_targets.json` | Solved seeds for Loaded / Overloaded Dice skills | `dice_skill_selector.py` generator | Class talent tables, CPR solver |
| `hs_torch_classes.json` | Solved seeds for Class Torch relics | `torch_class_selector.py` generator | Hero class definitions, CPR solver |
| `hs_tooltip_roll_models.json` | Affix ranges and roll distributions | `build_tooltip_roll_models.py` | Live `itemdrops.jsonl` traces from ForgePact |
| `hs_signature_items.json` | Presets for Headhunter, Tyrant's Crown, etc. | Manual / Design specification | Plugin mechanic definitions |

### Integrity & Build Verification
- Modules such as `dice_skill_selector.py` and `torch_class_selector.py` compute SHA-256 digests over their catalog files at runtime. If a catalog is modified or corrupted, the module fails closed and disables the affected selector.
- `game_build_identity.py` verifies game executable signatures before exposing build-sensitive seed optimizers.

---

## Setup, Build, Run, & Test Commands

All commands below are executed from the submodule root `hero-siege-item-editor/` unless otherwise indicated.

| Command | Shell / Platform | Working Directory | Prerequisites | Expected Result | Side Effects | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `py -3 hs_item_editor_gui.py` | PowerShell / CMD (Windows) | `hero-siege-item-editor/` | Python 3.10+ installed | Launches editor HTTP server at `http://127.0.0.1:8765` and opens browser | Creates lockfile `.item_editor.lock` | Verified |
| `ItemEditor.bat` | Windows CMD | `hero-siege-item-editor/` | Python in PATH | Launches `hs_item_editor_gui.py` | Same as GUI launch | Verified |
| `py -3 -m unittest test_launch_readiness.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 29 launch and port verification tests (`ForeignPortTests` bind real loopback ports in 20000–32767, never 8765–8774) | None | Verified |
| `py -3 -m unittest test_http_security.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 9 HTTP CSRF / Host header security tests | None | Verified |
| `py -3 -m unittest test_hss_recovery.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 17 save recovery and decode tests | None | Verified |
| `py -3 -m unittest test_hss_recovery_integration.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 12 recovery integration tests | Temp files in test sandbox | Verified |
| `py -3 -m unittest test_infinite_vault.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 44 SQLite vault schema and transaction tests | Temp SQLite databases | Verified |
| `py -3 -m unittest test_stat_semantics.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 13 stat semantics and bundle tests | None | Verified |
| `py -3 -m unittest test_socket_editor.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 18 socket solver and seed tests | None | Verified |
| `py -3 -m unittest test_small_charm_metadata.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 8 charm metadata tests | None | Verified |
| `py -3 -m unittest test_roll_profile_db.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 24 roll profile evaluator tests | None | Verified |
| `py -3 -m unittest test_custom_forge_runtime.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs custom forge runtime bridge tests | None | Verified |
| `py -3 -m unittest discover -s . -p "test*.py"` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs the whole suite (570 tests, 1 skipped, with hero-siege-item-editor#8, 2026-09-24; 476 with #6 passed on a fresh clone with `core.autocrlf` true or false, 2026-09-23) | Temporary test fixtures | Verified |
| `py -3 build_custom_forge_catalog.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Rebuilds `hs_custom_forge_catalog.json` | Overwrites catalog JSON | Inspected |
| `py -3 -m PyInstaller --clean --noconfirm HeroSiegeItemEditor.spec` | PowerShell / CMD | `hero-siege-item-editor/` | `pip install -r requirements-build.txt` (PyInstaller 6.20.0, pywebview 6.2.1) | Compiles single-file executable `dist/HeroSiegeItemEditor.exe` (18 MB with Python 3.14, 2026-09-23) | Creates `build/` and `dist/` | Verified |
| `py -3 tools/cut_release.py --check` / `py -3 tools/cut_release.py 2.15.5` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Reports / moves the X.Y.Z of `APP_VERSION`, keeping the `-s10` suffix | The bump rewrites `hs_item_editor_gui.py` | Verified |
| `py -3 tools/editor_tag.py --tag v2.15.5 --existing <tags>` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Prints `version=/tag=/bump=/previous=` or refuses with nothing on stdout | None | Verified |
| `py -3 tools/release_ci.py package --root . --out out` | PowerShell / CMD | `hero-siege-item-editor/` | a built `dist/HeroSiegeItemEditor.exe` | Writes `HeroSiegeItemEditor-v<APP_VERSION>.exe` and its `.sha256` | Creates `out/` | Verified |
| `py -3 -m unittest test_release_tooling` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 26 release tooling and workflow-shape tests | Temp directories | Verified |

### Test Suite Fixtures & Checksum Notes
- Several specialized test suites (`test_dice_skill_selector.py`, `test_torch_class_selector.py`) enforce strict SHA-256 catalog checksums and specific game build versions. If run in an environment where optional research files or catalog hashes differ, these tests fail-closed by design to reflect unverified data state.
- Those checksums are of the exact committed bytes. `.gitattributes` (`*.json -text`) keeps every checkout byte-exact; a working tree created before it existed can still hold CRLF copies, so re-check them out (`git rm --cached -r -q . && git reset --hard` in the submodule, with no local edits) if the dice or tooltip databases report a hash mismatch.

---

## Coding Conventions & Persistence Invariants

- **Language & Style:** Python 3.10+ standard library code without heavy third-party runtime dependencies (uses `http.server`, `sqlite3`, `json`, `hashlib`, `urllib`, `pathlib`, `ctypes`, `threading`).
- **No Direct Native Patching:** The editor never patches `Hero_Siege.exe` bytes or injects code into live processes. All runtime customization is mediated through sidecars and ForgePact.
- **Fail-Closed Principle:** Any unverified data structure, unrecognized JSON property, or hash mismatch causes the component to disable mutation operations rather than risk save corruption.
- **Unicode & Locale Safety:** All file paths, character names, tab labels, and JSON strings are encoded and decoded using explicit `utf-8` to support international player profiles (Cyrillic, CJK, Turkish, etc.).
- **Socket Invariants:** Forged stats attached to runes, gems, or jewels do not carry into host item sockets when inserted in-game; this constraint is explicitly labeled in the UI.

---

## Troubleshooting & Common Edge Cases

| Issue / Symptom | Root Cause | Solution |
| --- | --- | --- |
| "GAME RUNNING" warning stays visible when game is closed | Localized Windows output formatting in `tasklist` | Editor uses lenient tasklist parsing and PowerShell fallback. Ensure `Hero_Siege.exe` has fully terminated in Task Manager. |
| Red "Different Windows User" status on Item Forge | Stale report file from before the item was forged | A report older than the forge file triggers a "restart Hero Siege" prompt. Restart the game to allow ForgePact to reload `.runtime`. |
| Startup refused: "Item Editor vX is already running" or "An Item Editor older than v2.7.2 is already running" | Another editor version holds a port in 8765–8774 | Close that editor. Since 2.16.2, a program that is not an Item Editor (ForgePact's panel on 8766) no longer blocks startup; the editor leaves its port alone. |
| Startup refused: "No free editor port in 8765..8774" | Other programs, or a range Windows reserved, hold all ten ports | Close one of them. `netsh int ipv4 show excludedportrange protocol=tcp` lists Windows' reserved ranges. |
| Startup refused: "Local editor port N is occupied by an unidentified or legacy process" | A release before 2.16.2, and a program on a port in 8765–8774 that does not share it (ForgePact's panel does share; those releases bound 8766 on top of it instead) | Update to 2.16.2, or close that program before starting the editor. |
| Corrupted `.hss` save file fails to open | Save file payload was partially written or truncated | Use `hss_recovery.py` via the recovery interface to decode and salvage valid character/inventory JSON. |
| Forged stats do not appear in combat | ForgePact plugin not installed or game launched without loader | Ensure `BloodPactPlugin.dll` is installed in the game's `bin/` directory and loaded via Aurie/YYToolkit. |

---

## Maintenance Triggers & Upstream Links

- **New Hero Siege Patches / Seasons:**
  - Verify `CreateItemNew` and `itemStatStruct` field formats using development ForgePact telemetry (`itemdrops.jsonl`).
  - Run `build_custom_forge_catalog.py` to regenerate the property catalog if new stat keys or unique items are added.
  - Check `game_build_identity.py` to update supported game version hashes.
  - Game truth needs no action. The running build's id changes, so every owned item counts as unverified again, and the editor has the game build and draw them again on its own. Until then, tooltips show as **Estimate**. `MODEL_BUILD_ID` in `game_truth.py` names the only build the replay is promised for.
- **Companion Documentation Links:**
  - ForgePact Runtime Plugin & Architecture: [`../ForgePact/instructions.md`](../ForgePact/instructions.md)
  - HSCraftSim Crafting & CPR RNG Mechanics: [`../HSCraftSim/instructions.md`](../HSCraftSim/instructions.md)
  - HS Offline Tracker Telemetry Integration: [`../HS-Offline-Tracker/instructions.md`](../HS-Offline-Tracker/instructions.md)
  - Shared Documentation Index: [`../README.md`](../README.md)

## Miner's Helmet signature item (2026-09-23)

`miner` is a Custom Forge mechanic, and `hs_signature_items.json` carries a
Miner's Helmet template: Great Helm, SS tier, +1000 Defense, +500% Enhanced
Defense, +20% Movement Speed, +20% All Resistances, +5 Light Radius. Only helmet
selectors (`t=0`) may use it. ForgePact 1.4.5 implements the mechanic: 4x ore
while worn, and Vein Resonance digs the two nearest eligible veins with each
finished dig. `test_custom_item_forge.py` covers the template round trip and the
helmet-only rule.

## Release Automation

Ported from ForgePact (`docs/submodules/ForgePact/instructions.md`, "Tagging a
release"), which carries the longer reasoning. This repository's default branch
is **`master`**, and the tag and build workflows refuse to run from anything
else; `ai-review.yml` runs on a pull request's head, like every other copy of it.

**AI review (`ai-review.yml`).** ForgePact's workflow with only the repository
name changed. Opt-in: add the `ai-review` label or comment `@claude review`
(text after the phrase scopes the review). Needs the `CLAUDE_CODE_OAUTH_TOKEN`
repository secret **and** the Claude GitHub App installed on this repository;
the hub's `docs/hub/design.md` ("Asking for a review") explains the shape.

**Tagging (`editor-tag.yml`).** Actions → *Item Editor tag* → Run workflow,
with the tag (`v2.15.5`). `tools/editor_tag.py` refuses a malformed tag, a
taken one, one below the highest `v*` tag, and one below `APP_VERSION`; the
workflow also refuses a version that already has a release, drafts included.
It then composes the draft body from `RELEASE_NOTES_vX.Y.Z.md` (plus any
never-released versions' notes since the previous tag, newest first; or
GitHub's generated notes under a rewrite banner when the file is missing),
moves `APP_VERSION` with `tools/cut_release.py` and pushes that to `master`
before tagging, pushes the tag, leaves a **draft** release titled
`Hero Siege Item Editor X.Y.Z`, and dispatches `editor-release.yml` against
`master`. The bump commit is made by `github-actions[bot]` with `GITHUB_TOKEN`, so it
does not fire `notify-hub.yml`.

**Building (`editor-release.yml`).** `workflow_dispatch` with `tag` and
`dry_run` (default `true` for a manual run). On `windows-latest`, Python 3.14:
checks the draft exists and is still a draft, checks the tag out into `editor/`
(the tooling comes from `master`, in `ci/`), installs `requirements-build.txt`,
runs `cut_release.py --check --expect`, runs the **whole** unittest suite,
builds the spec with PyInstaller, and names/checksums the exe with
`release_ci.py package` (`HeroSiegeItemEditor-v<APP_VERSION>.exe` and
`<that>.sha256` as `<hash> *<name>`, the shapes the hub's
`catalog/sources.toml` matches). A dry run keeps them as a workflow artifact;
otherwise a second draft check runs and they are uploaded with
`gh release upload --clobber`. Nothing in either workflow publishes a release.

The data files are pinned by SHA-256 of their exact committed bytes
(`exact_tooltip.py` pins `hs_full_catalog.json` and
`hs_perfect_roll_profiles.json`; `dice_skill_selector.py` pins
`hs_dice_skill_targets.json`), so `.gitattributes` marks `*.json -text` and no
checkout rewrites their line endings, whatever `core.autocrlf` says. The build
also sets `core.autocrlf false` before checking out, since it may be building a
tag that predates `.gitattributes`.

Until 2026-09-23 no checkout passed the suite: `hs_tooltip_roll_models.json`
pinned the CRLF bytes of `hs_perfect_roll_profiles.json` (the file as a Windows
working tree wrote it) while the dice database was pinned to LF bytes, so an
LF clone rejected the exact-tooltip model and a CRLF clone rejected the dice
targets. The profile content never changed; the pin was moved to the committed
LF bytes and `payloadSha256` recomputed (the source files the model was
generated from are not in the repository, so this is a re-pin, not a
regeneration). A test that required the never-committed
`CLAUDE_CUSTOM_FORGE_STAT_DECODE_REQUEST.md` no longer does. The full suite
(425 tests, 1 skipped) now passes on fresh clones with `core.autocrlf` both
`true` and `false`. Tags up to `v2.15.4` still carry the old pin, so a rebuild
of one of those stops at "Tests".

**No notes cleanup.** ForgePact and the Tracker delete a release's notes files
once it is published. This repository's `README.md` links every
`RELEASE_NOTES_vX.Y.Z.md` as its version history, so that workflow is not
ported; the notes files stay.

### CI build launch gate

Before pressing Publish, download the exe from the draft, check its sha256
against the `.sha256` asset, start it, and confirm the window title and
`http://127.0.0.1:8765/api/instance` show the tagged version, a save loads,
and the exact tooltip for a saved item appears. Record a row here.

| tag | run URL | sha256 matches | starts, tagged version shown | save loads | exact tooltip shown | date | tester |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `v2.15.10` | [35884558791](https://github.com/falorfrozen-cmd/hero-siege-item-editor/actions/runs/35884558791) | yes: `4d6ae127…f99f8` = `.sha256` asset = GitHub asset digest | yes: window title and `/api/instance` show `2.15.10-s10` | yes: 10 saves listed, slot 0 loaded (Hero Siege was running; read-only checks) | yes: 22 character and 127 Shared Stash items carry exact tooltips (5059 profiles); Dice targets ready | 2026-09-23 | Claude Code, for the owner |
| `v2.16.0` | [36075703309](https://github.com/falorfrozen-cmd/hero-siege-item-editor/actions/runs/36075703309) | yes: `f937bc13…a493cb` = `.sha256` asset = GitHub asset digest | yes: window title and `/api/instance` show `2.16.0-s10` | yes: 10 saves listed, slot 0 loaded (Hero Siege 1.4.5 was running; read-only checks) | yes: all 16 character and 127 Shared Stash items **Game verified** with the game's own text; game truth reports 0 unverified and 0 undrawn on `pe-6aaa6779-0cad4fc8`; 5059 profiles; Dice targets ready | 2026-09-25 | Claude Code, for the owner |
| `v2.16.1` | [36116151604](https://github.com/falorfrozen-cmd/hero-siege-item-editor/actions/runs/36116151604) | yes: `ac18db5a…3b7dc6` = `.sha256` asset = GitHub asset digest | yes: window title and `/api/instance` show `2.16.1-s10` | yes: 10 saves listed, slot 0 loaded (Hero Siege was running; read-only checks) | yes: slot 0's 22 items and the Shared Stash's 167 are **Game verified**; game truth: 630/630 character, 167/167 Shared Stash and 6,805/6,805 Vault items verified, 0 missing, 13 character items not yet drawn by the game, on `pe-6aaa6779-0cad4fc8`; 5059 profiles; Dice targets ready | 2026-09-25 | Claude Code, for the owner |
| `v2.16.2` | [36160683077](https://github.com/falorfrozen-cmd/hero-siege-item-editor/actions/runs/36160683077) (suite: 585 tests, 1 skipped) | yes: `506ba048…13e89b` = `.sha256` asset = GitHub asset digest | yes: window title and `/api/instance` show `2.16.2-s10`. It was started beside a ForgePact-like server on 8766, listened on 8765 and 8767-8774, and 8766 kept answering from that server | yes: 10 saves listed, slot 0 loaded (Hero Siege was running; read-only checks) | yes: slot 0's 22 items and the Shared Stash's 167 are **Game verified**; game truth: 630/630 character, 167/167 Shared Stash and 6,806/6,806 Vault items verified, 0 missing, 14 items not yet drawn by the game (13 character, 1 Vault), on `pe-6aaa6779-0cad4fc8`; 5059 profiles; Dice targets ready | 2026-09-25 | Claude Code, for the owner |

## Infinite Vault deletion (2026-09-22)

The category **…** menu exposes **DELETE CATEGORY**; stash headers expose
**DELETE STASH**. Both remove their contents after a name/count confirmation.
`/api/vault/collections` and `/api/vault/stashes` accept `previewDelete`, followed
by `delete` with the returned `previewToken`. The store verifies the snapshot in
one write transaction, refuses unresolved transfers/reservations and deletion of
the last category/stash, and retains a dedicated `*.before-delete-<uuid>.bak`.
Game save files are untouched. The game must be closed. Deletion is not available
through metadata Undo; it forms an undo barrier. Manual whole-database restoration
is documented in `hero-siege-item-editor/INFINITE_VAULT_DESIGN.md`.

Stash page indexes remain stable across deletion. `_vault_layout_plan` accepts
existing indexes, and `ensure_stash_pages` initializes only missing required pages,
so refresh/compact cannot resurrect deleted gaps. Counts are refreshed after
initial placement of legacy/unplaced items.

Run `py -3 -m unittest test_vault_deletion -v` for isolated database/HTTP checks,
plus `test_infinite_vault`, `test_vault_integration`, and `test_http_security` for
regressions. Browser verification must use a temporary `SAVES` and `VAULT_DB_FILE`,
never the user's real Vault. The baseline already fails
`test_tooltip_identity_is_enriched_with_the_verified_subskill_name` with missing
`selectedName`; it is unrelated to deletion.

Verification on 2026-09-22: all 16 deletion tests passed; the combined 132-test
Vault/storage/HTTP run passed 131 tests with that same baseline tooltip error.
In the isolated browser fixture, Cancel preserved all items, deleting the first
stash preserved the second stash, and deleting a two-stash category removed its
two items while the other category's item remained. Counts, automatic fallback,
retained SQLite backup integrity, and an empty browser error log were checked.

## Merged local Item Editor (2026-09-22)

Version `2.15.5-s10-local` combines the AFK spool API, confirmed deletion, and
the local Miner template. Launch this source build with `ItemEditor.bat`; a new
release EXE has not been built.

`POST /api/vault/ingest` accepts expedition records; `GET /api/vault/ingest/status`
counts accepted identities, including items withdrawn or intentionally deleted.
Gear belongs to expedition stashes in AFK Farm, native stackables to AFK Materials.
The POST retains the existing Host/Origin and `X-Hero-Siege-Item-Editor: 1` checks.
Ingest changes only SQLite and may run while the game runs; deletion and save
transfers still require a closed game.

Schema 7 adds `deleted_deposit_keys`. Deletion stores import identities in the
same transaction that removes items; retries cannot recreate them, even after a
restart or removal of the whole category. Existing payloads and transfer journals
are preserved during migration after a pre-migration backup. Old editors reject
schema 7. Prior deletions made without receipts cannot be backfilled.

The final affected-suite command is:
`py -3 -m unittest test_infinite_vault test_vault_integration test_http_security test_vault_deletion test_vault_ingest test_custom_item_forge test_launch_readiness -q`.
It ran 203 tests: 201 passed, the prior tooltip error and the missing external
research fixture failed. All 28 deletion/ingest tests passed. Browser tests used
temporary storage and the actual AFK spool client to verify stash/category
deletion followed by retry: zero new items, no recreated storage, surviving
items intact, valid dedicated backups, and no console errors. See
`hero-siege-item-editor/MERGE_VERIFICATION_2026-09-22.md` for provenance and details.

## Vault speed, AFK categories and clean-up (2026-09-23)

Version `2.15.6-s10-local`. Measured on a copy of a real Vault (14 MB, a 5,230-item
AFK category): opening the category took 3–5 s of tooltip building and 17.5 MB of
JSON plus a 36,000-element page; ingesting one AFK item cost about 260 ms because
every deposit copied the whole database first (16 minutes for 4,547 items).

- `exact_tooltip.build_tooltip_model` reads definitions through private read-only
  views (`_definition_view`, `_profile_view`, `_stat_label_view`); the public
  lookups still return defensive copies. The builder never mutates them; a test
  mutates a returned model and checks the next one is unchanged.
- `resolve(..., roll_profiles=False)` skips roll profiles and skill selectors for
  grid fields. `_vault_item_derived` caches those per `(item id, raw sha256)`
  (first read still runs the integrity check); layout sizes use it too.
- `GET /api/vault/items?lite=1` returns grid rows without `gameTooltip`;
  `GET /api/vault/tooltips?ids=` returns up to 200 models. The embedded UI draws
  stash headers at once and each 17×18 grid when it nears the view
  (IntersectionObserver), prefetches tooltips per drawn stash, fetches a hovered
  item's model immediately, loads both models before Compare, and after a drop
  redraws only the source and target stashes.
- `_vault_layout_plan` starts each first-fit search at the page where the last item
  of the same size landed; a test compares it with a full scan on 900 random items.
- `InfiniteVault.deposit_many` stores a batch in one `_write` (one backup) and
  reports each entry. `op_vault_ingest` uses it; gear goes to a per-expedition
  category found again through a `collection_created` marker
  (`find_marked_collection`), laid out by `_afk_group_layout` on stashes named after
  `VAULT_RARITY_GROUPS` via `apply_named_layout`. `layout: "defer"` and
  `finalize: true` let a client lay out an expedition once. Expeditions that already
  have a page in **AFK Farm** keep the legacy path.
- `POST /api/vault/purge` (`preview_item_purge` / `purge_items`) deletes the chosen
  rarity groups of one category with the stash-deletion safety rules; custom-named
  items are kept, `removeEmptied` removes stashes it empties, and `items_purged` is
  an undo barrier. The UI entry is **CLEAN UP BY RARITY…** in the category menu.

Measured after the change on the same copy: lite listing 0.12 + 0.07 s (2.9 MB),
200 tooltips 0.02 s, layout ensure 0.1–0.17 s, ingest 500 records about 1.9 s. Browser
check on an isolated fixture (copied Vault, temporary saves, game reported closed):
the category opened with 837 elements, grids and tooltips appeared on scroll, a drop
updated two stashes in 0.19 s, Compare loaded both models, and clean-up deleted 576
Satanic items with a backup and removed 8 emptied stashes. No console errors.

Tests: `test_vault_afk_qol` (8 new) and updated `test_vault_ingest` (15, per-expedition
categories, legacy AFK Farm, one backup per batch) pass. The affected-suite command
above now runs 214 tests with the same two baseline failures. A full
`discover` run fails the same 17 tests before and after this change (dice/torch
selector catalog checks, the subskill-name tooltip test, the external research
fixture); none of them is new.

## Split AFK Farm by expedition (2.15.7, 2026-09-23)

`POST /api/vault/afk-split` with `action: "preview"` groups the shared AFK Farm
category's available items by the expedition their deposit key names and returns the
target category names and counts with a preview token; `action: "split"` with that
token creates or finds each expedition's marked category, moves the items with
`InfiniteVault.split_items` (one transaction, `before-split` backup, emptied stashes
removed, `items_split` undo barrier), lays each category out on rarity stashes and
deletes AFK Farm when it is empty. Hero Siege must be closed. The UI entry is
**SPLIT BY EXPEDITION…** in the AFK Farm category menu. `op_vault_ingest` now prefers
an expedition's marked category over a legacy AFK Farm stash of the same name.
Tests: `AfkFarmSplitTests` in `test_vault_afk_qol.py` (5). On a copy of the real
Vault, 3,351 items moved in 1.1 s. The full suite shows the same 23 existing
failures before and after the change (438 → 443 tests).

## AFK stack counts (2.15.8, 2026-09-23)

`_afk_prepare_record` keeps a stackable record's `itemDefinitionStruct.o` (a whole
number from 1 to `FULL_STACK_AMOUNT`, 999) instead of forcing 1; other values are
skipped with a reason. AFK FARM 0.6.2 delivers Prospector fragments as native stacks.
Test: `AfkStackCountTests` in `test_vault_afk_qol.py`.

## Stacks and AFK dismantle (2.15.9, 2026-09-23)

`InfiniteVault.rework_items` is the single atomic primitive for removing, changing
and adding items (deposit keys of removed items kept as deleted, dedicated backup,
undo barrier). Stackables merge into 999 stacks on AFK ingest into AFK Materials and
on COMPACT ITEMS (`_vault_stack_category`). `POST /api/vault/dismantle`
(preview/dismantle) runs the Prospector break-down on one stash of an AFK expedition
category (`vault_meta` marks those with `afk: true`); below Satanic is deleted.
Tests: `VaultStackTests` (2) and `AfkDismantleTests` (2) in `test_vault_afk_qol.py`.
The full suite shows the same 23 existing failures before and after (448 tests).

## Dismantle by rarity (2.15.10, 2026-09-23)

**DISMANTLE BY RARITY…** in the category menu of an AFK expedition category runs a
stash's DISMANTLE on every item of the ticked rarity groups (`VAULT_RARITY_GROUPS`,
the CLEAN UP BY RARITY grouping). `POST /api/vault/dismantle` takes `groups` instead
of `pageIndex` (never both); the preview returns per-group counts and `emptyStashes`,
and a different choice needs its own review. With `removeEmptied`,
`rework_items(remove_empty_stashes=True)` removes every empty stash of the category in
the same transaction (also ones already empty), keeping the lowest-numbered one.
Tests: `AfkDismantleTests` (4). Browser check on a copy of a real Vault: Set + Satanic,
3,164 items -> 15,725 Satanic Crystal + 2,535 random fragments, 49 empty stashes
removed, 17 Heroic items kept. `ItemEditorSeason10Tests` now keeps `VAULT_DB_FILE` in
its temporary folder (the Global Item Finder test used to search the machine's real
Vault). Merged with master 3aada04 on a clean checkout: 476 tests pass (1 skipped).

Upstream pull request for 2.15.5–2.15.10: falorfrozen-cmd/hero-siege-item-editor#6.

## Game truth: the game's numbers and text (2.16.0, 2026-09-24)

The editor shows every item it owns, on characters, in the Shared Stash and in the
Infinite Vault, with the numbers and tooltip text that the running game builds and
draws for it. Those items are marked **✓ Game verified**. When there is no game
record, the replay (`exact_tooltip.py`) is shown instead, marked **Estimate**.

This needs ForgePact 1.4.5 or newer. It merged as
falorfrozen-cmd/hero-siege-item-editor#8 together with falorfrozen-cmd/ForgePact#79.

Where to read more:
- Design and measurements:
  [`GAME_TRUTH_DESIGN.md`](../../../hero-siege-item-editor/GAME_TRUTH_DESIGN.md).
- The game facts it established:
  [`RUNTIME_DATA_MODELS.md` §16](../../RUNTIME_DATA_MODELS.md#16-items-as-the-game-builds-and-draws-them).
- Why the in-game half is ForgePact's:
  [ADR 0003](../../adr/0003-item-truth-lives-in-forgepact.md).

What it does:
- **Step 1, the game's records.** ForgePact journals every item the game finishes.
  The editor matches a saved item to a record by `itemTimeStamp`, class and every
  definition field. It ignores placement fields (`g`, `w`, `zz`, `pos`), counts `m`
  and `o` of 1 as absent, and ignores a native stack's `o`.
- **Step 2, the game builds on request.** Every 30 s while the game runs, the editor
  queues the owned items that are not verified on the running build, and the game
  builds them.
- **Step 3, the game's own text.** The game records the tooltip text it draws, and
  draws the tooltips of items nobody hovers while the player has any item tooltip
  open. An item not drawn yet takes its line text from the game's stat table,
  which is checked against 41,920 of 41,920 drawn lines.
- Measured 2026-09-24: all 7,628 owned items were verified and drawn.

The save rule does not change: saves are still never written while the game runs.
Game truth writes only the `itemtruth` files below, and ForgePact never writes
anything from them back into the game. Built items are left to the collector.

### The itemtruth contract

This section is the contract between the Item Editor and ForgePact, per ADR 0003.
Change it only together with both modules' code.
[ForgePact's guide](../ForgePact/instructions.md#item-truth-for-the-item-editor-145-verified-live-2026-09-24)
covers its side of the hooks. All paths are under
`%LOCALAPPDATA%\Hero_Siege\itemtruth\`.

| Path | Written by | Read by | Meaning |
|---|---|---|---|
| `capture.request` | Item Editor | ForgePact | Capture is on. ForgePact checks it at setup and about every 10 s, so removing it pauses capture. |
| `capture.off` | Item Editor | Item Editor | The player turned capture off. This survives an editor restart. |
| `status.json` | ForgePact | Item Editor | `schema`, `forgepact` (version), `build`, `pid`, `started`, `updated` (unix ms), `written`, `dropped`, `file`. It is rewritten at least every 30 s while the game runs, so an older one means the game is not running. |
| `journal\live-<build>-<yyyymmdd-HHMMSS>-<pid>-<part>.ndjson` | ForgePact | Item Editor | One JSON object per line (see below). A new part starts at 16 MB. Parts are numbered `1`, `2` … `10` without padding, so read them in number order, not name order. |
| `requests\<id>.req` / `.working` / `.stopped` | Item Editor, then ForgePact | ForgePact, then Item Editor | Items for the game to build. |
| `tips\<id>.req` / `.working` / `.stopped` | Item Editor, then ForgePact | ForgePact, then Item Editor | Items for the game to draw. |
| `truth.sqlite3` | Item Editor | Item Editor | The editor's own store. Not part of the contract. |

A journal holds four kinds of line, all with `"v":1`, `"build"` and `"t"` (unix ms):

- **An item record**:
  - fields: `"src":"live"|"eval"`, `"ts"` (itemTimeStamp), `"type"`, `"hash"`,
    `"def"`, `"stats"`, `"info"`;
  - `"native"` is added when Custom Forge changed the stats (the stats before it
    did);
  - an `eval` record also has `"req":"<id>"` and is always written;
  - a `live` record is written once per distinct content per session.
- **Progress**: `"kind":"eval"|"tipdraw"`, `"req"`, `"total"`, `"done"`, `"ok"`,
  `"failed"`, `"rejected"`, `"finished"`.
- **A drawn tooltip**:
  - fields: `"kind":"tooltip"`, `"ts"`, `"hash"`, `"args"`, `"rows"` (every text
    draw of the pass), `"stats"` (every stat call that drew a line);
  - `"by"` names the object whose draw event drew it;
  - `"req"` is present when it was drawn for a request.
  - A request's drawing comes right after the record of the item the game built
    for it.
- **The tooltip table**: `"kind":"tooltip-table"`, `"stats"`. It is written once per
  session and lists every stat call of one tooltip pass, in order.

Requests work like this:
- **Line format.** Each line is `<item key>\t<save data JSON>`. The JSON is ASCII
  with `\u` escapes, so the game's `json_parse` reads any name. A request holds at
  most 50,000 lines.
- **Ids.** An id is `<unix ms>-<6 hex digits>`, so ids sort by age.
- **Claiming and finishing.** ForgePact takes the oldest `.req` and renames it
  `.working` before reading it. It deletes the file when done.
- **Budgets.** Builds take at most 4 ms and 200 items a frame. Drawings take at most
  6 items and 3 ms a frame, and only while an item tooltip is open.
- **Never resumed.** A `.working` file found at start (the game closed during it)
  is renamed `.stopped` and never resumed by itself. The editor clears a stopped
  build when the player clicks, and a stopped drawing by itself.
- **Strikes.** Clearing gives the item the request stopped on a strike, but only
  when the request was what the game was doing as its session ended. An item with
  two strikes is not asked about again on that build.

Tests: `test_game_truth.py` and `test_game_truth_editor.py`. The whole suite is 570
tests (1 skipped) at the merge, 2026-09-24. ForgePact's side is covered by
`tests/item_truth_harness.cpp`, `tests/test_item_truth_contract.py` and
`tests/test_item_truth_behavior.py`.

Follow-up:
[issue #173](https://github.com/falorfrozen-cmd/hero-siege-offline-toolkit/issues/173),
which moves the reusable half of ForgePact's `ItemTruth.hpp` into `hs-game-sdk`.

## AFK FARM camp takes (2.16.1, 2026-09-25)

AFK FARM's camp (0.8) and town (0.9) fill their key rack and stock from AFK Materials:
- the key rack takes Basic Keys (12:0, golden chests) and Crystal Keys (12:1, crystal chests);
- the stock takes every town good. `AFK_TAKE_KINDS` is exactly AFK FARM's `tools/goods.py` list, 226 kinds:
  - keys: 12:0-2, 7-19, 21-30 and 33;
  - fragments, shards and tarot cards: 13:0-1, 18-42, 54 and 55;
  - materials, dusts and rare consumables: 14:0-23, 27-39, 43, 44, 49-51, 53-58, 60-66 and 68-70;
  - runes, gems, jewels and orbs: 15:1-69, 78-96 and 112-135.

  Anything else (a Pickaxe 12:20, the single-item 14:59, 15:136 and so on) is refused. A take is at most 32 kinds.

`POST /api/vault/afk-take` (`op_vault_afk_take`) has four actions:
- **`stock`** counts the plain stacks that can be taken: no custom name, sub and kind 0, at most 999.
- **`take`** removes `items` ([{cls, base, count}]) all or nothing, at most once per `requestId`. Smaller stacks are used up first (`_afk_take_plan`).
- **`status`** and **`cancel`** settle a request whose reply was lost.

How it stays exactly once:
- **Request id:** `InfiniteVault.take_items` checks the id inside the write transaction. A repeated id answers with the recorded `afk_items_taken` event.
- **Stale rows:** the rows are checked against a `preview_item_rework` token.
- **Used-up stacks** keep their deposit keys as deleted.
- **Cancel:** `cancel_take` records `afk_take_cancelled` unless the take already happened, so a late take with that id is refused.
- **Errors:** a committed take never answers with an error.
- **Undo:** `afk_items_taken` is an undo barrier.
- **Backups:** only the rolling `.bak` is written.
- **Game running:** SQLite only, so the game may run.

AFK FARM's client is `HS-AFK-Expedition/tools/vault_take.py`.

Replies name runes and orbs as AFK FARM does ("Lum Rune", "Orb of Goblin").

Tests:
- `AfkCampTakeTests` (6) and `AfkTownGoodsTakeTests` (3) in `test_vault_afk_qol.py`.
- The whole suite is 579 tests (1 skipped). Run it with `USERPROFILE` and `LOCALAPPDATA` pointed at a temporary folder: `ROOT` is `Path.home()`-based, so this keeps any test away from the machine's Vault.

Merged in falorfrozen-cmd/hero-siege-item-editor#9 and released as `v2.16.1` on 2026-09-25 (launch gate row above).

**Live check** (2026-09-25): AFK FARM 0.9 took seven kinds with `take`, and the Vault lost exactly those counts. For type 13, this editor made a Battle Fragment (13:0) in an empty Shared Stash tab with the game closed and deposited it into AFK Materials. AFK FARM's town then took it, and the game made it again. It came back to AFK Materials.

## Ports shared with other tools (2.16.2, 2026-09-25)

Reported while releasing 2.16.1: the editor could not start while ForgePact's panel held 8766. `main()` binds every port in 8765-8774, and a port that did not answer as an editor stopped startup ("occupied by an unidentified or legacy process").

**Measured before the fix** (Windows 11, Python 3.13). A dummy server sat on the real 8766, then the editor's real `main()` ran, with the window, message box and game truth replaced and `USERPROFILE`/`LOCALAPPDATA` in a temporary folder:
- **Dummy bound like ForgePact's panel** (`ThreadingHTTPServer`, which sets SO_REUSEADDR): the editor *started*, and counted 8766 as reserved. Its bind had succeeded on top of the dummy's. Every request to 8766 still reached the dummy, and the peer check never looked at 8766.
- **Dummy that does not share its port** (SO_REUSEADDR off): the editor refused, as reported.

How Windows binds, measured with throwaway servers on high ports:
- Two sockets that both set SO_REUSEADDR can bind the same port. The first listener kept all 40 test connections.
- A listener without the option makes a later SO_REUSEADDR bind fail with WSAEACCES (10013). A later bind without the option fails with WSAEADDRINUSE (10048).
- A server without the option rebinds at once over 28 TIME_WAIT connections.

**The fix (2.16.2).**
- `main()` binds with `EditorHTTPServer`, which has SO_REUSEADDR off on Windows, so an occupied port fails the bind.
- A port that fails and does not answer as an editor is left to its owner, and startup takes the rest.
- A different editor version is still refused, and the same version is still reused.
- A pre-2.7.2 build is still refused. Every commit before v2.7.2 lacks `/api/instance`, binds only 8765 and serves its page under the `<title>Hero Siege Item Editor`. `_legacy_editor_page` checks that title, on 8765 only, so the editor never fetches another program's page.
- `_peer_editor_error` and `INSTANCE_RESERVED_PORTS` are unchanged. The reserved set holds the ports this instance bound, so the peer check before each write also probes the ports left to other programs. ForgePact answers `/api/instance` there with a 404.

After the fix, with either dummy, the editor starts on 8765 and reserves 8765 and 8767-8774. 8766 keeps answering from the dummy.

Tests:
- `test_launch_readiness.py` has 29 tests. `ForeignPortTests` run `main()` on real sockets in 20000-32767, outside the ephemeral ranges and never in 8765-8774. The cases:
  - a sharing and a non-sharing server on the second port;
  - a non-editor on the first port;
  - a pre-2.7.2 editor page on the first port;
  - a held port that refuses a SO_REUSEADDR bind and still rebinds at once.
- All five cases fail when run against master's code.
- The whole suite is 585 tests (1 skipped), run with `USERPROFILE` and `LOCALAPPDATA` in a temporary folder.

**Not changed; for the owner to decide.** ForgePact's first port candidate is still 8766, inside the editor's range, so a running editor (2.8.0 or later) sends ForgePact to 8780. The hub's ForgePact health probe is `http://127.0.0.1:8766/`, and any 2xx counts, so the probe then gets the editor's page.

Read from `hub/src-tauri/src/launch.rs` and `hub/src/tool-presentation.js`, not reproduced: in that state ForgePact's card should show "Running externally" and offer no Launch button. Moving ForgePact's first candidate out of 8765-8774 would end this, together with the catalog's `ports` and `health.url`.

Merged in falorfrozen-cmd/hero-siege-item-editor#10 and released as `v2.16.2` on 2026-09-25 (launch gate row above). The released exe was started beside a ForgePact-like server on 8766. It listened on 8765 and 8767-8774 and left 8766 to that server.
