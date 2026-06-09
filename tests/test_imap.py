"""
Unit tests for core/imap.py move/delete primitives.

These mock the IMAP *connection* object only — they exercise MailRepo's own
dispatch logic (MOVE-vs-COPY selection, COPYUID parsing, UID-scoped expunge,
return-value contract), NOT the IMAP protocol against a real server. Fast:
no network, no Argon2id.
"""

from unittest.mock import MagicMock

import pytest

from core.imap import IMAP, IMAPError


def make_client(capabilities=("IMAP4REV1",)):
    """An IMAP client with a mocked connection and given server capabilities."""
    client = IMAP("imap.example.com")
    conn = MagicMock()
    conn.capabilities = capabilities
    conn.untagged_responses = {}
    client.connection = conn
    return client, conn


def _uid_dispatch(responses):
    """Build a uid() side_effect that returns per IMAP command verb."""

    def _side_effect(verb, *args):
        return responses.get(verb, ("OK", [b""]))

    return _side_effect


class TestMoveEmailMoveCapable:
    def test_uses_move_when_capable(self):
        client, conn = make_client(("IMAP4REV1", "MOVE", "UIDPLUS"))
        conn.uid.side_effect = _uid_dispatch(
            {"MOVE": ("OK", [b"[COPYUID 12 100 200] Move completed"])}
        )
        new_uid = client.move_email("100", "[Gmail]/Trash")
        assert new_uid == "200"
        verbs = [c.args[0] for c in conn.uid.call_args_list]
        assert verbs == ["MOVE"]  # no COPY/STORE/EXPUNGE on MOVE path
        conn.expunge.assert_not_called()

    def test_move_raises_on_failure(self):
        client, conn = make_client(("IMAP4REV1", "MOVE"))
        conn.uid.side_effect = _uid_dispatch({"MOVE": ("NO", [b"over quota"])})
        with pytest.raises(IMAPError):
            client.move_email("100", "[Gmail]/Trash")


class TestMoveEmailCopyFallback:
    def test_falls_back_to_copy_store_expunge(self):
        client, conn = make_client(("IMAP4REV1", "UIDPLUS"))  # no MOVE
        conn.uid.side_effect = _uid_dispatch(
            {
                "COPY": ("OK", [b"[COPYUID 12 100 200]"]),
                "STORE": ("OK", [b""]),
                "EXPUNGE": ("OK", [b""]),
            }
        )
        new_uid = client.move_email("100", "Trash")
        assert new_uid == "200"
        verbs = [c.args[0] for c in conn.uid.call_args_list]
        assert verbs == ["COPY", "STORE", "EXPUNGE"]  # UID EXPUNGE, scoped
        conn.expunge.assert_not_called()

    def test_bare_expunge_without_uidplus(self):
        client, conn = make_client(("IMAP4REV1",))  # no MOVE, no UIDPLUS
        conn.uid.side_effect = _uid_dispatch(
            {"COPY": ("OK", [b"[COPYUID 12 100 200]"]), "STORE": ("OK", [b""])}
        )
        new_uid = client.move_email("100", "Trash")
        assert new_uid == "200"
        verbs = [c.args[0] for c in conn.uid.call_args_list]
        assert verbs == ["COPY", "STORE"]  # no UID EXPUNGE
        conn.expunge.assert_called_once()  # bare expunge fallback

    def test_copy_failure_raises(self):
        client, conn = make_client(("IMAP4REV1",))
        conn.uid.side_effect = _uid_dispatch({"COPY": ("NO", [b"no such folder"])})
        with pytest.raises(IMAPError):
            client.move_email("100", "Trash")
        conn.expunge.assert_not_called()


class TestCopyUidParsing:
    def test_returns_none_when_copyuid_absent(self):
        # Success, but server reported no COPYUID (no UIDPLUS) -> None, not error.
        client, conn = make_client(("IMAP4REV1",))
        conn.uid.side_effect = _uid_dispatch(
            {"COPY": ("OK", [b"Copy completed"]), "STORE": ("OK", [b""])}
        )
        assert client.move_email("100", "Trash") is None

    def test_parses_copyuid_from_tuple_data(self):
        client, conn = make_client(("IMAP4REV1", "MOVE"))
        conn.uid.side_effect = _uid_dispatch({"MOVE": ("OK", [(b"OK", b"[COPYUID 99 7 4242]")])})
        assert client.move_email("7", "Trash") == "4242"

    def test_parses_copyuid_from_untagged_responses(self):
        client, conn = make_client(("IMAP4REV1", "MOVE"))
        conn.untagged_responses = {"COPYUID": [b"12 100 555"]}
        conn.uid.side_effect = _uid_dispatch({"MOVE": ("OK", [b"done"])})
        assert client.move_email("100", "Trash") == "555"


class TestCallSiteContract:
    """archive_email / trash_email must return True on success even when the
    server reports no COPYUID (regression: must not collapse to `is not None`)."""

    def test_archive_returns_true_with_copyuid(self, monkeypatch):
        client, conn = make_client(("IMAP4REV1", "MOVE"))
        monkeypatch.setattr(client, "get_special_folder", lambda t: "Archive")
        conn.uid.side_effect = _uid_dispatch({"MOVE": ("OK", [b"[COPYUID 1 9 99]"])})
        assert client.archive_email("9") is True

    def test_trash_returns_true_without_copyuid(self, monkeypatch):
        # The exact regression case: successful move, no COPYUID -> still True.
        client, conn = make_client(("IMAP4REV1",))
        monkeypatch.setattr(client, "get_special_folder", lambda t: "Trash")
        conn.uid.side_effect = _uid_dispatch({"COPY": ("OK", [b"done"]), "STORE": ("OK", [b""])})
        assert client.trash_email("9") is True

    def test_archive_raises_when_no_folder(self, monkeypatch):
        client, _ = make_client()
        monkeypatch.setattr(client, "get_special_folder", lambda t: None)
        with pytest.raises(IMAPError):
            client.archive_email("9")


class TestHasCapability:
    def test_reads_cached_tuple_without_command(self):
        client, conn = make_client(("IMAP4REV1", "MOVE", "UIDPLUS"))
        assert client._has_capability("MOVE") is True
        assert client._has_capability("uidplus") is True  # case-insensitive
        assert client._has_capability("IDLE") is False
        conn.capability.assert_not_called()  # used cached tuple
