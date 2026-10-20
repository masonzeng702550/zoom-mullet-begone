"""Background service: start when a meeting opens the camera, stop when it is gone."""

from __future__ import annotations

import functools
import os
import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from meet_pants.config import Config
from meet_pants.pipeline import RunControl
from meet_pants.service import BackgroundService
from meet_pants.worker import run_in_child


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
        self.watcher.sending = config.vcam  # only a run that feeds the virtual camera marks it in use
        try:
            while not control.stop.is_set() and (control.keep_running is None or control.keep_running()):
                control.on_frame(np.zeros((90, 160, 3), np.uint8))
                if self.probe_now.is_set() and control.probe is not None:
                    self.probe_now.clear()
                    self.watcher.sending = False  # the pipeline closes its output to probe
                    keep = control.probe()
                    self.probe_results.append(keep)
                    if not keep:
                        return 0
                    self.watcher.sending = config.vcam
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


def make_service(tmp_path: Path, vcam: bool = True) -> tuple[BackgroundService, FakeWatcher, FakeRunner]:
    watcher = FakeWatcher()
    runner = FakeRunner(watcher)
    config = replace(Config(), settings_port=0)
    service = BackgroundService(
        config, tmp_path / "config.yaml", watcher=watcher, runner=runner, vcam_check=lambda: vcam  # type: ignore[arg-type]
    )
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


def test_browser_tab_starts_and_stops_without_a_virtual_camera(tmp_path: Path, monkeypatch) -> None:
    """No OBS: only the browser extension's stream counts, and the run ends after it leaves."""
    monkeypatch.setattr("meet_pants.service.POLL_S", 0.02)
    monkeypatch.setattr("meet_pants.service.BROWSER_GRACE_S", 0.1)
    service, watcher, runner = make_service(tmp_path, vcam=False)
    watcher.meeting = True  # ignored: there is no virtual camera to feed
    service.start()
    try:
        time.sleep(0.2)
        assert runner.runs == 0 and service.config.vcam is False
        service.hub.feed.connect()  # a tab opened the meet-pants camera
        assert wait_for(lambda: service.state == "active")
        service.hub.feed.disconnect()
        assert wait_for(lambda: service.state == "waiting")
        assert runner.runs == 1
    finally:
        service.quit()


def test_browser_run_leaves_the_virtual_camera_alone_and_ends_with_the_tab(tmp_path: Path, monkeypatch) -> None:
    """OBS installed but unused: a tab-started run must not open the virtual camera, so it can
    stop as soon as the tab leaves; an app opening the virtual camera restarts it with output."""
    monkeypatch.setattr("meet_pants.service.POLL_S", 0.02)
    monkeypatch.setattr("meet_pants.service.BROWSER_GRACE_S", 0.1)
    configs = []
    service, watcher, runner = make_service(tmp_path, vcam=True)
    real_runner = runner

    def recording_runner(config, control):
        configs.append(config.vcam)
        return real_runner(config, control)

    service._runner = recording_runner
    service.start()
    try:
        service.hub.feed.connect()
        assert wait_for(lambda: service.state == "active")
        assert configs == [False]  # tab only: no virtual camera output
        service.hub.feed.disconnect()
        assert wait_for(lambda: service.state == "waiting")

        service.hub.feed.connect()
        assert wait_for(lambda: len(configs) == 2)
        watcher.meeting = True  # Zoom opens OBS Virtual Camera meanwhile
        assert wait_for(lambda: configs[-1] is True)  # restarted feeding it
        service.hub.feed.disconnect()
    finally:
        service.quit()


PROBE_COLOR = "#000001"  # the page picks this: the child runner probes once


def child_runner(config: Config, control: RunControl) -> int:
    """Stands in for pipeline.run in the child process. Like shirt matching, it picks a
    color itself when the page sets none: its pid, so the test can find it."""
    probed = False
    while control.keep_running():
        choice = control.hub.choice
        if not choice.color:
            control.hub.set(replace(choice, color=f"#{os.getpid():06x}"), save=False)
        if choice.color == PROBE_COLOR and not probed and control.probe is not None:
            probed = True
            if not control.probe():
                return 0
        control.on_frame(np.zeros((90, 160, 3), np.uint8))
        time.sleep(0.01)
    return 0


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_runs_in_a_child_process_that_exits_with_the_run(tmp_path: Path, monkeypatch) -> None:
    """The default runner: frames, settings and probes cross the process boundary, and the
    child (with the models' memory) is gone once the run ends."""
    monkeypatch.setattr("meet_pants.service.POLL_S", 0.02)
    monkeypatch.setattr("meet_pants.service.PROBE_SETTLE_S", 0.0)
    service, watcher, _ = make_service(tmp_path)
    service._runner = functools.partial(run_in_child, target=child_runner)
    service.hub.set(replace(service.hub.choice, color=""), save=False)
    watcher.meeting = True
    service.start()
    try:
        assert wait_for(lambda: service.hub.preview() is not None, timeout=20)  # the live preview crossed
        assert wait_for(lambda: service.hub.choice.color != "")  # the child's own pick reached the page
        pid = int(service.hub.choice.color[1:], 16)
        assert pid != os.getpid() and alive(pid)

        service.hub.feed.connect()  # a browser tab: full frames cross too
        try:
            assert service.hub.feed.next_frame(0, timeout=3) is not None
        finally:
            service.hub.feed.disconnect()

        watcher.meeting = False
        service.hub.update({"color": PROBE_COLOR})  # page -> child, which probes; nobody watches
        assert wait_for(lambda: service.state == "waiting")
        assert wait_for(lambda: not alive(pid))
        assert service.sessions == 1
    finally:
        service.quit()
