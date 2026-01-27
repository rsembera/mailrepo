"""
MailRepo API - Import/Export Routes

Handles mbox and eml import, and folder export.
"""

import io
import zipfile
from pathlib import Path
from flask import request, jsonify, send_file
from core import Database, Config, Encryption
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


@api_bp.route("/import/email", methods=["POST"])
def get_import_email():
    """
    Fetch full email content from an import source.
    
    Request body:
        sourcePath: Path to mbox file or directory
        uid: Email UID (e.g., "mbox-5", "eml-0", "apple-3")
        importType: 'mbox', 'apple-mbox', or 'eml'
        folderPath: (optional) For apple-mbox, path to specific .mbox folder
    
    Returns:
        email: Full email data including body
    """
    import email as email_lib
    from email.header import decode_header
    from email.utils import parsedate_to_datetime
    from .email_parser import get_raw_email_from_import, _parse_apple_mbox, _parse_eml_directory
    
    data = request.get_json() or {}
    source_path = data.get("sourcePath", "").strip()
    uid = data.get("uid", "").strip()
    import_type = data.get("importType", "mbox")
    folder_path = data.get("folderPath", "")
    
    if not source_path:
        return jsonify({"error": "Source path is required"}), 400
    if not uid:
        return jsonify({"error": "UID is required"}), 400
    
    source_path = Path(source_path).expanduser()
    if not source_path.exists():
        return jsonify({"error": "Source not found"}), 404
    
    def decode_header_value(header):
        if not header:
            return ""
        try:
            parts = decode_header(header)
            decoded = []
            for content, charset in parts:
                if isinstance(content, bytes):
                    decoded.append(content.decode(charset or "utf-8", errors="replace"))
                else:
                    decoded.append(content)
            return " ".join(decoded)
        except:
            return str(header)
    
    def get_email_body(msg):
        """Extract email body (prefer HTML, fallback to plain text)."""
        html_body = None
        text_body = None
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                
                if "attachment" in content_disposition:
                    continue
                
                if content_type == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        html_body = payload.decode(charset, errors="replace")
                elif content_type == "text/plain" and not html_body:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        text_body = payload.decode(charset, errors="replace")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                content_type = msg.get_content_type()
                if content_type == "text/html":
                    html_body = payload.decode(charset, errors="replace")
                else:
                    text_body = payload.decode(charset, errors="replace")
        
        return html_body or text_body or ""
    
    def get_attachments(msg):
        """Extract attachment info from email."""
        attachments = []
        if msg.is_multipart():
            for part in msg.walk():
                content_disposition = str(part.get("Content-Disposition", ""))
                if "attachment" in content_disposition:
                    filename = part.get_filename()
                    if filename:
                        attachments.append({
                            "filename": decode_header_value(filename),
                            "content_type": part.get_content_type(),
                            "size": len(part.get_payload(decode=True) or b""),
                        })
        return attachments
    
    try:
        raw_email = None
        
        # Get raw email bytes based on import type
        if import_type == 'eml':
            # EML directory - find specific file
            if uid.startswith('eml-'):
                results = _parse_eml_directory(str(source_path))
                for r_uid, r_bytes in results:
                    if r_uid == uid:
                        raw_email = r_bytes
                        break
        elif import_type == 'apple-mbox':
            # Apple Mail export
            if folder_path:
                results = _parse_apple_mbox(folder_path)
            else:
                results = _parse_apple_mbox(str(source_path))
            for r_uid, r_bytes in results:
                if r_uid == uid:
                    raw_email = r_bytes
                    break
        else:
            # Standard mbox
            raw_email = get_raw_email_from_import(str(source_path), uid)
        
        if not raw_email:
            return jsonify({"error": "Email not found in import source"}), 404
        
        # Parse the email
        msg = email_lib.message_from_bytes(raw_email)
        
        # Parse date
        date_str = msg.get("Date", "")
        date_display = date_str
        if date_str:
            try:
                dt = parsedate_to_datetime(date_str)
                date_display = dt.strftime("%Y-%m-%d %H:%M")
            except:
                pass
        
        email_data = {
            "uid": uid,
            "subject": decode_header_value(msg.get("Subject", "(no subject)")),
            "from": decode_header_value(msg.get("From", "")),
            "to": decode_header_value(msg.get("To", "")),
            "cc": decode_header_value(msg.get("Cc", "")),
            "date": date_display,
            "body": get_email_body(msg),
            "attachments": get_attachments(msg),
        }
        
        return jsonify({"email": email_data})
        
    except Exception as e:
        return jsonify({"error": f"Failed to read email: {str(e)}"}), 500


@api_bp.route("/folders/<int:folder_id>/export", methods=["POST"])
def export_folder(folder_id):
    """Export a folder and its contents as an unencrypted ZIP file."""
    folder = Database.fetchone("SELECT id, name FROM folders WHERE id = ?", (folder_id,))
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    data = request.get_json() or {}
    include_subfolders = data.get("include_subfolders", True)
    
    # Get all folders to export (recursive if include_subfolders)
    folder_ids = [folder_id]
    folders_by_id = {folder_id: folder}
    
    if include_subfolders:
        # Recursively collect all child folders
        def collect_children(parent_id, collected):
            children = Database.fetchall(
                "SELECT id, name, parent_id FROM folders WHERE parent_id = ? AND deleted_at IS NULL",
                (parent_id,)
            )
            for child in children:
                collected.append(child["id"])
                folders_by_id[child["id"]] = child
                collect_children(child["id"], collected)
        collect_children(folder_id, folder_ids)
    
    # Build folder path lookup (folder_id -> relative path in ZIP)
    def build_path(fid, path_parts=None):
        if path_parts is None:
            path_parts = []
        f = folders_by_id.get(fid)
        if not f:
            return "/".join(reversed(path_parts))
        path_parts.append(f["name"])
        # Row objects don't support .get(), use try/except or check keys
        parent_id = f["parent_id"] if "parent_id" in f.keys() else None
        if parent_id and parent_id in folders_by_id:
            return build_path(parent_id, path_parts)
        return "/".join(reversed(path_parts))
    
    folder_paths = {fid: build_path(fid) for fid in folder_ids}
    
    # Get all messages in these folders
    placeholders = ",".join("?" * len(folder_ids))
    messages = Database.fetchall(
        f"""
        SELECT id, folder_id, subject, sender, date, filepath
        FROM messages
        WHERE folder_id IN ({placeholders})
        ORDER BY folder_id, date
        """,
        tuple(folder_ids)
    )
    
    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Track filenames to avoid duplicates within same folder
        folder_filenames = {}  # folder_id -> set of used filenames
        
        for msg in messages:
            fid = msg["folder_id"]
            if fid not in folder_filenames:
                folder_filenames[fid] = set()
            
            filepath = Config.get_base_path() / msg["filepath"]
            if not filepath.exists():
                continue
            
            try:
                # Read and decrypt the email
                raw_bytes = filepath.read_bytes()
                decrypted_bytes = Encryption.decrypt(raw_bytes)
                
                # Generate a safe filename
                subject = msg["subject"] or "no_subject"
                # Sanitize subject for filename
                safe_subject = "".join(c if c.isalnum() or c in " -_" else "_" for c in subject)[:50].strip()
                base_filename = f"{safe_subject}.eml"
                
                # Ensure uniqueness within folder
                filename = base_filename
                counter = 1
                while filename in folder_filenames[fid]:
                    name_part = base_filename[:-4]  # remove .eml
                    filename = f"{name_part}_{counter}.eml"
                    counter += 1
                folder_filenames[fid].add(filename)
                
                # Build full path in ZIP
                folder_path = folder_paths.get(fid, "")
                if folder_path:
                    zip_path = f"{folder_path}/{filename}"
                else:
                    zip_path = filename
                
                # Add to ZIP
                zf.writestr(zip_path, decrypted_bytes)
            except Exception as e:
                print(f"Error exporting message {msg['id']}: {e}")
                continue
    
    zip_buffer.seek(0)
    
    # Generate download filename
    safe_folder_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in folder["name"])[:30].strip()
    download_filename = f"{safe_folder_name}_export.zip"
    
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=download_filename
    )
