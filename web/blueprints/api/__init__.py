"""
MailRepo API Blueprint Package

Combines all API sub-modules into a single blueprint.
"""

from flask import Blueprint

# Create the main API blueprint
api_bp = Blueprint("api", __name__, url_prefix="/api")

# Import and register route modules
# Each module adds its routes to api_bp
from . import folders
from . import accounts
from . import emails
from . import imports
from . import progress
from . import filesystem
from . import settings
from . import exports
