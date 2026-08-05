"""Audio-reactive spark spawning — the "random, but on the music" layer.

These tests pin *behaviour*, not arithmetic. The design claim is specific: the
music must move how **often** a highlight appears, never **whether** a given one
does. If a future change turns the spawner into a beat trigger, the statistical
tests here are what should fail first — a metronome passes every test that only
checks "sparks appear when the bass is loud".
"""
from __future__ import annotations

import pathlib
import random
import sys

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import iris_wash as w  # noqa: E402

N = 600
DT = 1.0 / 30.0  # the wash paces at WASH_FPS = 30


# ---- envelope follower -----------------------------------------------------

def test_attack_is_faster_than_release():
    """The asymmetry is the whole point: sit on the transient, decay after it."""
    rise = w.envelope_follow(0.0, 1.0, 0.02)
    fall = 1.0 - w.envelope_follow(1.0, 0.0, 0.02)
    assert rise > fall * 3, f"attack {rise:.3f} not decisively faster than release {fall:.3f}"


def test_attack_reaches_most_of_a_hit_within_one_frame():
    """A kick must not need three frames to register, or it lands visibly late."""
    assert w.envelope_follow(0.0, 1.0, DT) > 0.85


def test_release_still_audible_after_100ms():
    """Decay, not a cut — a hit should still be spawning a beat later."""
    env = 1.0
    for _ in range(3):  # ~100 ms at 30 fps
        env = w.envelope_follow(env, 0.0, DT)
    assert 0.15 < env < 0.85


def test_follower_converges_and_is_monotone():
    env, seen = 0.0, []
    for _ in range(200):
        env = w.envelope_follow(env, 0.7, DT)
        seen.append(env)
    assert seen == sorted(seen)
    assert env == pytest.approx(0.7, abs=1e-3)


def test_follower_ignores_zero_dt():
    assert w.envelope_follow(0.3, 1.0, 0.0) == 0.3


# ---- drive mixing ----------------------------------------------------------

def test_kick_outdrives_drone():
    """The core intent: a sustained sub must not out-spark an actual transient.

    Level alone would rank these the other way round, which is exactly the
    firehose the onset weighting exists to prevent.
    """
    drone = w.pulse_drive(level=0.95, onset=1.0)   # loud, but nothing happening
    kick = w.pulse_drive(level=0.35, onset=3.0)    # quieter, but a real hit
    assert kick > drone


def test_drone_still_simmers():
    """Not zero either — a bassline should keep the strip alive, just calmly."""
    assert 0.0 < w.pulse_drive(level=0.9, onset=1.0) < 0.45


def test_drive_is_clamped():
    assert w.pulse_drive(level=5.0, onset=99.0) <= 1.0
    assert w.pulse_drive(level=-1.0, onset=0.0) >= 0.0


def test_silence_gives_no_drive():
    assert w.pulse_drive(level=0.0, onset=1.0) == pytest.approx(0.0)


# ---- rate ------------------------------------------------------------------

def test_rate_never_drops_below_the_breathe():
    """A silent room must not mean a dead strip — this is a warning light first."""
    for e in (0.0, 0.5, 1.0):
        assert w.spark_rate_audio(e, drive=0.0) == pytest.approx(w.spark_rate(e))
        assert w.spark_rate_audio(e, drive=1.0) > w.spark_rate(e)


def test_rate_rises_monotonically_with_drive():
    rates = [w.spark_rate_audio(0.5, d / 10.0) for d in range(11)]
    assert rates == sorted(rates)


# ---- birth jitter ----------------------------------------------------------

def test_birth_age_is_within_the_jitter_window():
    for u in (0.0, 0.25, 0.5, 1.0):
        age = w.spark_birth_age(u)
        assert -w.SPARK_JITTER_S <= age <= 0.0


def test_unborn_spark_paints_nothing():
    """The delay costs nothing precisely because the envelope already handles it."""
    assert w.spark_envelope(w.spark_birth_age(1.0)) == 0.0


def test_jittered_sparks_do_not_all_bloom_on_the_same_frame():
    """A burst has to spatter across frames, not arrive as one flash."""
    rng = random.Random(7)
    ages = [w.spark_birth_age(rng.random()) for _ in range(40)]
    first_frame = sum(1 for a in ages if a + DT > 0.0)
    assert 0 < first_frame < len(ages), "burst landed all at once — that reads as synced"


# ---- lifetime --------------------------------------------------------------

def test_harder_hits_linger_longer():
    """Dynamics come from lifetime because the count is capped by the PSU."""
    soft = sum(w.spark_life(0.1, u / 20.0) for u in range(21))
    hard = sum(w.spark_life(1.0, u / 20.0) for u in range(21))
    assert hard > soft


def test_lifetime_stays_positive():
    for d in (0.0, 0.5, 1.0):
        for u in (0.0, 0.5, 1.0):
            assert w.spark_life(d, u) > 0.0


# ---- the spawner as a process ----------------------------------------------

def test_unconnected_bass_machinery_is_invisible():
    """The regression this replaced: shipping the dynamics before the signal.

    `spark_life`/`spark_birth_age` are not neutral at rest — with nothing driving
    them they shorten every spark from 0.70 s to ~0.4-0.5 s and delay its birth,
    which turns the bloom into a blink and drags the red->white blend through its
    orange middle often enough to read as colour. Until the audio feed exists the
    spawner must reproduce the fixed bloom exactly.
    """
    rng = random.Random(4)
    alive = w.spawn_sparks([], 90.0, DT, N, drive=0.0, rng=rng)
    assert alive, "nothing spawned — test says nothing"
    assert {life for _, _, life in alive} == {w.SPARK_LIFE_S}
    assert {age for _, age, _ in alive} == {0.0}


def test_the_dynamics_still_work_when_asked_for():
    """Off by default, not removed — the bass path switches them on."""
    rng = random.Random(4)
    alive = w.spawn_sparks([], 90.0, DT, N, drive=1.0, rng=rng,
                           jitter_s=w.SPARK_JITTER_S,
                           life_spread=w.SPARK_LIFE_SPREAD)
    assert len({round(life, 4) for _, _, life in alive}) > 1
    assert min(age for _, age, _ in alive) < 0.0


class _CountingRandom(random.Random):
    """Counts births directly — every spawn draws exactly one randrange."""

    births = 0

    def randrange(self, *a, **kw):
        self.births += 1
        return super().randrange(*a, **kw)


def test_spawn_count_tracks_the_density():
    """Poisson, not a trigger: mean arrivals must follow rate x dt.

    Net list growth cannot be used here — ageing removes sparks every frame, so
    growth understates births. Counting the draws is exact.
    """
    rng = _CountingRandom(11)
    rate, frames = 12.0, 4000
    alive = []
    for _ in range(frames):
        alive = w.spawn_sparks(alive, rate, DT, N, 0.5, rng, max_count=10**6)
    expected = rate * DT * frames
    assert rng.births == pytest.approx(expected, rel=0.12), \
        f"{rng.births} births vs {expected:.0f} expected"


def test_spawn_count_scales_with_the_music():
    """Twice the drive must actually mean measurably more highlights."""
    def births(drive):
        rng = _CountingRandom(23)
        alive = []
        rate = w.spark_rate_audio(0.5, drive)
        for _ in range(2000):
            alive = w.spawn_sparks(alive, rate, DT, N, drive, rng, max_count=10**6)
        return rng.births

    quiet, loud = births(0.0), births(1.0)
    assert loud > quiet * 3, f"drive barely moved the density ({quiet} → {loud})"


def test_identical_bass_bursts_draw_different_pictures():
    """The anti-metronome test. Same drive, same rate — different result.

    This is what separates the design from "flash on every beat": the music sets
    the density, chance sets the realisation.
    """
    def burst(seed):
        rng = random.Random(seed)
        alive = []
        for _ in range(6):
            alive = w.spawn_sparks(alive, w.spark_rate_audio(0.8, 1.0), DT, N, 1.0, rng)
        return [c for c, _, _ in alive]

    a, b = burst(1), burst(2)
    assert a and b
    assert a != b, "two identical bursts produced the same pattern"
    assert not (set(a) & set(b)), "bursts shared LED positions — not independent"


def test_spawner_respects_the_power_cap():
    """The cap is a current limit; a loud passage must not walk through it."""
    rng = random.Random(3)
    alive = []
    for _ in range(200):
        alive = w.spawn_sparks(alive, 500.0, DT, N, 1.0, rng)
        assert len(alive) <= w.SPARK_MAX


def test_sparks_expire():
    rng = random.Random(5)
    alive = w.spawn_sparks([], 60.0, DT, N, 1.0, rng)
    assert alive
    for _ in range(120):  # well past SPARK_LIFE_S even with the spread
        alive = w.spawn_sparks(alive, 0.0, DT, N, 0.0, rng)
    assert alive == []


def test_no_spawning_without_a_strip():
    rng = random.Random(2)
    assert w.spawn_sparks([], 50.0, DT, 0, 1.0, rng) == []
