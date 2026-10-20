from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from zoom_mullet_begone.config import DebugConfig
from zoom_mullet_begone.io.capture import CaptureError, VideoFileSource, open_source
from zoom_mullet_begone.io.preview import Stats, render_preview
from zoom_mullet_begone.perception.types import NUM_LANDMARKS, Landmark, PoseFrame


def test_video_file_reads_all_frames_with_increasing_timestamps(blank_video: Path) -> None:
    with VideoFileSource(str(blank_video)) as source:
        assert source.size == (160, 120)
        assert not source.is_live
        frames = []
        while (frame := source.read()) is not None:
            frames.append(frame)
    assert [f.index for f in frames] == list(range(10))
    times = [f.t_ms for f in frames]
    assert times[0] == 0
    assert all(b > a for a, b in zip(times, times[1:]))


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(CaptureError):
        open_source(str(tmp_path / "nope.mp4"), (640, 480), 30)


def _fake_pose(width: int, height: int) -> PoseFrame:
    landmarks = tuple(
        Landmark(x=0.2 + 0.6 * i / NUM_LANDMARKS, y=i / NUM_LANDMARKS, z=0.0, visibility=0.9, presence=0.9)
        for i in range(NUM_LANDMARKS)
    )
    mask = np.zeros((height, width), np.float32)
    mask[:, : width // 2] = 1.0
    return PoseFrame(t_ms=0, landmarks=landmarks, person_mask=mask, inference_ms=10.0)


def test_preview_draws_on_copy_and_mirrors() -> None:
    frame = np.zeros((120, 160, 3), np.uint8)
    pose = _fake_pose(160, 120)
    all_on = DebugConfig(landmarks=True, masks=True, hud=False)

    plain = render_preview(frame, pose, all_on, Stats(), mirror=False)
    mirrored = render_preview(frame, pose, all_on, Stats(), mirror=True)

    assert not frame.any(), "preview must not draw on the frame sent to the virtual camera"
    assert plain.any()
    np.testing.assert_array_equal(mirrored, plain[:, ::-1])


def test_preview_with_no_person_and_hud() -> None:
    frame = np.zeros((120, 160, 3), np.uint8)
    pose = PoseFrame(t_ms=0, landmarks=None, person_mask=None, inference_ms=5.0)
    image = render_preview(frame, pose, DebugConfig(), Stats(), mirror=True)
    assert image.shape == frame.shape


def test_stats_smoothing() -> None:
    stats = Stats()
    stats.update(frame_ms=40.0, inference_ms=20.0)
    assert stats.fps == pytest.approx(25.0)
    stats.update(frame_ms=20.0, inference_ms=20.0)
    assert 25.0 < stats.fps < 50.0
