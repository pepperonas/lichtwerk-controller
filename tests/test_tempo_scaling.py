"""Tempo-Skalierung (Tempo-Brief 2026-08-13): TempoBase + Renderer-Anbindung.

Abnahme-Kriterien aus docs/tempo-scaling-plan.md als Tests — allen voran der
120-BPM-ANKER: red_timing tempo <-> fixed muss dort BIT-IDENTISCH rendern.
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_TESTS = pathlib.Path(__file__).parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

if 'flask_cors' not in sys.modules:
    try:
        import flask_cors  # noqa: F401
    except ImportError:
        import types
        sys.modules['flask_cors'] = types.SimpleNamespace(CORS=lambda app: None)

import iris_config
import tempo_base
import web_controller as wc
from tempo_base import TempoBase
from test_iris_warn_smoke import FakeStrip, fresh

CFG = iris_config.load(None)
DT = 0.02


def _tick_until(tb, t0, seconds, cfg=CFG):
    t = t0
    st = None
    for _ in range(int(seconds / DT)):
        t += DT
        st = tb.tick(cfg, t)
    return t, st


def _feed_kicks(tb, t0, n, gap, bpm, strength=0.7, cfg=CFG):
    """n Kicks im gap-Abstand, dazwischen Frame-Ticks."""
    t = t0
    st = None
    for _ in range(n):
        steps = max(1, int(gap / DT))
        for _ in range(steps):
            t += DT
            st = tb.tick(cfg, t)
        tb.note_kick(cfg, t, bpm, strength)
    return t, st


# ── TempoBase pur ────────────────────────────────────────────────────────


def test_factor_values_match_the_plan():
    tb = TempoBase()
    tb.bpm_eff = 120.0
    assert tb.tick(CFG, 1.0)["f"] == 1.0
    tb2 = TempoBase()
    tb2.bpm_eff = tb2.target = 174.0
    assert abs(tb2.tick(CFG, 1.0)["f"] - 0.771) < 0.01
    tb3 = TempoBase()
    tb3.bpm_eff = tb3.target = 70.0
    assert abs(tb3.tick(CFG, 1.0)["f"] - 1.458) < 0.01


def test_ramp_is_never_a_jump():
    tb = TempoBase()
    t, _ = _feed_kicks(tb, 100.0, 2, 0.5, 120.0)
    tb.target = 140.0                       # direkte Ziel-Setzung: nur Rampe testen
    last = tb.bpm_eff
    max_step = 0.0
    for _ in range(int(3.0 / DT)):
        t += DT
        tb.tick(CFG, t)
        max_step = max(max_step, abs(tb.bpm_eff - last))
        last = tb.bpm_eff
    assert abs(tb.bpm_eff - 140.0) < 1.5, "nach 3 s praktisch am Ziel"
    assert max_step < 2.0, f"kein Sprung — groesster Schritt {max_step:.2f} BPM"


def test_big_jump_needs_confirmation_small_change_adopts():
    tb = TempoBase()
    _feed_kicks(tb, 100.0, 4, 0.476, 126.0)
    assert abs(tb.target - 126.0) < 0.1
    tb.note_kick(CFG, 110.0, 190.0, 0.7)    # einzelner Ausreisser
    assert abs(tb.target - 126.0) < 0.1, "1x 190 wird NICHT uebernommen"
    tb.note_kick(CFG, 110.3, 189.0, 0.7)
    tb.note_kick(CFG, 110.6, 191.0, 0.7)
    assert tb.target > 180.0, "3x konsistent -> uebernommen"
    tb2 = TempoBase()
    _feed_kicks(tb2, 100.0, 4, 0.476, 126.0)
    tb2.note_kick(CFG, 105.0, 132.0, 0.7)   # kleiner Wechsel: sofort
    assert abs(tb2.target - 132.0) < 0.1


def test_octave_error_halved_is_corrected_by_arrivals():
    """174er-Kick-Ankuenfte + gemeldete 87 (Halftime-Befund) -> nach 3
    Bestaetigungen korrigiert der Gegencheck auf die Ankunfts-Oktave."""
    tb = TempoBase()
    t = 100.0
    for i in range(10):
        t += 60.0 / 174.0                   # echte Ankuenfte: 174 BPM
        tb.note_kick(CFG, t, 87.0, 0.7)     # disco meldet die Haelfte
    assert tb.target > 160.0, f"Oktav-Korrektur muss greifen ({tb.target})"


def test_octave_error_doubled_is_corrected():
    tb = TempoBase()
    t = 100.0
    for i in range(10):
        t += 60.0 / 70.0                    # echte Ankuenfte: 70 BPM
        tb.note_kick(CFG, t, 140.0, 0.7)    # disco meldet das Doppelte
    assert tb.target < 80.0, f"({tb.target})"


def test_staleness_chain_stale_then_fallback_to_ref():
    tb = TempoBase()
    t, _ = _feed_kicks(tb, 100.0, 14, 0.428, 140.0)
    _tick_until(tb, t, 1.0)
    assert tb.source == "live"
    t2, st = _tick_until(tb, t, 4.0)
    assert tb.source == "stale" and abs(tb.target - 140.0) < 1.0, \
        "veraltet: letzter plausibler Wert haelt"
    t3, st = _tick_until(tb, t2, 30.0)
    assert tb.source == "fallback"
    assert abs(tb.bpm_eff - CFG["tempo_ref"]) < 5.0, \
        f"sanfte Rueckfuehrung auf die Referenz ({tb.bpm_eff:.0f})"


def test_zone_stretch_interpolates_and_reference_band_is_flat():
    tb = TempoBase()
    for bpm, lo, hi in ((70, 1.34, 1.36), (100, 1.11, 1.13),
                        (120, 0.999, 1.001), (128, 0.999, 1.001),
                        (132, 0.999, 1.001), (140, 0.87, 0.89),
                        (170, 0.74, 0.76), (110, 1.05, 1.07)):
        tb.bpm_eff = tb.target = float(bpm)
        tb._move = 1.0
        st = tb.tick(CFG, 1.0)
        assert lo <= st["stretch"] <= hi, f"{bpm}: {st['stretch']}"


def test_thinning_hysteresis_and_dwell():
    """Mit LEBENDEN Kicks (sonst zieht der Fallback das Tempo korrekt zur
    Referenz und der Test misst das Falsche)."""
    tb = TempoBase()
    t, st = _feed_kicks(tb, 100.0, 40, 60.0 / 152.0, 152.0)
    assert st["thinning"] is True and tb.source == "live"
    t, st = _feed_kicks(tb, t, 20, 60.0 / 147.0, 147.0)
    assert st["thinning"] is True, "Hysterese: bleibt an bis <= 145"
    t, st = _feed_kicks(tb, t, 40, 60.0 / 143.0, 143.0)
    assert st["thinning"] is False


def test_thin_factor_half_bar_raster_with_strength_bonus():
    tb = TempoBase()
    tb._thin = True
    for s in (0.3, 0.4, 0.5, 0.45, 0.35, 0.55, 0.4, 0.9):
        tb._strengths.append(s)
    tb._kicks = 1                            # Kick 1 = Raster ("1")
    assert tb.thin_factor(CFG, 0.3) == 1.0
    tb._kicks = 2                            # Zwischenschlag, schwach
    assert tb.thin_factor(CFG, 0.35) == CFG["thin_damp"]
    assert tb.thin_factor(CFG, 0.95) == 1.0, "starker Kick spielt trotzdem voll"
    tb._thin = False
    assert tb.thin_factor(CFG, 0.1) == 1.0


def test_move_drops_in_breakdown_and_stays_neutral_on_groove():
    tb = TempoBase()
    t = 100.0
    # Groove: Kicks im Takt + Bass hoch
    for i in range(24):
        t += 0.5
        tb.note_kick(CFG, t, 120.0, 0.7)
        tb.note_bass(t, 0.7)
        tb.tick(CFG, t)
    assert tb._move > 0.95, f"Groove = neutral ({tb._move:.2f})"
    # Breakdown: Kicks + Bass bleiben weg
    t2 = t
    for i in range(int(12.0 / 0.1)):
        t2 += 0.1
        tb.note_bass(t2, 0.05)
        tb.tick(CFG, t2)
    assert tb._move < 0.5, f"Breakdown muss die Bewegungsrate senken ({tb._move:.2f})"
    st = tb.tick(CFG, t2 + DT)
    assert st["stretch"] > 1.15, "Ruhe verlaengert die Zeitkonstanten"
    assert st["peak"] < 0.95, "und nimmt den Impuls-Anteil zurueck"


# ── Renderer-Integration ─────────────────────────────────────────────────


def _drive_organic(timing, kick_bpm, kick_gap, seconds_after=4.0, seed=77):
    """Organic mit Kicks fahren; Rueckgabe (Frames waehrend, Controller)."""
    state = {"t": 100.0}
    c = fresh(FakeStrip(600))
    c.iris_clock = lambda: state["t"]
    c._tempo = tempo_base.TempoBase()
    c._tempo_state = None
    wc.apply_iris_config({"seed": seed, "red_profile": "organic",
                          "red_timing": timing})
    frames = []
    try:
        for _ in range(30):                       # Engage + Sustain
            state["t"] += DT
            c.effect_iris_warn()
        next_kick = state["t"]
        for _ in range(int(seconds_after / DT)):
            state["t"] += DT
            if state["t"] >= next_kick:
                c.effect_params.setdefault("iris_kicks", []).append(
                    {"s": 0.7, "bpm": float(kick_bpm), "vel": 0.8})
                next_kick += kick_gap
            c.effect_iris_warn()
            frames.append(tuple(c.strip._px))
        # ⚠️ fresh() liefert den GETEILTEN Modul-Controller — Pulse hier
        # snapshotten, sonst liest der Vergleich den Zustand des 2. Laufs.
        pulses = [dict(p) for p in c.effect_params.get("iris_red_pulses") or []]
        return frames, pulses
    finally:
        wc.apply_iris_config(None)
        del c.iris_clock


def test_120_anchor_is_bit_identical():
    """DIE Brief-Randbedingung: bei 120 BPM aendert sich NICHTS —
    tempo <-> fixed rendern bit-identische Frames."""
    a, _ = _drive_organic("fixed", 120.0, 0.5)
    b, _ = _drive_organic("tempo", 120.0, 0.5)
    assert a == b


def test_decay_scales_with_tempo_and_clamps():
    """70 BPM -> laengere, 174 -> kuerzere Puls-Zeiten (Tabelle ±Toleranz);
    laufende Pulse tragen ihre Zeiten selbst (beim Spawn eingefroren)."""
    _, pulses_slow = _drive_organic("tempo", 70.0, 60.0 / 70.0, seconds_after=8.0)
    _, pulses_fast = _drive_organic("tempo", 174.0, 60.0 / 174.0, seconds_after=8.0)
    p_slow, p_fast = pulses_slow[-1], pulses_fast[-1]
    assert p_slow["dec"] > p_fast["dec"] * 1.5, \
        f"dec 70={p_slow['dec']:.3f} vs 174={p_fast['dec']:.3f}"
    assert p_slow["tail"] > p_fast["tail"] * 1.4
    assert 0.005 <= p_fast["atk"] <= 0.040, "Klemme haelt"
    # fixed traegt dieselben Felder mit F=1 (Umschalt-Robustheit)
    _, pulses_fix = _drive_organic("fixed", 120.0, 0.5)
    p = pulses_fix[-1]
    assert "dec" in p and "atk" in p and "tail" in p


def test_status_telemetry_and_endpoint_switch(tmp_path):
    client = wc.app.test_client()
    old_cfg, old_file = wc.controller.config, wc.controller.config_file
    wc.controller.config = {"led_config": {"pin": 21}}
    wc.controller.config_file = str(tmp_path / "config.json")
    try:
        r = client.post('/api/iris/profile',
                        json={"profile": "organic", "timing": "tempo"})
        assert r.get_json() == {"profile": "organic", "timing": "tempo"}
        st = wc.controller.get_status()
        assert st["red_timing"] == "tempo"
        assert set(st["tempo"]) == {"bpm", "source", "factor", "move", "thinning"}
        r = client.post('/api/iris/profile', json={"timing": "quatsch"})
        assert r.status_code == 400
        client.post('/api/iris/profile', json={"timing": "fixed"})
        assert wc.controller.get_status()["tempo"] is None
    finally:
        wc.controller.config, wc.controller.config_file = old_cfg, old_file
        wc.apply_iris_config(old_cfg.get('iris') if isinstance(old_cfg, dict) else None)