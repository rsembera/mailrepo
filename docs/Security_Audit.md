# MailRepo — Pre-Release Security Audit

**Date:** February 4, 2026  
**Reviewer:** Claude Opus 4.5  
**Scope:** Full codebase review prior to manual testing  
**Result:** ✅ No critical issues found. Proceed with testing.

---

> **Addendum (June 9, 2026):** This audit is a point-in-time record and predates the v2 crypto migration of May 29, 2026. References to PBKDF2 and Fernet below describe the retired v1 scheme. The current scheme is Argon2id (m=256 MiB, t=6) → HKDF-Expand with domain-separated info strings → AES-256-GCM, with SQLCipher unlocked via raw-key PRAGMA. See the module docstring in `core/encryption.py` for the authoritative description, and `docs/Code_Review_Findings.md` (Session 38) for the current pre-tag code review. The class-level key management pattern noted below remains in place and is documented as a deliberate design decision, with rationale, in the encryption module docstring.

> **Addendum (August 9, 2026 — Session 68):** The key file moved to the v3 envelope. The master key is now 32 random bytes, wrapped twice: once under Argon2id(password) and once under HKDF(recovery key). `file_key` and `db_key` still derive from the master by HKDF-Expand exactly as before, and archive ciphertext is unchanged — only the key file format moved (MRC2 → MRC3). Two consequences for this document:
>
> - **Password change no longer re-encrypts anything on v3 archives.** It replaces the 61-byte password wrapper. The old password is genuinely revoked because the master is random and independent of it — this is why the migration mints a fresh master and re-encrypts once rather than reusing the password-derived value.
> - **The recovery key is a second full-access credential.** See the new threat-model section below.
>
> The CSRF row under Authentication is unchanged and remains correct.

---

## Threat model: the recovery key (added Session 68)

The recovery key is a printable 160-bit secret that opens the archive **without the master password**. That is the point of it, and it is also its whole risk surface. For MailRepo's audience — solo lawyers, therapists, journalists holding confidential material — this deserves stating plainly rather than burying in a tooltip.

**What it changes.** Before v3, the security of an archive was exactly the security of one password held in one person's head. After v3, it is the weaker of that password and wherever the recovery key physically ends up. A key photographed and left in cloud photo storage, or filed in the same drawer as an unlocked laptop, is a full compromise of the archive regardless of how strong the password is.

**What MailRepo does about it.**

| Measure | Detail |
|---|---|
| Shown once | Generated at setup or upgrade, rendered into a single HTTP response, never stored server-side |
| Never in the session | Flask sessions are signed, not encrypted; a key placed there would be readable in the browser cookie jar. Guarded by `test_recovery_key_never_enters_the_session` |
| Rotatable | `rotate_recovery_key()` revokes the old key immediately, without a password change or re-encryption |
| Rotation gated on password | An unlocked session alone cannot mint a durable second credential |
| Post-recovery reset gated on the recovery login itself | The no-old-password reset at `/auth/login/recovery/new-password` is reachable only by a session that was established with the recovery key (`session["via_recovery_key"]`), and its form carries a CSRF token. Found and closed in Session 70: before the gate, any unlocked session could replace the master password without proving any credential — the same capability the rotation gate exists to withhold. Guarded by `test_password_reset_requires_a_recovery_login` |
| Rate limited | Recovery-key login shares the password login's limiter — it is an equivalent credential and must not be the cheaper thing to attack |
| Cleared from the DOM | The Settings rotation view blanks the key once acknowledged |

**What it does not do.** MailRepo cannot tell whether the key was written down, where it went, or whether it has been copied. There is no usage log, no "last used" indicator, and no way to detect that someone else has a copy. A user who suspects exposure has exactly one remedy: rotate.

**Guidance given in-product.** The setup and rotation screens tell the user to store it like a spare key to their office — somewhere physical, somewhere private, and not alongside the password. The downloadable text file repeats this, because that file is the copy most likely to be read months later.

**Not offered deliberately.** There is no "email me my recovery key", no cloud escrow, and no account-recovery path through Anthropic or anyone else. Every one of those would move the archive's security off the user's own premises, which is the property the product exists to provide.

**Known divergence from EdgeCase (raised Session 71, not yet actioned).** MailRepo's recovery key currently grants a full authenticated session, with the password reset offered rather than required. EdgeCase treats the same credential strictly as a password-reset mechanism that cannot log you in at all. EdgeCase's model is the correct one for a credential that lives on paper, and MailRepo should adopt it before 1.0 — see `Post_1_0_Backlog.md`. Until then, the recovery key is closer to a permanent parallel password than to a break-glass credential, which is a stronger claim on the user's storage discipline than this page otherwise implies.

**Rotation does not reach existing backups.** This is the most important limitation on this page, and it is a property of encrypted backups generally rather than a MailRepo shortcoming.

A backup is an immutable snapshot that includes the key file as it stood when the backup was taken. Changing the master password or rotating the recovery key rewrites the *live* key file only. Every existing backup still contains the old one, so the old credential still opens those copies — and copies are precisely what tends to live somewhere less controlled: a cloud folder, a sync target, an external drive, a version history the user cannot enumerate.

MailRepo deliberately does **not** re-encrypt old backups on credential change:

- They are the artifacts you need when something has already gone wrong. Rewriting the whole corpus puts that at risk for a benefit that is partial at best; an interruption partway leaves a mixed and possibly damaged set.
- It cannot reach every copy. Partial revocation is worse than none, because it produces confidence that is not warranted.
- It does not work at all for pre-v2 backups, where there is no wrapper to swap and the content itself would need re-encrypting under a scheme whose code has been removed.

**So the remedy for a genuinely compromised credential is to rotate *and* to destroy the backups that predate the rotation.** That is a policy action, not something software can do on the user's behalf across storage it does not control.

To make this visible rather than implicit, every restore point is annotated with which credentials it needs (Session 69). The check compares SHA-256 prefixes of the two wrapper halves against the live key file — no passwords required, because each rewrap touches one half and leaves the other byte-identical. Restore points are labelled as current, predating recovery keys, needing an older password, needing an older recovery key, or — for key files predating the v2 magic — unopenable by any current build.

---

## Summary

Comprehensive review of all security-critical code paths: encryption, authentication, database, API endpoints, file handling, IMAP connectivity, and frontend XSS protection. The security posture is solid for a localhost single-user application.

---

## Encryption (core/encryption.py)

| Check | Status | Detail |
|-------|--------|--------|
| Key derivation | ✅ | PBKDF2 with 480,000 iterations (SHA256) |
| Salt generation | ✅ | 32-byte, secrets.token_bytes() |
| Cipher | ✅ | Fernet (AES-128-CBC) |
| DB key derivation | ✅ | Separate salt suffix from file encryption key |
| Password storage | ✅ | Never stored; verification token only |
| Password verification | ✅ | Constant-time via Fernet.decrypt() |
| Key management | ✅ | In-memory with lock/unlock pattern |
| Password change | ✅ | Re-encrypts all files and credentials |

## Authentication (web/blueprints/auth.py)

| Check | Status | Detail |
|-------|--------|--------|
| Rate limiting | ✅ | 5 attempts per 60 seconds per IP |
| Session timeout | ✅ | Configurable (15/30/60/120 min or never) |
| CSRF protection | ✅ | Token validated on all POST/PUT/DELETE/PATCH to `/api/` paths. Frontend supplies it via a global `window.fetch` interceptor in `base.html` (commit `461bf6b`), which reads the meta tag and injects the header — so individual call sites correctly do not set it themselves |
| Session tracking | ✅ | Activity-based with automatic logout |
| Password policy | ✅ | Minimum 12 characters |
| Trash cleanup | ✅ | Expired items cleaned on login |

---

## Database (core/database.py)

| Check | Status | Detail |
|-------|--------|--------|
| Encryption at rest | ✅ | SQLCipher (entire database encrypted) |
| SQL injection | ✅ | All queries parameterized throughout |
| Foreign keys | ✅ | Enabled |
| Concurrency | ✅ | WAL mode |
| Transactions | ✅ | Proper management with rollback |
| Schema versioning | ✅ | Migrations with version tracking |
| Full-text search | ✅ | FTS5 for subject, sender, body_text |

---

## API Security (web/app.py)

| Check | Status | Detail |
|-------|--------|--------|
| Auth enforcement | ✅ | before_request check on all routes |
| CSRF validation | ✅ | All state-changing requests validated |
| Session timeout | ✅ | Enforced (except SSE streaming endpoints) |
| Error responses | ✅ | 401 for auth, 403 for CSRF |
| Public endpoints | ✅ | Whitelist: auth.login, auth.setup, static only |

## IMAP (core/imap.py)

| Check | Status | Detail |
|-------|--------|--------|
| Credential storage | ✅ | Fernet-encrypted in database |
| Connection security | ✅ | SSL/TLS by default (port 993) |
| Connection testing | ✅ | Validated before saving credentials |
| Auth failure handling | ✅ | Proper error messages, no credential leakage |
| Provider auto-detect | ✅ | Gmail, Outlook, iCloud, Fastmail, etc. |

---

## File System (web/blueprints/api/filesystem.py)

| Check | Status | Detail |
|-------|--------|--------|
| Path traversal | ✅ | os.path.realpath() protection |
| File size limits | ✅ | 50MB cap for read operations |
| Permission errors | ✅ | Handled gracefully |
| Hidden file filtering | ✅ | Optional, defaults to filtered |
| PST temp validation | ✅ | Must be in system temp with mailrepo_pst_ prefix |
| Temp file cleanup | ✅ | Proper cleanup on unmount |

---

## Email Archives (web/blueprints/api/emails.py)

| Check | Status | Detail |
|-------|--------|--------|
| Storage encryption | ✅ | All archived emails as .eml.enc |
| Decryption scope | ✅ | On-access only, never at rest |
| Header decoding | ✅ | RFC 2047 compliant |
| Attachment handling | ✅ | Content-type validation |
| Deletion model | ✅ | Soft delete (trash) before permanent |
| File path validation | ✅ | Validated before access |

## Settings & Reset (web/blueprints/api/settings.py)

| Check | Status | Detail |
|-------|--------|--------|
| Database reset | ✅ | Requires password + typing "RESET" |
| Timeout validation | ✅ | Whitelist: 15/30/60/120/0 only |
| Trash retention | ✅ | Whitelist: 0/7/30/90/365 only |
| Session keepalive | ✅ | Dedicated endpoint for extension |

---

## Backup (utils/backup.py)

| Check | Status | Detail |
|-------|--------|--------|
| WAL checkpoint | ✅ | Before backup (ensures completeness) |
| Path validation | ✅ | Folder picker validates paths |
| Permission checks | ✅ | Directory access verified |
| Restore safety | ✅ | Staging mechanism with rollback |

---

## Configuration (core/config.py)

| Check | Status | Detail |
|-------|--------|--------|
| Flask secret key | ✅ | secrets.token_hex(32) |
| Key file permissions | ✅ | 0o600 |
| Session cookies | ✅ | HttpOnly, SameSite=Lax |
| Environment vars | ✅ | MAILREPO_DATA_DIR supported |

---

## Frontend XSS (web/static/js/utils.js)

| Check | Status | Detail |
|-------|--------|--------|
| HTML escaping | ✅ | escapeHtml() utility, consistently used |
| DOM insertion | ✅ | User data escaped before insertion |
| API responses | ✅ | Backend returns JSON (no server-side HTML) |
| Email rendering | ✅ | Sandboxed iframe, no script execution |

---

## Minor Observations

These are noted for completeness but do not require action before release:

1. **SESSION_COOKIE_SECURE = False** — Comment says "Set True in production with HTTPS." Acceptable for localhost-only app; would need HTTPS to set True.

2. **SQLCipher fallback** — Code checks for SQLCipher availability and falls back to regular SQLite. Fine for development; production installs should enforce SQLCipher. (The app warns at startup if SQLCipher is unavailable.)

3. **Rate limiting in memory** — Login attempt tracking uses an in-memory dict, resets on restart. Acceptable for single-user local app; an attacker would need localhost access already.

4. **Duplicate logger import** — auth.py imports logger twice (lines 16-18). Harmless but untidy.

---

## Known Technical Debt (Not Security Issues)

- **Circular dependency:** staging.js ↔ folder-selection.js import from each other. Works correctly, causes no bugs. Proper fix would extract shared state into staging-state.js module. Deferred — not worth the risk of refactoring at ship stage.

- **Event handling patterns:** Mix of inline onclick and addEventListener across frontend components. Functional but inconsistent. Documented in Code_Quality_Review.md.

---

## Conclusion

The application's security model is well-implemented for its intended use case (single-user, localhost, encrypted local storage). All standard attack vectors are addressed: SQL injection (parameterized queries), XSS (escapeHtml + JSON API), CSRF (token validation), path traversal (realpath), and authentication (rate limiting + session management). Encryption uses current best practices with proper key derivation and separate keys for database vs. file encryption.

**Recommendation:** Proceed with manual testing per TESTING_CHECKLIST.md.
