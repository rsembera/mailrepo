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

from .encryption import Encryption
from utils.log import get_logger

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
                    ssl_context=context
                )
            else:
                self.connection = imaplib.IMAP4(self.host, self.port)
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
            except:
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
            Dict with folder info (message count, uidvalidity, etc.).
        """
        if not self.connection:
            raise IMAPError("Not connected")
        
        try:
            status, data = self.connection.select(f'"{folder}"')
            if status != "OK":
                raise IMAPError(f"Failed to select folder: {folder}")
            
            # Get UIDVALIDITY using STATUS command (more reliable)
            uidvalidity = None
            try:
                status, status_data = self.connection.status(f'"{folder}"', '(UIDVALIDITY)')
                if status == 'OK' and status_data and status_data[0]:
                    # Parse response like: b'"INBOX" (UIDVALIDITY 12345)'
                    response = status_data[0].decode() if isinstance(status_data[0], bytes) else status_data[0]
                    match = re.search(r'UIDVALIDITY\s+(\d+)', response)
                    if match:
                        uidvalidity = int(match.group(1))
            except Exception as e:
                # Log but don't fail - caching just won't work
                log.debug(f"Could not get UIDVALIDITY: {e}")
            
            return {
                "folder": folder,
                "message_count": int(data[0]) if data else 0,
                "uidvalidity": uidvalidity,
            }
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
        
        # First pass: collect inline images (parts with Content-ID) for cid: replacement
        import base64
        inline_images = {}  # cid -> data URL
        
        if msg.is_multipart():
            for part in msg.walk():
                content_id = part.get("Content-ID")
                if content_id:
                    payload = part.get_payload(decode=True)
                    if payload:
                        content_type = part.get_content_type()
                        # Strip angle brackets: <image001.png@...> -> image001.png@...
                        cid = content_id.strip('<>')
                        b64_data = base64.b64encode(payload).decode('ascii')
                        inline_images[cid] = f"data:{content_type};base64,{b64_data}"
        
        # Second pass: parse body and collect attachments
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                content_id = part.get("Content-ID")
                
                # Skip inline images - they're handled via cid: replacement
                # Only skip if it's an image with Content-ID (actual inline embedded image)
                if content_id and content_type.startswith("image/"):
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
                
                if content_type == "text/plain" and not result["text_body"]:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        result["text_body"] = payload.decode(charset, errors="replace")
                
                elif content_type == "text/html" and not result["html_body"]:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        result["html_body"] = payload.decode(charset, errors="replace")
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
            import re
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
        except:
            return header
    
    def _linkify_html(self, html: str) -> str:
        """
        Convert plain text URLs and email addresses in HTML to clickable links.
        Skips content that's already inside anchor tags or other HTML attributes.
        """
        import re
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
            # URL pattern: only match valid URL characters
            part = re.sub(
                r'\b(https?://[a-zA-Z0-9\-._~:/?#\[\]@!$&\'()*+,;=%]+)',
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
        Find special folder name (Archive, Trash) for this IMAP server.
        
        Args:
            folder_type: 'archive' or 'trash'
            
        Returns:
            Folder name or None if not found.
        """
        if not self.connection:
            raise IMAPError("Not connected")
        
        # Common folder names by type
        archive_names = ['Archive', '[Gmail]/All Mail', 'Archives', 'INBOX.Archive']
        trash_names = ['Trash', '[Gmail]/Trash', 'Deleted Items', 'Deleted Messages', 'INBOX.Trash']
        
        search_names = archive_names if folder_type == 'archive' else trash_names
        
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
