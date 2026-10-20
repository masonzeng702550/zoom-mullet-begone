# Zoom Mullet Begone

[English](README.md) | [繁體中文](README.zh-TW.md) | [日本語](README.ja.md) | **한국어**

> **Zoom 멀릿, 물러가라!** 위도 비즈니스, 아래도 비즈니스. (예전 이름 *meet-pants*)

**[브라우저에서 바로 써 보기 →](https://masonzeng702550.github.io/zoom-mullet-begone/)** 설치 필요 없음: 카메라를 켜거나 사진을 올리면 바지가 나타납니다. 모든 처리는 페이지 안에서 이루어지며, 영상은 이 컴퓨터 밖으로 나가지 않습니다.

화상 회의용 가상 바지입니다. Zoom Mullet Begone은 자세 추정 모델로 다리를 추적해 다리 움직임을 따라가는 바지를 그리고, 그 영상을 가상 카메라로 보냅니다. Google Meet, Zoom, Teams 같은 앱에서 이 카메라를 선택해 사용할 수 있습니다.

## 기능

- **브라우저에서 바로 체험**: [온라인 데모](https://masonzeng702550.github.io/zoom-mullet-begone/)에서 웹 페이지 안에서 바로 바지를 입어 볼 수 있습니다. 설치할 것이 없습니다.
- **다리마다 따라 움직이는 바지**: 허리, 허벅지, 무릎, 정강이를 추적하고, 바지 가장자리도 실제 몸의 윤곽을 따라 맞춥니다. 다리가 굵든 가늘든 잘 가려지고, 두 다리 사이도 드러나지 않습니다.
- **화면에 자연스럽게 섞임**: 조명, 색감, 카메라 노이즈를 화면에 맞추고, 가장자리를 부드럽게 처리하며, 팔뚝과 손은 바지보다 앞에 보이게 합니다.
- **가까이에서도 동작**: 카메라에 너무 가까이 앉아 허리와 다리만 보이면 다른 자세 추정 모델로 전환합니다.
- **상의에 맞춘 코디**: 상의와 어울리는 바지 스타일과 색을 자동으로 고릅니다. 직접 지정할 수도 있습니다.
- **설정 페이지**: 로컬 웹 페이지에서 스타일과 색을 고르고, 회의 상대에게 전송되는 화면을 실시간으로 볼 수 있습니다.
- **브라우저 확장 프로그램**: Chrome, Edge, Arc의 Google Meet 등 웹사이트에 'Zoom Mullet Begone' 카메라를 추가합니다. 카메라 드라이버를 설치할 필요가 없습니다.
- **백그라운드 모드**: 메뉴 막대에 상주하며, 회의가 카메라를 사용할 때만 동작합니다.

바지는 세 가지(네이비 정장 바지, 카키 치노 팬츠, 인디고 청바지)가 포함되어 있고, 모두 색을 바꿀 수 있습니다.

## 현재 상태

- macOS(Apple 실리콘)에서 개발하고 테스트했습니다. 브라우저 확장 프로그램은 Google Meet에서 동작을 확인했습니다.
- Windows와 Linux에서도 동작할 것으로 보이지만, 아직 테스트하지 않았습니다. 이 운영체제들의 백그라운드 모드는 브라우저 탭이 Zoom Mullet Begone 카메라를 쓰는 것은 알 수 있지만, 데스크톱 앱이 가상 카메라를 여는 것은 아직 알 수 없습니다.
- 브라우저 확장 프로그램은 Chromium 기반 브라우저(Chrome, Edge, Arc, Brave)에서 동작합니다. Safari와 Firefox는 아직 지원하지 않습니다.
- 엉덩이가 화면에 보이는 동안에는 항상 바지를 그립니다. '바지를 입지 않은 상태'를 자동으로 감지하는 기능은 계획 중입니다.

## 요구 사항

- Python 3.11 또는 3.12
- 영상을 회의로 보내는 방법(하나 또는 둘 다):
  - **브라우저 확장 프로그램**(Google Meet 같은 웹 회의, 따로 설치할 것 없음): 아래의 '브라우저 확장 프로그램(OBS 불필요)'을 참고하세요.
  - **가상 카메라 드라이버**(Zoom, Teams 데스크톱 앱을 포함한 모든 앱):
    - **macOS / Windows**: [OBS Studio](https://obsproject.com/) 30 이상. OBS를 한 번 열어 '가상 카메라 시작'(Start Virtual Camera)을 누른 뒤 OBS를 종료하세요. Zoom Mullet Begone은 OBS가 설치한 카메라 드라이버를 사용하므로, 평소에 OBS를 켜 둘 필요는 없습니다.
    - **Linux**: [v4l2loopback](https://github.com/umlaeute/v4l2loopback) (Chrome에 표시되도록 `sudo modprobe v4l2loopback exclusive_caps=1`로 불러옵니다).

## 설치

```bash
uv venv --python 3.11
uv pip install -e ".[dev]"
python scripts/download_models.py
```

`download_models.py`는 자세 추정, 분할, 대체용 모델(약 75 MB)을 `models/`에 내려받습니다.

macOS에서는 처음 실행할 때 터미널 앱의 카메라 사용 권한을 묻습니다.

## 빠른 시작

**백그라운드 모드(macOS, 권장):**

```bash
.venv/bin/python -m zoom_mullet_begone --background
```

메뉴 막대에 바지 아이콘이 나타납니다. 회의에 참여해 카메라로 'Zoom Mullet Begone'(브라우저 확장 프로그램) 또는 'OBS Virtual Camera'를 선택하면 약 3.5초 뒤에 바지가 나타납니다.

**포그라운드 모드(모든 운영체제):**

```bash
.venv/bin/python -m zoom_mullet_begone
```

미리보기 창이 열리고, 곧바로 가상 카메라로 영상을 보냅니다.

## 온라인 데모

**[https://masonzeng702550.github.io/zoom-mullet-begone/](https://masonzeng702550.github.io/zoom-mullet-begone/)**

누구나 아무것도 설치하지 않고 써 볼 수 있는 연습용 회의실입니다.

1. **Turn on camera**(카메라 켜기)를 누르거나, **Upload a photo or video**(사진 또는 동영상 올리기)를 누릅니다.
2. 허리와 다리가 화면에 들어오도록 뒤로 물러납니다. 위쪽 상태 표시가 *Pants on*(바지 착용 중)으로 바뀝니다.
3. 영상 위쪽에서 스타일과 색을 고르고, **Hold to compare**(눌러서 비교)를 누르고 있으면 원래 모습을 볼 수 있습니다.

모든 처리는 페이지 안에서 이루어집니다. MediaPipe 자세 추정 모델(WebAssembly, 가능하면 그래픽 카드 사용)이 다리를 찾고, WebGL이 바지를 그립니다. 영상은 업로드되지 않습니다. 처음 열 때 약 15 MB(모델과 실행 환경)를 내려받습니다. WebGL2를 지원하는 최신 Chrome, Edge, Safari, Firefox에서 동작합니다.

데모는 데스크톱 앱을 가볍게 옮긴 버전으로, 근거리용 대체 모델, 피부/옷 분할, 팔뚝을 바지 앞에 보이게 하는 처리, 솔기 선은 빠져 있습니다. 실제 회의에서는 데스크톱 앱과 브라우저 확장 프로그램 또는 가상 카메라를 사용하세요.

(데모 화면은 영어와 번체 중국어를 지원합니다.)

## 브라우저 확장 프로그램(OBS 불필요)

`browser-extension/`의 확장 프로그램은 모든 웹사이트에 'Zoom Mullet Begone'이라는 카메라를 추가합니다. Google Meet(또는 다른 사이트)에서 이 카메라를 고르면, 사이트가 Zoom Mullet Begone의 영상을 받습니다. 가상 카메라 드라이버가 필요 없으므로 OBS 없이도 사용할 수 있습니다.

**설치(Chrome, Edge, Arc, Brave):**

1. `chrome://extensions`(Edge는 `edge://extensions`)를 엽니다.
2. '개발자 모드'를 켭니다.
3. '압축해제된 확장 프로그램을 로드합니다'를 눌러 이 저장소의 `browser-extension` 폴더를 선택합니다.

**사용 방법:**

1. Zoom Mullet Begone을 실행합니다. 백그라운드 모드를 권장합니다: `.venv/bin/python -m zoom_mullet_begone --background`.
2. Google Meet에서 설정 → 동영상 → 카메라 → **Zoom Mullet Begone**를 고릅니다. 다른 사이트에서도 카메라를 고르는 곳에 나타납니다.
3. 도구 모음의 확장 프로그램 버튼에서 Zoom Mullet Begone 실행 여부를 확인하고 설정 페이지를 열 수 있습니다.

**개인정보와 보안:**

- Zoom Mullet Begone 카메라는 이미 카메라 사용 권한을 받은 사이트만 쓸 수 있습니다. 실제 카메라와 똑같습니다.
- 영상은 127.0.0.1을 거쳐 Zoom Mullet Begone에서 브라우저로 전달되며, 이 컴퓨터 밖으로 나가지 않습니다. Zoom Mullet Begone은 브라우저 확장 프로그램의 연결만 받아들이므로(웹 페이지가 설정할 수 없는 요청 헤더, 즉 `Sec-Fetch-Site` 또는 확장 프로그램의 `Origin`으로 판단), 웹사이트가 이를 통해 카메라를 읽을 수 없습니다.
- 백그라운드 모드에서는 탭이 Zoom Mullet Begone 카메라를 고르면 시작하고, 탭이 사용을 마치고 약 3초 뒤에 멈춥니다.

데스크톱 앱(Zoom, Teams, FaceTime)에서는 확장 프로그램의 카메라가 보이지 않으므로, 이런 앱에는 여전히 가상 카메라 드라이버가 필요합니다.

**화면에 '找不到 Zoom Mullet Begone'(Zoom Mullet Begone을 찾을 수 없음)이 표시되면** Zoom Mullet Begone이 실행 중이 아니거나 다른 포트를 쓰고 있는 것입니다. Zoom Mullet Begone을 실행하면 탭이 2초 안에 자동으로 다시 연결됩니다. 탭이 연결되면 터미널에 `browser stream: a tab connected`가 출력됩니다.

## 회의와 웹사이트에서 사용하기

가상 카메라 드라이버를 쓸 때 Zoom Mullet Begone은 영상을 'OBS Virtual Camera'로 보냅니다. 운영체제는 이것을 일반 카메라로 인식해 내장 카메라와 함께 보여 줍니다. 카메라를 고를 수 있는 곳이라면 어디서든 사용할 수 있습니다.

- **Google Meet**(모든 브라우저): 설정 → 동영상 → 카메라 → OBS Virtual Camera.
- **Chrome, Edge, Arc의 다른 웹사이트**: 주소 표시줄의 카메라 아이콘에서 고르거나, `chrome://settings/content/camera`에서 모든 사이트에 한 번에 설정합니다.
- **Safari와 Firefox**: 사이트마다 묻기 때문에, 카메라 확인 창이나 사이트 설정에서 OBS Virtual Camera를 고릅니다.
- **Zoom, Teams, FaceTime, Discord, Slack**: 각 앱의 비디오 설정에서 OBS Virtual Camera를 고릅니다.

내장 카메라를 계속 사용하는 앱은 Zoom Mullet Begone이 대신할 수 없습니다. macOS에서는 모든 앱이 실제 카메라를 직접 열 수 있고, 시스템 전체에서 카메라를 바꿔치기할 방법이 없기 때문입니다. Zoom Mullet Begone이 실행 중이 아닐 때는 가상 카메라에 OBS의 대기 화면이 표시됩니다.

## 백그라운드 모드

```bash
.venv/bin/python -m zoom_mullet_begone --background
```

메뉴 막대 아이콘은 대기 중에는 윤곽선만, 사용 중에는 채워진 모양으로 표시됩니다.

- **대기 중**: 카메라가 꺼져 있고 거의 아무것도 실행되지 않습니다(CPU 약 0%). 1초에 두 번, 브라우저 탭이 Zoom Mullet Begone 카메라를 골랐는지, 그리고 macOS에서는 어떤 앱이 OBS Virtual Camera를 열었는지(CoreMediaIO로) 확인합니다.
- **회의가 카메라를 열면**: Zoom Mullet Begone이 카메라를 켜고, 약 3.5초 뒤에 바지가 나타납니다.
- **브라우저 탭이 카메라 사용을 마치면**: 약 3초 뒤에 멈춥니다. 브라우저 탭으로 시작된 실행은 OBS Virtual Camera를 건드리지 않습니다.
- **데스크톱 앱이 OBS Virtual Camera를 닫으면**: Zoom Mullet Begone이 보내는 영상 때문에 가상 카메라가 계속 '사용 중'으로 표시되므로, 이를 바로 알아낼 수는 없습니다. 카메라 앞에 1분 동안 아무도 없으면 잠깐 영상 전송을 멈추고 다시 확인합니다. 카메라를 읽는 앱이 없으면 카메라를 끄고 대기 상태로 돌아갑니다. 회의가 끝난 뒤에도 자리에 앉아 있으면, 자리를 뜨거나 종료하거나 메뉴에서 자동 시작을 끌 때까지 계속 실행됩니다.
- **메뉴**: 현재 상태, '開啟設定…'(설정 열기), '會議開鏡頭時自動套用'(회의가 카메라를 열면 자동 시작), '結束 Zoom Mullet Begone'(종료).

Windows와 Linux의 백그라운드 모드는 데스크톱 앱이 가상 카메라를 여는 시점을 아직 알 수 없습니다. 가상 카메라 드라이버가 있으면 항상 실행되고, 없으면 브라우저 확장 프로그램에만 영상을 보내며 탭에 맞춰 시작하고 멈춥니다.

실행은 매번 별도의 프로세스에서 이루어지고 실행이 끝나면 그 프로세스도 종료되므로, 이후 메모리 사용량은 약 150 MB로 돌아갑니다.

## 설정 페이지

Zoom Mullet Begone이 실행 중일 때 `http://127.0.0.1:8765/`를 열거나, 미리보기 창에서 `S`를 누르거나, 메뉴 막대에서 '開啟設定…'을 고르세요. 다음을 할 수 있습니다.

- 스타일 선택: 카키 치노 팬츠, 네이비 정장 바지, 청바지
- 색 선택: 원래 색, 미리 정해진 색, 또는 색상 선택기로 원하는 색(원단의 음영, 직조 무늬, 주름은 그대로 유지됩니다)
- 상의에 맞추는 기능 켜기/끄기
- 회의에 전송되는 화면 실시간 보기(백그라운드 모드)

변경 사항은 곧바로 화면에 반영되고, 다음 실행 때의 기본값으로 저장됩니다. `python -m zoom_mullet_begone --settings`를 쓰면 카메라를 켜지 않고 설정 페이지만 열 수 있습니다.

설정 페이지와 메뉴 막대는 지금은 번체 중국어로만 제공됩니다. 설정 페이지는 127.0.0.1에서만 요청을 받고 페이지 자신이 보낸 변경만 받아들이므로, 다른 웹사이트가 설정을 바꿀 수 없습니다. 설정 파일에서 `settings_port: 0`으로 지정하면 꺼집니다.

## 명령줄 옵션

| 옵션 | 설명 |
|---|---|
| `--background` | 메뉴 막대에서 실행하고, 회의가 카메라를 열면 시작 |
| `--settings` | 카메라 없이 설정 페이지만 열기 |
| `--input 1` / `--input clip.mp4` | 카메라 번호 또는 동영상 파일 |
| `--resolution 1280x720`, `--fps 30` | 캡처 해상도와 프레임 속도 |
| `--model lite` | 더 빠르지만 덜 정확한 자세 추정 모델 |
| `--mode always` / `--mode off` | 엉덩이가 보이면 항상 바지를 그림 / 그리지 않음 |
| `--garment jeans_indigo` | 이 바지를 사용(`dress_navy`, `chino_khaki`, `jeans_indigo`). 상의에 맞추는 기능은 꺼짐 |
| `--auto-garment` / `--no-auto-garment` | 상의에 맞추는 기능 켜기/끄기 |
| `--no-vcam` | 미리보기만 하고 가상 카메라로는 보내지 않음 |
| `--no-preview` | 가상 카메라로만 보내고 미리보기 창은 열지 않음 |
| `--debug landmarks,masks,mesh,hud` | 미리보기 디버그 표시(`none`이면 숨김) |
| `--record data/clip.mp4` | 문제 재현을 위해 카메라 원본 영상도 녹화 |
| `--config path.yaml` | 지정한 설정 파일 사용 |

**미리보기 창 단축키**: `M` 바지 켜기/끄기, `P` 다음 바지(상의에 맞추는 기능은 꺼짐), `A` 상의에 맞추는 기능 켜기/끄기, `S` 설정 페이지, `D` 디버그 표시 전환(골격 → 골격과 인물 마스크(보라색)·피부(주황색) → 메시 → 없음), `Esc` 또는 `Q` 종료.

미리보기는 좌우 반전되어 보이지만, 가상 카메라 영상은 반전되지 않습니다. 회의 앱이 내 화면을 스스로 반전해서 보여 주기 때문입니다. 디버그 표시는 미리보기에만 나타납니다.

## 설정 파일

설정은 운영체제의 설정 폴더에 있는 YAML 파일에서 읽습니다.

| 운영체제 | 위치 |
|---|---|
| macOS | `~/Library/Application Support/zoom-mullet-begone/config.yaml` |
| Windows | `%APPDATA%\zoom-mullet-begone\config.yaml` |
| Linux | `~/.config/zoom-mullet-begone/config.yaml` |

명령줄 옵션이 설정 파일보다 우선합니다. 예전 버전(프로젝트 이름이 meet-pants였을 때)의 설정은 자동으로 새 위치로 옮겨집니다. 예시:

```yaml
garment: chino_khaki
garment_color: "#3c3f44"   # ""이면 바지의 원래 색
garment_auto: false        # true: 상의에 맞는 바지를 자동으로 선택
fps: 24
pose:
  pose_every: 2            # N프레임마다 자세 추정 실행
  segment_every: 2         # N프레임마다 피부/옷 분할 실행
  segmenter_gpu: true
  fallback: true           # 가까이 있을 때 RTMPose 사용
```

## 성능

M4 Pro MacBook Pro에서 720p, 30 fps 카메라로 측정했습니다.

| 상황 | CPU | 메모리 |
|---|---|---|
| 백그라운드 모드, 대기 중(첫 실행 전) | 약 0% | 약 200 MB |
| 백그라운드 모드, 실행 중 | 약 30~40% | 약 700 MB |
| 백그라운드 모드, 대기 중(실행한 뒤) | 약 0% | 약 150 MB |

부하를 줄이는 방법:

- 피부/옷 분할은 GPU에서 실행하며, 다리가 보이거나 상의 색을 읽어야 할 때만 동작합니다.
- 자세 추정은 두 프레임에 한 번 실행합니다. 빠른 움직임을 더 정확히 따라가려면 `pose_every: 1`로 설정하세요(CPU가 약 3분의 1 늘어납니다).
- 근거리용 대체 모델은 처음 필요할 때 불러옵니다. MediaPipe가 상반신을 잡고 있고 엉덩이가 화면 밖에 있을 때는 실행하지 않습니다.
- OpenCV는 단일 스레드로 실행합니다. 기본 설정에서는 프레임마다 하는 작은 작업까지 모든 코어에 나누어, 그것만으로 CPU의 3분의 1을 썼습니다.
- 자세 추정 모델은 CPU에서 실행합니다. macOS에서 MediaPipe의 GPU 모드는 프레임마다 메모리 누수가 생기기 때문입니다. `segmenter_gpu: false`로 설정하면 분할도 CPU로 되돌릴 수 있습니다(메모리는 약 400 MB 줄고 CPU는 늘어납니다).

부하를 더 줄이려면 `--fps 24`(또는 20)를 지정하고, `--no-preview`를 붙이거나 백그라운드 모드를 사용하세요.

## 작동 원리

**자세**: MediaPipe Pose Landmarker가 엉덩이, 무릎, 발목을 찾습니다. MediaPipe는 몸통 대부분이 보여야 동작하므로, 카메라에 가까이 앉아 허리와 다리만 보이는 프레임에서는 RTMPose가 대신 처리합니다(OpenMMLab의 YOLOX 인물 검출기와 26개 키포인트 몸·발 모델을 onnxruntime으로 실행). RTMPose 결과는 타당할 때만 사용합니다. 즉, 엉덩이가 화면 안에 있고, 적어도 한쪽 무릎이 보이며, MediaPipe가 어깨를 잡고 있다면 엉덩이가 어깨보다 충분히 아래에 있어야 합니다. 두 모델이 잠깐 놓치면 바지가 깜박이지 않도록 직전 자세를 300밀리초 동안 유지합니다. 미리보기에는 어느 모델을 쓰는지 표시됩니다(`pose mediapipe`, `rtmpose`, `hold`).

**다리**: 인물 마스크와 피부/옷 분할로 허벅지와 정강이의 여러 지점에서 다리 너비를 잽니다. 바지는 적어도 그 너비로 그리며, 허벅지가 맞닿는 부분에서는 양쪽 바지가 가운데에서 만납니다.

**상의에 맞추는 기능**: 어깨와 엉덩이 사이에서 상의 색을 읽고(옷 부분만, 손은 제외) 몇 초에 걸쳐 평활화합니다. 그런 다음 바지마다 점수를 매깁니다. 밝기 대비가 클수록 점수가 높고, 같은 계열 색에 밝기까지 비슷한 조합(네이비에 네이비 등)은 감점하며, 상의가 화려하면 차분한 바지를 우선합니다. 다른 바지가 뚜렷하게 앞선 상태가 1.5초 동안 이어질 때만 바지를 바꿉니다. 어깨가 보여야 하므로, 너무 가까이 앉으면 마지막 선택이 유지됩니다.

**바지 소재**: `garments/`의 각 폴더에는 정면에서 본 RGBA `texture.png`와 `garment.yaml`이 들어 있습니다. `garment.yaml`에는 기준점(다리마다 허리, 가랑이, 무릎, 밑단)과 장식선(솔기, 가장자리, 주름선, 스티치)이 적혀 있습니다. 텍스처를 크게 줄여서 보여 주면 가는 선이 사라지므로, 장식선은 화면에 선명한 선으로 직접 그리고 메시를 따라 구부립니다. 기본 제공 바지는 `scripts/make_garments.py`로 생성합니다. 바지를 바꾼 뒤에는 `scripts/export_web_garments.py`를 실행해 `site/garments/`에 있는 온라인 데모용 사본을 갱신하세요.

## 개발

```bash
.venv/bin/python -m pytest
node tests/js/mjpeg.test.js   # browser extension
```

온라인 데모는 `site/`에 있습니다(`index.html`은 회의실, `pants-engine.js`는 브라우저 안에서 도는 처리 과정, `garments/`는 내보낸 바지). 빌드 단계는 없습니다. `python -m http.server -d site 8000`으로 띄운 뒤 `http://localhost:8000/`을 열면 미리 볼 수 있습니다. `site/`를 바꾼 커밋을 `main`에 push하면 GitHub Pages에 자동으로 배포됩니다(`.github/workflows/pages.yml`).

모델이나 `data/`의 비공개 테스트 영상이 필요한 테스트는 파일이 없으면 건너뜁니다. `--record`로 녹화한 영상은 `data/`에 저장되며, 이 폴더는 커밋되지 않습니다.

## 서드파티 모델

| 모델 | 출처 | 라이선스 |
|---|---|---|
| Pose Landmarker, Selfie Multiclass Segmenter | Google MediaPipe | Apache-2.0 |
| RTMPose-s(Halpe-26), YOLOX-tiny(Human-Art) | OpenMMLab | Apache-2.0 |
| 웹용 MediaPipe Tasks Vision(온라인 데모, jsDelivr에서 불러옴) | Google MediaPipe | Apache-2.0 |

모델은 `scripts/download_models.py`로 내려받으며, 이 저장소에는 포함되어 있지 않습니다.
