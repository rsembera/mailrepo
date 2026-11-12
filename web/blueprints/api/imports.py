"""
MailRepo API - Import/Export Routes

Handles mbox and eml import.
"""

from pathlib import Path

from flask import jsonify, request

from core.message_view import attachment_at, view_fields
from utils.log import get_logger
from web.responses import attachment_response

from . import api_bp

log = get_logger()


def _locate_import_raw_email(
    source_path, uid: str, import_type: str, folder_path: str, email_source_path: str
) -> bytes | None:
    """Find one email's raw bytes inside a mounted import.

    Shared by the preview and view-source routes. Direct file paths
    (.eml, .emlx) are read as-is; everything else is a UID lookup that
    depends on the import type.
    """
    from .email_parser import (
        _parse_eml_directory,
        _parse_emlx_file,
        get_raw_email_from_import,
        mbox_message_bytes,
    )

    raw_email = None

    # If we have a direct path to the email file, use it (EML files, Apple emlx)
    # But NOT for mbox files - those need UID-based lookup
    if email_source_path:
        email_path = Path(email_source_path).expanduser()
        if email_path.exists() and email_path.is_file():
            suffix = email_path.suffix.lower()
            # Only use direct file reading for individual email files
            if suffix == ".emlx":
                raw_email = _parse_emlx_file(str(email_path))
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
            import os

            # Use folder_path which points to the specific .mbox directory
            mbox_dir = folder_path if folder_path else str(source_path)

            # Check for mbox file inside the .mbox directory
            mbox_file = os.path.join(mbox_dir, "mbox")
            if os.path.isfile(mbox_file):
                # UID format from filesystem.py: f"apple-{basename}-{i}"
                # e.g., "apple-mbox-0" where "mbox" is basename of the mbox file
                prefix = f"apple-{os.path.basename(mbox_file)}-"
                if uid.startswith(prefix) and uid[len(prefix) :].isdigit():
                    try:
                        raw_email = mbox_message_bytes(mbox_file, int(uid[len(prefix) :]))
                    except Exception:
                        raw_email = None

            # Check for Messages directory with .emlx files
            if not raw_email:
                messages_dir = os.path.join(mbox_dir, "Messages")
                if os.path.isdir(messages_dir):
                    # UID format: f"emlx-{filename}"
                    for entry in os.scandir(messages_dir):
                        if entry.name.endswith(".emlx") and entry.is_file():
                            expected_uid = f"emlx-{entry.name}"
                            if expected_uid == uid:
                                raw_email = _parse_emlx_file(entry.path)
                                if raw_email:
                                    break
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
