"""tempo_base.py — musikalische Zeitbasis des roten Pfads (Tempo-Brief 2026-08-13).

Pure Zustandsmaschine (docs/tempo-scaling-plan.md): konsumiert die ohnehin
ankommenden Push-Daten (warn_kick {bpm, strength} + warn_bass {level}) und
liefert dem Renderer einen GERAMPTEN, plausibilisierten Tempo-Zustand.
disco bleibt unberuehrt (Push-only, Phase-1-Entscheid).

Kette (Teil A des Briefs):
  Klemme 60-200 -> Oktav-Gegencheck gegen die EIGENEN Kick-Ankuenfte
  (Faktor ~2/~0.5 nach `tempo_jump_confirm` Bestaetigungen korrigiert) ->
  Sprung-Bestaetigung (|Δ|>25 erst nach N konsistenten Kicks) ->
  1,5-s-Rampe -> Staleness (3 s stale, 15 s Rueckfuehrung auf Referenz).

Alle Zeiten kommen als Parameter (injizierbare Uhr des Effekts), die Config
je Aufruf (IRIS wird bei apply_iris_config neu gebaut — keine stale Referenz),
kein Zufall, keine Allokation im Frame-Takt (tick ist O(1) + 6-Punkt-Interp;
die kleinen Ringe wachsen nur im 1-3-Hz-Kick-Takt).
"""

import math


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _interp(x, pts):
    """Stueckweise lineare Interpolation, flach ausserhalb der Anker."""
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / max(1e-9, x1 - x0)
    return pts[-1][1]


def _median(vals):
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def _pct(vals, q):
    s = sorted(vals)
    return s[min(len(s) - 1, int(q * len(s)))]


class TempoBase:
    """Ein Objekt je Controller — Zustand ueberlebt Warn-Flanken bewusst
    (Tempo-Kontinuitaet ueber flatternde Engages ist der Punkt)."""

    def __init__(self, ref=120.0):
        self.bpm_eff = ref
        self.target = ref
        self.source = "fallback"      # live | stale | fallback
        self._arrivals = []           # letzte 32 Kick-Zeiten
        self._strengths = []          # letzte 16 Kick-Staerken (Ausduennen)
        self._oct_dir = 0             # +1 = gemeldet ~doppelt, -1 = ~halb
        self._oct_n = 0
        self._jump = None             # (Kandidat, Zaehler)
        self._kicks = 0               # Beat-Zaehler (Halbtakt-Raster)
        self._thin = False
        self._thin_ch = -1e9          # letzter Schaltzeitpunkt (Verweildauer)
        self._move = 1.0              # 1 = normale Aktivitaet (Anker-neutral!)
        self._bass = None
        self._bass_hist = []          # ~60 s Pegel-Historie (Normierung)
        self._bass_ht = -1e9
        self._last_kick = None
        self._last_tick = None

    # ── Eingaenge (Kick-Takt, 1-3 Hz) ────────────────────────────────────

    def note_bass(self, t, level):
        self._bass = _clamp(float(level), 0.0, 1.0)
        if t - self._bass_ht >= 0.5:
            self._bass_ht = t
            self._bass_hist.append(self._bass)
            if len(self._bass_hist) > 120:
                self._bass_hist.pop(0)

    def _implied_bpm(self):
        """BPM aus den EIGENEN Kick-Ankuenften (Median-IOI) — der
        Oktav-Gegencheck, ohne disco anzufassen."""
        a = self._arrivals
        if len(a) < 5:
            return None
        # ⚠️ Paarbildung ueber EINEN Tail (zip(tail, tail[1:])) — zwei
        # getrennte Slices paaren bei < 9 Elementen jedes Element mit sich
        # selbst (IOI 0 -> alles gefiltert -> Gegencheck blind bis Kick 9).
        tail = a[-9:]
        iois = [b2 - b1 for b1, b2 in zip(tail, tail[1:])
                if 0.2 <= b2 - b1 <= 2.0]
        if len(iois) < 4:
            return None
        return 60.0 / _median(iois)

    def note_kick(self, cfg, t, bpm, strength):
        self._kicks += 1
        self._last_kick = t
        self._arrivals.append(t)
        if len(self._arrivals) > 32:
            self._arrivals.pop(0)
        self._strengths.append(_clamp(float(strength or 0.0), 0.0, 1.0))
        if len(self._strengths) > 16:
            self._strengths.pop(0)
        if bpm is None:
            return
        try:
            cand = _clamp(float(bpm), 60.0, 200.0)
        except (TypeError, ValueError):
            return
        # Oktav-Gegencheck: erst nach N Bestaetigungen IN DIESELBE Richtung
        implied = self._implied_bpm()
        if implied is not None:
            r = cand / implied
            direction = 1 if 1.7 <= r <= 2.3 else (-1 if 0.43 <= r <= 0.59 else 0)
            if direction != 0 and direction == self._oct_dir:
                self._oct_n += 1
            elif direction != 0:
                self._oct_dir, self._oct_n = direction, 1
            else:
                self._oct_dir, self._oct_n = 0, 0
            if direction != 0 and self._oct_n >= int(cfg["tempo_jump_confirm"]):
                fixed = cand / 2.0 if direction > 0 else cand * 2.0
                if 60.0 <= fixed <= 200.0:
                    cand = fixed
        # Sprung-Bestaetigung: grosse Wechsel nur mehrfach konsistent
        if abs(cand - self.target) > 25.0:
            if self._jump is not None and abs(cand - self._jump[0]) <= 10.0:
                n = self._jump[1] + 1
                avg = self._jump[0] + (cand - self._jump[0]) / n
                if n >= int(cfg["tempo_jump_confirm"]):
                    self.target = avg
                    self._jump = None
                else:
                    self._jump = (avg, n)
            else:
                self._jump = (cand, 1)
        else:
            self.target = cand
            self._jump = None

    # ── Frame-Takt (O(1)) ────────────────────────────────────────────────

    def tick(self, cfg, now):
        """Rueckgabe-Dict fuer den Renderer; `source`-Wechsel loggt der
        Aufrufer (Vergleich alt/neu)."""
        dt = 0.0 if self._last_tick is None else _clamp(now - self._last_tick,
                                                        0.0, 0.5)
        self._last_tick = now
        ref = cfg["tempo_ref"]
        # Staleness-Kette
        ks = 1e9 if self._last_kick is None else now - self._last_kick
        if ks < cfg["tempo_stale_s"]:
            self.source = "live"
        elif ks < cfg["tempo_fallback_s"]:
            self.source = "stale"          # letzter plausibler Wert haelt
        else:
            self.source = "fallback"       # sanft zur Referenz (~10 s)
            if dt > 0.0:
                a = 1.0 - math.exp(-dt / 5.0)
                self.target += (ref - self.target) * a
        # Rampe (Teil A: nie ein Sprung; ~95 % in tempo_ramp_s)
        if dt > 0.0:
            a = 1.0 - math.exp(-dt / max(0.1, cfg["tempo_ramp_s"] / 3.0))
            self.bpm_eff += (self.target - self.bpm_eff) * a
        f = (ref / max(40.0, self.bpm_eff)) ** cfg["tempo_exp"]
        stretch = _interp(self.bpm_eff, (
            (70.0, cfg["zone70"]), (100.0, cfg["zone100"]),
            (120.0, 1.0), (132.0, 1.0),
            (140.0, cfg["zone140"]), (170.0, cfg["zone170"])))
        peak_zone = _interp(self.bpm_eff, ((70.0, 0.85), (100.0, 1.0)))
        # Ausduennen: Hysterese 150/145 + Mindestverweildauer
        dwell = cfg["thin_dwell_s"]
        if not self._thin and self.bpm_eff >= cfg["thin_on_bpm"] \
                and now - self._thin_ch >= dwell:
            self._thin, self._thin_ch = True, now
        elif self._thin and self.bpm_eff <= cfg["thin_off_bpm"] \
                and now - self._thin_ch >= dwell:
            self._thin, self._thin_ch = False, now
        # Bewegungsrate (Teil D): 1.0 = normal (Anker-neutral); faellt nur,
        # wenn Kicks UND Bass gemeinsam wegbleiben (Breakdown).
        raw = self._move_raw(now)
        if dt > 0.0:
            a = 1.0 - math.exp(-dt / max(0.3, cfg["move_tau_s"]))
            step = _clamp((raw - self._move) * a, -0.5 * dt, 0.5 * dt)
            self._move += step
        move_stretch = 1.0 + (cfg["move_calm_stretch"] - 1.0) * (1.0 - self._move)
        peak = peak_zone * (cfg["move_peak_min"]
                            + (1.0 - cfg["move_peak_min"]) * self._move)
        return {
            "f": f,
            "stretch": stretch * move_stretch,
            "peak": peak,
            "move": self._move,
            "thinning": self._thin,
            "engage": _clamp(f ** 0.3, 0.85, 1.15),
            "source": self.source,
            "bpm": self.bpm_eff,
        }

    def _move_raw(self, now):
        # Onset-Anteil: Kicks der letzten 8 s gegen die Tempo-Erwartung;
        # 0.8er-Nenner = Saettigungs-Headroom (normaler Groove == 1.0).
        # Fenster auf die tatsaechliche Datenlage normiert: "noch keine
        # 8 s Historie" ist NEUTRAL (der 120-Anker darf beim Aufwaermen
        # nicht kippen) — "Kicks weggeblieben" (altes Fenster, 0 drin)
        # ist dagegen ein echtes Breakdown-Signal.
        if len(self._arrivals) < 2:
            onset = 1.0
        else:
            span = min(8.0, now - self._arrivals[0])
            if span < 2.0:
                onset = 1.0
            else:
                expect = span * self.bpm_eff / 60.0
                rate = sum(1 for a in self._arrivals if now - a <= 8.0)
                onset = _clamp((rate / max(1.0, expect)) / 0.8, 0.0, 1.0)
        # Bass-Anteil: aktueller Pegel relativ zum eigenen p75 — ohne
        # Datenlage NEUTRAL 1.0 (der 120-Anker darf nie kippen).
        if self._bass is None or len(self._bass_hist) < 6:
            bass = 1.0
        else:
            p75 = _pct(self._bass_hist, 0.75)
            bass = _clamp(self._bass / max(1e-6, p75) / 0.8, 0.0, 1.0)
        return min(1.0, 0.5 * onset + 0.5 * bass)

    # ── Ausduennen (Teil C, >150 BPM) ────────────────────────────────────

    def thin_factor(self, cfg, strength):
        """1.0 oder thin_damp fuer DIESEN Kick: Halbtakt-Raster (jeder 2.
        gedaempft) + Staerke-Bonus (>= P70 der letzten Kicks spielt voll)."""
        if not self._thin:
            return 1.0
        on_raster = ((self._kicks - 1) % 2) == 0
        if on_raster:
            return 1.0
        if len(self._strengths) >= 8 \
                and strength >= _pct(self._strengths, cfg["thin_strong_pct"]):
            return 1.0
        return cfg["thin_damp"]

    # ── Telemetrie ───────────────────────────────────────────────────────

    def status(self, cfg):
        return {
            "bpm": round(self.bpm_eff, 1),
            "source": self.source,
            "factor": round((cfg["tempo_ref"] / max(40.0, self.bpm_eff))
                            ** cfg["tempo_exp"], 3),
            "move": round(self._move, 2),
            "thinning": self._thin,
        }
