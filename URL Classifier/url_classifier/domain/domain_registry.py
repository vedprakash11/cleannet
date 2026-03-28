"""Domain-level reputation: load lists built from threat feeds + top sites (see build_domain_registry.py)."""

from __future__ import annotations

import os
from typing import Dict, Optional, Set

import pandas as pd

# Higher index = checked first when resolving conflicts at build time only.
LABEL_PRIORITY = ("malware", "phishing", "adult", "safe")


class DomainRegistry:
    """
    Fast lookups: full hostname and registrable-domain fallback.
    Inference order: malware set -> phishing -> adult -> safe allowlist.
    """

    def __init__(self) -> None:
        self._malware: Set[str] = set()
        self._phishing: Set[str] = set()
        self._adult: Set[str] = set()
        self._safe: Set[str] = set()

    def load_csv(self, path: str) -> None:
        if not os.path.isfile(path):
            return
        df = pd.read_csv(path, dtype=str)
        if "domain" not in df.columns or "label" not in df.columns:
            return
        for _, row in df.iterrows():
            dom = str(row["domain"]).strip().lower().rstrip(".")
            if not dom:
                continue
            label = str(row["label"]).strip().lower()
            if label == "malware":
                self._malware.add(dom)
            elif label == "phishing":
                self._phishing.add(dom)
            elif label == "adult":
                self._adult.add(dom)
            elif label == "safe":
                self._safe.add(dom)

    def lookup_host(self, host: str, registrable: str) -> Optional[str]:
        """Return label if host or its registrable domain is in a list (severity order)."""
        h = host.lower().rstrip(".")
        r = registrable.lower().rstrip(".")
        for label, bucket in (
            ("malware", self._malware),
            ("phishing", self._phishing),
            ("adult", self._adult),
            ("safe", self._safe),
        ):
            if h in bucket or r in bucket:
                return label
        return None

    def stats(self) -> Dict[str, int]:
        return {
            "malware": len(self._malware),
            "phishing": len(self._phishing),
            "adult": len(self._adult),
            "safe": len(self._safe),
        }


def default_registry_path(base_dir: Optional[str] = None) -> str:
    """Path to domain_registry.csv (under `data/` when using project layout)."""
    if base_dir is not None:
        return os.path.join(base_dir, "data", "domain_registry.csv")
    from url_classifier.paths import data_dir

    return str(data_dir() / "domain_registry.csv")
