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
        k = min(n, min(80, max(24 if n >= 48 else 3, n // 12)))
        k = min(k, max(1, (n * 2) // 5))
        rng = random.Random(int(t0 * 1000) ^ int(t * 200))
        for i in rng.sample(range(n), k):
            strip.setPixelColor(i, w)
    strip.show()


def test_iris_spark_density_contract():
    src = (_ROOT / "web_controller.py").read_text()
    assert "n // 12" in src
    assert "0.055" in src
    assert "(n * 2) // 5" in src


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


# ---- Beat-synced extension (2026-08-05): kicks, phase snap, shockwaves ------

def _src():
    return (_ROOT / "web_controller.py").read_text()


def test_kick_extension_falls_back_to_the_tagged_blitz():
    """Without kicks every frame must equal perfekt-20260805: phase offset
    rests at 0.0, period and duty are untouched, waves expire on their own."""
    src = _src()
    assert "self.effect_params['iris_ph'] = 0.0" in src
    assert "iris_ph', 0.0" in src              # default keeps the free-run identity
    assert "period = 0.55" in src
    assert "u < 0.65" in src
    assert "Fallback IS the tag" in src


def test_warn_kick_endpoint_is_an_event_not_a_frame():
    src = _src()
    assert "@app.route('/api/warn_kick', methods=['POST'])" in src
    assert "if len(q) < 8:" in src, "queue must shed bursts, not build a backlog"
    assert "if controller.current_effect == 'iris_warn':" in src, \
        "outside iris_warn the event must be a silent no-op"


def test_phase_snaps_onto_the_tempo_locked_grid():
    # u == 0 at the kick instant → the ON edge lands ON the beat. The modulus
    # is the MEASURED period, not the fixed 0.55: snapping a fixed 0.3575 s ON
    # window per kick collapsed the dark phase above ~160 BPM (measured as
    # "verharrt" — the strip latched solid crimson).
    assert "(t - 0.21) % iris_period" in _src()


def _sim_lit(kick_times, t, period_fallback=0.55):
    """Mirror of the tempo-locked square: EMA period + 0.24 s snap refractory."""
    ema, last_kick, last_snap, ph = None, None, -9.0, 0.0
    for k in [k for k in kick_times if k <= t]:
        if last_kick is not None and 0.24 <= k - last_kick <= 1.5:
            ema = (k - last_kick) if ema is None else ema + ((k - last_kick) - ema) * 0.25
        last_kick = k
        if k - last_snap >= 0.24:
            last_snap = k
            period = max(0.30, min(1.20, ema)) if ema is not None else period_fallback
            ph = (k - 0.21) % period
    period = (max(0.30, min(1.20, ema))
              if ema is not None and last_kick is not None and t - last_kick <= 1.6
              else period_fallback)
    u = ((t - 0.21 - ph) / period) % 1.0
    return u < 0.65


def test_dark_phase_survives_every_tempo():
    """The invariant behind the fix: at ANY kick rate every beat window must
    contain BOTH lit and dark samples. 175 BPM latched solid before."""
    for bpm in (100, 123, 140, 160, 175):
        iv = 60.0 / bpm
        kicks = [0.5 + i * iv for i in range(40)]
        # steady state: inspect the window between kick 30 and 31
        a = kicks[30]
        samples = [_sim_lit(kicks, a + f * iv) for f in
                   (0.02, 0.2, 0.4, 0.6, 0.8, 0.95)]
        assert any(samples), f"{bpm} BPM: never lit"
        assert not all(samples), f"{bpm} BPM: dark phase collapsed (verharrt)"


def test_onset_double_fire_cannot_eat_the_dark_phase():
    """on_beat fires per onset (snare+kick): pairs 120 ms apart at 123 BPM.
    The 0.24 s snap refractory must keep the blink alive regardless."""
    iv = 60.0 / 123
    kicks = []
    for i in range(40):
        kicks += [0.5 + i * iv, 0.5 + i * iv + 0.12]
    a = 0.5 + 30 * iv
    samples = [_sim_lit(kicks, a + f * iv) for f in
               (0.02, 0.2, 0.4, 0.6, 0.8, 0.95)]
    assert any(samples) and not all(samples), "double-fire collapsed the blink"


def test_free_run_fallback_keeps_the_tagged_period():
    # No kicks at all → the tagged 0.55 s / 65 % square, bit-identical maths.
    assert iris_phase(0.21) == _sim_lit([], 0.21)
    for i in range(60):
        t = 0.25 + i * 0.031
        assert iris_phase(t) == _sim_lit([], t), f"free-run diverged at t={t}"


def test_shockwave_replaces_toward_ember_gold():
    """Conservative current budget: the front REPLACE-blends crimson toward the
    head colour — additive blending would stack current on top of full crimson,
    and 600 LEDs of full white would be ~36 A.

    2026-08-09 (Nutzerentscheid "Glut statt Weiss"): der Kern ist GOLD-BERNSTEIN
    (255,190,96), nicht mehr Warmweiss — Weiss gehoert exklusiv den
    Event-Blindern + Drop (Interpunktions-Prinzip der dB-Analyse-Seite)."""
    src = _src()
    assert "255, 190, 96" in src, "core must be ember gold — white belongs to the blinders"
    assert "255, 110, 80" in src, "halo must stay hot red"
    # Replace-Blend in beiden Zonen: Halo mischt zur Zielfarbe, der Kern
    # mischt vom Halo-Ergebnis weiter Richtung Weiss — nie additiv aufs Rot.
    assert "(xr - br) * halo" in src, "halo must replace-blend, not add"
    assert "(wr - r_) * core" in src, "core must replace-blend on top of the halo"


def test_spark_boost_never_drops_below_the_tagged_density():
    # factor 1.0 + 0.6*boost: boost=0 → exactly the tagged shower.
    assert "1.0 + 0.6 * boost" in _src()


# ---- Standstill artifacts (2026-08-05): stuck green/blue pixels -------------

def test_show_reports_frame_delivery():
    """A silently dropped clear frame left the strip holding its last image
    forever. show() must surface the _write result so clear() can retry."""
    src = (_ROOT / "pio_strip.py").read_text()
    assert "return self._write(payload)" in src


def test_clear_writes_twice_and_only_latches_on_success():
    """WS2812 is GRB-serialised: one slipped bit shifts crimson's 255 into the
    green or blue slot — the standstill artifacts ARE our own red. Standard
    practice: write the blank frame twice (wire errors are per-transmission);
    and _cleared may only latch when the write actually landed."""
    src = _src()
    blk = src[src.index("def clear(self, force=False):"):]
    blk = blk[:blk.index("\n    def ")]
    assert "for versuch in range(2):" in blk
    assert "self.strip.show() is not False" in blk
    assert "self._cleared = ok" in blk
    assert "self._cleared = True" not in blk, "unconditional latch is the old bug"


def test_idle_reclear_heals_stuck_pixels():
    """At standstill nothing overwrites a mis-latched pixel — the off branch
    must re-assert black periodically (2 s), not just once."""
    src = _src()
    blk = src[src.index("if not self.power:"):]
    blk = blk[:blk.index("effects = {")]
    assert "_last_clear_ts" in blk
    assert "> 2.0" in blk


# ---- Optimisation pass (2026-08-06): BPM seed + ordered shutdown ------------

def test_bpm_seed_beats_the_gap_estimate():
    """disco's IOI-median BPM rides in the kick POST; the strip takes it
    directly instead of re-estimating tempo from inter-kick gaps (the EMA
    needed 4-8 kicks after a track change). EMA stays as the fallback for
    kicks without bpm — old clients keep working."""
    src = _src()
    assert "60.0 / float(kb)" in src
    assert "seed if seed else ema" in src
    assert "50.0 <= b <= 200.0" in src, "implausible bpm must not seed the period"
    assert "iris_beat_ema" in src, "the EMA fallback must survive"


def test_shutdown_joins_the_painter_before_the_final_clear():
    """A frame past the `running` check can paint AFTER an early clear: the
    strip then sits lit with nobody left to blank it until the next service
    start. The handler must stop the painter first and finish with the PROVEN
    double-clear (force=True) — the last frames on the wire are black."""
    src = _src()
    h = src[src.index("def signal_handler(self, sig, frame):"):]
    h = h[:h.index("sys.exit(0)")]
    assert "self.effect_thread.join" in h
    assert "self.clear(force=True)" in h
    assert h.index("join") < h.index("clear(force=True)"), "join must come first"


def test_hold_phases_heal_bit_slips_via_heartbeat():
    """A GRB bit-slip (shifted crimson = GREEN) in the last transmitted frame
    used to STAND for the whole hold window — the edge-only rewrite held the
    corruption in place. Wire errors are per-transmission, not sticky: the
    heartbeat re-sends every 0.12 s, so a slip lives 120 ms instead of a beat;
    the dark branch force-clears so black gets re-proven too."""
    src = _src()
    assert "iris_next_heal" in src
    assert "+ 0.08" in src   # 2026-08-06: Heilung 120 -> 80 ms (einheitlicher Schreibtakt macht es sicher)
    blitz = src[src.index("def effect_iris_warn"):src.index("def run_effect")]
    assert "self.clear(force=True)" in blitz, "dark phase must re-prove black"



def test_strip_drop_blinder_mirrors_the_page_bomb():
    """The strip fires the same dramaturgy as the page: a very hard kick after
    sustained energy (avg EMA) triggers a triple white blinder — at 55 % gain,
    because full warm white on 600 LEDs would be ~33 A and current spikes on
    the 5 V rail cause exactly the bit-slips the heartbeat fights. 8 s
    cooldown: bombs that repeat are wallpaper."""
    src = _src()
    assert "if ks >= 0.9 and avg >= 0.5" in src
    assert "> 8.0" in src
    assert "(0.0, 0.07, 1.0), (0.13, 0.22, 1.0), (0.30, 0.40, 0.7)" in src
    assert "scale * 0.55 * blinder[1]" in src, "blinder stays in the crimson current class"


def test_one_write_clock_for_all_paths():
    """Every paint path shares one 20 ms floor (= the 18 ms wire time).
    Racing the wire only produces EBUSY drops, and a dropped frame is a
    20 ms window in which a slip fragment stands."""
    src = _src()
    assert "iris_last_write" in src
    assert "< 0.02:" in src


def test_sparks_are_ember_not_white():
    """2026-08-09 (Nutzerentscheid): Per-Kick-Funken sind BERNSTEIN — Weiss ist
    Interpunktion und gehoert exklusiv den Event-Blindern + Drop. Nebeneffekt:
    weniger Spitzenstrom als das alte Warmweiss."""
    src = _src()
    blitz = src[src.index("if spark and n > 0:"):]
    blitz = blitz[:blitz.index("self.strip.show()")]
    assert "int(176 * scale)" in blitz and "int(64 * scale)" in blitz, \
        "sparks must be ember amber; white belongs to the blinders"
    assert "int(224 * scale)" not in blitz, "the old warm-white spark must not return"


# ---- Blinder-Scheduler (2026-08-09): Weiss nur auf Events ------------------

def blinder_state(win, bt):
    """Mirror of the scheduler evaluation in effect_iris_warn: None = Plan
    abgelaufen, sonst (an, gain); zwischen den Fenstern erzwungen dunkel."""
    if bt >= win[-1][1]:
        return None
    for a, b, g in win:
        if a <= bt < b:
            return (True, g)
    return (False, 0.0)


def double_win(gap):
    return ((0.0, 0.07, 1.0), (gap, gap + 0.07, 0.85))


def roll_win(gap, n):
    return tuple((i * gap, i * gap + 0.055, max(0.5, 1.0 - i * 0.14)) for i in range(n))


DROP_WIN = ((0.0, 0.07, 1.0), (0.13, 0.22, 1.0), (0.30, 0.40, 0.7))


def test_double_blinder_mirrors_the_measured_gap():
    """Peak — dunkel — Peak, exakt im gemessenen Kick-Abstand; zweiter Puls
    gedimmt (dieselbe Kurve, die auf der Seite per Opacity-Sampling gemessen
    wurde)."""
    win = double_win(0.18)
    assert blinder_state(win, 0.03) == (True, 1.0)
    assert blinder_state(win, 0.12) == (False, 0.0)      # harte Dunkelphase
    assert blinder_state(win, 0.20) == (True, 0.85)      # zweiter Puls, gedimmt
    assert blinder_state(win, 0.30) is None              # Plan abgelaufen


def test_roll_train_decays_but_never_below_half():
    win = roll_win(0.15, 5)
    gains = [g for _, _, g in win]
    assert gains == sorted(gains, reverse=True), "roll must decay"
    assert gains[0] == 1.0 and gains[-1] == 0.5
    assert all(g >= 0.5 for g in gains)
    # Pulse getrennt durch Dunkelphasen (gap 0.15 > Pulsdauer 0.055)
    assert blinder_state(win, 0.10) == (False, 0.0)
    assert blinder_state(win, 0.16) == (True, gains[1])


def test_drop_preset_is_the_tagged_triple_blinder():
    """Der Drop nutzt denselben Scheduler — als Preset mit exakt der alten
    Choreografie (0/0.07, 0.13/0.22, 0.30/0.40 @ 1.0/1.0/0.7)."""
    src = _src()
    assert "((0.0, 0.07, 1.0), (0.13, 0.22, 1.0), (0.30, 0.40, 0.7))" in src
    assert blinder_state(DROP_WIN, 0.05) == (True, 1.0)
    assert blinder_state(DROP_WIN, 0.10) == (False, 0.0)
    assert blinder_state(DROP_WIN, 0.35) == (True, 0.7)
    assert blinder_state(DROP_WIN, 0.45) is None


def test_warn_event_route_and_intake_contracts():
    """Event-Weiss: Route validiert kind/gap/n, Queue gekappt, laufender Plan
    gewinnt (Events verderblich), alter iris_drop_t0-Pfad vollstaendig ersetzt."""
    src = _src()
    assert "@app.route('/api/warn_event', methods=['POST'])" in src
    assert "('double', 'roll', 'accent')" in src, "kind whitelist"
    assert "max(0.06, min(0.40, float(data.get('gap_ms', 160)) / 1000.0))" in src
    assert "if len(evq) < 4:" in src, "queue cap sheds bursts"
    assert "if self.effect_params.get('iris_blinder') is not None:" in src, \
        "a running plan (esp. the drop) must win over a late event"
    assert "iris_drop_t0" not in src, "the old drop-only path must be fully replaced"
    # Blinder bleibt in der erprobten 55-%-Stromklasse
    assert "scale * 0.55 * blinder[1]" in src
