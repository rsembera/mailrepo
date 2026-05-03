# MailRepo — Bulk Export Plan

Design document for a future bulk-export feature. Not yet implemented. To be revisited and refined when packaging work (.deb / .dmg) is complete.

---

## Motivation

Solo practitioners (lawyers, therapists, journalists) periodically need to hand correspondence to someone who is not a MailRepo user. Examples:

- A lawyer needs to give opposing counsel the relevant exchange about a matter
- A therapist is asked by a client for a copy of their email correspondence
- A journalist wants a colleague to review a thread before publication
- An audit, court order, or insurance claim requires a defensible record

The existing per-folder ZIP export gives a folder of `.eml` files, which is fine for "migrate off MailRepo" but poor for "send to a colleague to read." Per-email print works for one email at a time. There is no path for "the relevant 47 emails as a single readable PDF."

The two formats that cover the live use cases:

- **Combined PDF** for human review and defensible records
- **Encrypted ZIP of `.eml`** for handing off to other archiving / mail tools

Both go through the same selection and packaging UI; the format choice is the last step.

---

## Selection model

The user must be able to export from any of these starting points:

| Source | Already exists? | Notes |
|---|---|---|
| A single archive folder | Yes (ZIP only today) | Extend to add PDF and the toggles below |
| Folder + all subfolders | Implicit in current ZIP | Make subfolder inclusion an explicit toggle, default on |
| A search result set | No | Highest-value addition — answers "find the relevant correspondence and export it" in one motion |
| Manual batch selection of archived emails | Batch select exists for move/delete | Reuse the same selection state to feed an Export button |

The mental model: **"this is what's selected → choose a format → done."** The selection mechanism is whatever surface the user is on (folder view, search results, batch-select). The export modal is the same in every case.

---

## Export modal

A single modal opened from an Export button. Contents:

- **Format**: PDF / ZIP of `.eml` / both (radio or segmented control)
- **Include subfolders** (visible only when the source is a folder; default on, mirrors the search-scope picker convention)
- **For PDF**: include attachments? (yes-as-sibling-folder / list-only / convert-where-possible)
- **Encrypt the export** (checkbox; if on, prompt for password — see Security section)
- **Cover page** (yes/no; default yes for >1 email, no for single-email exports)

Output is always a ZIP if more than one file is produced (PDF + attachments folder, or multiple `.eml` plus optional PDF). If the result is a single PDF with no attachments, deliver as a bare PDF.

---

## PDF generation: WeasyPrint

Use **WeasyPrint** (HTML+CSS to PDF). MailRepo's sister project Minium already uses WeasyPrint for manuscript compilation, so the dependency footprint, packaging implications, and font-loading patterns are already understood. Cairo and Pango are native dependencies; Mac (.dmg) and Linux (.deb) handle them fine, which matches MailRepo's target platforms.

### Architecture

Build a single combined HTML document and let WeasyPrint render it in one pass. No per-email separate renders, no merge dance.

Structure:
- Cover page (CSS `@page :first`) — title, scope, export date, email count, MailRepo version
- Table of Contents (optional) — generated from email subjects and dates
- Email section 1 (with `break-before: page`) — header table (From/To/Date/Subject), body (sanitized HTML), attachments inline (images) or listed (other types)
- Email section 2 ... N
- Appendix references (if any) — lists "Appendix A: contract.pdf — referenced in email 3"

Then `pypdf` merges any PDF attachments onto the back to produce the final PDF.

Page breaks between emails: CSS `.email-section { break-before: page; }`.

Headers and footers via `@page` rules: page numbers (`counter(page) " of " counter(pages)`), export date, optional folder/scope label. Pattern lifted from Minium's `_build_page_css`.

### Email body rendering

Email HTML in the wild is grim — Outlook, MsoNormal, vendor CSS, weird namespaces. Three mitigations:

1. **Sanitize aggressively** before passing to WeasyPrint. Strip `<style>` blocks with MSO selectors, drop `<o:p>`, neutralise `position: absolute`, remove `<script>`. Reuse whatever sanitization already runs in the email viewer.
2. **Wrap each email body** in a constrained container with `max-width: 100%; overflow: hidden;` to prevent runaway tables.
3. **Plain-text fallback**: if WeasyPrint errors on a particular email's HTML, fall back to rendering its plain-text body with a minimal stylesheet. Better an ugly-but-readable section than a broken export.

### Attachment handling

The fork that drives most of the design complexity:

| Attachment type | Treatment |
|---|---|
| Inline images (PNG/JPG/GIF embedded in HTML) | Render in place inside email body — WeasyPrint handles `<img src="cid:...">` if `base_url` is set correctly |
| PDF attachments | Reference inline as `[Appendix A: contract.pdf]`, then **pypdf-merge** onto the back of the main PDF. Pattern borrowed from EdgeCase's `client_export.py` |
| Image attachments (not inline) | Embed as a sibling page after the email's section, scaled to fit |
| Office docs / other | List filename inline; bundle the actual file in `attachments/<email-id>/<filename>` inside the export ZIP wrapper |

### Reusable references

- **Minium** (`/Users/rick/Applications/minium/web/blueprints/compiler.py`): WeasyPrint pipeline, `@page` CSS for headers/footers/page numbers/mirror margins, `@font-face` rule generation with absolute `file://` URLs (necessary because `base_url` will point to email content, not app statics)
- **EdgeCase** (`/Users/rick/Applications/edgecase/pdf/client_export.py`): the `(elements, pdf_attachments)` two-list pattern, pypdf merging of appendix PDFs onto the back of a generated PDF

Reuse the *patterns*, not the code. EdgeCase's PDF code is tightly coupled to therapy/billing schemas; Minium's compiler has a full style system MailRepo doesn't need. The MailRepo export should be much smaller than either — one fixed template, no user-customisable styling.

---

## .eml export

Bundle decrypted `.eml` files into a ZIP. Two questions:

1. **Preserve folder structure or flatten?** Default to preserving — when exporting from "Smith → 2024" the recipient sees `Smith/2024/<emails>`. Flatten only if the source was a search result set.
2. **Filename conflicts**: emails with the same subject collide. Prefix every filename with `<YYYYMMDD>_<id>_` to guarantee uniqueness and chronological sort order.

Mostly reuses the existing per-folder ZIP code path. Low novelty.

---

## Security: encrypted exports

Exports cross MailRepo's encryption-at-rest boundary. The ZIP/PDF on disk is plaintext — that's the user's intent (they want to send it to someone) but it deserves friction.

### One-time warning

First time a user runs an export, show a modal:

> "Exports are not encrypted. The file you're about to create can be opened by anyone with access to it. You can password-protect this export by checking 'Encrypt the export.'"

Don't repeat the warning every time — that's annoying. Do remember the user's choice via a "Don't show again" checkbox.

### Password-protected ZIP

Use **`pyzipper`** for AES-256 encrypted ZIPs. Standard ZIP password protection (ZipCrypto) is broken and would be a footgun for a feature whose users actually need real protection.

Recipient-side notes (mention in the export confirmation, not just buried in docs):
- macOS: built-in Archive Utility does **not** open AES ZIPs. Recommend The Unarchiver (free, App Store).
- Windows 11: native support since 23H2.
- Linux: `unzip` 6.0+ supports AES with the `-P` flag.

### Password handling

Don't reuse the user's MailRepo master password — different threat model, different recipient. Prompt for a fresh password per export. Don't store it anywhere; the user is responsible for communicating it to the recipient out-of-band.

Show a strength meter but don't enforce a minimum length the way the master password does. The user knows their recipient's needs better than we do.

---

## Dependencies to add

- `weasyprint>=60.0` — already used in Minium, native deps already understood
- `pypdf>=4.0` — for merging attachment PDFs onto the back of the main PDF
- `pyzipper>=0.3` — AES-256 ZIP encryption

All three are pure-Python at the import level (WeasyPrint has C native deps but those are at the system layer, not Python). Packaging implications are well-understood from Minium.

---

## Open questions for v1 design

To resolve when this work is picked up:

1. **TOC in the combined PDF — yes or no?** Useful for >20 emails, noise for <5. Possibly auto-generate when count exceeds a threshold.
2. **Cover page content** — what exactly? At minimum: title (user-supplied or "MailRepo Export"), scope description, date range, email count, export date. Should we include the user's name? Practice name? Neither (let users add it themselves)?
3. **Header/footer convention** — page numbers always; what else? Folder/scope on every page is helpful for context; the title might be redundant if it's already on the cover.
4. **Verbose headers option** — full raw email headers for legal authenticity, vs the four-field summary. Probably yes-as-toggle, default off.
5. **Order** — chronological default (oldest first) feels right for correspondence review. Newest first is useful for "what just happened." Probably toggle, default chronological.
6. **Manual selection ceiling** — if a user batch-selects 5,000 emails and clicks Export, do we warn? Probably yes around 500 or 1,000.
7. **Progress UI** — a 200-email PDF export will take time. Reuse the existing SSE progress streaming pattern from import/commit.

---

## What this is NOT

- **Not a styling system.** One fixed template, possibly with two minor variations ("Compact" vs "Full"). Resist the temptation to make it customisable. Solo practitioners want it to look professional and unambiguous, not pretty.
- **Not a replacement for per-email print.** That path stays — it's the right tool for "I need this one email on paper now."
- **Not a migration tool.** The `.eml` ZIP export already covers "I'm leaving MailRepo" reasonably well. Don't add migration-specific features here.
- **Not a sharing service.** MailRepo doesn't host or transmit the exports. Output is a file on the user's disk. Sending it to the recipient is the user's job.

---

## Implementation phases

1. **Skeleton + Polish (combined)**: ✅ **Done — May 3, 2026.** See "Phase 1 status" below.
2. **Selection sources**: ✅ **Done — May 3, 2026.** Both the archive batch-select toolbar and the search-results toolbar now open the same export modal. See "Phase 2 status" below.
3. **Attachments — non-PDF types**: ✅ **Done — May 3, 2026 (late evening).** Image and other-type attachments now land in `attachments/email-N/<file>` inside a wrapper ZIP. Bare PDF output is preserved when there are no non-PDF attachments and no password.
4. **Encryption**: ✅ **Done — May 3, 2026 (late evening).** AES-256 encrypted ZIP via `pyzipper`, with a per-export password the user types into the modal. One-time first-use friction modal explains that exports are unencrypted by default and gestures at the new "Encrypt this export" checkbox.

---

## Phase 1 status — May 3, 2026

What got built in the first build, beyond the original "skeleton" scope:

**Folder source** — Right-click a folder or use the ⋯ menu → "Export…" opens the modal. Subfolder toggle exposed (default on). Backend resolves all archived emails under the folder including descendants.

**PDF generation** — WeasyPrint pipeline in `core/pdf_export.py`. Combined HTML document with cover page → email sections → appendix references → merged PDF attachments. Cover page shows scope, email count, date range, export date. Each email has a header table (From/To/Date/Subject/Folder) and the original HTML body, CSS-scoped per-email so styles don't leak across sections. PDF attachments are appended on the back via pypdf.

**CSS scoping fix (the hard problem)** — Email HTML often sets backgrounds via `<body style>` or `<style>html, body { ... }</style>`, sometimes wrapped in `@media only screen`. Naive concatenation causes one email's background to leak across the cover page and other sections. Fix: rewrite `<html>`/`<body>`/`<head>` tags as `<div class="email-shell">` (preserving attributes including inline styles), and rewrite selectors in `<style>` blocks to be prefixed with the email's scope class. Recurses into `@media`/`@supports`/`@layer`/`@container`/`@scope` so nested selectors get scoped too. Functions: `_scope_css_selectors`, `_prefix_selector`, `_sanitize_email_html`.

**WeasyPrint compatibility shims** — Two HTML-attribute behaviors WeasyPrint doesn't honor like browsers do, both mattered for real email layouts:
- `<table width="100%">` doesn't reliably fill its container. Promoted to `table[width="100%"] { width: 100% !important }` in base CSS.
- `<td align="center">` doesn't center block-level descendants like nested tables. Added `td[align="center"] > table { margin: 0 auto !important }`.

**Save to disk (not download)** — User picks a destination directory inside the modal with a custom folder picker. Backend writes the PDF directly to disk. After success, "Reveal in Finder" button (uses `open -R` on macOS, `xdg-open` on Linux). Last-used directory persists in `localStorage`. Default is `~` (home), expanded server-side via `os.path.expanduser` so it works on Mac and Linux.

**Progress UI** — SSE streaming through `/api/export/progress/<job_id>`. Bar advances during loading and rendering phases. WeasyPrint's render call has no progress callback, so when it starts, the bar switches to indeterminate mode (pulsing animation) with a clearer status message ("Composing PDF (N emails)… this can take a moment.") so 15-second stalls don't look like crashes.

**Load remote images toggle** — Default off. When off, a custom WeasyPrint `url_fetcher` returns an empty PNG for any non-`data:` URL, blocking remote image loads (faster, no tracking pixels). Inline `cid:` images aren't affected — those are converted to data URLs upstream during email parsing. The WeasyPrint logger is temporarily raised to CRITICAL during the blocked render so each blocked image doesn't spam the terminal with an ERROR line.

**Cover page** — Title, scope, email count, date range, export date. White background enforced as defense-in-depth (in case scoping ever misses something).

**Cosmetic polish** — Format card heights equalized, modal close button properly placed, file-size formatting in B/KB/MB.

What was specifically deferred from Phase 1:

- Custom export filename: auto-generated (scope + timestamp) is good enough for now. Can add an optional input field later if recipient-aware naming becomes a real need.
- TOC in the combined PDF: deferred. Auto-include for >20 emails would be a useful default if it comes up.
- Verbose headers option: deferred. Four-field summary (From/To/Date/Subject + Folder) is sufficient for current users.
- Anchor-id collision warnings: WeasyPrint logs "Anchor defined twice" for emails that reuse template `id`/`name` attributes. Cosmetic, no impact on output. Could rewrite duplicate ids to be scope-unique during sanitization if it ever matters.

---

## Phase 2 status — May 3, 2026 (evening)

Wiring only — no new backend or modal work. The export modal already supported the `messages` and `search` selection sources from Phase 1; this just exposes the entry points in the UI.

**Archive folder view (batch-select → export):** When the user has one or more archived emails selected via the row check buttons, the existing toolbar (All / Clear / Move / Trash) now also shows an "Export…" button. Clicking it opens the modal with `source: 'messages'` and a label like "12 emails from Clients/Smith" so the cover page reflects where the emails came from.

**Search results view (export results):** When a search has produced one or more results, an "Export…" button appears in the search toolbar (next to Clear). It opens the modal with `source: 'search'` and the current query / folder scope / subfolder toggle, so the export re-runs the same FTS query at export time. This is intentional — it keeps the export consistent with what the user saw in the results list, and avoids embedding thousands of message IDs in the payload for big result sets.

The Phase 1 form-state-preservation fix from earlier today applies here too — opening the destination picker no longer clobbers the user\'s format / sort / cover / remote-images choices.

What\'s deferred to Phase 3:
- Format = "both" still produces a wrapper ZIP (PDF + emails.zip) but neither output is encrypted yet.
- The `.eml ZIP` format card is enabled for "eml" exports as plain ZIP, but encrypted ZIP via pyzipper with a one-time warning modal is the Phase 3 deliverable. Until then, the existing in-modal "not encrypted" warning is shown.

---

## Phase 3 status — May 3, 2026 (late evening)

The remaining design pieces from the original plan, all in one session.

**Encryption (3a).** `pyzipper>=0.3` added as a dependency. The export modal now has an "Encrypt this export" checkbox; when checked, password + confirm fields appear with a live strength/match indicator. Submit validates locally before kicking off the export. The password is sent in the start payload but never persisted (not in `window._export`, not in localStorage, not in logs). Backend handling depends on format:
- **PDF + password** → wrapper AES-256 ZIP containing the PDF
- **eml + password** → the eml ZIP itself is AES-256 (single layer, no double-zipping)
- **both + password** → single wrapper AES-256 ZIP containing the PDF + flat `emails/<folder>/<file>.eml` entries (no nested ZIP for the recipient)

Recipient notes are surfaced in the modal\'s encryption section: macOS users need The Unarchiver (built-in Archive Utility doesn\'t support AES); Windows 11 (23H2+) and Linux unzip 6.0+ handle AES natively.

**One-time first-use warning (3b).** The first time a user opens the export modal in this browser, a friction screen explains that exports cross MailRepo\'s encryption boundary (a regular file on disk that anyone can read unless encrypted). Has a "Don\'t show again" checkbox (default on); dismissal stored under `localStorage["mailrepo.exportWarningDismissed"]`. After dismissal the modal opens straight to the form view as before. Cancel button on the warning aborts the whole flow without consuming the dismissal.

**Non-PDF attachments (3c).** The PDF render pipeline already separated PDF attachments (which get pypdf-merged onto the back) from images and other types (which were previously just listed by name). Images and other types are now packaged as sibling files inside a wrapper ZIP under `attachments/email-N/<filename>`. De-duplicates filenames per email folder. The packaging logic composes cleanly with the encryption path:
- No password, no non-PDF attachments → bare PDF (unchanged)
- No password, has non-PDF attachments → plain ZIP wrapper
- Password → encrypted ZIP wrapper (covers both cases)

The email body\'s attachments list updates its annotation when packaging: "(see attachments/email-N/)" instead of "(image attachment)" when the file is actually included alongside.

What was deferred:

- **Strict password strength enforcement.** We warn at < 8 characters but don\'t block. Solo-practitioner users know their recipient\'s needs better than a one-size-fits-all rule.
- **Custom export filename.** Still auto-generated. Could revisit if recipient-aware naming becomes a real need.
- **TOC for >20-email exports.** Deferred from Phase 1, still deferred.
- **Verbose headers option.** Deferred from Phase 1, still deferred.

---

*Doc created May 1, 2026 after architecture conversation between Rick and Claude. Phases 1–3 implemented May 3, 2026.*
