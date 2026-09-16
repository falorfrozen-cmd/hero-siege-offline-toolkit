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

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / ".claude" / "hooks"
SETTINGS = REPO / ".claude" / "settings.json"


def _hooks_source_dir():
    """The directory `HookRig` and `_load_hook_module` load hook scripts from.

    `HSTK_HOOK_UNDER_TEST_DIR` swaps in a scratchpad copy -- a mutant, or an
    older revision fetched with `git show` -- without ever overwriting the
    live `.claude/hooks/` the running session's own hooks execute from."""
    override = os.environ.get("HSTK_HOOK_UNDER_TEST_DIR")
    return Path(override) if override else HOOKS


def _load_hook_module(name):
    """Exec a `.claude/hooks/<name>.py` in isolation, for unit-level tests of
    its pure functions (as opposed to `HookRig`, which drives the hook as a
    subprocess the way `settings.json` actually invokes it). Not added to
    `sys.modules` -- each call gets its own copy."""
    spec = importlib.util.spec_from_file_location(name, _hooks_source_dir() / f"{name}.py")
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
        shutil.copytree(_hooks_source_dir(), self.root / ".claude" / "hooks")
        # leftover_processes.py reads its sibling hooks' configured `command`
        # strings out of this file (see `_configured_hooks`), so the rig
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
            # `$CLAUDE_PROJECT_DIR` -- needed so `_configured_hooks`'s script
            # paths (and a py/python hop's own expanded command line) resolve
            # to the same normalised form.
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

    # F1 (structural matcher, replacing the substring one): a hop's command
    # line is only "running a hook" when `CommandLineToArgvW`'s parse matches
    # a configured `command` string exactly (a shell hop) or a configured
    # script path exactly (a py/python hop) -- never a bare mention. These
    # three probe the old matcher's own blind spot (round-0 planner
    # research): with `CLAUDE_PROJECT_DIR` in forward-slash form, the old
    # code treated all three spellings below as proof a hop was running the
    # hook, even though the process below only ever *mentions* one in its own
    # command line and never invokes anything under `.claude/hooks/`.
    # Positive pair for all three: test_real_hook_wrapper_chain_is_not_reported
    # below.
    def _assert_hook_path_mention_is_still_reported(self, spelling):
        env = dict(self.env)
        env["CLAUDE_PROJECT_DIR"] = str(self.rig.root).replace("\\", "/")
        self.assertEqual(self.pre(env=env).returncode, 0)
        pidfile = Path(self.ledger_dir) / "quoting_pidfile"
        parent = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _MENTION_PARENT_SRC,
                str(pidfile),
                "bash.exe",
                "-c",
                f'echo "{spelling}" >/dev/null; py -3 -c "import time; time.sleep(40)"',
            ]
        )
        self.addCleanup(_kill_popen, parent)
        child_pid = self.track(_wait_for_pidfile(pidfile))
        self.assertEqual(self.post(env=env).returncode, 0)
        result = self.stop(env=env)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn(str(child_pid), result.stderr)

    def test_command_quoting_unexpanded_hook_path_is_still_reported(self):
        self._assert_hook_path_mention_is_still_reported(
            "$CLAUDE_PROJECT_DIR/.claude/hooks/decompiled_output.py"
        )

    def test_command_quoting_forward_slash_hook_path_is_still_reported(self):
        root = str(self.rig.root).replace("\\", "/")
        self._assert_hook_path_mention_is_still_reported(
            f"{root}/.claude/hooks/decompiled_output.py"
        )

    def test_command_quoting_backslash_hook_path_is_still_reported(self):
        root = str(self.rig.root).replace("\\", "/")
        self._assert_hook_path_mention_is_still_reported(
            f"{root}/.claude/hooks/decompiled_output.py".replace("/", "\\")
        )

    # F1's positive pair, and the round-2 N4 replacement for the deleted
    # test_process_running_a_hook_script_is_not_reported: that fixture's
    # `python -c ... py -3 <path>` gave argv[1] == "-c", which the structural
    # rule rightly excludes from matching a py/python hop, so it proved
    # nothing about F1's replacement. This spawns the real wrapper chain
    # settings.json actually configures -- Git Bash's own `-c` argument, byte
    # for byte -- so the exclusion is proven against the real shape, not a
    # fixture that merely looks like it.
    def test_real_hook_wrapper_chain_is_not_reported(self):
        bash = os.path.join(
            os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "bin", "bash.exe"
        )
        if not os.path.exists(bash):
            bash = shutil.which("bash")
        if not bash:
            self.skipTest("Git Bash not found")
        # Overwrite the rig's own copy -- never the repository's -- with a
        # script that reports its PID and sleeps, standing in for the hook
        # body so the test controls how long the chain lives.
        pidfile = Path(self.ledger_dir) / "wrapper_pidfile"
        self.rig.write(
            ".claude/hooks/decompiled_output.py",
            "import os\n"
            "open(os.environ['HSTK_TEST_PIDFILE'], 'w').write(str(os.getpid()))\n"
            "import time; time.sleep(60)\n",
        )
        self.assertEqual(self.pre().returncode, 0)
        environ = dict(os.environ)
        environ.pop("HSTK_SKIP_HOOKS", None)
        environ.update(self.env)
        environ["HSTK_TEST_PIDFILE"] = str(pidfile)
        wrapper = subprocess.Popen(
            [bash, "-c", 'py -3 "$CLAUDE_PROJECT_DIR/.claude/hooks/decompiled_output.py"'],
            cwd=self.rig.root,
            env=environ,
        )
        self.addCleanup(_kill_popen, wrapper)
        py_pid = _wait_for_pidfile(pidfile)
        self.addCleanup(_kill_pid, py_pid)
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
    # test_real_hook_wrapper_chain_is_not_reported above.
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

    # -- fail-open and blindness are visible (F3/F4) --------------------------

    # F3: an unreadable settings.json means `_hooks()` finds no configured
    # hook command, so a sibling hook chain cannot be recognised -- fails
    # open (never crashes) and says so on the one channel a person actually
    # sees (`systemMessage`; plain stderr at exit 0 is invisible).
    def test_malformed_settings_fails_open_with_note(self):
        self.rig.write(".claude/settings.json", "{not json")
        self.assertEqual(self.pre().returncode, 0)
        self.spawn_sleeper()
        self.assertEqual(self.post().returncode, 0)
        result = self.stop()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("no hook commands found", result.stderr)
        message = json.loads(result.stdout)
        self.assertIn("no hook commands found", message["systemMessage"])

    # Same fail-open contract against a settings.json that parses as JSON but
    # is the wrong shape throughout -- a non-list hook group, a bare string
    # where a list belongs. Must not raise.
    def test_non_dict_hooks_group_fails_open_without_traceback(self):
        self.rig.write(
            ".claude/settings.json",
            json.dumps({"hooks": {"PostToolUse": ["oops", 3], "Stop": "x"}}),
        )
        self.assertEqual(self.pre().returncode, 0)
        self.spawn_sleeper()
        self.assertEqual(self.post().returncode, 0)
        result = self.stop()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("no hook commands found", result.stderr)

    # Negative control: the real settings.json (what the rig copies by
    # default) has hook commands, so the note never fires.
    def test_valid_settings_emits_no_hook_note(self):
        self.assertEqual(self.pre().returncode, 0)
        self.spawn_sleeper()
        self.assertEqual(self.post().returncode, 0)
        result = self.stop()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertNotIn("no hook commands found", result.stderr)
        self.assertNotIn("no hook commands found", result.stdout)

    # The F3 note is shown once per session, not repeated every reply while
    # the config stays broken (the user's own call, overriding the plan's
    # every-reply wording near its "Needs human judgement" section): the
    # first Stop against a broken settings.json warns.
    def test_malformed_settings_note_shown_only_on_first_stop(self):
        self.rig.write(".claude/settings.json", "{not json")
        self.assertEqual(self.pre().returncode, 0)
        self.assertEqual(self.post().returncode, 0)
        first = self.stop()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("no hook commands found", first.stderr)
        message = json.loads(first.stdout)
        self.assertIn("no hook commands found", message["systemMessage"])

    # Positive/negative pair for the once-per-session claim above: a second
    # Stop of the same session, settings still broken, says nothing more.
    def test_malformed_settings_note_suppressed_on_second_stop(self):
        self.rig.write(".claude/settings.json", "{not json")
        self.assertEqual(self.pre().returncode, 0)
        self.assertEqual(self.post().returncode, 0)
        self.stop()
        second = self.stop()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("no hook commands found", second.stderr)
        self.assertEqual(second.stdout.strip(), "")

    # F4 (stop): the session-root lookup itself failing is a visible warning,
    # not a silent "admits nothing".
    def test_stop_without_root_emits_system_message(self):
        env = dict(self.env)
        env["HSTK_PROC_SESSION_ROOT_PID"] = "not-a-pid"
        result = self.stop(env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no claude.exe ancestor at Stop", result.stderr)
        message = json.loads(result.stdout)
        self.assertIn("no claude.exe ancestor at Stop", message["systemMessage"])

    # F4 (post): a `post` call that could not find its session root records
    # nothing but leaves a marker, so a later `stop` (with a working root)
    # can say how many calls this session went blind for -- once per newly
    # blind call, the same way `reported.json` already does for a leftover.
    def test_post_without_root_is_surfaced_once_at_stop(self):
        env = dict(self.env)
        env["HSTK_PROC_SESSION_ROOT_PID"] = "not-a-pid"
        self.assertEqual(self.pre(env=env).returncode, 0)
        self.assertEqual(self.post(env=env).returncode, 0)
        first = self.stop()
        self.assertEqual(first.returncode, 0, first.stderr)
        message = json.loads(first.stdout)
        self.assertIn(
            "1 PostToolUse call(s) found no claude.exe ancestor", message["systemMessage"]
        )
        second = self.stop()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout.strip(), "")

    # R1-B item 4: a hand-corrupted `reported.json` (wrong shape entirely, not
    # merely an unreadable file) must not crash `stop` -- it degrades to
    # "nothing was reported before", the same as a missing file, so a real
    # leftover is still reported rather than the hook raising. Covers
    # `noroot-reported.json` the same way in the same call.
    def test_corrupt_marker_file_is_treated_as_empty(self):
        self.assertEqual(self.pre().returncode, 0)
        self.spawn_sleeper()
        self.assertEqual(self.post().returncode, 0)
        sdir = Path(self.ledger_dir) / self.session
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "reported.json").write_text("[1, 2, 3]", encoding="utf-8")
        (sdir / "noroot-reported.json").write_text('"not-a-dict"', encoding="utf-8")
        result = self.stop()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn(SLEEPER_MARKER, result.stderr)

    # R2-2: a hand-corrupted ledger file can be wrong-shaped in ways the
    # marker-file test above does not cover -- a `post-*.json` that is a
    # top-level list instead of a `{pid: entry}` map, one whose entry is not
    # itself a dict (a good entry sitting right next to a bad one, in the
    # same file), a `pre-*.json` whose `procs` is likewise a list, and
    # `reported.json` holding `Infinity` (valid JSON to Python's own parser,
    # but `int(float("inf"))` raises `OverflowError`, not `ValueError`). None
    # of this may crash `post` or `stop`, and a leftover recorded through the
    # normal path must still be reported. Must fail against 6f536a6.
    def test_wrong_shape_ledger_files_do_not_crash(self):
        self.assertEqual(self.pre().returncode, 0)
        proc = self.spawn_sleeper()
        self.assertEqual(self.post().returncode, 0)
        sdir = Path(self.ledger_dir) / self.session
        post_call1 = sdir / "post-call1.json"
        good_entry = json.loads(post_call1.read_text(encoding="utf-8"))
        post_call1.unlink()
        mixed = dict(good_entry)
        mixed["1"] = 5
        (sdir / "post-mixed.json").write_text(json.dumps(mixed), encoding="utf-8")
        (sdir / "post-badlist.json").write_text("[1, 2, 3]", encoding="utf-8")
        (sdir / "pre-call2.json").write_text(
            json.dumps({"procs": [1, 2, 3], "raw_pids": []}), encoding="utf-8"
        )
        (sdir / "reported.json").write_text(
            json.dumps({"1": float("inf")}), encoding="utf-8"
        )
        post_result = self.post(call="call2")
        self.assertEqual(post_result.returncode, 0, post_result.stderr)
        self.assertNotIn("Traceback", post_result.stdout)
        self.assertNotIn("Traceback", post_result.stderr)
        result = self.stop()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn(str(proc.pid), result.stderr)

    # E: item 2's two corruption shapes, exercised at CLI level through a
    # real pre/post/stop sequence rather than `_load_pre_snapshot` alone -- a
    # hand-corrupted `pre-*.json` must not crash the very next `post`, and a
    # leftover recorded through the normal path must still be reported at
    # `stop` afterward. Must fail against the pre-fix baseline, which raises
    # `OverflowError` out of the `raw_pids` loop and `KeyError` out of
    # `cmd_post`'s `pre_keys` comprehension.
    def test_overflow_raw_pids_and_pidless_pre_entry_do_not_crash(self):
        self.assertEqual(self.pre().returncode, 0)
        proc = self.spawn_sleeper()
        self.assertEqual(self.post().returncode, 0)
        sdir = Path(self.ledger_dir) / self.session

        self.assertEqual(self.pre(call="call2").returncode, 0)
        pre2 = sdir / "pre-call2.json"
        data = json.loads(pre2.read_text(encoding="utf-8"))
        data["raw_pids"].append(float("inf"))
        pre2.write_text(json.dumps(data), encoding="utf-8")
        post2 = self.post(call="call2")
        self.assertEqual(post2.returncode, 0, post2.stderr)
        self.assertNotIn("Traceback", post2.stdout)
        self.assertNotIn("Traceback", post2.stderr)

        self.assertEqual(self.pre(call="call3").returncode, 0)
        pre3 = sdir / "pre-call3.json"
        data = json.loads(pre3.read_text(encoding="utf-8"))
        data["procs"]["999999"] = {"ppid": 4, "image": "pidless.exe", "creation": 1}
        pre3.write_text(json.dumps(data), encoding="utf-8")
        post3 = self.post(call="call3")
        self.assertEqual(post3.returncode, 0, post3.stderr)
        self.assertNotIn("Traceback", post3.stdout)
        self.assertNotIn("Traceback", post3.stderr)

        result = self.stop()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn(str(proc.pid), result.stderr)

    # Negative control: an ordinary tracked call with nothing spawned and
    # nothing broken prints no systemMessage at all.
    def test_tracked_session_prints_no_system_message(self):
        self.assertEqual(self.pre().returncode, 0)
        self.assertEqual(self.post().returncode, 0)
        result = self.stop()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")


@unittest.skipUnless(sys.platform == "win32", "leftover_processes.py is Windows-only")
class TestLeftoverProcessesStaleToolhelp(unittest.TestCase):
    """F5: a positive control for `stop`'s `GetExitCodeProcess` liveness gate.

    `test_killed_process_is_not_reported` (in `TestLeftoverProcesses`) passes
    even with the gate removed, because Toolhelp32Snapshot does not list an
    exited process on demand in this suite's own timing -- it cannot produce
    the stale case the gate exists for. Built at unit level instead: a
    fabricated ledger entry, plus a stubbed `snapshot()`/`_command_line` that
    still "sees" the pid the way a just-terminated process's stale Toolhelp32
    entry does, with `_is_still_active` stubbed both ways so the gate itself
    is what the assertion depends on.
    """

    def setUp(self):
        self.hook = _load_hook_module("leftover_processes")
        self.ledger_dir = tempfile.mkdtemp(prefix="hstk-stale-")
        self.addCleanup(shutil.rmtree, self.ledger_dir, ignore_errors=True)
        sdir = Path(self.ledger_dir) / "t"
        sdir.mkdir(parents=True, exist_ok=True)
        entry = {"pid": 4000004, "ppid": 1, "image": "sleeper.exe", "creation": 123}
        (sdir / "post-x.json").write_text(json.dumps({"4000004": entry}), encoding="utf-8")
        self.entry = entry
        self.env_patch = mock.patch.dict(
            os.environ,
            {"HSTK_PROC_LEDGER_DIR": self.ledger_dir, "HSTK_PROC_SESSION_ROOT_PID": "1"},
        )
        self.env_patch.start()
        os.environ.pop("HSTK_SKIP_HOOKS", None)
        self.addCleanup(self.env_patch.stop)

    def _run_stop(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = self.hook.cmd_stop({"session_id": "t", "stop_hook_active": False})
        return code, stdout.getvalue(), stderr.getvalue()

    # A pid Toolhelp32 still lists, but whose exit code is no longer
    # STILL_ACTIVE, must not be reported -- the gate this proves. Without
    # `if not _is_still_active(pid):` in `cmd_stop`, this would report it.
    def test_exited_process_still_in_snapshot_is_not_reported(self):
        snap = {4000004: dict(self.entry)}
        with mock.patch.object(self.hook, "snapshot", return_value=(snap, {4000004})), \
             mock.patch.object(self.hook, "_command_line", return_value=None), \
             mock.patch.object(self.hook, "_is_still_active", return_value=False):
            code, _stdout, _stderr = self._run_stop()
        self.assertEqual(code, 0)

    # Positive pair: the same stale-looking snapshot, but the exit code
    # genuinely still reads STILL_ACTIVE -- a real leftover, and it must
    # still be reported.
    def test_live_process_in_snapshot_is_reported(self):
        snap = {4000004: dict(self.entry)}
        with mock.patch.object(self.hook, "snapshot", return_value=(snap, {4000004})), \
             mock.patch.object(self.hook, "_command_line", return_value=None), \
             mock.patch.object(self.hook, "_is_still_active", return_value=True):
            code, _stdout, stderr = self._run_stop()
        self.assertEqual(code, 2)
        self.assertIn("4000004", stderr)


@unittest.skipUnless(sys.platform == "win32", "leftover_processes.py is Windows-only")
class TestLeftoverProcessesHookMatch(unittest.TestCase):
    """Unit-level tests of F1's structural matcher: `_configured_hooks` (what
    counts as a configured hook, read straight from `settings.json`/
    `settings.local.json`) and `_is_hook_invocation` (whether one hop's own
    command line is actually running one) -- as opposed to `TestLeftoverProcesses`
    above, which proves the mechanism end to end against a real process tree.
    """

    @classmethod
    def setUpClass(cls):
        cls.hook = _load_hook_module("leftover_processes")

    def setUp(self):
        self.claude_dir = Path(tempfile.mkdtemp(prefix="hstk-claude-"))
        self.addCleanup(shutil.rmtree, self.claude_dir, ignore_errors=True)

    def _write(self, name, text):
        (self.claude_dir / name).write_text(text, encoding="utf-8")

    # The four hop shapes a 45 s live poll actually captured (round-0 planner
    # research), read against a real `.claude/settings.json` copy -- proves
    # the matcher recognises the hook chain settings.json actually produces,
    # not just a hand-built approximation of it.
    def test_measured_hook_command_lines_match(self):
        self._write("settings.json", SETTINGS.read_text(encoding="utf-8"))
        project_dir = "C:/Users/Administrator/PycharmProjects/hero-siege-offline-toolkit"
        commands, scripts = self.hook._configured_hooks(self.claude_dir, [project_dir])
        cases = [
            (
                "bash.exe",
                r'"C:\Program Files\Git\bin\bash.exe" -c "py -3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/decompiled_output.py\""',
            ),
            (
                "bash.exe",
                r'"C:\Program Files\Git\bin\..\usr\bin\bash.exe" -c "py -3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/decompiled_output.py\""',
            ),
            (
                "py.exe",
                r"C:\WINDOWS\py.exe -3 C:/Users/Administrator/PycharmProjects/hero-siege-offline-toolkit/.claude/hooks/decompiled_output.py",
            ),
            (
                "python.exe",
                r"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe C:/Users/Administrator/PycharmProjects/hero-siege-offline-toolkit/.claude/hooks/decompiled_output.py",
            ),
        ]
        for image, cmdline in cases:
            with self.subTest(image=image):
                self.assertTrue(self.hook._is_hook_invocation(image, cmdline, commands, scripts))

    # Negative pair: a bare mention (the Bash tool's own wrapper text), a
    # `-c`/other-option interpreter flag, and another repo script are never
    # mistaken for a hop actually running a configured hook.
    def test_mentions_and_other_scripts_do_not_match(self):
        self._write("settings.json", SETTINGS.read_text(encoding="utf-8"))
        project_dir = "C:/Users/Administrator/PycharmProjects/hero-siege-offline-toolkit"
        commands, scripts = self.hook._configured_hooks(self.claude_dir, [project_dir])
        cases = [
            (
                "bash.exe",
                "bash.exe -c \"source x && eval 'echo $CLAUDE_PROJECT_DIR/.claude/hooks/decompiled_output.py'\"",
            ),
            (
                "py.exe",
                'py.exe -3 -c "import time" C:/Users/Administrator/PycharmProjects/hero-siege-offline-toolkit/.claude/hooks/decompiled_output.py',
            ),
            (
                "python.exe",
                "python.exe C:/Users/Administrator/PycharmProjects/hero-siege-offline-toolkit/.claude/hooks/_common.py",
            ),
            (
                "python.exe",
                r'python.exe -c "..." bash.exe -c "py -3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/decompiled_output.py\""',
            ),
        ]
        for image, cmdline in cases:
            with self.subTest(image=image, cmdline=cmdline):
                self.assertFalse(self.hook._is_hook_invocation(image, cmdline, commands, scripts))

    # `settings.local.json` is read too, `${CLAUDE_PROJECT_DIR}` (braced) is
    # recognised alongside the bare `$CLAUDE_PROJECT_DIR` form, and a script
    # token with no `$CLAUDE_PROJECT_DIR` prefix at all is resolved relative
    # to the project dir -- a hook's cwd is the project dir.
    def test_configured_hooks_reads_local_settings_and_brace_and_relative_forms(self):
        self._write(
            "settings.json",
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "py -3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/a.py",
                                    }
                                ]
                            }
                        ]
                    }
                }
            ),
        )
        self._write(
            "settings.local.json",
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {"hooks": [{"type": "command", "command": "py -3 .claude/hooks/b.py"}]}
                        ]
                    }
                }
            ),
        )
        project_dir = "C:/proj"
        commands, scripts = self.hook._configured_hooks(self.claude_dir, [project_dir])
        self.assertIn("py -3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/a.py", commands)
        self.assertIn("py -3 .claude/hooks/b.py", commands)
        self.assertIn(f"{project_dir}/.claude/hooks/a.py".lower(), scripts)
        self.assertIn(f"{project_dir}/.claude/hooks/b.py".lower(), scripts)

    # F3's robustness contract: a missing file, a non-dict top level, a
    # non-list hook group, and hook entries that are the wrong shape entirely
    # must all be skipped rather than raising -- `stop` fails open on this,
    # never crashes.
    def test_configured_hooks_tolerates_malformed_shapes(self):
        shapes = [
            "{not json",
            "[]",
            json.dumps({"hooks": []}),
            json.dumps({"hooks": {"Stop": "x"}}),
            json.dumps(
                {
                    "hooks": {
                        "PostToolUse": [
                            "oops",
                            3,
                            {"hooks": "nope"},
                            {"hooks": [{"command": 5}]},
                        ]
                    }
                }
            ),
        ]
        for shape in shapes:
            with self.subTest(shape=shape[:40]):
                self._write("settings.json", shape)
                (self.claude_dir / "settings.local.json").unlink(missing_ok=True)
                commands, scripts = self.hook._configured_hooks(self.claude_dir, ["C:/proj"])
                self.assertEqual(commands, frozenset())
                self.assertEqual(scripts, frozenset())

    # F: item 3's docstring claimed `pyw.exe` (the windowed Python launcher)
    # already matched the same way `py.exe` does, but the python branch only
    # ever checked the literal `py.exe`/`_PYTHON_IMAGE_RE`, which does not
    # cover `pyw.exe` -- the windowed launcher never got the version-selector
    # skip at all. Must fail against the pre-fix baseline.
    def test_windowed_launcher_with_version_selector_matches(self):
        self._write("settings.json", SETTINGS.read_text(encoding="utf-8"))
        project_dir = "C:/Users/Administrator/PycharmProjects/hero-siege-offline-toolkit"
        commands, scripts = self.hook._configured_hooks(self.claude_dir, [project_dir])
        cmdline = (
            r"C:\WINDOWS\pyw.exe -3 "
            r"C:/Users/Administrator/PycharmProjects/hero-siege-offline-toolkit/.claude/hooks/decompiled_output.py"
        )
        self.assertTrue(self.hook._is_hook_invocation("pyw.exe", cmdline, commands, scripts))

    # Negative pair: the version selector is only a launcher's own leading
    # argument (`py.exe`/`pyw.exe`) -- on a `python*.exe` interpreter, `-3`
    # is an option and must keep failing the match, deliberately strictly.
    def test_version_selector_on_python_image_does_not_match(self):
        self._write("settings.json", SETTINGS.read_text(encoding="utf-8"))
        project_dir = "C:/Users/Administrator/PycharmProjects/hero-siege-offline-toolkit"
        commands, scripts = self.hook._configured_hooks(self.claude_dir, [project_dir])
        cmdline = (
            r"C:\WINDOWS\pythonw.exe -3 "
            r"C:/Users/Administrator/PycharmProjects/hero-siege-offline-toolkit/.claude/hooks/decompiled_output.py"
        )
        self.assertFalse(
            self.hook._is_hook_invocation("pythonw.exe", cmdline, commands, scripts)
        )


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
        # image is an allowlisted dev tool (R1-A) so this test still exercises
        # the raw-PID logic below, not the image filter added on top of it.
        proc = {"pid": 100, "ppid": 50, "creation": 500, "image": "python.exe"}
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
        # image is an allowlisted dev tool (R1-A); the unrelated-image case is
        # test_detached_orphan_with_unrelated_image_is_not_admitted below.
        proc = {"pid": 100, "ppid": 50, "creation": 500, "image": "python.exe"}
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

    # F2/R1-B item 1: `cmd_post` must capture each new pid's command line
    # before doing anything slow (loading the ledger, walking every admission
    # rule), so a short-lived sibling hook hop is not read after it has
    # already exited. `_capture_new` is the function that does the capturing:
    # it drops a pid that is no longer alive by the time it is checked from
    # `alive` (the admission-candidate set) -- but it must still keep that
    # pid's own command line in `cmdlines` when the line itself was readable,
    # since that line is exactly what lets `_is_hook_chain` recognise a
    # since-exited sibling hook hop as a hook chain rather than a leftover.
    def test_capture_new_drops_exited_process(self):
        new_procs = {10: {"pid": 10, "creation": 100}, 20: {"pid": 20, "creation": 200}}
        with mock.patch.object(
            self.hook, "_process_identity",
            side_effect=lambda pid: (new_procs[pid]["creation"], f"cmd{pid}"),
        ), mock.patch.object(
            self.hook, "_is_still_active", side_effect=lambda pid: pid == 10
        ):
            alive, cmdlines = self.hook._capture_new(new_procs)
        self.assertNotIn(20, alive)
        self.assertEqual(cmdlines[20], "cmd20")

    # Positive pair: a pid still alive when checked keeps its captured line
    # too, and is also a member of `alive` (unlike pid 20 above, which is
    # kept in `cmdlines` but dropped from `alive`).
    def test_capture_new_keeps_live_process_with_command_line(self):
        new_procs = {10: {"pid": 10, "creation": 100}, 20: {"pid": 20, "creation": 200}}
        with mock.patch.object(
            self.hook, "_process_identity",
            side_effect=lambda pid: (new_procs[pid]["creation"], f"cmd{pid}"),
        ), mock.patch.object(
            self.hook, "_is_still_active", side_effect=lambda pid: pid == 10
        ):
            alive, cmdlines = self.hook._capture_new(new_procs)
        self.assertEqual(alive, {10})
        self.assertEqual(cmdlines[10], "cmd10")

    # A pid whose command line could not be read at all (`_process_identity`
    # returned a `None` line) is captured as `None` in `cmdlines` -- still a
    # key, just not a trustworthy one -- whether or not it is still alive.
    def test_capture_new_drops_unreadable_command_line(self):
        new_procs = {10: {"pid": 10, "creation": 100}}
        with mock.patch.object(
            self.hook, "_process_identity", return_value=(100, None)
        ), mock.patch.object(self.hook, "_is_still_active", return_value=True):
            alive, cmdlines = self.hook._capture_new(new_procs)
        self.assertEqual(alive, {10})
        self.assertIn(10, cmdlines)
        self.assertIsNone(cmdlines[10])

    # R2-4: a pid can be recycled between `snapshot()`'s post read (which
    # supplied `new_procs[pid]["creation"]`) and this function's own
    # `_process_identity` read a moment later -- if the PID has since been
    # reused by an unrelated process, the captured line must not be
    # attributed to the old identity. Must fail against 6f536a6, which never
    # read a creation time here at all.
    def test_capture_new_discards_command_line_on_creation_mismatch(self):
        new_procs = {10: {"pid": 10, "creation": 100}}
        with mock.patch.object(
            self.hook, "_process_identity", return_value=(999, "cmd10")  # recycled: != 100
        ), mock.patch.object(self.hook, "_is_still_active", return_value=True):
            alive, cmdlines = self.hook._capture_new(new_procs)
        self.assertEqual(alive, {10})  # still a live admission candidate
        self.assertIn(10, cmdlines)  # captured, but...
        self.assertIsNone(cmdlines[10])  # ...not trusted

    # R1-A: rule (b) is narrowed to a named allowlist of images a session
    # plausibly starts itself (`DETACHED_ORPHAN_IMAGES`), after a live Stop on
    # 2026-09-16 15:05 attributed two `DiscordSystemHelper.exe` orphans to this
    # session -- Discord's own short-lived relaunch helper happened to die
    # inside this session's call window, and timing alone (the rest of rule
    # (b)) cannot tell that apart from a real leftover. This must fail against
    # the code as it stood before R1-A, since that code admitted any orphan
    # whose parent was truly gone regardless of image.
    def test_detached_orphan_with_unrelated_image_is_not_admitted(self):
        proc = {"pid": 100, "ppid": 50, "creation": 500, "image": "DiscordSystemHelper.exe"}
        post_snap = {}
        pre_snap = {}
        post_raw_pids = set()
        pre_raw_pids = set()
        self.assertFalse(
            self.hook._is_orphan_admissible(
                proc, post_snap, pre_snap, post_raw_pids, pre_raw_pids
            )
        )

    # PR #59 review: the reused-PID branch must ask the raw PID set, like its
    # sibling does. An unopenable parent (a SYSTEM service) that existed at
    # `pre` is absent from `pre_snap`, so checking `pre_snap` made its child
    # look like a real orphan once an openable process reused that PID.
    def test_reused_pid_of_unopenable_pre_parent_is_not_admitted(self):
        proc = {"pid": 100, "ppid": 50, "creation": 500, "image": "python.exe"}
        post_snap = {50: {"pid": 50, "ppid": 1, "creation": 900, "image": "x.exe"}}
        self.assertFalse(
            self.hook._is_orphan_admissible(proc, post_snap, {}, {50}, {50})
        )

    # Positive pair: the same reused PID, when nothing held it at `pre`, still
    # means the launcher was born and died inside the call -- admitted.
    def test_reused_pid_of_parent_born_during_call_is_admitted(self):
        proc = {"pid": 100, "ppid": 50, "creation": 500, "image": "python.exe"}
        post_snap = {50: {"pid": 50, "ppid": 1, "creation": 900, "image": "x.exe"}}
        self.assertTrue(
            self.hook._is_orphan_admissible(proc, post_snap, {}, {50}, set())
        )

    # PR #59 review: an empty `pre` snapshot (a failed Toolhelp32 call) must not
    # become a baseline, or every live process on the machine looks new at
    # `post`. `cmd_pre` writes nothing, so `cmd_post` takes its no-baseline path.
    def test_empty_pre_snapshot_is_not_used_as_baseline(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        payload = {"session_id": "s", "tool_use_id": "call1"}
        everything = {7: {"pid": 7, "ppid": 3, "creation": 5, "image": "node.exe"}}
        with mock.patch.dict(os.environ, {"HSTK_PROC_LEDGER_DIR": tmp}):
            with mock.patch.object(self.hook, "snapshot", return_value=({}, set())):
                self.hook.cmd_pre(payload)
            sdir = self.hook._session_dir("s")
            self.assertFalse((sdir / "pre-call1.json").exists())
            with mock.patch.object(self.hook, "snapshot", return_value=(everything, {7})):
                self.hook.cmd_post(payload)
            self.assertEqual(json.loads((sdir / "post-call1.json").read_text()), {})

    # Positive pair: a non-empty `pre` snapshot is still written as the baseline.
    def test_nonempty_pre_snapshot_is_written(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        procs = {7: {"pid": 7, "ppid": 3, "creation": 5, "image": "node.exe"}}
        with mock.patch.dict(os.environ, {"HSTK_PROC_LEDGER_DIR": tmp}):
            with mock.patch.object(self.hook, "snapshot", return_value=(procs, {7})):
                self.hook.cmd_pre({"session_id": "s", "tool_use_id": "call1"})
            self.assertTrue((self.hook._session_dir("s") / "pre-call1.json").exists())

    # PR #59 review: without an explicit restype, ctypes truncates the HANDLE
    # these calls return to a c_int, so a real INVALID_HANDLE_VALUE (-1 as a
    # c_int) never equals the pointer-width constant and the failure guard in
    # `_iter_processes` cannot fire.
    @unittest.skipUnless(sys.platform == "win32", "Win32 ctypes prototypes")
    def test_handle_returning_calls_use_pointer_width_restype(self):
        from ctypes import wintypes

        self.assertIs(self.hook.kernel32.CreateToolhelp32Snapshot.restype, wintypes.HANDLE)
        self.assertIs(self.hook.kernel32.OpenProcess.restype, wintypes.HANDLE)

    # R2-1: rule (b)'s image check must accept every Python interpreter name
    # the hook-invocation matcher itself already accepts (`python[0-9.]*w?.exe`),
    # plus `py.exe`/`pyw.exe` -- not just the literal `python.exe`/`pythonw.exe`
    # names `DETACHED_ORPHAN_IMAGES` used to list on its own. Must fail against
    # 6f536a6, which only recognised those two literal names.
    def test_orphan_admission_admits_versioned_and_windowed_python_images(self):
        for image in ("python3.exe", "python3.14.exe", "pyw.exe", "py.exe", "pythonw.exe"):
            with self.subTest(image=image):
                proc = {"pid": 100, "ppid": 50, "creation": 500, "image": image}
                self.assertTrue(
                    self.hook._is_orphan_admissible(proc, {}, {}, set(), set())
                )

    # Negative pair: a name that merely starts with "python" but is not one
    # of the interpreter's own image names (a typosquat, or an unrelated
    # tool) must not be admitted -- the shared pattern is anchored, not a
    # prefix match.
    def test_orphan_admission_rejects_python_lookalike_image(self):
        proc = {"pid": 100, "ppid": 50, "creation": 500, "image": "pythonista.exe"}
        self.assertFalse(
            self.hook._is_orphan_admissible(proc, {}, {}, set(), set())
        )

    # `_is_hook_chain` must prefer a captured command line over a fresh
    # `_command_line` read -- by the time `_admit_new` walks the chain, a
    # short-lived sibling hop's own `_command_line(pid)` can return `None`
    # (the process has already exited), which would wrongly stop looking
    # like a hook and admit the whole sibling chain as a leftover.
    def test_hook_chain_uses_captured_command_line(self):
        snap = {
            10: {"pid": 10, "ppid": 1, "creation": 100, "image": "bash.exe"},
            11: {"pid": 11, "ppid": 10, "creation": 200, "image": "python.exe"},
        }
        outer_bash_line = (
            r'"C:\Program Files\Git\bin\bash.exe" -c '
            r'"py -3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/decompiled_output.py\""'
        )
        cmdlines = {10: outer_bash_line}
        with mock.patch.object(self.hook, "_command_line", return_value=None):
            self.assertTrue(self.hook._is_hook_chain(11, snap, 1, cmdlines))

    # Negative pair: without the captured line, `_command_line` returning
    # `None` for the dead hop means nothing in the chain looks like a hook,
    # so the sibling is (wrongly, absent F2) admitted as a leftover.
    def test_hook_chain_without_captured_line_is_admitted(self):
        snap = {
            10: {"pid": 10, "ppid": 1, "creation": 100, "image": "bash.exe"},
            11: {"pid": 11, "ppid": 10, "creation": 200, "image": "python.exe"},
        }
        with mock.patch.object(self.hook, "_command_line", return_value=None):
            self.assertFalse(self.hook._is_hook_chain(11, snap, 1, {}))

    # A: R2-4 reproduced. A pid whose captured line was discarded on a
    # creation mismatch must not be re-read from `_is_hook_chain` -- that
    # re-read is exactly the recycled line R2-4 meant to discard. Patching
    # both `_command_line`/`_creation_time` (what the pre-fix `_capture_new`
    # calls) and `_process_identity` (what the fixed one calls) makes this
    # one test meaningful against both trees: on the baseline, the mismatch
    # leaves pid 11 out of `cmdlines` entirely, so `_is_hook_chain`'s
    # `cmdlines and cur in cmdlines` falls through to a fresh, recycled
    # `_command_line` read. Must fail against the pre-fix baseline.
    def test_hook_chain_does_not_reread_line_discarded_on_creation_mismatch(self):
        outer_bash_line = (
            r'"C:\Program Files\Git\bin\bash.exe" -c '
            r'"py -3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/decompiled_output.py\""'
        )
        new_procs = snap = {
            11: {"pid": 11, "ppid": 1, "image": "bash.exe", "creation": 100},
        }
        with mock.patch.object(
            self.hook, "_hooks",
            return_value=(
                frozenset({'py -3 "$CLAUDE_PROJECT_DIR/.claude/hooks/decompiled_output.py"'}),
                frozenset(),
            ),
        ), mock.patch.object(
            self.hook, "_command_line", return_value=outer_bash_line
        ) as command_line_mock, mock.patch.object(
            self.hook, "_creation_time", return_value=999
        ), mock.patch.object(
            self.hook, "_process_identity", create=True,
            return_value=(999, outer_bash_line),  # recycled: != new_procs[11]["creation"]
        ), mock.patch.object(
            self.hook, "_is_still_active", return_value=True
        ):
            _alive, cmdlines = self.hook._capture_new(new_procs)
            command_line_mock.reset_mock()
            result = self.hook._is_hook_chain(11, snap, 1, cmdlines)
        self.assertFalse(result)
        self.assertEqual(command_line_mock.call_count, 0)

    # B: positive pair. The same shape, but the identity read's creation
    # matches -- the captured line is trustworthy, and `_is_hook_chain` must
    # recognise it as a hook invocation without ever re-reading it.
    def test_hook_chain_uses_line_captured_with_matching_identity(self):
        outer_bash_line = (
            r'"C:\Program Files\Git\bin\bash.exe" -c '
            r'"py -3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/decompiled_output.py\""'
        )
        new_procs = snap = {
            11: {"pid": 11, "ppid": 1, "image": "bash.exe", "creation": 100},
        }
        with mock.patch.object(
            self.hook, "_hooks",
            return_value=(
                frozenset({'py -3 "$CLAUDE_PROJECT_DIR/.claude/hooks/decompiled_output.py"'}),
                frozenset(),
            ),
        ), mock.patch.object(
            self.hook, "_command_line", return_value=outer_bash_line
        ), mock.patch.object(
            self.hook, "_creation_time", return_value=100
        ), mock.patch.object(
            self.hook, "_process_identity", create=True,
            return_value=(100, outer_bash_line),  # matches new_procs[11]["creation"]
        ), mock.patch.object(
            self.hook, "_is_still_active", return_value=True
        ):
            _alive, cmdlines = self.hook._capture_new(new_procs)
            result = self.hook._is_hook_chain(11, snap, 1, cmdlines)
        self.assertTrue(result)

    # C: `_process_identity` reads both values through one handle. Its
    # creation time must agree with `_creation_time`'s own (separate-handle)
    # read of the same live process, and its command line must be readable.
    def test_process_identity_reads_live_process(self):
        pid = os.getpid()
        creation, line = self.hook._process_identity(pid)
        self.assertIsNotNone(creation)
        self.assertEqual(creation, self.hook._creation_time(pid))
        self.assertIsInstance(line, str)
        self.assertTrue(line)

    # Negative pair: an invalid pid fails `OpenProcess` outright, so both
    # values come back `None` rather than one succeeding and the other not.
    def test_process_identity_of_invalid_pid_is_none(self):
        self.assertEqual(self.hook._process_identity(0), (None, None))


if __name__ == "__main__":
    unittest.main()
