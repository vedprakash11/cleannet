import math
import re
from typing import Optional
from urllib.parse import urlparse

from url_classifier.classification.url_utils import (
    extract_domain,
    is_shortener_host,
    path_depth,
    query_length,
    registrable_domain,
)

BAD_WORDS = (
    "login",
    "verify",
    "xxx",
    "free",
    "secure",
    "porn",
    "update",
    "confirm",
)

# Commonly abused TLDs (heuristic, not exhaustive)
RISKY_TLDS = frozenset(
    {
        "xyz",
        "top",
        "ru",
        "tk",
        "ml",
        "ga",
        "cf",
        "gq",
        "loan",
        "work",
        "click",
        "download",
        "zip",
        "mov",
        "win",
        "review",
        "accountant",
    }
)

_BRAND_TYPO = re.compile(
    r"(paypa1|amaz0n|app1e|micr0soft|goog1e|faceb00k|netf1ix|micros0ft)",
    re.I,
)


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = {}
    for c in s:
        counts[c] = counts.get(c, 0) + 1
    n = len(s)
    ent = 0.0
    for c in counts.values():
        p = c / n
        ent -= p * math.log2(p)
    return ent


def _tld(host: str) -> str:
    parts = host.lower().rstrip(".").split(".")
    return parts[-1] if parts else ""


def brand_spoof_hits(url: str) -> int:
    return len(_BRAND_TYPO.findall(url))


def extract_features(url: str, domain_age_days: Optional[float] = None) -> dict:
    """
    Lexical + structural features (Layer 1 + host heuristics).
    domain_age_days: set to -1.0 when unknown (default for training/inference speed).
    """
    raw = url if url.startswith("http") else "http://" + url
    parsed = urlparse(raw)
    netloc = parsed.netloc or ""
    path = parsed.path or ""
    host = extract_domain(url)

    age = domain_age_days
    if age is None:
        age = -1.0

    tld = _tld(host)
    tld_risk = 1.0 if tld in RISKY_TLDS else 0.0
    reg = registrable_domain(host)
    reg_ent = shannon_entropy(reg.split(".")[0]) if reg else 0.0

    has_double_slash = int("//" in path)
    has_userinfo = int(bool(parsed.username))

    return {
        "url_length": len(url),
        "domain_length": len(host),
        "num_dots": url.count("."),
        "num_digits": sum(c.isdigit() for c in url),
        "num_special": len(re.findall(r"[^a-zA-Z0-9]", url)),
        "has_https": int("https" in url.lower()),
        "has_ip": int(bool(re.match(r"^\d+\.\d+\.\d+\.\d+", host))),
        "num_subdomains": max(0, host.count(".")),
        "path_length": len(path),
        "path_depth": float(path_depth(url)),
        "query_length": float(query_length(url)),
        "url_entropy": shannon_entropy(url),
        "domain_entropy": shannon_entropy(host),
        "registrable_entropy": reg_ent,
        "tld_risk": tld_risk,
        "is_shortener": float(is_shortener_host(host)),
        "brand_spoof_hits": float(brand_spoof_hits(url)),
        "has_double_slash_path": float(has_double_slash),
        "has_userinfo": float(has_userinfo),
        "punycode_domain": float("xn--" in netloc.lower()),
        "domain_age_days": float(age),
    }


def keyword_flag(url: str) -> bool:
    u = url.lower()
    return any(word in u for word in BAD_WORDS)


def rule_based(url: str) -> Optional[str]:
    u = url.lower()
    adult_tokens = ("xxx", "porn", "adult", "sex", "nsfw")
    phishing_tokens = ("phishing-login-bank", "verify-account-now", "secure-login-update")
    if any(t in u for t in adult_tokens):
        return "adult"
    if any(t in u for t in phishing_tokens):
        return "phishing"
    return None
