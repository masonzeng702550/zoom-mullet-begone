"""MediaPipe Tasks Vision PoseLandmarker wrapper (VIDEO running mode)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

from meet_pants.config import PoseConfig
from meet_pants.perception.types import Landmark, PoseFrame


def to_mp_image(bgr: np.ndarray, gpu: bool) -> mp.Image:
    """MediaPipe image from a BGR frame; the GPU path only accepts 4-channel input."""
    if gpu:
        return mp.Image(image_format=mp.ImageFormat.SRGBA, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA))
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


class PoseDetector:
    def __init__(self, model_path: Path, config: PoseConfig):
        self._model_path = model_path
        self._config = config
        self.gpu = False
        if config.pose_gpu:
            try:
                self._landmarker = self._create(gpu=True)
                self.gpu = True
            except (RuntimeError, ValueError) as e:
                print(f"pose model on CPU (GPU unavailable: {e})", file=sys.stderr)
        if not self.gpu:
            self._landmarker = self._create(gpu=False)
        self._last_t_ms = -1

    def _create(self, gpu: bool) -> vision.PoseLandmarker:
        delegate = mp_tasks.BaseOptions.Delegate.GPU if gpu else mp_tasks.BaseOptions.Delegate.CPU
        options = vision.PoseLandmarkerOptions(
            base_options=mp_tasks.BaseOptions(model_asset_path=str(self._model_path), delegate=delegate),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=self._config.min_detection_confidence,
            min_pose_presence_confidence=self._config.min_presence_confidence,
            min_tracking_confidence=self._config.min_tracking_confidence,
            output_segmentation_masks=self._config.segmentation_mask,
        )
        return vision.PoseLandmarker.create_from_options(options)

    def detect(self, bgr: np.ndarray, t_ms: int) -> PoseFrame:
        # VIDEO mode rejects timestamps that do not strictly increase.
        t_ms = max(t_ms, self._last_t_ms + 1)
        self._last_t_ms = t_ms

        start = time.perf_counter()
        try:
            result = self._landmarker.detect_for_video(to_mp_image(bgr, self.gpu), t_ms)
        except (RuntimeError, ValueError) as e:
            if not self.gpu:
                raise
            print(f"pose model moved to CPU (GPU failed: {e})", file=sys.stderr)
            self._landmarker.close()
            self._landmarker, self.gpu = self._create(gpu=False), False
            result = self._landmarker.detect_for_video(to_mp_image(bgr, False), t_ms)
        inference_ms = (time.perf_counter() - start) * 1000

        landmarks = None
        if result.pose_landmarks:
            landmarks = tuple(
                Landmark(lm.x, lm.y, lm.z, lm.visibility or 0.0, lm.presence or 0.0)
                for lm in result.pose_landmarks[0]
            )

        mask = None
        if result.segmentation_masks:
            # numpy_view() borrows the Image's buffer; copy before it is released.
            mask = np.array(result.segmentation_masks[0].numpy_view(), dtype=np.float32)
            if mask.ndim == 3:
                mask = mask[..., 0]

        return PoseFrame(t_ms, landmarks, mask, inference_ms)

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self) -> PoseDetector:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
