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
        self.assertEqual(recorded["files"]["crlf.txt"], expected)
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

    # A commit *inside* the submodule (not just a dirty file) must still be
    # seen, prefixed with its dir -- and the hub's own commit bumping the
    # gitlink pointer to that new submodule commit must not itself add a bare
    # "Sub" entry, since the submodule's own diff already covers it.
    def test_commit_inside_submodule_reports_prefixed_path_hub_gitlink_not_listed(self):
        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        (self.sub / "docs" / "file.md").write_bytes(b"changed in submodule\n")
        _git("add", "-A", cwd=self.sub)
        _git("commit", "-qm", "change file.md", cwd=self.sub)
        _git("add", "-A", cwd=self.repo.root)
        _git("commit", "-qm", "bump Sub pointer", cwd=self.repo.root)

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        changed = set(delta.stdout.split())
        self.assertEqual(changed, {"Sub/docs/file.md"})


class TestCommitTracking(RoundDeltaTestCase):
    """Snapshot format v2 (`AGENTS.md` § "Prove the Instrument Before Trusting
    a Negative Result"): the hub's own `git status` at `delta` time cannot see
    a path that was clean at `snapshot`, then edited *and committed* during
    the round -- it is clean again by the time `delta` runs. Every test here
    pins one shape of that blindness down.

    `test_committed_modification_is_listed` is also the positive control that
    demonstrated the original defect: run by hand against the pre-fix script
    (a bare `git status --porcelain` diff with no head tracking), snapshot +
    commit + delta on this exact scenario printed an empty delta (rc 0,
    stdout ''), instead of `modme.txt` -- the round's whole change silently
    dropped out from round 1 on.
    """

    def test_committed_modification_is_listed(self):
        self.repo.write("modme.txt", b"before\n")
        self.repo.commit("add modme")

        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        self.repo.write("modme.txt", b"after\n")
        self.repo.commit("modify modme during round")

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        self.assertEqual(delta.stdout.strip(), "modme.txt")

    def test_committed_new_file_is_listed(self):
        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        self.repo.write("brand_new.txt", b"hello\n")
        self.repo.commit("add brand_new during round")

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        self.assertEqual(delta.stdout.strip(), "brand_new.txt")

    def test_committed_deletion_is_listed(self):
        self.repo.write("doomed.txt", b"bye\n")
        self.repo.commit("add doomed")

        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        (self.repo.root / "doomed.txt").unlink()
        self.repo.commit("delete doomed during round")

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        self.assertEqual(delta.stdout.strip(), "doomed.txt")

    # Control side of the modification case above: a file dirty at snapshot
    # time and then committed with those *same* bytes must not cost a
    # reviewer re-run, same principle as the plain revert case in
    # TestSnapshotAndDelta.
    def test_dirty_then_committed_same_bytes_is_not_listed(self):
        self.repo.write("roundtrip2.txt", b"committed\n")
        self.repo.commit("add roundtrip2")
        self.repo.write("roundtrip2.txt", b"dirty at snapshot time\n")

        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        self.repo.commit("commit roundtrip2 with snapshot bytes")

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        self.assertEqual(delta.stdout.strip(), "")

    # Paired with the test above: dirty at snapshot, edited *again*, then
    # committed with different bytes -- still listed.
    def test_dirty_then_changed_further_then_committed_is_listed(self):
        self.repo.write("roundtrip3.txt", b"committed\n")
        self.repo.commit("add roundtrip3")
        self.repo.write("roundtrip3.txt", b"dirty at snapshot time\n")

        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        self.repo.write("roundtrip3.txt", b"changed further\n")
        self.repo.commit("commit roundtrip3 with different bytes")

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        self.assertEqual(delta.stdout.strip(), "roundtrip3.txt")

    def test_committed_plus_uncommitted_both_listed(self):
        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        self.repo.write("committed_one.txt", b"a\n")
        self.repo.commit("add committed_one during round")
        self.repo.write("uncommitted_one.txt", b"b\n")  # left dirty

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        changed = set(delta.stdout.split())
        self.assertEqual(changed, {"committed_one.txt", "uncommitted_one.txt"})

    def test_amended_commit_still_diffs(self):
        self.repo.write("amend.txt", b"first\n")
        self.repo.commit("add amend.txt")

        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        self.repo.write("amend.txt", b"first\namended\n")
        _git("add", "-A", cwd=self.repo.root)
        _git("commit", "--amend", "-qm", "amended", cwd=self.repo.root)

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 0, delta.stderr)
        self.assertEqual(delta.stdout.strip(), "amend.txt")


class TestCommitTrackingSafety(RoundDeltaTestCase):
    """The exit-3 cases `AGENTS.md`'s "safe direction" requires: `delta` must
    refuse rather than silently under-report when it cannot trust a recorded
    head."""

    def test_v1_flat_snapshot_exits_3(self):
        path = self.repo.snapshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"some/file.txt": "abc123"}), encoding="utf-8")

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 3, delta.stdout)
        self.assertIn("version 2", delta.stderr)

    def test_recorded_head_that_does_not_exist_exits_3(self):
        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        path = self.repo.snapshot_path()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["heads"][""] = "0" * 40  # not an object in this repo
        path.write_text(json.dumps(data), encoding="utf-8")

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 3, delta.stdout)
        self.assertTrue(delta.stderr.strip())

    def test_repo_present_now_with_no_recorded_head_exits_3(self):
        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        origin = Path(tempfile.mkdtemp(prefix="hstk-workorder-late-sub-"))
        self.addCleanup(shutil.rmtree, origin, ignore_errors=True)
        _git("init", "-q", cwd=origin)
        _git("config", "user.email", "t@example.com", cwd=origin)
        _git("config", "user.name", "T", cwd=origin)
        (origin / "f.txt").write_bytes(b"x\n")
        _git("add", "-A", cwd=origin)
        _git("commit", "-qm", "base", cwd=origin)
        try:
            _git(
                "-c", "protocol.file.allow=always",
                "submodule", "add", "-q", origin.as_uri(), "LateSub",
                cwd=self.repo.root,
            )
            _git("commit", "-qm", "add LateSub after snapshot", cwd=self.repo.root)
        except subprocess.CalledProcessError as exc:
            raise unittest.SkipTest(f"git submodule add unavailable: {exc.stderr}")

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 3, delta.stdout)
        self.assertTrue(delta.stderr.strip())

    def test_repo_recorded_in_snapshot_but_gone_now_exits_3(self):
        # The mirror image of the test above: a submodule the snapshot knew
        # that is no longer an initialized repo cannot be diffed, so whatever
        # changed inside it would drop out of the delta without a word.
        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)
        # Control: the untouched snapshot is usable.
        self.assertEqual(self.repo.run("delta").returncode, 0)

        path = self.repo.snapshot_path()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["heads"]["GoneSub"] = "0" * 40
        path.write_text(json.dumps(data), encoding="utf-8")

        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 3, delta.stdout)
        self.assertIn("GoneSub", delta.stderr)


class TestUnbornHead(unittest.TestCase):
    # Separate from RoundDeltaTestCase deliberately -- DeltaRepo's own setUp
    # makes a base commit immediately, which is exactly the state this test
    # must not start from.
    def test_unborn_head_at_snapshot_then_first_commit_lists_its_files(self):
        root = Path(tempfile.mkdtemp(prefix="hstk-workorder-unborn-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        _git("init", "-q", cwd=root)
        _git("config", "user.email", "t@example.com", cwd=root)
        _git("config", "user.name", "T", cwd=root)

        snap = subprocess.run(
            [sys.executable, str(SCRIPT), "snapshot", "wo", "0", "--root", str(root)],
            capture_output=True, text=True,
        )
        self.assertEqual(snap.returncode, 0, snap.stderr)

        (root / "first.txt").write_bytes(b"hello\n")
        _git("add", "-A", cwd=root)
        _git("commit", "-qm", "first commit", cwd=root)

        delta = subprocess.run(
            [sys.executable, str(SCRIPT), "delta", "wo", "0", "--root", str(root)],
            capture_output=True, text=True,
        )
        self.assertEqual(delta.returncode, 0, delta.stderr)
        self.assertEqual(delta.stdout.strip(), "first.txt")


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
