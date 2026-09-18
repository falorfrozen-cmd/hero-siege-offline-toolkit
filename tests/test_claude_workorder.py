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
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / ".claude" / "skills" / "workorder" / "round_delta.py"
ENSURE_SCRIPT = REPO / ".claude" / "skills" / "workorder" / "ensure_submodule.py"


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
        # A clone does not inherit its origin's local Git identity.
        _git("config", "user.email", "t@example.com", cwd=self.sub)
        _git("config", "user.name", "T", cwd=self.sub)

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


class TestHeadsSubcommand(RoundDeltaTestCase):
    """`round_delta.py heads` (SPEC.md § 2a): the reviewer-dispatch base the
    driver reads instead of re-deriving heads itself. Its contract is
    deliberately narrower than `delta`'s -- it only validates the snapshot's
    own shape, never whether the recorded heads are still resolvable in this
    repo -- so most of `TestCommitTrackingSafety` above is this class's
    control: the same corruptions that make `delta` exit 3 must NOT make
    `heads` exit 3.
    """

    # Negative control: no snapshot at all is still refused the same way
    # `delta` refuses it.
    def test_missing_snapshot_exits_3(self):
        heads = self.repo.run("heads", slug="never-snapshotted")
        self.assertEqual(heads.returncode, 3, heads.stdout)
        self.assertTrue(heads.stderr.strip())

    def test_corrupt_snapshot_exits_3(self):
        path = self.repo.snapshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        heads = self.repo.run("heads")
        self.assertEqual(heads.returncode, 3, heads.stdout)
        self.assertTrue(heads.stderr.strip())

    def test_v1_flat_snapshot_exits_3(self):
        path = self.repo.snapshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"some/file.txt": "abc123"}), encoding="utf-8")
        heads = self.repo.run("heads")
        self.assertEqual(heads.returncode, 3, heads.stdout)
        self.assertIn("version 2", heads.stderr)

    # Positive control paired with the two below: the hub's real HEAD, keyed
    # "." rather than the snapshot's own "" key.
    def test_hub_head_printed_under_dot_key(self):
        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)
        expected_sha = _git("rev-parse", "HEAD", cwd=self.repo.root).stdout.strip()

        heads = self.repo.run("heads")
        self.assertEqual(heads.returncode, 0, heads.stderr)
        lines = [l for l in heads.stdout.splitlines() if l]
        self.assertEqual(lines, [f".\t{expected_sha}"])

    def test_unborn_head_prints_empty_sha(self):
        root = Path(tempfile.mkdtemp(prefix="hstk-workorder-heads-unborn-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        _git("init", "-q", cwd=root)
        _git("config", "user.email", "t@example.com", cwd=root)
        _git("config", "user.name", "T", cwd=root)

        snap = subprocess.run(
            [sys.executable, str(SCRIPT), "snapshot", "wo", "0", "--root", str(root)],
            capture_output=True, text=True,
        )
        self.assertEqual(snap.returncode, 0, snap.stderr)

        heads = subprocess.run(
            [sys.executable, str(SCRIPT), "heads", "wo", "0", "--root", str(root)],
            capture_output=True, text=True,
        )
        self.assertEqual(heads.returncode, 0, heads.stderr)
        lines = [l for l in heads.stdout.splitlines() if l or True]
        # Not `.strip()`-ed as a whole -- ".\t".strip() would eat the trailing
        # tab and hide exactly the thing under test (an empty sha after it).
        key, _, sha = lines[0].partition("\t")
        self.assertEqual((key, sha), (".", ""))

    # The contract-defining test: a corruption that makes `delta` exit 3 for
    # a *live-repo* reason (see TestCommitTrackingSafety.
    # test_recorded_head_that_does_not_exist_exits_3, its control) must not
    # touch `heads` at all -- it only echoes back what the snapshot says.
    def test_heads_does_not_validate_recorded_shas_against_the_live_repo(self):
        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        path = self.repo.snapshot_path()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["heads"][""] = "0" * 40  # not an object in this repo
        path.write_text(json.dumps(data), encoding="utf-8")

        heads = self.repo.run("heads")
        self.assertEqual(heads.returncode, 0, heads.stderr)
        self.assertIn("." + "\t" + "0" * 40, heads.stdout)

        # Control: the identical corruption makes `delta` refuse.
        delta = self.repo.run("delta")
        self.assertEqual(delta.returncode, 3, delta.stdout)


class TestHeadsWithSubmodule(RoundDeltaTestCase):
    """`heads` must key a submodule by its own dir, not fold it into the hub
    entry -- the same prefixing property `TestSubmodulePrefixing` pins down
    for `delta`."""

    def setUp(self):
        super().setUp()
        self.origin = Path(tempfile.mkdtemp(prefix="hstk-workorder-heads-sub-"))
        self.addCleanup(shutil.rmtree, self.origin, ignore_errors=True)
        _git("init", "-q", cwd=self.origin)
        _git("config", "user.email", "t@example.com", cwd=self.origin)
        _git("config", "user.name", "T", cwd=self.origin)
        (self.origin / "file.md").write_bytes(b"clean\n")
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

    def test_submodule_keyed_by_its_own_dir(self):
        snap = self.repo.run("snapshot")
        self.assertEqual(snap.returncode, 0, snap.stderr)
        hub_sha = _git("rev-parse", "HEAD", cwd=self.repo.root).stdout.strip()
        sub_sha = _git("rev-parse", "HEAD", cwd=self.sub).stdout.strip()

        heads = self.repo.run("heads")
        self.assertEqual(heads.returncode, 0, heads.stderr)
        printed = dict(l.split("\t", 1) for l in heads.stdout.splitlines() if l)
        self.assertEqual(printed, {".": hub_sha, "Sub": sub_sha})


class EnsureSubmoduleRepoSet:
    """A main checkout with a submodule already initialized, plus a linked
    worktree of that same checkout where the submodule is not -- the exact
    shape SPEC.md § "A worktree works on its own submodule" fixes (a
    worktree that would otherwise fall back to the main checkout's copy)."""

    def __init__(self):
        self.origin = Path(tempfile.mkdtemp(prefix="hstk-ensuresub-origin-"))
        _git("init", "-q", cwd=self.origin)
        _git("config", "user.email", "t@example.com", cwd=self.origin)
        _git("config", "user.name", "T", cwd=self.origin)
        (self.origin / "f.txt").write_bytes(b"base\n")
        _git("add", "-A", cwd=self.origin)
        _git("commit", "-qm", "base", cwd=self.origin)

        self.main = Path(tempfile.mkdtemp(prefix="hstk-ensuresub-main-"))
        _git("init", "-q", cwd=self.main)
        _git("config", "user.email", "t@example.com", cwd=self.main)
        _git("config", "user.name", "T", cwd=self.main)
        (self.main / "README.md").write_bytes(b"hub\n")
        _git("add", "-A", cwd=self.main)
        _git("commit", "-qm", "base", cwd=self.main)
        try:
            _git(
                "-c", "protocol.file.allow=always",
                "submodule", "add", "-q", self.origin.as_uri(), "Sub",
                cwd=self.main,
            )
            _git("commit", "-qm", "add submodule", cwd=self.main)
        except subprocess.CalledProcessError as exc:
            raise unittest.SkipTest(f"git submodule add unavailable: {exc.stderr}")
        # The main checkout's own copy is fully initialized -- ensure_submodule.py
        # must never touch this one, only reference it.
        _git("submodule", "update", "--init", "--", "Sub", cwd=self.main)

        self.worktree = Path(tempfile.mkdtemp(prefix="hstk-ensuresub-wt-")) / "wt"
        try:
            _git(
                "worktree", "add", "-q", "-b", "feat/sub-work", str(self.worktree),
                cwd=self.main,
            )
        except subprocess.CalledProcessError as exc:
            raise unittest.SkipTest(f"git worktree add unavailable: {exc.stderr}")

    def destroy(self):
        # SPEC.md's own proven finding: "working trees containing submodules
        # cannot be moved or removed" without --force.
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(self.worktree)],
            cwd=str(self.main), capture_output=True,
        )
        shutil.rmtree(self.worktree.parent, ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=str(self.main),
                        capture_output=True)
        shutil.rmtree(self.main, ignore_errors=True)
        shutil.rmtree(self.origin, ignore_errors=True)

    def run(self, module="Sub", root=None):
        # The worktree's own gitdir for the module doesn't exist yet, so
        # `--reference --dissociate` still performs a genuine (if
        # object-sharing) clone rather than reusing an existing `.git/modules`
        # entry -- and a persisted `protocol.file.allow` in repo-local config
        # does not reach that clone subprocess (measured: it still refuses
        # with "transport 'file' not allowed" even though `git config --get`
        # reports it set). `GIT_ALLOW_PROTOCOL` is the override that does
        # reach it -- this is test-only, standing in for the ordinary
        # https/ssh submodule URL a real module uses, where this is a
        # non-issue.
        env = dict(os.environ, GIT_ALLOW_PROTOCOL="file")
        return subprocess.run(
            [sys.executable, str(ENSURE_SCRIPT), module,
             "--root", str(root if root is not None else self.worktree)],
            capture_output=True, text=True, env=env,
        )


class TestEnsureSubmoduleLinkedWorktree(unittest.TestCase):
    def setUp(self):
        self.repos = EnsureSubmoduleRepoSet()
        self.addCleanup(self.repos.destroy)

    # Negative control for the test below: before running, the worktree
    # genuinely has no copy of the submodule at all.
    def test_starts_uninitialized(self):
        self.assertFalse((self.repos.worktree / "Sub" / ".git").exists())

    def test_uninitialized_in_linked_worktree_gets_its_own_git_dir(self):
        result = self.repos.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("initialized: Sub @", result.stdout)
        sub_git = self.repos.worktree / "Sub" / ".git"
        self.assertTrue(sub_git.exists())

        wt_gitdir = _git(
            "rev-parse", "--absolute-git-dir", cwd=str(self.repos.worktree / "Sub")
        ).stdout.strip()
        main_gitdir = _git(
            "rev-parse", "--absolute-git-dir", cwd=str(self.repos.main / "Sub")
        ).stdout.strip()
        # Positive control: the two are genuinely separate git dirs, not the
        # main checkout's module reused in place.
        self.assertNotEqual(Path(wt_gitdir).resolve(), Path(main_gitdir).resolve())
        self.assertIn("worktrees", wt_gitdir.replace("\\", "/"))

    def test_commit_in_worktree_module_is_invisible_to_main_checkout_module(self):
        result = self.repos.run()
        self.assertEqual(result.returncode, 0, result.stderr)

        sub_in_wt = self.repos.worktree / "Sub"
        (sub_in_wt / "new.txt").write_bytes(b"from worktree\n")
        # ensure_submodule clones this module fresh, so it has none of the
        # identity the fixture set up elsewhere; CI has no global one.
        _git("config", "user.email", "t@example.com", cwd=sub_in_wt)
        _git("config", "user.name", "T", cwd=sub_in_wt)
        _git("add", "-A", cwd=sub_in_wt)
        _git("commit", "-qm", "worktree-only commit", cwd=sub_in_wt)

        main_log = _git("log", "--oneline", "--all", cwd=str(self.repos.main / "Sub")).stdout
        self.assertNotIn("worktree-only commit", main_log)
        # Positive control: the commit genuinely exists, just not there.
        wt_log = _git("log", "--oneline", cwd=sub_in_wt).stdout
        self.assertIn("worktree-only commit", wt_log)

    def test_second_run_is_idempotent(self):
        first = self.repos.run()
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.repos.run()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("already initialized: Sub @", second.stdout)
        # Idempotent means no repeated init, not just "still succeeds": the
        # HEAD reported the second time must be the one the first call left.
        first_sha = first.stdout.splitlines()[0].split("@", 1)[1].strip()
        second_sha = second.stdout.splitlines()[0].split("@", 1)[1].strip()
        self.assertEqual(first_sha, second_sha)

    def test_unknown_module_exits_2(self):
        result = self.repos.run(module="NotAModule")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertTrue(result.stderr.strip())

    def test_prints_fetch_command_for_bringing_unpushed_work_across(self):
        result = self.repos.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("bring unpushed work across:", result.stdout)
        self.assertIn("git -C Sub fetch", result.stdout)


class TestEnsureSubmoduleMainCheckout(unittest.TestCase):
    """Run from the main checkout itself -- no linked worktree involved, so
    there is nothing to reference and nothing to fetch across. Paired
    negative control for `TestEnsureSubmoduleLinkedWorktree`'s
    `test_prints_fetch_command_for_bringing_unpushed_work_across`."""

    def setUp(self):
        self.origin = Path(tempfile.mkdtemp(prefix="hstk-ensuresub-solo-origin-"))
        self.addCleanup(shutil.rmtree, self.origin, ignore_errors=True)
        _git("init", "-q", cwd=self.origin)
        _git("config", "user.email", "t@example.com", cwd=self.origin)
        _git("config", "user.name", "T", cwd=self.origin)
        (self.origin / "f.txt").write_bytes(b"base\n")
        _git("add", "-A", cwd=self.origin)
        _git("commit", "-qm", "base", cwd=self.origin)

        self.repo = Path(tempfile.mkdtemp(prefix="hstk-ensuresub-solo-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        _git("init", "-q", cwd=self.repo)
        _git("config", "user.email", "t@example.com", cwd=self.repo)
        _git("config", "user.name", "T", cwd=self.repo)
        (self.repo / "README.md").write_bytes(b"hub\n")
        _git("add", "-A", cwd=self.repo)
        _git("commit", "-qm", "base", cwd=self.repo)
        try:
            _git(
                "-c", "protocol.file.allow=always",
                "submodule", "add", "-q", self.origin.as_uri(), "Sub",
                cwd=self.repo,
            )
            _git("commit", "-qm", "add submodule", cwd=self.repo)
        except subprocess.CalledProcessError as exc:
            raise unittest.SkipTest(f"git submodule add unavailable: {exc.stderr}")
        # `submodule add` clones and checks out immediately -- deinit gets
        # back to the "not yet initialized" starting point this test needs,
        # without discarding `.git/modules/Sub` (so the later plain
        # `update --init` this script runs is a local checkout, not a fresh
        # clone, and needs no file-protocol override).
        _git("submodule", "deinit", "-f", "--", "Sub", cwd=self.repo)

    def test_plain_init_from_main_checkout_no_reference_no_fetch_hint(self):
        self.assertFalse((self.repo / "Sub" / ".git").exists())
        result = subprocess.run(
            [sys.executable, str(ENSURE_SCRIPT), "Sub", "--root", str(self.repo)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("initialized: Sub @", result.stdout)
        self.assertTrue((self.repo / "Sub" / ".git").exists())
        # Running from the main checkout is not a linked-worktree case, so
        # there is no separate main copy to reference or fetch from.
        self.assertNotIn("bring unpushed work across", result.stdout)


class PrereqsRepoSet:
    """The same shape as `EnsureSubmoduleRepoSet` -- a main checkout with an
    initialized submodule, plus a linked worktree where it is not -- but with
    a committed `local_prereqs.json` manifest already in place *before* the
    worktree is created, the same way any other tracked file reaches a
    worktree: through history, never a live copy from main. `write_prereq`
    then drops files straight into the main checkout's submodule copy,
    uncommitted, standing in for a real local-only, `.gitignore`'d build
    input (`plugin_build/include`) that only whichever machine first
    initialized the module has -- exactly what the worktree's own
    `git submodule update --init` cannot produce."""

    def __init__(self, manifest):
        self.origin = Path(tempfile.mkdtemp(prefix="hstk-prereqs-origin-"))
        _git("init", "-q", cwd=self.origin)
        _git("config", "user.email", "t@example.com", cwd=self.origin)
        _git("config", "user.name", "T", cwd=self.origin)
        (self.origin / "f.txt").write_bytes(b"base\n")
        _git("add", "-A", cwd=self.origin)
        _git("commit", "-qm", "base", cwd=self.origin)

        self.main = Path(tempfile.mkdtemp(prefix="hstk-prereqs-main-"))
        _git("init", "-q", cwd=self.main)
        _git("config", "user.email", "t@example.com", cwd=self.main)
        _git("config", "user.name", "T", cwd=self.main)
        (self.main / "README.md").write_bytes(b"hub\n")
        manifest_dir = self.main / ".claude" / "skills" / "workorder"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "local_prereqs.json").write_text(
            json.dumps(manifest), encoding="utf-8")
        _git("add", "-A", cwd=self.main)
        _git("commit", "-qm", "base + manifest", cwd=self.main)
        try:
            _git(
                "-c", "protocol.file.allow=always",
                "submodule", "add", "-q", self.origin.as_uri(), "Sub",
                cwd=self.main,
            )
            _git("commit", "-qm", "add submodule", cwd=self.main)
        except subprocess.CalledProcessError as exc:
            raise unittest.SkipTest(f"git submodule add unavailable: {exc.stderr}")
        _git("submodule", "update", "--init", "--", "Sub", cwd=self.main)

        self.worktree = Path(tempfile.mkdtemp(prefix="hstk-prereqs-wt-")) / "wt"
        try:
            _git(
                "worktree", "add", "-q", "-b", "feat/prereqs-work", str(self.worktree),
                cwd=self.main,
            )
        except subprocess.CalledProcessError as exc:
            raise unittest.SkipTest(f"git worktree add unavailable: {exc.stderr}")

    def write_prereq(self, rel, data=b"local-only\n"):
        path = self.main / "Sub" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            data = data.encode("utf-8")
        path.write_bytes(data)

    def destroy(self):
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(self.worktree)],
            cwd=str(self.main), capture_output=True,
        )
        shutil.rmtree(self.worktree.parent, ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=str(self.main),
                        capture_output=True)
        shutil.rmtree(self.main, ignore_errors=True)
        shutil.rmtree(self.origin, ignore_errors=True)

    def run(self, module="Sub", root=None):
        env = dict(os.environ, GIT_ALLOW_PROTOCOL="file")
        return subprocess.run(
            [sys.executable, str(ENSURE_SCRIPT), module,
             "--root", str(root if root is not None else self.worktree)],
            capture_output=True, text=True, env=env,
        )


class TestProvisionLocalPrereqs(unittest.TestCase):
    """`ensure_submodule.py`'s local-only build prerequisite provisioning
    (SPEC.md § 5) -- proven on the real repo (SPEC.md § 1's `plugin_build`
    finding: a linked worktree's build failed until `plugin_build/include`
    was copied across by hand). Every case here pairs a positive with a
    negative control, per `AGENTS.md` § "Prove the Instrument Before
    Trusting a Negative Result"."""

    def _make(self, manifest):
        repos = PrereqsRepoSet(manifest)
        self.addCleanup(repos.destroy)
        return repos

    def test_copied_when_missing(self):
        repos = self._make({"ForgePact": ["ignored/entry"], "Sub": ["plugin_build/include"]})
        repos.write_prereq("plugin_build/include/YYTK_Shared_Types.cpp", "hdr\n")
        result = repos.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("copied prerequisite: plugin_build/include", result.stdout)
        copied = repos.worktree / "Sub" / "plugin_build" / "include" / "YYTK_Shared_Types.cpp"
        self.assertTrue(copied.exists())
        self.assertEqual(copied.read_text(encoding="utf-8"), "hdr\n")

    # Negative control for the copy above: once the worktree has its own
    # copy (here, left over from the first run), a second run -- the
    # already-initialized path -- must never overwrite it, even though the
    # main checkout's bytes still differ.
    def test_left_alone_when_already_present(self):
        repos = self._make({"Sub": ["marker.txt"]})
        repos.write_prereq("marker.txt", "from main\n")
        first = repos.run()
        self.assertEqual(first.returncode, 0, first.stderr)
        target = repos.worktree / "Sub" / "marker.txt"
        self.assertTrue(target.exists())
        target.write_text("worktree-local edit\n", encoding="utf-8")

        second = repos.run()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("already initialized: Sub @", second.stdout)
        self.assertEqual(target.read_text(encoding="utf-8"), "worktree-local edit\n")

    # Positive control paired with the copy test: an extra main-checkout file
    # the manifest does not name is left behind, even though it too "exists
    # in the main checkout and is missing here" -- the same predicate that
    # copies a listed entry, so this pins that the manifest (not existence
    # alone) gates the copy.
    def test_unlisted_files_not_copied(self):
        repos = self._make({"Sub": ["listed.txt"]})
        repos.write_prereq("listed.txt", "keep\n")
        repos.write_prereq("unlisted.txt", "must not travel\n")
        result = repos.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((repos.worktree / "Sub" / "listed.txt").exists())
        self.assertFalse((repos.worktree / "Sub" / "unlisted.txt").exists())

    def test_bad_manifest_entry_rejected(self):
        repos = self._make({"Sub": ["../escape.txt", "/abs/evil.txt", "C:/evil2.txt", "safe.txt"]})
        repos.write_prereq("safe.txt", "ok\n")
        (repos.main / "escape.txt").write_bytes(b"must never be read\n")
        result = repos.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count("rejected prerequisite"), 3)
        self.assertIn("copied prerequisite: safe.txt", result.stdout)
        self.assertFalse((repos.worktree / "escape.txt").exists())

    # SPEC.md § 5's explicit negative: running from the main checkout itself
    # (not a linked worktree) copies nothing, since that IS where the
    # local-only files already live -- paired with
    # `TestEnsureSubmoduleMainCheckout` above for the submodule-init half of
    # the same case.
    def test_main_checkout_run_copies_nothing(self):
        repos = self._make({"Sub": ["only-in-main.txt"]})
        repos.write_prereq("only-in-main.txt", "already here\n")
        _git("submodule", "deinit", "-f", "--", "Sub", cwd=repos.main)
        env = dict(os.environ, GIT_ALLOW_PROTOCOL="file")
        result = subprocess.run(
            [sys.executable, str(ENSURE_SCRIPT), "Sub", "--root", str(repos.main)],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("copied prerequisite", result.stdout)
        self.assertNotIn("prerequisite not in main checkout", result.stdout)

    # Missing manifest and missing module key are both "no prerequisites",
    # not an error -- most modules (and most repos exercising this script in
    # tests) have neither.
    def test_missing_manifest_is_fine(self):
        repos = EnsureSubmoduleRepoSet()
        self.addCleanup(repos.destroy)
        result = repos.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("copied prerequisite", result.stdout)

    def test_missing_module_key_is_fine(self):
        repos = self._make({"OtherModule": ["x.txt"]})
        result = repos.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("copied prerequisite", result.stdout)
        self.assertNotIn("prerequisite not in main checkout", result.stdout)

    # Positive control for the "not in main checkout" line: a listed entry
    # that genuinely doesn't exist anywhere is reported, not silently
    # dropped -- the failure mode SPEC.md § 1 measured (a missing prereq
    # failing the build with no hint why).
    def test_prerequisite_not_in_main_checkout_reported(self):
        repos = self._make({"Sub": ["never-existed.txt"]})
        result = repos.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("prerequisite not in main checkout: never-existed.txt", result.stdout)


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
