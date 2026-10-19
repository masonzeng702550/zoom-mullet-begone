"""Command-line entry point: python -m meet_pants"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from meet_pants.config import Config, ConfigError, load_config

DEBUG_LAYERS = ("landmarks", "masks", "hud")


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
    parser.add_argument("--no-vcam", action="store_true", help="do not open the virtual camera")
    parser.add_argument("--no-preview", action="store_true", help="do not open the preview window")
    parser.add_argument(
        "--debug",
        type=_debug_layers,
        metavar="LAYERS",
        help=f"preview overlays, comma separated: {','.join(DEBUG_LAYERS)} or none",
    )
    parser.add_argument("--frames", type=int, help="stop after N frames (for testing)")
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

    if not config.pose_model_path.exists():
        print(
            f"model not found: {config.pose_model_path}\n"
            "run: python scripts/download_models.py",
            file=sys.stderr,
        )
        return 2

    # Imported late so --help and config errors don't pay for loading mediapipe.
    from meet_pants.pipeline import run

    return run(config, max_frames=args.frames)
