"""
The one URL fetcher for every WeasyPrint render in MailRepo.

An email's HTML names the resources WeasyPrint fetches, so the fetcher
is the boundary between attacker-chosen markup and the user's disk and
network. WeasyPrint's default fetcher resolves ``file://`` (and ``ftp://``),
and its metadata pass turns every ``<link rel="attachment">`` in the
document into an embedded PDF attachment fetched through that fetcher —
so an email could ride the user's key file or SSH key into a PDF they
then send to someone else.

Every render therefore goes through :func:`make_url_fetcher`, which
allows ``data:`` always, ``http(s):`` only when the user asked for remote
content, and returns an empty image for anything else. Nothing here can
ever resolve a local path.
"""

from __future__ import annotations

_EMPTY_PNG_MIME = "image/png"


def allowed_schemes(load_remote: bool) -> frozenset[str]:
    """Schemes a render may fetch. ``data:`` always; ``http(s):`` on request."""
    schemes = {"data"}
    if load_remote:
        schemes |= {"http", "https"}
    return frozenset(schemes)


def scheme_of(url: str) -> str:
    """Lowercase URL scheme, '' if there is none."""
    head, sep, _ = (url or "").partition(":")
    if not sep:
        return ""
    return head.strip().lower()


def make_url_fetcher(load_remote: bool):
    """Build a WeasyPrint ``url_fetcher`` confined to :func:`allowed_schemes`.

    Prefers WeasyPrint's ``URLFetcher`` class (66+, the supported API);
    falls back to wrapping the deprecated ``default_url_fetcher`` on older
    releases. Disallowed schemes get an empty PNG rather than an
    exception so blocked tracking pixels do not flood the log.
    """
    allowed = allowed_schemes(load_remote)

    try:
        from weasyprint.urls import URLFetcher, URLFetcherResponse
    except ImportError:  # pragma: no cover - WeasyPrint < 66
        URLFetcher = None  # type: ignore[assignment]

    if URLFetcher is None:  # pragma: no cover
        from weasyprint import default_url_fetcher

        def _legacy(url):
            if scheme_of(url) in allowed:
                return default_url_fetcher(url)
            return {"mime_type": _EMPTY_PNG_MIME, "string": b""}

        return _legacy

    class _GuardedFetcher(URLFetcher):
        def fetch(self, url, headers=None):
            if scheme_of(url) not in allowed:
                return URLFetcherResponse(url, body=b"", headers={"Content-Type": _EMPTY_PNG_MIME})
            return super().fetch(url, headers)

    # allowed_protocols is a second fence behind the check above: even a
    # code path that bypasses fetch() (none known) could not open file://.
    return _GuardedFetcher(allowed_protocols=allowed, allow_redirects=load_remote)
