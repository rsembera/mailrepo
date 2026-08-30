"""
MailRepo desktop launcher — the packaged app's entry point.

Wraps the Flask/waitress server in a native window (pywebview), the same
shape as EdgeCase's desktop.py. `python main.py` remains the command-line
way to run MailRepo; this file is what py2app (and, later, the .deb's
desktop entry) points at.

What this does that main.py does not:
  1. Puts the archive in the OS's application-data location instead of
     next to the code (inside a .app bundle, "next to the code" is wiped
     on every upgrade).
  2. Picks a port that is actually free, and refuses to start a second
     instance against the same archive.
  3. Opens a window and runs the normal backup-and-checkpoint shutdown
     when that window closes.
"""

import os
import platform
import socket
import sys
import threading
import time
from pathlib import Path

APP_TITLE = "MailRepo"
PREFERRED_PORT = 5050


def default_data_dir() -> Path:
    """Where the archive lives on a packaged install.

    macOS: ~/Library/Application Support/MailRepo/ — one level below
    backup_locations.json, which Config.get_state_path() keeps at the top
    of that same folder. Deleting the app from /Applications touches
    neither. Linux: XDG data home, with state in XDG config home as before.
    """
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "MailRepo"
    xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg) / "mailrepo"


# Must be set before anything imports core.config, which caches the base
# path on first use. An explicit MAILREPO_DATA_DIR in the environment wins,
# so the test suite and power users are unaffected.
os.environ.setdefault("MAILREPO_DATA_DIR", str(default_data_dir()))
os.environ["MAILREPO_DESKTOP"] = "1"

# The launcher runs from inside the bundle; make the project importable
# the same way main.py does.
sys.path.insert(0, str(Path(__file__).parent))


def _bundle_contents() -> Path | None:
    """Contents/ of the .app when running packaged, else None."""
    resources = os.environ.get("RESOURCEPATH")  # set by py2app's bootstrap
    if getattr(sys, "frozen", False) and resources:
        return Path(resources).parent
    return None


def _use_bundled_native_libraries(contents: Path) -> None:
    """Route WeasyPrint's dlopen-by-name to Contents/Frameworks, and readpst
    to Contents/Helpers.

    WeasyPrint opens pango, harfbuzz, fontconfig & co. with cffi by bare
    name ('libpango-1.0.dylib'). dyld resolves such names through its
    search path, which cannot be changed from inside a hardened-runtime
    process, and it does NOT consult already-loaded images (verified,
    Session 88: pre-loading the bundled copies still opened Homebrew's).
    So the one dlopen WeasyPrint uses is wrapped: a bare name that matches
    a bundled library becomes that library's absolute path. Anything else
    passes through untouched.
    """
    import cffi

    frameworks = contents / "Frameworks"
    bundled = {p.name: p for p in frameworks.glob("*.dylib")}
    original = cffi.FFI.dlopen

    def stem(leaf: str) -> str:
        # 'libgobject-2.0.0.dylib' -> 'gobject-2.0.0'; 'gobject-2.0' -> 'gobject-2.0'
        if leaf.endswith(".dylib"):
            leaf = leaf[: -len(".dylib")]
        return leaf[3:] if leaf.startswith("lib") else leaf

    by_stem = {stem(leaf): path for leaf, path in bundled.items()}

    def resolve(name):
        if not isinstance(name, str) or "/" in name:
            return name  # absolute path or non-string: untouched
        wanted = stem(name)
        if wanted in by_stem:
            return str(by_stem[wanted])
        # Unversioned request ('pango-1.0') for a versioned file
        # ('pango-1.0.0'), and the Windows-style spelling ('gobject-2.0-0')
        # with its last '-' read as '.'.
        head, _, tail = wanted.rpartition("-")
        for candidate in (wanted, f"{head}.{tail}" if head else wanted):
            for bundled_stem, path in by_stem.items():
                if bundled_stem == candidate or bundled_stem.startswith(candidate + "."):
                    return str(path)
        # Inside the bundle a bare name that is not bundled must fail here,
        # not fall through to whatever dyld finds on this particular Mac —
        # a Homebrew copy would load a second glib and still be missing on
        # the user's machine. WeasyPrint catches OSError and tries its next
        # spelling.
        raise OSError(f"{name}: not bundled in {frameworks}")

    def dlopen(self, name, flags=0):
        return original(self, resolve(name), flags)

    cffi.FFI.dlopen = dlopen

    helpers = contents / "Helpers"
    if helpers.is_dir():
        os.environ["PATH"] = f"{helpers}{os.pathsep}{os.environ.get('PATH', '')}"


_contents = _bundle_contents()
if _contents is not None:
    _use_bundled_native_libraries(_contents)


def _is_mailrepo(port: int, timeout: float = 2.0) -> bool:
    """True if a MailRepo server is already answering on this port."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/auth/login", timeout=timeout) as r:
            return r.status == 200 and b"MailRepo" in r.read(65536)
    except Exception:
        return False


def _pick_port(preferred: int = PREFERRED_PORT) -> int:
    """Preferred port if free; refuse if MailRepo owns it; otherwise ephemeral."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", preferred))
        return preferred
    except OSError:
        pass

    if _is_mailrepo(preferred):
        _fatal(
            "MailRepo is already running.\n\n"
            "Close the existing MailRepo window before opening it again."
        )

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 20.0) -> bool:
    """Poll until the server answers, or give up."""
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/auth/login", timeout=1):
                return True
        except Exception:
            time.sleep(0.2)
    return False


def _fatal(message: str) -> None:
    """Show a native error dialog (there is no terminal to print to) and exit."""
    print(message, file=sys.stderr)
    try:
        import webview

        # A throwaway window is the only way to get a dialog before
        # webview.start(); on macOS this maps to a native NSAlert.
        w = webview.create_window(APP_TITLE, html="<p></p>", hidden=True)
        webview.start(lambda: (w.create_confirmation_dialog(APP_TITLE, message), w.destroy()))
    except Exception:
        pass
    sys.exit(1)


def _serve(app, port: int) -> None:
    import logging

    from waitress import serve

    logging.getLogger("waitress").setLevel(logging.ERROR)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    serve(app, host="127.0.0.1", port=port, _quiet=True)


def run_desktop() -> None:
    import webview

    import main as cli

    port = _pick_port()

    try:
        app = cli.prepare_app()
    except SystemExit:
        # prepare_app already printed the reason (missing SQLCipher).
        _fatal("MailRepo cannot start: its encryption library is missing from this build.")
        return

    threading.Thread(target=_serve, args=(app, port), daemon=True).start()

    if not _wait_for_server(port):
        _fatal(f"MailRepo failed to start: the local server on port {port} did not respond.")
        return

    # Native Save panel for <a download> links and attachment responses
    # (PDF export, .eml download, recovery key, backups).
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True

    window = webview.create_window(
        APP_TITLE,
        f"http://127.0.0.1:{port}",
        width=1280,
        height=820,
        min_size=(1024, 680),
    )

    def on_closing():
        # Same path as Ctrl-C on the command line: checkpoint, backup if
        # due, close the database.
        cli._cleanup(app)

    window.events.closing += on_closing

    storage_dir = Path(os.environ["MAILREPO_DATA_DIR"]) / "webview"
    storage_dir.mkdir(parents=True, exist_ok=True)
    webview.start(private_mode=False, storage_path=str(storage_dir))
    sys.exit(0)


if __name__ == "__main__":
    run_desktop()
