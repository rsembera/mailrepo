"""
Tests for the restore path — utils/backup.py's prepare/complete/cancel.

Restore had no automated coverage until Session 68. It had been exercised
by hand exactly twice: Session 34 (February 2026, against v1 crypto) and
the Session 67 drill (against v2). Between those two, the crypto stack was
replaced wholesale. A v2-breaks-restore regression would have gone
unnoticed until someone actually needed their data back — which is the
worst possible moment to discover it.

These tests are the Session 67 drill, automated: build a small v2 archive,
back it up, restore it, assert the restored bytes still decrypt under the
original password. The drill's one manual step (typing the master
password) is unnecessary here because the fixture knows it.
"""

import json
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.config import Config
from core.encryption import Encryption
from utils.backup import (
    cancel_restore,
    check_restore_pending,
    complete_restore,
    create_full_backup,
    create_incremental_backup,
    describe_restore_point_credentials,
    get_restore_points,
    get_verified_latest_restore_point,
    key_file_fingerprint,
    prepare_restore,
    read_key_file_from_chain,
    verify_restore_point_files,
)

PASSWORD = "TestPassword123!"

# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture
def archive_with_backup(initialized_app):
    """A small v2 archive plus one full backup of it."""
    app, password = initialized_app

    archive_root = Config.get_archive_path() / "1"
    archive_root.mkdir(parents=True, exist_ok=True)

    plaintexts = {
        "1/000.eml.enc": b"From: alice@example.com\r\nSubject: One\r\n\r\nFirst body.",
        "1/001.eml.enc": b"From: bob@example.com\r\nSubject: Two\r\n\r\nSecond body.",
        "1/002.eml.enc": b"From: carol@example.com\r\nSubject: Three\r\n\r\nThird body.",
    }

    for rel, pt in plaintexts.items():
        path = Config.get_archive_path() / rel
        path.write_bytes(Encryption.encrypt(pt))

    with app.app_context():
        backup_info = create_full_backup()
        yield {
            "app": app,
            "password": password,
            "plaintexts": plaintexts,
            "backup_info": backup_info,
        }


def _decrypts_to(staging_dir, rel_path, expected):
    """True if the staged copy of rel_path decrypts to expected plaintext."""
    staged = staging_dir / "archive" / rel_path
    if not staged.exists():
        return False
    return Encryption.decrypt(staged.read_bytes()) == expected


# ============================================================
# THE DRILL: a backup must restore to decryptable content
# ============================================================


class TestRestoreRoundTrip:
    """The claim that matters: backed-up bytes come back and still decrypt."""

    def test_full_backup_creates_a_restore_point(self, archive_with_backup):
        points = get_restore_points()
        assert len(points) >= 1
        assert points[0]["type"] == "full"

    def test_prepare_restore_stages_decryptable_files(self, archive_with_backup):
        points = get_restore_points()
        staging = Path(prepare_restore(points[0]["id"]))

        for rel, expected in archive_with_backup["plaintexts"].items():
            assert _decrypts_to(staging, rel, expected), f"{rel} did not survive"

    def test_backup_carries_its_own_key_material(self, archive_with_backup):
        """A backup that cannot be opened on a fresh machine is not a backup.

        The salt file and the database must travel inside the archive;
        this is what the Session 67 drill confirmed by hand.
        """
        points = get_restore_points()
        staging = Path(prepare_restore(points[0]["id"]))

        salt = staging / "data" / ".salt"
        assert salt.exists(), "backup does not contain the salt file"
        assert salt.read_bytes()[:4] == b"MRC2", "salt file is not v2 format"
        assert (staging / "data" / "mailrepo.db").exists()

    def test_restored_database_is_not_plaintext(self, archive_with_backup):
        points = get_restore_points()
        staging = Path(prepare_restore(points[0]["id"]))
        header = (staging / "data" / "mailrepo.db").read_bytes()[:16]
        assert not header.startswith(b"SQLite format 3")


# ============================================================
# INCREMENTAL CHAINS
# ============================================================


class TestIncrementalChain:
    """Restoring an incremental means replaying full + incrementals in order."""

    def test_incremental_restore_includes_later_changes(self, archive_with_backup):
        new_rel = "1/003.eml.enc"
        new_plain = b"From: dave@example.com\r\nSubject: Four\r\n\r\nAdded later."
        (Config.get_archive_path() / new_rel).write_bytes(Encryption.encrypt(new_plain))

        assert create_incremental_backup() is not None

        points = get_restore_points()
        newest = points[0]
        assert newest["type"] == "incremental"
        assert len(newest["files_needed"]) == 2, "chain should be full + incremental"

        staging = Path(prepare_restore(newest["id"]))

        # Everything from the full...
        for rel, expected in archive_with_backup["plaintexts"].items():
            assert _decrypts_to(staging, rel, expected)
        # ...plus the file that only exists in the incremental.
        assert _decrypts_to(staging, new_rel, new_plain)

    def test_deletion_propagates_through_the_chain(self, archive_with_backup):
        """Deleted files must not reappear on restore.

        This exercises the _backup_metadata.json branch, which only fires
        when an incremental actually records a deletion.
        """
        doomed = "1/002.eml.enc"
        (Config.get_archive_path() / doomed).unlink()

        assert create_incremental_backup() is not None

        points = get_restore_points()
        staging = Path(prepare_restore(points[0]["id"]))

        assert not (staging / "archive" / doomed).exists(), (
            "a file deleted before the incremental came back on restore"
        )
        # The survivors are untouched.
        for rel in ("1/000.eml.enc", "1/001.eml.enc"):
            assert _decrypts_to(staging, rel, archive_with_backup["plaintexts"][rel])

    def test_restoring_an_older_point_does_not_include_newer_files(self, archive_with_backup):
        new_rel = "1/003.eml.enc"
        (Config.get_archive_path() / new_rel).write_bytes(Encryption.encrypt(b"later"))
        create_incremental_backup()

        # Restore the FULL, not the incremental.
        full_point = next(p for p in get_restore_points() if p["type"] == "full")
        staging = Path(prepare_restore(full_point["id"]))

        assert not (staging / "archive" / new_rel).exists()


# ============================================================
# SAFETY: staging is not production
# ============================================================


class TestRestoreSafety:
    """prepare_restore must not touch live data until complete_restore runs."""

    def test_prepare_does_not_modify_production(self, archive_with_backup):
        live = Config.get_archive_path() / "1/000.eml.enc"
        before = live.read_bytes()

        prepare_restore(get_restore_points()[0]["id"])

        assert live.read_bytes() == before

    def test_prepare_creates_a_pre_restore_safety_backup(self, archive_with_backup):
        prepare_restore(get_restore_points()[0]["id"])
        assert any(p["type"] == "pre_restore" for p in get_restore_points()), (
            "no safety backup was taken before staging a restore"
        )

    def test_prepare_writes_a_pending_marker(self, archive_with_backup):
        prepare_restore(get_restore_points()[0]["id"])
        assert check_restore_pending()

    def test_cancel_clears_the_pending_restore(self, archive_with_backup):
        prepare_restore(get_restore_points()[0]["id"])
        cancel_restore()
        assert not check_restore_pending()

    def test_cancel_leaves_production_intact(self, archive_with_backup):
        live = Config.get_archive_path() / "1/000.eml.enc"
        before = live.read_bytes()

        prepare_restore(get_restore_points()[0]["id"])
        cancel_restore()

        assert live.read_bytes() == before
        assert (
            Encryption.decrypt(live.read_bytes())
            == (archive_with_backup["plaintexts"]["1/000.eml.enc"])
        )


# ============================================================
# COMPLETION
# ============================================================


class TestCompleteRestore:
    """complete_restore swaps staging into production at startup."""

    def test_complete_restores_a_deleted_file(self, archive_with_backup):
        victim = Config.get_archive_path() / "1/000.eml.enc"
        expected = archive_with_backup["plaintexts"]["1/000.eml.enc"]
        victim.unlink()

        prepare_restore(get_restore_points()[0]["id"])
        result = complete_restore()

        assert result is not None
        assert victim.exists(), "restore did not bring back the deleted file"
        assert Encryption.decrypt(victim.read_bytes()) == expected

    def test_complete_clears_the_pending_state(self, archive_with_backup):
        prepare_restore(get_restore_points()[0]["id"])
        complete_restore()
        assert not check_restore_pending()

    def test_complete_is_a_no_op_with_nothing_staged(self, archive_with_backup):
        assert complete_restore() is None


# ============================================================
# CHAIN VERIFICATION (the Session 67 gate, tested directly)
# ============================================================


class TestVerifyRestorePointFiles:
    """Previously only exercised indirectly through the password-change gate."""

    def test_healthy_chain_reports_no_problems(self, archive_with_backup):
        assert verify_restore_point_files(get_restore_points()[0]) == []

    def test_missing_file_is_reported(self, archive_with_backup):
        point = get_restore_points()[0]
        Path(point["files_needed"][0]).unlink()
        problems = verify_restore_point_files(point)
        assert len(problems) == 1
        assert "missing" in problems[0]

    def test_zero_byte_file_is_reported(self, archive_with_backup):
        point = get_restore_points()[0]
        Path(point["files_needed"][0]).write_bytes(b"")
        assert "zero bytes" in verify_restore_point_files(point)[0]

    def test_truncated_zip_is_reported(self, archive_with_backup):
        point = get_restore_points()[0]
        path = Path(point["files_needed"][0])
        path.write_bytes(path.read_bytes()[:20])
        assert "not a readable zip" in verify_restore_point_files(point)[0]

    def test_corrupt_entry_is_reported(self, archive_with_backup):
        """A zip whose central directory is fine but whose contents are not.

        This is the case testzip() exists to catch — the file opens, lists
        its entries, and only fails when you actually read the bytes.
        """
        point = get_restore_points()[0]
        path = Path(point["files_needed"][0])

        with zipfile.ZipFile(path) as zf:
            first = zf.infolist()[0]
            offset = first.header_offset + 128

        data = bytearray(path.read_bytes())
        for i in range(offset, min(offset + 64, len(data))):
            data[i] ^= 0xFF
        path.write_bytes(bytes(data))

        problems = verify_restore_point_files(point)
        assert problems, "corrupted payload passed verification"

    def test_verified_latest_refuses_a_broken_newest_point(self, archive_with_backup):
        """No silent fallback to an older backup.

        Someone who believes they have an hour-old backup must not be
        handed one from last week without being told.
        """
        point = get_restore_points()[0]
        Path(point["files_needed"][0]).unlink()

        found, problems = get_verified_latest_restore_point()
        assert found is None
        assert problems


# ============================================================
# CREDENTIAL FINGERPRINTING OF RESTORE POINTS
# ============================================================


class TestRestorePointCredentials:
    """Restoring replaces the key file, so a backup opens with whatever
    credentials were in force when it was taken. Detecting that needs no
    password: each rewrap changes one half of the key file and leaves the
    other byte-identical."""

    def test_fresh_backup_is_current(self, archive_with_backup):
        point = get_restore_points()[0]
        assert point["credential_status"] == "current"
        assert point["credential_note"] == ""

    def test_v2_backup_flagged_once_the_archive_has_a_recovery_key(self, archive_with_backup):
        """The pre-migration case: restoring it drops the recovery key."""
        from core.crypto_migration_v3 import migrate_to_v3

        migrate_to_v3(PASSWORD)

        points = get_restore_points()
        v2_point = next(p for p in points if p["credential_status"] == "predates_recovery_key")
        assert "recovery key" in v2_point["credential_note"]

    def test_password_change_flags_older_backups(self, archive_with_backup):
        from core.crypto_migration_v3 import migrate_to_v3
        from core.password_change import change_master_password

        migrate_to_v3(PASSWORD)
        create_full_backup()  # taken under the current password
        change_master_password(PASSWORD, "ADifferentPassword456!")

        statuses = {p["credential_status"] for p in get_restore_points()}
        assert "password_changed" in statuses

        flagged = next(
            p for p in get_restore_points() if p["credential_status"] == "password_changed"
        )
        assert "password you used then" in flagged["credential_note"]
        # The recovery key is untouched by a password change, and the note
        # must say so — otherwise the user assumes they have nothing.
        assert "recovery key still works" in flagged["credential_note"]

    def test_recovery_key_rotation_flags_older_backups(self, archive_with_backup):
        from core.crypto_migration_v3 import migrate_to_v3
        from core.password_change import rotate_recovery_key

        migrate_to_v3(PASSWORD)
        create_full_backup()
        rotate_recovery_key(PASSWORD)

        statuses = {p["credential_status"] for p in get_restore_points()}
        assert "recovery_key_rotated" in statuses

    def test_rotating_recovery_key_does_not_flag_the_password(self, archive_with_backup):
        """Each half is independent; a rotation must not imply the password
        moved, or the warning becomes noise."""
        from core.crypto_migration_v3 import migrate_to_v3
        from core.password_change import rotate_recovery_key

        migrate_to_v3(PASSWORD)
        create_full_backup()
        rotate_recovery_key(PASSWORD)

        statuses = {p["credential_status"] for p in get_restore_points()}
        assert "password_changed" not in statuses
        assert "both_changed" not in statuses

    def test_both_changed_when_both_rotate(self, archive_with_backup):
        from core.crypto_migration_v3 import migrate_to_v3
        from core.password_change import change_master_password, rotate_recovery_key

        migrate_to_v3(PASSWORD)
        create_full_backup()
        rotate_recovery_key(PASSWORD)
        change_master_password(PASSWORD, "ADifferentPassword456!")

        statuses = {p["credential_status"] for p in get_restore_points()}
        assert "both_changed" in statuses

    def test_pre_v2_key_file_is_reported_as_unopenable(self, archive_with_backup):
        """Key files with no magic predate v2, whose code was deleted.

        Rick's real archive has 102 of these. They are not 'needs an older
        password' — no current build can open them at all.
        """
        blob = b"\xf0;x\x9b" + b"\x00" * 148  # 152 bytes, no magic: v1 shape
        assert key_file_fingerprint(blob)["version"] == 1

        result = describe_restore_point_credentials([], current_blob=None)
        assert result["status"] in ("unknown", "obsolete_crypto")

    def test_effective_key_file_is_the_last_one_in_the_chain(self, archive_with_backup):
        """Incrementals only carry changed files.

        Most do not contain the key file at all, so the one that lands on
        disk comes from the last backup in the chain that has it. Reading
        the full's copy would misreport every chain that spans a change.
        """
        from core.crypto_migration_v3 import migrate_to_v3

        # Full is v2; the migration then rewrites every file, so the next
        # incremental carries the v3 key file.
        migrate_to_v3(PASSWORD)
        create_incremental_backup()

        newest = get_restore_points()[0]
        assert len(newest["files_needed"]) >= 2
        blob = read_key_file_from_chain(newest["files_needed"])
        assert blob[:4] == b"MRC3", "chain reported the older key file instead of the effective one"
        assert newest["credential_status"] == "current"


# ============================================================
# REVIEW FINDINGS — regression tests
# ============================================================
#
# These encode bugs found in the Session 74 pre-tag review and
# reproduced in a sandbox before any fix was written. Each one failed
# against the code as it stood.


class TestChainReplayCorrectness:
    """The restore path reconstructed states that never existed."""

    def test_delete_then_recreate_survives_restore(self, archive_with_backup):
        """Finding 1 (critical).

        Deletions used to be accumulated across every zip in the chain
        and applied after all extractions, so a file deleted in
        incremental N and recreated in N+1 was extracted correctly and
        then removed by N's stale tombstone. The restore reported
        success.

        The trigger is ordinary use for this app: permanently delete an
        archived email, later re-commit the same message to the same
        folder — `{folder_id}/{account}_{uid}.eml.enc` repeats exactly.
        """
        path = Config.get_archive_path() / "1/000.eml.enc"
        recreated = b"From: alice@example.com\r\nSubject: One\r\n\r\nRECREATED"

        path.unlink()
        assert create_incremental_backup() is not None

        time.sleep(1.05)  # distinct filenames; see finding 6
        path.write_bytes(Encryption.encrypt(recreated))
        assert create_incremental_backup() is not None

        staging = Path(prepare_restore(get_restore_points()[0]["id"]))
        staged = staging / "archive" / "1/000.eml.enc"

        assert staged.exists(), "file deleted then recreated was lost on restore"
        assert Encryption.decrypt(staged.read_bytes()) == recreated

    def test_deletion_still_applies_when_not_recreated(self, archive_with_backup):
        """The counterpart: per-zip ordering must not break real deletions."""
        path = Config.get_archive_path() / "1/002.eml.enc"
        path.unlink()
        assert create_incremental_backup() is not None

        staging = Path(prepare_restore(get_restore_points()[0]["id"]))
        assert not (staging / "archive" / "1/002.eml.enc").exists()


class TestMissingChainMemberIsReported:
    """A chain with a hole must not verify clean."""

    def test_missing_incremental_stays_in_files_needed(self, archive_with_backup):
        """Finding 2 (critical).

        get_restore_points() skipped incrementals absent from disk and
        kept building the chain, so a restore point could be full +
        incr1 + incr3 with incr2 silently gone. Verification reported no
        problems, because it checks that listed files open — not that the
        list is complete.
        """
        (Config.get_archive_path() / "1/003.eml.enc").write_bytes(Encryption.encrypt(b"second"))
        assert create_incremental_backup() is not None
        middle = get_restore_points()[0]

        time.sleep(1.05)
        (Config.get_archive_path() / "1/004.eml.enc").write_bytes(Encryption.encrypt(b"third"))
        assert create_incremental_backup() is not None

        # Lose the middle incremental, as cloud eviction or partial sync would.
        Path(middle["files_needed"][-1]).unlink()

        newest = get_restore_points()[0]
        assert len(newest["files_needed"]) == 3, (
            "missing incremental was silently dropped from the chain"
        )

        problems = verify_restore_point_files(newest)
        assert problems, "chain with a hole verified clean"
        assert "missing" in problems[0]

    def test_gate_refuses_a_chain_with_a_hole(self, archive_with_backup):
        """The consequence: the non-resumable windows must not open."""
        (Config.get_archive_path() / "1/003.eml.enc").write_bytes(Encryption.encrypt(b"second"))
        create_incremental_backup()
        middle = get_restore_points()[0]

        time.sleep(1.05)
        (Config.get_archive_path() / "1/004.eml.enc").write_bytes(Encryption.encrypt(b"third"))
        create_incremental_backup()

        Path(middle["files_needed"][-1]).unlink()

        found, problems = get_verified_latest_restore_point()
        assert found is None
        assert problems


class TestBackupFilenameCollisions:
    """Finding 6. Two backups in one second used to overwrite each other."""

    def test_same_second_backups_get_distinct_filenames(self, archive_with_backup):
        from utils.backup import generate_backup_filename

        backups_dir = Config.get_data_path().parent / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)

        first = generate_backup_filename("full", backups_dir)
        (backups_dir / first).write_bytes(b"placeholder")
        second = generate_backup_filename("full", backups_dir)

        assert first != second, "second backup in the same second would overwrite the first"

    def test_back_to_back_backups_do_not_clobber(self, archive_with_backup):
        """End to end: no sleep, so both land in the same second."""
        (Config.get_archive_path() / "1/003.eml.enc").write_bytes(Encryption.encrypt(b"a"))
        first = create_incremental_backup()
        (Config.get_archive_path() / "1/004.eml.enc").write_bytes(Encryption.encrypt(b"b"))
        second = create_incremental_backup()

        assert first["filename"] != second["filename"]
        for info in (first, second):
            assert (Path(info.get("backup_dir", "")) / info["filename"]).exists() or (
                Config.get_data_path().parent / "backups" / info["filename"]
            ).exists()


class TestSafetyBackupsAreAllReachable:
    """Finding 7. Only the newest used to be offered."""

    def test_every_safety_backup_becomes_a_restore_point(self, archive_with_backup):
        from utils.backup import create_pre_restore_backup

        create_pre_restore_backup()
        time.sleep(1.05)
        create_pre_restore_backup()

        safety = [p for p in get_restore_points() if p["type"] == "pre_restore"]
        assert len(safety) >= 2, (
            "older safety backups are unreachable — which is exactly when "
            "you want one, after a second bad restore"
        )
        assert len({p["id"] for p in safety}) == len(safety)


class TestSafetyBackupLocation:
    """Finding 10. The rollback copy never left the machine."""

    def test_safety_backup_honours_configured_location(self, archive_with_backup):
        from core.database import set_setting
        from utils.backup import create_pre_restore_backup

        custom = Config.get_base_path() / "custom_backups"
        custom.mkdir(parents=True, exist_ok=True)
        set_setting("backup_location", str(custom))

        create_pre_restore_backup()

        assert list(custom.glob("pre_restore_*.zip")), (
            "safety backup went to the repo-local dir, which never syncs off-machine"
        )


class TestRetentionKeepsSomethingUsable:
    """Finding 3. 'Keep at least one valid restore point' was a docstring
    promise the code did not implement."""

    def _age_manifest(self, backups_dir, hours, keep_newest_chain=None):
        """Backdate every chain except one, so retention has work to do."""
        manifest_path = backups_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        old = (datetime.now() - timedelta(hours=hours)).isoformat()
        for entry in manifest["backups"]:
            if keep_newest_chain and entry.get("chain_id") == keep_newest_chain:
                continue
            entry["created_at"] = old
        manifest_path.write_text(json.dumps(manifest))

    def test_refuses_to_prune_when_the_kept_chain_is_broken(self, archive_with_backup):
        """The case that loses everything.

        If the newest chain is corrupt and the older ones have aged past
        retention, the old code deleted them and kept the one that does
        not open. Since Session 69 cleanup runs on every automatic
        backup, so this executes daily.
        """
        from utils.backup import cleanup_old_backups

        backups_dir = Config.get_data_path().parent / "backups"

        # A second, newer chain.
        time.sleep(1.05)
        newest = create_full_backup()
        newest_chain = json.loads((backups_dir / "manifest.json").read_text())
        newest_chain_id = next(
            b["chain_id"] for b in newest_chain["backups"] if b["filename"] == newest["filename"]
        )

        self._age_manifest(backups_dir, hours=24 * 400, keep_newest_chain=newest_chain_id)

        # Break the chain we would be keeping.
        newest_path = backups_dir / newest["filename"]
        newest_path.write_bytes(b"corrupt")

        before = {p["filename"] for p in get_restore_points()}
        cleanup_old_backups("1_year")
        after = {p["filename"] for p in get_restore_points()}

        assert before == after, (
            "retention deleted older chains while keeping one that does not open"
        )

    def test_prunes_normally_when_the_kept_chain_verifies(self, archive_with_backup):
        """The counterpart: the guard must not disable retention outright."""
        from utils.backup import cleanup_old_backups

        backups_dir = Config.get_data_path().parent / "backups"

        time.sleep(1.05)
        newest = create_full_backup()
        manifest = json.loads((backups_dir / "manifest.json").read_text())
        newest_chain_id = next(
            b["chain_id"] for b in manifest["backups"] if b["filename"] == newest["filename"]
        )

        self._age_manifest(backups_dir, hours=24 * 400, keep_newest_chain=newest_chain_id)

        before = len(get_restore_points())
        cleanup_old_backups("1_year")
        after = len(get_restore_points())

        assert after < before, "retention did not prune a healthy, aged-out chain"
        assert any(p["filename"] == newest["filename"] for p in get_restore_points())


# ============================================================
# Security review 2026-09, finding 4: a backup must not be able to name
# files outside the staging directory for deletion, and a manifest must
# not be able to point at zips outside its folder.
# ============================================================


def _rewrite_metadata(zip_path: Path, deleted_files):
    """Replace _backup_metadata.json inside a zip, as an attacker with
    write access to the backup folder would."""
    tmp = zip_path.with_suffix(".tmp")
    with (
        zipfile.ZipFile(zip_path, "r") as src,
        zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst,
    ):
        for item in src.infolist():
            if item.filename == "_backup_metadata.json":
                meta = json.loads(src.read(item.filename))
                meta["deleted_files"] = deleted_files
                dst.writestr(item.filename, json.dumps(meta))
            else:
                dst.writestr(item, src.read(item.filename))
    tmp.replace(zip_path)


class TestTombstoneTraversal:
    @pytest.fixture
    def incremental(self, archive_with_backup):
        (Config.get_archive_path() / "1/002.eml.enc").unlink()
        info = create_incremental_backup()
        assert info is not None
        from utils.backup import get_backup_path_for_entry

        return get_backup_path_for_entry(info)

    @pytest.mark.parametrize(
        "evil",
        [
            "../../victim.txt",
            "archive/../../victim.txt",
            "/tmp/victim.txt",
            "data/../../../victim.txt",
            "victim.txt",  # outside data/ and archive/
            "",
        ],
    )
    def test_forged_tombstone_is_rejected(self, incremental, evil, tmp_path):
        from utils.backup import UnsafeBackupPathError

        victim = Config.get_base_path().parent / "victim.txt"
        victim.write_text("do not delete")
        try:
            _rewrite_metadata(incremental, [evil])
            points = get_restore_points()
            with pytest.raises(UnsafeBackupPathError):
                prepare_restore(points[0]["id"])
            assert victim.exists()
        finally:
            victim.unlink(missing_ok=True)

    def test_legitimate_tombstone_still_works(self, incremental):
        _rewrite_metadata(incremental, ["archive/1/001.eml.enc"])
        points = get_restore_points()
        staging = Path(prepare_restore(points[0]["id"]))
        assert not (staging / "archive/1/001.eml.enc").exists()
        assert (staging / "archive/1/000.eml.enc").exists()


class TestSafePaths:
    def test_relpath_accepts_backup_shapes(self):
        from utils.backup import safe_backup_relpath

        assert safe_backup_relpath("data/mailrepo.db") == "data/mailrepo.db"
        assert safe_backup_relpath("archive/1/000.eml.enc") == "archive/1/000.eml.enc"

    @pytest.mark.parametrize(
        "bad", ["data", "archive/", "data/./x", "a\\b", "data/x\x00y", None, 5]
    )
    def test_relpath_rejects(self, bad):
        from utils.backup import UnsafeBackupPathError, safe_backup_relpath

        with pytest.raises(UnsafeBackupPathError):
            safe_backup_relpath(bad)

    @pytest.mark.parametrize("bad", ["../x.zip", "/tmp/x.zip", "a/b.zip", "..", "", "a\\b.zip"])
    def test_manifest_filename_rejects(self, bad):
        from utils.backup import UnsafeBackupPathError, safe_backup_filename

        with pytest.raises(UnsafeBackupPathError):
            safe_backup_filename(bad)

    def test_manifest_filename_accepts_bare(self):
        from utils.backup import safe_backup_filename

        assert safe_backup_filename("mailrepo_full_20260903.zip") == "mailrepo_full_20260903.zip"
