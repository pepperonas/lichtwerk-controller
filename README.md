# Lichtwerk LED Controller

<div align="center">

![License](https://img.shields.io/badge/License-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.11-3776AB.svg?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0-000000.svg?logo=flask&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi-C51A4A.svg?logo=raspberrypi&logoColor=white)

A sophisticated WS2812B LED strip controller for Raspberry Pi with web interface, featuring multiple animated effects and real-time brightness control.

</div>

## Features

- **10+ Effects** — Rainbow, breathing, fire, sparkle, color wipe, theater chase, and more
- **Web Dashboard** — Control effects, brightness, and power from any device
- **REST API** — Full programmatic control for home automation integration
- **Real-time Control** — Instant brightness and effect changes via responsive UI
- **Hardware PWM** — Smooth LED control using rpi_ws281x library
- **Persistent Config** — Saves last state and restores on startup

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
| `/api/effect` | POST | Set effect (`{ "effect": 0-9 }`) |

## Tech Stack

- **Backend** — Python 3.11, Flask, Flask-CORS
- **Frontend** — HTML5 (Jinja2 templates), CSS3, JavaScript
- **Hardware** — WS2812B LED strip, rpi_ws281x
- **Process Manager** — PM2

## Author

**Martin Pfeffer** — [celox.io](https://celox.io)

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
