#!/usr/bin/env python3

import threading
import time
import json
import signal
import sys
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
try:
    from pio_strip import PixelStrip, Color  # Pi 5: ws2812-pio /dev/leds0
except ImportError:
    from rpi_ws281x import PixelStrip, Color
import iris_wash
import math
import random

# Strip-Warn pacing. The WS2812 shift-out for 600 LEDs is 18 ms (55.6 fps
# ceiling); a 1.8 s breathe ramp is perfectly smooth at 30 fps, and the extra
# headroom keeps us from ever writing into an in-flight DMA transfer.
WASH_FPS = 30.0
WASH_FRAME_S = 1.0 / WASH_FPS

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
        # Strip-Warn: exclusive ownership while disco Strip-Warn is armed
        self.strip_warn_over = False   # mirrors page body.over-iris
        self.strip_warn_mode = False   # True while Strip-Warn owns the strip
        self._strip_lock = threading.Lock()

        # Strip-Warn wash — the dB-Analyse page background, see iris_wash.py.
        # `max_current_a` caps the 5 V draw of a full-strip red wash by scaling
        # the exposure; leave it null to render at full exposure.
        wash_cfg = self.config.get('iris_wash') or {}
        self._wash_steps = max(2, int(wash_cfg.get('steps', iris_wash.DEFAULT_STEPS)))
        self._wash_exposure = float(wash_cfg.get('exposure', iris_wash.DEFAULT_EXPOSURE))
        self._wash_max_current_a = wash_cfg.get('max_current_a') or None
        self._wash_cache = ()
        self._wash_n = 0
        self._wash_t0 = None           # breathe origin; None while idle
        self._wash_fade_t0 = None      # release ramp origin; None when not fading
        self._wash_fade_from = 0       # frame the fade started from
        # White highlights on top of the wash — sparse, so the base frame stays
        # precomputed and only a handful of LEDs are rewritten per frame.
        self._wash_sparks_on = bool(wash_cfg.get('sparks', True))
        self._wash_sparks = []         # [(centre_led, age_s), ...]
        self._wash_spark_ts = None
        self._wash_kernel = iris_wash.spark_kernel()
        
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
        self._cleared = False          # skip redundant black show() when already dark
        self._effect_wake = threading.Event()
        
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        self.start_effect_loop()
    
    def signal_handler(self, sig, frame):
        print('\nShutting down...')
        self.running = False
        self._effect_wake.set()
        self.clear()
        if self.strip and hasattr(self.strip, 'close'):
            try:
                self.strip.close()
            except Exception:
                pass
        sys.exit(0)
    
    def clear(self, force=False):
        if not self.strip:
            return
        if self._cleared and not force:
            return
        with self._strip_lock:
            if self._cleared and not force:
                return
            if hasattr(self.strip, 'fill'):
                self.strip.fill(Color(0, 0, 0))
            else:
                for i in range(self.strip.numPixels()):
                    self.strip.setPixelColor(i, Color(0, 0, 0))
            self.strip.show()
            self._cleared = True
    
    def wake_effect(self):
        """Interrupt effect-loop sleep so the next frame paints ASAP."""
        self._effect_wake.set()
    
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
        scale = max(0.0, min(1.0, self.brightness / 255.0))
        c = Color(int(self.color[0] * scale), int(self.color[1] * scale), int(self.color[2] * scale))
        if hasattr(self.strip, 'fill'):
            self.strip.fill(c)
        else:
            for i in range(self.strip.numPixels()):
                self.strip.setPixelColor(i, c)
        self.strip.show()
        self._cleared = False
    
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
    

    def _wash_frames(self):
        """Precomputed breathe ramp — rebuilt only when the LED count changes."""
        n = self.strip.numPixels() if self.strip else 0
        if n <= 0:
            return ()
        if self._wash_n != n or not self._wash_cache:
            self._wash_cache = iris_wash.build_frames(
                n, self._wash_steps, self._wash_exposure, self._wash_max_current_a)
            self._wash_n = n
            exposure = (iris_wash.fit_exposure(n, self._wash_max_current_a, self._wash_exposure)
                        if self._wash_max_current_a else self._wash_exposure)
            peak = iris_wash.estimate_current_a(n, 1.0, exposure)
            spark = iris_wash.spark_current_a() if self._wash_sparks_on else 0.0
            print(f"iris wash: {len(self._wash_cache)} frames x {n} LEDs, "
                  f"exposure {exposure:.2f}, peak ~{peak:.1f} A"
                  + (f" (+{spark:.1f} A highlights)" if spark else " (no highlights)"))
        return self._wash_cache

    def _wash_engage(self):
        """Threshold crossed — start the wash at the breathe peak.

        `alternate` reaches its maximum half a cycle in, so back-dating t0 by
        one period lands the first frame on the peak: the warning arrives at
        full intensity and breathes down from there.
        """
        self._wash_t0 = time.monotonic() - iris_wash.BREATHE_PERIOD_S
        self._wash_fade_t0 = None
        self._wash_sparks = []
        self._wash_spark_ts = None
        self._wash_frames()

    def _wash_release(self):
        """Back under threshold — fade out like the page's .55 s transition."""
        if self._wash_t0 is None and self._wash_fade_t0 is None:
            return
        if self._wash_fade_t0 is None:
            self._wash_fade_from = self._wash_index()
            self._wash_fade_t0 = time.monotonic()
        self._wash_t0 = None

    def _wash_index(self):
        if self._wash_t0 is None:
            return self._wash_steps - 1
        return iris_wash.frame_index(time.monotonic() - self._wash_t0, self._wash_steps)

    def _iris_abort(self):
        """Hard-stop the wash — black at once, no fade (disarm / explicit off)."""
        self._wash_t0 = None
        self._wash_fade_t0 = None
        self.clear(force=True)

    def _show_payload(self, payload, gain=255):
        """Write a precomputed frame; falls back to per-pixel on legacy drivers.

        The master brightness slider is folded in here rather than inside the
        driver, so the wash keeps exactly the exposure `iris_wash` rendered.
        """
        strip = self.strip
        if strip is None:
            return
        gain = max(0, min(255, gain * max(0, min(255, self.brightness)) // 255))
        show_payload = getattr(strip, 'show_payload', None)
        if show_payload is not None:
            show_payload(payload, gain)
            return
        for i in range(strip.numPixels()):
            j = i * 4
            strip.setPixelColor(i, Color(payload[j] * gain // 255,
                                         payload[j + 1] * gain // 255,
                                         payload[j + 2] * gain // 255))
        strip.show()

    def _paint_wash_fade(self):
        """Drive the release ramp. Runs with power=False so it can finish."""
        frames = self._wash_frames()
        if not frames or self._wash_fade_t0 is None:
            self._wash_fade_t0 = None
            return
        gain = iris_wash.release_gain(time.monotonic() - self._wash_fade_t0)
        if gain <= 0:
            self._wash_fade_t0 = None
            self.clear(force=True)
            return
        with self._strip_lock:
            self._show_payload(frames[min(self._wash_fade_from, len(frames) - 1)], gain)
        self._cleared = False

    def effect_iris_warn(self):
        """Paint the dB-Analyse page wash (`body.over-iris`) onto the chain.

        The colour maths lives in `iris_wash`: a faithful port of the page's
        radial gradient, breathe keyframes and cubic-bezier easing, gamma
        corrected into the WS2812's linear PWM domain. The whole breathe is
        precomputed at arm time, so a frame costs an index lookup and a write.

        `strip_warn_over` is the gate — the same bit the page renders as
        `over-iris`. Under threshold the strip fades out and stays black.
        """
        if not self.strip:
            return
        if not self.power or not self.strip_warn_over:
            if self._wash_fade_t0 is not None:
                self._paint_wash_fade()
            elif not self._cleared:
                self._iris_abort()
            return

        frames = self._wash_frames()
        if not frames:
            return
        if self._wash_t0 is None:
            self._wash_engage()
        now = time.monotonic()
        idx = iris_wash.frame_index(now - self._wash_t0, len(frames))
        payload = frames[idx]
        if self._wash_sparks_on:
            payload = self._paint_sparks(payload, idx, len(frames), now)
        with self._strip_lock:
            # Re-check under the lock so a concurrent release is not overpainted
            if not self.power or not self.strip_warn_over:
                return
            self._show_payload(payload)
        self._cleared = False

    def _paint_sparks(self, base, idx, steps, now):
        """Lay fading white highlights over the precomputed wash frame.

        `bytearray(base)` is a C-level copy and only a few LEDs are rewritten
        afterwards, so the highlights cost roughly nothing and the breathe stays
        precomputed. Added additively: the payload is already in linear PWM
        space, which is where light actually sums.
        """
        dt = now - (self._wash_spark_ts if self._wash_spark_ts is not None else now)
        self._wash_spark_ts = now
        n = self.strip.numPixels() if self.strip else 0
        if n <= 0:
            return base

        e = idx / max(1, steps - 1)          # breathe phase drives the spawn rate
        alive = [(c, a + dt) for c, a in self._wash_sparks
                 if a + dt < iris_wash.SPARK_LIFE_S]
        expected = iris_wash.spark_rate(e) * dt
        while expected > 0.0 and len(alive) < iris_wash.SPARK_MAX:
            if random.random() < min(1.0, expected):
                alive.append((random.randrange(n), 0.0))
            expected -= 1.0
        self._wash_sparks = alive
        if not alive:
            return base

        buf = bytearray(base)
        kernel = self._wash_kernel
        w = iris_wash.SPARK_WIDTH
        for centre, age in alive:
            env = iris_wash.spark_envelope(age)
            if env <= 0.0:
                continue
            amp = env * iris_wash.SPARK_PEAK
            for k, off in enumerate(range(-w, w + 1)):
                i = centre + off
                if i < 0 or i >= n:
                    continue
                add = int(amp * kernel[k])
                if add <= 0:
                    continue
                j = i * 4
                for c in (j, j + 1, j + 2):
                    v = buf[c] + add
                    buf[c] = 255 if v > 255 else v
        return bytes(buf)

    def run_effect(self):
        if self._wash_fade_t0 is not None:
            # The release ramp outlives power=False so it can run down to black
            self._paint_wash_fade()
            return
        if not self.power:
            # One clear when off — don't hammer /dev/leds0 every frame
            if not self._cleared:
                self.clear(force=True)
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
            'fire': self.effect_fire,
            'iris_warn': self.effect_iris_warn
        }
        
        if self.current_effect in effects:
            effects[self.current_effect]()
            # Non-iris effects always leave the strip potentially lit
            if self.current_effect != 'iris_warn':
                self._cleared = False

    def start_effect_loop(self):
        def effect_loop():
            deadline = time.monotonic()
            while self.running:
                try:
                    self.run_effect()
                    washing = (self.current_effect == 'iris_warn'
                               or self._wash_fade_t0 is not None)
                    if washing:
                        # Deadline pacing, not sleep-after-work: the frame
                        # budget stays honest regardless of paint time. If we
                        # fall behind we skip ahead instead of queueing frames
                        # into an in-flight DMA transfer.
                        now = time.monotonic()
                        deadline += WASH_FRAME_S
                        if deadline < now:
                            deadline = now + WASH_FRAME_S
                        sleep_time = deadline - now
                    else:
                        sleep_time = max(0.01, (101 - self.speed) / 1000.0)
                        deadline = time.monotonic() + sleep_time
                    # Interruptible sleep: API changes paint on the next wake
                    if self._effect_wake.wait(timeout=sleep_time):
                        deadline = time.monotonic()
                    self._effect_wake.clear()
                except Exception as e:
                    print(f"Effect error: {e}")
                    time.sleep(0.05)

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
            # Frames the kernel refused. Non-zero means we are writing into an
            # in-flight DMA transfer — the pacing is off, not the paint.
            'dropped_frames': getattr(self.strip, 'dropped_frames', 0) if self.strip else 0,
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
    data = request.get_json() or {}
    controller.power = bool(data.get('power', False))
    if not controller.power:
        controller.strip_warn_over = False
        # Explicit power-off also leaves Strip-Warn mode (disco will re-arm if needed)
        if data.get('clear_warn_mode', False):
            controller.strip_warn_mode = False
        controller._iris_abort()
    controller.wake_effect()
    return jsonify({'status': 'ok', 'power': controller.power})


@app.route('/api/warn_gate', methods=['POST'])
def warn_gate():
    """Edge-triggered Strip-Warn gate — mirrors page body.over-iris.

    over=true  → wash in at the breathe peak, then the 1.8 s CSS breathe
    over=false → .55 s fade to black, matching the page's background transition
    """
    data = request.get_json() or {}
    over = bool(data.get('over', False))
    controller.strip_warn_mode = True
    controller.strip_warn_over = over
    if over:
        controller.power = True
        controller.current_effect = 'iris_warn'
        controller.brightness = 255
        controller._wash_engage()
        try:
            controller.run_effect()   # first frame in-request, no wake latency
        except Exception as e:
            print(f"warn_gate on: {e}")
    else:
        # Under threshold: ramp down like the page instead of cutting to black.
        # The fade runs past power=False (run_effect checks it first), and
        # strip_warn_mode still blocks every other effect meanwhile.
        controller.strip_warn_over = False
        controller._wash_release()
        controller.power = False
    controller.wake_effect()
    return jsonify({
        'status': 'ok',
        'over': over,
        'power': controller.power,
        'effect': controller.current_effect,
        'strip_warn_mode': controller.strip_warn_mode,
    })


@app.route('/api/warn_mode', methods=['POST'])
def warn_mode():
    """Enable/disable Strip-Warn exclusive ownership of the strip."""
    data = request.get_json() or {}
    on = bool(data.get('on', False))
    controller.strip_warn_mode = on
    if not on:
        controller.strip_warn_over = False
        controller.power = False
        controller._iris_abort()
    controller.wake_effect()
    return jsonify({
        'status': 'ok',
        'strip_warn_mode': controller.strip_warn_mode,
        'power': controller.power,
    })


def _blocked_by_strip_warn():
    """While Strip-Warn owns the strip, ignore UI/disco effect/color writes."""
    return bool(getattr(controller, 'strip_warn_mode', False))

@app.route('/api/brightness', methods=['POST'])
def set_brightness():
    data = request.get_json() or {}
    brightness = int(data.get('brightness', 100))
    controller.brightness = max(0, min(255, brightness))
    controller.wake_effect()
    return jsonify({'status': 'ok', 'brightness': controller.brightness})

@app.route('/api/speed', methods=['POST'])
def set_speed():
    data = request.get_json() or {}
    speed = int(data.get('speed', 50))
    controller.speed = max(1, min(100, speed))
    return jsonify({'status': 'ok', 'speed': controller.speed})

@app.route('/api/effect', methods=['POST'])
def set_effect():
    data = request.get_json() or {}
    effect = data.get('effect', 'solid')
    valid_effects = ['solid', 'rainbow', 'pulse', 'chase', 'sparkle', 'strobe', 'meteor', 'breathe', 'sinelon', 'juggle', 'theater', 'gradient', 'fire', 'iris_warn']
    
    if effect not in valid_effects:
        return jsonify({'status': 'error', 'message': 'Invalid effect'}), 400

    # Strip-Warn exclusive: only iris_warn arm allowed; other effects would flash through
    if _blocked_by_strip_warn() and effect != 'iris_warn':
        return jsonify({
            'status': 'blocked',
            'reason': 'strip-warn',
            'effect': controller.current_effect,
            'power': controller.power,
        })

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
        elif effect == 'iris_warn':
            # Arm Strip-Warn. over=false → dark + power off until warn_gate
            controller._wash_t0 = None
            controller._wash_fade_t0 = None
            controller._wash_frames()   # precompute now, not on the first edge
            controller.brightness = 255
            controller.strip_warn_mode = True
            over = bool(data.get('over', False))
            controller.strip_warn_over = over
            controller.power = bool(over)
            try:
                controller.run_effect()
            except Exception as e:
                print(f"iris_warn first frame: {e}")
            if not over:
                controller._iris_abort()

        controller.wake_effect()
        return jsonify({'status': 'ok', 'effect': controller.current_effect, 'power': controller.power})

@app.route('/api/color', methods=['POST'])
def set_color():
    if _blocked_by_strip_warn():
        return jsonify({'status': 'blocked', 'reason': 'strip-warn'})
    data = request.get_json() or {}
    r = max(0, min(255, int(data.get('r', 255))))
    g = max(0, min(255, int(data.get('g', 255))))
    b = max(0, min(255, int(data.get('b', 255))))
    controller.color = [r, g, b]
    controller.wake_effect()
    return jsonify({'status': 'ok', 'color': {'r': r, 'g': g, 'b': b}})

@app.route('/api/solid', methods=['POST'])
def set_solid():
    """One-shot disco sync: power + solid effect + RGB + brightness in a single RTT."""
    if _blocked_by_strip_warn():
        return jsonify({'status': 'blocked', 'reason': 'strip-warn', 'power': controller.power})
    data = request.get_json() or {}
    if 'r' in data or 'g' in data or 'b' in data:
        r = max(0, min(255, int(data.get('r', controller.color[0]))))
        g = max(0, min(255, int(data.get('g', controller.color[1]))))
        b = max(0, min(255, int(data.get('b', controller.color[2]))))
        controller.color = [r, g, b]
    if 'brightness' in data:
        controller.brightness = max(0, min(255, int(data.get('brightness'))))
    if 'power' in data:
        controller.power = bool(data.get('power'))
        if not controller.power:
            controller.clear(force=True)
            controller.wake_effect()
            return jsonify({'status': 'ok', 'power': False})
    else:
        controller.power = True
    controller.current_effect = 'solid'
    try:
        controller.effect_solid()
    except Exception as e:
        print(f"solid paint: {e}")
    controller.wake_effect()
    return jsonify({
        'status': 'ok',
        'power': controller.power,
        'effect': 'solid',
        'color': {'r': controller.color[0], 'g': controller.color[1], 'b': controller.color[2]},
        'brightness': controller.brightness,
    })

@app.route('/api/theater_mode', methods=['POST'])
def set_theater_mode():
    data = request.get_json() or {}
    rainbow = data.get('rainbow', True)
    controller.theater_rainbow = bool(rainbow)
    return jsonify({'status': 'ok', 'theater_rainbow': controller.theater_rainbow})

if __name__ == '__main__':
    print("Lichtwerk Web Controller starting...")
    led_count = controller.strip.numPixels() if controller.strip else 50
    print(f"LEDs: {led_count} on GPIO {controller.config['led_config']['pin']} (Demo Mode: {not controller.strip})")
    print("Web interface: http://localhost:5006")
    # threaded=True: disco warn_flash + sync don't serialize behind each other
    app.run(host='0.0.0.0', port=5006, debug=False, threaded=True)