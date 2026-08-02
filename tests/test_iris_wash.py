"""Colour-maths tests for iris_wash — the dB-Analyse page wash on the strip.

The reference is disco-controller's `public/stats.html`. These values were
derived by replicating the browser's compositing (premultiplied gradient
interpolation, srcOver in sRGB) and are what the page actually paints, so they
pin the port down: if the CSS changes, these tests are what should fail first.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import iris_wash as w  # noqa: E402

N = 600

# (led index, breathe phase) -> sRGB the browser paints on the centre scanline
PAGE_REFERENCE = {
    (0, 0.0): (123, 28, 25),
    (0, 1.0): (167, 43, 36),
    (150, 0.0): (134, 33, 29),
    (150, 1.0): (174, 47, 39),
    (299, 0.0): (145, 38, 33),
    (299, 1.0): (182, 50, 42),
    (599, 0.0): (123, 28, 25),
    (599, 1.0): (167, 43, 36),
}


@pytest.mark.parametrize("key,expected", sorted(PAGE_REFERENCE.items()))
def test_page_pixel_matches_browser_composite(key, expected):
    i, e = key
    got = tuple(round(v) for v in w.page_pixel(w.strip_t(i, N), e))
    assert got == expected


def test_strip_is_symmetric_about_its_middle():
    """The gradient origin sits at 50% width, so the two halves must mirror."""
    for i in (0, 37, 120, 250):
        assert w.led_rgb(i, N, 0.6) == w.led_rgb(N - 1 - i, N, 0.6)


def test_brightness_falls_off_from_the_middle():
    mid = w.led_rgb(N // 2, N, 1.0)
    quarter = w.led_rgb(N // 4, N, 1.0)
    end = w.led_rgb(0, N, 1.0)
    assert mid[0] > quarter[0] > end[0]


def test_breathe_is_monotonic():
    prev = -1
    for step in range(11):
        r = w.led_rgb(N // 2, N, step / 10.0)[0]
        assert r >= prev
        prev = r


def test_wash_base_stays_red():
    """The base wash is the page, and the page is red — no white in the gradient.

    White highlights do exist on the strip, but as a deliberate sparse layer
    painted over this base at draw time (see `_paint_sparks`). Keeping the base
    itself free of white is what lets it stay precomputed.
    """
    for i in range(0, N, 17):
        for e in (0.0, 0.5, 1.0):
            r, g, b = w.led_rgb(i, N, e)
            assert g < r * 0.15
            assert b < r * 0.15


def test_gamma_darkens_relative_to_srgb():
    """WS2812 PWM is linear; writing the sRGB byte straight out is too bright."""
    srgb = w.page_pixel(w.strip_t(299, N), 1.0)
    linear = w.led_rgb(299, N, 1.0, exposure=1.0)
    assert linear[0] < srgb[0]
    assert linear[1] < srgb[1]


def test_ease_is_the_css_cubic_bezier():
    assert w.ease(0.0) == 0.0
    assert w.ease(1.0) == 1.0
    # cubic-bezier(.2,0,0,1) is an emphasised decelerate: most of the travel
    # happens in the first quarter, then it flattens out.
    assert w.ease(0.10) == pytest.approx(0.156, abs=0.01)
    assert w.ease(0.25) == pytest.approx(0.607, abs=0.01)
    assert w.ease(0.50) == pytest.approx(0.878, abs=0.01)
    assert w.ease(0.75) == pytest.approx(0.975, abs=0.01)
    prev = -1.0
    for i in range(21):
        v = w.ease(i / 20.0)
        assert v >= prev
        prev = v


def test_frame_index_walks_a_triangle_over_two_periods():
    steps = 64
    period = w.BREATHE_PERIOD_S
    assert w.frame_index(0.0, steps) == 0
    assert w.frame_index(period, steps) == steps - 1
    assert w.frame_index(2 * period, steps) == 0
    # alternate: the ramp mirrors on the way back
    assert w.frame_index(period * 0.5, steps) == w.frame_index(period * 1.5, steps)


def test_engage_convention_starts_at_the_peak():
    """`_wash_engage` back-dates t0 by one period so the warning hits full."""
    assert w.frame_index(w.BREATHE_PERIOD_S, 64) == 63


def test_release_gain_matches_the_page_transition():
    assert w.release_gain(0.0) == 255
    assert w.release_gain(w.RELEASE_FADE_S) == 0
    assert w.release_gain(w.RELEASE_FADE_S + 1) == 0
    prev = 256
    for i in range(12):
        g = w.release_gain(i * w.RELEASE_FADE_S / 11.0)
        assert g <= prev
        prev = g


def test_build_frames_shape_and_padding():
    frames = w.build_frames(8, steps=5)
    assert len(frames) == 5
    for f in frames:
        assert isinstance(f, bytes)
        assert len(f) == 8 * 4
        # W channel unused on RGB WS2812B
        assert all(f[i * 4 + 3] == 0 for i in range(8))


def test_build_frames_ends_bracket_the_breathe():
    frames = w.build_frames(4, steps=16)
    assert frames[0][0] < frames[-1][0]


def test_fit_exposure_respects_a_power_budget():
    """A 600 LED red wash pulls double-digit amps — the cap has to bite."""
    full = w.estimate_current_a(N, 1.0)
    assert full > 6.0, "reference draw changed; revisit the power budget"

    capped = w.fit_exposure(N, 6.0)
    assert capped < w.DEFAULT_EXPOSURE
    assert w.estimate_current_a(N, 1.0, capped) == pytest.approx(6.0, rel=0.02)


def test_fit_exposure_noop_without_budget():
    assert w.fit_exposure(N, 0) == w.DEFAULT_EXPOSURE
    assert w.fit_exposure(N, None) == w.DEFAULT_EXPOSURE
    # A budget larger than the draw must not raise the exposure
    assert w.fit_exposure(N, 999) == w.DEFAULT_EXPOSURE


def test_build_frames_honours_the_cap():
    loose = w.build_frames(N, steps=2)
    tight = w.build_frames(N, steps=2, max_current_a=4.0)
    assert tight[-1][0] < loose[-1][0]


def test_single_led_strip_does_not_divide_by_zero():
    assert w.strip_t(0, 1) == 0.0
    assert len(w.build_frames(1, steps=3)) == 3


# ---- white highlights ------------------------------------------------------
# Not part of the page; added on request. They must stay sparse and smooth,
# otherwise they undo both the look and the precomputation.

def test_spark_envelope_fades_in_and_out():
    assert w.spark_envelope(0.0) == 0.0
    assert w.spark_envelope(w.SPARK_LIFE_S) == 0.0
    assert w.spark_envelope(-1.0) == 0.0
    assert w.spark_envelope(w.SPARK_LIFE_S * 2) == 0.0
    assert w.spark_envelope(w.SPARK_LIFE_S / 2) == pytest.approx(1.0, abs=1e-6)
    rising = [w.spark_envelope(w.SPARK_LIFE_S * x / 20) for x in range(11)]
    assert rising == sorted(rising)
    assert rising[1] < 0.25, "a hard onset would read as a blink, not a fade"


def test_spark_kernel_is_a_centred_bell():
    k = w.spark_kernel(2)
    assert len(k) == 5
    assert k[2] == pytest.approx(1.0)
    assert k[0] == k[4] and k[1] == k[3]
    assert k[0] < k[1] < k[2]
    assert all(0.0 <= v <= 1.0 for v in k)


def test_spark_kernel_degenerate_width():
    assert w.spark_kernel(0) == (1.0,)


def test_spark_rate_scales_with_the_breathe():
    assert w.spark_rate(0.0) == pytest.approx(w.SPARK_RATE_IDLE)
    assert w.spark_rate(1.0) == pytest.approx(w.SPARK_RATE_PEAK)
    assert w.spark_rate(0.5) > w.spark_rate(0.0)
    assert w.spark_rate(-5) == pytest.approx(w.SPARK_RATE_IDLE)
    assert w.spark_rate(5) == pytest.approx(w.SPARK_RATE_PEAK)


def test_spark_draw_stays_a_small_share_of_the_budget():
    """Highlights must accent the wash, not rival it on the supply."""
    wash = w.estimate_current_a(N, 1.0)
    sparks = w.spark_current_a()
    assert sparks < wash * 0.25
    assert sparks > 0.05, "too dim to be worth the code"
