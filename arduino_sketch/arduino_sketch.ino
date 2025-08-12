#include <FastLED.h>

// =====================
// Hardware Configuration
// =====================
#define LED_PIN          5
#define NUM_LEDS         600
#define LED_TYPE         WS2812B
#define COLOR_ORDER      GRB
#define BRIGHTNESS       120
#define MAX_POWER_MW     18000  // 18W max power

// =====================
// Global Variables
// =====================
CRGB leds[NUM_LEDS];

// LED Control State
bool ledState = false;
uint8_t ledBrightness = BRIGHTNESS;
CRGB currentColor = CRGB(255, 255, 255);

// Effect System
uint8_t currentEffect = 0;
uint8_t effectSpeed = 50;    // 0-100
uint8_t effectIntensity = 255; // 0-255
uint32_t lastEffectUpdate = 0;

// Effect state variables
uint8_t effectHue = 0;
uint8_t effectCounter = 0;
int meteorPos = 0;
uint8_t sparkleCounter = 0;
bool fadeDirection = true;
uint8_t fadeValue = 0;

// =====================
// Effect List
// =====================
// 0 = Static Color
// 1 = Rainbow Cycle
// 2 = Fire Simulation
// 3 = Meteor/Comet
// 4 = Sparkle/Glitter
// 5 = Breathing/Fade
// 6 = Color Wipe
// 7 = Theater Chase
// 8 = Twinkle
// 9 = Color Flow

// =====================
// Setup
// =====================
void setup() {
  Serial.begin(115200);
  
  // Wait for serial on supported boards
  #if defined(USBCON) || defined(ARDUINO_ARCH_SAMD) || defined(ARDUINO_ARCH_ESP32)
    while (!Serial) delay(10);
  #endif
  
  Serial.setTimeout(15); // Prevent blocking
  
  Serial.println("🎨 Lichtwerk Controller v2.0 - Clean & Modern");
  Serial.println("✨ 600 WS2812B LEDs | 10 Effects | Color Picker Ready");
  
  // Initialize FastLED
  FastLED.addLeds<LED_TYPE, LED_PIN, COLOR_ORDER>(leds, NUM_LEDS);
  FastLED.setBrightness(ledBrightness);
  FastLED.setMaxPowerInVoltsAndMilliamps(5, MAX_POWER_MW);
  FastLED.setCorrection(TypicalLEDStrip);
  FastLED.setTemperature(DirectSunlight);
  
  // Initialize all LEDs to black
  FastLED.clear();
  FastLED.show();
  
  Serial.println("✅ FastLED initialized");
  Serial.println("✅ Ready for commands");
  
  // Send initial status
  sendStatus();
}

// =====================
// Main Loop
// =====================
void loop() {
  uint32_t now = millis();
  
  // Handle serial commands
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    if (command.length() > 0) {
      processCommand(command);
    }
  }
  
  // Update effects
  if (ledState) {
    uint32_t effectDelay = map(100 - effectSpeed, 0, 100, 10, 200);
    
    if (now - lastEffectUpdate >= effectDelay) {
      runCurrentEffect();
      lastEffectUpdate = now;
    }
    
    FastLED.show();
  }
  
  delay(1); // Small delay for stability
}

// =====================
// Command Processing
// =====================
void processCommand(String cmd) {
  Serial.println("CMD: " + cmd);
  
  if (cmd == "ON") {
    ledState = true;
    Serial.println("✅ LEDs ON");
  }
  else if (cmd == "OFF") {
    ledState = false;
    FastLED.clear();
    FastLED.show();
    Serial.println("✅ LEDs OFF");
  }
  else if (cmd.startsWith("BRIGHTNESS:")) {
    int brightness = cmd.substring(11).toInt();
    ledBrightness = constrain(brightness, 0, 255);
    FastLED.setBrightness(ledBrightness);
    Serial.println("✅ Brightness: " + String(ledBrightness));
  }
  else if (cmd.startsWith("COLOR:")) {
    // Format: COLOR:255,128,64
    int r, g, b;
    if (sscanf(cmd.c_str(), "COLOR:%d,%d,%d", &r, &g, &b) == 3) {
      currentColor = CRGB(constrain(r, 0, 255), constrain(g, 0, 255), constrain(b, 0, 255));
      Serial.println("✅ Color: " + String(r) + "," + String(g) + "," + String(b));
    } else {
      Serial.println("❌ Invalid color format");
    }
  }
  else if (cmd.startsWith("EFFECT:")) {
    int effect = cmd.substring(7).toInt();
    currentEffect = constrain(effect, 0, 9);
    resetEffectVariables();
    Serial.println("✅ Effect: " + String(currentEffect) + " (" + getEffectName(currentEffect) + ")");
  }
  else if (cmd.startsWith("SPEED:")) {
    int speed = cmd.substring(6).toInt();
    effectSpeed = constrain(speed, 0, 100);
    Serial.println("✅ Speed: " + String(effectSpeed));
  }
  else if (cmd.startsWith("INTENSITY:")) {
    int intensity = cmd.substring(10).toInt();
    effectIntensity = constrain(intensity, 0, 255);
    Serial.println("✅ Intensity: " + String(effectIntensity));
  }
  else if (cmd == "STATUS") {
    // Force status update
  }
  else {
    Serial.println("❓ Unknown command: " + cmd);
  }
  
  sendStatus();
}

// =====================
// Effect Management
// =====================
void resetEffectVariables() {
  effectHue = 0;
  effectCounter = 0;
  meteorPos = 0;
  sparkleCounter = 0;
  fadeDirection = true;
  fadeValue = 0;
}

String getEffectName(uint8_t effect) {
  switch (effect) {
    case 0: return "Static Color";
    case 1: return "Rainbow Cycle";
    case 2: return "Fire Simulation";
    case 3: return "Meteor/Comet";
    case 4: return "Sparkle/Glitter";
    case 5: return "Breathing/Fade";
    case 6: return "Color Wipe";
    case 7: return "Theater Chase";
    case 8: return "Twinkle";
    case 9: return "Color Flow";
    default: return "Unknown";
  }
}

// =====================
// Effect Runner
// =====================
void runCurrentEffect() {
  switch (currentEffect) {
    case 0: effectStaticColor(); break;
    case 1: effectRainbow(); break;
    case 2: effectFire(); break;
    case 3: effectMeteor(); break;
    case 4: effectSparkle(); break;
    case 5: effectBreathing(); break;
    case 6: effectColorWipe(); break;
    case 7: effectTheaterChase(); break;
    case 8: effectTwinkle(); break;
    case 9: effectColorFlow(); break;
  }
}

// =====================
// Effect Implementations
// =====================

// Effect 0: Static Color
void effectStaticColor() {
  fill_solid(leds, NUM_LEDS, currentColor);
}

// Effect 1: Rainbow Cycle
void effectRainbow() {
  effectHue += map(effectSpeed, 0, 100, 1, 8);
  for (int i = 0; i < NUM_LEDS; i++) {
    leds[i] = CHSV(effectHue + (i * 256 / NUM_LEDS), 255, effectIntensity);
  }
}

// Effect 2: Fire Simulation
void effectFire() {
  static uint8_t heat[NUM_LEDS];
  
  // Cool down every cell
  for (int i = 0; i < NUM_LEDS; i++) {
    heat[i] = qsub8(heat[i], random8(0, ((55 * 10) / NUM_LEDS) + 2));
  }
  
  // Heat from bottom
  for (int k = NUM_LEDS - 1; k >= 2; k--) {
    heat[k] = (heat[k - 1] + heat[k - 2] + heat[k - 2]) / 3;
  }
  
  // Add sparks
  if (random8() < map(effectSpeed, 0, 100, 40, 120)) {
    int y = random8(min(NUM_LEDS/4, 15));
    heat[y] = qadd8(heat[y], random8(160, 255));
  }
  
  // Convert heat to colors
  for (int j = 0; j < NUM_LEDS; j++) {
    CRGB color = HeatColor(heat[j]);
    color.nscale8_video(effectIntensity);
    leds[j] = color;
  }
}

// Effect 3: Meteor/Comet
void effectMeteor() {
  // Fade all LEDs
  for (int i = 0; i < NUM_LEDS; i++) {
    leds[i].fadeToBlackBy(60);
  }
  
  // Draw meteor
  int meteorSize = 8;
  for (int i = 0; i < meteorSize; i++) {
    int pos = (meteorPos - i + NUM_LEDS) % NUM_LEDS;
    uint8_t brightness = 255 - (i * 32);
    CRGB color = currentColor;
    color.nscale8_video(brightness);
    color.nscale8_video(effectIntensity);
    leds[pos] = color;
  }
  
  meteorPos = (meteorPos + map(effectSpeed, 0, 100, 1, 4)) % NUM_LEDS;
}

// Effect 4: Sparkle/Glitter
void effectSparkle() {
  // Fade existing pixels
  fadeToBlackBy(leds, NUM_LEDS, map(effectSpeed, 0, 100, 20, 60));
  
  // Add sparkles
  int sparkleCount = map(effectSpeed, 0, 100, 2, 8);
  for (int i = 0; i < sparkleCount; i++) {
    int pos = random16(NUM_LEDS);
    CRGB color = currentColor;
    color.nscale8_video(effectIntensity);
    leds[pos] = color;
  }
}

// Effect 5: Breathing/Fade
void effectBreathing() {
  if (fadeDirection) {
    fadeValue += map(effectSpeed, 0, 100, 2, 10);
    if (fadeValue >= 255) {
      fadeValue = 255;
      fadeDirection = false;
    }
  } else {
    fadeValue -= map(effectSpeed, 0, 100, 2, 10);
    if (fadeValue <= 0) {
      fadeValue = 0;
      fadeDirection = true;
    }
  }
  
  CRGB color = currentColor;
  color.nscale8_video(fadeValue);
  color.nscale8_video(effectIntensity);
  fill_solid(leds, NUM_LEDS, color);
}

// Effect 6: Color Wipe
void effectColorWipe() {
  static bool wipeDirection = true;
  
  if (wipeDirection) {
    leds[effectCounter] = currentColor;
    leds[effectCounter].nscale8_video(effectIntensity);
    effectCounter++;
    if (effectCounter >= NUM_LEDS) {
      effectCounter = NUM_LEDS - 1;
      wipeDirection = false;
    }
  } else {
    leds[effectCounter] = CRGB::Black;
    effectCounter--;
    if (effectCounter < 0) {
      effectCounter = 0;
      wipeDirection = true;
    }
  }
}

// Effect 7: Theater Chase
void effectTheaterChase() {
  static uint8_t chasePos = 0;
  
  // Clear all
  fill_solid(leds, NUM_LEDS, CRGB::Black);
  
  // Set every 3rd LED
  for (int i = chasePos; i < NUM_LEDS; i += 3) {
    CRGB color = currentColor;
    color.nscale8_video(effectIntensity);
    leds[i] = color;
  }
  
  chasePos = (chasePos + 1) % 3;
}

// Effect 8: Twinkle
void effectTwinkle() {
  // Fade all pixels
  for (int i = 0; i < NUM_LEDS; i++) {
    leds[i].fadeToBlackBy(map(effectSpeed, 0, 100, 5, 20));
  }
  
  // Add random twinkles
  if (random8() < map(effectSpeed, 0, 100, 30, 80)) {
    int pos = random16(NUM_LEDS);
    leds[pos] = currentColor;
    leds[pos].nscale8_video(effectIntensity);
  }
}

// Effect 9: Color Flow
void effectColorFlow() {
  static uint8_t flowHue = 0;
  
  // Shift all pixels
  for (int i = NUM_LEDS - 1; i > 0; i--) {
    leds[i] = leds[i - 1];
  }
  
  // Set first pixel to new color
  leds[0] = CHSV(flowHue, 255, effectIntensity);
  flowHue += map(effectSpeed, 0, 100, 1, 8);
}

// =====================
// Status Output
// =====================
void sendStatus() {
  Serial.print("STATUS:");
  Serial.print(ledState ? "ON" : "OFF"); Serial.print(",");
  Serial.print(ledBrightness); Serial.print(",");
  Serial.print(currentColor.r); Serial.print(",");
  Serial.print(currentColor.g); Serial.print(",");
  Serial.print(currentColor.b); Serial.print(",");
  Serial.print(currentEffect); Serial.print(",");
  Serial.print(effectSpeed); Serial.print(",");
  Serial.println(effectIntensity);
}