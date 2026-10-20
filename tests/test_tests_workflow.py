"""Tests for `tests.yml`: the suite runs on pull requests, but not on bump or
catalog PRs.

A submodule bump PR changes one gitlink. `submodule-dispatch.yml` opens it as
github-actions, and a `pull_request` run on such a PR waits in
`action_required` for an approval, so the PR reads `unstable` and
`merge_submodule_pointer.py` (which merges only on `clean`) leaves it for a
person. That happened to #494 the day #492 added this workflow (#495).
`catalog.yml`'s catalog PR is opened the same way, and `merge_catalog_pr.py`
also merges only on `clean`, so #526 and #531 waited for a person too (#532).

So the workflow's `pull_request` trigger ignores every submodule path and the
catalog files `merge_catalog_pr.py` accepts, and the list must stay equal to
`.gitmodules` plus that script's FILES: a submodule or catalog file added
without its entry would bring the stalled PR back for that one alone.
"""

import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"

spec = importlib.util.spec_from_file_location("catalog_merge", ROOT / "tools/merge_catalog_pr.py")
catalog_merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog_merge)


def submodule_paths():
    text = (ROOT / ".gitmodules").read_text(encoding="utf-8")
    return sorted(re.findall(r"^\s*path\s*=\s*(\S+)\s*$", text, re.M))


def ignored_paths():
    """What `pull_request.paths-ignore` must list: every submodule path and
    every file a catalog PR may change."""
    return sorted(submodule_paths() + list(catalog_merge.FILES))


def trigger_block(text, event):
    """The indented block under `on:` -> `<event>:`, as text."""
    m = re.search(rf"^  {event}:\n((?:    .*\n|\s*\n)*)", text, re.M)
    return m.group(1) if m else None


class TestsWorkflowSkipsBumpPRs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_pull_request_ignores_exactly_the_submodule_and_catalog_paths(self):
        block = trigger_block(self.text, "pull_request")
        self.assertIsNotNone(block, "tests.yml has no pull_request trigger")
        self.assertIn("paths-ignore:", block)
        ignored = sorted(re.findall(r"^      - (\S+)\s*$", block, re.M))
        self.assertEqual(ignored, ignored_paths(),
                         "pull_request.paths-ignore must list every .gitmodules path and every "
                         "merge_catalog_pr.FILES entry, and only those")

    def test_pull_request_has_no_paths_filter_that_would_skip_real_changes(self):
        block = trigger_block(self.text, "pull_request")
        self.assertNotRegex(block, r"^    paths:", "a `paths:` allowlist would skip changes outside it")

    def test_push_to_main_still_runs_unfiltered(self):
        block = trigger_block(self.text, "push")
        self.assertIsNotNone(block, "tests.yml no longer runs on push")
        self.assertIn("branches: [main]", block)
        self.assertNotIn("paths", block, "the push to main must run the suite, bumps included")

    def test_parser_sees_a_dropped_entry(self):
        # Negative control: the same parse over a copy with one submodule line
        # or one catalog line removed must not match, so the equality above
        # can fail for either kind.
        for line in ("      - ForgePact\n", "      - catalog/catalog.json.minisig\n"):
            with self.subTest(line=line.strip()):
                mutated = self.text.replace(line, "", 1)
                self.assertNotEqual(mutated, self.text)
                ignored = sorted(re.findall(r"^      - (\S+)\s*$", trigger_block(mutated, "pull_request"), re.M))
                self.assertNotEqual(ignored, ignored_paths())


if __name__ == "__main__":
    unittest.main()
