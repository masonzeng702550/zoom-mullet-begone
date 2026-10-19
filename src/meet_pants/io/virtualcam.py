"""Virtual camera output via pyvirtualcam (OBS Virtual Camera backend on macOS/Windows)."""

from __future__ import annotations

import numpy as np
import pyvirtualcam


class VirtualCamError(RuntimeError):
    pass


class VirtualCam:
    def __init__(self, width: int, height: int, fps: float):
        try:
            self._cam = pyvirtualcam.Camera(
                width=width, height=height, fps=fps, fmt=pyvirtualcam.PixelFormat.BGR
            )
        except RuntimeError as e:
            raise VirtualCamError(
                f"{e}\n"
                "Install OBS Studio (30+), click 'Start Virtual Camera' once, then close OBS. "
                "Or run with --no-vcam to only use the preview."
            ) from e
        self.device = self._cam.device

    def send(self, bgr: np.ndarray) -> None:
        self._cam.send(bgr)

    def close(self) -> None:
        self._cam.close()

    def __enter__(self) -> VirtualCam:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
