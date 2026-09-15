# ADR 0001 — Keep submodules; fix the coupling instead of moving the repos

**Status:** accepted, 2026-09-11
**Supersedes:** nothing
**Context:** the Toolkit Hub, [`docs/hub/design.md`](../hub/design.md)

---

## The question

Ten tools, one shared SDK, ten repositories joined by git submodules. Should the
toolkit become a monorepo?

## What the literature says, and why it does not decide this

The general argument favours the monorepo for exactly this shape: a shared SDK,
cross-cutting changes that want to be atomic, one CI run over the whole matrix.
The usual objection — that per-project release cycles get harder — is solved in
practice: `release-please` with `monorepo-tags: true` gives every tool its own
tag, changelog and GitHub Release inside a single repository.

So the standard trade-off does not settle it. Three facts about *this* project do.

### 1. The repositories are not ours to move

The canonical repositories are `falorfrozen-cmd/*`. Every checkout points
`origin` at those, and where a fork still exists it is the remote named `fork`
(`S-Borkowski/*`) — the superproject and each submodule agree on that.

A migration is therefore not a change we can make — it is a proposal to
upstream, across ten repositories, with ten sets of release history and issue
links to preserve. Blocking the hub on that means shipping nothing.

**Amended 2026-09-15.** This reason has weakened: the author is now a
collaborator on all eleven `falorfrozen-cmd` repositories, so a migration is no
longer someone else's to approve. The superproject's remotes were backwards
until this date — `origin` was the fork and `falorfrozen-cmd` was `upstream`,
which is why contributions kept being routed through a fork nobody needed — and
were swapped to match the convention above. The decision below still stands, on
reasons 2 and 3: those are about what a monorepo would and would not fix, and
access changes neither.

### 2. Two members cannot join

`HS-ValueEditor` and `Hs-Offline-Loot-Forge` contain a built `.exe` and
supporting text, and no source at all. In a monorepo they would be committed
binaries, which the root `.gitignore` bans outright (`*.exe`). They would stay
external either way, so the monorepo never actually becomes whole — it becomes
eight repositories in a trench coat plus two that are still separate.

### 3. The migration would not fix the defect it is prescribed for

This is the one that matters.

The SDK coupling problem is not "ten pull requests are annoying". It is that
`ForgePact/src/forgepact.py:37` resolves `hs-game-sdk` by walking
`parents[2]/"hs-game-sdk"/"python"`, and `:58` swallows the failure into
`GameObject = None`. `ForgePact/build_release.py` never bundles the SDK. So every
*shipped* ForgePact runs with the SDK absent and fails open, silently.

A monorepo does not put a wheel inside a PyInstaller build. The fix is to publish
the SDK as a versioned artifact and vendor it into each frozen build — and that
fix is needed in either topology.

## Decision

Keep submodules. Do the three things the monorepo was wanted for, directly.

### Publish `hs-game-sdk` as a versioned artifact

- Build a wheel from the existing `hs-game-sdk/python/pyproject.toml`.
- Add the missing `tsconfig.json` and build script so `@hero-siege/sdk` matches
  its own manifest — `hs-game-sdk/ts/package.json` declares
  `main: dist/index.js`, and today nothing produces `dist/`.
- Zip the C++ headers.
- Attach all three to an `sdk-vX.Y.Z` release.

Each consumer pins a version and vendors it into its frozen build (an
`--add-data` / `collect` step in `ForgePact/build_release.py` and its
equivalents), which deletes the `parents[2]` path hack and the silent `None`.

### Make the hub indifferent to topology

The hub consumes *released artifacts* through the signed catalog, never source.
Whether the source lives in one repository or ten is invisible to it. This is
why the catalog has a `submodule` field but no `path` field: the submodule name
is used only for developer mode, and developer mode is a convenience, not a
dependency.

### Keep the door open

If upstream later wants the monorepo, the work above has already removed most of
its motivation, and nothing in the hub or the catalog changes. The migration
path, should anyone want it:

1. `git subtree add` each tool into `tools/<name>/` preserving history.
2. `release-please` with `monorepo-tags: true`, one component per tool.
3. `catalog/sources.toml` keeps its `repo` field pointing at the monorepo and
   gains nothing else — tags become `<tool>-vX.Y.Z` and `asset_pattern` is
   unchanged.
4. `HS-ValueEditor` and `Hs-Offline-Loot-Forge` stay external regardless.

## What this gives up

Honestly stated, because it is a real cost:

- A cross-cutting SDK regeneration still spans ten pull requests.
- CI still cannot test the whole matrix in one run.

The pinned-SDK model contains the blast radius — consumers upgrade deliberately
instead of being broken by a pointer bump — but it does not make the change
atomic. That is accepted.

## Consequences

- The hub can ship now, without upstream coordination.
- The SDK work (Phase 5 of the plan) is a sequence of pull requests to
  repositories this one does not own, and is deliberately sequenced *after* the
  hub ships so upstream review never blocks it.
- `catalog/sources.toml` remains the single place where per-tool facts live,
  whichever topology the source ends up in.
