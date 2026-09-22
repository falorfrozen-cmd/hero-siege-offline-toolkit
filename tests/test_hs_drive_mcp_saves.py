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

from tools.hs_drive_mcp import launcher_bridge, procs, saves  # noqa: E402

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

    def gate(self) -> tuple[str, str]:
        """A gate answers `(state, why)`; the reason travels with the answer."""
        return self.state, f"the test gate was set to {self.state!r}."

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

    def test_a_checkout_without_forgepact_refuses_by_the_right_name(self):
        """The real gate, with the engine source absent.

        `unknown` and `engine_missing` both refuse, so a test that only checked
        "did it refuse" would pass against the bug. What was wrong was the
        *name*: the save tools blamed a Win32 snapshot that was never
        attempted, while `hs_status`, asking the bridge directly, said
        `engine_source_missing` about the same machine.
        """
        absent = self.root / "ForgePact" / "src" / "offline_launcher.py"
        with patch.object(launcher_bridge, "_LOADED", {}), \
             patch.object(launcher_bridge, "ENGINE_PATH", absent):
            self.assertEqual(procs.gate()[0], "engine_missing")
            made = saves.backup("nochain", gate=procs.gate)
            done = saves.restore("anything", "anything", gate=procs.gate)

        for result in (made, done):
            self.assertTrue(result["refused"], result)
            self.assertEqual(result["reason"], "engine_source_missing")
            self.assertIn("ForgePact/src/offline_launcher.py", result["detail"])
            self.assertIn("git submodule update --init ForgePact", result["detail"])
        self.assertEqual(self.backup_ids(), [])
        self.assertEqual(tree(self.live), FIXTURE)

    def test_the_status_tri_state_still_hides_the_engine_states(self):
        """`game_state` keeps the three values hs_status was specified against."""
        absent = self.root / "ForgePact" / "src" / "offline_launcher.py"
        with patch.object(launcher_bridge, "_LOADED", {}), \
             patch.object(launcher_bridge, "ENGINE_PATH", absent):
            state, why = procs.game_state_detail()
            self.assertEqual(state, "engine_missing")
            self.assertIn("offline_launcher.py", why)
            self.assertEqual(procs.game_state(), "unknown")
            self.assertEqual(procs.game_pids(), [])

    def test_an_engine_that_will_not_import_refuses_by_its_own_name(self):
        """Present but unimportable is not the same machine as absent.

        The gate used to report this as `unknown` and the detail then named a
        Win32 snapshot that was never attempted, while `hs_status` raised
        ModuleNotFoundError straight across the transport. Both now say
        `engine_import_failed` and name the import.
        """
        def explode(*_args, **_kwargs):
            raise ModuleNotFoundError("No module named 'ctypes.wintypes'")

        with patch.object(launcher_bridge, "load", explode):
            state, why = procs.game_state_detail()
            self.assertEqual(state, "engine_unusable")
            self.assertIn("ModuleNotFoundError", why)
            self.assertEqual(procs.game_state(), "unknown")

            made = saves.backup("noimport", gate=procs.gate)
            report = procs.status()

        self.assertTrue(made["refused"], made)
        self.assertEqual(made["reason"], "engine_import_failed")
        self.assertIn("ModuleNotFoundError", made["detail"])
        self.assertTrue(report["refused"], report)
        self.assertEqual(report["reason"], "engine_import_failed",
                         "hs_status and the save gate disagreed about one machine")
        self.assertEqual(self.backup_ids(), [])
        self.assertEqual(tree(self.live), FIXTURE)

    def test_a_refusal_carries_the_gates_own_reason(self):
        """The `why` travels with the state instead of being re-derived."""
        self.state = "unknown"
        result = saves.backup("baseline", gate=self.gate)
        self.assertEqual(result["reason"], "game_state_unknown")
        self.assertIn("the test gate was set to 'unknown'", result["detail"])


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

    def test_a_wiped_save_directory_can_still_be_restored(self):
        """The recovery case: the reason this tool exists at all.

        The pre-restore backup runs over a directory with no `herosiege*.hss`
        left in it. Requiring one there made `hs_saves_restore` refuse
        `pre_restore_backup_failed` precisely when a player had lost their
        characters -- a feature that reports a reason and does nothing.
        """
        made = saves.backup("target", gate=self.gate)
        for path in sorted(self.live.iterdir()):
            if path.suffix == ".hss":
                path.unlink()
        self.assertEqual([p.name for p in self.live.iterdir()], ["shop.ini"])

        done = saves.restore(made["backup_id"], made["backup_id"], gate=self.gate)
        self.assertFalse(done["refused"], done)
        self.assertEqual(tree(self.live), FIXTURE)

        pre = json.loads((self.backups / done["pre_restore_backup_id"]
                          / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([entry["name"] for entry in pre["files"]], ["shop.ini"])

    def test_an_entirely_empty_save_directory_can_still_be_restored(self):
        made = saves.backup("target", gate=self.gate)
        for path in sorted(self.live.iterdir()):
            path.unlink()

        done = saves.restore(made["backup_id"], made["backup_id"], gate=self.gate)
        self.assertFalse(done["refused"], done)
        self.assertEqual(tree(self.live), FIXTURE)

        pre = json.loads((self.backups / done["pre_restore_backup_id"]
                          / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(pre["files"], [])

    def test_an_unrelated_directory_is_not_a_restore_target(self):
        """The negative control for the two cases above.

        Relaxing the character-save requirement so a wiped directory could be
        restored into also removed the only thing stopping a mis-set
        HS_DRIVE_SAVE_DIR from being restored into -- and with remove_extra
        that directory's own files would be moved into the pre-restore backup.
        Kept beside the recovery tests on purpose: widening what is accepted
        must not be able to drift into accepting anything.
        """
        made = saves.backup("target", gate=self.gate)
        elsewhere = self.root / "not-a-save-dir"
        elsewhere.mkdir()
        for name in ("notes.txt", "photo.jpg", "budget.xlsx"):
            (elsewhere / name).write_bytes(b"someone else's file: " + name.encode())
        before = tree(elsewhere)

        with patch.dict(os.environ, {"HS_DRIVE_SAVE_DIR": str(elsewhere)}):
            done = saves.restore(made["backup_id"], made["backup_id"],
                                 remove_extra=True, gate=self.gate)

        self.assertTrue(done["refused"], done)
        self.assertEqual(done["reason"], "restore_target_unrelated")
        for name in before:
            self.assertIn(name, done["detail"])
        self.assertEqual(tree(elsewhere), before, "an unrelated directory was written to")
        self.assertEqual(self.backup_ids(), [made["backup_id"]],
                         "a pre-restore backup was taken of an unrelated directory")

    def test_a_live_directory_with_unrelated_extras_still_restores(self):
        """A real save directory keeps restoring, extras and all (B3/B4)."""
        made = saves.backup("target", gate=self.gate)
        (self.live / "lootfilter_notes.txt").write_bytes(b"not in the backup")
        done = saves.restore(made["backup_id"], made["backup_id"], gate=self.gate)
        self.assertFalse(done["refused"], done)
        self.assertEqual((self.live / "lootfilter_notes.txt").read_bytes(),
                         b"not in the backup")

    def test_a_plain_backup_of_a_wiped_directory_is_still_refused(self):
        """The relaxation is for the pre-restore backup only, not for backup()."""
        for path in sorted(self.live.iterdir()):
            if path.suffix == ".hss":
                path.unlink()
        result = saves.backup("wiped", gate=self.gate)
        self.assertTrue(result["refused"], result)
        self.assertEqual(result["reason"], "no_character_saves")

    def test_the_size_ceiling_still_applies_to_the_pre_restore_backup(self):
        """`require_characters=False` relaxes one guard, and only that one."""
        made = saves.backup("target", gate=self.gate)
        with patch.object(saves, "MAX_SOURCE_BYTES", 4):
            done = saves.restore(made["backup_id"], made["backup_id"], gate=self.gate)
        self.assertTrue(done["refused"], done)
        self.assertEqual(done["reason"], "pre_restore_backup_failed")
        self.assertIn("save_dir_too_large", done["detail"])
        self.assertEqual(tree(self.live), FIXTURE)


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

    def test_a_backup_id_that_is_a_path_is_refused(self):
        """`backup_id` is model-chosen and becomes a path component."""
        made = saves.backup("target", gate=self.gate)
        for bad in ("..", "../" + made["backup_id"], r"..\..\Hero_Siege",
                    "sub/dir", r"sub\dir", "/etc/passwd", r"C:\Windows", ""):
            with self.subTest(backup_id=bad):
                self.assertFalse(saves.is_bare_name(bad))
                done = saves.restore(bad, bad, gate=self.gate)
                self.assertTrue(done["refused"], done)
                self.assertEqual(done["reason"], "invalid_backup_id")
                seen = saves.inspect_backup(bad)
                self.assertTrue(seen["refused"], seen)
                self.assertEqual(seen["reason"], "invalid_backup_id")
        # The negative control: a real id is still accepted.
        self.assertTrue(saves.is_bare_name(made["backup_id"]))
        self.assertFalse(saves.inspect_backup(made["backup_id"])["refused"])

    def test_a_manifest_naming_a_path_is_corrupt_not_followed(self):
        made = saves.backup("target", gate=self.gate)
        path = self.backups / made["backup_id"] / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"][0]["name"] = r"..\escaped.hss"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        before = tree(self.live)

        done = saves.restore(made["backup_id"], made["backup_id"], gate=self.gate)
        self.assertTrue(done["refused"], done)
        self.assertEqual(done["reason"], "backup_corrupt")
        self.assertIn("escaped.hss", done["detail"])
        self.assertEqual(tree(self.live), before)
        self.assertFalse((self.root / "escaped.hss").exists())

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
