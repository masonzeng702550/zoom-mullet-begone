"""Configuration: dataclass defaults, overridden by a YAML file, overridden by CLI flags."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "meet-pants" / "config.yaml"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODELS_DIR = PROJECT_ROOT / "models"
DEFAULT_GARMENTS_DIR = PROJECT_ROOT / "garments"

# "auto" (draw only when the lower body is inappropriate) arrives with M3.
MODES = ("always", "off")


@dataclass(frozen=True)
class PoseConfig:
    model: str = "pose_landmarker_full.task"
    segmenter_model: str = "selfie_multiclass_256x256.tflite"
    min_detection_confidence: float = 0.5
    min_presence_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    segmentation_mask: bool = True
    # Run a MediaPipe model on the GPU: about half the CPU time, less heat. Falls
    # back to the CPU when the GPU cannot be used. The pose model stays on the CPU
    # by default: on macOS its GPU path leaks each input frame (~3.7 MB per frame
    # at 720p, mediapipe 0.10). The segmenter's GPU path does not leak.
    pose_gpu: bool = False
    segmenter_gpu: bool = True
    # Run the skin/clothes segmenter on every Nth frame (its mask is reused in
    # between). It is the most expensive model; legs barely move in 1/15 s.
    segment_every: int = 2
    # RTMPose fallback for frames where MediaPipe cannot see the hips (person
    # too close, head and chest out of frame).
    fallback: bool = True
    fallback_detector: str = "yolox_tiny_humanart.onnx"
    fallback_model: str = "rtmpose_s_halpe26.onnx"
    hold_ms: int = 300  # keep the last pose this long when both detectors miss


@dataclass(frozen=True)
class SmoothingConfig:
    # One Euro parameters; landmark speed is measured in pixels per second.
    min_cutoff: float = 1.0
    beta: float = 0.05
    d_cutoff: float = 1.0


@dataclass(frozen=True)
class DebugConfig:
    landmarks: bool = True
    masks: bool = False
    mesh: bool = False
    hud: bool = True


@dataclass(frozen=True)
class Config:
    input: int | str = 0
    resolution: tuple[int, int] = (1280, 720)
    fps: int = 30
    # Mirrors only the local preview. The virtual camera always sends the
    # unmirrored image; meeting apps mirror the self-view on their own.
    preview_mirror: bool = True
    preview: bool = True
    vcam: bool = True
    mode: str = "always"
    garment: str = "dress_navy"
    # Pick the pants that go with the shirt color (P in the preview turns it off).
    garment_auto: bool = True
    # "#rrggbb" to recolor the chosen garment, "" for its own color (ignored while
    # garment_auto picks the pants).
    garment_color: str = ""
    # Local settings page (http://127.0.0.1:<port>, S in the preview); 0 turns it off.
    settings_port: int = 8765
    models_dir: str = str(DEFAULT_MODELS_DIR)
    garments_dir: str = str(DEFAULT_GARMENTS_DIR)
    pose: PoseConfig = field(default_factory=PoseConfig)
    smoothing: SmoothingConfig = field(default_factory=SmoothingConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)

    @property
    def pose_model_path(self) -> Path:
        return Path(self.models_dir).expanduser() / self.pose.model

    @property
    def models_path(self) -> Path:
        return Path(self.models_dir).expanduser()

    @property
    def segmenter_model_path(self) -> Path:
        return Path(self.models_dir).expanduser() / self.pose.segmenter_model


class ConfigError(ValueError):
    pass


def _merge(base: Any, overrides: dict[str, Any], path: str = "") -> Any:
    """Return a copy of dataclass `base` with values from the nested dict `overrides`."""
    known = {f.name: f for f in fields(base)}
    changes: dict[str, Any] = {}
    for key, value in overrides.items():
        if key not in known:
            raise ConfigError(f"unknown config key: {path}{key}")
        current = getattr(base, key)
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ConfigError(f"{path}{key} must be a mapping")
            changes[key] = _merge(current, value, f"{path}{key}.")
        elif isinstance(current, tuple):
            if not isinstance(value, (list, tuple)) or len(value) != len(current):
                raise ConfigError(f"{path}{key} must be a list of {len(current)} values")
            changes[key] = tuple(type(c)(v) for c, v in zip(current, value))
        elif isinstance(current, bool):
            if not isinstance(value, bool):
                raise ConfigError(f"{path}{key} must be true or false")
            changes[key] = value
        elif key == "input":
            changes[key] = parse_input(value)
        else:
            try:
                changes[key] = type(current)(value)
            except (TypeError, ValueError) as e:
                raise ConfigError(f"{path}{key}: {e}") from e
    return replace(base, **changes)


def parse_input(value: int | str) -> int | str:
    """Camera indices may arrive as strings ("0"); file paths stay strings."""
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text) if text.isdigit() else text


def load_config(path: Path | None = None, overrides: dict[str, Any] | None = None) -> Config:
    """Load defaults, then the YAML file (if it exists), then `overrides`.

    An explicitly given `path` must exist; the default path is optional.
    """
    config = Config()
    if path is not None and not path.exists():
        raise ConfigError(f"config file not found: {path}")
    file_path = path or DEFAULT_CONFIG_PATH
    if file_path.exists():
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ConfigError(f"{file_path}: top level must be a mapping")
        config = _merge(config, data)
    if overrides:
        config = _merge(config, overrides)
    if config.mode not in MODES:
        raise ConfigError(f"mode must be one of {', '.join(MODES)}, got {config.mode!r}")
    return config
