"""
MailRepo - Core module.

Provides configuration, database, encryption, and IMAP utilities.
"""

from .config import Config, FlaskConfig
from .database import Database, delete_setting, get_setting, set_setting
from .encryption import Encryption, EncryptionError, InvalidPasswordError
from .imap import IMAP, IMAPError
from .importer import ImportError, import_eml_file, import_mbox_file, scan_mbox_file

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
    "import_eml_file",
    "import_mbox_file",
    "scan_mbox_file",
    "ImportError",
]
