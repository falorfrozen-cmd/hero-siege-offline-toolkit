---
name: submodule-context
description: Load a submodule's development guide before working in it. Use whenever a task touches ForgePact/, HS-Offline-Launcher/, HS-Offline-Tracker/, HS-ValueEditor/, HSCraftSim/, HSSaveEditor/, HSSaveEditor-SteamDeck-/, Hs-Offline-Loot-Forge/, hero-siege-item-editor/, hs-stat-forge/, hs-game-sdk/, hub/ or third_party/yytoolkit/ (the modified YYToolkit's patch series, including any question about the distributed YYToolkit.dll or a submodule's yytoolkit-modified/ copy) — before reading their source, planning a change, or answering a question about how one of them works.
user-invocable: false
---

# Read the module's guide first

`AGENTS.md` and `CLAUDE.md` both open with this rule, because on 2026-09-14 an
agent fixed two ForgePact bugs and opened both PRs without ever reading
`AGENTS.md` or the module's guide.

These guides are **not optional background** — they carry workflow, test
commands, packaging guardrails and release rules no amount of reading the
source reveals. ForgePact, for instance, expects a player-visible change to
carry its `release-notes-vX.Y.Z.md` in the same PR, because `forgepact-tag.yml`
composes the draft release body from those files.

## What to read

| Working in | Read |
|---|---|
| Any submodule | `docs/submodules/<submodule-name>/instructions.md` — by section, below |
| `hub/` (not a submodule) | `hub/instructions.md`, then `docs/hub/design.md` |
| `hs-game-sdk/`, or any runtime value | `docs/submodules/hs-game-sdk/instructions.md` and `docs/RUNTIME_DATA_MODELS.md` |
| `third_party/yytoolkit/` (not a submodule), `tools/build_yytoolkit.py`, or anything about the distributed `YYToolkit.dll` — including `ForgePact/yytoolkit-modified/` and `HS-Offline-Tracker/aurie-loader/yytoolkit-modified/`, which are **not** the source of truth | `third_party/yytoolkit/README.md`, then the header of every patch you touch (`Why` / `Evidence` / `Fails-safe` / `Log-markers` / `Upstream-status`); `docs/adr/0002-modified-yytoolkit-is-a-patch-series-in-the-hub.md` for why it is a series |
| Anything catalog-shaped | `docs/hub/catalog-schema.md` |
| Unsure which module owns something | the index at `docs/submodules/README.md` |

### Read a guide by section

`grep -n '^## \|^### ' <guide>` first — the same role has a different heading per
module (ForgePact's `Command Reference` = `hero-siege-item-editor`'s `Setup,
Build, Run, & Test Commands`), and a guide may skip a role it has no use for
(only ForgePact and `hs-stat-forge` package a binary). **Always read**:
overview/metadata, the change workflow (if any), platforms & prerequisites,
the command reference, packaging guardrails (if any), maintenance triggers,
and the repository-layout entries for your files. **Always grep** the
symbols you're changing and read every match — Known Limitations especially.
Data formats, release/tagging and long narratives (ForgePact's Performance
Pass is 47KB) are on demand only.

A submodule may also carry its own `instructions.md` in its working directory.
Each submodule additionally carries its own `AGENTS.md` and `CLAUDE.md`
pointing back to the superproject, because a submodule checkout is a separate
repository and inherits nothing from this one.

Submodules are frequently **not checked out**. If the directory is empty, the
guide under `docs/submodules/` is still there and still the thing to read —
say the source is unavailable rather than guessing, or run `git submodule
update --init <path>`.

## What the guides commit you to

Each guide's command tables are marked `Verified`, `Inspected` or `Blocked`.
Prefer a `Verified` command verbatim — working directory, shell and
prerequisites are part of it, and several tools here are Windows-only and
expect PowerShell.

Two `AGENTS.md` rules apply to every module:

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

`sdk-contract-reviewer` covers the identity/kind/stub bug class for SDK
bindings; `tauri-command-reviewer` covers command threading for
`hub/src-tauri/`.
