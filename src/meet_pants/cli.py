"""Command-line entry point: python -m meet_pants"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path
from typing import Any

from meet_pants.config import DEFAULT_CONFIG_PATH, MODES, Config, ConfigError, load_config

DEBUG_LAYERS = ("landmarks", "masks", "mesh", "hud")


def _resolution(text: str) -> list[int]:
    try:
        width, height = (int(v) for v in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError("expected WIDTHxHEIGHT, e.g. 1280x720") from None
    return [width, height]


def _debug_layers(text: str) -> list[str]:
    layers = [v.strip() for v in text.split(",") if v.strip()]
    unknown = set(layers) - set(DEBUG_LAYERS) - {"none"}
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown debug layer(s): {', '.join(sorted(unknown))}")
    return layers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meet-pants",
        description="Skeleton-tracked virtual pants for video calls.",
    )
    parser.add_argument("--input", "-i", help="camera index or video file path (default 0)")
    parser.add_argument("--config", "-c", type=Path, help="YAML config file")
    parser.add_argument("--resolution", type=_resolution, help="capture size, e.g. 1280x720")
    parser.add_argument("--fps", type=int, help="capture / virtual camera frame rate")
    parser.add_argument("--model", choices=["full", "lite"], help="pose landmarker model size")
    parser.add_argument("--mode", choices=MODES, help="always draw pants, or off")
    parser.add_argument(
        "--garment", help="garment id (folder name under garments/); turns off --auto-garment unless given"
    )
    parser.add_argument(
        "--auto-garment",
        action=argparse.BooleanOptionalAction,
        help="pick the pants that go with the shirt color (default on)",
    )
    parser.add_argument("--no-vcam", action="store_true", help="do not open the virtual camera")
    parser.add_argument("--no-preview", action="store_true", help="do not open the preview window")
    parser.add_argument(
        "--debug",
        type=_debug_layers,
        metavar="LAYERS",
        help=f"preview overlays, comma separated: {','.join(DEBUG_LAYERS)} or none",
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="only open the pants settings page (style, color, auto matching) without the camera",
    )
    parser.add_argument("--frames", type=int, help="stop after N frames (for testing)")
    parser.add_argument(
        "--record",
        type=Path,
        metavar="PATH",
        help="also save the raw camera input to an .mp4 (for reproducing issues; keep it out of git)",
    )
    return parser


def args_to_overrides(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if args.input is not None:
        overrides["input"] = args.input
    if args.resolution is not None:
        overrides["resolution"] = args.resolution
    if args.fps is not None:
        overrides["fps"] = args.fps
    if args.model is not None:
        overrides["pose"] = {"model": f"pose_landmarker_{args.model}.task"}
    if args.mode is not None:
        overrides["mode"] = args.mode
    if args.garment is not None:
        overrides["garment"] = args.garment
        overrides["garment_auto"] = False
    if args.auto_garment is not None:
        overrides["garment_auto"] = args.auto_garment
    if args.no_vcam:
        overrides["vcam"] = False
    if args.no_preview:
        overrides["preview"] = False
    if args.debug is not None:
        overrides["debug"] = {layer: layer in args.debug for layer in DEBUG_LAYERS}
    return overrides


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config: Config = load_config(args.config, args_to_overrides(args))
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    settings_path = args.config or DEFAULT_CONFIG_PATH
    if args.settings:
        return settings_only(config, settings_path)

    for model in (config.pose_model_path, config.segmenter_model_path):
        if not model.exists():
            print(f"model not found: {model}\nrun: python scripts/download_models.py", file=sys.stderr)
            return 2

    # Imported late so --help and config errors don't pay for loading mediapipe.
    from meet_pants.pipeline import run

    return run(config, max_frames=args.frames, record=args.record, settings_path=settings_path)


def settings_only(config: Config, settings_path: Path) -> int:
    """Serve the settings page until Ctrl-C; choices are saved to `settings_path`."""
    from meet_pants.ui.settings import GarmentChoice, SettingsHub, SettingsServer

    choice = GarmentChoice(config.garment, config.garment_color, config.garment_auto)
    hub = SettingsHub(Path(config.garments_dir), choice, settings_path)
    try:
        server = SettingsServer(hub, config.settings_port or 8765)
    except OSError as e:
        print(f"cannot open the settings page: {e}\nis meet-pants already running? press S in its preview", file=sys.stderr)
        return 1
    with server:
        print(f"settings page: {server.url}  (saved to {settings_path}; Ctrl-C to stop)")
        server.open()
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    return 0
