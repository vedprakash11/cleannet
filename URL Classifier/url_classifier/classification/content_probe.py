"""
Optional Layer 3: lightweight HTML text signals (enable with ENABLE_CONTENT_PROBE=1).

Includes age-gate / 18+ disclaimer copy common on adult sites (not just vulgar keywords).
Use with care (timeouts, robots, legal).
"""

from __future__ import annotations

import os
import re
from typing import Optional, Tuple

import requests

from url_classifier.classification.url_utils import SESSION, ensure_scheme

ADULT_TERMS = re.compile(
    r"\b(porn|xxx|nsfw|explicit|adult\s*content|sex\s*tape)\b",
    re.I,
)

# High-precision phrases from typical "you must be 18" interstitials
_ADULT_GATE_STRONG = [
    re.compile(r"explicit\s+depictions?\s+of\s+sexual\s+activity", re.I),
    re.compile(
        r"not\s+offended\s+by\s+nudity\s+and\s+explicit\s+depictions", re.I
    ),
    re.compile(r"age-restricted\s+materials?", re.I),
    re.compile(
        r"do\s+not\s+have\s+(?:authorization|permission)\s+to\s+enter\s+this\s+website",
        re.I,
    ),
]

_ADULT_GATE_WEAK = [
    re.compile(r"under\s+the\s+age\s+of\s+18", re.I),
    re.compile(r"age\s+of\s+majority\s+in\s+the\s+location", re.I),
    re.compile(r"penalty\s+of\s+perjury", re.I),
    re.compile(r"certify.{0,120}?you\s+are\s+an\s+adult", re.I | re.DOTALL),
    re.compile(r"by\s+clicking.{0,80}?(?:['\"])?\s*enter", re.I | re.DOTALL),
    re.compile(
        r"(?:enter|visit)\s+this\s+website\s+you.{0,40}?agree",
        re.I | re.DOTALL,
    ),
    re.compile(r"terms\s+and\s+conditions", re.I),
    re.compile(r"accessing\s+this\s+website", re.I),
    re.compile(r"hereby\s+agree\s+to\s+comply", re.I),
]

_AGE_CONTEXT = re.compile(
    r"(?:18|age-restricted|majority|adult\s+content|nudity)",
    re.I,
)

PHISH_TERMS = re.compile(
    r"\b(verify\s*your\s*account|suspended|unusual\s*activity|confirm\s*billing)\b",
    re.I,
)

MAX_BYTES = 400_000


def _adult_age_gate_confidence(text: str) -> Optional[float]:
    """
    Match stacks of 18+ / age-gate boilerplate. Returns confidence or None.
    """
    strong = sum(1 for p in _ADULT_GATE_STRONG if p.search(text))
    if strong >= 1:
        return min(0.93, 0.82 + 0.05 * min(strong, 3))

    weak = sum(1 for p in _ADULT_GATE_WEAK if p.search(text))
    has_age_context = _AGE_CONTEXT.search(text) is not None

    if weak >= 3 and has_age_context:
        return min(0.88, 0.72 + 0.04 * weak)
    if weak >= 4:
        return 0.82
    return None


def content_signals(url: str, timeout: float = 5.0) -> Optional[Tuple[str, float]]:
    """
    If enabled via env, fetch page and return (label, confidence) or None.
    """
    if os.environ.get("ENABLE_CONTENT_PROBE", "").lower() not in ("1", "true", "yes"):
        return None
    url = ensure_scheme(url)
    try:
        r = SESSION.get(url, timeout=timeout, stream=True, allow_redirects=True)
        r.raise_for_status()
        chunk = b""
        for part in r.iter_content(chunk_size=65536):
            chunk += part
            if len(chunk) >= MAX_BYTES:
                break
        r.close()
        text = chunk.decode("utf-8", errors="ignore")
    except (requests.RequestException, OSError):
        return None

    gate = _adult_age_gate_confidence(text)
    if gate is not None:
        return ("adult", gate)

    text_l = text.lower()
    if ADULT_TERMS.search(text_l):
        return ("adult", 0.75)
    if PHISH_TERMS.search(text_l):
        return ("phishing", 0.65)
    return None
