"""Configuration: dataclass defaults, overridden by a YAML file, overridden by CLI flags."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "meet-pants" / "config.yaml"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODELS_DIR = PROJECT_ROOT / "models"


@dataclass(frozen=True)
class PoseConfig:
    model: str = "pose_landmarker_full.task"
    min_detection_confidence: float = 0.5
    min_presence_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    segmentation_mask: bool = True


@dataclass(frozen=True)
class DebugConfig:
    landmarks: bool = True
    masks: bool = False
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
    models_dir: str = str(DEFAULT_MODELS_DIR)
    pose: PoseConfig = field(default_factory=PoseConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)

    @property
    def pose_model_path(self) -> Path:
        return Path(self.models_dir).expanduser() / self.pose.model


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
    return config
