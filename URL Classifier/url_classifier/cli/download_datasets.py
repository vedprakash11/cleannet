"""
Download publicly available URL/domain lists for training.

Sources (see each project's terms of use):
  - PhishTank: https://data.phishtank.com/data/online-valid.csv.gz
  - OpenPhish: https://openphish.com/feed.txt
  - URLHaus (text, online URLs): https://urlhaus.abuse.ch/downloads/text_online/
  - Tranco top 1M: https://tranco-list.eu/top-1m.csv.zip
  - Adult blocklist: https://raw.githubusercontent.com/blocklistproject/Lists/master/porn.txt

Outputs: data/safe.csv, data/phishing.csv, data/malware.csv, data/adult.csv (column: url).

Example:
  python download_datasets.py --max-per-class 20000
  python train_pipeline.py

Optional image-based adult detection (NudeNet): set ENABLE_IMAGE_NSFW=1 before python app.py
"""

from __future__ import annotations

import argparse
import gzip
import io
import os
import random
import sys
import zipfile
from typing import Iterable, Iterator, List, Optional

import pandas as pd
import requests

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "URLClassifier/1.0 (+https://github.com; research; contact: local)",
        "Accept": "*/*",
    }
)

PHISHTANK_GZ = "https://data.phishtank.com/data/online-valid.csv.gz"
OPENPHISH_TXT = "https://openphish.com/feed.txt"
URLHAUS_TEXT_ONLINE = "https://urlhaus.abuse.ch/downloads/text_online/"
TRANCO_ZIP = "https://tranco-list.eu/top-1m.csv.zip"
ADULT_PORN_TXT = (
    "https://raw.githubusercontent.com/blocklistproject/Lists/master/porn.txt"
)

TIMEOUT = 120


def _cache_path(cache_dir: str, name: str) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, name)


def _download_bytes(url: str, cache_file: Optional[str] = None) -> bytes:
    if cache_file and os.path.isfile(cache_file):
        with open(cache_file, "rb") as f:
            return f.read()
    r = SESSION.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.content
    if cache_file:
        with open(cache_file, "wb") as f:
            f.write(data)
    return data


def reservoir_sample(stream: Iterator[str], k: int, rng: random.Random) -> List[str]:
    """Reservoir sample k items from a streaming iterator (unknown length)."""
    reservoir: List[str] = []
    for i, item in enumerate(stream):
        if i < k:
            reservoir.append(item)
        else:
            j = rng.randint(0, i)
            if j < k:
                reservoir[j] = item
    return reservoir


def iter_phishtank_urls(gz_bytes: bytes) -> Iterator[str]:
    with gzip.open(io.BytesIO(gz_bytes), "rt", encoding="utf-8", errors="replace") as f:
        # pandas can read from buffer; use chunks for memory
        reader = pd.read_csv(f, chunksize=50_000, usecols=["url"], dtype=str, low_memory=False)
        for chunk in reader:
            for u in chunk["url"].dropna().astype(str):
                u = u.strip()
                if u and u.startswith("http"):
                    yield u


def fetch_phishing(max_n: int, cache_dir: str, rng: random.Random) -> List[str]:
    cache_gz = _cache_path(cache_dir, "phishtank_online-valid.csv.gz")
    print("Downloading PhishTank online-valid ...", flush=True)
    gz = _download_bytes(PHISHTANK_GZ, cache_gz)
    phish_urls = reservoir_sample(iter_phishtank_urls(gz), max_n, rng)
    print(f"  PhishTank sampled: {len(phish_urls)}", flush=True)

    extra: List[str] = []
    try:
        print("Downloading OpenPhish feed ...", flush=True)
        raw = _download_bytes(OPENPHISH_TXT, _cache_path(cache_dir, "openphish_feed.txt"))
        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("http"):
                extra.append(line)
        rng.shuffle(extra)
        print(f"  OpenPhish lines: {len(extra)}", flush=True)
    except requests.RequestException as e:
        print(f"  OpenPhish skipped: {e}", flush=True)

    seen = set()
    out: List[str] = []
    for u in phish_urls + extra:
        if u not in seen:
            seen.add(u)
            out.append(u)
        if len(out) >= max_n:
            break
    return out[:max_n]


def fetch_malware(max_n: int, cache_dir: str, rng: random.Random) -> List[str]:
    cache_txt = _cache_path(cache_dir, "urlhaus_text_online.txt")
    print("Downloading URLHaus text_online ...", flush=True)
    raw = _download_bytes(URLHAUS_TEXT_ONLINE, cache_txt)
    lines = raw.decode("utf-8", errors="replace").splitlines()
    urls = [ln.strip() for ln in lines if ln.strip().startswith("http")]
    rng.shuffle(urls)
    out = urls[:max_n]
    print(f"  URLHaus URLs: {len(out)}", flush=True)
    return out


def fetch_safe(max_n: int, cache_dir: str, rng: random.Random) -> List[str]:
    cache_zip = _cache_path(cache_dir, "tranco_top-1m.csv.zip")
    print("Downloading Tranco top-1m ...", flush=True)
    zdata = _download_bytes(TRANCO_ZIP, cache_zip)
    domains: List[str] = []
    with zipfile.ZipFile(io.BytesIO(zdata)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not names:
            raise RuntimeError("Tranco zip: no csv found")
        with zf.open(names[0]) as f:
            # rank,domain
            df = pd.read_csv(f, header=None, names=["rank", "domain"], dtype=str, nrows=min(1_000_000, max_n * 20))
    domains = df["domain"].dropna().astype(str).str.strip().tolist()
    domains = [d for d in domains if d and "." in d and " " not in d]
    rng.shuffle(domains)
    domains = domains[:max_n]
    # Normalize to URL strings for the char n-gram model
    out = []
    for d in domains:
        d = d.lower().rstrip(".")
        if not d.startswith("http"):
            out.append(f"https://{d}/")
        else:
            out.append(d)
    print(f"  Tranco (as https://...): {len(out)}", flush=True)
    return out


def iter_adult_domains(txt: str) -> Iterator[str]:
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("0.0.0.0") or line.startswith("127.0.0.1"):
            parts = line.split()
            if len(parts) >= 2:
                dom = parts[1]
                if dom and dom not in ("localhost",) and "." in dom:
                    yield dom
        elif "." in line and " " not in line and not line.startswith("http"):
            yield line


def fetch_adult(max_n: int, cache_dir: str, rng: random.Random) -> List[str]:
    cache_txt = _cache_path(cache_dir, "blocklist_porn.txt")
    print("Downloading adult blocklist (BlockListProject porn) ...", flush=True)
    raw = _download_bytes(ADULT_PORN_TXT, cache_txt)
    text = raw.decode("utf-8", errors="replace")
    # Reservoir over iterator
    doms = reservoir_sample(iter_adult_domains(text), max_n, rng)
    out = []
    for d in doms:
        d = d.lower().strip().rstrip(".")
        if d.startswith("http"):
            out.append(d if d.endswith("/") else d + "/")
        else:
            out.append(f"https://{d}/")
    print(f"  Adult URLs: {len(out)}", flush=True)
    return out


def write_urls_csv(path: str, urls: List[str]) -> None:
    df = pd.DataFrame({"url": urls})
    df.to_csv(path, index=False)


_WIN_CMD = (
    "Windows Command Prompt (cmd.exe): do not add text after the command on the same line "
    "(cmd does not treat # as a comment, so Python receives extra arguments). "
    "Run only: python download_datasets.py"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download public URL lists into data/*.csv",
        epilog=_WIN_CMD,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--max-per-class",
        type=int,
        default=25_000,
        help="Max URLs per label (default: 25000). Use smaller values for quick tests.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for sampling.",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Cache directory for raw downloads (default: data/cache)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Output directory for CSVs (default: project data/)",
    )
    args = parser.parse_args()

    from url_classifier.paths import data_dir as project_data_dir

    data_dir = args.data_dir or str(project_data_dir())
    cache_dir = args.cache_dir or os.path.join(data_dir, "cache")
    os.makedirs(data_dir, exist_ok=True)

    rng = random.Random(args.seed)
    m = args.max_per_class

    try:
        phishing = fetch_phishing(m, cache_dir, rng)
        malware = fetch_malware(m, cache_dir, rng)
        safe = fetch_safe(m, cache_dir, rng)
        adult = fetch_adult(m, cache_dir, rng)
    except requests.RequestException as e:
        print(f"Download failed: {e}", file=sys.stderr)
        return 1

    write_urls_csv(os.path.join(data_dir, "phishing.csv"), phishing)
    write_urls_csv(os.path.join(data_dir, "malware.csv"), malware)
    write_urls_csv(os.path.join(data_dir, "safe.csv"), safe)
    write_urls_csv(os.path.join(data_dir, "adult.csv"), adult)

    print(
        f"Wrote: safe={len(safe)}, phishing={len(phishing)}, malware={len(malware)}, adult={len(adult)} -> {data_dir}"
    )

    from url_classifier.cli.build_domain_registry import build_registry

    print("Building domain_registry.csv ...", flush=True)
    build_registry(data_dir)

    print("Next: python train_pipeline.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
