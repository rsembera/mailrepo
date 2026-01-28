"""
MailRepo - Authentication blueprint.

Handles master password setup, login, and logout.
"""

import time
from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from core import Encryption, InvalidPasswordError, EncryptionError, Database
from core.database import get_setting


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def init_database():
    """Initialize the database with the encryption key."""
    db_key = Encryption.get_db_key()
    Database.set_key(db_key)
    Database.initialize()


def cleanup_expired_trash():
    """
    Permanently delete folders that have been in trash longer than the retention period.
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
            print(f"Trash cleanup: permanently deleted {len(expired_folders)} expired folder(s)")
    except Exception as e:
        print(f"Trash cleanup error: {e}")


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
        
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        
        if password != confirm:
            errors.append("Passwords do not match.")
        
        if errors:
            return render_template("auth/setup.html", errors=errors)
        
        # Initialize encryption
        try:
            Encryption.initialize(password)
            init_database()
            session["authenticated"] = True
            session.permanent = True
            flash("Master password created successfully.", "success")
            return redirect(url_for("main.create_archive"))
        except EncryptionError as e:
            return render_template("auth/setup.html", errors=[str(e)])
    
    return render_template("auth/setup.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Login with master password.
    
    Redirects to setup if not initialized.
    """
    # Redirect if setup needed
    if not Encryption.is_initialized():
        return redirect(url_for("auth.setup"))
    
    # Already logged in
    if session.get("authenticated") and Encryption.is_unlocked():
        return redirect(url_for("main.index"))
    
    if request.method == "POST":
        password = request.form.get("password", "")
        
        try:
            Encryption.unlock(password)
            init_database()
            cleanup_expired_trash()
            session["authenticated"] = True
            session.permanent = True
            return redirect(url_for("main.index"))
        except InvalidPasswordError:
            return render_template("auth/login.html", error="Invalid password.")
        except EncryptionError as e:
            return render_template("auth/login.html", error=str(e))
    
    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Log out and lock encryption."""
    Database.close()
    Encryption.lock()
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
