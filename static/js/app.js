class LichtwerkController {
    constructor() {
        this.apiBase = '';
        this.updateInterval = null;
        this.isUpdating = false;
        
        this.initializeElements();
        this.attachEventListeners();
        this.startStatusUpdates();
        this.loadStatus();
    }
    
    initializeElements() {
        // Power control
        this.powerToggle = document.getElementById('power-toggle');
        
        // Color controls
        this.colorDisplay = document.getElementById('color-display');
        this.redSlider = document.getElementById('red-slider');
        this.greenSlider = document.getElementById('green-slider');
        this.blueSlider = document.getElementById('blue-slider');
        this.redValue = document.getElementById('red-value');
        this.greenValue = document.getElementById('green-value');
        this.blueValue = document.getElementById('blue-value');
        
        // Effect controls
        this.effectButtons = document.querySelectorAll('.effect-btn');
        
        // Slider controls
        this.brightnessSlider = document.getElementById('brightness-slider');
        this.speedSlider = document.getElementById('speed-slider');
        this.brightnessValue = document.getElementById('brightness-value');
        this.speedValue = document.getElementById('speed-value');
        
        // Status elements
        this.statusText = document.getElementById('status-text');
        this.statusDot = document.getElementById('status-dot');
        this.ledCount = document.getElementById('led-count');
        this.gpioPin = document.getElementById('gpio-pin');
        this.currentEffect = document.getElementById('current-effect');
        
        // Color presets
        this.colorPresets = document.querySelectorAll('.color-preset');
    }
    
    attachEventListeners() {
        // Power toggle
        this.powerToggle.addEventListener('change', () => {
            this.setPower(this.powerToggle.checked);
        });
        
        // Color sliders
        [this.redSlider, this.greenSlider, this.blueSlider].forEach((slider, index) => {
            slider.addEventListener('input', (e) => {
                const value = parseInt(e.target.value);
                const valueInput = [this.redValue, this.greenValue, this.blueValue][index];
                valueInput.value = value;
                this.updateColor();
            });
        });
        
        // Color number inputs
        [this.redValue, this.greenValue, this.blueValue].forEach((input, index) => {
            input.addEventListener('input', (e) => {
                let value = parseInt(e.target.value) || 0;
                value = Math.max(0, Math.min(255, value));
                e.target.value = value;
                const slider = [this.redSlider, this.greenSlider, this.blueSlider][index];
                slider.value = value;
                this.updateColor();
            });
        });
        
        // Effect buttons
        this.effectButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                const effect = btn.dataset.effect;
                this.setEffect(effect);
            });
        });
        
        // Brightness slider
        this.brightnessSlider.addEventListener('input', (e) => {
            const value = parseInt(e.target.value);
            this.brightnessValue.textContent = value;
            this.setBrightness(value);
        });
        
        // Speed slider
        this.speedSlider.addEventListener('input', (e) => {
            const value = parseInt(e.target.value);
            this.speedValue.textContent = value;
            this.setSpeed(value);
        });
        
        // Color presets
        this.colorPresets.forEach(preset => {
            preset.addEventListener('click', () => {
                const [r, g, b] = preset.dataset.color.split(',').map(Number);
                this.setColorValues(r, g, b);
            });
        });
    }
    
    updateColor() {
        const r = parseInt(this.redSlider.value);
        const g = parseInt(this.greenSlider.value);
        const b = parseInt(this.blueSlider.value);
        
        this.colorDisplay.style.backgroundColor = `rgb(${r}, ${g}, ${b})`;
        
        // Debounce API call
        clearTimeout(this.colorTimeout);
        this.colorTimeout = setTimeout(() => {
            this.setColor(r, g, b);
        }, 100);
    }
    
    setColorValues(r, g, b) {
        this.redSlider.value = r;
        this.greenSlider.value = g;
        this.blueSlider.value = b;
        this.redValue.value = r;
        this.greenValue.value = g;
        this.blueValue.value = b;
        this.updateColor();
    }
    
    async apiCall(endpoint, method = 'GET', data = null) {
        try {
            const options = {
                method,
                headers: {
                    'Content-Type': 'application/json'
                }
            };
            
            if (data && method !== 'GET') {
                options.body = JSON.stringify(data);
            }
            
            const response = await fetch(`${this.apiBase}/api/${endpoint}`, options);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            return await response.json();
        } catch (error) {
            console.error(`API call failed: ${endpoint}`, error);
            this.setConnectionStatus(false);
            throw error;
        }
    }
    
    async loadStatus() {
        try {
            const status = await this.apiCall('status');
            this.updateUI(status);
            this.setConnectionStatus(true);
        } catch (error) {
            console.error('Failed to load status:', error);
            this.setConnectionStatus(false);
        }
    }
    
    updateUI(status) {
        // Power
        this.powerToggle.checked = status.power;
        
        // Color
        this.setColorValues(status.color.r, status.color.g, status.color.b);
        
        // Brightness
        this.brightnessSlider.value = status.brightness;
        this.brightnessValue.textContent = status.brightness;
        
        // Speed
        this.speedSlider.value = status.speed;
        this.speedValue.textContent = status.speed;
        
        // Effect
        this.effectButtons.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.effect === status.effect);
        });
        
        // System info
        this.ledCount.textContent = status.led_count;
        this.gpioPin.textContent = status.pin;
        this.currentEffect.textContent = status.effect.charAt(0).toUpperCase() + status.effect.slice(1);
    }
    
    setConnectionStatus(connected) {
        if (connected) {
            this.statusText.textContent = 'Connected';
            this.statusDot.classList.add('connected');
        } else {
            this.statusText.textContent = 'Disconnected';
            this.statusDot.classList.remove('connected');
        }
    }
    
    async setPower(power) {
        try {
            await this.apiCall('power', 'POST', { power });
        } catch (error) {
            console.error('Failed to set power:', error);
            this.powerToggle.checked = !power; // Revert on error
        }
    }
    
    async setColor(r, g, b) {
        try {
            await this.apiCall('color', 'POST', { r, g, b });
        } catch (error) {
            console.error('Failed to set color:', error);
        }
    }
    
    async setBrightness(brightness) {
        try {
            await this.apiCall('brightness', 'POST', { brightness });
        } catch (error) {
            console.error('Failed to set brightness:', error);
        }
    }
    
    async setSpeed(speed) {
        try {
            await this.apiCall('speed', 'POST', { speed });
        } catch (error) {
            console.error('Failed to set speed:', error);
        }
    }
    
    async setEffect(effect) {
        try {
            await this.apiCall('effect', 'POST', { effect });
            
            // Update UI immediately for better UX
            this.effectButtons.forEach(btn => {
                btn.classList.toggle('active', btn.dataset.effect === effect);
            });
            this.currentEffect.textContent = effect.charAt(0).toUpperCase() + effect.slice(1);
        } catch (error) {
            console.error('Failed to set effect:', error);
        }
    }
    
    startStatusUpdates() {
        // Update status every 2 seconds
        this.updateInterval = setInterval(() => {
            if (!this.isUpdating) {
                this.isUpdating = true;
                this.loadStatus().finally(() => {
                    this.isUpdating = false;
                });
            }
        }, 2000);
    }
    
    destroy() {
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
        }
    }
}

// Initialize the controller when the page loads
document.addEventListener('DOMContentLoaded', () => {
    window.lichtwerkController = new LichtwerkController();
});

// Clean up on page unload
window.addEventListener('beforeunload', () => {
    if (window.lichtwerkController) {
        window.lichtwerkController.destroy();
    }
});