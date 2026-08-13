# BPM-Integration — Analyse der Quelle (Phase 0, Tempo-Brief 2026-08-13)

Basis: Tag `iris-tempo-baseline-2026-08-13` (disco `28c4020` + lichtwerk
`06acf3c`). ⚠️ Die Disco-App ist in diesem Brief GESPERRT — sie wird hier
nur SEZIERT, nicht verändert (0 Diff im disco-Repo außer Doku).

---

## 1. Wo die BPM entsteht und wie sie veröffentlicht wird

**Erkennung:** disco `audio_engine.py` — Energy-Onset (Kick-Band 30–150 Hz,
SuperFlux-Gate) → IOI-Median-Clustering → **Oktav-Faltung in [60, 200]**
(`while raw < 60: ×2; while > 200: ÷2`) → Oktav-Snap ±8 BPM auf den
gelockten Wert → Anzeige = 4-s-Mittel. Konfidenz = `1 − stddev/median` der
IOIs (0..1). `music_present` = Crest-Kriterium.

**Drei Veröffentlichungswege:**

| Weg | Inhalt | Takt | Kosten für disco | Bewertung |
|---|---|---|---|---|
| **A · `POST /api/warn_kick {strength, bpm, vel, bass}`** (Push an lichtwerk) | bpm (client-seitig auf 50–200 geklemmt), Kick-Stärke, Perzentil-Velocity, Bass-Snapshot — **ein POST je erkanntem Beat, nur bei aktivem Warn** | 1–3,3 Hz (Beat-Pfad, 0,3-s-Refraktär; In-Flight-Guard verwirft statt zu stauen) | **0** (existiert, fire-and-forget Daemon-Thread) | ✅ **der stabilste UND günstigste Weg** — und Rot rendert ohnehin NUR bei aktivem Warn: die Abdeckung ist vollständig |
| B · `POST /api/warn_bass {level}` (Push) | kontinuierlicher Bass-Pegel | ≤ 5 Hz, delta-gated | 0 (existiert) | ✅ liefert die „ruhige Passage"-Info für Teil D gleich mit |
| C · `GET /api/status` (Poll durch lichtwerk) | bpm + **Konfidenz** + music_present + Sektionszustand (nur bei v2/Analysis + Telemetrie) | frei wählbar | ⚠️ **NICHT 0**: jeder Status-Poll füttert das `AUDIO_ACTIVE_WINDOW` (8 s) — ein Dauer-Poll **hebelt den Idle-Fast-Path aus** (die 37 %→3 %-CPU-Optimierung von 2026-07-01) und hielte die volle FFT 24/7 wach | ❌ als Dauerweg; allenfalls Hybrid (nur während Warn) |

**Kern-Erkenntnis:** Der Push-Kanal A+B existiert bereits, kostet disco
nichts Zusätzliches und trägt alles Nötige. Ein Status-Poll wäre der
klassische Integrationsfehler auf diesem Stack (s. ir_bridge-Lektion: die
pollte für jeden Matrix-Modus und hielt disco dauerhaft wach).

## 2. Rate, Latenz, Qualität

- **Aktualisierung:** bpm-Wert je warn_kick = je Beat (1–3,3 Hz bei 60–200
  BPM); der Analyzer aktualisiert intern im 4-s-Mittel — Tempoänderungen
  brauchen ohnehin Sekunden, die Push-Rate ist kein Engpass.
- **Latenz** Musikereignis → Wert verfügbar: Erkennungskette ~90–100 ms
  (gemessen, disco docs/trigger-analysis.md) + HTTP localhost ~1–2 ms.
  Für ZEITKONSTANTEN (nicht Phasen-Snaps) irrelevant.
- **Konfidenz:** liegt NICHT im Payload — aber implizit: der v1-Pfad sendet
  warn_kick **nur bei Konfidenz ≥ 0,15** (app.py `_on_beat`). Ein
  ankommendes bpm-Feld IST also bereits qualitätsgefiltert. Ohne
  Konfidenz-Zahl bleibt lichtwerk-seitige Plausibilisierung Pflicht (§4).
- **Beat-Phase/Downbeat:** nicht im Push. lichtwerk hat aber eine EIGENE
  phasen-gelockte Uhr (Kick-Snap setzt `iris_ph`, Perioden-Wrap =
  Schlagmoment) — Halbtakt-Raster (Teil C, >150 BPM) ist damit OHNE
  Downbeat-Info baubar (Beat-Zähler ab Snap).

## 3. Verhalten in den Randfällen (heute, verifizierter Bestand)

| Fall | Verhalten |
|---|---|
| Stille / Musik unter Schwelle | Kicks bleiben aus → nach `kick_stale` 1,6 s Freilauf 0,55 s (Tag-Verhalten). Warn fällt ohnehin meist ab (Strip idle dunkel) |
| Trackwechsel | bpm-Seed je Kick überschreibt sofort; die Intervall-EMA faltet Ausreißer-Gaps (>1,6×) zurück aufs Raster; Übernahme heute NICHT gerampt (→ Teil A des Briefs) |
| Tempowechsel im Track | 4-s-Mittel im Analyzer + `period_ema` 0,25 in lichtwerk — träge, aber sprunghaft bei Oktav-Kipp |
| disco weg/hängt | KEINE Abhängigkeit: Posts bleiben aus, lichtwerk rendert im Freilauf weiter; kommt disco wieder, fließen Kicks automatisch (kein Handshake). Der Ausfalltest des Briefs ist architektonisch schon erfüllt — die Tempo-Skalierung muss dasselbe Muster nur ERBEN |
| lichtwerk-Neustart | Effekt-Zustand resettet je Engage (Zombie-Doktrin); bpm kommt mit dem nächsten Kick |

## 4. Oktavfehler — explizit geprüft: JA, real

Der Analyzer faltet HART in [60, 200] und misst den **Kick-Kanal**:

- 174-BPM-DnB mit Halftime-Kick (Backbeat) → IOI ≈ 0,69 s → **~87 BPM
  gemeldet** (halbe Rate). Licht würde träge statt straff.
- 70-BPM-HipHop mit dichtem Doppel-Kick → kann als **140** lesen (doppelt).
- >200 echte BPM (Hardcore) → per Faltung halbiert (by design).
- Der ±8-Oktav-Snap STABILISIERT einen einmal gelockten Wert — kippt der
  Lock initial falsch, bleibt er falsch bis zum Reset.
- disco docs/trigger-abnahme.md nennt die Halftime-Ambiguität als bekannte
  ehrliche Grenze (auch der v2-Kette, Prior 130).

**Konsequenz für den Plan:** lichtwerk MUSS gegenprüfen, ohne disco
anzufassen — die eigene Kick-Ankunftsrate ist das Werkzeug: kommen Kicks
im Median-Abstand ≈ ½ × (60/bpm), ist die gemeldete BPM vermutlich
halbiert (und umgekehrt). Sprünge um Faktor ~2 nur nach mehrfacher
Bestätigung übernehmen; dazwischen zählt der gedämpfte Charakter (Exponent
0,6–0,8), der Oktavfehler ohnehin auf ~1,5–1,7× Wirkung staucht.

## 5. Rote Parameter in festen Millisekunden (Fundstellen = web_controller.py / iris_config.py)

**Bereits beat-bezogen (kein Handlungsbedarf):** die classic-Periode selbst
(`iris_beat_ema`/bpm-Seed, geklemmt 0,30–1,20 s), `red_attack` 0,12 /
`red_hold` 0,09 (ANTEILE der Periode).

**Fest in ms/s (Kandidaten für Beat-Bezug):**

| Parameter | Ist | Fundstelle | Beat-Kandidat |
|---|---|---|---|
| `organic_attack_ms` | 14 ms | iris_config | langsam weicher / schnell knackiger (Teil B) |
| `organic_decay_ms` | 240 ms × Gewicht | iris_config | **Hauptträger** — Beats statt ms |
| `organic_tail_ms` | 340 ms | iris_config | Beats |
| `organic_spread_ms` | 180 ms | iris_config | Ausbreitung je Beat |
| `organic_bass_up_s / down_s` | 0,12 / 0,45 s | iris_config | Glättungs-Zeitkonstanten |
| Energie-EMA (Bett) | τ 4,0 s hart | `_organic_blocks` | ~2 Takte |
| Hue-Drift-Periode | 240 s hart | `_organic_gradient` | tempoabhängig langsam |
| Wellen `v = 520+780·s` | LED/s | `iris_wave_spawn` | **LED/Beat** (Teil B explizit) |
| Wellen-Breite 12+24·s | LED | dito | leicht mitskalieren |
| Funkenfenster | 40–80 ms | `iris_spark_window` | kurz beat-bezogen, hart geklemmt |
| `snap_refractory` | 0,24 s | iris_config | ~½ Beat (Klemme!) |
| `kick_stale` | 1,6 s | iris_config | ~2–3 Beats, min 1 s |
| Engage-Doppelpuls | 70/60/80 ms | `iris_engage_window` | NUR mild skalieren (Signatur!) |
| Schattenzonen Leben/Drift | 4–9 s, ≤8 LED/s | iris_config | Takt-Vielfache |
| Wander-Glut Drift | 14/−9 LED/s | iris_config | LED/Beat |
| Freilauf | 0,55 s | iris_config | bleibt der tempolose Anker |

**Referenz-Anker:** 120 BPM ⇒ beat 500 ms. Die heutigen Werte in Beats @120:
attack 0,028 · decay 0,48 · tail 0,68 · spread 0,36 · Welle ~4,3–10,8
LED/Beat-Faktor … — der Plan definiert exakt diese Zahlen als Beat-Werte,
damit sich **bei 120 BPM nichts ändert** (Brief-Randbedingung).

## 6. Empfohlene Architektur (Vorgriff auf den Plan)

Push-only-Consumer in lichtwerk: ein kleines pures Modul (`tempo_base.py`)
führt aus den ohnehin ankommenden warn_kick/warn_bass-Daten eine
**TempoBase** {bpm_geglättet, Quelle live/veraltet/Fallback, Zone,
Bewegungsrate} mit Staleness-Zeitstempel, Plausibilisierung (Klemme 60–200,
Oktav-Gegencheck via eigener Kick-IOI, Sprünge nur nach Bestätigung),
1–2-s-Rampe, Zonen mit Hysterese. Der Render-Pfad liest NUR den gerampten
Zustand (nie blockierend, nie HTTP). Fallback-Kette: live → letzter
plausibler Wert (bis Staleness) → Referenz 120. Sichtbar in `/api/status`.
