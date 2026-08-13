# Plan: red_tempo_scaled — musikalische Zeitbasis für Rot

Phase 2 des Tempo-Briefs (2026-08-13). Analyse:
[bpm-integration.md](./bpm-integration.md). Phase-1-Entscheidungen (Nutzer):
**Push-only** (kein Status-Poll — Idle-Fast-Path bleibt heilig) ·
**Halbtakt + Stärke-Bonus** beim Ausdünnen · **nur organic, direkt aktiv**
(classic bleibt bit-identischer Rollback).

**KEINE Implementierung vor Freigabe dieses Plans.**

---

## Architektur

**Neues pures Modul `tempo_base.py`** (lichtwerk): führt aus den ohnehin
ankommenden Push-Daten den Zustand **TempoBase**:

```
note_kick(t, bpm, strength)   # aus dem warn_kick-Intake (bpm schon geparst)
note_bass(t, level)           # aus /api/warn_bass (existiert)
tick(now) -> {bpm_eff, factor, zone_stretch, move, thinning, source}
```

Der Render-Pfad liest NUR diesen gerampten Zustand — nie HTTP, nie
blockierend, keine Allokation (Ringe vorallokiert). disco: **0 Diff**.

**Schalter `red_timing`** = `"fixed"` (Code-Default = exakt der heutige
organic-Stand, bit-genau) | `"tempo"`. Live umschaltbar über den bestehenden
Profil-Endpoint (`POST /api/iris/profile {"timing": "tempo"|"fixed"}`),
persistiert atomar in config.json. Nach dem Deploy wird live `tempo`
gesetzt (Phase-1-Entscheid) — **bei 120 BPM per Konstruktion unhörbar**.
Wirkt NUR im organic-Pfad; classic + alle Weiß-Pfade unberührt.

## Teil A — Robustheit (die Kette)

1. **Plausibilisierung je Kick:** bpm-Feld klemmen auf 60–200 (Payload ist
   schon 50–200). **Oktav-Gegencheck:** Median-IOI der eigenen
   Kick-Ankünfte (Ring 8) → implizite BPM; weicht die gemeldete um Faktor
   ~2 bzw. ~0,5 (±20 %) ab, zählt ein Verdachtszähler — nach **3
   Bestätigungen in Folge** wird auf die Ankunfts-Oktave korrigiert.
2. **Sprung-Bestätigung:** |Δ| > 25 BPM → erst nach 3 konsistenten Kicks
   (±10 BPM untereinander) als neues Ziel übernehmen.
3. **Rampe:** `bpm_eff` läuft per One-Pole in `tempo_ramp_s` 1,5 s aufs
   Ziel — nie ein Sprung. **Laufende Pulse behalten ihre beim Spawn
   eingefrorenen Zeiten** (ist im Pulse-Design schon so: dscale & Co.
   werden je Puls kopiert) — die neue Zeitbasis gilt nur für Neues.
4. **Staleness:** letzter Kick-Zeitstempel; > `tempo_stale_s` 3 s ⇒ Quelle
   „veraltet" (letzter plausibler Wert bleibt); > `tempo_fallback_s` 15 s
   ⇒ sanfte Rückführung auf Referenz 120 über ~10 s, Quelle „fallback".
   Beides im Log (eine Zeile je Übergang) und im Statusendpunkt.
5. disco weg/Neustart: Posts enden → Staleness-Kette greift; kommen Kicks
   wieder, heilt alles ohne Handshake (Bestandsmuster geerbt).

## Teil B — Beat-Zeitbasis mit gedämpfter Kurve

Globaler Faktor `F = (tempo_ref / bpm_eff) ^ tempo_exp` mit **tempo_ref
120** und **tempo_exp 0,7** (Range 0,3–1,0):
70 BPM → F 1,46 · 100 → 1,14 · **120 → 1,000** · 140 → 0,90 · 174 → 0,77.
Ein unentdeckter Oktavfehler wirkt so nur ×~1,6 statt ×2 (Dämpfung als
zweites Netz unter dem Gegencheck).

| Parameter | Ist (@120 = Anker) | Skalierung | harte Klemme |
|---|---|---|---|
| `organic_attack_ms` | 14 | × F^1,3 (`tempo_attack_exp` — langsam weicher, schnell knackiger) | 5–40 ms (RANGES) |
| `organic_decay_ms` | 240 | × F | 80–800 ms |
| `organic_tail_ms` | 340 | × F | 100–900 ms |
| `organic_spread_ms` | 180 | × F | 60–600 ms |
| `organic_bass_up_s/down_s` | 0,12/0,45 | × F^0,7 (Glättung nur mild) | RANGES |
| Energie-EMA (Bett) | 4,0 s ≈ 2 Takte | × F (bleibt „2 Takte") | 1,5–8 s |
| Hue-Drift-Periode | 240 s | × F | 120–480 s |
| Wellen-Tempo `520+780·s` LED/s | ≈ 4,3–10,8 LED/Beat | × F⁻¹ (LED/Beat konstant) | 300–3000 LED/s |
| Wellen-Breite `12+24·s` | | × F^0,5 (nur mild) | 8–48 LED |
| Funkenfenster 40–80 ms | | × F | 25–120 ms |
| `snap_refractory` 0,24 s | ≈ ½ Beat | × F, NUR wenn organic+tempo | 0,10–0,50 s |
| `kick_stale` 1,6 s | ≈ 3 Beats | × F | 1,0–4,0 s |
| Schattenzonen-Leben 4–9 s | | × F^0,7 | 2–15 s |
| Wander-Glut-Drift 14/−9 LED/s | | × F⁻¹ mild (^0,5) | RANGES |
| Engage 70/60/80 ms | Signatur! | × F^0,3 (kaum — Charakter gesperrt) | 50–110 ms |
| Freilauf 0,55 s | tempoloser Anker | UNVERÄNDERT | – |

Alle effektiven Werte laufen zusätzlich durch die bestehenden
iris_config-RANGES — nichts kann in einen unbrauchbaren Bereich kippen.

## Teil C — Zonen-Charakter (interpoliert, nie geschaltet)

Zusätzlich zum F-Faktor ein **Zonen-Stretch** als stückweise lineare Kurve
über bpm_eff (Stützpunkte konfigurierbar):

| Anker | Stretch auf Decay/Tail | Charakter |
|---|---|---|
| ≤ 70 | ×1,35 (+ Attack ×1,4, Bett +0,03, Impuls-Peak ×0,85) | getragen: Impulse gehen ins Atmen über |
| 100 | ×1,12 | groovig, weiche Kanten |
| **120–132** | **×1,00 — der Referenzcharakter, per Definition unverändert** | |
| 140 | ×0,88 | straffer Puls, kürzere Ausklänge |
| ≥ 170 | ×0,75 | + Ausdünnen (unten) |

Zwischen den Ankern wird linear interpoliert — es gibt keine Zustände, also
kein Flattern; Hysterese braucht nur der Ausdünn-SCHALTER:

**Ausdünnen > 150 BPM** (an bei ≥ 150, aus bei ≤ 145, Mindestverweildauer
4 s): Beat-Zähler ab dem letzten Phase-Snap; **jeder 2. Puls** spawnt mit
Peak × `thin_damp` 0,45 — **außer** seine Kick-Stärke liegt ≥ P70 der
letzten ~16 Kicks (Stärke-Ring in tempo_base): dann spielt er voll
(Akzente überleben das Raster). Downbeat-Näherung: der Snap-Anker zählt
als „1".

## Teil D — Bewegungsrate (Breakdown ≠ langsames Lied)

`move ∈ 0..1` = 0,5 · Bass-Hüllkurve (aus warn_bass, normiert auf das
eigene 60-s-Perzentil) + 0,5 · Onset-Rate (Kicks der letzten 8 s /
Erwartung aus bpm_eff). One-Pole τ 2 s + Slew-Begrenzung
(Mindestverweildauer-Äquivalent, kein Flattern).

Wirkung (alles gerampt): Decay/Tail × (1 + 0,5·(1−move)) ·
Impuls-Peak × (0,75 + 0,25·move) · Bett-Anteil steigt bei Ruhe.
Breakdown im 140er-Track: Kicks dünn + Bass weg ⇒ move → 0 ⇒ hörbar
ruhigeres, weicheres Licht — Groove/Drop ⇒ move → 1 ⇒ tempoübliches
Verhalten. (Echter Sektionszustand bewusst NICHT gelesen — Push-only.)

## Neue Parameter (iris_config, alle geklemmt)

`red_timing` "fixed" · `tempo_ref` 120 (100–140) · `tempo_exp` 0,7
(0,3–1,0) · `tempo_attack_exp` 1,3 (0,5–2,0) · `tempo_ramp_s` 1,5 (0,5–5) ·
`tempo_stale_s` 3 (1–10) · `tempo_fallback_s` 15 (5–60) ·
`tempo_jump_confirm` 3 (1–6) · `thin_on_bpm` 150 / `thin_off_bpm` 145 ·
`thin_damp` 0,45 (0,2–1) · `thin_strong_pct` 0,70 · `move_tau_s` 2 ·
`move_calm_stretch` 1,5 · `move_peak_min` 0,75 · Zonen-Anker
`zone70/zone100/zone140/zone170` (0,5–1,6).

## Telemetrie

`GET :5006/api/status` → `"tempo": {bpm_eff, source: live|stale|fallback,
zone_stretch, move, thinning, factor}` (rein aus dem Speicher) + eine
Journal-Zeile je Quellen-Übergang und je Oktav-Korrektur.

## Implementierungsschritte

1. **T1**: `tempo_base.py` pur + Tests (Plausibilisierung, Oktav-Feed
   halbiert/verdoppelt, Sprung-Bestätigung, Rampe, Staleness-Kette,
   Zonen-Interpolation, move) — noch nichts verdrahtet
2. **T2**: iris_config-Keys + Verdrahtung im organic-Pfad (Spawn-Parameter
   je Puls aus TempoBase eingefroren; Wellen/Funken/Bett/Drift skaliert);
   `red_timing: fixed` = bit-identisch (Test: gleiche Seeds + 120-BPM-Kicks
   ⇒ identische Frames tempo↔fixed)
3. **T3**: Ausdünnen + Bewegungsrate + Telemetrie + Profil-Endpoint-Erweiterung
4. **T4**: Doku (CONFIG je Parameter mit Beat-Bezug/Kurve/Klemme, TUNING,
   CHANGELOG, ARCHITECTURE-Verweis) + Deploy + Live-Verifikation

## Testkriterien (Abnahme)

- **120-BPM-Anker:** tempo ↔ fixed bit-identische Frames (der Punkt, an dem
  sich nichts ändern darf — als Test gepinnt).
- Referenz-Feeds 70/100/120/128/140/174: Decay-Zeiten folgen der Tabelle
  (±5 %), Klemmen greifen an den Enden.
- **Oktav-Fehlertest:** bpm 87 einspeisen bei 174er-Kick-Ankünften ⇒
  Korrektur nach 3 Kicks; dito verdoppelt.
- **Tempowechsel** 126→140 im Lauf: bpm_eff rampt in ~1,5 s, kein Sprung in
  den abgeleiteten Zeiten; laufende Pulse unverändert.
- **Ausfalltest:** Kicks stoppen ⇒ nach 3 s „stale", nach 15 s Rückführung
  auf 120; Kicks wieder da ⇒ live, ohne Neustart (Unit + live nachgestellt).
- **Breakdown-Test:** 140er-Kicks + Bass aus + Kick-Lücken ⇒ move fällt,
  Decays verlängern hörbar (Unit über die Zahlen, live per Ohr).
- Weiß/classic: bestehende Suiten (212 lichtwerk / 313 disco) grün;
  disco-Repo-Diff = NUR Doku.
- `dropped_frames == 0` live; CPU-Delta ausgewiesen (Erwartung: ~0, O(1)).

## Rollback-Matrix

| Ebene | Weg | Dauer |
|---|---|---|
| Timing | `POST /api/iris/profile {"timing":"fixed"}` | Sekunden, live |
| Einzelparameter | iris-Config-Key (z. B. `tempo_exp` 1,0→0) + Restart | 1 min |
| Code | Tag `iris-tempo-baseline-2026-08-13` | 5 min |
