# MailRepo — Security Review, September 2026

**Date:** September 3, 2026
**Reviewer:** Claude (Fable 5.1)
**Scope:** Full source tree as of the working copy on this date (post-1.0.0). Security and safety only; code quality was out of scope.
**Method:** Three parallel read-throughs (web layer and rendering; cryptography and auth; parsing, IMAP, backups, packaging), followed by independent re-verification of every finding rated Medium or above against the code, and against the installed behaviour of WeasyPrint 69.0 where the finding depended on it. Claims in `docs/Security_Audit.md` were treated as hypotheses to check, not as established.

## Threat model used

MailRepo is a local, single-user desktop app (pywebview + waitress on 127.0.0.1) and is not meant to be exposed to a network. So the attackers that matter are, in rough order of realism:

1. **Hostile email content** arriving over IMAP or in an imported mbox/eml/pst. This is the one every user faces daily, and it is the one an encrypted-at-rest design does nothing about once the archive is unlocked.
2. **A malicious or compromised IMAP server**, which controls folder names, UIDs, and message bodies.
3. **Someone with a copy of the data directory or a backup** — a cloud sync folder, a Time Machine drive, a stolen laptop.
4. **Another process or browser tab on the same machine** reaching the local port.
5. **A hostile or tampered backup** offered for restore.
6. **Brief physical access** to a machine where MailRepo was left open.

Anything that requires the app to be reachable from another host is out of scope.

## Headline

The cryptographic core is in good shape and I would not change its design. Key file layout, Argon2id parameters, HKDF domain separation, per-call random GCM nonces, atomic key-file rewrites, the recovery-key handoff flow, the hard fail when SQLCipher is missing, and the no-plaintext-fallback for the database all checked out line by line. The email-body iframe is correctly sandboxed (no `allow-scripts`), remote content is blocked by default, Jinja autoescaping is on with no `|safe` anywhere, all SQL is parameterized, IMAP TLS uses `ssl.create_default_context()` with no way to turn verification off, and nothing sensitive is written to a log file.

The problems are almost all at the edges, where untrusted content meets the parts of the app that were built for the user's own data. Six findings deserve fixing before the next release; the first two are the ones I would fix this week.

| # | Severity | Finding | Where |
|---|---|---|---|
| 1 | High | Server-side idle timeout never fires; "Session Timed Out" screen leaves the archive unlocked | `web/app.py`, `base.html`, `settings.py` |
| 2 | High | HTML/SVG attachments served inline, same-origin, with the email's own Content-Type (browser mode) | `emails.py`, `accounts.py`, `imports.py`, `mail.js` |
| 3 | High | "Load remote images" PDF export lets an email embed local files into the PDF via WeasyPrint's default fetcher | `core/pdf_export.py` |
| 4 | High | Restore trusts `deleted_files` from the backup's metadata: path traversal → arbitrary file deletion | `utils/backup.py` |
| 5 | Medium | `escapeHtml()` does not escape quotes; used in attribute context with IMAP/mbox folder names | `utils.js` and callers |
| 6 | Medium | `post_backup_command` is arbitrary shell, settable with a CSRF token alone — turns any XSS into code execution | `backups.py`, `utils/__init__.py` |
| 7 | Medium | Folder-level post-commit action deletes every message in the IMAP folder, including ones that failed to archive | `progress_commit.py` |
| 8 | Medium | Password/recovery-key rotation does not revoke against anyone holding an older key file | `core/encryption.py` |
| 9 | Medium | No STARTTLS; unticking "Use SSL/TLS" sends the IMAP password in cleartext | `core/imap.py` |
| 10 | Medium | Port squatting in the desktop launcher; webview cannot verify it is talking to MailRepo | `launcher.py` |
| 11 | Medium | Flask `SECRET_KEY` is copied into every backup and restored with loose permissions | `utils/backup.py` |
| 12 | Low | `/api/filesystem/*` reads anywhere the user can — defines the blast radius of any XSS | `filesystem.py` |
| 13 | Low | PST import leaves a plaintext mbox in `$TMPDIR` unless the browser asks for cleanup | `filesystem.py` |
| 14 | Low | Data files created with default umask; only `.secret_key` is 0600 | several |
| 15 | Low | Plaintext metadata on disk and in backups (folder names, per-folder counts, timing) | `sync_cache.py`, `backup.py` |
| 16 | Low | Archive file overwrite on IMAP UID reuse | `commit.py` |
| 17 | Low | Attachment filenames unescaped in `Content-Disposition` | `emails.py` etc. |
| 18 | Low | Backups have CRC only, no integrity/authenticity; sidecar manifest can point at arbitrary zip paths | `backup.py` |
| 19 | Low | Dependency floors admit known-vulnerable pypdf and Pillow releases | `requirements.txt` |
| 20 | Low | Smaller items: `/auth/logout` lacks a CSRF token, rate limiter keyed on loopback address, restore leaves stale `-wal`, non-constant-time compare in two migration paths, reset token accepted from `request.args` | various |

Two claims in the existing `Security_Audit.md` are wrong and should be corrected there: it says Argon2id runs with `p=4` (code and README say `p=1`, and `tests/test_kdf_cost.py` pins it), and its "Key file permissions 0o600" row applies only to `.secret_key`, not to `.salt` or anything else. Its "Session timeout: Enforced" row is contradicted by finding 1.

---

## Findings

### 1. High — The server-side idle timeout never fires, and the client-side timeout leaves the archive unlocked

`web/app.py:128-167`: every non-streaming request refreshes `session["last_activity"] = now`. `web/templates/base.html:239-326` polls `GET /api/session-status` every 30 seconds. That poll is not exempted from the refresh, so the server's idea of "last activity" is never more than 30 seconds old while a tab is open. Consequently the timeout branch at `app.py:156-164` (which is the only place that calls `Encryption.lock()` on timeout) is unreachable, and `settings.py:89-92` computes `seconds_remaining` from the just-refreshed value, so `warning_needed` is never true and the countdown-then-logout path in `showWarning()` never runs either.

What actually happens at the configured timeout is `blankScreenAndLogout()` (`base.html:386-420`), which is purely cosmetic: it replaces `document.body` with a "Session Timed Out" panel. It does not POST `/auth/logout`, does not call `Encryption.lock()`, and does not clear the cookie. The polling interval keeps running.

Exploit: the user sets a 15-minute timeout, walks away from the machine with MailRepo open, and sees the timed-out screen when they return — which reads as safe. Anyone who sat down in between could open a new tab (or, in the desktop shell, navigate the same window) to `http://127.0.0.1:<port>/`, and the cookie is valid, `Encryption.is_unlocked()` is true, and the full archive is readable. For an app whose pitch is protecting privileged client correspondence, the idle lock is a core promise and it is not being kept.

Fix, in three parts: exempt `api.session_status` from the `last_activity` refresh (and `api.keepalive` too, since it is only meant to fire on real user input — the current client code already does that correctly); make `blankScreenAndLogout()` call `window.mailrepoLogout()` so the server locks; and add a server-side watchdog independent of any request — a daemon thread that checks a process-level `last_real_activity` timestamp and calls `Database.close(); Encryption.lock()` when it is exceeded, so that a closed tab or crashed webview still locks the archive. Add a test that advances time past the timeout while polling `session-status` and asserts `Encryption.is_unlocked()` is false.

### 2. High — HTML and SVG attachments are served inline, same-origin, with the email's own Content-Type

`web/blueprints/api/emails.py:759-767` (and the same pattern in `accounts.py:449-456` and `imports.py:666-673`): with `?view=1` the attachment is returned as `Content-Disposition: inline` with `mimetype=att["content_type"]` taken verbatim from the MIME part. There is no `Content-Security-Policy`, no `X-Content-Type-Options: nosniff`, and no `after_request` hook anywhere. `mail.js:1838-1866` (`isViewableInBrowser`) explicitly lists `text/html`, `image/svg+xml`, and `text/javascript` as viewable and, for archived mail, renders `<a href="…?view=1" target="_blank">` at `mail.js:1581`.

In **browser mode** (`python main.py`, which the README documents), one click on "Open in new tab" for a `text/html` attachment navigates the browser to a page served from the app's own origin with the attacker's markup. Its script runs with the session cookie, reads the CSRF meta tag from the opener (same origin), and has the whole JSON API — every folder, every message, every attachment, the IMAP credentials via the accounts endpoints — plus `/api/filesystem/read-file` (finding 12) and `post_backup_command` (finding 6). SVG as a top-level document executes `<script>` the same way.

In the **packaged desktop build** this is mitigated: `desktop.js:70-82` intercepts same-origin `target="_blank"` clicks in the capture phase and opens the bytes with the OS default application instead. So the packaged app is not exploitable through the left-click path. It remains exploitable through anything that bypasses that click handler (middle-click/`auxclick`, a context-menu "open in new window" if the webview offers one), and the server-side hole is there regardless of which client happens to be in front of it.

Fix: on the server, never honour the email's Content-Type for inline delivery. Force `Content-Disposition: attachment` for everything except a short allowlist (`application/pdf`, `image/jpeg`, `image/png`, `image/gif`, `image/webp`, `text/plain`) and for those serve with `Content-Security-Policy: sandbox; default-src 'none'` and `X-Content-Type-Options: nosniff`. Remove `text/html`, `image/svg+xml`, `text/javascript`, `text/css`, `application/json` and the matching extensions from `isViewableInBrowser`. Add a global `after_request` that sets `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY` on every response — cheap and closes several doors at once.

### 3. High — "Load remote images" PDF export embeds local files named by the email

`core/pdf_export.py:932-933`: when `load_remote=True`, `HTML(string=full_html).write_pdf(...)` runs with WeasyPrint's default `URLFetcher`. I checked WeasyPrint 69.0's `urls.py:300-304`: the default opener registers `FileHandler` and `FTPHandler`, so `file://` URLs resolve. WeasyPrint's `get_html_metadata()` (`html.py:360-397`) does `query_all('title','meta','link')` over the **whole document** and turns every `<link rel="attachment" href="…">` into an embedded PDF file attachment fetched through that fetcher. The sanitizer `_sanitize_email_html()` (`pdf_export.py:416-486`) strips `<script>`, Office namespace tags, and absolute positioning, but leaves `<link>` alone.

Exploit: an attacker sends an email whose body contains `<link rel="attachment" href="file:///Users/rick/Library/Application Support/MailRepo/data/.salt">` (or `~/.ssh/id_ed25519`, or a client's file with a guessable path). Months later the user exports that folder to PDF with "Load remote images" ticked — the checkbox persists for the session (`export-modal.js:45-51`) and its hint mentions only tracking pixels — and sends the PDF to a client or opposing counsel. The key file rides along inside the PDF as an attachment. `<img src="file:///…/something.png">` similarly embeds local images. The default `load_remote=False` path (`pdf_export.py:937-946`) is sound: its fetcher passes only `data:` URLs and returns an empty PNG for everything else, and `launcher.py`'s `print_html` uses the same one.

Fix: never use the default fetcher. In the `load_remote` branch, wrap `default_url_fetcher` so it permits only `http:` and `https:` (and `data:`) and returns the empty-PNG stub for anything else; and strip `<link …>` elements and `rel="attachment"` attributes in `_sanitize_email_html` regardless of mode. Separately, `from weasyprint import default_url_fetcher` is deprecated in 69.0 and will eventually be removed — with the `>=60.0` floor that will one day break export outright, so migrate to `URLFetcher(allowed_protocols=…)`.

### 4. High — Restore trusts the backup's `deleted_files` list: path traversal to arbitrary file deletion

`utils/backup.py:1265-1272`: entries are extracted with `zf.extract()`, which is safe (CPython strips `..` and absolute components). But immediately afterwards:

```python
metadata = json.loads(zf.read("_backup_metadata.json"))
for rel_path in metadata.get("deleted_files", []):
    staged_path = staging_dir / rel_path
    if staged_path.exists():
        staged_path.unlink()
```

`rel_path` is used verbatim. `staging_dir / "../../../.ssh/id_rsa"` resolves outside the staging directory, and with an absolute `rel_path` pathlib discards the left-hand side entirely. Nothing verifies the result stays under `staging_dir`.

Exploit: anyone who can write to the backup destination (a shared Dropbox, a compromised cloud sync account, a colleague on a shared NAS) edits `_backup_metadata.json` inside any incremental zip. Backups carry no integrity protection (finding 18), so the change is invisible. The next restore silently deletes whatever files were named, as the user. The disaster-recovery "pick a folder" path (`discover_restore_points_in`, `backup.py:1153`) is reachable with an entirely attacker-supplied manifest and zips, so this does not even require access to the user's real backup folder — only convincing them to restore from a folder.

Fix: before joining, reject any entry that is absolute or contains `..` as a component; after joining, `resolve()` and require `is_relative_to(staging_dir.resolve())`; and restrict to the `data/` and `archive/` prefixes that `get_all_backup_files()` actually produces. Apply the same check to `entry["filename"]` from the sidecar manifest at `backup.py:890-893`, which currently accepts absolute and `../` paths.

### 5. Medium — `escapeHtml()` does not escape quotes, and is used inside double-quoted attributes

`web/static/js/utils.js:10-15` implements `escapeHtml` by setting `textContent` and reading back `innerHTML`. Text-node serialization escapes `&`, `<`, and `>` but not `"`. That is fine in element-text context — and the vast majority of uses (subjects, senders, filenames in the viewer and lists) are in that context and are safe. But there are 22 uses of the form `attr="${escapeHtml(...)}"`, and the ones fed from the network are IMAP folder paths: `sidebar.js:657` renders `data-folder="${escapeHtml(node.fullPath)}"` with `fullPath` straight from `client.list_folders()` (`accounts.py:275-316`), and `imports.js:623` and `folder-selection.js:341,493` do the same for imported mbox folder names (which come from `X-Folder` / `X-Gmail-Labels` headers). A folder named `x" onmouseover="…` closes the attribute and injects an event handler; `<`/`>` escaping prevents a new tag but not this. The injected handler runs in the main, unsandboxed app origin.

Realism: a hostile IMAP server, or an mbox file from an untrusted source. Not something a random email sender can do on Gmail, which is why this is Medium rather than High — but the fix is one line and closes the whole class.

Fix: make `escapeHtml` also replace `"` → `&quot;` and `'` → `&#39;`. Do the same in the local copies of the function in `progress.js:355`, `settings.js:1153`, `backups.js:1015`, and `mail.js:1153` (better: delete those and import the shared one).

### 6. Medium — `post_backup_command` is arbitrary shell behind a CSRF token only

`web/blueprints/backups.py:66-67` stores the command with no confirmation; `backups.py:123-133`, `auth.py:1044-1056`, and `main.py:82-108` run it via `utils/__init__.py:33-41` with `shell=True`. The feature is legitimate (rclone/rsync hooks), but as gated today it means any script execution in the app origin — findings 2 or 5 — can set the command and trigger a backup, escalating "read the archive" to "run code as the user". The same token-only gate covers `prepare-restore` (rolls the archive back at next launch) and `backup_location` (redirects future backups, including `.salt` and `.secret_key`, to any writable folder).

Fix: require the master password for changing `post_backup_command`, `backup_location`, and `prepare-restore`, exactly as `reset_database` already does (`settings.py:184-192`). The `verify-password` endpoint and pattern already exist.

### 7. Medium — Folder-level post-commit action deletes everything in the IMAP folder, including messages that were not archived

`progress_commit.py:665-676`: `_apply_folder_post_action` runs a fresh `search("ALL")` and applies archive/trash/delete to every UID it gets back. The preceding `commit_imap_folder` records per-message failures in `results["failed"]`, but the caller at `progress_commit.py:376-378` does not look at them before applying the folder action. Any message that failed to archive (fetch error, decode error, disk error) and any message that arrived between the two SEARCHes is deleted without ever entering the archive. With "delete" on Gmail this goes through `delete_emails_via_trash` and is permanent.

This is a data-safety issue rather than a confidentiality one, but for a compliance-archiving tool "we deleted the original and it is not in the archive" is arguably the worst outcome the product can produce.

Fix: apply the post-action only to the UID set that was successfully archived in the commit pass, and skip the folder action entirely (with a visible warning) if `results["failed"]` is non-empty for that folder. The per-message path at `progress_commit.py:454-596` already reasons about "unaccounted" items and is the pattern to follow.

### 8. Medium — Credential rotation does not revoke against anyone holding an older key file

`core/encryption.py:810-849`: a password change or recovery-key rotation rewrites one 93-byte half of the 190-byte key file; the master key never changes. `_encrypt_v2_with_key` (`:533-545`) uses AAD of a single version byte, so the two wrapper halves are not bound to each other, and nothing inside the SQLCipher database records which key file it belongs to (`utils/backup.py:1691-1740` computes a fingerprint, but only for labelling restore points; login never checks it).

Two consequences. Rollback: someone with last month's backup and last month's password copies the old `data/.salt` over the live one — or splices only the old recovery-key half into the live file, leaving the current password half intact so the owner notices nothing — and the revoked credential opens all current mail. Offline: with an old `.salt` and the old password they derive the master, HKDF the database key, and read a copy of the live `mailrepo.db` without touching the machine. The existing audit's line "the old password is genuinely revoked" is true only against an attacker with no earlier copy of the key file, and the audit's own backup section already concedes that backups are exactly what tends to escape control.

Fix: (a) bind the AAD to `magic || salt_pw || salt_rk || archive_id`, where `archive_id` is 16 random bytes stored both in the key file and in the encrypted `settings` table, and compare at login — this detects splicing and rollback even though it cannot prevent them; (b) offer "rotate master key and re-encrypt" as an explicit option on password change and post-recovery reset, for users who suspect compromise — `migrate_to_v3` already implements the full walk and can be generalised; (c) reword the README and audit claim so users understand that changing the password protects the live archive only, and that old backups must be destroyed to complete a revocation.

### 9. Medium — No STARTTLS; unticking "Use SSL/TLS" sends the IMAP password in cleartext

`core/imap.py:117-126`: `use_ssl=False` produces a plain `imaplib.IMAP4` and there is no `starttls()` call anywhere in the codebase. The checkbox at `index.html:500` carries no warning. A user on port 143 — common on small hosts, and what many provider docs describe as "STARTTLS" — ends up sending the mailbox password and every fetched message in the clear. The legitimate use for the unticked box is ProtonMail Bridge on loopback.

Fix: when `use_ssl` is false, call `connection.starttls(ssl.create_default_context())` and fail if the server does not advertise STARTTLS; allow true plaintext only when the host is loopback; relabel the checkbox so it says what it does.

### 10. Medium — Port squatting in the desktop launcher

`launcher.py:143-160`: `_pick_port` binds 5050 to test availability, closes the socket, and returns; waitress binds later in a daemon thread. If another local process takes 5050 in that window, waitress dies silently in its thread, `_wait_for_server` gets a 200 from the squatter, and `webview.create_window(..., f"http://127.0.0.1:{port}")` displays the squatter's page. A pixel-perfect login page captures the master password — the one secret that is never on disk. Also, `_is_mailrepo()` (`:132`) checks only that the response contains the bytes `MailRepo`, so a squatter that serves that string makes every launch abort with "already running".

This needs a hostile process already running as the user, so it is not a remote attack. But that is precisely the position a signed, notarized, hardened-runtime app is supposed to defend against on macOS, where the attacker cannot simply ptrace the process.

Fix: bind the listening socket once in the launcher and hand it to waitress (`serve(app, sockets=[sock])`) so there is no window; additionally generate a per-launch secret, load the webview at `/?boot=<token>`, and have the server refuse to render the login page without it. Use the token for the "already running" check instead of a substring.

### 11. Medium — Flask `SECRET_KEY` is copied into every backup and restored with loose permissions

`utils/backup.py:125-127` includes `data/.secret_key` in every zip; `:1265` extracts it (zipfile does not restore modes) and `:1373-1379` `copy2`s it into place, so after a restore it is no longer 0600. The session cookie is signed, not encrypted, and contains only `authenticated`, `last_activity`, and `csrf_token` (`auth.py:727-731`) with no per-login nonce. Anyone holding the secret and able to reach 127.0.0.1 (another account on the same machine) can mint a valid authenticated cookie with a fresh CSRF token and, while the archive is unlocked — which finding 1 makes "all day" — read everything and pass CSRF. `app.py:109-119` also accepts any 24-hour-old signed cookie once the process is unlocked, so a cookie captured before a logout/re-login still works afterwards.

Fix: sessions cannot outlive the process anyway (the keys live in process memory), so generate `SECRET_KEY` per process with `secrets.token_bytes(32)` and never write it to disk; drop it from backups. Put a random `login_id` in the cookie at login, hold the current one in process memory, clear it on lock, and compare in `before_request` — this also closes cookie replay across logout.

### 12. Low — `/api/filesystem/*` is an authenticated read-anywhere

`filesystem.py:77-447`: `browse`, `read-file`, `scan-eml`, and the parse endpoints do `expanduser` + `realpath` and then operate, with no base directory. `realpath` canonicalises; it does not confine. The existing audit's "Path traversal: realpath() protection" describes something that is not containment. This is by design for the import file picker, and on its own requires a session plus CSRF token, so it is not a vulnerability. It is listed because it sets the blast radius of findings 2 and 5: any script in the app origin can read `~/.ssh`, other apps' data, and anything else the user can. If an import root or a user-chosen directory would not hurt the UX, confine to it; otherwise leave as is and treat 2, 5, and 6 as the priority.

### 13. Low — PST import leaves a plaintext mailbox in the temp directory

`filesystem.py:702-763`: `readpst` writes plaintext mbox files into `mkdtemp(prefix="mailrepo_pst_")` (0700, good). Removal happens only if the browser later calls `/filesystem/cleanup-pst-temp` (`:774-807`) or on error. A crash, force-quit, or forgotten tab leaves the decrypted PST in `$TMPDIR` indefinitely. `launcher.py:220-227` already sweeps viewer temp files at startup; do the same for `mailrepo_pst_*`, and also remove on logout, lock, and `atexit`. The subprocess call itself is list-form with a realpath'd, `.pst`-checked argument and a 300-second timeout, and is fine.

### 14. Low — Data files are created with the default umask

Only `generate_flask_secret_key` (`encryption.py:903-911`) and the launcher viewer files set modes. The key file (`encryption.py:870`), database, archive files (`commit.py:118`), sync cache (`sync_cache.py:31`), and state JSON (`backup.py:38`) get whatever the umask gives, typically 0644. On a multi-account machine other users get the Argon2 salt and wrappers, the full ciphertext corpus, and the metadata in finding 15. Fix: `os.umask(0o077)` at startup, and create `data/` and `archive/` as 0700.

### 15. Low — Plaintext metadata on disk and in backups

`.sync_cache.db` holds account ids, IMAP folder names, UIDVALIDITY, MODSEQ, and timestamps, and is not wiped by Reset Database (`settings.py:169-247`). `.backup_state.json` lists every archive path with hash, mtime, and size — revealing per-folder message counts and filing times. `backups/manifest.json` and its copies in every backup destination list filenames, sizes, dates, and directory paths. Backup zips are plain ZIPs of encrypted files, so entry names and sizes are visible. The legacy `core/importer.py` (`:100,186`, reachable through the unreferenced-but-live `/api/import/mbox` and `/api/import/eml` routes in `imports.py:60-141`) names archive files by Message-ID, which reveals correspondent domains. None of this exposes content; all of it exposes activity patterns, which for a therapist's or lawyer's archive is itself sensitive. Fix: include `.sync_cache.db` in reset; delete or rename the legacy importer routes; consider whether folder names in the sync cache can move inside SQLCipher. The desktop viewer's decrypted files in `/tmp/mailrepo-viewer-<uid>/` (0700/0600) persist across lock and logout until next launch — clear them on lock as well.

### 16. Low — Archive file overwrite on IMAP UID reuse

`commit.py:116-119, 245, 411`: archive filenames are `{account_id}_{uid}.eml.enc` and `_save_email_to_archive` uses `write_bytes()` with no existence check. UIDs are unique only per UIDVALIDITY; after a mailbox rebuild (or from a server that simply re-issues a UID) a new message archived into the same folder overwrites an earlier one's ciphertext while the old database row still points at the file. The Message-ID duplicate check does not catch this. Also nothing verifies `uid.isdigit()`; the fixed prefix is what prevents traversal. Fix: open with `O_CREAT | O_EXCL` and disambiguate on collision as `core/importer.py:193-200` already does, or name by UUID; validate the UID.

### 17. Low — Attachment filenames unescaped in `Content-Disposition`

`emails.py:693,766`, `accounts.py:391,456`, `imports.py:672`: `filename="{att["filename"]}"` embeds the decoded MIME filename without escaping `"`. Werkzeug rejects CR/LF so there is no response splitting, but a `"` breaks the header and the client-side regex at `mail.js:1937`, and lets a filename smuggle a `filename*=` parameter. Use `send_file(..., download_name=…)` or RFC 5987 encoding.

### 18. Low — Backups carry no integrity or authenticity

`verify_backup` (`backup.py:813`) and `verify_restore_point_files` (`:1638`) run `testzip()` only. The encrypted payloads self-authenticate, but the metadata that drives restore (finding 4) and the manifest sidecar (`:890-893`, which accepts absolute and `../` filenames) do not. Fix: HMAC each zip with a key derived from the master via HKDF (a new info string), record it in the manifest, and refuse to restore on mismatch; treat a `post_backup_command` read from a just-restored database as untrusted and require re-confirmation.

### 19. Low — Dependency floors admit known-vulnerable releases

`requirements.txt` uses `>=` floors and `build_deb.sh:47-57` installs whatever satisfies them at build time. `pypdf>=4.0` admits versions with a run of infinite-loop denial-of-service advisories (CVE-2025-62707, CVE-2026-54651, CVE-2026-54531, CVE-2026-84309); `_append_pdf_attachments` (`pdf_export.py:1036-1046`) merges attacker-supplied PDF attachments, and the export runs in a daemon thread with no timeout, so a crafted PDF pins that thread forever. `Pillow>=10.0.0` admits pre-11.3 releases with buffer overflows (CVE-2025-48379 and later); WeasyPrint decodes attacker images passed as `data:` URLs. Fix: pin exact versions in the packaged builds (a `requirements.lock`), and put a wall-clock limit around the pypdf merge. For what it is worth, `pyzipper`'s WinZip AES uses PBKDF2-SHA1 at 1000 iterations, so ZIP export passwords need to be long — worth a sentence in the export dialog.

### 20. Low — Smaller items

`/auth/logout` is POST-only but sits outside `/api/` and does not check a token (`auth.py:991-1008`); a cross-site auto-submitting form can force a logout and, if a backup is due, run the post-backup command. Add the explicit check the sibling non-`/api/` forms use.

The login rate limiter keys on `request.remote_addr`, which on loopback is a single bucket; on Linux every 127.x.y.z is a distinct key. Practical impact is small because each guess costs a full Argon2id, but any web page can lock the owner out for 60 seconds with five cross-site POSTs. A process-global counter with backoff is simpler and better for a single-user app.

`complete_restore` (`backup.py:1363-1370`) replaces `mailrepo.db` without removing a stale `-wal`/`-shm`; after an unclean exit SQLite will replay the old WAL into the restored database. Unlink both before copying, and in `reset_database`.

`core/password_change.py:151` and `core/crypto_migration_v3.py:218` compare derived keys with `!=`; not exploitable (each probe costs a full derivation) but use `secrets.compare_digest` for consistency with `encryption.py:704,731`.

`auth.py:852`: the post-recovery reset route accepts the handoff token from `request.args` on GET. The app never generates such a URL, but accepting it means a pasted URL lands the token in browser history. Restrict to `request.form`.

`encryption.py:869`: a crash between writing `.salt.v2tmp` and the rename leaves the temp file behind. Harmless, but clean it up at startup.

---

## What I verified as sound

Listed so the next reviewer knows what has been covered and does not have to re-derive it.

**Key material.** MRC3 is exactly `"MRC3" ‖ salt_pw[32] ‖ wrapped_pw[61] ‖ salt_rk[32] ‖ wrapped_rk[61]` = 190 bytes, length-checked before use. Argon2id `t=6, m=256 MiB, p=1`, 32-byte output; the cheap parameters engage only when both `MAILREPO_FAST_KDF` and `MAILREPO_DATA_DIR` are set. Fresh 32-byte `secrets` salts on every wrap and rewrap. Recovery KEK is full HKDF-extract-and-expand with a random salt and `mailrepo.recovery.v3` info. File and database subkeys use HKDF-Expand with distinct info strings. Every AES-GCM encryption in the codebase goes through one call site with `os.urandom(12)` per call — no deterministic or counter nonces anywhere. Newly built key files are re-opened through both doors before hitting disk. Recovery key is `secrets.token_bytes(20)` base32 with lookalike fix-ups. Password verification is GCM-tag-only; there is no stored comparand and no `==` against a secret. The master key is never pickled or written unencrypted; `lock()` drops all references; `before_request` checks `Encryption.is_unlocked()` server-side so an old cookie cannot decrypt after a lock. Key-file and per-file rewrites use temp + fsync + `os.replace` + directory fsync. v3 password change and reset are single atomic replaces; v2 paths gate on a verified recent backup and write an interruption marker.

**SQLCipher.** `PRAGMA key = "x'<hex>'"` from `bytes.hex()` — no quoting problem; raw key skips SQLCipher's own KDF; WAL frames are encrypted; `-shm` holds only the index. Missing `sqlcipher3` is a hard fail at startup and again before connect — no silent plaintext fallback. All SQL is parameterized. FTS5 and pending-commit tables are inside the encrypted database.

**Recovery flow.** `verify_recovery_key` adopts nothing; the handoff token is `secrets.token_urlsafe(32)` with a 300-second TTL, single-entry, consumed on success; reset grants no session; the key never enters session, cookie, URL, or log (the tests at `test_recovery_key_web.py:107,179,196` guard this). Rotation requires the password.

**Email rendering.** The body iframe sandbox is `allow-same-origin allow-modals allow-popups allow-popups-to-escape-sandbox` with no `allow-scripts`, so inline scripts, SVG scripts, form submission, `javascript:` links, and event handlers do not execute. Remote resources are blocked by the iframe CSP until the user clicks "Load remote content"; `cid:` parts are inlined server-side as `data:`. Subject, sender, and recipients reach the DOM via `textContent` or `escapeHtml` in element-text context, which is safe. Jinja autoescape is on; no `|safe`, `Markup`, or `autoescape false` anywhere. No `innerHTML` of raw server strings outside the attribute cases in finding 5. No `eval`, `new Function`, `pickle`, `yaml.load`, or `marshal` anywhere.

**CSRF and sessions.** The middleware covers every `/api/`-path POST/PUT/DELETE/PATCH with `compare_digest`; the three state-changing non-`/api/` forms each verify a token explicitly; no state-changing GET routes exist. The CSRF token is injected into the meta tag only when authenticated, and the login page renders it empty. `SECRET_KEY` is `secrets.token_hex(32)` created with `O_CREAT|O_EXCL` at 0600. Cookies are `HttpOnly`, `SameSite=Lax`. SSE exemptions still require an authenticated, unlocked session and only skip the idle timeout. Reset Database requires the password, the literal `RESET`, and a CSRF token.

**IMAP.** `ssl.create_default_context()` gives certificate and hostname verification with no override flag. Credentials are AES-GCM in the database and decrypted only in process. SEARCH criteria are constants, and Message-ID searches go through `_imap_escape`. Thread walks are bounded.

**Files and exports.** Archive write paths use an integer folder id and a sanitized UID. PST conversion uses list-form `subprocess.run` with a realpath'd argument and a timeout; cleanup is confined to `$TMPDIR/mailrepo_pst_*`. The default PDF export fetcher passes only `data:` URLs; header fields are HTML-escaped. ZIP export sanitizes entry names and uses AES-256 when a password is given; `reveal` is restricted to known job paths; job ids are UUID4. Restore extracts with `ZipFile.extract` (safe), takes a safety backup first, and is idempotent on crash.

**Launcher and logging.** Server binds 127.0.0.1 only; waitress with the werkzeug logger silenced; `debug=True` only behind the explicit `--dev` flag. Hardened runtime with no entitlement exceptions. `utils/log.py` writes to stdout only — there is no log file — and no log statement emits passwords, keys, credentials, subjects, or bodies; the one thing worth noting is that the full `post_backup_command` string is printed at INFO, which may include tokens for rclone-style hooks.

---

## Suggested order of work

Findings 1 and 2 first: the idle-lock fix is small and restores a promise the product makes on its front page, and the attachment fix is a few lines of server-side header hardening plus a shorter allowlist. Then 3 and 4, both of which are five-line guards against a crafted input. Then 5 and 6 together, since 6 is what makes 5 (and any future XSS) more than a read. Then 7, which is the one most likely to cost a real user real data. The remaining Medium items — 8 through 11 — are design conversations rather than patches, and 8 in particular deserves a short design note before anything is coded. Everything under Low can be batched into a hardening release.

Finally, `docs/Security_Audit.md` should get an addendum pointing here and correcting the three rows noted above, so that the next reviewer starts from an accurate map.
