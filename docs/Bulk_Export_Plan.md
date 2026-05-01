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

## Implementation phases (when picked up)

Roughly:

1. **Skeleton**: Export button on folder view, modal with format-only choice, PDF and ZIP formats both producing minimal output. Use the existing folder-as-source path. No subfolder toggle, no encryption, no attachments-in-PDF beyond inline listing.
2. **Selection sources**: Wire up the search-result-set source and the batch-selected-emails source to the same modal.
3. **Attachments**: Inline images, pypdf-appended PDFs, sibling folder for other types.
4. **Polish**: Cover page, TOC, headers/footers, encryption, progress UI, one-time warning.

Each phase is a coherent shippable increment. Don't wait until phase 4 to ship something useful.

---

*Doc created May 1, 2026 after architecture conversation between Rick and Claude. Refinement pending.*
