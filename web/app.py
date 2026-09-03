"""
MailRepo - Flask application factory.

Creates and configures the Flask application.
"""

import secrets
import time

from flask import Flask, jsonify, redirect, request, session, url_for

from core import Config, Database, Encryption, FlaskConfig
from core.database import get_setting

from . import idle


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
        # Per process, never on disk. Sessions cannot outlive the process
        # anyway (the keys live in memory), so a persistent signing key
        # only ever helped someone else mint a cookie — and it rode along
        # in every backup (security review 2026-09, #11).
        app.config["SECRET_KEY"] = secrets.token_bytes(32)
        app.config["app_version"] = Config.VERSION
    else:
        app.config.update(test_config)

    # Ensure directories exist
    Config.ensure_directories()

    # NOTE: Database initialization is deferred until after authentication
    # because we need the master password to derive the encryption key.

    # Register blueprints
    from .blueprints.api import api_bp
    from .blueprints.auth import auth_bp
    from .blueprints.backups import backups_bp
    from .blueprints.main import main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(backups_bp)

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
        # auth.login_with_recovery_key is public for the same reason
        # auth.login is: it is a way IN. Requiring an authenticated
        # session to reach it would make it unreachable by exactly the
        # person it exists for — someone locked out of their archive.
        #
        # auth.set_password_post_recovery likewise: since Session 71 the
        # recovery key no longer grants a session, so the reset step has
        # no session to check. Its gate is the server-side handoff token
        # minted only after a key verifies.
        #
        # auth.recover / recover_scan / recover_prepare are public for the
        # same reason, in its sharpest form: they are for someone whose
        # key file is gone, so there is no credential left for them to
        # present. They gate on the opposite condition instead — each one
        # refuses once an archive exists, which is what stops them being
        # a way to roll a live archive back over its owner.
        public_endpoints = {
            "auth.login",
            "auth.login_with_recovery_key",
            "auth.set_password_post_recovery",
            "auth.setup",
            "auth.recover",
            "auth.recover_scan",
            "auth.recover_prepare",
            "auth.recover_search",
            "auth.recover_browse",
            "static",
            "main.launch_check",
        }

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

        # The cookie must belong to THIS login. A cookie captured earlier
        # and replayed after a logout and fresh login is otherwise still
        # a valid signed cookie against a once-again-unlocked archive.
        login_id = session.get("login_id", "")
        if not login_id or not secrets.compare_digest(login_id, idle.current_login_id()):
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
        # NOTE: the export progress stream (api.export_progress) is
        # deliberately NOT listed here. Its work runs in a detached daemon
        # thread and the generator self-caps at 5 min, so it doesn't need the
        # session kept alive — and an already-expired session shouldn't be
        # able to open a fresh export stream. Only the long-lived account/
        # commit streams are exempted from the timeout.
        streaming_endpoints = {
            "api.stream_account_emails",
            "api.stream_commit",
        }
        if request.endpoint in streaming_endpoints:
            # Extend session for streaming - these can take a long time
            session["last_activity"] = time.time()
            idle.touch()
            return

        # Housekeeping requests the page makes on its own must not count
        # as activity. The status poll fires every 30 seconds while a tab
        # is open; if it refreshed last_activity the timeout could never
        # be reached and the idle lock would be a promise on the front
        # page with nothing behind it. It is still subject to the check
        # below, so it is the request that reports "timed out" to the page.
        passive_endpoints = {"api.session_status"}
        is_passive = request.endpoint in passive_endpoints

        try:
            timeout_minutes = int(get_setting("session_timeout", "30"))
            if timeout_minutes == 0:  # "Never" option
                if not is_passive:
                    session["last_activity"] = time.time()
                    idle.touch()
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
                Database.close()
                Encryption.lock()
                if is_api_request():
                    return jsonify({"error": "Session timed out", "code": "session_timeout"}), 401
                return redirect(url_for("auth.login", timeout=1))

        # Update last activity timestamp
        if not is_passive:
            session["last_activity"] = now
            idle.touch(now)

    # Defensive headers on every response. nosniff stops a browser from
    # deciding that some response is really HTML; DENY keeps app pages
    # out of frames on any other origin. The email-body iframe is a
    # same-origin about:blank document written by script, so DENY does
    # not touch it.
    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

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
            # Whether this archive can be opened with a recovery key.
            # Injected globally so the login screen does not have to
            # thread it through every render path (there are several,
            # including the rate-limit branches, and missing one would
            # silently hide the recovery link exactly when a locked-out
            # user needs it most).
            "has_recovery_key": Encryption.has_recovery_key(),
        }

    # JSON safety net: any uncaught exception on an API path returns JSON
    # instead of Flask's default HTML error page, so the frontend's fetch
    # handlers always receive a parseable response. Non-API routes keep
    # Flask's normal behavior (including the debugger in debug mode).
    @app.errorhandler(Exception)
    def handle_uncaught(e):
        from werkzeug.exceptions import HTTPException

        if not is_api_request():
            if isinstance(e, HTTPException):
                return e
            raise e
        if isinstance(e, HTTPException):
            return jsonify({"error": e.description or e.name, "code": e.code}), e.code
        app.logger.exception("Unhandled exception on API route")
        return jsonify({"error": "Internal server error"}), 500

    # Teardown: ensure clean state
    @app.teardown_appcontext
    def teardown(exception):
        """Clean up after request."""
        pass  # Database connection is reused; don't close here

    return app
