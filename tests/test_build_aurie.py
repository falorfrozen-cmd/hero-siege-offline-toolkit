"""Exercise tools/build_aurie.py, and the authoring path both products share,
offline against a synthetic mini-upstream.

`tools/build_aurie.py` is an entry point onto `tools/build_yytoolkit.py` with
the `AURIE` profile; tests/test_build_yytoolkit.py proves the steps themselves
and stays unedited. What this file adds:

  - the Aurie profile end to end (materialise, apply, build, hosttests,
    verify-dll, and `all` through the command line), with MSBuild, cl and the
    compiled host tests stubbed through the tool's injected runner as
    tests/test_build_yytoolkit.py stubs them. What it names, where it builds,
    what `verify-dll` writes and what the props file injects are Aurie's, and
    the YYToolkit profile is pinned beside it as the control;
  - the authoring path (`overlay`, `make-patch`) on BOTH profiles, starting
    from an empty series: two patches, a regenerated last one and a rename,
    the result checked against tests/test_yytoolkit_patch_series.py's own
    mail-shape, hunk-count and index-chain rules, and applied by `apply`;
  - every `make-patch` refusal as a pair: the refused input (positive control)
    and the nearest accepted one (negative control), with the patch directory
    proven untouched after the refusal.

The upstream is a throwaway git repository in the SYSTEM temp directory, under
a directory whose name contains a space, with a source path containing one too.
The "checkout" an overlay may or may not live in is a throwaway repository as
well, with `build/` ignored as the hub ignores it.

The last class builds the synthetic Aurie project for real with MSBuild and
cl, to show that the `/d1trimfile` the Aurie profile injects keeps the work
directory (a user-profile path by default) out of the DLL, with the same build
without it as the negative control. It skips, saying why, without the VS 2022
C++ build tools.
"""

import contextlib
import dataclasses
import hashlib
import importlib.util
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AURIE_PATH = ROOT / "tools" / "build_aurie.py"
SERIES_RULES_PATH = ROOT / "tests" / "test_yytoolkit_patch_series.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module     # @dataclass resolves annotations through sys.modules
    spec.loader.exec_module(module)
    return module


aurie = _load("build_aurie", AURIE_PATH)
core = aurie.core
# The YYToolkit series' own rules, imported rather than copied: a generated
# patch has to pass what a hand-made one would.
rules = _load("hstk_aurie_test_series_rules", SERIES_RULES_PATH)

GIT = shutil.which("git")
ROOMY = 250

MARKER_ONE = "hs-author-one: rejected candidate"
MARKER_TWO = "hs-author-two: accepted, with a comma"
NEGATIVE = b"upstream: negative"


def clean_git_env(config: Path) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX")}
    config.write_text("", encoding="utf-8")
    env["GIT_CONFIG_GLOBAL"] = str(config)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def git(cwd: Path, env: dict, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-c", "user.name=hstk", "-c", "user.email=hstk@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=cwd, env=env, check=True, capture_output=True,
    ).stdout


def vcxproj(product) -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
  <PropertyGroup Label="Globals">
    <VCProjectVersion>17.0</VCProjectVersion>
    <ProjectName>{product.project_name}</ProjectName>
    <WindowsTargetPlatformVersion>10.0</WindowsTargetPlatformVersion>
  </PropertyGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.Default.props" />
  <PropertyGroup Condition="'$(Configuration)|$(Platform)'=='Release|x64'" Label="Configuration">
    <ConfigurationType>DynamicLibrary</ConfigurationType>
    <UseDebugLibraries>false</UseDebugLibraries>
    <PlatformToolset>v143</PlatformToolset>
    <CharacterSet>Unicode</CharacterSet>
  </PropertyGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.props" />
  <ItemDefinitionGroup Condition="'$(Configuration)|$(Platform)'=='Release|x64'">
    <ClCompile>
      <WarningLevel>Level3</WarningLevel>
      <LanguageStandard>stdcpplatest</LanguageStandard>
      <RuntimeLibrary>MultiThreadedDLL</RuntimeLibrary>
      <Optimization>Disabled</Optimization>
    </ClCompile>
    <Link>
      <SubSystem>Console</SubSystem>
      <GenerateDebugInformation>true</GenerateDebugInformation>
    </Link>
  </ItemDefinitionGroup>
  <ItemGroup>
    <ClCompile Include="source\\Module Internals\\Hooks.cpp" />
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
""".encode()


# __FILE__ is returned, so it is in the DLL: the /d1trimfile class reads it.
HOOKS_BASE = b"""#include "filter.hpp"

extern "C" __declspec(dllexport) const char* hs_describe(int value)
{
\tif (hs_filter(value) < 0)
\t\treturn "upstream: negative";
\treturn "upstream: all good";
}

extern "C" __declspec(dllexport) const char* hs_where()
{
\treturn __FILE__;
}
"""
FILTER_BASE = b"#pragma once\ninline int hs_filter(int value) { return value; }\n"
FILTER_PATCHED = b"#pragma once\ninline int hs_filter(int value) { return value > 100 ? -1 : value; }\n"
HOST_TEST = b"""#include "Module Internals/filter.hpp"
#include <cstdio>

int main()
{
\tif (hs_filter(5) != 5 || hs_filter(500) != -1)
\t{
\t\tstd::puts("FAIL");
\t\treturn 1;
\t}
\tstd::puts("ok");
\treturn 0;
}
"""


class Layout:
    """Where the fixture puts things, for one product."""

    def __init__(self, product):
        self.product = product
        root = product.project[0]
        self.project = f"{root}/{product.project[1]}"
        self.hooks = f"{root}/source/Module Internals/Hooks.cpp"
        self.filter = f"{root}/source/Module Internals/filter.hpp"
        self.host_test = "/".join(product.host_tests) + "/test_filter.cpp"
        facing = product.plugin_facing[0]
        self.plugin_facing = facing + "Shared.hpp" if facing.endswith("/") else facing
        self.outside = "Outside/main.cpp"


class Upstream:
    """The pinned commit, then another commit and a dirty checkout: the tool
    exports the commit object, so neither may matter."""

    def __init__(self, base: Path, product):
        self.layout = Layout(product)
        self.repo = base / "up stream"
        self.env = clean_git_env(base / "gitconfig")
        self.repo.mkdir()
        git(self.repo, self.env, "init", "-q")
        lay = self.layout
        self.files = {
            "README.md": b"mini upstream\n",
            lay.project: vcxproj(product),
            lay.hooks: HOOKS_BASE,
            lay.filter: FILTER_BASE,
            lay.plugin_facing: b"#pragma once\nstruct PluginAbi { int value; };\n",
            lay.outside: b"int main() { return 0; }\n",
        }
        for rel, data in self.files.items():
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        git(self.repo, self.env, "add", "-A")
        git(self.repo, self.env, "commit", "-q", "-m", "pinned")
        self.commit = git(self.repo, self.env, "rev-parse", "HEAD").decode().strip()
        self.tree = git(self.repo, self.env, "rev-parse", "HEAD^{tree}").decode().strip()
        (self.repo / "README.md").write_bytes(b"moved on\n")
        git(self.repo, self.env, "commit", "-q", "-am", "later")
        (self.repo / lay.hooks).write_bytes(b"a local edit nobody committed\n")


class Call:
    def __init__(self, argv, cwd, env):
        self.argv, self.cwd, self.env = list(argv), cwd, dict(env or {})


class Recorder:
    def __init__(self, *stubs, passthrough=True):
        self.calls, self.stubs, self.passthrough = [], stubs, passthrough

    def __call__(self, argv, *, cwd=None, env=None, timeout=None, capture=True):
        call = Call(argv, cwd, env)
        self.calls.append(call)
        for stub in self.stubs:
            answer = stub(call)
            if answer is not None:
                return answer
        if not self.passthrough:
            raise AssertionError(f"unexpected process: {argv}")
        return core.run_process(argv, cwd=cwd, env=env, timeout=timeout, capture=capture)

    def named(self, exe: str):
        return [c for c in self.calls if os.path.basename(c.argv[0]).lower() == exe]


def done(call, code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(call.argv, code, stdout, stderr)


def scrub(path):
    try:
        core.remove_tree(path)
    except OSError:
        pass


FAKE_TOOLCHAIN = core.Toolchain("MSBuild.exe", "C:\\VS\\VC\\Auxiliary\\Build\\vcvars64.bat", "17.14.1")
GOOD_DLL = b"MZ\x90\x00" + b"\x00" * 64 + MARKER_ONE.encode() + b"\x00" + MARKER_TWO.encode() + b"\x00PE"
BUILD_STATE = "PlatformToolSet=v143:VCToolArchitecture=Native64Bit:VCToolsVersion=14.44.35207:"


class FakeTools:
    """MSBuild, cmd.exe running vcvars64 + cl, and the host-test executables,
    for whichever product the build is for."""

    def __init__(self, product, dll=GOOD_DLL, msbuild_code=0):
        self.product, self.dll, self.msbuild_code = product, dll, msbuild_code

    def __call__(self, call):
        exe = os.path.basename(call.argv[0]).lower()
        if exe == "msbuild.exe":
            if "-version" in call.argv:
                return done(call, stdout="17.14.60.43110\n")
            props = dict(a[3:].split("=", 1) for a in call.argv if a.startswith("/p:"))
            if self.msbuild_code == 0:
                Path(props["OutDir"]).mkdir(parents=True, exist_ok=True)
                (Path(props["OutDir"]) / self.product.dll_name).write_bytes(self.dll)
                name = self.product.project_name
                tlog = Path(props["IntDir"]) / f"{name}.tlog"
                tlog.mkdir(parents=True, exist_ok=True)
                (tlog / f"{name}.lastbuildstate").write_text(BUILD_STATE + "\nRelease|x64|\n")
            return done(call, self.msbuild_code)
        if exe == "cmd.exe":
            script = Path(call.argv[-1])
            if script.name == "clver.bat":
                return done(call, stdout="Microsoft (R) C/C++ Optimizing Compiler Version 19.44 for x64\n")
            script.with_suffix(".exe").write_bytes(b"MZ")
            return done(call, stdout="fake cl output")
        if exe.endswith(".exe") and Path(call.argv[0]).parent.name == "t":
            return done(call, stdout="fake test output")
        return None


def message(subject: str, markers: str, drop=None, **override) -> str:
    fields = {
        "Why": "a unit test needs a change to turn into a patch.",
        "Evidence": "none; the fixture upstream is made up by this test.",
        "Fails-safe": "not applicable, nothing built here ever reaches a player.",
        "Log-markers": markers,
        "Upstream-status": "not submitted, the upstream is a test fixture.",
    }
    fields.update(override)
    body = "\n\n".join(f"{key}: {value}" for key, value in fields.items() if key != drop)
    return f"{subject}\n\n{body}\n"


def snapshot(directory: Path) -> dict:
    return {p.relative_to(directory).as_posix(): p.read_bytes()
            for p in sorted(directory.rglob("*")) if p.is_file()} if directory.is_dir() else {}


@unittest.skipIf(GIT is None, "git is not on PATH; the tool drives git for every step")
class Rig(unittest.TestCase):
    """One upstream per class; a hub checkout (a git repository ignoring
    `build/`), pin directory, work directory and overlay per test."""

    PRODUCT = None

    @classmethod
    def setUpClass(cls):
        cls.class_base = Path(tempfile.mkdtemp(prefix="hstk au "))
        cls.addClassCleanup(scrub, cls.class_base)
        cls.upstream = Upstream(cls.class_base, cls.PRODUCT)
        cls.lay = cls.upstream.layout

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="hstk au "))
        self.addCleanup(scrub, self.base)
        self.hub = self.base / "hub"
        self.hub.mkdir()
        git(self.hub, self.upstream.env, "init", "-q")
        (self.hub / ".gitignore").write_text("build/\n", encoding="utf-8")
        self.pin_dir = self.hub / "third_party" / self.PRODUCT.zip_prefix.split("/")[1]
        (self.pin_dir / "patches").mkdir(parents=True)
        (self.pin_dir / "upstream.json").write_text(json.dumps({
            "repo": "https://github.com/AurieFramework/Example", "tag": "v1.0.0",
            "commit": self.upstream.commit, "tree": self.upstream.tree}, indent=2) + "\n")
        (self.pin_dir / "README.md").write_bytes(b"# the guide\n")
        self.work = self.base / "w"
        self.overlay = self.hub / "build" / "ov"
        self.lines = []
        self.recorder = Recorder()

    def ctx(self, *stubs, product=None):
        self.recorder = Recorder(*stubs)
        return core.Context(pin_dir=self.pin_dir, work_dir=self.work, runner=self.recorder,
                            environ=self.upstream.env, max_work_dir_len=ROOMY,
                            log=self.lines.append, product=product or self.PRODUCT)

    def materialised(self, *stubs):
        ctx = self.ctx(*stubs)
        core.materialise(ctx, self.upstream.repo)
        return ctx

    def write_message(self, text: str, name: str = "msg.txt") -> Path:
        path = self.base / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def edit(self, rel: str, old: bytes, new: bytes):
        path = self.overlay / rel
        data = path.read_bytes()
        self.assertIn(old, data)
        path.write_bytes(data.replace(old, new))

    def create(self, rel: str, data: bytes):
        path = self.overlay / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def first_patch(self, ctx):
        core.overlay_files(ctx, self.overlay, [self.lay.hooks])
        self.edit(self.lay.hooks, NEGATIVE, MARKER_ONE.encode())
        return core.make_patch(ctx, self.overlay,
                               self.write_message(message("first change", f'"{MARKER_ONE}"')),
                               name="0001-first.patch")

    def second_patch(self, ctx):
        core.overlay_files(ctx, self.overlay, [self.lay.filter])
        self.create(self.lay.filter, FILTER_PATCHED)
        self.create(self.lay.host_test, HOST_TEST)
        self.edit(self.lay.hooks, b"upstream: all good", MARKER_TWO.encode())
        return core.make_patch(ctx, self.overlay,
                               self.write_message(message("second change", f'"{MARKER_TWO}"')),
                               name="0002-second.patch")

    def series(self):
        return core.load_series(self.pin_dir)

    def assertRefusedUntouched(self, call, *needles):
        before = snapshot(self.pin_dir)
        with self.assertRaises(core.Refused) as refusal:
            call()
        for needle in needles:
            self.assertIn(needle, str(refusal.exception))
        self.assertEqual(snapshot(self.pin_dir), before, "a refusal wrote into the pin directory")
        return refusal.exception


# --------------------------------------------------------------------------
# the authoring path, on both profiles
# --------------------------------------------------------------------------

class AuthoringCases:
    def test_from_an_empty_series_two_patches_then_a_regenerated_last_one(self):
        ctx = self.materialised()
        self.assertEqual(core.load_series(self.pin_dir, allow_empty=True), [])
        with self.assertRaises(core.Refused):
            core.load_series(self.pin_dir)       # building still needs a patch

        copied = core.overlay_files(ctx, self.overlay, [self.lay.hooks])
        self.assertEqual(copied, [self.overlay / self.lay.hooks])
        self.assertEqual(copied[0].read_bytes(), HOOKS_BASE)
        self.edit(self.lay.hooks, NEGATIVE, MARKER_ONE.encode())
        first = core.make_patch(ctx, self.overlay, self.write_message(
            message("first change", f'"{MARKER_ONE}"')), name="0001-first.patch")
        self.assertEqual(first, self.pin_dir / "patches" / "0001-first.patch")
        self.assertEqual([p.name for p in self.series()], ["0001-first.patch"])
        self.assertEqual(self.series()[0].markers, (MARKER_ONE,))

        # overlay copies from upstream PLUS the series: the copy carries 0001.
        core.overlay_files(ctx, self.overlay, [self.lay.hooks], replace=True)
        self.assertIn(MARKER_ONE.encode(), (self.overlay / self.lay.hooks).read_bytes())
        second = self.second_patch(ctx)

        names = [p.name for p in self.series()]
        self.assertEqual(names, ["0001-first.patch", "0002-second.patch"])
        one, two = first.read_bytes(), second.read_bytes()
        self.assertIn(b"\nSubject: [PATCH 1/2] first change\n", one)   # renumbered
        self.assertIn(b"\nSubject: [PATCH 2/2] second change\n", two)
        sections = dict(core._diff_sections(two))
        self.assertEqual(sorted(sections), sorted([self.lay.hooks, self.lay.filter,
                                                   self.lay.host_test]))
        self.assertIn(b"\nnew file mode 100644\n", sections[self.lay.host_test])
        # A space in the path: the header keeps the TAB `git apply` needs.
        self.assertIn(f"--- a/{self.lay.hooks}\t".encode(), two)
        self.assert_series_shape()

        core.apply_series(ctx)
        src = self.work / "src"
        self.assertEqual((src / self.lay.filter).read_bytes(), FILTER_PATCHED)
        self.assertEqual((src / self.lay.host_test).read_bytes(), HOST_TEST)
        hooks = (src / self.lay.hooks).read_bytes()
        self.assertIn(MARKER_ONE.encode(), hooks)
        self.assertIn(MARKER_TWO.encode(), hooks)

        # Regenerate the last: diffed from the tree BEFORE it, so the change
        # it already made to filter.hpp stays even with the file gone from
        # the overlay, and only the host test changes.
        (self.overlay / self.lay.filter).unlink()
        self.create(self.lay.host_test, HOST_TEST.replace(b'"ok"', b'"all ok"'))
        regenerated = core.make_patch(ctx, self.overlay, self.write_message(
            message("second change, again", f'"{MARKER_TWO}"')), regenerate_last=True)
        self.assertEqual(regenerated, second)
        self.assertEqual([p.name for p in self.series()], names)
        again = regenerated.read_bytes()
        self.assertIn(b"\nSubject: [PATCH 2/2] second change, again\n", again)
        self.assertEqual(first.read_bytes(), one)                         # untouched
        self.assertEqual(sorted(dict(core._diff_sections(again))), sorted(sections))
        core.apply_series(ctx)
        self.assertEqual((src / self.lay.filter).read_bytes(), FILTER_PATCHED)
        self.assertIn(b'"all ok"', (src / self.lay.host_test).read_bytes())

        # ... and with a new slug the old file goes.
        renamed = core.make_patch(ctx, self.overlay, self.write_message(
            message("second change, renamed", f'"{MARKER_TWO}"')),
            name="0002-renamed.patch", regenerate_last=True)
        self.assertFalse(second.exists())
        self.assertEqual([p.name for p in self.series()], ["0001-first.patch", "0002-renamed.patch"])
        self.assertEqual((self.pin_dir / "patches" / "series").read_bytes(),
                         b"# application order\n0001-first.patch\n0002-renamed.patch\n")
        self.assertTrue(renamed.is_file())
        self.assert_series_shape()

    def assert_series_shape(self):
        """The YYToolkit series' own rules, on what the tool generated."""
        parsed = []
        for patch in self.series():
            data = patch.data
            self.assertNotIn(b"\r", data)
            self.assertTrue(data.startswith(core.MAIL_SEPARATOR.encode() + b"\n"))
            self.assertIn(f"\nFrom: {core.MAIL_FROM}\nDate: {core.MAIL_DATE}\n".encode(), data)
            item = rules.parse_patch(patch.name, data)
            self.assertEqual(item.problems, [], patch.name)
            self.assertEqual(rules.message_problems(item, data), [], patch.name)
            self.assertEqual(rules.marker_problems(item, patch.markers), [], patch.name)
            parsed.append(item)
        self.assertEqual(rules.BlobChain.chain_problems(parsed), [])

    def test_a_long_subject_is_folded_as_format_patch_folds_it(self):
        subject = "runner interface: refuse to publish an interface the walk did not find"
        self.assertEqual(core.fold_subject("[PATCH 7/7] " + subject), [
            "Subject: [PATCH 7/7] runner interface: refuse to publish an interface the walk",
            " did not find"])
        self.assertTrue(all(len(line) <= 78 for line in core.fold_subject("[PATCH 1/1] " + "x " * 60)))

    # -- refusals: each the refused input, then the nearest accepted one --

    def test_an_overlay_in_the_checkout_must_be_ignored_by_git(self):
        ctx = self.materialised()
        tracked = self.hub / "notignored" / "ov"
        exception = self.assertRefusedUntouched(
            lambda: core.overlay_files(ctx, tracked, [self.lay.hooks]), "does not ignore")
        self.assertIn(core.overlay_example(self.PRODUCT), str(exception))
        self.assertFalse(tracked.exists())
        self.assertRefusedUntouched(lambda: core.check_overlay(ctx, tracked), "does not ignore")
        # Controls: ignored inside the checkout, and outside it, are both fine.
        self.assertEqual(core.check_overlay(ctx, self.overlay), self.overlay)
        outside = self.base / "elsewhere"
        self.assertEqual(core.check_overlay(ctx, outside), outside)
        # Never the work directory or the pin directory.
        self.assertRefusedUntouched(lambda: core.check_overlay(ctx, self.work / "ov"), "work directory")
        self.assertRefusedUntouched(lambda: core.check_overlay(ctx, self.pin_dir / "ov"), "pin directory")

    def test_a_name_out_of_sequence_is_refused(self):
        ctx = self.materialised()
        core.overlay_files(ctx, self.overlay, [self.lay.hooks])
        self.edit(self.lay.hooks, NEGATIVE, MARKER_ONE.encode())
        msg = self.write_message(message("first change", f'"{MARKER_ONE}"'))
        for wrong in ("0002-first.patch", "1-first.patch", "0001-First.patch", "0001-first.diff",
                      "0001-.patch", "../0001-first.patch"):
            with self.subTest(name=wrong):
                self.assertRefusedUntouched(
                    lambda: core.make_patch(ctx, self.overlay, msg, name=wrong), "out of sequence")
        self.assertRefusedUntouched(lambda: core.make_patch(ctx, self.overlay, msg), "--name")
        self.assertRefusedUntouched(
            lambda: core.make_patch(ctx, self.overlay, msg, regenerate_last=True), "nothing")
        core.make_patch(ctx, self.overlay, msg, name="0001-first.patch")    # control
        self.edit(self.lay.hooks, b"upstream: all good", MARKER_TWO.encode())
        msg_two = self.write_message(message("second", f'"{MARKER_TWO}"'))
        self.assertRefusedUntouched(
            lambda: core.make_patch(ctx, self.overlay, msg_two, name="0001-again.patch"),
            "out of sequence")
        self.assertRefusedUntouched(
            lambda: core.make_patch(ctx, self.overlay, msg_two, name="0003-second.patch"),
            "out of sequence")
        self.assertRefusedUntouched(
            lambda: core.make_patch(ctx, self.overlay, msg_two, name="0002-x.patch",
                                    regenerate_last=True), "out of sequence")
        core.make_patch(ctx, self.overlay, msg_two, name="0002-second.patch")   # control

    def test_a_message_needs_all_five_fields_and_readable_markers(self):
        ctx = self.materialised()
        core.overlay_files(ctx, self.overlay, [self.lay.hooks])
        self.edit(self.lay.hooks, NEGATIVE, MARKER_ONE.encode())

        def attempt(text):
            return lambda: core.make_patch(ctx, self.overlay, self.write_message(text),
                                           name="0001-first.patch")

        for field in core.MESSAGE_FIELDS:
            with self.subTest(missing=field):
                self.assertRefusedUntouched(
                    attempt(message("first", f'"{MARKER_ONE}"', drop=field)), f"`{field}:`")
        for markers in ("bare words", '"short"', f'"{MARKER_ONE}" trailing'):
            with self.subTest(markers=markers):
                self.assertRefusedUntouched(attempt(message("first", markers)), "Log-markers")
        self.assertRefusedUntouched(attempt(message("first", f'"{MARKER_ONE}"', Why="")), "empty")
        self.assertRefusedUntouched(attempt("Why: no subject line\n\nEvidence: x\n"), "subject")
        self.assertRefusedUntouched(attempt(message("[PATCH 1/1] first", f'"{MARKER_ONE}"')),
                                    "[PATCH")
        self.assertRefusedUntouched(attempt(message("first", f'"{MARKER_ONE}"') + "---\n"),
                                    "end the message")
        # Controls: complete, with a marker, and with `none`.
        attempt(message("first", "none"))()
        self.assertEqual(self.series()[0].markers, ())
        core.make_patch(ctx, self.overlay, self.write_message(message("first", f'"{MARKER_ONE}"')),
                        regenerate_last=True)
        self.assertEqual(self.series()[0].markers, (MARKER_ONE,))

    def test_an_overlay_that_changes_nothing_is_refused(self):
        ctx = self.materialised()
        msg = self.write_message(message("nothing", "none"))
        self.assertRefusedUntouched(
            lambda: core.make_patch(ctx, self.overlay, msg, name="0001-nothing.patch"),
            "not a directory")
        self.overlay.mkdir(parents=True)
        self.assertRefusedUntouched(
            lambda: core.make_patch(ctx, self.overlay, msg, name="0001-nothing.patch"),
            "holds no files")
        core.overlay_files(ctx, self.overlay, [self.lay.hooks])               # an unchanged copy
        self.assertRefusedUntouched(
            lambda: core.make_patch(ctx, self.overlay, msg, name="0001-nothing.patch"),
            "changes nothing")
        self.edit(self.lay.hooks, NEGATIVE, b"upstream: changed")              # control
        core.make_patch(ctx, self.overlay, msg, name="0001-nothing.patch")
        self.assertEqual(len(self.series()), 1)

    def test_plugin_facing_and_out_of_scope_paths_are_refused(self):
        ctx = self.materialised()
        msg = self.write_message(message("abi", "none"))
        for rel, needle in ((self.lay.plugin_facing, "plugin-facing"),
                            (self.lay.outside, "outside")):
            with self.subTest(path=rel):
                self.assertRefusedUntouched(
                    lambda: core.overlay_files(ctx, self.overlay, [rel]), needle)
                self.create(rel, b"// changed\n")
                self.assertRefusedUntouched(
                    lambda: core.make_patch(ctx, self.overlay, msg, name="0001-abi.patch"),
                    needle, rel)
                shutil.rmtree(self.overlay)
        for bad in ("../escape.cpp", "/abs.cpp", f"{self.lay.project}/../x"):
            with self.subTest(path=bad):
                self.assertRefusedUntouched(
                    lambda: core.overlay_files(ctx, self.overlay, [bad]), "plain upstream-relative")
        self.assertRefusedUntouched(
            lambda: core.overlay_files(ctx, self.overlay, [self.lay.project[:-1]]), "not a file")
        # Control: a file under the product's directory, not plugin-facing.
        core.overlay_files(ctx, self.overlay, [self.lay.hooks.replace("/", "\\")])
        self.edit(self.lay.hooks, NEGATIVE, b"upstream: changed")
        core.make_patch(ctx, self.overlay, msg, name="0001-abi.patch")
        self.assertEqual(len(self.series()), 1)

    def test_cr_bytes_and_an_existing_copy_are_refused(self):
        ctx = self.materialised()
        core.overlay_files(ctx, self.overlay, [self.lay.hooks])
        self.assertRefusedUntouched(
            lambda: core.overlay_files(ctx, self.overlay, [self.lay.hooks]), "--replace")
        path = self.overlay / self.lay.hooks
        crlf = path.read_bytes().replace(NEGATIVE, b"upstream: changed").replace(b"\n", b"\r\n")
        path.write_bytes(crlf)
        msg = self.write_message(message("crlf", "none"))
        self.assertRefusedUntouched(
            lambda: core.make_patch(ctx, self.overlay, msg, name="0001-crlf.patch"),
            "CR bytes", self.lay.hooks)
        path.write_bytes(crlf.replace(b"\r\n", b"\n"))                        # control
        core.make_patch(ctx, self.overlay, msg, name="0001-crlf.patch")
        self.assertEqual(len(self.series()), 1)

    def test_authoring_needs_a_materialised_upstream(self):
        ctx = self.ctx()
        self.assertRefusedUntouched(
            lambda: core.overlay_files(ctx, self.overlay, [self.lay.hooks]), "materialise")
        self.assertFalse(self.overlay.exists())

    def test_the_command_line_exit_codes_and_prefix(self):
        work = short_work_dir(self)
        entry = aurie.main if self.PRODUCT is core.AURIE else core.main
        prefix = Path(self.PRODUCT.tool).stem + ": REFUSED"

        def run(*argv):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = entry(list(argv) + ["--work-dir", str(work), "--pin-dir", str(self.pin_dir)],
                             runner=Recorder(), environ=self.upstream.env)
            return code, out.getvalue(), err.getvalue()

        self.assertEqual(run("materialise", "--upstream", str(self.upstream.repo))[0], 0)
        code, _, err = run("overlay", "--overlay", str(self.overlay), self.lay.plugin_facing)
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith(prefix), err)
        code, out, err = run("overlay", "--overlay", str(self.overlay), self.lay.hooks)
        self.assertEqual((code, err), (0, ""))
        msg = self.write_message(message("cli", "none"))
        code, _, err = run("make-patch", "--overlay", str(self.overlay), "--message", str(msg),
                           "--name", "0001-cli.patch")
        self.assertEqual(code, 2)
        self.assertIn("changes nothing", err)
        self.edit(self.lay.hooks, NEGATIVE, b"upstream: changed")
        code, out, err = run("make-patch", "--overlay", str(self.overlay), "--message", str(msg),
                             "--name", "0001-cli.patch")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("make-patch: wrote", out)


def short_work_dir(case) -> Path:
    """The command line enforces the real 40-character limit."""
    for _ in range(20):
        candidate = Path(tempfile.gettempdir()) / ("au" + secrets.token_hex(2)[:3])
        if len(str(candidate)) > core.MAX_WORK_DIR_LEN:
            case.skipTest("the system temp directory is too long for the command line's "
                          f"{core.MAX_WORK_DIR_LEN}-character --work-dir limit")
        if not candidate.exists():
            case.addCleanup(scrub, candidate)
            return candidate
    case.skipTest("no free short directory name in the system temp directory")


class TestAuthoringAurie(AuthoringCases, Rig):
    PRODUCT = core.AURIE


class TestAuthoringYYToolkit(AuthoringCases, Rig):
    PRODUCT = core.YYTOOLKIT


# --------------------------------------------------------------------------
# the Aurie profile end to end
# --------------------------------------------------------------------------

class TestProfiles(unittest.TestCase):
    def test_the_aurie_profile_holds_the_planned_values(self):
        a = core.AURIE
        self.assertEqual(a.pin_dir, ROOT / "third_party" / "aurie")
        self.assertEqual(a.project, ("Aurie", "AurieCore.vcxproj"))
        self.assertEqual((a.dll_name, a.build_info_name, a.tool),
                         ("AurieCore.dll", "AurieCore-BUILD-INFO.json", "tools/build_aurie.py"))
        self.assertEqual(a.host_tests, ("Aurie", "hs-tests"))
        self.assertEqual((a.zip_stem, a.zip_prefix), ("aurie-source", "third_party/aurie/"))
        self.assertEqual(a.work_leaf, "au")
        self.assertNotEqual(a.work_marker, core.YYTOOLKIT.work_marker)
        self.assertEqual(a.source_root, "Aurie/")
        self.assertIn("Aurie/source/framework/shared.hpp", a.plugin_facing)
        self.assertIs(aurie.PRODUCT, a)
        self.assertEqual(aurie.Context(pin_dir=ROOT).product, a)
        self.assertEqual(aurie.Context().pin_dir, a.pin_dir)

    def test_the_yytoolkit_profile_is_still_the_default_and_unchanged(self):
        y = core.YYTOOLKIT
        self.assertEqual((y.dll_name, y.build_info_name, y.tool, y.work_leaf, y.zip_stem),
                         ("YYToolkit.dll", "YYToolkit-BUILD-INFO.json", "tools/build_yytoolkit.py",
                          "yk", "yytoolkit-source"))
        self.assertEqual(core.Context().product, y)
        self.assertEqual(core.Context().pin_dir, ROOT / "third_party" / "yytoolkit")
        self.assertEqual(core.DEFAULT_PIN_DIR, y.pin_dir)

    def test_only_aurie_injects_d1trimfile(self):
        yy, au = core.repro_props(core.YYTOOLKIT), core.repro_props(core.AURIE)
        self.assertNotIn("d1trimfile", yy)
        self.assertIn('/Brepro /d1trimfile:"$(ProjectDir)\\"</AdditionalOptions>', au)
        self.assertIn('"YYToolkit.pdb"', yy)
        self.assertIn('"AurieCore.pdb"', au)
        self.assertIn("Written by tools/build_aurie.py", au)
        self.assertIn("Upstream's AurieCore.vcxproj is", au)
        self.assertEqual(core.configuration(core.YYTOOLKIT),
                         "Release|x64 + repro.props (/Brepro, /PDBALTPATH:%_PDB%)")
        self.assertIn("/d1trimfile", core.configuration(core.AURIE))

    def test_default_work_dir_is_au(self):
        if os.name == "nt":
            self.assertEqual(aurie.default_work_dir({"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}),
                             Path(r"C:\Users\x\AppData\Local\hstk\au"))
            deep = "C:\\Users\\" + "n" * 30 + "\\AppData\\Local"
            self.assertEqual(aurie.default_work_dir({"LOCALAPPDATA": deep, "SystemDrive": "D:"}),
                             Path("D:\\hstk\\au"))
        else:
            self.assertEqual(aurie.default_work_dir({"XDG_CACHE_HOME": "/c"}), Path("/c/hstk/au"))

    def test_the_entry_point_holds_no_commit_id_and_runs_as_a_script(self):
        source = AURIE_PATH.read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"\b[0-9a-f]{7,}\b", source), [])
        with tempfile.TemporaryDirectory(prefix="hstk au ") as base:
            missing = Path(base) / "no pin here"
            result = subprocess.run(
                [sys.executable, str(AURIE_PATH), "apply", "--pin-dir", str(missing),
                 "--work-dir", str(Path(base) / "w")],
                capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertTrue(result.stderr.startswith("build_aurie: REFUSED"), result.stderr)
            self.assertFalse((Path(base) / "w").exists())
        help_text = subprocess.run([sys.executable, str(AURIE_PATH), "--help"],
                                   capture_output=True, text=True, check=True).stdout
        self.assertIn("AurieCore.dll", help_text)
        self.assertIn("make-patch", help_text)


class TestAurieBuild(Rig):
    PRODUCT = core.AURIE

    def setUp(self):
        super().setUp()
        ctx = self.materialised()
        self.first_patch(ctx)
        self.second_patch(ctx)
        self.lines.clear()

    def test_every_step_names_aurie_and_writes_aurie_outputs(self):
        tools = FakeTools(core.AURIE)
        ctx = self.ctx(tools)
        core.materialise(ctx, self.upstream.repo)
        self.assertIn("created by tools/build_aurie.py",
                      (self.work / ".hstk-aurie-work").read_text())
        core.apply_series(ctx)
        record = core.build(ctx, toolchain=FAKE_TOOLCHAIN)
        tests = core.hosttests(ctx, toolchain=FAKE_TOOLCHAIN)
        info = core.verify_dll(ctx)

        builds = [c for c in self.recorder.named("msbuild.exe") if "-version" not in c.argv]
        self.assertEqual(len(builds), 1)
        argv = builds[0].argv
        self.assertEqual(argv[1], str(self.work / "src" / "Aurie" / "AurieCore.vcxproj"))
        props = dict(a[3:].split("=", 1) for a in argv if a.startswith("/p:"))
        self.assertEqual(props["ForceImportAfterCppTargets"], str(self.work / "repro.props"))
        injected = (self.work / "repro.props").read_text()
        self.assertEqual(injected, core.repro_props(core.AURIE))
        self.assertIn("/d1trimfile", injected)
        self.assertEqual(record["toolchain"]["build_state"], BUILD_STATE)
        self.assertEqual(record["configuration"], core.configuration(core.AURIE))
        for call in self.recorder.calls:
            self.assertEqual([k for k in call.env if k.upper() in core.STRIPPED_ENV], [])

        self.assertEqual((tests["ran"], tests["passed"], tests["files"]), (1, 1, ["test_filter.cpp"]))
        out = self.work / "o"
        self.assertEqual(json.loads((out / "AurieCore-BUILD-INFO.json").read_text()), info)
        self.assertEqual(info["tool"], "tools/build_aurie.py")
        self.assertEqual(info["dll"]["name"], "AurieCore.dll")
        self.assertEqual(info["dll"]["sha256"], hashlib.sha256(GOOD_DLL).hexdigest())
        self.assertEqual({m["patch"] for m in info["markers_verified"]},
                         {"0001-first.patch", "0002-second.patch"})
        self.assertEqual(info["host_tests"]["ran"], 1)
        self.assertIs(info["live_gameplay_verified"], False)
        self.assertEqual((out / "AurieCore.dll.sha256").read_text(),
                         f"{info['dll']['sha256']}  AurieCore.dll\n")
        archive = out / info["source"]["name"]
        self.assertRegex(archive.name, r"^aurie-source-[0-9a-f]{12}\.zip$")
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.namelist()
        self.assertIn("third_party/aurie/patches/0002-second.patch", entries)
        self.assertTrue(all(e.startswith("third_party/aurie/") for e in entries), entries)
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         sorted(["AurieCore.dll", "AurieCore-BUILD-INFO.json",
                                 "AurieCore.dll.sha256", archive.name]))

    def test_negative_control_a_missing_marker_fails_and_leaves_no_build_info(self):
        ctx = self.ctx(FakeTools(core.AURIE, dll=GOOD_DLL.replace(MARKER_TWO.encode(), b"x")))
        core.materialise(ctx, self.upstream.repo)
        core.apply_series(ctx)
        core.build(ctx, toolchain=FAKE_TOOLCHAIN)
        with self.assertRaises(core.Failed) as failure:
            core.verify_dll(ctx)
        self.assertIn(MARKER_TWO, str(failure.exception))
        self.assertIn("0002-second.patch", str(failure.exception))
        self.assertFalse((self.work / "o" / "AurieCore-BUILD-INFO.json").exists())

    def test_all_through_the_command_line(self):
        work = short_work_dir(self)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = aurie.main(["all", "--upstream", str(self.upstream.repo), "--work-dir", str(work),
                               "--pin-dir", str(self.pin_dir)],
                              runner=Recorder(FakeTools(core.AURIE)), environ=self.upstream.env,
                              toolchain=FAKE_TOOLCHAIN)
        self.assertEqual((code, err.getvalue()), (0, ""))
        info = json.loads((work / "o" / "AurieCore-BUILD-INFO.json").read_text())
        self.assertEqual(info["tool"], "tools/build_aurie.py")
        self.assertFalse((work / "o" / "YYToolkit-BUILD-INFO.json").exists())

    def test_refusals_exit_2_with_the_aurie_prefix(self):
        inside = ROOT / "build" / "au-test"
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = aurie.main(["materialise", "--upstream", str(self.upstream.repo),
                               "--work-dir", str(inside), "--pin-dir", str(self.pin_dir)],
                              runner=Recorder(passthrough=False), environ=self.upstream.env)
        self.assertEqual(code, 2)
        self.assertTrue(err.getvalue().startswith("build_aurie: REFUSED"), err.getvalue())
        # Over the limit before it is inside the repository; either refuses.
        self.assertTrue("hstk\\au" in err.getvalue()
                        or "inside the repository" in err.getvalue(), err.getvalue())
        self.assertFalse(inside.exists())


# --------------------------------------------------------------------------
# the real toolchain: /d1trimfile, with and without
# --------------------------------------------------------------------------

def real_toolchain():
    if os.name != "nt":
        return None, "MSBuild, vcvars64.bat and cl are Windows-only"
    if GIT is None:
        return None, "git is not on PATH"
    try:
        found = core.locate_toolchain(core.Context(product=core.AURIE))
    except core.ToolError as error:
        return None, f"no VS 2022 C++ build tools: {error}"
    if not found.vcvars64:
        return None, "vcvars64.bat not found in the Visual Studio install"
    return found, ""


class TestRealToolchainTrim(Rig):
    """A source returning `__FILE__` puts the path it was compiled from into the
    DLL. The Aurie profile's `/d1trimfile` must keep the work directory out;
    the same build without it is the negative control that shows the check can
    see the path at all."""

    PRODUCT = core.AURIE

    @classmethod
    def setUpClass(cls):
        cls.toolchain, reason = real_toolchain()
        if cls.toolchain is None:
            raise unittest.SkipTest(reason)
        super().setUpClass()

    def build_with(self, product):
        def quietly(argv, **options):
            return core.run_process(argv, **dict(options, capture=True))

        ctx = core.Context(pin_dir=self.pin_dir, work_dir=self.work, environ=self.upstream.env,
                           runner=quietly, max_work_dir_len=ROOMY, log=self.lines.append,
                           product=product)
        core.materialise(ctx, self.upstream.repo)
        core.apply_series(ctx)
        core.build(ctx, toolchain=self.toolchain)
        tests = core.hosttests(ctx, toolchain=self.toolchain)
        info = core.verify_dll(ctx)
        return (self.work / "o" / product.dll_name).read_bytes(), tests, info

    def test_the_work_directory_stays_out_of_the_dll(self):
        ctx = self.materialised()
        self.first_patch(ctx)
        self.second_patch(ctx)
        source_dir = str(self.work / "src" / "Aurie").lower().encode()

        untrimmed, _, _ = self.build_with(dataclasses.replace(core.AURIE, trim_project_dir=False))
        self.assertIn(source_dir, untrimmed.lower(), "control: __FILE__ should carry the path")

        dll, tests, info = self.build_with(core.AURIE)
        self.assertEqual(dll[:2], b"MZ")
        self.assertIn(MARKER_ONE.encode(), dll)
        self.assertIn(b"Module Internals", dll)          # __FILE__ is there, trimmed
        self.assertNotIn(str(self.work).lower().encode(), dll.lower())
        self.assertNotIn(str(self.base).lower().encode(), dll.lower())
        self.assertIn(b"AurieCore.pdb", dll)
        self.assertEqual((tests["ran"], tests["passed"]), (1, 1))
        self.assertIs(info["live_gameplay_verified"], False)


if __name__ == "__main__":
    unittest.main()
