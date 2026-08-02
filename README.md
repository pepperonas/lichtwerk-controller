# Lichtwerk LED Controller

> **⚡ Update 2026-08-02 — Iris-Wash: der dB-Analyse-Hintergrund auf dem Strip**
>
> - **Host:** Live auf **raspi5** (`192.168.178.105`), GPIO **21**, Overlay `dtoverlay=ws2812-pio,gpio=21,num_leds=600,brightness=255` → `/dev/leds0`.
> - **Driver:** **ein Frame pro `open()`** — ein zweiter `write()` auf denselben FD scheitert immer mit `ENOSPC`, Warten hilft nicht (bis 1000 ms geprüft), das Device ist nicht seekbar. Die frühere „FD offen halten"-Optimierung konnte deshalb nie greifen; jeder Frame lief still über Fehl-Write → close → reopen → write. `show()` öffnet jetzt pro Frame (0,002 ms), Helligkeit über `bytes.translate`-LUT statt Genexp.
> - **Effekt `iris_warn`:** exakte Portierung des Seiten-Hintergrunds `body.over-iris` (Radialgradient + `iris-breathe` + echte `cubic-bezier(.2,0,0,1)`), gamma-korrigiert, **ohne** weiße Sparks. Atem komplett vorberechnet → ~150 KB, Frame = Index + Write. Release blendet über **0,55 s** aus wie die Seite.
> - **Timing:** Shift-out-Boden 600 LEDs = **18,0 ms (55,6 fps)**; der Wash taktet deadline-basiert auf **30 fps** — live gemessen exakt 30,0 fps, im Leerlauf **0 Byte** auf `/dev/leds0`.
> - **API:** `POST /api/solid` = power+RGB+bri in **einem** RTT (Disco-Sync). Flask `threaded=True`.
> - **Deploy:** `git pull && sudo systemctl restart lichtwerk-controller`


<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0-000000.svg?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi-C51A4A.svg?logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/)
[![Hardware](https://img.shields.io/badge/Hardware-WS2812B-FF6600.svg?logo=adafruit&logoColor=white)](https://cdn-shop.adafruit.com/datasheets/WS2812B.pdf)
[![LEDs](https://img.shields.io/badge/LEDs-600-FFD700.svg?logo=sparkfun&logoColor=white)](https://www.sparkfun.com/)
[![Library](https://img.shields.io/badge/Library-rpi__ws281x-CC0000.svg?logo=github&logoColor=white)](https://github.com/jgarff/rpi_ws281x)
[![Managed by](https://img.shields.io/badge/Managed%20by-systemd-0A7BBB.svg?logo=linux&logoColor=white)](https://systemd.io/)
[![Tests](https://img.shields.io/badge/Tests-60%20passed-brightgreen.svg?logo=pytest&logoColor=white)](tests/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/pepperonas/lichtwerk-controller/pulls)
[![Made with ❤️](https://img.shields.io/badge/Made%20with-%E2%9D%A4%EF%B8%8F-red.svg)](https://celox.io)

A sophisticated WS2812B LED strip controller for Raspberry Pi with web interface, featuring multiple animated effects and real-time brightness control.

</div>

## Features

- **10+ Effects** — Rainbow, breathing, fire, sparkle, chase, theater, meteor, **iris_warn** (Strip-Warn), and more
- **Web Dashboard** — Control effects, brightness, and power from any device
- **REST API** — Full programmatic control for home automation / disco Strip-Warn
- **Pi 5 PIO path** — `pio_strip.py` → `/dev/leds0` (ws2812-pio overlay); rpi_ws281x fallback
- **Real-time Control** — Instant brightness and effect changes via responsive UI
- **Persistent Config** — Saves last state and restores on startup (`config.json`)

## Iris-Warn (`iris_warn`)

Disco **Strip-Warn** starts this effect while reported SPL exceeds the shared **`warn_thr`** (default **55 dB**, same as page/card Warnung and Matrix „IRIS“):

Der Strip zeigt dabei **denselben Wash wie der Seitenhintergrund der dB-Analyse** (`body.over-iris` in `stats.html`) — als Portierung, nicht als Interpretation. Die Farbmathematik liegt in `iris_wash.py`:

1. **Compositing wie im Browser:** premultiplied interpolierter Radialgradient über `#3a1010`, darüber die `iris-breathe`-Keyframes (1,8 s, `alternate`) per srcOver in sRGB. Die `cubic-bezier(.2,0,0,1)` wird gelöst, nicht durch einen Smoothstep angenähert.
2. **Geometrie:** die Seite ist 2-D, der Strip eine Linie → gerendert wird die **horizontale Mittel-Scanline** durch den Gradientenursprung (50 % / 40 %). Die Ellipse misst 120 % der Viewport-Breite, der Strip überstreicht also t ∈ [0, 0.417]: sanfter Abfall von der Mitte zu beiden Enden, genau wie am Schirm.
3. **Gamma:** CSS-Farben sind sRGB für einen Bildschirm mit ~2,2 Gamma, WS2812-PWM ist linear. Ohne Korrektur werden die schwachen Kanäle viel zu hell und aus Ziegelrot wird Rosa. sRGB → linear, danach `exposure` als Belichtung, damit es Warnlicht bleibt und keine dunkle Bildschirmkopie.
4. **Keine weißen Sparks** — die Seite hat keine. Ihr Wegfall macht die Vorberechnung überhaupt erst möglich.
5. **Vorberechnung:** der gesamte Atem entsteht beim Armieren (64 Stufen × 600 LEDs × 4 B ≈ 150 KB). Ein Frame = Index + Write, CPU an der Messgrenze.
6. **Release:** Ausblende über **0,55 s** passend zur `transition: background .55s` der Seite; erneutes Überschreiten während der Rampe springt sofort zurück auf den Höhepunkt. `/api/warn_mode {on:false}` schneidet weiterhin hart ab.

Konfiguration in `config.json` → `iris_wash`: `steps` (64), `exposure` (1.8), `max_current_a` (`null`). Ein Vollflächen-Wash zieht bei Belichtung 1,8 auf 600 LEDs bis zu **~10,8 A** — der Dienst loggt den Wert beim Armieren. Ist das Netzteil knapper, `max_current_a` auf dessen Nennstrom setzen; die Belichtung wird dann passend heruntergerechnet (Farbton und Atem bleiben unverändert).

```bash
curl -X POST http://127.0.0.1:5006/api/effect -H 'Content-Type: application/json' -d '{"effect":"iris_warn"}'
# Disco color sync (one RTT):
curl -X POST http://127.0.0.1:5006/api/solid -H 'Content-Type: application/json' \
  -d '{"power":true,"r":255,"g":70,"b":55,"brightness":255}'
```

Valid effects include: `solid`, `rainbow`, `pulse`, `chase`, `sparkle`, `strobe`, `meteor`, `breathe`, `sinelon`, `juggle`, `theater`, `gradient`, `fire`, **`iris_warn`**.

## Wiring Diagram

```
    Raspberry Pi                         WS2812B LED Strip (600 LEDs)
    ┌──────────────┐                     ┌────────────────────────┐
    │              │                     │                        │
    │  GPIO21(40) ─┼─────────────────────┤── DIN                  │
    │              │                     │                        │
    │   GND  (39) ─┼────────┬────────────┤── GND                  │
    │              │        │            │                        │
    └──────────────┘        │            │   VCC ─────────┐       │
                            │            └────────────────┼───────┘
                       ┌────┴─────────────────────────────┴──┐
                       │  External 5V Power Supply           │
                       │  (min. 30A for 600 LEDs @ full)     │
                       └─────────────────────────────────────┘

    Config: 800kHz signal · DMA channel 10 · LED channel 0

    ┌──────────┬──────────┬──────────────────────────────────┐
    │ Pi Pin   │ GPIO     │ Connection                       │
    ├──────────┼──────────┼──────────────────────────────────┤
    │ Pin 40   │ GPIO 21  │ WS2812B Data In (DIN)            │
    │ Pin 39   │ GND      │ Common ground (Pi + PSU + Strip) │
    └──────────┴──────────┴──────────────────────────────────┘
```

> **Note:** The WS2812B strip requires an external 5V power supply — do not power from the Pi. All three GND lines (Pi, PSU, strip) must be connected together. Requires root for DMA/mmap access.

**Realistischer Strombedarf.** Die 30 A oben sind der Worst Case (600 LEDs, Vollweiß). Der Iris-Wash ist rot und gedimmt und zieht bei Belichtung 1,8 rund **6,4 A (Atem-Minimum) bis 10,8 A (Maximum)**, plus ~0,6 A Ruhestrom der 600 Controller. Reicht das Netzteil dafür nicht, `iris_wash.max_current_a` in `config.json` auf dessen Nennstrom setzen — die Belichtung wird dann heruntergerechnet, Farbton und Atem bleiben erhalten.

Bei ~10 m Gesamtlänge (2 × 300 LEDs in Serie) ist **einseitige Einspeisung grenzwertig**: der Spannungsabfall macht das ferne Ende dunkler und verschiebt Rot ins Gelbliche. Wenn der Verlauf zu den Enden hin stärker abfällt als die Tabelle in `iris_wash.py` vorgibt, ist das kein Rendering-Fehler, sondern fehlende Einspeisung am Strip-Ende.

## Quick Start

```bash
# Clone the repository
git clone https://github.com/pepperonas/lichtwerk-controller.git
cd lichtwerk-controller

# Set up virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start the controller (requires root for GPIO/PWM access)
sudo python web_controller.py
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Current state (power, brightness, effect) |
| `/api/power` | POST | Toggle power on/off |
| `/api/brightness` | POST | Set brightness (`{ "value": 0-255 }`) |
| `/api/speed` | POST | Set effect speed (`{ "speed": 1-100 }`) |
| `/api/effect` | POST | Set effect (`{ "effect": 0-9 }`) |
| `/api/color` | POST | Set color (`{ "r": 0-255, "g": 0-255, "b": 0-255 }`) |

## Tech Stack

- **Backend** — Python 3.11, Flask, Flask-CORS
- **Frontend** — HTML5 (Jinja2 templates), CSS3, JavaScript
- **Hardware** — WS2812B LED strip; Pi 5 via `ws2812-pio` / `pio_strip.py`, else rpi_ws281x
- **Process Manager** — systemd `lichtwerk-controller` (live: raspi5)

## Author

**Martin Pfeffer** — [celox.io](https://celox.io)

## Tests

Pure-function + driver unit tests live in `tests/`. They run on any machine (Mac, Linux CI, the Pi itself) — hardware is mocked or unused (`pio_strip` buffer-only), so no GPIO is required.

```bash
# Install dev dependency
pip install -r requirements-dev.txt

# Run all tests (tests/ only — root test_*.py are Pi hardware scripts)
pytest tests/ -v
```

**Coverage (60 tests):**

| Suite | Fokus |
|---|---|
| `test_pure.py` | `wheel`, brightness, HSV, fade, fire palette, speed→sleep, effect registry |
| `test_pio_strip.py` | FD reuse across `show()`, `fill()`, brightness scale, missing device |
| `test_iris_warn.py` | timing, paint/clear, `/api/solid` + wake + first-frame contracts |

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
