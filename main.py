#!/usr/bin/env python3
"""
MailRepo - Encrypted email archiving for solo practitioners.

Run this file to start the application:
    python main.py

Options:
    --port=XXXX    Port to run on (default: 5050)
    --dev          Development mode with auto-reload
    --help         Show this message
"""

import atexit
import logging
import os
import signal
import sys
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.log import get_logger
from web import create_app

log = get_logger()

# Track if cleanup has run to avoid running twice
_cleanup_done = False


class PollingFilter(logging.Filter):
    """Filter out noisy polling endpoint log messages."""

    POLLING_PATHS = [
        "GET /api/session-status",
        "GET /api/keepalive",
        "HEAD / ",  # Heartbeat check
    ]

    def filter(self, record):
        message = record.getMessage()
        # Filter out polling requests (any status code)
        for path in self.POLLING_PATHS:
            if path in message:
                return False
        # Filter out static file requests (304 Not Modified)
        if "/static/" in message and "304" in message:
            return False
        return True


def _cleanup(app):
    """Cleanup function - backup and checkpoint database before exit."""
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True

    try:
        from core.database import Database, get_setting

        with app.app_context():
            # Checkpoint WAL first so backup captures all changes
            Database.checkpoint()

            # Run backup check before shutdown
            try:
                import subprocess

                from utils import backup

                frequency = get_setting("backup_frequency", "daily")
                if backup.check_backup_needed(frequency):
                    location = get_setting("backup_location", "")
                    result = backup.create_backup(location if location else None)
                    if result:
                        log.info(f"Backup completed: {result['filename']}")
                        # Run post-backup command if configured
                        post_cmd = get_setting("post_backup_command", "")
                        if post_cmd:
                            log.info(f"Running post-backup command: {post_cmd}")
                            try:
                                proc_result = subprocess.run(
                                    post_cmd,
                                    shell=True,
                                    timeout=300,
                                    capture_output=True,
                                    text=True,
                                )
                                if proc_result.stdout:
                                    for line in proc_result.stdout.strip().split("\n"):
                                        if line:
                                            log.info(f"  {line}")
                                if proc_result.returncode == 0:
                                    log.info("Post-backup command completed")
                                else:
                                    error_msg = (
                                        proc_result.stderr.strip()
                                        if proc_result.stderr
                                        else f"Exit code {proc_result.returncode}"
                                    )
                                    log.warning(f"Post-backup command failed: {error_msg}")
                            except subprocess.TimeoutExpired:
                                log.warning("Post-backup command timed out")
                            except Exception as e:
                                log.warning(f"Post-backup command error: {e}")
                    backup.record_backup_check()
                else:
                    # No backup needed, but checkpoint may have changed db binary
                    # Update baseline so next check doesn't see spurious changes
                    backup.refresh_hash_baseline()
            except Exception as e:
                log.warning(f"Backup warning: {e}")

            # Close database connection cleanly
            Database.close()
    except Exception:
        pass  # Silent fail on exit


def shutdown_handler(signum, frame, app):
    """Handle Ctrl-C gracefully - backup and checkpoint database before exit."""
    log.info("Shutting down...")
    _cleanup(app)
    sys.exit(0)


def show_help():
    """Display help text and exit."""
    help_text = """
MailRepo - Encrypted email archiving for solo practitioners

Usage: python main.py [options]

Options:
  --port=XXXX    Port to run on (default: 5050)
  --dev          Development mode with auto-reload
  --help         Show this message

Environment variables:
  MAILREPO_PORT  Port number (default: 5050)
"""
    print(help_text)
    sys.exit(0)


def main():
    """Application entry point."""

    # Check for --help first
    if "--help" in sys.argv or "-h" in sys.argv:
        show_help()

    # Console logging with timestamps (WARNING+). Console-only by design:
    # error strings can contain folder names, which shouldn't hit disk.
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Suppress polling endpoint logging
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.addFilter(PollingFilter())

    # Quiet Waitress queue warnings (normal for single-user app)
    waitress_log = logging.getLogger("waitress")
    waitress_log.setLevel(logging.ERROR)

    # Check for pending restore before opening database
    try:
        from utils import backup

        result = backup.complete_restore()
        if result:
            log.info(f"Restore completed from: {result.get('restore_point', 'unknown')}")
    except Exception as e:
        log.error(f"Restore failed: {e}")

    app = create_app()

    # Register cleanup handlers
    atexit.register(lambda: _cleanup(app))
    signal.signal(signal.SIGINT, lambda s, f: shutdown_handler(s, f, app))
    signal.signal(signal.SIGTERM, lambda s, f: shutdown_handler(s, f, app))

    # Get port from command line (--port=XXXX) or environment variable or default
    port = 5050
    for arg in sys.argv:
        if arg.startswith("--port="):
            try:
                port = int(arg.split("=")[1])
            except ValueError:
                print(f"Invalid port: {arg}")
                sys.exit(1)

    # Environment variable override
    env_port = os.environ.get("MAILREPO_PORT")
    if env_port:
        try:
            port = int(env_port)
        except ValueError:
            print(f"Invalid MAILREPO_PORT: {env_port}")
            sys.exit(1)

    host = "127.0.0.1"

    print(f"\n{'=' * 50}")
    print(f"  MailRepo v{app.config.get('app_version', '0.1.0')}")
    print(f"{'=' * 50}")

    # Check for --dev flag for development mode with auto-reload
    if "--dev" in sys.argv:
        print("\nStarting in DEVELOPMENT mode (auto-reload enabled)...")
        print(f"Open your browser to: http://localhost:{port}")
        print("\nPress Ctrl+C to stop the server\n")
        app.run(host=host, port=port, debug=True)
    else:
        # Production mode with Waitress
        from waitress import serve

        print("\nStarting web server...")
        print(f"Open your browser to: http://localhost:{port}")
        print("\nPress Ctrl+C to stop the server\n")
        serve(app, host=host, port=port)


if __name__ == "__main__":
    main()
