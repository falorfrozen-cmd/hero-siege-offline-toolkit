"""`tools/workorder_brief.py` prints one implementer's slice of a workorder:
the plan's frame, its own steps, the context subsections those steps cite,
and nothing from the `## Log` it was not asked for.

Measured 2026-10-03 (docs/agents/workorder-calibration.md, "Plan slices, the
amendment tier and symbol lookup"): implementers spent 5-20 reads on the plan
and context before their first edit, many of them whole files. The brief is
the one call that replaces them, so what it leaves out matters as much as what
it prints: a lane that sees another lane's steps may act on them, and a
verifier-shaped reader must not see Log text it was never asked for.

Driven as a subprocess on a fixture built in a temp directory, CRLF like the
repository's own workorders. Every positive assertion has a control beside it,
so a brief that printed both files whole would fail here.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tools" / "workorder_brief.py"


def crlf(*lines):
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


PLAN = crlf(
    "# Fixture workorder",
    "",
    "status: READY",
    "",
    "## State",
    "round: 1        phase: implement",
    "STATE-MARK",
    "",
    "## Goal",
    "",
    "GOAL-MARK",
    "",
    "## Out of scope",
    "",
    "- SCOPE-MARK",
    "",
    "## Acceptance criteria",
    "",
    "- [ ] `py -3 -c \"print('crit-one')\"` exits 0 (reads `tools/a.py`)",
    "- [ ] `py -3 -c \"print('crit-two')\"` prints `crit-two`",
    "  CRIT-TWO-CONTINUATION",
    "- [ ] crit-three by reading (ctx: \"Criteria-only notes\")",
    "",
    "## Steps",
    "",
    "PRECONDITION-MARK, for every lane (ctx: \"Shared hazards\").",
    "",
    "### Lane: alpha",
    "files: `tools/a.py`, `Sub/plugin/x.cpp`",
    "",
    "1. ALPHA-STEP per ctx: \"Alpha contract\", and ctx: \"Staging the hub guide\".",
    "2. ALPHA-STEP-TWO, again ctx: \"Alpha contract\", then ctx:",
    "   \"Code and test sites\" and ctx: \"No such heading\".",
    "",
    "### Lane: beta",
    "files: `docs/*.md`",
    "",
    "1. BETA-STEP per ctx: \"Beta contract\".",
    "",
    "### Join",
    "",
    "1. JOIN-STEP commits each lane.",
    "",
)

CONTEXT = crlf(
    "## Context the implementer needs",
    "",
    "### Alpha contract",
    "ALPHA-CTX-BODY → utf-8",
    "",
    "### Beta contract",
    "BETA-CTX-BODY",
    "",
    "### Shared hazards",
    "HAZARD-CTX-BODY",
    "```markdown",
    "### Not a heading inside a fence",
    "```",
    "",
    "### Staging the `hub` guide",
    "STAGING-CTX-BODY",
    "",
    "### Code and test sites (line numbers at `b56e626`)",
    "SITES-CTX-BODY",
    "",
    "### Criteria-only notes",
    "CRITERIA-CTX-BODY",
    "",
    "### Never cited",
    "UNCITED-CTX-BODY",
    "",
    "## Needs human judgement",
    "",
    "### Optional check",
    "JUDGEMENT-BODY",
    "",
    "## Log",
    "",
    "### Decisions",
    "DECISION-MARK",
    "",
    "### Plan",
    "planner: PLANNER-ENTRY",
    "",
    "### Round 0",
    "ROUND-ZERO-ENTRY",
    "",
    "### Round 1",
    "ROUND-ONE-ENTRY",
    "",
    "### Amendment 1",
    "AMENDMENT-ONE-ENTRY",
    "",
    "### Amendment 2",
    "AMENDMENT-TWO-ENTRY",
    "",
)

ITEMS_PLAN = crlf(
    "# Items fixture",
    "",
    "## Goal",
    "ITEMS-GOAL",
    "",
    "## Acceptance criteria",
    "",
    "- [ ] `py -3 -c \"print(1)\"` exits 0",
    "",
    "## Steps",
    "",
    "ITEMS-PRECONDITION",
    "",
    "### Item: ui-a — the first item",
    "files: `hub/src/a.ts`",
    "checks:",
    "- `node --test hub/a.test.mjs`",
    "",
    "1. ITEM-A-STEP per ctx: \"Item notes\".",
    "",
    "### Item: ui-b",
    "files: `hub/src/b/*.ts`",
    "checks: `node --test hub/b.test.mjs`",
    "",
    "1. ITEM-B-STEP.",
    "",
)

ITEMS_CONTEXT = crlf(
    "## Context the implementer needs",
    "",
    "### Item notes",
    "ITEM-NOTES-BODY",
    "",
    "## Log",
    "",
    "### Decisions",
    "",
    "### Round 0",
    "ITEMS-ROUND-ZERO",
    "",
)

LEGACY_PLAN = crlf(
    "# Legacy fixture",
    "",
    "## Goal",
    "LEGACY-GOAL",
    "",
    "## Acceptance criteria",
    "",
    "- [ ] `py -3 -c \"print(1)\"` exits 0",
    "",
    "## Steps",
    "",
    "1. LEGACY-STEP per ctx: \"Legacy notes\".",
    "",
    "## Context the implementer needs",
    "",
    "### Legacy notes",
    "LEGACY-NOTES-BODY",
    "",
    "### Legacy uncited",
    "LEGACY-UNCITED-BODY",
    "",
    "## Log",
    "",
    "### Decisions",
    "LEGACY-DECISION",
    "",
    "### Round 0",
    "LEGACY-ROUND-ZERO",
    "",
)

LOG_TEXT = ("PLANNER-ENTRY", "ROUND-ZERO-ENTRY", "ROUND-ONE-ENTRY", "AMENDMENT-ONE-ENTRY", "AMENDMENT-TWO-ENTRY")


class BriefTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="hstk-brief-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.wo = self.root / ".claude" / "workorders"
        self.wo.mkdir(parents=True)
        self.plan = self.wo / "zz-plan.md"
        self.plan.write_bytes(PLAN)
        (self.wo / "zz-context.md").write_bytes(CONTEXT)
        self.items_plan = self.wo / "yy-plan.md"
        self.items_plan.write_bytes(ITEMS_PLAN)
        (self.wo / "yy-context.md").write_bytes(ITEMS_CONTEXT)
        self.legacy = self.wo / "old-plan.md"
        self.legacy.write_bytes(LEGACY_PLAN)

    def brief(self, plan, *args):
        result = subprocess.run([sys.executable, str(SCRIPT), str(plan), *args], capture_output=True,
                                cwd=self.root)
        return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")

    def ok(self, plan, *args):
        code, out, err = self.brief(plan, *args)
        self.assertEqual(code, 0, err)
        return out

    def assertNoLog(self, out, *allowed):
        for text in LOG_TEXT:
            if text not in allowed:
                self.assertNotIn(text, out)


class TestTheFrame(BriefTestCase):
    def test_every_brief_carries_goal_scope_state_and_the_header(self):
        out = self.ok(self.plan, "--lane", "alpha")
        first = out.splitlines()[0]
        self.assertIn(self.plan.as_posix(), first)
        self.assertIn("--lane alpha", first)
        self.assertIn("KB", first)
        for mark in ("GOAL-MARK", "SCOPE-MARK", "STATE-MARK", "PRECONDITION-MARK"):
            self.assertIn(mark, out)
        self.assertLess(out.index("GOAL-MARK"), out.index("SCOPE-MARK"))
        self.assertLess(out.index("SCOPE-MARK"), out.index("STATE-MARK"))
        self.assertLess(out.index("STATE-MARK"), out.index("PRECONDITION-MARK"))
        self.assertLess(out.index("PRECONDITION-MARK"), out.index("ALPHA-STEP"))

    def test_decisions_are_printed_whole_and_nothing_else_from_the_log(self):
        out = self.ok(self.plan, "--lane", "alpha")
        self.assertIn("DECISION-MARK", out)
        self.assertNoLog(out)
        self.assertNotIn("JUDGEMENT-BODY", out)

    def test_an_empty_decisions_entry_prints_nothing(self):
        out = self.ok(self.items_plan, "--item", "ui-a")
        self.assertNotIn("### Decisions", out)
        self.assertNotIn("ITEMS-ROUND-ZERO", out)

    def test_the_footer_lists_what_was_left_out_and_names_the_full_files(self):
        out = self.ok(self.plan, "--lane", "alpha")
        footer = out[out.index("ALPHA-STEP-TWO"):]
        self.assertRegex(footer, r"### Never cited.*KB")
        self.assertRegex(footer, r"### Beta contract.*KB")
        # Forward slashes, on Windows too: the paths are pasted into Bash.
        self.assertIn(f"Full plan: {self.plan.as_posix()}", footer)
        self.assertIn(f"Full context: {(self.wo / 'zz-context.md').as_posix()}", footer)
        self.assertIn("section.py", footer)
        # A printed subsection is not listed as left out, and the Log's
        # headings are not context.
        self.assertNotRegex(footer, r"### Alpha contract.*KB")
        self.assertNotIn("### Round 0", out)

    def test_output_is_utf8_bytes(self):
        result = subprocess.run([sys.executable, str(SCRIPT), str(self.plan), "--lane", "alpha"],
                                capture_output=True, cwd=self.root)
        self.assertEqual(result.returncode, 0)
        self.assertIn("ALPHA-CTX-BODY → utf-8".encode("utf-8"), result.stdout)


class TestLanes(BriefTestCase):
    def test_a_lane_gets_its_own_steps_and_not_the_other_lanes(self):
        out = self.ok(self.plan, "--lane", "alpha")
        self.assertIn("### Lane: alpha", out)
        self.assertIn("ALPHA-STEP", out)
        self.assertNotIn("### Lane: beta", out)
        self.assertNotIn("BETA-STEP", out)
        self.assertNotIn("JOIN-STEP", out)
        self.assertNotIn("crit-one", out, "a lane brief carries no criteria unless asked")

        other = self.ok(self.plan, "--lane", "beta")
        self.assertIn("BETA-STEP", other)
        self.assertNotIn("ALPHA-STEP", other)

    def test_cited_context_resolves_on_every_tier_once_each(self):
        out = self.ok(self.plan, "--lane", "alpha")
        self.assertIn("### Alpha contract", out)
        self.assertEqual(out.count("ALPHA-CTX-BODY"), 1, "cited twice, printed once")
        self.assertIn("STAGING-CTX-BODY", out)  # backticks stripped
        self.assertIn("SITES-CTX-BODY", out)  # prefix, cited across a line break
        self.assertIn("HAZARD-CTX-BODY", out)  # cited by the preconditions
        self.assertIn("### Not a heading inside a fence", out)  # fenced text stays in its section
        self.assertIn('ctx not found: "No such heading"', out)
        # Controls: what alpha does not cite.
        self.assertNotIn("BETA-CTX-BODY", out)
        self.assertNotIn("UNCITED-CTX-BODY", out)
        self.assertNotIn("CRITERIA-CTX-BODY", out)

    def test_an_unknown_lane_exits_3(self):
        code, out, err = self.brief(self.plan, "--lane", "gamma")
        self.assertEqual(code, 3)
        self.assertIn("gamma", err)
        self.assertEqual(out, "")

    def test_the_join_gets_its_steps_the_lanes_file_sets_and_every_criterion(self):
        out = self.ok(self.plan, "--join")
        self.assertIn("JOIN-STEP", out)
        self.assertIn("alpha", out)
        self.assertIn("`tools/a.py`", out)
        self.assertIn("`docs/*.md`", out)
        for crit in ("crit-one", "crit-two", "CRIT-TWO-CONTINUATION", "crit-three"):
            self.assertIn(crit, out)
        self.assertIn("CRITERIA-CTX-BODY", out)  # cited by a printed criterion
        self.assertNotIn("ALPHA-STEP", out)
        self.assertNotIn("BETA-STEP", out)

    def test_a_plan_without_a_join_exits_3_for_join(self):
        code, _, _ = self.brief(self.items_plan, "--join")
        self.assertEqual(code, 3)


class TestRounds(BriefTestCase):
    def test_round_zero_is_every_step_and_criterion_and_no_round_entry(self):
        out = self.ok(self.plan, "--round", "0")
        for mark in ("ALPHA-STEP", "BETA-STEP", "JOIN-STEP", "crit-one", "crit-three"):
            self.assertIn(mark, out)
        self.assertEqual(out.count("PRECONDITION-MARK"), 1)
        self.assertNoLog(out)

    def test_a_later_round_adds_the_previous_and_its_own_round_entry_only(self):
        out = self.ok(self.plan, "--round", "1")
        self.assertIn("ROUND-ZERO-ENTRY", out)
        self.assertIn("ROUND-ONE-ENTRY", out)
        self.assertNoLog(out, "ROUND-ZERO-ENTRY", "ROUND-ONE-ENTRY")

        out = self.ok(self.plan, "--round", "2")
        self.assertIn("ROUND-ONE-ENTRY", out)
        self.assertNoLog(out, "ROUND-ONE-ENTRY")

    def test_amended_adds_the_newest_amendment_only(self):
        out = self.ok(self.plan, "--round", "1", "--amended")
        self.assertIn("AMENDMENT-TWO-ENTRY", out)
        self.assertNotIn("AMENDMENT-ONE-ENTRY", out)
        self.assertNotIn("PLANNER-ENTRY", out)


class TestItemsPathsCriteria(BriefTestCase):
    def test_an_item_gets_its_section_with_files_and_checks(self):
        out = self.ok(self.items_plan, "--item", "ui-a")
        self.assertIn("ITEM-A-STEP", out)
        self.assertIn("`hub/src/a.ts`", out)
        self.assertIn("node --test hub/a.test.mjs", out)
        self.assertIn("ITEM-NOTES-BODY", out)
        self.assertIn("ITEMS-PRECONDITION", out)
        self.assertNotIn("ITEM-B-STEP", out)
        self.assertNotIn("hub/b.test.mjs", out)

    def test_an_unknown_item_exits_3(self):
        self.assertEqual(self.brief(self.items_plan, "--item", "nosuch")[0], 3)
        self.assertEqual(self.brief(self.plan, "--item", "ui-a")[0], 3)

    def test_paths_select_every_section_whose_file_set_covers_them(self):
        out = self.ok(self.items_plan, "--paths", "hub/src/b/deep/c.ts")
        self.assertIn("ITEM-B-STEP", out)
        self.assertNotIn("ITEM-A-STEP", out)

        out = self.ok(self.plan, "--paths", "docs/x.md,tools/a.py")
        self.assertIn("BETA-STEP", out)
        self.assertIn("ALPHA-STEP", out)
        self.assertNotIn("JOIN-STEP", out)

    def test_paths_no_section_covers_say_so_and_list_the_steps_headings(self):
        out = self.ok(self.plan, "--paths", "elsewhere/z.py")
        self.assertIn("no lane or item covers", out)
        self.assertIn("### Lane: alpha", out)
        self.assertIn("### Join", out)
        self.assertNotIn("ALPHA-STEP", out)
        self.assertNotIn("JOIN-STEP", out)

    def test_criteria_alone_are_preconditions_plus_those_criteria(self):
        out = self.ok(self.plan, "--criteria", "2")
        self.assertIn("PRECONDITION-MARK", out)
        self.assertIn("crit-two", out)
        self.assertIn("CRIT-TWO-CONTINUATION", out)
        self.assertNotIn("crit-one", out)
        self.assertNotIn("crit-three", out)
        self.assertNotIn("ALPHA-STEP", out)
        self.assertRegex(out, r"(?m)^2\. ")

    def test_criteria_numbering_is_run_criterias(self):
        sys.path.insert(0, str(REPO / "tools"))
        import run_criteria
        items = run_criteria.criteria(PLAN.decode("utf-8"))
        out = self.ok(self.plan, "--criteria", "3")
        self.assertIn(items[2].splitlines()[0], out)

    def test_criteria_next_to_a_lane_add_them(self):
        out = self.ok(self.plan, "--lane", "beta", "--criteria", "1,3")
        self.assertIn("BETA-STEP", out)
        self.assertIn("crit-one", out)
        self.assertIn("CRITERIA-CTX-BODY", out)
        self.assertNotIn("crit-two", out)
        self.assertNotIn("ALPHA-STEP", out)

    def test_a_criterion_that_does_not_exist_exits_3(self):
        self.assertEqual(self.brief(self.plan, "--criteria", "9")[0], 3)
        self.assertEqual(self.brief(self.plan, "--criteria", "0")[0], 3)


class TestDiffPointers(BriefTestCase):
    def write_snapshot(self, round_, heads):
        snap = self.wo / ".rounds" / "zz"
        snap.mkdir(parents=True, exist_ok=True)
        (snap / f"round-{round_}.json").write_text(
            json.dumps({"version": 2, "heads": heads, "files": {}}), encoding="utf-8")

    def test_since_round_prints_one_diff_per_repo_for_the_file_set(self):
        self.write_snapshot(0, {"": "aaa111", "Sub": "bbb222"})
        out = self.ok(self.plan, "--lane", "alpha", "--since-round", "0")
        self.assertIn('git diff aaa111 -- "tools/a.py"', out)
        self.assertIn('git -C Sub diff bbb222 -- "plugin/x.cpp"', out)
        self.assertNotIn('"Sub/plugin/x.cpp"', out)
        self.assertNotIn("docs/*.md", out[out.index("git diff"):])

    def test_no_file_set_prints_a_stat(self):
        out = self.ok(self.plan, "--criteria", "1", "--base", "ccc333")
        self.assertIn("git diff ccc333 --stat", out)

    def test_base_flags_name_the_hub_and_submodules(self):
        out = self.ok(self.plan, "--lane", "alpha", "--base", ".=ddd444", "--base", "Sub=eee555")
        self.assertIn('git diff ddd444 -- "tools/a.py"', out)
        self.assertIn('git -C Sub diff eee555 -- "plugin/x.cpp"', out)

    def test_an_unreadable_snapshot_prints_one_line_and_no_pointers(self):
        out = self.ok(self.plan, "--lane", "alpha", "--since-round", "4")
        self.assertIn("round-4.json", out)
        self.assertNotIn("git diff", out)

    def test_no_base_no_pointers(self):
        self.assertNotIn("git diff", self.ok(self.plan, "--lane", "alpha"))


class TestContextFile(BriefTestCase):
    def test_a_legacy_plan_is_its_own_context(self):
        out = self.ok(self.legacy, "--round", "0")
        self.assertIn("LEGACY-STEP", out)
        self.assertIn("LEGACY-NOTES-BODY", out)
        self.assertIn("LEGACY-DECISION", out)
        self.assertNotIn("LEGACY-ROUND-ZERO", out)
        self.assertNotIn("LEGACY-UNCITED-BODY", out)
        self.assertRegex(out, r"### Legacy uncited.*KB")

    def test_context_flag_overrides_the_sibling(self):
        other = self.root / "other-context.md"
        other.write_bytes(crlf("## Context the implementer needs", "", "### Alpha contract", "OVERRIDE-BODY"))
        out = self.ok(self.plan, "--lane", "alpha", "--context", str(other))
        self.assertIn("OVERRIDE-BODY", out)
        self.assertNotIn("ALPHA-CTX-BODY", out)
        self.assertNotIn("DECISION-MARK", out)


class TestErrors(BriefTestCase):
    def test_usage_errors_exit_2(self):
        self.assertEqual(self.brief(self.plan)[0], 2)
        self.assertEqual(self.brief(self.plan, "--lane", "alpha", "--join")[0], 2)
        self.assertEqual(self.brief(self.wo / "missing-plan.md", "--round", "0")[0], 2)
        self.assertEqual(self.brief(self.plan, "--criteria", "x")[0], 2)

    def test_an_unclosed_fence_exits_5(self):
        self.plan.write_bytes(PLAN + crlf("```", "### Lane: hidden"))
        code, out, err = self.brief(self.plan, "--lane", "alpha")
        self.assertEqual(code, 5)
        self.assertIn("never closed", err)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
