"""Leg joints in pixels plus per-row leg width profiles measured from the body masks.

Legs are named by screen side (left = smaller x at the hip), not by the
person's anatomy, so the garment texture maps the same way whether the person
faces the camera or turns away.

Widths are measured at many points along each thigh and shin, so the pants
follow the real silhouette (skin and clothes), including legs that are wider
or narrower than the skeleton suggests.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from meet_pants.perception.segmenter import Segmentation
from meet_pants.perception.types import Lm, PoseFrame

HIP_VISIBLE = 0.5
CROTCH_DROP = 0.2  # each leg's centerline starts this fraction of the thigh below the hip
# Where the inner seams meet, as a fraction of thigh length below the hips'
# midpoint: measured from the mask, clamped to this range, default otherwise.
CROTCH_DEPTH = (0.15, 0.55)
CROTCH_DEPTH_DEFAULT = 0.25
HEM_EXTEND = 0.08  # hem goes this fraction of the shin past the ankle
WAIST_RISE = 1 / 8  # waist sits this fraction of hip->shoulder above the hip
WAIST_DIP = 0.08  # front of the waistband dips this fraction of waist->crotch below the sides
PROFILE_SAMPLES = 9  # width samples along each thigh and shin
PROFILE_T = np.linspace(0.04, 0.96, PROFILE_SAMPLES)
WIDTH_CLAMP = (0.5, 2.2)  # measured width relative to the skeleton-based prior
WIDTH_EMA = 0.35
# Inward scan this many times longer than the outward one means the legs touch
# and the scan ran into the other leg.
MERGED_RATIO = 2.5
ARM_THICKNESS = 0.45  # forearm/hand cut-out thickness relative to the hip-width base


def unit(v: np.ndarray) -> np.ndarray:
    n = float(np.hypot(*v))
    return v / n if n > 1e-6 else np.array([0.0, 1.0])


def lerp_points(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    return a + (b - a) * t


def outward_normal(direction: np.ndarray, screen_left: bool) -> np.ndarray:
    """Unit normal of a leg bone pointing to the leg's outer side.

    For a leg pointing down, outer is -x on the screen-left leg and +x on the
    right one. Keeping that handedness fixed (instead of comparing against the
    hip line) keeps the normal continuous when a shin swings out sideways and
    runs parallel to the hips.
    """
    d = unit(direction)
    return np.array([-d[1], d[0]]) if screen_left else np.array([d[1], -d[0]])


@dataclass(frozen=True)
class Profile:
    """Half width and center shift (along the outward normal) at PROFILE_T positions."""

    half: np.ndarray
    shift: np.ndarray

    def at(self, t: float) -> tuple[float, float]:
        return float(np.interp(t, PROFILE_T, self.half)), float(np.interp(t, PROFILE_T, self.shift))

    @property
    def median_half(self) -> float:
        return float(np.median(self.half))

    @classmethod
    def constant(cls, half: float, shift: float = 0.0) -> Profile:
        return cls(np.full(PROFILE_SAMPLES, half), np.full(PROFILE_SAMPLES, shift))


@dataclass(frozen=True)
class Leg:
    hip: np.ndarray
    knee: np.ndarray
    ankle: np.ndarray
    waist: np.ndarray
    crotch: np.ndarray  # crotch level on this leg's centerline
    hem: np.ndarray
    outward: np.ndarray  # unit vector along the hip line, away from the other leg
    screen_left: bool
    thigh: Profile  # measured from crotch (t=0) to knee (t=1), no garment ease
    shin: Profile  # knee (t=0) to hem (t=1)

    @property
    def thigh_half(self) -> float:
        return self.thigh.median_half

    @property
    def shin_half(self) -> float:
        return self.shin.median_half

    @property
    def thigh_normal(self) -> np.ndarray:
        return outward_normal(self.knee - self.crotch, self.screen_left)

    @property
    def shin_normal(self) -> np.ndarray:
        return outward_normal(self.hem - self.knee, self.screen_left)

    @property
    def knee_normal(self) -> np.ndarray:
        """Bisector of thigh and shin normals, so a bent knee neither tears nor folds."""
        return unit(self.thigh_normal + self.shin_normal)


@dataclass(frozen=True)
class LegGeometry:
    left: Leg  # screen left
    right: Leg
    waist_mid: np.ndarray
    crotch_mid: np.ndarray
    scale: float  # body size in pixels (about the hip width)
    # Forearms and hands where they overlap the body (uint8 H x W), drawn in
    # front of the pants. None without a body mask.
    arms: np.ndarray | None = None


def scan_profile(
    mask: np.ndarray, a: np.ndarray, b: np.ndarray, normal: np.ndarray, max_r: int, ts: np.ndarray = PROFILE_T
) -> tuple[np.ndarray, np.ndarray]:
    """Half width and center shift of the mask region across segment a->b at each t.

    Scans from each point outward (along `normal`) and inward until leaving
    the mask. The shift is how far the region's center lies from the segment,
    positive toward `normal`. When the inward scan runs much further than the
    outward one, the legs are touching; then only the outward distance is
    trusted and the shift is 0. Points off the frame or off the mask are NaN.
    """
    h, w = mask.shape
    centers = a + ts[:, None] * (b - a)  # (K, 2)
    cx = np.round(centers[:, 0]).astype(int)
    cy = np.round(centers[:, 1]).astype(int)
    usable = (cx >= 0) & (cx < w) & (cy >= 0) & (cy < h)
    usable[usable] = mask[cy[usable], cx[usable]] > 0

    radii = np.arange(1, max_r + 1)

    def distance(sign: float) -> np.ndarray:
        pts = centers[:, None, :] + sign * radii[None, :, None] * normal  # (K, R, 2)
        xs = np.round(pts[..., 0]).astype(int)
        ys = np.round(pts[..., 1]).astype(int)
        valid = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        inside = np.zeros(xs.shape, dtype=bool)
        inside[valid] = mask[ys[valid], xs[valid]] > 0
        # first index that is outside the mask; max_r if the scan never leaves it
        outside = ~inside
        return np.where(outside.any(axis=1), outside.argmax(axis=1), max_r).astype(float)

    d_out, d_in = distance(1.0), distance(-1.0)
    merged = d_in > MERGED_RATIO * d_out
    half = np.where(merged, d_out, (d_out + d_in) / 2)
    shift = np.where(merged, 0.0, (d_out - d_in) / 2)
    half[~usable] = np.nan
    shift[~usable] = np.nan
    return half, shift


def scan_crotch_depth(mask: np.ndarray, start: np.ndarray, direction: np.ndarray, max_r: int) -> float | None:
    """Distance from `start` along `direction` until the mask ends (the gap between
    the legs), or None if the start is off the body or the scan never leaves it."""
    h, w = mask.shape
    pts = start + np.arange(max_r + 1)[:, None] * direction
    xs = np.round(pts[:, 0]).astype(int)
    ys = np.round(pts[:, 1]).astype(int)
    valid = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    if not valid[0]:
        return None
    inside = np.zeros(len(pts), dtype=bool)
    inside[valid] = mask[ys[valid], xs[valid]] > 0
    if not inside[0] or inside.all():
        return None
    return float(np.argmin(inside))


def arm_mask(pose: PoseFrame, width: int, height: int, base: float) -> np.ndarray:
    """uint8 mask of both forearms (elbow to wrist) and hands, from landmarks."""
    mask = np.zeros((height, width), np.uint8)
    thickness = max(2, int(ARM_THICKNESS * base))
    for elbow, wrist, tips in (
        (Lm.LEFT_ELBOW, Lm.LEFT_WRIST, (Lm.LEFT_PINKY, Lm.LEFT_INDEX, Lm.LEFT_THUMB)),
        (Lm.RIGHT_ELBOW, Lm.RIGHT_WRIST, (Lm.RIGHT_PINKY, Lm.RIGHT_INDEX, Lm.RIGHT_THUMB)),
    ):
        pts = [pose.landmarks[i].to_px(width, height) for i in (elbow, wrist, *tips)]
        cv2.line(mask, pts[0], pts[1], 1, thickness)
        cv2.fillConvexPoly(mask, cv2.convexHull(np.array(pts[1:], np.int32)), 1)
        for p in pts[1:]:
            cv2.circle(mask, p, thickness // 2, 1, -1)
    return mask


def body_mask(pose: PoseFrame, segmentation: Segmentation | None, width: int, height: int) -> np.ndarray | None:
    """uint8 union of the pose model's person mask and the segmenter's skin + clothes
    classes, so bare skin always counts as body."""
    masks = []
    if pose.person_mask is not None:
        masks.append(pose.person_mask >= 0.5)
    if segmentation is not None and segmentation.category.shape == (height, width):
        masks.append(segmentation.body)
    if not masks:
        return None
    return np.logical_or.reduce(masks).astype(np.uint8)


class LegTracker:
    """Builds LegGeometry per frame, smoothing measured widths over time."""

    def __init__(self) -> None:
        self._state: dict[str, np.ndarray] = {}

    def reset(self) -> None:
        self._state.clear()

    def _ema(self, key: str, value: np.ndarray) -> np.ndarray:
        previous = self._state.get(key)
        if previous is not None and previous.shape == value.shape:
            value = previous + WIDTH_EMA * (value - previous)
        self._state[key] = value
        return value

    def _profile(self, key: str, measured: tuple[np.ndarray, np.ndarray] | None, prior: float) -> Profile:
        lo, hi = WIDTH_CLAMP
        if measured is None or np.isnan(measured[0]).all():
            half = np.full(PROFILE_SAMPLES, prior)
            shift = np.zeros(PROFILE_SAMPLES)
        else:
            half, shift = measured
            valid = ~np.isnan(half)
            # Off-frame or off-mask samples take the nearest measured value.
            idx = np.arange(PROFILE_SAMPLES)
            half = np.interp(idx, idx[valid], half[valid])
            shift = np.interp(idx, idx[valid], shift[valid])
            # 3-tap median removes single-sample spikes (a finger, a phone in a pocket).
            padded = np.pad(half, 1, mode="edge")
            half = np.median(np.stack([padded[:-2], padded[1:-1], padded[2:]]), axis=0)
            half = np.clip(half, lo * prior, hi * prior)
            shift = np.clip(shift, -0.5 * half, 0.5 * half)
        return Profile(self._ema(f"{key}.half", half), self._ema(f"{key}.shift", shift))

    def update(
        self, pose: PoseFrame, width: int, height: int, segmentation: Segmentation | None = None
    ) -> LegGeometry | None:
        if not pose.landmarks or min(pose.visibility(Lm.LEFT_HIP), pose.visibility(Lm.RIGHT_HIP)) < HIP_VISIBLE:
            self.reset()
            return None

        def px(i: int) -> np.ndarray:
            lm = pose.landmarks[i]
            return np.array([lm.x * width, lm.y * height])

        sides = [
            (px(Lm.LEFT_HIP), px(Lm.LEFT_KNEE), px(Lm.LEFT_ANKLE), px(Lm.LEFT_SHOULDER)),
            (px(Lm.RIGHT_HIP), px(Lm.RIGHT_KNEE), px(Lm.RIGHT_ANKLE), px(Lm.RIGHT_SHOULDER)),
        ]
        sides.sort(key=lambda s: s[0][0])  # screen left first

        hip_l, hip_r = sides[0][0], sides[1][0]
        shoulder_mid = (sides[0][3] + sides[1][3]) / 2
        torso = float(np.hypot(*(shoulder_mid - (hip_l + hip_r) / 2)))
        base = max(float(np.hypot(*(hip_r - hip_l))), 0.35 * torso, 4.0)
        thigh_prior, shin_prior = 0.5 * base, 0.32 * base
        max_r = int(np.ceil(WIDTH_CLAMP[1] * thigh_prior * 2))
        body = body_mask(pose, segmentation, width, height)
        arms = None
        mask = None  # legs are measured on the body without forearms and hands
        if body is not None:
            arm_region = arm_mask(pose, width, height, base)
            arms = body & arm_region
            mask = body & (1 - arm_region)

        legs = []
        for key, (hip, knee, ankle, shoulder), other_hip in (
            ("left", sides[0], hip_r),
            ("right", sides[1], hip_l),
        ):
            outward = unit(hip - other_hip)
            crotch = hip + CROTCH_DROP * (knee - hip)
            hem = ankle + HEM_EXTEND * (ankle - knee)
            screen_left = key == "left"
            thigh_m = shin_m = None
            if mask is not None:
                thigh_m = scan_profile(mask, crotch, knee, outward_normal(knee - crotch, screen_left), max_r)
                shin_m = scan_profile(mask, knee, ankle, outward_normal(hem - knee, screen_left), max_r)
            legs.append(
                Leg(
                    hip=hip,
                    knee=knee,
                    ankle=ankle,
                    waist=hip + WAIST_RISE * (shoulder - hip),
                    crotch=crotch,
                    hem=hem,
                    outward=outward,
                    screen_left=screen_left,
                    thigh=self._profile(f"{key}.thigh", thigh_m, thigh_prior),
                    shin=self._profile(f"{key}.shin", shin_m, shin_prior),
                )
            )

        left, right = legs
        hip_mid = (left.hip + right.hip) / 2
        down = unit((left.knee + right.knee) / 2 - hip_mid)
        thigh_len = (np.hypot(*(left.knee - left.hip)) + np.hypot(*(right.knee - right.hip))) / 2
        lo, hi = CROTCH_DEPTH
        depth = None
        if mask is not None and thigh_len > 1:
            depth = scan_crotch_depth(mask, hip_mid, down, int(hi * thigh_len))
        ratio = CROTCH_DEPTH_DEFAULT if depth is None else float(np.clip(depth / thigh_len, lo, hi))
        ratio = float(self._ema("crotch.depth", np.array([ratio]))[0])
        crotch_mid = hip_mid + down * ratio * thigh_len
        waist_mid = lerp_points((left.waist + right.waist) / 2, crotch_mid, WAIST_DIP)
        return LegGeometry(
            left=left,
            right=right,
            waist_mid=waist_mid,
            crotch_mid=crotch_mid,
            scale=base,
            arms=arms,
        )
