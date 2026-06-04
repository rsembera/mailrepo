"""
MailRepo - IMAP integration.

Handles IMAP connections for any email provider.
"""

import email
import imaplib
import json
import re
import ssl
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional

from utils.log import get_logger

from .encryption import Encryption

log = get_logger()


# Common IMAP servers (for auto-detection)
IMAP_SERVERS = {
    "gmail.com": ("imap.gmail.com", 993),
    "googlemail.com": ("imap.gmail.com", 993),
    "icloud.com": ("imap.mail.me.com", 993),
    "me.com": ("imap.mail.me.com", 993),
    "mac.com": ("imap.mail.me.com", 993),
    "outlook.com": ("outlook.office365.com", 993),
    "hotmail.com": ("outlook.office365.com", 993),
    "live.com": ("outlook.office365.com", 993),
    "yahoo.com": ("imap.mail.yahoo.com", 993),
    "fastmail.com": ("imap.fastmail.com", 993),
    "protonmail.com": ("127.0.0.1", 1143),  # ProtonMail Bridge
    "proton.me": ("127.0.0.1", 1143),
}


# Thread-discovery bounds (used by IMAP.find_thread).
#
# DEFAULT is the out-of-the-box cap and the value used when no explicit
# max is passed. CEILING is an absolute hard limit: find_thread clamps
# whatever it is given to at most this, so no setting, API payload, or
# stale database value can make a thread walk run unbounded against the
# mail server. FLOOR keeps a misconfigured tiny value from making the
# feature useless.
THREAD_MAX_MESSAGES_DEFAULT = 500
THREAD_MAX_MESSAGES_CEILING = 2000
THREAD_MAX_MESSAGES_FLOOR = 10


class IMAPError(Exception):
    """Raised when IMAP operations fail."""
    pass


class IMAP:
    """
    IMAP client for MailRepo.
    
    Handles connection, authentication, and email fetching from any IMAP server.
    """

    def __init__(self, host: str, port: int = 993, use_ssl: bool = True):
        """
        Initialize IMAP connection.
        
        Args:
            host: IMAP server hostname.
            port: IMAP port (default 993 for SSL).
            use_ssl: Whether to use SSL (default True).
        """
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.connection: Optional[imaplib.IMAP4_SSL | imaplib.IMAP4] = None

    @classmethod
    def detect_server(cls, email_address: str) -> tuple[str, int] | None:
        """
        Auto-detect IMAP server from email domain.
        
        Args:
            email_address: User's email address.
            
        Returns:
            Tuple of (host, port) or None if not found.
        """
        _, addr = parseaddr(email_address)
        if not addr or "@" not in addr:
            return None

        domain = addr.split("@")[1].lower()
        return IMAP_SERVERS.get(domain)

    def connect(self) -> None:
        """Establish connection to IMAP server."""
        try:
            if self.use_ssl:
                context = ssl.create_default_context()
                self.connection = imaplib.IMAP4_SSL(
                    self.host,
                    self.port,
                    ssl_context=context,
                    timeout=60,
                )
            else:
                self.connection = imaplib.IMAP4(self.host, self.port, timeout=60)
        except Exception as e:
            raise IMAPError(f"Failed to connect to {self.host}:{self.port}: {e}")

    def login(self, email_address: str, password: str) -> None:
        """
        Authenticate with IMAP server.
        
        Args:
            email_address: Email address (username).
            password: Password or app-specific password.
        """
        if not self.connection:
            self.connect()

        try:
            self.connection.login(email_address, password)
        except imaplib.IMAP4.error as e:
            raise IMAPError(f"Authentication failed: {e}")

    def disconnect(self) -> None:
        """Close IMAP connection."""
        if self.connection:
            try:
                self.connection.logout()
            except Exception:
                pass
            self.connection = None

    def list_folders(self) -> list[dict]:
        """
        Get list of IMAP folders (mailboxes).
        
        Returns:
            List of folder dicts with 'name', 'delimiter', and 'raw'.
        """
        if not self.connection:
            raise IMAPError("Not connected")

        try:
            status, data = self.connection.list()
            if status != "OK":
                raise IMAPError("Failed to list folders")

            folders = []
            for item in data:
                if item is None:
                    continue
                # Parse folder line: (\\Flags) "delimiter" "FolderName"
                # Example: (\HasNoChildren) "/" "INBOX/Subfolder"
                # Example: (\Noselect \HasChildren) "/" "[Gmail]"
                decoded = item.decode() if isinstance(item, bytes) else item

                # Extract flags
                flags_match = re.match(r'\(([^)]*)\)', decoded)
                flags = flags_match.group(1).split() if flags_match else []
                noselect = any(f.lower() == '\\noselect' for f in flags)

                # Extract delimiter - it's between the flags and folder name
                match = re.match(r'\([^)]*\)\s+"(.)"|\s+NIL\s+', decoded)
                delimiter = match.group(1) if match and match.group(1) else "/"

                # Extract folder name - it's after the delimiter specification
                parts = decoded.rsplit('" ', 1)
                if len(parts) == 2:
                    name = parts[1].strip('"')
                    folders.append({
                        "name": name,
                        "delimiter": delimiter,
                        "noselect": noselect,
                        "raw": decoded,
                    })

            return folders
        except Exception as e:
            raise IMAPError(f"Failed to list folders: {e}")

    def select_folder(self, folder: str = "INBOX") -> dict:
        """
        Select a folder for operations.
        
        Args:
            folder: Folder name (default INBOX).
            
        Returns:
            Dict with folder info (message_count, uidvalidity, highestmodseq).
        """
        if not self.connection:
            raise IMAPError("Not connected")

        try:
            status, data = self.connection.select(f'"{folder}"')
            if status != "OK":
                raise IMAPError(f"Failed to select folder: {folder}")

            result = {
                "folder": folder,
                "message_count": int(data[0]) if data else 0,
                "uidvalidity": None,
                "highestmodseq": None,
            }

            # Get UIDVALIDITY and HIGHESTMODSEQ using STATUS command
            try:
                status, status_data = self.connection.status(
                    f'"{folder}"', '(UIDVALIDITY HIGHESTMODSEQ)'
                )
                if status == 'OK' and status_data and status_data[0]:
                    response = status_data[0].decode() if isinstance(status_data[0], bytes) else status_data[0]

                    uv_match = re.search(r'UIDVALIDITY\s+(\d+)', response)
                    if uv_match:
                        result["uidvalidity"] = int(uv_match.group(1))

                    hm_match = re.search(r'HIGHESTMODSEQ\s+(\d+)', response)
                    if hm_match:
                        result["highestmodseq"] = int(hm_match.group(1))
            except Exception as e:
                # HIGHESTMODSEQ not supported — fall back to UIDVALIDITY only
                log.debug(f"Could not get STATUS with HIGHESTMODSEQ: {e}")
                try:
                    status, status_data = self.connection.status(
                        f'"{folder}"', '(UIDVALIDITY)'
                    )
                    if status == 'OK' and status_data and status_data[0]:
                        response = status_data[0].decode() if isinstance(status_data[0], bytes) else status_data[0]
                        uv_match = re.search(r'UIDVALIDITY\s+(\d+)', response)
                        if uv_match:
                            result["uidvalidity"] = int(uv_match.group(1))
                except Exception as e2:
                    log.debug(f"Could not get UIDVALIDITY: {e2}")

            return result
        except Exception as e:
            raise IMAPError(f"Failed to select folder {folder}: {e}")

    def search(self, criteria: str = "ALL", limit: int = 0) -> list[str]:
        """
        Search for messages in selected folder.
        
        Args:
            criteria: IMAP search criteria (default ALL).
            limit: Maximum messages to return (0 = no limit).
            
        Returns:
            List of message UIDs.
        """
        if not self.connection:
            raise IMAPError("Not connected")

        try:
            # Filter out messages flagged for deletion — these are ghost
            # messages that the server hasn't expunged yet (common with Gmail)
            effective_criteria = criteria
            if criteria == "ALL":
                effective_criteria = "NOT DELETED"

            status, data = self.connection.uid("SEARCH", None, effective_criteria)
            if status != "OK":
                raise IMAPError("Search failed")

            uids = data[0].split() if data[0] else []
            # Return most recent first (reverse order)
            uids = [uid.decode() for uid in reversed(uids)]
            # Apply limit only if specified (> 0)
            if limit > 0:
                uids = uids[:limit]
            return uids
        except Exception as e:
            raise IMAPError(f"Search failed: {e}")

    def fetch_headers(self, uid: str) -> dict:
        """
        Fetch message headers (lightweight).
        
        Args:
            uid: Message UID.
            
        Returns:
            Dict with subject, from, to, date, etc.
        """
        if not self.connection:
            raise IMAPError("Not connected")

        try:
            status, data = self.connection.uid(
                "FETCH", uid,
                "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])"
            )
            if status != "OK" or not data[0]:
                raise IMAPError(f"Failed to fetch headers for {uid}")

            # Parse headers
            header_data = data[0][1]
            if isinstance(header_data, bytes):
                header_data = header_data.decode("utf-8", errors="replace")

            msg = email.message_from_string(header_data)

            return {
                "uid": uid,
                "subject": self._decode_header(msg.get("Subject", "")),
                "from": self._decode_header(msg.get("From", "")),
                "to": self._decode_header(msg.get("To", "")),
                "date": msg.get("Date", ""),
                "message_id": msg.get("Message-ID", ""),
            }
        except Exception as e:
            raise IMAPError(f"Failed to fetch headers for {uid}: {e}")

    def fetch_raw(self, uid: str) -> bytes:
        """
        Fetch complete raw message (for saving as .eml).
        
        Args:
            uid: Message UID.
            
        Returns:
            Raw RFC 2822 email bytes.
        """
        if not self.connection:
            raise IMAPError("Not connected")

        try:
            status, data = self.connection.uid("FETCH", uid, "(RFC822)")
            if status != "OK" or not data[0]:
                raise IMAPError(f"Failed to fetch message {uid}")

            return data[0][1]
        except Exception as e:
            raise IMAPError(f"Failed to fetch message {uid}: {e}")

    def fetch_full(self, uid: str) -> dict:
        """
        Fetch complete message with parsed body for viewing.
        
        Args:
            uid: Message UID.
            
        Returns:
            Dict with headers and body (text and/or html).
        """
        raw = self.fetch_raw(uid)
        msg = email.message_from_bytes(raw)

        result = {
            "uid": uid,
            "subject": self._decode_header(msg.get("Subject", "")),
            "from": self._decode_header(msg.get("From", "")),
            "to": self._decode_header(msg.get("To", "")),
            "cc": self._decode_header(msg.get("Cc", "")),
            "date": msg.get("Date", ""),
            "message_id": msg.get("Message-ID", ""),
            "text_body": None,
            "html_body": None,
            "attachments": [],
        }

        # Pre-scan: extract every cid: reference that appears in the html
        # bodies of this message. A MIME part with a Content-ID is only
        # truly "inline" if its id is actually referenced by the html.
        # This matters for Gmail mobile and similar clients that set both
        # Content-Disposition: attachment AND Content-ID on attached
        # images that the html doesn\'t reference \u2014 those should appear
        # in the attachments list, not be silently dropped.
        import base64
        referenced_cids: set[str] = set()
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() != "text/html":
                    continue
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                try:
                    html_text = payload.decode(charset, errors="replace")
                except Exception:
                    continue
                for m in re.finditer(r'cid:([^"\'\s>]+)', html_text):
                    referenced_cids.add(m.group(1))

        # First pass: collect inline images for cid: replacement. Only
        # parts whose Content-ID is actually referenced in the html.
        inline_images = {}  # cid -> data URL

        if msg.is_multipart():
            for part in msg.walk():
                content_id = part.get("Content-ID")
                if not content_id:
                    continue
                cid = content_id.strip('<>')
                if cid not in referenced_cids:
                    # Has a Content-ID but the html doesn\'t use it \u2014
                    # the second pass will handle it as a regular attachment.
                    continue
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                content_type = part.get_content_type()
                b64_data = base64.b64encode(payload).decode('ascii')
                inline_images[cid] = f"data:{content_type};base64,{b64_data}"

        # Second pass: parse body and collect attachments
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                content_id = part.get("Content-ID")

                # Skip parts we registered as inline images above. Use the
                # set of referenced cids so we don\'t accidentally also skip
                # attachments that happen to have a Content-ID.
                if content_id and content_type.startswith("image/"):
                    cid = content_id.strip('<>')
                    if cid in referenced_cids:
                        continue

                # Collect attachments
                if "attachment" in content_disposition:
                    filename = part.get_filename()
                    if filename:
                        result["attachments"].append({
                            "filename": self._decode_header(filename),
                            "content_type": content_type,
                            "size": len(part.get_payload(decode=True) or b""),
                        })
                    continue

                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        result["text_body"] = (result["text_body"] or "") + payload.decode(charset, errors="replace")

                elif content_type == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        result["html_body"] = (result["html_body"] or "") + payload.decode(charset, errors="replace")
        else:
            # Simple message
            content_type = msg.get_content_type()
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")
                if content_type == "text/html":
                    result["html_body"] = body
                else:
                    result["text_body"] = body

        # Replace cid: references in HTML body with data URLs
        if result["html_body"] and inline_images:
            def replace_cid(match):
                cid = match.group(1)
                return inline_images.get(cid, match.group(0))

            result["html_body"] = re.sub(
                r'cid:([^"\'\s>]+)',
                replace_cid,
                result["html_body"]
            )

        # Linkify URLs and emails in HTML body that aren't already links
        if result["html_body"]:
            result["html_body"] = self._linkify_html(result["html_body"])

        return result

    def fetch_thread_headers(self, uid: str) -> dict:
        """Fetch just the thread-related headers for a message.

        Lighter than fetch_headers (which fetches FROM/TO/SUBJECT/DATE/MESSAGE-ID)
        and adds In-Reply-To and References. Used by find_thread().

        Returns dict with: message_id, in_reply_to, references (list), subject,
        from, date. Empty strings / empty list if a header is missing.
        """
        if not self.connection:
            raise IMAPError("Not connected")

        try:
            status, data = self.connection.uid(
                "FETCH", uid,
                "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID IN-REPLY-TO REFERENCES "
                "FROM SUBJECT DATE)])"
            )
            if status != "OK" or not data or not data[0]:
                raise IMAPError(f"Failed to fetch thread headers for {uid}")

            header_data = data[0][1]
            if isinstance(header_data, bytes):
                header_data = header_data.decode("utf-8", errors="replace")

            msg = email.message_from_string(header_data)

            # References is a space-separated list of <id> tokens; parse all
            references_raw = msg.get("References", "") or ""
            references = re.findall(r'<[^>]+>', references_raw)

            in_reply_to_raw = (msg.get("In-Reply-To", "") or "").strip()
            # In-Reply-To should be a single id but some clients put more
            in_reply_to = ''
            ir_match = re.search(r'<[^>]+>', in_reply_to_raw)
            if ir_match:
                in_reply_to = ir_match.group(0)

            return {
                "uid": uid,
                "message_id": (msg.get("Message-ID", "") or "").strip(),
                "in_reply_to": in_reply_to,
                "references": references,
                "subject": self._decode_header(msg.get("Subject", "")),
                "from": self._decode_header(msg.get("From", "")),
                "date": msg.get("Date", ""),
            }
        except IMAPError:
            raise
        except Exception as e:
            raise IMAPError(f"Failed to fetch thread headers for {uid}: {e}")

    def find_thread(
        self,
        source_folder: str,
        source_uid: str,
        *,
        also_search_folders: list[str] | None = None,
        max_messages: int = THREAD_MAX_MESSAGES_DEFAULT,
        max_iterations: int = 5,
        deadline_seconds: float = 10.0,
    ) -> dict:
        """Find all messages in the same thread as (source_folder, source_uid).

        Walks the In-Reply-To and References headers across the source folder
        and any folders in ``also_search_folders`` (typically the account's
        Sent folder). Pure header-walk \u2014 does not use the IMAP THREAD
        extension. This is the universal path that works on any RFC-3501 server.

        Args:
            source_folder: IMAP folder containing the message the user clicked.
            source_uid: UID of that message within source_folder.
            also_search_folders: Additional folders to search (Sent, typically).
                The source folder is always searched; pass extras here.
            max_messages: Cap on thread size. If we hit this we stop
                expanding and mark the result truncated. Clamped to
                [THREAD_MAX_MESSAGES_FLOOR, THREAD_MAX_MESSAGES_CEILING]
                regardless of the value passed.
            max_iterations: Max passes through the search loop. Mailing-list
                threads can ping-pong; this caps depth.
            deadline_seconds: Total wall-clock budget for the operation. If
                exceeded we return whatever we\'ve found and mark the result
                timed_out.

        Returns:
            {
              "thread": [ {folder, uid, message_id, subject, from, date}, ... ],
              "truncated": bool,
              "timed_out": bool,
              "method": "header_walk",
            }
            The list includes the source message itself, ordered by date ascending
            where the Date header is parseable (others append at the end).
        """
        import time

        if not self.connection:
            raise IMAPError("Not connected")

        # Defence in depth: clamp max_messages into [FLOOR, CEILING]
        # regardless of caller input. The settings endpoint validates the
        # user-facing value too, but this guarantees that even a bad value
        # arriving by any other path cannot make the walk run unbounded.
        max_messages = max(
            THREAD_MAX_MESSAGES_FLOOR,
            min(int(max_messages), THREAD_MAX_MESSAGES_CEILING),
        )

        start = time.monotonic()
        deadline = start + deadline_seconds

        # Build the search-folder list: source first, then extras minus duplicates
        search_folders = [source_folder]
        if also_search_folders:
            for f in also_search_folders:
                if f and f != source_folder and f not in search_folders:
                    search_folders.append(f)

        # First, select the source folder and fetch the starting message's headers
        self.select_folder(source_folder)
        source_headers = self.fetch_thread_headers(source_uid)
        source_mid = source_headers["message_id"]

        if not source_mid:
            # No Message-ID means we can\'t thread. Return just this message.
            return {
                "thread": [{
                    "folder": source_folder,
                    "uid": source_uid,
                    "message_id": "",
                    "subject": source_headers["subject"],
                    "from": source_headers["from"],
                    "date": source_headers["date"],
                }],
                "truncated": False,
                "timed_out": False,
                "method": "header_walk",
                "note": "source message has no Message-ID; cannot thread",
            }

        # Track messages we\'ve already added to the result keyed by message-id.
        # Each value: {folder, uid, message_id, subject, from, date}
        found: dict[str, dict] = {
            source_mid: {
                "folder": source_folder,
                "uid": source_uid,
                "message_id": source_mid,
                "subject": source_headers["subject"],
                "from": source_headers["from"],
                "date": source_headers["date"],
            }
        }

        # Set of message-ids we know about but haven\'t located in IMAP yet.
        # Seeded from the source's In-Reply-To + References.
        wanted: set[str] = set()
        if source_headers["in_reply_to"]:
            wanted.add(source_headers["in_reply_to"])
        for ref in source_headers["references"]:
            wanted.add(ref)
        wanted.discard(source_mid)

        truncated = False
        timed_out = False

        def _imap_escape(value: str) -> str:
            """IMAP SEARCH string literal: escape backslash and double-quote."""
            return value.replace("\\", "\\\\").replace('"', '\\"')

        iteration = 0
        while iteration < max_iterations:
            iteration += 1

            if time.monotonic() >= deadline:
                timed_out = True
                break
            if len(found) >= max_messages:
                truncated = True
                break

            new_messages_this_iteration = 0

            for folder in search_folders:
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                if len(found) >= max_messages:
                    truncated = True
                    break

                # Selecting a folder can fail (folder vanished, permissions);
                # log and skip rather than abort the whole operation.
                try:
                    self.select_folder(folder)
                except IMAPError as e:
                    log.debug(f"find_thread: skipping folder {folder}: {e}")
                    continue

                # Pass 1: locate any wanted IDs that are present in this folder.
                # Each wanted id is one SEARCH command \u2014 cheap, but bounded.
                for wid in list(wanted):
                    if time.monotonic() >= deadline:
                        timed_out = True
                        break
                    if len(found) >= max_messages:
                        truncated = True
                        break
                    if wid in found:
                        wanted.discard(wid)
                        continue
                    try:
                        status, data = self.connection.uid(
                            "SEARCH", None,
                            f'HEADER Message-ID "{_imap_escape(wid)}"',
                        )
                    except Exception as e:
                        log.debug(f"find_thread: search failed for {wid} in {folder}: {e}")
                        continue
                    if status != "OK" or not data or not data[0]:
                        continue
                    uids = data[0].split()
                    if not uids:
                        continue
                    # Take the first match (Message-ID is meant to be unique)
                    match_uid = uids[0].decode() if isinstance(uids[0], bytes) else uids[0]
                    try:
                        hdrs = self.fetch_thread_headers(match_uid)
                    except IMAPError:
                        continue
                    found[wid] = {
                        "folder": folder,
                        "uid": match_uid,
                        "message_id": wid,
                        "subject": hdrs["subject"],
                        "from": hdrs["from"],
                        "date": hdrs["date"],
                    }
                    wanted.discard(wid)
                    new_messages_this_iteration += 1
                    # Any new references from this message are also wanted
                    if hdrs["in_reply_to"] and hdrs["in_reply_to"] not in found:
                        wanted.add(hdrs["in_reply_to"])
                    for ref in hdrs["references"]:
                        if ref and ref not in found:
                            wanted.add(ref)

                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                if len(found) >= max_messages:
                    truncated = True
                    break

                # Pass 2: find replies that point at messages already in `found`.
                # One SEARCH per known id, returning UIDs of messages whose
                # In-Reply-To points at it.
                for known_id in list(found.keys()):
                    if time.monotonic() >= deadline:
                        timed_out = True
                        break
                    if len(found) >= max_messages:
                        truncated = True
                        break
                    try:
                        status, data = self.connection.uid(
                            "SEARCH", None,
                            f'HEADER In-Reply-To "{_imap_escape(known_id)}"',
                        )
                    except Exception as e:
                        log.debug(f"find_thread: reply-search failed for {known_id} in {folder}: {e}")
                        continue
                    if status != "OK" or not data or not data[0]:
                        continue
                    reply_uids = data[0].split()
                    for ruid_raw in reply_uids:
                        if len(found) >= max_messages:
                            truncated = True
                            break
                        ruid = ruid_raw.decode() if isinstance(ruid_raw, bytes) else ruid_raw
                        try:
                            hdrs = self.fetch_thread_headers(ruid)
                        except IMAPError:
                            continue
                        rmid = hdrs["message_id"]
                        if not rmid or rmid in found:
                            continue
                        found[rmid] = {
                            "folder": folder,
                            "uid": ruid,
                            "message_id": rmid,
                            "subject": hdrs["subject"],
                            "from": hdrs["from"],
                            "date": hdrs["date"],
                        }
                        new_messages_this_iteration += 1
                        if hdrs["in_reply_to"] and hdrs["in_reply_to"] not in found:
                            wanted.add(hdrs["in_reply_to"])
                        for ref in hdrs["references"]:
                            if ref and ref not in found:
                                wanted.add(ref)

            # If a full pass through all folders found nothing new, we're done.
            if new_messages_this_iteration == 0:
                break

        # Sort the thread by date when parseable; unparseable dates go to the end.
        def _date_key(item):
            try:
                return (0, parsedate_to_datetime(item["date"]))
            except Exception:
                return (1, None)
        sorted_thread = sorted(found.values(), key=_date_key)

        return {
            "thread": sorted_thread,
            "truncated": truncated,
            "timed_out": timed_out,
            "method": "header_walk",
        }

    def _decode_header(self, header: str) -> str:
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
        except Exception:
            return header

    def _linkify_html(self, html: str) -> str:
        """
        Convert plain text URLs and email addresses in HTML to clickable links.
        Skips content that's already inside anchor tags or other HTML attributes.
        """
        # Split HTML into parts: inside tags vs text content
        parts = re.split(r'(<a\s[^>]*>.*?</a>|<[^>]+>)', html, flags=re.IGNORECASE | re.DOTALL)

        result = []
        for part in parts:
            if not part:
                continue
            if part.startswith('<'):
                result.append(part)
                continue

            # This is text content - linkify URLs and emails
            # URL pattern: match until we hit whitespace, quotes, angle brackets, or HTML entities
            # The negative lookahead stops at &nbsp; &amp; &lt; etc but allows & in query strings
            part = re.sub(
                r'(https?://(?:(?!&(?:nbsp|amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)[^\s\u00a0<>"\'])+)',
                r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>',
                part
            )
            part = re.sub(
                r'\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b(?![^<]*>)',
                r'<a href="mailto:\1">\1</a>',
                part
            )
            result.append(part)

        return ''.join(result)

    # ==========================================
    # Credential management (stored encrypted)
    # ==========================================

    @classmethod
    def save_credentials(cls, account_id: int, email: str, password: str,
                         host: str, port: int, use_ssl: bool = True) -> None:
        """
        Save encrypted IMAP credentials to database.
        
        Args:
            account_id: Database account ID.
            email: Email address.
            password: Password or app password.
            host: IMAP server hostname.
            port: IMAP port.
            use_ssl: Whether to use SSL.
        """
        from .database import Database

        creds_data = {
            "email": email,
            "password": password,
            "host": host,
            "port": port,
            "use_ssl": use_ssl,
        }

        encrypted = Encryption.encrypt_string(json.dumps(creds_data))

        Database.execute(
            "UPDATE accounts SET email = ?, credentials_encrypted = ? WHERE id = ?",
            (email, encrypted, account_id)
        )
        Database.commit()

    @classmethod
    def load_credentials(cls, encrypted_creds: str) -> dict | None:
        """
        Load and decrypt IMAP credentials.
        
        Args:
            encrypted_creds: Encrypted credentials from database.
            
        Returns:
            Dict with email, password, host, port, use_ssl or None.
        """
        if not encrypted_creds:
            return None

        try:
            creds_json = Encryption.decrypt_string(encrypted_creds)
            return json.loads(creds_json)
        except Exception as e:
            log.warning(f"Error loading credentials: {e}")
            return None

    @classmethod
    def connect_with_credentials(cls, encrypted_creds: str) -> "IMAP":
        """
        Create connected and authenticated IMAP client from stored credentials.
        
        Args:
            encrypted_creds: Encrypted credentials from database.
            
        Returns:
            Connected IMAP instance.
        """
        creds = cls.load_credentials(encrypted_creds)
        if not creds:
            raise IMAPError("Failed to load credentials")

        client = cls(creds["host"], creds["port"], creds.get("use_ssl", True))
        client.connect()
        client.login(creds["email"], creds["password"])

        return client

    @classmethod
    def test_connection(cls, email: str, password: str,
                        host: str, port: int, use_ssl: bool = True) -> dict:
        """
        Test IMAP connection without saving credentials.
        
        Args:
            email: Email address.
            password: Password.
            host: IMAP server.
            port: IMAP port.
            use_ssl: Use SSL.
            
        Returns:
            Dict with success status and folder count or error.
        """
        client = None
        try:
            client = cls(host, port, use_ssl)
            client.connect()
            client.login(email, password)
            folders = client.list_folders()
            return {
                "success": True,
                "folder_count": len(folders),
                "message": f"Connected successfully. Found {len(folders)} folders."
            }
        except IMAPError as e:
            return {
                "success": False,
                "error": str(e),
            }
        finally:
            if client:
                client.disconnect()

    # ==========================================
    # Post-commit actions (archive, trash, delete)
    # ==========================================

    def get_special_folder(self, folder_type: str) -> str | None:
        """
        Find special folder name (Archive, Trash, Sent) for this IMAP server.

        Args:
            folder_type: 'archive', 'trash', or 'sent'

        Returns:
            Folder name or None if not found.
        """
        if not self.connection:
            raise IMAPError("Not connected")

        # Common folder names by type. Order matters slightly — provider-specific
        # names go first so we match (e.g.) "[Gmail]/Sent Mail" before the
        # generic "Sent" if both somehow exist.
        archive_names = ['Archive', '[Gmail]/All Mail', 'Archives', 'INBOX.Archive']
        trash_names = ['Trash', '[Gmail]/Trash', 'Deleted Items', 'Deleted Messages', 'INBOX.Trash']
        sent_names = [
            '[Gmail]/Sent Mail',  # Gmail
            'Sent Mail',          # some clients
            'Sent Items',         # Outlook / Exchange
            'Sent Messages',      # Apple Mail (older)
            'INBOX.Sent',         # cPanel / Courier-style nested
            'Sent',               # most everything else (Fastmail, generic IMAP, NCF)
        ]

        if folder_type == 'archive':
            search_names = archive_names
        elif folder_type == 'trash':
            search_names = trash_names
        elif folder_type == 'sent':
            search_names = sent_names
        else:
            log.warning(f"Unknown folder_type: {folder_type}")
            return None

        try:
            folders = self.list_folders()
            folder_names = [f['name'] for f in folders]

            # Try to find matching folder
            for name in search_names:
                if name in folder_names:
                    return name

            # Case-insensitive fallback
            for name in search_names:
                for folder_name in folder_names:
                    if folder_name.lower() == name.lower():
                        return folder_name

            return None
        except Exception as e:
            log.debug(f"Could not find {folder_type} folder: {e}")
            return None

    def move_email(self, uid: str, destination_folder: str) -> bool:
        """
        Move an email to another folder (copy + delete from source).
        
        Args:
            uid: Message UID.
            destination_folder: Destination folder name.
            
        Returns:
            True if successful.
        """
        if not self.connection:
            raise IMAPError("Not connected")

        try:
            # Copy to destination
            status, _ = self.connection.uid('COPY', uid, f'"{destination_folder}"')
            if status != 'OK':
                raise IMAPError(f"Failed to copy message {uid} to {destination_folder}")

            # Mark original as deleted
            status, _ = self.connection.uid('STORE', uid, '+FLAGS', '(\\Deleted)')
            if status != 'OK':
                raise IMAPError(f"Failed to mark message {uid} as deleted")

            # Expunge to remove from source folder
            self.connection.expunge()

            return True
        except Exception as e:
            raise IMAPError(f"Failed to move message {uid}: {e}")

    def archive_email(self, uid: str) -> bool:
        """
        Move email to Archive folder.
        
        Args:
            uid: Message UID.
            
        Returns:
            True if successful, raises IMAPError if archive folder not found.
        """
        archive_folder = self.get_special_folder('archive')
        if not archive_folder:
            raise IMAPError("Archive folder not found on server")

        return self.move_email(uid, archive_folder)

    def trash_email(self, uid: str) -> bool:
        """
        Move email to Trash folder.
        
        Args:
            uid: Message UID.
            
        Returns:
            True if successful, raises IMAPError if trash folder not found.
        """
        trash_folder = self.get_special_folder('trash')
        if not trash_folder:
            raise IMAPError("Trash folder not found on server")

        return self.move_email(uid, trash_folder)

    def delete_email(self, uid: str) -> bool:
        """
        Permanently delete email (mark deleted + expunge).
        
        Args:
            uid: Message UID.
            
        Returns:
            True if successful.
        """
        if not self.connection:
            raise IMAPError("Not connected")

        try:
            # Mark as deleted
            status, _ = self.connection.uid('STORE', uid, '+FLAGS', '(\\Deleted)')
            if status != 'OK':
                raise IMAPError(f"Failed to mark message {uid} as deleted")

            # Expunge to permanently remove
            self.connection.expunge()

            return True
        except Exception as e:
            raise IMAPError(f"Failed to delete message {uid}: {e}")
