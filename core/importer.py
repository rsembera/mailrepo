"""
MailRepo - Import utilities.

Handles importing emails from .mbox files and individual .eml files.
"""

import mailbox
from email import message_from_bytes, message_from_binary_file
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Iterator

from .config import Config
from .encryption import Encryption
from .database import Database


class ImportError(Exception):
    """Raised when import operations fail."""
    pass


def decode_header_value(header: str) -> str:
    """Decode RFC 2047 encoded header."""
    if not header:
        return ""
    
    try:
        parts = decode_header(header)
        decoded = []
        for content, charset in parts:
            if isinstance(content, bytes):
                decoded.append(content.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(content)
        return " ".join(decoded)
    except:
        return header


def parse_email_metadata(raw_bytes: bytes) -> dict:
    """
    Extract metadata from raw email bytes.
    
    Args:
        raw_bytes: Raw RFC 2822 email.
        
    Returns:
        Dict with subject, sender, date, message_id.
    """
    msg = message_from_bytes(raw_bytes)
    
    subject = decode_header_value(msg.get("Subject", "(no subject)"))
    sender = decode_header_value(msg.get("From", ""))
    date_str = msg.get("Date", "")
    message_id = msg.get("Message-ID", "")
    
    # Parse date to timestamp
    date_ts = None
    if date_str:
        try:
            dt = parsedate_to_datetime(date_str)
            date_ts = int(dt.timestamp())
        except:
            pass
    
    return {
        "subject": subject[:500] if subject else "(no subject)",  # Truncate long subjects
        "sender": sender[:500] if sender else "",
        "date": date_ts,
        "date_str": date_str,
        "message_id": message_id,
    }


def import_eml_file(
    filepath: Path,
    folder_id: int,
    encrypted: bool = True,
) -> dict:
    """
    Import a single .eml file into the archive.
    
    Args:
        filepath: Path to .eml file.
        folder_id: Destination folder ID.
        encrypted: Whether to encrypt the stored file.
        
    Returns:
        Dict with import result (success, message_id, error).
    """
    try:
        raw_bytes = filepath.read_bytes()
        metadata = parse_email_metadata(raw_bytes)
        
        # Generate unique filename based on message-id or hash
        if metadata["message_id"]:
            # Clean message-id for filename
            safe_id = metadata["message_id"].strip("<>").replace("/", "_")[:100]
        else:
            # Use hash of content
            import hashlib
            safe_id = hashlib.sha256(raw_bytes).hexdigest()[:20]
        
        # Save to archive
        archive_path = Config.get_archive_path() / str(folder_id)
        archive_path.mkdir(parents=True, exist_ok=True)
        
        if encrypted:
            encrypted_data = Encryption.encrypt(raw_bytes)
            dest_path = archive_path / f"{safe_id}.eml.enc"
            dest_path.write_bytes(encrypted_data)
        else:
            dest_path = archive_path / f"{safe_id}.eml"
            dest_path.write_bytes(raw_bytes)
        
        # Create database record
        Database.execute(
            """
            INSERT INTO messages 
            (folder_id, source_account_id, message_id, subject, sender, date, filepath, encrypted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                folder_id,
                None,  # No source account for imported files
                metadata["message_id"],
                metadata["subject"],
                metadata["sender"],
                metadata["date"],
                str(dest_path.relative_to(Config.get_base_path())),
                1 if encrypted else 0,
            )
        )
        
        return {
            "success": True,
            "subject": metadata["subject"],
            "message_id": metadata["message_id"],
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "filename": filepath.name,
        }


def import_mbox_file(
    mbox_path: Path,
    folder_id: int,
    encrypted: bool = True,
    progress_callback=None,
) -> dict:
    """
    Import all emails from an .mbox file into the archive.
    
    Args:
        mbox_path: Path to .mbox file.
        folder_id: Destination folder ID.
        encrypted: Whether to encrypt stored files.
        progress_callback: Optional callback(current, total) for progress updates.
        
    Returns:
        Dict with import results (total, success_count, failed_count, errors).
    """
    try:
        mbox = mailbox.mbox(str(mbox_path))
        total = len(mbox)
        
        results = {
            "total": total,
            "success_count": 0,
            "failed_count": 0,
            "errors": [],
        }
        
        archive_path = Config.get_archive_path() / str(folder_id)
        archive_path.mkdir(parents=True, exist_ok=True)
        
        for i, message in enumerate(mbox):
            try:
                raw_bytes = message.as_bytes()
                metadata = parse_email_metadata(raw_bytes)
                
                # Generate unique filename
                if metadata["message_id"]:
                    safe_id = metadata["message_id"].strip("<>").replace("/", "_")[:100]
                else:
                    import hashlib
                    safe_id = hashlib.sha256(raw_bytes).hexdigest()[:20]
                
                # Ensure unique filename
                base_id = safe_id
                counter = 0
                while True:
                    if encrypted:
                        dest_path = archive_path / f"{safe_id}.eml.enc"
                    else:
                        dest_path = archive_path / f"{safe_id}.eml"
                    
                    if not dest_path.exists():
                        break
                    counter += 1
                    safe_id = f"{base_id}_{counter}"
                
                # Save file
                if encrypted:
                    encrypted_data = Encryption.encrypt(raw_bytes)
                    dest_path.write_bytes(encrypted_data)
                else:
                    dest_path.write_bytes(raw_bytes)
                
                # Create database record
                Database.execute(
                    """
                    INSERT INTO messages 
                    (folder_id, source_account_id, message_id, subject, sender, date, filepath, encrypted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        folder_id,
                        None,
                        metadata["message_id"],
                        metadata["subject"],
                        metadata["sender"],
                        metadata["date"],
                        str(dest_path.relative_to(Config.get_base_path())),
                        1 if encrypted else 0,
                    )
                )
                
                results["success_count"] += 1
                
            except Exception as e:
                results["failed_count"] += 1
                results["errors"].append({
                    "index": i,
                    "error": str(e),
                })
            
            # Progress callback
            if progress_callback:
                progress_callback(i + 1, total)
        
        Database.commit()
        return results
        
    except Exception as e:
        raise ImportError(f"Failed to read mbox file: {e}")


def scan_mbox_file(mbox_path: Path) -> dict:
    """
    Scan an mbox file and return summary without importing.
    
    Args:
        mbox_path: Path to .mbox file.
        
    Returns:
        Dict with message_count and sample subjects.
    """
    try:
        mbox = mailbox.mbox(str(mbox_path))
        total = len(mbox)
        
        # Get a few sample subjects
        samples = []
        for i, message in enumerate(mbox):
            if i >= 5:
                break
            subject = decode_header_value(message.get("Subject", "(no subject)"))
            sender = decode_header_value(message.get("From", ""))
            samples.append({
                "subject": subject[:100],
                "sender": sender[:100],
            })
        
        return {
            "message_count": total,
            "samples": samples,
        }
        
    except Exception as e:
        raise ImportError(f"Failed to scan mbox file: {e}")
