#!/usr/bin/env python3

import os
import threading
import time
import json
import signal
import sys
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
try:
    from pio_strip import MultiStrip, PixelStrip, Color  # Pi 5: ws2812-pio /dev/leds0
except ImportError:
    from rpi_ws281x import PixelStrip, Color
import iris_wash
import iris_render
import math
import random

# Strip-Warn pacing. The WS2812 shift-out for 600 LEDs is 18 ms (55.6 fps
# ceiling); a 1.8 s breathe ramp is perfectly smooth at 30 fps, and the extra
# headroom keeps us from ever writing into an in-flight DMA transfer.
WASH_FPS = 30.0
WASH_FRAME_S = 1.0 / WASH_FPS

import iris_config

# Zentrale Iris-Konfiguration (Phase 3 / L1): Defaults = Baseline-Werte,
# ueberschreibbar per config.json-Sektion "iris" (Ranges geklemmt).
IRIS = iris_config.load(None)


def apply_iris_config(section):
    """config.json-Sektion "iris" anwenden (Controller-Init)."""
    global IRIS
    IRIS = iris_config.load(section)


def iris_glow_factor(x, t):
    """Raeumliche Glut-Modulation des Rots (Nutzerwunsch 2026-08-11).

    'Rot soll nicht ueberall gleich intensiv leuchten — die intensiven
    Bereiche sollen wandern.' Die Strip-Uebersetzung der Glut-Blobs der
    dB-Analyse-Seite: zwei langsame Sinuswellen mit inkommensurablen
    Wellenlaengen driften gegenlaeufig; ihre Summe formt helle Zonen, die
    ohne sichtbare Schleife den Streifen entlangwandern. Multipliziert
    sich mit der Atem-Huellkurve (iris_red_envelope): Rot atmet zeitlich
    UND wandert raeumlich — Glut, in der es arbeitet.
    """
    l1, l2 = IRIS['glow_l1'], IRIS['glow_l2']
    v = (0.5
         + 0.25 * math.sin(x * (2 * math.pi / l1)
                           + t * (2 * math.pi * IRIS['glow_v1'] / l1))
         + 0.25 * math.sin(x * (2 * math.pi / l2)
                           + t * (2 * math.pi * IRIS['glow_v2'] / l2)))
    gmin = IRIS['glow_min']
    return gmin + (1.0 - gmin) * max(0.0, min(1.0, v))


# ── Schattenzonen (Nutzerwunsch 2026-08-11: "Glut sieht man nicht stark
# genug — Bereiche von ca. 50-150 cm weniger stark erhellen, dynamisch und
# abwechselnd"). Bei 60 LED/m sind das 30-90 LEDs je Zone. Jede Zone hat ein
# weiches Gauss-Profil (keine harten Kanten), dimmt ihr Zentrum auf ~15-45 %,
# blendet ueber ihr Leben ein/aus und driftet langsam — der Nachschub spawnt
# an zufaelliger Position: nie uniform, nie wiederholend, nie tot.
def iris_shadow_profile(dist, width):
    """Weiches Zonen-Profil: 1 im Zentrum, Gauss-Abfall — Halbwertsbreite
    entspricht der Zonenbreite, keine harte Kante."""
    sigma = width / 2.355     # FWHM -> sigma
    return math.exp(-(dist * dist) / (2.0 * sigma * sigma))


def iris_shadow_alpha(age, life, ramp=None):
    """Trapez ueber die Lebenszeit: einblenden, halten, ausblenden."""
    if ramp is None:
        ramp = IRIS['shadow_ramp']
    if age <= 0 or age >= life:
        return 0.0
    return max(0.0, min(1.0, min(age / ramp, (life - age) / ramp)))


def iris_shadow_field(x, pockets, now):
    """Multiplikative Abdunklung aller Zonen an Position x (0..1)."""
    f = 1.0
    for pk in pockets:
        age = now - pk['born']
        a = iris_shadow_alpha(age, pk['life'])
        if a <= 0.0:
            continue
        pos = pk['pos'] + pk['vel'] * age
        f *= 1.0 - pk['depth'] * a * iris_shadow_profile(x - pos, pk['width'])
    return f


def iris_red_envelope(u):
    """Atem-Huellkurve des roten Blitzes.

    2026-08-11 Runde 2 ("etwas weniger flashy"): der Attack SPRINGT nicht
    mehr, er BLUEHT ueber den Perioden-Anfang auf (smoothstep — sitzt
    fuers Auge weiter auf dem Beat, liest sich aber als Puls statt
    Strobe; Club-Praxis: Pulse haben endliche Attacks, Strobes springen).

    2026-08-12 Runde 3 ("fade-in/out subtiler, natuerlicher"): die
    Verglimm-Form ist konfigurierbar — das alte quadratische g² faellt
    direkt nach dem Hold MAXIMAL steil (genau das las sich flashy);
    red_decay_smooth blendet auf smoothstep(g), das mit Steigung 0
    beginnt UND landet: der Schlag loest sich, er bricht nicht ab.
    Attack/Hold-Anteile kommen aus iris_config (Default 12 %/9 %).
    """
    u = u % 1.0
    atk, hold, floor = IRIS['red_attack'], IRIS['red_hold'], IRIS['red_floor']
    if u < atk:
        f = u / atk
        rise = f * f * (3.0 - 2.0 * f)
        return floor + (1.0 - floor) * rise
    if u < atk + hold:
        return 1.0
    f = (u - atk - hold) / (1.0 - atk - hold)
    g = 1.0 - f
    decay = g * g
    sm = IRIS['red_decay_smooth']
    if sm > 0.0:
        decay += (g * g * (3.0 - 2.0 * g) - decay) * sm
    return floor + (1.0 - floor) * decay


def iris_red_punch_peak(ks, punch):
    """L2: Peak-Faktor des Schlags aus der gemessenen Kick-Staerke.

    Harter Kick (ks=1) -> voller Peak 1.0; sanfter Kick (ks=0) drueckt den
    Peak um bis zu `punch`. punch=0 = Baseline (jeder Schlag gleich hart).
    """
    ks = max(0.0, min(1.0, ks))
    return 1.0 - max(0.0, punch) * (1.0 - ks)


def iris_scale_envelope(env, peak, floor):
    """Huellkurve ueber dem Glut-Boden auf den Peak skalieren.

    Der Boden BLEIBT (die Glut stirbt nie mit einem sanften Kick) — nur
    der Hub darueber atmet mit der Schlag-Staerke.
    """
    if peak >= 1.0 or floor >= 1.0:
        return env
    return floor + (env - floor) * (peak - floor) / (1.0 - floor)


def iris_freerun_walk(f, jitter, r):
    """L2: Random-Walk-Schritt der Freilauf-Periode (r in [-1,1]).

    Halber Jitter je Schritt, reflektierend geklemmt auf ±jitter — die
    0.55 s driften traege statt exakt zu ticken (kein Metronom), koennen
    aber nie davonlaufen.
    """
    if jitter <= 0.0:
        return 1.0
    return max(1.0 - jitter, min(1.0 + jitter, f + 0.5 * jitter * r))


def iris_engage_window(rng, variety):
    """L2: Dunkelfenster des Engage-Doppelpulses, je Warn-Flanke gewuerfelt.

    Baseline (variety=False): exakt (0.07, 0.13) = ON 70 / OFF 60 / ON 80 ms.
    Mit Variety wandert der Aussetzer (Start 50-90 ms, Laenge 45-75 ms) —
    bleibt aber IMMER in der Engage-Phase (< 0.21 s), der zweite Puls hat
    also mindestens ~45 ms.
    """
    if not variety:
        return (0.07, 0.13)
    a = rng.uniform(0.05, 0.09)
    return (a, a + rng.uniform(0.045, 0.075))


def iris_wave_spawn(rng, s, variety):
    """L3: Wellen-Descriptor je Kick (`born` setzt der Aufrufer).

    Baseline (variety=False): das Legacy-Dict {'s'} — Malpfad-Fallbacks
    (of 0.5, dir 0, v/width aus s) reproduzieren die alte Welle bit-genau.
    Mit Variety: Ursprung Mitte-bias gewuerfelt (Gauss sigma 0.18, geklemmt
    0.08..0.92 — nie AN der Kante, nie fix), Richtung 50 % beidseitig /
    je 25 % links/rechts, Tempo ±~17 %, Breite -20..+25 %.
    """
    if not variety:
        return {'s': s}
    of = max(0.08, min(0.92, 0.5 + rng.gauss(0.0, 0.18)))
    r = rng.random()
    direction = 0 if r < 0.5 else (1 if r < 0.75 else -1)
    return {'s': s, 'of': of, 'dir': direction,
            'v': (520.0 + 780.0 * s) * rng.uniform(0.85, 1.2),
            'width': (12.0 + 24.0 * s) * rng.uniform(0.8, 1.25)}


def iris_wave_speed(w):
    """Effektive Wellen-Geschwindigkeit (LED/s) — Legacy-Fallback aus s."""
    return w.get('v') or (520.0 + 780.0 * w['s'])


def iris_wave_reach(w, n):
    """Lauf-Distanz, nach der die Welle den Strip verlassen hat (+Puffer).

    Legacy (of 0.5, dir 0) = n/2 + 60 — exakt die alte Prune-Formel.
    Einseitige Wellen sterben frueher/spaeter, je nachdem wie viel Strip
    in ihrer Richtung liegt.
    """
    of = w.get('of', 0.5)
    direction = w.get('dir', 0)
    if direction > 0:
        base = (1.0 - of) * n
    elif direction < 0:
        base = of * n
    else:
        base = max(of, 1.0 - of) * n
    return base + 60.0


def iris_spark_window(rng, variety):
    """L3: Dauer des Funkenfensters je Schlag — Baseline exakt 55 ms."""
    if not variety:
        return 0.055
    return rng.uniform(0.04, 0.08)


def _meteor_v1_factor(profile):
    """End-/Start-Geschwindigkeits-Verhaeltnis je Profil.

    expo_out = Whip: schnell herein, klar verlangsamend — aber nie unter
    45 % von v0 (ein klassisches expo-out kriecht am Ende, der Meteor muss
    den Strip ENTSCHLOSSEN verlassen). accel zieht leicht an.
    """
    return {'const': 1.0, 'accel': 1.25}.get(profile, 0.45)


def iris_meteor_pos(t, v0, dur, profile):
    """Kopf-Weg (LED ab Start) zur Zeit t — analytisch, delta-time.

    Geschwindigkeit laeuft linear von v0 auf v0*faktor ueber `dur`
    (integriert = Quadratik); NACH dur faehrt der Kopf mit Endtempo weiter,
    damit der Schweif hinausgleitet statt eingefroren stehenzubleiben.
    """
    v1 = v0 * _meteor_v1_factor(profile)
    if t <= 0.0:
        return 0.0
    if t <= dur:
        return v0 * t + (v1 - v0) * t * t / (2.0 * dur)
    return (v0 + v1) * dur / 2.0 + v1 * (t - dur)


def iris_meteor_dur(dist, v0, profile):
    """Flugdauer fuer `dist` LEDs (Mitteltempo des linearen Profils)."""
    v1 = v0 * _meteor_v1_factor(profile)
    return dist / max(1.0, (v0 + v1) / 2.0)


def iris_meteor_time_for(x, v0, dur, profile):
    """Zeitpunkt, an dem der Kopf den Weg `x` erreicht (Umkehrfunktion).

    Quadratik aufgeloest; jenseits von dur linear weiter. Fuer den
    vorberechneten Impact-Zeitpunkt (Kopf verlaesst den Strip).
    """
    v1 = v0 * _meteor_v1_factor(profile)
    end = (v0 + v1) * dur / 2.0
    if x <= 0.0:
        return 0.0
    if x >= end:
        return dur + (x - end) / max(1.0, v1)
    a = (v1 - v0) / (2.0 * dur)
    if abs(a) < 1e-9:
        return x / v0
    disc = v0 * v0 + 4.0 * a * x
    return (-v0 + disc ** 0.5) / (2.0 * a)


def iris_meteor_duck(bl_t, pre, flight_end, duck, recover):
    """Duck-Faktor der roten Basis waehrend eines Meteor-Plans.

    Pre-Dip: Smoothstep 1.0 -> duck ueber die `pre`-Phase (das "Einatmen");
    im Flug konstant duck; nach flight_end Smoothstep zurueck auf 1.0 ueber
    `recover`. Stetig an allen Uebergaengen — die Basis darf nie springen.
    """
    if bl_t <= 0.0:
        return 1.0
    if bl_t < pre:
        f = bl_t / pre
        s = f * f * (3.0 - 2.0 * f)
        return 1.0 + (duck - 1.0) * s
    if bl_t < flight_end:
        return duck
    f = min(1.0, (bl_t - flight_end) / max(1e-6, recover))
    s = f * f * (3.0 - 2.0 * f)
    return duck + (1.0 - duck) * s


def iris_meteor_jitter(pixel, seed):
    """Deterministische Glut-Koernung des Schweifs: -1..1 je (Pixel, Seed).

    Hash-Rauschen mit u32-Maske — die usize-Falle aus dem Beat-Detektor:
    ohne Maske wird das 'Rauschen' eine riesige In-Band-Rampe.
    """
    h = (pixel * 2654435761 + seed * 40503) & 0xffffffff
    h ^= h >> 13
    h = (h * 1274126177) & 0xffffffff
    return ((h >> 8) & 0xffff) / 32767.5 - 1.0


app = Flask(__name__)
CORS(app)


def parse_pio_map(dmesg_text):
    """GPIO -> /dev/ledsN aus den Kernel-Meldungen des ws2812-pio-Treibers.

    Der Kernel nummeriert die Devices nach DT-Unit-Adresse (aufsteigender
    GPIO), NICHT nach Overlay-Reihenfolge in der config.txt. Beobachtet
    2026-08-06: gpio=18 zusaetzlich zu gpio=21 machte GPIO 18 zu leds0 und
    schob die BESTEHENDE Kette auf leds1 — der Dienst schrieb weiter auf
    leds0, also auf den falschen Pin. Genau das war die "Farbverschiebung"
    vom 05.08. Deshalb: nie Namen aus der Config glauben, immer aufloesen.
    Bei mehreren Eintraegen pro GPIO (Re-Bind) gewinnt der letzte.
    """
    import re
    m = {}
    for g, d in re.findall(r"ws2812[^\n]*?GPIO (\d+) as (/dev/leds\d+)", dmesg_text):
        m[int(g)] = d
    return m


def resolve_pio_device(pin, pins_sorted):
    """Device fuer einen GPIO: dmesg-Wahrheit, sonst Rang in sortierter Pin-Liste.

    Kennt dmesg den Treiber, ist seine Karte VOLLSTAENDIG: ein Pin ohne
    Eintrag hat KEIN Device (Overlay aus) und liefert None — Kette wird
    uebersprungen. Der Rang-Fallback gilt nur, wenn dmesg gar nicht lesbar
    ist. Vorher fiel ein overlay-loser Pin in den Fallback und landete auf
    Rang 0 = dem Device der ERSTEN Kette: zwei Ketten auf einem Device,
    jeder zweite Write EBUSY, und der bewiesene Clear konnte nie latchen.
    """
    try:
        import subprocess
        out = subprocess.run(["dmesg"], capture_output=True, text=True, timeout=3).stdout
        m = parse_pio_map(out)
        if m:
            return m.get(int(pin))
    except Exception:
        pass
    # Fallback = dieselbe Ordnung, nach der der Kernel nummeriert.
    return "/dev/leds%d" % sorted(pins_sorted).index(int(pin))


class LichtwerkWebController:
    def __init__(self, config_file='config.json'):
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        
        led_cfg = self.config['led_config']
        # Multi-Kette (2026-08-06): jede in config['strips'] gelistete Kette,
        # deren Device existiert, spielt gespiegelt mit (MultiStrip: EIN
        # Buffer, EIN Render, N Writes — der Versatz zwischen den Ketten ist
        # Mikrosekunden, weil write() sofort zurueckkehrt und die 18 ms
        # Shift-out in Hardware laufen). Fehlt ein /dev/ledsN (Overlay aus,
        # Kette ab, Boot-Konflikt), wird GENAU DIESE Kette uebersprungen und
        # alles andere laeuft wie bisher — eine fehlende zweite Kette darf
        # nie die erste kosten.
        chains = self.config.get('strips') or [{
            'pin': led_cfg['pin'], 'led_count': led_cfg['led_count'],
            'device': '/dev/leds0',
        }]
        working = []
        belegt = set()
        pins = [int(c.get('pin', led_cfg['pin'])) for c in chains]
        for c in chains:
            pin = int(c.get('pin', led_cfg['pin']))
            # config['device'] wird BEWUSST ignoriert: die leds-Nummern haengen
            # von der Menge der Overlays ab (s. parse_pio_map) — nur der Pin
            # ist stabil.
            dev = resolve_pio_device(pin, pins)
            if not dev or not os.path.exists(dev):
                print(f"Kette GPIO {pin} ({dev}) nicht vorhanden — uebersprungen")
                continue
            if dev in belegt:
                print(f"Kette GPIO {pin}: {dev} schon belegt — uebersprungen")
                continue
            belegt.add(dev)
            st = PixelStrip(
                c.get('led_count', led_cfg['led_count']),
                pin,
                led_cfg['led_freq_hz'],
                led_cfg['led_dma'],
                led_cfg['led_invert'],
                led_cfg['led_brightness'],
                led_cfg['led_channel'],
                device=dev,
            )
            try:
                st.begin()
                working.append(st)
                print(f"Kette aktiv: GPIO {pin} -> {dev}")
            except RuntimeError as e:
                print(f"Warning: LED strip init failed ({dev}): {e}")
        if not working:
            print("Running in demo mode without hardware...")
            self.strip = None
        elif len(working) == 1:
            self.strip = working[0]
        else:
            self.strip = MultiStrip(working)
        
        # Konfigurierte Anlagen-Helligkeit der Strip-LUT — der Blinder
        # neutralisiert sie pro Frame und stellt sie danach wieder her.
        self.strip_lut_default = int(led_cfg.get('led_brightness', 255))
        # Zentrale Iris-Config (L1): Sektion "iris" aus config.json anwenden
        apply_iris_config(self.config.get('iris'))
        # State variables
        self.running = True
        self.power = False
        self.current_effect = 'solid'
        self.brightness = 100
        self.speed = 50
        self.color = [255, 255, 255]
        self.theater_rainbow = True  # Toggle for theater effect
        self.effect_thread = None
        # Strip-Warn: exclusive ownership while disco Strip-Warn is armed
        self.strip_warn_over = False   # mirrors page body.over-iris
        self.strip_warn_mode = False   # True while Strip-Warn owns the strip
        self._pre_warn = None          # Nutzer-Einstellungen vor dem Warn (Restore beim Disarm)
        self._strip_lock = threading.Lock()

        # Strip-Warn wash — the dB-Analyse page background, see iris_wash.py.
        # `max_current_a` caps the 5 V draw of a full-strip red wash by scaling
        # the exposure; leave it null to render at full exposure.
        wash_cfg = self.config.get('iris_wash') or {}
        self._wash_steps = max(2, int(wash_cfg.get('steps', iris_wash.DEFAULT_STEPS)))
        self._wash_exposure = float(wash_cfg.get('exposure', iris_wash.DEFAULT_EXPOSURE))
        self._wash_max_current_a = wash_cfg.get('max_current_a') or None
        self._wash_cache = ()
        self._wash_n = 0
        self._wash_t0 = None           # breathe origin; None while idle
        self._wash_fade_t0 = None      # release ramp origin; None when not fading
        self._wash_fade_from = 0       # frame the fade started from
        # White highlights on top of the wash — sparse, so the base frame stays
        # precomputed and only a handful of LEDs are rewritten per frame.
        wp = wash_cfg.get('white_point') or iris_wash.WHITE_POINT
        self._wash_white_point = tuple(max(0, min(255, int(v))) for v in wp)
        self._wash_sparks_on = bool(wash_cfg.get('sparks', True))
        self._wash_shimmer_on = bool(wash_cfg.get('shimmer', True))
        self._wash_sparks = []         # [(centre_led, age_s), ...]
        self._wash_spark_ts = None
        self._wash_kernel = iris_wash.spark_kernel()
        
        # Effect parameters
        self.effect_params = {
            'rainbow_offset': 0,
            'pulse_direction': 1,
            'pulse_brightness': 0.1,
            'chase_position': 0,
            'sparkle_pixels': [],
            'meteor_positions': [],
            'breathe_direction': 1,
            'breathe_brightness': 0.1
        }
        self._cleared = False          # skip redundant black show() when already dark
        self._effect_wake = threading.Event()
        
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        self.start_effect_loop()
    
    def signal_handler(self, sig, frame):
        print('\nShutting down...')
        self.running = False
        self._effect_wake.set()
        # Order matters: a frame past the `running` check can still paint AFTER
        # an early clear — the strip would sit lit (or holding a corrupted
        # frame) with nobody left to blank it until the next service start.
        # Join the painter first, then run the PROVEN double-clear so the last
        # frames on the wire are two black ones.
        if self.effect_thread and self.effect_thread.is_alive():
            try:
                self.effect_thread.join(timeout=0.5)
            except Exception:
                pass
        self.clear(force=True)
        if self.strip and hasattr(self.strip, 'close'):
            try:
                self.strip.close()
            except Exception:
                pass
        sys.exit(0)
    
    def clear(self, force=False):
        """Blank the strip — and PROVE it, twice.

        WS2812 serialises GRB, so one slipped bit in a 600-LED chain shifts
        crimson's 255 into the green or blue slot: the classic "LEDs stay
        green/blue at standstill" artifact is our own red, mis-latched. Two
        holes let it persist: (1) the PIO device takes ONE frame per open and
        drops collisions with EBUSY — a clear during 50 fps wave painting
        could vanish silently; (2) _cleared latched True regardless, blocking
        every retry. Standard WS2812 practice is writing the frame twice
        (signal-integrity errors are per-transmission, not sticky), and
        _cleared only latches when the LAST write really landed — a dropped
        one retries on the next effect-loop tick. The maintenance re-clear in
        run_effect heals anything that still slips through.
        """
        if not self.strip:
            return
        if self._cleared and not force:
            return
        with self._strip_lock:
            if self._cleared and not force:
                return
            ok = False
            for versuch in range(2):
                if versuch:
                    time.sleep(0.025)   # EBUSY window is the 18 ms shift-out
                if hasattr(self.strip, 'fill'):
                    self.strip.fill(Color(0, 0, 0))
                else:
                    for i in range(self.strip.numPixels()):
                        self.strip.setPixelColor(i, Color(0, 0, 0))
                ok = self.strip.show() is not False   # None (fremde Treiber) = ok
            self._cleared = ok
            self._last_clear_ts = time.monotonic()
    
    def wake_effect(self):
        """Interrupt effect-loop sleep so the next frame paints ASAP."""
        self._effect_wake.set()

    def _warn_snapshot(self):
        """Beim SCHARFWERDEN des Strip-Warn: Nutzer-Einstellungen sichern.

        Idempotent je Warn-Session (Folge-Flanken ueberschreiben den
        Schnappschuss nicht — sonst wuerde die Warn-eigene 255er-Brightness
        als 'Nutzerwunsch' gespeichert). Das ist die eine Haelfte der
        Entkopplung 2026-08-12 ('Lichtwerk-Einstellungen beissen sich mit
        Iris'): vorher ueberschrieb warn_gate die Nutzer-Brightness
        DAUERHAFT mit 255."""
        if self._pre_warn is None:
            self._pre_warn = {
                'brightness': self.brightness,
                'speed': self.speed,
                'color': list(self.color),
                'effect': (self.current_effect
                           if self.current_effect != 'iris_warn' else 'solid'),
            }

    def _warn_restore(self):
        """Beim ENTSCHAERFEN: Einstellungen zurueckspielen — inklusive
        aller waehrend des Warn DEFERRED geaenderten Werte (die UI-Routen
        schreiben bei aktivem Warn in den Schnappschuss statt live).
        Power bleibt bewusst AUS (bisherige Disarm-Semantik); der naechste
        Power-On startet mit den richtigen Werten statt mit der Warn-255."""
        pw = self._pre_warn
        self._pre_warn = None
        if not pw:
            return
        self.brightness = pw['brightness']
        self.speed = pw['speed']
        self.color = list(pw['color'])
        if pw['effect'] != 'iris_warn':
            self.current_effect = pw['effect']

    def _px_mix(self, i, r, g, b, w):
        """Replace-Blend gegen den AKTUELLEN Puffer — komponiert, nie ueberschreiben.

        Ein Lerp gegen die BERECHNETE Basis liesse jeden spaeteren Maler
        (Rueckwelle/Flash/Sparkle) einen frueheren hellen Maler wieder
        UEBERSCHREIBEN statt darueberzulegen (Feldbefund W2: die letzten
        6 LEDs verloren den Meteor-Kopf an die Rueckwelle). Geteilt von
        Meteor (W2) und Stardust (W3).
        """
        if w <= 0.003:
            return
        cur = self.strip.getPixelColor(i)
        cr = (cur >> 16) & 0xFF
        cg = (cur >> 8) & 0xFF
        cb = cur & 0xFF
        w = min(1.0, w)
        self.strip.setPixelColor(i, Color(
            int(cr + (r - cr) * w),
            int(cg + (g - cg) * w),
            int(cb + (b - cb) * w)))
    
    def set_pixel(self, index, r, g, b, brightness=1.0):
        if not self.strip:
            return
        r = int(r * brightness * (self.brightness / 255.0))
        g = int(g * brightness * (self.brightness / 255.0))
        b = int(b * brightness * (self.brightness / 255.0))
        self.strip.setPixelColor(index, Color(r, g, b))
    
    def wheel(self, pos):
        if pos < 0 or pos > 255:
            r = g = b = 0
        elif pos < 85:
            r = pos * 3
            g = 255 - pos * 3
            b = 0
        elif pos < 170:
            pos -= 85
            r = 255 - pos * 3
            g = 0
            b = pos * 3
        else:
            pos -= 170
            r = 0
            g = pos * 3
            b = 255 - pos * 3
        return r, g, b
    
    def effect_solid(self):
        if not self.strip:
            return
        scale = max(0.0, min(1.0, self.brightness / 255.0))
        c = Color(int(self.color[0] * scale), int(self.color[1] * scale), int(self.color[2] * scale))
        if hasattr(self.strip, 'fill'):
            self.strip.fill(c)
        else:
            for i in range(self.strip.numPixels()):
                self.strip.setPixelColor(i, c)
        self.strip.show()
        self._cleared = False
    
    def effect_rainbow(self):
        if not self.strip:
            return
        for i in range(self.strip.numPixels()):
            pixel_hue = (i + self.effect_params['rainbow_offset']) % 256
            r, g, b = self.wheel(pixel_hue)
            self.set_pixel(i, r, g, b)
        self.strip.show()
        self.effect_params['rainbow_offset'] = (self.effect_params['rainbow_offset'] + 1) % 256
    
    def effect_pulse(self):
        if not self.strip:
            return
        brightness = self.effect_params['pulse_brightness']
        direction = self.effect_params['pulse_direction']
        
        for i in range(self.strip.numPixels()):
            self.set_pixel(i, self.color[0], self.color[1], self.color[2], brightness)
        self.strip.show()
        
        brightness += direction * (self.speed / 1000.0)
        if brightness >= 1.0:
            brightness = 1.0
            direction = -1
        elif brightness <= 0.1:
            brightness = 0.1
            direction = 1
        
        self.effect_params['pulse_brightness'] = brightness
        self.effect_params['pulse_direction'] = direction
    
    def effect_chase(self):
        if not self.strip:
            return
        self.clear()
        segment_size = max(1, int(self.strip.numPixels() * 0.05))
        position = self.effect_params['chase_position']
        
        for i in range(segment_size):
            pixel_index = (position + i) % self.strip.numPixels()
            self.set_pixel(pixel_index, self.color[0], self.color[1], self.color[2])
        
        self.strip.show()
        self.effect_params['chase_position'] = (position + 1) % self.strip.numPixels()
    
    def effect_sparkle(self):
        if not self.strip:
            return
        # Fade existing sparkles
        for pixel_data in self.effect_params['sparkle_pixels']:
            pixel_data['brightness'] *= 0.9
            if pixel_data['brightness'] > 0.01:
                self.set_pixel(pixel_data['index'], 
                             self.color[0], self.color[1], self.color[2], 
                             pixel_data['brightness'])
        
        # Remove dim sparkles
        self.effect_params['sparkle_pixels'] = [
            p for p in self.effect_params['sparkle_pixels'] 
            if p['brightness'] > 0.01
        ]
        
        # Add new sparkles
        density = max(1, int(self.strip.numPixels() * 0.02))
        for _ in range(density):
            if random.random() < (self.speed / 100.0):
                self.effect_params['sparkle_pixels'].append({
                    'index': random.randint(0, self.strip.numPixels() - 1),
                    'brightness': 1.0
                })
        
        self.strip.show()
    
    def effect_strobe(self):
        if not self.strip:
            return
        if time.time() * 1000 % (200 - self.speed * 2) < 50:
            for i in range(self.strip.numPixels()):
                self.set_pixel(i, self.color[0], self.color[1], self.color[2])
        else:
            self.clear()
        self.strip.show()
    
    def effect_meteor(self):
        if not self.strip:
            return
        
        # Enhanced fade effect - store pixel states for proper fading
        if 'pixel_states' not in self.effect_params:
            self.effect_params['pixel_states'] = [[0, 0, 0] for _ in range(self.strip.numPixels())]
            self.effect_params['last_meteor_spawn'] = 0
        
        # Fade all pixels more gradually and visibly
        for i in range(self.strip.numPixels()):
            # Fade factor for smoother, more visible trail
            fade_factor = 0.92  # Slower fade for more visible trail
            self.effect_params['pixel_states'][i][0] = int(self.effect_params['pixel_states'][i][0] * fade_factor)
            self.effect_params['pixel_states'][i][1] = int(self.effect_params['pixel_states'][i][1] * fade_factor)
            self.effect_params['pixel_states'][i][2] = int(self.effect_params['pixel_states'][i][2] * fade_factor)
            
            # Apply faded color
            self.strip.setPixelColor(i, Color(
                self.effect_params['pixel_states'][i][0],
                self.effect_params['pixel_states'][i][1],
                self.effect_params['pixel_states'][i][2]
            ))
        
        # Create new meteors MUCH less frequently with minimum spacing
        self.effect_params['last_meteor_spawn'] = self.effect_params.get('last_meteor_spawn', 0) + 1
        min_spawn_distance = 100  # Minimum frames between spawns
        spawn_chance = (self.speed / 5000.0)  # Drastically reduced spawn rate
        
        # Only spawn if enough time has passed AND random chance succeeds AND not too many meteors
        if (self.effect_params['last_meteor_spawn'] > min_spawn_distance and 
            random.random() < spawn_chance and 
            len(self.effect_params.get('meteor_positions', [])) < 2):  # Max 2 meteors at once
            
            meteor_size = random.randint(10, 20)  # Larger meteors
            self.effect_params['meteor_positions'].append({
                'position': 0,
                'size': meteor_size,
                'speed': random.uniform(1.5, 2.5),  # More consistent speed
                'trail_length': meteor_size * 3  # Longer trail for better visibility
            })
            self.effect_params['last_meteor_spawn'] = 0  # Reset spawn timer
        
        # Update existing meteors
        active_meteors = []
        for meteor in self.effect_params['meteor_positions']:
            meteor['position'] += meteor['speed']
            
            # Draw meteor with enhanced trail
            for i in range(meteor['trail_length']):
                pixel_pos = int(meteor['position'] - i)
                if 0 <= pixel_pos < self.strip.numPixels():
                    # Enhanced brightness calculation for better trail visibility
                    if i < meteor['size']:
                        # Bright head of meteor
                        brightness = 1.0 - (i * 0.05)  # Gradual dimming at head
                    else:
                        # Fading tail
                        tail_position = i - meteor['size']
                        tail_length = meteor['trail_length'] - meteor['size']
                        brightness = max(0.05, 0.8 * (1.0 - (tail_position / tail_length)))
                    
                    # Update pixel state for proper fading
                    self.effect_params['pixel_states'][pixel_pos][0] = int(self.color[0] * brightness)
                    self.effect_params['pixel_states'][pixel_pos][1] = int(self.color[1] * brightness)
                    self.effect_params['pixel_states'][pixel_pos][2] = int(self.color[2] * brightness)
                    
                    self.strip.setPixelColor(pixel_pos, Color(
                        self.effect_params['pixel_states'][pixel_pos][0],
                        self.effect_params['pixel_states'][pixel_pos][1],
                        self.effect_params['pixel_states'][pixel_pos][2]
                    ))
            
            # Keep meteor if still visible (including tail)
            if meteor['position'] < self.strip.numPixels() + meteor['trail_length']:
                active_meteors.append(meteor)
        
        self.effect_params['meteor_positions'] = active_meteors
        self.strip.show()
    
    def fade_toward_color(self, current_color, target_color, fade_amount):
        """FastLED-style fadeTowardColor function"""
        def fade_component(current, target, amount):
            if current == target:
                return current
            elif current < target:
                return min(current + amount, target)
            else:
                return max(current - amount, target)
        
        return [
            fade_component(current_color[0], target_color[0], fade_amount),
            fade_component(current_color[1], target_color[1], fade_amount),
            fade_component(current_color[2], target_color[2], fade_amount)
        ]
    
    def hsv_to_rgb(self, h, s, v):
        """Convert HSV to RGB color space"""
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return int(r * 255), int(g * 255), int(b * 255)
    
    def effect_sinelon(self):
        """Sinelon - a sinusoidal wave with fading trail"""
        if not self.strip:
            return
        
        import math
        
        # Initialize effect parameters
        if 'sinelon_phase' not in self.effect_params:
            self.effect_params['sinelon_phase'] = 0
            self.effect_params['sinelon_pixels'] = [[0, 0, 0] for _ in range(self.strip.numPixels())]
        
        pixels = self.effect_params['sinelon_pixels']
        
        # Fade all pixels
        fade_rate = 0.95
        for i in range(len(pixels)):
            pixels[i][0] = int(pixels[i][0] * fade_rate)
            pixels[i][1] = int(pixels[i][1] * fade_rate)
            pixels[i][2] = int(pixels[i][2] * fade_rate)
        
        # Calculate position using sine wave
        self.effect_params['sinelon_phase'] += self.speed / 500.0
        pos = int((math.sin(self.effect_params['sinelon_phase']) + 1.0) * 0.5 * (len(pixels) - 1))
        
        # Set pixel at position
        # Use the configured color
        color = self.color
        
        if 0 <= pos < len(pixels):
            pixels[pos] = [color[0], color[1], color[2]]
        
        # Apply brightness and update strip
        brightness_factor = self.brightness / 255.0
        for i in range(len(pixels)):
            self.strip.setPixelColor(i, Color(
                int(pixels[i][0] * brightness_factor),
                int(pixels[i][1] * brightness_factor),
                int(pixels[i][2] * brightness_factor)
            ))
        
        self.strip.show()
    
    def effect_juggle(self):
        """Juggle - eight colored dots weaving in and out"""
        if not self.strip:
            return
        
        import math
        
        # Initialize effect parameters
        if 'juggle_phase' not in self.effect_params:
            self.effect_params['juggle_phase'] = 0
            self.effect_params['juggle_pixels'] = [[0, 0, 0] for _ in range(self.strip.numPixels())]
        
        pixels = self.effect_params['juggle_pixels']
        
        # Fade all pixels
        fade_rate = 0.92
        for i in range(len(pixels)):
            pixels[i][0] = int(pixels[i][0] * fade_rate)
            pixels[i][1] = int(pixels[i][1] * fade_rate)
            pixels[i][2] = int(pixels[i][2] * fade_rate)
        
        # Update phase
        self.effect_params['juggle_phase'] += self.speed / 300.0
        phase = self.effect_params['juggle_phase']
        
        # Draw 8 dots
        for dot in range(8):
            pos = int((math.sin((dot + 7) * phase * 1.2) + 1.0) * 0.5 * (len(pixels) - 1))
            if 0 <= pos < len(pixels):
                # Each dot gets a different color
                hue = (dot * 32) / 255.0
                color = self.hsv_to_rgb(hue, 0.8, 1.0)
                # Add to existing pixel value
                pixels[pos][0] = min(255, pixels[pos][0] + color[0])
                pixels[pos][1] = min(255, pixels[pos][1] + color[1])
                pixels[pos][2] = min(255, pixels[pos][2] + color[2])
        
        # Apply brightness and update strip
        brightness_factor = self.brightness / 255.0
        for i in range(len(pixels)):
            self.strip.setPixelColor(i, Color(
                int(pixels[i][0] * brightness_factor),
                int(pixels[i][1] * brightness_factor),
                int(pixels[i][2] * brightness_factor)
            ))
        
        self.strip.show()
    
    def effect_theater_chase_rainbow(self):
        """Theater chase with rainbow or single color"""
        if not self.strip:
            return
        
        # Initialize effect parameters
        if 'theater_j' not in self.effect_params:
            self.effect_params['theater_j'] = 0
            self.effect_params['theater_q'] = 0
        
        # Clear strip
        for i in range(self.strip.numPixels()):
            self.strip.setPixelColor(i, Color(0, 0, 0))
        
        # Draw pattern
        j = self.effect_params['theater_j']
        q = self.effect_params['theater_q']
        
        for i in range(0, self.strip.numPixels(), 3):
            idx = i + q
            if idx < self.strip.numPixels():
                if self.theater_rainbow:
                    # Rainbow color based on position and time
                    hue = ((i + j) % 255) / 255.0
                    color = self.hsv_to_rgb(hue, 1.0, 1.0)
                else:
                    # Use single color
                    color = (self.color[0], self.color[1], self.color[2])
                
                brightness_factor = self.brightness / 255.0
                self.strip.setPixelColor(idx, Color(
                    int(color[0] * brightness_factor),
                    int(color[1] * brightness_factor),
                    int(color[2] * brightness_factor)
                ))
        
        self.strip.show()
        
        # Update counters
        self.effect_params['theater_q'] = (q + 1) % 3
        if q == 2:
            self.effect_params['theater_j'] = (j + 1) % 256
    
    def effect_gradient_fill(self):
        """Gradient fill effect - fills strip with gradient colors"""
        if not self.strip:
            return
        
        # Initialize effect parameters
        if 'gradient_pos' not in self.effect_params:
            self.effect_params['gradient_pos'] = 0
            self.effect_params['gradient_hue1'] = 0
            self.effect_params['gradient_hue2'] = 120
        
        pos = self.effect_params['gradient_pos']
        hue1 = self.effect_params['gradient_hue1'] / 360.0
        hue2 = self.effect_params['gradient_hue2'] / 360.0
        
        # Fill with gradient up to current position
        for i in range(self.strip.numPixels()):
            if i <= pos:
                # Interpolate between two hues
                t = i / max(1, pos)
                hue = hue1 + (hue2 - hue1) * t
                if hue < 0:
                    hue += 1.0
                if hue > 1.0:
                    hue -= 1.0
                color = self.hsv_to_rgb(hue, 1.0, 1.0)
            else:
                color = (0, 0, 0)
            
            brightness_factor = self.brightness / 255.0
            self.strip.setPixelColor(i, Color(
                int(color[0] * brightness_factor),
                int(color[1] * brightness_factor),
                int(color[2] * brightness_factor)
            ))
        
        self.strip.show()
        
        # Update position
        self.effect_params['gradient_pos'] += max(1, int(self.speed / 10))
        if self.effect_params['gradient_pos'] >= self.strip.numPixels():
            self.effect_params['gradient_pos'] = 0
            # New random colors
            import random
            self.effect_params['gradient_hue1'] = random.randint(0, 360)
            self.effect_params['gradient_hue2'] = (self.effect_params['gradient_hue1'] + random.randint(60, 180)) % 360
    
    def effect_fire(self):
        """Fire effect - 1D heat simulation"""
        if not self.strip:
            return
        
        import random
        
        # Initialize heat array
        if 'fire_heat' not in self.effect_params:
            self.effect_params['fire_heat'] = [0] * self.strip.numPixels()
        
        heat = self.effect_params['fire_heat']
        num_leds = len(heat)
        
        # Cooling: How much does each cell cool down every step
        cooling = 55
        
        # Sparking: What chance (out of 255) is there that a new spark will be lit
        sparking = 120
        
        # Step 1: Cool down every cell a little
        for i in range(num_leds):
            cooldown = random.randint(0, ((cooling * 10) // num_leds) + 2)
            heat[i] = max(0, heat[i] - cooldown)
        
        # Step 2: Heat from each cell drifts up and diffuses slightly
        for k in range(num_leds - 1, 1, -1):
            heat[k] = (heat[k - 1] + heat[k - 2] + heat[k - 2]) // 3
        
        # Step 3: Randomly ignite new sparks near the bottom
        if random.randint(0, 255) < sparking:
            y = random.randint(0, min(7, num_leds - 1))
            heat[y] = min(255, heat[y] + random.randint(160, 255))
        
        # Step 4: Convert heat to LED colors
        for j in range(num_leds):
            # Scale heat value to 0-255
            colorindex = min(255, heat[j])
            
            # Calculate color - heat palette (black -> red -> yellow -> white)
            if colorindex < 85:
                # Black to red
                r = (colorindex * 3)
                g = 0
                b = 0
            elif colorindex < 170:
                # Red to yellow
                r = 255
                g = ((colorindex - 85) * 3)
                b = 0
            else:
                # Yellow to white
                r = 255
                g = 255
                b = ((colorindex - 170) * 3)
            
            brightness_factor = self.brightness / 255.0
            # Mirror to make fire rise from bottom
            self.strip.setPixelColor(num_leds - 1 - j, Color(
                int(r * brightness_factor),
                int(g * brightness_factor),
                int(b * brightness_factor)
            ))
        
        self.strip.show()
    
    def effect_breathe(self):
        if not self.strip:
            return
        
        brightness = self.effect_params['breathe_brightness']
        direction = self.effect_params['breathe_direction']
        
        # Set all pixels to same brightness
        for i in range(self.strip.numPixels()):
            self.set_pixel(i, self.color[0], self.color[1], self.color[2], brightness)
        self.strip.show()
        
        # Update breathing pattern
        speed_factor = self.speed / 2000.0
        brightness += direction * speed_factor
        
        if brightness >= 1.0:
            brightness = 1.0
            direction = -1
        elif brightness <= 0.05:
            brightness = 0.05
            direction = 1
        
        self.effect_params['breathe_brightness'] = brightness
        self.effect_params['breathe_direction'] = direction
    

    def _wash_frames(self):
        """Precomputed breathe ramp — rebuilt only when the LED count changes."""
        n = self.strip.numPixels() if self.strip else 0
        if n <= 0:
            return ()
        if self._wash_n != n or not self._wash_cache:
            self._wash_cache = iris_wash.build_frames(
                n, self._wash_steps, self._wash_exposure, self._wash_max_current_a)
            self._wash_n = n
            exposure = (iris_wash.fit_exposure(n, self._wash_max_current_a, self._wash_exposure)
                        if self._wash_max_current_a else self._wash_exposure)
            peak = iris_wash.estimate_current_a(n, 1.0, exposure)
            spark = iris_wash.spark_current_a() if self._wash_sparks_on else 0.0
            shim = iris_wash.shimmer_current_a() if self._wash_shimmer_on else 0.0
            print(f"iris wash: {len(self._wash_cache)} frames x {n} LEDs, "
                  f"exposure {exposure:.2f}, peak ~{peak:.1f} A"
                  f" (+{spark:.1f} sparks +{shim:.1f} shimmer)"
                  f" = worst case ~{peak + spark + shim:.1f} A")
        return self._wash_cache

    def _wash_engage(self):
        """Threshold crossed — start the wash at the breathe peak.

        `alternate` reaches its maximum half a cycle in, so back-dating t0 by
        one period lands the first frame on the peak: the warning arrives at
        full intensity and breathes down from there.
        """
        self._wash_t0 = time.monotonic() - iris_wash.BREATHE_PERIOD_S
        self._wash_fade_t0 = None
        self._wash_sparks = []
        self._wash_spark_ts = None
        self._wash_frames()

    def _wash_release(self):
        """Back under threshold — fade out like the page's .55 s transition."""
        if self._wash_t0 is None and self._wash_fade_t0 is None:
            return
        if self._wash_fade_t0 is None:
            self._wash_fade_from = self._wash_index()
            self._wash_fade_t0 = time.monotonic()
        self._wash_t0 = None

    def _wash_index(self):
        if self._wash_t0 is None:
            return self._wash_steps - 1
        return iris_wash.frame_index(time.monotonic() - self._wash_t0, self._wash_steps)

    def _iris_abort(self):
        """Hard-stop the wash — black at once, no fade (disarm / explicit off)."""
        self._wash_t0 = None
        self._wash_fade_t0 = None
        self.clear(force=True)

    def _show_payload(self, payload, gain=255):
        """Write a precomputed frame; falls back to per-pixel on legacy drivers.

        The master brightness slider is folded in here rather than inside the
        driver, so the wash keeps exactly the exposure `iris_wash` rendered.
        """
        strip = self.strip
        if strip is None:
            return
        gain = max(0, min(255, gain * max(0, min(255, self.brightness)) // 255))
        show_payload = getattr(strip, 'show_payload', None)
        if show_payload is not None:
            show_payload(payload, gain)
            return
        for i in range(strip.numPixels()):
            j = i * 4
            strip.setPixelColor(i, Color(payload[j] * gain // 255,
                                         payload[j + 1] * gain // 255,
                                         payload[j + 2] * gain // 255))
        strip.show()

    def _paint_wash_fade(self):
        """Drive the release ramp. Runs with power=False so it can finish."""
        frames = self._wash_frames()
        if not frames or self._wash_fade_t0 is None:
            self._wash_fade_t0 = None
            return
        gain = iris_wash.release_gain(time.monotonic() - self._wash_fade_t0)
        if gain <= 0:
            self._wash_fade_t0 = None
            self.clear(force=True)
            return
        with self._strip_lock:
            self._show_payload(frames[min(self._wash_fade_from, len(frames) - 1)], gain)
        self._cleared = False

    def effect_iris_warn(self):
        """Hard Iris blitz — LED translation of dB-Analyse `over-iris`.

        On screen the crimson wash pops against a dark page. Historische
        Doktrin war "LEDs need binary contrast: FULL crimson <-> BLACK" —
        seit 2026-08-11 auf Nutzerwunsch ersetzt: Attack hart AUF dem Beat,
        danach verglimmt das Rot per iris_red_envelope auf einen Glut-Boden
        (dieselbe Abklingsprache wie die Sparkle-Blinder).

        Timing:
          1) Engage double-pulse (class applied → hard snap)
          2) Sustain square flash @ body-transition period (.55s), ~65% duty
          3) On each ON edge: dense white LED sparks for ~55 ms
        Local ~60 fps — no HTTP frame spam from disco.

        Beat-synced extension (2026-08-05, additive): disco pushes ONE tiny
        POST per detected kick (/api/warn_kick {strength}) — events, not
        frames. Each kick (a) snaps the square-wave phase so the ON edge lands
        ON the beat, (b) launches a centre-out shockwave whose white-hot front
        races to both ends (the 1D twin of the page's IGNIS Druckwelle;
        replace-blend toward warm white, so peak current stays ≈ the tagged
        blitz), and (c) re-arms the spark window with density ∝ strength.
        WITHOUT kicks every frame is bit-identical to the tagged
        perfekt-20260805 behaviour — the square free-runs at 0.55 s from the
        last phase, waves expire, boost decays. Fallback IS the tag.
        Club-lighting research behind the shape: motion/chase carries energy,
        strobe accents belong ON musical hits, restraint preserves impact.

        Weiss-Events (2026-08-09): disco klassifiziert schnelle Onsets zu
        double/roll/accent (POST /api/warn_event) und der Blinder-Scheduler
        rendert die FORM des Events — Doppel-Blitz im echt gemessenen
        Kick-Abstand, Rollen-Stakkato, Einzelschlag; der Drop nutzt den
        Scheduler als Preset. Per-Kick-Funken + Wellenkern sind seither
        GLUT (Bernstein) statt Weiss: Weiss ist Interpunktion, Rot (und
        seine Glut) ist die Stimmung.
        """
        if not self.strip:
            return
        import random
        import time as _time
        # Injizierbare Uhr (L1): Default = Echtzeit; Offline-Harness und
        # Golden-Frame-Test setzen self.iris_clock auf eine Fake-Uhr —
        # damit werden Frames vollstaendig deterministisch.
        mono = getattr(self, 'iris_clock', None) or _time.monotonic

        def _sparkle_spots(count):
            # Cluster-Positionen fuer den Sparkle-Blinder: `count` Zentren,
            # 2-5 LEDs breit, individuelle Helligkeit — der Glitzer-Look.
            # Zufall NUR aus der seedbaren Effekt-RNG (L1).
            # ⚠️ WEISS-BUDGET (2026-08-13): die abgenommenen Detektor-Formen
            # laufen mit 16-26 Clustern (Sparse-Klasse: winzige Last -> kein
            # 5-V-Sack -> ehrliches Warmweiss). Die Picker-Events skalieren
            # mit density bis 1,5 auf bis zu 39 Cluster (~195 LEDs) — genau
            # dort kippte Weiss GELBLICH (Nutzerbefund: die blaue Die
            # verhungert zuerst). Kappen auf die erprobte Klasse; Formen
            # innerhalb des Budgets bleiben bit-identisch. 0 = Waechter aus.
            max_spots = int(IRIS.get('white_max_spots', 0) or 0)
            if max_spots > 0:
                count = min(int(count), max_spots)
            max_px = int(IRIS.get('white_max_px', 0) or 0)
            rng = self.effect_params.get('iris_rng') or random
            npx = self.strip.numPixels()
            spots = []
            for _ in range(count):
                if max_px > 0 and len(spots) >= max_px:
                    break
                centre = rng.randrange(npx)
                width = rng.choice((2, 3, 3, 4, 5))
                bri = 0.6 + rng.random() * 0.4
                for off in range(-(width // 2), (width - 1) // 2 + 1):
                    j = centre + off
                    if 0 <= j < npx:
                        spots.append((j, bri))
            return tuple(spots)
        t0 = self.effect_params.get('iris_t0')
        if t0 is None:
            t0 = mono()
            self.effect_params['iris_t0'] = t0
            self.effect_params['iris_lit'] = None
            self.effect_params['iris_sparking'] = None
            self.effect_params['iris_spark_until'] = 0.0
            self.effect_params['iris_ph'] = 0.0          # square-wave phase offset (kick sync)
            self.effect_params['iris_beat_ema'] = None   # measured inter-kick interval (tempo lock)
            self.effect_params['iris_last_kick'] = None
            self.effect_params['iris_last_snap'] = -9.0  # snap refractory vs onset double-fire
            self.effect_params['iris_waves'] = []        # [{'born': t, 's': strength}]
            self.effect_params['iris_kick_boost'] = 0.0  # spark density ∝ last kick strength
            self.effect_params['iris_next_paint'] = 0.0  # wave repaint pacing (~50 fps)
            self.effect_params['iris_next_heal'] = 0.0   # heartbeat: hold-phase re-send (bit-slip healing)
            self.effect_params['iris_kick_avg'] = 0.0    # traeges Staerke-Mittel -> Drop-Erkennung
            self.effect_params['iris_blinder'] = None    # Blinder-Plan {'t0', 'win': ((a,b,gain),...)}
            self.effect_params['iris_events'] = []       # double/roll/accent von disco (verderblich)
            self.effect_params['iris_shadows'] = []      # Schattenzonen: frische Kohorte je Engage
            # Seedbare RNG je Engage (L1): fester Seed => jedes Engage exakt
            # reproduzierbar (Golden-Frame/Offline-Harness); None = Zufall.
            self.effect_params['iris_rng'] = random.Random(IRIS['seed'])
                                                         # (iris_t0 resettet je Warn-Flanke -> alte
                                                         # born-Zeiten waeren unsichtbare Zombies)
            # L2: Engage-Timing je Flanke + Freilauf-Random-Walk (Reset je
            # Engage — Zombie-Doktrin: kein Zustand ueberlebt die Flanke).
            self.effect_params['iris_engage_win'] = iris_engage_window(
                self.effect_params['iris_rng'], IRIS['engage_variety'])
            self.effect_params['iris_freerun_f'] = 1.0
            self.effect_params['iris_drop_at'] = -1e9    # Cooldown 8 s — Bomben sind rar
            self.effect_params['iris_last_write'] = 0.0  # EIN Schreibtakt fuer ALLE Pfade
        t = mono() - t0

        # ── Kick intake (Flask thread appends plain floats; GIL-safe pops) ──
        q = self.effect_params.get('iris_kicks')
        snap = False
        while q:
            try:
                item = q.pop(0)
            except IndexError:
                break
            kb = None
            if isinstance(item, dict):
                kb = item.get('bpm')
                item = item.get('s')
            try:
                ks = max(0.0, min(1.0, float(item)))
            except (TypeError, ValueError):
                break
            if kb:
                # BPM seed: disco's IOI-median tempo is steadier than any gap
                # estimate here — take it directly; the EMA below remains the
                # fallback for kicks without bpm (older client).
                self.effect_params['iris_bpm_period'] = 60.0 / float(kb)
            lk = self.effect_params.get('iris_last_kick')
            if lk is not None:
                dt_k = t - lk
                # Plausible beat gaps only (40-250 BPM): onset double-fire and
                # dropouts must not poison the tempo estimate.
                if 0.24 <= dt_k <= 1.5:
                    ema = self.effect_params.get('iris_beat_ema')
                    # Fold missed-beat gaps back onto the grid: a skipped onset
                    # shows up as ~2x the beat interval and dragged the EMA up
                    # (measured 0.572 s against a 0.488 s beat) — halve instead
                    # of averaging in the outlier.
                    if ema is not None:
                        while dt_k > ema * 1.6 and dt_k >= 0.48:
                            dt_k /= 2.0
                    self.effect_params['iris_beat_ema'] = \
                        dt_k if ema is None else ema + (dt_k - ema) * IRIS['period_ema']
            self.effect_params['iris_last_kick'] = t
            # Refractory 0.24 s: on_beat fires on EVERY onset (snares/offbeats
            # included), and a snap per onset re-lights the window until the
            # dark phase collapses — the measured "verharrt" failure.
            if t - self.effect_params.get('iris_last_snap', -9.0) >= IRIS['snap_refractory']:
                self.effect_params['iris_last_snap'] = t
                snap = True
            self.effect_params['iris_spark_until'] = t + iris_spark_window(
                self.effect_params.get('iris_rng') or random, IRIS['wave_variety'])
            self.effect_params['iris_kick_boost'] = ks
            avg = self.effect_params.get('iris_kick_avg', 0.0)
            self.effect_params['iris_kick_avg'] = avg + (ks - avg) * 0.15
            # Drop: sehr harter Schlag nach laenger anliegender Energie —
            # der Strip zuendet denselben Blinder-Moment wie die Seite.
            if ks >= IRIS['drop_ks'] and avg >= IRIS['drop_avg'] \
                    and t - self.effect_params.get('iris_drop_at', -1e9) > IRIS['drop_cooldown']:
                self.effect_params['iris_drop_at'] = t
                # Drop = Preset desselben Blinder-Schedulers wie die Events.
                sp = _sparkle_spots(IRIS['drop_spots'])
                self.effect_params['iris_blinder'] = {
                    't0': t,
                    'win': ((0.0, 0.07, 1.0), (0.13, 0.22, 1.0), (0.30, 0.40, 0.7)),
                    'spots': (sp, sp, sp)}
            waves = self.effect_params['iris_waves']
            wv = iris_wave_spawn(self.effect_params.get('iris_rng') or random,
                                 ks, IRIS['wave_variety'])
            wv['born'] = t
            waves.append(wv)
            if len(waves) > 3:
                waves.pop(0)

        # ── Weiss-Event-Intake (2026-08-09): double/roll/accent von disco ──
        # Weiss ist Interpunktion: der Vollflaechen-Blinder feuert nur noch
        # auf erkannte Rhythmus-Events (Seiten-Paritaet; "keep the strobe
        # off until the music earns it"). Ein laufender Plan — insbesondere
        # der Drop — gewinnt: Events sind verderblich wie Kicks, ein spaeter
        # Blinder ist schlimmer als keiner.
        evq = self.effect_params.get('iris_events')
        while evq:
            try:
                ev = evq.pop(0)
            except IndexError:
                break
            if self.effect_params.get('iris_blinder') is not None:
                continue
            g = ev.get('gap', 0.16)
            m = ev.get('n', 2)
            kind = ev.get('kind')
            inten = float(ev.get('intensity', 1.0) or 1.0)
            dens = float(ev.get('density', 1.0) or 1.0)
            dur = float(ev.get('dur', 0.0) or 0.0)
            # L6-Varianten: eigener Plan-Typ, gleiche Scheduler-Mechanik
            if kind == 'meteor':
                # W2: rasender Weiss-Kopf mit Schweif. Der Plan traegt ALLES
                # vorberechnet (Dauern, Exit-Zeiten) — der Malpfad ist reine
                # Funktion von t. mode='duck': erste Plan-Art, die das Rot
                # NICHT abschaltet, sondern gedimmt weiterlaufen laesst.
                if not IRIS['meteor_enabled']:
                    continue
                rng = self.effect_params.get('iris_rng') or random
                n_px = self.strip.numPixels()
                sign = 1 if ev.get('dir', 1) >= 0 else -1
                count = max(1, min(int(IRIS['meteor_max_concurrent']),
                                   int(ev.get('n', 1) or 1)))
                profile = IRIS['meteor_profile']
                pre = IRIS['meteor_pre_dip_s']
                v_req = float(ev.get('v', 0.0) or 0.0)
                meteors, first_exit, flight_end = [], None, 0.0
                for k in range(count):
                    v0 = (max(IRIS['meteor_v_min'],
                              min(IRIS['meteor_v_max'], v_req))
                          if v_req > 0.0 else
                          rng.uniform(IRIS['meteor_v_min'], IRIS['meteor_v_max']))
                    delay = 0.0 if k == 0 else rng.uniform(0.08, 0.24)
                    efold = v0 * IRIS['meteor_trail_s']
                    # bis auch der SICHTBARE Schweif (ln(1/cut) e-Faltungen)
                    # den Strip verlassen hat
                    dist = n_px + efold * math.log(1.0 / IRIS['meteor_tail_cut']) + 12.0
                    dur = iris_meteor_dur(dist, v0, profile)
                    exit_t = iris_meteor_time_for(n_px + 6.0, v0, dur, profile)
                    meteors.append({
                        'v0': v0, 'dur': dur, 'delay': delay, 'sign': sign,
                        'start': -3.0 if sign > 0 else n_px + 3.0,
                        'efold': efold, 'seed': k + 1,
                        'gain': inten * rng.uniform(0.8, 1.0),
                        'last_pos': None})
                    exit_abs = pre + delay + exit_t
                    first_exit = exit_abs if first_exit is None else min(first_exit, exit_abs)
                    flight_end = max(flight_end, pre + delay + dur)
                plan_end = flight_end + IRIS['meteor_recover_s']
                sparks_fx = []
                if IRIS['stardust_enabled'] and IRIS['meteor_sparks']:
                    # Funkenflug: Sparkles entlang der Bahn, geboren kurz
                    # NACH dem Durchflug des Kopfs (40-120 ms Nachgluehen).
                    for _ in range(int(IRIS['meteor_spark_count'])):
                        m_ref = meteors[rng.randrange(len(meteors))]
                        x = rng.uniform(0.0, float(n_px))
                        travel = (x - m_ref['start']) * m_ref['sign']
                        t_pass = iris_meteor_time_for(
                            travel, m_ref['v0'], m_ref['dur'], profile)
                        birth = (pre + m_ref['delay'] + t_pass
                                 + rng.uniform(0.04, 0.12))
                        life = max(0.06, rng.uniform(0.08, 0.25))
                        peak = (0.3 + 0.7 * iris_render.powerlaw_brightness(
                            rng.random(), IRIS['stardust_powerlaw_k']))
                        sparks_fx.append({
                            'pos': min(float(n_px) - 0.01, max(0.0, x + rng.uniform(-3.0, 3.0))),
                            'birth': birth, 'life': life, 'peak': peak,
                            'rgb': iris_render.temp_to_rgb(
                                rng.uniform(3800.0, 7000.0))})
                        plan_end = max(plan_end, birth + life + 0.05)
                self.effect_params['iris_blinder'] = {
                    't0': t, 'type': 'meteor', 'mode': 'duck',
                    'win': ((0.0, plan_end, 1.0),),
                    'pre': pre, 'flight_end': flight_end,
                    'impact_at': first_exit if IRIS['meteor_impact'] else None,
                    'launch_at': pre if IRIS['meteor_launch'] else None,
                    'meteors': meteors, 'sparks_fx': sparks_fx}
                print(f"warn_event angenommen: meteor n={count} "
                      f"v={'/'.join(str(int(m['v0'])) for m in meteors)} "
                      f"dir={sign} dauer={flight_end:.2f}s "
                      f"funken={len(sparks_fx)}", flush=True)
                continue
            if kind == 'stardust':
                # W3: Sternenstaub-Burst — Partikel komplett vorgeneriert
                # (deterministisch aus iris_rng): Blue-Noise-Positionen,
                # Geburt ueber die Burst-Dauer verteilt, Leben 40-250 ms,
                # Peak nach Potenzgesetz, Farbtemperatur gestreut.
                if not IRIS['stardust_enabled']:
                    continue
                rng = self.effect_params.get('iris_rng') or random
                n_px = self.strip.numPixels()
                sd_dur = dur or 0.7
                count = max(6, min(int(IRIS['stardust_max_particles']),
                                   int(80 * dens * (sd_dur / 0.7))))
                positions = iris_render.blue_noise_positions(
                    rng, count, n_px, IRIS['stardust_min_dist'])
                l_min = IRIS['stardust_life_min_ms'] / 1000.0
                l_max = max(l_min, IRIS['stardust_life_max_ms'] / 1000.0)
                parts, plan_end = [], 0.0
                for p in positions:
                    birth = rng.uniform(0.0, sd_dur)
                    life = max(0.06, rng.uniform(l_min, l_max))  # >= 3 Frames (50 fps)
                    peak = ((0.35 + 0.65 * iris_render.powerlaw_brightness(
                        rng.random(), IRIS['stardust_powerlaw_k'])) * inten)
                    parts.append({
                        'pos': p, 'birth': birth, 'life': life, 'peak': peak,
                        'rgb': iris_render.temp_to_rgb(rng.uniform(
                            IRIS['stardust_temp_min'], IRIS['stardust_temp_max']))})
                    plan_end = max(plan_end, birth + life)
                self.effect_params['iris_blinder'] = {
                    't0': t, 'type': 'stardust',
                    'win': ((0.0, plan_end, inten),),
                    'parts': parts}
                print(f"warn_event angenommen: stardust teilchen={len(parts)} "
                      f"dauer={plan_end:.2f}s", flush=True)
                continue
            if kind == 'sweep':
                self.effect_params['iris_blinder'] = {
                    't0': t, 'type': 'sweep',
                    'win': ((0.0, dur or 0.7, inten),),
                    'origin': float(ev.get('origin', 0.5) or 0.5),
                    'dir': 1 if ev.get('dir', 1) >= 0 else -1}
                print(f"warn_event angenommen: sweep dur={dur or 0.7:.2f}s "
                      f"origin={self.effect_params['iris_blinder']['origin']:.2f} "
                      f"dir={self.effect_params['iris_blinder']['dir']}", flush=True)
                continue
            if kind == 'shimmer':
                self.effect_params['iris_blinder'] = {
                    't0': t, 'type': 'shimmer',
                    'win': ((0.0, dur or 0.7, inten),),
                    'density': dens}
                print(f"warn_event angenommen: shimmer dur={dur or 0.7:.2f}s "
                      f"density={dens:.2f}", flush=True)
                continue
            if kind == 'burst':
                sp_b = _sparkle_spots(max(4, int(IRIS['accent_spots'] * dens)))
                self.effect_params['iris_blinder'] = {
                    't0': t,
                    'win': ((0.0, dur or IRIS['accent_pulse'], inten),),
                    'spots': (sp_b,)}
                print(f"warn_event angenommen: burst leds={len(sp_b)}", flush=True)
                continue
            if kind == 'echo':
                d_p = dur or IRIS['double_pulse']
                sp = _sparkle_spots(max(4, int(IRIS['double_spots'] * dens)))
                self.effect_params['iris_blinder'] = {
                    't0': t,
                    'win': ((0.0, d_p, inten),
                            (g, g + d_p, inten * IRIS['double_gain2'])),
                    'spots': (sp, sp)}
                print(f"warn_event angenommen: echo leds={len(sp)} "
                      f"gap={g * 1000:.0f}ms", flush=True)
                continue
            if kind == 'double':
                # Zwei Schlaege im ECHT gemessenen Kick-Abstand — das Licht
                # echot den Rhythmus. ZWEIMAL DIESELBEN Stellen: das Echo.
                d_p = IRIS['double_pulse']
                win = ((0.0, d_p, 1.0), (g, g + d_p, IRIS['double_gain2']))
                sp = _sparkle_spots(IRIS['double_spots'])
                spots = (sp, sp)
            elif kind == 'roll':
                # Stakkato im Roll-Tempo, abklingend — je Puls NEUE Stellen
                # (wandernder Glitzer), nie unter halbe Kraft.
                win = tuple((i * g, i * g + IRIS['roll_pulse'],
                             max(IRIS['roll_gain_floor'], 1.0 - i * IRIS['roll_decay_per']))
                            for i in range(m))
                spots = tuple(_sparkle_spots(IRIS['roll_spots']) for _ in win)
            else:
                win = ((0.0, IRIS['accent_pulse'], 1.0),)   # accent: ein Einschlag
                spots = (_sparkle_spots(IRIS['accent_spots']),)
            print(f"warn_event angenommen: {kind} pulse={len(win)} "
                  f"leds={sum(len(x) for x in spots)}", flush=True)
            self.effect_params['iris_blinder'] = {'t0': t, 'win': win,
                                                  'spots': spots}

        # Tempo lock: the square's period IS the measured beat interval, so ON
        # 65 % / DARK 35 % hold for every REAL beat at any tempo. The original
        # snap kept the fixed 0.3575 s ON window and re-lit it per kick — above
        # ~160 BPM (or any onset burst) the dark phase hit zero and the strip
        # latched solid crimson. Stale (>1.6 s without kicks) → the tagged
        # 0.55 s free-run takes over: fallback IS the tag.
        seed = self.effect_params.get('iris_bpm_period')
        ema = self.effect_params.get('iris_beat_ema')
        lk = self.effect_params.get('iris_last_kick')
        freerun_now = not (lk is not None and t - lk <= IRIS['kick_stale']
                           and (seed or ema is not None))
        if not freerun_now:
            iris_period = max(IRIS['period_min'], min(IRIS['period_max'], seed if seed else ema))
        else:
            # L2: Freilauf atmet (Random-Walk ±freerun_jitter statt Metronom);
            # der Faktor wird am Perioden-Wrap weitergewuerfelt.
            iris_period = IRIS['period_freerun'] \
                * self.effect_params.get('iris_freerun_f', 1.0)
        self.effect_params['iris_period_eff'] = iris_period
        if snap and t >= 0.21:
            # u == 0 right now → rising edge ON the beat.
            self.effect_params['iris_ph'] = (t - 0.21) % iris_period

        # CSS peak rgba(255,70,55) — full punch, flat strip (no radial soft)
        hr, hg, hb = 255, 70, 55

        # ── Blinder-Scheduler: Vollflaechen-Weiss als Fensterplan ──
        # Volles Warmweiss bei 600 LEDs waeren ~33 A — jeder Blinder faehrt
        # bei 55 % Gain und bleibt in der Stromklasse des Vollrot-Blitzes
        # (Stromspitzen druecken die 5-V-Schiene und verschaerfen genau die
        # Bit-Slips, gegen die der Heartbeat kaempft). Zwischen den Fenstern
        # erzwingt der Plan SCHWARZ — die harte Dunkelphase zwischen den
        # Peaks ist die Blinder-Signatur (dieselbe Kurve, die auf der Seite
        # per Opacity-Sampling gemessen wurde: Peak, dunkel, Peak).
        bl = self.effect_params.get('iris_blinder')
        blinder = None    # None = kein Plan; sonst (an: bool, gain: float)
        blinder_wi = 0    # Index des aktiven Fensters -> dessen Spot-Liste
        blinder_decay = None   # (fenster_index, faktor 0..1) im Nachglimmen
        BL_DECAY_S = IRIS['sparkle_decay']   # Funken reissen nicht ab, sie verglimmen
        if bl is not None:
            bl_t = t - bl['t0']
            if bl_t < bl['win'][-1][1] + BL_DECAY_S:
                blinder = (False, 0.0)
                for wi, (a, b_, g_) in enumerate(bl['win']):
                    if a <= bl_t < b_:
                        blinder = (True, g_)
                        blinder_wi = wi
                        break
                if not blinder[0]:
                    # Nachglimmen des juengsten vergangenen Pulses
                    for wi in range(len(bl['win']) - 1, -1, -1):
                        a, b_, g_ = bl['win'][wi]
                        if bl_t >= b_ and bl_t - b_ < BL_DECAY_S:
                            f = 1.0 - (bl_t - b_) / BL_DECAY_S
                            blinder_decay = (wi, g_ * f * f)
                            break
            else:
                self.effect_params['iris_blinder'] = None
        blind_on = blinder is not None   # Plan aktiv (inkl. Pausen + Glimmen)
        # W2: Meteor-Plaene DUCKEN das Rot statt es abzuschalten (erste
        # Plan-Art mit mode='duck'). duck_f traegt die LUT-Kompensation:
        # Blinder-Frames laufen LUT-neutral (Weiss braucht die absolute
        # Stromklasse), also muss die Basis um led_brightness/255 herunter —
        # sonst spraenge ihre Helligkeit an den Plan-Grenzen.
        meteor_on = blind_on and bl.get('type') == 'meteor'
        duck_f = 1.0
        if meteor_on:
            duck_f = iris_meteor_duck(
                bl_t, bl['pre'], bl['flight_end'],
                IRIS['meteor_duck'], IRIS['meteor_recover_s']) \
                * (self.strip_lut_default / 255.0)

        # ── Engage: two hard pulses (Aufleuchten) ──
        # ON 70ms · OFF 60ms · ON 80ms, then sustain
        red_env = 1.0
        if t < 0.21:
            ew = self.effect_params.get('iris_engage_win') or (0.07, 0.13)
            lit = not (ew[0] <= t < ew[1])
        else:
            # Atmen statt Rechteck (2026-08-11): Periode bleibt tempo-gelockt
            # und der Attack sitzt AUF dem Beat (Kick-Snap setzt u=0) — aber
            # statt 65 % AN / 35 % SCHWARZ verglimmt der Schlag ueber die
            # Periode auf einen Glut-Boden (iris_red_envelope).
            u = ((t - 0.21 - self.effect_params.get('iris_ph', 0.0)) / iris_period) % 1.0
            lit = True
            red_env = iris_red_envelope(u)
            # L2: Peak folgt der Kick-Staerke — ein sanfter Schlag blueht
            # flacher auf, der Glut-Boden bleibt. Im Freilauf (kein frischer
            # Kick) neutraler Mittelwert statt eingefrorenem letzten Kick.
            punch = IRIS['red_punch']
            if punch > 0.0:
                ks = (float(self.effect_params.get('iris_kick_boost', 0.0) or 0.0)
                      if not freerun_now else 0.5)
                red_env = iris_scale_envelope(
                    red_env, iris_red_punch_peak(ks, punch), IRIS['red_floor'])
            prev_u = self.effect_params.get('iris_prev_u')
            self.effect_params['iris_prev_u'] = u
            if prev_u is not None and u < prev_u - 0.5:
                # Perioden-Wrap = Schlagmoment -> Funkenfenster (Freilauf;
                # echte Kicks armieren es ohnehin im Intake)
                self.effect_params['iris_spark_until'] = t + iris_spark_window(
                self.effect_params.get('iris_rng') or random, IRIS['wave_variety'])
                if freerun_now and IRIS['freerun_jitter'] > 0.0:
                    rng = self.effect_params.get('iris_rng') or random
                    self.effect_params['iris_freerun_f'] = iris_freerun_walk(
                        self.effect_params.get('iris_freerun_f', 1.0),
                        IRIS['freerun_jitter'], rng.uniform(-1.0, 1.0))

        if blinder is not None and not meteor_on:
            # Klassische Blinder: Rot AUS in Dunkelfenstern. Meteor-Plaene
            # lassen lit stehen — ihre Basis laeuft geduckt weiter.
            lit = blinder[0]
        last = self.effect_params.get('iris_lit')
        if lit and last is not True:
            # Rising edge → arm a ~55 ms white-spark window
            self.effect_params['iris_spark_until'] = t + iris_spark_window(
                self.effect_params.get('iris_rng') or random, IRIS['wave_variety'])
        spark = bool(lit and t < float(self.effect_params.get('iris_spark_until') or 0))
        last_spark = self.effect_params.get('iris_sparking')

        # Live shockwaves force full repaints (paced ~50 fps ≈ the 18 ms
        # shift-out floor); without waves the tagged edge-only rewrite stays.
        waves = self.effect_params.get('iris_waves') or []
        if waves:
            now_m = mono()
            waves = [w for w in waves
                     if (t - w['born']) * iris_wave_speed(w)
                     < iris_wave_reach(w, self.strip.numPixels())]
            self.effect_params['iris_waves'] = waves
            if not waves and last is lit and last_spark is spark:
                return
            if waves and now_m < self.effect_params.get('iris_next_paint', 0.0) \
                    and last is lit and last_spark is spark:
                return
            self.effect_params['iris_next_paint'] = now_m + 0.02
        elif self.effect_params.get('iris_blinder') is not None:
            # Blinder-Plan aktiv: KONTINUIERLICH neu senden — der 20-ms-
            # Schreibtakt unten paced (Dunkelfenster laufen ueber clear(),
            # das ohnehin doppelt schreibt). Ein Blinder-Puls war sonst EINE
            # einzige Transmission (Flanken-Optimierung + 80-ms-Heartbeat
            # greifen erst im Haltefenster), und ein GRB-Bit-Slip in genau
            # dieser Uebertragung stand die volle Pulsdauer als GRUEN-Artefakt
            # ("statt weissem Blitzen gruenlich", Feldbefund 2026-08-09 —
            # der Vollflaechen-Wechsel ist die haerteste Stromtransiente, und
            # die Y-Kette verschaerft die marginale 3,3-V-Leitung). Slips sind
            # per-Transmission, nicht klebrig: der 20-ms-Refresh heilt sie,
            # bevor das Auge sie als Farbe liest.
            pass
        elif t >= 0.21:
            # Atmender Rot-Fade (2026-08-11): kontinuierlich neu zeichnen —
            # der 20-ms-Schreibtakt unten paced (~50 fps, dieselbe Klasse wie
            # die Wellen; der A/B-Test hat schnelles Rot-Neusenden als sauber
            # bewiesen). Der 80-ms-Heartbeat wuerde den Verglimm-Verlauf in
            # sichtbare Stufen zerhacken; seine Slip-Heilung uebernimmt der
            # Dauertakt gleich mit.
            pass
        elif last is lit and last_spark is spark:
            # Heartbeat statt reiner Flanken-Optimierung (2026-08-06): ein
            # GRB-Bit-Slip (verrutschtes Rot = GRUEN) im zuletzt gesendeten
            # Frame stand sonst das GANZE Haltefenster sichtbar — die Flanken-
            # Optimierung hielt die Korruption fest. Uebertragungsfehler sind
            # per-Transmission, nicht klebrig: alle 0.08 s neu senden heilt
            # jeden Slip binnen 80 ms, kostet ~15 % Wire-Duty (18 ms/Frame).
            now_hb = mono()
            if now_hb < self.effect_params.get('iris_next_heal', 0.0):
                return
            self.effect_params['iris_next_heal'] = now_hb + 0.08
        self.effect_params['iris_lit'] = lit
        self.effect_params['iris_sparking'] = spark

        # EIN Schreibtakt fuer alle Pfade: 20 ms Boden (= die 18-ms-Drahtzeit).
        # Schneller zu wollen erzeugt nur EBUSY-Drops — und ein verworfener
        # Frame ist ein 20-ms-Fenster, in dem ein Slip-Fragment stehen bleibt.
        now_w = mono()
        if now_w - self.effect_params.get('iris_last_write', 0.0) < 0.02:
            return
        self.effect_params['iris_last_write'] = now_w

        scale = max(0.0, min(1.0, self.brightness / 255.0))
        n = self.strip.numPixels()

        # Strip-LUT pro Frame setzen statt Zustand zu merken (selbstheilend):
        # Blinder-ON-Frames fahren mit neutraler LUT (voller Payload), alles
        # andere mit der konfigurierten Anlagen-Helligkeit.
        if hasattr(self.strip, 'setBrightness'):
            want = 255 if blind_on else int(getattr(self, 'strip_lut_default', 255))
            if self.strip.getBrightness() != want:
                self.strip.setBrightness(want)

        if not lit and not waves and not blind_on:
            # force: auf Flanken ist _cleared ohnehin False (identisch), aber
            # der Heartbeat muss auch SCHWARZ neu beweisen koennen — ein heller
            # Slip stand sonst das ganze Dunkelfenster (der _cleared-Guard
            # blockte genau die Heilung, die der Heartbeat bringen soll).
            self.clear(force=True)
            return

        glow_tbl = None
        if t >= 0.21 and lit and (not blind_on or meteor_on):
            # Schattenzonen-Lebenszyklus: abgelaufene ersetzen (an neuer,
            # zufaelliger Position mit neuer Breite/Tiefe/Drift) — der Bestand
            # bleibt bei IRIS['shadow_count'], gestaffelt durch zufaellige Leben.
            pockets = self.effect_params.setdefault('iris_shadows', [])
            # 0 <= age: Zonen aus einer aelteren Zeitrechnung (iris_t0 wird je
            # Warn-Flanke resettet) waeren mit negativem Alter unsichtbare
            # Zombies, die nie sterben und den Nachschub blockieren — weg damit.
            pockets[:] = [pk for pk in pockets
                          if 0.0 <= t - pk['born'] < pk['life']]
            rng = self.effect_params.get('iris_rng') or random
            fresh = not pockets
            while len(pockets) < IRIS['shadow_count']:
                life = rng.uniform(IRIS['shadow_life_min'], IRIS['shadow_life_max'])
                # Initial-Kohorte rueckdatiert = sofort mitten im Leben und
                # damit SOFORT sichtbar — die Warn-Flanke flattert bei Musik um
                # die Schwelle, eine 1-s-Einblendzeit je Engage saehe man nie.
                born = t - rng.uniform(IRIS['shadow_ramp'], life * 0.6) if fresh else t
                pockets.append({
                    'pos': rng.uniform(0, n),
                    'width': rng.uniform(IRIS['shadow_w_min'], IRIS['shadow_w_max']),
                    'depth': rng.uniform(IRIS['shadow_depth_min'], IRIS['shadow_depth_max']),
                    'life': life,
                    'vel': rng.uniform(-IRIS['shadow_vel_max'], IRIS['shadow_vel_max']),
                    'born': born,
                })
            # Wander-Glut (feine Grundtextur) x Schattenzonen, in 4er-Bloecken
            glow_tbl = [iris_glow_factor(b + 1.5, t)
                        * iris_shadow_field(b + 1.5, pockets, t)
                        for b in range(0, n, 4)]
        # duck_f ist 1.0 ausserhalb von Meteor-Plaenen (x*1.0 == x, bit-exakt).
        red_env *= duck_f
        c = Color(int(hr * scale * red_env), int(hg * scale * red_env), int(hb * scale * red_env))
        dark = Color(0, 0, 0)
        # SPARKLE-Blinder (Nutzerentscheid 2026-08-10, ersetzt das
        # Vollflaechen-Flutlicht): waehrend eines Event-Pulses geht das ROT AUS
        # und an wenigen zufaelligen Stellen blitzen helle Funken-Cluster.
        # Vorgeschichte in den Geraete-A/B-Tests: (a) schnelles Rot-Neusenden
        # sauber (Datenleitung unschuldig), (b) stehendes Vollweiss driftet
        # gruenlich, hinten zuerst (Einspeisung nur vorn, Blau-Die stirbt
        # zuerst), (c) die 5-m-Segmente rendern Weiss verschieden (Binning).
        # Sparse kann diese Verkabelung dagegen ehrlich: wenige LEDs = winzige
        # Last -> keine Drift, hohe Duty -> Binning ertrinkt, fast echtes
        # Warmweiss; der Schwarz-Kontrast macht den Blitz. Vollflaechen-
        # Kaltweiss braucht beidseitige Stromeinspeisung (Hardware).
        base = dark if (blind_on and not meteor_on) else (c if lit else dark)
        if glow_tbl is not None:
            # Rot atmet zeitlich (red_env) UND wandert raeumlich (glow_tbl)
            sc = scale * red_env
            for i in range(n):
                f = glow_tbl[i >> 2] * sc
                self.strip.setPixelColor(i, Color(int(hr * f), int(hg * f), int(hb * f)))
        elif hasattr(self.strip, 'fill') and not waves:
            self.strip.fill(base)
        else:
            for i in range(n):
                self.strip.setPixelColor(i, base)

        # ── Shockwaves: white-hot front racing centre → both ends ──
        # Replace-blend toward warm white keeps per-LED current ≈ crimson+Δ;
        # the front burns brightest young and cools as it travels.
        if waves and not blind_on:
            # Zweizoniger Wellenkopf (2026-08-06): weissgluehender KERN in einem
            # heissroten HALO — vorher ein einzelner Blend, der auf halber
            # Strecke als blasses Rosa las (genau die "Fragmente"-Optik).
            # Replace-Blend bleibt: Strombudget ≈ Vollrot.
            # Glut statt Weiss (2026-08-09): Gold-Bernstein-Kern im heissroten
            # Halo — Weiss gehoert exklusiv den Event-Blindern + Drop.
            # Gruen-Die-kompensiert (2026-08-10): G/B deutlich unter dem naiven
            # Gold, sonst kippt der Kern nach der Kernel-Gamma ins Gelbgruene
            # (gruene Die ~2x Luminanz je Duty — iris_wash.WHITE_POINT-Physik).
            wr, wg, wb = 255, 105, 25    # ember core, tief orange — bin-streuungsfest
            xr, xg, xb = 255, 110, 80    # hot red halo
            half = n / 2.0
            for w in waves:
                age = t - w['born']
                v = iris_wave_speed(w)                # LED/s — harder kicks race faster
                dist = age * v
                width = w.get('width') or (12.0 + 24.0 * w['s'])
                # L3: Ursprung + Richtung je Welle (Legacy: Mitte, beidseitig)
                centre = w.get('of', 0.5) * n
                direction = w.get('dir', 0)
                cool = max(0.0, 1.0 - (dist / max(1.0, half)) * 0.45)
                lo = max(0, int(centre - (dist if direction <= 0 else 0) - width * 3))
                hi = min(n - 1, int(centre + (dist if direction >= 0 else 0) + width * 3))
                cw = width * 0.45
                for i in range(lo, hi + 1):
                    arm = i - centre
                    if direction > 0 and arm < 0:
                        continue
                    if direction < 0 and arm > 0:
                        continue
                    d = abs(abs(arm) - dist)
                    if d > width * 3:
                        continue
                    halo = cool * w['s'] * (2.718281828 ** (-(d * d) / (2.0 * width * width)))
                    if halo <= 0.02:
                        continue
                    core = cool * w['s'] * (2.718281828 ** (-(d * d) / (2.0 * cw * cw)))
                    gf = red_env * (glow_tbl[i >> 2] if glow_tbl is not None else 1.0)
                    br, bg_, bb = (hr * gf, hg * gf, hb * gf) if lit else (0, 0, 0)
                    r_ = br + (xr - br) * halo
                    g_ = bg_ + (xg - bg_) * halo
                    b_ = bb + (xb - bb) * halo
                    if core > 0.02:
                        r_ += (wr - r_) * core
                        g_ += (wg - g_) * core
                        b_ += (wb - b_) * core
                    self.strip.setPixelColor(i, Color(
                        int(min(255, r_) * scale),
                        int(min(255, g_) * scale),
                        int(min(255, b_) * scale)))

        if spark and n > 0 and not blind_on:
            # Glut statt Weiss (2026-08-09, Nutzerentscheid): Weiss gehoert
            # exklusiv den Event-Blindern + Drop — die Per-Kick-Funken sind
            # Bernstein wie die Glut-Blobs der Seite. Nebeneffekt: nochmal
            # weniger Spitzenstrom als das alte Warmweiss.
            # Gruen-Die-kompensiert (2026-08-10): 176er-G las sich nach der
            # Kernel-Gamma als Gelbgruen — 120/30 haelt die Funken klar orange.
            # Feinschliff 2026-08-10: bei den LUT-bedingten Mini-Duties (G~6)
            # kippten bin-streuende Einzel-LEDs ins Gelbgruene — G weiter runter,
            # B ganz raus (unterhalb 1 Duty-Schritt = reine Rauschquelle).
            w = Color(int(255 * scale), int(90 * scale), 0)
            # ~8% of strip (was ~12 LEDs); cap so crimson base stays visible
            k = min(n, min(80, max(24 if n >= 48 else 3, n // 12)))
            k = min(k, max(1, (n * 2) // 5))  # ≤40% white
            # Kick strength scales the shower; the tagged density is the floor.
            boost = float(self.effect_params.get('iris_kick_boost', 0.0) or 0.0)
            k = min(max(1, int(k * (1.0 + 0.6 * boost))), max(1, (n * 2) // 5))
            rng = random.Random(int(t0 * 1000) ^ int(t * 200))
            for i in rng.sample(range(n), k):
                self.strip.setPixelColor(i, w)

        # W3 Ambient-Glitzer (Phase-1-Entscheid: default AUS, 0.0 Sparkles/s):
        # sehr duenner Dauer-Sternenstaub UEBER dem atmenden Rot. Eigener,
        # kleiner Partikel-Pool (<= 12) mit denselben Huellkurven wie der
        # Burst; Zombie-Doktrin: negative Alter werden entsorgt.
        amb_rate = IRIS['stardust_ambient']
        if amb_rate > 0.0 and not blind_on and lit and t >= 0.21:
            amb = self.effect_params.setdefault('iris_ambient', [])
            amb[:] = [p for p in amb if 0.0 <= t - p['birth'] < p['life']]
            rng = self.effect_params.get('iris_rng') or random
            if len(amb) < 12 and rng.random() < amb_rate * 0.02:
                amb.append({
                    'pos': rng.uniform(0.0, float(n)),
                    'birth': t,
                    'life': max(0.06, rng.uniform(0.08, 0.3)),
                    'peak': 0.3 + 0.7 * iris_render.powerlaw_brightness(
                        rng.random(), IRIS['stardust_powerlaw_k']),
                    'rgb': iris_render.temp_to_rgb(rng.uniform(
                        IRIS['stardust_temp_min'], IRIS['stardust_temp_max']))})
            for pt in amb:
                env = iris_render.spark_envelope(
                    t - pt['birth'], pt['life'], IRIS['stardust_attack'])
                if env <= 0.0:
                    continue
                # BEWUSST LUT-gedimmt: Ambient-Frames laufen mit Strip-LUT
                # (kein Blinder-Frame) — eine Kompensation nach OBEN gibt es
                # nicht (die Unsichtbar-Weiss-Lektion). Ergebnis ist ein
                # leises Glimmen ueber dem Rot, kein Blinder-Weiss — genau
                # die Rolle des Dauer-Layers.
                w_a = pt['peak'] * env * IRIS['stardust_gain']
                pr, pg, pb = pt['rgb']
                for i, aa in iris_render.point_aa(pt['pos'], n):
                    self._px_mix(i, pr, pg, pb, min(1.0, w_a * aa))
        if blind_on and bl.get('type') == 'meteor':
            # W2 METEOR: Kopf als Line-Integral (die im Frame ueberstrichene
            # Strecke — lueckenlos bei jeder Geschwindigkeit), Gauss-Bloom um
            # die Kopfposition, Schweif exponentiell im LINEAREN Licht
            # (perceptual-Encode) mit Glut-Koernung + Temperatur-Gradient.
            # Alles Replace-Blend auf die GEDUCKTE Basis (kein Clipping).
            if 'grad' not in bl:
                # Temperatur-Gradient einmal je Plan vorberechnen (32 Stufen)
                h_t, t_t = IRIS['meteor_head_temp'], IRIS['meteor_tail_temp']
                bl['grad'] = [iris_render.temp_to_rgb(h_t + (t_t - h_t) * k / 31.0)
                              for k in range(32)]
            grad = bl['grad']
            gj = IRIS['meteor_jitter']
            profile = IRIS['meteor_profile']
            mt0 = bl['pre']

            _mix = self._px_mix

            hr_w, hg_w, hb_w = grad[0]
            for m in bl['meteors']:
                tm = bl_t - mt0 - m['delay']
                if tm <= 0.0:
                    continue
                pos = m['start'] + m['sign'] * iris_meteor_pos(
                    tm, m['v0'], m['dur'], profile)
                prev = m['last_pos'] if m['last_pos'] is not None else pos
                m['last_pos'] = pos
                g = IRIS['meteor_head_gain'] * m['gain']
                # Kopf-Strecke des Frames (Motion-Blur, Randpixel anteilig)
                for i, wgt in iris_render.line_coverage(prev, pos, n):
                    _mix(i, hr_w, hg_w, hb_w, g * min(1.0, wgt))
                # Bloom: Streulicht um die aktuelle Kopfposition (sigma 1.2)
                ci = int(pos)
                for i in range(max(0, ci - 3), min(n - 1, ci + 3) + 1):
                    d = (i + 0.5) - pos
                    _mix(i, hr_w, hg_w, hb_w,
                         g * math.exp(-(d * d) / 2.88))
                # Schweif hinter dem Kopf: e-Faltung = v*tau LEDs. Der
                # Schnitt (meteor_tail_cut) NORMALISIERT das Restlicht auf
                # echtes Null — ohne ihn hielt der Gamma-Encode das ferne
                # Ende auf ~17 % Duty ueber hunderte LEDs: der flaechige
                # Niedrig-Duty-Teppich, der gelbgruen kippt (2026-08-12).
                efold = m['efold']
                cut = IRIS['meteor_tail_cut']
                span = int(min(n, efold * math.log(1.0 / cut) + 2.0))
                for k_px in range(1, span + 1):
                    ip = ci - m['sign'] * k_px
                    # Kopf schon draussen: der Schweif reicht noch HEREIN —
                    # ueberspringen, nicht abbrechen (sonst friert der
                    # sichtbare Rest-Schweif beim Kopf-Austritt ein).
                    if m['sign'] > 0 and ip >= n:
                        continue
                    if m['sign'] < 0 and ip < 0:
                        continue
                    if ip < 0 or ip >= n:
                        break     # durchs hintere Ende hinausgelaufen
                    d = abs(pos - (ip + 0.5))
                    b_lin = math.exp(-d / efold)
                    if b_lin < cut:
                        break
                    jit = 1.0 + gj * iris_meteor_jitter(ip, m['seed'])
                    gi = min(31, int(31.0 * min(1.0, d / (2.5 * efold))))
                    tr, tg, tb = grad[gi]
                    _mix(ip, tr, tg, tb,
                         g * iris_render.perceptual(
                             (b_lin - cut) / (1.0 - cut)) * jit)
            # Impact: kurzer Vollflaechen-Flash (gain-gedeckelt, Stroboskop-
            # Bremse via geteiltem iris_last_flash) + Rueckwelle vom Ende.
            fl_s = IRIS['flash_max_ms'] / 1000.0
            imp = bl.get('impact_at')
            if imp is not None and bl_t >= imp:
                ft = bl_t - imp
                sign0 = bl['meteors'][0]['sign']
                if ft < 0.35:
                    # Rueckwelle: reflektierter Kurz-Schweif, ~25 % Amplitude
                    end_pos = float(n) if sign0 > 0 else 0.0
                    rw_v = bl['meteors'][0]['v0'] * 0.5
                    rw_pos = end_pos - sign0 * rw_v * ft
                    amp = 0.25 * (1.0 - ft / 0.35)
                    ri = int(rw_pos)
                    for i in range(max(0, ri - 12), min(n - 1, ri + 12) + 1):
                        d = (i + 0.5) - rw_pos
                        _mix(i, hr_w, hg_w, hb_w,
                             amp * math.exp(-(d * d) / 32.0))
                if ft < fl_s:
                    if 'impact_fired' not in bl:
                        last_fl = self.effect_params.get('iris_last_flash', -1e9)
                        bl['impact_fired'] = \
                            (t - last_fl) >= 1.0 / IRIS['max_flash_rate_hz']
                        if bl['impact_fired']:
                            self.effect_params['iris_last_flash'] = t
                    if bl['impact_fired']:
                        fg = IRIS['flash_gain'] * (1.0 - ft / fl_s)
                        for i in range(n):
                            _mix(i, 255.0, 190.0, 120.0, fg)
            lau = bl.get('launch_at')
            if lau is not None and lau <= bl_t < lau + fl_s:
                if 'launch_fired' not in bl:
                    last_fl = self.effect_params.get('iris_last_flash', -1e9)
                    bl['launch_fired'] = \
                        (t - last_fl) >= 1.0 / IRIS['max_flash_rate_hz']
                    if bl['launch_fired']:
                        self.effect_params['iris_last_flash'] = t
                if bl['launch_fired']:
                    ft = bl_t - lau
                    fg = IRIS['flash_gain'] * 0.7 * (1.0 - ft / fl_s)
                    sign0 = bl['meteors'][0]['sign']
                    for i in range(n):
                        dist_in = i if sign0 > 0 else (n - 1 - i)
                        w = fg * max(0.0, 1.0 - dist_in / (n * 0.5))
                        _mix(i, 255.0, 190.0, 120.0, w)
            # Funkenflug (W3): Nachgluehen entlang der Bahn — jedes Teilchen
            # mit eigener Attack/Decay-Huellkurve, Sub-Pixel-platziert.
            for pt in bl.get('sparks_fx') or ():
                env = iris_render.spark_envelope(
                    bl_t - pt['birth'], pt['life'], IRIS['stardust_attack'])
                if env <= 0.0:
                    continue
                w = pt['peak'] * env * IRIS['stardust_gain']
                pr, pg, pb = pt['rgb']
                for i, aa in iris_render.point_aa(pt['pos'], n):
                    _mix(i, pr, pg, pb, w * aa)
        elif blind_on and bl.get('type') == 'stardust':
            # W3 STARDUST: Sternenstaub auf Schwarz (klassischer Blinder:
            # Rot ist aus — der Kontrast macht das Funkeln). Partikel sind
            # vorgeneriert; hier laeuft nur die Huellkurven-Schleife.
            for pt in bl['parts']:
                env = iris_render.spark_envelope(
                    bl_t - pt['birth'], pt['life'], IRIS['stardust_attack'])
                if env <= 0.0:
                    continue
                w = pt['peak'] * env * IRIS['stardust_gain']
                pr, pg, pb = pt['rgb']
                for i, aa in iris_render.point_aa(pt['pos'], n):
                    self._px_mix(i, pr, pg, pb, w * aa)
        elif blind_on and bl.get('type') == 'sweep':
            # SWEEP (L6): ein warmweisser Lichtstreif rast von der
            # Startposition in eine Richtung — Gauss-Kopf wie die Welle,
            # aber auf SCHWARZ und in Blinder-Weiss. Im Nachglimmen steht
            # der Kopf am Ende der Strecke und verglimmt.
            if blinder[0]:
                gv = IRIS['blinder_gain'] * blinder[1]
                a0, b0, _g0 = bl['win'][0]
                prog = max(0.0, min(1.0, (bl_t - a0) / max(0.05, b0 - a0)))
            elif blinder_decay is not None:
                _wi, gv = blinder_decay
                prog = 1.0
            else:
                gv, prog = 0.0, 1.0
            if gv > 0.01:
                span = IRIS['sweep_span']
                centre = bl['origin'] * n + bl['dir'] * prog * span
                w = IRIS['sweep_width']
                lo_i = max(0, int(centre - 3 * w))
                hi_i = min(n - 1, int(centre + 3 * w))
                sr, sg, sb = IRIS['sparkle_r'], IRIS['sparkle_g'], IRIS['sparkle_b']
                for i in range(lo_i, hi_i + 1):
                    d = i - centre
                    v = gv * math.exp(-(d * d) / (2.0 * w * w))
                    if v > 0.02:
                        self.strip.setPixelColor(i, Color(int(sr * v), int(sg * v), int(sb * v)))
        elif blind_on and bl.get('type') == 'shimmer':
            # SHIMMER (L6): flirrendes Weiss — jede Neuzeichnung wuerfelt
            # neue Pixel (die 20-ms-Resends SIND das Flirren); im Nachglimmen
            # duennt es aus und verglimmt.
            rng = self.effect_params.get('iris_rng') or random
            if blinder[0]:
                gv = IRIS['shimmer_gain'] * IRIS['blinder_gain'] * blinder[1]
                frac = 1.0
            elif blinder_decay is not None:
                _wi, dgv = blinder_decay
                gv = IRIS['shimmer_gain'] * dgv
                frac = max(0.0, dgv)
            else:
                gv, frac = 0.0, 0.0
            if gv > 0.01:
                count = max(2, int(IRIS['shimmer_px'] * bl.get('density', 1.0) * frac))
                _wmax = int(IRIS.get('white_max_px', 0) or 0)
                if _wmax > 0:
                    count = min(count, _wmax)    # Weiss-Budget (Sparse-Klasse)
                sr, sg, sb = IRIS['sparkle_r'], IRIS['sparkle_g'], IRIS['sparkle_b']
                for i in rng.sample(range(n), min(n, count)):
                    v = gv * (0.5 + rng.random() * 0.5)
                    self.strip.setPixelColor(i, Color(int(sr * v), int(sg * v), int(sb * v)))
        elif blind_on:
            # Sparse -> hell: nahe Warmweiss ist hier erlaubt (winzige
            # Gesamtlast); die LUT ist im ganzen Plan neutralisiert. Aktives
            # Fenster malt voll, danach verglimmt der Puls (quadratischer
            # Abfall ueber BL_DECAY_S) — Funken sterben, sie schalten nicht.
            spots = bl.get('spots') or ((),)
            if blinder[0]:
                wi, gv = blinder_wi, IRIS['blinder_gain'] * blinder[1]
            elif blinder_decay is not None:
                wi, gv = blinder_decay
            else:
                wi, gv = 0, 0.0
            if gv > 0.01:
                if not bl.get('dbg'):
                    bl['dbg'] = True
                    print(f"sparkle-frame gemalt: fenster={wi} "
                          f"leds={len(spots[min(wi, len(spots) - 1)])}", flush=True)
                for j, bri in spots[min(wi, len(spots) - 1)]:
                    v = gv * bri
                    self.strip.setPixelColor(j, Color(int(IRIS['sparkle_r'] * v), int(IRIS['sparkle_g'] * v), int(IRIS['sparkle_b'] * v)))
        self.strip.show()
        self._cleared = False

    def run_effect(self):
        if self._wash_fade_t0 is not None:
            # The release ramp outlives power=False so it can run down to black
            self._paint_wash_fade()
            return
        if not self.power:
            # One clear when off — don't hammer /dev/leds0 every frame. But
            # re-assert black every 2 s: a pixel that mis-latched during the
            # last transmission (or survived a dropped clear) holds its wrong
            # colour indefinitely, and at standstill nothing else would ever
            # overwrite it. One 18 ms frame every 2 s is free; stuck green/blue
            # pixels now heal within 2 s instead of never.
            if not self._cleared:
                self.clear(force=True)
            elif time.monotonic() - getattr(self, '_last_clear_ts', 0.0) > 2.0:
                self.clear(force=True)
            return
        
        effects = {
            'solid': self.effect_solid,
            'rainbow': self.effect_rainbow,
            'pulse': self.effect_pulse,
            'chase': self.effect_chase,
            'sparkle': self.effect_sparkle,
            'strobe': self.effect_strobe,
            'meteor': self.effect_meteor,
            'breathe': self.effect_breathe,
            'sinelon': self.effect_sinelon,
            'juggle': self.effect_juggle,
            'theater': self.effect_theater_chase_rainbow,
            'gradient': self.effect_gradient_fill,
            'fire': self.effect_fire,
            'iris_warn': self.effect_iris_warn
        }
        
        if self.current_effect in effects:
            effects[self.current_effect]()
            # Non-iris effects always leave the strip potentially lit
            if self.current_effect != 'iris_warn':
                self._cleared = False

    def start_effect_loop(self):
        def effect_loop():
            while self.running:
                try:
                    self.run_effect()
                    if self.current_effect == 'iris_warn':
                        sleep_time = 0.008  # ~125 Hz poll — edges land within ~8 ms
                    else:
                        sleep_time = max(0.01, (101 - self.speed) / 1000.0)
                    # Interruptible sleep: API changes paint on the next wake
                    self._effect_wake.wait(timeout=sleep_time)
                    self._effect_wake.clear()
                except Exception as e:
                    print(f"Effect error: {e}")
                    time.sleep(0.05)

        if self.effect_thread and self.effect_thread.is_alive():
            return

        self.effect_thread = threading.Thread(target=effect_loop, daemon=True)
        self.effect_thread.start()

    def get_status(self):
        return {
            'power': self.power,
            'effect': self.current_effect,
            'brightness': self.brightness,
            'speed': self.speed,
            'color': {
                'r': self.color[0],
                'g': self.color[1],
                'b': self.color[2]
            },
            # Frames the kernel refused. Non-zero means we are writing into an
            # in-flight DMA transfer — the pacing is off, not the paint.
            'dropped_frames': getattr(self.strip, 'dropped_frames', 0) if self.strip else 0,
            # Entkopplung 2026-08-12: UI kann anzeigen, dass Iris den Strip
            # besitzt und Einstellungen erst nach dem Warn-Modus greifen.
            'strip_warn_mode': self.strip_warn_mode,
            'settings_deferred': self._pre_warn is not None and self.strip_warn_mode,
            'iris_beat_s': (round(self.effect_params['iris_period_eff'], 3)
                            if self.current_effect == 'iris_warn'
                            and self.effect_params.get('iris_period_eff') else None),
            'theater_rainbow': self.theater_rainbow,
            'led_count': self.strip.numPixels() if self.strip else 50,
            'pin': self.config['led_config']['pin']
        }

# Global controller instance
controller = LichtwerkWebController()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    return jsonify(controller.get_status())

@app.route('/api/power', methods=['POST'])
def set_power():
    data = request.get_json() or {}
    controller.power = bool(data.get('power', False))
    if not controller.power:
        controller.strip_warn_over = False
        # Explicit power-off also leaves Strip-Warn mode (disco will re-arm if needed)
        if data.get('clear_warn_mode', False):
            controller.strip_warn_mode = False
            controller._warn_restore()
        controller._iris_abort()
    controller.wake_effect()
    return jsonify({'status': 'ok', 'power': controller.power})


@app.route('/api/warn_gate', methods=['POST'])
def warn_gate():
    """Edge-triggered Strip-Warn gate — mirrors page body.over-iris.

    over=true  → wash in at the breathe peak, then the 1.8 s CSS breathe
    over=false → .55 s fade to black, matching the page's background transition
    """
    data = request.get_json() or {}
    over = bool(data.get('over', False))
    controller._warn_snapshot()
    controller.strip_warn_mode = True
    controller.strip_warn_over = over
    if over:
        controller.power = True
        controller.current_effect = 'iris_warn'
        controller.brightness = 255
        controller._wash_engage()
        try:
            controller.run_effect()   # first frame in-request, no wake latency
        except Exception as e:
            print(f"warn_gate on: {e}")
    else:
        # Under threshold: ramp down like the page instead of cutting to black.
        # The fade runs past power=False (run_effect checks it first), and
        # strip_warn_mode still blocks every other effect meanwhile.
        controller.strip_warn_over = False
        controller._wash_release()
        controller.power = False
    controller.wake_effect()
    return jsonify({
        'status': 'ok',
        'over': over,
        'power': controller.power,
        'effect': controller.current_effect,
        'strip_warn_mode': controller.strip_warn_mode,
    })


@app.route('/api/warn_kick', methods=['POST'])
def warn_kick_evt():
    """Beat event from disco while Strip-Warn runs (~1-3 POSTs/s).

    Events, not frames — the strip stays the renderer (era principle). Outside
    iris_warn it is a silent no-op so the disco client can stay dumb; the queue
    cap sheds bursts instead of building a backlog of stale beats."""
    data = request.get_json() or {}
    try:
        strength = max(0.0, min(1.0, float(data.get('strength', 0.5))))
    except (TypeError, ValueError):
        strength = 0.5
    bpm = None
    try:
        b = float(data.get('bpm'))
        if 50.0 <= b <= 200.0:
            bpm = b
    except (TypeError, ValueError):
        pass
    if controller.current_effect == 'iris_warn':
        q = controller.effect_params.setdefault('iris_kicks', [])
        if len(q) < 8:
            q.append({'s': strength, 'bpm': bpm})
        controller.wake_effect()
    return jsonify({'status': 'ok'})


@app.route('/api/warn_event', methods=['POST'])
def warn_event_evt():
    """Weiss-Event von disco (double/roll/accent) — EIN POST pro Event.

    Weiss ist Interpunktion: der Vollflaechen-Blinder feuert nur noch auf
    erkannte Rhythmus-Events (Paritaet zur dB-Analyse-Seite). Zugleich der
    Dev-Hook zum Handzuenden:
      curl -X POST :5006/api/warn_event -H 'Content-Type: application/json' \
           -d '{"kind": "double", "gap_ms": 180}'
    Ausserhalb von iris_warn ein stiller No-op (disco bleibt dumm); die
    Queue-Kappe verwirft Bursts statt veralteter Blinder."""
    data = request.get_json() or {}
    kind = str(data.get('kind') or '')
    if kind not in ('double', 'roll', 'accent', 'burst', 'sweep', 'shimmer', 'echo', 'meteor', 'stardust'):
        return jsonify({'status': 'ignored'})

    def _f(key, default, lo, hi):
        try:
            return max(lo, min(hi, float(data.get(key, default))))
        except (TypeError, ValueError):
            return default

    gap = _f('gap_ms', 160, 60, 400) / 1000.0
    try:
        n = max(2, min(6, int(data.get('n', 2))))
    except (TypeError, ValueError):
        n = 2
    # L6: additive Varianten-Felder — alte Clients (ohne Felder) rendern
    # exakt wie bisher; alles geklemmt (Strom + Geschmack sind Config-Sache).
    # dur_ms ABWESEND => 0.0 (Intake nimmt den Renderer-Default, z.B. 0.7 s
    # beim Sweep) — die Klemme darf Abwesenheit nicht auf 80 ms hochziehen.
    ev = {'kind': kind, 'gap': gap, 'n': n,
          'dur': (_f('dur_ms', IRIS['variant_dur_min'] * 1000,
                     IRIS['variant_dur_min'] * 1000,
                     IRIS['variant_dur_max'] * 1000) / 1000.0
                  if data.get('dur_ms') is not None else 0.0),
          'intensity': _f('intensity', 1.0, 0.3, 1.0),
          'density': _f('density', 1.0, 0.5, 1.5),
          'origin': _f('origin', 0.5, 0.0, 1.0),
          'v': _f('v', 0, 0, 4000),   # Meteor: Kopftempo LED/s; 0 = wuerfeln
          'dir': 1 if _f('dir', 1, -1, 1) >= 0 else -1}
    if controller.current_effect == 'iris_warn':
        evq = controller.effect_params.setdefault('iris_events', [])
        if len(evq) < 4:
            evq.append(ev)
        controller.wake_effect()
    return jsonify({'status': 'ok'})


@app.route('/api/warn_mode', methods=['POST'])
def warn_mode():
    """Enable/disable Strip-Warn exclusive ownership of the strip."""
    data = request.get_json() or {}
    on = bool(data.get('on', False))
    if on:
        controller._warn_snapshot()
    controller.strip_warn_mode = on
    if not on:
        controller.strip_warn_over = False
        controller.power = False
        controller._iris_abort()
        controller._warn_restore()
    controller.wake_effect()
    return jsonify({
        'status': 'ok',
        'strip_warn_mode': controller.strip_warn_mode,
        'power': controller.power,
    })


def _blocked_by_strip_warn():
    """While Strip-Warn owns the strip, ignore UI/disco effect/color writes."""
    return bool(getattr(controller, 'strip_warn_mode', False))

@app.route('/api/brightness', methods=['POST'])
def set_brightness():
    data = request.get_json() or {}
    brightness = max(0, min(255, int(data.get('brightness', 100))))
    if _blocked_by_strip_warn():
        # Entkopplung 2026-08-12: waehrend Iris/Strip-Warn den Strip
        # besitzt, wird der Nutzerwunsch NICHT live angewendet (er wuerde
        # das laufende Warn-Bild dimmen), sondern in den Schnappschuss
        # geschrieben — er gilt, sobald der Warn-Modus endet.
        controller._warn_snapshot()
        controller._pre_warn['brightness'] = brightness
        return jsonify({'status': 'deferred', 'reason': 'strip-warn',
                        'brightness': brightness})
    controller.brightness = brightness
    controller.wake_effect()
    return jsonify({'status': 'ok', 'brightness': controller.brightness})

@app.route('/api/speed', methods=['POST'])
def set_speed():
    data = request.get_json() or {}
    speed = max(1, min(100, int(data.get('speed', 50))))
    if _blocked_by_strip_warn():
        controller._warn_snapshot()
        controller._pre_warn['speed'] = speed
        return jsonify({'status': 'deferred', 'reason': 'strip-warn',
                        'speed': speed})
    controller.speed = speed
    return jsonify({'status': 'ok', 'speed': controller.speed})

@app.route('/api/effect', methods=['POST'])
def set_effect():
    data = request.get_json() or {}
    effect = data.get('effect', 'solid')
    valid_effects = ['solid', 'rainbow', 'pulse', 'chase', 'sparkle', 'strobe', 'meteor', 'breathe', 'sinelon', 'juggle', 'theater', 'gradient', 'fire', 'iris_warn']
    
    if effect not in valid_effects:
        return jsonify({'status': 'error', 'message': 'Invalid effect'}), 400

    # Strip-Warn exclusive: only iris_warn arm allowed; other effects would flash through
    if _blocked_by_strip_warn() and effect != 'iris_warn':
        # Wunsch aufheben statt verwerfen — gilt nach dem Warn-Modus
        controller._warn_snapshot()
        controller._pre_warn['effect'] = effect
        return jsonify({
            'status': 'deferred',
            'reason': 'strip-warn',
            'effect': controller.current_effect,
            'power': controller.power,
        })

    if effect in valid_effects:
        controller.current_effect = effect
        # Reset effect parameters when changing effects
        if effect == 'meteor':
            controller.effect_params['meteor_positions'] = []
            controller.effect_params['pixel_states'] = [[0, 0, 0] for _ in range(controller.strip.numPixels() if controller.strip else 600)]
            controller.effect_params['last_meteor_spawn'] = 0
        elif effect == 'breathe':
            controller.effect_params['breathe_brightness'] = 0.1
            controller.effect_params['breathe_direction'] = 1
        elif effect == 'sparkle':
            controller.effect_params['sparkle_pixels'] = []
        elif effect == 'chase':
            controller.effect_params['chase_position'] = 0
        elif effect == 'rainbow':
            controller.effect_params['rainbow_offset'] = 0
        elif effect == 'pulse':
            controller.effect_params['pulse_brightness'] = 0.1
            controller.effect_params['pulse_direction'] = 1
        elif effect == 'sinelon':
            controller.effect_params['sinelon_phase'] = 0
            controller.effect_params['sinelon_pixels'] = [[0, 0, 0] for _ in range(controller.strip.numPixels() if controller.strip else 600)]
        elif effect == 'juggle':
            controller.effect_params['juggle_phase'] = 0
            controller.effect_params['juggle_pixels'] = [[0, 0, 0] for _ in range(controller.strip.numPixels() if controller.strip else 600)]
        elif effect == 'theater':
            controller.effect_params['theater_j'] = 0
            controller.effect_params['theater_q'] = 0
        elif effect == 'gradient':
            controller.effect_params['gradient_pos'] = 0
            controller.effect_params['gradient_hue1'] = 0
            controller.effect_params['gradient_hue2'] = 120
        elif effect == 'fire':
            controller.effect_params['fire_heat'] = [0] * (controller.strip.numPixels() if controller.strip else 600)
        elif effect == 'iris_warn':
            controller._warn_snapshot()   # 255er-Punch nie als Nutzerwunsch
            controller.effect_params['iris_t0'] = None
            controller.effect_params['iris_lit'] = None
            controller.effect_params['iris_sparking'] = None
            controller.effect_params['iris_spark_until'] = 0.0
            # Full punch + auto-power: one POST from disco engages the strip
            controller.brightness = 255
            controller.power = True
            # Paint first frame in-request → LED lights before HTTP returns
            try:
                controller.run_effect()
            except Exception as e:
                print(f"iris_warn first frame: {e}")

        controller.wake_effect()
        return jsonify({'status': 'ok', 'effect': controller.current_effect, 'power': controller.power})

@app.route('/api/color', methods=['POST'])
def set_color():
    data = request.get_json() or {}
    r = max(0, min(255, int(data.get('r', 255))))
    g = max(0, min(255, int(data.get('g', 255))))
    b = max(0, min(255, int(data.get('b', 255))))
    if _blocked_by_strip_warn():
        # frueher 'blocked' (Wunsch verworfen) — jetzt aufgehoben
        controller._warn_snapshot()
        controller._pre_warn['color'] = [r, g, b]
        return jsonify({'status': 'deferred', 'reason': 'strip-warn',
                        'color': {'r': r, 'g': g, 'b': b}})
    controller.color = [r, g, b]
    controller.wake_effect()
    return jsonify({'status': 'ok', 'color': {'r': r, 'g': g, 'b': b}})

@app.route('/api/solid', methods=['POST'])
def set_solid():
    """One-shot disco sync: power + solid effect + RGB + brightness in a single RTT."""
    if _blocked_by_strip_warn():
        return jsonify({'status': 'blocked', 'reason': 'strip-warn', 'power': controller.power})
    data = request.get_json() or {}
    if 'r' in data or 'g' in data or 'b' in data:
        r = max(0, min(255, int(data.get('r', controller.color[0]))))
        g = max(0, min(255, int(data.get('g', controller.color[1]))))
        b = max(0, min(255, int(data.get('b', controller.color[2]))))
        controller.color = [r, g, b]
    if 'brightness' in data:
        controller.brightness = max(0, min(255, int(data.get('brightness'))))
    if 'power' in data:
        controller.power = bool(data.get('power'))
        if not controller.power:
            controller.clear(force=True)
            controller.wake_effect()
            return jsonify({'status': 'ok', 'power': False})
    else:
        controller.power = True
    controller.current_effect = 'solid'
    try:
        controller.effect_solid()
    except Exception as e:
        print(f"solid paint: {e}")
    controller.wake_effect()
    return jsonify({
        'status': 'ok',
        'power': controller.power,
        'effect': 'solid',
        'color': {'r': controller.color[0], 'g': controller.color[1], 'b': controller.color[2]},
        'brightness': controller.brightness,
    })

@app.route('/api/theater_mode', methods=['POST'])
def set_theater_mode():
    data = request.get_json() or {}
    rainbow = data.get('rainbow', True)
    controller.theater_rainbow = bool(rainbow)
    return jsonify({'status': 'ok', 'theater_rainbow': controller.theater_rainbow})

if __name__ == '__main__':
    print("Lichtwerk Web Controller starting...")
    led_count = controller.strip.numPixels() if controller.strip else 50
    print(f"LEDs: {led_count} on GPIO {controller.config['led_config']['pin']} (Demo Mode: {not controller.strip})")
    print("Web interface: http://localhost:5006")
    # threaded=True: disco warn_flash + sync don't serialize behind each other
    app.run(host='0.0.0.0', port=5006, debug=False, threaded=True)