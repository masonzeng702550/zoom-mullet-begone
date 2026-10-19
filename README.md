# meet-pants

Skeleton-tracked virtual pants for video calls. Built on MediaPipe Tasks Vision `PoseLandmarker`; output goes to a virtual camera that Zoom / Meet / Teams can select.

> Status: **M0** — camera capture, virtual camera passthrough, and a skeleton preview. No pants yet.

## Setup

Requires Python 3.11 or 3.12.

```bash
uv venv --python 3.11
uv pip install -e ".[dev]"
python scripts/download_models.py
```

For the virtual camera on macOS or Windows, install [OBS Studio](https://obsproject.com/) 30 or newer, click **Start Virtual Camera** once, then quit OBS.

On macOS the first run asks for camera access for your terminal app.

## Run

```bash
.venv/bin/python -m meet_pants
```

Then pick **OBS Virtual Camera** in your meeting app.

| Option | Meaning |
|---|---|
| `--input 1` / `--input clip.mp4` | camera index or video file |
| `--resolution 1280x720`, `--fps 30` | capture settings |
| `--model lite` | faster, less accurate pose model |
| `--no-vcam` | preview only |
| `--no-preview` | virtual camera only |
| `--debug landmarks,masks,hud` | preview overlays (`none` to hide) |
| `--config path.yaml` | config file (default `~/.config/meet-pants/config.yaml`) |

Preview keys: `D` cycles overlays (skeleton → skeleton + person mask → off), `Esc` or `Q` quits.

The preview is mirrored; the virtual camera is not (meeting apps mirror your self-view themselves). Overlays appear only in the preview.

## Test

```bash
.venv/bin/python -m pytest
```
