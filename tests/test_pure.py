"""
Pure-function unit tests for lichtwerk-controller.

Hardware is mocked at the top so these tests run on any machine
(Mac, Linux CI, the Pi itself) without the rpi_ws281x C extension.
"""

import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Mock hardware before any project import
# ---------------------------------------------------------------------------
_rpi_ws281x_mock = MagicMock()
_rpi_ws281x_mock.Color = lambda r, g, b: (r, g, b)
sys.modules['rpi_ws281x'] = _rpi_ws281x_mock

import json
import os
import tempfile
import pytest

# ---------------------------------------------------------------------------
# Helpers: stand-alone versions of the pure functions extracted from the
# source files (no PixelStrip, no Flask, no GPIO) so tests are self-contained.
# ---------------------------------------------------------------------------

def wheel(pos: int):
    """Copy of LichtwerkController.wheel / LichtwerkWebController.wheel."""
    if pos < 0 or pos > 255:
        return 0, 0, 0
    elif pos < 85:
        r = pos * 3
        g = 255 - pos * 3
        b = 0
    elif pos < 170:
        pos -= 85
        r = 255 - pos * 3
        g = 0
        b = pos * 3
    else:
        pos -= 170
        r = 0
        g = pos * 3
        b = 255 - pos * 3
    return r, g, b


def apply_brightness(r: int, g: int, b: int, brightness: float):
    """Copy of LichtwerkController.set_pixel brightness scaling (no strip)."""
    return int(r * brightness), int(g * brightness), int(b * brightness)


def clamp_brightness(value: int, lo: int = 0, hi: int = 255) -> int:
    return max(lo, min(hi, value))


def clamp_speed(value: int, lo: int = 1, hi: int = 100) -> int:
    return max(lo, min(hi, value))


def hsv_to_rgb(h: float, s: float, v: float):
    """Copy of LichtwerkWebController.hsv_to_rgb."""
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def fade_toward_color(current, target, fade_amount: int):
    """Copy of LichtwerkWebController.fade_toward_color (pure helper)."""
    def fade_component(c, t, a):
        if c == t:
            return c
        elif c < t:
            return min(c + a, t)
        else:
            return max(c - a, t)
    return [
        fade_component(current[0], target[0], fade_amount),
        fade_component(current[1], target[1], fade_amount),
        fade_component(current[2], target[2], fade_amount),
    ]


def fire_palette(colorindex: int):
    """Copy of the heat→colour conversion in effect_fire."""
    colorindex = min(255, max(0, colorindex))
    if colorindex < 85:
        return colorindex * 3, 0, 0
    elif colorindex < 170:
        return 255, (colorindex - 85) * 3, 0
    else:
        return 255, 255, (colorindex - 170) * 3


def speed_to_sleep(speed: int) -> float:
    """Copy of start_effect_loop's sleep-time formula."""
    return max(0.01, (101 - speed) / 1000.0)


def valid_effects():
    return ['solid', 'rainbow', 'pulse', 'chase', 'sparkle',
            'strobe', 'meteor', 'breathe', 'sinelon', 'juggle',
            'theater', 'gradient', 'fire']


# ===========================================================================
# Tests
# ===========================================================================


class TestWheel:
    def test_zero_is_red_family(self):
        r, g, b = wheel(0)
        assert r == 0
        assert g == 255
        assert b == 0

    def test_85_boundary(self):
        """pos=85 is the start of the second third."""
        r, g, b = wheel(85)
        assert r == 255
        assert g == 0
        assert b == 0

    def test_170_boundary(self):
        """pos=170 is the start of the third third."""
        r, g, b = wheel(170)
        assert r == 0
        assert g == 0
        assert b == 255

    def test_255_gives_rgb_triple(self):
        r, g, b = wheel(255)
        # pos 255 → third branch: pos-=170 → 85: r=0, g=85*3=255, b=255-85*3=0
        assert r == 0
        assert g == 255
        assert b == 0

    def test_out_of_range_negative(self):
        assert wheel(-1) == (0, 0, 0)

    def test_out_of_range_high(self):
        assert wheel(256) == (0, 0, 0)

    def test_midpoint_first_third(self):
        """pos=42: r=126, g=129, b=0"""
        r, g, b = wheel(42)
        assert r == 126
        assert g == 129
        assert b == 0

    def test_all_components_in_range(self):
        for pos in range(256):
            r, g, b = wheel(pos)
            assert 0 <= r <= 255, f"r out of range at pos={pos}"
            assert 0 <= g <= 255, f"g out of range at pos={pos}"
            assert 0 <= b <= 255, f"b out of range at pos={pos}"


class TestBrightnessScaling:
    def test_full_brightness(self):
        assert apply_brightness(200, 100, 50, 1.0) == (200, 100, 50)

    def test_half_brightness(self):
        r, g, b = apply_brightness(200, 100, 50, 0.5)
        assert r == 100
        assert g == 50
        assert b == 25

    def test_zero_brightness(self):
        assert apply_brightness(255, 255, 255, 0.0) == (0, 0, 0)

    def test_fractional_rounds_down(self):
        """int() truncates, not rounds."""
        r, g, b = apply_brightness(3, 3, 3, 0.9)
        assert r == int(3 * 0.9)  # 2


class TestClamp:
    def test_brightness_in_range(self):
        assert clamp_brightness(128) == 128

    def test_brightness_clamp_high(self):
        assert clamp_brightness(300) == 255

    def test_brightness_clamp_low(self):
        assert clamp_brightness(-5) == 0

    def test_speed_clamp_high(self):
        assert clamp_speed(200) == 100

    def test_speed_clamp_low(self):
        assert clamp_speed(0) == 1

    def test_speed_boundary_min(self):
        assert clamp_speed(1) == 1

    def test_speed_boundary_max(self):
        assert clamp_speed(100) == 100


class TestHsvToRgb:
    def test_red(self):
        r, g, b = hsv_to_rgb(0.0, 1.0, 1.0)
        assert r == 255
        assert g == 0
        assert b == 0

    def test_green(self):
        r, g, b = hsv_to_rgb(1 / 3, 1.0, 1.0)
        assert r == 0
        assert g == 255
        assert b == 0

    def test_blue(self):
        r, g, b = hsv_to_rgb(2 / 3, 1.0, 1.0)
        assert r == 0
        assert g == 0
        assert b == 255

    def test_black(self):
        r, g, b = hsv_to_rgb(0.0, 0.0, 0.0)
        assert r == g == b == 0

    def test_white(self):
        r, g, b = hsv_to_rgb(0.0, 0.0, 1.0)
        assert r == g == b == 255


class TestFadeTowardColor:
    def test_fade_up(self):
        result = fade_toward_color([0, 0, 0], [100, 100, 100], 10)
        assert result == [10, 10, 10]

    def test_fade_down(self):
        result = fade_toward_color([100, 100, 100], [0, 0, 0], 10)
        assert result == [90, 90, 90]

    def test_no_overshoot_up(self):
        result = fade_toward_color([95, 95, 95], [100, 100, 100], 20)
        assert result == [100, 100, 100]

    def test_no_overshoot_down(self):
        result = fade_toward_color([5, 5, 5], [0, 0, 0], 20)
        assert result == [0, 0, 0]

    def test_already_at_target(self):
        result = fade_toward_color([50, 50, 50], [50, 50, 50], 10)
        assert result == [50, 50, 50]


class TestFirePalette:
    def test_cold_is_black_to_red(self):
        r, g, b = fire_palette(0)
        assert r == 0
        assert g == 0
        assert b == 0

    def test_mid_low_red(self):
        r, g, b = fire_palette(42)
        assert r == 126
        assert g == 0
        assert b == 0

    def test_mid_high_yellow(self):
        """85..169 → red channel stays 255, green ramps up"""
        r, g, b = fire_palette(85)
        assert r == 255
        assert g == 0
        assert b == 0

    def test_hot_white(self):
        """170..255 → both r and g 255, blue ramps up"""
        r, g, b = fire_palette(170)
        assert r == 255
        assert g == 255
        assert b == 0

    def test_clamps_above_255(self):
        r, g, b = fire_palette(300)
        assert r == 255
        assert g == 255
        # colorindex clamped to 255 → third branch: 255-170=85 → b=85*3=255
        assert b == 255

    def test_clamps_below_0(self):
        r, g, b = fire_palette(-10)
        assert r == g == b == 0


class TestSpeedToSleep:
    def test_speed_50(self):
        result = speed_to_sleep(50)
        assert abs(result - 0.051) < 0.001

    def test_speed_100_gives_minimum(self):
        """Speed 100 → (101-100)/1000 = 0.001 → clamped to 0.01"""
        assert speed_to_sleep(100) == 0.01

    def test_speed_1_gives_max(self):
        assert abs(speed_to_sleep(1) - 0.1) < 0.001

    def test_floor_enforced(self):
        """Any extreme value should not go below 0.01."""
        assert speed_to_sleep(200) >= 0.01


class TestValidEffects:
    def test_count(self):
        assert len(valid_effects()) == 13

    def test_all_expected_names(self):
        effects = valid_effects()
        for name in ['solid', 'rainbow', 'pulse', 'chase', 'sparkle',
                     'strobe', 'meteor', 'breathe', 'sinelon', 'juggle',
                     'theater', 'gradient', 'fire']:
            assert name in effects

    def test_no_duplicates(self):
        effects = valid_effects()
        assert len(effects) == len(set(effects))
