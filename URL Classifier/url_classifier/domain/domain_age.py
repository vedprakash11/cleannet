"""Optional domain age via WHOIS (slow; use mainly offline or sparingly)."""

from __future__ import annotations

import datetime as dt
from typing import Optional


def domain_age_days(domain: str) -> Optional[float]:
    """
    Return approximate days since domain creation, or None if unavailable.
    Requires: pip install python-whois
    """
    try:
        import whois  # type: ignore
    except ImportError:
        return None

    try:
        w = whois.whois(domain)
        created = w.creation_date
        if created is None:
            return None
        if isinstance(created, list):
            created = created[0]
        if isinstance(created, str):
            return None
        now = dt.datetime.now(tz=created.tzinfo) if created.tzinfo else dt.datetime.now()
        delta = now - created.replace(tzinfo=None) if not created.tzinfo else now - created
        return max(0.0, delta.total_seconds() / 86400.0)
    except Exception:
        return None
