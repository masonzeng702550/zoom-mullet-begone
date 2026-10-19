"""One Euro Filter (Casiez et al., 2012) for landmark smoothing.

Low speed -> low cutoff (removes jitter while standing still);
high speed -> higher cutoff (follows fast motion with little lag).
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from meet_pants.config import SmoothingConfig
from meet_pants.perception.types import Landmark, PoseFrame


def _alpha(cutoff: np.ndarray | float, dt: float) -> np.ndarray | float:
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuroFilter:
    """Filters an array of values element-wise; time in seconds."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.05, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.reset()

    def reset(self) -> None:
        self._x: np.ndarray | None = None
        self._dx: np.ndarray | None = None
        self._t = 0.0

    def __call__(self, x: np.ndarray, t: float) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        if self._x is None or self._x.shape != x.shape:
            self._x, self._dx, self._t = x.copy(), np.zeros_like(x), t
            return x.copy()
        dt = t - self._t
        if dt <= 0:
            return self._x.copy()
        dx = (x - self._x) / dt
        self._dx += _alpha(self.d_cutoff, dt) * (dx - self._dx)
        cutoff = self.min_cutoff + self.beta * np.abs(self._dx)
        self._x += _alpha(cutoff, dt) * (x - self._x)
        self._t = t
        return self._x.copy()


class LandmarkSmoother:
    """Smooths landmark x/y in pixel units; visibility and presence pass through.

    Off-screen and occluded landmarks are still smoothed rather than frozen:
    MediaPipe's extrapolated positions are what the mesh needs when a knee or
    ankle is below the frame edge.
    """

    def __init__(self, config: SmoothingConfig):
        self._filter = OneEuroFilter(config.min_cutoff, config.beta, config.d_cutoff)

    def __call__(self, pose: PoseFrame, width: int, height: int) -> PoseFrame:
        if pose.landmarks is None:
            self._filter.reset()
            return pose
        scale = np.array([width, height], dtype=np.float64)
        xy = np.array([(lm.x, lm.y) for lm in pose.landmarks]) * scale
        smooth = self._filter(xy, pose.t_ms / 1000.0) / scale
        landmarks = tuple(
            Landmark(float(sx), float(sy), lm.z, lm.visibility, lm.presence)
            for lm, (sx, sy) in zip(pose.landmarks, smooth)
        )
        return replace(pose, landmarks=landmarks)
