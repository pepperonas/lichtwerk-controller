#!/usr/bin/env python3

# Minimaler Test mit nur 1 LED
from rpi_ws281x import PixelStrip, Color
import time

print("Minimaler WS2812B Test - nur 1 LED")
print("===================================")

try:
    # Nur 1 LED testen
    strip = PixelStrip(1, 18, 800000, 10, False, 255, 0)
    strip.begin()
    
    print("LED auf Maximum ROT...")
    strip.setPixelColor(0, Color(255, 0, 0))
    strip.show()
    time.sleep(2)
    
    print("LED auf Maximum GRÜN...")
    strip.setPixelColor(0, Color(0, 255, 0))
    strip.show()
    time.sleep(2)
    
    print("LED auf Maximum BLAU...")
    strip.setPixelColor(0, Color(0, 0, 255))
    strip.show()
    time.sleep(2)
    
    print("LED auf Maximum WEIß...")
    strip.setPixelColor(0, Color(255, 255, 255))
    strip.show()
    time.sleep(2)
    
    print("LED aus...")
    strip.setPixelColor(0, Color(0, 0, 0))
    strip.show()
    
    print("\n✓ Test abgeschlossen")
    print("\nWenn KEINE LED geleuchtet hat:")
    print("1. 5V Stromversorgung prüfen")
    print("2. Gemeinsame Masse Pi ↔ Netzteil") 
    print("3. Data-Pin an DIN (nicht DOUT!)")
    print("4. LED-Strip Richtung (Pfeil beachten)")
    
except Exception as e:
    print(f"Fehler: {e}")