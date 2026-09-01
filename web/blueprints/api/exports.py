"""
MailRepo API — Export Routes

Bulk export of archived emails as PDF or .eml ZIP.

The export runs as a background job so progress can be streamed to the UI
via Server-Sent Events. The flow is:

1. Client POSTs to /api/export/start with a list of message IDs and options.
   Server creates a job, kicks off a background thread, returns ``{job_id}``.
2. Client opens an EventSource on /api/export/progress/<job_id> and reads
   progress / status / complete events.
3. On ``complete``:
   - If the user picked a destination directory, the file has already been
     written to disk; the ``complete`` event carries ``saved_path``.
   - Otherwise, the client navigates to /api/export/download/<job_id> which
     streams the in-memory result with ``Content-Disposition: attachment``.
4. The job is cleaned up after the file is saved/downloaded (or after a TTL
   if abandoned).

Job state lives in process memory only — exports are ephemeral. This is
fine for a local-first single-user app.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
import uuid
import zipfile
from collections import deque
from datetime import datetime, timedelta
from typing import Any

from flask import Response, jsonify, request, send_file, stream_with_context

from core import Config, Database, Encryption
from core.database import build_fts_match

from . import api_bp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job registry
# ---------------------------------------------------------------------------

# job_id -> {
#   "status": "running" | "done" | "failed",
#   "events": deque[dict],         # progress events the SSE endpoint hasn\'t shipped yet
#   "result_bytes": bytes | None,    # only when no output_dir
#   "result_mimetype": str,
#   "result_filename": str,
#   "saved_path": str | None,        # set when output_dir was provided
#   "error": str | None,
#   "created_at": datetime,
#   "downloaded_at": datetime | None,
#   "lock": threading.Lock,
#   "event_added": threading.Event,  # set when a new event lands; SSE waits on this
# }
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_JOB_TTL = timedelta(minutes=30)  # abandoned jobs purged after this


def _new_job() -> str:
    """Allocate a job id and register an empty job record."""
    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "status": "running",
            "events": deque(),
            "result_bytes": None,
            "result_mimetype": "application/octet-stream",
            "result_filename": "export.bin",
            "saved_path": None,  # absolute disk path when output_dir was used
            "error": None,
            "created_at": datetime.now(),
            "downloaded_at": None,
            "lock": threading.Lock(),
            "event_added": threading.Event(),
        }
    _gc_jobs()
    return job_id


def _get_job(job_id: str) -> dict | None:
    """Return job record, or None if unknown."""
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


def _push_event(job_id: str, event: str, data: dict) -> None:
    """Append a progress event to a job\'s queue and wake any SSE readers."""
    job = _get_job(job_id)
    if not job:
        return
    with job["lock"]:
        job["events"].append({"event": event, "data": data})
    job["event_added"].set()


def _gc_jobs() -> None:
    """Drop jobs that have outlived their TTL."""
    cutoff = datetime.now() - _JOB_TTL
    stale = []
    with _JOBS_LOCK:
        for jid, job in _JOBS.items():
            if job["downloaded_at"] and job["downloaded_at"] < cutoff:
                stale.append(jid)
            elif job["created_at"] < cutoff:
                stale.append(jid)
        for jid in stale:
            _JOBS.pop(jid, None)


# ---------------------------------------------------------------------------
# Selection resolution
# ---------------------------------------------------------------------------


def _resolve_message_ids(payload: dict) -> tuple[list[int], str]:
    """Resolve a selection payload into a concrete list of message IDs and a
    human-readable scope label.

    Selection payload shapes::

        {"source": "folder", "folder_id": 5, "include_subfolders": true}
        {"source": "messages", "message_ids": [1, 2, 3]}
        {"source": "search",
         "query": "smith", "folder_id": 5, "include_subfolders": false}
    """
    source = payload.get("source")
    if source == "folder":
        folder_id = int(payload["folder_id"])
        include_subs = bool(payload.get("include_subfolders", True))
        folder_ids = _collect_folder_ids(folder_id, include_subs)
        ids = _message_ids_in_folders(folder_ids)
        label = _folder_path_label(folder_id)
        if include_subs and len(folder_ids) > 1:
            label = f"{label} (+ subfolders)"
        return ids, label
    elif source == "messages":
        ids = [int(x) for x in payload.get("message_ids", [])]
        label = f"{len(ids)} selected emails"
        return ids, label
    elif source == "search":
        query = (payload.get("query") or "").strip()
        if not query:
            return [], ""
        folder_id = payload.get("folder_id")
        include_subs = bool(payload.get("include_subfolders", True))
        ids = _search_message_ids(query, folder_id, include_subs)
        label = f'Search: "{query[:40]}"'
        if folder_id:
            scope = _folder_path_label(int(folder_id))
            label = f"{label} in {scope}"
            if include_subs:
                label += " (+ subfolders)"
        return ids, label
    raise ValueError(f"Unknown selection source: {source!r}")


def _collect_folder_ids(root_id: int, include_subs: bool) -> list[int]:
    """Return ``[root_id, *descendants]`` if include_subs else ``[root_id]``."""
    ids = [root_id]
    if not include_subs:
        return ids
    queue = [root_id]
    while queue:
        parent = queue.pop()
        children = Database.fetchall(
            "SELECT id FROM folders WHERE parent_id = ? AND deleted_at IS NULL",
            (parent,),
        )
        for c in children:
            ids.append(c["id"])
            queue.append(c["id"])
    return ids


def _message_ids_in_folders(folder_ids: list[int]) -> list[int]:
    """All non-deleted message ids within these folders, ordered by date."""
    if not folder_ids:
        return []
    placeholders = ",".join("?" * len(folder_ids))
    rows = Database.fetchall(
        f"""
        SELECT id FROM messages
        WHERE folder_id IN ({placeholders}) AND deleted_at IS NULL
        ORDER BY date
        """,
        tuple(folder_ids),
    )
    return [r["id"] for r in rows]


def _search_message_ids(query: str, folder_id: int | None, include_subs: bool) -> list[int]:
    """FTS5 search returning message ids."""
    fts_query = build_fts_match(query)
    if fts_query is None:
        return []
    if folder_id:
        folder_ids = _collect_folder_ids(int(folder_id), include_subs)
        placeholders = ",".join("?" * len(folder_ids))
        rows = Database.fetchall(
            f"""
            SELECT m.id FROM messages m
            JOIN messages_fts fts ON m.id = fts.rowid
            WHERE messages_fts MATCH ? AND m.folder_id IN ({placeholders})
              AND m.deleted_at IS NULL
            ORDER BY m.date
            """,
            (fts_query, *folder_ids),
        )
    else:
        rows = Database.fetchall(
            """
            SELECT m.id FROM messages m
            JOIN messages_fts fts ON m.id = fts.rowid
            WHERE messages_fts MATCH ? AND m.deleted_at IS NULL
            ORDER BY m.date
            """,
            (fts_query,),
        )
    return [r["id"] for r in rows]


def _folder_path_label(folder_id: int) -> str:
    """Build a slash-joined path for a folder, like ``Clients/Smith``."""
    parts: list[str] = []
    seen: set[int] = set()
    cur_id = folder_id
    while cur_id and cur_id not in seen:
        seen.add(cur_id)
        row = Database.fetchone("SELECT name, parent_id FROM folders WHERE id = ?", (cur_id,))
        if not row:
            break
        parts.append(row["name"])
        cur_id = row["parent_id"]
    return "/".join(reversed(parts)) or "Folder"


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------


def _encrypt_to_zip(payload_bytes: bytes, payload_filename: str, password: str) -> bytes:
    """Wrap ``payload_bytes`` in an AES-256 encrypted ZIP using pyzipper.

    Standard ``zipfile`` only supports the legacy ZipCrypto cipher, which is
    cryptographically broken. We use pyzipper for proper AES-256.

    Recipient-side notes (these matter \u2014 standard tools differ):
    - macOS\'s built-in Archive Utility does NOT open AES ZIPs. Recipients
      need The Unarchiver (free, App Store).
    - Windows 11 (23H2+) handles AES natively in File Explorer.
    - Linux ``unzip`` 6.0+ supports AES with the ``-P`` flag.
    """
    import pyzipper

    buf = io.BytesIO()
    with pyzipper.AESZipFile(
        buf, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
    ) as zf:
        zf.setpassword(password.encode("utf-8"))
        zf.writestr(payload_filename, payload_bytes)
    return buf.getvalue()


def _write_other_attachments(zf, other_attachments: list[dict]) -> None:
    """Write non-PDF attachments as sibling files inside an open ZipFile.

    Path layout: ``attachments/email-<N>/<filename>``. Filenames are
    de-duplicated within each email-N folder. Works with both
    ``zipfile.ZipFile`` and ``pyzipper.AESZipFile``.
    """
    if not other_attachments:
        return
    per_email_used: dict[int, set[str]] = {}
    for att in other_attachments:
        eidx = att["email_index"]
        used = per_email_used.setdefault(eidx, set())
        base = att["filename"] or "attachment"
        safe = re.sub(r"[^A-Za-z0-9 ._\-]", "_", base)[:120].strip() or "attachment"
        name = safe
        counter = 1
        while name in used:
            stem, _, ext = safe.rpartition(".")
            if stem:
                name = f"{stem}_{counter}.{ext}"
            else:
                name = f"{safe}_{counter}"
            counter += 1
        used.add(name)
        zf.writestr(f"attachments/email-{eidx}/{name}", att["data"])


def _build_encrypted_eml_zip(message_ids: list[int], password: str) -> tuple[bytes, str]:
    """Build an AES-256 encrypted ZIP of decrypted .eml files.

    Same shape as ``_build_eml_zip`` but writes via pyzipper with a password,
    so the resulting ZIP is natively encrypted (no double-wrapping).
    """
    import pyzipper

    if not message_ids:
        return b"", "export.zip"

    placeholders = ",".join("?" * len(message_ids))
    rows = Database.fetchall(
        f"""
        SELECT m.id, m.folder_id, m.subject, m.date, m.filepath, f.name AS folder_name
        FROM messages m
        JOIN folders f ON m.folder_id = f.id
        WHERE m.id IN ({placeholders}) AND m.deleted_at IS NULL
        ORDER BY m.date
        """,
        tuple(message_ids),
    )

    folder_paths: dict[int, str] = {}

    def folder_path(fid: int) -> str:
        if fid in folder_paths:
            return folder_paths[fid]
        path = _folder_path_label(fid)
        folder_paths[fid] = path
        return path

    buf = io.BytesIO()
    with pyzipper.AESZipFile(
        buf, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
    ) as zf:
        zf.setpassword(password.encode("utf-8"))
        per_folder_used: dict[int, set[str]] = {}
        for row in rows:
            fid = row["folder_id"]
            used = per_folder_used.setdefault(fid, set())
            filepath = Config.get_base_path() / row["filepath"]
            if not filepath.exists():
                continue
            try:
                decrypted = Encryption.decrypt(filepath.read_bytes())
            except Exception as e:
                logger.warning("Failed to decrypt message %s for export: %s", row["id"], e)
                continue
            subject = row["subject"] or "no_subject"
            safe_subject = re.sub(r"[^A-Za-z0-9 _\-]", "_", subject)[:50].strip() or "email"
            base = f"{safe_subject}.eml"
            name = base
            counter = 1
            while name in used:
                name = f"{safe_subject}_{counter}.eml"
                counter += 1
            used.add(name)
            zf.writestr(f"{folder_path(fid)}/{name}", decrypted)

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return buf.getvalue(), f"mailrepo_export_{stamp}.zip"


# ---------------------------------------------------------------------------
# .eml ZIP builder
# ---------------------------------------------------------------------------


def _build_eml_zip(message_ids: list[int]) -> tuple[bytes, str]:
    """Build an unencrypted ZIP of decrypted .eml files.

    Returns ``(bytes, filename_hint)``.

    Reuses the filename-sanitization conventions of the existing folder
    export. Emails are placed under their folder path inside the ZIP so the
    recipient sees the original structure.
    """
    if not message_ids:
        return b"", "export.zip"

    placeholders = ",".join("?" * len(message_ids))
    rows = Database.fetchall(
        f"""
        SELECT m.id, m.folder_id, m.subject, m.date, m.filepath, f.name AS folder_name
        FROM messages m
        JOIN folders f ON m.folder_id = f.id
        WHERE m.id IN ({placeholders}) AND m.deleted_at IS NULL
        ORDER BY m.date
        """,
        tuple(message_ids),
    )

    # Build folder paths once
    folder_paths: dict[int, str] = {}

    def folder_path(fid: int) -> str:
        if fid in folder_paths:
            return folder_paths[fid]
        path = _folder_path_label(fid)
        folder_paths[fid] = path
        return path

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        per_folder_used: dict[int, set[str]] = {}
        for row in rows:
            fid = row["folder_id"]
            used = per_folder_used.setdefault(fid, set())
            filepath = Config.get_base_path() / row["filepath"]
            if not filepath.exists():
                continue
            try:
                decrypted = Encryption.decrypt(filepath.read_bytes())
            except Exception as e:
                logger.warning("Failed to decrypt message %s for export: %s", row["id"], e)
                continue
            subject = row["subject"] or "no_subject"
            safe_subject = re.sub(r"[^A-Za-z0-9 _\-]", "_", subject)[:50].strip() or "email"
            base = f"{safe_subject}.eml"
            name = base
            counter = 1
            while name in used:
                name = f"{safe_subject}_{counter}.eml"
                counter += 1
            used.add(name)
            zf.writestr(f"{folder_path(fid)}/{name}", decrypted)

    buf.seek(0)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return buf.getvalue(), f"mailrepo_export_{stamp}.zip"


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------


def _run_export_job(job_id: str, payload: dict) -> None:
    """Worker thread entry point. Resolves selection, builds the export, and
    writes results into the job record.
    """
    try:
        selection = payload.get("selection") or {}
        message_ids, scope_label = _resolve_message_ids(selection)
        if not message_ids:
            _fail_job(job_id, "No emails matched the selection.")
            return

        export_format = payload.get("format", "pdf")
        if export_format not in ("pdf", "eml", "both"):
            _fail_job(job_id, f"Unknown format: {export_format!r}")
            return

        if export_format == "pdf":
            _build_pdf_only(job_id, message_ids, scope_label, payload)
        elif export_format == "eml":
            _build_eml_only(job_id, message_ids, scope_label, payload)
        else:  # both
            _build_pdf_and_eml(job_id, message_ids, scope_label, payload)
    except Exception as e:
        logger.exception("Export job %s crashed", job_id)
        _fail_job(job_id, f"Unexpected error: {e}")


def _build_pdf_only(job_id: str, message_ids: list[int], scope_label: str, payload: dict) -> None:
    from core.pdf_export import build_combined_pdf

    sort_order = payload.get("sort_order", "chronological")
    include_cover = bool(payload.get("include_cover", True))
    load_remote = bool(payload.get("load_remote_content", False))

    final_data: dict | None = None
    for ev in build_combined_pdf(
        message_ids,
        scope_label=scope_label,
        sort_order=sort_order,
        include_cover=include_cover,
        load_remote=load_remote,
    ):
        if ev["event"] == "complete":
            final_data = ev["data"]
            break
        if ev["event"] == "error":
            _fail_job(job_id, ev["data"].get("error", "Unknown error"))
            return
        # Forward to the SSE event queue (skip raw bytes if any sneak in)
        forwardable = {k: v for k, v in ev["data"].items() if k != "pdf_bytes"}
        _push_event(job_id, ev["event"], forwardable)

    if not final_data:
        _fail_job(job_id, "PDF generation finished without a result.")
        return

    pdf_password = (payload.get("encryption_password") or "").strip()
    other_attachments = final_data.get("other_attachments") or []

    # Decide on packaging:
    # - No password, no non-PDF attachments \u2192 bare PDF
    # - No password, has non-PDF attachments \u2192 plain ZIP wrapper
    # - Password, anything \u2192 encrypted ZIP wrapper (also covers attachments)
    needs_wrapper = bool(pdf_password) or bool(other_attachments)

    if not needs_wrapper:
        _finish_job(
            job_id,
            result_bytes=final_data["pdf_bytes"],
            result_mimetype="application/pdf",
            result_filename=final_data["filename_hint"],
            summary={
                "format": "pdf",
                "email_count": final_data.get("email_count", 0),
                "appendix_count": final_data.get("appendix_count", 0),
            },
            output_dir=payload.get("output_dir"),
        )
        return

    # Build a wrapper ZIP containing the PDF + attachments/email-N/<files>.
    # Use pyzipper for the encrypted case, plain zipfile otherwise.
    if pdf_password:
        _push_event(job_id, "status", {"phase": "encrypting", "message": "Encrypting export\u2026"})
        _push_event(job_id, "progress", {"phase": "encrypting", "percent": 95})
    elif other_attachments:
        _push_event(
            job_id,
            "status",
            {
                "phase": "packaging",
                "message": f"Packaging {len(other_attachments)} attachments\u2026",
            },
        )
        _push_event(job_id, "progress", {"phase": "packaging", "percent": 95})

    out_buf = io.BytesIO()
    if pdf_password:
        import pyzipper

        zf_ctx = pyzipper.AESZipFile(
            out_buf,
            "w",
            compression=pyzipper.ZIP_DEFLATED,
            encryption=pyzipper.WZ_AES,
        )
    else:
        zf_ctx = zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED)

    with zf_ctx as zf:
        if pdf_password:
            zf.setpassword(pdf_password.encode("utf-8"))
        # The PDF
        zf.writestr(final_data["filename_hint"], final_data["pdf_bytes"])
        # Sibling attachments grouped by email index
        _write_other_attachments(zf, other_attachments)

    zip_filename = re.sub(r"\.pdf$", ".zip", final_data["filename_hint"], flags=re.IGNORECASE)
    if not zip_filename.endswith(".zip"):
        zip_filename += ".zip"

    _finish_job(
        job_id,
        result_bytes=out_buf.getvalue(),
        result_mimetype="application/zip",
        result_filename=zip_filename,
        summary={
            "format": "pdf",
            "email_count": final_data.get("email_count", 0),
            "appendix_count": final_data.get("appendix_count", 0),
            "other_attachment_count": len(other_attachments),
            "encrypted": bool(pdf_password),
        },
        output_dir=payload.get("output_dir"),
    )


def _build_eml_only(job_id: str, message_ids: list[int], scope_label: str, payload: dict) -> None:
    eml_password = (payload.get("encryption_password") or "").strip()
    if eml_password:
        _push_event(
            job_id,
            "status",
            {
                "phase": "loading",
                "message": f"Bundling and encrypting {len(message_ids)} emails...",
            },
        )
        _push_event(
            job_id,
            "progress",
            {"phase": "loading", "current": 0, "total": len(message_ids), "percent": 5},
        )
        zip_bytes, filename = _build_encrypted_eml_zip(message_ids, eml_password)
        _push_event(job_id, "progress", {"phase": "done", "percent": 100})
        _finish_job(
            job_id,
            result_bytes=zip_bytes,
            result_mimetype="application/zip",
            result_filename=filename,
            summary={"format": "eml", "email_count": len(message_ids), "encrypted": True},
            output_dir=payload.get("output_dir"),
        )
        return

    _push_event(
        job_id, "status", {"phase": "loading", "message": f"Bundling {len(message_ids)} emails..."}
    )
    _push_event(
        job_id,
        "progress",
        {"phase": "loading", "current": 0, "total": len(message_ids), "percent": 5},
    )
    zip_bytes, filename = _build_eml_zip(message_ids)
    _push_event(job_id, "progress", {"phase": "done", "percent": 100})
    _finish_job(
        job_id,
        result_bytes=zip_bytes,
        result_mimetype="application/zip",
        result_filename=filename,
        summary={"format": "eml", "email_count": len(message_ids)},
        output_dir=payload.get("output_dir"),
    )


def _build_pdf_and_eml(
    job_id: str, message_ids: list[int], scope_label: str, payload: dict
) -> None:
    """Combined export: PDF + .eml ZIP, packaged into a single ZIP."""
    from core.pdf_export import build_combined_pdf

    sort_order = payload.get("sort_order", "chronological")
    include_cover = bool(payload.get("include_cover", True))
    load_remote = bool(payload.get("load_remote_content", False))

    pdf_data: dict | None = None
    for ev in build_combined_pdf(
        message_ids,
        scope_label=scope_label,
        sort_order=sort_order,
        include_cover=include_cover,
        load_remote=load_remote,
    ):
        if ev["event"] == "complete":
            pdf_data = ev["data"]
            break
        if ev["event"] == "error":
            _fail_job(job_id, ev["data"].get("error", "Unknown error"))
            return
        forwardable = {k: v for k, v in ev["data"].items() if k != "pdf_bytes"}
        # Cap PDF percent at 80 so the .eml step has room to report progress
        if "percent" in forwardable:
            forwardable["percent"] = min(80, int(forwardable["percent"] * 0.8))
        _push_event(job_id, ev["event"], forwardable)

    if not pdf_data:
        _fail_job(job_id, "PDF generation finished without a result.")
        return

    _push_event(job_id, "status", {"phase": "bundling", "message": "Packaging files..."})
    _push_event(job_id, "progress", {"phase": "bundling", "percent": 90})

    eml_bytes, _ = _build_eml_zip(message_ids)

    both_password = (payload.get("encryption_password") or "").strip()

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    safe_scope = re.sub(r"[^A-Za-z0-9_\- ]", "_", scope_label)[:40].strip() or "export"
    filename = f"{safe_scope}_{stamp}_pdf+eml.zip"

    other_attachments = pdf_data.get("other_attachments") or []

    if both_password:
        # Build the contents directly into an encrypted wrapper ZIP. No nested
        # ZIP for the .eml side either \u2014 emails go straight into the wrapper
        # under emails/<folder>/<file>.eml so the recipient only deals with one
        # password.
        import pyzipper

        out_buf = io.BytesIO()
        with pyzipper.AESZipFile(
            out_buf,
            "w",
            compression=pyzipper.ZIP_DEFLATED,
            encryption=pyzipper.WZ_AES,
        ) as zf:
            zf.setpassword(both_password.encode("utf-8"))
            zf.writestr(pdf_data["filename_hint"], pdf_data["pdf_bytes"])
            # Re-read the inner eml zip and copy its entries into the wrapper
            # so we don\'t end up with a ZIP-inside-a-ZIP.
            with zipfile.ZipFile(io.BytesIO(eml_bytes)) as inner:
                for info in inner.infolist():
                    zf.writestr(f"emails/{info.filename}", inner.read(info.filename))
            # Sibling attachments grouped by email index
            _write_other_attachments(zf, other_attachments)

        _push_event(job_id, "progress", {"phase": "done", "percent": 100})

        _finish_job(
            job_id,
            result_bytes=out_buf.getvalue(),
            result_mimetype="application/zip",
            result_filename=filename,
            summary={
                "format": "both",
                "email_count": pdf_data.get("email_count", 0),
                "appendix_count": pdf_data.get("appendix_count", 0),
                "other_attachment_count": len(other_attachments),
                "encrypted": True,
            },
            output_dir=payload.get("output_dir"),
        )
        return

    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(pdf_data["filename_hint"], pdf_data["pdf_bytes"])
        # Nest the .eml ZIP as well
        zf.writestr("emails.zip", eml_bytes)
        _write_other_attachments(zf, other_attachments)
    out_buf.seek(0)

    _push_event(job_id, "progress", {"phase": "done", "percent": 100})

    _finish_job(
        job_id,
        result_bytes=out_buf.getvalue(),
        result_mimetype="application/zip",
        result_filename=filename,
        summary={
            "format": "both",
            "email_count": pdf_data.get("email_count", 0),
            "appendix_count": pdf_data.get("appendix_count", 0),
            "other_attachment_count": len(other_attachments),
        },
        output_dir=payload.get("output_dir"),
    )


def _finish_job(
    job_id: str,
    *,
    result_bytes: bytes,
    result_mimetype: str,
    result_filename: str,
    summary: dict,
    output_dir: str | None = None,
) -> None:
    """Finish a job. If ``output_dir`` is given, write the bytes to disk at
    ``output_dir/result_filename`` and report the saved path; otherwise keep
    the bytes in memory for browser download.
    """
    import os

    job = _get_job(job_id)
    if not job:
        return

    saved_path: str | None = None
    if output_dir:
        try:
            expanded = os.path.expanduser(output_dir.strip())
            target_dir = os.path.realpath(expanded)
            # Create the dir if it doesn't exist (only one level beyond an
            # existing parent — don't silently mkdir -p arbitrary trees).
            if not os.path.isdir(target_dir):
                parent = os.path.dirname(target_dir)
                if parent and os.path.isdir(parent):
                    os.makedirs(target_dir, exist_ok=False)
                else:
                    _fail_job(job_id, f"Destination not found: {output_dir}")
                    return
            # Disambiguate filename if it already exists at the target
            base, ext = os.path.splitext(result_filename)
            candidate = result_filename
            n = 1
            while os.path.exists(os.path.join(target_dir, candidate)):
                candidate = f"{base} ({n}){ext}"
                n += 1
                if n > 999:
                    break
            saved_path = os.path.join(target_dir, candidate)
            with open(saved_path, "wb") as f:
                f.write(result_bytes)
        except PermissionError:
            _fail_job(job_id, f"Permission denied writing to {output_dir}")
            return
        except OSError as e:
            _fail_job(job_id, f"Could not save to {output_dir}: {e}")
            return

    with job["lock"]:
        job["status"] = "done"
        job["result_mimetype"] = result_mimetype
        job["result_filename"] = result_filename
        if saved_path:
            # File is on disk; don't hold the bytes in memory.
            job["result_bytes"] = None
            job["saved_path"] = saved_path
        else:
            job["result_bytes"] = result_bytes

    _push_event(
        job_id,
        "complete",
        {
            "filename": os.path.basename(saved_path) if saved_path else result_filename,
            "size": len(result_bytes),
            "summary": summary,
            "saved_path": saved_path,
        },
    )


def _fail_job(job_id: str, error: str) -> None:
    job = _get_job(job_id)
    if not job:
        return
    with job["lock"]:
        job["status"] = "failed"
        job["error"] = error
    _push_event(job_id, "error", {"error": error})


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


@api_bp.route("/export/start", methods=["POST"])
def start_export():
    """Kick off a new export job."""
    payload = request.get_json() or {}
    if not payload.get("selection"):
        return jsonify({"error": "selection is required"}), 400
    if payload.get("format") not in ("pdf", "eml", "both"):
        return jsonify({"error": "format must be pdf, eml, or both"}), 400

    job_id = _new_job()
    thread = threading.Thread(
        target=_run_export_job,
        args=(job_id, payload),
        daemon=True,
        name=f"export-{job_id[:8]}",
    )
    thread.start()
    return jsonify({"job_id": job_id})


@api_bp.route("/export/progress/<job_id>", methods=["GET"])
def export_progress(job_id):
    """SSE stream of progress events for a running export job."""
    job = _get_job(job_id)
    if not job:
        return Response(
            f"event: error\ndata: {json.dumps({'error': 'Unknown job'})}\n\n",
            mimetype="text/event-stream",
        )

    def generate():
        # Drain any events that already landed before the client connected.
        idle_iters = 0
        while True:
            with job["lock"]:
                events_to_send = list(job["events"])
                job["events"].clear()
                status = job["status"]

            for ev in events_to_send:
                yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'])}\n\n"
                if ev["event"] in ("complete", "error"):
                    return

            # No events pending; wait briefly for more, or exit if job is done.
            if status in ("done", "failed"):
                # In case events drained before status flipped, give one more tick.
                if not job["events"]:
                    return

            # Wait up to 1s for a new event
            job["event_added"].clear()
            triggered = job["event_added"].wait(timeout=1.0)
            if not triggered:
                idle_iters += 1
                # Heartbeat every ~10s to keep proxies happy
                if idle_iters % 10 == 0:
                    yield ": heartbeat\n\n"
                # Safety stop: 5 minutes of total idle time
                if idle_iters > 300:
                    yield f"event: error\ndata: {json.dumps({'error': 'Export timed out'})}\n\n"
                    return
            else:
                idle_iters = 0

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@api_bp.route("/export/download/<job_id>", methods=["GET"])
def download_export(job_id):
    """Download the finished export file. Marks the job for cleanup."""
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Unknown job"}), 404
    if job["status"] != "done":
        return jsonify({"error": f"Job is {job['status']}"}), 409
    # Two paths: bytes still in memory, OR file already saved to disk.
    with job["lock"]:
        bytes_data = job["result_bytes"]
        saved_path = job.get("saved_path")
        mimetype = job["result_mimetype"]
        filename = job["result_filename"]
        job["downloaded_at"] = datetime.now()

    if bytes_data:
        return send_file(
            io.BytesIO(bytes_data),
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename,
        )
    if saved_path and os.path.exists(saved_path):
        return send_file(
            saved_path,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename,
        )
    return jsonify({"error": "No result available"}), 500


@api_bp.route("/export/cancel/<job_id>", methods=["POST"])
def cancel_export(job_id):
    """Best-effort cancel — drops the job record. The worker thread may still
    finish and discover its job is gone, which is fine.
    """
    with _JOBS_LOCK:
        _JOBS.pop(job_id, None)
    return jsonify({"success": True})


@api_bp.route("/export/reveal", methods=["POST"])
def reveal_export():
    """Open the OS file manager at the given file's location.

    On macOS: ``open -R <path>`` (selects the file in Finder).
    On Linux: ``xdg-open <parent_dir>`` (opens the parent folder; xdg-open
              has no concept of "select this file").
    On Windows: not yet supported (we don't target Windows for MailRepo).

    Body: ``{"path": "<absolute-path-to-saved-file>"}``.

    For safety, we only reveal paths that match the ``saved_path`` of an
    active job — never arbitrary user-provided paths.
    """
    payload = request.get_json() or {}
    path = (payload.get("path") or "").strip()
    if not path:
        return jsonify({"error": "path is required"}), 400

    # Only allow revealing saved_paths from known jobs (defense against an
    # attacker tricking the server into running `open` on something outside
    # MailRepo's exports). We accept a path that matches *any* current job's
    # saved_path.
    with _JOBS_LOCK:
        known_paths = {j.get("saved_path") for j in _JOBS.values() if j.get("saved_path")}
    if path not in known_paths:
        return jsonify({"error": "Unknown export path"}), 403

    if not os.path.exists(path):
        return jsonify({"error": "File no longer exists"}), 404

    try:
        if sys.platform == "darwin":
            # macOS: `open -R` selects the file in Finder
            subprocess.Popen(["open", "-R", path])
        elif sys.platform.startswith("linux"):
            # xdg-open opens the parent directory in the user's file manager.
            # No standard way to select a specific file across all DEs.
            parent = os.path.dirname(path)
            subprocess.Popen(["xdg-open", parent])
        else:
            return jsonify({"error": f"Reveal not supported on {sys.platform}"}), 501
    except FileNotFoundError as e:
        return jsonify({"error": f"File manager not available: {e}"}), 500
    except Exception as e:
        logger.exception("reveal failed")
        return jsonify({"error": str(e)}), 500

    return jsonify({"success": True})
