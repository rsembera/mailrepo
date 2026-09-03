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

import base64
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
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


def _bind_listen_socket(preferred: int = PREFERRED_PORT) -> socket.socket:
    """Bind the server socket here and keep it.

    The socket is handed to waitress, so there is no window between
    "checked the port was free" and "started listening" in which another
    local process could take the port and put its own login page in the
    MailRepo window (security review 2026-09, #10). Preferred port if
    free; refuse if MailRepo owns it; otherwise ephemeral.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", preferred))
    except OSError:
        if _is_mailrepo(preferred):
            sock.close()
            _fatal(
                "MailRepo is already running.\n\n"
                "Close the existing MailRepo window before opening it again."
            )
        sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    return sock


def _wait_for_server(port: int, launch_nonce: str, timeout: float = 20.0) -> bool:
    """Poll until OUR server answers, or give up.

    The check is the launch nonce, not a substring: only the app this
    process built knows it, so a squatter cannot pass as MailRepo.
    """
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/launch-check", timeout=1) as r:
                return r.status == 200 and r.read(256).decode("ascii", "replace") == launch_nonce
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


def _serve(app, sock: socket.socket) -> None:
    import logging

    from waitress import serve

    logging.getLogger("waitress").setLevel(logging.ERROR)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    serve(app, sockets=[sock], _quiet=True)


class DesktopApi:
    """What the page can ask the desktop shell to do (window.pywebview.api).

    A browser opens an attachment in a new tab and prints with its own
    dialog; a pywebview window can do neither. Both come back to the same
    move: put the bytes in a file and hand it to macOS, which opens the
    right application — Preview for a PDF, and Preview's print dialog is
    a real one.

    The page does the fetching (it holds the session cookie); Python only
    ever receives bytes. Files land in a per-run 0700 directory that is
    wiped on the next launch, not deleted immediately, because the
    viewer reads them lazily (EdgeCase's arrangement, kept as is).
    """

    def __init__(self):
        self._dir = None

    def _viewer_dir(self) -> Path:
        if self._dir is None:
            parent = Path(tempfile.gettempdir()) / f"mailrepo-viewer-{os.getuid()}"
            shutil.rmtree(parent, ignore_errors=True)
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            parent.chmod(0o700)
            self._dir = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
        return self._dir

    def _place(self, filename: str, data: bytes) -> Path:
        safe = re.sub(r"[\\/:\x00-\x1f]", "_", Path(filename or "file").name).strip() or "file"
        folder = Path(tempfile.mkdtemp(dir=self._viewer_dir()))
        path = folder / safe
        path.write_bytes(data)
        path.chmod(0o600)
        return path

    @staticmethod
    def _open(path: Path) -> None:
        if platform.system() == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)

    def open_bytes(self, filename: str, data_b64: str) -> bool:
        """Open a file (attachment, source text) in the default application."""
        try:
            self._open(self._place(filename, base64.b64decode(data_b64)))
            return True
        except Exception as e:  # noqa: BLE001 — surfaced to the page as False
            print(f"open_bytes failed: {e}", file=sys.stderr)
            return False

    def print_html(self, title: str, html: str) -> bool:
        """Render a print document to PDF and open it; the user prints from there.

        Remote resources are refused, as in core.pdf_export: an email's
        tracking pixel must not phone home because someone pressed Print.
        """
        try:
            from weasyprint import HTML

            from core.pdf_fetcher import make_url_fetcher

            pdf = HTML(string=html, url_fetcher=make_url_fetcher(load_remote=False)).write_pdf()
            self._open(self._place(f"{title or 'Email'}.pdf", pdf))
            return True
        except Exception as e:  # noqa: BLE001
            print(f"print_html failed: {e}", file=sys.stderr)
            return False


def run_desktop() -> None:
    import webview

    import main as cli

    sock = _bind_listen_socket()
    port = sock.getsockname()[1]

    try:
        app = cli.prepare_app()
    except SystemExit:
        # prepare_app already printed the reason (missing SQLCipher).
        _fatal("MailRepo cannot start: its encryption library is missing from this build.")
        return

    import secrets

    launch_nonce = secrets.token_urlsafe(32)
    app.config["LAUNCH_NONCE"] = launch_nonce

    threading.Thread(target=_serve, args=(app, sock), daemon=True).start()

    if not _wait_for_server(port, launch_nonce):
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
        js_api=DesktopApi(),
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
