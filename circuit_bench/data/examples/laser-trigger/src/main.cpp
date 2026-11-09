// laser-trigger: example firmware of the Circuit Bench demo project (ESP32-S3-DevKitC-1, Arduino framework).
//
// LASER SAFETY: a laser beam can hurt eyes. Use only a small, labelled low-power laser module, never look into
// the beam and never point it at people, animals, mirrors or windows. Try the circuit with an LED first.
// The firmware switches the load only while the button is held, for at most LASER_MAX_ON_MS at a time, and keeps
// it off during boot (R2 pulls the transistor base low until the firmware drives GPIO14).
//
// Wiring (bench project laser-trigger):
//   GPIO14  -> R1 1 kOhm -> base of Q1 (2N2222A, NPN low side); R2 10 kOhm from the base to GND.
//              Load (laser module, or an LED with its series resistor) from +5 V to the collector of Q1 (J2).
//   GPIO2   <- push button SW1 to GND; internal pull-up, pressed reads LOW.
//   GPIO8/9    I2C SDA/SCL, placeholder for a sensor (not used yet).
//   GPIO1   <- VBAT through the divider R3 100 kOhm / R4 100 kOhm (ADC1): GPIO1 sees half of VBAT.
//
// DEMO_CRASH 1: the sensor frame never gets its memory, so write_sensor_buffer() writes through a NULL pointer
// (StoreProhibited). This is the "Fix with Hermes" exercise of the README. DEMO_CRASH 0 is the fixed firmware.
#define DEMO_CRASH 1

#include <Arduino.h>
#include <Wire.h>

static const uint8_t LASER_PIN = 14;
static const uint8_t BUTTON_PIN = 2;
static const uint8_t SDA_PIN = 8;
static const uint8_t SCL_PIN = 9;
static const uint8_t VBAT_PIN = 1;
static const uint32_t LASER_MAX_ON_MS = 5000;
static const uint32_t REPORT_EVERY_MS = 5000;

// Sensor frame (placeholder for the I2C sensor): bytes 0..11 sensor data, byte 12 VBAT in 20 mV steps.
static const size_t FRAME_SIZE = 16;
static const size_t FRAME_VBAT = 12;
static uint8_t frame_storage[FRAME_SIZE];
static uint8_t *sensor_frame = nullptr;  // points to frame_storage once the sensor is set up

static bool laser_on = false;
static bool wait_for_release = false;
static uint32_t laser_since_ms = 0;
static uint32_t last_report_ms = 0;
static uint32_t vbat_mv = 0;

// noipa: the compiler keeps this function and its call as written, so a crash points to this line.
__attribute__((noipa)) void write_sensor_buffer(uint8_t *buf, uint32_t millivolts) {
  buf[FRAME_VBAT] = (uint8_t)(millivolts / 20);  // buf == NULL: StoreProhibited, EXCVADDR 0x0000000c
}

__attribute__((noinline)) void sample_sensor() {
  vbat_mv = 2 * analogReadMilliVolts(VBAT_PIN);  // R3 = R4: the ADC sees half of VBAT
  write_sensor_buffer(sensor_frame, vbat_mv);
}

static void begin_sensor() {
  Wire.begin(SDA_PIN, SCL_PIN);
#if !DEMO_CRASH
  sensor_frame = frame_storage;  // the fix: the sensor frame gets its memory before the first sample
#endif
}

static void set_laser(bool on, const char *why) {
  digitalWrite(LASER_PIN, on ? HIGH : LOW);
  laser_on = on;
  laser_since_ms = millis();
  Serial.printf("[laser-trigger] %s: laser %s\n", why, on ? "on" : "off");
}

void setup() {
  digitalWrite(LASER_PIN, LOW);  // laser off before the pin becomes an output
  pinMode(LASER_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  Serial.begin(115200);
  delay(500);  // give the USB serial port time to come up
  Serial.println("[laser-trigger] boot, laser off");
  begin_sensor();
  sample_sensor();
  Serial.printf("[laser-trigger] vbat %.2f V\n", vbat_mv / 1000.0);
  Serial.println("[laser-trigger] boot ok");
}

void loop() {
  const bool pressed = digitalRead(BUTTON_PIN) == LOW;
  const uint32_t now = millis();
  if (!pressed) {
    wait_for_release = false;
    if (laser_on) {
      set_laser(false, "button released");
    }
  } else if (!laser_on && !wait_for_release) {
    set_laser(true, "button pressed");
  } else if (laser_on && now - laser_since_ms >= LASER_MAX_ON_MS) {
    set_laser(false, "on-time limit, release the button");
    wait_for_release = true;
  }
  if (now - last_report_ms >= REPORT_EVERY_MS) {
    last_report_ms = now;
    sample_sensor();
    Serial.printf("[laser-trigger] vbat %.2f V, laser %s\n", vbat_mv / 1000.0, laser_on ? "on" : "off");
  }
  delay(10);
}
