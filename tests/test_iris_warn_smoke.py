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
        assert all(wc.IRIS_GLOW_MIN <= v <= 1.0 for v in vals)
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
