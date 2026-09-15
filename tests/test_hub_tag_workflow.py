"""Tests for the workflow that cuts a hub release as a typed tag.

`hub-tag.yml` is a `git tag` wrapped in guards, and the guards are the point:
once a tag is pushed and a release is built against it, nothing here is undone
from the repository's side. Five things are worth pinning, and none of them is
"the YAML parses".

**That the typed tag is checked before anything acts on it.** It is typed into a
box on the Actions tab and everything downstream trusts it, so the shape, the
collision and the downgrade checks all belong in `tools/hub_tag.py` -- which has
tests -- and the workflow's job is to stop when that refuses.

**That the typed string never reaches a shell as text.** It arrives through
`env:` and is quoted at the point of use. Interpolated into a `run:` line
instead, `${{ inputs.tag }}` is whatever the person typed, executed.

**That the bump reaches `main` before the tag exists.** A tag on a commit that
was never pushed is the hub-v0.1.1 shape of broken: reachable from nothing, and
built from a tree nobody can check out.

**The ref the release is dispatched against.** Every guard inside
`hub-release.yml` is written `if: startsWith(github.ref, 'refs/tags/hub-v')`.
Dispatch it against `main` and it still builds, still signs, still publishes --
with the version check, the duplicate-release guard and the draft notice all
silently skipped. That is this repository's own recurring bug shape: a thing
that reports armed and is not.

**That nothing here publishes.** The draft gate in `hub-release.yml` is
deliberate, and automating up to it is the entire scope of this workflow.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import hub_tag  # noqa: E402


REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github/workflows/hub-tag.yml"
RELEASE_WORKFLOW = REPO / ".github/workflows/hub-release.yml"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def run_lines(text: str) -> list[str]:
    """Every line inside a `run:` block, which is what a shell will execute."""
    lines = []
    inside = False
    indent = 0
    for line in text.splitlines():
        if re.match(r"^\s*run: \|", line):
            inside = True
            indent = len(line) - len(line.lstrip())
            continue
        if re.match(r"^\s*run: ", line):
            lines.append(line.split("run: ", 1)[1])
            continue
        if inside:
            if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                inside = False
            else:
                lines.append(line)
    return lines


class TheWorkflowExists(unittest.TestCase):
    def test_it_is_there(self):
        self.assertTrue(WORKFLOW.exists(), f"{WORKFLOW} is missing")


class ItIsRunByHandWithATag(unittest.TestCase):
    def test_it_takes_a_tag_input(self):
        self.assertTrue(
            re.search(r"(?m)^\s{6}tag:\s*$", workflow_text()),
            "the whole point is typing the tag to release as",
        )

    def test_the_tag_is_required(self):
        self.assertTrue(
            re.search(r"(?m)^\s*required: true\s*$", workflow_text()),
            "an empty tag would tag whatever the tree happens to say",
        )

    def test_the_description_shows_the_shape(self):
        """Whoever runs it should not have to read the validator to guess."""
        described = re.search(r"(?m)^\s*description: '([^']*)'", workflow_text())
        self.assertIsNotNone(described, "the input has no description")
        self.assertIn("1.0.2", described.group(1))

    def test_nothing_else_triggers_it(self):
        text = workflow_text()
        for trigger in ("push:", "pull_request:", "schedule:", "repository_dispatch:"):
            self.assertFalse(
                re.search(rf"(?m)^\s{{2}}{re.escape(trigger)}", text),
                f"{trigger} would cut releases nobody asked for",
            )

    def test_it_refuses_to_run_off_main(self):
        """A branch's tree is not what a release should ship."""
        self.assertTrue(
            re.search(r'\[ "\$BRANCH" != "main" \]', workflow_text()),
            "a release cut from a feature branch would push that branch to main",
        )


class TheTypedTagIsHandledSafely(unittest.TestCase):
    def test_the_input_is_checked_by_the_tested_tool(self):
        self.assertTrue(
            "tools/hub_tag.py" in workflow_text(),
            "the shape, collision and downgrade checks belong in the tool with tests",
        )

    def test_the_run_block_reader_actually_reads_them(self):
        """A positive control for the test below.

        `run_lines` returning nothing would pass the injection test on every
        workflow ever written, including one that interpolated the input into
        every line. An instrument that cannot produce a hit anywhere has not
        measured the thing it was pointed at.
        """
        lines = run_lines(workflow_text())
        self.assertGreater(len(lines), 20, "the run blocks are not being read")
        self.assertTrue(
            any("gh workflow run" in line for line in lines),
            "a command known to be in a run block was not found",
        )

    def test_the_input_never_appears_inside_a_run_block(self):
        """`${{ inputs.tag }}` in a `run:` line is whatever was typed, executed."""
        for line in run_lines(workflow_text()):
            self.assertNotIn(
                "inputs.tag",
                line,
                f"the typed tag is interpolated into a shell here: {line.strip()!r}",
            )

    def test_the_input_is_passed_through_the_environment(self):
        self.assertTrue(
            re.search(r"TAG_INPUT: \$\{\{ inputs\.tag \}\}", workflow_text()),
            "pass the typed tag through env:, not into the command line",
        )

    def test_a_refusal_is_not_swallowed_by_a_pipe(self):
        """The validator's exit code has to survive to fail the step.

        GitHub runs `run:` blocks as `bash -e {0}` -- no `pipefail`. So
        `hub_tag.py ... | tee -a "$GITHUB_OUTPUT"` exits with tee's status,
        which is 0, and a refused tag would sail on into the bump, the push and
        the tag with no version behind it.
        """
        for line in run_lines(workflow_text()):
            if "hub_tag.py" in line and "|" in line:
                self.assertTrue(
                    "pipefail" in workflow_text(),
                    f"the validator's exit status is discarded here: {line.strip()!r}",
                )

    def test_the_workflow_parses_no_manifest_of_its_own(self):
        # `jq -r .version`, a `grep` for `"version"`, a `node -e` reading
        # package.json: each is a second answer to a question that already has
        # one, and each would keep working right up until the version moved.
        for reader in ("jq -r .version", "jq .version", '"version":'):
            self.assertFalse(
                reader in workflow_text(),
                f"{reader!r} is a second version reader; ask cut_release.py",
            )

    def test_the_tree_is_checked_against_the_chosen_version(self):
        """`hub-release.yml` will check this too, twelve minutes later."""
        self.assertTrue(
            re.search(r"cut_release\.py --check --expect", workflow_text()),
            "the tag must point at a tree whose six fields already agree",
        )


class TheBumpReachesMainBeforeTheTag(unittest.TestCase):
    def test_the_bump_only_happens_when_the_tree_disagrees(self):
        self.assertTrue(
            re.search(r"if: steps\.plan\.outputs\.bump == 'true'", workflow_text()),
            "rewriting a tree that already matches would commit nothing, noisily",
        )

    def test_main_is_pushed_before_the_tag_is_created(self):
        text = workflow_text()
        pushed = text.find("git push origin HEAD:main")
        tagged = text.find("git tag -a")
        self.assertNotEqual(pushed, -1, "the bump is never pushed to main")
        self.assertNotEqual(tagged, -1, "nothing is tagged")
        self.assertLess(
            pushed,
            tagged,
            "a tag on a commit main never got is reachable from nothing",
        )

    def test_the_bump_is_committed_with_every_rewritten_file(self):
        self.assertTrue(
            re.search(r"git commit --all", workflow_text()),
            "cut_release.py writes five files; committing some half-bumps main",
        )


class TheReleaseIsDispatchedAgainstTheTag(unittest.TestCase):
    """Dispatch against a branch and every guard in the release silently skips."""

    def test_the_dispatch_names_the_tag_ref(self):
        text = workflow_text()
        self.assertTrue(
            re.search(r"gh workflow run hub-release\.yml[^\n]*--ref \"?\$(\{)?TAG", text),
            "the release must be dispatched against the tag it just pushed",
        )

    def test_the_dispatch_never_names_a_branch(self):
        text = workflow_text()
        for branch_ref in ("--ref main", "--ref ${{ github.ref }}", "--ref $GITHUB_REF"):
            self.assertFalse(branch_ref in text, f"{branch_ref} skips every tag guard")

    def test_the_tag_is_the_shape_the_release_triggers_on(self):
        """`hub-release.yml` filters on `hub-v*`; a tag it ignores builds nothing."""
        self.assertEqual(
            hub_tag.PREFIX,
            "hub-v",
            "the tagger and the release workflow must agree on the prefix",
        )
        self.assertTrue(
            "- 'hub-v*'" in RELEASE_WORKFLOW.read_text(encoding="utf-8"),
            "hub-release.yml no longer triggers on hub-v* tags",
        )

    def test_the_release_is_asked_to_publish_not_dry_run(self):
        self.assertTrue(
            re.search(r"gh workflow run hub-release\.yml[^\n]*-f dry_run=false", workflow_text()),
            "a dispatch without dry_run=false uploads nothing",
        )


class ThePermissionsCoverWhatItDoes(unittest.TestCase):
    """Both are runtime failures mid-release, which is the worst time to find them."""

    def test_it_may_push_a_commit_and_a_tag(self):
        self.assertTrue(
            re.search(r"(?m)^\s*contents: write\s*$", workflow_text()),
            "without contents: write the bump and the tag are both a 403",
        )

    def test_it_may_start_the_release(self):
        # `gh workflow run` without this is a 403 from a job that already
        # pushed the tag, leaving a tag with no build behind it.
        self.assertTrue(
            re.search(r"(?m)^\s*actions: write\s*$", workflow_text()),
            "without actions: write the release is never started",
        )


class NothingHerePublishes(unittest.TestCase):
    """The draft gate is the deliberate stopping point."""

    def test_no_step_takes_the_release_out_of_draft(self):
        text = workflow_text()
        for publish in ("--draft=false", "gh release edit", "gh release create"):
            self.assertFalse(
                publish in text,
                f"{publish!r} publishes; this workflow stops at the draft",
            )


if __name__ == "__main__":
    unittest.main()
