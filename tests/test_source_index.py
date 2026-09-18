"""Tests for tools/source_index.py.

A small synthetic fixture (built in code, not read from a file, so the
exact 1-based line numbers below are trustworthy) covers the banner styles,
a nested guard span, and a function on each side of the guard. A separate
smoke test runs the real thing against ForgePact/plugin/ModuleMain.cpp and
is skipped when that file is not present in this checkout.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import source_index as si  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_MAIN = REPO_ROOT / "ForgePact" / "plugin" / "ModuleMain.cpp"

# Line numbers below are 1-based positions in this exact list (index + 1).
FIXTURE_LINES = [
    "// ===== Alpha section =====",           # 1
    "int AlphaHelper()",                       # 2
    "{",                                        # 3
    "    return 1;",                            # 4
    "}",                                        # 5
    "",                                          # 6
    "// --- Alpha sub note ---",                # 7
    "static void UnguardedFunc()",              # 8
    "{",                                         # 9
    "    int x = 1;",                            # 10
    "    if (x)",                                # 11
    "    {",                                     # 12
    "        x = 2;",                            # 13
    "    }",                                     # 14
    "}",                                          # 15
    "",                                            # 16
    "#ifndef FORGEPACT_RELEASE",                   # 17
    "// ===== Research section =====",             # 18
    "static void GuardedFunc()",                    # 19
    "{",                                              # 20
    "#ifdef SOMETHING_ELSE",                           # 21
    "    int y = 1;",                                   # 22
    "#else",                                              # 23
    "    int y = 2;",                                      # 24
    "#endif",                                                # 25
    "}",                                                       # 26
    "#endif",                                                    # 27
    "",                                                          # 28
    "// ===== Beta section =====",                              # 29
    "void BetaHelper(int a, int b)",                            # 30
    "{",                                                         # 31
    "    return;",                                              # 32
    "}",                                                         # 33
]


def _index(lines=FIXTURE_LINES, guard=si.DEFAULT_GUARD):
    clean = si.strip_comments_and_literals(lines)
    guarded = si.compute_guarded_lines(clean, guard)
    regions = si.build_regions(lines, guarded)
    functions = si.find_functions(clean)
    return regions, functions, guarded


class RegionTests(unittest.TestCase):
    def test_four_banners_produce_four_regions(self):
        regions, _functions, _guarded = _index()
        self.assertEqual(
            [(r["start"], r["end"], r["title"]) for r in regions],
            [
                (1, 6, "Alpha section"),
                (7, 17, "Alpha sub note"),
                (18, 28, "Research section"),
                (29, 33, "Beta section"),
            ],
        )

    def test_region_inside_guard_is_flagged(self):
        regions, _functions, _guarded = _index()
        by_title = {r["title"]: r for r in regions}
        self.assertTrue(by_title["Research section"]["guarded"])

    def test_region_outside_guard_is_not_flagged(self):
        regions, _functions, _guarded = _index()
        by_title = {r["title"]: r for r in regions}
        # A control alongside the positive case above: the same file, a
        # region whose lines are never inside the #ifndef span.
        self.assertFalse(by_title["Alpha section"]["guarded"])
        self.assertFalse(by_title["Alpha sub note"]["guarded"])
        self.assertFalse(by_title["Beta section"]["guarded"])


class GuardSpanTests(unittest.TestCase):
    def test_nested_guard_span_stays_guarded_through_inner_conditional(self):
        # Lines 21-25 are inside an unrelated #ifdef/#else/#endif that is
        # itself nested inside the outer #ifndef FORGEPACT_RELEASE span
        # (lines 17-27). Every one of them must still read as guarded,
        # regardless of which branch of the inner conditional they are in.
        _regions, _functions, guarded = _index()
        for lineno in range(18, 27):
            self.assertIn(lineno, guarded, f"line {lineno} should be guarded")
        for lineno in list(range(1, 17)) + [28]:
            self.assertNotIn(lineno, guarded, f"line {lineno} should not be guarded")

    def test_unrelated_macro_does_not_toggle_guard(self):
        clean = si.strip_comments_and_literals([
            "#ifdef SOMETHING_ELSE",
            "int a;",
            "#else",
            "int b;",
            "#endif",
        ])
        guarded = si.compute_guarded_lines(clean, si.DEFAULT_GUARD)
        self.assertEqual(guarded, set())

    def test_ifdef_guard_else_branch_is_guarded(self):
        # The *shipping* branch is #ifdef GUARD ... #else <research> #endif
        # -- the else side is the research side and must read as guarded.
        clean = si.strip_comments_and_literals([
            "#ifdef FORGEPACT_RELEASE",
            "int shipping;",
            "#else",
            "int research;",
            "#endif",
        ])
        guarded = si.compute_guarded_lines(clean, si.DEFAULT_GUARD)
        self.assertNotIn(2, guarded)
        self.assertIn(4, guarded)


class FunctionTests(unittest.TestCase):
    def test_functions_found_with_ranges(self):
        _regions, functions, _guarded = _index()
        self.assertEqual(
            functions,
            [
                ("AlphaHelper", 2, 5),
                ("UnguardedFunc", 8, 15),
                ("GuardedFunc", 19, 26),
                ("BetaHelper", 30, 33),
            ],
        )

    def test_function_outside_guard(self):
        _regions, functions, guarded = _index()
        start, end = next((s, e) for (n, s, e) in functions if n == "UnguardedFunc")
        self.assertTrue(all(ln not in guarded for ln in range(start, end + 1)))

    def test_function_inside_guard(self):
        _regions, functions, guarded = _index()
        start, end = next((s, e) for (n, s, e) in functions if n == "GuardedFunc")
        self.assertTrue(all(ln in guarded for ln in range(start, end + 1)))

    def test_nested_brace_block_is_not_a_second_function(self):
        # The `if (x) { x = 2; }` inside UnguardedFunc must not itself be
        # reported as a file-scope function.
        _regions, functions, _guarded = _index()
        names = [n for (n, _s, _e) in functions]
        self.assertEqual(names.count("UnguardedFunc"), 1)
        self.assertNotIn("if", names)


class FindTests(unittest.TestCase):
    def test_find_matches_region_title_case_insensitively(self):
        regions, functions, _guarded = _index()
        region_hits, _func_hits = si.do_find(regions, functions, "research")
        self.assertEqual([r["title"] for r in region_hits], ["Research section"])

    def test_find_matches_function_name(self):
        regions, functions, _guarded = _index()
        _region_hits, func_hits = si.do_find(regions, functions, "BetaHelper")
        self.assertEqual([(h["name"], h["start"], h["end"]) for h in func_hits],
                          [("BetaHelper", 30, 33)])

    def test_find_no_match_returns_empty(self):
        regions, functions, _guarded = _index()
        region_hits, func_hits = si.do_find(regions, functions, "NoSuchThing")
        self.assertEqual(region_hits, [])
        self.assertEqual(func_hits, [])


class AtLineTests(unittest.TestCase):
    def test_at_line_inside_a_function_and_region(self):
        regions, functions, _guarded = _index()
        region = si._region_at(regions, 4)  # inside AlphaHelper's body
        function = si._function_at(functions, 4)
        self.assertEqual(region["title"], "Alpha section")
        self.assertEqual(function, {"name": "AlphaHelper", "start": 2, "end": 5})

    def test_at_line_inside_guarded_function(self):
        regions, functions, _guarded = _index()
        region = si._region_at(regions, 21)  # inside GuardedFunc, inner #ifdef
        function = si._function_at(functions, 21)
        self.assertEqual(region["title"], "Research section")
        self.assertEqual(function, {"name": "GuardedFunc", "start": 19, "end": 26})

    def test_at_line_with_no_function(self):
        regions, functions, _guarded = _index()
        function = si._function_at(functions, 6)  # the blank line between regions
        self.assertIsNone(function)


class BannerParsingTests(unittest.TestCase):
    def test_pure_separator_line_is_not_a_banner(self):
        banners = si.find_banners([
            "// ============================================================",
            "// ===== Real title ============================================",
            "// ============================================================",
        ])
        self.assertEqual(banners, [(2, "Real title")])

    def test_dash_style_banner(self):
        banners = si.find_banners(["// ---- research profiler ----------------------------"])
        self.assertEqual(banners, [(1, "research profiler")])


class CommentStrippingTests(unittest.TestCase):
    def test_brace_inside_string_literal_is_ignored(self):
        clean = si.strip_comments_and_literals(['const char* s = "{";', "int Foo() {", "}"])
        # Only the real braces on line 2/3 should register; line 1's is a
        # blanked-out string literal.
        depth = 0
        for line in clean:
            depth += line.count("{") - line.count("}")
        self.assertEqual(depth, 0)
        self.assertNotIn("{", clean[0])

    def test_brace_inside_line_comment_is_ignored(self):
        clean = si.strip_comments_and_literals(["int Foo() { // note: { not a real brace", "}"])
        self.assertEqual(clean[0].count("{"), 1)

    def test_block_comment_spanning_lines(self):
        clean = si.strip_comments_and_literals(["/* start", "middle { brace", "end */ int x;"])
        joined = "".join(clean)
        self.assertNotIn("{", joined)


class CLITests(unittest.TestCase):
    """Exercise main() through argparse, including the on-disk file path
    and JSON output, without going through a subprocess for every case."""

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.fixture_path = Path(self._tmpdir.name) / "fixture.cpp"
        self.fixture_path.write_text("\n".join(FIXTURE_LINES) + "\n", encoding="utf-8")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "source_index.py"), *args],
            capture_output=True, text=True,
        )

    def test_default_mode_is_regions(self):
        result = self._run(str(self.fixture_path))
        self.assertEqual(result.returncode, 0)
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        self.assertEqual(len(lines), 4)
        self.assertIn("Research section", lines[2])
        self.assertIn("[R]", lines[2])

    def test_regions_json(self):
        result = self._run(str(self.fixture_path), "--regions", "--json")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        titles = [r["title"] for r in payload["regions"]]
        self.assertEqual(titles, ["Alpha section", "Alpha sub note", "Research section", "Beta section"])

    def test_functions_mode(self):
        result = self._run(str(self.fixture_path), "--functions")
        self.assertEqual(result.returncode, 0)
        self.assertIn("BetaHelper", result.stdout)
        self.assertIn("30-33", result.stdout)

    def test_find_mode(self):
        result = self._run(str(self.fixture_path), "--find", "Research")
        self.assertEqual(result.returncode, 0)
        self.assertIn("region", result.stdout)
        self.assertIn("Research section", result.stdout)

    def test_at_mode(self):
        result = self._run(str(self.fixture_path), "--at", "21")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Research section", result.stdout)
        self.assertIn("GuardedFunc", result.stdout)

    def test_conflicting_modes_is_usage_error(self):
        result = self._run(str(self.fixture_path), "--regions", "--functions")
        self.assertEqual(result.returncode, 2)

    def test_missing_file_is_usage_error(self):
        result = self._run(str(Path(self._tmpdir.name) / "nope.cpp"))
        self.assertEqual(result.returncode, 2)

    def test_custom_guard_name(self):
        clean = si.strip_comments_and_literals([
            "#ifndef MY_GUARD",
            "int a;",
            "#endif",
        ])
        guarded_default = si.compute_guarded_lines(clean, si.DEFAULT_GUARD)
        guarded_custom = si.compute_guarded_lines(clean, "MY_GUARD")
        self.assertEqual(guarded_default, set())
        self.assertEqual(guarded_custom, {1, 2})


@unittest.skipUnless(MODULE_MAIN.is_file(), "ForgePact/plugin/ModuleMain.cpp not present in this checkout")
class ModuleMainSmokeTest(unittest.TestCase):
    def test_regions_count_and_find_pp_backing_id_check(self):
        lines = si.read_lines(MODULE_MAIN)
        clean = si.strip_comments_and_literals(lines)
        guarded = si.compute_guarded_lines(clean, si.DEFAULT_GUARD)
        regions = si.build_regions(lines, guarded)
        functions = si.find_functions(clean)

        self.assertGreaterEqual(len(regions), 90, f"only {len(regions)} regions found")

        region_hits, func_hits = si.do_find(regions, functions, "PpBackingIdCheck")
        self.assertTrue(func_hits, "expected a function match for PpBackingIdCheck")
        start, end = func_hits[0]["start"], func_hits[0]["end"]
        defining_line = next(
            i for i, l in enumerate(lines, start=1)
            if "PpBackingIdCheck" in l and l.strip().startswith(("static", "void"))
        )
        self.assertTrue(start <= defining_line <= end,
                         f"range {start}-{end} does not contain defining line {defining_line}")


if __name__ == "__main__":
    unittest.main()
