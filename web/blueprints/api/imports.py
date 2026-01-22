"""
MailRepo API - Import/Export Routes

Handles mbox and eml import, and folder export.
"""

from pathlib import Path
from flask import request, jsonify
from core import Database
from core import scan_mbox_file, import_mbox_file, import_eml_file
from . import api_bp


@api_bp.route("/import/mbox/scan", methods=["POST"])
def scan_mbox():
    """Scan an mbox file and return summary."""
    data = request.get_json()
    mbox_path = data.get("path", "").strip()
    
    if not mbox_path:
        return jsonify({"error": "Path is required"}), 400
    
    path = Path(mbox_path).expanduser()
    if not path.exists():
        return jsonify({"error": "File not found"}), 404
    
    try:
        result = scan_mbox_file(path)
        return jsonify(result)
    except ImportError as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/import/mbox", methods=["POST"])
def import_mbox():
    """Import an mbox file into a folder."""
    data = request.get_json()
    mbox_path = data.get("path", "").strip()
    folder_id = data.get("folder_id")
    
    if not mbox_path:
        return jsonify({"error": "Path is required"}), 400
    if not folder_id:
        return jsonify({"error": "Folder ID is required"}), 400
    
    path = Path(mbox_path).expanduser()
    if not path.exists():
        return jsonify({"error": "File not found"}), 404
    
    folder = Database.fetchone("SELECT id FROM folders WHERE id = ?", (folder_id,))
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    try:
        result = import_mbox_file(path, folder_id)
        return jsonify({
            "success": True,
            "total": result["total"],
            "imported": result["success_count"],
            "failed": result["failed_count"],
            "errors": result["errors"][:10],
        })
    except ImportError as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/import/eml", methods=["POST"])
def import_eml():
    """Import a single .eml file into a folder."""
    data = request.get_json()
    eml_path = data.get("path", "").strip()
    folder_id = data.get("folder_id")
    
    if not eml_path:
        return jsonify({"error": "Path is required"}), 400
    if not folder_id:
        return jsonify({"error": "Folder ID is required"}), 400
    
    path = Path(eml_path).expanduser()
    if not path.exists():
        return jsonify({"error": "File not found"}), 404
    
    folder = Database.fetchone("SELECT id FROM folders WHERE id = ?", (folder_id,))
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    result = import_eml_file(path, folder_id)
    
    if result["success"]:
        Database.commit()
        return jsonify({"success": True, "subject": result["subject"]})
    else:
        return jsonify({"success": False, "error": result["error"]}), 500


@api_bp.route("/folders/<int:folder_id>/export", methods=["POST"])
def export_folder(folder_id):
    """Export a folder as ZIP file (not yet implemented)."""
    folder = Database.fetchone("SELECT id, name FROM folders WHERE id = ?", (folder_id,))
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    # TODO: Implement ZIP export
    return jsonify({"error": "Export not yet implemented"}), 501
