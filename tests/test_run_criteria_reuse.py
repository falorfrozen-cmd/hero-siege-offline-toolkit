"""run_criteria.py `--reuse DIR` (audit F10, owner 2026-10-11: "implementer
and verifier may share test results if it makes sense").

A development run may copy a prior run's result for a criterion instead of
running it again, but only when the runner can see that nothing it depends
on changed: every repository HEAD it reaches, and the content of every file
its `(reads ...)` matches. These pin both directions: a match is reused and
marked as such in the report, status and digest, and each kind of change (a
read file, a new commit, a criterion with no reads, a final-gate criterion,
a full run) runs the command again. A hit counter outside the repository
records which commands really ran.
"""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import run_criteria  # noqa: E402

PLAN = """# x

## Acceptance criteria

- [ ] (reads `src/**`) `bash -c "echo a >> ../hits.txt; cat src/a.txt"` exits 0
- [ ] `bash -c "echo b >> ../hits.txt"` exits 0
- [ ] (reads `src/**`) `bash -c "echo c >> ../hits.txt; exit 3"` exits 3
"""


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        rc = run_criteria.main(argv)
    return rc, out.getvalue()


def git(repo, *args):
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


class ReuseTests(unittest.TestCase):
    def setUp(self):
        if not run_criteria.find_bash(None):
            self.skipTest("no bash on this machine")
        if shutil.which("git") is None:
            self.skipTest("no git on this machine")
        self.tmp = Path(tempfile.mkdtemp(prefix="run_criteria_reuse_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src" / "a.txt").write_text("one\n", encoding="utf-8")
        (self.repo / "other.txt").write_text("x\n", encoding="utf-8")
        self.plan = self.repo / "x-plan.md"
        self.plan.write_text(PLAN, encoding="utf-8")
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@example.invalid")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "core.autocrlf", "false")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        self.hits = self.tmp / "hits.txt"

    def counts(self):
        text = self.hits.read_text(encoding="utf-8") if self.hits.exists() else ""
        return {c: text.split().count(c) for c in "abc"}

    def first_then_second(self, *extra, between=None, first=("--dev",), second=("--dev",)):
        o1, o2 = self.tmp / "o1", self.tmp / "o2"
        rc, out = run([str(self.plan), "--out", str(o1), *first, *extra])
        self.assertEqual(rc, 0, out)
        if between:
            between()
        rc, out = run([str(self.plan), "--out", str(o2), *second, "--reuse", str(o1), *extra])
        return rc, out, o2

    def status(self, out):
        return {c["k"]: c for c in json.loads((out / "status.json").read_text(encoding="utf-8"))["criteria"]}

    def test_every_criterion_records_heads_dirty_and_reads_hash(self):
        rc, out = run([str(self.plan), "--out", str(self.tmp / "o1"), "--dev"])
        self.assertEqual(rc, 0, out)
        fp = self.status(self.tmp / "o1")[1]["fingerprint"]
        self.assertEqual(set(fp), {"heads", "dirty", "dirty_hash", "reads_hash"})
        self.assertRegex(fp["heads"]["."], r"^[0-9a-f]{40}$")
        self.assertEqual(fp["dirty"], {".": False})
        self.assertIsNone(self.status(self.tmp / "o1")[2]["fingerprint"]["reads_hash"],
                          "a criterion with no (reads ...) has no reads hash, so it never matches")

    def test_unchanged_tree_reuses_and_says_so(self):
        for jobs in ((), ("--jobs", "2")):
            with self.subTest(jobs=jobs):
                self.hits.unlink(missing_ok=True)
                shutil.rmtree(self.tmp / "o1", ignore_errors=True)
                shutil.rmtree(self.tmp / "o2", ignore_errors=True)
                rc, out, o2 = self.first_then_second(*jobs)
                self.assertEqual(rc, 0, out)
                self.assertEqual(self.counts(), {"a": 1, "b": 2, "c": 1},
                                 "1 and 3 reused (exit 0 and exit 3 alike); 2 declares no reads and runs again")
                self.assertIn(f"REUSED from {self.tmp / 'o1'}", out)
                self.assertIn("reuse: from", out)
                st = self.status(o2)
                self.assertEqual(st[1]["reused_from"], str(self.tmp / "o1"))
                self.assertEqual([c["exit"] for c in st[3]["commands"]], [3], "a failed result is reused as failed")
                self.assertNotIn("reused_from", st[2])
                self.assertTrue((o2 / "reused-cmd-1.log").is_file())
                self.assertIn("one", (o2 / "reused-cmd-1.log").read_text(encoding="utf-8"))
                self.assertEqual((o2 / "report.txt").read_text(encoding="utf-8"), out)
                digest = io.StringIO()
                with contextlib.redirect_stdout(digest):
                    self.assertEqual(run_criteria.main(["--digest", str(o2)]), 0)
                self.assertIn("reused from", digest.getvalue())

    def test_an_uncommitted_change_outside_the_reads_still_reuses(self):
        # Control for the next test: dirtiness alone is not a mismatch.
        rc, out, _ = self.first_then_second(
            between=lambda: (self.repo / "other.txt").write_text("y\n", encoding="utf-8"))
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.counts()["a"], 1)

    def test_a_changed_read_file_runs_again(self):
        rc, out, o2 = self.first_then_second(
            between=lambda: (self.repo / "src" / "a.txt").write_text("two\n", encoding="utf-8"))
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.counts()["a"], 2)
        self.assertNotIn("REUSED", out)
        self.assertIn("a file it reads changed", out)

    def test_a_new_untracked_read_file_runs_again(self):
        rc, out, _ = self.first_then_second(
            between=lambda: (self.repo / "src" / "b.txt").write_text("new\n", encoding="utf-8"))
        self.assertEqual(self.counts()["a"], 2, out)

    def test_a_new_commit_runs_again(self):
        def commit():
            (self.repo / "other.txt").write_text("z\n", encoding="utf-8")
            git(self.repo, "commit", "-q", "-am", "unrelated")
        rc, out, _ = self.first_then_second(between=commit)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.counts()["a"], 2)
        self.assertIn("a repository HEAD moved", out)

    def test_a_full_run_refuses_reuse(self):
        rc, out = run([str(self.plan), "--out", str(self.tmp / "o1"), "--dev"])
        self.assertEqual(rc, 0, out)
        rc, _ = run([str(self.plan), "--out", str(self.tmp / "o2"), "--reuse", str(self.tmp / "o1")])
        self.assertEqual(rc, 2, "the final gate always runs every criterion")
        self.assertEqual(self.counts()["a"], 1, "nothing ran")

    def test_a_missing_prior_runs_everything(self):
        rc, out = run([str(self.plan), "--out", str(self.tmp / "o2"), "--dev", "--reuse", str(self.tmp / "nope")])
        self.assertEqual(rc, 0, out)
        self.assertIn("reuse: none", out)
        self.assertEqual(self.counts(), {"a": 1, "b": 1, "c": 1})


class ReusableRuleTests(unittest.TestCase):
    """`reusable()` as a pure function of a prior status entry and this
    tree's fingerprint."""

    FP = {"heads": {".": "a" * 40}, "dirty": {".": False}, "dirty_hash": "d", "reads_hash": "r"}
    ITEM = "(reads `src/**`) `bash -c \"true\"` exits 0"

    def prior(self, item, fp=None, exit=0, item_id=None):
        return {"item": item_id, "criteria": [{"k": 1, "state": "done", "text": item,
                                                "fingerprint": fp or self.FP,
                                                "commands": [{"n": 1, "cmd": "x", "exit": exit}]}]}

    def test_match_is_reused(self):
        entry, why = run_criteria.reusable(self.prior(self.ITEM), 1, self.ITEM, None, self.FP)
        self.assertIsNotNone(entry, why)

    def test_final_and_whole_suite_criteria_never_are(self):
        for item in ("(final) " + self.ITEM, "(reads `tests/**`) `py -3 -m unittest discover -s tests` exits 0"):
            with self.subTest(item=item):
                entry, why = run_criteria.reusable(self.prior(item), 1, item, None, self.FP)
                self.assertIsNone(entry)
                self.assertEqual(why, "final gate only")

    def test_each_mismatch_refuses(self):
        cases = {
            "no reads": ("`bash -c \"true\"` exits 0", self.FP, 0, None),
            "text changed": (self.ITEM, self.FP, 0, None),
            "head moved": (self.ITEM, dict(self.FP, heads={".": "b" * 40}), 0, None),
            "reads changed": (self.ITEM, dict(self.FP, reads_hash="other"), 0, None),
            "dirty changed": (self.ITEM, dict(self.FP, dirty_hash="other"), 0, None),
            "timed out": (self.ITEM, self.FP, "TIMEOUT", None),
            "other item": (self.ITEM, self.FP, 0, "item-2"),
        }
        for name, (prior_item, fp, exit, item_id) in cases.items():
            with self.subTest(name):
                current = self.ITEM + " " if name == "text changed" else prior_item
                entry, _ = run_criteria.reusable(self.prior(prior_item, fp, exit, item_id), 1, current, None, self.FP)
                self.assertIsNone(entry)

    def test_unknown_heads_never_match(self):
        fp = dict(self.FP, heads={".": None})
        entry, _ = run_criteria.reusable(self.prior(self.ITEM, fp), 1, self.ITEM, None, fp)
        self.assertIsNone(entry)


if __name__ == "__main__":
    unittest.main()
