"""Main loop: capture -> pose -> smoothing -> leg geometry -> pants mesh -> output.

The virtual camera gets the composited frame; the preview shows the same frame
plus debug overlays.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from pathlib import Path

import cv2
import numpy as np

from zoom_mullet_begone.analysis.leg_geometry import LegGeometry, LegTracker
from zoom_mullet_begone.analysis.outfit import OutfitMatcher, sample_top_color, texture_color
from zoom_mullet_begone.config import MODES, Config, DebugConfig
from zoom_mullet_begone.io.capture import CaptureError, open_source
from zoom_mullet_begone.io.preview import KEY_ESC, PreviewWindow, Stats, render_preview
from zoom_mullet_begone.io.virtualcam import VirtualCam, VirtualCamError
from zoom_mullet_begone.perception.chain import PoseChain
from zoom_mullet_begone.perception.segmenter import BodySegmenter, Segmentation
from zoom_mullet_begone.perception.types import PoseFrame
from zoom_mullet_begone.render.compositor import Compositor, SceneMasks
from zoom_mullet_begone.render.garment import Garment, GarmentError, list_garments, load_garment, parse_color, with_color
from zoom_mullet_begone.render.mesh import Mesh, build_mesh
from zoom_mullet_begone.render.trim import draw_trim
from zoom_mullet_begone.render.warp_cv import render_mesh
from zoom_mullet_begone.tracking.one_euro import LandmarkSmoother
from zoom_mullet_begone.ui.settings import GarmentChoice, SettingsHub, SettingsServer, effective

FADE_IN_MS = 120
TOP_SAMPLE_EVERY = 5  # frames between shirt color samples
# A skin/clothes segmentation older than this is not used (the segmenter only
# runs while legs are in view or a shirt sample is due).
SEGMENTATION_MAX_AGE_MS = 200

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


@dataclass
class RunControl:
    """Hooks for running the pipeline under the background service."""

    stop: threading.Event = field(default_factory=threading.Event)
    # Shared settings; the service runs the settings page itself.
    hub: SettingsHub | None = None
    # Called with every output frame (the service makes the live preview from it).
    on_frame: Callable[[np.ndarray], None] | None = None
    # Called with the virtual camera closed after nobody has been in view for
    # `probe_after_s` (repeated at that interval): True keeps running, False ends
    # the run. Closing the output is how the service tells whether a meeting
    # app still reads the camera; with nobody in view, the brief gap is harmless.
    probe: Callable[[], bool] | None = None
    probe_after_s: float = 60.0
    # Checked every frame: False ends the run (e.g. the last browser tab closed
    # its camera and there is no virtual camera to feed).
    keep_running: Callable[[], bool] | None = None


class Wardrobe:
    """Available garments, loaded on first use, with a current selection and color."""

    def __init__(self, root: Path, initial: str, color: str = ""):
        self._root = root
        self.ids = list_garments(root)
        if initial not in self.ids:
            available = ", ".join(self.ids) or "none"
            raise GarmentError(f"garment '{initial}' not found in {root} (available: {available})")
        self._index = self.ids.index(initial)
        self._cache: dict[str, Garment] = {}
        self._recolored: tuple[tuple[str, str], Garment] | None = None
        self.color = ""
        self.set_color(color)

    def _base(self, gid: str) -> Garment:
        if gid not in self._cache:
            self._cache[gid] = load_garment(self._root, gid)
        return self._cache[gid]

    @property
    def current(self) -> Garment:
        gid = self.ids[self._index]
        if not self.color:
            return self._base(gid)
        key = (gid, self.color)
        if self._recolored is None or self._recolored[0] != key:
            self._recolored = (key, with_color(self._base(gid), self.color))
        return self._recolored[1]

    def set_color(self, color: str) -> None:
        """'#rrggbb', or '' for each garment's own color."""
        if color:
            parse_color(color)  # raises GarmentError on a bad value
        self.color = color

    def next(self) -> Garment:
        self._index = (self._index + 1) % len(self.ids)
        return self.current

    def select(self, garment_id: str) -> Garment:
        self._index = self.ids.index(garment_id)
        return self.current

    def colors(self) -> dict[str, np.ndarray]:
        """Median Lab color of every garment (loads them all)."""
        return {gid: texture_color(self._base(gid).texture) for gid in self.ids}


def apply_choice(
    choice: GarmentChoice, wardrobe: Wardrobe, matcher: OutfitMatcher | None
) -> tuple[bool, OutfitMatcher | None]:
    """Put on the garment chosen on the settings page; returns (auto, matcher)."""
    wardrobe.select(choice.garment)
    wardrobe.set_color(effective(choice).color)
    if choice.auto and matcher is None:
        matcher = OutfitMatcher(wardrobe.colors(), wardrobe.current.id)
    if matcher is not None:
        matcher.follow(wardrobe.current.id)
    return choice.auto, matcher


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


def run(
    config: Config,
    max_frames: int | None = None,
    record: Path | None = None,
    settings_path: Path | None = None,
    control: RunControl | None = None,
) -> int:
    """`settings_path`: config file the settings page saves to (None: changes are not saved).
    `control`: hooks for the background service (see RunControl)."""
    # OpenCV splits even small per-frame jobs (the preview's color conversion,
    # resizes) across every core through GCD; the hand-off costs more than the
    # work: ~13 ms of CPU per preview frame instead of ~4, and a third of the
    # app's total CPU. One thread is as fast here and much cooler.
    cv2.setNumThreads(1)
    choice = GarmentChoice(config.garment, config.garment_color, config.garment_auto)
    try:
        wardrobe = Wardrobe(Path(config.garments_dir), config.garment, effective(choice).color)
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
        segmenter = stack.enter_context(BodySegmenter(config.segmenter_model_path, gpu=config.pose.segmenter_gpu))
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

        if control is not None and control.hub is not None:
            hub = control.hub
            choice = hub.choice
            auto, matcher = apply_choice(choice, wardrobe, matcher)
        else:
            hub = SettingsHub(Path(config.garments_dir), choice, settings_path)
        seen_version = hub.version
        settings = None
        if config.settings_port and (vcam is not None or config.preview) and (control is None or control.hub is None):
            try:
                settings = stack.enter_context(SettingsServer(hub, config.settings_port))
                print(f"settings page: {settings.url}")
            except OSError as e:
                print(f"settings page off: port {config.settings_port} unavailable ({e})", file=sys.stderr)

        preview = None
        if config.preview:
            preview = PreviewWindow()
            stack.callback(preview.close)
            print("preview: Esc/Q quit, M mode, P next garment, A auto garment, S settings, D cycle debug overlays")

        mode = config.mode
        debug = config.debug
        stats = Stats()
        auto = hub.choice.auto
        legs_in_view = True
        person_seen = last_probe = time.perf_counter()
        raw_pose: PoseFrame | None = None
        frames = detected = dressed = 0
        sources: dict[str, int] = {}
        total_inference_ms = total_render_ms = 0.0
        # Video files are paced to real time only when someone is watching.
        pace = not source.is_live and (vcam is not None or preview is not None)
        frame_interval = 1.0 / source.fps
        start = last = deadline = time.perf_counter()

        try:
            while max_frames is None or frames < max_frames:
                if control is not None and (
                    control.stop.is_set() or (control.keep_running is not None and not control.keep_running())
                ):
                    break
                frame = source.read()
                if frame is None:
                    if source.is_live:
                        print("camera stopped delivering frames", file=sys.stderr)
                        return 1
                    break

                if recorder is not None:
                    recorder.write(frame.image)
                # The segmenter is the most expensive model: run it only while legs are
                # in view, and just before a shirt color sample is due.
                need_legs = legs_in_view and frames % max(1, config.pose.segment_every) == 0
                need_top = auto and frames % TOP_SAMPLE_EVERY == TOP_SAMPLE_EVERY - 1
                if need_legs or need_top:
                    segmenter.submit(frame.image, frame.t_ms)  # runs while the pose model works
                if raw_pose is None or frames % max(1, config.pose.pose_every) == 0:
                    raw_pose = detector.detect(frame.image, frame.t_ms)
                else:
                    raw_pose = replace(raw_pose, t_ms=frame.t_ms, inference_ms=0.0)
                pose = smoother(raw_pose, width, height)
                segmentation = segmenter.latest()
                if segmentation is not None and frame.t_ms - segmentation.t_ms > SEGMENTATION_MAX_AGE_MS:
                    segmentation = None
                geometry = legs.update(pose, width, height, segmentation)
                legs_in_view = pose.has_hips()
                if hub.version != seen_version:  # changed on the settings page
                    seen_version = hub.version
                    auto, matcher = apply_choice(hub.choice, wardrobe, matcher)
                if auto and matcher is not None and frames % TOP_SAMPLE_EVERY == 0:
                    switched = matcher.update(sample_top_color(frame.image, pose, segmentation), frame.t_ms)
                    if switched is not None:
                        wardrobe.select(switched)
                        hub.set(GarmentChoice(switched, hub.choice.color, True), save=False)
                        seen_version = hub.version
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
                if control is None:
                    hub.feed.publish(output)  # browser extension tabs (no-op without any)
                if control is not None:
                    if control.on_frame is not None:
                        control.on_frame(output)
                    now = time.perf_counter()
                    if pose.detected:
                        person_seen = now
                    idle = now - max(person_seen, last_probe)
                    if control.probe is not None and vcam is not None and idle >= control.probe_after_s:
                        last_probe = now
                        vcam.close()
                        if not control.probe():
                            break
                        try:
                            vcam = stack.enter_context(VirtualCam(width, height, source.fps))
                        except VirtualCamError as e:
                            print(f"virtual camera error: {e}", file=sys.stderr)
                            return 1

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
                        wardrobe.set_color(hub.choice.color)
                    elif key == ord("a"):
                        if matcher is None:
                            matcher = OutfitMatcher(wardrobe.colors(), wardrobe.current.id)
                        auto = not auto
                        matcher.follow(wardrobe.current.id)
                        wardrobe.set_color(effective(replace(hub.choice, auto=auto)).color)
                    elif key == ord("s") and settings is not None:
                        settings.open()
                    if key in (ord("p"), ord("a")):  # keep the page in step; not saved as the default
                        hub.set(GarmentChoice(wardrobe.current.id, hub.choice.color, auto), save=False)
                        seen_version = hub.version

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
