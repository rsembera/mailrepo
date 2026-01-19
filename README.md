# MailRepo

Encrypted email archiving for solo practitioners.

**Philosophy:** Your correspondence, your machine, your control.

## Features

- Connect Gmail accounts via OAuth
- Browse and file emails into organized folders
- Choose encrypted or unencrypted storage per folder tree
- Batch filing with Stage → Review → Commit workflow
- Import existing .mbox archives
- Export archives as ZIP files
- Search across archived emails

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/mailrepo.git
cd mailrepo

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

Then open http://localhost:5000 in your browser.

## Gmail API Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable the Gmail API
4. Create OAuth 2.0 credentials (Desktop app type)
5. Download `credentials.json` to the `config/` directory

## Configuration

On first run, you'll be prompted to:
1. Create a master password (encrypts OAuth tokens and secure archives)
2. Create your first archive folder (choose encrypted or unencrypted)
3. Connect your Gmail account

## Data Storage

All data is stored locally in `~/mailrepo/`:

```
~/mailrepo/
├── data/mailrepo.db      # SQLite database
├── archive/              # Archived emails (.eml or .eml.enc)
├── config/               # OAuth credentials
└── backups/              # Manual/auto backups
```

## License

MIT License - See LICENSE file for details.
