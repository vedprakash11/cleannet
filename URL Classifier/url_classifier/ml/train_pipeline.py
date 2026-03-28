"""Production-style training: TF-IDF + manual features + RandomForest."""

import os
import pickle

import pandas as pd
from scipy.sparse import hstack
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from url_classifier.classification.features import extract_features
from url_classifier.ml.data_pipeline import load_data
from url_classifier.paths import artifacts_dir, project_root

FEATURE_KEYS = list(extract_features("https://example.com/path").keys())
# Keep in sync with features.extract_features() for scaler + model.


def main() -> None:
    df = load_data()
    if len(df) < 8:
        raise SystemExit(
            "Not enough rows in data/*.csv — add more URLs per label (safe, phishing, malware, adult)."
        )

    vectorizer = TfidfVectorizer(
        analyzer="char",
        ngram_range=(3, 5),
        max_features=50000,
    )
    X_text = vectorizer.fit_transform(df["url"])

    feature_df = pd.DataFrame([extract_features(u) for u in df["url"]], columns=FEATURE_KEYS)
    scaler = StandardScaler()
    X_manual = scaler.fit_transform(feature_df)

    X = hstack([X_text, X_manual])
    y = df["label"]

    stratify = y if y.value_counts().min() >= 2 else None
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        stratify=stratify,
        random_state=42,
    )

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=20,
        n_jobs=-1,
        class_weight="balanced",
        random_state=42,
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    print(classification_report(y_test, preds))

    root = project_root()
    out_dir = artifacts_dir()
    os.makedirs(out_dir, exist_ok=True)
    with open(out_dir / "model.pkl", "wb") as f:
        pickle.dump(model, f)
    with open(out_dir / "vectorizer.pkl", "wb") as f:
        pickle.dump(vectorizer, f)
    with open(out_dir / "scaler.pkl", "wb") as f:
        pickle.dump(scaler, f)

    print(f"Training complete: {out_dir / 'model.pkl'}, vectorizer.pkl, scaler.pkl")


if __name__ == "__main__":
    main()
