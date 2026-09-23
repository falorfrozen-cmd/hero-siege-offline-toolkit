# HS-AFK-Expedition Module Development Guide

## Module Overview & Metadata
- **Module Name:** HS-AFK-Expedition (AFK FARM)
- **Submodule Path:** `HS-AFK-Expedition`
- **Reviewed Git Revision:** `6079ee90bbe1828c5214f4277840c2eb73f8e350` (Branch: `main`; release tag `v0.6.4` is `5082037`)
- **Revision Date:** `2026-09-23`
- **Commit Message:** `Tell the toolkit hub about published releases`
- **Source Availability:** Full source:
  - the C++20 Aurie/YYToolkit plugin (`plugin/`);
  - the Python 3.13 standard-library panel and CLI (`tools/`);
  - the web UI (`web/`), the C++ launcher (`launcher/`) and the tests.

  The AGPL-3.0 Aurie/YYToolkit headers are placed by `tools/prepare_toolchain.py` and never committed (`plugin_build/include/`). Live verification records stay with the tester, outside the public repository.
- **CI / Pipeline Availability:** No test CI; the suites run locally (see Command Reference). Two workflows talk to the hub, and both need the `HUB_DISPATCH_TOKEN` repository secret:
  - `notify-hub.yml` (push to `main`) asks for a submodule pointer bump;
  - `notify-hub-release.yml` (release published) asks for a catalog rebuild.

  Releases are built locally with `tools/build_release.py` and uploaded to GitHub by hand.
- **Purpose & Scope:** Timed offline expeditions for Hero Siege.
  1. A calibration measures a hero's kill pace in one region.
  2. An expedition turns elapsed time into that many kills.
  3. Claiming replays every kill through the game's own drop and reward calls (items, XP, gold).

  Items the loot filter hides are sold or broken down inside the game. Delivered items go to Hero Siege Item Editor's Infinite Vault. The tool is for offline, single-player play only.

---

## Architecture & Repository Map

### Repository Layout
- `plugin/`: the Aurie module `HSAfkExpeditionPlugin.dll` (C++20, YYToolkit).
  - `ModuleMain.cpp`: the core of the plugin:
    - script hooks and IPC commands;
    - calibration capture and reward delivery;
    - checkpoints and the spool writer.
  - `IndependentRewards.inl`, `FarmContext.inl`, `TestSession.inl`: reward modifiers, the build-bound farm context, and the game-session test driver.
  - `include/AfkExpedition/`: `Conversion.hpp` (selling and breaking down filtered items), `Packet.hpp`, `RewardPolicy.hpp`, `RuntimeState.hpp` (continue rules), `Version.hpp`.
- `plugin_build/build.bat`: MSVC build of the plugin against `hs-game-sdk/cpp/include` and the toolchain headers.
- `tools/`: Python 3.13, standard library only.
  - `panel.py`: local HTTP panel on 127.0.0.1:8787 (next free port through 8796) serving `web/`.
  - `afk.py`: CLI and core: profiles, plans, claims, spool, delivery speeds.
  - Other tools:
    - `recovery.py`, `notify.py`, `calibration.py` and `validate_farm.py`;
    - `reward_modifiers.py`, `loot_filter.py` and `game_session.py`;
    - `ingest_spool.py` (the Vault transfer client);
    - `build_release.py` and `prepare_toolchain.py`.
- `web/`: the panel UI (`index.html`, `app.js`, `extras.js`, `qol.js`, `modifiers.js`, `style.css`), `zones.json`, `items.json`, and item icons reused from the Item Editor (provenance in `web/assets/items/SOURCE.json`).
- `launcher/Launcher.cpp`: builds `AFK FARM.exe`, which starts the bundled `runtime\python.exe` on `app\tools\panel.py`.
- `tests/`: Python unittest suites, Node UI tests (`test_panel_ui.cjs`, `test_map_ui.cjs`), and C++ smoke tests (`tests/cpp/`, run by `tests/build_and_run.bat`).
- `docs/`: `PLAYER_GUIDE.md`, `DESIGN.md`, `UI_CONTRACT.md`, `INDEPENDENT_REWARDS.md`, `TEST_SESSIONS.md`, `AUDIT_FIXES.md`, and historical notes.

### Data Flow
1. **Calibration.** The plugin records kills and farm-clock time in a region. `afk.py` saves a profile with the pace and the farm context (build, loadout, settings).
2. **Expedition.** A plan turns the chosen duration (up to 8 h) into kill packets. The timer keeps running while the game is closed.
3. **Claim.** The recorded hero must be in the recorded region, on the same game build. The plugin replays each kill through the game's native drop calls at the chosen delivery speed.
   - It writes a spool (`%LOCALAPPDATA%\Hero_Siege\afk\spool\<expedition>.ndjson`) and checkpoints.
   - A paused or crashed delivery continues from its recorded position.
4. **Filtered items (0.6.2).** Items the loot filter hides are converted in the game:
   - below Satanic, they are sold for gold;
   - Satanic and above are broken down with the Prospector's recipes.

   This happens only while the game has no API exchange connection.
5. **Vault transfer.** The panel (or `ingest_spool.py`) posts the spool to Item Editor's loopback API (`POST /api/vault/ingest`): one category per expedition, plus AFK Materials.

Data lives under `%LOCALAPPDATA%\Hero_Siege\afk\` (`profiles`, `sessions`, `plans`, `packets`, `spool`, preference and delivery-rate files). Plugin backups go to `afk\plugin-backups\`.

---

## Supported Platforms, Prerequisites & Dependencies
- **Platform:** Windows only. Hero Siege with Aurie and YYToolkit installed for the game build.
- **Python:** 3.13 (standard library) for the panel and tools. The release bundles an embeddable Python 3.13.
- **Compiler:** MSVC (C++20) for the plugin, the launcher and the C++ tests.
- **From the hub:** the `hs-game-sdk` C++ headers `hs_game_sdk.hpp`, `native_names.hpp`, `reward_scope.hpp` and `reward_stats.hpp`, and the Python `hs_game_sdk` (`GameObject`, `GameScript`, `GameRoom`). `build_release.py` copies the Python SDK into the package.
- **Node.js:** only for the UI tests.
- **Item Editor:** Hero Siege Item Editor 2.15.5 or later for Vault transfers. 2.15.8 keeps fragment stack counts; 2.15.10 adds stacking and DISMANTLE.

## Command Reference

All commands run from `HS-AFK-Expedition/`.

| Command | Shell | Purpose | Status |
| --- | --- | --- | --- |
| `py -3 -B tools/panel.py` | PowerShell / CMD | Runs the panel from source | Verified |
| `py -3 -B -m unittest discover -s tests -p "test_*.py"` | PowerShell / CMD | 143 Python tests (temporary data, fake IPC) | Verified 2026-09-23 |
| `node --test tests/test_panel_ui.cjs` | PowerShell / CMD | 22 panel UI state tests | Verified 2026-09-23 |
| `node --test tests/test_map_ui.cjs` | PowerShell / CMD | 11 map UI tests | Verified 2026-09-23 |
| `tests\build_and_run.bat` | CMD | C++ packet, runtime (38 checks) and rewards smoke tests | Verified 2026-09-23 |
| `plugin_build\build.bat` | CMD | Builds `HSAfkExpeditionPlugin.dll` | Verified |
| `launcher\build.bat` | CMD | Builds `AFK FARM.exe` | Verified |
| `py -3.13 -B tools/build_release.py` | PowerShell / CMD | Builds `dist/AFK-FARM-<version>/` and its zip | Verified 2026-09-23 (0.6.4) |

## Safety Rules
- **Native rewards only.** Rewards come only from the game's native drop and reward calls. No item structures are generated in Python or JavaScript.
- **What a claim needs.** The recorded hero (identity version 2: save slot, name and class), the same game build, and the recorded region. Since 0.6.3, a changed loadout, level or combat setting does not block a claim; the calibrated pace still sets the rewards.
- **Offline-only conversion.** Converting filtered items needs the game's API exchange to be disconnected. `ReportClient` sends whenever it is connected, even offline; in that case the plugin keeps the items.
- **Vault transfers.** Never replay rewards to repair a Vault transfer; retry the transfer instead. The Vault refuses to re-import deleted or dismantled AFK records (`deleted_deposit_keys`).
- **Plugin DLLs.** Plugin backups stay outside `mods/aurie`, because Aurie loads every `.dll` there. Do not overwrite the DLL of a running game.
- **No decompiled source.** Decompiled game source never enters the repository (hub `AGENTS.md`, Legal).

## Releases & Hub Integration
- **Package.** `tools/build_release.py` names the package after `VERSION` in `tools/panel.py`. The zip carries an `AFK-FARM-<version>/` root with `MANIFEST.json` (a SHA-256 for every file).
- **Release assets.** GitHub releases carry `AFK-FARM-<version>.zip` and its `AFK-FARM-<version>.zip.sha256` sidecar.
- **Catalog.** The catalog id is `afk-farm` (`catalog/sources.toml`), and its asset pattern is `^AFK-FARM-[0-9][^/]*\.zip$`.
- **Dispatch token.** Until the AFK repository has the `HUB_DISPATCH_TOKEN` secret (the same token the other tools use), pointer bumps and catalog rebuilds are started by hand: Actions → Catalog → Run workflow, with `only: afk-farm`.

## Testing & Validation Classification
1. **Game-free.** The Python, Node and C++ suites above.
2. **Live-game checks.** The maintainer ran these on a verified build: calibration, claims, delivery speeds, pause and continue, filtered-item conversion, and Vault transfer. Those records stay outside the public repository.

## Known Gaps
- **Beta.** Automatic startup and **Claim in background** support the verified executable only.
- **Build-bound.** The plugin's farm context is tied to one game build; a game update needs a new verification.
- **Item Editor release.** The Vault side needs Item Editor 2.15.5 or later, which is on its `master` branch until its next release.

## Related Guides
- [hero-siege-item-editor](../hero-siege-item-editor/instructions.md): Infinite Vault, AFK transfers, DISMANTLE
- [hs-game-sdk](../hs-game-sdk/instructions.md): reward scope, reward stats, native routine names
- [ForgePact](../ForgePact/instructions.md): shared reward scope
- [Shared Documentation Index](../README.md)
