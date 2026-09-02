"""The server must never listen beyond localhost.

EdgeCase's one real security finding — the only exploitable issue a
hostile Reddit review produced — was a bind to 0.0.0.0 that silently
turned "local-only" into "exposed to the whole LAN". One line, trivial
to fix, catastrophic to miss, and invisible to every functional test.
This test makes the class of mistake impossible to repeat quietly: it
walks every waitress serve() call in both entry points and requires a
literal loopback host. A refactor to a variable fails the test too —
deliberately, so the change gets human eyes.
"""

import ast
from pathlib import Path

ENTRY_POINTS = ["main.py", "launcher.py"]
LOOPBACK = "127.0.0.1"


def _serve_calls(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", getattr(func, "attr", None))
            if name == "serve":
                yield node


def test_every_serve_call_binds_loopback_literally():
    repo = Path(__file__).parent.parent
    checked = 0
    for entry in ENTRY_POINTS:
        for call in _serve_calls(repo / entry):
            hosts = [kw.value for kw in call.keywords if kw.arg == "host"]
            assert hosts, f"{entry}: serve() without an explicit host= (line {call.lineno})"
            for value in hosts:
                assert isinstance(value, ast.Constant) and value.value == LOOPBACK, (
                    f"{entry} line {call.lineno}: serve() host must be the literal "
                    f"'{LOOPBACK}' — not a variable, not 0.0.0.0. If this needs to "
                    f"change, it is a security decision, not a refactor."
                )
            checked += 1
    assert checked >= 2, "expected serve() in both main.py and launcher.py"
