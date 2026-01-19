"""
MailRepo - Main blueprint.

Handles the main application views: inbox, archive, folders, staging.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash

from core import Database


main_bp = Blueprint("main", __name__)


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
        name = request.form.get("name", "").strip()
        encrypted = request.form.get("encrypted", "1") == "1"
        
        # Validation
        errors = []
        
        if not name:
            errors.append("Folder name is required.")
        
        if len(name) > 100:
            errors.append("Folder name must be 100 characters or less.")
        
        # Check for duplicate name at root level
        existing = Database.fetchone(
            "SELECT id FROM folders WHERE name = ? AND parent_id IS NULL",
            (name,)
        )
        if existing:
            errors.append("A folder with this name already exists.")
        
        if errors:
            return render_template("main/create_archive.html", errors=errors, name=name)
        
        # Create folder
        Database.execute(
            "INSERT INTO folders (name, encrypted) VALUES (?, ?)",
            (name, 1 if encrypted else 0),
        )
        Database.commit()
        
        flash(f"Archive '{name}' created successfully.", "success")
        return redirect(url_for("main.index"))
    
    # Check if this is first-run (no folders exist)
    folder_count = Database.fetchone("SELECT COUNT(*) as count FROM folders")
    is_first_run = folder_count["count"] == 0
    
    return render_template("main/create_archive.html", is_first_run=is_first_run)


@main_bp.route("/review")
def review():
    """Review staged emails before committing."""
    folders = Database.fetchall("SELECT * FROM folders ORDER BY name")
    return render_template("main/review.html", folders=folders)


@main_bp.route("/settings")
def settings():
    """Application settings page."""
    accounts = Database.fetchall("SELECT * FROM accounts ORDER BY name")
    return render_template("main/settings.html", accounts=accounts)
