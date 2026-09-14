# Hero Siege Offline Toolkit

A collection of offline/single-player tools for Hero Siege, created by **Falor**.

Explore Cube crafting, edit items and characters, customize offline gameplay,
track your runs, or launch the game offline. This repository is the central hub
for all tools and the shared Game SDK below.

> These tools are intended for offline / single-player use only.

---

## Working with Submodules

This repository uses Git submodules to link all individual tool repositories into one unified workspace.

### Cloning with Submodules

To clone this repository along with all submodules in a single step:

```bash
git clone --recurse-submodules https://github.com/falorfrozen-cmd/hero-siege-offline-toolkit.git
```

### Initializing and Pulling Submodules

If you cloned the repository without `--recurse-submodules`, initialize and pull all submodules with:

```bash
git submodule update --init --recursive
```

### Updating Submodules

To pull the latest changes for all submodules from their respective remote repositories:

```bash
git submodule update --remote --recursive
```

### Working Inside a Submodule

1. Navigate into the submodule directory:
   ```bash
   cd <submodule-folder>
   ```
2. Checkout your working branch before editing (submodules often default to a detached HEAD):
   ```bash
   git checkout main
   ```
3. Commit and push changes directly within the submodule:
   ```bash
   git commit -m "Commit message"
   git push origin main
   ```
4. Return to the root project to commit the updated submodule commit pointer:
   ```bash
   cd ..
   git add <submodule-folder>
   git commit -m "Update submodule reference"
   ```

---

## Tools

Select a tool name for its repository and setup instructions, or **Download** to
open its latest release and available packages. Developer instructions and architectural
guides for submodules are indexed in [Submodule Development Guides](docs/submodules/README.md).

| Tool | What it does | Latest release | Developer Guide |
| --- | --- | --- | --- |
| [HSCraftSim](https://github.com/falorfrozen-cmd/HSCraftSim) | Simulate Cube crafting, explore recipes and probabilities, and compare item stats before and after each craft. Available for Windows and the browser. | [Download](https://github.com/falorfrozen-cmd/HSCraftSim/releases/latest) | [Guide](docs/submodules/HSCraftSim/instructions.md) |
| [ForgePact](https://github.com/falorfrozen-cmd/ForgePact) | Control offline gameplay modifiers, including monster density, special spawns, drop rates, combat stats and map reveal. | [Download](https://github.com/falorfrozen-cmd/ForgePact/releases/latest) | [Guide](docs/submodules/ForgePact/instructions.md) |
| [Hero Siege Item Editor](https://github.com/falorfrozen-cmd/hero-siege-item-editor) | Browse, add, equip and customize items in local saves, including set pieces, runewords, relics and stash inventories. | [Download](https://github.com/falorfrozen-cmd/hero-siege-item-editor/releases/latest) | [Guide](docs/submodules/hero-siege-item-editor/instructions.md) |
| [HS Offline Tracker](https://github.com/falorfrozen-cmd/HS-Offline-Tracker) | Keep a loot journal, view session statistics and run history, and use configurable drop alerts with a compact overlay. See the project instructions for game-link setup. | [Download](https://github.com/falorfrozen-cmd/HS-Offline-Tracker/releases/latest) | [Guide](docs/submodules/HS-Offline-Tracker/instructions.md) |
| [HS Offline Stat Forge](https://github.com/falorfrozen-cmd/hs-stat-forge) | Adjust runtime character stats such as Magic Find, movement speed, skills, experience and combat bonuses, plus monster density. | [Download](https://github.com/falorfrozen-cmd/hs-stat-forge/releases/latest) | [Guide](docs/submodules/hs-stat-forge/instructions.md) |
| [HS Offline Launcher](https://github.com/falorfrozen-cmd/HS-Offline-Launcher) | Find the Steam installation and launch Hero Siege directly for offline play on Windows. | [Download](https://github.com/falorfrozen-cmd/HS-Offline-Launcher/releases/latest) | [Guide](docs/submodules/HS-Offline-Launcher/instructions.md) |
| [HS Save Editor](https://github.com/falorfrozen-cmd/HSSaveEditor) | Edit character-related save values such as level, gold and professions. | [Download](https://github.com/falorfrozen-cmd/HSSaveEditor/releases/latest) | [Guide](docs/submodules/HSSaveEditor/instructions.md) |
| [HS Value Scanner](https://github.com/falorfrozen-cmd/HS-ValueEditor) | Find and modify in-game values such as Magic Find, movement speed and stacked item counts. | [Download](https://github.com/falorfrozen-cmd/HS-ValueEditor/releases/latest) | [Guide](docs/submodules/HS-ValueEditor/instructions.md) |
| [HS Offline Loot Forge](https://github.com/falorfrozen-cmd/Hs-Offline-Loot-Forge) | Assist with target farming through offline runtime loot adjustments. | [Download](https://github.com/falorfrozen-cmd/Hs-Offline-Loot-Forge/releases/latest) | [Guide](docs/submodules/Hs-Offline-Loot-Forge/instructions.md) |
| [HS Steam Deck Save Editor](https://github.com/falorfrozen-cmd/HSSaveEditor-SteamDeck-) | Edit Hero Siege saves through a browser-based interface designed for Steam Deck users. | [Download](https://github.com/falorfrozen-cmd/HSSaveEditor-SteamDeck-/releases/latest) | [Guide](docs/submodules/HSSaveEditor-SteamDeck-/instructions.md) |
| **HS Game SDK** (`hs-game-sdk/`) | Centralized multi-language SDK (C++, Python, TypeScript) and symbol engine extracted from `Hero_Siege.exe` & `data.win`. | Integrated | [Guide](docs/submodules/hs-game-sdk/instructions.md) |

Each tool is maintained and released in its own repository. Download links follow
the latest published release automatically; installation steps and supported game
builds are documented by each project.

---

## HS Game SDK (`hs-game-sdk`)

`hs-game-sdk` is an integral component of the toolkit providing GameMaker objects (6,016), scripts (6,254), assets, stat IDs, and runtime struct models directly to all toolkit submodules.

### Structure & Modules
* **Python (`hs-game-sdk/python`)**: `hs_game_sdk` package with `GameObject`, `GameScript`, `GameRoom`, `StatId`, `ItemDefinitionStruct`, `ItemStatStruct`.
* **C++ Headers (`hs-game-sdk/cpp/include/hs_game_sdk`)**: Strongly-typed enums, constexpr script names, and YYToolkit wrappers (`hs_game_sdk.hpp`, `yytk_helpers.hpp`).
* **TypeScript (`hs-game-sdk/ts`)**: `@hero-siege/sdk` with typed object ID mappings and stat constants for web modules.

### Extraction & Re-generation
Extract symbols and generate SDK bindings from a local Hero Siege installation:
```powershell
py -3 tools/extract_and_generate_sdk.py --game-bin "C:\Program Files (x86)\Steam\steamapps\common\HeroSiege\bin"
```

`hs-game-sdk/curated/` holds a second, smaller kind of data alongside the extracted symbols:
hand-verified game knowledge (item/effect names and text that no mechanical extractor can
derive) meant to be shared across submodules instead of copied into each one. Unlike
`hs-game-sdk/data/`, `curated/` is tracked in git. Regenerate its bindings after editing a
`curated/*.json` file:
```powershell
py -3 tools/generate_satanic_zone_sdk.py
```

---

## Diagnostics

`tools/freeze_probe.ps1` samples a running game process from outside it — useful
when a submodule's own logging can't tell whether a freeze is in that submodule,
the game, or the machine (display driver, anti-virus, paging). It brackets a
freeze precisely with `Process.Responding`, and records disk I/O, free RAM, and
machine-wide CPU busy/idle across it, printing a verdict at the end:

```powershell
powershell -ExecutionPolicy Bypass -File tools/freeze_probe.ps1
```

Then launch the game and reproduce the freeze; Ctrl+C when done. See
[ForgePact's instructions](docs/submodules/ForgePact/instructions.md) for a
worked example (Known Limitations, stall watchdog section).

---

## Context7 MCP Setup

For AI-assisted development (e.g., retrieving `YYToolkit` API documentation and references across submodules like `ForgePact` and `HS-Offline-Tracker`), you can integrate the [Context7 MCP Server](https://github.com/context7/context7).

### Adding to MCP Configuration

Add Context7 to your MCP client configuration (such as Claude Desktop, Cursor, or IDE settings):

```json
{
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@context7/mcp-server"]
    }
  }
}
```

For more details on Context7 indexing and query capabilities, consult the [Context7 Documentation](https://github.com/context7/context7).

## Design Notes & Future Work

Longer-form notes that are deliberately *not* on the roadmap — kept so the reasoning
isn't re-derived from scratch later. Nothing here is implemented.

- [Steam ownership gating & offline integrity](docs/ownership-and-offline-integrity-plan.md)
  — why Easy Anti-Cheat and exe-patching mods can never coexist, why EAC was never the
  anti-piracy layer in the first place, and what a real Steam ownership check in
  `HS-Offline-Launcher` would look like if the toolkit ever wanted one.

- [Toolkit Hub: one app that installs, launches and updates every tool](docs/toolkit-hub-plan.md)
  — why the hub owns windows and processes rather than tabs (five of the tools refuse
  to be framed), why the ten repositories stay as submodules with the SDK coupling fixed
  directly instead, and the signed catalog that pins a SHA-256 per release asset.

## Notes

- [Automatic submodule pointer updates](docs/submodules/README.md#automated-submodule-pointer-updates): validated bot PRs merge automatically; feature PRs remain for manual review.

- Offline / single-player use only
- Backup your save files before editing
- Use at your own risk
- Not affiliated with Hero Siege or Panic Art Studios
