"""
MailRepo - Flask application factory.

Creates and configures the Flask application.
"""

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
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    
    # Helper to check if request is an API call
    def is_api_request():
        return request.endpoint and request.endpoint.startswith("api.")
    
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
        
        # Session timeout check
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
        return {
            "app_name": Config.APP_NAME,
            "app_version": Config.VERSION,
        }
    
    # Teardown: ensure clean state
    @app.teardown_appcontext
    def teardown(exception):
        """Clean up after request."""
        pass  # Database connection is reused; don't close here
    
    return app
