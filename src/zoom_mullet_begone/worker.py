"""Run one background-mode session of the pipeline in a child process.

The pose and segmentation models, onnxruntime and the frame buffers take about
half a gigabyte, and a process does not give that memory back to the OS after
a run in a thread ends. A child process does: when it exits, the service is
back to its idle size.

The service (parent) keeps the settings page, the browser stream, the camera
watcher and the menu bar. One pipe connects the two:

    parent -> child   ("stop",)                    end the run
                      ("feed", bool)               a browser tab reads the stream
                      ("choice", choice, version)  changed on the settings page
                      ("probe", bool)              answer to a probe request
    child -> parent   ("feed", jpeg)               a frame for the browser stream
                      ("preview", jpeg)            small frame for the settings page
                      ("choice", choice, version)  shirt matching picked a garment
                      ("probe",)                   virtual camera closed: still watched?
                      ("done", status)             run() returned

Frames cross only as JPEG, and only while somebody looks at them: every frame
while a browser tab reads the stream, a small one three times a second for the
page's live preview.
"""

from __future__ import annotations

import multiprocessing as mp
import sys
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path

import cv2
import numpy as np

from zoom_mullet_begone.config import Config
from zoom_mullet_begone.pipeline import RunControl, run
from zoom_mullet_begone.ui.browser_feed import JPEG_QUALITY
from zoom_mullet_begone.ui.settings import GarmentChoice, SettingsHub

PREVIEW_EVERY_S = 0.3
PREVIEW_WIDTH = 480
POLL_S = 0.05
STOP_TIMEOUT_S = 5.0


def preview_jpeg(frame: np.ndarray) -> bytes | None:
    """A small JPEG of the frame for the settings page's live preview."""
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (PREVIEW_WIDTH, round(h * PREVIEW_WIDTH / w)), interpolation=cv2.INTER_AREA)
    ok, jpeg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return jpeg.tobytes() if ok else None


def run_in_child(config: Config, control: RunControl, target: Callable[..., int] = run) -> int:
    """Like run(config, control=control), but in a child process. `control.hub` is required;
    `control.on_frame` is not called (frames go to the hub's feed and preview).
    `target` must be importable by name (it is pickled for the child)."""
    hub = control.hub
    assert hub is not None
    ctx = mp.get_context("spawn")  # a fresh interpreter: nothing of the parent's state, safe beside Cocoa
    conn, child_conn = ctx.Pipe()
    sent_version = hub.version
    process = ctx.Process(
        target=_child_main,
        args=(target, config, child_conn, hub.choice, sent_version, control.probe is not None, control.probe_after_s),
        name="zoom-mullet-begone-pipeline",
        daemon=True,
    )
    process.start()
    child_conn.close()

    status = 1  # the child died without reporting
    stopping = False
    feeding: bool | None = None
    try:
        while True:
            if not stopping and (
                control.stop.is_set() or (control.keep_running is not None and not control.keep_running())
            ):
                stopping = True
                _send(conn, ("stop",))
            wants = hub.feed.clients > 0
            if wants != feeding:
                feeding = wants
                _send(conn, ("feed", wants))
            if hub.version != sent_version:
                sent_version = hub.version
                _send(conn, ("choice", hub.choice, sent_version))

            if not conn.poll(POLL_S):
                if not process.is_alive() and not conn.poll():
                    break
                continue
            try:
                msg = conn.recv()
            except (EOFError, OSError):
                break
            kind = msg[0]
            if kind == "feed":
                hub.feed.publish_jpeg(msg[1])
            elif kind == "preview":
                hub.set_preview(msg[1])
            elif kind == "choice":
                # Shirt matching in the child; a newer choice from the page wins.
                if msg[2] == sent_version:
                    hub.set(msg[1], save=False)
                    sent_version = hub.version
            elif kind == "probe":
                keep = control.probe is not None and control.probe()
                _send(conn, ("probe", keep))
            elif kind == "done":
                status = msg[1]
    finally:
        process.join(STOP_TIMEOUT_S)
        if process.is_alive():
            print("pipeline process did not stop; killing it", file=sys.stderr)
            process.kill()
            process.join()
        conn.close()
    if process.exitcode != 0:
        print(f"pipeline process exited with {process.exitcode}", file=sys.stderr)
        return 1
    return status


def _send(conn: Connection, msg: tuple) -> None:
    try:
        conn.send(msg)
    except (BrokenPipeError, OSError):
        pass  # the child is gone; the loop notices


class _ParentLink:
    """The child's end: a RunControl backed by the pipe."""

    def __init__(self, conn: Connection, hub: SettingsHub, version: int):
        self.conn = conn
        self.hub = hub
        self.parent_version = version  # the parent's hub version our choice came from
        self.seen_version = hub.version  # our hub's version as last synced
        self.stopped = False
        self.feed = False
        self.last_preview = 0.0

    def _handle(self, msg: tuple) -> bool | None:
        kind = msg[0]
        if kind == "stop":
            self.stopped = True
        elif kind == "feed":
            self.feed = msg[1]
        elif kind == "choice":
            self.parent_version = msg[2]
            self.hub.set(msg[1], save=False)
            self.seen_version = self.hub.version
        elif kind == "probe":
            return msg[1]
        return None

    def _drain(self) -> None:
        while self.conn.poll():
            self._handle(self.conn.recv())

    def keep_running(self) -> bool:
        # Called every frame. First report a garment the pipeline picked itself.
        if self.hub.version != self.seen_version:
            self.seen_version = self.hub.version
            self.conn.send(("choice", self.hub.choice, self.parent_version))
        self._drain()
        return not self.stopped

    def probe(self) -> bool:
        self.conn.send(("probe",))
        while True:
            answer = self._handle(self.conn.recv())
            if self.stopped:
                return False
            if answer is not None:
                return answer

    def on_frame(self, frame: np.ndarray) -> None:
        if self.feed:
            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if ok:
                self.conn.send(("feed", jpeg.tobytes()))
        now = time.perf_counter()
        if now - self.last_preview >= PREVIEW_EVERY_S:
            self.last_preview = now
            jpeg = preview_jpeg(frame)
            if jpeg is not None:
                self.conn.send(("preview", jpeg))


def _child_main(
    target: Callable[..., int],
    config: Config,
    conn: Connection,
    choice: GarmentChoice,
    version: int,
    probe: bool,
    probe_after_s: float,
) -> None:
    status = 1
    try:
        hub = SettingsHub(Path(config.garments_dir), choice, None)  # the parent saves the page's changes
        link = _ParentLink(conn, hub, version)
        control = RunControl(
            hub=hub,
            on_frame=link.on_frame,
            probe=link.probe if probe else None,
            probe_after_s=probe_after_s,
            keep_running=link.keep_running,
        )
        status = target(config, control=control)
    except (KeyboardInterrupt, EOFError, BrokenPipeError):
        status = 0  # Ctrl+C in the terminal, or the parent went away
    finally:
        try:
            conn.send(("done", status))
        except (BrokenPipeError, OSError):
            pass
        conn.close()
