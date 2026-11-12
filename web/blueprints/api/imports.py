"""
MailRepo API - Import/Export Routes

Handles mbox and eml import, and folder export.
"""

import io
import zipfile
from pathlib import Path

from flask import jsonify, request, send_file

from core import Config, Database, Encryption, scan_mbox_file
from core.message_view import attachment_at, view_fields
from utils.log import get_logger
from web.responses import attachment_response

from . import api_bp

log = get_logger()


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


def _locate_import_raw_email(
    source_path, uid: str, import_type: str, folder_path: str, email_source_path: str
) -> bytes | None:
    """Find one email's raw bytes inside a mounted import.

    Shared by the preview and view-source routes. Direct file paths
    (.eml, .emlx) are read as-is; everything else is a UID lookup that
    depends on the import type.
    """
    from .email_parser import _parse_eml_directory, get_raw_email_from_import

    raw_email = None

    # If we have a direct path to the email file, use it (EML files, Apple emlx)
    # But NOT for mbox files - those need UID-based lookup
    if email_source_path:
        email_path = Path(email_source_path).expanduser()
        if email_path.exists() and email_path.is_file():
            suffix = email_path.suffix.lower()
            # Only use direct file reading for individual email files
            if suffix == ".emlx":
                # Parse Apple .emlx format
                with open(email_path, "rb") as f:
                    content = f.read()
                first_newline = content.find(b"\n")
                if first_newline > 0:
                    email_content = content[first_newline + 1 :]
                    plist_marker = email_content.rfind(b"<?xml version=")
                    if plist_marker > 0:
                        email_content = email_content[:plist_marker]
                    raw_email = email_content
            elif suffix == ".eml":
                # Regular .eml file
                with open(email_path, "rb") as f:
                    raw_email = f.read()
            # For mbox files, fall through to UID-based lookup below

    # Fallback lookups - only if direct file reading didn't work
    if not raw_email:
        if import_type == "eml":
            # EML directory - find specific file
            if uid.startswith("eml-"):
                results = _parse_eml_directory(str(source_path))
                for r_uid, r_bytes in results:
                    if r_uid == uid:
                        raw_email = r_bytes
                        break
        elif import_type == "apple-mbox":
            # Apple Mail export - parse directly using same logic as filesystem.py
            import mailbox
            import os

            # Use folder_path which points to the specific .mbox directory
            mbox_dir = folder_path if folder_path else str(source_path)

            # Check for mbox file inside the .mbox directory
            mbox_file = os.path.join(mbox_dir, "mbox")
            if os.path.isfile(mbox_file):
                # UID format from filesystem.py: f"apple-{basename}-{i}"
                # e.g., "apple-mbox-0" where "mbox" is basename of the mbox file
                try:
                    mbox = mailbox.mbox(mbox_file)
                    for i, message in enumerate(mbox):
                        expected_uid = f"apple-{os.path.basename(mbox_file)}-{i}"
                        if expected_uid == uid:
                            raw_email = message.as_bytes()
                            break
                except Exception:
                    pass

            # Check for Messages directory with .emlx files
            if not raw_email:
                messages_dir = os.path.join(mbox_dir, "Messages")
                if os.path.isdir(messages_dir):
                    # UID format: f"emlx-{filename}"
                    for entry in os.scandir(messages_dir):
                        if entry.name.endswith(".emlx") and entry.is_file():
                            expected_uid = f"emlx-{entry.name}"
                            if expected_uid == uid:
                                try:
                                    with open(entry.path, "rb") as f:
                                        content = f.read()
                                    # .emlx format: first line is byte count, then email, then plist
                                    first_newline = content.find(b"\n")
                                    if first_newline > 0:
                                        email_content = content[first_newline + 1 :]
                                        plist_marker = email_content.rfind(b"<?xml version=")
                                        if plist_marker > 0:
                                            email_content = email_content[:plist_marker]
                                        raw_email = email_content
                                        break
                                except Exception:
                                    pass
        elif import_type == "pst":
            # PST converted to mbox - use emailSourcePath which points to specific mbox file
            if email_source_path:
                raw_email = get_raw_email_from_import(email_source_path, uid)
            else:
                # Fallback to source_path (shouldn't normally happen)
                raw_email = get_raw_email_from_import(str(source_path), uid)
        else:
            # Standard mbox
            raw_email = get_raw_email_from_import(str(source_path), uid)
    return raw_email


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
    from email.utils import parsedate_to_datetime

    data = request.get_json() or {}
    source_path = data.get("sourcePath", "").strip()
    uid = data.get("uid", "").strip()
    import_type = data.get("importType", "mbox")
    folder_path = data.get("folderPath", "")
    email_source_path = data.get("emailSourcePath", "").strip()  # Direct path to email file

    if not source_path and not email_source_path:
        return jsonify({"error": "Source path is required"}), 400
    if not uid:
        return jsonify({"error": "UID is required"}), 400

    source_path = Path(source_path).expanduser() if source_path else None
    if source_path and not source_path.exists():
        return jsonify({"error": "Source not found"}), 404

    try:
        raw_email = _locate_import_raw_email(
            source_path, uid, import_type, folder_path, email_source_path
        )

        if not raw_email:
            return jsonify({"error": "Email not found in import source"}), 404

        fields = view_fields(raw_email)

        # Parse date
        date_str = fields["date"]
        date_display = date_str
        if date_str:
            try:
                dt = parsedate_to_datetime(date_str)
                date_display = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass

        email_data = {
            **fields,
            "uid": uid,
            "subject": fields["subject"] or "(no subject)",
            "date": date_display,
        }

        return jsonify({"email": email_data})

    except Exception as e:
        return jsonify({"error": f"Failed to read email: {str(e)}"}), 500



@api_bp.route("/import/source", methods=["POST"])
def get_import_email_source():
    """Raw source of an email in a mounted import — the counterpart of
    /folders/<id>/emails/<id>/source for mail that is not yet archived,
    so headers can be inspected before deciding to archive it."""
    data = request.get_json() or {}
    source_path = data.get("sourcePath", "").strip()
    uid = data.get("uid", "").strip()
    import_type = data.get("importType", "mbox")
    folder_path = data.get("folderPath", "")
    email_source_path = data.get("emailSourcePath", "").strip()

    if not source_path and not email_source_path:
        return jsonify({"error": "Source path is required"}), 400
    if not uid:
        return jsonify({"error": "UID is required"}), 400

    source_path = Path(source_path).expanduser() if source_path else None
    if source_path and not source_path.exists():
        return jsonify({"error": "Source not found"}), 404

    try:
        raw_email = _locate_import_raw_email(
            source_path, uid, import_type, folder_path, email_source_path
        )
    except Exception as e:
        log.error(f"Error reading import source: {e}")
        return jsonify({"error": "Failed to read email source"}), 500
    if not raw_email:
        return jsonify({"error": "Email not found in import source"}), 404

    try:
        source = raw_email.decode("utf-8")
    except UnicodeDecodeError:
        source = raw_email.decode("latin-1")
    return jsonify({"source": source})

@api_bp.route("/import/attachment", methods=["POST"])
def download_import_attachment():
    """
    Download an attachment from an import source email.

    Request body:
        sourcePath: Path to mbox file or directory
        uid: Email UID
        importType: 'mbox', 'apple-mbox', 'pst', or 'eml'
        folderPath: (optional) For apple-mbox, path to specific .mbox folder
        emailSourcePath: (optional) Direct path to email file
        index: Attachment index (0-based)
        inline: (optional) If true, display inline instead of download

    Returns:
        Attachment file data
    """

    from utils.log import get_logger


    log = get_logger()

    data = request.get_json() or {}
    source_path = data.get("sourcePath", "").strip()
    uid = data.get("uid", "").strip()
    import_type = data.get("importType", "mbox")
    folder_path = data.get("folderPath", "")
    email_source_path = data.get("emailSourcePath", "").strip()
    index = data.get("index", 0)
    view_inline = data.get("inline", False)

    log.debug(f"Import attachment request: type={import_type}, uid={uid}, index={index}")
    log.debug(
        f"  sourcePath={source_path}, emailSourcePath={email_source_path}, folderPath={folder_path}"
    )

    if not source_path and not email_source_path:
        return jsonify({"error": "Source path is required"}), 400
    if not uid:
        return jsonify({"error": "UID is required"}), 400

    source_path = Path(source_path).expanduser() if source_path else None
    if source_path and not source_path.exists():
        return jsonify({"error": "Source not found"}), 404

    try:
        raw_email = _locate_import_raw_email(
            source_path, uid, import_type, folder_path, email_source_path
        )
        if not raw_email:
            return jsonify({"error": "Email not found in import source"}), 404

        # The same list the preview route reported (core/message_view.py).
        att = attachment_at(raw_email, index)
        if att is None:
            return jsonify({"error": "Attachment not found"}), 404
        # Inline only for a short list of inert types; see web/responses.py.
        return attachment_response(
            att["payload"], att["content_type"], att["filename"], inline=view_inline
        )

    except Exception as e:
        return jsonify({"error": f"Failed to download attachment: {str(e)}"}), 500


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
                (parent_id,),
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
        tuple(folder_ids),
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
                safe_subject = "".join(c if c.isalnum() or c in " -_" else "_" for c in subject)[
                    :50
                ].strip()
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
                log.warning(f"Error exporting message {msg['id']}: {e}")
                continue

    zip_buffer.seek(0)

    # Generate download filename
    safe_folder_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in folder["name"])[
        :30
    ].strip()
    download_filename = f"{safe_folder_name}_export.zip"

    return send_file(
        zip_buffer, mimetype="application/zip", as_attachment=True, download_name=download_filename
    )
