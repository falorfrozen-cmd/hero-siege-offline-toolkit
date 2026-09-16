"""The PostToolUse hooks in .claude/hooks/ must actually block.

`AGENTS.md` § "Prove the Instrument Before Trusting a Negative Result" is the
reason this file exists. A hook that exits 0 on a file it should have flagged
is indistinguishable from a hook that is working, and during development all
three did exactly that: they exited 0 against a harness feeding them paths
Windows Python could not resolve, and looked healthy while guarding nothing.

So every test here is a pair. A *positive control* proves the hook fires on a
real violation, and a negative control proves it stays quiet on a clean tree.
A suite with only the negative half would pass against hooks that do nothing.

The rig is a throwaway git repository in the system temp directory, not the
session scratchpad -- `git init` there fails with `Filename too long`.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / ".claude" / "hooks"
SETTINGS = REPO / ".claude" / "settings.json"


def _load_hook_module(name):
    """Exec a `.claude/hooks/<name>.py` in isolation, for unit-level tests of
    its pure functions (as opposed to `HookRig`, which drives the hook as a
    subprocess the way `settings.json` actually invokes it). Not added to
    `sys.modules` -- each call gets its own copy."""
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

CLEAN_COMMAND = """\
#[tauri::command]
async fn correct_one(app: AppHandle) -> Result<(), String> {
    thing.check().await;
    Ok(())
}
"""

PASSING_TEST = """\
import test from 'node:test';
import assert from 'node:assert';
test('passes', () => { assert.equal(1, 1); });
"""


def _git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )


class HookRig:
    """A minimal git repo laid out like the toolkit, with the hooks copied in."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="hstk-hooks-"))
        for part in ("hub/src", "hub/src-tauri/src", "catalog", "tools"):
            (self.root / part).mkdir(parents=True, exist_ok=True)
        shutil.copytree(HOOKS, self.root / ".claude" / "hooks")
        # leftover_processes.py reads its sibling hooks' configured `command`
        # strings out of this file (see `_hook_path_fragments`), so the rig
        # needs a real copy, not just the scripts themselves.
        shutil.copy2(SETTINGS, self.root / ".claude" / "settings.json")

        # Real files so the clean-tree controls are meaningful.
        self.write("hub/src-tauri/src/lib.rs", CLEAN_COMMAND)
        self.write("hub/src/thing.js", "export const a = 1;\n")
        self.write("hub/src/thing.test.js", PASSING_TEST)
        for name in ("catalog.json", "catalog.json.minisig", "catalog-signing.pub"):
            self.write(f"catalog/{name}", "placeholder\n")
        # A verifier stub: the signature machinery is covered by
        # tests/test_minisign.py. What matters here is how the hook reacts to
        # each exit status, so the stub is switchable.
        self.write("tools/minisign.py", "import sys\nprint('OK')\nsys.exit(0)\n")

        _git("init", "-q", cwd=self.root)
        _git("config", "user.email", "t@example.com", cwd=self.root)
        _git("config", "user.name", "T", cwd=self.root)
        _git("add", "-A", cwd=self.root)
        _git("commit", "-qm", "base", cwd=self.root)

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def run(self, hook, payload=None, env=None, args=()):
        environ = dict(os.environ)
        environ.pop("HSTK_SKIP_HOOKS", None)
        environ.update(env or {})
        return subprocess.run(
            [sys.executable, str(self.root / ".claude" / "hooks" / hook), *args],
            cwd=self.root,
            input=json.dumps(payload if payload is not None else {"tool_name": "Bash"}),
            capture_output=True,
            text=True,
            env=environ,
        )

    def destroy(self):
        shutil.rmtree(self.root, ignore_errors=True)


class HookTestCase(unittest.TestCase):
    def setUp(self):
        self.rig = HookRig()
        self.addCleanup(self.rig.destroy)


class TestTauriCommandGuard(HookTestCase):
    HOOK = "tauri_command_guard.py"

    def test_clean_tree_is_silent(self):
        """Negative control: nothing changed, nothing said."""
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_block_on_in_command_blocks(self):
        self.rig.write(
            "hub/src-tauri/src/bad.rs",
            "#[tauri::command(async)]\n"
            "fn wrong(app: AppHandle) -> Result<(), String> {\n"
            "    let _ = tauri::async_runtime::block_on(thing.check());\n"
            "    Ok(())\n}\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("block_on", result.stderr)

    def test_async_fn_with_async_attribute_blocks(self):
        self.rig.write(
            "hub/src-tauri/src/bad.rs",
            "#[tauri::command(async)]\n"
            "async fn wrong(app: AppHandle) -> Result<(), String> {\n    Ok(())\n}\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("async fn", result.stderr)

    def test_indented_command_in_a_module_is_seen(self):
        """Regression: column-zero matching made every command in a mod invisible."""
        self.rig.write(
            "hub/src-tauri/src/bad.rs",
            "mod inner {\n"
            "    #[tauri::command(async)]\n"
            "    fn wrong(app: AppHandle) -> Result<(), String> {\n"
            "        let _ = tauri::async_runtime::block_on(thing.check());\n"
            "        Ok(())\n    }\n}\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("wrong", result.stderr)

    def test_rustfmt_wrapped_attribute_is_seen(self):
        """Regression: a wrapped attribute yielded no command, skipping both checks."""
        self.rig.write(
            "hub/src-tauri/src/bad.rs",
            "#[tauri::command(\n"
            '    rename_all = "snake_case",\n'
            "    async\n"
            ")]\n"
            "async fn wrong(app: AppHandle) -> Result<(), String> {\n    Ok(())\n}\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("wrong", result.stderr)

    def test_bare_command_attribute_is_seen(self):
        self.rig.write(
            "hub/src-tauri/src/bad.rs",
            "#[command]\n"
            "fn wrong(app: AppHandle) -> Result<(), String> {\n"
            "    let _ = tauri::async_runtime::block_on(thing.check());\n"
            "    Ok(())\n}\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_commented_out_block_on_does_not_block(self):
        self.rig.write(
            "hub/src-tauri/src/ok.rs",
            "#[tauri::command(async)]\n"
            "fn fine(app: AppHandle) -> Result<(), String> {\n"
            "    // tauri::async_runtime::block_on(thing.check());\n"
            "    Ok(())\n}\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_block_on_outside_a_command_does_not_block(self):
        """`startup_check` is a plain fn on its own thread and must stay legal."""
        self.rig.write(
            "hub/src-tauri/src/ok.rs",
            "fn startup_check(app: AppHandle) {\n"
            "    tauri::async_runtime::block_on(refresh(&app));\n}\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_violation_written_without_a_payload_path_still_blocks(self):
        """The Bash-bypass gap: a sed/heredoc edit produces no file_path at all."""
        self.rig.write(
            "hub/src-tauri/src/bad.rs",
            "#[tauri::command(async)]\n"
            "fn wrong(app: AppHandle) -> Result<(), String> {\n"
            "    let _ = tauri::async_runtime::block_on(thing.check());\n"
            "    Ok(())\n}\n",
        )
        result = self.rig.run(self.HOOK, payload={"tool_name": "Bash", "tool_input": {}})
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_skip_switch_silences_it(self):
        self.rig.write(
            "hub/src-tauri/src/bad.rs",
            "#[tauri::command(async)]\n"
            "fn wrong(app: AppHandle) -> Result<(), String> {\n"
            "    let _ = tauri::async_runtime::block_on(thing.check());\n"
            "    Ok(())\n}\n",
        )
        result = self.rig.run(self.HOOK, env={"HSTK_SKIP_HOOKS": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)


class TestCatalogSignature(HookTestCase):
    HOOK = "catalog_signature.py"

    def test_unchanged_catalog_is_silent(self):
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_changed_catalog_that_verifies_is_silent(self):
        self.rig.write("catalog/catalog.json", "changed\n")
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_bad_signature_blocks(self):
        self.rig.write("catalog/catalog.json", "changed\n")
        self.rig.write(
            "tools/minisign.py", "import sys\nprint('BAD SIGNATURE')\nsys.exit(1)\n"
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("no longer verifies", result.stderr)

    def test_crlf_is_named_as_the_cause(self):
        self.rig.write("catalog/catalog.json", "a\r\nb\r\n")
        self.rig.write(
            "tools/minisign.py", "import sys\nprint('BAD SIGNATURE')\nsys.exit(1)\n"
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("CRLF", result.stderr)

    def test_broken_verifier_is_not_reported_as_a_bad_signature(self):
        """A missing key is a verifier problem; saying 'bad signature' misleads."""
        self.rig.write("catalog/catalog.json", "changed\n")
        self.rig.write(
            "tools/minisign.py",
            "import sys\nsys.stderr.write('FileNotFoundError: key\\n')\nsys.exit(1)\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("could not be checked", result.stderr)
        self.assertNotIn("no longer verifies", result.stderr)

    def test_skip_switch_silences_it(self):
        self.rig.write("catalog/catalog.json", "changed\n")
        self.rig.write(
            "tools/minisign.py", "import sys\nprint('BAD SIGNATURE')\nsys.exit(1)\n"
        )
        result = self.rig.run(self.HOOK, env={"HSTK_SKIP_HOOKS": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)


class TestHubFrontendTests(HookTestCase):
    HOOK = "hub_frontend_tests.py"

    def test_clean_tree_is_silent(self):
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unrelated_change_does_not_run_tests(self):
        self.rig.write("hub/src-tauri/src/lib.rs", CLEAN_COMMAND + "// touched\n")
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node not on PATH")
    def test_failing_test_blocks(self):
        self.rig.write("hub/src/thing.js", "export const a = 2;\n")
        self.rig.write(
            "hub/src/thing.test.js",
            "import test from 'node:test';\n"
            "import assert from 'node:assert';\n"
            "test('fails', () => { assert.equal(1, 2); });\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("frontend tests fail", result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node not on PATH")
    def test_passing_tests_are_silent(self):
        self.rig.write("hub/src/thing.js", "export const a = 2;\n")
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)


class TestDecompiledOutput(HookTestCase):
    """The one hook whose failure is not fixable by a later release.

    `ForgePact/CREDITS.md` claims AGPL-3.0 original work, and that holds only
    while no game source text has reached any remote here. So this suite carries
    more negative controls than the others: a hook that flags `hs-game-sdk`'s own
    script-name tables would be switched off within a day, and a switched-off
    hook guards nothing.
    """

    HOOK = "decompiled_output.py"

    # Every one of these is explicitly blessed by AGENTS.md as an
    # interoperability fact. If the patterns ever start matching them, the hook
    # has become worse than useless.
    ALLOWED = """\
# Drop research

`gml_Script_scr_DropItem` (index 4021) is reached from `Loot_Manager_obj`.
We install through `HeroSiege::Scripts::gml_Script_scr_DropRelic` by name.
Measured: 176993 calls, 0 with a resolvable player, before the IsInstanceHandle
fix. The door script rolls the same die as case 11/31/40.
Offsets: +0x18 is the RValue kind; calling convention is __fastcall.
"""

    def test_clean_tree_is_silent(self):
        """Negative control: nothing changed, nothing said."""
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sdk_names_indices_and_measurements_do_not_block(self):
        """The load-bearing negative control -- see this class's docstring."""
        self.rig.write("docs/drop-research.md", self.ALLOWED)
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ghidra_symbol_blocks(self):
        self.rig.write(
            "docs/notes.md",
            "The handler:\n\n    iVar1 = FUN_00b489070(param_1);\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("Ghidra", result.stderr)

    def test_ida_symbol_blocks(self):
        self.rig.write("docs/notes.md", "call    sub_140A3B7C0\n")
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("IDA", result.stderr)

    def test_ghidra_type_declaration_blocks(self):
        self.rig.write("docs/notes.md", "undefined8 result;\n")
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_gml_positional_argument_blocks(self):
        self.rig.write(
            "ForgePact-notes.md",
            "the body reads:\n\nif (argument0 > 0) { return argument1; }\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("GML positional argument", result.stderr)

    def test_vm_pseudo_variable_blocks(self):
        self.rig.write("docs/notes.md", "pushi.e @@This@@\n")
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_gml_fence_blocks(self):
        self.rig.write("docs/notes.md", "```gml\nvar x = 1;\n```\n")
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_listing_in_source_blocks_not_only_markdown(self):
        """A comment in a .cpp is as tracked as a docs page."""
        self.rig.write(
            "hub/src-tauri/src/note.rs",
            "// original: iVar1 = FUN_00b489070(param_1);\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_guard_machinery_is_not_flagged_by_its_own_patterns(self):
        """`.claude/` holds the patterns themselves; see the hook's docstring."""
        self.rig.write(".claude/agents/note.md", "matches FUN_00b489070 too\n")
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_binary_asset_is_not_scanned(self):
        self.rig.write("docs/shot.png", "FUN_00b489070\n")
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_skip_switch_silences_it(self):
        self.rig.write("docs/notes.md", "call    sub_140A3B7C0\n")
        blocked = self.rig.run(self.HOOK)
        self.assertEqual(blocked.returncode, 2, blocked.stdout)
        allowed = self.rig.run(self.HOOK, env={"HSTK_SKIP_HOOKS": "1"})
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

    # -- added lines only -------------------------------------------------
    #
    # The first version of this hook matched whole file contents, and five
    # matches already sit in committed files (two in
    # ForgePact/docs/pet-quest-collector-c-research.md, two in
    # dungeon-key-research.md, one in the vendored YYToolkit). Appending a
    # paragraph to any of them made every subsequent tool call exit 2 until
    # someone set HSTK_SKIP_HOOKS=1 -- the exact outcome the docstring says it
    # avoids. These two tests are a pair: the hook must stop wedging, and
    # grandfathering must not become a loophole.

    LEGACY = "Old finding\n\n    iVar1 = FUN_00b489070(param_1);\n"

    def _commit_legacy(self):
        self.rig.write("docs/legacy-research.md", self.LEGACY)
        _git("add", "-A", cwd=self.rig.root)
        _git("commit", "-qm", "legacy research", cwd=self.rig.root)

    def test_appending_to_a_file_that_already_contains_a_listing_is_silent(self):
        self._commit_legacy()
        self.rig.write(
            "docs/legacy-research.md",
            self.LEGACY + "\nMeasured 176993 calls through the same path.\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_new_listing_added_to_such_a_file_still_blocks(self):
        """Grandfathering is scoped to what is in HEAD, not to the file."""
        self._commit_legacy()
        self.rig.write(
            "docs/legacy-research.md",
            self.LEGACY + "\nand then: call    sub_140A3B7C0\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("IDA", result.stderr)

    def test_deleting_a_line_containing_a_listing_is_silent(self):
        self._commit_legacy()
        self.rig.write("docs/legacy-research.md", "Old finding\n")
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)


class TestDecompiledOutputInSubmodules(HookTestCase):
    """`ForgePact/docs/` is where research notes land, and the hub's own
    `git status` reports a dirty submodule as one changed pointer -- never as
    the files inside it. Scanning only the hub would leave the single
    highest-risk directory in the repository unguarded, which is precisely the
    "looked installed and healthy while guarding nothing" failure this suite
    exists to prevent.
    """

    HOOK = "decompiled_output.py"

    def setUp(self):
        super().setUp()
        self.origin = Path(tempfile.mkdtemp(prefix="hstk-sub-"))
        self.addCleanup(shutil.rmtree, self.origin, ignore_errors=True)
        _git("init", "-q", cwd=self.origin)
        _git("config", "user.email", "t@example.com", cwd=self.origin)
        _git("config", "user.name", "T", cwd=self.origin)
        (self.origin / "docs").mkdir()
        (self.origin / "docs" / "research.md").write_bytes(b"clean\n")
        _git("add", "-A", cwd=self.origin)
        _git("commit", "-qm", "base", cwd=self.origin)
        try:
            _git(
                "-c", "protocol.file.allow=always",
                "submodule", "add", "-q", self.origin.as_uri(), "ForgePact",
                cwd=self.rig.root,
            )
            _git("commit", "-qm", "add submodule", cwd=self.rig.root)
        except subprocess.CalledProcessError as exc:
            raise unittest.SkipTest(f"git submodule add unavailable: {exc.stderr}")
        self.sub = self.rig.root / "ForgePact"

    def test_clean_submodule_is_silent(self):
        """Negative control: a registered, unmodified submodule says nothing."""
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_listing_inside_a_dirty_submodule_blocks(self):
        (self.sub / "docs" / "research.md").write_bytes(
            b"the collect path:\n\n    iVar1 = FUN_00b489070(param_1);\n"
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("ForgePact/docs/research.md", result.stderr)

    def test_clean_change_inside_a_submodule_does_not_block(self):
        (self.sub / "docs" / "research.md").write_bytes(
            b"Measured 176993 calls through gml_Script_scr_DropRelic.\n"
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)


def _kill_pid(pid):
    """Best-effort kill by PID, for cleanup only -- the hook itself never does this."""
    if sys.platform != "win32":
        return
    import ctypes

    PROCESS_TERMINATE = 0x0001
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if handle:
        try:
            ctypes.windll.kernel32.TerminateProcess(handle, 1)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)


def _kill_popen(proc):
    try:
        proc.kill()
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _wait_for_pidfile(path, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            text = path.read_text().strip()
            if text:
                return int(text)
        time.sleep(0.05)
    raise AssertionError(f"{path} never appeared")


def _get_exit_code(pid):
    """STILL_ACTIVE (259) means the PID is a live process, not a reused one."""
    import ctypes
    import ctypes.wintypes as wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value if ok else None
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


STILL_ACTIVE = 259

SLEEPER_MARKER = "hstk-leftover-sleeper"

_SLEEPER_ARGS = [sys.executable, "-c", "import time; time.sleep(60)", SLEEPER_MARKER]

_ORPHAN_LAUNCHER_SRC = (
    "import subprocess, sys\n"
    "p = subprocess.Popen(\n"
    f"    [sys.executable, '-c', 'import time; time.sleep(60)', '{SLEEPER_MARKER}'],\n"
    "    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,\n"
    ")\n"
    "print(p.pid)\n"
)

# A stand-in for an MCP server: polls for a trigger file, then spawns a
# sleeper and writes its PID, so a test can control exactly when the child
# appears relative to `pre`/`post`/`stop`.
_FAKE_MCP_SERVER_SRC = (
    "import os, subprocess, sys, time\n"
    "trigger, pidfile = sys.argv[1], sys.argv[2]\n"
    "while not os.path.exists(trigger):\n"
    "    time.sleep(0.05)\n"
    "p = subprocess.Popen(\n"
    f"    [sys.executable, '-c', 'import time; time.sleep(60)', '{SLEEPER_MARKER}']\n"
    ")\n"
    "open(pidfile, 'w').write(str(p.pid))\n"
    "time.sleep(60)\n"
)

# A live parent whose own command line can carry arbitrary extra argv --
# R2-1's fixture. It spawns a sleeper and writes its PID, then stays alive so
# it is still the sleeper's valid parent at `post`, the same as
# `_FAKE_MCP_SERVER_SRC` above, but with no polling: whatever this test wants
# the parent's own command line to *say* is passed as extra arguments, unused
# by the script itself.
_MENTION_PARENT_SRC = (
    "import subprocess, sys, time\n"
    "pidfile = sys.argv[1]\n"
    "p = subprocess.Popen(\n"
    f"    [sys.executable, '-c', 'import time; time.sleep(60)', '{SLEEPER_MARKER}']\n"
    ")\n"
    "open(pidfile, 'w').write(str(p.pid))\n"
    "time.sleep(60)\n"
)


def _spawn_orphan():
    """Runs an intermediate that detaches a sleeper and exits immediately.

    `subprocess.run` blocks until the intermediate exits, so by the time this
    returns the sleeper's parent is already gone -- exactly the
    `Start-Process` / `cmd /c start` shape the orphan admission rule targets.
    """
    result = subprocess.run(
        [sys.executable, "-c", _ORPHAN_LAUNCHER_SRC],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(result.stdout.strip())


@unittest.skipUnless(sys.platform == "win32", "leftover_processes.py is Windows-only")
class TestLeftoverProcesses(HookTestCase):
    """`.claude/hooks/leftover_processes.py`: reports, never kills.

    Every test drives the same `pre` -> (spawn) -> `post` -> `stop` sequence a
    real session would, through the three CLI modes, so the ledger file dance
    is exercised exactly the way `settings.json` invokes it, not through the
    hook's internals directly.
    """

    HOOK = "leftover_processes.py"

    def setUp(self):
        super().setUp()
        self.ledger_dir = tempfile.mkdtemp(prefix="hstk-ledger-")
        self.addCleanup(shutil.rmtree, self.ledger_dir, ignore_errors=True)
        self.session = "t"
        self.env = {
            "HSTK_PROC_LEDGER_DIR": self.ledger_dir,
            "HSTK_PROC_SESSION_ROOT_PID": str(os.getpid()),
            # Matches how a real session's hook commands resolve
            # `$CLAUDE_PROJECT_DIR` -- needed for `_hook_process_markers`'s
            # expanded-fragment form.
            "CLAUDE_PROJECT_DIR": str(self.rig.root),
        }
        self._cleanup_pids = []
        self.addCleanup(self._kill_tracked)

    def _kill_tracked(self):
        for pid in self._cleanup_pids:
            _kill_pid(pid)

    def track(self, pid):
        self._cleanup_pids.append(pid)
        return pid

    def spawn_sleeper(self):
        proc = subprocess.Popen(_SLEEPER_ARGS)
        self.addCleanup(_kill_popen, proc)
        return proc

    def _payload(self, event, call="call1", **extra):
        payload = {
            "session_id": self.session,
            "tool_use_id": call,
            "hook_event_name": event,
        }
        payload.update(extra)
        return payload

    def pre(self, call="call1", env=None):
        return self.rig.run(
            self.HOOK,
            payload=self._payload("PreToolUse", call),
            env=env if env is not None else self.env,
            args=("pre",),
        )

    def post(self, call="call1", env=None):
        return self.rig.run(
            self.HOOK,
            payload=self._payload("PostToolUse", call),
            env=env if env is not None else self.env,
            args=("post",),
        )

    def stop(self, active=False, env=None):
        payload = {
            "session_id": self.session,
            "hook_event_name": "Stop",
            "stop_hook_active": active,
        }
        return self.rig.run(
            self.HOOK,
            payload=payload,
            env=env if env is not None else self.env,
            args=("stop",),
        )

    # -- silence when nothing happened ------------------------------------

    # Negative control: an ordinary call with no leftovers reports nothing.
    def test_no_process_started_is_silent(self):
        self.assertEqual(self.pre().returncode, 0)
        self.assertEqual(self.post().returncode, 0)
        self.assertEqual(self.stop().returncode, 0)

    # -- the core positive/negative pair -----------------------------------

    # Positive control: a child spawned during the call outlives it.
    def test_child_started_during_call_is_reported(self):
        self.assertEqual(self.pre().returncode, 0)
        proc = self.spawn_sleeper()
        self.assertEqual(self.post().returncode, 0)
        result = self.stop()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn(str(proc.pid), result.stderr)

    # A process alive before `pre` is not this call's business.
    def test_process_existing_before_call_is_not_reported(self):
        self.spawn_sleeper()
        time.sleep(0.2)
        self.assertEqual(self.pre().returncode, 0)
        self.assertEqual(self.post().returncode, 0)
        self.assertEqual(self.stop().returncode, 0)

    # -- orphan admission (rule b) ------------------------------------------

    # A detached child whose launcher already exited is still attributed.
    def test_orphan_started_during_call_is_reported(self):
        self.assertEqual(self.pre().returncode, 0)
        orphan_pid = self.track(_spawn_orphan())
        self.assertEqual(self.post().returncode, 0)
        result = self.stop()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn(str(orphan_pid), result.stderr)

    # -- MCP-shaped exclusion (rule a's negative side) ----------------------

    # A child of a process that predates the call is not admitted. This is the
    # fake-MCP-server shape: the server itself is alive before `pre`, so a
    # child it spawns mid-call has a chain that passes through a pre-existing
    # process and must not be attributed to this call.
    def test_child_of_preexisting_process_is_not_reported(self):
        trigger = Path(self.ledger_dir) / "trigger"
        pidfile = Path(self.ledger_dir) / "pidfile"
        server = subprocess.Popen(
            [sys.executable, "-c", _FAKE_MCP_SERVER_SRC, str(trigger), str(pidfile)]
        )
        self.addCleanup(_kill_popen, server)
        time.sleep(0.2)
        self.assertEqual(self.pre().returncode, 0)
        trigger.write_text("go")
        child_pid = self.track(_wait_for_pidfile(pidfile))
        self.assertEqual(self.post().returncode, 0)
        result = self.stop()
        self.assertEqual(result.returncode, 0, result.stderr)

    # B1: a concurrent sibling PostToolUse hook's own chain (bash -> bash ->
    # py -> python .claude/hooks/*.py) is new relative to `pre` and reaches
    # root through processes that are all new this call -- structurally
    # identical to a real leftover under rule (a). A live Stop on 2026-09-16
    # 10:51 reported eleven of these. The fixture below is that chain's real
    # shape: a `py`/`python` descendant's own command line, after its shell
    # has substituted `$CLAUDE_PROJECT_DIR`, carries the fully-expanded
    # `<project dir>/.claude/hooks/<name>.py` fragment `_hook_process_markers`
    # reads out of `settings.json` -- not a bare directory mention. Its
    # negative pair is test_child_started_during_call_is_reported above: an
    # otherwise identical new child, without that fragment in its command
    # line, must still be reported. R2-1's own negative pair is
    # test_process_whose_ancestor_merely_mentions_hook_path_is_still_reported
    # below: a mention that is *not* this exact fragment must not exclude
    # anything.
    def test_process_running_a_hook_script_is_not_reported(self):
        self.assertEqual(self.pre().returncode, 0)
        expanded_fragment = f"{self.rig.root}/.claude/hooks/decompiled_output.py"
        sibling = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)", "py", "-3", expanded_fragment]
        )
        self.addCleanup(_kill_popen, sibling)
        self.assertEqual(self.post().returncode, 0)
        result = self.stop()
        self.assertEqual(result.returncode, 0, result.stderr)

    # R2-1 (instrument-blindness round 1): the old matcher treated *any*
    # mention of ".claude/hooks/" in a command line as proof a hop was running
    # a hook -- including a Bash tool call's own wrapper text, which embeds
    # whatever the user's command happened to say. Live A/B:
    # `echo .claude/hooks/ >/dev/null; py -3 -c "import time; time.sleep(40)"`
    # left every process in that chain out of the ledger; the same command
    # without the mention admitted all of them. Here the sleeper's parent
    # merely carries that same kind of text as extra argv -- never actually
    # invoking anything under `.claude/hooks/` -- and must not shield the
    # sleeper it spawned. Positive pair:
    # test_process_running_a_hook_script_is_not_reported above.
    def test_process_whose_ancestor_merely_mentions_hook_path_is_still_reported(self):
        self.assertEqual(self.pre().returncode, 0)
        pidfile = Path(self.ledger_dir) / "mention_pidfile"
        parent = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _MENTION_PARENT_SRC,
                str(pidfile),
                "bash.exe",
                "-c",
                'echo .claude/hooks/ >/dev/null; py -3 -c "import time; time.sleep(40)"',
            ]
        )
        self.addCleanup(_kill_popen, parent)
        child_pid = self.track(_wait_for_pidfile(pidfile))
        self.assertEqual(self.post().returncode, 0)
        result = self.stop()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn(str(child_pid), result.stderr)

    # -- ledger extension at Stop (rule c) -----------------------------------

    # A grandchild spawned after `post`, of a parent this call already owns.
    # The parent (this call's own fake MCP server, started between `pre` and
    # `post`) is admitted at `post` via rule (a). The child it spawns after
    # `post` never goes through `post` at all -- only `stop`'s ledger
    # extension (rule c) can attribute it.
    def test_child_of_preexisting_ledger_entry_is_reported(self):
        self.assertEqual(self.pre().returncode, 0)
        trigger = Path(self.ledger_dir) / "trigger2"
        pidfile = Path(self.ledger_dir) / "pidfile2"
        server = subprocess.Popen(
            [sys.executable, "-c", _FAKE_MCP_SERVER_SRC, str(trigger), str(pidfile)]
        )
        self.addCleanup(_kill_popen, server)
        time.sleep(0.2)
        self.assertEqual(self.post().returncode, 0)
        trigger.write_text("go")
        child_pid = self.track(_wait_for_pidfile(pidfile))
        result = self.stop()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn(str(child_pid), result.stderr)

    # -- a wrong root sees nothing of this session's tree --------------------

    # A root pid unrelated to this call's ancestry admits nothing.
    def test_other_session_root_is_not_reported(self):
        other_root = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(_kill_popen, other_root)
        env = dict(self.env)
        env["HSTK_PROC_SESSION_ROOT_PID"] = str(other_root.pid)
        self.assertEqual(self.pre(env=env).returncode, 0)
        self.spawn_sleeper()
        self.assertEqual(self.post(env=env).returncode, 0)
        self.assertEqual(self.stop(env=env).returncode, 0)

    # -- the Stop loop guard ---------------------------------------------

    # `stop_hook_active: true` must never block again -- that is the loop.
    def test_stop_hook_active_is_silent(self):
        self.assertEqual(self.pre().returncode, 0)
        self.spawn_sleeper()
        self.assertEqual(self.post().returncode, 0)
        self.assertEqual(self.stop(active=True).returncode, 0)

    # -- report-once ---------------------------------------------------------

    # A leftover blocks once; the second Stop of the same reply is silent.
    def test_reported_only_once(self):
        self.assertEqual(self.pre().returncode, 0)
        self.spawn_sleeper()
        self.assertEqual(self.post().returncode, 0)
        first = self.stop()
        self.assertEqual(first.returncode, 2, first.stdout)
        second = self.stop()
        self.assertEqual(second.returncode, 0, second.stderr)

    # -- identity is (pid, creation time), never pid alone -------------------

    # Once the PID is dead, `stop` must not report it (or a reused PID).
    def test_killed_process_is_not_reported(self):
        self.assertEqual(self.pre().returncode, 0)
        proc = subprocess.Popen(_SLEEPER_ARGS)
        self.assertEqual(self.post().returncode, 0)
        proc.kill()
        proc.wait(timeout=5)
        self.assertEqual(self.stop().returncode, 0)

    # A ledger entry whose creation time no longer matches is a stale PID.
    def test_reused_pid_is_not_reported(self):
        self.assertEqual(self.pre().returncode, 0)
        proc = self.spawn_sleeper()
        self.assertEqual(self.post().returncode, 0)
        sdir = Path(self.ledger_dir) / self.session
        post_file = sdir / "post-call1.json"
        recorded = json.loads(post_file.read_text())
        entry = recorded[str(proc.pid)]
        entry["creation"] = entry["creation"] + 999_999_999
        post_file.write_text(json.dumps({str(proc.pid): entry}))
        self.assertEqual(self.stop().returncode, 0)

    # -- the hard rule: it reports, it never touches the process --------------

    def test_hook_does_not_kill(self):
        self.assertEqual(self.pre().returncode, 0)
        proc = self.spawn_sleeper()
        self.assertEqual(self.post().returncode, 0)
        result = self.stop()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(_get_exit_code(proc.pid), STILL_ACTIVE)

    # -- escape hatch ----------------------------------------------------

    def test_skip_switch_silences_it(self):
        self.assertEqual(self.pre().returncode, 0)
        self.spawn_sleeper()
        self.assertEqual(self.post().returncode, 0)
        env = dict(self.env)
        env["HSTK_SKIP_HOOKS"] = "1"
        result = self.stop(env=env)
        self.assertEqual(result.returncode, 0, result.stderr)

    # -- the report names what to kill -------------------------------------

    def test_command_line_is_shown(self):
        self.assertEqual(self.pre().returncode, 0)
        self.spawn_sleeper()
        self.assertEqual(self.post().returncode, 0)
        result = self.stop()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn(SLEEPER_MARKER, result.stderr)


@unittest.skipUnless(sys.platform == "win32", "leftover_processes.py is Windows-only")
class TestLeftoverProcessesAdmissionRules(unittest.TestCase):
    """Unit-level tests of `leftover_processes.py`'s pure admission functions.

    `TestLeftoverProcesses` above drives the hook as `settings.json` actually
    invokes it -- three CLI calls against a real process tree -- which is the
    only way to prove the *mechanism* works end to end. These tests instead
    call the admission functions directly with a hand-built process table, so
    they can exercise a shape a real process tree makes awkward to arrange on
    purpose (an unopenable parent, a reused ledger PID) without depending on
    OS scheduling to land it.
    """

    @classmethod
    def setUpClass(cls):
        cls.hook = _load_hook_module("leftover_processes")

    # B2: a PPID this hook could not open (a SYSTEM service, a protected
    # process) is missing from `post_snap`/`pre_snap` exactly the way a truly
    # dead PPID is. Without the raw Toolhelp32 PID set, the two are
    # indistinguishable, and a live-but-unopenable parent gets misclassified
    # as an orphan -- the live 2026-09-16 report did this to
    # `dllhost.exe`/`audiodg.exe` under an unopenable `svchost.exe`.
    def test_orphan_admission_respects_unopenable_parent_in_raw_pids(self):
        proc = {"pid": 100, "ppid": 50, "creation": 500}
        post_snap = {}  # parent unopenable -> absent from the creation-keyed map
        pre_snap = {}
        post_raw_pids = {50}  # but Toolhelp32 still lists PID 50 as existing
        pre_raw_pids = {50}
        self.assertFalse(
            self.hook._is_orphan_admissible(
                proc, post_snap, pre_snap, post_raw_pids, pre_raw_pids
            )
        )

    # Negative pair: when the PPID is genuinely absent from the raw PID set
    # too, it is still a real orphan and must still be admitted -- the fix
    # above must not blind rule (b) to actual detached launches.
    def test_orphan_admission_still_admits_when_parent_truly_gone(self):
        proc = {"pid": 100, "ppid": 50, "creation": 500}
        post_snap = {}
        pre_snap = {}
        post_raw_pids = set()
        pre_raw_pids = set()
        self.assertTrue(
            self.hook._is_orphan_admissible(
                proc, post_snap, pre_snap, post_raw_pids, pre_raw_pids
            )
        )

    # B3: `entry.creation <= proc.creation` is true for any later process once
    # a ledger entry is dead, reused PID or not -- so a dead entry must prove
    # it died *during this call* (present at `pre`, gone by `post`) before its
    # PPID field is trusted, and a *live* PID must match the ledger's creation
    # time exactly rather than merely postdate it.
    def test_parent_in_ledger_rejects_reused_ppid(self):
        ledger = {50: {"pid": 50, "ppid": 1, "creation": 100}}
        proc = {"pid": 100, "ppid": 50, "creation": 9999}
        # PID 50 is currently occupied by an unrelated process with a much
        # later creation time: the ledger's process is long gone and reused.
        post_snap = {50: {"pid": 50, "ppid": 1, "creation": 9000, "image": "unrelated.exe"}}
        pre_snap = {}
        self.assertFalse(self.hook._parent_in_ledger(proc, ledger, post_snap, pre_snap))

    # Negative pair: the ledger's parent really did die mid-call (it was
    # alive at `pre`, gone by `post`), so the PPID link is trustworthy and the
    # child must still be admitted.
    def test_parent_in_ledger_admits_when_parent_died_this_call(self):
        ledger = {50: {"pid": 50, "ppid": 1, "creation": 100}}
        proc = {"pid": 100, "ppid": 50, "creation": 9999}
        post_snap = {}  # parent is dead by post
        pre_snap = {50: {"pid": 50, "ppid": 1, "creation": 100, "image": "x.exe"}}
        self.assertTrue(self.hook._parent_in_ledger(proc, ledger, post_snap, pre_snap))

    # B5: `conhost.exe` dies with its owning console and is pure noise even
    # when it structurally qualifies as a live descendant of a ledger entry --
    # `post`'s admission already excludes it; the Stop-time ledger extension
    # (rule c's grandchild case) did not, and a live run reported one.
    def test_extend_ledger_excludes_conhost(self):
        root = 1
        ledger = {50: {"pid": 50, "ppid": root, "creation": 100, "image": "cmd.exe"}}
        live_snap = {
            50: {"pid": 50, "ppid": root, "creation": 100, "image": "cmd.exe"},
            60: {"pid": 60, "ppid": 50, "creation": 200, "image": "conhost.exe"},
        }
        extended = self.hook._extend_ledger_with_live_descendants(ledger, live_snap, root)
        self.assertEqual(extended, {})

    # Negative pair: an ordinary (non-conhost) live descendant of the same
    # ledger entry is still extended -- the fix must not blind rule (c) to
    # real grandchildren.
    def test_extend_ledger_admits_ordinary_descendant(self):
        root = 1
        ledger = {50: {"pid": 50, "ppid": root, "creation": 100, "image": "cmd.exe"}}
        live_snap = {
            50: {"pid": 50, "ppid": root, "creation": 100, "image": "cmd.exe"},
            60: {"pid": 60, "ppid": 50, "creation": 200, "image": "python.exe"},
        }
        extended = self.hook._extend_ledger_with_live_descendants(ledger, live_snap, root)
        self.assertEqual(extended, {60: live_snap[60]})


if __name__ == "__main__":
    unittest.main()
