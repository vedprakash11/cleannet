"""URL parsing helpers: registered domain extraction, redirect resolution."""

from __future__ import annotations

from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests

# Known URL shorteners — resolve redirects before domain reputation lookup
SHORTENER_HOSTS = frozenset(
    {
        "bit.ly",
        "tinyurl.com",
        "t.co",
        "goo.gl",
        "ow.ly",
        "is.gd",
        "buff.ly",
        "rebrand.ly",
        "cutt.ly",
        "short.link",
    }
)

# Browser-like UA — many sites/CDNs block non-browser clients or require Referer on images.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
)


def ensure_scheme(url: str) -> str:
    u = url.strip()
    if not u:
        return u
    if not u.startswith(("http://", "https://")):
        return "http://" + u
    return u


def extract_domain(url: str) -> str:
    """Return lowercase hostname without port (punycode as from IDNA)."""
    u = ensure_scheme(url)
    parsed = urlparse(u)
    host = parsed.hostname or ""
    return host.lower().rstrip(".")


def registrable_domain(host: str) -> str:
    """
    Best-effort eTLD+1: last two labels (not full PSL; breaks on co.uk etc.).
    Used with full-host matching so misclassified registrable pairs are rare.
    """
    host = host.lower().rstrip(".")
    parts = host.split(".")
    if len(parts) < 2:
        return host
    return ".".join(parts[-2:])


def is_shortener_host(host: str) -> bool:
    h = host.lower().rstrip(".")
    return h in SHORTENER_HOSTS or h.endswith(".bit.ly")


def query_length(url: str) -> int:
    u = ensure_scheme(url)
    q = urlparse(u).query
    return len(q)


def path_depth(url: str) -> int:
    u = ensure_scheme(url)
    path = urlparse(u).path or ""
    segments = [s for s in path.split("/") if s]
    return len(segments)


def resolve_redirects(url: str, max_hops: int = 8, timeout: float = 6.0) -> str:
    """
    Follow redirects; return final URL string (or original on failure).
    Used so bit.ly/... can be mapped to a registrable domain for reputation.
    """
    url = ensure_scheme(url)
    try:
        r = SESSION.get(
            url,
            allow_redirects=True,
            timeout=timeout,
            stream=True,
            headers={"Range": "bytes=0-0"},
        )
        try:
            final = r.url
        finally:
            r.close()
        return final
    except (requests.RequestException, OSError):
        return url
