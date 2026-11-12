"""
core/message_view.py: one parser behind every message view and every
attachment download (code review 2026-11, findings 9, 14, 16, 19).
"""

import time
from email.message import EmailMessage

import pytest

from core import IMAP, Database, ImapPool
from core.message_view import attachment_at, linkify_html, parse_message, view_fields

PNG = b"\x89PNG-image-bytes"
PDF = b"%PDF-pdf-bytes"


def _base(html=None):
    m = EmailMessage()
    m["Subject"] = "s"
    m["From"] = "a@b.c"
    m["To"] = "d@e.f"
    m["Message-ID"] = "<m@x>"
    m.set_content("plain body")
    if html is not None:
        m.add_alternative(html, subtype="html")
    return m


def _gmail_mobile():
    """An image with a Content-ID the HTML never references, then a PDF."""
    m = _base("<p>see attached</p>")
    m.add_attachment(PNG, maintype="image", subtype="png", filename="photo.png", cid="<abc123>")
    m.add_attachment(PDF, maintype="application", subtype="pdf", filename="report.pdf")
    return m.as_bytes()


def _names(raw):
    return [a["filename"] for a in view_fields(raw)["attachments"]]


class TestListingAndDownloadAgree:
    def test_every_listed_attachment_downloads_as_itself(self):
        raw = _gmail_mobile()
        assert _names(raw) == ["photo.png", "report.pdf"]
        assert attachment_at(raw, 0)["payload"] == PNG
        assert attachment_at(raw, 1)["payload"] == PDF
        assert attachment_at(raw, 2) is None
        assert attachment_at(raw, -1) is None

    def test_imap_route_serves_the_attachment_that_was_listed(
        self, authenticated_client, initialized_app, monkeypatch
    ):
        """Clicking photo.png used to return the PDF; report.pdf was a 404."""
        cur = Database.execute(
            "INSERT INTO accounts (name, email, provider) VALUES ('A', 'a@example.com', 'imap')"
        )
        Database.commit()
        IMAP.save_credentials(cur.lastrowid, "a@example.com", "pw", "imap.example.com", 993, True)
        raw = _gmail_mobile()

        class Client:
            def select_folder(self, folder):
                return {}

            def fetch_raw(self, uid):
                return raw

            def release(self):
                pass

        monkeypatch.setattr(ImapPool, "acquire", classmethod(lambda cls, a, c: Client()))
        base = f"/api/accounts/{cur.lastrowid}/emails/5/attachments"
        assert authenticated_client.get(f"{base}/0?folder=INBOX").data == PNG
        assert authenticated_client.get(f"{base}/1?folder=INBOX").data == PDF
        assert authenticated_client.get(f"{base}/2?folder=INBOX").status_code == 404

    def test_live_imap_view_uses_the_same_rules(self):
        client = IMAP("x")
        client.fetch_raw = lambda uid: _gmail_mobile()
        full = client.fetch_full("9")
        assert full["uid"] == "9"
        assert [a["filename"] for a in full["attachments"]] == ["photo.png", "report.pdf"]


class TestAttachmentRules:
    def test_inline_disposition_with_a_filename_is_listed(self):
        """Apple Mail sends PDFs this way; the live IMAP view dropped them."""
        m = _base()
        m.add_attachment(
            PDF, maintype="application", subtype="pdf", filename="scan.pdf", disposition="inline"
        )
        assert _names(m.as_bytes()) == ["scan.pdf"]

    def test_referenced_inline_image_is_embedded_not_listed(self):
        m = _base('<p><img src="cid:logo1"></p>')
        m.add_attachment(PNG, maintype="image", subtype="png", filename="logo.png", cid="<logo1>")
        fields = view_fields(m.as_bytes())
        assert fields["attachments"] == []
        assert "data:image/png;base64," in fields["html_body"]
        assert "cid:logo1" not in fields["html_body"]

    def test_attached_message_is_offered_whole_and_not_merged_into_the_body(self):
        inner = EmailMessage()
        inner["Subject"] = "inner"
        inner["From"] = "x@y.z"
        inner.set_content("INNER BODY TEXT")
        inner.add_attachment(PDF, maintype="application", subtype="pdf", filename="inner.pdf")
        m = _base()
        m.add_attachment(inner, filename="forwarded.eml")

        fields = view_fields(m.as_bytes())
        assert "INNER BODY TEXT" not in (fields["text_body"] or "")
        assert [a["filename"] for a in fields["attachments"]] == ["forwarded.eml"]
        payload = attachment_at(m.as_bytes(), 0)["payload"]
        assert b"INNER BODY TEXT" in payload and b"Subject: inner" in payload

    def test_a_message_that_is_only_a_pdf_lists_it(self):
        m = EmailMessage()
        m["Subject"] = "scan"
        m.set_content(PDF, maintype="application", subtype="pdf")
        fields = view_fields(m.as_bytes())
        assert fields["text_body"] is None
        assert [a["content_type"] for a in fields["attachments"]] == ["application/pdf"]
        assert attachment_at(m.as_bytes(), 0)["payload"] == PDF

    def test_a_declared_attachment_without_a_name_is_still_offered(self):
        raw = (
            b"Subject: s\r\nMIME-Version: 1.0\r\n"
            b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
            b"--b\r\nContent-Type: text/plain\r\n\r\nbody\r\n"
            b"--b\r\nContent-Type: application/octet-stream\r\n"
            b"Content-Disposition: attachment\r\n\r\nDATA\r\n--b--\r\n"
        )
        assert _names(raw) == ["attachment"]

    def test_text_parts_are_concatenated_in_order(self):
        raw = (
            b"Subject: s\r\nMIME-Version: 1.0\r\n"
            b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
            b"--b\r\nContent-Type: text/plain\r\n\r\nfirst\r\n"
            b"--b\r\nContent-Type: text/plain\r\n\r\nsecond\r\n--b--\r\n"
        )
        text = parse_message(raw)["text_body"]
        assert text.index("first") < text.index("second")


class TestLinkify:
    def test_plain_urls_and_addresses_become_links(self):
        out = linkify_html("<p>see https://example.com/a?b=1&c=2 or mail me@example.com</p>")
        assert (
            '<a href="https://example.com/a?b=1&c=2" target="_blank" rel="noopener noreferrer">'
            in out
        )
        assert '<a href="mailto:me@example.com">me@example.com</a>' in out

    def test_existing_links_are_left_alone(self):
        html = '<a href="https://example.com">https://example.com</a>'
        assert linkify_html(html) == html

    def test_a_url_stops_at_an_entity(self):
        out = linkify_html("<p>https://example.com&nbsp;next</p>")
        assert '<a href="https://example.com" ' in out

    def test_an_address_inside_a_url_is_not_linked_twice(self):
        out = linkify_html("<p>https://example.com/?to=me@example.com</p>")
        assert out.count("<a ") == 1

    @pytest.mark.parametrize("tag", ["style", "script", "textarea", "title"])
    def test_non_page_text_is_untouched(self, tag):
        html = (
            f"<{tag}>.h{{background:url(https://example.com/a.png)}} me@example.com</{tag}><p>x</p>"
        )
        assert linkify_html(html) == html

    def test_text_after_a_skipped_element_is_linkified_again(self):
        out = linkify_html("<style>a{}</style><p>https://example.com</p>")
        assert out.count("<a href") == 1

    @pytest.mark.parametrize(
        "hostile",
        [
            "<a x>" * 40_000,  # unclosed anchors: 34 s before the rewrite
            "<" * 200_000,  # opening brackets that never close
            "a." * 100_000,  # address-like run with no @
            ("a." * 50_000) + "@",
            "<!--" * 50_000,
        ],
    )
    def test_hostile_markup_is_handled_in_linear_time(self, hostile):
        start = time.perf_counter()
        linkify_html(hostile)
        assert time.perf_counter() - start < 2.0


class _Conn:
    """imaplib stand-in that records the FETCH and returns a canned reply."""

    def __init__(self, data):
        self.data = data
        self.calls = []

    def uid(self, *args):
        self.calls.append(args)
        return "OK", self.data


class TestFetchRaw:
    def test_fetch_does_not_mark_the_message_read(self):
        client = IMAP("x")
        client.connection = _Conn([(b"1 (UID 7 BODY[] {5}", b"hello"), b")"])
        assert client.fetch_raw("7") == b"hello"
        fetch_items = client.connection.calls[0][2]
        assert "BODY.PEEK[]" in fetch_items
        assert "RFC822" not in fetch_items

    def test_an_interleaved_flag_update_is_not_mistaken_for_the_message(self):
        client = IMAP("x")
        client.connection = _Conn(
            [
                b"3 (UID 99 FLAGS (\\Seen))",
                (b"4 (UID 8 BODY[] {5}", b"other"),
                (b"5 (UID 7 BODY[] {5}", b"right"),
                b")",
            ]
        )
        assert client.fetch_raw("7") == b"right"
