#!/usr/bin/env python3
"""
MailRepo - Encrypted email archiving for solo practitioners.

Run this file to start the application:
    python main.py

Or use the installed command:
    mailrepo
"""

import sys
import logging
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from web import create_app


class PollingFilter(logging.Filter):
    """Filter out noisy polling endpoint log messages."""
    
    POLLING_PATHS = [
        'GET /api/session-status',
        'GET /api/keepalive', 
        'HEAD / ',  # Heartbeat check
    ]
    
    def filter(self, record):
        message = record.getMessage()
        # Filter out polling requests (only successful ones)
        for path in self.POLLING_PATHS:
            if path in message and '200' in message:
                return False
        return True


def main():
    """Application entry point."""
    # Suppress polling endpoint logging
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.addFilter(PollingFilter())
    
    app = create_app()
    
    # Development server settings
    host = "127.0.0.1"
    port = 5050  # Different from EdgeCase's 5000
    debug = True  # Development mode
    
    print(f"\n{'=' * 50}")
    print(f"  MailRepo v{app.config.get('app_version', '0.1.0')}")
    print(f"  Running at http://{host}:{port}")
    print(f"{'=' * 50}\n")
    
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
