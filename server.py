#!/usr/bin/env python3
"""
Lichtwerk LED Controller v2.0 - Modern & Clean
Flask server with HTML5 color picker and FastLED effects
"""

import os
import time
import serial
import threading
from queue import Queue, Empty
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS

# Configuration
ARDUINO_PORT = os.environ.get('ARDUINO_PORT', '/dev/ttyACM0')
ARDUINO_BAUDRATE = 115200
SERVER_PORT = int(os.environ.get('PORT', 5006))

# Flask App
app = Flask(__name__, static_folder='public', static_url_path='')
CORS(app)

class LichtverkController:
    def __init__(self):
        self.serial_conn = None
        self.connected = False
        self.status = {
            "state": "OFF", 
            "brightness": 120, 
            "r": 255, "g": 255, "b": 255,
            "effect": 0,
            "speed": 50,
            "intensity": 255
        }
        self.command_queue = Queue()
        self.running = True
        
        # Start background threads
        threading.Thread(target=self.connect_arduino, daemon=True).start()
        threading.Thread(target=self.command_worker, daemon=True).start()
        
    def connect_arduino(self):
        """Connect to Arduino and handle reconnection"""
        while self.running:
            try:
                if not self.connected:
                    print(f"🔌 Connecting to Arduino on {ARDUINO_PORT}...")
                    self.serial_conn = serial.Serial(ARDUINO_PORT, ARDUINO_BAUDRATE, timeout=2)
                    time.sleep(3)  # Arduino boot time
                    self.connected = True
                    print("✅ Arduino connected!")
                
                # Read Arduino output
                if self.serial_conn.in_waiting > 0:
                    line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        print(f"Arduino: {line}")
                        if line.startswith("STATUS:"):
                            self.parse_status(line)
                            
            except Exception as e:
                if self.connected:
                    print(f"❌ Arduino connection lost: {e}")
                self.connected = False
                if self.serial_conn:
                    try:
                        self.serial_conn.close()
                    except:
                        pass
                time.sleep(2)
                
    def parse_status(self, status_line):
        """Parse Arduino status: STATUS:ON,120,255,255,255,0,50,255"""
        try:
            parts = status_line.replace("STATUS:", "").split(",")
            if len(parts) >= 8:
                self.status = {
                    "state": parts[0],
                    "brightness": int(parts[1]),
                    "r": int(parts[2]),
                    "g": int(parts[3]),
                    "b": int(parts[4]),
                    "effect": int(parts[5]),
                    "speed": int(parts[6]),
                    "intensity": int(parts[7])
                }
        except Exception as e:
            print(f"❌ Status parse error: {e}")
            
    def command_worker(self):
        """Process command queue"""
        while self.running:
            try:
                command = self.command_queue.get(timeout=1)
                if self.connected and self.serial_conn:
                    print(f"📤 Sending: {command}")
                    self.serial_conn.write(f"{command}\n".encode())
                    self.serial_conn.flush()
                self.command_queue.task_done()
            except Empty:
                continue
            except Exception as e:
                print(f"❌ Command send error: {e}")
                
    def send_command(self, command):
        """Add command to queue"""
        try:
            self.command_queue.put(command, timeout=1)
            return True
        except:
            return False
            
    def get_status(self):
        """Get current status"""
        return {
            "connected": self.connected,
            "arduino_port": ARDUINO_PORT,
            **self.status
        }

# Global controller
controller = LichtverkController()

# Effect names for frontend
EFFECT_NAMES = [
    "Static Color",
    "Rainbow Cycle", 
    "Fire Simulation",
    "Meteor/Comet",
    "Sparkle/Glitter",
    "Breathing/Fade",
    "Color Wipe",
    "Theater Chase",
    "Twinkle",
    "Color Flow"
]

# =====================
# Routes
# =====================
@app.route('/')
def index():
    return render_template('index.html', effect_names=EFFECT_NAMES)

@app.route('/api/status')
def api_status():
    return jsonify(controller.get_status())

@app.route('/api/power', methods=['POST'])
def api_power():
    data = request.get_json()
    if 'on' in data:
        command = "ON" if data['on'] else "OFF"
        success = controller.send_command(command)
        return jsonify({"success": success})
    return jsonify({"success": False, "error": "Missing 'on' parameter"})

@app.route('/api/brightness', methods=['POST'])
def api_brightness():
    data = request.get_json()
    if 'brightness' in data:
        brightness = max(0, min(255, int(data['brightness'])))
        success = controller.send_command(f"BRIGHTNESS:{brightness}")
        return jsonify({"success": success})
    return jsonify({"success": False, "error": "Missing 'brightness' parameter"})

@app.route('/api/color', methods=['POST'])
def api_color():
    data = request.get_json()
    if all(key in data for key in ['r', 'g', 'b']):
        r = max(0, min(255, int(data['r'])))
        g = max(0, min(255, int(data['g'])))
        b = max(0, min(255, int(data['b'])))
        success = controller.send_command(f"COLOR:{r},{g},{b}")
        return jsonify({"success": success})
    return jsonify({"success": False, "error": "Missing r,g,b parameters"})

@app.route('/api/effect', methods=['POST'])
def api_effect():
    data = request.get_json()
    if 'effect' in data:
        effect = max(0, min(9, int(data['effect'])))
        success = controller.send_command(f"EFFECT:{effect}")
        return jsonify({"success": success})
    return jsonify({"success": False, "error": "Missing 'effect' parameter"})

@app.route('/api/speed', methods=['POST'])
def api_speed():
    data = request.get_json()
    if 'speed' in data:
        speed = max(0, min(100, int(data['speed'])))
        success = controller.send_command(f"SPEED:{speed}")
        return jsonify({"success": success})
    return jsonify({"success": False, "error": "Missing 'speed' parameter"})

@app.route('/api/intensity', methods=['POST'])
def api_intensity():
    data = request.get_json()
    if 'intensity' in data:
        intensity = max(0, min(255, int(data['intensity'])))
        success = controller.send_command(f"INTENSITY:{intensity}")
        return jsonify({"success": success})
    return jsonify({"success": False, "error": "Missing 'intensity' parameter"})

@app.route('/health')
def health():
    return jsonify({"status": "ok", "connected": controller.connected})

if __name__ == '__main__':
    print("🎨 Lichtwerk Controller v2.0 - Modern & Clean")
    print(f"🌐 Server: http://0.0.0.0:{SERVER_PORT}")
    print(f"🔌 Arduino: {ARDUINO_PORT}")
    print(f"✨ Features: 600 LEDs | 10 Effects | Color Picker")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=SERVER_PORT, debug=False)