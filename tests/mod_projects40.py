"""40 synthetic hobby projects for the module check engine (regression test test_mod_regress40, 08.11.2026).

Each project: id, title, ok (wired correctly?), chip, assignments, parts, options,
expect  = [(warning_code, {allowed severities})]  -> must come as a failed finding with one of these severities,
forbid  = [warning_code | (warning_code, {severities})] -> must NOT come (in these severities, default caution/danger),
allow   = [warning_code]  -> may come (hints, safety notes), does not count as a false alarm,
note    = what an electronics engineer expects, in words.
With ok=True every other caution/danger finding outside expect/allow counts as a false alarm.

Nets 3V3/5V/GND are fixed; further rails via options.rails. ESP32-S3, pins without strapping/USB/flash.
Titles and notes are free text; the tests read only the other fields.
"""
from __future__ import annotations

CHIP = "esp32s3"
HARD = {"caution", "danger"}
ANY = {"info", "caution", "danger"}


# --- building blocks -----------------------------------------------------------------------------------------------
def R(ref, a, b, value="4k7"):
    return {"ref": ref, "kind": "resistor", "value": value, "conn": {"1": a, "2": b}}


def C(ref, a, b="GND", value="100nF", kind="capacitor"):
    return {"ref": ref, "kind": kind, "value": value, "conn": {"1": a, "2": b}}


def D(ref, anode, cathode, value="1N4007"):
    return {"ref": ref, "kind": "diode", "value": value, "conn": {"A": anode, "K": cathode}}


def M(ref, module, conn, variant=None, **kw):
    p = {"ref": ref, "kind": "module", "value": module, "module": module, "conn": conn}
    if variant:
        p["variant"] = variant
    p.update(kw)
    return p


def i2c(sda=8, scl=9, sda_net="SDA", scl_net="SCL"):
    return [{"role": "SDA", "mode": "i2c_sda", "pin": sda, "net": sda_net},
            {"role": "SCL", "mode": "i2c_scl", "pin": scl, "net": scl_net}]


def i2c_pullups(rail="3V3", sda="SDA", scl="SCL", value="4k7", p="R"):
    return [R(p + "SDA", sda, rail, value), R(p + "SCL", scl, rail, value)]


def a(mode, pin, net, role=None):
    return {"role": role or net, "mode": mode, "pin": pin, "net": net}


def spi(sck=12, mosi=11, miso=13):
    return [a("spi_sck", sck, "SCK"), a("spi_mosi", mosi, "MOSI"), a("spi_miso", miso, "MISO")]


BME = lambda ref="U1", sdo="GND", sda="SDA", scl="SCL", vdd="3V3": M(ref, "bme280", {  # noqa: E731
    "VDD": vdd, "GND": "GND", "SDI": sda, "SCK": scl, "SDO": sdo})
OLED = lambda ref="U2", sa0="GND", rst="OLED_RST": M(ref, "ssd1306", {  # noqa: E731
    "VDD": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL", "SA0": sa0, "RES": rst})

PROJECTS: list[dict] = []


def P(**kw):
    kw.setdefault("chip", CHIP)
    kw.setdefault("options", {})
    kw.setdefault("expect", [])
    kw.setdefault("forbid", [])
    kw.setdefault("allow", [])
    PROJECTS.append(kw)


# ===================================================================================================================
# 01 weather station BME280 + SSD1306 (correct)
P(id="p01_weather_ok", ok=True, title="Weather station BME280 + SSD1306 on S3, 3V3, pull-ups 4k7 to 3V3",
  assignments=i2c() + [a("out", 21, "OLED_RST")],
  parts=[BME(), OLED(), *i2c_pullups(), C("C1", "3V3")],
  forbid=["mod_address_conflict", "mod_level_out", "mod_level_in", "mod_supply_range", "mod_required_parts"],
  note="Everything within the datasheet range: 0x76 + 0x3C, pull-ups to 3V3, decoupling present. Expected: no warning.")

# 02 clock DS3231 + OLED + button (correct)
P(id="p02_clock_ok", ok=True, title="Clock DS3231 (chip) + SSD1306 + button, coin cell on VBAT",
  assignments=i2c() + [a("out", 21, "OLED_RST"), a("in_pullup", 5, "BTN"), a("in_pullup", 6, "RTC_INT")],
  parts=[M("U1", "ds3231", {"VCC": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL", "VBAT": "VBAT",
                             "INT/SQW": "RTC_INT"}),
         OLED(), *i2c_pullups(), C("C1", "3V3"),
         {"ref": "SW1", "kind": "button", "value": "push button", "conn": {"1": "BTN", "2": "GND"}},
         {"ref": "BT1", "kind": "battery", "value": "CR2032", "conn": {"+": "VBAT", "-": "GND"}}],
  options={"rails": {"VBAT": 3.0}},
  forbid=["mod_address_conflict", "mod_level_out", "mod_level_in", "mod_supply_range", "mod_unconnected"],
  note="DS3231 0x68 + OLED 0x3C, INT/SQW open drain with the internal pull-up of the ESP. Expected: nothing.")

# 03 clock with ZS-042 on 5 V (fault: board pull-ups to 5 V on the ESP bus)
P(id="p03_clock_zs042_5v", ok=False, title="ZS-042 (DS3231) on 5 V, SDA/SCL directly on the ESP, no own pull-ups",
  assignments=i2c(),
  parts=[M("U1", "ds3231", {"VCC": "5V", "GND": "GND", "SDA": "SDA", "SCL": "SCL"}, variant="zs042"),
         C("C1", "5V")],
  expect=[("mod_level_out", {"caution", "danger"})],
  allow=["mod_rtc_rtc_module_charger", "mod_required_parts"],
  forbid=["mod_supply_range"],
  note="The ZS-042 carries 4k7 to VCC: on 5 V the ESP bus sits at 5 V -> at least caution 'confirm the pull-up "
       "voltage' (breakout without facts), charging note for the CR2032. The DS3231 itself on 5 V is allowed.")

# 04 robot A4988 + MPU-6050 (correct)
P(id="p04_robot_ok", ok=True, title="Robot: A4988 Stepstick (VDD 3V3, VMOT 12 V, 100 µF) + MPU-6050",
  assignments=i2c() + [a("out", 4, "STEP"), a("out", 5, "DIR"), a("out", 6, "EN"), a("in", 7, "IMU_INT")],
  parts=[M("U1", "a4988", {"VDD": "3V3", "GND": "GND", "VBB1": "VMOT", "STEP": "STEP", "DIR": "DIR",
                            "ENABLE": "EN", "SLEEP": "SLP_RST", "RESET": "SLP_RST", "MS1": "GND", "MS2": "GND",
                            "MS3": "GND", "OUT1A": "M1A", "OUT1B": "M1B", "OUT2A": "M2A", "OUT2B": "M2B"},
           variant="carrier"),
         R("R_SLP", "SLP_RST", "3V3", "10k"),
         M("U2", "mpu6050", {"VDD": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL", "AD0": "GND",
                             "INT": "IMU_INT"}),
         *i2c_pullups(), C("C1", "3V3"), C("C2", "VMOT", value="100uF", kind="electrolytic")],
  options={"rails": {"VMOT": 12.0}},
  allow=["mod_hazard"],
  forbid=["mod_unconnected", "mod_motor_a4988_vdd_3v3", "mod_supply_range", "mod_motor_motor_supply",
          "mod_level_in"],
  note="Stepstick as from Pololu: SLEEP+RESET bridged with a pull-up, MSx to GND, ROSC/REF/CPx/VREG are wired on the "
       "carrier and not on the header. Expected: only motor notes (hazard), no 'ROSC open'.")

# 05 A4988 with RESET open (fault)
P(id="p05_a4988_reset_open", ok=False, title="A4988 Stepstick: RESET open (not bridged to SLEEP)",
  assignments=[a("out", 4, "STEP"), a("out", 5, "DIR")],
  parts=[M("U1", "a4988", {"VDD": "3V3", "GND": "GND", "VBB1": "VMOT", "STEP": "STEP", "DIR": "DIR",
                            "ENABLE": "GND", "SLEEP": "3V3", "MS1": "GND", "MS2": "GND", "MS3": "GND",
                            "OUT1A": "M1A", "OUT1B": "M1B", "OUT2A": "M2A", "OUT2B": "M2B"}, variant="carrier"),
         C("C2", "VMOT", value="100uF", kind="electrolytic")],
  options={"rails": {"VMOT": 12.0}},
  expect=[("mod_unconnected", {"caution"})],
  allow=["mod_hazard"],
  note="Classic: RESET floats, the driver randomly fails to start. Expected: mod_unconnected caution on RESET.")

# 06 WS2812B with 74AHCT125 (correct)
P(id="p06_ws2812_ahct_ok", ok=True, title="60 × WS2812B on 5 V, data via 74AHCT125 + 330 Ω, 1000 µF",
  assignments=[a("out", 16, "LED_3V")],
  parts=[M("U1", "sn74ahct125", {"VCC": "5V", "GND": "GND", "1OE": "GND", "1A": "LED_3V", "1Y": "LED_5V",
                                  "2OE": "5V", "2A": "GND", "3OE": "5V", "3A": "GND", "4OE": "5V", "4A": "GND"}),
         R("R1", "LED_5V", "LED_DIN", "330"),
         M("LED", "ws2812b", {"VDD": "5V", "VSS": "GND", "DIN": "LED_DIN"}, qty=60),
         C("C1", "5V"), C("C2", "5V", value="1000uF", kind="electrolytic")],
  options={"rail_limits": {"5V": 4.0}},
  forbid=["mod_pixel_ws2812_vih", "mod_level_in", "mod_level_out", "mod_unconnected", "mod_level_ahct_needs_5v",
          "mod_level_oe_disabled"],
  allow=["mod_power_budget"],
  note="Textbook solution. Unused channels: OE high (off), A to GND. 60 × ~60 mA = 3.6 A < 4 A. Expected: nothing "
       "(at most a budget note).")

# 07 WS2812B directly on the GPIO (fault)
P(id="p07_ws2812_direct", ok=False, title="30 × WS2812B on 5 V, DIN directly on the 3.3 V GPIO",
  assignments=[a("out", 16, "LED_DIN")],
  parts=[M("LED", "ws2812b", {"VDD": "5V", "VSS": "GND", "DIN": "LED_DIN"}, qty=30),
         C("C2", "5V", value="1000uF", kind="electrolytic")],
  expect=[("mod_pixel_ws2812_vih", {"caution"})],
  forbid=[("mod_pixel_ws2812_vih", {"danger"}), ("mod_level_in", {"danger"})],
  note="VIH 0.7·5 V = 3.5 V > 3.3 V: outside the guarantee, no damage -> caution, exactly one finding.")

# 08 RS-485 with MAX3485 (correct)
P(id="p08_rs485_ok", ok=True, title="RS-485 node MAX3485 on 3V3, DE/RE bridged, 120 Ω termination",
  assignments=[a("uart_tx", 17, "RS_DI"), a("uart_rx", 18, "RS_RO"), a("out", 15, "RS_DE")],
  parts=[M("U1", "max3485", {"VCC": "3V3", "GND": "GND", "RO": "RS_RO", "DI": "RS_DI", "DE": "RS_DE",
                              "RE": "RS_DE", "A": "RS_A", "B": "RS_B"}),
         R("RT", "RS_A", "RS_B", "120"), C("C1", "3V3")],
  allow=["mod_wired_rs485_termination"],
  forbid=["mod_level_out", "mod_level_in", "mod_pin_role", "mod_supply_range", "mod_unconnected"],
  note="One end terminated (the other side is off the board). Expected: at most info on the second termination.")

# 09 MAX485 on 5 V, RO direct (fault)
P(id="p09_max485_5v_ro", ok=False, title="MAX485 on 5 V, RO directly on ESP RX",
  assignments=[a("uart_tx", 17, "RS_DI"), a("uart_rx", 18, "RS_RO"), a("out", 15, "RS_DE")],
  parts=[M("U1", "max485", {"VCC": "5V", "GND": "GND", "RO": "RS_RO", "DI": "RS_DI", "DE": "RS_DE",
                             "RE": "RS_DE", "A": "RS_A", "B": "RS_B"}),
         R("RT", "RS_A", "RS_B", "120"), C("C1", "5V")],
  expect=[("mod_level_out", {"danger"})],
  allow=["mod_wired_max485_ro_5v", "mod_wired_rs485_termination"],
  forbid=[("mod_wired_max485_ro_5v", {"danger", "caution"})],
  note="RO drives 5 V into the GPIO -> danger, once; MAX3485 suggestion as info.")

# 10 LoRa RFM95W (correct)
P(id="p10_lora_ok", ok=True, title="LoRa RFM95W on 3V3, SPI + RESET + DIO0",
  assignments=spi() + [a("spi_cs", 10, "LORA_CS"), a("out", 14, "LORA_RST"), a("in", 7, "LORA_DIO0")],
  parts=[M("U1", "rfm95w", {"GND": "GND", "3.3V": "3V3", "NSS": "LORA_CS", "SCK": "SCK", "MOSI": "MOSI",
                             "MISO": "MISO", "RESET": "LORA_RST", "DIO0": "LORA_DIO0"}),
         C("C1", "3V3"), C("C2", "3V3", value="10uF")],
  allow=["mod_radio_sx1276_duty_20dbm"],
  forbid=["mod_supply_range", "mod_level_in", "mod_level_out", "mod_spi_cs", "mod_unconnected", "mod_pin_role"],
  note="Standard wiring. Expected: nothing (duty cycle note as info is ok).")

# 11 RFM95W on 5 V (fault)
P(id="p11_lora_5v", ok=False, title="RFM95W 3.3V pin tied to 5 V",
  assignments=spi() + [a("spi_cs", 10, "LORA_CS"), a("out", 14, "LORA_RST"), a("in", 7, "LORA_DIO0")],
  parts=[M("U1", "rfm95w", {"GND": "GND", "3.3V": "5V", "NSS": "LORA_CS", "SCK": "SCK", "MOSI": "MOSI",
                             "MISO": "MISO", "RESET": "LORA_RST", "DIO0": "LORA_DIO0"}), C("C1", "5V")],
  expect=[("mod_supply_range", {"danger"})],
  allow=["mod_level_out", "mod_level_in", "mod_radio_sx1276_duty_20dbm"],
  note="Abs. max 3.9 V exceeded; the RFM95W is a radio module without a regulator -> danger (module destroyed). "
       "A follow-up finding on MISO/DIO (5 V high) would be ok, but is not required.")

# 12 CAN with SN65HVD230 (correct)
P(id="p12_can_ok", ok=True, title="CAN node SN65HVD230 on 3V3, Rs to GND, 120 Ω",
  assignments=[a("out", 17, "CAN_TX"), a("in", 18, "CAN_RX")],
  parts=[M("U1", "sn65hvd230", {"VCC": "3V3", "GND": "GND", "D": "CAN_TX", "R": "CAN_RX", "Rs": "GND",
                                 "CANH": "CANH", "CANL": "CANL"}),
         R("RT", "CANH", "CANL", "120"), C("C1", "3V3")],
  allow=["mod_wired_can_termination"],
  forbid=["mod_level_out", "mod_level_in", "mod_wired_hvd230_rs_standby", "mod_supply_range", "mod_unconnected"],
  note="Expected: nothing (termination info for the other end is ok).")

# 13 TJA1050 on 5 V, RXD direct (fault)
P(id="p13_tja1050_5v", ok=False, title="TJA1050 on 5 V, RXD directly on the ESP",
  assignments=[a("out", 17, "CAN_TX"), a("in", 18, "CAN_RX")],
  parts=[M("U1", "tja1050", {"VCC": "5V", "GND": "GND", "TXD": "CAN_TX", "RXD": "CAN_RX", "CANH": "CANH",
                              "CANL": "CANL"}),
         R("RT", "CANH", "CANL", "120"), C("C1", "5V")],
  expect=[("mod_level_out", {"danger"})],
  allow=["mod_wired_tja1050_rxd_5v", "mod_wired_can_termination"],
  forbid=[("mod_wired_tja1050_rxd_5v", {"danger", "caution"})],
  note="RXD push-pull 5 V -> danger once, SN65HVD230 suggestion as info.")

# 14 LCD1602 via PCF8574 on 5 V with 5 V pull-ups (fault, danger)
LCD_CONN = {"VCC": "5V", "GND": "GND", "RS": "L_RS", "RW": "L_RW", "E": "L_E", "DB4": "L_D4", "DB5": "L_D5",
            "DB6": "L_D6", "DB7": "L_D7", "DB0": "GND", "DB1": "GND", "DB2": "GND", "DB3": "GND"}
PCF_LCD = {"P0": "L_RS", "P1": "L_RW", "P2": "L_E", "P3": "L_BL", "P4": "L_D4", "P5": "L_D5", "P6": "L_D6",
           "P7": "L_D7", "A0": "5V", "A1": "5V", "A2": "5V", "GND": "GND", "VCC": "5V"}
P(id="p14_lcd_pcf_5v_pullups", ok=False, title="LCD1602 + PCF8574 backpack on 5 V, pull-ups 4k7 to 5 V",
  assignments=i2c(),
  parts=[M("U1", "pcf8574", {**PCF_LCD, "SDA": "SDA", "SCL": "SCL"}, address="0x27"),
         M("U2", "hd44780", LCD_CONN), *i2c_pullups("5V"), C("C1", "5V")],
  expect=[("mod_level_out", {"danger"})],
  allow=["mod_display_hd44780_rw_gnd", "mod_iox_pcf8574_quasi_bidir"],
  note="SDA/SCL on the ESP pulled to 5 V -> danger. (The PCF8574 VIH of 3.5 V would be met with 5 V pull-ups.)")

# 15 LCD1602 + PCF8574 on 5 V via PCA9306 (correct)
P(id="p15_lcd_pca9306_ok", ok=True, title="LCD1602 + PCF8574 on 5 V behind a PCA9306 (3V3 <-> 5V), pull-ups on each side",
  assignments=i2c(),
  parts=[M("U3", "pca9306", {"GND": "GND", "VREF1": "3V3", "SDA1": "SDA", "SCL1": "SCL", "SDA2": "SDA5",
                              "SCL2": "SCL5", "VREF2": "VREF2", "EN": "VREF2"}),
         R("R_REF", "VREF2", "5V", "200k"), C("C_REF", "VREF2"),
         *i2c_pullups("3V3"), *i2c_pullups("5V", "SDA5", "SCL5", p="R5"),
         M("U1", "pcf8574", {**PCF_LCD, "SDA": "SDA5", "SCL": "SCL5"}, address="0x27"),
         M("U2", "hd44780", LCD_CONN), C("C1", "5V"), C("C2", "3V3")],
  allow=["mod_display_hd44780_rw_gnd", "mod_iox_pcf8574_quasi_bidir"],
  forbid=["mod_level_out", "mod_level_in", "mod_unconnected", "mod_nlevel_pca9306_bias", "mod_required_parts",
          "mod_address_select"],
  note="Application circuit from the PCA9306 datasheet (VREF2 via 200 kΩ to 5 V, EN=VREF2). Expected: nothing.")

# 16 INA219 on a battery (correct)
P(id="p16_ina219_ok", ok=True, title="INA219 high side on a 2S battery (8.4 V), VS 3V3, shunt 0.1 Ω",
  assignments=i2c(),
  parts=[M("U1", "ina219", {"VS": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL", "A0": "GND", "A1": "GND",
                             "IN+": "VBAT", "IN-": "VLOAD"}),
         R("RSH", "VBAT", "VLOAD", "0R1"), *i2c_pullups(), C("C1", "3V3")],
  options={"rails": {"VBAT": 8.4}},
  forbid=["mod_level_out", "mod_level_in", "mod_supply_range", "mod_required_parts", "mod_unconnected"],
  note="Bus voltage 8.4 V < 26 V. Expected: nothing.")

# 17 INA219 on a 36 V e-bike battery (fault)
P(id="p17_ina219_36v", ok=False, title="INA219 high side on a 36 V battery (42 V full)",
  assignments=i2c(),
  parts=[M("U1", "ina219", {"VS": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL", "A0": "GND", "A1": "GND",
                             "IN+": "VBAT", "IN-": "VLOAD"}),
         R("RSH", "VBAT", "VLOAD", "0R01"), *i2c_pullups(), C("C1", "3V3")],
  options={"rails": {"VBAT": 42.0}},
  expect=[("mod_*", {"danger"})],
  note="IN+/IN- common mode max 26 V (abs. max), 42 V destroys the INA219 -> danger. Expected: some danger "
       "on IN+.")

# 18 DS18B20 parasite power (correct)
P(id="p18_ds18b20_parasite_ok", ok=True, title="DS18B20 parasite power: VDD to GND, 4k7 to 3V3",
  assignments=[a("out", 4, "OW")],
  parts=[M("U1", "ds18b20", {"VDD": "GND", "GND": "GND", "DQ": "OW"}), R("R1", "OW", "3V3")],
  allow=["mod_ambient_ds18b20_parasite"],
  forbid=["mod_supply_range", "mod_unconnected", "mod_required_parts", "mod_ambient_ds18b20_pullup",
          "mod_level_out", "mod_level_in"],
  note="Allowed mode of operation; the note 'strong pull-up during conversion' as info/caution is ok, nothing else.")

# 19 DS18B20 without pull-up (fault)
P(id="p19_ds18b20_no_pullup", ok=False, title="DS18B20 on 3V3, DQ only with the internal ESP pull-up",
  assignments=[a("in_pullup", 4, "OW")],
  parts=[M("U1", "ds18b20", {"VDD": "3V3", "GND": "GND", "DQ": "OW"}), C("C1", "3V3")],
  expect=[("mod_ambient_ds18b20_pullup|mod_required_parts", {"caution"})],
  note="The internal pull-up (~45 kΩ) is not enough for 1-Wire -> caution, exactly one finding (not both "
       "required_parts + ds18b20_pullup).")

# 20 relay with driver and diode (correct, switches 12 V)
P(id="p20_relay_ok", ok=True, title="SRD-05VDC on 5 V via NPN + 1 kΩ, 1N4007, switches a 12 V LED strip",
  assignments=[a("out", 15, "RLY_GPIO")],
  parts=[M("K1", "srd_05vdc_sl_c", {"COIL1": "5V", "COIL2": "RLY_C", "COM": "V12", "NO": "LAMP"}),
         {"ref": "Q1", "kind": "transistor", "value": "BC337", "conn": {"C": "RLY_C", "B": "RLY_B", "E": "GND"}},
         R("RB", "RLY_GPIO", "RLY_B", "1k"), D("D1", "RLY_C", "5V")],
  options={"rails": {"V12": 12.0}},
  allow=["mod_hazard"],
  forbid=["mod_required_parts", "mod_unconnected", "mod_supply_range", ("mod_hazard", {"danger"})],
  note="Correct. The contacts switch 12 V (known rail): a 'mains' danger would be a false alarm, a "
       "note is ok.")

# 21 relay directly on the GPIO without diode (fault)
P(id="p21_relay_direct", ok=False, title="SRD-05VDC coil directly between GPIO and GND, no diode",
  assignments=[a("out", 15, "RLY")],
  parts=[M("K1", "srd_05vdc_sl_c", {"COIL1": "RLY", "COIL2": "GND", "COM": "V12", "NO": "LAMP"})],
  options={"rails": {"V12": 12.0}},
  expect=[("mod_switch_relay_flyback|mod_required_parts", {"caution", "danger"}),
          ("mod_switch_relay_needs_driver|mod_power_budget", {"caution", "danger"})],
  allow=["mod_hazard"],
  note="Two faults: the flyback diode is missing (caution) and ~72 mA coil current from the GPIO (>40 mA, a 5 V coil on "
       "3.3 V does not pull in reliably) -> caution/danger.")

# 22 TP4056 charger (correct)
P(id="p22_tp4056_ok", ok=True, title="TP4056 on USB 5V, PROG 1.2 kΩ, CHRG on a GPIO (open drain, internal pull-up)",
  assignments=[a("in_pullup", 6, "CHRG")],
  parts=[M("U1", "tp4056", {"VCC": "5V", "GND": "GND", "BAT": "VBAT", "PROG": "PROG", "TEMP": "GND",
                             "CE": "5V", "CHRG": "CHRG"}),
         R("RPROG", "PROG", "GND", "1k2"), C("C1", "5V", value="10uF"), C("C2", "VBAT", value="10uF"),
         {"ref": "BT1", "kind": "battery", "value": "18650", "conn": {"+": "VBAT", "-": "GND"}}],
  options={"rails": {"VBAT": 4.2}},
  expect=[("mod_hazard", {"danger"})],
  forbid=["mod_level_out", "mod_level_in", "mod_supply_range", "mod_unconnected", "mod_pin_role"],
  note="Correct. The Li-ion safety notice as danger is a project rule, nothing else.")

# 23 PCA9685 servo driver (correct)
P(id="p23_pca9685_ok", ok=True, title="PCA9685 on 3V3, servo on LED0, servo V+ 5 V with 470 µF",
  assignments=i2c(),
  parts=[M("U1", "pca9685", {"VDD": "3V3", "VSS": "GND", "SDA": "SDA", "SCL": "SCL", "A0": "GND", "A1": "GND",
                              "A2": "GND", "A3": "GND", "A4": "GND", "A5": "GND", "OE": "GND", "LED0": "SERVO0"}),
         {"ref": "S1", "kind": "servo", "value": "SG90", "conn": {"SIG": "SERVO0", "V+": "5V", "GND": "GND"}},
         *i2c_pullups(), C("C1", "3V3"), C("C2", "5V", value="470uF", kind="electrolytic")],
  forbid=["mod_address_conflict", "mod_address_reserved", "mod_iox_pca9685_allcall", "mod_unconnected",
          "mod_level_out", "mod_level_in"],
  note="Only device, 0x40. Expected: nothing (all-call 0x70 only matters with a 0x70 device).")

# 24 PCA9685 + TCA9548A all-call conflict (fault)
P(id="p24_pca9685_tca_allcall", ok=False, title="PCA9685 (0x40) + TCA9548A (0x70) on the same bus, BME280 on channel 0",
  assignments=i2c(),
  parts=[M("U1", "pca9685", {"VDD": "3V3", "VSS": "GND", "SDA": "SDA", "SCL": "SCL", "A0": "GND", "A1": "GND",
                              "A2": "GND", "A3": "GND", "A4": "GND", "A5": "GND", "OE": "GND", "LED0": "SERVO0"}),
         M("U2", "tca9548a", {"VCC": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL", "A0": "GND", "A1": "GND",
                               "A2": "GND", "RESET": "TCA_RST", "SD0": "SDA_0", "SC0": "SCL_0"}),
         R("R_RST", "TCA_RST", "3V3", "10k"),
         BME("U3", sda="SDA_0", scl="SCL_0"), *i2c_pullups(), *i2c_pullups("3V3", "SDA_0", "SCL_0", p="R0"),
         C("C1", "3V3")],
  expect=[("mod_iox_pca9685_allcall|mod_address_conflict|mod_address_reserved", {"caution", "danger"})],
  note="After reset the PCA9685 answers the all-call 0x70 = TCA9548A -> caution, exactly one finding.")

# 25 MAX30102 on 3V3 (fault, danger)
P(id="p25_max30102_3v3", ok=False, title="MAX30102 (bare chip) VDD on 3V3",
  assignments=i2c() + [a("in_pullup", 7, "HR_INT")],
  parts=[M("U1", "max30102", {"VDD": "3V3", "GND": "GND", "VLED+": "3V3", "SDA": "SDA", "SCL": "SCL",
                               "INT": "HR_INT"}),
         *i2c_pullups(), R("R_INT", "HR_INT", "3V3"), C("C1", "3V3")],
  expect=[("mod_motion_max30102_vdd_1v8|mod_supply_range", {"danger"})],
  note="VDD abs. max 2.2 V -> danger, exactly one finding (not both supply_range + max30102_vdd_1v8).")

# 26 MAX30102 correct (1.8 V LDO)
P(id="p26_max30102_ok", ok=True, title="MAX30102 VDD on a 1.8 V rail, VLED+ 3V3, pull-ups to 3V3",
  assignments=i2c() + [a("in", 7, "HR_INT")],
  parts=[M("U1", "max30102", {"VDD": "V1V8", "GND": "GND", "VLED+": "3V3", "SDA": "SDA", "SCL": "SCL",
                               "INT": "HR_INT"}),
         *i2c_pullups(), R("R_INT", "HR_INT", "3V3"), C("C1", "3V3"), C("C2", "V1V8")],
  options={"rails": {"V1V8": 1.8}},
  forbid=["mod_motion_max30102_vdd_1v8", "mod_supply_range", "mod_level_out", "mod_level_in",
          "mod_required_parts"],
  note="As in the datasheet (SDA/SCL/INT tolerant up to 6 V, VIH 0.7·1.8 V). Expected: nothing.")

# 27 HC-SR04 echo direct (fault)
P(id="p27_hcsr04_direct", ok=False, title="HC-SR04 on 5 V, echo directly on the GPIO",
  assignments=[a("out", 4, "TRIG"), a("in", 5, "ECHO")],
  parts=[M("U1", "hcsr04", {"VCC": "5V", "GND": "GND", "Trig": "TRIG", "Echo": "ECHO"})],
  expect=[("mod_prox_hcsr04_echo|mod_level_out", {"danger", "caution"})],
  note="Echo = 5 V into the GPIO -> danger (well documented). Exactly one finding expected.")

# 28 HC-SR04 with voltage divider (correct)
P(id="p28_hcsr04_divider_ok", ok=True, title="HC-SR04 on 5 V, echo via a 1k/2k divider",
  assignments=[a("out", 4, "TRIG"), a("in", 5, "ECHO_DIV")],
  parts=[M("U1", "hcsr04", {"VCC": "5V", "GND": "GND", "Trig": "TRIG", "Echo": "ECHO5"}),
         R("R1", "ECHO5", "ECHO_DIV", "1k"), R("R2", "ECHO_DIV", "GND", "2k")],
  forbid=["mod_prox_hcsr04_echo", "mod_unconnected", "mod_level_out"],
  note="5 V · 2/3 = 3.33 V. Expected: nothing (no 'typo in the net name' on ECHO5).")

# 29 two VL53L0X with a shared XSHUT (fault)
VL = lambda ref, xs: M(ref, "vl53l0x", {"AVDD": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL",  # noqa: E731
                                         "XSHUT": xs})
P(id="p29_vl53_shared_xshut", ok=False, title="Two VL53L0X, both XSHUT on the same GPIO",
  assignments=i2c() + [a("out", 4, "XSHUT")],
  parts=[VL("U1", "XSHUT"), VL("U2", "XSHUT"), *i2c_pullups(), C("C1", "3V3"),
         C("C2", "3V3", value="4.7uF")],
  expect=[("mod_prox_vl53_xshut|mod_address_conflict|mod_required_parts", {"caution", "danger"})],
  allow=["mod_hazard"],
  note="Both 0x29, readdressing needs one XSHUT each -> caution, ideally one finding with a fix.")

# 30 SSD1306 + SH1106 both 0x3C (fault)
P(id="p30_two_oled_0x3c", ok=False, title="SSD1306 + SH1106 on the same bus, both SA0 to GND",
  assignments=i2c() + [a("out", 21, "OLED_RST")],
  parts=[OLED(), M("U3", "sh1106", {"VDD1": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL", "SA0": "GND",
                                     "RES": "OLED_RST"}),
         *i2c_pullups(), C("C1", "3V3")],
  expect=[("mod_address_conflict", {"caution", "danger"})],
  allow=["mod_display_sh1106_vs_ssd1306", "mod_display_oled_two_per_bus"],
  note="0x3C twice -> one conflict finding with the fix SA0 to VDD.")

# 31 ADS1115 measures 5 V at VDD 3V3 (fault)
P(id="p31_ads1115_ain_5v", ok=False, title="ADS1115 on 3V3, AIN0 directly on the 5 V rail",
  assignments=i2c(),
  parts=[M("U1", "ads1115", {"VDD": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL", "ADDR": "GND",
                              "AIN0": "5V"}),
         *i2c_pullups(), C("C1", "3V3")],
  expect=[("mod_adc_ads_ain_vdd|mod_adc_ain_abs_max", {"danger"})],
  note="AIN max VDD+0.3 V = 3.6 V -> danger.")

# 32 TFT ST7789 + SD card, separate CS (correct)
SPI_TFT = lambda cs="TFT_CS": M("U1", "st7789v", {"VDD": "3V3", "GND": "GND", "CSX": cs, "SCL": "SCK",  # noqa: E731
                                                  "SDA": "MOSI", "D/CX": "TFT_DC", "RESX": "TFT_RST"})
SPI_SD = lambda cs="SD_CS": M("U2", "sdcard", {"VDD": "3V3", "VSS": "GND", "CS": cs, "DI": "MOSI",  # noqa: E731
                                               "SCLK": "SCK", "DO": "MISO"})
P(id="p32_tft_sd_ok", ok=True, title="ST7789 TFT + microSD (3V3) on the same SPI, separate CS",
  assignments=spi() + [a("spi_cs", 10, "TFT_CS"), a("spi_cs", 14, "SD_CS"), a("out", 15, "TFT_DC"),
                       a("out", 16, "TFT_RST")],
  parts=[SPI_TFT(), SPI_SD(), R("R_SDCS", "SD_CS", "3V3", "10k"), C("C1", "3V3"), C("C2", "3V3", value="10uF")],
  allow=["mod_net_sd_spi_init_400k", "mod_pixel_tft_spi_clock"],
  forbid=["mod_spi_cs", "mod_unconnected", "mod_pin_role", "mod_level_out", "mod_level_in", "mod_supply_range"],
  note="Expected: nothing (the 400 kHz init note as info is ok).")

# 33 TFT + SD share CS (fault)
P(id="p33_tft_sd_shared_cs", ok=False, title="ST7789 TFT + microSD share one CS net (TFT with SDO on MISO)",
  assignments=spi() + [a("spi_cs", 10, "CS"), a("out", 15, "TFT_DC"), a("out", 16, "TFT_RST")],
  parts=[M("U1", "st7789v", {"VDD": "3V3", "GND": "GND", "CSX": "CS", "SCL": "SCK", "SDA": "MOSI",
                             "SDO": "MISO", "D/CX": "TFT_DC", "RESX": "TFT_RST"}),
         SPI_SD("CS"), C("C1", "3V3")],
  expect=[("mod_spi_cs", {"danger"})],
  allow=["mod_net_sd_spi_init_400k", "mod_pixel_tft_spi_clock"],
  note="Both drive MISO -> danger (bus conflict).")

# 34 GPS UART not crossed (fault)
P(id="p34_gps_uart_straight", ok=False, title="GY-NEO6MV2 on 3V3, TX->TX and RX->RX",
  assignments=[a("uart_tx", 17, "GPS_TX"), a("uart_rx", 18, "GPS_RX")],
  parts=[M("U1", "neo6m", {"VCC": "3V3", "GND": "GND", "TX": "GPS_TX", "RX": "GPS_RX"}, variant="gy_neo6mv2")],
  expect=[("mod_pin_role", {"caution", "danger"})],
  forbid=["mod_supply_range"],
  note="RX/TX not crossed -> one finding per module (or per pin) with the text 'UART not crossed'.")

# 35 SIM800L on 3V3 (fault)
P(id="p35_sim800l_3v3", ok=False, title="SIM800L breakout VCC on the 3V3 of the DevKit, without a bulk electrolytic",
  assignments=[a("uart_tx", 17, "GSM_RXD"), a("uart_rx", 18, "GSM_TXD")],
  parts=[M("U1", "sim800l", {"VCC": "3V3", "GND": "GND", "RXD": "GSM_RXD", "TXD": "GSM_TXD"},
           variant="breakout")],
  expect=[("mod_net_sim800_vbat|mod_supply_range", {"caution", "danger"})],
  allow=["mod_required_parts", "mod_power_budget", "mod_net_sim800_vih"],
  note="3.3 V < 3.4 V min and 2 A peaks -> caution (brownout), the electrolytic is missing; ideally one main finding.")

# 36 HX711 load cell (correct)
P(id="p36_hx711_ok", ok=True, title="HX711 on 3V3 with a load cell",
  assignments=[a("out", 4, "HX_SCK"), a("in", 5, "HX_DOUT")],
  parts=[M("U1", "hx711", {"VSUP": "3V3", "AVDD": "3V3", "DVDD": "3V3", "AGND": "GND", "PD_SCK": "HX_SCK",
                            "DOUT": "HX_DOUT", "INA+": "LC_P", "INA-": "LC_N", "INB+": "GND", "INB-": "GND"}),
         {"ref": "LC1", "kind": "loadcell", "value": "5kg", "conn": {"E+": "3V3", "E-": "GND", "S+": "LC_P",
                                                                     "S-": "LC_N"}},
         C("C1", "3V3")],
  forbid=["mod_level_out", "mod_level_in", "mod_supply_range", "mod_unconnected", "mod_pin_role"],
  note="Expected: nothing.")

# 37 ULN2003 + 28BYJ-48 (correct)
P(id="p37_uln2003_ok", ok=True, title="ULN2003A + 28BYJ-48 on 5 V, COM to 5 V",
  assignments=[a("out", 4, "IN1"), a("out", 5, "IN2"), a("out", 6, "IN3"), a("out", 7, "IN4")],
  parts=[M("U1", "uln2003a", {"1B": "IN1", "2B": "IN2", "3B": "IN3", "4B": "IN4", "1C": "MA", "2C": "MB",
                               "3C": "MC", "4C": "MD", "E": "GND", "COM": "5V"}),
         {"ref": "M1", "kind": "motor", "value": "28BYJ-48 5V", "conn": {"A": "MA", "B": "MB", "C": "MC", "D": "MD",
                                                                          "COM": "5V"}},
         C("C1", "5V", value="100uF", kind="electrolytic")],
  allow=["mod_hazard"],
  forbid=["mod_motor_uln_com_flyback", "mod_level_in", "mod_unconnected", "mod_supply_range"],
  note="COM on the motor supply = flyback diodes active. Expected: only motor notes.")

# 38 I2S audio INMP441 + MAX98357A (correct)
P(id="p38_i2s_audio_ok", ok=True, title="INMP441 microphone + MAX98357A amplifier on a shared BCLK/WS",
  assignments=[a("out", 4, "BCLK"), a("out", 5, "WS"), a("in", 6, "MIC_SD"), a("out", 7, "AMP_DIN")],
  parts=[M("U1", "inmp441", {"VDD": "3V3", "GND": "GND", "SCK": "BCLK", "WS": "WS", "SD": "MIC_SD", "L/R": "GND",
                              "CHIPEN": "3V3"}),
         R("R_SD", "MIC_SD", "GND", "100k"),
         M("U2", "max98357a", {"VDD": "5V", "GND": "GND", "BCLK": "BCLK", "LRCLK": "WS", "DIN": "AMP_DIN",
                                "SD_MODE": "3V3", "OUTP": "SPK_P", "OUTN": "SPK_N"}),
         C("C1", "3V3"), C("C2", "5V"), C("C3", "5V", value="10uF", kind="electrolytic")],
  allow=["mod_hazard"],
  forbid=["mod_logic_inmp441_lr", "mod_level_in", "mod_level_out", "mod_required_parts", "mod_unconnected",
          "mod_pin_role"],
  note="Expected: at most a high_current note.")

# 39 GY-87 style: MPU-6050 + QMC5883L + BMP280 on 3V3 (correct)
P(id="p39_imu_compass_ok", ok=True, title="MPU-6050 + QMC5883L + BMP280 on 3V3 (different addresses)",
  assignments=i2c(),
  parts=[M("U1", "mpu6050", {"VDD": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL", "AD0": "GND"}),
         M("U2", "qmc5883l", {"VDD": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL"}),
         M("U3", "bmp280", {"VDD": "3V3", "GND": "GND", "SDI": "SDA", "SCK": "SCL", "SDO": "3V3"}),
         *i2c_pullups(), C("C1", "3V3")],
  allow=["mod_env_bmp_vs_bme"],
  forbid=["mod_address_conflict", "mod_level_out", "mod_level_in", "mod_supply_range", "mod_required_parts",
          "mod_unconnected"],
  note="0x68, 0x0D, 0x77. Expected: nothing (the BMP vs BME note as info is ok).")

# 40 TXB0104 on I2C (fault)
P(id="p40_txb0104_i2c", ok=False, title="TXB0104 as an I²C level shifter to the 5 V PCF8574",
  assignments=i2c(),
  parts=[M("U3", "txb0104", {"VCCA": "3V3", "VCCB": "5V", "GND": "GND", "OE": "3V3", "A1": "SDA", "B1": "SDA5",
                              "A2": "SCL", "B2": "SCL5", "A3": "GND", "A4": "GND"}),
         *i2c_pullups("3V3"), *i2c_pullups("5V", "SDA5", "SCL5", p="R5"),
         M("U1", "pcf8574", {"VCC": "5V", "GND": "GND", "SDA": "SDA5", "SCL": "SCL5", "A0": "GND", "A1": "GND",
                              "A2": "GND"}),
         C("C1", "5V"), C("C2", "3V3")],
  expect=[("mod_level_txb_not_i2c", {"caution"})],
  allow=["mod_level_txb_pull_resistor"],
  note="TXB (auto direction, push-pull booster) is unsuitable for I²C -> caution, recommend PCA9306/TXS/BSS138.")

assert len(PROJECTS) == 40, len(PROJECTS)
assert sum(p["ok"] for p in PROJECTS) == 20
