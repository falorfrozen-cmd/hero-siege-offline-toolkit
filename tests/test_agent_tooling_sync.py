"""The Claude Code and Codex copies of the shared agent tooling must agree.

This project is developed with both Claude Code and ChatGPT's Codex. Each
shared resource has one source of truth and a derived copy for the other agent
(`tools/sync_agent_tooling.py` describes the mapping). A derived copy someone
edited by hand, or a source nobody re-synced, would leave the two agents
following different skills, reviewers or MCP servers with nothing to show it.

`TestTheCheckerItself` breaks a copy on purpose and expects `--check` to say
so: a drift check that never saw drift proves nothing.
"""

import importlib.util
import io
import json
import re
import shutil
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("sync_agent_tooling", REPO / "tools" / "sync_agent_tooling.py")
sync = importlib.util.module_from_spec(_spec)
sys.modules["sync_agent_tooling"] = sync
_spec.loader.exec_module(sync)


def run_check() -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = sync.main(["--check"])
    return rc, out.getvalue()


class TestDerivedCopiesAreCurrent(unittest.TestCase):
    def test_check_reports_no_drift(self):
        rc, out = run_check()
        self.assertEqual(rc, 0, out)

    def test_every_claude_agent_has_a_codex_twin(self):
        claude = {p.stem for p in (REPO / ".claude" / "agents").glob("*.md")}
        codex = {p.stem for p in (REPO / ".codex" / "agents").glob("*.toml")}
        self.assertEqual(claude, codex)

    def test_codex_agents_parse_and_keep_the_contract(self):
        for path in (REPO / ".codex" / "agents").glob("*.toml"):
            with self.subTest(agent=path.name):
                data = tomllib.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["name"], path.stem)
                self.assertTrue(data["description"])
                self.assertIn(data["sandbox_mode"], {"read-only", "workspace-write"})
                self.assertIn(f".claude/agents/{path.stem}.md", data["developer_instructions"])

    def test_read_only_claude_agents_stay_read_only_in_codex(self):
        for path in (REPO / ".claude" / "agents").glob("*.md"):
            fields, _ = sync.parse_frontmatter(path.read_text(encoding="utf-8"))
            tools = {t.strip() for t in fields["tools"].split(",")}
            if tools & sync.WRITE_TOOLS:
                continue
            with self.subTest(agent=path.stem):
                data = tomllib.loads((REPO / ".codex" / "agents" / f"{path.stem}.toml").read_text(encoding="utf-8"))
                self.assertEqual(data["sandbox_mode"], "read-only")

    def test_effort_variants_are_their_source_at_another_effort(self):
        """A variant differs from its source in name, effort and description
        only; the body is the same instructions, byte for byte."""
        variants = [p for p in sorted(sync.CLAUDE_AGENTS.glob("*.md")) if sync.is_generated_variant(p)]
        self.assertTrue(variants, "the /workorder tier tables name effort variants; none were generated")
        for path in variants:
            fields, body = sync.parse_frontmatter(path.read_text(encoding="utf-8"))
            base, _, level = fields["name"].rpartition("-")
            src_fields, src_body = sync.parse_frontmatter((sync.CLAUDE_AGENTS / f"{base}.md").read_text(encoding="utf-8"))
            self.assertIn(level, src_fields["effort-variants"], path.name)
            self.assertEqual(fields["effort"], level, path.name)
            self.assertEqual(fields["model"], src_fields["model"], path.name)
            self.assertEqual(fields["tools"], src_fields["tools"], path.name)
            self.assertEqual(body, src_body, path.name)
            self.assertNotIn("effort-variants", fields, path.name)

    def test_codex_mcp_servers_match_mcp_json(self):
        claude = json.loads((REPO / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        codex = tomllib.loads((REPO / ".codex" / "config.toml").read_text(encoding="utf-8"))["mcp_servers"]
        self.assertEqual(set(claude), set(codex))
        for name, spec in claude.items():
            with self.subTest(server=name):
                if "command" in spec:
                    self.assertEqual(codex[name]["command"], spec["command"])
                    self.assertEqual(codex[name].get("args", []), spec.get("args", []))
                else:
                    self.assertEqual(codex[name]["url"], spec["url"])

    def test_every_token_a_server_reads_is_asked_for_by_setup(self):
        spec = importlib.util.spec_from_file_location("setup_agent_secrets", REPO / "tools" / "setup_agent_secrets.py")
        setup = importlib.util.module_from_spec(spec)
        sys.modules["setup_agent_secrets"] = setup
        spec.loader.exec_module(setup)
        asked = {s.name for s in setup.SECRETS}
        referenced = set(re.findall(r"\$\{(\w+)\}", (REPO / ".mcp.json").read_text(encoding="utf-8")))
        self.assertTrue(referenced)
        self.assertEqual(referenced, asked)

    def test_passthrough_env_reaches_codex_servers(self):
        claude = json.loads((REPO / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        codex = tomllib.loads((REPO / ".codex" / "config.toml").read_text(encoding="utf-8"))["mcp_servers"]
        for name, spec in claude.items():
            for key, value in (spec.get("env") or {}).items():
                with self.subTest(server=name, var=key):
                    if value == f"${{{key}}}":
                        self.assertIn(key, codex[name]["env_vars"])
                        self.assertNotIn(key, codex[name].get("env", {}))

    def test_user_only_skills_are_explicit_only_in_codex(self):
        for skill in (REPO / ".agents" / "skills").glob("*/SKILL.md"):
            fields, _ = sync.parse_frontmatter(skill.read_text(encoding="utf-8"))
            yaml_path = skill.parent / "agents" / "openai.yaml"
            with self.subTest(skill=skill.parent.name):
                if fields.get("disable-model-invocation") == "true":
                    self.assertIn("allow_implicit_invocation: false", yaml_path.read_text(encoding="utf-8"))
                else:
                    self.assertFalse(yaml_path.exists())

    def test_claude_only_skills_are_not_shared(self):
        shared = {p.name for p in (REPO / ".agents" / "skills").iterdir()}
        self.assertFalse(sync.CLAUDE_ONLY_SKILLS & shared)
        for name in sync.CLAUDE_ONLY_SKILLS:
            self.assertTrue((REPO / ".claude" / "skills" / name / "SKILL.md").is_file(), name)


class TestCodexHooks(unittest.TestCase):
    def test_codex_runs_the_same_dispatcher_as_claude(self):
        claude = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
        codex = json.loads((REPO / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        claude_cmds = [h["command"] for g in claude["hooks"]["PostToolUse"] for h in g["hooks"]]
        codex_cmds = [h["command"] for g in codex["hooks"]["PostToolUse"] for h in g["hooks"]]
        self.assertTrue(all(".claude/hooks/post_tool_use.py" in c for c in claude_cmds + codex_cmds), (claude_cmds, codex_cmds))
        self.assertEqual(len(claude_cmds), len(codex_cmds))

    def test_dispatcher_runs_on_codex_edits(self):
        sys.path.insert(0, str(REPO / ".claude" / "hooks"))
        try:
            import post_tool_use
        finally:
            sys.path.pop(0)
        codex = json.loads((REPO / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        for group in codex["hooks"]["PostToolUse"]:
            for tool in group["matcher"].split("|"):
                with self.subTest(tool=tool):
                    self.assertIn(tool, post_tool_use.TREE_TOOLS)


class TestTheCheckerItself(unittest.TestCase):
    """Point the sync at a scratch copy and break each derived kind in turn."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for rel in (".agents", ".claude/skills", ".claude/agents", ".codex"):
            shutil.copytree(REPO / rel, self.tmp / rel, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(REPO / ".mcp.json", self.tmp / ".mcp.json")
        self.saved = {k: getattr(sync, k) for k in ("SHARED_SKILLS", "CLAUDE_SKILLS", "CLAUDE_AGENTS", "CODEX_AGENTS", "MCP_JSON", "CODEX_CONFIG", "ROOT")}
        sync.ROOT = self.tmp
        sync.SHARED_SKILLS = self.tmp / ".agents" / "skills"
        sync.CLAUDE_SKILLS = self.tmp / ".claude" / "skills"
        sync.CLAUDE_AGENTS = self.tmp / ".claude" / "agents"
        sync.CODEX_AGENTS = self.tmp / ".codex" / "agents"
        sync.MCP_JSON = self.tmp / ".mcp.json"
        sync.CODEX_CONFIG = self.tmp / ".codex" / "config.toml"

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(sync, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scratch_copy_starts_clean(self):
        self.assertEqual(run_check()[0], 0)

    def test_edited_skill_mirror_is_caught_and_repaired(self):
        target = self.tmp / ".claude" / "skills" / "animate" / "SKILL.md"
        target.write_text(target.read_text(encoding="utf-8") + "\nhand edit\n", encoding="utf-8")
        rc, out = run_check()
        self.assertEqual(rc, 1)
        self.assertIn(".claude/skills/animate", out)
        with redirect_stdout(io.StringIO()):
            sync.main([])
        self.assertEqual(run_check()[0], 0)

    def test_stray_claude_skill_is_caught(self):
        (self.tmp / ".claude" / "skills" / "new-skill").mkdir()
        rc, out = run_check()
        self.assertEqual(rc, 1)
        self.assertIn("new-skill", out)

    def test_changed_agent_source_is_caught(self):
        src = self.tmp / ".claude" / "agents" / "verifier.md"
        src.write_text(src.read_text(encoding="utf-8") + "\nA new rule.\n", encoding="utf-8")
        rc, out = run_check()
        self.assertEqual(rc, 1)
        self.assertIn(".codex/agents/verifier.toml", out)

    def test_changed_agent_source_reaches_its_effort_variants(self):
        src = self.tmp / ".claude" / "agents" / "planner.md"
        src.write_text(src.read_text(encoding="utf-8") + "\nA new rule.\n", encoding="utf-8")
        rc, out = run_check()
        self.assertEqual(rc, 1)
        self.assertIn(".claude/agents/planner-xhigh.md", out)
        with redirect_stdout(io.StringIO()):
            sync.main([])
        self.assertEqual(run_check()[0], 0)
        self.assertTrue((self.tmp / ".claude" / "agents" / "planner-xhigh.md").read_text(encoding="utf-8")
                        .endswith("\nA new rule.\n"))

    def test_hand_edited_effort_variant_is_caught(self):
        variant = self.tmp / ".claude" / "agents" / "planner-max.md"
        variant.write_text(variant.read_text(encoding="utf-8").replace("effort: max", "effort: high"), encoding="utf-8")
        rc, out = run_check()
        self.assertEqual(rc, 1)
        self.assertIn("planner-max.md", out)

    def test_dropped_effort_variant_is_caught_and_removed(self):
        src = self.tmp / ".claude" / "agents" / "consultant.md"
        src.write_text(src.read_text(encoding="utf-8").replace("effort-variants: max\n", ""), encoding="utf-8")
        rc, out = run_check()
        self.assertEqual(rc, 1)
        self.assertIn("consultant-max.md", out)
        with redirect_stdout(io.StringIO()):
            sync.main([])
        self.assertFalse((self.tmp / ".claude" / "agents" / "consultant-max.md").exists())
        self.assertFalse((self.tmp / ".codex" / "agents" / "consultant-max.toml").exists())
        self.assertEqual(run_check()[0], 0)

    def test_unknown_effort_variant_refuses(self):
        src = self.tmp / ".claude" / "agents" / "consultant.md"
        src.write_text(src.read_text(encoding="utf-8").replace("effort-variants: max", "effort-variants: extreme"), encoding="utf-8")
        with self.assertRaises(ValueError):
            run_check()

    def test_changed_mcp_server_is_caught(self):
        data = json.loads((self.tmp / ".mcp.json").read_text(encoding="utf-8"))
        data["mcpServers"]["context7"]["args"].append("--extra")
        (self.tmp / ".mcp.json").write_text(json.dumps(data), encoding="utf-8")
        rc, out = run_check()
        self.assertEqual(rc, 1)
        self.assertIn(".codex/config.toml", out)

    def test_untranslatable_mcp_key_refuses_instead_of_dropping_it(self):
        data = json.loads((self.tmp / ".mcp.json").read_text(encoding="utf-8"))
        data["mcpServers"]["context7"]["cwd"] = "somewhere"
        (self.tmp / ".mcp.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ValueError):
            sync.codex_config_toml()

    def test_multiline_string_round_trips_awkward_text(self):
        text = 'a """ b \\ c\n"quoted"\n'
        self.assertEqual(tomllib.loads(f"x = {sync.toml_multiline(text)}")["x"], text)


if __name__ == "__main__":
    unittest.main()
