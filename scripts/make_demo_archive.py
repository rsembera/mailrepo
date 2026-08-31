"""
Build a fictional solo-practice archive for screenshots and demos.

    MAILREPO_DATA_DIR=/tmp/mr_demo ./venv/bin/python scripts/make_demo_archive.py

Then point the app at it:

    MAILREPO_DATA_DIR=/tmp/mr_demo mailrepo        # packaged
    MAILREPO_DATA_DIR=/tmp/mr_demo python launcher.py  # from source

Password: demo-archive-2026    (full-strength KDF unless MAILREPO_FAST_KDF=1)

Everything is fictional. All addresses use RFC-2606 reserved domains
(example.com/.org/.net), so nothing can collide with a real mailbox
even by accident. The practice, the clients, and every word of the
correspondence are invented for the screenshots on mailrepo.ca.
"""

import os
import sys
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

if not os.environ.get("MAILREPO_DATA_DIR"):
    sys.exit("Set MAILREPO_DATA_DIR to a fresh directory first.")

DATA_DIR = Path(os.environ["MAILREPO_DATA_DIR"])
if (DATA_DIR / "data").exists():
    sys.exit(f"{DATA_DIR} already holds an archive; refusing to touch it.")

PASSWORD = "demo-archive-2026"

ME = ("Alex Fontaine", "alex@fontainelaw.example.com")

# A tiny but valid single-page PDF, so attachment badges and downloads work.
MINI_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n9\n%%EOF\n"
)


def build_email(from_, to, subject, body, when, attachments=(), reply_to_id=None):
    msg = EmailMessage()
    msg["From"] = f"{from_[0]} <{from_[1]}>"
    msg["To"] = f"{to[0]} <{to[1]}>"
    msg["Subject"] = subject
    msg["Date"] = format_datetime(when)
    msg["Message-ID"] = make_msgid(domain="fontainelaw.example.com")
    if reply_to_id:
        msg["In-Reply-To"] = reply_to_id
        msg["References"] = reply_to_id
    msg.set_content(body)
    for name, data in attachments:
        msg.add_attachment(
            data, maintype="application", subtype="pdf", filename=name
        )
    return msg


def day(offset, hour=9, minute=15):
    return datetime(2026, 8, 28, hour, minute) - timedelta(days=offset)


CLIENTS = {
    "Beaumont, Marisol": [
        # (direction 'in'/'out', days-ago, subject, body, attachments)
        ("in", 62, "Commercial lease review — 4410 Wellington St",
         "Dear Mr. Fontaine,\n\nFurther to our call, please find attached the draft lease for the Wellington Street unit. The landlord's agent is pressing for signature by month's end, which strikes me as fast.\n\nCould you review the renewal and escalation clauses in particular?\n\nBest regards,\nMarisol Beaumont",
         [("Draft_Lease_4410_Wellington.pdf", MINI_PDF)]),
        ("out", 60, "Re: Commercial lease review — 4410 Wellington St",
         "Dear Ms. Beaumont,\n\nThank you — received and reviewed. Two items warrant pushback before signature:\n\n1. Clause 8.2 ties renewal rent to \"prevailing market rate\" with no arbitration mechanism. We should insist on a defined process.\n2. The escalation schedule compounds annually at 4%, which is above what comparable units in the area are taking.\n\nI've marked up the draft accordingly (attached) and can have a revised version to their agent by Thursday. There is no legal basis for their urgency; do not feel pressed.\n\nKind regards,\nAlex Fontaine",
         [("Lease_Markup_AF.pdf", MINI_PDF)]),
        ("in", 55, "Re: Commercial lease review — 4410 Wellington St",
         "Mr. Fontaine,\n\nThe agent has accepted both changes — arbitration clause in, escalation down to 2.5%. Thank you for holding firm. Please proceed to final.\n\nMarisol",
         []),
        ("out", 53, "Signature copies — Wellington lease (final)",
         "Dear Ms. Beaumont,\n\nAttached is the execution copy incorporating both amendments. Please sign where flagged and return one copy; I will hold the second with the file.\n\nMy account for this matter follows separately.\n\nKind regards,\nAlex Fontaine",
         [("Execution_Copy_Wellington.pdf", MINI_PDF), ("Invoice_2026-081.pdf", MINI_PDF)]),
    ],
    "Okafor, Daniel": [
        ("in", 34, "Updating my will after the house sale",
         "Hello Alex,\n\nNow that the sale of the Elm Street property has closed, I'd like to update my will and the powers of attorney to reflect it. My daughter Amara should be added as an alternate executor.\n\nWhat do you need from me?\n\nThanks,\nDaniel Okafor",
         []),
        ("out", 33, "Re: Updating my will after the house sale",
         "Dear Daniel,\n\nCongratulations on the closing. To update the will and POAs I'll need:\n\n- The statement of adjustments from the sale (your realtor will have it)\n- Amara's full legal name and address\n- Confirmation of whether the charitable bequest to the food bank stands\n\nI've attached a short intake sheet covering the rest. Once back, I'll have drafts to you within the week.\n\nBest,\nAlex",
         [("Estate_Update_Intake.pdf", MINI_PDF)]),
        ("in", 29, "Re: Updating my will after the house sale",
         "Alex,\n\nCompleted intake attached, plus the statement of adjustments. The food bank bequest stands — increase it to $10,000 if the estate allows.\n\nDaniel",
         [("Intake_Completed_DO.pdf", MINI_PDF), ("Statement_of_Adjustments.pdf", MINI_PDF)]),
        ("out", 24, "Draft will and POAs for your review",
         "Dear Daniel,\n\nDrafts attached: updated will, POA for property, POA for personal care. Changes are tracked against your 2022 documents. Note in particular section 4(c), where the bequest is now expressed as a fixed sum with a residue fallback, as discussed.\n\nTake your time reviewing; signing can be done here any weekday.\n\nBest,\nAlex",
         [("Draft_Will_2026.pdf", MINI_PDF), ("POA_Property_Draft.pdf", MINI_PDF)]),
    ],
    "Tremblay, Sophie": [
        ("in", 15, "Termination package — 48 hours to sign?",
         "Mr. Fontaine,\n\nI was let go this morning after nine years. HR gave me a package and said the offer expires in 48 hours. A former colleague said you helped her in a similar situation.\n\nCan you look at this quickly? Documents attached.\n\nSophie Tremblay",
         [("Termination_Letter.pdf", MINI_PDF), ("Severance_Offer.pdf", MINI_PDF)]),
        ("out", 15, "Re: Termination package — 48 hours to sign?",
         "Dear Ms. Tremblay,\n\nFirst: the 48-hour deadline is a pressure tactic, not a legal boundary — signing deadlines of that kind are routinely extended, and no reasonable employer withdraws an offer because you sought legal advice. Do not sign anything yet.\n\nOn a first read, the offer is four weeks per year of service capped at twelve; for nine years' service in your role, common-law notice would likely run considerably higher. I'd like thirty minutes by phone tomorrow morning — my assistant will send times.\n\nYou did the right thing writing before signing.\n\nKind regards,\nAlex Fontaine",
         []),
        ("in", 13, "Re: Termination package — 48 hours to sign?",
         "Thank you — that's a huge relief. Tomorrow at 9:30 works. I've asked HR for the extension in writing and they granted two weeks without argument, exactly as you predicted.\n\nSophie",
         []),
    ],
}

PRACTICE = [
    ("Accounting", "in", 45, ("Priya Sharma", "priya@sharmacpa.example.org"),
     "Q2 HST filing — confirmation",
     "Hi Alex,\n\nYour Q2 HST return was filed this morning; confirmation attached. Installment for Q3 is due September 30 — same amount as last quarter unless revenue shifted materially.\n\nBest,\nPriya",
     [("HST_Q2_Confirmation.pdf", MINI_PDF)]),
    ("Accounting", "out", 44, ("Priya Sharma", "priya@sharmacpa.example.org"),
     "Re: Q2 HST filing — confirmation",
     "Thanks Priya — received and filed away. Revenue is tracking flat, so same installment is right.\n\nAlex",
     []),
    ("Insurance", "in", 90, ("LawPro Renewals", "renewals@lawpro-demo.example.net"),
     "Professional liability renewal — action required",
     "Dear A. Fontaine,\n\nYour professional liability policy renews October 1. The renewal application is attached; premiums are unchanged for your practice profile. Please return the completed form within 30 days.\n\nLawPro Renewals Team",
     [("Renewal_Application_2026.pdf", MINI_PDF)]),
]


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    from core.database import Database
    from core.encryption import Encryption

    print("Initializing archive (full-strength KDF; ~a second)...")
    recovery = Encryption.initialize_v3(PASSWORD)
    Database.set_key(Encryption.get_db_key())
    Database.initialize()

    from web.blueprints.api.commit import _save_email_to_archive

    def folder(name, parent_id=None):
        cur = Database.execute(
            "INSERT INTO folders (name, parent_id) VALUES (?, ?)", (name, parent_id)
        )
        Database.commit()  # scripts have no request lifecycle to commit for them
        return cur.lastrowid

    clients_root = folder("Clients")
    practice_root = folder("Practice")

    total = 0
    for client, thread in CLIENTS.items():
        fid = folder(client, clients_root)
        prev_id = None
        for direction, days_ago, subject, body, atts in thread:
            other = (client.split(",")[1].strip() + " " + client.split(",")[0],
                     client.split(",")[0].lower().replace(" ", "") + "@example.com")
            frm, to = (other, ME) if direction == "in" else (ME, other)
            msg = build_email(frm, to, subject, body, day(days_ago), atts, prev_id)
            prev_id = msg["Message-ID"]
            _save_email_to_archive(msg.as_bytes(), fid, None, "demo")
            total += 1

    practice_folders = {}
    for sub, direction, days_ago, other, subject, body, atts in PRACTICE:
        fid = practice_folders.setdefault(sub, folder(sub, practice_root))
        frm, to = (other, ME) if direction == "in" else (ME, other)
        msg = build_email(frm, to, subject, body, day(days_ago), atts)
        _save_email_to_archive(msg.as_bytes(), fid, None, "demo")
        total += 1

    Database.commit()
    print(f"Done: {total} emails across Clients/{{3}} and Practice/{{2}}.")
    print(f"Password: {PASSWORD}")
    print(f"Recovery key (demo, disposable): {recovery}")


if __name__ == "__main__":
    main()
