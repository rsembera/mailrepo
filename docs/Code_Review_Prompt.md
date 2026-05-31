# Code Review Prompt — for sending to a fresh model

This file is the prompt to paste into a fresh Claude conversation (or
any other capable model) when you want an outside-eyes code review.

The current version below is calibrated for the **pre-1.0-tag review**
done at the end of Session 38 (May 31, 2026). If you reuse this for a
later review (e.g. before tagging 1.1), update the "Recent work to
scrutinize" section to point at the new work, but the surrounding
framing — what counts as critical, what to skip, output format — is
deliberately reusable.

---

## The prompt

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
