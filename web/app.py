"""
MailRepo - Flask application factory.

Creates and configures the Flask application.
"""

import secrets
import time
from flask import Flask, redirect, url_for, session, g, request, jsonify

from core import Config, FlaskConfig, Database, Encryption, generate_flask_secret_key
from core.database import get_setting


def create_app(test_config: dict = None) -> Flask:
    """
    Application factory for MailRepo.
    
    Args:
        test_config: Optional configuration dict for testing.
        
    Returns:
        Configured Flask application.
    """
    app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates",
    )
    
    # Load configuration
    if test_config is None:
        app.config.from_object(FlaskConfig)
        app.config["SECRET_KEY"] = generate_flask_secret_key()
        app.config["app_version"] = Config.VERSION
    else:
        app.config.update(test_config)
    
    # Ensure directories exist
    Config.ensure_directories()
    
    # NOTE: Database initialization is deferred until after authentication
    # because we need the master password to derive the encryption key.
    
    # Register blueprints
    from .blueprints.auth import auth_bp
    from .blueprints.main import main_bp
    from .blueprints.api import api_bp
    from .blueprints.backups import backups_bp
    from .blueprints.migration import migration_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(backups_bp)
    app.register_blueprint(migration_bp)
    
    # Helper to check if request is an API call.
    # Matches both: endpoints in the 'api' blueprint, and any request whose
    # URL path contains /api/ regardless of which blueprint hosts it. The
    # latter catches /backups/api/..., /migration/api/..., etc. so those
    # blueprints get JSON 401s instead of HTML redirects on auth failure.
    def is_api_request():
        if request.endpoint and request.endpoint.startswith("api."):
            return True
        return "/api/" in (request.path or "")
    
    # Before request: check authentication and session timeout
    @app.before_request
    def check_auth():
        """Ensure user is authenticated and session hasn't timed out."""
        # Public routes that don't require authentication
        public_endpoints = {"auth.login", "auth.setup", "static"}
        
        if request.endpoint in public_endpoints:
            return
        
        # Check if setup is needed
        if not Encryption.is_initialized():
            return redirect(url_for("auth.setup"))
        
        # Check if logged in
        if not session.get("authenticated"):
            if is_api_request():
                return jsonify({"error": "Authentication required", "code": "auth_required"}), 401
            return redirect(url_for("auth.login"))
        
        # Verify encryption is unlocked (session might be stale)
        if not Encryption.is_unlocked():
            session.clear()
            if is_api_request():
                return jsonify({"error": "Session expired", "code": "session_expired"}), 401
            return redirect(url_for("auth.login"))
        
        # CSRF protection for state-changing API requests
        if is_api_request() and request.method in ("POST", "PUT", "DELETE", "PATCH"):
            token = request.headers.get("X-CSRF-Token", "")
            expected = session.get("csrf_token", "")
            if not expected or not secrets.compare_digest(token, expected):
                return jsonify({"error": "Invalid CSRF token"}), 403
        
        # Session timeout check - skip for SSE streaming endpoints
        streaming_endpoints = {
            "api.stream_account_emails",
            "api.stream_commit",
        }
        if request.endpoint in streaming_endpoints:
            # Extend session for streaming - these can take a long time
            session["last_activity"] = time.time()
            return
        
        try:
            timeout_minutes = int(get_setting("session_timeout", "30"))
            if timeout_minutes == 0:  # "Never" option
                session["last_activity"] = time.time()
                return
            session_timeout = timeout_minutes * 60
        except (ValueError, TypeError):
            session_timeout = 30 * 60
        
        last_activity = session.get("last_activity")
        now = time.time()
        
        if last_activity:
            elapsed = now - last_activity
            if elapsed > session_timeout:
                # Session expired - clear everything
                session.clear()
                Encryption.lock()
                if is_api_request():
                    return jsonify({"error": "Session timed out", "code": "session_timeout"}), 401
                return redirect(url_for("auth.login", timeout=1))
        
        # Update last activity timestamp
        session["last_activity"] = now
    
    # Context processor: make common variables available to all templates
    @app.context_processor
    def inject_globals():
        """Inject global variables into all templates."""
        # Generate CSRF token if authenticated and not already set
        csrf_token = session.get("csrf_token", "")
        if session.get("authenticated") and not csrf_token:
            csrf_token = secrets.token_hex(32)
            session["csrf_token"] = csrf_token
        return {
            "app_name": Config.APP_NAME,
            "app_version": Config.VERSION,
            "csrf_token": csrf_token,
        }
    
    # Teardown: ensure clean state
    @app.teardown_appcontext
    def teardown(exception):
        """Clean up after request."""
        pass  # Database connection is reused; don't close here
    
    return app
