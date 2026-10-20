"""Builds the garment mesh: matching vertex grids on the texture and in the frame.

Each leg is a strip of rows (waist -> crotch -> knee -> hem). Every row runs
from the leg's outer edge to its inner edge and is split into `across`
columns. The texture rows come from the garment anchors, the frame rows from
LegGeometry, so the texture bends at the knee with the leg.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from zoom_mullet_begone.analysis.leg_geometry import Leg, LegGeometry
from zoom_mullet_begone.render.garment import Garment, LegAnchors

# Fraction of the thigh over which the inner edge leaves the crotch point and
# joins the thigh's own inner contour.
CROTCH_BLEND = 0.35
# Pants are at least this much wider than the measured leg (skin + clothes).
BODY_MARGIN = 1.05
BODY_PAD = 2.0  # pixels


@dataclass(frozen=True)
class Mesh:
    dst: np.ndarray  # (N, 2) float32 frame pixels
    src: np.ndarray  # (N, 2) float32 texture pixels
    triangles: np.ndarray  # (M, 3) int32 vertex indices


def lerp(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    return a + (b - a) * t


def _crosses(p: np.ndarray, origin: np.ndarray, m: np.ndarray, sign: float) -> bool:
    """True if p lies past the line through `origin` with normal m, in direction sign * m."""
    return float((p - origin) @ m) * sign > 0


def _leg_rows(
    leg: Leg, anchors: LegAnchors, garment: Garment, waist_mid: np.ndarray, crotch_mid: np.ndarray
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """Rows of (dst_outer, dst_inner, src_outer, src_inner), top to bottom.

    Each row is as wide as the larger of the garment's own cut (straight
    taper from the median leg widths, times ease) and the measured leg at that
    row plus a small margin, so the pants keep their shape but never leave
    skin uncovered where a leg is wider than average.
    """
    ease = garment.ease
    style_top = leg.thigh_half * ease * 1.05
    style_knee = (0.45 * leg.thigh_half + 0.55 * leg.shin_half) * ease
    style_hem = max(leg.shin_half * ease, 0.75 * style_knee)

    def body(half: float) -> float:
        return half * BODY_MARGIN + BODY_PAD

    shin_len = max(float(np.hypot(*(leg.ankle - leg.knee))), 1e-6)
    hem_t = float(np.hypot(*(leg.hem - leg.knee))) / shin_len  # mesh t=1 in shin-profile units

    def thigh_row(t: float) -> tuple[float, float]:
        half, shift = leg.thigh.at(t)
        return max(lerp(style_top, style_knee, t), body(half)), shift

    def shin_row(t: float) -> tuple[float, float]:
        half, shift = leg.shin.at(t * hem_t)
        return max(lerp(style_knee, style_hem, t), body(half)), shift

    top, top_shift = thigh_row(0.0)
    (wt, st), (ws, ss) = thigh_row(1.0), shin_row(0.0)
    knee, knee_shift = max(wt, ws), (st + ss) / 2
    thigh_n, shin_n, knee_n = leg.thigh_normal, leg.shin_normal, leg.knee_normal
    a = anchors
    # The knee bisector line separates thigh rows from shin rows. On a sharp
    # bend, rows near the knee would cross it on the inside of the bend and
    # fold the mesh; snapping those points to the knee row's edge point
    # collapses the triangles there instead (the fabric bunches at the crease).
    knee_c = leg.knee + knee_n * knee_shift
    knee_outer, knee_inner = knee_c + knee_n * knee, knee_c - knee_n * knee
    along_leg = (leg.knee - leg.crotch) / max(np.hypot(*(leg.knee - leg.crotch)), 1e-6) + (
        leg.hem - leg.knee
    ) / max(np.hypot(*(leg.hem - leg.knee)), 1e-6)
    m = np.array([-knee_n[1], knee_n[0]])
    if float(m @ along_leg) < 0:
        m = -m  # m points from the thigh side to the shin side

    rows = []
    # waist -> crotch: one panel shared with the other leg at the center line
    for i in range(garment.waist_rows + 1):
        t = i / garment.waist_rows
        rows.append((
            lerp(leg.waist + leg.outward * top, leg.crotch + thigh_n * (top + top_shift), t),
            lerp(waist_mid, crotch_mid, t),
            lerp(a.waist_out, a.crotch_out, t),
            lerp(garment.waist_mid, garment.crotch, t),
        ))
    # crotch -> knee
    for i in range(1, garment.along + 1):
        t = i / garment.along
        if i == garment.along:
            n, c, w = knee_n, knee_c, knee
        else:
            n = thigh_n
            w, shift = thigh_row(t)
            c = lerp(leg.crotch, leg.knee, t) + n * shift
        inner = lerp(crotch_mid, c - n * w, min(1.0, t / CROTCH_BLEND))
        outer = c + n * w
        if i < garment.along:
            outer = knee_outer if _crosses(outer, knee_c, m, 1.0) else outer
            inner = knee_inner if _crosses(inner, knee_c, m, 1.0) else inner
        rows.append((outer, inner, lerp(a.crotch_out, a.knee_out, t), lerp(garment.crotch, a.knee_in, t)))
    # knee -> hem
    for i in range(1, garment.along + 1):
        t = i / garment.along
        w, shift = shin_row(t)
        c = lerp(leg.knee, leg.hem, t) + shin_n * shift
        outer, inner = c + shin_n * w, c - shin_n * w
        outer = knee_outer if _crosses(outer, knee_c, m, -1.0) else outer
        inner = knee_inner if _crosses(inner, knee_c, m, -1.0) else inner
        rows.append((outer, inner, lerp(a.knee_out, a.hem_out, t), lerp(a.knee_in, a.hem_in, t)))
    return rows


def _grid(rows: list, across: int, offset: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    s = np.linspace(0.0, 1.0, across + 1)[:, None]
    dst = np.concatenate([do + (di - do) * s for do, di, _, _ in rows])
    src = np.concatenate([so + (si - so) * s for _, _, so, si in rows])
    cols = across + 1
    tris = []
    for r in range(len(rows) - 1):
        for c in range(across):
            p = offset + r * cols + c
            q = p + cols
            tris.append((p, p + 1, q))
            tris.append((p + 1, q + 1, q))
    return dst, src, np.array(tris, dtype=np.int32)


def build_mesh(geometry: LegGeometry, garment: Garment) -> Mesh:
    dsts, srcs, tris = [], [], []
    offset = 0
    for leg, anchors in ((geometry.left, garment.left), (geometry.right, garment.right)):
        rows = _leg_rows(leg, anchors, garment, geometry.waist_mid, geometry.crotch_mid)
        dst, src, t = _grid(rows, garment.across, offset)
        dsts.append(dst)
        srcs.append(src)
        tris.append(t)
        offset += len(dst)
    return Mesh(
        dst=np.concatenate(dsts).astype(np.float32),
        src=np.concatenate(srcs).astype(np.float32),
        triangles=np.concatenate(tris),
    )
