"""Single place for repository-root and standard artifact paths."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def project_root() -> Path:
    """Directory that contains `data/`, `artifacts/`, and the `url_classifier/` package."""
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    return project_root() / "data"


def artifacts_dir() -> Path:
    """Trained ML bundle (model.pkl, vectorizer.pkl, scaler.pkl)."""
    return project_root() / "artifacts"


def ml_bundle_dir(root: Optional[Path] = None) -> Path:
    """
    Prefer `artifacts/` when populated; fall back to repo root for older layouts.
    """
    root = root or project_root()
    art = root / "artifacts"
    need = ("model.pkl", "vectorizer.pkl", "scaler.pkl")
    if all((art / n).is_file() for n in need):
        return art
    if all((root / n).is_file() for n in need):
        return root
    return art
