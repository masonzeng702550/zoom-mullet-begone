"""Integration tests that run the real PoseLandmarker model."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from zoom_mullet_begone.config import Config, PoseConfig
from zoom_mullet_begone.perception.pose import PoseDetector
from zoom_mullet_begone.perception.types import NUM_LANDMARKS, Lm
from zoom_mullet_begone.pipeline import run


def test_detects_full_body(model_path: Path, person_image: np.ndarray) -> None:
    with PoseDetector(model_path, PoseConfig()) as detector:
        pose = detector.detect(person_image, 0)

    assert pose.detected
    assert len(pose.landmarks) == NUM_LANDMARKS
    for i in (Lm.LEFT_HIP, Lm.RIGHT_HIP, Lm.LEFT_KNEE, Lm.RIGHT_KNEE, Lm.LEFT_ANKLE, Lm.RIGHT_ANKLE):
        assert pose.visibility(i) > 0.5, Lm(i).name
    # In the sample the person stands with feet apart, knees below hips, ankles below knees.
    lm = pose.landmarks
    for hip, knee, ankle in ((Lm.LEFT_HIP, Lm.LEFT_KNEE, Lm.LEFT_ANKLE), (Lm.RIGHT_HIP, Lm.RIGHT_KNEE, Lm.RIGHT_ANKLE)):
        assert lm[hip].y < lm[knee].y < lm[ankle].y

    h, w = person_image.shape[:2]
    assert pose.person_mask is not None and pose.person_mask.shape == (h, w)
    hip_x, hip_y = lm[Lm.LEFT_HIP].to_px(w, h)
    assert pose.person_mask[hip_y, hip_x] > 0.5
    assert pose.person_mask[5, 5] < 0.5  # sky


def test_repeated_timestamps_are_accepted(model_path: Path, person_image: np.ndarray) -> None:
    with PoseDetector(model_path, PoseConfig(segmentation_mask=False)) as detector:
        first = detector.detect(person_image, 100)
        second = detector.detect(person_image, 100)
    assert second.t_ms > first.t_ms
    assert second.person_mask is None


def test_no_person_in_blank_frame(model_path: Path) -> None:
    with PoseDetector(model_path, PoseConfig()) as detector:
        pose = detector.detect(np.zeros((240, 320, 3), np.uint8), 0)
    assert not pose.detected


def test_pipeline_headless(model_path: Path, person_video: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = replace(Config(), input=str(person_video), vcam=False, preview=False)
    assert run(config, max_frames=15) == 0
    out = capsys.readouterr().out
    assert "done   15 frames" in out
    assert "person detected in 100% of frames" in out
    assert "pants drawn in 100%" in out
