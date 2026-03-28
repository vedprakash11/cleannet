"""Quick baseline: TF-IDF + LogisticRegression. Run once for a minimal demo model."""

import pickle

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from url_classifier.paths import artifacts_dir, project_root


def main() -> None:
    data = {
        "url": [
            "https://google.com",
            "https://facebook.com",
            "http://xxx-adult-site.com",
            "http://phishing-login-bank.com",
        ],
        "label": ["safe", "safe", "adult", "phishing"],
    }

    df = pd.DataFrame(data)

    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(3, 5))
    X = vectorizer.fit_transform(df["url"])
    y = df["label"]

    model = LogisticRegression(max_iter=1000)
    model.fit(X, y)

    _ = project_root()
    out_dir = artifacts_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "model.pkl", "wb") as f:
        pickle.dump(model, f)
    with open(out_dir / "vectorizer.pkl", "wb") as f:
        pickle.dump(vectorizer, f)

    print(f"Model trained and saved under {out_dir} (model.pkl, vectorizer.pkl).")
    print("For production (4-class + manual features), run: python train_pipeline.py")


if __name__ == "__main__":
    main()
