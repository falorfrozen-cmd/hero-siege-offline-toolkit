"""Tests for `tests.yml`: the suite runs on pull requests, but not on bump PRs.

A submodule bump PR changes one gitlink. `submodule-dispatch.yml` opens it as
github-actions, and a `pull_request` run on such a PR waits in
`action_required` for an approval, so the PR reads `unstable` and
`merge_submodule_pointer.py` (which merges only on `clean`) leaves it for a
person. That happened to #494 the day #492 added this workflow (#495).

So the workflow's `pull_request` trigger ignores every submodule path, and the
list must stay equal to `.gitmodules`: a submodule added without its entry
would bring the stalled bump back for that module alone.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"


def submodule_paths():
    text = (ROOT / ".gitmodules").read_text(encoding="utf-8")
    return sorted(re.findall(r"^\s*path\s*=\s*(\S+)\s*$", text, re.M))


def trigger_block(text, event):
    """The indented block under `on:` -> `<event>:`, as text."""
    m = re.search(rf"^  {event}:\n((?:    .*\n|\s*\n)*)", text, re.M)
    return m.group(1) if m else None


class TestsWorkflowSkipsBumpPRs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_pull_request_ignores_exactly_the_submodule_paths(self):
        block = trigger_block(self.text, "pull_request")
        self.assertIsNotNone(block, "tests.yml has no pull_request trigger")
        self.assertIn("paths-ignore:", block)
        ignored = sorted(re.findall(r"^      - (\S+)\s*$", block, re.M))
        self.assertEqual(ignored, submodule_paths(),
                         "pull_request.paths-ignore must list every .gitmodules path, and only those")

    def test_pull_request_has_no_paths_filter_that_would_skip_real_changes(self):
        block = trigger_block(self.text, "pull_request")
        self.assertNotRegex(block, r"^    paths:", "a `paths:` allowlist would skip changes outside it")

    def test_push_to_main_still_runs_unfiltered(self):
        block = trigger_block(self.text, "push")
        self.assertIsNotNone(block, "tests.yml no longer runs on push")
        self.assertIn("branches: [main]", block)
        self.assertNotIn("paths", block, "the push to main must run the suite, bumps included")

    def test_parser_sees_a_dropped_entry(self):
        # Negative control: the same parse over a copy with ForgePact's line
        # removed must not match .gitmodules, so the equality above can fail.
        mutated = self.text.replace("      - ForgePact\n", "", 1)
        self.assertNotEqual(mutated, self.text)
        ignored = sorted(re.findall(r"^      - (\S+)\s*$", trigger_block(mutated, "pull_request"), re.M))
        self.assertNotEqual(ignored, submodule_paths())


if __name__ == "__main__":
    unittest.main()
