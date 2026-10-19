"""Generate the built-in garment textures procedurally (garments/<id>/).

The textures are drawn from scratch here so the project owns them; nothing
comes from other projects' assets. Re-run after changing the layout:

    python scripts/make_garments.py
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1] / "garments"
W, H = 1024, 1536
MID = W // 2

# Rows of the screen-left leg: y, outer x, inner x. The right leg mirrors it.
ROWS_Y = np.array([40.0, 430.0, 950.0, 1500.0])
OUTER_X = np.array([205.0, 180.0, 225.0, 238.0])
INNER_X = np.array([MID, MID, 478.0, 490.0])
WAISTBAND = (40, 105)


@dataclass(frozen=True)
class Style:
    id: str
    name: str
    bgr: tuple[int, int, int]
    twill: float  # diagonal weave contrast
    mottle: float  # low-frequency color variation
    crease: bool  # pressed front crease (dress trousers)
    stitch_bgr: tuple[int, int, int] | None  # contrast stitching (jeans)
    ease: float
    folds: float  # depth of baked-in fabric folds


STYLES = (
    Style("dress_navy", "深藍西裝褲", (72, 42, 30), twill=2.0, mottle=3.0, crease=True, stitch_bgr=None, ease=1.15, folds=0.10),
    Style("chino_khaki", "卡其褲", (118, 162, 188), twill=4.0, mottle=4.0, crease=False, stitch_bgr=None, ease=1.18, folds=0.16),
    Style("jeans_indigo", "牛仔褲", (112, 66, 44), twill=9.0, mottle=10.0, crease=False, stitch_bgr=(60, 140, 214), ease=1.12, folds=0.18),
)


def leg_edges(y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return np.interp(y, ROWS_Y, OUTER_X), np.interp(y, ROWS_Y, INNER_X)


def coverage_and_u() -> tuple[np.ndarray, np.ndarray]:
    """Anti-aliased silhouette alpha and per-pixel position across the leg (0 outer, 1 inner)."""
    y = np.arange(H, dtype=np.float64)[:, None] + 0.5
    x = np.arange(W, dtype=np.float64)[None, :] + 0.5
    outer, inner = leg_edges(y)
    xl = x  # screen-left leg in its own coordinates
    xr = W - x  # right leg mirrored into left-leg coordinates
    alpha = np.zeros((H, W))
    u = np.zeros((H, W))
    for xx in (xl, xr):
        a = np.clip(np.minimum(xx - outer, inner - xx) + 0.5, 0, 1)
        alpha = np.maximum(alpha, a)
        uu = np.clip((xx - outer) / np.maximum(inner - outer, 1), 0, 1)
        u = np.where(a > 0, uu, u)
    vertical = np.clip(np.minimum(y - ROWS_Y[0], ROWS_Y[-1] - y) + 0.5, 0, 1)
    return alpha * vertical, u


def blurred_noise(rng: np.random.Generator, sigma: float) -> np.ndarray:
    n = cv2.GaussianBlur(rng.standard_normal((H, W)), (0, 0), sigma)
    return n / (np.abs(n).max() + 1e-9)


def draw_seam(img: np.ndarray, pts: np.ndarray, shade: float = 0.72) -> None:
    """A sewn seam: a dark groove with a faint highlight beside it."""
    pts = np.round(pts).astype(np.int32).reshape(-1, 1, 2)
    groove = np.zeros((H, W), np.float32)
    cv2.polylines(groove, [pts], False, 1.0, 3, cv2.LINE_AA)
    light = np.zeros((H, W), np.float32)
    cv2.polylines(light, [pts + np.array([2, 0])], False, 1.0, 2, cv2.LINE_AA)
    img *= (1 - (1 - shade) * groove)[..., None]
    img *= (1 + 0.12 * light)[..., None]


def draw_stitch(img: np.ndarray, pts: np.ndarray, bgr: tuple[int, int, int]) -> None:
    """Dashed contrast stitching along a polyline."""
    pts = pts.astype(np.float64)
    seg = np.diff(pts, axis=0)
    lengths = np.hypot(seg[:, 0], seg[:, 1])
    total = lengths.sum()
    for start in np.arange(0, total, 14.0):
        a = _along(pts, lengths, start)
        b = _along(pts, lengths, min(start + 8.0, total))
        cv2.line(img, tuple(np.round(a).astype(int)), tuple(np.round(b).astype(int)), bgr, 2, cv2.LINE_AA)


def _along(pts: np.ndarray, lengths: np.ndarray, d: float) -> np.ndarray:
    for p, q, l in zip(pts[:-1], pts[1:], lengths):
        if d <= l:
            return p + (q - p) * (d / max(l, 1e-9))
        d -= l
    return pts[-1]


def fold(d: np.ndarray, width: float) -> np.ndarray:
    """Shading across a soft fabric fold at signed distance d: lit ridge, shadowed valley."""
    return 0.6 * np.exp(-((d + width * 0.4) / width) ** 2) - np.exp(-((d - width * 0.5) / (0.7 * width)) ** 2)


def folds(rng: np.random.Generator, u: np.ndarray, y: np.ndarray, x: np.ndarray, strength: float) -> np.ndarray:
    """Multiplicative fold shading: knee bunching, crotch whiskers, hem breaks."""
    shade = np.zeros((H, W))
    on_leg = (y > ROWS_Y[1]) & (y < ROWS_Y[-1])
    # knees: a few short curved folds per leg, each fading out across the leg,
    # different on each leg so they do not read as drawn rings
    for leg in (x < MID, x >= MID):
        for _ in range(4):
            center = ROWS_Y[2] + rng.uniform(-100, 90) + rng.uniform(8, 30) * np.sin(np.pi * u + rng.uniform(-0.6, 0.6))
            span = np.exp(-((u - rng.uniform(0.25, 0.75)) / rng.uniform(0.25, 0.45)) ** 2)
            shade += leg * on_leg * span * fold(y - center, rng.uniform(8, 16)) * rng.uniform(0.5, 1.0)
    # crotch whiskers: short diagonal folds fanning out from the crotch on each leg
    for sign, cx in ((1, MID), (-1, MID)):
        for angle in rng.uniform(0.35, 0.75, 3):
            d = (x - cx) * np.cos(angle) * sign + (y - ROWS_Y[1]) * np.sin(angle) - rng.uniform(40, 90)
            reach = np.exp(-(((x - cx) * sign - 120) / 110) ** 2) * np.exp(-((y - ROWS_Y[1] - 70) / 70) ** 2)
            shade += fold(d, 10) * reach * 0.8
    # hem break: folds where the trouser rests on the shoe
    for leg in (x < MID, x >= MID):
        for offset in (rng.uniform(55, 85), rng.uniform(120, 170)):
            center = ROWS_Y[-1] - offset - rng.uniform(5, 18) * np.sin(np.pi * u)
            span = np.exp(-((u - rng.uniform(0.3, 0.7)) / 0.4) ** 2)
            shade += leg * on_leg * span * fold(y - center, rng.uniform(10, 14)) * 0.7
    return 1 + strength * shade


def mirror(pts: list[tuple[float, float]]) -> np.ndarray:
    return np.array([(W - x, y) for x, y in pts])


def make(style: Style, out_dir: Path) -> None:
    rng = np.random.default_rng(zlib.crc32(style.id.encode()))
    alpha, u = coverage_and_u()
    y = np.arange(H, dtype=np.float64)[:, None]
    x = np.arange(W, dtype=np.float64)[None, :]

    img = np.ones((H, W, 3)) * np.array(style.bgr, dtype=np.float64)
    # fabric: mottling, fine grain, diagonal twill
    img += (style.mottle * blurred_noise(rng, 30))[..., None]
    img += (1.5 * rng.standard_normal((H, W)))[..., None]
    img += (style.twill * np.sin(2 * np.pi * (x + y) / 5.0))[..., None]
    # baked roundness: legs a little darker toward both edges
    img *= (0.84 + 0.16 * np.sin(np.pi * u) ** 0.6)[..., None]

    if style.stitch_bgr is not None:  # jeans fade lighter down the front of the thighs
        fade = np.exp(-((u - 0.45) / 0.22) ** 2) * np.exp(-((y - 700) / 350) ** 2)
        img *= (1 + 0.22 * fade)[..., None]

    img *= folds(rng, u, y, x, style.folds)[..., None]

    if style.crease:
        outer, inner = leg_edges(y)
        for center in (outer + 0.5 * (inner - outer), W - (outer + 0.5 * (inner - outer))):
            d = x - center
            on_leg = (y > ROWS_Y[1]) & (y < ROWS_Y[-1])
            img *= (1 + on_leg * (0.16 * np.exp(-(d / 2.5) ** 2) - 0.06 * np.exp(-((d - 5) / 4) ** 2)))[..., None]

    # waistband, belt loops, fly, slant pockets, hem
    top, bottom = WAISTBAND
    img[top:bottom] *= 0.9
    draw_seam(img, np.array([(150, bottom), (W - 150, bottom)]))
    for lx in (262, 410, W - 410, W - 262):
        img[top - 2 : bottom + 8, lx : lx + 18] *= 1.08
        draw_seam(img, np.array([(lx, top), (lx, bottom + 8)]), 0.8)
        draw_seam(img, np.array([(lx + 18, top), (lx + 18, bottom + 8)]), 0.8)
    fly = np.array([(548, bottom), (548, 330), (540, 372), (512, 400)])
    draw_seam(img, fly)
    pocket_l = np.array([(318, bottom), (262, 210), (196, 300)])
    draw_seam(img, pocket_l)
    draw_seam(img, mirror(list(map(tuple, pocket_l))))
    img[ROWS_Y[-1].astype(int) - 28 : ROWS_Y[-1].astype(int)] *= 0.9
    hem_y = ROWS_Y[-1] - 28
    for xs in ((OUTER_X[-1], INNER_X[-1]), (W - INNER_X[-1], W - OUTER_X[-1])):
        draw_seam(img, np.array([(xs[0], hem_y), (xs[1], hem_y)]), 0.82)

    if style.stitch_bgr is not None:
        draw_stitch(img, fly + np.array([-12, 0]), style.stitch_bgr)
        draw_stitch(img, pocket_l + np.array([8, 6]), style.stitch_bgr)
        draw_stitch(img, mirror(list(map(tuple, pocket_l))) + np.array([-8, 6]), style.stitch_bgr)
        draw_stitch(img, np.array([(150, top + 8), (W - 150, top + 8)]), style.stitch_bgr)
        draw_stitch(img, np.array([(150, bottom - 8), (W - 150, bottom - 8)]), style.stitch_bgr)

    bgra = np.dstack([np.clip(img, 0, 255), alpha * 255]).astype(np.uint8)
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / "texture.png"), bgra)

    def leg(side: str) -> dict[str, list[float]]:
        f = (lambda v: float(v)) if side == "left" else (lambda v: float(W - v))
        return {
            "waist_out": [f(OUTER_X[0]), float(ROWS_Y[0])],
            "crotch_out": [f(OUTER_X[1]), float(ROWS_Y[1])],
            "knee_out": [f(OUTER_X[2]), float(ROWS_Y[2])],
            "knee_in": [f(INNER_X[2]), float(ROWS_Y[2])],
            "hem_out": [f(OUTER_X[3]), float(ROWS_Y[3])],
            "hem_in": [f(INNER_X[3]), float(ROWS_Y[3])],
        }

    spec = {
        "id": style.id,
        "name": style.name,
        "type": "pants",
        "ease": style.ease,
        "texture": "texture.png",
        "anchors": {
            "waist_mid": [float(MID), float(ROWS_Y[0])],
            "crotch": [float(MID), float(ROWS_Y[1])],
            "left": leg("left"),
            "right": leg("right"),
        },
        "mesh": {"waist_rows": 3, "along": 8, "across": 4},
    }
    header = "# Generated by scripts/make_garments.py; left/right are screen sides.\n"
    (out_dir / "garment.yaml").write_text(
        header + yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(f"wrote {out_dir}")


def main() -> None:
    for style in STYLES:
        make(style, ROOT / style.id)


if __name__ == "__main__":
    main()
