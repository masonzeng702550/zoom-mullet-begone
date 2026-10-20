# meet-pants

[English](README.md) | **繁體中文** | [日本語](README.ja.md) | [한국어](README.ko.md)

視訊會議用的虛擬褲子。meet-pants 用姿勢模型追蹤你的腿，畫上一條跟著腿動的褲子，再把畫面送到虛擬鏡頭，讓 Google Meet、Zoom、Teams 等軟體選用。

## 功能

- **褲子跟著每條腿動**：追蹤腰、大腿、膝蓋和小腿，褲子邊緣也會逐段貼合實際的身形，腿粗腿細都蓋得住，兩腿中間也不會露出來。
- **和畫面融為一體**：自動配合畫面的光線、色調和鏡頭雜訊，邊緣柔化，前臂和手會保持在褲子前面。
- **近距離也能用**：坐得很近、畫面只拍到腰和腿時，會改用第二個姿勢模型。
- **依上衣搭配**：自動挑選跟上衣搭配的褲子樣式和顏色，也可以自己指定。
- **設定頁**：在本機網頁上選樣式和顏色，還能看到會議那頭收到的即時畫面。
- **瀏覽器擴充功能**：在 Chrome、Edge、Arc 的 Google Meet 和其他網站加入一個「meet-pants」鏡頭，不需要安裝任何鏡頭驅動。
- **背景模式**：常駐在選單列，只有在會議使用鏡頭時才啟動。

內建三種褲子：深藍西裝褲、卡其褲、牛仔褲，每一種都可以換顏色。

## 目前狀態

- 在 macOS（Apple 晶片）上開發和測試。
- Windows 和 Linux 應該可以使用，但還沒實測。在這兩個系統上，背景模式能得知瀏覽器分頁何時使用 meet-pants 鏡頭，但還無法得知桌面軟體何時打開虛擬鏡頭。
- 瀏覽器擴充功能支援以 Chromium 為基礎的瀏覽器（Chrome、Edge、Arc、Brave），目前還不支援 Safari 和 Firefox。
- 只要畫面中看得到髖部就會畫上褲子。自動判斷「有沒有穿褲子」還在規劃中。

## 需求

- Python 3.11 或 3.12
- 把畫面送進會議的方式，以下擇一或兩者都用：
  - **瀏覽器擴充功能**（Google Meet 等網頁會議，不需要另外安裝東西）：見下方「瀏覽器擴充功能（不需要 OBS）」一節。
  - **虛擬鏡頭驅動**（所有軟體，包括 Zoom、Teams 桌面版）：
    - **macOS / Windows**：[OBS Studio](https://obsproject.com/) 30 以上。打開一次 OBS，按「啟動虛擬攝影機」（Start Virtual Camera），再關掉 OBS。meet-pants 使用的是 OBS 安裝的鏡頭驅動，平常不需要開著 OBS。
    - **Linux**：[v4l2loopback](https://github.com/umlaeute/v4l2loopback)（用 `sudo modprobe v4l2loopback exclusive_caps=1` 載入，Chrome 才會列出它）。

## 安裝

```bash
uv venv --python 3.11
uv pip install -e ".[dev]"
python scripts/download_models.py
```

`download_models.py` 會把姿勢、分割和備援模型（約 75 MB）下載到 `models/`。

macOS 第一次執行時，系統會詢問是否允許終端機使用鏡頭。

## 快速開始

**背景模式（macOS，建議使用）：**

```bash
.venv/bin/python -m meet_pants --background
```

選單列會出現一個褲子圖示。進入會議後把鏡頭選成「meet-pants」（瀏覽器擴充功能）或「OBS Virtual Camera」，大約 2.5 秒後就會出現褲子。

**前景模式（所有系統）：**

```bash
.venv/bin/python -m meet_pants
```

會開啟預覽視窗，並立刻把畫面送到虛擬鏡頭。

## 瀏覽器擴充功能（不需要 OBS）

`browser-extension/` 裡的擴充功能會在每個網站加入一個名為「meet-pants」的鏡頭。在 Google Meet（或其他網站）選擇它，網站就會收到 meet-pants 的畫面。因為不需要虛擬鏡頭驅動，沒有安裝 OBS 也能使用。

**安裝（Chrome、Edge、Arc、Brave）：**

1. 打開 `chrome://extensions`（Edge 為 `edge://extensions`）。
2. 開啟「開發人員模式」。
3. 按「載入未封裝項目」，選擇這個專案的 `browser-extension` 資料夾。

**使用：**

1. 啟動 meet-pants，建議用背景模式：`.venv/bin/python -m meet_pants --background`。
2. 在 Google Meet：設定 → 視訊 → 攝影機 → **meet-pants**。其他網站在選擇鏡頭的地方也會看到它。
3. 工具列上的擴充功能按鈕會顯示 meet-pants 是否在執行，並提供設定頁的連結。

**隱私與安全：**

- 只有已經取得鏡頭權限的網站才能使用 meet-pants 鏡頭，規則和實體鏡頭完全一樣。
- 畫面經由 127.0.0.1 從 meet-pants 傳到瀏覽器，不會離開你的電腦。meet-pants 只接受來自瀏覽器擴充功能的連線（依據網頁無法偽造的 `Origin` 標頭），所以網站無法透過它讀取你的鏡頭。
- 在背景模式下，分頁選用 meet-pants 鏡頭時就會啟動，分頁停止使用後約 3 秒停止。

桌面軟體（Zoom、Teams、FaceTime）看不到擴充功能提供的鏡頭，仍然需要虛擬鏡頭驅動。

## 在會議和網站中使用

使用虛擬鏡頭驅動時，meet-pants 把畫面送到「OBS Virtual Camera」，系統會把它當成一般鏡頭，跟內建鏡頭一起列出。只要能選擇鏡頭的地方都能使用：

- **Google Meet**（任何瀏覽器）：設定 → 視訊 → 攝影機 → OBS Virtual Camera。
- **Chrome、Edge、Arc 上的其他網站**：點網址列的鏡頭圖示選擇，或在 `chrome://settings/content/camera` 一次設定給所有網站。
- **Safari 和 Firefox**：每個網站分別詢問，在鏡頭提示或網站設定中選 OBS Virtual Camera。
- **Zoom、Teams、FaceTime、Discord、Slack**：在各軟體的視訊設定中選 OBS Virtual Camera。

如果某個軟體一直使用內建鏡頭，meet-pants 無法接管：macOS 允許每個軟體直接開啟實體鏡頭，也沒有辦法在整個系統層級把它換掉。meet-pants 沒有執行時，虛擬鏡頭會顯示 OBS 的預設畫面。

## 背景模式

```bash
.venv/bin/python -m meet_pants --background
```

選單列圖示在待命時是空心的，使用中是實心的。

- **待命**：鏡頭關閉，幾乎不做任何事（CPU 約 0%）。每秒檢查兩次：有沒有瀏覽器分頁選用了 meet-pants 鏡頭，以及在 macOS 上有沒有軟體打開了 OBS Virtual Camera（透過 CoreMediaIO）。
- **會議打開鏡頭**：meet-pants 打開你的鏡頭，大約 2.5 秒後出現褲子。
- **瀏覽器分頁停止使用鏡頭**：約 3 秒後停止。由瀏覽器分頁啟動的執行不會動到 OBS Virtual Camera。
- **桌面軟體關閉 OBS Virtual Camera**：meet-pants 自己送出的畫面會讓虛擬鏡頭一直顯示為「使用中」，所以無法直接得知會議已經關閉。當鏡頭前連續一分鐘沒有人時，它會短暫停止送出畫面並重新檢查；如果已經沒有軟體在讀取鏡頭，就關閉鏡頭回到待命。如果會議結束後你還坐在電腦前，它會繼續執行，直到你離開畫面、結束程式，或在選單中關閉自動啟動。
- **選單**：目前狀態、「開啟設定…」、「會議開鏡頭時自動套用」、「結束 meet-pants」。

在 Windows 和 Linux 上，背景模式還無法得知桌面軟體何時打開虛擬鏡頭：有安裝虛擬鏡頭驅動時會一直執行；沒有安裝時只服務瀏覽器擴充功能，隨分頁啟動和停止。

執行過一次之後，記憶體會維持在約 700 MB，直到結束 meet-pants（Python 不會把用過的記憶體還給系統）。

## 設定頁

meet-pants 執行時，打開 `http://127.0.0.1:8765/`、在預覽視窗按 `S`，或在選單列選「開啟設定…」。可以：

- 選擇樣式：卡其褲、深藍西裝褲、牛仔褲；
- 選擇顏色：褲子原本的顏色、預設色票，或用取色器選任何顏色（布料的明暗、紋理和皺褶都會保留）；
- 開啟或關閉依上衣搭配；
- 查看會議收到的即時畫面（背景模式）。

修改會立刻顯示在畫面上，並存成下次啟動的預設值。`python -m meet_pants --settings` 可以在不開鏡頭的情況下只打開設定頁。

設定頁只在 127.0.0.1 上監聽，也只接受來自頁面本身的修改，其他網站無法更改你的設定。在設定檔中設定 `settings_port: 0` 可以關閉它。

## 指令列參數

| 參數 | 說明 |
|---|---|
| `--background` | 在選單列執行，會議打開鏡頭時自動啟動 |
| `--settings` | 只打開設定頁，不開鏡頭 |
| `--input 1` / `--input clip.mp4` | 鏡頭編號或影片檔 |
| `--resolution 1280x720`、`--fps 30` | 擷取解析度和畫面更新率 |
| `--model lite` | 較快但較不準的姿勢模型 |
| `--mode always` / `--mode off` | 看得到髖部就畫褲子，或完全不畫 |
| `--garment jeans_indigo` | 使用指定的褲子（`dress_navy`、`chino_khaki`、`jeans_indigo`），並關閉依上衣搭配 |
| `--auto-garment` / `--no-auto-garment` | 開啟或關閉依上衣搭配 |
| `--no-vcam` | 只開預覽，不送到虛擬鏡頭 |
| `--no-preview` | 只送到虛擬鏡頭，不開預覽視窗 |
| `--debug landmarks,masks,mesh,hud` | 預覽視窗的除錯圖層（`none` 全部隱藏） |
| `--record data/clip.mp4` | 同時錄下原始鏡頭畫面，方便重現問題 |
| `--config path.yaml` | 使用指定的設定檔 |

**預覽視窗按鍵**：`M` 開關褲子、`P` 換下一件（會關閉依上衣搭配）、`A` 開關依上衣搭配、`S` 開啟設定頁、`D` 切換除錯圖層（骨架 → 骨架加上人物遮罩（紫色）和皮膚（橘色） → 網格 → 不顯示）、`Esc` 或 `Q` 結束。

預覽畫面是鏡像的，虛擬鏡頭則不是，因為會議軟體會自己把你的自拍畫面鏡像。除錯圖層只會出現在預覽視窗。

## 設定檔

設定讀取自系統設定資料夾中的 YAML 檔：

| 系統 | 位置 |
|---|---|
| macOS | `~/Library/Application Support/meet-pants/config.yaml` |
| Windows | `%APPDATA%\meet-pants\config.yaml` |
| Linux | `~/.config/meet-pants/config.yaml` |

指令列參數會覆蓋設定檔。macOS 和 Windows 上舊位置的 `~/.config/meet-pants/config.yaml` 會自動搬到新位置。範例：

```yaml
garment: chino_khaki
garment_color: "#3c3f44"   # "" 表示使用褲子原本的顏色
garment_auto: false        # true：依上衣自動挑選
fps: 24
pose:
  pose_every: 2            # 每 N 張畫面跑一次姿勢模型
  segment_every: 2         # 每 N 張畫面跑一次皮膚 / 衣服分割
  segmenter_gpu: true
  fallback: true           # 近距離時使用 RTMPose
```

## 效能

在 M4 Pro MacBook Pro 上，使用 720p、30 fps 的鏡頭實測：

| 情況 | CPU | 記憶體 |
|---|---|---|
| 背景模式，待命中（第一次執行前） | 約 0% | 約 170 MB |
| 背景模式，待命中（執行過之後） | 約 0% | 約 700 MB |
| 執行中，畫面拍到上半身 | 約 30–40% | 約 650 MB |

省資源的做法：

- 皮膚 / 衣服分割器在 GPU 上執行，而且只在看得到腿或需要取上衣顏色時才跑。
- 姿勢模型每兩張畫面跑一次。設定 `pose_every: 1` 可以更即時地追蹤快速動作（CPU 約多三分之一）。
- 近距離用的備援模型第一次需要時才載入；MediaPipe 看得到上半身、而髖部在畫面外時，就不會執行。
- OpenCV 限制為單執行緒。它預設會把每張畫面的小工作分到所有核心，光是這樣就用掉三分之一的 CPU。
- 姿勢模型維持在 CPU 上執行，因為 MediaPipe 在 macOS 的 GPU 模式每張畫面都會漏記憶體。設定 `segmenter_gpu: false` 可以把分割器也改回 CPU（記憶體少約 400 MB，CPU 會增加）。

想更省資源：使用 `--fps 24`（或 20），並加上 `--no-preview` 或改用背景模式。

## 運作原理

**姿勢**：MediaPipe Pose Landmarker 找出髖部、膝蓋和腳踝。MediaPipe 需要看到大部分的軀幹，所以坐得很近、只拍到腰和腿時，那些畫面會改由 RTMPose 處理（OpenMMLab 的 YOLOX 人體偵測器，加上 26 個關鍵點的身體與腳部模型，用 onnxruntime 執行）。RTMPose 的結果必須合理才會採用：髖部在畫面內、至少看得到一邊膝蓋，而且 MediaPipe 看得到肩膀時，髖部要在肩膀下方夠遠的地方。如果兩個模型都短暫失誤，會沿用上一個姿勢 300 毫秒，避免褲子閃爍。預覽畫面會顯示目前使用哪一個（`pose mediapipe`、`rtmpose` 或 `hold`）。

**腿**：用人物遮罩和皮膚 / 衣服分割，在大腿和小腿的多個位置量出每條腿的寬度。褲子至少會畫得一樣寬；大腿併攏的地方，兩條褲管會在中間會合。

**依上衣搭配**：在肩膀到髖部之間取上衣的顏色（只取衣服，不含手），並在幾秒內平滑化，再為每件褲子評分：明暗對比越大分數越高，同色系又亮度相近（例如深藍配深藍）會扣分，上衣很鮮豔時偏好比較素的褲子。只有在另一件褲子明顯勝出並持續 1.5 秒時才會更換。必須看得到肩膀，所以坐得太近時會維持上一次的選擇。

**褲子素材**：`garments/` 裡的每個資料夾包含一張正面的 RGBA `texture.png`，以及一份 `garment.yaml`，裡面有錨點（每條腿的腰、褲襠、膝蓋和褲腳）和裝飾線（縫線、邊線、褲摺和車縫線）。裝飾線會在螢幕上直接畫成清楚的線條，並隨網格彎曲，因為材質縮小顯示時，細節會消失。內建的褲子由 `scripts/make_garments.py` 產生。

## 開發

```bash
.venv/bin/python -m pytest
node tests/js/mjpeg.test.js   # browser extension
```

需要模型或 `data/` 中私人測試影片的測試，在檔案不存在時會自動略過。用 `--record` 錄下的影片會存在 `data/`，這個資料夾不會被 commit。

## 第三方模型

| 模型 | 來源 | 授權 |
|---|---|---|
| Pose Landmarker、Selfie Multiclass Segmenter | Google MediaPipe | Apache-2.0 |
| RTMPose-s（Halpe-26）、YOLOX-tiny（Human-Art） | OpenMMLab | Apache-2.0 |

模型由 `scripts/download_models.py` 下載，不包含在這個儲存庫中。
