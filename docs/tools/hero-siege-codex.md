# Hero Siege Codex

An English offline reference archive, created by Falor. The Toolkit installs its Windows x64 portable release from [falorfrozen-cmd/hero-siege-codex](https://github.com/falorfrozen-cmd/hero-siege-codex).

## Integration contract

| Field | Value |
| --- | --- |
| Stable catalog ID | `hero-siege-codex` |
| Display name | Hero Siege Codex |
| Summary | Explore items, classes, creatures, and the world. |
| Package | `HeroSiegeItemCodex-<version>-Windows-x64-Portable.zip` |
| Entry point | `hero-siege-item-codex.exe` at the ZIP root |
| Install kind | `zip`, managed per-user by the Toolkit |
| Requirements | Windows x64 and WebView2; no administrator or game-state requirement |
| Health check | Process liveness; no HTTP service or ports |
| Source checkout | Release-only integration; no submodule or source launch |

Existing Toolkit 1.0.5 clients accept this additive schema-1 entry after refreshing their signed catalog. The entry appears under All and search using the standard fallback icon. No Toolkit executable update or custom card styling is needed.

## User behavior

The card follows Install, Launch and Update using the existing Toolkit pipeline. The archive neither reads nor writes game saves and can be used without the game installed. Data, images, fonts and search are bundled; external social links require internet.

The portable edition does not register `hscodex:` with Windows. Use File > Open entry link... or Ctrl+O to paste a shared link. Users wanting protocol registration can choose standalone setup from the Codex release page, but the Toolkit must continue installing the portable ZIP.

Version 0.5.0 is a public test edition. Its in-package verification report describes remaining Windows/device coverage and known data limitations. Missing facts are labelled; the release is not a complete-current-game guarantee.

## Future releases

Publish immutable assets under `v<version>`, with a `SHA256SUMS.txt` sidecar. The generator uses the latest published non-prerelease release; test status is stated in the release title and documentation.

After publishing, run Catalog from GitHub Actions with `only=hero-siege-codex`, or:

```sh
gh workflow run catalog.yml --repo falorfrozen-cmd/hero-siege-offline-toolkit --ref main -f only=hero-siege-codex
```

Review and merge the generated catalog PR after its checks pass. Catalog publish uploads the signed pair. The other ten tool entries must remain unchanged. Publishing only the Codex release does not notify Toolkit clients; no sender workflow/token is configured in the distribution repository.

Never select the Setup EXE or the standalone setup ZIP as this tool's artifact, and do not add a made-up HTTP health endpoint. `catalog/sources.toml` is the package rule; `tools/build_catalog.py` verifies its archive and checksum before signing.
