"""Background mode: start the pants when a meeting app opens the virtual camera.

States:
    waiting  camera off, nothing sent; checks twice a second whether any app
             opened the virtual camera (CameraWatcher)
    active   the pipeline runs (camera on, frames to the virtual camera)
    paused   automatic start turned off from the menu

While active, meet-pants' own frames keep the virtual camera "in use", so the
service cannot see a meeting app leave. When nobody has been in view for a
minute, it stops sending for a moment and checks again (RunControl.probe);
with nobody in view, the brief OBS placeholder the meeting sees is harmless.
If no app reads the camera any more, it goes back to waiting.

Where the watcher is not supported (not macOS, or no virtual camera), the
service runs the pipeline as soon as it starts.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from meet_pants.config import Config
from meet_pants.io.camwatch import CameraWatcher
from meet_pants.pipeline import RunControl, run
from meet_pants.ui.settings import GarmentChoice, SettingsHub, SettingsServer

POLL_S = 0.5
PROBE_SETTLE_S = 0.15  # after closing our output, before reading the in-use flag
PREVIEW_EVERY_S = 0.3
PREVIEW_WIDTH = 480
RETRY_AFTER_ERROR_S = 5.0

STATUS_TEXT = {
    "waiting": "待命中：會議軟體打開 OBS Virtual Camera 時會自動開始",
    "starting": "啟動中…",
    "active": "執行中：正在套用褲子",
    "paused": "已暫停自動啟動",
    "error": "發生錯誤，稍後重試（詳見終端機）",
}


class BackgroundService:
    def __init__(
        self,
        config: Config,
        settings_path: Path | None,
        watcher: CameraWatcher | None = None,
        runner: Callable[..., int] = run,
    ):
        # The service owns the output: no preview window, frames to the virtual camera.
        self.config = replace(config, preview=False, vcam=True)
        self.watcher = watcher or CameraWatcher()
        self._runner = runner
        self.hub = SettingsHub(
            Path(config.garments_dir),
            GarmentChoice(config.garment, config.garment_color, config.garment_auto),
            settings_path,
        )
        self.server: SettingsServer | None = None
        self.state = "waiting"
        self.auto_start = True
        self.sessions = 0
        self.on_change: Callable[[], None] | None = None  # e.g. refresh the menu bar
        self._quit = threading.Event()
        self._control: RunControl | None = None
        self._last_preview = 0.0
        self._thread = threading.Thread(target=self._loop, name="meet-pants-service", daemon=True)

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> BackgroundService:
        if self.config.settings_port:
            try:
                self.server = SettingsServer(self.hub, self.config.settings_port).start()
                print(f"settings page: {self.server.url}")
            except OSError as e:
                print(f"settings page off: port {self.config.settings_port} unavailable ({e})", file=sys.stderr)
        if not self.watcher.supported or self.watcher.in_use() is None:
            print("cannot tell when a meeting opens the virtual camera here; running all the time")
        self._set_state("waiting")
        self._thread.start()
        return self

    def quit(self) -> None:
        self._quit.set()
        self._stop_session()
        self._thread.join(timeout=5)
        if self.server is not None:
            self.server.close()

    def set_auto_start(self, enabled: bool) -> None:
        self.auto_start = enabled
        if not enabled:
            self._stop_session()
        self._set_state("waiting" if enabled else "paused")

    # -- internals -----------------------------------------------------------

    def _set_state(self, state: str) -> None:
        self.state = state
        self.hub.status = STATUS_TEXT[state]
        if state != "active":
            self.hub.set_preview(None)
        if self.on_change is not None:
            self.on_change()

    def _stop_session(self) -> None:
        control = self._control
        if control is not None:
            control.stop.set()

    def _meeting_wants_camera(self) -> bool:
        used = self.watcher.in_use()
        return True if used is None else used  # unknown: always on

    def _loop(self) -> None:
        while not self._quit.is_set():
            if not self.auto_start or not self._meeting_wants_camera():
                self._quit.wait(POLL_S)
                continue
            self._session()

    def _session(self) -> None:
        self._set_state("starting")
        self._control = RunControl(
            hub=self.hub,
            on_frame=self._preview,
            probe=self._probe if self.watcher.in_use() is not None else None,
        )
        self.sessions += 1
        try:
            self._set_state("active")
            status = self._runner(self.config, control=self._control)
        except Exception as e:  # keep the service alive; the next meeting tries again
            print(f"pipeline failed: {e!r}", file=sys.stderr)
            status = 1
        self._control = None
        if self._quit.is_set():
            return
        if status != 0:
            self._set_state("error")
            self._quit.wait(RETRY_AFTER_ERROR_S)
        self._set_state("waiting" if self.auto_start else "paused")

    def _probe(self) -> bool:
        """Called with our output closed: does any app still read the virtual camera?"""
        time.sleep(PROBE_SETTLE_S)
        return bool(self.watcher.in_use()) and self.auto_start and not self._quit.is_set()

    def _preview(self, frame: np.ndarray) -> None:
        now = time.perf_counter()
        if now - self._last_preview < PREVIEW_EVERY_S:
            return
        self._last_preview = now
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (PREVIEW_WIDTH, round(h * PREVIEW_WIDTH / w)), interpolation=cv2.INTER_AREA)
        ok, jpeg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            self.hub.set_preview(jpeg.tobytes())
