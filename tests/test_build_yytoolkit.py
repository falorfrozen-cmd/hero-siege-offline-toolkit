"""Exercise tools/build_yytoolkit.py offline, against a synthetic mini-upstream.

Nothing here needs the real YYToolkit, the network or the game. A throwaway git
repository stands in for upstream; it lives in the SYSTEM temp directory, not
the session scratchpad (`git init` there fails with `Filename too long`, see
tests/test_claude_hooks.py), under a directory whose name contains a space, and
it carries a source path with a space in it -- upstream has `Module Internals/`
and a patch header for such a path ends in a TAB that is easy to destroy.

After the pinned commit the fixture makes two more commits and then dirties its
checkout, so every test runs against an upstream whose HEAD is NOT the pin and
whose working tree is NOT clean. That is the point: the tool exports the commit
object, so neither may matter. Each test also re-hashes the whole fixture
afterwards, `.git` included, to prove `--upstream` was only ever read.

MSBuild, cl and the compiled host tests are stubbed through the tool's injected
runner, which is also how the environment it hands to child processes is
inspected. The checks come in pairs where a one-sided test would pass against a
tool that does nothing: the log-marker check has a positive control (markers
present, BUILD-INFO written) and a negative one (marker missing, the marker and
its patch named, no BUILD-INFO left behind).

One class at the end runs the real thing -- MSBuild, vcvars64, cl -- against
the same synthetic project. It is skipped, with the reason, anywhere but a
Windows machine with the VS 2022 C++ build tools; the hub's CI is ubuntu.
"""

import contextlib
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
TOOL_PATH = ROOT / "tools" / "build_yytoolkit.py"
spec = importlib.util.spec_from_file_location("build_yytoolkit", TOOL_PATH)
tool = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tool   # @dataclass resolves annotations through sys.modules
spec.loader.exec_module(tool)

GIT = shutil.which("git")

MARKER_ONE = "hs-patch-one: rejected candidate"
MARKER_TWO = "hs-patch-two: accepted, with a comma"
SPACED = "YYToolkit/source/Module Internals/Hooks.cpp"
FILTER = "YYToolkit/source/Module Internals/filter.hpp"
FIRST, SECOND = "0001-first.patch", "0002-second.patch"

# The system temp directory is itself longer than the tool's limit on Windows,
# so the functional tests lift it through the API. The limit itself is tested
# with the default, and the command line cannot change it.
ROOMY = 250

VCXPROJ = b"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
  <PropertyGroup Label="Globals">
    <VCProjectVersion>17.0</VCProjectVersion>
    <RootNamespace>YYToolkit</RootNamespace>
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
"""

HOOKS_BASE = b"""#include "filter.hpp"

extern "C" __declspec(dllexport) const char* hs_describe(int value)
{
\tif (hs_filter(value) < 0)
\t\treturn "upstream: negative";
\treturn "upstream: all good";
}
"""
FILTER_BASE = b"#pragma once\ninline int hs_filter(int value) { return value; }\n"
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


def clean_git_env(config: Path) -> dict:
    """The caller's environment, minus everything that would make git behave
    differently here than on a CI runner."""
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX")}
    config.write_text("", encoding="utf-8")
    env["GIT_CONFIG_GLOBAL"] = str(config)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


class Upstream:
    """pin commit -> commit "one" -> commit "two" -> a dirty checkout."""

    def __init__(self, base: Path):
        self.base = base
        self.repo = base / "up stream"
        self.env = clean_git_env(base / "gitconfig")
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "false")
        self.base_files = {
            "README.md": b"mini upstream\n",
            "YYToolkit/YYToolkit.vcxproj": VCXPROJ,
            SPACED: HOOKS_BASE,
            FILTER: FILTER_BASE,
        }
        self.write(self.base_files)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "pinned")
        self.commit = self.git("rev-parse", "HEAD").decode().strip()
        self.tree = self.git("rev-parse", "HEAD^{tree}").decode().strip()

        self.write({
            SPACED: HOOKS_BASE.replace(b"upstream: negative", MARKER_ONE.encode()),
            FILTER: FILTER_BASE.replace(b"return value;", b"return value > 100 ? -1 : value;"),
        })
        self.patch_one = self.header("first change", f'"{MARKER_ONE}"') + self.staged_diff()
        self.git("commit", "-q", "-m", "one")

        # Touches the line next to the one "one" changed, so its context carries
        # patch one's text: it applies after 0001 and not before it.
        final_hooks = (HOOKS_BASE.replace(b"upstream: negative", MARKER_ONE.encode())
                       .replace(b"upstream: all good", MARKER_TWO.encode()))
        self.write({
            SPACED: final_hooks,
            "YYToolkit/hs-tests/test_alpha.cpp": b"int main() { return 0; }\n",
            "YYToolkit/hs-tests/test_filter.cpp": HOST_TEST,
        })
        self.patch_two = self.header("second change", f'"{MARKER_TWO}"') + self.staged_diff()
        self.git("commit", "-q", "-m", "two")
        self.final_hooks = final_hooks

        # Another HEAD, a modified tracked file, stale build output.
        (self.repo / "README.md").write_bytes(b"a local edit nobody committed\n")
        (self.repo / "YYToolkit" / "stale.obj").write_bytes(b"stale build output")
        self.snapshot = self.hash_everything()

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ["git", "-c", "user.name=hstk", "-c", "user.email=hstk@example.invalid",
             "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
            cwd=self.repo, env=self.env, check=True, capture_output=True,
        ).stdout

    def write(self, files: dict) -> None:
        for rel, data in files.items():
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def staged_diff(self) -> bytes:
        self.git("add", "-A")
        return self.git("diff", "--cached", "--no-color", "--no-ext-diff")

    @staticmethod
    def header(subject: str, markers: str) -> bytes:
        return (
            "From: Hub Tests <hstk@example.invalid>\n"
            "Date: Sat, 19 Sep 2026 10:00:00 +0000\n"
            f"Subject: [PATCH] {subject}\n\n"
            "Why: a unit test needs a patch.\n"
            f"Log-markers: {markers}\n"
            "---\n"
        ).encode()

    def hash_everything(self) -> dict:
        return {p.relative_to(self.repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.repo.rglob("*")) if p.is_file()}


class Call:
    def __init__(self, argv, cwd, env):
        self.argv, self.cwd, self.env = list(argv), cwd, dict(env or {})

    @property
    def git_subcommand(self):
        if os.path.basename(self.argv[0]).lower() not in ("git", "git.exe"):
            return None
        rest = self.argv[1:]
        while rest and rest[0] in ("-c", "-C"):
            rest = rest[2:]
        return rest[0] if rest else None


class Recorder:
    """The injected runner: records every call, lets a stub answer it, and
    otherwise runs it for real (that is git, in these tests)."""

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
        return tool.run_process(argv, cwd=cwd, env=env, timeout=timeout, capture=capture)

    def named(self, exe: str):
        return [c for c in self.calls if os.path.basename(c.argv[0]).lower() == exe]


def scrub(path):
    """Best-effort: a lingering mspdbsrv.exe can hold a build directory open."""
    try:
        tool.remove_tree(path)
    except OSError:
        pass


def done(call, code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(call.argv, code, stdout, stderr)


FAKE_TOOLCHAIN = tool.Toolchain("MSBuild.exe", "C:\\VS\\VC\\Auxiliary\\Build\\vcvars64.bat", "17.14.1")
GOOD_DLL = b"MZ\x90\x00" + b"\x00" * 64 + MARKER_ONE.encode() + b"\x00" + MARKER_TWO.encode() + b"\x00PE"
CL_BANNER = "Microsoft (R) C/C++ Optimizing Compiler Version 19.44.35229 for x64"
BUILD_STATE = "PlatformToolSet=v143:VCToolArchitecture=Native64Bit:VCToolsVersion=14.44.35207:"


class FakeTools:
    """Stands in for MSBuild, for cmd.exe running vcvars64 + cl, and for the
    host-test executables cl would have produced."""

    def __init__(self, dll=GOOD_DLL, msbuild_code=0, compile_code=0, test_codes=None):
        self.dll, self.msbuild_code, self.compile_code = dll, msbuild_code, compile_code
        self.test_codes = test_codes or {}
        self.scripts = []

    def __call__(self, call):
        exe = os.path.basename(call.argv[0]).lower()
        if exe == "msbuild.exe":
            if "-version" in call.argv:
                return done(call, stdout="17.14.60.43110\n")
            props = dict(a[3:].split("=", 1) for a in call.argv if a.startswith("/p:"))
            if self.msbuild_code == 0 and self.dll is not None:
                Path(props["OutDir"]).mkdir(parents=True, exist_ok=True)
                (Path(props["OutDir"]) / "YYToolkit.dll").write_bytes(self.dll)
                tlog = Path(props["IntDir"]) / "YYToolkit.tlog"
                tlog.mkdir(parents=True, exist_ok=True)
                (tlog / "YYToolkit.lastbuildstate").write_text(BUILD_STATE + "\nRelease|x64|\n")
            return done(call, self.msbuild_code)
        if exe == "cmd.exe":
            script = Path(call.argv[-1])
            self.scripts.append((script.name, script.read_text()))
            if script.name == "clver.bat":
                return done(call, stdout=CL_BANNER + "\nusage: cl [ option... ]\n")
            if self.compile_code == 0:
                script.with_suffix(".exe").write_bytes(b"MZ")
            return done(call, self.compile_code, stdout="fake cl output")
        if exe.endswith(".exe") and Path(call.argv[0]).parent.name == "t":
            return done(call, self.test_codes.get(exe, 0), stdout="fake test output")
        return None


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and not rel.startswith(".git/"):
            digest.update(rel.encode() + b"\x00" + path.read_bytes() + b"\x00")
    return digest.hexdigest()


@unittest.skipIf(GIT is None, "git is not on PATH; the tool drives git for every step")
class Rig(unittest.TestCase):
    """One upstream per class (it is read-only, and every test proves that);
    one hub pin directory and one work directory per test."""

    @classmethod
    def setUpClass(cls):
        cls.class_base = Path(tempfile.mkdtemp(prefix="hstk yk "))
        cls.addClassCleanup(scrub, cls.class_base)
        cls.upstream = Upstream(cls.class_base)

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="hstk yk "))
        self.addCleanup(scrub, self.base)
        self.addCleanup(self.assert_upstream_untouched)
        self.hub = self.base / "hub"
        self.pin_dir = self.hub / "third_party" / "yytoolkit"
        (self.pin_dir / "patches").mkdir(parents=True)
        self.work = self.base / "w"
        self.write_pin()
        (self.pin_dir / "README.md").write_bytes(b"# the guide\n")
        (self.pin_dir / "NOTICE.md").write_bytes(b"AGPL-3.0 modification notice\n")
        self.write_patch(FIRST, self.upstream.patch_one)
        self.write_patch(SECOND, self.upstream.patch_two)
        self.write_series(FIRST, SECOND)
        self.lines = []
        self.recorder = Recorder()

    def assert_upstream_untouched(self):
        self.assertEqual(self.upstream.hash_everything(), self.upstream.snapshot,
                         "--upstream was written to")

    def write_pin(self, **changes):
        pin = {"repo": "https://github.com/AurieFramework/YYToolkit", "tag": "v4.0.1",
               "commit": self.upstream.commit, "tree": self.upstream.tree}
        pin.update(changes)
        (self.pin_dir / "upstream.json").write_text(json.dumps(pin, indent=2) + "\n")

    def write_patch(self, name: str, data: bytes):
        (self.pin_dir / "patches" / name).write_bytes(data)

    def write_series(self, *names: str):
        (self.pin_dir / "patches" / "series").write_bytes(
            ("# application order\n" + "\n".join(names) + "\n").encode())

    def ctx(self, *stubs, work=None, environ=None, limit=ROOMY, passthrough=True):
        self.recorder = Recorder(*stubs, passthrough=passthrough)
        return tool.Context(pin_dir=self.pin_dir, work_dir=work or self.work,
                            runner=self.recorder, environ=environ or self.upstream.env,
                            max_work_dir_len=limit, log=self.lines.append)

    def materialised(self, *stubs):
        ctx = self.ctx(*stubs)
        tool.materialise(ctx, self.upstream.repo)
        return ctx

    def applied(self, *stubs):
        ctx = self.materialised(*stubs)
        tool.apply_series(ctx)
        return ctx

    def built(self, tools=None):
        tools = tools or FakeTools()
        ctx = self.applied(tools)
        tool.build(ctx, toolchain=FAKE_TOOLCHAIN)
        return ctx, tools

    def upstream_blob(self, rev: str, rel: str) -> bytes:
        return self.upstream.git("show", f"{rev}:{rel}")


class TestPin(Rig):
    def test_an_abbreviated_or_missing_id_is_not_a_pin(self):
        for changes in ({"commit": self.upstream.commit[:12]}, {"tree": ""},
                        {"tree": self.upstream.tree.upper()}, {"commit": 5}):
            with self.subTest(changes=changes):
                self.write_pin(**changes)
                with self.assertRaises(tool.Refused):
                    tool.load_pin(self.pin_dir)
        (self.pin_dir / "upstream.json").write_text("{ not json")
        with self.assertRaises(tool.Refused):
            tool.load_pin(self.pin_dir)

    def test_the_tool_itself_holds_no_commit_id(self):
        # upstream.json is the only place the pin lives. Anything that looks
        # like an abbreviated or full object id in the tool is a second copy.
        source = TOOL_PATH.read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"\b[0-9a-f]{7,}\b", source), [])
        self.assertNotIn(self.upstream.commit, source)


class TestWorkDir(Rig):
    def test_inside_the_repository_is_refused_and_not_created(self):
        for inside in (ROOT / "build" / "yk-test", self.hub / "yk"):
            with self.subTest(inside=inside):
                with self.assertRaises(tool.Refused) as refusal:
                    tool.materialise(self.ctx(work=inside), self.upstream.repo)
                self.assertIn("inside the repository", str(refusal.exception))
                self.assertFalse(inside.exists())
                self.assertEqual(self.recorder.calls, [])

    def test_over_long_is_refused_with_the_default_limit_and_not_created(self):
        long_dir = Path(tempfile.gettempdir()) / ("x" * (tool.MAX_WORK_DIR_LEN + 1))
        ctx = self.ctx(work=long_dir, limit=tool.MAX_WORK_DIR_LEN)
        with self.assertRaises(tool.Refused) as refusal:
            tool.materialise(ctx, self.upstream.repo)
        self.assertIn("characters", str(refusal.exception))
        self.assertFalse(long_dir.exists())
        self.assertEqual(self.recorder.calls, [])
        self.assertEqual(tool.Context(pin_dir=self.pin_dir).max_work_dir_len, 40)

    def test_a_path_of_exactly_the_limit_passes(self):
        room = tool.MAX_WORK_DIR_LEN - len(tempfile.gettempdir()) - 1
        if room < 1:
            self.skipTest("the system temp directory alone exceeds the work-dir limit")
        exact = Path(tempfile.gettempdir()) / ("k" * room)
        self.assertEqual(len(str(exact)), tool.MAX_WORK_DIR_LEN)
        self.ctx(work=exact, limit=tool.MAX_WORK_DIR_LEN).check_work_dir()
        self.assertFalse(exact.exists())

    def test_a_directory_this_tool_did_not_create_is_refused(self):
        self.work.mkdir()
        (self.work / "src").mkdir()
        (self.work / "src" / "thesis.txt").write_text("someone's only copy")
        with self.assertRaises(tool.Refused):
            tool.materialise(self.ctx(), self.upstream.repo)
        self.assertTrue((self.work / "src" / "thesis.txt").exists())

    def test_work_dir_and_upstream_may_not_contain_one_another(self):
        with self.assertRaises(tool.Refused):
            tool.materialise(self.ctx(work=self.upstream.repo / "w"), self.upstream.repo)
        self.assertFalse((self.upstream.repo / "w").exists())

    def test_the_default_is_short_and_falls_back_to_a_drive_root(self):
        if os.name == "nt":
            self.assertEqual(tool.default_work_dir({"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}),
                             Path(r"C:\Users\x\AppData\Local\hstk\yk"))
            deep = "C:\\Users\\" + "n" * 30 + "\\AppData\\Local"
            self.assertEqual(tool.default_work_dir({"LOCALAPPDATA": deep, "SystemDrive": "D:"}),
                             Path("D:\\hstk\\yk"))
        else:
            self.assertEqual(tool.default_work_dir({"XDG_CACHE_HOME": "/c"}), Path("/c/hstk/yk"))


class TestMaterialise(Rig):
    def test_wrong_tree_id_is_refused_and_nothing_is_exported(self):
        self.write_pin(tree="0" * 40)
        with self.assertRaises(tool.Refused) as refusal:
            tool.materialise(self.ctx(), self.upstream.repo)
        self.assertIn(self.upstream.tree, str(refusal.exception))
        self.assertFalse(self.work.exists())
        self.assertNotIn("archive", [c.git_subcommand for c in self.recorder.calls])

    def test_a_commit_the_clone_does_not_have_is_refused(self):
        self.write_pin(commit="1" * 40)
        with self.assertRaises(tool.Refused) as refusal:
            tool.materialise(self.ctx(), self.upstream.repo)
        self.assertIn("does not contain", str(refusal.exception))
        self.assertFalse(self.work.exists())

    def test_exports_the_commit_object_not_the_dirty_checkout_at_another_head(self):
        head = self.upstream.git("rev-parse", "HEAD").decode().strip()
        self.assertNotEqual(head, self.upstream.commit)     # the fixture really is elsewhere
        ctx = self.materialised()
        up = ctx.path("up")
        for rel, data in self.upstream.base_files.items():
            self.assertEqual((up / rel).read_bytes(), data, rel)
        self.assertEqual((up / SPACED).read_bytes(), HOOKS_BASE)
        self.assertNotIn(b"\r", (up / SPACED).read_bytes())
        self.assertFalse((up / "YYToolkit" / "stale.obj").exists())
        self.assertFalse((up / "YYToolkit" / "hs-tests").exists())
        record = json.loads(ctx.path("materialised.json").read_text())
        self.assertEqual((record["commit"], record["tree"]),
                         (self.upstream.commit, self.upstream.tree))
        self.assertEqual(sorted(record["files"]), sorted(self.upstream.base_files))

    def test_every_git_call_is_offline_read_only_and_line_ending_safe(self):
        self.materialised()
        commands = [c.git_subcommand for c in self.recorder.calls]
        self.assertIn("archive", commands)
        self.assertEqual(set(commands) & {"fetch", "clone", "pull", "push", "remote",
                                          "ls-remote", "submodule", "checkout", "reset"}, set())
        for call in self.recorder.calls:
            self.assertEqual(call.env.get("GIT_NO_LAZY_FETCH"), "1")
            self.assertIn("core.autocrlf=false", call.argv)
            self.assertIn("core.longpaths=true", call.argv)

    def test_an_export_that_does_not_match_the_blobs_is_caught(self):
        up = self.materialised().path("up")
        (up / FILTER).write_bytes(b"tampered\n")
        with self.assertRaises(tool.Failed) as failure:
            tool.verify_tree(up, json.loads((self.work / "materialised.json").read_text())["files"], "x")
        self.assertIn(FILTER, str(failure.exception))
        (up / "extra.txt").write_text("not upstream's")
        (up / FILTER).write_bytes(FILTER_BASE)
        with self.assertRaises(tool.Failed) as failure:
            tool.verify_tree(up, json.loads((self.work / "materialised.json").read_text())["files"], "x")
        self.assertIn("extra.txt", str(failure.exception))


class TestNetwork(Rig):
    def test_no_upstream_and_no_permission_means_no_process_at_all(self):
        ctx = self.ctx(passthrough=False)
        with self.assertRaises(tool.Refused) as refusal:
            tool.materialise(ctx, None)
        self.assertIn("--allow-network", str(refusal.exception))
        self.assertEqual(self.recorder.calls, [])
        self.assertFalse(self.work.exists())

    def test_with_permission_it_fetches_exactly_the_pinned_commit(self):
        def no_network(call):
            if call.git_subcommand == "fetch":
                return done(call, 128, stderr="fatal: the tests have no network")
            return None

        with self.assertRaises(tool.Failed):
            tool.materialise(self.ctx(no_network), None, allow_network=True)
        fetches = [c for c in self.recorder.calls if c.git_subcommand == "fetch"]
        self.assertEqual(len(fetches), 1)
        self.assertEqual(fetches[0].argv[-2:],
                         ["https://github.com/AurieFramework/YYToolkit", self.upstream.commit])
        self.assertIn("--depth=1", fetches[0].argv)
        self.assertTrue(any("NETWORK" in line for line in self.lines))

    def test_only_an_https_repo_is_ever_fetched(self):
        self.write_pin(repo="--upload-pack=calc.exe")
        with self.assertRaises(tool.Refused):
            tool.materialise(self.ctx(passthrough=False), None, allow_network=True)
        self.assertEqual(self.recorder.calls, [])


class TestApply(Rig):
    def test_series_order_is_honoured(self):
        ctx = self.applied()
        src = ctx.path("src")
        self.assertEqual((src / SPACED).read_bytes(), self.upstream.final_hooks)
        self.assertEqual((src / FILTER).read_bytes(), self.upstream_blob("HEAD", FILTER))
        self.assertEqual((src / "YYToolkit/hs-tests/test_filter.cpp").read_bytes(), HOST_TEST)
        applies = [c.argv[-1] for c in self.recorder.calls
                   if c.git_subcommand == "apply" and "--check" not in c.argv]
        # scratch copy first, then the real tree: 0001, 0002, 0001, 0002
        self.assertEqual([os.path.basename(a) for a in applies], [FIRST, SECOND] * 2)
        record = json.loads(ctx.path("applied.json").read_text())
        self.assertEqual([p["name"] for p in record["patches"]], [FIRST, SECOND])
        self.assertFalse(ctx.path("chk").exists())
        # The pristine export is still pristine; only the copy was patched.
        self.assertEqual((ctx.path("up") / SPACED).read_bytes(), HOOKS_BASE)

    def test_the_wrong_order_fails_naming_the_patch_that_does_not_apply(self):
        ctx = self.materialised()
        self.write_series(SECOND, FIRST)
        with self.assertRaises(tool.Failed) as failure:
            tool.apply_series(ctx)
        self.assertIn(f"patch {SECOND} (1 of 2", str(failure.exception))
        self.assert_nothing_applied(ctx)

    def test_a_failing_patch_is_named_and_nothing_is_applied(self):
        ctx = self.materialised()
        broken = self.upstream.patch_two.replace(b'-\treturn "upstream: all good";',
                                                 b'-\treturn "upstream: all wrong";')
        self.assertNotEqual(broken, self.upstream.patch_two)
        self.write_patch("0002-broken.patch", broken)
        self.write_series(FIRST, "0002-broken.patch")
        with self.assertRaises(tool.Failed) as failure:
            tool.apply_series(ctx)
        message = str(failure.exception)
        self.assertIn("0002-broken.patch (2 of 2", message)
        self.assertIn("NOTHING was applied", message)
        self.assert_nothing_applied(ctx)
        # ...and a corrected series then applies cleanly in the same work dir.
        self.write_series(FIRST, SECOND)
        tool.apply_series(ctx)
        self.assertEqual((ctx.path("src") / SPACED).read_bytes(), self.upstream.final_hooks)

    def assert_nothing_applied(self, ctx):
        for name in ("src", "chk", "applied.json"):
            self.assertFalse(ctx.path(name).exists(), name)
        tool.verify_tree(ctx.path("up"),
                         json.loads(ctx.path("materialised.json").read_text())["files"], "up")
        for path in self.work.rglob("*"):
            if path.is_file() and path.parent.name != "p":
                self.assertNotIn(b"hs-patch-one", path.read_bytes(), path)

    def test_a_failure_discards_the_tree_an_earlier_series_produced(self):
        ctx = self.applied()
        self.write_series(SECOND, FIRST)
        with self.assertRaises(tool.Failed):
            tool.apply_series(ctx)
        self.assert_nothing_applied(ctx)

    def test_rerunning_is_idempotent(self):
        ctx = self.applied()
        first = tree_digest(ctx.path("src"))
        tool.apply_series(ctx)
        self.assertEqual(tree_digest(ctx.path("src")), first)
        tool.materialise(ctx, self.upstream.repo)
        self.assertFalse(ctx.path("src").exists())      # a new export invalidates it
        tool.apply_series(ctx)
        self.assertEqual(tree_digest(ctx.path("src")), first)

    def test_a_modified_export_is_not_patched(self):
        ctx = self.materialised()
        (ctx.path("up") / FILTER).write_bytes(b"edited after materialise\n")
        with self.assertRaises(tool.Failed) as failure:
            tool.apply_series(ctx)
        self.assertIn(FILTER, str(failure.exception))
        self.assertFalse(ctx.path("src").exists())

    def test_apply_needs_a_materialised_tree_for_this_pin(self):
        with self.assertRaises(tool.Refused):
            tool.apply_series(self.ctx())
        ctx = self.materialised()
        self.write_pin(tree="2" * 40)
        with self.assertRaises(tool.Refused):
            tool.apply_series(ctx)

    def test_series_and_patch_files_are_validated_before_use(self):
        ctx = self.materialised()
        cases = {
            "traversal": lambda: self.write_series("../0001-first.patch"),
            "missing": lambda: self.write_series(FIRST, "0009-absent.patch"),
            "twice": lambda: self.write_series(FIRST, FIRST),
            "empty": lambda: self.write_series(),
            "crlf patch": lambda: self.write_patch(
                FIRST, self.upstream.patch_one.replace(b"\n", b"\r\n")),
        }
        for name, arrange in cases.items():
            with self.subTest(case=name):
                self.write_patch(FIRST, self.upstream.patch_one)
                self.write_series(FIRST, SECOND)
                arrange()
                with self.assertRaises(tool.Refused):
                    tool.apply_series(ctx)
                self.assertFalse(ctx.path("src").exists())


class TestMarkerGrammar(unittest.TestCase):
    def parse(self, header: str):
        return tool.parse_markers("x.patch", (header + "---\ndiff --git a/f b/f\n").encode())

    def test_accepted_forms(self):
        self.assertEqual(self.parse("Log-markers: none\n"), ())
        self.assertEqual(self.parse("Log-markers: NONE\n"), ())
        self.assertEqual(
            self.parse('Log-markers: "first literal", "second, with a comma"\n'
                       'Log-markers: "a \\"quoted\\" third"\n'),
            ("first literal", "second, with a comma", 'a "quoted" third'))

    def test_refused_forms(self):
        for header in ("Subject: no marker line at all\n",
                       "Log-markers: bare words without quotes\n",
                       'Log-markers: "quoted literal" and trailing words\n',
                       'Log-markers: "short"\n',
                       "Log-markers:\n",
                       'Log-markers: "caf\u00e9 au lait log line"\n'):
            with self.subTest(header=header):
                with self.assertRaises(tool.Refused):
                    self.parse(header)

    def test_only_the_header_declares_markers(self):
        data = (b'Log-markers: none\n---\ndiff --git a/f b/f\n'
                b'Log-markers: "smuggled in below the header"\n')
        self.assertEqual(tool.parse_markers("x.patch", data), ())


class TestBuild(Rig):
    def test_msbuild_is_driven_with_a_clean_environment_and_short_directories(self):
        polluted = dict(self.upstream.env)
        polluted.update({"CL": "/DEVIL", "_CL_": "/DEVIL", "LINK": "/FORCE", "_LINK_": "/FORCE",
                         "_link_": "/FORCE"})
        tools = FakeTools()
        ctx = self.ctx(tools, environ=polluted)
        tool.materialise(ctx, self.upstream.repo)
        tool.apply_series(ctx)
        record = tool.build(ctx, toolchain=FAKE_TOOLCHAIN)

        self.assertTrue(self.recorder.calls)
        for call in self.recorder.calls:
            leaked = [k for k in call.env if k.upper() in ("CL", "_CL_", "LINK", "_LINK_")]
            self.assertEqual(leaked, [], call.argv)
        builds = [c for c in self.recorder.named("msbuild.exe") if "-version" not in c.argv]
        self.assertEqual(len(builds), 1)
        argv = builds[0].argv
        props = dict(a[3:].split("=", 1) for a in argv if a.startswith("/p:"))
        self.assertEqual(argv[1], str(self.work / "src" / "YYToolkit" / "YYToolkit.vcxproj"))
        self.assertEqual(props["Configuration"], "Release")
        self.assertEqual(props["Platform"], "x64")
        self.assertEqual(props["OutDir"], str(self.work / "o") + os.sep)
        self.assertEqual(props["IntDir"], str(self.work / "i") + os.sep)
        self.assertEqual(props["ForceImportAfterCppTargets"], str(self.work / "repro.props"))
        self.assertIn("/t:Rebuild", argv)

        injected = (self.work / "repro.props").read_text()
        self.assertEqual(injected.count("/Brepro"), 3)      # comment, ClCompile, Link
        self.assertIn("<AdditionalOptions>%(AdditionalOptions) /Brepro</AdditionalOptions>", injected)
        self.assertIn("/Brepro /PDBALTPATH:%25_PDB%25", injected)
        # Upstream's project file is what upstream committed: not edited.
        self.assertEqual((self.work / "src" / "YYToolkit" / "YYToolkit.vcxproj").read_bytes(), VCXPROJ)

        self.assertEqual(record["dll_sha256"], hashlib.sha256(GOOD_DLL).hexdigest())
        self.assertEqual(record["toolchain"]["msbuild_version"], "17.14.60.43110")
        self.assertEqual(record["toolchain"]["build_state"], BUILD_STATE)
        self.assertEqual(record["toolchain"]["cl"], CL_BANNER)
        self.assertEqual(json.loads((self.work / "build.json").read_text()), record)

    def test_the_dll_never_leaves_the_work_directory(self):
        self.built()
        found = [p for p in self.base.rglob("*.dll")] + [p for p in self.pin_dir.rglob("*.dll")]
        self.assertEqual(found, [self.work / "o" / "YYToolkit.dll"])

    def test_a_series_that_changed_since_apply_is_not_built(self):
        ctx = self.applied(FakeTools())
        self.write_patch(SECOND, self.upstream.patch_two.replace(b"second change", b"edited later"))
        with self.assertRaises(tool.Refused) as refusal:
            tool.build(ctx, toolchain=FAKE_TOOLCHAIN)
        self.assertIn("apply", str(refusal.exception))
        self.assertEqual(self.recorder.named("msbuild.exe"), [])

    def test_a_failed_or_empty_build_is_a_failure(self):
        for tools in (FakeTools(msbuild_code=1), FakeTools(dll=None)):
            with self.subTest(code=tools.msbuild_code):
                ctx = self.applied(tools)
                with self.assertRaises(tool.Failed):
                    tool.build(ctx, toolchain=FAKE_TOOLCHAIN)
                self.assertFalse(ctx.path("build.json").exists())

    def test_build_refuses_without_a_patched_tree(self):
        ctx = self.materialised(FakeTools())
        with self.assertRaises(tool.Refused):
            tool.build(ctx, toolchain=FAKE_TOOLCHAIN)


class TestToolchainDiscovery(Rig):
    def test_vswhere_is_asked_for_vs2022_with_the_x64_cpp_tools(self):
        vswhere = self.base / "vswhere.exe"
        vswhere.write_bytes(b"MZ")
        answers = {"MSBuild\\**\\Bin\\amd64\\MSBuild.exe": "C:\\VS\\MSBuild.exe\n",
                   "VC\\Auxiliary\\Build\\vcvars64.bat": "C:\\VS\\vcvars64.bat\n",
                   "installationVersion": "17.14.37710.0\n"}

        def fake_vswhere(call):
            if call.argv[0] == str(vswhere):
                return done(call, stdout=answers[call.argv[-1]])
            return None

        found = tool.locate_toolchain(self.ctx(fake_vswhere, passthrough=False), vswhere=vswhere)
        self.assertEqual(found, tool.Toolchain("C:\\VS\\MSBuild.exe", "C:\\VS\\vcvars64.bat",
                                               "17.14.37710.0"))
        for call in self.recorder.calls:
            self.assertEqual(call.argv[call.argv.index("-version") + 1], "[17.0,18.0)")
            self.assertEqual(call.argv[call.argv.index("-requires") + 1],
                             "Microsoft.VisualStudio.Component.VC.Tools.x86.x64")

    def test_no_matching_install_or_no_vswhere_exits_as_a_missing_toolchain(self):
        vswhere = self.base / "vswhere.exe"
        with self.assertRaises(tool.ToolchainMissing):
            tool.locate_toolchain(self.ctx(passthrough=False), vswhere=vswhere)
        vswhere.write_bytes(b"MZ")
        with self.assertRaises(tool.ToolchainMissing):
            tool.locate_toolchain(self.ctx(lambda call: done(call), passthrough=False),
                                  vswhere=vswhere)
        self.assertEqual(tool.ToolchainMissing.exit_code, 3)

    @unittest.skipIf(os.name == "nt", "on Windows the real vswhere is looked up instead")
    def test_off_windows_the_build_steps_say_so(self):
        with self.assertRaises(tool.ToolchainMissing) as missing:
            tool.locate_toolchain(self.ctx(passthrough=False))
        self.assertIn("Windows", str(missing.exception))


class TestHostTests(Rig):
    def test_every_host_test_is_compiled_through_vcvars_and_run(self):
        tools = FakeTools()
        ctx = self.applied(tools)
        record = tool.hosttests(ctx, toolchain=FAKE_TOOLCHAIN)
        self.assertEqual(record["files"], ["test_alpha.cpp", "test_filter.cpp"])
        self.assertEqual((record["ran"], record["passed"]), (2, 2))
        self.assertEqual([name for name, _ in tools.scripts], ["test_alpha.bat", "test_filter.bat"])
        script = tools.scripts[1][1]
        self.assertIn(f'call "{FAKE_TOOLCHAIN.vcvars64}"', script)
        self.assertIn("/std:c++latest", script)
        self.assertIn(f'"{self.work / "src" / "YYToolkit" / "hs-tests" / "test_filter.cpp"}"', script)
        self.assertIn(f'/I "{self.work / "src" / "YYToolkit" / "source"}"', script)
        ran = [os.path.basename(c.argv[0]) for c in self.recorder.calls
               if c.argv[0].endswith(".exe") and Path(c.argv[0]).parent == self.work / "t"]
        self.assertEqual(ran, ["test_alpha.exe", "test_filter.exe"])
        self.assertEqual(json.loads((self.work / "hosttests.json").read_text())["passed"], 2)

    def test_a_non_zero_exit_fails_naming_the_test_and_still_runs_the_rest(self):
        tools = FakeTools(test_codes={"test_alpha.exe": 3})
        ctx = self.applied(tools)
        with self.assertRaises(tool.Failed) as failure:
            tool.hosttests(ctx, toolchain=FAKE_TOOLCHAIN)
        self.assertIn("test_alpha.cpp: exited 3", str(failure.exception))
        self.assertNotIn("test_filter.cpp", str(failure.exception))
        self.assertEqual(len(tools.scripts), 2)
        self.assertFalse((self.work / "hosttests.json").exists())

    def test_a_test_that_does_not_compile_fails_naming_it(self):
        ctx = self.applied(FakeTools(compile_code=2))
        with self.assertRaises(tool.Failed) as failure:
            tool.hosttests(ctx, toolchain=FAKE_TOOLCHAIN)
        self.assertIn("test_filter.cpp: did not compile (exit 2)", str(failure.exception))

    def test_zero_host_tests_is_not_a_pass(self):
        self.write_series(FIRST)        # 0002 is the patch that adds hs-tests/
        ctx = self.applied(FakeTools())
        with self.assertRaises(tool.Failed):
            tool.hosttests(ctx, toolchain=FAKE_TOOLCHAIN)
        record = tool.hosttests(ctx, toolchain=FAKE_TOOLCHAIN, allow_none=True)
        self.assertEqual((record["ran"], record["passed"]), (0, 0))


class TestVerifyDll(Rig):
    def test_positive_control_markers_present_and_build_info_written(self):
        ctx, _ = self.built()
        tool.hosttests(ctx, toolchain=FAKE_TOOLCHAIN)
        returned = tool.verify_dll(ctx)
        out = self.work / "o"
        info = json.loads((out / "YYToolkit-BUILD-INFO.json").read_text())
        self.assertEqual(info, returned)

        self.assertEqual(info["upstream"], {
            "repo": "https://github.com/AurieFramework/YYToolkit", "tag": "v4.0.1",
            "commit": self.upstream.commit, "tree": self.upstream.tree})
        self.assertEqual(info["patches"], [
            {"name": FIRST, "sha256": hashlib.sha256(self.upstream.patch_one).hexdigest(),
             "log_markers": [MARKER_ONE]},
            {"name": SECOND, "sha256": hashlib.sha256(self.upstream.patch_two).hexdigest(),
             "log_markers": [MARKER_TWO]}])
        self.assertEqual(info["dll"], {"name": "YYToolkit.dll", "size": len(GOOD_DLL),
                                       "sha256": hashlib.sha256(GOOD_DLL).hexdigest()})
        self.assertEqual(info["toolchain"]["build_state"], BUILD_STATE)
        self.assertEqual(info["toolchain"]["msbuild_version"], "17.14.60.43110")
        self.assertEqual(info["toolchain"]["cl"], CL_BANNER)
        self.assertEqual(info["markers_verified"], [{"patch": FIRST, "marker": MARKER_ONE},
                                                    {"patch": SECOND, "marker": MARKER_TWO}])
        self.assertEqual(info["host_tests"]["passed"], 2)
        # A build cannot know this, and must never claim it.
        self.assertIs(info["live_gameplay_verified"], False)

        self.assertEqual((out / "YYToolkit.dll.sha256").read_text(),
                         hashlib.sha256(GOOD_DLL).hexdigest() + "  YYToolkit.dll\n")
        archive = out / info["source"]["name"]
        self.assertRegex(archive.name, r"^yytoolkit-source-[0-9a-f]{12}\.zip$")
        with zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
            self.assertEqual(names, {"third_party/yytoolkit/" + n for n in (
                "README.md", "NOTICE.md", "upstream.json", "patches/series",
                "patches/" + FIRST, "patches/" + SECOND)})
            self.assertEqual(bundle.read("third_party/yytoolkit/patches/" + SECOND),
                             self.upstream.patch_two)

    def test_negative_control_a_missing_marker_names_the_marker_and_the_patch(self):
        # What actually happened: a binary that lacks a change the source documents.
        lacking = GOOD_DLL.replace(MARKER_TWO.encode(), b"x" * len(MARKER_TWO))
        ctx, _ = self.built(FakeTools(dll=lacking))
        with self.assertRaises(tool.Failed) as failure:
            tool.verify_dll(ctx)
        message = str(failure.exception)
        self.assertIn(repr(MARKER_TWO), message)
        self.assertIn(SECOND, message)
        self.assertNotIn(repr(MARKER_ONE), message)
        self.assertEqual(sorted(p.name for p in (self.work / "o").iterdir()), ["YYToolkit.dll"])

    def test_a_failure_removes_the_build_info_an_earlier_success_wrote(self):
        ctx, _ = self.built()
        tool.verify_dll(ctx)
        self.assertTrue((self.work / "o" / "YYToolkit-BUILD-INFO.json").exists())
        (self.work / "o" / "YYToolkit.dll").write_bytes(GOOD_DLL + b"swapped after the build")
        with self.assertRaises(tool.Failed) as failure:
            tool.verify_dll(ctx)
        self.assertIn("not the file `build` produced", str(failure.exception))
        self.assertEqual(sorted(p.name for p in (self.work / "o").iterdir()), ["YYToolkit.dll"])

    def test_a_wide_string_does_not_count_and_the_message_says_so(self):
        wide = GOOD_DLL.replace(MARKER_TWO.encode(), MARKER_TWO.encode("utf-16-le"))
        ctx, _ = self.built(FakeTools(dll=wide))
        with self.assertRaises(tool.Failed) as failure:
            tool.verify_dll(ctx)
        self.assertIn("UTF-16", str(failure.exception))

    def test_a_marker_unpatched_upstream_already_contains_proves_nothing(self):
        ctx = self.materialised()
        self.write_patch(FIRST, self.upstream.patch_one.replace(
            f'"{MARKER_ONE}"'.encode(), b'"upstream: negative"', 1))
        dll = self.base / "unknown.dll"
        dll.write_bytes(GOOD_DLL + b"upstream: negative\x00")
        with self.assertRaises(tool.Failed) as failure:
            tool.verify_dll(ctx, dll=dll)
        self.assertIn("already occurs in unpatched upstream", str(failure.exception))
        self.assertIn(SPACED, str(failure.exception))

    def test_rerunning_writes_identical_bytes(self):
        ctx, _ = self.built()
        tool.verify_dll(ctx)
        first = {p.name: p.read_bytes() for p in (self.work / "o").iterdir()}
        tool.verify_dll(ctx)
        self.assertEqual({p.name: p.read_bytes() for p in (self.work / "o").iterdir()}, first)

    def test_expected_sha256_is_enforced(self):
        ctx, _ = self.built()
        tool.verify_dll(ctx, expected_sha256=hashlib.sha256(GOOD_DLL).hexdigest().upper())
        with self.assertRaises(tool.Failed):
            tool.verify_dll(ctx, expected_sha256="0" * 64)
        self.assertFalse((self.work / "o" / "YYToolkit-BUILD-INFO.json").exists())

    def test_a_dll_built_from_another_series_is_not_documented_as_this_one(self):
        ctx, _ = self.built()
        self.write_series(FIRST)
        with self.assertRaises(tool.Refused):
            tool.verify_dll(ctx)

    def test_any_dll_can_be_checked_read_only_and_nothing_is_written(self):
        dll = self.base / "of unknown origin.dll"
        ctx = self.ctx(passthrough=False)
        for data, passes in ((GOOD_DLL, True), (b"MZ" + MARKER_ONE.encode(), False)):
            with self.subTest(passes=passes):
                dll.write_bytes(data)
                if passes:
                    result = tool.verify_dll(ctx, dll=dll)
                    self.assertEqual(result["dll"]["sha256"], hashlib.sha256(data).hexdigest())
                else:
                    with self.assertRaises(tool.Failed) as failure:
                        tool.verify_dll(ctx, dll=dll)
                    self.assertIn(SECOND, str(failure.exception))
                self.assertEqual(dll.read_bytes(), data)
        self.assertFalse(self.work.exists())
        self.assertEqual(self.recorder.calls, [])


class TestCommandLine(Rig):
    def run_main(self, *argv, runner=None, toolchain=None):
        self.recorder = runner or Recorder()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tool.main(list(argv), runner=self.recorder, environ=self.upstream.env,
                             toolchain=toolchain)
        return code, out.getvalue(), err.getvalue()

    def short_work_dir(self) -> Path:
        """The command line enforces the real limit, so it needs a really short
        directory: <system temp>/ykNNN."""
        for _ in range(20):
            candidate = Path(tempfile.gettempdir()) / ("yk" + secrets.token_hex(2)[:3])
            if len(str(candidate)) > tool.MAX_WORK_DIR_LEN:
                self.skipTest(f"the system temp directory is too long for the command line's "
                              f"{tool.MAX_WORK_DIR_LEN}-character --work-dir limit")
            if not candidate.exists():
                self.addCleanup(scrub, candidate)
                return candidate
        self.skipTest("no free short directory name in the system temp directory")

    def test_refusals_exit_2_before_anything_runs(self):
        pin = ["--pin-dir", str(self.pin_dir)]
        inside = ROOT / "build" / "yk-test"
        code, _, err = self.run_main("materialise", "--upstream", str(self.upstream.repo),
                                     "--work-dir", str(inside), *pin,
                                     runner=Recorder(passthrough=False))
        self.assertEqual(code, 2)
        self.assertIn("REFUSED", err)
        self.assertFalse(inside.exists())

        too_long = Path(tempfile.gettempdir()) / ("y" * 41)
        code, _, err = self.run_main("all", "--upstream", str(self.upstream.repo),
                                     "--work-dir", str(too_long), *pin,
                                     runner=Recorder(passthrough=False))
        self.assertEqual(code, 2)
        self.assertFalse(too_long.exists())

    def test_no_upstream_without_allow_network_exits_2_and_starts_nothing(self):
        work = self.short_work_dir()
        code, _, err = self.run_main("all", "--work-dir", str(work), "--pin-dir", str(self.pin_dir),
                                     runner=Recorder(passthrough=False))
        self.assertEqual(code, 2)
        self.assertIn("--allow-network", err)
        self.assertEqual(self.recorder.calls, [])
        self.assertFalse(work.exists())

    def test_all_runs_the_five_steps_in_order_and_exits_0(self):
        work = self.short_work_dir()
        tools = FakeTools()
        code, out, err = self.run_main(
            "all", "--upstream", str(self.upstream.repo), "--work-dir", str(work),
            "--pin-dir", str(self.pin_dir), runner=Recorder(tools), toolchain=FAKE_TOOLCHAIN)
        self.assertEqual((code, err), (0, ""))
        steps = [line.split(":", 1)[0] for line in out.splitlines() if ":" in line]
        order = [s for i, s in enumerate(steps) if s in ("materialise", "apply", "build",
                 "hosttests", "verify-dll") and (i == 0 or steps[i - 1] != s)]
        self.assertEqual(order, ["materialise", "apply", "build", "hosttests", "verify-dll"])
        info = json.loads((work / "o" / "YYToolkit-BUILD-INFO.json").read_text())
        self.assertIs(info["live_gameplay_verified"], False)
        self.assertEqual(info["host_tests"]["passed"], 2)

    def test_a_patch_that_does_not_apply_exits_1_naming_it(self):
        work = self.short_work_dir()
        self.write_series(SECOND, FIRST)
        code, _, err = self.run_main(
            "all", "--upstream", str(self.upstream.repo), "--work-dir", str(work),
            "--pin-dir", str(self.pin_dir), runner=Recorder(FakeTools()), toolchain=FAKE_TOOLCHAIN)
        self.assertEqual(code, 1)
        self.assertIn(SECOND, err)
        self.assertEqual(self.recorder.named("msbuild.exe"), [])


def real_toolchain():
    if os.name != "nt":
        return None, "MSBuild, vcvars64.bat and cl are Windows-only"
    if GIT is None:
        return None, "git is not on PATH"
    try:
        found = tool.locate_toolchain(tool.Context(pin_dir=ROOT / "third_party" / "yytoolkit"))
    except tool.ToolError as error:
        return None, f"no VS 2022 C++ build tools: {error}"
    if not found.vcvars64:
        return None, "vcvars64.bat not found in the Visual Studio install"
    return found, ""


class TestRealToolchain(Rig):
    """The stubs above cannot notice a quoting mistake in an MSBuild property
    or a batch file. This runs all five steps for real on the synthetic project,
    in a work directory whose path contains a space."""

    @classmethod
    def setUpClass(cls):
        cls.toolchain, reason = real_toolchain()
        if cls.toolchain is None:
            raise unittest.SkipTest(reason)
        super().setUpClass()

    def test_all_five_steps_with_msbuild_and_cl(self):
        def quietly(argv, **options):      # MSBuild's console output is not a test result
            return tool.run_process(argv, **dict(options, capture=True))

        ctx = tool.Context(pin_dir=self.pin_dir, work_dir=self.work, environ=self.upstream.env,
                           runner=quietly, max_work_dir_len=ROOMY, log=self.lines.append)
        tool.materialise(ctx, self.upstream.repo)
        tool.apply_series(ctx)
        tool.build(ctx, toolchain=self.toolchain)
        tests = tool.hosttests(ctx, toolchain=self.toolchain)
        info = tool.verify_dll(ctx)

        self.assertEqual((tests["ran"], tests["passed"]), (2, 2))
        dll = (self.work / "o" / "YYToolkit.dll").read_bytes()
        self.assertEqual(dll[:2], b"MZ")
        self.assertIn(MARKER_ONE.encode(), dll)
        self.assertNotIn(b"upstream: negative", dll)
        # /PDBALTPATH arrived through the injected props file: the DLL names
        # its PDB, not the directory it was built in.
        self.assertIn(b"YYToolkit.pdb", dll)
        self.assertNotIn(str(self.work).encode(), dll)
        self.assertIn("v143", info["toolchain"]["build_state"])
        self.assertIn("Version", info["toolchain"]["cl"])
        self.assertIs(info["live_gameplay_verified"], False)


if __name__ == "__main__":
    unittest.main()
