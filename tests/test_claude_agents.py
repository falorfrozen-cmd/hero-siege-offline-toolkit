"""The agent and skill definitions in .claude/ must declare what they run as.

Two rules from `.claude/README.md` are checkable, and neither was checked.

**Every agent pins `model:`.** An omitted field means "whatever the session
is", which is not a decision anybody made. Running the session on Haiku would
have quietly dropped `sdk-contract-reviewer` -- four separate rediscoveries of
one defect -- to the cheapest tier while still printing a clean report; running
it on Fable would have doubled the cost of every SDK-touching change with
nobody choosing that. Neither shows up in a diff. That is the same shape as the
rest of this project's expensive bugs: something that reports itself working
while doing something other than what it says.

**No unquoted `#` in frontmatter.** A ` #` in a plain YAML scalar opens a
comment and the rest of the value is silently dropped -- no error, and the file
still loads. `tauri-command-reviewer` shipped that way and lost the last 86
characters of its `description`, which were the trigger conditions that make
the agent get selected at all. It is now a double-quoted scalar, and this test
is what stops the next one regressing.

Per `AGENTS.md` § "Prove the Instrument Before Trusting a Negative Result",
`TestTheCheckerItself` runs the parser against known-bad input. A static test
that only ever sees good files cannot distinguish "all clean" from "parser
returns nothing".
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENTS = REPO / ".claude" / "agents"
SKILLS = REPO / ".claude" / "skills"

# Tier aliases, not pinned version IDs -- the tier is the design decision and
# the version is not. See `.claude/README.md`, "Agents".
VALID_MODELS = {"opus", "sonnet", "haiku", "fable", "inherit"}

FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
FIELD = re.compile(r"^([A-Za-z][\w-]*):[ \t]*(.*?)[ \t]*$", re.M)


def parse_frontmatter(text):
    """(fields, raw) for a definition file, or (None, None) if it has none."""
    match = FRONTMATTER.match(text)
    if not match:
        return None, None
    raw = match.group(1)
    return dict(FIELD.findall(raw)), raw


def yaml_comment_risk(raw):
    """Field names whose unquoted value would lose everything after a ` #`."""
    risky = []
    for name, value in FIELD.findall(raw):
        quoted = len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'"
        if not quoted and " #" in value:
            risky.append(name)
    return risky


def definition_files():
    return sorted(AGENTS.glob("*.md")) + sorted(SKILLS.glob("*/SKILL.md"))


class TestAgentDefinitions(unittest.TestCase):
    def setUp(self):
        self.agents = sorted(AGENTS.glob("*.md"))
        self.assertTrue(self.agents, "no agent definitions found -- wrong path?")

    def test_every_agent_pins_a_model(self):
        for path in self.agents:
            with self.subTest(agent=path.name):
                fields, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
                self.assertIsNotNone(fields, f"{path.name} has no frontmatter")
                self.assertIn(
                    "model",
                    fields,
                    f"{path.name} does not pin `model:`, so it silently runs at "
                    f"whatever the session is set to. Use `inherit` explicitly "
                    f"if following the session is genuinely the intent.",
                )

    def test_every_pinned_model_is_a_known_tier(self):
        for path in self.agents:
            with self.subTest(agent=path.name):
                fields, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
                model = fields.get("model", "")
                self.assertIn(
                    model,
                    VALID_MODELS,
                    f"{path.name} pins `model: {model}`, which is not a tier "
                    f"alias. Pinning a dated model ID rots -- see "
                    f"`.claude/README.md`.",
                )

    def test_agent_name_matches_its_filename(self):
        for path in self.agents:
            with self.subTest(agent=path.name):
                fields, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
                self.assertEqual(fields.get("name"), path.stem)

    def test_every_agent_declares_its_tools(self):
        for path in self.agents:
            with self.subTest(agent=path.name):
                fields, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
                self.assertIn("tools", fields, f"{path.name} declares no tools")


class TestFrontmatterIsNotSilentlyTruncated(unittest.TestCase):
    """The ` #` trap, across agents and skills alike."""

    def test_no_unquoted_hash_in_any_definition(self):
        for path in definition_files():
            with self.subTest(definition=str(path.relative_to(REPO))):
                _, raw = parse_frontmatter(path.read_text(encoding="utf-8"))
                self.assertIsNotNone(raw, f"{path} has no frontmatter")
                self.assertEqual(
                    yaml_comment_risk(raw),
                    [],
                    f"an unquoted ' #' in {path.name} opens a YAML comment and "
                    f"silently drops the rest of the value. Double-quote it.",
                )

    def test_every_definition_has_a_description(self):
        for path in definition_files():
            with self.subTest(definition=str(path.relative_to(REPO))):
                fields, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
                self.assertTrue(
                    fields.get("description"),
                    f"{path.name} has no description, so nothing can select it",
                )


class TestTheCheckerItself(unittest.TestCase):
    """Positive controls. Without these the suite above proves nothing."""

    def test_missing_frontmatter_is_detected(self):
        fields, raw = parse_frontmatter("# just a heading\n")
        self.assertIsNone(fields)
        self.assertIsNone(raw)

    def test_unquoted_hash_is_detected(self):
        _, raw = parse_frontmatter(
            "---\nname: x\ndescription: edits a #[tauri::command] here\n---\n"
        )
        self.assertEqual(yaml_comment_risk(raw), ["description"])

    def test_quoted_hash_is_not_flagged(self):
        _, raw = parse_frontmatter(
            '---\nname: x\ndescription: "edits a #[tauri::command] here"\n---\n'
        )
        self.assertEqual(yaml_comment_risk(raw), [])

    def test_a_hash_with_no_leading_space_is_not_a_comment(self):
        _, raw = parse_frontmatter("---\nname: x\ndescription: issue#12\n---\n")
        self.assertEqual(yaml_comment_risk(raw), [])

    def test_missing_model_is_detected(self):
        fields, _ = parse_frontmatter("---\nname: x\ntools: Read\n---\n")
        self.assertNotIn("model", fields)

    def test_crlf_frontmatter_parses(self):
        """The worktree is CRLF; a parser anchored on '\\n---\\n' would see none."""
        fields, _ = parse_frontmatter("---\r\nname: x\r\nmodel: opus\r\n---\r\n")
        self.assertEqual(fields.get("model"), "opus")


if __name__ == "__main__":
    unittest.main()
