"""Blends the rendered garment into the camera frame so it looks filmed, not pasted.

- feathered edges (premultiplied, so no dark fringe)
- local lighting taken from the person's skin around the legs
- scene exposure and white balance
- camera noise matched to the frame
- forearms and hands stay in front of the pants
- fade-in opacity
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from meet_pants.render.warp_cv import Layer

LIGHT_GAMMA = 0.6  # how strongly local skin brightness modulates the garment
LIGHT_RANGE = (0.6, 1.35)
# Scale (relative to body size) at which skin lighting is sampled: small enough
# to carry the leg's own form shading onto the fabric, large enough to ignore
# skin texture and hair.
LIGHT_SIGMA = 0.25
EXPOSURE_RANGE = (0.85, 1.1)
WHITE_BALANCE_RANGE = (0.95, 1.05)
MID_GRAY = 0.45
NOISE_MAX = 8.0  # largest camera noise sigma we try to match, in 0..255 units
STATS_EMA = 0.15
NOISE_EVERY = 15  # frames between camera-noise estimates
LIGHT_DOWNSCALE = 4


@dataclass(frozen=True)
class SceneMasks:
    skin: np.ndarray | None = None  # bool H x W, bare skin (lighting reference)
    body: np.ndarray | None = None  # uint8/bool H x W, lighting fallback when no skin is visible
    occluder: np.ndarray | None = None  # uint8 H x W, things in front of the pants (arms)


def _blur(img: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(img, (0, 0), sigma, borderType=cv2.BORDER_REPLICATE)


def _pad_layer(layer: Layer, pad: int, frame_shape: tuple[int, ...]) -> Layer:
    """Grow the layer box by `pad` (within the frame) so feathering is not cut off."""
    h, w = frame_shape[:2]
    x0, y0, x1, y1 = layer.box
    nx0, ny0, nx1, ny1 = max(x0 - pad, 0), max(y0 - pad, 0), min(x1 + pad, w), min(y1 + pad, h)
    rgba = np.pad(layer.rgba, ((y0 - ny0, ny1 - y1), (x0 - nx0, nx1 - x1), (0, 0)))
    return Layer(rgba, (nx0, ny0, nx1, ny1))


def estimate_noise(gray: np.ndarray) -> float:
    """Camera noise sigma (0..255) from the Laplacian's median absolute value.

    For the 4-neighbour Laplacian, pure noise of sigma s gives a response with
    standard deviation s * sqrt(20). The median keeps edges from dominating.
    """
    lap = cv2.Laplacian(gray.astype(np.float32), cv2.CV_32F, ksize=1)
    return float(np.median(np.abs(lap)) * 1.4826 / np.sqrt(20))


def local_light(
    frame_gray: np.ndarray, weight: np.ndarray, sigma: float
) -> np.ndarray | None:
    """Smooth brightness of the weighted pixels (normalized convolution), or None.

    Computed at reduced resolution; the result is upscaled to the input size.
    """
    if not weight.any():
        return None
    h, w = frame_gray.shape
    sw, sh = max(1, w // LIGHT_DOWNSCALE), max(1, h // LIGHT_DOWNSCALE)
    g = cv2.resize(frame_gray, (sw, sh), interpolation=cv2.INTER_AREA)
    wt = cv2.resize(weight.astype(np.float32), (sw, sh), interpolation=cv2.INTER_AREA)
    s = max(sigma / LIGHT_DOWNSCALE, 1.0)
    num, den = _blur(g * wt, s), _blur(wt, s)
    light = np.where(den > 1e-3, num / np.maximum(den, 1e-3), np.nan)
    if np.isnan(light).all():
        return None
    light = np.where(np.isnan(light), np.nanmean(light), light).astype(np.float32)
    return cv2.resize(light, (w, h), interpolation=cv2.INTER_LINEAR)


class Compositor:
    def __init__(self, seed: int = 0):
        rng = np.random.default_rng(seed)
        self._noise = rng.standard_normal((512, 512)).astype(np.float32)
        self._rng = rng
        self._exposure: float | None = None
        self._white_balance: np.ndarray | None = None
        self._noise_sigma: float | None = None
        self._calls = 0

    def _ema(self, old, new):
        return new if old is None else old + STATS_EMA * (new - old)

    def _scene_color(self, frame: np.ndarray) -> tuple[float, np.ndarray]:
        step = max(1, min(frame.shape[:2]) // 48)
        means = frame[::step, ::step].reshape(-1, 3).mean(axis=0) / 255
        luma = float(means @ np.array([0.114, 0.587, 0.299]))
        exposure = float(np.clip(np.sqrt(max(luma, 1e-3) / MID_GRAY), *EXPOSURE_RANGE))
        # gray world, softened (square root) so a blue sky does not turn the pants orange
        wb = np.clip(np.sqrt(means.mean() / np.maximum(means, 1e-3)), *WHITE_BALANCE_RANGE)
        self._exposure = self._ema(self._exposure, exposure)
        self._white_balance = self._ema(self._white_balance, wb)
        return self._exposure, self._white_balance

    def _noise_patch(self, h: int, w: int) -> np.ndarray:
        """A fresh-looking h x w noise field: the fixed tile at a random offset."""
        th, tw = self._noise.shape
        oy, ox = int(self._rng.integers(0, th)), int(self._rng.integers(0, tw))
        tile = np.tile(self._noise, ((oy + h) // th + 1, (ox + w) // tw + 1))
        return tile[oy : oy + h, ox : ox + w]

    def composite(
        self,
        frame: np.ndarray,
        layer: Layer,
        masks: SceneMasks,
        scale: float,
        opacity: float = 1.0,
    ) -> np.ndarray:
        """Blend `layer` over a copy of `frame`. `scale` is the body size in pixels."""
        feather = float(np.clip(scale * 0.02, 0.7, 2.0))
        layer = _pad_layer(layer, int(np.ceil(3 * feather)) + 1, frame.shape)
        x0, y0, x1, y1 = layer.box
        region = frame[y0:y1, x0:x1].astype(np.float32)

        rgba = layer.rgba.astype(np.float32)
        sharp_alpha = rgba[..., 3] / 255.0
        rgb = rgba[..., :3]
        # Feather only the silhouette. Pixels outside the garment get their color
        # from the blurred premultiplied image (no dark fringe); the interior keeps
        # the sharp texture so seams and folds survive.
        alpha = _blur(sharp_alpha, feather)
        spread = _blur(rgb * sharp_alpha[..., None], feather) / np.maximum(alpha, 1e-3)[..., None]
        rgb = np.where((sharp_alpha > 0.5)[..., None], rgb, spread)

        gray = cv2.cvtColor(region.astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32) / 255

        # local light: brightness of nearby skin (or body) relative to its mean under the pants
        weight = None
        if masks.skin is not None:
            weight = masks.skin[y0:y1, x0:x1]
        if (weight is None or not weight.any()) and masks.body is not None:
            weight = masks.body[y0:y1, x0:x1] > 0
        if weight is not None:
            light = local_light(gray, weight, sigma=LIGHT_SIGMA * scale)
            covered = alpha > 0.5
            if light is not None and covered.any():
                ref = float(light[covered].mean())
                shade = np.clip((light / max(ref, 1e-3)) ** LIGHT_GAMMA, *LIGHT_RANGE)
                rgb *= shade[..., None]

        exposure, wb = self._scene_color(frame)
        rgb *= exposure * wb

        if self._noise_sigma is None or self._calls % NOISE_EVERY == 0:
            self._noise_sigma = self._ema(self._noise_sigma, min(estimate_noise(gray * 255), NOISE_MAX))
        self._calls += 1
        sigma = self._noise_sigma
        if sigma > 0.3:
            rgb += (self._noise_patch(*rgb.shape[:2]) * sigma)[..., None]

        if masks.occluder is not None:
            occ = _blur(masks.occluder[y0:y1, x0:x1].astype(np.float32), feather)
            alpha *= 1.0 - np.clip(occ, 0, 1)
        alpha *= float(np.clip(opacity, 0, 1))

        out = frame.copy()
        a = alpha[..., None]
        out[y0:y1, x0:x1] = np.clip(rgb * a + region * (1.0 - a), 0, 255).astype(np.uint8)
        return out
