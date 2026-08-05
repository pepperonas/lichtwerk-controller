"""Unit tests for pio_strip (Pi 5 ws2812-pio driver) — no /dev/leds0 needed."""

from __future__ import annotations

import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pio_strip import Color, PixelStrip  # noqa: E402


def test_color_packing_rgb():
    c = Color(255, 70, 55)
    assert (c >> 16) & 0xFF == 255
    assert (c >> 8) & 0xFF == 70
    assert c & 0xFF == 55
    assert (c >> 24) & 0xFF == 0


def test_color_packing_with_white():
    c = Color(1, 2, 3, 4)
    assert (c >> 24) & 0xFF == 4


def test_pixelstrip_buffer_roundtrip(tmp_path):
    s = PixelStrip(4, pin=21, brightness=255, device=str(tmp_path / "missing"))
    assert s.numPixels() == 4
    assert s.getBrightness() == 255
    s.setPixelColor(0, Color(10, 20, 30))
    s.setPixelColor(1, Color(255, 0, 0))
    assert s.getPixelColor(0) == Color(10, 20, 30)
    assert s.getPixelColor(1) == Color(255, 0, 0)
    assert s.getPixelColor(99) == 0


def test_fill_writes_all_pixels(tmp_path):
    s = PixelStrip(5, device=str(tmp_path / "x"))
    s.fill(Color(255, 70, 55))
    for i in range(5):
        assert s.getPixelColor(i) == Color(255, 70, 55)


def test_set_pixel_out_of_range_noop(tmp_path):
    s = PixelStrip(2, device=str(tmp_path / "x"))
    s.setPixelColor(-1, Color(1, 1, 1))
    s.setPixelColor(2, Color(1, 1, 1))
    assert s.getPixelColor(0) == 0


def test_brightness_clamped(tmp_path):
    s = PixelStrip(1, brightness=999, device=str(tmp_path / "x"))
    assert s.getBrightness() == 255
    s.setBrightness(-5)
    assert s.getBrightness() == 0
    s.setBrightness(128)
    assert s.getBrightness() == 128


def test_begin_missing_device_raises(tmp_path):
    s = PixelStrip(8, pin=21, device=str(tmp_path / "nope"))
    with pytest.raises(RuntimeError) as ei:
        s.begin()
    assert "ws2812-pio" in str(ei.value)
    assert "gpio=21" in str(ei.value)


def test_show_without_begin_is_noop(tmp_path, monkeypatch):
    s = PixelStrip(2, device=str(tmp_path / "x"))
    s.setPixelColor(0, Color(255, 255, 255))
    opened = []

    def boom(*a, **k):
        opened.append(1)
        raise AssertionError("should not open device")

    monkeypatch.setattr("os.open", boom)
    s.show()  # not begun
    assert opened == []

def _fake_dev(monkeypatch):
    """Capture open/write/close so the driver contract can be asserted."""
    log = {"opens": [], "writes": [], "closes": []}
    fd_seq = [10]

    def fake_open(path, flags):
        log["opens"].append(path)
        fd_seq[0] += 1
        return fd_seq[0]

    monkeypatch.setattr("os.open", fake_open)
    monkeypatch.setattr("os.write",
                        lambda fd, data: log["writes"].append((fd, bytes(data))) or len(data))
    monkeypatch.setattr("os.close", lambda fd: log["closes"].append(fd))
    return log


def test_begin_uses_its_own_open_for_the_brightness_byte(tmp_path, monkeypatch):
    """The brightness byte counts against the frame buffer.

    Sharing an fd with the first frame would make that frame fail with ENOSPC,
    which is exactly what the old persistent-fd path papered over.
    """
    dev = tmp_path / "leds0"
    dev.write_bytes(b"")
    log = _fake_dev(monkeypatch)

    s = PixelStrip(1, brightness=255, device=str(dev))
    s.begin()

    assert log["opens"] == [str(dev)]
    assert log["writes"][0][1] == b"\xff"
    assert log["closes"], "begin() must not leave the fd open"


def test_show_opens_once_per_frame(tmp_path, monkeypatch):
    """One frame per open(): a second write on the same fd always fails ENOSPC."""
    dev = tmp_path / "leds0"
    dev.write_bytes(b"")
    log = _fake_dev(monkeypatch)

    s = PixelStrip(1, brightness=255, device=str(dev))
    s.begin()
    before = len(log["opens"])

    s.setPixelColor(0, Color(255, 0, 0))
    s.show()
    s.show()
    s.show()

    assert len(log["opens"]) == before + 3
    assert len(log["closes"]) == len(log["opens"])
    assert log["writes"][-1][1][0:3] == bytes([255, 0, 0])


def test_show_scales_by_brightness(tmp_path, monkeypatch):
    dev = tmp_path / "leds0"
    dev.write_bytes(b"")
    log = _fake_dev(monkeypatch)
    s = PixelStrip(1, brightness=128, device=str(dev))
    s.begin()
    s.setPixelColor(0, Color(255, 0, 0))
    s.show()
    assert log["writes"][-1][1][0:3] == bytes([128, 0, 0])


def test_show_full_brightness_passthrough(tmp_path, monkeypatch):
    dev = tmp_path / "leds0"
    dev.write_bytes(b"")
    log = _fake_dev(monkeypatch)
    s = PixelStrip(1, brightness=255, device=str(dev))
    s.begin()
    s.setPixelColor(0, Color(255, 70, 55))
    s.show()
    assert log["writes"][-1][1][0:3] == bytes([255, 70, 55])


def test_show_payload_ignores_driver_brightness(tmp_path, monkeypatch):
    """Payloads are gamma/exposure rendered — only the caller's gain may scale them."""
    dev = tmp_path / "leds0"
    dev.write_bytes(b"")
    log = _fake_dev(monkeypatch)
    s = PixelStrip(1, brightness=100, device=str(dev))
    s.begin()
    s.show_payload(bytes([200, 20, 15, 0]))
    assert log["writes"][-1][1][0:3] == bytes([200, 20, 15])
    s.show_payload(bytes([200, 20, 15, 0]), gain=128)
    assert log["writes"][-1][1][0:3] == bytes([100, 10, 7])


def test_write_failure_is_counted_not_raised(tmp_path, monkeypatch):
    """A refused frame must never take down the effect loop."""
    dev = tmp_path / "leds0"
    dev.write_bytes(b"")
    _fake_dev(monkeypatch)
    s = PixelStrip(1, device=str(dev))
    s.begin()

    def enospc(fd, data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("os.write", enospc)
    s.show()
    assert s.dropped_frames == 1



# ---- MultiStrip: second chain, mirrored ("analog") — 2026-08-06 -------------

def test_multistrip_mirrors_one_render_to_all_devices():
    """One buffer, one render, N writes: both chains must receive the byte-
    identical payload — the mirror is by construction, not by re-drawing."""
    from pio_strip import MultiStrip, Color

    class Fake:
        def __init__(self):
            self._buf = bytearray(8); self._brightness = 255
            self.payloads = []; self.dropped_frames = 0
        def numPixels(self): return 2
        def setPixelColor(self, n, c):
            self._buf[n*4:n*4+3] = bytes([(c>>16)&255, (c>>8)&255, c&255])
        def show_payload(self, payload, gain=255):
            self.payloads.append(bytes(payload)); return True

    a, b = Fake(), Fake()
    m = MultiStrip([a, b])
    m.setPixelColor(0, Color(255, 70, 55))
    assert m.show() is True
    assert a.payloads == b.payloads and len(a.payloads) == 1


def test_multistrip_show_is_false_if_any_chain_dropped():
    """Proven-clear contract: one chain silently keeping an image the other
    lost is exactly the standstill-artifact bug at fleet scale. Any drop makes
    the group show() False so clear() retries until EVERY chain is black."""
    from pio_strip import MultiStrip

    class Fake:
        def __init__(self, ok):
            self._buf = bytearray(4); self._brightness = 255
            self.ok = ok; self.dropped_frames = 0
        def show_payload(self, payload, gain=255):
            if not self.ok: self.dropped_frames += 1; return False
            return True

    m = MultiStrip([Fake(True), Fake(False)])
    assert m.show() is False
    assert m.dropped_frames == 1


def test_missing_second_device_never_costs_the_first():
    """A /dev/ledsN that is absent (overlay off, chain unplugged, boot
    conflict) must be SKIPPED — single-chain behaviour is the fallback."""
    src = (_ROOT / "web_controller.py").read_text()
    assert "if not os.path.exists(dev):" in src
    assert "uebersprungen" in src


def test_pio_device_map_is_resolved_not_assumed():
    """2026-08-06, the real face of the '05.08 colour shift': the kernel
    numbers ws2812-pio devices by DT unit address (ascending GPIO), not by
    overlay order. Enabling gpio=18 next to gpio=21 made GPIO 18 leds0 and
    moved the EXISTING chain to leds1 — the service kept writing the wrong
    pin. Device names must be resolved at runtime; config 'device' keys are
    deliberately ignored."""
    src = (_ROOT / "web_controller.py").read_text()
    fn = src[src.index("def parse_pio_map"):src.index("def resolve_pio_device")]
    ns = {}
    exec(fn, ns)
    swap = ("a ws2812-pio-rp1 x: Instantiated 600 LEDs on GPIO 18 as /dev/leds0\n"
            "b ws2812-pio-rp1 y: Instantiated 600 LEDs on GPIO 21 as /dev/leds1")
    assert ns["parse_pio_map"](swap) == {18: "/dev/leds0", 21: "/dev/leds1"}
    single = "x ws2812: Instantiated 600 LEDs on GPIO 21 as /dev/leds0"
    assert ns["parse_pio_map"](single) == {21: "/dev/leds0"}
    assert "resolve_pio_device(pin, pins)" in src, "chains must resolve by pin"
    assert "wird BEWUSST ignoriert" in src
