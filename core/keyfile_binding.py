"""
Rollback detection for the key file (security review 2026-09, #8).

MRC4 binds the two wrapper halves to each other with a keyed tag (see
core/encryption.py). This module closes the other gap the review named:
an *entire* older key file — say last month's ``.salt`` from a backup,
opened with last month's password — is self-consistent and passes the
binding check on its own. The encrypted settings table therefore
records the tag of the key file that currently belongs to this archive
(plus the one before it, so a crash between a rewrap's two writes can
never lock the owner out), and login refuses a key file whose tag is
not one of those.

What this does and does not do, plainly: it stops a revoked password
from *quietly* opening the live archive via a rolled-back key file, and
it makes a splice detectable. It cannot stop someone who holds an old
key file, an old password and a copy of the ciphertext from reading
that copy offline. Only rotating the master key (re-encrypting every
file and rekeying the database) does that; see rotate_master_key().
"""

import json

from core.database import Database, get_setting, set_setting
from core.encryption import Encryption, EncryptionError
from utils.log import get_logger

log = get_logger(__name__)

SETTING_KEY = "key_file_tags"


class KeyFileRollbackError(EncryptionError):
    """The key file on disk is not the one this archive last recorded."""


def _recorded_tags() -> list[str]:
    raw = get_setting(SETTING_KEY, "")
    if not raw:
        return []
    try:
        tags = json.loads(raw)
        return [t for t in tags if isinstance(t, str)]
    except (ValueError, TypeError):
        return []


def record_current_tag(blob: bytes | None = None, *, sole: bool = False) -> None:
    """Record the on-disk key file's tag as current. Requires an open database.

    The previous tag is kept as a crash-window fallback — except with
    ``sole=True`` (master rotation), where the previous key file wraps a
    master that opens nothing and must not be accepted at all.
    """
    tag = Encryption.key_file_tag_hex(blob)
    if tag is None:
        return
    tags = _recorded_tags()
    if sole:
        new_tags = [tag]
    else:
        if tags and tags[0] == tag:
            return
        new_tags = [tag] + [t for t in tags if t != tag][:1]
    set_setting(SETTING_KEY, json.dumps(new_tags))


def record_tag_with_master(master: bytes, blob: bytes) -> None:
    """Record a tag when no session is open (the recovery-key reset path).

    Opens the database with a key derived from ``master`` just long
    enough to write the setting, then closes it again.
    """
    from core.encryption import HKDF_INFO_DB_V2

    opened_here = False
    try:
        if Database._connection is None:  # noqa: SLF001 - deliberate peek
            Database.set_key(Encryption._derive_subkey_v2(master, HKDF_INFO_DB_V2).hex())
            Database.initialize()
            opened_here = True
        record_current_tag(blob)
    finally:
        if opened_here:
            Database.close()


def check_after_unlock() -> None:
    """Run right after unlock + database open, on every login.

    * MRC3 on disk → upgrade in place to MRC4 (no re-encryption, no
      recovery key needed) and record the new tag.
    * MRC4 on disk → its tag must be the recorded current or previous
      one. Nothing recorded yet (first login after upgrade, or an
      archive created before this check existed) → record it now.
    """
    if Encryption._master is None:  # noqa: SLF001
        raise EncryptionError("check_after_unlock called while locked")

    blob = Encryption.read_salt_blob()
    if blob[:4] not in (b"MRC3", b"MRC4"):
        return  # MRC2: the v3 migration comes first

    if blob[:4] == b"MRC3":
        upgraded = Encryption.upgrade_blob_to_v4(blob, Encryption._master)  # noqa: SLF001
        Encryption.write_v3_salt_file(upgraded)
        record_current_tag(upgraded)
        log.info("Key file upgraded MRC3 → MRC4 (bound envelope)")
        return

    tag = Encryption.key_file_tag_hex(blob)
    recorded = _recorded_tags()
    if not recorded:
        record_current_tag(blob)
        return
    if tag in recorded:
        if tag != recorded[0]:
            # The previous tag: a rewrap's file write landed but its
            # database write did not. Promote it and move on.
            record_current_tag(blob)
        return

    raise KeyFileRollbackError(
        "This key file is not the one this archive last used. Someone has "
        "replaced data/.salt with an older copy — possibly to reuse a "
        "password or recovery key that was since changed. If you did this "
        "yourself by restoring only the key file, restore the whole backup "
        "instead. Otherwise treat the archive as exposed: restore data/.salt "
        "from a trusted backup, change your password, rotate the recovery key, "
        "and consider rotating the master key from Settings."
    )
