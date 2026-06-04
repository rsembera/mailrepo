"""
Tests for core/importer.py - mbox / .eml ingestion.

Uses the deliberately-nasty samples in ``test_files/`` (malformed
headers, bad encoding, truncated MIME, a corrupt mbox, a 17MB email, a
multi-attachment email) plus clean fixtures built inline. The property
that matters most for a local-first archive: an email is *never silently
dropped or altered* on import - even a malformed one is stored
byte-for-byte (encrypted), and a bad message in an mbox is counted as a
failure rather than aborting the whole import.
"""

import mailbox
from pathlib import Path

import pytest

from core import Config, Database, Encryption
from core.importer import (
    ImportError as ImporterError,
)
from core.importer import (
    decode_header_value,
    import_eml_file,
    import_mbox_file,
    parse_email_metadata,
    scan_mbox_file,
)

TEST_FILES = Path(__file__).resolve().parent.parent / "test_files"


def _make_folder(name="Imports"):
    cur = Database.execute("INSERT INTO folders (name) VALUES (?)", (name,))
    Database.commit()
    return cur.lastrowid


def _clean_eml(subject="Hello", body="body", message_id="<clean@test>", date_hdr=True):
    headers = [
        "From: sender@example.com",
        "To: me@example.com",
        f"Subject: {subject}",
    ]
    if message_id:
        headers.append(f"Message-ID: {message_id}")
    if date_hdr:
        headers.append("Date: Sat, 15 Feb 2026 10:30:00 -0500")
    headers.append('Content-Type: text/plain; charset="utf-8"')
    return ("\r\n".join(headers) + "\r\n\r\n" + body + "\r\n").encode()


# ---------------------------------------------------------------------------
# decode_header_value
# ---------------------------------------------------------------------------


class TestDecodeHeaderValue:
    def test_empty(self):
        assert decode_header_value("") == ""

    def test_plain_ascii(self):
        assert decode_header_value("Plain Subject") == "Plain Subject"

    def test_rfc2047_encoded(self):
        assert decode_header_value("=?utf-8?q?Caf=C3=A9?=") == "Café"

    def test_rfc2047_base64(self):
        # "Subject" base64-encoded
        assert decode_header_value("=?utf-8?b?U3ViamVjdA==?=") == "Subject"


# ---------------------------------------------------------------------------
# parse_email_metadata
# ---------------------------------------------------------------------------


class TestParseEmailMetadata:
    def test_clean_extraction(self):
        m = parse_email_metadata(_clean_eml(subject="Quarterly", message_id="<q1@test>"))
        assert m["subject"] == "Quarterly"
        assert "sender@example.com" in m["sender"]
        assert m["message_id"] == "<q1@test>"
        assert isinstance(m["date"], int)

    def test_missing_subject_defaults(self):
        m = parse_email_metadata(b"From: a@b.com\r\n\r\nbody")
        assert m["subject"] == "(no subject)"

    def test_bad_date_is_none(self):
        m = parse_email_metadata(_clean_eml(date_hdr=False))
        assert m["date"] is None

    def test_subject_truncated_to_500(self):
        long_subject = "A" * 800
        m = parse_email_metadata(_clean_eml(subject=long_subject))
        assert len(m["subject"]) == 500

    @pytest.mark.parametrize(
        "sample",
        [
            "malformed_no_headers.eml",
            "malformed_bad_encoding.eml",
            "malformed_truncated.eml",
        ],
    )
    def test_malformed_samples_do_not_raise(self, sample):
        raw = (TEST_FILES / sample).read_bytes()
        m = parse_email_metadata(raw)  # must not raise
        assert "subject" in m and "message_id" in m


# ---------------------------------------------------------------------------
# import_eml_file
# ---------------------------------------------------------------------------


class TestImportEmlFile:
    def test_happy_round_trip(self, initialized_app, tmp_path):
        fid = _make_folder()
        raw = _clean_eml(subject="Filed", body="archived content", message_id="<file@test>")
        src = tmp_path / "msg.eml"
        src.write_bytes(raw)
        result = import_eml_file(src, fid)
        assert result["success"] is True
        row = Database.fetchone(
            "SELECT subject, filepath FROM messages WHERE folder_id = ?", (fid,)
        )
        assert row["subject"] == "Filed"
        # Stored ciphertext decrypts back to the exact original bytes
        stored = (Config.get_base_path() / row["filepath"]).read_bytes()
        assert Encryption.decrypt(stored) == raw

    def test_filename_from_message_id(self, initialized_app, tmp_path):
        fid = _make_folder()
        src = tmp_path / "m.eml"
        src.write_bytes(_clean_eml(message_id="<unique-id-123@test>"))
        import_eml_file(src, fid)
        files = list((Config.get_archive_path() / str(fid)).glob("*.eml.enc"))
        assert any("unique-id-123" in f.name for f in files)

    def test_filename_hash_fallback_without_message_id(self, initialized_app, tmp_path):
        fid = _make_folder()
        src = tmp_path / "m.eml"
        src.write_bytes(_clean_eml(message_id=None))
        result = import_eml_file(src, fid)
        assert result["success"] is True
        files = list((Config.get_archive_path() / str(fid)).glob("*.eml.enc"))
        assert len(files) == 1  # a hash-named file was created

    def test_nonexistent_file_returns_failure(self, initialized_app):
        fid = _make_folder()
        result = import_eml_file(Path("/no/such/file.eml"), fid)
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.parametrize(
        "sample",
        [
            "malformed_no_headers.eml",
            "malformed_bad_encoding.eml",
            "malformed_truncated.eml",
        ],
    )
    def test_malformed_archived_byte_for_byte(self, initialized_app, sample):
        fid = _make_folder()
        raw = (TEST_FILES / sample).read_bytes()
        result = import_eml_file(TEST_FILES / sample, fid)
        assert result["success"] is True
        row = Database.fetchone("SELECT filepath FROM messages WHERE folder_id = ?", (fid,))
        stored = (Config.get_base_path() / row["filepath"]).read_bytes()
        assert Encryption.decrypt(stored) == raw

    def test_many_attachments_round_trip(self, initialized_app):
        fid = _make_folder()
        raw = (TEST_FILES / "many_attachments.eml").read_bytes()
        result = import_eml_file(TEST_FILES / "many_attachments.eml", fid)
        assert result["success"] is True
        row = Database.fetchone("SELECT filepath FROM messages WHERE folder_id = ?", (fid,))
        stored = (Config.get_base_path() / row["filepath"]).read_bytes()
        assert Encryption.decrypt(stored) == raw

    def test_large_email_round_trip(self, initialized_app):
        fid = _make_folder()
        src = TEST_FILES / "large_email.eml"
        raw_len = src.stat().st_size
        result = import_eml_file(src, fid)
        assert result["success"] is True
        row = Database.fetchone("SELECT filepath FROM messages WHERE folder_id = ?", (fid,))
        stored = (Config.get_base_path() / row["filepath"]).read_bytes()
        assert len(Encryption.decrypt(stored)) == raw_len


# ---------------------------------------------------------------------------
# import_mbox_file
# ---------------------------------------------------------------------------


def _build_clean_mbox(path, *messages):
    mb = mailbox.mbox(str(path))
    mb.lock()
    try:
        for raw in messages:
            mb.add(raw)
        mb.flush()
    finally:
        mb.unlock()
        mb.close()


class TestImportMboxFile:
    def test_clean_mbox_imports_all(self, initialized_app, tmp_path):
        fid = _make_folder()
        mbox_path = tmp_path / "clean.mbox"
        _build_clean_mbox(
            mbox_path,
            _clean_eml(subject="One", body="first body", message_id="<one@test>"),
            _clean_eml(subject="Two", body="second body", message_id="<two@test>"),
        )
        results = import_mbox_file(mbox_path, fid)
        assert results["total"] == 2
        assert results["success_count"] == 2
        assert results["failed_count"] == 0
        subjects = {
            r["subject"]
            for r in Database.fetchall("SELECT subject FROM messages WHERE folder_id = ?", (fid,))
        }
        assert subjects == {"One", "Two"}

    def test_clean_mbox_content_preserved(self, initialized_app, tmp_path):
        fid = _make_folder()
        mbox_path = tmp_path / "clean.mbox"
        _build_clean_mbox(mbox_path, _clean_eml(body="distinctive payload xyz"))
        import_mbox_file(mbox_path, fid)
        row = Database.fetchone("SELECT filepath FROM messages WHERE folder_id = ?", (fid,))
        stored = Encryption.decrypt((Config.get_base_path() / row["filepath"]).read_bytes())
        assert b"distinctive payload xyz" in stored

    def test_progress_callback_invoked(self, initialized_app, tmp_path):
        fid = _make_folder()
        mbox_path = tmp_path / "clean.mbox"
        _build_clean_mbox(mbox_path, _clean_eml(), _clean_eml(message_id="<two@test>"))
        seen = []
        import_mbox_file(mbox_path, fid, progress_callback=lambda cur, tot: seen.append((cur, tot)))
        assert seen[-1] == (2, 2)

    def test_corrupt_mbox_handled_gracefully(self, initialized_app):
        fid = _make_folder()
        results = import_mbox_file(TEST_FILES / "corrupt.mbox", fid)
        # Every message is accounted for as either a success or a failure -
        # the import never aborts wholesale or silently loses a message.
        assert results["total"] == results["success_count"] + results["failed_count"]

    def test_bad_path_raises_import_error(self, initialized_app):
        with pytest.raises(ImporterError):
            import_mbox_file(Path("/no/such/dir/x.mbox"), 1)


# ---------------------------------------------------------------------------
# scan_mbox_file
# ---------------------------------------------------------------------------


class TestScanMboxFile:
    def test_scan_counts_and_samples(self, initialized_app, tmp_path):
        mbox_path = tmp_path / "clean.mbox"
        _build_clean_mbox(
            mbox_path,
            _clean_eml(subject="Alpha"),
            _clean_eml(subject="Beta", message_id="<b@test>"),
        )
        result = scan_mbox_file(mbox_path)
        assert result["message_count"] == 2
        assert len(result["samples"]) == 2
        assert {s["subject"] for s in result["samples"]} == {"Alpha", "Beta"}

    def test_scan_samples_capped_at_five(self, initialized_app, tmp_path):
        mbox_path = tmp_path / "many.mbox"
        _build_clean_mbox(
            mbox_path,
            *[_clean_eml(subject=f"S{i}", message_id=f"<m{i}@test>") for i in range(8)],
        )
        result = scan_mbox_file(mbox_path)
        assert result["message_count"] == 8
        assert len(result["samples"]) == 5

    def test_scan_corrupt_does_not_crash(self, initialized_app):
        result = scan_mbox_file(TEST_FILES / "corrupt.mbox")
        assert isinstance(result["message_count"], int)

    def test_scan_bad_path_raises(self, initialized_app):
        with pytest.raises(ImporterError):
            scan_mbox_file(Path("/no/such/dir/x.mbox"))
