#!/usr/bin/env python3

import threading
import time
import json
import signal
import sys
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from rpi_ws281x import PixelStrip, Color
import random

app = Flask(__name__)
CORS(app)

class LichtwerkWebController:
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
        
        try:
            self.strip.begin()
        except RuntimeError as e:
            print(f"Warning: LED strip initialization failed: {e}")
            print("Running in demo mode without hardware...")
            self.strip = None
        
        # State variables
        self.running = True
        self.power = False
        self.current_effect = 'solid'
        self.brightness = 100
        self.speed = 50
        self.color = [255, 255, 255]
        self.theater_rainbow = True  # Toggle for theater effect
        self.effect_thread = None
        
        # Effect parameters
        self.effect_params = {
            'rainbow_offset': 0,
            'pulse_direction': 1,
            'pulse_brightness': 0.1,
            'chase_position': 0,
            'sparkle_pixels': [],
            'meteor_positions': [],
            'breathe_direction': 1,
            'breathe_brightness': 0.1
        }
        
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        self.start_effect_loop()
    
    def signal_handler(self, sig, frame):
        print('\nShutting down...')
        self.running = False
        self.clear()
        sys.exit(0)
    
    def clear(self):
        if not self.strip:
            return
        for i in range(self.strip.numPixels()):
            self.strip.setPixelColor(i, Color(0, 0, 0))
        self.strip.show()
    
    def set_pixel(self, index, r, g, b, brightness=1.0):
        if not self.strip:
            return
        r = int(r * brightness * (self.brightness / 255.0))
        g = int(g * brightness * (self.brightness / 255.0))
        b = int(b * brightness * (self.brightness / 255.0))
        self.strip.setPixelColor(index, Color(r, g, b))
    
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
    
    def effect_solid(self):
        if not self.strip:
            return
        for i in range(self.strip.numPixels()):
            self.set_pixel(i, self.color[0], self.color[1], self.color[2])
        self.strip.show()
    
    def effect_rainbow(self):
        if not self.strip:
            return
        for i in range(self.strip.numPixels()):
            pixel_hue = (i + self.effect_params['rainbow_offset']) % 256
            r, g, b = self.wheel(pixel_hue)
            self.set_pixel(i, r, g, b)
        self.strip.show()
        self.effect_params['rainbow_offset'] = (self.effect_params['rainbow_offset'] + 1) % 256
    
    def effect_pulse(self):
        if not self.strip:
            return
        brightness = self.effect_params['pulse_brightness']
        direction = self.effect_params['pulse_direction']
        
        for i in range(self.strip.numPixels()):
            self.set_pixel(i, self.color[0], self.color[1], self.color[2], brightness)
        self.strip.show()
        
        brightness += direction * (self.speed / 1000.0)
        if brightness >= 1.0:
            brightness = 1.0
            direction = -1
        elif brightness <= 0.1:
            brightness = 0.1
            direction = 1
        
        self.effect_params['pulse_brightness'] = brightness
        self.effect_params['pulse_direction'] = direction
    
    def effect_chase(self):
        if not self.strip:
            return
        self.clear()
        segment_size = max(1, int(self.strip.numPixels() * 0.05))
        position = self.effect_params['chase_position']
        
        for i in range(segment_size):
            pixel_index = (position + i) % self.strip.numPixels()
            self.set_pixel(pixel_index, self.color[0], self.color[1], self.color[2])
        
        self.strip.show()
        self.effect_params['chase_position'] = (position + 1) % self.strip.numPixels()
    
    def effect_sparkle(self):
        if not self.strip:
            return
        # Fade existing sparkles
        for pixel_data in self.effect_params['sparkle_pixels']:
            pixel_data['brightness'] *= 0.9
            if pixel_data['brightness'] > 0.01:
                self.set_pixel(pixel_data['index'], 
                             self.color[0], self.color[1], self.color[2], 
                             pixel_data['brightness'])
        
        # Remove dim sparkles
        self.effect_params['sparkle_pixels'] = [
            p for p in self.effect_params['sparkle_pixels'] 
            if p['brightness'] > 0.01
        ]
        
        # Add new sparkles
        density = max(1, int(self.strip.numPixels() * 0.02))
        for _ in range(density):
            if random.random() < (self.speed / 100.0):
                self.effect_params['sparkle_pixels'].append({
                    'index': random.randint(0, self.strip.numPixels() - 1),
                    'brightness': 1.0
                })
        
        self.strip.show()
    
    def effect_strobe(self):
        if not self.strip:
            return
        if time.time() * 1000 % (200 - self.speed * 2) < 50:
            for i in range(self.strip.numPixels()):
                self.set_pixel(i, self.color[0], self.color[1], self.color[2])
        else:
            self.clear()
        self.strip.show()
    
    def effect_meteor(self):
        if not self.strip:
            return
        
        # Enhanced fade effect - store pixel states for proper fading
        if 'pixel_states' not in self.effect_params:
            self.effect_params['pixel_states'] = [[0, 0, 0] for _ in range(self.strip.numPixels())]
            self.effect_params['last_meteor_spawn'] = 0
        
        # Fade all pixels more gradually and visibly
        for i in range(self.strip.numPixels()):
            # Fade factor for smoother, more visible trail
            fade_factor = 0.92  # Slower fade for more visible trail
            self.effect_params['pixel_states'][i][0] = int(self.effect_params['pixel_states'][i][0] * fade_factor)
            self.effect_params['pixel_states'][i][1] = int(self.effect_params['pixel_states'][i][1] * fade_factor)
            self.effect_params['pixel_states'][i][2] = int(self.effect_params['pixel_states'][i][2] * fade_factor)
            
            # Apply faded color
            self.strip.setPixelColor(i, Color(
                self.effect_params['pixel_states'][i][0],
                self.effect_params['pixel_states'][i][1],
                self.effect_params['pixel_states'][i][2]
            ))
        
        # Create new meteors MUCH less frequently with minimum spacing
        self.effect_params['last_meteor_spawn'] = self.effect_params.get('last_meteor_spawn', 0) + 1
        min_spawn_distance = 100  # Minimum frames between spawns
        spawn_chance = (self.speed / 5000.0)  # Drastically reduced spawn rate
        
        # Only spawn if enough time has passed AND random chance succeeds AND not too many meteors
        if (self.effect_params['last_meteor_spawn'] > min_spawn_distance and 
            random.random() < spawn_chance and 
            len(self.effect_params.get('meteor_positions', [])) < 2):  # Max 2 meteors at once
            
            meteor_size = random.randint(10, 20)  # Larger meteors
            self.effect_params['meteor_positions'].append({
                'position': 0,
                'size': meteor_size,
                'speed': random.uniform(1.5, 2.5),  # More consistent speed
                'trail_length': meteor_size * 3  # Longer trail for better visibility
            })
            self.effect_params['last_meteor_spawn'] = 0  # Reset spawn timer
        
        # Update existing meteors
        active_meteors = []
        for meteor in self.effect_params['meteor_positions']:
            meteor['position'] += meteor['speed']
            
            # Draw meteor with enhanced trail
            for i in range(meteor['trail_length']):
                pixel_pos = int(meteor['position'] - i)
                if 0 <= pixel_pos < self.strip.numPixels():
                    # Enhanced brightness calculation for better trail visibility
                    if i < meteor['size']:
                        # Bright head of meteor
                        brightness = 1.0 - (i * 0.05)  # Gradual dimming at head
                    else:
                        # Fading tail
                        tail_position = i - meteor['size']
                        tail_length = meteor['trail_length'] - meteor['size']
                        brightness = max(0.05, 0.8 * (1.0 - (tail_position / tail_length)))
                    
                    # Update pixel state for proper fading
                    self.effect_params['pixel_states'][pixel_pos][0] = int(self.color[0] * brightness)
                    self.effect_params['pixel_states'][pixel_pos][1] = int(self.color[1] * brightness)
                    self.effect_params['pixel_states'][pixel_pos][2] = int(self.color[2] * brightness)
                    
                    self.strip.setPixelColor(pixel_pos, Color(
                        self.effect_params['pixel_states'][pixel_pos][0],
                        self.effect_params['pixel_states'][pixel_pos][1],
                        self.effect_params['pixel_states'][pixel_pos][2]
                    ))
            
            # Keep meteor if still visible (including tail)
            if meteor['position'] < self.strip.numPixels() + meteor['trail_length']:
                active_meteors.append(meteor)
        
        self.effect_params['meteor_positions'] = active_meteors
        self.strip.show()
    
    def fade_toward_color(self, current_color, target_color, fade_amount):
        """FastLED-style fadeTowardColor function"""
        def fade_component(current, target, amount):
            if current == target:
                return current
            elif current < target:
                return min(current + amount, target)
            else:
                return max(current - amount, target)
        
        return [
            fade_component(current_color[0], target_color[0], fade_amount),
            fade_component(current_color[1], target_color[1], fade_amount),
            fade_component(current_color[2], target_color[2], fade_amount)
        ]
    
    def hsv_to_rgb(self, h, s, v):
        """Convert HSV to RGB color space"""
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return int(r * 255), int(g * 255), int(b * 255)
    
    def effect_sinelon(self):
        """Sinelon - a sinusoidal wave with fading trail"""
        if not self.strip:
            return
        
        import math
        
        # Initialize effect parameters
        if 'sinelon_phase' not in self.effect_params:
            self.effect_params['sinelon_phase'] = 0
            self.effect_params['sinelon_pixels'] = [[0, 0, 0] for _ in range(self.strip.numPixels())]
        
        pixels = self.effect_params['sinelon_pixels']
        
        # Fade all pixels
        fade_rate = 0.95
        for i in range(len(pixels)):
            pixels[i][0] = int(pixels[i][0] * fade_rate)
            pixels[i][1] = int(pixels[i][1] * fade_rate)
            pixels[i][2] = int(pixels[i][2] * fade_rate)
        
        # Calculate position using sine wave
        self.effect_params['sinelon_phase'] += self.speed / 500.0
        pos = int((math.sin(self.effect_params['sinelon_phase']) + 1.0) * 0.5 * (len(pixels) - 1))
        
        # Set pixel at position
        # Use the configured color
        color = self.color
        
        if 0 <= pos < len(pixels):
            pixels[pos] = [color[0], color[1], color[2]]
        
        # Apply brightness and update strip
        brightness_factor = self.brightness / 255.0
        for i in range(len(pixels)):
            self.strip.setPixelColor(i, Color(
                int(pixels[i][0] * brightness_factor),
                int(pixels[i][1] * brightness_factor),
                int(pixels[i][2] * brightness_factor)
            ))
        
        self.strip.show()
    
    def effect_juggle(self):
        """Juggle - eight colored dots weaving in and out"""
        if not self.strip:
            return
        
        import math
        
        # Initialize effect parameters
        if 'juggle_phase' not in self.effect_params:
            self.effect_params['juggle_phase'] = 0
            self.effect_params['juggle_pixels'] = [[0, 0, 0] for _ in range(self.strip.numPixels())]
        
        pixels = self.effect_params['juggle_pixels']
        
        # Fade all pixels
        fade_rate = 0.92
        for i in range(len(pixels)):
            pixels[i][0] = int(pixels[i][0] * fade_rate)
            pixels[i][1] = int(pixels[i][1] * fade_rate)
            pixels[i][2] = int(pixels[i][2] * fade_rate)
        
        # Update phase
        self.effect_params['juggle_phase'] += self.speed / 300.0
        phase = self.effect_params['juggle_phase']
        
        # Draw 8 dots
        for dot in range(8):
            pos = int((math.sin((dot + 7) * phase * 1.2) + 1.0) * 0.5 * (len(pixels) - 1))
            if 0 <= pos < len(pixels):
                # Each dot gets a different color
                hue = (dot * 32) / 255.0
                color = self.hsv_to_rgb(hue, 0.8, 1.0)
                # Add to existing pixel value
                pixels[pos][0] = min(255, pixels[pos][0] + color[0])
                pixels[pos][1] = min(255, pixels[pos][1] + color[1])
                pixels[pos][2] = min(255, pixels[pos][2] + color[2])
        
        # Apply brightness and update strip
        brightness_factor = self.brightness / 255.0
        for i in range(len(pixels)):
            self.strip.setPixelColor(i, Color(
                int(pixels[i][0] * brightness_factor),
                int(pixels[i][1] * brightness_factor),
                int(pixels[i][2] * brightness_factor)
            ))
        
        self.strip.show()
    
    def effect_theater_chase_rainbow(self):
        """Theater chase with rainbow or single color"""
        if not self.strip:
            return
        
        # Initialize effect parameters
        if 'theater_j' not in self.effect_params:
            self.effect_params['theater_j'] = 0
            self.effect_params['theater_q'] = 0
        
        # Clear strip
        for i in range(self.strip.numPixels()):
            self.strip.setPixelColor(i, Color(0, 0, 0))
        
        # Draw pattern
        j = self.effect_params['theater_j']
        q = self.effect_params['theater_q']
        
        for i in range(0, self.strip.numPixels(), 3):
            idx = i + q
            if idx < self.strip.numPixels():
                if self.theater_rainbow:
                    # Rainbow color based on position and time
                    hue = ((i + j) % 255) / 255.0
                    color = self.hsv_to_rgb(hue, 1.0, 1.0)
                else:
                    # Use single color
                    color = (self.color[0], self.color[1], self.color[2])
                
                brightness_factor = self.brightness / 255.0
                self.strip.setPixelColor(idx, Color(
                    int(color[0] * brightness_factor),
                    int(color[1] * brightness_factor),
                    int(color[2] * brightness_factor)
                ))
        
        self.strip.show()
        
        # Update counters
        self.effect_params['theater_q'] = (q + 1) % 3
        if q == 2:
            self.effect_params['theater_j'] = (j + 1) % 256
    
    def effect_gradient_fill(self):
        """Gradient fill effect - fills strip with gradient colors"""
        if not self.strip:
            return
        
        # Initialize effect parameters
        if 'gradient_pos' not in self.effect_params:
            self.effect_params['gradient_pos'] = 0
            self.effect_params['gradient_hue1'] = 0
            self.effect_params['gradient_hue2'] = 120
        
        pos = self.effect_params['gradient_pos']
        hue1 = self.effect_params['gradient_hue1'] / 360.0
        hue2 = self.effect_params['gradient_hue2'] / 360.0
        
        # Fill with gradient up to current position
        for i in range(self.strip.numPixels()):
            if i <= pos:
                # Interpolate between two hues
                t = i / max(1, pos)
                hue = hue1 + (hue2 - hue1) * t
                if hue < 0:
                    hue += 1.0
                if hue > 1.0:
                    hue -= 1.0
                color = self.hsv_to_rgb(hue, 1.0, 1.0)
            else:
                color = (0, 0, 0)
            
            brightness_factor = self.brightness / 255.0
            self.strip.setPixelColor(i, Color(
                int(color[0] * brightness_factor),
                int(color[1] * brightness_factor),
                int(color[2] * brightness_factor)
            ))
        
        self.strip.show()
        
        # Update position
        self.effect_params['gradient_pos'] += max(1, int(self.speed / 10))
        if self.effect_params['gradient_pos'] >= self.strip.numPixels():
            self.effect_params['gradient_pos'] = 0
            # New random colors
            import random
            self.effect_params['gradient_hue1'] = random.randint(0, 360)
            self.effect_params['gradient_hue2'] = (self.effect_params['gradient_hue1'] + random.randint(60, 180)) % 360
    
    def effect_fire(self):
        """Fire effect - 1D heat simulation"""
        if not self.strip:
            return
        
        import random
        
        # Initialize heat array
        if 'fire_heat' not in self.effect_params:
            self.effect_params['fire_heat'] = [0] * self.strip.numPixels()
        
        heat = self.effect_params['fire_heat']
        num_leds = len(heat)
        
        # Cooling: How much does each cell cool down every step
        cooling = 55
        
        # Sparking: What chance (out of 255) is there that a new spark will be lit
        sparking = 120
        
        # Step 1: Cool down every cell a little
        for i in range(num_leds):
            cooldown = random.randint(0, ((cooling * 10) // num_leds) + 2)
            heat[i] = max(0, heat[i] - cooldown)
        
        # Step 2: Heat from each cell drifts up and diffuses slightly
        for k in range(num_leds - 1, 1, -1):
            heat[k] = (heat[k - 1] + heat[k - 2] + heat[k - 2]) // 3
        
        # Step 3: Randomly ignite new sparks near the bottom
        if random.randint(0, 255) < sparking:
            y = random.randint(0, min(7, num_leds - 1))
            heat[y] = min(255, heat[y] + random.randint(160, 255))
        
        # Step 4: Convert heat to LED colors
        for j in range(num_leds):
            # Scale heat value to 0-255
            colorindex = min(255, heat[j])
            
            # Calculate color - heat palette (black -> red -> yellow -> white)
            if colorindex < 85:
                # Black to red
                r = (colorindex * 3)
                g = 0
                b = 0
            elif colorindex < 170:
                # Red to yellow
                r = 255
                g = ((colorindex - 85) * 3)
                b = 0
            else:
                # Yellow to white
                r = 255
                g = 255
                b = ((colorindex - 170) * 3)
            
            brightness_factor = self.brightness / 255.0
            # Mirror to make fire rise from bottom
            self.strip.setPixelColor(num_leds - 1 - j, Color(
                int(r * brightness_factor),
                int(g * brightness_factor),
                int(b * brightness_factor)
            ))
        
        self.strip.show()
    
    def effect_breathe(self):
        if not self.strip:
            return
        
        brightness = self.effect_params['breathe_brightness']
        direction = self.effect_params['breathe_direction']
        
        # Set all pixels to same brightness
        for i in range(self.strip.numPixels()):
            self.set_pixel(i, self.color[0], self.color[1], self.color[2], brightness)
        self.strip.show()
        
        # Update breathing pattern
        speed_factor = self.speed / 2000.0
        brightness += direction * speed_factor
        
        if brightness >= 1.0:
            brightness = 1.0
            direction = -1
        elif brightness <= 0.05:
            brightness = 0.05
            direction = 1
        
        self.effect_params['breathe_brightness'] = brightness
        self.effect_params['breathe_direction'] = direction
    
    def run_effect(self):
        if not self.power:
            self.clear()
            return
        
        effects = {
            'solid': self.effect_solid,
            'rainbow': self.effect_rainbow,
            'pulse': self.effect_pulse,
            'chase': self.effect_chase,
            'sparkle': self.effect_sparkle,
            'strobe': self.effect_strobe,
            'meteor': self.effect_meteor,
            'breathe': self.effect_breathe,
            'sinelon': self.effect_sinelon,
            'juggle': self.effect_juggle,
            'theater': self.effect_theater_chase_rainbow,
            'gradient': self.effect_gradient_fill,
            'fire': self.effect_fire
        }
        
        if self.current_effect in effects:
            effects[self.current_effect]()
    
    def start_effect_loop(self):
        def effect_loop():
            while self.running:
                try:
                    self.run_effect()
                    sleep_time = max(0.01, (101 - self.speed) / 1000.0)
                    time.sleep(sleep_time)
                except Exception as e:
                    print(f"Effect error: {e}")
                    time.sleep(0.1)
        
        if self.effect_thread and self.effect_thread.is_alive():
            return
        
        self.effect_thread = threading.Thread(target=effect_loop, daemon=True)
        self.effect_thread.start()
    
    def get_status(self):
        return {
            'power': self.power,
            'effect': self.current_effect,
            'brightness': self.brightness,
            'speed': self.speed,
            'color': {
                'r': self.color[0],
                'g': self.color[1],
                'b': self.color[2]
            },
            'theater_rainbow': self.theater_rainbow,
            'led_count': self.strip.numPixels() if self.strip else 50,
            'pin': self.config['led_config']['pin']
        }

# Global controller instance
controller = LichtwerkWebController()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    return jsonify(controller.get_status())

@app.route('/api/power', methods=['POST'])
def set_power():
    data = request.get_json()
    controller.power = bool(data.get('power', False))
    if not controller.power:
        controller.clear()
    return jsonify({'status': 'ok', 'power': controller.power})

@app.route('/api/brightness', methods=['POST'])
def set_brightness():
    data = request.get_json()
    brightness = int(data.get('brightness', 100))
    controller.brightness = max(0, min(255, brightness))
    return jsonify({'status': 'ok', 'brightness': controller.brightness})

@app.route('/api/speed', methods=['POST'])
def set_speed():
    data = request.get_json()
    speed = int(data.get('speed', 50))
    controller.speed = max(1, min(100, speed))
    return jsonify({'status': 'ok', 'speed': controller.speed})

@app.route('/api/effect', methods=['POST'])
def set_effect():
    data = request.get_json()
    effect = data.get('effect', 'solid')
    valid_effects = ['solid', 'rainbow', 'pulse', 'chase', 'sparkle', 'strobe', 'meteor', 'breathe', 'sinelon', 'juggle', 'theater', 'gradient', 'fire']
    
    if effect in valid_effects:
        controller.current_effect = effect
        # Reset effect parameters when changing effects
        if effect == 'meteor':
            controller.effect_params['meteor_positions'] = []
            controller.effect_params['pixel_states'] = [[0, 0, 0] for _ in range(controller.strip.numPixels() if controller.strip else 600)]
            controller.effect_params['last_meteor_spawn'] = 0
        elif effect == 'breathe':
            controller.effect_params['breathe_brightness'] = 0.1
            controller.effect_params['breathe_direction'] = 1
        elif effect == 'sparkle':
            controller.effect_params['sparkle_pixels'] = []
        elif effect == 'chase':
            controller.effect_params['chase_position'] = 0
        elif effect == 'rainbow':
            controller.effect_params['rainbow_offset'] = 0
        elif effect == 'pulse':
            controller.effect_params['pulse_brightness'] = 0.1
            controller.effect_params['pulse_direction'] = 1
        elif effect == 'sinelon':
            controller.effect_params['sinelon_phase'] = 0
            controller.effect_params['sinelon_pixels'] = [[0, 0, 0] for _ in range(controller.strip.numPixels() if controller.strip else 600)]
        elif effect == 'juggle':
            controller.effect_params['juggle_phase'] = 0
            controller.effect_params['juggle_pixels'] = [[0, 0, 0] for _ in range(controller.strip.numPixels() if controller.strip else 600)]
        elif effect == 'theater':
            controller.effect_params['theater_j'] = 0
            controller.effect_params['theater_q'] = 0
        elif effect == 'gradient':
            controller.effect_params['gradient_pos'] = 0
            controller.effect_params['gradient_hue1'] = 0
            controller.effect_params['gradient_hue2'] = 120
        elif effect == 'fire':
            controller.effect_params['fire_heat'] = [0] * (controller.strip.numPixels() if controller.strip else 600)
            
        return jsonify({'status': 'ok', 'effect': controller.current_effect})
    else:
        return jsonify({'status': 'error', 'message': 'Invalid effect'}), 400

@app.route('/api/color', methods=['POST'])
def set_color():
    data = request.get_json()
    r = max(0, min(255, int(data.get('r', 255))))
    g = max(0, min(255, int(data.get('g', 255))))
    b = max(0, min(255, int(data.get('b', 255))))
    controller.color = [r, g, b]
    return jsonify({'status': 'ok', 'color': {'r': r, 'g': g, 'b': b}})

@app.route('/api/theater_mode', methods=['POST'])
def set_theater_mode():
    data = request.get_json()
    rainbow = data.get('rainbow', True)
    controller.theater_rainbow = bool(rainbow)
    return jsonify({'status': 'ok', 'theater_rainbow': controller.theater_rainbow})

if __name__ == '__main__':
    print("Lichtwerk Web Controller starting...")
    led_count = controller.strip.numPixels() if controller.strip else 50
    print(f"LEDs: {led_count} on GPIO {controller.config['led_config']['pin']} (Demo Mode: {not controller.strip})")
    print("Web interface: http://localhost:5006")
    app.run(host='0.0.0.0', port=5006, debug=False)