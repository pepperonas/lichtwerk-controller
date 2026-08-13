# Plan: red_organic — Glut und Puls statt Signalleuchte

Phase 2 des Rot-Briefs (2026-08-13). Priorisierung aus
[red-diagnosis.md](./red-diagnosis.md). Der Nutzer hat den Durchlauf ohne
Zwischen-Freigabe angeordnet („setze das sorgfältig um") — die Phase-1-
Rückfragen sind darum hier als **dokumentierte Entscheidungen** geführt, jede
per Config umkehrbar.

## Architektur

**Ein Profil-Schalter, zwei Pfade:** `iris.red_profile` = `"classic"`
(Code-Default, bit-identisch zur Baseline — Golden-Frame-Hash beweist es)
oder `"organic"`. Live umschaltbar über `POST /api/iris/profile
{"profile": "organic"|"classic"}` (wirkt sofort in-memory + persistiert in
config.json) — der A/B-Vergleich aus dem Brief.

Der organische Pfad ersetzt NUR die Berechnung des roten Felds (Skalar
`red_env` × Einheitsfarbe → **per-Block-Feld mit Farbrampe**). Unverändert
bleiben: Engage-Doppelpuls, Takt-/Snap-Maschinerie, Wellen- und
Funken-Overlays, Blinder-Interplay (Weiß gewinnt exakt wie heute:
`lit = blinder[0]`, Meteor-Duck multipliziert), Heartbeat/Schreibtakt, LUT-
Logik, `clear()`-Semantik.

**Neue Dateien:** lichtwerk `red_organic.py` (pure, unit-getestet), disco
`red_feed.py` (pure). Keine neuen Abhängigkeiten, keine Allokation im
Render-Pfad (Pulse-Liste ist gekappt, Gradient vorberechnet).

## Maßnahmen (Reihenfolge = Diagnose-Priorität)

### M1 — Bass-Envelope getrennt vom Kick (Ursache 6)
disco sendet den bereits berechneten `bass_level` an den Strip:
(a) als Feld `bass` im bestehenden `warn_kick`-POST (kostenlos), (b) als
neuer, gedrosselter POST **`/api/warn_bass {level}`** (≤ 5 Hz, nur bei
Δ ≥ 0.02, nur bei aktivem Warn; fire-and-forget mit In-Flight-Guard wie
warn_kick). lichtwerk glättet asymmetrisch (auf 0.12 s, ab 0.45 s) und
rendert eine **träge Druckwelle von beiden Strip-Enden** zur Mitte — der
„Woofer zum Anschauen". Kontrakt: additiver 6. POST, alte Renderer ohne den
Endpoint antworten 404 ins Leere (harmlos); `DISCO_RED_FEED=0` schaltet die
Speisung komplett ab.

### M2 — Perzentil-Velocity (Ursache 1)
disco `red_feed.velocity_rank(hist, s)`: Rang der aktuellen Kick-Stärke in
der rollenden Verteilung, die `white_events` ohnehin führt (`_strengths` —
**nur gelesen**, Datei unangetastet). Als Feld `vel` im warn_kick-POST.
`strength` bleibt **bit-identisch** belegt (speist Drop-Erkennung = Weiß).
Renderer: `peak = vel^organic_vel_gamma` (perzeptuell), Velocity skaliert
zusätzlich Decay-Dauer und Ausbreitungsradius. Fallback ohne `vel`-Feld
(alter Client): heutige Ableitung aus `strength`.

### M3 — ADSR-Pulse additiv stapeln (Ursache 2)
Statt Phasen-Reset: jeder Kick erzeugt einen **Puls** {born, vel, origin}.
Hüllkurve je Puls: s-förmiger Attack (`organic_attack_ms`), exponentieller
Anfangs-Decay auf einen Sustain-Anteil (`organic_sustain`), Sustain-Schwanz
(`organic_tail_ms`) der ins Bett übergeht — alles analytische Funktionen des
Alters (delta-time). Pulse **summieren mit soft-knee** Richtung 1.0
(`organic_knee`) — Retrigger stapelt statt zu springen, das Knacksen ist weg.
Cap `organic_pulse_max` (älteste fliegen). Im Freilauf spawnt der
Perioden-Wrap synthetische Pulse (vel ≈ 0.45) — ohne Kicks bleibt das Bild
lebendig wie heute.

### M4 — Farbrampe in Oklab (Ursache 4)
32-stufiger Gradient, **in Oklab interpoliert** (kompakte Implementierung in
red_organic.py, nur beim Gradient-Bau — kein Frame-Kostenpunkt): dunkles
Tiefrot → sattes Rot (≈ der klassische Farbort bei ~0.7) → glühendes
Orangerot an der Spitze. Lokale Feld-Intensität indiziert den Gradient.
**Harte Nie-Weiß-Kappe: G ≤ 140, B ≤ 90, R strikt dominant** — im Gradient-Bau
erzwungen und im Test gepinnt (der Kontrast zu den Weiß-Akzenten ist
gesperrtes Terrain). Dazu minimaler Hue-Drift (±`organic_hue_drift` Stufen,
Periode Minuten) — nie exakt dasselbe Bild, bleibt immer „rot".

### M5 — Temporales Dithering + Rundung (Ursache 7)
Im organischen Pfad: Kanalwert = `floor(v + hash01(block, frame, kanal))`
statt `int(v)` — der Erwartungswert ist exakt v, bei 50 fps mittelt das Auge
die Zwischenstufe. Block-weise (150 Hashes × 3 Kanäle/Frame — billig),
deterministisch (testbar), `organic_dither=false` schaltet ab.

### M6 — Bloom mit Herkunft (Ursache 3)
Jeder Puls expandiert **radial vom gewürfelten Ursprung** (Mitte-bias wie die
Wellen): Deckung = weiche Front, die in `organic_spread_ms` (Velocity-
skaliert) den Strip füllt. Schnell genug, dass der Punch global bleibt
(~150–250 ms), aber der Schlag hat sichtbar Herkunft und Laufrichtung.
**Eigene RNG** (`iris_rng_org`) — die geteilte `iris_rng`-Ziehungssequenz
(Sparkle-Spots = Weiß!) bleibt byte-identisch.

### M7 — Energie-gekoppeltes Bett (Ursache 5)
Bett-Pegel = `organic_bed_min` + (`organic_bed_max` − min) × Energie-EMA
(τ ≈ 4 s aus der Bass-Envelope). Breakdown: Bett sinkt Richtung dunkel;
Groove: lebendiger. Wander-Glut × Schattenzonen wirken unverändert darauf.

**Bewusst NICHT in dieser Runde:** eigener Snare-/Clap-Trigger (bräuchte
einen neuen Band-Detektor im Audio-Callback; `high_level` existiert, aber ein
halbgarer Snare-Pfad wäre schlimmer als keiner) und Downbeat-Betonung
(Beat-Phase gibt es erst unter trigger_v2, das AUS ist). Beide als Follow-up
dokumentiert.

## Neue Parameter (iris_config, alle geklemmt)

| Key | Default | Range | Begründung |
|---|---|---|---|
| `red_profile` | `"classic"` | classic\|organic | Rollback-Pfad; unbekannte Werte = classic |
| `organic_attack_ms` | 14 | 5–40 | Brief: 5–20 ms geformter Attack |
| `organic_decay_ms` | 240 | 80–800 | kräftiger Anfangs-Decay (Basis, ×Velocity) |
| `organic_sustain` | 0.30 | 0.0–0.7 | Sustain-Anteil rel. Peak |
| `organic_tail_ms` | 340 | 100–900 | Brief: Sustain-Schwanz 100–400 ms |
| `organic_vel_gamma` | 0.65 | 0.3–2.0 | perzeptuelle power curve Velocity→Peak |
| `organic_vel_floor` | 0.18 | 0.0–0.6 | zartester Schlag bleibt sichtbar |
| `organic_pulse_max` | 6 | 2–10 | Stapel-Kappe (Allokations-Deckel) |
| `organic_spread_ms` | 180 | 60–600 | Bloom-Expansion bis Vollabdeckung |
| `organic_knee` | 0.80 | 0.5–0.95 | soft-knee-Beginn der Summensättigung |
| `organic_bed_min` | 0.06 | 0.0–0.3 | Bett im Breakdown |
| `organic_bed_max` | 0.20 | 0.05–0.4 | Bett im Groove |
| `organic_bass_gain` | 0.45 | 0.0–1.0 | Druckwellen-Anteil |
| `organic_bass_up_s` | 0.12 | 0.03–1.0 | Bass-Attack (träge genug gegen Pumpen) |
| `organic_bass_down_s` | 0.45 | 0.1–3.0 | Bass-Release |
| `organic_hue_drift` | 1.5 | 0.0–4.0 | Gradient-Stufen Drift-Amplitude (Minuten) |
| `organic_dither` | true | bool | M5 abschaltbar |
| `organic_g_max` | 140 | 60–160 | Nie-Weiß-Kappe Grün |
| `organic_b_max` | 90 | 20–120 | Nie-Weiß-Kappe Blau |

disco: `DISCO_RED_FEED` (env, Default 1) — vel/bass-Felder + warn_bass-POSTs.

## Performance-Abschätzung

Organischer Mehraufwand pro Frame (600 px = 150 Blöcke, 50 fps):
Pulse-Feld ≤ 6×150 = 900 einfache Ops, Druckwelle 150, Gradient-Lookup 150,
Dithering 450 Hashes → ~2–3k Ops/Frame ≈ 100–150k/s — **einstellige
Prozent** eines Pi-5-Kerns (die bestehende Schattenzonen-Rechnung liegt in
derselben Klasse). Der per-Pixel-Teil wird sogar BILLIGER als classic
(Blockfarbe vorberechnet: 0 Muls/Pixel statt 3). Messkriterium: Frame-Zeit
im Test < 10 ms/Frame (Mac, großzügig), live `dropped_frames == 0`.

## Testkriterien (aus dem Brief)

1. Golden-Frame-Hash (classic, Default) **unverändert** — Rollback-Beweis.
2. Weiß-Pixel-Identität: Frames während eines Sparkle-Blinder-Fensters sind
   **byte-identisch** zwischen classic und organic (gleicher Seed) — Weiß
   sticht exakt wie heute heraus.
3. Retrigger: zweiter Kick mitten im Verglimmen erzeugt **keinen
   Abwärtssprung** der mittleren Helligkeit (Stack statt Teleport).
4. Velocity: vel 0.2 vs. 1.0 unterscheiden sich sichtbar in Peak (>25 %
   Felddifferenz) — monotone Kopplung.
5. Farbkappe: jeder Gradient-Eintrag hält G ≤ g_max, B ≤ b_max, R dominant.
6. Dithering: zeitlicher Mittelwert ≈ Sollwert (±0.1 LSB), deterministisch.
7. Bass ohne Kick: warn_bass-Pegel allein bewegt das Feld (Druckwelle).
8. Alle Bestands-Suites grün (lichtwerk 195, disco 282) — insbesondere die
   Weiß-Budget-, Parity- und Golden-Pins.

## Rollback-Matrix

| Ebene | Weg | Dauer |
|---|---|---|
| Profil | `POST /api/iris/profile {"profile":"classic"}` | Sekunden, live |
| Feature einzeln | iris-Config-Key (z. B. `organic_dither: false`) + Restart | 1 min |
| Speisung | `DISCO_RED_FEED=0` in disco-.env + Restart | 1 min |
| Code | Tag `iris-red-baseline-2026-08-13` + scp (OPERATIONS.md) | 5 min |
