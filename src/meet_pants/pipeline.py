"""Main loop: capture -> pose -> smoothing -> leg geometry -> pants mesh -> output.

The virtual camera gets the composited frame; the preview shows the same frame
plus debug overlays.
"""

from __future__ import annotations

import sys
import time
from contextlib import ExitStack
from pathlib import Path

import cv2
import numpy as np

from meet_pants.analysis.leg_geometry import LegGeometry, LegTracker
from meet_pants.analysis.outfit import OutfitMatcher, sample_top_color, texture_color
from meet_pants.config import MODES, Config, DebugConfig
from meet_pants.io.capture import CaptureError, open_source
from meet_pants.io.preview import KEY_ESC, PreviewWindow, Stats, render_preview
from meet_pants.io.virtualcam import VirtualCam, VirtualCamError
from meet_pants.perception.chain import PoseChain
from meet_pants.perception.segmenter import BodySegmenter, Segmentation
from meet_pants.perception.types import PoseFrame
from meet_pants.render.compositor import Compositor, SceneMasks
from meet_pants.render.garment import Garment, GarmentError, list_garments, load_garment
from meet_pants.render.mesh import Mesh, build_mesh
from meet_pants.render.trim import draw_trim
from meet_pants.render.warp_cv import render_mesh
from meet_pants.tracking.one_euro import LandmarkSmoother

FADE_IN_MS = 120
TOP_SAMPLE_EVERY = 5  # frames between shirt color samples

# D cycles the preview overlays through these presets.
DEBUG_PRESETS = (
    DebugConfig(landmarks=True, masks=False, mesh=False, hud=True),
    DebugConfig(landmarks=True, masks=True, mesh=False, hud=True),
    DebugConfig(landmarks=False, masks=False, mesh=True, hud=True),
    DebugConfig(landmarks=False, masks=False, mesh=False, hud=False),
)


def _next_debug(current: DebugConfig) -> DebugConfig:
    try:
        i = DEBUG_PRESETS.index(current)
    except ValueError:
        return DEBUG_PRESETS[0]
    return DEBUG_PRESETS[(i + 1) % len(DEBUG_PRESETS)]


class Wardrobe:
    """Available garments, loaded on first use, with a current selection."""

    def __init__(self, root: Path, initial: str):
        self._root = root
        self.ids = list_garments(root)
        if initial not in self.ids:
            available = ", ".join(self.ids) or "none"
            raise GarmentError(f"garment '{initial}' not found in {root} (available: {available})")
        self._index = self.ids.index(initial)
        self._cache: dict[str, Garment] = {}

    @property
    def current(self) -> Garment:
        gid = self.ids[self._index]
        if gid not in self._cache:
            self._cache[gid] = load_garment(self._root, gid)
        return self._cache[gid]

    def next(self) -> Garment:
        self._index = (self._index + 1) % len(self.ids)
        return self.current

    def select(self, garment_id: str) -> Garment:
        self._index = self.ids.index(garment_id)
        return self.current

    def colors(self) -> dict[str, np.ndarray]:
        """Median Lab color of every garment (loads them all)."""
        colors = {}
        for gid in self.ids:
            if gid not in self._cache:
                self._cache[gid] = load_garment(self._root, gid)
            colors[gid] = texture_color(self._cache[gid].texture)
        return colors


def scene_masks(pose: PoseFrame, segmentation: Segmentation | None, geometry: LegGeometry) -> SceneMasks:
    return SceneMasks(
        skin=segmentation.skin if segmentation is not None else None,
        body=pose.person_mask >= 0.5 if pose.person_mask is not None else None,
        occluder=geometry.arms,
    )


def dress(
    frame: np.ndarray,
    geometry: LegGeometry | None,
    garment: Garment,
    compositor: Compositor,
    masks: SceneMasks | None = None,
    opacity: float = 1.0,
) -> tuple[np.ndarray, Mesh | None]:
    """Draw the garment on a copy of the frame; returns the frame unchanged if nothing is visible."""
    if geometry is None:
        return frame, None
    mesh = build_mesh(geometry, garment)
    layer = render_mesh(mesh, garment.pyramid, frame.shape)
    if layer is None:
        return frame, mesh
    draw_trim(layer, mesh, garment.trim, geometry.scale)
    return compositor.composite(frame, layer, masks or SceneMasks(), geometry.scale, opacity), mesh


def run(config: Config, max_frames: int | None = None, record: Path | None = None) -> int:
    try:
        wardrobe = Wardrobe(Path(config.garments_dir), config.garment)
        wardrobe.current  # fail on a broken garment before opening devices
        matcher = OutfitMatcher(wardrobe.colors(), config.garment) if config.garment_auto else None
    except (GarmentError, ValueError) as e:
        print(f"garment error: {e}", file=sys.stderr)
        return 1

    with ExitStack() as stack:
        try:
            source = stack.enter_context(open_source(config.input, config.resolution, config.fps))
        except CaptureError as e:
            print(f"capture error: {e}", file=sys.stderr)
            return 1
        width, height = source.size
        print(f"input  {config.input}  {width}x{height} @ {source.fps:.0f} fps")

        detector = stack.enter_context(PoseChain.create(config.pose_model_path, config.models_path, config.pose))
        segmenter = stack.enter_context(BodySegmenter(config.segmenter_model_path))
        smoother = LandmarkSmoother(config.smoothing)
        legs = LegTracker()
        compositor = Compositor()
        appeared_ms: int | None = None

        vcam = None
        if config.vcam:
            try:
                vcam = stack.enter_context(VirtualCam(width, height, source.fps))
            except VirtualCamError as e:
                print(f"virtual camera error: {e}", file=sys.stderr)
                return 1
            print(f"output virtual camera: {vcam.device}")

        recorder = None
        if record is not None:
            record.parent.mkdir(parents=True, exist_ok=True)
            recorder = cv2.VideoWriter(str(record), cv2.VideoWriter_fourcc(*"mp4v"), source.fps, (width, height))
            if not recorder.isOpened():
                print(f"cannot write recording: {record}", file=sys.stderr)
                return 1
            stack.callback(recorder.release)
            print(f"record raw input -> {record}")

        preview = None
        if config.preview:
            preview = PreviewWindow()
            stack.callback(preview.close)
            print("preview: Esc/Q quit, M mode, P next garment, A auto garment, D cycle debug overlays")

        mode = config.mode
        debug = config.debug
        stats = Stats()
        auto = matcher is not None
        frames = detected = dressed = 0
        sources: dict[str, int] = {}
        total_inference_ms = total_render_ms = 0.0
        # Video files are paced to real time only when someone is watching.
        pace = not source.is_live and (vcam is not None or preview is not None)
        frame_interval = 1.0 / source.fps
        start = last = deadline = time.perf_counter()

        try:
            while max_frames is None or frames < max_frames:
                frame = source.read()
                if frame is None:
                    if source.is_live:
                        print("camera stopped delivering frames", file=sys.stderr)
                        return 1
                    break

                if recorder is not None:
                    recorder.write(frame.image)
                segmenter.submit(frame.image, frame.t_ms)  # runs while the pose model works
                pose = smoother(detector.detect(frame.image, frame.t_ms), width, height)
                segmentation = segmenter.latest()
                geometry = legs.update(pose, width, height, segmentation)
                if auto and matcher is not None and frames % TOP_SAMPLE_EVERY == 0:
                    switched = matcher.update(sample_top_color(frame.image, pose, segmentation), frame.t_ms)
                    if switched is not None:
                        wardrobe.select(switched)
                        print(f"garment {switched} (matches the shirt)")

                render_start = time.perf_counter()
                output, mesh = frame.image, None
                if mode == "always" and geometry is not None:
                    if appeared_ms is None:
                        appeared_ms = frame.t_ms
                    opacity = min(1.0, (frame.t_ms - appeared_ms) / FADE_IN_MS)
                    masks = scene_masks(pose, segmentation, geometry)
                    output, mesh = dress(frame.image, geometry, wardrobe.current, compositor, masks, opacity)
                else:
                    appeared_ms = None
                render_ms = (time.perf_counter() - render_start) * 1000

                if vcam is not None:
                    vcam.send(output)

                now = time.perf_counter()
                stats.update((now - last) * 1000, pose.inference_ms, render_ms)
                last = now
                frames += 1
                detected += pose.detected
                if pose.detected:
                    sources[pose.source] = sources.get(pose.source, 0) + 1
                dressed += output is not frame.image
                total_inference_ms += pose.inference_ms
                total_render_ms += render_ms

                if preview is not None:
                    status = [
                        f"mode {mode}  garment {wardrobe.current.id}{' (auto)' if auto else ''}  pose {pose.source}"
                    ]
                    key = preview.show(
                        render_preview(
                            output, pose, debug, stats, config.preview_mirror, status, mesh, segmentation
                        )
                    )
                    if key in (KEY_ESC, ord("q")) or preview.closed():
                        break
                    if key == ord("d"):
                        debug = _next_debug(debug)
                    elif key == ord("m"):
                        mode = MODES[(MODES.index(mode) + 1) % len(MODES)]
                    elif key == ord("p"):
                        wardrobe.next()
                        auto = False  # a hand-picked garment stays
                    elif key == ord("a"):
                        if matcher is None:
                            matcher = OutfitMatcher(wardrobe.colors(), wardrobe.current.id)
                        auto = not auto
                        matcher.follow(wardrobe.current.id)

                if pace:
                    # Fixed schedule, so processing time is absorbed instead of added.
                    deadline += frame_interval
                    delay = deadline - time.perf_counter()
                    if delay > 0:
                        time.sleep(delay)
                    else:
                        deadline = time.perf_counter()  # running behind: don't burst to catch up
        except KeyboardInterrupt:
            pass

        elapsed = time.perf_counter() - start
        if frames:
            print(
                f"done   {frames} frames in {elapsed:.1f} s ({frames / elapsed:.1f} fps), "
                f"pose avg {total_inference_ms / frames:.1f} ms, "
                f"render avg {total_render_ms / frames:.1f} ms, "
                f"person detected in {100 * detected / frames:.0f}% of frames, "
                f"pants drawn in {100 * dressed / frames:.0f}%"
            )
            if detected:
                share = ", ".join(f"{src} {100 * n / detected:.0f}%" for src, n in sorted(sources.items()))
                print(f"pose   {share}")
    return 0
