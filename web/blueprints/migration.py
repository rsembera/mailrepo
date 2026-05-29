"""
MailRepo - Crypto migration blueprint.

SSE endpoints for the two-phase v1 -> v2 crypto migration. The actual
migration logic lives in core/migration.py; this blueprint is the
HTTP/SSE wrapper that streams progress to the browser.

Flow:
  1. GET  /migration/api/state              - state + preflight checks.
  2. POST /migration/api/start-phase-1      - validate password, stash in session.
  3. GET  /migration/api/phase-1-progress   - SSE stream of Phase 1.
  4. POST /migration/api/start-phase-2      - validate Phase 2 preconditions.
  5. GET  /migration/api/phase-2-progress   - SSE stream of Phase 2.

The split into two endpoints per phase (POST to authorize, GET to stream)
mirrors the change_password_progress pattern. The password is stashed in
the session between the POST and the GET so it survives just long enough
for the SSE endpoint to consume it, then is cleared immediately on read.

Phase 2 does NOT need the password again: by Phase 1 completion the v2
keys are already loaded in memory on the Encryption class, and Phase 2
just uses them.
"""

import json
import queue
import threading

from flask import Blueprint, Response, request, session, jsonify

from core import Encryption, InvalidPasswordError
from core.migration import Migration, MigrationError, MigrationCorruptionError
from utils.log import get_logger

log = get_logger(__name__)

migration_bp = Blueprint("migration", __name__, url_prefix="/migration")


def _require_auth():
    """Returns a Flask error response if not authenticated, else None."""
    if not session.get("authenticated"):
        return jsonify({"error": "Not authenticated"}), 401
    return None


# ============================================================
# STATE + PREFLIGHT
# ============================================================

@migration_bp.route("/api/state", methods=["GET"])
def get_state():
    """Returns current migration state and preflight checks.

    The frontend uses this to decide whether to show the migration banner
    and what content to show in the migration modal.
    """
    err = _require_auth()
    if err:
        return err

    try:
        state = Migration.state()
    except Exception as e:
        return jsonify({"error": f"state detection failed: {e}"}), 500

    # Phase 1 preflight is overridable for backup-age (Phase 2 has its
    # own non-overridable check). We pass allow_stale_backup=True here so
    # the UI can show the user the actual backup age and offer to proceed.
    try:
        preflight = Migration.run_preflight(allow_stale_backup=True)
    except Exception as e:
        return jsonify({"error": f"preflight failed: {e}"}), 500

    return jsonify({
        "state": state,
        "preflight": preflight,
    })


# ============================================================
# PHASE 1: start (POST) + progress (GET, SSE)
# ============================================================

@migration_bp.route("/api/start-phase-1", methods=["POST"])
def start_phase_1():
    """Validate password and authorize Phase 1.

    Stashes the password in the session for the immediately-following
    SSE endpoint to consume. The password is needed to derive the v2
    keys via Argon2id (which is the only place the password is used in
    Phase 1; once v2 keys are derived they live in memory).
    """
    err = _require_auth()
    if err:
        return err

    data = request.get_json() or {}
    password = data.get("password", "")
    if not password:
        return jsonify({"error": "Password required"}), 400

    # Verify the password by attempting unlock. This is idempotent for v1
    # archives that are already unlocked (it re-derives the same keys).
    try:
        Encryption.unlock(password)
    except InvalidPasswordError:
        return jsonify({"error": "Incorrect password"}), 400
    except Exception as e:
        return jsonify({"error": f"Unlock failed: {e}"}), 400

    # Refuse if migration isn\'t needed.
    if not Migration.is_needed():
        return jsonify({
            "error": "Migration is not needed (archive is already on v2)"
        }), 400

    session["migration_phase_1_password"] = password
    session.modified = True
    return jsonify({"success": True})


def _stream_migration(worker_func):
    """Bridge a sync progress_cb into an SSE event stream.

    Migration.run_phase_1/run_phase_2 take a synchronous progress_cb that\'s
    called inline as the work proceeds. To stream those events to the browser
    via SSE, we run the migration in a background thread and feed events
    through a queue that the generator consumes.

    worker_func is a callable taking (cb) -> result; it should call cb(event)
    for each progress event and return the final result (or raise).
    """
    q: queue.Queue = queue.Queue()
    SENTINEL = object()

    def cb(event):
        q.put(event)

    def worker():
        try:
            result = worker_func(cb)
            q.put({"status": "success", "result": result})
        except MigrationCorruptionError as e:
            q.put({
                "status": "error",
                "kind": "corruption",
                "filepath": e.filepath,
                "message": str(e),
            })
        except MigrationError as e:
            q.put({"status": "error", "message": str(e)})
        except Exception as e:
            log.exception("Unexpected migration error")
            q.put({
                "status": "error",
                "kind": "unexpected",
                "message": f"{type(e).__name__}: {e}",
            })
        finally:
            q.put(SENTINEL)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    while True:
        event = q.get()
        if event is SENTINEL:
            break
        yield f"data: {json.dumps(event)}\n\n"
    t.join(timeout=1.0)


@migration_bp.route("/api/phase-1-progress")
def phase_1_progress():
    """SSE stream of Phase 1 progress."""
    err = _require_auth()
    if err:
        return err

    # Pop the password from the session. It must have been set by
    # start_phase_1 immediately before this request.
    password = session.pop("migration_phase_1_password", None)
    session.modified = True

    def generate():
        if not password:
            yield f"data: {json.dumps({'status': 'error', 'message': 'No password staged. Re-authorize via /api/start-phase-1.'})}\n\n"
            return
        yield from _stream_migration(
            lambda cb: Migration.run_phase_1(password, progress_cb=cb)
        )

    return Response(generate(), mimetype="text/event-stream")


# ============================================================
# PHASE 2: start (POST) + progress (GET, SSE)
# ============================================================

@migration_bp.route("/api/start-phase-2", methods=["POST"])
def start_phase_2():
    """Validate Phase 2 preconditions and authorize the SSE endpoint.

    Phase 2 needs:
    - The Phase 1 marker file to exist (Phase 1 finished and verified).
    - v2 keys already loaded in memory (from Phase 1 or from a mid-migration
      unlock).
    - A backup <=24h old (re-checked inside run_phase_2; non-overridable).

    We pre-check all three here so the SSE stream doesn\'t have to deliver
    these as inline errors.
    """
    err = _require_auth()
    if err:
        return err

    if not Migration.has_marker():
        return jsonify({
            "error": "Phase 1 marker not found; complete Phase 1 first"
        }), 400

    if Encryption._db_key_v2 is None or Encryption._file_key_v2 is None:
        return jsonify({
            "error": "v2 keys not loaded; lock and re-unlock the session, then retry"
        }), 400

    age = Migration._latest_backup_age_hours()
    if age is None or age > Migration.PHASE_2_MAX_BACKUP_AGE_HOURS:
        age_repr = f"{age:.1f}h" if age is not None else "no backups found"
        return jsonify({
            "error": (
                f"Phase 2 refused: backup is {age_repr}. Phase 2 is not "
                f"resumable -- the backup is the recovery path. Take a fresh "
                f"backup from the Backup & Restore screen and retry."
            ),
            "backup_age_hours": age,
        }), 400

    session["migration_phase_2_authorized"] = True
    session.modified = True
    return jsonify({"success": True, "backup_age_hours": age})


@migration_bp.route("/api/phase-2-progress")
def phase_2_progress():
    """SSE stream of Phase 2 progress."""
    err = _require_auth()
    if err:
        return err

    authorized = session.pop("migration_phase_2_authorized", False)
    session.modified = True

    def generate():
        if not authorized:
            yield f"data: {json.dumps({'status': 'error', 'message': 'Phase 2 not authorized. Call /api/start-phase-2 first.'})}\n\n"
            return
        yield from _stream_migration(
            lambda cb: Migration.run_phase_2(progress_cb=cb)
        )

    return Response(generate(), mimetype="text/event-stream")
