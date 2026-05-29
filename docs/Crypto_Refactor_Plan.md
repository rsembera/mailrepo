# Crypto Refactor Plan (May 2026)

## Scope

A single, coordinated migration that addresses four things at once on the
pre-1.0 codebase:

1. **Argon2id replaces PBKDF2 as the password KDF** — memory-hard
   derivation, resistant to GPU/ASIC attack. Tuned to ~750ms–1s on the
   MacBook Air M4 with 256 MiB memory cost.
2. **HKDF subkey expansion** — replace the current dual-PBKDF2
   derivation (running 480k iterations independently for file key and
   DB key) with a single Argon2id derivation of a master key, followed
   by two HKDF-Expand calls into the file subkey and the DB subkey.
   Subkey derivation becomes essentially free.
3. **AES-128 → AES-256 file encryption** — replace Fernet (AES-128-CBC
   + HMAC) with AES-256-GCM for archived email files (`*.eml.enc`) and
   encrypted IMAP credentials. Brings file encryption to parity with
   SQLCipher and pyzipper.
4. **Crypto-version field in the salt file** — store a magic+version
   identifier alongside the salt so future cipher/KDF changes can be
   detected and migrated cleanly without breaking existing archives.

All four ride on a single one-time migration so we re-walk every
`.eml.enc` only once.

## Why one migration (the load-bearing reason)

Changing the KDF forces a full re-walk of every `.eml.enc` file
regardless: the file key bytes change, so every Fernet token would need
to be decrypted under the old key and re-encrypted under the new key
even if we kept Fernet itself. Once that re-walk is forced by the
Argon2id change, the AES-128 → AES-256 upgrade and the version-byte
addition cost essentially nothing extra — they ride as free passengers
on a walk that's happening anyway.

Stated plainly: if the KDF weren't changing, AES-256-for-files would
**not** be worth a dedicated migration. "Documentation asymmetry" and
"256 > 128" are real annoyances but not reasons to rewrite 1,634 files
on their own. It's the forced KDF re-walk that converts the cipher
upgrade from "not worth it alone" to "free rider on a forced walk."
This is the right reason to bundle the four changes; the wrong reason
would be "they're all crypto, let's just do them together."

## Why now (and where the risk actually is)

These are pre-1.0 changes. The motivation is **not** security urgency
— the current crypto is not weak. PBKDF2-SHA256 at 480k iterations is
above OWASP's PBKDF2 floor and resists offline cracking adequately for
the threat model. AES-128 has no practical break and won't for
decades. The framing is engineering-cost: doing this now is cheaper
than after real users have real data on disk. Post-1.0, every crypto
change becomes a migration with users on the other side.

The single largest risk in this whole exercise is the migration
itself corrupting or losing the only copy of 1,634 personal emails.
That risk dwarfs the marginal security delta between PBKDF2-at-480k
and Argon2id. So the care budget flows accordingly: less energy on
exact Argon2 parameters (any reasonable choice is safe), more on the
rekey/backup/atomicity machinery. The plan reflects this.

## What stays the same

- **SQLCipher** (AES-256, key derived via raw PRAGMA so we bypass its
  internal KDF) — unchanged. We continue to pass it a 32-byte hex key.
- **pyzipper exports** (AES-256, per-export password) — unchanged.
- **Schema version** — unchanged. This is purely a crypto-layer
  migration; no DB schema changes.
- **The salt itself** — still a 32-byte random value generated on
  initial setup. We're changing how the salt is *used*, not the salt.

## What changes

### 1. Salt file format

**Before (v1):** `<32-byte salt><Fernet-encrypted verification token>`

**After (v2):** `MRC2<32-byte salt><AES-256-GCM-encrypted verification token>`

The 4-byte `MRC2` magic ("MailRepo Crypto v2") lets us cleanly detect
old-format salt files for migration. v1 has no magic; the absence of
`MRC2` at byte 0 means "this is a pre-migration file." The v2
verification token is encrypted under the new Argon2id-derived file
subkey, so being able to decrypt it proves the user knows the
passphrase AND that we're on the right crypto version.

### 2. Key derivation

**Before** (`encryption.py`):
```python
fernet_key = PBKDF2(password, salt,            iterations=480_000, length=32)
db_key     = PBKDF2(password, salt + DBSUFFIX, iterations=480_000, length=32)
# Total unlock cost: 2 × PBKDF2-SHA256
```

**After**:
```python
# Argon2id-based master derivation (memory-hard, GPU-resistant)
master_key = argon2id.derive(
    password,
    salt=salt,
    time_cost=4,             # iterations
    memory_cost=262144,      # 256 MiB (in KiB; 256 * 1024)
    parallelism=1,
    length=32,
)
# HKDF-Expand for subkeys (Argon2id output is already uniform 32 bytes,
# so we use Expand rather than Extract-and-Expand)
file_key = HKDFExpand(master_key, info=b"mailrepo.file.v2", length=32)
db_key   = HKDFExpand(master_key, info=b"mailrepo.db.v2",   length=32)
# Total unlock cost: 1 × Argon2id (~750ms–1s on MacBook Air M4)
```

**Argon2id parameters.** m=256 MiB, t=4, p=1, targeting ~750ms–1s on
the MacBook Air M4. The mental model: time is the security knob,
memory is what kills GPU/ASIC parallelism. Bumping memory from 64 MiB
to 256 MiB raises offline-cracking cost meaningfully and is invisible
to the user on machines that have 8+ GiB of RAM. p=1 is cleaner than
p=2 for a single latency-bound unlock; higher parallelism would split
the memory across lanes, slightly reducing memory-hardness per lane.

These parameters are measured against the actual target during
implementation (Test 6 below). If we land far from ~1s on the M4, we
tune `time_cost` to hit the target.

**Why HKDF-Expand, not full HKDF.** Argon2id already outputs a
uniform 32-byte key. HKDF-Extract is for concentrating entropy from
non-uniform input, which we don't have. HKDF-Expand alone is the
honest expression of what we're doing. (Full HKDF with a salt would
be harmless and conventional; HKDFExpand is just more accurate.) The
`info` strings include `.v2` so the KDF identity is part of the
domain separation — a v3 KDF would use `.v3` info strings, making
keys cryptographically distinct from v2 even if the master happened
to land on the same bytes.

**Dependency change.** Add `argon2-cffi` to `requirements.txt`. The
library wraps the reference Argon2 implementation, is widely used
(Django, Flask-Security, others), and ships precompiled wheels for
Linux/macOS on Python 3.9+. No new system dependency on Linux.

### 3. File encryption

**Before:** Fernet (AES-128-CBC + HMAC-SHA256, 128-bit key).

**After:** AES-256-GCM (256-bit key, 96-bit nonce, 128-bit auth tag).
Same primitives library (`cryptography.hazmat.primitives.ciphers.aead`),
authenticated encryption (GCM provides confidentiality + integrity in
one operation), comparable performance with hardware acceleration on
both targets (AES instructions on M4, AES-NI on x86).

**Wire format on disk** for each `.eml.enc` file:
```
[1 byte: version (0x02 for v2)]
[12 bytes: random nonce, from os.urandom(12)]
[N bytes: ciphertext]
[16 bytes: GCM auth tag]
```

The leading version byte is **bound into GCM's AAD** (additional
authenticated data) at encryption time and verified on decryption.
This authenticates the version byte itself, so a tampered version
byte breaks the auth check — cheap defense in depth against
ciphertext-shape manipulation.

v1 (existing Fernet) files have no version byte; we detect them by
the Fernet token's signature (starts with `0x80` followed by an
8-byte timestamp). The migration's per-file walk skips any file
that already starts with `0x02` (resumability).

**Why random nonces, not deterministic.** A deterministic nonce
derived from the file path would be a trap: if a file's content ever
changes while its path stays the same, we'd reuse a nonce under the
same key — and GCM nonce reuse is catastrophic (leaks the auth key,
enables forgery). At our scale (thousands of files, far below the
~2^32 random-nonce bound), random 96-bit nonces are completely safe.

### 4. Stored credentials

`accounts.credentials_encrypted` currently holds a Fernet token. The
migration re-encrypts these to AES-256-GCM with the same wire format
as the file payloads.

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

### Two-phase structure

The file walk and the DB rekey have fundamentally different risk
profiles: the file walk is granular, atomic per file, and
version-byte-resumable. The DB rekey is monolithic, not
version-byte-resumable, and dependent on quiescent DB access. The
migration is therefore split into two phases with a durable checkpoint
between them.

**Phase 1: file layer.** Walks every `.eml.enc`, re-encrypts to v2.
Re-encrypts IMAP credentials. Verifies by counting all files start
with `0x02` and randomly sampling decrypts.

**Phase 2: database layer.** Only begins after Phase 1 has fully
completed and verified. Quiesces all other DB access. `PRAGMA rekey`
to v2 db_key. Atomically writes new salt file with `MRC2` magic.
Swaps in-memory keys. Deletes the Phase 1 completion marker.

The benefit: by the time we touch the DB at all, the file layer is
already fully v2 and verified. The scary, non-resumable rekey window
is narrowed to exactly the operations that need to be in it.

### Resumability

Within Phase 1, every file self-identifies via its leading byte. A
half-migrated archive has some v1 files and some v2 files; the runtime
`decrypt()` handles both. The migration picks up by skipping any file
that already starts with `0x02`.

If Phase 1 is interrupted, the salt file is untouched (still v1, no
`MRC2` magic), but a `.migration_phase_1_complete` marker has not yet
been written. On next launch, the unlock logic detects v2 files in the
archive without the marker and prompts the user to resume the
migration before normal use. The resume derives both v1 keys (PBKDF2
path, for the still-v1 DB) and v2 keys (Argon2id path, for the
already-v2 files), and continues the walk.

Phase 2 is **not** version-byte-resumable — there's no equivalent of
the per-file version byte for SQLCipher pages. An interrupted Phase 2
is recovered by restoring from the verified ≤24h backup. The backup
check before Phase 2 is therefore **not user-overridable**: it's the
recovery path, not a nice-to-have.

### Migration steps (live order)

**Pre-flight:**
1. The current Fernet key successfully decrypts a known-good file
   (sanity check that the user's session is healthy).
2. `argon2-cffi` imports cleanly and a throwaway Argon2id derivation
   with the chosen parameters completes successfully. This catches
   missing dependency, hostile environment, and OOM together — more
   reliably than a separate RAM-math check.
3. Free disk space ≥ 2× the size of all `.eml.enc` files combined.
4. Most recent backup is ≤24h old (override allowed for Phase 1
   only — see Phase 2 below).

**Phase 1 (file layer):**
5. Acquire the v1 Fernet from the current unlocked session.
6. Derive the v2 keys. Run Argon2id on password+salt to get the
   master key, then HKDF-Expand into the v2 file subkey and v2 db
   subkey. (The v2 db_key is derived now but not used until Phase 2.)
7. Walk archive and re-encrypt every `.eml.enc`. For each file:
   - Read.
   - If first byte is `0x02`, already v2 → skip (resumability).
   - Else decrypt with v1 Fernet, encrypt with v2 GCM (version byte in
     AAD), atomically replace via temp-file + rename + directory
     fsync.
   - **On Fernet decrypt failure: halt the migration, name the
     specific file, present the failure clearly. Do not silently
     skip.** A decrypt failure means real disk damage or a bug; both
     are loud problems, not paper-overable. Collecting multiple
     failures and reporting at the end is acceptable; silent skip is
     not.
   - Stream progress every 10 files.
8. Re-encrypt IMAP credentials in the `accounts` table.
9. **Verification step.** Count: every file in the archive starts
   with `0x02`. Random sample: pick 50 files (or all if fewer),
   decrypt each with the v2 file_key, confirm the plaintext starts
   with a valid email header. Refuse to proceed to Phase 2 if any
   check fails.
10. Write the `.migration_phase_1_complete` marker file. This is the
    durable checkpoint between phases.

**Phase 2 (database layer):**
11. **Re-check backup is ≤24h old. This check is not overridable.**
    Phase 2 is not resumable; backup is the recovery path.
12. Quiesce all other DB access. The single shared `Database._connection`
    is the most dangerous concurrency surface in the codebase, and
    `PRAGMA rekey` is the most dangerous operation to share it
    against. For the duration of the rekey, no other code path may
    touch the connection. The migration takes exclusive ownership
    by setting a class-level `_migration_active` flag that every DB
    access method checks; concurrent calls raise immediately rather
    than racing the rekey.
13. `WAL checkpoint(TRUNCATE)` to flush pending writes before rekey.
14. `PRAGMA rekey = "x'<v2_db_key_hex>'"`. This rewrites every page
    of the DB in place under the new key.
15. Write the new salt file with `MRC2` magic, 32-byte salt, and
    v2-format verification token. Atomic: write to temp file in the
    same directory, `fsync` the temp file, `os.replace`, then
    `fsync` the containing directory.
16. Swap the in-memory `Encryption` keys to v2 for the rest of the
    session.
17. Delete the `.migration_phase_1_complete` marker.
18. Release the `_migration_active` flag.

### Atomic file replacement

For every replaced file (per-file in Phase 1 and the salt file in
Phase 2), the pattern is:

```python
tmp = filepath + ".v2tmp"
with open(tmp, "wb") as f:
    f.write(payload)
    f.flush()
    os.fsync(f.fileno())             # file contents durable
os.replace(tmp, filepath)            # atomic on POSIX
# Directory fsync — durability of the rename itself
dir_fd = os.open(os.path.dirname(filepath), os.O_RDONLY)
try:
    os.fsync(dir_fd)
finally:
    os.close(dir_fd)
```

The directory `fsync` is the step that's usually missed. Without it,
a power loss after the `os.replace` returns can lose the rename even
though the file contents were synced — leaving either the old file or
a stray temp file behind. With it, we never have a window where the
rename can vanish.

### Failure modes considered

| Failure | Phase | Effect | Recovery |
|---|---|---|---|
| Process killed mid-file (after fsync, before rename) | 1 | Stray `.v2tmp` alongside original. Original intact. | Resume: tmp files detected and cleaned at next migration run start. |
| Process killed during file walk | 1 | Mixed-state archive. Runtime decrypt handles both. App still launches but warns user. | Resume from where Phase 1 stopped (skip v2 files). |
| Power loss after rename but before directory fsync | 1 | On some filesystems, rename can be lost. Either old or new file visible; never partial. | Resume; whichever file is present is intact. |
| Decrypt failure on a v1 file mid-walk | 1 | Real disk damage or a bug. | Halt loud, name the file, do not skip. User decides whether to restore from backup or investigate the specific file. |
| Verification step finds a v2 file that won't decrypt | 1 | A bug in v2 encrypt (highly unlikely after testing) or disk corruption. | Halt before Phase 2; restore from backup. |
| Process killed during Phase 1 verification | 1 | All files v2 but marker not yet written. | Resume: verification re-runs and writes marker. |
| Process killed during DB rekey | 2 | DB in indeterminate state. **Not version-byte-resumable.** | Restore from the verified ≤24h backup. |
| Salt file write fails after successful rekey | 2 | DB encrypted with v2 key, salt file says v1. Next unlock fails. | Restore from backup, OR re-run migration end to end (re-derives v2 deterministically, re-attempts salt file write). |
| Salt file write succeeds, in-memory swap fails | 2 | Disk v2, memory v1. Session broken. | Restart app; fresh unlock derives v2 from salt magic; works. |
| Power loss during atomic rename of salt file | 2 | `os.replace` + dir fsync; either old or new file present. | None needed if rename was synced; otherwise behaves like "salt file write fails" above. |
| Argon2 OOM during derivation | Pre-flight | Pre-flight test catches this before any file is touched. | Lower memory parameter; re-run. |
| `argon2-cffi` import fails | Pre-flight | Migration refuses to start. Archive untouched. | Install dependency; re-run. |
| Concurrent DB access during rekey | 2 | `_migration_active` flag raises in concurrent callers. | None needed — the protection works by construction. |

### Pre-flight checks

Before any file is touched:

1. Current Fernet key decrypts a known-good file.
2. `argon2-cffi` imports AND a live derivation with the chosen
   parameters completes — catches missing dependency and OOM in one
   shot.
3. Free disk space ≥ 2× total `.eml.enc` size.
4. Most recent backup is ≤24h old (Phase 1 override allowed;
   Phase 2 not overridable — see step 11).

The previous draft included a "available RAM ≥ 2× Argon2 memory"
check; that's been dropped as redundant with the live Argon2
derivation test, which catches OOM directly and more reliably.

## Testing plan

### Test 1: Dry run on Apollo

Apollo's archive is small (a handful of test messages). Copy it
aside, run the full two-phase migration end to end on the copy with
the production code path, verify every file decrypts cleanly with v2
keys and the contents byte-match what v1 produced.

### Test 2: Interrupt mid-Phase-1 on Apollo

Kill the migration partway through the file walk. Verify:
- Some files v1, some v2.
- App launches in resume-required mode (detects v2 files without marker).
- Resume completes successfully.
- After resume, every file is v2; Phase 2 runs cleanly.
- Post-migration content byte-matches pre-migration.

### Test 3: Power-loss simulation on Apollo

Run the migration under a process killer that SIGKILLs at random
points. Verify recovery from each phase:
- Phase 1 interrupt → resume.
- Phase 2 interrupt → restore from backup, re-run.

### Test 4: Full content equivalence

After migration, walk every file and verify:
- v2 decrypt output byte-equals what v1 decrypt would have produced.
- File counts match.
- DB queries return identical results (subjects, senders, etc.).

### Test 5: Run the actual app

Stage an email, commit it, archive it, search it, export it, restore
from a backup taken before migration. Every code path that touches
encrypted data exercised.

### Test 6: Unlock-time measurement on the MacBook

Before the production migration, measure Argon2id with the proposed
parameters (m=256 MiB, t=4, p=1) on the actual M4. Target window:
~750ms–1s. If measurement is significantly under (say <400ms), raise
`time_cost`. If significantly over (say >1.5s), the UX hit is real
but probably still acceptable for a once-per-session unlock — flag
for review rather than auto-adjust.

### Test 7: Corrupted-file behavior

Plant a deliberately corrupted v1 file in the Apollo copy and run
Phase 1. Verify the migration halts, names the file, and produces a
clear error rather than skipping silently.

### Test 8: Concurrent DB access during rekey

Attempt a concurrent DB query during the simulated rekey window.
Verify the `_migration_active` flag raises cleanly rather than racing.

Only after Tests 1-8 pass on Apollo do we touch the MacBook.

## Risks and mitigations

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Bug in v2 encrypt/decrypt corrupts data | Low | High | Tests 1-7; per-file verification step before Phase 2; backup ≤24h |
| Mid-Phase-1 crash leaves archive unreadable | Very low | Medium | Per-file version byte + atomic rename + directory fsync + resumable walk |
| Phase 2 interrupt (the genuinely scary one) | Very low | High | Non-overridable backup check; Phase 2 is short; concurrent-access protection |
| Concurrent DB access during rekey | Low (single-user app) | High | `_migration_active` flag enforced at every DB entry point |
| Argon2 parameter choice too slow on slower hardware | Medium | Low | Test 6 measures actual time; tunable |
| Argon2 parameter choice too fast (under-securing) | Low | Medium | Memory at 256MiB is conservative; if hardware is fast, we land safely above the security threshold |
| HKDF expansion produces a key collision with v1 db_key | Effectively zero | High | Domain separation via `info=` strings; different KDF altogether |
| Silent skip of corrupt file leaves stranded v1 file | Eliminated by design | High | Halt-loud behavior; no silent skip |
| pyzipper exports break | None (separate keying) | N/A | Exports use per-export password, not master key |
| `argon2-cffi` regression on some Python version | Low | High | Pre-flight derivation test |
| Tests pass on Apollo, production fails on MacBook | Low | High | Backup verified ≤24h before; Phase 1 fully resumable; Phase 2 falls back to backup |

## Out of scope

Explicitly **not** part of this refactor:

- **Hardware-backed key storage** (macOS Keychain, etc.) — different
  product surface; not 1.0 territory.
- **Iteration-count tuning post-launch** — the version byte gives us
  the migration hook to bump parameters later if/when hardware moves on.
- **General fix for the shared DB connection across threads.** The
  threading concern is now handled *specifically during the rekey*
  via the `_migration_active` flag, but the broader architectural
  question (one connection vs per-thread connections) remains open
  for post-1.0. The narrow protection during the migration is a hard
  requirement; the broader fix is a latent improvement.

## Open questions for review

These were the open questions in the prior draft. Each is now
resolved by 4.8's review:

1. **Argon2id parameters.** Resolved: m=256 MiB, t=4, p=1, target
   ~750ms–1s. Tunable per Test 6.
2. **HKDF salt reuse.** Resolved: use HKDF-Expand (not full HKDF),
   no salt parameter needed; domain separation comes from `info=`.
3. **Nonce strategy.** Resolved: random 96-bit per file via
   `os.urandom(12)`. Deterministic nonces would be a trap.
4. **Version byte per file vs salt-only.** Resolved: per file, AND
   bound into GCM's AAD for authentication.
5. **`os.replace` cross-platform.** Resolved: fine for Linux/macOS;
   not a Windows-supported codebase today. Comment for future-you.
6. **Corrupt Fernet token mid-migration.** Resolved: halt loud, do
   not skip.
7. **Cipher choice (AES-256-GCM vs XChaCha20-Poly1305).** Resolved:
   stick with AES-256-GCM. Hardware-accelerated on both targets,
   consistent with SQLCipher/pyzipper, nonce-reuse risk handled by
   random 96-bit nonces.

## Estimated execution time

- Implementation: 3-4 hours (the new Encryption class methods, two-phase
  migration SSE endpoint with marker file, unlock-resume detection,
  concurrent-access protection).
- Apollo testing (Tests 1-8): 2 hours.
- MacBook migration with backup verification: 30 minutes.
- Total: a focused day's work.

## Rollback plan

If something goes wrong on the MacBook:

1. **Mid-Phase-1.** Salt file untouched. Worst case is mixed-state
   archive plus the marker not yet written. Re-run resumes from where
   it stopped. If we lose confidence entirely, restore from the
   ≤24h backup.
2. **Between phases (Phase 1 complete, Phase 2 not started).** Marker
   file is present. Unlock detects this state and prompts for
   resume — but the user can choose "restore from backup" instead.
3. **Mid-Phase-2.** Restore from the ≤24h backup. (This is exactly
   why the backup check is non-overridable at step 11.)
4. **Post-migration.** Per-file `.v2tmp` cleaned up by next migration
   pre-flight. The v1 code (Fernet + dual-PBKDF2) stays compileable
   through this refactor — we don't delete it, just stop using it
   for new encryption. Worst case is: revert the commit, restore the
   backup, app boots on v1 again.

## Acknowledgments

This plan integrates substantive review from Claude Opus 4.8. The
load-bearing argument for bundling ("KDF change forces a re-walk; the
others ride free"), the directory-fsync requirement, the
non-overridable backup check before Phase 2, the two-phase
restructure with verification checkpoint, the halt-loud-on-corruption
behavior, the GCM AAD binding, the Argon2 parameter bump to 256 MiB,
and the use of HKDF-Expand rather than full HKDF all come from that
review. Errors that remain are Opus 4.7's (and Rick's, if he agrees
with this plan).
