"""red_organic.py — pure Rechenkerne des organischen Rot-Profils.

Rot-Brief 2026-08-13 („Glut und Puls, nicht Signalleuchte"): dieses Modul
haelt AUSSCHLIESSLICH deterministische, seiteneffektfreie Mathematik —
Huellkurven, Farbrampe (Oklab), soft-knee, Dithering, Filter. Kein Strip,
keine Uhr, kein Zufall: alles kommt als Parameter herein (Haus-Stil, exakt
testbar). Der Malpfad in web_controller.effect_iris_warn ruft nur.

Design-Anker aus docs/red-diagnosis.md / red-organic-plan.md:
- Pulse stapeln ADDITIV mit soft-knee (kein Retrigger-Teleport, Ursache 2)
- Velocity nichtlinear auf Peak/Dauer/Ausbreitung (Ursache 1)
- Intensitaet -> Farbtemperatur in Oklab, NIE Richtung Weiss (Ursache 4;
  der Kontrast zu den Weiss-Akzenten ist gesperrtes Terrain)
- temporales Dithering gegen 8-Bit-Stufen im Glut-Boden (Ursache 7)
- keine Allokation im Frame: Gradient vorberechnet, Pulse-Liste gekappt
"""

import math

# ── Oklab (nur beim Gradient-Bau — nie im Frame-Pfad) ────────────────────


def _srgb_to_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lin_to_srgb(c):
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1.0 / 2.4) - 0.055


def srgb_to_oklab(rgb):
    r, g, b = (_srgb_to_lin(v / 255.0) for v in rgb)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = l ** (1.0 / 3.0), m ** (1.0 / 3.0), s ** (1.0 / 3.0)
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def oklab_to_srgb(lab):
    big_l, a, b2 = lab
    l_ = big_l + 0.3963377774 * a + 0.2158037573 * b2
    m_ = big_l - 0.1055613458 * a - 0.0638541728 * b2
    s_ = big_l - 0.0894841775 * a - 1.2914855480 * b2
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    b = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return tuple(int(round(max(0.0, min(1.0, _lin_to_srgb(v))) * 255))
                 for v in (r, g, b))


# Rampe: dunkles Tiefrot -> sattes Rot (~ der klassische Farbort) ->
# gluehendes Orangerot an der Spitze. Interpoliert wird in Oklab; die
# Kappen (g_max/b_max) sichern die Nie-Weiss-Doktrin zusaetzlich ab.
GRADIENT_ANCHORS = (
    (0.00, (34, 3, 2)),      # Glut-Abgrund: fast schwarzes Tiefrot
    (0.62, (232, 52, 40)),   # sattes Rot — Nachbar des classic (255,70,55)
    (1.00, (255, 122, 45)),  # gluehendes Orangerot (Peak)
)


def _sample_anchors(t):
    """Stueckweise lineare Oklab-Interpolation ueber GRADIENT_ANCHORS."""
    t = max(0.0, min(1.0, t))
    pts = [(p, srgb_to_oklab(rgb)) for p, rgb in GRADIENT_ANCHORS]
    for (p0, l0), (p1, l1) in zip(pts, pts[1:]):
        if t <= p1:
            f = 0.0 if p1 <= p0 else (t - p0) / (p1 - p0)
            return tuple(a + (b - a) * f for a, b in zip(l0, l1))
    return pts[-1][1]


def build_gradient(steps, g_max, b_max, drift=0.0):
    """steps Eintraege (r,g,b) 0..255. `drift` verschiebt NUR den Farbort
    (Chroma-Abtastpunkt), nicht die Helligkeitsrampe — der minutenlange
    Hue-Drift aendert die Stimmung, nie die Dynamik. Kappen erzwingen die
    Nie-Weiss-Doktrin hart: G/B gedeckelt, R bleibt dominant.
    """
    out = []
    for i in range(steps):
        t = i / (steps - 1.0)
        big_l = _sample_anchors(t)[0]
        _, a, b2 = _sample_anchors(max(0.0, min(1.0, t + drift)))
        r, g, b = oklab_to_srgb((big_l, a, b2))
        g = min(g, int(g_max))
        b = min(b, int(b_max))
        if r < g:                    # R-Dominanz ist nicht verhandelbar
            g = r
        out.append((r, g, b))
    return out


# ── Puls-Huellkurve (ADSR-artig, analytisch in der Zeit) ─────────────────


def pulse_env(age, attack_s, decay_s, sustain, tail_s):
    """0..1: s-foermiger Attack, exponentieller Anfangs-Decay auf den
    Sustain-Anteil, Sustain-Schwanz smoothstept auf 0. Stetig an allen
    Uebergaengen (Attack-Ende: rise=1 == punch+sus=1), reine Funktion des
    Alters — delta-time-sauber, kein akkumulierender Zustand."""
    if age <= 0.0:
        return 0.0
    if age < attack_s:
        f = age / attack_s
        return f * f * (3.0 - 2.0 * f)
    a2 = age - attack_s
    tau = max(1e-3, decay_s / 3.0)
    punch = (1.0 - sustain) * math.exp(-a2 / tau)
    if a2 >= tail_s or tail_s <= 0.0:
        sus = 0.0
    else:
        f = a2 / tail_s
        sus = sustain * (1.0 - f * f * (3.0 - 2.0 * f))
    return punch + sus


def pulse_dead(age, attack_s, decay_s, sustain, tail_s):
    """Prune-Kriterium: Schwanz vorbei UND Punch-Rest unter Sichtbarkeit."""
    if age < attack_s + tail_s:
        return False
    tau = max(1e-3, decay_s / 3.0)
    return (1.0 - sustain) * math.exp(-(age - attack_s) / tau) < 0.01


def vel_peak(vel, gamma, floor):
    """Velocity -> Peak, perzeptuell (power curve); floor haelt den
    zartesten Schlag sichtbar."""
    v = max(0.0, min(1.0, vel)) ** max(0.05, gamma)
    return floor + (1.0 - floor) * v


def pulse_cover(dist, reach, edge):
    """Expandierende Bloom-Front: 1 innerhalb des Radius, smoothstep-Rand.
    dist = |x - Ursprung|, reach = Alter x Ausbreitungstempo."""
    if dist <= reach:
        return 1.0
    if edge <= 0.0 or dist >= reach + edge:
        return 0.0
    f = (dist - reach) / edge
    return 1.0 - f * f * (3.0 - 2.0 * f)


def soft_knee(x, knee):
    """Saettigende Summe: identisch bis knee, danach asymptotisch gegen 1.0
    (C1-stetig am Knie) — gestapelte Pulse addieren, ohne zu clippen."""
    if x <= knee:
        return max(0.0, x)
    span = max(1e-6, 1.0 - knee)
    return knee + span * (1.0 - math.exp(-(x - knee) / span))


# ── Filter / Felder ──────────────────────────────────────────────────────


def one_pole(cur, target, dt, tau_up, tau_down):
    """Asymmetrischer One-Pole (EMA): eigene Zeitkonstante je Richtung."""
    tau = tau_up if target > cur else tau_down
    a = 1.0 - math.exp(-max(0.0, dt) / max(1e-3, tau))
    return cur + (target - cur) * a


def bed_level(energy, lo, hi):
    """Glut-Bett folgt der traegen Energie: Breakdown dunkel, Groove lebendig."""
    return lo + (hi - lo) * max(0.0, min(1.0, energy))


def bass_press(x01, env, gain, front=0.12):
    """Druckwelle der Bassline: waechst von BEIDEN Strip-Enden zur Mitte.

    x01 = Position 0..1, env = getraegte Bass-Huellkurve (0..1 = Fuellgrad
    je Haelfte), weiche smoothstep-Front. Amplitude zusaetzlich x env:
    leiser Bass drueckt flacher UND kuerzer — der 'Woofer zum Anschauen'.
    """
    if env <= 0.0 or gain <= 0.0:
        return 0.0
    edge = min(x01, 1.0 - x01) * 2.0     # 0 an den Enden, 1 in der Mitte
    d = edge - env
    if d <= 0.0:
        return gain * env
    if d >= front:
        return 0.0
    f = d / front
    return gain * env * (1.0 - f * f * (3.0 - 2.0 * f))


# ── Dithering ────────────────────────────────────────────────────────────


def hash01(a, b, c=0):
    """Deterministisches Rauschen 0..1 je (Block, Frame, Kanal) — u32-Maske
    (die usize-Falle aus dem Beat-Detektor: ohne Maske wird das 'Rauschen'
    eine In-Band-Rampe)."""
    h = (a * 2654435761 + b * 40503 + c * 69069) & 0xffffffff
    h ^= h >> 13
    h = (h * 1274126177) & 0xffffffff
    return ((h >> 8) & 0xffff) / 65536.0


def dither8(v, noise01):
    """floor(v + Rauschen): Erwartungswert exakt v — bei 50 fps mittelt das
    Auge die Zwischenstufe (die Anti-Treppen-Massnahme, Ursache 7)."""
    return max(0, min(255, int(v + noise01)))
