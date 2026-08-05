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
        # Returns the _write result: False = frame dropped (EBUSY/error). A
        # silently dropped CLEAR frame left the strip holding its last image
        # forever, because _cleared latched anyway (the standstill artifacts).
        if not self._begun:
            return
        payload = bytes(self._buf)
        scale = self._brightness
        if scale < 255:
            payload = payload.translate(self._brightness_lut(scale))
        return self._write(payload)

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


class MultiStrip:
    """One logical strip fanned out to N identical PIO devices ("analog").

    Mirror by construction: there is exactly ONE pixel buffer (the primary's —
    every drawing call is delegated to it), and show() renders the payload once
    and writes it to every device back-to-back. A write() returns in ~2 us
    while the 18 ms shift-out runs in hardware, so the inter-device skew is
    microseconds: visually simultaneous, no software timing to drift.

    Delivery semantics follow the proven-clear contract: show() is False if ANY
    device dropped its frame, so clear() keeps retrying until every chain is
    really black — one chain must never silently keep an image the other lost.
    dropped_frames sums across devices for the status endpoint.
    """

    def __init__(self, strips):
        if not strips:
            raise ValueError("MultiStrip needs at least one strip")
        self._strips = list(strips)
        self._p = self._strips[0]

    # ---- drawing: one buffer, the primary's ----
    def numPixels(self):
        return self._p.numPixels()

    def setPixelColor(self, n, color):
        self._p.setPixelColor(n, color)

    def fill(self, color):
        self._p.fill(color)

    def getPixelColor(self, n):
        return self._p.getPixelColor(n)

    # ---- lifecycle / settings: fan out ----
    def begin(self):
        for s in self._strips:
            s.begin()

    def close(self):
        for s in self._strips:
            s.close()

    def setBrightness(self, brightness):
        for s in self._strips:
            s.setBrightness(brightness)

    def getBrightness(self):
        return self._p.getBrightness()

    @property
    def dropped_frames(self):
        return sum(getattr(s, "dropped_frames", 0) or 0 for s in self._strips)

    # ---- output ----
    def show(self):
        # Render once (brightness LUT folded in like PioStrip.show), write N x.
        payload = bytes(self._p._buf)
        scale = self._p._brightness
        if scale < 255:
            payload = payload.translate(self._p._brightness_lut(scale))
        ok = True
        for s in self._strips:
            # show_payload applies gain only — brightness is already folded in.
            if s.show_payload(payload, 255) is False:
                ok = False
        return ok

    def show_payload(self, payload, gain=255):
        ok = True
        for s in self._strips:
            if s.show_payload(payload, gain) is False:
                ok = False
        return ok
