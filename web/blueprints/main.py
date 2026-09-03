"""
MailRepo - Main blueprint.

Handles the main application views: inbox, archive, folders, staging.
"""

import secrets

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from core import Database

main_bp = Blueprint("main", __name__)


@main_bp.route("/launch-check")
def launch_check():
    """Echo the per-launch nonce so the desktop launcher can confirm the
    port is answered by the server it started, not a squatter. Public;
    the nonce is a liveness proof, not a secret worth anything else.
    """
    from flask import current_app

    nonce = current_app.config.get("LAUNCH_NONCE")
    if not nonce:
        return ("", 404)
    return (nonce, 200, {"Content-Type": "text/plain; charset=ascii"})


@main_bp.route("/")
def index():
    """
    Main dashboard / inbox view.

    Shows email list from selected account, folder sidebar, staging controls.
    """
    # Check if any folders exist
    folders = Database.fetchall("SELECT * FROM folders ORDER BY name")

    if not folders:
        # No folders yet - redirect to create first archive
        return redirect(url_for("main.create_archive"))

    # Get accounts
    accounts = Database.fetchall("SELECT * FROM accounts ORDER BY name")

    return render_template(
        "main/index.html",
        folders=folders,
        accounts=accounts,
    )


@main_bp.route("/archive/create", methods=["GET", "POST"])
def create_archive():
    """
    Create a new archive folder.

    First-run experience lands here after password setup.
    """
    if request.method == "POST":
        # State-changing form outside /api/, so the middleware CSRF check
        # in web/app.py does not cover it — verify explicitly, the same
        # way auth.upgrade_to_recovery_keys and recovery_key_confirmed do.
        # Payload here is benign (a cross-site POST would create a folder),
        # but this is the pattern a maintainer copies.
        token = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not secrets.compare_digest(token, expected):
            return redirect(url_for("auth.login"))

        name = request.form.get("name", "").strip()

        # Validation
        errors = []

        if not name:
            errors.append("Folder name is required.")

        if len(name) > 100:
            errors.append("Folder name must be 100 characters or less.")

        # Check for duplicate name at root level
        existing = Database.fetchone(
            "SELECT id FROM folders WHERE name = ? AND parent_id IS NULL", (name,)
        )
        if existing:
            errors.append("A folder with this name already exists.")

        if errors:
            return render_template("main/create_archive.html", errors=errors, name=name)

        # Create folder
        Database.execute(
            "INSERT INTO folders (name) VALUES (?)",
            (name,),
        )
        Database.commit()

        flash(f"Archive '{name}' created successfully.", "success")
        return redirect(url_for("main.index"))

    # Check if this is first-run (no folders exist)
    folder_count = Database.fetchone("SELECT COUNT(*) as count FROM folders")
    is_first_run = folder_count["count"] == 0

    return render_template("main/create_archive.html", is_first_run=is_first_run)
