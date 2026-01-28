"""
MailRepo API - Email Streaming Logic

Handles streaming of emails from IMAP servers and import sources.
Implements caching with UIDVALIDITY for incremental sync.
"""

from core import Database


def get_cached_emails(account_id: int, folder: str, uidvalidity: int) -> list[dict]:
    """
    Get cached email headers for a folder.
    
    Args:
        account_id: IMAP account ID
        folder: Folder name (e.g., "INBOX")
        uidvalidity: IMAP UIDVALIDITY value for cache validation
        
    Returns:
        List of email header dicts sorted by UID descending
    """
    rows = Database.fetchall(
        """SELECT uid, subject, sender, recipients, date, message_id
           FROM email_cache
           WHERE account_id = ? AND folder_name = ? AND uidvalidity = ?
           ORDER BY CAST(uid AS INTEGER) DESC""",
        (account_id, folder, uidvalidity)
    )
    return [
        {
            "uid": row["uid"],
            "subject": row["subject"],
            "from": row["sender"],
            "to": row["recipients"],
            "date": row["date"],
            "message_id": row["message_id"],
        }
        for row in rows
    ]


def get_highest_cached_uid(account_id: int, folder: str, uidvalidity: int) -> int:
    """
    Get the highest UID in cache for incremental sync.
    
    Used to determine which emails are new since last sync.
    """
    row = Database.fetchone(
        """SELECT MAX(CAST(uid AS INTEGER)) as max_uid
           FROM email_cache
           WHERE account_id = ? AND folder_name = ? AND uidvalidity = ?""",
        (account_id, folder, uidvalidity)
    )
    return row["max_uid"] if row and row["max_uid"] else 0


def clear_folder_cache(account_id: int, folder: str):
    """
    Clear cache for a folder (when UIDVALIDITY changes or force refresh).
    """
    Database.execute(
        "DELETE FROM email_cache WHERE account_id = ? AND folder_name = ?",
        (account_id, folder)
    )
    Database.commit()


def get_any_cached_emails(account_id: int, folder: str) -> list[dict]:
    """
    Get cached emails regardless of UIDVALIDITY (for offline mode).
    
    Used when IMAP connection fails but we have cached data.
    """
    rows = Database.fetchall(
        """SELECT uid, subject, sender, recipients, date, message_id
           FROM email_cache
           WHERE account_id = ? AND folder_name = ?
           ORDER BY CAST(uid AS INTEGER) DESC""",
        (account_id, folder)
    )
    return [
        {
            "uid": row["uid"],
            "subject": row["subject"],
            "from": row["sender"],
            "to": row["recipients"],
            "date": row["date"],
            "message_id": row["message_id"],
        }
        for row in rows
    ]


def cache_email(account_id: int, folder: str, uidvalidity: int, email: dict):
    """
    Cache a single email header.
    
    Uses INSERT OR REPLACE to handle both new and updated emails.
    """
    Database.execute(
        """INSERT OR REPLACE INTO email_cache
           (account_id, folder_name, uid, uidvalidity, subject, sender, recipients, date, message_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            account_id,
            folder,
            email.get("uid"),
            uidvalidity,
            email.get("subject"),
            email.get("from"),
            email.get("to"),
            email.get("date"),
            email.get("message_id"),
        )
    )


def remove_stale_cache_entries(account_id: int, folder: str, uidvalidity: int, valid_uids: list) -> int:
    """
    Remove cached emails that no longer exist on the server.
    
    Args:
        account_id: IMAP account ID
        folder: Folder name
        uidvalidity: Current UIDVALIDITY
        valid_uids: List of UIDs that currently exist on server
        
    Returns:
        Number of stale entries removed
    """
    if not valid_uids:
        return 0
    
    # Get all cached UIDs for this folder
    cached = Database.fetchall(
        """SELECT uid FROM email_cache
           WHERE account_id = ? AND folder_name = ? AND uidvalidity = ?""",
        (account_id, folder, uidvalidity)
    )
    
    cached_uids = {str(row["uid"]) for row in cached}
    valid_uid_set = {str(uid) for uid in valid_uids}
    stale_uids = cached_uids - valid_uid_set
    
    if stale_uids:
        # Delete stale entries
        placeholders = ",".join("?" * len(stale_uids))
        Database.execute(
            f"""DELETE FROM email_cache
               WHERE account_id = ? AND folder_name = ? AND uid IN ({placeholders})""",
            (account_id, folder, *stale_uids)
        )
        Database.commit()
    
    return len(stale_uids)
