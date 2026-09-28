"""Tests for tools/plan_lint.py's owner-question rules (workorder-speedup,
2026-09-27): every `owner:` item and every entry under `## Needs human
judgement`, in the plan or its sibling `<slug>-context.md`, carries
`default:` and `reversible: yes|no`, so the engine can proceed on a
reversible default instead of idling on a question.

Each finding has a failing fixture beside a passing control: a rule that
always fires would refuse every plan, and one that never fires would let a
question with no default park the pipeline again.
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import plan_lint  # noqa: E402


HEAD = """# x

## State
planning: complete
gates: none

## Acceptance criteria
- [ ] (reads `tools/plan_lint.py`) `py -3 tools/plan_lint.py x-plan.md` exits 0

## Steps

Preconditions: work in this checkout.
"""


def item(iid, *fields):
    """One `### Item:` with a file, a check and the given extra field lines."""
    return "\n".join([f"### Item: {iid}", f"files: `a/{iid}.py`", "checks: `grep a b` exits 0",
                      *fields, "", "1. Do it.", ""])


def plan(*items, judgement=None):
    text = HEAD + "\n" + "\n".join(items)
    if judgement is not None:
        text += "\n## Needs human judgement\n\n" + judgement + "\n"
    return text


LEGAL_ENTRY = """### Whether the listing may be quoted

The research read the drop script in Ghidra; the note could quote it.

default: {default}
reversible: {reversible}
"""


class OwnerLintTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="workorder_plan_lint_owner_")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.dir = Path(self._tmp)

    def lint(self, text, *extra, context=None, name="x"):
        path = self.dir / f"{name}-plan.md"
        path.write_text(text, encoding="utf-8")
        if context is not None:
            (self.dir / f"{name}-context.md").write_text(context, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = plan_lint.main([str(path), *extra])
        return rc, out.getvalue()

    def assertClean(self, rc, out):
        self.assertEqual(rc, 0, out)
        self.assertIn("0 finding(s)", out)

    # -- owner-no-default ----------------------------------------------------

    def test_fail_an_owner_item_with_no_default(self):
        rc, out = self.lint(plan(item("one", "owner: which flag?", "reversible: yes")))
        self.assertEqual(rc, 1, out)
        self.assertIn("item one: owner-no-default", out)
        self.assertNotIn("owner-no-reversible", out)

    def test_control_an_owner_item_with_a_default_passes(self):
        self.assertClean(*self.lint(plan(item("one", "owner: which flag?", "default: `--fast`",
                                              "reversible: yes"))))

    # -- owner-no-reversible -------------------------------------------------

    def test_fail_an_owner_item_with_no_reversible_or_a_value_that_is_not_yes_or_no(self):
        for fields in (["default: `--fast`"], ["default: `--fast`", "reversible: maybe"],
                       ["default: `--fast`", "reversible:"]):
            with self.subTest(fields=fields):
                rc, out = self.lint(plan(item("one", "owner: which flag?", *fields)))
                self.assertEqual(rc, 1, out)
                self.assertIn("item one: owner-no-reversible", out)

    def test_control_yes_or_no_with_an_explanation_passes(self):
        for default, value in (("`--fast`", "yes. Revert the item's commit."), ("none", "`no`"),
                               ("none", "No -- the save is gone once written"), ("`--fast`", "**yes**")):
            with self.subTest(value=value):
                self.assertClean(*self.lint(plan(item("one", "owner: which flag?", f"default: {default}",
                                                      f"reversible: {value}"))))

    # -- owner-reversible-no-default ----------------------------------------

    def test_fail_reversible_yes_with_a_default_of_none_or_empty(self):
        for default in ("none", "`none`", "None (waits on the capture)", ""):
            with self.subTest(default=default):
                rc, out = self.lint(plan(item("one", "owner: which flag?", f"default: {default}",
                                              "reversible: yes")))
                self.assertEqual(rc, 1, out)
                self.assertIn("item one: owner-reversible-no-default", out)

    def test_control_a_wait_on_data_that_does_not_exist_yet_is_no_with_none(self):
        # The bug batch's three owner items waited on a live capture: nothing
        # to default to, and nothing to undo.
        self.assertClean(*self.lint(plan(item("one", "owner: what does live capture 2 show?",
                                              "default: none", "reversible: no"))))

    # -- owner-legal-default -------------------------------------------------

    def test_fail_a_legal_entry_marked_reversible_or_given_a_default(self):
        for default, reversible in (("paraphrase it", "yes"), ("none", "yes"), ("quote two lines", "no")):
            with self.subTest(default=default, reversible=reversible):
                rc, out = self.lint(plan(judgement=LEGAL_ENTRY.format(default=default, reversible=reversible)))
                self.assertEqual(rc, 1, out)
                self.assertIn("judgement 1: owner-legal-default", out)

    def test_control_the_same_legal_entry_with_no_and_none_passes(self):
        self.assertClean(*self.lint(plan(judgement=LEGAL_ENTRY.format(default="none", reversible="no"))))

    def test_fail_a_legal_owner_item_and_pass_an_ordinary_one_with_the_same_fields(self):
        for question, want in (("may the note quote the decompiled body?", 1),
                               ("may the dnSpy output go in docs?", 1),
                               ("which colour for the badge?", 0)):
            with self.subTest(question=question):
                rc, out = self.lint(plan(item("one", f"owner: {question}", "default: yes, quote it",
                                              "reversible: yes")))
                self.assertEqual(rc, want, out)
                self.assertEqual("owner-legal-default" in out, bool(want), out)

    def test_ida_matches_only_as_a_word(self):
        # `\bIDA\b`: "idea" and "Idaho" are not the disassembler.
        rc, out = self.lint(plan(item("one", "owner: which idea for the Idaho badge?", "default: the first",
                                      "reversible: yes")))
        self.assertClean(rc, out)
        rc, out = self.lint(plan(item("one", "owner: may we keep the IDA export?", "default: none",
                                      "reversible: no")))
        self.assertClean(rc, out)
        rc, out = self.lint(plan(item("one", "owner: may we keep the IDA export?", "default: keep it",
                                      "reversible: no")))
        self.assertEqual(rc, 1, out)
        self.assertIn("owner-legal-default", out)

    # -- `## Needs human judgement` entries -----------------------------------

    def test_fail_subsection_entries_without_the_two_lines(self):
        judgement = ("### Which branch\n\nNo branch existed.\n\n"
                     "default: create one\nreversible: yes\n\n"
                     "### Which runner label\n\n- windows-latest\n- a self-hosted one\n")
        rc, out = self.lint(plan(judgement=judgement))
        self.assertEqual(rc, 1, out)
        # Only the second subsection; its bullets are part of it, not entries.
        self.assertIn('judgement 2: owner-no-default: "Which runner label"', out)
        self.assertIn("judgement 2: owner-no-reversible", out)
        self.assertNotIn("judgement 1:", out)
        self.assertNotIn("judgement 3:", out)

    def test_top_level_list_items_are_entries_when_there_are_no_subsections(self):
        judgement = ("Route these to the owner.\n\n"
                     "- **The release order.** Either tool can go first.\n"
                     "  default: ForgePact first\n"
                     "  reversible: yes\n"
                     "0. **The runner label.** Windows or self-hosted.\n"
                     "   More text about it.\n")
        rc, out = self.lint(plan(judgement=judgement))
        self.assertEqual(rc, 1, out)
        self.assertIn('judgement 2: owner-no-default: "**The runner label.**', out)
        self.assertNotIn("judgement 1:", out)

    def test_a_field_written_as_its_own_bullet_is_not_a_new_entry(self):
        judgement = "- Which flag should ship?\n- default: `--fast`\n- reversible: yes\n"
        self.assertClean(*self.lint(plan(judgement=judgement)))

    def test_a_default_that_wraps_onto_the_next_line_is_read_whole(self):
        found = plan_lint.judgement_entries(
            "## Needs human judgement\n\n### Rows\n\nWhich rows?\n\n"
            "default: one row for each laned round the report finds, named by the\n"
            "slug of its launch.\nreversible: yes. Deleting rows undoes it.\n\n## Log\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["default"],
                         "one row for each laned round the report finds, named by the slug of its launch.")
        self.assertIs(found[0]["reversible"], True)

    def test_prose_only_or_none_or_a_fenced_heading_is_no_entry(self):
        for judgement in ("none", "- none", "Nothing needs the owner here.",
                          "```md\n### Not an entry, inside a fence\n```"):
            with self.subTest(judgement=judgement):
                self.assertClean(*self.lint(plan(judgement=judgement)))

    def test_fail_an_entry_found_only_in_the_sibling_context_file(self):
        context = "# x context\n\n## Context the implementer needs\n\n### Where\ndocs/x.md\n\n" \
                  "## Needs human judgement\n\n### Which flag\n\nEither works.\n\n## Log\n### Plan\nwritten\n"
        rc, out = self.lint(plan(), context=context)
        self.assertEqual(rc, 1, out)
        self.assertIn('context judgement 1: owner-no-default: "Which flag"', out)
        self.assertIn("context judgement 1: owner-no-reversible", out)
        # Control: the same entry with both lines passes.
        fixed = context.replace("Either works.\n", "Either works.\n\ndefault: `--fast`\nreversible: yes\n")
        self.assertClean(*self.lint(plan(), context=fixed))

    def test_control_a_context_file_that_is_not_the_sibling_is_not_read(self):
        context = "## Needs human judgement\n\n### Which flag\n\nEither works.\n"
        (self.dir / "other-context.md").write_text(context, encoding="utf-8")
        self.assertClean(*self.lint(plan()))

    # -- no owner question at all ---------------------------------------------

    def test_a_plan_with_no_owner_and_no_judgement_gets_no_finding(self):
        rc, out = self.lint(plan(item("one"), item("two", "after: `one`")))
        self.assertClean(rc, out)
        self.assertNotIn("owner-", out)

    def test_default_and_reversible_beside_no_owner_are_not_required_or_checked(self):
        # Required only beside `owner:`; an item with neither passes, and so
        # does one that carries them without a question.
        self.assertClean(*self.lint(plan(item("one", "default: none", "reversible: yes"))))

    # -- `--items-json` ------------------------------------------------------

    def test_items_json_carries_default_and_reversible_on_every_item(self):
        rc, out = self.lint(plan(item("asked", "owner: which flag?", "default: `--fast`", "reversible: yes"),
                                 item("waits", "owner: what does the capture show?", "default: none",
                                      "reversible: no"),
                                 item("plain")), "--items-json")
        self.assertEqual(rc, 0, out)
        table = {it["id"]: it for it in json.loads(out.strip().splitlines()[-1])["items"]}
        self.assertEqual((table["asked"]["default"], table["asked"]["reversible"]), ("`--fast`", True))
        self.assertEqual((table["waits"]["default"], table["waits"]["reversible"]), ("none", False))
        self.assertEqual((table["plain"]["default"], table["plain"]["reversible"]), (None, None))
        self.assertEqual(table["asked"]["owner"], "which flag?")

    def test_items_json_is_withheld_while_an_owner_item_lacks_its_lines(self):
        rc, out = self.lint(plan(item("asked", "owner: which flag?")), "--items-json")
        self.assertEqual(rc, 1, out)
        self.assertNotIn('"items"', out)


if __name__ == "__main__":
    unittest.main()
