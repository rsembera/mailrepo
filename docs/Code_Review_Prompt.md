# Code Review Prompt — for sending to a fresh model

This file is the prompt to paste into a fresh Claude conversation (or
any other capable model) when you want an outside-eyes code review.

> **CURRENT VERSION: v2**, near the bottom of this file — "Version 2 —
> pre-1.0-tag review, calibrated for Sessions 67–73". Scroll to it.
>
> **v1 below is HISTORICAL** and describes the codebase as it stood on
> May 31, 2026 (Sessions 36–38, v1→v2 crypto, 68 tests). It is kept for
> the record. Do not paste it — a reviewer given v1 today will start by
> reporting that the brief is stale, which is exactly what happened the
> first time v2 was used.

Version 1 was calibrated for the **pre-1.0-tag review** done at the end
of Session 38 (May 31, 2026). The surrounding framing — what counts as
critical, what to skip, output format — is deliberately reusable; the
"Recent work to scrutinize" section is what goes out of date.

---

## The prompt (v1 — HISTORICAL, superseded by v2 at the bottom of this file)

```
You're doing a pre-tag code review of MailRepo, a local-first encrypted email
archive application for solo practitioners. It's about to ship 1.0; the
author is dogfooding before `git tag v1.0.0` and wants a fresh pair of eyes
on three threads of work that landed in the last three days. I'd like you
to read the codebase and flag what's wrong, in priority order.

## Project context

- Repo: https://github.com/rsembera/mailrepo.git (AGPL-3.0)
- Stack: Flask + SQLCipher (Argon2id KDF + AES-256-GCM file encryption with
  HKDF-derived subkeys) + IMAP + FTS5. Vanilla JavaScript frontend, no
  build step.
- Size: ~38,200 lines across Python (~13k), JS (~16k), CSS (~7.5k), HTML.
- Read `docs/Navigation_Map.md` first for the layout, then `docs/Session_Log.md`
  Sessions 36–38 for what just shipped, then `docs/Post_1_0_Backlog.md` for
  what's still open.

## Recent work to scrutinize

1. **Crypto refactor (Session 36, May 29)**: v1 (Fernet + PBKDF2) → v2
   (Argon2id + AES-256-GCM + HKDF). Per-file version byte, two-phase
   migration. v1 code stripped May 30 after production migration on a
   1,648-file archive. Focus on `core/encryption.py`,
   `core/password_change.py`, `core/database.py`, `tests/test_encryption_v2.py`,
   `tests/test_password_change.py`.

2. **Frontend dispatch model unification (Sessions 37–38, May 30–31)**:
   Replaced every inline `onclick="..."` and every cross-module `window.X = X`
   global with `bindActions(container, handlers)` for view-scoped clicks
   plus a single `template-bindings.js` delegated handler on `document.body`
   for template-level actions. Eleven JS files converted plus the
   `index.html` template. Focus on `web/static/js/delegate.js`,
   `web/static/js/template-bindings.js`, `web/templates/main/index.html`,
   and the 11 view/component files listed in Session 38's commits.

3. **Smaller things**: `progress.py` split, password-change unit tests,
   external `.backup_state.json` (Libram-style), search view UX refactor
   (live search + asterisk prefix-matching), closeModal consolidation
   (`modals.js` canonical with a `registerModalCloseHandler` registry).

## What I specifically want you to look for

**Critical** (must fix before tag):

- **Missing-export-after-window-removal**: yesterday during the template
  conversion I removed `window.X = X` assignments but forgot to add
  `export` to five function declarations in `mail.js` and two in `vault.js`.
  ES module link failed silently at runtime (not at `node --check`),
  half-rendering the page. Audit every named import in
  `template-bindings.js` and every cross-module import in the
  views/components — does the source module actually export each name?
  If not, latent crash.

- **Crypto correctness**: Argon2id params (m=256 MiB, t=6, p=1). HKDF info
  string usage and domain separation. Nonce generation for AES-256-GCM
  (must be unique per encryption with the same key — a repeat is
  catastrophic for GCM). Salt file format. Anything that weakens the
  actual security properties claimed in the README/Navigation_Map.

- **SQL injection / parameterization**: every API endpoint in
  `web/blueprints/api/`. Anywhere a query string is built from user
  input.

- **Auth flow correctness**: `is_api_request()` in `web/app.py`. CSRF
  token validation. Session timeout. Anywhere a state-changing endpoint
  might bypass CSRF.

**Important** (should fix soon):

- **bindActions binding location**: the pattern is "bind on a view-
  specific child wrapper (e.g. `.starred-view-root`) so the listener
  dies with the view when innerHTML is replaced." Binding on a shared
  parent like `emailList` directly is a cross-talk bug. We hit this in
  Session 37 with starred/trash — verify it's not still latent anywhere.

- **template-bindings.js HANDLERS map completeness**: every
  `data-tpl-action="X"` in `web/templates/main/index.html` must map to
  a `HANDLERS[X]` entry. Missing entries log a console warning but the
  button silently does nothing.

- **closeModal registry leak risk**: `_modalCloseHandlers` Map in
  `modals.js` is never cleaned up. Probably fine for a single-page
  app, but flag if it would matter.

- **Backup state file**: `utils/backup.py` + `.backup_state.json`.
  Recovery from interrupted backups. mtime-based change detection —
  any false-negative or false-positive scenarios?

**Worth considering**:

- Test coverage gaps. 68 tests; what's notably missing?
- Error handling consistency across API endpoints.
- SSE stream lifecycle and cleanup.
- Anything that would surprise a maintainer reading the code cold.

**Please skip**:

- Vanilla JS vs framework, Flask + Jinja vs SPA. Intentional.
- Style/formatting preferences.
- "Could be refactored to X" without concrete reasoning.
- Micro-optimizations without a measured problem.

## Output format

For each finding:
1. **Severity**: critical / important / suggestion / nit
2. **Location**: file path + line number(s)
3. **Problem**: what's wrong, briefly
4. **Fix**: one or two sentences, or "needs design discussion" if bigger

Prioritize findings that would be embarrassing if a user discovered them.
Things that produce wrong answers, data loss, or security holes rank
above things that just look ugly.

If you find that a commit message claims X was done but the code still
has Y, flag it explicitly. The author is fallible and you should not
assume the docs are ground truth.
```

---

## Notes on calibration

- The "Critical / Important / Worth considering / Please skip" structure
  keeps the review from drowning in style debates the author already
  had with themselves.
- The "Please skip" section is load-bearing. Without it, reviewers tend
  to spend disproportionate effort on framework/style suggestions that
  are deliberate intentional choices.
- The "if a commit message claims X but the code has Y, flag it" line
  explicitly licenses the reviewer to not trust the docs. Important
  because the author wrote the docs and might have a blind spot.
- The bug-from-yesterday callout (missing-export-after-window-removal)
  primes the reviewer to look for the same failure mode elsewhere —
  the kind of mistake you only catch by knowing it's the kind of
  mistake you make.

## When to reuse

Before any release tag, before a major version bump, before publishing
a significant new feature to the website, or any time the author has
been working alone on the codebase for a stretch and wants a sanity
check.

---

## Version 2 — pre-1.0-tag review, calibrated for Sessions 67–73 (Aug 9–11, 2026)

Written at the end of Session 73. The v1 prompt above covered the crypto
v1→v2 refactor and the frontend dispatch unification; this one covers the
recovery-key / envelope-encryption work and the backup hardening that came
with it.

**Ordering matters.** The prompt deliberately asks the reviewer to read
code before docs. `Session_Log.md` entries were written to justify
decisions and are persuasive; a reviewer who reads them first is half
recruited to the author's position before forming a view.

```
You're doing a pre-tag review of MailRepo, a local-first encrypted email
archive for solo practitioners — lawyers, therapists, journalists holding
confidential correspondence. It is about to ship 1.0. I want an outside
read on three days of work that touched the encryption layer, the backup
system, and the account-recovery flow.

## Ground rules, please read these first

1. **Read the code before the prose.** Start with `docs/Navigation_Map.md`
   for layout only. Do NOT read `docs/Session_Log.md` until you have
   formed your own view of the code. Those entries are the author's
   justifications and they are persuasive; I want your reading, not your
   agreement with his.

2. **Treat the documentation as claims to verify, not as context.**
   `docs/Security_Audit.md` asserts specific runtime properties. Several
   are checkable. Check them.

3. **The author's known failure mode this week was asserting things about
   the running system that were only inferences from reading code.**
   Three examples he caught late: he reported a CSRF vulnerability that
   did not exist (missed a `window.fetch` interceptor in `base.html`
   because he grepped only `web/static/js/`); he stated a retention
   setting's value from the code default rather than the database; he
   described a sibling project's design from a one-line summary without
   reading it. So: any claim of the form "X happens at runtime" deserves
   independent verification, and absence of evidence in one directory is
   not evidence of absence.

4. **Weight the frontend heavily.** Every bug that reached the user this
   week was in the frontend or in the seams around the crypto, never in
   the crypto itself. No Python test executes any JavaScript. ESLint
   `no-undef` is the only automated frontend check that exists, and it
   found a shipping `ReferenceError` the first time it was run.

## Project context

- Repo: https://github.com/rsembera/mailrepo.git (AGPL-3.0)
- Flask + SQLCipher + IMAP + FTS5. Vanilla JS frontend, no build step.
- 518 Python tests. `ruff check .` clean. ESLint baseline: 0 errors,
  64 warnings (unused imports / unused catch bindings, left deliberately).
- Single-user, localhost-only, no reverse proxy.

## What landed, and what to scrutinize

**1. v3 envelope encryption (Sessions 68, 71–73).**
The master key became 32 random bytes wrapped twice — once under
Argon2id(password), once under HKDF(recovery key). Either unwraps the
same master; `file_key` and `db_key` derive from it exactly as before, so
archive ciphertext is unchanged and only the key file moved (MRC2 → MRC3,
fixed 190 bytes).

Files: `core/encryption.py`, `core/crypto_migration_v3.py`,
`core/password_change.py`, `tests/test_recovery_key.py`,
`tests/test_crypto_migration_v3.py`.

Specific things to check:
- The v2→v3 migration generates a *fresh random* master and re-encrypts,
  rather than reusing the password-derived value. The claim is that
  reusing it would leave the old password a permanent path to the master,
  so password change would stop truly revoking. Is that reasoning sound,
  and does the code actually do it?
- The migration persists its candidate master to `data/.v3_migration_state`,
  wrapped under the OLD file key, so an interrupted run can resume with
  the same master. Is that safe? What happens if that file survives into
  a state where it shouldn't?
- The key file is written LAST, after the DB rekey. Is the ordering
  actually crash-safe, or is there a window that loses the archive?
- Password change on v3 is a 61-byte rewrap with NO backup gate — the
  gate was deliberately removed on the grounds that the operation is a
  single atomic `os.replace`. Is that justified?

**2. Recovery key as password reset, not a credential (Session 72).**
`/auth/login/recovery` verifies a key, mints a server-side handoff token,
and redirects to a MANDATORY password reset. It grants no session. After
reset the user is deliberately NOT logged in.

Files: `web/blueprints/auth.py`, `web/app.py` (public endpoint list),
`web/templates/auth/`, `tests/test_recovery_key_web.py`.

- The reset route is unauthenticated by design. Its only gate is the
  handoff token (`secrets.token_urlsafe(32)`, 5-min TTL, single-entry
  dict, module-global). Is that sufficient? Consider replay, concurrent
  users, process restart, and whether "single entry" creates a denial
  path.
- There is no CSRF token on that form. The argument is that the handoff
  token serves the purpose since a forgot-password user has no session.
  Is that right?
- A malformed key deliberately does NOT consume a rate-limit attempt,
  only a well-formed wrong one does. Is that exploitable?
- `Encryption.verify_recovery_key()` unwraps and discards the master.
  Confirm nothing is left in class state.

**3. Backup hardening (Sessions 67, 69).**
The password-change gate now verifies the newest restore chain on disk —
opens every zip, runs `testzip()` — rather than trusting `manifest.json`.
Restore points are annotated with which credentials they need, by
comparing SHA-256 prefixes of the two key-file wrapper halves.

Files: `utils/backup.py`, `tests/test_restore.py`, `tests/test_backup.py`.

- `read_key_file_from_chain()` returns the key file from the LAST backup
  in the chain that contains one, because incrementals only carry changed
  files. Is that the right rule in every case?
- Retention cleanup runs on both the manual and automatic backup paths as
  of Session 69. Verify it cannot delete the only usable restore point.
- The author decided NOT to re-encrypt existing backups on credential
  rotation. Reasoning is in `Security_Audit.md`. Is the conclusion right,
  and is the residual risk stated accurately?

## Claims to verify against the code

These are asserted in `docs/Security_Audit.md`. Confirm or refute each:

- The recovery key never enters the Flask session or any cookie.
- The recovery key is never written to disk in plaintext.
- Rotating the recovery key revokes the old one immediately.
- Changing the password leaves the recovery key working, and vice versa.
- An unlocked session alone cannot mint a new recovery key.
- Verification changes nothing — no password, no rotation, no unlock.
- A v2 (pre-recovery-key) archive refuses recovery-key operations with a
  specific reason rather than a generic failure.

## Where coverage is thin, by admission

- No test executes any JavaScript. The frontend's only automated check is
  ESLint `no-undef`.
- `authenticated_client` in `tests/conftest.py` injects CSRF headers, so
  no test using it can observe a missing token.
- The UI screens added this week were verified by a human clicking
  through once, not by anything repeatable.

## Please skip

- Vanilla JS vs a framework; Flask + Jinja vs SPA. Intentional.
- Style and formatting.
- "Could be refactored to X" without concrete reasoning.
- Micro-optimizations with no measured problem.
- The 64 ESLint warnings — deliberately left so new errors stay visible.

## Output format

For each finding:
1. **Severity**: critical / important / suggestion / nit
2. **Location**: file path + line numbers
3. **Problem**: what's wrong
4. **Fix**: a sentence or two, or "needs design discussion"

Rank by what would be worst if a user hit it. Data loss and lockout rank
above everything: this application's core promise is that a solo
practitioner's confidential correspondence stays both private and
recoverable. A bug that loses an archive is worse than one that exposes
a bad error message.

If a commit message or a doc claims X and the code does Y, say so
explicitly. The author is fallible and the docs are not ground truth.
```
