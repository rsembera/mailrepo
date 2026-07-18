# MailRepo — Known Issues

Tracked open issues. Update status here as they're diagnosed or resolved so a
future session can pick up where the last one left off.

---

## OPEN: catch-up did not fire (or silently declined) at home — 2026-07-18 morning

Rick worked on the MacBook at home the morning of Jul 18 with the pending
flag set (since Jul 17 19:29); the backlog should have shipped. It didn't.
launchd events at 09:18 and 09:54 (interval-consistent spacing) suggest the
agent *ran* and silently declined — but the catch-up's decline paths logged
nothing, so "never ran" vs "ran and declined" is indistinguishable for that
morning. The only silent-decline reasons are: pending flag absent (it
wasn't) or current SSID matching `office-networks.conf` — which at home
would mean **home and office Wi-Fi share a name** (question posed to Rick,
unanswered as of this entry). Also unexplained: the Jul 17 14:14 catch-up
attempt died 15s in with ssh I/O errors (likely lid-close or network
transition mid-transfer; the flag correctly survived).

**Narrowed 2026-07-18 (same day):** Rick confirms home and office SSIDs are
entirely different — shared-name misfire ruled out. That implies the script
did not run at all during the home window: with the flag set and a
non-matching SSID, even the un-instrumented code would have logged a
CATCHUP (or WARN) line, and there is none. Suspect is therefore the
launchd trigger itself (the 09:18/09:54 "service inactive" events were
likely dark-wake evaluations, not spawns; StartInterval fires may not have
occurred during the awake home session). Hardening applied: StartInterval
600s (was 1800) and a WatchPaths trigger on
`/Library/Preferences/SystemConfiguration` so joining a network fires the
check within moments of arriving home. Reloaded agent verified firing and
logging. The debug log from the next home session confirms or refutes.

**Instrumentation armed (2026-07-18):** every `--catchup` invocation now
writes one line to `~/Applications/mailrepo-ops/catchup-debug.log` —
`pending=SET|absent ssid=matches-conf|no-match|none` — regardless of what
it decides. The next home session settles it: `no-match` = trigger works
(morning anomaly was something else); `matches-conf` at home = shared SSID
name, switch the discriminator to gateway MAC (or a throughput probe);
no line at all = launchd isn't spawning the job. Backlog itself was cleared
manually from the office at 11:35 (see revision below), flag cleared.

---

## Slow Sentinel backup sync (~200 KB/s) — RESOLVED 2026-07-11: office network, not a MailRepo bug
## REVISED 2026-07-18 (Session 60): the throttling is CONDITIONAL, not constant

**Update 2026-07-18.** The static version of the verdict below is falsified:
a manual 285 MB catch-up ran from the office at **5.2 MB/s** (direct IPv6
path confirmed via `tailscale status`) — the same network that pinned
transfers at ~200–240 KB/s on multiple prior occasions, including a
237 KB/s probe seven days earlier. Still supported: the slowness has only
ever occurred on the office network; when present it is outbound-only and
pinned flat at ~200–240 KB/s. Now known: it is **sometimes absent**.
Leading hypothesis: load-adaptive QoS that squeezes unrecognized bulk
traffic only when the shared link is busy; the true condition is unknown.
This also retires the July 3 anomaly — the fast 19:42 wrapper run that
evening no longer requires having been off the office network. The
skip+catch-up design is unaffected (defers when throttled, costs ~nothing
when not). Possible refinement if SSID-based skipping proves troublesome:
condition on measured throughput (short probe) instead of network identity.
Read the verdict below with this revision in mind.

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
   command on the current SSID). **← IMPLEMENTED 2026-07-11 (Session 58) on the
   MacBook, with automatic catch-up**: `backup-sync.sh` skips (logs `SKIP`,
   exits 0, touches `.sentinel-pending`) when the Wi-Fi SSID matches a line in
   `~/Applications/mailrepo-ops/office-networks.conf`. A launchd agent
   (`~/Library/LaunchAgents/ca.mailrepo.sentinel-catchup.plist`, every 30 min)
   re-runs the script with `--catchup`, which exits silently unless the pending
   flag is set AND the machine is off the office network — so skipped backups
   ship within ~30 min of leaving the office, without waiting for the next
   backup to be created (MailRepo only invokes the post-backup command when a
   backup was actually made, so a no-changes home logout would never have
   triggered the catch-up). Any successful sync clears the flag. Rationale for
   not just eating the slowness: weekly *fulls* (~222 MB and growing, timing
   not user-controllable) would exceed MailRepo's 300s post-backup command
   timeout at office rates — killed incomplete at 5 min, never finishing.
   Caveats: matches Wi-Fi SSID only (wired office connection not caught);
   local iCloud backups unaffected either way.
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
