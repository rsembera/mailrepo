"""
MailRepo API - Folder Routes

Handles all /api/folders/* endpoints for managing archive folders.
"""

import time
from flask import request, jsonify
from core import Database
from core import Config
from . import api_bp


@api_bp.route("/folders", methods=["GET"])
def list_folders():
    """Get all archive folders."""
    folders = Database.fetchall(
        "SELECT id, name, parent_id, color, deleted_at, created_at FROM folders ORDER BY name"
    )
    return jsonify({"folders": [dict(f) for f in folders]})


@api_bp.route("/folders", methods=["POST"])
def create_folder():
    """Create a new archive folder."""
    data = request.get_json()
    
    name = data.get("name", "").strip()
    parent_id = data.get("parent_id")
    
    if not name:
        return jsonify({"error": "Folder name is required"}), 400
    
    if len(name) > 100:
        return jsonify({"error": "Folder name must be 100 characters or less"}), 400

    # Check for duplicate name at same level (excluding trashed folders)
    if parent_id:
        existing = Database.fetchone(
            "SELECT id FROM folders WHERE name = ? AND parent_id = ? AND deleted_at IS NULL",
            (name, parent_id)
        )
    else:
        existing = Database.fetchone(
            "SELECT id FROM folders WHERE name = ? AND parent_id IS NULL AND deleted_at IS NULL",
            (name,)
        )
    
    if existing:
        return jsonify({"error": "A folder with this name already exists"}), 400
    
    cursor = Database.execute(
        "INSERT INTO folders (name, parent_id) VALUES (?, ?)",
        (name, parent_id)
    )
    Database.commit()
    
    return jsonify({
        "folder": {
            "id": cursor.lastrowid,
            "name": name,
            "parent_id": parent_id,
        }
    }), 201


@api_bp.route("/folders/<int:folder_id>", methods=["GET"])
def get_folder(folder_id):
    """Get a single folder."""
    folder = Database.fetchone(
        "SELECT id, name, parent_id, created_at FROM folders WHERE id = ?",
        (folder_id,)
    )
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    return jsonify({"folder": dict(folder)})


@api_bp.route("/folders/<int:folder_id>", methods=["DELETE"])
def delete_folder(folder_id):
    """Soft-delete a folder (move to trash)."""
    folder = Database.fetchone("SELECT id FROM folders WHERE id = ?", (folder_id,))
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    now = int(time.time())
    Database.execute(
        "UPDATE folders SET deleted_at = ? WHERE id = ?",
        (now, folder_id)
    )
    Database.execute(
        "UPDATE folders SET deleted_at = ? WHERE parent_id = ?",
        (now, folder_id)
    )
    Database.commit()
    return jsonify({"success": True})


@api_bp.route("/folders/<int:folder_id>", methods=["PATCH"])
def update_folder(folder_id):
    """Update folder properties (name, color, parent_id)."""
    folder = Database.fetchone("SELECT id, name FROM folders WHERE id = ?", (folder_id,))
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    data = request.get_json()
    updates = []
    params = []

    if "name" in data:
        name = data["name"].strip()
        if not name:
            return jsonify({"error": "Folder name cannot be empty"}), 400
        if len(name) > 100:
            return jsonify({"error": "Folder name must be 100 characters or less"}), 400
        updates.append("name = ?")
        params.append(name)
    
    if "color" in data:
        updates.append("color = ?")
        params.append(data["color"])
    
    if "parent_id" in data:
        new_parent_id = data["parent_id"]
        
        if new_parent_id == folder_id:
            return jsonify({"error": "Cannot move folder into itself"}), 400
        
        if new_parent_id is not None:
            def is_descendant(parent_id, target_id):
                children = Database.fetchall(
                    "SELECT id FROM folders WHERE parent_id = ? AND deleted_at IS NULL",
                    (parent_id,)
                )
                for child in children:
                    if child["id"] == target_id:
                        return True
                    if is_descendant(child["id"], target_id):
                        return True
                return False
            
            if is_descendant(folder_id, new_parent_id):
                return jsonify({"error": "Cannot move folder into one of its subfolders"}), 400
            
            new_parent = Database.fetchone(
                "SELECT id, deleted_at FROM folders WHERE id = ?",
                (new_parent_id,)
            )
            if not new_parent or new_parent["deleted_at"]:
                return jsonify({"error": "Destination folder not found"}), 404
        
        updates.append("parent_id = ?")
        params.append(new_parent_id)
    
    if not updates:
        return jsonify({"error": "No updates provided"}), 400
    
    params.append(folder_id)
    Database.execute(
        f"UPDATE folders SET {', '.join(updates)} WHERE id = ?",
        tuple(params)
    )
    Database.commit()
    return jsonify({"success": True})


@api_bp.route("/folders/<int:folder_id>/restore", methods=["POST"])
def restore_folder(folder_id):
    """Restore a folder from trash."""
    folder = Database.fetchone(
        "SELECT id, name, parent_id, deleted_at FROM folders WHERE id = ?",
        (folder_id,)
    )
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    if not folder["deleted_at"]:
        return jsonify({"error": "Folder is not in trash"}), 400
    
    target_parent_id = folder["parent_id"]
    
    if target_parent_id:
        parent = Database.fetchone(
            "SELECT id, deleted_at FROM folders WHERE id = ?",
            (target_parent_id,)
        )
        if not parent or parent["deleted_at"]:
            target_parent_id = None
    
    folder_name = folder["name"]
    if target_parent_id:
        conflict = Database.fetchone(
            "SELECT id FROM folders WHERE name = ? AND parent_id = ? AND deleted_at IS NULL",
            (folder_name, target_parent_id)
        )
    else:
        conflict = Database.fetchone(
            "SELECT id FROM folders WHERE name = ? AND parent_id IS NULL AND deleted_at IS NULL",
            (folder_name,)
        )

    if conflict:
        base_name = folder_name
        counter = 2
        while counter <= 100:
            new_name = f"{base_name} ({counter})"
            if target_parent_id:
                existing = Database.fetchone(
                    "SELECT id FROM folders WHERE name = ? AND parent_id = ? AND deleted_at IS NULL",
                    (new_name, target_parent_id)
                )
            else:
                existing = Database.fetchone(
                    "SELECT id FROM folders WHERE name = ? AND parent_id IS NULL AND deleted_at IS NULL",
                    (new_name,)
                )
            if not existing:
                folder_name = new_name
                break
            counter += 1
        else:
            return jsonify({"error": "Could not generate unique folder name"}), 500
    
    # Restore the folder itself
    Database.execute(
        "UPDATE folders SET deleted_at = NULL, parent_id = ?, name = ? WHERE id = ?",
        (target_parent_id, folder_name, folder_id)
    )
    
    # Recursively restore all descendants
    def restore_descendants(parent_id):
        children = Database.fetchall(
            "SELECT id FROM folders WHERE parent_id = ?",
            (parent_id,)
        )
        for child in children:
            Database.execute(
                "UPDATE folders SET deleted_at = NULL WHERE id = ?",
                (child["id"],)
            )
            restore_descendants(child["id"])
    
    restore_descendants(folder_id)
    Database.commit()
    
    return jsonify({
        "success": True,
        "folder": {
            "id": folder_id,
            "name": folder_name,
            "renamed": folder_name != folder["name"]
        }
    })


@api_bp.route("/folders/<int:folder_id>/permanent", methods=["DELETE"])
def permanently_delete_folder(folder_id):
    """Permanently delete a folder from trash."""
    folder = Database.fetchone(
        "SELECT id, deleted_at FROM folders WHERE id = ?",
        (folder_id,)
    )
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    if not folder["deleted_at"]:
        return jsonify({"error": "Folder must be in trash before permanent deletion"}), 400
    
    messages = Database.fetchall(
        "SELECT filepath FROM messages WHERE folder_id = ? OR folder_id IN (SELECT id FROM folders WHERE parent_id = ?)",
        (folder_id, folder_id)
    )
    
    for msg in messages:
        try:
            filepath = Config.get_base_path() / msg["filepath"]
            if filepath.exists():
                filepath.unlink()
        except Exception as e:
            print(f"Warning: Could not delete file {msg['filepath']}: {e}")
    
    try:
        folder_path = Config.get_archive_path() / str(folder_id)
        if folder_path.exists() and folder_path.is_dir():
            folder_path.rmdir()
    except:
        pass
    
    Database.execute("DELETE FROM folders WHERE id = ? OR parent_id = ?", (folder_id, folder_id))
    Database.commit()
    return jsonify({"success": True})


@api_bp.route("/trash/empty", methods=["POST"])
def empty_trash():
    """Permanently delete all items in trash."""
    trashed = Database.fetchall(
        "SELECT id FROM folders WHERE deleted_at IS NOT NULL"
    )
    
    if not trashed:
        return jsonify({"success": True, "deleted": 0})
    
    folder_ids = [f["id"] for f in trashed]
    placeholders = ",".join(["?" for _ in folder_ids])
    
    messages = Database.fetchall(
        f"SELECT filepath FROM messages WHERE folder_id IN ({placeholders})",
        tuple(folder_ids)
    )
    
    for msg in messages:
        try:
            filepath = Config.get_base_path() / msg["filepath"]
            if filepath.exists():
                filepath.unlink()
        except Exception as e:
            print(f"Warning: Could not delete file {msg['filepath']}: {e}")
    
    Database.execute(
        f"DELETE FROM folders WHERE id IN ({placeholders})",
        tuple(folder_ids)
    )
    Database.commit()
    
    return jsonify({"success": True, "deleted": len(trashed)})
