# meet-pants

**English** | [繁體中文](README.zh-TW.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

Virtual pants for video calls. meet-pants tracks your legs with a pose model, draws a pair of pants that follows them, and sends the result to a virtual camera that Google Meet, Zoom, Teams and other apps can select.

## Features

- **Pants that follow each leg**: waist, thighs, knees and shins are tracked, and the edges follow your real silhouette row by row, so wider or narrower legs stay covered, including the gap between the legs.
- **Blends into the scene**: lighting, color and camera noise are matched to the picture, edges are feathered, and your forearms and hands stay in front of the pants.
- **Works up close**: when you sit so close that only your waist and legs are in view, a second pose model takes over.
- **Matches your shirt**: picks the pants style and color that go with your top, or use the one you choose.
- **Settings page**: pick the style and color in a local web page, with a live view of what the meeting sees.
- **Background mode (macOS)**: lives in the menu bar and turns on only while a meeting app uses the camera.

Three garments are included: navy dress trousers, khaki chinos and indigo jeans. Any of them can be recolored.

## Status

- Developed and tested on macOS (Apple silicon).
- Windows and Linux should work in the regular (foreground) mode with the virtual cameras listed below, but they have not been tested yet. Background mode cannot detect meetings on them yet.
- The pants are always on while your hips are in view. Automatic detection of "not wearing pants" is planned.

## Requirements

- Python 3.11 or 3.12
- A virtual camera driver:
  - **macOS / Windows**: [OBS Studio](https://obsproject.com/) 30 or newer. Open it once, click **Start Virtual Camera**, then quit OBS. meet-pants uses the camera driver OBS installs; OBS itself does not need to run.
  - **Linux**: [v4l2loopback](https://github.com/umlaeute/v4l2loopback) (`sudo modprobe v4l2loopback exclusive_caps=1` so Chrome lists it).

## Setup

```bash
uv venv --python 3.11
uv pip install -e ".[dev]"
python scripts/download_models.py
```

`download_models.py` puts the pose, segmentation and fallback models (about 75 MB) into `models/`.

On macOS the first run asks for camera access for your terminal app.

## Quick start

**Background mode (macOS, recommended):**

```bash
.venv/bin/python -m meet_pants --background
```

A pants icon appears in the menu bar. Join a meeting and choose **OBS Virtual Camera** as the camera; the pants appear about 2.5 seconds later.

**Foreground mode (all systems):**

```bash
.venv/bin/python -m meet_pants
```

This opens a preview window and sends the video to the virtual camera right away.

## Using it in meetings and websites

meet-pants sends its video to **OBS Virtual Camera**, which the system lists as a normal camera next to the built-in one. Anything that lets you pick a camera can use it:

- **Google Meet** (any browser): Settings → Video → Camera → *OBS Virtual Camera*.
- **Other websites in Chrome, Edge or Arc**: use the camera icon in the address bar, or choose it once for all sites at `chrome://settings/content/camera`.
- **Safari and Firefox**: they ask per site; pick *OBS Virtual Camera* in the camera prompt or the site settings.
- **Zoom, Teams, FaceTime, Discord, Slack**: choose *OBS Virtual Camera* in the app's video settings.

meet-pants cannot take over apps that keep using the built-in camera: macOS lets every app open the real camera directly and offers no way to replace it system-wide. When meet-pants is not running, the virtual camera shows the OBS placeholder image.

## Background mode (macOS)

```bash
.venv/bin/python -m meet_pants --background
```

The menu bar icon is outlined while waiting and filled while in use.

- **Waiting**: the camera is off and almost nothing runs (about 0% CPU and 170 MB of memory). Twice a second meet-pants asks macOS (CoreMediaIO) whether an app has opened *OBS Virtual Camera*.
- **A meeting opens the camera**: meet-pants turns on your camera, and the pants appear about 2.5 seconds later. Until then the meeting shows the OBS placeholder.
- **The meeting closes the camera**: meet-pants' own video keeps the virtual camera marked as "in use", so it cannot see this directly. After nobody has been in front of the camera for a minute, it stops sending for a moment and checks again. If no app is reading the camera, it turns your camera off and goes back to waiting. If you stay at your desk after the meeting, it keeps running until you leave, quit it, or turn off auto start in the menu.
- **Menu**: the current status, 開啟設定… (open settings), 會議開鏡頭時自動套用 (auto start when a meeting opens the camera) and 結束 meet-pants (quit).

On Windows and Linux, `--background` cannot tell when a meeting opens the camera yet, so it runs all the time.

## Settings page

While meet-pants runs, open `http://127.0.0.1:8765/`, press `S` in the preview, or choose 開啟設定… in the menu bar. You can:

- choose the style: khaki chinos, navy dress trousers or jeans;
- choose the color: the garment's own color, a preset, or any color from the color picker (the fabric keeps its shading, weave and folds);
- turn shirt matching on or off;
- see a live view of what the meeting receives (background mode).

Changes show up on screen immediately and are saved as the default for next time. `python -m meet_pants --settings` opens the page without starting the camera.

The settings page and the menu bar are in Traditional Chinese for now. The page listens only on 127.0.0.1 and accepts changes only from itself, so other websites cannot change your settings. Set `settings_port: 0` in the config file to turn it off.

## Command-line options

| Option | Meaning |
|---|---|
| `--background` | Run from the menu bar and start when a meeting opens the virtual camera (macOS) |
| `--settings` | Open only the settings page, without the camera |
| `--input 1` / `--input clip.mp4` | Camera index or video file |
| `--resolution 1280x720`, `--fps 30` | Capture size and frame rate |
| `--model lite` | Faster, less accurate pose model |
| `--mode always` / `--mode off` | Draw the pants whenever the hips are visible, or never |
| `--garment jeans_indigo` | Use this garment (`dress_navy`, `chino_khaki`, `jeans_indigo`); turns off shirt matching |
| `--auto-garment` / `--no-auto-garment` | Turn shirt matching on or off |
| `--no-vcam` | Preview only, no virtual camera |
| `--no-preview` | Virtual camera only, no preview window |
| `--debug landmarks,masks,mesh,hud` | Preview overlays (`none` hides them) |
| `--record data/clip.mp4` | Also save the raw camera video, for reproducing problems |
| `--config path.yaml` | Use this config file |

**Preview window keys**: `M` pants on/off, `P` next garment (turns off shirt matching), `A` shirt matching on/off, `S` settings page, `D` cycle overlays (skeleton → skeleton with person mask in purple and skin in orange → mesh → none), `Esc` or `Q` quit.

The preview is mirrored; the virtual camera is not, because meeting apps mirror your self-view themselves. Overlays appear only in the preview.

## Configuration

Settings are read from a YAML file in the system's settings folder:

| System | Location |
|---|---|
| macOS | `~/Library/Application Support/meet-pants/config.yaml` |
| Windows | `%APPDATA%\meet-pants\config.yaml` |
| Linux | `~/.config/meet-pants/config.yaml` |

Command-line options override the file. An older `~/.config/meet-pants/config.yaml` on macOS or Windows is moved to the new location automatically. Example:

```yaml
garment: chino_khaki
garment_color: "#3c3f44"   # "" keeps the garment's own color
garment_auto: false        # true: pick the pants that match the shirt
fps: 24
pose:
  pose_every: 2            # run the pose model on every Nth frame
  segment_every: 2         # run the skin/clothes segmenter on every Nth frame
  segmenter_gpu: true
  fallback: true           # RTMPose for close-up shots
```

## Performance

Measured on an M4 Pro MacBook Pro with a 720p camera at 30 fps:

| Situation | CPU | Memory |
|---|---|---|
| Background mode, waiting | about 0% | about 170 MB |
| Running, upper body in view | about 30–40% | about 650 MB |

How it stays light:

- The skin/clothes segmenter runs on the GPU, and only while your legs are in view or when a shirt-color sample is due.
- The pose model runs on every second frame. Set `pose_every: 1` for sharper tracking of fast movements (about a third more CPU).
- The close-up fallback model is loaded only when first needed, and is skipped while MediaPipe sees your upper body with the hips below the frame.
- OpenCV runs single-threaded. Its default spreads even small per-frame jobs over every core, which used a third of the CPU.
- The pose model stays on the CPU, because MediaPipe's GPU path on macOS leaks memory on every frame. Set `segmenter_gpu: false` to move the segmenter to the CPU as well (about 400 MB less memory, more CPU).

To use even less: `--fps 24` (or 20), and `--no-preview` or background mode.

## How it works

**Pose.** MediaPipe Pose Landmarker finds the hips, knees and ankles. MediaPipe needs most of the torso in view, so when you sit close and only your waist and legs are visible, an RTMPose model takes over for those frames (a YOLOX person detector plus a 26-keypoint body-and-feet model from OpenMMLab, run with onnxruntime). Its result is used only if it is plausible: the hips are inside the frame, at least one knee is visible, and the hips are well below the shoulders when MediaPipe can see them. If both models miss for a moment, the last pose is kept for 300 ms so the pants do not flicker. The preview shows which one is in use (`pose mediapipe`, `rtmpose` or `hold`).

**Legs.** A person mask and a skin/clothes segmentation measure each leg's width at several points along the thigh and shin. The pants are drawn at least that wide, and the two legs meet in the middle wherever your thighs touch.

**Shirt matching.** The shirt color is sampled between the shoulders and hips (clothes only, not hands) and smoothed over a few seconds. Each garment is scored against it: light/dark contrast scores well, the same hue at a similar lightness (navy on navy) is penalized, and a bright top prefers quieter pants. The pants change only when another garment wins clearly for 1.5 seconds. The shoulders must be visible, so when you sit too close the last choice stays.

**Garments.** Each folder in `garments/` holds a front-view RGBA `texture.png` and a `garment.yaml` with anchor points (waist, crotch, knee and hem for each leg) and trim lines (seams, edges, creases and stitching). Trim is drawn as sharp lines on screen, bent with the mesh, because thin details in the texture disappear when it is shown much smaller than it was drawn. The built-in garments are generated by `scripts/make_garments.py`.

## Development

```bash
.venv/bin/python -m pytest
```

Tests that need the models or the private test footage in `data/` are skipped when those files are missing. Videos recorded with `--record` stay in `data/`, which is not committed.

## Third-party models

| Model | Source | License |
|---|---|---|
| Pose Landmarker, Selfie Multiclass Segmenter | Google MediaPipe | Apache-2.0 |
| RTMPose-s (Halpe-26), YOLOX-tiny (Human-Art) | OpenMMLab | Apache-2.0 |

The models are downloaded by `scripts/download_models.py` and are not included in this repository.
