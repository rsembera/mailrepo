"""
Tests for core/encryption.py - Master password and encryption handling.
"""

import pytest


class TestEncryptionInitialization:
    """Tests for initial password setup."""
    
    def test_not_initialized_on_fresh_start(self):
        """Encryption should not be initialized with no salt file."""
        from core.encryption import Encryption
        
        assert not Encryption.is_initialized()
    
    def test_initialize_creates_salt_file(self):
        """Initializing encryption should create the salt file."""
        from core.encryption import Encryption
        from core.config import Config
        
        Encryption.initialize("SecurePassword123!")
        
        assert Config.get_salt_path().exists()
        assert Encryption.is_initialized()
        assert Encryption.is_unlocked()
    
    def test_initialize_rejects_if_already_initialized(self):
        """Cannot initialize twice."""
        from core.encryption import Encryption, EncryptionError
        
        Encryption.initialize("SecurePassword123!")
        
        with pytest.raises(EncryptionError, match="already initialized"):
            Encryption.initialize("AnotherPassword123!")


class TestEncryptionUnlock:
    """Tests for password verification and unlocking."""
    
    def test_unlock_with_correct_password(self):
        """Correct password should unlock encryption."""
        from core.encryption import Encryption
        
        password = "SecurePassword123!"
        Encryption.initialize(password)
        Encryption.lock()
        
        assert not Encryption.is_unlocked()
        assert Encryption.unlock(password)
        assert Encryption.is_unlocked()
    
    def test_unlock_with_wrong_password(self):
        """Wrong password should raise InvalidPasswordError."""
        from core.encryption import Encryption, InvalidPasswordError
        
        Encryption.initialize("SecurePassword123!")
        Encryption.lock()
        
        with pytest.raises(InvalidPasswordError):
            Encryption.unlock("WrongPassword456!")
    
    def test_unlock_not_initialized(self):
        """Unlocking without initialization should raise EncryptionError."""
        from core.encryption import Encryption, EncryptionError
        
        with pytest.raises(EncryptionError, match="not initialized"):
            Encryption.unlock("SomePassword123!")


class TestEncryptDecrypt:
    """Tests for data encryption and decryption."""
    
    def test_encrypt_decrypt_bytes(self):
        """Encrypting and decrypting bytes should return original data."""
        from core.encryption import Encryption
        
        Encryption.initialize("SecurePassword123!")
        
        original = b"This is sensitive email content."
        encrypted = Encryption.encrypt(original)
        decrypted = Encryption.decrypt(encrypted)
        
        assert encrypted != original
        assert decrypted == original
    
    def test_encrypt_decrypt_string(self):
        """Encrypting and decrypting strings should work."""
        from core.encryption import Encryption
        
        Encryption.initialize("SecurePassword123!")
        
        original = '{"email": "test@example.com", "password": "secret"}'
        encrypted = Encryption.encrypt_string(original)
        decrypted = Encryption.decrypt_string(encrypted)
        
        assert encrypted != original
        assert decrypted == original
    
    def test_encrypt_while_locked_fails(self):
        """Encrypting while locked should raise EncryptionError."""
        from core.encryption import Encryption, EncryptionError
        
        Encryption.initialize("SecurePassword123!")
        Encryption.lock()
        
        with pytest.raises(EncryptionError, match="locked"):
            Encryption.encrypt(b"data")


class TestDatabaseKey:
    """Tests for SQLCipher key derivation."""
    
    def test_db_key_is_hex_string(self):
        """Database key should be a hex string."""
        from core.encryption import Encryption
        
        Encryption.initialize("SecurePassword123!")
        
        db_key = Encryption.get_db_key()
        
        assert isinstance(db_key, str)
        assert len(db_key) == 64  # 32 bytes = 64 hex chars
        assert all(c in "0123456789abcdef" for c in db_key)
    
    def test_db_key_differs_from_encryption(self):
        """Database key should be derivable and consistent."""
        from core.encryption import Encryption
        
        Encryption.initialize("SecurePassword123!")
        
        db_key1 = Encryption.get_db_key()
        
        # Lock and unlock - should get same key
        Encryption.lock()
        Encryption.unlock("SecurePassword123!")
        
        db_key2 = Encryption.get_db_key()
        
        assert db_key1 == db_key2
