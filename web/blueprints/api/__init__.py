"""
MailRepo API Blueprint Package

Combines all API sub-modules into a single blueprint.
"""

from flask import Blueprint

# Create the main API blueprint
api_bp = Blueprint("api", __name__, url_prefix="/api")

# Import and register route modules. Each module adds its routes to api_bp
# via @api_bp.route decorators. The progress* modules form a split-out
# triple: progress.py is the small coordinator (sse_message + the two
# pending-commit endpoints), progress_emails.py and progress_commit.py
# hold one SSE workflow each. progress_emails and progress_commit both
# import sse_message from progress, so progress must be imported first.
from . import (
    accounts,
    emails,
    exports,
    filesystem,
    folders,
    imports,
    progress,
    progress_commit,
    progress_emails,
    settings,
    threads,
)
