# MailRepo — Known Issues

Tracked open issues. Update status here as they're diagnosed or resolved so a
future session can pick up where the last one left off.

---

## Slow Sentinel backup sync (~200 KB/s) — RESOLVED 2026-07-11: office network, not a MailRepo bug

**Verdict.** Rick's counselling office rate-limits outbound VPN/tunnel traffic.
The backup `rsync` to Sentinel runs over Tailscale (`sentinel` resolves to the
Tailscale IP `100.116.129.95`), so at the office it gets shaped to ~200 KB/s
(~60s for the ~12 MB incremental). At home it runs at 20–29 MB/s. **Nothing to
fix in MailRepo. Do not spend more time on this.**

**The evidence that settled it — an asymmetry test:**

- **Download from Sentinel: 16.8 MB/s. Upload to Sentinel: ~216 KB/s.** Same
  tunnel, same route, same MTU, same moment — 80× slower in one direction only.
  No packet-size, MTU, routing, or relay problem can do that; only a shaper
  acting on outbound traffic can.
- Raw `ssh … 'cat > /dev/null'` (no rsync, no iCloud, no MailRepo) is equally
  slow → the app is not involved at any level.
- Speedtest at the office: 351 / 52 Mbps, 7ms, 0% loss → the internet connection
  is fine. Ordinary TCP/443 is untouched; it's the WireGuard-style UDP (port
  41641) to an unrecognised peer that gets shaped.
- The rate is *pinned*, not noisy: 204,513 / 204,046 / 211,561 / 216,134 B/s
  across weeks. A flat ceiling is a rate limiter, not congestion.
- Only ever at the office; never at home.

**Dead ends — already chased and disproven. Don't repeat these:**

- **Office internet being "slow"** — no; Speedtest is 351/52 Mbps.
- **rsync scanning the growing backup directory** — no; a full-dir dry-run of
  147 files / 6.34 GB takes 2 seconds.
- **The iCloud write → rsync race** — no; faithfully replicated at 4.6 MB/s.
- **Process QoS / the app spawning a throttled child** — no; the server runs at
  normal priority, and even a forced `taskpolicy -b` transfer only fell to
  ~1.8 MB/s, nowhere near 200 KB/s.
- **Tailscale falling back to a DERP relay** — no; `tailscale status` shows a
  **direct** IPv6 path at ~50ms, and it's still slow.
- **MTU / PMTU black hole** — no. Two wrong turns here, recorded so they aren't
  repeated: (1) the Tailscale interface is **`utun8`**, not `utun0`; (2) it was
  already at the correct 1280, and forcing it to 1200 changed throughput *not at
  all*. The "drop line" in a ping-size probe simply tracks the interface MTU —
  that's normal behaviour, not a black hole.
  **If utun8 is still at 1200, set it back: `sudo ifconfig utun8 mtu 1280`.**
  (Any stray change to `utun0` is harmless — those transient utun interfaces are
  recreated by macOS and don't persist.)

**Options at the office (all optional — none is a bug fix):**

1. **Accept it.** The backup completes in ~60s and the Sentinel copy is a
   backup-of-a-backup (primaries live in iCloud Drive). This is the sane default.
2. **Try Tailscale over TCP/443**, so the traffic looks like ordinary HTTPS that
   shapers ignore. Not guaranteed; would need its own session.
3. **Skip the Sentinel sync on the office network** (condition the post-backup
   command on the current SSID).
4. Ask office IT to stop shaping outbound UDP — the correct fix, rarely available
   in a leased space.

**Not affected:** Google Meet and similar. The shaper targets unrecognised tunnel
traffic, not standard services — Speedtest pushed 52 Mbps up through the same
network, and Meet is well-known traffic on standard ports.

---

## Instrumentation: backup-sync black box (retained)

The wrapper that caught this is still in place and still useful for any future
backup-throughput question.

- **Script:** `~/Applications/mailrepo-ops/backup-sync.sh` — outside the repo
  (machine-specific paths). Wired in as MailRepo's post-backup command; terminal
  output is identical to the raw rsync.
- **Log:** `~/Applications/mailrepo-ops/backup-sync.log`.
- Normal run → one line: `OK rate=… sent=… elapsed=…`.
- A real (≥1 MB) transfer under 1 MB/s → a timestamped diagnostic snapshot:
  rsync summary, interface, iCloud (`bird`) activity, `nettop`, top CPU, and an
  **independent 12 MB throughput probe to Sentinel** run right after the sync.
- **Reading it:** if the probe is *also* slow, it's the link/Sentinel path — i.e.
  this issue (you're at the office). If the probe is *fast*, it's the backup flow
  specifically — that would be new and worth investigating.
