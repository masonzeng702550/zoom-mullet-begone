"""Fallback pose: YOLOX person detector + RTMPose body-with-feet (Halpe-26), via onnxruntime.

MediaPipe needs most of the torso in view to find a person. When someone sits
close to the camera only the waist and legs are visible and MediaPipe returns
nothing; these OpenMMLab models (Apache-2.0) still find hips, knees and feet.

Pre/post-processing follows rtmlib (which is not a dependency: it pulls in
opencv-python, which would overwrite mediapipe's opencv-contrib-python).

The 26 keypoints are mapped onto MediaPipe's 33 so everything downstream stays
the same. Points the model is unsure about are replaced with estimates that
keep the leg geometry sane: shoulders above the hips, unseen arms parked at the
shoulders (so they never cut a hole in the pants).
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

from meet_pants.perception.types import NUM_LANDMARKS, Landmark, Lm, PoseFrame

DETECTOR_INPUT = (416, 416)  # (w, h)
POSE_INPUT = (192, 256)  # (w, h)
POSE_MEAN = np.array([123.675, 116.28, 103.53])
POSE_STD = np.array([58.395, 57.12, 57.375])
SIMCC_SPLIT = 2.0
BOX_PADDING = 1.25
DETECTOR_SCORE = 0.3
DETECT_EVERY = 10  # frames between person-detector runs; in between the box follows the keypoints
SHOULDER_SCORE = 0.5  # below this the shoulders are estimated from the hips
ARM_SCORE = 0.3  # below this an elbow / wrist is moved to its shoulder
# A knee or ankle below this score, or within EDGE_FRAC of the frame border,
# is taken as out of view: the model pins such points at the edge of its crop,
# which makes the leg look far too short. They are extended off-screen instead.
LEG_SCORE = 0.5
EDGE_FRAC = 0.02
THIGH_PER_HIP = 2.0  # thigh length relative to the hip keypoint distance
SHIN_PER_THIGH = 0.95
ONNX_THREADS = 2  # 1 thread: less CPU but ~18 ms per frame, too slow next to MediaPipe at 30 fps

# Halpe-26 index -> MediaPipe indices it fills.
HALPE_TO_MP: dict[int, tuple[int, ...]] = {
    0: (Lm.NOSE, 9, 10),  # mouth corners have no Halpe counterpart
    1: (1, Lm.LEFT_EYE, 3),
    2: (4, Lm.RIGHT_EYE, 6),
    3: (7,),
    4: (8,),
    5: (Lm.LEFT_SHOULDER,),
    6: (Lm.RIGHT_SHOULDER,),
    7: (Lm.LEFT_ELBOW,),
    8: (Lm.RIGHT_ELBOW,),
    9: (Lm.LEFT_WRIST, Lm.LEFT_PINKY, Lm.LEFT_INDEX, Lm.LEFT_THUMB),
    10: (Lm.RIGHT_WRIST, Lm.RIGHT_PINKY, Lm.RIGHT_INDEX, Lm.RIGHT_THUMB),
    11: (Lm.LEFT_HIP,),
    12: (Lm.RIGHT_HIP,),
    13: (Lm.LEFT_KNEE,),
    14: (Lm.RIGHT_KNEE,),
    15: (Lm.LEFT_ANKLE,),
    16: (Lm.RIGHT_ANKLE,),
    20: (Lm.LEFT_FOOT_INDEX,),  # big toe
    21: (Lm.RIGHT_FOOT_INDEX,),
    24: (Lm.LEFT_HEEL,),
    25: (Lm.RIGHT_HEEL,),
}


def _session(path: Path) -> ort.InferenceSession:
    options = ort.SessionOptions()
    options.log_severity_level = 3
    # By default onnxruntime uses every core and keeps its threads spinning
    # between runs: ~80 ms of CPU for an 11 ms inference. Two threads that
    # sleep when idle cost about as much CPU as the inference takes.
    options.intra_op_num_threads = ONNX_THREADS
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])


def _warp_matrix(center: np.ndarray, size: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """Affine map from the box (center, size) onto an out_w x out_h image (no rotation)."""
    sx, sy = out_w / size[0], out_h / size[1]
    return np.array([[sx, 0, out_w / 2 - sx * center[0]], [0, sy, out_h / 2 - sy * center[1]]])


class RtmPoseDetector:
    def __init__(self, detector_path: Path, pose_path: Path):
        self._detector = _session(detector_path)
        self._pose = _session(pose_path)
        self._box: np.ndarray | None = None  # xyxy
        self._frames_since_detect = 0

    def reset(self) -> None:
        self._box = None

    def detect_person(self, bgr: np.ndarray) -> np.ndarray | None:
        """Most confident person box (xyxy pixels), or None."""
        h, w = bgr.shape[:2]
        in_w, in_h = DETECTOR_INPUT
        ratio = min(in_w / w, in_h / h)
        padded = np.full((in_h, in_w, 3), 114, np.uint8)
        rw, rh = int(w * ratio), int(h * ratio)
        padded[:rh, :rw] = cv2.resize(bgr, (rw, rh), interpolation=cv2.INTER_LINEAR)
        blob = padded.transpose(2, 0, 1)[None].astype(np.float32)
        dets = self._detector.run(None, {self._detector.get_inputs()[0].name: blob})[0][0]
        if len(dets) == 0:
            return None
        best = dets[np.argmax(dets[:, 4])]
        if best[4] <= DETECTOR_SCORE:
            return None
        return best[:4] / ratio

    def keypoints(self, bgr: np.ndarray, box: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(26, 2) pixel keypoints and (26,) scores for the person in `box`."""
        out_w, out_h = POSE_INPUT
        center = (box[:2] + box[2:]) / 2
        size = (box[2:] - box[:2]) * BOX_PADDING
        aspect = out_w / out_h  # grow the box to the model's aspect ratio
        if size[0] > size[1] * aspect:
            size = np.array([size[0], size[0] / aspect])
        else:
            size = np.array([size[1] * aspect, size[1]])
        crop = cv2.warpAffine(bgr, _warp_matrix(center, size, out_w, out_h), (out_w, out_h), flags=cv2.INTER_LINEAR)
        blob = ((crop - POSE_MEAN) / POSE_STD).transpose(2, 0, 1)[None].astype(np.float32)
        simcc_x, simcc_y = self._pose.run(None, {self._pose.get_inputs()[0].name: blob})
        simcc_x, simcc_y = simcc_x[0], simcc_y[0]
        locs = np.stack([simcc_x.argmax(axis=1), simcc_y.argmax(axis=1)], axis=1) / SIMCC_SPLIT
        scores = (simcc_x.max(axis=1) + simcc_y.max(axis=1)) / 2
        points = locs / np.array([out_w, out_h]) * size + center - size / 2
        return points, scores

    def _track_box(self, points: np.ndarray, scores: np.ndarray) -> None:
        """Move the last detector box with the confident keypoints until the next detection."""
        sure = scores >= ARM_SCORE
        if self._box is None or sure.sum() < 4:
            self._box = None
            return
        shift = points[sure].mean(axis=0) - (self._box[:2] + self._box[2:]) / 2
        self._box = self._box + np.tile(shift, 2)

    def detect(self, bgr: np.ndarray, t_ms: int, person_mask: np.ndarray | None = None) -> PoseFrame:
        start = time.perf_counter()
        h, w = bgr.shape[:2]
        if self._box is None or self._frames_since_detect >= DETECT_EVERY:
            self._box = self.detect_person(bgr)
            self._frames_since_detect = 0
        self._frames_since_detect += 1
        if self._box is None:
            return PoseFrame(t_ms, None, person_mask, (time.perf_counter() - start) * 1000, "rtmpose")
        box = self._box.copy()
        points, scores = self.keypoints(bgr, box)
        self._track_box(points, scores)
        landmarks = to_mediapipe(points, np.clip(scores, 0.0, 1.0), w, h)
        return PoseFrame(t_ms, landmarks, person_mask, (time.perf_counter() - start) * 1000, "rtmpose")


def _estimate_shoulders(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Shoulders straight 'up' from the hips (away from the knees), one torso length away."""
    hip_l, hip_r = points[11], points[12]
    knee_mid = (points[13] + points[14]) / 2
    hip_mid = (hip_l + hip_r) / 2
    across = hip_r - hip_l
    up = np.array([across[1], -across[0]])
    if np.dot(up, hip_mid - knee_mid) < 0:
        up = -up
    norm = np.hypot(*up)
    up = up / norm if norm > 1e-6 else np.array([0.0, -1.0])
    thigh = (np.hypot(*(points[13] - hip_l)) + np.hypot(*(points[14] - hip_r))) / 2
    torso = max(1.2 * thigh, 2.8 * np.hypot(*across))
    return hip_l + torso * up, hip_r + torso * up


def _unit(v: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    norm = float(np.hypot(*v))
    return v / norm if norm > 1e-6 else fallback


def _extend_legs(points: np.ndarray, scores: np.ndarray, width: int, height: int) -> None:
    """Move out-of-view knees / ankles (and the feet with them) to a plausible place off-screen,
    along the visible part of the leg, the way MediaPipe extrapolates hidden landmarks."""
    margin = EDGE_FRAC * height

    def unsure(i: int) -> bool:
        x, y = points[i]
        at_edge = x < margin or x > width - 1 - margin or y < margin or y > height - 1 - margin
        return scores[i] < LEG_SCORE or at_edge

    hip_l, hip_r = points[11], points[12]
    across = hip_r - hip_l
    hip_width = float(np.hypot(*across))
    down = _unit(np.array([-across[1], across[0]]), np.array([0.0, 1.0]))
    if np.dot(down, (points[13] + points[14]) / 2 - (hip_l + hip_r) / 2) < 0:
        down = -down
    thigh_min = THIGH_PER_HIP * hip_width

    for hip, knee, ankle, feet in ((11, 13, 15, (20, 24)), (12, 14, 16, (21, 25))):
        old_ankle = points[ankle].copy()
        thigh = points[knee] - points[hip]
        thigh_len = float(np.hypot(*thigh))
        knee_moved = False
        if unsure(knee) and thigh_len < thigh_min:
            # the clipped knee still shows which way the thigh goes, unless it is too close to tell
            direction = _unit(thigh, down) if thigh_len > 0.3 * hip_width else down
            points[knee] = points[hip] + direction * thigh_min
            thigh_len, knee_moved = thigh_min, True
        shin = points[ankle] - points[knee]
        shin_min = SHIN_PER_THIGH * thigh_len
        if knee_moved or (unsure(ankle) and float(np.hypot(*shin)) < shin_min):
            # straight leg: continue the thigh unless the ankle was seen beyond the knee
            direction = _unit(points[knee] - points[hip], down)
            if not knee_moved and not unsure(knee) and float(np.hypot(*shin)) > 0.3 * thigh_len:
                direction = _unit(shin, direction)
            points[ankle] = points[knee] + direction * max(shin_min, float(np.hypot(*shin)) if not knee_moved else 0)
        moved = points[ankle] - old_ankle
        for foot in feet:
            points[foot] = points[foot] + moved


def to_mediapipe(points: np.ndarray, scores: np.ndarray, width: int, height: int) -> tuple[Landmark, ...]:
    """Halpe-26 pixel keypoints -> 33 normalized MediaPipe landmarks (visibility = score)."""
    points = points.astype(np.float64).copy()
    _extend_legs(points, scores, width, height)
    if min(scores[5], scores[6]) < SHOULDER_SCORE:
        points[5], points[6] = _estimate_shoulders(points)
    for joint, shoulder in ((7, 5), (9, 5), (8, 6), (10, 6)):
        if scores[joint] < ARM_SCORE:
            points[joint] = points[shoulder]

    out: list[Landmark | None] = [None] * NUM_LANDMARKS
    for halpe, targets in HALPE_TO_MP.items():
        x, y = points[halpe]
        s = float(scores[halpe])
        for i in targets:
            out[i] = Landmark(x / width, y / height, 0.0, s, s)
    assert all(lm is not None for lm in out)
    return tuple(out)  # type: ignore[arg-type]
