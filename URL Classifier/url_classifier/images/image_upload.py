"""NudeNet analysis for user-uploaded images (Flask file upload)."""

from __future__ import annotations

import os
from io import BytesIO
from typing import Any, Dict, List, Optional

# Same explicit set as image_nsfw.py for consistent "adult" summary
EXPLICIT_CLASSES = frozenset(
    {
        "FEMALE_GENITALIA_EXPOSED",
        "MALE_GENITALIA_EXPOSED",
        "FEMALE_BREAST_EXPOSED",
        "BUTTOCKS_EXPOSED",
        "ANUS_EXPOSED",
        "MALE_BREAST_EXPOSED",
    }
)

THRESHOLD = float(os.environ.get("UPLOAD_NSFW_THRESHOLD", "0.45"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_IMAGE_UPLOAD_BYTES", str(8 * 1024 * 1024)))

_ALLOWED_EXT = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})


def allowed_upload_filename(filename: str) -> bool:
    if not filename:
        return False
    ext = os.path.splitext(filename)[1].lower()
    return ext in _ALLOWED_EXT


def _pil_image_to_jpeg_bytes(im, max_side: int, quality: int) -> bytes:
    im = im.copy()
    im.thumbnail((max_side, max_side))
    out = BytesIO()
    im.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def preview_plain_jpeg_bytes(image_bytes: bytes, max_side: int = 520, quality: int = 85) -> Optional[bytes]:
    """Resized upload as JPEG bytes (no overlays)."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        im = Image.open(BytesIO(image_bytes)).convert("RGB")
        return _pil_image_to_jpeg_bytes(im, max_side, quality)
    except Exception:
        return None


def preview_marked_jpeg_bytes(image_bytes: bytes, rows: List[Dict[str, Any]]) -> Optional[bytes]:
    """
    Draw NudeNet boxes, return JPEG bytes. Red = explicit NSFW, amber = other detections.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return preview_plain_jpeg_bytes(image_bytes)

    try:
        im = Image.open(BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return preview_plain_jpeg_bytes(image_bytes)

    draw = ImageDraw.Draw(im)
    W, H = im.size
    lw = max(2, min(W, H) // 200)

    for d in rows:
        box = d.get("box")
        if not box or len(box) != 4:
            continue
        x, y, bw, bh = [float(c) for c in box]
        x0 = int(max(0, min(x, W - 1)))
        y0 = int(max(0, min(y, H - 1)))
        x1 = int(min(x0 + max(0, bw), W))
        y1 = int(min(y0 + max(0, bh), H))
        if x1 <= x0 or y1 <= y0:
            continue

        cls = str(d.get("class", ""))
        score = float(d.get("score", 0.0))
        explicit = cls in EXPLICIT_CLASSES
        color = (255, 55, 55) if explicit else (255, 190, 60)

        try:
            draw.rectangle([x0, y0, x1, y1], outline=color, width=lw)
        except TypeError:
            for t in range(lw):
                draw.rectangle([x0 + t, y0 + t, x1 - t, y1 - t], outline=color)

        label = f"{cls.replace('_', ' ')[:32]}  {score:.2f}"
        ty = max(0, y0 - 20)
        try:
            tb = draw.textbbox((x0, ty), label)
            pad = 2
            draw.rectangle(
                [tb[0] - pad, tb[1] - pad, tb[2] + pad, tb[3] + pad],
                fill=(18, 18, 22),
            )
            draw.text((x0, ty), label, fill=color)
        except Exception:
            try:
                draw.text((x0, ty), label, fill=color)
            except Exception:
                pass

    try:
        return _pil_image_to_jpeg_bytes(im, 520, 85)
    except Exception:
        return preview_plain_jpeg_bytes(image_bytes)


def _max_explicit_score(detections: List[dict]) -> float:
    best = 0.0
    for d in detections:
        if d.get("class") in EXPLICIT_CLASSES:
            best = max(best, float(d.get("score", 0.0)))
    return best


def analyze_image_bytes(image_bytes: bytes, filename: str = "") -> Dict[str, Any]:
    """
    Run NudeDetector on raw bytes.
    On success, includes preview_original_jpeg / preview_marked_jpeg (bytes) for the app to cache & serve.
    """
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        return {
            "ok": False,
            "error": f"File too large (max {MAX_UPLOAD_BYTES // (1024*1024)} MB).",
        }

    try:
        from nudenet import NudeDetector
    except ImportError:
        return {
            "ok": False,
            "error": "nudenet is not installed. Run: pip install nudenet",
        }

    try:
        detector = NudeDetector()
        detections = detector.detect(image_bytes)
    except Exception as e:
        return {"ok": False, "error": f"NudeNet error: {e}"}

    rows: List[Dict[str, Any]] = []
    for d in detections:
        rows.append(
            {
                "class": d.get("class", ""),
                "score": float(d.get("score", 0.0)),
                "box": d.get("box", []),
                "explicit": d.get("class", "") in EXPLICIT_CLASSES,
            }
        )

    max_exp = _max_explicit_score(detections)
    if max_exp >= THRESHOLD:
        summary_label = "adult"
        summary_text = (
            f"Explicit regions detected (max score {max_exp:.2f} ≥ {THRESHOLD}). "
            "Treat as sensitive / adult content."
        )
    elif rows:
        summary_label = "review"
        summary_text = (
            "Detections found, but no high-confidence explicit exposure by project rules. "
            "Review manually if needed."
        )
    else:
        summary_label = "none"
        summary_text = "No body regions scored above the model’s display threshold."

    orig_jpeg = preview_plain_jpeg_bytes(image_bytes)
    marked_jpeg = preview_marked_jpeg_bytes(image_bytes, rows) if rows else None

    preview_legend = None
    if marked_jpeg:
        preview_legend = (
            "Marked view: red boxes = explicit NSFW classes; amber = other detected body regions. "
            "Left: your upload (resized), same scale as marked image."
        )

    out: Dict[str, Any] = {
        "ok": True,
        "filename": filename or "upload",
        "detections": rows,
        "max_explicit": max_exp,
        "threshold": THRESHOLD,
        "summary_label": summary_label,
        "summary_text": summary_text,
        "preview_legend": preview_legend,
    }
    if orig_jpeg:
        out["preview_original_jpeg"] = orig_jpeg
    if marked_jpeg:
        out["preview_marked_jpeg"] = marked_jpeg
    return out
