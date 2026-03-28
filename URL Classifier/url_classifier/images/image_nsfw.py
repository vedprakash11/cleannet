"""
Page image fetch: HTML sampling, optional NudeNet scoring, UI previews (data-URI thumbnails).

ENABLE_IMAGE_NSFW=1 — run nudity detection on downloaded bytes.
SHOW_PAGE_IMAGES=1 (default) — embed thumbnails in the Flask UI.
"""

from __future__ import annotations

import base64
import ipaddress
import os
import re
import socket
from dataclasses import dataclass, field
from io import BytesIO
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from url_classifier.classification.url_utils import SESSION, ensure_scheme

MAX_IMAGES_DEFAULT = 5
MAX_IMAGE_BYTES = 2_000_000
FETCH_TIMEOUT = float(os.environ.get("PAGE_FETCH_TIMEOUT", "12.0"))
UNSAFE_THRESHOLD = float(os.environ.get("IMAGE_NSFW_THRESHOLD", "0.45"))

PREVIEW_MAX_IMAGES = int(os.environ.get("PREVIEW_MAX_IMAGES", "6"))
PREVIEW_MAX_SOURCE_BYTES = 450_000
THUMB_MAX = (280, 280)

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


@dataclass
class PageImageBundle:
    """One HTML fetch; images downloaded once; previews + optional NSFW reuse."""

    page_url: str
    html: str
    previews: List[dict] = field(default_factory=list)
    raw_images: List[Tuple[str, bytes]] = field(default_factory=list)
    fetch_error: Optional[str] = None


def _nude_detector():
    try:
        from nudenet import NudeDetector  # type: ignore
    except ImportError:
        return None
    return NudeDetector()


def _is_public_host(hostname: str) -> bool:
    if not hostname or hostname == "localhost":
        return False
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError:
        return False
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    return True


def _first_url_from_srcset(srcset: str) -> Optional[str]:
    """First URL in a srcset string (e.g. 'url 1x, url2 2w')."""
    if not srcset or not isinstance(srcset, str):
        return None
    part = srcset.split(",")[0].strip().split()
    return part[0] if part else None


def _collect_image_urls(page_url: str, html: str, max_n: int) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: List[str] = []
    for tag in soup.find_all(["img", "source"]):
        for attr in ("src", "data-src", "data-lazy-src", "data-original"):
            v = tag.get(attr)
            if v and isinstance(v, str) and not v.lower().startswith("data:"):
                found.append(urljoin(page_url, v.strip()))
                break
        ss = tag.get("srcset") or tag.get("data-srcset")
        if ss and isinstance(ss, str):
            u = _first_url_from_srcset(ss)
            if u and not u.lower().startswith("data:"):
                found.append(urljoin(page_url, u.strip()))
    for tag in soup.find_all("meta"):
        if tag.get("property") in ("og:image", "twitter:image"):
            c = tag.get("content")
            if c and isinstance(c, str):
                found.append(urljoin(page_url, c.strip()))
    seen = set()
    out: List[str] = []
    for u in found:
        if u not in seen and u.startswith("http"):
            seen.add(u)
            out.append(u)
        if len(out) >= max_n * 4:
            break
    return out


_IMG_EXT = re.compile(r"\.(jpe?g|png|webp|gif)(\?|$)", re.I)


def _looks_like_image_url(url: str) -> bool:
    path = urlparse(url).path
    return bool(_IMG_EXT.search(path)) or "image" in url.lower()


def _is_image_magic(b: bytes) -> bool:
    if len(b) < 12:
        return False
    if b[:3] == b"\xff\xd8\xff":
        return True
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if b[:4] == b"GIF8":
        return True
    if b[:4] == b"RIFF" and len(b) >= 12 and b[8:12] == b"WEBP":
        return True
    return False


def _mime_from_magic(b: bytes) -> str:
    if len(b) >= 3 and b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(b) >= 8 and b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"GIF8":
        return "image/gif"
    if len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _download_image(
    url: str,
    byte_cap: int = MAX_IMAGE_BYTES,
    referer: Optional[str] = None,
) -> Optional[bytes]:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return None
    host = p.hostname or ""
    if not _is_public_host(host):
        return None
    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    try:
        r = SESSION.get(url, timeout=FETCH_TIMEOUT, stream=True, headers=headers)
        r.raise_for_status()
        ctype = (r.headers.get("Content-Type") or "").lower()
        data = b""
        for chunk in r.iter_content(65536):
            data += chunk
            if len(data) >= 32:
                ok = "image" in ctype or _is_image_magic(data)
                if not ok:
                    r.close()
                    return None
            if len(data) > byte_cap:
                break
        r.close()
        if not data:
            return None
        if "image" in ctype or "octet-stream" in ctype:
            if "image" in ctype or _is_image_magic(data[:32]):
                return data
            return None
        if _is_image_magic(data[:32]):
            return data
        return None
    except (requests.RequestException, OSError):
        return None


def _thumbnail_jpeg_data_uri(image_bytes: bytes) -> Optional[str]:
    """Resize to THUMB_MAX, return data:image/jpeg;base64,..."""
    try:
        from PIL import Image

        im = Image.open(BytesIO(image_bytes))
        im = im.convert("RGB")
        im.thumbnail(THUMB_MAX)
        out = BytesIO()
        im.save(out, format="JPEG", quality=78, optimize=True)
        b64 = base64.b64encode(out.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        if len(image_bytes) > PREVIEW_MAX_SOURCE_BYTES:
            image_bytes = image_bytes[:PREVIEW_MAX_SOURCE_BYTES]
        mime = _mime_from_magic(image_bytes)
        b64 = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{mime};base64,{b64}"


def _ssl_verify() -> bool:
    return os.environ.get("REQUESTS_VERIFY", "1").lower() not in ("0", "false", "no")


def _url_variants(url: str) -> List[str]:
    """Try bare domain and www. — some sites only respond on one host."""
    u = ensure_scheme(url)
    parsed = urlparse(u)
    host = (parsed.hostname or "").lower()
    if not host:
        return [u]
    variants = [u]
    if host.startswith("www."):
        rest = host[4:]
        variants.append(
            urlunparse(
                (parsed.scheme, rest, parsed.path or "/", parsed.params, parsed.query, parsed.fragment)
            )
        )
    else:
        variants.append(
            urlunparse(
                (
                    parsed.scheme,
                    f"www.{host}",
                    parsed.path or "/",
                    parsed.params,
                    parsed.query,
                    parsed.fragment,
                )
            )
        )
    out: List[str] = []
    seen = set()
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _fetch_page_html(url: str) -> Tuple[Optional[str], str, Optional[str]]:
    """
    Returns (final_page_url, html, error_message).
    error_message is None on success; html may be empty string on failure.
    """
    timeout = float(os.environ.get("PAGE_FETCH_TIMEOUT", str(FETCH_TIMEOUT)))
    verify = _ssl_verify()
    last_err: Optional[str] = None

    for page_url in _url_variants(url):
        try:
            r = SESSION.get(
                page_url,
                timeout=timeout,
                stream=True,
                allow_redirects=True,
                verify=verify,
            )
            final_url = r.url
            if r.status_code >= 400:
                msg = (
                    f"HTTP {r.status_code} {r.reason}. "
                    "Many sites block non-browser or data-center clients; try from a browser-only check."
                )
                r.close()
                last_err = msg
                continue
            r.raise_for_status()
            raw = b""
            for chunk in r.iter_content(65536):
                raw += chunk
                if len(raw) > 800_000:
                    break
            r.close()
            html = raw.decode("utf-8", errors="replace")
            return final_url, html, None
        except requests.exceptions.SSLError as e:
            last_err = (
                f"SSL error: {e!s} "
                "(upgrade certifi, or set REQUESTS_VERIFY=0 for local testing only)."
            )
        except requests.exceptions.Timeout:
            last_err = f"Timed out after {timeout}s (try PAGE_FETCH_TIMEOUT=25)."
        except (requests.RequestException, OSError) as e:
            last_err = f"{type(e).__name__}: {e}"

    return None, "", last_err or "Could not fetch page."


def load_page_bundle(url: str, *, build_previews: bool = True) -> PageImageBundle:
    """
    Fetch page once; download up to N distinct images once.
    Fills raw_images for NSFW; optional JPEG thumbnails for UI when build_previews=True.
    Always returns a bundle; see fetch_error if HTML could not be loaded.
    """
    page_url, html, fetch_err = _fetch_page_html(url)
    if fetch_err or not html.strip():
        return PageImageBundle(
            page_url=page_url or ensure_scheme(url),
            html="",
            fetch_error=fetch_err or "Empty HTML response.",
        )

    nsfw_on = os.environ.get("ENABLE_IMAGE_NSFW", "").lower() in ("1", "true", "yes")
    nsfw_max = (
        int(os.environ.get("IMAGE_NSFW_MAX_IMAGES", str(MAX_IMAGES_DEFAULT))) if nsfw_on else 0
    )
    fetch_n = max(PREVIEW_MAX_IMAGES, nsfw_max) if nsfw_max else PREVIEW_MAX_IMAGES
    if fetch_n <= 0:
        fetch_n = PREVIEW_MAX_IMAGES

    img_urls = _collect_image_urls(page_url, html, max_n=max(fetch_n * 4, 20))
    prefer = [u for u in img_urls if _looks_like_image_url(u)]
    ordered = prefer + [u for u in img_urls if u not in prefer]
    img_urls = ordered[:fetch_n]

    previews: List[dict] = []
    raw_images: List[Tuple[str, bytes]] = []

    for img_url in img_urls:
        data = _download_image(
            img_url,
            byte_cap=PREVIEW_MAX_SOURCE_BYTES,
            referer=page_url,
        )
        if not data:
            continue
        raw_images.append((img_url, data))
        if build_previews and len(previews) < PREVIEW_MAX_IMAGES:
            uri = _thumbnail_jpeg_data_uri(data)
            if uri:
                previews.append({"src": img_url, "data_uri": uri})

    return PageImageBundle(
        page_url=page_url,
        html=html,
        previews=previews,
        raw_images=raw_images,
        fetch_error=None,
    )


def _detections_to_score(detections: list) -> float:
    if not detections:
        return 0.0
    best = 0.0
    for d in detections:
        cls = d.get("class", "")
        sc = float(d.get("score", 0.0))
        if cls in EXPLICIT_CLASSES:
            best = max(best, sc)
    return best


def _score_image_bytes(detector, image_bytes: bytes) -> Optional[float]:
    try:
        dets = detector.detect(image_bytes)
        return _detections_to_score(dets)
    except Exception:
        return None


def image_adult_signals(url: str, bundle: Optional[PageImageBundle] = None) -> Optional[Tuple[str, float, str]]:
    if os.environ.get("ENABLE_IMAGE_NSFW", "").lower() not in ("1", "true", "yes"):
        return None

    detector = _nude_detector()
    if detector is None:
        return None

    if bundle is None:
        bundle = load_page_bundle(url, build_previews=False)
    if not bundle or not bundle.raw_images:
        return None

    nsfw_max = int(os.environ.get("IMAGE_NSFW_MAX_IMAGES", str(MAX_IMAGES_DEFAULT)))
    best_score = 0.0
    checked = 0

    for img_url, data in bundle.raw_images[:nsfw_max]:
        u = _score_image_bytes(detector, data)
        if u is not None:
            checked += 1
            best_score = max(best_score, u)
        if best_score >= UNSAFE_THRESHOLD:
            break

    if checked == 0:
        return None
    if best_score >= UNSAFE_THRESHOLD:
        conf = min(0.95, 0.5 + 0.45 * best_score)
        return ("adult", conf, f"Explicit image regions (NudeNet, score~{best_score:.2f}, n={checked})")
    return None
