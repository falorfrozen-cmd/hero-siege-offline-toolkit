"""Keep an issue on the "Hero Siege Tools" board, in the column its work is in.

Run it:

    py -3 tools/issue_board.py move falorfrozen-cmd/ForgePact 114 "In Progress"
    py -3 tools/issue_board.py move falorfrozen-cmd/hero-siege-offline-toolkit 176 Todo
    py -3 tools/issue_board.py check-title "[QoL] Stash tabs renaming"

`move` adds the issue to user project 1 of `falorfrozen-cmd` if it is not
there yet, sets its Status, and sets its `Development` iteration to the one
running today. An issue the project's auto-add picked up has none of those, so
it sits on the project but in no column of the board the owner looks at --
which is how ForgePact #74 went missing twice. Pass `--no-iteration` to leave
the iteration alone.

`check-title` exits non-zero unless the title starts with one of the type
prefixes in `PREFIXES`, which is the convention AGENTS.md § "Every Piece of
Work Belongs to an Issue on the Board" asks for.

Everything goes through `gh`, which needs the `project` scope
(`gh auth refresh -s project`); without it the edit fails and this says so
rather than reporting the issue as moved.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys

OWNER = "falorfrozen-cmd"
PROJECT_NUMBER = 1
STATUSES = ("Backlog", "Todo", "In Progress", "Done", "Impossible")
PREFIXES = (
    "Bug",
    "QoL",
    "Mod",
    "Adjustment",
    "Research",
    "Tooling",
    "Docs",
)
_PREFIX_RE = re.compile(r"^\[(?P<prefix>[^\]]+)\]\s+\S")


def title_prefix(title: str) -> str | None:
    """The canonical prefix a title carries, or None. Case-insensitive, so the
    older `[BUG]` titles still count."""
    m = _PREFIX_RE.match(title.strip())
    if not m:
        return None
    wanted = m.group("prefix").strip().lower()
    for p in PREFIXES:
        if p.lower() == wanted:
            return p
    return None


def current_iteration(iterations: list[dict], today: _dt.date) -> dict | None:
    """The iteration whose [startDate, startDate + duration) contains today."""
    for it in iterations:
        start = _dt.date.fromisoformat(it["startDate"])
        if start <= today < start + _dt.timedelta(days=int(it["duration"])):
            return it
    return None


def _gh(*args: str) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise SystemExit(f"gh {' '.join(args[:3])} ... failed:\n{proc.stderr.strip()}")
    return proc.stdout


def _graphql(query: str, **variables: str) -> dict:
    args = ["api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        args += ["-F", f"{k}={v}"]
    return json.loads(_gh(*args))["data"]


_PROJECT_QUERY = """
query($owner: String!, $number: Int!) {
  user(login: $owner) {
    projectV2(number: $number) {
      id
      status: field(name: "Status") {
        ... on ProjectV2SingleSelectField { id options { id name } }
      }
      development: field(name: "Development") {
        ... on ProjectV2IterationField { id configuration { iterations { id title startDate duration } } }
      }
    }
  }
}
"""


def move(repo: str, number: int, status: str, set_iteration: bool) -> None:
    if status not in STATUSES:
        raise SystemExit(f"unknown status {status!r}; one of {', '.join(STATUSES)}")
    issue = json.loads(_gh("issue", "view", str(number), "-R", repo, "--json", "url,title"))
    if title_prefix(issue["title"]) is None:
        print(f"warning: {repo}#{number} has no type prefix: {issue['title']!r}", file=sys.stderr)

    project = _graphql(_PROJECT_QUERY, owner=OWNER, number=str(PROJECT_NUMBER))["user"]["projectV2"]
    item = json.loads(_gh(
        "project", "item-add", str(PROJECT_NUMBER), "--owner", OWNER,
        "--url", issue["url"], "--format", "json",
    ))
    option = next(o for o in project["status"]["options"] if o["name"] == status)
    _gh(
        "project", "item-edit", "--project-id", project["id"], "--id", item["id"],
        "--field-id", project["status"]["id"], "--single-select-option-id", option["id"],
    )
    done = [f"Status={status}"]
    if set_iteration:
        it = current_iteration(
            project["development"]["configuration"]["iterations"], _dt.date.today()
        )
        if it is None:
            done.append("iteration NOT set (none running today)")
        else:
            _gh(
                "project", "item-edit", "--project-id", project["id"], "--id", item["id"],
                "--field-id", project["development"]["id"], "--iteration-id", it["id"],
            )
            done.append(f"Development={it['title']}")
    print(f"{repo}#{number}: {', '.join(done)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    mv = sub.add_parser("move", help="add to the board and set Status (+ current iteration)")
    mv.add_argument("repo")
    mv.add_argument("number", type=int)
    mv.add_argument("status", choices=STATUSES)
    mv.add_argument("--no-iteration", action="store_true")
    ct = sub.add_parser("check-title", help="exit 1 unless the title has a type prefix")
    ct.add_argument("title")
    args = ap.parse_args(argv)

    if args.cmd == "check-title":
        prefix = title_prefix(args.title)
        if prefix is None:
            print(f"no type prefix; start the title with one of: "
                  f"{', '.join(f'[{p}]' for p in PREFIXES)}", file=sys.stderr)
            return 1
        print(prefix)
        return 0
    move(args.repo, args.number, args.status, not args.no_iteration)
    return 0


if __name__ == "__main__":
    sys.exit(main())
