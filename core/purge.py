"""
MailRepo - Permanent deletion of archive folders.

One place that turns "these folders are to be destroyed" into files
removed from disk and rows removed from the database. It existed as
four hand-copied blocks in web/blueprints/api/folders.py and a fifth,
in the automatic trash cleanup, that deleted the rows and left every
encrypted message file on disk (code review 2026-11, #6).
"""

from utils.log import get_logger

from .config import Config
from .database import Database

log = get_logger(__name__)

# Bound parameters per statement. Well under every SQLite build's limit.
_CHUNK = 500


def _chunks(items: list) -> list[list]:
    return [items[i : i + _CHUNK] for i in range(0, len(items), _CHUNK)]


def folder_tree_ids(root_ids) -> list[int]:
    """The given folders plus every descendant, each id once."""
    found: list[int] = []
    seen: set[int] = set()
    frontier = [int(r) for r in root_ids]
    while frontier:
        fresh = [f for f in dict.fromkeys(frontier) if f not in seen]
        seen.update(fresh)
        found.extend(fresh)
        frontier = []
        for chunk in _chunks(fresh):
            marks = ",".join("?" * len(chunk))
            rows = Database.fetchall(
                f"SELECT id FROM folders WHERE parent_id IN ({marks})", tuple(chunk)
            )
            frontier.extend(r["id"] for r in rows)
    return found


def count_messages_in(folder_ids) -> int:
    total = 0
    for chunk in _chunks(list(folder_ids)):
        marks = ",".join("?" * len(chunk))
        total += Database.fetchone(
            f"SELECT COUNT(*) AS cnt FROM messages WHERE folder_id IN ({marks})", tuple(chunk)
        )["cnt"]
    return total


def purge_folders(root_ids) -> dict:
    """Permanently delete folders, their descendants and all their mail.

    Message files are unlinked first, then the rows go (the folder delete
    cascades to messages). A file that cannot be removed is logged and
    left; its row still goes, as before. Does NOT commit: the caller
    owns the transaction.

    Returns ``{"folders": n, "emails": n, "files_removed": n}``.
    """
    all_ids = folder_tree_ids(root_ids)
    if not all_ids:
        return {"folders": 0, "emails": 0, "files_removed": 0}

    base = Config.get_base_path()
    emails = 0
    removed = 0
    for chunk in _chunks(all_ids):
        marks = ",".join("?" * len(chunk))
        rows = Database.fetchall(
            f"SELECT filepath FROM messages WHERE folder_id IN ({marks})", tuple(chunk)
        )
        emails += len(rows)
        for row in rows:
            try:
                filepath = base / row["filepath"]
                if filepath.exists():
                    filepath.unlink()
                    removed += 1
            except Exception as e:
                log.warning(f"Could not delete file {row['filepath']}: {e}")

    # The per-folder directories, if now empty.
    for fid in all_ids:
        try:
            folder_path = Config.get_archive_path() / str(fid)
            if folder_path.is_dir():
                folder_path.rmdir()
        except OSError:
            pass

    for chunk in _chunks(all_ids):
        marks = ",".join("?" * len(chunk))
        Database.execute(f"DELETE FROM folders WHERE id IN ({marks})", tuple(chunk))

    return {"folders": len(all_ids), "emails": emails, "files_removed": removed}
