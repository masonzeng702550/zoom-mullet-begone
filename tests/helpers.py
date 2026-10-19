"""Synthetic poses for geometry and rendering tests."""

from __future__ import annotations

import numpy as np

from meet_pants.perception.types import NUM_LANDMARKS, Landmark, Lm, PoseFrame


def make_pose(
    points_px: dict[int, tuple[float, float]],
    width: int,
    height: int,
    mask: np.ndarray | None = None,
    visibility: float = 0.95,
    t_ms: int = 0,
) -> PoseFrame:
    """A PoseFrame with the given landmarks (pixels); others sit off-screen."""
    landmarks = []
    for i in range(NUM_LANDMARKS):
        x, y = points_px.get(i, (-500.0, -500.0))
        landmarks.append(Landmark(x / width, y / height, 0.0, visibility, visibility))
    return PoseFrame(t_ms, tuple(landmarks), mask, 1.0)


def standing_points(
    hip_y: float = 200,
    knee_y: float = 330,
    ankle_y: float = 460,
    left_x: float = 260,
    right_x: float = 180,
) -> dict[int, tuple[float, float]]:
    """A person facing the camera: anatomical left appears on screen right."""
    return {
        Lm.LEFT_SHOULDER: (left_x + 10, hip_y - 150),
        Lm.RIGHT_SHOULDER: (right_x - 10, hip_y - 150),
        Lm.LEFT_HIP: (left_x, hip_y),
        Lm.RIGHT_HIP: (right_x, hip_y),
        Lm.LEFT_KNEE: (left_x, knee_y),
        Lm.RIGHT_KNEE: (right_x, knee_y),
        Lm.LEFT_ANKLE: (left_x, ankle_y),
        Lm.RIGHT_ANKLE: (right_x, ankle_y),
    }


def legs_mask(width: int, height: int, centers_x: list[float], half: float, top: int, bottom: int) -> np.ndarray:
    """Vertical rectangular legs plus a torso block above `top`."""
    mask = np.zeros((height, width), np.float32)
    for cx in centers_x:
        mask[top:bottom, int(cx - half) : int(cx + half)] = 1.0
    xs = sorted(centers_x)
    mask[: top, int(xs[0] - half) : int(xs[-1] + half)] = 1.0
    return mask
