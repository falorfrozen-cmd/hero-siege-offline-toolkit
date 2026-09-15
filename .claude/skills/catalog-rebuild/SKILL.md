---
name: catalog-rebuild
description: Rebuild, sign and verify catalog/catalog.json from catalog/sources.toml. Use when a tool has published a release the catalog does not know about, when sources.toml changed, or when a signature check failed and you need to know whether the catalog or the copy is wrong.
disable-model-invocation: true
---

# Rebuild the tool catalog

`catalog/catalog.json` is what the hub reads: one entry per tool with a pinned
SHA-256, how to install it, how to launch it, and what it requires. It is
generated from the hand-written per-tool rules in `catalog/sources.toml`,
resolved against each repository's latest GitHub **release**, and signed with
minisign.

Normally CI does this — `catalog.yml` rebuilds on a `release-published` or
`submodule-updated` dispatch and opens a pull request. Rebuild by hand when a
release was published from a repository whose notifier is not installed or
whose `HUB_DISPATCH_TOKEN` has lapsed, because nothing else will pick it up.

## Before you start

**The signing key is not in this repository and must never be.**
`--key` defaults to `$HUB_MINISIGN_SECRET_KEY`. If that is not set, you do not
have the key on this machine — stop and rebuild unsigned (`--print` or plain
`--sign`-less) so a human with the key can sign, rather than inventing one.

**Never write `catalog/catalog.json` through Python text mode.** The minisign
signature covers the exact bytes. `open(path, "w")` on Windows turns every `\n`
into `\r\n` and invalidates it, and the damage is invisible locally because a
file you wrote and committed is never re-checked-out. This is documented at
length in `.gitattributes` because it once produced fourteen signature failures
that named everything except the cause. Use binary I/O.

## Steps

1. **Check first whether the catalog is actually wrong.** A `BAD SIGNATURE` is
   more often a stale or mangled working copy than a signing problem:

   ```bash
   py -3 tools/minisign.py verify catalog/catalog.json --public-key catalog/catalog-signing.pub
   git status --porcelain -- catalog/
   ```

   If verification fails on an unmodified file, restore it
   (`git checkout -- catalog/catalog.json`) and verify again before rebuilding
   anything.

2. **Rebuild.** Full, or narrowed to the tools that moved — a partial rebuild
   reads the existing catalog for every tool it is *not* rebuilding, so those
   entries survive:

   ```bash
   py -3 tools/build_catalog.py --sign
   py -3 tools/build_catalog.py --sign --only forgepact hscraftsim
   ```

   Useful flags: `--cache-dir <dir>` keeps downloaded assets so reruns are
   cheap; `--token` (or `$GITHUB_TOKEN`) raises the rate limit and is never
   required; `--print` dumps to stdout and writes nothing; `--no-download`
   trusts the releases' checksum sidecars but **skips `strip_prefix` derivation
   and the launch-path check**, so do not use it for a catalog you intend to
   publish.

3. **Verify the signature you just produced.**

   ```bash
   py -3 tools/minisign.py verify catalog/catalog.json --public-key catalog/catalog-signing.pub
   ```

4. **Run the generator's tests.**

   ```bash
   py -3 -m unittest discover -s tests
   ```

5. **Read the diff before committing.** Every entry carries a pinned hash and a
   version taken from the git tag, not from the asset filename — `HS-ValueEditor`
   ships `HSValueScanner-Windows-v1.0.1.zip` under tag `v1.0.2` and the catalog
   says 1.0.2. A version moving backwards, or a hash changing with no version
   change, means a release was re-cut and is worth a second look rather than a
   commit.

## When a tool's entry cannot be built

The ten repositories agree on no naming convention, which is why every field in
`sources.toml` is declared rather than inferred. If a rebuild cannot find the
asset, the fix is almost always `asset_pattern` in `sources.toml` — the tool
published under a new filename — not a change to the generator. See
`docs/hub/catalog-schema.md` and `docs/adr/0001-repo-topology.md`.

## Afterwards

`.claude/hooks/catalog_signature.py` re-verifies the signature after any edit
that touches `catalog/`, so a later mangling will be caught at the point it
happens rather than in CI. If that hook fires, step 1 above is the response.
