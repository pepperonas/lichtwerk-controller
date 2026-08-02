"""Render the dB-Analyse page wash (`body.over-iris`) onto the WS2812 chain.

The reference is disco-controller's `public/stats.html`:

    body.warn-iris-bg.over-iris {
      background:
        radial-gradient(120% 100% at 50% 40%,
          rgba(255,70,60,.38), rgba(120,20,18,.55) 70%, #2a0c0c 100%),
        #3a1010;
    }
    body.warn-iris-bg.over-iris::before {
      background: rgba(255,60,50,.28);
      animation: iris-breathe 1.8s cubic-bezier(.2,0,0,1) infinite alternate;
    }
    @keyframes iris-breathe {
      0%   { opacity:.45; background:rgba(255,50,40,.22) }
      100% { opacity:1;   background:rgba(255,70,55,.4)  }
    }

This module reproduces that composite exactly — premultiplied gradient
interpolation and srcOver in sRGB, the same as the browser — and then maps it
onto the strip.

Two things the strip needs that a browser gets for free:

* **Geometry.** The page gradient is 2-D; the strip is a line. We take the
  horizontal centre scanline through the gradient origin (50% / 40%), so LED
  positions map to the row of pixels the origin sits on. The ellipse is 120%
  of the viewport width, hence the strip only spans t ∈ [0, 0.417] — a gentle
  falloff from the middle to both ends, exactly as on screen.

* **Gamma.** CSS colours are sRGB, meant for a display with a ~2.2 gamma.
  WS2812 PWM is linear in duty cycle, so writing the sRGB byte straight out
  renders the low channels far too bright and turns the brick red into a washed
  pink. We convert sRGB → linear light, which is what the LED actually needs,
  then apply an exposure gain so the result still works as a warning light
  rather than a dim replica of a screen.

Everything here is pure and hardware-free, so the colour maths can be unit
tested without a strip attached.
"""
from __future__ import annotations

# ---- the page, verbatim ----------------------------------------------------
PAGE_BASE = (58, 16, 16)                    # #3a1010
GRADIENT_STOPS = (                          # (position, rgb, alpha)
    (0.00, (255, 70, 60), 0.38),
    (0.70, (120, 20, 18), 0.55),
    (1.00, (42, 12, 12), 1.00),             # #2a0c0c
)
OVERLAY_FROM = ((255, 50, 40), 0.22, 0.45)  # rgb, background alpha, opacity
OVERLAY_TO = ((255, 70, 55), 0.40, 1.00)
BREATHE_PERIOD_S = 1.8                      # one direction; alternate → 3.6 s cycle
RELEASE_FADE_S = 0.55                       # body { transition: background .55s }
EASE = (0.2, 0.0, 0.0, 1.0)                 # cubic-bezier(.2,0,0,1)
ELLIPSE_RX = 1.2                            # radial-gradient(120% ...)

# ---- rendering defaults ----------------------------------------------------
DEFAULT_STEPS = 64                          # frames per breathe ramp
DEFAULT_EXPOSURE = 1.8                      # post-gamma gain (see module docstring)
MA_PER_CHANNEL = 0.020                      # WS2812B, one channel at full
MA_IDLE_PER_LED = 0.001                     # quiescent draw of the controller


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ease(x: float, bezier=EASE, iterations: int = 24) -> float:
    """Evaluate a CSS cubic-bezier(x1,y1,x2,y2) timing function at progress x.

    Solved by bisection — this only ever runs at precompute time, so accuracy
    is free and there is no reason to approximate it with a smoothstep.
    """
    x1, y1, x2, y2 = bezier
    x = max(0.0, min(1.0, x))
    if x in (0.0, 1.0):
        return x
    lo, hi = 0.0, 1.0
    for _ in range(iterations):
        t = (lo + hi) / 2.0
        u = 1.0 - t
        bx = 3.0 * u * u * t * x1 + 3.0 * u * t * t * x2 + t * t * t
        if bx < x:
            lo = t
        else:
            hi = t
    t = (lo + hi) / 2.0
    u = 1.0 - t
    return 3.0 * u * u * t * y1 + 3.0 * u * t * t * y2 + t * t * t


def gradient_at(t: float):
    """Sample the radial gradient at normalised radius t → (rgb, alpha).

    CSS interpolates gradient stops with premultiplied alpha; doing it
    unpremultiplied would darken the midpoint noticeably here, because the
    stops differ in both colour and alpha.
    """
    t = max(0.0, min(1.0, t))
    stops = GRADIENT_STOPS
    for i in range(len(stops) - 1):
        p0, c0, a0 = stops[i]
        p1, c1, a1 = stops[i + 1]
        if t <= p1 or i == len(stops) - 2:
            f = 0.0 if p1 == p0 else (t - p0) / (p1 - p0)
            f = max(0.0, min(1.0, f))
            pm = [_lerp(c * a0, d * a1, f) for c, d in zip(c0, c1)]
            a = _lerp(a0, a1, f)
            rgb = tuple(p / a for p in pm) if a > 1e-6 else (0.0, 0.0, 0.0)
            return rgb, a
    return tuple(float(v) for v in stops[-1][1]), stops[-1][2]


def _over(src, alpha: float, dst):
    return tuple(alpha * s + (1.0 - alpha) * d for s, d in zip(src, dst))


def page_pixel(t: float, e: float):
    """The sRGB colour the browser paints at radius t, breathe phase e ∈ [0,1]."""
    grad_rgb, grad_a = gradient_at(t)
    below = _over(grad_rgb, grad_a, PAGE_BASE)

    (c_from, a_from, o_from) = OVERLAY_FROM
    (c_to, a_to, o_to) = OVERLAY_TO
    overlay_rgb = tuple(_lerp(a, b, e) for a, b in zip(c_from, c_to))
    overlay_a = _lerp(a_from, a_to, e) * _lerp(o_from, o_to, e)
    return _over(overlay_rgb, overlay_a, below)


def srgb_to_linear(v: float) -> float:
    """sRGB byte → linear light 0..1 (the WS2812's actual PWM domain)."""
    c = max(0.0, min(1.0, v / 255.0))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def strip_t(i: int, n: int) -> float:
    """LED index → gradient radius, along the page's centre scanline."""
    if n <= 1:
        return 0.0
    return abs(i / (n - 1) - 0.5) / ELLIPSE_RX


def led_rgb(i: int, n: int, e: float, exposure: float = DEFAULT_EXPOSURE):
    """Final 8-bit PWM values for LED i at breathe phase e."""
    srgb = page_pixel(strip_t(i, n), e)
    out = []
    for v in srgb:
        lin = srgb_to_linear(v) * exposure
        out.append(max(0, min(255, int(round(lin * 255.0)))))
    return tuple(out)


def fit_exposure(n: int, max_current_a: float,
                 exposure: float = DEFAULT_EXPOSURE) -> float:
    """Largest exposure ≤ `exposure` whose breathe peak stays within a budget.

    A 600 LED red wash pulls double-digit amps; if the supply cannot deliver it
    the strip browns out, the far end shifts colour, and the whole point of the
    warning is lost. Scaling the exposure keeps hue and breathe dynamics intact
    and only trades away brightness.
    """
    if not max_current_a or max_current_a <= 0:
        return exposure
    idle = n * MA_IDLE_PER_LED
    budget = max_current_a - idle
    if budget <= 0:
        return 0.0
    peak = estimate_current_a(n, 1.0, exposure) - idle
    if peak <= budget or peak <= 0:
        return exposure
    return exposure * (budget / peak)


def build_frames(n: int, steps: int = DEFAULT_STEPS,
                 exposure: float = DEFAULT_EXPOSURE,
                 max_current_a: float | None = None):
    """Precompute the breathe ramp as ready-to-write RGBW payloads.

    Only the 0 → 1 ramp is stored; `alternate` replays it backwards, so
    `frame_index()` walks it as a triangle. 64 steps × 600 LEDs × 4 bytes is
    ~154 KB, and it collapses the per-frame cost to an index plus a write.
    """
    n = max(0, int(n))
    steps = max(2, int(steps))
    if max_current_a:
        exposure = fit_exposure(n, max_current_a, exposure)
    frames = []
    for s in range(steps):
        e = ease(s / (steps - 1))
        buf = bytearray(n * 4)
        for i in range(n):
            r, g, b = led_rgb(i, n, e, exposure)
            j = i * 4
            buf[j] = r
            buf[j + 1] = g
            buf[j + 2] = b
        frames.append(bytes(buf))
    return tuple(frames)


def frame_index(elapsed_s: float, steps: int) -> int:
    """Breathe position at `elapsed_s` seconds, as an index into build_frames()."""
    steps = max(2, int(steps))
    cycle = elapsed_s % (BREATHE_PERIOD_S * 2.0)
    frac = cycle / BREATHE_PERIOD_S
    if frac > 1.0:
        frac = 2.0 - frac
    idx = int(round(frac * (steps - 1)))
    return max(0, min(steps - 1, idx))


def release_gain(elapsed_s: float) -> int:
    """0..255 multiplier for the .55 s fade-out, matching the page transition."""
    if elapsed_s <= 0.0:
        return 255
    if elapsed_s >= RELEASE_FADE_S:
        return 0
    return int(round(255.0 * (1.0 - ease(elapsed_s / RELEASE_FADE_S))))


def estimate_current_a(n: int, e: float, exposure: float = DEFAULT_EXPOSURE) -> float:
    """Rough 5 V draw for a full-strip wash — the power budget is the real
    constraint on a 600 LED chain, so keep it checkable."""
    total = 0.0
    for i in range(n):
        total += sum(led_rgb(i, n, e, exposure)) / 255.0 * MA_PER_CHANNEL
    return total + n * MA_IDLE_PER_LED
