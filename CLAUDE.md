# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Lichtwerk LED Controller - A Raspberry Pi-based WS2812B LED strip controller with web interface for controlling 600 LEDs with various effects.

## Architecture

The system consists of two main Python applications:
- **controller.py**: Standalone LED controller that runs effects directly
- **web_controller.py**: Flask-based web server with real-time LED control (port 5006)

Both applications:
- Use the rpi_ws281x library for LED control  
- Read configuration from config.json
- Support demo mode when hardware is unavailable
- Require sudo/root access for GPIO operations

## Key Commands

### Installation
```bash
# Install dependencies
./install.sh

# Quick install (Flask dependencies only)
./install_fast.sh
```

### Development & Testing
```bash
# Test LEDs (requires sudo)
sudo venv/bin/python test_leds.py

# Run standalone controller with specific effect
sudo venv/bin/python controller.py --effect rainbow

# Run web controller directly
sudo python3 web_controller.py

# Debug hardware issues
./debug_hardware.sh
```

### PM2 Process Management
```bash
# Start with PM2
pm2 start ecosystem.config.js

# View logs
pm2 logs lichtwerk-controller

# Restart/stop/status
pm2 restart lichtwerk-controller
pm2 stop lichtwerk-controller
pm2 status

# Save configuration for auto-restart
pm2 save
pm2 startup systemd -u pi --hp /home/pi
```

## Configuration

The system is configured via **config.json**:
- LED hardware settings (GPIO pin 21, 600 LEDs)
- Default brightness limits to prevent power issues
- Effect parameters for rainbow, solid, pulse, chase, sparkle

## Important Notes

1. **GPIO Access**: All LED control operations require sudo/root access. PM2 should run the process as root or with appropriate permissions.

2. **Power Limitations**: 600 LEDs can draw up to 36A at 5V (180W). The configuration limits brightness to prevent overload.

3. **Port 5006**: The web interface runs on port 5006. Check for conflicts if the app fails to start.

4. **Demo Mode**: When hardware initialization fails (e.g., permission issues), the app runs in demo mode without actual LED control.

5. **Error Handling**: Common errors include:
   - "Can't open /dev/mem: Permission denied" - needs sudo
   - "Port 5006 is in use" - another instance is running
   - "ws2811_init failed" - GPIO/hardware access issue

## Deployment

The application is managed via PM2 with automatic restart on failure. The ecosystem.config.js defines:
- Python3 interpreter
- Working directory
- Log file locations
- Memory limits
- Restart policies