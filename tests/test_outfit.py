"""Shirt color sampling and pants pairing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from helpers import make_pose, standing_points

from meet_pants.analysis.outfit import (
    SWITCH_MS,
    WARMUP_SAMPLES,
    OutfitMatcher,
    best_garment,
    bgr_to_lab,
    sample_top_color,
    texture_color,
)
from meet_pants.perception.segmenter import BODY_SKIN, CLOTHES, Segmentation
from meet_pants.perception.types import Lm, PoseFrame
from meet_pants.render.garment import list_garments, load_garment

GARMENTS_DIR = Path(__file__).resolve().parents[1] / "garments"


def lab(bgr: tuple[int, int, int]) -> np.ndarray:
    return bgr_to_lab(np.array([[bgr]], np.uint8))[0, 0]


@pytest.fixture(scope="module")
def wardrobe() -> dict[str, np.ndarray]:
    return {gid: texture_color(load_garment(GARMENTS_DIR, gid).texture) for gid in list_garments(GARMENTS_DIR)}


def test_garment_colors_are_what_their_names_say(wardrobe: dict[str, np.ndarray]) -> None:
    assert wardrobe["chino_khaki"][0] > 50  # light
    assert wardrobe["dress_navy"][0] < 25  # dark
    assert wardrobe["dress_navy"][2] < 0 and wardrobe["jeans_indigo"][2] < 0  # blue
    assert wardrobe["chino_khaki"][2] > 0  # yellowish


@pytest.mark.parametrize(
    ("top_bgr", "expected"),
    [
        ((245, 245, 245), "dress_navy"),  # white shirt
        ((25, 25, 25), "chino_khaki"),  # black
        ((80, 40, 20), "chino_khaki"),  # navy: no navy-on-navy
        ((235, 200, 160), "dress_navy"),  # light blue
        ((40, 90, 30), "chino_khaki"),  # dark green
    ],
)
def test_pairing(wardrobe: dict[str, np.ndarray], top_bgr: tuple[int, int, int], expected: str) -> None:
    assert best_garment(lab(top_bgr), wardrobe) == expected


def _shirt_scene(shirt_bgr: tuple[int, int, int]) -> tuple[np.ndarray, PoseFrame, Segmentation]:
    w, h = 400, 500
    frame = np.full((h, w, 3), 200, np.uint8)
    category = np.zeros((h, w), np.uint8)
    frame[40:210, 150:290] = shirt_bgr
    category[40:210, 150:290] = CLOTHES
    frame[120:140, 200:240] = (90, 140, 200)  # a hand on the chest
    category[120:140, 200:240] = BODY_SKIN
    return frame, make_pose(standing_points(), w, h), Segmentation(0, category)


def test_samples_the_shirt_not_the_skin() -> None:
    frame, pose, seg = _shirt_scene((30, 30, 160))
    color = sample_top_color(frame, pose, seg)
    assert color is not None
    assert np.allclose(color, lab((30, 30, 160)), atol=1)


def test_no_sample_without_shoulders() -> None:
    frame, pose, seg = _shirt_scene((30, 30, 160))
    points = standing_points()
    hidden = make_pose(points, 400, 500)
    landmarks = list(hidden.landmarks)
    for i in (Lm.LEFT_SHOULDER, Lm.RIGHT_SHOULDER):
        lm = landmarks[i]
        landmarks[i] = type(lm)(lm.x, lm.y, lm.z, 0.1, 0.1)
    hidden = PoseFrame(0, tuple(landmarks), None, 1.0, "rtmpose")
    assert sample_top_color(frame, hidden, seg) is None
    held = PoseFrame(0, pose.landmarks, None, 1.0, "hold")
    assert sample_top_color(frame, held, seg) is None


def test_matcher_decides_after_warmup_then_needs_a_lasting_change(wardrobe: dict[str, np.ndarray]) -> None:
    matcher = OutfitMatcher(wardrobe, "dress_navy")
    black, white = lab((25, 25, 25)), lab((245, 245, 245))
    switches = [matcher.update(black, i * 100) for i in range(WARMUP_SAMPLES)]
    assert switches[-1] == "chino_khaki" and switches[:-1] == [None] * (WARMUP_SAMPLES - 1)

    assert matcher.update(None, 900) is None  # shirt not visible: nothing changes
    t = 1000
    result = None
    while result is None and t < 1000 + 4 * SWITCH_MS:
        result = matcher.update(white, t)
        t += 100
    assert result == "dress_navy"
    assert t - 1000 >= SWITCH_MS  # not on the first white sample


def test_matcher_follows_a_manual_pick(wardrobe: dict[str, np.ndarray]) -> None:
    matcher = OutfitMatcher(wardrobe, "dress_navy")
    for i in range(WARMUP_SAMPLES):
        matcher.update(lab((245, 245, 245)), i * 100)
    matcher.follow("jeans_indigo")
    assert matcher.current == "jeans_indigo"
