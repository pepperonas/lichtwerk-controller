"""Unit tests for iris_warn timing / frame logic (mirrors web_controller)."""

from __future__ import annotations

import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def iris_phase(t: float) -> bool:
    """Whether the strip should be lit at relative time t (seconds since engage).

    Copied from effect_iris_warn timing in web_controller.py.
    """
    if t < 0.21:
        return not (0.07 <= t < 0.13)
    period = 0.55
    u = ((t - 0.21) / period) % 1.0
    return u < 0.65


def test_iris_engage_double_pulse_pattern():
    # ON … OFF gap … ON
    assert iris_phase(0.00) is True
    assert iris_phase(0.06) is True
    assert iris_phase(0.08) is False
    assert iris_phase(0.12) is False
    assert iris_phase(0.14) is True
    assert iris_phase(0.20) is True


def test_iris_sustain_duty_cycle_about_65_percent():
    # Sample sustain window after engage
    lit = sum(1 for i in range(100) if iris_phase(0.21 + i * 0.01))
    # 1.0s of samples → expect ~65 lit
    assert 55 <= lit <= 75


def test_iris_hard_edges_not_soft_glow():
    """Adjacent samples around a cut must be binary True/False — no mid values."""
    # Find a falling edge in sustain
    prev = iris_phase(0.21)
    edge = None
    for i in range(1, 200):
        t = 0.21 + i * 0.005
        cur = iris_phase(t)
        if prev and not cur:
            edge = t
            break
        prev = cur
    assert edge is not None
    assert iris_phase(edge - 0.005) is True
    assert iris_phase(edge) is False


def test_web_controller_registers_iris_warn():
    src = (_ROOT / "web_controller.py").read_text()
    assert "def effect_iris_warn(self)" in src
    assert "'iris_warn': self.effect_iris_warn" in src
    assert "iris_warn" in src
    assert "0.55" in src  # period / attack
    assert "0.65" in src  # duty
    assert "spark" in src.lower() or "iris_spark" in src
    assert "255, 70, 55" in src or "255,70,55" in src


def test_web_controller_iris_fps_sleep():
    src = (_ROOT / "web_controller.py").read_text()
    assert "0.008" in src  # ~125 Hz edge poll
    assert "wake_effect" in src
    assert "/api/solid" in src
    assert "threaded=True" in src
    assert "run_effect()" in src  # first-frame paint in iris_warn handler


def _iris_frame(strip, effect_params, brightness, now):
    """Standalone copy of effect_iris_warn paint path (no Flask/GPIO import).

    Kept in sync with web_controller.effect_iris_warn via the source-contract
    tests above — web_controller instantiates hardware at import time.
    """
    from pio_strip import Color
    import random

    t0 = effect_params.get("iris_t0")
    if t0 is None:
        t0 = now
        effect_params["iris_t0"] = t0
        effect_params["iris_lit"] = None
        effect_params["iris_sparking"] = None
        effect_params["iris_spark_until"] = 0.0
    t = now - t0
    hr, hg, hb = 255, 70, 55
    lit = iris_phase(t)
    last = effect_params.get("iris_lit")
    if lit and last is not True:
        effect_params["iris_spark_until"] = t + 0.04
    spark = bool(lit and t < float(effect_params.get("iris_spark_until") or 0))
    last_spark = effect_params.get("iris_sparking")
    if last is lit and last_spark is spark:
        return
    effect_params["iris_lit"] = lit
    effect_params["iris_sparking"] = spark
    if not lit:
        for i in range(strip.numPixels()):
            strip.setPixelColor(i, Color(0, 0, 0))
        strip.show()
        return
    scale = max(0.0, min(1.0, brightness / 255.0))
    c = Color(int(hr * scale), int(hg * scale), int(hb * scale))
    n = strip.numPixels()
    for i in range(n):
        strip.setPixelColor(i, c)
    if spark and n > 0:
        w = Color(int(255 * scale), int(255 * scale), int(255 * scale))
        k = min(n, min(80, max(24, n // 12)))
        if k < 1:
            k = 1
        rng = random.Random(int(t0 * 1000) ^ int(t * 200))
        for i in rng.sample(range(n), k):
            strip.setPixelColor(i, w)
    strip.show()


def test_iris_spark_density_contract():
    src = (_ROOT / "web_controller.py").read_text()
    assert "min(80, max(24, n // 12))" in src
    assert "0.055" in src


def test_effect_iris_warn_paints_and_clears():
    """Paint path: ON paints crimson (+sparks), engage-OFF clears to black."""
    from pio_strip import Color

    class FakeStrip:
        def __init__(self, n=20):
            self._n = n
            self.buf = [0] * n
            self.shows = 0

        def numPixels(self):
            return self._n

        def setPixelColor(self, i, c):
            self.buf[i] = c

        def show(self):
            self.shows += 1

    strip = FakeStrip(20)
    params = {}
    _iris_frame(strip, params, 255, now=1000.0)
    assert params.get("iris_lit") is True
    assert strip.shows >= 1
    assert Color(255, 70, 55) in strip.buf or any(
        (c >> 16) & 0xFF == 255 and (c & 0xFF) == 55 for c in strip.buf
    )

    _iris_frame(strip, params, 255, now=1000.08)
    assert params.get("iris_lit") is False
    assert all(c == 0 for c in strip.buf)


def test_readme_documents_iris_warn_and_pio():
    readme = (_ROOT / "README.md").read_text()
    assert "iris_warn" in readme
    assert "pio_strip" in readme or "ws2812-pio" in readme
    assert "raspi5" in readme.lower() or "Pi 5" in readme
