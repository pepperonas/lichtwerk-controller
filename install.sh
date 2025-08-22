#!/bin/bash

echo "Installing Lichtwerk Controller dependencies..."

# System dependencies für WS2812B
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv python3-dev

# Python virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python packages
pip install --upgrade pip
pip install rpi_ws281x
pip install adafruit-circuitpython-neopixel
pip install numpy

echo "Installation complete!"
echo "Remember to run with sudo for GPIO access: sudo venv/bin/python controller.py"