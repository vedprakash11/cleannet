"""
Quick local test for NudeNet (same detector as image_nsfw.py).

Usage:
  python test_nudenet.py path/to/image.jpg
  python test_nudenet.py path/to/image.png

Requires: pip install nudenet
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NudeNet NudeDetector on one image file.")
    parser.add_argument(
        "image",
        nargs="?",
        default=None,
        help="Path to a JPEG/PNG/WebP/GIF file",
    )
    args = parser.parse_args()

    path = args.image
    if not path:
        print("Usage: python test_nudenet.py <path/to/image.jpg>", file=sys.stderr)
        return 1
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        print(f"Not a file: {path}", file=sys.stderr)
        return 1

    try:
        from nudenet import NudeDetector
    except ImportError:
        print("Install nudenet first: pip install nudenet", file=sys.stderr)
        return 1

    print(f"Loading NudeDetector (first run may download ONNX weights)...")
    detector = NudeDetector()
    print(f"Scanning: {path}\n")

    try:
        detections = detector.detect(path)
    except Exception as e:
        print(f"detect() failed: {e}", file=sys.stderr)
        return 1

    if not detections:
        print("No detections (model found no labeled regions above its score threshold).")
        return 0

    print(f"{'class':<32} {'score':>8}  box [x, y, w, h]")
    print("-" * 72)
    for d in detections:
        cls = d.get("class", "?")
        sc = float(d.get("score", 0.0))
        box = d.get("box", [])
        print(f"{cls:<32} {sc:8.4f}  {box}")

    # Simple "explicit" score similar to image_nsfw.py
    explicit = {
        "FEMALE_GENITALIA_EXPOSED",
        "MALE_GENITALIA_EXPOSED",
        "FEMALE_BREAST_EXPOSED",
        "BUTTOCKS_EXPOSED",
        "ANUS_EXPOSED",
        "MALE_BREAST_EXPOSED",
    }
    best = max(
        (float(d.get("score", 0)) for d in detections if d.get("class") in explicit),
        default=0.0,
    )
    print("-" * 72)
    print(f"Max explicit-class score (project heuristic): {best:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
