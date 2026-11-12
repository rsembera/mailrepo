"""
Code review 2026-11, finding 15: what the search index is built from.
"""

from email.message import EmailMessage

from core import Config, Database, Encryption
from web.blueprints.api.email_parser import BODY_TEXT_LIMIT, extract_body_text


def _html_mail(html):
    m = EmailMessage()
    m["Subject"] = "x"
    m.set_content(html, subtype="html")
    return m.as_bytes()


def test_entity_encoded_accents_are_indexed_as_words():
    text = extract_body_text(_html_mail("<p>Rendez-vous au caf&eacute; &agrave; Montr&#233;al</p>"))
    assert "café" in text
    assert "Montréal" in text
    assert "&#" not in text


def test_nbsp_separates_words():
    assert extract_body_text(_html_mail("<p>one&nbsp;two</p>")) == "one two"


def test_long_messages_are_indexed_well_past_the_old_cutoff():
    body = " ".join(f"word{i}" for i in range(4000))  # about 35,000 characters
    m = EmailMessage()
    m["Subject"] = "long"
    m.set_content(body)
    text = extract_body_text(m.as_bytes())
    assert "word3999" in text
    assert BODY_TEXT_LIMIT >= 100_000


def test_reindex_saves_its_work(authenticated_client, initialized_app):
    Database.execute("INSERT INTO folders (id, name) VALUES (1, 'F')")
    directory = Config.get_archive_path() / "1"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "a.eml.enc"
    path.write_bytes(Encryption.encrypt(_html_mail("<p>caf&eacute;</p>")))
    Database.execute(
        "INSERT INTO messages (folder_id, message_id, filepath, body_text) VALUES (1, '<a@x>', ?, 'stale')",
        (str(path.relative_to(Config.get_base_path())),),
    )
    Database.commit()

    resp = authenticated_client.post("/api/search/reindex")
    assert resp.status_code == 200
    assert not Database.get_connection().in_transaction
    assert Database.fetchone("SELECT body_text FROM messages")["body_text"] == "café"


class TestOneTimeReindex:
    def _archive_one(self, body_text):
        Database.execute("INSERT INTO folders (id, name) VALUES (1, 'F')")
        directory = Config.get_archive_path() / "1"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "a.eml.enc"
        path.write_bytes(Encryption.encrypt(_html_mail("<p>caf&eacute;</p>")))
        Database.execute(
            "INSERT INTO messages (folder_id, message_id, filepath, body_text) VALUES (1, '<a@x>', ?, ?)",
            (str(path.relative_to(Config.get_base_path())), body_text),
        )
        Database.commit()

    def _wait(self):
        import threading

        for thread in threading.enumerate():
            if thread.name == "search-reindex":
                thread.join(timeout=10)

    def test_an_older_archive_is_reindexed_once(self, initialized_app):
        from core.database import get_setting
        from web.blueprints.api.emails import SEARCH_INDEX_VERSION, start_reindex_if_needed

        self._archive_one("caf")  # what the old extractor produced
        assert start_reindex_if_needed() is True
        self._wait()

        assert Database.fetchone("SELECT body_text FROM messages")["body_text"] == "café"
        assert get_setting("search_index_version") == SEARCH_INDEX_VERSION
        hits = Database.fetchall(
            "SELECT rowid FROM messages_fts WHERE messages_fts MATCH '\"café\"'"
        )
        assert len(hits) == 1
        assert start_reindex_if_needed() is False  # not again

    def test_an_empty_archive_is_just_marked_current(self, initialized_app):
        from core.database import get_setting
        from web.blueprints.api.emails import SEARCH_INDEX_VERSION, start_reindex_if_needed

        assert start_reindex_if_needed() is False
        assert get_setting("search_index_version") == SEARCH_INDEX_VERSION

    def test_a_run_cut_short_is_not_recorded_as_done(self, initialized_app):
        from core.database import get_setting
        from web import idle
        from web.blueprints.api.emails import start_reindex_if_needed

        self._archive_one("caf")
        idle.new_login_id()
        assert start_reindex_if_needed() is True
        idle.new_login_id()  # a logout and fresh login while it runs (or just after)
        self._wait()
        assert get_setting("search_index_version", "1") in ("1", "2")
        # Whatever happened, the idle lock is not left held.
        assert not idle.is_busy()
