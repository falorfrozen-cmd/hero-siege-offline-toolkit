"""The x64dbg MCP tools are `live-operator`'s, and nobody else's.

The `x64dbg` MCP server (`tools/x64dbg_mcp.py`, `docs/tools/x64dbg-mcp.md`)
attaches a debugger to the running game. Its eight tools,
`tools.x64dbg_mcp.LIVE_OPERATOR_TOOLS`, are the live session's: `live-operator`
carries each as `mcp__x64dbg__<name>`, and every other agent carries none. The
plugin behind the server can do far more (end the debuggee, which kills the
game; write memory; dump modules; set software breakpoints; step), and the
proxy registers none of that, so no name in the set may be one of those
either.

A `tools:` line is the whole of that boundary on the Claude Code side, and it
is one comma-separated line nobody reads closely in a diff. So this pins it:

- `live-operator`'s x64dbg tools equal the set exactly;
- no other agent, Claude Code or Codex, names any `mcp__x64dbg__` tool;
- no agent carries a bare `mcp__x64dbg` grant or a wildcard;
- no name in the set is one of the plugin's stopping, writing, dumping,
  stepping or software-breakpoint tools, or its command pass-throughs.

Per `AGENTS.md` § "Prove the Instrument Before Trusting a Negative Result",
the `refuses` tests run the checker on synthetic frontmatter that carries each
kind of bad grant, and expect it reported.
"""

import importlib.util
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENTS = REPO / ".claude" / "agents"
CODEX_AGENTS = REPO / ".codex" / "agents"
sys.path.insert(0, str(REPO))

from tools import x64dbg_mcp  # noqa: E402

_spec = importlib.util.spec_from_file_location("sync_agent_tooling", REPO / "tools" / "sync_agent_tooling.py")
sync = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("sync_agent_tooling", sync)
_spec.loader.exec_module(sync)

PREFIX = "mcp__x64dbg__"
OPERATOR = "live-operator"

# The pinned plugin's tools that stop the game, write to it, dump it, load
# something, step it, set a software breakpoint, or pass an arbitrary command
# through. None of them may become one of ours, under any spelling.
FORBIDDEN_PLUGIN_TOOLS = {
    name.lower() for name in (
        "StopDebug", "RestartDebug", "PauseDebug", "run",
        "WriteMemory", "WriteMemToAddress", "WriteBytesToAddress",
        "DumpModuleToFile", "DotNetDumpProcess", "LoadBinary",
        "SetBreakpoint", "DeleteBreakpoint",
        "StepInto", "StepOver", "StepOut",
        "ExecuteDbgCommand", "ExecuteDebuggerCommand", "ExecuteDebuggerCommandDirect",
        "ExecuteDebuggerCommandWithVar", "DbgCmdExec",
        "CommentOrLabelAtAddress", "StartMCPServer", "StopMCPServer",
    )
}


def tools_of(fields):
    return [t.strip() for t in fields.get("tools", "").split(",") if t.strip()]


def x64dbg_problems(name, fields):
    """Every way one agent's `tools:` line breaks the x64dbg boundary, as
    readable strings; empty when it keeps it."""
    problems = []
    want = {PREFIX + n for n in x64dbg_mcp.LIVE_OPERATOR_TOOLS}
    granted = [t for t in tools_of(fields) if t.startswith("mcp__x64dbg")]
    for tool in granted:
        if not tool.startswith(PREFIX) or tool == PREFIX:
            problems.append(f"{name}: bare server grant {tool!r}")
        elif "*" in tool or "?" in tool:
            problems.append(f"{name}: wildcard grant {tool!r}")
        elif tool[len(PREFIX):].lower() in FORBIDDEN_PLUGIN_TOOLS:
            problems.append(f"{name}: a plugin tool that stops, writes, dumps, steps or passes commands {tool!r}")
        elif tool not in want:
            problems.append(f"{name}: {tool!r} is outside LIVE_OPERATOR_TOOLS")
    if name == OPERATOR:
        missing = sorted(want - set(granted))
        if missing:
            problems.append(f"{name}: lacks {missing}")
    elif granted:
        problems.append(f"{name}: not {OPERATOR}, but carries {sorted(granted)}")
    return problems


def frontmatter(path):
    fields, _ = sync.parse_frontmatter(path.read_bytes().decode("utf-8"))
    return fields


def all_agents():
    return {p.stem: frontmatter(p) for p in sorted(AGENTS.glob("*.md"))}


def synthetic(name, tools):
    text = f"---\nname: {name}\ndescription: x\ntools: {tools}\nmodel: opus\n---\n\nbody\n"
    fields, _ = sync.parse_frontmatter(text)
    return fields


OPERATOR_LINE = ", ".join(PREFIX + n for n in x64dbg_mcp.LIVE_OPERATOR_TOOLS)


class TheToolSet(unittest.TestCase):
    def test_the_set_has_no_duplicates(self):
        self.assertEqual(len(x64dbg_mcp.LIVE_OPERATOR_TOOLS), len(set(x64dbg_mcp.LIVE_OPERATOR_TOOLS)))

    def test_live_operator_set_has_no_stopping_writing_dumping_stepping_or_breaking_tool(self):
        bad = [n for n in x64dbg_mcp.LIVE_OPERATOR_TOOLS if n.lower() in FORBIDDEN_PLUGIN_TOOLS]
        self.assertEqual(bad, [])


class TheAgents(unittest.TestCase):
    def test_live_operator_exists(self):
        self.assertIn(OPERATOR, all_agents())

    def test_live_operator_carries_exactly_the_set(self):
        have = {t for t in tools_of(all_agents()[OPERATOR]) if t.startswith("mcp__x64dbg")}
        self.assertEqual(have, {PREFIX + n for n in x64dbg_mcp.LIVE_OPERATOR_TOOLS})

    def test_no_other_agent_carries_an_x64dbg_tool(self):
        for name, fields in all_agents().items():
            if name == OPERATOR:
                continue
            with self.subTest(agent=name):
                self.assertEqual([t for t in tools_of(fields) if t.startswith("mcp__x64dbg")], [])

    def test_no_other_codex_agent_names_an_x64dbg_tool(self):
        for path in sorted(CODEX_AGENTS.glob("*.toml")):
            if path.stem == OPERATOR:
                continue
            with self.subTest(agent=path.stem):
                self.assertNotIn("mcp__x64dbg", path.read_text(encoding="utf-8"))

    def test_no_agent_breaks_the_boundary(self):
        problems = [p for name, fields in all_agents().items() for p in x64dbg_problems(name, fields)]
        self.assertEqual(problems, [])


class TheCheckerItself(unittest.TestCase):
    """Negative controls: synthetic frontmatter carrying each kind of bad
    grant, which the checker must report, beside clean ones it must pass."""

    def test_live_operator_passes_with_exactly_the_set(self):
        self.assertEqual(x64dbg_problems(OPERATOR, synthetic(OPERATOR, f"Read, Bash, {OPERATOR_LINE}")), [])

    def test_passes_another_agent_without_x64dbg(self):
        self.assertEqual(x64dbg_problems("verifier", synthetic("verifier", "Read, Grep, Bash")), [])

    def test_refuses_each_bad_grant_on_live_operator(self):
        for bad in (
            "mcp__x64dbg__StopDebug",
            "mcp__x64dbg__WriteMemory",
            "mcp__x64dbg__DumpModuleToFile",
            "mcp__x64dbg__SetBreakpoint",
            "mcp__x64dbg__StepInto",
            "mcp__x64dbg__ExecuteDbgCommand",
            "mcp__x64dbg__registers",
            "mcp__x64dbg",
            "mcp__x64dbg__*",
        ):
            with self.subTest(grant=bad):
                problems = x64dbg_problems(OPERATOR, synthetic(OPERATOR, f"Read, {OPERATOR_LINE}, {bad}"))
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(repr(bad), problems[0])

    def test_refuses_any_x64dbg_grant_on_any_other_agent(self):
        for agent in ("planner", "implementer", "verifier", "consultant"):
            for grant in ("mcp__x64dbg__status", "mcp__x64dbg__logpoint", "mcp__x64dbg", "mcp__x64dbg__*"):
                with self.subTest(agent=agent, grant=grant):
                    self.assertTrue(x64dbg_problems(agent, synthetic(agent, f"Read, {grant}")),
                                    f"{grant} on {agent} was not reported")

    def test_refuses_live_operator_missing_part_of_the_set(self):
        partial = ", ".join(PREFIX + n for n in x64dbg_mcp.LIVE_OPERATOR_TOOLS[1:])
        problems = x64dbg_problems(OPERATOR, synthetic(OPERATOR, f"Read, {partial}"))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn(x64dbg_mcp.LIVE_OPERATOR_TOOLS[0], problems[0])

    def test_refuses_forbidden_plugin_names_in_any_case(self):
        for name in ("stopdebug", "WRITEMEMORY", "LoadBinary", "stepover", "DbgCmdExec", "Run"):
            with self.subTest(name=name):
                self.assertIn(name.lower(), FORBIDDEN_PLUGIN_TOOLS)
        self.assertTrue(re.fullmatch(r"[a-z]+", "".join(x64dbg_mcp.LIVE_OPERATOR_TOOLS)))


if __name__ == "__main__":
    unittest.main()
