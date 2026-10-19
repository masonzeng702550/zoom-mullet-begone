"""CPU mesh renderer: piecewise-affine texture mapping with OpenCV.

Instead of warping each triangle separately (which leaves hairline seams), it
fills one inverse map (frame pixel -> texture pixel) triangle by triangle and
samples the texture once with cv2.remap.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from meet_pants.render.mesh import Mesh

SUBPIXEL_SHIFT = 4  # fillConvexPoly fixed-point bits


@dataclass(frozen=True)
class Layer:
    rgba: np.ndarray  # BGRA uint8 covering `box`
    box: tuple[int, int, int, int]  # x0, y0, x1, y1 in frame pixels


def _triangle_areas(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    p = points[triangles]
    return np.abs(
        (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1])
    ) / 2


def pick_level(mesh: Mesh, levels: int) -> int:
    """Pyramid level whose resolution best matches the mesh's on-screen size.

    Bilinear sampling is clean while the texture is shrunk by at most 2x, so
    pick the smallest level that is still at least as large as the screen.
    """
    screen = _triangle_areas(mesh.dst, mesh.triangles).sum()
    texture = _triangle_areas(mesh.src, mesh.triangles).sum()
    if screen <= 0 or texture <= 0:
        return 0
    shrink = float(np.sqrt(texture / screen))  # texture pixels per screen pixel
    return int(np.clip(np.floor(np.log2(max(shrink, 1.0))), 0, levels - 1))


def render_mesh(
    mesh: Mesh, texture: np.ndarray | tuple[np.ndarray, ...], frame_shape: tuple[int, ...]
) -> Layer | None:
    """Rasterize the mesh. `texture` may be a single image or a mipmap pyramid."""
    pyramid = texture if isinstance(texture, tuple) else (texture,)
    level = pick_level(mesh, len(pyramid))
    texture = pyramid[level]
    src = mesh.src / (1 << level)
    h, w = frame_shape[:2]
    lo = np.floor(mesh.dst.min(axis=0)).astype(int)
    hi = np.ceil(mesh.dst.max(axis=0)).astype(int) + 1
    x0, y0 = max(lo[0], 0), max(lo[1], 0)
    x1, y1 = min(hi[0], w), min(hi[1], h)
    if x1 <= x0 or y1 <= y0:
        return None

    bw, bh = x1 - x0, y1 - y0
    dst = (mesh.dst - np.array([x0, y0], np.float32)).astype(np.float64)
    tri_dst = dst[mesh.triangles]  # (T, 3, 2)
    tri_src = src[mesh.triangles].astype(np.float64)
    e1, e2 = tri_dst[:, 1] - tri_dst[:, 0], tri_dst[:, 2] - tri_dst[:, 0]
    keep = np.abs(e1[:, 0] * e2[:, 1] - e2[:, 0] * e1[:, 1]) >= 0.5  # skip collapsed triangles
    tri_dst, tri_src = tri_dst[keep], tri_src[keep]
    if len(tri_dst) == 0:
        return None

    # Label every pixel with the triangle covering it (uint16: index + 1) ...
    labels = np.zeros((bh, bw), np.uint16)
    polys = np.round(tri_dst * (1 << SUBPIXEL_SHIFT)).astype(np.int32)
    for k, poly in enumerate(polys, start=1):
        cv2.fillConvexPoly(labels, poly, k, cv2.LINE_8, SUBPIXEL_SHIFT)

    # ... then map all labelled pixels to the texture at once, each through its
    # triangle's affine transform (frame -> texture), solved for all triangles together.
    ones = np.ones((len(tri_dst), 3, 1))
    affine = np.linalg.solve(np.concatenate([tri_dst, ones], axis=2), tri_src)  # (T, 3, 2)
    ys, xs = np.nonzero(labels)
    a = affine[labels[ys, xs].astype(np.intp) - 1]  # (N, 3, 2)
    map_x = np.full((bh, bw), -1.0, np.float32)
    map_y = np.full((bh, bw), -1.0, np.float32)
    map_x[ys, xs] = xs * a[:, 0, 0] + ys * a[:, 1, 0] + a[:, 2, 0]
    map_y[ys, xs] = xs * a[:, 0, 1] + ys * a[:, 1, 1] + a[:, 2, 1]

    rgba = cv2.remap(
        texture, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0)
    )
    return Layer(rgba, (x0, y0, x1, y1))
