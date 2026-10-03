"""`section.py`'s code mode: one call finds a function, class or method in a
large source file and prints it, instead of a `grep -n` and then a `sed -n`
range read.

Measured in the 2026-10-03 audit (`.claude/workorders/` context of
`workorder-cost-slices-symbols`): implementers went to a symbol in
`ModuleMain.cpp` and the workflow script with a grep chain and a ranged read,
two or three calls each time, and `tools/source_index.py --functions` found
nothing at all in a header whose functions sit inside a `namespace` block.

Driven as a subprocess, the way an agent runs it, on fixtures built in code
(one per language, CRLF where the repository writes CRLF), each carrying the
outliers the contract names. Every "finds it" assertion has a control beside
it (`AGENTS.md` § "Prove the Instrument Before Trusting a Negative Result"): a
printer that dumped the whole file would pass every positive check here.
"""

import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / ".claude" / "skills" / "workorder" / "section.py"

TOC_LINE = re.compile(r"^(\d+)-(\d+)  \d+\.\dKB  (.+) (\S+)$")

CPP = "\r\n".join([
    "#pragma once",                                              # 1
    "#include <string>",                                         # 2
    "",                                                          # 3
    "// ===== Helpers ==========================================",  # 4
    "namespace Outer::Inner {",                                  # 5
    "",                                                          # 6
    "/** Doc comment above, not printed. { a brace in a comment */",  # 7
    "inline void ScanThings(",                                   # 8
    "    int a,",                                                # 9
    "    const char* label = \"}{\",",                           # 10
    "    char open = '{'",                                       # 11
    ") {",                                                       # 12
    "    if (a) { return; }",                                    # 13
    "}",                                                         # 14
    "",                                                          # 15
    "inline bool OneLiner(int v) { return v == '}'; }",          # 16
    "",                                                          # 17
    "struct Widget : public Base {",                             # 18
    "    int Size() const {",                                    # 19
    "        return 1;",                                         # 20
    "    }",                                                     # 21
    "    void Lonely();",                                        # 22
    "};",                                                        # 23
    "",                                                          # 24
    "enum class Mode : int {",                                   # 25
    "    A,",                                                    # 26
    "    B,",                                                    # 27
    "};",                                                        # 28
    "",                                                          # 29
    "namespace Deep {",                                          # 30
    "int DeepFunc(int x)",                                       # 31
    "{",                                                         # 32
    "    return x;",                                             # 33
    "}",                                                         # 34
    "}  // namespace Deep",                                      # 35
    "",                                                          # 36
    "}  // namespace Outer::Inner",                              # 37
    "",                                                          # 38
    "void Widget::Lonely() {",                                   # 39
    "    const char* s = \"void Fake() {\";",                    # 40
    "}",                                                         # 41
    "",                                                          # 42
    "#ifndef FORGEPACT_RELEASE",                                 # 43
    "static int ResearchOnly(int n) {",                          # 44
    "    return n;",                                             # 45
    "}",                                                         # 46
    "#endif",                                                    # 47
    "",                                                          # 48
    "class Gadget {",                                            # 49
    "public:",                                                   # 50
    "    Gadget() : m_value{0}, m_other(1) {",                   # 51
    "    }",                                                     # 52
    "    int Size() const { return m_value; }",                  # 53
    "private:",                                                  # 54
    "    int m_value;",                                          # 55
    "    int m_other;",                                          # 56
    "};",                                                        # 57
    "",                                                          # 58
    "template <typename T>",                                     # 59
    "T Twice(T v) {",                                            # 60
    "    return v + v;",                                         # 61
    "}",                                                         # 62
    "",
])

PY = "\r\n".join([
    "import functools",                                          # 1
    "",                                                          # 2
    "CONST = {\"a\": \"def fake(): pass\"}",                     # 3
    "",                                                          # 4
    "",                                                          # 5
    "def plain(x):",                                             # 6
    "    return x",                                              # 7
    "",                                                          # 8
    "",                                                          # 9
    "# a comment above, not printed",                            # 10
    "@functools.lru_cache(maxsize=None)",                        # 11
    "@other",                                                    # 12
    "def decorated(y):",                                         # 13
    "    \"\"\"doc\"\"\"",                                       # 14
    "    return y",                                              # 15
    "",                                                          # 16
    "",                                                          # 17
    "async def fetcher():",                                      # 18
    "    return 1",                                              # 19
    "",                                                          # 20
    "",                                                          # 21
    "class Box:",                                                # 22
    "    \"\"\"A box.\"\"\"",                                    # 23
    "",                                                          # 24
    "    def size(self):",                                       # 25
    "        return 2",                                          # 26
    "",                                                          # 27
    "    @property",                                             # 28
    "    def label(self):",                                      # 29
    "        return \"box\"",                                    # 30
    "",                                                          # 31
    "    async def load(self):",                                 # 32
    "        def inner():",                                      # 33
    "            return 3",                                      # 34
    "        return inner()",                                    # 35
    "",
])

JS = "\n".join([
    "// --- Section banner ---------------------------------------",  # 1
    "const RX = /a{1,2}}/g",                                     # 2
    "",                                                          # 3
    "const TEMPLATE = `outer { ${cond ? `inner } ${deep({ x: 1 })} {` : '}'} tail }`",  # 4
    "",                                                          # 5
    "export async function alpha(a, b) {",                       # 6
    "  const s = '}'",                                           # 7
    "  return `${a}{`",                                          # 8
    "}",                                                         # 9
    "",                                                          # 10
    "function beta() {",                                         # 11
    "  function nestedHelper() {",                               # 12
    "    return 1",                                              # 13
    "  }",                                                       # 14
    "  return nestedHelper()",                                   # 15
    "}",                                                         # 16
    "",                                                          # 17
    "export class Gamma extends Base {",                         # 18
    "  constructor() {",                                         # 19
    "    super()",                                               # 20
    "  }",                                                       # 21
    "  async run(x) {",                                          # 22
    "    if (x) { return /}/.test(x) }",                         # 23
    "    return 0",                                              # 24
    "  }",                                                       # 25
    "  static make() { return new Gamma() }",                    # 26
    "}",                                                         # 27
    "",                                                          # 28
    "const delta = {",                                           # 29
    "  a: 1,",                                                   # 30
    "  b: [1, 2],",                                              # 31
    "}",                                                         # 32
    "",                                                          # 33
    "let epsilon = (v) =>",                                      # 34
    "  v + 1",                                                   # 35
    "",                                                          # 36
    "var zeta = 3",                                              # 37
    "",
])

TS = "\n".join([
    "export interface Shape {",                                  # 1
    "  area(): number",                                          # 2
    "  name: string",                                            # 3
    "}",                                                         # 4
    "",                                                          # 5
    "export function pick<T extends { id: number }>(items: T[], id: number): T | undefined {",  # 6
    "  return items.find((i) => i.id === id)",                   # 7
    "}",                                                         # 8
    "",                                                          # 9
    "export type Pair = {",                                      # 10
    "  left: number",                                            # 11
    "  right: number",                                           # 12
    "}",                                                         # 13
    "",                                                          # 14
    "export const enum Color {",                                 # 15
    "  Red,",                                                    # 16
    "  Blue,",                                                   # 17
    "}",                                                         # 18
    "",                                                          # 19
    "class Holder<T> {",                                         # 20
    "  private value: T",                                        # 21
    "  get(): T {",                                              # 22
    "    return this.value",                                     # 23
    "  }",                                                       # 24
    "}",                                                         # 25
    "",
])


class CodeModeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="hstk-symbols-")
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, name, text):
        path = self.dir / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def run_section(self, *args, cwd=None):
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, cwd=cwd)
        return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")

    def toc(self, path, *extra):
        code, out, err = self.run_section(path, "--toc", *extra)
        self.assertEqual(code, 0, err)
        rows = {}
        for line in out.splitlines():
            m = TOC_LINE.match(line)
            self.assertIsNotNone(m, f"not a toc line: {line!r}")
            rows[m.group(4)] = (int(m.group(1)), int(m.group(2)), m.group(3))
        return out, rows

    def lookup(self, path, name, *extra):
        code, out, err = self.run_section(path, name, *extra)
        self.assertEqual(code, 0, err)
        header, _, body = out.partition("\n")
        return header, body

    def assertSpan(self, path, name, first, last):
        header, body = self.lookup(path, name)
        self.assertRegex(header, rf"^-- {re.escape(str(path))} lines {first}-{last} \(")
        lines = body.rstrip("\n").split("\n")
        self.assertEqual(len(lines), last - first + 1, body)
        return header, lines


class TestCpp(CodeModeCase):
    def setUp(self):
        super().setUp()
        self.path = self.write("fixture.hpp", CPP)

    def test_toc_lists_every_definition_in_file_order_with_its_range(self):
        out, rows = self.toc(self.path)
        expected = {
            "ScanThings": (8, 14, "function"),
            "OneLiner": (16, 16, "function"),
            "Widget": (18, 23, "struct"),
            "Widget::Size": (19, 21, "method"),
            "Mode": (25, 28, "enum"),
            "DeepFunc": (31, 34, "function"),
            "Widget::Lonely": (39, 41, "function"),
            "ResearchOnly": (44, 46, "function"),
            "Gadget": (49, 57, "class"),
            "Gadget::Gadget": (51, 52, "method"),
            "Gadget::Size": (53, 53, "method"),
            "Twice": (59, 62, "function"),
        }
        self.assertEqual(rows, expected)
        starts = [int(line.split("-")[0]) for line in out.splitlines()]
        self.assertEqual(starts, sorted(starts))
        # Controls: a brace in a string, a declaration, a data member.
        for absent in ("Fake", "m_value", "Outer", "Deep"):
            self.assertNotIn(absent, rows)

    def test_a_multi_line_signature_is_printed_whole_without_the_comment_above(self):
        header, lines = self.assertSpan(self.path, "ScanThings", 8, 14)
        self.assertIn("(function Outer::Inner::ScanThings)", header)
        self.assertEqual(lines[0], "inline void ScanThings(")
        self.assertEqual(lines[-1], "}")
        self.assertIn("    char open = '{'", lines)
        self.assertNotIn("Doc comment", "\n".join(lines))
        self.assertNotIn("OneLiner", "\n".join(lines))

    def test_a_body_on_the_signature_line_is_one_line(self):
        _, lines = self.assertSpan(self.path, "OneLiner", 16, 16)
        self.assertEqual(lines, ["inline bool OneLiner(int v) { return v == '}'; }"])

    def test_namespace_nesting_and_a_brace_on_its_own_line(self):
        _, lines = self.assertSpan(self.path, "DeepFunc", 31, 34)
        self.assertEqual(lines[0], "int DeepFunc(int x)")

    def test_a_function_inside_the_research_guard_is_found(self):
        _, lines = self.assertSpan(self.path, "ResearchOnly", 44, 46)
        self.assertNotIn("#endif", lines)

    def test_a_template_prefix_and_a_brace_initialiser_belong_to_the_definition(self):
        _, lines = self.assertSpan(self.path, "Twice", 59, 62)
        self.assertEqual(lines[0], "template <typename T>")
        self.assertSpan(self.path, "Gadget::Gadget", 51, 52)

    def test_an_ambiguous_name_exits_4_and_its_qualified_name_resolves_it(self):
        code, out, err = self.run_section(self.path, "Size")
        self.assertEqual(code, 4)
        self.assertEqual(out, "")
        self.assertIn("19-21", err)
        self.assertIn("53-53", err)
        _, lines = self.assertSpan(self.path, "Widget::Size", 19, 21)
        self.assertIn("        return 1;", lines)
        self.assertNotIn("m_value", "\n".join(lines))

    def test_a_case_insensitive_name_is_the_last_tier(self):
        self.assertSpan(self.path, "oneliner", 16, 16)

    def test_no_match_exits_3_and_lists_names_containing_the_request(self):
        code, out, err = self.run_section(self.path, "Scan")
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertIn("ScanThings", err)
        self.assertNotIn("Twice", err)

    def test_grep_prints_matching_body_lines_with_numbers_and_context(self):
        code, out, _ = self.run_section(self.path, "ScanThings", "--grep", "open")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"(?m)^11: +char open = '\{'$")
        self.assertRegex(out, r"(?m)^9- +int a,$")
        self.assertRegex(out, r"(?m)^13- +if \(a\)")
        self.assertNotRegex(out, r"(?m)^8[:-]")
        code, out, err = self.run_section(self.path, "ScanThings", "--grep", "zz-nothing")
        self.assertEqual(code, 7)
        self.assertIn("zz-nothing", err)

    def test_toc_grep_filters_by_name(self):
        out, rows = self.toc(self.path, "--grep", "size")
        self.assertEqual(set(rows), {"Widget::Size", "Gadget::Size"})


class TestPython(CodeModeCase):
    def setUp(self):
        super().setUp()
        self.path = self.write("fixture.py", PY)

    def test_toc_lists_top_level_definitions_and_methods(self):
        _, rows = self.toc(self.path)
        self.assertEqual(rows, {
            "plain": (6, 7, "def"),
            "decorated": (11, 15, "def"),
            "fetcher": (18, 19, "async def"),
            "Box": (22, 35, "class"),
            "Box.size": (25, 26, "def"),
            "Box.label": (28, 30, "def"),
            "Box.load": (32, 35, "async def"),
        })
        self.assertNotIn("inner", rows)
        self.assertNotIn("fake", rows)

    def test_the_span_includes_decorators_and_not_the_comment_above(self):
        _, lines = self.assertSpan(self.path, "decorated", 11, 15)
        self.assertEqual(lines[0], "@functools.lru_cache(maxsize=None)")
        self.assertEqual(lines[-1], "    return y")
        _, lines = self.assertSpan(self.path, "Box.label", 28, 30)
        self.assertEqual(lines[0], "    @property")

    def test_a_syntax_error_exits_2(self):
        path = self.write("broken.py", "def broken(:\n    pass\n")
        code, out, err = self.run_section(path, "broken")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("broken.py", err)


class TestJavaScript(CodeModeCase):
    def setUp(self):
        super().setUp()
        self.path = self.write("fixture.mjs", JS)

    def test_toc_survives_templates_and_regex_literals_holding_braces(self):
        _, rows = self.toc(self.path)
        self.assertEqual(rows, {
            "RX": (2, 2, "const"),
            "TEMPLATE": (4, 4, "const"),
            "alpha": (6, 9, "async function"),
            "beta": (11, 16, "function"),
            "Gamma": (18, 27, "class"),
            "Gamma.constructor": (19, 21, "method"),
            "Gamma.run": (22, 25, "method"),
            "Gamma.make": (26, 26, "method"),
            "delta": (29, 32, "const"),
            "epsilon": (34, 35, "let"),
            "zeta": (37, 37, "var"),
        })
        self.assertNotIn("nestedHelper", rows)

    def test_a_nested_definition_is_found_by_lookup(self):
        header, lines = self.assertSpan(self.path, "nestedHelper", 12, 14)
        self.assertEqual(lines[0], "  function nestedHelper() {")

    def test_a_const_ends_where_its_brackets_close_and_a_continuation_stays(self):
        _, lines = self.assertSpan(self.path, "delta", 29, 32)
        self.assertNotIn("epsilon", "\n".join(lines))
        _, lines = self.assertSpan(self.path, "epsilon", 34, 35)
        self.assertEqual(lines[-1], "  v + 1")

    def test_a_method_by_its_qualified_name(self):
        _, lines = self.assertSpan(self.path, "Gamma.run", 22, 25)
        self.assertNotIn("static make", "\n".join(lines))


class TestTypeScript(CodeModeCase):
    def setUp(self):
        super().setUp()
        self.path = self.write("fixture.ts", TS)

    def test_generics_interfaces_and_types(self):
        _, rows = self.toc(self.path)
        self.assertEqual(rows, {
            "Shape": (1, 4, "interface"),
            "pick": (6, 8, "function"),
            "Pair": (10, 13, "type"),
            "Color": (15, 18, "enum"),
            "Holder": (20, 25, "class"),
            "Holder.get": (22, 24, "method"),
        })
        # Controls: an interface's member is not a method, a call is not one.
        self.assertNotIn("Shape.area", rows)
        self.assertNotIn("find", rows)
        _, lines = self.assertSpan(self.path, "pick", 6, 8)
        self.assertNotIn("Pair", "\n".join(lines))


class TestDispatchAndScale(CodeModeCase):
    def test_a_markdown_file_keeps_the_heading_behaviour(self):
        path = self.write("notes.md", "## def plain(x):\nbody\n## Other\nx\n")
        code, out, _ = self.run_section(path, "def plain(x):")
        self.assertEqual(code, 0)
        self.assertEqual(out, "## def plain(x):\nbody\n")
        code, _, _ = self.run_section(path, "plain")
        self.assertEqual(code, 3, "a markdown file must not be read as code")

    def test_section_and_the_index_agree_on_which_files_are_code(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("section_under_test", SCRIPT)
        section = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(section)
        self.assertEqual(section.CODE_SUFFIXES, section._source_index().SYMBOL_SUFFIXES)

    def test_the_symbol_index_is_found_from_any_working_directory(self):
        path = self.write("fixture.py", PY)
        code, out, err = self.run_section(path, "plain", cwd=self.dir)
        self.assertEqual(code, 0, err)
        self.assertIn("def plain(x):", out)

    def test_the_toc_caps_at_20kb_and_says_how_to_narrow_it(self):
        many = "\n".join(f"def a_rather_long_function_name_number_{k:04d}(x):\n    return x\n" for k in range(600))
        path = self.write("many.py", many)
        code, out, err = self.run_section(path, "--toc")
        self.assertEqual(code, 0, err)
        self.assertLess(len(out.encode("utf-8")), 4096)
        self.assertIn("600 symbols", out)
        self.assertIn("--grep", out)
        self.assertNotRegex(out, TOC_LINE.pattern.replace("^", "(?m)^"))
        # Control: under the cap, the listing is printed whole.
        few = self.write("few.py", "\n".join(f"def f{k}(x):\n    return x\n" for k in range(50)))
        _, rows = self.toc(few)
        self.assertEqual(len(rows), 50)
        # And --grep narrows a capped file to a listing.
        _, rows = self.toc(path, "--grep", "number_0042")
        self.assertEqual(list(rows), ["a_rather_long_function_name_number_0042"])

    def test_a_2_5mb_cpp_file_is_indexed_and_looked_up_in_under_10_seconds(self):
        parts = ["#pragma once", "namespace Big {"]
        k, size = 0, 0
        while size < 2_600_000:
            chunk = [
                f"// helper {k}: a comment with a brace {{ in it",
                f"static int GeneratedFunction{k:05d}(int value, const char* label = \"}}\")",
                "{",
                f"    if (value > {k}) {{ return value - {k}; }}",
                "    for (int i = 0; i < 4; ++i) { value += i; }",
                "    return value * 2 + label[0];",
                "}",
            ]
            if k % 200 == 0:
                chunk.insert(0, f"// ===== Region {k // 200} ===============================================")
            parts.extend(chunk)
            size += sum(len(p) + 2 for p in chunk)
            k += 1
        parts.append("}  // namespace Big")
        path = self.write("big.cpp", "\r\n".join(parts) + "\r\n")
        self.assertGreaterEqual(path.stat().st_size, 2_500_000)
        middle = k // 2
        started = time.perf_counter()
        code, out, err = self.run_section(path, "--toc")
        toc_seconds = time.perf_counter() - started
        self.assertEqual(code, 0, err)
        self.assertIn(f"{k} symbols", out)
        self.assertIn("Region 1", out)
        started = time.perf_counter()
        code, out, err = self.run_section(path, f"GeneratedFunction{middle:05d}")
        lookup_seconds = time.perf_counter() - started
        self.assertEqual(code, 0, err)
        lines = out.rstrip("\n").split("\n")
        self.assertEqual(lines[1], f"static int GeneratedFunction{middle:05d}(int value, const char* label = \"}}\")")
        self.assertEqual(lines[-1], "}")
        self.assertEqual(len(lines), 1 + 6)
        self.assertLess(toc_seconds, 10.0)
        self.assertLess(lookup_seconds, 10.0)


class TestTheHubsOwnFiles(CodeModeCase):
    """The acceptance criteria, restated on the files they name."""

    def test_a_function_inside_a_namespace_in_player_hpp(self):
        code, out, err = self.run_section(REPO / "hs-game-sdk/cpp/include/hs_game_sdk/player.hpp", "IsInstanceHandle")
        self.assertEqual(code, 0, err)
        self.assertIn("inline bool IsInstanceHandle(const RValue& value) {", out)
        self.assertEqual([l for l in out.splitlines() if l.strip()][-1], "}")
        self.assertNotIn("ScanContainerForRelics", out)

    def test_a_python_function_in_the_audit(self):
        code, out, err = self.run_section(REPO / "tools/workorder_audit.py", "rule_r26_reread_after_write")
        self.assertEqual(code, 0, err)
        self.assertIn("def rule_r26_reread_after_write(", out)
        self.assertIn('return RuleResult("R26"', out)
        self.assertNotIn("ALL_RULES", out)

    def test_a_js_function_in_the_workflow(self):
        code, out, err = self.run_section(REPO / ".claude/workflows/workorder-rounds.js", "amendOnce")
        self.assertEqual(code, 0, err)
        self.assertIn("async function amendOnce(", out)
        self.assertIn("amend-check:", out)
        self.assertNotIn("3b: items mode", out)

    def test_the_workflows_toc_grep(self):
        out, rows = self.toc(REPO / ".claude/workflows/workorder-rounds.js", "--grep", "amend")
        for name in ("amendOnce", "amendPlan", "restoreAmendment"):
            self.assertIn(name, rows)
            start, end, _ = rows[name]
            self.assertLess(start, end)


if __name__ == "__main__":
    unittest.main()
