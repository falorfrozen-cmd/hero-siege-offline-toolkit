"""Back up and restore `hs2saves\\`, refusing rather than risking a save.

Three rules hold everywhere in this module, and every refusal token exists to
keep one of them:

1. **Nothing is ever deleted.** A backup that fails verification is *renamed*
   to `<id>.failed`, not removed. A file the live directory has and the backup
   does not is *moved* into the pre-restore backup, never unlinked. A copy that
   fails its hash check leaves its `.hsdrive-tmp` file beside the target and
   the refusal names it. There is no code path in this file that removes a
   file, which is what makes "did it delete a save?" answerable by reading it.
2. **The gate is asked twice** -- once at the start and again immediately
   before the first write -- and `unknown` refuses exactly as hard as
   `running`. `docs/submodules/HSSaveEditor/instructions.md` § "Process
   Boundaries" records that the game rewrites these files on exit, so a backup
   taken mid-session is superseded before it could ever be restored; that is
   why backup is gated too, not only restore.
3. **A copy counts only once it has been re-read.** Every file is hashed at
   the source, copied, and hashed again from the copy. `AGENTS.md` § "Prove
   the Instrument Before Trusting a Negative Result" is about measurement, but
   the same distrust applies to a write: "shutil.copy2 returned" is not
   evidence that the bytes arrived.

Layout of a backup directory::

    <backup root>/<UTC yyyymmddTHHMMSSZ>_<label>/
        files/<every regular file that was directly in the save dir>
        manifest.json

The copies live in `files/` rather than beside the manifest so that a save
directory containing a file called `manifest.json` cannot collide with the
backup's own metadata. The manifest is written last, via a temp file and
`os.replace`, so a directory without one is unambiguously incomplete rather
than half-trustworthy.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from . import launcher_bridge, results

SCHEMA = "hs-drive-save-backup/1"
MANIFEST_NAME = "manifest.json"
FILES_DIR = "files"
CHARACTER_GLOB = "herosiege*.hss"
TEMP_SUFFIX = ".hsdrive-tmp"
FAILED_SUFFIX = ".failed"
PRE_RESTORE_LABEL = "pre-restore"

#: The measured directory is 1.5 MB across 137 files. The ceiling is here so a
#: mis-set HS_DRIVE_SAVE_DIR pointing at a game install refuses instead of
#: copying tens of gigabytes into %LOCALAPPDATA%.
MAX_SOURCE_BYTES = 256 * 1024 * 1024

LABEL_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,40}$")

_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

Gate = Callable[[], str]


# --------------------------------------------------------------------------
# Locations. Both overrides exist so no test ever resolves the real directory.
# --------------------------------------------------------------------------

def save_dir() -> Path:
    """The live save directory. `HS_DRIVE_SAVE_DIR` wins when set."""
    override = os.environ.get("HS_DRIVE_SAVE_DIR")
    if override:
        return Path(override)
    return launcher_bridge.local_app_data() / "Hero_Siege" / "hs2saves"


def backup_root() -> Path:
    """Where backups accumulate. `HS_DRIVE_BACKUP_DIR` wins when set."""
    override = os.environ.get("HS_DRIVE_BACKUP_DIR")
    if override:
        return Path(override)
    return launcher_bridge.local_app_data() / "HSDriveMcp" / "save-backups"


# --------------------------------------------------------------------------
# Seams: both are module level so a test can replace them without touching a
# real file system, and so a corrupted copy is reachable in a test at all.
# --------------------------------------------------------------------------

def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(source: Path, target: Path) -> None:
    shutil.copy2(source, target)


def default_is_link(path: Path) -> bool:
    """Skip symlinks and junctions, as HSSaveEditor's scanner does.

    An entry whose kind cannot be read is treated as a link, i.e. skipped: an
    unreadable entry is the one case where copying might follow something the
    caller never meant to copy.
    """
    try:
        if path.is_symlink():
            return True
        info = os.lstat(path)
    except OSError:
        return True
    return bool(getattr(info, "st_file_attributes", 0) & _REPARSE)


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def _gate_refusal(tool: str, gate: Gate, when: str) -> dict[str, Any] | None:
    """Ask the gate. `unknown` refuses; it is never read as "not running"."""
    state = gate()
    if state == "running":
        return results.refuse(
            tool, "game_running",
            f"Hero_Siege.exe is running ({when}). Close the game first: it "
            "rewrites hs2saves on exit, so anything done now is undone then.")
    if state != "not_running":
        return results.refuse(
            tool, "game_state_unknown",
            f"The Windows process snapshot could not be read ({when}), so "
            "whether the game is running is unknown. Refusing rather than "
            "assuming it is closed.")
    return None


def _inventory(source: Path, is_link: Callable[[Path], bool]) -> tuple[list[Path], list[str], int]:
    """Regular files directly in `source`. Subdirectories are never descended."""
    files: list[Path] = []
    skipped: list[str] = []
    total = 0
    for entry in sorted(source.iterdir()):
        if is_link(entry):
            skipped.append(entry.name)
            continue
        if not entry.is_file():
            continue
        files.append(entry)
        total += entry.stat().st_size
    return files, skipped, total


def _utc_stamp() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _free_directory(root: Path, base: str) -> Path:
    """`<base>`, or `<base>-2`, `<base>-3`... Never reuses an existing one."""
    candidate = root / base
    counter = 2
    while candidate.exists():
        candidate = root / f"{base}-{counter}"
        counter += 1
    return candidate


def _mark_failed(directory: Path) -> Path:
    """Rename a partial backup out of the way. It is kept, not removed."""
    target = directory.with_name(directory.name + FAILED_SUFFIX)
    counter = 2
    while target.exists():
        target = directory.with_name(f"{directory.name}{FAILED_SUFFIX}-{counter}")
        counter += 1
    directory.rename(target)
    return target


def read_manifest(directory: Path) -> dict[str, Any] | None:
    """The manifest, or None when it is absent or unreadable."""
    path = directory / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        return None
    return data


def verify_backup(directory: Path) -> tuple[str, str] | None:
    """`None` when the backup is whole, else `(reason, detail)`.

    Re-hashes every file. A manifest that merely exists proves the backup
    finished, not that the bytes on disk are still the bytes it recorded.
    """
    if not directory.is_dir():
        return "backup_incomplete", f"No backup directory at {directory}."
    manifest = read_manifest(directory)
    if manifest is None:
        return ("backup_incomplete",
                f"{directory} has no readable {MANIFEST_NAME}, so it is a "
                "partial or interrupted backup and cannot be trusted.")
    for entry in manifest["files"]:
        name = str(entry.get("name", ""))
        stored = directory / FILES_DIR / name
        if not name or not stored.is_file():
            return ("backup_corrupt",
                    f"{name or '<unnamed>'} is listed in {directory / MANIFEST_NAME} "
                    f"but missing from {directory / FILES_DIR}.")
        actual = file_sha256(stored)
        if actual != entry.get("sha256"):
            return ("backup_corrupt",
                    f"{name} in {directory} hashes {actual}, but the manifest "
                    f"records {entry.get('sha256')}.")
    return None


# --------------------------------------------------------------------------
# Backup
# --------------------------------------------------------------------------

def backup(label: str, gate: Gate, is_link: Callable[[Path], bool] | None = None,
           source: Path | None = None, root: Path | None = None,
           tool: str = "hs_saves_backup") -> dict[str, Any]:
    """Snapshot the whole live directory. Gate, inventory, copy, verify, manifest.

    `source`/`root` are explicit rather than read from the environment so that
    `hs_selfcheck`'s round trip can drive these exact functions against a
    fixture without mutating process-wide state that another tool call is
    reading at the same moment.
    """
    is_link = default_is_link if is_link is None else is_link

    if not isinstance(label, str) or not LABEL_PATTERN.match(label):
        return results.refuse(
            tool, "invalid_label",
            f"{label!r} is not a usable label. Use 1-40 characters from "
            "A-Z a-z 0-9 . _ - : the label becomes part of a directory name.")

    refusal = _gate_refusal(tool, gate, "before reading the save directory")
    if refusal:
        return refusal

    source = save_dir() if source is None else Path(source)
    if not source.is_dir():
        return results.refuse(
            tool, "save_dir_missing",
            f"No save directory at {source}. Set HS_DRIVE_SAVE_DIR if the "
            "saves live somewhere else.")

    files, skipped, total = _inventory(source, is_link)
    if not any(entry.match(CHARACTER_GLOB) for entry in files):
        return results.refuse(
            tool, "no_character_saves",
            f"{source} holds no {CHARACTER_GLOB} file, so it is not a Hero "
            "Siege save directory. Nothing was copied.")
    if total > MAX_SOURCE_BYTES:
        return results.refuse(
            tool, "save_dir_too_large",
            f"{source} holds {total} bytes, over the {MAX_SOURCE_BYTES}-byte "
            "ceiling. A save directory is megabytes; check the path.")

    # The gate again, immediately before the first write: everything between
    # here and the previous check was file reads, and the game can start
    # during them.
    refusal = _gate_refusal(tool, gate, "immediately before the first write")
    if refusal:
        return refusal

    stamp, created = _utc_stamp()
    root = backup_root() if root is None else Path(root)
    root.mkdir(parents=True, exist_ok=True)
    directory = _free_directory(root, f"{stamp}_{label}")
    store = directory / FILES_DIR
    store.mkdir(parents=True)

    entries: list[dict[str, Any]] = []
    copied_bytes = 0
    for entry in files:
        expected = file_sha256(entry)
        target = store / entry.name
        copy_file(entry, target)
        actual = file_sha256(target)
        if actual != expected:
            kept = _mark_failed(directory)
            return results.refuse(
                tool, "copy_verification_failed",
                f"{entry.name} copied to {target} hashes {actual}, not the "
                f"{expected} it had at the source. The partial backup was "
                f"kept as {kept}; nothing was deleted.")
        size = target.stat().st_size
        copied_bytes += size
        entries.append({"name": entry.name, "size": size, "sha256": expected})

    manifest = {
        "schema": SCHEMA,
        "id": directory.name,
        "label": label,
        "created_utc": created,
        "source_dir": str(source),
        "game_state_at_backup": "not_running",
        "files": entries,
        "total_bytes": copied_bytes,
    }
    # Written last, through a temp file: a reader that finds manifest.json
    # finds a finished backup, and never a half-written one.
    staging = directory / (MANIFEST_NAME + TEMP_SUFFIX)
    staging.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(staging, directory / MANIFEST_NAME)

    return results.ok(
        tool,
        backup_id=directory.name,
        label=label,
        files=len(entries),
        total_bytes=copied_bytes,
        path=str(directory),
        created_utc=created,
        skipped_links=skipped,
    )


# --------------------------------------------------------------------------
# Restore
# --------------------------------------------------------------------------

def restore(backup_id: str, confirm_backup_id: str, remove_extra: bool = False,
            gate: Gate | None = None, is_link: Callable[[Path], bool] | None = None,
            source: Path | None = None, root: Path | None = None,
            tool: str = "hs_saves_restore") -> dict[str, Any]:
    """Put a verified backup back, after backing up what is there now."""
    is_link = default_is_link if is_link is None else is_link
    if gate is None:
        from . import procs
        gate = procs.gate

    # Before anything is read: a caller who cannot name the backup twice has
    # not chosen it.
    if confirm_backup_id != backup_id:
        return results.refuse(
            tool, "confirmation_mismatch",
            f"confirm_backup_id {confirm_backup_id!r} does not equal "
            f"backup_id {backup_id!r}. Restoring overwrites live saves, so it "
            "asks for the id twice. Nothing was read.")

    refusal = _gate_refusal(tool, gate, "before reading the backup")
    if refusal:
        return refusal

    root = backup_root() if root is None else Path(root)
    directory = root / backup_id
    problem = verify_backup(directory)
    if problem:
        return results.refuse(tool, problem[0], problem[1])
    manifest = read_manifest(directory)
    assert manifest is not None  # verify_backup would have refused

    source = save_dir() if source is None else Path(source)
    if not source.is_dir():
        return results.refuse(
            tool, "save_dir_missing",
            f"No save directory at {source} to restore into.")

    # Everything currently live is backed up before a single byte is written,
    # and that backup is verified the same way the chosen one just was.
    pre = backup(PRE_RESTORE_LABEL, gate=gate, is_link=is_link,
                 source=source, root=root, tool=tool)
    if results.is_refusal(pre):
        return results.refuse(
            tool, "pre_restore_backup_failed",
            f"The pre-restore backup of {source} was refused "
            f"({pre['reason']}): {pre['detail']} The live directory was not "
            "touched.")
    pre_directory = Path(pre["path"])
    problem = verify_backup(pre_directory)
    if problem:
        return results.refuse(
            tool, "pre_restore_backup_failed",
            f"The pre-restore backup {pre['backup_id']} did not verify "
            f"({problem[0]}): {problem[1]} The live directory was not touched.")

    # The gate once more: the pre-restore backup took time, and a wait is
    # exactly when the state this decision rests on can change.
    refusal = _gate_refusal(tool, gate, "immediately before the first write")
    if refusal:
        return refusal

    restored: list[str] = []
    for entry in manifest["files"]:
        name = str(entry["name"])
        stored = directory / FILES_DIR / name
        target = source / name
        staging = source / (name + TEMP_SUFFIX)
        copy_file(stored, staging)
        actual = file_sha256(staging)
        if actual != entry["sha256"]:
            return results.refuse(
                tool, "copy_verification_failed",
                f"{name} copied to {staging} hashes {actual}, not the "
                f"{entry['sha256']} the manifest records. The partial copy "
                f"was left at {staging} and nothing was deleted. "
                f"{len(restored)} file(s) had already been restored; the "
                f"pre-restore backup is {pre['backup_id']}.",
                pre_restore_backup_id=pre["backup_id"],
                restored=len(restored))
        os.replace(staging, target)
        restored.append(name)

    # Post-verify from the live directory itself, not from the temp file that
    # was just renamed over it.
    for entry in manifest["files"]:
        name = str(entry["name"])
        actual = file_sha256(source / name)
        if actual != entry["sha256"]:
            return results.refuse(
                tool, "copy_verification_failed",
                f"{name} in {source} hashes {actual} after the restore, not "
                f"the {entry['sha256']} the manifest records. The "
                f"pre-restore backup is {pre['backup_id']}.",
                pre_restore_backup_id=pre["backup_id"],
                restored=len(restored))

    moved, not_moved = _move_extras(
        source, pre_directory, set(str(e["name"]) for e in manifest["files"]),
        is_link) if remove_extra else ([], [])

    return results.ok(
        tool,
        restored=len(restored),
        files=restored,
        backup_id=backup_id,
        pre_restore_backup_id=pre["backup_id"],
        moved_extras=moved,
        extras_not_moved=not_moved,
    )


def _move_extras(source: Path, pre_directory: Path, known: set[str],
                 is_link: Callable[[Path], bool]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Move files the backup did not contain into the pre-restore backup.

    A move, never a removal -- and `os.replace` only. The copy+unlink fallback
    `shutil.move` uses across volumes would delete a file inside the live save
    directory, which nothing in this module is allowed to do. When the backup
    root is on another volume the extra is reported as not moved instead, with
    the operating system's reason.
    """
    store = pre_directory / FILES_DIR
    moved: list[dict[str, str]] = []
    not_moved: list[dict[str, str]] = []
    for entry in sorted(source.iterdir()):
        if entry.name in known or is_link(entry) or not entry.is_file():
            continue
        if entry.name.endswith(TEMP_SUFFIX):
            continue
        name = entry.name
        if name == MANIFEST_NAME:
            # Would otherwise overwrite the pre-restore backup's own metadata.
            name = MANIFEST_NAME + ".extra"
        target = store / name
        try:
            os.replace(entry, target)
        except OSError as exc:
            not_moved.append({"name": entry.name, "detail": str(exc)})
            continue
        moved.append({"name": entry.name, "moved_to": str(target)})
    return moved, not_moved


# --------------------------------------------------------------------------
# Read-only views
# --------------------------------------------------------------------------

def list_backups(limit: int = 20, offset: int = 0, root: Path | None = None,
                 tool: str = "hs_saves_list") -> dict[str, Any]:
    """Newest first. A directory without a manifest lists as `incomplete`."""
    limit = max(1, min(100, int(limit)))
    offset = max(0, int(offset))
    root = backup_root() if root is None else Path(root)
    directories: Iterable[Path] = []
    if root.is_dir():
        directories = sorted((p for p in root.iterdir() if p.is_dir()),
                             key=lambda p: p.name, reverse=True)
    directories = list(directories)
    total = len(directories)
    page = directories[offset:offset + limit]

    rows = []
    for directory in page:
        manifest = read_manifest(directory)
        if manifest is None:
            rows.append({"id": directory.name, "label": "", "status": "incomplete",
                         "files": 0, "total_bytes": 0, "created_utc": ""})
            continue
        rows.append({
            "id": str(manifest.get("id", directory.name)),
            "label": str(manifest.get("label", "")),
            "status": "complete",
            "files": len(manifest["files"]),
            "total_bytes": int(manifest.get("total_bytes", 0)),
            "created_utc": str(manifest.get("created_utc", "")),
        })

    has_more = offset + len(rows) < total
    return results.ok(
        tool,
        total=total,
        count=len(rows),
        offset=offset,
        limit=limit,
        has_more=has_more,
        next_offset=(offset + len(rows)) if has_more else None,
        backups=rows,
        path=str(root),
    )


def inspect_backup(backup_id: str, is_link: Callable[[Path], bool] | None = None,
                   source: Path | None = None, root: Path | None = None,
                   tool: str = "hs_saves_inspect") -> dict[str, Any]:
    """The manifest, plus how the live directory differs from it right now."""
    is_link = default_is_link if is_link is None else is_link
    directory = (backup_root() if root is None else Path(root)) / backup_id
    if not directory.is_dir():
        return results.refuse(
            tool, "backup_incomplete", f"No backup directory at {directory}.")
    manifest = read_manifest(directory)
    if manifest is None:
        return results.refuse(
            tool, "backup_incomplete",
            f"{directory} has no readable {MANIFEST_NAME}.")

    source = save_dir() if source is None else Path(source)
    live: dict[str, Path] = {}
    if source.is_dir():
        files, _, _ = _inventory(source, is_link)
        live = {entry.name: entry for entry in files}

    changed: list[str] = []
    missing: list[str] = []
    for entry in manifest["files"]:
        name = str(entry["name"])
        current = live.get(name)
        if current is None:
            missing.append(name)
        elif file_sha256(current) != entry.get("sha256"):
            changed.append(name)
    known = {str(entry["name"]) for entry in manifest["files"]}
    added = sorted(name for name in live if name not in known)

    return results.ok(
        tool,
        backup_id=backup_id,
        path=str(directory),
        manifest=manifest,
        live_dir=str(source),
        live_dir_exists=source.is_dir(),
        changed=sorted(changed),
        added=added,
        missing=sorted(missing),
    )
