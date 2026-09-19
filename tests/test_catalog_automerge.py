"""Exercise the catalog PR merge boundary with controlled GitHub responses (no network)."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("catalog_merge", ROOT / "tools/merge_catalog_pr.py")
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)
HUB = merge.HUB
HEAD = "a" * 40
PAIR = [{"filename": "catalog/catalog.json", "status": "modified"},
        {"filename": "catalog/catalog.json.minisig", "status": "modified"}]


class Github:
    def __init__(self):
        self.endpoint = f"repos/{HUB}/pulls/7"
        self.pr = {
            "state": "open", "merged": False, "draft": False,
            "mergeable": True, "mergeable_state": "clean",
            "user": {"login": "github-actions[bot]", "type": "Bot"},
            "base": {"sha": "b" * 40, "ref": "main", "repo": {"full_name": HUB}},
            "head": {"sha": HEAD, "ref": "catalog/regenerate", "repo": {"full_name": HUB}},
        }
        self.responses = {
            f"repos/{HUB}": {"default_branch": "main", "allow_squash_merge": True},
            f"{self.endpoint}/files?per_page=100": copy.deepcopy(PAIR),
            f"repos/{HUB}/commits/{HEAD}/status": {"total_count": 0, "state": "pending"},
            f"repos/{HUB}/commits/{HEAD}/check-runs?per_page=100": {"total_count": 0, "check_runs": []},
        }
        self.writes = []
        self.reads = []
        self.sleeps = 0
        self.on_read = None

    def __call__(self, path, *, method="GET", body=None):
        if method != "GET":
            self.writes.append((path, method, body))
            return {"merged": True, "sha": "e" * 40}
        self.reads.append(path)
        if self.on_read:
            self.on_read(self, path)
        return copy.deepcopy(self.pr if path == self.endpoint else self.responses[path])

    def sleep(self, _seconds):
        self.sleeps += 1

    def run(self, *, write=True, head=HEAD):
        return merge.process(self, HUB, 7, head, merge=write, sleep=self.sleep)


class CatalogMergeTests(unittest.TestCase):
    def assert_refused(self, api):
        with self.assertRaises(merge.Ineligible):
            api.run()
        self.assertEqual(api.writes, [])

    def test_read_only_by_default(self):
        api = Github()
        result = merge.process(api, HUB, 7, HEAD, sleep=api.sleep)
        self.assertTrue(result["eligible"])
        self.assertFalse(api.writes)

    def test_valid_catalog_pr_merges_once_with_exact_head(self):
        api = Github()
        self.assertTrue(api.run()["merged"])
        self.assertEqual(len(api.writes), 1)
        path, method, body = api.writes[0]
        self.assertEqual(path, api.endpoint + "/merge")
        self.assertEqual(method, "PUT")
        self.assertEqual(body["sha"], HEAD)
        self.assertEqual(body["merge_method"], "squash")

    def test_catalog_alone_without_signature_change_still_merges(self):
        api = Github()
        api.responses[f"{api.endpoint}/files?per_page=100"] = PAIR[:1]
        self.assertTrue(api.run()["merged"])

    def test_rejects_unknown_inputs_before_any_api_call(self):
        for repo, number, head in [("other/hub", 7, HEAD), (HUB, 0, HEAD), (HUB, 7, "not-a-sha")]:
            api = Github()
            with self.assertRaises(merge.Ineligible):
                merge.process(api, repo, number, head, merge=True, sleep=api.sleep)
            self.assertEqual(api.reads + api.writes, [])

    def test_human_fork_draft_closed_and_wrong_branch_are_refused(self):
        changes = [
            lambda p: p["user"].update(login="S-Borkowski", type="User"),
            lambda p: p["head"].update(repo={"full_name": "S-Borkowski/hero-siege-offline-toolkit"}),
            lambda p: p["head"].update(repo=None),
            lambda p: p.update(draft=True),
            lambda p: p.update(state="closed"),
            lambda p: p["base"].update(ref="feature/toolkit-hub"),
            lambda p: p["head"].update(ref="auto/bump-ForgePact-abcdef0"),
        ]
        for change in changes:
            with self.subTest(change=change):
                api = Github()
                change(api.pr)
                self.assert_refused(api)

    def test_a_head_this_run_did_not_build_is_refused(self):
        api = Github()
        with self.assertRaises(merge.Ineligible):
            api.run(head="f" * 40)
        self.assertEqual(api.writes, [])

    def test_anything_but_the_catalog_pair_is_refused(self):
        for files in [[{"filename": ".github/workflows/catalog.yml", "status": "modified"}],
                      PAIR + [{"filename": "tools/build_catalog.py", "status": "modified"}],
                      PAIR[1:],
                      [{"filename": "catalog/catalog.json", "status": "removed"}],
                      [{"filename": "catalog/catalog.json", "status": "renamed"}],
                      []]:
            with self.subTest(files=files):
                api = Github()
                api.responses[f"{api.endpoint}/files?per_page=100"] = files
                self.assert_refused(api)

    def test_head_pushed_during_validation_is_refused_at_last_read(self):
        api = Github()
        def change(client, path):
            if path == client.endpoint and client.reads.count(path) == 2:
                client.pr["head"]["sha"] = "f" * 40
        api.on_read = change
        self.assert_refused(api)

    def test_pending_and_failing_checks_are_not_bypassed(self):
        for status, conclusion in [("queued", None), ("in_progress", None),
                                   ("completed", "failure"), ("completed", "cancelled")]:
            api = Github()
            api.responses[f"repos/{HUB}/commits/{HEAD}/check-runs?per_page=100"] = {
                "total_count": 1, "check_runs": [{"status": status, "conclusion": conclusion}]}
            self.assert_refused(api)
        api = Github()
        api.responses[f"repos/{HUB}/commits/{HEAD}/status"] = {"total_count": 1, "state": "failure"}
        self.assert_refused(api)

    def test_successful_checks_allow_merge(self):
        api = Github()
        api.responses[f"repos/{HUB}/commits/{HEAD}/status"] = {"total_count": 1, "state": "success"}
        api.responses[f"repos/{HUB}/commits/{HEAD}/check-runs?per_page=100"] = {
            "total_count": 1, "check_runs": [{"status": "completed", "conclusion": "success"}]}
        self.assertTrue(api.run()["merged"])

    def test_conflicts_and_required_reviews_are_refused(self):
        for mergeable, state in [(False, "dirty"), (True, "blocked"),
                                 (True, "behind"), (True, "unstable")]:
            api = Github()
            api.pr.update(mergeable=mergeable, mergeable_state=state)
            self.assert_refused(api)

    def test_mergeability_still_computing_is_waited_for(self):
        api = Github()
        api.pr.update(mergeable=None, mergeable_state="unknown")
        def settle(client, path):
            if path == client.endpoint and client.reads.count(path) == 3:
                client.pr.update(mergeable=True, mergeable_state="clean")
        api.on_read = settle
        self.assertTrue(api.run()["merged"])
        self.assertEqual(api.sleeps, 1)

    def test_mergeability_that_never_settles_is_refused_after_bounded_wait(self):
        api = Github()
        api.pr.update(mergeable=None, mergeable_state="unknown")
        self.assert_refused(api)
        self.assertEqual(api.sleeps, 6)

    def test_merge_rejection_is_not_retried(self):
        api = Github()
        def reject(path, **kwargs):
            if kwargs.get("method") == "PUT":
                api.writes.append(path)
                raise subprocess.CalledProcessError(1, "gh api merge")
            return api(path, **kwargs)
        with self.assertRaises(subprocess.CalledProcessError):
            merge.process(reject, HUB, 7, HEAD, merge=True, sleep=api.sleep)
        self.assertEqual(len(api.writes), 1)


class OutputTests(unittest.TestCase):
    """catalog.yml publishes only on merged=true, so every exit must write the flag."""

    def run_main(self, outcome):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "github_output"
            argv = ["merge_catalog_pr.py", "--pull-request", "7", "--head", HEAD,
                    "--merge", "--output", str(out)]
            with mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(merge, "process", side_effect=outcome), \
                 mock.patch("builtins.print"):
                code = merge.main()
            return code, out.read_text(encoding="utf-8")

    def test_merged_writes_true(self):
        self.assertEqual(self.run_main(lambda *a, **k: {"merged": True, "number": 7, "sha": "e" * 40}),
                         (0, "merged=true\n"))

    def test_ineligible_writes_false_and_succeeds(self):
        self.assertEqual(self.run_main(merge.Ineligible("no")), (0, "merged=false\n"))

    def test_api_error_writes_false_and_fails(self):
        self.assertEqual(self.run_main(subprocess.CalledProcessError(1, "gh")), (1, "merged=false\n"))


if __name__ == "__main__":
    unittest.main()
