from __future__ import annotations

from pathlib import Path

import pytest

from meet_pants import cli
from meet_pants.config import Config, ConfigError, load_config, parse_input


def test_defaults_when_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("meet_pants.config.DEFAULT_CONFIG_PATH", tmp_path / "missing.yaml")
    assert load_config() == Config()


def test_yaml_then_overrides(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text("input: '2'\nresolution: [640, 480]\npose:\n  min_tracking_confidence: 0.7\n")
    config = load_config(path, {"fps": 15, "pose": {"model": "pose_landmarker_lite.task"}})
    assert config.input == 2
    assert config.resolution == (640, 480)
    assert config.fps == 15
    assert config.pose.min_tracking_confidence == 0.7
    assert config.pose.model == "pose_landmarker_lite.task"
    assert config.pose.min_detection_confidence == 0.5  # untouched sibling keeps default


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"nope": 1}, "unknown config key: nope"),
        ({"pose": {"nope": 1}}, "unknown config key: pose.nope"),
        ({"resolution": [1]}, "list of 2 values"),
        ({"vcam": "yes"}, "true or false"),
        ({"pose": 3}, "must be a mapping"),
        ({"fps": "fast"}, "fps"),
    ],
)
def test_invalid_overrides(overrides: dict, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_config(None, overrides)


def test_explicit_missing_file_is_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml")


@pytest.mark.parametrize("value, expected", [(0, 0), ("1", 1), (" 3 ", 3), ("clip.mp4", "clip.mp4")])
def test_parse_input(value: int | str, expected: int | str) -> None:
    assert parse_input(value) == expected


def test_cli_overrides() -> None:
    args = cli.build_parser().parse_args(
        ["-i", "clip.mp4", "--resolution", "640x360", "--model", "lite", "--no-vcam", "--debug", "masks"]
    )
    assert cli.args_to_overrides(args) == {
        "input": "clip.mp4",
        "resolution": [640, 360],
        "pose": {"model": "pose_landmarker_lite.task"},
        "vcam": False,
        "debug": {"landmarks": False, "masks": True, "hud": False},
    }


def test_cli_debug_none_hides_all() -> None:
    args = cli.build_parser().parse_args(["--debug", "none"])
    assert cli.args_to_overrides(args)["debug"] == {"landmarks": False, "masks": False, "hud": False}


@pytest.mark.parametrize("argv", [["--resolution", "big"], ["--debug", "skeleton"]])
def test_cli_rejects_bad_values(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(argv)


def test_cli_reports_missing_model(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(f"models_dir: {tmp_path}\n")
    assert cli.main(["--config", str(path), "--no-vcam", "--no-preview"]) == 2
    assert "download_models.py" in capsys.readouterr().err
