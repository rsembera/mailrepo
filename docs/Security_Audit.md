# MailRepo — Pre-Release Security Audit

**Date:** February 4, 2026  
**Reviewer:** Claude Opus 4.5  
**Scope:** Full codebase review prior to manual testing  
**Result:** ✅ No critical issues found. Proceed with testing.

---

> **Addendum (June 9, 2026):** This audit is a point-in-time record and predates the v2 crypto migration of May 29, 2026. References to PBKDF2 and Fernet below describe the retired v1 scheme. The current scheme is Argon2id (m=256 MiB, t=6) → HKDF-Expand with domain-separated info strings → AES-256-GCM, with SQLCipher unlocked via raw-key PRAGMA. See the module docstring in `core/encryption.py` for the authoritative description, and `docs/Code_Review_Findings.md` (Session 38) for the current pre-tag code review. The class-level key management pattern noted below remains in place and is documented as a deliberate design decision, with rationale, in the encryption module docstring.

> **Addendum (August 9, 2026 — Session 68):** The key file moved to the v3 envelope. The master key is now 32 random bytes, wrapped twice: once under Argon2id(password) and once under HKDF(recovery key). `file_key` and `db_key` still derive from the master by HKDF-Expand exactly as before, and archive ciphertext is unchanged — only the key file format moved (MRC2 → MRC3). Two consequences for this document:
>
> - **Password change no longer re-encrypts anything on v3 archives.** It replaces the 61-byte password wrapper. The old password is revoked *against the live key file* because the master is random and independent of it — this is why the migration mints a fresh master and re-encrypts once rather than reusing the password-derived value. It is not revoked against anyone holding an earlier copy of the key file (a backup): the master never changes, so an old `.salt` plus the old password still derives it. See "Rotation does not reach existing backups" below and the September 2026 review, finding 8.
> - **The recovery key is a second full-access credential.** See the new threat-model section below.
>
> The CSRF row under Authentication is unchanged and remains correct.

> **Addendum (September 3, 2026 — Session 93):** A second full review, `docs/Security_Review_2026-09.md`, found six issues worth fixing before the next release and corrected three rows in this document (Argon2id `p`, key-file permissions, session timeout — marked inline). All twenty findings are fixed on `main` as of Session 93, including finding 8 — implemented as described in the design note below, with one refinement: the halves are bound by an HMAC over the whole file (keyed from the master) rather than per-wrapper AAD, so an MRC3 file upgrades in place without re-wrapping and without the recovery key. Start from the September review, not this page, for the current map.

> **Design note for finding 8 (implemented Session 93; see `core/keyfile_binding.py` and `core/master_rotation.py`).** (a) New key-file format `MRC4` = `MRC3` layout plus a 16-byte random `archive_id`; every wrapper's GCM AAD becomes `version ‖ magic ‖ salt_pw ‖ salt_rk ‖ archive_id` so a spliced half or a rolled-back file fails to open; the same `archive_id` is stored in the encrypted `settings` table and compared at login (mismatch = "this key file was not written for this archive", refuse). Detects splicing and rollback; cannot prevent offline use of an old file plus old password. (b) "Rotate master key" as an explicit option on password change and post-recovery reset: mint a fresh master, re-encrypt every archive file and rekey SQLCipher — `migrate_to_v3` already implements the full walk with backup gating and an interruption marker, and generalises. (c) Migration MRC3 → MRC4 at first login after upgrade, atomic, no re-encryption. Tests: splice old recovery half into live file → refuse; restore old `.salt` over live → refuse at login with a clear message; rotation → old file plus old password derives a master that opens nothing.

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
| Cannot open the archive | Since Session 72 the recovery key grants no session at all. `/auth/login/recovery` verifies it and hands a short-lived server-side token to a **mandatory** password reset; the key never enters a URL or a cookie. This is what keeps it a break-glass credential rather than a second password — otherwise a user who skipped the reset would reach for the printed key at every login. Guarded by `test_recovery_key_does_not_unlock_the_archive` and `test_reset_does_not_log_the_user_in` |
| No auto-login after reset | The user signs in with the new password while the recovery key is still in hand — the cheapest confirmation the password is what they think it is |
| Rate limited | Recovery-key login shares the password login's limiter — it is an equivalent credential and must not be the cheaper thing to attack |
| Cleared from the DOM | The Settings rotation view blanks the key once acknowledged |

**What it does not do.** MailRepo cannot tell whether the key was written down, where it went, or whether it has been copied. There is no usage log, no "last used" indicator, and no way to detect that someone else has a copy. A user who suspects exposure has exactly one remedy: rotate.

**Guidance given in-product.** The setup and rotation screens tell the user to store it like a spare key to their office — somewhere physical, somewhere private, and not alongside the password. The downloadable text file repeats this, because that file is the copy most likely to be read months later.

**Not offered deliberately.** There is no "email me my recovery key", no cloud escrow, and no account-recovery path through Anthropic or anyone else. Every one of those would move the archive's security off the user's own premises, which is the property the product exists to provide.

**Resolved Session 72.** MailRepo has adopted EdgeCase's model. The recovery key no longer grants a session at all: `/auth/login/recovery` verifies it, hands a short-lived server-side token to the reset step, and the reset is mandatory. After a successful reset the user is not logged in — they sign in with the new password while the recovery key is still in hand. `session["via_recovery_key"]` no longer exists, and the Session 70 gating it supported is superseded. The recovery key is now a break-glass credential rather than a parallel password.

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

> ⚠️ **The table below describes the RETIRED v1 scheme (PBKDF2 + Fernet), removed in May 2026.** It is kept as the point-in-time record of the February audit. For what MailRepo does today, see the "Current scheme" table immediately after it.

| Check (v1 — HISTORICAL) | Status | Detail |
|-------|--------|--------|
| Key derivation | ✅ | PBKDF2 with 480,000 iterations (SHA256) |
| Salt generation | ✅ | 32-byte, secrets.token_bytes() |
| Cipher | ✅ | Fernet (AES-128-CBC) |
| DB key derivation | ✅ | Separate salt suffix from file encryption key |
| Password storage | ✅ | Never stored; verification token only |
| Password verification | ✅ | Constant-time via Fernet.decrypt() |
| Key management | ✅ | In-memory with lock/unlock pattern |
| Password change | ✅ | Re-encrypts all files and credentials |

### Current scheme (v3 envelope, as of August 2026)

| Check | Status | Detail |
|-------|--------|--------|
| Key derivation | ✅ | Argon2id, m=256 MiB, t=6, p=1 (`core/encryption.py`; pinned by `tests/test_kdf_cost.py`) |
| Subkey derivation | ✅ | HKDF-Expand from the master, domain-separated info strings for file vs DB |
| Salt generation | ✅ | 32-byte, `secrets.token_bytes()`; fresh salt on every rewrap |
| Cipher | ✅ | AES-256-GCM, random 96-bit nonce per encryption |
| Master key | ✅ | 32 random bytes, wrapped twice — under Argon2id(password) and under HKDF(recovery key). Independent of any password, which is what makes revocation real |
| Key file | ✅ | MRC3, fixed 190 bytes; length validated before use |
| Password storage | ✅ | Never stored. A wrong password fails the GCM tag on the wrapper — no separate verification token needed |
| DB key | ✅ | SQLCipher via raw-key PRAGMA, derived from the master, never from the password directly |
| Password change | ✅ | 61-byte rewrap of the password wrapper. No file walk, no DB rekey, no non-resumable window |
| Recovery key | ✅ | 160 bits, generated not chosen, shown once, never stored. Resets the password; cannot open the archive (Session 72) |
| Credential rotation | ✅ | Password and recovery key rotate independently; each rewrap leaves the other wrapper byte-identical |

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
| CSRF validation | ✅ | Middleware covers every state-changing request on a path containing `/api/`. Forms outside that (`/auth/upgrade`, `/auth/setup/recovery-key-saved`, `/archive/create`) carry and verify a token explicitly. `/archive/create` was missed until August 2026 — it is the pattern a maintainer copies, so new non-`/api/` forms must do the same |
| Session timeout | ✅ | Enforced server-side since Session 93 (idle watchdog + status poll exempt from activity); before that the poll refreshed activity and the timeout never fired — see the September 2026 review, finding 1 |
| Error responses | ✅ | 401 for auth, 403 for CSRF |
| Public endpoints | ✅ | Whitelist only: `auth.login`, `auth.login_with_recovery_key`, `auth.set_password_post_recovery`, `auth.setup`, `static`. The two recovery routes are public by necessity — a user locked out of their archive has no session, so gating them would make them unreachable by exactly the person they exist for. The reset step's gate is a server-side handoff token minted only after a recovery key verifies |

## IMAP (core/imap.py)

| Check | Status | Detail |
|-------|--------|--------|
| Credential storage | ✅ | Encrypted in the database with the file key (AES-256-GCM since May 2026; this row read "Fernet-encrypted" until August) |
| Connection security | ✅ | SSL/TLS by default (port 993) |
| Connection testing | ✅ | Validated before saving credentials |
| Auth failure handling | ✅ | Proper error messages, no credential leakage |
| Provider auto-detect | ✅ | Gmail, Outlook, iCloud, Fastmail, etc. |

---

## File System (web/blueprints/api/filesystem.py)

| Check | Status | Detail |
|-------|--------|--------|
| Path traversal | ⚠️ | `/api/filesystem/*` uses realpath() to canonicalise, not to confine: it is an authenticated read-anywhere by design (import file picker). Backup/restore paths are validated since Session 93 |
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
| Key file permissions | ⚠️ | 0o600 applied only to the former `.secret_key` (removed Session 93). `.salt`, the database and archive files take the umask — see review finding 14 |
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
