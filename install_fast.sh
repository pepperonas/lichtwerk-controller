#!/bin/bash

echo "Fast installation for Lichtwerk Controller..."

# System packages
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv python3-dev

# Create venv
python3 -m venv venv
source venv/bin/activate

# Only install essential package
pip install --upgrade pip
pip install rpi_ws281x==5.0.0

echo "Installation complete!"
echo "Run with: sudo venv/bin/python controller.py"