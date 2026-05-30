# MailRepo

**Encrypted email archiving for solo practitioners.**

> Your correspondence, your machine, your control.

Therapists, lawyers, accountants, and journalists handle sensitive client correspondence every day. Most email is stored on servers where administrators can read it in plaintext. MailRepo lets you archive that correspondence locally, encrypted with a password only you know — no cloud, no third parties, no exposure.

<!-- SCREENSHOTS: Insert 4 screenshots here when available
  1. Main browse view (sidebar + folder tree)
  2. Email list with staged emails
  3. Review screen before committing
  4. Email viewer
-->

---

## Features

- **Encrypted at rest** — Every archived email and your entire database are encrypted with your master password. Without it, the files are unreadable.
- **IMAP support** — Connects to Gmail, iCloud, Fastmail, and any standard IMAP server using app-specific passwords. Your email password is never stored.
- **Stage → Review → Commit workflow** — Browse your inbox, select emails to file, review your selections, then commit them to your archive in one batch.
- **Organized folder structure** — Create a folder hierarchy that matches your practice (e.g. Clients → Smith, John).
- **Full-text search** — Search across subjects, senders, recipients, and email body text.
- **Import existing archives** — Bring in existing email from .mbox files (including Apple Mail exports), individual .eml files, and .pst files.
- **Export as ZIP** — Export any folder as standard .eml files you can open in any email client.
- **Backup and restore** — Full and incremental backups with one click.
- **Retention vault** — Permanently delete emails with a clear audit trail.

---

## Who It's For

MailRepo is designed for solo practitioners who need to:

- Keep client correspondence records for compliance (HIPAA, PHIPA, legal privilege)
- Maintain an organized archive without relying on cloud storage
- Ensure that sensitive correspondence is encrypted and under their direct control

It is a **single-user, local application**. It runs on your machine and is accessible in your browser at `localhost:5050`. It is not a cloud service and does not phone home.

---

## Installation

### Requirements

- Python 3.11 or later
- macOS or Linux (Windows untested)
- SQLCipher (usually installed automatically with the `sqlcipher3` Python package)

### Steps

```bash
# Clone the repository
git clone https://github.com/rsembera/mailrepo.git
cd mailrepo

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the application
python main.py
```

Then open **http://localhost:5050** in your browser.

To start in development mode with auto-reload:

```bash
python main.py --dev
```

To run on a different port:

```bash
python main.py --port=8080
```

### PST Import (Optional)

To import Outlook .pst files, you need `libpst` installed at the system level:

- **macOS:** `brew install libpst`
- **Debian/Ubuntu:** `sudo apt install pst-utils`

---

## First Run

1. **Set a master password.** This is the only password that matters. It encrypts your database and every archived email. Choose something strong and don't forget it — there is no recovery mechanism by design.

2. **Create your first archive folder.** Give it a name that makes sense for your practice (e.g. "Clients", "Active Matters").

3. **Connect an email account.** Enter your IMAP server details. For Gmail and iCloud, use an app-specific password rather than your main account password. MailRepo will auto-detect server settings for common providers.

---

## How the Workflow Works

**Browse & Stage** — Select an account from the sidebar and browse your inbox. Check the emails you want to archive. A badge tracks how many you've staged. You can browse multiple folders and accounts before committing.

**Review** — Click Review to see all staged emails grouped by source. You can change the destination folder, remove individual emails from the batch, and choose what happens to the originals on the server (leave in place, move to trash, delete).

**Commit** — Click Commit. MailRepo downloads each email, encrypts it, saves it to your archive, and updates the database. Progress is shown in real time. Any failures are reported and can be retried.

---

## Security Model

| Data | Protection |
|------|------------|
| Database | SQLCipher (AES-256) |
| Archived emails | AES-256-GCM with per-file random nonce |
| IMAP credentials | AES-256-GCM |
| Master password | Argon2id (m=256 MiB, t=6, p=1) → HKDF-Expand into file & DB keys |
| File format | `[0x02][12-byte nonce][ciphertext][16-byte GCM tag]` |
| Salt file | `MRC2` magic + 32-byte salt + GCM-encrypted verification token |

The master password is never stored. On startup, MailRepo attempts to decrypt a verification token with keys derived from the entered password — if the GCM authentication succeeds, the session proceeds. If not, access is denied.

The 0x02 per-file version byte and `MRC2` salt magic are forward infrastructure: a future crypto migration can identify v2 archives and act accordingly. The version byte is bound into GCM AAD, so tampering with it breaks the auth check.

MailRepo runs on `127.0.0.1` (localhost only) and does not accept connections from other machines on your network by default. For remote access from your own devices, [Tailscale](https://tailscale.com) works well.

---

## Data Storage

All data lives inside the application directory:

```
mailrepo/
├── data/
│   ├── mailrepo.db      # SQLCipher encrypted database
│   ├── .salt            # Password salt and verification token
│   └── .secret_key      # Flask session key
├── archive/
│   └── {folder_id}/
│       └── *.eml.enc    # Encrypted email files
└── backups/             # Backup archives
```

To store data in a different location, set the `MAILREPO_DATA_DIR` environment variable before starting the application.

**Backup = copy the folder.** Everything MailRepo needs is in these directories. Back them up like any other important files.

---

## Troubleshooting

**SQLCipher fails to install**

On some systems the `sqlcipher3` Python package needs the SQLCipher C library installed first:

- macOS: `brew install sqlcipher`
- Debian/Ubuntu: `sudo apt install libsqlcipher-dev`

Then retry `pip install -r requirements.txt`.

**"Master password incorrect" on first run**

This usually means the `.salt` file was created but something went wrong during setup. Delete `data/.salt` and `data/mailrepo.db` and start again. (Only do this if you haven't archived anything yet.)

**Gmail connection refused**

Gmail requires an [App Password](https://support.google.com/accounts/answer/185833) — your regular Google password will not work. Generate one in your Google Account settings under Security → 2-Step Verification → App passwords.

---

## License

GNU Affero General Public License v3.0. See [LICENSE](LICENSE) for details.

The AGPL requires that if you modify and deploy this software to provide a service to others, you must make your modified source code available. For personal use, no restrictions apply.
