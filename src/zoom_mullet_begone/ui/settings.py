"""Garment settings page: a small local web server (stdlib only).

The page lets the user pick the pants style and color, or leave it to the
shirt matching. Choices apply to the running pipeline at once (through
`SettingsHub`) and are saved to the config file, so they are the default
next time.

It listens on 127.0.0.1 only and accepts changes only from its own page
(Host / Origin checks), so other websites cannot change the settings.
"""

from __future__ import annotations

import json
import select
import socket
import sys
import threading
import webbrowser
from dataclasses import asdict, dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np
import yaml

from zoom_mullet_begone.render.garment import GarmentError, list_garments, load_garment, parse_color, recolor_texture
from zoom_mullet_begone.ui.browser_feed import FrameFeed, is_extension_request

PAGE = Path(__file__).with_name("settings.html")
MJPEG_BOUNDARY = "zoommulletbegoneframe"
THUMB_SIZE = (120, 180)  # w, h
PRESET_COLORS = (
    ("黑", "#1c1c1c"),
    ("炭灰", "#3c3f44"),
    ("灰", "#6b6b6b"),
    ("深藍", "#1f2a44"),
    ("卡其", "#c8b48c"),
    ("米白", "#e8e4dc"),
    ("橄欖綠", "#4b5a32"),
    ("酒紅", "#6e1e28"),
    ("咖啡", "#5a3e2b"),
)


@dataclass(frozen=True)
class GarmentChoice:
    garment: str
    color: str = ""  # "#rrggbb" or "" for the garment's own color
    auto: bool = True


def normalize_choice(data: dict[str, Any], garments: list[str], current: GarmentChoice) -> GarmentChoice:
    """Validate a (partial) choice from the page; raises GarmentError."""
    garment = str(data.get("garment", current.garment))
    if garment not in garments:
        raise GarmentError(f"unknown garment: {garment}")
    color = str(data.get("color", current.color) or "")
    if color:
        b, g, r = parse_color(color)
        color = f"#{r:02x}{g:02x}{b:02x}"
    auto = data.get("auto", current.auto)
    if not isinstance(auto, bool):
        raise GarmentError("auto must be true or false")
    return GarmentChoice(garment, color, auto)


def save_choice(path: Path, choice: GarmentChoice) -> None:
    """Write the choice into the YAML config file, keeping its other settings."""
    data: dict[str, Any] = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    data.update(garment=choice.garment, garment_color=choice.color, garment_auto=choice.auto)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


class SettingsHub:
    """The current garment choice, shared between the page's server thread and the main loop."""

    def __init__(self, garments_dir: Path, choice: GarmentChoice, save_path: Path | None):
        self.garments_dir = Path(garments_dir).expanduser()
        self.garment_ids = list_garments(self.garments_dir)
        self._save_path = save_path
        self._lock = threading.Lock()
        self._choice = choice
        self.version = 0
        # name and a thumbnail-sized texture per garment; the full textures stay
        # with the pipeline's wardrobe
        self._garments: dict[str, tuple[str, np.ndarray]] = {}
        self._thumbs: dict[tuple[str, str], bytes] = {}
        # set by the background service: what it is doing, and a small JPEG of
        # the latest output frame for the page's live preview
        self.status = ""
        self._preview: bytes | None = None
        self.feed = FrameFeed()  # live video for the browser extension

    def set_preview(self, jpeg: bytes | None) -> None:
        with self._lock:
            self._preview = jpeg

    def preview(self) -> bytes | None:
        with self._lock:
            return self._preview

    @property
    def choice(self) -> GarmentChoice:
        with self._lock:
            return self._choice

    def set(self, choice: GarmentChoice, save: bool = True) -> None:
        with self._lock:
            if choice == self._choice:
                return
            self._choice = choice
            self.version += 1
        if save and self._save_path is not None:
            save_choice(self._save_path, choice)

    def update(self, data: dict[str, Any]) -> GarmentChoice:
        """Apply a change from the page (validated and saved)."""
        choice = normalize_choice(data, self.garment_ids, self.choice)
        self.set(choice)
        return choice

    def _garment(self, garment_id: str) -> tuple[str, np.ndarray]:
        with self._lock:
            if garment_id not in self._garments:
                garment = load_garment(self.garments_dir, garment_id)
                small = cv2.resize(garment.texture, THUMB_SIZE, interpolation=cv2.INTER_AREA)
                self._garments[garment_id] = (garment.name, small)
            return self._garments[garment_id]

    def thumbnail(self, garment_id: str, color: str) -> bytes:
        """PNG of the garment (recolored), small enough for the page."""
        key = (garment_id, color)
        with self._lock:
            cached = self._thumbs.get(key)
        if cached is not None:
            return cached
        small = self._garment(garment_id)[1]
        if color:
            small = recolor_texture(small, parse_color(color))
        ok, png = cv2.imencode(".png", small)
        if not ok:
            raise GarmentError("could not encode thumbnail")
        data = png.tobytes()
        with self._lock:
            self._thumbs[key] = data
        return data

    def state(self) -> dict[str, Any]:
        return {
            **asdict(self.choice),
            "status": self.status,
            "garments": [{"id": gid, "name": self._garment(gid)[0]} for gid in self.garment_ids],
            "presets": [{"name": n, "color": c} for n, c in PRESET_COLORS],
        }


def _handler(hub: SettingsHub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        @property
        def allowed_hosts(self) -> set[str]:
            port = self.server.server_address[1]
            return {f"127.0.0.1:{port}", f"localhost:{port}"}

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - quiet
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: Any) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _same_origin(self) -> bool:
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            return host in self.allowed_hosts and (origin is None or origin == f"http://{host}")

        def do_GET(self) -> None:
            if self.headers.get("Host", "") not in self.allowed_hosts:  # DNS rebinding
                self._send(403, b"forbidden", "text/plain")
                return
            url = urlparse(self.path)
            if url.path == "/":
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/settings":
                self._json(200, hub.state())
            elif url.path == "/stream.mjpg":
                self._stream()
            elif url.path == "/live.jpg":
                jpeg = hub.preview()
                if jpeg is None:
                    self.send_response(204)
                    self.end_headers()
                else:
                    self._send(200, jpeg, "image/jpeg")
            elif url.path.startswith("/preview/") and url.path.endswith(".png"):
                gid = url.path[len("/preview/") : -len(".png")]
                color = parse_qs(url.query).get("color", [""])[0]
                if gid not in hub.garment_ids:
                    self._send(404, b"not found", "text/plain")
                    return
                try:
                    if color:
                        normalize_choice({"garment": gid, "color": color}, hub.garment_ids, hub.choice)
                    self._send(200, hub.thumbnail(gid, color), "image/png")
                except GarmentError as e:
                    self._send(400, str(e).encode(), "text/plain; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain")

        def _client_gone(self) -> bool:
            """True once the browser closed the connection (readable with nothing to read)."""
            try:
                readable, _, _ = select.select([self.connection], [], [], 0)
                return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
            except OSError:
                return True

        def _stream(self) -> None:
            """MJPEG for the browser extension; only extensions may read it."""
            if not is_extension_request(self.headers):
                seen = {k: self.headers.get(k) for k in ("Origin", "Sec-Fetch-Site", "Sec-Fetch-Mode")}
                print(f"browser stream refused, not from the extension: {seen}", file=sys.stderr)
                self._send(403, b"only the zoom-mullet-begone browser extension may read the stream", "text/plain")
                return
            print("browser stream: a tab connected")
            self.send_response(200)
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            hub.feed.connect()
            seq = 0
            try:
                while not hub.feed.closed:
                    item = hub.feed.next_frame(seq)
                    if item is None:
                        if self._client_gone():  # no frame to write, so check the socket itself
                            break
                        continue
                    seq, jpeg = item
                    self.wfile.write(
                        f"--{MJPEG_BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n\r\n".encode()
                        + jpeg
                        + b"\r\n"
                    )
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # the page closed the camera
            finally:
                hub.feed.disconnect()

        def do_POST(self) -> None:
            if not self._same_origin():
                self._send(403, b"forbidden", "text/plain")
                return
            if urlparse(self.path).path != "/api/settings":
                self._send(404, b"not found", "text/plain")
                return
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                self._send(415, b"expected application/json", "text/plain")
                return
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 10_000)
                data = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(data, dict):
                    raise GarmentError("expected a JSON object")
                hub.update(data)
            except (ValueError, GarmentError) as e:
                self._json(400, {"error": str(e)})
                return
            self._json(200, hub.state())

    return Handler


class SettingsServer:
    def __init__(self, hub: SettingsHub, port: int):
        self._hub = hub
        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), _handler(hub))  # port 0: any free port
        self._httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._httpd.server_address[1]}/"
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="settings", daemon=True)

    def start(self) -> SettingsServer:
        self._thread.start()
        return self

    def open(self) -> None:
        webbrowser.open(self.url)

    def close(self) -> None:
        self._hub.feed.close()  # ends open browser streams
        self._httpd.shutdown()
        self._httpd.server_close()

    def __enter__(self) -> SettingsServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.close()


def effective(choice: GarmentChoice) -> GarmentChoice:
    """What to draw: shirt matching uses the garments' own colors."""
    return replace(choice, color="") if choice.auto else choice
