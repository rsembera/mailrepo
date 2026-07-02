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
        # imaplib surfaces response-code arguments via response(), which POPS
        # the entry from untagged_responses — emulate that pop.
        store = {"COPYUID": [b"12 100 555"]}
        conn.response.side_effect = lambda key: (key, store.pop(key, [None]))
        conn.uid.side_effect = _uid_dispatch({"MOVE": ("OK", [b"done"])})
        assert client.move_email("100", "Trash") == "555"

    def test_stale_copyuid_not_reused_for_later_move(self):
        # Regression (Session 46 review): a COPYUID left over from an earlier
        # command must not be misattributed to a later move whose server
        # response carries no COPYUID of its own.
        client, conn = make_client(("IMAP4REV1", "MOVE"))
        store = {"COPYUID": [b"12 100 555"]}
        conn.response.side_effect = lambda key: (key, store.pop(key, [None]))
        conn.uid.side_effect = _uid_dispatch({"MOVE": ("OK", [b"done"])})
        assert client.move_email("100", "Trash") == "555"
        # Second move: entry was consumed, server reports nothing -> None,
        # never the previous message's UID.
        assert client.move_email("101", "Trash") is None


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


class TestGetSpecialFolderSpam:
    def test_resolves_gmail_spam(self, monkeypatch):
        client, _ = make_client()
        monkeypatch.setattr(
            client,
            "list_folders",
            lambda: [{"name": "INBOX"}, {"name": "[Gmail]/Spam"}],
        )
        assert client.get_special_folder("spam") == "[Gmail]/Spam"

    def test_resolves_generic_junk(self, monkeypatch):
        client, _ = make_client()
        monkeypatch.setattr(client, "list_folders", lambda: [{"name": "INBOX"}, {"name": "Junk"}])
        assert client.get_special_folder("spam") == "Junk"


def _trash_spam(t):
    return {"trash": "[Gmail]/Trash", "spam": "[Gmail]/Spam"}.get(t)


class TestDeleteViaTrash:
    def test_happy_path_move_then_expunge(self, monkeypatch):
        client, conn = make_client(("IMAP4REV1", "MOVE", "UIDPLUS"))
        monkeypatch.setattr(client, "get_special_folder", _trash_spam)
        monkeypatch.setattr(client, "select_folder", MagicMock())
        conn.uid.side_effect = _uid_dispatch(
            {
                "MOVE": ("OK", [b"[COPYUID 1 100 200]"]),
                "STORE": ("OK", [b""]),
                "EXPUNGE": ("OK", [b""]),
            }
        )
        assert client.delete_email_via_trash("100", "INBOX") is True
        verbs = [c.args[0] for c in conn.uid.call_args_list]
        assert verbs == ["MOVE", "STORE", "EXPUNGE"]
        # expunge was UID-scoped against the moved message's new UID
        assert conn.uid.call_args_list[-1].args[1] == "200"

    def test_in_place_when_source_is_trash(self, monkeypatch):
        client, conn = make_client(("IMAP4REV1", "UIDPLUS"))
        monkeypatch.setattr(client, "get_special_folder", _trash_spam)
        conn.uid.side_effect = _uid_dispatch({"STORE": ("OK", [b""]), "EXPUNGE": ("OK", [b""])})
        assert client.delete_email_via_trash("100", "[Gmail]/Trash") is True
        verbs = [c.args[0] for c in conn.uid.call_args_list]
        assert verbs == ["STORE", "EXPUNGE"]  # no MOVE/COPY

    def test_in_place_when_source_is_spam(self, monkeypatch):
        client, conn = make_client(("IMAP4REV1", "UIDPLUS"))
        monkeypatch.setattr(client, "get_special_folder", _trash_spam)
        conn.uid.side_effect = _uid_dispatch({"STORE": ("OK", [b""]), "EXPUNGE": ("OK", [b""])})
        assert client.delete_email_via_trash("100", "[Gmail]/Spam") is True
        verbs = [c.args[0] for c in conn.uid.call_args_list]
        assert verbs == ["STORE", "EXPUNGE"]

    def test_move_failure_propagates(self, monkeypatch):
        client, conn = make_client(("IMAP4REV1", "MOVE"))
        monkeypatch.setattr(client, "get_special_folder", _trash_spam)
        monkeypatch.setattr(client, "select_folder", MagicMock())
        conn.uid.side_effect = _uid_dispatch({"MOVE": ("NO", [b"over quota"])})
        with pytest.raises(IMAPError):
            client.delete_email_via_trash("100", "INBOX")

    def test_expunge_failure_after_move_is_success_with_warning(self, monkeypatch):
        client, conn = make_client(("IMAP4REV1", "MOVE", "UIDPLUS"))
        monkeypatch.setattr(client, "get_special_folder", _trash_spam)
        monkeypatch.setattr(client, "select_folder", MagicMock())

        def _side_effect(verb, *args):
            if verb == "MOVE":
                return ("OK", [b"[COPYUID 1 100 200]"])
            if verb == "STORE":
                return ("OK", [b""])
            if verb == "EXPUNGE":
                raise OSError("connection dropped")
            return ("OK", [b""])

        conn.uid.side_effect = _side_effect
        # Reached Trash; expunge failed -> still True (Gmail auto-purges).
        assert client.delete_email_via_trash("100", "INBOX") is True

    def test_message_id_fallback_when_no_copyuid(self, monkeypatch):
        # No UIDPLUS, no MOVE: COPY reports no COPYUID, so the new UID is
        # located by Message-ID search in Trash.
        client, conn = make_client(("IMAP4REV1",))
        monkeypatch.setattr(client, "get_special_folder", _trash_spam)
        monkeypatch.setattr(client, "select_folder", MagicMock())
        monkeypatch.setattr(
            client, "fetch_headers", lambda uid: {"message_id": "<abc@example.com>"}
        )
        find_mock = MagicMock(return_value="555")
        monkeypatch.setattr(client, "_find_uid_in_folder_by_message_id", find_mock)
        conn.uid.side_effect = _uid_dispatch(
            {"COPY": ("OK", [b"Copy done"]), "STORE": ("OK", [b""])}
        )
        assert client.delete_email_via_trash("100", "INBOX") is True
        find_mock.assert_called_once_with("[Gmail]/Trash", "<abc@example.com>")


class TestBatchedGmailDelete:
    """delete_emails_via_trash: one UID-set MOVE + one EXPUNGE for many
    messages, with per-uid results and partial-failure honesty."""

    def _gmail(self, monkeypatch, caps=("IMAP4REV1", "MOVE", "UIDPLUS")):
        client, conn = make_client(caps)
        monkeypatch.setattr(
            client, "get_special_folder",
            lambda t: "[Gmail]/Trash" if t == "trash" else None,
        )
        monkeypatch.setattr(client, "select_folder", lambda f=None: {})
        return client, conn

    def test_expand_uid_set(self):
        assert IMAP._expand_uid_set("4,7:9") == ["4", "7", "8", "9"]
        assert IMAP._expand_uid_set("100:102") == ["100", "101", "102"]
        assert IMAP._expand_uid_set("5") == ["5"]

    def test_parse_copyuid_map_comma_and_range(self, monkeypatch):
        client, conn = self._gmail(monkeypatch)
        store = {"COPYUID": [b"12 100,101 500,501"]}
        conn.response.side_effect = lambda key: (key, store.pop(key, [None]))
        assert client._parse_copyuid_map([b""]) == {"100": "500", "101": "501"}

        store2 = {"COPYUID": [b"12 4:6 500:502"]}
        conn.response.side_effect = lambda key: (key, store2.pop(key, [None]))
        assert client._parse_copyuid_map([b""]) == {"4": "500", "5": "501", "6": "502"}

    def test_parse_copyuid_map_absent_or_mismatched(self, monkeypatch):
        client, conn = self._gmail(monkeypatch)
        conn.response.side_effect = lambda key: (key, [None])
        assert client._parse_copyuid_map([b"done"]) == {}
        # mismatched set lengths -> {} (don't guess a partial mapping)
        store = {"COPYUID": [b"12 100,101 500"]}
        conn.response.side_effect = lambda key: (key, store.pop(key, [None]))
        assert client._parse_copyuid_map([b""]) == {}

    def test_one_move_and_one_expunge_for_many(self, monkeypatch):
        client, conn = self._gmail(monkeypatch)
        store = {"COPYUID": [b"12 100,101,102 500,501,502"]}
        conn.response.side_effect = lambda key: (key, store.pop(key, [None]))
        conn.uid.side_effect = _uid_dispatch(
            {"MOVE": ("OK", [b"done"]), "STORE": ("OK", [b""]), "EXPUNGE": ("OK", [b""])}
        )

        result = client.delete_emails_via_trash(["100", "101", "102"], "INBOX")

        assert result == {"100": True, "101": True, "102": True}
        verbs = [c.args[0] for c in conn.uid.call_args_list]
        assert verbs.count("MOVE") == 1          # one MOVE for all three
        assert verbs.count("EXPUNGE") == 1       # one scoped EXPUNGE
        # EXPUNGE targets the destination UID set from COPYUID
        exp = [c for c in conn.uid.call_args_list if c.args[0] == "EXPUNGE"][0]
        assert exp.args[1] == "500,501,502"

    def test_without_copyuid_still_reports_success(self, monkeypatch):
        # MOVE OK but no COPYUID -> messages are in Trash; report True and rely
        # on Gmail's ~30-day auto-purge (matches per-message behaviour).
        client, conn = self._gmail(monkeypatch, caps=("IMAP4REV1", "MOVE"))
        conn.response.side_effect = lambda key: (key, [None])
        conn.uid.side_effect = _uid_dispatch({"MOVE": ("OK", [b"done"])})

        result = client.delete_emails_via_trash(["100", "101"], "INBOX")

        assert result == {"100": True, "101": True}
        verbs = [c.args[0] for c in conn.uid.call_args_list]
        assert verbs.count("MOVE") == 1
        assert "EXPUNGE" not in verbs            # no dst uids -> no scoped expunge

    def test_move_failure_raises(self, monkeypatch):
        client, conn = self._gmail(monkeypatch)
        conn.response.side_effect = lambda key: (key, [None])
        conn.uid.side_effect = _uid_dispatch({"MOVE": ("NO", [b"over quota"])})
        with pytest.raises(IMAPError):
            client.delete_emails_via_trash(["100", "101"], "INBOX")

    def test_single_uid_delegates_to_per_message(self, monkeypatch):
        client, _ = self._gmail(monkeypatch)
        seen = []
        monkeypatch.setattr(
            client, "delete_email_via_trash",
            lambda uid, src: (seen.append(uid) or True),
        )
        result = client.delete_emails_via_trash(["100"], "INBOX")
        assert result == {"100": True}
        assert seen == ["100"]                   # one message -> proven path

    def test_in_place_delegates_to_per_message(self, monkeypatch):
        client, _ = self._gmail(monkeypatch)
        seen = []
        monkeypatch.setattr(
            client, "delete_email_via_trash",
            lambda uid, src: (seen.append(uid) or True),
        )
        result = client.delete_emails_via_trash(["100", "101"], "[Gmail]/Trash")
        assert result == {"100": True, "101": True}
        assert seen == ["100", "101"]            # source is Trash -> in-place
