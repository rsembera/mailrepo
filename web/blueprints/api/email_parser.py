"""
MailRepo API - Email Parsing Utilities

Handles parsing of various email formats:
- Standard mbox files
- Apple Mail mbox exports (.mbox directories with emlx files)
- Individual .eml files
- Individual .emlx files (Apple Mail format)
"""

import os
import re
import mailbox
import email as email_lib
from email.header import decode_header
from email.utils import parsedate_to_datetime


def get_emails_from_import_folder(source_path: str, folder_path: str, import_type: str) -> list:
    """
    Get emails belonging DIRECTLY to a specific folder in an import.
    
    IMPORTANT: Only returns emails that are direct children of the folder,
    NOT emails from nested subfolders. This ensures that staging a parent
    folder without its children only archives the parent's direct emails.
    
    Args:
        source_path: Path to the mbox file or Apple Mail export root
        folder_path: Full path to the specific folder (e.g., "/path/to/Parent.mbox/Child.mbox")
        import_type: 'mbox', 'apple-mbox', or 'eml'
        
    Returns:
        List of (uid, raw_email_bytes) tuples
    """
    results = []
    
    if import_type == 'eml':
        results = _parse_eml_directory(source_path)
    elif import_type == 'apple-mbox':
        results = _parse_apple_mbox(folder_path)
    elif import_type == 'mbox' and os.path.isfile(source_path):
        results = _parse_standard_mbox(source_path, folder_path)
    
    return results


def _parse_eml_directory(source_path: str) -> list:
    """Parse a directory of .eml files."""
    results = []
    if os.path.isdir(source_path):
        for i, filename in enumerate(sorted(os.listdir(source_path))):
            if filename.lower().endswith('.eml'):
                filepath = os.path.join(source_path, filename)
                try:
                    with open(filepath, 'rb') as f:
                        raw_email = f.read()
                    results.append((f"eml-{i}", raw_email))
                except Exception:
                    pass  # Skip unreadable files
    return results


def _parse_apple_mbox(folder_path: str) -> list:
    """
    Parse Apple Mail export (.mbox directory).
    
    Apple Mail .mbox directories can contain either:
    - An 'mbox' file (standard mbox format)
    - A 'Messages' subdirectory with .emlx files
    """
    results = []
    
    # Try standard mbox file inside the .mbox directory
    mbox_internal = os.path.join(folder_path, 'mbox')
    if os.path.exists(mbox_internal):
        try:
            mbox = mailbox.mbox(mbox_internal)
            for i, message in enumerate(mbox):
                results.append((f"apple-{i}", message.as_bytes()))
        except Exception:
            pass  # Skip unreadable mbox
        return results
    
    # Check for emlx files in Messages subdirectory
    messages_dir = os.path.join(folder_path, 'Messages')
    if os.path.isdir(messages_dir):
        for i, filename in enumerate(sorted(os.listdir(messages_dir))):
            if filename.endswith('.emlx'):
                filepath = os.path.join(messages_dir, filename)
                email_content = _parse_emlx_file(filepath)
                if email_content:
                    results.append((f"emlx-{filename}", email_content))
    
    return results


def _parse_standard_mbox(source_path: str, folder_path: str) -> list:
    """
    Parse a standard mbox file, filtering by folder header for exact match.
    
    Args:
        source_path: Path to the mbox file
        folder_path: Folder path to filter by (emails in child folders excluded)
    """
    results = []
    try:
        mbox = mailbox.mbox(source_path)
        for i, message in enumerate(mbox):
            # Check if email belongs to this folder
            email_folder = message.get("X-Folder") or message.get("X-Gmail-Labels") or ""
            
            # If folder_path is empty/root, include emails without folder or match exactly
            if not folder_path or email_folder == folder_path:
                results.append((f"mbox-{i}", message.as_bytes()))
    except Exception:
        pass  # Skip unreadable mbox
    
    return results


def _parse_emlx_file(filepath: str) -> bytes | None:
    """
    Parse an Apple Mail .emlx file.
    
    .emlx format:
    - First line: byte count of email content
    - Email content (RFC 822 format)
    - Apple plist metadata at the end
    """
    try:
        with open(filepath, 'rb') as f:
            content = f.read()
        
        # Skip the byte count line
        first_newline = content.find(b'\n')
        if first_newline > 0:
            email_content = content[first_newline + 1:]
            # Find where the email ends (before Apple's plist metadata)
            plist_marker = email_content.rfind(b'<?xml version=')
            if plist_marker > 0:
                email_content = email_content[:plist_marker]
            return email_content
    except Exception:
        pass
    return None


def get_raw_email_from_import(source_path: str, uid: str) -> bytes | None:
    """
    Get raw email content from an imported source by UID.
    
    Used during commit to fetch specific emails for archiving.
    
    Args:
        source_path: Path to mbox file or emlx/eml file
        uid: Email UID (e.g., "mbox-5", "emlx-12345.emlx", "eml-0")
        
    Returns:
        Raw email bytes or None if not found
    """
    if not source_path or not os.path.exists(source_path):
        return None
    
    # Handle .emlx files (Apple Mail format)
    if source_path.endswith('.emlx'):
        return _parse_emlx_file(source_path)
    
    # Handle mbox files
    if uid.startswith('mbox-') or uid.startswith('apple-'):
        return _get_email_from_mbox_by_index(source_path, uid)
    
    # Handle standalone .eml files
    if source_path.endswith('.eml'):
        try:
            with open(source_path, 'rb') as f:
                return f.read()
        except Exception:
            return None
    
    return None


def _get_email_from_mbox_by_index(source_path: str, uid: str) -> bytes | None:
    """Extract a specific email from mbox by index in UID."""
    try:
        # Extract index from uid (e.g., "mbox-5" -> 5)
        parts = uid.split('-')
        if len(parts) >= 2:
            index = int(parts[-1])
            mbox = mailbox.mbox(source_path)
            for i, message in enumerate(mbox):
                if i == index:
                    return message.as_bytes()
    except Exception:
        pass
    return None


def extract_body_text(raw_email: bytes) -> str:
    """
    Extract plain text from email for full-text search indexing.
    
    Walks multipart messages to find text/plain parts and concatenates them.
    Limits output to 10,000 characters for database storage.
    
    Args:
        raw_email: Raw email bytes (RFC 822 format)
        
    Returns:
        Plain text content, truncated to 10,000 chars
    """
    try:
        msg = email_lib.message_from_bytes(raw_email)
        text_parts = []
        
        def decode_part(part):
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or 'utf-8'
                try:
                    return payload.decode(charset, errors='replace')
                except Exception:
                    return payload.decode('utf-8', errors='replace')
            return ""
        
        def strip_html(html):
            """Strip HTML tags and entities, adding spaces for proper tokenization."""
            text = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', html, flags=re.IGNORECASE)
            text = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', text, flags=re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'&nbsp;', ' ', text)
            text = re.sub(r'&[a-zA-Z]+;', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text
        
        plain_parts = []
        html_parts = []
        
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
                    plain_parts.append(decode_part(part))
                elif part.get_content_type() == 'text/html':
                    html_parts.append(strip_html(decode_part(part)))
        else:
            if msg.get_content_type() == 'text/plain':
                plain_parts.append(decode_part(msg))
            elif msg.get_content_type() == 'text/html':
                html_parts.append(strip_html(decode_part(msg)))
        
        # Prefer HTML-derived text (better tokenization from tag boundaries)
        # Fall back to plain text if no HTML
        text_parts = html_parts if html_parts else plain_parts
        
        return "\n".join(text_parts)[:10000]
    except Exception:
        return ""


def decode_email_header(header_value: str) -> str:
    """
    Decode an email header that may contain encoded words (RFC 2047).
    
    Args:
        header_value: Raw header value
        
    Returns:
        Decoded string
    """
    if not header_value:
        return ""
    try:
        parts = decode_header(header_value)
        return " ".join(
            p.decode(c or "utf-8", errors="replace") if isinstance(p, bytes) else p
            for p, c in parts
        )
    except Exception:
        return str(header_value)


def parse_email_metadata(raw_email: bytes) -> dict:
    """
    Parse email metadata from raw bytes.
    
    Returns a dict with: subject, sender, recipients, message_id, date
    
    Args:
        raw_email: Raw email bytes
        
    Returns:
        Dict with parsed metadata fields
    """
    try:
        msg = email_lib.message_from_bytes(raw_email)
        
        subject = decode_email_header(msg.get("Subject", ""))[:500] or "(no subject)"
        sender = decode_email_header(msg.get("From", ""))
        message_id = msg.get("Message-ID", "")
        date_str = msg.get("Date", "")
        
        # Extract all recipient fields
        to_addr = decode_email_header(msg.get("To", ""))
        cc_addr = decode_email_header(msg.get("Cc", ""))
        bcc_addr = decode_email_header(msg.get("Bcc", ""))
        
        # Combine recipients for storage and searching
        recipients_parts = []
        if to_addr:
            recipients_parts.append(f"To: {to_addr}")
        if cc_addr:
            recipients_parts.append(f"Cc: {cc_addr}")
        if bcc_addr:
            recipients_parts.append(f"Bcc: {bcc_addr}")
        recipients = "\n".join(recipients_parts)
        
        try:
            date_ts = int(parsedate_to_datetime(date_str).timestamp()) if date_str else None
        except Exception:
            date_ts = None
        
        return {
            "subject": subject,
            "sender": sender,
            "recipients": recipients,
            "message_id": message_id,
            "date": date_ts,
        }
    except Exception:
        return {
            "subject": "(error)",
            "sender": "",
            "recipients": "",
            "message_id": "",
            "date": None,
        }
