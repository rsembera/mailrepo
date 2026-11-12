"""
MailRepo - Core module.

Provides configuration, database, encryption, and IMAP utilities.
"""

from . import pst_temp
from .config import Config, FlaskConfig
from .database import Database, delete_setting, get_setting, set_setting
from .encryption import Encryption, EncryptionError, InvalidPasswordError
from .imap import IMAP, IMAPError
from .imap_pool import ImapPool

# Locking the archive drops the database key along with the file keys.
Encryption.on_lock(Database.forget_key)
# ...and removes PST conversions, which are mail in plain text and which
# only the page that has just gone away knew about.
Encryption.on_lock(pst_temp.remove_own)

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
