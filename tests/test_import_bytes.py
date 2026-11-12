"""
Code review 2026-11, finding 20: importing from mbox and .emlx.

Messages are archived as the bytes in the source file, one at a time,
and message N is reached without re-parsing the N before it.
"""

import types

import pytest

from web.blueprints.api import email_parser as ep

CRLF_MESSAGE = (
    b"Received: by x;\r\n\tMon, 1 Jan 2026 00:00:00 +0000\r\n"
    b"Message-ID: <one@x>\r\nSubject: one\r\nX-Folder: Clients\r\n\r\nfirst body\r\n"
)
SECOND = b"Message-ID: <two@x>\r\nSubject: two\r\nX-Folder: Other\r\n\r\nsecond body\r\n"


@pytest.fixture
def mbox_file(tmp_path):
    path = tmp_path / "mail.mbox"
    path.write_bytes(
        b"From a@b Mon Jan  1 00:00:00 2026\r\n"
        + CRLF_MESSAGE
        + b"\r\nFrom a@b Mon Jan  1 00:00:01 2026\r\n"
        + SECOND
        + b"\r\n"
    )
    ep._mbox_cache.clear()
    return str(path)


def _same(a, b):
    return a.rstrip(b"\r\n") == b.rstrip(b"\r\n")


class TestMbox:
    def test_messages_come_out_as_the_bytes_that_went_in(self, mbox_file):
        emails = ep.get_emails_from_import_folder(mbox_file, "", "mbox")
        assert [uid for uid, _raw in emails] == ["mbox-0", "mbox-1"]
        assert _same(emails[0][1], CRLF_MESSAGE)  # CRLF survived; as_bytes() made it LF
        assert b"\r\n\tMon, 1 Jan" in emails[0][1]

    def test_single_message_lookup_returns_the_same_bytes(self, mbox_file):
        assert _same(ep.get_raw_email_from_import(mbox_file, "mbox-1"), SECOND)
        assert ep.get_raw_email_from_import(mbox_file, "mbox-9") is None
        assert ep.get_raw_email_from_import(mbox_file, "mbox-x") is None

    def test_folder_filter_is_an_exact_match(self, mbox_file):
        assert [u for u, _ in ep.get_emails_from_import_folder(mbox_file, "Clients", "mbox")] == [
            "mbox-0"
        ]
        assert ep.count_emails_in_import_folder(mbox_file, "Clients", "mbox") == 1
        assert ep.count_emails_in_import_folder(mbox_file, "", "mbox") == 2

    def test_iteration_is_lazy(self, mbox_file):
        stream = ep.iter_emails_from_import_folder(mbox_file, "", "mbox")
        assert isinstance(stream, types.GeneratorType)
        assert next(stream)[0] == "mbox-0"

    def test_the_file_is_opened_once_for_many_lookups(self, mbox_file, monkeypatch):
        opened = []
        real = ep.mailbox.mbox
        monkeypatch.setattr(
            ep.mailbox, "mbox", lambda *a, **k: (opened.append(a[0]), real(*a, **k))[1]
        )
        for _ in range(5):
            ep.get_raw_email_from_import(mbox_file, "mbox-0")
            ep.get_raw_email_from_import(mbox_file, "mbox-1")
        assert len(opened) == 1

    def test_a_changed_file_is_reopened(self, mbox_file):
        assert ep.mbox_message_count(mbox_file) == 2
        with open(mbox_file, "ab") as fh:
            fh.write(b"From a@b Mon Jan  1 00:00:02 2026\r\nSubject: three\r\n\r\nx\r\n\r\n")
        assert ep.mbox_message_count(mbox_file) == 3

    def test_a_source_that_cannot_be_opened_is_an_error_not_an_empty_folder(self, tmp_path):
        directory = tmp_path / "x.mbox"
        directory.mkdir()
        (directory / "mbox").mkdir()  # a directory where the mbox file should be
        with pytest.raises(Exception):
            list(ep.iter_emails_from_import_folder(str(tmp_path), str(directory), "apple-mbox"))


class TestEmlx:
    BODY = b'Subject: xml inside\r\n\r\n<?xml version="1.0"?><invoice/>\r\ntrailing text\r\n'

    def test_byte_count_delimits_the_message(self, tmp_path):
        plist = b'<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict/></plist>\n'
        path = tmp_path / "1.emlx"
        path.write_bytes(str(len(self.BODY)).encode() + b"\n" + self.BODY + plist)
        assert ep._parse_emlx_file(str(path)) == self.BODY

    def test_xml_in_the_message_does_not_truncate_it_when_there_is_no_plist(self, tmp_path):
        path = tmp_path / "2.emlx"
        path.write_bytes(str(len(self.BODY)).encode() + b"\n" + self.BODY)
        assert ep._parse_emlx_file(str(path)) == self.BODY

    def test_a_first_line_that_is_not_a_number_falls_back_to_the_plist_search(self, tmp_path):
        plist = b'<?xml version="1.0" encoding="UTF-8"?>\n<plist/>\n'
        path = tmp_path / "3.emlx"
        path.write_bytes(b"garbage\n" + b"Subject: s\r\n\r\nbody\r\n" + plist)
        assert ep._parse_emlx_file(str(path)) == b"Subject: s\r\n\r\nbody\r\n"
