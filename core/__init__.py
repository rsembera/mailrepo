"""
MailRepo - Core module.

Provides configuration, database, encryption, and IMAP utilities.
"""

from .config import Config, FlaskConfig
from .database import Database, get_setting, set_setting, delete_setting
from .encryption import Encryption, EncryptionError, InvalidPasswordError, generate_flask_secret_key
from .imap import IMAP, IMAPError
from .importer import import_eml_file, import_mbox_file, scan_mbox_file, ImportError

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
    "generate_flask_secret_key",
    "IMAP",
    "IMAPError",
    "import_eml_file",
    "import_mbox_file",
    "scan_mbox_file",
    "ImportError",
]
