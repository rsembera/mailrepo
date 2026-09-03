"""
MailRepo - Authentication blueprint.

Handles master password setup, login, logout, and password change.
"""

import json
import secrets
import threading
import time
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from core import Database, Encryption, EncryptionError, InvalidPasswordError
from core.config import Config
from core.crypto_migration_v3 import migrate_to_v3, needs_v3_migration
from core.database import get_setting
from core.password_change import (
    MAX_BACKUP_AGE_HOURS,
    PasswordChangeError,
    _restore_point_age_hours,
    reset_password_with_recovery_key,
    rotate_recovery_key,
)
from utils.backup import create_full_backup, get_verified_latest_restore_point
from utils.log import get_logger
from web import idle

log = get_logger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# Simple rate limiting for login attempts
# In-memory rate limiting — intentionally resets on restart.
# Acceptable for single-user localhost app; an attacker would need
# local access already, making persistent tracking unnecessary.
_login_attempts = {}  # bucket -> list of attempt timestamps

# One bucket for the whole process. The server only listens on loopback,
# so every caller shares one address on macOS and, on Linux, could pick
# a fresh 127.x.y.z per guess to dodge a per-address limit. A single
# user's app needs a single counter (security review 2026-09, #20).
_RATE_BUCKET = "local"


def _rate_key(_ip: str) -> str:
    return _RATE_BUCKET
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 60


# Pending password-change jobs. The plaintext current/new passwords are held
# here in server-process memory ONLY — never in the Flask session, which is a
# signed-but-unencrypted client cookie and would expose them to the browser.
# The POST endpoint mints an opaque one-time job id; the SSE endpoint consumes
# it exactly once. Mirrors the job model in web/blueprints/api/exports.py.
_pw_change_jobs = {}  # job_id -> {"current", "new", "created_at"}
_pw_change_lock = threading.Lock()
_PW_CHANGE_TTL = 300  # seconds; abandoned (never-consumed) jobs purged


# A recovery key that has been VERIFIED, held between /login/recovery and
# /login/recovery/new-password. Server-process memory only, for the same
# reason as the password-change jobs above: the session is a signed but
# unencrypted cookie, and a recovery key placed there would be readable in
# the browser's cookie jar.
#
# Short TTL: the user is mid-flow with the key in front of them, so there
# is no reason for this to outlive a single sitting. Single-entry — a new
# verification supersedes any pending one.
_recovery_reset_handoff = {}  # token -> {"key", "created_at"}
_recovery_handoff_lock = threading.Lock()
_RECOVERY_HANDOFF_TTL = 300


def _store_recovery_handoff(recovery_key):
    token = secrets.token_urlsafe(32)
    with _recovery_handoff_lock:
        _recovery_reset_handoff.clear()
        _recovery_reset_handoff[token] = {
            "key": recovery_key,
            "created_at": time.time(),
        }
    return token


def _peek_recovery_handoff(token):
    """Return the verified key for this token, or None. Does not consume."""
    if not token:
        return None
    with _recovery_handoff_lock:
        entry = _recovery_reset_handoff.get(token)
        if not entry:
            return None
        if time.time() - entry["created_at"] > _RECOVERY_HANDOFF_TTL:
            _recovery_reset_handoff.pop(token, None)
            return None
        return entry["key"]


def _drop_recovery_handoff(token):
    with _recovery_handoff_lock:
        _recovery_reset_handoff.pop(token, None)


def _gc_pw_change_jobs():
    """Drop password-change jobs older than the TTL so abandoned requests
    don't leave plaintext passwords sitting in memory indefinitely."""
    cutoff = time.time() - _PW_CHANGE_TTL
    with _pw_change_lock:
        stale = [jid for jid, j in _pw_change_jobs.items() if j["created_at"] < cutoff]
        for jid in stale:
            _pw_change_jobs.pop(jid, None)


def _check_rate_limit(ip: str) -> tuple[bool, int]:
    """
    Check whether login attempts are currently rate limited.

    Returns:
        (allowed: bool, seconds_remaining: int)
    """
    ip = _rate_key(ip)
    now = time.time()

    if ip not in _login_attempts:
        _login_attempts[ip] = []

    # Clean old attempts (older than lockout period)
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _LOCKOUT_SECONDS]

    if len(_login_attempts[ip]) >= _MAX_ATTEMPTS:
        oldest = min(_login_attempts[ip])
        seconds_remaining = int(_LOCKOUT_SECONDS - (now - oldest))
        return False, max(0, seconds_remaining)

    return True, 0


def _record_failed_attempt(ip: str):
    """Record a failed login attempt."""
    ip = _rate_key(ip)
    if ip not in _login_attempts:
        _login_attempts[ip] = []
    _login_attempts[ip].append(time.time())


def _clear_attempts(ip: str):
    """Clear login attempts after successful login."""
    ip = _rate_key(ip)
    if ip in _login_attempts:
        del _login_attempts[ip]


def init_database():
    """Initialize the database with the encryption key."""
    db_key = Encryption.get_db_key()
    Database.set_key(db_key)
    Database.initialize()


def cleanup_expired_trash():
    """
    Permanently delete folders and emails that have been in trash longer than the retention period.
    Called on login to clean up stale trash items.
    """
    retention_days = get_setting("trash_retention_days", "0")
    if retention_days == "0":
        return  # Never auto-delete

    try:
        retention_seconds = int(retention_days) * 24 * 60 * 60
        cutoff_time = int(time.time()) - retention_seconds

        # Find folders that have been deleted longer than retention period
        expired_folders = Database.fetchall(
            "SELECT id FROM folders WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff_time,)
        )

        if expired_folders:
            # Delete the folders (CASCADE will handle children)
            for folder in expired_folders:
                Database.execute("DELETE FROM folders WHERE id = ?", (folder["id"],))
            Database.commit()
            log.info(f"Trash cleanup: permanently deleted {len(expired_folders)} expired folder(s)")

        # Find emails that have been deleted longer than retention period
        expired_emails = Database.fetchall(
            "SELECT id, filepath FROM messages WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (cutoff_time,),
        )

        if expired_emails:
            # Delete the email files and database records
            for email in expired_emails:
                # Delete the file
                try:
                    filepath = Config.get_base_path() / email["filepath"]
                    if filepath.exists():
                        filepath.unlink()
                except Exception as e:
                    log.warning(f"Could not delete file {email['filepath']}: {e}")

                # Delete the database record
                Database.execute("DELETE FROM messages WHERE id = ?", (email["id"],))
            Database.commit()
            log.info(f"Trash cleanup: permanently deleted {len(expired_emails)} expired email(s)")
    except Exception as e:
        log.warning(f"Trash cleanup error: {e}")


@auth_bp.route("/setup", methods=["GET", "POST"])
def setup():
    """
    First-run setup: create master password.

    Only accessible if encryption hasn't been initialized yet.
    """
    # Redirect if already set up
    if Encryption.is_initialized():
        return redirect(url_for("auth.login"))

    # If backups exist, restoring is almost certainly what is wanted, so
    # lead with it rather than putting it behind a link on a page whose
    # obvious action starts an empty archive over the top of a
    # recoverable situation. ?new=1 is the way past, for someone who
    # really is starting a second archive alongside their backups.
    if request.method == "GET" and not request.args.get("new"):
        if _find_backups():
            return redirect(url_for("auth.recover"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        # Validation
        errors = []

        if len(password) < 12:
            errors.append("Password must be at least 12 characters.")

        if password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            return render_template("auth/setup.html", errors=errors)

        # Initialize encryption
        try:
            recovery_key = Encryption.initialize_v3(password)
            init_database()

            # Clear any stale session data before setting new values
            session.clear()
            session["authenticated"] = True
            session["last_activity"] = time.time()
            session["csrf_token"] = secrets.token_hex(32)
            session["login_id"] = idle.new_login_id()
            session.permanent = True

            # Render the recovery key directly in this response rather than
            # redirecting with it in the session. Flask sessions are SIGNED,
            # not encrypted, so anything put there is readable in the
            # browser's cookie jar — which is the last place a recovery key
            # should live. This is the only time the key exists in plaintext
            # anywhere; it is not stored, and closing this page loses it.
            return render_template(
                "auth/recovery_key.html",
                recovery_key=recovery_key,
                context="setup",
            )
        except EncryptionError as e:
            return render_template("auth/setup.html", errors=[str(e)])

    return render_template("auth/setup.html")


# ============================================================================
# Disaster recovery
#
# These routes are public, and deliberately so — the same reasoning that
# makes auth.login public. They exist for someone whose archive is gone:
# requiring a session to reach them would make them unreachable by
# precisely the person they are for, since a session requires a key file
# that no longer exists.
#
# What keeps this narrow:
#   - They are dead unless the door is open. Every one of them refuses
#     via _recovery_door_open(): closed once an archive exists that
#     someone has proved they can open, so this is not a way to roll a
#     live archive back over its owner. The door reopens only for an
#     UNVERIFIED restore — data nobody has vouched for yet.
#   - Completing a restore grants no access to anything. The restored
#     database and archive are still encrypted under the credentials
#     that were in force when the backup was taken.
#   - MailRepo binds loopback, though that is the weakest of the three
#     and is not relied on here.
# ============================================================================


def _recovery_door_open():
    """May the disaster-recovery routes be used right now?

    Two states qualify:
      - true first run: no key file at all (the door's original purpose)
      - an UNVERIFIED restore: a key file exists, but it arrived by
        restore and nobody has proved they can open it yet. If the
        backup's password turns out to be lost, login is a wall — and
        without this, the recovery routes would be dead the moment the
        restore landed, leaving no way back to a different backup,
        including the pre-restore safety copy. A demonstrated credential
        (password login, or a verified recovery key) clears the marker
        and closes the door, so an archive in normal use is never
        reachable this way. Not a rollback hole: the only state exposed
        is an archive nobody has vouched for, and whoever could exploit
        the window could have used the recovery door moments earlier.
    """
    from utils import backup

    return not Encryption.is_initialized() or backup.restore_unverified()


def _recovery_gate():
    """Redirect away from the recovery routes when the door is closed."""
    if not _recovery_door_open():
        return redirect(url_for("auth.login"))
    return None


def _restore_login_context():
    """What the login screen needs to say about a just-restored archive.

    Two independent signals, both read WITHOUT consuming:
      - RESTORE_COMPLETED (set at startup when a staged restore was
        applied): carries the date and the credential note chosen with
        the restore point. Popped only on a successful vouch.
      - the unverified-restore marker: still present means nobody has
        opened the restored data yet, so the screen also offers the way
        back ("restore a different backup").

    Without this, a perfectly correct restore is indistinguishable from
    a rejected password — the user types their current password, is
    refused, and has no way to know the archive now wants an older one.
    Read on every render of the login screens, so it survives failed
    attempts, which is precisely when it is needed.
    """
    from flask import current_app

    from utils import backup

    restored = current_app.config.get("RESTORE_COMPLETED")
    unverified = backup.restore_unverified()

    if not restored and not unverified:
        return {}

    note = ""
    date = ""
    if restored:
        note = restored.get("credential_note", "")
        date = (restored.get("original_date") or "")[:10]
    if not note:
        note = (
            "It opens with the master password that was in use when the "
            "backup was made — not necessarily your current one."
        )

    return {
        "restored_banner": True,
        "restored_date": date,
        "restored_note": note,
        "restore_retry_available": unverified,
    }


def _vouch_for_restored_data():
    """A credential has been demonstrated against the data on disk.

    Clears the unverified-restore marker (closing the recovery door) and
    retires the startup banner. Called from both ways in — login() and
    login_with_recovery_key() — because both are demonstrations, not
    inferences: the password unwrapped the key file and opened the
    database; verify_recovery_key performs the full recovery-side unwrap.
    Consistent with Daybook's ruling of Aug 16 (7cecbb8, 'a session
    proves the password and nothing else'): what counts is the
    credential actually proved against this archive, and here one was.
    """
    from flask import current_app

    from core.database import set_setting
    from utils import backup

    if backup.restore_unverified():
        # A post-backup command read out of a just-restored database is a
        # shell command chosen by whoever wrote that backup. Do not run it
        # on the strength of the restore; make the owner re-enter it
        # (security review 2026-09, #18).
        try:
            if get_setting("post_backup_command", ""):
                set_setting("post_backup_command", "")
                flash(
                    "The post-backup command stored in the restored backup was cleared "
                    "as a precaution. Re-enter it under Backups if you use one.",
                    "info",
                )
        except Exception as e:  # noqa: BLE001
            log.warning(f"Could not clear restored post-backup command: {e}")

    backup.clear_restore_unverified()
    current_app.config.pop("RESTORE_COMPLETED", None)


def _recovery_csrf_token():
    """Mint (or reuse) a CSRF token for the recovery screen.

    There is no authenticated session here, so this token is not proving
    identity — nothing to prove it against. It stops a page in another
    tab from firing off a restore, which is destructive.
    """
    token = session.get("recovery_csrf")
    if not token:
        token = secrets.token_hex(32)
        session["recovery_csrf"] = token
    return token


def _check_recovery_csrf():
    """Accept the token from the header base.html already sends, or the body."""
    expected = session.get("recovery_csrf", "")
    if not expected:
        return False

    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied and request.is_json:
        supplied = (request.get_json(silent=True) or {}).get("csrf_token", "")
    if not supplied:
        supplied = request.form.get("csrf_token", "")

    return secrets.compare_digest(supplied, expected)


@auth_bp.route("/restore")
def recover():
    """Restore from a backup when there is no archive to log in to."""
    gate = _recovery_gate()
    if gate:
        return gate

    default_folder = str(Config.get_backup_path())

    return render_template(
        "auth/recover.html",
        csrf_token=_recovery_csrf_token(),
        default_folder=default_folder,
    )


@auth_bp.route("/restore/scan", methods=["POST"])
def recover_scan():
    """List restore points found in a folder."""
    if not _recovery_door_open():
        return jsonify({"success": False, "error": "This archive is already set up."}), 403

    if not _check_recovery_csrf():
        return jsonify({"success": False, "error": "Invalid request token."}), 403

    from utils import backup

    data = request.get_json(silent=True) or {}
    folder = (data.get("folder") or "").strip()

    if not folder:
        folder = str(Config.get_backup_path())

    try:
        resolved = Path(folder).expanduser().resolve()
    except Exception as e:
        return jsonify({"success": False, "error": f"Invalid path: {e}"}), 400

    if not resolved.exists():
        return jsonify({"success": False, "error": "That folder does not exist."}), 400
    if not resolved.is_dir():
        return jsonify({"success": False, "error": "That path is not a folder."}), 400

    try:
        points, source = backup.discover_restore_points_in(resolved)
    except PermissionError:
        return jsonify(
            {"success": False, "error": "MailRepo cannot read that folder."}
        ), 403
    except Exception as e:
        log.error(f"Recovery scan failed for {resolved}: {e}")
        return jsonify({"success": False, "error": f"Could not read that folder: {e}"}), 500

    return jsonify(
        {
            "success": True,
            "folder": str(resolved),
            "source": source,
            "restore_points": points,
        }
    )


@auth_bp.route("/restore/prepare", methods=["POST"])
def recover_prepare():
    """Stage a restore found by a recovery scan.

    Re-scans rather than trusting an id and a file list from the client.
    The scan is cheap, and it means the paths that get opened are ones
    this route derived itself from a folder the user named.
    """
    if not _recovery_door_open():
        return jsonify({"success": False, "error": "This archive is already set up."}), 403

    if not _check_recovery_csrf():
        return jsonify({"success": False, "error": "Invalid request token."}), 403

    from utils import backup

    data = request.get_json(silent=True) or {}
    folder = (data.get("folder") or "").strip()
    point_id = (data.get("restore_point_id") or "").strip()

    if not point_id:
        return jsonify({"success": False, "error": "No restore point specified."}), 400

    if not folder:
        folder = str(Config.get_backup_path())

    try:
        resolved = Path(folder).expanduser().resolve()
        points, _source = backup.discover_restore_points_in(resolved)
    except Exception as e:
        return jsonify({"success": False, "error": f"Could not read that folder: {e}"}), 400

    point = next((p for p in points if p["id"] == point_id), None)
    if not point:
        return jsonify({"success": False, "error": "That restore point is no longer there."}), 404

    problems = backup.verify_restore_point_files(point)
    if problems:
        return jsonify({"success": False, "error": "; ".join(problems)}), 400

    try:
        backup.prepare_restore_from_point(point)
    except Exception as e:
        log.error(f"Recovery restore failed: {e}")
        return jsonify({"success": False, "error": f"Restore could not be staged: {e}"}), 500

    return jsonify(
        {
            "success": True,
            "message": (
                "Restore staged. Quit MailRepo and start it again to finish."
            ),
        }
    )


_backup_search_cache = {"done": False, "results": []}
_backup_search_lock = threading.Lock()


def _find_backups(force=False):
    """Locate this archive's backups, once per process unless forced.

    Reads MailRepo's own record of where it has written backups, plus
    its default backups folder. No guessing and no disk search — a
    location the record does not know is the folder picker's job.
    """
    from utils import backup

    with _backup_search_lock:
        if _backup_search_cache["done"] and not force:
            return _backup_search_cache["results"]

        try:
            results = backup.find_backup_locations()
        except Exception as e:
            log.error(f"Backup search failed: {e}")
            results = []

        _backup_search_cache["done"] = True
        _backup_search_cache["results"] = results
        return results


@auth_bp.route("/restore/search", methods=["POST"])
def recover_search():
    """Re-run the backup search on demand."""
    if not _recovery_door_open():
        return jsonify({"success": False, "error": "This archive is already set up."}), 403

    if not _check_recovery_csrf():
        return jsonify({"success": False, "error": "Invalid request token."}), 403

    force = bool((request.get_json(silent=True) or {}).get("force"))
    locations = _find_backups(force=force)

    return jsonify({"success": True, "locations": locations})


@auth_bp.route("/restore/browse", methods=["POST"])
def recover_browse():
    """List subfolders so the user can point at a backup without typing.

    A pared-down twin of the authenticated folder picker in the backups
    blueprint. Kept separate rather than shared because that one sits
    behind the auth gate, and the whole point here is that there is no
    session to gate on.
    """
    if not _recovery_door_open():
        return jsonify({"success": False, "error": "This archive is already set up."}), 403

    if not _check_recovery_csrf():
        return jsonify({"success": False, "error": "Invalid request token."}), 403

    from utils import backup

    requested = ((request.get_json(silent=True) or {}).get("path") or "").strip()

    try:
        current = Path(requested).expanduser().resolve() if requested else Path.home()
    except Exception as e:
        return jsonify({"success": False, "error": f"Invalid path: {e}"}), 400

    if not current.is_dir():
        return jsonify({"success": False, "error": "That folder does not exist."}), 400

    folders = []
    try:
        for entry in sorted(current.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith(".") or not entry.is_dir():
                continue
            try:
                names = {p.name for p in entry.iterdir() if p.is_file()}
                holds_backups = backup.folder_holds_mailrepo_backups(entry)
            except (OSError, PermissionError):
                names, holds_backups = set(), False

            folders.append(
                {
                    "name": entry.name,
                    "path": str(entry),
                    # Flagged in the listing so the user can see which
                    # folder to pick instead of opening each in turn.
                    "has_backups": holds_backups,
                    "other_app_backups": bool(
                        not holds_backups and backup._looks_like_backup_folder(names)
                    ),
                }
            )
    except PermissionError:
        return jsonify({"success": False, "error": "MailRepo cannot read that folder."}), 403

    return jsonify(
        {
            "success": True,
            "current_path": str(current),
            "parent_path": str(current.parent) if current.parent != current else None,
            "folders": folders,
            "current_has_backups": backup.folder_holds_mailrepo_backups(current),
        }
    )


@auth_bp.route("/setup/recovery-key-saved", methods=["POST"])
def recovery_key_confirmed():
    """Acknowledge that the recovery key has been written down.

    Deliberately stores nothing. The checkbox is a speed bump against
    clicking past the one screen where the key exists, not a record of
    anything — MailRepo cannot verify the user actually saved it, and
    pretending otherwise in the data model would be theatre.

    Where the user lands afterwards depends on how they got here. After
    first-run setup, creating an archive is genuinely the next step.
    After a migration they already have one, and sending them to
    "Create New Archive" reads like the upgrade wiped everything.
    """
    if not session.get("authenticated"):
        return redirect(url_for("auth.login"))

    token = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if not expected or not secrets.compare_digest(token, expected):
        return redirect(url_for("auth.login"))

    if request.form.get("context") == "migration":
        flash("Recovery key created. Your archive is unchanged.", "success")
        return redirect(url_for("main.index"))

    return redirect(url_for("main.create_archive"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Login with master password.

    Redirects to setup if not initialized.
    Rate limited to prevent brute-force attacks.
    """
    # Redirect if setup needed
    if not Encryption.is_initialized():
        return redirect(url_for("auth.setup"))

    # Already logged in
    if session.get("authenticated") and Encryption.is_unlocked():
        return redirect(url_for("main.index"))

    # After a restore, this screen is the one place that can say which
    # password the archive wants. Passed to every render below so the
    # banner survives failed attempts — exactly when it is needed.
    restore_ctx = _restore_login_context()

    # Check rate limit
    client_ip = request.remote_addr or "unknown"
    allowed, seconds_remaining = _check_rate_limit(client_ip)

    if not allowed:
        return render_template(
            "auth/login.html",
            error=f"Too many failed attempts. Please wait {seconds_remaining} seconds.",
            lockout_seconds=seconds_remaining,
            **restore_ctx,
        )

    if request.method == "POST":
        password = request.form.get("password", "")

        try:
            Encryption.unlock(password)
            _clear_attempts(client_ip)  # Success - clear attempts
            init_database()
            cleanup_expired_trash()

            # The password unwrapped the key file and opened the
            # database: whoever is here can vouch for the data on disk.
            # If it arrived by restore, the unverified marker comes off
            # and the recovery door closes.
            _vouch_for_restored_data()

            # Clear any stale session data before setting new values
            session.clear()
            session["authenticated"] = True
            session["last_activity"] = time.time()
            session["csrf_token"] = secrets.token_hex(32)
            session["login_id"] = idle.new_login_id()
            session.permanent = True
            idle.touch()

            # Offer the recovery-key upgrade on the way in. A one-time
            # nudge per login rather than a permanent nag: the archive
            # works fine without it, and pestering someone on every page
            # trains them to dismiss notices that matter.
            if needs_v3_migration():
                return make_response(
                    redirect(url_for("auth.upgrade_to_recovery_keys"))
                )

            # Use make_response for explicit cookie handling (Safari/Firefox)
            response = make_response(redirect(url_for("main.index")))
            return response
        except InvalidPasswordError:
            _record_failed_attempt(client_ip)
            return render_template(
                "auth/login.html", error="Invalid password.", **restore_ctx
            )
        except EncryptionError as e:
            return render_template("auth/login.html", error=str(e), **restore_ctx)

    return render_template("auth/login.html", **restore_ctx)


@auth_bp.route("/login/recovery", methods=["GET", "POST"])
def login_with_recovery_key():
    """Unlock using the printed recovery key instead of the master password.

    Rate limited on the same counter as password login: this is a second
    full-access credential, and leaving it un-throttled would make it the
    cheaper thing to attack.
    """
    if not Encryption.is_initialized():
        return redirect(url_for("auth.setup"))

    # A restored archive whose password is lost lands exactly here, so
    # this screen carries the restore banner too.
    restore_ctx = _restore_login_context()

    if not Encryption.has_recovery_key():
        return render_template(
            "auth/login.html",
            error="This archive predates recovery keys and can only be opened "
            "with its master password.",
            **restore_ctx,
        )

    client_ip = request.remote_addr or "unknown"
    allowed, seconds_remaining = _check_rate_limit(client_ip)
    if not allowed:
        return render_template(
            "auth/recovery_login.html",
            error=f"Too many failed attempts. Please wait {seconds_remaining} seconds.",
            lockout_seconds=seconds_remaining,
            **restore_ctx,
        )

    if request.method == "POST":
        recovery_key = request.form.get("recovery_key", "")

        try:
            # Verify ONLY. This route deliberately does not unlock the
            # archive or grant a session: the recovery key is a way to
            # reset the password, not a second password. Granting a
            # session here is what would let someone skip the reset and
            # keep using the printed key as their daily credential.
            Encryption.verify_recovery_key(recovery_key)
        except InvalidPasswordError:
            _record_failed_attempt(client_ip)
            return render_template(
                "auth/recovery_login.html",
                error="That recovery key does not open this archive.",
                **restore_ctx,
            )
        except EncryptionError as e:
            # Malformed input (wrong length, bad characters). A typo is
            # not a guess, so it does not spend a rate-limit attempt —
            # otherwise fumbling a 32-character string locks you out of
            # your own recovery path.
            return render_template(
                "auth/recovery_login.html", error=str(e), **restore_ctx
            )

        _clear_attempts(client_ip)

        # verify_recovery_key performed the full recovery-side unwrap of
        # the key file on disk: a credential was DEMONSTRATED against
        # this archive, not inferred. That is a vouch — if the data
        # arrived by restore, the unverified marker comes off here just
        # as it does on password login. (Daybook's Aug 16 ruling: only
        # what has been proved counts. This was proved.)
        _vouch_for_restored_data()

        token = _store_recovery_handoff(recovery_key)

        # Render the reset form directly rather than redirecting with the
        # token in a query string. A redirect would put the token in
        # browser history for the whole of its 5-minute life; here it
        # exists only in a hidden field on the page in front of the user.
        return render_template("auth/post_recovery_password.html", token=token)

    return render_template("auth/recovery_login.html", **restore_ctx)


@auth_bp.route("/login/recovery/new-password", methods=["GET", "POST"])
def set_password_post_recovery():
    """Set a new master password after a verified recovery key.

    Reachable only with a handoff token from /login/recovery, which is
    minted only after the key verifies. No session is involved: the
    verified key held server-side IS the authorisation, and it is what
    performs the reset.

    This is mandatory rather than offered. Someone who used their
    recovery key has by definition lost their password; letting them skip
    would leave them reaching for the printed key at every subsequent
    login, and a 32-character string used routinely ends up photographed
    or pasted into a notes app — the break-glass credential migrating
    into everyday storage.
    """
    # Form only. Accepting it from the query string would let a pasted
    # URL land the handoff token in browser history.
    token = request.form.get("token", "")
    recovery_key = _peek_recovery_handoff(token)
    if not recovery_key:
        return redirect(url_for("auth.login_with_recovery_key"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        errors = []
        if len(password) < 12:
            errors.append("Password must be at least 12 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            return render_template(
                "auth/post_recovery_password.html", errors=errors, token=token
            )

        try:
            reset_password_with_recovery_key(recovery_key, password)
        except (PasswordChangeError, EncryptionError) as e:
            return render_template(
                "auth/post_recovery_password.html", errors=[str(e)], token=token
            )

        _drop_recovery_handoff(token)

        # Deliberately does NOT log the user in. They have typed this
        # password exactly twice; using it once more now, while the
        # recovery key is still in their hand, is the cheapest possible
        # confirmation that it is what they think it is.
        return render_template("auth/post_recovery_password.html", done=True)

    return render_template("auth/post_recovery_password.html", token=token)

    return render_template("auth/post_recovery_password.html")


@auth_bp.route("/upgrade", methods=["GET", "POST"])
def upgrade_to_recovery_keys():
    """Offer, and perform, the v2 -> v3 upgrade for an existing archive.

    Runs synchronously. Measured throughput is ~850 files/s (the walk is
    plain AES-GCM; the expensive Argon2id derivation happens once), so
    even a very large archive is a couple of minutes, and this is
    localhost with no proxy in front of it. A progress stream would be
    more machinery than the operation warrants.
    """
    if not session.get("authenticated") or not Encryption.is_unlocked():
        return redirect(url_for("auth.login"))

    if not needs_v3_migration():
        flash("This archive already has a recovery key.", "info")
        return redirect(url_for("main.index"))

    # The migration ends in a non-resumable window, so it demands a
    # verified recent backup. Report that up front rather than letting the
    # user submit the form and bounce off the gate.
    point, problems = get_verified_latest_restore_point()
    age = _restore_point_age_hours(point) if point else None
    backup_ok = not problems and age is not None and age <= MAX_BACKUP_AGE_HOURS

    if request.method == "POST":
        # CSRF token check. The password requirement already stops a blind
        # cross-site POST from doing anything, but the app-level CSRF
        # middleware only covers /api/ paths, so state-changing /auth/
        # forms carry and verify the token themselves for consistency.
        token = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not secrets.compare_digest(token, expected):
            return redirect(url_for("auth.login"))

        password = request.form.get("password", "")

        try:
            if not backup_ok:
                # MUST be a full backup, not create_backup(). The latter
                # auto-decides and picks incremental when a recent full
                # exists — and an incremental returns None when nothing
                # has changed, which is exactly the case here for an
                # archive that has been sitting idle. The gate would then
                # still see the stale backup and refuse, after this page
                # promised a fresh one would be taken.
                #
                # And it MUST go to the configured backup location. With
                # no argument it defaults to the repo's backups/ dir,
                # which for anyone using a cloud folder means the backup
                # lands somewhere their off-machine sync never sees — a
                # full that exists locally while the incrementals that
                # depend on it are the only things replicated.
                location = get_setting("backup_location", "")
                create_full_backup(location if location else None)

            recovery_key = migrate_to_v3(password)
        except InvalidPasswordError:
            return render_template(
                "auth/upgrade.html",
                errors=["That is not your current master password."],
                backup_ok=backup_ok,
                backup_age=age,
                backup_problems=problems,
            )
        except Exception as e:
            log.error(f"v3 upgrade failed: {e}")
            # Re-read backup state: a backup may well have been taken
            # just now, and reporting the pre-attempt state would be
            # stale and confusing.
            point, problems = get_verified_latest_restore_point()
            age = _restore_point_age_hours(point) if point else None
            return render_template(
                "auth/upgrade.html",
                errors=[
                    "The upgrade could not be completed. Your archive has "
                    "not been changed and your password is unaffected.",
                    str(e),
                ],
                backup_ok=not problems
                and age is not None
                and age <= MAX_BACKUP_AGE_HOURS,
                backup_age=age,
                backup_problems=problems,
            )

        return render_template(
            "auth/recovery_key.html",
            recovery_key=recovery_key,
            context="migration",
        )

    return render_template(
        "auth/upgrade.html",
        backup_ok=backup_ok,
        backup_age=age,
        backup_problems=problems,
    )


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Log out, run backup check, and lock encryption.

    POST-only. This clears the session, locks the archive and triggers a
    backup check — all state-changing, so a cross-site `<img src>` could
    otherwise force it. Nuisance-tier at this threat model rather than
    dangerous, but a state-changing GET is the kind of thing a maintainer
    copies. Callers go through window.mailrepoLogout() in base.html.

    Also carries a CSRF token, like the other non-/api/ forms: a
    cross-site auto-submitting form could otherwise force a logout
    and, if a backup is due, run the post-backup command.
    """
    if session.get("authenticated"):
        # Form field from window.mailrepoLogout(); header from the two
        # fetch()-based callers (the fetch wrapper in base.html adds it).
        token = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not expected or not secrets.compare_digest(token, expected):
            return redirect(url_for("main.index"))

    timed_out = request.form.get("reason") == "timeout"

    # Run automatic backup check before closing database
    _run_auto_backup_check()

    Database.close()
    Encryption.lock()
    session.clear()
    if timed_out:
        flash("Your session timed out due to inactivity. Please log in again.", "info")
    else:
        flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


def _run_auto_backup_check():
    """Run automatic backup if frequency setting requires it."""
    try:
        from utils import backup

        # Checkpoint WAL first so backup captures all changes
        Database.checkpoint()

        frequency = get_setting("backup_frequency", "daily")
        log.debug(f"Backup frequency setting: {frequency}")

        if backup.check_backup_needed(frequency):
            log.info("Checking backup status...")
            location = get_setting("backup_location", "")
            if not location:
                location = None  # Use default
            result = backup.create_backup(location)
            if result:
                log.info(f"Backup created: {result['filename']}")

                # Retention cleanup. This lives here as well as in the
                # manual Backup Now endpoint because almost every backup
                # is automatic — pruning only on the days the user
                # happens to click the button means a retention setting
                # that quietly does nothing.
                retention = get_setting("backup_retention", "forever")
                if retention != "forever":
                    backup.cleanup_old_backups(retention, location)

                # Run post-backup command if configured. run_shell_command
                # owns the process group and kills it wholesale on timeout,
                # so the outcome we log is the outcome that happened (no
                # orphaned rsync finishing after a reported "timeout").
                post_cmd = get_setting("post_backup_command", "")
                if post_cmd:
                    log.info("Running post-backup command")
                    from utils import run_shell_command

                    success, msg, cmd_stdout = run_shell_command(post_cmd, timeout=300)
                    for line in (cmd_stdout or "").strip().split("\n"):
                        if line:
                            log.info(f"  {line}")
                    if success:
                        log.info("Post-backup command completed")
                    else:
                        log.warning(f"Post-backup command: {msg}")
            else:
                log.info("No changes since last backup")

            # Record that we checked today (whether backup created or not)
            backup.record_backup_check()
        else:
            log.debug("Backup not needed (frequency check)")
    except Exception as e:
        log.error(f"Auto-backup failed: {e}")


@auth_bp.route("/api/verify-recovery-key", methods=["POST"])
def api_verify_recovery_key():
    """Check a recovery key without changing anything.

    The counterpart to the recovery flow, which always resets the
    password. Testing a key should not cost you your password, and a key
    that has never been tested is one you are only assuming works.

    Gated on an existing session rather than the master password. Someone
    with a live session already has the archive open, so this reveals
    nothing they do not have, and it writes nothing. Demanding the
    password here would only discourage the checking this exists to
    encourage.
    """
    if not session.get("authenticated"):
        return {"error": "Not authenticated"}, 401

    if not Encryption.has_recovery_key():
        return {"error": "This archive has no recovery key."}, 400

    data = request.get_json() or {}
    recovery_key = data.get("recovery_key", "")

    try:
        Encryption.verify_recovery_key(recovery_key)
        return {"verified": True}
    except InvalidPasswordError:
        return {
            "verified": False,
            "error": (
                "That key does not open this archive. If it is the one you "
                "have on file, generate a new one and replace it."
            ),
        }
    except EncryptionError as e:
        # Malformed — a typo, not a wrong key. Say which.
        return {"verified": False, "error": str(e)}


@auth_bp.route("/api/recovery-key-status", methods=["GET"])
def recovery_key_status():
    """Whether this archive has a recovery key, for the settings screen."""
    if not session.get("authenticated"):
        return {"error": "Not authenticated"}, 401

    return {
        "has_recovery_key": Encryption.has_recovery_key(),
        "needs_upgrade": needs_v3_migration(),
    }


@auth_bp.route("/api/rotate-recovery-key", methods=["POST"])
def api_rotate_recovery_key():
    """Issue a new recovery key, revoking the old one.

    Returns the new key in the response body. It is not stored, so this
    response is the only place it exists — the frontend must show it and
    must not discard it silently.
    """
    if not session.get("authenticated"):
        return {"error": "Not authenticated"}, 401

    data = request.get_json() or {}
    password = data.get("password", "")

    try:
        new_key = rotate_recovery_key(password)
        return {"recovery_key": new_key}
    except InvalidPasswordError:
        return {"error": "Current password is incorrect"}, 403
    except PasswordChangeError as e:
        return {"error": str(e)}, 400
    except Exception as e:
        log.error(f"Recovery key rotation failed: {e}")
        return {"error": "Could not rotate the recovery key."}, 500


@auth_bp.route("/api/verify-password", methods=["POST"])
def verify_password():
    """Verify the current password before allowing password change."""
    if not session.get("authenticated"):
        return {"error": "Not authenticated"}, 401

    data = request.get_json() or {}
    current_password = data.get("current_password", "")

    try:
        # Unlocking is the verification: a wrong password raises. This
        # DOES re-adopt class state, but with identical values, since the
        # archive is already unlocked when this endpoint is reachable.
        Encryption.unlock(current_password)
        return {"valid": True}
    except InvalidPasswordError:
        return {"valid": False, "error": "Current password is incorrect"}
    except Exception as e:
        return {"valid": False, "error": str(e)}


@auth_bp.route("/api/change-password", methods=["POST"])
def change_password_start():
    """Start the password change process - store new password in session."""
    if not session.get("authenticated"):
        return {"error": "Not authenticated"}, 401

    data = request.get_json() or {}
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")

    # Validate
    if len(new_password) < 12:
        return {"error": "New password must be at least 12 characters"}, 400

    # Verify current password
    try:
        Encryption.unlock(current_password)
    except InvalidPasswordError:
        return {"error": "Current password is incorrect"}, 400

    # Hold the passwords in server-side memory keyed by an opaque one-time
    # job id. They never touch the session cookie. The SSE progress endpoint
    # consumes this job exactly once.
    _gc_pw_change_jobs()
    job_id = secrets.token_urlsafe(32)
    with _pw_change_lock:
        _pw_change_jobs[job_id] = {
            "current": current_password,
            "new": new_password,
            "created_at": time.time(),
        }

    return {"success": True, "job_id": job_id}


@auth_bp.route("/api/change-password-progress/<job_id>")
def change_password_progress(job_id):
    """SSE endpoint for password change progress.

    Consumes the one-time job created by change_password_start. The plaintext
    passwords live only in server memory (keyed by the opaque job id) and are
    popped here exactly once — they are never placed in the session cookie."""
    if not session.get("authenticated"):
        return {"error": "Not authenticated"}, 401

    # Consume the job exactly once, and enforce the TTL HERE as well as
    # in _gc_pw_change_jobs(). That collector runs only when the next job
    # is created, so a job that is never consumed and never followed by
    # another holds both plaintext passwords in memory until the process
    # restarts. Checking at consume time makes the TTL mean what it says.
    cutoff = time.time() - _PW_CHANGE_TTL
    with _pw_change_lock:
        job = _pw_change_jobs.pop(job_id, None)
        if job and job["created_at"] < cutoff:
            job = None
        # Opportunistic sweep, mirroring _peek_recovery_handoff.
        for jid in [j for j, v in _pw_change_jobs.items() if v["created_at"] < cutoff]:
            _pw_change_jobs.pop(jid, None)
    current_password = job["current"] if job else None
    new_password = job["new"] if job else None

    def generate():
        if not current_password or not new_password:
            yield f"data: {json.dumps({'error': 'Missing or expired password-change request'})}\n\n"
            return

        # The actual work lives in core/password_change.change_master_password,
        # which branches on the key-file version itself: v2 archives get the
        # full re-encrypt walk, v3 archives get the 61-byte rewrap. Here we
        # just bridge its progress_cb into the SSE stream via a worker
        # thread + queue. The event
        # vocabulary matches settings.js (counting / counted / encrypting
        # with current+total / credentials / database / finalizing /
        # complete + error) so the frontend works without changes.
        import queue
        import threading

        from core.password_change import (
            PasswordChangeCorruptionError,
            PasswordChangeError,
            change_master_password,
        )

        q = queue.Queue()
        SENTINEL = object()

        def cb(event):
            q.put(event)

        def worker():
            try:
                result = change_master_password(current_password, new_password, progress_cb=cb)
                q.put(
                    {
                        "status": "complete",
                        "message": "Password changed successfully",
                        "result": result,
                    }
                )
            except InvalidPasswordError as e:
                q.put({"status": "error", "message": str(e)})
            except PasswordChangeCorruptionError as e:
                q.put(
                    {
                        "status": "error",
                        "message": str(e),
                        "kind": "corruption",
                        "filepath": e.filepath,
                    }
                )
            except PasswordChangeError as e:
                q.put({"status": "error", "message": str(e)})
            except Exception as e:
                q.put({"status": "error", "message": f"{type(e).__name__}: {e}"})
            finally:
                q.put(SENTINEL)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        while True:
            ev = q.get()
            if ev is SENTINEL:
                break
            yield f"data: {json.dumps(ev)}\n\n"
        t.join(timeout=1.0)

    return Response(generate(), mimetype="text/event-stream")
