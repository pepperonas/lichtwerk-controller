# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Lichtwerk LED Controller — Raspberry Pi WS2812B strip (600 LEDs) with Flask UI/API on port **5006**.

**Live (2026-08-01):** **raspi5** (`192.168.178.105`), systemd `lichtwerk-controller`, GPIO **21**, kernel overlay:

```
dtoverlay=ws2812-pio,gpio=21,num_leds=600,brightness=255
```

Device node: `/dev/leds0`. Driver module: `pio_strip.py` (preferred on Pi 5). Fallback: `rpi_ws281x` when `pio_strip` is absent (older Pi / DMA path).

**Important:** Kernel brightness write is a **0–255 multiplier**. Never write `0` on begin (strip stays dark). App sets `brightness=255` when selecting `iris_warn`.

## Architecture

- **`web_controller.py`**: Flask server + effect loop (port 5006). Production entrypoint.
- **`pio_strip.py`**: PixelStrip/Color compatible with rpi_ws281x API → writes RGBW u32 frames to `/dev/leds0`.
- **`controller.py`**: CLI/standalone effects (legacy/dev).
- Demo mode if strip init fails (no hardware).

## Iris-Warn (`effect_iris_warn`)

Used by **disco-controller Strip-Warn** (`warn_hue` API key). Hard crimson↔black square blitz + brief white sparks. See README. Disco owns start/stop; do not restore prior disco solid scene when Strip-Warn abandons (`LichtwerkClient.abandon`).

## Key Commands

```bash
# Pi 5 overlay (once, in /boot/firmware/config.txt)
dtoverlay=ws2812-pio,gpio=21,num_leds=600,brightness=255

# Service
ssh raspi5 'cd /home/pi/apps/lichtwerk-controller && git pull && sudo systemctl restart lichtwerk-controller'
ssh raspi5 'sudo journalctl -u lichtwerk-controller -f'

# Smoke iris_warn
curl -s -X POST http://127.0.0.1:5006/api/power -H 'Content-Type: application/json' -d '{"power":true}'
curl -s -X POST http://127.0.0.1:5006/api/effect -H 'Content-Type: application/json' -d '{"effect":"iris_warn"}'
```

### Tests

```bash
# Unit tests (no hardware)
python -m pytest tests/ -q
```

### Legacy PM2

PM2/`ecosystem.config.js` is obsolete — use systemd. Root may still be required on classic rpi_ws281x/DMA hosts; on Pi 5 + pio overlay the service typically runs as `pi` with access to `/dev/leds0`.

## GPIO

| Pin | GPIO | Function |
|-----|------|----------|
| 40 | 21 | WS2812B DIN |
| 39 | GND | Common ground with external 5 V PSU |

External 5 V supply required (do not power 600 LEDs from the Pi).
