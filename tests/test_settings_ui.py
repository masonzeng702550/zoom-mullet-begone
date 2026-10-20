"""Garment recoloring, the settings page server, and applying its choices."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pytest
import yaml

from meet_pants.pipeline import Wardrobe, apply_choice
from meet_pants.render.garment import GarmentError, load_garment, parse_color, recolor_texture, with_color
from meet_pants.ui.settings import GarmentChoice, SettingsHub, SettingsServer, effective, normalize_choice, save_choice

GARMENTS = Path(__file__).resolve().parents[1] / "garments"
IDS = ["chino_khaki", "dress_navy", "jeans_indigo"]


def test_parse_color() -> None:
    assert parse_color("#6e1e28") == (0x28, 0x1E, 0x6E)  # BGR
    with pytest.raises(GarmentError):
        parse_color("red")


def test_recolor_keeps_shading_and_alpha() -> None:
    texture = np.zeros((4, 4, 4), np.uint8)
    texture[..., 3] = 255
    texture[:3, :, :3] = 100  # lit fabric (the median)
    texture[3:, :, :3] = 50  # a fold, half as bright
    texture[0, 0, 3] = 0  # transparent pixel stays as it was
    out = recolor_texture(texture, (40, 40, 200))
    assert (out[..., 3] == texture[..., 3]).all()
    lit, fold = out[1, 1, :3].astype(int), out[3, 1, :3].astype(int)
    assert lit[2] > lit[0]  # red now
    assert fold[2] == pytest.approx(lit[2] / 2, abs=2)  # the fold is still half as bright
    assert (out[0, 0] == texture[0, 0]).all()


def test_with_color_rebuilds_the_pyramid() -> None:
    garment = load_garment(GARMENTS, "chino_khaki")
    red = with_color(garment, "#6e1e28")
    assert red.texture is not garment.texture and red.pyramid[0] is red.texture
    assert with_color(garment, "") is garment


def test_normalize_choice() -> None:
    current = GarmentChoice("dress_navy", "", True)
    assert normalize_choice({"color": "#ABCDEF"}, IDS, current) == GarmentChoice("dress_navy", "#abcdef", True)
    assert normalize_choice({"garment": "jeans_indigo", "auto": False}, IDS, current).auto is False
    for bad in ({"garment": "shorts"}, {"color": "blue"}, {"auto": "yes"}):
        with pytest.raises(GarmentError):
            normalize_choice(bad, IDS, current)


def test_save_keeps_other_settings(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("fps: 24\ngarment: dress_navy\n", encoding="utf-8")
    save_choice(path, GarmentChoice("jeans_indigo", "#6e1e28", False))
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data == {"fps": 24, "garment": "jeans_indigo", "garment_color": "#6e1e28", "garment_auto": False}


def test_auto_uses_the_garments_own_colors() -> None:
    assert effective(GarmentChoice("dress_navy", "#6e1e28", True)).color == ""
    assert effective(GarmentChoice("dress_navy", "#6e1e28", False)).color == "#6e1e28"


def test_apply_choice_dresses_the_wardrobe() -> None:
    wardrobe = Wardrobe(GARMENTS, "dress_navy")
    auto, matcher = apply_choice(GarmentChoice("jeans_indigo", "#6e1e28", False), wardrobe, None)
    assert not auto and matcher is None
    assert wardrobe.current.id == "jeans_indigo" and wardrobe.color == "#6e1e28"
    auto, matcher = apply_choice(GarmentChoice("chino_khaki", "#6e1e28", True), wardrobe, None)
    assert auto and matcher is not None and matcher.current == "chino_khaki"
    assert wardrobe.color == ""  # matching uses the garments' own colors


def _request(url: str, data: dict | None = None, origin: str | None = None) -> tuple[int, dict | bytes]:
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if origin:
        headers["Origin"] = origin
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, body, headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = r.read()
            return r.status, json.loads(raw) if r.headers.get_content_type() == "application/json" else raw
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_server_applies_and_saves(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    hub = SettingsHub(GARMENTS, GarmentChoice("dress_navy", "", True), path)
    with SettingsServer(hub, 0) as server:
        status, state = _request(server.url + "api/settings")
        assert status == 200 and [g["id"] for g in state["garments"]] == IDS

        status, state = _request(server.url + "api/settings", {"garment": "jeans_indigo", "auto": False}, server.url[:-1])
        assert status == 200 and state["garment"] == "jeans_indigo" and state["auto"] is False
        assert hub.version == 1 and hub.choice == GarmentChoice("jeans_indigo", "", False)
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["garment"] == "jeans_indigo"

        status, png = _request(server.url + "preview/chino_khaki.png?color=%236e1e28")
        assert status == 200 and png[:8] == b"\x89PNG\r\n\x1a\n"

        # Another website cannot change the settings.
        status, _ = _request(server.url + "api/settings", {"auto": True}, "https://example.com")
        assert status == 403 and hub.choice.auto is False
        status, _ = _request(server.url + "api/settings", {"color": "red"}, server.url[:-1])
        assert status == 400


def test_browser_stream_only_for_extensions(tmp_path: Path) -> None:
    import http.client
    import threading
    import time as _time

    hub = SettingsHub(GARMENTS, GarmentChoice("dress_navy", "", True), None)
    with SettingsServer(hub, 0) as server:
        port = int(server.url.rsplit(":", 1)[1].strip("/"))

        def get(headers: dict[str, str]) -> http.client.HTTPResponse:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/stream.mjpg", headers=headers)
            return conn.getresponse()

        page = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors"}
        # Websites (fetch, <img>, no-cors) and bare local clients cannot read the camera.
        for headers in (
            {},
            {"Origin": "https://meet.google.com", **page},
            {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "image"},
            {"Origin": "http://127.0.0.1:%d" % port, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors"},
            {"Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate"},  # typed into the address bar
        ):
            r = get(headers)
            assert r.status == 403, headers
            r.read()
        assert hub.feed.clients == 0

        # What Chrome sends for the extension's fetch under host permissions.
        r = get({"Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"})
        assert r.status == 200
        r.close()
        assert wait_until(lambda: hub.feed.clients == 0)

        r = get({"Origin": "chrome-extension://abcdefghijklmnop"})
        assert r.status == 200
        assert r.getheader("Content-Type").startswith("multipart/x-mixed-replace")
        assert wait_until(lambda: hub.feed.clients == 1)

        frame = np.zeros((72, 128, 3), np.uint8)
        stop = threading.Event()

        def publish() -> None:
            while not stop.is_set():
                hub.feed.publish(frame)
                _time.sleep(0.02)

        threading.Thread(target=publish, daemon=True).start()
        head = r.read(200)
        stop.set()
        assert head.startswith(b"--meetpantsframe\r\nContent-Type: image/jpeg\r\nContent-Length: ")
        assert b"\xff\xd8" in head  # JPEG start
        r.close()
    assert hub.feed.closed


def wait_until(condition, timeout: float = 3.0) -> bool:
    import time as _time

    end = _time.time() + timeout
    while _time.time() < end:
        if condition():
            return True
        _time.sleep(0.02)
    return False
