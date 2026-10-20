"""Background service: start when a meeting opens the camera, stop when it is gone."""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from meet_pants.config import Config
from meet_pants.pipeline import RunControl
from meet_pants.service import BackgroundService


class FakeWatcher:
    supported = True

    def __init__(self) -> None:
        self.meeting = False  # a meeting app reads the virtual camera
        self.sending = False  # our own output is open (also counts as "in use")

    def in_use(self) -> bool:
        return self.meeting or self.sending


class FakeRunner:
    """Stands in for pipeline.run: sends frames until stopped; probes when asked."""

    def __init__(self, watcher: FakeWatcher):
        self.watcher = watcher
        self.runs = 0
        self.probe_now = threading.Event()
        self.probe_results: list[bool] = []

    def __call__(self, config: Config, control: RunControl) -> int:
        self.runs += 1
        self.watcher.sending = True
        try:
            while not control.stop.is_set():
                control.on_frame(np.zeros((90, 160, 3), np.uint8))
                if self.probe_now.is_set() and control.probe is not None:
                    self.probe_now.clear()
                    self.watcher.sending = False  # the pipeline closes its output to probe
                    keep = control.probe()
                    self.probe_results.append(keep)
                    if not keep:
                        return 0
                    self.watcher.sending = True
                time.sleep(0.01)
            return 0
        finally:
            self.watcher.sending = False


def wait_for(condition, timeout: float = 3.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False


def make_service(tmp_path: Path) -> tuple[BackgroundService, FakeWatcher, FakeRunner]:
    watcher = FakeWatcher()
    runner = FakeRunner(watcher)
    config = replace(Config(), settings_port=0)
    service = BackgroundService(config, tmp_path / "config.yaml", watcher=watcher, runner=runner)  # type: ignore[arg-type]
    return service, watcher, runner


def test_waits_until_a_meeting_opens_the_camera(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("meet_pants.service.POLL_S", 0.02)
    service, watcher, runner = make_service(tmp_path)
    service.start()
    try:
        time.sleep(0.2)
        assert runner.runs == 0 and service.state == "waiting"
        watcher.meeting = True
        assert wait_for(lambda: service.state == "active")
        assert wait_for(lambda: service.hub.preview() is not None)  # live preview for the page
    finally:
        service.quit()


def test_probe_ends_the_run_when_the_meeting_left(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("meet_pants.service.POLL_S", 0.02)
    monkeypatch.setattr("meet_pants.service.PROBE_SETTLE_S", 0.0)
    service, watcher, runner = make_service(tmp_path)
    watcher.meeting = True
    service.start()
    try:
        assert wait_for(lambda: service.state == "active")
        runner.probe_now.set()  # meeting still there: keep going
        assert wait_for(lambda: runner.probe_results == [True])
        assert service.state == "active"

        watcher.meeting = False
        runner.probe_now.set()  # meeting gone: back to waiting, camera off
        assert wait_for(lambda: runner.probe_results == [True, False])
        assert wait_for(lambda: service.state == "waiting")
        assert service.hub.preview() is None
        time.sleep(0.2)
        assert runner.runs == 1  # does not restart on its own output
    finally:
        service.quit()


def test_turning_off_auto_start_stops_and_waits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("meet_pants.service.POLL_S", 0.02)
    service, watcher, runner = make_service(tmp_path)
    watcher.meeting = True
    service.start()
    try:
        assert wait_for(lambda: service.state == "active")
        service.set_auto_start(False)
        assert wait_for(lambda: service.state == "paused")
        time.sleep(0.2)
        assert runner.runs == 1
        service.set_auto_start(True)
        assert wait_for(lambda: runner.runs == 2)
    finally:
        service.quit()
