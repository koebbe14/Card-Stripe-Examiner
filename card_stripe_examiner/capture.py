"""Keyboard-wedge capture for the Adesso MSR-100.

The reader is a USB keyboard. Its keystrokes are taken from Windows Raw Input
for that device, so they are still captured when no text box has focus.
"""

from __future__ import annotations

import struct
import sys
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, QSettings, QTimer, Signal

# US scan codes (set 1). A wedge reader sends these whether or not Windows is
# using a US layout, so the map is fixed rather than taken from ToUnicode.
_UNSHIFTED = {
    0x02: "1",
    0x03: "2",
    0x04: "3",
    0x05: "4",
    0x06: "5",
    0x07: "6",
    0x08: "7",
    0x09: "8",
    0x0A: "9",
    0x0B: "0",
    0x0C: "-",
    0x0D: "=",
    0x10: "q",
    0x11: "w",
    0x12: "e",
    0x13: "r",
    0x14: "t",
    0x15: "y",
    0x16: "u",
    0x17: "i",
    0x18: "o",
    0x19: "p",
    0x1A: "[",
    0x1B: "]",
    0x1E: "a",
    0x1F: "s",
    0x20: "d",
    0x21: "f",
    0x22: "g",
    0x23: "h",
    0x24: "j",
    0x25: "k",
    0x26: "l",
    0x27: ";",
    0x28: "'",
    0x2B: "\\",
    0x2C: "z",
    0x2D: "x",
    0x2E: "c",
    0x2F: "v",
    0x30: "b",
    0x31: "n",
    0x32: "m",
    0x33: ",",
    0x34: ".",
    0x35: "/",
    0x39: " ",
}
_SHIFTED = {
    0x02: "!",
    0x03: "@",
    0x04: "#",
    0x05: "$",
    0x06: "%",
    0x07: "^",
    0x08: "&",
    0x09: "*",
    0x0A: "(",
    0x0B: ")",
    0x0C: "_",
    0x0D: "+",
    0x1A: "{",
    0x1B: "}",
    0x27: ":",
    0x28: '"',
    0x2B: "|",
    0x33: "<",
    0x34: ">",
    0x35: "?",
}
_NUMPAD = {
    0x52: "0",
    0x4F: "1",
    0x50: "2",
    0x51: "3",
    0x4B: "4",
    0x4C: "5",
    0x4D: "6",
    0x47: "7",
    0x48: "8",
    0x49: "9",
}
_SHIFT_VKEYS = {0x10, 0xA0, 0xA1}
_RI_KEY_BREAK = 0x01
_RI_KEY_E0 = 0x02
_VK_RETURN = 0x0D


def scancode_char(make_code: int, shift: bool, extended: bool = False) -> str | None:
    if not extended and make_code in _NUMPAD:
        return _NUMPAD[make_code]
    table = _SHIFTED if shift else _UNSHIFTED
    if make_code in table:
        return table[make_code]
    if make_code in _UNSHIFTED and _UNSHIFTED[make_code].isalpha():
        letter = _UNSHIFTED[make_code]
        return letter.upper() if shift else letter
    return None


def is_enter(make_code: int, vkey: int) -> bool:
    return make_code == 0x1C or vkey == _VK_RETURN


_VK_CHARS = {
    0xBA: (";", ":"),
    0xBB: ("=", "+"),
    0xBC: (",", "<"),
    0xBD: ("-", "_"),
    0xBE: (".", ">"),
    0xBF: ("/", "?"),
    0xDB: ("[", "{"),
    0xDC: ("\\", "|"),
    0xDD: ("]", "}"),
    0xDE: ("'", '"'),
    0x20: (" ", " "),
}
_VK_SHIFTED_DIGITS = ")!@#$%^&*("


def vkey_char(vkey: int, shift: bool) -> str | None:
    if 0x41 <= vkey <= 0x5A:
        letter = chr(vkey)
        return letter if shift else letter.lower()
    if 0x30 <= vkey <= 0x39:
        if shift:
            return _VK_SHIFTED_DIGITS[vkey - 0x30]
        return chr(vkey)
    pair = _VK_CHARS.get(vkey)
    if pair is None:
        return None
    return pair[1] if shift else pair[0]


def looks_like_swipe(text: str) -> bool:
    if any(sentinel in text for sentinel in "%;+"):
        return True
    digits = sum(character.isdigit() for character in text)
    return len(text) >= 12 and digits >= 12


class ReaderCapture(QObject):
    swipe_ready = Signal(str)
    bound = Signal(str)
    unavailable = Signal()
    activity = Signal()
    rejected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("CardStripeExaminer", "CardStripeExaminer")
        self.device_name = str(self.settings.value("reader_device", "") or "")
        if self.device_name == "window":
            self.device_name = ""
            self.settings.remove("reader_device")
        self.identifying = False
        self.listening = bool(self.device_name)
        self.available = False
        self.raw_events = 0
        self._chars: list[str] = []
        self._buffer_device: str | None = None
        self._buffers: dict[str, list[str]] = {}
        self._shift: dict[str, bool] = {}
        self._last_at: dict[str, float] = {}
        self._legacy_pending = 0
        self._hwnd = 0
        self._names: dict[int, str] = {}
        self._user32 = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(450)
        self.timer.timeout.connect(self._on_idle)

    def offer_qt_key(
        self,
        text: str,
        enter: bool,
        focus_is_text: bool = False,
        autorepeat: bool = False,
    ) -> bool:
        """Collect a key typed into this window. True means the key belongs to a swipe."""
        if self.available or autorepeat or (not self.identifying and not self.listening and not self._chars):
            return False
        character = text if text and text.isprintable() else ""
        if not self._chars:
            if self.identifying:
                if not character and not enter:
                    return False
            elif enter or not character:
                return False
            elif focus_is_text and character[0] not in "%;+":
                return False
            elif character[0] not in "%;+0123456789":
                return False
        if enter:
            self._finish()
            return True
        if not character:
            return False
        if not self._chars:
            self.activity.emit()
        self._chars.append(character)
        self._buffer_device = self._buffer_device or "window"
        self.timer.start()
        return True

    def take_legacy_key(self) -> bool:
        """Swallow the matching on-screen key so a swipe is not also typed into the case."""
        if self._legacy_pending <= 0:
            return False
        self._legacy_pending -= 1
        return True

    def attach(self, hwnd: int) -> None:
        if sys.platform != "win32":
            self.unavailable.emit()
            return
        self._hwnd = int(hwnd)
        try:
            import ctypes

            user32 = ctypes.windll.user32
            header_size = 24 if struct.calcsize("P") == 8 else 16

            class RawInputDevice(ctypes.Structure):
                _fields_ = [
                    ("usUsagePage", wintypes.USHORT),
                    ("usUsage", wintypes.USHORT),
                    ("dwFlags", wintypes.DWORD),
                    ("hwndTarget", wintypes.HWND),
                ]

            user32.RegisterRawInputDevices.argtypes = [
                ctypes.POINTER(RawInputDevice),
                wintypes.UINT,
                wintypes.UINT,
            ]
            user32.RegisterRawInputDevices.restype = wintypes.BOOL
            user32.GetRawInputData.argtypes = [
                ctypes.c_void_p,
                wintypes.UINT,
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.UINT),
                wintypes.UINT,
            ]
            user32.GetRawInputData.restype = wintypes.UINT
            user32.GetRawInputDeviceInfoW.argtypes = [
                ctypes.c_void_p,
                wintypes.UINT,
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.UINT),
            ]
            user32.GetRawInputDeviceInfoW.restype = wintypes.UINT

            device = RawInputDevice()
            device.usUsagePage = 0x01
            device.usUsage = 0x06
            device.dwFlags = 0x00000100
            device.hwndTarget = hwnd
            ok = user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device))
            if not ok:
                self.unavailable.emit()
                return
            self._user32 = user32
            self._header_size = header_size
            self._ctypes = ctypes
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            self.available = True
        except Exception:
            self.unavailable.emit()

    def begin_identify(self) -> None:
        self.identifying = True
        self._reset_buffer()
        self._buffers.clear()
        self._shift.clear()
        self._last_at.clear()

    def handle_native(self, message) -> None:
        try:
            contents = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError, OverflowError):
            return
        if int(contents.message) != 0x00FF:
            return
        self.raw_events += 1
        self.handle_wm_input(int(contents.lParam))

    def handle_wm_input(self, lparam: int) -> None:
        parsed = self._read_keyboard(lparam)
        if parsed is None:
            return
        handle, make_code, flags, vkey = parsed
        if not handle:
            return
        self.push_raw_key(self._device_name(handle), make_code, flags, vkey)

    def push_raw_key(self, device: str, make_code: int, flags: int, vkey: int) -> None:
        if not device:
            return
        key_up = bool(flags & _RI_KEY_BREAK)
        extended = bool(flags & _RI_KEY_E0)
        shift_key = vkey in _SHIFT_VKEYS or make_code in {0x2A, 0x36}
        if not self.identifying and not self._is_bound(device) and not self._buffers.get(device):
            return
        if shift_key:
            self._shift[device] = not key_up
            return
        if key_up:
            return
        if is_enter(make_code, vkey):
            self._note_legacy()
            self._finish_device(device)
            return
        character = scancode_char(make_code, self._shift.get(device, False), extended)
        if character is None:
            character = vkey_char(vkey, self._shift.get(device, False))
        if not character:
            return
        self._note_legacy()
        buffer = self._buffers.setdefault(device, [])
        if not buffer:
            self.activity.emit()
        buffer.append(character)
        self._last_at[device] = time.monotonic()
        self.timer.start()

    def _note_legacy(self) -> None:
        if self._window_is_foreground():
            self._legacy_pending += 1

    def _is_bound(self, device: str) -> bool:
        saved = self.device_name
        if not self.listening or not saved:
            return False
        if device == saved:
            return True
        token = "VID_0801&PID_0001"
        return token in device.upper() and token in saved.upper()

    def _window_is_foreground(self) -> bool:
        if self._user32 is None or not self._hwnd:
            return False
        foreground = int(self._user32.GetForegroundWindow() or 0)
        if foreground == self._hwnd:
            return True
        root = int(self._user32.GetAncestor(foreground, 2) or 0)
        return root == self._hwnd

    def _on_idle(self) -> None:
        now = time.monotonic()
        due = [device for device, stamp in list(self._last_at.items()) if now - stamp >= 0.4 and self._buffers.get(device)]
        for device in due:
            self._finish_device(device)
        if self._chars:
            self._finish()

    def _finish_device(self, device: str) -> None:
        text = "".join(self._buffers.pop(device, [])).strip()
        self._last_at.pop(device, None)
        self._shift.pop(device, None)
        if not self._buffers:
            self.timer.stop()
        self._accept(text, device)

    def _read_keyboard(self, lparam: int):
        ctypes = self._ctypes
        size = wintypes.UINT(0)
        handle = ctypes.c_void_p(lparam & 0xFFFFFFFFFFFFFFFF)
        self._user32.GetRawInputData(handle, 0x10000003, None, ctypes.byref(size), self._header_size)
        if not size.value:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        written = self._user32.GetRawInputData(
            handle,
            0x10000003,
            buffer,
            ctypes.byref(size),
            self._header_size,
        )
        if written == 0xFFFFFFFF or size.value < self._header_size + 16:
            return None
        raw = buffer.raw[: size.value]
        if self._header_size == 24:
            device_type, _dw_size, device_handle, _wparam = struct.unpack_from("=IIQQ", raw, 0)
            offset = 24
        else:
            device_type, _dw_size, device_handle, _wparam = struct.unpack_from("=IIII", raw, 0)
            offset = 16
        if device_type != 1:
            return None
        make_code, flags, _reserved, vkey, _message, _extra = struct.unpack_from("=HHHHII", raw, offset)
        return device_handle, make_code, flags, vkey

    def _device_name(self, handle: int) -> str:
        if not handle:
            return ""
        cached = self._names.get(handle)
        if cached is not None:
            return cached
        ctypes = self._ctypes
        size = wintypes.UINT(0)
        self._user32.GetRawInputDeviceInfoW(
            ctypes.c_void_p(handle),
            0x20000007,
            None,
            ctypes.byref(size),
        )
        if size.value <= 0:
            return f"handle:{handle}"
        buffer = ctypes.create_unicode_buffer(size.value)
        self._user32.GetRawInputDeviceInfoW(
            ctypes.c_void_p(handle),
            0x20000007,
            buffer,
            ctypes.byref(size),
        )
        if not buffer.value:
            return f"handle:{handle}"
        self._names[handle] = buffer.value
        return buffer.value

    def _reset_buffer(self) -> None:
        self._chars.clear()
        self._buffer_device = None
        self.timer.stop()

    def _finish(self) -> None:
        text = "".join(self._chars).strip()
        device = self._buffer_device or "window"
        self._reset_buffer()
        self._accept(text, device)

    def _accept(self, text: str, device: str) -> None:
        if self.identifying:
            if not text or not looks_like_swipe(text):
                if sum(character.isdigit() for character in text) >= 8:
                    self.rejected.emit("Swipe was not read. Click Identify reader and swipe the card again.")
                return
            self.identifying = False
            self.listening = True
            self.device_name = device
            self.settings.setValue("reader_device", device)
            self.bound.emit(device)
        elif device == "window":
            if not self.listening:
                return
        elif not self._is_bound(device):
            return
        if text and looks_like_swipe(text):
            self.swipe_ready.emit(text)
