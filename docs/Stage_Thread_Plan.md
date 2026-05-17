# MailRepo — Stage Thread Plan

Design document for a "Stage thread to…" action in the live email viewer. Not yet implemented. Drafted May 16, 2026.

---

## Motivation

The most common filing workflow in MailRepo today is a multi-step hunt:

1. Recognize that an email exchange should be filed under a particular client
2. Navigate to the Inbox, find the email, stage it to the client folder
3. Navigate to the Sent folder, find your reply, stage it to the same folder
4. Repeat for any back-and-forth in the conversation
5. Eventually go to Review and commit the batch

Steps 2–5 are mechanical work — there is no judgment being exercised at those points, just navigation and hunting. The judgment lives in step 1 (this belongs to this client) and at Review (does the staged set look right before commit). The hunting in between is friction with no compensating value.

A "Stage thread to…" action in the live email viewer should collapse steps 2–5 into one click. Click a button, pick a destination, all messages in the same conversation across the Inbox and Sent folders get staged together. Review and commit work exactly as they do today.

---

## Scope

**In scope:** threading among *live IMAP messages* — what's currently in the user's mail account, not yet archived. The use case is "I'm reading mail in MailRepo's live view, I want to file this conversation."

**Out of scope:**
- Threading among already-archived messages. Conversation-based browsing of the archive is explicitly NOT a goal; the user prefers folder-based organization for archived mail.
- Recipient-based bulk pull ("everything from Jane Smith, ever"). Different problem, different solution. Considered briefly during scoping and rejected — recipient identity is too ambiguous to automate without a review step, and threading is the actual unit of meaning for the day-to-day workflow.
- Modifications to the database schema. The archive's `messages` table does not need `in_reply_to` or `references` columns for this feature.

---

## What "thread" means here

A thread is the transitive closure of a Message-ID under the `In-Reply-To` and `References` headers (RFC 5322 §3.6.4 / RFC 5256). For a given starting message:

- Walk backwards via `In-Reply-To` and `References` to find earlier messages it replies to
- Walk forwards by searching for messages whose `In-Reply-To` points at any message already in the set
- Repeat until no new messages are found

In practice, for a typical 3–6 message exchange between two people, this is fast and deterministic. The headers don't lie — `In-Reply-To` points at exactly one message, no ambiguity about which "Jane Smith" we mean.

Subject-line matching ("Re: Re: Re: foo") is explicitly NOT used. It's heuristic, fails on edited subjects, and Gmail-style "discussion" threading is already what people complain about. RFC headers only.

---

## Where threads can live

The feature searches a small, fixed set of folders per account:

1. **The folder the message is currently in** (always)
2. **The Sent folder** for that account
3. *(Optional, deferred)* **The Inbox** if the starting message is in some other folder

Searching the entire IMAP tree is wasteful and slow. For the stated workflow — "filing today's exchange with a client" — Inbox + Sent covers the realistic cases. If a user needs to thread across additional folders, they can stage individual messages manually; the feature doesn't need to be exhaustive.

### Identifying the Sent folder

MailRepo's `core/imap.py` already has `get_special_folder(folder_type)` for Archive and Trash. It currently only knows `'archive'` and `'trash'`. The feature needs to extend it with `'sent'`, with a candidate list along these lines:

```python
sent_names = ['Sent', 'Sent Mail', '[Gmail]/Sent Mail', 'Sent Items',
              'INBOX.Sent', 'Sent Messages']
```

Case-insensitive fallback is already in place. Same pattern, same code, just an additional case.

---

## IMAP strategy

Two paths, chosen at runtime per server:

**Preferred: IMAP THREAD extension (RFC 5256).** Many servers support it. One command — `THREAD REFERENCES UTF-8 ALL` — returns the full thread tree for everything in the selected folder. We pick out the tree containing the starting Message-ID. Fast, single round-trip per folder.

**Fallback: header-walking.** For each folder in scope:
1. `SEARCH HEADER "Message-ID" "<starting-id>"` to find the starting message's UID
2. Fetch its `In-Reply-To` and `References` headers
3. For each ID found, `SEARCH HEADER "Message-ID" "<id>"` to find that message's UID (might be in a different folder, hence the per-folder loop)
4. Also `SEARCH HEADER "In-Reply-To" "<id>"` for each known ID, to find replies
5. Iterate until no new IDs surface, capped at a reasonable depth

Capability detection via the existing IMAP connection's CAPABILITY response, cached per account in process memory (no schema change needed).

### Caps and safety

- **Hard ceiling on thread size:** 100 messages. Beyond this we surface a confirmation ("This thread has N messages. Stage all?") with a "stage all" override for the rare mailing-list case.
- **Hard ceiling on header-walk depth:** 5 iterations. Pathological deeply-nested mailing-list threads would otherwise hammer the server.
- **Total search timeout:** 10 seconds for the whole find operation. If we hit it, return what we have and tell the user "found N messages; some may be missing if the search timed out."

---

## User-facing flow

1. User is in the live email viewer reading a message from a client.
2. Action bar in the viewer gets a new single-icon button (`messages-square` from Lucide, or similar — see UI section). Tooltip: "Stage thread to folder…".
3. Click → opens the existing folder picker modal (same one used by Move Email / Stage modal).
4. User picks a destination archive folder.
5. Modal switches to a "Finding messages…" state with a small spinner. Backend runs the thread search.
6. Modal updates: "Found 4 messages in this thread. Stage all 4 to `[Folder Path]`?" with Stage / Cancel buttons. If the count is high, the framing changes ("Found 47 messages — that's unusually large. Continue?").
7. User confirms → all messages get added to `state.staged` with the chosen destination. Modal closes, the staged-count badge updates, viewer stays where it was.
8. User continues working, or navigates to Review when ready to commit.

The button is single-icon to preserve the viewer's existing visual rhythm (as established when we discussed not adding a text "Export as PDF" button alongside the icon row). All explanatory text lives inside the modal.

### UI placement

In the viewer's action bar, between the existing Move Email and Export icons. Probably visually grouped with Move since both are "send this somewhere" actions.

### Disabled state

Greyed out and tooltipped with a reason when:
- The current account has no identified Sent folder (`get_special_folder('sent')` returned `None`)
- The current message has no Message-ID header (rare but possible)
- The user is viewing an archived message rather than a live one

---

## Backend API

One new endpoint:

`POST /api/threads/find`

**Request body:**
```json
{
  "account_id": 3,
  "folder": "INBOX",
  "uid": "12345"
}
```

**Response:**
```json
{
  "thread": [
    {
      "account_id": 3,
      "folder": "INBOX",
      "uid": "12340",
      "subject": "Following up on Tuesday",
      "from": "client@example.com",
      "date": "2026-05-14T10:30:00Z",
      "message_id": "<abc@example.com>"
    },
    {
      "account_id": 3,
      "folder": "[Gmail]/Sent Mail",
      "uid": "98765",
      "subject": "Re: Following up on Tuesday",
      "from": "rick@example.com",
      "date": "2026-05-14T11:15:00Z",
      "message_id": "<def@example.com>"
    }
  ],
  "truncated": false,
  "timed_out": false,
  "method": "thread_ext"
}
```

`method` is `"thread_ext"` if the server supported IMAP THREAD, `"header_walk"` for the fallback. Useful for debugging and for the unit tests, not surfaced to the user.

**No new staging endpoint needed.** Staging is client-side state — `state.staged` Map in `web/static/js/components/staging.js`. The frontend takes the response from `/api/threads/find`, iterates the items, calls the existing staging code path that already handles "add this email reference to the stage with this destination."

---

## Frontend changes

### New module: `web/static/js/components/thread-stage.js`

Single exported function:

```javascript
export async function openStageThreadModal({ accountId, folder, uid, currentMessageSubject }) {
    // 1. Open folder picker (reuse existing component)
    // 2. On destination selected: POST /api/threads/find
    // 3. Show count + confirm
    // 4. On confirm: feed results into state.staged via existing staging helpers
    // 5. Update badge, close modal
}
```

### Viewer integration

In whichever viewer module handles live email rendering (probably `web/static/js/views/mail.js` or a sibling), add the button to the action bar and wire its `onclick` to `openStageThreadModal`. Lazy-import the module, same pattern as the export modal:

```javascript
import('../components/thread-stage.js').then(m => m.openStageThreadModal({...}));
```

This keeps the bundle small on initial load — users who don't use the feature don't pay for it.

---

## Phasing

**Phase 1 — Core feature.** Backend endpoint with both IMAP THREAD and header-walk paths. `get_special_folder('sent')` extension. Viewer button. Folder picker → find → confirm → stage flow. Lands one working version.

**Phase 2 — Polish.** Truncation warning UI ("47 messages — continue?"). Disabled-state tooltips. Account-level setting for "also search Inbox when threading from other folders" if needed.

**Phase 3 — Optional refinements (probably won't need).** Allow user to deselect specific messages from the found thread before staging. Today's plan is to stage all and let the user untick during Review. If that turns out awkward in practice, revisit.

---

## Deferred / explicitly not building

- **Archive-side threading.** Conversation-grouped views of archived mail. Out of scope by design.
- **Subject-line heuristics.** Headers only.
- **Multi-account thread merging.** A thread that legitimately crosses two accounts (rare) is two separate stage operations.
- **Pre-stage thread visualization.** No tree view of the thread structure before staging. The Review screen already shows the staged set; that's the audit point.
- **Saving a "recipient preset" for repeated automated pulls.** Discussed and rejected — the Stage Thread action is per-conversation, not per-recipient. A separate "recipient pull" feature could be considered post-1.0 if the need is real, but is not part of this plan.

---

## Open questions

1. **Inbox as a default search folder when starting from elsewhere?** If the user is reading a message in a custom folder (say, an IMAP-side label), should we automatically include the Inbox in the search? Leaning yes, but it adds another round-trip. Probably make it the default and offer a toggle later if anyone complains.

2. **What happens if a thread member is already archived?** The backend searches live IMAP folders; an archived copy of the same Message-ID isn't on the IMAP server anymore. The existing `_check_duplicate(folder_id, message_id)` in `commit.py` will catch the duplicate at commit time and skip it. That's correct behavior — no special handling needed.

3. **NCF's IMAP server capability.** Rick's primary email provider is NCF (a small Ottawa community ISP). Whether their IMAP server supports the THREAD extension is unknown. Worth testing before relying on the fast path — if NCF requires the fallback, the header-walk implementation needs to be solid on day one, not as a defensive fallback.

---

## Estimated effort

One focused weekend session, ~8 hours. Breakdown:

- Backend endpoint + IMAP THREAD path: 2 hours
- Header-walk fallback: 2 hours
- `get_special_folder('sent')` + identification: 30 minutes
- Frontend modal + viewer button: 2 hours
- Edge cases and testing on Rick's actual accounts (NCF, Gmail): 1.5 hours

Could stretch to two weekends if NCF's IMAP server has surprises.

---

*Doc drafted May 16, 2026 by Rick and Claude on Apollo. Sized for a single-weekend build, post-bulk-export, pre-packaging.*
