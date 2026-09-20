"""hs-drive save backup/restore: the fail-closed contract, not the happy path.

Every case runs against a fixture directory and a fixture backup root, both
handed to the module through `HS_DRIVE_SAVE_DIR` / `HS_DRIVE_BACKUP_DIR`, and
`LOCALAPPDATA` is repointed at a temp directory as well. Nothing in this file
can reach the real `hs2saves\\`, which is the whole reason those two overrides
exist.

B2 is the baseline (`AGENTS.md` § "Mod Development Workflow"): with the gate
saying the game is running -- or saying it does not know -- nothing happens at
all, which is the behaviour a broken gate would silently replace. B3 is the
target: a full round trip that comes back byte-identical.
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.hs_drive_mcp import saves  # noqa: E402

FIXTURE = {
    "herosiege1.hss": b"character one\x00\x01",
    "ether1.hss": b"ether one",
    "shop.ini": b"[shop]\nstock=3\n",
    "stash.hss": b"stash bytes",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(directory: Path) -> dict[str, bytes]:
    if not directory.is_dir():
        return {}
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir()) if p.is_file()}


class SaveToolBase(unittest.TestCase):
    """A live dir, a backup root, and a gate the test drives by hand."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hs-drive-saves-")
        self.addCleanup(self.temp.cleanup)
        # resolve(): a CI TEMP is an 8.3 short path, and the manifest records
        # the source directory as a string other assertions compare against.
        self.root = Path(self.temp.name).resolve()
        self.live = self.root / "hs2saves"
        self.live.mkdir()
        for name, data in FIXTURE.items():
            (self.live / name).write_bytes(data)
        self.backups = self.root / "save-backups"
        self.appdata = self.root / "appdata"
        self.appdata.mkdir()
        self.enterContext(patch.dict(os.environ, {
            "HS_DRIVE_SAVE_DIR": str(self.live),
            "HS_DRIVE_BACKUP_DIR": str(self.backups),
            "LOCALAPPDATA": str(self.appdata),
        }))
        self.state = "not_running"

    def gate(self) -> str:
        return self.state

    def backup_ids(self) -> list[str]:
        if not self.backups.is_dir():
            return []
        return sorted(p.name for p in self.backups.iterdir())


class BaselineRefusalTests(SaveToolBase):
    """B2 -- the gate is the only thing standing between a tool and a save."""

    def assert_nothing_happened(self, result, reason):
        self.assertTrue(result["refused"], result)
        self.assertEqual(result["reason"], reason)
        self.assertTrue(result["detail"])
        self.assertEqual(self.backup_ids(), [])
        self.assertEqual(tree(self.live), FIXTURE)

    def test_backup_refuses_while_the_game_is_running(self):
        self.state = "running"
        self.assertEqual(self.backup_ids(), [])
        self.assert_nothing_happened(
            saves.backup("baseline", gate=self.gate), "game_running")

    def test_backup_refuses_when_the_process_state_is_unknown(self):
        self.state = "unknown"
        self.assertEqual(self.backup_ids(), [])
        self.assert_nothing_happened(
            saves.backup("baseline", gate=self.gate), "game_state_unknown")

    def test_restore_refuses_while_the_game_is_running(self):
        self.state = "running"
        self.assert_nothing_happened(
            saves.restore("anything", "anything", gate=self.gate), "game_running")

    def test_restore_refuses_when_the_process_state_is_unknown(self):
        self.state = "unknown"
        self.assert_nothing_happened(
            saves.restore("anything", "anything", gate=self.gate), "game_state_unknown")


class RoundTripTests(SaveToolBase):
    """B3 -- the target: back up, damage the directory, restore it."""

    def test_restore_returns_every_original_file_and_keeps_extras(self):
        made = saves.backup("target", gate=self.gate)
        self.assertFalse(made["refused"], made)
        backup_id = made["backup_id"]
        self.assertEqual(made["files"], len(FIXTURE))

        (self.live / "herosiege1.hss").write_bytes(b"mutated")
        (self.live / "stash.hss").unlink()
        (self.live / "extra.hss").write_bytes(b"added after the backup")

        done = saves.restore(backup_id, backup_id, remove_extra=False, gate=self.gate)
        self.assertFalse(done["refused"], done)
        self.assertEqual(done["moved_extras"], [])

        for name, data in FIXTURE.items():
            self.assertEqual((self.live / name).read_bytes(), data, name)
        self.assertEqual((self.live / "extra.hss").read_bytes(), b"added after the backup")


class ExtraFileTests(SaveToolBase):
    """B4 -- `remove_extra` moves, and this module unlinks nothing, ever."""

    def test_extras_are_moved_into_the_pre_restore_backup_and_never_deleted(self):
        made = saves.backup("target", gate=self.gate)
        backup_id = made["backup_id"]
        (self.live / "extra.hss").write_bytes(b"added after the backup")

        removed: list[Path] = []
        real_remove, real_unlink = os.remove, os.unlink
        real_path_unlink = Path.unlink

        def record_remove(path, *args, **kwargs):
            removed.append(Path(path))
            return real_remove(path, *args, **kwargs)

        def record_unlink(path, *args, **kwargs):
            removed.append(Path(path))
            return real_unlink(path, *args, **kwargs)

        def record_path_unlink(self_path, *args, **kwargs):
            removed.append(Path(self_path))
            return real_path_unlink(self_path, *args, **kwargs)

        with patch.object(os, "remove", record_remove), \
             patch.object(os, "unlink", record_unlink), \
             patch.object(Path, "unlink", record_path_unlink):
            done = saves.restore(backup_id, backup_id, remove_extra=True, gate=self.gate)

        self.assertFalse(done["refused"], done)
        self.assertEqual([e["name"] for e in done["moved_extras"]], ["extra.hss"])
        self.assertEqual(done["extras_not_moved"], [])

        pre = self.backups / done["pre_restore_backup_id"] / saves.FILES_DIR / "extra.hss"
        self.assertTrue(pre.is_file(), f"{pre} is missing")
        self.assertEqual(pre.read_bytes(), b"added after the backup")
        self.assertFalse((self.live / "extra.hss").exists())

        for target in removed:
            resolved = str(target.resolve())
            self.assertFalse(resolved.startswith(str(self.live)),
                             f"a file inside the live save directory was unlinked: {target}")
            self.assertFalse(resolved.startswith(str(self.backups)),
                             f"a file inside a backup directory was unlinked: {target}")


class PreRestoreBackupTests(SaveToolBase):
    """B5 -- the restore's own safety net, and what happens when it tears."""

    def live_hashes(self) -> dict[str, str]:
        return {p.name: saves.file_sha256(p) for p in sorted(self.live.iterdir()) if p.is_file()}

    def test_pre_restore_backup_records_the_live_files_as_they_were(self):
        made = saves.backup("target", gate=self.gate)
        (self.live / "herosiege1.hss").write_bytes(b"mutated before the restore")
        before = self.live_hashes()

        done = saves.restore(made["backup_id"], made["backup_id"], gate=self.gate)
        self.assertFalse(done["refused"], done)

        pre_id = done["pre_restore_backup_id"]
        self.assertTrue(pre_id.endswith("_pre-restore"), pre_id)
        manifest = json.loads((self.backups / pre_id / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual({e["name"]: e["sha256"] for e in manifest["files"]}, before)

    def test_a_pre_restore_backup_that_cannot_be_copied_refuses_the_restore(self):
        made = saves.backup("target", gate=self.gate)
        before = self.live_hashes()
        real_copy = saves.copy_file

        def corrupt_into_the_pre_restore_backup(source, target):
            real_copy(source, target)
            if "_pre-restore" in str(target):
                Path(target).write_bytes(b"corrupted in transit")

        with patch.object(saves, "copy_file", corrupt_into_the_pre_restore_backup):
            done = saves.restore(made["backup_id"], made["backup_id"], gate=self.gate)

        self.assertTrue(done["refused"], done)
        self.assertEqual(done["reason"], "pre_restore_backup_failed")
        self.assertIn("copy_verification_failed", done["detail"])
        self.assertEqual(self.live_hashes(), before)

    def test_a_pre_restore_backup_that_fails_verification_refuses_the_restore(self):
        made = saves.backup("target", gate=self.gate)
        before = self.live_hashes()
        real_verify = saves.verify_backup

        def reject_the_pre_restore_backup(directory):
            if "_pre-restore" in directory.name:
                return "backup_corrupt", f"stash.hss in {directory} hashes differently."
            return real_verify(directory)

        with patch.object(saves, "verify_backup", reject_the_pre_restore_backup):
            done = saves.restore(made["backup_id"], made["backup_id"], gate=self.gate)

        self.assertTrue(done["refused"], done)
        self.assertEqual(done["reason"], "pre_restore_backup_failed")
        self.assertEqual(self.live_hashes(), before)


class SourceRefusalTests(SaveToolBase):
    """B6 -- a directory that is not a save directory is refused, not guessed at."""

    def test_a_directory_without_character_saves_is_refused(self):
        for name in ("herosiege1.hss", "stash.hss"):
            (self.live / name).unlink()
        result = saves.backup("nochars", gate=self.gate)
        self.assertTrue(result["refused"], result)
        self.assertEqual(result["reason"], "no_character_saves")
        self.assertFalse(self.backups.exists())

    def test_a_missing_save_directory_is_refused(self):
        with patch.dict(os.environ, {"HS_DRIVE_SAVE_DIR": str(self.root / "gone")}):
            result = saves.backup("missing", gate=self.gate)
        self.assertTrue(result["refused"], result)
        self.assertEqual(result["reason"], "save_dir_missing")
        self.assertFalse(self.backups.exists())


class BackupIntegrityTests(SaveToolBase):
    """B7/B8 -- a backup is trusted only as far as it has been re-read."""

    def test_a_backup_without_a_manifest_lists_incomplete_and_cannot_be_restored(self):
        made = saves.backup("target", gate=self.gate)
        before = tree(self.live)
        (self.backups / made["backup_id"] / "manifest.json").unlink()

        listed = saves.list_backups()
        row = next(r for r in listed["backups"] if r["id"] == made["backup_id"])
        self.assertEqual(row["status"], "incomplete")

        done = saves.restore(made["backup_id"], made["backup_id"], gate=self.gate)
        self.assertTrue(done["refused"], done)
        self.assertEqual(done["reason"], "backup_incomplete")
        self.assertEqual(tree(self.live), before)

    def test_a_backup_whose_bytes_drifted_from_its_manifest_is_refused_by_name(self):
        made = saves.backup("target", gate=self.gate)
        before = tree(self.live)
        stored = self.backups / made["backup_id"] / saves.FILES_DIR / "stash.hss"
        stored.write_bytes(b"rotted on disk")

        done = saves.restore(made["backup_id"], made["backup_id"], gate=self.gate)
        self.assertTrue(done["refused"], done)
        self.assertEqual(done["reason"], "backup_corrupt")
        self.assertIn("stash.hss", done["detail"])
        self.assertEqual(tree(self.live), before)

    def test_the_manifest_is_written_last_through_a_temp_file(self):
        real_replace = os.replace
        calls: list[tuple[str, str, int]] = []
        copies: list[str] = []
        real_copy = saves.copy_file

        def record_copy(source, target):
            copies.append(str(target))
            return real_copy(source, target)

        def record_replace(source, target, *args, **kwargs):
            calls.append((str(source), str(target), len(copies)))
            return real_replace(source, target, *args, **kwargs)

        with patch.object(saves, "copy_file", record_copy), \
             patch.object(saves.os, "replace", record_replace):
            made = saves.backup("target", gate=self.gate)

        self.assertFalse(made["refused"], made)
        self.assertEqual(len(calls), 1, calls)
        source, target, copies_done = calls[0]
        self.assertTrue(source.endswith("manifest.json" + saves.TEMP_SUFFIX), source)
        self.assertTrue(target.endswith("manifest.json"), target)
        self.assertEqual(copies_done, len(FIXTURE),
                         "the manifest was written before every file was copied")

    def test_the_manifest_records_the_documented_fields(self):
        made = saves.backup("fields", gate=self.gate)
        manifest = json.loads(
            (self.backups / made["backup_id"] / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], "hs-drive-save-backup/1")
        self.assertEqual(manifest["id"], made["backup_id"])
        self.assertEqual(manifest["label"], "fields")
        self.assertEqual(manifest["source_dir"], str(self.live))
        self.assertEqual(manifest["game_state_at_backup"], "not_running")
        self.assertTrue(manifest["created_utc"].endswith("Z"))
        self.assertEqual(manifest["total_bytes"], sum(len(v) for v in FIXTURE.values()))
        self.assertEqual({e["name"] for e in manifest["files"]}, set(FIXTURE))
        for entry in manifest["files"]:
            self.assertEqual(entry["size"], len(FIXTURE[entry["name"]]))
            self.assertEqual(entry["sha256"], sha256(self.live / entry["name"]))

    def test_a_copy_that_fails_its_re_hash_keeps_the_partial_backup_as_failed(self):
        real_copy = saves.copy_file

        def corrupt_one_file(source, target):
            real_copy(source, target)
            if Path(target).name == "shop.ini":
                Path(target).write_bytes(b"corrupted in transit")

        with patch.object(saves, "copy_file", corrupt_one_file):
            result = saves.backup("corrupt", gate=self.gate)

        self.assertTrue(result["refused"], result)
        self.assertEqual(result["reason"], "copy_verification_failed")
        self.assertIn("shop.ini", result["detail"])
        failed = [p for p in self.backups.iterdir() if p.name.endswith(".failed")]
        self.assertEqual(len(failed), 1, self.backup_ids())
        self.assertTrue((failed[0] / saves.FILES_DIR / "shop.ini").is_file(),
                        "the partial backup was deleted instead of kept")
        self.assertFalse((failed[0] / "manifest.json").exists())


class InventoryAndConfirmationTests(SaveToolBase):
    """B9 -- what is never copied, and what is never even read."""

    def test_flagged_entries_are_neither_copied_nor_counted(self):
        made = saves.backup("links", gate=self.gate, is_link=lambda p: p.name == "ether1.hss")
        self.assertFalse(made["refused"], made)
        self.assertEqual(made["skipped_links"], ["ether1.hss"])
        self.assertEqual(made["files"], len(FIXTURE) - 1)
        self.assertEqual(made["total_bytes"],
                         sum(len(v) for k, v in FIXTURE.items() if k != "ether1.hss"))
        store = self.backups / made["backup_id"] / saves.FILES_DIR
        self.assertFalse((store / "ether1.hss").exists())

    def test_subdirectories_are_never_descended(self):
        nested = self.live / "old"
        nested.mkdir()
        (nested / "herosiege9.hss").write_bytes(b"an older character")
        made = saves.backup("nested", gate=self.gate)
        store = self.backups / made["backup_id"] / saves.FILES_DIR
        self.assertEqual(made["files"], len(FIXTURE))
        self.assertEqual(sorted(p.name for p in store.iterdir()), sorted(FIXTURE))

    def test_a_source_over_the_ceiling_is_refused(self):
        with patch.object(saves, "MAX_SOURCE_BYTES", 4):
            result = saves.backup("toolarge", gate=self.gate)
        self.assertTrue(result["refused"], result)
        self.assertEqual(result["reason"], "save_dir_too_large")
        self.assertFalse(self.backups.exists())

    def test_a_mismatched_confirmation_refuses_before_the_backup_is_read(self):
        made = saves.backup("target", gate=self.gate)
        with patch.object(saves, "verify_backup") as verify, \
             patch.object(saves, "read_manifest") as manifest:
            done = saves.restore(made["backup_id"], "not-the-same-id", gate=self.gate)
        self.assertTrue(done["refused"], done)
        self.assertEqual(done["reason"], "confirmation_mismatch")
        verify.assert_not_called()
        manifest.assert_not_called()

    def test_an_unusable_label_is_refused(self):
        result = saves.backup("no spaces allowed", gate=self.gate)
        self.assertTrue(result["refused"], result)
        self.assertEqual(result["reason"], "invalid_label")
        self.assertFalse(self.backups.exists())


class ListAndInspectTests(SaveToolBase):
    """B10 -- the two read-only views."""

    def make(self, count: int) -> list[str]:
        ids = []
        for index in range(count):
            made = saves.backup(f"page{index}", gate=self.gate)
            self.assertFalse(made["refused"], made)
            ids.append(made["backup_id"])
        return ids

    def test_listing_pages_through_the_backup_root(self):
        ids = self.make(5)
        first = saves.list_backups(limit=2, offset=0)
        self.assertEqual(first["total"], 5)
        self.assertEqual(first["count"], 2)
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_offset"], 2)

        last = saves.list_backups(limit=2, offset=4)
        self.assertEqual(last["count"], 1)
        self.assertFalse(last["has_more"])
        self.assertIsNone(last["next_offset"])

        seen = [row["id"] for row in first["backups"]]
        seen += [row["id"] for row in saves.list_backups(limit=2, offset=2)["backups"]]
        seen += [row["id"] for row in last["backups"]]
        self.assertEqual(sorted(seen), sorted(ids))

    def test_inspect_reports_changed_added_and_missing_against_the_live_dir(self):
        made = saves.backup("target", gate=self.gate)
        (self.live / "herosiege1.hss").write_bytes(b"changed since the backup")
        (self.live / "stash.hss").unlink()
        (self.live / "extra.hss").write_bytes(b"new since the backup")

        seen = saves.inspect_backup(made["backup_id"])
        self.assertFalse(seen["refused"], seen)
        self.assertEqual(seen["manifest"]["id"], made["backup_id"])
        self.assertEqual(seen["changed"], ["herosiege1.hss"])
        self.assertEqual(seen["added"], ["extra.hss"])
        self.assertEqual(seen["missing"], ["stash.hss"])

    def test_the_live_directory_comes_from_the_environment_override(self):
        made = saves.backup("target", gate=self.gate)
        other = self.root / "elsewhere"
        other.mkdir()
        for name, data in FIXTURE.items():
            (other / name).write_bytes(data)
        with patch.dict(os.environ, {"HS_DRIVE_SAVE_DIR": str(other)}):
            self.assertEqual(saves.save_dir(), other)
            seen = saves.inspect_backup(made["backup_id"])
        self.assertEqual(seen["live_dir"], str(other))
        self.assertEqual(seen["changed"], [])
        self.assertEqual(seen["added"], [])
        self.assertEqual(seen["missing"], [])


if __name__ == "__main__":
    unittest.main()
