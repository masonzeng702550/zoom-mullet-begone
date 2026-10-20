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
        "debug": {"landmarks": False, "masks": True, "mesh": False, "hud": False},
    }


def test_cli_debug_none_hides_all() -> None:
    args = cli.build_parser().parse_args(["--debug", "none"])
    assert cli.args_to_overrides(args)["debug"] == {"landmarks": False, "masks": False, "mesh": False, "hud": False}


@pytest.mark.parametrize("argv", [["--resolution", "big"], ["--debug", "skeleton"]])
def test_cli_rejects_bad_values(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(argv)


def test_cli_reports_missing_model(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(f"models_dir: {tmp_path}\n")
    assert cli.main(["--config", str(path), "--no-vcam", "--no-preview"]) == 2
    assert "download_models.py" in capsys.readouterr().err


def test_explicit_garment_turns_off_auto_matching() -> None:
    parse = cli.build_parser().parse_args
    assert cli.args_to_overrides(parse(["--garment", "jeans_indigo"]))["garment_auto"] is False
    assert cli.args_to_overrides(parse(["--garment", "jeans_indigo", "--auto-garment"]))["garment_auto"] is True
    assert cli.args_to_overrides(parse(["--no-auto-garment"]))["garment_auto"] is False
    assert "garment_auto" not in cli.args_to_overrides(parse([]))


def test_legacy_config_moves_to_the_os_settings_folder(tmp_path: Path) -> None:
    from meet_pants.config import migrate_legacy_config

    legacy = tmp_path / "old" / "meet-pants" / "config.yaml"
    current = tmp_path / "new" / "meet-pants" / "config.yaml"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("garment: jeans_indigo\n", encoding="utf-8")
    assert migrate_legacy_config(legacy, current) is True
    assert current.read_text(encoding="utf-8") == "garment: jeans_indigo\n"
    assert not legacy.exists() and not legacy.parent.exists()
    # already moved, or nothing to move
    assert migrate_legacy_config(legacy, current) is False
    # never overwrites existing settings
    legacy.parent.mkdir(parents=True)
    legacy.write_text("garment: chino_khaki\n", encoding="utf-8")
    assert migrate_legacy_config(legacy, current) is False
    assert current.read_text(encoding="utf-8") == "garment: jeans_indigo\n"
