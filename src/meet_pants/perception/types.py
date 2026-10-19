"""Data passed between the perception, tracking and render stages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import numpy as np


class Lm(IntEnum):
    """MediaPipe pose landmark indices used by this project."""

    NOSE = 0
    LEFT_EYE = 2
    RIGHT_EYE = 5
    LEFT_SHOULDER = 11
    RIGHT_SHOULDER = 12
    LEFT_WRIST = 15
    RIGHT_WRIST = 16
    LEFT_HIP = 23
    RIGHT_HIP = 24
    LEFT_KNEE = 25
    RIGHT_KNEE = 26
    LEFT_ANKLE = 27
    RIGHT_ANKLE = 28
    LEFT_HEEL = 29
    RIGHT_HEEL = 30
    LEFT_FOOT_INDEX = 31
    RIGHT_FOOT_INDEX = 32


LEG_LANDMARKS = tuple(range(Lm.LEFT_HIP, Lm.RIGHT_FOOT_INDEX + 1))
NUM_LANDMARKS = 33


@dataclass(frozen=True)
class Landmark:
    x: float  # normalized to image width
    y: float  # normalized to image height
    z: float
    visibility: float
    presence: float

    def to_px(self, width: int, height: int) -> tuple[int, int]:
        return round(self.x * width), round(self.y * height)


@dataclass(frozen=True)
class PoseFrame:
    t_ms: int
    landmarks: tuple[Landmark, ...] | None  # 33 points, None when nobody is detected
    person_mask: np.ndarray | None  # float32 H x W in [0, 1]
    inference_ms: float

    @property
    def detected(self) -> bool:
        return self.landmarks is not None

    def visibility(self, index: int) -> float:
        return self.landmarks[index].visibility if self.landmarks else 0.0
