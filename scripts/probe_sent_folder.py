#!/usr/bin/env python3
"""One-off probe: list each account's Sent / Archive / Trash folder names.

Run from the mailrepo repo root after activating the venv:

    source venv/bin/activate
    python scripts/probe_sent_folder.py

You'll be prompted for the MailRepo master password. The script lists each
configured account's special folders as identified by
core.imap.IMAP.get_special_folder(). No credentials or message contents
are printed.

Used during Stage Thread feature development to confirm our Sent-folder
candidate list covers the real accounts (NCF, Gmail). Delete this file
after we're confident the candidate list is right.
"""

import getpass
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
os.chdir(REPO)
sys.path.insert(0, REPO)

pw = getpass.getpass("MailRepo master password: ")

from core.database import Database
from core.encryption import Encryption, InvalidPasswordError
from core.imap import IMAP, IMAPError

# Same init sequence used by web/blueprints/auth.py after a successful login
try:
    Encryption.unlock(pw)
except InvalidPasswordError:
    print("Incorrect password.")
    sys.exit(1)

db_key = Encryption.get_db_key()
Database.set_key(db_key)
Database.initialize()

rows = Database.fetchall("SELECT id, email FROM accounts WHERE credentials_encrypted IS NOT NULL")
if not rows:
    print("No accounts configured.")
    sys.exit(0)

for row in rows:
    print(f"\n--- Account: {row['email']} (id={row['id']}) ---")
    try:
        creds_row = Database.fetchone(
            "SELECT credentials_encrypted FROM accounts WHERE id = ?", (row["id"],)
        )
        client = IMAP.connect_with_credentials(creds_row["credentials_encrypted"])
        try:
            for ftype in ("sent", "archive", "trash"):
                name = client.get_special_folder(ftype)
                print(f"  {ftype:8s} -> {name!r}")
        finally:
            client.disconnect()
    except IMAPError as e:
        print(f"  ERROR: {e}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
