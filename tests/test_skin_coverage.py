"""Integration: on a real photo, the pants must cover the bare leg skin the segmenter finds."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from meet_pants.analysis.leg_geometry import LegTracker
from meet_pants.config import Config
from meet_pants.perception.pose import PoseDetector
from meet_pants.perception.segmenter import BodySegmenter
from meet_pants.perception.types import Lm
from meet_pants.pipeline import Wardrobe, dress, scene_masks
from meet_pants.render.compositor import Compositor
from meet_pants.render.garment import build_pyramid


@pytest.fixture(scope="module")
def scene(person_image_module):
    config = Config()
    if not config.segmenter_model_path.exists() or not config.pose_model_path.exists():
        pytest.skip("models missing; run scripts/download_models.py")
    img = person_image_module
    h, w = img.shape[:2]
    with PoseDetector(config.pose_model_path, config.pose) as detector, BodySegmenter(
        config.segmenter_model_path
    ) as segmenter:
        pose = detector.detect(img, 0)
        segmenter.submit(img, 0)
        segmentation = segmenter.wait(timeout=5.0)
    geometry = LegTracker().update(pose, w, h, segmentation)
    return config, img, pose, segmentation, geometry


@pytest.fixture(scope="module")
def person_image_module():
    import cv2

    path = Path(__file__).resolve().parents[1] / "data" / "pose.jpg"
    if not path.exists():
        pytest.skip("data/pose.jpg missing (MediaPipe sample image, not committed)")
    return cv2.imread(str(path))


def leg_skin(img: np.ndarray, pose, segmentation) -> np.ndarray:
    """Segmenter skin below the hips and above the ankles (feet stay bare)."""
    h, w = img.shape[:2]
    hip_y = max(pose.landmarks[i].y for i in (Lm.LEFT_HIP, Lm.RIGHT_HIP)) * h
    ankle_y = min(pose.landmarks[i].y for i in (Lm.LEFT_ANKLE, Lm.RIGHT_ANKLE)) * h
    rows = np.arange(h)[:, None]
    return segmentation.skin & (rows > hip_y) & (rows < ankle_y - 0.03 * h)


def test_segmenter_finds_leg_skin(scene) -> None:
    _, img, pose, segmentation, _ = scene
    assert segmentation is not None
    assert segmentation.category.shape == img.shape[:2]
    assert leg_skin(img, pose, segmentation).sum() > 2000


@pytest.mark.parametrize("garment_id", ["dress_navy", "chino_khaki", "jeans_indigo"])
def test_pants_cover_leg_skin(scene, garment_id: str) -> None:
    """Each garment's shape covers the skin. The texture is swapped for magenta so
    "covered" can be told apart from "pants happen to be skin-colored" (khaki)."""
    config, img, pose, segmentation, geometry = scene
    garment = Wardrobe(Path(config.garments_dir), garment_id).current
    probe = garment.texture.copy()
    probe[..., :3] = (255, 0, 255)
    garment = replace(garment, texture=probe, pyramid=build_pyramid(probe))
    out, _ = dress(img, geometry, garment, Compositor(), scene_masks(pose, segmentation, geometry))

    skin = leg_skin(img, pose, segmentation)
    b, g, r = (out[..., i].astype(int) for i in range(3))
    magenta = (b - g > 60) & (r - g > 60)
    coverage = magenta[skin].mean()
    assert coverage > 0.98, f"only {coverage:.1%} of leg skin covered"
