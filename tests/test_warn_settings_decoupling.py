"""Entkopplung Lichtwerk-Einstellungen vs. Iris/Strip-Warn (2026-08-12).

Feldbefund: 'die Einstellungen beissen sich' — (a) warn_gate ueberschrieb
die Nutzer-Brightness DAUERHAFT mit 255, (b) ein Brightness-/Speed-Write
aus der UI dimmte das LAUFENDE Warn-Bild, (c) color/effect wurden als
'blocked' schlicht VERWORFEN. Jetzt: Schnappschuss beim Scharfwerden,
UI-Writes waehrend des Warn landen als 'deferred' im Schnappschuss,
Restore beim Entschaerfen.
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).parent.parent
for _p in (str(_ROOT), str(_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_iris_warn_smoke import FakeStrip, fresh   # noqa: E402
import web_controller as wc                          # noqa: E402


def _boot():
    c = fresh(FakeStrip(60))
    c.strip_warn_mode = False
    c.strip_warn_over = False
    c._pre_warn = None
    c.current_effect = 'solid'
    c.brightness = 100
    c.speed = 50
    c.color = [255, 255, 255]
    wc.app.config['TESTING'] = True
    return c, wc.app.test_client()


def test_user_brightness_survives_a_warn_session():
    """Der Kern-Bug: Nutzer stellt 80 ein, Warn feuert (255er-Punch),
    Nutzer will waehrenddessen 40 — nach dem Warn gilt 40, und waehrend
    des Warn bleibt die LIVE-Helligkeit unangetastet bei 255."""
    c, cl = _boot()
    assert cl.post('/api/brightness', json={'brightness': 80}).get_json()['status'] == 'ok'
    assert c.brightness == 80

    cl.post('/api/warn_mode', json={'on': True})
    cl.post('/api/effect', json={'effect': 'iris_warn'})   # 255er-Punch
    assert c.brightness == 255

    r = cl.post('/api/brightness', json={'brightness': 40}).get_json()
    assert r['status'] == 'deferred' and r['reason'] == 'strip-warn'
    assert c.brightness == 255, "Live-Warn darf NICHT gedimmt werden"

    cl.post('/api/warn_mode', json={'on': False})
    assert c.brightness == 40, "der aufgehobene Nutzerwunsch gilt nach dem Warn"
    assert c.power is False, "Disarm-Semantik: Strip bleibt aus"
    assert c._pre_warn is None


def test_untouched_settings_restore_to_pre_warn_values():
    c, cl = _boot()
    cl.post('/api/brightness', json={'brightness': 66})
    cl.post('/api/speed', json={'speed': 33})
    cl.post('/api/warn_mode', json={'on': True})
    cl.post('/api/effect', json={'effect': 'iris_warn'})
    assert c.brightness == 255
    cl.post('/api/warn_mode', json={'on': False})
    assert c.brightness == 66 and c.speed == 33, \
        "ohne Aenderungen wird exakt der Vor-Warn-Stand wiederhergestellt"


def test_color_and_effect_are_deferred_not_dropped():
    c, cl = _boot()
    cl.post('/api/warn_mode', json={'on': True})
    cl.post('/api/effect', json={'effect': 'iris_warn'})
    r = cl.post('/api/color', json={'r': 10, 'g': 20, 'b': 30}).get_json()
    assert r['status'] == 'deferred'
    r = cl.post('/api/effect', json={'effect': 'rainbow'}).get_json()
    assert r['status'] == 'deferred'
    assert c.current_effect == 'iris_warn', "kein Effekt blitzt durchs Warn"
    assert c.color == [255, 255, 255], "Live-Farbe unangetastet"
    cl.post('/api/warn_mode', json={'on': False})
    assert c.color == [10, 20, 30]
    assert c.current_effect == 'rainbow'


def test_power_off_with_clear_warn_mode_also_restores():
    c, cl = _boot()
    cl.post('/api/brightness', json={'brightness': 77})
    cl.post('/api/warn_mode', json={'on': True})
    cl.post('/api/effect', json={'effect': 'iris_warn'})
    cl.post('/api/brightness', json={'brightness': 55})
    cl.post('/api/power', json={'power': False, 'clear_warn_mode': True})
    assert c.strip_warn_mode is False
    assert c.brightness == 55
    assert c._pre_warn is None


def test_repeated_flanks_keep_the_original_snapshot():
    """Folge-Flanken (warn_gate/effect je Ueberschreitung) duerfen den
    Schnappschuss NICHT mit der Warn-255 ueberschreiben."""
    c, cl = _boot()
    cl.post('/api/brightness', json={'brightness': 90})
    for _ in range(3):
        cl.post('/api/warn_mode', json={'on': True})
        cl.post('/api/effect', json={'effect': 'iris_warn'})
    assert c._pre_warn['brightness'] == 90
    cl.post('/api/warn_mode', json={'on': False})
    assert c.brightness == 90


def test_status_exposes_ownership_and_deferred_flag():
    c, cl = _boot()
    st = cl.get('/api/status').get_json()
    assert st['strip_warn_mode'] is False
    assert st['settings_deferred'] is False
    cl.post('/api/warn_mode', json={'on': True})
    cl.post('/api/effect', json={'effect': 'iris_warn'})
    st = cl.get('/api/status').get_json()
    assert st['strip_warn_mode'] is True
    assert st['settings_deferred'] is True   # Snapshot existiert
    cl.post('/api/warn_mode', json={'on': False})
    st = cl.get('/api/status').get_json()
    assert st['strip_warn_mode'] is False and st['settings_deferred'] is False


def test_normal_operation_unchanged_without_warn():
    c, cl = _boot()
    assert cl.post('/api/brightness', json={'brightness': 42}).get_json()['status'] == 'ok'
    assert cl.post('/api/color', json={'r': 1, 'g': 2, 'b': 3}).get_json()['status'] == 'ok'
    assert cl.post('/api/speed', json={'speed': 77}).get_json()['status'] == 'ok'
    assert c.brightness == 42 and c.color == [1, 2, 3] and c.speed == 77
