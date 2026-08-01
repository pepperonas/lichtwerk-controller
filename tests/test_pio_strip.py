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


def test_begin_keeps_fd_open(tmp_path, monkeypatch):
    """Latency: open once in begin(); show() must not re-open every frame."""
    dev = tmp_path / "leds0"
    dev.write_bytes(b"")
    opens = []
    writes = []
    closes = []
    fake_fd = [10]

    def fake_open(path, flags):
        opens.append(path)
        fd = fake_fd[0]
        fake_fd[0] += 1
        return fd

    def fake_write(fd, data):
        writes.append((fd, bytes(data)))
        return len(data)

    def fake_close(fd):
        closes.append(fd)

    monkeypatch.setattr("os.open", fake_open)
    monkeypatch.setattr("os.write", fake_write)
    monkeypatch.setattr("os.close", fake_close)

    s = PixelStrip(1, brightness=255, device=str(dev))
    s.begin()
    assert len(opens) == 1
    assert s._fd >= 0
    # brightness init write
    assert writes and writes[0][1] == b"\xff"

    s.setPixelColor(0, Color(255, 0, 0))
    s.show()
    s.show()
    assert len(opens) == 1  # no reopen
    assert len(closes) == 0
    assert writes[-1][1][0:3] == bytes([255, 0, 0])
    assert writes[-1][0] == s._fd

    s.close()
    assert s._fd < 0
    assert closes


def test_show_scales_by_brightness(tmp_path, monkeypatch):
    s = PixelStrip(1, brightness=128, device=str(tmp_path / "leds0"))
    s._begun = True
    s._fd = 3
    s.setPixelColor(0, Color(255, 0, 0))
    writes = []

    monkeypatch.setattr("os.write", lambda fd, data: writes.append(bytes(data)) or len(data))
    s.show()
    assert writes
    assert writes[0][0] == 128
    assert writes[0][1] == 0
    assert writes[0][2] == 0


def test_show_full_brightness_passthrough(tmp_path, monkeypatch):
    s = PixelStrip(1, brightness=255, device=str(tmp_path / "leds0"))
    s._begun = True
    s._fd = 7
    s.setPixelColor(0, Color(255, 70, 55))
    writes = []
    monkeypatch.setattr("os.write", lambda fd, data: writes.append(bytes(data)) or len(data))
    s.show()
    assert writes[0][0:3] == bytes([255, 70, 55])
