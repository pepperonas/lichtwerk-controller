#!/bin/bash

echo "==================================="
echo "WS2812B Hardware Debug Check"
echo "==================================="
echo ""
echo "VERKABELUNG PRÜFEN:"
echo "-------------------"
echo ""
echo "Raspberry Pi 2 → WS2812B LED Strip:"
echo ""
echo "1. DATA Verbindung:"
echo "   RPi Pin 12 (GPIO 18) → LED Strip DIN (Data In)"
echo "   - Meist grünes oder gelbes Kabel"
echo "   - Widerstand 330-470 Ohm empfohlen zwischen Pi und DIN"
echo ""
echo "2. STROMVERSORGUNG (5V):"
echo "   Externes Netzteil 5V+ → LED Strip 5V+ (rot)"
echo "   Externes Netzteil GND → LED Strip GND (schwarz/weiß)"
echo "   - 600 LEDs = max 36A bei voller weiß!"
echo "   - Mindestens 5V/10A Netzteil empfohlen"
echo ""  
echo "3. GEMEINSAME MASSE (WICHTIG!):"
echo "   RPi Pin 6/9/14/20/25/30/34/39 (GND) → Netzteil GND"
echo "   - Ohne gemeinsame Masse kein Signal!"
echo ""
echo "==================================="
echo ""
echo "ALTERNATIVE GPIO PINS testen:"
echo ""
echo "sudo python3 test_gpio.py 10  # SPI Pin 19"
echo "sudo python3 test_gpio.py 12  # PWM Pin 32"
echo "sudo python3 test_gpio.py 21  # PCM Pin 40"
echo ""
echo "==================================="
echo ""
echo "CHECKLISTE:"
echo "[ ] LED Strip hat Strom (5V angeschlossen?)"
echo "[ ] Gemeinsame Masse zwischen Pi und Netzteil"
echo "[ ] Data-Leitung an DIN (nicht DOUT!)"
echo "[ ] Richtung beachten: Pfeil zeigt von DIN → DOUT"
echo "[ ] Level-Shifter 3.3V→5V (optional aber empfohlen)"
echo ""
echo "==================================="

# Check if SPI is enabled
echo ""
echo "SPI Status (für GPIO 10):"
if [ -e /dev/spidev0.0 ]; then
    echo "✓ SPI ist aktiviert"
else
    echo "✗ SPI ist deaktiviert"
    echo "  Aktivieren mit: sudo raspi-config → Interface Options → SPI"
fi

# Check audio (conflicts with PWM)
echo ""
echo "Audio Status (kann mit PWM konfliktieren):"
if lsmod | grep -q snd_bcm2835; then
    echo "⚠ Audio Modul geladen - kann GPIO 18 stören"
    echo "  Deaktivieren mit: sudo modprobe -r snd_bcm2835"
else
    echo "✓ Audio Modul nicht geladen"
fi