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
- `infinite_vault.py`: SQLite-backed permanent storage engine (schema version 6). Manages unlimited item collections and 17×18 stash pages, automatic migrations with pre-migration backups, item transfers, deduplication, full-text search, and cross-process file locking.
- `hss_recovery.py`: Corrupted `.hss` save file recovery and sanitization engine. Decodes base64/XOR/zlib payloads, enforces memory and recursion boundaries (128 MB max decoded payload, 256 max JSON depth), extracts salvageable inventory and character data, and creates timestamped recovery manifests.
- `custom_item_forge.py`: Custom forge validation and mutation engine. Manages custom property presets, donor item unique mechanics, linked proc bundles, keep/replace native stat semantics, and serializes sidecars to `%LOCALAPPDATA%\Hero_Siege\hs_custom_item_forge.json` and `.runtime`.
- `custom_forge_runtime.py`: ForgePact runtime status watcher. Inspects ForgePact capability markers, reads status from `bp_ipc/customforge_status.json`, verifies timestamp ordering between runtime files and reports, and checks process user matching.
- `game_build_identity.py`: Game executable fingerprinting and build identity verification. Checks `Hero_Siege.exe` headers and hash fingerprints to enforce version constraints (e.g., Season 10 patch compatibility).
- `exact_tooltip.py`: Accurate in-game tooltip generator matching native GameMaker layout, affix coloring, roll range formatting, socket statuses, and custom forge annotations.
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
|  - Atomic replace        .sqlite3 (schema 6)    - Validates stat keys & bundles         |
|  - Timestamped bak     - Migrations (v2->v6)    - Writes sidecars                       |
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
+-----------------------------------------------------------------------------------------+
```

---

## Process Boundaries, HTTP Security, & Save Safety

### 1. Loopback Binding & Port Range Guard
- The local server binds strictly to `127.0.0.1:8765`.
- At startup, the server acquires `editor-startup.itemeditor.lock` and inspects the port range `8765–8774`.
- If an existing instance of the same editor version is running, the launcher reuses it by opening the browser to that port.
- If an older or unrecognized process occupies a port in `8765–8774`, startup fails closed to prevent port confusion.
- While active, the editor responds with its application identity across all 10 reserved ports, preventing legacy versions (v2.7.2 and older) from spawning concurrently.

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
- **Live Stat Snapshots:** ForgePact exports the live runtime stat struct to `bp_ipc\itemstats.json` (at most once every 2 seconds). When editing an owned item, the editor reads this file to display verified in-game stat values.

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
| `py -3 -m unittest test_launch_readiness.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 23 launch and port verification tests | None | Verified |
| `py -3 -m unittest test_http_security.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 9 HTTP CSRF / Host header security tests | None | Verified |
| `py -3 -m unittest test_hss_recovery.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 17 save recovery and decode tests | None | Verified |
| `py -3 -m unittest test_hss_recovery_integration.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 12 recovery integration tests | Temp files in test sandbox | Verified |
| `py -3 -m unittest test_infinite_vault.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 44 SQLite vault schema and transaction tests | Temp SQLite databases | Verified |
| `py -3 -m unittest test_stat_semantics.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 13 stat semantics and bundle tests | None | Verified |
| `py -3 -m unittest test_socket_editor.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 18 socket solver and seed tests | None | Verified |
| `py -3 -m unittest test_small_charm_metadata.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 8 charm metadata tests | None | Verified |
| `py -3 -m unittest test_roll_profile_db.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs 24 roll profile evaluator tests | None | Verified |
| `py -3 -m unittest test_custom_forge_runtime.py` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs custom forge runtime bridge tests | None | Verified |
| `py -3 -m unittest discover -s . -p "test*.py"` | PowerShell / CMD | `hero-siege-item-editor/` | Python 3.10+ | Runs all 20 test suites (425 tests, 1 skipped; passes on a fresh clone with `core.autocrlf` true or false, 2026-09-23) | Temporary test fixtures | Verified |
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
| Port 8765 occupied / startup refused | Another process or legacy editor instance is using port 8765 | Close conflicting processes. The editor verifies application identity across ports 8765–8774 and refuses to bind if an unidentified service is present. |
| Corrupted `.hss` save file fails to open | Save file payload was partially written or truncated | Use `hss_recovery.py` via the recovery interface to decode and salvage valid character/inventory JSON. |
| Forged stats do not appear in combat | ForgePact plugin not installed or game launched without loader | Ensure `BloodPactPlugin.dll` is installed in the game's `bin/` directory and loaded via Aurie/YYToolkit. |

---

## Maintenance Triggers & Upstream Links

- **New Hero Siege Patches / Seasons:**
  - Verify `CreateItemNew` and `itemStatStruct` field formats using development ForgePact telemetry (`itemdrops.jsonl`).
  - Run `build_custom_forge_catalog.py` to regenerate the property catalog if new stat keys or unique items are added.
  - Check `game_build_identity.py` to update supported game version hashes.
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
