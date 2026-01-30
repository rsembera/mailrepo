"""
MailRepo API - Settings endpoints.

Handles application settings like trash retention and session timeout.
"""

import time
from flask import jsonify, request, session
from core.database import get_setting, set_setting, Database
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
        return jsonify({
            "logged_in": True,
            "timeout_minutes": 0,
            "seconds_remaining": None,
            "warning_needed": False
        })
    
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
    
    return jsonify({
        "logged_in": True,
        "timeout_minutes": timeout_minutes,
        "seconds_remaining": int(seconds_remaining),
        "warning_threshold": warning_threshold,
        "warning_needed": seconds_remaining <= warning_threshold and seconds_remaining > 0
    })


@api_bp.route("/keepalive", methods=["POST"])
def keepalive():
    """Extend session when user clicks 'Stay Logged In'."""
    if not session.get("authenticated"):
        return jsonify({"success": False, "error": "Not logged in"}), 401
    
    # Update last activity timestamp
    session["last_activity"] = time.time()
    return jsonify({"success": True})
