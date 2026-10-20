"""Frame sources: a live camera (threaded, latest frame only) or a video file."""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Frame:
    image: np.ndarray  # BGR uint8, H x W x 3
    t_ms: int  # capture timestamp in milliseconds, strictly increasing per source
    index: int


class CaptureError(RuntimeError):
    pass


class FrameSource:
    is_live: bool
    fps: float
    size: tuple[int, int]  # (width, height)

    def read(self, timeout: float = 2.0) -> Frame | None:
        """Return the next frame, or None when the source has ended."""
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def __enter__(self) -> FrameSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class CameraSource(FrameSource):
    """Reads a camera on a background thread and keeps only the newest frame.

    Dropping stale frames keeps latency flat when processing is slower than the
    camera; read() never returns the same frame twice.
    """

    is_live = True

    def __init__(self, index: int, resolution: tuple[int, int], fps: int):
        backend = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
        self._cap = cv2.VideoCapture(index, backend)
        if not self._cap.isOpened():
            raise CaptureError(
                f"cannot open camera {index}"
                + (" (check camera permission for your terminal app)" if sys.platform == "darwin" else "")
            )
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])
        self._cap.set(cv2.CAP_PROP_FPS, fps)

        ok, first = self._cap.read()
        if not ok:
            self._cap.release()
            raise CaptureError(f"camera {index} opened but returned no frame")
        self.size = (first.shape[1], first.shape[0])
        self.fps = self._cap.get(cv2.CAP_PROP_FPS) or float(fps)

        self._cond = threading.Condition()
        self._latest: Frame | None = None
        self._last_read_index = -1
        self._next_index = 0
        self._last_t_ms = -1
        self._running = True
        self._failed = False
        self._store(first)
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()

    def _store(self, image: np.ndarray) -> None:
        t_ms = max(time.monotonic_ns() // 1_000_000, self._last_t_ms + 1)
        self._last_t_ms = t_ms
        with self._cond:
            self._latest = Frame(image, t_ms, self._next_index)
            self._next_index += 1
            self._cond.notify_all()

    def _loop(self) -> None:
        while self._running:
            ok, image = self._cap.read()
            if not ok:
                with self._cond:
                    self._failed = True
                    self._cond.notify_all()
                return
            self._store(image)

    def read(self, timeout: float = 2.0) -> Frame | None:
        with self._cond:
            fresh = self._cond.wait_for(
                lambda: self._failed
                or (self._latest is not None and self._latest.index > self._last_read_index),
                timeout=timeout,
            )
            if not fresh or self._failed or self._latest is None:
                return None
            self._last_read_index = self._latest.index
            return self._latest

    def close(self) -> None:
        self._running = False
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._cap.release()


class VideoFileSource(FrameSource):
    """Reads every frame of a file in order; timestamps come from the frame index."""

    is_live = False

    def __init__(self, path: str):
        self._cap = cv2.VideoCapture(path)
        if not self._cap.isOpened():
            raise CaptureError(f"cannot open video file: {path}")
        self.fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.size = (
            int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
        self._index = 0

    def read(self, timeout: float = 2.0) -> Frame | None:
        ok, image = self._cap.read()
        if not ok:
            return None
        frame = Frame(image, round(self._index * 1000 / self.fps), self._index)
        self._index += 1
        return frame

    def close(self) -> None:
        self._cap.release()


def open_source(input_: int | str, resolution: tuple[int, int], fps: int) -> FrameSource:
    if isinstance(input_, int):
        return CameraSource(input_, resolution, fps)
    return VideoFileSource(input_)
