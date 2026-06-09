"""Tests for core/account_utils.py."""

from core.account_utils import is_gmail_host


def test_gmail_host_true():
    assert is_gmail_host("imap.gmail.com") is True


def test_gmail_host_case_and_whitespace_insensitive():
    assert is_gmail_host("  IMAP.Gmail.COM  ") is True


def test_non_gmail_hosts_false():
    assert is_gmail_host("imap.fastmail.com") is False
    assert is_gmail_host("outlook.office365.com") is False
    assert is_gmail_host("imap.mail.me.com") is False


def test_none_and_empty_false():
    assert is_gmail_host(None) is False
    assert is_gmail_host("") is False
