# Implementation Plan: Provider-Aware Permanent Delete for Gmail

**Status:** Ready to implement (pre-release; no version gate)
**Effort:** ~1 day across two commits, plus live-Gmail dogfooding (manual, Rick-only)
**Revision:** Rewritten after source review. Supersedes the original draft.

---

## Background

MailRepo's current "Delete" post-commit action uses standard IMAP semantics:
`UID STORE +FLAGS (\Deleted)` followed by `EXPUNGE`. This is RFC-correct and
works on every standards-compliant IMAP server (Fastmail, Dovecot, Cyrus,
hosted providers, etc.).

Gmail is non-standard. In Gmail's IMAP implementation folders are labels, and
`STORE +FLAGS (\Deleted)` + `EXPUNGE` in a regular folder removes only the
*label* for the selected folder; the message itself persists in the implicit
"All Mail" view. The exceptions are `[Gmail]/Trash` and `[Gmail]/Spam`, where
Gmail honours standard IMAP delete semantics and actually removes the message.

Because of this, the UI currently hides the Delete option for Gmail accounts
(`web/static/js/views/review.js:651-668`). This plan re-enables it with a
Gmail-aware path that behaves as users expect.

---

## What changed in this revision

The work is split into two commits, and the shared `move_email()` primitive is
hardened rather than worked around:

1. **Commit 1 — `move_email()` hardening (provider-agnostic).** Upgrade to IMAP
   MOVE (RFC 6851) with COPY fallback, capability-gated UID-scoped EXPUNGE
   (RFC 4315 / UIDPLUS), and return the destination UID. Benefits the existing
   Archive and Trash actions too, so it ships with its own regression coverage.
2. **Commit 2 — Gmail delete path.** `delete_email_via_trash()` built on the
   hardened primitive, with an in-place short-circuit for messages already in
   Trash/Spam, plus dispatch routing and the UI re-enable.

Three correctness issues found during source review are addressed:

- **Loop selection.** The post-commit dispatch (`commit.py:461`) calls
  `select_folder(source_folder)` *once*, then iterates UIDs. The Gmail path
  changes the selected folder as a side effect (it has to, to expunge in
  Trash), so from the second UID onward the move would run against the wrong
  folder. Fix: re-select the source folder per iteration.
- **New-UID discovery.** Uses COPYUID from the MOVE/COPY response, not a
  Message-ID search (fragile under duplicate IDs / races). Search is a
  documented fallback only.
- **Over-broad expunge.** The current `move_email()` uses a bare `expunge()`
  that sweeps every `\Deleted` message in the folder. Scope it to the target
  UID where the server supports UIDPLUS.

---

## Goal

Provide an immediate permanent-delete post-commit action that works correctly
on Gmail, with no UI difference beyond the Delete option becoming available.

## Non-goals

- Do **not** change `delete_email()`'s behaviour on non-Gmail accounts.
- Do **not** introduce a Gmail-specific UI affordance; only routing changes.
- Do **not** depend on Gmail's `X-GM-LABELS` extension. The portable
  MOVE + standard-delete pattern is preferred.

---

## Commit 1 — Harden `core/imap.py::move_email`

Current implementation (line ~1045) does COPY + STORE `\Deleted` + bare
`expunge()`, returns `bool`, and discards the COPY response (which carries
COPYUID). Three changes:

**1. Return the destination UID.** Change the signature from `-> bool` to
`-> Optional[str]` (the new UID in the destination folder, or `None` if the
server reported no COPYUID — which is *not* a failure; failures raise). Update
the two internal callers to report a plain bool by success-not-raising, NOT by
`is not None` (a successful move on a non-UIDPLUS server returns `None`):

```python
def archive_email(self, uid: str) -> bool:
    ...
    self.move_email(uid, archive_folder)   # raises on failure
    return True

def trash_email(self, uid: str) -> bool:
    ...
    self.move_email(uid, trash_folder)
    return True
```

**2. Prefer IMAP MOVE (RFC 6851), fall back to COPY.** MOVE is atomic and
removes the source/expunge race. Gate on the `MOVE` capability:

```python
def move_email(self, uid: str, destination_folder: str) -> Optional[str]:
    if not self.connection:
        raise IMAPError("Not connected")
    dest = f'"{destination_folder}"'
    try:
        if self._has_capability("MOVE"):
            status, data = self.connection.uid("MOVE", uid, dest)
            if status != "OK":
                raise IMAPError(f"MOVE of {uid} to {destination_folder} failed")
            return self._parse_copyuid(data)
        # Fallback: COPY + STORE \Deleted + scoped EXPUNGE
        status, data = self.connection.uid("COPY", uid, dest)
        if status != "OK":
            raise IMAPError(f"COPY of {uid} to {destination_folder} failed")
        new_uid = self._parse_copyuid(data)
        self.connection.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
        self._expunge_uid(uid)
        return new_uid
    except Exception as e:
        raise IMAPError(f"Failed to move message {uid}: {e}")
```

**3. New private helpers.**

```python
def _has_capability(self, name: str) -> bool:
    """True if the server advertised the given IMAP capability."""
    try:
        status, data = self.connection.capability()
        if status != "OK" or not data:
            return False
        caps = data[0].decode("ascii", "ignore").upper().split()
        return name.upper() in caps
    except Exception:
        return False

def _parse_copyuid(self, data) -> Optional[str]:
    """Extract the destination UID from a COPYUID response code.
    Returns None if absent (server lacks UIDPLUS); caller may fall back
    to a Message-ID search in the destination folder."""
    # COPYUID <uidvalidity> <src-uid-set> <dst-uid-set>
    # Search both the returned data and untagged_responses for the code.
    ...

def _expunge_uid(self, uid: str) -> None:
    """UID-scoped expunge when UIDPLUS is available, else bare expunge."""
    if self._has_capability("UIDPLUS"):
        self.connection.uid("EXPUNGE", uid)
    else:
        self.connection.expunge()
```

Notes for the implementer:
- `_parse_copyuid` regex: `\[COPYUID\s+\d+\s+\S+\s+(\d+)\]` against the decoded
  response text. imaplib surfaces the code in the tagged completion line; check
  `connection.untagged_responses` as well.
- Capability results could be cached on the client after first fetch; not
  required for correctness.
- `_expunge_uid`'s bare-expunge branch preserves today's behaviour exactly for
  servers without UIDPLUS, so the fallback path is a no-regression change.

### Commit 1 tests (`tests/test_imap.py`)

- `test_move_email_uses_move_when_capable` — MOVE issued, COPYUID parsed and
  returned.
- `test_move_email_falls_back_to_copy` — no MOVE cap → COPY + STORE + expunge.
- `test_move_email_uid_scoped_expunge_with_uidplus` — `UID EXPUNGE` issued.
- `test_move_email_bare_expunge_without_uidplus` — bare `expunge()` issued
  (regression lock for old servers).
- `test_archive_email_still_returns_bool` / `test_trash_email_still_returns_bool`
  — call-site coercion regression.

---

## Commit 2 — Gmail delete path

### `core/imap.py::delete_email_via_trash`

```python
def delete_email_via_trash(self, uid: str, source_folder: str) -> bool:
    """
    Permanently delete on Gmail. If the message already lives in a folder
    where Gmail honours real delete (Trash or Spam), delete it in place.
    Otherwise move it to Trash, then expunge it there.

    Caller contract: source_folder is currently SELECTed. This method may
    change the selected folder; callers iterating multiple UIDs must
    re-SELECT the source folder per iteration (see dispatch below).

    Returns True on permanent deletion. Also returns True (with a logged
    warning) if the message reached Trash but the second-stage expunge
    failed — Gmail auto-purges Trash within 30 days, satisfying intent.
    """
    trash = self.get_special_folder("trash")
    spam = self.get_special_folder("spam")   # NOTE: add a "spam" type to
                                              # get_special_folder (it only
                                              # knows archive/trash/sent today;
                                              # candidates: "[Gmail]/Spam",
                                              # "Spam", "Junk", "Junk E-mail").

    # In-place: already in a folder where \Deleted + EXPUNGE truly deletes.
    if source_folder in (trash, spam):
        self.connection.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
        self._expunge_uid(uid)
        return True

    # Move to Trash, then expunge there.
    new_uid = self.move_email(uid, trash)   # raises IMAPError on move failure
    if new_uid is None:
        # COPYUID unavailable; fall back to Message-ID search in Trash.
        new_uid = self._find_uid_in_folder_by_message_id(trash, original_message_id)
    try:
        self.select_folder(trash)
        self.connection.uid("STORE", new_uid, "+FLAGS", "(\\Deleted)")
        self._expunge_uid(new_uid)
        return True
    except Exception as e:
        log.warning("Gmail delete: reached Trash but expunge failed for "
                    "uid=%s (%s); Gmail will auto-purge in ~30 days", uid, e)
        return True
```

(`log` is the module logger in `core/imap.py`, via `get_logger()`.)

The Message-ID fallback needs the source message's Message-ID captured before
the move (it is already available in the committed-email record). If neither
COPYUID nor a unique Message-ID match is available, log a warning and return
`True` (message is in Trash, will auto-purge).

### `web/blueprints/api/commit.py` — dispatch routing + per-iteration re-select

In `apply_post_commit_actions` (loop ~line 461), the source folder is selected
once before the UID loop. The Gmail delete path mutates the selected folder, so
re-select inside the loop:

```python
client.select_folder(source_folder)
for uid, dest_folder_id in email_list:
    try:
        if action == "delete" and is_gmail:
            client.select_folder(source_folder)   # restore per iteration
            client.delete_email_via_trash(uid, source_folder)
            results["post_actions"]["success"] += 1
        elif action == "delete":
            client.delete_email(uid)
            results["post_actions"]["success"] += 1
        elif action == "archive":
            client.archive_email(uid)
            results["post_actions"]["success"] += 1
        elif action == "trash":
            client.trash_email(uid)
            results["post_actions"]["success"] += 1
    except IMAPError:
        results["post_actions"]["failed"] += 1
```

`is_gmail` should come from a small, testable helper that inspects the
decrypted IMAP host (`imap.gmail.com`, which also covers Workspace custom
domains). Factor the existing check in `accounts.py:51-58` into
`core/account_utils.py::is_gmail_host(host)` and reuse it both places.

### `web/static/js/views/review.js` — re-enable Delete

Replace the Gmail exclusion block (lines 651-668):

```javascript
options.push({ value: 'delete', label: 'Delete emails' });
```

Drop the `isGmail && selectedValue === 'delete'` fallback and the
`isGmail` parameter if it is now unused elsewhere in the function.

---

## Failure modes

| Source location | Move step | Expunge step | Outcome | Treatment |
|---|---|---|---|---|
| Trash / Spam | (skipped) | Success | Permanently deleted | success |
| Trash / Spam | (skipped) | Failure | Still in Trash/Spam | failure (existing path) |
| Other folder | Success | Success | Permanently deleted | success |
| Other folder | Success | Failure | In Trash, auto-purges ~30d | **success + logged warning** |
| Other folder | Failure | n/a | Untouched in source | failure |

With IMAP MOVE the move step is atomic, so the "move partially succeeded"
ambiguity from the old COPY+EXPUNGE primitive is gone on MOVE-capable servers
(Gmail qualifies). On COPY-fallback servers, COPYUID capture confirms whether
the copy landed before the source expunge runs.

---

## Commit 2 tests

`tests/test_imap.py`:
- `test_delete_via_trash_happy_path` — moved to Trash then expunged.
- `test_delete_via_trash_in_place_when_source_is_trash` — no move; direct
  STORE + expunge.
- `test_delete_via_trash_in_place_when_source_is_spam` — same for Spam.
- `test_delete_via_trash_move_fails` — IMAPError propagates; source untouched.
- `test_delete_via_trash_expunge_fails_after_move` — returns True, warning
  logged.
- `test_delete_via_trash_uses_copyuid` — new UID from COPYUID, no search.
- `test_delete_via_trash_falls_back_to_message_id_search` — COPYUID absent.

`tests/test_commit.py` (or a mocked-dispatch test alongside `test_imap.py`;
note `test_commit.py` today is pure-DB with no IMAP — the dispatch test needs
a mocked IMAP client):
- `test_post_commit_delete_routes_via_trash_for_gmail`.
- `test_post_commit_delete_uses_standard_delete_for_non_gmail` (regression).
- **`test_post_commit_delete_reselects_source_per_iteration`** — the important
  one: dispatch over **2+ Gmail UIDs**, asserting `select_folder(source)` is
  called before each `delete_email_via_trash`. This is the test that catches
  the loop-selection bug; single-call tests do not.

`tests/test_account_utils.py`:
- `test_is_gmail_host` — gmail.com host true; others false.

---

## Manual verification (dogfooding, Rick-only — cannot be automated)

Required before the feature is considered done:

1. Stage a few emails from a Gmail Inbox; choose Delete as the post-commit
   action; commit. In the Gmail web UI confirm they are gone from Inbox **and**
   All Mail (briefly visible in Trash, then expunged).
2. Repeat with emails whose source folder *is* `[Gmail]/Trash` — confirm the
   in-place path deletes without an intermediate move.
3. Repeat with a multi-email selection (≥3) from the same Inbox in one commit —
   confirm **all** are deleted, not just the first. (Guards the loop-selection
   fix in production.)
4. Sanity-check a non-Gmail account (Fastmail/Dovecot) still deletes correctly —
   confirms Commit 1 didn't regress the standard path.

---

## Resolved decisions (was "open questions")

1. **IMAP MOVE:** adopted in Commit 1, with COPY fallback. Atomic; tightens
   failure semantics; benefits Archive/Trash too.
2. **Module location:** stays in `core/imap.py`. Only one provider quirk; a
   separate module is premature.
3. **`is_gmail` helper:** factored into `core/account_utils.py::is_gmail_host`,
   reused by `accounts.py` and `commit.py`.
4. **UID discovery:** COPYUID primary, Message-ID search fallback.
5. **UID-scoped expunge:** adopted, capability-gated on UIDPLUS.
6. **Trash/Spam as source:** handled by the in-place short-circuit.

---

## Docs updates required

- `Session_Log.md` — entries for both commits (standing rule).
- `CHANGELOG.md` — Added: Gmail permanent-delete post-commit action;
  Changed: `move_email` now uses IMAP MOVE + UID-scoped expunge where
  supported.
- `Navigation_Map.md` — note `core/account_utils.py` if newly created.

## Out of scope

- Generalising label-based-provider handling beyond Gmail.
- Batching the two-step delete across many UIDs in one round-trip pair —
  per-message overhead is two short commands; fine for typical commit sizes.
