"""tools/issue_board.py: the parts that do not need GitHub."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import issue_board  # noqa: E402


def test_title_prefix_accepts_the_board_convention():
    assert issue_board.title_prefix("[QoL] Stash tabs renaming") == "QoL"
    assert issue_board.title_prefix("[Mod] Mining Ore Slider") == "Mod"
    # the older upper-case spelling still counts
    assert issue_board.title_prefix("[BUG] Allow to run tools without updating") == "Bug"


def test_title_prefix_rejects_missing_or_unknown_prefixes():
    assert issue_board.title_prefix("Dungeon issue") is None
    assert issue_board.title_prefix("workorder: run steps in lanes") is None
    assert issue_board.title_prefix("[Whatever] something") is None
    assert issue_board.title_prefix("[Bug]") is None  # prefix with no title


def test_check_title_exit_codes():
    assert issue_board.main(["check-title", "[Research] drop roll"]) == 0
    assert issue_board.main(["check-title", "drop roll"]) == 1


def test_current_iteration_picks_the_running_one():
    its = [
        {"id": "a", "title": "Development 2", "startDate": "2026-09-25", "duration": 7},
        {"id": "b", "title": "Development 3", "startDate": "2026-10-02", "duration": 7},
    ]
    assert issue_board.current_iteration(its, dt.date(2026, 9, 28))["id"] == "a"
    assert issue_board.current_iteration(its, dt.date(2026, 10, 1))["id"] == "a"
    assert issue_board.current_iteration(its, dt.date(2026, 10, 2))["id"] == "b"
    assert issue_board.current_iteration(its, dt.date(2026, 10, 9)) is None
