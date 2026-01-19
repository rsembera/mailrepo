"""
MailRepo - Core module.

Provides configuration, database, encryption, and Gmail utilities.
"""

from .config import Config, FlaskConfig
from .database import Database, get_setting, set_setting, delete_setting
from .encryption import Encryption, EncryptionError, InvalidPasswordError, generate_flask_secret_key
from .gmail import Gmail, GmailError

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
    "Gmail",
    "GmailError",
]
