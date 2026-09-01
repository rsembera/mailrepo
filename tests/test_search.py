"""Search endpoint: FTS5 query sanitization (Session 89)."""

import pytest


class TestFtsQuerySanitization:
    """FTS5 operators in user input must be literal text, never syntax.
    A bare hyphen 500'd the search endpoint (Session 89, found by
    searching for a Google Meet link)."""

    @pytest.mark.parametrize("bad", ["-", "re: invoice", "follow-up",
                                     "(unbalanced", "NOT", "a AND b",
                                     "meet.google.com/abc-defg-hij", "^start", "trail*"])
    def test_punctuation_queries_return_200(self, authenticated_client, initialized_app, bad):
        resp = authenticated_client.get("/api/search", query_string={"q": bad})
        assert resp.status_code == 200, bad

    def test_pure_punctuation_returns_empty(self, authenticated_client, initialized_app):
        resp = authenticated_client.get("/api/search", query_string={"q": "-"})
        assert resp.status_code == 200
        assert resp.get_json()["results"] == []

    def test_build_fts_match_quotes_tokens(self):
        from core.database import build_fts_match

        assert build_fts_match("follow-up meeting") == '"follow-up" "meeting"'
        assert build_fts_match('-') is None
        assert build_fts_match('... !!') is None
        # user phrases survive as phrases
        assert build_fts_match('signed "wellington lease" today') == '"signed" "wellington lease" "today"'

    def test_hyphenated_and_url_content_is_findable(self, authenticated_client, initialized_app, tmp_path):
        """The motivating case: an email containing a Meet link is found
        by searching that link (and by 'follow-up')."""
        from core.database import Database
        from web.blueprints.api.commit import _save_email_to_archive

        fid = Database.execute(
            "INSERT INTO folders (name, parent_id) VALUES (?, ?)", ("SearchTest", None)
        ).lastrowid
        raw = (b"From: a@example.com\r\nTo: b@example.com\r\n"
               b"Subject: Follow-up call\r\nMessage-ID: <s1@example.com>\r\n\r\n"
               b"Join here: meet.google.com/abc-defg-hij before our follow-up.\r\n")
        _save_email_to_archive(raw, fid, None, "t")
        Database.commit()

        for q in ("meet.google.com/abc-defg-hij", "follow-up", "abc-defg-hij"):
            resp = authenticated_client.get("/api/search", query_string={"q": q})
            assert resp.status_code == 200, q
            assert resp.get_json()["count"] >= 1, q
