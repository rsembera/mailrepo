"""
MailRepo API - Import/Export Routes

Handles mbox and eml import, and folder export.
"""

import io
import re
import zipfile
from pathlib import Path

from flask import jsonify, request, send_file

from core import Config, Database, Encryption, import_eml_file, import_mbox_file, scan_mbox_file
from utils.log import get_logger

from . import api_bp

log = get_logger()


def _linkify_html(html):
    """
    Convert plain text URLs and email addresses in HTML to clickable links.
    Skips content that's already inside anchor tags or other HTML attributes.
    """
    # Split HTML into parts: inside tags vs text content
    # This regex captures HTML tags (including their content) as separate groups
    parts = re.split(r'(<a\s[^>]*>.*?</a>|<[^>]+>)', html, flags=re.IGNORECASE | re.DOTALL)

    result = []
    for part in parts:
        # Skip empty parts
        if not part:
            continue
        # Skip HTML tags and existing anchor elements
        if part.startswith('<'):
            result.append(part)
            continue

        # This is text content - linkify URLs and emails
        # URL pattern: match until we hit whitespace, quotes, angle brackets, or HTML entities
        # The negative lookahead stops at &nbsp; &amp; &lt; etc but allows & in query strings
        part = re.sub(
            r'(https?://(?:(?!&(?:nbsp|amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)[^\s\u00a0<>"\'])+)',
            r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>',
            part
        )
        # Then linkify email addresses (but not ones we just made into links)
        part = re.sub(
            r'\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b(?![^<]*>)',
            r'<a href="mailto:\1">\1</a>',
            part
        )
        result.append(part)

    return ''.join(result)


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

    from .email_parser import _parse_eml_directory, get_raw_email_from_import

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
        except Exception:
            return str(header)

    def get_email_body(msg):
        """Extract email body - returns (html_body, text_body) tuple."""
        html_body = None
        text_body = None

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                if "attachment" in content_disposition:
                    continue

                if content_type == "text/html" and not html_body:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        html_body = payload.decode(charset, errors="replace")
                elif content_type == "text/plain" and not text_body:
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

        return (html_body, text_body)

    def get_inline_images(msg):
        """Extract inline images (parts with Content-ID) for cid: replacement."""
        import base64
        inline_images = {}  # cid -> data URL

        if msg.is_multipart():
            for part in msg.walk():
                content_id = part.get("Content-ID")
                if content_id:
                    payload = part.get_payload(decode=True)
                    if payload:
                        content_type = part.get_content_type()
                        # Strip angle brackets: <image001.png@...> -> image001.png@...
                        cid = content_id.strip('<>')
                        b64_data = base64.b64encode(payload).decode('ascii')
                        inline_images[cid] = f"data:{content_type};base64,{b64_data}"

        return inline_images

    def replace_cid_refs(html_body, inline_images):
        """Replace cid: references in HTML with data URLs."""
        if not html_body or not inline_images:
            return html_body

        import re
        def replace_cid(match):
            cid = match.group(1)
            return inline_images.get(cid, match.group(0))

        return re.sub(r'cid:([^"\'\s>]+)', replace_cid, html_body)

    def get_attachments(msg):
        """Extract attachment info from email (excludes inline images)."""
        attachments = []
        if msg.is_multipart():
            for part in msg.walk():
                content_disposition = str(part.get("Content-Disposition", ""))
                filename = part.get_filename()
                content_type = part.get_content_type()
                content_id = part.get("Content-ID")

                # Debug logging
                log.debug(f"  Part: {content_type}, filename: {filename}, disposition: {content_disposition[:30] if content_disposition else 'None'}")

                # Skip inline images - they're handled via cid: replacement in HTML
                # Only skip if it's an image with Content-ID (actual inline embedded image)
                if content_id and content_type.startswith("image/"):
                    continue

                # Treat as attachment if explicitly marked as attachment,
                # OR if it has a filename (even if inline)
                if "attachment" in content_disposition or (filename and part.get_content_maintype() != "text"):
                    if filename:
                        attachments.append({
                            "filename": decode_header_value(filename),
                            "content_type": part.get_content_type(),
                            "size": len(part.get_payload(decode=True) or b""),
                        })
        log.debug(f"  Found {len(attachments)} attachments")
        return attachments

    try:
        raw_email = None

        # If we have a direct path to the email file, use it (EML files, Apple emlx)
        # But NOT for mbox files - those need UID-based lookup
        if email_source_path:
            email_path = Path(email_source_path).expanduser()
            if email_path.exists() and email_path.is_file():
                suffix = email_path.suffix.lower()
                # Only use direct file reading for individual email files
                if suffix == '.emlx':
                    # Parse Apple .emlx format
                    with open(email_path, 'rb') as f:
                        content = f.read()
                    first_newline = content.find(b'\n')
                    if first_newline > 0:
                        email_content = content[first_newline + 1:]
                        plist_marker = email_content.rfind(b'<?xml version=')
                        if plist_marker > 0:
                            email_content = email_content[:plist_marker]
                        raw_email = email_content
                elif suffix == '.eml':
                    # Regular .eml file
                    with open(email_path, 'rb') as f:
                        raw_email = f.read()
                # For mbox files, fall through to UID-based lookup below

        # Fallback lookups - only if direct file reading didn't work
        if not raw_email:
            if import_type == 'eml':
                # EML directory - find specific file
                if uid.startswith('eml-'):
                    results = _parse_eml_directory(str(source_path))
                    for r_uid, r_bytes in results:
                        if r_uid == uid:
                            raw_email = r_bytes
                            break
            elif import_type == 'apple-mbox':
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
                            if entry.name.endswith('.emlx') and entry.is_file():
                                expected_uid = f"emlx-{entry.name}"
                                if expected_uid == uid:
                                    try:
                                        with open(entry.path, 'rb') as f:
                                            content = f.read()
                                        # .emlx format: first line is byte count, then email, then plist
                                        first_newline = content.find(b'\n')
                                        if first_newline > 0:
                                            email_content = content[first_newline + 1:]
                                            plist_marker = email_content.rfind(b'<?xml version=')
                                            if plist_marker > 0:
                                                email_content = email_content[:plist_marker]
                                            raw_email = email_content
                                            break
                                    except Exception:
                                        pass
            elif import_type == 'pst':
                # PST converted to mbox - use emailSourcePath which points to specific mbox file
                if email_source_path:
                    raw_email = get_raw_email_from_import(email_source_path, uid)
                else:
                    # Fallback to source_path (shouldn't normally happen)
                    raw_email = get_raw_email_from_import(str(source_path), uid)
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
            except Exception:
                pass

        html_body, text_body = get_email_body(msg)

        # Resolve cid: references in HTML body
        inline_images = get_inline_images(msg)
        html_body = replace_cid_refs(html_body, inline_images)

        # Linkify URLs and emails in HTML body that aren't already links
        if html_body:
            html_body = _linkify_html(html_body)

        email_data = {
            "uid": uid,
            "subject": decode_header_value(msg.get("Subject", "(no subject)")),
            "from": decode_header_value(msg.get("From", "")),
            "to": decode_header_value(msg.get("To", "")),
            "cc": decode_header_value(msg.get("Cc", "")),
            "date": date_display,
            "html_body": html_body,
            "text_body": text_body,
            "attachments": get_attachments(msg),
        }

        return jsonify({"email": email_data})

    except Exception as e:
        return jsonify({"error": f"Failed to read email: {str(e)}"}), 500


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
    import email as email_lib
    from email.header import decode_header

    from flask import Response

    from utils.log import get_logger

    from .email_parser import _parse_eml_directory, get_raw_email_from_import
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
    log.debug(f"  sourcePath={source_path}, emailSourcePath={email_source_path}, folderPath={folder_path}")

    if not source_path and not email_source_path:
        return jsonify({"error": "Source path is required"}), 400
    if not uid:
        return jsonify({"error": "UID is required"}), 400

    source_path = Path(source_path).expanduser() if source_path else None
    if source_path and not source_path.exists():
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
        except Exception:
            return str(header)

    try:
        # Get raw email - same logic as get_import_email
        raw_email = None

        if email_source_path:
            email_path = Path(email_source_path).expanduser()
            if email_path.exists() and email_path.is_file():
                suffix = email_path.suffix.lower()
                if suffix == '.emlx':
                    with open(email_path, 'rb') as f:
                        content = f.read()
                    first_newline = content.find(b'\n')
                    if first_newline > 0:
                        email_content = content[first_newline + 1:]
                        plist_marker = email_content.rfind(b'<?xml version=')
                        if plist_marker > 0:
                            email_content = email_content[:plist_marker]
                        raw_email = email_content
                elif suffix == '.eml':
                    with open(email_path, 'rb') as f:
                        raw_email = f.read()

        if not raw_email:
            if import_type == 'pst':
                if email_source_path:
                    raw_email = get_raw_email_from_import(email_source_path, uid)
                else:
                    raw_email = get_raw_email_from_import(str(source_path), uid)
            elif import_type == 'eml':
                if uid.startswith('eml-'):
                    results = _parse_eml_directory(str(source_path))
                    for r_uid, r_bytes in results:
                        if r_uid == uid:
                            raw_email = r_bytes
                            break
            elif import_type == 'apple-mbox':
                import mailbox
                import os
                mbox_dir = folder_path if folder_path else str(source_path)
                mbox_file = os.path.join(mbox_dir, "mbox")
                if os.path.isfile(mbox_file):
                    try:
                        mbox = mailbox.mbox(mbox_file)
                        for i, message in enumerate(mbox):
                            expected_uid = f"apple-{os.path.basename(mbox_file)}-{i}"
                            if expected_uid == uid:
                                raw_email = message.as_bytes()
                                break
                    except Exception:
                        pass
                if not raw_email:
                    messages_dir = os.path.join(mbox_dir, "Messages")
                    if os.path.isdir(messages_dir):
                        for entry in os.scandir(messages_dir):
                            if entry.name.endswith('.emlx') and entry.is_file():
                                expected_uid = f"emlx-{entry.name}"
                                if expected_uid == uid:
                                    try:
                                        with open(entry.path, 'rb') as f:
                                            content = f.read()
                                        first_newline = content.find(b'\n')
                                        if first_newline > 0:
                                            email_content = content[first_newline + 1:]
                                            plist_marker = email_content.rfind(b'<?xml version=')
                                            if plist_marker > 0:
                                                email_content = email_content[:plist_marker]
                                            raw_email = email_content
                                            break
                                    except Exception:
                                        pass
            else:
                raw_email = get_raw_email_from_import(str(source_path), uid)

        if not raw_email:
            return jsonify({"error": "Email not found in import source"}), 404

        # Parse the email and find attachments (must match filtering in get_attachments)
        msg = email_lib.message_from_bytes(raw_email)

        attachments = []
        if msg.is_multipart():
            for part in msg.walk():
                content_disposition = str(part.get("Content-Disposition", ""))
                filename = part.get_filename()
                content_id = part.get("Content-ID")
                content_type = part.get_content_type()

                # Skip inline images - they're handled via cid: replacement in HTML
                # Only skip if it's an image with Content-ID (actual inline embedded image)
                if content_id and content_type.startswith("image/"):
                    continue

                # Treat as attachment if explicitly marked as attachment,
                # OR if it has a filename (even if inline) and isn't text
                if "attachment" in content_disposition or (filename and part.get_content_maintype() != "text"):
                    if filename:
                        attachments.append({
                            "filename": decode_header_value(filename),
                            "content_type": content_type,
                            "data": part.get_payload(decode=True),
                        })

        if index < 0 or index >= len(attachments):
            return jsonify({"error": "Attachment not found"}), 404

        att = attachments[index]
        content_type = att["content_type"] or "application/octet-stream"
        disposition = "inline" if view_inline else "attachment"

        return Response(
            att["data"],
            mimetype=content_type,
            headers={"Content-Disposition": f'{disposition}; filename="{att["filename"]}"'}
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
                log.warning(f"Error exporting message {msg['id']}: {e}")
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
