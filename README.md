# meet-pants

Skeleton-tracked virtual pants for video calls. Built on MediaPipe Tasks Vision `PoseLandmarker`; output goes to a virtual camera that Zoom / Meet / Teams can select.

> Status: **M1 + most of M2** — virtual pants follow each leg's skeleton (waist, thighs, knees, shins). Their edges follow the detected skin and clothes row by row, so wider or narrower legs stay covered. Lighting, color and camera noise are matched to the scene, edges are feathered, and forearms/hands stay in front. Always on for now; automatic "no pants" detection comes in M3.

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
| `--mode always` / `--mode off` | draw pants whenever hips are visible, or never |
| `--garment jeans_indigo` | use this garment (`dress_navy`, `chino_khaki`, `jeans_indigo`); turns off automatic matching |
| `--no-auto-garment` | keep the starting garment instead of matching the shirt |
| `--background` | run from the menu bar, start when a meeting opens the virtual camera (macOS) |
| `--settings` | only open the pants settings page (no camera) |
| `--no-vcam` | preview only |
| `--no-preview` | virtual camera only |
| `--debug landmarks,masks,mesh,hud` | preview overlays (`none` to hide) |
| `--record data/clip.mp4` | also save the raw camera input (to reproduce issues; `data/` is gitignored) |
| `--config path.yaml` | config file (default: `~/Library/Application Support/meet-pants/config.yaml` on macOS, `%APPDATA%\\meet-pants\\config.yaml` on Windows, `~/.config/meet-pants/config.yaml` on Linux) |

Preview keys: `M` toggles pants on/off, `P` next garment (stops automatic matching), `A` toggles automatic matching, `S` opens the settings page, `D` cycles overlays (skeleton → skeleton + person mask (purple) and skin (orange) → mesh → off), `Esc` or `Q` quits.

The preview is mirrored; the virtual camera is not (meeting apps mirror your self-view themselves). Overlays appear only in the preview.

## Background mode (macOS)

```bash
.venv/bin/python -m meet_pants --background
```

meet-pants then lives in the menu bar (a pants icon: outlined while waiting, filled while in use) and starts by itself:

- **Waiting**: the camera is off and nothing runs (about 0% CPU, ~170 MB). Twice a second it asks macOS (CoreMediaIO) whether any app opened *OBS Virtual Camera*.
- **A meeting opens the camera**: meet-pants turns on the camera and the pants appear about 2.5 s later (the meeting shows the OBS placeholder until then).
- **The meeting closes the camera**: meet-pants' own frames keep the virtual camera "in use", so it cannot see that directly. After nobody has been in front of the camera for a minute it stops sending for a moment and checks again; if no app reads the camera, it turns the camera off and waits. (If you stay at the desk after the meeting, it keeps running until you leave or choose *Quit* / untick *auto start* in the menu.)
- The menu has the status, *Open settings* (the settings page now also shows a live view of what the meeting sees), the auto-start switch and *Quit*.

On other systems `--background` cannot tell when a meeting opens the camera yet and simply runs all the time.

## Using it in meetings and websites

meet-pants sends its video to **OBS Virtual Camera**, which macOS lists as a normal camera next to the built-in one. Anything that lets you pick a camera can use it:

- **Google Meet** (any browser): Settings → Video → Camera → *OBS Virtual Camera*. Other sites in Chrome, Edge or Arc: the camera icon in the address bar, or set it once for all sites in `chrome://settings/content/camera`. Safari and Firefox ask per site; pick *OBS Virtual Camera* in their camera prompt or site settings.
- **Zoom, Teams, FaceTime, Discord, Slack**: choose *OBS Virtual Camera* in the app's video settings.

It cannot take over apps or sites that keep using the built-in camera: macOS gives every app direct access to the real camera and has no way to swap in another one system-wide. Start meet-pants before joining (the virtual camera shows the OBS placeholder when meet-pants is not running), and you do not need the preview during a call (`--no-preview`).

## CPU, memory and heat

- The skin/clothes segmenter runs on the GPU and only while your legs are in view (or briefly for a shirt-color sample); sitting at a desk with only your upper body in view, almost nothing but the pose model runs.
- The RTMPose fallback is loaded the first time it is needed, and is not run while MediaPipe sees your upper body with the hips below the frame.
- The pose model stays on the CPU: MediaPipe's macOS GPU path leaks every input frame. `pose: {segmenter_gpu: false}` moves the segmenter back to the CPU (about 400 MB less memory, more CPU).
- OpenCV is limited to one thread: its default spreads even the preview's per-frame color conversion over every core, and the hand-off cost a third of the app's CPU.
- The pose model runs on every second frame (`pose: {pose_every: 1}` for every frame: sharper on fast moves, about a third more CPU).
- To cool down further: `--fps 24` (or 20) and `--no-preview`.

## Pose fallback

MediaPipe needs most of the torso in view. When you sit close and only your waist and legs are visible, an RTMPose model (YOLOX person detector + 26-keypoint body-with-feet, OpenMMLab, Apache-2.0, run with onnxruntime) takes over for those frames. If both miss for a moment, the last pose is held for 300 ms so the pants do not flicker. The preview HUD shows which one is active (`pose mediapipe` / `rtmpose` / `hold`). Turn it off with `pose: {fallback: false}` in the config file.

## Matching the shirt

By default the pants are picked to go with your top. The shirt color is sampled between the shoulders and hips (clothes pixels only, not hands), smoothed over a few seconds, and each garment is scored against it: light/dark contrast scores, the same hue at a similar lightness (navy on navy) is penalized, and a bright top prefers quiet pants. The pants change only when another garment wins clearly for 1.5 s. The shoulders must be visible, so when you sit too close the last choice stays.

## Pants settings page

While meet-pants runs, `http://127.0.0.1:8765/` (or `S` in the preview) shows a settings page: choose the style (khaki chinos, navy dress trousers, jeans), a color (the garment's own, a preset, or any color from the picker), or leave it to the shirt matching. A change shows up on screen at once and is saved to the config file (`garment`, `garment_color`, `garment_auto`) as the default for next time. `python -m meet_pants --settings` opens the page without starting the camera.

Recoloring keeps the fabric's shading, weave and folds. The page only listens on 127.0.0.1 and only accepts changes from itself; set `settings_port: 0` to turn it off.

## Garments

Each folder in `garments/` holds a front-view RGBA `texture.png` and a `garment.yaml` with anchor points (waist, crotch, knee and hem rows per leg) and `trim`: seams, edges, creases and stitching as polylines in texture coordinates. Trim is drawn as crisp lines on screen, bent through the mesh, because thin texture details vanish when the texture is shown several times smaller than it was drawn. The built-in garments are generated by `scripts/make_garments.py`; re-run it after changing the layout.

## Test

```bash
.venv/bin/python -m pytest
```
