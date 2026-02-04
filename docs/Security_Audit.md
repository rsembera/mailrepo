# MailRepo — Pre-Release Security Audit

**Date:** February 4, 2026  
**Reviewer:** Claude Opus 4.5  
**Scope:** Full codebase review prior to manual testing  
**Result:** ✅ No critical issues found. Proceed with testing.

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
| CSRF protection | ✅ | Token validated on all POST/PUT/DELETE/PATCH |
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
