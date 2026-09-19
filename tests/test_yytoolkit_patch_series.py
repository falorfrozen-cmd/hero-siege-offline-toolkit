"""Pin the shape of `third_party/yytoolkit/` -- offline, stdlib only, no MSVC.

The modified YYToolkit is one pinned upstream commit plus a patch series. The
DLL this toolkit distributed before that was built from a tree nobody kept, and
its strings show changes no document lists (docs/agents/yytoolkit-provenance.md).
`tools/build_yytoolkit.py verify-dll` is the check on a *binary*; this file is
the check on the *series*, and it runs on the ubuntu CI where nothing can be
built: every rule below is about text that is in the repository.

What is pinned, in the order of the test classes:

  - `patches/*.patch` and `patches/series` list the same files, numbered
    contiguously from 0001, in numeric order;
  - the README's patch table and the NOTICE name exactly those files, in order;
  - every patch is a mail-format patch whose message carries the five fields,
    whose `Log-markers:` lines parse under the build tool's own grammar (its
    parser is imported, not copied), and whose hunk counts add up;
  - every declared marker literally occurs in a line the same patch ADDS to a
    file that is compiled into the DLL -- a marker that only a host test or the
    message mentions can never reach the binary `verify-dll` looks in;
  - the full upstream commit id is written in `upstream.json` and nowhere else,
    and an abbreviation quoted in the docs is a prefix of it;
  - `index <pre>..<post>` lines chain across the series per path;
  - no patch leaves `YYToolkit/`, carries a binary hunk, or touches the
    plugin-facing shared headers (plugins compile against the unmodified ones);
  - patches and `series` are LF, end in a newline, keep the TAB that ends a
    header path containing a space, and `.gitattributes` still protects them;
  - no decompiler or VM listing text, no hand-resolved address and no
    person-identifying absolute path is ADDED by a patch, written in a patch
    message, or present in the README or the NOTICE;
  - every kind of local evidence file a patch message cites by path (a log, a
    strings listing - neither may be committed, they carry machine paths) is
    named by the README, which says what it is and how to re-derive it;
  - the NOTICE says what an AGPL modification notice has to, and `LICENSE` is
    upstream's blob;
  - the directory holds text only, the hub docs point at it, and
    `series_revision` is the literal patch 0006 compiles into the DLL;
  - when `ForgePact/` is checked out, its own `tools/toolchain-pins.json`
    pins `modfiles_shipped/YYToolkit.dll` at either this series' sha256 (the
    README's "How to build" section) as a plain hub-release pin, or the
    pre-migration sha256 (NOTICE.md's "About the previously distributed
    binary") in its original zip-member form -- anything else is drifted and
    fails. The legacy state is temporary: it is accepted only until
    ForgePact's own pin-moving change merges and the hub's gitlink is bumped
    past it, at which point that branch of the check is deleted. Skips,
    saying why, when the submodule is absent (hub CI runs without it).

Checks that a one-sided test would pass while doing nothing come in pairs. The
message, marker, chain, legal, address and path rules each also run on a
synthetic patch: a positive control (the offending text as an ADDED line is
reported) and a negative one (the same text as a CONTEXT line, which is
upstream's and not ours, is not). The synthetic listing symbol is assembled at
run time, because `.claude/hooks/decompiled_output.py` reads every line this
file adds and would otherwise flag the fixture as the thing it guards against.

Deliberately NOT caught, written down rather than implied:

  - whether a patch *applies*. `index` lines can chain while a hunk's context
    is stale. That needs upstream's blobs, which the hub must not vendor, so it
    is the optional last class: set `HSTK_YYTK_UPSTREAM` to a local clone that
    contains the pinned commit and the series is exported and applied for real
    through the build tool. Without it that class SKIPS and says why.
  - paraphrase of game source, which no pattern can tell from description
    (the `decompile-output-guard` agent's job), and addresses written in
    decimal outside an `...Rva = <n>` assignment.
  - anything about the built DLL, or the game. Nothing here launches either.
"""

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
PIN_DIR = ROOT / "third_party" / "yytoolkit"
PATCH_DIR = PIN_DIR / "patches"
SERIES = PATCH_DIR / "series"
README = PIN_DIR / "README.md"
NOTICE = PIN_DIR / "NOTICE.md"
LICENSE = PIN_DIR / "LICENSE"
UPSTREAM_JSON = PIN_DIR / "upstream.json"
TOOL_PATH = ROOT / "tools" / "build_yytoolkit.py"
HOOK_PATH = ROOT / ".claude" / "hooks" / "decompiled_output.py"
ADR = ROOT / "docs" / "adr" / "0002-modified-yytoolkit-is-a-patch-series-in-the-hub.md"

#: The hub documents that must keep pointing at the series directory.
SYNCED_DOCS = (
    "docs/submodules/README.md",
    "docs/submodules/ForgePact/instructions.md",
    "docs/submodules/HS-Offline-Tracker/instructions.md",
    "AGENTS.md",
    "README.md",
)

#: upstream's LICENSE at the pin, as `git ls-tree` names it.
LICENSE_BLOB = "0ad25db4bd1d86c452db3f9602ccdbe172438f52"

UPSTREAM_ENV = "HSTK_YYTK_UPSTREAM"
HOST_TESTS = "YYToolkit/hs-tests/"
#: What plugins compile against. A patch that touches these changes the ABI of
#: every plugin already built, silently.
FORBIDDEN_PREFIXES = ("YYToolkit/source/YYTK/Shared/", "ExamplePlugin/")
ALLOWED_SUFFIXES = (".md", ".json", ".patch")
ALLOWED_NAMES = ("series", "LICENSE")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # Its own name: tests/test_build_yytoolkit.py loads the same file, and
    # @dataclass resolves annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load("hstk_series_test_build_yytoolkit", TOOL_PATH)
# The hook's own detection, not a copy of its patterns: a signature added there
# is enforced here the same day.
hook = _load("hstk_series_test_decompiled_output", HOOK_PATH)


# --------------------------------------------------------------------------
# reading a patch
# --------------------------------------------------------------------------

HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
INDEX = re.compile(r"^index ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})(?: [0-7]{6})?$")
ZERO = re.compile(r"0{7,40}")


class FileDiff:
    def __init__(self, path: str, line: int):
        self.path, self.line = path, line
        self.pre: Optional[str] = None
        self.post: Optional[str] = None
        self.new_file = self.binary = self.renamed = False
        self.added: List[Tuple[int, str]] = []
        self.path_lines: List[Tuple[int, str]] = []     # the `--- a/` and `+++ b/` lines


class ParsedPatch:
    def __init__(self, name: str):
        self.name = name
        self.header: List[Tuple[int, str]] = []
        self.files: List[FileDiff] = []
        self.problems: List[str] = []

    def added(self, *, shipped_only: bool = False) -> Iterator[Tuple[str, int, str]]:
        """(path, line number in the patch file, text) of every `+` line."""
        for diff in self.files:
            if shipped_only and diff.path.startswith(HOST_TESTS):
                continue
            for number, text in diff.added:
                yield diff.path, number, text


def _diff_path(line: str) -> Optional[str]:
    """`diff --git a/X b/X` -> X. X may contain spaces, so the line is split by
    length, not on " b/". None when the two sides differ (a rename or a copy)."""
    rest = line[len("diff --git "):]
    size = (len(rest) - len("a/ b/")) // 2
    path = rest[2:2 + size]
    return path if size > 0 and rest == f"a/{path} b/{path}" else None


def parse_patch(name: str, data: bytes) -> ParsedPatch:
    """Hunks are followed by their declared line counts, so `+++` inside a hunk
    is an added line and a mail trailer after the last hunk is not a removal."""
    parsed = ParsedPatch(name)
    lines = data.decode("utf-8", "replace").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    current: Optional[FileDiff] = None
    old_left = new_left = 0

    def unfinished(number: int) -> None:
        nonlocal old_left, new_left
        if old_left or new_left:
            parsed.problems.append(
                f"{name}:{number}: the hunk before this line is {old_left} old / {new_left} new "
                f"line(s) short of what its @@ header declares"
            )
        old_left = new_left = 0

    for number, line in enumerate(lines, 1):
        if current is not None and (old_left > 0 or new_left > 0):
            if line.startswith("\\"):           # "\ No newline at end of file"
                continue
            kind = line[:1]
            if kind in ("+", "-", " ", ""):     # an empty line is blank context
                if kind != "+":
                    old_left -= 1
                if kind != "-":
                    new_left -= 1
                if kind == "+":
                    current.added.append((number, line[1:]))
                if old_left < 0 or new_left < 0:
                    parsed.problems.append(
                        f"{name}:{number}: more lines than the hunk's @@ header declares")
                    old_left = new_left = 0
                continue
            # Anything else ends the hunk early. The line is then read as what
            # it is, so a `diff --git` still opens its file.
            unfinished(number)
        if line.startswith("diff --git "):
            path = _diff_path(line)
            current = FileDiff(path if path is not None else line, number)
            current.renamed = path is None
            parsed.files.append(current)
        elif current is None:
            parsed.header.append((number, line))
        elif line.startswith("@@"):
            match = HUNK.match(line)
            if not match:
                parsed.problems.append(f"{name}:{number}: unreadable hunk header {line!r}")
                continue
            old_left = int(match.group(1)) if match.group(1) is not None else 1
            new_left = int(match.group(2)) if match.group(2) is not None else 1
        elif line.startswith(("--- ", "+++ ")):
            current.path_lines.append((number, line))
        elif line.startswith("new file mode"):
            current.new_file = True
        elif line.startswith(("GIT binary patch", "Binary files ")):
            current.binary = True
        elif line.startswith(("rename ", "copy ", "similarity ", "dissimilarity ")):
            current.renamed = True
        else:
            match = INDEX.match(line)
            if match:
                current.pre, current.post = match.group(1), match.group(2)
    unfinished(len(lines) + 1)
    return parsed


def synthetic_patch(added: str, context: str = "upstream's own line",
                    markers: str = '"synthetic marker"',
                    path: str = "YYToolkit/source/Thing.cpp",
                    drop_field: Optional[str] = None) -> bytes:
    """One well-formed patch: a complete message, one file, one hunk that adds
    `added` between two context lines."""
    fields = [
        ("Why", "the controls need a patch the rules can be pointed at."),
        ("Evidence", "none, this text is made up by a unit test."),
        ("Fails-safe", "not applicable, nothing is built from it."),
        ("Log-markers", markers),
        ("Upstream-status", "not submitted, it is not a change."),
    ]
    message = "\n\n".join(f"{key}: {value}" for key, value in fields if key != drop_field)
    return (
        f"From {'0' * 40} Mon Sep 17 00:00:00 2001\n"
        "From: Hub Tests <hstk@example.invalid>\n"
        "Date: Sat, 19 Sep 2026 12:00:00 +0000\n"
        "Subject: [PATCH] a synthetic change\n\n"
        f"{message}\n---\n"
        f"diff --git a/{path} b/{path}\n"
        "index 1111111..2222222 100644\n"
        f"--- a/{path}\n+++ b/{path}\n"
        "@@ -1,2 +1,3 @@\n"
        " first line\n"
        f"+{added}\n"
        f" {context}\n"
    ).encode("utf-8")


# --------------------------------------------------------------------------
# the rules. Each takes parsed patches and returns the problems it found, so a
# control and the real series go through the same code.
# --------------------------------------------------------------------------

FIELDS = ("Why", "Evidence", "Fails-safe", "Upstream-status")
FIELD_LINE = re.compile(r"^(Why|Evidence|Fails-safe|Log-markers|Upstream-status):[ \t]*(.*)$")
#: "TODO" is not a reason. Every real field is far longer than this.
MIN_FIELD_CHARS = 20


def header_fields(parsed: ParsedPatch) -> Dict[str, List[str]]:
    """field name -> one string per occurrence; a field runs to the next blank line."""
    fields: Dict[str, List[List[str]]] = {}
    current: Optional[List[str]] = None
    for _number, line in parsed.header:
        match = FIELD_LINE.match(line)
        if match:
            current = [match.group(2)]
            fields.setdefault(match.group(1), []).append(current)
        elif not line.strip() or line == "---":
            current = None
        elif current is not None:
            current.append(line)
    return {key: [" ".join(part).strip() for part in parts] for key, parts in fields.items()}


def message_problems(parsed: ParsedPatch, data: bytes) -> List[str]:
    name = parsed.name
    problems: List[str] = []
    header = [text for _number, text in parsed.header]
    if not header or not re.match(r"^From [0-9a-f]{40} ", header[0]):
        problems.append(f"{name}: line 1 is not a `From <40 hex> <date>` mail separator; "
                        f"write the file with `git format-patch`, do not assemble it by hand")
    for key in ("From", "Date", "Subject"):
        values = [line[len(key) + 1:].strip() for line in header if line.startswith(key + ":")]
        if not values or not values[0]:
            problems.append(f"{name}: no `{key}:` mail header; regenerate it with `git format-patch`")
    subject = next((line for line in header if line.startswith("Subject:")), "")
    if subject and not re.sub(r"^Subject:\s*(\[[^\]]*\])?\s*", "", subject):
        problems.append(f"{name}: the Subject is empty after its [PATCH] prefix")
    fields = header_fields(parsed)
    for key in FIELDS:
        values = fields.get(key, [])
        if not values:
            problems.append(
                f"{name}: the message has no `{key}:` field. Add it to the commit message and "
                f"regenerate the patch (third_party/yytoolkit/README.md, 'How to change the series')")
        elif len(values) > 1:
            problems.append(f"{name}: `{key}:` appears {len(values)} times; one field, one statement")
        elif len(values[0]) < MIN_FIELD_CHARS:
            problems.append(f"{name}: `{key}:` says only {values[0]!r}; state it in a sentence")
    try:
        tool.parse_markers(name, data)
    except tool.ToolError as error:
        problems.append(f"{name}: tools/build_yytoolkit.py refuses its Log-markers: {error}")
    return problems


def marker_problems(parsed: ParsedPatch, markers: Iterable[str]) -> List[str]:
    shipped = [text for _path, _number, text in parsed.added(shipped_only=True)]
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
              "string in the source, so they are the same characters on one line."
        )
    return problems


def legal_problems(display: str, lines: List[Tuple[int, str]]) -> List[str]:
    return hook.inspect(display, lines)


def patch_lines_we_wrote(parsed: ParsedPatch) -> List[Tuple[int, str]]:
    """The message and the added lines. Context and removed lines are
    upstream's text, which is not ours to police (the hook's own reasoning)."""
    return parsed.header + [(number, text) for _path, number, text in parsed.added()]


HEX = re.compile(r"(?<![0-9A-Za-z_])0[xX]([0-9A-Fa-f]+(?:'[0-9A-Fa-f]+)*)")
#: 1 MiB. Below it a literal is a mask, a page size, a window, a small cap;
#: from it upwards it is big enough to be an offset into a 190 MB game image.
ADDRESS_SIZED = 0x100000

_RI_SCAN_TEST = HOST_TESTS + "ri_scan_test.cpp"
_FNARRAY_TEST = HOST_TESTS + "fnarray_validation_test.cpp"
_GENERIC = "YYToolkit/source/YYTK/Module Internals/GameMaker/Generic/"
_LEDGER = "YYToolkit/source/YYTK/Module Internals/Hooks/YYErrorLedger.hpp"

#: (path, value) -> (where it may appear, why it is not a hand-resolved address).
#: "comment": only after `//` on its line; the entry stops covering it the
#: moment the value moves into code. Every entry must still be in use.
BIG_HEX_ALLOWED = {
    (_RI_SCAN_TEST, 0xB5557E2): (
        "code",
        "host test, never linked into the DLL: the chain RVA the patch's Evidence field quotes, "
        "handed to GetPageOfRva() as a NUMBER to check rva -> page arithmetic (and printed in "
        "that check's description). A host executable maps nothing there and never dereferences it."),
    (_RI_SCAN_TEST, 0xC000000): (
        "code", "host test: a made-up 192 MB section SIZE, the other operand of the same arithmetic."),
    (_RI_SCAN_TEST, 0x2545F491): (
        "code", "host test: seed of the fixed linear congruential sequence that fills a synthetic "
                "page buffer, so the run is the same on every host."),
    (_GENERIC + "Generic-RunnerInterfaceNew.cpp", 0xB5557E2): (
        "comment", "a comment in the shipped scan naming the one build on which 'the chain sits "
                   "inside a single page' was observed. Prose; no code reads it."),
    (_GENERIC + "Generic.cpp", 0x100000): (
        "code", "a size cap: GAME_SYMBOL_MAX_SCRIPT_SLOTS, the upper bound of a loop counter."),
    (_LEDGER, 0x100000001B3): ("code", "the published FNV-1a 64-bit prime."),
    (_LEDGER, 0xCBF29CE484222325): ("code", "the published FNV-1a 64-bit offset basis."),
    (_FNARRAY_TEST, 0x1122334455667788): (
        "code", "host test: a deliberately meaningless scalar the validator must REJECT without "
                "faulting; it is never treated as an address that works."),
}

#: An identifier is "an RVA" by camel case (`HookRva`, `kChainRva`) or as its
#: own upper-case word (`HOOK_RVA`, `ChainRVA`). Not by substring: INTERVAL and
#: RESERVATION both contain the letters.
RVA_NAME = re.compile(r"Rva|(?:^|_|(?<=[a-z0-9]))RVA(?![a-z])")
ASSIGNED_LITERAL = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:=(?!=)|\{)\s*\(?\s*(0[xX][0-9A-Fa-f']+|[0-9][0-9']*)")

#: (path, identifier, value) -> why. Host tests only, and the test enforces that.
RVA_ASSIGNMENT_ALLOWED = {
    (_RI_SCAN_TEST, "HookRva", 190141265):
        "a field of the hint line the test WRITES and parses back: a number in a text round "
        "trip, in a host executable where nothing is mapped at it.",
    (_RI_SCAN_TEST, "ChainRva", 190142434): "the same round trip, the line's other field.",
    (_RI_SCAN_TEST, "HookRva", 1): "a deliberately different small number for the key-mismatch case.",
    (_RI_SCAN_TEST, "ChainRva", 2): "the same key-mismatch case.",
}

_LITERAL = r"(?:0[xX][0-9A-Fa-f']+|[0-9][0-9']*)"
CALL_TARGETS = (
    (re.compile(r"GetModuleHandle\w*\s*\([^()]*\)[\s)]*\+\s*" + _LITERAL),
     "a module handle plus a literal offset"),
    (re.compile(r"\(\s*(?:unsigned\s+)?(?:char|uint8_t|BYTE|std::byte)\s*\*\s*\)\s*\w+\s*\+\s*"
                r"(?:0[xX][0-9A-Fa-f']+|k\w*Rva\w*)"),
     "a byte pointer plus a literal offset (the shape ForgePact's release contract test rejects)"),
    (re.compile(r"\b\w*(?:[Bb]ase|BASE|[Ii]mage|IMAGE|[Mm]odule|MODULE)\w*\s*\+\s*"
                r"0[xX][0-9A-Fa-f']{5,}"),
     "an image or module base plus a literal offset"),
)


def _int(literal: str) -> int:
    digits = literal.replace("'", "")
    return int(digits, 16) if digits[:2] in ("0x", "0X") else int(digits, 10)


def address_problems(parsed: ParsedPatch, used: Optional[set] = None) -> List[str]:
    """AGENTS.md, 'Never Call an Address You Resolved by Hand', applied to
    what a patch adds. `used` collects the allowlist entries that were needed."""
    used = set() if used is None else used
    problems = []
    for path, number, text in parsed.added():
        where = f"{parsed.name}:{number} ({path})"
        for pattern, what in CALL_TARGETS:
            match = pattern.search(text)
            if match:
                problems.append(
                    f"{where}: adds {what}: {match.group(0)!r}. A build's RVAs are not an "
                    f"interface; resolve by name, or find the address by scanning mapped bytes.")
        for match in ASSIGNED_LITERAL.finditer(text):
            identifier, value = match.group(1), _int(match.group(2))
            if value == 0 or not RVA_NAME.search(identifier):
                continue
            key = (path, identifier, value)
            if key in RVA_ASSIGNMENT_ALLOWED and path.startswith(HOST_TESTS):
                used.add(key)
                continue
            problems.append(
                f"{where}: assigns the literal {match.group(2)} to `{identifier}`. A measured RVA "
                f"is a research finding for docs/, not a constant in the DLL. In a host test, "
                f"add it to RVA_ASSIGNMENT_ALLOWED in this file with the reason.")
        for match in HEX.finditer(text):
            value = int(match.group(1).replace("'", ""), 16)
            if value < ADDRESS_SIZED:
                continue
            key = (path, value)
            scope = BIG_HEX_ALLOWED.get(key, (None, ""))[0]
            in_comment = "//" in text[:match.start()]
            if scope == "code" or (scope == "comment" and in_comment):
                used.add(key)
                continue
            problems.append(
                f"{where}: adds the address-sized literal {match.group(0)}"
                + (" outside a comment, which is all its allowlist entry covers" if scope else "")
                + ". If it is an encoding mask, a PE constant or a size cap, add (path, value) to "
                  "BIG_HEX_ALLOWED in this file with a one-line justification; if it is an address "
                  "somebody measured, it does not belong in a patch.")
    return problems


USER_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s\"'`<>|*?:]+)")
#: Stand-ins that identify nobody. Anything else after `Users\` is a name.
PLACEHOLDER_USERS = ("SomeUser", "Public", "Default", "USERNAME", "username", "user", "name", "you")


def user_path_problems(display: str, lines: Iterable[Tuple[int, str]]) -> List[str]:
    problems = []
    for number, text in lines:
        for match in USER_PATH.finditer(text):
            who = match.group(1)
            if who in PLACEHOLDER_USERS or who.startswith(("%", "$", "{")):
                continue
            problems.append(
                f"{display}:{number}: an absolute path under a user profile ({match.group(0)!r}). "
                f"It identifies a person; write `%LOCALAPPDATA%`, `<work>` or 'a path under the "
                f"builder's user profile' instead.")
    return problems


#: Evidence the patch messages cite by a path that is NOT in the repository
#: (a log and a strings listing carry machine paths; DirectoryHoldsTextOnly
#: keeps them out). kind -> how a message spells a citation of it.
LOCAL_EVIDENCE = {
    "evidence/": re.compile(r"(?<![\w/.-])evidence/[\w.-]+"),
    "shipped-strings.txt": re.compile(r"(?<![\w/.-])shipped-strings\.txt"),
    "documented/": re.compile(r"(?<![\w/.-])documented/[\w.-]+"),
}


def unexplained_evidence_problems(patches: Iterable[ParsedPatch], readme: str) -> List[str]:
    """A citation nobody can follow is not evidence. Every kind of local file a
    message cites must be named, in backticks, by the README, which is where it
    says what the file is, why it is not committed and how to re-derive it."""
    problems = []
    for kind, pattern in LOCAL_EVIDENCE.items():
        cited = [f"{parsed.name}:{number}" for parsed in patches
                 for number, text in parsed.header if pattern.search(text)]
        if cited and f"`{kind}" not in readme:
            problems.append(
                f"{', '.join(cited)} cite `{kind}...`, a file that is not in the repository, and "
                f"third_party/yytoolkit/README.md never mentions it. Say there (under 'Known "
                f"limitations and what is not measured') what the file is, why it is not "
                f"committed and how to re-derive it - or stop citing it.")
    return problems


def git_blob_id(data: bytes) -> str:
    digest = hashlib.sha1(b"blob %d\x00" % len(data), usedforsecurity=False)
    digest.update(data)
    return digest.hexdigest()


def numbered(text: str) -> List[Tuple[int, str]]:
    return list(enumerate(text.splitlines(), start=1))


# --------------------------------------------------------------------------
# the series as it is on disk
# --------------------------------------------------------------------------

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


class SeriesAndFilesAgree(SeriesCase):
    NAME = re.compile(r"^(\d{4})-[a-z0-9][a-z0-9-]*\.patch$")

    def test_series_and_patch_files_are_the_same_set(self):
        on_disk = sorted(p.name for p in PATCH_DIR.glob("*.patch"))
        problems = [f"{name} is in third_party/yytoolkit/patches/ but not in patches/series: add "
                    f"it as the last line of series, or delete the file - an unlisted patch is "
                    f"never applied, so it documents a change the DLL does not have"
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
                problems.append(f"{name}: not NNNN-lower-case-slug.patch; rename the file and its "
                                f"line in patches/series")
            elif int(match.group(1)) != position:
                problems.append(
                    f"{name} is line {position} of patches/series but is numbered "
                    f"{match.group(1)}; numbers run from 0001 with no gap, and series order is "
                    f"numeric order (a new patch takes the next number and the last line)")
        self.assertNoProblems(problems, "patch numbering:")

    def test_the_build_tool_reads_the_same_series(self):
        try:
            loaded = tool.load_series(PIN_DIR)
        except tool.ToolError as error:
            self.fail(f"tools/build_yytoolkit.py refuses the series: {error}")
        self.assertEqual([p.name for p in loaded], self.names)


class ReadmeAndNoticeNameEveryPatch(SeriesCase):
    TABLE_HEADER = "| # | Patch | What it changes | Why |"
    ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|(.*)\|\s*$")

    def table_rows(self) -> List[Tuple[int, str, List[str]]]:
        lines = self.readme.splitlines()
        self.assertIn(
            self.TABLE_HEADER, lines,
            f"third_party/yytoolkit/README.md has no patch table headed {self.TABLE_HEADER!r}; "
            f"this test reads the table by that header - restore it rather than renaming it")
        rows = []
        for line in lines[lines.index(self.TABLE_HEADER) + 1:]:
            if not line.startswith("|"):
                break
            if re.fullmatch(r"[|\s:-]+", line):
                continue
            match = self.ROW.match(line)
            self.assertIsNotNone(
                match, f"README.md patch table: cannot read the row {line[:70]!r}; a row is "
                       f"`| <n> | `<file>.patch` | what | why |`")
            cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", match.group(3))]
            rows.append((int(match.group(1)), match.group(2), cells))
        return rows

    def test_readme_table_lists_the_series_in_order(self):
        rows = self.table_rows()
        self.assertEqual(
            [name for _n, name, _cells in rows], self.names,
            "third_party/yytoolkit/README.md's patch table and patches/series differ. Every patch "
            "gets a row, in series order, in the same change that adds it.")
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
            self.assertIn(
                name, self.notice,
                f"third_party/yytoolkit/NOTICE.md does not name {name}. The notice ships beside "
                f"the DLL and must list every change; the previous notice listed two of six.")
            positions.append(self.notice.index(name))
        self.assertEqual(positions, sorted(positions),
                         "NOTICE.md lists the patches in another order than patches/series")

    def test_readme_host_test_count_matches_the_patches(self):
        added = sorted(diff.path for parsed in self.parsed for diff in parsed.files
                       if diff.path.startswith(HOST_TESTS) and diff.path.endswith(".cpp")
                       and diff.new_file)
        stated = re.search(r"hs-tests/`\s*\((\d+) files\)", self.readme)
        if stated:
            self.assertEqual(
                int(stated.group(1)), len(added),
                f"README.md says {stated.group(1)} host test files; the patches add {len(added)}: "
                f"{', '.join(Path(p).name for p in added)}")


class PatchMessages(SeriesCase):
    def test_controls_a_complete_message_passes_and_a_missing_field_is_named(self):
        data = synthetic_patch("int harmless = 1;")
        self.assertEqual(message_problems(parse_patch("ok.patch", data), data), [])
        for field in FIELDS:
            data = synthetic_patch("int harmless = 1;", drop_field=field)
            problems = message_problems(parse_patch("bad.patch", data), data)
            self.assertEqual(len(problems), 1, problems)
            self.assertIn(f"`{field}:`", problems[0])
        data = synthetic_patch("int harmless = 1;", drop_field="Log-markers")
        problems = message_problems(parse_patch("bad.patch", data), data)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("Log-markers", problems[0])
        data = synthetic_patch("int harmless = 1;", markers="short, unquoted")
        self.assertTrue(message_problems(parse_patch("bad.patch", data), data))

    def test_every_patch_carries_mail_headers_and_the_five_fields(self):
        problems = []
        for parsed in self.parsed:
            problems += message_problems(parsed, self.data[parsed.name])
        self.assertNoProblems(problems, "patch messages:")

    def test_control_a_wrong_hunk_count_is_reported(self):
        data = synthetic_patch("int harmless = 1;")
        self.assertEqual(parse_patch("ok.patch", data).problems, [])
        edited = data.replace(b"@@ -1,2 +1,3 @@", b"@@ -1,2 +1,5 @@")
        self.assertTrue(parse_patch("edited.patch", edited).problems)

    def test_hunk_counts_add_up(self):
        problems = [p for parsed in self.parsed for p in parsed.problems]
        self.assertNoProblems(
            problems, "a patch was edited by hand (regenerate it with `git format-patch`; an "
                      "edited diff fails in `git apply` without saying why):")


class DeclaredMarkersAreAdded(SeriesCase):
    def test_controls(self):
        marker = "hs-control: refused candidate"
        source = f'\tLog("{marker} 0x%p", candidate);'
        added = parse_patch("c.patch", synthetic_patch(source))
        self.assertEqual(marker_problems(added, [marker]), [])

        # The same text where the patch does NOT add it proves nothing.
        context_only = parse_patch("c.patch", synthetic_patch("int other = 1;", context=source))
        self.assertEqual(len(marker_problems(context_only, [marker])), 1)
        message_only = parse_patch("c.patch", synthetic_patch("int other = 1;"))
        self.assertEqual(len(marker_problems(message_only, [marker])), 1)
        host_test_only = parse_patch(
            "c.patch", synthetic_patch(source, path=HOST_TESTS + "thing_test.cpp"))
        problems = marker_problems(host_test_only, [marker])
        self.assertEqual(len(problems), 1)
        self.assertIn("only a host test", problems[0])

    def test_every_declared_marker_is_in_a_line_the_patch_adds_to_the_dll_source(self):
        problems, total = [], 0
        for parsed in self.parsed:
            markers = tool.parse_markers(parsed.name, self.data[parsed.name])
            total += len(markers)
            problems += marker_problems(parsed, markers)
        self.assertNoProblems(problems, "declared log markers the patch does not add:")
        self.assertGreater(total, 0, "no patch declares a single log marker; verify-dll would "
                                     "then accept any binary at all")


class ThePinIsWrittenOnce(SeriesCase):
    #: Files that must never repeat the commit id: a second copy is the one
    #: that goes stale. The tool's docstring promises it holds none.
    ELSEWHERE = (
        "tools/build_yytoolkit.py",
        "tests/test_build_yytoolkit.py",
        "tests/test_yytoolkit_patch_series.py",
        "docs/agents/yytoolkit-provenance.md",
        "docs/adr/0002-modified-yytoolkit-is-a-patch-series-in-the-hub.md",
    ) + SYNCED_DOCS

    def test_pin_is_a_full_commit_and_tree(self):
        try:
            pin = tool.load_pin(PIN_DIR)
        except tool.ToolError as error:
            self.fail(f"tools/build_yytoolkit.py refuses third_party/yytoolkit/upstream.json: {error}")
        self.assertTrue(pin.repo.startswith("https://"), pin.repo)

    def test_the_commit_and_tree_ids_occur_in_upstream_json_only(self):
        files = [p for p in sorted(PIN_DIR.rglob("*")) if p.is_file()]
        files += [ROOT / rel for rel in self.ELSEWHERE if (ROOT / rel).is_file()]
        for key in ("commit", "tree"):
            needle = self.pin[key].encode("ascii")
            hits = {p.relative_to(ROOT).as_posix(): p.read_bytes().count(needle) for p in files}
            hits = {rel: count for rel, count in hits.items() if count}
            self.assertEqual(
                hits, {"third_party/yytoolkit/upstream.json": 1},
                f"the pinned {key} id must be written once, in upstream.json, and nowhere else "
                f"(abbreviate it to 7 characters in prose): a second copy does not move when the "
                f"pin does. Found: {hits}")

    def test_a_quoted_abbreviation_is_a_prefix_of_the_pin(self):
        commit = self.pin["commit"]
        docs = [README, NOTICE, ADR] + [ROOT / rel for rel in self.ELSEWHERE if rel.endswith(".md")]
        docs = list(dict.fromkeys(docs + [PATCH_DIR / name for name in self.data]))
        problems = []
        for path in docs:
            if not path.is_file():
                continue
            text = path.read_bytes().decode("utf-8", "replace")
            if path.suffix == ".patch":         # the message only; hunks are full of hex
                text = text.split("\ndiff --git ", 1)[0]
            # 7 to 40 hex digits standing alone. A sha256 is 64 and never matches.
            for token in re.findall(r"\b[0-9a-f]{7,40}\b", text):
                # "Starts like the pin": the same first four digits. That is a
                # mistyped or stale abbreviation, not some other commit.
                if token[:4] == commit[:4] and not commit.startswith(token):
                    problems.append(
                        f"{path.relative_to(ROOT).as_posix()}: {token} starts like the pinned "
                        f"commit but is not a prefix of it ({commit[:12]}...); correct it, or "
                        f"move upstream.json if the pin really changed")
        self.assertNoProblems(problems, "stale or mistyped commit abbreviations:")

    def test_notice_identifies_the_base_it_modifies(self):
        for needle, what in ((self.pin["tag"], "the upstream tag"),
                             (self.pin["commit"][:7], "the pinned commit's 7-character abbreviation")):
            self.assertIn(needle, self.notice,
                          f"third_party/yytoolkit/NOTICE.md does not name {what} ({needle}); a "
                          f"modification notice has to say what was modified")


class BlobChain(SeriesCase):
    @staticmethod
    def chain_problems(patches: List[ParsedPatch]) -> List[str]:
        problems = []
        last: Dict[str, Tuple[str, str]] = {}      # path -> (post-image, patch that wrote it)
        for parsed in patches:
            for diff in parsed.files:
                where = f"{parsed.name}: {diff.path}"
                if diff.pre is None or diff.post is None:
                    problems.append(f"{where}: no readable `index <pre>..<post>` line")
                    continue
                creates = bool(ZERO.fullmatch(diff.pre))
                if creates != diff.new_file:
                    problems.append(f"{where}: `new file mode` and a {diff.pre} pre-image disagree")
                known = last.get(diff.path)
                if known is None or ZERO.fullmatch(known[0]):
                    if known is not None and not creates:
                        problems.append(f"{where}: {known[1]} deleted this path; it can only be "
                                        f"created again")
                    # Otherwise: first touch. A non-zero pre-image is upstream's
                    # blob, which only the apply check can confirm.
                elif creates:
                    problems.append(f"{where}: created as a new file, but {known[1]} already has it")
                else:
                    size = min(len(diff.pre), len(known[0]))
                    if diff.pre[:size] != known[0][:size]:
                        problems.append(
                            f"{where}: expects pre-image {diff.pre}, but {known[1]} left the file "
                            f"at {known[0]}. A patch earlier in the series was regenerated without "
                            f"the ones after it: regenerate every patch from {known[1]} onwards.")
                last[diff.path] = (diff.post, parsed.name)
        return problems

    def test_controls(self):
        first = parse_patch("0001-a.patch", synthetic_patch("int a = 1;"))
        second = parse_patch("0002-b.patch", synthetic_patch("int b = 2;").replace(
            b"index 1111111..2222222", b"index 2222222..3333333"))
        self.assertEqual(self.chain_problems([first, second]), [])
        stale = parse_patch("0002-b.patch", synthetic_patch("int b = 2;").replace(
            b"index 1111111..2222222", b"index 4444444..3333333"))
        problems = self.chain_problems([first, stale])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("0001-a.patch left the file at 2222222", problems[0])

    def test_each_patch_starts_from_the_blob_the_previous_one_left(self):
        self.assertNoProblems(self.chain_problems(self.parsed), "index lines do not chain:")


class Scope(SeriesCase):
    def test_every_path_is_under_yytoolkit_and_none_is_plugin_abi(self):
        problems = []
        for parsed in self.parsed:
            self.assertTrue(parsed.files, f"{parsed.name} changes no file")
            for diff in parsed.files:
                where = f"{parsed.name}: {diff.path}"
                if diff.renamed:
                    problems.append(f"{where}: a rename or copy; upstream's files stay where "
                                    f"plugin authors and the next rebase expect them")
                if diff.binary:
                    problems.append(f"{where}: a binary hunk. The series is reviewable text only.")
                if not diff.path.startswith("YYToolkit/") or ".." in diff.path.split("/"):
                    problems.append(f"{where}: outside YYToolkit/. The series changes the DLL's "
                                    f"project and nothing else in upstream's repository.")
                if diff.path.startswith(FORBIDDEN_PREFIXES):
                    problems.append(
                        f"{where}: a plugin-facing shared header. Plugins (ForgePact, the Tracker "
                        f"producer) compile against the UNMODIFIED pinned headers, so a change "
                        f"here silently breaks the ABI of every plugin already built. Keep new "
                        f"declarations in a DLL-private header.")
        self.assertNoProblems(problems, "patches out of scope:")

    def test_host_tests_are_not_part_of_the_dll(self):
        # The address rules below treat YYToolkit/hs-tests/ as "not shipped".
        # That is only true while nothing pulls those files into the project.
        problems = []
        for parsed in self.parsed:
            for path, number, text in parsed.added(shipped_only=True):
                project = path.endswith((".vcxproj", ".filters", ".props", ".sln"))
                include = re.match(r"\s*#\s*include\b", text)
                if "hs-tests" in text and (project or include):
                    problems.append(f"{parsed.name}:{number} ({path}): {text.strip()[:80]!r} "
                                    f"brings a host test into the DLL build")
        self.assertNoProblems(problems, "host tests must stay standalone executables:")


class Bytes(SeriesCase):
    def test_no_cr_and_a_final_newline(self):
        problems = []
        for path in [SERIES] + sorted(PATCH_DIR.glob("*.patch")):
            data = path.read_bytes()
            rel = path.relative_to(ROOT).as_posix()
            if b"\r" in data:
                problems.append(
                    f"{rel} contains {data.count(bytes([13]))} CR byte(s). Upstream's blobs are LF "
                    f"and `git apply` compares context byte for byte. Check .gitattributes still "
                    f"covers it, then `git add --renormalize` or regenerate the file.")
            if not data.endswith(b"\n"):
                problems.append(f"{rel} does not end in a newline; an editor truncated it")
        self.assertNoProblems(problems, "line endings:")

    def test_header_paths_with_a_space_keep_their_tab(self):
        # `--- a/source/Module Internals/x.cpp<TAB>`: git ends such a path with a
        # TAB, and an editor that strips trailing whitespace destroys it.
        problems = []
        for parsed in self.parsed:
            for diff in parsed.files:
                for number, line in diff.path_lines:
                    if " " in diff.path and "/dev/null" not in line and not line.endswith("\t"):
                        problems.append(f"{parsed.name}:{number}: {line[:60]!r}... lost the TAB "
                                        f"that ends a path containing a space")
        self.assertNoProblems(problems, "trailing whitespace was stripped from a patch:")

    def test_gitattributes_protects_the_series(self):
        rules = {}
        for line in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if parts and not parts[0].startswith("#"):
                rules[parts[0]] = parts[1:]
        for pattern, attribute in (("third_party/yytoolkit/patches/*.patch", "-text"),
                                   ("third_party/yytoolkit/patches/series", "eol=lf"),
                                   ("third_party/yytoolkit/LICENSE", "-text")):
            self.assertIn(
                attribute, rules.get(pattern, []),
                f".gitattributes must keep `{pattern} {attribute}`: with core.autocrlf on, a "
                f"fresh Windows clone otherwise rewrites the file to CRLF and the series stops "
                f"applying (or LICENSE stops being upstream's blob)")


class NoDecompiledOutput(SeriesCase):
    """`.patch` is not a suffix the PostToolUse hook watches, so without this
    nothing reads what the series adds."""

    @staticmethod
    def offender() -> str:
        # Assembled here so this file never contains the shape it looks for.
        return "sub" + "_" + "140A3F2C0"

    def test_controls(self):
        line = f"\tauto target = {self.offender()}(self, other);"
        added = parse_patch("c.patch", synthetic_patch(line))
        problems = legal_problems("c.patch", patch_lines_we_wrote(added))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("IDA", problems[0])

        context = parse_patch("c.patch", synthetic_patch("int ours = 1;", context=line))
        self.assertEqual(legal_problems("c.patch", patch_lines_we_wrote(context)), [])

    def test_patches_add_no_listing_text(self):
        problems = []
        for parsed in self.parsed:
            problems += legal_problems(f"third_party/yytoolkit/patches/{parsed.name}",
                                       patch_lines_we_wrote(parsed))
        self.assertNoProblems(
            problems, "AGENTS.md, 'Legal: Decompiled Output Never Reaches Any Origin' - describe "
                      "what was learned in your own words, in the message and in the code:")

    def test_readme_and_notice_carry_no_listing_text(self):
        problems = (legal_problems("third_party/yytoolkit/README.md", numbered(self.readme))
                    + legal_problems("third_party/yytoolkit/NOTICE.md", numbered(self.notice)))
        self.assertNoProblems(problems, "decompiler or VM listing text in the series' documents:")


class NoHandResolvedAddress(SeriesCase):
    def test_controls(self):
        def problems(added, **kwargs):
            return address_problems(parse_patch("c.patch", synthetic_patch(added, **kwargs)))

        base_plus = "\tauto fn = (Fn)((char*)GetModuleHandleA(nullptr) + 0xB489070);"
        self.assertTrue(any("module handle" in p for p in problems(base_plus)))
        self.assertTrue(any("base plus" in p for p in problems("\tcall(game_base + 0xB555351);")))
        self.assertEqual(len(problems("\tconstexpr uint32_t kHookRva = 0xB555351;")), 2)
        self.assertEqual(len(problems("\tconstexpr uint32_t HOOK_RVA{ 190141265 };")), 1)
        self.assertEqual(len(problems("\tuintptr_t where = 0x7FF7D2F80000;")), 1)

        for harmless in ("\tuint64_t HookRva = 0;",
                         "\tif (line.ChainRva == 190142434) return;",
                         "\tconstexpr uint64_t YYERROR_SUMMARY_INTERVAL_MS = 30000;",
                         "\tconstexpr size_t EDGE_PAGE_RESERVATION = 8 * 1024 * 1024;",
                         "\tconst auto page = text_base + (index * 0x1000);",
                         "\tconst auto target = game_base + line.ChainRva;",
                         "\tif ((byte & 0xF8) == 0x48 && window <= 0x400) mask = 0xFFFFF;"):
            self.assertEqual(problems(harmless), [], harmless)
        # Upstream's line, not ours.
        self.assertEqual(problems("int ours = 1;", context=base_plus), [])

        # An allowlist entry covers its own file only, and "comment" means comment.
        value = "0x100000001B3"
        self.assertEqual(problems(f"\tprime = {value};", path=_LEDGER), [])
        self.assertEqual(len(problems(f"\tprime = {value};")), 1)
        noted = _GENERIC + "Generic-RunnerInterfaceNew.cpp"
        self.assertEqual(problems("\t// seen once, at rva 0xB5557E2", path=noted), [])
        self.assertEqual(len(problems("\thook_at(0xB5557E2);", path=noted)), 1)

    def test_patches_add_no_hand_resolved_address(self):
        used: set = set()
        problems = []
        for parsed in self.parsed:
            problems += address_problems(parsed, used)
        self.assertNoProblems(
            problems, "AGENTS.md, 'Never Call an Address You Resolved by Hand':")
        stale = [repr(key) for key in list(BIG_HEX_ALLOWED) + list(RVA_ASSIGNMENT_ALLOWED)
                 if key not in used]
        self.assertNoProblems(
            stale, "allowlist entries in tests/test_yytoolkit_patch_series.py that no patch needs "
                   "any more - delete them, an unused exemption is a hole:")

    def test_the_allowlists_cannot_exempt_shipped_code_from_the_rva_rule(self):
        for path, identifier, value in RVA_ASSIGNMENT_ALLOWED:
            self.assertTrue(
                path.startswith(HOST_TESTS),
                f"RVA_ASSIGNMENT_ALLOWED exempts `{identifier} = {value}` in {path}, which is "
                f"compiled into the DLL. Only a host test may hold such a number.")
        for (path, value), (scope, reason) in BIG_HEX_ALLOWED.items():
            self.assertIn(scope, ("code", "comment"), (path, value))
            self.assertTrue(reason.strip(), f"{path} {value:#x}: every entry says why")


class NoPersonIdentifyingPath(SeriesCase):
    def test_controls(self):
        # As C++ source spells it, backslashes doubled. A made-up name, nobody's.
        named = "C:\\\\Users\\\\jdoe\\\\trace\\\\crumbs.txt"
        added = parse_patch("c.patch", synthetic_patch(f'\tOpen("{named}");'))
        self.assertEqual(len(user_path_problems("c.patch", patch_lines_we_wrote(added))), 1)
        forward = numbered("see C:/Users/jdoe/yk/evidence")
        self.assertEqual(len(user_path_problems("doc.md", forward)), 1)

        for harmless in ('\tCheck(Narrow(L"C:\\\\Users\\\\SomeUser\\\\mods\\\\Plugin.dll"));',
                         "\t// %LOCALAPPDATA%\\hstk\\yk, or C:\\Users\\%USERNAME%\\x",
                         "\t// C:\\src\\YYToolkit and C:\\yk"):
            parsed = parse_patch("c.patch", synthetic_patch(harmless))
            self.assertEqual(user_path_problems("c.patch", patch_lines_we_wrote(parsed)), [], harmless)
        context = parse_patch("c.patch", synthetic_patch("int ours = 1;", context=f'Open("{named}");'))
        self.assertEqual(user_path_problems("c.patch", patch_lines_we_wrote(context)), [])

    def test_patches_readme_and_notice_name_no_user_profile(self):
        problems = []
        for parsed in self.parsed:
            problems += user_path_problems(f"third_party/yytoolkit/patches/{parsed.name}",
                                           patch_lines_we_wrote(parsed))
        problems += user_path_problems("third_party/yytoolkit/README.md", numbered(self.readme))
        problems += user_path_problems("third_party/yytoolkit/NOTICE.md", numbered(self.notice))
        self.assertNoProblems(
            problems, "the previously distributed DLL wrote to a path under its builder's "
                      "profile; nothing here repeats that, in code or in prose:")


class CitedEvidenceIsExplained(SeriesCase):
    @staticmethod
    def message(text: str) -> ParsedPatch:
        parsed = ParsedPatch("c.patch")
        parsed.header = [(8, f"Evidence: {text}")]
        return parsed

    def test_controls(self):
        cites = self.message("evidence/some-run.YYToolkit.log:3 shows the cache hit.")
        problems = unexplained_evidence_problems([cites], "a guide that never mentions it")
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("c.patch:8", problems[0])
        self.assertEqual(
            unexplained_evidence_problems([cites], "`evidence/some-run.YYToolkit.log` is kept ..."), [])
        # Prose that merely contains the letters is not a citation.
        prose = self.message("the change was undocumented/unlisted; no evidence, shipped-strings differ")
        self.assertEqual(unexplained_evidence_problems([prose], ""), [])

    def test_the_readme_explains_every_local_file_a_message_cites(self):
        self.assertNoProblems(
            unexplained_evidence_problems(self.parsed, self.readme),
            "patch messages cite files a reader of the repository cannot open:")
        # The positive control on the real series: if no message cited anything
        # the rule above would pass while checking nothing.
        cited = [kind for kind, pattern in LOCAL_EVIDENCE.items()
                 if any(pattern.search(text) for parsed in self.parsed for _n, text in parsed.header)]
        self.assertTrue(cited, "no patch message cites a local evidence file any more; delete "
                               "LOCAL_EVIDENCE and this class rather than keeping a dead check")


class NoticeAndLicence(SeriesCase):
    def test_notice_says_what_a_modification_notice_must(self):
        notice = self.notice
        required = (
            ("AGPL-3.0", "the licence"),
            (self.pin["repo"], "where upstream's source is (the `repo` in upstream.json)"),
            ("upstream.json", "the file that pins the base commit"),
            ("third_party/yytoolkit/patches", "where the changes are"),
            ("tools/build_yytoolkit.py", "how the binary is produced from them"),
        )
        for needle, what in required:
            self.assertIn(needle, notice,
                          f"third_party/yytoolkit/NOTICE.md must state {what}: {needle!r} is "
                          f"missing. It ships beside the DLL as the AGPL section 5 notice.")
        self.assertRegex(notice, r"(?i)\bmodified\b",
                         "NOTICE.md must say, in that word, that this YYToolkit is MODIFIED")

    def test_license_is_upstreams_blob(self):
        # Raw bytes: .gitattributes marks the file -text, so they are the same
        # on every checkout, and one converted line ending changes the id.
        actual = git_blob_id(LICENSE.read_bytes())
        self.assertEqual(
            actual, LICENSE_BLOB,
            f"third_party/yytoolkit/LICENSE hashes to git blob {actual}, upstream's LICENSE at "
            f"the pin is {LICENSE_BLOB}. Restore upstream's file byte for byte (check for CRLF); "
            f"change LICENSE_BLOB here only when the pin moves AND upstream changed its licence "
            f"file.")

    def test_control_the_blob_id_is_gits(self):
        # `git hash-object` of an empty file; proves the framing, not just a hash.
        self.assertEqual(git_blob_id(b""), "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")


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
            problems.append(
                f"{rel}: third_party/yytoolkit/ holds .md, .json, .patch, `series` and LICENSE "
                f"only. No upstream source (the pin names it), no binary (the hub bans *.dll), "
                f"no log or evidence file (they carry machine paths). Keep it outside the repo.")
        self.assertNoProblems(problems, "unexpected files:")


class HubDocsPointHere(SeriesCase):
    def test_docs_mention_the_series_directory(self):
        for rel in SYNCED_DOCS:
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn(
                "third_party/yytoolkit", text,
                f"{rel} no longer mentions third_party/yytoolkit. It is where a reader looking "
                f"for the distributed YYToolkit.dll's source has to be sent; restore the pointer.")

    def test_agents_md_names_this_test(self):
        self.assertIn("tests/test_yytoolkit_patch_series.py",
                      (ROOT / "AGENTS.md").read_text(encoding="utf-8"),
                      "AGENTS.md ('YYToolkit Integration') names this file as the mechanical "
                      "check; update it if the test is renamed")


class SeriesRevision(SeriesCase):
    DEFINITION = re.compile(r'\bg_HeroSiegeSeriesRevision\s*=\s*"([^"]*)"\s*;')

    def test_upstream_json_the_dll_and_the_docs_agree(self):
        defined = [(parsed.name, match.group(1))
                   for parsed in self.parsed for _path, _number, text in parsed.added(shipped_only=True)
                   for match in [self.DEFINITION.search(text)] if match]
        self.assertEqual(
            len(defined), 1,
            f"exactly one patch must add the line defining g_HeroSiegeSeriesRevision (the literal "
            f"in the DLL's first log line); found {defined}")
        patch, literal = defined[0]
        revision = self.pin.get("series_revision")
        self.assertEqual(
            revision, literal,
            f"upstream.json says series_revision {revision!r}, {patch} compiles {literal!r} into "
            f"the DLL. Bump BOTH in the same change, or a YYToolkit.log stops identifying the "
            f"source it came from.")
        for path, text in ((README, self.readme), (NOTICE, self.notice)):
            self.assertIn(
                f"`{literal}`", text,
                f"{path.relative_to(ROOT).as_posix()} does not name series revision `{literal}`; "
                f"update the expected build result and the revision there when the series changes")


#: A pin whose sha256 matches the series and carries neither zip-member key is
#: a plain file pin fetched straight from a GitHub release asset of the HUB
#: repository (not ForgePact's own releases, which is where the legacy pin's
#: zip lived).
HUB_RELEASE_URL_MARKER = "/hero-siege-offline-toolkit/releases/download/"

#: 64 lowercase hex characters, not glued to more hex on either side -- a
#: sha256 in hex, and never a sha1/commit id (those are shorter).
SHA256_TOKEN = re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{64}(?![0-9a-fA-F])")


def classify_forgepact_yytoolkit_pin(
    entry: Dict[str, object], series_sha: str, legacy_sha: str
) -> Tuple[str, str]:
    """Classify one `modfiles_shipped/YYToolkit.dll` entry from ForgePact's
    `tools/toolchain-pins.json` against the two pins that entry has ever
    legitimately held. Pure function: no filesystem, no git -- a synthetic
    `entry` dict exercises every branch (see
    `ClassifyForgePactYYToolkitPinControls` below).

    "migrated": `sha256` equals `series_sha`, the entry is a plain file pin
    (neither a `"member"` nor an `"archive_sha256"` key) and its `url` is a
    release asset of the HUB repository (contains `HUB_RELEASE_URL_MARKER`).
    This is ForgePact's own change that moves the pin, once merged.

    "legacy": `sha256` equals `legacy_sha` and the entry is in zip-member
    form (has both `"member"` and `"archive_sha256"`) -- the pre-migration
    state: the recorded ForgePact revision predates ForgePact's pin move.

    Anything else is "drifted", with a reason naming precisely what is
    wrong: a third hash; the series hash still in zip-member form or not on
    a hub release URL; the legacy hash presented as a plain hub-release pin;
    or a missing `sha256`.
    """
    sha = entry.get("sha256")
    is_plain_pin = "member" not in entry and "archive_sha256" not in entry
    is_zip_member_pin = "member" in entry and "archive_sha256" in entry
    url = str(entry.get("url", ""))
    on_hub_release = HUB_RELEASE_URL_MARKER in url

    if not sha:
        return "drifted", "the entry has no \"sha256\" key"

    if sha == series_sha:
        if not is_plain_pin:
            return "drifted", (
                f"sha256 {sha} matches the series hash, but the entry is not a plain file pin "
                f"(it carries \"member\" and/or \"archive_sha256\"); a migrated pin has neither")
        if not on_hub_release:
            return "drifted", (
                f"sha256 {sha} matches the series hash as a plain file pin, but its url {url!r} "
                f"is not a hub release asset (expected one containing "
                f"{HUB_RELEASE_URL_MARKER!r})")
        return "migrated", f"sha256 {sha} matches the series hash, plain file pin, hub release url"

    if sha == legacy_sha:
        if not is_zip_member_pin:
            return "drifted", (
                f"sha256 {sha} matches the legacy (pre-migration) hash, but the entry is not in "
                f"zip-member form (it needs both \"member\" and \"archive_sha256\"); the legacy "
                f"pin is a zip-member pin, never a plain hub-release pin")
        return "legacy", f"sha256 {sha} matches the legacy hash, zip-member form"

    return "drifted", (
        f"sha256 {sha} is neither the series hash ({series_sha}) nor the legacy hash "
        f"({legacy_sha})")


def notice_legacy_yytoolkit_sha(notice_text: str, series_sha: str) -> str:
    """The one sha256 in NOTICE.md that is not the series hash: the
    previously distributed DLL's, under "About the previously distributed
    binary". Asserts there is exactly one, so a second, unrelated 64-hex
    string added to NOTICE.md later can never silently widen what
    `classify_forgepact_yytoolkit_pin` accepts as "legacy"."""
    others = sorted({m.group(0) for m in SHA256_TOKEN.finditer(notice_text)} - {series_sha})
    if len(others) != 1:
        raise AssertionError(
            f"third_party/yytoolkit/NOTICE.md must contain exactly one sha256 other than the "
            f"series hash ({series_sha}) -- the previously distributed DLL's, under \"About the "
            f"previously distributed binary\". Found {len(others)}: {others}")
    return others[0]


class ForgePactPinMatchesThisSeries(SeriesCase):
    """ADR 0002: the hub cannot change what a player receives - only a
    submodule's own pin does that, and it drifts silently unless something
    reads both sides. Hub CI has no submodules, so
    `test_forgepact_pin_is_migrated_or_legacy` is opt-in: it skips, saying
    why, when ForgePact/ is not checked out.

    Two pin states pass here, not one: "migrated" (the pin points at this
    series' hub release asset) and "legacy" (the pin is still the
    previously distributed DLL, in its original zip-member form). That is
    deliberate, not a loophole. The hub's ForgePact gitlink can only move
    past the commit that moves the pin AFTER ForgePact's own pull request
    doing that has merged to ForgePact's default branch - the hub's pointer
    automation accepts only default-branch commits - so a plain, correct
    `git submodule update --init ForgePact` on an in-flight hub branch
    legitimately produces "legacy", not "migrated", until then.

    The "legacy" branch of this check is TEMPORARY. Delete it - and this
    paragraph - in the same hub change that bumps the ForgePact gitlink past
    the commit that moves the pin, so that only "migrated" passes from that
    point on. third_party/yytoolkit/README.md's "Follow-ups in the submodule
    repos" section carries the same instruction.
    """

    #: `Expected result for `hs.1`: **950,784 bytes, sha256\n`<hex>`**` in the
    #: "How to build" section - the one place this README states the sha256 a
    #: build of the pinned series is expected to produce.
    EXPECTED_SHA = re.compile(
        r"Expected result for `[^`]+`:\s*\*\*[\d,]+ bytes, sha256\s*\n`([0-9a-f]{64})`\*\*")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        match = cls.EXPECTED_SHA.search(cls.readme)
        if match is None:
            raise AssertionError(
                "third_party/yytoolkit/README.md's \"How to build\" section no longer states "
                "an expected sha256 for a build of this series; this test has nothing to "
                "classify ForgePact's pin against")
        cls.series_sha = match.group(1)
        cls.legacy_sha = notice_legacy_yytoolkit_sha(cls.notice, cls.series_sha)

    def _single_yytoolkit_entry(self, pins: dict) -> dict:
        entries = [f for f in pins.get("files", [])
                   if f.get("dest", "").endswith("modfiles_shipped/YYToolkit.dll")]
        self.assertEqual(
            len(entries), 1,
            f"expected exactly one modfiles_shipped/YYToolkit.dll entry in "
            f"ForgePact/tools/toolchain-pins.json; found {len(entries)}")
        return entries[0]

    def test_forgepact_pin_is_migrated_or_legacy(self):
        pins_path = ROOT / "ForgePact" / "tools" / "toolchain-pins.json"
        if not pins_path.is_file():
            self.skipTest(f"{pins_path.relative_to(ROOT).as_posix()} is not present -- "
                          f"ForgePact/ is not checked out (hub CI runs without submodules)")
        pins = json.loads(pins_path.read_text(encoding="utf-8"))
        entry = self._single_yytoolkit_entry(pins)
        state, reason = classify_forgepact_yytoolkit_pin(entry, self.series_sha, self.legacy_sha)
        self.assertNotEqual(
            state, "drifted",
            f"ForgePact/tools/toolchain-pins.json's modfiles_shipped/YYToolkit.dll pin is "
            f"drifted: {reason}")


class ClassifyForgePactYYToolkitPinControls(unittest.TestCase):
    """Unit-level controls for `classify_forgepact_yytoolkit_pin`, entirely
    synthetic -- no filesystem, so these never move when the real hashes in
    third_party/yytoolkit/README.md or NOTICE.md do
    (`ForgePactPinRealRevisionControls` below exercises the same function
    against real ForgePact history instead)."""

    SERIES = "1" * 64
    LEGACY = "2" * 64

    MIGRATED_ENTRY = {
        "dest": "modfiles_shipped/YYToolkit.dll",
        "url": "https://github.com/falorfrozen-cmd/hero-siege-offline-toolkit/releases/"
               "download/yytoolkit-v4.0.1-hs.1/YYToolkit.dll",
        "sha256": SERIES,
        "provenance": "modified YYToolkit, built from the hub's third_party/yytoolkit/ series",
    }
    LEGACY_ENTRY = {
        "dest": "modfiles_shipped/YYToolkit.dll",
        "url": "https://github.com/falorfrozen-cmd/ForgePact/releases/download/v1.3.16/"
               "ForgePact-1.3.16.zip",
        "archive_sha256": "3" * 64,
        "member": "ForgePact-1.3.16/modfiles/YYToolkit.dll",
        "sha256": LEGACY,
    }

    def classify(self, entry: dict) -> Tuple[str, str]:
        return classify_forgepact_yytoolkit_pin(entry, self.SERIES, self.LEGACY)

    def test_migrated_pin_is_accepted(self):
        state, reason = self.classify(self.MIGRATED_ENTRY)
        self.assertEqual(state, "migrated", reason)

    def test_legacy_pin_is_accepted(self):
        state, reason = self.classify(self.LEGACY_ENTRY)
        self.assertEqual(state, "legacy", reason)

    # -- negative controls: each must classify "drifted" and say why --

    def test_a_third_hash_is_drifted(self):
        entry = dict(self.MIGRATED_ENTRY, sha256="4" * 64)
        state, reason = self.classify(entry)
        self.assertEqual(state, "drifted")
        self.assertIn("neither the series hash", reason)

    def test_series_hash_in_zip_member_form_is_drifted(self):
        entry = dict(self.LEGACY_ENTRY, sha256=self.SERIES)
        state, reason = self.classify(entry)
        self.assertEqual(state, "drifted")
        self.assertIn("not a plain file pin", reason)

    def test_series_hash_off_a_hub_release_is_drifted(self):
        entry = dict(self.MIGRATED_ENTRY,
                     url="https://github.com/falorfrozen-cmd/ForgePact/releases/download/"
                         "v1.3.17/YYToolkit.dll")
        state, reason = self.classify(entry)
        self.assertEqual(state, "drifted")
        self.assertIn("not a hub release asset", reason)

    def test_legacy_hash_as_a_plain_hub_release_pin_is_drifted(self):
        entry = dict(self.MIGRATED_ENTRY, sha256=self.LEGACY)
        state, reason = self.classify(entry)
        self.assertEqual(state, "drifted")
        self.assertIn("not in zip-member form", reason)

    def test_missing_sha256_is_drifted(self):
        entry = {k: v for k, v in self.MIGRATED_ENTRY.items() if k != "sha256"}
        state, reason = self.classify(entry)
        self.assertEqual(state, "drifted")
        self.assertIn("sha256", reason)


class ForgePactPinRealRevisionControls(SeriesCase):
    """Controls `classify_forgepact_yytoolkit_pin` against real ForgePact
    revisions, read with `git show` -- the ForgePact working tree is never
    touched. Skips (never fails) whenever the object these need is not
    available locally: this class proves the classifier against real
    history, it does not require a network fetch."""

    FORGEPACT_DIR = ROOT / "ForgePact"
    #: The branch ForgePact's still-unmerged pin-move change lives on
    #: (third_party/yytoolkit/README.md, "Follow-ups in the submodule
    #: repos"). A branch name, not a commit id, so it never goes stale here.
    MIGRATED_BRANCH = "claude/yytoolkit-hs1-distribution"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        match = ForgePactPinMatchesThisSeries.EXPECTED_SHA.search(cls.readme)
        cls.series_sha = match.group(1) if match else None
        cls.legacy_sha = (notice_legacy_yytoolkit_sha(cls.notice, cls.series_sha)
                          if cls.series_sha else None)

    def _forgepact_checked_out(self) -> bool:
        return (self.FORGEPACT_DIR / ".git").exists()

    def _read_pins_at(self, rev: str) -> Optional[dict]:
        result = subprocess.run(
            ["git", "-C", str(self.FORGEPACT_DIR), "show", f"{rev}:tools/toolchain-pins.json"],
            capture_output=True, text=True)
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

    def _single_entry(self, pins: dict) -> dict:
        entries = [f for f in pins.get("files", [])
                   if f.get("dest", "").endswith("modfiles_shipped/YYToolkit.dll")]
        self.assertEqual(len(entries), 1, entries)
        return entries[0]

    def _recorded_gitlink(self) -> Optional[str]:
        # The revision a plain `git submodule update --init ForgePact` checks
        # out - deliberately NOT `git -C ForgePact rev-parse HEAD`, which
        # reads the working tree's own checkout and can be ahead of what the
        # hub commit actually records (exactly the discrepancy this test
        # class exists to catch).
        result = subprocess.run(["git", "ls-tree", "HEAD", "ForgePact"],
                                cwd=ROOT, capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        fields = result.stdout.split()
        return fields[2] if len(fields) >= 3 else None

    def test_the_recorded_gitlink_is_not_drifted(self):
        if not self._forgepact_checked_out():
            self.skipTest("ForgePact/ is not checked out")
        rev = self._recorded_gitlink()
        if not rev:
            self.skipTest("could not read the ForgePact gitlink with `git ls-tree HEAD ForgePact`")
        pins = self._read_pins_at(rev)
        if pins is None:
            self.skipTest(f"ForgePact's local object store does not have {rev[:12]} (the hub's "
                          f"recorded gitlink); fetch it there to run this control")
        entry = self._single_entry(pins)
        state, reason = classify_forgepact_yytoolkit_pin(entry, self.series_sha, self.legacy_sha)
        self.assertNotEqual(
            state, "drifted",
            f"the hub's recorded ForgePact gitlink ({rev[:12]}) -- what a plain `git submodule "
            f"update --init ForgePact` checks out, i.e. the repository owner's reproduction -- "
            f"pins YYToolkit.dll in a way that is neither migrated nor legacy: {reason}")

    def test_the_forgepact_migrated_branch_head_is_migrated(self):
        if not self._forgepact_checked_out():
            self.skipTest("ForgePact/ is not checked out")
        check = subprocess.run(
            ["git", "-C", str(self.FORGEPACT_DIR), "rev-parse", "--verify", "--quiet",
             self.MIGRATED_BRANCH],
            capture_output=True, text=True)
        if check.returncode != 0:
            self.skipTest(f"ForgePact branch {self.MIGRATED_BRANCH!r} does not exist locally")
        pins = self._read_pins_at(self.MIGRATED_BRANCH)
        if pins is None:
            self.skipTest(f"{self.MIGRATED_BRANCH!r} exists locally but tools/toolchain-pins.json "
                          f"could not be read at it")
        entry = self._single_entry(pins)
        state, reason = classify_forgepact_yytoolkit_pin(entry, self.series_sha, self.legacy_sha)
        self.assertEqual(state, "migrated", reason)


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

        # The system temp directory: outside the repository (the tool refuses a
        # work directory inside it) and short enough for upstream's paths.
        base = Path(tempfile.mkdtemp(prefix="hstk-yk-"))
        self.addCleanup(tool.remove_tree, base)
        # The caller's git configuration stays: the clone is theirs, and a
        # `safe.directory` entry may be what lets git read it at all.
        environ = {k: v for k, v in os.environ.items()
                   if k.upper() not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX")}
        # The tool's own export and apply: core.autocrlf=false, GIT_NO_LAZY_FETCH,
        # the commit object and not the clone's checkout, every file re-hashed,
        # each patch `git apply --check`ed on top of the ones before it.
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

        # What the offline chain test has to take on trust.
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
