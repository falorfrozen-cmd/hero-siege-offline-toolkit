"""Tests for the tag a hub release is being cut as.

The tag is typed into a box on the Actions tab, which makes this the one place
in the release path where a human hand reaches straight into CI. Everything
downstream trusts it: the tree is rewritten to match it, the commit is pushed to
`main`, and the release is built and signed against it. So the checks are here,
before any of that has happened, and they are the whole reason this is a tested
tool rather than four lines of shell.

Three refusals matter more than the rest.

A tag that already exists must be refused, because tagging into one that has a
release gives that tag two release objects, and
`releases/latest/download/latest.json` then resolves to whichever of them GitHub
calls latest. That is what hub-v0.1.1 did to every installed hub's update check.

A version *below* one already tagged must be refused. `releases/latest` would
point at it, and every hub asking what the newest version is would be told
something older than what it has.

Anything that is not three plain numbers must be refused, because the string
reaches a shell and a `git tag` either way. The validation is not politeness
about formatting.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import hub_tag  # noqa: E402


REPO = Path(__file__).resolve().parents[1]

# Roughly this repository's tag list, ragged on purpose: `hub-v0.1.4` sorts
# after `hub-v1.0.0` in any lexical order, so anything comparing these as
# strings has a wrong answer readily available.
TAGS = [
    "hub-v0.1.0",
    "hub-v0.1.4",
    "hub-v1.0.0",
    "hub-v1.0.1",
    "catalog",
    "v2.0.0",
]


class EitherSpellingIsAccepted(unittest.TestCase):
    """Whoever types it should not have to remember which half to include."""

    def test_the_full_tag(self):
        got = hub_tag.plan("hub-v1.0.2", TAGS, tree="1.0.1")
        self.assertEqual((got.version, got.tag), ("1.0.2", "hub-v1.0.2"))

    def test_the_bare_version(self):
        got = hub_tag.plan("1.0.2", TAGS, tree="1.0.1")
        self.assertEqual((got.version, got.tag), ("1.0.2", "hub-v1.0.2"))

    def test_surrounding_whitespace(self):
        got = hub_tag.plan("  hub-v1.0.2\n", TAGS, tree="1.0.1")
        self.assertEqual(got.tag, "hub-v1.0.2")


class TheTreeIsRewrittenOnlyWhenItDisagrees(unittest.TestCase):
    def test_a_version_the_tree_already_holds_needs_no_bump(self):
        got = hub_tag.plan("1.0.2", TAGS, tree="1.0.2")
        self.assertFalse(got.bump)

    def test_anything_else_needs_one(self):
        got = hub_tag.plan("1.1.0", TAGS, tree="1.0.1")
        self.assertTrue(got.bump, "the tag must point at a tree that agrees with it")


class ATakenTagIsRefused(unittest.TestCase):
    """Two release objects on one tag is how `latest.json` starts lying."""

    def test_an_existing_tag(self):
        with self.assertRaises(SystemExit) as caught:
            hub_tag.plan("hub-v1.0.1", TAGS, tree="1.0.1")
        self.assertIn("hub-v1.0.1", str(caught.exception))

    def test_the_bare_spelling_of_an_existing_tag(self):
        with self.assertRaises(SystemExit):
            hub_tag.plan("1.0.1", TAGS, tree="1.0.1")

    def test_refs_as_git_prints_them_count_as_taken(self):
        """`git ls-remote` gives `refs/tags/hub-v1.0.2` and a peeled `^{}` line."""
        refs = ["refs/tags/hub-v1.0.2", "refs/tags/hub-v1.0.2^{}"]
        with self.assertRaises(SystemExit):
            hub_tag.plan("1.0.2", refs, tree="1.0.1")

    def test_a_tag_belonging_to_another_scheme_does_not_block_it(self):
        """`v2.0.0` is not `hub-v2.0.0`; something else in this repo owns it."""
        got = hub_tag.plan("2.0.0", TAGS, tree="1.0.1")
        self.assertEqual(got.tag, "hub-v2.0.0")


class GoingBackwardsIsRefused(unittest.TestCase):
    """`releases/latest` would point at it, and every hub would be told it is newest."""

    def test_below_the_highest_tag(self):
        with self.assertRaises(SystemExit) as caught:
            hub_tag.plan("0.9.0", TAGS, tree="1.0.1")
        self.assertIn("hub-v1.0.1", str(caught.exception), "say what it is behind")

    def test_the_comparison_is_numeric_not_lexical(self):
        """`0.1.4` must not read as higher than `1.0.1` just because `0` > `1` never..."""
        with self.assertRaises(SystemExit):
            hub_tag.plan("0.2.0", TAGS, tree="1.0.1")

    def test_a_higher_version_is_fine(self):
        self.assertEqual(hub_tag.plan("1.0.2", TAGS, tree="1.0.1").tag, "hub-v1.0.2")

    def test_the_first_release_of_all_is_fine(self):
        self.assertEqual(hub_tag.plan("0.1.0", [], tree="0.1.0").tag, "hub-v0.1.0")


class MalformedInputIsRefused(unittest.TestCase):
    """The string reaches `git tag` and a shell; this is not about formatting."""

    def test_shapes_that_are_not_three_numbers(self):
        for bad in (
            "1.0",
            "1.0.0.0",
            "v1.0.2",
            "hub-1.0.2",
            "1.0.2-rc1",
            "latest",
            "",
            "   ",
            "1.0.2; rm -rf /",
            "$(whoami)",
            "hub-v1.0.2 --force",
            "../../etc/passwd",
        ):
            with self.assertRaises(SystemExit, msg=f"{bad!r} was accepted"):
                hub_tag.plan(bad, TAGS, tree="1.0.1")

    def test_the_refusal_says_what_was_wanted(self):
        with self.assertRaises(SystemExit) as caught:
            hub_tag.plan("latest", TAGS, tree="1.0.1")
        self.assertIn("1.2.3", str(caught.exception), "show the shape that works")


class TheOutputIsWhatAWorkflowReads(unittest.TestCase):
    """Three `key=value` lines, appended straight to `$GITHUB_OUTPUT`."""

    def run_it(self, *args, expect=0):
        done = subprocess.run(
            [sys.executable, str(REPO / "tools/hub_tag.py"), *args],
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, expect, done.stderr)
        return done

    def test_it_prints_three_pairs(self):
        out = self.run_it("--tag", "1.0.2", "--tree", "1.0.1", "--existing", *TAGS).stdout
        pairs = dict(line.split("=", 1) for line in out.strip().splitlines())
        self.assertEqual(set(pairs), {"version", "tag", "bump"})
        self.assertEqual(pairs["version"], "1.0.2")
        self.assertEqual(pairs["tag"], "hub-v1.0.2")
        self.assertEqual(pairs["bump"], "true")

    def test_bump_is_a_string_a_step_can_test(self):
        """`if: steps.x.outputs.bump == 'true'` is the only shape `if:` understands."""
        out = self.run_it("--tag", "1.0.2", "--tree", "1.0.2", "--existing", *TAGS).stdout
        pairs = dict(line.split("=", 1) for line in out.strip().splitlines())
        self.assertEqual(pairs["bump"], "false")

    def test_it_reads_the_tree_itself_when_not_told(self):
        """One version reader in the repository, and it is `cut_release.py`."""
        import cut_release

        out = self.run_it("--tag", "99.0.0").stdout
        pairs = dict(line.split("=", 1) for line in out.strip().splitlines())
        self.assertEqual(pairs["bump"], "true" if cut_release.current(REPO) != "99.0.0" else "false")

    def test_a_refusal_exits_nonzero_and_prints_no_pairs(self):
        done = self.run_it("--tag", "nonsense", "--tree", "1.0.1", expect=1)
        self.assertNotIn("version=", done.stdout)
        self.assertTrue(done.stderr.strip(), "a refusal must say why")


if __name__ == "__main__":
    unittest.main()
