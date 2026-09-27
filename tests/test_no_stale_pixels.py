"""Kein Effekt darf Pixel des VORHERIGEN Bildes stehen lassen (2026-09-27).

Feldbefund 'LEDs bleiben haengen': ein Effekt, der nur einzelne Pixel malt
(Funken, Lauflicht), erbt den restlichen Puffer vom vorherigen Effekt bzw.
von eigenen ausgelaufenen Funken — diese Pixel zeigt der Strip dann fuer
immer. Probe: Puffer mit einer Sentinel-Farbe vorbelegen, die kein Effekt
je erzeugt, Effekt wechseln, Frames laufen lassen, Sentinel muss weg sein.
"""

import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
for _p in (str(_ROOT), str(_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_iris_warn_smoke import FakeStrip, fresh   # noqa: E402
import web_controller as wc                          # noqa: E402

SENTINEL = wc.Color(3, 1, 4)
EFFECTS = ['solid', 'rainbow', 'pulse', 'chase', 'sparkle', 'strobe',
           'meteor', 'breathe', 'sinelon', 'juggle', 'theater', 'gradient',
           'fire']


@pytest.mark.parametrize('effect', EFFECTS)
def test_effect_overwrites_the_previous_frame(effect):
    c = fresh(FakeStrip(60))
    c.power = True
    c.brightness = 200
    c.speed = 100
    c.color = [255, 255, 255]
    c.owner = 'lichtwerk'
    c.strip_warn_mode = False
    wc.app.config['TESTING'] = True
    cl = wc.app.test_client()
    assert cl.post('/api/effect', json={'effect': effect}).status_code == 200
    c.strip._px = [SENTINEL] * 60
    for _ in range(300):
        c.run_effect()
    stale = [i for i, p in enumerate(c.strip._px) if p == SENTINEL]
    assert not stale, f"{effect}: {len(stale)} Pixel vom vorigen Bild haengen"


def test_expired_sparkles_leave_no_residue():
    """Ein ausgelaufener Funke muss auf Schwarz enden, nicht auf seinem
    letzten Glimmwert stehen bleiben."""
    c = fresh(FakeStrip(60))
    c.power = True
    c.brightness = 255
    c.speed = 1          # kaum neue Funken
    c.color = [255, 255, 255]
    c.current_effect = 'sparkle'
    c.effect_params['sparkle_pixels'] = [{'index': 7, 'brightness': 1.0}]
    c.strip._px = [0] * 60
    wc.random.seed(1)
    for _ in range(80):
        c.effect_params['sparkle_pixels'] = [
            p for p in c.effect_params['sparkle_pixels'] if p['index'] == 7]
        c.effect_sparkle()
    assert c.strip._px[7] == 0


class _LockProbeStrip(FakeStrip):
    """show() prueft aus einem FREMDEN Thread, ob der Mal-Lock gehalten wird."""

    def __init__(self, lock_getter, n=60):
        super().__init__(n)
        self._lock_getter = lock_getter
        self.unguarded = 0

    def show(self):
        import threading
        res = {}

        def probe():
            lk = self._lock_getter()
            got = lk.acquire(blocking=False)
            if got:
                lk.release()
            res['free'] = got
        t = threading.Thread(target=probe)
        t.start()
        t.join()
        if res['free']:
            self.unguarded += 1
        return super().show()


@pytest.mark.parametrize('path,body', [
    ('/api/solid', {'r': 9, 'g': 9, 'b': 9, 'brightness': 50}),
    ('/api/effect', {'effect': 'iris_warn'}),
])
def test_request_threads_paint_under_the_strip_lock(path, body):
    """Anfragen-Threads malen in-request (Latenz) — parallel zum Effekt-Loop.
    Ohne gemeinsamen Lock mischen sich zwei Bilder im Puffer, und ein
    Frame nach einem Clear laesst den Strip trotz power=False leuchten."""
    c = fresh()
    c.strip = _LockProbeStrip(lambda: c._strip_lock)
    c.owner = 'lichtwerk'
    c.strip_warn_mode = False
    c.power = True
    wc.app.config['TESTING'] = True
    wc.app.test_client().post(path, json=body)
    assert c.strip.shows > 0
    assert c.strip.unguarded == 0


def test_effect_loop_frame_runs_under_the_strip_lock():
    c = fresh()
    c.strip = _LockProbeStrip(lambda: c._strip_lock)
    c.power = True
    c.owner = 'lichtwerk'
    c.strip_warn_mode = False
    wc.app.config['TESTING'] = True
    cl = wc.app.test_client()
    for eff in ('rainbow', 'chase', 'strobe', 'solid'):
        cl.post('/api/effect', json={'effect': eff})
        c.strip.unguarded = 0
        c.run_effect()
        assert c.strip.unguarded == 0, eff
    assert c.strip.shows > 0 and c.strip.unguarded == 0


def test_brightness_never_reaches_zero():
    """Feldbefund 2026-09-27: der Regler stand auf 0 — jeder Effekt malte
    schwarz, der Strip wirkte tot, 'egal was man drueckt'. Aus ist Aus
    (Power), die Helligkeit bleibt >= 1 — auch aus M5/Dashboard."""
    c = fresh(FakeStrip(10))
    c.owner = 'lichtwerk'
    c.strip_warn_mode = False
    wc.app.config['TESTING'] = True
    cl = wc.app.test_client()
    r = cl.post('/api/brightness', json={'brightness': 0}).get_json()
    assert r['brightness'] == 1 and c.brightness == 1
    src = (_ROOT / 'templates' / 'index.html').read_text()
    assert 'id="brightness-slider" min="1"' in src
