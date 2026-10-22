"""Draw the README's before/after meme: a Zoom mullet, then the same picture
with pants from the real renderer (assets/zoom-mullet-before-after.png).

The "before" panel is a cartoon drawn here; the "after" panel is that same
image run through LegTracker + dress() with the cartoon's known joints, so
the pants are exactly what the app draws.

    python scripts/make_readme_image.py
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from zoom_mullet_begone.analysis.leg_geometry import LegTracker
from zoom_mullet_begone.perception.types import NUM_LANDMARKS, Landmark, Lm, PoseFrame
from zoom_mullet_begone.pipeline import Wardrobe, dress, scene_masks
from zoom_mullet_begone.render.compositor import Compositor

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "zoom-mullet-before-after.png"
FONTS = Path("/System/Library/Fonts/Supplemental")
IMPACT = FONTS / "Impact.ttf"
BOLD = FONTS / "Arial Bold.ttf"

TILE = (720, 840)  # one video tile, w x h
SS = 3  # supersampling for smooth cartoon edges

SKIN = (236, 188, 150)
SKIN_SHADE = (214, 160, 122)
HAIR = (92, 58, 36)
SHIRT = (231, 238, 248)
SHIRT_SHADE = (200, 212, 230)
TIE = (178, 34, 52)
BOXERS = (238, 86, 104)
BOXER_DOT = (255, 238, 120)
SOCK = (34, 34, 38)
SHOE = (60, 40, 28)
WALL = (214, 222, 216)
WALL_SHADE = (196, 206, 200)
FLOOR = (176, 150, 120)

# Joints in tile pixels (screen left = the person's right).
J = {
    Lm.RIGHT_SHOULDER: (282, 268), Lm.LEFT_SHOULDER: (438, 268),
    Lm.RIGHT_ELBOW: (254, 378), Lm.LEFT_ELBOW: (466, 378),
    Lm.RIGHT_WRIST: (262, 478), Lm.LEFT_WRIST: (458, 478),
    Lm.RIGHT_HIP: (320, 486), Lm.LEFT_HIP: (400, 486),
    Lm.RIGHT_KNEE: (314, 628), Lm.LEFT_KNEE: (406, 628),
    Lm.RIGHT_ANKLE: (316, 762), Lm.LEFT_ANKLE: (404, 762),
}
for wrist, tips in ((Lm.RIGHT_WRIST, (Lm.RIGHT_PINKY, Lm.RIGHT_INDEX, Lm.RIGHT_THUMB)),
                    (Lm.LEFT_WRIST, (Lm.LEFT_PINKY, Lm.LEFT_INDEX, Lm.LEFT_THUMB))):
    x, y = J[wrist]
    for i, tip in enumerate(tips):
        J[tip] = (x + (i - 1) * 6, y + 22)
J[Lm.NOSE] = (360, 168)


def s(*v: float) -> list[float]:
    return [c * SS for c in v]


def leg(d: ImageDraw.ImageDraw, top: tuple, knee: tuple, ankle: tuple, half_top: float, half_knee: float, half_ankle: float, color) -> None:
    """A leg as a tapered polygon plus round joints."""
    pts = []
    for (x, y), h in ((top, half_top), (knee, half_knee), (ankle, half_ankle)):
        pts.append((x - h, y))
    for (x, y), h in reversed(((top, half_top), (knee, half_knee), (ankle, half_ankle))):
        pts.append((x + h, y))
    d.polygon([tuple(s(*p)) for p in pts], fill=color)
    kx, ky = knee
    d.ellipse(s(kx - half_knee, ky - half_knee, kx + half_knee, ky + half_knee), fill=color)


def draw_person(d: ImageDraw.ImageDraw) -> None:
    rs, ls = J[Lm.RIGHT_SHOULDER], J[Lm.LEFT_SHOULDER]
    rh, lh = J[Lm.RIGHT_HIP], J[Lm.LEFT_HIP]
    # legs (skin) with socks and shoes
    for hip, knee, ankle in ((rh, J[Lm.RIGHT_KNEE], J[Lm.RIGHT_ANKLE]), (lh, J[Lm.LEFT_KNEE], J[Lm.LEFT_ANKLE])):
        leg(d, (hip[0], hip[1] + 10), knee, ankle, 30, 25, 18, SKIN)
        ax, ay = ankle
        d.rounded_rectangle(s(ax - 19, ay - 40, ax + 19, ay + 6), radius=8 * SS, fill=SOCK)
        toe = 1 if ax > 360 else -1
        d.rounded_rectangle(s(min(ax, ax + toe * 46) - 20, ay - 2, max(ax, ax + toe * 46) + 20, ay + 26), radius=12 * SS, fill=SHOE)
        # a few leg hairs
        for i in range(7):
            hx = knee[0] - 14 + i * 5
            hy = knee[1] + 20 + (i % 3) * 18
            d.line(s(hx, hy, hx + 3, hy - 6), fill=SKIN_SHADE, width=2 * SS)
    # boxers: shorts that end mid-thigh, polka dots
    d.polygon([tuple(s(*p)) for p in (
        (rs[0] + 12, 452), (ls[0] - 12, 452), (lh[0] + 44, 572), (371, 572), (360, 530), (349, 572), (rh[0] - 44, 572),
    )], fill=BOXERS)
    rng = np.random.default_rng(7)
    for _ in range(26):
        x, y = rng.uniform(rh[0] - 30, lh[0] + 30), rng.uniform(462, 562)
        d.ellipse(s(x - 5, y - 5, x + 5, y + 5), fill=BOXER_DOT)
    # torso: shirt and tie
    d.polygon([tuple(s(*p)) for p in (
        (rs[0] - 6, rs[1]), (ls[0] + 6, ls[1]), (ls[0] - 8, 488), (360, 494), (rs[0] + 8, 488),
    )], fill=SHIRT)
    d.line(s(360, 258, 360, 490), fill=SHIRT_SHADE, width=3 * SS)  # placket
    for by in range(300, 450, 34):
        d.ellipse(s(354, by, 366, by + 12), fill=SHIRT_SHADE)
    d.polygon([tuple(s(*p)) for p in ((342, 250), (378, 250), (360, 276))], fill=SHIRT_SHADE)  # collar shadow
    d.polygon([tuple(s(*p)) for p in ((352, 266), (368, 266), (374, 300), (360, 400), (346, 300))], fill=TIE)
    d.polygon([tuple(s(*p)) for p in ((350, 254), (370, 254), (366, 270), (354, 270))], fill=(150, 24, 40))  # knot
    d.polygon([tuple(s(*p)) for p in ((330, 246), (356, 262), (342, 282))], fill=SHIRT)  # collar points
    d.polygon([tuple(s(*p)) for p in ((390, 246), (364, 262), (378, 282))], fill=SHIRT)
    # arms (sleeves) and hands
    for shoulder, elbow, wrist in ((rs, J[Lm.RIGHT_ELBOW], J[Lm.RIGHT_WRIST]), (ls, J[Lm.LEFT_ELBOW], J[Lm.LEFT_WRIST])):
        d.line(s(*shoulder, *elbow), fill=SHIRT, width=46 * SS, joint="curve")
        d.line(s(*elbow, *wrist), fill=SHIRT, width=40 * SS, joint="curve")
        d.ellipse(s(elbow[0] - 22, elbow[1] - 22, elbow[0] + 22, elbow[1] + 22), fill=SHIRT)
        d.ellipse(s(wrist[0] - 22, wrist[1] - 8, wrist[0] + 22, wrist[1] + 10), fill=SHIRT_SHADE)  # cuff
        d.ellipse(s(wrist[0] - 17, wrist[1] + 2, wrist[0] + 17, wrist[1] + 40), fill=SKIN)  # hand
    for shoulder in (rs, ls):
        d.ellipse(s(shoulder[0] - 26, shoulder[1] - 22, shoulder[0] + 26, shoulder[1] + 30), fill=SHIRT)
    # neck and head with a proper mullet
    d.rectangle(s(344, 214, 376, 256), fill=SKIN_SHADE)
    # the party in the back: long hair behind the neck, flaring onto the shoulders
    d.polygon([tuple(s(*p)) for p in (
        (322, 190), (398, 190), (404, 236), (418, 262), (436, 284), (412, 280), (398, 270), (360, 262),
        (322, 270), (308, 280), (284, 284), (302, 262), (316, 236),
    )], fill=HAIR)
    d.ellipse(s(306, 104, 414, 230), fill=SKIN)
    d.chord(s(304, 96, 416, 176), 180, 360, fill=HAIR)  # business on top: short and neat
    d.polygon([tuple(s(*p)) for p in ((306, 136), (318, 136), (316, 158), (306, 150))], fill=HAIR)  # short sideburns
    d.polygon([tuple(s(*p)) for p in ((414, 136), (402, 136), (404, 158), (414, 150))], fill=HAIR)
    for k in range(5):  # a little spike on top
        x = 336 + k * 12
        d.polygon([tuple(s(*p)) for p in ((x, 102), (x + 10, 86 + (k % 2) * 6), (x + 16, 104))], fill=HAIR)
    d.ellipse(s(298, 152, 316, 186), fill=SKIN)  # ears
    d.ellipse(s(404, 152, 422, 186), fill=SKIN)
    # face: confident meeting smile
    for ex in (338, 382):
        d.ellipse(s(ex - 6, 160, ex + 6, 172), fill=(40, 30, 30))
    d.line(s(326, 148, 348, 150), fill=HAIR, width=4 * SS)
    d.line(s(372, 150, 394, 148), fill=HAIR, width=4 * SS)
    d.arc(s(336, 172, 384, 206), 15, 165, fill=(140, 60, 60), width=4 * SS)


def background(d: ImageDraw.ImageDraw) -> None:
    w, h = TILE
    d.rectangle(s(0, 0, w, 700), fill=WALL)
    d.rectangle(s(0, 700, w, h), fill=FLOOR)
    # bookshelf, plant and a framed "motivational" poster
    d.rectangle(s(36, 220, 196, 640), fill=WALL_SHADE)
    for row, y in enumerate(range(240, 640, 80)):
        x = 48
        for k in range(6):
            bw = 14 + (row * 7 + k * 5) % 12
            color = [(120, 80, 60), (70, 100, 140), (150, 120, 70), (90, 120, 90), (160, 90, 90)][(row + k) % 5]
            d.rectangle(s(x, y + 12, x + bw, y + 70), fill=color)
            x += bw + 4
        d.rectangle(s(36, y + 70, 196, y + 78), fill=(150, 125, 100))
    d.rectangle(s(560, 120, 676, 250), fill=(250, 250, 248), outline=(120, 110, 100), width=6 * SS)
    d.polygon([tuple(s(*p)) for p in ((578, 230), (612, 160), (634, 196), (650, 176), (662, 230))], fill=(120, 160, 190))
    d.rounded_rectangle(s(580, 590, 650, 700), radius=10 * SS, fill=(190, 110, 70))
    for k, (dx, dy) in enumerate(((-30, -80), (0, -110), (30, -86), (-12, -60), (18, -64))):
        d.ellipse(s(615 + dx - 22, 590 + dy - 34, 615 + dx + 22, 590 + dy + 34), fill=(70 + k * 8, 140, 80))


def text_outline(d: ImageDraw.ImageDraw, xy, text: str, font, fill=(255, 255, 255), stroke=(0, 0, 0), anchor="mm", width=6) -> None:
    d.text(xy, text, font=font, fill=fill, stroke_width=width, stroke_fill=stroke, anchor=anchor)


def tile_image() -> tuple[np.ndarray, np.ndarray]:
    """The cartoon (BGR) and its person mask (float32, legs + boxers + body)."""
    w, h = TILE
    img = Image.new("RGB", (w * SS, h * SS))
    d = ImageDraw.Draw(img)
    background(d)
    draw_person(d)
    small = img.resize((w, h), Image.LANCZOS)
    # person mask: draw the person alone over black
    m = Image.new("RGB", (w * SS, h * SS))
    draw_person(ImageDraw.Draw(m))
    mask = (np.asarray(m.resize((w, h), Image.LANCZOS)).max(axis=2) > 8).astype(np.float32)
    return cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2BGR), mask


def with_pants(frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    landmarks = []
    for i in range(NUM_LANDMARKS):
        x, y = J.get(i, (-500, -500))
        landmarks.append(Landmark(x / w, y / h, 0.0, 0.99 if i in J else 0.0, 0.99))
    pose = PoseFrame(0, tuple(landmarks), mask, 0.0)
    geometry = LegTracker().update(pose, w, h, None)
    garment = Wardrobe(ROOT / "garments", "dress_navy").current
    out, _ = dress(frame, geometry, garment, Compositor(), scene_masks(pose, None, geometry))
    return out


def chrome(tile: Image.Image, title: str, caption: str, crop_line: bool) -> Image.Image:
    """Video-call tile look: rounded corners, name tag, meme captions top and bottom."""
    w, h = tile.size
    d = ImageDraw.Draw(tile)
    impact_big = ImageFont.truetype(str(IMPACT), 64)
    impact = ImageFont.truetype(str(IMPACT), 44)
    label = ImageFont.truetype(str(BOLD), 22)
    small = ImageFont.truetype(str(BOLD), 18)
    if crop_line:  # where a laptop camera's picture usually ends
        y = 430
        for x in range(0, w, 28):
            d.line((x, y, x + 16, y), fill=(255, 255, 255), width=4)
        for dy, text in ((-22, "what your camera shows ↑"), (22, "what it doesn't ↓")):
            box = d.textbbox((0, 0), text, font=small)
            tw = box[2] - box[0]
            d.rounded_rectangle((20, y + dy - 14, 20 + tw + 24, y + dy + 14), radius=6, fill=(32, 33, 36))
            d.text((32, y + dy), text, font=small, fill=(232, 234, 237), anchor="lm")
    text_outline(d, (w // 2, 58), title, impact_big)
    text_outline(d, (w // 2, h - 100), caption, impact, width=5)
    # name tag and mic badge like a meeting tile
    d.rounded_rectangle((16, h - 56, 140, h - 16), radius=8, fill=(32, 33, 36))
    d.text((32, h - 36), "You", font=label, fill=(232, 234, 237), anchor="lm")
    d.ellipse((w - 60, h - 60, w - 16, h - 16), fill=(32, 33, 36))
    d.rounded_rectangle((w - 44, h - 50, w - 32, h - 32), radius=6, fill=(232, 234, 237))
    d.arc((w - 50, h - 42, w - 26, h - 26), 0, 180, fill=(232, 234, 237), width=3)
    rounded = Image.new("L", (w, h), 0)
    ImageDraw.Draw(rounded).rounded_rectangle((0, 0, w - 1, h - 1), radius=26, fill=255)
    tile.putalpha(rounded)
    return tile


def main() -> None:
    before, mask = tile_image()
    after = with_pants(before, mask)
    panels = [
        chrome(Image.fromarray(cv2.cvtColor(before, cv2.COLOR_BGR2RGB)), "THE ZOOM MULLET", "BUSINESS ON TOP, PARTY BELOW", True),
        chrome(Image.fromarray(cv2.cvtColor(after, cv2.COLOR_BGR2RGB)), "ZOOM MULLET BEGONE", "BUSINESS ALL THE WAY DOWN", False),
    ]
    gap, pad, foot = 40, 36, 64
    W = pad * 2 + TILE[0] * 2 + gap
    H = pad + TILE[1] + foot
    canvas = Image.new("RGBA", (W, H), (32, 33, 36, 255))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for i, panel in enumerate(panels):
        x = pad + i * (TILE[0] + gap)
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle((x + 4, pad + 8, x + TILE[0] + 4, pad + TILE[1] + 8), radius=26, fill=(0, 0, 0, 140))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(10)))
    for i, panel in enumerate(panels):
        canvas.alpha_composite(panel, (pad + i * (TILE[0] + gap), pad))
    d = ImageDraw.Draw(canvas)
    arrow_font = ImageFont.truetype(str(IMPACT), 56)
    text_outline(d, (W // 2, pad + TILE[1] // 2), "→", arrow_font, width=6)
    foot_font = ImageFont.truetype(str(BOLD), 24)
    d.text((W // 2, pad + TILE[1] + foot // 2 + 4), "Right panel: pants drawn by Zoom Mullet Begone's own renderer", font=foot_font, fill=(189, 193, 198), anchor="mm")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(OUT, optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e3:.0f} KB, {W}x{H})")


if __name__ == "__main__":
    main()
