# Lichtwerk LED Controller

> **⚡ Update 2026-06 — Stack & UI**
>
> - **Backend:** Python (**rpi_ws281x**, WS2812B 600 LEDs, GPIO 21, DMA) — jetzt als **systemd-Service** `lichtwerk-controller` (root für DMA; war root-PM2).
> - **UI:** **Material Design 3 Expressive** + Spring-Animationen (gestaffelte Sektionen-Entrance, pulsierende Status-Dots, atmende aktive Effekt-Buttons).
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
[![Tests](https://img.shields.io/badge/Tests-42%20passed-brightgreen.svg?logo=pytest&logoColor=white)](tests/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/pepperonas/lichtwerk-controller/pulls)
[![Made with ❤️](https://img.shields.io/badge/Made%20with-%E2%9D%A4%EF%B8%8F-red.svg)](https://celox.io)

A sophisticated WS2812B LED strip controller for Raspberry Pi with web interface, featuring multiple animated effects and real-time brightness control.

</div>

## Features

- **10+ Effects** — Rainbow, breathing, fire, sparkle, color wipe, theater chase, and more
- **Web Dashboard** — Control effects, brightness, and power from any device
- **REST API** — Full programmatic control for home automation integration
- **Real-time Control** — Instant brightness and effect changes via responsive UI
- **Hardware PWM** — Smooth LED control using rpi_ws281x library
- **Persistent Config** — Saves last state and restores on startup

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
- **Hardware** — WS2812B LED strip, rpi_ws281x
- **Process Manager** — systemd (as root, required for DMA)

## Author

**Martin Pfeffer** — [celox.io](https://celox.io)

## Tests

Pure-function unit tests live in `tests/test_pure.py`. They run on any machine (Mac, Linux CI, the Pi itself) — hardware is mocked via `unittest.mock`, so no GPIO or rpi_ws281x library is required.

```bash
# Install dev dependency
pip install -r requirements-dev.txt

# Run all tests
pytest tests/ -v
```

**Coverage (42 assertions across 7 test classes):**

| Class | Functions under test |
|---|---|
| `TestWheel` | `wheel()` — hue-wheel colour formula, boundary values, all-256 range check |
| `TestBrightnessScaling` | `set_pixel()` brightness multiplication, int truncation |
| `TestClamp` | `set_brightness` + `set_speed` endpoint clamping logic |
| `TestHsvToRgb` | `hsv_to_rgb()` — red, green, blue, black, white |
| `TestFadeTowardColor` | `fade_toward_color()` — up/down fade, overshoot guard, already-at-target |
| `TestFirePalette` | Fire-effect heat→colour palette (black→red→yellow→white), clamp guards |
| `TestSpeedToSleep` | `start_effect_loop` sleep-time formula, floor enforcement |
| `TestValidEffects` | Effect name registry — count, names, no duplicates |

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
