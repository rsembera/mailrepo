"""
MailRepo API - Email Parsing Utilities

Handles parsing of various email formats:
- Standard mbox files
- Apple Mail mbox exports (.mbox directories with emlx files)
- Individual .eml files
- Individual .emlx files (Apple Mail format)
"""

import email as email_lib
import html as html_lib
import mailbox
import os
import re
import threading
from email.header import decode_header
from email.parser import BytesHeaderParser
from email.utils import parsedate_to_datetime

# ---------------------------------------------------------------------------
# Reading mbox files
#
# Messages are read with mailbox.get_bytes(), which returns the bytes as
# they are in the file. The earlier code used message.as_bytes(), which
# parses and regenerates each message: a CRLF message came back with LF
# endings, so the archived copy was not the original, signatures over it
# no longer verified, and the same message arriving by IMAP did not
# compare equal (code review 2026-11, #20).
#
# One open mailbox per file is kept, with its table of contents, so that
# fetching message N is a seek rather than a re-parse of everything
# before it. Committing individually staged messages from a large mbox
# used to be quadratic.
# ---------------------------------------------------------------------------

_mbox_lock = threading.Lock()
_mbox_cache: dict[str, tuple] = {}  # path -> ((mtime_ns, size), mailbox, keys)
_MBOX_CACHE_SIZE = 4


def _open_mbox(path: str):
    """``(mailbox, keys)`` for an mbox file. Call with _mbox_lock held."""
    path = str(path)
    st = os.stat(path)
    signature = (st.st_mtime_ns, st.st_size)
    hit = _mbox_cache.get(path)
    if hit and hit[0] == signature:
        return hit[1], hit[2]
    if hit:
        _close_quietly(_mbox_cache.pop(path)[1])
    while len(_mbox_cache) >= _MBOX_CACHE_SIZE:
        oldest = next(iter(_mbox_cache))
        _close_quietly(_mbox_cache.pop(oldest)[1])
    box = mailbox.mbox(path, create=False)
    keys = box.keys()
    _mbox_cache[path] = (signature, box, keys)
    return box, keys


def _close_quietly(box) -> None:
    try:
        box.close()
    except Exception:
        pass


def mbox_message_count(path: str) -> int:
    with _mbox_lock:
        return len(_open_mbox(path)[1])


def mbox_message_bytes(path: str, index: int) -> bytes | None:
    """The original bytes of message ``index`` in an mbox file, or None."""
    with _mbox_lock:
        box, keys = _open_mbox(path)
        if index < 0 or index >= len(keys):
            return None
        return box.get_bytes(keys[index])


def iter_mbox_bytes(path: str):
    """Yield ``(index, raw_bytes)`` for every message, one at a time."""
    for index in range(mbox_message_count(path)):
        raw = mbox_message_bytes(path, index)
        if raw is not None:
            yield index, raw


def _mbox_folder_of(raw: bytes) -> str:
    headers = BytesHeaderParser().parsebytes(raw, headersonly=True)
    return headers.get("X-Folder") or headers.get("X-Gmail-Labels") or ""


def iter_emails_from_import_folder(source_path: str, folder_path: str, import_type: str):
    """Yield ``(uid, raw_email_bytes)`` for the emails DIRECTLY in a folder.

    Only direct children: staging a parent folder without its children
    archives the parent's own emails and nothing nested. One message is
    in memory at a time, so a multi-gigabyte mbox does not have to fit
    in RAM. A source that cannot be opened raises; it used to come back
    as an empty list, which looked like "this folder has no mail".
    """
    if import_type == "eml":
        yield from _iter_eml_directory(source_path)
    elif import_type == "apple-mbox":
        yield from _iter_apple_mbox(folder_path)
    elif import_type == "mbox" and os.path.isfile(source_path):
        for index, raw in iter_mbox_bytes(source_path):
            if not folder_path or _mbox_folder_of(raw) == folder_path:
                yield f"mbox-{index}", raw


def count_emails_in_import_folder(source_path: str, folder_path: str, import_type: str) -> int:
    """How many emails iter_emails_from_import_folder will yield."""
    if import_type == "eml":
        if not os.path.isdir(source_path):
            return 0
        return sum(1 for name in os.listdir(source_path) if name.lower().endswith(".eml"))
    if import_type == "apple-mbox":
        mbox_internal = os.path.join(folder_path, "mbox")
        if os.path.exists(mbox_internal):
            return mbox_message_count(mbox_internal)
        messages_dir = os.path.join(folder_path, "Messages")
        if os.path.isdir(messages_dir):
            return sum(1 for name in os.listdir(messages_dir) if name.endswith(".emlx"))
        return 0
    if import_type == "mbox" and os.path.isfile(source_path):
        if not folder_path:
            return mbox_message_count(source_path)
        return sum(
            1 for _i, raw in iter_mbox_bytes(source_path) if _mbox_folder_of(raw) == folder_path
        )
    return 0


def get_emails_from_import_folder(source_path: str, folder_path: str, import_type: str) -> list:
    """List form of iter_emails_from_import_folder (loads everything)."""
    return list(iter_emails_from_import_folder(source_path, folder_path, import_type))


def _iter_eml_directory(source_path: str):
    if not os.path.isdir(source_path):
        return
    for i, filename in enumerate(sorted(os.listdir(source_path))):
        if filename.lower().endswith(".eml"):
            filepath = os.path.join(source_path, filename)
            try:
                with open(filepath, "rb") as f:
                    raw_email = f.read()
            except OSError:
                continue  # Skip unreadable files
            yield f"eml-{i}", raw_email


def _parse_eml_directory(source_path: str) -> list:
    """Parse a directory of .eml files."""
    return list(_iter_eml_directory(source_path))


def _iter_apple_mbox(folder_path: str):
    """
    Apple Mail export (.mbox directory).

    Apple Mail .mbox directories can contain either:
    - An 'mbox' file (standard mbox format)
    - A 'Messages' subdirectory with .emlx files
    """
    mbox_internal = os.path.join(folder_path, "mbox")
    if os.path.exists(mbox_internal):
        for index, raw in iter_mbox_bytes(mbox_internal):
            yield f"apple-{index}", raw
        return

    messages_dir = os.path.join(folder_path, "Messages")
    if os.path.isdir(messages_dir):
        for filename in sorted(os.listdir(messages_dir)):
            if filename.endswith(".emlx"):
                email_content = _parse_emlx_file(os.path.join(messages_dir, filename))
                if email_content:
                    yield f"emlx-{filename}", email_content


def _parse_apple_mbox(folder_path: str) -> list:
    return list(_iter_apple_mbox(folder_path))


def _parse_standard_mbox(source_path: str, folder_path: str) -> list:
    """Messages of a standard mbox whose folder header matches exactly."""
    return [
        (f"mbox-{index}", raw)
        for index, raw in iter_mbox_bytes(source_path)
        if not folder_path or _mbox_folder_of(raw) == folder_path
    ]


def _parse_emlx_file(filepath: str) -> bytes | None:
    """
    Parse an Apple Mail .emlx file.

    .emlx format:
    - First line: byte count of email content
    - Email content (RFC 822 format)
    - Apple plist metadata at the end

    The byte count is what delimits the message. Searching for the
    plist's "<?xml" instead cut a message short if it carried XML of its
    own and the file had no plist; that search is now only the fallback
    for a first line that is not a number.
    """
    try:
        with open(filepath, "rb") as f:
            content = f.read()
    except OSError:
        return None

    first_newline = content.find(b"\n")
    if first_newline <= 0:
        return None
    rest = content[first_newline + 1 :]
    try:
        length = int(content[:first_newline].strip())
    except ValueError:
        length = -1
    if 0 < length <= len(rest):
        return rest[:length]
    plist_marker = rest.rfind(b"<?xml version=")
    if plist_marker > 0:
        return rest[:plist_marker]
    return rest


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
    if source_path.endswith(".emlx"):
        return _parse_emlx_file(source_path)

    # Handle mbox files
    if uid.startswith("mbox-") or uid.startswith("apple-"):
        return _get_email_from_mbox_by_index(source_path, uid)

    # Handle standalone .eml files
    if source_path.endswith(".eml"):
        try:
            with open(source_path, "rb") as f:
                return f.read()
        except Exception:
            return None

    return None


def _get_email_from_mbox_by_index(source_path: str, uid: str) -> bytes | None:
    """Extract a specific email from mbox by the index in its UID ("mbox-5" -> 5)."""
    try:
        index = int(uid.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return None
    try:
        return mbox_message_bytes(source_path, index)
    except Exception:
        return None


# How much of a message's text is indexed for search. Was 10,000, which
# cut off long threads without saying so; text past the limit simply
# could not be found. 200,000 covers all but pathological messages and
# costs little: the text lives inside the encrypted database.
BODY_TEXT_LIMIT = 200_000


def extract_body_text(raw_email: bytes) -> str:
    """
    Extract plain text from email for full-text search indexing.

    Walks multipart messages to find text/plain parts and concatenates them.
    Limits output to BODY_TEXT_LIMIT characters for database storage.

    Args:
        raw_email: Raw email bytes (RFC 822 format)

    Returns:
        Plain text content, truncated to BODY_TEXT_LIMIT chars
    """
    try:
        msg = email_lib.message_from_bytes(raw_email)
        text_parts = []

        def decode_part(part):
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                try:
                    return payload.decode(charset, errors="replace")
                except Exception:
                    return payload.decode("utf-8", errors="replace")
            return ""

        def strip_html(html):
            """Strip HTML tags and entities, adding spaces for proper tokenization."""
            text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
            text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            # Decode entities, do not blank them: "caf&eacute;" and
            # "Montr&#233;al" must be indexed as the words they are.
            # (They used to become "caf" and "Montr&#233;al", so a search
            # for either word missed the message.)
            text = html_lib.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            return text

        plain_parts = []
        html_parts = []

        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    plain_parts.append(decode_part(part))
                elif part.get_content_type() == "text/html":
                    html_parts.append(strip_html(decode_part(part)))
        else:
            if msg.get_content_type() == "text/plain":
                plain_parts.append(decode_part(msg))
            elif msg.get_content_type() == "text/html":
                html_parts.append(strip_html(decode_part(msg)))

        # Prefer HTML-derived text (better tokenization from tag boundaries)
        # Fall back to plain text if no HTML
        text_parts = html_parts if html_parts else plain_parts

        return "\n".join(text_parts)[:BODY_TEXT_LIMIT]
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
