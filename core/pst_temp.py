"""
MailRepo - Temporary directories for PST conversion.

A PST file is converted with ``readpst`` into mbox files in a directory
under the system temp folder. Those files are the mail in plain text.
They are needed while the import is mounted in the page and by nobody
afterwards, so they are removed when the import is unmounted, when the
archive locks (the page that knew about them is gone), at exit, and at
the next launch in case none of those happened (a crash).

Paths are compared after resolving symlinks on both sides. On macOS the
temp folder is itself reached through one (/var -> /private/var,
/tmp -> /private/tmp), and comparing a resolved path with an unresolved
root refused every cleanup request there.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading

PREFIX = "mailrepo_pst_"


def temp_root() -> str:
    """The system temp folder, symlinks resolved."""
    return os.path.realpath(tempfile.gettempdir())


# Directories this process made and has not yet removed.
_own: set[str] = set()
_own_lock = threading.Lock()


def create() -> str:
    """Make a new conversion directory and return its path."""
    path = tempfile.mkdtemp(prefix=PREFIX)
    with _own_lock:
        _own.add(os.path.realpath(path))
    return path


def is_conversion_dir(path: str) -> bool:
    """True if ``path`` is one of our directories, directly under the temp folder."""
    if not path:
        return False
    resolved = os.path.realpath(path)
    parent, name = os.path.split(resolved)
    return parent == temp_root() and name.startswith(PREFIX) and name != PREFIX


def remove(path: str) -> bool:
    """Remove one conversion directory. False if ``path`` is not one."""
    if not is_conversion_dir(path):
        return False
    resolved = os.path.realpath(path)
    shutil.rmtree(resolved, ignore_errors=True)
    with _own_lock:
        _own.discard(resolved)
    return True


def remove_own() -> int:
    """Remove the conversion directories this process made.

    Used when the archive locks and at exit. Another running copy of the
    app (a demo instance, say) keeps its own.
    """
    with _own_lock:
        paths = list(_own)
    return sum(1 for path in paths if remove(path))


def sweep() -> int:
    """Remove every conversion directory, whoever made it. For launch.

    Returns how many were found.
    """
    root = temp_root()
    try:
        names = [n for n in os.listdir(root) if n.startswith(PREFIX) and n != PREFIX]
    except OSError:
        return 0
    found = 0
    for name in names:
        path = os.path.join(root, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
            found += 1
    return found
