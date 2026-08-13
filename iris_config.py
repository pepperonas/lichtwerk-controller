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
    # Tempo-Skalierung (Tempo-Brief 2026-08-13; docs/tempo-scaling-plan.md)
    "tempo_ref": (100.0, 140.0),
    "tempo_exp": (0.3, 1.0),
    "tempo_attack_exp": (0.5, 2.0),
    "tempo_ramp_s": (0.5, 5.0),
    "tempo_stale_s": (1.0, 10.0),
    "tempo_fallback_s": (5.0, 60.0),
    "tempo_jump_confirm": (1, 6),
    "thin_on_bpm": (130.0, 190.0),
    "thin_off_bpm": (125.0, 185.0),
    "thin_damp": (0.2, 1.0),
    "thin_strong_pct": (0.5, 0.95),
    "thin_dwell_s": (1.0, 15.0),
    "move_tau_s": (0.5, 8.0),
    "move_calm_stretch": (1.0, 2.5),
    "move_peak_min": (0.5, 1.0),
    "zone70": (0.5, 1.6),
    "zone100": (0.5, 1.6),
    "zone140": (0.5, 1.6),
    "zone170": (0.5, 1.6),
    # Organisches Rot-Profil (Rot-Brief 2026-08-13; docs/red-organic-plan.md)
    "organic_attack_ms": (5.0, 40.0),
    "organic_decay_ms": (80.0, 800.0),
    "organic_sustain": (0.0, 0.7),
    "organic_tail_ms": (100.0, 900.0),
    "organic_vel_gamma": (0.3, 2.0),
    "organic_vel_floor": (0.0, 0.6),
    "organic_pulse_max": (2, 10),
    "organic_spread_ms": (60.0, 600.0),
    "organic_knee": (0.5, 0.95),
    "organic_bed_min": (0.0, 0.3),
    "organic_bed_max": (0.05, 0.4),
    "organic_bass_gain": (0.0, 1.0),
    "organic_bass_up_s": (0.03, 1.0),
    "organic_bass_down_s": (0.1, 3.0),
    "organic_hue_drift": (0.0, 4.0),
    "organic_g_max": (60, 160),
    "organic_b_max": (20, 120),
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
    "white_max_spots": (0, 80),
    "white_max_px": (0, 400),
    "variant_dur_min": (0.06, 0.5),
    "variant_dur_max": (0.2, 1.5),
    # Meteor (W2)
    "meteor_v_min": (200.0, 4000.0),
    "meteor_v_max": (200.0, 4000.0),
    "meteor_trail_s": (0.02, 0.3),
    "meteor_tail_cut": (0.02, 0.3),
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
    # Stardust (W3)
    "stardust_max_particles": (20, 300),
    "stardust_life_min_ms": (50.0, 500.0),
    "stardust_life_max_ms": (20.0, 500.0),
    "stardust_powerlaw_k": (1.0, 5.0),
    "stardust_min_dist": (1.0, 20.0),
    "stardust_temp_min": (2500.0, 10000.0),
    "stardust_temp_max": (2500.0, 10000.0),
    "stardust_attack": (0.1, 0.5),
    "stardust_gain": (0.3, 1.0),
    "stardust_ambient": (0.0, 3.0),
    "meteor_spark_count": (4, 80),
    "drop_ks": (0.5, 1.0),
    "drop_avg": (0.1, 1.0),
    "drop_cooldown": (2.0, 60.0),
}

DEFAULTS = {
    # Reproduzierbarkeit: None = echter Zufall; int = deterministisch je Engage
    "seed": None,

    # ── Organisches Rot-Profil (Rot-Brief 2026-08-13) ────────────────────
    # "classic" = bit-identische Baseline (Golden-Frame-Hash beweist es);
    # "organic" = Velocity + ADSR-Stack + Farbrampe + Bass-Druckwelle +
    # Dithering. Live umschaltbar via POST /api/iris/profile. Jeder andere
    # Wert faellt im Renderer auf classic zurueck (Tippfehler-sicher).
    "red_profile": "classic",

    # ── Tempo-Skalierung (Tempo-Brief 2026-08-13) ────────────────────────
    # "fixed" = Code-Default = exakt der abgenommene organic-Stand (der
    # 120-BPM-Anker-Test pinnt Bit-Identitaet); "tempo" = Beat-Zeitbasis
    # F=(tempo_ref/bpm_eff)^tempo_exp + Zonen + Bewegungsrate. Wirkt NUR
    # im organic-Profil; classic bleibt unberuehrt. Live umschaltbar via
    # POST /api/iris/profile {"timing": ...}.
    "red_timing": "fixed",
    "tempo_ref": 120.0,        # der Anker, an dem sich nichts aendern darf
    "tempo_exp": 0.7,          # gedaempfte Kurve (1.0 = proportional = flackert)
    "tempo_attack_exp": 1.3,   # Attack skaliert staerker (langsam weicher)
    "tempo_ramp_s": 1.5,       # Tempo-Uebernahme als Rampe, nie als Sprung
    "tempo_stale_s": 3.0,      # ohne Kicks: Wert gilt als veraltet
    "tempo_fallback_s": 15.0,  # danach sanfte Rueckfuehrung auf tempo_ref
    "tempo_jump_confirm": 3,   # Oktav-/Sprung-Korrektur erst nach N Kicks
    "thin_on_bpm": 150.0,      # Ausduennen an (Hysterese-Paar + Verweildauer)
    "thin_off_bpm": 145.0,
    "thin_damp": 0.45,         # Zwischenschlag-Peak-Faktor
    "thin_strong_pct": 0.70,   # >= P70 der letzten Kicks spielt trotzdem voll
    "thin_dwell_s": 4.0,
    "move_tau_s": 2.0,         # Bewegungsrate traege (kein Flattern)
    "move_calm_stretch": 1.5,  # Breakdown: Decay/Tail bis x1.5
    "move_peak_min": 0.75,     # Breakdown: Impuls-Peak bis x0.75
    "zone70": 1.35,            # getragen — Impulse gehen ins Atmen ueber
    "zone100": 1.12,           # groovig, weiche Kanten
    "zone140": 0.88,           # straffer Puls (115-135 bleibt per Anker 1.0)
    "zone170": 0.75,           # + Ausduennen statt Beschleunigen
    "organic_attack_ms": 14.0,    # geformter Attack (Brief: 5-20 ms)
    "organic_decay_ms": 240.0,    # Anfangs-Decay-Basis (x Velocity-Faktor)
    "organic_sustain": 0.30,      # Sustain-Anteil rel. Peak
    "organic_tail_ms": 340.0,     # Sustain-Schwanz -> Bett (Brief: 100-400)
    "organic_vel_gamma": 0.65,    # perzeptuelle power curve Velocity->Peak
    "organic_vel_floor": 0.18,    # zartester Schlag bleibt sichtbar
    "organic_pulse_max": 6,       # Stapel-Kappe (Allokations-Deckel)
    "organic_spread_ms": 180.0,   # Bloom-Expansion bis Vollabdeckung
    "organic_knee": 0.80,         # soft-knee-Beginn der Summensaettigung
    "organic_bed_min": 0.06,      # Glut-Bett im Breakdown
    "organic_bed_max": 0.20,      # Glut-Bett im Groove
    "organic_bass_gain": 0.45,    # Druckwellen-Anteil der Bassline
    "organic_bass_up_s": 0.12,    # Bass-Attack (traege genug gegen Pumpen)
    "organic_bass_down_s": 0.45,  # Bass-Release
    "organic_hue_drift": 1.5,     # Gradient-Drift-Amplitude (Minuten-Periode)
    "organic_dither": True,       # temporales Dithering (Ursache 7)
    "organic_g_max": 140,         # Nie-Weiss-Kappe Gruen (Weiss = gesperrt)
    "organic_b_max": 90,          # Nie-Weiss-Kappe Blau

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
    # (schneller = laengerer Schweif, physikalisch plausibel).
    # 2026-08-12 („Schweif kuerzer, faerbt gruenlich"): 0.08 -> 0.035 —
    # bei 0.08 deckte der Schweif bei 2400 LED/s ~750 px ab und der
    # Gamma-Encode hielt das ferne Ende auf ~17 % Duty: genau der
    # flaechige Niedrig-Duty-Teppich, der laut Feldbefund 2026-08-10
    # gelbgruen kippt (Spannungssack + fast-gleiche niedrige Kanaele).
    # Jetzt: sichtbarer Schweif ~73 px (900) bis ~193 px (2400).
    "meteor_trail_s": 0.035,
    # Schweif-Schnitt: unterhalb dieses linearen Restlichts endet der
    # Schweif AUF NULL (normalisiert) statt als Schleier weiterzuglimmen —
    # sichtbare Laenge = ln(1/cut) e-Faltungen (~2.3 bei 0.10).
    "meteor_tail_cut": 0.10,
    "meteor_jitter": 0.10,     # per-Pixel-Glut-Koernung im Schweif (5-15 %)
    "meteor_head_gain": 1.0,   # absolut (Blinder-Stromklasse), wie sparkle
    # 2026-08-12 („weiss nur wenn rot aus"): Flug auf SCHWARZ — der Pre-Dip
    # wird zum Fade-to-Black-Auftakt, Recover blendet das Rot zurueck.
    # > 0 = das alte Ducking (Rot glimmt unter dem Meteor weiter).
    "meteor_duck": 0.0,
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

    # W3: Stardust — Sternenstaub-Burst (Kind 'stardust') + Funkenflug.
    # Partikel werden beim Intake VORGENERIERT (Blue-Noise-Positionen,
    # Potenzgesetz-Helligkeit, Farbtemperatur-Streuung) — der Malpfad ist
    # eine Schleife ueber lebende Partikel, keine Allokation im Frame.
    "stardust_enabled": True,
    "stardust_max_particles": 120,
    "stardust_life_min_ms": 60.0,
    "stardust_life_max_ms": 250.0,
    "stardust_powerlaw_k": 2.5,    # viele schwache, wenige sehr helle
    "stardust_min_dist": 4.0,      # Poisson-Disk: nie verklumpt
    "stardust_temp_min": 4000.0,   # Diamant-Streuung; kuehle Toene nur auf
    "stardust_temp_max": 8000.0,   # hellen EINZEL-Partikeln (Blau-Die-Physik)
    "stardust_attack": 0.25,       # Attack-Anteil des Lebens (nie hart an)
    "stardust_gain": 1.0,          # absolut (Blinder-Stromklasse)
    # Ambient-Dauer-Glitzer in Sparkles/s — Phase-1-Entscheid: default AUS.
    "stardust_ambient": 0.0,
    # Funkenflug: Sparkles entlang der Meteor-Bahn, kurz verzoegert.
    "meteor_sparks": True,
    "meteor_spark_count": 26,

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

    # Weiss-Budget (2026-08-13): harte Sparse-Stromklasse fuer ALLE
    # Weiss-Effekte. Die Detektor-Formen (16-26 Cluster) sind die erprobte
    # Klasse, in der Warmweiss ehrlich bleibt; density-skalierte Picker-
    # Events (burst/echo bis x1,5) rissen darueber hinaus und kippten
    # GELBLICH (5-V-Sack, blaue Die verhungert). 0 = Waechter aus
    # (Rollback = exakt das Vorverhalten).
    "white_max_spots": 26,  # max Cluster je Sparkle-Plan (= accent, groesste
                            # abgenommene Form — Bestand bleibt bit-identisch)
    "white_max_px": 130,    # absolute LED-Obergrenze je Weiss-Plan/Frame
                            # (26 Cluster x max 5 = erlaubter Bestands-Worst-Case)

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
