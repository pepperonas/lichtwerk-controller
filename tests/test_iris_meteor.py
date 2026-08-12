"""Meteor (W2) — Bewegungsqualitaet, Duck-Compositing, Flash-Bremse.

Der Lueckenlos-Test hier ist das Brief-Pflichtkriterium: bei v_min UND
v_max darf KEINE LED uebersprungen werden. Verhaltensvergleiche laufen als
Differenz zweier deterministischer Laeufe (gleicher Seed, gleiche Fake-Uhr)
— die Basis atmet selbst, ein stales Referenz-Frame taugt nicht.
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).parent.parent
for _p in (str(_ROOT), str(_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_iris_warn_smoke import FakeStrip, fresh   # noqa: E402
import web_controller as wc                          # noqa: E402


# ── pure Helfer ──────────────────────────────────────────────────────────

def test_meteor_pos_profiles():
    # const: exakt linear, dur = D/v0
    assert wc.iris_meteor_pos(0.5, 1000.0, 1.0, 'const') == 500.0
    # expo_out: monoton, anfangs schnell, am Ende ~45 % von v0 — nie kriechend
    v0, dur = 1000.0, 1.0
    xs = [wc.iris_meteor_pos(k / 20, v0, dur, 'expo_out') for k in range(21)]
    assert all(b > a for a, b in zip(xs, xs[1:])), "monoton"
    v_start = (xs[1] - xs[0]) * 20
    v_end = (xs[20] - xs[19]) * 20
    assert v_start > v_end > v0 * 0.40, f"whip, aber kein Kriechen ({v_end:.0f})"
    # jenseits dur: linear mit Endtempo weiter (Schweif gleitet hinaus)
    p1 = wc.iris_meteor_pos(dur, v0, dur, 'expo_out')
    p2 = wc.iris_meteor_pos(dur + 0.1, v0, dur, 'expo_out')
    assert abs((p2 - p1) - v0 * 0.45 * 0.1) < 1e-6


def test_meteor_dur_and_time_for_roundtrip():
    for profile in ('const', 'expo_out', 'accel'):
        v0 = 1400.0
        dur = wc.iris_meteor_dur(700.0, v0, profile)
        # Umkehrfunktion: time_for(pos(t)) == t
        for t in (0.0, dur * 0.3, dur * 0.9, dur * 1.2):
            x = wc.iris_meteor_pos(t, v0, dur, profile)
            assert abs(wc.iris_meteor_time_for(x, v0, dur, profile) - t) < 1e-6


def test_meteor_duck_is_continuous_at_all_boundaries():
    pre, fe, duck, rec = 0.12, 0.8, 0.35, 0.25
    f = lambda t: wc.iris_meteor_duck(t, pre, fe, duck, rec)   # noqa: E731
    assert f(0.0) == 1.0 and f(-1.0) == 1.0
    assert f(pre) == duck and f(fe - 0.01) == duck
    assert f(fe + rec) == 1.0 and f(fe + 2 * rec) == 1.0
    # stetig: kein Sprung > 0.12 bei 10-ms-Schritten
    prev = f(0.0)
    t = 0.0
    while t < fe + rec + 0.1:
        cur = f(t)
        assert abs(cur - prev) < 0.12, f"Sprung bei t={t:.2f}"
        assert duck - 1e-9 <= cur <= 1.0 + 1e-9
        prev, t = cur, t + 0.01


def test_meteor_jitter_is_deterministic_bounded_and_varied():
    vals = [wc.iris_meteor_jitter(i, 1) for i in range(600)]
    assert vals == [wc.iris_meteor_jitter(i, 1) for i in range(600)]
    assert all(-1.0 <= v <= 1.0 for v in vals)
    assert len({round(v, 3) for v in vals}) > 300, "Rauschen, keine Rampe"
    assert vals != [wc.iris_meteor_jitter(i, 2) for i in range(600)]


# ── Verhaltens-Harness ───────────────────────────────────────────────────

def _run(event, frames, cfg=None, dt=0.02, warmup=12):
    """Deterministischer Lauf: Warmup-Frames, dann `event` (oder None), dann
    `frames` Frames — liefert (frames als px-Listen, brightness je Frame)."""
    state = {"t": 100.0}
    c = fresh(FakeStrip(600))
    c.iris_clock = lambda: state["t"]
    conf = {"seed": 11}
    conf.update(cfg or {})
    wc.apply_iris_config(conf)
    try:
        for _ in range(warmup):
            state["t"] += dt
            c.effect_iris_warn()
        if event is not None:
            c.effect_params.setdefault("iris_events", []).append(dict(event))
        out, bris = [], []
        for _ in range(frames):
            state["t"] += dt
            c.effect_iris_warn()
            out.append(list(c.strip._px))
            bris.append(c.strip.getBrightness())
        return out, bris
    finally:
        wc.apply_iris_config(None)
        del c.iris_clock


def _g(px):
    return (px >> 8) & 0xFF


def _meteor_cells(with_ev, without_ev):
    """Zellen, in denen der Meteor sichtbar WEISS malt: gruener Kanal klar
    ueber der (geduckten) Basis desselben Frames im Vergleichslauf."""
    cells = set()
    for fa, fb in zip(with_ev, without_ev):
        for i in range(600):
            if _g(fa[i]) > _g(fb[i]) + 40:
                cells.add(i)
    return cells


def test_meteor_leaves_no_led_untouched_at_min_and_max_speed():
    """PFLICHTKRITERIUM: bei v_min (900) und v_max (2400) bekommt JEDE der
    600 LEDs sichtbare Meteor-Energie — keine uebersprungene LED, bei
    keiner Geschwindigkeit."""
    for v in (900, 2400):
        ev = {"kind": "meteor", "gap": 0.16, "n": 1, "dur": 0.0,
              "intensity": 1.0, "density": 1.0, "origin": 0.5, "dir": 1,
              "v": float(v)}
        frames = int((0.12 + (600 + 3 * v * 0.08 + 12) / (v * 0.725) + 0.4) / 0.02) + 5
        a, _ = _run(ev, frames)
        b, _ = _run(None, frames)
        cells = _meteor_cells(a, b)
        missing = sorted(set(range(600)) - cells)
        assert not missing, f"v={v}: {len(missing)} LEDs uebersprungen, z.B. {missing[:8]}"


def test_meteor_ducks_the_base_and_recovers():
    """Duck-Compositing: waehrend des Flugs liegt die EFFEKTIVE Basis-
    Helligkeit (px x LUT) bei ~duck x Vergleichslauf; nach Planende ist sie
    wieder identisch. Prueft implizit die LUT-Kompensation (Meteor-Frames
    laufen LUT-neutral 255, der Vergleichslauf mit LUT 100)."""
    ev = {"kind": "meteor", "gap": 0.16, "n": 1, "dur": 0.0, "v": 1200.0,
          "intensity": 1.0, "density": 1.0, "origin": 0.5, "dir": 1}
    frames = 90
    # freerun_jitter aus: der Meteor-Intake zieht aus der iris_rng — danach
    # wuerfelten die Laeufe VERSCHIEDENE Freilauf-Perioden und die Envelope-
    # Phasen truegen den Ratio-Vergleich davon (gemessen: 0.64 statt 0.35).
    # meteor_duck EXPLIZIT 0.35: seit „weiss nur wenn rot aus" (2026-08-12)
    # ist der DEFAULT 0.0 (Flug auf Schwarz) — hier wird der Duck-MECHANISMUS
    # samt LUT-Kompensation geprueft, nicht der Default.
    quiet = {"freerun_jitter": 0.0, "meteor_duck": 0.35}
    # Warmup 24 Frames: die Schatten-Kohorte muss VOR dem Event gespawnt
    # sein — der Intake zieht aus der iris_rng, und eine NACH dem Event
    # gewuerfelte Kohorte macht die Glut-Karten der Laeufe unvergleichbar
    # (Feldbefund: Ratio 0.64 statt 0.35, komplett andere Schattenzonen).
    a, bri_a = _run(ev, frames, cfg=quiet, warmup=24)
    b, bri_b = _run(None, frames, cfg=quiet, warmup=24)
    # Frame mitten im Flug: Pixel weit HINTER dem Schweifende ist reine Basis
    k = 30                                # t ~ 0.6 s nach Event
    assert bri_a[k] == 255 and bri_b[k] == 100, "Meteor-Frame muss LUT-neutral sein"
    probe = 5                             # Kopf bei ~1200*0.45s = weit rechts
    eff_a = ((a[k][probe] >> 16) & 0xFF) * bri_a[k] / 255.0
    eff_b = ((b[k][probe] >> 16) & 0xFF) * bri_b[k] / 255.0
    assert eff_b > 8, "Vergleichsbasis muss sichtbar leuchten"
    ratio = eff_a / eff_b
    assert 0.25 <= ratio <= 0.48, f"Duck ~0.35 erwartet, ist {ratio:.2f}"
    # Nach Planende (letzter Frame): exakt gleiche Basis wie der Vergleich
    assert a[-1] == b[-1] and bri_a[-1] == bri_b[-1] == 100, \
        "nach recover muss der Lauf auf die Baseline zurueckfallen"


def test_impact_flash_respects_the_strobe_brake():
    """Zwei Meteore kurz nacheinander: der erste Impact-Flash feuert, der
    zweite wird von max_flash_rate_hz unterdrueckt (Journal-los, rein ueber
    die Vollflaechen-Aufhellung gemessen)."""
    def flash_frames(events, frames, rate):
        state = {"t": 100.0}
        c = fresh(FakeStrip(600))
        c.iris_clock = lambda: state["t"]
        wc.apply_iris_config({"seed": 3, "max_flash_rate_hz": rate})
        try:
            for _ in range(12):
                state["t"] += 0.02
                c.effect_iris_warn()
            hits = []
            for f in range(frames):
                for at, ev in events:
                    if f == at:
                        c.effect_params.setdefault("iris_events", []).append(dict(ev))
                state["t"] += 0.02
                c.effect_iris_warn()
                gs = [_g(px) for px in c.strip._px]
                # Vollflaechen-Flash: praktisch ALLE Pixel deutlich gruen-hell
                if sum(1 for g in gs if g > 60) > 550:
                    hits.append(f)
            return hits
        finally:
            wc.apply_iris_config(None)
            del c.iris_clock

    ev = {"kind": "meteor", "gap": 0.16, "n": 1, "dur": 0.0, "v": 2400.0,
          "intensity": 1.0, "density": 1.0, "origin": 0.5, "dir": 1}
    # Fluege: ~0.12 pre + ~0.36 s Flug -> Plan ~0.75 s = ~38 Frames
    hits = flash_frames([(0, ev), (45, ev)], 95, rate=0.5)
    assert hits, "der erste Impact muss feuern"
    assert all(h < 45 for h in hits), \
        f"zweiter Impact muss von der 0.5-Hz-Bremse unterdrueckt sein: {hits}"


def test_meteor_disabled_ignores_the_event():
    ev = {"kind": "meteor", "gap": 0.16, "n": 1, "dur": 0.0, "v": 1200.0,
          "intensity": 1.0, "density": 1.0, "origin": 0.5, "dir": 1}
    a, bri_a = _run(ev, 40, cfg={"meteor_enabled": False})
    b, bri_b = _run(None, 40, cfg={"meteor_enabled": False})
    assert a == b and bri_a == bri_b


def test_meteor_default_flies_on_black():
    """2026-08-12 („weiss nur wenn rot aus"): Default meteor_duck = 0.0 —
    der Pre-Dip blendet das Rot komplett aus, der Flug laeuft auf SCHWARZ
    (fern von Kopf/Schweif kein Rot), Recover bringt es zurueck."""
    assert wc.IRIS["meteor_duck"] == 0.0, "Default ist Flug auf Schwarz"
    ev = {"kind": "meteor", "gap": 0.16, "n": 1, "dur": 0.0, "v": 1200.0,
          "intensity": 1.0, "density": 1.0, "origin": 0.5, "dir": 1}
    quiet = {"freerun_jitter": 0.0}
    a, bri_a = _run(ev, 90, cfg=quiet, warmup=24)
    b, bri_b = _run(None, 90, cfg=quiet, warmup=24)
    k = 30                     # mitten im Flug; px 5 liegt fern von Schweif
    assert a[k][5] == 0, "Basis fern vom Meteor muss SCHWARZ sein (rot aus)"
    assert b[k][5] != 0, "im Vergleichslauf atmet dort das Rot"
    assert a[-1] == b[-1] and bri_a[-1] == bri_b[-1], \
        "nach dem Recover ist das Rot bit-genau zurueck"
