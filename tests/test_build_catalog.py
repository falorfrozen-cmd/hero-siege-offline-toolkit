"""Tests for the Toolkit Hub catalog generator.

No network. Every release payload here is a trimmed copy of what
`api.github.com/repos/falorfrozen-cmd/<tool>/releases/latest` actually returned on
2026-09-11, so the awkward shapes being tested are the real ones: HSCraftSim's
seven assets, HS-ValueEditor's tag/asset version disagreement, and
HS-Offline-Tracker's checksum file naming an asset GitHub serves under a
different spelling.
"""

import hashlib
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import build_catalog as bc  # noqa: E402
from build_catalog import CatalogError  # noqa: E402


def make_zip(entries):
    """Build a zip in memory. `entries` maps archive path -> bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def asset(name, url=None, size=None):
    return {
        "name": name,
        "browser_download_url": url or f"https://example.invalid/{name}",
        "size": size if size is not None else 0,
    }


class FakeFetcher:
    """Stands in for GitHubFetcher. Records what was asked for."""

    def __init__(self, releases, blobs=None):
        self.releases = releases
        self.blobs = blobs or {}
        self.release_calls = []
        self.asset_calls = []

    def release(self, repo):
        self.release_calls.append(repo)
        if repo not in self.releases:
            raise CatalogError(f"no fixture for {repo}")
        return self.releases[repo]

    def asset(self, url, name=""):
        self.asset_calls.append(name or url)
        key = name or url
        if key not in self.blobs:
            raise CatalogError(f"no blob fixture for {key}")
        return self.blobs[key]


class TestVersionNormalization(unittest.TestCase):
    def test_strips_leading_v(self):
        self.assertEqual(bc.normalize_version("v1.3.16"), "1.3.16")
        self.assertEqual(bc.normalize_version("V2.15.4"), "2.15.4")

    def test_leaves_bare_versions_alone(self):
        self.assertEqual(bc.normalize_version("1.0.2"), "1.0.2")

    def test_does_not_strip_a_v_that_starts_a_word(self):
        # `version-2` is not a v-prefixed number; chopping the v would be wrong.
        self.assertEqual(bc.normalize_version("version-2"), "version-2")


class TestAssetSelection(unittest.TestCase):
    def test_picks_the_windows_build_out_of_hscraftsims_seven_assets(self):
        assets = [
            asset("HSCraftSim-1.0.2-SHA256SUMS.txt"),
            asset("HSCraftSim-1.0.2-Source.zip"),
            asset("HSCraftSim-1.0.2-Source.zip.sha256"),
            asset("HSCraftSim-1.0.2-Windows-x64.zip"),
            asset("HSCraftSim-Research-Scripts-2026-09-09.zip"),
            asset("HSCraftSim-Research-Scripts-2026-09-09.zip.sha256"),
            asset("HSCraftSim.exe"),
        ]
        chosen = bc.select_asset(assets, r"^HSCraftSim-[0-9][^/]*-Windows-x64\.zip$", "hscraftsim")
        self.assertEqual(chosen["name"], "HSCraftSim-1.0.2-Windows-x64.zip")

    def test_no_match_is_fatal_and_lists_what_was_available(self):
        with self.assertRaises(CatalogError) as ctx:
            bc.select_asset([asset("something-else.zip")], r"^nope\.zip$", "toolid")
        self.assertIn("toolid", str(ctx.exception))
        self.assertIn("something-else.zip", str(ctx.exception))

    def test_ambiguous_match_is_fatal_rather_than_first_wins(self):
        assets = [asset("tool-1.0.zip"), asset("tool-1.0-portable.zip")]
        with self.assertRaises(CatalogError) as ctx:
            bc.select_asset(assets, r"^tool-1\.0.*\.zip$", "toolid")
        self.assertIn("matched 2 assets", str(ctx.exception))


class TestChecksumParsing(unittest.TestCase):
    def test_two_space_form(self):
        text = "e0bbe3a0" + "0" * 56 + "  ForgePact-1.3.16.zip\n"
        self.assertEqual(
            bc.parse_checksums(text), {"ForgePact-1.3.16.zip": "e0bbe3a0" + "0" * 56}
        )

    def test_binary_star_form_and_uppercase_hex(self):
        digest = "2BD07A49C21DB48C17CAF3054C6FA7338ABE83DAA85DC7BD118A8F297FC60816"
        text = f"{digest} *HSSaveEditor-Windows-v1.4.1.zip\n"
        parsed = bc.parse_checksums(text)
        self.assertEqual(parsed["HSSaveEditor-Windows-v1.4.1.zip"], digest.lower())

    def test_multi_entry_file_and_blank_lines(self):
        text = (
            "\n"
            "# a comment\n"
            "aa" + "0" * 62 + "  one.zip\n"
            "bb" + "0" * 62 + " *two.exe\n"
        )
        self.assertEqual(set(bc.parse_checksums(text)), {"one.zip", "two.exe"})

    def test_garbage_lines_are_ignored_not_fatal(self):
        self.assertEqual(bc.parse_checksums("not a checksum at all\n"), {})


class TestChecksumNameMatching(unittest.TestCase):
    def test_matches_when_github_replaced_spaces_with_dots(self):
        # SHA256SUMS-0.1.2.txt names the setup with spaces; the asset downloads
        # as HS.Offline.Tracker_0.1.2_x64-setup.exe.
        sums = {"HS Offline Tracker_0.1.2_x64-setup.exe": "ab" + "0" * 62}
        found = bc.find_checksum(sums, "HS.Offline.Tracker_0.1.2_x64-setup.exe")
        self.assertEqual(found, "ab" + "0" * 62)

    def test_exact_match_still_wins(self):
        sums = {"ForgePact-1.3.16.zip": "cd" + "0" * 62}
        self.assertEqual(bc.find_checksum(sums, "ForgePact-1.3.16.zip"), "cd" + "0" * 62)

    def test_unrelated_name_returns_none(self):
        self.assertIsNone(bc.find_checksum({"a.zip": "ee" + "0" * 62}, "b.zip"))


class TestStripPrefixDerivation(unittest.TestCase):
    def test_single_wrapping_directory_is_stripped(self):
        archive = make_zip({
            "ForgePact/ForgePact.exe": b"MZ",
            "ForgePact/modfiles/AurieCore.dll": b"MZ",
        })
        self.assertEqual(bc.derive_strip_prefix(archive), "ForgePact/")

    def test_flat_archive_has_no_prefix(self):
        archive = make_zip({"HSValueScanner.exe": b"MZ", "README.txt": b"hi"})
        self.assertEqual(bc.derive_strip_prefix(archive), "")

    def test_single_top_level_file_is_not_mistaken_for_a_wrapper(self):
        archive = make_zip({"only.exe": b"MZ"})
        self.assertEqual(bc.derive_strip_prefix(archive), "")

    def test_multiple_roots_have_no_prefix(self):
        archive = make_zip({"a/x.txt": b"1", "b/y.txt": b"2"})
        self.assertEqual(bc.derive_strip_prefix(archive), "")

    def test_empty_archive_is_fatal(self):
        with self.assertRaises(CatalogError):
            bc.derive_strip_prefix(make_zip({}))

    def test_archive_contains_respects_the_prefix(self):
        archive = make_zip({"ForgePact/ForgePact.exe": b"MZ"})
        self.assertTrue(bc.archive_contains(archive, "ForgePact.exe", "ForgePact/"))
        self.assertFalse(bc.archive_contains(archive, "ForgePact.exe", ""))


class TestBuildToolEntry(unittest.TestCase):
    def _forgepact(self):
        archive = make_zip({
            "ForgePact/ForgePact.exe": b"MZ ForgePact",
            "ForgePact/modfiles/AurieCore.dll": b"MZ dll",
        })
        digest = hashlib.sha256(archive).hexdigest()
        release = {
            "tag_name": "v1.3.16",
            "published_at": "2026-09-10T06:24:46Z",
            "html_url": "https://github.com/falorfrozen-cmd/ForgePact/releases/tag/v1.3.16",
            "body": "Fixes the density slider.",
            "assets": [
                asset("ForgePact-1.3.16.zip", size=len(archive)),
                asset("ForgePact-1.3.16.zip.sha256"),
            ],
        }
        blobs = {
            "ForgePact-1.3.16.zip": archive,
            "ForgePact-1.3.16.zip.sha256": f"{digest}  ForgePact-1.3.16.zip\n".encode(),
        }
        tool = {
            "id": "forgepact",
            "name": "ForgePact",
            "summary": "Offline gameplay modifiers.",
            "repo": "falorfrozen-cmd/ForgePact",
            "submodule": "ForgePact",
            "license": "AGPL-3.0",
            "guide": "docs/submodules/ForgePact/instructions.md",
            "asset_pattern": r"^ForgePact-[0-9][^/]*\.zip$",
            "kind": "zip",
            "requires": {"admin": False, "game_closed": False, "windows_only": True},
            "launch": {"exe": "ForgePact.exe", "args": [], "elevate": False, "ports": [8766]},
            "source_launch": {"cmd": "py", "args": ["-3", "src/forgepact.py"]},
        }
        return tool, release, blobs, digest

    def test_zip_entry_pins_hash_and_derives_prefix(self):
        tool, release, blobs, digest = self._forgepact()
        fetcher = FakeFetcher({tool["repo"]: release}, blobs)
        entry = bc.build_tool_entry(tool, fetcher)

        self.assertEqual(entry["version"], "1.3.16")
        self.assertEqual(entry["artifact"]["sha256"], digest)
        self.assertEqual(entry["artifact"]["strip_prefix"], "ForgePact/")
        self.assertEqual(entry["artifact"]["sha256_source"], "published+verified")
        self.assertEqual(entry["license"], "AGPL-3.0")
        self.assertEqual(entry["source_launch"]["cmd"], "py")
        self.assertFalse(entry["requires"]["admin"])

    def test_published_hash_that_disagrees_with_the_bytes_is_fatal(self):
        tool, release, blobs, _ = self._forgepact()
        blobs["ForgePact-1.3.16.zip.sha256"] = (b"0" * 64) + b"  ForgePact-1.3.16.zip\n"
        fetcher = FakeFetcher({tool["repo"]: release}, blobs)
        with self.assertRaises(CatalogError) as ctx:
            bc.build_tool_entry(tool, fetcher)
        self.assertIn("Refusing to pin", str(ctx.exception))

    def test_launch_exe_missing_from_the_archive_is_fatal(self):
        tool, release, blobs, _ = self._forgepact()
        tool["launch"]["exe"] = "NotThere.exe"
        fetcher = FakeFetcher({tool["repo"]: release}, blobs)
        with self.assertRaises(CatalogError) as ctx:
            bc.build_tool_entry(tool, fetcher)
        self.assertIn("does not contain", str(ctx.exception))

    def test_no_download_trusts_the_sidecar_and_never_fetches_the_artifact(self):
        tool, release, blobs, digest = self._forgepact()
        tool["strip_prefix"] = "ForgePact/"
        fetcher = FakeFetcher({tool["repo"]: release}, blobs)
        entry = bc.build_tool_entry(tool, fetcher, download=False)
        self.assertEqual(entry["artifact"]["sha256"], digest)
        self.assertEqual(entry["artifact"]["sha256_source"], "published")
        self.assertNotIn("ForgePact-1.3.16.zip", fetcher.asset_calls)

    def test_no_download_without_any_sidecar_is_fatal(self):
        tool, release, blobs, _ = self._forgepact()
        release["assets"] = [asset("ForgePact-1.3.16.zip")]
        fetcher = FakeFetcher({tool["repo"]: release}, blobs)
        with self.assertRaises(CatalogError) as ctx:
            bc.build_tool_entry(tool, fetcher, download=False)
        self.assertIn("no published checksum", str(ctx.exception))

    def test_repo_without_a_release_is_fatal(self):
        tool, _, blobs, _ = self._forgepact()
        fetcher = FakeFetcher({tool["repo"]: {"message": "Not Found"}}, blobs)
        with self.assertRaises(CatalogError) as ctx:
            bc.build_tool_entry(tool, fetcher)
        self.assertIn("no published release", str(ctx.exception))


class TestArtifactKinds(unittest.TestCase):
    def test_exe_kind_defaults_the_launch_exe_to_the_asset_name(self):
        payload = b"MZ item editor"
        digest = hashlib.sha256(payload).hexdigest()
        tool = {
            "id": "hero-siege-item-editor",
            "name": "Hero Siege Item Editor",
            "repo": "falorfrozen-cmd/hero-siege-item-editor",
            "asset_pattern": r"^HeroSiegeItemEditor-v[0-9][^/]*\.exe$",
            "kind": "exe",
            "launch": {"ports": [8765]},
        }
        release = {
            "tag_name": "v2.15.4",
            "assets": [
                asset("HeroSiegeItemEditor-v2.15.4-s10.exe", size=len(payload)),
                asset("HeroSiegeItemEditor-v2.15.4-s10.exe.sha256"),
            ],
        }
        blobs = {
            "HeroSiegeItemEditor-v2.15.4-s10.exe": payload,
            "HeroSiegeItemEditor-v2.15.4-s10.exe.sha256":
                f"{digest} *HeroSiegeItemEditor-v2.15.4-s10.exe\n".encode(),
        }
        entry = bc.build_tool_entry(tool, FakeFetcher({tool["repo"]: release}, blobs))
        self.assertEqual(entry["artifact"]["kind"], "exe")
        self.assertEqual(entry["launch"]["exe"], "HeroSiegeItemEditor-v2.15.4-s10.exe")
        self.assertEqual(entry["artifact"]["strip_prefix"], "")
        self.assertEqual(entry["artifact"]["install_as"], entry["launch"]["exe"])

    def test_exe_kind_installs_under_the_declared_stable_name(self):
        # The released filename carries the version; the installed one must not,
        # or the launch path changes on every update and the state file's idea of
        # where the exe lives goes stale.
        payload = b"MZ item editor"
        tool = {
            "id": "hero-siege-item-editor",
            "name": "Hero Siege Item Editor",
            "repo": "falorfrozen-cmd/hero-siege-item-editor",
            "asset_pattern": r"^HeroSiegeItemEditor-v[0-9][^/]*\.exe$",
            "kind": "exe",
            "launch": {"exe": "HeroSiegeItemEditor.exe", "ports": [8765]},
        }
        release = {
            "tag_name": "v2.15.4",
            "assets": [asset("HeroSiegeItemEditor-v2.15.4-s10.exe", size=len(payload))],
        }
        blobs = {"HeroSiegeItemEditor-v2.15.4-s10.exe": payload}
        entry = bc.build_tool_entry(tool, FakeFetcher({tool["repo"]: release}, blobs))
        self.assertEqual(entry["artifact"]["name"], "HeroSiegeItemEditor-v2.15.4-s10.exe")
        self.assertEqual(entry["artifact"]["install_as"], "HeroSiegeItemEditor.exe")

    def test_nsis_kind_is_accepted(self):
        payload = b"MZ setup"
        tool = {
            "id": "hs-offline-tracker-setup",
            "name": "HS Offline Tracker (setup)",
            "repo": "falorfrozen-cmd/HS-Offline-Tracker",
            "asset_pattern": r"^HS\.Offline\.Tracker_[0-9].*-setup\.exe$",
            "kind": "nsis",
            "launch": {},
        }
        release = {
            "tag_name": "v0.1.2",
            "assets": [asset("HS.Offline.Tracker_0.1.2_x64-setup.exe", size=len(payload))],
        }
        blobs = {"HS.Offline.Tracker_0.1.2_x64-setup.exe": payload}
        entry = bc.build_tool_entry(tool, FakeFetcher({tool["repo"]: release}, blobs))
        self.assertEqual(entry["artifact"]["kind"], "nsis")
        self.assertEqual(entry["artifact"]["sha256"], hashlib.sha256(payload).hexdigest())

    def test_html_kind_keeps_the_declared_entry_document(self):
        archive = make_zip({"HSSaveEditor.html": b"<!doctype html>"})
        tool = {
            "id": "hssaveeditor-steamdeck",
            "name": "HS Steam Deck Save Editor",
            "repo": "falorfrozen-cmd/HSSaveEditor-SteamDeck-",
            "asset_pattern": r"^HSSaveEditor-SteamDeck-Web-v[0-9][^/]*\.zip$",
            "kind": "html",
            "requires": {"windows_only": False},
            "launch": {"exe": "HSSaveEditor.html"},
        }
        release = {
            "tag_name": "v1.0.0",
            "assets": [asset("HSSaveEditor-SteamDeck-Web-v1.0.0.zip", size=len(archive))],
        }
        blobs = {"HSSaveEditor-SteamDeck-Web-v1.0.0.zip": archive}
        entry = bc.build_tool_entry(tool, FakeFetcher({tool["repo"]: release}, blobs))
        self.assertEqual(entry["launch"]["exe"], "HSSaveEditor.html")
        self.assertFalse(entry["requires"]["windows_only"])
        # `html` says how the hub opens it, not how it arrives -- it is a zip, so
        # it still gets a strip_prefix and the entry document still gets checked.
        self.assertEqual(entry["artifact"]["strip_prefix"], "")

    def test_html_kind_still_checks_the_entry_document_exists(self):
        archive = make_zip({"wrapper/something-else.html": b"<!doctype html>"})
        tool = {
            "id": "hssaveeditor-steamdeck",
            "name": "HS Steam Deck Save Editor",
            "repo": "falorfrozen-cmd/HSSaveEditor-SteamDeck-",
            "asset_pattern": r"^HSSaveEditor-SteamDeck-Web-v[0-9][^/]*\.zip$",
            "kind": "html",
            "launch": {"exe": "HSSaveEditor.html"},
        }
        release = {
            "tag_name": "v1.0.0",
            "assets": [asset("HSSaveEditor-SteamDeck-Web-v1.0.0.zip", size=len(archive))],
        }
        blobs = {"HSSaveEditor-SteamDeck-Web-v1.0.0.zip": archive}
        with self.assertRaises(CatalogError):
            bc.build_tool_entry(tool, FakeFetcher({tool["repo"]: release}, blobs))


class TestValueEditorVersionMismatch(unittest.TestCase):
    """Tag v1.0.2 ships HSValueScanner-Windows-v1.0.1.zip.

    The catalog has to say 1.0.2, or the hub will offer an update on every single
    check: the installed version would read 1.0.1 from the filename while the
    release stays at v1.0.2 forever.
    """

    def test_version_comes_from_the_tag_not_the_filename(self):
        archive = make_zip({"HSValueScanner.exe": b"MZ"})
        tool = {
            "id": "hs-value-editor",
            "name": "HS Value Scanner",
            "repo": "falorfrozen-cmd/HS-ValueEditor",
            "asset_pattern": r"^HSValueScanner-Windows-v[0-9][^/]*\.zip$",
            "kind": "zip",
            "requires": {"admin": True, "game_running": True},
            "launch": {"exe": "HSValueScanner.exe", "elevate": True},
        }
        release = {
            "tag_name": "v1.0.2",
            "assets": [asset("HSValueScanner-Windows-v1.0.1.zip", size=len(archive))],
        }
        blobs = {"HSValueScanner-Windows-v1.0.1.zip": archive}
        entry = bc.build_tool_entry(tool, FakeFetcher({tool["repo"]: release}, blobs))

        self.assertEqual(entry["version"], "1.0.2")
        self.assertEqual(entry["tag"], "v1.0.2")
        self.assertEqual(entry["artifact"]["name"], "HSValueScanner-Windows-v1.0.1.zip")
        self.assertTrue(entry["requires"]["admin"])
        self.assertTrue(entry["requires"]["game_running"])
        self.assertTrue(entry["launch"]["elevate"])


class TestSourcesFile(unittest.TestCase):
    SOURCES = Path(__file__).resolve().parents[1] / "catalog" / "sources.toml"

    def test_the_checked_in_sources_file_loads(self):
        sources = bc.load_sources(self.SOURCES)
        self.assertEqual(len(sources["tool"]), 12)

    def test_every_tool_points_at_a_guide_that_exists(self):
        root = Path(__file__).resolve().parents[1]
        for tool in bc.load_sources(self.SOURCES)["tool"]:
            with self.subTest(tool=tool["id"]):
                self.assertTrue(tool.get("guide"), "no guide declared")
                self.assertTrue(
                    (root / tool["guide"]).is_file(),
                    f"{tool['guide']} does not exist",
                )

    def test_every_asset_pattern_compiles_and_is_anchored(self):
        import re as _re
        for tool in bc.load_sources(self.SOURCES)["tool"]:
            with self.subTest(tool=tool["id"]):
                _re.compile(tool["asset_pattern"])
                self.assertTrue(tool["asset_pattern"].startswith("^"))
                self.assertTrue(tool["asset_pattern"].endswith("$"))

    def test_no_pattern_would_pick_up_a_checksum_sidecar(self):
        # A pattern loose enough to match `<asset>.sha256` would make the build
        # ambiguous rather than wrong, but it would fail on release day instead
        # of now.
        for tool in bc.load_sources(self.SOURCES)["tool"]:
            with self.subTest(tool=tool["id"]):
                self.assertFalse(bc.is_checksum_asset(tool["asset_pattern"]))

    def test_elevate_and_admin_agree(self):
        for tool in bc.load_sources(self.SOURCES)["tool"]:
            with self.subTest(tool=tool["id"]):
                self.assertEqual(
                    bool(tool.get("requires", {}).get("admin")),
                    bool(tool.get("launch", {}).get("elevate")),
                    "a tool that requires admin must also declare elevate",
                )


class TestGeneratedCatalog(unittest.TestCase):
    """Checks on the catalog.json that is actually checked in.

    The hub ships this file embedded as its offline fallback, so a malformed one
    is not a stale artifact -- it is a hub that cannot show a library.
    """

    CATALOG = Path(__file__).resolve().parents[1] / "catalog" / "catalog.json"

    @classmethod
    def setUpClass(cls):
        if not cls.CATALOG.is_file():
            raise unittest.SkipTest("catalog.json has not been generated yet")
        cls.catalog = json.loads(cls.CATALOG.read_text(encoding="utf-8"))

    def test_schema_and_tool_count_match_sources(self):
        self.assertEqual(self.catalog["schema"], bc.SCHEMA_VERSION)
        sources = bc.load_sources(Path(__file__).resolve().parents[1] / "catalog" / "sources.toml")
        self.assertEqual(
            {t["id"] for t in self.catalog["tools"]},
            {t["id"] for t in sources["tool"]},
            "catalog.json and sources.toml disagree about which tools exist",
        )

    def test_every_artifact_is_hash_pinned(self):
        for tool in self.catalog["tools"]:
            with self.subTest(tool=tool["id"]):
                sha = tool["artifact"]["sha256"]
                self.assertRegex(sha, r"^[0-9a-f]{64}$")
                self.assertGreater(tool["artifact"]["size"], 0)
                self.assertTrue(tool["artifact"]["url"].startswith("https://"))

    def test_every_archive_declares_a_strip_prefix(self):
        for tool in self.catalog["tools"]:
            with self.subTest(tool=tool["id"]):
                self.assertIn("strip_prefix", tool["artifact"])

    def test_bare_downloads_declare_the_name_to_install_under(self):
        for tool in self.catalog["tools"]:
            if tool["artifact"]["kind"] in ("exe", "nsis"):
                with self.subTest(tool=tool["id"]):
                    self.assertEqual(
                        tool["artifact"]["install_as"], tool["launch"]["exe"]
                    )

    def test_versions_are_dotted_numbers_without_a_v(self):
        for tool in self.catalog["tools"]:
            with self.subTest(tool=tool["id"]):
                self.assertRegex(tool["version"], r"^[0-9]+(\.[0-9]+)*$")


class TestCatalogAssembly(unittest.TestCase):
    def test_only_filters_and_rejects_unknown_ids(self):
        archive = make_zip({"x.exe": b"MZ"})
        sources = {
            "schema": 1,
            "tool": [{
                "id": "a", "name": "A", "repo": "o/a",
                "asset_pattern": r"^x\.zip$", "kind": "zip",
                "launch": {"exe": "x.exe"},
            }],
        }
        fetcher = FakeFetcher(
            {"o/a": {"tag_name": "v1.0.0", "assets": [asset("x.zip", size=len(archive))]}},
            {"x.zip": archive},
        )
        catalog = bc.build_catalog(sources, fetcher, only=["a"], generated="2026-09-11T00:00:00Z")
        self.assertEqual(len(catalog["tools"]), 1)

        with self.assertRaises(CatalogError):
            bc.build_catalog(sources, fetcher, only=["nope"])

    def _two_tool_sources(self):
        return {
            "schema": 1,
            "tool": [
                {"id": "a", "name": "A", "repo": "o/a",
                 "asset_pattern": r"^x\.zip$", "kind": "zip",
                 "launch": {"exe": "x.exe"}},
                {"id": "b", "name": "B", "repo": "o/b",
                 "asset_pattern": r"^y\.zip$", "kind": "zip",
                 "launch": {"exe": "y.exe"}},
            ],
        }

    def _fetcher_for(self, *ids):
        releases, blobs = {}, {}
        for tool_id, name in (("a", "x"), ("b", "y")):
            if tool_id not in ids:
                continue
            archive = make_zip({f"{name}.exe": b"MZ"})
            releases[f"o/{tool_id}"] = {
                "tag_name": "v2.0.0",
                "assets": [asset(f"{name}.zip", size=len(archive))],
            }
            blobs[f"{name}.zip"] = archive
        return FakeFetcher(releases, blobs)

    def test_partial_rebuild_keeps_the_tools_it_did_not_rebuild(self):
        # The whole point: --only must not publish a catalog that silently drops
        # every tool it was not asked about.
        previous = {
            "schema": 1,
            "generated": "2026-09-01T00:00:00Z",
            "tools": [
                {"id": "a", "name": "A", "version": "1.0.0"},
                {"id": "b", "name": "B", "version": "1.0.0"},
            ],
            "warnings": ["b: something was odd last time"],
        }
        catalog = bc.build_catalog(
            self._two_tool_sources(), self._fetcher_for("a"),
            only=["a"], previous=previous, generated="2026-09-13T00:00:00Z",
        )

        self.assertEqual([t["id"] for t in catalog["tools"]], ["a", "b"])
        rebuilt, kept = catalog["tools"]
        self.assertEqual(rebuilt["version"], "2.0.0", "the named tool was rebuilt")
        self.assertEqual(kept, previous["tools"][1], "the other entry is carried over verbatim")
        self.assertIn("b: something was odd last time", catalog["warnings"])

    def test_partial_rebuild_never_fetches_the_tools_it_carries_over(self):
        previous = {
            "schema": 1, "generated": "2026-09-01T00:00:00Z",
            "tools": [{"id": "a"}, {"id": "b"}], "warnings": [],
        }
        fetcher = self._fetcher_for("a")
        bc.build_catalog(self._two_tool_sources(), fetcher, only=["a"], previous=previous)
        self.assertEqual(fetcher.release_calls, ["o/a"])

    def test_entries_stay_in_sources_order_regardless_of_previous_order(self):
        previous = {
            "schema": 1, "generated": "2026-09-01T00:00:00Z",
            "tools": [{"id": "b"}, {"id": "a"}], "warnings": [],
        }
        catalog = bc.build_catalog(
            self._two_tool_sources(), self._fetcher_for("b"), only=["b"], previous=previous,
        )
        self.assertEqual([t["id"] for t in catalog["tools"]], ["a", "b"])

    def test_partial_rebuild_with_no_previous_catalog_is_fatal(self):
        with self.assertRaises(CatalogError) as caught:
            bc.build_catalog(self._two_tool_sources(), self._fetcher_for("a"), only=["a"])
        self.assertIn("drop --only", str(caught.exception))

    def test_partial_rebuild_across_a_schema_change_is_fatal(self):
        previous = {"schema": 99, "tools": [{"id": "b"}], "warnings": []}
        with self.assertRaises(CatalogError):
            bc.build_catalog(
                self._two_tool_sources(), self._fetcher_for("a"),
                only=["a"], previous=previous,
            )

    def test_a_tool_missing_from_both_only_and_previous_is_fatal(self):
        # sources.toml gained a tool, someone rebuilt a different one. Omitting
        # the newcomer silently is the bug; failing loudly is the fix.
        previous = {"schema": 1, "tools": [{"id": "a"}], "warnings": []}
        with self.assertRaises(CatalogError) as caught:
            bc.build_catalog(
                self._two_tool_sources(), self._fetcher_for("a"),
                only=["a"], previous=previous,
            )
        self.assertIn("b", str(caught.exception))

    def test_full_rebuild_contains_every_tool_in_sources(self):
        sources = self._two_tool_sources()
        catalog = bc.build_catalog(sources, self._fetcher_for("a", "b"))
        self.assertEqual(
            [t["id"] for t in catalog["tools"]],
            [t["id"] for t in sources["tool"]],
        )

    def test_only_naming_every_tool_needs_no_previous_catalog(self):
        catalog = bc.build_catalog(
            self._two_tool_sources(), self._fetcher_for("a", "b"), only=["a", "b"],
        )
        self.assertEqual([t["id"] for t in catalog["tools"]], ["a", "b"])

    def test_serialization_is_stable_and_newline_terminated(self):
        catalog = {"schema": 1, "generated": "2026-09-11T00:00:00Z", "tools": [], "warnings": []}
        payload = bc.serialize(catalog)
        self.assertEqual(payload, bc.serialize(catalog))
        self.assertTrue(payload.endswith(b"\n"))
        self.assertNotIn(b"\r", payload)
        self.assertEqual(json.loads(payload)["schema"], 1)


class TestSourcesValidation(unittest.TestCase):
    def _write(self, tmp, text):
        path = Path(tmp) / "sources.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_wrong_schema_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "schema = 99\n[[tool]]\nid='a'\n")
            with self.assertRaises(CatalogError):
                bc.load_sources(path)

    def test_unknown_kind_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, (
                "schema = 1\n[[tool]]\nid='a'\nname='A'\nrepo='o/a'\n"
                "asset_pattern='^x$'\nkind='msi'\n"
            ))
            with self.assertRaises(CatalogError) as ctx:
                bc.load_sources(path)
            self.assertIn("msi", str(ctx.exception))

    def test_duplicate_ids_are_rejected(self):
        import tempfile
        entry = "[[tool]]\nid='a'\nname='A'\nrepo='o/a'\nasset_pattern='^x$'\nkind='zip'\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "schema = 1\n" + entry + entry)
            with self.assertRaises(CatalogError) as ctx:
                bc.load_sources(path)
            self.assertIn("duplicate", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
