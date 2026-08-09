"""
MailRepo - Encryption utilities.

  KDF:          Argon2id (m=256 MiB, t=6, p=1) -> 32-byte master key,
                then HKDF-Expand with domain-separated info strings
                into the file key and the SQLCipher DB key. Memory-hard,
                GPU/ASIC-resistant.
  File cipher:  AES-256-GCM with a 12-byte random nonce per file and
                the version byte bound into GCM AAD.
  File format:  [0x02][12-byte nonce][ciphertext][16-byte GCM tag]
  Salt file:    "MRC2"[32-byte salt][AES-256-GCM verification token]

The 0x02 version byte and "MRC2" magic are forward infrastructure: a
future v3 crypto migration can detect "this archive is on v2" and act
accordingly. They are NOT used to disambiguate from a legacy v1 format -
no such format exists in this codebase anymore. The v1 (PBKDF2 + Fernet)
era and its migration code were removed after every archive reached v2.
See docs/Session_Log.md for the May 29, 2026 migration; the migration
itself lives in git history as commits b7db944 / 39e0ce2 / 944b0aa /
3f0e67a if it ever needs to be referenced for pattern.

Key management & threat model:
  Keys are held as class-level attributes on Encryption for the
  lifetime of an unlocked session. This is deliberate, not an
  oversight. MailRepo is architecturally single-user and
  single-archive: there is exactly one master key per process, ever,
  so module-global state models a genuinely global fact. Instance-based
  injection would not change the security posture - the keys must live
  in process memory while the archive is unlocked regardless of which
  object holds the reference, and CPython offers no reliable
  mlock/zeroize for bytes objects (the interpreter copies immutable
  data freely). Memory-disclosure attacks against the running process
  (debugger attach, /proc/<pid>/mem, swap, core dumps) are outside the
  threat model, which defends data at rest. lock() drops all key
  references when the session ends.
"""

import base64
import os
import secrets
from typing import Optional

from argon2.low_level import Type as Argon2Type
from argon2.low_level import hash_secret_raw
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF, HKDFExpand

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

SALT_LENGTH = 32
VERIFICATION_TOKEN = b"MAILREPO_PASSWORD_OK"

# Argon2id parameters measured on the MacBook Air M4: ~750ms at t=6.
# Memory is the GPU-resistance knob; 256 MiB is invisible on machines with
# >=8 GB RAM and meaningfully raises offline cracking cost.
ARGON2_TIME_COST = 6  # iterations
ARGON2_MEMORY_COST = 262_144  # 256 MiB, in KiB
ARGON2_PARALLELISM = 1  # cleaner than p=2 for a latency-bound single derivation
ARGON2_KEY_LENGTH = 32

# HKDF-Expand info strings. The .v2 suffix means a future v3 KDF would
# derive cryptographically distinct keys even if the master collided.
HKDF_INFO_FILE_V2 = b"mailrepo.file.v2"
HKDF_INFO_DB_V2 = b"mailrepo.db.v2"

# Wire format
SALT_MAGIC_V2 = b"MRC2"
VERSION_BYTE_V2 = 0x02
GCM_NONCE_LENGTH = 12
GCM_TAG_LENGTH = 16

# ------------------------------------------------------------
# v3 envelope encryption
# ------------------------------------------------------------
#
# v2 derives the master key directly from the password. That makes the
# password the only way in: forget it and the archive is gone, and
# changing it means re-encrypting every file because every key below it
# moves.
#
# v3 makes the master key a random 32 bytes and wraps it twice -- once
# under a password-derived KEK, once under a recovery-key-derived KEK.
# Either wrapper yields the same master, so file_key and db_key are
# unchanged and NOTHING below the master needs to know v3 exists. The
# ciphertext format of archive files is still v2; only the key file
# changes.
#
# Second-order benefit: a password change becomes a rewrap of 61 bytes
# instead of a walk over the whole archive, which removes the
# non-resumable rekey window entirely for password changes.
#
# The recovery key is generated, never user-chosen: 160 bits of entropy
# means no password-strength guessing to defend against, so HKDF is
# sufficient and unlock-by-recovery-key is instant. Argon2id would buy
# nothing against a uniformly random 160-bit secret.

SALT_MAGIC_V3 = b"MRC3"
HKDF_INFO_RECOVERY_V3 = b"mailrepo.recovery.v3"

MASTER_KEY_LENGTH = 32
RECOVERY_KEY_BYTES = 20  # 160 bits -> exactly 32 base32 chars, no padding
RECOVERY_KEY_GROUP = 4

# [version 1][nonce 12][ciphertext 32][tag 16]
WRAPPED_KEY_LENGTH = 1 + GCM_NONCE_LENGTH + MASTER_KEY_LENGTH + GCM_TAG_LENGTH

# MRC3 layout, fixed length:
#   0   4    magic "MRC3"
#   4   32   salt_pw    (Argon2id salt)
#   36  61   wrapped_pw (master under the password KEK)
#   97  32   salt_rk    (HKDF salt)
#   129 61   wrapped_rk (master under the recovery-key KEK)
V3_OFF_SALT_PW = len(SALT_MAGIC_V3)
V3_OFF_WRAPPED_PW = V3_OFF_SALT_PW + SALT_LENGTH
V3_OFF_SALT_RK = V3_OFF_WRAPPED_PW + WRAPPED_KEY_LENGTH
V3_OFF_WRAPPED_RK = V3_OFF_SALT_RK + SALT_LENGTH
V3_SALT_FILE_LENGTH = V3_OFF_WRAPPED_RK + WRAPPED_KEY_LENGTH

# Base32 excludes 0/1/8, so these can only be typos for lookalikes.
_RECOVERY_KEY_FIXUPS = str.maketrans({"0": "O", "1": "I", "8": "B"})


# ============================================================
# MAIN CLASS
# ============================================================


class Encryption:
    """
    Master encryption manager.

    Class-level state so the rest of the app can call Encryption.encrypt()
    and Encryption.decrypt() without threading an instance through every
    call site.
    """

    _salt: Optional[bytes] = None
    _file_key_v2: Optional[bytes] = None
    _db_key_v2: Optional[str] = None

    # ----------------------------------------------------------
    # Initialization / unlock state
    # ----------------------------------------------------------

    @classmethod
    def is_initialized(cls) -> bool:
        """True if a salt file exists on disk."""
        return Config.get_salt_path().exists()

    @classmethod
    def is_unlocked(cls) -> bool:
        """True if keys are loaded in memory."""
        return cls._file_key_v2 is not None

    @classmethod
    def lock(cls) -> None:
        """Clear all in-memory keys."""
        cls._salt = None
        cls._file_key_v2 = None
        cls._db_key_v2 = None

    # ----------------------------------------------------------
    # Initialize / unlock
    # ----------------------------------------------------------

    @classmethod
    def initialize(cls, password: str) -> None:
        """
        Initialize encryption for a brand-new install.

        Generates a fresh salt, derives keys via Argon2id + HKDF, writes the
        salt file with the MRC2 magic and a verification token encrypted
        under the file key.
        """
        if cls.is_initialized():
            raise EncryptionError(
                "Encryption already initialized. Use the password-change flow instead."
            )

        salt = secrets.token_bytes(SALT_LENGTH)
        master = cls._derive_master_v2(password, salt)
        file_key = cls._derive_subkey_v2(master, HKDF_INFO_FILE_V2)
        db_key = cls._derive_subkey_v2(master, HKDF_INFO_DB_V2)

        verification = cls._encrypt_v2_with_key(VERIFICATION_TOKEN, file_key)

        Config.get_data_path().mkdir(parents=True, exist_ok=True)
        cls._atomic_write_salt_file(SALT_MAGIC_V2 + salt + verification)

        cls._salt = salt
        cls._file_key_v2 = file_key
        cls._db_key_v2 = db_key.hex()

    @classmethod
    def unlock(cls, password: str) -> bool:
        """Unlock with the master password. Raises InvalidPasswordError on mismatch."""
        if not cls.is_initialized():
            raise EncryptionError("Encryption not initialized. Call initialize() first.")

        with open(Config.get_salt_path(), "rb") as f:
            data = f.read()
        if data[:4] != SALT_MAGIC_V2:
            raise EncryptionError(
                "Salt file is missing the MRC2 magic. This archive may have been "
                "created by an incompatible version of MailRepo, or the salt file "
                "may be corrupt."
            )

        salt = data[4 : 4 + SALT_LENGTH]
        encrypted_verification = data[4 + SALT_LENGTH :]

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
        return True

    # ----------------------------------------------------------
    # DB key access
    # ----------------------------------------------------------

    @classmethod
    def get_db_key(cls) -> str:
        """Hex-encoded DB key for SQLCipher."""
        if cls._db_key_v2 is None:
            raise EncryptionError("Encryption is locked.")
        return cls._db_key_v2

    # ----------------------------------------------------------
    # Encrypt / decrypt
    # ----------------------------------------------------------

    @classmethod
    def encrypt(cls, data: bytes) -> bytes:
        """AES-256-GCM encrypt with a fresh random nonce per call."""
        if cls._file_key_v2 is None:
            raise EncryptionError("Encryption is locked.")
        return cls._encrypt_v2_with_key(data, cls._file_key_v2)

    @classmethod
    def decrypt(cls, data: bytes) -> bytes:
        """AES-256-GCM decrypt. Expects the 0x02 version byte prefix."""
        if cls._file_key_v2 is None:
            raise EncryptionError("Encryption is locked.")
        if len(data) < 1 or data[0] != VERSION_BYTE_V2:
            got = f"0x{data[0]:02x}" if len(data) > 0 else "empty"
            raise EncryptionError(f"Unexpected version byte: {got} (expected 0x02).")
        try:
            return cls._decrypt_v2_with_key(data, cls._file_key_v2)
        except Exception as e:
            raise EncryptionError(f"Decryption failed: {e}")

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
    # KDF primitives
    # ----------------------------------------------------------

    @classmethod
    def _derive_master_v2(cls, password: str, salt: bytes) -> bytes:
        """Argon2id derivation of the master key."""
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
        """HKDF-Expand: derive a domain-separated subkey from the master."""
        hkdf = HKDFExpand(algorithm=hashes.SHA256(), length=32, info=info)
        return hkdf.derive(master)

    @classmethod
    def _encrypt_v2_with_key(cls, data: bytes, key: bytes) -> bytes:
        """AES-256-GCM encrypt with a fresh random 96-bit nonce.

        Wire format: [version=0x02][12-byte nonce][ciphertext][16-byte GCM tag]

        The version byte is bound into GCM AAD so a tampered version byte
        breaks the auth check.
        """
        nonce = os.urandom(GCM_NONCE_LENGTH)
        aesgcm = AESGCM(key)
        version_byte = bytes([VERSION_BYTE_V2])
        ct_and_tag = aesgcm.encrypt(nonce, data, associated_data=version_byte)
        return version_byte + nonce + ct_and_tag

    @classmethod
    def _decrypt_v2_with_key(cls, data: bytes, key: bytes) -> bytes:
        """AES-256-GCM decrypt. Verifies the version byte via AAD."""
        if len(data) < 1 + GCM_NONCE_LENGTH + GCM_TAG_LENGTH:
            raise EncryptionError("Ciphertext too short for v2 format.")
        version_byte = data[0:1]
        if version_byte[0] != VERSION_BYTE_V2:
            raise EncryptionError(f"Unexpected v2 version byte: 0x{version_byte[0]:02x}")
        nonce = data[1 : 1 + GCM_NONCE_LENGTH]
        ct_and_tag = data[1 + GCM_NONCE_LENGTH :]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ct_and_tag, associated_data=version_byte)

    # ----------------------------------------------------------
    # Password change helpers (used by core/password_change.py)
    # ----------------------------------------------------------

    @classmethod
    def derive_v2_file_key_for_password(cls, password: str) -> bytes:
        """Derive a file_key from an arbitrary password using the current salt."""
        if cls._salt is None:
            raise EncryptionError("Encryption is not unlocked.")
        master = cls._derive_master_v2(password, cls._salt)
        return cls._derive_subkey_v2(master, HKDF_INFO_FILE_V2)

    @classmethod
    def derive_v2_db_key_for_password(cls, password: str) -> str:
        """Derive a db_key (hex) from an arbitrary password using the current salt."""
        if cls._salt is None:
            raise EncryptionError("Encryption is not unlocked.")
        master = cls._derive_master_v2(password, cls._salt)
        return cls._derive_subkey_v2(master, HKDF_INFO_DB_V2).hex()

    @classmethod
    def write_v2_salt_file(cls) -> None:
        """
        Rewrite the salt file with the current in-memory keys.

        Used by the password change flow after deriving new keys and
        rekeying SQLCipher: this writes a salt file whose verification
        token decrypts with the new file_key. Atomic write pattern (temp +
        fsync + os.replace + dir fsync) protects against torn writes on
        power loss.
        """
        if cls._salt is None or cls._file_key_v2 is None:
            raise EncryptionError("Keys not available; cannot write salt file.")
        encrypted_verification = cls._encrypt_v2_with_key(VERIFICATION_TOKEN, cls._file_key_v2)
        cls._atomic_write_salt_file(SALT_MAGIC_V2 + cls._salt + encrypted_verification)

    # ----------------------------------------------------------
    # v3 envelope: recovery key
    # ----------------------------------------------------------

    @classmethod
    def generate_recovery_key(cls) -> str:
        """Generate a fresh recovery key in display format.

        20 random bytes -> 32 base32 characters -> eight hyphenated groups
        of four. Base32 (RFC 4648) has no 0, 1 or 8, which removes the
        worst transcription ambiguities before they happen.
        """
        raw = secrets.token_bytes(RECOVERY_KEY_BYTES)
        return cls.format_recovery_key(raw)

    @staticmethod
    def format_recovery_key(raw: bytes) -> str:
        """Render recovery-key bytes as hyphenated base32 groups."""
        encoded = base64.b32encode(raw).decode("ascii").rstrip("=")
        return "-".join(
            encoded[i : i + RECOVERY_KEY_GROUP] for i in range(0, len(encoded), RECOVERY_KEY_GROUP)
        )

    @staticmethod
    def parse_recovery_key(text: str) -> bytes:
        """Parse a user-typed recovery key back to bytes.

        Tolerant of the things people actually do: lowercase, spaces
        instead of hyphens, missing hyphens, and 0/1/8 typed for O/I/B.
        Raises EncryptionError on anything that cannot be a recovery key,
        so a malformed key is distinguishable from a wrong one.
        """
        if not text:
            raise EncryptionError("No recovery key provided.")

        cleaned = (
            text.strip()
            .upper()
            .replace("-", "")
            .replace(" ", "")
            .replace("\t", "")
            .translate(_RECOVERY_KEY_FIXUPS)
        )

        expected_chars = len(base64.b32encode(b"\x00" * RECOVERY_KEY_BYTES).rstrip(b"="))
        if len(cleaned) != expected_chars:
            raise EncryptionError(
                f"Recovery key should be {expected_chars} characters "
                f"(excluding hyphens); got {len(cleaned)}."
            )

        padding = "=" * (-len(cleaned) % 8)
        try:
            raw = base64.b32decode(cleaned + padding, casefold=False)
        except Exception:
            raise EncryptionError(
                "Recovery key contains characters that are not part of the key "
                "alphabet (A-Z and 2-7)."
            )
        if len(raw) != RECOVERY_KEY_BYTES:
            raise EncryptionError("Recovery key is the wrong length.")
        return raw

    @classmethod
    def _derive_kek_from_recovery_key(cls, raw: bytes, salt_rk: bytes) -> bytes:
        """HKDF a key-encryption key from recovery-key bytes.

        Full HKDF (extract + expand) rather than expand-only: the salt
        makes two archives with the same recovery key derive different
        KEKs, which matters because recovery keys get printed, copied and
        occasionally reused by people who should not reuse them.
        """
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt_rk,
            info=HKDF_INFO_RECOVERY_V3,
        )
        return hkdf.derive(raw)

    # ----------------------------------------------------------
    # v3 envelope: salt file
    # ----------------------------------------------------------

    @classmethod
    def build_v3_salt_blob(cls, master: bytes, password: str, recovery_key: str) -> bytes:
        """Wrap the master key under both a password and a recovery key."""
        if len(master) != MASTER_KEY_LENGTH:
            raise EncryptionError(
                f"Master key must be {MASTER_KEY_LENGTH} bytes, got {len(master)}."
            )

        salt_pw = secrets.token_bytes(SALT_LENGTH)
        salt_rk = secrets.token_bytes(SALT_LENGTH)

        kek_pw = cls._derive_master_v2(password, salt_pw)
        kek_rk = cls._derive_kek_from_recovery_key(cls.parse_recovery_key(recovery_key), salt_rk)

        wrapped_pw = cls._encrypt_v2_with_key(master, kek_pw)
        wrapped_rk = cls._encrypt_v2_with_key(master, kek_rk)

        blob = SALT_MAGIC_V3 + salt_pw + wrapped_pw + salt_rk + wrapped_rk
        if len(blob) != V3_SALT_FILE_LENGTH:
            raise EncryptionError(
                f"Built a v3 salt blob of {len(blob)} bytes, expected {V3_SALT_FILE_LENGTH}."
            )
        return blob

    @staticmethod
    def parse_v3_salt_blob(blob: bytes) -> dict:
        """Split an MRC3 blob into its fields. Raises if malformed."""
        if blob[:4] != SALT_MAGIC_V3:
            raise EncryptionError("Not a v3 (MRC3) key file.")
        if len(blob) != V3_SALT_FILE_LENGTH:
            raise EncryptionError(
                f"v3 key file is {len(blob)} bytes, expected "
                f"{V3_SALT_FILE_LENGTH}. The file may be truncated."
            )
        return {
            "salt_pw": blob[V3_OFF_SALT_PW:V3_OFF_WRAPPED_PW],
            "wrapped_pw": blob[V3_OFF_WRAPPED_PW:V3_OFF_SALT_RK],
            "salt_rk": blob[V3_OFF_SALT_RK:V3_OFF_WRAPPED_RK],
            "wrapped_rk": blob[V3_OFF_WRAPPED_RK:],
        }

    @classmethod
    def unwrap_master_with_password(cls, blob: bytes, password: str) -> bytes:
        """Recover the master key from a v3 blob using the password.

        A wrong password fails the GCM auth tag, so the wrapper doubles as
        the verification token v2 needed a separate field for.
        """
        fields = cls.parse_v3_salt_blob(blob)
        kek = cls._derive_master_v2(password, fields["salt_pw"])
        try:
            return cls._decrypt_v2_with_key(fields["wrapped_pw"], kek)
        except Exception:
            raise InvalidPasswordError("Invalid master password.")

    @classmethod
    def unwrap_master_with_recovery_key(cls, blob: bytes, recovery_key: str) -> bytes:
        """Recover the master key from a v3 blob using the recovery key."""
        fields = cls.parse_v3_salt_blob(blob)
        raw = cls.parse_recovery_key(recovery_key)
        kek = cls._derive_kek_from_recovery_key(raw, fields["salt_rk"])
        try:
            return cls._decrypt_v2_with_key(fields["wrapped_rk"], kek)
        except Exception:
            raise InvalidPasswordError("That recovery key does not open this archive.")

    @classmethod
    def rewrap_password(cls, blob: bytes, master: bytes, new_password: str) -> bytes:
        """Replace the password wrapper, leaving the recovery wrapper alone.

        This is the whole point of the envelope: changing a password
        rewrites 61 bytes and revokes the old password, with no file walk
        and no database rekey. It works only because the master is random
        -- if the master were derived from the old password, that password
        would remain a permanent path to it no matter how often we rewrap.
        """
        fields = cls.parse_v3_salt_blob(blob)
        salt_pw = secrets.token_bytes(SALT_LENGTH)
        kek_pw = cls._derive_master_v2(new_password, salt_pw)
        wrapped_pw = cls._encrypt_v2_with_key(master, kek_pw)
        return SALT_MAGIC_V3 + salt_pw + wrapped_pw + fields["salt_rk"] + fields["wrapped_rk"]

    @classmethod
    def rewrap_recovery_key(cls, blob: bytes, master: bytes, new_recovery_key: str) -> bytes:
        """Replace the recovery wrapper, leaving the password wrapper alone.

        A printed recovery key is a second full-access credential. If it
        is lost, or was stored somewhere it should not have been, it has
        to be revocable without forcing a password change.
        """
        fields = cls.parse_v3_salt_blob(blob)
        salt_rk = secrets.token_bytes(SALT_LENGTH)
        kek_rk = cls._derive_kek_from_recovery_key(
            cls.parse_recovery_key(new_recovery_key), salt_rk
        )
        wrapped_rk = cls._encrypt_v2_with_key(master, kek_rk)
        return SALT_MAGIC_V3 + fields["salt_pw"] + fields["wrapped_pw"] + salt_rk + wrapped_rk

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

        Step 4 is the one usually missed: without it, the rename can vanish
        on power loss even though the data was synced.
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
# FLASK SECRET KEY (independent of master password)
# ============================================================


def generate_flask_secret_key() -> str:
    """
    Generate or load the Flask secret key.

    Independent of the user's master password. Lives in data/.secret_key
    with 0600 permissions.
    """
    secret_key_path = Config.get_secret_key_path()
    if secret_key_path.exists():
        return secret_key_path.read_text().strip()

    secret_key = secrets.token_hex(32)
    secret_key_path.parent.mkdir(parents=True, exist_ok=True)
    secret_key_path.write_text(secret_key)
    os.chmod(secret_key_path, 0o600)
    return secret_key
