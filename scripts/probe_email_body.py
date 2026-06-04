#!/usr/bin/env python3
"""One-off probe: print the structure and content of a specific email.

Usage:
    source venv/bin/activate
    python scripts/probe_email_body.py <account_id> <folder> <uid>

Shows the MIME structure of the message, then prints what fetch_full()
returns (the same data the email viewer gets), so we can see whether
the issue is upstream (server returned empty body) or downstream (viewer
mishandled non-empty body).
"""

import getpass
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
os.chdir(REPO)
sys.path.insert(0, REPO)

if len(sys.argv) != 4:
    print(__doc__)
    sys.exit(2)

account_id = int(sys.argv[1])
folder = sys.argv[2]
uid = sys.argv[3]

pw = getpass.getpass("MailRepo master password: ")

from core.database import Database
from core.encryption import Encryption, InvalidPasswordError
from core.imap import IMAP

try:
    Encryption.unlock(pw)
except InvalidPasswordError:
    print("Incorrect password.")
    sys.exit(1)

Database.set_key(Encryption.get_db_key())
Database.initialize()

row = Database.fetchone(
    "SELECT email, credentials_encrypted FROM accounts WHERE id = ?",
    (account_id,),
)
if not row or not row["credentials_encrypted"]:
    print(f"No credentials for account {account_id}")
    sys.exit(1)

print(f"Account: {row['email']}\nFolder: {folder}\nUID: {uid}\n")

client = IMAP.connect_with_credentials(row["credentials_encrypted"])
try:
    client.select_folder(folder)

    # 1. Raw structure — what MIME parts are present
    print("=" * 60)
    print("MIME STRUCTURE")
    print("=" * 60)
    import email

    raw = client.fetch_raw(uid)
    msg = email.message_from_bytes(raw)

    def walk(part, depth=0):
        prefix = "  " * depth
        ct = part.get_content_type()
        cd = str(part.get("Content-Disposition", ""))
        cid = part.get("Content-ID", "")
        fn = part.get_filename() or ""
        size = ""
        if not part.is_multipart():
            payload = part.get_payload(decode=True) or b""
            size = f"  [{len(payload)} bytes]"
        print(f"{prefix}{ct}  disp={cd or '-'}  cid={cid or '-'}  filename={fn or '-'}{size}")
        if part.is_multipart():
            for sub in part.get_payload():
                walk(sub, depth + 1)

    walk(msg)

    # 2. fetch_full output — what the viewer actually sees
    print()
    print("=" * 60)
    print("fetch_full() OUTPUT (what the viewer gets)")
    print("=" * 60)
    full = client.fetch_full(uid)
    for k in ("subject", "from", "to", "date", "message_id"):
        print(f"  {k}: {full.get(k)!r}")
    print(f"  text_body: {full.get('text_body')!r}")
    html = full.get("html_body")
    if html is None:
        print("  html_body: None")
    else:
        print(f"  html_body length: {len(html)} chars")
        print(f"  html_body first 500: {html[:500]!r}")
        print(f"  html_body last 200: {html[-200:]!r}")
    print(f"  attachments: {len(full.get('attachments', []))} listed")
    for a in full.get("attachments", []):
        print(f"    - {a}")
finally:
    client.disconnect()
