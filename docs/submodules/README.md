# Submodule Development Guides Index

This directory serves as the centralized repository for development, architecture, testing, and operational guides across all tool submodules integrated into the **Hero Siege Offline Toolkit**.

---

## Submodule Inventory

| Module Name | Submodule Path | Development Guide | Status | Description |
| --- | --- | --- | --- | --- |
| **ForgePact** | `ForgePact/` | [ForgePact Instructions](ForgePact/instructions.md) | Ready | Offline gameplay modifier panel and C++20 runtime hook plugin (`BloodPactPlugin`). |
| **HS Offline Launcher** | `HS-Offline-Launcher/` | [HS-Offline-Launcher Instructions](HS-Offline-Launcher/instructions.md) | Ready | Steam installation discovery and offline game launcher. |
| **HS Offline Tracker** | `HS-Offline-Tracker/` | [HS-Offline-Tracker Instructions](HS-Offline-Tracker/instructions.md) | Ready | Session telemetry journal, rarity drop alert engine, and compact overlay with Aurie producer. |
| **HS Value Scanner** | `HS-ValueEditor/` | [HS-ValueEditor Instructions](HS-ValueEditor/instructions.md) | Ready | Memory value scanner and offline runtime value editor. |
| **HSCraftSim** | `HSCraftSim/` | [HSCraftSim Instructions](HSCraftSim/instructions.md) | Ready | Cube crafting simulator, recipe database, and desktop/web simulation workbench. |
| **HS Save Editor** | `HSSaveEditor/` | [HSSaveEditor Instructions](HSSaveEditor/instructions.md) | Ready | Character save editor for offline saves. |
| **HS Steam Deck Save Editor** | `HSSaveEditor-SteamDeck-/` | [HSSaveEditor-SteamDeck- Instructions](HSSaveEditor-SteamDeck-/instructions.md) | Ready | Browser-based save editor tailored for Steam Deck handheld users. |
| **HS Offline Loot Forge** | `Hs-Offline-Loot-Forge/` | [Hs-Offline-Loot-Forge Instructions](Hs-Offline-Loot-Forge/instructions.md) | Ready | Runtime loot table adjustments and targeted farming assistant. |
| **Hero Siege Item Editor** | `hero-siege-item-editor/` | [hero-siege-item-editor Instructions](hero-siege-item-editor/instructions.md) | Ready | Item creator, stash editor, and inventory customizer. |
| **HS Offline Stat Forge** | `hs-stat-forge/` | [hs-stat-forge Instructions](hs-stat-forge/instructions.md) | Ready | Runtime character stat tuner and monster density modifier. |
| **HS Game SDK** | `hs-game-sdk/` | [HS Game SDK Instructions](hs-game-sdk/instructions.md) | Ready | Centralized cross-language SDK and metadata library for GameMaker objects, scripts, assets, and runtime models. |
| **Runtime Data Models** | `docs/` | [Runtime Data Models & Cheat-Sheet](../RUNTIME_DATA_MODELS.md) | Ready | Reverse-engineered Season 10 memory models, player instance structs, equipment slots, and drop tables. |

---

## Documentation Methodology & Standards

Submodule development instructions adhere to the following authoring principles:

1. **Evidence-Backed Verification:** Every architecture claim, dependency version, and file path must be verified directly against repository source files, configuration manifests, build scripts, or unit test declarations. Unverified claims must be explicitly marked.
2. **Deterministic Command Metadata:** Commands in the reference tables specify exact working directories, shells, prerequisites, side effects, and verification statuses (`Verified`, `Inspected`, or `Blocked`).
3. **Safety & Fail-Closed Operations:** Guides document offline-only constraints, anti-cheat isolation (EAC disabled), non-destructive save handling, and atomic backup/restoration mechanisms.
4. **Modified Upstream Provenance:** Modifications to third-party or upstream dependencies (such as Aurie or YYToolkit) must document exact change locations, compilation flags, and AGPL-3.0 compliance notices.
5. **No Decompiled Game Code:** Research notes document measured runtime *behavior* (what a function does, observed crash signatures, memory layout) and reference game objects/scripts by the names and indices in `hs-game-sdk` — never by pasting decompiled or disassembled Hero Siege source. See "Legal: No Decompiled Code in Any Origin" in the root [`agents.md`](../../agents.md) for the full rule and what is/isn't safe to commit.
6. **Standard Outline Structure:**
   - Module Overview & Metadata
   - Architecture & Repository Map
   - Representative Change Workflow
   - Supported Platforms & Prerequisites
   - Setup / Build / Test Command Reference
   - Data Formats, Persistence & Protocol Contracts
   - Safety, Backup & Runtime Boundaries
   - Known Limitations, Gaps & Maintenance Triggers
   - Portable Source Document Links

---

## YYToolkit & Context7 Integration

When working with submodules utilizing `YYToolkit` (such as `ForgePact` and `HS-Offline-Tracker`):
- Attempt retrieval of upstream `YYToolkit` documentation and API references via the `context7` MCP server when available.
- Treat local modified sources (e.g., `ForgePact/yytoolkit-modified/` and `HS-Offline-Tracker/aurie-loader/yytoolkit-modified/`) and repository header definitions as authoritative over upstream documentation.

---

## Automated Submodule Pointer Updates

[`.github/workflows/submodule-dispatch.yml`](../../.github/workflows/submodule-dispatch.yml)
listens for a `repository_dispatch` event (type `submodule-updated`), opens
a PR bumping the recorded commit for the named submodule, and automatically
squash-merges it only after the pointer validation below succeeds. The event is
meant to be fired by a small workflow living in each submodule's own repo
(template: [`.github/workflow-templates/notify-hub.example.yml`](../../.github/workflow-templates/notify-hub.example.yml)),
triggered when a commit lands on that submodule's tracked branch. Wiring the
sender side into a submodule repo requires push access there and a
`HUB_DISPATCH_TOKEN` secret scoped to this hub repo — see the template's
header comment for setup steps.

The merge step uses the hub's built-in `GITHUB_TOKEN`; no new PAT or secret is
needed. This is a merge step in the dispatch workflow, not GitHub's optional
queued Auto-merge feature. The repository's `allow_auto_merge` setting can stay
off. Contents write, pull requests write, checks read and statuses read are declared in the
workflow; squash merging must be allowed. Required reviews/checks and conflicts
are not bypassed. The existing Actions PR-creation permission is still needed.

[`tools/merge_submodule_pointer.py`](../../tools/merge_submodule_pointer.py)
only accepts a GitHub Actions bot PR from this repository, on the exact branch
created for this dispatch. Its sole changed entry must be the named gitlink,
pointing to the current default-branch tip in that tool's canonical repository.
The target must advance the hub's current pointer; rollbacks and divergent
histories need manual review. The tool repository supplies its default-branch
name, so `hero-siege-item-editor` is correctly checked against `master`.
Pending/failing checks, changed PR heads, unknown mergeability, and stale targets
leave the PR open. The merge request includes the validated head SHA and never
uses an administrator bypass or approves a review on someone's behalf.

The validator's tests run in the dispatch job itself. The workflow does not
depend on another PR-triggered job starting for a PR created by `GITHUB_TOKEN`.
An API error fails the job and leaves the PR for inspection; an ineligible PR
prints its reason and remains open. A later tool push or re-running its sender
workflow retries the process. Already-open PRs are not swept or bulk-merged when
this workflow is installed, and ordinary feature PRs are never candidates.

Read-only check (requires authenticated `gh` and Python; no `--merge`):

```bash
python tools/merge_submodule_pointer.py --pull-request <number> --submodule <tool> --sha <full-tool-commit>
python -m unittest discover -s tests -p test_pointer_automerge.py -v
```

Adding `--merge` performs the guarded merge. This updates the toolkit checkout's
recorded source revision only; it does not build or publish a tool release.

---

## Index Maintenance & Guide Reconciliation

- When a new submodule guide is authored at `docs/submodules/<module-name>/instructions.md`, update its entry in the inventory table above from a plain-text pending reference to an active relative link (`[<Module> Instructions](<module-name>/instructions.md)`).
- Ensure navigation links from the root `README.md` and `agents.md` remain aligned with available guides.
