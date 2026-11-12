"""
MailRepo - Turning a raw message into what the viewer shows.

One parser for the three places a message is displayed (a live IMAP
message, an archived message, an import preview) and for the three
attachment-download routes that go with them.

Before this there were six hand-synced copies with three different
rules, and they had drifted: the live IMAP view listed an attachment
that its download route did not count, so clicking one attachment
returned another (code review 2026-11, #9); attachments sent as
``Content-Disposition: inline`` were missing from the live view (#16);
and the import preview hid images the other two showed. The listing
and the download now come from the same list, so the index that was
clicked is the file that is served.

The rules, in one place:

* An image part with a Content-ID is an inline image only if the HTML
  body actually references that id (``cid:...``). It is then embedded
  as a data URL and not listed. Otherwise it is an attachment.
* A part is an attachment if its disposition says so, or if it has a
  filename and is not text, or if it is an attached message
  (message/rfc822). Attached messages are offered whole, as .eml, and
  their contents are not merged into the body of the outer message.
* Every other text/plain and text/html part is body, concatenated in
  order.
"""

import base64
import email as email_lib
import re
from email.header import decode_header

_CID_REF = re.compile(r'cid:([^"\'\s>]+)')


def decode_header_value(header) -> str:
    """Decode an RFC 2047 header value to text."""
    if not header:
        return ""
    try:
        decoded = []
        for content, charset in decode_header(str(header)):
            if isinstance(content, bytes):
                try:
                    decoded.append(content.decode(charset or "utf-8", errors="replace"))
                except LookupError:  # a charset Python does not know
                    decoded.append(content.decode("utf-8", errors="replace"))
            else:
                decoded.append(content)
        return " ".join(decoded)
    except Exception:
        return str(header)


# ---------------------------------------------------------------------------
# Linkify
# ---------------------------------------------------------------------------

# Text inside these elements is never rewritten: an existing link, and
# places where the "text" is code or is not shown as page text at all.
_NO_LINKIFY = frozenset({"a", "style", "script", "textarea", "title", "head"})

_TAG_NAME = re.compile(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9]*)")

# URL: up to whitespace, quotes, angle brackets, or an HTML entity
# (&nbsp; &amp; ...), while still allowing a bare & in a query string.
# Email: bounded repeats, so a long run of address-like characters with
# no @ cannot make the scan quadratic.
_URL_OR_EMAIL = re.compile(
    r'(?P<url>https?://(?:(?!&(?:nbsp|amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)[^\s <>"\'])+)'
    r"|(?P<email>(?<![a-zA-Z0-9._%+\-])[a-zA-Z0-9._%+\-]{1,64}@[a-zA-Z0-9.\-]{1,253}\.[a-zA-Z]{2,24}\b)"
)


def _link(match) -> str:
    url = match.group("url")
    if url:
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{url}</a>'
    address = match.group("email")
    return f'<a href="mailto:{address}">{address}</a>'


def _html_tokens(html: str):
    """Yield ``(is_tag, text)`` pieces of an HTML string in one pass.

    Deliberately not a regex over the whole document. The previous
    version split on ``<a ...>.*?</a>``, which rescans to the end of the
    document for every unclosed ``<a``: a 200 KB message built that way
    held the interpreter for half a minute and froze the whole app
    (code review 2026-11, #14).
    """
    pos = 0
    n = len(html)
    while pos < n:
        lt = html.find("<", pos)
        if lt == -1:
            yield False, html[pos:]
            return
        if lt > pos:
            yield False, html[pos:lt]
        if html.startswith("<!--", lt):
            end = html.find("-->", lt + 4)
            end = n if end == -1 else end + 3
        else:
            gt = html.find(">", lt + 1)
            if gt == -1:
                # A "<" with no ">" anywhere after it: the rest is text,
                # and there is nothing further to find.
                yield False, html[lt:]
                return
            end = gt + 1
        yield True, html[lt:end]
        pos = end


def linkify_html(html: str) -> str:
    """Make plain URLs and email addresses in HTML text clickable.

    Only text that is shown as page text is touched. Existing links, and
    the contents of <style>, <script>, <textarea>, <title> and <head>,
    are left exactly as they are.
    """
    if not html:
        return html
    out = []
    skipping = None  # name of the element whose contents are being left alone
    for is_tag, piece in _html_tokens(html):
        if is_tag:
            out.append(piece)
            m = _TAG_NAME.match(piece)
            if not m:
                continue
            closing, name = m.group(1), m.group(2).lower()
            if skipping is None:
                if not closing and name in _NO_LINKIFY and not piece.rstrip().endswith("/>"):
                    skipping = name
            elif closing and name == skipping:
                skipping = None
            continue
        if skipping is not None or ("@" not in piece and "://" not in piece):
            out.append(piece)
        else:
            out.append(_URL_OR_EMAIL.sub(_link, piece))
    return "".join(out)


# ---------------------------------------------------------------------------
# The view
# ---------------------------------------------------------------------------


def _decode_text(part) -> str:
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _leaf_parts(msg):
    """Depth-first parts of a message, treating an attached message as a leaf."""
    if msg.get_content_type() == "message/rfc822":
        yield msg
        return
    if msg.is_multipart():
        for sub in msg.get_payload():
            yield from _leaf_parts(sub)
        return
    yield msg


def _attached_message_bytes(part) -> bytes:
    payload = part.get_payload()
    if isinstance(payload, list) and payload:
        try:
            return payload[0].as_bytes()
        except Exception:
            return b""
    return part.get_payload(decode=True) or b""


def parse_message(raw: bytes, linkify: bool = True) -> dict:
    """Parse a raw message into bodies and an ordered attachment list.

    Returns a dict with ``msg`` (the parsed message, for headers),
    ``text_body``, ``html_body`` (cid: references resolved, linkified)
    and ``attachments``: a list of ``{"filename", "content_type",
    "payload"}`` in the order every route presents them.
    """
    msg = email_lib.message_from_bytes(raw)
    top_is_container = msg.is_multipart() and msg.get_content_type() != "message/rfc822"
    parts = list(_leaf_parts(msg)) if top_is_container else [msg]

    html_parts = [p for p in parts if p.get_content_type() == "text/html"]
    referenced = set()
    for p in html_parts:
        if "attachment" not in str(p.get("Content-Disposition", "")).lower():
            referenced.update(_CID_REF.findall(_decode_text(p)))

    inline_images = {}
    text_body = None
    html_body = None
    attachments = []

    for part in parts:
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition", "")).lower()
        filename = part.get_filename()
        content_id = (part.get("Content-ID") or "").strip().strip("<>")

        if content_id and content_id in referenced:
            payload = part.get_payload(decode=True)
            if payload:
                b64 = base64.b64encode(payload).decode("ascii")
                inline_images[content_id] = f"data:{content_type};base64,{b64}"
            if content_type.startswith("image/"):
                continue  # shown in place; not offered as an attachment

        if content_type == "message/rfc822":
            name = decode_header_value(filename) or "attached message.eml"
            attachments.append(
                {
                    "filename": name,
                    "content_type": content_type,
                    "payload": _attached_message_bytes(part),
                }
            )
            continue

        is_text = part.get_content_maintype() == "text"
        declared = "attachment" in disposition
        if declared or not is_text:
            # Inside a multipart message, a non-text part with no name and
            # no declaration is structural (a signature, a stray related
            # part) and is not offered. A message that IS a single
            # non-text part (a bare PDF or image) has nothing else to
            # show, so it is listed.
            if declared or filename or not top_is_container:
                attachments.append(
                    {
                        "filename": decode_header_value(filename) or "attachment",
                        "content_type": content_type,
                        "payload": part.get_payload(decode=True) or b"",
                    }
                )
            continue

        if content_type == "text/plain":
            text_body = (text_body or "") + _decode_text(part)
        elif content_type == "text/html":
            html_body = (html_body or "") + _decode_text(part)

    if html_body and inline_images:
        html_body = _CID_REF.sub(
            lambda m: inline_images.get(m.group(1), m.group(0)), html_body
        )
    if html_body and linkify:
        html_body = linkify_html(html_body)

    return {
        "msg": msg,
        "text_body": text_body,
        "html_body": html_body,
        "attachments": attachments,
    }


def view_fields(raw: bytes) -> dict:
    """The JSON-ready fields every viewer route returns for a message."""
    parsed = parse_message(raw)
    msg = parsed["msg"]
    return {
        "subject": decode_header_value(msg.get("Subject", "")),
        "from": decode_header_value(msg.get("From", "")),
        "to": decode_header_value(msg.get("To", "")),
        "cc": decode_header_value(msg.get("Cc", "")),
        "date": msg.get("Date", ""),
        "message_id": msg.get("Message-ID", ""),
        "text_body": parsed["text_body"],
        "html_body": parsed["html_body"],
        "attachments": [
            {
                "filename": a["filename"],
                "content_type": a["content_type"],
                "size": len(a["payload"]),
            }
            for a in parsed["attachments"]
        ],
    }


def attachment_at(raw: bytes, index: int) -> dict | None:
    """The attachment at ``index`` in the list ``view_fields`` reported."""
    attachments = parse_message(raw)["attachments"]
    if not isinstance(index, int) or index < 0 or index >= len(attachments):
        return None
    return attachments[index]
