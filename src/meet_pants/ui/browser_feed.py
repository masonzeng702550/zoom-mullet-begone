"""Live video for the meet-pants browser extension (no virtual camera driver needed).

The extension adds a "meet-pants" camera to web pages and reads frames from
the settings server as an MJPEG stream (`/stream.mjpg`). Frames are encoded
only while a client is connected.

Only browser extensions may read the stream: the request must carry an
`Origin: chrome-extension://…` (or moz-extension) header, which web pages
cannot forge, so a website cannot pull the camera through it.
"""

from __future__ import annotations

import threading
import time

import cv2
import numpy as np

JPEG_QUALITY = 80
EXTENSION_ORIGINS = ("chrome-extension://", "moz-extension://")


def is_extension_origin(origin: str | None) -> bool:
    return bool(origin) and origin.startswith(EXTENSION_ORIGINS)


class FrameFeed:
    """Latest output frame as JPEG, handed to any number of stream readers."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._jpeg: bytes | None = None
        self._seq = 0
        self._clients = 0
        self._closed = False
        self.idle_since = time.monotonic()  # when the last client left (or creation)

    @property
    def clients(self) -> int:
        with self._cond:
            return self._clients

    def connect(self) -> None:
        with self._cond:
            self._clients += 1

    def disconnect(self) -> None:
        with self._cond:
            self._clients = max(0, self._clients - 1)
            if self._clients == 0:
                self.idle_since = time.monotonic()
                self._jpeg = None  # a new client should not get a stale picture

    def publish(self, frame: np.ndarray) -> None:
        """Encode and hand out a frame, if anyone is watching."""
        if self.clients == 0:
            return
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            return
        with self._cond:
            self._jpeg = jpeg.tobytes()
            self._seq += 1
            self._cond.notify_all()

    def next_frame(self, after: int, timeout: float = 1.0) -> tuple[int, bytes] | None:
        """The first frame newer than sequence number `after`, or None on timeout / close."""
        with self._cond:
            self._cond.wait_for(lambda: self._closed or (self._jpeg is not None and self._seq > after), timeout)
            if self._closed or self._jpeg is None or self._seq <= after:
                return None
            return self._seq, self._jpeg

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()
