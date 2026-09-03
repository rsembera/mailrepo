"""
MailRepo API - Settings endpoints.

Handles application settings like trash retention and session timeout.
"""

import time

from flask import jsonify, request, session

from core.database import Database, get_setting, set_setting

from . import api_bp


@api_bp.route("/settings/trash-retention", methods=["GET"])
def get_trash_retention():
    """Get the trash retention setting."""
    value = get_setting("trash_retention_days", "0")
    return jsonify({"value": value})


@api_bp.route("/settings/trash-retention", methods=["POST"])
def set_trash_retention():
    """Set the trash retention setting."""
    data = request.get_json()
    value = str(data.get("value", "0"))

    # Validate value
    if value not in ("0", "7", "30", "90", "365"):
        return jsonify({"error": "Invalid retention value"}), 400

    set_setting("trash_retention_days", value)
    Database.commit()

    return jsonify({"success": True, "value": value})


# ============================================================================
# SESSION TIMEOUT SETTINGS
# ============================================================================


@api_bp.route("/settings/session-timeout", methods=["GET"])
def get_session_timeout():
    """Get the session timeout setting."""
    value = get_setting("session_timeout", "30")
    return jsonify({"value": value})


@api_bp.route("/settings/session-timeout", methods=["POST"])
def set_session_timeout():
    """Set the session timeout setting."""
    data = request.get_json()
    value = str(data.get("value", "30"))

    # Validate value
    if value not in ("15", "30", "60", "120", "0"):
        return jsonify({"error": "Invalid timeout value"}), 400

    set_setting("session_timeout", value)
    Database.commit()

    return jsonify({"success": True, "value": value})


@api_bp.route("/session-status", methods=["GET"])
def session_status():
    """Return session timeout status for frontend warning system."""
    if not session.get("authenticated"):
        return jsonify({"logged_in": False})

    try:
        timeout_minutes = int(get_setting("session_timeout", "30"))
    except (ValueError, TypeError):
        timeout_minutes = 30

    # If timeout is 0 ("Never"), no warning needed
    if timeout_minutes == 0:
        return jsonify(
            {
                "logged_in": True,
                "timeout_minutes": 0,
                "seconds_remaining": None,
                "warning_needed": False,
            }
        )

    last_activity = session.get("last_activity", time.time())
    elapsed = time.time() - last_activity
    timeout_seconds = timeout_minutes * 60
    seconds_remaining = max(0, timeout_seconds - elapsed)

    # Warning thresholds (proportional to timeout):
    # 15 min -> warn at 2 min (120s)
    # 30 min -> warn at 3 min (180s)
    # 60+ min -> warn at 5 min (300s)
    if timeout_minutes <= 15:
        warning_threshold = 120
    elif timeout_minutes <= 30:
        warning_threshold = 180
    else:
        warning_threshold = 300

    return jsonify(
        {
            "logged_in": True,
            "timeout_minutes": timeout_minutes,
            "seconds_remaining": int(seconds_remaining),
            "warning_threshold": warning_threshold,
            "warning_needed": seconds_remaining <= warning_threshold and seconds_remaining > 0,
        }
    )


# ============================================================================
# THREAD STAGING SETTINGS
# ============================================================================

# Allowed values for the maximum thread size when using Stage Thread.
# This is the user-facing choice list; the POST handler rejects anything
# outside it. find_thread additionally clamps to its own hard ceiling, so
# these two layers together mean no input path can make a thread walk run
# unbounded against the mail server.
THREAD_MAX_MESSAGES_CHOICES = ("100", "250", "500", "1000", "2000")
THREAD_MAX_MESSAGES_DEFAULT = "500"


@api_bp.route("/settings/thread-max-messages", methods=["GET"])
def get_thread_max_messages():
    """Get the maximum-thread-size setting for Stage Thread."""
    value = get_setting("thread_max_messages", THREAD_MAX_MESSAGES_DEFAULT)
    return jsonify({"value": value})


@api_bp.route("/settings/thread-max-messages", methods=["POST"])
def set_thread_max_messages():
    """Set the maximum-thread-size setting for Stage Thread."""
    data = request.get_json()
    value = str(data.get("value", THREAD_MAX_MESSAGES_DEFAULT))

    # Validate against the fixed allowed set — protects the mail server
    # from a hand-crafted POST with an absurd value.
    if value not in THREAD_MAX_MESSAGES_CHOICES:
        return jsonify({"error": "Invalid thread size value"}), 400

    set_setting("thread_max_messages", value)
    Database.commit()

    return jsonify({"success": True, "value": value})


@api_bp.route("/keepalive", methods=["POST"])
def keepalive():
    """Extend session when user clicks 'Stay Logged In'."""
    if not session.get("authenticated"):
        return jsonify({"success": False, "error": "Not logged in"}), 401

    # Update last activity timestamp
    session["last_activity"] = time.time()
    return jsonify({"success": True})


# ============================================================================
# DATABASE RESET
# ============================================================================


@api_bp.route("/reset_database", methods=["POST"])
def reset_database():
    """
    Reset the entire database and delete all user data.
    Requires password confirmation and typing 'RESET' to confirm.
    """
    import shutil

    from core.config import Config
    from core.encryption import Encryption

    data = request.get_json()
    password = data.get("password", "")
    confirmation = data.get("confirmation", "")

    # Validate confirmation text
    if confirmation != "RESET":
        return jsonify({"success": False, "error": "Please type RESET to confirm"}), 400

    # Validate password
    try:
        Encryption.unlock(password)
    except Exception:
        return jsonify({"success": False, "error": "Incorrect password"}), 401

    try:
        # Close database connection
        Database.close()

        # Delete database file
        db_path = Config.get_database_path()
        if db_path.exists():
            db_path.unlink()

        # Delete WAL and SHM files if they exist
        for ext in ["-wal", "-shm"]:
            wal_path = db_path.parent / f"{db_path.name}{ext}"
            if wal_path.exists():
                wal_path.unlink()

        # Delete archive directory contents
        archive_path = Config.get_archive_path()
        if archive_path.exists():
            shutil.rmtree(archive_path)
            archive_path.mkdir(parents=True, exist_ok=True)

        # Delete backups directory contents
        backups_path = Config.get_backup_path()
        if backups_path.exists():
            shutil.rmtree(backups_path)
            backups_path.mkdir(parents=True, exist_ok=True)

        # Delete salt file (forces new password setup)
        salt_path = Config.get_salt_path()
        if salt_path.exists():
            salt_path.unlink()

        # Delete a stale secret key file from before 1.1 (no longer used)
        secret_key_path = Config.get_secret_key_path()
        if secret_key_path.exists():
            secret_key_path.unlink()

        # Note: Don't call Encryption.lock() here — clearing the in-memory
        # keys while Flask is still processing the response can cause a
        # segfault in SQLCipher. The keys will be replaced when the user
        # sets up a new password via the first-run flow.

        # Clear session to force re-login
        session.clear()

        return jsonify(
            {
                "success": True,
                "message": "Database reset complete. You will be redirected to set up a new password.",
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
