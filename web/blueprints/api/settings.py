"""
MailRepo API - Settings endpoints.

Handles application settings like trash retention.
"""

from flask import jsonify, request
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
