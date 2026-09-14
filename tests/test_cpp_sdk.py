"""Compiles and runs the C++ SDK behavioural tests, then checks cross-language parity.

`tests/cpp/test_sdk_player_hooks.cpp` exercises the two helpers in the C++ SDK
that Python cannot reach - the relic scanner in `player.hpp` and the script-hook
installer in `hooks.hpp` - through the unchanged production headers, with the
YYToolkit and Aurie surfaces supplied by `tests/cpp/stubs`.

Skips when no C++ compiler is available, so the default suite still runs in a
clean checkout without build tools.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PY_PATH = ROOT / "hs-game-sdk" / "python"
if str(SDK_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SDK_PY_PATH))

from hs_game_sdk import (  # noqa: E402
    GENERAL_CONTAINER_FIELDS,
    MAX_SCAN_DEPTH,
    MAX_SCANNED_ARRAY_LENGTH,
    MAXED_RELIC_LEVEL,
    RELIC_CONTAINER_FIELDS,
    RELIC_ID_FIELDS,
    RELIC_ID_LIMIT,
    RELIC_LEVEL_FIELDS,
    RELIC_ONLY_FIELD,
    RELIC_RARITY_TIER,
    RELIC_TIER_FIELDS,
    scan_relic_levels,
)

CPP_DIR = ROOT / "tests" / "cpp"
SOURCE = CPP_DIR / "test_sdk_player_hooks.cpp"
STUBS = CPP_DIR / "stubs"
SDK_INCLUDE = ROOT / "hs-game-sdk" / "cpp" / "include"

# The fixture shared with the C++ side: the ordinary item the review reported
# plus a real maxed relic. Both languages must agree on {42: 10}.
PARITY_FIXTURE = {
    "equippedItems": [
        {"b": 15, "c": 8, "level": 100},
        {"b": 42, "c": 16, "o": 10},
    ]
}

# The three layouts from origin's second review of PR #3, where C++ accepted
# records Python dropped. Each is passed to the C++ scanner by the harness under
# the matching `CASE` label and to scan_relic_levels() here, and both must agree.
# The negative control stays: numbers in a general container mean nothing.
CROSS_LANGUAGE_CASES = {
    "relic_levels_numeric": ({"relic_levels": [0, 0, 10]}, {2: 10}),
    "inventory_cls_item": ({"inventory": [{"b": 42, "cls": 16, "o": 10}]}, {42: 10}),
    "inventory_numeric_negative_control": ({"inventory": [0, 0, 10]}, {}),
}


def _vcvars_path() -> Path | None:
    """Locate a Visual Studio build environment script, if one is installed."""
    program_files = os.environ.get("ProgramFiles(x86)") or os.environ.get("ProgramFiles")
    if not program_files:
        return None
    vswhere = Path(program_files) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.exists():
        return None
    try:
        out = subprocess.run(
            [
                str(vswhere), "-latest", "-products", "*",
                "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-property", "installationPath",
            ],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    install = out.stdout.strip().splitlines()
    if not install:
        return None
    script = Path(install[0]) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
    return script if script.exists() else None


def _build_and_run_msvc(work: Path) -> subprocess.CompletedProcess:
    vcvars = _vcvars_path()
    if vcvars is None:
        raise unittest.SkipTest("no MSVC build tools found")
    # Via a batch file rather than `cmd /c "<long quoted string>"`, whose quote
    # handling silently drops the command when several quoted paths appear.
    script = work / "build_and_run.bat"
    script.write_text(
        "@echo off\r\n"
        f'call "{vcvars}" >nul 2>&1\r\n'
        f'cl /nologo /std:c++20 /EHsc /permissive- /W3 /I "{STUBS}" /I "{SDK_INCLUDE}" '
        f'"{SOURCE}" /Fe:harness.exe\r\n'
        "if errorlevel 1 exit /b 1\r\n"
        ".\\harness.exe\r\n",
        encoding="utf-8",
    )
    return subprocess.run(
        ["cmd", "/c", str(script)], cwd=work, capture_output=True, text=True, timeout=600
    )


def _build_and_run_gnu(work: Path, compiler: str) -> subprocess.CompletedProcess:
    exe = work / ("harness.exe" if os.name == "nt" else "harness")
    build = subprocess.run(
        [compiler, "-std=c++20", "-I", str(STUBS), "-I", str(SDK_INCLUDE),
         str(SOURCE), "-o", str(exe)],
        cwd=work, capture_output=True, text=True, timeout=600,
    )
    if build.returncode != 0:
        return build
    return subprocess.run([str(exe)], cwd=work, capture_output=True, text=True, timeout=300)


class TestCppSdkBehaviour(unittest.TestCase):
    output: str = ""

    @classmethod
    def setUpClass(cls):
        if os.name != "nt":
            # hooks.hpp uses VirtualQuery/GetModuleHandle: Windows-only by design.
            raise unittest.SkipTest("the C++ hook installer is Windows-only")
        if not SOURCE.exists():
            raise unittest.SkipTest(f"missing {SOURCE}")

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            compiler = shutil.which("g++") or shutil.which("clang++")
            if compiler:
                result = _build_and_run_gnu(work, compiler)
            else:
                result = _build_and_run_msvc(work)
            cls.output = (result.stdout or "") + (result.stderr or "")
            cls.returncode = result.returncode

    def test_harness_passed(self):
        self.assertIn("ALL C++ SDK CHECKS PASSED", self.output, self.output)
        self.assertEqual(self.returncode, 0, self.output)

    def test_ordinary_item_is_not_a_maxed_relic(self):
        """The exact case reported against PR #3."""
        self.assertIn("ordinary_item_id_15_flagged_maxed_relic=0", self.output, self.output)
        self.assertIn("real_relic_id_42_flagged_maxed_relic=1", self.output, self.output)

    def test_relics_are_found_through_an_instance_reference(self):
        """The player this runner resolves is a reference, not a struct.

        REPORTED 2026-09-14: the ForgePact relic filter armed and hooked but
        never suppressed a drop, because the scan rejected the VALUE_REF
        player before reading a single container.
        """
        self.assertIn("relic_scan_through_instance_reference=1", self.output, self.output)

    def test_numbers_in_a_general_container_invent_nothing(self):
        self.assertIn("numbers_in_general_container_invented_relics=0", self.output, self.output)

    def test_repeat_install_preserves_the_original(self):
        self.assertIn("original_points_to_hook=0", self.output, self.output)
        self.assertIn("original_still_trampoline=1", self.output, self.output)

    def test_first_install_is_native_and_swaps_the_table(self):
        self.assertIn("kind_native=1", self.output, self.output)
        self.assertIn("original_is_trampoline=1", self.output, self.output)
        self.assertIn("table_is_hook=1", self.output, self.output)

    def test_cpp_and_python_agree_on_the_same_fixture(self):
        cpp = {
            int(m.group(1)): int(m.group(2))
            for m in re.finditer(r"^PARITY_OWNED (\d+)=(\d+)$", self.output, re.MULTILINE)
        }
        self.assertTrue(cpp, f"harness printed no parity lines:\n{self.output}")
        self.assertEqual(cpp, scan_relic_levels(PARITY_FIXTURE))
        self.assertEqual(cpp, {42: 10})

    def _case_result(self, label: str) -> dict:
        match = re.search(rf"^CASE {re.escape(label)}(.*)$", self.output, re.MULTILINE)
        self.assertIsNotNone(match, f"harness printed no CASE {label}:\n{self.output}")
        return {
            int(pair.split("=")[0]): int(pair.split("=")[1])
            for pair in match.group(1).split()
        }

    def test_cross_language_cases_agree(self):
        """The layouts origin's second review found C++ accepting and Python dropping."""
        for label, (fixture, expected) in CROSS_LANGUAGE_CASES.items():
            with self.subTest(case=label):
                cpp = self._case_result(label)
                python = scan_relic_levels(fixture)
                self.assertEqual(cpp, expected, f"C++ changed for {label}")
                self.assertEqual(python, expected, f"Python changed for {label}")
                self.assertEqual(cpp, python, f"{label}: C++ {cpp} vs Python {python}")

    def _contract_fields(self, label: str) -> list:
        match = re.search(rf"^CONTRACT {re.escape(label)}(.*)$", self.output, re.MULTILINE)
        self.assertIsNotNone(match, f"harness printed no CONTRACT {label}:\n{self.output}")
        return match.group(1).split()

    def test_identification_contract_matches_between_bindings(self):
        """Guards against the two scanners drifting apart again.

        The C++ header declares these as enumerable constants purely so the
        harness can print them and this test can compare them field for field.
        """
        for label, python_value in [
            ("id_fields", RELIC_ID_FIELDS),
            ("tier_fields", RELIC_TIER_FIELDS),
            ("level_fields", RELIC_LEVEL_FIELDS),
            ("general_containers", GENERAL_CONTAINER_FIELDS),
            ("relic_containers", RELIC_CONTAINER_FIELDS),
        ]:
            with self.subTest(contract=label):
                self.assertEqual(self._contract_fields(label), list(python_value))

        for label, python_value in [
            ("relic_only_field", RELIC_ONLY_FIELD),
            ("rarity_tier", str(RELIC_RARITY_TIER)),
            ("id_limit", str(RELIC_ID_LIMIT)),
            ("maxed_level", str(MAXED_RELIC_LEVEL)),
            ("max_scan_depth", str(MAX_SCAN_DEPTH)),
            ("max_array_length", str(MAX_SCANNED_ARRAY_LENGTH)),
        ]:
            with self.subTest(contract=label):
                self.assertEqual(self._contract_fields(label), [str(python_value)])


if __name__ == "__main__":
    unittest.main()
