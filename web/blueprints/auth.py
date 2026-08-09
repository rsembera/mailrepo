"""
MailRepo - Authentication blueprint.

Handles master password setup, login, logout, and password change.
"""

import json
import secrets
import threading
import time

from flask import (
    Blueprint,
    Response,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from core import Database, Encryption, EncryptionError, InvalidPasswordError
from core.config import Config
from core.database import get_setting
from core.password_change import (
    PasswordChangeError,
    set_password_after_recovery,
)
from utils.log import get_logger

log = get_logger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# Simple rate limiting for login attempts
# In-memory rate limiting — intentionally resets on restart.
# Acceptable for single-user localhost app; an attacker would need
# local access already, making persistent tracking unnecessary.
_login_attempts = {}  # IP -> list of attempt timestamps
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
    Check if IP is rate limited.

    Returns:
        (allowed: bool, seconds_remaining: int)
    """
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
    if ip not in _login_attempts:
        _login_attempts[ip] = []
    _login_attempts[ip].append(time.time())


def _clear_attempts(ip: str):
    """Clear login attempts after successful login."""
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


@auth_bp.route("/setup/recovery-key-saved", methods=["POST"])
def recovery_key_confirmed():
    """Acknowledge that the recovery key has been written down.

    Deliberately stores nothing. The checkbox is a speed bump against
    clicking past the one screen where the key exists, not a record of
    anything — MailRepo cannot verify the user actually saved it, and
    pretending otherwise in the data model would be theatre.
    """
    if not session.get("authenticated"):
        return redirect(url_for("auth.login"))

    token = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if not expected or not secrets.compare_digest(token, expected):
        return redirect(url_for("auth.login"))

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

    # Check rate limit
    client_ip = request.remote_addr or "unknown"
    allowed, seconds_remaining = _check_rate_limit(client_ip)

    if not allowed:
        return render_template(
            "auth/login.html",
            error=f"Too many failed attempts. Please wait {seconds_remaining} seconds.",
            lockout_seconds=seconds_remaining,
        )

    if request.method == "POST":
        password = request.form.get("password", "")

        try:
            Encryption.unlock(password)
            _clear_attempts(client_ip)  # Success - clear attempts
            init_database()
            cleanup_expired_trash()

            # Clear any stale session data before setting new values
            session.clear()
            session["authenticated"] = True
            session["last_activity"] = time.time()
            session["csrf_token"] = secrets.token_hex(32)
            session.permanent = True

            # Use make_response for explicit cookie handling (Safari/Firefox)
            response = make_response(redirect(url_for("main.index")))
            return response
        except InvalidPasswordError:
            _record_failed_attempt(client_ip)
            return render_template("auth/login.html", error="Invalid password.")
        except EncryptionError as e:
            return render_template("auth/login.html", error=str(e))

    return render_template("auth/login.html")


@auth_bp.route("/login/recovery", methods=["GET", "POST"])
def login_with_recovery_key():
    """Unlock using the printed recovery key instead of the master password.

    Rate limited on the same counter as password login: this is a second
    full-access credential, and leaving it un-throttled would make it the
    cheaper thing to attack.
    """
    if not Encryption.is_initialized():
        return redirect(url_for("auth.setup"))

    if not Encryption.has_recovery_key():
        return render_template(
            "auth/login.html",
            error="This archive predates recovery keys and can only be opened "
            "with its master password.",
        )

    client_ip = request.remote_addr or "unknown"
    allowed, seconds_remaining = _check_rate_limit(client_ip)
    if not allowed:
        return render_template(
            "auth/recovery_login.html",
            error=f"Too many failed attempts. Please wait {seconds_remaining} seconds.",
            lockout_seconds=seconds_remaining,
        )

    if request.method == "POST":
        recovery_key = request.form.get("recovery_key", "")

        try:
            Encryption.unlock_with_recovery_key(recovery_key)
            _clear_attempts(client_ip)
            init_database()
            cleanup_expired_trash()

            session.clear()
            session["authenticated"] = True
            session["last_activity"] = time.time()
            session["csrf_token"] = secrets.token_hex(32)
            session["via_recovery_key"] = True
            session.permanent = True

            return make_response(redirect(url_for("auth.set_password_post_recovery")))
        except InvalidPasswordError:
            _record_failed_attempt(client_ip)
            return render_template(
                "auth/recovery_login.html",
                error="That recovery key does not open this archive.",
            )
        except EncryptionError as e:
            # Malformed input (wrong length, bad characters) lands here
            # rather than in InvalidPasswordError, so the user is told they
            # mistyped it rather than that it is the wrong key.
            return render_template("auth/recovery_login.html", error=str(e))

    return render_template("auth/recovery_login.html")


@auth_bp.route("/login/recovery/new-password", methods=["GET", "POST"])
def set_password_post_recovery():
    """Set a new master password after unlocking with a recovery key.

    Someone who used their recovery key has almost always forgotten their
    password. Letting them straight into the app would leave them locked
    out again at the next login, so this is offered immediately — but not
    forced, because a user may have had another reason to use the key.
    """
    if not session.get("authenticated") or not Encryption.is_unlocked():
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        errors = []
        if len(password) < 12:
            errors.append("Password must be at least 12 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            return render_template("auth/post_recovery_password.html", errors=errors)

        try:
            set_password_after_recovery(password)
            session.pop("via_recovery_key", None)
            session["csrf_token"] = secrets.token_hex(32)
            flash("Master password updated.", "success")
            return redirect(url_for("main.index"))
        except PasswordChangeError as e:
            return render_template("auth/post_recovery_password.html", errors=[str(e)])

    return render_template("auth/post_recovery_password.html")


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    """Log out, run backup check, and lock encryption."""
    # Run automatic backup check before closing database
    _run_auto_backup_check()

    Database.close()
    Encryption.lock()
    session.clear()
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

                # Run post-backup command if configured. run_shell_command
                # owns the process group and kills it wholesale on timeout,
                # so the outcome we log is the outcome that happened (no
                # orphaned rsync finishing after a reported "timeout").
                post_cmd = get_setting("post_backup_command", "")
                if post_cmd:
                    log.info(f"Running post-backup command: {post_cmd}")
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


@auth_bp.route("/api/verify-password", methods=["POST"])
def verify_password():
    """Verify the current password before allowing password change."""
    if not session.get("authenticated"):
        return {"error": "Not authenticated"}, 401

    data = request.get_json()
    current_password = data.get("current_password", "")

    try:
        # Try to unlock with the provided password
        # This verifies it matches without changing state
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

    data = request.get_json()
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

    # Consume the job exactly once.
    with _pw_change_lock:
        job = _pw_change_jobs.pop(job_id, None)
    current_password = job["current"] if job else None
    new_password = job["new"] if job else None

    def generate():
        if not current_password or not new_password:
            yield f"data: {json.dumps({'error': 'Missing or expired password-change request'})}\n\n"
            return

        # All archives are on v2 (AES-256-GCM + Argon2id). The actual work
        # lives in core/password_change.change_master_password as a pure
        # function with a progress_cb; here we just bridge that callback
        # into the SSE stream via a worker thread + queue. The event
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
