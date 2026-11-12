"""
Code review 2026-11, finding 6: permanent deletion removes the files.

The automatic trash cleanup deleted folder rows and let the cascade
take the message rows, which left every encrypted message file on disk
and in every later backup.
"""

import time

from core import Config, Database, Encryption
from core.database import set_setting
from core.purge import folder_tree_ids, purge_folders
from web.blueprints.auth import cleanup_expired_trash


def _folder(name, parent=None, deleted_at=None, retention_date=None):
    cur = Database.execute(
        "INSERT INTO folders (name, parent_id, deleted_at, retention_date) VALUES (?, ?, ?, ?)",
        (name, parent, deleted_at, retention_date),
    )
    return cur.lastrowid


def _message(folder_id, name):
    directory = Config.get_archive_path() / str(folder_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.eml.enc"
    path.write_bytes(Encryption.encrypt(b"Subject: s\r\n\r\nconfidential"))
    Database.execute(
        "INSERT INTO messages (folder_id, message_id, filepath) VALUES (?, ?, ?)",
        (folder_id, f"<{name}@x>", str(path.relative_to(Config.get_base_path()))),
    )
    return path


class TestAutomaticTrashCleanup:
    def test_expired_folders_take_their_files_with_them(self, initialized_app):
        old = int(time.time()) - 90 * 86400
        parent = _folder("Client", deleted_at=old)
        child = _folder("2019", parent=parent, deleted_at=old)
        files = [_message(parent, "a"), _message(child, "b")]
        Database.commit()
        set_setting("trash_retention_days", "30")

        cleanup_expired_trash()

        assert Database.fetchone("SELECT COUNT(*) AS c FROM messages")["c"] == 0
        assert Database.fetchone("SELECT COUNT(*) AS c FROM folders")["c"] == 0
        assert [f.exists() for f in files] == [False, False]

    def test_folders_not_yet_expired_are_untouched(self, initialized_app):
        recent = int(time.time()) - 86400
        folder = _folder("Recent", deleted_at=recent)
        path = _message(folder, "a")
        Database.commit()
        set_setting("trash_retention_days", "30")

        cleanup_expired_trash()

        assert path.exists()
        assert Database.fetchone("SELECT COUNT(*) AS c FROM messages")["c"] == 1

    def test_never_means_never(self, initialized_app):
        old = int(time.time()) - 900 * 86400
        folder = _folder("Old", deleted_at=old)
        path = _message(folder, "a")
        Database.commit()
        set_setting("trash_retention_days", "0")

        cleanup_expired_trash()
        assert path.exists()


class TestPurge:
    def test_tree_lists_every_descendant_once(self, initialized_app):
        a = _folder("a")
        b = _folder("b", parent=a)
        c = _folder("c", parent=b)
        other = _folder("other")
        Database.commit()
        assert sorted(folder_tree_ids([a, b])) == sorted([a, b, c])
        assert other not in folder_tree_ids([a])

    def test_purge_removes_files_rows_and_empty_directories(self, initialized_app):
        a = _folder("a")
        b = _folder("b", parent=a)
        keep = _folder("keep")
        gone = [_message(a, "x"), _message(b, "y")]
        kept = _message(keep, "z")
        Database.commit()

        result = purge_folders([a])
        Database.commit()

        assert result == {"folders": 2, "emails": 2, "files_removed": 2}
        assert not any(p.exists() for p in gone)
        assert not (Config.get_archive_path() / str(a)).exists()
        assert kept.exists()
        assert Database.fetchone("SELECT COUNT(*) AS c FROM messages")["c"] == 1

    def test_empty_trash_route_removes_nested_files(self, authenticated_client, initialized_app):
        now = int(time.time())
        parent = _folder("p", deleted_at=now)
        child = _folder("c", parent=parent, deleted_at=now)
        files = [_message(parent, "a"), _message(child, "b")]
        Database.commit()

        resp = authenticated_client.post("/api/trash/empty")
        assert resp.status_code == 200
        assert not any(f.exists() for f in files)

    def test_vault_batch_delete_reports_emails_and_removes_files(
        self, authenticated_client, initialized_app
    ):
        overdue = int(time.time()) - 86400
        a = _folder("a", retention_date=overdue)
        b = _folder("b", retention_date=overdue)
        files = [_message(a, "x"), _message(b, "y"), _message(b, "z")]
        Database.commit()

        resp = authenticated_client.post(
            "/api/folders/batch-permadelete", json={"folder_ids": [a, b]}
        )
        body = resp.get_json()
        assert resp.status_code == 200
        assert (body["folders_deleted"], body["emails_deleted"]) == (2, 3)
        assert not any(f.exists() for f in files)
