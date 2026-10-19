from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from meet_pants.config import DEFAULT_GARMENTS_DIR
from meet_pants.render.garment import GarmentError, TrimLine, load_garment
from meet_pants.render.mesh import Mesh
from meet_pants.render.trim import draw_trim, map_points, resample
from meet_pants.render.warp_cv import Layer


def square_mesh(offset=(0.0, 0.0), scale: float = 1.0) -> Mesh:
    """Texture square 0..100 mapped to a frame square at `offset`, scaled."""
    src = np.array([[0, 0], [100, 0], [0, 100], [100, 100]], np.float32)
    return Mesh(dst=src * scale + np.array(offset, np.float32), src=src, triangles=np.array([[0, 1, 2], [1, 3, 2]], np.int32))


def test_resample_keeps_ends_and_limits_spacing() -> None:
    pts = resample(np.array([[0.0, 0.0], [100.0, 0.0]]), step=12)
    assert np.allclose(pts[0], [0, 0]) and np.allclose(pts[-1], [100, 0])
    assert np.diff(pts[:, 0]).max() <= 12


def test_map_points_through_mesh() -> None:
    mesh = square_mesh(offset=(10, 20), scale=2.0)
    mapped, found = map_points(mesh, np.array([[50.0, 50.0], [0.0, 100.0], [150.0, 50.0]]))
    assert found.tolist() == [True, True, False]
    np.testing.assert_allclose(mapped[:2], [[110, 120], [10, 220]], atol=1e-6)


def test_seam_darkens_along_its_path() -> None:
    mesh = square_mesh()
    rgba = np.full((101, 101, 4), 200, np.uint8)
    layer = Layer(rgba, (0, 0, 101, 101))
    draw_trim(layer, mesh, (TrimLine("seam", np.array([[50.0, 10.0], [50.0, 90.0]])),), scale=60)
    assert layer.rgba[50, 50, 0] < 160  # on the seam
    assert layer.rgba[50, 20, 0] == 200  # away from it


def test_stitch_is_dashed_and_colored() -> None:
    mesh = square_mesh(scale=3.0)
    rgba = np.full((301, 301, 4), 100, np.uint8)
    layer = Layer(rgba, (0, 0, 301, 301))
    draw_trim(layer, mesh, (TrimLine("stitch", np.array([[5.0, 50.0], [95.0, 50.0]]), (0, 0, 255)),), scale=100)
    row = layer.rgba[150, 20:280, 2].astype(int)
    colored = row > 180
    assert colored.any() and not colored.all()  # dashes with gaps


def test_builtin_garments_have_trim() -> None:
    for gid in ("dress_navy", "chino_khaki", "jeans_indigo"):
        g = load_garment(DEFAULT_GARMENTS_DIR, gid)
        kinds = {line.kind for line in g.trim}
        assert {"seam", "edge"} <= kinds
    assert any(line.kind == "crease" for line in load_garment(DEFAULT_GARMENTS_DIR, "dress_navy").trim)
    assert any(line.kind == "stitch" for line in load_garment(DEFAULT_GARMENTS_DIR, "jeans_indigo").trim)


@pytest.mark.parametrize(
    "trim, message",
    [
        ([{"kind": "zigzag", "points": [[0, 0], [1, 1]]}], "kind must be one of"),
        ([{"kind": "seam", "points": [[0, 0]]}], "at least 2 points"),
        ([{"kind": "seam"}], "points must be"),
    ],
)
def test_invalid_trim_is_rejected(tmp_path: Path, trim: list, message: str) -> None:
    src = DEFAULT_GARMENTS_DIR / "dress_navy"
    dst = tmp_path / "bad"
    dst.mkdir()
    (dst / "texture.png").write_bytes((src / "texture.png").read_bytes())
    spec = yaml.safe_load((src / "garment.yaml").read_text(encoding="utf-8"))
    spec["trim"] = trim
    (dst / "garment.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    with pytest.raises(GarmentError, match=message):
        load_garment(tmp_path, "bad")
