"""Background mode: start the pants when a meeting opens the camera.

A meeting can use zoom-mullet-begone two ways: through the virtual camera (OBS
Virtual Camera, any app) or through the browser extension (web pages only, no
driver needed). Without OBS the service serves the extension alone.

States:
    waiting  camera off, nothing sent; checks twice a second whether any app
             opened the virtual camera (CameraWatcher) or a browser tab is
             reading the extension stream
    active   the pipeline runs (camera on, frames to the virtual camera)
    paused   automatic start turned off from the menu

While active, zoom-mullet-begone' own frames keep the virtual camera "in use", so the
service cannot see a meeting app leave. When nobody has been in view for a
minute, it stops sending for a moment and checks again (RunControl.probe);
with nobody in view, the brief OBS placeholder the meeting sees is harmless.
If no app reads the camera any more, it goes back to waiting.

Browser tabs are exact: the run ends a few seconds after the last tab stops
reading. Where the watcher is not supported (not macOS) but a virtual camera
works, the service runs the pipeline all the time to feed it.

Each run happens in a child process (worker.run_in_child), so the models'
memory goes back to the OS when it ends.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import numpy as np

from zoom_mullet_begone.config import Config
from zoom_mullet_begone.io.camwatch import CameraWatcher
from zoom_mullet_begone.pipeline import RunControl
from zoom_mullet_begone.ui.settings import GarmentChoice, SettingsHub, SettingsServer
from zoom_mullet_begone.worker import PREVIEW_EVERY_S, preview_jpeg, run_in_child

POLL_S = 0.5
PROBE_SETTLE_S = 0.15  # after closing our output, before reading the in-use flag
RETRY_AFTER_ERROR_S = 5.0
BROWSER_GRACE_S = 3.0  # keep running this long after the last browser tab leaves (reloads, device switches)

STATUS_TEXT = {
    "waiting": "待命中：會議打開 Zoom Mullet Begone 鏡頭時會自動開始",
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
        runner: Callable[..., int] = run_in_child,
        vcam_check: Callable[[], bool] | None = None,
    ):
        # The service owns the output: no preview window, frames to the virtual camera.
        self.config = replace(config, preview=False, vcam=True)
        self.watcher = watcher or CameraWatcher()
        self._runner = runner
        self._vcam_check = vcam_check or self._vcam_works
        self.hub = SettingsHub(
            Path(config.garments_dir),
            GarmentChoice(config.garment, config.garment_color, config.garment_auto),
            settings_path,
        )
        self.server: SettingsServer | None = None
        self.vcam_available = False
        self.state = "waiting"
        self.auto_start = True
        self.sessions = 0
        self.on_change: Callable[[], None] | None = None  # e.g. refresh the menu bar
        self._quit = threading.Event()
        self._control: RunControl | None = None
        self._last_preview = 0.0
        self._thread = threading.Thread(target=self._loop, name="zoom-mullet-begone-service", daemon=True)

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> BackgroundService:
        if self.config.settings_port:
            try:
                self.server = SettingsServer(self.hub, self.config.settings_port).start()
                print(f"settings page: {self.server.url}")
            except OSError as e:
                print(f"settings page off: port {self.config.settings_port} unavailable ({e})", file=sys.stderr)
        self.vcam_available = self._vcam_check()
        self.config = replace(self.config, vcam=self.vcam_available)
        if not self.vcam_available:
            print("no virtual camera (OBS not installed?): serving the browser extension only")
        elif self.watcher.in_use() is None:
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

    def _vcam_works(self) -> bool:
        from zoom_mullet_begone.io.virtualcam import VirtualCam, VirtualCamError

        width, height = self.config.resolution
        try:
            VirtualCam(width, height, self.config.fps).close()
            return True
        except VirtualCamError:
            return False

    def _browser_watching(self) -> bool:
        feed = self.hub.feed
        return feed.clients > 0 or time.monotonic() - feed.idle_since < BROWSER_GRACE_S

    def _browser_only_watching(self) -> bool:
        """For a browser-only run: tabs still watch, and no app opened the virtual camera."""
        return self._browser_watching() and not (self.vcam_available and self.watcher.in_use())

    def _meeting_wants_camera(self) -> bool:
        if self.hub.feed.clients > 0:
            return True
        if not self.vcam_available:
            return False
        used = self.watcher.in_use()
        return True if used is None else used  # unknown: always on to feed the virtual camera

    def _loop(self) -> None:
        while not self._quit.is_set():
            if not self.auto_start or not self._meeting_wants_camera():
                self._quit.wait(POLL_S)
                continue
            self._session()

    def _session(self) -> None:
        self._set_state("starting")
        used = self.watcher.in_use()
        # Feed the virtual camera only when an app reads it (or where that cannot
        # be told). A run started by browser tabs alone leaves it closed, so its
        # in-use flag keeps showing real readers: the run then ends exactly when
        # the tabs are gone, and restarts with the virtual camera if an app opens it.
        feed_vcam = self.vcam_available and (used is None or used)
        if feed_vcam:
            control = RunControl(
                hub=self.hub, on_frame=self._on_frame, probe=self._probe if used is not None else None
            )
        else:
            control = RunControl(hub=self.hub, on_frame=self._on_frame, keep_running=self._browser_only_watching)
        self._control = control
        self.sessions += 1
        try:
            self._set_state("active")
            status = self._runner(replace(self.config, vcam=feed_vcam), control=control)
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
        watched = bool(self.watcher.in_use()) or self.hub.feed.clients > 0
        return watched and self.auto_start and not self._quit.is_set()

    def _on_frame(self, frame: np.ndarray) -> None:
        self.hub.feed.publish(frame)
        self._preview(frame)

    def _preview(self, frame: np.ndarray) -> None:
        now = time.perf_counter()
        if now - self._last_preview < PREVIEW_EVERY_S:
            return
        self._last_preview = now
        jpeg = preview_jpeg(frame)
        if jpeg is not None:
            self.hub.set_preview(jpeg)
