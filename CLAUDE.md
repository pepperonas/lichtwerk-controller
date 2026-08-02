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

**Driver contract — one frame per `open()`.** Measured on `ws2812_pio_rp1`: a second `write()` on the same fd always fails `ENOSPC`, and waiting does not clear it (verified to 1000 ms); the device is not seekable (`lseek`/`pwrite` → `ESPIPE`). An earlier "keep the fd open" optimisation therefore could not work — every frame silently took a failed-write → close → reopen → write path. `show()` now opens per frame, which costs 0.002 ms. Brightness scaling uses a `bytes.translate` LUT, not a per-byte generator.

**Frame budget:** 600 LEDs × 24 bit × 1.25 µs = **18.0 ms shift-out → 55.6 fps ceiling**. The wash paces on a monotonic deadline at `WASH_FPS = 30`, skipping ahead if late rather than writing into an in-flight DMA transfer. Verified live at exactly 30.0 fps, 0 bytes written while idle.

**Latency:** `POST /api/effect iris_warn` auto-powers and paints the first frame in-request. Disco sync uses `POST /api/solid` (one RTT). Flask `threaded=True`.

**Known quirk:** `setBrightness()` is never called, so the driver-level brightness stays at `config.json` `led_brightness` (100) and every `show()` scales to ~39%. All effects paint `self.brightness` themselves, so this is a second, hidden multiplier. `show_payload()` deliberately bypasses it — see below.

## Architecture

- **`web_controller.py`**: Flask server + effect loop (port 5006). Production entrypoint.
- **`pio_strip.py`**: PixelStrip/Color compatible with rpi_ws281x API → persistent FD write to `/dev/leds0`.
- **`controller.py`**: CLI/standalone effects (legacy/dev).
- Demo mode if strip init fails (no hardware).

## Iris-Warn (`effect_iris_warn` + `iris_wash.py`)

Used by **disco-controller Strip-Warn** (`warn_hue` API key, threshold `warn_thr` SPL). One POST from disco per edge; no per-frame HTTP.

The strip is a **faithful port of the dB-Analyse page background** (`body.over-iris` in disco-controller's `public/stats.html`) — not an interpretation of it. `iris_wash.py` reproduces the browser composite exactly: premultiplied radial-gradient interpolation, srcOver in sRGB, the `iris-breathe` keyframes and the real `cubic-bezier(.2,0,0,1)` easing (solved, not approximated by a smoothstep).

Two things the strip needs that the browser gets for free:

- **Geometry.** The page gradient is 2-D, the strip is a line, so we render the horizontal **centre scanline** through the gradient origin (50% / 40%). The ellipse is 120% of viewport width, so the strip spans t ∈ [0, 0.417] — a gentle falloff from the middle to both ends, exactly as on screen.
- **Gamma.** CSS colours are sRGB for a ~2.2-gamma display; WS2812 PWM is linear. Writing the sRGB byte straight out renders the low channels far too bright and turns the brick red into washed pink. We convert sRGB → linear, then apply `exposure` so it still reads as a warning light rather than a dim replica of a screen.

**No white sparks** — the page has none; the old effect invented them. Dropping them is also what makes precomputation possible.

The whole breathe is **precomputed at arm time** (64 phase steps × 600 LEDs × 4 B ≈ 150 KB), so a frame costs an index lookup plus one write. Release ramps down over **0.55 s**, matching the page's `transition: background .55s`; re-crossing mid-fade snaps straight back to the peak. Disarm (`/api/warn_mode {on:false}`) still cuts hard.

`config.json` → `iris_wash`:

| Key | Default | Meaning |
|---|---|---|
| `steps` | 64 | frames per breathe ramp |
| `exposure` | 1.8 | post-gamma gain |
| `max_current_a` | `null` | caps the 5 V draw by scaling `exposure` down |

A full-strip wash at `exposure` 1.8 peaks near **10.8 A** on 600 LEDs (the service logs the figure on arm). Set `max_current_a` to the supply rating if it is tighter than that.

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
