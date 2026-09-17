# Hero Siege Offline Toolkit

Ten offline/single-player tools for Hero Siege, created by **Falor**, and one
application that installs and runs all of them.

Simulate Cube crafting, edit items and characters, adjust offline gameplay,
track your runs, or launch the game offline.

> These tools are intended for offline / single-player use only. Back up your
> saves before editing them.

---

## Get the Toolkit Hub

**[Download the latest release →](https://github.com/falorfrozen-cmd/hero-siege-offline-toolkit/releases/latest)**

One window that installs, launches and updates every tool below. Getting the
toolkit no longer means visiting ten GitHub pages, downloading ten
differently-named archives, and having no way to hear that any of them shipped a
fix.

- **Install and launch** any tool from a single library view.
- **Know when something is out of date.** One request fetches a signed catalog,
  and the hub compares it against what you have installed. Nothing is downloaded
  or installed by that check alone.
- **Every download is verified.** None of these tools is code-signed, so instead
  the hub pins a SHA-256 for every file inside a catalog signed with a key built
  into the application. A release file swapped after the catalog was made fails
  to install rather than installing quietly.
- **Nothing of yours is moved.** The hub manages program files only. Your saves,
  settings and backups stay exactly where each tool puts them, and every tool
  behaves identically whether you start it from the hub or by hand.
- **Work offline** is one switch that stops every outbound request, including the
  check on launch. On first run the hub tells you what it would contact, before
  it contacts anything.

It knows which tools need Administrator and which need the game closed, and says
so on the card rather than letting you find out by failing.

The library includes tool search (Ctrl+K), category and installation filters,
grid/list views, and full quick-launch cards with star and action controls. Its graphite and
copper interface uses a distinct original icon for every tool.

### What you need

- **Windows 10 or 11**, 64-bit. The hub itself is Windows-only; the Steam Deck
  save editor it can open is a browser page and works anywhere.
- The installer is per-user and needs no Administrator. The three tools that
  edit game memory do, and the hub asks Windows for it per launch rather than
  running elevated itself.
- **Windows will warn you about the download.** There is no code-signing
  certificate for this project, or for any of the ten tools. Choose *More info →
  Run anyway*. The hash pinning described above is what stands in for a
  certificate, and you can see each pinned hash in the hub's detail view for a
  tool.

---

## The tools

The hub installs and updates all of these for you. The links are here for
browsing the source, reading a project's own documentation, or downloading a
tool on its own.

| Tool | What it does | Download | Developer guide |
| --- | --- | --- | --- |
| [HSCraftSim](https://github.com/falorfrozen-cmd/HSCraftSim) | Simulate Cube crafting, explore recipes and probabilities, and compare item stats before and after each craft. Windows and browser. | [Release](https://github.com/falorfrozen-cmd/HSCraftSim/releases/latest) | [Guide](docs/submodules/HSCraftSim/instructions.md) |
| [ForgePact](https://github.com/falorfrozen-cmd/ForgePact) | Control offline gameplay modifiers: monster density, special spawns, drop rates, combat stats and map reveal. | [Release](https://github.com/falorfrozen-cmd/ForgePact/releases/latest) | [Guide](docs/submodules/ForgePact/instructions.md) |
| [Hero Siege Item Editor](https://github.com/falorfrozen-cmd/hero-siege-item-editor) | Browse, add, equip and customize items in local saves, including set pieces, runewords, relics and stash inventories. | [Release](https://github.com/falorfrozen-cmd/hero-siege-item-editor/releases/latest) | [Guide](docs/submodules/hero-siege-item-editor/instructions.md) |
| [HS Offline Tracker](https://github.com/falorfrozen-cmd/HS-Offline-Tracker) | Keep a loot journal, view session statistics and run history, and set drop alerts with a compact overlay. | [Release](https://github.com/falorfrozen-cmd/HS-Offline-Tracker/releases/latest) | [Guide](docs/submodules/HS-Offline-Tracker/instructions.md) |
| [HS Offline Stat Forge](https://github.com/falorfrozen-cmd/hs-stat-forge) | Adjust runtime character stats — Magic Find, movement speed, skills, experience, combat bonuses — plus monster density. | [Release](https://github.com/falorfrozen-cmd/hs-stat-forge/releases/latest) | [Guide](docs/submodules/hs-stat-forge/instructions.md) |
| [HS Offline Launcher](https://github.com/falorfrozen-cmd/HS-Offline-Launcher) | Find your Steam installation and start Hero Siege directly for offline play. | [Release](https://github.com/falorfrozen-cmd/HS-Offline-Launcher/releases/latest) | [Guide](docs/submodules/HS-Offline-Launcher/instructions.md) |
| [HS Save Editor](https://github.com/falorfrozen-cmd/HSSaveEditor) | Edit character save values such as level, gold and professions. | [Release](https://github.com/falorfrozen-cmd/HSSaveEditor/releases/latest) | [Guide](docs/submodules/HSSaveEditor/instructions.md) |
| [HS Value Scanner](https://github.com/falorfrozen-cmd/HS-ValueEditor) | Find and modify in-game values such as Magic Find, movement speed and stacked item counts. | [Release](https://github.com/falorfrozen-cmd/HS-ValueEditor/releases/latest) | [Guide](docs/submodules/HS-ValueEditor/instructions.md) |
| [HS Offline Loot Forge](https://github.com/falorfrozen-cmd/Hs-Offline-Loot-Forge) | Assist with target farming through offline runtime loot adjustments. | [Release](https://github.com/falorfrozen-cmd/Hs-Offline-Loot-Forge/releases/latest) | [Guide](docs/submodules/Hs-Offline-Loot-Forge/instructions.md) |
| [HS Steam Deck Save Editor](https://github.com/falorfrozen-cmd/HSSaveEditor-SteamDeck-) | Edit saves through a browser-based interface built for Steam Deck. | [Release](https://github.com/falorfrozen-cmd/HSSaveEditor-SteamDeck-/releases/latest) | [Guide](docs/submodules/HSSaveEditor-SteamDeck-/instructions.md) |

Each tool is maintained and released in its own repository, and the hub does not
change how any of them work. Supported game builds are documented by each
project.

---

## Notes

- [Automatic submodule pointer updates](docs/submodules/README.md#automated-submodule-pointer-updates): validated bot PRs merge automatically; feature PRs remain for manual review.
- Offline / single-player use only
- Back up your save files before editing
- Use at your own risk
- Not affiliated with Hero Siege or Panic Art Studios

---

# Development

Everything below is for working on the toolkit rather than using it.

## The hub

```bash
cd hub
npm install
npm start     # run it in development
npm test      # the Rust engine's tests
npm run release   # build the installer
```

Needs Node 20.19+ and Rust 1.88+. `npm start` opens the app against a Vite dev
server; `npm run dev` alone serves the frontend in a plain browser, where it
draws the real library from the committed catalog with everything stubbed as not
installed — so the interface is workable without building the Rust side.

A debug build also starts an MCP bridge on `127.0.0.1:9223`, so the running
window can be clicked and screenshotted from a terminal rather than by hand:

```bash
npx -y -p @hypothesi/tauri-mcp-cli tauri-mcp driver-session start --port 9223
npx -y -p @hypothesi/tauri-mcp-cli tauri-mcp webview-screenshot --window-id hub --file-path shot.png --format png
```

It is behind `#[cfg(debug_assertions)]` and a release build never starts one —
it can invoke any command the app has. The window label is `hub`, not `main`;
[`docs/hub/design.md`](docs/hub/design.md) has the rest of the sharp edges.

| | |
| --- | --- |
| Source, and how to work on it | [`hub/`](hub) · [`hub/instructions.md`](hub/instructions.md) |
| How it works, and what the manual testing found | [`docs/hub/design.md`](docs/hub/design.md) |
| Catalog format | [`docs/hub/catalog-schema.md`](docs/hub/catalog-schema.md) |
| Why submodules and not a monorepo | [`docs/adr/0001-repo-topology.md`](docs/adr/0001-repo-topology.md) |
| Per-tool developer guides | [`docs/submodules/README.md`](docs/submodules/README.md) |

A release is cut from **Actions → Hub tag → Run workflow**, typing the tag it
should go out as (`hub-v1.0.2`). That checks the tag, moves the version in all
six places it lives, tags it and starts the build; what comes out is a draft,
and publishing it is the one step left to a person.

A build points at the repository that published it: `HUB_REPO` in
[`hub/src-tauri/src/catalog.rs`](hub/src-tauri/src/catalog.rs) decides where the
catalog, the hub's own updates and the documentation links come from, and
`hub-release.yml` sets it from the repository running the workflow. To build one
for a fork, `HUB_REPO=owner/hero-siege-offline-toolkit npm run release`.

## The catalog

[`catalog/catalog.json`](catalog/catalog.json) is what the hub reads: one entry
per tool with a pinned SHA-256, how to install it, how to launch it, and what it
requires. It is generated by
[`tools/build_catalog.py`](tools/build_catalog.py) from the hand-written
per-tool rules in [`catalog/sources.toml`](catalog/sources.toml), signed with
minisign, and published to the `catalog` release tag.

```bash
py -3 tools/build_catalog.py          # rebuild from the live releases
py -3 -m unittest discover -s tests   # the generator's tests
```

CI rebuilds it when a tool publishes a release and opens a pull request;
merging that publishes it. See
[`docs/hub/catalog-schema.md`](docs/hub/catalog-schema.md).

## Working with submodules

The ten tools are Git submodules. Clone with them:

```bash
git clone --recurse-submodules https://github.com/falorfrozen-cmd/hero-siege-offline-toolkit.git
```

Or, in an existing clone:

```bash
git submodule update --init --recursive     # fetch them
git submodule update --remote --recursive   # move them to their latest
```

The hub does not need them. It consumes released artifacts, so the submodules
matter only for working on a tool's source — and for the hub's developer mode,
which can run a checked-out tool from source instead of an installed copy.

To change a tool, commit inside its own repository first, then record the moved
pointer here:

```bash
cd <submodule>
git checkout main        # submodules default to a detached HEAD
git commit -m "..." && git push
cd ..
git add <submodule> && git commit -m "Update submodule reference"
```

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

## Context7 MCP

For AI-assisted development — retrieving `YYToolkit` API documentation across
submodules such as `ForgePact` and `HS-Offline-Tracker` — add the
[Context7 MCP Server](https://github.com/context7/context7) to your MCP client
configuration:

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

## Design notes

Why something went the way it did is recorded next to the thing it describes —
[`docs/hub/design.md`](docs/hub/design.md) for the hub,
[`docs/adr/`](docs/adr) for decisions that outlived the discussion,
[`docs/RUNTIME_DATA_MODELS.md`](docs/RUNTIME_DATA_MODELS.md) for the runtime
item and stat structs, and each submodule's `instructions.md` for the tool
itself.

Planning documents are deliberately **not** kept here; `*-plan.md` is in
`.gitignore`. A plan says what someone intended to build and goes out of date
the moment it is built, and a repository holding both leaves a reader two
documents with no way to tell which one describes the software they are running.
