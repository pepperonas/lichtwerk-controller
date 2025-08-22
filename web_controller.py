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
        
        # Create new meteors less frequently
        if random.random() < (self.speed / 500.0):  # Reduced from 200 to 500 for fewer meteors
            meteor_size = random.randint(5, 12)  # Slightly larger meteors
            self.effect_params['meteor_positions'].append({
                'position': 0,
                'size': meteor_size,
                'speed': random.uniform(1.0, 3.0),  # Slightly faster for better effect
                'trail_length': meteor_size * 3  # Longer trail for better visibility
            })
        
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
    
    def effect_meteor_adv(self):
        """FastLED-inspired meteor effect with realistic trails"""
        if not self.strip:
            return
        
        # Initialize FastLED-style meteor parameters
        if 'meteor_adv_position' not in self.effect_params:
            self.effect_params['meteor_adv_position'] = 0
            self.effect_params['meteor_adv_size'] = 6  # FastLED typical meteor size
            self.effect_params['meteor_adv_trail_decay'] = 64  # FastLED decay value (0-255)
            self.effect_params['meteor_adv_random_decay'] = True
            self.effect_params['meteor_adv_color_mode'] = 'changing'  # 'static' or 'changing'
            self.effect_params['meteor_adv_hue'] = 0  # For changing colors
        
        # Get background color (dark for dramatic effect)
        background_color = [16, 0, 0]  # Dark red background like FastLED examples
        
        # FastLED-style fade all pixels toward background color
        for i in range(self.strip.numPixels()):
            # Random decay for organic look (FastLED feature)
            if not self.effect_params['meteor_adv_random_decay'] or random.randint(0, 10) > 5:
                current_r = (self.strip.getPixelColor(i) >> 16) & 0xFF
                current_g = (self.strip.getPixelColor(i) >> 8) & 0xFF  
                current_b = self.strip.getPixelColor(i) & 0xFF
                
                # FastLED-style fadeTowardColor function
                new_r, new_g, new_b = self.fade_toward_color(
                    [current_r, current_g, current_b],
                    background_color,
                    self.effect_params['meteor_adv_trail_decay']
                )
                self.strip.setPixelColor(i, Color(new_r, new_g, new_b))
        
        # Get meteor color based on mode
        if self.effect_params['meteor_adv_color_mode'] == 'static':
            meteor_color = self.color
        else:
            # Cycling rainbow colors (FastLED-style)
            self.effect_params['meteor_adv_hue'] = (self.effect_params['meteor_adv_hue'] + 1) % 360
            h = self.effect_params['meteor_adv_hue'] / 360.0
            meteor_color = self.hsv_to_rgb(h, 1.0, 1.0)
        
        # Draw meteor with FastLED-style approach
        meteor_pos = int(self.effect_params['meteor_adv_position'])
        meteor_size = self.effect_params['meteor_adv_size']
        
        for j in range(meteor_size):
            pixel_idx = meteor_pos - j
            if 0 <= pixel_idx < self.strip.numPixels():
                self.strip.setPixelColor(pixel_idx, Color(meteor_color[0], meteor_color[1], meteor_color[2]))
        
        # Advance meteor position (FastLED linear movement)
        speed_factor = (self.speed / 100.0) * 2.0  # Scale speed appropriately
        self.effect_params['meteor_adv_position'] += speed_factor
        
        # Reset meteor when it exits the strip (FastLED behavior)
        if self.effect_params['meteor_adv_position'] >= self.strip.numPixels() + meteor_size:
            self.effect_params['meteor_adv_position'] = 0
        
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
            'meteor_adv': self.effect_meteor_adv,
            'breathe': self.effect_breathe
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
    valid_effects = ['solid', 'rainbow', 'pulse', 'chase', 'sparkle', 'strobe', 'meteor', 'meteor_adv', 'breathe']
    
    if effect in valid_effects:
        controller.current_effect = effect
        # Reset effect parameters when changing effects
        if effect == 'meteor':
            controller.effect_params['meteor_positions'] = []
        elif effect == 'meteor_adv':
            controller.effect_params['meteor_adv_position'] = 0
            controller.effect_params['meteor_adv_hue'] = 0
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

@app.route('/api/color_mode', methods=['POST'])
def set_color_mode():
    data = request.get_json()
    mode = data.get('mode', 'changing')
    if mode in ['static', 'changing']:
        if 'meteor_adv_color_mode' in controller.effect_params:
            controller.effect_params['meteor_adv_color_mode'] = mode
        return jsonify({'status': 'ok', 'color_mode': mode})
    else:
        return jsonify({'status': 'error', 'message': 'Invalid color mode'}), 400

if __name__ == '__main__':
    print("Lichtwerk Web Controller starting...")
    led_count = controller.strip.numPixels() if controller.strip else 50
    print(f"LEDs: {led_count} on GPIO {controller.config['led_config']['pin']} (Demo Mode: {not controller.strip})")
    print("Web interface: http://localhost:5006")
    app.run(host='0.0.0.0', port=5006, debug=False)