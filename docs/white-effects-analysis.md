# Weiße Akzent-Effekte — Bestandsanalyse (Phase 0)

Stand 2026-08-12, Branch `iris-white-effects` (von `iris-rework` @ 56b210b,
Rollback-Tag `white-effects-base-20260812` in beiden Repos).

## 0.2a — Die Referenz: `effect_meteor` (web_controller.py ~568–646)

Der bestehende „Comet" ist der Deko-Effekt `meteor` aus dem ursprünglichen
lichtwerk-Effektset (13 Modi, Registry s. u.) — er ist NICHT Teil der
Iris-Warn-Pipeline.

**Ehrliches Urteil: er ist exakt das Tutorial-Muster, das der Auftrag
ausschließt.** Im Detail:

| Kriterium | Befund |
|---|---|
| Timing | **Frame-Counter**, kein delta-time: `position += speed` pro FRAME; Spawn-Timer zählt Frames (`min_spawn_distance = 100`). Die Effekt-Loop schläft `(101 - speed)/1000` s → die reale Geschwindigkeit hängt an der Loop-Rate, nicht an der Zeit. |
| Position | **Ganzzahlige Pixel**: `pixel_pos = int(position - i)` — kein Sub-Pixel, bei hoher Geschwindigkeit Sprünge/Lücken. |
| Schweif | `fade_factor 0.92` multiplikativ **pro Frame** auf einem **8-bit-int-Zustand** (`pixel_states`) — frame-raten-abhängige Schweiflänge, `int()`-Trunkierung quantisiert das Ausglimmen (genau das „abgehackt statt glühend"). |
| Blocking | Kein `delay()` im Effekt selbst (die Loop schläft zentral) — dieser Teil ist ok. |
| Pool | Max 2 Meteore, aber je Spawn ein neues dict (Allokation außerhalb des Pixel-Loops — tolerabel, kein Pool). |
| Farbraum | 8-bit-Werte direkt, kein lineares Licht, kein Temperatur-Gradient. |

**Konsequenz:** `effect_meteor` bleibt als Deko-Effekt unangetastet (Regression
ausgeschlossen), dient aber nur als *Look*-Referenz („Kopf + Schweif"). Die
neue Meteor-Engine baut auf dem **Iris-Rendering-Modell** auf, das alle
geforderten Eigenschaften schon vorlebt (s. 0.2c).

## 0.2b — Registry, Lifecycle, State, Speicher

* **Registry:** `run_effect()` hält ein dict `name → bound method`
  (web_controller.py ~1677) + `valid_effects`-Whitelist in `/api/effect`.
  Ein Deko-Effekt = Methode + zwei Listeneinträge.
* **Iris-interne „Registry":** Für Warn-Akzente ist der Erweiterungspunkt NICHT
  die Effekt-Registry, sondern die **Blinder-Plan-Maschine im `iris_warn`**:
  `/api/warn_event` (kind-Whitelist + geklemmte Felder) → `iris_events`-Queue
  (max 4, verderblich) → Intake baut einen **Single-Slot-Plan**
  (`iris_blinder`: `t0`, Fenster `(start, ende, gain)`, optional `type`,
  Spot-Listen) → Malzweige unter `blind_on`. Genau so wurden L6-Sweep/Shimmer
  ergänzt — das ist der vorgesehene Weg für Meteor/Sparkle-Events.
* **Lifecycle:** EIN Effekt-Thread, interruptible sleep (`wake_effect`);
  `iris_warn` pollt mit 8 ms und schreibt auf einem eigenen **20-ms-Takt**
  (`iris_last_write`). Ein laufender Plan **gewinnt** gegen späte Events
  (Events verderblich); Pläne enden per Zeit (letztes Fenster + `sparkle_decay`
  Nachglimmen), kein explizites Teardown.
* **State:** geteiltes `effect_params`-dict; jeder Effekt initialisiert sich
  selbst lazy. `iris_warn` resettet **seinen kompletten Zustand je Engage**
  (`iris_t0 is None` → Init) — **Zombie-Doktrin:** alles mit Zeitstempeln MUSS
  dort zurückgesetzt werden (negatives Alter = unsichtbar + unsterblich;
  zweimal teuer bezahlt: Schatten-Zonen, Test-Wellen).
* **Speicher:** bounded überall — Wellen ≤ 3, Event-Queue ≤ 4, Blinder
  single-slot, Schatten = `shadow_count`. Keine Allokation im per-Pixel-Loop;
  per-Event-Allokationen (Spot-Listen) sind Konvention und ok (Spawns sind
  selten gegen 50 fps).

## 0.2c — Rendering-Modell des Iris-Pfads (die Basis für Neues)

* **Zeit:** durchgehend **delta-time** (`t` = Sekunden seit Engage aus
  `mono()`, injizierbare Uhr `controller.iris_clock`). Keine blockierenden
  Sleeps im Effekt.
* **Sub-Pixel:** de facto vorhanden — Sweep-Kopf und Wellenfronten sind
  **Gauss-Profile um float-Zentren** (jede LED bekommt `exp(-d²/2w²)`), d. h.
  für breite Köpfe ist das Anti-Aliasing schon besser als frac/1-frac.
  **Was fehlt:** (a) frac-AA für 1-px-Punkte, (b) **Line-Integral /
  Motion-Blur** — der Sweep malt die *Punktposition* pro Frame. Bei 20 ms
  Frames trägt die Kopf-Breite (σ=14 → ±42 px) das bis ~1000 LED/s; ein
  echter schneller Meteor (2000+ LED/s = 40+ px/Frame) reißt Lücken →
  Rendering-Hilfsschicht nötig.
* **Compositing:** **Replace-Blend** (Basis malen, dann pro Pixel Richtung
  Akzent lerpen: `r_ += (w - r_) * core`) — kein additiver Puffer, kein
  Clipping-Risiko. **Weiß über Rot = Ducking per Design:** während eines
  Blinder-Plans ist das Rot AUS (`lit = blinder[0]`), Wellen + Funken werden
  aus Blinder-Frames herausgehalten. Die Brief-Forderung „Ducking statt
  Clipping" ist Bestandskonvention.
* **Farbraum:** 8 bit/Kanal auf den Draht; **Kernel-Gamma ist bypassed**
  (`begin()` schreibt Kernel-Brightness 0xff = Identität), Skalierung macht
  die Userspace-LUT (`led_brightness 100` → ×0,39 auf jeden `show()`), die
  Blinder-Frames **neutralisieren** (LUT → 255, absolute Stromklasse).
  Interne Rechnung ist float pro Frame, quantisiert erst am Ende — aber es
  gibt **keinen linearen Lichtraum** und keinen persistenten
  float-Akkumulationspuffer (das einzige Akku-Beispiel, `effect_meteor`,
  akkumuliert in 8-bit-ints — Negativbeispiel). WS2812-Duty ist ~linear in
  Lichtstrom; „exponentieller Schweif im linearen Licht" heißt hier: Profil in
  float rechnen, perzeptuell formen (γ≈2,2-Encode), erst dann quantisieren.
* **RNG:** `iris_rng` = `random.Random(seed)` je Engage — deterministisch
  testbar (Golden-Frame-Hash, BASELINE_OFF-Rollback-Beweis).

## 0.2d — Trigger-Infrastruktur (disco → lichtwerk)

* **Onsets:** schneller Zweit-Onset-Pfad (`FAST_ONSET_REFRACTORY_S = 0.12`),
  Beat-Pfad 0,30 s; SuperFlux-Gate; BPM/IOI-Median.
* **Events:** `WhiteEventDetector` (double/roll/accent, adaptive p50/p85-
  Schwellen) + **`WhiteScheduler`** (inhomogener Poisson: λ = base × Energie ×
  Onset-Dichte; `min_gap` 2,5 s, `max_gap` 30 s, Beat-Snapping ≤150 ms) +
  **`WhiteVariantPicker`** (gewichtete Auswahl, **no-repeat-last**, Stärke
  koppelt Intensität/Dichte) → `lichtwerk_client.warn_event` (⚠️ reicht nur
  explizit gelistete Felder durch!) → `/api/warn_event`.
* **Drop:** lichtwerk-seitig (Kick-Stärke ≥ 0,9 + träges Mittel ≥ 0,5,
  Cooldown 8 s) — der „Kronjuwelen"-Moment existiert bereits.
* **Bausteine für den Director existieren verteilt** (Refraktärzeiten,
  no-repeat, Cooldown, Energie-Kopplung), aber es gibt **keine zentrale
  Tier-/Budget-/Build-up-Schicht**.
* **Lücke für Sparkle:** disco liefert lichtwerk heute nur Kick-Stärke, BPM
  und Events — **keine Hochband-Energie** (Hi-Hats/Becken). Die 24-Band-FFT
  existiert in disco; ein Hochband-Wert müsste zusätzlich übertragen werden.

## 0.2e — Konventionen für nahtlose neue Effekte

1. Neues Akzent-Event = neues `kind` in der `/api/warn_event`-Whitelist +
   geklemmte Payload-Felder (`_f()`-Helper) + Intake-Branch (Plan mit `type`)
   + Malzweig unter `blind_on` — dem L6-Muster (sweep/shimmer) folgend.
2. **Alle Parameter in `iris_config.py`** (DEFAULTS + RANGES-Klemmen,
   config.json-Sektion `"iris"`); jeder Effekt einzeln abschaltbar;
   **Schalter aus = bit-genau Baseline** (Golden-Frame-BASELINE_OFF beweist
   den Rollback-Pfad).
3. Zufall aus `iris_rng`, Zeitstempel effekt-relativ, Reset je Engage
   (Zombie-Doktrin), bounded Pools.
4. disco-Seite: Auswahl-/Timing-Logik als pure Module (`white_*.py`),
   injizierbare RNG/Uhr, deterministische Tests; `DISCO_WHITE_*`-Env-Overrides.
5. **`lichtwerk_client.warn_event` muss neue Felder explizit durchreichen**
   (Feldbefund D2: der defensive Payload-Neuaufbau verwarf sie).
6. Tests: pure Helpers + Ausführungs-Smoke (FakeStrip) + Golden-Hash;
   Verhaltensvergleiche als Differenz zweier deterministischer Läufe
   (die Basis atmet selbst — ein stales Referenz-Frame taugt nicht).

## 0.3 — Rendering-Fähigkeiten, ehrlich

* **Frame-Rate/Budget:** `iris_warn` läuft auf einem 20-ms-Schreibtakt
  (~50 fps); die Physik deckelt hart: 600 px × 30 µs ≈ **18 ms Shift-out** je
  Frame. Hot-Path gemessen (600 px, Sustain inkl. Glut+Schatten): **0,53 ms/
  Frame auf dem Mac**, auf dem Pi 5 konservativ ~1–1,5 ms → **Budget-Rest
  > 15 ms/Frame**, neue Effekte mit ≤ 2 ms Zuschlag sind unkritisch.
* **LEDs:** 600 logische px (RGBW-Payload 4 B/px an `/dev/leds0`), physisch
  1200 (zwei Y-gespiegelte Ketten à 2×5 m, ein Datenstrom). EBUSY-Drops werden
  gezählt; Frames sind per-Transmission (Slips heilen durch Neu-Senden).
* **Sub-Pixel:** float-Zentren ja (Gauss); **frac-AA für Punkte und
  Line-Integral für schnelle Köpfe fehlen** → kleine pure Rendering-
  Hilfsschicht ist Teil des Plans (Phase 2).
* **Farbtiefe:** 8 bit/Kanal Ausgabe, float in-frame, kein HDR-Puffer.
  Für Sparkle-Hüllkurven reicht per-Partikel-float-State (kein Framebuffer-
  Akku nötig — Lehre aus `effect_meteor`).
* **Strom-/Netzteil-Budget — die harte Wahrheit:** Vollstrip-Weiß @ 255 wäre
  nominal ~36 A **je Kette** (600 × 60 mA), ×2 Ketten. Real bewiesen
  (2026-08-10, Geräte-A/B): Einspeisung nur vorn → die 5-V-Schiene sackt über
  10 m, die blaue Die verhungert zuerst → **stehendes Vollweiß driftet binnen
  Sekunden grünlich**. Vollflächiges Weiß ist auf dieser Verkabelung
  **physisch unehrlich**, unabhängig vom Netzteil.
  **Vorhandenes Power-Limiting ist Design, kein Regler:** sparse Spots
  (Cap ≤ 40 % des Strips), Blinder in der absoluten 55-%-Stromklasse
  (`blinder_gain`), Duty statt Fläche. (`iris_wash.fit_exposure` enthält ein
  schlafendes Ampere-Budget-Modell, ist aber nicht im Live-Pfad.)
  → Launch-/Impact-„Flashes" müssen kurz (≤ ~60 ms), gain-gedeckelt und/oder
  sparse ausgeführt werden; ein Dauer-Vollweiß-Frame ist keine Option.
* **Tutorial-Muster-Check:** ja, der bestehende `effect_meteor` IST das Muster
  (Beleg in 0.2a) — die neuen Effekte bauen nicht darauf, sondern auf dem
  Iris-Modell; der Deko-Effekt bleibt unverändert.
