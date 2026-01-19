"""
MailRepo - Gmail API integration.

Handles OAuth authentication and email fetching from Gmail accounts.
"""

import base64
import json
from email import message_from_bytes
from pathlib import Path
from typing import Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import Config
from .encryption import Encryption


# Gmail API scopes
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",    # Read emails
    "https://www.googleapis.com/auth/gmail.modify",      # Archive, trash, mark read
    "https://www.googleapis.com/auth/gmail.labels",      # Manage labels
]


class GmailError(Exception):
    """Raised when Gmail API operations fail."""
    pass


class Gmail:
    """
    Gmail API client for MailRepo.
    
    Handles OAuth flow, token management, and email operations.
    """
    
    @classmethod
    def get_credentials_path(cls) -> Path:
        """Path to OAuth client credentials (downloaded from Google Cloud Console)."""
        return Config.get_config_path() / "credentials.json"
    
    @classmethod
    def has_client_credentials(cls) -> bool:
        """Check if OAuth client credentials file exists."""
        return cls.get_credentials_path().exists()
    
    @classmethod
    def authorize(cls, account_id: int) -> Credentials:
        """
        Run OAuth flow to authorize a Gmail account.
        
        Opens browser for user to sign in and grant permissions.
        Stores encrypted refresh token in database.
        
        Args:
            account_id: Database ID for the account record.
            
        Returns:
            Authorized Credentials object.
            
        Raises:
            GmailError: If credentials.json not found or auth fails.
        """
        if not cls.has_client_credentials():
            raise GmailError(
                "credentials.json not found. Download it from Google Cloud Console "
                "and place it in ~/mailrepo/config/"
            )
        
        flow = InstalledAppFlow.from_client_secrets_file(
            str(cls.get_credentials_path()),
            SCOPES,
        )
        
        # Run local server for OAuth callback
        credentials = flow.run_local_server(port=8089)
        
        # Store encrypted token
        cls._save_credentials(account_id, credentials)
        
        return credentials
    
    @classmethod
    def get_credentials(cls, account_id: int, encrypted_creds: str) -> Optional[Credentials]:
        """
        Load and refresh credentials for an account.
        
        Args:
            account_id: Database ID for the account.
            encrypted_creds: Encrypted credentials JSON from database.
            
        Returns:
            Valid Credentials object, or None if refresh fails.
        """
        if not encrypted_creds:
            return None
        
        try:
            # Decrypt credentials
            creds_json = Encryption.decrypt_string(encrypted_creds)
            creds_data = json.loads(creds_json)
            
            credentials = Credentials(
                token=creds_data.get("token"),
                refresh_token=creds_data.get("refresh_token"),
                token_uri=creds_data.get("token_uri"),
                client_id=creds_data.get("client_id"),
                client_secret=creds_data.get("client_secret"),
                scopes=creds_data.get("scopes"),
            )
            
            # Refresh if expired
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                cls._save_credentials(account_id, credentials)
            
            return credentials
            
        except Exception as e:
            print(f"Error loading credentials: {e}")
            return None
    
    @classmethod
    def _save_credentials(cls, account_id: int, credentials: Credentials) -> None:
        """Save encrypted credentials to database."""
        from .database import Database
        
        creds_data = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes,
        }
        
        encrypted = Encryption.encrypt_string(json.dumps(creds_data))
        
        Database.execute(
            "UPDATE accounts SET credentials_encrypted = ? WHERE id = ?",
            (encrypted, account_id)
        )
        Database.commit()
    
    @classmethod
    def get_service(cls, credentials: Credentials):
        """Build Gmail API service object."""
        return build("gmail", "v1", credentials=credentials)
    
    @classmethod
    def get_profile(cls, service) -> dict:
        """Get Gmail profile (email address, etc.)."""
        try:
            profile = service.users().getProfile(userId="me").execute()
            return {
                "email": profile.get("emailAddress"),
                "messages_total": profile.get("messagesTotal"),
                "threads_total": profile.get("threadsTotal"),
            }
        except HttpError as e:
            raise GmailError(f"Failed to get profile: {e}")
    
    @classmethod
    def list_labels(cls, service) -> list[dict]:
        """Get all Gmail labels (folders)."""
        try:
            results = service.users().labels().list(userId="me").execute()
            labels = results.get("labels", [])
            return [{"id": l["id"], "name": l["name"]} for l in labels]
        except HttpError as e:
            raise GmailError(f"Failed to list labels: {e}")
    
    @classmethod
    def list_messages(
        cls,
        service,
        label_ids: list[str] = None,
        query: str = None,
        max_results: int = 50,
        page_token: str = None,
    ) -> dict:
        """
        List messages from Gmail.
        
        Args:
            service: Gmail API service object.
            label_ids: Filter by label IDs (e.g., ["INBOX"]).
            query: Gmail search query (e.g., "from:alice@example.com").
            max_results: Maximum messages to return (default 50).
            page_token: Pagination token for next page.
            
        Returns:
            Dict with "messages" list and optional "nextPageToken".
        """
        try:
            kwargs = {
                "userId": "me",
                "maxResults": max_results,
            }
            if label_ids:
                kwargs["labelIds"] = label_ids
            if query:
                kwargs["q"] = query
            if page_token:
                kwargs["pageToken"] = page_token
            
            results = service.users().messages().list(**kwargs).execute()
            
            messages = results.get("messages", [])
            
            return {
                "messages": messages,  # Just IDs at this point
                "nextPageToken": results.get("nextPageToken"),
                "resultSizeEstimate": results.get("resultSizeEstimate"),
            }
        except HttpError as e:
            raise GmailError(f"Failed to list messages: {e}")
    
    @classmethod
    def get_message(cls, service, message_id: str, format: str = "metadata") -> dict:
        """
        Get a single message.
        
        Args:
            service: Gmail API service object.
            message_id: Gmail message ID.
            format: "minimal", "metadata", "full", or "raw".
            
        Returns:
            Message data dict.
        """
        try:
            message = service.users().messages().get(
                userId="me",
                id=message_id,
                format=format,
            ).execute()
            
            return cls._parse_message(message, format)
        except HttpError as e:
            raise GmailError(f"Failed to get message {message_id}: {e}")
    
    @classmethod
    def get_message_raw(cls, service, message_id: str) -> bytes:
        """
        Get raw RFC 2822 message (for saving as .eml).
        
        Args:
            service: Gmail API service object.
            message_id: Gmail message ID.
            
        Returns:
            Raw email bytes.
        """
        try:
            message = service.users().messages().get(
                userId="me",
                id=message_id,
                format="raw",
            ).execute()
            
            raw = message.get("raw", "")
            return base64.urlsafe_b64decode(raw)
        except HttpError as e:
            raise GmailError(f"Failed to get raw message {message_id}: {e}")
    
    @classmethod
    def _parse_message(cls, message: dict, format: str) -> dict:
        """Parse Gmail API message response into clean dict."""
        result = {
            "id": message.get("id"),
            "threadId": message.get("threadId"),
            "labelIds": message.get("labelIds", []),
            "snippet": message.get("snippet"),
            "internalDate": message.get("internalDate"),  # Unix timestamp ms
        }
        
        # Parse headers if available
        payload = message.get("payload", {})
        headers = payload.get("headers", [])
        
        header_map = {h["name"].lower(): h["value"] for h in headers}
        
        result["subject"] = header_map.get("subject", "(no subject)")
        result["from"] = header_map.get("from", "")
        result["to"] = header_map.get("to", "")
        result["date"] = header_map.get("date", "")
        result["messageId"] = header_map.get("message-id", "")
        
        return result
    
    @classmethod
    def archive_message(cls, service, message_id: str) -> None:
        """Archive a message (remove INBOX label)."""
        try:
            service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["INBOX"]},
            ).execute()
        except HttpError as e:
            raise GmailError(f"Failed to archive message {message_id}: {e}")
    
    @classmethod
    def trash_message(cls, service, message_id: str) -> None:
        """Move a message to trash."""
        try:
            service.users().messages().trash(userId="me", id=message_id).execute()
        except HttpError as e:
            raise GmailError(f"Failed to trash message {message_id}: {e}")
    
    @classmethod
    def delete_message(cls, service, message_id: str) -> None:
        """Permanently delete a message (use with caution!)."""
        try:
            service.users().messages().delete(userId="me", id=message_id).execute()
        except HttpError as e:
            raise GmailError(f"Failed to delete message {message_id}: {e}")
    
    @classmethod
    def move_message(cls, service, message_id: str, add_labels: list[str], remove_labels: list[str] = None) -> None:
        """Move message by adding/removing labels."""
        try:
            body = {"addLabelIds": add_labels}
            if remove_labels:
                body["removeLabelIds"] = remove_labels
            
            service.users().messages().modify(
                userId="me",
                id=message_id,
                body=body,
            ).execute()
        except HttpError as e:
            raise GmailError(f"Failed to move message {message_id}: {e}")
