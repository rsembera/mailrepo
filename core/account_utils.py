"""
Account helper utilities shared across blueprints and core.

Kept deliberately small and dependency-light so it can be imported from both
the web layer (blueprints) and core without circular imports.
"""


def is_gmail_host(host: str | None) -> bool:
    """Return True if the IMAP host is Gmail / Google Workspace.

    Google Workspace custom domains also connect via imap.gmail.com, so the
    host check covers them too. This is the single source of truth for the
    Gmail provider quirk (non-standard IMAP delete semantics).
    """
    if not host:
        return False
    return host.strip().lower() == "imap.gmail.com"
