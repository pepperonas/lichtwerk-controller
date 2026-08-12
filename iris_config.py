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
    "red_attack": (0.01, 0.20),
    "red_hold": (0.02, 0.40),
    "red_floor": (0.0, 0.40),
    "red_decay_smooth": (0.0, 1.0),
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
    # Meteor (W2)
    "meteor_v_min": (200.0, 4000.0),
    "meteor_v_max": (200.0, 4000.0),
    "meteor_trail_s": (0.02, 0.3),
    "meteor_jitter": (0.0, 0.3),
    "meteor_head_gain": (0.3, 1.0),
    "meteor_duck": (0.0, 1.0),
    "meteor_pre_dip_s": (0.05, 0.3),
    "meteor_recover_s": (0.1, 1.0),
    "flash_gain": (0.1, 0.55),
    "flash_max_ms": (20.0, 120.0),
    "max_flash_rate_hz": (0.2, 3.0),
    "meteor_max_concurrent": (1, 4),
    "meteor_head_temp": (4000.0, 10000.0),
    "meteor_tail_temp": (1500.0, 5000.0),
    "drop_ks": (0.5, 1.0),
    "drop_avg": (0.1, 1.0),
    "drop_cooldown": (2.0, 60.0),
}

DEFAULTS = {
    # Reproduzierbarkeit: None = echter Zufall; int = deterministisch je Engage
    "seed": None,

    # Rot-Puls: Aufbluehen (Anteil der Periode), Vollphase, Glut-Boden.
    # 2026-08-12 Runde 3 („zu flashy — fade-in/out subtiler"): Attack
    # 0.06->0.12 (die Bluete ist SICHTBAR, ~55-65 ms), Hold 0.16->0.09
    # (weniger Voll-Plateau, mehr Atem), Verglimmen per red_decay_smooth.
    "red_attack": 0.12,
    "red_hold": 0.09,
    "red_floor": 0.16,
    # Verglimm-Form: 0 = quadratisch (Baseline, faellt nach dem Hold sofort
    # steil), 1 = smoothstep (beginnt sanft, landet sanft — der Atem).
    "red_decay_smooth": 1.0,
    # L2: Peak folgt der gemessenen Kick-Staerke (0 = jeder Schlag gleich
    # hart = Baseline); sanfter Schlag drueckt den Peak um bis zu red_punch.
    "red_punch": 0.3,
    # L2: Freilauf-Periode als langsamer Random-Walk (±Anteil) statt
    # exaktem 0.55-s-Metronom; 0 = Baseline.
    "freerun_jitter": 0.05,
    # L2: Engage-Doppelpuls-Timing variiert je Warn-Flanke (False = immer
    # exakt 70/60/80 ms = Baseline).
    "engage_variety": True,
    # L3: Wellen-Vielfalt — Ursprung Mitte-bias gewuerfelt (nie fix),
    # Richtung beid-/einseitig, Breite/Tempo-Jitter, Funkenfenster 40-80 ms
    # statt exakt 55 ms (False = Baseline: immer Mitte, beidseitig, 55 ms).
    "wave_variety": True,

    # W2: Meteor — rasender Weiss-Kopf mit Schweif (Kind 'meteor').
    # Bewegung analytisch in LED/s (delta-time), gemalt als Line-Integral
    # (iris_render.line_coverage) — lueckenlos bei jeder Geschwindigkeit.
    "meteor_enabled": True,
    "meteor_v_min": 900.0,     # LED/s — 600 px in ~0.65 s
    "meteor_v_max": 2400.0,    # LED/s — 600 px in ~0.25 s ("Whip")
    "meteor_profile": "expo_out",   # const | expo_out | accel
    # Schweif-Zeitkonstante: e-Faltung = v*tau LEDs hinter dem Kopf
    # (schneller = laengerer Schweif, physikalisch plausibel). 0.08 s:
    # bei 2400 LED/s ~190 px e-Faltung (~2/3 Strip sichtbar), bei 900 ~70 px.
    # Der Plan-Wert 0.35 haette bei 2400 den GANZEN Strip dauerhell gelegt.
    "meteor_trail_s": 0.08,
    "meteor_jitter": 0.10,     # per-Pixel-Glut-Koernung im Schweif (5-15 %)
    "meteor_head_gain": 1.0,   # absolut (Blinder-Stromklasse), wie sparkle
    "meteor_duck": 0.35,       # Basis-Rot im Flug (Ducking statt Clipping)
    "meteor_pre_dip_s": 0.12,  # "Einatmen" 80-150 ms vor dem Start
    "meteor_recover_s": 0.25,  # Rot-Rueckkehr nach dem Impact
    "meteor_impact": True,     # Impact-Flash am Strip-Ende
    "meteor_launch": False,    # Launch-Flash (Phase-1-Entscheid: default aus)
    "flash_gain": 0.35,        # Vollflaechen-Deckel = 55-%-Stromklasse
    "flash_max_ms": 60.0,      # kurze Transienten driften nicht gruenlich
    "max_flash_rate_hz": 1.0,  # konservative Stroboskop-Bremse
    "meteor_max_concurrent": 2,
    "meteor_head_temp": 7500.0,   # Kopf minimal kuehl ("Plasma"-Spitze)
    "meteor_tail_temp": 2900.0,   # Schweif verglueht ins Warme

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
