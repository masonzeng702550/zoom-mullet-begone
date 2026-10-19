from __future__ import annotations

import numpy as np
import pytest

from helpers import legs_mask, make_pose, standing_points
from meet_pants.analysis.leg_geometry import (
    CROTCH_DEPTH_DEFAULT,
    LegTracker,
    outward_normal,
    scan_crotch_depth,
    scan_profile,
)
from meet_pants.config import SmoothingConfig
from meet_pants.perception.types import Lm, PoseFrame
from meet_pants.tracking.one_euro import LandmarkSmoother, OneEuroFilter

W, H = 440, 520


# --- One Euro -----------------------------------------------------------------

def test_one_euro_constant_input_is_unchanged() -> None:
    f = OneEuroFilter()
    for i in range(30):
        out = f(np.array([10.0, 20.0]), i / 30)
    np.testing.assert_allclose(out, [10.0, 20.0])


def test_one_euro_reduces_jitter_but_follows_motion() -> None:
    rng = np.random.default_rng(0)
    still = OneEuroFilter(min_cutoff=1.0, beta=0.05)
    noisy = 100 + rng.normal(0, 2.0, 300)
    smooth = np.array([still(np.array([v]), i / 30)[0] for i, v in enumerate(noisy)])
    assert smooth[50:].std() < 0.5 * noisy[50:].std()

    moving = OneEuroFilter(min_cutoff=1.0, beta=0.05)
    ramp = np.arange(60) * 15.0  # 450 px/s
    out = [moving(np.array([v]), i / 30)[0] for i, v in enumerate(ramp)]
    assert ramp[-1] - out[-1] < 15.0  # lags by less than one frame of motion


def test_smoother_resets_when_person_lost() -> None:
    smoother = LandmarkSmoother(SmoothingConfig())
    first = smoother(make_pose({0: (100, 100)}, W, H, t_ms=0), W, H)
    lost = PoseFrame(33, None, None, 1.0)
    assert smoother(lost, W, H) is lost
    # after a reset the next pose is taken as-is, not blended with the old one
    jumped = smoother(make_pose({0: (300, 300)}, W, H, t_ms=66), W, H)
    assert jumped.landmarks[0].x == pytest.approx(300 / W)
    assert first.landmarks[0].x == pytest.approx(100 / W)


# --- leg geometry ---------------------------------------------------------------

def test_outward_normal_points_away() -> None:
    down = np.array([0.0, 1.0])
    np.testing.assert_allclose(outward_normal(down, screen_left=True), [-1.0, 0.0])
    np.testing.assert_allclose(outward_normal(down, screen_left=False), [1.0, 0.0])
    # a screen-right shin kicked out sideways: outer side is the top of the shin
    np.testing.assert_allclose(outward_normal(np.array([1.0, 0.0]), screen_left=False), [0.0, -1.0])


def test_scan_measures_width_and_offset() -> None:
    mask = np.zeros((200, 200), np.uint8)
    mask[:, 80:120] = 1  # 40 px wide strip centered at x=100
    a, b, n = np.array([100.0, 20.0]), np.array([100.0, 180.0]), np.array([-1.0, 0.0])
    half, shift = scan_profile(mask, a, b, n, 100)
    np.testing.assert_allclose(half, 20, atol=1.5)
    np.testing.assert_allclose(shift, 0, atol=1.0)

    # bone line 6 px right of the strip's center: center lies toward -x, i.e. toward n
    half, shift = scan_profile(mask, a + [6, 0], b + [6, 0], n, 100)
    np.testing.assert_allclose(half, 20, atol=1.5)
    np.testing.assert_allclose(shift, 6, atol=1.0)


def test_scan_follows_changing_width() -> None:
    """A leg that widens toward the bottom (e.g. calves) is measured row by row."""
    mask = np.zeros((200, 200), np.uint8)
    for y in range(200):
        half = 10 + y // 10  # 10 px at the top, 29 px at the bottom
        mask[y, 100 - half : 100 + half] = 1
    half, _ = scan_profile(mask, np.array([100.0, 0.0]), np.array([100.0, 199.0]), np.array([-1.0, 0.0]), 100)
    assert half[0] < 13 and half[-1] > 26
    assert (np.diff(half) >= 0).all()


def test_scan_off_body_is_nan() -> None:
    mask = np.zeros((100, 100), np.uint8)
    half, shift = scan_profile(mask, np.array([50.0, 10.0]), np.array([50.0, 90.0]), np.array([1.0, 0.0]), 40)
    assert np.isnan(half).all() and np.isnan(shift).all()


def test_crotch_depth_scan() -> None:
    mask = np.zeros((300, 100), np.float32)
    mask[:150, 40:60] = 1.0
    assert scan_crotch_depth(mask, np.array([50.0, 100.0]), np.array([0.0, 1.0]), 100) == 50
    assert scan_crotch_depth(mask, np.array([50.0, 200.0]), np.array([0.0, 1.0]), 50) is None


def test_geometry_uses_screen_sides_and_measures_legs() -> None:
    pts = standing_points()
    mask = legs_mask(W, H, [180, 260], half=22, top=230, bottom=480)
    geo = LegTracker().update(make_pose(pts, W, H, mask), W, H)

    assert geo is not None
    # anatomical RIGHT hip is at x=180, i.e. screen left
    assert geo.left.hip[0] == pytest.approx(180)
    assert geo.right.hip[0] == pytest.approx(260)
    assert geo.left.outward[0] < 0 < geo.right.outward[0]
    for leg in (geo.left, geo.right):
        assert leg.shin_half == pytest.approx(22, abs=2)
        assert leg.waist[1] < leg.hip[1] < leg.crotch[1] < leg.knee[1]
    # mask gap between the legs starts at y=230, 30 px below the hips
    assert geo.crotch_mid[1] == pytest.approx(230, abs=3)


def test_geometry_same_sides_when_facing_away() -> None:
    pts = standing_points(left_x=180, right_x=260)  # anatomical left now on screen left
    geo = LegTracker().update(make_pose(pts, W, H), W, H)
    assert geo.left.hip[0] == pytest.approx(180)


def test_no_mask_uses_priors() -> None:
    geo = LegTracker().update(make_pose(standing_points(), W, H), W, H)
    thigh_len = 130
    assert geo.crotch_mid[1] == pytest.approx(200 + CROTCH_DEPTH_DEFAULT * thigh_len, abs=1)
    assert geo.left.thigh_half > geo.left.shin_half > 0


def test_hidden_hips_give_no_geometry() -> None:
    assert LegTracker().update(make_pose(standing_points(), W, H, visibility=0.2), W, H) is None
    lost = PoseFrame(0, None, None, 1.0)
    assert LegTracker().update(lost, W, H) is None


def test_wider_leg_is_covered_where_it_is_wider() -> None:
    """One leg with a much wider thigh than the skeleton prior suggests."""
    pts = standing_points()
    mask = legs_mask(W, H, [180, 260], half=22, top=230, bottom=480)
    mask[230:330, 260 - 45 : 260 + 45] = 1.0  # right thigh 90 px wide
    geo = LegTracker().update(make_pose(pts, W, H, mask), W, H)
    assert geo.right.thigh.at(0.5)[0] == pytest.approx(45, abs=3)
    assert geo.left.thigh.at(0.5)[0] == pytest.approx(22, abs=3)


def test_arms_beside_thighs_are_not_measured_as_leg() -> None:
    pts = standing_points()
    pts[Lm.RIGHT_ELBOW] = (150, 180)  # screen-left arm hanging along the screen-left leg
    pts[Lm.RIGHT_WRIST] = (150, 280)
    for tip in (Lm.RIGHT_PINKY, Lm.RIGHT_INDEX, Lm.RIGHT_THUMB):
        pts[tip] = (150, 300)
    mask = legs_mask(W, H, [180, 260], half=22, top=230, bottom=480)
    mask[150:310, 135:165] = 1.0  # the arm, touching the thigh's outer edge
    geo = LegTracker().update(make_pose(pts, W, H, mask), W, H)
    assert geo.left.thigh.at(0.5)[0] < 30


def test_width_is_smoothed_over_time() -> None:
    pts = standing_points()
    tracker = LegTracker()
    tracker.update(make_pose(pts, W, H, legs_mask(W, H, [180, 260], 22, 230, 480)), W, H)
    geo = tracker.update(make_pose(pts, W, H, legs_mask(W, H, [180, 260], 30, 230, 480)), W, H)
    assert 22 < geo.left.shin_half < 30


def test_crotch_scan_that_never_leaves_the_body_is_deep() -> None:
    mask = np.ones((300, 100), np.float32)  # legs together: no gap below the hips
    assert scan_crotch_depth(mask, np.array([50.0, 100.0]), np.array([0.0, 1.0]), 80) == 80
    # running off the bottom of the frame while still on the body is the same
    assert scan_crotch_depth(mask, np.array([50.0, 250.0]), np.array([0.0, 1.0]), 80) == 80


def test_touching_legs_meet_at_the_midline() -> None:
    """Thighs pressed together: each leg must reach the midline, leaving no strip of skin."""
    pts = standing_points(left_x=250, right_x=190)  # centerlines 60 px apart
    mask = np.zeros((H, W), np.float32)
    mask[150:480, 190 - 40 : 250 + 40] = 1.0  # one solid block: no gap between the thighs
    geo = LegTracker().update(make_pose(pts, W, H, mask), W, H)
    for leg in (geo.left, geo.right):
        half, shift = leg.thigh.at(0.5)
        center = leg.crotch[0] + 0.5 * (leg.knee[0] - leg.crotch[0])
        # outward normal is -x for the screen-left leg, +x for the right one
        inner = center + (1 if leg.screen_left else -1) * (half - shift)
        # inner edge reaches x=220 (the midline) from either side
        assert abs(inner - 220) <= 2, (leg.screen_left, inner)
