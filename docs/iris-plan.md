# Iris Mode — Umsetzungsplan (Phase 2, 2026-08-12)

Basis: `docs/iris-mode-baseline.md`. Freigegebene Phase-1-Antworten:
Scope = Strip-Warn-System · Weiß = **Hybrid** (Poisson-Grundrate + bestehende
Events, Beat-Snapping) · Ziel-Rate 4–8/min energetisch, 1–2/min ruhig,
min_gap 2,5 s · Farbe als Config-Palette (`classic` Default, `glow` neu) ·
Kick-Stärke → roter Puls ±30 % + Engage-Variation · **kein numpy** ·
Hysterese nur in Effekt-Ketten, Warn-Gate bleibt live · Offline-Harness mit
Feature-JSONL + synthetischen Kicks.

**Stack-/Pipeline-Änderung: keine empfohlen.** FFT/Onset/BPM existieren;
pure-Python-Renderer reicht (0,90 ms/Frame gemessen, Decke = 18 ms Draht).
Verworfen: numpy im Renderer (neue Abhängigkeit ohne Not), Goertzel/
Filterbank (FFT ist da), Frame-Streaming statt Events (Latenz + Kopplung).

---

## Architektur-Leitentscheidungen

1. **„Events, nicht Frames" bleibt.** Der Poisson-Scheduler lebt in **disco**
   (dort sind Onset-Dichte, Energie, Beat-Timing) und postet erweiterte
   `warn_event`-Payloads; lichtwerk bleibt dummer, deterministischer Renderer.
2. **Zentrale Config statt Magic Numbers.** Neues Modul `iris_config.py`
   (lichtwerk) bzw. `white_config.py` (disco): alle Iris-Parameter als
   Defaults im Code, überschreibbar per `config.json`-Sektion `iris` (lichtwerk)
   bzw. `.env`/`white_events.json` (disco). Jede NEUE Verhaltensweise hat
   einen eigenen Schalter; **alle Schalter aus = bit-identisch zur Baseline**
   (Golden-Frame-Test sichert das ab).
3. **Seedbarer RNG.** Je Prozess eine `random.Random(seed)`-Instanz
   (`iris.seed`, Default `null` = nicht deterministisch); alle Zufallsanteile
   (Scheduler, Varianten, Positionen, Jitter) laufen ausschließlich darüber.
4. **Strom-Doktrin.** Compositing darf das Peak-Duty-Budget der Baseline
   (Vollrot + Sparse-Weiß) nicht überschreiten: Blend = `screen` (beschränkt)
   bzw. add mit Clamp + Budget-Guard (geschätztes Post-Gamma-Duty pro Frame).
5. **Zombie-Doktrin.** Jeder neue Effekt-Zustand mit Zeitstempeln wird im
   Effekt-Init zurückgesetzt (iris_t0 resettet je Warn-Flanke).

---

## Schritte (jeder einzeln commit-fähig, per Config abschaltbar)

### Block L — lichtwerk (Renderer)

**L1 · Config-Extraktion + Seed-RNG (bit-identisch).**
Neu: `iris_config.py` (Defaults + `config.json`-Merge + Validierung),
`effect_iris_warn` liest alle heutigen Magic Numbers von dort; RNG-Instanz.
*Dateien:* `web_controller.py`, neu `iris_config.py`. *Absicherung:*
Golden-Frame-Test (FakeStrip-Buffer-Hash über eine feste Frame-Sequenz mit
Seed) beweist Bit-Identität; bestehende 138 Tests bleiben grün.

**L2 · Rot-Dynamik.** (a) `red_punch` — Peak des Schlags folgt der gemessenen
Kick-Stärke; (b) `freerun_humanize` — Freilauf-Periode als langsamer Random-
Walk statt exakter 0,55 s; (c) `engage_variety` — Engage-Puls-Timing leicht
variiert je Flanke. *Fix für Schwachstellen 1/2/6.*

**L3 · Wellen-/Funken-Vielfalt.** `wave_variety`: Ursprung gewichtet
randomisiert (Mitte-bias, aber nie fix), Richtung ein-/beidseitig, Breite/
Tempo-Jitter; Funken-Fensterdauer leicht randomisiert. *Fix Schwachstelle 5.*

**L4 · Farb-Pipeline.** `palette: classic|glow`. `glow`: Hue-Jitter
(350°–15°), Sättigung/Value getrennt moduliert, **Farbtemperatur ∝
Intensität** (dunkelrot → glutrot → orange-weiß am Peak), Interpolation in
**Oklab** (kleines pure-Python-Modul + LUT-Cache, kein numpy); One-Pole-
Glättung aller Farbsteuerwerte. Kernel-Gamma bleibt die Ausgabe-Gamma;
temporales Dithering nur falls Stufen sichtbar (eigener Schalter,
Default aus — der Kernel quantisiert ohnehin). *Fix Schwachstelle 8.*

**L5 · Layer-Compositing.** `compositing: replace|screen`. Struktur:
Ambient (Atmen + Glut + Schatten) → Beat (Wellen + Funken) → Accent
(Sparkle, höchste Priorität) mit Screen-Blend + Clamp + Budget-Guard.
Ambient bekommt zusätzlich langsames wertiges Rauschen (kleines
Simplex/Value-Noise-Modul, pure Python, block-granular). *Riskantester
Schritt — deshalb zuletzt im L-Block, eigener Schalter.*

**L6 · Varianten-Rendering.** `warn_event`-Payload wird erweitert
(abwärtskompatibel, alles optional mit heutigen Defaults):
`{kind, gap_ms, n, s, dur_ms, intensity, density, origin, dir, variant}`.
Renderer setzt Dauer/Intensität/Dichte/Startposition/Richtung um.

**L7 · Offline-Harness Renderer.** `tools/iris_sim.py`: Kick-/Event-Timeline
(JSONL) → Frames auf FakeStrip → Metriken: Intervall-Histogramm,
%-unveränderte-Frames, Peak-Duty-Schätzung, Frame-Zeit. Läuft ohne Hardware
und ohne Musik.

### Block D — disco (Erkennung/Scheduler)

**D1 · Stochastischer Weiß-Scheduler.** Neu `white_scheduler.py`
(pur, deterministisch testbar): Poisson-Wartezeiten `-ln(1-u)/λ`,
λ = Basis × f(Onset-Dichte, Energie) mit Clamp; `min_gap`/`max_gap`;
**Beat-Snapping**: fälliger Trigger wartet bis zum nächsten Fast-Onset
(≤ `snap_window_ms`), sonst feuert er zur Deadline. Getickt vom
Audio-Callback (23-ms-Blöcke — keine neuen Threads, keine Sleeps).
Bestehende Detector-Events (double/roll/accent) bleiben als beat-genaue
Zusatz-Trigger und resetten die Poisson-Uhr. Schalter
`white.scheduler=on|off` (off = exakt heutiges Verhalten). Der
40-s-Verhungerungs-Fallback wird vom Scheduler ABGELÖST (max_gap übernimmt
seine Rolle — zufällig statt metronomisch). *Fix Schwachstelle 3.*

**D2 · Varianten-Picker.** Gewichtete Auswahl aus Sub-Varianten
(sparkle-burst, sweep, shimmer, double-echo …) mit „letzte Variante
ausgeschlossen"; randomisiert Dauer/Intensität/Dichte/Ursprung/Richtung
in konfigurierten Ranges; seedbar. Sendet die erweiterte Payload (L6).
*Fix Schwachstelle 4.*

**D3 · Feature-Capture + Harness.** `DISCO_FEATURE_CAPTURE=1` bzw.
`/api/capture {on}`: schreibt JSONL (`t, bass, onset, strength, beat,
fast_onset, bpm, conf`) für echte Musik. `tools/white_sim.py`: JSONL oder
synthetischer Kick-Track-Generator → Detector + Scheduler → Event-Log +
Metriken (Trigger/min, Intervall-Histogramm + CV, Beat-Treffergenauigkeit).

### Reihenfolge & Deploys

L1 → D1 → D2+L6 → L2 → L3 → D3+L7 → L4 → L5. Nach jedem Schritt: Suite grün,
Deploy mit Schalter AUS (Golden-Frame-geprüft), dann Schalter AN + kurzer
Live-Check (Journal-Diagnose + Sichttest), Commit auf `iris-rework`.
Merge nach main erst nach deiner Gesamtabnahme.

---

## Neue Config-Parameter (Auszug — vollständig in den Modulen)

| Parameter | Default | Range | Begründung |
|---|---|---|---|
| `white.scheduler` | on | on/off | Hybrid-Doktrin; off = Baseline |
| `white.lambda_base` | 0,05 /s | 0,01–0,2 | 3/min Grundrate bei Referenz-Energie |
| `white.lambda_max` | 0,14 /s | ≤0,3 | ≈8/min Deckel bei voller Energie (Ziel 4–8) |
| `white.min_gap_ms` | 2500 | 1000–10000 | Refraktärzeit (vorher 5000) |
| `white.max_gap_ms` | 30000 | 10–90 s | Loch-Schutz, ersetzt STARVE_S-Metronom |
| `white.snap_window_ms` | 150 | 0–300 | Zufall sitzt musikalisch; 0 = aus |
| `white.variant_weights` | burst 40/sweep 25/shimmer 20/echo 15 | — | Vielfalt, no-repeat-Regel |
| `iris.seed` | null | int/null | reproduzierbare Tests |
| `iris.red_punch` | 0,3 | 0–0,5 | Peak folgt Kick-Stärke ±30 % |
| `iris.freerun_jitter` | 0,05 | 0–0,15 | Random-Walk statt 0,55-s-Metronom |
| `iris.engage_variety` | on | on/off | Intro variiert je Flanke |
| `iris.wave_variety` | on | on/off | Ursprung/Richtung/Breite randomisiert |
| `iris.palette` | classic | classic/glow | abgenommener Look bleibt Default |
| `iris.glow_hue_jitter_deg` | 8 | 0–15 | 350°–15°-Band |
| `iris.compositing` | replace | replace/screen | L5-Schalter, Budget-Guard |
| `iris.dither` | off | on/off | nur falls Stufen sichtbar |

## Performance-Abschätzung

Baseline-Hot-Path 0,90 ms/Frame. Zuschläge (geschätzt, block-granular):
Noise ~0,1 ms · Oklab-LUT-Farben ~0,2 ms · Screen-Compositing (2. Pass,
600 px) ~0,4 ms · Rest <0,1 ms ⇒ **≤ 1,8 ms/Frame ≈ 9 % eines Kerns @50 fps**
(Decke bleibt Draht-Zeit 18 ms). disco-Zuschlag vernachlässigbar (Scheduler-
Tick = Arithmetik im vorhandenen Callback). Messung vorher/nachher im
Harness (Frame-Zeit-Metrik) UND on-device (Benchmark wie Phase 0);
Ausweis im jeweiligen Commit.

## Testkriterien

1. **Bit-Identität:** Golden-Frame-Hash (Seed + feste Timeline) mit allen
   Schaltern AUS == Baseline; alle bestehenden Suites grün (138 lw/188 disco).
2. **Poisson:** Sim 30 min konstante Energie → Intervalle exponentialverteilt
   (CV ≈ 1 ± 0,15, Histogramm monoton fallend), min_gap nie verletzt,
   max_gap nie überschritten, Rate = λ ± 15 %.
3. **Musikkopplung:** Sim ruhig vs. energetisch → 1–2/min vs. 4–8/min.
4. **Beat-Snapping:** bei dichten Onsets ≥ 80 % der Trigger ≤ snap_window
   am nächsten Onset; ohne Onsets feuern Trigger zur Deadline.
5. **Varianz:** keine unmittelbare Varianten-Wiederholung; Dauer/Intensität/
   Ursprung streuen nachweisbar (Histogramm).
6. **Budget:** geschätztes Peak-Duty je Frame ≤ Baseline-Budget; 0 dropped
   frames im 60-s-Live-Lauf; Frame-Zeit ≤ 2 ms on-device.
7. **Doktrin-Wächter:** Warn-Gate bleibt hysteresefrei (Source-Pin);
   Zombie-Test für alle neuen Zeitstempel-Zustände.

## Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Look-Drift vom abgenommenen Stand | alles hinter Schaltern, classic/replace als Default, Golden-Frame |
| Compositing hebt Stromspitzen | Budget-Guard + screen statt add, Live-Check dropped/Artefakte |
| Payload-Inkompatibilität disco↔lichtwerk bei gestaffeltem Deploy | Payload rein additiv mit Defaults; L6 vor D2 deployen |
| Poisson „fühlt sich falsch an" trotz korrekter Statistik | Geschmacks-Parameter zentral; A/B per Schalter live umschaltbar |
| Zombie-Zustände (Scheduler-Uhren, Noise-Phase) | Init-Reset-Doktrin + Tests |
| Zwei-Repo-Rollback | Tag `iris-baseline-20260812` beidseitig; Schalter-off als Soft-Rollback |
