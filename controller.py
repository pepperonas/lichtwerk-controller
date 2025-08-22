#!/usr/bin/env python3

import time
import json
import signal
import sys
import argparse
from rpi_ws281x import PixelStrip, Color

class LichtwerkController:
    def __init__(self, config_file='config.json'):
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        
        led_cfg = self.config['led_config']
        self.strip = PixelStrip(
            led_cfg['led_count'],
            led_cfg['pin'],
            led_cfg['led_freq_hz'],
            led_cfg['led_dma'],
            led_cfg['led_invert'],
            led_cfg['led_brightness'],
            led_cfg['led_channel']
        )
        
        self.strip.begin()
        self.running = True
        self.current_effect = self.config['default_effect']
        self.effect_config = self.config['effects']
        
        self.pixels = [[0, 0, 0] for _ in range(led_cfg['led_count'])]
        
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, sig, frame):
        print('\nShutting down...')
        self.running = False
        self.clear()
        sys.exit(0)
    
    def clear(self):
        for i in range(self.strip.numPixels()):
            self.strip.setPixelColor(i, Color(0, 0, 0))
        self.strip.show()
    
    def set_pixel(self, index, r, g, b, brightness=1.0):
        r = int(r * brightness)
        g = int(g * brightness)
        b = int(b * brightness)
        self.strip.setPixelColor(index, Color(r, g, b))
    
    def rainbow_effect(self):
        cfg = self.effect_config['rainbow']
        j = 0
        
        while self.running and self.current_effect == 'rainbow':
            for i in range(self.strip.numPixels()):
                pixel_hue = (i + j) % 256
                r, g, b = self.wheel(pixel_hue)
                self.set_pixel(i, r, g, b, cfg['brightness'])
            
            self.strip.show()
            time.sleep(cfg['speed'])
            j = (j + 1) % 256
    
    def solid_effect(self):
        cfg = self.effect_config['solid']
        color = cfg['color']
        
        for i in range(self.strip.numPixels()):
            self.set_pixel(i, color[0], color[1], color[2], cfg['brightness'])
        self.strip.show()
        
        while self.running and self.current_effect == 'solid':
            time.sleep(0.1)
    
    def pulse_effect(self):
        cfg = self.effect_config['pulse']
        color = cfg['color']
        direction = 1
        brightness = cfg['min_brightness']
        
        while self.running and self.current_effect == 'pulse':
            for i in range(self.strip.numPixels()):
                self.set_pixel(i, color[0], color[1], color[2], brightness)
            self.strip.show()
            
            brightness += direction * cfg['speed']
            if brightness >= cfg['max_brightness']:
                brightness = cfg['max_brightness']
                direction = -1
            elif brightness <= cfg['min_brightness']:
                brightness = cfg['min_brightness']
                direction = 1
            
            time.sleep(0.01)
    
    def chase_effect(self):
        cfg = self.effect_config['chase']
        color = cfg['color']
        segment_size = cfg['segment_size']
        position = 0
        
        while self.running and self.current_effect == 'chase':
            self.clear()
            
            for i in range(segment_size):
                pixel_index = (position + i) % self.strip.numPixels()
                self.set_pixel(pixel_index, color[0], color[1], color[2])
            
            self.strip.show()
            time.sleep(cfg['speed'])
            position = (position + 1) % self.strip.numPixels()
    
    def sparkle_effect(self):
        import random
        cfg = self.effect_config['sparkle']
        color = cfg['color']
        fade_speed = cfg['fade_speed']
        density = cfg['density']
        
        brightness_array = [0.0] * self.strip.numPixels()
        
        while self.running and self.current_effect == 'sparkle':
            for i in range(len(brightness_array)):
                brightness_array[i] *= fade_speed
            
            num_sparkles = int(self.strip.numPixels() * density)
            for _ in range(num_sparkles):
                if random.random() < 0.1:
                    index = random.randint(0, self.strip.numPixels() - 1)
                    brightness_array[index] = 1.0
            
            for i in range(self.strip.numPixels()):
                self.set_pixel(i, color[0], color[1], color[2], brightness_array[i])
            
            self.strip.show()
            time.sleep(0.02)
    
    def wheel(self, pos):
        if pos < 0 or pos > 255:
            r = g = b = 0
        elif pos < 85:
            r = pos * 3
            g = 255 - pos * 3
            b = 0
        elif pos < 170:
            pos -= 85
            r = 255 - pos * 3
            g = 0
            b = pos * 3
        else:
            pos -= 170
            r = 0
            g = pos * 3
            b = 255 - pos * 3
        return r, g, b
    
    def run_effect(self, effect_name):
        self.current_effect = effect_name
        
        effects = {
            'rainbow': self.rainbow_effect,
            'solid': self.solid_effect,
            'pulse': self.pulse_effect,
            'chase': self.chase_effect,
            'sparkle': self.sparkle_effect
        }
        
        if effect_name in effects:
            print(f"Running effect: {effect_name}")
            effects[effect_name]()
        else:
            print(f"Unknown effect: {effect_name}")
    
    def run(self):
        print(f"Lichtwerk Controller started with {self.strip.numPixels()} LEDs")
        print(f"Running default effect: {self.current_effect}")
        print("Press Ctrl+C to exit")
        
        self.run_effect(self.current_effect)

def main():
    parser = argparse.ArgumentParser(description='Lichtwerk LED Controller')
    parser.add_argument('--effect', type=str, help='Effect to run (rainbow, solid, pulse, chase, sparkle)')
    parser.add_argument('--config', type=str, default='config.json', help='Config file path')
    
    args = parser.parse_args()
    
    controller = LichtwerkController(args.config)
    
    if args.effect:
        controller.current_effect = args.effect
    
    controller.run()

if __name__ == '__main__':
    main()