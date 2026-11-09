# laser-trigger (Circuit Bench example)

Example firmware for the Circuit Bench demo project `laser-trigger`: an ESP32-S3-DevKitC-1 switches a laser module
(or an LED) through an NPN transistor while a push button is held. It also has an I2C placeholder and a battery
voltage input. The firmware ships with a deliberate crash for the "Fix with Hermes" exercise.

> **Laser safety.** A laser beam can hurt eyes. Use only a small, labelled low-power laser module, never look into
> the beam and never point it at people, animals, mirrors or windows. Build and test the circuit with an LED first.
> The firmware switches the load only while the button is held, for at most 5 s at a time, and keeps it off during
> boot (R2 pulls the transistor base low until the firmware drives GPIO14). Low voltage only: no mains.

## Wiring

| GPIO | Role | Mode | Circuit |
|---|---|---|---|
| 14 | LASER | out | R1 1 kΩ to the base of Q1 (2N2222A, NPN low side), R2 10 kΩ base to GND; load from +5 V to the collector (J2) |
| 2 | BUTTON | in_pullup | push button SW1 to GND, internal pull-up (pressed = LOW) |
| 8 | SDA | i2c_sda | I2C placeholder for a sensor |
| 9 | SCL | i2c_scl | I2C placeholder for a sensor |
| 1 | VBAT | adc | divider R3 100 kΩ / R4 100 kΩ (ADC1): GPIO1 sees half of VBAT, 4.2 V in gives 2.1 V |

Circuit Bench computes the parts (`bench_calc npn`, `divider`, `led`), draws the schematics and plans the solder order
for this project; the values above come from the demo project.

## Build

```
pio run -e s3
```

`platformio.ini` pins `espressif32@6.9.0` (Arduino framework) and sets `-DARDUINO_USB_CDC_ON_BOOT=1`, so `Serial`
runs on the board's native USB port (USB-Serial/JTAG). That port also resets the board into the bootloader for an
upload. The board profile `esp32-s3-devkitc-1` describes an 8 MB module without PSRAM; the firmware does not use PSRAM
and runs on an N16R8 module as well.

If a board runs firmware with its own USB stack (it then shows up as USB `303a:4001`), the automatic reset does not
work: hold BOOT, tap RESET, release BOOT, then upload. If the boot or panic output does not show up on the native USB
port, use the board's UART port instead.

## Fix with Hermes (exercise)

`src/main.cpp` starts with `#define DEMO_CRASH 1`. `sample_sensor()` then hands a NULL buffer to
`write_sensor_buffer()`, which writes through it. The board prints `[laser-trigger] boot, laser off`, crashes with a
`StoreProhibited` panic and reboots.

1. Flash the firmware and open the serial monitor in the Bench (or run the simulated board `sim://esp32s3-n16r8`).
2. When the panic shows up, choose **Fix with Hermes**: the agent decodes the crash (`write_sensor_buffer` in
   `src/main.cpp`, write through a NULL pointer at offset 12 bytes), explains it and changes the source.
3. The fix gives the sensor frame its memory: set `DEMO_CRASH` to `0`. Build and flash again; the board now prints
   `[laser-trigger] boot ok`, and the button switches the load.

## Simulated board

Without hardware, Circuit Bench runs this project on `sim://esp32s3-n16r8`. The simulated board plays recorded,
synthetic serial logs: a panic loop while `DEMO_CRASH` is `1`, the fixed boot when it is `0`. Every simulated result
is marked `simulated: true`.
