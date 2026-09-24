# ADR 0003 — Item Truth lives in ForgePact, and the Item Editor reaches it only through files

**Status:** accepted, 2026-09-25
**Supersedes:** nothing
**Context:** [ForgePact#79](https://github.com/falorfrozen-cmd/ForgePact/pull/79) and
[hero-siege-item-editor#8](https://github.com/falorfrozen-cmd/hero-siege-item-editor/pull/8),
merged 2026-09-24; the question, raised about #79, of where this code belongs; the
follow-up [issue #173](https://github.com/falorfrozen-cmd/hero-siege-offline-toolkit/issues/173)

---

## The question

The Item Editor now shows every item it owns exactly as the running game builds
and draws it (Item Editor 2.16.0, ForgePact 1.4.5). Three parts of that work have
to run inside `Hero_Siege.exe`:
- recording each finished item at `CreateItemNew`'s outermost return;
- building the items the editor asks about through the game's own
  `InitItemFromJson`, on the game thread;
- recording the tooltip text the game draws, and drawing the tooltips of items
  nobody hovers into an off-screen surface.

About 1,400 lines of it went into ForgePact: `plugin/include/ForgePact/ItemTruth.hpp`
(661 lines) and `plugin/ModuleMain.cpp` (+745). Yet it serves the editor, not the
mod. Where should it live?

## The options

### The Item Editor: ruled out

The editor is Python, and it never injects code into the game
([its guide](../submodules/hero-siege-item-editor/instructions.md), "No Direct
Native Patching"). It can ask the game for something, but it cannot run code
there.

### `hs-game-sdk` alone: ruled out

The SDK ships headers, constants and curated data, not a DLL, so it cannot hook
anything by itself.

### A separate Aurie plugin for the editor: not now

The model exists: HS-Offline-Tracker's `aurie-producer`. But the record has to be
taken after Custom Forge has finished changing the item, and Custom Forge is
ForgePact's own `CreateItemNew` hook. Two DLLs hooking one function run in no
guaranteed order. A second plugin would first need an ordering contract with
ForgePact, which is a bigger change than the feature.

### ForgePact: chosen

- The ordering after Custom Forge comes free, because both run in ForgePact's
  single `CreateItemNew` hook.
- ForgePact already works for the editor this way: `bp_ipc\itemstats.json` and
  `customforge_status.json`. The itemstats snapshot now uses the same final pass.
- Nothing runs until the editor writes `itemtruth\capture.request`, so a player
  without the editor pays nothing.

## Decision

1. The hooks, the capture switch and the per-frame budgets stay in ForgePact.
2. The two modules talk only through the files under
   `%LOCALAPPDATA%\Hero_Siege\itemtruth\`. The contract is written down in the hub,
   in [the Item Editor's guide](../submodules/hero-siege-item-editor/instructions.md#game-truth-the-games-numbers-and-text-2160-2026-09-24),
   so ForgePact's code is not the only place that defines it. A change to the
   files changes that section too.
3. What the capture established about the game is in
   [`RUNTIME_DATA_MODELS.md` §16](../RUNTIME_DATA_MODELS.md#16-items-as-the-game-builds-and-draws-them)
   and `hs-game-sdk/curated/item_info.json`, not only in the two modules.
4. The reusable half of `ItemTruth.hpp` needs only the standard library and
   `windows.h`, with no YYToolkit. It covers the build id, the JSON helpers, the
   journal writer thread, the request queue and the tooltip record format. It moves
   into `hs-game-sdk` once a second plugin needs it
   ([issue #173](https://github.com/falorfrozen-cmd/hero-siege-offline-toolkit/issues/173)).
   It does not move sooner, because ForgePact's release build takes the SDK from
   hub `main`, so the move costs a hub PR that has to land before ForgePact's.

## What this gives up

- Editor features that need the game wait on ForgePact's release schedule.
- ForgePact's reviewers review code their mod does not use.
- Until #173 is done, a second plugin that wants the journal or the build id has
  to copy them.

## Consequences

- A change to the `itemtruth` files touches two modules and this hub's contract
  section. Per `AGENTS.md` § "One Branch and One Pull Request per Module, per
  Feature", that is one branch and one PR in each.
- A player who never runs the Item Editor never has `capture.request`, so ForgePact
  1.4.5 behaves for them as it did before.
