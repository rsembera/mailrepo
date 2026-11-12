"""
MailRepo - Core module.

Provides configuration, database, encryption, and IMAP utilities.
"""

from .config import Config, FlaskConfig
from .database import Database, delete_setting, get_setting, set_setting
from .encryption import Encryption, EncryptionError, InvalidPasswordError
from .imap import IMAP, IMAPError
from .imap_pool import ImapPool

# Locking the archive drops the database key along with the file keys.
Encryption.on_lock(Database.forget_key)

__all__ = [
    "Config",
    "FlaskConfig",
    "Database",
    "get_setting",
    "set_setting",
    "delete_setting",
    "Encryption",
    "EncryptionError",
    "InvalidPasswordError",
    "IMAP",
    "IMAPError",
    "ImapPool",
]
