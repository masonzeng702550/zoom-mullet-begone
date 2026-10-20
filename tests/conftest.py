from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from zoom_mullet_begone.config import Config

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_IMAGE = ROOT / "data" / "pose.jpg"  # python scripts/download_models.py does not fetch this


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def model_path(config: Config) -> Path:
    if not config.pose_model_path.exists():
        pytest.skip("pose model missing; run scripts/download_models.py")
    return config.pose_model_path


def write_video(path: Path, frames: list[np.ndarray], fps: float = 30.0) -> Path:
    h, w = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    assert writer.isOpened()
    for f in frames:
        writer.write(f)
    writer.release()
    return path


@pytest.fixture
def blank_video(tmp_path: Path) -> Path:
    frames = [np.full((120, 160, 3), i * 20, np.uint8) for i in range(10)]
    return write_video(tmp_path / "blank.mp4", frames)


@pytest.fixture
def person_image() -> np.ndarray:
    if not SAMPLE_IMAGE.exists():
        pytest.skip("data/pose.jpg missing (MediaPipe sample image, not committed)")
    return cv2.imread(str(SAMPLE_IMAGE))


@pytest.fixture
def person_video(tmp_path: Path, person_image: np.ndarray) -> Path:
    """The sample image panned sideways to simulate motion."""
    frames = [np.roll(person_image, shift=i * 4, axis=1) for i in range(20)]
    return write_video(tmp_path / "person.mp4", frames)
