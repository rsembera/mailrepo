"""One email's HTML and CSS cannot change the rest of a combined PDF."""

import io

import pytest
import tinycss2
import tinyhtml5

from core import pdf_export
from core.pdf_email_html import clean_declarations, sanitize_email_html, scope_css

SCOPE = ".email-scope-e1"


def _clean(html):
    return sanitize_email_html(html, scope="e1")


def _in_document(fragment):
    """Parse the fragment as it sits in an export: wrapper, then the next section."""
    doc = f'<body><div id="wrap">{fragment}</div><p id="after">AFTER</p></body>'
    return tinyhtml5.parse(doc, namespace_html_elements=False).find("body")


def _rules(css):
    """Every style rule in a stylesheet, including those inside @media and the like."""
    found = []

    def walk(rules):
        for rule in rules:
            if rule.type == "qualified-rule":
                # Split the selector list as the parser sees it: a comma
                # inside :is(...) or behind a backslash separates nothing.
                group = []
                for token in [*rule.prelude, None]:
                    if token is None or (token.type == "literal" and token.value == ","):
                        found.append(tinycss2.serialize(group).strip())
                        group = []
                    else:
                        group.append(token)
            elif rule.type == "at-rule" and rule.content is not None:
                if rule.lower_at_keyword in ("media", "supports", "layer", "container"):
                    walk(
                        tinycss2.parse_rule_list(
                            rule.content, skip_comments=True, skip_whitespace=True
                        )
                    )
                else:
                    assert rule.lower_at_keyword in ("font-face", "keyframes"), (
                        rule.lower_at_keyword
                    )
            else:
                raise AssertionError(f"unexpected {rule.type}: {rule.serialize()!r}")

    walk(tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True))
    return found


def _assert_confined(css):
    for selector in _rules(css):
        assert selector.startswith(SCOPE), selector


UNBALANCED = [
    "<p>one</p><style>body{display:none}",
    "<p>one</p><!-- never closed",
    "<div><div style='display:none'><p>one</p>",
    "<p>one</p><textarea>",
    "<p>one</p><title>",
    "<p>one</p><script>var a = '",
    "<p>one</p><xmp>",
    "<p>one</p><plaintext>",
    "<table><tr><td>one",
    "<p>one</p></div></div></div>",
    "<p>one</p><select><option>",
    "<p>one</p><iframe>",
    "<p>one</p><noscript>",
    "<p>one</p><svg><style>",
    "<p>one</p><math><mtext>",
    "</body></html><p>one</p>",
]


@pytest.mark.parametrize("html", UNBALANCED)
def test_what_follows_an_email_stays_outside_it(html):
    body = _in_document(_clean(html))
    children = [c for c in body if isinstance(c.tag, str)]
    assert [c.get("id") for c in children] == ["wrap", "after"]
    assert "".join(children[1].itertext()) == "AFTER"


LEAKY_CSS = [
    "body{display:none}",
    "p{color:red} body{display:none",
    'p{content:"}"} body{display:none}',
    "p{content:'}'} body{display:none}",
    "p{color:red /* } body{display:none} */ }",
    "} body{display:none}",
    "}} * {display:none}",
    '@import url("data:text/css,body{display:none}");',
    "@import 'x.css'; body{display:none}",
    "@page{size:1in 1in} @page :first{margin:0}",
    "@namespace svg url(http://www.w3.org/2000/svg); body{display:none}",
    "@media print{ body{display:none} .cover{display:none} }",
    "@media print{ @media screen { html, body { display:none } } }",
    "@supports (display:grid){ *{display:none} }",
    "@media print{ body{display:none}",
    "html,body,*{display:none}",
    ":root{display:none} .cover,.email-header{display:none}",
    "a:is(b,c), body > .cover {display:none}",
    r"bod\79{display:none}",
    r".cover\,.x{display:none}",
    "@unknown{ body{display:none} }",
    "@font-face{font-family:x;src:url(data:font/woff2;base64,AAAA)} body{display:none}",
    "<!-- body{display:none} -->",
    "@keyframes k{from{opacity:0}to{opacity:1}} .cover{animation:k 1s}",
    "@charset 'utf-8'; .cover{display:none}",
]


@pytest.mark.parametrize("css", LEAKY_CSS)
def test_every_rule_is_confined_to_the_email(css):
    _assert_confined(scope_css(css, "email-scope-e1"))


@pytest.mark.parametrize("css", LEAKY_CSS)
def test_style_blocks_in_the_fragment_are_confined(css):
    body = _in_document(_clean(f"<style>{css}</style><p>one</p><style>{css}"))
    styles = [e for e in body.iter() if e.tag == "style"]
    for style in styles:
        _assert_confined("".join(style.itertext()))
    # None of it escaped the wrapper.
    assert all(s in list(body[0].iter()) for s in styles)


@pytest.mark.parametrize(
    "css",
    [
        r'p{content:"\3c/style>\3cp id=out>OUT"}',
        r'a[title="\3c/style>\3cstyle>body{display:none}"]{color:red}',
        r'p{content:"\3c /style>"} q{content:"\00003c/STYLE >"}',
    ],
)
def test_a_style_block_cannot_end_itself_early(css):
    """The CSS parser turns \3c back into "<"; the block must still not close."""
    body = _in_document(_clean(f"<style>{css}</style><p>x</p>"))
    assert body.find(".//*[@id='out']") is None
    styles = [e for e in body.iter() if e.tag == "style"]
    assert len(styles) == 1
    _assert_confined("".join(styles[0].itertext()))
    assert [c.get("id") for c in body if isinstance(c.tag, str)] == ["wrap", "after"]


def test_ordinary_rules_survive_scoping():
    css = scope_css(
        "p, td.x > a:hover { color: red; margin: 0 !important } "
        "@media (max-width:600px){ .col{width:100%} } "
        "body{background:#fafafa} html body .y{font:12px Arial}",
        "email-scope-e1",
    )
    assert f"{SCOPE} p, {SCOPE} td.x > a:hover {{ color: red; margin: 0 !important }}" in css
    assert "@media (max-width:600px)" in css and f"{SCOPE} .col {{ width: 100% }}" in css
    assert f"{SCOPE} {{ background: #fafafa }}" in css
    assert f"{SCOPE} body .y" in css or f"{SCOPE} .y" in css


def test_data_urls_and_strings_keep_their_punctuation():
    css = scope_css(
        'p{background:url(data:image/png;base64,AA,BB==);content:"a;b:c{d}"}', "email-scope-e1"
    )
    assert "url(data:image/png;base64,AA,BB==)" in css
    assert '"a;b:c{d}"' in css


POSITIONS = [
    ("position:fixed", False),
    ("position:absolute", False),
    ("position: FIXED !important", False),
    (r"pos\69tion: fixed", False),
    (r"position: f\69xed", False),
    ("position:/**/fixed", False),
    ("--p: fixed; position: var(--p)", False),
    ("position: sticky", False),
    ("position: running(header)", False),
    ("position: fixed fixed", False),
    ("position: relative fixed", False),
    ("position: relative", True),
    ("POSITION: Static", True),
]


@pytest.mark.parametrize("style,kept", POSITIONS)
def test_only_positions_that_stay_in_the_email_are_kept(style, kept):
    cleaned = clean_declarations(f"color: red; {style}; top: 0")
    names = [
        d.lower_name for d in tinycss2.parse_declaration_list(cleaned) if d.type == "declaration"
    ]
    assert ("position" in names) is kept
    assert "color" in names and "top" in names

    in_rule = scope_css(f"div{{ {style} }}", "email-scope-e1")
    rule = tinycss2.parse_stylesheet(in_rule, skip_whitespace=True)[0]
    names = [
        d.lower_name
        for d in tinycss2.parse_declaration_list(rule.content)
        if d.type == "declaration"
    ]
    assert ("position" in names) is kept


def test_position_hidden_in_an_entity_is_still_seen():
    out = _clean('<div style="position&#58;fixed;top:0;color:red">x</div>')
    assert "position" not in out
    assert "color: red" in out and "top: 0" in out


def test_declarations_that_write_to_the_pdf_outline_or_page_are_dropped():
    cleaned = clean_declarations(
        "bookmark-level:1; bookmark-label:'x'; string-set:t 'x'; page:wide; color:red"
    )
    assert cleaned == "color: red"


def test_style_attribute_cannot_hold_rules():
    cleaned = clean_declarations("color:red } body { display:none")
    assert "body" not in cleaned or "{" not in cleaned
    out = _clean('<p style="color:red } body { display:none">x</p>')
    assert "{" not in out.split("<p", 1)[1].split(">", 1)[0]


@pytest.mark.parametrize(
    "html",
    [
        "<script>alert(1)</script><p>keep</p>",
        '<link rel="stylesheet" href="http://x/y.css"><p>keep</p>',
        '<link rel="attachment" href="file:///etc/passwd"><p>keep</p>',
        '<base href="file:///"><p>keep</p>',
        '<meta http-equiv="refresh" content="0;url=http://x"><p>keep</p>',
        '<iframe src="http://x"></iframe><p>keep</p>',
        '<object data="http://x"></object><p>keep</p>',
        '<embed src="http://x"><p>keep</p>',
        "<svg><script>alert(1)</script></svg><p>keep</p>",
        "<p>keep</p><o:p>office</o:p>",
        "<title>window title</title><p>keep</p>",
        '<p>keep</p><div><link rel="attachment" href="data:text/plain,passwd"></div>',
        '<p>keep</p><div><base href="file:///"><meta name="x" content="passwd"></div>',
    ],
)
def test_elements_with_no_place_in_a_printed_email_are_removed(html):
    out = _clean(html)
    assert "keep" in out
    for gone in (
        "<script",
        "<link",
        "<base",
        "<meta",
        "<iframe",
        "<object",
        "<embed",
        "<o:p",
        "<title",
    ):
        assert gone not in out
    for text in ("alert(1)", "office", "window title", "passwd"):
        assert text not in out


def test_office_namespace_tags_go_but_their_content_stays():
    out = _clean("<p>a<v:shape><v:textbox>inside</v:textbox></v:shape>b</p>")
    assert "inside" in out and "v:" not in out


def test_attachment_links_and_event_handlers_are_stripped():
    out = _clean(
        '<a rel="attachment" href="data:text/plain,x" onclick="x()">file</a><img src="cid:1" onerror="x()">'
    )
    assert "attachment" not in out and "onclick" not in out and "onerror" not in out
    assert 'href="data:text/plain,x"' in out and 'src="cid:1"' in out


def test_body_and_html_attributes_carry_over_to_this_email_only():
    out = _clean(
        '<html lang="en"><body style="background:#eee" class="dark" bgcolor="#fff"><p>x</p></body></html>'
    )
    body = _in_document(out)
    shells = {e.get("class"): e for e in body.iter() if "email-shell" in (e.get("class") or "")}
    assert "email-shell email-shell-html" in shells
    body_shell = shells["email-shell email-shell-body dark"]
    assert body_shell.get("style") == "background: #eee"
    assert body_shell.get("bgcolor") == "#fff"


def test_head_contributes_only_its_stylesheets():
    out = _clean(
        "<head><title>T</title><style>p{color:red}</style><meta charset=utf-8></head><body><p>x</p>"
    )
    assert f"<style>{SCOPE} p {{ color: red }}</style>" in out
    assert "T<" not in out and "charset" not in out


def test_word_stylesheets_are_left_out():
    out = _clean("<style>p.MsoNormal{mso-style-parent:''}</style><p class=MsoNormal>x</p>")
    assert "<style" not in out and ">x</p>" in out


def test_text_and_attributes_are_written_back_escaped():
    out = _clean(
        '<p title="a &quot;b&quot; <c>">1 &lt; 2 &amp; 3 &gt; 2</p><textarea><b>raw</b></textarea>'
    )
    assert 'title="a &quot;b&quot; &lt;c&gt;"' in out
    assert "1 &lt; 2 &amp; 3 &gt; 2" in out
    assert "&lt;b&gt;raw&lt;/b&gt;" in out


def test_raw_text_elements_become_pre():
    out = _clean("<xmp><b>not bold</b></xmp>")
    assert "<pre>&lt;b&gt;not bold&lt;/b&gt;</pre>" in out


def test_svg_and_tables_come_through():
    out = _clean(
        '<table width="100%"><tr><td align="center">c</td></tr></table>'
        '<svg viewBox="0 0 1 1"><foreignObject><p>f</p></foreignObject><use xlink:href="#a"/></svg><br><img src="data:x">'
    )
    assert '<td align="center">c</td>' in out
    assert "<foreignObject>" in out and 'viewBox="0 0 1 1"' in out and 'xlink:href="#a"' in out
    assert "<br>" in out and "</br>" not in out and "</img>" not in out


def test_empty_and_plain_input():
    assert "email-shell-body" in _clean("")
    assert "just text" in _clean("just text")


# --- rendered --------------------------------------------------------------


def _render(bodies):
    from pypdf import PdfReader
    from weasyprint import HTML

    from core.pdf_fetcher import make_url_fetcher

    parts = ['<html><body><div class="cover">COVERPAGE</div>']
    for i, body in enumerate(bodies):
        parts.append(
            f'<section class="email">HEADER{i} {pdf_export._safe_render_body(body, "", i)}</section>'
        )
    parts.append("</body></html>")
    pdf = HTML(string="".join(parts), url_fetcher=make_url_fetcher(load_remote=False)).write_pdf()
    reader = PdfReader(io.BytesIO(pdf))
    return [page.extract_text() or "" for page in reader.pages]


RENDERED = [
    "<style>p{color:red} body{display:none</style><p>FIRST</p>",
    "<p>FIRST</p><style>body{display:none}",
    "<p>FIRST</p><!-- oops",
    '<style>@import url("data:text/css,body{display:none}");</style><p>FIRST</p>',
    '<style>p{content:"}"} body{display:none}</style><p>FIRST</p>',
    "<style>.cover, section, .email{display:none}</style><p>FIRST</p>",
    "<div><div style='display:none'><p>hidden</p>",
]


@pytest.mark.parametrize("first", RENDERED)
def test_rendered_export_still_shows_the_cover_and_the_next_email(first):
    text = " ".join(_render([first, "<p>SECONDEMAIL</p>"]))
    assert "COVERPAGE" in text
    assert "HEADER0" in text and "HEADER1" in text
    assert "SECONDEMAIL" in text


def test_fixed_content_is_not_repeated_on_every_page():
    filler = "".join(f"<p>line {i}</p>" for i in range(200))
    overlay = '<div style="position:fixed;top:0;left:0">STAMPED</div>'
    pages = _render([overlay + "<p>FIRST</p>", filler])
    assert len(pages) > 2
    assert sum("STAMPED" in page for page in pages) == 1
