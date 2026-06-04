"""
Tests for email parsing functionality.
"""



class TestEmailMetadataParsing:
    """Tests for parsing email headers and metadata."""

    def test_parse_basic_email(self, sample_email):
        """Should extract basic metadata from plain email."""
        from web.blueprints.api.email_parser import parse_email_metadata

        metadata = parse_email_metadata(sample_email)

        assert metadata["sender"] == "sender@example.com"
        assert metadata["subject"] == "Test Email"
        assert metadata["message_id"] == "<test-123@example.com>"
        assert "recipient@example.com" in metadata["recipients"]

    def test_parse_html_email(self, sample_html_email):
        """Should parse multipart HTML email."""
        from web.blueprints.api.email_parser import parse_email_metadata

        metadata = parse_email_metadata(sample_html_email)

        assert metadata["sender"] == "sender@example.com"
        assert metadata["subject"] == "HTML Test Email"


class TestBodyExtraction:
    """Tests for extracting email body text."""

    def test_extract_plain_text_body(self, sample_email):
        """Should extract plain text body."""
        from web.blueprints.api.email_parser import extract_body_text

        body = extract_body_text(sample_email)

        assert "test email body" in body.lower()
        assert "multiple lines" in body.lower()

    def test_extract_html_body_as_text(self, sample_html_email):
        """Should extract text from HTML emails."""
        from web.blueprints.api.email_parser import extract_body_text

        body = extract_body_text(sample_html_email)

        # Should get either plain text part or stripped HTML
        assert body is not None
        assert len(body) > 0

    def test_extract_body_handles_malformed(self):
        """Should handle malformed emails gracefully."""
        from web.blueprints.api.email_parser import extract_body_text

        malformed = b"Not a valid email at all"
        body = extract_body_text(malformed)

        # Should return something, not crash
        assert body is not None


class TestEncodedHeaders:
    """Tests for RFC 2047 encoded headers."""

    def test_decode_utf8_subject(self):
        """Should decode UTF-8 encoded subjects."""
        from web.blueprints.api.email_parser import parse_email_metadata

        email = b"""From: test@example.com
To: recipient@example.com
Subject: =?UTF-8?B?VGVzdCBTdWJqZWN0IHdpdGggw6nDqMOgIGNoYXJhY3RlcnM=?=
Date: Sat, 15 Feb 2026 10:30:00 -0500

Body
"""
        metadata = parse_email_metadata(email)

        # Should decode the base64 UTF-8
        assert "Test Subject" in metadata["subject"]

    def test_decode_quoted_printable_sender(self):
        """Should decode quoted-printable sender names."""
        from web.blueprints.api.email_parser import parse_email_metadata

        email = b"""From: =?UTF-8?Q?Jos=C3=A9_Garc=C3=ADa?= <jose@example.com>
To: recipient@example.com
Subject: Test
Date: Sat, 15 Feb 2026 10:30:00 -0500

Body
"""
        metadata = parse_email_metadata(email)

        assert "José García" in metadata["sender"]
