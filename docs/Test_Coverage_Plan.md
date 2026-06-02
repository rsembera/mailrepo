# MailRepo — Test Coverage Plan

Created May 31, 2026 (Session 39). Tracks the post-1.0 effort to fill the
test-coverage gap surfaced in the pre-tag code review
(`docs/Code_Review_Findings.md` #5).

**Current suite:** 238 tests (encryption, password change, backup, database,
threading, email parser, auth, pending-commit, and the full API surface:
folders, emails, imports/export, accounts, commit, threads, settings).

**Guiding principle:** cover the paths where a silent regression would
*corrupt or lose data* or *break a security boundary* — not coverage parity
for its own sake. The expensive-to-test, low-payoff modules (IMAP protocol,
PDF rendering) are explicitly deprioritized and likely skippable.

---

## Priority order

### Tier 1 — security + data integrity (do first)

1. **`core/pending_commit.py`** — commit-resume state machine. Pure DB
   logic, no external deps. *Done in Session 39* (`tests/test_pending_commit.py`).

2. **`web/blueprints/auth.py`** — login, logout, password-change via the
   job-id flow (validates the Session 39 #1 security fix, which otherwise
   relies only on a manual test), rate-limit lockout trigger, and CSRF
   token verification. The security boundary. *Done in Session 40*
   (`tests/test_auth.py`, 22 tests, including the password-change job-id
   handoff end to end — which also surfaced/exercises the non-overridable
   "backup must be <=24h old" guard before a rekey). Elevated to Tier 1
   per Opus 4.7's suggestion — higher ROI than the generic API blueprints.
   - Test notes: exercise the rate-limit *lockout trigger* (5 failures →
     blocked) without waiting out the 60s window; don't test the time-based
     reset unless `time` is mocked. For CSRF, use the raw test client (not
     the `authenticated_client` wrapper, which auto-adds the header):
     POST without `X-CSRF-Token` → 403, with the right token → passes.

### Tier 2 — user-facing API surface (high value, low effort) — *Done in Session 41*

The Flask test-client scaffolding already exists — `tests/test_api_folders.py`
is a working template and `conftest.py` provides `initialized_app` and
`authenticated_client`. Each blueprint is a short sitting.

3. **`api/emails.py`** — view / move / soft-delete / restore / batch select.
   *Done (`tests/test_api_emails.py`, 28 tests): FTS search with folder
   scoping + subfolder toggle + trash exclusion, the decrypt-and-parse
   viewer and raw source exercised against real AES-256-GCM .eml.enc
   fixtures, soft-delete (folder detach to `original_folder_id`), restore
   (original / needs-destination 409 / chosen destination), permanent
   delete (row + file gone), flag set/clear + flagged list, move.*
4. **`api/imports.py`** — mount / unmount / browse imported folders & emails.
   *Done (`tests/test_api_imports.py`, 19 tests): mbox/eml scan + import
   validation, a real single-.eml import round-trip, import-email content
   and attachment read from a file on disk, and the unencrypted-ZIP folder
   export read back and verified to decrypt to the original bytes (incl.
   nested subfolders).*
5. **`api/accounts.py`** — CRUD + Gmail detection (the runtime `is_gmail`).
   *Done (`tests/test_api_accounts.py`, 23 tests): listing + the is_gmail
   detection (decrypts stored credentials, inspects host), create/update
   validation, no-password update path, test/emails guards, the
   cached-folder fast path that returns without IMAP, delete, and
   email-domain server detection. Live IMAP paths left out per Tier 4.*
6. **`api/commit.py` + `api/progress_commit.py`** — commit workflow and
   resume (pairs naturally with the `pending_commit` unit tests).
   *Done (`tests/test_commit.py`, 22 tests): unit tests for the pure
   helpers (archive-folder-from-path, duplicate detection, summary
   building, post-action key parsing, atomic save-to-archive incl.
   orphan-file cleanup on DB failure) + the SSE `/api/commit/stream`
   empty-payload guard and a full import round-trip (session create →
   walk → archive row + encrypted file → session cleared), no IMAP.*
7. **`api/threads.py`, `api/settings.py`** — smaller, quick.
   *Done (`tests/test_api_threads.py`, 6 tests: the request-validation
   boundary before any IMAP connect; `tests/test_api_settings.py`,
   14 tests: validated retention/timeout/thread-size endpoints with
   allow-list rejection, session-status incl. Never, keepalive, and the
   reset-database guards without running the destructive reset).*

### Tier 3 — pipelines (medium effort, fixture-heavy)

8. **`api/exports.py`** — scope resolution (`_resolve_message_ids` and
   friends), the job state machine, and an encrypted-ZIP round-trip (build,
   then read back with the export password via pyzipper). Needs a DB with
   sample messages plus real decryptable `.eml.enc` files on disk.
9. **`core/importer.py`** — mbox / EML using the existing `test_files/`
   samples. PST needs the `libpst` binary, so leave PST for last or skip.

### Tier 4 — high cost / low ROI (consider skipping)

10. **`core/imap.py`** — the pure helpers (credential load/save, folder-name
    parsing, sync-cache TTL) are cheap; the connect/fetch paths need heavy
    `imaplib` mocking or a throwaway server. High cost, catches little.
11. **`core/pdf_export.py`** — WeasyPrint is slow and rendering assertions
    are brittle.

---

## Rough sizing

- Tier 1 + Tier 2: ~3–4 working sessions. Front-loaded value — `pending_commit`
  + `auth` + the API blueprints cover most of the real protection.
- Tier 3: ~1 session, mostly fixture setup.
- Tier 4: ~2 sessions and the most likely to overrun; recommended skip.

The binding constraint is context-window length and review time, not raw
effort — so this proceeds module-by-module across sessions, each an
independent, committable win.
