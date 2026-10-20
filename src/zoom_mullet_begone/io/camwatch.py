"""Is any app using the virtual camera? (for starting when a meeting opens it)

macOS: CoreMediaIO's kCMIODevicePropertyDeviceIsRunningSomewhere on the
"OBS Virtual Camera" device turns true while any process streams it. Our own
frame sending counts too, so while zoom-mullet-begone sends frames the answer is only
meaningful after briefly stopping (see the background service).

Called through ctypes: no extra packages and no camera permission needed.
Other systems: not supported yet (`in_use()` returns None).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import struct
import sys

VIRTUAL_CAMERA_NAME = "OBS Virtual Camera"


def _fourcc(code: str) -> int:
    return struct.unpack(">I", code.encode())[0]


class _Address(ctypes.Structure):
    _fields_ = [("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("element", ctypes.c_uint32)]


_SYSTEM_OBJECT = 1
_SCOPE_GLOBAL = _fourcc("glob")
_ELEMENT_MAIN = 0
_DEVICES = _fourcc("dev#")
_NAME = _fourcc("lnam")
_RUNNING_SOMEWHERE = _fourcc("gone")
_UTF8 = 0x08000100


class CameraWatcher:
    """Answers whether a named camera device is being used by any process."""

    def __init__(self, device_name: str = VIRTUAL_CAMERA_NAME):
        self.device_name = device_name
        self._device: int | None = None
        self._cmio = self._cf = None
        if sys.platform == "darwin":
            try:
                self._cmio = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreMediaIO"))
                self._cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
            except (OSError, TypeError):
                self._cmio = self._cf = None
        if self._cmio is not None:
            self._cmio.CMIOObjectGetPropertyDataSize.argtypes = [
                ctypes.c_uint32, ctypes.POINTER(_Address), ctypes.c_uint32, ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint32),
            ]  # fmt: skip
            self._cmio.CMIOObjectGetPropertyData.argtypes = [
                ctypes.c_uint32, ctypes.POINTER(_Address), ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
            ]  # fmt: skip
            self._cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
            self._cf.CFRelease.argtypes = [ctypes.c_void_p]

    @property
    def supported(self) -> bool:
        return self._cmio is not None

    def _get(self, obj: int, selector: int, out: ctypes._SimpleCData | ctypes.Array) -> int:
        address = _Address(selector, _SCOPE_GLOBAL, _ELEMENT_MAIN)
        used = ctypes.c_uint32()
        return self._cmio.CMIOObjectGetPropertyData(
            obj, ctypes.byref(address), 0, None, ctypes.sizeof(out), ctypes.byref(used), ctypes.byref(out)
        )

    def devices(self) -> dict[str, int]:
        """Camera name -> CoreMediaIO object id."""
        if not self.supported:
            return {}
        address = _Address(_DEVICES, _SCOPE_GLOBAL, _ELEMENT_MAIN)
        size = ctypes.c_uint32()
        if self._cmio.CMIOObjectGetPropertyDataSize(_SYSTEM_OBJECT, ctypes.byref(address), 0, None, ctypes.byref(size)):
            return {}
        ids = (ctypes.c_uint32 * (size.value // 4))()
        if self._get(_SYSTEM_OBJECT, _DEVICES, ids):
            return {}
        found = {}
        for device in ids:
            ref = ctypes.c_void_p()
            if self._get(device, _NAME, ref) or not ref.value:
                continue
            buf = ctypes.create_string_buffer(512)
            if self._cf.CFStringGetCString(ref, buf, len(buf), _UTF8):
                found[buf.value.decode("utf-8", "replace")] = int(device)
            self._cf.CFRelease(ref)
        return found

    def in_use(self) -> bool | None:
        """True if any process streams the device, False if none, None if unknown
        (not macOS, or the virtual camera is not installed)."""
        if not self.supported:
            return None
        if self._device is None:
            self._device = self.devices().get(self.device_name)
            if self._device is None:
                return None
        value = ctypes.c_uint32()
        if self._get(self._device, _RUNNING_SOMEWHERE, value):
            self._device = None  # device went away (OBS reinstalled?); look it up again next time
            return None
        return bool(value.value)
