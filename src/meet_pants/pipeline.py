"""Main loop: capture -> pose -> (render, from M1) -> virtual camera + preview.

M0 passes frames through unchanged; the skeleton is only drawn on the preview.
"""

from __future__ import annotations

import sys
import time
from contextlib import ExitStack

from meet_pants.config import Config, DebugConfig
from meet_pants.io.capture import CaptureError, open_source
from meet_pants.io.preview import KEY_ESC, PreviewWindow, Stats, render_preview
from meet_pants.io.virtualcam import VirtualCam, VirtualCamError
from meet_pants.perception.pose import PoseDetector

# D cycles the preview overlays through these presets.
DEBUG_PRESETS = (
    DebugConfig(landmarks=True, masks=False, hud=True),
    DebugConfig(landmarks=True, masks=True, hud=True),
    DebugConfig(landmarks=False, masks=False, hud=False),
)


def _next_debug(current: DebugConfig) -> DebugConfig:
    try:
        i = DEBUG_PRESETS.index(current)
    except ValueError:
        return DEBUG_PRESETS[0]
    return DEBUG_PRESETS[(i + 1) % len(DEBUG_PRESETS)]


def run(config: Config, max_frames: int | None = None) -> int:
    with ExitStack() as stack:
        try:
            source = stack.enter_context(open_source(config.input, config.resolution, config.fps))
        except CaptureError as e:
            print(f"capture error: {e}", file=sys.stderr)
            return 1
        width, height = source.size
        print(f"input  {config.input}  {width}x{height} @ {source.fps:.0f} fps")

        detector = stack.enter_context(PoseDetector(config.pose_model_path, config.pose))

        vcam = None
        if config.vcam:
            try:
                vcam = stack.enter_context(VirtualCam(width, height, source.fps))
            except VirtualCamError as e:
                print(f"virtual camera error: {e}", file=sys.stderr)
                return 1
            print(f"output virtual camera: {vcam.device}")

        preview = None
        if config.preview:
            preview = PreviewWindow()
            stack.callback(preview.close)
            print("preview: Esc/Q quit, D cycle debug overlays")

        debug = config.debug
        stats = Stats()
        frames = detected = 0
        total_inference_ms = 0.0
        # Video files are paced to real time only when someone is watching.
        pace = not source.is_live and (vcam is not None or preview is not None)
        frame_interval = 1.0 / source.fps
        start = last = time.perf_counter()

        try:
            while max_frames is None or frames < max_frames:
                frame = source.read()
                if frame is None:
                    if source.is_live:
                        print("camera stopped delivering frames", file=sys.stderr)
                        return 1
                    break

                pose = detector.detect(frame.image, frame.t_ms)
                output = frame.image  # M0: passthrough

                if vcam is not None:
                    vcam.send(output)

                now = time.perf_counter()
                stats.update((now - last) * 1000, pose.inference_ms)
                last = now
                frames += 1
                detected += pose.detected
                total_inference_ms += pose.inference_ms

                if preview is not None:
                    key = preview.show(
                        render_preview(frame.image, pose, debug, stats, config.preview_mirror)
                    )
                    if key in (KEY_ESC, ord("q")) or preview.closed():
                        break
                    if key == ord("d"):
                        debug = _next_debug(debug)

                if pace:
                    delay = frame_interval - (time.perf_counter() - now)
                    if delay > 0:
                        time.sleep(delay)
        except KeyboardInterrupt:
            pass

        elapsed = time.perf_counter() - start
        if frames:
            print(
                f"done   {frames} frames in {elapsed:.1f} s ({frames / elapsed:.1f} fps), "
                f"pose avg {total_inference_ms / frames:.1f} ms, "
                f"person detected in {100 * detected / frames:.0f}% of frames"
            )
    return 0

