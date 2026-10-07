"""Tests for tools/plan_lint.py's Ghidra MCP rules (hub #468, 2026-10-07): a
plan that researches a game mechanism records its Ghidra MCP check on a
`ghidra mcp: used|unavailable|skipped -- <...>` line of `## State`.

A plan is mechanism research when the plan or its sibling `<slug>-context.md`
has a `### Live procedure` heading, a `route tokens:` State line with a
backticked token, the text `analyzeHeadless`, `DecompileTo`, `decomp_index.py
has` or `mcp__ghidra__`, or a `ForgePact/docs/<name>-research.md` path.

Each trigger has a failing fixture beside a passing control: a rule that
always fires would refuse every plan, and one that never fires would let a
mechanism plan skip the decompiler check that would have answered it.
"""

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import plan_lint  # noqa: E402


def plan(state=(), body=""):
    """A minimal clean plan with extra `## State` lines and extra body text."""
    return "\n".join([
        "# x", "", "## State", "planning: complete", "gates: none", *state, "",
        "## Acceptance criteria",
        "- [ ] (reads `tools/plan_lint.py`) `py -3 tools/plan_lint.py x-plan.md` exits 0", "",
        "## Steps", "", "1. Do it.", "", body, "",
    ])


# Each trigger as plan text: (name, state lines, body text).
TRIGGERS = {
    "live-procedure": ((), "### Live procedure\n\n1. Launch the game."),
    "route-tokens": (("route tokens: `save-route: proven` or `save-route: not-observed`",), ""),
    "analyzeHeadless": ((), "Run `analyzeHeadless` on the project."),
    "DecompileTo": ((), "Read the body with DecompileTo.java."),
    "decomp_index": ((), "First `py -3 tools/decomp_index.py has SaveStash`."),
    "mcp__ghidra__": ((), "Ask `mcp__ghidra__decompile_function` for it."),
    "research-doc": ((), "The facts are in `ForgePact/docs/pet-quest-research.md`."),
}


class GhidraLintTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="workorder_plan_lint_ghidra_")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.dir = Path(self._tmp)

    def lint(self, text, context=None, name="x"):
        path = self.dir / f"{name}-plan.md"
        path.write_text(text, encoding="utf-8")
        if context is not None:
            (self.dir / f"{name}-context.md").write_text(context, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = plan_lint.main([str(path)])
        return rc, out.getvalue()

    def rules(self, out):
        return [line.split(": ")[2] for line in out.splitlines() if ": plan: " in line]

    def test_ghidra_unchecked_each_trigger_alone_fires(self):
        for name, (state, body) in TRIGGERS.items():
            with self.subTest(trigger=name):
                rc, out = self.lint(plan(state, body))
                self.assertEqual(rc, 1, out)
                self.assertEqual(self.rules(out), ["ghidra-unchecked"], out)

    def test_ghidra_unchecked_excerpt_names_the_trigger(self):
        _, out = self.lint(plan(body="Run `analyzeHeadless` on the project."))
        self.assertIn("analyzeHeadless", out)
        _, out = self.lint(plan(body="### Live procedure\n"))
        self.assertIn("Live procedure", out)
        _, out = self.lint(plan(body="See ForgePact/docs/pet-quest-research.md."))
        self.assertIn("ForgePact/docs/pet-quest-research.md", out)

    def test_ghidra_unchecked_fires_on_a_trigger_found_only_in_the_sibling_context_file(self):
        context = "## Context\n\n### Reading\n\nThe callers came from `mcp__ghidra__get_callers`.\n"
        rc, out = self.lint(plan(), context=context)
        self.assertEqual(rc, 1, out)
        self.assertEqual(self.rules(out), ["ghidra-unchecked"], out)
        self.assertIn("context", out.split("ghidra-unchecked: ", 1)[1])
        self.assertIn("mcp__ghidra__", out)

    def test_ghidra_unchecked_control_a_context_file_that_is_not_the_sibling_is_not_read(self):
        (self.dir / "other-context.md").write_text("Run `analyzeHeadless`.\n", encoding="utf-8")
        rc, out = self.lint(plan())
        self.assertEqual((rc, self.rules(out)), (0, []), out)

    def test_ghidra_unchecked_cleared_by_each_recorded_value(self):
        for line in ("ghidra mcp: used — DecompileTo not needed; the MCP answered the callers",
                     "ghidra mcp: unavailable — status printed `server not running`; offered "
                     "`py -3 -m tools.ghidra_mcp setup`",
                     "ghidra mcp: skipped — hub tooling change, no mechanism researched"):
            for name, (state, body) in TRIGGERS.items():
                with self.subTest(line=line.split(" — ")[0], trigger=name):
                    rc, out = self.lint(plan((*state, line), body))
                    self.assertEqual((rc, self.rules(out)), (0, []), out)

    def test_ghidra_unchecked_control_no_trigger_and_no_line_is_clean(self):
        rc, out = self.lint(plan(body="Edit the hub's README. Ghidra is not involved."),
                            context="## Context\n\nNothing about the game.\n")
        self.assertEqual((rc, self.rules(out)), (0, []), out)

    def test_ghidra_unchecked_control_route_tokens_without_a_token_or_outside_state(self):
        rc, out = self.lint(plan(("route tokens: none",)))
        self.assertEqual((rc, self.rules(out)), (0, []), out)
        rc, out = self.lint(plan(body="route tokens: `save-route: proven`"))
        self.assertEqual((rc, self.rules(out)), (0, []), out)

    def test_ghidra_unchecked_control_a_live_procedure_mention_that_is_not_a_heading(self):
        rc, out = self.lint(plan(body="This plan has no ### Live procedure section."))
        self.assertEqual((rc, self.rules(out)), (0, []), out)

    def test_ghidra_unchecked_control_a_line_outside_state_does_not_clear_it(self):
        rc, out = self.lint(plan(body="Run `analyzeHeadless`.\n\nghidra mcp: used — the callers"))
        self.assertEqual(self.rules(out), ["ghidra-unchecked"], out)

    def test_ghidra_unchecked_key_is_matched_case_insensitively(self):
        for key in ("Ghidra MCP:", "GHIDRA mcp:", "ghidra Mcp:"):
            with self.subTest(key=key):
                rc, out = self.lint(plan((f"{key} skipped — not a mechanism plan",),
                                         "Run `analyzeHeadless`."))
                self.assertEqual((rc, self.rules(out)), (0, []), out)

    def test_ghidra_bad_value_skipped_without_a_reason(self):
        for line in ("ghidra mcp: skipped", "ghidra mcp: skipped —", "ghidra mcp: skipped -- : ",
                     "ghidra mcp: skipped –"):
            with self.subTest(line=line):
                rc, out = self.lint(plan((line,)))
                self.assertEqual(rc, 1, out)
                self.assertEqual(self.rules(out), ["ghidra-bad-value"], out)

    def test_ghidra_bad_value_an_unknown_word_even_when_no_trigger_fired(self):
        for line in ("ghidra mcp: maybe — later", "ghidra mcp: n/a", "ghidra mcp:", "ghidra mcp: usedd"):
            with self.subTest(line=line):
                rc, out = self.lint(plan((line,)))
                self.assertEqual(rc, 1, out)
                self.assertEqual(self.rules(out), ["ghidra-bad-value"], out)

    def test_ghidra_bad_value_with_a_trigger_is_reported_instead_of_unchecked(self):
        rc, out = self.lint(plan(("ghidra mcp: pending",), "Run `analyzeHeadless`."))
        self.assertEqual(rc, 1, out)
        self.assertEqual(self.rules(out), ["ghidra-bad-value"], out)

    def test_ghidra_bad_value_control_the_key_is_case_insensitive_and_values_pass(self):
        for line in ("GHIDRA MCP: used — the MCP answered", "Ghidra Mcp: unavailable — server not running",
                     "ghidra mcp: skipped: no mechanism", "ghidra mcp: skipped - docs only"):
            with self.subTest(line=line):
                rc, out = self.lint(plan((line,)))
                self.assertEqual((rc, self.rules(out)), (0, []), out)


if __name__ == "__main__":
    unittest.main()
