"""Export the garments for the in-browser demo (site/garments/).

The web page cannot read garment.yaml + a 1024x1536 PNG cheaply, so each
garment becomes a half-size WebP texture plus a JSON file with the anchors
scaled to match. Re-run after changing the garments:

    python scripts/export_web_garments.py
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from zoom_mullet_begone.render.garment import LEG_ANCHORS, list_garments, load_garment

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "garments"
SCALE = 0.5
WEBP_QUALITY = 90


def pt(p: np.ndarray) -> list[float]:
    return [round(float(p[0]) * SCALE, 2), round(float(p[1]) * SCALE, 2)]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for gid in list_garments(ROOT / "garments"):
        g = load_garment(ROOT / "garments", gid)
        h, w = g.texture.shape[:2]
        small = cv2.resize(g.texture, (round(w * SCALE), round(h * SCALE)), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(OUT / f"{gid}.webp"), small, [cv2.IMWRITE_WEBP_QUALITY, WEBP_QUALITY])
        spec = {
            "id": gid,
            "name": g.name,
            "ease": g.ease,
            "texture": f"{gid}.webp",
            "size": [small.shape[1], small.shape[0]],
            "waist_mid": pt(g.waist_mid),
            "crotch": pt(g.crotch),
            "left": {k: pt(getattr(g.left, k)) for k in LEG_ANCHORS},
            "right": {k: pt(getattr(g.right, k)) for k in LEG_ANCHORS},
            "mesh": {"waist_rows": g.waist_rows, "along": g.along, "across": g.across},
            "trim": [
                {"kind": t.kind, "points": [pt(p) for p in t.points], "color": list(t.color) if t.color else None}
                for t in g.trim
            ],
        }
        (OUT / f"{gid}.json").write_text(json.dumps(spec, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index.append({"id": gid, "name": g.name})
        print(f"{gid}: {(OUT / f'{gid}.webp').stat().st_size / 1e3:.0f} KB")
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
