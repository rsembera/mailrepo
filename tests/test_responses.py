"""
Tests for web/responses.py and the global security headers.

Security review 2026-09, findings 2 and 17: attachment bytes are
attacker-chosen, so the MIME part's Content-Type must never decide how a
browser treats them, and a filename must not be able to break the
Content-Disposition header.
"""

import pytest

from web.responses import INLINE_TYPES, attachment_response, normalize_content_type


@pytest.fixture
def ctx(app):
    with app.test_request_context():
        yield


class TestNormalize:
    def test_strips_params_and_lowercases(self):
        assert normalize_content_type("Text/HTML; charset=utf-8") == "text/html"

    def test_empty_is_octet_stream(self):
        assert normalize_content_type("") == "application/octet-stream"
        assert normalize_content_type(None) == "application/octet-stream"


class TestAttachmentResponse:
    @pytest.mark.parametrize("ctype", ["text/html", "image/svg+xml", "text/javascript", "application/json", "text/css"])
    def test_active_types_are_never_inline(self, ctx, ctype):
        resp = attachment_response(b"<script>1</script>", ctype, "x.html", inline=True)
        assert resp.mimetype == "application/octet-stream"
        assert resp.headers["Content-Disposition"].startswith("attachment")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    @pytest.mark.parametrize("ctype", sorted(INLINE_TYPES))
    def test_inert_types_may_be_inline(self, ctx, ctype):
        resp = attachment_response(b"data", ctype, "x", inline=True)
        assert resp.mimetype == ctype
        assert resp.headers["Content-Disposition"].startswith("inline")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    def test_inline_images_get_sandbox_csp(self, ctx):
        resp = attachment_response(b"png", "image/png", "x.png", inline=True)
        assert resp.headers["Content-Security-Policy"] == "sandbox; default-src 'none'"

    def test_pdf_has_no_csp(self, ctx):
        # Chromium's PDF viewer is an embedded plugin; object-src 'none'
        # or sandbox would blank it.
        resp = attachment_response(b"%PDF", "application/pdf", "x.pdf", inline=True)
        assert "Content-Security-Policy" not in resp.headers

    def test_download_when_not_inline(self, ctx):
        resp = attachment_response(b"png", "image/png", "x.png", inline=False)
        assert resp.headers["Content-Disposition"].startswith("attachment")

    def test_quote_in_filename_cannot_break_header(self, ctx):
        name = 'a"; filename*=UTF-8\'\'evil.html;.png'
        resp = attachment_response(b"png", "image/png", name, inline=False)
        from werkzeug.http import parse_options_header

        disposition, params = parse_options_header(resp.headers["Content-Disposition"])
        # The quote is escaped, so the whole thing parses back as one
        # filename and the smuggled filename*= never becomes a parameter.
        assert disposition == "attachment"
        assert params["filename"] == name
        assert "filename*" not in params

    def test_non_ascii_filename_is_rfc5987_encoded(self, ctx):
        resp = attachment_response(b"png", "image/png", "résumé.png", inline=False)
        assert "filename*=UTF-8''r%C3%A9sum%C3%A9.png" in resp.headers["Content-Disposition"]


class TestGlobalHeaders:
    def test_every_response_has_nosniff_and_frame_deny(self, client):
        resp = client.get("/auth/login")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "no-referrer"
