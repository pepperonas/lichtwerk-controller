"""Smoke-Test: effect_iris_warn wird wirklich AUSGEFUEHRT (Fake-Strip).

Entstanden aus dem 2026-08-09-Ausfall: ein `blind_on`-NameError lief durch
alle Quelltext-Pin-Tests und py_compile — und liess den Strip live komplett
dunkel (der Effekt-Loop faengt Frame-Fehler und loggt sie nur). Diese Suite
treibt den Effekt ueber echte Frames inkl. Kick-Intake und Blinder-Plan;
JEDE unbehandelte Exception im Frame-Pfad faellt hier sofort auf.
"""

from __future__ import annotations

import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# flask_cors ist reine Deploy-Abhaengigkeit (CORS-Header) — auf Dev-Maschinen
# oft nicht installiert. Der Stub haelt die Suite dependency-frei; am Verhalten
# des Effekts aendert CORS nichts.
if 'flask_cors' not in sys.modules:
    try:
        import flask_cors  # noqa: F401
    except ImportError:
        import types
        sys.modules['flask_cors'] = types.SimpleNamespace(CORS=lambda app: None)

import web_controller as wc


class FakeStrip:
    """Minimale Strip-Attrappe: nimmt Frames an, zaehlt shows, traegt LUT."""

    def __init__(self, n=60, brightness=100):
        self._n = n
        self._px = [0] * n
        self._bri = brightness
        self.shows = 0

    def numPixels(self):
        return self._n

    def setPixelColor(self, i, c):
        self._px[i] = c

    def fill(self, c):
        self._px = [c] * self._n

    def setBrightness(self, b):
        self._bri = int(b)

    def getBrightness(self):
        return self._bri

    def show(self):
        self.shows += 1
        return True


def fresh(strip=None):
    """Den (im Demo-Modus gebauten) Modul-Controller pro Test zuruecksetzen."""
    c = wc.controller
    c.strip = strip or FakeStrip()
    c.effect_params = {}
    c.brightness = 100
    c.strip_lut_default = 100
    c._cleared = False
    c.power = True
    return c


def run_frames(c, count, dt=0.02):
    for _ in range(count):
        c.effect_iris_warn()   # jede Exception laesst den Test platzen
        time.sleep(dt)


def test_effect_survives_engage_sustain_and_kicks():
    c = fresh()
    run_frames(c, 8)
    # Kick wie ihn /api/warn_kick einreiht
    c.effect_params.setdefault('iris_kicks', []).append({'s': 0.8, 'bpm': 128.0})
    run_frames(c, 8)
    assert c.strip.shows > 0, "the effect must actually write frames"


def test_blinder_event_neutralises_the_lut_and_restores_it():
    """Die Regression von 2026-08-09 in ausfuehrbar: ein Doppel-Blitz-Event
    muss (a) ohne Exception rendern, (b) waehrend ON-Fenstern die Strip-LUT
    auf 255 neutralisieren und (c) sie nach Planende wiederherstellen."""
    c = fresh()
    run_frames(c, 6)
    c.effect_params.setdefault('iris_events', []).append(
        {'kind': 'double', 'gap': 0.12, 'n': 2})
    saw_neutral = False
    for _ in range(24):
        c.effect_iris_warn()
        if c.strip.getBrightness() == 255:
            saw_neutral = True
        time.sleep(0.02)
    assert saw_neutral, "blinder ON frames must neutralise the strip LUT to 255"
    run_frames(c, 40)   # Plan + 0.28 s Nachglimmen ausklingen lassen
    assert c.strip.getBrightness() == 100, \
        "after the plan (incl. decay) the configured LUT brightness must be restored"


def test_roll_and_accent_render_without_raising():
    c = fresh()
    run_frames(c, 6)
    c.effect_params.setdefault('iris_events', []).append(
        {'kind': 'roll', 'gap': 0.12, 'n': 4})
    run_frames(c, 30)
    c.effect_params.setdefault('iris_events', []).append({'kind': 'accent'})
    run_frames(c, 10)
    assert c.strip.shows > 20


def test_glow_factor_wanders_and_stays_in_band():
    """Wander-Glut (2026-08-11): Rot ist nie uniform — helle Zonen wandern.
    Direkt gegen die echte Funktion getestet (kein Spiegel-Drift moeglich)."""
    N = 600
    for t in (0.0, 3.7, 12.4):
        vals = [wc.iris_glow_factor(x, t) for x in range(N)]
        assert all(wc.IRIS['glow_min'] <= v <= 1.0 for v in vals)
        assert max(vals) - min(vals) > 0.3, "sichtbare Modulation, nicht uniform"
    # Die hellste Stelle WANDERT: argmax verschiebt sich ueber die Zeit
    def argmax_at(t):
        vals = [wc.iris_glow_factor(x, t) for x in range(N)]
        return vals.index(max(vals))
    a, b, c = argmax_at(0.0), argmax_at(4.0), argmax_at(9.0)
    assert len({a, b, c}) >= 2 and (abs(a - b) > 10 or abs(b - c) > 10)


def test_breathing_red_with_glow_renders_without_raising():
    """Der modulierte Basis-Pfad (per-LED-Loop + 4er-Block-Tabelle) laeuft
    exceptionfrei durch echte Sustain-Frames, auch mit Kick + Welle."""
    c = fresh()
    run_frames(c, 16)   # Engage (0.21 s) + Sustain-Frames
    c.effect_params.setdefault('iris_kicks', []).append({'s': 0.9, 'bpm': 128.0})
    run_frames(c, 16)
    assert c.strip.shows > 10


def test_shadow_pockets_dim_visibly_and_softly():
    """Schattenzonen (2026-08-11): 30-90 LED breite Bereiche dimmen das Rot
    deutlich (Zentrum auf 15-45 %), mit weichen Raendern und Trapez-Leben."""
    pk = {'pos': 300.0, 'width': 60.0, 'depth': 0.8, 'life': 6.0,
          'vel': 0.0, 'born': 0.0}
    now = 3.0   # mitten im Leben -> alpha 1
    centre = wc.iris_shadow_field(300, [pk], now)
    assert 0.15 < centre < 0.25, "Zentrum muss DEUTLICH dimmen (depth 0.8)"
    edge = wc.iris_shadow_field(300 + 60, [pk], now)
    assert edge > centre + 0.3, "weicher Abfall: eine Breite weiter ist es viel heller"
    far = wc.iris_shadow_field(300 + 200, [pk], now)
    assert far > 0.97, "ausserhalb bleibt das Rot praktisch voll"
    # Trapez: frisch gespawnt und kurz vor dem Tod ist die Zone unsichtbar
    assert wc.iris_shadow_field(300, [pk], 0.05) > 0.9
    assert wc.iris_shadow_field(300, [pk], 5.95) > 0.9
    # Drift: die Zone WANDERT mit vel
    pk2 = dict(pk, vel=10.0)
    assert wc.iris_shadow_field(300 + 30, [pk2], 3.0) < wc.iris_shadow_field(300 + 30, [pk], 3.0)


def test_shadow_sizes_match_the_50_to_150_cm_request():
    """50-150 cm bei 60 LED/m = 30-90 LEDs — die Konstanten muessen die
    Nutzer-Anforderung woertlich abbilden."""
    assert wc.IRIS['shadow_w_min'] == 30 and wc.IRIS['shadow_w_max'] == 90
    assert 0.5 <= wc.IRIS['shadow_depth_min'] < wc.IRIS['shadow_depth_max'] <= 0.9


def test_shadow_zombies_are_pruned_and_fresh_cohort_is_visible_immediately():
    """Regression 2026-08-11: iris_t0 resettet je Warn-Flanke — Zonen mit
    born aus der alten Zeitrechnung hatten negatives Alter (alpha 0), starben
    nie und blockierten den Nachschub: Schatten dauerhaft unsichtbar. Jetzt:
    Zeitreisende werden entsorgt, und die Initial-Kohorte spawnt RUECKDATIERT
    (sofort mitten im Leben = sofort sichtbar trotz flatternder Flanke)."""
    c = fresh()
    # Zombie aus einer frueheren Zeitrechnung einschleusen
    c.effect_params['iris_shadows'] = [
        {'pos': 100.0, 'width': 60.0, 'depth': 0.8, 'life': 6.0,
         'vel': 0.0, 'born': 9999.0}]
    run_frames(c, 16)   # Engage + erste Sustain-Frames
    pockets = c.effect_params['iris_shadows']
    assert len(pockets) == wc.IRIS['shadow_count']
    assert all(pk['born'] < 100 for pk in pockets), "Zombie muss entsorgt sein"
    # Rueckdatierung: mindestens eine Zone ist bereits voll eingeblendet
    # (Alter >= Einblendzeit) — die Kohorte ist SOFORT sichtbar.
    visible = [pk for pk in pockets
               if wc.iris_shadow_alpha(max(0.0, 0.5 - pk['born']), pk['life']) > 0.3]
    assert visible, "Initial-Kohorte muss ohne 1-s-Wartezeit sichtbar sein"


GOLDEN_FRAME_HASH = "a38f6cdb0b2100c4fb11090ecba036ef745f80c31fb0fc6490df238564f6f446"


def test_golden_frames_with_seed_and_fake_clock():
    """L1-Waechter (Phase 3): Seed + injizierte Fake-Uhr => bitgenau
    reproduzierbare Frames. Der Hash ist der Verhaltens-Fingerabdruck der
    Baseline — JEDE unbeabsichtigte Verhaltensaenderung (auch durch kuenftige
    Feature-Schalter im AUS-Zustand) aendert ihn und faellt hier auf.
    Absichtliche Aenderungen pinnen einen neuen Hash MIT Begruendung."""
    import hashlib
    state = {"t": 100.0}
    c = fresh()
    c.iris_clock = lambda: state["t"]
    wc.apply_iris_config({"seed": 1234})
    try:
        h = hashlib.sha256()

        def frames(n):
            for _ in range(n):
                state["t"] += 0.02
                c.effect_iris_warn()
                h.update(repr(c.strip._px).encode())

        frames(30)                                        # Engage + Sustain
        c.effect_params.setdefault("iris_kicks", []).append(
            {"s": 0.8, "bpm": 128.0})                     # Tempo-Lock + Welle
        frames(30)
        c.effect_params.setdefault("iris_events", []).append(
            {"kind": "double", "gap": 0.12, "n": 2})      # Sparkle-Blinder
        frames(40)
        assert h.hexdigest() == GOLDEN_FRAME_HASH
    finally:
        wc.apply_iris_config(None)
        if hasattr(c, "iris_clock"):
            del c.iris_clock
