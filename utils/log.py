"""
MailRepo - Logging configuration.

Provides centralized logging for the application.
"""

import logging
import os
import sys

# Create logger
_logger = None


def get_logger(name: str = "mailrepo") -> logging.Logger:
    """
    Get a configured logger instance.

    Args:
        name: Logger name (typically module name)

    Returns:
        Configured logger instance
    """
    global _logger

    if _logger is not None:
        return _logger

    logger = logging.getLogger(name)

    # Only configure if not already configured
    if not logger.handlers:
        # Set level based on environment
        debug_mode = os.environ.get("MAILREPO_DEBUG", "").lower() in ("1", "true", "yes")
        logger.setLevel(logging.DEBUG if debug_mode else logging.INFO)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG if debug_mode else logging.INFO)

        # Simple format
        formatter = logging.Formatter("[%(levelname)s] %(message)s")
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # Prevent propagation to root logger
        logger.propagate = False

    _logger = logger
    return logger
