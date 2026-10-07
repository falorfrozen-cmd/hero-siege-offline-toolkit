"""Merge only the bot PR produced by this dispatch, after read-only validation.

Uses gh's existing authentication; never reads a token itself. No PR or tool code
is checked out or executed. Without --merge the command only checks eligibility.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from urllib.parse import quote


HUB = "falorfrozen-cmd/hero-siege-offline-toolkit"
TOOLS = frozenset({
    "ForgePact", "HSCraftSim", "HSSaveEditor", "HSSaveEditor-SteamDeck-",
    "HS-Offline-Launcher", "HS-Offline-Tracker", "HS-ValueEditor",
    "Hs-Offline-Loot-Forge", "hs-stat-forge", "hero-siege-item-editor",
})


class Ineligible(ValueError):
    """Leave this PR open for a person; do not weaken repository rules."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise Ineligible(reason)


def gh_api(path: str, *, method: str = "GET", body: dict | None = None):
    command = ["gh", "api", "--method", method, path]
    if body is not None:
        command += ["--input", "-"]
    result = subprocess.run(
        command, input=json.dumps(body) if body is not None else None,
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def pointer(api, repository: str, commit: str, path: str) -> str:
    tree = api(f"repos/{repository}/git/commits/{commit}")["tree"]["sha"]
    entries = api(f"repos/{repository}/git/trees/{tree}")
    require(not entries.get("truncated", False), "Git tree response is incomplete.")
    matches = [e for e in entries["tree"] if e["path"] == path]
    require(len(matches) == 1, "Expected one submodule entry.")
    entry = matches[0]
    require(entry["mode"] == "160000" and entry["type"] == "commit",
            "The changed entry is not a git submodule pointer.")
    return entry["sha"]


def identity(pr: dict, repository: str, branch: str, module: str, target: str) -> None:
    require(pr["state"] == "open" and not pr.get("merged", False), "PR is not open.")
    require(not pr.get("draft", False), "Draft PRs need manual review.")
    require(pr["user"]["login"] == "github-actions[bot]" and pr["user"]["type"] == "Bot",
            "PR was not created by GitHub Actions.")
    require(pr["base"]["repo"]["full_name"] == repository
            and pr["base"]["ref"] == branch, "PR does not target the hub default branch.")
    require(pr["head"].get("repo") is not None
            and pr["head"]["repo"]["full_name"] == repository,
            "Fork PRs must never be automatically merged here.")
    require(pr["head"]["ref"] == f"auto/bump-{module}-{target[:7]}",
            "PR branch does not match this dispatch.")
    require(pr["changed_files"] == 1, "PR changes more than one file.")


def check_statuses(api, repository: str, head: str) -> None:
    status = api(f"repos/{repository}/commits/{head}/status")
    require(status["total_count"] == 0 or status["state"] == "success",
            "Commit statuses are pending or failing.")
    checks = api(f"repos/{repository}/commits/{head}/check-runs?per_page=100")
    require(checks["total_count"] == len(checks["check_runs"]),
            "Too many checks to validate in one response; review manually.")
    for check in checks["check_runs"]:
        require(check["status"] == "completed"
                and check["conclusion"] in {"success", "neutral", "skipped"},
                "A check is pending or failing.")


def process(api, repository: str, number: int, module: str, target: str,
            *, merge: bool = False) -> dict:
    require(repository == HUB, "Automatic merging is limited to the canonical hub.")
    require(module in TOOLS, "Unknown tool.")
    require(number > 0 and re.fullmatch(r"[0-9a-f]{40}", target) is not None,
            "Invalid pull request number or target SHA.")
    repo = api(f"repos/{repository}")
    branch = repo["default_branch"]
    require(repo.get("allow_squash_merge", False), "Squash merging is disabled.")
    endpoint = f"repos/{repository}/pulls/{number}"
    pr = api(endpoint)
    identity(pr, repository, branch, module, target)
    head = pr["head"]["sha"]
    pr_base = pr["base"]["sha"]
    base = api(f"repos/{repository}/commits/{quote(branch, safe='')}")["sha"]
    # PR base.sha can still name the original base after another pointer PR
    # merges. Compare ancestry against the live hub pointer, not that old tree.

    files = api(f"{endpoint}/files?per_page=100")
    require(len(files) == 1 and files[0]["filename"] == module
            and files[0]["status"] == "modified", "PR is not a single pointer update.")
    require(pointer(api, repository, head, module) == target, "PR points to a different SHA.")
    old = pointer(api, repository, base, module)
    require(old != target, "Hub already records this SHA.")

    upstream = f"falorfrozen-cmd/{module}"
    upstream_branch = api(f"repos/{upstream}")["default_branch"]
    latest_path = f"repos/{upstream}/commits/{quote(upstream_branch, safe='')}"
    require(api(latest_path)["sha"] == target,
            "Target is not the tool's current default-branch tip; leave stale PR open.")
    comparison = api(f"repos/{upstream}/compare/{old}...{target}")
    require(comparison["status"] == "ahead", "Pointer would roll back or cross divergent history.")
    check_statuses(api, repository, head)

    # Re-read mutable data after validation. The merge API additionally matches
    # the exact PR head, so a subsequent push cannot silently change our diff.
    current = api(endpoint)
    identity(current, repository, branch, module, target)
    require(current["head"]["sha"] == head and current["base"]["sha"] == pr_base,
            "PR changed during validation; leave it for the next dispatch/review.")
    require(api(f"repos/{repository}/commits/{quote(branch, safe='')}")["sha"] == base,
            "Hub default branch changed during validation; leave PR open.")
    require(current.get("mergeable") is True
            and current.get("mergeable_state") == "clean",
            "PR is conflicted, awaiting checks/reviews, or mergeability is unknown.")
    require(api(latest_path)["sha"] == target, "A newer tool commit arrived during validation.")
    if not merge:
        return {"eligible": True, "number": number, "head": head, "target": target}
    result = api(f"{endpoint}/merge", method="PUT", body={
        "sha": head, "merge_method": "squash",
        "commit_title": f"chore: bump {module} to {target[:7]} (#{number})",
    })
    require(result.get("merged") is True, "GitHub did not merge the PR; manual review required.")
    return {"merged": True, "number": number, "sha": result["sha"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=HUB)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--submodule", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--merge", action="store_true", help="Merge after validation (default: read-only).")
    args = parser.parse_args()
    try:
        result = process(gh_api, args.repository, args.pull_request, args.submodule,
                         args.sha, merge=args.merge)
    except Ineligible as error:
        print(f"Left for manual review: {error}")
        return 0
    except (subprocess.CalledProcessError, KeyError, TypeError, json.JSONDecodeError) as error:
        # Never retry a mutation blindly. A failed/uncertain request is visible
        # in the job; inspect the PR before rerunning it.
        print(f"Could not validate or merge the pointer PR: {error}")
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
