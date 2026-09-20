"""Merge only the catalog PR this catalog.yml run opened, after read-only validation.

The same boundary as merge_submodule_pointer.py, applied to the catalog: the
PR must be the bot's own `catalog/regenerate` branch, change nothing but the
signed catalog pair, and still sit at the exact commit this run built, signed,
verified and tested. Anything else is left open for a person.

Uses gh's existing authentication; never reads a token itself. No PR code is
checked out or executed. Without --merge the command only checks eligibility.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from urllib.parse import quote


HUB = "falorfrozen-cmd/hero-siege-offline-toolkit"
BRANCH = "catalog/regenerate"
FILES = frozenset({"catalog/catalog.json", "catalog/catalog.json.minisig"})


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


def identity(pr: dict, repository: str, branch: str, head: str) -> None:
    require(pr["state"] == "open" and not pr.get("merged", False), "PR is not open.")
    require(not pr.get("draft", False), "Draft PRs need manual review.")
    require(pr["user"]["login"] == "github-actions[bot]" and pr["user"]["type"] == "Bot",
            "PR was not created by GitHub Actions.")
    require(pr["base"]["repo"]["full_name"] == repository
            and pr["base"]["ref"] == branch, "PR does not target the hub default branch.")
    require(pr["head"].get("repo") is not None
            and pr["head"]["repo"]["full_name"] == repository,
            "Fork PRs must never be automatically merged here.")
    require(pr["head"]["ref"] == BRANCH, "PR branch is not the catalog regenerate branch.")
    # The commit this run signed and verified. A later push to the branch is
    # content this run never checked.
    require(pr["head"]["sha"] == head, "PR head is not the commit this run built.")


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


def process(api, repository: str, number: int, head: str, *, merge: bool = False,
            attempts: int = 6, sleep=time.sleep) -> dict:
    require(repository == HUB, "Automatic merging is limited to the canonical hub.")
    require(number > 0 and re.fullmatch(r"[0-9a-f]{40}", head) is not None,
            "Invalid pull request number or head SHA.")
    repo = api(f"repos/{repository}")
    branch = repo["default_branch"]
    require(repo.get("allow_squash_merge", False), "Squash merging is disabled.")
    endpoint = f"repos/{repository}/pulls/{number}"
    identity(api(endpoint), repository, branch, head)

    files = api(f"{endpoint}/files?per_page=100")
    require({f["filename"] for f in files} <= FILES
            and all(f["status"] == "modified" for f in files)
            and "catalog/catalog.json" in {f["filename"] for f in files},
            "PR changes something other than the signed catalog pair.")
    check_statuses(api, repository, head)

    # Re-read mutable data after validation. The merge API additionally matches
    # the exact PR head, so a subsequent push cannot silently change our diff.
    # GitHub computes mergeability in the background, and this runs seconds
    # after the PR was opened, so null here means "not yet", not "no".
    for _ in range(attempts):
        current = api(endpoint)
        if current.get("mergeable") is not None:
            break
        sleep(5)
    identity(current, repository, branch, head)
    require(current.get("mergeable") is True
            and current.get("mergeable_state") == "clean",
            "PR is conflicted, awaiting checks/reviews, or mergeability is unknown.")
    if not merge:
        return {"eligible": True, "number": number, "head": head}
    result = api(f"{endpoint}/merge", method="PUT", body={
        "sha": head, "merge_method": "squash",
        "commit_title": f"Regenerate the tool catalog (#{number})",
    })
    require(result.get("merged") is True, "GitHub did not merge the PR; manual review required.")
    return {"merged": True, "number": number, "sha": result["sha"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=HUB)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--head", required=True, help="The commit this run pushed to the PR branch.")
    parser.add_argument("--merge", action="store_true", help="Merge after validation (default: read-only).")
    parser.add_argument("--output", help="Append merged=true|false here (GITHUB_OUTPUT).")
    args = parser.parse_args()
    merged = False
    try:
        result = process(gh_api, args.repository, args.pull_request, args.head,
                         merge=args.merge)
        merged = result.get("merged", False)
        print(json.dumps(result))
        code = 0
    except Ineligible as error:
        print(f"Left for manual review: {error}")
        code = 0
    except (subprocess.CalledProcessError, KeyError, TypeError, json.JSONDecodeError) as error:
        # Never retry a mutation blindly. A failed/uncertain request is visible
        # in the job; inspect the PR before rerunning it.
        print(f"Could not validate or merge the catalog PR: {error}")
        code = 1
    if args.output:
        with open(args.output, "a", encoding="utf-8") as out:
            out.write(f"merged={'true' if merged else 'false'}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
