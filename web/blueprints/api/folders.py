"""
MailRepo API - Folder Routes

Handles all /api/folders/* endpoints for managing archive folders.
"""

import time
from flask import request, jsonify
from core import Database
from core import Config
from utils.log import get_logger
from . import api_bp

log = get_logger()


@api_bp.route("/folders", methods=["GET"])
def list_folders():
    """Get all archive folders."""
    folders = Database.fetchall(
        "SELECT id, name, parent_id, color, retention_date, deleted_at, created_at FROM folders ORDER BY name"
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
    folder = Database.fetchone("SELECT id, retention_date FROM folders WHERE id = ?", (folder_id,))
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    # Don't allow deleting folders that are in the retention vault
    if folder["retention_date"]:
        return jsonify({"error": "Cannot delete folders in the Retention Vault"}), 400
    
    now = int(time.time())
    
    # Recursively soft-delete folder and all descendants
    # (Retention vault folders are already detached, so they won't be affected)
    def soft_delete_recursive(parent_id):
        Database.execute(
            "UPDATE folders SET deleted_at = ? WHERE id = ?",
            (now, parent_id)
        )
        children = Database.fetchall(
            "SELECT id FROM folders WHERE parent_id = ?",
            (parent_id,)
        )
        for child in children:
            soft_delete_recursive(child["id"])
    
    soft_delete_recursive(folder_id)
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
    
    # Collect all descendant folder IDs recursively
    # (Retention vault folders are already detached when moved to vault, so they won't be included)
    def collect_descendants(parent_id):
        ids = [parent_id]
        children = Database.fetchall(
            "SELECT id FROM folders WHERE parent_id = ?",
            (parent_id,)
        )
        for child in children:
            ids.extend(collect_descendants(child["id"]))
        return ids
    
    all_folder_ids = collect_descendants(folder_id)
    placeholders = ",".join(["?" for _ in all_folder_ids])
    
    # Delete message files for all folders in the tree
    messages = Database.fetchall(
        f"SELECT filepath FROM messages WHERE folder_id IN ({placeholders})",
        tuple(all_folder_ids)
    )
    
    for msg in messages:
        try:
            filepath = Config.get_base_path() / msg["filepath"]
            if filepath.exists():
                filepath.unlink()
        except Exception as e:
            log.warning(f"Could not delete file {msg['filepath']}: {e}")
    
    # Try to remove folder directories
    for fid in all_folder_ids:
        try:
            folder_path = Config.get_archive_path() / str(fid)
            if folder_path.exists() and folder_path.is_dir():
                folder_path.rmdir()
        except:
            pass
    
    # Delete all folders (CASCADE will handle messages)
    Database.execute(f"DELETE FROM folders WHERE id IN ({placeholders})", tuple(all_folder_ids))
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
            log.warning(f"Could not delete file {msg['filepath']}: {e}")
    
    Database.execute(
        f"DELETE FROM folders WHERE id IN ({placeholders})",
        tuple(folder_ids)
    )
    Database.commit()
    
    return jsonify({"success": True, "deleted": len(trashed)})


# ============================================================
# RETENTION VAULT ENDPOINTS
# ============================================================


@api_bp.route("/folders/vault", methods=["GET"])
def list_vault_folders():
    """Get all folders in the Retention Vault (have retention_date set)."""
    now = int(time.time())
    
    # Get top-level vault folders (those with retention_date set, not deleted)
    # We need to return the full tree for each, so get all folders first
    all_folders = Database.fetchall(
        """SELECT id, name, parent_id, color, retention_date, deleted_at 
           FROM folders 
           WHERE deleted_at IS NULL"""
    )
    
    # Build a map for quick lookups
    folder_map = {f["id"]: dict(f) for f in all_folders}
    
    # Find top-level vault folders (have retention_date, and parent doesn't have retention_date)
    vault_folders = []
    for f in all_folders:
        if f["retention_date"] is not None:
            # Check if this is a top-level vault folder (parent not in vault)
            parent = folder_map.get(f["parent_id"])
            if parent is None or parent["retention_date"] is None:
                # This is a top-level vault folder
                # Count emails in this folder and all descendants
                def count_tree_emails(folder_id):
                    count = Database.fetchone(
                        "SELECT COUNT(*) as cnt FROM messages WHERE folder_id = ? AND deleted_at IS NULL",
                        (folder_id,)
                    )["cnt"]
                    children = [fid for fid, data in folder_map.items() 
                               if data["parent_id"] == folder_id]
                    for child_id in children:
                        count += count_tree_emails(child_id)
                    return count
                
                email_count = count_tree_emails(f["id"])
                
                vault_folders.append({
                    "id": f["id"],
                    "name": f["name"],
                    "color": f["color"],
                    "retention_date": f["retention_date"],
                    "email_count": email_count,
                    "is_overdue": f["retention_date"] < now
                })
    
    overdue_count = sum(1 for f in vault_folders if f["is_overdue"])
    
    return jsonify({
        "folders": vault_folders,
        "overdue_count": overdue_count
    })


@api_bp.route("/folders/vault/overdue-count", methods=["GET"])
def vault_overdue_count():
    """Get count of overdue folders in vault (for login alert badge)."""
    now = int(time.time())
    
    # Count top-level vault folders that are overdue
    all_folders = Database.fetchall(
        """SELECT id, parent_id, retention_date 
           FROM folders 
           WHERE retention_date IS NOT NULL AND deleted_at IS NULL"""
    )
    
    folder_map = {f["id"]: dict(f) for f in all_folders}
    
    count = 0
    for f in all_folders:
        if f["retention_date"] < now:
            # Check if top-level vault folder
            parent = folder_map.get(f["parent_id"])
            if parent is None or parent.get("retention_date") is None:
                count += 1
    
    return jsonify({"count": count})


@api_bp.route("/folders/<int:folder_id>/vault", methods=["POST"])
def move_to_vault(folder_id):
    """Move a folder to the Retention Vault with a deletion date."""
    folder = Database.fetchone(
        "SELECT id, deleted_at, retention_date FROM folders WHERE id = ?",
        (folder_id,)
    )
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    if folder["deleted_at"]:
        return jsonify({"error": "Cannot move trashed folder to vault"}), 400
    if folder["retention_date"]:
        return jsonify({"error": "Folder is already in vault"}), 400
    
    data = request.get_json()
    retention_date = data.get("retention_date")
    
    if not retention_date:
        return jsonify({"error": "Retention date is required"}), 400
    
    try:
        retention_date = int(retention_date)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid retention date"}), 400
    
    # Set retention_date on this folder and all descendants
    # Also detach from parent (set parent_id = NULL) so it's not affected by parent deletion
    def set_retention_recursive(parent_id, is_root=False):
        if is_root:
            # Detach the root folder being moved to vault from its parent
            Database.execute(
                "UPDATE folders SET retention_date = ?, parent_id = NULL WHERE id = ?",
                (retention_date, parent_id)
            )
        else:
            Database.execute(
                "UPDATE folders SET retention_date = ? WHERE id = ?",
                (retention_date, parent_id)
            )
        children = Database.fetchall(
            "SELECT id FROM folders WHERE parent_id = ? AND deleted_at IS NULL",
            (parent_id,)
        )
        for child in children:
            set_retention_recursive(child["id"], is_root=False)
    
    set_retention_recursive(folder_id, is_root=True)
    Database.commit()
    
    return jsonify({"success": True})


@api_bp.route("/folders/<int:folder_id>/vault/restore", methods=["POST"])
def restore_from_vault(folder_id):
    """Restore a folder from the Retention Vault back to the archive."""
    folder = Database.fetchone(
        "SELECT id, parent_id, deleted_at, retention_date FROM folders WHERE id = ?",
        (folder_id,)
    )
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    if folder["deleted_at"]:
        return jsonify({"error": "Folder is in trash, not vault"}), 400
    if not folder["retention_date"]:
        return jsonify({"error": "Folder is not in vault"}), 400
    
    data = request.get_json() or {}
    destination_id = data.get("destination_id")  # None means root
    
    # Validate destination if provided
    if destination_id is not None:
        dest = Database.fetchone(
            "SELECT id, deleted_at, retention_date FROM folders WHERE id = ?",
            (destination_id,)
        )
        if not dest:
            return jsonify({"error": "Destination folder not found"}), 404
        if dest["deleted_at"]:
            return jsonify({"error": "Cannot restore to trashed folder"}), 400
        if dest["retention_date"]:
            return jsonify({"error": "Cannot restore to a folder in vault"}), 400
    
    # Clear retention_date on this folder and all descendants
    def clear_retention_recursive(parent_id):
        Database.execute(
            "UPDATE folders SET retention_date = NULL WHERE id = ?",
            (parent_id,)
        )
        children = Database.fetchall(
            "SELECT id FROM folders WHERE parent_id = ?",
            (parent_id,)
        )
        for child in children:
            clear_retention_recursive(child["id"])
    
    clear_retention_recursive(folder_id)
    
    # Move to new parent if specified
    if destination_id != folder["parent_id"]:
        Database.execute(
            "UPDATE folders SET parent_id = ? WHERE id = ?",
            (destination_id, folder_id)
        )
    
    Database.commit()
    
    return jsonify({"success": True})


@api_bp.route("/folders/<int:folder_id>/permadelete", methods=["DELETE"])
def permadelete_vault_folder(folder_id):
    """Permanently delete a folder from the Retention Vault (must be overdue)."""
    now = int(time.time())
    
    folder = Database.fetchone(
        "SELECT id, deleted_at, retention_date FROM folders WHERE id = ?",
        (folder_id,)
    )
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    if folder["deleted_at"]:
        return jsonify({"error": "Folder is in trash, use permanent delete from trash"}), 400
    if not folder["retention_date"]:
        return jsonify({"error": "Folder is not in vault"}), 400
    if folder["retention_date"] > now:
        return jsonify({"error": "Folder is not yet overdue"}), 400
    
    # Collect all descendant folder IDs recursively
    def collect_descendants(parent_id):
        ids = [parent_id]
        children = Database.fetchall(
            "SELECT id FROM folders WHERE parent_id = ?",
            (parent_id,)
        )
        for child in children:
            ids.extend(collect_descendants(child["id"]))
        return ids
    
    all_folder_ids = collect_descendants(folder_id)
    placeholders = ",".join(["?" for _ in all_folder_ids])
    
    # Count emails before deletion
    email_count = Database.fetchone(
        f"SELECT COUNT(*) as cnt FROM messages WHERE folder_id IN ({placeholders})",
        tuple(all_folder_ids)
    )["cnt"]
    
    # Delete message files for all folders in the tree
    messages = Database.fetchall(
        f"SELECT filepath FROM messages WHERE folder_id IN ({placeholders})",
        tuple(all_folder_ids)
    )
    
    for msg in messages:
        try:
            filepath = Config.get_base_path() / msg["filepath"]
            if filepath.exists():
                filepath.unlink()
        except Exception as e:
            log.warning(f"Could not delete file {msg['filepath']}: {e}")
    
    # Try to remove folder directories
    for fid in all_folder_ids:
        try:
            folder_path = Config.get_archive_path() / str(fid)
            if folder_path.exists() and folder_path.is_dir():
                folder_path.rmdir()
        except:
            pass
    
    # Delete all folders (CASCADE will handle messages)
    Database.execute(f"DELETE FROM folders WHERE id IN ({placeholders})", tuple(all_folder_ids))
    Database.commit()
    
    return jsonify({"success": True, "emails_deleted": email_count})


@api_bp.route("/folders/batch-permadelete", methods=["POST"])
def batch_permadelete_vault():
    """Permanently delete multiple folders from the Retention Vault."""
    now = int(time.time())
    
    data = request.get_json()
    folder_ids = data.get("folder_ids", [])
    
    if not folder_ids:
        return jsonify({"error": "No folders specified"}), 400
    
    # Validate all folders
    total_emails = 0
    all_folder_ids_to_delete = []
    
    for folder_id in folder_ids:
        folder = Database.fetchone(
            "SELECT id, deleted_at, retention_date FROM folders WHERE id = ?",
            (folder_id,)
        )
        if not folder:
            return jsonify({"error": f"Folder {folder_id} not found"}), 404
        if folder["deleted_at"]:
            return jsonify({"error": f"Folder {folder_id} is in trash"}), 400
        if not folder["retention_date"]:
            return jsonify({"error": f"Folder {folder_id} is not in vault"}), 400
        if folder["retention_date"] > now:
            return jsonify({"error": f"Folder {folder_id} is not yet overdue"}), 400
        
        # Collect descendants
        def collect_descendants(parent_id):
            ids = [parent_id]
            children = Database.fetchall(
                "SELECT id FROM folders WHERE parent_id = ?",
                (parent_id,)
            )
            for child in children:
                ids.extend(collect_descendants(child["id"]))
            return ids
        
        all_folder_ids_to_delete.extend(collect_descendants(folder_id))
    
    # Deduplicate (in case of nested selections)
    all_folder_ids_to_delete = list(set(all_folder_ids_to_delete))
    placeholders = ",".join(["?" for _ in all_folder_ids_to_delete])
    
    # Count emails
    total_emails = Database.fetchone(
        f"SELECT COUNT(*) as cnt FROM messages WHERE folder_id IN ({placeholders})",
        tuple(all_folder_ids_to_delete)
    )["cnt"]
    
    # Delete message files
    messages = Database.fetchall(
        f"SELECT filepath FROM messages WHERE folder_id IN ({placeholders})",
        tuple(all_folder_ids_to_delete)
    )
    
    for msg in messages:
        try:
            filepath = Config.get_base_path() / msg["filepath"]
            if filepath.exists():
                filepath.unlink()
        except Exception as e:
            log.warning(f"Could not delete file {msg['filepath']}: {e}")
    
    # Try to remove folder directories
    for fid in all_folder_ids_to_delete:
        try:
            folder_path = Config.get_archive_path() / str(fid)
            if folder_path.exists() and folder_path.is_dir():
                folder_path.rmdir()
        except:
            pass
    
    # Delete all folders
    Database.execute(f"DELETE FROM folders WHERE id IN ({placeholders})", tuple(all_folder_ids_to_delete))
    Database.commit()
    
    return jsonify({
        "success": True,
        "folders_deleted": len(folder_ids),
        "emails_deleted": total_emails
    })
