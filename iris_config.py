"""Zentrale Konfiguration des Iris-Modus (Phase 3, Schritt L1).

Alle wirkmächtigen Iris-Parameter leben hier als Defaults und sind per
`config.json`-Sektion `"iris"` überschreibbar. Die Defaults sind exakt die
zuvor hart codierten Werte (Baseline-Tag `iris-baseline-20260812`) — mit
leerer Sektion ist das Verhalten bit-identisch (Golden-Frame-Test in
tests/test_iris_warn_smoke.py sichert das ab).

Jeder Wert wird beim Laden auf seinen Range geklemmt: eine verschriebene
config.json darf den Effekt verstimmen, aber nie crashen oder ins
Unsinnige treiben (Strom!).

`seed` (Default None) macht alle Zufallsanteile des Effekts reproduzierbar:
der Effekt zieht seine Zufaelle aus einer eigenen random.Random-Instanz,
die je Engage frisch aus dem Seed erzeugt wird (Zombie-Doktrin: Zustand
resettet je Warn-Flanke; mit festem Seed ist damit jedes Engage exakt
wiederholbar — die Grundlage der Offline-Verifikation).
"""

# (min, max) je numerischem Parameter — Klemm-Grenzen, nicht Geschmack.
RANGES = {
    # Rot-Puls (Atem-Huellkurve)
    "red_attack": (0.01, 0.15),
    "red_hold": (0.02, 0.40),
    "red_floor": (0.0, 0.40),
    "red_punch": (0.0, 0.5),
    "freerun_jitter": (0.0, 0.15),
    # Takt
    "period_freerun": (0.30, 1.50),
    "period_min": (0.20, 0.60),
    "period_max": (0.60, 2.00),
    "period_ema": (0.05, 0.60),
    "snap_refractory": (0.10, 0.50),
    "kick_stale": (0.8, 4.0),
    # Wander-Glut
    "glow_min": (0.10, 0.90),
    "glow_l1": (40.0, 600.0),
    "glow_l2": (40.0, 600.0),
    "glow_v1": (-40.0, 40.0),
    "glow_v2": (-40.0, 40.0),
    # Schattenzonen
    "shadow_count": (0, 10),
    "shadow_w_min": (6, 300),
    "shadow_w_max": (6, 300),
    "shadow_depth_min": (0.0, 0.95),
    "shadow_depth_max": (0.0, 0.95),
    "shadow_life_min": (1.0, 30.0),
    "shadow_life_max": (1.0, 60.0),
    "shadow_vel_max": (0.0, 40.0),
    "shadow_ramp": (0.1, 5.0),
    # Sparkle-Blinder (Weiss-Events)
    "blinder_gain": (0.1, 1.0),
    "sparkle_r": (0, 255), "sparkle_g": (0, 255), "sparkle_b": (0, 255),
    "sparkle_decay": (0.10, 0.80),
    "double_pulse": (0.05, 0.30),
    "double_gain2": (0.3, 1.0),
    "double_spots": (4, 60),
    "roll_pulse": (0.04, 0.25),
    "roll_decay_per": (0.0, 0.3),
    "roll_gain_floor": (0.2, 1.0),
    "roll_spots": (4, 60),
    "accent_pulse": (0.05, 0.40),
    "accent_spots": (4, 80),
    "drop_spots": (4, 80),
    "sweep_width": (4, 60),
    "sweep_span": (60, 600),
    "shimmer_px": (6, 80),
    "shimmer_gain": (0.1, 1.0),
    "variant_dur_min": (0.06, 0.5),
    "variant_dur_max": (0.2, 1.5),
    "drop_ks": (0.5, 1.0),
    "drop_avg": (0.1, 1.0),
    "drop_cooldown": (2.0, 60.0),
}

DEFAULTS = {
    # Reproduzierbarkeit: None = echter Zufall; int = deterministisch je Engage
    "seed": None,

    # Rot-Puls: Aufbluehen (Anteil der Periode), Vollphase, Glut-Boden
    "red_attack": 0.06,
    "red_hold": 0.16,
    "red_floor": 0.16,
    # L2: Peak folgt der gemessenen Kick-Staerke (0 = jeder Schlag gleich
    # hart = Baseline); sanfter Schlag drueckt den Peak um bis zu red_punch.
    "red_punch": 0.3,
    # L2: Freilauf-Periode als langsamer Random-Walk (±Anteil) statt
    # exaktem 0.55-s-Metronom; 0 = Baseline.
    "freerun_jitter": 0.05,
    # L2: Engage-Doppelpuls-Timing variiert je Warn-Flanke (False = immer
    # exakt 70/60/80 ms = Baseline).
    "engage_variety": True,

    # Takt: Freilauf-Periode + Klemmen + Tempo-Lock-Glaettung
    "period_freerun": 0.55,
    "period_min": 0.30,
    "period_max": 1.20,
    "period_ema": 0.25,
    "snap_refractory": 0.24,
    "kick_stale": 1.6,

    # Wander-Glut: 2 inkommensurable Sinuswellen (LED-Wellenlaengen, Drift LED/s)
    "glow_min": 0.45,
    "glow_l1": 170.0,
    "glow_l2": 290.0,
    "glow_v1": 14.0,
    "glow_v2": -9.0,

    # Schattenzonen: 50-150 cm dunkle Wander-Taschen
    "shadow_count": 4,
    "shadow_w_min": 30,
    "shadow_w_max": 90,
    "shadow_depth_min": 0.55,
    "shadow_depth_max": 0.85,
    "shadow_life_min": 4.0,
    "shadow_life_max": 9.0,
    "shadow_vel_max": 8.0,
    "shadow_ramp": 1.0,

    # Sparkle-Blinder (Weiss = Interpunktion)
    "blinder_gain": 1.0,
    "sparkle_r": 255, "sparkle_g": 205, "sparkle_b": 150,
    "sparkle_decay": 0.28,
    "double_pulse": 0.10,
    "double_gain2": 0.85,
    "double_spots": 22,
    "roll_pulse": 0.09,
    "roll_decay_per": 0.14,
    "roll_gain_floor": 0.5,
    "roll_spots": 16,
    "accent_pulse": 0.16,
    "accent_spots": 26,
    "drop_spots": 24,

    # Weiss-Varianten (L6): Sweep = rasender Lichtstreif, Shimmer = Flirren
    "sweep_width": 14,      # Gauss-Halbbreite des Sweep-Kopfs (LEDs)
    "sweep_span": 380,      # Laufstrecke des Sweeps (LEDs)
    "shimmer_px": 30,       # Basis-Anzahl flirrender Pixel je Frame
    "shimmer_gain": 0.5,    # Shimmer ist Flaechen-Textur, kein Blinder
    "variant_dur_min": 0.08,   # Klemmen fuer Payload-Dauern (Sicherheit)
    "variant_dur_max": 1.2,
    "drop_ks": 0.9,
    "drop_avg": 0.5,
    "drop_cooldown": 8.0,
}


def load(section):
    """DEFAULTS + Overrides aus der config.json-Sektion, Werte range-geklemmt.

    Unbekannte Schluessel werden ignoriert (vorwaertskompatibel), falsche
    Typen fallen still auf den Default zurueck — eine kaputte config.json
    darf den Strip nie lahmlegen.
    """
    cfg = dict(DEFAULTS)
    if isinstance(section, dict):
        for key, val in section.items():
            if key not in cfg:
                continue
            if key == "seed":
                cfg["seed"] = int(val) if isinstance(val, (int, float)) else None
                continue
            try:
                val = type(DEFAULTS[key])(val)
            except (TypeError, ValueError):
                continue
            if key in RANGES:
                lo, hi = RANGES[key]
                val = max(lo, min(hi, val))
            cfg[key] = val
    return cfg
