"""
MailRepo - Flask application factory.

Creates and configures the Flask application.
"""

from flask import Flask, redirect, url_for, session, g

from core import Config, FlaskConfig, Database, Encryption, generate_flask_secret_key


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
    
    # Initialize database
    Database.initialize()
    
    # Register blueprints
    from .blueprints.auth import auth_bp
    from .blueprints.main import main_bp
    from .blueprints.api import api_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    
    # Before request: check authentication
    @app.before_request
    def check_auth():
        """Ensure user is authenticated before accessing protected routes."""
        from flask import request
        
        # Public routes that don't require authentication
        public_endpoints = {"auth.login", "auth.setup", "static"}
        
        if request.endpoint in public_endpoints:
            return
        
        # Check if setup is needed
        if not Encryption.is_initialized():
            return redirect(url_for("auth.setup"))
        
        # Check if logged in
        if not session.get("authenticated"):
            # For API requests, return 401 JSON
            if request.endpoint and request.endpoint.startswith("api."):
                from flask import jsonify
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("auth.login"))
        
        # Verify encryption is unlocked (session might be stale)
        if not Encryption.is_unlocked():
            session.clear()
            if request.endpoint and request.endpoint.startswith("api."):
                from flask import jsonify
                return jsonify({"error": "Session expired"}), 401
            return redirect(url_for("auth.login"))
    
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
