# Lichtwerk LED Controller

> **⚡ Update 2026-08-01 — Pi 5 + Iris-Warn**
>
> - **Host:** Live auf **raspi5** (`192.168.178.105`), GPIO **21**, Overlay `dtoverlay=ws2812-pio,gpio=21,num_leds=600,brightness=255` → `/dev/leds0`.
> - **Driver:** `pio_strip.py` (Kernel-PIO) mit Fallback auf `rpi_ws281x` (Pi 3 / rpi_ws281x). Kernel-Brightness-Byte = Multiplier 0–255 (nie 0 schreiben).
> - **Effekt `iris_warn`:** harter Crimson↔Schwarz-Square-Blitz (~60 fps) für Disco **Strip-Warn** (feuert ab der geteilten `warn_thr`-Schwelle, Default **55 dB SPL** — nicht die Iris-~70‑Marke). Engage-Doppelpuls + ~65 % Duty @ 0,55 s; kurze **Weiß-Sparks** (~12 LEDs, ~40 ms) an jeder ON-Kante. Kein HTTP-Frame-Spam von disco.
> - **UI:** Material Design 3 Expressive + shared App-Nav (`/shared/nav.js`).
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
[![Tests](https://img.shields.io/badge/Tests-58%20passed-brightgreen.svg?logo=pytest&logoColor=white)](tests/)
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

Disco **Strip-Warn** starts this effect while reported SPL exceeds the shared **`warn_thr`** (default **55 dB**, same as page/card Warnung — not the Iris ~70 dB / `DISCO_LOUD_MARK_DB` matrix mark):

1. Engage: two hard full-strip crimson pulses (~210 ms)
2. Sustain: square wave, period 0.55 s, ~65 % ON — full `(255,70,55)` vs black (no soft glow)
3. Each ON edge: ~12 random white LEDs for ~40 ms (lightning accent)
4. Loop runs locally at ~60 fps; disco only POSTs `power`/`effect` once

```bash
curl -X POST http://127.0.0.1:5006/api/power -H 'Content-Type: application/json' -d '{"power":true}'
curl -X POST http://127.0.0.1:5006/api/effect -H 'Content-Type: application/json' -d '{"effect":"iris_warn"}'
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

**Coverage (58 tests):**

| Suite | Fokus |
|---|---|
| `test_pure.py` | `wheel`, brightness, HSV, fade, fire palette, speed→sleep, effect registry |
| `test_pio_strip.py` | Pi-5 `pio_strip.Color`/`PixelStrip` buffer, brightness scale, missing `/dev/leds0` |
| `test_iris_warn.py` | `iris_warn` timing (engage double-pulse, 65 % duty), paint/clear, README/source contracts |

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
