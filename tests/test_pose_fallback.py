"""RTMPose fallback, its mapping onto MediaPipe landmarks, and the pose chain's hold."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from helpers import make_pose, standing_points

from meet_pants.config import Config
from meet_pants.perception.chain import PoseChain
from meet_pants.perception.rtmpose import RtmPoseDetector, to_mediapipe
from meet_pants.perception.types import NUM_LANDMARKS, Lm, PoseFrame

ROOT = Path(__file__).resolve().parents[1]
# A webcam frame cropped to waist and legs (person too close), where MediaPipe
# finds nobody; private, not committed.
HEADLESS = [ROOT / "data" / "headless_430.jpg"]


def halpe_standing() -> tuple[np.ndarray, np.ndarray]:
    points = np.zeros((26, 2))
    scores = np.full(26, 0.9)
    points[5], points[6] = (270, 50), (170, 50)  # shoulders
    points[7], points[8] = (290, 120), (150, 120)
    points[9], points[10] = (300, 190), (140, 190)
    points[11], points[12] = (260, 200), (180, 200)  # hips
    points[13], points[14] = (260, 330), (180, 330)
    points[15], points[16] = (260, 460), (180, 460)
    points[20], points[21] = (270, 480), (170, 480)
    points[24], points[25] = (255, 470), (185, 470)
    return points, scores


def test_mapping_fills_all_mediapipe_landmarks() -> None:
    points, scores = halpe_standing()
    landmarks = to_mediapipe(points, scores, 400, 500)
    assert len(landmarks) == NUM_LANDMARKS
    assert landmarks[Lm.LEFT_HIP].to_px(400, 500) == (260, 200)
    assert landmarks[Lm.RIGHT_ANKLE].to_px(400, 500) == (180, 460)
    assert landmarks[Lm.LEFT_HEEL].to_px(400, 500) == (255, 470)
    assert landmarks[Lm.LEFT_INDEX].to_px(400, 500) == landmarks[Lm.LEFT_WRIST].to_px(400, 500)


def test_unseen_shoulders_are_placed_above_the_hips() -> None:
    points, scores = halpe_standing()
    points[5], points[6] = (240, 600), (200, 600)  # nonsense guesses below the knees
    scores[5:11] = 0.1  # shoulders and arms out of frame
    landmarks = to_mediapipe(points, scores, 400, 500)
    ls = np.array(landmarks[Lm.LEFT_SHOULDER].to_px(400, 500))
    hip = np.array(landmarks[Lm.LEFT_HIP].to_px(400, 500))
    assert ls[1] < hip[1] - 100  # well above the hip
    assert abs(ls[0] - hip[0]) < 5  # straight up for an upright body
    assert landmarks[Lm.LEFT_SHOULDER].visibility == pytest.approx(0.1)
    # Unseen arms sit at the shoulders, away from the legs.
    assert landmarks[Lm.LEFT_WRIST].to_px(400, 500) == tuple(ls)


class FakeDetector:
    def __init__(self, frames: list[PoseFrame | None]):
        self.frames = frames
        self.calls = 0
        self.resets = 0

    def detect(self, bgr: np.ndarray, t_ms: int, person_mask: np.ndarray | None = None) -> PoseFrame:
        frame = self.frames[min(self.calls, len(self.frames) - 1)]
        self.calls += 1
        return frame if frame is not None else PoseFrame(t_ms, None, None, 1.0)

    def reset(self) -> None:
        self.resets += 1

    def close(self) -> None:
        pass


def _pose(t_ms: int, visibility: float = 0.95, source: str = "mediapipe") -> PoseFrame:
    pose = make_pose(standing_points(), 400, 500, visibility=visibility, t_ms=t_ms)
    return PoseFrame(pose.t_ms, pose.landmarks, None, 1.0, source)


IMAGE = np.zeros((500, 400, 3), np.uint8)


def test_chain_uses_fallback_only_without_hips() -> None:
    primary = FakeDetector([_pose(0), _pose(33, visibility=0.1)])
    fallback = FakeDetector([_pose(33, source="rtmpose")])
    chain = PoseChain(primary, fallback)  # type: ignore[arg-type]
    assert chain.detect(IMAGE, 0).source == "mediapipe"
    assert fallback.calls == 0 and fallback.resets == 1
    assert chain.detect(IMAGE, 33).source == "rtmpose"
    assert fallback.calls == 1


def test_chain_holds_the_last_pose_briefly() -> None:
    primary = FakeDetector([_pose(0), None])
    chain = PoseChain(primary, None, hold_ms=100)  # type: ignore[arg-type]
    chain.detect(IMAGE, 0)
    held = chain.detect(IMAGE, 66)
    assert held.source == "hold" and held.t_ms == 66 and held.has_hips()
    assert not chain.detect(IMAGE, 133).detected  # hold expired
    assert not chain.detect(IMAGE, 150).detected  # and does not come back


def test_fallback_finds_hips_when_mediapipe_cannot(config: Config) -> None:
    models = [config.models_path / config.pose.fallback_detector, config.models_path / config.pose.fallback_model]
    if not all(p.exists() for p in models) or not config.pose_model_path.exists():
        pytest.skip("models missing; run scripts/download_models.py")
    images = [cv2.imread(str(p)) for p in HEADLESS if p.exists()]
    if not images:
        pytest.skip("data/headless_430.jpg missing (private webcam crop, not committed)")
    rtm = RtmPoseDetector(*models)
    for image in images:
        with PoseChain.create(config.pose_model_path, config.models_path, config.pose) as chain:
            assert not chain._primary.detect(image, 0).has_hips()
            pose = chain.detect(image, 100)
        assert pose.source == "rtmpose" and pose.has_hips()
        h, w = image.shape[:2]
        for i in (Lm.LEFT_KNEE, Lm.RIGHT_KNEE, Lm.LEFT_ANKLE, Lm.RIGHT_ANKLE):
            x, y = pose.landmarks[i].to_px(w, h)
            assert 0 <= x < w and 0 <= y < h
        rtm.reset()
        assert rtm.detect(image, 0).has_hips()
