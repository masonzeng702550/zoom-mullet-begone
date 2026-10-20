"""Pose with fallbacks: MediaPipe first, RTMPose when MediaPipe has no hips, then a short hold.

MediaPipe stays the primary because it is tuned for webcams and also gives the
person mask. The fallback only runs on frames where MediaPipe cannot see the
hips (typically: sitting close, head and chest out of frame). If both miss, the
last good pose is held briefly so a single dropped frame does not make the
pants flicker.

RTMPose always finds *some* hips in a person box, also when only the chest is
in view: it then puts them below the frame or on the shoulders. Those
fallback poses are rejected (see `plausible_fallback`).
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import numpy as np

from zoom_mullet_begone.config import PoseConfig
from zoom_mullet_begone.perception.pose import PoseDetector
from zoom_mullet_begone.perception.types import Lm, PoseFrame

SHOULDER_VISIBLE = 0.5
# Hips at least this many shoulder widths below the shoulders (real torsos: ~1-1.5).
MIN_TORSO = 0.6
# Hips lower than this (fraction of the frame height) leave no leg in view to dress.
MAX_HIP_Y = 0.97
# At least one knee this sure, i.e. a thigh actually in view. With only the belly
# in view RTMPose still reports hips (~0.5) but its knees stay below ~0.28.
MIN_KNEE_SCORE = 0.3
# After the fallback finds nothing usable while MediaPipe sees the upper body,
# skip it for this many frames: it costs about as much CPU as MediaPipe and such
# misses come in long runs (sitting at a desk).
FALLBACK_RETRY_FRAMES = 5


def plausible_fallback(fallback: PoseFrame, primary: PoseFrame, width: int, height: int) -> bool:
    """Whether RTMPose's hips can be real: inside the frame with a thigh in view
    below them, and well below the shoulders when MediaPipe sees them."""
    lh, rh = fallback.landmarks[Lm.LEFT_HIP], fallback.landmarks[Lm.RIGHT_HIP]
    hips_y = (lh.y + rh.y) / 2
    if hips_y > MAX_HIP_Y:
        return False
    if max(fallback.visibility(Lm.LEFT_KNEE), fallback.visibility(Lm.RIGHT_KNEE)) < MIN_KNEE_SCORE:
        return False
    if primary.landmarks is None:
        return True
    if min(primary.visibility(Lm.LEFT_SHOULDER), primary.visibility(Lm.RIGHT_SHOULDER)) < SHOULDER_VISIBLE:
        return True
    ls, rs = primary.landmarks[Lm.LEFT_SHOULDER], primary.landmarks[Lm.RIGHT_SHOULDER]
    shoulder_w = float(np.hypot((ls.x - rs.x) * width, (ls.y - rs.y) * height))
    drop = (hips_y - (ls.y + rs.y) / 2) * height
    return drop >= MIN_TORSO * shoulder_w


def legs_out_of_view(primary: PoseFrame) -> bool:
    """MediaPipe sees the upper body and places the hips below the frame: sitting at
    a desk. RTMPose cannot find usable legs then, so it is not worth running."""
    if primary.landmarks is None:
        return False
    if min(primary.visibility(Lm.LEFT_SHOULDER), primary.visibility(Lm.RIGHT_SHOULDER)) < SHOULDER_VISIBLE:
        return False
    hips_y = (primary.landmarks[Lm.LEFT_HIP].y + primary.landmarks[Lm.RIGHT_HIP].y) / 2
    return hips_y > MAX_HIP_Y


class PoseChain:
    def __init__(
        self,
        primary: PoseDetector,
        fallback: object | None = None,
        hold_ms: int = 0,
        fallback_factory: Callable[[], object] | None = None,
    ):
        self._primary = primary
        self._fallback = fallback  # RtmPoseDetector, or anything with the same detect()/reset()
        self._fallback_factory = fallback_factory  # builds it on first use (saves ~115 MB until then)
        self._hold_ms = hold_ms
        self._last_good: PoseFrame | None = None
        self._retry_in = 0  # frames to wait before trying the fallback again after a miss

    @classmethod
    def create(cls, pose_model: Path, models_dir: Path, config: PoseConfig) -> PoseChain:
        primary = PoseDetector(pose_model, config)
        factory = None
        if config.fallback:
            detector = models_dir / config.fallback_detector
            model = models_dir / config.fallback_model
            if detector.exists() and model.exists():

                def factory() -> object:
                    from zoom_mullet_begone.perception.rtmpose import RtmPoseDetector

                    return RtmPoseDetector(detector, model)
            else:
                print(
                    "pose fallback off: RTMPose models missing; run scripts/download_models.py",
                    file=sys.stderr,
                )
        return cls(primary, None, config.hold_ms, factory)

    @property
    def has_fallback(self) -> bool:
        return self._fallback is not None or self._fallback_factory is not None

    def _fallback_pose(self, bgr: np.ndarray, pose: PoseFrame) -> PoseFrame | None:
        """RTMPose's pose if it is worth trying this frame and plausible, else None."""
        if not self.has_fallback or legs_out_of_view(pose):
            return None
        if self._retry_in > 0:
            self._retry_in -= 1
            return None
        if self._fallback is None:
            self._fallback = self._fallback_factory()
        rtm = self._fallback.detect(bgr, pose.t_ms, pose.person_mask)
        rtm = replace(rtm, inference_ms=pose.inference_ms + rtm.inference_ms)
        height, width = bgr.shape[:2]
        if rtm.has_hips() and plausible_fallback(rtm, pose, width, height):
            return rtm
        if pose.detected:
            # MediaPipe sees the person, just not the legs (upper body only): wait a
            # bit before the next try. When it sees nobody (too close for it), keep
            # trying every frame; that is the case the fallback exists for.
            self._retry_in = FALLBACK_RETRY_FRAMES
        return None

    def detect(self, bgr: np.ndarray, t_ms: int) -> PoseFrame:
        pose = self._primary.detect(bgr, t_ms)
        if not pose.has_hips():
            pose = self._fallback_pose(bgr, pose) or pose
        else:
            self._retry_in = 0
            if self._fallback is not None:
                self._fallback.reset()  # re-detect the person next time it is needed

        if pose.has_hips():
            self._last_good = pose
            return pose
        held = self._last_good
        if held is not None and pose.t_ms - held.t_ms <= self._hold_ms:
            return replace(
                held,
                t_ms=pose.t_ms,
                person_mask=pose.person_mask,
                inference_ms=pose.inference_ms,
                source="hold",
            )
        self._last_good = None
        return pose

    def close(self) -> None:
        self._primary.close()

    def __enter__(self) -> PoseChain:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
