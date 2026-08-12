# Weiße Akzent-Effekte — Plan (Phase 2)

Stand 2026-08-12, Branch `iris-white-effects`. Basis: `docs/white-effects-analysis.md`.
Beschlossen (Phase 1): Iris-Pipeline-Integration · Flashes kurz + gain-gedeckelt
(55-%-Klasse, Launch default aus) · nur ereignis-lokales Ducking (kein globaler
Deckel) · Ambient-Glitzer wird gebaut, default AUS.

## Architektur — ein Satz

disco entscheidet **wann und was** (Director als Ausbau von Scheduler + Picker),
lichtwerk **rendert** (zwei neue `warn_event`-Kinds `meteor` + `stardust` in der
bewährten Blinder-Plan-Maschine); der alte Deko-`effect_meteor` bleibt unberührt.

## Module

### W1 · `iris_render.py` (lichtwerk, NEU — pure Rendering-Hilfsschicht)

Reine Funktionen, kein Hardware-/Controller-Import, vollständig unit-getestet:

| Funktion | Zweck |
|---|---|
| `line_energy(p0, p1, n) -> [(idx, anteil)]` | **Line-Integral/Motion-Blur:** Energie der im Frame überstrichenen Strecke `p0→p1` (float) auf alle berührten LEDs, Randpixel anteilig. Invariante: `sum(anteile) == |p1-p0|` (bzw. geclippter Teil), **lückenlos bei jeder Geschwindigkeit**. |
| `point_aa(pos) -> ((i, 1-frac), (i+1, frac))` | Sub-Pixel-Punkt für 1-px-Akzente (Sparkles). |
| `temp_to_rgb(kelvin) -> (r, g, b)` | Farbtemperatur 1000–12000 K (Tanner-Helland-Approximation, tabellenfrei) für Schweif-Gradient + Sparkle-Streuung. |
| `powerlaw_brightness(u, k) -> float` | Helligkeitsverteilung `u^k` — viele schwache, wenige helle. |
| `blue_noise_positions(rng, count, n, min_dist)` | Poisson-Disk per Best-Candidate (kein Dep): Sparkle-Positionen ohne Verklumpung. |
| `spark_envelope(age, life, attack_frac)` | Attack/Decay-Hüllkurve, nie hartes An/Aus. |
| `perceptual(v)` | γ≈2,2-Encode für Schweifprofil (exponentiell im *Licht*-, nicht im 8-bit-Raum). |

Kein Verhaltensänderung an Bestehendem — eigener Commit.

### W2 · Meteor (lichtwerk, Kind `meteor`)

**Plan-Datenstruktur** (Single-Slot wie alle Blinder-Pläne, aber `mode='duck'`
statt Rot-aus — NEU):

```python
{'t0': t, 'type': 'meteor',
 'v0': 1800.0,          # LED/s Startgeschwindigkeit
 'profile': 'expo_out', # const | expo_out (Whip) | accel
 'dir': +1, 'origin': -trail_len,   # startet AUSSERHALB, fliegt herein
 'trail_s': 0.35,       # Schweif-Zeitkonstante (an v gekoppelt)
 'gain': 1.0, 'seed_off': int,      # per-Meteor-Jitter-Basis
 'pre_dip_s': 0.12, 'duck': 0.35,   # Einatmen + Basis-Ducking im Flug
 'impact': True, 'launch': False}
```

* **Bewegung:** `pos(t)` analytisch aus dem Profil (delta-time, LED/s);
  pro Frame wird die Strecke `pos(t_prev)→pos(t)` per `line_energy` gerendert —
  kein Punkt-Hopping, bei 3000 LED/s genauso lückenlos wie bei 300.
* **Schweif:** exponentielles Profil hinter dem Kopf im linearen Lichtraum
  (`perceptual`-Encode am Ende), Länge ∝ Geschwindigkeit, per-Pixel-Jitter
  5–15 % (deterministischer Hash aus `(pixel, seed_off)` — ⚠️ mit u32-Cast,
  die usize-Falle aus dem Beat-Detektor). Farbtemperatur-Gradient: Kopf
  ~7500 K (minimal kühl) → ~3200 K warm → Glut-Rot → dunkel.
* **Kopf:** Overdrive-Gain + Gauss-Bloom ±2 px (existierendes Muster).
* **Compositing `mode='duck'` (NEU):** Basis-Rot läuft weiter, aber ×`duck`
  (0,35) während des Flugs; Pre-Dip = weicher Ramp auf `duck` in den
  80–150 ms VOR dem Start (der Plan beginnt bei `t0`, der Meteor fliegt ab
  `t0 + pre_dip_s`). Nach Impact Ramp zurück (~200 ms). ⚠️ LUT-Falle: Duck-
  Frames neutralisieren die Strip-LUT (Weiß braucht absolute Stromklasse) und
  **kompensieren das Rot manuell um `led_brightness/255`** — sonst springt die
  Basis-Helligkeit an den Plan-Grenzen.
* **Impact-Flash:** ≤ 60 ms Vollfläche Warmweiß, Gain ≤ `flash_gain` (0,35 ≈
  55-%-Klasse), plus Rückwelle: reflektierter Kurz-Schweif mit 20–30 %
  Amplitude über ~150 LED. **Launch-Flash:** implementiert, default AUS.
  Beide einzeln schaltbar; globale `max_flash_rate_hz`-Bremse (default 1,0 —
  konservativ unter jeder Stroboskop-Schwelle; teilt sich den Zähler mit dem
  Drop-Blinder).
* **Pool:** max `meteor_max_concurrent` (2) Meteore in EINEM Plan (versetzte
  Starts, gewürfelte v/Schweif/Helligkeit aus `iris_rng`) — fester Array im
  Plan, keine Allokation im Frame.

### W3 · Stardust (lichtwerk, Kind `stardust`)

* **Burst-Modus:** beim Intake werden ≤ `stardust_max_particles` (120) Partikel
  **vorgeneriert** (deterministisch aus `iris_rng`): Position (Blue-Noise,
  `min_dist` 4 px), Geburt (Poisson über die Burst-Dauer), Leben 40–250 ms,
  Peak nach Potenzgesetz (k=2,5), Attack 25 % des Lebens, Farbtemperatur
  4000–8000 K gestreut (einzelne kühle Ausreißer = Diamant-Glitzer; kühle
  Töne nur auf Partikeln mit hoher Duty — die Blau-Die-Physik verbietet
  flächiges Blau, nicht einzelne helle Funken). Rendering pro Frame = Schleife
  über lebende Partikel (≤ ~40 gleichzeitig), `point_aa`-Platzierung.
* **Ambient-Layer:** gleiche Engine als Dauerschleife mit sehr niedriger
  Poisson-Rate, **default AUS** (`stardust_ambient` 0.0 = aus); Dichte von der
  Hochband-Energie moduliert, sobald der Director sie liefert.
* **Funkenflug (Meteor-Kopplung):** der Meteor-Plan trägt optional eingebettete
  Stardust-Partikel entlang der Bahn — Geburt = Durchflugzeit + 40–120 ms
  Verzögerung, Position ±3 px um die Bahn. Ein Schalter (`meteor_sparks`).
* Ersetzt im D2-Picker perspektivisch das flächige `shimmer` NICHT — Stardust
  wird als **fünfte Variante** ins Pool aufgenommen (Gewicht 20), shimmer
  bleibt.

### W4 · Director (disco, `white_director.py` — Ausbau von Scheduler+Picker)

* **Tiers:** Stardust/Burst-Varianten = häufig (der bestehende Poisson-Pfad,
  Picker-Pool um `stardust` erweitert); `meteor` ist NICHT im Pool — er hat
  einen eigenen seltenen Pfad: starker Onset (≥ p90 des Tracks) **oder**
  Build-up→Release, mit Budget + Cooldown.
* **Budget/Cooldown:** `meteor_cooldown_s` (25), `meteor_budget` (max 3 pro
  120 s, Sliding Window). Seltenheit ist die Wirkung — die Zahlen sind Config.
* **Build-up-Erkennung:** Energie-EMA-Steigung über `build_window_s` (4 s);
  anhaltend positiver Trend ⇒ Sparkle-Dichte des Ambient-/Burst-Pfads
  graduell ×(1+build_gain·Trend); auf den ersten sehr starken Kick nach einem
  Build (Release) feuert der Meteor bevorzugt. Pure, injizierbare Uhr, Tests
  mit synthetischen Energieverläufen.
* **Hochband:** `audio_engine.py` exponiert `high_level` (Bänder 18–23,
  gleiche Glättung wie `bass_level`) — ein Attribut-Mirror, kein neuer
  HTTP-Kanal: es reist im bestehenden Event-Payload (`hb`-Feld) und
  moduliert lichtwerk-seitig nichts weiter (Director sitzt in disco).
* **Ducking/No-Repeat/Refraktär:** bleiben wo sie sind (Renderer-Duck im Plan,
  no-repeat im Picker, min_gap im Scheduler) — der Director ORCHESTRIERT nur.
* `lichtwerk_client.warn_event`: neue Felder (`v`, `profile`, `sparks`, `hb`)
  explizit durchreichen (⚠️ D2-Lektion, Test pinnt das).

## Konfig-Parameter (iris_config.py bzw. white_config.py)

| Parameter | Default | Range | Begründung |
|---|---|---|---|
| `meteor_enabled` (L) | true | bool | Renderer-Master; inert ohne Events |
| `meteor_v_min` / `meteor_v_max` (L) | 900 / 2400 LED/s | 200–4000 | 600 px in 0,25–0,65 s = „Whip" ohne Blur-Verlust; Line-Integral trägt jede Rate |
| `meteor_profile` (L) | expo_out | const/expo_out/accel | Whip-Gefühl per Default |
| `meteor_trail_s` (L) | 0,35 | 0,1–1,0 | Schweif-Sichtbarkeit bei 50 fps; ∝ v skaliert |
| `meteor_jitter` (L) | 0,10 | 0–0,3 | 5–15 % Glut-Körnung lt. Brief |
| `meteor_head_gain` (L) | 1,0 | 0,3–1,0 | absolute Stromklasse wie Blinder |
| `meteor_duck` (L) | 0,35 | 0–1 | Kontrast durch Absenken, nicht Clipping |
| `meteor_pre_dip_s` (L) | 0,12 | 0,05–0,3 | „Einatmen" 80–150 ms lt. Brief |
| `meteor_impact` / `meteor_launch` (L) | true / **false** | bool | Physik-Entscheid Phase 1 |
| `flash_gain` (L) | 0,35 | 0,1–0,55 | 55-%-Stromklasse, Grün-Drift-sicher |
| `flash_max_ms` (L) | 60 | 20–120 | kurze Transienten driften nicht |
| `max_flash_rate_hz` (L) | 1,0 | 0,2–3,0 | konservativ; teilt Zähler mit Drop |
| `meteor_max_concurrent` (L) | 2 | 1–4 | Pool-Deckel, keine Frame-Allokation |
| `meteor_sparks` (L) | true | bool | Funkenflug-Kopplung |
| `stardust_enabled` (L) | true | bool | Renderer-Master |
| `stardust_max_particles` (L) | 120 | 20–300 | Budget: ≤0,1 ms/Frame |
| `stardust_life_min/max_ms` (L) | 40 / 250 | 20–500 | Brief-Vorgabe |
| `stardust_powerlaw_k` (L) | 2,5 | 1–5 | Sternenstaub-Verteilung |
| `stardust_min_dist` (L) | 4 px | 1–20 | Blue-Noise-Abstand |
| `stardust_temp_min/max` (L) | 4000 / 8000 K | 2500–10000 | Diamant-Streuung |
| `stardust_ambient` (L) | 0,0 (aus) | 0–3 Sparkles/s | Phase-1-Entscheid: default aus |
| `w_stardust` (D) | 20 | 0–100 | fünfte Picker-Variante |
| `meteor_cooldown_s` (D) | 25 | 5–120 | Seltenheit = Wirkung |
| `meteor_budget` / `budget_window_s` (D) | 3 / 120 | 1–10 / 30–600 | Kontingent |
| `meteor_kick_pct` (D) | 0,90 | 0,5–0,99 | nur Ausnahme-Onsets |
| `build_window_s` / `build_gain` (D) | 4 / 1,0 | 2–15 / 0–3 | Build-up-Dramaturgie |

(L) = lichtwerk `iris_config.py`, (D) = disco `white_config.py`. Env-Overrides
im bestehenden `DISCO_WHITE_*`-Stil.

## Performance-Abschätzung (gegen 0,53 ms/Frame Ist, >15 ms Budget)

| Effekt | Kosten/Frame | Herleitung |
|---|---|---|
| Meteor | ~0,15–0,35 ms | Line-Integral über (v·0,02 s + Schweif) ≈ 60–160 px Python-Loop |
| Stardust | <0,1 ms | ≤40 lebende Partikel × ~6 Ops |
| Duck-Compositing | ~0 | multipliziert in den existierenden Basis-Loop |
| Director (disco) | ~0 | Block-Takt-Arithmetik, kein FFT-Zusatz |

Worst-Case gesamt < 1 ms Zuschlag ⇒ weit im Budget. Frame-Zeit wird vor/nach
jedem Schritt mit dem Mess-Snippet aus Phase 0 ausgewiesen.

## Testkriterien

1. **Bewegungsqualität (Brief-Pflicht):** `line_energy`-Invarianten (Summe =
   Streckenlänge, lückenlos) + Integrationstest: Meteor bei `v_min` UND
   `v_max` über den ganzen Strip — **keine LED zwischen Start und Ende bleibt
   bei 0 Gesamtenergie**, kein Frame malt eine Lücke zwischen `pos_prev` und
   `pos`.
2. **Golden-Frame:** BASELINE_OFF-Hash unverändert (neue Kinds = neue Pfade);
   Defaults-Determinismus-Test erweitert um je einen Meteor-/Stardust-Lauf.
3. **Stardust:** Lebensdauer ≥ 2 Frames erzwungen; Blue-Noise-Mindestabstand;
   Potenzgesetz (Median ≪ Mittel der Peaks); Hüllkurve nie hartes An/Aus.
4. **Duck:** Basis-Helligkeit an Plan-Grenzen stetig (LUT-Kompensation exakt;
   Differenz-Test zweier deterministischer Läufe).
5. **Flash-Bremse:** `max_flash_rate_hz` hält auch bei Event-Spam (Test feuert
   10 Meteore/s, zählt Vollflächen-Frames).
6. **Director:** Poisson-Statistik bleibt (bestehende Suite), Meteor-Budget/
   Cooldown/Build-up mit synthetischen Verläufen, no-repeat inkl. stardust.
7. **Offline-Sichtprüfung:** `tools/frame_dump.py` — FakeStrip + Fake-Uhr,
   Ausgabe als ASCII-Zeilen (Helligkeitsrampe) und/oder PPM-Streifenbild je
   Frame; Debug-Trigger bleibt `curl /api/warn_event` (existiert).
8. **Protokoll:** Journal-Breadcrumb je Event mit Parametern + Dauer
   (bestehendes Muster erweitert).

## Risiken

* **Duck-Compositing ist der invasivste Teil** (erste Plan-Art, die Rot NICHT
  abschaltet): LUT-Kompensation falsch ⇒ Helligkeitssprung. Mitigation:
  exakte Gegenrechnung, Differenz-Tests, eigener Commit, Schalter
  (`meteor_duck` 1,0 = kein Duck).
* **Single-Slot-Plan:** ein ~1-s-Meteor verdrängt währenddessen ankommende
  Events (verderblich — bewusst); Meteor-Dauer wird über `v_min` nach oben
  begrenzt (≤ ~1,2 s inkl. Schweif-Austritt).
* **Photosensitivität:** `max_flash_rate_hz` default 1,0; Impact-Flash klein.
* **Strom/Drift:** Flashes ≤ 60 ms + Gain 0,35; Stardust sparse per Design;
  kühle Farbtöne nur auf hellen Einzelpartikeln.
* **Deploy-Reihenfolge:** lichtwerk (Renderer, inert) VOR disco (Director) —
  wie bei L6/D2.
* **Keine neuen Dependencies** (Blue-Noise per Best-Candidate, Farbtemperatur
  per Formel).

## Schritte (je einzeln commit-fähig + schaltbar)

W1 Rendering-Grundlage (`iris_render.py`, pure + Tests, kein Verhalten) →
W2 Meteor (Renderer + Duck + Flashes + Tests + frame_dump) →
W3 Stardust (Burst + Ambient[aus] + Funkenflug + Tests) →
W4 Director (disco: high_level, Build-up, Budget, Picker + Tests, Live-E2E).

Nach jedem Schritt: Suite grün → Deploy → Live-Check (curl-Trigger + Journal +
Sichttest) → Commit auf `iris-white-effects`. Merge erst nach Gesamtabnahme.
