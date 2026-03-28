import logging
import os
import secrets
from collections import OrderedDict
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for

from url_classifier.classification.classifier import classify_url, load_classifier_bundle
from url_classifier.images.image_nsfw import load_page_bundle
from url_classifier.images.image_upload import allowed_upload_filename, analyze_image_bytes
from url_classifier.paths import project_root

_WEB_DIR = Path(__file__).resolve().parent
app = Flask(
    __name__,
    template_folder=str(_WEB_DIR / "templates"),
)

# In-memory JPEG cache for upload previews (avoids huge data: URLs in HTML).
PREVIEW_CACHE: OrderedDict[str, bytes] = OrderedDict()
MAX_PREVIEW_CACHE = 48


def _cache_preview_jpeg(data: bytes) -> str:
    while len(PREVIEW_CACHE) >= MAX_PREVIEW_CACHE:
        PREVIEW_CACHE.popitem(last=False)
    key = secrets.token_urlsafe(16)
    PREVIEW_CACHE[key] = data
    return key


def _attach_preview_urls(image_result: dict) -> None:
    if not image_result.get("ok"):
        return
    orig = image_result.pop("preview_original_jpeg", None)
    marked = image_result.pop("preview_marked_jpeg", None)
    if orig:
        k = _cache_preview_jpeg(orig)
        image_result["preview_original_url"] = url_for("upload_preview", key=k)
    if marked:
        k = _cache_preview_jpeg(marked)
        image_result["preview_marked_url"] = url_for("upload_preview", key=k)


app.config["MAX_CONTENT_LENGTH"] = int(
    os.environ.get("MAX_IMAGE_UPLOAD_BYTES", str(8 * 1024 * 1024))
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

api_logger = logging.getLogger("url_classifier.android_api")

BASE = str(project_root())

registry, model, vectorizer, scaler, FEATURE_KEYS = load_classifier_bundle(BASE)


def _empty_template_kwargs():
    return {
        "prediction": None,
        "confidence": None,
        "rule_applied": False,
        "keyword_flag": False,
        "layer": None,
        "domain": None,
        "detail": None,
        "preview_images": [],
        "preview_message": None,
        "image_result": None,
        "classification_trace": None,
    }


@app.errorhandler(413)
def request_entity_too_large(_e):
    kw = _empty_template_kwargs()
    mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    kw["image_result"] = {
        "ok": False,
        "error": f"Upload too large (server limit ~{mb} MB). Set MAX_IMAGE_UPLOAD_BYTES if needed.",
    }
    return render_template("index.html", **kw), 413


def _wants_page_bundle() -> bool:
    return (
        os.environ.get("SHOW_PAGE_IMAGES", "1").lower() in ("1", "true", "yes")
        or os.environ.get("ENABLE_IMAGE_NSFW", "").lower() in ("1", "true", "yes")
    )


def _show_previews() -> bool:
    return os.environ.get("SHOW_PAGE_IMAGES", "1").lower() in ("1", "true", "yes")


@app.route("/upload-preview/<key>")
def upload_preview(key):
    data = PREVIEW_CACHE.get(key)
    if data is None:
        abort(404)
    return Response(
        data,
        mimetype="image/jpeg",
        headers={"Cache-Control": "no-store, private"},
    )


@app.route("/", methods=["GET", "POST"])
def home():
    prediction = None
    confidence = None
    rule_applied = False
    keyword_flag = False
    layer = None
    domain = None
    detail = None
    preview_images = []
    preview_message = None
    image_result = None
    classification_trace = None

    if request.method == "POST":
        url = (request.form.get("url") or "").strip()
        bundle = None
        if url and _wants_page_bundle():
            bundle = load_page_bundle(url, build_previews=_show_previews())
            if bundle.previews:
                preview_images = bundle.previews
            elif _show_previews():
                if bundle.fetch_error:
                    preview_message = bundle.fetch_error
                elif not bundle.raw_images:
                    preview_message = (
                        "Page HTML loaded, but no images could be downloaded. "
                        "The site may block hotlinking without a browser session, use JS-only images, or embed graphics in CSS."
                    )
        r = classify_url(
            url, registry, model, vectorizer, scaler, FEATURE_KEYS, page_bundle=bundle
        )
        classification_trace = r.trace
        prediction = r.prediction or None
        confidence = r.confidence if r.prediction else None
        keyword_flag = r.keyword_flag
        domain = r.domain or None
        detail = r.detail or None
        layer = r.layer
        rule_applied = layer in (
            "lexical_rule",
            "domain_registry",
            "redirect_registry",
            "content",
            "image_nsfw",
        )

    return render_template(
        "index.html",
        prediction=prediction,
        confidence=confidence,
        rule_applied=rule_applied,
        keyword_flag=keyword_flag,
        layer=layer,
        domain=domain,
        detail=detail,
        preview_images=preview_images,
        preview_message=preview_message,
        image_result=image_result,
        classification_trace=classification_trace,
    )


def _android_label_from_prediction(pred: str) -> str:
    """Map multi-class output to CleanNet Android expectation: label \"adult\" | \"safe\"."""
    p = (pred or "").strip().lower()
    if p == "safe" or p == "":
        return "safe"
    return "adult"


@app.route("/v1/classify", methods=["POST"])
def api_v1_classify():
    """
    JSON API for the CleanNet Android app (see ``ClassificationClient``).

    Request body: ``{"url": "<string>", "html": "<optional page source>"}``
    Optional header: ``Authorization: Bearer <token>`` (ignored unless you add verification).

    Response: ``{"label": "adult"|"safe", "score": float, "class": str, "layer": str, ...}``
    """
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or "").strip()
    html = payload.get("html")
    html_chars = len(html) if isinstance(html, str) else 0

    if not url:
        api_logger.warning("[Android] /v1/classify rejected: missing url")
        return jsonify({"error": "missing url", "label": "safe", "score": 0.0}), 400

    r = classify_url(
        url, registry, model, vectorizer, scaler, FEATURE_KEYS, page_bundle=None
    )
    pred = r.prediction or ""
    conf = float(r.confidence or 0.0)
    android_label = _android_label_from_prediction(pred)
    client_ip = request.remote_addr or "?"

    # Terminal visibility when Flask runs with ``python app.py`` (CMD / PowerShell).
    api_logger.info(
        "[Android] client=%s URL=%s | class=%r | layer=%r | confidence=%.4f | "
        "keyword_flag=%s | android_label=%r | html_chars=%s",
        client_ip,
        url,
        pred,
        r.layer,
        conf,
        r.keyword_flag,
        android_label,
        html_chars,
    )
    print(
        f"\n{'─' * 64}\n"
        f"  CleanNet request  (phone/PC: {client_ip})\n"
        f"  URL hit:     {url}\n"
        f"  Class:       {pred!r}\n"
        f"  Layer:       {r.layer}\n"
        f"  Confidence:  {conf:.4f}\n"
        f"  App label:   {android_label!r}  (adult = block in app)\n"
        f"{'─' * 64}\n",
        flush=True,
    )

    return jsonify(
        {
            "label": android_label,
            "score": conf,
            "class": pred,
            "layer": r.layer,
            "confidence": conf,
            "keyword_flag": r.keyword_flag,
            "domain": r.domain,
        }
    )


@app.route("/classify-image", methods=["GET", "POST"])
def classify_image_upload():
    if request.method == "GET":
        return redirect(url_for("home"))

    image_result = None
    f = request.files.get("image")
    if not f or not f.filename:
        image_result = {"ok": False, "error": "No file selected."}
    elif not allowed_upload_filename(f.filename):
        image_result = {
            "ok": False,
            "error": "Allowed types: JPG, PNG, WebP, GIF.",
        }
    else:
        try:
            data = f.read()
        except OSError as e:
            image_result = {"ok": False, "error": str(e)}
        else:
            image_result = analyze_image_bytes(data, f.filename)
            _attach_preview_urls(image_result)

    return render_template(
        "index.html",
        prediction=None,
        confidence=None,
        rule_applied=False,
        keyword_flag=False,
        layer=None,
        domain=None,
        detail=None,
        preview_images=[],
        preview_message=None,
        image_result=image_result,
        classification_trace=None,
    )


if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "0.0.0.0")
    app.run(debug=True, host=host, port=port, threaded=True)
