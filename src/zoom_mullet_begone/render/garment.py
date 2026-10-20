"""Garment assets: an RGBA front-view texture plus anchor points on it.

garments/<id>/garment.yaml
garments/<id>/texture.png

Anchors are pixel coordinates on the texture. `left` and `right` mean screen
sides, matching LegGeometry. Each leg is mapped row by row:

    waist row   waist_out ........ waist_mid
    crotch row  crotch_out ....... crotch
    knee row    knee_out ......... knee_in
    hem row     hem_out .......... hem_in
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np
import yaml

TRIM_KINDS = ("seam", "edge", "crease", "stitch")
LEG_ANCHORS = ("waist_out", "crotch_out", "knee_out", "knee_in", "hem_out", "hem_in")


class GarmentError(ValueError):
    pass


@dataclass(frozen=True)
class LegAnchors:
    waist_out: np.ndarray
    crotch_out: np.ndarray
    knee_out: np.ndarray
    knee_in: np.ndarray
    hem_out: np.ndarray
    hem_in: np.ndarray


@dataclass(frozen=True)
class TrimLine:
    kind: str  # one of TRIM_KINDS
    points: np.ndarray  # (N, 2) texture pixels
    color: tuple[int, int, int] | None = None  # BGR, for stitches


@dataclass(frozen=True)
class Garment:
    id: str
    name: str
    ease: float  # garment half width relative to the measured leg half width
    texture: np.ndarray  # BGRA uint8
    # texture, then each level half the size: sampling the level closest to the
    # on-screen size avoids the shimmer/moire of sampling a large texture sparsely
    pyramid: tuple[np.ndarray, ...]
    waist_mid: np.ndarray
    crotch: np.ndarray
    left: LegAnchors
    right: LegAnchors
    waist_rows: int  # mesh rows between waist and crotch
    along: int  # mesh rows per thigh / shin
    across: int  # mesh columns across each leg
    trim: tuple[TrimLine, ...] = ()  # seams etc. drawn as crisp lines on screen


MIN_LEVEL_SIZE = 64


def build_pyramid(texture: np.ndarray) -> tuple[np.ndarray, ...]:
    levels = [texture]
    while min(levels[-1].shape[:2]) >= 2 * MIN_LEVEL_SIZE:
        levels.append(cv2.pyrDown(levels[-1]))
    return tuple(levels)


def _point(data: dict, key: str, where: str) -> np.ndarray:
    try:
        x, y = data[key]
        return np.array([float(x), float(y)])
    except (KeyError, TypeError, ValueError):
        raise GarmentError(f"{where}: missing or invalid anchor '{key}' (expected [x, y])") from None


def load_garment(root: Path, garment_id: str) -> Garment:
    folder = Path(root).expanduser() / garment_id
    spec_path = folder / "garment.yaml"
    if not spec_path.exists():
        raise GarmentError(f"garment not found: {spec_path}")
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    texture = cv2.imread(str(folder / spec.get("texture", "texture.png")), cv2.IMREAD_UNCHANGED)
    if texture is None or texture.ndim != 3 or texture.shape[2] != 4:
        raise GarmentError(f"{folder}: texture must be an RGBA PNG")

    anchors = spec.get("anchors", {})
    legs = {}
    for side in ("left", "right"):
        data = anchors.get(side, {})
        legs[side] = LegAnchors(*(_point(data, k, f"{spec_path} anchors.{side}") for k in LEG_ANCHORS))
    mesh = spec.get("mesh", {})
    return Garment(
        id=garment_id,
        name=str(spec.get("name", garment_id)),
        ease=float(spec.get("ease", 1.15)),
        texture=texture,
        pyramid=build_pyramid(texture),
        waist_mid=_point(anchors, "waist_mid", f"{spec_path} anchors"),
        crotch=_point(anchors, "crotch", f"{spec_path} anchors"),
        left=legs["left"],
        right=legs["right"],
        waist_rows=int(mesh.get("waist_rows", 3)),
        along=int(mesh.get("along", 8)),
        across=int(mesh.get("across", 4)),
        trim=_trim(spec, str(spec_path)),
    )


def _trim(spec: dict, where: str) -> tuple[TrimLine, ...]:
    lines = []
    for i, item in enumerate(spec.get("trim", []) or []):
        kind = item.get("kind")
        if kind not in TRIM_KINDS:
            raise GarmentError(f"{where} trim[{i}]: kind must be one of {', '.join(TRIM_KINDS)}")
        try:
            points = np.array(item["points"], dtype=np.float64).reshape(-1, 2)
        except (KeyError, ValueError):
            raise GarmentError(f"{where} trim[{i}]: points must be a list of [x, y]") from None
        if len(points) < 2:
            raise GarmentError(f"{where} trim[{i}]: needs at least 2 points")
        color = item.get("color")
        lines.append(TrimLine(kind, points, tuple(int(c) for c in color) if color else None))
    return tuple(lines)


def list_garments(root: Path) -> list[str]:
    root = Path(root).expanduser()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "garment.yaml").exists())


def parse_color(text: str) -> tuple[int, int, int]:
    """'#rrggbb' -> BGR."""
    value = text.strip().lstrip("#")
    if len(value) != 6:
        raise GarmentError(f"color must look like #rrggbb, got {text!r}")
    try:
        r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise GarmentError(f"color must look like #rrggbb, got {text!r}") from None
    return b, g, r


def recolor_texture(texture: np.ndarray, bgr: tuple[int, int, int]) -> np.ndarray:
    """The texture in another color, keeping its shading, weave and folds.

    Each pixel's brightness relative to the fabric's median brightness is kept
    and applied to the new color, so a fold that is 20% darker stays 20% darker.
    """
    out = texture.copy()
    opaque = texture[..., 3] > 0
    if not opaque.any():
        return out
    luma = cv2.cvtColor(np.ascontiguousarray(texture[..., :3]), cv2.COLOR_BGR2GRAY).astype(np.float32)
    ratio = luma / max(float(np.median(luma[texture[..., 3] > 200])), 1.0)
    rgb = np.clip(ratio[..., None] * np.array(bgr, np.float32), 0, 255).astype(np.uint8)
    out[..., :3] = np.where(opaque[..., None], rgb, texture[..., :3])
    return out


def with_color(garment: Garment, color: str | None) -> Garment:
    """The garment recolored to '#rrggbb'; unchanged for None / ''."""
    if not color:
        return garment
    texture = recolor_texture(garment.texture, parse_color(color))
    return replace(garment, texture=texture, pyramid=build_pyramid(texture))
