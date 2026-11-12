"""Front-end checks.

The staging logic that can be separated from the page lives in
web/static/js/staged-key.js and state.js and is tested in Node
(tests/js). Those tests run from here when a recent Node is installed;
the checks on the source text below run everywhere.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "static" / "js"


def _sources():
    return {p: p.read_text(encoding="utf-8") for p in JS.rglob("*.js") if p.name != "lucide.min.js"}


def _node():
    """Path to a Node that loads the app's ES modules, or None."""
    node = shutil.which("node")
    if not node:
        return None
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=20).stdout
        major, minor = (int(x) for x in out.strip().lstrip("v").split(".")[:2])
    except Exception:
        return None
    # Plain .js files with import/export load as modules from 22.7.
    return node if (major, minor) >= (22, 7) else None


def test_staging_logic_in_node():
    node = _node()
    if node is None:
        pytest.skip("Node 22.7+ not installed")
    tests = sorted(str(p) for p in (ROOT / "tests" / "js").glob("*.test.mjs"))
    assert tests
    result = subprocess.run(
        [node, "--test", *tests], capture_output=True, text=True, cwd=ROOT, timeout=120
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]


def test_staged_emails_are_keyed_by_source_everywhere():
    """state.staged is only ever keyed through staged-key.js.

    A bare id (state.staged.has(emailId)) confuses message 12 in INBOX
    with message 12 in Sent.
    """
    offenders = []
    for path, text in _sources().items():
        for m in re.finditer(r"state\.staged\.(has|get|set|delete)\(([^)]*)\)", text):
            arg = m.group(2).split(",")[0].strip()
            if arg != "key" and not arg.startswith("stagedKey"):
                offenders.append(f"{path.name}: {m.group(0)}")
    assert offenders == []


def test_only_state_js_writes_staged_items_to_storage():
    """One writer, so an emptied set is removed rather than left behind."""
    offenders = [
        path.name
        for path, text in _sources().items()
        if path.name != "state.js" and re.search(r"sessionStorage\.(setItem|removeItem)", text)
    ]
    assert offenders == []
    state = (JS / "state.js").read_text(encoding="utf-8")
    assert "removeItem('stagedEmails')" in state
    assert "removeItem('stagedFolders')" in state


def test_every_staging_change_is_persisted():
    """Each place that changes the staged set saves it afterwards."""
    for name in (
        "components/staging.js",
        "components/thread-stage.js",
        "views/review.js",
        "views/folder-selection.js",
    ):
        assert "persistStaged()" in (JS / name).read_text(encoding="utf-8"), name
    staging = (JS / "components" / "staging.js").read_text(encoding="utf-8")
    confirm = staging[staging.index("export function confirmStage()") :]
    confirm = confirm[: confirm.index("export function updateButtonStates()")]
    # Both the folder branch and the email branch.
    assert confirm.count("persistStaged()") == 2


def test_data_attributes_are_not_backslash_escaped():
    """The old onclick escaper turned O'Connor into O\\'Connor in data-*."""
    for path, text in _sources().items():
        assert "escapeForOnclick" not in text, path.name
    selection = (JS / "views" / "folder-selection.js").read_text(encoding="utf-8")
    assert selection.count("const escapedPath = escapeHtml(folderPath);") == 2
    review = (JS / "views" / "review.js").read_text(encoding="utf-8")
    assert 'data-line-key="${escapeHtml(lineKey)}"' in review
    mail = (JS / "views" / "mail.js").read_text(encoding="utf-8")
    assert mail.count('data-folder-path="${escapeHtml(') == 2


def test_server_action_choice_does_not_outlive_its_commit():
    review = (JS / "views" / "review.js").read_text(encoding="utf-8")
    done = review[review.index("onComplete: async (data) =>") :]
    done = done[: done.index("onError")]
    assert "sourceActions = {}" in done
    unstage = review[review.index("function unstageAll()") :][:300]
    assert "sourceActions = {}" in unstage


def test_copy_as_reply_feedback_finds_its_button():
    mail = (JS / "views" / "mail.js").read_text(encoding="utf-8")
    template = (ROOT / "web" / "templates" / "main" / "index.html").read_text(encoding="utf-8")
    assert "[onclick=" not in mail
    assert '[data-tpl-action="copyAsReply"]' in mail
    assert 'data-tpl-action="copyAsReply"' in template


def test_dates_are_escaped_on_their_way_into_the_page():
    """formatDate() hands back what it was given when it cannot parse it.

    In a mailbox list that is the message's own Date header, which is
    whatever the sender wrote: `Date: <img src=x onerror=...>` used to
    go into the page as markup.
    """
    offenders = []
    for path, text in _sources().items():
        # Straight after a tag, i.e. as element content in a template.
        for m in re.finditer(r">\s*\$\{formatDate\(", text):
            offenders.append(f"{path.name}: {text[m.start() - 40 : m.end() + 30]!r}")
    assert offenders == []
    rows = (JS / "components" / "email-list.js").read_text(encoding="utf-8")
    assert "${escapeHtml(formatDate(email.date))}" in rows


def test_email_ids_are_escaped_in_list_rows():
    """Import ids carry file names ("eml-<name>"), which may hold quotes."""
    rows = (JS / "components" / "email-list.js").read_text(encoding="utf-8")
    assert '="${emailId}"' not in rows
    assert 'data-email-id="${escapeHtml(emailId)}"' in rows


def test_server_error_text_is_escaped_before_display():
    for path, text in _sources().items():
        for m in re.finditer(r"innerHTML = `[^`]*\$\{[^}]*\.error[^}]*\}", text):
            assert "escapeHtml(" in m.group(0), f"{path.name}: {m.group(0)[:120]}"


def _mail_function(name):
    mail = (JS / "views" / "mail.js").read_text(encoding="utf-8")
    start = mail.index(f"function {name}(")
    end = mail.find("\n}\n", start)
    return mail[start:end]


def test_email_html_is_never_parsed_into_this_page():
    """div.innerHTML = <email html> runs the email's onerror handlers.

    Even on an element that is never attached. Copy-as-reply did this.
    """
    body = _mail_function("htmlToPlainText")
    assert "DOMParser().parseFromString(html, 'text/html')" in body
    assert "innerHTML" not in body
    mail = (JS / "views" / "mail.js").read_text(encoding="utf-8")
    assert not re.search(r"\.innerHTML\s*=\s*[a-zA-Z_.]*html_body\s*;", mail)


def test_print_uses_a_frame_that_cannot_run_script():
    """A window opened from the page shares its origin; a sandboxed frame does not run script."""
    printing = _mail_function("printEmail")
    assert "window.open" not in printing
    assert "document.write" not in printing
    assert "buildPrintFrame(doc)" in printing
    assert "${printCsp(currentViewerContext.remoteLoaded === true)}" in printing

    frame = _mail_function("buildPrintFrame")
    sandbox = re.search(r"frame\.sandbox = '([^']*)'", frame).group(1).split()
    assert "allow-scripts" not in sandbox
    assert sorted(sandbox) == ["allow-modals", "allow-same-origin"]
    # The sandbox only binds a frame that has it before joining the page.
    assert (
        frame.index("frame.sandbox")
        < frame.index("appendChild(frame)")
        < frame.index(".write(doc)")
    )


def test_print_blocks_remote_content_unless_the_reader_loaded_it():
    csp = _mail_function("printCsp")
    blocked = re.search(r': "([^"]*)";', csp).group(1)
    allowed = re.search(r'\? "([^"]*)"', csp).group(1)
    for policy in (blocked, allowed):
        assert policy.startswith("default-src 'none'")
        assert "script-src" not in policy
    assert "img-src data:;" in blocked and "*" not in blocked
    assert "img-src * data:" in allowed
    remote = _mail_function("loadRemoteContent")
    assert "currentViewerContext.remoteLoaded = true" in remote


def test_an_image_only_email_is_not_reported_empty():
    mail = (JS / "views" / "mail.js").read_text(encoding="utf-8")
    assert r"/<img\b/i.test(email.html_body)" in mail


def test_list_loads_cannot_write_into_another_folders_list():
    """Every callback of a mailbox load checks it is still the one on screen.

    The cached rows show at once and the server's answer follows; a reader
    who had opened Sent by then got INBOX's rows under Sent's name, staged
    as if they came from Sent.
    """
    account = _mail_function("loadAccountEmails")
    assert "activeListStream.cancel()" in account
    assert "const isCurrent = beginListLoad(state);" in account
    for callback in ("onCached: (data) => {", "onComplete: (data) => {", "onError: (err) => {"):
        after = account[account.index(callback) + len(callback) :].lstrip()
        assert after.startswith("if (!isCurrent()) return;"), callback
    assert "if (!isCurrent() || !showingCache" in account
    # Nothing is written before the guard in any of them.
    assert account.count("state.emails = ") == 2

    folder = _mail_function("loadFolderEmails")
    assert "const isCurrent = beginListLoad(state);" in folder
    assert folder.index("if (!isCurrent()) return;") < folder.index("state.emails = ")
    failed = folder[folder.index("} catch (error) {") :]
    assert failed.index("if (!isCurrent()) return;") < failed.index("showError(")
