"""ForgePact pins the `AurieCore.dll` this hub's `third_party/aurie/` series
builds (ForgePact #151).

ADR 0002's point applies here as it does to YYToolkit: the hub cannot change
what a player receives -- only ForgePact's own `tools/toolchain-pins.json`
does, and that pin drifts silently unless something reads both sides. This
module reads both:

  - the expected sha256 stated once in `third_party/aurie/README.md`
    ("How to build");
  - ForgePact's `modfiles_shipped/AurieCore.dll` pin, which must be a plain
    file pin (no zip member) on a release asset of THIS hub repository, at
    that sha256;
  - ForgePact's committed `aurie-modified/AurieCore-BUILD-INFO.json`, which
    must name the same DLL hash, the same upstream pin and the same series.

Upstream's own v2.0.2 release pin -- what ForgePact shipped before #151 -- is
the negative control: it must classify as drifted, in its real shape.

Hub CI checks out no submodules, so every test that reads `ForgePact/` skips,
saying why, when it is absent. The classifier controls never skip.
"""
import hashlib
import json
import re
import unittest
from pathlib import Path
from typing import Dict, Tuple

ROOT = Path(__file__).resolve().parents[1]
SERIES_DIR = ROOT / "third_party" / "aurie"
FORGEPACT = ROOT / "ForgePact"
PINS_PATH = FORGEPACT / "tools" / "toolchain-pins.json"
BUILD_INFO_PATH = FORGEPACT / "aurie-modified" / "AurieCore-BUILD-INFO.json"
PIN_DEST = "modfiles_shipped/AurieCore.dll"

#: A release asset of this hub repository; the library release's own tag is
#: checked separately so a pin at a YYToolkit release does not pass.
HUB_RELEASE_URL_MARKER = "github.com/falorfrozen-cmd/hero-siege-offline-toolkit/releases/download/"
AURIE_RELEASE_TAG = "aurie-v2.0.2-hs.1"

#: Upstream's unmodified v2.0.2 release, as ForgePact pinned it before #151.
UPSTREAM_ENTRY = {
    "dest": PIN_DEST,
    "url": "https://github.com/AurieFramework/Aurie/releases/download/v2.0.2/AurieCore.dll",
    "sha256": "18e3a1de980f487a6b3858b673d2030e96984dd96de3a047b43a263a5ba829ae",
    "provenance": "Aurie Framework release v2.0.2, unmodified",
}

#: "Expected result for `hs.1`: **968,704 bytes, sha256\n`<hex>`**" -- the one
#: place the series README states what a build of the pinned series hashes to.
EXPECTED_SHA = re.compile(
    r"Expected result for `[^`]+`:\s*\*\*[\d,]+ bytes, sha256\s*\n`([0-9a-f]{64})`\*\*")


def classify_aurie_pin(entry: Dict[str, object], series_sha: str) -> Tuple[str, str]:
    """"pinned" when `entry` is a plain file pin of this hub's Aurie library
    release at `series_sha`; otherwise "drifted", with the reason. Pure: no
    filesystem, so the controls below can feed it any shape."""
    sha = entry.get("sha256")
    url = str(entry.get("url", ""))
    if not sha:
        return "drifted", "the entry has no \"sha256\" key"
    if sha != series_sha:
        return "drifted", f"sha256 {sha} is not the series hash ({series_sha})"
    if "member" in entry or "archive_sha256" in entry:
        return "drifted", ("the entry is not a plain file pin (it carries \"member\" and/or "
                           "\"archive_sha256\")")
    if HUB_RELEASE_URL_MARKER not in url:
        return "drifted", f"url {url!r} is not a release asset of the hub repository"
    if f"/{AURIE_RELEASE_TAG}/AurieCore.dll" not in url:
        return "drifted", f"url {url!r} is not the {AURIE_RELEASE_TAG} release's AurieCore.dll"
    return "pinned", "plain file pin of the hub's Aurie library release at the series hash"


def read_series_sha() -> str:
    readme = (SERIES_DIR / "README.md").read_text(encoding="utf-8")
    match = EXPECTED_SHA.search(readme)
    if match is None:
        raise AssertionError("third_party/aurie/README.md's \"How to build\" no longer states "
                             "an expected sha256; there is nothing to check ForgePact's pin against")
    return match.group(1)


class ClassifierControls(unittest.TestCase):
    SERIES = "1" * 64
    PINNED = {
        "dest": PIN_DEST,
        "url": f"https://{HUB_RELEASE_URL_MARKER}{AURIE_RELEASE_TAG}/AurieCore.dll",
        "sha256": SERIES,
    }

    def classify(self, entry):
        return classify_aurie_pin(entry, self.SERIES)

    def test_the_pinned_shape_is_accepted(self):
        state, reason = self.classify(self.PINNED)
        self.assertEqual(state, "pinned", reason)

    def test_another_hash_is_drifted(self):
        state, reason = self.classify(dict(self.PINNED, sha256="2" * 64))
        self.assertEqual((state, "is not the series hash" in reason), ("drifted", True))

    def test_a_zip_member_form_is_drifted(self):
        entry = dict(self.PINNED, member="x/modfiles/AurieCore.dll", archive_sha256="3" * 64)
        state, reason = self.classify(entry)
        self.assertEqual((state, "not a plain file pin" in reason), ("drifted", True))

    def test_the_series_hash_off_the_hub_is_drifted(self):
        entry = dict(self.PINNED, url="https://github.com/falorfrozen-cmd/ForgePact/releases/"
                                      "download/v2.2.0/AurieCore.dll")
        state, reason = self.classify(entry)
        self.assertEqual((state, "not a release asset of the hub" in reason), ("drifted", True))

    def test_the_yytoolkit_library_release_is_drifted(self):
        entry = dict(self.PINNED, url=f"https://{HUB_RELEASE_URL_MARKER}yytoolkit-v4.0.1-hs.1/"
                                      "AurieCore.dll")
        state, reason = self.classify(entry)
        self.assertEqual((state, AURIE_RELEASE_TAG in reason), ("drifted", True))

    def test_a_missing_hash_is_drifted(self):
        entry = {k: v for k, v in self.PINNED.items() if k != "sha256"}
        self.assertEqual(self.classify(entry)[0], "drifted")

    def test_upstreams_real_release_pin_is_drifted(self):
        # The negative control in its real shape, against the real series hash.
        state, reason = classify_aurie_pin(UPSTREAM_ENTRY, read_series_sha())
        self.assertEqual(state, "drifted", reason)
        self.assertIn("is not the series hash", reason)

    def test_upstreams_hash_is_the_one_the_series_readme_names_as_upstream(self):
        # The control's hash is not invented: the series README records it as
        # the upstream DLL its marker check fails on.
        readme = (SERIES_DIR / "README.md").read_text(encoding="utf-8")
        self.assertIn(UPSTREAM_ENTRY["sha256"], readme)
        self.assertNotEqual(UPSTREAM_ENTRY["sha256"], read_series_sha())


class ForgePactCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PINS_PATH.is_file():
            raise unittest.SkipTest(
                f"{PINS_PATH.relative_to(ROOT).as_posix()} is not present -- ForgePact/ is not "
                f"checked out (hub CI runs without submodules)")
        cls.series_sha = read_series_sha()
        files = json.loads(PINS_PATH.read_text(encoding="utf-8"))["files"]
        cls.entries = [f for f in files if f.get("dest") == PIN_DEST]


class ForgePactPinsThisSeries(ForgePactCase):
    def test_exactly_one_aurie_core_pin(self):
        self.assertEqual(len(self.entries), 1,
                         f"expected one {PIN_DEST} entry in ForgePact/tools/toolchain-pins.json")

    def test_the_pin_is_the_series_build(self):
        state, reason = classify_aurie_pin(self.entries[0], self.series_sha)
        self.assertEqual(state, "pinned",
                         f"ForgePact's {PIN_DEST} pin is not this series' build: {reason}")

    def test_the_provenance_says_modified(self):
        provenance = str(self.entries[0].get("provenance", ""))
        self.assertIn("third_party/aurie", provenance)
        self.assertNotIn("unmodified", provenance)


class ForgePactBuildInfoDescribesThisSeries(ForgePactCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not BUILD_INFO_PATH.is_file():
            raise AssertionError(f"{BUILD_INFO_PATH.relative_to(ROOT).as_posix()} is missing; "
                                 f"ForgePact ships the modified DLL without its build record")
        cls.info = json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8"))
        cls.upstream = json.loads((SERIES_DIR / "upstream.json").read_text(encoding="utf-8"))

    def test_the_dll_hash_is_the_series_readmes(self):
        self.assertEqual(self.info["dll"]["name"], "AurieCore.dll")
        self.assertEqual(self.info["dll"]["sha256"], self.series_sha)

    def test_the_upstream_pin_is_this_series(self):
        for key in ("repo", "tag", "commit", "tree"):
            self.assertEqual(self.info["upstream"][key], self.upstream[key], key)

    def test_the_patches_are_this_series_in_order(self):
        series = [line.strip() for line in
                  (SERIES_DIR / "patches" / "series").read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.lstrip().startswith("#")]
        self.assertEqual([p["name"] for p in self.info["patches"]], series)
        for p in self.info["patches"]:
            data = (SERIES_DIR / "patches" / p["name"]).read_bytes()
            self.assertEqual(p["sha256"], hashlib.sha256(data).hexdigest(), p["name"])

    def test_it_is_a_clean_build_from_the_build_tool(self):
        self.assertEqual(self.info["tool"], "tools/build_aurie.py")
        self.assertIs(self.info["hub"]["patch_directory_dirty"], False)
        self.assertIs(self.info["live_gameplay_verified"], False)


if __name__ == "__main__":
    unittest.main()
