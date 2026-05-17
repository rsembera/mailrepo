# MailRepo — Flagging Plan

Design document for a per-email starring/flagging feature on archived emails. Not yet implemented. Drafted May 17, 2026.

---

## Motivation

Solo practitioners archive a lot of email and need to come back to a small subset of it quickly. The use cases:

- "This is the email I need for next week's session — let me mark it so I can find it again."
- "This thread is the source of truth for X — keep it accessible."
- "I need to revisit this once I have more information."

Today, the only way to find an archived email after the fact is to navigate to the folder and scroll, or use full-text search. Neither is fast for "I know I marked this as important — show me what I marked."

A single-color star is the right primitive for this. Solo practitioners typically have one workflow ("this matters"), not an elaborate color taxonomy. If they did, that's what folders are for. Multi-color tagging is an explicitly-rejected alternative — see "Deferred" below.

---

## Scope

**In scope:**
- Per-email flagged state, stored as a timestamp (`null` = unflagged, integer = when flagged)
- A star toggle button in the archived-email viewer's action bar
- A read-only star indicator on flagged rows in the email list
- A "Starred" pseudo-folder in the sidebar that lists all flagged emails across the archive
- Searchability: full-text search results show the star indicator on flagged hits
- Keyboard shortcut: `s` in the viewer toggles flagged state
- Theme-aware star color (uses `--color-primary` per theme)

**Out of scope:**
- Flagging live IMAP messages (Rick: "that's mail-client territory")
- IMAP `\Flagged` sync (corollary)
- Multi-color stars or labels (explicitly rejected — see Deferred)
- Per-folder filter for flagged-only ("show me only starred in this folder") — pseudo-folder covers the discovery use case; per-folder filter can be added later if needed
- Bulk flag/unflag operations — single toggle per email is enough for v1
- Auto-flagging rules ("flag everything from this sender")

---

## Data model

One new column on `messages`:

```sql
ALTER TABLE messages ADD COLUMN flagged_at INTEGER;
```

`NULL` = unflagged. Integer = Unix timestamp when the star was toggled on. Untoggling clears it back to `NULL`.

Storing a timestamp instead of a boolean costs the same disk space and adds a useful ordering axis: "show me what I flagged recently" works naturally without a separate `flagged_at` column added later. The "Starred" pseudo-folder can sort by this descending.

The schema change should NOT be a migration — MailRepo hasn't shipped yet and the established practice is direct schema edits.

---

## Backend

### New / changed endpoints

**`PATCH /api/messages/<int:message_id>/flag`** (new)

Body: `{ "flagged": true }` or `{ "flagged": false }`

Sets or clears `flagged_at` for the given message. Returns `{ "flagged_at": 1747487123 }` or `{ "flagged_at": null }`.

This is its own endpoint rather than reusing the existing `PATCH /api/messages/<id>` (which currently handles folder moves) because the operations are conceptually distinct and authorization rules may diverge later. Small endpoint, separate concern.

**`GET /api/messages/flagged`** (new)

Returns all flagged messages across the archive, ordered by `flagged_at DESC`:

```json
{
  "emails": [
    {
      "id": 1710,
      "folder_id": 83,
      "folder_name": "Testing",
      "folder_path": "06 Personal > Testing",
      "subject": "(no subject)",
      "sender": "Swarna Sriraman <swarna.sriraman@gmail.com>",
      "date": 1747487100,
      "flagged_at": 1747487123
    },
    ...
  ]
}
```

The shape mirrors `GET /api/trash/emails` so the same frontend list-rendering code can be reused with minor adjustments.

### Endpoints that need updating

These need to include `flagged_at` in their response so the frontend can render the star indicator:

- `GET /api/folders/<folder_id>/emails` (folder contents)
- `GET /api/folders/<folder_id>/emails/<message_id>` (single email view)
- `GET /api/search` (search results)
- `GET /api/trash/emails` (so we know if a trashed email was previously flagged — display only, no functional change)

Each just adds `flagged_at` to its SELECT and to the returned dict.

---

## Frontend

### Star toggle in viewer

A new icon button in the email-viewer action bar (`web/templates/main/index.html`), placed near the other viewer actions. Lucide icon: `star` (empty outline when unflagged, filled when flagged).

Click handler:
- POSTs to `/api/messages/<id>/flag`
- Updates local state on success (the email's `flagged_at` field in whatever in-memory list it lives in)
- Re-renders the email list IF the list is visible behind the viewer (it usually is)
- Updates the icon's appearance (empty ↔ filled)

The button is shown only when `context.type === 'folder'` (archived) — never for live IMAP context (`'account'`) or import preview (`'import'`).

Keyboard shortcut: `s` while the viewer is open and an archived email is loaded.

### Star indicator in email list rows

A read-only star icon prepended to the subject (or next to the date — UI decision deferred to implementation, depending on what looks cleanest) on rows where `flagged_at` is not null.

Rows where `flagged_at` is null show NOTHING — no empty star, no placeholder. Avoids visual noise on the 99% of unflagged rows.

The indicator is non-interactive. To toggle, the user opens the email and uses the viewer's star button. (This is a deliberate choice — see "UX rationale" below.)

### "Starred" pseudo-folder

A new entry in the sidebar near "Trash" (which already exists as a pseudo-folder). Lucide icon: `star`. Label: "Starred". Optional count badge showing total flagged count.

Clicking it renders a view similar to the Trash view: list of all flagged emails across the archive, sorted by `flagged_at DESC` (most-recently-flagged first), with the folder path visible on each row so the user knows where in the archive the email actually lives.

Clicking an email opens the standard archive viewer.

### CSS / theming

A new variable per theme:

```css
:root, [data-theme="pine"] { --color-star: var(--color-primary); }
[data-theme="graphite"]   { --color-star: var(--color-primary); }
... etc.
```

Default everywhere is `--color-primary`. If any theme reads poorly with the primary color as a star (Graphite's gray, e.g.), that theme can override to a tuned value:

```css
[data-theme="graphite"] { --color-star: #C9A227; }  /* if needed */
```

Decision on per-theme overrides deferred until the feature can be seen in each theme.

---

## UX rationale

### Why the toggle lives in the viewer, not the list rows

Three reasons:
1. **Visual noise.** Putting a star (even an empty outline) on every list row clutters the layout on 99% of rows where nothing is flagged.
2. **Decision context.** Users typically flag an email after reading it, not while scanning a list. The viewer is where the relevant judgment happens.
3. **Separation of concerns.** The list row's job is "show me what I have." The viewer's job is "let me act on this one." Keeping the toggle in the viewer respects that split.

The list still needs to SHOW flagged status (so users can see what they've flagged without opening each email) — that's the read-only indicator's job.

### Why "Starred" is a pseudo-folder, not a per-folder filter

A pseudo-folder answers "what have I flagged?" at a glance from anywhere in the app. A per-folder filter answers "what have I flagged in *this* folder?" which is a narrower question that users rarely actually ask.

If the per-folder filter turns out to be needed, it can be added later. The pseudo-folder is the discoverable starting point.

### Why a single color, not multiple

Solo practitioners have one workflow: "this matters." A multi-color system (Apple Mail flags, Gmail multi-stars) is for users with elaborate triage taxonomies — which solo practitioners typically don't have, and which is what folders are for in this app.

Adding multi-color later if real demand emerges is straightforward: add a `flag_color TEXT` column, default `'primary'`, expose a color picker in the viewer. The single-color v1 doesn't preclude this.

### Why timestamps, not booleans

Storing `flagged_at INTEGER` instead of `flagged BOOLEAN` costs the same and gains a sortable ordering axis for free. The pseudo-folder sorts by `flagged_at DESC` (most recently flagged first), which is the natural reading order. No retrofit needed if Rick later wants "flagged in the last week" or similar.

---

## Open questions

1. **Star indicator placement in list rows.** Before the subject (Apple Mail style) vs. next to the date (Outlook style). Resolve during implementation by trying both — depends on the existing email-list visual rhythm.

2. **Should trashed-but-flagged emails appear in the Starred pseudo-folder?** Probably no — trash is trash. The flag survives in the DB so if the email is restored, it's still starred, but the Starred view only shows non-trashed.

3. **Search result rendering: does the star indicator show?** Probably yes — adds two characters of UI complexity for the same payoff as the folder view. Just include `flagged_at` in the search response and let the renderer handle it.

4. **Keyboard shortcut conflict.** Need to verify `s` isn't already bound to something in the viewer. Most likely not but worth a quick grep before claiming the shortcut.

---

## Deferred / explicitly not building

- **IMAP `\Flagged` sync.** Out of scope; that's mail-client territory.
- **Multi-color stars or labels.** Explicitly rejected. Solo-practitioner workflow doesn't need it; folders are the organizational primitive.
- **Bulk flag/unflag.** Single toggle per email is enough for v1.
- **Auto-flagging rules.** Out of scope.
- **Per-folder "show only flagged" filter.** The pseudo-folder covers the discovery use case. Add the per-folder filter only if real use shows a need.
- **Flagged-count badge on every parent folder.** Visually noisy. The pseudo-folder is the single discovery surface.

---

## Estimated effort

One focused session, ~6-8 hours. Breakdown:

- Schema change + endpoint updates (folder/email/search responses include `flagged_at`): 1.5 hours
- New endpoints (`PATCH /flag`, `GET /flagged`): 1 hour
- Viewer star button + theme CSS variable: 1.5 hours
- Email-list star indicator: 1 hour
- "Starred" pseudo-folder view: 2 hours
- Keyboard shortcut + edge cases: 30 minutes
- Testing across all five themes: 30 minutes

---

*Doc drafted May 17, 2026 by Rick and Claude on the MacBook. Sized for a single-session build, after prev/next in archive viewer, before 1.0.*
