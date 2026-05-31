# MailRepo — Code Review Findings

**Review date:** May 31, 2026 (pre-`v1.0.0`-tag, end of Session 38)
**Scope:** The three threads in `docs/Code_Review_Prompt.md` — crypto refactor
(Session 36), frontend dispatch unification (Sessions 37–38), and the
smaller items — plus the prompt's critical/important/worth-considering list.
**Method:** Static read of the codebase + full test-suite run (68/68 green).

Severity legend: **critical** (fix before tag) / **important** (fix soon) /
**suggestion** / **nit**.

---

## Summary

No critical findings. The two flagged-hardest threads — the
missing-export audit and crypto correctness — came back clean. One
**important** finding (master password transiting a client-side session
cookie). The rest are suggestions and doc drift.

| # | Severity | Area | One-line |
|---|----------|------|----------|
| 1 | important | auth | Master passwords stored in default client-side session cookie |
| 2 | suggestion | backup | `_write_backup_state` / `save_manifest` are non-atomic |
| 3 | suggestion | api | No JSON 500 safety net (uncaught exc → HTML) |
| 4 | suggestion | frontend | Two modal pickers accumulate listeners on reopen |
| 5 | suggestion | tests | No coverage for backup / pending_commit / exports |
| 6 | nit | auth/sse | `export_progress` SSE absent from `streaming_endpoints` |
| 7 | nit | docs | Navigation_Map schema block is stale |
| 8 | nit | docs | Navigation_Map mislabels `test_encryption.py` as v1 |
| 9 | nit | api | Bare `except:` in `accounts.py` |

---

## Important

### 1. Master passwords transit a client-side session cookie
- **Location:** `web/blueprints/auth.py` ~344–346 (store) and
  `change_password_progress` ~351+ (consume); `core/config.py:102+`
  (`FlaskConfig` — no server-side session backend).
- **Problem:** The password-change flow verifies the current password,
  then writes *both* the current and new master password into
  `session["password_change_current"]` / `["password_change_new"]` so the
  SSE endpoint can pick them up. There is no server-side session store
  (no Flask-Session, no `SESSION_TYPE`), so Flask uses its **default
  signed-cookie session**. That session is *signed, not encrypted* — its
  contents are base64-encoded and readable by anyone holding the cookie.
  The `Set-Cookie` from the POST response ships both plaintext passwords
  to the browser, where they sit in the cookie jar until the SSE request
  pops them. `HttpOnly`/`SameSite=Lax` are set and traffic is loopback,
  so remote exploitation isn't the concern — but a master password
  base64'd in a browser cookie is exactly the posture this app's audience
  (lawyers/therapists/journalists who chose it *for* the crypto) would be
  alarmed to discover, and it's avoidable.
- **Fix:** Reuse the pattern `exports.py` already implements — the POST
  endpoint creates an opaque `job_id`, holds the passwords in a
  server-side in-memory dict keyed by that id (never in the
  session/cookie), starts the worker, and returns the id; the SSE
  endpoint streams by `job_id` and the entry is cleared on completion.
  Alternatively add a filesystem-backed server-side session. The job-id
  route is lighter and consistent with the export pipeline.

---

## Suggestions

### 2. Backup state writes are non-atomic
- **Location:** `utils/backup.py:237` (`_write_backup_state`), `:205`
  (`save_manifest`).
- **Problem:** Both do `open(path,'w')` + `json.dump`. A crash mid-write
  truncates the file. This is inconsistent with the careful atomic write
  in `core/encryption.py` (`_atomic_write_salt_file`: temp + fsync +
  `os.replace` + dir fsync). The failure mode is *safe* —
  `_read_backup_state` swallows `JSONDecodeError`/`OSError` and returns
  `{}`, which forces a full re-hash + backup that re-establishes a clean
  baseline — so this is hygiene, not a data-loss risk.
- **Fix:** Factor the salt file's atomic-write helper into a shared util
  and use it here too.

### 3. No JSON 500 safety net for the API
- **Location:** `web/app.py` (no `errorhandler` registered anywhere).
- **Problem:** The API is otherwise very consistent (184 structured
  `jsonify({"error":...})` returns). But an *uncaught* exception in any
  `/api/` endpoint falls through to Flask's default 500, which is HTML —
  breaking the JSON contract the frontend's fetch handlers expect. The 3
  bare top-level `raise`s are mostly contained (`exports.py:167` is caught
  by the job's `except`→`_fail_job`; `commit.py:129` is a deliberate
  re-raise), but any future bug has the same exposure.
- **Fix:** Register a blueprint/app error handler that returns
  `jsonify({"error": ...}), 500` for API paths (mirror the `is_api_request`
  logic) so the JSON contract holds even on unexpected errors.

### 4. Two modal pickers accumulate listeners on reopen
- **Location:** `web/static/js/components/move-email-modal.js:77`
  (`moveEmailFolderList`); `web/static/js/views/vault.js:632`
  (`restoreDestinationList`).
- **Problem:** Both call `bindActions` on a *persistent* element each time
  the modal opens, with no teardown, so click listeners stack across
  reopens. Benign today — both handlers are idempotent selection-state
  setters, and neither element is shared *across views*, so this is **not**
  the Session-37 cross-talk bug (that bug is confirmed not latent: every
  view binds on a fresh `.X-view-root` child). It's a latent footgun if a
  future handler isn't idempotent.
- **Fix:** Bind once at init, or render+bind a fresh child element like the
  view-root pattern does.

### 5. Test-coverage gaps in data-integrity-critical modules
- **Location:** `tests/` — no test files for `utils/backup.py`,
  `core/pending_commit.py`, `web/blueprints/api/exports.py` (also
  imap/importer/pdf_export/sync_cache, but those are harder to unit-test).
- **Problem:** The backup change-detection logic and commit-resume logic
  are exactly the subtle, interruption-sensitive code paths most worth
  guarding, and they have zero tests. (The logic itself reads correct —
  see "Verified clean" below — but a regression would be silent.)
- **Fix (priority order):** `backup.py` first — cover `has_file_changes`
  (new/deleted/modified), the WAL-style "mtime changed, content identical →
  no spurious backup + baseline refresh" path, and the
  zip-then-baseline ordering. Then `pending_commit` resume, then the
  export scope-resolution + job lifecycle.

---

## Nits / doc drift

### 6. `export_progress` SSE not in `streaming_endpoints`
- **Location:** `web/app.py` (`streaming_endpoints` set) vs
  `web/blueprints/api/exports.py:808` (`export_progress`).
- **Problem:** The timeout-skip set lists only `api.stream_account_emails`
  and `api.stream_commit`. `export_progress` runs the full session-timeout
  check at stream start. Impact is bounded: the export work runs in a
  detached daemon thread, the generator self-caps at 5 min (< 30-min
  default timeout), and `before_request` runs only once per request.
- **Fix:** None strictly needed — excluding it is defensible (an
  already-expired session arguably shouldn't open a fresh export stream).
  If you want consistency, add `api.export_progress` to the set or drop a
  comment noting the intentional exclusion.

### 7. Navigation_Map schema block is stale
- **Location:** `docs/Navigation_Map.md` "Database Schema (v5)" vs
  `core/database.py` `SCHEMA_SQL`.
- **Problem:** Lists `accounts.server`, `accounts.port`, `accounts.is_gmail`,
  and `folders.original_parent_id` as columns — none exist. `server`/`port`
  live in the `credentials_encrypted` JSON; `is_gmail` is derived at runtime
  from the creds host (`accounts.py:48–57`); `original_parent_id` is
  unreferenced anywhere. It also omits the real `folders.retention_days` and
  `messages.original_folder_id`. No functional impact — the code and
  `SCHEMA_SQL` agree; only the doc is wrong.
- **Fix:** Regenerate the schema block from `SCHEMA_SQL`.

### 8. Navigation_Map mislabels `test_encryption.py`
- **Location:** `docs/Navigation_Map.md` test table.
- **Problem:** Calls it "v1 encryption (preserved for migration test
  reference)". It actually tests the current v2 `Encryption` lifecycle
  (`initialize`/`unlock`/`lock`/wrong-password), overlapping
  `test_encryption_v2.py`. There is no v1 code left for it to test.
- **Fix:** Relabel (and optionally fold the overlap into
  `test_encryption_v2.py`).

### 9. Bare `except:` in accounts.py
- **Location:** `web/blueprints/api/accounts.py:56`.
- **Problem:** Bare `except:` also swallows `KeyboardInterrupt`/`SystemExit`.
- **Fix:** `except Exception:`.

(Also minor: folder `color` is stored unvalidated in `folders.py:134`.
Irrelevant under the single-user threat model unless it's ever
interpolated into a style attribute on render — worth a one-line check of
the swatch render path, then ignore.)

---

## Verified clean (checked, no action needed)

- **Missing-export audit** (the Session-38 failure mode): all named
  imports across the 29 JS files resolve to real `export`s, including the
  five viewer functions that broke yesterday. The one tool-flagged hit was
  a JSDoc usage example in `delegate.js:25`.
- **`template-bindings` HANDLERS completeness:** all 25 `data-tpl-action`
  values resolve; `handleLogout` is registered unconditionally at init via
  `registerHandler` (aliased `registerTemplateHandler`) in `app.js:189`.
- **Crypto construction:** Argon2id (m=256 MiB, t=6, p=1) above OWASP
  minimums; HKDF-Expand on the high-entropy master with domain-separated
  info strings is correct (Extract unnecessary for uniform IKM); random
  96-bit nonce per call is safe at archive scale; version byte bound into
  GCM AAD. **SQLCipher key** passed as `PRAGMA key = "x'<64-hex>'"` — the
  raw-key form, so the HKDF subkey is used directly with no double-KDF.
- **SQL injection:** every dynamic query uses count-derived `?`
  placeholders with bound params; `UPDATE ... SET` is hard-coded column
  fragments; FTS5 search binds the query as `MATCH ?`. No user data reaches
  SQL as raw text.
- **Auth/CSRF shape:** constant-time CSRF compare; JSON-401 vs redirect
  correctly split by `is_api_request()`; stale-unlock re-check clears the
  session; password-change passwords are *not* in the URL (POST body →
  session → SSE) and the state-changing POST is CSRF-protected. (The
  cookie-storage concern is finding #1, separate from the flow's shape.)
- **bindActions cross-talk:** not latent — all view bindings use a fresh
  `.X-view-root` child that dies with the view's innerHTML swap.
- **closeModal registry:** bounded — `registerModalCloseHandler` is called
  once, the `Map` is keyed by `modalId` (overwrite, not grow); one entry
  for the app lifetime.
- **Backup change-detection + recovery:** WAL-induced mtime bumps do not
  produce spurious backups (hash check finds no content change → baseline
  refreshed, returns `None`); baseline is saved *after* zip write +
  `verify_backup` + manifest, so an interrupted backup re-captures on the
  next run (redundant at worst, never a coverage gap).
- **SSE lifecycle:** all three generators have `except` + `finally`
  cleanup; export jobs have a GC (`_gc_jobs`) and a 5-min idle cap.
- **Test suite:** 68/68 pass (71s) on Python 3.14.5.

---

## Resolution — May 31, 2026 (same session)

All nine findings plus the folder-color aside were addressed in this
session. Full test suite green at **85 passed** (was 68; +17 backup tests).

| # | Status | What changed |
|---|--------|--------------|
| 1 | fixed | Password-change flow moved to a server-side one-time job id (`auth.py`); passwords never enter the session cookie. Frontend passes the id to the SSE endpoint (`settings.js`). |
| 2 | fixed | Added `_atomic_write_text` (temp + fsync + os.replace + dir-fsync); `save_manifest` and `_write_backup_state` route through it (`backup.py`). |
| 3 | fixed | `@app.errorhandler(Exception)` returns JSON on `/api/` paths, leaves non-API routes and the debugger untouched (`app.py`). |
| 4 | fixed | `dataset.actionsBound` guard so the two persistent modal pickers bind exactly once (`move-email-modal.js`, `vault.js`). |
| 5 | fixed | `tests/test_backup.py` — 17 tests: state-file round-trip + corruption degrade, the two-layer change detector, the WAL-checkpoint no-spurious-backup case, and the interrupted-backup baseline-safety invariant. |
| 6 | documented | Comment in `app.py` recording the intentional exclusion of `export_progress` from the timeout-skip set. |
| 7 | fixed | Navigation_Map schema block regenerated from `SCHEMA_SQL` (also corrected `pending_commit.batch_id` and `email_cache.uid_data`, which were likewise wrong). |
| 8 | fixed | Navigation_Map test-table label for `test_encryption.py` corrected to "v2 lifecycle". |
| 9 | fixed | `accounts.py` bare `except:` → `except Exception:`. |
| aside | fixed | Folder color validated server-side (null or `#rgb`/`#rrggbb`) in the folder-update endpoint, since it lands in a `style` attribute (`folders.py`). |

**Reviewer note left for the author:** the password-change refactor is the
one change worth a manual end-to-end test — change the master password once
and confirm the progress stream completes — because it touches the
re-encryption path and that can't be fully exercised by the unit suite.
