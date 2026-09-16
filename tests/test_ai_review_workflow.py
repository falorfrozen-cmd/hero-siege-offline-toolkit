"""Tests for the opt-in AI review workflow.

`ai-review.yml` reviews a pull request only when a person asks. Three things
are worth pinning, and "the YAML parses" is not one of them.

**That review stays opt-in.** Automation in this repository opens pull requests
by itself -- pointer bumps from `submodule-dispatch.yml`, catalog regeneration
from `catalog.yml` -- and a one-line SHA change has nothing to review. So the
workflow listens for a label being added and for a comment being created, and
never for a pull request being opened or pushed to.

**That an unrelated event cannot cancel a review in progress.** Every issue
comment and every label starts a run of this workflow, whether or not it is a
request. Concurrency was first declared at workflow level, where a run joins its
group when it is queued -- before any job's `if` is looked at -- so a plain
"thanks" comment joined `ai-review-<PR>` and, with `cancel-in-progress`, killed
the review that was running. Origin's review of PR #42 found it. The group is
now on the job and is only shared when the event is a real request; anything
else gets a group unique to its own run.

**That the two copies of the request predicate agree.** Neither `concurrency`
nor a job's `if` can read a value the other computes, so the predicate is
written out twice. If they drift, the group can go back to being shared by
events the `if` rejects -- the original bug, reintroduced by an edit to one
side. The comparison has a negative control, because a check that cannot fail
proves nothing.

**That the review is allowed to do its job.** `--allowedTools` replaces the
code-review command's own tool list rather than adding to it. The first version
listed only the inline-comment tool, so the review could neither read the pull
request (`gh pr view`, `gh pr diff`) nor post its "No issues found" summary
(`gh pr comment`); the job went green with five denied tool calls and nothing
on the PR (hub #56). The allow-list is now checked against every tool that
command declares, and the full result file is uploaded so the next denial is
visible rather than a bare count.

The file is read as text rather than parsed: CI runs this suite with
`python -m unittest discover -s tests` and installs nothing, so PyYAML is not
available there.
"""

import re
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github/workflows/ai-review.yml"


def workflow_text():
    return WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n")


def squash(text):
    return re.sub(r"\s+", " ", text).strip()


def folded_block(text, key, indent):
    """The body of a `key: >-` folded scalar at the given indentation."""
    match = re.search(
        rf"(?m)^{' ' * indent}{re.escape(key)}: >-\n((?:{' ' * (indent + 2)}.*\n|\s*\n)+)",
        text,
    )
    if match is None:
        return None
    return match.group(1)


def request_predicate(text):
    return folded_block(text, "if", 4)


def concurrency_group(text):
    return folded_block(text, "group", 6)


def predicate_shared_with_group(text):
    predicate = request_predicate(text)
    group = concurrency_group(text)
    if predicate is None or group is None:
        return False
    return squash(predicate) in squash(group)


class TriggersStayOptIn(unittest.TestCase):
    def test_listens_only_for_a_label_being_added(self):
        text = workflow_text()
        self.assertRegex(text, r"(?m)^  pull_request:\n    types: \[labeled\]\n")

    def test_listens_only_for_a_comment_being_created(self):
        text = workflow_text()
        self.assertRegex(text, r"(?m)^  issue_comment:\n    types: \[created\]\n")

    def test_never_reviews_on_open_or_push(self):
        # `synchronize` and `opened` are what would sweep in every automated
        # pointer and catalog pull request.
        text = workflow_text()
        for action in ("opened", "synchronize", "reopened"):
            self.assertNotRegex(text, rf"types: \[[^\]]*\b{action}\b")

    def test_request_predicate_names_the_label_and_the_comment(self):
        predicate = request_predicate(workflow_text())
        self.assertIsNotNone(predicate, "job `if: >-` block not found")
        self.assertIn("github.event.label.name == 'ai-review'", predicate)
        self.assertIn("startsWith(github.event.comment.body, '@claude review')", predicate)
        self.assertIn("github.event.issue.pull_request != null", predicate)


class UnrelatedEventsCannotCancelAReview(unittest.TestCase):
    def test_no_workflow_level_concurrency(self):
        # At column 0 a concurrency group applies to the run as it is queued,
        # before the job `if` has rejected an ordinary comment.
        self.assertNotRegex(workflow_text(), r"(?m)^concurrency:")

    def test_the_job_declares_concurrency_and_cancels_superseded_requests(self):
        text = workflow_text()
        self.assertRegex(text, r"(?m)^    concurrency:\n")
        self.assertRegex(text, r"(?m)^      cancel-in-progress: true$")

    def test_a_request_shares_the_pull_request_group(self):
        group = squash(concurrency_group(workflow_text()) or "")
        self.assertIn(
            "format('ai-review-{0}', github.event.pull_request.number || github.event.issue.number)",
            group,
        )

    def test_anything_else_gets_a_group_of_its_own(self):
        # `github.run_id` is unique per run, so this branch of the group can
        # never match -- and so never cancel -- another run.
        group = squash(concurrency_group(workflow_text()) or "")
        self.assertRegex(group, r"\|\| format\('ai-review-unrequested-\{0\}', github\.run_id\)")

    def test_the_request_branch_is_taken_first(self):
        # `a && shared || unique`: the shared name must be the `&&` arm. The
        # other order would give every request a unique group and every
        # unrelated event the shared one -- the bug, inverted, and still live.
        group = squash(concurrency_group(workflow_text()) or "")
        shared = group.find("format('ai-review-{0}'")
        unique = group.find("format('ai-review-unrequested-{0}'")
        self.assertGreater(shared, -1)
        self.assertGreater(unique, shared)
        self.assertIn(") && format('ai-review-{0}'", group)


class PredicateCopiesAgree(unittest.TestCase):
    def test_the_group_uses_exactly_the_job_predicate(self):
        self.assertTrue(
            predicate_shared_with_group(workflow_text()),
            "the concurrency group no longer contains the job's `if` predicate "
            "verbatim; edit both copies together",
        )

    def test_negative_control_drift_in_the_if_is_detected(self):
        # Change the label name only in the job `if` (the first occurrence)
        # and confirm the comparison notices. Without this, a helper that
        # always returned True would pass the test above.
        text = workflow_text()
        needle = "github.event.label.name == 'ai-review'"
        self.assertEqual(text.count(needle), 2, "expected the predicate twice")
        drifted = text.replace(needle, "github.event.label.name == 'ai-review-x'", 1)
        self.assertFalse(predicate_shared_with_group(drifted))

    def test_negative_control_drift_in_the_group_is_detected(self):
        text = workflow_text()
        needle = "startsWith(github.event.comment.body, '@claude review')"
        self.assertEqual(text.count(needle), 2, "expected the predicate twice")
        first = text.find(needle)
        second = text.find(needle, first + 1)
        drifted = (
            text[:second]
            + "startsWith(github.event.comment.body, '@claude please')"
            + text[second + len(needle):]
        )
        self.assertFalse(predicate_shared_with_group(drifted))


# The `allowed-tools` frontmatter of the code-review command the workflow runs
# (plugins/code-review/commands/code-review.md in anthropics/claude-code, read
# 2026-09-16). If the plugin adds a tool, add it here and to the workflow.
CODE_REVIEW_COMMAND_TOOLS = (
    "Bash(gh issue view:*)",
    "Bash(gh search:*)",
    "Bash(gh issue list:*)",
    "Bash(gh pr comment:*)",
    "Bash(gh pr diff:*)",
    "Bash(gh pr view:*)",
    "Bash(gh pr list:*)",
    "mcp__github_inline_comment__create_inline_comment",
)


def allowed_tools(text):
    match = re.search(r'--allowedTools "([^"]*)"', text)
    if match is None:
        return None
    return {tool.strip() for tool in match.group(1).split(",") if tool.strip()}


class TheReviewCanReadAndPost(unittest.TestCase):
    def test_allow_list_covers_every_tool_the_command_declares(self):
        tools = allowed_tools(workflow_text())
        self.assertIsNotNone(tools, "--allowedTools not found in claude_args")
        missing = [tool for tool in CODE_REVIEW_COMMAND_TOOLS if tool not in tools]
        self.assertEqual(missing, [], "denied at run time, silently: %s" % missing)

    def test_negative_control_the_original_allow_list_fails(self):
        # The shape that shipped first and posted nothing on hub #56.
        original = """claude_args: '--allowedTools "mcp__github_inline_comment__create_inline_comment"'"""
        tools = allowed_tools(original)
        self.assertEqual(tools, {"mcp__github_inline_comment__create_inline_comment"})
        self.assertTrue(any(tool not in tools for tool in CODE_REVIEW_COMMAND_TOOLS))

    def test_the_workflow_token_can_write_to_pull_requests(self):
        self.assertRegex(workflow_text(), r"(?m)^  pull-requests: write$")

    def test_the_full_result_is_kept_even_when_the_review_fails(self):
        text = workflow_text()
        step = re.search(
            r"(?ms)^      - name: Keep the run's full result\n(.*?)(?=^      - |\Z)", text
        )
        self.assertIsNotNone(step, "result upload step not found")
        body = step.group(1)
        self.assertIn("if: always()", body)
        self.assertIn("uses: actions/upload-artifact@", body)
        self.assertIn("path: ${{ runner.temp }}/claude-execution-output.json", body)


if __name__ == "__main__":
    unittest.main()
