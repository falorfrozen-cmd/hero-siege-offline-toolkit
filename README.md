# Hero Siege Offline Toolkit

Eleven offline/single-player tools for Hero Siege, created by **Falor**, and one
application that installs and runs all of them.

Simulate Cube crafting, edit items and characters, adjust offline gameplay,
track your runs, browse the Codex reference archive, or launch the game offline.

> These tools are intended for offline / single-player use only. Back up your
> saves before editing them.

---

## Get the Toolkit Hub

**[Download the latest release →](https://github.com/falorfrozen-cmd/hero-siege-offline-toolkit/releases/latest)**

One window that installs, launches and updates every tool below. Getting the
toolkit no longer means visiting separate GitHub pages, downloading
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
copper interface uses original tool icons, with a standard fallback for newly
added catalog entries.

### What you need

- **Windows 10 or 11**, 64-bit. The hub itself is Windows-only; the Steam Deck
  save editor it can open is a browser page and works anywhere.
- A release carries two installers; use one, not both. The `-setup.exe` one
  installs for your user only and needs no Administrator. The `.msi` one
  installs for every user of the PC, so Windows asks for Administrator when you
  install it and again each time the hub updates itself. If you decline that
  prompt during an update, the hub stays closed and on the old version; start
  it again from the Start menu. The `.msi` is there because some antivirus
  programs flag a helper file inside the `-setup.exe` installer.
- If the hub is already installed, let it update itself rather than
  downloading the other installer over it. To change from one installer to the
  other, uninstall the hub first; that leaves your tools and settings alone.
- The three tools that edit game memory need Administrator, and the hub asks
  Windows for it per launch rather than running elevated itself.
- **Windows will warn you about the download.** There is no code-signing
  certificate for this project or its tools. Choose *More info →
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
| [Hero Siege Codex](https://github.com/falorfrozen-cmd/hero-siege-codex) | Explore items, classes, creatures, and the world in an offline reference archive. | [Release](https://github.com/falorfrozen-cmd/hero-siege-codex/releases/latest) | [Guide](docs/tools/hero-siege-codex.md) |

Each tool is maintained and released in its own repository, and the hub does not
change how any of them work. Supported game builds are documented by each
project. Codex is a release-only integration and has no source submodule.
Existing Toolkit 1.0.5 users can refresh the library while online to see it
under All or search; a Toolkit application upgrade is not required.

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
npm run release   # build both installers (setup.exe and .msi)
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

A second, unrelated MCP server, `hs-drive`, sits beside it in `.mcp.json`. It
is a local stdio server in `tools/hs_drive_mcp/` that reports whether Hero
Siege is running, backs up or restores the save directory, launches the
ForgePact-modded game through ForgePact's own launcher engine, sends ForgePact
commands over `bp_ipc` and reads the plugin's reply back, screenshots the game
window, injects keyboard and mouse input into that window (`hs_input`, by
either of two routes), clicks from the title screen into a loaded character
(`hs_select_character`, proving the load through the plugin rather than a
screenshot), and closes the game gracefully — every tool refusing
with a named reason rather than guessing, the save tools refusing unless the
game is provably closed, and the injection refusing unless the target window
belongs to a running game process. A machine-wide game lease
(`hs_lease_acquire`, `hs_lease_status`, `hs_lease_release`) keeps two
sessions from driving the one game at once: while another live hs-drive
process holds it, every tool that drives the game or overwrites saves
refuses with `lease_held`, naming the holder. See
[`docs/tools/hs-drive-mcp.md`](docs/tools/hs-drive-mcp.md). Nothing about it
ships to a player.

The `ghidra` MCP server (`tools/ghidra_mcp.py`) puts the local Ghidra project
behind tool calls: search functions, decompile by address, follow callers and
xrefs, with no headless run per question. It serves a copy of the research
project from one shared headless server on loopback, and what it decompiles
stays local. See [`docs/tools/ghidra-mcp.md`](docs/tools/ghidra-mcp.md).

The `x64dbg` MCP server (`tools/x64dbg_mcp.py`) attaches a headless debugger
to the running, modded game during a live session and answers "does this
function fire, with what arguments, how often" through non-breaking hardware
logging breakpoints, with no research build and no relaunch. Only the
`live-operator` agent carries its tools, it works under the hs-drive game
lease, and it detaches before the game is closed. Its one-time setup downloads
and builds a pinned x64dbg and plugin outside the repository. See
[`docs/tools/x64dbg-mcp.md`](docs/tools/x64dbg-mcp.md). Nothing about it ships
to a player.

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
* **Python (`hs-game-sdk/python`)**: `hs_game_sdk` package with `GameObject`, `GameScript`, `GameRoom`, `StatId`, `ItemDefinitionStruct`, `ItemStatStruct`, and the item-class `ItemType` enum.
* **C++ Headers (`hs-game-sdk/cpp/include/hs_game_sdk`)**: Strongly-typed enums, constexpr script names, and YYToolkit wrappers (`hs_game_sdk.hpp`, `yytk_helpers.hpp`), plus `HeroSiege::Items::ItemType` and its enumerable `kItemTypes` (`item_type.hpp`).
* **TypeScript (`hs-game-sdk/ts`)**: `@hero-siege/sdk` with typed object ID mappings and stat constants for web modules, plus `ItemType` and `ITEM_TYPES`.

`ItemType` is the value an item instance carries in its `itemType` field (e.g. `ItemType.MATERIAL == 14`). The three bindings are hand-written and `tests/test_item_type_parity.py` asserts they match value for value; see [`docs/submodules/hs-game-sdk/instructions.md`](docs/submodules/hs-game-sdk/instructions.md#item-class-itemtype) for each value's source.

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
`curated/stash_containers.json` (ForgePact issue #14's stash and Crafting Cube container names,
and ForgePact #68's bag-to-stash move routines)
is data-only and is not regenerated by that script - it has no generator and no bindings yet,
checked against the SDK and `docs/RUNTIME_DATA_MODELS.md` § 17 by `tests/test_curated_stash_containers.py`.

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

`tools/stash_tab_counts.py` counts what the shared stash's two special tabs —
Socketable (`socket_tab`) and Materials (`material_tab`) — hold in the save,
summed per (item class, base id). It decodes `hs2saves\stash.hss` read-only with
`hero-siege-item-editor`'s own decoder (so that submodule must be initialized)
and never writes; run it with the game closed, since the file is the last saved
state. It is the save-side cross-check for ForgePact issue #14's in-game reader
(`craftprobe node`). See [its page](docs/tools/stash-tab-counts.md):

```powershell
py -3 tools/stash_tab_counts.py            # or --path <a backup's stash.hss>, --json
```

`tools/save_item_keys.py` lists every item key (`0-0-<n>-<class>`) in one or
more save files, grouped by the container it is saved under: the shared
stash's tabs in `stash.hss`, the bag's tabs in `inventory_order_<slot>.hss`,
and the personal stash and equipped items inside `herosiege<slot>.hss`. It uses
the same decoder, read-only, with the game closed, and is how ForgePact issue
#68's live sessions show a moved item is saved in the stash, not in the bag,
and only once. See [its page](docs/tools/save-item-keys.md):

```powershell
py -3 tools/save_item_keys.py <stash.hss> <inventory_order_13.hss> <herosiege13.hss> --key <0-0-n-class>
```

`tools/button_label_check.py` measures, on a game screenshot, whether a
button's label is drawn centred inside its box, against a button the game
draws itself as the reference. Which member, if any, says where the game draws
a node's label is not established, so ForgePact issue #131's live sessions
judge the label from the picture. See [its page](docs/tools/button-label-check.md):

```powershell
py -3 tools/button_label_check.py <png> --gui 2560x1440 --box <l,t,r,b> --ref <l,t,r,b>
```

## Modified YYToolkit

ForgePact and HS Offline Tracker load their plugins through a modified
[YYToolkit](https://github.com/AurieFramework/YYToolkit) (AGPL-3.0). Its source
of truth is [`third_party/yytoolkit/`](third_party/yytoolkit): one pinned
upstream commit, a patch series in which every patch states why it exists, what
backs it and how it fails safe, and the AGPL notice. No binary is committed;
[`tools/build_yytoolkit.py`](tools/build_yytoolkit.py) builds one from a local
clone of upstream, outside the repository:

```powershell
py -3 tools/build_yytoolkit.py all --upstream C:\src\YYToolkit
```

That exports the pinned commit, applies the series, builds `Release|x64`, runs
the host tests and checks that every log line the patches declare is in the
DLL. It never launches the game. The series has been built, host-tested and
**launched twice against the game** (2026-09-19: first YYToolkit alone, then
a second, idle session with ForgePact's plugin and the HS-Offline-Tracker
producer both loaded) — the startup fault did not reproduce in either
session and lag was not observed in the first; the second confirmed both
plugins initialize and the plugin-to-runner interface works, but gameplay
with mods active and the error-report path with a plugin loaded are still
unexercised. Both submodules' pull requests have merged and their pins now
point at this series, but neither has cut a release carrying it, so players
still receive the earlier DLL until one does —
see the directory's [README](third_party/yytoolkit/README.md) for the full
launch-gate record,
[ADR 0002](docs/adr/0002-modified-yytoolkit-is-a-patch-series-in-the-hub.md)
for why it is a patch series, and
[`docs/agents/yytoolkit-provenance.md`](docs/agents/yytoolkit-provenance.md)
for what went wrong with the binary it replaces.

## Modified Aurie

ForgePact also ships a modified `AurieCore.dll`, from the
[Aurie Framework](https://github.com/AurieFramework/Aurie) (AGPL-3.0). Its
source of truth is [`third_party/aurie/`](third_party/aurie), kept under the
same rules as the YYToolkit series: one pinned upstream commit (Aurie v2.0.2),
a patch series whose every patch carries `Why` / `Evidence` / `Fails-safe` /
`Log-markers` / `Upstream-status`, upstream's licence and the AGPL notice. No
binary is committed; [`tools/build_aurie.py`](tools/build_aurie.py), a second
profile of the same build tool, builds one:

```powershell
py -3 tools/build_aurie.py all --upstream C:\src\Aurie
```

The series changes one thing about the framework: when `MmCreateHook` freezes
the game to write a hook, it walks only the game process's own threads instead
of taking two thread snapshots of the whole system, which ForgePact #151
measured at about 69 ms per hook. Hooks attach exactly as before. The build
travels as the hub library release `aurie-v2.0.2-hs.1` (`--latest=false`),
which ForgePact's toolchain pin names; HS-Offline-Tracker ships the same
build from its next release (0.1.4, falorfrozen-cmd/HS-Offline-Tracker#14).
The directory's
[README](third_party/aurie/README.md) holds the patch table and the launch
gate, and [ADR 0006](docs/adr/0006-modified-auriecore-is-a-patch-series-in-the-hub.md)
says why the fix is a patch series here.

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
item and stat structs, the patch headers in
[`third_party/yytoolkit/patches/`](third_party/yytoolkit/patches) for each
change to YYToolkit, and each submodule's `instructions.md` for the tool
itself.

Planning documents are deliberately **not** kept here; `*-plan.md` is in
`.gitignore`. A plan says what someone intended to build and goes out of date
the moment it is built, and a repository holding both leaves a reader two
documents with no way to tell which one describes the software they are running.
