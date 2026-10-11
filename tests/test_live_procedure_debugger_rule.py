"""A live procedure puts "which code" questions to the x64dbg debugger.

Only `live-operator` carries the `mcp__x64dbg__*` tools
(`tests/test_x64dbg_agent_tools.py`), and it attaches only when the
procedure names debugger steps. So the debugger runs only if the planner
writes it in. Until hub #490 nothing told it to: ForgePact #197's Live 1
(2026-10-11) logged a research hook's `calls=0` against an observed merge,
with no logpoint to show which code did it.

This pins the rule in each place that has to carry it:

- `planner.md` gives every procedure a **debugger** field, says when it
  names x64dbg steps, which steps, and how their checks are named;
- every effort variant and Codex copy of the planner carries the same rule;
- `live-gate.md` checks the field before the install question and sends a
  missing one back to the planner;
- `instrument-blindness-reviewer` flags a pending procedure that answers a
  "which code" question with a hook alone.
"""

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENTS = REPO / ".claude" / "agents"
CODEX = REPO / ".codex" / "agents"
LIVE_GATE = REPO / ".claude" / "skills" / "workorder" / "live-gate.md"

RULE_HEADING = "Ask \"which code\" of the debugger, not only of a hook."


def text(path):
    return path.read_text(encoding="utf-8")


class ThePlanner(unittest.TestCase):
    def setUp(self):
        self.body = text(AGENTS / "planner.md")

    def test_every_procedure_carries_a_debugger_field(self):
        self.assertIn("- **debugger**: the x64dbg steps the session runs, or `none — <reason>`.", self.body)

    def test_the_rule_says_when_to_write_debugger_steps(self):
        self.assertIn(RULE_HEADING, self.body)
        self.assertIn("whether a function fires, which code does something", self.body)

    def test_the_steps_keep_the_debugger_rules(self):
        for phrase in (
            "attach under the session's lease",
            "a **debugger control** first",
            "at most four non-breaking hardware logpoints",
            "`expect_bytes`",
            "`detach` before `hs_stop_game`",
            "research finding",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.body)

    def test_debugger_checks_are_named_and_routed(self):
        self.assertIn("named as the check `dbg-control`", self.body)
        self.assertIn("named as the check\n  `dbg-<candidate>`", self.body)
        self.assertIn("`dbg-control` is a session-validity check and goes on `--require-pass`", self.body)

    def test_the_rule_sits_in_the_live_procedure_section(self):
        start = self.body.index("## A live session is a procedure, not a request")
        end = self.body.index("\n## ", start + 1)
        self.assertIn(RULE_HEADING, self.body[start:end])

    def test_every_variant_and_codex_copy_carries_it(self):
        paths = sorted(AGENTS.glob("planner*.md")) + sorted(CODEX.glob("planner*.toml"))
        self.assertGreaterEqual(len(paths), 8, [p.name for p in paths])
        for path in paths:
            with self.subTest(path=path.name):
                self.assertIn(RULE_HEADING, text(path))


class TheLiveGate(unittest.TestCase):
    def test_the_driver_checks_the_field_before_the_install_question(self):
        body = text(LIVE_GATE)
        check = body.index("Check the procedure puts \"which code\" questions to the debugger.")
        install = body.index("Ask before anything changes on the owner's machine.")
        self.assertLess(check, install)
        self.assertIn("`PLAN-DEFECT`", body[check:install])


class TheReviewer(unittest.TestCase):
    def test_instrument_blindness_reviewer_flags_a_hook_only_which_code_question(self):
        for path in (AGENTS / "instrument-blindness-reviewer.md", CODEX / "instrument-blindness-reviewer.toml"):
            with self.subTest(path=path.name):
                self.assertIn("A pending live procedure asks \"which code\" of the debugger too.", text(path))


class TheChecksItself(unittest.TestCase):
    """Negative control: the phrases this file looks for must not already
    appear in an agent that was never given the rule, or a pass here would
    say nothing."""

    def test_the_verifier_does_not_carry_the_rule(self):
        body = text(AGENTS / "verifier.md")
        self.assertNotIn(RULE_HEADING, body)
        self.assertNotIn("`dbg-control`", body)


if __name__ == "__main__":
    unittest.main()
