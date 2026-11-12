"""Content-Security-Policy on the app's own pages."""

import re
from pathlib import Path

import pytest

from web.app import content_security_policy

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "web" / "templates"
JS = ROOT / "web" / "static" / "js"


def _directives(header):
    out = {}
    for part in header.split(";"):
        name, _, value = part.strip().partition(" ")
        out[name] = value.split()
    return out


def _page_nonce(resp):
    policy = _directives(resp.headers["Content-Security-Policy"])
    nonces = [s for s in policy["script-src"] if s.startswith("'nonce-")]
    assert len(nonces) == 1
    return nonces[0][len("'nonce-") : -1]


def _inline_scripts(html):
    """(attributes, body) of every <script> without a src."""
    found = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, flags=re.S)
    return [(attrs, body) for attrs, body in found if "src=" not in attrs]


PAGES = ["/auth/login"]


@pytest.mark.parametrize("path", PAGES)
def test_pages_carry_a_policy_that_runs_only_the_apps_scripts(client, initialized_app, path):
    resp = client.get(path)
    assert resp.status_code == 200
    policy = _directives(resp.headers["Content-Security-Policy"])

    scripts = policy["script-src"]
    assert "'self'" in scripts
    assert "'unsafe-inline'" not in scripts and "'unsafe-eval'" not in scripts
    assert "*" not in scripts and "data:" not in scripts and "blob:" not in scripts
    assert "https:" not in scripts and "http:" not in scripts

    assert policy["default-src"] == ["'self'"]
    assert policy["object-src"] == ["'none'"]
    assert policy["form-action"] == ["'self'"]
    assert policy["frame-ancestors"] == ["'none'"]
    # Scripts may only talk to the app.
    assert set(policy["connect-src"]) == {"'self'", "data:", "blob:"}


def test_main_page_carries_the_policy_too(authenticated_client):
    from core import Database

    # Without a folder the main page redirects to "create your first archive".
    Database.execute("INSERT INTO folders (name) VALUES ('Clients')")
    Database.commit()
    resp = authenticated_client.get("/")
    assert resp.status_code == 200
    assert (
        "'unsafe-inline'" not in _directives(resp.headers["Content-Security-Policy"])["script-src"]
    )
    nonce = _page_nonce(resp)
    inline = _inline_scripts(resp.get_data(as_text=True))
    assert inline
    for attrs, _ in inline:
        assert f'nonce="{nonce}"' in attrs


def test_every_inline_script_on_the_login_page_has_this_requests_nonce(client, initialized_app):
    resp = client.get("/auth/login")
    nonce = _page_nonce(resp)
    inline = _inline_scripts(resp.get_data(as_text=True))
    assert inline
    for attrs, _ in inline:
        assert f'nonce="{nonce}"' in attrs


def test_the_nonce_is_new_for_every_response(client, initialized_app):
    first = _page_nonce(client.get("/auth/login"))
    second = _page_nonce(client.get("/auth/login"))
    assert first != second
    assert len(first) >= 20


def test_api_responses_are_not_pages(authenticated_client):
    resp = authenticated_client.get("/api/folders")
    assert "Content-Security-Policy" not in resp.headers


def test_inline_attachments_keep_their_own_stricter_policy(initialized_app):
    from web.responses import attachment_response

    app, _ = initialized_app
    headers = next(f for f in app.after_request_funcs[None] if f.__name__ == "set_security_headers")
    with app.test_request_context("/"):
        resp = headers(attachment_response(b"plain", "text/plain", "a.txt", inline=True))
        # HTML is never served inline; it is a download, not a page.
        html = headers(attachment_response(b"<p>x</p>", "text/html", "a.html", inline=True))
        assert html.mimetype == "application/octet-stream"
        assert "Content-Security-Policy" not in html.headers
        # The same hook does add the page policy to a plain HTML response.
        page = headers(app.response_class("<p>x</p>", mimetype="text/html"))
        # ...and leaves alone a response that already has one.
        own = app.response_class("<p>x</p>", mimetype="text/html")
        own.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
        own = headers(own)
    assert "script-src 'self'" in page.headers["Content-Security-Policy"]
    assert own.headers["Content-Security-Policy"] == "sandbox; default-src 'none'"
    assert resp.headers["Content-Security-Policy"] == "sandbox; default-src 'none'"


def test_policy_without_a_nonce_allows_no_inline_script():
    policy = _directives(content_security_policy(None))
    assert policy["script-src"] == ["'self'"]


def test_templates_have_no_inline_handlers_and_every_inline_script_is_nonced():
    for path in TEMPLATES.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\son[a-z]+\s*=\s*[\"']", text), path.name
        assert "javascript:" not in text, path.name
        for attrs, _ in _inline_scripts(text):
            assert 'nonce="{{ csp_nonce }}"' in attrs, path.name


def test_scripts_build_no_inline_handlers_or_javascript_links():
    for path in JS.rglob("*.js"):
        if path.name == "lucide.min.js":
            continue
        text = path.read_text(encoding="utf-8")
        # In markup built by the scripts: <tag ... onclick="...">.
        assert not re.search(r"<[a-z][^>`]*\son[a-z]+=[\"']", text), path.name
        assert "javascript:" not in text, path.name
        assert not re.search(r"\beval\(|new Function\(", text), path.name


def test_overlay_buttons_are_wired_by_listener():
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    for button in (
        "stay-logged-in-btn",
        "timeout-logout-btn",
        "session-expired-login-btn",
        "server-retry-btn",
    ):
        assert f'id="{button}"' in base
        assert f"on('{button}'" in base


# --- desktop shell, and the switch ------------------------------------------


def test_desktop_shell_gets_the_policy_in_report_only_form_for_now(
    client, initialized_app, monkeypatch
):
    app, _ = initialized_app
    monkeypatch.delenv("MAILREPO_CSP", raising=False)
    monkeypatch.setitem(app.config, "LAUNCH_NONCE", "x")
    resp = client.get("/auth/login")
    assert "Content-Security-Policy" not in resp.headers
    policy = _directives(resp.headers["Content-Security-Policy-Report-Only"])
    # pywebview's bridge needs eval; injected markup still needs what is not there.
    assert "'unsafe-eval'" in policy["script-src"]
    assert "'unsafe-inline'" not in policy["script-src"]


def test_browser_mode_never_allows_eval(client, initialized_app, monkeypatch):
    monkeypatch.delenv("MAILREPO_CSP", raising=False)
    resp = client.get("/auth/login")
    assert "'unsafe-eval'" not in _directives(resp.headers["Content-Security-Policy"])["script-src"]
    assert "Content-Security-Policy-Report-Only" not in resp.headers


@pytest.mark.parametrize(
    "setting,desktop,enforced,reported",
    [
        ("enforce", True, True, False),
        ("report", False, False, True),
        ("off", False, False, False),
        ("off", True, False, False),
        ("nonsense", False, True, False),
        ("nonsense", True, False, True),
    ],
)
def test_the_environment_switch(
    client, initialized_app, monkeypatch, setting, desktop, enforced, reported
):
    app, _ = initialized_app
    monkeypatch.setenv("MAILREPO_CSP", setting)
    if desktop:
        monkeypatch.setitem(app.config, "LAUNCH_NONCE", "x")
    resp = client.get("/auth/login")
    assert ("Content-Security-Policy" in resp.headers) is enforced
    assert ("Content-Security-Policy-Report-Only" in resp.headers) is reported
