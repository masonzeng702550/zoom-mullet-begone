"""MediaPipe multiclass selfie segmenter (hair / body skin / face skin / clothes),
run on a background thread.

The model costs about 20 ms per frame whatever the input size, so it runs in
parallel with the pose model and the main loop uses the newest finished mask
(typically one frame old). Leg widths are smoothed over time anyway, so the
lag is not visible.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

BACKGROUND, HAIR, BODY_SKIN, FACE_SKIN, CLOTHES, OTHERS = range(6)
MODEL_NAME = "selfie_multiclass_256x256.tflite"
INPUT_WIDTH = 640  # the model works at 256x256; a bigger input only costs resize time


@dataclass(frozen=True)
class Segmentation:
    t_ms: int
    category: np.ndarray  # uint8 H x W at full frame size

    @property
    def skin(self) -> np.ndarray:
        return self.category == BODY_SKIN

    @property
    def body(self) -> np.ndarray:
        """Everything that belongs to the person's body or what they wear (not hair or face)."""
        return (self.category == BODY_SKIN) | (self.category == CLOTHES) | (self.category == OTHERS)


class BodySegmenter:
    def __init__(self, model_path: Path):
        options = vision.ImageSegmenterOptions(
            base_options=mp_tasks.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            output_category_mask=True,
            output_confidence_masks=False,
        )
        self._segmenter = vision.ImageSegmenter.create_from_options(options)
        self._cond = threading.Condition()
        self._pending: tuple[np.ndarray, int] | None = None
        self._result: tuple[np.ndarray, int, tuple[int, int]] | None = None
        self._full: Segmentation | None = None
        self._last_t_ms = -1
        self._error: BaseException | None = None
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="segmenter", daemon=True)
        self._thread.start()

    def submit(self, bgr: np.ndarray, t_ms: int) -> None:
        """Queue a frame; replaces any frame still waiting (only the newest matters)."""
        with self._cond:
            if self._error is not None:
                raise RuntimeError("segmenter thread failed") from self._error
            self._pending = (bgr, t_ms)
            self._cond.notify()

    def _loop(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._pending is not None or not self._running)
                if not self._running:
                    return
                bgr, t_ms = self._pending
                self._pending = None
            try:
                h, w = bgr.shape[:2]
                small_h = max(1, round(h * INPUT_WIDTH / w))
                small = cv2.resize(bgr, (INPUT_WIDTH, small_h), interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                t_ms = max(t_ms, self._last_t_ms + 1)  # VIDEO mode needs increasing timestamps
                self._last_t_ms = t_ms
                result = self._segmenter.segment_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), t_ms
                )
                category = np.array(result.category_mask.numpy_view(), dtype=np.uint8).reshape(small_h, INPUT_WIDTH)
            except BaseException as e:  # surfaced to the main thread on the next submit()
                with self._cond:
                    self._error = e
                return
            with self._cond:
                self._result = (category, t_ms, (w, h))
                self._cond.notify_all()

    def latest(self) -> Segmentation | None:
        """The newest finished segmentation, upscaled to frame size (cached)."""
        with self._cond:
            result = self._result
        if result is None:
            return None
        category, t_ms, (w, h) = result
        if self._full is None or self._full.t_ms != t_ms:
            self._full = Segmentation(t_ms, cv2.resize(category, (w, h), interpolation=cv2.INTER_NEAREST))
        return self._full

    def wait(self, timeout: float = 1.0) -> Segmentation | None:
        """Block until a result exists (for tests and still images)."""
        with self._cond:
            self._cond.wait_for(lambda: self._result is not None or self._error is not None, timeout)
        return self.latest()

    def close(self) -> None:
        with self._cond:
            self._running = False
            self._cond.notify_all()
        self._thread.join(timeout=2.0)
        self._segmenter.close()

    def __enter__(self) -> BodySegmenter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
