"""`.claude/skills/workorder/section.py` is how a verifier opens the one
context subsection a criterion cites -- and nothing else in that file, whose
`## Log` holds the implementer's reasoning the verifier must never see.

Measured 2026-09-18 (`forgepact-closure-names-current-game`): with no command
for a cited `###` heading, and no context path in its dispatch, the verifier
spent eight calls looking for the section and then read the whole 29KB file.
The audit caught it (R2) only after the fact; this is the instrument that
makes the right thing one command.

Driven as a subprocess, the way an agent runs it, on the bytes a CRLF worktree
actually writes. Each "finds it" test has a control beside it, per `AGENTS.md`
§ "Prove the Instrument Before Trusting a Negative Result": an extractor that
printed the whole file would pass every positive assertion here.

The last class pins the sentences in the agent and skill files that carry the
same lesson, so a later edit cannot drop one silently.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / ".claude" / "skills" / "workorder" / "section.py"

CONTEXT = "\r\n".join([
    "# Workorder title",
    "",
    "## Context the implementer needs",
    "",
    "intro line",
    "",
    "### Measured state (planner, 2026-09-18)",
    "measured-body",
    "",
    "### Syntax-only compile check",
    "compile-body → EXIT=0",
    "```markdown",
    "## Log",
    "### Not a real heading",
    "```",
    "after-the-fence",
    "",
    "### Merge order",
    "merge-body",
    "",
    "### Code and test sites (line numbers at `b56e626`; on `89abb26` ~1 line earlier)",
    "sites-body",
    "",
    "### Staging the `hub` guide",
    "staging-body",
    "",
    "## Needs human judgement",
    "human-body",
    "",
    "## Log",
    "",
    "### Round 0",
    "IMPLEMENTER-REASONING",
    "",
]) + "\n### Round 1\nlf-only-line\n"


class SectionTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="hstk-section-")
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "zz-context.md"
        self.path.write_bytes(CONTEXT.encode("utf-8"))

    def run_section(self, *args):
        result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True)
        return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


class TestExtraction(SectionTestCase):
    def test_a_cited_subsection_is_printed_and_stops_at_its_sibling(self):
        code, out, _ = self.run_section(str(self.path), "Syntax-only compile check")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("### Syntax-only compile check\n"))
        self.assertIn("compile-body → EXIT=0", out)
        self.assertIn("after-the-fence", out, "a fenced `## Log` must not end the section")
        self.assertNotIn("merge-body", out)
        self.assertNotIn("measured-body", out)

    def test_the_log_never_rides_along(self):
        for heading in ("Syntax-only compile check", "Merge order", "Context the implementer needs",
                        "Needs human judgement"):
            with self.subTest(heading=heading):
                code, out, _ = self.run_section(str(self.path), heading)
                self.assertEqual(code, 0)
                self.assertNotIn("IMPLEMENTER-REASONING", out)

    def test_a_level_two_section_brings_its_subsections(self):
        code, out, _ = self.run_section(str(self.path), "## Context the implementer needs")
        self.assertEqual(code, 0)
        for body in ("intro line", "measured-body", "compile-body", "merge-body"):
            self.assertIn(body, out)
        self.assertNotIn("human-body", out)

    def test_the_last_section_runs_to_the_end_of_a_mixed_eol_file(self):
        code, out, _ = self.run_section(str(self.path), "Round 1", "--log")
        self.assertEqual(code, 0)
        self.assertEqual(out, "### Round 1\nlf-only-line\n")

    def test_a_citation_as_planners_write_them_resolves_when_it_names_one_heading(self):
        # Both shapes are from the plan whose verifier prompted this tool:
        # `ctx: "Code and test sites"` for a heading with a long suffix, and a
        # backticked heading after a shell has eaten the backticks.
        for spelled, body in (("Code and test sites", "sites-body"), ("Staging the hub guide", "staging-body"),
                              ("Staging the `hub` guide", "staging-body")):
            with self.subTest(spelled=spelled):
                code, out, _ = self.run_section(str(self.path), spelled)
                self.assertEqual(code, 0)
                self.assertIn(body, out)
                self.assertNotIn("merge-body", out)

    def test_an_exact_match_beats_a_prefix_match(self):
        self.path.write_bytes(b"## Notes\none\n## Notes on merging\ntwo\n")
        code, out, _ = self.run_section(str(self.path), "Notes")
        self.assertEqual(code, 0)
        self.assertEqual(out, "## Notes\none\n")

    def test_the_exact_tier_wins_over_the_backtick_blind_one(self):
        # Without an exact tier, `Notes` would be ambiguous between these two.
        self.path.write_bytes(b"## `Notes`\none\n## Notes\ntwo\n")
        self.assertEqual(self.run_section(str(self.path), "Notes")[1], "## Notes\ntwo\n")
        self.assertEqual(self.run_section(str(self.path), "`Notes`")[1], "## `Notes`\none\n")

    def test_what_follows_the_log_under_a_level_one_heading_is_kept(self):
        self.path.write_bytes(b"# T\n## A\na\n## Log\nsecret\n## B\nb-body\n")
        code, out, _ = self.run_section(str(self.path), "# T")
        self.assertEqual(code, 0)
        self.assertIn("b-body", out)
        self.assertNotIn("secret", out)

    def test_a_level_one_heading_after_the_log_ends_the_log(self):
        self.path.write_bytes(b"## Log\nsecret\n# Appendix\n### x\nx-body\n")
        code, out, _ = self.run_section(str(self.path), "x")
        self.assertEqual(code, 0)
        self.assertEqual(out, "### x\nx-body\n")

    def test_a_fence_closes_only_on_its_own_character_with_nothing_after_it(self):
        self.path.write_bytes(b"## A\n```\n~~~\n## Q\n```\ntail\n## B\nb\n")
        self.assertEqual(self.run_section(str(self.path), "Q")[0], 3, "~~~ does not close a ``` fence")
        self.assertIn("tail", self.run_section(str(self.path), "A")[1])
        self.path.write_bytes(b"## A\n```\n``` not a close\n## Q\n```\ntail\n## B\nb\n")
        self.assertEqual(self.run_section(str(self.path), "Q")[0], 3, "a closing fence carries nothing after its run")
        self.assertIn("tail", self.run_section(str(self.path), "A")[1])

    def test_inline_triple_backtick_code_in_prose_is_not_a_fence(self):
        self.path.write_bytes(b"## A\n```cmd /c``` hangs here\nbody\n## Log\n### Round 0\nsecret\n")
        code, out, _ = self.run_section(str(self.path), "A")
        self.assertEqual(code, 0, "an inline code line must not read as an unclosed fence")
        self.assertIn("body", out)
        self.assertNotIn("secret", out)

    def test_a_bom_does_not_hide_the_first_heading(self):
        self.path.write_bytes(b"\xef\xbb\xbf## First\nbody\n## Second\nx\n")
        code, out, _ = self.run_section(str(self.path), "First")
        self.assertEqual(code, 0)
        self.assertEqual(out, "## First\nbody\n")

    def test_a_longer_fence_quoting_a_shorter_one_stays_open_until_its_own_run(self):
        self.path.write_bytes(b"## A\n````markdown\n```\n## Quoted\n```\n````\ntail-of-a\n## B\nb\n")
        code, out, _ = self.run_section(str(self.path), "A")
        self.assertEqual(code, 0)
        self.assertIn("tail-of-a", out)
        self.assertEqual(self.run_section(str(self.path), "Quoted")[0], 3)

    def test_the_citation_may_be_pasted_as_written(self):
        for spelled in ('§ "Merge order"', "### Merge order", "`Merge order`", "  Merge order  "):
            with self.subTest(spelled=spelled):
                code, out, _ = self.run_section(str(self.path), spelled)
                self.assertEqual(code, 0)
                self.assertIn("merge-body", out)

    def test_punctuation_in_a_heading_is_literal(self):
        code, out, _ = self.run_section(str(self.path), "Measured state (planner, 2026-09-18)")
        self.assertEqual(code, 0)
        self.assertIn("measured-body", out)
        self.assertNotIn("compile-body", out)


class TestRefusals(SectionTestCase):
    def test_no_such_heading_exits_3_and_lists_what_there_is(self):
        code, out, err = self.run_section(str(self.path), "only compile check")
        self.assertEqual(code, 3, "a suffix is not a citation")
        self.assertEqual(out, "")
        self.assertIn("### Syntax-only compile check", err)
        self.assertNotIn("Round 0", err, "the listing must not advertise the Log")
        self.assertNotIn("## Log", err)

    def test_the_log_is_refused_without_the_flag_and_printed_with_it(self):
        for heading in ("Log", "## Log", "Round 0", "Round"):
            with self.subTest(heading=heading):
                code, out, err = self.run_section(str(self.path), heading)
                self.assertEqual(code, 6, err)
                self.assertEqual(out, "")
        code, out, _ = self.run_section(str(self.path), "Round 0", "--log")
        self.assertEqual(code, 0)
        self.assertIn("IMPLEMENTER-REASONING", out)

    def test_a_whole_file_section_has_the_log_cut_out(self):
        code, out, _ = self.run_section(str(self.path), "# Workorder title")
        self.assertEqual(code, 0)
        self.assertIn("human-body", out)
        self.assertNotIn("IMPLEMENTER-REASONING", out)
        self.assertNotIn("lf-only-line", out)
        self.assertIn("IMPLEMENTER-REASONING", self.run_section(str(self.path), "# Workorder title", "--log")[1])

    def test_an_unclosed_fence_is_refused_not_printed_to_the_end_of_the_file(self):
        self.path.write_bytes(b"## A\n```\nnever closed\n## Log\n### Round 0\nIMPLEMENTER-REASONING\n")
        code, out, err = self.run_section(str(self.path), "A")
        self.assertEqual(code, 5)
        self.assertEqual(out, "")
        self.assertIn("line 2", err)

    def test_an_ambiguous_prefix_exits_4(self):
        self.path.write_bytes(b"## Decision 1: literals\na\n## Decision 2: branch\nb\n")
        self.assertEqual(self.run_section(str(self.path), "Decision")[0], 4)
        self.assertEqual(self.run_section(str(self.path), "Decision 1")[0], 0)

    def test_a_heading_inside_a_fence_is_not_a_heading(self):
        code, _, err = self.run_section(str(self.path), "Not a real heading")
        self.assertEqual(code, 3)
        self.assertNotIn("Not a real heading", err.split("this file has:")[1])

    def test_the_wrong_level_does_not_match(self):
        code, _, _ = self.run_section(str(self.path), "## Merge order")
        self.assertEqual(code, 3)

    def test_an_ambiguous_heading_exits_4_with_the_lines(self):
        self.path.write_bytes(b"## A\n### Notes\none\n## B\n### Notes\ntwo\n")
        code, out, err = self.run_section(str(self.path), "Notes")
        self.assertEqual(code, 4)
        self.assertEqual(out, "")
        self.assertIn("line 2", err)
        self.assertIn("line 5", err)

    def test_usage_and_unreadable_file_exit_2(self):
        self.assertEqual(self.run_section(str(self.path))[0], 2)
        self.assertEqual(self.run_section(str(self.path.with_name("gone.md")), "A")[0], 2)


class TestGuideReading(SectionTestCase):
    """`--toc` and `--grep`: reading a module guide whose lines are huge.

    Measured 2026-09-22: ForgePact's guide is 334KB and 23 of its lines hold
    128KB, so agents that read it "by section" with a 20-line window still
    pulled 45KB a read -- R3 failed in 8 of 22 workorder sessions."""

    GUIDE = "\n".join([
        "# Guide",
        "## Commands",
        "- `alpha on`: turns alpha on.",
        "- `beta on`: turns beta on,",
        "  and its continuation line mentions gamma.",
        "",
        "A paragraph about delta.",
        "- `huge`: " + ("filler " * 1500) + "NEEDLE" + (" filler" * 1500),
        "## Log",
        "- secret alpha",
    ])

    def setUp(self):
        super().setUp()
        self.guide = Path(self._tmp.name) / "instructions.md"
        self.guide.write_bytes(self.GUIDE.encode("utf-8"))

    def test_toc_gives_each_section_its_line_and_size_and_hides_the_log(self):
        code, out, _ = self.run_section(str(self.guide), "--toc")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"(?m)^\s+2\s+\d+\.\dKB  ## Commands$")
        self.assertNotIn("Log", out)

    def test_grep_prints_only_the_matching_items_with_their_lines(self):
        code, out, _ = self.run_section(str(self.guide), "Commands", "--grep", "gamma")
        self.assertEqual(code, 0)
        self.assertIn("-- line 4\n- `beta on`: turns beta on,\n  and its continuation line mentions gamma.", out)
        self.assertNotIn("alpha", out, "a non-matching item is not printed")
        self.assertNotIn("filler", out)

    def test_a_long_item_is_windowed_around_the_match(self):
        code, out, _ = self.run_section(str(self.guide), "Commands", "--grep", "needle")
        self.assertEqual(code, 0)
        self.assertIn("NEEDLE", out)
        self.assertIn("-- line 8 (", out)
        self.assertLess(len(out), 2000, "the 21K-character item must not print whole")

    def test_grep_never_reaches_into_the_log_and_says_when_nothing_matches(self):
        code, out, err = self.run_section(str(self.guide), "Guide", "--grep", "secret")
        self.assertEqual((code, out), (7, ""))
        self.assertIn("matches", err)
        self.assertEqual(self.run_section(str(self.guide), "Commands", "--grep", "(")[0], 2)


class TestThePipelineSaysSo(unittest.TestCase):
    """The lesson lives in four files an agent reads; each must keep saying it."""

    def read(self, *parts):
        return (REPO / ".claude").joinpath(*parts).read_bytes().decode("utf-8").replace("\r\n", "\n")

    def flat(self, *parts):
        return " ".join(self.read(*parts).split())

    def test_the_verifier_is_given_the_command_and_told_not_to_read_the_file_whole(self):
        text = self.flat("agents", "verifier.md")
        self.assertIn("py -3 .claude/skills/workorder/section.py", text)
        self.assertIn("Never `Read` or `cat` the context file whole", text)

    def test_the_implementer_treats_a_guard_refusal_as_a_plan_defect(self):
        text = self.flat("agents", "implementer.md")
        self.assertIn("is in the base repo checkout", text)
        self.assertIn("can only be carried out over there is a `PLAN-DEFECT`", text)
        self.assertIn("Never route the edit through `Bash`", text)

    def test_the_planner_does_not_target_another_checkout(self):
        text = self.flat("agents", "planner.md")
        self.assertIn("`Edit` and `Write` are refused outside the session's own checkout", text)

    def test_the_skill_stops_before_planning_against_another_checkout(self):
        text = self.flat("skills", "workorder", "SKILL.md")
        self.assertIn("### Step 0.25", text)
        self.assertIn("git rev-parse --show-toplevel", text)
        self.assertNotIn("escape hatch", text, "repoRoot from a worktree session is refused, not offered")


if __name__ == "__main__":
    unittest.main()
