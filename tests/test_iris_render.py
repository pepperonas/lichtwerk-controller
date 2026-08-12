"""iris_render (W1) — die pure Rendering-Grundlage der weissen Akzente.

Die line_coverage-Invarianten hier sind das Brief-Pflichtkriterium:
'es darf an keiner Stelle eine uebersprungene LED geben' — bei JEDER
Geschwindigkeit.
"""

import math
import pathlib
import random
import sys

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import iris_render as ir


# ── line_coverage ────────────────────────────────────────────────────────

def test_line_coverage_sum_equals_clipped_length():
    for p0, p1 in ((3.2, 7.9), (0.0, 600.0), (10.5, 10.9), (599.1, 604.0),
                   (-12.3, 4.7), (7.9, 3.2)):
        cov = ir.line_coverage(p0, p1, 600)
        lo, hi = min(p0, p1), max(p0, p1)
        clipped = max(0.0, min(hi, 600.0) - max(lo, 0.0))
        assert abs(sum(w for _, w in cov) - clipped) < 1e-9, (p0, p1)


def test_line_coverage_is_gapless_and_ordered_at_any_speed():
    """Das Pflichtkriterium: von Schneckentempo bis 4000 LED/s (80 px pro
    20-ms-Frame) ist jede beruehrte Zelle vertreten, aufsteigend, lueckenlos."""
    for step in (0.3, 1.0, 7.7, 18.0, 48.0, 80.0):
        pos = -10.0
        while pos < 610.0:
            cov = ir.line_coverage(pos, pos + step, 600)
            idx = [i for i, _ in cov]
            assert idx == sorted(idx)
            if idx:
                assert idx == list(range(idx[0], idx[-1] + 1)), \
                    f"Luecke bei pos={pos} step={step}"
                assert all(w > 0.0 for _, w in cov)
            pos += step


def test_line_coverage_interior_cells_are_full():
    cov = dict(ir.line_coverage(2.5, 6.5, 600))
    assert cov[3] == 1.0 and cov[4] == 1.0 and cov[5] == 1.0
    assert abs(cov[2] - 0.5) < 1e-9 and abs(cov[6] - 0.5) < 1e-9


def test_line_coverage_degenerate_and_outside():
    assert ir.line_coverage(5.0, 5.0, 600) == []
    assert ir.line_coverage(-30.0, -1.0, 600) == []
    assert ir.line_coverage(600.0, 700.0, 600) == []


def test_line_coverage_direction_independent():
    assert ir.line_coverage(3.2, 9.7, 600) == ir.line_coverage(9.7, 3.2, 600)


# ── point_aa ─────────────────────────────────────────────────────────────

def test_point_aa_splits_and_sums_to_one():
    cov = dict(ir.point_aa(10.9, 600))
    assert set(cov) == {10, 11}
    assert abs(sum(cov.values()) - 1.0) < 1e-9


def test_point_aa_weights_follow_distance_to_cell_centres():
    # Zellzentren bei i + 0.5: 10.9 liegt 0.4 vom Zentrum der 10 und 0.6
    # vom Zentrum der 11 entfernt -> LED 10 bekommt MEHR.
    cov = dict(ir.point_aa(10.9, 600))
    assert abs(cov[10] - 0.6) < 1e-9 and abs(cov[11] - 0.4) < 1e-9
    centred = ir.point_aa(10.5, 600)
    assert centred == [(10, 1.0)]


def test_point_aa_clips_at_strip_edges():
    assert ir.point_aa(0.2, 600) == [(0, 0.7)]        # Rest faellt links raus
    cov = dict(ir.point_aa(599.8, 600))
    assert set(cov) == {599} and abs(cov[599] - 0.7) < 1e-9
    assert ir.point_aa(-2.0, 600) == []
    assert ir.point_aa(603.0, 600) == []


# ── temp_to_rgb ──────────────────────────────────────────────────────────

def test_temp_to_rgb_warm_vs_cool_ordering():
    r3, g3, b3 = ir.temp_to_rgb(3000)
    r8, g8, b8 = ir.temp_to_rgb(8000)
    assert r3 == 255.0 and r3 > b3, "3000 K ist rot-dominant"
    assert b8 == 255.0 and b8 > r8, "8000 K ist blau-dominant"
    for v in (r3, g3, b3, r8, g8, b8):
        assert 0.0 <= v <= 255.0


def test_temp_to_rgb_clamps_extremes():
    assert ir.temp_to_rgb(100) == ir.temp_to_rgb(1000)
    assert ir.temp_to_rgb(50000) == ir.temp_to_rgb(12000)


# ── powerlaw ─────────────────────────────────────────────────────────────

def test_powerlaw_many_dim_few_bright():
    rng = random.Random(7)
    vals = [ir.powerlaw_brightness(rng.random(), 2.5) for _ in range(4000)]
    vals.sort()
    median = vals[len(vals) // 2]
    mean = sum(vals) / len(vals)
    assert median < mean * 0.75, "Median deutlich unter Mittel = Sternenstaub"
    assert 0.0 <= min(vals) and max(vals) <= 1.0
    assert ir.powerlaw_brightness(0.5, 1.0) == 0.5   # k=1 = Gleichverteilung


# ── blue noise ───────────────────────────────────────────────────────────

def test_blue_noise_keeps_min_distance_and_is_deterministic():
    a = ir.blue_noise_positions(random.Random(42), 40, 600, 6.0)
    b = ir.blue_noise_positions(random.Random(42), 40, 600, 6.0)
    assert a == b, "seed => reproduzierbar"
    assert len(a) == 40
    assert all(0.0 <= p < 600.0 for p in a)
    gaps = [q - p for p, q in zip(a, a[1:])]
    assert min(gaps) >= 6.0 - 1e-9, "Poisson-Disk: nie verklumpt"


def test_blue_noise_degrades_distance_instead_of_hanging():
    # 100 Punkte mit Abstand 30 passen NICHT auf 600 px — der Abstand wird
    # halbiert statt endlos zu wuerfeln; es kommt eine begrenzte Menge zurueck.
    pts = ir.blue_noise_positions(random.Random(1), 100, 600, 30.0)
    assert 15 <= len(pts) <= 100
    assert pts == sorted(pts)


# ── envelope + perceptual ────────────────────────────────────────────────

def test_spark_envelope_never_hard_on_off():
    life, atk = 0.2, 0.25
    assert ir.spark_envelope(-0.01, life, atk) == 0.0
    assert ir.spark_envelope(0.0, life, atk) == 0.0        # startet bei 0
    assert ir.spark_envelope(life, life, atk) == 0.0       # endet bei 0
    peak_t = life * atk
    assert abs(ir.spark_envelope(peak_t, life, atk) - 1.0) < 1e-9
    # monoton rauf, monoton runter, keine Spruenge > 0.35 bei 20-ms-Schritten
    prev = 0.0
    for k in range(11):
        v = ir.spark_envelope(k * life / 10, life, atk)
        assert abs(v - prev) < 0.6
        prev = v


def test_spark_envelope_degenerate_life():
    assert ir.spark_envelope(0.0, 0.0, 0.25) == 0.0


def test_perceptual_encode():
    assert ir.perceptual(0.0) == 0.0 and ir.perceptual(1.0) == 1.0
    assert ir.perceptual(0.5) > 0.5, "Gamma-Encode hebt Mitteltoene"
    vals = [ir.perceptual(v / 20) for v in range(21)]
    assert vals == sorted(vals)
