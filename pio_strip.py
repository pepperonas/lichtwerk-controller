"""WS2812 driver for Raspberry Pi 5 via dtoverlay=ws2812-pio (/dev/leds0).

Kernel buffer: little-endian RGBW u32 per LED (R,G,B,W).
Kernel brightness byte (1-byte write) = multiplier 0–255.

Driver contract (measured on ws2812_pio_rp1, 600 LEDs):
  * ONE frame per open(). A second write() on the same fd always fails with
    ENOSPC — the buffer is spent, and waiting does not help (verified up to
    1000 ms). The device is not seekable either (lseek/pwrite → ESPIPE), so the
    offset cannot be rewound.
  * open+write+close costs ~0.002 ms, i.e. nothing. Reusing the fd bought
    nothing and merely added a failed syscall plus an exception per frame.
  * Shift-out floor is 600 × 24 bit × 1.25 µs = 18.0 ms → 55.6 fps ceiling.
    Pacing is the caller's job (see LedController's effect loop).

Brightness scaling uses a 256-byte translation table, so show() stays at C
speed instead of running a 2400-element generator expression per frame.
"""
from __future__ import annotations

import os

DEV_DEFAULT = "/dev/leds0"

_IDENTITY = bytes(range(256))


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
        self._luts: dict[int, bytes] = {}
        self._dropped = 0

    # ---- lifecycle ---------------------------------------------------------
    def begin(self):
        if not os.path.exists(self._device):
            raise RuntimeError(
                f"{self._device} missing — enable "
                f"'dtoverlay=ws2812-pio,gpio={self._pin},num_leds={self._num},brightness=255' "
                "in /boot/firmware/config.txt"
            )
        # Kernel brightness is a pixel multiplier (0=off … 255=full). It needs
        # its own open: the byte counts against the frame buffer, so sharing an
        # fd with the first frame would burn a write.
        fd = os.open(self._device, os.O_WRONLY)
        try:
            os.write(fd, b"\xff")
        finally:
            os.close(fd)
        self._gamma_bypass = True
        self._begun = True

    def close(self):
        self._begun = False

    # ---- buffer ------------------------------------------------------------
    def numPixels(self) -> int:
        return self._num

    def setBrightness(self, brightness: int):
        self._brightness = max(0, min(255, int(brightness)))

    def getBrightness(self) -> int:
        return self._brightness

    def setPixelColor(self, n: int, color: int):
        if n < 0 or n >= self._num:
            return
        i = n * 4
        self._buf[i] = (color >> 16) & 0xFF
        self._buf[i + 1] = (color >> 8) & 0xFF
        self._buf[i + 2] = color & 0xFF
        self._buf[i + 3] = (color >> 24) & 0xFF

    def fill(self, color: int):
        """Fill the whole buffer with one packed Color, without per-LED calls."""
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        w = (color >> 24) & 0xFF
        self._buf[:] = bytes((r, g, b, w)) * self._num

    def getPixelColor(self, n: int) -> int:
        if n < 0 or n >= self._num:
            return 0
        i = n * 4
        return Color(self._buf[i], self._buf[i + 1], self._buf[i + 2], self._buf[i + 3])

    # ---- output ------------------------------------------------------------
    def _brightness_lut(self, scale: int) -> bytes:
        """256-byte table for `bytes.translate`, memoised per scale.

        A fade ramp walks through many scales per second; rebuilding the table
        each time would undo the point of the LUT.
        """
        lut = self._luts.get(scale)
        if lut is None:
            lut = (_IDENTITY if scale >= 255
                   else bytes((v * scale) // 255 for v in range(256)))
            self._luts[scale] = lut
        return lut

    def _write(self, payload: bytes) -> bool:
        """One frame = one open. Returns False if the kernel refused the frame."""
        try:
            fd = os.open(self._device, os.O_WRONLY)
        except OSError:
            self._dropped += 1
            return False
        try:
            os.write(fd, payload)
            return True
        except OSError:
            self._dropped += 1
            return False
        finally:
            os.close(fd)

    def show(self):
        if not self._begun:
            return
        payload = bytes(self._buf)
        scale = self._brightness
        if scale < 255:
            payload = payload.translate(self._brightness_lut(scale))
        self._write(payload)

    def show_payload(self, payload: bytes, gain: int = 255):
        """Write a pre-rendered RGBW payload (4 bytes/LED) straight out.

        Lets callers precompute whole frames — master brightness and any fade
        ramp fold into a single translate(), so a frame costs a table lookup
        plus the write instead of a per-pixel Python loop.

        `gain` is the ONLY scaling applied. Unlike show(), this deliberately
        ignores `self._brightness`: payloads come from a gamma-corrected render
        with an exposure chosen against a power budget, and silently folding in
        a second multiplier would invalidate both.
        """
        if not self._begun:
            return
        scale = max(0, min(255, int(gain)))
        if scale < 255:
            payload = payload.translate(self._brightness_lut(scale))
        self._write(payload)

    @property
    def dropped_frames(self) -> int:
        return self._dropped


class StripGroup:
    """Several independent PIO chains presented as one logical strip.

    Effects paint into a single address space of `sum(lengths)` pixels and never
    learn there is more than one chain — the split happens at write time. That is
    what keeps all thirteen effects, the fade ramp and the disco sync working
    untouched; the alternative, teaching each effect about chains, would have
    been thirteen chances to get it wrong.

    The group owns the pixel buffer rather than delegating to the members, so
    `setPixelColor` costs exactly what it did with one strip. Routing per pixel
    would have put a lookup in the hottest loop in the app for no benefit.

    Two write modes, because the two kinds of content want opposite things:

    * `show()` / `show_payload()` **extend** — one picture spread across the
      chains. That is what a chase, a rainbow or a meteor means.
    * `show_mirrored()` **mirrors** — the same picture on every chain. That is
      what a warning means: each run has to carry the whole signal. Stretch one
      iris across two runs in different corners and the second shows only its
      dark tail, which is precisely when you needed to see it.

    Writes are sequential, but the shift-out is not: each chain has its own PIO
    state machine, so the 18 ms for 600 LEDs overlaps instead of adding up. Two
    chains of 600 hold 55 fps where one chain of 1200 would drop to 28.
    """

    def __init__(self, strips):
        self._strips = list(strips)
        if not self._strips:
            raise ValueError("StripGroup needs at least one strip")
        self._num = sum(s.numPixels() for s in self._strips)
        self._buf = bytearray(self._num * 4)
        self._brightness = self._strips[0].getBrightness()
        bounds, off = [], 0
        for s in self._strips:
            end = off + s.numPixels() * 4
            bounds.append((off, end))
            off = end
        self._bounds = tuple(bounds)

    # ---- lifecycle ---------------------------------------------------------
    def begin(self):
        for s in self._strips:
            s.begin()

    def close(self):
        for s in self._strips:
            s.close()

    # ---- shape -------------------------------------------------------------
    def numPixels(self) -> int:
        return self._num

    @property
    def lengths(self):
        """Pixels per chain — what the mirrored painters need to size a frame."""
        return tuple(s.numPixels() for s in self._strips)

    @property
    def count(self) -> int:
        return len(self._strips)

    # ---- buffer ------------------------------------------------------------
    def setBrightness(self, brightness: int):
        self._brightness = max(0, min(255, int(brightness)))
        for s in self._strips:
            s.setBrightness(self._brightness)

    def getBrightness(self) -> int:
        return self._brightness

    def setPixelColor(self, n: int, color: int):
        if n < 0 or n >= self._num:
            return
        i = n * 4
        self._buf[i] = (color >> 16) & 0xFF
        self._buf[i + 1] = (color >> 8) & 0xFF
        self._buf[i + 2] = color & 0xFF
        self._buf[i + 3] = (color >> 24) & 0xFF

    def getPixelColor(self, n: int) -> int:
        if n < 0 or n >= self._num:
            return 0
        i = n * 4
        return Color(self._buf[i], self._buf[i + 1], self._buf[i + 2], self._buf[i + 3])

    def fill(self, color: int):
        for n in range(self._num):
            self.setPixelColor(n, color)

    # ---- output ------------------------------------------------------------
    def show(self):
        self.show_payload(bytes(self._buf), self._brightness)

    def show_payload(self, payload: bytes, gain: int = 255):
        """Spread one frame across the chains, in chain order."""
        for s, (a, b) in zip(self._strips, self._bounds):
            s.show_payload(payload[a:b], gain)

    def show_mirrored(self, payloads, gain: int = 255):
        """One frame per chain — same content, independently rendered overlays.

        Takes a list rather than one payload so the caller can give each chain
        its own highlights. Identical spark positions on every run read as a
        machine; the wash underneath is what should be identical, not the specks.
        """
        for s, p in zip(self._strips, payloads):
            s.show_payload(p, gain)

    @property
    def dropped_frames(self) -> int:
        return sum(s.dropped_frames for s in self._strips)
