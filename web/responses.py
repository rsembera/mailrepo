"""
Response helpers for content that came from an email.

Attachments are the one place where bytes an attacker chose are handed
straight to a browser from the app's own origin. The MIME part's own
Content-Type must never decide how the browser treats them: a text/html
or image/svg+xml attachment opened "inline" is a page running script in
the same origin as the archive, with the session cookie and the CSRF
token within reach.

So: only a short list of harmless types is ever served inline, and
those go out with a sandboxing CSP and nosniff. Everything else is a
download, and the browser is told not to guess.
"""

import io

from flask import Response, send_file

# Types a browser may render as a top-level document from this origin.
# All of these are inert: none can carry script or load subresources.
INLINE_TYPES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "text/plain",
    }
)

_NOSNIFF = "nosniff"


def normalize_content_type(content_type: str | None) -> str:
    """Lowercase media type with parameters stripped; octet-stream if empty."""
    if not content_type:
        return "application/octet-stream"
    return content_type.split(";", 1)[0].strip().lower() or "application/octet-stream"


def attachment_response(
    payload: bytes, content_type: str | None, filename: str, *, inline: bool
) -> Response:
    """Build a response for an email attachment.

    ``inline`` is honoured only for types in INLINE_TYPES. The filename is
    encoded by werkzeug (RFC 6266/5987), so quotes and non-ASCII in a
    MIME filename cannot break or smuggle into the header.
    """
    media_type = normalize_content_type(content_type)
    serve_inline = inline and media_type in INLINE_TYPES

    resp = send_file(
        io.BytesIO(payload or b""),
        mimetype=media_type if serve_inline else "application/octet-stream",
        as_attachment=not serve_inline,
        download_name=filename or "attachment",
        max_age=0,
        conditional=False,
        etag=False,
    )
    resp.headers["X-Content-Type-Options"] = _NOSNIFF
    resp.headers["Cache-Control"] = "no-store"
    if serve_inline and media_type != "application/pdf":
        # A sandboxed document with no origin and no permitted
        # subresources. Not applied to PDFs: Chromium's viewer is an
        # embedded plugin and object-src 'none' / sandbox would blank it;
        # a PDF cannot reach the DOM anyway.
        resp.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return resp


def eml_download(raw_bytes: bytes, filename: str) -> Response:
    """A raw .eml as a download."""
    resp = send_file(
        io.BytesIO(raw_bytes),
        mimetype="message/rfc822",
        as_attachment=True,
        download_name=filename,
        max_age=0,
        conditional=False,
        etag=False,
    )
    resp.headers["X-Content-Type-Options"] = _NOSNIFF
    resp.headers["Cache-Control"] = "no-store"
    return resp
