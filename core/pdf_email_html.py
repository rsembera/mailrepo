"""
MailRepo - Making one email's HTML safe to place in a combined PDF.

A PDF export is one document: cover page, then every email, rendered by
WeasyPrint in a single pass. Each email's HTML and CSS are whatever its
sender wrote, so without care one email can change the rest of the
document:

* an unclosed ``<style>``, comment or ``<div>`` swallows or restyles
  every email after it;
* a stylesheet rule that is not confined (``body { display: none }``, an
  unterminated rule, ``@import`` of a ``data:`` stylesheet) applies to
  the cover page and to every other email;
* ``position: fixed`` is repeated by WeasyPrint on every page.

Whether by accident (sloppy newsletters) or on purpose (a correspondent
who wants an export to misrepresent the record), the result is a PDF
that does not show what the archive holds.

So the email is parsed with the same HTML and CSS parsers WeasyPrint
uses (tinyhtml5, tinycss2), which removes any difference of opinion
about where a tag or a rule ends, and written back out as a balanced
fragment in which every style rule is confined to this email.
"""

from __future__ import annotations

import html as html_module
import re

import tinycss2
import tinyhtml5

SVG_NS = "http://www.w3.org/2000/svg"
MATHML_NS = "http://www.w3.org/1998/Math/MathML"
XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"

# Removed with everything inside them. None has a use in a printed
# email; several fetch or embed things (link, iframe, object, embed).
_DROP_ELEMENTS = frozenset(
    {
        "script", "link", "base", "meta", "title", "iframe", "frame",
        "frameset", "object", "embed", "applet", "template", "noembed",
        "noframes", "o:p",
    }
)  # fmt: skip

# Raw-text elements: their content would be re-read as markup or shown
# with its escapes if written back under the same name.
_RENAME_ELEMENTS = {"xmp": "pre", "plaintext": "pre", "listing": "pre"}

_VOID_ELEMENTS = frozenset(
    {
        "area", "br", "col", "hr", "img", "input", "param", "source",
        "track", "wbr",
    }
)  # fmt: skip

_ATTR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")
_TAG_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")

# Selectors that, when seen as the entirety of a selector clause, refer to
# the document root or all elements. After scoping, these should match
# elements inside this email's shell (not the document <body>).
_DOC_ROOT_SELECTORS = {"html", "body", ":root", "*"}

# At-rules that hold ordinary rules, which are confined in turn.
_NESTED_AT_RULES = frozenset({"media", "supports", "layer", "container"})

# At-rules kept as written: they define names, they do not style anything.
_PASS_AT_RULES = frozenset({"font-face", "keyframes", "-webkit-keyframes", "-moz-keyframes"})

# Everything else (@import, @page, @namespace, @charset, anything new) is
# dropped: @import brings in a whole unconfined stylesheet, @page is the
# document's, not the email's.

# Declarations that reach beyond the element they are on.
_DROP_PROPERTIES = frozenset(
    {"bookmark-level", "bookmark-label", "bookmark-state", "string-set", "page"}
)
# position: fixed repeats on every page and absolute leaves the email's
# box; both are refused by allowing only what stays put. A var() or any
# other value is refused too, since what it resolves to cannot be known.
_SAFE_POSITIONS = frozenset({"static", "relative"})


def sanitize_email_html(html: str, *, scope: str) -> str:
    """Return ``html`` as a balanced fragment confined to ``.email-scope-<scope>``.

    The ``<html>``, ``<head>`` and ``<body>`` of the email become
    ``<div class="email-shell email-shell-...">`` so that their attributes
    (a background on ``<body>``, say) still apply, to this email only.
    """
    scope_class = f"email-scope-{scope}"
    root = tinyhtml5.parse(html, namespace_html_elements=False)

    head = root.find("head")
    body = root.find("body")

    out: list[str] = []
    out.append(_open_shell("html", root.attrib))
    out.append(_open_shell("head", head.attrib if head is not None else {}))
    if head is not None:
        # Only the stylesheets; nothing else in a head is content.
        for child in head.iter():
            if _local_name(child) == "style":
                out.append(_style_block(child, scope_class))
    out.append("</div>")
    out.append(_open_shell("body", body.attrib if body is not None else {}))
    if body is not None:
        _write_children(body, out, scope_class)
    out.append("</div></div>")
    return "".join(out)


def scope_css(css: str, scope_class: str) -> str:
    """Rewrite a stylesheet so every rule applies only inside ``.scope_class``.

    Anything that is not a complete, understood rule is left out.
    """
    rules = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
    return "\n".join(filter(None, (_scope_rule(rule, scope_class) for rule in rules)))


def clean_declarations(css: str) -> str:
    """Clean the value of a ``style`` attribute (see ``_declarations``)."""
    return _declarations(css)


# --- HTML -----------------------------------------------------------------


def _local_name(element) -> str:
    """Lower-case tag name without namespace; '' for comments and the like."""
    tag = element.tag
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{"):
        tag = tag.split("}", 1)[1]
    return tag.lower()


def _open_shell(part: str, attrs) -> str:
    """Opening tag of the div standing in for <html>, <head> or <body>."""
    attrs = dict(attrs)
    classes = f"email-shell email-shell-{part}"
    if attrs.get("class"):
        classes += " " + attrs["class"]
    attrs["class"] = classes
    return f"<div{_attributes(attrs)}>"


def _attributes(attrs) -> str:
    parts = []
    for name, value in attrs.items():
        if name.startswith("{"):
            ns, local = name[1:].split("}", 1)
            prefix = {XLINK_NS: "xlink:", XML_NS: "xml:"}.get(ns)
            if prefix is None:
                continue
            name = prefix + local
        if not _ATTR_NAME.match(name):
            continue
        lower = name.lower()
        if lower.startswith("on"):
            continue
        if lower == "style":
            value = _declarations(value)
            if not value:
                continue
        elif lower == "rel" and "attachment" in value.lower():
            # WeasyPrint embeds the target of rel=attachment in the PDF.
            continue
        parts.append(f' {name}="{html_module.escape(value, quote=True)}"')
    return "".join(parts)


def _style_block(element, scope_class: str) -> str:
    css = "".join(element.itertext())
    # Word's stylesheets are for Word; they were always left out.
    if "mso-" in css.lower() or "MsoNormal" in css:
        return ""
    scoped = scope_css(css, scope_class)
    if not scoped:
        return ""
    # A stylesheet cannot contain its own end tag.
    return "<style>" + scoped.replace("</", "<\\/") + "</style>"


def _write_children(element, out: list[str], scope_class: str) -> None:
    if element.text:
        out.append(html_module.escape(element.text, quote=False))
    for child in element:
        _write_element(child, out, scope_class)
        if child.tail:
            out.append(html_module.escape(child.tail, quote=False))


def _write_element(element, out: list[str], scope_class: str) -> None:
    name = _local_name(element)
    if not name:
        return  # comment, processing instruction
    if name in _DROP_ELEMENTS:
        return
    if name == "style":
        out.append(_style_block(element, scope_class))
        return
    if ":" in name or not _TAG_NAME.match(name):
        # Office and other namespace tags (<v:shape>, <w:...>): keep
        # what they contain, not the tag.
        _write_children(element, out, scope_class)
        return
    if name in ("html", "head", "body"):
        # A second one, misplaced; its content is still content.
        _write_children(element, out, scope_class)
        return

    tag = element.tag
    if tag.startswith("{"):
        # SVG and MathML names are case-sensitive (foreignObject).
        written = tag.split("}", 1)[1]
    else:
        written = _RENAME_ELEMENTS.get(name, name)

    out.append(f"<{written}{_attributes(element.attrib)}>")
    if written in _VOID_ELEMENTS:
        return
    _write_children(element, out, scope_class)
    out.append(f"</{written}>")


# --- CSS ------------------------------------------------------------------


def _scope_rule(rule, scope_class: str) -> str:
    if rule.type == "qualified-rule":
        selectors = _selectors(rule.prelude, scope_class)
        if not selectors:
            return ""
        return f"{selectors} {{ {_declarations(rule.content)} }}"

    if rule.type == "at-rule":
        keyword = rule.lower_at_keyword
        if rule.content is None:
            return ""  # @import, @charset, @namespace
        if keyword in _NESTED_AT_RULES:
            inner = tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
            body = "\n".join(filter(None, (_scope_rule(r, scope_class) for r in inner)))
            prelude = tinycss2.serialize(rule.prelude).strip()
            return f"@{keyword} {prelude} {{\n{body}\n}}"
        if keyword == "font-face":
            return f"@font-face {{ {_declarations(rule.content)} }}"
        if keyword in _PASS_AT_RULES:
            return rule.serialize()
    return ""


def _selectors(prelude, scope_class: str) -> str:
    """Selector list with each selector confined to the scope."""
    groups: list[list] = [[]]
    for token in prelude:
        if token.type == "literal" and token.value == ",":
            groups.append([])
        else:
            groups[-1].append(token)
    scoped = []
    for group in groups:
        selector = tinycss2.serialize(group).strip()
        if selector:
            scoped.append(_prefix_selector(selector, scope_class))
    return ", ".join(scoped)


def _prefix_selector(selector: str, scope_class: str) -> str:
    """Prefix a single selector with ``.scope_class``.

    Special cases:
    - Pure root selectors (html, body, *, :root) become ``.scope_class``
      itself, so e.g. ``body { background: cream }`` ends up styling the
      email's shell div.
    - Any selector starting with html/body is rewritten to drop the
      html/body part, since those tags no longer exist (they are now
      ``<div class="email-shell">``).
    """
    if selector in _DOC_ROOT_SELECTORS:
        return f".{scope_class}"

    m = re.match(r"^(html|body)\b\s*(>?\s*)?", selector, flags=re.IGNORECASE)
    if m:
        rest = selector[m.end() :].lstrip()
        if not rest:
            return f".{scope_class}"
        return f".{scope_class} {rest}"

    return f".{scope_class} {selector}"


def _declarations(content) -> str:
    """Declarations, minus those that reach outside the element.

    ``content`` is a string (a style attribute) or the tokens of a rule
    body. Anything that is not a plain declaration is left out.
    """
    kept = []
    for item in tinycss2.parse_declaration_list(content, skip_comments=True, skip_whitespace=True):
        if item.type != "declaration":
            continue
        name = item.lower_name
        if name in _DROP_PROPERTIES:
            continue
        if name == "position" and not _is_safe_position(item.value):
            continue
        value = tinycss2.serialize(item.value).strip()
        important = " !important" if item.important else ""
        kept.append(f"{item.name}: {value}{important}")
    return "; ".join(kept)


def _is_safe_position(tokens) -> bool:
    words = [t for t in tokens if t.type not in ("whitespace", "comment")]
    return len(words) == 1 and words[0].type == "ident" and words[0].lower_value in _SAFE_POSITIONS
