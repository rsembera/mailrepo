"""
MailRepo - Configuration management.

Handles application paths, settings, and environment configuration.
"""

import os
from pathlib import Path
from typing import Optional


class Config:
    """Application configuration."""
    
    # Application info
    APP_NAME = "MailRepo"
    VERSION = "1.0.0"
    
    # Default paths (can be overridden via environment variables)
    _base_path: Optional[Path] = None
    
    @classmethod
    def get_base_path(cls) -> Path:
        """
        Get the base path for all MailRepo data.
        
        Defaults to the application directory, can be overridden with MAILREPO_DATA_DIR.
        """
        if cls._base_path is None:
            env_path = os.environ.get("MAILREPO_DATA_DIR")
            if env_path:
                cls._base_path = Path(env_path)
            else:
                # Default to application directory (where this file lives)
                cls._base_path = Path(__file__).parent.parent
        return cls._base_path
    
    @classmethod
    def set_base_path(cls, path: Path) -> None:
        """Set the base path (useful for testing)."""
        cls._base_path = path
    
    @classmethod
    def get_data_path(cls) -> Path:
        """Path to the data directory (contains database)."""
        return cls.get_base_path() / "data"
    
    @classmethod
    def get_database_path(cls) -> Path:
        """Path to the SQLite database file."""
        return cls.get_data_path() / "mailrepo.db"
    
    @classmethod
    def get_archive_path(cls) -> Path:
        """Path to the archive directory (contains archived emails)."""
        return cls.get_base_path() / "archive"
    
    @classmethod
    def get_config_path(cls) -> Path:
        """Path to the config directory (contains OAuth credentials)."""
        return cls.get_base_path() / "config"
    
    @classmethod
    def get_backup_path(cls) -> Path:
        """Path to the backups directory."""
        return cls.get_base_path() / "backups"
    
    @classmethod
    def get_salt_path(cls) -> Path:
        """Path to the encryption salt file."""
        return cls.get_data_path() / ".salt"
    
    @classmethod
    def get_secret_key_path(cls) -> Path:
        """Path to the Flask secret key file."""
        return cls.get_data_path() / ".secret_key"
    
    @classmethod
    def ensure_directories(cls) -> None:
        """Create all required directories if they don't exist."""
        directories = [
            cls.get_data_path(),
            cls.get_archive_path(),
            cls.get_config_path(),
            cls.get_backup_path(),
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def is_initialized(cls) -> bool:
        """Check if MailRepo has been initialized (database exists)."""
        return cls.get_database_path().exists()
    
    @classmethod
    def has_master_password(cls) -> bool:
        """Check if master password has been set (salt file exists)."""
        return cls.get_salt_path().exists()


# Flask configuration
class FlaskConfig:
    """Flask-specific configuration."""
    
    SECRET_KEY: Optional[str] = None  # Set at runtime from file
    SESSION_COOKIE_NAME = "mailrepo_session"
    SESSION_COOKIE_SECURE = False  # Set True in production with HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 86400  # 24 hours
    
    # Development settings
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    TESTING = False
