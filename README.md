# Lichtwerk LED Controller

A sophisticated WS2812B LED strip controller for Raspberry Pi with web interface, featuring multiple animated effects and real-time control.

## Features

- **Modern Web Interface**: Control LEDs through an intuitive web UI on port 5006 with Teufel-inspired design
- **Multiple Effects**: Rainbow, Pulse, Chase, Sparkle, Strobe, Meteor, Breathe, Sinelon, Juggle, Theater, Gradient, Fire
- **Interactive Controls**: Circular power button, theater mode toggle, and real-time parameter adjustment
- **Real-time Control**: Adjust brightness, speed, and colors on the fly
- **PM2 Integration**: Professional process management with auto-restart
- **Demo Mode**: Runs without hardware for testing
- **600 LED Support**: Optimized for large LED installations

## Hardware Requirements

- Raspberry Pi (tested on Pi 2/3/4)
- WS2812B LED Strip (up to 600 LEDs)
- 5V Power Supply (sufficient amperage - 600 LEDs need ~36A at full brightness)
- Level shifter (recommended for 3.3V → 5V signal conversion)

### Wiring

- **GPIO 21** (Pin 40) → Data input of LED strip
- **5V Power Supply** → LED strip power (connect at multiple points for long strips)
- **Common GND** between Raspberry Pi and LED power supply

## Installation

### Quick Install

```bash
# Clone the repository
git clone https://github.com/pepperonas/lichtwerk-controller.git
cd lichtwerk-controller

# Install dependencies
./install.sh

# Or for web controller only
./install_fast.sh
```

### Manual Installation

```bash
# System dependencies
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv

# Python environment
python3 -m venv venv
source venv/bin/activate

# Python packages
pip install -r requirements.txt
```

## Usage

### Web Controller (Recommended)

```bash
# Start with PM2
pm2 start ecosystem.config.js

# Or run directly
sudo python3 web_controller.py
```

Access the web interface at: `http://<raspberry-pi-ip>:5006`

### Standalone Controller

```bash
# Run with default effect
sudo venv/bin/python controller.py

# Run with specific effect
sudo venv/bin/python controller.py --effect rainbow
sudo venv/bin/python controller.py --effect meteor
```

### PM2 Management

```bash
# View status
pm2 status

# View logs
pm2 logs lichtwerk-controller

# Restart
pm2 restart lichtwerk-controller

# Stop
pm2 stop lichtwerk-controller

# Setup auto-start on boot
pm2 startup systemd -u pi --hp /home/pi
pm2 save
```

## Configuration

Edit `config.json` to customize:

```json
{
    "led_config": {
        "pin": 21,              // GPIO pin
        "led_count": 600,       // Number of LEDs
        "led_brightness": 100,  // Max brightness (0-255)
        "led_freq_hz": 800000,  // LED signal frequency
        "led_dma": 10,          // DMA channel
        "led_channel": 0        // PWM channel
    },
    "default_effect": "rainbow",
    "effects": {
        // Effect-specific settings
    }
}
```

## Available Effects

- **Rainbow**: Smooth color transitions across the spectrum
- **Solid**: Single static color
- **Pulse**: Breathing effect with adjustable speed
- **Chase**: Running lights effect
- **Sparkle**: Random twinkling pixels
- **Strobe**: Fast flashing effect
- **Meteor**: Shooting star effect with trails (fixed in latest version)
- **Breathe**: Gentle fading in and out
- **Sinelon**: Sinusoidal wave with fading trail
- **Juggle**: Eight colored dots weaving in and out
- **Theater**: Theater chase with rainbow colors
- **Gradient**: Gradient fill effect
- **Fire**: Realistic fire simulation

## API Endpoints

- `GET /` - Web interface
- `GET /api/status` - Current status and settings
- `POST /api/power` - Toggle power on/off
- `POST /api/brightness` - Set brightness (0-255)
- `POST /api/speed` - Set speed/intensity (1-100)
- `POST /api/color` - Set RGB color values
- `POST /api/effect` - Change LED effect
- `POST /api/theater_mode` - Toggle theater effect rainbow/single color mode

## Safety Notes

⚠️ **Power Considerations**:
- 600 LEDs at full white brightness can draw up to 36A (180W)
- Use appropriate gauge wiring
- Connect power at multiple points along the strip
- Consider using a current-limiting resistor on the data line
- Always test with reduced brightness first

## Troubleshooting

### Permission Denied
- LED control requires root access: use `sudo` or run with PM2

### LEDs Not Responding
- Check GPIO pin configuration in `config.json`
- Verify common ground between Pi and LED power supply
- Ensure data line voltage levels (3.3V vs 5V)

### Port Already in Use
- Another instance may be running
- Check with: `pm2 status` or `ps aux | grep web_controller`
- Kill existing processes: `pm2 delete all` or `sudo pkill -f web_controller`

### LEDs Flickering
- Insufficient power supply
- Reduce brightness in configuration
- Add capacitor (1000µF) across power supply terminals

## Development

### Project Structure

```
lichtwerk-controller/
├── web_controller.py    # Flask web server with effects
├── controller.py        # Standalone LED controller
├── config.json         # Configuration file
├── ecosystem.config.js # PM2 configuration
├── templates/          # HTML templates
├── static/            # CSS/JS assets
└── logs/              # PM2 logs
```

### Adding New Effects

1. Add effect method to `web_controller.py`:
```python
def effect_custom(self):
    # Your effect logic here
    pass
```

2. Register in the effects dictionary:
```python
effects = {
    'custom': self.effect_custom,
    # ...
}
```

## License

MIT License - See LICENSE file for details

## Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss what you would like to change.

## Author

- [pepperonas](https://github.com/pepperonas)

## Acknowledgments

- Built with [rpi_ws281x](https://github.com/jgarff/rpi_ws281x) library
- Web interface powered by Flask
- Process management by PM2