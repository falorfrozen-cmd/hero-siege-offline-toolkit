"""The ghidra MCP tools an agent may call are the read set, and only on the
workorder phase agents.

The `ghidra` MCP server (`tools/ghidra_mcp.py`, `docs/tools/ghidra-mcp.md`)
exposes about 240 tools, most of which write: renames, retypes, scripts,
program loads, and a `debugger_*` family that attaches to a running process.
The planner, implementer and consultant (and their generated effort variants)
get the read set `tools.ghidra_mcp.AGENT_READ_TOOLS` -- search, list,
decompile, xrefs, callers/callees/call graph, function info and status -- and
nothing else. Every other agent gets no ghidra tool at all.

A `tools:` line is the whole of that boundary on the MCP side, and it is one
comma-separated line nobody reads closely in a diff. So this pins it:

- each phase agent's ghidra tools equal the read set exactly, as a set;
- no other agent carries any `mcp__ghidra` tool;
- no agent carries a bare `mcp__ghidra` grant, a wildcard, or a ghidra tool
  outside the read set;
- no name in the read set looks like a write or a debugger tool;
- the set was classified against the server release `tools/ghidra_mcp.py`
  pins, so a version bump fails here until someone reclassifies the schema.

Per `AGENTS.md` § "Prove the Instrument Before Trusting a Negative Result",
the `refuses` tests run the checker on synthetic frontmatter that carries
each kind of bad grant, and expect it reported. A checker that only ever sees
the real, clean files cannot tell "all clean" from "checks nothing".
"""

import importlib.util
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENTS = REPO / ".claude" / "agents"
sys.path.insert(0, str(REPO))

from tools import ghidra_mcp  # noqa: E402

_spec = importlib.util.spec_from_file_location("sync_agent_tooling", REPO / "tools" / "sync_agent_tooling.py")
sync = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("sync_agent_tooling", sync)
_spec.loader.exec_module(sync)

PREFIX = "mcp__ghidra__"

# The agents that get the read set: the three sources and every effort variant
# tools/sync_agent_tooling.py generates from them.
PHASE_AGENTS = {
    "planner",
    "planner-medium",
    "planner-xhigh",
    "planner-max",
    "implementer",
    "implementer-medium",
    "consultant",
    "consultant-max",
}

# A tool name that writes to the program or project, changes the session, or
# drives the debugger. It covers every prefix docs/tools/ghidra-mcp.md lists as
# left out, plus the two single tools left out on their own: `force_decompile`
# (refreshes the decompiler cache) and `disassemble_bytes` (a POST that creates
# instructions in the listing).
WRITE_OR_DEBUGGER = re.compile(
    r"^(?:"
    r"rename_|set_|create_|delete_|save_|import_|apply_|"
    r"batch_set_|batch_create_|batch_delete_|batch_rename_|"
    r"add_|remove_|clear_|modify_|embed_|resize_|recreate_|clone_|move_|merge_|"
    r"run_script|run_ghidra_script|run_analysis|reanalyze|"
    r"archive_|checkin_|export_|restore_|open_|close_|load_|unload_|"
    r"switch_program|connect_instance|emulate_|debugger_|"
    r"force_decompile|disassemble_bytes"
    r")"
)


def tools_of(fields):
    return [t.strip() for t in fields.get("tools", "").split(",") if t.strip()]


def ghidra_problems(name, fields):
    """Every way one agent's `tools:` line breaks the ghidra boundary, as
    readable strings; empty when it keeps it."""
    problems = []
    read_set = {PREFIX + n for n in ghidra_mcp.AGENT_READ_TOOLS}
    ghidra = [t for t in tools_of(fields) if t.startswith("mcp__ghidra")]
    for tool in ghidra:
        if not tool.startswith(PREFIX) or tool == PREFIX:
            problems.append(f"{name}: bare server grant {tool!r}")
        elif "*" in tool or "?" in tool:
            problems.append(f"{name}: wildcard grant {tool!r}")
        elif WRITE_OR_DEBUGGER.match(tool[len(PREFIX):]):
            problems.append(f"{name}: write or debugger tool {tool!r}")
        elif tool not in read_set:
            problems.append(f"{name}: {tool!r} is outside AGENT_READ_TOOLS")
    if name in PHASE_AGENTS:
        missing = sorted(read_set - set(ghidra))
        if missing:
            problems.append(f"{name}: lacks {missing}")
    elif ghidra:
        problems.append(f"{name}: not a phase agent, but carries {sorted(ghidra)}")
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


READ_LINE = ", ".join(PREFIX + n for n in ghidra_mcp.AGENT_READ_TOOLS)


class TheReadSet(unittest.TestCase):
    def test_the_read_set_has_no_duplicates(self):
        self.assertEqual(len(ghidra_mcp.AGENT_READ_TOOLS), len(set(ghidra_mcp.AGENT_READ_TOOLS)))

    def test_no_name_in_the_read_set_writes_or_debugs(self):
        bad = [n for n in ghidra_mcp.AGENT_READ_TOOLS if WRITE_OR_DEBUGGER.match(n)]
        self.assertEqual(bad, [])

    def test_the_classification_matches_the_pinned_release(self):
        self.assertEqual(
            ghidra_mcp.AGENT_READ_TOOLS_CLASSIFIED_FOR,
            ghidra_mcp.VERSION,
            "tools/ghidra_mcp.py's VERSION moved: reclassify the new /mcp/schema, "
            "update AGENT_READ_TOOLS and the agents' tools: lines, then bump "
            "AGENT_READ_TOOLS_CLASSIFIED_FOR",
        )


class TheAgents(unittest.TestCase):
    def test_every_phase_agent_exists(self):
        # Without this, a renamed or missing agent would leave the set check
        # below with nothing to compare.
        self.assertEqual(PHASE_AGENTS - set(all_agents()), set())

    def test_each_phase_agent_carries_exactly_the_read_set(self):
        want = {PREFIX + n for n in ghidra_mcp.AGENT_READ_TOOLS}
        agents = all_agents()
        for name in sorted(PHASE_AGENTS):
            with self.subTest(agent=name):
                have = {t for t in tools_of(agents[name]) if t.startswith("mcp__ghidra")}
                self.assertEqual(have, want)

    def test_no_other_agent_carries_a_ghidra_tool(self):
        for name, fields in all_agents().items():
            if name in PHASE_AGENTS:
                continue
            with self.subTest(agent=name):
                self.assertEqual([t for t in tools_of(fields) if t.startswith("mcp__ghidra")], [])

    def test_no_agent_breaks_the_boundary(self):
        problems = [p for name, fields in all_agents().items() for p in ghidra_problems(name, fields)]
        self.assertEqual(problems, [])


class TheCheckerItself(unittest.TestCase):
    """Negative controls: synthetic frontmatter carrying each kind of bad
    grant, which the checker must report, beside a clean one it must pass."""

    def test_passes_a_phase_agent_with_the_read_set(self):
        self.assertEqual(ghidra_problems("planner", synthetic("planner", f"Read, Bash, {READ_LINE}")), [])

    def test_passes_another_agent_without_ghidra(self):
        self.assertEqual(ghidra_problems("verifier", synthetic("verifier", "Read, Grep, Bash")), [])

    def test_refuses_each_bad_grant_on_a_phase_agent(self):
        for bad in (
            "mcp__ghidra__rename_function",
            "mcp__ghidra__debugger_attach",
            "mcp__ghidra__run_script_inline",
            "mcp__ghidra",
            "mcp__ghidra__*",
        ):
            with self.subTest(grant=bad):
                fields = synthetic("planner", f"Read, Bash, {READ_LINE}, {bad}")
                problems = ghidra_problems("planner", fields)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(repr(bad), problems[0])

    def test_refuses_each_bad_grant_on_any_other_agent(self):
        for bad in (
            "mcp__ghidra__rename_function",
            "mcp__ghidra__debugger_attach",
            "mcp__ghidra__run_script_inline",
            "mcp__ghidra",
            "mcp__ghidra__*",
            "mcp__ghidra__decompile_function",
        ):
            with self.subTest(grant=bad):
                problems = ghidra_problems("verifier", synthetic("verifier", f"Read, {bad}"))
                self.assertTrue(problems, f"{bad} on verifier was not reported")

    def test_refuses_a_read_tool_outside_the_set(self):
        problems = ghidra_problems("planner", synthetic("planner", f"Read, {READ_LINE}, mcp__ghidra__read_memory"))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("outside AGENT_READ_TOOLS", problems[0])

    def test_refuses_a_phase_agent_missing_part_of_the_set(self):
        partial = ", ".join(PREFIX + n for n in ghidra_mcp.AGENT_READ_TOOLS[1:])
        problems = ghidra_problems("consultant", synthetic("consultant", f"Read, {partial}"))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn(ghidra_mcp.AGENT_READ_TOOLS[0], problems[0])

    def test_refuses_write_and_debugger_names_by_pattern(self):
        for name in (
            "rename_function",
            "set_function_prototype",
            "create_struct",
            "run_script_inline",
            "run_ghidra_script",
            "load_tool_group",
            "load_program_from_project",
            "switch_program",
            "connect_instance",
            "debugger_attach",
            "force_decompile",
            "disassemble_bytes",
            "batch_rename_functions",
            "save_program",
        ):
            with self.subTest(name=name):
                self.assertTrue(WRITE_OR_DEBUGGER.match(name), name)


if __name__ == "__main__":
    unittest.main()
