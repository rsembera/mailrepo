"""
Code review 2026-11, finding 18: an export says how many messages it
actually holds, and names what it left out.
"""

import io
import mailbox
import zipfile

import web.blueprints.api.exports as ex
from core import Config, Database, Encryption


def _message(folder_id, name, readable=True, present=True):
    directory = Config.get_archive_path() / str(folder_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.eml.enc"
    raw = f"Message-ID: <{name}@x>\r\nSubject: {name}\r\n\r\nbody of {name}\r\n".encode()
    if present:
        path.write_bytes(Encryption.encrypt(raw) if readable else b"\x02" + b"damaged" * 20)
    cur = Database.execute(
        "INSERT INTO messages (folder_id, message_id, subject, date, filepath) VALUES (?, ?, ?, ?, ?)",
        (
            folder_id,
            f"<{name}@x>",
            name,
            1_700_000_000,
            str(path.relative_to(Config.get_base_path())),
        ),
    )
    return cur.lastrowid


def _three(initialized_app):
    Database.execute("INSERT INTO folders (id, name) VALUES (1, 'Clients')")
    ids = [
        _message(1, "good"),
        _message(1, "unreadable", readable=False),
        _message(1, "missing", present=False),
    ]
    Database.commit()
    return ids


def test_zip_reports_what_it_wrote_and_what_it_skipped(initialized_app):
    ids = _three(initialized_app)
    report = {}
    data, _name = ex._build_eml_zip(ids, report)

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert len(zf.namelist()) == 1
    assert sorted(report["skipped_ids"]) == sorted(ids[1:])
    assert ex._export_counts(report, ids) == {"email_count": 1, "skipped_count": 2}


def test_encrypted_zip_reports_the_same(initialized_app):
    ids = _three(initialized_app)
    report = {}
    ex._build_encrypted_eml_zip(ids, "Corr3ctHorse!", report)
    assert ex._export_counts(report, ids) == {"email_count": 1, "skipped_count": 2}


def test_mbox_reports_the_same(initialized_app, tmp_path):
    ids = _three(initialized_app)
    report = {}
    data, _name = ex._build_mbox(ids, "Clients", report)
    out = tmp_path / "x.mbox"
    out.write_bytes(data)
    assert len(mailbox.mbox(str(out))) == 1
    assert ex._export_counts(report, ids) == {"email_count": 1, "skipped_count": 2}


def test_a_trashed_message_counts_as_left_out(initialized_app):
    ids = _three(initialized_app)
    Database.execute("UPDATE messages SET deleted_at = 1 WHERE id = ?", (ids[0],))
    Database.commit()
    report = {}
    ex._build_eml_zip(ids, report)
    assert ex._export_counts(report, ids) == {"email_count": 0, "skipped_count": 3}


def test_a_clean_export_reports_nothing_skipped(initialized_app):
    Database.execute("INSERT INTO folders (id, name) VALUES (1, 'Clients')")
    ids = [_message(1, "a"), _message(1, "b")]
    Database.commit()
    report = {}
    ex._build_eml_zip(ids, report)
    assert ex._export_counts(report, ids) == {"email_count": 2, "skipped_count": 0}


def test_builders_still_work_without_a_report(initialized_app):
    ids = _three(initialized_app)
    data, _name = ex._build_eml_zip(ids)
    assert data
