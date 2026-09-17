"""`.claude/skills/workorder/round_delta.py` is the instrument `/workorder`'s
delta-scoped reviewers depend on (SPEC.md § "Delta-scoped reviewers"): a round
that only touched one file must hand a re-run reviewer that one file, not the
whole cumulative diff. `AGENTS.md` § "Prove the Instrument Before Trusting a
Negative Result" is why this suite exists as pairs rather than single
assertions -- an instrument that reports an empty delta for every round looks
identical to one that is scoping correctly, right up until a reviewer misses
something a round actually changed.

The key property under test is not "does it see changes" (any diff would do
that); it is "does it see *only this round's* changes" -- a file dirty before
the round started, and untouched by it, must drop out of the delta even
though it is still dirty relative to `HEAD`. That is what the
already-dirty-file and changed-then-restored tests below pin down.

Every test builds a throwaway git repository in the system temp directory
(not the session scratchpad -- `git init` there fails with `Filename too
long`, the same reason `tests/test_claude_hooks.py` uses temp), and drives
`round_delta.py` as the subprocess `settings.json`/the driver actually
invoke, not by importing its functions.
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / ".claude" / "skills" / "workorder" / "round_delta.py"


def _git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )


class DeltaRepo:
    """A throwaway git repository `round_delta.py` runs against."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="hstk-workorder-"))
        _git("init", "-q", cwd=self.root)
        _git("config", "user.email", "t@example.com", cwd=self.root)
        _git("config", "user.name", "T", cwd=self.root)
        self.write("README.md", b"base\n")
        _git("add", "-A", cwd=self.root)
        _git("commit", "-qm", "base", cwd=self.root)

    def write(self, rel, data):
        """Always binary -- a text-mode write would itself defeat the CRLF
        test below by normalizing line endings before they ever reach the
        script under test."""
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            data = data.encode("utf-8")
        path.write_bytes(data)

    def commit(self, message="commit"):
        _git("add", "-A", cwd=self.root)
        _git("commit", "-qm", message, cwd=self.root)

    def run(self, command, slug="wo", round_="0", root=None):
        return subprocess.run(
            [
                sys.executable, str(SCRIPT), command, slug, round_,
                "--root", str(root if root is not None else self.root),
            ],
            capture_output=True, text=True,
        )

    def snapshot_path(self, slug="wo", round_="0"):
        return self.root / ".claude" / "workorders" / ".rounds" / slug / f"round-{round_}.json"

    def destroy(self):
        shutil.rmtree(self.root, ignore_errors=True)


class RoundDeltaTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = DeltaRepo()
        self.addCleanup(self.repo.destroy)


class TestSnapshotAndDelta(RoundDeltaTestCase):
    # Negative control: an unmodified tree between snapshot and delta yields
    # nothing. Every other test in this file is meaningless without this one
    # passing -- it proves the instrument is not simply always non-empty.
    def test_no_change_is_empty_delta(self):
        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)
        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        self.assertEqual(delta.stdout.strip(), "")

    def test_snapshot_prints_the_snapshot_name(self):
        snap = self.repo.run("snapshot", slug="wo", round_="3")
        self.assertEqual(snap.returncode, 0, snap.stderr)
        printed = snap.stdout.strip()
        self.assertEqual(printed, ".claude/workorders/.rounds/wo/round-3.json")
        self.assertTrue((self.repo.root / printed).exists())

    # Positive control: modified, new-untracked and deleted files are all
    # reported by one round.
    def test_modified_untracked_and_deleted_are_listed(self):
        self.repo.write("tracked.txt", b"one\n")
        self.repo.write("to_delete.txt", b"gone\n")
        self.repo.commit("add tracked and to_delete")

        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        self.repo.write("tracked.txt", b"one\ntwo\n")
        self.repo.write("new_untracked.txt", b"new\n")
        (self.repo.root / "to_delete.txt").unlink()

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        changed = set(delta.stdout.split())
        self.assertEqual(changed, {"tracked.txt", "new_untracked.txt", "to_delete.txt"})

    # The key property: a file dirty *before* the round's snapshot, and never
    # touched during it, is not part of the round's delta -- even though it
    # is still dirty relative to HEAD when `delta` runs. Scoping by whether a
    # file is dirty (rather than by whether its content changed since the
    # snapshot) would fail this test by reporting it every round.
    def test_pre_existing_dirty_file_untouched_is_not_listed(self):
        self.repo.write("already_dirty.txt", b"committed\n")
        self.repo.commit("add already_dirty")
        self.repo.write("already_dirty.txt", b"dirty before the round starts\n")

        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        # Nothing touches already_dirty.txt between snapshot and delta.
        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        self.assertEqual(delta.stdout.strip(), "")

    # Paired with the test above: a file the round *did* touch, but which
    # ends up byte-identical to what the snapshot recorded, also drops out.
    # This is what makes "hash the bytes" the right primitive instead of
    # "record that it changed" -- a revert during the round must not cost a
    # reviewer re-run.
    def test_changed_then_restored_to_snapshot_bytes_is_not_listed(self):
        self.repo.write("roundtrip.txt", b"committed\n")
        self.repo.commit("add roundtrip")
        self.repo.write("roundtrip.txt", b"dirty at snapshot time\n")

        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        self.repo.write("roundtrip.txt", b"something else entirely\n")
        self.repo.write("roundtrip.txt", b"dirty at snapshot time\n")  # back to snapshot bytes

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        self.assertEqual(delta.stdout.strip(), "")

    # A file added after the snapshot and then deleted before `delta` runs is
    # "present on only one side" from the opposite direction of the ordinary
    # add case -- exercises the `before.keys() | after.keys()` union rather
    # than only one dict's keys.
    def test_file_added_then_removed_before_delta_is_listed(self):
        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        self.repo.write("came_and_went.txt", b"brief\n")
        self.repo.commit("add came_and_went")
        (self.repo.root / "came_and_went.txt").unlink()

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        self.assertEqual(delta.stdout.strip(), "came_and_went.txt")

    def test_missing_snapshot_exits_3(self):
        delta = self.repo.run("delta", slug="never-snapshotted")
        self.assertEqual(delta.returncode, 3, delta.stdout)
        self.assertTrue(delta.stderr.strip())

    def test_corrupt_snapshot_exits_3(self):
        path = self.repo.snapshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 3, delta.stdout)
        self.assertTrue(delta.stderr.strip())

    # Bytes, not text: a signature-bearing catalog or a save file this
    # toolkit hashes for other purposes lives and dies by its exact bytes
    # (this worktree is CRLF -- the same hazard). If this script
    # ever read files in text mode, universal-newline translation would
    # silently normalize CRLF to LF before hashing.
    def test_crlf_content_hashes_as_raw_bytes(self):
        crlf_bytes = b"line one\r\nline two\r\n"
        self.repo.write("crlf.txt", crlf_bytes)

        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        recorded = json.loads(self.repo.snapshot_path().read_text(encoding="utf-8"))
        expected = hashlib.sha1(crlf_bytes).hexdigest()
        self.assertEqual(recorded["crlf.txt"], expected)
        # A text-mode read would have produced this (wrong) digest instead --
        # assert the two differ so a regression to text-mode reads fails loudly.
        lf_digest = hashlib.sha1(crlf_bytes.replace(b"\r\n", b"\n")).hexdigest()
        self.assertNotEqual(expected, lf_digest)


class TestSubmodulePrefixing(RoundDeltaTestCase):
    """`.gitmodules` path prefixing -- the one place state must reach outside
    the hub's own `git status`, per SPEC.md § "Delta-scoped reviewers"."""

    def setUp(self):
        super().setUp()
        self.origin = Path(tempfile.mkdtemp(prefix="hstk-workorder-sub-"))
        self.addCleanup(shutil.rmtree, self.origin, ignore_errors=True)
        _git("init", "-q", cwd=self.origin)
        _git("config", "user.email", "t@example.com", cwd=self.origin)
        _git("config", "user.name", "T", cwd=self.origin)
        (self.origin / "docs").mkdir()
        (self.origin / "docs" / "file.md").write_bytes(b"clean\n")
        _git("add", "-A", cwd=self.origin)
        _git("commit", "-qm", "base", cwd=self.origin)
        try:
            _git(
                "-c", "protocol.file.allow=always",
                "submodule", "add", "-q", self.origin.as_uri(), "Sub",
                cwd=self.repo.root,
            )
            _git("commit", "-qm", "add submodule", cwd=self.repo.root)
        except subprocess.CalledProcessError as exc:
            raise unittest.SkipTest(f"git submodule add unavailable: {exc.stderr}")
        self.sub = self.repo.root / "Sub"

    # Negative control: a clean, registered submodule contributes nothing.
    def test_clean_submodule_is_not_in_the_delta(self):
        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)
        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        self.assertEqual(delta.stdout.strip(), "")

    def test_dirty_file_in_submodule_is_prefixed_with_its_dir(self):
        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        (self.sub / "docs" / "file.md").write_bytes(b"dirty\n")
        (self.sub / "docs" / "new.md").write_bytes(b"new\n")

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        changed = set(delta.stdout.split())
        self.assertEqual(changed, {"Sub/docs/file.md", "Sub/docs/new.md"})

    # A dirty submodule pointer (the hub's own view of "the submodule has
    # uncommitted content") must not itself appear as a hub-level path --
    # `--ignore-submodules=all` on the hub-level status call is what this
    # pins down; without it the hub run would add a spurious "Sub" entry
    # alongside the prefixed file paths above.
    def test_submodule_pointer_itself_is_not_a_hub_level_path(self):
        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)
        (self.sub / "docs" / "file.md").write_bytes(b"dirty\n")
        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        changed = set(delta.stdout.split())
        self.assertNotIn("Sub", changed)


class TestUsageErrors(RoundDeltaTestCase):
    def test_slug_with_path_separator_exits_2(self):
        result = self.repo.run("snapshot", slug="../escape")
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_round_with_path_separator_exits_2(self):
        result = self.repo.run("snapshot", round_="../0")
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_non_numeric_round_exits_2(self):
        result = self.repo.run("snapshot", round_="zero")
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_unknown_command_exits_2(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "bogus", "wo", "0", "--root", str(self.repo.root)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2, result.stdout)


if __name__ == "__main__":
    unittest.main()
