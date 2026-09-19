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
import io
import json
import os
import re
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


def _normalize_node_timing(text):
    """`node --test`'s own output embeds each run's wall-clock time, which
    genuinely differs between two invocations of the same test -- an
    equivalence check must not fail on that noise."""
    return re.sub(r"\(\d+(?:\.\d+)?ms\)|duration_ms:?\s+\d+(?:\.\d+)?", "<t>", text)


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
        # The real settings.json, so the rig is laid out like the toolkit.
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
    # The first version of this hook matched whole file contents, and
    # matches already sit in committed files
    # (ForgePact/docs/pet-quest-collector-c-research.md and
    # ForgePact/plugin/ModuleMain.cpp -- see GrandfatheredWholeFileInventory
    # below, which keeps this inventory honest instead of restating a count).
    # Appending a paragraph to either of them made every subsequent tool call
    # exit 2 until someone set HSTK_SKIP_HOOKS=1 -- the exact outcome the
    # docstring says it avoids. These two tests are a pair: the hook must
    # stop wedging, and grandfathering must not become a loophole.

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


class GrandfatheredWholeFileInventory(unittest.TestCase):
    """Pins the whole-file-match inventory `decompiled_output.py`'s own
    docstring and the comment above `TestDecompiledOutput`'s "added lines
    only" tests describe in prose, to a checked fact -- see the hook's
    "Added lines only, and why that is not a loophole" section. Runs the
    hook's own `SIGNATURES`, via its own `inspect`, over whole file contents
    (not added lines: the claim is about what already sits in committed
    files, which is exactly what the hook itself no longer reads) of the
    hub tree at HEAD (excluding `EXCLUDED_PREFIXES`) plus ForgePact and
    HS-Offline-Tracker at the revisions the hub's own gitlinks record.

    Skips, never fails, when a submodule is not checked out or its object
    store lacks the recorded revision -- mirroring
    tests/test_yytoolkit_patch_series.py's ForgePactPinRealRevisionControls.
    The hub tree's own share of the inventory is asserted separately and
    never skips, so a hub-only checkout (CI) still checks it.
    A change here means the docstring/comment prose must change with it, and
    both cite this test by name instead of repeating a number that has
    already been wrong twice for two different reasons.
    """

    #: Measured 2026-09-19 against hub origin/main 3758af0, ForgePact
    #: f5a3515, HS-Offline-Tracker 9da9569.
    EXPECTED = frozenset({
        "ForgePact/docs/pet-quest-collector-c-research.md",
        "ForgePact/plugin/ModuleMain.cpp",
    })

    SUBMODULES = ("ForgePact", "HS-Offline-Tracker")

    @classmethod
    def setUpClass(cls):
        cls.hook = _load_hook_module("decompiled_output")

    def _recorded_revision(self, sub):
        result = subprocess.run(
            ["git", "ls-tree", "HEAD", sub], cwd=REPO, capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        fields = result.stdout.split()
        return fields[2] if len(fields) >= 3 else None

    def _matches(self, display, blob_bytes):
        text = blob_bytes.decode("utf-8", "replace")
        lines = list(enumerate(text.splitlines(), start=1))
        return bool(self.hook.inspect(display, lines))

    def _scan_hub_tree(self):
        found = set()
        listing = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD"],
            cwd=REPO, capture_output=True, text=True, check=True)
        for rel in listing.stdout.splitlines():
            if rel.startswith(self.hook.EXCLUDED_PREFIXES):
                continue
            if not rel.endswith(self.hook.WATCHED_SUFFIXES):
                continue
            blob = subprocess.run(
                ["git", "show", f"HEAD:{rel}"], cwd=REPO, capture_output=True)
            if blob.returncode != 0:
                continue
            if self._matches(rel, blob.stdout):
                found.add(rel)
        return found

    def _scan_submodule(self, sub):
        subroot = REPO / sub
        if not (subroot / ".git").exists():
            self.skipTest(f"{sub}/ is not checked out")
        rev = self._recorded_revision(sub)
        if not rev:
            self.skipTest(f"could not read the {sub} gitlink with `git ls-tree HEAD {sub}`")
        listing = subprocess.run(
            ["git", "-C", str(subroot), "ls-tree", "-r", "--name-only", rev],
            capture_output=True, text=True)
        if listing.returncode != 0:
            self.skipTest(
                f"{sub}'s local object store does not have {rev[:12]} (the hub's recorded "
                f"gitlink); fetch it there to run this control")
        found = set()
        for rel in listing.stdout.splitlines():
            if not rel.endswith(self.hook.WATCHED_SUFFIXES):
                continue
            blob = subprocess.run(
                ["git", "-C", str(subroot), "show", f"{rev}:{rel}"], capture_output=True)
            if blob.returncode != 0:
                continue
            display = f"{sub}/{rel}"
            if self._matches(display, blob.stdout):
                found.add(display)
        return found

    def test_the_hub_tree_itself_carries_no_whole_file_match(self):
        # Needs no submodule, so it runs -- and can fail -- in a hub-only
        # checkout such as CI, where the combined test below skips before
        # its assertion is reached.
        expected_in_hub = {p for p in self.EXPECTED
                           if not p.startswith(tuple(f"{s}/" for s in self.SUBMODULES))}
        found = self._scan_hub_tree()
        self.assertEqual(
            found, expected_in_hub,
            f"whole-file decompiled-output signature matches in the hub tree: "
            f"{sorted(found)}; expected: {sorted(expected_in_hub)}")

    def test_the_grandfathered_inventory_is_exactly_two_paths(self):
        found = self._scan_hub_tree()
        for sub in self.SUBMODULES:
            found |= self._scan_submodule(sub)
        self.assertEqual(
            found, self.EXPECTED,
            f"decompiled_output.py's docstring and the comment above "
            f"TestDecompiledOutput's \"added lines only\" tests both cite an exact "
            f"inventory of whole-file matches already sitting in committed files. "
            f"Found: {sorted(found)}; expected: {sorted(self.EXPECTED)}. If this "
            f"genuinely changed, update the docstring and the comment together with "
            f"this EXPECTED set, citing this test by name rather than a bare count.")


class TestPostToolUseDispatcher(HookTestCase):
    """`.claude/hooks/post_tool_use.py`: one process running the four tree
    checks instead of four independent `py -3` launches. Each pair here
    mirrors the positive/negative shape this file opens with -- a clean tree
    stays silent, and each check's own violation still blocks when reached
    through the dispatcher, not just when the check runs standalone.
    """

    HOOK = "post_tool_use.py"

    # -- negative control -----------------------------------------------

    def test_clean_tree_is_silent(self):
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    # -- one positive control per check, run through the dispatcher -----

    def test_catalog_violation_blocks_through_it(self):
        self.rig.write("tools/minisign.py", "import sys\nprint('BAD SIGNATURE')\nsys.exit(1)\n")
        self.rig.write("catalog/catalog.json", "changed\n")
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("catalog/catalog.json no longer verifies", result.stderr)

    def test_tauri_violation_blocks_through_it(self):
        self.rig.write(
            "hub/src-tauri/src/bad.rs",
            "#[tauri::command(async)]\n"
            "fn wrong(app: AppHandle) -> Result<(), String> {\n"
            "    let _ = tauri::async_runtime::block_on(thing.check());\n"
            "    Ok(())\n}\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Tauri command rules violated", result.stderr)

    def test_hub_frontend_violation_blocks_through_it(self):
        self.rig.write("hub/src/thing.js", "export const a = 2;\n")
        self.rig.write(
            "hub/src/thing.test.js",
            "import test from 'node:test';\n"
            "import assert from 'node:assert';\n"
            "test('fails', () => { assert.equal(1, 2); });\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("hub's frontend tests fail", result.stderr)

    def test_decompiled_output_violation_blocks_through_it(self):
        self.rig.write("docs/notes.md", "clean line\n    iVar1 = FUN_00b489070(param_1);\n")
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Decompiled or disassembled game source", result.stderr)

    # -- tool_name gating (the two old matchers folded into one) --------

    def test_edit_tool_runs_the_tree_checks(self):
        self.rig.write(
            "hub/src-tauri/src/bad.rs",
            "#[tauri::command(async)]\n"
            "fn wrong(app: AppHandle) -> Result<(), String> {\n"
            "    let _ = tauri::async_runtime::block_on(thing.check());\n"
            "    Ok(())\n}\n",
        )
        result = self.rig.run(self.HOOK, payload={"tool_name": "Edit"})
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_read_tool_runs_nothing(self):
        self.rig.write(
            "hub/src-tauri/src/bad.rs",
            "#[tauri::command(async)]\n"
            "fn wrong(app: AppHandle) -> Result<(), String> {\n"
            "    let _ = tauri::async_runtime::block_on(thing.check());\n"
            "    Ok(())\n}\n",
        )
        result = self.rig.run(self.HOOK, payload={"tool_name": "Read"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_malformed_stdin_still_runs_the_tree_checks(self):
        """A `tool_name` the dispatcher cannot read runs the tree checks
        anyway -- the fail-safe direction the old per-tool matcher also took
        (it does not see a malformed payload as excluding anything)."""
        environ = dict(os.environ)
        environ.pop("HSTK_SKIP_HOOKS", None)
        result = subprocess.run(
            [sys.executable, str(self.rig.root / ".claude" / "hooks" / self.HOOK)],
            cwd=self.rig.root,
            input="{not json",
            capture_output=True,
            text=True,
            env=environ,
        )
        self.assertEqual(result.returncode, 0, result.stderr)  # clean tree

    def test_skip_hooks_silences_the_tree_checks(self):
        self.rig.write(
            "hub/src-tauri/src/bad.rs",
            "#[tauri::command(async)]\n"
            "fn wrong(app: AppHandle) -> Result<(), String> {\n"
            "    let _ = tauri::async_runtime::block_on(thing.check());\n"
            "    Ok(())\n}\n",
        )
        result = self.rig.run(self.HOOK, env={"HSTK_SKIP_HOOKS": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)

    # -- a crash in one check must not mask, or block for, the others ---

    def test_crash_in_one_check_does_not_mask_a_real_violation(self):
        self.rig.write(
            ".claude/hooks/hub_frontend_tests.py",
            "def check(payload, tree):\n    raise RuntimeError('boom')\n",
        )
        self.rig.write(
            "hub/src-tauri/src/bad.rs",
            "#[tauri::command(async)]\n"
            "fn wrong(app: AppHandle) -> Result<(), String> {\n"
            "    let _ = tauri::async_runtime::block_on(thing.check());\n"
            "    Ok(())\n}\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 2, result.stderr)  # the real violation still blocks
        self.assertIn("hub_frontend_tests crashed", result.stderr)
        self.assertIn("RuntimeError", result.stderr)
        self.assertIn("Tauri command rules violated", result.stderr)

    def test_crash_alone_is_non_blocking(self):
        """A check's own bug is an error (rc 1), not a block (rc 2) -- it must
        never gain the enforcement power of a real finding."""
        self.rig.write(
            ".claude/hooks/hub_frontend_tests.py",
            "def check(payload, tree):\n    raise RuntimeError('boom')\n",
        )
        result = self.rig.run(self.HOOK)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("hub_frontend_tests crashed", result.stderr)


class TestDispatcherEquivalence(HookTestCase):
    """Permanent equivalence check, not a one-off measurement: the four tree
    checks run independently (settings.json's old topology, the order it ran
    them in) must produce byte-identical stderr and the same exit code as
    running them through `post_tool_use.py`. This is what keeps the
    `check(payload, tree)` refactor and the dispatcher's own concatenation
    from drifting silently apart from what each script's standalone `main()`
    still does.
    """

    ORDER = (
        "catalog_signature.py",
        "tauri_command_guard.py",
        "hub_frontend_tests.py",
        "decompiled_output.py",
    )

    def _run_originals(self, payload=None, env=None):
        out, rc = "", 0
        for hook in self.ORDER:
            result = self.rig.run(hook, payload=payload, env=env)
            self.assertEqual(result.stdout, "", (hook, result.stdout))
            out += result.stderr
            rc = max(rc, result.returncode)
        return rc, out

    def _run_dispatcher(self, payload=None, env=None):
        result = self.rig.run("post_tool_use.py", payload=payload, env=env)
        self.assertEqual(result.stdout, "", result.stdout)
        return result.returncode, result.stderr

    def _assert_equivalent(self, payload=None, env=None):
        rc_o, err_o = self._run_originals(payload, env)
        rc_p, err_p = self._run_dispatcher(payload, env)
        self.assertEqual(
            (rc_o, _normalize_node_timing(err_o)), (rc_p, _normalize_node_timing(err_p))
        )
        return rc_o

    def test_clean_tree_is_equivalent(self):
        self.assertEqual(self._assert_equivalent(), 0)

    def test_all_violations_at_once_is_equivalent(self):
        self.rig.write(
            "hub/src-tauri/src/bad.rs",
            "#[tauri::command]\nfn bad(app: AppHandle) {\n"
            "    tauri::async_runtime::block_on(x());\n}\n",
        )
        self.rig.write("hub/src/thing.js", "export const a = 2;\n")
        self.rig.write(
            "hub/src/thing.test.js",
            "import test from 'node:test';\n"
            "import assert from 'node:assert';\n"
            "test('fails', () => { assert.equal(1, 2); });\n",
        )
        self.rig.write("catalog/catalog.json", "changed\r\n")
        self.rig.write("tools/minisign.py", "import sys\nprint('BAD SIGNATURE')\nsys.exit(1)\n")
        self.rig.write("docs/notes.md", "clean line\n    iVar1 = FUN_00b489070(param_1);\n")
        self.rig.write("docs/new note.md", "pushglb.v self.thing\n")
        self.assertEqual(self._assert_equivalent(), 2)

    def test_hstk_skip_hooks_is_equivalent(self):
        self.rig.write(
            "hub/src-tauri/src/bad.rs",
            "#[tauri::command]\nfn bad(app: AppHandle) {\n"
            "    tauri::async_runtime::block_on(x());\n}\n",
        )
        self.assertEqual(self._assert_equivalent(env={"HSTK_SKIP_HOOKS": "1"}), 0)

    def test_malformed_stdin_is_equivalent(self):
        environ = dict(os.environ)
        environ.pop("HSTK_SKIP_HOOKS", None)
        out_o, rc_o = "", 0
        for hook in self.ORDER:
            result = subprocess.run(
                [sys.executable, str(self.rig.root / ".claude" / "hooks" / hook)],
                cwd=self.rig.root, input="{not json",
                capture_output=True, text=True, env=environ,
            )
            out_o += result.stderr
            rc_o = max(rc_o, result.returncode)
        result_p = subprocess.run(
            [sys.executable, str(self.rig.root / ".claude" / "hooks" / "post_tool_use.py")],
            cwd=self.rig.root, input="{not json",
            capture_output=True, text=True, env=environ,
        )
        self.assertEqual((rc_o, out_o), (result_p.returncode, result_p.stderr))


class TestDispatcherEquivalenceInSubmodules(HookTestCase):
    """The submodule-scanning half of the equivalence claim: a listing inside
    a dirty submodule, and a submodule whose pointer moved but whose own tree
    is clean (the case `TreeState.dirty_submodules` must not over- or
    under-report against `decompiled_output.py`'s own `dirty_submodules`).
    """

    def setUp(self):
        super().setUp()
        self.origin = Path(tempfile.mkdtemp(prefix="hstk-sub-equiv-"))
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

    ORDER = TestDispatcherEquivalence.ORDER

    def _assert_equivalent(self):
        out_o, rc_o = "", 0
        for hook in self.ORDER:
            result = self.rig.run(hook)
            out_o += result.stderr
            rc_o = max(rc_o, result.returncode)
        result_p = self.rig.run("post_tool_use.py")
        self.assertEqual((rc_o, out_o), (result_p.returncode, result_p.stderr))
        return rc_o

    def test_listing_inside_dirty_submodule_is_equivalent(self):
        (self.sub / "docs" / "research.md").write_bytes(
            b"the collect path:\n\n    iVar1 = FUN_00b489070(param_1);\n"
        )
        self.assertEqual(self._assert_equivalent(), 2)

    def test_submodule_pointer_moved_but_clean_is_equivalent(self):
        (self.sub / "docs" / "research.md").write_bytes(b"clean v2\n")
        _git("-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-qam", "bump", cwd=self.sub)
        self.assertEqual(self._assert_equivalent(), 0)


if __name__ == "__main__":
    unittest.main()
