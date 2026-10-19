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

from dataclasses import dataclass
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
