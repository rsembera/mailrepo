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


class TestConvertedPst:
    """A converted PST is a directory per folder, each holding a file
    called "mbox". Staging its folders created the archive folders,
    archived nothing, and said "3 folders archived"."""

    @staticmethod
    def _folder(root, rel, subjects):
        d = root / rel
        d.mkdir(parents=True)
        body = b""
        for i, subject in enumerate(subjects):
            body += (
                f"From sender@example.com Mon Jan  1 00:00:0{i} 2024\n"
                f"Subject: {subject}\nMessage-ID: <{rel}-{i}@example.com>\n\nBody {subject}\n\n"
            ).encode()
        (d / "mbox").write_bytes(body)
        return str(d / "mbox")

    def test_a_staged_pst_folder_yields_its_own_emails(self, tmp_path):
        inbox = self._folder(tmp_path, "PF/Inbox", ["one", "two"])
        sent = self._folder(tmp_path, "PF/Sent Items", ["three"])
        pst = str(tmp_path / "Old Mail.pst")

        assert ep.count_emails_in_import_folder(pst, inbox, "pst") == 2
        got = list(ep.iter_emails_from_import_folder(pst, inbox, "pst"))
        assert [uid for uid, _ in got] == ["mbox-0", "mbox-1"]
        assert b"Subject: one" in got[0][1] and b"Subject: two" in got[1][1]

        assert ep.count_emails_in_import_folder(pst, sent, "pst") == 1
        only = list(ep.iter_emails_from_import_folder(pst, sent, "pst"))
        assert b"Subject: three" in only[0][1]

    def test_committing_pst_folders_archives_the_mail(self, authenticated_client, tmp_path):
        from core import Database
        from web.blueprints.api.commit import (
            commit_import_folder,
            create_archive_folder_from_path,
        )

        inbox = self._folder(tmp_path, "PF/Inbox", ["one", "two"])
        clients = self._folder(tmp_path, "PF/Inbox/Clients", ["three"])
        dest = Database.execute("INSERT INTO folders (name) VALUES ('Imported')").lastrowid
        Database.commit()

        for path, archive_path in ((inbox, "Inbox"), (clients, "Inbox/Clients")):
            item = {
                "sourceType": "import",
                "importType": "pst",
                "importPath": str(tmp_path / "Old Mail.pst"),
                "folder": path,
                "archivePath": archive_path,
                "destinationFolderId": dest,
            }
            results = {"success": [], "failed": [], "skipped": []}
            target = create_archive_folder_from_path(archive_path, dest)
            for _ in commit_import_folder(item, target, 1, 2, results):
                pass
            assert results["failed"] == []
        Database.commit()

        rows = Database.fetchall(
            """SELECT f.name AS folder, p.name AS parent, m.subject FROM messages m
               JOIN folders f ON m.folder_id = f.id LEFT JOIN folders p ON f.parent_id = p.id
               ORDER BY m.subject"""
        )
        assert [(r["parent"], r["folder"], r["subject"]) for r in rows] == [
            ("Imported", "Inbox", "one"),
            ("Inbox", "Clients", "three"),
            ("Imported", "Inbox", "two"),
        ]
