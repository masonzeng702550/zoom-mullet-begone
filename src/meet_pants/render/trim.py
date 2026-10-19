"""Garment trim (seams, creases, stitching) drawn as crisp lines in screen space.

Fine details in the texture get lost when it is shown 3-5x smaller than it was
drawn. Trim lines are stored as polylines in texture coordinates, mapped
through the mesh (so they bend with the knees) and drawn anti-aliased at a
thickness suited to the on-screen size.
"""

from __future__ import annotations

import cv2
import numpy as np

from meet_pants.render.garment import TrimLine
from meet_pants.render.mesh import Mesh
from meet_pants.render.warp_cv import Layer

RESAMPLE = 12.0  # texture pixels between mapped points, so lines follow the bends
SHIFT = 3  # fixed-point bits for sub-pixel line positions
BARY_EPS = 1e-6
DEFAULT_STITCH = (60, 140, 214)  # BGR, jeans-orange


def resample(points: np.ndarray, step: float = RESAMPLE) -> np.ndarray:
    """Points along the polyline at most `step` apart (keeping the corners)."""
    out = [points[0]]
    for a, b in zip(points[:-1], points[1:]):
        n = max(1, int(np.ceil(np.hypot(*(b - a)) / step)))
        out.extend(a + (b - a) * (i / n) for i in range(1, n + 1))
    return np.array(out)


def map_points(mesh: Mesh, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Map texture points to the frame through the mesh triangle containing them.

    Returns (mapped (N, 2), found (N,) bool); points outside the mesh are not found.
    """
    tri_src = mesh.src[mesh.triangles].astype(np.float64)  # (T, 3, 2)
    origin = tri_src[:, 0]
    v0, v1 = tri_src[:, 1] - origin, tri_src[:, 2] - origin
    d00, d01, d11 = (v0 * v0).sum(-1), (v0 * v1).sum(-1), (v1 * v1).sum(-1)
    den = d00 * d11 - d01 * d01
    usable = np.abs(den) > 1e-9
    den = np.where(usable, den, 1.0)

    rel = points[:, None, :] - origin[None]  # (N, T, 2)
    d20, d21 = (rel * v0).sum(-1), (rel * v1).sum(-1)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    u = 1.0 - v - w
    inside = (u >= -BARY_EPS) & (v >= -BARY_EPS) & (w >= -BARY_EPS) & usable

    found = inside.any(axis=1)
    k = inside.argmax(axis=1)
    rows = np.arange(len(points))
    tri_dst = mesh.dst[mesh.triangles][k].astype(np.float64)  # (N, 3, 2)
    mapped = (
        u[rows, k][:, None] * tri_dst[:, 0] + v[rows, k][:, None] * tri_dst[:, 1] + w[rows, k][:, None] * tri_dst[:, 2]
    )
    return mapped, found


def _runs(mapped: np.ndarray, found: np.ndarray) -> list[np.ndarray]:
    """Split a mapped polyline where points fell outside the mesh."""
    runs, current = [], []
    for p, ok in zip(mapped, found):
        if ok:
            current.append(p)
        elif current:
            runs.append(np.array(current))
            current = []
    if current:
        runs.append(np.array(current))
    return [r for r in runs if len(r) >= 2]


def _dashes(run: np.ndarray, dash: float, gap: float) -> list[np.ndarray]:
    """Cut a screen-space polyline into dashes."""
    seg = np.diff(run, axis=0)
    lengths = np.hypot(seg[:, 0], seg[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(lengths)])
    out = []
    start = 0.0
    while start < cum[-1]:
        end = min(start + dash, cum[-1])
        ts = np.linspace(start, end, 3)
        xs = np.interp(ts, cum, run[:, 0])
        ys = np.interp(ts, cum, run[:, 1])
        out.append(np.stack([xs, ys], axis=1))
        start = end + gap
    return out


def draw_trim(layer: Layer, mesh: Mesh, lines: tuple[TrimLine, ...], scale: float) -> None:
    """Draw trim onto the layer's color channels in place. `scale` is the body size in pixels."""
    if not lines:
        return
    x0, y0, _, _ = layer.box
    h, w = layer.rgba.shape[:2]
    width = max(1, int(round(scale * 0.016)))
    dark = np.zeros((h, w), np.float32)
    light = np.zeros((h, w), np.float32)
    stitches: dict[tuple[int, int, int], list[np.ndarray]] = {}
    origin = np.array([x0, y0], np.float64)

    def poly(run: np.ndarray) -> np.ndarray:
        return np.round((run - origin) * (1 << SHIFT)).astype(np.int32).reshape(-1, 1, 2)

    for line in lines:
        mapped, found = map_points(mesh, resample(line.points))
        for run in _runs(mapped, found):
            if line.kind == "seam":
                # a sewn seam: shallow groove with lit shoulders on both sides
                cv2.polylines(light, [poly(run)], False, 0.5, width + 2, cv2.LINE_AA, SHIFT)
                cv2.polylines(dark, [poly(run)], False, 1.0, width, cv2.LINE_AA, SHIFT)
            elif line.kind == "edge":
                cv2.polylines(dark, [poly(run)], False, 0.7, width, cv2.LINE_AA, SHIFT)
            elif line.kind == "crease":
                cv2.polylines(light, [poly(run)], False, 1.0, width, cv2.LINE_AA, SHIFT)
            elif line.kind == "stitch":
                dash = max(2.5, scale * 0.05)
                color = line.color or DEFAULT_STITCH
                stitches.setdefault(color, []).extend(poly(p) for p in _dashes(run, dash, dash * 0.7))

    rgb = layer.rgba[..., :3].astype(np.float32)
    rgb *= (1.0 + 0.22 * np.clip(light, 0, 1))[..., None]
    rgb *= (1.0 - 0.38 * np.clip(dark, 0, 1))[..., None]
    for color, polys in stitches.items():
        mask = np.zeros((h, w), np.float32)
        cv2.polylines(mask, polys, False, 1.0, width, cv2.LINE_AA, SHIFT)
        a = (0.85 * np.clip(mask, 0, 1))[..., None]
        rgb = rgb * (1 - a) + np.array(color, np.float32) * a
    layer.rgba[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
