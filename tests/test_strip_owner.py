"""Strip-Besitz: immer nur EINE App steuert den Strip (2026-09-27).

Feldbefund: Lichtwerk-App und dB-Analyse (Strip-Warn / Disco-Strip)
steuerten den Strip gleichzeitig — ein im Lichtwerk eingeschaltetes Bild
wurde von der naechsten Warn-Flanke uebermalt bzw. abgeschaltet, und ein
Power-On im Lichtwerk startete den liegengebliebenen `iris_warn` mit
255er-Helligkeit ohne disco dahinter.

Regel (Nutzerentscheid): die LETZTE Aktion gewinnt.
- disco beansprucht den Strip explizit (POST /api/owner {owner:'disco'}).
- Jede Bedienung OHNE disco-Kennung (Lichtwerk-App, Dashboard, M5,
  Gute Nacht) uebernimmt ihn zurueck: Nutzer-Einstellungen zurueck,
  disco wird benachrichtigt.
- disco-Schreibzugriffe ohne Besitz werden mit 409 abgewiesen — ein
  verspaeteter Warn-POST darf das Bild des Nutzers nicht mehr kippen.
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).parent.parent
for _p in (str(_ROOT), str(_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_iris_warn_smoke import FakeStrip, fresh   # noqa: E402
import web_controller as wc                          # noqa: E402

DISCO = {'X-Lichtwerk-Client': 'disco'}


def _boot(tmp_path, monkeypatch):
    c = fresh(FakeStrip(60))
    c.strip_warn_mode = False
    c.strip_warn_over = False
    c._pre_warn = None
    c.current_effect = 'rainbow'
    c.brightness = 80
    c.speed = 50
    c.color = [10, 20, 30]
    c.power = True
    c.owner = 'lichtwerk'
    monkeypatch.setattr(wc, 'OWNER_FILE', str(tmp_path / 'strip_owner.json'))
    notes = []
    monkeypatch.setattr(wc, '_notify_disco_released', lambda: notes.append(1))
    wc.app.config['TESTING'] = True
    return c, wc.app.test_client(), notes


def test_disco_claim_switches_lichtwerk_off(tmp_path, monkeypatch):
    c, cl, _ = _boot(tmp_path, monkeypatch)
    r = cl.post('/api/owner', json={'owner': 'disco'}, headers=DISCO)
    assert r.status_code == 200
    assert c.owner == 'disco'
    assert c.power is False, "Strip-Warn scharf = Lichtwerk-Bild aus"


def test_user_action_takes_the_strip_back(tmp_path, monkeypatch):
    c, cl, notes = _boot(tmp_path, monkeypatch)
    cl.post('/api/owner', json={'owner': 'disco'}, headers=DISCO)
    # disco engaged the warn meanwhile (255er-Punch, iris_warn)
    cl.post('/api/effect', json={'effect': 'iris_warn'}, headers=DISCO)
    assert c.current_effect == 'iris_warn' and c.brightness == 255
    # Nutzer drueckt im Lichtwerk auf Power
    r = cl.post('/api/power', json={'power': True})
    assert r.status_code == 200
    assert c.owner == 'lichtwerk'
    assert c.power is True
    assert c.current_effect == 'rainbow', "Nutzerbild zurueck, nicht iris_warn"
    assert c.brightness == 80, "nicht die Warn-255"
    assert notes, "disco muss erfahren, dass es den Strip verloren hat"


def test_disco_write_without_ownership_is_refused(tmp_path, monkeypatch):
    c, cl, _ = _boot(tmp_path, monkeypatch)
    for path, body in (('/api/effect', {'effect': 'iris_warn'}),
                       ('/api/power', {'power': False}),
                       ('/api/solid', {'r': 1, 'g': 2, 'b': 3})):
        r = cl.post(path, json=body, headers=DISCO)
        assert r.status_code == 409, path
    assert c.power is True and c.current_effect == 'rainbow'


def test_disco_release_restores_user_settings_and_stays_dark(tmp_path, monkeypatch):
    c, cl, notes = _boot(tmp_path, monkeypatch)
    cl.post('/api/owner', json={'owner': 'disco'}, headers=DISCO)
    cl.post('/api/effect', json={'effect': 'iris_warn'}, headers=DISCO)
    cl.post('/api/owner', json={'owner': 'lichtwerk'}, headers=DISCO)
    assert c.owner == 'lichtwerk'
    assert c.power is False
    assert c.current_effect == 'rainbow' and c.brightness == 80
    assert not notes, "disco hat selbst freigegeben — keine Rueckmeldung"


def test_user_write_when_lichtwerk_owns_does_not_notify(tmp_path, monkeypatch):
    c, cl, notes = _boot(tmp_path, monkeypatch)
    cl.post('/api/color', json={'r': 1, 'g': 2, 'b': 3})
    assert c.color == [1, 2, 3]
    assert not notes


def test_owner_survives_a_restart(tmp_path, monkeypatch):
    c, cl, _ = _boot(tmp_path, monkeypatch)
    cl.post('/api/owner', json={'owner': 'disco'}, headers=DISCO)
    assert wc._load_owner() == 'disco'
    cl.post('/api/power', json={'power': True})
    assert wc._load_owner() == 'lichtwerk'


def test_status_reports_owner(tmp_path, monkeypatch):
    c, cl, _ = _boot(tmp_path, monkeypatch)
    assert cl.get('/api/status').get_json()['owner'] == 'lichtwerk'
    cl.post('/api/owner', json={'owner': 'disco'}, headers=DISCO)
    assert cl.get('/api/status').get_json()['owner'] == 'disco'


def test_release_with_restore_brings_the_scene_back(tmp_path, monkeypatch):
    """Disco-Strip aus: das Bild von vor der Disco kommt zurueck (inkl. an)."""
    c, cl, _ = _boot(tmp_path, monkeypatch)
    cl.post('/api/owner', json={'owner': 'disco'}, headers=DISCO)
    cl.post('/api/solid', json={'r': 9, 'g': 9, 'b': 9, 'brightness': 3},
            headers=DISCO)
    cl.post('/api/owner', json={'owner': 'lichtwerk', 'restore': True},
            headers=DISCO)
    assert c.power is True
    assert c.current_effect == 'rainbow' and c.color == [10, 20, 30]
    assert c.brightness == 80


def test_takeover_by_colour_change_keeps_the_users_power(tmp_path, monkeypatch):
    c, cl, _ = _boot(tmp_path, monkeypatch)
    cl.post('/api/owner', json={'owner': 'disco'}, headers=DISCO)
    cl.post('/api/color', json={'r': 1, 'g': 2, 'b': 3})
    assert c.owner == 'lichtwerk'
    assert c.power is True, "war vor dem Warn an -> Farbwahl zeigt sich"
    assert c.color == [1, 2, 3]
