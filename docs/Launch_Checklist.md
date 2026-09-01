# Launch Checklist — MailRepo 1.0.0

State as of Aug 31, 8:30 p.m. Everything below is mechanical; the
recipes are proven (the .dmg chain has run four times, the .deb three).
Any executor — Fable, Opus, or Rick with coffee — follows this top to
bottom. Do not reorder the GO-LIVE section.

## A. On Apollo

1. `git pull` (must land 2c6080c search fix + 80f4bcc README).
2. Screenshots from the demo archive (rebuild it if /tmp was cleared:
   `MAILREPO_DATA_DIR=/tmp/mr_demo MAILREPO_STATE_DIR=/tmp/mr_demo_state ./venv/bin/python scripts/make_demo_archive.py`
   then same env + `./venv/bin/python launcher.py`; password
   `demo-archive-2026`). Shots: browse view w/ Clients sidebar; the
   Tremblay reply open; search for `lease`. Save as
   `docs/screenshots/{browse,viewer,search}.png`, commit, push.
3. Rebuild .deb: `bash packaging/build_deb.sh 1.0.0`
4. `sha256sum packaging/deb/mailrepo_1.0.0_amd64.deb` → record as DEB_SHA.
5. Replace the release asset:
   `gh release upload v1.0.0 packaging/deb/mailrepo_1.0.0_amd64.deb --clobber`
6. Optional quick check: `sudo apt reinstall ./packaging/deb/...` and
   confirm the About modal shows "Opus 4.5–4.8 and Fable 5" + SVG logo,
   and search for "-" returns no error.

## B. On the MacBook

7. `git pull` (brings screenshots).
8. .dmg round five — the proven chain verbatim from
   docs/Mac_Packaging_Guide.md ("now the canonical release recipe"),
   or rerun the block in /tmp/release_run4.log's generating command.
   Requires Rick present for possible keychain prompts.
9. `shasum -a 256 dist/MailRepo-1.0.0.dmg` → record as DMG_SHA.
10. `gh release upload v1.0.0 dist/MailRepo-1.0.0.dmg --clobber`

## C. Hash ripple (MacBook)

Replace OLD hashes everywhere with the new DMG_SHA / DEB_SHA:
- OLD dmg: f90dca459694fa8ff591299bb87e6bc15d574054600e6bd6d8a1407e00e6174a
- OLD deb: f2c82cb26747a419cec448f8c3f915f27a060304fd8480a69b1fdda5aafe3d82

11. `gh release edit v1.0.0 --notes-file` with updated notes (regenerate
    from the current notes via `gh release view v1.0.0 --json body`,
    substitute both hashes).
12. README.md download table: substitute both hashes; also add the
    screenshots under the `<!-- SCREENSHOTS -->` marker and the
    attribution line (see D). Commit + push.
13. Website repo (Apollo holds it, but edits can be committed from
    either side of the pull): download.html — substitute both hashes.

## D. Attribution (Rick-approved wording; final polish his)

- README, bottom (before License): "MailRepo was designed by Richard
  Sembera and coded with Anthropic's Claude — Opus 4.5–4.8 and
  Fable 5."
- Website footer or why.html: same sentence.
- (About modal already updated in-app.)

## E. GO-LIVE — order is load-bearing

14. Final read of README on GitHub's renderer (private repo view).
15. `gh repo edit rsembera/mailrepo --visibility public --accept-visibility-change-consequences`
16. Verify anonymously (curl, no auth): release page 200, both
    download URLs 200.
17. Website: on Apollo, `git push sentinel main` (or the repo's
    documented deploy remote) → verify https://mailrepo.ca serves the
    new landing page, download links resolve, favicon updated.
18. Smoke the funnel once as a stranger: mailrepo.ca → download .dmg →
    hash matches DMG_SHA.

## F. Announcements — Tuesday morning, NOT tonight

Staggered, Rick present for comments: Show HN first, then r/selfhosted,
r/privacy, FB. Drafts to be written fresh; do not announce before E.16
and E.17 both verify.

## Hard rules for any executor

- Never push the website before the repo is public (dead links).
- Never edit hashes by hand-typing; copy from the shasum output.
- Anything unexpected: stop, write down what happened, don't improvise
  around a failed signing or notarization step.
