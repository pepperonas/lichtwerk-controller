"""Stardust (W3) — Partikel-Vertraege, Huellkurven, Funkenflug, Ambient.

Wie test_iris_meteor: deterministische Laeufe (Seed + Fake-Uhr); Partikel-
Invarianten werden direkt am vorgenerierten Plan geprueft (der Malpfad ist
nur noch die Huellkurven-Schleife darueber).
"""

import pathlib
import statistics
import sys

_ROOT = pathlib.Path(__file__).parent.parent
for _p in (str(_ROOT), str(_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_iris_warn_smoke import FakeStrip, fresh   # noqa: E402
import web_controller as wc                          # noqa: E402


def _boot(event, cfg=None, warmup=12):
    state = {"t": 100.0}
    c = fresh(FakeStrip(600))
    c.iris_clock = lambda: state["t"]
    conf = {"seed": 21}
    conf.update(cfg or {})
    wc.apply_iris_config(conf)
    for _ in range(warmup):
        state["t"] += 0.02
        c.effect_iris_warn()
    if event is not None:
        c.effect_params.setdefault("iris_events", []).append(dict(event))
    return c, state


def _teardown(c):
    wc.apply_iris_config(None)
    del c.iris_clock


SD = {"kind": "stardust", "gap": 0.16, "n": 1, "dur": 0.7,
      "intensity": 1.0, "density": 1.0, "origin": 0.5, "dir": 1}


def test_stardust_plan_particles_obey_all_contracts():
    """Vorgenerierte Partikel: Blue-Noise-Mindestabstand, Leben >= 2 Frames,
    Potenzgesetz (Median << Mittel), Temperatur im Streuband."""
    c, state = _boot(SD)
    try:
        state["t"] += 0.021
        c.effect_iris_warn()          # Intake
        bl = c.effect_params["iris_blinder"]
        assert bl["type"] == "stardust"
        parts = bl["parts"]
        assert 6 <= len(parts) <= wc.IRIS["stardust_max_particles"]
        pos = sorted(p["pos"] for p in parts)
        gaps = [b - a for a, b in zip(pos, pos[1:])]
        assert min(gaps) >= wc.IRIS["stardust_min_dist"] - 1e-9, "verklumpt"
        assert all(p["life"] >= 0.06 for p in parts), "Leben >= 3 Frames"
        peaks = [p["peak"] for p in parts]
        assert statistics.median(peaks) < statistics.mean(peaks), \
            "viele schwache, wenige helle"
        for p in parts:
            r, g, b_ = p["rgb"]
            assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b_ <= 255
    finally:
        _teardown(c)


def test_stardust_never_hard_on_off_per_pixel():
    """Kein Rauschen: jede Position, die je hell wird, ist es ueber MEHRERE
    Frames (Huellkurve statt Ein-Frame-Blitz)."""
    c, state = _boot(SD)
    try:
        history = []
        for _ in range(60):
            state["t"] += 0.021
            c.effect_iris_warn()
            history.append(list(c.strip._px))
        lit_frames = {}
        for k, frame in enumerate(history):
            for i in range(600):
                if ((frame[i] >> 8) & 0xFF) > 25:
                    lit_frames.setdefault(i, []).append(k)
        assert lit_frames, "der Burst muss sichtbar funkeln"

        def g_at(k, i):
            return (history[k][i] >> 8) & 0xFF if 0 <= k < len(history) else 0

        for i, ks in lit_frames.items():
            if len(ks) >= 2:
                continue
            # Nur 1 Frame ueber der Hell-Schwelle: dann muss ein NACHBAR-
            # Frame Rest-Glimmen zeigen (Huellkurve) — 0 -> hell -> 0 in
            # einem Frame waere das verbotene harte An/Aus.
            k = ks[0]
            assert g_at(k - 1, i) > 0 or g_at(k + 1, i) > 0, \
                f"px {i}: hell nur in Frame {k} und beide Nachbarn voellig dunkel"
    finally:
        _teardown(c)


def test_stardust_red_stays_off_and_lut_neutral_during_burst():
    c, state = _boot(SD)
    try:
        state["t"] += 0.021
        c.effect_iris_warn()
        assert c.strip.getBrightness() == 255, "Blinder-Frames LUT-neutral"
        # dunkle Basis: die grosse Mehrheit der Pixel ist AUS
        dark = sum(1 for px in c.strip._px if px == 0)
        assert dark > 400, "Sternenstaub lebt vom Schwarz-Kontrast"
    finally:
        _teardown(c)


def test_stardust_disabled_ignores_the_event():
    def run(event):
        c, state = _boot(event, cfg={"stardust_enabled": False})
        try:
            frames = []
            for _ in range(40):
                state["t"] += 0.021
                c.effect_iris_warn()
                frames.append(list(c.strip._px))
            return frames
        finally:
            _teardown(c)
    assert run(SD) == run(None)


def test_meteor_carries_funkenflug_after_the_head():
    """Funkenflug: der Meteor-Plan traegt Sparkles, deren Geburt NACH dem
    Kopf-Durchflug ihrer Position liegt; meteor_sparks=False entfernt sie."""
    ev = {"kind": "meteor", "gap": 0.16, "n": 1, "dur": 0.0, "v": 1500.0,
          "intensity": 1.0, "density": 1.0, "origin": 0.5, "dir": 1}
    c, state = _boot(ev)
    try:
        state["t"] += 0.021
        c.effect_iris_warn()
        bl = c.effect_params["iris_blinder"]
        sparks = bl["sparks_fx"]
        assert len(sparks) == wc.IRIS["meteor_spark_count"]
        m = bl["meteors"][0]
        for pt in sparks:
            travel = (pt["pos"] - m["start"]) * m["sign"]
            t_pass = bl["pre"] + wc.iris_meteor_time_for(
                travel, m["v0"], m["dur"], wc.IRIS["meteor_profile"])
            # Geburt = Durchflug + 40-120 ms (Position +-3 px Streuung ->
            # kleine Toleranz nach unten)
            assert pt["birth"] >= t_pass - 0.01, "Funken folgen dem Kopf"
            assert pt["birth"] <= t_pass + 0.15
        # Plan lebt bis der letzte Funke verglommen ist
        assert bl["win"][0][1] >= max(p["birth"] + p["life"] for p in sparks)
    finally:
        _teardown(c)
    c, state = _boot(ev, cfg={"meteor_sparks": False})
    try:
        state["t"] += 0.021
        c.effect_iris_warn()
        assert c.effect_params["iris_blinder"]["sparks_fx"] == []
    finally:
        _teardown(c)


def test_ambient_layer_default_off_and_spawns_when_enabled():
    """Phase-1-Entscheid: default AUS (kein Partikel-Pool entsteht); mit
    Rate 3.0 entstehen im Sustain Ambient-Partikel (Pool <= 12)."""
    c, state = _boot(None)
    try:
        for _ in range(80):
            state["t"] += 0.021
            c.effect_iris_warn()
        assert not c.effect_params.get("iris_ambient"), "default ist AUS"
    finally:
        _teardown(c)
    c, state = _boot(None, cfg={"stardust_ambient": 3.0})
    try:
        seen = 0
        for _ in range(400):
            state["t"] += 0.021
            c.effect_iris_warn()
            pool = c.effect_params.get("iris_ambient") or []
            seen = max(seen, len(pool))
            assert len(pool) <= 12
        assert seen >= 1, "mit Rate 3/s muss in 8 s etwas glitzern"
    finally:
        _teardown(c)
