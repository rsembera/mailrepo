"""
MailRepo — PDF Export

Generates a combined PDF from a list of archived emails using WeasyPrint.

Architecture
------------
Build a single combined HTML document (cover page → email sections →
appendix references), then let WeasyPrint render it in one pass. PDF
attachments are merged onto the back via pypdf in a second step.

The main entry point :func:`build_combined_pdf` is a generator that
yields progress events so the SSE-streaming export endpoint can report
to the UI as work happens.

Failure modes
-------------
Email HTML in the wild is irregular (Outlook MsoNormal, vendor CSS,
malformed nesting, etc.). For robustness we *pre-validate* each email\'s
HTML by trying to parse it with WeasyPrint\'s underlying parser. If that
fails for a given email, we substitute its plain-text body so the email
still appears in the export — uglier but readable. No email is ever
silently dropped.
"""

from __future__ import annotations

import html as html_module
import io
import logging
import re
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Iterable, Iterator

from core import Config, Database, Encryption
from core.message_view import parse_message
from core.pdf_email_html import sanitize_email_html

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Email loading and parsing
# ---------------------------------------------------------------------------


def _decode_header_value(header) -> str:
    """Best-effort decoding of an email header value to a str."""
    if not header:
        return ""
    try:
        parts = decode_header(header)
        out = []
        for content, charset in parts:
            if isinstance(content, bytes):
                out.append(content.decode(charset or "utf-8", errors="replace"))
            else:
                out.append(content)
        return " ".join(out)
    except Exception:
        return str(header)


# S/MIME and PGP signatures and other crypto/protocol artifacts that mail
# clients attach automatically. These aren't user-visible content and just
# clutter the export's attachments folder. Filter at parse time.
_CRYPTO_ATTACHMENT_FILENAMES = {"smime.p7s", "smime.p7m", "signature.asc", "winmail.dat"}
_CRYPTO_ATTACHMENT_TYPES = {
    "application/pkcs7-signature",
    "application/x-pkcs7-signature",
    "application/pkcs7-mime",
    "application/x-pkcs7-mime",
    "application/pgp-signature",
    "application/ms-tnef",
}


def _is_crypto_artifact(filename: str, ctype: str) -> bool:
    """True if this attachment is an S/MIME or similar protocol artifact
    that doesn't need to appear in the export's sibling-files folder."""
    if (filename or "").lower() in _CRYPTO_ATTACHMENT_FILENAMES:
        return True
    if (ctype or "").lower() in _CRYPTO_ATTACHMENT_TYPES:
        return True
    return False


def _export_attachments(parsed_attachments: list[dict]) -> list[dict]:
    """The viewer's attachment list, shaped for the export.

    Comes from core.message_view, the same list every viewer shows, so
    an export lists what the user saw. This module used to have its own
    copy of the rules, and that copy left out images carrying a
    Content-ID the HTML never referenced (code review 2026-11).

    Each entry has ``filename``, ``content_type``, ``data`` (bytes) and
    ``is_pdf``/``is_image`` flags. S/MIME signatures and similar
    crypto/protocol artifacts are skipped: those are mail-client
    metadata, not user content.
    """
    attachments: list[dict] = []
    for att in parsed_attachments:
        filename = att["filename"]
        ctype = att["content_type"]
        if _is_crypto_artifact(filename, ctype) or not att["payload"]:
            continue
        attachments.append(
            {
                "filename": filename,
                "content_type": ctype,
                "data": att["payload"],
                "is_pdf": ctype == "application/pdf" or filename.lower().endswith(".pdf"),
                "is_image": ctype.startswith("image/"),
            }
        )
    return attachments


def _load_email(message_id: int) -> dict | None:
    """Load and decrypt a single archived email by its DB id.

    Returns a dict with keys: ``id``, ``folder_id``, ``folder_name``, ``subject``,
    ``sender``, ``recipients``, ``cc``, ``date_iso``, ``date_display``,
    ``html_body``, ``text_body``, ``attachments``.

    Returns ``None`` if the email cannot be loaded (e.g. file missing).
    """
    row = Database.fetchone(
        """
        SELECT m.id, m.folder_id, m.subject, m.sender, m.date, m.filepath,
               f.name AS folder_name
        FROM messages m
        JOIN folders f ON m.folder_id = f.id
        WHERE m.id = ? AND m.deleted_at IS NULL
        """,
        (message_id,),
    )
    if not row:
        return None

    filepath = Config.get_base_path() / row["filepath"]
    if not filepath.exists():
        logger.warning("Email file missing for message id=%s: %s", message_id, filepath)
        return None

    try:
        raw = Encryption.decrypt(filepath.read_bytes())
        parsed = parse_message(raw, linkify=False)
    except Exception as e:
        logger.warning("Failed to decrypt/parse message id=%s: %s", message_id, e)
        return None

    msg = parsed["msg"]
    html_body, text_body = parsed["html_body"], parsed["text_body"]

    date_str = msg.get("Date", "")
    date_iso = ""
    date_display = date_str
    # The moment the message was sent, for ordering. Falls back to the
    # date recorded when it was archived. Ordering by the ISO text was
    # wrong whenever two messages carried different UTC offsets: 08:00
    # -05:00 sorted before 10:00 +05:00, eight hours out of order.
    date_ts = float(row["date"]) if row["date"] is not None else None
    if date_str:
        try:
            dt = parsedate_to_datetime(date_str)
            date_iso = dt.isoformat()
            date_display = dt.strftime("%Y-%m-%d %H:%M")
            date_ts = dt.timestamp()
        except Exception:
            pass

    return {
        "id": row["id"],
        "folder_id": row["folder_id"],
        "folder_name": row["folder_name"],
        "subject": _decode_header_value(msg.get("Subject", "(no subject)")),
        "sender": _decode_header_value(msg.get("From", "")),
        "recipients": _decode_header_value(msg.get("To", "")),
        "cc": _decode_header_value(msg.get("Cc", "")),
        "date_iso": date_iso,
        "date_ts": date_ts,
        "date_display": date_display,
        "html_body": html_body,
        "text_body": text_body,
        "attachments": _export_attachments(parsed["attachments"]),
        "raw_msg": msg,  # kept for downstream attachment access
    }


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def _esc(s: str | None) -> str:
    """HTML-escape a string, returning empty for None."""
    if not s:
        return ""
    return html_module.escape(s)


def _render_email_section(
    email: dict,
    index: int,
    total: int,
    attachment_refs: list[dict],
    other_attachments: list[dict] | None = None,
) -> str:
    """Build the HTML for one email section in the combined export.

    ``attachment_refs`` is mutated as a side effect: PDF attachments encountered
    here get appended so the caller can later merge them onto the back of the
    rendered PDF. The structure of each entry is::

        {"label": "A", "filename": "contract.pdf", "data": <bytes>, "email_index": 1}

    ``other_attachments``, if provided, is also mutated: image and other
    non-PDF attachments are appended as ``{"filename", "data", "email_index",
    "content_type"}``. The caller decides whether to package them as sibling
    files inside a wrapper ZIP. Pass ``None`` to ignore non-PDF attachments
    (e.g. when the caller can\'t package them anyway).
    """
    body_html = email.get("html_body") or ""
    text_body = email.get("text_body") or ""
    rendered_body = _safe_render_body(body_html, text_body, email_index=index)

    # Attachment markup
    attachment_lines: list[str] = []
    for att in email.get("attachments", []):
        if att["is_pdf"]:
            label = chr(ord("A") + len(attachment_refs))
            attachment_refs.append(
                {
                    "label": label,
                    "filename": att["filename"],
                    "data": att["data"],
                    "email_index": index,
                    "email_subject": email.get("subject", ""),
                }
            )
            attachment_lines.append(
                f'<li><span class="att-icon">📎</span> {_esc(att["filename"])} '
                f'<span class="att-ref">(see Appendix {label})</span></li>'
            )
        elif att["is_image"]:
            if other_attachments is not None:
                other_attachments.append(
                    {
                        "filename": att["filename"],
                        "data": att["data"],
                        "email_index": index,
                        "content_type": att["content_type"],
                    }
                )
                attachment_lines.append(
                    f'<li><span class="att-icon">📎</span> {_esc(att["filename"])} '
                    f'<span class="att-ref">(image \u2014 see attachments/email-{index}/)</span></li>'
                )
            else:
                attachment_lines.append(
                    f'<li><span class="att-icon">📎</span> {_esc(att["filename"])} '
                    f'<span class="att-ref">(image attachment)</span></li>'
                )
        else:
            if other_attachments is not None:
                other_attachments.append(
                    {
                        "filename": att["filename"],
                        "data": att["data"],
                        "email_index": index,
                        "content_type": att["content_type"],
                    }
                )
                attachment_lines.append(
                    f'<li><span class="att-icon">📎</span> {_esc(att["filename"])} '
                    f'<span class="att-ref">(see attachments/email-{index}/)</span></li>'
                )
            else:
                attachment_lines.append(
                    f'<li><span class="att-icon">📎</span> {_esc(att["filename"])}</li>'
                )

    attachments_block = ""
    if attachment_lines:
        attachments_block = (
            '<div class="attachments"><h4>Attachments</h4><ul>'
            + "".join(attachment_lines)
            + "</ul></div>"
        )

    return f"""
        <section class="email-section" id="email-{index}">
            <header class="email-header">
                <div class="email-counter">Email {index} of {total}</div>
                <h2 class="email-subject">{_esc(email.get("subject")) or "(no subject)"}</h2>
                <table class="email-meta">
                    <tr><th>From:</th><td>{_esc(email.get("sender"))}</td></tr>
                    <tr><th>To:</th><td>{_esc(email.get("recipients"))}</td></tr>
                    {f"<tr><th>Cc:</th><td>{_esc(email.get('cc'))}</td></tr>" if email.get("cc") else ""}
                    <tr><th>Date:</th><td>{_esc(email.get("date_display"))}</td></tr>
                    <tr><th>Folder:</th><td>{_esc(email.get("folder_name"))}</td></tr>
                </table>
            </header>
            <div class="email-body">{rendered_body}</div>
            {attachments_block}
        </section>
    """


def _safe_render_body(html_body: str, text_body: str, email_index: int) -> str:
    """Validate HTML for WeasyPrint; fall back to plain text if it\'s no good.

    WeasyPrint renders the entire combined document in one pass, so a single
    broken email could break the whole export. This pre-validates each
    email\'s HTML by trying to parse it; if parsing fails (or there\'s no HTML
    at all), we substitute a plain-text rendering wrapped in ``<pre>``.

    We also CSS-scope the email so its styles don\'t bleed into the cover
    page or other emails: ``<html>``/``<body>`` tags are rewritten to
    ``<div class="email-shell">`` and any ``<style>`` blocks have their
    selectors prefixed with this email\'s scope id.
    """
    if not html_body:
        return _render_plain_text(text_body)

    scope = f"e{email_index}"
    sanitized = _sanitize_email_html(html_body, scope=scope)
    try:
        # Parse-only test with stdlib html.parser. This catches structural
        # errors before WeasyPrint does (which would otherwise abort the
        # whole combined render). Permissive by design: only truly malformed
        # markup will trip this.
        from html.parser import HTMLParser

        class _ValidatingParser(HTMLParser):
            def error(self, message):  # py<3.10
                raise ValueError(message)

        _ValidatingParser(convert_charrefs=True).feed(sanitized)
        # Wrap in a scoped container so any <style> rules we rewrote actually
        # match. The class name carries the scope prefix.
        return f'<div class="email-body-html email-scope-{scope}">{sanitized}</div>'
    except Exception as e:
        logger.warning("Email HTML failed pre-validation, falling back to text: %s", e)
        return _render_plain_text(text_body or _strip_tags(html_body))


def _sanitize_email_html(html: str, *, scope: str) -> str:
    """One email's HTML as a balanced fragment whose styles stay inside it.

    See :mod:`core.pdf_email_html` for what that guards against.
    """
    return sanitize_email_html(html, scope=scope)


def _strip_tags(html: str) -> str:
    """Crude tag stripper for the last-resort fallback."""
    text = re.sub(r"<[^>]+>", "", html)
    text = html_module.unescape(text)
    return text


def _render_plain_text(text: str) -> str:
    """Wrap plain-text content in a styled ``<pre>`` block."""
    if not text:
        return '<div class="email-body-empty">(This email had no readable body.)</div>'
    return f'<pre class="email-body-text">{_esc(text)}</pre>'


def _render_cover_page(scope_label: str, emails: list[dict], export_date: datetime) -> str:
    """Build the cover-page HTML."""
    if not emails:
        date_range = "—"
    else:
        dated = [e for e in emails if e.get("date_iso")]
        if dated:
            dated.sort(key=lambda e: e.get("date_ts") or 0)
            try:
                first = datetime.fromisoformat(dated[0]["date_iso"]).strftime("%b %d, %Y")
                last = datetime.fromisoformat(dated[-1]["date_iso"]).strftime("%b %d, %Y")
                date_range = first if first == last else f"{first} – {last}"
            except Exception:
                date_range = "—"
        else:
            date_range = "—"

    return f"""
        <section class="cover-page">
            <div class="cover-inner">
                <h1 class="cover-title">MailRepo Export</h1>
                <div class="cover-meta">
                    <div class="cover-row"><span class="cover-label">Scope</span><span class="cover-value">{_esc(scope_label)}</span></div>
                    <div class="cover-row"><span class="cover-label">Emails</span><span class="cover-value">{len(emails)}</span></div>
                    <div class="cover-row"><span class="cover-label">Date range</span><span class="cover-value">{_esc(date_range)}</span></div>
                    <div class="cover-row"><span class="cover-label">Exported</span><span class="cover-value">{export_date.strftime("%B %d, %Y at %H:%M")}</span></div>
                </div>
                <div class="cover-footer">Generated by MailRepo</div>
            </div>
        </section>
    """


def _render_appendix_page(refs: list[dict]) -> str:
    """Build the appendix-references page (last page before merged PDFs)."""
    if not refs:
        return ""
    rows = "".join(
        f'<tr><td class="app-label">Appendix {_esc(r["label"])}</td>'
        f'<td class="app-file">{_esc(r["filename"])}</td>'
        f'<td class="app-from">Email {r["email_index"]}: {_esc(r["email_subject"])}</td></tr>'
        for r in refs
    )
    return f"""
        <section class="appendix-page">
            <h2>Appendices</h2>
            <p class="appendix-intro">The following PDF attachments are appended after this page in their original form.</p>
            <table class="appendix-table">
                <thead><tr><th>Appendix</th><th>File</th><th>From</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </section>
    """


# ---------------------------------------------------------------------------
# Combined-document CSS
# ---------------------------------------------------------------------------

_BASE_CSS = """
@page {
    size: letter;
    margin: 0.75in 0.75in 1in 0.75in;
    @bottom-left { content: "MailRepo Export"; font-size: 9pt; color: #666; }
    @bottom-right { content: counter(page) " of " counter(pages); font-size: 9pt; color: #666; }
}

@page :first {
    margin: 0;
    @bottom-left { content: ""; }
    @bottom-right { content: ""; }
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.5;
    color: #222;
}

/* Cover page — explicit background so it can never inherit a stray
   declaration from sanitized email HTML. Each email\'s body styles are
   CSS-scoped to that email\'s container, but a defense-in-depth white
   background here protects the cover page no matter what. */
.cover-page {
    page: cover;
    height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    page-break-after: always;
    background: white;
}
/* Email shells (rewritten <html>/<body>/<head>) fill the available width
   so backgrounds and centered content render the way they did in the
   original email. */
.email-shell {
    display: block;
    width: 100%;
    box-sizing: border-box;
}
.cover-inner { max-width: 5in; }
.cover-title { font-size: 32pt; margin: 0 0 0.5in 0; font-weight: 600; color: #1a3d2e; }
.cover-meta { text-align: left; border-top: 1px solid #ccc; border-bottom: 1px solid #ccc; padding: 0.3in 0; margin-bottom: 0.5in; }
.cover-row { display: flex; padding: 6pt 0; }
.cover-label { width: 1.5in; font-weight: 600; color: #555; }
.cover-value { flex: 1; }
.cover-footer { font-size: 9pt; color: #999; }

/* Email sections */
.email-section { page-break-before: always; }
.email-section:first-of-type { page-break-before: auto; }
.email-header { border-bottom: 1.5pt solid #1a3d2e; padding-bottom: 8pt; margin-bottom: 14pt; }
.email-counter { font-size: 9pt; color: #888; text-transform: uppercase; letter-spacing: 0.5pt; margin-bottom: 4pt; }
.email-subject { font-size: 16pt; font-weight: 600; margin: 0 0 8pt 0; color: #1a3d2e; }
.email-meta { font-size: 9.5pt; border-collapse: collapse; }
.email-meta th { text-align: left; font-weight: 600; color: #555; padding: 1pt 8pt 1pt 0; vertical-align: top; width: 0.6in; }
.email-meta td { padding: 1pt 0; vertical-align: top; }

.email-body { word-wrap: break-word; overflow-wrap: break-word; }
.email-body-html { max-width: 100%; }
.email-body-html img { max-width: 100% !important; height: auto !important; }

/* Email HTML compatibility shims for WeasyPrint:
   1. <table width="100%"> doesn't reliably fill its container without an
      explicit CSS width rule. We promote the HTML attribute to CSS.
   2. <td align="center"> doesn't center block-level descendants (like
      nested tables) the way browsers do. Add margin: auto so nested
      tables center inside aligned cells.
   These rules are scoped to .email-body-html so they don't affect the
   cover page or appendix tables. */
.email-body-html table[width="100%"] { width: 100% !important; }
.email-body-html td[align="center"] > table {
    margin-left: auto !important;
    margin-right: auto !important;
}
.email-body-text { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 9.5pt; white-space: pre-wrap; word-wrap: break-word; background: #f7f7f7; padding: 8pt; border-radius: 3pt; }
.email-body-empty { color: #999; font-style: italic; }

.attachments { margin-top: 16pt; padding-top: 8pt; border-top: 1px dashed #bbb; font-size: 9.5pt; }
.attachments h4 { margin: 0 0 4pt 0; font-size: 10pt; color: #555; }
.attachments ul { list-style: none; padding: 0; margin: 0; }
.attachments li { padding: 2pt 0; }
.att-icon { color: #888; }
.att-ref { color: #888; font-style: italic; }

/* Appendix page */
.appendix-page { page-break-before: always; }
.appendix-page h2 { color: #1a3d2e; }
.appendix-intro { color: #555; font-size: 10pt; }
.appendix-table { border-collapse: collapse; width: 100%; margin-top: 12pt; font-size: 10pt; }
.appendix-table th { text-align: left; border-bottom: 1pt solid #1a3d2e; padding: 4pt 8pt; }
.appendix-table td { padding: 4pt 8pt; border-bottom: 1px solid #eee; }
.app-label { font-weight: 600; white-space: nowrap; }
.app-file { font-family: ui-monospace, monospace; font-size: 9.5pt; }
.app-from { color: #555; }
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_combined_pdf(
    message_ids: Iterable[int],
    *,
    scope_label: str = "Selected emails",
    sort_order: str = "chronological",
    include_cover: bool = True,
    load_remote: bool = False,
) -> Iterator[dict]:
    """Build a combined PDF from a list of archived email ids.

    This is a generator. Callers consume progress events (``{"event": ...,
    "data": {...}}``). The terminal ``"complete"`` event carries
    ``{"pdf_bytes": <bytes>, "filename_hint": <str>}`` — the caller is
    responsible for serving / saving those bytes.

    Args:
        message_ids: archived email ids to include.
        scope_label: human-readable description of what was exported.
            Shown on the cover page.
        sort_order: ``"chronological"`` (default, oldest first) or
            ``"reverse_chronological"`` (newest first).
        include_cover: if False, skip the cover page.
        load_remote: if True, allow WeasyPrint to fetch remote http(s) URLs
            referenced in email HTML (e.g. ``<img src="https://...">``).
            Default False — slower exports and a privacy leak otherwise.
            Inline (cid:) images are unaffected; those resolve to data URLs.

    Yields:
        Progress dicts. Event names: ``status``, ``progress``, ``complete``,
        ``error``.
    """
    from weasyprint import CSS, HTML

    ids = list(message_ids)
    total = len(ids)
    if not total:
        yield {"event": "error", "data": {"error": "No emails to export"}}
        return

    # ---- Phase 1: load and decrypt --------------------------------------
    plural = "s" if total != 1 else ""
    yield {
        "event": "status",
        "data": {"phase": "loading", "message": f"Loading {total} email{plural}..."},
    }
    emails: list[dict] = []
    for i, mid in enumerate(ids, start=1):
        loaded = _load_email(mid)
        if loaded is not None:
            emails.append(loaded)
        yield {
            "event": "progress",
            "data": {
                "phase": "loading",
                "current": i,
                "total": total,
                "percent": int(i / total * 30),  # loading is ~30% of work
            },
        }

    if not emails:
        yield {"event": "error", "data": {"error": "Failed to load any emails"}}
        return

    # ---- Phase 2: sort ---------------------------------------------------
    def sort_key(e: dict):
        ts = e.get("date_ts")
        return ts if ts is not None else float("-inf")  # undated first, as before

    emails.sort(key=sort_key, reverse=(sort_order == "reverse_chronological"))

    # ---- Phase 3: build combined HTML -----------------------------------
    yield {"event": "status", "data": {"phase": "rendering", "message": "Rendering PDF..."}}

    export_date = datetime.now()
    parts: list[str] = []
    if include_cover:
        parts.append(_render_cover_page(scope_label, emails, export_date))

    attachment_refs: list[dict] = []
    other_attachments: list[dict] = []
    for idx, em in enumerate(emails, start=1):
        parts.append(
            _render_email_section(em, idx, len(emails), attachment_refs, other_attachments)
        )
        if idx % 10 == 0 or idx == len(emails):
            yield {
                "event": "progress",
                "data": {
                    "phase": "rendering",
                    "current": idx,
                    "total": len(emails),
                    "percent": 30 + int(idx / len(emails) * 50),  # rendering is ~50%
                },
            }

    if attachment_refs:
        parts.append(_render_appendix_page(attachment_refs))

    full_html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        "<title>MailRepo Export</title></head><body>" + "".join(parts) + "</body></html>"
    )

    # ---- Phase 4: WeasyPrint render -------------------------------------
    # WeasyPrint runs synchronously with no progress callbacks, so we can\'t
    # increment the bar during the render. Tell the UI to switch to an
    # indeterminate "pulsing" mode so the user knows we\'re still working.
    yield {
        "event": "status",
        "data": {
            "phase": "weasyprint",
            "message": f"Composing PDF ({len(emails)} emails)\u2026 this can take a moment.",
            "indeterminate": True,
        },
    }
    try:
        # Never WeasyPrint's default fetcher: it resolves file:// URLs, and
        # an email's <link rel="attachment" href="file:///..."> would embed
        # a local file in the PDF. core.pdf_fetcher confines every render
        # to data: (always) and http(s): (only when "Load remote" is on).
        from core.pdf_fetcher import make_url_fetcher

        _fetcher = make_url_fetcher(load_remote)

        # Blocked resources come back as empty images. WeasyPrint still
        # logs oddities for some of them, and on a real folder export
        # that floods the terminal. Temporarily raise its logger threshold
        # so only CRITICAL gets through; real problems still surface via
        # the outer try/except.
        wp_logger = logging.getLogger("weasyprint")
        prev_level = wp_logger.level
        wp_logger.setLevel(logging.CRITICAL)
        try:
            pdf_bytes = HTML(string=full_html, url_fetcher=_fetcher).write_pdf(
                stylesheets=[CSS(string=_BASE_CSS)]
            )
        finally:
            wp_logger.setLevel(prev_level)
    except Exception as e:
        logger.exception("WeasyPrint render failed")
        yield {"event": "error", "data": {"error": f"PDF rendering failed: {e}"}}
        return

    yield {
        "event": "progress",
        "data": {"phase": "weasyprint", "percent": 85, "indeterminate": False},
    }

    # ---- Phase 5: append PDF attachments via pypdf ----------------------
    if attachment_refs:
        app_word = "appendices" if len(attachment_refs) != 1 else "appendix"
        yield {
            "event": "status",
            "data": {
                "phase": "appendices",
                "message": f"Attaching {len(attachment_refs)} {app_word}...",
            },
        }
        pdf_bytes = _append_pdf_attachments(pdf_bytes, attachment_refs)

    yield {"event": "progress", "data": {"phase": "done", "percent": 100}}

    safe_scope = re.sub(r"[^A-Za-z0-9_\- ]", "_", scope_label)[:40].strip() or "export"
    date_stamp = export_date.strftime("%Y%m%d_%H%M")
    filename_hint = f"{safe_scope}_{date_stamp}.pdf"

    yield {
        "event": "complete",
        "data": {
            "pdf_bytes": pdf_bytes,
            "filename_hint": filename_hint,
            "email_count": len(emails),
            # Selected but not in the PDF: file missing, unreadable, or
            # trashed since the selection was made.
            "skipped_count": total - len(emails),
            "appendix_count": len(attachment_refs),
            # Non-PDF attachments (images and other types) for the caller to
            # package alongside the PDF as sibling files. The caller may
            # ignore these if it can\'t package them \u2014 the email body
            # already lists them by name.
            "other_attachments": other_attachments,
        },
    }


PDF_ATTACHMENT_PARSE_TIMEOUT_SECONDS = 30


def _read_pdf_pages_with_timeout(PdfReader, data: bytes, filename: str, timeout=None):
    """Parse ``data`` with pypdf on a worker thread; None if it fails or overruns."""
    import threading

    timeout = PDF_ATTACHMENT_PARSE_TIMEOUT_SECONDS if timeout is None else timeout
    result: dict = {}

    def work():
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                result["skip"] = "encrypted"
                return
            result["pages"] = list(reader.pages)
        except Exception as e:  # noqa: BLE001
            result["error"] = e

    t = threading.Thread(target=work, name="pdf-attachment-parse", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        logger.warning("Skipping PDF attachment %s: parse exceeded %ss", filename, timeout)
        return None
    if "skip" in result:
        logger.info("Skipping encrypted PDF attachment: %s", filename)
        return None
    if "error" in result:
        logger.warning("Skipping unreadable PDF attachment %s: %s", filename, result["error"])
        return None
    return result.get("pages")


def _append_pdf_attachments(main_pdf: bytes, refs: list[dict]) -> bytes:
    """Append each PDF attachment onto the back of ``main_pdf`` using pypdf.

    Bad attachments (corrupt, encrypted, not actually a PDF) are silently
    skipped — they\'re still listed in the appendix table on the main PDF,
    so the user can see something\'s amiss.

    pypdf logs a WARNING for every minor structural irregularity it
    encounters ("Ignoring wrong pointing object", etc.). For exports with
    many attachments these warnings flood the terminal even though pypdf
    handles them gracefully and the merge succeeds. Silence them at the
    logger level for the duration of the merge \u2014 actual unrecoverable
    failures still raise exceptions and surface via the try/except below.
    """
    from pypdf import PdfReader, PdfWriter

    pypdf_logger = logging.getLogger("pypdf")
    prev_level = pypdf_logger.level
    pypdf_logger.setLevel(logging.ERROR)
    try:
        writer = PdfWriter()
        try:
            for page in PdfReader(io.BytesIO(main_pdf)).pages:
                writer.add_page(page)
        except Exception:
            # If we can\'t even read what WeasyPrint produced, return the original
            return main_pdf

        for ref in refs:
            # Each attachment is parsed on a worker thread with a wall-clock
            # limit. pypdf has had a run of infinite-loop advisories on
            # crafted input, and the export runs in a daemon thread with no
            # other timeout, so one bad attachment would otherwise pin the
            # export forever (security review 2026-09, #19). A parse that
            # overruns is skipped; its (daemon) thread is abandoned.
            pages = _read_pdf_pages_with_timeout(PdfReader, ref["data"], ref["filename"])
            if pages is None:
                continue
            for page in pages:
                writer.add_page(page)

        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    finally:
        pypdf_logger.setLevel(prev_level)
