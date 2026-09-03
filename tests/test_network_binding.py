"""The server must never listen beyond localhost.

EdgeCase's one real security finding — the only exploitable issue a
hostile Reddit review produced — was a bind to 0.0.0.0 that silently
turned "local-only" into "exposed to the whole LAN". One line, trivial
to fix, catastrophic to miss, and invisible to every functional test.
This test makes the class of mistake impossible to repeat quietly: it
walks every waitress serve() and dev-mode app.run() call in both entry points and requires a
literal loopback host. A refactor to a variable fails the test too —
deliberately, so the change gets human eyes.
"""

import ast
from pathlib import Path

ENTRY_POINTS = ["main.py", "launcher.py"]
LOOPBACK = "127.0.0.1"


def _server_calls(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", getattr(func, "attr", None))
            if name in ("serve", "run"):
                yield node


def _bind_calls(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "bind":
            yield node


def test_every_serve_call_binds_loopback_literally():
    repo = Path(__file__).parent.parent
    checked = 0
    for entry in ENTRY_POINTS:
        for call in _server_calls(repo / entry):
            hosts = [kw.value for kw in call.keywords if kw.arg == "host"]
            if not hosts and getattr(call.func, "attr", None) == "run":
                continue  # unrelated .run() with no host kwarg
            if not hosts and any(kw.arg == "sockets" for kw in call.keywords):
                # A pre-bound socket (launcher.py, review #10). Then every
                # socket.bind() in that file must name the literal loopback
                # address — the same rule, one level down.
                binds = list(_bind_calls(repo / entry))
                assert binds, f"{entry}: serve(sockets=...) but no socket.bind() found"
                for b in binds:
                    tup = b.args[0]
                    assert (
                        isinstance(tup, ast.Tuple)
                        and isinstance(tup.elts[0], ast.Constant)
                        and tup.elts[0].value == LOOPBACK
                    ), (
                        f"{entry} line {b.lineno}: socket.bind() host must be the literal '{LOOPBACK}'"
                    )
                checked += 1
                continue
            assert hosts, f"{entry}: server start without an explicit host= (line {call.lineno})"
            for value in hosts:
                assert isinstance(value, ast.Constant) and value.value == LOOPBACK, (
                    f"{entry} line {call.lineno}: server host must be the literal "
                    f"'{LOOPBACK}' — not a variable, not 0.0.0.0. If this needs to "
                    f"change, it is a security decision, not a refactor."
                )
            checked += 1
    assert checked >= 3, "expected waitress serve() in both entry points plus dev-mode app.run()"


class TestLaunchCheck:
    """Security review 2026-09, #10: the launcher verifies the port by a
    per-launch nonce rather than a substring."""

    def test_404_when_not_launched_by_desktop(self, client):
        assert client.get("/launch-check").status_code == 404

    def test_echoes_nonce_without_auth(self, app):
        app.config["LAUNCH_NONCE"] = "n0nce"
        resp = app.test_client().get("/launch-check")
        assert resp.status_code == 200
        assert resp.get_data(as_text=True) == "n0nce"

    def test_launcher_binds_and_serves_prebound_socket(self, app):
        import threading

        import launcher

        app.config["LAUNCH_NONCE"] = "xyz"
        sock = launcher._bind_listen_socket(0)
        port = sock.getsockname()[1]
        threading.Thread(target=launcher._serve, args=(app, sock), daemon=True).start()
        assert launcher._wait_for_server(port, "xyz", timeout=5) is True
        assert launcher._wait_for_server(port, "not-it", timeout=0.5) is False
