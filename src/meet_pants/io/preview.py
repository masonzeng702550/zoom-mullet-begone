"""Local preview window with debug overlays (skeleton, person mask, HUD).

Overlays are drawn on a copy for the preview only; the virtual camera never
receives them.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from mediapipe.tasks.python import vision

from meet_pants.config import DebugConfig
from meet_pants.perception.segmenter import Segmentation
from meet_pants.perception.types import LEG_LANDMARKS, PoseFrame
from meet_pants.render.mesh import Mesh

WINDOW_NAME = "meet-pants preview"
CONNECTIONS = [(c.start, c.end) for c in vision.PoseLandmarksConnections.POSE_LANDMARKS]
VISIBLE = 0.5

# BGR
COLOR_BODY = (255, 200, 80)
COLOR_LEG = (60, 220, 255)
COLOR_HIDDEN = (120, 120, 120)
COLOR_MASK = np.array([255, 0, 180], dtype=np.float32)
COLOR_SKIN = np.array([60, 140, 255], dtype=np.float32)
COLOR_MESH = (0, 255, 255)
COLOR_TEXT = (255, 255, 255)

KEY_ESC = 27


@dataclass
class Stats:
    fps: float = 0.0
    inference_ms: float = 0.0
    frame_ms: float = 0.0
    render_ms: float = 0.0

    def update(self, frame_ms: float, inference_ms: float, render_ms: float = 0.0, alpha: float = 0.1) -> None:
        if self.frame_ms == 0.0:
            self.frame_ms, self.inference_ms, self.render_ms = frame_ms, inference_ms, render_ms
        else:
            self.frame_ms += alpha * (frame_ms - self.frame_ms)
            self.inference_ms += alpha * (inference_ms - self.inference_ms)
            self.render_ms += alpha * (render_ms - self.render_ms)
        self.fps = 1000.0 / self.frame_ms if self.frame_ms > 0 else 0.0


def draw_mask(
    image: np.ndarray, mask: np.ndarray, strength: float = 0.4, color: np.ndarray = COLOR_MASK
) -> None:
    mask = mask.astype(np.float32)
    if mask.shape != image.shape[:2]:
        mask = cv2.resize(mask, (image.shape[1], image.shape[0]))
    weight = (np.clip(mask, 0.0, 1.0) * strength)[..., None]
    image[:] = (image * (1.0 - weight) + color * weight).astype(np.uint8)


def draw_skeleton(image: np.ndarray, pose: PoseFrame) -> None:
    if not pose.landmarks:
        return
    h, w = image.shape[:2]
    points = [lm.to_px(w, h) for lm in pose.landmarks]
    vis = [lm.visibility for lm in pose.landmarks]
    thickness = max(2, w // 400)

    for a, b in CONNECTIONS:
        visible = vis[a] >= VISIBLE and vis[b] >= VISIBLE
        is_leg = a in LEG_LANDMARKS and b in LEG_LANDMARKS
        color = (COLOR_LEG if is_leg else COLOR_BODY) if visible else COLOR_HIDDEN
        cv2.line(image, points[a], points[b], color, thickness if visible else 1, cv2.LINE_AA)

    for i, p in enumerate(points):
        visible = vis[i] >= VISIBLE
        color = (COLOR_LEG if i in LEG_LANDMARKS else COLOR_BODY) if visible else COLOR_HIDDEN
        cv2.circle(image, p, thickness + 2, color, -1 if visible else 1, cv2.LINE_AA)


def draw_mesh(image: np.ndarray, mesh: Mesh) -> None:
    polys = np.round(mesh.dst[mesh.triangles]).astype(np.int32)
    cv2.polylines(image, list(polys), True, COLOR_MESH, 1, cv2.LINE_AA)


def draw_hud(image: np.ndarray, pose: PoseFrame, stats: Stats, lines: list[str]) -> None:
    hip_vis = (pose.visibility(23) + pose.visibility(24)) / 2
    knee_vis = (pose.visibility(25) + pose.visibility(26)) / 2
    text = [
        f"{stats.fps:5.1f} fps  frame {stats.frame_ms:5.1f} ms  pose {stats.inference_ms:5.1f} ms  "
        f"render {stats.render_ms:4.1f} ms",
        f"person {'yes' if pose.detected else 'no '}  hips {hip_vis:.2f}  knees {knee_vis:.2f}",
        *lines,
    ]
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = max(0.45, image.shape[1] / 2200)
    thickness = 1 if scale < 0.7 else 2
    sizes = [cv2.getTextSize(line, font, scale, thickness)[0] for line in text]
    line_h = max(h for _, h in sizes) * 2
    pad = line_h // 3

    box_w = max(w for w, _ in sizes) + 2 * pad
    box_h = line_h * len(text) + pad
    region = image[:box_h, :box_w]
    region[:] = (region * 0.35).astype(np.uint8)  # darken behind the text
    for i, line in enumerate(text):
        org = (pad, line_h * (i + 1) - pad // 2)
        cv2.putText(image, line, org, font, scale, COLOR_TEXT, thickness, cv2.LINE_AA)


def render_preview(
    frame: np.ndarray,
    pose: PoseFrame,
    debug: DebugConfig,
    stats: Stats,
    mirror: bool,
    status_lines: list[str] | None = None,
    mesh: Mesh | None = None,
    segmentation: Segmentation | None = None,
) -> np.ndarray:
    image = frame.copy()
    if debug.masks and pose.person_mask is not None:
        draw_mask(image, pose.person_mask)
    if debug.masks and segmentation is not None and segmentation.category.shape == image.shape[:2]:
        draw_mask(image, segmentation.skin, 0.5, COLOR_SKIN)
    if debug.mesh and mesh is not None:
        draw_mesh(image, mesh)
    if debug.landmarks:
        draw_skeleton(image, pose)
    if mirror:
        image = cv2.flip(image, 1)
    # HUD after the flip so the text stays readable.
    if debug.hud:
        draw_hud(image, pose, stats, status_lines or [])
    return image


class PreviewWindow:
    def __init__(self) -> None:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

    def show(self, image: np.ndarray) -> int:
        """Show the image and return the pressed key code, or -1."""
        cv2.imshow(WINDOW_NAME, image)
        key = cv2.waitKey(1)
        return key & 0xFF if key != -1 else -1

    def closed(self) -> bool:
        return cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1

    def close(self) -> None:
        cv2.destroyWindow(WINDOW_NAME)
        cv2.waitKey(1)
