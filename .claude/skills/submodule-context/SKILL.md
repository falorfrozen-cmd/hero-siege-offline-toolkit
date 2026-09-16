---
name: submodule-context
description: Load a submodule's development guide before working in it. Use whenever a task touches ForgePact/, HS-Offline-Launcher/, HS-Offline-Tracker/, HS-ValueEditor/, HSCraftSim/, HSSaveEditor/, HSSaveEditor-SteamDeck-/, Hs-Offline-Loot-Forge/, hero-siege-item-editor/, hs-stat-forge/, hs-game-sdk/ or hub/ — before reading their source, planning a change, or answering a question about how one of them works.
user-invocable: false
---

# Read the module's guide first

`AGENTS.md` opens with this rule and `CLAUDE.md` repeats it, because on
2026-09-14 an agent fixed two ForgePact bugs, opened both pull requests, and
only then found `AGENTS.md` — so the change went up for review with no
documentation updates and without the module's guide ever being read.

These guides are **not optional background**. They carry workflow, test
commands, packaging guardrails and release rules that no amount of reading the
source reveals. ForgePact, for instance, expects a player-visible change to
carry its `release-notes-vX.Y.Z.md` in the same PR, because `forgepact-tag.yml`
composes the draft release body from those files — nothing in the plugin code
says that.

## What to read

| Working in | Read |
|---|---|
| Any submodule | `docs/submodules/<submodule-name>/instructions.md` |
| `hub/` (not a submodule) | `hub/instructions.md`, then `docs/hub/design.md` |
| `hs-game-sdk/`, or any runtime value | `docs/submodules/hs-game-sdk/instructions.md` and `docs/RUNTIME_DATA_MODELS.md` |
| Anything catalog-shaped | `docs/hub/catalog-schema.md` |
| Unsure which module owns something | the index at `docs/submodules/README.md` |

A submodule may also carry its own `instructions.md` in its working directory.
Each submodule additionally carries its own `AGENTS.md` and `CLAUDE.md`
pointing back to the superproject, because a submodule checkout is a separate
repository and inherits nothing from this one.

Submodules are frequently **not checked out** in a given worktree. If the
directory is empty, the guide under `docs/submodules/` is still present and is
still the thing to read — say that the source is unavailable rather than
guessing at it, or run `git submodule update --init <path>`.

## What the guides commit you to

Each guide's command tables are marked `Verified`, `Inspected` or `Blocked`.
Prefer a `Verified` command verbatim — working directory, shell and
prerequisites are part of it, and several of these tools are Windows-only and
expect PowerShell.

Two rules from `AGENTS.md` apply to every module and are worth holding
alongside the guide:

- **Update the docs in the same change.** When you change a feature, workflow,
  architecture or dependency, update that module's `instructions.md` and any
  affected `README.md`. Do not leave a `*-plan.md` behind — it is gitignored
  on purpose; fold what is still true into the guide, an ADR, or
  `docs/hub/design.md`.
- **Never paste decompiled or disassembled game source.** Reference game
  objects and scripts by the names and indices in `hs-game-sdk`, and document
  measured runtime *behavior* instead. See "Legal: Decompiled Output Never
  Reaches Any Origin" in `AGENTS.md`.

## Related

For changes to the SDK bindings or anything reading runtime values, the
`sdk-contract-reviewer` agent covers the recurring identity/kind/stub bug class.
For `hub/src-tauri/`, the `tauri-command-reviewer` agent covers the command
threading rules.
