"""
MailRepo - Encryption utilities (Crypto Refactor 2026-05).

Supports two crypto versions side by side so a migration from v1 to v2 can
proceed incrementally without ever leaving the archive unreadable.

  v1 (legacy)
    KDF:           PBKDF2-HMAC-SHA256, 480,000 iterations, run twice
                   (once for file_key, once with a suffixed salt for db_key)
    File cipher:   Fernet (AES-128-CBC + HMAC-SHA256)
    Salt file:     [32-byte salt][Fernet-encrypted verification token]

  v2 (current, post-migration)
    KDF:           Argon2id (m=256MiB, t=6, p=1) -> 32-byte master key, then
                   HKDF-Expand with domain-separated info strings into
                   file_key and db_key. Memory-hard, GPU/ASIC-resistant.
    File cipher:   AES-256-GCM with a 12-byte random nonce per file and the
                   version byte bound into GCM AAD.
    File format:   [0x02][12-byte nonce][ciphertext][16-byte GCM tag]
    Salt file:     "MRC2"[32-byte salt][AES-256-GCM verification token]

The single-byte version prefix on every encrypted file means decrypt() can
auto-detect v1 (Fernet tokens start with 0x80) versus v2 (starts with 0x02),
so during migration files can be in mixed state and the runtime keeps working.

See docs/Crypto_Refactor_Plan.md for the full migration design.
"""

import os
import secrets
import base64
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from argon2.low_level import hash_secret_raw, Type as Argon2Type

from .config import Config


# ============================================================
# EXCEPTIONS
# ============================================================

class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""
    pass


class InvalidPasswordError(Exception):
    """Raised when the master password is incorrect."""
    pass


# ============================================================
# CONSTANTS
# ============================================================

# Shared
SALT_LENGTH = 32
VERIFICATION_TOKEN = b"MAILREPO_PASSWORD_OK"

# v1 (legacy, used to read existing archives during/before migration)
PBKDF2_ITERATIONS_V1 = 480_000
DB_SALT_SUFFIX_V1 = b"_MAILREPO_DB_KEY"

# v2 (current)
# Argon2id parameters measured on the MacBook Air M4: ~750ms at t=6.
# Memory is the GPU-resistance knob; 256MiB is invisible on machines
# with >=8GB RAM and meaningfully raises offline cracking cost.
ARGON2_TIME_COST = 6           # iterations
ARGON2_MEMORY_COST = 262_144   # 256 MiB, in KiB
ARGON2_PARALLELISM = 1         # cleaner than p=2 for latency-bound single derivation
ARGON2_KEY_LENGTH = 32

# HKDF-Expand info strings. The .v2 suffix means a future v3 KDF would derive
# cryptographically distinct keys even if the master key happens to collide.
HKDF_INFO_FILE_V2 = b"mailrepo.file.v2"
HKDF_INFO_DB_V2 = b"mailrepo.db.v2"

# v2 wire format
SALT_MAGIC_V2 = b"MRC2"
VERSION_BYTE_V2 = 0x02
GCM_NONCE_LENGTH = 12
GCM_TAG_LENGTH = 16


# ============================================================
# MAIN CLASS
# ============================================================

class Encryption:
    """
    Master encryption manager.

    State is held at class level so the rest of the app can call
    `Encryption.encrypt(...)` and `Encryption.decrypt(...)` without
    threading an instance through every call site.

    During migration BOTH v1 and v2 in-memory keys may be loaded at once
    so that v1-format archive files (no version byte) can still be read
    while new writes go out as v2.
    """

    # Shared
    _salt: Optional[bytes] = None

    # v1 state (legacy)
    _fernet_v1: Optional[Fernet] = None
    _db_key_v1: Optional[str] = None

    # v2 state (current)
    _file_key_v2: Optional[bytes] = None
    _db_key_v2: Optional[str] = None

    # ----------------------------------------------------------
    # Initialization / unlock state
    # ----------------------------------------------------------

    @classmethod
    def is_initialized(cls) -> bool:
        """True if a salt file exists on disk (encryption has been set up)."""
        return Config.get_salt_path().exists()

    @classmethod
    def is_unlocked(cls) -> bool:
        """True if either v1 or v2 keys are currently loaded in memory."""
        return cls._fernet_v1 is not None or cls._file_key_v2 is not None

    @classmethod
    def lock(cls) -> None:
        """Clear all in-memory keys."""
        cls._salt = None
        cls._fernet_v1 = None
        cls._db_key_v1 = None
        cls._file_key_v2 = None
        cls._db_key_v2 = None

    # ----------------------------------------------------------
    # Crypto-version detection
    # ----------------------------------------------------------

    @classmethod
    def get_crypto_version(cls) -> int:
        """
        Detect the on-disk crypto version by reading the salt file's first 4 bytes.

        Returns:
            2 if the salt file starts with the MRC2 magic.
            1 otherwise (legacy format, no magic).

        Raises:
            EncryptionError: If encryption is not yet initialized.
        """
        if not cls.is_initialized():
            raise EncryptionError("Encryption not initialized.")
        with open(Config.get_salt_path(), "rb") as f:
            head = f.read(4)
        return 2 if head == SALT_MAGIC_V2 else 1

    @classmethod
    def get_migration_marker_path(cls) -> Path:
        """Path to the Phase 1 completion marker file."""
        return Config.get_data_path() / ".migration_phase_1_complete"

    @classmethod
    def is_migration_in_progress(cls) -> bool:
        """
        True if the archive is in a Phase-1-complete-but-Phase-2-pending state.

        Detected by: salt file is still v1 (no MRC2 magic) AND the marker
        file exists. In this state, unlock() derives both v1 keys (for the
        still-v1 SQLCipher DB) and v2 keys (for the already-v2 archive files).
        """
        try:
            version = cls.get_crypto_version()
        except EncryptionError:
            return False
        if version == 2:
            return False
        return cls.get_migration_marker_path().exists()

    # ----------------------------------------------------------
    # Initialize (new install) — always creates v2
    # ----------------------------------------------------------

    @classmethod
    def initialize(cls, password: str) -> None:
        """
        Initialize encryption for a brand-new install. Always creates v2.

        Generates a fresh salt, derives v2 keys, writes the v2-format salt
        file with the MRC2 magic and a v2 verification token.

        Raises:
            EncryptionError: If encryption is already initialized.
        """
        if cls.is_initialized():
            raise EncryptionError(
                "Encryption already initialized. Use update_password() instead."
            )

        salt = secrets.token_bytes(SALT_LENGTH)
        master = cls._derive_master_v2(password, salt)
        file_key = cls._derive_subkey_v2(master, HKDF_INFO_FILE_V2)
        db_key = cls._derive_subkey_v2(master, HKDF_INFO_DB_V2)

        # Encrypt the verification token with the v2 file_key.
        verification = cls._encrypt_v2_with_key(VERIFICATION_TOKEN, file_key)

        # Atomic write of the v2 salt file.
        Config.get_data_path().mkdir(parents=True, exist_ok=True)
        cls._atomic_write_salt_file(SALT_MAGIC_V2 + salt + verification)

        cls._salt = salt
        cls._file_key_v2 = file_key
        cls._db_key_v2 = db_key.hex()

    # ----------------------------------------------------------
    # Unlock
    # ----------------------------------------------------------

    @classmethod
    def unlock(cls, password: str) -> bool:
        """
        Unlock with the master password. Routes to v1 or v2 based on salt file.

        - v2 salt → derive v2 keys only.
        - v1 salt, no migration marker → derive v1 keys only.
        - v1 salt, marker exists (mid-migration) → derive both v1 and v2 keys.

        Returns:
            True on success.

        Raises:
            EncryptionError: If encryption is not initialized.
            InvalidPasswordError: If the password is wrong.
        """
        if not cls.is_initialized():
            raise EncryptionError("Encryption not initialized. Call initialize() first.")

        version = cls.get_crypto_version()
        if version == 2:
            cls._unlock_v2(password)
        else:
            cls._unlock_v1(password)
            # Mid-migration: also derive v2 keys so v2 files can be read.
            if cls.is_migration_in_progress():
                cls._derive_and_set_v2_keys(password)
        return True

    @classmethod
    def _unlock_v1(cls, password: str) -> None:
        """Unlock a v1 archive (salt file: <salt><Fernet-encrypted token>)."""
        with open(Config.get_salt_path(), "rb") as f:
            data = f.read()
        salt = data[:SALT_LENGTH]
        encrypted_verification = data[SALT_LENGTH:]

        fernet = cls._derive_fernet_v1(password, salt)
        try:
            decrypted = fernet.decrypt(encrypted_verification)
        except InvalidToken:
            raise InvalidPasswordError("Invalid master password.")
        if decrypted != VERIFICATION_TOKEN:
            raise InvalidPasswordError("Invalid master password.")

        cls._salt = salt
        cls._fernet_v1 = fernet
        cls._db_key_v1 = cls._derive_db_key_v1(password, salt)

    @classmethod
    def _unlock_v2(cls, password: str) -> None:
        """Unlock a v2 archive (salt file: MRC2<salt><GCM-encrypted token>)."""
        with open(Config.get_salt_path(), "rb") as f:
            data = f.read()
        if data[:4] != SALT_MAGIC_V2:
            raise EncryptionError("Salt file is missing the MRC2 magic.")

        salt = data[4:4 + SALT_LENGTH]
        encrypted_verification = data[4 + SALT_LENGTH:]

        master = cls._derive_master_v2(password, salt)
        file_key = cls._derive_subkey_v2(master, HKDF_INFO_FILE_V2)
        db_key = cls._derive_subkey_v2(master, HKDF_INFO_DB_V2)

        try:
            decrypted = cls._decrypt_v2_with_key(encrypted_verification, file_key)
        except Exception:
            raise InvalidPasswordError("Invalid master password.")
        if decrypted != VERIFICATION_TOKEN:
            raise InvalidPasswordError("Invalid master password.")

        cls._salt = salt
        cls._file_key_v2 = file_key
        cls._db_key_v2 = db_key.hex()

    @classmethod
    def _derive_and_set_v2_keys(cls, password: str) -> None:
        """
        Derive v2 keys using the already-loaded salt.

        Called during mid-migration unlock when the salt file is still v1 but
        v2 files exist (marker is present). Requires _salt to be set, which
        _unlock_v1 will have done immediately before this is called.
        """
        if cls._salt is None:
            raise EncryptionError("Salt not loaded; cannot derive v2 keys.")
        master = cls._derive_master_v2(password, cls._salt)
        cls._file_key_v2 = cls._derive_subkey_v2(master, HKDF_INFO_FILE_V2)
        cls._db_key_v2 = cls._derive_subkey_v2(master, HKDF_INFO_DB_V2).hex()

    # ----------------------------------------------------------
    # DB key access (whichever version is current)
    # ----------------------------------------------------------

    @classmethod
    def get_db_key(cls) -> str:
        """
        Return the hex-encoded DB key for SQLCipher.

        - Pure v1 archive → returns v1 db_key.
        - Pure v2 archive → returns v2 db_key.
        - Mid-migration (Phase 1 done, Phase 2 not yet run) → returns v1 db_key,
          because the DB hasn't been rekeyed yet. The migration code calls
          get_db_key_v2() explicitly when it's ready to rekey.
        """
        if cls._db_key_v1 is not None:
            return cls._db_key_v1
        if cls._db_key_v2 is not None:
            return cls._db_key_v2
        raise EncryptionError("Encryption is locked.")

    @classmethod
    def get_db_key_v2(cls) -> str:
        """Return the v2 DB key. Used by the migration to rekey SQLCipher."""
        if cls._db_key_v2 is None:
            raise EncryptionError("v2 keys are not derived.")
        return cls._db_key_v2

    # ----------------------------------------------------------
    # Encrypt / decrypt (with auto-detection on decrypt)
    # ----------------------------------------------------------

    @classmethod
    def encrypt(cls, data: bytes) -> bytes:
        """
        Encrypt data.

        Prefers v2 (AES-256-GCM) if available. Falls back to v1 (Fernet) if
        only v1 keys are loaded — meaning a pre-migration archive. After Phase 1
        of the migration, v2 keys are loaded and all new writes are v2.
        """
        if cls._file_key_v2 is not None:
            return cls._encrypt_v2_with_key(data, cls._file_key_v2)
        if cls._fernet_v1 is not None:
            return cls._fernet_v1.encrypt(data)
        raise EncryptionError("Encryption is locked.")

    @classmethod
    def decrypt(cls, data: bytes) -> bytes:
        """
        Decrypt data, auto-detecting v1 vs v2 by the first byte.

        - 0x02 → v2 (AES-256-GCM); requires v2 file_key in memory.
        - anything else (Fernet tokens start with 0x80) → v1.

        Raises:
            EncryptionError: If the relevant key isn't loaded or decryption fails.
        """
        if not cls.is_unlocked():
            raise EncryptionError("Encryption is locked.")

        if len(data) > 0 and data[0] == VERSION_BYTE_V2:
            if cls._file_key_v2 is None:
                raise EncryptionError(
                    "v2-format ciphertext encountered but v2 key is not loaded."
                )
            try:
                return cls._decrypt_v2_with_key(data, cls._file_key_v2)
            except Exception as e:
                raise EncryptionError(f"v2 decryption failed: {e}")

        # v1 / Fernet path
        if cls._fernet_v1 is None:
            raise EncryptionError(
                "v1-format ciphertext encountered but v1 key is not loaded."
            )
        try:
            return cls._fernet_v1.decrypt(data)
        except InvalidToken as e:
            raise EncryptionError(f"v1 decryption failed: {e}")

    @classmethod
    def encrypt_string(cls, text: str) -> str:
        """Encrypt a UTF-8 string, return base64-url-safe encoded result."""
        encrypted = cls.encrypt(text.encode("utf-8"))
        return base64.urlsafe_b64encode(encrypted).decode("ascii")

    @classmethod
    def decrypt_string(cls, encrypted_text: str) -> str:
        """Decrypt a base64-url-safe encoded encrypted string back to UTF-8."""
        encrypted = base64.urlsafe_b64decode(encrypted_text.encode("ascii"))
        return cls.decrypt(encrypted).decode("utf-8")

    # ----------------------------------------------------------
    # v1 primitives (legacy)
    # ----------------------------------------------------------

    @classmethod
    def _derive_fernet_v1(cls, password: str, salt: bytes) -> Fernet:
        """PBKDF2 → 32-byte key → Fernet (AES-128-CBC + HMAC)."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=PBKDF2_ITERATIONS_V1,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
        return Fernet(key)

    @classmethod
    def _derive_db_key_v1(cls, password: str, salt: bytes) -> str:
        """PBKDF2 with suffixed salt → 32-byte key → hex for SQLCipher."""
        db_salt = salt + DB_SALT_SUFFIX_V1
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=db_salt,
            iterations=PBKDF2_ITERATIONS_V1,
        )
        return kdf.derive(password.encode("utf-8")).hex()

    # Backward-compat alias for callers from before the v1/v2 split.
    # Always routes to the v1 derivation. The post-migration password
    # change flow uses derive_v2_db_key_for_password() instead and never
    # calls this name.
    @classmethod
    def _derive_db_key(cls, password: str, salt: bytes) -> str:
        return cls._derive_db_key_v1(password, salt)

    # ----------------------------------------------------------
    # v2 primitives
    # ----------------------------------------------------------

    @classmethod
    def _derive_master_v2(cls, password: str, salt: bytes) -> bytes:
        """
        Argon2id derivation of the master key.

        At the configured parameters (m=256MiB, t=6, p=1) this takes ~750ms
        on the MacBook Air M4. Memory cost is what kills GPU/ASIC parallelism;
        time cost is the wall-clock knob.
        """
        return hash_secret_raw(
            secret=password.encode("utf-8"),
            salt=salt,
            time_cost=ARGON2_TIME_COST,
            memory_cost=ARGON2_MEMORY_COST,
            parallelism=ARGON2_PARALLELISM,
            hash_len=ARGON2_KEY_LENGTH,
            type=Argon2Type.ID,
        )

    @classmethod
    def _derive_subkey_v2(cls, master: bytes, info: bytes) -> bytes:
        """
        HKDF-Expand to derive a domain-separated subkey from the master.

        Argon2id output is already a uniform 32-byte key, so HKDF-Expand alone
        is the right primitive (HKDF-Extract is for concentrating entropy from
        non-uniform input, which we don't have here).
        """
        hkdf = HKDFExpand(algorithm=hashes.SHA256(), length=32, info=info)
        return hkdf.derive(master)

    @classmethod
    def _encrypt_v2_with_key(cls, data: bytes, key: bytes) -> bytes:
        """
        AES-256-GCM encrypt with a fresh random 96-bit nonce.

        Wire format: [version=0x02][12-byte nonce][ciphertext][16-byte GCM tag]

        The version byte is bound into GCM's AAD, so a tampered version byte
        causes the auth check to fail — cheap defense in depth against
        ciphertext-shape manipulation.
        """
        nonce = os.urandom(GCM_NONCE_LENGTH)
        aesgcm = AESGCM(key)
        version_byte = bytes([VERSION_BYTE_V2])
        # AESGCM.encrypt returns ciphertext || tag, concatenated.
        ct_and_tag = aesgcm.encrypt(nonce, data, associated_data=version_byte)
        return version_byte + nonce + ct_and_tag

    @classmethod
    def _decrypt_v2_with_key(cls, data: bytes, key: bytes) -> bytes:
        """AES-256-GCM decrypt. Verifies the version byte via AAD."""
        if len(data) < 1 + GCM_NONCE_LENGTH + GCM_TAG_LENGTH:
            raise EncryptionError("Ciphertext too short for v2 format.")
        version_byte = data[0:1]
        if version_byte[0] != VERSION_BYTE_V2:
            raise EncryptionError(
                f"Unexpected v2 version byte: 0x{version_byte[0]:02x}"
            )
        nonce = data[1:1 + GCM_NONCE_LENGTH]
        ct_and_tag = data[1 + GCM_NONCE_LENGTH:]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ct_and_tag, associated_data=version_byte)

    # ----------------------------------------------------------
    # Password change (operates on whichever version is current)
    # ----------------------------------------------------------

    @classmethod
    def derive_fernet_for_password(cls, password: str) -> Fernet:
        """
        Legacy helper: derive a Fernet from an arbitrary password using the
        currently-loaded salt. Used by the v1 password-change flow.

        Will not be useful for v2 archives once migration completes; v2 password
        change should use derive_v2_file_key_for_password() instead.
        """
        if cls._salt is None:
            raise EncryptionError("Encryption is not unlocked.")
        return cls._derive_fernet_v1(password, cls._salt)

    @classmethod
    def derive_v2_file_key_for_password(cls, password: str) -> bytes:
        """Derive a v2 file_key from an arbitrary password using the current salt."""
        if cls._salt is None:
            raise EncryptionError("Encryption is not unlocked.")
        master = cls._derive_master_v2(password, cls._salt)
        return cls._derive_subkey_v2(master, HKDF_INFO_FILE_V2)

    @classmethod
    def derive_v2_db_key_for_password(cls, password: str) -> str:
        """Derive a v2 db_key (hex) from an arbitrary password using the current salt."""
        if cls._salt is None:
            raise EncryptionError("Encryption is not unlocked.")
        master = cls._derive_master_v2(password, cls._salt)
        return cls._derive_subkey_v2(master, HKDF_INFO_DB_V2).hex()

    @classmethod
    def update_password(cls, new_password: str) -> None:
        """
        Update the master password.

        The caller is responsible for re-encrypting archive files with the new
        key BEFORE calling this — this method only rewrites the salt file's
        verification token and updates in-memory keys.

        Branches on the on-disk crypto version. The v1 branch keeps existing
        behavior for unmigrated archives. The v2 branch uses Argon2id + HKDF.
        """
        if cls._salt is None:
            raise EncryptionError("Encryption is not unlocked.")
        version = cls.get_crypto_version()
        if version == 2:
            cls._update_password_v2(new_password)
        else:
            cls._update_password_v1(new_password)

    @classmethod
    def _update_password_v1(cls, new_password: str) -> None:
        new_fernet = cls._derive_fernet_v1(new_password, cls._salt)
        new_db_key = cls._derive_db_key_v1(new_password, cls._salt)
        encrypted_verification = new_fernet.encrypt(VERIFICATION_TOKEN)
        cls._atomic_write_salt_file(cls._salt + encrypted_verification)
        cls._fernet_v1 = new_fernet
        cls._db_key_v1 = new_db_key

    @classmethod
    def _update_password_v2(cls, new_password: str) -> None:
        master = cls._derive_master_v2(new_password, cls._salt)
        new_file_key = cls._derive_subkey_v2(master, HKDF_INFO_FILE_V2)
        new_db_key = cls._derive_subkey_v2(master, HKDF_INFO_DB_V2).hex()
        encrypted_verification = cls._encrypt_v2_with_key(
            VERIFICATION_TOKEN, new_file_key
        )
        cls._atomic_write_salt_file(SALT_MAGIC_V2 + cls._salt + encrypted_verification)
        cls._file_key_v2 = new_file_key
        cls._db_key_v2 = new_db_key

    # ----------------------------------------------------------
    # Migration-specific operations (called by the migration endpoint)
    # ----------------------------------------------------------

    @classmethod
    def write_v2_salt_file(cls) -> None:
        """
        Phase 2 finalize step: write the new v2 salt file with MRC2 magic.

        Atomic via temp-file + fsync + replace + directory fsync. Requires
        _salt and _file_key_v2 to be set.
        """
        if cls._salt is None or cls._file_key_v2 is None:
            raise EncryptionError(
                "v2 keys not available; cannot write v2 salt file."
            )
        encrypted_verification = cls._encrypt_v2_with_key(
            VERIFICATION_TOKEN, cls._file_key_v2
        )
        cls._atomic_write_salt_file(
            SALT_MAGIC_V2 + cls._salt + encrypted_verification
        )

    @classmethod
    def swap_v1_to_v2(cls) -> None:
        """
        Phase 2 finalize step: clear v1 in-memory state.

        Called after the v2 salt file is written and SQLCipher has been rekeyed.
        The v2 keys remain loaded.
        """
        cls._fernet_v1 = None
        cls._db_key_v1 = None

    # ----------------------------------------------------------
    # Atomic file replacement
    # ----------------------------------------------------------

    @staticmethod
    def _atomic_write_salt_file(content: bytes) -> None:
        """
        Atomically replace the salt file. Crash-safe pattern:

          1. Write to a temp file in the same directory.
          2. fsync the temp file (durability of contents).
          3. os.replace (atomic on POSIX for same-filesystem rename).
          4. fsync the containing directory (durability of the rename itself).

        Step 4 is the one usually missed: without it, the rename can vanish on
        power loss even though the data was synced.
        """
        salt_path = Config.get_salt_path()
        tmp_path = salt_path.with_suffix(salt_path.suffix + ".v2tmp")
        with open(tmp_path, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, salt_path)
        dir_fd = os.open(str(salt_path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


# ============================================================
# FLASK SECRET KEY (unchanged from v1)
# ============================================================

def generate_flask_secret_key() -> str:
    """
    Generate or load the Flask secret key.

    This is independent of the user's master password and lives in
    data/.secret_key with 0600 permissions.
    """
    secret_key_path = Config.get_secret_key_path()
    if secret_key_path.exists():
        return secret_key_path.read_text().strip()

    secret_key = secrets.token_hex(32)
    secret_key_path.parent.mkdir(parents=True, exist_ok=True)
    secret_key_path.write_text(secret_key)
    os.chmod(secret_key_path, 0o600)
    return secret_key
