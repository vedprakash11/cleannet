"""Layered decision: lexical rules -> domain reputation -> optional content -> ML."""

from __future__ import annotations

import logging
import os
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple

import pandas as pd
from scipy.sparse import hstack

from url_classifier.classification.content_probe import content_signals
from url_classifier.classification.features import extract_features, keyword_flag, rule_based
from url_classifier.classification.url_utils import (
    extract_domain,
    is_shortener_host,
    registrable_domain,
    resolve_redirects,
)
from url_classifier.domain.domain_registry import DomainRegistry, default_registry_path
from url_classifier.images.image_nsfw import image_adult_signals
from url_classifier.paths import ml_bundle_dir, project_root

if TYPE_CHECKING:
    from url_classifier.images.image_nsfw import PageImageBundle

logger = logging.getLogger(__name__)


@dataclass
class ClassifyResult:
    prediction: str
    confidence: float
    layer: str
    keyword_flag: bool
    domain: str
    detail: str = ""
    trace: List[str] = field(default_factory=list)


def _load_ml(root: Path):
    mdir = ml_bundle_dir(root)
    files = {
        "model": mdir / "model.pkl",
        "vectorizer": mdir / "vectorizer.pkl",
        "scaler": mdir / "scaler.pkl",
    }
    missing = [k for k, p in files.items() if not p.is_file()]
    if missing:
        raise FileNotFoundError(
            f"Missing ML artifacts in {mdir}: {missing}. Run: python train_pipeline.py"
        )
    with open(files["model"], "rb") as f:
        model = pickle.load(f)
    with open(files["vectorizer"], "rb") as f:
        vectorizer = pickle.load(f)
    with open(files["scaler"], "rb") as f:
        scaler = pickle.load(f)
    return model, vectorizer, scaler


def predict_ml(url: str, model, vectorizer, scaler, feature_keys: list) -> Tuple[str, float]:
    X_text = vectorizer.transform([url])
    manual = pd.DataFrame([extract_features(url)], columns=feature_keys)
    X_manual = scaler.transform(manual)
    X = hstack([X_text, X_manual])
    pred = model.predict(X)[0]
    proba = float(model.predict_proba(X).max())
    return pred, proba


def _env_on(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def classify_url(
    url: str,
    registry: DomainRegistry,
    model,
    vectorizer,
    scaler,
    feature_keys: list,
    page_bundle: Optional["PageImageBundle"] = None,
) -> ClassifyResult:
    url = (url or "").strip()
    trace: List[str] = []

    def _log_trace() -> None:
        joined = "\n".join(trace)
        logger.info("Classification trace for %r\n%s", url or "(empty)", joined)

    if not url:
        trace.append("Input empty — no classification steps run.")
        _log_trace()
        return ClassifyResult("", 0.0, "none", False, "", "", trace=trace)

    kw = keyword_flag(url)
    if kw:
        trace.append("Keyword flag: URL contains common risk tokens (informational only).")

    trace.append("Step 1 — Lexical rules: URL substring patterns (adult/phishing hints).")
    rb = rule_based(url)
    if rb:
        dom = extract_domain(url)
        trace.append(f"  → DECISION: match → label={rb!r} (confidence 100%).")
        trace.append("  Stopping: higher-priority rule layer matched.")
        _log_trace()
        return ClassifyResult(
            rb, 1.0, "lexical_rule", kw, dom, "URL keyword / pattern", trace=trace
        )
    trace.append("  → No lexical pattern matched; continuing.")

    host = extract_domain(url)
    reg = registrable_domain(host)
    lookup_host = host
    lookup_reg = reg
    detail_parts = []

    trace.append(
        f"Step 2 — Domain reputation: host={host!r}, registrable={reg!r}."
    )
    if is_shortener_host(host) or _env_on("ALWAYS_RESOLVE_REDIRECTS"):
        trace.append("  Resolving redirects (shortener or ALWAYS_RESOLVE_REDIRECTS).")
        final = resolve_redirects(url)
        if final != url:
            lookup_host = extract_domain(final)
            lookup_reg = registrable_domain(lookup_host)
            detail_parts.append(f"resolved->{lookup_host}")
            trace.append(f"  → Final URL after redirects: host={lookup_host!r}.")

    label = registry.lookup_host(lookup_host, lookup_reg)
    if label:
        layer = "redirect_registry" if detail_parts else "domain_registry"
        trace.append(
            f"  → DECISION: domain in registry → label={label!r} (confidence 100%)."
        )
        trace.append("  Stopping: domain blocklist/allowlist matched.")
        _log_trace()
        return ClassifyResult(
            label,
            1.0,
            layer,
            kw,
            lookup_host,
            "; ".join(detail_parts) if detail_parts else "domain reputation list",
            trace=trace,
        )
    trace.append("  → No registry hit for host/registrable; continuing.")

    trace.append("Step 3 — Page images (NudeNet on fetched assets).")
    if not _env_on("ENABLE_IMAGE_NSFW"):
        trace.append("  → Skipped (set ENABLE_IMAGE_NSFW=1 to enable).")
    else:
        img = image_adult_signals(url, bundle=page_bundle)
        if img:
            clab, cconf, img_detail = img
            trace.append(
                f"  → DECISION: explicit image signal → label={clab!r}, "
                f"confidence={cconf:.1%}. {img_detail}"
            )
            trace.append("  Stopping: image layer matched.")
            _log_trace()
            return ClassifyResult(
                clab,
                cconf,
                "image_nsfw",
                kw,
                host,
                img_detail,
                trace=trace,
            )
        trace.append("  → No image above NSFW threshold (or no images loaded).")

    trace.append("Step 4 — HTML text probe (age-gate / keywords / phishing phrases).")
    if not _env_on("ENABLE_CONTENT_PROBE"):
        trace.append("  → Skipped (set ENABLE_CONTENT_PROBE=1 to enable).")
    else:
        cs = content_signals(url)
        if cs:
            clab, cconf = cs
            trace.append(
                f"  → DECISION: HTML text signal → label={clab!r}, confidence={cconf:.1%}."
            )
            trace.append("  Stopping: content layer matched.")
            _log_trace()
            return ClassifyResult(
                clab,
                cconf,
                "content",
                kw,
                host,
                "HTML text heuristics (ENABLE_CONTENT_PROBE)",
                trace=trace,
            )
        trace.append("  → No content heuristic matched.")

    trace.append("Step 5 — ML model: TF-IDF (char n-grams) + structural features → RandomForest.")
    pred, proba = predict_ml(url, model, vectorizer, scaler, feature_keys)
    trace.append(
        f"  → DECISION: ML fallback → label={pred!r}, max class probability={proba:.1%}."
    )
    trace.append("  (No earlier layer returned a verdict.)")
    _log_trace()
    return ClassifyResult(
        pred,
        proba,
        "ml",
        kw,
        host,
        "TF-IDF + structural features",
        trace=trace,
    )


def load_classifier_bundle(base: Optional[str] = None):
    root = Path(base).resolve() if base else project_root()
    model, vectorizer, scaler = _load_ml(root)
    reg = DomainRegistry()
    reg.load_csv(default_registry_path(str(root)))
    fk = list(extract_features("https://example.com/path").keys())
    return reg, model, vectorizer, scaler, fk
