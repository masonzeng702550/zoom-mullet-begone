"""Download the pose and segmentation models into models/ (not committed to git).

MediaPipe models are single files. The RTMPose fallback models (OpenMMLab,
Apache-2.0) come as zip archives; only the .onnx inside is kept.

Usage: python scripts/download_models.py [--force]
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
MEDIAPIPE = "https://storage.googleapis.com/mediapipe-models/"
OPENMMLAB = "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"

MODELS = {
    "pose_landmarker_full.task": MEDIAPIPE
    + "pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
    "pose_landmarker_lite.task": MEDIAPIPE
    + "pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
    "selfie_multiclass_256x256.tflite": MEDIAPIPE
    + "image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite",
    # Fallback pose (works without the head / upper torso in view): person
    # detector + 26-keypoint body-with-feet model.
    "yolox_tiny_humanart.onnx": OPENMMLAB + "yolox_tiny_8xb8-300e_humanart-6f3252f9.zip",
    "rtmpose_s_halpe26.onnx": OPENMMLAB
    + "rtmpose-s_simcc-body7_pt-body7-halpe26_700e-256x192-7f134165_20230605.zip",
}


def fetch(url: str, target: Path) -> None:
    partial = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as response, open(partial, "wb") as out:
        while chunk := response.read(1 << 16):
            out.write(chunk)
    partial.replace(target)


def download(name: str, url: str, force: bool) -> None:
    target = MODELS_DIR / name
    if target.exists() and not force:
        print(f"skip   {name} (already exists)")
        return
    print(f"fetch  {name}")
    if url.endswith(".zip"):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "model.zip"
            fetch(url, archive)
            with zipfile.ZipFile(archive) as zf:
                members = [m for m in zf.namelist() if m.endswith(".onnx")]
                if len(members) != 1:
                    raise OSError(f"{url}: expected one .onnx in the archive, found {members}")
                partial = target.with_suffix(target.suffix + ".part")
                partial.write_bytes(zf.read(members[0]))
                partial.replace(target)
    else:
        fetch(url, target)
    print(f"saved  {target} ({target.stat().st_size / 1e6:.1f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download existing files")
    args = parser.parse_args()
    MODELS_DIR.mkdir(exist_ok=True)
    try:
        for name, url in MODELS.items():
            download(name, url, args.force)
    except (OSError, zipfile.BadZipFile) as e:
        print(f"download failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
