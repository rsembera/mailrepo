# Crypto Refactor Plan (May 2026)

## Scope

A single, coordinated migration that addresses three things at once on the
pre-1.0 codebase:

1. **HKDF refactor** — replace the current `_derive_fernet` and `_derive_db_key`
   pair (both running 480,000 PBKDF2 iterations independently) with a single
   PBKDF2 derivation of an intermediate "master key", followed by two HKDF
   expansions into the Fernet subkey and the DB subkey. Halves unlock cost.
2. **AES-128 → AES-256 file encryption** — replace Fernet (AES-128-CBC + HMAC)
   with AES-256-GCM for all archived email files (`*.eml.enc`) and encrypted
   IMAP credentials. Brings file encryption to parity with SQLCipher and
   pyzipper.
3. **Crypto-version field in the salt file** — store a one-byte version
   identifier alongside the salt so future KDF or cipher changes can be
   detected and migrated cleanly without breaking existing archives.

All three ride on a single one-time migration so we re-walk every
`.eml.enc` only once.

## Why one migration

Doing these as separate migrations would mean walking every encrypted file
on disk three times. Combining them is safer (fewer rewrite passes = fewer
windows for corruption) and faster (one migration, one verification).

## Why now

These are pre-1.0 changes. After 1.0 ships, the v1 cipher and KDF choices
become a permanent floor — every subsequent change is a migration with
real users on real data. Doing the cleanup now means 1.0 ships with the
mature crypto rather than the in-progress crypto.

## What stays the same

- SQLCipher (AES-256, key derived via raw PRAGMA so we bypass its internal
  KDF) — unchanged.
- pyzipper exports (AES-256, per-export password) — unchanged.
- PBKDF2-SHA256 at 480,000 iterations as the slow KDF — unchanged for now.
  (Argon2id remains a possible future change but is out of scope here;
  the crypto-version byte added in this refactor gives us the migration
  hook for it.)
- Schema version — unchanged. This is purely a crypto-layer migration; no
  DB schema changes.

## What changes

### 1. Salt file format

**Before:** `<32-byte salt><Fernet-encrypted verification token>`

**After:** `MRC2<32-byte salt><AES-256-GCM-encrypted verification token>`

The 4-byte `MRC2` magic ("MailRepo Crypto v2") lets us cleanly detect
old-format salt files for migration. v1 has no magic; the absence of
`MRC2` at byte 0 means "this is a pre-migration file, run migration".

### 2. Key derivation

**Before** (`encryption.py`):
```python
fernet_key = PBKDF2(password, salt,        iterations=480_000, length=32)   # cost: 1x PBKDF2
db_key     = PBKDF2(password, salt + DBSUFFIX, iterations=480_000, length=32) # cost: 1x PBKDF2
# Total unlock cost: 2 × PBKDF2 = ~960,000 iterations
```

**After**:
```python
master_key = PBKDF2(password, salt, iterations=480_000, length=32)          # cost: 1x PBKDF2
file_key   = HKDF(master_key, salt, info=b"mailrepo.file.v1", length=32)    # cost: ~free
db_key     = HKDF(master_key, salt, info=b"mailrepo.db.v1",   length=32)    # cost: ~free
# Total unlock cost: 1 × PBKDF2 = ~480,000 iterations
```

HKDF (RFC 5869) is the standard primitive for exactly this — turning one
secret into multiple subkeys with domain separation. The `info` parameter
provides the domain separation that the salt-suffix trick was hand-rolling.

### 3. File encryption

**Before:** Fernet (AES-128-CBC + HMAC-SHA256, 128-bit key).

**After:** AES-256-GCM (256-bit key, 96-bit nonce, 128-bit auth tag).
Same primitives library (`cryptography.hazmat.primitives.ciphers.aead`),
authenticated encryption (GCM provides confidentiality + integrity in one
operation), and ~the same performance characteristics.

**Wire format on disk** for each `.eml.enc` file:
```
[1 byte: version (0x02 for AES-256-GCM)]
[12 bytes: random nonce]
[N bytes: ciphertext]
[16 bytes: GCM auth tag]
```

The leading version byte means each file knows how to decrypt itself.
v1 (existing Fernet) files have no such byte; we detect them by the
Fernet token's signature (a Fernet token starts with `0x80` followed by
an 8-byte timestamp).

### 4. Stored credentials

`accounts.credentials_encrypted` currently holds a Fernet token. The
migration re-encrypts these to AES-256-GCM with the same wire format as
the file payloads.

### 5. Encryption class API

The public API stays nearly identical:
- `Encryption.encrypt(bytes) -> bytes` — now produces AES-256-GCM output
- `Encryption.decrypt(bytes) -> bytes` — auto-detects v1 (Fernet) vs v2
  (AES-256-GCM) by reading the first byte. This is what lets the
  migration be resumable: code that hasn't been migrated yet still works.
- `Encryption.encrypt_string` / `decrypt_string` — unchanged API,
  unchanged base64 encoding around the new payload.
- New: `Encryption.get_crypto_version() -> int` — reports whether the
  current archive is on v1 (needs migration) or v2 (current).

## Migration design

### Resumability is non-negotiable

The migration walks every `.eml.enc` file on disk (~1,634 on the
MacBook). Each file is read, decrypted with the v1 (Fernet) key, then
encrypted with the v2 (AES-256-GCM) key, then atomically replaced.

If the process is interrupted (sleep, crash, kill, power) partway
through, we MUST be able to resume cleanly. The mechanism:

1. The **per-file version byte** means every file self-identifies. A
   half-migrated archive has some v1 files and some v2 files; the runtime
   `decrypt()` handles both, so the app keeps working. The migration
   simply picks up where it left off by skipping any file that already
   starts with `0x02`.
2. The **salt file** is rewritten **last**, after every file and every
   credential record has been successfully migrated. Until that final
   write, the archive is still on v1 from the unlock-token's
   perspective. The salt file rewrite is atomic via temp-file + rename.
3. **Progress is streamed** via SSE just like the password-change flow
   already does, so the user has live feedback and can see where they
   are in the process.

### Migration steps (live order)

1. **Verify backup is current.** Refuse to run if the most recent backup
   is older than 24 hours, unless the user explicitly confirms an
   over-ride checkbox in the migration UI. (Cheap safety net; users
   should have a known-good backup before any crypto change.)
2. **Acquire the v1 Fernet** from the current unlocked session.
3. **Derive the v2 keys** (master → HKDF → file_key + db_key_v2). Note:
   the v2 db_key is derived from the same PBKDF2 master, so it WILL be
   different from the current v1 db_key. SQLCipher must be rekeyed.
4. **Walk archive and re-encrypt** every `.eml.enc`. For each file:
   - Read.
   - If first byte is `0x02`, already v2 → skip (resumability).
   - Else decrypt with v1 Fernet, encrypt with v2 GCM, atomically
     replace via temp-file + rename in the same directory (same
     filesystem, so rename is atomic).
   - Stream progress every 10 files.
5. **Re-encrypt IMAP credentials** in the `accounts` table.
6. **SQLCipher rekey** to the v2 db_key (`PRAGMA rekey`).
7. **Write the new salt file** with the `MRC2` magic, 32-byte salt, and
   v2-format verification token. Atomic write via temp file + rename.
8. **In-memory swap.** Replace the Encryption class's keys with v2 keys
   for the remainder of the session.

If step 4 or 5 is interrupted, restarting the migration finds the same
salt file (still v1 magic absent), the same v1 db_key works, and the
loop resumes from the first non-v2 file.

If step 6 succeeds but 7 fails, the DB is rekeyed to v2 but the salt
file still says v1 — on next launch, unlock would derive v1 keys and
SQLCipher would reject the open. Mitigation: step 6 and 7 happen back
to back with no I/O in between except the salt file write, and the salt
file write is to a temp file that's been pre-created and pre-`fsync`-ed.

### Atomic file replacement

For each migrated file, the pattern is:

```python
# Same directory = same filesystem = atomic rename on POSIX
tmp = filepath + ".v2tmp"
with open(tmp, "wb") as f:
    f.write(b"\x02" + nonce + ciphertext + tag)
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, filepath)  # atomic on POSIX
```

`os.replace` is atomic on the same filesystem on POSIX (Linux, macOS).
We never have a window where the file is missing or partially written —
either the v1 file is there, or the v2 file is there, never neither.

### Failure modes considered

| Failure | Effect | Recovery |
|---|---|---|
| Process killed mid-file (after fsync, before rename) | Stray `.v2tmp` file alongside original `.eml.enc`. Original is intact. | Resume: tmp files are detected and cleaned up at the start of the next migration run. |
| Process killed during file walk | Some files v1, some v2, salt file still v1. Runtime decrypt handles mixed state. App works. | Resume: re-run migration, skip files already at v2. |
| SQLCipher rekey succeeds, salt file write fails | DB encrypted with v2 key, salt file says v1. Next unlock fails. | Recovery script: use last backup, OR re-run migration end-to-end (re-derives the v2 key deterministically and re-attempts the salt file write). |
| Salt file write succeeds, in-memory swap fails | Disk is v2, memory is v1. Session is broken. | User restarts app → fresh unlock → derives v2 from salt magic → works. |
| Power loss during atomic rename | `os.replace` is atomic; either old or new file exists, never both, never neither. | None needed. |
| Disk full during migration | First write to `.v2tmp` fails. Original `.eml.enc` untouched. | Free up space, re-run. |

### Pre-flight checks

Before any file is touched:

1. The current Fernet key successfully decrypts a known-good file
   (sanity check that the user's session is healthy).
2. Free disk space ≥ 2× the size of all `.eml.enc` files combined.
   (Worst case: every file is duplicated via `.v2tmp` momentarily.)
3. The archive directory is on the same filesystem as `/tmp`-equivalent
   space we'd be using. (Actually, we keep `.v2tmp` files in the same
   directory as the source file, so this is automatic.)
4. Most recent backup is ≤24h old (or user override).

## Testing plan

### Test 1: Dry run on a copy of Apollo's archive

Apollo's archive is small (small handful of test messages). Copy it
aside, run the full migration end to end on the copy with the production
code path, verify every file decrypts cleanly with v2 keys and the
contents byte-match what v1 produced.

### Test 2: Interrupt mid-migration on the copy

Kill the migration partway through. Verify:
- Some files are v1, some are v2.
- App still launches and reads all files correctly (auto-detect works).
- Resume completes successfully.
- After resume, every file is v2 and decrypts identically to the
  pre-migration content.

### Test 3: Power-loss simulation on the copy

Run migration under `stress-ng` or similar process killer that
SIGKILLs the migration at random points. Repeat several times,
verifying each time that the archive is recoverable.

### Test 4: Full content equivalence

After migration, walk every file and verify:
- v2 decrypt output byte-equals what v1 decrypt would have produced.
- File counts match.
- DB queries return identical results (subjects, senders, etc).

### Test 5: Run the actual app

Stage an email, commit it, archive it, search it, export it, restore
from a backup taken before migration. Every code path that touches
encrypted data exercised.

Only after Tests 1-5 pass on the Apollo copy do we touch the MacBook.

## Risks and mitigations

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Bug in v2 encrypt or decrypt corrupts data | Low | High | Tests 1-5; resumability means partial migration is recoverable; backup taken before run |
| Mid-migration crash leaves archive unreadable | Very low | High | Per-file version byte + atomic rename + resumable walk |
| User loses passphrase between migration and verification | Same as today | Same as today | No change |
| HKDF expansion produces a key that collides with v1 db_key | Effectively zero | High | Domain separation via `info=` parameter; different by construction |
| pyzipper exports break | None (separate keying) | N/A | Exports use per-export password, not master key |
| Tests pass, production fails | Low | High | Migration is run with last good backup verified ≤24h before |

## Out of scope

These are explicitly **not** part of this refactor:

- **Argon2id** instead of PBKDF2. Worth doing later; the crypto-version
  byte added here gives us the migration hook. Decision deferred.
- **Database connection threading** (the shared connection issue). Latent;
  fix when a real bug surfaces.
- **Iteration count bumping** (480k → 600k). Same migration mechanism
  would apply via crypto-version byte.
- **Hardware-backed key storage** (macOS Keychain, etc). Different
  product surface; not 1.0 territory.

## Open questions for review

1. **HKDF salt parameter.** I'm using the same 32-byte salt for both
   PBKDF2 and HKDF, which is acceptable per RFC 5869 (HKDF's salt is
   not security-critical when the input keying material is already
   high-entropy, which PBKDF2 output is). But should HKDF use a
   separate salt? My read: no — the `info` parameter provides the
   domain separation, the salt is just a non-secret randomizer.

2. **Nonce strategy for AES-GCM.** I'm using a fresh random 96-bit
   nonce per file. NIST SP 800-38D allows up to 2^32 random nonces per
   key before collision probability becomes meaningful; we'll never
   approach that. Alternative: deterministic nonce from file path. I
   chose random because it's simpler and the file count we'd need to
   hit the limit is astronomical.

3. **Should the version byte be on every file or just on the salt file?**
   Current plan: every file. Pro: each file self-identifies, resumability
   trivial. Con: 1 byte of overhead per file. Marginal but worth
   confirming.

4. **`os.replace` cross-platform behaviour.** Atomic on Linux/macOS for
   same-filesystem replacements. Less guaranteed on Windows. MailRepo
   targets Linux + macOS today, so this is fine. Worth flagging if
   Windows is ever in scope.

5. **What if a Fernet token in the archive is corrupted?** Today's
   `decrypt()` raises; we'd hit an exception mid-migration and skip
   that file. Probably right behaviour but worth confirming we want
   that vs. aborting the whole migration on the first corruption.

## What I'd ask 4.8 to review

- The HKDF parameters (`info` values, salt reuse).
- The wire format for v2 files (version byte placement, GCM nonce
  size, tag handling).
- The atomic-replace pattern — is there a portability gotcha?
- The pre-flight checks — are any missing?
- The failure-mode table — any cases I haven't considered?
- The open questions above.

## Estimated execution time

- Implementation: 2-3 hours (mostly: the new `Encryption` class methods,
  the migration SSE endpoint, the UI hook, the v1/v2 detection).
- Apollo testing (Tests 1-5): 1-2 hours.
- MacBook migration (with backup verification): 30 minutes including
  the actual run.
- Total: half a day with focused work.

## Rollback plan

If something goes wrong on the MacBook:

1. The migration writes the salt file last. If we never reach step 7,
   the archive is still v1 from the unlock perspective.
2. If we did reach step 7 and something failed after, restore from the
   ≤24h-old backup.
3. Per-file `.v2tmp` files are cleaned up by the next migration run's
   pre-flight; they're harmless if left behind.
4. The original v1 code (Fernet) stays compileable through this
   refactor — we don't delete it, we just stop using it for new
   encryption. So a worst-case is: revert the commit, restore the
   backup, app boots on v1 again.
