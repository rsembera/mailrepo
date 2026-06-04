#!/usr/bin/env python3
"""One-off probe: run find_thread() on a real message and print the result.

Two modes:

  # List recent INBOX messages so you can pick one
  python scripts/probe_find_thread.py <account_id> --list [folder]

  # Run find_thread against a specific message
  python scripts/probe_find_thread.py <account_id> <folder> <uid>

Examples:
    python scripts/probe_find_thread.py 1 --list
    python scripts/probe_find_thread.py 1 --list "[Gmail]/Sent Mail"
    python scripts/probe_find_thread.py 1 INBOX 12345

Used during Stage Thread development to confirm header-walk works on
real accounts before wiring up the HTTP endpoint.
"""
import getpass
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
os.chdir(REPO)
sys.path.insert(0, REPO)

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(2)

account_id = int(sys.argv[1])
mode = sys.argv[2]

pw = getpass.getpass("MailRepo master password: ")

from core.database import Database
from core.encryption import Encryption, InvalidPasswordError
from core.imap import IMAP, IMAPError

try:
    Encryption.unlock(pw)
except InvalidPasswordError:
    print("Incorrect password.")
    sys.exit(1)

Database.set_key(Encryption.get_db_key())
Database.initialize()

row = Database.fetchone(
    "SELECT email, credentials_encrypted FROM accounts WHERE id = ?",
    (account_id,)
)
if not row or not row["credentials_encrypted"]:
    print(f"No credentials for account {account_id}")
    sys.exit(1)

print(f"Account: {row['email']}\n")

client = IMAP.connect_with_credentials(row["credentials_encrypted"])
try:
    if mode == "--list":
        folder = sys.argv[3] if len(sys.argv) > 3 else "INBOX"
        client.select_folder(folder)
        uids = client.search("ALL", limit=15)
        print(f"Recent messages in {folder}:\n")
        for uid in uids:
            try:
                h = client.fetch_thread_headers(uid)
                subj = (h["subject"] or "(no subject)")[:60]
                frm = (h["from"] or "")[:35]
                print(f"  uid={uid:>6}  from: {frm:<35}  subj: {subj}")
            except IMAPError as e:
                print(f"  uid={uid:>6}  ERROR: {e}")
        print()
        print(f"To probe one: python scripts/probe_find_thread.py {account_id} {folder!r} <uid>")
    else:
        folder = sys.argv[2]
        uid = sys.argv[3]
        sent = client.get_special_folder("sent")
        print(f"Sent folder: {sent!r}\n")
        extras = [sent] if sent else []

        import time
        t0 = time.monotonic()
        result = client.find_thread(
            source_folder=folder,
            source_uid=uid,
            also_search_folders=extras,
        )
        elapsed = time.monotonic() - t0

        print(f"Found {len(result['thread'])} messages in {elapsed:.2f}s")
        print(f"  truncated={result['truncated']}, timed_out={result['timed_out']}")
        print(f"  method={result['method']}\n")
        for i, m in enumerate(result["thread"], 1):
            print(f"  {i}. [{m['folder']} uid={m['uid']}]")
            print(f"     from:    {m['from']}")
            print(f"     subject: {m['subject']}")
            print(f"     date:    {m['date']}")
            print(f"     msgid:   {m['message_id']}")
            print()
finally:
    client.disconnect()
