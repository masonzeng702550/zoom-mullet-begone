"""Download the MediaPipe Tasks models into models/ (not committed to git).

Usage: python scripts/download_models.py [--force]
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"

MODELS = {
    "pose_landmarker_full.task": "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
    "pose_landmarker_lite.task": "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
    "selfie_multiclass_256x256.tflite": "https://storage.googleapis.com/mediapipe-models/"
    "image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite",
}


def download(name: str, url: str, force: bool) -> None:
    target = MODELS_DIR / name
    if target.exists() and not force:
        print(f"skip   {name} (already exists)")
        return
    partial = target.with_suffix(target.suffix + ".part")
    print(f"fetch  {name}")
    with urllib.request.urlopen(url, timeout=60) as response, open(partial, "wb") as out:
        while chunk := response.read(1 << 16):
            out.write(chunk)
    partial.replace(target)
    print(f"saved  {target} ({target.stat().st_size / 1e6:.1f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download existing files")
    args = parser.parse_args()
    MODELS_DIR.mkdir(exist_ok=True)
    try:
        for name, url in MODELS.items():
            download(name, url, args.force)
    except OSError as e:
        print(f"download failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
