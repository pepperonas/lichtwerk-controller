"""WS2812 driver for Raspberry Pi 5 via dtoverlay=ws2812-pio (/dev/leds0).

Kernel buffer: little-endian RGBW u32 per LED (R,G,B,W).
Kernel brightness byte (1-byte write) = multiplier 0–255.

Latency: keep the device FD open across frames — open/close per show()
was the dominant Strip-Warn / effect-loop cost at ~60 fps.
"""
from __future__ import annotations

import os

DEV_DEFAULT = "/dev/leds0"


def Color(red: int, green: int, blue: int, white: int = 0) -> int:
    return ((white & 0xFF) << 24) | ((red & 0xFF) << 16) | ((green & 0xFF) << 8) | (blue & 0xFF)


class PixelStrip:
    def __init__(
        self,
        num: int,
        pin: int = 21,
        freq_hz: int = 800000,
        dma: int = 10,
        invert: bool = False,
        brightness: int = 255,
        channel: int = 0,
        strip_type=None,
        device: str = DEV_DEFAULT,
    ):
        self._num = int(num)
        self._pin = pin
        self._device = device
        self._brightness = max(0, min(255, int(brightness)))
        self._buf = bytearray(self._num * 4)
        self._begun = False
        self._gamma_bypass = False
        self._fd = -1

    def begin(self):
        if not os.path.exists(self._device):
            raise RuntimeError(
                f"{self._device} missing — enable "
                f"'dtoverlay=ws2812-pio,gpio={self._pin},num_leds={self._num},brightness=255' "
                "in /boot/firmware/config.txt"
            )
        self.close()
        fd = os.open(self._device, os.O_WRONLY)
        try:
            # Kernel brightness is a pixel multiplier (0=off … 255=full).
            os.write(fd, b"\xff")
            self._gamma_bypass = True
        except OSError:
            os.close(fd)
            raise
        self._fd = fd
        self._begun = True

    def numPixels(self) -> int:
        return self._num

    def setBrightness(self, brightness: int):
        self._brightness = max(0, min(255, int(brightness)))

    def getBrightness(self) -> int:
        return self._brightness

    def setPixelColor(self, n: int, color: int):
        if n < 0 or n >= self._num:
            return
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        w = (color >> 24) & 0xFF
        i = n * 4
        self._buf[i] = r
        self._buf[i + 1] = g
        self._buf[i + 2] = b
        self._buf[i + 3] = w

    def fill(self, color: int):
        """Fill entire buffer with one packed Color — O(n) but no Python per-LED call overhead from callers."""
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        w = (color >> 24) & 0xFF
        buf = self._buf
        for i in range(0, len(buf), 4):
            buf[i] = r
            buf[i + 1] = g
            buf[i + 2] = b
            buf[i + 3] = w

    def getPixelColor(self, n: int) -> int:
        if n < 0 or n >= self._num:
            return 0
        i = n * 4
        return Color(self._buf[i], self._buf[i + 1], self._buf[i + 2], self._buf[i + 3])

    def _ensure_fd(self) -> int:
        if self._fd >= 0:
            return self._fd
        fd = os.open(self._device, os.O_WRONLY)
        self._fd = fd
        return fd

    def show(self):
        if not self._begun:
            return
        if self._brightness >= 255:
            out = bytes(self._buf)
        else:
            scale = self._brightness
            out = bytes((v * scale) // 255 for v in self._buf)
        try:
            fd = self._ensure_fd()
            os.write(fd, out)
        except OSError:
            # Device reset / overlay reload — reopen once
            self.close()
            self._begun = True
            fd = self._ensure_fd()
            os.write(fd, out)

    def close(self):
        fd = self._fd
        self._fd = -1
        self._begun = False
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
