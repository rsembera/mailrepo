"""
Security review 2026-09, finding 3: a PDF export must never embed a local
file named by an email, in either fetch mode.
"""

import io

import pytest

from core.pdf_export import _sanitize_email_html
from core.pdf_fetcher import allowed_schemes, make_url_fetcher, scheme_of

SECRET = b"SECRET-KEY-MATERIAL-8f3a"


@pytest.fixture
def secret_file(tmp_path):
    p = tmp_path / "salt.bin"
    p.write_bytes(SECRET)
    return p


def _attachments(pdf_bytes):
    from pypdf import PdfReader

    return PdfReader(io.BytesIO(pdf_bytes)).attachments


class TestSchemes:
    def test_scheme_of(self):
        assert scheme_of("FILE:///x") == "file"
        assert scheme_of("data:image/png;base64,AAAA") == "data"
        assert scheme_of("relative/path.png") == ""
        assert scheme_of("") == ""

    def test_allowed(self):
        assert allowed_schemes(False) == {"data"}
        assert allowed_schemes(True) == {"data", "http", "https"}


class TestFetcher:
    @pytest.mark.parametrize("load_remote", [False, True])
    def test_file_url_is_not_fetched(self, secret_file, load_remote):
        fetcher = make_url_fetcher(load_remote)
        resp = fetcher(f"file://{secret_file}")
        body = resp.read() if hasattr(resp, "read") else resp["string"]
        assert body == b""

    def test_data_url_is_fetched(self):
        fetcher = make_url_fetcher(False)
        resp = fetcher("data:text/plain,hello")
        body = resp.read() if hasattr(resp, "read") else resp["string"]
        assert body == b"hello"

    def test_http_blocked_without_remote(self):
        # Must not even attempt the network: an empty image comes back.
        resp = make_url_fetcher(False)("http://127.0.0.1:1/pixel.gif")
        body = resp.read() if hasattr(resp, "read") else resp["string"]
        assert body == b""


class TestWeasyPrintEndToEnd:
    @pytest.mark.parametrize("load_remote", [False, True])
    def test_link_attachment_cannot_embed_local_file(self, secret_file, load_remote):
        from weasyprint import HTML

        html = (
            f'<html><head><link rel="attachment" href="file://{secret_file}"></head>'
            f'<body><img src="file://{secret_file}"><p>hi</p></body></html>'
        )
        pdf = HTML(string=html, url_fetcher=make_url_fetcher(load_remote)).write_pdf()
        for _name, chunks in _attachments(pdf).items():
            assert SECRET not in b"".join(chunks)

    def test_default_fetcher_would_have_leaked(self, secret_file):
        """Documents why the guard exists; if WeasyPrint ever closes this
        itself, the guard is still harmless."""
        from weasyprint import HTML

        html = f'<html><head><link rel="attachment" href="file://{secret_file}"></head><body>x</body></html>'
        pdf = HTML(string=html).write_pdf()
        leaked = any(SECRET in b"".join(c) for c in _attachments(pdf).values())
        assert leaked, "WeasyPrint default fetcher no longer embeds file:// — guard still fine"


class TestSanitizer:
    def test_link_elements_are_stripped(self):
        html = '<html><head><link rel="attachment" href="file:///etc/passwd"><link rel="stylesheet" href="http://x/y.css"/></head><body><p>hi</p></body></html>'
        out = _sanitize_email_html(html, scope="e1")
        assert "<link" not in out.lower()
        assert "rel=" not in out.lower()
        assert "<p>hi</p>" in out

    def test_style_survives(self):
        out = _sanitize_email_html("<style>p{color:red}</style><p>x</p>", scope="e1")
        assert "<style>" in out


class TestPdfAttachmentParseTimeout:
    """Security review 2026-09, #19: a crafted PDF attachment must not pin
    the export thread forever."""

    def test_overrunning_parse_is_skipped(self):
        import time

        from core.pdf_export import _read_pdf_pages_with_timeout

        class Hangs:
            def __init__(self, _f):
                time.sleep(5)

        t0 = time.monotonic()
        assert _read_pdf_pages_with_timeout(Hangs, b"%PDF", "x.pdf", timeout=0.2) is None
        assert time.monotonic() - t0 < 2

    def test_good_pdf_returns_pages(self):
        from pypdf import PdfReader
        from weasyprint import HTML

        from core.pdf_export import _read_pdf_pages_with_timeout

        pdf = HTML(string="<p>one</p>").write_pdf()
        pages = _read_pdf_pages_with_timeout(PdfReader, pdf, "ok.pdf")
        assert pages is not None and len(pages) == 1

    def test_garbage_is_skipped(self):
        from pypdf import PdfReader

        from core.pdf_export import _read_pdf_pages_with_timeout

        assert _read_pdf_pages_with_timeout(PdfReader, b"not a pdf", "bad.pdf") is None
