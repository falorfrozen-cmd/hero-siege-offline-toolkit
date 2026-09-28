#!/usr/bin/env python3
"""save_item_keys.py -- every item key in a Hero Siege save file, by the container it sits in.

ForgePact issue #68 ("Move all" from the bag into the stash) has to show, after
a session, that a moved item's key is saved under a stash container and under
no bag container, and that it is saved exactly once. This prints, for one or
more `.hss` files, every item key (`0-0-<n>-<class>`) found as an object key,
grouped by the container it sits under. Every container is listed; none is
filtered out, so the personal stash, the equipped items and the bag's own tabs
show up beside the shared stash's tabs.

The files are decoded with hero-siege-item-editor's own decoder (imported from
that submodule, the way tools/stash_tab_counts.py imports it, never copied - the
codec and its key live there). Three layouts are read, all measured on the
owner's saves on 2026-09-28:

- `stash.hss` decodes to one JSON object whose keys are the containers
  (`stash_tab_<n>`, `material_tab`, `socket_tab`, `unique_items`, ...);
- `inventory_order_<slot>.hss` decodes to one JSON object too, and holds the
  bag (`inventory_tab_0`..`inventory_tab_4`, `inventory_material_tab`,
  `inventory_charms`, ...);
- `herosiege<slot>.hss` decodes to `key="value"` lines, some of whose values
  are base64 of a JSON object; `inventory="..."` holds `personal_stash`,
  `equipped_items` and `potions`. Each such field is read as a container named
  after the field, so the personal stash prints as `inventory.personal_stash`.

A container is the dotted path to the object that holds the keys. A key that
appears only as a string value (a reference, not an entry) is not listed.

It is a read-only cross-check, not a mechanism: the game owns these files while
it runs and rewrites them on exit, so run it with the game closed and read the
answer as "the last saved state". Nothing is ever written. A missing or
undecodable file exits non-zero with one line.

Usage:
    py -3 tools/save_item_keys.py <file.hss> [<file.hss> ...]
    py -3 tools/save_item_keys.py <file.hss> --key 0-0-123-7    # only where these keys are
    py -3 tools/save_item_keys.py <file.hss> --json             # machine-readable
"""
from __future__ import annotations

import argparse
import base64
import binascii
import importlib
import json
import re
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITOR_DIR = ROOT / "hero-siege-item-editor"
ITEM_KEY = re.compile(r"0-0-\d+--?\d+")
# One `name="value"` line of a character file; only a value that is base64 of a
# JSON object or array is read, anything else (numbers, names) is skipped.
FIELD = re.compile(r'(?m)^\s*([A-Za-z_][\w]*)="([A-Za-z0-9+/=]+)"\s*$')


class SaveKeysError(Exception):
    """A refusal: the one line the tool prints before exiting non-zero."""


def load_editor():
    """hero-siege-item-editor's GUI module, for its codec (decode_hss). Refuses with
    the command that initializes it, on the same two files
    tests/test_save_item_keys.py requires before it runs."""
    if not all((EDITOR_DIR / name).is_file() for name in ("hs_item_editor_gui.py", "hss_recovery.py")):
        raise SaveKeysError(
            f"hero-siege-item-editor is not initialized at {EDITOR_DIR} "
            "(py -3 .claude/skills/workorder/ensure_submodule.py hero-siege-item-editor)")
    if str(EDITOR_DIR) not in sys.path:
        sys.path.insert(0, str(EDITOR_DIR))
    return importlib.import_module("hs_item_editor_gui")


def decode_text(path: Path) -> str:
    """The file's decoded text. The editor's decode_hss only reads the file."""
    if not path.is_file():
        raise SaveKeysError(f"save_item_keys: {path} not found - nothing read")
    editor = load_editor()
    try:
        return editor.decode_hss(path)
    except (ValueError, binascii.Error, zlib.error, OSError, UnicodeError) as exc:
        raise SaveKeysError(f"save_item_keys: {path} could not be decoded ({type(exc).__name__}: {exc})") from exc


def _embedded_json(value: str):
    """A field value that is base64 of a JSON object or array, else None."""
    try:
        raw = base64.b64decode(value, validate=True)
        parsed = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeError):
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def documents(text: str, path: Path) -> list[tuple[str, object]]:
    """(root name, parsed JSON) pairs: the whole text when it is JSON, else one per
    `name="<base64 JSON>"` field. A text with neither is refused."""
    try:
        whole = json.loads(text)
    except ValueError:
        whole = None
    if isinstance(whole, (dict, list)):
        return [("", whole)]
    found: list[tuple[str, object]] = []
    seen: dict[str, int] = {}
    for match in FIELD.finditer(text):
        parsed = _embedded_json(match.group(2))
        if parsed is None:
            continue
        name = match.group(1)
        seen[name] = seen.get(name, 0) + 1
        found.append((name if seen[name] == 1 else f"{name}#{seen[name]}", parsed))
    if not found:
        raise SaveKeysError(f"save_item_keys: {path} decoded, but holds neither JSON nor a base64 JSON field")
    return found


def collect(node, container: str, out: dict) -> None:
    """Record every item key held as an object key, under the dotted path of the
    object that holds it, then walk every value (an entry can hold containers)."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and ITEM_KEY.fullmatch(key):
                out.setdefault(container, []).append(key)
            child = f"{container}.{key}" if container else str(key)
            collect(value, child, out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            collect(value, f"{container}.{index}" if container else str(index), out)


def item_keys(path: Path) -> dict:
    """Container -> sorted item keys for one file."""
    out: dict = {}
    for root, document in documents(decode_text(path), path):
        collect(document, root, out)
    return {name: sorted(keys) for name, keys in sorted(out.items())}


def render_text(results: list[tuple[Path, dict]], wanted: set[str]) -> str:
    lines = []
    for path, containers in results:
        lines.append(f"save_item_keys: {path} (read-only; the last saved state - run it with the game closed)")
        if not containers:
            lines.append("  no item keys in this file")
        for name, keys in containers.items():
            shown = [k for k in keys if not wanted or k in wanted]
            if wanted and not shown:
                continue
            lines.append(f"{name}: keys={len(keys)}")
            lines.extend(f"  {key}" for key in shown)
    if wanted:
        for key in sorted(wanted):
            places = [f"{path.name}:{name}" for path, containers in results
                      for name, keys in containers.items() if key in keys]
            lines.append(f"key {key}: " + (", ".join(places) if places else "not in any file read"))
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="save_item_keys.py",
        description="List every item key (0-0-<n>-<class>) in Hero Siege .hss files, grouped by the container "
                    "it sits under, read-only, with hero-siege-item-editor's own decoder. Run it with the game "
                    "closed: the files are the last saved state.")
    parser.add_argument("paths", nargs="+", type=Path, help="one or more .hss files (stash, inventory_order, herosiege)")
    parser.add_argument("--key", action="append", default=[], metavar="KEY",
                        help="show only these keys, and where each one is (repeatable)")
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    args = parser.parse_args(argv)
    for key in args.key:
        if not ITEM_KEY.fullmatch(key):
            print(f"save_item_keys: --key {key!r} is not an item key (0-0-<n>-<class>) - nothing read", file=sys.stderr)
            return 2
    try:
        results = [(path, item_keys(path)) for path in args.paths]
    except SaveKeysError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    wanted = set(args.key)
    if args.json:
        payload = {"files": {str(path): containers for path, containers in results}}
        if wanted:
            payload["keys"] = {key: [{"file": str(path), "container": name} for path, containers in results
                                     for name, keys in containers.items() if key in keys]
                               for key in sorted(wanted)}
        print(json.dumps(payload, indent=1, sort_keys=True))
    else:
        print(render_text(results, wanted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
