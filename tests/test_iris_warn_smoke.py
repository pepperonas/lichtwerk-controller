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

    def getPixelColor(self, i):
        return self._px[i]

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
    # Der Import startet den ECHTEN Effekt-Loop-Thread — der malte waehrend
    # der Tests nebenlaeufig 'solid'-Frames auf den FakeStrip (gemessen:
    # 5 shows/0.3 s) und verfaelschte Frame-Captures mit ~1 % je Zugriff.
    # DAS war die Quelle aller wandernden Suite-Fehlschlaege (Golden-Hash,
    # Paar-Vergleiche). Fuer Tests wird der Loop einmalig beendet; die
    # Tests treiben effect_iris_warn direkt.
    if c.effect_thread is not None and c.effect_thread.is_alive():
        c.running = False
        c._effect_wake.set()
        c.effect_thread.join(timeout=1.0)
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

# L2/L3-Schalter + Runde-3-Atemkurve auf Baseline: red_punch aus, kein
# Freilauf-Jitter, festes Engage-Timing, Wellen immer Mitte/beidseitig/
# 55-ms-Funken, Envelope 6/16 % quadratisch — damit bleibt der
# Original-Hash der Rollback-Beweis.
BASELINE_OFF = {"red_punch": 0.0, "freerun_jitter": 0.0,
                "engage_variety": False, "wave_variety": False,
                "red_attack": 0.06, "red_hold": 0.16,
                "red_decay_smooth": 0.0}

def _golden_run(extra_cfg):
    import hashlib
    state = {"t": 100.0}
    c = fresh()
    c.iris_clock = lambda: state["t"]
    cfg = {"seed": 1234}
    cfg.update(extra_cfg)
    wc.apply_iris_config(cfg)
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
        return h.hexdigest()
    finally:
        wc.apply_iris_config(None)
        if hasattr(c, "iris_clock"):
            del c.iris_clock


def test_golden_frames_with_seed_and_fake_clock():
    """L1-Waechter (Phase 3): Seed + injizierte Fake-Uhr => bitgenau
    reproduzierbare Frames. Mit den L2-Schaltern AUS ist der Hash der
    Verhaltens-Fingerabdruck der BASELINE (Tag iris-baseline-20260812) —
    der Beweis, dass der Rollback-Pfad intakt bleibt. JEDE unbeabsichtigte
    Aenderung (auch durch kuenftige Feature-Schalter im AUS-Zustand)
    aendert ihn und faellt hier auf."""
    assert _golden_run(BASELINE_OFF) == GOLDEN_FRAME_HASH


def test_golden_defaults_are_deterministic():
    """L2-Defaults (Schalter AN): zwei Laeufe mit demselben Seed sind
    bit-identisch UND unterscheiden sich von der Baseline (die Schalter
    tun nachweislich etwas)."""
    a = _golden_run({})
    b = _golden_run({})
    assert a == b
    assert a != GOLDEN_FRAME_HASH


def _lit_pixels(strip):
    return [i for i, px in enumerate(strip._px) if px]


def test_sweep_variant_travels_along_the_strip():
    """L6: der Sweep ist BEWEGUNG — der weisse Kopf wandert waehrend des
    Fensters von der Startposition in Pfeilrichtung."""
    state = {"t": 100.0}
    # sweep_span (380 LED) ist fuer den echten 600er dimensioniert — auf dem
    # 60-px-Default-Strip liefe der Kopf nach 2 Frames rechts raus (lit=0).
    # Der Test faehrt darum in ECHTER Geometrie.
    c = fresh(FakeStrip(600))
    c.iris_clock = lambda: state["t"]
    wc.apply_iris_config({"seed": 5})
    try:
        for _ in range(12):
            state["t"] += 0.021
            c.effect_iris_warn()
        c.effect_params.setdefault("iris_events", []).append(
            {"kind": "sweep", "gap": 0.16, "n": 1, "dur": 0.6,
             "intensity": 1.0, "density": 1.0, "origin": 0.2, "dir": 1})
        centres = []
        for _ in range(28):
            state["t"] += 0.021
            c.effect_iris_warn()
            lit = _lit_pixels(c.strip)
            if lit:
                centres.append(sum(lit) / len(lit))
        assert len(centres) >= 10
        assert centres[-1] - centres[0] > 60, \
            f"Sweep muss wandern ({centres[0]:.0f} -> {centres[-1]:.0f})"
    finally:
        wc.apply_iris_config(None)
        del c.iris_clock


def test_shimmer_variant_rerolls_pixels_each_frame():
    """L6: Shimmer flirrt — aufeinanderfolgende Frames wuerfeln andere Pixel."""
    state = {"t": 200.0}
    c = fresh()
    c.iris_clock = lambda: state["t"]
    wc.apply_iris_config({"seed": 6})
    try:
        for _ in range(12):
            state["t"] += 0.021
            c.effect_iris_warn()
        c.effect_params.setdefault("iris_events", []).append(
            {"kind": "shimmer", "gap": 0.16, "n": 1, "dur": 0.6,
             "intensity": 1.0, "density": 1.0, "origin": 0.5, "dir": 1})
        frames = []
        for _ in range(20):
            state["t"] += 0.021
            c.effect_iris_warn()
            lit = frozenset(_lit_pixels(c.strip))
            if lit:
                frames.append(lit)
        assert len(frames) >= 8
        distinct = len(set(frames))
        assert distinct >= len(frames) * 0.6, "Shimmer muss je Frame neu wuerfeln"
    finally:
        wc.apply_iris_config(None)
        del c.iris_clock


def test_red_punch_peak_and_envelope_scaling():
    """L2 (pure): harter Kick = voller Peak, sanfter Kick drueckt um bis zu
    `punch`; die Skalierung laesst den Glut-Boden UNANGETASTET."""
    assert wc.iris_red_punch_peak(1.0, 0.3) == 1.0
    assert abs(wc.iris_red_punch_peak(0.0, 0.3) - 0.7) < 1e-9
    assert wc.iris_red_punch_peak(0.5, 0.0) == 1.0          # Baseline
    assert wc.iris_red_punch_peak(7.0, 0.3) == 1.0          # ks geklemmt
    floor = 0.16
    # Spitze der Huellkurve landet auf dem Peak, der Boden bleibt der Boden
    assert abs(wc.iris_scale_envelope(1.0, 0.7, floor) - 0.7) < 1e-9
    assert abs(wc.iris_scale_envelope(floor, 0.7, floor) - floor) < 1e-9
    assert wc.iris_scale_envelope(0.5, 1.0, floor) == 0.5   # Peak 1.0 = no-op


def test_freerun_walk_stays_in_band_and_drifts():
    """L2 (pure): der Random-Walk bleibt IMMER in ±jitter und bewegt sich."""
    import random as _r
    rng = _r.Random(3)
    f, seen = 1.0, set()
    for _ in range(500):
        f = wc.iris_freerun_walk(f, 0.05, rng.uniform(-1.0, 1.0))
        assert 0.95 <= f <= 1.05
        seen.add(round(f, 4))
    assert len(seen) > 50, "Walk muss wandern, nicht kleben"
    assert wc.iris_freerun_walk(1.3, 0.0, 1.0) == 1.0       # jitter 0 = Baseline


def test_engage_window_variety_and_baseline():
    """L2 (pure): Baseline exakt (0.07, 0.13); Variety wuerfelt, bleibt aber
    immer in der Engage-Phase (zweiter Puls >= ~45 ms vor 0.21 s)."""
    import random as _r
    assert wc.iris_engage_window(_r.Random(1), False) == (0.07, 0.13)
    wins = {wc.iris_engage_window(_r.Random(s), True) for s in range(200)}
    assert len(wins) > 100, "Variety muss variieren"
    for a, b in wins:
        assert 0.03 <= a < b <= 0.20
        assert 0.04 <= b - a <= 0.08


def test_wave_spawn_variety_and_legacy_baseline():
    """L3 (pure): Baseline = Legacy-Dict {'s'} (Malpfad-Fallbacks = alte
    Welle); Variety wuerfelt Ursprung (nie an der Kante, nie fix),
    Richtung (beid-/einseitig gemischt) und Tempo/Breite im Band."""
    import random as _r
    assert wc.iris_wave_spawn(_r.Random(1), 0.8, False) == {"s": 0.8}
    rng = _r.Random(7)
    dirs, origins = set(), set()
    for _ in range(300):
        w = wc.iris_wave_spawn(rng, 0.8, True)
        assert 0.08 <= w["of"] <= 0.92
        assert w["dir"] in (-1, 0, 1)
        base_v, base_w = 520.0 + 780.0 * 0.8, 12.0 + 24.0 * 0.8
        assert base_v * 0.85 - 1e-6 <= w["v"] <= base_v * 1.2 + 1e-6
        assert base_w * 0.8 - 1e-6 <= w["width"] <= base_w * 1.25 + 1e-6
        dirs.add(w["dir"])
        origins.add(round(w["of"], 3))
    assert dirs == {-1, 0, 1}, "alle Richtungen muessen vorkommen"
    assert len(origins) > 200, "Ursprung darf nicht fix sein"


def test_wave_reach_and_speed_legacy_and_directional():
    """L3 (pure): Legacy-Welle stirbt exakt bei n/2+60 (alte Prune-Formel);
    einseitige Wellen leben so lange, wie Strip in ihrer Richtung liegt."""
    legacy = {"s": 0.5}
    assert wc.iris_wave_reach(legacy, 600) == 360.0            # n/2 + 60
    assert wc.iris_wave_speed(legacy) == 520.0 + 780.0 * 0.5
    assert wc.iris_wave_reach({"s": 1, "of": 0.2, "dir": 1}, 600) == 540.0
    assert wc.iris_wave_reach({"s": 1, "of": 0.2, "dir": -1}, 600) == 180.0
    assert wc.iris_wave_reach({"s": 1, "of": 0.2, "dir": 0}, 600) == 540.0
    assert wc.iris_wave_speed({"s": 1, "v": 777.0}) == 777.0


def test_spark_window_baseline_and_jitter():
    import random as _r
    assert wc.iris_spark_window(_r.Random(1), False) == 0.055
    vals = {wc.iris_spark_window(_r.Random(s), True) for s in range(100)}
    assert all(0.04 <= v <= 0.08 for v in vals)
    assert len(vals) > 50


def test_one_sided_wave_paints_only_its_arm():
    """L3 (Verhalten): eine dir=+1-Welle bei of=0.2 laesst die linke
    Strip-Seite unangetastet. Die Basis atmet selbst (red_env + Glut) —
    der Wellen-Beitrag ist darum die DIFFERENZ zweier deterministischer
    Laeufe (gleicher Seed, gleiche Fake-Uhr), einmal mit, einmal ohne."""
    def run(with_wave):
        state = {"t": 100.0}
        c = fresh(FakeStrip(600))
        c.iris_clock = lambda: state["t"]
        wc.apply_iris_config({"seed": 9})
        try:
            frames = []
            for _ in range(12):
                state["t"] += 0.021
                c.effect_iris_warn()
            if with_wave:
                # born in EFFEKT-relativer Zeit (t = uhr - iris_t0) — eine
                # absolute Zeit waere ein unsichtbarer Zombie (Doktrin).
                rel_now = state["t"] - c.effect_params["iris_t0"]
                c.effect_params["iris_waves"] = [
                    {"born": rel_now, "s": 0.9, "of": 0.2, "dir": 1,
                     "v": 900.0, "width": 20.0}]
            for _ in range(4):
                state["t"] += 0.021
                c.effect_iris_warn()
                frames.append(list(c.strip._px))
            return frames
        finally:
            wc.apply_iris_config(None)
            del c.iris_clock

    plain, waved = run(False), run(True)
    changed = sorted({i for a, b in zip(plain, waved)
                      for i in range(600) if a[i] != b[i]})
    assert changed, "die Welle muss sichtbar malen"
    assert min(changed) >= int(0.2 * 600) - 1, \
        f"links vom Ursprung darf nichts passieren (min={min(changed)})"
    assert max(changed) > int(0.2 * 600) + 20, "rechter Arm muss laufen"


def test_red_envelope_default_breathes_softly():
    """Runde 3 (2026-08-12, Nutzer: „zu flashy — fade-in/out subtiler,
    natuerlicher"): die Bluete ist SICHTBAR (12 % der Periode), das Voll-
    Plateau kuerzer (9 %), und das Verglimmen STARTET sanft (smoothstep:
    Steigung 0 direkt nach dem Hold — kein Absturz) und landet sanft auf
    dem Glut-Boden. Getestet gegen die ECHTE Funktion, kein Mirror."""
    wc.apply_iris_config(None)
    env = wc.iris_red_envelope
    assert abs(env(0.0) - 0.16) < 1e-9, "startet am Glut-Boden"
    assert env(0.06) < 0.9, "Attack ist laenger — bei 6 % noch mitten in der Bluete"
    assert env(0.12) == 1.0 and env(0.20) == 1.0     # Hold 0.12..0.21
    assert env(0.30) > 0.93, "Verglimmen beginnt SANFT (kein Quadrat-Absturz)"
    samples = [env(u) for u in (0.3, 0.45, 0.6, 0.8, 0.99)]
    assert samples == sorted(samples, reverse=True)
    for a, b in zip(samples, samples[1:]):
        assert 0 < a - b < 0.4, "weiches Verglimmen, keine Spruenge"
    assert 0.15 < env(0.999) < 0.22, "Boden 16 % — nie tot"


def test_red_envelope_baseline_config_restores_the_old_curve():
    """Rollback-Pfad: mit den Baseline-Werten (6/16 %, decay_smooth 0) ist
    die Kurve exakt das alte quadratische Verglimmen."""
    wc.apply_iris_config({"red_attack": 0.06, "red_hold": 0.16,
                          "red_decay_smooth": 0.0})
    try:
        env = wc.iris_red_envelope
        assert env(0.06) == 1.0 and env(0.21) == 1.0
        f = (0.61 - 0.22) / 0.78
        g = 1.0 - f
        assert abs(env(0.61) - (0.16 + 0.84 * g * g)) < 1e-9
        mean = sum(env(i / 1000.0) for i in range(1000)) / 1000.0
        assert 0.42 < mean < 0.62      # das alte Energie-Budget
    finally:
        wc.apply_iris_config(None)


def test_white_budget_caps_dense_picker_events_but_not_approved_forms():
    """Weiss-Budget (2026-08-13, Nutzerbefund 'zu viele weisse LEDs ->
    gelblich'): density-skalierte Picker-Events (burst/echo bis x1,5 =
    bis 39 Cluster ~195 LEDs) rissen ueber die erprobte Sparse-Klasse
    hinaus — dort sackt die 5-V-Schiene und Weiss kippt gelb. Der Waechter
    kappt auf die abgenommene Klasse (26 Cluster / 130 LEDs); die
    Detektor-Formen (density 1.0, 16-26 Cluster) bleiben unangetastet
    (zusaetzlich vom Golden-Frame-Test bewiesen)."""
    import iris_config
    c = fresh()
    run_frames(c, 4)
    # burst mit maximaler Dichte: ohne Cap waeren es int(26*1.5)=39 Cluster
    c.effect_params.setdefault('iris_events', []).append(
        {'kind': 'burst', 'density': 1.5, 'intensity': 1.0})
    run_frames(c, 2)
    bl = c.effect_params.get('iris_blinder')
    assert bl and bl.get('spots'), "burst muss einen Sparkle-Plan anlegen"
    leds = len(bl['spots'][0])
    assert leds <= 130, f"Weiss-Budget gerissen: {leds} LEDs (> 130)"
    # Cluster-Zaehlung indirekt: 26 Cluster x max 5 LEDs = 130; ein
    # ungekappter 39er-Plan laege im Mittel bei ~133 und wuerde die
    # Grenze regelmaessig reissen — hier zusaetzlich der Erwartungsbereich.
    assert leds >= 26, "Plan darf nicht leer/degeneriert sein"
    run_frames(c, 40)
    # echo mit maximaler Dichte ebenso
    c.effect_params.setdefault('iris_events', []).append(
        {'kind': 'echo', 'density': 1.5, 'gap_ms': 150})
    run_frames(c, 2)
    bl2 = c.effect_params.get('iris_blinder')
    assert bl2 and len(bl2['spots'][0]) <= 130
    # Waechter aus (white_max_spots/px = 0) = Vorverhalten: der dichte
    # burst darf dann GROESSER ausfallen (Rollback-Pfad bleibt beweisbar).
    old_spots, old_px = wc.IRIS['white_max_spots'], wc.IRIS['white_max_px']
    try:
        wc.IRIS['white_max_spots'] = 0
        wc.IRIS['white_max_px'] = 0
        run_frames(c, 40)
        c.effect_params.setdefault('iris_events', []).append(
            {'kind': 'burst', 'density': 1.5, 'intensity': 1.0})
        run_frames(c, 2)
        bl3 = c.effect_params.get('iris_blinder')
        assert bl3 and len(bl3['spots'][0]) > 100, \
            "ohne Waechter muss der 39-Cluster-Plan wieder moeglich sein"
    finally:
        wc.IRIS['white_max_spots'] = old_spots
        wc.IRIS['white_max_px'] = old_px
