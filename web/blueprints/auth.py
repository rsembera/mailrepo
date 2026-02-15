"""
MailRepo - Authentication blueprint.

Handles master password setup, login, logout, and password change.
"""

import json
import os
import secrets
import time
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, Response, current_app, make_response

from core import Encryption, InvalidPasswordError, EncryptionError, Database
from core.database import get_setting
from core.config import Config
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
            "SELECT id FROM folders WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (cutoff_time,)
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
            (cutoff_time,)
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
            Encryption.initialize(password)
            init_database()
            
            # Clear any stale session data before setting new values
            session.clear()
            session["authenticated"] = True
            session["last_activity"] = time.time()
            session["csrf_token"] = secrets.token_hex(32)
            session.permanent = True
            
            flash("Master password created successfully.", "success")
            response = make_response(redirect(url_for("main.create_archive")))
            return response
        except EncryptionError as e:
            return render_template("auth/setup.html", errors=[str(e)])
    
    return render_template("auth/setup.html")


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
            lockout_seconds=seconds_remaining
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
        
        frequency = get_setting('backup_frequency', 'daily')
        log.debug(f"Backup frequency setting: {frequency}")
        
        if backup.check_backup_needed(frequency):
            log.info("Checking backup status...")
            location = get_setting('backup_location', '')
            if not location:
                location = None  # Use default
            result = backup.create_backup(location)
            if result:
                log.info(f"Backup created: {result['filename']}")
                
                # Run post-backup command if configured
                post_cmd = get_setting('post_backup_command', '')
                if post_cmd:
                    from utils import run_shell_command
                    success, msg = run_shell_command(post_cmd, timeout=300)
                    if success:
                        log.info("Post-backup command completed")
                    else:
                        log.warning(f"Post-backup command error: {msg}")
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
    
    # Store in session for SSE endpoint
    session["password_change_current"] = current_password
    session["password_change_new"] = new_password
    session.modified = True
    
    return {"success": True}


@auth_bp.route("/api/change-password-progress")
def change_password_progress():
    """SSE endpoint for password change progress."""
    if not session.get("authenticated"):
        return {"error": "Not authenticated"}, 401
    
    # Get passwords from session
    current_password = session.get("password_change_current")
    new_password = session.get("password_change_new")
    
    # Clear from session immediately
    session.pop("password_change_current", None)
    session.pop("password_change_new", None)
    session.modified = True
    
    def generate():
        if not current_password or not new_password:
            yield f"data: {json.dumps({'error': 'Missing password data'})}\n\n"
            return
        
        try:
            # Step 1: Count encrypted files
            yield f"data: {json.dumps({'status': 'counting', 'message': 'Counting encrypted files...'})}\n\n"
            
            archive_dir = Config.get_archive_path()
            enc_files = []
            for root, dirs, files in os.walk(archive_dir):
                for f in files:
                    if f.endswith(".eml.enc"):
                        enc_files.append(os.path.join(root, f))
            
            total_files = len(enc_files)
            yield f"data: {json.dumps({'status': 'counted', 'total': total_files, 'message': f'Found {total_files} encrypted files'})}\n\n"
            
            # Step 2: Re-encrypt all files
            if total_files > 0:
                yield f"data: {json.dumps({'status': 'encrypting', 'total': total_files, 'current': 0, 'message': 'Re-encrypting files...'})}\n\n"
                
                old_fernet = Encryption.derive_fernet_for_password(current_password)
                new_fernet = Encryption.derive_fernet_for_password(new_password)
                
                failed_files = []
                for i, filepath in enumerate(enc_files):
                    try:
                        # Read and decrypt with old password
                        with open(filepath, "rb") as f:
                            encrypted_data = f.read()
                        decrypted_data = old_fernet.decrypt(encrypted_data)
                        
                        # Re-encrypt with new password
                        new_encrypted = new_fernet.encrypt(decrypted_data)
                        
                        # Write back
                        with open(filepath, "wb") as f:
                            f.write(new_encrypted)
                        
                    except Exception as e:
                        failed_files.append({"file": os.path.basename(filepath), "error": str(e)})
                    
                    # Progress update every 10 files or on last file
                    if (i + 1) % 10 == 0 or i == total_files - 1:
                        yield f"data: {json.dumps({'status': 'encrypting', 'total': total_files, 'current': i + 1, 'message': f'Re-encrypting {i + 1} of {total_files}...'})}\n\n"
                
                if failed_files:
                    yield f"data: {json.dumps({'status': 'warning', 'message': f'{len(failed_files)} files failed to re-encrypt', 'failed': failed_files})}\n\n"
            
            # Step 3: Re-encrypt IMAP credentials
            yield f"data: {json.dumps({'status': 'credentials', 'message': 'Re-encrypting account credentials...'})}\n\n"
            
            try:
                accounts = Database.fetchall("SELECT id, credentials_encrypted FROM accounts WHERE credentials_encrypted IS NOT NULL")
                for account in accounts:
                    try:
                        # Decrypt with old key, re-encrypt with new key
                        old_creds = old_fernet.decrypt(account["credentials_encrypted"].encode() if isinstance(account["credentials_encrypted"], str) else account["credentials_encrypted"])
                        new_creds = new_fernet.encrypt(old_creds)
                        Database.execute(
                            "UPDATE accounts SET credentials_encrypted = ? WHERE id = ?",
                            (new_creds.decode() if isinstance(new_creds, bytes) else new_creds, account["id"])
                        )
                    except Exception as e:
                        account_id = account["id"]
                        yield f"data: {json.dumps({'status': 'warning', 'message': f'Failed to re-encrypt credentials for account {account_id}: {e}'})}\n\n"
                Database.commit()
            except Exception as e:
                yield f"data: {json.dumps({'status': 'warning', 'message': f'Error re-encrypting credentials: {e}'})}\n\n"
            
            # Step 4: Rekey the database
            yield f"data: {json.dumps({'status': 'database', 'message': 'Updating database encryption...'})}\n\n"
            
            new_db_key = Encryption._derive_db_key(new_password, Encryption._salt)
            conn = Database._connection
            conn.execute(f"PRAGMA rekey = \"x'{new_db_key}'\"")
            
            # Step 5: Update the verification token
            yield f"data: {json.dumps({'status': 'finalizing', 'message': 'Updating password verification...'})}\n\n"
            
            Encryption.update_password(new_password)
            
            # Success
            yield f"data: {json.dumps({'status': 'complete', 'message': 'Password changed successfully!'})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
    
    return Response(generate(), mimetype="text/event-stream")
