#!/usr/bin/env python3

import sys
from rpi_ws281x import PixelStrip, Color
import time

print("WS2812B GPIO Pin Test")
print("=" * 40)
print("\nMögliche GPIO Pins für WS2812B:")
print("- GPIO 18 (PWM0) - Pin 12 auf dem Header")
print("- GPIO 10 (SPI)  - Pin 19 auf dem Header") 
print("- GPIO 12 (PWM0) - Pin 32 auf dem Header")
print("- GPIO 13 (PWM1) - Pin 33 auf dem Header")
print("- GPIO 21 (PCM)  - Pin 40 auf dem Header")
print("\n" + "=" * 40)

if len(sys.argv) < 2:
    print("\nVerwendung: sudo python3 test_gpio.py [GPIO-PIN]")
    print("Beispiel: sudo python3 test_gpio.py 18")
    print("          sudo python3 test_gpio.py 10")
    sys.exit(1)

gpio_pin = int(sys.argv[1])
print(f"\nTeste GPIO {gpio_pin}...")

# Test mit nur 10 LEDs für einfachen Test
LED_COUNT = 10
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 100
LED_INVERT = False

# Channel depends on GPIO pin
# GPIO 18, 12 use PWM channel 0
# GPIO 13, 19 use PWM channel 1
# GPIO 10 (SPI), 21 (PCM) use channel 0
if gpio_pin in [13, 19]:
    LED_CHANNEL = 1
else:
    LED_CHANNEL = 0

try:
    print(f"Initialisiere Strip auf GPIO {gpio_pin}, Channel {LED_CHANNEL}...")
    strip = PixelStrip(LED_COUNT, gpio_pin, LED_FREQ_HZ, LED_DMA, 
                       LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
    strip.begin()
    print("✓ Initialisierung erfolgreich!")
    
    print("\nSetze erste 3 LEDs auf ROT...")
    for i in range(min(3, LED_COUNT)):
        strip.setPixelColor(i, Color(255, 0, 0))
    strip.show()
    time.sleep(1)
    
    print("Setze alle LEDs auf GRÜN...")
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(0, 255, 0))
    strip.show()
    time.sleep(1)
    
    print("Setze alle LEDs auf BLAU...")
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(0, 0, 255))
    strip.show()
    time.sleep(1)
    
    print("LEDs ausschalten...")
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(0, 0, 0))
    strip.show()
    
    print(f"\n✓ GPIO {gpio_pin} funktioniert!")
    
except Exception as e:
    print(f"\n✗ Fehler bei GPIO {gpio_pin}: {e}")
    print("\nMögliche Ursachen:")
    print("1. Falscher GPIO Pin")
    print("2. Fehlende sudo Rechte")
    print("3. Pin bereits in Verwendung")
    print("4. Verkabelung prüfen")

print("\n" + "=" * 40)
print("Physische Pin-Zuordnung (40-pin Header):")
print("GPIO 18 → Physical Pin 12")
print("GPIO 10 → Physical Pin 19")  
print("GPIO 12 → Physical Pin 32")
print("GPIO 13 → Physical Pin 33")
print("GPIO 21 → Physical Pin 40")