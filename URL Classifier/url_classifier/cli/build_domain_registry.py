"""
Build data/domain_registry.csv from URL CSVs + optional seeds.

Columns: domain, label, source
Conflict resolution (feeds only): malware > phishing > adult > safe.
Rows in seeds/curated_domains.csv override feed-derived labels for that domain.

Run after download_datasets.py or whenever data/*.csv changes:
  python build_domain_registry.py
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Tuple

import pandas as pd

from url_classifier.classification.url_utils import extract_domain
from url_classifier.domain.domain_registry import LABEL_PRIORITY

PRIORITY_MAP = {lab: i for i, lab in enumerate(LABEL_PRIORITY)}


def _load_urls_with_label(path: str, label: str, source: str) -> List[Tuple[str, str, str]]:
    if not os.path.isfile(path):
        return []
    df = pd.read_csv(path, dtype=str)
    col = None
    for c in df.columns:
        if c.lower() in ("url", "urls", "link"):
            col = c
            break
    if col is None:
        col = df.columns[0]
    out: List[Tuple[str, str, str]] = []
    for v in df[col].dropna().astype(str):
        v = v.strip()
        if not v:
            continue
        dom = extract_domain(v)
        if dom:
            out.append((dom, label, source))
    return out


def _load_seed_domains(path: str) -> List[Tuple[str, str, str]]:
    if not os.path.isfile(path):
        return []
    df = pd.read_csv(path, dtype=str)
    rows: List[Tuple[str, str, str]] = []
    for _, row in df.iterrows():
        d = str(row.get("domain", "")).strip().lower().rstrip(".")
        lab = str(row.get("label", "")).strip().lower()
        src = str(row.get("source", "seed")).strip()
        if d and lab in PRIORITY_MAP:
            rows.append((d, lab, src))
    return rows


def merge_feed_rows(rows: List[Tuple[str, str, str]]) -> Dict[str, Tuple[str, str]]:
    """Keep best label per domain by severity priority (malware > phishing > adult > safe)."""
    best: Dict[str, Tuple[str, str]] = {}
    for dom, lab, src in rows:
        if lab not in PRIORITY_MAP:
            continue
        if dom not in best:
            best[dom] = (lab, src)
        else:
            cur_lab, cur_src = best[dom]
            if PRIORITY_MAP[lab] < PRIORITY_MAP[cur_lab]:
                best[dom] = (lab, src)
    return best


def merge_rows_to_df(best: Dict[str, Tuple[str, str]]) -> pd.DataFrame:
    data = [{"domain": d, "label": t[0], "source": t[1]} for d, t in best.items()]
    return pd.DataFrame(data)


def build_registry(data_dir: str) -> bool:
    """Merge URL CSVs + seeds into data_dir/domain_registry.csv. Returns False if nothing to merge."""
    feed_rows: List[Tuple[str, str, str]] = []
    feed_rows.extend(_load_urls_with_label(os.path.join(data_dir, "safe.csv"), "safe", "tranco_urls"))
    feed_rows.extend(_load_urls_with_label(os.path.join(data_dir, "phishing.csv"), "phishing", "phishtank_urls"))
    feed_rows.extend(_load_urls_with_label(os.path.join(data_dir, "malware.csv"), "malware", "urlhaus_urls"))
    feed_rows.extend(_load_urls_with_label(os.path.join(data_dir, "adult.csv"), "adult", "blocklist_urls"))

    seeds = _load_seed_domains(os.path.join(data_dir, "seeds", "curated_domains.csv"))

    if not feed_rows and not seeds:
        return False

    best = merge_feed_rows(feed_rows) if feed_rows else {}
    # Curated seeds override feed labels (fix false positives like google.com in noisy feeds).
    for dom, lab, src in seeds:
        best[dom] = (lab, src)

    df = merge_rows_to_df(best)
    out_path = os.path.join(data_dir, "domain_registry.csv")
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} domains -> {out_path}")
    for lab in LABEL_PRIORITY:
        n = (df["label"] == lab).sum()
        if n:
            print(f"  {lab}: {n}")
    return True


_WIN_CMD = (
    "Windows Command Prompt (cmd.exe): do not add # comments after the command; "
    "Python will see them as extra arguments. Run only: python build_domain_registry.py"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build domain_registry.csv from data/*.csv",
        epilog=_WIN_CMD,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()

    from url_classifier.paths import data_dir

    data_dir_path = args.data_dir or str(data_dir())

    if not build_registry(data_dir_path):
        print("No rows to merge — run download_datasets.py or add data/*.csv", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
