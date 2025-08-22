#!/usr/bin/env python3

import time
import sys
from rpi_ws281x import PixelStrip, Color

LED_COUNT = 600
LED_PIN = 21
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 50
LED_INVERT = False
LED_CHANNEL = 0

def test_connection():
    print("Testing LED strip connection...")
    print(f"LED Count: {LED_COUNT}")
    print(f"GPIO Pin: {LED_PIN}")
    print(f"Brightness: {LED_BRIGHTNESS}/255")
    
    try:
        strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
        strip.begin()
        print("✓ LED strip initialized successfully")
        return strip
    except Exception as e:
        print(f"✗ Failed to initialize LED strip: {e}")
        print("\nTroubleshooting:")
        print("1. Make sure you're running with sudo")
        print("2. Check GPIO pin connection (default: GPIO18)")
        print("3. Verify power supply (5V, sufficient amperage)")
        sys.exit(1)

def test_single_led(strip):
    print("\nTesting first 10 LEDs individually...")
    for i in range(min(10, LED_COUNT)):
        strip.setPixelColor(i, Color(255, 0, 0))
        strip.show()
        print(f"LED {i} - RED")
        time.sleep(0.2)
        strip.setPixelColor(i, Color(0, 0, 0))
        strip.show()

def test_all_colors(strip):
    print("\nTesting all LEDs with different colors...")
    
    colors = [
        ("Red", Color(255, 0, 0)),
        ("Green", Color(0, 255, 0)),
        ("Blue", Color(0, 0, 255)),
        ("White", Color(255, 255, 255)),
        ("Off", Color(0, 0, 0))
    ]
    
    for name, color in colors:
        print(f"Setting all LEDs to {name}")
        for i in range(strip.numPixels()):
            strip.setPixelColor(i, color)
        strip.show()
        time.sleep(1)

def test_segments(strip):
    print("\nTesting LED segments (every 100 LEDs)...")
    for segment in range(0, LED_COUNT, 100):
        end = min(segment + 100, LED_COUNT)
        print(f"Lighting LEDs {segment} to {end-1}")
        
        for i in range(strip.numPixels()):
            strip.setPixelColor(i, Color(0, 0, 0))
        
        for i in range(segment, end):
            strip.setPixelColor(i, Color(0, 255, 255))
        
        strip.show()
        time.sleep(0.5)
    
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, Color(0, 0, 0))
    strip.show()

def main():
    print("=== Lichtwerk LED Test ===\n")
    
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("Usage: sudo python3 test_leds.py [test_type]")
        print("\nTest types:")
        print("  all     - Run all tests (default)")
        print("  single  - Test first 10 LEDs individually")
        print("  colors  - Test all LEDs with different colors")
        print("  segments - Test LED segments")
        return
    
    strip = test_connection()
    
    test_type = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    try:
        if test_type == "single":
            test_single_led(strip)
        elif test_type == "colors":
            test_all_colors(strip)
        elif test_type == "segments":
            test_segments(strip)
        else:
            test_single_led(strip)
            test_all_colors(strip)
            test_segments(strip)
        
        print("\n✓ All tests completed successfully!")
        
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    finally:
        print("Clearing LEDs...")
        for i in range(strip.numPixels()):
            strip.setPixelColor(i, Color(0, 0, 0))
        strip.show()

if __name__ == '__main__':
    main()