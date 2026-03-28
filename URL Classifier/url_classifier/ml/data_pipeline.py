import os

import pandas as pd

from url_classifier.paths import data_dir

DATA_DIR = str(data_dir())


def _read_urls_csv(path: str, label: str) -> pd.DataFrame:
    if not os.path.isfile(path):
        return pd.DataFrame(columns=["url", "label"])
    df = pd.read_csv(path)
    col = None
    for c in df.columns:
        if c.lower() in ("url", "urls", "domain", "link"):
            col = c
            break
    if col is None:
        df = df.rename(columns={df.columns[0]: "url"})
    else:
        df = df.rename(columns={col: "url"})
    df["url"] = df["url"].astype(str).str.strip()
    df = df[df["url"].str.len() > 0]
    df["label"] = label
    return df[["url", "label"]]


def load_data() -> pd.DataFrame:
    safe = _read_urls_csv(os.path.join(DATA_DIR, "safe.csv"), "safe")
    phishing = _read_urls_csv(os.path.join(DATA_DIR, "phishing.csv"), "phishing")
    malware = _read_urls_csv(os.path.join(DATA_DIR, "malware.csv"), "malware")
    adult = _read_urls_csv(os.path.join(DATA_DIR, "adult.csv"), "adult")

    df = pd.concat([safe, phishing, malware, adult], ignore_index=True)
    df = df.drop_duplicates(subset=["url"])
    return df
