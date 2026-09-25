# HS-AFK-Expedition Module Development Guide

## Module Overview & Metadata
- **Module Name:** HS-AFK-Expedition (AFK FARM)
- **Submodule Path:** `HS-AFK-Expedition`
- **Reviewed Git Revision:** `75e335c` (Branch: `main`; release tag `v0.6.4` is `5082037`)
- **Revision Date:** `2026-09-23`
- **Commit Message:** `Opt-in AI code review, like ForgePact and the toolkit`
- **Source Availability:** Full source:
  - the C++20 Aurie/YYToolkit plugin (`plugin/`);
  - the Python 3.13 standard-library panel and CLI (`tools/`);
  - the web UI (`web/`), the C++ launcher (`launcher/`) and the tests.

  The AGPL-3.0 Aurie/YYToolkit headers are placed by `tools/prepare_toolchain.py` and never committed (`plugin_build/include/`). Live verification records stay with the tester, outside the public repository.
- **CI / Pipeline Availability:** No test CI; the suites run locally (see Command Reference). Two workflows talk to the hub, and both need the `HUB_DISPATCH_TOKEN` repository secret:
  - `notify-hub.yml` (push to `main`) asks for a submodule pointer bump;
  - `notify-hub-release.yml` (release published) asks for a catalog rebuild.

  `ai-review.yml` is the opt-in AI code review, ForgePact's workflow with only the repository guard changed. A pull request gets a review when it is labelled `ai-review` or someone with write access comments `@claude review` (text after the phrase narrows the scope). It needs the Claude GitHub App installed on the repository and the `CLAUDE_CODE_OAUTH_TOKEN` secret from `claude setup-token`.

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
- **Item Editor:** Hero Siege Item Editor 2.15.5 or later for Vault transfers. 2.15.8 keeps fragment stack counts; 2.15.10 adds stacking and DISMANTLE; 2.16.1 lets the camp and town (0.8-0.9) take their goods from AFK Materials.

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

## Workers and the camp (0.7.0-0.8, in review)

Not released yet. They are in falorfrozen-cmd/HS-AFK-Expedition#1 (0.7.0) and #2 (0.8, stacked on #1). The design notes are in the module's `docs/DESIGN.md`, the API in `docs/UI_CONTRACT.md`, and the player text in `docs/PLAYER_GUIDE.md`.

- **Workers** (`tools/workers.py`, 0.7.0):
  - They are paid with the game's gold (`afk worker pay`, one receipt per request).
  - A trip takes real time. Its haul is made in the game (`afk worker deliver`, `LootGroundCreate`) and then transferred to the Vault.
- **The camp** (0.8: `camp.py`, `traits.py`, `teams.py`): buildings, camp resources, traits and team trips. This is AFK FARM's own layer. It changes the crew's numbers and the Siege gate, and never makes an item.
- **Adventurers and goblin hunters** (`worker_loot.py`):
  - They replay recorded world-chest and loot-goblin packets of the running build, in the packets' region.
  - Replays go through `afk.py worker-replay`, with experience off.
  - Chest keys come from the camp's key rack.
- **The jeweler** (`worker_jeweler.py`, plugin `0.8.0-camp`):
  - `afk worker recipes` reads the Crafting Cube's jewel recipes.
  - `worker deliver` reads a recipe again and makes only its jewel or gem.
  - Materials come from the camp's stock. Miners fill it with their Gem Sense share, which the plugin rolls but does not make (`route_prospect`).
- **Keys and materials from the Vault** (`vault_take.py`):
  - They come through Item Editor 2.16.1's `POST /api/vault/afk-take`, with one receipt per request in `workers.json` (`vault_takes`).
  - Anything but a clear "done" is settled by cancelling the request, so a lost answer neither doubles nor loses keys.
  - AFK FARM never writes the Vault database.
- **Tests on the 0.8 branch** (2026-09-25):
  - 246 Python tests, including a bridge test against the real Item Editor handler, which is skipped without a sibling 2.16.1 checkout;
  - 42 Node UI tests (panel 28, map 11, share card 3);
  - the C++ smokes, including `worker_smoke`.
- **Live check:** the 0.8 engine has not been run against the game yet.

## The town (0.9, in review)

Not released. It is in falorfrozen-cmd/HS-AFK-Expedition#3, stacked on #2. The rules are in the module's `docs/DESIGN.md`, the API in `docs/UI_CONTRACT.md` ("0.9: the town"), the player text in `docs/PLAYER_GUIDE.md`, and the UI brief in `docs/CHATGPT_HANDOVER.md`.

- **Town defense** (`defense.py`, `battle.py`, `bestiary.py`, `fortifications.py`, `town.py`):
  - Sieges of 15 minutes to 8 hours, a wave every 5 minutes, at levels 1-60.
  - The defenders are walls, a keep, eight kinds of towers (levels 1-10, a specialisation at 5) and up to three stationed heroes. Each hero fights with its measured pace from a calibration in that region.
  - The attackers are drawn from the region's recorded kill packets: the player's own monsters, with their real rank, speed, range, immunities and affixes. The monsters that special content spawned come as special waves (the Abyss chest's pack, the Unholy Siege's, a Chaos Pillar's).
  - Each kill is paid by replaying that packet:
    - a hero's kills through its own claim (`mode: 'defense'`, with XP);
    - every other kill as the town's share, collected like a worker's haul with no XP.
  - The fight, the tiers above Legion (Ascended, Primordial, Warlord), the affix effects and events are AFK FARM's layer.
- **Economy** (`goods.py`, `economy.py`, `trade.py`, `merchants.py`, `town_panel.py`):
  - The town has its own coffer. A deposit goes through the purchase path; a payout uses the new `afk worker credit` (plugin 0.9.0-town), with one receipt per request. A refused payout after which the gold rose anyway stays out of the coffer as `review`.
  - The stock holds 226 kinds of stackable goods. Goods come in through the Item Editor's take and go out only as stacks the game makes (`worker_town_*` deliveries; `TownGoods.hpp` is generated from `goods.py`).
  - Travelling merchants and trade wagons to ten towns price with a stock model: every unit moves the price, a round trip always loses, and prices recover by the hour.
- **Tests** (2026-09-25): 387 Python tests, including the panel integration (`test_town.py`, 34), the town modules' unit tests (94) and the goods header; 42 Node UI tests; the C++ smokes, with 36 worker checks covering the credit decisions and the goods list. An independent review's findings were fixed with regression tests.
- **The watch** (`defense_watch`): the town can keep itself under siege with its towers alone, one siege after another. It catches up after the panel was closed (at most a day back) and pauses while 8 town shares wait or after the keep falls.
- **Live check:** not run in the game yet. Still to verify: `worker credit`; town deliveries of types 12, 13 and 15; a siege's hero and town claims.

## Related Guides
- [hero-siege-item-editor](../hero-siege-item-editor/instructions.md): Infinite Vault, AFK transfers, DISMANTLE, camp takes
- [hs-game-sdk](../hs-game-sdk/instructions.md): reward scope, reward stats, native routine names
- [ForgePact](../ForgePact/instructions.md): shared reward scope
- [Shared Documentation Index](../README.md)
