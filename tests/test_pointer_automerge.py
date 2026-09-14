"""Exercise the merge boundary with controlled GitHub responses (no network)."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pointer_merge", ROOT / "tools/merge_submodule_pointer.py")
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)
HUB = merge.HUB
HEAD, BASE, OLD, TARGET = (c * 40 for c in "abcd")


class Github:
    def __init__(self, module="ForgePact", upstream_branch="main"):
        self.module = module
        self.endpoint = f"repos/{HUB}/pulls/7"
        self.latest = f"repos/falorfrozen-cmd/{module}/commits/{upstream_branch}"
        self.pr = {
            "state": "open", "merged": False, "draft": False, "changed_files": 1,
            "mergeable": True, "mergeable_state": "clean",
            "user": {"login": "github-actions[bot]", "type": "Bot"},
            "base": {"sha": BASE, "ref": "main", "repo": {"full_name": HUB}},
            "head": {"sha": HEAD, "ref": f"auto/bump-{module}-{TARGET[:7]}",
                     "repo": {"full_name": HUB}},
        }
        self.responses = {
            f"repos/{HUB}": {"default_branch": "main", "allow_squash_merge": True},
            f"repos/{HUB}/commits/main": {"sha": BASE},
            f"{self.endpoint}/files?per_page=100": [{"filename": module, "status": "modified"}],
            f"repos/{HUB}/git/commits/{HEAD}": {"tree": {"sha": "head-tree"}},
            f"repos/{HUB}/git/commits/{BASE}": {"tree": {"sha": "base-tree"}},
            f"repos/{HUB}/git/trees/head-tree": {"tree": [
                {"path": module, "mode": "160000", "type": "commit", "sha": TARGET}]},
            f"repos/{HUB}/git/trees/base-tree": {"tree": [
                {"path": module, "mode": "160000", "type": "commit", "sha": OLD}]},
            f"repos/falorfrozen-cmd/{module}": {"default_branch": upstream_branch},
            self.latest: {"sha": TARGET},
            f"repos/falorfrozen-cmd/{module}/compare/{OLD}...{TARGET}": {"status": "ahead"},
            f"repos/{HUB}/commits/{HEAD}/status": {"total_count": 0, "state": "pending"},
            f"repos/{HUB}/commits/{HEAD}/check-runs?per_page=100": {"total_count": 0, "check_runs": []},
        }
        self.writes = []
        self.reads = []
        self.on_read = None

    def __call__(self, path, *, method="GET", body=None):
        if method != "GET":
            self.writes.append((path, method, body))
            return {"merged": True, "sha": "e" * 40}
        self.reads.append(path)
        if self.on_read:
            self.on_read(self, path)
        return copy.deepcopy(self.pr if path == self.endpoint else self.responses[path])

    def run(self, *, write=True):
        return merge.process(self, HUB, 7, self.module, TARGET, merge=write)


class PointerMergeTests(unittest.TestCase):
    def assert_refused(self, api):
        with self.assertRaises(merge.Ineligible):
            api.run()
        self.assertEqual(api.writes, [])

    def test_read_only_by_default(self):
        api = Github()
        result = merge.process(api, HUB, 7, api.module, TARGET)
        self.assertTrue(result["eligible"])
        self.assertFalse(api.writes)

    def test_valid_pointer_merges_once_with_exact_head(self):
        api = Github()
        self.assertTrue(api.run()["merged"])
        self.assertEqual(len(api.writes), 1)
        path, method, body = api.writes[0]
        self.assertEqual(path, api.endpoint + "/merge")
        self.assertEqual(method, "PUT")
        self.assertEqual(body["sha"], HEAD)
        self.assertEqual(body["merge_method"], "squash")

    def test_item_editor_uses_master(self):
        api = Github("hero-siege-item-editor", "master")
        self.assertTrue(api.run()["merged"])
        self.assertIn(api.latest, api.reads)

    def test_original_pr_base_does_not_hide_the_live_hub_pointer(self):
        api = Github()
        api.pr["base"]["sha"] = "9" * 40
        self.assertTrue(api.run()["merged"])
        self.assertIn(f"repos/{HUB}/git/commits/{BASE}", api.reads)

    def test_hub_advancing_during_validation_leaves_pr_open(self):
        api = Github()
        def change(client, path):
            if path == f"repos/{HUB}/commits/main" and client.reads.count(path) == 2:
                client.responses[path]["sha"] = "f" * 40
        api.on_read = change
        self.assert_refused(api)

    def test_rejects_unknown_inputs_before_any_api_call(self):
        for repo, module, sha in [("other/hub", "ForgePact", TARGET),
                                   (HUB, "../ForgePact", TARGET),
                                   (HUB, "ForgePact", "not-a-sha")]:
            api = Github()
            with self.assertRaises(merge.Ineligible):
                merge.process(api, repo, 7, module, sha, merge=True)
            self.assertEqual(api.reads + api.writes, [])

    def test_human_fork_draft_wrong_branch_and_extra_files_are_refused(self):
        changes = [
            lambda p: p["user"].update(login="S-Borkowski", type="User"),
            lambda p: p["head"]["repo"].update(full_name="S-Borkowski/hero-siege-offline-toolkit"),
            lambda p: p.update(draft=True),
            lambda p: p.update(state="closed"),
            lambda p: p["base"].update(ref="feature/toolkit-hub"),
            lambda p: p["head"].update(ref="feature/toolkit-hub"),
            lambda p: p.update(changed_files=2),
        ]
        for change in changes:
            with self.subTest(change=change):
                api = Github()
                change(api.pr)
                self.assert_refused(api)

    def test_an_ordinary_file_or_wrong_pointer_cannot_pass(self):
        for field, value in [("mode", "100644"), ("type", "blob"), ("sha", OLD)]:
            api = Github()
            api.responses[f"repos/{HUB}/git/trees/head-tree"]["tree"][0][field] = value
            self.assert_refused(api)

    def test_wrong_deleted_or_extra_changed_files_are_refused(self):
        for files in [[{"filename": ".github/workflows/evil.yml", "status": "modified"}],
                      [{"filename": "ForgePact", "status": "removed"}],
                      [{"filename": "ForgePact", "status": "modified"}] * 2]:
            api = Github()
            api.responses[f"{api.endpoint}/files?per_page=100"] = files
            self.assert_refused(api)

    def test_rollback_divergence_and_stale_target_are_refused(self):
        for status in ["behind", "diverged", "identical"]:
            api = Github()
            api.responses[f"repos/falorfrozen-cmd/ForgePact/compare/{OLD}...{TARGET}"]["status"] = status
            self.assert_refused(api)
        api = Github()
        api.responses[api.latest]["sha"] = "f" * 40
        self.assert_refused(api)

    def test_unmerged_or_updated_head_is_refused_at_last_read(self):
        for side in ["head", "base"]:
            api = Github()
            def change(client, path):
                if path == client.endpoint and client.reads.count(path) == 2:
                    client.pr[side]["sha"] = "f" * 40
            api.on_read = change
            self.assert_refused(api)

    def test_upstream_advancing_during_validation_is_refused(self):
        api = Github()
        def change(client, path):
            if path == client.latest and client.reads.count(path) == 2:
                client.responses[path]["sha"] = "f" * 40
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
        api.responses[f"repos/{HUB}/commits/{HEAD}/status"] = {"total_count": 1, "state": "pending"}
        self.assert_refused(api)

    def test_conflicts_unknown_state_and_required_reviews_are_refused(self):
        for mergeable, state in [(False, "dirty"), (None, "unknown"), (True, "blocked"),
                                 (True, "behind"), (True, "unstable")]:
            api = Github()
            api.pr.update(mergeable=mergeable, mergeable_state=state)
            self.assert_refused(api)

    def test_successful_checks_allow_merge(self):
        api = Github()
        api.responses[f"repos/{HUB}/commits/{HEAD}/status"] = {"total_count": 1, "state": "success"}
        api.responses[f"repos/{HUB}/commits/{HEAD}/check-runs?per_page=100"] = {
            "total_count": 1, "check_runs": [{"status": "completed", "conclusion": "success"}]}
        self.assertTrue(api.run()["merged"])

    def test_merge_rejection_is_not_retried(self):
        api = Github()
        def reject(path, **kwargs):
            if kwargs.get("method") == "PUT":
                api.writes.append(path)
                raise subprocess.CalledProcessError(1, "gh api merge")
            return api(path, **kwargs)
        with self.assertRaises(subprocess.CalledProcessError):
            merge.process(reject, HUB, 7, "ForgePact", TARGET, merge=True)
        self.assertEqual(len(api.writes), 1)


if __name__ == "__main__":
    unittest.main()
