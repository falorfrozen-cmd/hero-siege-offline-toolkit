"""Pin the shape of `third_party/aurie/` -- offline, stdlib only, no MSVC.

The modified AurieCore.dll is one pinned upstream commit (Aurie v2.0.2) plus a
patch series, kept the way `third_party/yytoolkit/` keeps YYToolkit's (ADR
0002, ADR 0006). `tools/build_aurie.py verify-dll` is the check on a *binary*;
this file is the check on the *series*, and it runs on the ubuntu CI where
nothing can be built: every rule below is about text in the repository.

The rules are `tests/test_yytoolkit_patch_series.py`'s, translated to Aurie.
That file's helpers (the patch parser, the message, legal, address and path
rules, the blob chain) are imported from it, not copied, so a rule sharpened
there is sharpened here the same day; that file itself is not edited. What is
pinned, in the order of the test classes:

  - `patches/*.patch` and `patches/series` list the same files, numbered
    contiguously from 0001, in numeric order, and the build tool reads them;
  - the README's patch table and the NOTICE name exactly those files, in order;
  - every patch is a mail-format patch whose message carries the five fields,
    whose `Log-markers:` lines parse under the build tool's own grammar, and
    whose hunk counts add up;
  - every declared marker literally occurs in a line the same patch ADDS to a
    file compiled into the DLL (not under `Aurie/hs-tests/`);
  - the full upstream commit and tree ids are written in `upstream.json` and
    nowhere else, and an abbreviation quoted in the docs is a prefix of it;
  - `index <pre>..<post>` lines chain across the series per path;
  - no patch leaves `Aurie/`, carries a binary hunk, or touches the
    plugin-facing `Aurie/source/framework/shared.hpp` (ForgePact compiles
    against the unmodified one), and no host test is pulled into the DLL;
  - the freeze keeps its contract (context of patch 0002): no added line
    calls `MmCreateHook(`, `MmpFreezeCurrentProcess` / `MmpResumeCurrentProcess`
    are neither added nor removed (they keep their names, signatures and call
    sites), `NtGetNextThread` is resolved by name, the freeze unit includes
    Windows SDK headers only, it is in the project's `ClCompile` list, the host
    test names every baseline and target case, and the two log prefixes and
    the identity line are the literal strings the live checks read;
  - patches and `series` are LF, end in a newline, keep the TAB that ends a
    header path containing a space, and `.gitattributes` still protects them;
  - no decompiler or VM listing text, no hand-resolved address and no
    person-identifying absolute path is ADDED by a patch, written in a patch
    message, or present in the README or the NOTICE, and a local evidence file
    a message cites is explained by the README;
  - the NOTICE says what an AGPL modification notice has to, and `LICENSE` is
    upstream's blob;
  - the directory holds text only, the hub docs point at it, and
    `series_revision` is the literal patch 0001 compiles into the DLL.

Rules that would pass while doing nothing come with controls: each
Aurie-specific rule also runs on a synthetic patch, once with the offending
text as an ADDED line (reported) and once as a CONTEXT line, which is
upstream's and not ours (not reported).

Deliberately NOT caught, written down rather than implied:

  - whether a patch *applies*. That needs upstream's blobs, which the hub must
    not vendor, so it is the optional last class: set `HSTK_AURIE_UPSTREAM` to
    a local clone that contains the pinned commit and the series is exported
    and applied for real through the build tool. Without it, it SKIPS.
  - whether ForgePact pins this series' DLL. `tests/test_forgepact_aurie_pin.py`
    owns that check.
  - anything about the built DLL, the freeze's behaviour or the game. The host
    test inside patch 0002 is run by `tools/build_aurie.py hosttests`, and the
    README's launch gate is the record of the game.
"""

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Iterable, Iterator, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
PIN_DIR = ROOT / "third_party" / "aurie"
PATCH_DIR = PIN_DIR / "patches"
SERIES = PATCH_DIR / "series"
README = PIN_DIR / "README.md"
NOTICE = PIN_DIR / "NOTICE.md"
LICENSE = PIN_DIR / "LICENSE"
UPSTREAM_JSON = PIN_DIR / "upstream.json"
TOOL_PATH = ROOT / "tools" / "build_aurie.py"
YYTK_SERIES_TEST = ROOT / "tests" / "test_yytoolkit_patch_series.py"

#: The hub documents that must keep pointing at the series directory.
SYNCED_DOCS = (
    "AGENTS.md",
    "README.md",
    "docs/submodules/README.md",
    "docs/submodules/HS-Offline-Tracker/instructions.md",
    ".agents/skills/submodule-context/SKILL.md",
)

#: upstream's LICENSE at the pin, as `git ls-tree` names it. The same blob as
#: third_party/yytoolkit/LICENSE: both upstreams ship the same AGPL-3.0 text.
LICENSE_BLOB = "0ad25db4bd1d86c452db3f9602ccdbe172438f52"

UPSTREAM_ENV = "HSTK_AURIE_UPSTREAM"
SOURCE_ROOT = "Aurie/"
HOST_TESTS = "Aurie/hs-tests/"
#: What plugins compile against (ForgePact pins upstream's shared.hpp), and the
#: parts of upstream's repository that are not the DLL. The last three are
#: outside SOURCE_ROOT anyway; they are named so the refusal says why.
FORBIDDEN_PREFIXES = ("Aurie/source/framework/shared.hpp", "AuriePatcher/",
                      "AurieInstaller/", "TestModule/")
ALLOWED_SUFFIXES = (".md", ".json", ".patch")
ALLOWED_NAMES = ("series", "LICENSE")

#: The strings the live checks and the plan's criteria read, character for
#: character. A reworded log line fails a live session that cannot say why.
IDENTITY_FORMAT = ('"[hs] Aurie Core %d.%d.%d, Hero Siege patch series %s '
                   '(hero-siege-offline-toolkit, third_party/aurie)"')
FREEZE_PREFIXES = (
    "[hs] MmCreateHook freeze: per-process thread walk",
    "[hs] MmCreateHook freeze: FELL BACK to the system-wide thread snapshot",
)
HOST_TEST_CASES = (
    "baseline-suspends-others", "baseline-scales-with-system",
    "baseline-resumes-unseen", "baseline-misses-late-thread",
    "target-suspends-others", "target-own-threads-only", "target-leaves-unseen",
    "target-catches-late-thread", "target-cost",
)
FREEZE_UNIT = "Aurie/source/framework/Memory Manager/thread_freeze."
FREEZE_PAIR = ("MmpFreezeCurrentProcess", "MmpResumeCurrentProcess")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # Its own name: @dataclass resolves annotations through sys.modules, and
    # the YYToolkit tests load the same files under theirs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load("hstk_aurie_series_test_build_aurie", TOOL_PATH)
# The YYToolkit series test, for its helpers only. Bound to a module object,
# never star-imported, so its test classes are not collected a second time.
yy = _load("hstk_aurie_series_test_yytoolkit_rules", YYTK_SERIES_TEST)

ParsedPatch = yy.ParsedPatch
parse_patch = yy.parse_patch
message_problems = yy.message_problems
legal_problems = yy.legal_problems
patch_lines_we_wrote = yy.patch_lines_we_wrote
address_problems = yy.address_problems
user_path_problems = yy.user_path_problems
unexplained_evidence_problems = yy.unexplained_evidence_problems
chain_problems = yy.BlobChain.chain_problems
git_blob_id = yy.git_blob_id
numbered = yy.numbered
FIELDS = yy.FIELDS


def synthetic_patch(added: str, *, path: str = SOURCE_ROOT + "source/Thing.cpp",
                    **kwargs) -> bytes:
    """yy's well-formed one-hunk patch, on an Aurie path."""
    return yy.synthetic_patch(added, path=path, **kwargs)


def shipped_added(parsed: ParsedPatch) -> Iterator[Tuple[str, int, str]]:
    """Every `+` line outside the host tests: what can reach the DLL."""
    for path, number, text in parsed.added():
        if not path.startswith(HOST_TESTS):
            yield path, number, text


def removed_lines(data: bytes) -> Iterator[Tuple[int, str]]:
    """`-` lines of the hunks (not `--- a/` headers, not the message)."""
    lines = data.decode("utf-8", "replace").split("\n")
    in_diff = False
    for number, line in enumerate(lines, 1):
        if line.startswith("diff --git "):
            in_diff = True
        elif in_diff and line.startswith("-") and not line.startswith("--- "):
            yield number, line[1:]


# --------------------------------------------------------------------------
# the Aurie-specific rules. Each returns the problems it found, so a control
# and the real series go through the same code.
# --------------------------------------------------------------------------

def marker_problems(parsed: ParsedPatch, markers: Iterable[str]) -> List[str]:
    shipped = [text for _path, _number, text in shipped_added(parsed)]
    problems = []
    for marker in markers:
        if any(marker in text for text in shipped):
            continue
        elsewhere = any(marker in text for _p, _n, text in parsed.added())
        problems.append(
            f"{parsed.name}: declares Log-markers literal {marker!r}, but no line it ADDS outside "
            f"{HOST_TESTS} contains that text"
            + (" (only a host test does, and host tests are not in the DLL)" if elsewhere else "")
            + ". verify-dll looks for it in the binary: fix the literal in the message, or the "
              "string in the source, so they are the same characters on one line.")
    return problems


def contract_problems(parsed: ParsedPatch, data: bytes) -> List[str]:
    """Patch 0002's contract with every plugin: hooks attach as before."""
    problems = []
    for path, number, text in parsed.added():
        if "MmCreateHook(" in text:
            problems.append(
                f"{parsed.name}:{number} ({path}): adds a line containing `MmCreateHook(`. The "
                f"series changes the freeze around a hook write, never MmCreateHook itself or "
                f"its call sites.")
        for name in FREEZE_PAIR:
            if re.search(rf"\b{name}\s*\(", text):
                problems.append(
                    f"{parsed.name}:{number} ({path}): adds `{name}(`. It keeps its name, its "
                    f"argument-less void signature and every call site; change its body only.")
    for number, text in removed_lines(data):
        for name in FREEZE_PAIR:
            if re.search(rf"\b{name}\s*\(", text):
                problems.append(
                    f"{parsed.name}:{number}: removes a line with `{name}(` - its definition or a "
                    f"call site. Both stay as upstream has them.")
    return problems


INCLUDE = re.compile(r'^\s*#\s*include\s*([<"])([^>"]+)[>"]')


def unit_include_problems(parsed: ParsedPatch) -> List[str]:
    """The freeze unit compiles with Windows SDK headers only, so the host test
    includes the very file the DLL compiles. A framework header would pull Aurie
    (and SafetyHook) into the host test, or stop it compiling."""
    problems = []
    for path, number, text in parsed.added():
        if not path.startswith(FREEZE_UNIT):
            continue
        match = INCLUDE.match(text)
        if not match:
            continue
        quoted, header = match.group(1) == '"', match.group(2)
        if quoted and header != "thread_freeze.hpp":
            problems.append(
                f"{parsed.name}:{number} ({path}): includes \"{header}\". The freeze unit "
                f"includes Windows SDK headers (<...>) and its own header only.")
    return problems


def series_names() -> List[str]:
    names = []
    for line in SERIES.read_bytes().decode("utf-8", "replace").split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            names.append(line)
    return names


class SeriesCase(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.names = series_names()
        cls.data = {name: (PATCH_DIR / name).read_bytes()
                    for name in cls.names if (PATCH_DIR / name).is_file()}
        cls.parsed = [parse_patch(name, cls.data[name]) for name in cls.names if name in cls.data]
        cls.pin = json.loads(UPSTREAM_JSON.read_text(encoding="utf-8"))
        cls.readme = README.read_text(encoding="utf-8")
        cls.notice = NOTICE.read_text(encoding="utf-8")

    def assertNoProblems(self, problems: List[str], summary: str) -> None:
        if problems:
            self.fail(summary + "\n  " + "\n  ".join(problems))

    def all_added(self) -> List[Tuple[str, str, int, str]]:
        return [(parsed.name, path, number, text)
                for parsed in self.parsed for path, number, text in parsed.added()]


class SeriesAndFilesAgree(SeriesCase):
    NAME = re.compile(r"^(\d{4})-[a-z0-9][a-z0-9-]*\.patch$")

    def test_series_and_patch_files_are_the_same_set(self):
        on_disk = sorted(p.name for p in PATCH_DIR.glob("*.patch"))
        problems = [f"{name} is in third_party/aurie/patches/ but not in patches/series: an "
                    f"unlisted patch is never applied, so it documents a change the DLL lacks"
                    for name in on_disk if name not in self.names]
        problems += [f"patches/series lists {name}, which is not a file in patches/"
                     for name in self.names if name not in on_disk]
        problems += [f"patches/series lists {name} {self.names.count(name)} times"
                     for name in sorted(set(self.names)) if self.names.count(name) > 1]
        self.assertNoProblems(problems, "patches/series and patches/*.patch disagree:")
        self.assertTrue(self.names, "patches/series lists no patches")

    def test_patches_are_numbered_contiguously_and_listed_in_that_order(self):
        problems = []
        for position, name in enumerate(self.names, 1):
            match = self.NAME.match(name)
            if not match:
                problems.append(f"{name}: not NNNN-lower-case-slug.patch")
            elif int(match.group(1)) != position:
                problems.append(f"{name} is line {position} of patches/series but is numbered "
                                f"{match.group(1)}; numbers run from 0001 with no gap")
        self.assertNoProblems(problems, "patch numbering:")

    def test_the_build_tool_reads_the_same_series(self):
        try:
            loaded = tool.load_series(PIN_DIR)
        except tool.ToolError as error:
            self.fail(f"tools/build_aurie.py refuses the series: {error}")
        self.assertEqual([p.name for p in loaded], self.names)

    def test_the_build_tool_builds_this_directory(self):
        self.assertEqual(tool.PRODUCT.pin_dir.resolve(), PIN_DIR.resolve())
        self.assertEqual(tool.PRODUCT.source_root, SOURCE_ROOT)
        self.assertEqual("/".join(tool.PRODUCT.host_tests) + "/", HOST_TESTS)


class ReadmeAndNoticeNameEveryPatch(SeriesCase):
    TABLE_HEADER = "| # | Patch | What it changes | Why |"
    ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|(.*)\|\s*$")

    def table_rows(self) -> List[Tuple[int, str, List[str]]]:
        lines = self.readme.splitlines()
        self.assertIn(self.TABLE_HEADER, lines,
                      f"third_party/aurie/README.md has no patch table headed "
                      f"{self.TABLE_HEADER!r}; this test reads the table by that header")
        rows = []
        for line in lines[lines.index(self.TABLE_HEADER) + 1:]:
            if not line.startswith("|"):
                break
            if re.fullmatch(r"[|\s:-]+", line):
                continue
            match = self.ROW.match(line)
            self.assertIsNotNone(match, f"README.md patch table: cannot read {line[:70]!r}")
            cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", match.group(3))]
            rows.append((int(match.group(1)), match.group(2), cells))
        return rows

    def test_readme_table_lists_the_series_in_order(self):
        rows = self.table_rows()
        self.assertEqual([name for _n, name, _cells in rows], self.names,
                         "third_party/aurie/README.md's patch table and patches/series differ")
        problems = []
        for position, (number, name, cells) in enumerate(rows, 1):
            if number != position:
                problems.append(f"the row for {name} is numbered {number}, it is patch {position}")
            if len(cells) != 2 or not all(cells):
                problems.append(f"the row for {name} needs a non-empty 'What it changes' AND 'Why'")
        self.assertNoProblems(problems, "README.md patch table:")

    def test_notice_names_every_patch_in_order(self):
        positions = []
        for name in self.names:
            self.assertIn(name, self.notice,
                          f"third_party/aurie/NOTICE.md does not name {name}; the notice ships "
                          f"beside the DLL and must list every change")
            positions.append(self.notice.index(name))
        self.assertEqual(positions, sorted(positions),
                         "NOTICE.md lists the patches in another order than patches/series")

    def test_readme_host_test_count_matches_the_patches(self):
        added = sorted(diff.path for parsed in self.parsed for diff in parsed.files
                       if diff.path.startswith(HOST_TESTS) and diff.path.endswith(".cpp")
                       and diff.new_file)
        stated = re.search(r"hs-tests/`\s*\((\d+) files?\)", self.readme)
        self.assertIsNotNone(stated, "README.md must state the host test count as "
                                     "`Aurie/hs-tests/` (<n> file(s))")
        self.assertEqual(int(stated.group(1)), len(added),
                         f"README.md says {stated.group(1)} host test files; the patches add "
                         f"{len(added)}: {', '.join(Path(p).name for p in added)}")


class PatchMessages(SeriesCase):
    def test_controls_a_complete_message_passes_and_a_missing_field_is_named(self):
        data = synthetic_patch("int harmless = 1;")
        self.assertEqual(message_problems(parse_patch("ok.patch", data), data), [])
        for field in FIELDS:
            data = synthetic_patch("int harmless = 1;", drop_field=field)
            problems = message_problems(parse_patch("bad.patch", data), data)
            self.assertEqual(len(problems), 1, problems)
            self.assertIn(f"`{field}:`", problems[0])

    def test_every_patch_carries_mail_headers_and_the_five_fields(self):
        problems = []
        for parsed in self.parsed:
            problems += message_problems(parsed, self.data[parsed.name])
        self.assertNoProblems(problems, "patch messages:")

    def test_every_patch_is_not_yet_offered_upstream(self):
        # The owner decides whether to offer the freeze upstream; until then
        # every message says so, and the README's limitations rely on it.
        for parsed in self.parsed:
            status = yy.header_fields(parsed).get("Upstream-status", [""])[0]
            self.assertTrue(status.startswith("not submitted"), f"{parsed.name}: {status!r}")

    def test_hunk_counts_add_up(self):
        problems = [p for parsed in self.parsed for p in parsed.problems]
        self.assertNoProblems(problems, "a patch was edited by hand (regenerate it with "
                                        "`tools/build_aurie.py make-patch`):")


class DeclaredMarkersAreAdded(SeriesCase):
    def test_controls(self):
        marker = "hs-control: refused candidate"
        source = f'\tDbgPrintEx(LOG_SEVERITY_INFO, "{marker} %p", candidate);'
        added = parse_patch("c.patch", synthetic_patch(source))
        self.assertEqual(marker_problems(added, [marker]), [])

        context_only = parse_patch("c.patch", synthetic_patch("int other = 1;", context=source))
        self.assertEqual(len(marker_problems(context_only, [marker])), 1)
        host_test_only = parse_patch(
            "c.patch", synthetic_patch(source, path=HOST_TESTS + "thing_test.cpp"))
        problems = marker_problems(host_test_only, [marker])
        self.assertEqual(len(problems), 1)
        self.assertIn("only a host test", problems[0])

    def test_every_declared_marker_is_in_a_line_the_patch_adds_to_the_dll_source(self):
        problems, declaring = [], []
        for parsed in self.parsed:
            markers = tool.parse_markers(parsed.name, self.data[parsed.name])
            if markers:
                declaring.append(parsed.name)
            problems += marker_problems(parsed, markers)
        self.assertNoProblems(problems, "declared log markers the patch does not add:")
        self.assertEqual(declaring, self.names,
                         "every patch of this series changes what the DLL logs, so every patch "
                         "declares at least one marker; verify-dll checks each one")


class ThePinIsWrittenOnce(SeriesCase):
    #: Files that must never repeat the commit or tree id: a second copy is the
    #: one that goes stale.
    ELSEWHERE = (
        "tools/build_aurie.py",
        "tools/build_yytoolkit.py",
        "tests/test_build_aurie.py",
        "tests/test_aurie_patch_series.py",
    ) + SYNCED_DOCS

    def elsewhere(self) -> List[Path]:
        paths = [ROOT / rel for rel in self.ELSEWHERE]
        paths += sorted((ROOT / "docs" / "adr").glob("0006-*.md"))
        return [p for p in paths if p.is_file()]

    def test_pin_is_a_full_commit_and_tree(self):
        try:
            pin = tool.load_pin(PIN_DIR)
        except tool.ToolError as error:
            self.fail(f"tools/build_aurie.py refuses third_party/aurie/upstream.json: {error}")
        self.assertEqual(pin.repo, "https://github.com/AurieFramework/Aurie")
        self.assertEqual(pin.tag, "v2.0.2")

    def test_the_commit_and_tree_ids_occur_in_upstream_json_only(self):
        files = [p for p in sorted(PIN_DIR.rglob("*")) if p.is_file()] + self.elsewhere()
        for key in ("commit", "tree"):
            needle = self.pin[key].encode("ascii")
            hits = {p.relative_to(ROOT).as_posix(): p.read_bytes().count(needle) for p in files}
            hits = {rel: count for rel, count in hits.items() if count}
            self.assertEqual(hits, {"third_party/aurie/upstream.json": 1},
                             f"the pinned {key} id must be written once, in upstream.json "
                             f"(abbreviate it to 7 characters in prose). Found: {hits}")

    def test_a_quoted_abbreviation_is_a_prefix_of_the_pin(self):
        commit = self.pin["commit"]
        docs = [README, NOTICE] + [p for p in self.elsewhere() if p.suffix == ".md"]
        docs += [PATCH_DIR / name for name in self.data]
        problems = []
        for path in dict.fromkeys(docs):
            if not path.is_file():
                continue
            text = path.read_bytes().decode("utf-8", "replace")
            if path.suffix == ".patch":
                text = text.split("\ndiff --git ", 1)[0]
            for token in re.findall(r"\b[0-9a-f]{7,40}\b", text):
                if token[:4] == commit[:4] and not commit.startswith(token):
                    problems.append(f"{path.relative_to(ROOT).as_posix()}: {token} starts like "
                                    f"the pinned commit but is not a prefix of it")
        self.assertNoProblems(problems, "stale or mistyped commit abbreviations:")

    def test_notice_identifies_the_base_it_modifies(self):
        for needle in (self.pin["tag"], self.pin["commit"][:7]):
            self.assertIn(needle, self.notice,
                          f"third_party/aurie/NOTICE.md does not name {needle}; a modification "
                          f"notice has to say what was modified")


class BlobChain(SeriesCase):
    def test_each_patch_starts_from_the_blob_the_previous_one_left(self):
        self.assertNoProblems(chain_problems(self.parsed), "index lines do not chain:")


class Scope(SeriesCase):
    def test_every_path_is_under_aurie_and_none_is_plugin_facing(self):
        problems = []
        for parsed in self.parsed:
            self.assertTrue(parsed.files, f"{parsed.name} changes no file")
            for diff in parsed.files:
                where = f"{parsed.name}: {diff.path}"
                if diff.renamed:
                    problems.append(f"{where}: a rename or copy")
                if diff.binary:
                    problems.append(f"{where}: a binary hunk. The series is reviewable text only.")
                if not diff.path.startswith(SOURCE_ROOT) or ".." in diff.path.split("/"):
                    problems.append(f"{where}: outside Aurie/. The series changes AurieCore's "
                                    f"project and nothing else in upstream's repository.")
                if diff.path.startswith(FORBIDDEN_PREFIXES):
                    problems.append(
                        f"{where}: shared.hpp is what plugins compile against (ForgePact pins "
                        f"upstream's copy), and AuriePatcher/AurieInstaller/TestModule are not "
                        f"the DLL. Keep new declarations in a framework-private header.")
        self.assertNoProblems(problems, "patches out of scope:")

    def test_host_tests_are_not_part_of_the_dll(self):
        problems = []
        for parsed in self.parsed:
            for path, number, text in shipped_added(parsed):
                project = path.endswith((".vcxproj", ".filters", ".props", ".sln"))
                include = re.match(r"\s*#\s*include\b", text)
                if "hs-tests" in text and (project or include):
                    problems.append(f"{parsed.name}:{number} ({path}): {text.strip()[:80]!r} "
                                    f"brings a host test into the DLL build")
        self.assertNoProblems(problems, "host tests must stay standalone executables:")


class FreezeContract(SeriesCase):
    """What the plan's "patched freeze" section and ADR 0006 hold patch 0002 to."""

    def test_controls(self):
        call = "\tMmCreateHook(module, name, target, detour, &trampoline);"
        added = parse_patch("c.patch", synthetic_patch(call))
        self.assertEqual(len(contract_problems(added, synthetic_patch(call))), 1)
        context = synthetic_patch("int ours = 1;", context=call)
        self.assertEqual(contract_problems(parse_patch("c.patch", context), context), [])

        renamed = "\t\tvoid MmpFreezeCurrentProcess(bool Wait)"
        data = synthetic_patch(renamed)
        self.assertEqual(len(contract_problems(parse_patch("c.patch", data), data)), 1)
        removal = synthetic_patch("int ours = 1;").replace(
            b"@@ -1,2 +1,3 @@\n first line\n",
            b"@@ -1,3 +1,3 @@\n first line\n-\t\t\tMmpResumeCurrentProcess();\n")
        parsed = parse_patch("c.patch", removal)
        self.assertEqual(parsed.problems, [])
        self.assertEqual(len(contract_problems(parsed, removal)), 1)

        unit = FREEZE_UNIT + "cpp"
        framework = parse_patch("c.patch", synthetic_patch('#include "../framework.hpp"', path=unit))
        self.assertEqual(len(unit_include_problems(framework)), 1)
        for fine in ("#include <Windows.h>", '#include "thread_freeze.hpp"'):
            parsed = parse_patch("c.patch", synthetic_patch(fine, path=unit))
            self.assertEqual(unit_include_problems(parsed), [], fine)
        elsewhere = parse_patch("c.patch", synthetic_patch('#include "thread_freeze.hpp"'))
        self.assertEqual(unit_include_problems(elsewhere), [])

    def test_hooks_attach_as_before(self):
        problems = []
        for parsed in self.parsed:
            problems += contract_problems(parsed, self.data[parsed.name])
        self.assertNoProblems(problems, "the freeze pair or MmCreateHook changed shape:")

    def test_the_unit_stands_alone(self):
        problems = [p for parsed in self.parsed for p in unit_include_problems(parsed)]
        self.assertNoProblems(problems, "the freeze unit must compile without Aurie:")
        units = {path for _name, path, _n, _t in self.all_added() if path.startswith(FREEZE_UNIT)}
        self.assertEqual(units, {FREEZE_UNIT + "cpp", FREEZE_UNIT + "hpp"})

    def test_the_unit_is_compiled_into_the_dll(self):
        lines = [text for _name, path, _n, text in self.all_added()
                 if path == "Aurie/AurieCore.vcxproj"]
        self.assertTrue(
            any(re.search(r'<ClCompile Include="source\\framework\\Memory Manager\\'
                          r'thread_freeze\.cpp"', text) for text in lines),
            "Aurie/AurieCore.vcxproj does not gain thread_freeze.cpp in its ClCompile list")

    def test_ntgetnextthread_is_resolved_by_name(self):
        shipped = [text for parsed in self.parsed for _p, _n, text in shipped_added(parsed)]
        self.assertTrue(any("GetProcAddress" in text and '"NtGetNextThread"' in text
                            for text in shipped),
                        "no shipped line resolves NtGetNextThread by name through GetProcAddress")

    def test_the_log_lines_are_the_literals_the_live_checks_read(self):
        shipped = [text for parsed in self.parsed for _p, _n, text in shipped_added(parsed)]
        for prefix in FREEZE_PREFIXES:
            self.assertTrue(any(f'"{prefix}' in text for text in shipped),
                            f"no shipped line starts a string literal with {prefix!r}")
        self.assertTrue(any(IDENTITY_FORMAT in text for text in shipped),
                        f"no shipped line holds the identity format {IDENTITY_FORMAT}")

    def test_the_host_test_names_every_case(self):
        test_lines = [text for _name, path, _n, text in self.all_added()
                      if path.startswith(HOST_TESTS)]
        missing = [case for case in HOST_TEST_CASES
                   if not any(f'"{case}"' in text for text in test_lines)]
        self.assertEqual(missing, [], "host test cases the plan's criteria name but the test lacks")


class Bytes(SeriesCase):
    def test_no_cr_and_a_final_newline(self):
        problems = []
        for path in [SERIES] + sorted(PATCH_DIR.glob("*.patch")):
            data = path.read_bytes()
            rel = path.relative_to(ROOT).as_posix()
            if b"\r" in data:
                problems.append(f"{rel} contains {data.count(bytes([13]))} CR byte(s); upstream's "
                                f"blobs are LF and `git apply` compares context byte for byte")
            if not data.endswith(b"\n"):
                problems.append(f"{rel} does not end in a newline")
        self.assertNoProblems(problems, "line endings:")

    def test_header_paths_with_a_space_keep_their_tab(self):
        # `Memory Manager/` has a space: git ends such a header path with a TAB.
        problems = []
        for parsed in self.parsed:
            for diff in parsed.files:
                for number, line in diff.path_lines:
                    if " " in diff.path and "/dev/null" not in line and not line.endswith("\t"):
                        problems.append(f"{parsed.name}:{number}: {line[:60]!r}... lost its TAB")
        self.assertNoProblems(problems, "trailing whitespace was stripped from a patch:")

    def test_gitattributes_protects_the_series(self):
        rules = {}
        for line in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if parts and not parts[0].startswith("#"):
                rules[parts[0]] = parts[1:]
        for pattern, attribute in (("third_party/aurie/patches/*.patch", "-text"),
                                   ("third_party/aurie/patches/series", "eol=lf"),
                                   ("third_party/aurie/LICENSE", "-text")):
            self.assertIn(attribute, rules.get(pattern, []),
                          f".gitattributes must keep `{pattern} {attribute}`")


class NoDecompiledOutput(SeriesCase):
    def test_patches_add_no_listing_text(self):
        problems = []
        for parsed in self.parsed:
            problems += legal_problems(f"third_party/aurie/patches/{parsed.name}",
                                       patch_lines_we_wrote(parsed))
        self.assertNoProblems(problems, "AGENTS.md, 'Legal: Decompiled Output Never Reaches "
                                        "Any Origin':")

    def test_readme_and_notice_carry_no_listing_text(self):
        problems = (legal_problems("third_party/aurie/README.md", numbered(self.readme))
                    + legal_problems("third_party/aurie/NOTICE.md", numbered(self.notice)))
        self.assertNoProblems(problems, "decompiler or VM listing text in the series' documents:")


class NoHandResolvedAddress(SeriesCase):
    def test_control_the_rule_reaches_aurie_paths(self):
        base_plus = "\tauto fn = (Fn)((char*)GetModuleHandleA(nullptr) + 0xB489070);"
        added = parse_patch("c.patch", synthetic_patch(base_plus))
        self.assertTrue(address_problems(added))
        context = parse_patch("c.patch", synthetic_patch("int ours = 1;", context=base_plus))
        self.assertEqual(address_problems(context), [])

    def test_patches_add_no_hand_resolved_address(self):
        used: set = set()
        problems = []
        for parsed in self.parsed:
            problems += address_problems(parsed, used)
        self.assertNoProblems(problems, "AGENTS.md, 'Never Call an Address You Resolved by Hand':")
        # The YYToolkit allowlists are keyed by YYToolkit paths; none may cover Aurie.
        self.assertEqual(used, set())


class NoPersonIdentifyingPath(SeriesCase):
    def test_control(self):
        named = "C:\\\\Users\\\\jdoe\\\\trace\\\\crumbs.txt"
        added = parse_patch("c.patch", synthetic_patch(f'\tOpen("{named}");'))
        self.assertEqual(len(user_path_problems("c.patch", patch_lines_we_wrote(added))), 1)

    def test_patches_readme_and_notice_name_no_user_profile(self):
        problems = []
        for parsed in self.parsed:
            problems += user_path_problems(f"third_party/aurie/patches/{parsed.name}",
                                           patch_lines_we_wrote(parsed))
        problems += user_path_problems("third_party/aurie/README.md", numbered(self.readme))
        problems += user_path_problems("third_party/aurie/NOTICE.md", numbered(self.notice))
        self.assertNoProblems(problems, "an absolute path under a user profile:")


class CitedEvidenceIsExplained(SeriesCase):
    def test_the_readme_explains_every_local_file_a_message_cites(self):
        self.assertNoProblems(unexplained_evidence_problems(self.parsed, self.readme),
                              "patch messages cite files a reader of the repository cannot open:")


class NoticeAndLicence(SeriesCase):
    def test_notice_says_what_a_modification_notice_must(self):
        required = (
            ("AGPL-3.0", "the licence"),
            (self.pin["repo"], "where upstream's source is (the `repo` in upstream.json)"),
            ("upstream.json", "the file that pins the base commit"),
            ("third_party/aurie/patches", "where the changes are"),
            ("tools/build_aurie.py", "how the binary is produced from them"),
        )
        for needle, what in required:
            self.assertIn(needle, self.notice,
                          f"third_party/aurie/NOTICE.md must state {what}: {needle!r} is missing")
        self.assertRegex(self.notice, r"(?i)\bmodified\b",
                         "NOTICE.md must say, in that word, that this Aurie is MODIFIED")
        self.assertRegex(self.notice, r"\b20\d\d-\d\d-\d\d\b", "NOTICE.md must date the changes")

    def test_license_is_upstreams_blob(self):
        actual = git_blob_id(LICENSE.read_bytes())
        self.assertEqual(actual, LICENSE_BLOB,
                         f"third_party/aurie/LICENSE hashes to git blob {actual}, upstream's is "
                         f"{LICENSE_BLOB}. Restore upstream's file byte for byte (check for CRLF).")


class DirectoryHoldsTextOnly(SeriesCase):
    def test_only_allowed_file_types(self):
        problems = []
        for path in sorted(PIN_DIR.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(PIN_DIR).as_posix()
            if path.name in ALLOWED_NAMES or path.suffix in ALLOWED_SUFFIXES:
                if (path.suffix == ".patch" or path.name == "series") and path.parent != PATCH_DIR:
                    problems.append(f"{rel}: patches and the series file live in patches/")
                continue
            problems.append(f"{rel}: third_party/aurie/ holds .md, .json, .patch, `series` and "
                            f"LICENSE only - no upstream source, no binary, no log")
        self.assertNoProblems(problems, "unexpected files:")


class HubDocsPointHere(SeriesCase):
    def test_docs_mention_the_series_directory(self):
        for rel in SYNCED_DOCS:
            self.assertIn("third_party/aurie", (ROOT / rel).read_text(encoding="utf-8"),
                          f"{rel} no longer mentions third_party/aurie; restore the pointer")

    def test_agents_md_names_this_test(self):
        self.assertIn("tests/test_aurie_patch_series.py",
                      (ROOT / "AGENTS.md").read_text(encoding="utf-8"))


class SeriesRevision(SeriesCase):
    DEFINITION = re.compile(r'\bg_HeroSiegeSeriesRevision\s*=\s*"([^"]*)"\s*;')

    def test_upstream_json_the_dll_and_the_docs_agree(self):
        defined = [(parsed.name, match.group(1))
                   for parsed in self.parsed for _path, _number, text in shipped_added(parsed)
                   for match in [self.DEFINITION.search(text)] if match]
        self.assertEqual(len(defined), 1,
                         f"exactly one patch must define g_HeroSiegeSeriesRevision; found {defined}")
        patch, literal = defined[0]
        self.assertEqual(self.pin.get("series_revision"), literal,
                         f"upstream.json's series_revision and the literal {patch} compiles into "
                         f"the DLL differ; bump both in the same change")
        for path, text in ((README, self.readme), (NOTICE, self.notice)):
            self.assertIn(f"`{literal}`", text,
                          f"{path.relative_to(ROOT).as_posix()} does not name series revision "
                          f"`{literal}`")


@unittest.skipIf(shutil.which("git") is None, "git is not on PATH")
class SeriesAppliesToThePin(SeriesCase):
    """The only test here that needs upstream's source, so it is opt-in."""

    def test_series_applies_cumulatively_to_the_pinned_commit(self):
        upstream = os.environ.get(UPSTREAM_ENV, "").strip()
        if not upstream:
            self.skipTest(f"{UPSTREAM_ENV} is not set. Point it at a local clone of "
                          f"{self.pin['repo']} that contains {self.pin['tag']} to apply the "
                          f"series for real; nothing is fetched.")
        if not Path(upstream).is_dir():
            self.skipTest(f"{UPSTREAM_ENV}={upstream} is not a directory")

        base = Path(tempfile.mkdtemp(prefix="hstk-au-"))
        self.addCleanup(tool.remove_tree, base)
        environ = {k: v for k, v in os.environ.items()
                   if k.upper() not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX")}
        ctx = tool.Context(pin_dir=PIN_DIR, work_dir=base / "w", environ=environ,
                           max_work_dir_len=250, log=lambda _line: None)
        present = ctx.git("-C", upstream, "cat-file", "-e", self.pin["commit"] + "^{commit}",
                          check=False)
        if present.returncode != 0:
            self.skipTest(f"{UPSTREAM_ENV}={upstream} does not contain the pinned commit "
                          f"{self.pin['commit'][:12]} ({self.pin['tag']}); fetch it there")
        try:
            record = tool.materialise(ctx, Path(upstream))
            tool.apply_series(ctx)
        except tool.ToolError as error:
            self.fail(f"the series does not apply to the pin: {error}")

        problems = []
        first_seen, final = {}, {}
        for parsed in self.parsed:
            for diff in parsed.files:
                first_seen.setdefault(diff.path, (parsed.name, diff))
                final[diff.path] = (parsed.name, diff)
        for path, (name, diff) in sorted(first_seen.items()):
            blob = record["files"].get(path)
            if diff.new_file and blob is not None:
                problems.append(f"{name}: creates {path}, which upstream already has")
            elif not diff.new_file and (blob is None or not blob.startswith(diff.pre)):
                problems.append(f"{name}: {path} pre-image {diff.pre} is not upstream's blob {blob}")
        for path, (name, diff) in sorted(final.items()):
            actual = git_blob_id((ctx.path("src") / path).read_bytes())
            if not actual.startswith(diff.post):
                problems.append(f"{name}: leaves {path} at {actual[:12]}, its index line says {diff.post}")
        self.assertNoProblems(problems, "index lines disagree with the applied tree:")


if __name__ == "__main__":
    unittest.main()
