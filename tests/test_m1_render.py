from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from helpers import legs_mask, make_pose, standing_points
from meet_pants.analysis.leg_geometry import LegTracker
from meet_pants.config import DEFAULT_GARMENTS_DIR
from meet_pants.perception.types import Lm
from meet_pants.pipeline import Wardrobe, dress
from meet_pants.render.garment import GarmentError, list_garments, load_garment
from meet_pants.render.mesh import Mesh, build_mesh
from meet_pants.render.compositor import Compositor, SceneMasks, estimate_noise
from meet_pants.render.warp_cv import Layer, pick_level, render_mesh

W, H = 440, 520


@pytest.fixture(scope="module")
def garment():
    return load_garment(DEFAULT_GARMENTS_DIR, "dress_navy")


def signed_areas(mesh: Mesh) -> np.ndarray:
    p = mesh.dst[mesh.triangles]
    return (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1])


def test_builtin_garments_load() -> None:
    ids = list_garments(DEFAULT_GARMENTS_DIR)
    assert {"dress_navy", "chino_khaki", "jeans_indigo"} <= set(ids)
    for gid in ids:
        g = load_garment(DEFAULT_GARMENTS_DIR, gid)
        assert g.texture.shape[2] == 4


def test_missing_garment_errors(tmp_path: Path) -> None:
    with pytest.raises(GarmentError):
        load_garment(tmp_path, "nope")
    with pytest.raises(GarmentError, match="available: chino_khaki"):
        Wardrobe(DEFAULT_GARMENTS_DIR, "nope")


def test_wardrobe_cycles() -> None:
    wardrobe = Wardrobe(DEFAULT_GARMENTS_DIR, "dress_navy")
    seen = {wardrobe.current.id}
    for _ in range(len(wardrobe.ids)):
        seen.add(wardrobe.next().id)
    assert seen == set(wardrobe.ids)


def test_mesh_shape_and_texture_bounds(garment) -> None:
    geo = LegTracker().update(make_pose(standing_points(), W, H), W, H)
    mesh = build_mesh(geo, garment)
    rows = garment.waist_rows + 1 + 2 * garment.along
    assert len(mesh.dst) == 2 * rows * (garment.across + 1)
    assert mesh.triangles.min() >= 0 and mesh.triangles.max() < len(mesh.dst)
    th, tw = garment.texture.shape[:2]
    assert (mesh.src >= 0).all() and (mesh.src[:, 0] <= tw).all() and (mesh.src[:, 1] <= th).all()
    assert np.isfinite(mesh.dst).all()


@pytest.mark.parametrize("bend", [0, 45, 90, 120])
def test_bent_knee_does_not_fold_the_mesh(garment, bend: int) -> None:
    """No triangle of a leg flips winding however far the knee bends.

    Triangles on the inside of a sharp bend may collapse to (near) zero area,
    which renders nothing; a flipped triangle would draw texture inside out.
    """
    pts = standing_points()
    angle = np.radians(bend)
    for knee, ankle, side in ((Lm.LEFT_KNEE, Lm.LEFT_ANKLE, 1), (Lm.RIGHT_KNEE, Lm.RIGHT_ANKLE, -1)):
        kx, ky = pts[knee]
        pts[ankle] = (kx + side * 130 * np.sin(angle), ky + 130 * np.cos(angle))
    geo = LegTracker().update(make_pose(pts, W, H), W, H)
    mesh = build_mesh(geo, garment)
    half = len(mesh.triangles) // 2
    for areas in (signed_areas(mesh)[:half], signed_areas(mesh)[half:]):
        assert (areas > -1).all() or (areas < 1).all()


def test_identity_mesh_reproduces_texture(garment) -> None:
    """A mesh whose frame and texture coordinates match must copy the texture."""
    tex = garment.texture
    h, w = tex.shape[:2]
    xs, ys = np.meshgrid(np.linspace(0, w - 1, 9), np.linspace(0, h - 1, 13))
    pts = np.stack([xs.ravel(), ys.ravel()], axis=1).astype(np.float32)
    tris = []
    for r in range(12):
        for c in range(8):
            p = r * 9 + c
            tris += [(p, p + 1, p + 9), (p + 1, p + 10, p + 9)]
    mesh = Mesh(dst=pts, src=pts, triangles=np.array(tris, np.int32))
    layer = render_mesh(mesh, tex, (h, w, 3))
    x0, y0, x1, y1 = layer.box
    diff = np.abs(layer.rgba.astype(int) - tex[y0:y1, x0:x1].astype(int))
    assert diff[2:-2, 2:-2].mean() < 1.0


def test_mesh_fully_off_screen_renders_nothing(garment) -> None:
    mesh = Mesh(
        dst=np.array([[-50, -50], [-10, -50], [-30, -10]], np.float32),
        src=np.array([[0, 0], [10, 0], [5, 10]], np.float32),
        triangles=np.array([[0, 1, 2]], np.int32),
    )
    assert render_mesh(mesh, garment.texture, (100, 100, 3)) is None


def test_dress_covers_the_legs(garment) -> None:
    pts = standing_points()
    mask = legs_mask(W, H, [180, 260], half=22, top=230, bottom=470)
    frame = np.full((H, W, 3), 255, np.uint8)
    geo = LegTracker().update(make_pose(pts, W, H, mask), W, H)
    out, mesh = dress(frame, geo, garment, Compositor())

    assert mesh is not None
    assert not (frame != 255).any(), "input frame must not be modified"
    legs = (mask > 0) & (np.arange(H)[:, None] > 240) & (np.arange(H)[:, None] < 440)
    covered = (out != 255).any(axis=2)
    assert covered[legs].mean() > 0.97
    # nothing drawn far from the body
    assert not covered[:, :100].any() and not covered[:, 340:].any()


def test_dress_without_geometry_is_passthrough(garment) -> None:
    frame = np.zeros((10, 10, 3), np.uint8)
    out, mesh = dress(frame, None, garment, Compositor())
    assert out is frame and mesh is None


def _square_layer(size: int = 40, color: int = 200) -> Layer:
    rgba = np.zeros((size, size, 4), np.uint8)
    rgba[..., :3] = color
    rgba[..., 3] = 255
    return Layer(rgba, (30, 30, 30 + size, 30 + size))


def test_composite_covers_and_feathers() -> None:
    frame = np.full((100, 100, 3), 100, np.uint8)
    out = Compositor().composite(frame, _square_layer(), SceneMasks(), scale=50)
    center = out[50, 50].astype(int)
    assert (np.abs(center - 200 * np.array([1, 1, 1]) * 1.0) < 40).all()  # garment color (scene exposure may tint it)
    assert (out[5, 5] == 100).all()  # far outside untouched
    edge = out[50, 29:32, 0].astype(int)  # across the left edge: a soft ramp, not a step
    assert edge[0] < edge[1] < edge[2]
    assert not (frame != 100).any(), "input frame must not be modified"


def test_composite_has_no_dark_fringe() -> None:
    """Feathering must not mix in the black of unrendered pixels."""
    frame = np.full((100, 100, 3), 220, np.uint8)
    out = Compositor().composite(frame, _square_layer(color=220), SceneMasks(), scale=50)
    assert out[20:80, 20:80].min() >= 200


def test_occluder_stays_in_front() -> None:
    frame = np.full((100, 100, 3), 30, np.uint8)
    occluder = np.zeros((100, 100), np.uint8)
    occluder[40:60, 40:60] = 1  # a hand over the middle of the garment
    out = Compositor().composite(frame, _square_layer(), SceneMasks(occluder=occluder), scale=50)
    assert abs(int(out[50, 50, 0]) - 30) < 5  # the hand (original frame) shows
    assert out[33, 33, 0] > 120  # garment around it


def test_opacity_fades() -> None:
    frame = np.zeros((100, 100, 3), np.uint8)
    half = Compositor().composite(frame, _square_layer(), SceneMasks(), scale=50, opacity=0.5)
    full = Compositor().composite(frame, _square_layer(), SceneMasks(), scale=50, opacity=1.0)
    assert 0.4 < half[50, 50, 0] / full[50, 50, 0] < 0.6


def test_lighting_follows_skin_brightness() -> None:
    """Skin lit from the left makes the garment brighter on the left."""
    frame = np.zeros((100, 100, 3), np.uint8)
    frame[:, :, :] = np.linspace(60, 200, 100, dtype=np.uint8)[None, :, None]
    skin = np.ones((100, 100), bool)
    out = Compositor().composite(frame, _square_layer(size=40), SceneMasks(skin=skin), scale=50)
    assert out[50, 35, 0] < out[50, 65, 0]


def test_noise_estimate() -> None:
    rng = np.random.default_rng(1)
    flat = np.full((200, 200), 128.0)
    assert estimate_noise(flat) < 0.1
    assert estimate_noise(flat + rng.normal(0, 4, flat.shape)) == pytest.approx(4, rel=0.25)


def test_pyramid_level_matches_screen_size(garment) -> None:
    th, tw = garment.texture.shape[:2]
    full = np.array([[0, 0], [tw, 0], [0, th]], np.float32)
    big = Mesh(dst=full, src=full, triangles=np.array([[0, 1, 2]], np.int32))
    small = Mesh(dst=full / 5, src=full, triangles=np.array([[0, 1, 2]], np.int32))
    assert pick_level(big, len(garment.pyramid)) == 0
    assert pick_level(small, len(garment.pyramid)) == 2  # 5x smaller: level 2 (4x) is the closest larger one


def test_composite_keeps_interior_detail_sharp() -> None:
    """Edge feathering must not blur seams and folds inside the garment."""
    layer = _square_layer(size=40, color=200)
    layer.rgba[:, 20, :3] = 40  # a 1 px dark seam down the middle
    frame = np.full((100, 100, 3), 120, np.uint8)
    out = Compositor().composite(frame, layer, SceneMasks(), scale=100)
    seam, beside = int(out[50, 50, 0]), int(out[50, 52, 0])
    assert beside - seam > 100
