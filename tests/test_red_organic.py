"""red_organic (Rot-Brief 2026-08-13): pure Kerne + Renderer-Integration.

Die Abnahme-Kriterien aus docs/red-organic-plan.md als Tests:
- classic (Default) bleibt bit-identisch (Golden-Hash liegt in
  test_iris_warn_smoke.py — hier der Beweis, dass organic sich WIRKLICH
  unterscheidet und der Rueckweg existiert)
- Weiss-Frames sind zwischen den Profilen BYTE-IDENTISCH (gesperrtes Terrain)
- Retrigger stapelt statt zu teleportieren
- Velocity ist sichtbar, Farbrampe haelt die Nie-Weiss-Kappe, Dithering
  mittelt exakt, Bass bewegt das Feld ohne Kicks
"""

from __future__ import annotations

import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if 'flask_cors' not in sys.modules:
    try:
        import flask_cors  # noqa: F401
    except ImportError:
        import types
        sys.modules['flask_cors'] = types.SimpleNamespace(CORS=lambda app: None)

_TESTS = pathlib.Path(__file__).parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import red_organic as ro
import web_controller as wc
from test_iris_warn_smoke import FakeStrip, fresh


# ── pure Kerne ───────────────────────────────────────────────────────────


def test_pulse_env_shape_and_continuity():
    atk, dec, sus, tail = 0.014, 0.24, 0.30, 0.34
    assert ro.pulse_env(0.0, atk, dec, sus, tail) == 0.0
    # Attack steigt s-foermig auf 1.0
    assert 0.4 < ro.pulse_env(atk * 0.5, atk, dec, sus, tail) < 0.6
    # Stetigkeit an der Attack-Grenze (rise(1) == punch+sus == 1)
    lo = ro.pulse_env(atk - 1e-4, atk, dec, sus, tail)
    hi = ro.pulse_env(atk + 1e-4, atk, dec, sus, tail)
    assert abs(lo - hi) < 0.02
    # Anfangs-Decay ist kraeftig, der Sustain-Schwanz traegt danach
    mid = ro.pulse_env(atk + dec, atk, dec, sus, tail)
    assert 0.05 < mid < 0.6
    # Ende: Schwanz vorbei -> praktisch 0, pulse_dead greift
    assert ro.pulse_env(atk + tail + 1.0, atk, dec, sus, tail) < 0.02
    assert not ro.pulse_dead(atk + tail * 0.5, atk, dec, sus, tail)
    assert ro.pulse_dead(atk + tail + 2.0, atk, dec, sus, tail)


def test_pulse_env_is_monotone_decaying_after_attack():
    atk, dec, sus, tail = 0.014, 0.24, 0.30, 0.34
    prev = 1.1
    for k in range(60):
        v = ro.pulse_env(atk + k * 0.01, atk, dec, sus, tail)
        assert v <= prev + 1e-9, "nach dem Attack darf nichts mehr steigen"
        prev = v


def test_soft_knee_identity_below_and_saturation_above():
    assert ro.soft_knee(0.5, 0.8) == 0.5
    assert ro.soft_knee(0.8, 0.8) == 0.8
    assert ro.soft_knee(3.0, 0.8) < 1.0          # asymptotisch, clippt nie
    # monoton
    xs = [ro.soft_knee(x / 10.0, 0.8) for x in range(40)]
    assert all(b >= a for a, b in zip(xs, xs[1:]))


def test_vel_peak_power_curve_and_floor():
    assert ro.vel_peak(0.0, 0.65, 0.18) == 0.18   # zartester Schlag sichtbar
    assert ro.vel_peak(1.0, 0.65, 0.18) == 1.0
    a, b = ro.vel_peak(0.3, 0.65, 0.18), ro.vel_peak(0.7, 0.65, 0.18)
    assert a < b, "monoton in der Velocity"
    # power < 1 hebt die Mitte (perzeptuell): 0.5 liegt UEBER der Geraden
    lin = 0.18 + (1.0 - 0.18) * 0.5
    assert ro.vel_peak(0.5, 0.65, 0.18) > lin


def test_pulse_cover_front():
    assert ro.pulse_cover(0.0, 10.0, 5.0) == 1.0     # im Radius
    assert ro.pulse_cover(9.9, 10.0, 5.0) == 1.0
    assert ro.pulse_cover(15.1, 10.0, 5.0) == 0.0    # jenseits der Front
    mid = ro.pulse_cover(12.5, 10.0, 5.0)
    assert 0.4 < mid < 0.6                           # weiche Kante


def test_bass_press_grows_from_both_ends():
    # env 0.4: die aeusseren 20 % je Seite stehen unter Druck, Mitte frei
    assert ro.bass_press(0.02, 0.4, 1.0) > 0.3
    assert ro.bass_press(0.98, 0.4, 1.0) > 0.3
    assert ro.bass_press(0.5, 0.4, 1.0) == 0.0
    assert ro.bass_press(0.5, 0.0, 1.0) == 0.0       # ohne Bass nichts
    # leiser Bass drueckt flacher (Amplitude x env)
    assert ro.bass_press(0.02, 0.2, 1.0) < ro.bass_press(0.02, 0.8, 1.0)


def test_one_pole_is_asymmetric():
    up = ro.one_pole(0.0, 1.0, 0.1, 0.12, 0.45)
    down = 1.0 - ro.one_pole(1.0, 0.0, 0.1, 0.12, 0.45)
    assert up > down, "Attack schneller als Release"


def test_gradient_never_toward_white_and_r_dominant():
    for drift in (-0.06, 0.0, 0.06):
        grad = ro.build_gradient(32, 140, 90, drift)
        assert len(grad) == 32
        for r, g, b in grad:
            assert g <= 140 and b <= 90, "Nie-Weiss-Kappe"
            assert r >= g, "Rot bleibt dominant"
        # Helligkeit steigt ueber die Rampe (dunkles Tiefrot -> Orangerot)
        assert sum(grad[0]) < sum(grad[15]) < sum(grad[31])
        assert grad[31][0] == 255


def test_dither8_mean_equals_value_and_is_deterministic():
    v = 10.37
    vals = [ro.dither8(v, ro.hash01(5, f, 0)) for f in range(2000)]
    mean = sum(vals) / len(vals)
    assert abs(mean - v) < 0.1, f"Erwartungswert muss v sein ({mean})"
    assert set(vals) <= {10, 11}
    assert ro.hash01(3, 7, 1) == ro.hash01(3, 7, 1)
    assert 0.0 <= ro.hash01(3, 7, 1) < 1.0


# ── Renderer-Integration (Fake-Uhr + Seed, wie die Golden-Tests) ─────────


def _lum(strip):
    s = 0
    for c in strip._px:
        s += ((c >> 16) & 255) + ((c >> 8) & 255) + (c & 255)
    return s


def _drive(profile, script, n=600, seed=77):
    """Frames fahren; `script` ist eine Liste von (frames, aktion|None,
    record: bool) — Rueckgabe (aufgezeichnete Frames, Controller)."""
    state = {"t": 100.0}
    c = fresh(FakeStrip(n))
    c.iris_clock = lambda: state["t"]
    c._iris_bass_in = None
    c._iris_bass_ts = 0.0
    wc.apply_iris_config({"seed": seed, "red_profile": profile})
    rec = []
    try:
        for frames, action, record in script:
            if action is not None:
                action(c)
            for _ in range(frames):
                state["t"] += 0.02
                c.effect_iris_warn()
                if record:
                    rec.append(tuple(c.strip._px))
        return rec, c
    finally:
        wc.apply_iris_config(None)
        if hasattr(c, "iris_clock"):
            del c.iris_clock


def _kick(s=0.7, bpm=126.0, vel=None, bass=None):
    def _do(c):
        k = {"s": s, "bpm": bpm}
        if vel is not None:
            k["vel"] = vel
        if bass is not None:
            k["bass"] = bass
        c.effect_params.setdefault("iris_kicks", []).append(k)
    return _do


def test_organic_differs_from_classic_but_classic_is_the_tag():
    """Der Schalter tut etwas — und der Golden-Hash in test_iris_warn_smoke
    beweist parallel, dass classic (Default) die Baseline IST."""
    script = [(30, None, False), (20, _kick(vel=0.9, bass=0.6), True)]
    a, _ = _drive("classic", script)
    b, _ = _drive("organic", script)
    assert a != b


def test_white_frames_byte_identical_between_profiles():
    """GESPERRTES TERRAIN: waehrend eines Sparkle-Blinder-Plans (Rot aus,
    nur Weiss-Spots) muss jedes Frame zwischen classic und organic
    byte-identisch sein — gleiche iris_rng-Ziehungssequenz, gleiche Spots,
    gleiche Gains. Organische Wuerfe laufen darum auf iris_rng_org."""
    def _white_frames(profile):
        state = {"t": 100.0}
        c = fresh(FakeStrip(600))
        c.iris_clock = lambda: state["t"]
        wc.apply_iris_config({"seed": 41, "red_profile": profile})
        rec = []
        try:
            for _ in range(30):
                state["t"] += 0.02
                c.effect_iris_warn()
            c.effect_params.setdefault("iris_kicks", []).append(
                {"s": 0.7, "bpm": 126.0, "vel": 0.9, "bass": 0.6})
            for _ in range(20):
                state["t"] += 0.02
                c.effect_iris_warn()
            c.effect_params.setdefault("iris_events", []).append(
                {"kind": "double", "gap": 0.12, "n": 2})
            for _ in range(30):
                state["t"] += 0.02
                c.effect_iris_warn()
                if c.effect_params.get("iris_blinder") is not None:
                    rec.append(tuple(c.strip._px))
            return rec
        finally:
            wc.apply_iris_config(None)
            del c.iris_clock

    a = _white_frames("classic")
    b = _white_frames("organic")
    assert len(a) >= 10, "der Plan muss real aufgezeichnet sein"
    assert a == b


def test_retrigger_stacks_instead_of_teleporting():
    """Ursache 2: der zweite Kick mitten im Verglimmen darf die Helligkeit
    nicht nach unten reissen. classic teleportiert (Phasen-Reset auf den
    Boden), organic stapelt — der Kontrast ist der Beweis."""
    def _jump(profile):
        state = {"t": 100.0}
        c = fresh(FakeStrip(600))
        c.iris_clock = lambda: state["t"]
        wc.apply_iris_config({"seed": 77, "red_profile": profile})
        try:
            for _ in range(30):                       # Engage + Sustain
                state["t"] += 0.02
                c.effect_iris_warn()
            c.effect_params.setdefault("iris_kicks", []).append(
                {"s": 0.9, "bpm": 126.0, "vel": 0.8})
            for _ in range(13):                       # 0.26 s Verglimmen
                state["t"] += 0.02
                c.effect_iris_warn()
            before = _lum(c.strip)
            c.effect_params.setdefault("iris_kicks", []).append(
                {"s": 0.9, "bpm": 126.0, "vel": 0.8})
            state["t"] += 0.02                        # 1 Frame nach Kick 2
            c.effect_iris_warn()
            return before, _lum(c.strip)
        finally:
            wc.apply_iris_config(None)
            del c.iris_clock

    b0, a0 = _jump("organic")
    assert a0 >= b0 * 0.93, f"organic darf nicht abwaerts springen ({b0} -> {a0})"
    b1, a1 = _jump("classic")
    assert a1 < b1 * 0.85, f"classic-Teleport als Kontrast erwartet ({b1} -> {a1})"


def test_velocity_is_visible():
    """Ursache 1: zarter vs. harter Schlag unterscheiden sich deutlich."""
    def _peak(vel):
        script = [(30, None, False), (8, _kick(s=0.6, vel=vel), True)]
        rec, _ = _drive("organic", script, seed=99)
        return max(sum(((c >> 16) & 255) + ((c >> 8) & 255) + (c & 255)
                       for c in fr) for fr in rec)
    soft, hard = _peak(0.1), _peak(1.0)
    assert hard >= soft * 1.25, f"Velocity muss sichtbar sein ({soft} vs {hard})"


def test_bass_alone_moves_the_field():
    """M1: eine Bassline OHNE Kick erzeugt die Druckwelle."""
    def _sum(bass_lvl):
        state = {"t": 100.0}
        c = fresh(FakeStrip(600))
        c.iris_clock = lambda: state["t"]
        wc.apply_iris_config({"seed": 55, "red_profile": "organic"})
        try:
            c._iris_bass_in = bass_lvl
            c._iris_bass_ts = time.monotonic() + 3600.0   # nie stale im Test
            for _ in range(40):
                state["t"] += 0.02
                c.effect_iris_warn()
            return _lum(c.strip)
        finally:
            wc.apply_iris_config(None)
            del c.iris_clock
    quiet, loud = _sum(0.0), _sum(0.9)
    assert loud > quiet * 1.15, f"Druckwelle fehlt ({quiet} vs {loud})"


def test_organic_frame_time_within_budget():
    """Performance-Kriterium aus dem Plan: << 20-ms-Schreibtakt; grosszuegige
    10 ms/Frame-Schranke faengt nur Pathologisches (Mac wie Pi 5)."""
    state = {"t": 100.0}
    c = fresh(FakeStrip(600))
    c.iris_clock = lambda: state["t"]
    wc.apply_iris_config({"seed": 7, "red_profile": "organic"})
    try:
        c.effect_params.setdefault("iris_kicks", []).append(
            {"s": 0.8, "bpm": 128.0, "vel": 0.9, "bass": 0.7})
        t0 = time.perf_counter()
        frames = 100
        for _ in range(frames):
            state["t"] += 0.02
            c.effect_iris_warn()
        per_frame = (time.perf_counter() - t0) / frames
        assert per_frame < 0.010, f"Frame-Zeit {per_frame * 1000:.2f} ms"
    finally:
        wc.apply_iris_config(None)
        del c.iris_clock


def test_profile_endpoint_switches_live_and_persists(tmp_path):
    """A/B-Umschaltung: POST wirkt sofort (IRIS) + schreibt config.json."""
    client = wc.app.test_client()
    old_cfg, old_file = wc.controller.config, wc.controller.config_file
    cfg_file = tmp_path / "config.json"
    wc.controller.config = {"led_config": {"pin": 21}}
    wc.controller.config_file = str(cfg_file)
    try:
        r = client.post('/api/iris/profile', json={"profile": "organic"})
        assert r.status_code == 200 and r.get_json()["profile"] == "organic"
        assert wc.IRIS.get("red_profile") == "organic"
        import json as _json
        assert _json.loads(cfg_file.read_text())["iris"]["red_profile"] == "organic"
        r = client.post('/api/iris/profile', json={"profile": "quatsch"})
        assert r.status_code == 400
        r = client.post('/api/iris/profile', json={"profile": "classic"})
        assert wc.IRIS.get("red_profile") == "classic"
        assert client.get('/api/iris/profile').get_json()["profile"] == "classic"
    finally:
        wc.controller.config, wc.controller.config_file = old_cfg, old_file
        wc.apply_iris_config(old_cfg.get('iris') if isinstance(old_cfg, dict) else None)


def test_warn_bass_endpoint_sets_level():
    client = wc.app.test_client()
    wc.controller._iris_bass_in = None
    r = client.post('/api/warn_bass', json={"level": 0.73})
    assert r.status_code == 200
    assert abs(wc.controller._iris_bass_in - 0.73) < 1e-9
    client.post('/api/warn_bass', json={"level": 7.0})
    assert wc.controller._iris_bass_in == 1.0            # geklemmt
    client.post('/api/warn_bass', json={"level": "kaputt"})
    assert wc.controller._iris_bass_in == 0.0            # failsafe
