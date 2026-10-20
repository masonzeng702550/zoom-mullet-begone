"""RTMPose fallback, its mapping onto MediaPipe landmarks, and the pose chain's hold."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest
from helpers import make_pose, standing_points

from meet_pants.config import Config
from meet_pants.perception.chain import FALLBACK_RETRY_FRAMES, PoseChain, plausible_fallback
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


def test_knees_pinned_to_the_frame_edge_are_extended_off_screen() -> None:
    """Standing close: the frame ends mid-thigh and the model pins the knees to the
    bottom edge. A 130 px thigh for hips 80 px apart would squash the pants."""
    points, scores = halpe_standing()
    w, h = 400, 335  # bottom edge just below the knees at y=330
    scores[13:17] = 0.4
    scores[20:26] = 0.2
    landmarks = to_mediapipe(points, scores, w, h)
    knee = np.array(landmarks[Lm.LEFT_KNEE].to_px(w, h))
    ankle = np.array(landmarks[Lm.LEFT_ANKLE].to_px(w, h))
    heel = np.array(landmarks[Lm.LEFT_HEEL].to_px(w, h))
    assert knee[1] > h  # off-screen, like MediaPipe's extrapolated landmarks
    assert knee[1] - 200 == pytest.approx(2.0 * 80, abs=2)  # thigh from hip width
    assert abs(knee[0] - 260) <= 1  # along the visible thigh: straight down
    assert ankle[1] > knee[1] + 100 and abs(ankle[0] - 260) <= 1
    np.testing.assert_allclose(heel - ankle, [255 - 260, 470 - 460], atol=1)  # foot moves with the ankle
    assert landmarks[Lm.LEFT_KNEE].visibility == pytest.approx(0.4)


def test_seen_short_thighs_are_kept() -> None:
    """Knees clearly in view stay put even when foreshortened (sitting, knees toward the camera)."""
    points, scores = halpe_standing()
    points[13], points[14] = (262, 250), (178, 250)  # 50 px thighs
    landmarks = to_mediapipe(points, scores, 400, 500)
    assert landmarks[Lm.LEFT_KNEE].to_px(400, 500) == (262, 250)
    assert landmarks[Lm.LEFT_ANKLE].to_px(400, 500) == (260, 460)


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
        # The CPU model misses this frame (the GPU one happens to find it).
        cpu = replace(config.pose, pose_gpu=False)
        with PoseChain.create(config.pose_model_path, config.models_path, cpu) as chain:
            assert not chain._primary.detect(image, 0).has_hips()
            pose = chain.detect(image, 100)
        assert pose.source == "rtmpose" and pose.has_hips()
        h, w = image.shape[:2]
        for i in (Lm.LEFT_KNEE, Lm.RIGHT_KNEE, Lm.LEFT_ANKLE, Lm.RIGHT_ANKLE):
            x, y = pose.landmarks[i].to_px(w, h)
            assert 0 <= x < w and 0 <= y < h
        rtm.reset()
        assert rtm.detect(image, 0).has_hips()


def _mp_with_shoulders(shoulder_y: float) -> PoseFrame:
    pts = standing_points()
    pts[Lm.LEFT_SHOULDER] = (300, shoulder_y)
    pts[Lm.RIGHT_SHOULDER] = (140, shoulder_y)  # 160 px apart
    pose = make_pose(pts, 400, 500)
    hidden_hips = list(pose.landmarks)
    for i in (Lm.LEFT_HIP, Lm.RIGHT_HIP):
        lm = hidden_hips[i]
        hidden_hips[i] = type(lm)(lm.x, lm.y, lm.z, 0.1, 0.1)
    return PoseFrame(0, tuple(hidden_hips), None, 1.0)


def test_fallback_hips_on_the_shoulders_are_rejected() -> None:
    """Only the chest in view: RTMPose calls the shoulders hips. Hips are at y=200."""
    rtm = _pose(33, source="rtmpose")
    assert plausible_fallback(rtm, _mp_with_shoulders(190), 400, 500) is False
    assert plausible_fallback(rtm, _mp_with_shoulders(50), 400, 500) is True  # 150 px above: a real torso
    assert plausible_fallback(rtm, PoseFrame(0, None, None, 1.0), 400, 500) is True  # MediaPipe sees nobody


def test_fallback_hips_below_the_frame_are_rejected() -> None:
    pose = make_pose(standing_points(hip_y=495), 400, 500)
    rtm = PoseFrame(0, pose.landmarks, None, 1.0, "rtmpose")
    assert plausible_fallback(rtm, PoseFrame(0, None, None, 1.0), 400, 500) is False


def test_chain_skips_an_implausible_fallback() -> None:
    primary = FakeDetector([_mp_with_shoulders(190)])
    fallback = FakeDetector([_pose(0, source="rtmpose")])
    pose = PoseChain(primary, fallback).detect(IMAGE, 0)  # type: ignore[arg-type]
    assert pose.source == "mediapipe" and not pose.has_hips()


def test_fallback_without_a_visible_thigh_is_rejected() -> None:
    """Only the belly in view: hips found, but no knee the model is sure about."""
    pose = make_pose(standing_points(), 400, 500)
    landmarks = list(pose.landmarks)
    for i in (Lm.LEFT_KNEE, Lm.RIGHT_KNEE):
        lm = landmarks[i]
        landmarks[i] = type(lm)(lm.x, lm.y, lm.z, 0.2, 0.2)
    rtm = PoseFrame(0, tuple(landmarks), None, 1.0, "rtmpose")
    assert plausible_fallback(rtm, PoseFrame(0, None, None, 1.0), 400, 500) is False


def test_fallback_is_skipped_when_mediapipe_puts_the_hips_below_the_frame() -> None:
    """Sitting at a desk: MediaPipe sees the shoulders, hips extrapolated off-screen."""
    pts = standing_points(hip_y=560)  # frame is 500 tall
    pose = make_pose(pts, 400, 500, visibility=0.95)
    landmarks = list(pose.landmarks)
    for i in (Lm.LEFT_HIP, Lm.RIGHT_HIP):
        lm = landmarks[i]
        landmarks[i] = type(lm)(lm.x, lm.y, lm.z, 0.1, 0.1)
    primary = FakeDetector([PoseFrame(0, tuple(landmarks), None, 1.0)])
    fallback = FakeDetector([_pose(0, source="rtmpose")])
    PoseChain(primary, fallback).detect(IMAGE, 0)  # type: ignore[arg-type]
    assert fallback.calls == 0


def test_fallback_waits_after_a_miss_while_mediapipe_sees_the_person() -> None:
    primary = FakeDetector([_mp_with_shoulders(190)])  # upper body seen, hips not
    fallback = FakeDetector([None])  # finds nobody
    chain = PoseChain(primary, fallback)  # type: ignore[arg-type]
    for i in range(1 + FALLBACK_RETRY_FRAMES + 1):
        chain.detect(IMAGE, i * 33)
    assert fallback.calls == 2  # first frame, then again after the pause


def test_fallback_keeps_trying_when_mediapipe_sees_nobody() -> None:
    primary = FakeDetector([None])
    fallback = FakeDetector([None])
    chain = PoseChain(primary, fallback)  # type: ignore[arg-type]
    for i in range(4):
        chain.detect(IMAGE, i * 33)
    assert fallback.calls == 4


def test_fallback_model_loads_on_first_use() -> None:
    built: list[FakeDetector] = []

    def factory() -> FakeDetector:
        built.append(FakeDetector([_pose(0, source="rtmpose")]))
        return built[-1]

    chain = PoseChain(FakeDetector([_pose(0)]), None, fallback_factory=factory)  # type: ignore[arg-type]
    chain.detect(IMAGE, 0)
    assert built == []  # MediaPipe had the hips: nothing loaded
    chain._primary = FakeDetector([None])  # type: ignore[assignment]
    assert chain.detect(IMAGE, 33).source == "rtmpose" and len(built) == 1
