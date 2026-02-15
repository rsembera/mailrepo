# MailRepo

Encrypted email archiving for solo practitioners.

**Philosophy:** Your correspondence, your machine, your control.

## Features

- **Full encryption at rest** — Database and all archived emails encrypted with your master password using SQLCipher
- **IMAP support** — Connect to Gmail, iCloud, Fastmail, or any IMAP server
- **Batch filing workflow** — Stage → Review → Commit emails to organized folders
- **Full-text search** — Search across subjects, senders, recipients, and email content (FTS5)
- **Import existing archives** — Import .mbox, .eml, and .pst files (PST requires libpst-utils)
- **Export as ZIP** — Export archives as standard .eml files

## Installation

```bash
# Clone the repository
git clone https://github.com/rsembera/mailrepo.git
cd mailrepo

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

Then open http://localhost:5050 in your browser.

## First Run

1. **Create master password** — This encrypts your entire database and all archived emails
2. **Create your first archive folder** — e.g., "Client Files", "Personal"
3. **Connect an email account** — Enter IMAP credentials (auto-detects server for common providers)

## Security Model

MailRepo uses defense in depth:

| Data | Protection |
|------|------------|
| Database | SQLCipher (AES-256 encryption) |
| Archived emails | Fernet encryption (AES-128-CBC) |
| IMAP credentials | Fernet encryption |
| Master password | PBKDF2 key derivation (480,000 iterations) |

The master password is never stored — only a verification token encrypted with the derived key.

## Data Storage

All data is stored in the application directory:

```
mailrepo/
├── data/
│   ├── mailrepo.db          # SQLCipher encrypted database
│   ├── .salt                # Password salt + verification
│   └── .secret_key          # Flask session key
├── archive/
│   └── {folder_id}/
│       └── *.eml.enc        # Encrypted email files
├── config/                  # (reserved for future use)
└── backups/                 # Manual/auto backups
```

To use a different location, set the `MAILREPO_DATA_DIR` environment variable.

## Requirements

- Python 3.11+
- SQLCipher libraries (bundled with `sqlcipher3` package on most platforms)
- **For PST import:** libpst-utils (`apt install pst-utils` on Debian/Ubuntu)

## License

GNU Affero General Public License v3.0 — See LICENSE file for details.
