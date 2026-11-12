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
