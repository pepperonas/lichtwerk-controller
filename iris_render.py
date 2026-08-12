"""Pure Rendering-Hilfsschicht fuer die weissen Akzent-Effekte (W1).

Kein Hardware-, Controller- oder Flask-Import — nur Mathematik. Alles hier
ist deterministisch (Zufall kommt als injizierte random.Random herein) und
vollstaendig unit-getestet (tests/test_iris_render.py).

Warum es dieses Modul gibt (docs/white-effects-analysis.md, 0.3): der
Iris-Pfad rendert float-Zentren als Gauss-Profile — gut fuer breite Koepfe,
aber es fehlten (a) Sub-Pixel-Anti-Aliasing fuer 1-px-Punkte und (b) ein
Line-Integral fuer schnelle Koepfe: der Sweep malt die PUNKT-Position pro
Frame, ab ~1000 LED/s reissen bei 20-ms-Frames Luecken. `line_coverage`
liefert stattdessen die im Frame UEBERSTRICHENE Strecke, Randpixel anteilig
— der Unterschied zwischen "flackernde Punktkette" und "fliegender Meteor".
"""


def line_coverage(p0, p1, n):
    """Abdeckung der Strecke [p0, p1] je LED-Zelle — lueckenlos, Raender anteilig.

    LED i belegt das Intervall [i, i+1). Rueckgabe: Liste (index, anteil)
    mit anteil = Ueberlappungslaenge der Strecke mit der Zelle (0..1),
    nur Zellen innerhalb [0, n). Reihenfolge aufsteigend, zusammenhaengend.

    Invarianten (getestet): sum(anteile) == auf den Strip geclippte
    Streckenlaenge; KEINE Luecke — jede Zelle zwischen erster und letzter
    hat einen Eintrag > 0. p0 == p1 => leer (ein Punkt hat keine Laenge;
    Koepfe rendern zusaetzlich per point_aa/Gauss).
    """
    lo, hi = (p0, p1) if p0 <= p1 else (p1, p0)
    lo = max(lo, 0.0)
    hi = min(hi, float(n))
    if hi <= lo:
        return []
    out = []
    i = int(lo)
    while i < hi:
        a = lo if i < lo else float(i)
        b = hi if (i + 1) > hi else float(i + 1)
        if b > a:
            out.append((i, b - a))
        i += 1
    return out


def point_aa(pos, n):
    """Sub-Pixel-Punkt: Gewicht anteilig auf die beiden Nachbar-LEDs.

    `pos` ist eine kontinuierliche Position (LED-Zentren bei i + 0.5 —
    pos == i + 0.5 landet zu 100 % auf LED i). Rueckgabe wie line_coverage;
    Summe der Gewichte == 1.0, ausser der Punkt haengt teilweise/ganz
    ausserhalb des Strips (dann verlaesst die Energie den Strip).
    """
    c = pos - 0.5
    import math
    base = math.floor(c)
    frac = c - base
    out = []
    if 0 <= base < n and 1.0 - frac > 0.0:
        out.append((int(base), 1.0 - frac))
    if 0 <= base + 1 < n and frac > 0.0:
        out.append((int(base) + 1, frac))
    return out


def temp_to_rgb(kelvin):
    """Farbtemperatur -> (r, g, b) 0..255 (Tanner-Helland-Approximation).

    Geklemmt auf 1000..12000 K. Warm (3000 K) ist rot-dominant, kuehl
    (8000 K) blau-dominant — der Schweif-Gradient und die Sparkle-Streuung
    bauen darauf.
    """
    import math
    k = max(1000.0, min(12000.0, float(kelvin))) / 100.0
    if k <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(k) - 161.1195681661
    else:
        r = 329.698727446 * ((k - 60) ** -0.1332047592)
        g = 288.1221695283 * ((k - 60) ** -0.0755148492)
    if k >= 66:
        b = 255.0
    elif k <= 19:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(k - 10) - 305.0447927307
    clamp = lambda v: max(0.0, min(255.0, v))  # noqa: E731
    return (clamp(r), clamp(g), clamp(b))


def powerlaw_brightness(u, k):
    """Potenzgesetz-Helligkeit: u ~ uniform(0,1) -> u**k.

    k > 1 = viele schwache, wenige sehr helle (Sternenstaub); k = 1 waere
    die billig wirkende Gleichverteilung.
    """
    u = max(0.0, min(1.0, float(u)))
    return u ** max(0.0, float(k))


def blue_noise_positions(rng, count, n, min_dist):
    """Poisson-Disk-artige Positionen: uniform gewuerfelt, aber nie naeher
    als `min_dist` an einer bestehenden — verhindert Verklumpung (wirkt
    komponiert statt zufaellig). Dart-Throwing mit Versuchs-Deckel; wenn der
    Strip zu voll ist, wird der Abstand schrittweise halbiert statt endlos
    zu ziehen (bounded, deterministisch via rng).
    """
    out = []
    dist = max(0.0, float(min_dist))
    attempts = 0
    max_attempts = max(20, int(count) * 30)
    while len(out) < count and attempts < max_attempts:
        attempts += 1
        cand = rng.uniform(0.0, float(n))
        if all(abs(cand - p) >= dist for p in out):
            out.append(cand)
        elif attempts % (10 * max(1, count)) == 0 and dist > 0.5:
            dist /= 2.0
    out.sort()
    return out


def spark_envelope(age, life, attack_frac):
    """Attack/Decay-Huellkurve eines Sparkles — nie hartes An/Aus.

    Smoothstep-Anstieg ueber `attack_frac` des Lebens, dann Smoothstep-
    Verglimmen auf 0. Ausserhalb [0, life) exakt 0. Peak == 1.0 am Ende
    des Attacks.
    """
    life = float(life)
    if life <= 0.0 or age < 0.0 or age >= life:
        return 0.0
    atk = max(1e-6, min(0.9, float(attack_frac))) * life
    if age < atk:
        f = age / atk
        return f * f * (3.0 - 2.0 * f)
    g = 1.0 - (age - atk) / (life - atk)
    return g * g * (3.0 - 2.0 * g)


def perceptual(v):
    """Gamma-Encode (~2.2) eines linearen Lichtwerts 0..1.

    Exponentielle Schweif-Profile werden im LINEAREN Licht gerechnet und
    erst hiermit fuer den 8-bit-Draht geformt — im 8-bit-Raum gerechnet
    wirken sie abgehackt statt gluehend (Negativ-Beispiel: effect_meteor).
    """
    v = max(0.0, min(1.0, float(v)))
    return v ** (1.0 / 2.2)
