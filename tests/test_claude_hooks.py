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

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / ".claude" / "hooks"

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

    def run(self, hook, payload=None, env=None):
        environ = dict(os.environ)
        environ.pop("HSTK_SKIP_HOOKS", None)
        environ.update(env or {})
        return subprocess.run(
            [sys.executable, str(self.root / ".claude" / "hooks" / hook)],
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


if __name__ == "__main__":
    unittest.main()
