# MailRepo — Test Coverage Plan

Created May 31, 2026 (Session 39). Tracks the post-1.0 effort to fill the
test-coverage gap surfaced in the pre-tag code review
(`docs/Code_Review_Findings.md` #5).

**Current suite:** 85 tests (encryption, password change, backup, database,
threading, email parser, API folders).

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
   token verification. This is the security boundary and currently has
   zero automated coverage. *Elevated to Tier 1 per Opus 4.7's suggestion —
   higher ROI than the generic API blueprints below.*
   - Test notes: exercise the rate-limit *lockout trigger* (5 failures →
     blocked) without waiting out the 60s window; don't test the time-based
     reset unless `time` is mocked. For CSRF, use the raw test client (not
     the `authenticated_client` wrapper, which auto-adds the header):
     POST without `X-CSRF-Token` → 403, with the right token → passes.

### Tier 2 — user-facing API surface (high value, low effort)

The Flask test-client scaffolding already exists — `tests/test_api_folders.py`
is a working template and `conftest.py` provides `initialized_app` and
`authenticated_client`. Each blueprint is a short sitting.

3. **`api/emails.py`** — view / move / soft-delete / restore / batch select.
4. **`api/imports.py`** — mount / unmount / browse imported folders & emails.
5. **`api/accounts.py`** — CRUD + Gmail detection (the runtime `is_gmail`).
6. **`api/commit.py` + `api/progress_commit.py`** — commit workflow and
   resume (pairs naturally with the `pending_commit` unit tests).
7. **`api/threads.py`, `api/settings.py`** — smaller, quick.

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
