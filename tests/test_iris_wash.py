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


def test_wash_stays_red_dominant():
    """Red has to stay clearly dominant, lift or no lift.

    The breathe peak deliberately carries a white floor (white_lift) so it reads
    hot rather than flat, but the wash is a red warning — if green approaches
    red it has turned pink, which is the failure this guards.
    """
    for i in range(0, N, 17):
        for e in (0.0, 0.5, 1.0):
            r, g, b = w.led_rgb(i, N, e)
            assert r > 90, "wash went dim"
            assert g < r * 0.30, f"desaturated to pink at LED {i}, e={e}: {(r,g,b)}"
            assert b <= g, "blue must not lead green in a warm red"


def test_base_carries_no_white_floor():
    """The floor is off by design: it desaturated all 600 LEDs at once and, with
    red already near 255, pushed the colour along red → orange → yellow → white.
    White belongs in the highlights, where it can be crisp."""
    assert w.WHITE_PEAK == 0
    assert w.white_lift(1.0) == 0
    assert w.led_rgb(300, N, 1.0) == w.led_rgb(300, N, 1.0, white=0)



def test_breathe_varies_the_red_tone():
    """With no white floor the variation has to come from red itself."""
    lo, hi = w.led_rgb(300, N, 0.0), w.led_rgb(300, N, 1.0)
    assert hi[0] - lo[0] > 60, "breathe should move the red substantially"
    for c in (lo, hi):
        assert c[1] < c[0] * 0.12, f"stayed saturated? {c}"



def test_shimmer_is_a_flat_core_with_a_short_edge():
    """A bell spends most of its width in the mid amplitudes — and those are
    exactly the values that render orange and yellow, because red clips at 255
    while green and blue are still climbing. Flat core, short edge instead."""
    assert w.shimmer_amp(0, 1.0) == pytest.approx(w.SHIMMER_MIX)
    assert w.shimmer_amp(w.SHIMMER_WIDTH, 1.0) == 0.0
    assert w.shimmer_amp(0, 0.0) == 0.0, "must be gated on the breathe"
    inner = int(w.SHIMMER_WIDTH * w.SHIMMER_PLATEAU)
    assert w.shimmer_amp(inner, 1.0) == pytest.approx(w.SHIMMER_MIX), "core not flat"
    # The zone that renders as orange must stay a couple of LEDs wide
    mid = [o for o in range(w.SHIMMER_WIDTH + 1)
           if 0.15 < w.shimmer_amp(o, 1.0) < 0.85]
    assert len(mid) <= 3, f"transition too wide: {mid}"



def test_shimmer_bands_are_evenly_spaced_and_wrap():
    n, cnt = 600, 2
    a = w.shimmer_centre(0.0, n, 0, cnt)
    b = w.shimmer_centre(0.0, n, 1, cnt)
    assert abs((b - a) - n / cnt) < 1e-6
    # one full pass returns to the start
    period = n / w.SHIMMER_SPEED
    assert w.shimmer_centre(period, n, 0, cnt) == pytest.approx(a, abs=1e-6)
    assert 0 <= w.shimmer_centre(12345.6, n, 1, cnt) < n


def test_gamma_darkens_relative_to_srgb():
    """WS2812 PWM is linear; writing the sRGB byte straight out is too bright.

    Isolated with white=0: the white floor is added after the gamma conversion,
    so leaving it on compares the conversion against a different quantity and
    the assertion stops meaning anything.
    """
    srgb = w.page_pixel(w.strip_t(299, N), 1.0)
    linear = w.led_rgb(299, N, 1.0, exposure=1.0, white=0)
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


def _frame_current_a(frame, n):
    """Draw of an actual built frame — the formula alone misses the white lift."""
    tot = sum(frame[i*4] + frame[i*4+1] + frame[i*4+2] for i in range(n))
    return tot / 255.0 * w.MA_PER_CHANNEL + n * w.MA_IDLE_PER_LED


def test_cap_is_measured_on_the_built_frame():
    """The cap must hold for what is actually written, not just the exposure.

    white_lift is additive after the exposure, so scaling exposure alone would
    leave a term untouched and quietly bust the budget the cap promised.
    """
    full = w.estimate_current_a(N, 1.0)
    assert full > 6.0, "reference draw changed; revisit the power budget"
    for cap in (9.0, 8.0, 6.0):
        peak = w.build_frames(N, steps=2, max_current_a=cap)[-1]
        assert _frame_current_a(peak, N) == pytest.approx(cap, rel=0.03)


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


def test_spark_kernel_is_a_flat_core():
    k = w.spark_kernel(2)
    assert len(k) == 5
    assert k[1] == k[2] == k[3] == 1.0, "core must be flat white"
    assert k[0] == k[4] < 1.0, "one LED of edge"



def test_spark_kernel_degenerate_width():
    assert w.spark_kernel(0) == (0.45,)   # width 0 -> the single LED is the edge


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
    assert sparks < wash * 0.4, "highlights should accent the wash, not rival it"
    assert sparks > 0.05, "too dim to be worth the code"
