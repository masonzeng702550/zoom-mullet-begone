"""Menu bar / system tray icon for the background service (pystray).

pystray's loop must own the main thread (on macOS it is the Cocoa app loop),
so the service runs in its own thread and menu updates from it are handed to
the main thread.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from PIL import Image, ImageDraw

from zoom_mullet_begone.service import STATUS_TEXT, BackgroundService

ICON_SIZE = 64


def pants_icon(active: bool) -> Image.Image:
    """A small pair of pants; filled while the camera is in use, outlined otherwise."""
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = ICON_SIZE / 64
    outline = [(14, 6), (50, 6), (54, 58), (38, 58), (32, 26), (26, 58), (10, 58)]
    points = [(x * s, y * s) for x, y in outline]
    color = (0, 0, 0, 255)
    if active:
        d.polygon(points, fill=color)
    else:
        d.line(points + [points[0]], fill=color, width=round(5 * s), joint="curve")
    d.rectangle((14 * s, 6 * s, 50 * s, 13 * s), fill=color)  # waistband
    return img


def _on_main_thread(fn: Callable[[], None]) -> None:
    if sys.platform == "darwin":
        from PyObjCTools import AppHelper

        AppHelper.callAfter(fn)
    else:
        fn()


def run_tray(service: BackgroundService) -> int:
    import pystray

    def status(_item: object) -> str:
        return STATUS_TEXT.get(service.state, service.state)

    def open_settings(_icon: object, _item: object) -> None:
        if service.server is not None:
            service.server.open()

    def toggle_auto(_icon: object, _item: object) -> None:
        service.set_auto_start(not service.auto_start)

    def quit_app(icon: pystray.Icon, _item: object) -> None:
        service.quit()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(status, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("開啟設定…", open_settings, default=True, enabled=lambda _i: service.server is not None),
        pystray.MenuItem("會議開鏡頭時自動套用", toggle_auto, checked=lambda _i: service.auto_start),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("結束 Zoom Mullet Begone", quit_app),
    )
    icon = pystray.Icon("zoom-mullet-begone", pants_icon(False), "Zoom Mullet Begone", menu)

    def refresh() -> None:
        def apply() -> None:
            icon.icon = pants_icon(service.state == "active")
            icon.update_menu()

        _on_main_thread(apply)

    def setup(icon: pystray.Icon) -> None:
        icon.visible = True
        service.on_change = refresh
        service.start()

    try:
        icon.run(setup=setup)
    except KeyboardInterrupt:
        pass
    finally:
        service.quit()
    return 0
