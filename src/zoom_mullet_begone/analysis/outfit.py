"""Pick the pants that go with the shirt: sample the top's color, score each garment.

Colors are CIE Lab (L 0..100). The scoring follows the usual pairing advice:

- contrast in lightness between top and bottom reads well (light top with dark
  pants, dark top with light pants), with no extra credit past a point;
- the same hue at a similar lightness looks like an accidental match (navy
  shirt with indigo jeans), so it is penalized;
- a bright, saturated top wants quiet pants, so pants chroma counts against
  them then.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from zoom_mullet_begone.perception.segmenter import CLOTHES, Segmentation
from zoom_mullet_begone.perception.types import Lm, PoseFrame

SHOULDER_VISIBLE = 0.5
# Part of the torso quad (shoulders -> hips) sampled: away from the arms,
# collar and belt.
SAMPLE_U = (0.2, 0.8)  # across, left shoulder/hip = 0
SAMPLE_V = (0.15, 0.75)  # down, shoulders = 0
MIN_PIXELS = 150
MIN_COVERAGE = 0.4  # of the sampled area that must be clothes

CONTRAST_CAP = 60.0
TONAL_HUE_DEG = 40.0
TONAL_CHROMA = 12.0
TONAL_LIGHTNESS = 40.0
TONAL_PENALTY = 30.0
BRIGHT_CHROMA = 35.0
BRIGHT_WEIGHT = 0.4

COLOR_EMA = 0.2  # per sample
WARMUP_SAMPLES = 8
SWITCH_MARGIN = 6.0  # score points the better garment must win by
SWITCH_MS = 1500  # ...for this long before the pants change


def bgr_to_lab(bgr: np.ndarray) -> np.ndarray:
    """uint8 BGR pixels (..., 3) -> float Lab with L in 0..100."""
    shape = bgr.shape
    lab = cv2.cvtColor(bgr.reshape(-1, 1, 3).astype(np.float32) / 255, cv2.COLOR_BGR2Lab)
    return lab.reshape(shape)


def texture_color(bgra: np.ndarray) -> np.ndarray:
    """Median Lab of a garment texture's opaque pixels (from a 1/8 size copy: same
    median, a fraction of the memory)."""
    h, w = bgra.shape[:2]
    small = cv2.resize(bgra, (max(1, w // 8), max(1, h // 8)), interpolation=cv2.INTER_AREA)
    pixels = small[small[..., 3] > 200][:, :3]
    if len(pixels) == 0:
        raise ValueError("texture has no opaque pixels")
    return np.median(bgr_to_lab(pixels), axis=0)


def _chroma_hue(lab: np.ndarray) -> tuple[float, float]:
    return float(np.hypot(lab[1], lab[2])), float(np.degrees(np.arctan2(lab[2], lab[1])))


def pairing_score(top: np.ndarray, pants: np.ndarray) -> float:
    """Higher is better. Both colors are Lab."""
    dl = abs(float(top[0] - pants[0]))
    score = min(dl, CONTRAST_CAP)
    top_c, top_h = _chroma_hue(top)
    pants_c, pants_h = _chroma_hue(pants)
    hue_gap = abs((top_h - pants_h + 180) % 360 - 180)
    if top_c > TONAL_CHROMA and pants_c > TONAL_CHROMA and hue_gap < TONAL_HUE_DEG:
        score -= TONAL_PENALTY * max(0.0, 1 - dl / TONAL_LIGHTNESS)
    if top_c > BRIGHT_CHROMA:
        score -= BRIGHT_WEIGHT * pants_c
    return score


def best_garment(top: np.ndarray, garments: dict[str, np.ndarray]) -> str:
    """The best-scoring garment id; ties go to the first in `garments`."""
    return max(garments, key=lambda gid: pairing_score(top, garments[gid]))


def top_region(pose: PoseFrame, width: int, height: int) -> np.ndarray | None:
    """uint8 mask of the sampled torso area, or None when shoulders or hips are not seen."""
    if not pose.landmarks or pose.source == "hold":
        return None
    corners = (Lm.LEFT_SHOULDER, Lm.RIGHT_SHOULDER, Lm.LEFT_HIP, Lm.RIGHT_HIP)
    if min(pose.visibility(i) for i in corners) < SHOULDER_VISIBLE:
        return None
    ls, rs, lh, rh = (np.array(pose.landmarks[i].to_px(width, height), np.float64) for i in corners)

    def at(u: float, v: float) -> np.ndarray:
        return (1 - v) * (ls + u * (rs - ls)) + v * (lh + u * (rh - lh))

    (u0, u1), (v0, v1) = SAMPLE_U, SAMPLE_V
    polygon = np.array([at(u0, v0), at(u1, v0), at(u1, v1), at(u0, v1)], np.int32)
    mask = np.zeros((height, width), np.uint8)
    cv2.fillConvexPoly(mask, polygon, 1)
    return mask


def sample_top_color(frame: np.ndarray, pose: PoseFrame, segmentation: Segmentation | None) -> np.ndarray | None:
    """Median Lab color of the shirt, or None when it cannot be seen well enough."""
    height, width = frame.shape[:2]
    region = top_region(pose, width, height)
    if region is None:
        return None
    area = int(region.sum())
    if area < MIN_PIXELS:
        return None
    keep = region.astype(bool)
    if segmentation is not None and segmentation.category.shape == (height, width):
        keep &= segmentation.category == CLOTHES
    elif pose.person_mask is not None and pose.person_mask.shape == (height, width):
        keep &= pose.person_mask >= 0.5
    count = int(keep.sum())
    if count < MIN_PIXELS or count < MIN_COVERAGE * area:
        return None
    return np.median(bgr_to_lab(frame[keep]), axis=0)


@dataclass
class OutfitDecision:
    garment: str
    top: np.ndarray  # smoothed Lab


class OutfitMatcher:
    """Smooths the sampled shirt color and switches garments only on a clear, lasting win."""

    def __init__(self, garments: dict[str, np.ndarray], current: str):
        self._garments = garments
        self.current = current
        self.top: np.ndarray | None = None
        self._samples = 0
        self._decided = False
        self._challenger: str | None = None
        self._since_ms = 0

    def update(self, top: np.ndarray | None, t_ms: int) -> str | None:
        """Feed one sample (None = shirt not visible). Returns the new garment id on a switch."""
        if top is None:
            return None
        self.top = top.copy() if self.top is None else self.top + COLOR_EMA * (top - self.top)
        self._samples += 1
        if self._samples < WARMUP_SAMPLES:
            return None

        best = best_garment(self.top, self._garments)
        if not self._decided:
            self._decided = True
            return self._switch(best)
        if best == self.current:
            self._challenger = None
            return None
        margin = pairing_score(self.top, self._garments[best]) - pairing_score(self.top, self._garments[self.current])
        if margin < SWITCH_MARGIN:
            self._challenger = None
            return None
        if best != self._challenger:
            self._challenger, self._since_ms = best, t_ms
            return None
        if t_ms - self._since_ms >= SWITCH_MS:
            return self._switch(best)
        return None

    def _switch(self, garment: str) -> str | None:
        self._challenger = None
        if garment == self.current:
            return None
        self.current = garment
        return garment

    def follow(self, garment: str) -> None:
        """The garment was changed by hand; judge future switches against it."""
        self.current = garment
        self._challenger = None
