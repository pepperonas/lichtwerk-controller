# Iris Mode — Baseline-Analyse (Phase 0, 2026-08-12)

Rollback-Punkt: Branch `iris-baseline` + Tag `iris-baseline-20260812` in
**beiden** Repos (`lichtwerk-controller` c2236fe, `disco-controller` 2fa43eb).
Arbeit läuft auf Feature-Branch `iris-rework`. Keine Verhaltensänderung in
Phase 0.

---

## 0.2 Stack

Das System spannt sich über **zwei Dienste auf einem Host** — Erkennung und
Rendering sind bewusst getrennt (Events über HTTP, nie Frames):

| | Erkennung (`disco-controller`) | Rendering (`lichtwerk-controller`) |
|---|---|---|
| Runtime | Raspberry Pi 5 (BCM2712, 4× Cortex-A76 @ **2,8 GHz**), 8 GB RAM, Debian 12 aarch64, Kernel 6.12.47 | derselbe Host |
| Sprache | Python 3.11 + numpy (FFT), Flask, systemd | Python 3.11 **ohne numpy** (nur math/random), Flask, systemd |
| Rolle | Mikrofon → Features → Beat/Event-POSTs | `effect_iris_warn`-Frameloop → `/dev/leds0` |

**LED-Pfad:** WS2812B über den Kernel-Treiber `ws2812-pio-rp1` (RP1-PIO,
GPIO 21/Pin 40), Userspace schreibt RGBW-Payload (4 B/Pixel) nach `/dev/leds0`
(`pio_strip.py`: ein `open`+`write` pro Frame). **600 logische Pixel**, elektrisch
per Y auf **2 Ketten gespiegelt** (2×600 physisch, 2×5 m je Kette, **60 LED/m**).
800 kHz, 24 bit GRB auf dem Draht. Zwei Dimm-Schichten über der Payload:
`led_brightness=100` (LUT ×0,39 in `pio_strip.show()`) und die **hart codierte
Kernel-Gamma** (~^2,22, nicht abschaltbar auf diesem Kernel).

**Frame-Budget:** Draht-Zeit ≈ **18 ms/Frame** (600 px seriell) ⇒ physikalische
Decke ~50 fps. Effekt-Schreibtakt: 20 ms Boden (`iris_last_write`, wc:~1310).
Gemessener Hot-Path auf der Zielhardware (Glut-Tabelle + Schattenzonen +
600× `setPixelColor` + Brightness-Translate, ohne Write): **0,90 ms/Frame**
⇒ ~4,5 % eines Kerns bei 50 fps. **Der Engpass ist der Bus, nicht die CPU.**
Live-Last heute: disco 5,3 % CPU, lichtwerk 0,2 % (Strip idle), 7 GB RAM frei.

**Audio-Quelle:** USB-Mikrofon → `sounddevice.InputStream`, **44 100 Hz,
Blockgröße 1024** (≈ 23,2 ms/Block, ae:256-257). Latenz Sample→Licht:
~23 ms Block + Onset-Entscheidung im Callback + lokaler HTTP-POST (~2 ms)
+ Queue-Intake ≤ 20 ms + 18 ms Draht ≈ **45–65 ms** — unter der
Wahrnehmungsschwelle für Licht-auf-Beat (~80–100 ms).

**Bewertung:** Die Basis trägt Onset-Detection und Frequenzband-Analyse
**locker** — beides existiert bereits (s. 0.3). Fließkomma nativ, kein
Fixed-Point nötig. Kein Engpass für die Ziele A/B; einzige harte Grenzen:
18 ms Draht-Zeit (Framerate) und **kein numpy im Renderer** (per-LED-Python-
Loops sind bei 600 px/50 fps trotzdem billig, s. Benchmark).

---

## 0.3 Audio-Pipeline — was existiert wirklich

**Kein RMS-only-System.** Die volle Feature-Kette existiert; der mechanische
Eindruck entsteht NICHT durch fehlende Features (→ 0.4):

```
Mikro 44,1 kHz / 1024er-Blöcke (ae:372)
 │
 ├─ dBFS (RMS) ──────────────► Warn-Gate: round(spl,1) > warn_thr, LIVE ohne
 │                             Hysterese (BEWUSSTE Nutzer-Abnahme 02.08.) 
 │                             → POST /api/warn_gate (Flanke) → Engage/Release
 │
 ├─ Voll-FFT (rfft, Hanning) ─► 24-Band-Spektrum (Visualisierung)
 │
 └─ Bass-FFT (4096er-Fenster, ae:83) → Bandenergie 30–150 Hz (BASS_PRESETS)
     │
     ├─ BpmAnalyzer (Beat-Pfad): moving-avg-Baseline ×1,4 (AVG_WINDOW_S=3,0,
     │  ae:30) + SuperFlux-Steiggate (LAG 4/WIN 4/MARGIN 1,04) +
     │  Refraktärzeit 0,30 s (ae:31) → IOI-Median-BPM [60,200] + Konfidenz
     │    └─► on_beat → _warn_kick_strength (0,45·Salienz + 0,35·Bass +
     │        0,20·Konfidenz, Floor 0,25; app:1012) 
     │        → POST /api/warn_kick {strength, bpm}   (Tempo-Lock + Welle + Funken)
     │
     └─ Fast-Onset-Pfad: gleiche Gates, Refraktärzeit 0,12 s (ae:32) —
        NUR für die Event-Klassifikation, fasst BPM nie an
          └─► WhiteEventDetector (white_events.py): double/roll/accent,
              Schwellen RELATIV (p50/p85 der letzten 64 Kick-Stärken, ATC),
              WHITE_GAP 5 s (we:38), Verhungerungs-Fallback 40 s (we:50)
              → POST /api/warn_event {kind, gap_ms, n, s}
```

Glättung: Bass-Meter mit asymmetrischer EMA (Attack 0,45/Release 0,16),
adaptive Peaks mit Headroom (AGC-artig), Onset-Salienz als EMA. BPM-Tracking
vorhanden (IOI-Median, kein Autokorrelations-Verfahren).

---

## 0.4 Iris-Mode-Rendering — Kette, Parameter, Timing

### Ablauf (lichtwerk `effect_iris_warn`, ~125-Hz-Poll, 20-ms-Schreibtakt)

```
Kick-Intake (Queue) ─ snap: Rechteck-Phase u=0 AUF den Beat (Refraktär 0,24 s)
                    ─ Tempo-Lock: Periode = BPM-Seed | IOI-EMA | 0,55 s Freilauf
Event-Intake ───────► Blinder-Plan {Fenster(start,ende,gain), Spots je Puls}
Drop-Erkennung ─────► ks≥0,9 ∧ avg≥0,5 ∧ 8 s Cooldown (wc:1062) → Triple-Plan
Frame:
  red_env = iris_red_envelope(u)      Aufblühen 6 % → Hold 16 % → quad. Verglimmen auf 16 %
  glow_tbl = Wander-Glut × Schattenzonen   (4er-Blöcke; wc:25ff, 57ff)
  Basis    = Vollrot(255,70,55) · scale · red_env · glow_tbl   — ROT AUS im Blinder-Plan
  + Wellen (Mitte→außen, v=520+780·s LED/s, wc:1203; Gold-Kern/Rot-Halo, Replace-Blend)
  + Funken (Flanke/Kick, 55-ms-Fenster, Bernstein 255,90,0, Dichte ∝ Stärke)
  + Sparkle-Blinder (Cluster warmweiß 255,205,150, LUT je Frame neutralisiert,
    Verglimmen BL_DECAY_S=0,28 s; wc:1146)
  → show(): Payload × Brightness-LUT → /dev/leds0 → Kernel-Gamma → Draht
```

### Parameter-Tabelle (Auszug — die wirkmächtigen)

| Parameter | Ist | Fundstelle | Wirkung | sinnvoller Bereich |
|---|---|---|---|---|
| Warn-Schwelle `warn_thr` | 55 SPL, live | disco app.py (Server-Flag) | Engage/Release des gesamten Modus | 30–100 |
| Beat-Refraktär | 0,30 s | ae:31 | max. Beat-Rate 200 BPM | 0,25–0,35 |
| Fast-Refraktär | 0,12 s | ae:32 | Doppel-Kick-Sichtbarkeit | 0,10–0,15 |
| Kick-Stärke-Mix | 0,45/0,35/0,20 | app:1012 | Gewicht Salienz/Bass/Konfidenz | Summe 1 |
| `WHITE_GAP_S` | 5,0 s | we:38 | harter Weiß-Mindestabstand | 3–10 |
| `STARVE_S` | 40 s | we:50 | Fallback-Metronom (s. Schwächen!) | 25–90 |
| double/accent-Bars | p50 / p85 (+Floors 0,35/0,6) | we:42/48/155/174 | relative Event-Schwellen | Perzentile |
| Rechteck-Periode | BPM→IOI-EMA→**0,55 s** | wc:1123-1125 | Puls-Takt; Freilauf = Metronom | 0,30–1,20 |
| `IRIS_RED_ATTACK/HOLD/FLOOR` | 0,06/0,16/0,16 | wc:95-97 | Atem-Form des Rots | A 0,02–0,12; F 0,05–0,3 |
| Glut-Wellenlängen/-Drift | 170/290 LED, 14/−9 LED/s | wc:26ff | Wander-Textur | inkommensurabel halten |
| Schattenzonen | 4× 30–90 LED, Tiefe 0,55–0,85, Leben 4–9 s | wc:57ff | dunkle Wander-Taschen | — |
| Blinder-Fenster | double 2×0,10 s · roll n×0,09 s · accent 0,16 s | wc:1095-1107 | Weiß-Puls-Dauern | 0,06–0,25 |
| Sparkle-Spots | 22/16/26/24 Cluster, **fix je Kind** | wc:1066,1097-1107 | Weiß-Dichte | randomisierbar |
| `BL_DECAY_S` | 0,28 s | wc:1146 | Verglimmen der Funken | 0,15–0,6 |
| Funken-Fenster | 0,055 s je Flanke/Kick | wc:1056,1186 | rote Textur-Blitzer | — |
| Wellen-Tempo | 520+780·s LED/s, **immer Mitte→außen** | wc:1203 | Druckwelle je Kick | Startpunkt randomisierbar |
| Drop | ks≥0,9 ∧ avg≥0,5, 8 s | wc:1062-1063 | Triple-Blinder | — |
| Schreibtakt / Heartbeat | 20 ms / 80 ms | wc:~1310/~1300 | Framerate / Slip-Heilung | 18 ms Draht = Boden |

### Timing-Analyse — woher kommt Periodizität?

| Effekt | Taktquelle | Charakter |
|---|---|---|
| Roter Puls | Kick-Snap (musikalisch ✓) — aber Freilauf-Fallback = **fixe 0,55 s** | ohne konfidente Kicks: Metronom |
| Rote Hüllkurve | identische Form **jede** Periode, Peak immer 1,0 | Kick-Stärke moduliert NICHT den Puls selbst |
| Funken/Wellen | je Kick (musikalisch ✓), Formeln deterministisch, Welle **immer aus der Mitte** | erkennbares Muster |
| Weiß-Events | musikgetriggert ✓, aber `WHITE_GAP` 5 s hart + `STARVE_S` **exakt 40 s** | bei ereignisarmer Musik: ~45-s-Metronom |
| Weiß-Formen | Cluster-Zahl, Puls-Dauer, Intensität **fix je Event-Art** | nur Positionen zufällig |
| Engage | identische 70/60/80-ms-Choreo **je Warn-Flanke** | bei Musik um die Schwelle oft wiederholt |

### Ehrliche Schwachstellenliste (Codestellen des mechanischen Eindrucks)

1. **wc:1125** `iris_period = 0.55` — der Freilauf ist ein exaktes Metronom.
2. **wc:95-120** Hüllkurve parameterlos: jeder Beat sieht gleich aus; die
   gemessene Kick-Stärke (vorhanden!) erreicht den roten Puls nie.
3. **we:50 + we:167ff** Verhungerungs-Fallback feuert nach exakt 40 s →
   quasi-periodisches Weiß bei ruhiger Musik; kein Zufall im *Wann*.
4. **wc:1095-1107** Weiß-Varianten ohne Varianz: Dauer/Intensität/Dichte fix;
   keine gewichtete Auswahl, keine „letzte Variante ausschließen"-Regel.
5. **wc:1203ff** Wellen starten immer in der Streifenmitte; Richtung/Ursprung
   nie randomisiert.
6. **wc (Engage-Block, t<0,21)** identische Intro-Choreo je Flanke.
7. Kein seedbarer RNG (`random` global) → keine reproduzierbaren Tests der
   Zufallsanteile; keine Offline-Verifikation der Trigger-Statistik.
8. Farbe: Basis konstant (255,70,55); kein Hue-Jitter, keine Intensität→
   Farbtemperatur-Kopplung (Funken/Welle/Weiß sind bereits getrennte Töne).

### Brief-Ziele vs. Bestand (damit nichts doppelt gebaut wird)

| Brief-Punkt | Status |
|---|---|
| Frequenzbänder, Bass-Kopplung | ✅ vorhanden (Bass-FFT, Kick-Kette) |
| Onset (SuperFlux-artig), Refraktärzeit | ✅ vorhanden (Energie-basiert, Max-Filter-Gate) |
| Adaptiver Schwellwert, AGC | ✅ vorhanden (Baseline ×1,4 + ATC-Perzentile; adaptive Peaks) |
| BPM | ✅ (IOI-Median; keine Autokorrelation) |
| Asymm. Hüllkurven (Attack/Decay) | ✅ (Rot-Envelope, Sparkle-Decay) — aber ohne Stärke-Modulation |
| Hysterese Warn-Gate | ❌ BEWUSST nicht (Nutzer-Abnahme 02.08.; 3 Versuche zurückgenommen) |
| Gamma | ✅ Kernel hart codiert (+LUT); kein temporales Dithering |
| Poisson-Timing, Seed-RNG, Varianten-Gewichtung | ❌ offen (Ziel A) |
| Hue-Jitter, Farbtemperatur-Kopplung, Oklab | ❌ offen (Ziel B.3) |
| Ambient-Layer | ◐ Wander-Glut + Schattenzonen (Sinus/Zonen, kein Perlin) |
| Layer-Compositing (add/screen) | ❌ Replace-Malerei in fester Reihenfolge |
| Räumlichkeit | ◐ Wellen/Spots/Schatten ja; Ursprünge/Richtungen fix |
| Offline-Verifikation | ❌ offen (nur Unit-Tests der Einzelteile: 138 lw + 188 disco) |

**Nicht verhandelbare Bestandsdoktrinen** (aus teuren Feld-Lektionen):
Vollflächen-Neutralweiß unmöglich (Einspeisung nur vorn → Blau-Drift +
Segment-Binning; Sparse-Weiß ist der ehrliche Weg) · Warn-Bit bewusst ohne
Hysterese · „Fallback ist der Tag": ohne Kicks muss ein definierter,
abgenommener Grundzustand laufen · Zombie-Gotcha: Effekt-Zustand mit
Zeitstempeln MUSS im Effekt-Init resetten (iris_t0 resettet je Flanke).
