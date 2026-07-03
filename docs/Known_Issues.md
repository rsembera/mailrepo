# MailRepo — Known Issues

Tracked open issues. Update status here as they're diagnosed or resolved so a
future session can pick up where the last one left off.

---

## Intermittent slow Sentinel backup sync (~204 KB/s) — OPEN, cause unpinned

**Symptom.** The post-backup `rsync` to Sentinel occasionally crawls at
~204 KB/s (~60s for the ~12 MB incremental) instead of its normal ~3–4 MB/s.
Observed 2026-06-26 (204,513 B/s) and 2026-07-03 (204,046 B/s) — both evenings,
both landing on almost exactly the same rate, which points to something
*systematic when it happens* rather than random congestion. It only surfaces at
backup time, and it blocks the logout flow while it runs.

**Ruled out** (2026-07-03 — every isolated retest ran fast, 3–4.6 MB/s, minutes
after the slow backup):

- **Office / home internet.** Direct rsync to Sentinel does 3–4.6 MB/s.
- **rsync directory scan.** Dry-run of the full 147-file / 6.34 GB backup
  directory: 2 seconds.
- **The transport itself.** Single-file transfer from the real iCloud source: fast.
- **Process QoS.** The MailRepo server runs at normal priority (nice 0, launched
  from a shell), so a spawned rsync isn't throttled by inheritance; and a forced
  background-QoS transfer (`taskpolicy -b`) only fell to ~1.8 MB/s — nowhere near
  204 KB/s.
- **iCloud write / rsync race.** Faithfully replicated (write 12 MB into the
  iCloud backup folder, then immediately rsync it from there to Sentinel):
  4.6 MB/s. iCloud's `bird` uploader *was* active during the slow 18:11 window
  per the unified log, but its upload bursts were only seconds long — too short
  to account for a 60-second crawl.

**Status.** Could not reproduce on demand. Genuinely transient, tied to
conditions at the specific moments the real backups ran. Not worth chasing
further blind — instrumented instead (below).

**Instrumentation (the black box).** A wrapper now runs the sync and logs the
outcome, capturing a full snapshot only when a *real* transfer comes in slow:

- **Script:** `~/Applications/mailrepo-ops/backup-sync.sh` — kept outside the repo
  because it holds machine-specific paths (iCloud source, `rick@sentinel`). Wired
  in as MailRepo's post-backup command, replacing the raw rsync. Terminal output
  is identical to before.
- **Log:** `~/Applications/mailrepo-ops/backup-sync.log`.
- Normal run → one line: `OK rate=… sent=… elapsed=…`, or `OK nothing substantial
  to send` for a no-op re-sync.
- Slow run (a real ≥1 MB send under 1 MB/s) → a timestamped snapshot: rsync
  summary, network interface, iCloud (`bird`) upload activity, a per-process
  network sample (`nettop`), top CPU processes, and — the key datum — **an
  independent 12 MB throughput probe to Sentinel run right after the sync.**

**Next step when it recurs.** Read the `SLOW` entry in the log. The probe result
splits it immediately: if the probe is *also* slow, the bottleneck is the
link/Sentinel; if the probe is *fast*, it's the backup flow specifically. The
`bird` and `nettop` lines show what else was using the uplink at that instant.
Diagnose from that evidence rather than re-running fast tests after the fact.
