# HS Save Editor Module Development Guide

## Module Overview & Metadata
- **Module Name:** HS Save Editor (Hero Siege Character Save Editor)
- **Submodule Path:** `HSSaveEditor`
- **Reviewed Git Revision:** `c01f9f968c9d85a8e0147c05df0ee78d237c5877` (v1.4.3, Branch: `fix/block-saves-while-game-runs`, [PR #5](https://github.com/falorfrozen-cmd/HSSaveEditor/pull/5); the `v1.4.3` tag follows the merge)
- **Revision Date:** `Sat Sep 26 11:09:45 2026 +0700`
- **Commit Message:** `v1.4.3: Refuse to write saves while Hero Siege is running`
- **Source Availability:** Full application source is present (`hs_save_editor.py`, `test_hs_save_editor.py`, `README.md`, `RELEASE_NOTES.md`, `LICENSE.txt`, and standalone Windows distribution `HeroSiegeSaveEditor.exe`).
- **CI / Pipeline Availability:** No test or build CI: no workflow runs `test_hs_save_editor.py` or builds `HeroSiegeSaveEditor.exe`, so validation is local (Python `unittest`, see the command table below). The repository has two GitHub Actions workflows, and both only notify this hub through the `HUB_DISPATCH_TOKEN` secret: `.github/workflows/notify-hub.yml` sends `submodule-updated` on every push to `main`, which the hub's `submodule-dispatch.yml` turns into the pointer-bump pull request, and `.github/workflows/notify-hub-release.yml` sends `release-published` when a stable release is published (or when run by hand), which the hub's `catalog.yml` uses to rebuild the tool catalog.
- **License & Provenance:** Permissive offline-use license (`LICENSE.txt` — allows use, copying, modification, and redistribution provided it is not represented as an official Hero Siege tool, is not used for online/multiplayer/trading/anti-cheat modes, and license terms remain attached).
- **Purpose & Scope:** Standalone offline save editor and Season 10 progression forge for Hero Siege character `.hss` save files. Operates strictly offline on local saves located in `%LOCALAPPDATA%\Hero_Siege` (`hs2saves/`), shared account data in `shop.ini`, and per-character Ether sidecars (`ether<N>.hss`). Enables modification of character attributes, gold and professions, difficulty unlocking via the Act 9 campaign clear gate, difficulty-scoped waypoint unlocking, complete 30-cell charm grid activation (`fallOfDarkness|4`), exact quest-derived Ether Point allocation (100–800), and comprehensive subskill tree rank customization for all 24 playable classes. Modifications generate pre-mutation timestamped backups. Since v1.4.3 every write first checks that Hero Siege is closed and refuses while it runs (see [Game-Closed Check](#1-game-closed-check-since-v143)).

---

## Architecture & Repository Map

### Repository Layout
- `hs_save_editor.py`: Primary application source code and desktop entry point. Implements a Tkinter desktop GUI styled with a responsive Season 10 Character Save Forge dark rune theme, save discovery routines, binary XOR/zlib/base64 encoding and decoding pipelines, INI section mutation helpers, `shop.ini` synchronization, Ether sidecar managers, translation table resolution with built-in audited EXE class fallbacks, subskill cap validation, a running-game check before every write, and automated backup cleanup routines.
- `test_hs_save_editor.py`: Python `unittest` test suite containing 105 unit and integration tests across `CharacterBackupCleanupTests`, `Season10ProgressTests`, `DeletedSlotTests` and `GameRunningGuardTests`. Tests cover `.hss` round-trip serialization, starting a character in a slot emptied by an in-game delete, the running-game check before every write, odd quest stage flooring, Ether point validation, 24-class subskill tree verification, legacy tree migration, and link/junction safety.
- `HeroSiegeSaveEditor.exe`: Pre-compiled standalone Windows executable built via PyInstaller.
- `README.md`: End-user documentation, feature overviews, Steam Deck / Proton directory guidance, and PyInstaller build instructions.
- `RELEASE_NOTES.md`: Changelog documenting version changes from v1.3.0 through v1.4.3.
- `LICENSE.txt`: Project license terms and offline safety notice.
- `.gitignore`: Build artifact ignores (`dist/`, `build/`, `*.spec`, `*.bak*`, `__pycache__/`).

---

## Component Architecture & Data Flow

```text
+-----------------------------------------------------------------------------------------+
|                                  HS SAVE EDITOR (Python / Tkinter)                      |
|                                                                                         |
|   +----------------------------------------------------------------------------------+  |
|   |                           HssEditorApp (Desktop UI)                              |  |
|   |  - Character Vault Listbox (Numeric Slot Order)                                  |  |
|   |  - Attribute & Profession Editors (Level, Gold, Professions)                     |  |
|   |  - Action Grid: Unlock Difficulties, Unlock Waypoints, Unlock 30-Cell Charm Grid |  |
|   |  - Progression Modals: Ether Points Picker (100-800), Subskill Tree Forge        |  |
|   |  - Backup Cleanup Modal (Controlled Scans & Explicit Confirmation)               |  |
|   +------------------+-------------------------------+-------------------------------+  |
|                      |                               |                                  |
|                      v                               v                                  v
|       [ Save Decoder / Encoder ]           [ Shared Shop Engine ]             [ Ether Sidecar Engine ]
|       - Base64 / zlib / XOR                - shop.ini parser                  - ether<N>.hss manager
|       - Round-trip INI sections            - [shop] gold & professions        - StatEtherPoints logic
|       - Preserves unknown data             - Atomic backup & write            - Loadout preservation
+----------------------|-------------------------------|----------------------------------+
                       |                               |                                  |
                       +-------------------------------+----------------------------------+
                                                       |
                                                       v (Direct file I/O with .bak)
+-----------------------------------------------------------------------------------------+
| LOCAL DISK STORAGE: %LOCALAPPDATA%\Hero_Siege\ (or hs2saves\)                           |
|                                                                                         |
|   - Character Saves:  herosiege<N>.hss  (herosiege1.hss .. herosiege24.hss)             |
|   - Shared Account:   shop.ini (Gold, Mining, Woodcutting, Fishing, Blacksmith, Alchemy)|
|   - Ether Sidecars:   ether<N>.hss (Ether Tree node allocations per character slot)     |
|   - Backups:          herosiege<N>.hss.bak_YYYYMMDD_HHMMSS                              |
|   - External CSVs:    HeroSiege\bin\translationsTalent.csv, translationsSubTalent.csv   |
+-----------------------------------------------------------------------------------------+
```

---

## Data Contracts & File Formats

### 1. Character Save Format (`herosiege<N>.hss`)
Hero Siege encodes character saves using a combination of character interleaving, XOR obfuscation, zlib compression, and Base64 encoding.

- **Decoding Pipeline (`decode_hss_bytes`, `decode_hss_file`):**
  1. Strip whitespace and null bytes (`\x00`).
  2. Base64 decode to retrieve compressed bytes.
  3. Decompress via `zlib.decompress`.
  4. XOR decode byte-by-byte using the repeating multi-byte key `HSS_XOR_KEY`.
  5. Validate that high bytes (`decoded[1::2]`) are null (rejecting corrupted payloads if the non-zero ratio exceeds 1%).
  6. Extract payload from even bytes (`decoded[::2]`) and decode as UTF-8 (falling back to Latin-1 if needed).
  7. Plain text fallback: If unencoded plain INI text is detected (`looks_like_plain_character_ini`), the file is loaded directly.
- **Encoding Pipeline (`encode_hss_text`, `write_hss_file`):**
  1. Normalize line endings to `\r\n`.
  2. Encode UTF-8 text into an interleaved byte stream (even bytes receive the text, odd bytes are `0x00`).
  3. Obfuscate via `xor_bytes` with `HSS_XOR_KEY`.
  4. Compress using `zlib.compress(..., level=9)`.
  5. Base64 encode and append a trailing null byte (`\x00`).
- **Key Character Sections:**
  - `[0]`: Character identity and stats (`name`, `class`, `level`, `hero_level`, `experience`, `gold`, `wormhole_level`, `difficulty`, `hell_subdifficulty`, `soloselffound`, `talent_loadout`, `act_1`..`act_9`, `zone1,0`..`zone9,9`). All numbers are formatted with 6 decimal places (e.g. `"1.000000"`).
  - `[4]`: Quest progression dictionary (`questlog_chain<N>="<chain>|<stage>"`, `questlog_diff<N>="<diff>"`). Contains the 9 Ether quest chains and the Charm unlock quest (`fallOfDarkness|4`).
  - `[inventory]`: Contains item descriptors (`item_0=""`, etc.). Preserved byte-for-byte during character modifications.
  - `[talent_loadout_<N>]`: Active skill tree allocations (`talent_<id>="1"`).
  - `[subtalent_loadout_<N>]`: Subskill allocations (`subtalent_<tree_id>_s<node_id>="<rank>"`).

### 2. Shared Account Data (`shop.ini`)
- Hero Siege stores gold and profession progress in `shop.ini` under the `[shop]` section rather than inside character saves.
- Managed keys: `gold`, `mining`, `woodcutting`, `fishing`, `blacksmithing`, `alchemy`.
- Writing character gold or profession values in the editor automatically locates and updates `shop.ini` in the active save folder.

### 3. Ether Sidecars (`ether<N>.hss`) & Point Calculation
- **Sidecar File:** Stored at `ether<N>.hss` (matching the character slot number `N`).
- **Payload Structure:** An encoded `.hss` file containing `[ether]` or `[ether_loadout_<N>]` sections with key-value entries `node_<node_id>="1"`.
- **Point Calculation Formula:**
  - Total earned Ether Points are calculated from the character's 9 native quest chains in section `[4]` (`act1_ether` through `act8_ether`, plus `wormhole_ether`), matching the game's native `StatEtherPoints` routine.
  - Each quest chain awards points in increments based on completed stages. Odd stages (e.g., stage 7 after an incomplete Inferno challenge) are floored to the lower even stage (`math.floor(stage / 2) * 2`) rather than throwing fractional point errors.
  - Available unspent points = Total Earned Points − Active Loadout Allocated Nodes.
- **Ether Points Picker:** Offers preset totals: 100, 200, 300, 400, 500, 600, 700, or 800. The picker blocks selections lower than the active loadout's currently allocated node count to prevent negative unspent balances.
- **Future Node ID Preservation:** Ether node IDs are read without a fixed upper limit, ensuring future expanded trees remain compatible.

### 4. Subskill Tree & Talent Mapping
- **24 Playable Classes:** Viking, Pyromancer, Marksman, Nomad, Redneck, Necromancer, Samurai, Paladin, Amazon, Demon Slayer, Demonblade, Shaman, White Mage, Marauder, Plague Doctor, Berserker, Exorcist, Shield Lancer, Illusionist, Jotunn, Prophet, Phantom Knight, Huntress, Mechanic.
- **14 Nodes per Tree:**
  - `s1`–`s10`: Small subskill nodes. Each node possesses a game-verified rank cap (default 5, with tree-specific caps ranging from 1 to 8, such as Marksman Gunner Drone or Rapidfire).
  - `s11`–`s14`: Mutually exclusive major/special nodes. When a major node is selected, it is written as 3/3 (`"3.000000"`) and competing major nodes (`s11`–`s14`) in that tree are set to 0.
- **Translation Discovery & Fallback:**
  - Checks for game translation files `HeroSiege\bin\translationsTalent.csv` and `translationsSubTalent.csv` in `%LOCALAPPDATA%` and Steam directories.
  - If CSVs are absent, falls back to the audited built-in 24-class EXE mapping table (`S10_EXE_TALENT_IDS_BY_CLASS`, `S10_VERIFIED_SUBTALENT_IDS`, `S10_SMALL_SUBTALENT_CAP_OVERRIDES`).
- **Legacy Migration & Safety:**
  - Historical/renamed parent skills map via `S10_SUBTALENT_PARENT_ALIASES`.
  - Deprecated tree IDs migrate only when a single unambiguous verified native target exists (e.g., legacy Poison Nova `t119` -> `t118`); ambiguous historical IDs are preserved without guessing.

### 5. Unused and Deleted Slots
- **Unused slot:** the game keeps a blank character in a slot that never held one. Decoded it is `BLANK_SLOT_TEXT`: an `[inventory]` section with an empty inventory and `[0] version="8.000000"`. The list shows it as `Unnamed`, and it opens like any character.
- **Deleted slot:** deleting a character in the game rewrites the slot's `herosiege<N>.hss`, `ether<N>.hss`, `incarnation<N>.hss` and `inventory_order_<N>.hss` as a single NUL byte ([Runtime Data Models § 8.2](../../RUNTIME_DATA_MODELS.md#82-main-menu-and-character-select)). `decode_hss_file` raises `EmptySlotError`, a subclass of `HssFormatError`, for it, and the list shows `Empty slot - open to start a new character`.
- **Starting a character there (v1.4.2):** opening an emptied `herosiege<N>.hss` asks first (`offer_blank_character`). On yes, `create_blank_character_slot` backs up the empty file with the usual `.bak_<timestamp>` name and writes `BLANK_SLOT_TEXT`, then the slot opens for editing. It refuses any file that is not a still-empty `herosiege<N>.hss`, so a slot that gained a character meanwhile is never overwritten. The other three files stay as the game left them; `read_ether_file` already reads an emptied `ether<N>.hss` as no Ether data.
- **Character count:** `list_label_is_character` leaves `Unnamed`, emptied, `Empty / unsupported` and `Not a character` entries out of the "N CHARACTERS" summary.
- **Test fixture:** `GAME_UNUSED_SLOT_FILE` in `test_hs_save_editor.py` is the game's own unused-slot file. It pins `BLANK_SLOT_TEXT`; if a future season changes the blank character, refresh the fixture from a fresh install before changing the constant.

---

## Process Boundaries, Save Safety, & Backup Protection

### 1. Game-Closed Check (Since v1.4.3)
- Save editing must only occur while `Hero_Siege.exe` is completely terminated. Writing to saves while the game is running risks process file locks, memory overwrites, or save truncation.
- **Every write checks first.** `HssEditorApp.ensure_game_closed()` runs right before `save_current`, `save_as`, `save_ether_changes`, `offer_blank_character` (before `create_blank_character_slot`) and `clean_character_backups` write or delete anything. It runs after their own confirmation dialogs, so a game started after the editor opened is caught too. Before v1.4.3 nothing checked; the README and release notes only asked the player to close the game.
- **Detection:** `game_running_state()` returns True, False or None. `tasklist_says_running()` runs `tasklist /FI "IMAGENAME eq Hero_Siege.exe" /FO CSV /NH` and decodes the output leniently, because Turkish and German Windows print the "no tasks" notice in the OEM code page. `powershell_says_running()` asks `Get-Process` only when tasklist gave no answer. The approach follows the item editor's `game_running()` (`hero-siege-item-editor/hs_item_editor_gui.py`), with one difference: a check that cannot run is not counted as "running".
- **Outcomes:** while the game runs, the write is refused with an error dialog and no file changes. When it is closed, the write goes ahead as before. When neither command answers (possible under Proton or Wine), the editor asks "Continue anyway?", defaulting to No, so a Steam Deck player is warned instead of locked out.
- **Tests:** `GameRunningGuardTests` covers detection with captured `tasklist` and PowerShell output, and all five writes in all three states. A module-level patch in `test_hs_save_editor.py` makes every other test see "closed", so the suite does not depend on whether the game is open on the machine running it.
- The hub's "Requires game closed" label (`requires.game_closed` in `catalog/sources.toml`) is still only a label, and the hub still launches the editor while the game runs; the editor's own check covers the writes.
- The editor does not inject code into live game processes or modify game memory.

### 2. Pre-Mutation Backups
- Every save modification automatically creates a timestamped copy:
  - Pattern: `herosiege<N>.hss.bak_YYYYMMDD_HHMMSS`
  - Location: Placed in the same directory as the target save file.
  - `shop.ini` and `ether<N>.hss` modifications create corresponding `.bak_<timestamp>` files before rewriting.

### 3. Safe Backup Cleanup Rules
- **Target Filter:** Matches only files strictly conforming to `CHARACTER_BACKUP_NAME_PATTERN` (`^herosiege\d+\.hss\.bak_\d{8}_\d{6}$`).
- **Protected Files:** Active character saves (`herosiege<N>.hss`), Shared Stash (`stash.hss`), `shop.ini`, Ether sidecars (`ether<N>.hss`), and non-character backups are excluded from cleanup.
- **Directory Scope:** Scans the selected folder and its direct `hs2saves` child (unless `hs2saves` is already the selected folder).
- **Link & Junction Avoidance:** Symlinks and Windows directory junctions are detected via `path_is_link_or_junction` and skipped to prevent traversal out of the intended save root.
- **Confirmation Requirement:** Requires explicit user confirmation via a modal dialog before performing deletions; deletion validates snapshot freshness against disk state.

### 4. Separate Difficulty and Waypoint Operations
- **Difficulty Unlock:** Sets the Act 9 campaign clear gate in section `[4]` (`questlog_chain<N>="act9_campaign|4"`), unlocking Normal, Nightmare, Hell, and Inferno without altering the character's currently selected difficulty or overwriting waypoint arrays.
- **Waypoint Unlock:** Unlocks all 10 zone slots for Acts 1–9 (`act_1`..`act_9` = 1, `zone1,0`..`zone9,9` = 1) strictly for the *currently selected difficulty*. To unlock Inferno waypoints, the player selects Inferno in-game, saves, and executes the waypoint unlock action.
- **30-Cell Charm Grid Unlock:** Sets `fallOfDarkness|4` in `[4]` (the native Season 10 `Light of Dawn` quest completion state) and strips legacy synthetic `charmSlot` keys from section `[0]`.

---

## Setup, Build, Run, & Test Commands

All commands below are executed from the submodule root `HSSaveEditor/` unless otherwise indicated.

| Command | Shell / Platform | Working Directory | Prerequisites | Expected Result | Side Effects | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `py -3 hs_save_editor.py` | PowerShell / CMD (Windows) | `HSSaveEditor/` | Python 3.10+ (Tkinter included) | Launches Tkinter Character Save Forge UI | Reads local saves in `%LOCALAPPDATA%\Hero_Siege` | Verified |
| `py -3 -m unittest test_hs_save_editor.py` | PowerShell / CMD | `HSSaveEditor/` | Python 3.10+ | Runs all 105 automated unit and integration tests | Creates temporary directories in test sandbox | Verified |
| `py -3 -m unittest test_hs_save_editor.CharacterBackupCleanupTests` | PowerShell / CMD | `HSSaveEditor/` | Python 3.10+ | Runs 8 backup cleanup and safety tests | None | Verified |
| `py -3 -m unittest test_hs_save_editor.Season10ProgressTests` | PowerShell / CMD | `HSSaveEditor/` | Python 3.10+ | Runs 82 Season 10 progression, talent, and Ether tests | None | Verified |
| `py -3 -m unittest test_hs_save_editor.DeletedSlotTests` | PowerShell / CMD | `HSSaveEditor/` | Python 3.10+ | Runs 8 unused and deleted slot tests | Creates temporary directories in test sandbox | Verified |
| `py -3 -m unittest test_hs_save_editor.GameRunningGuardTests` | PowerShell / CMD | `HSSaveEditor/` | Python 3.10+ | Runs 7 running-game check tests | Creates temporary directories in test sandbox | Verified |
| `python -m PyInstaller --onefile --windowed --name HeroSiegeSaveEditor hs_save_editor.py` | PowerShell / CMD (Windows) | `HSSaveEditor/` | Python 3.13 (documented build environment), PyInstaller | Packages standalone GUI executable `dist/HeroSiegeSaveEditor.exe` | Creates `build/`, `dist/`, and `.spec` files | Inspected |

### Build Environment & Packaging Notes
- **Documented Build Environment:** Python 3.13 with PyInstaller is the documented build environment used for official release binaries (`HeroSiegeSaveEditor.exe`). Python 3.13 is recorded as the documented build environment, not an inferred strict minimum runtime requirement; the source code is compatible with Python 3.10+.
- **PyInstaller Recipe:** Packaging uses `--onefile --windowed --name HeroSiegeSaveEditor` targeting `hs_save_editor.py`. No external C extensions, DLL hooks, or non-standard asset folders are required because all rune UI elements are procedurally rendered in Tkinter Canvas and standard library modules are utilized.
- **Test Sandbox Paths:** In Windows environments where `TEMP` paths use 8.3 short names (e.g. `ADMINI~1`), path string assertions comparing `tempfile` outputs with long user profiles may differ during explicit path equality checks; tests using standard temporary files run cleanly.

---

## Coding Conventions & Persistence Invariants

- **Standard Library Only:** Built entirely using Python standard libraries (`tkinter`, `sqlite3`, `subprocess`, `zlib`, `base64`, `json`, `pathlib`, `re`, `shutil`, `argparse`, `dataclasses`, `math`). Requires no third-party package installations for development or execution.
- **Preservation of Unknown Keys:** When parsing and rewriting `.hss` files, unrecognized INI sections and key-value pairs are preserved in their original ordering to prevent data loss across game patches.
- **GameMaker Numeric Formatting:** Floating-point numbers written to `.hss` sections use 6 decimal places (e.g., `1.000000`, `0.000000`, `5.000000`) matching GameMaker Studio's native serialization format.
- **Fail-Closed Progression:** Subskill rank inputs exceeding node caps or unverified class IDs are rejected immediately before file writes can occur.
- **Atomic Operations:** File modifications generate backups prior to write, write normalized payloads, and verify buffer validity.

---

## Troubleshooting & Common Edge Cases

| Issue / Symptom | Root Cause | Solution |
| --- | --- | --- |
| Save slot appears as "Empty / unsupported" | File is not a readable save: a Steam Cloud placeholder, a save from an incompatible platform, or the wrong folder | Verify that the save slot contains an active character and that the selected directory matches the game's active save folder. |
| Slot shows "Empty slot - open to start a new character" (before v1.4.2: "Empty / unsupported" and "This save slot is empty") | The character in that slot was deleted in the game, which empties the slot's files | Open the slot and confirm: the editor backs up the empty file and writes the game's blank character (v1.4.2+). On older versions, copy an unused slot's `herosiege<N>.hss` over it. |
| Changes do not appear in-game | Hero Siege was running while saving, causing the game to overwrite files on exit | Close Hero Siege completely before editing. Re-open editor, apply modifications, save, and then start the game. |
| Save refused with "Hero Siege is running" (v1.4.3+) | `Hero_Siege.exe` is running, and the editor refuses every write while it runs | Close the game completely, then save again. |
| "Could not check whether Hero Siege is running" before a write (v1.4.3+) | Neither `tasklist` nor PowerShell answered, which can happen under Proton or Wine | Answer Yes only when Hero Siege is closed; No cancels the write. |
| Steam Deck / Proton saves not found | Editor is pointing to local Windows AppData rather than the Proton prefix | On Linux/Steam Deck, direct the editor to the Hero Siege Proton prefix: `<SteamLibrary>/steamapps/compatdata/269210/pfx/drive_c/users/steamuser/AppData/Local/Hero_Siege/`. |
| "Total points below allocated nodes" in Ether picker | Selected Ether total is lower than the points already allocated in the active Ether Tree | Choose an Ether Point preset equal to or higher than the number of nodes already allocated in the sidecar loadout. |
| Backup cleanup does not remove old files | Files do not match `herosiegeN.hss.bak_YYYYMMDD_HHMMSS` or reside in symlinked folders | Ensure backup filenames follow the standard pattern. Symlinks and junctions are intentionally skipped for safety. |
| Waypoints locked on Inferno after unlocking | Waypoints were unlocked while character was set to Normal or Nightmare | Select Inferno in-game, save character, then run "Unlock Waypoints (Current Difficulty)". Waypoint unlocks apply only to the active difficulty tier. |

---

## Maintenance Triggers & Upstream Links

- **New Hero Siege Classes or Reworked Subskills:**
  - Update `S10_EXE_TALENT_IDS_BY_CLASS`, `S10_VERIFIED_SUBTALENT_IDS`, and `S10_SMALL_SUBTALENT_CAP_OVERRIDES` in `hs_save_editor.py`.
  - Add test fixtures in `test_hs_save_editor.py` verifying the 14-node layout for new class trees.
- **Save Encoding / XOR Key Changes:**
  - If GameMaker save obfuscation changes in a future season, update `HSS_XOR_KEY` and test round-trip encoding against new save samples.
- **Game Executable Rename:**
  - If a game update renames `Hero_Siege.exe`, update `GAME_PROCESS_NAME` in `hs_save_editor.py` (the PowerShell check uses its stem) and the captured `tasklist` fixtures in `GameRunningGuardTests`.
- **Shared Toolkit Documentation Links:**
  - Submodule Index: [`../README.md`](../README.md)
  - ForgePact (Native Aurie Plugin): [`../ForgePact/instructions.md`](../ForgePact/instructions.md)
  - Hero Siege Item Editor: [`../hero-siege-item-editor/instructions.md`](../hero-siege-item-editor/instructions.md)
  - HSCraftSim (Crafting Simulator): [`../HSCraftSim/instructions.md`](../HSCraftSim/instructions.md)
  - HS Offline Launcher: [`../HS-Offline-Launcher/instructions.md`](../HS-Offline-Launcher/instructions.md)
  - HS Offline Tracker: [`../HS-Offline-Tracker/instructions.md`](../HS-Offline-Tracker/instructions.md)
