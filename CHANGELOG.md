# Changelog

All notable changes to MailRepo will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

_Nothing yet._

---

## [1.0.0] — Unreleased (dogfooding)

The first stable release. Local-first encrypted email archiving for solo
practitioners (lawyers, therapists, journalists, etc.) who need local
control over sensitive client correspondence without cloud dependency.

Rick is dogfooding 1.0 before tagging. This section captures what 1.0
is; the date and tag will land when dogfooding settles.

### Added

#### Encryption
- **AES-256-GCM file encryption** for every archived email and every
  stored IMAP credential. Per-file random 96-bit nonce. Wire format:
  `[0x02 version byte][12-byte nonce][ciphertext][16-byte GCM tag]`,
  with the version byte bound into GCM AAD so tampering breaks the
  auth check.
- **Argon2id key derivation** at memory-hard parameters
  (m=256 MiB, t=6, p=1), measured ~750 ms per derivation on Apple M4.
  A single Argon2id master feeds HKDF-Expand with domain-separated
  `info` strings (`mailrepo.file.v2`, `mailrepo.db.v2`) into the file
  key and the SQLCipher DB key, keeping the slow derivation single per
  unlock.
- **SQLCipher AES-256 database** with class-level `threading.RLock`
  serializing all access and a `_migration_active` flag that grants
  exclusive ownership during rekey windows.
- **Forward-compatible salt file** with `MRC2` magic and a per-file 0x02
  version byte so any future crypto migration can detect "this archive
  is on v2" and act accordingly.
- **Atomic salt file writes** via `temp + fsync(file) + os.replace +
  fsync(directory)` — crash-safe against power loss during rekey.

#### Workflow
- **Stage → Review → Commit pipeline** with SSE progress streaming.
  Resumable commits via the `pending_commit` table: if an SSE stream is
  interrupted, the next call with `resumeCommitId` picks up from where
  it left off.
- **IMAP integration** with auto-detection for Gmail (incl. Google
  Workspace), iCloud, Outlook / Hotmail / Live, and Fastmail.
- **Gmail-aware post-commit options.** "Delete" is hidden for Gmail
  accounts because Gmail's IMAP delete just archives — misleading
  semantics. "Archive" maps to `[Gmail]/All Mail` at the IMAP layer.
- **Master password change** with file-walk re-encryption + SQLCipher
  rekey + new salt file write. Non-overridable backup-≤24h check
  before the irreversible DB rekey window.
- **Encrypted bulk export** to per-export-password ZIP archives via
  pyzipper (AES-256). Non-PDF attachments included as sibling files in
  the wrapper ZIP. First-use friction modal explaining the encryption
  boundary.
- **Archived email file operations:** move, soft delete, restore,
  permanent delete; batch select with "X of Y selected" counter;
  dedicated Trash view with Folders + Emails tabs.

#### Backup
- **Session-based backup** with 7-day incremental + full cycle.
  External `data/.backup_state.json` keeps the hash baseline outside
  the encrypted DB to avoid spurious change detection from WAL
  checkpoints.
- **Configurable retention** (default 6 months).
- **Post-backup rsync hook** for replication to a remote server.
- **Persistent "Last Checked" indicator** in the Backup & Restore
  status card that updates on every Backup Now click, even on no-op.

#### UI
- **Three-pane layout:** rail / sidebar / main, with resizable sidebar.
- **Five themes:** Pine (default), Lagoon, Graphite, Midnight, Atlantic.
- **Right-click context menu** for folder operations.
- **Collapsible search tips** and subfolder breadcrumbs.
- **Full-text search** via FTS5 with native column operators
  (`sender:`, `recipients:`, `subject:`, `body_text:`).
- **IMAP folder list caching** with a two-layer approach (TTL
  short-circuit + CONDSTORE/HIGHESTMODSEQ) and a manual refresh button.

#### Tooling
- **68 unit tests** across encryption (v2 wire format + AAD binding),
  database (thread safety), email parser, API folders, and password
  change (15 tests covering happy path, refusal cases, resumability,
  and corruption-halt behavior).

[Unreleased]: https://github.com/rsembera/mailrepo/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/rsembera/mailrepo/releases/tag/v1.0.0
