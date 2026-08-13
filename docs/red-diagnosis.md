# Rot-Diagnose — warum wirkt der rote Pfad „plump"?

Phase 0.2 des Briefs „Rote Effekte: von plump zu organisch" (2026-08-13).
Basis: Tag `iris-red-baseline-2026-08-13` (lichtwerk `88d02c2` + disco
`76c7460`), roter Pfad vollständig gelesen:

- lichtwerk `web_controller.py` — `effect_iris_warn` (Z. 1172–2101) + Helfer
  `iris_red_envelope` (95), `iris_red_punch_peak` (127), `iris_scale_envelope`
  (137), `iris_glow_factor` (39), `iris_shadow_*` (66–92), `iris_wave_*`
  (174–220), Kick-Intake (1279–1345), Takt/Snap (1532–1553), Malpfad
  (1710–1862), `run_effect`/Loop (2103–2164), `iris_config.py` komplett
- disco `app.py` — `_warn_kick_strength` (1064), `_on_beat` (1254),
  `_v2_kick` (1116), `audio_engine.py` bass-/high-Meter (631–658),
  `lichtwerk_client.warn_kick` (168)

Bewertung je Ursache: **ja** = trifft zu und trägt zum Plump-Eindruck bei ·
**teilweise** = Ansätze vorhanden, aber unvollständig · **nein** = kein Befund.

---

## 1. Binäres Verhalten (an/aus statt kontinuierlicher Intensität) — **teilweise**

Velocity-Ansätze existieren, werden aber **dreifach komprimiert**:

1. **Quelle komprimiert** — `_warn_kick_strength` (disco app.py:1064) mischt
   `0.45·Salienz + 0.35·Bass + 0.20·Konfidenz` mit **Floor 0.25**. Bei
   laufender Musik sind Bass ≈ 0.5–0.9 und Konfidenz ≈ 0.5–1.0 fast konstant
   → die gesendete Stärke lebt praktisch in einem **schmalen Band ~0.5–0.9**.
   Keine Normierung auf die laufende Verteilung: ein leiser Track hat nie
   „harte", ein lauter nie „zarte" Schläge.
2. **Mapping flach & linear** — `iris_red_punch_peak` (web_controller.py:127):
   `peak = 1 − red_punch·(1−ks)` mit `red_punch` 0.3. Zartester vs. härtester
   Schlag unterscheiden sich im Peak um **maximal 30 %** — nach der
   Treiber-Gamma perzeptuell noch weniger. Nicht-linear (power curve) ist
   nichts.
3. **Nur der Peak skaliert** — Hüllkurven-**Dauer** und **Form** sind
   velocity-blind (Decay hängt an der Beat-Periode, Z. 1615). Die Wellen
   skalieren immerhin mit s (`v = 520+780·s`, `width = 12+24·s`, Z. 189–190),
   die Funken schwach (`×(1+0.6·boost)`, Z. 1859). Im Freilauf ist ks fix
   0.5 (Z. 1623–1624).

**Folge:** jeder Schlag sieht fast gleich aus — genau das Brief-Symptom.

## 2. Hüllkurvenform — **teilweise**

Gut: der Attack ist geformt (smoothstep über 12 % der Periode ≈ 66 ms,
`iris_red_envelope` Z. 110–115), der Decay ist smoothstep statt linear
(Z. 118–124) und landet auf einem Glut-Boden (16 %) statt Schwarz.

Die zwei echten Defekte:

- **Retrigger = Teleport nach unten.** Es gibt EINE globale, phasen-gekoppelte
  Hüllkurve. Der Kick-Snap (Z. 1551–1553) setzt `u = 0` → der Wert springt vom
  aktuellen Verglimm-Stand (z. B. 0.45) **instantan hinunter auf den Boden
  0.16** und blüht dann neu auf. Bei dichten Schlagfolgen ist das das
  „Retrigger-Knacksen" aus dem Brief — es gibt kein additives Stapeln, keinen
  soft-knee.
- **Dauer folgt dem Tempo, nicht dem Gewicht.** Decay-Länge = Rest der
  Beat-Periode. Ein brutaler Drop-Hit klingt exakt so lange aus wie ein zartes
  Pochen im selben Tempo.

## 3. Uniformität im Raum — **teilweise**

Die **Fläche** ist nicht uniform: Wander-Glut (2 inkommensurable Sinuswellen,
Z. 39–57) × Schattenzonen (4 Gauß-Taschen, Z. 66–92, 1729–1759) geben dem Rot
Textur und Drift.

Aber der **Schlag selbst ist ein globaler Lift ohne Herkunft**: `red_env` ist
ein Skalar, der alle 600 LEDs im selben Frame multipliziert (Z. 1776–1781).
Eine Herkunft haben nur die dünnen Wellenfronten (12–36 LEDs, Z. 1788 ff.) —
der dominante Bloom hebt und senkt sich überall gleichzeitig, wie eine
Signalleuchte.

## 4. Farbe statisch — **ja**

`hr, hg, hb = 255, 70, 55` ist hart codiert (Z. 1556); jede Intensität ist
**derselbe Farbort, linear skaliert** (Z. 1762, 1781). Kein
intensitätsabhängiger Temperaturverlauf (dunkles Tiefrot → sattes Rot →
Orangerot), kein langsamer Hue-Drift. (Wellen und Funken haben eigene, ebenso
feste Farben: Z. 1801–1802, 1853.) Nebenwirkung: beim Herunterskalieren
quantisieren die drei Kanäle unterschiedlich → der Farbort **rotiert
unkontrolliert** im Dunkeln (die bekannte Grün-Kipp-Physik), statt kontrolliert
wärmer zu werden.

## 5. Fehlende Zwischenzustände — **teilweise** (weitgehend gelöst)

Zwischen den Impulsen ist NICHT Schwarz: Glut-Boden (`red_floor` 0.16) ×
Wander-Glut × Schattenzonen = ein lebendes, driftendes Bett. Zwei Lücken:

- Das Bett ist **energie-blind**: Breakdown und Voll-Groove haben exakt
  denselben Boden — es atmet nicht mit der Musik (keine RMS-/Energie-Kopplung).
- `red_floor` hat **zwei Bedeutungen** (Hüllkurven-Landepunkt UND Bett-Pegel)
  — eine Stellschraube für zwei Wahrnehmungen.

## 6. Ein einziger Auslöser — **ja**

Alles Rote hängt am Kick-Onset-Pfad (`warn_kick`): Snap, Wellen, Funken,
`kick_boost` (Z. 1279–1345). Der Bass fließt nur als Mischterm in die
Einmal-pro-Beat-Stärke ein (disco app.py:1077) — es gibt **keinen
kontinuierlichen Bass-Pegel am Strip** (zwischen Kicks friert `kick_boost` auf
dem letzten Wert ein, Z. 1858). Eine Bassline ohne Kick ist unsichtbar; Snares,
Flächen, Downbeat-Betonung haben keinen Ausdruck. Das per Brief vermutete
„transient vs. tonal im Bassband"-Defizit **bestätigt sich vollständig** —
disco berechnet `bass_level` (audio_engine.py:631–639) bereits kontinuierlich,
er wird nur nie an den Strip übertragen.

## 7. 8-Bit-Stufen — **ja**

Im Glut-Boden-Bereich sichtbar:

- `Color(int(hr·f), …)` **trunkiert** statt zu runden (Z. 1762, 1781).
- Blau-Kanal 55: am Boden `55 × 0.16 × glow(0.45..1)` ≈ 4–9, nach der
  Strip-LUT (`led_brightness` 100 → ×0.39) **1–3** → ein LSB-Schritt ist
  30–50 % relative Helligkeit; dazu die hart codierte Treiber-Gamma
  (`ws2812-pio-rp1`), die untere Werte weiter spreizt.
- Die smoothstep-Änderung pro 20-ms-Frame ist am Boden **sub-LSB** → der Wert
  steht, springt eine Treppe, steht — genau die „Stufen im unteren Bereich"
  aus dem Brief. Es gibt **kein Dithering** im roten Pfad.

Die Treiber-Gamma selbst ist unantastbar (Kernel); die Gegenmaßnahme
(temporales Dithering + Rundung im Renderer) fehlt.

## 8. Frame-Timing — **nein**

Kein Befund. Die Hüllkurve ist eine reine Funktion von `t` (monotone,
injizierbare Uhr — delta-time-sauber, kein akkumulierender Fehler); der
Sustain zeichnet kontinuierlich mit 20-ms-Schreibboden (Z. 1702–1708) bei
8-ms-Loop-Poll (Z. 2150); live 0 dropped frames. Die sichtbare Stufigkeit
kommt aus Ursache 7 (Quantisierung), nicht aus dem Timing.

---

## Priorisierung für den Plan

| Prio | Ursache | Hebel |
|---|---|---|
| 1 | **6** (ein Auslöser) | Bass-Envelope getrennt vom Kick an den Strip — der größte Einzelhebel, Daten existieren schon |
| 2 | **1** (Einheitsbrei) | Perzentil-Velocity je Schlag (Quantil-Statistik nur LESEN) + nichtlineares Mapping auf Peak/Dauer/Ausbreitung |
| 3 | **2** (Retrigger-Teleport) | ADSR-Pulse additiv stapeln mit soft-knee statt Phasen-Reset |
| 4 | **4** (Farbe statisch) | Intensität→Temperatur-Rampe (Oklab), harte Nie-Richtung-Weiß-Kappe |
| 5 | **7** (Stufen) | Temporales Dithering + Rundung im organischen Pfad |
| 6 | **3** (Herkunft) | Bloom expandiert radial vom gewürfelten Ursprung (schnell — Punch bleibt) |
| 7 | **5** (Bett energie-blind) | Bett-Pegel an träge Energie-EMA koppeln |

Ursache 8 braucht keine Maßnahme.

## Gesperrte Bereiche — Berührungspunkte, die der Plan meiden muss

- `_warn_kick_strength` (disco) speist AUCH die Weiß-Klassifikation
  (`_white_kick`) und den Poisson-Scheduler → **bleibt unverändert**; Velocity
  wird als ZUSÄTZLICHES Feld übertragen.
- Die `strength` im `warn_kick`-POST speist in lichtwerk die
  **Drop-Erkennung** (`iris_kick_avg`/`drop_ks` → Drop-Blinder = Weiß,
  Z. 1326–1338) → das Feld bleibt bit-identisch belegt.
- `iris_rng` (seedbare Effekt-RNG) speist die **Sparkle-Spot-Positionen**
  (Weiß). Der organische Pfad würfelt aus einer **eigenen** RNG, damit die
  geteilte Ziehungssequenz — und damit jedes Weiß-Frame — unangetastet bleibt.
