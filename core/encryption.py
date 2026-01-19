"""
MailRepo - Encryption utilities.

Handles master password verification, key derivation, and Fernet encryption
for both archived emails and OAuth credentials.
"""

import os
import secrets
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

from .config import Config


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""
    pass


class InvalidPasswordError(Exception):
    """Raised when the master password is incorrect."""
    pass


class Encryption:
    """
    Handles all encryption operations for MailRepo.
    
    Uses Fernet (AES-128-CBC) with PBKDF2 key derivation.
    The master password is never stored; only a verification hash.
    """
    
    # PBKDF2 iterations (higher = more secure but slower)
    PBKDF2_ITERATIONS = 480000
    
    # Salt length in bytes
    SALT_LENGTH = 32
    
    # Verification token stored to check password correctness
    VERIFICATION_TOKEN = b"MAILREPO_PASSWORD_OK"
    
    _fernet: Optional[Fernet] = None
    _salt: Optional[bytes] = None
    
    @classmethod
    def is_initialized(cls) -> bool:
        """Check if encryption has been set up (salt exists)."""
        return Config.get_salt_path().exists()
    
    @classmethod
    def initialize(cls, password: str) -> None:
        """
        Initialize encryption with a new master password.
        
        Creates salt file and stores encrypted verification token.
        Raises EncryptionError if already initialized.
        
        Args:
            password: The master password to set.
        """
        if cls.is_initialized():
            raise EncryptionError("Encryption already initialized. Use change_password() instead.")
        
        # Generate random salt
        salt = secrets.token_bytes(cls.SALT_LENGTH)
        
        # Derive key and create Fernet instance
        fernet = cls._derive_fernet(password, salt)
        
        # Encrypt verification token
        encrypted_verification = fernet.encrypt(cls.VERIFICATION_TOKEN)
        
        # Save salt + encrypted verification token
        Config.get_data_path().mkdir(parents=True, exist_ok=True)
        with open(Config.get_salt_path(), "wb") as f:
            f.write(salt + encrypted_verification)
        
        # Store in memory for this session
        cls._salt = salt
        cls._fernet = fernet
    
    @classmethod
    def unlock(cls, password: str) -> bool:
        """
        Unlock encryption with the master password.
        
        Verifies the password against stored verification token.
        
        Args:
            password: The master password to verify.
            
        Returns:
            True if password is correct.
            
        Raises:
            InvalidPasswordError: If password is incorrect.
            EncryptionError: If encryption not initialized.
        """
        if not cls.is_initialized():
            raise EncryptionError("Encryption not initialized. Call initialize() first.")
        
        # Read salt and encrypted verification
        with open(Config.get_salt_path(), "rb") as f:
            data = f.read()
        
        salt = data[:cls.SALT_LENGTH]
        encrypted_verification = data[cls.SALT_LENGTH:]
        
        # Derive key and try to decrypt verification token
        fernet = cls._derive_fernet(password, salt)
        
        try:
            decrypted = fernet.decrypt(encrypted_verification)
            if decrypted != cls.VERIFICATION_TOKEN:
                raise InvalidPasswordError("Invalid master password.")
        except InvalidToken:
            raise InvalidPasswordError("Invalid master password.")
        
        # Store in memory for this session
        cls._salt = salt
        cls._fernet = fernet
        return True
    
    @classmethod
    def is_unlocked(cls) -> bool:
        """Check if encryption is unlocked for this session."""
        return cls._fernet is not None
    
    @classmethod
    def lock(cls) -> None:
        """Lock encryption (clear keys from memory)."""
        cls._fernet = None
        cls._salt = None
    
    @classmethod
    def encrypt(cls, data: bytes) -> bytes:
        """
        Encrypt data using the master password key.
        
        Args:
            data: Plaintext bytes to encrypt.
            
        Returns:
            Encrypted bytes (Fernet token).
            
        Raises:
            EncryptionError: If encryption is locked.
        """
        if not cls.is_unlocked():
            raise EncryptionError("Encryption is locked. Call unlock() first.")
        return cls._fernet.encrypt(data)
    
    @classmethod
    def decrypt(cls, data: bytes) -> bytes:
        """
        Decrypt data using the master password key.
        
        Args:
            data: Encrypted bytes (Fernet token).
            
        Returns:
            Decrypted plaintext bytes.
            
        Raises:
            EncryptionError: If encryption is locked or decryption fails.
        """
        if not cls.is_unlocked():
            raise EncryptionError("Encryption is locked. Call unlock() first.")
        try:
            return cls._fernet.decrypt(data)
        except InvalidToken as e:
            raise EncryptionError(f"Decryption failed: {e}")
    
    @classmethod
    def encrypt_string(cls, text: str) -> str:
        """Encrypt a string, returning base64-encoded result."""
        encrypted = cls.encrypt(text.encode("utf-8"))
        return base64.urlsafe_b64encode(encrypted).decode("ascii")
    
    @classmethod
    def decrypt_string(cls, encrypted_text: str) -> str:
        """Decrypt a base64-encoded encrypted string."""
        encrypted = base64.urlsafe_b64decode(encrypted_text.encode("ascii"))
        return cls.decrypt(encrypted).decode("utf-8")
    
    @classmethod
    def _derive_fernet(cls, password: str, salt: bytes) -> Fernet:
        """
        Derive a Fernet key from password and salt using PBKDF2.
        
        Args:
            password: The master password.
            salt: Random salt bytes.
            
        Returns:
            Fernet instance with derived key.
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=cls.PBKDF2_ITERATIONS,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
        return Fernet(key)


def generate_flask_secret_key() -> str:
    """
    Generate or load the Flask secret key.
    
    Creates a new random key if one doesn't exist.
    """
    secret_key_path = Config.get_secret_key_path()
    
    if secret_key_path.exists():
        return secret_key_path.read_text().strip()
    
    # Generate new secret key
    secret_key = secrets.token_hex(32)
    
    # Ensure directory exists
    secret_key_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Save with restrictive permissions
    secret_key_path.write_text(secret_key)
    os.chmod(secret_key_path, 0o600)
    
    return secret_key
