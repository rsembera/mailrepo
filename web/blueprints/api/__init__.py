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
from . import folders
from . import accounts
from . import emails
from . import imports
from . import progress
from . import progress_emails
from . import progress_commit
from . import filesystem
from . import settings
from . import exports
from . import threads
