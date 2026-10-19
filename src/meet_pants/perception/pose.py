"""MediaPipe Tasks Vision PoseLandmarker wrapper (VIDEO running mode)."""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

from meet_pants.config import PoseConfig
from meet_pants.perception.types import Landmark, PoseFrame


class PoseDetector:
    def __init__(self, model_path: Path, config: PoseConfig):
        options = vision.PoseLandmarkerOptions(
            base_options=mp_tasks.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=config.min_detection_confidence,
            min_pose_presence_confidence=config.min_presence_confidence,
            min_tracking_confidence=config.min_tracking_confidence,
            output_segmentation_masks=config.segmentation_mask,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)
        self._last_t_ms = -1

    def detect(self, bgr: np.ndarray, t_ms: int) -> PoseFrame:
        # VIDEO mode rejects timestamps that do not strictly increase.
        t_ms = max(t_ms, self._last_t_ms + 1)
        self._last_t_ms = t_ms

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        start = time.perf_counter()
        result = self._landmarker.detect_for_video(image, t_ms)
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
