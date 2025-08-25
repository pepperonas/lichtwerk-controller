# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Lichtwerk LED Controller - A Raspberry Pi-based WS2812B LED strip controller with web interface for controlling 600 LEDs with various effects. 

## Architecture

Two main Python applications:
- **controller.py**: Standalone LED controller that runs effects directly
- **web_controller.py**: Flask-based web server with real-time LED control (port 5006)

Both use rpi_ws281x library and require sudo/root access for GPIO operations. Demo mode activates automatically when hardware is unavailable.

## Key Commands

### Installation
```bash
# Full install with LED libraries
./install.sh

# Quick install (Flask dependencies only)
./install_fast.sh

# Manual install
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Development & Testing
```bash
# Test LEDs (requires sudo)
sudo venv/bin/python test_leds.py

# Run standalone controller
sudo venv/bin/python controller.py --effect rainbow
sudo venv/bin/python controller.py --effect meteor

# Run web controller directly
sudo python3 web_controller.py

# Debug hardware issues  
./debug_hardware.sh

# Test alternative GPIO pins
sudo python3 test_gpio.py 10  # SPI Pin 19
sudo python3 test_gpio.py 12  # PWM Pin 32
sudo python3 test_gpio.py 21  # PCM Pin 40
```

### PM2 Process Management
```bash
# Start/restart/stop
pm2 start ecosystem.config.js
pm2 restart lichtwerk-controller
pm2 stop lichtwerk-controller

# Logs and status
pm2 logs lichtwerk-controller
pm2 status

# Save configuration for auto-restart on boot
pm2 save
pm2 startup systemd -u pi --hp /home/pi
```

### Troubleshooting Common Issues
```bash
# Port 5006 already in use
pm2 delete all
sudo pkill -f web_controller

# Check for audio module conflicts (GPIO 18)
lsmod | grep snd_bcm2835
sudo modprobe -r snd_bcm2835  # Disable if present

# Check SPI status (GPIO 10)
ls /dev/spidev0.0  # Should exist if SPI enabled
```

## Configuration

**config.json** controls:
- GPIO pin 21 (default), 600 LEDs
- Brightness limit (100/255) to prevent power overload  
- Effect parameters for rainbow, solid, pulse, chase, sparkle, strobe, meteor, breathe

**ecosystem.config.js** defines PM2 settings:
- Python3 interpreter
- Auto-restart on failure (max 10 restarts)
- 200MB memory limit
- Log rotation in ./logs/

## API Endpoints

- `GET /` - Web interface
- `GET /api/status` - Current LED status and settings
- `POST /api/control` - Update settings (power, brightness, speed, color, effect)

## Hardware Notes

- **GPIO 21** (Pin 40) → LED data input
- **Power**: 600 LEDs can draw 36A at 5V (180W) - brightness limited to prevent overload
- **Common ground** required between Pi and LED power supply
- **Wiring direction**: Data flows DIN → DOUT (check arrow on strip)

## Adding New Effects

Add to web_controller.py:
```python
def effect_custom(self):
    # Effect implementation
    pass

# Register in effects dictionary
self.effects = {
    'custom': self.effect_custom,
    # ...
}
```

## Critical Errors

- "Can't open /dev/mem: Permission denied" → needs sudo
- "ws2811_init failed" → GPIO/hardware access issue  
- "Port 5006 is in use" → another instance running (check pm2 status)