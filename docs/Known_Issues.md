# MailRepo — Known Issues

Tracked open issues. Update status here as they're diagnosed or resolved so a
future session can pick up where the last one left off.

---

## RESOLVED 2026-08-08 (Session 65): launchd catch-up had NEVER worked — TCC blocked iCloud Drive

iCloud Drive is TCC-protected; launchd-spawned bash had no grant, so the
catch-up's rsync saw an empty source and "succeeded" shipping nothing
(sent=29 bytes) — 199 times out of 201 since 2026-07-11. Fixed: /bin/bash
granted Full Disk Access (manual, System Settings); wrapper now refuses
loudly (ERROR, flag kept, exit 1) whenever the source reads empty, so the
failure class is permanently un-silent. Verified: agent shipped the
deferred 224.5 MB Aug 7 full at 5.8 MB/s in 40s — its first real
delivery. If this Mac is ever rebuilt, re-grant FDA to /bin/bash or the
guard will start firing. Parked: occasional WatchPaths bursts (~10s
apart) from SystemConfiguration churn; harmless under the lock.

---

## CORRECTION 2026-07-24 evening (Session 63): the morning tether sync SUCCEEDED; tether shaping is NOT confirmed

Sentinel-side ctime proves `full_2026-07-24_101936.zip` (223.4 MB) landed
complete at **10:25:38** — over the tether. MailRepo's `timeout=300`
killed only the spawned *shell* at 10:24:36; the orphaned rsync/ssh kept
transferring and finished 62s later. So: (1) MailRepo's UI reported a
failed sync for a transfer that succeeded — real finding, see backlog
note below; (2) the "killed as predicted" claim below is FALSE; (3) the
"221 KB/s pinned" measurement divided bytes by wall time that included a
slow first phase — true average was 617 KB/s with ~5x acceleration after
minute ~3.5 (TCP/ssh ramp over high-RTT cellular is a candidate; shaping
is neither confirmed nor excluded); (4) the pending flag set manually at
10:26 was for an already-delivered full, causing the afternoon's futile
retry WARNs on flapping in-transit networks (some re-armed by
overlapping zombie runs hitting the new touch-on-failure path).
The constrained-tether skip REMAINS, on corrected grounds: metered
cellular data, and the 300s-timeout/orphan mismatch means big tether
syncs report failure in MailRepo's UI even when they succeed.
waverley361's acquittal stands (directly measured fast, repeatedly).
MailRepo backlog item — DONE 2026-07-24 evening (cec22a6):
run_shell_command owns the process group and kills it wholesale on
timeout, reporting truthfully. Ops wrapper stripped to one rule (defer
on constrained links), with PID lock and pre-armed pending flag; all
office/gateway machinery removed.

## UPDATE 2026-07-24 (Session 62): carrier tether shaping confirmed; constrained-link skip added; office Wi-Fi still unjudged

The pinned ~220 KB/s outbound ceiling was measured live on an iPhone
tether over a **confirmed direct IPv6 Tailscale path** (DERP hypothesis
tested and killed) — carrier hotspot traffic management, not the data
plan. The wrapper now skips (and sets the pending flag) on any
`constrained` default-route interface (macOS's own hotspot/expensive-link
marker); MAC matching is impossible on tethers anyway (CLAT gateway
192.0.0.1, NOARP). Failed syncs now also set the pending flag. Because of
the `<redacted>` bug, no July slow event has a verified network identity;
Rick believes he was not tethered for them, so the office remains a
suspect — **probe `waverley361`'s throughput before adding it to
`office-gateways.conf`**.

**CLOSED 2026-07-24 evening: waverley361 ACQUITTED.** Every verified
measurement on it is fast: 285 MB @ 5.2 MB/s (Jul 18), 223 MB full via
catch-up (Jul 24 ~12:16, minutes after leaving the tether), and two
incrementals @ ~5 MB/s (Jul 24 17:44/17:50). `office-gateways.conf`
stays intentionally EMPTY; the constrained-tether check is the only
deferral rule. The July slow events' network identity is permanently
unknowable (the `<redacted>` bug), but the tether is the only network
ever verified slow. If a slow sync recurs, the logs now capture rate and
network verdict — reopen then.

---

## ROOT-CAUSED & FIXED 2026-07-20: catch-up never fired away from the office — the SSID conf contained the literal string `<redacted>`

**Root cause (Session 61).** Modern macOS redacts Wi-Fi SSIDs from CLI tools
lacking location permission: `ipconfig getsummary` (and `system_profiler`)
return the 10-character placeholder `<redacted>` instead of the network
name. The Jul 11 shell-side "capture the office SSID" therefore wrote the
placeholder into `office-networks.conf` (11 bytes — 10 chars + newline),
and every subsequent runtime read returned the same placeholder on every
network. Result: `matches-conf` everywhere, i.e. **skip-everywhere since
Jul 11** — the worst inversion, silently deferring all Sentinel syncs.
Confirmed empirically: 490 of 496 debug-log invocations said
`matches-conf` across office AND home (SSIDs `waverley361` vs
`NCF_1639098` — entirely different); the only exceptions were
`ssid=none` moments (Wi-Fi unassociated) and one conf-moved artifact.

This retires the Jul 18 "trigger mystery" entirely: the launchd trigger
was never broken. The Sat-morning home declines were *real* declines
against the placeholder; the sole spontaneous catch-up attempt
(Jul 17 14:14) fired precisely because Wi-Fi was unassociated in transit
— guaranteed to fail with I/O errors. Every anomaly, one cause. The
StartInterval-600s + WatchPaths hardening from Jul 18 was aimed at a
non-existent launchd fault but is harmless and kept.

**Fix (per Rick: skip ONLY at 361 Waverley, sync everywhere else):**
discriminate by **default-gateway MAC address** instead of SSID — no
permissions, no redaction, identifies the actual router. `backup-sync.sh`
now skips only when the current gateway MAC matches a line in
`office-gateways.conf`, and **fails open** (syncs) on no-conf, unreadable
gateway, or no match. Debug log now records `gw=` states. New
`--mark-office` mode captures the current gateway into the conf.
**Pending one action: run `backup-sync.sh --mark-office` once at the
office.** Until then the wrapper syncs everywhere (worst case: an
occasionally-throttled office sync — safe direction). Gateway-MAC also
covers a wired office connection to the same router, retiring the old
Wi-Fi-only caveat.

---

## Historical: the Jul 18 investigation notes (superseded by the root cause above)

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
