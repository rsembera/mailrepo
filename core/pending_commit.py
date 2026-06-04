"""
MailRepo - Pending Commit Management

Tracks commit progress to allow resumption after interruption.
"""

import json
import uuid
from typing import Optional

from .database import Database


def create_commit_session(staged_emails: list, staged_folders: list, source_actions: dict) -> str:
    """
    Create a new commit session and save all items to pending_commit table.

    Args:
        staged_emails: List of email items to commit
        staged_folders: List of folder items to commit
        source_actions: Dict of source actions (leave/archive/trash/delete)

    Returns:
        commit_id: Unique identifier for this commit session
    """
    commit_id = str(uuid.uuid4())

    # Save emails
    for item in staged_emails:
        source_key = _build_source_key(item)
        action = source_actions.get(source_key, 'leave')

        Database.execute(
            """INSERT INTO pending_commit
               (commit_id, item_type, item_data, destination_folder_id, source_action, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (commit_id, 'email', json.dumps(item), item.get('destinationFolderId'), action)
        )

    # Save folders
    for item in staged_folders:
        source_key = _build_source_key_folder(item)
        action = source_actions.get(source_key, 'leave')

        Database.execute(
            """INSERT INTO pending_commit
               (commit_id, item_type, item_data, destination_folder_id, source_action, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (commit_id, 'folder', json.dumps(item), item.get('destinationFolderId'), action)
        )

    Database.commit()
    return commit_id


def get_pending_commit() -> Optional[dict]:
    """
    Check if there's an incomplete commit session.

    Returns:
        Dict with commit_id and counts, or None if no pending commit
    """
    row = Database.fetchone(
        """SELECT commit_id,
                  COUNT(*) as total,
                  SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                  SUM(CASE WHEN status = 'committed' THEN 1 ELSE 0 END) as committed,
                  SUM(CASE WHEN status = 'post_action_done' THEN 1 ELSE 0 END) as done,
                  MIN(created_at) as created_at
           FROM pending_commit
           WHERE status != 'post_action_done'
           GROUP BY commit_id
           HAVING pending > 0 OR committed > 0
           ORDER BY created_at DESC
           LIMIT 1"""
    )

    if not row:
        return None

    return {
        'commit_id': row['commit_id'],
        'total': row['total'],
        'pending': row['pending'],
        'committed': row['committed'],
        'done': row['done'],
        'created_at': row['created_at'],
    }


def get_pending_items(commit_id: str, status: str = 'pending') -> list:
    """
    Get items with a specific status from a commit session.

    Args:
        commit_id: The commit session ID
        status: Filter by status ('pending', 'committed', 'post_action_done')

    Returns:
        List of pending commit rows
    """
    rows = Database.fetchall(
        """SELECT id, item_type, item_data, destination_folder_id, source_action, status
           FROM pending_commit
           WHERE commit_id = ? AND status = ?
           ORDER BY id""",
        (commit_id, status)
    )

    # Parse JSON data
    result = []
    for row in rows:
        item = dict(row)
        item['item_data'] = json.loads(item['item_data'])
        result.append(item)

    return result


def get_committed_items_needing_post_action(commit_id: str) -> list:
    """
    Get committed items that still need post-action applied.

    Returns only IMAP items with non-'leave' actions.
    """
    rows = Database.fetchall(
        """SELECT id, item_type, item_data, destination_folder_id, source_action
           FROM pending_commit
           WHERE commit_id = ?
             AND status = 'committed'
             AND source_action IS NOT NULL
             AND source_action != 'leave'
           ORDER BY id""",
        (commit_id,)
    )

    result = []
    for row in rows:
        item = dict(row)
        item['item_data'] = json.loads(item['item_data'])
        # Only IMAP items have post-actions
        if item['item_data'].get('sourceType') != 'import':
            result.append(item)

    return result


def mark_item_committed(item_id: int) -> None:
    """Mark a pending item as committed (email saved to archive)."""
    Database.execute(
        "UPDATE pending_commit SET status = 'committed', updated_at = strftime('%s', 'now') WHERE id = ?",
        (item_id,)
    )


def mark_item_done(item_id: int) -> None:
    """Mark a committed item as fully done (post-action applied or not needed)."""
    Database.execute(
        "UPDATE pending_commit SET status = 'post_action_done', updated_at = strftime('%s', 'now') WHERE id = ?",
        (item_id,)
    )


def mark_all_committed_as_done(commit_id: str) -> None:
    """Mark all committed items as done (used when post-actions complete or skipped)."""
    Database.execute(
        """UPDATE pending_commit
           SET status = 'post_action_done', updated_at = strftime('%s', 'now')
           WHERE commit_id = ? AND status = 'committed'""",
        (commit_id,)
    )
    Database.commit()


def clear_commit_session(commit_id: str) -> None:
    """Remove all items from a commit session (called on successful completion)."""
    Database.execute("DELETE FROM pending_commit WHERE commit_id = ?", (commit_id,))
    Database.commit()


def discard_pending_commit(commit_id: str) -> None:
    """
    Discard a pending commit - user chose not to resume.

    Removes all pending items but keeps committed ones marked as done.
    """
    # Mark committed items as done (they're already in the archive)
    Database.execute(
        """UPDATE pending_commit
           SET status = 'post_action_done', updated_at = strftime('%s', 'now')
           WHERE commit_id = ? AND status = 'committed'""",
        (commit_id,)
    )

    # Delete pending items
    Database.execute(
        "DELETE FROM pending_commit WHERE commit_id = ? AND status = 'pending'",
        (commit_id,)
    )

    Database.commit()


def _build_source_key(item: dict) -> str:
    """Build source key for an email item to look up its action.

    Format: 'account:{accountId}:{destinationFolderId}' or 'import:{importId}:{destinationFolderId}'.
    Must match the frontend key format (sourceKey + ':' + destId).
    """
    if item.get('sourceType') == 'import':
        return f"import:{item.get('sourceImportId')}:{item.get('destinationFolderId')}"
    return f"account:{item.get('sourceAccountId')}:{item.get('destinationFolderId')}"


def _build_source_key_folder(item: dict) -> str:
    """Build source key for a folder item to look up its action.

    Format: 'account:{accountId}:{destinationFolderId}' or 'import:{importId}:{destinationFolderId}'.
    Must match the frontend key format (sourceKey + ':' + destId).
    """
    if item.get('sourceType') == 'import':
        return f"import:{item.get('importId')}:{item.get('destinationFolderId')}"
    return f"account:{item.get('accountId')}:{item.get('destinationFolderId')}"
