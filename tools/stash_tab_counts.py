#!/usr/bin/env python3
"""stash_tab_counts.py -- what the shared stash's special tabs hold, read from the save.

ForgePact issue #14 (crafting from the stash's special tabs) needs an in-game
reader that finds the Socketable and Materials tabs' contents. A reader's sum
means nothing until it is compared with a count taken some other way, and the
eye is one way; this is the other. It decodes the shared stash file,
`%LOCALAPPDATA%\\Hero_Siege\\hs2saves\\stash.hss`, with hero-siege-item-editor's
own decoder (imported from that submodule, never copied - the codec and its key
live there), and prints, for every tab key matching `socket_tab(_N)?` or
`material_tab(_N)?`, the entry count and the summed stack per (class, b):

- class is the item key's trailing number (`0-0-<n>-<class>`),
- b is the entry's `data.b` (the base item id),
- the stack is `data.o`, a missing `o` counting as one (the editor's own
  `native_stack_count`).

Ordinary grid tabs (`stash_tab_<n>`), the Unique tab and the personal stash
are never counted.

It is a read-only cross-check, not a mechanism: the game owns the file while
it runs and rewrites it on exit, so run this with the game closed, and read the
answer as "the last saved state". The file is opened for reading only, and
nothing is ever written. A missing or undecodable file exits non-zero with one
line.

Usage:
    py -3 tools/stash_tab_counts.py                  # the live save directory
    py -3 tools/stash_tab_counts.py --path <file>    # any stash.hss (a backup)
    py -3 tools/stash_tab_counts.py --json           # machine-readable

The save directory is found the way tools/hs_drive_mcp/saves.py's save_dir()
finds it: `HS_DRIVE_SAVE_DIR` when set, else `%LOCALAPPDATA%\\Hero_Siege\\hs2saves`.
"""
from __future__ import annotations

import argparse
import binascii
import importlib
import json
import re
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITOR_DIR = ROOT / "hero-siege-item-editor"
STASH_FILE = "stash.hss"
SPECIAL_TAB = re.compile(r"(socket_tab|material_tab)(_[1-9]\d*)?")
BASE_TABS = ("socket_tab", "material_tab")


class StashCountError(Exception):
    """A refusal: the one line the tool prints before exiting non-zero."""


def save_dir() -> Path:
    """The live save directory, resolved as tools/hs_drive_mcp/saves.py does."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.hs_drive_mcp import saves
    return saves.save_dir()


def load_editor():
    """hero-siege-item-editor's GUI module, for its codec (decode_hss/encode_hss)
    and native_stack_count. Refuses with the command that initializes it."""
    if not (EDITOR_DIR / "hs_item_editor_gui.py").is_file():
        raise StashCountError(
            f"hero-siege-item-editor is not initialized at {EDITOR_DIR} "
            "(py -3 .claude/skills/workorder/ensure_submodule.py hero-siege-item-editor)")
    if str(EDITOR_DIR) not in sys.path:
        sys.path.insert(0, str(EDITOR_DIR))
    return importlib.import_module("hs_item_editor_gui")


def load_document(path: Path) -> dict:
    """The decoded stash document. The editor's decode_hss only reads the file."""
    if not path.is_file():
        raise StashCountError(f"stash_tab_counts: {path} not found - nothing read")
    editor = load_editor()
    try:
        text = editor.decode_hss(path)
    except (ValueError, binascii.Error, zlib.error, OSError, UnicodeError) as exc:
        raise StashCountError(f"stash_tab_counts: {path} could not be decoded ({type(exc).__name__}: {exc})") from exc
    try:
        document = json.loads(text)
    except ValueError as exc:
        raise StashCountError(f"stash_tab_counts: {path} decoded, but is not JSON ({exc})") from exc
    if not isinstance(document, dict):
        raise StashCountError(f"stash_tab_counts: {path} decoded to {type(document).__name__}, not a stash document")
    return document


def _whole(value):
    """An integral number as int, anything else as given (so it is still shown)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _order(value):
    """Numbers first, in numeric order; anything else after, as text."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (0, value, "")
    return (1, 0, str(value))


def count_tabs(document: dict, native_stack_count) -> dict:
    """Per special tab: entries, stacks per (class, b), and entries skipped with why."""
    tabs: dict = {}
    for key in sorted(document):
        if not SPECIAL_TAB.fullmatch(key):
            continue
        entries = document[key]
        report = {"entries": 0, "stacks": [], "skipped": []}
        tabs[key] = report
        if not isinstance(entries, dict):
            report["skipped"].append({"item": None, "why": f"the tab is {type(entries).__name__}, not an object"})
            continue
        sums: dict = {}
        for item_key, entry in entries.items():
            report["entries"] += 1
            data = entry.get("data") if isinstance(entry, dict) else None
            tail = str(item_key).rsplit("-", 1)[-1]
            cls = int(tail) if tail.isdigit() else tail
            if not isinstance(data, dict) or "b" not in data:
                report["skipped"].append({"item": item_key, "why": "no data.b"})
                continue
            stack = native_stack_count(data)
            if stack is None:
                report["skipped"].append({"item": item_key, "why": f"data.o is not a positive whole stack ({data.get('o')!r})"})
                continue
            slot = sums.setdefault((str(cls), str(_whole(data["b"]))), {"class": cls, "b": _whole(data["b"]), "stack": 0, "entries": 0})
            slot["stack"] += stack
            slot["entries"] += 1
        report["stacks"] = sorted(sums.values(), key=lambda r: (_order(r["class"]), _order(r["b"])))
    return tabs


def render_text(path: Path, tabs: dict) -> str:
    lines = [f"stash_tab_counts: {path} (read-only; the last saved state - run it with the game closed)"]
    for base in BASE_TABS:
        if not any(SPECIAL_TAB.fullmatch(k).group(1) == base for k in tabs):
            lines.append(f"{base}: not in the document")
    for key, report in tabs.items():
        lines.append(f"{key}: entries={report['entries']}")
        for row in report["stacks"]:
            lines.append(f"  class={row['class']} b={row['b']} stack={row['stack']} entries={row['entries']}")
        for skip in report["skipped"]:
            lines.append(f"  skipped {skip['item']}: {skip['why']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="stash_tab_counts.py",
        description="Sum the shared stash's Socketable (socket_tab*) and Materials (material_tab*) tabs per "
                    "(class, b) from stash.hss, read-only, with hero-siege-item-editor's own decoder. "
                    "Run it with the game closed: the file is the last saved state.")
    parser.add_argument("--path", type=Path, help="a stash.hss to read (default: <save dir>\\stash.hss)")
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    args = parser.parse_args(argv)
    try:
        path = args.path if args.path else save_dir() / STASH_FILE
        document = load_document(path)
        tabs = count_tabs(document, load_editor().native_stack_count)
    except StashCountError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"path": str(path), "tabs": tabs}, indent=1, sort_keys=True))
    else:
        print(render_text(path, tabs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
