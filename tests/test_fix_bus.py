"""False alarms and double findings of the generic bus rules (modrules/bus.py).

- mod.unconnected: a net counts as defined through a pull-up/pull-down to a rail, a series resistor to a driven net
  or a module supply pin on it; a module output nobody reads is info without the typo text.
- level shifters / I²C buffers (PCA9306, TXS0108E, TXB0104, BSS138, SN74LVC1T45) are bridges: buses run through
  them, pin_role checks no direction on their channel pins, the far side counts as wired.
- mod.address_conflict / mod.address_reserved: caution (the bus fails, nothing is damaged), the text names the way out.
- project mistakes: a ref used twice, conn values that are no text -> caution.
- mod.net_shared_signals: different bus lines on one net -> danger (MOSI+MISO: caution, 3-wire SPI).
Real catalog modules (data/modules/*.json), synthetic projects.
"""
from __future__ import annotations

import modkit as k

from circuit_bench.bench_core import contracts, modcheck, pins

UNC = "mod.unconnected"
ROLE = "mod.pin_role"
CONFLICT = "mod.address_conflict"
RESERVED = "mod.address_reserved"
SHARED = "mod.net_shared_signals"
SPEED = "mod.bus_speed"
BUS = [k.assign("i2c_sda", 8, "SDA"), k.assign("i2c_scl", 9, "SCL")]


def R(ref, a, b, value="4k7"):
    return {"ref": ref, "kind": "resistor", "value": value, "conn": {"1": a, "2": b}}


def C(ref, a, b="GND"):
    return {"ref": ref, "kind": "capacitor", "value": "100nF", "conn": {"1": a, "2": b}}


def run(parts, assignments=BUS, options=None, only=None):
    return k.run(assignments=assignments, parts=parts, options=options, only=only)


def failed(rep, rule_id, sev=("caution", "danger")):
    return [f for f in k.findings(rep, rule_id, "failed") if f.severity in sev]


def bme(ref="B1", sda="SDA", scl="SCL", sdo="GND"):
    return k.mod(ref, "bme280", {"VDD": "3V3", "GND": "GND", "SDI": sda, "SCK": scl, "SDO": sdo})


def pcf(ref="U1", sda="SDA5", scl="SCL5", a=("GND", "GND", "GND")):
    return k.mod(ref, "pcf8574", {"VCC": "5V", "GND": "GND", "SDA": sda, "SCL": scl,
                                  "A0": a[0], "A1": a[1], "A2": a[2]})


def pca9306(ref="U3"):
    return k.mod(ref, "pca9306", {"GND": "GND", "VREF1": "3V3", "SDA1": "SDA", "SCL1": "SCL", "SDA2": "SDA5",
                                  "SCL2": "SCL5", "VREF2": "VREF2", "EN": "VREF2"})


def i2c_side(rail, sda, scl, p):
    return [R(p + "SDA", sda, rail), R(p + "SCL", scl, rail)]


# --- 1 mod.unconnected: what defines a net -------------------------------------------------------------------------
def test_pullup_to_a_rail_defines_a_shared_input_net():
    a4988 = k.mod("U1", "a4988", {"VDD": "3V3", "GND": "GND", "VBB1": "VMOT", "STEP": "STEP", "DIR": "DIR",
                                  "ENABLE": "GND", "SLEEP": "SLP_RST", "RESET": "SLP_RST", "MS1": "GND",
                                  "MS2": "GND", "MS3": "GND"})
    asg = [k.assign("out", 4, "STEP"), k.assign("out", 5, "DIR")]
    opts = {"rails": {"VMOT": 12.0}}
    rep = run([a4988, R("R_SLP", "SLP_RST", "3V3"), C("C2", "VMOT")], asg, opts, only=(UNC,))
    assert not [f for f in failed(rep, UNC) if "SLP_RST" in f.message]
    # without the pull-up the shared net floats: still reported, with the typo text
    rep = run([a4988, C("C2", "VMOT")], asg, opts, only=(UNC,))
    w = [f for f in failed(rep, UNC) if "SLP_RST" in f.message]
    assert w and all(f.severity == "caution" and "Typo" in f.message for f in w)


def test_open_reset_stays_caution_and_board_mode_pin_is_info():
    a4988 = k.mod("U1", "a4988", {"VDD": "3V3", "GND": "GND", "VBB1": "VMOT", "STEP": "STEP", "DIR": "DIR",
                                  "ENABLE": "GND", "SLEEP": "3V3", "MS1": "GND", "MS2": "GND", "MS3": "GND"},
                  variant="carrier")
    rep = run([a4988, C("C2", "VMOT")], [k.assign("out", 4, "STEP"), k.assign("out", 5, "DIR")],
              {"rails": {"VMOT": 12.0}}, only=(UNC,))
    hard = failed(rep, UNC)
    assert [f for f in hard if "RESET" in f.message] and not [f for f in hard if "ROSC" in f.message]
    assert not [f for f in failed(rep, UNC) if "ROSC" in f.message]  # nc on the carrier


def test_series_resistor_from_a_buffer_output_defines_the_led_input():
    parts = [k.mod("U1", "sn74ahct125", {"VCC": "5V", "GND": "GND", "1OE": "GND", "1A": "LED_3V", "1Y": "LED_5V",
                                         "2OE": "5V", "2A": "GND", "3OE": "5V", "3A": "GND", "4OE": "5V",
                                         "4A": "GND"}),
             R("R1", "LED_5V", "LED_DIN", "330"), k.mod("LED", "ws2812b", {"VDD": "5V", "VSS": "GND",
                                                                          "DIN": "LED_DIN"}), C("C1", "5V")]
    rep = run(parts, [k.assign("out", 16, "LED_3V")], only=(UNC,))
    assert failed(rep, UNC, ("info", "caution", "danger")) == []


def test_output_into_a_divider_or_to_ground_resistor_is_read():
    hc = k.mod("U1", "hcsr04", {"VCC": "5V", "GND": "GND", "Trig": "TRIG", "Echo": "ECHO5"})
    rep = run([hc, R("R1", "ECHO5", "ECHO_DIV", "1k"), R("R2", "ECHO_DIV", "GND", "2k")],
              [k.assign("out", 4, "TRIG"), k.assign("in", 5, "ECHO_DIV")], only=(UNC,))
    assert failed(rep, UNC, ("info", "caution", "danger")) == []
    tp = k.mod("U1", "tp4056", {"VCC": "5V", "GND": "GND", "BAT": "VBAT", "PROG": "PROG", "TEMP": "GND",
                                "CE": "5V", "CHRG": "CHRG"})
    rep = run([tp, R("RPROG", "PROG", "GND", "1k2"), C("C1", "5V"), C("C2", "VBAT")],
              [k.assign("in_pullup", 6, "CHRG")], {"rails": {"VBAT": 4.2}}, only=(UNC,))
    assert not [f for f in failed(rep, UNC, ("info", "caution", "danger")) if "PROG" in f.message]


def test_unread_module_output_is_info_without_typo_text():
    parts = [k.mod("U1", "pca9685", {"VDD": "3V3", "VSS": "GND", "SDA": "SDA", "SCL": "SCL", "A0": "GND",
                                     "A1": "GND", "A2": "GND", "A3": "GND", "A4": "GND", "A5": "GND", "OE": "GND",
                                     "LED0": "SERVO0"}), *i2c_side("3V3", "SDA", "SCL", "R")]
    rep = run(parts, only=(UNC,))
    w = [f for f in k.findings(rep, UNC, "failed") if "SERVO0" in f.message]
    assert len(w) == 1 and w[0].severity == "info" and "Typo" not in w[0].message
    assert "nothing reads this output" in w[0].message


def test_supply_pin_on_the_net_defines_an_enable_input():
    parts = [pca9306(), R("R_REF", "VREF2", "5V", "200k"), *i2c_side("3V3", "SDA", "SCL", "R"),
             *i2c_side("5V", "SDA5", "SCL5", "R5"), pcf()]
    rep = run(parts, only=(UNC,))
    assert not [f for f in failed(rep, UNC) if "EN" in f.message]


def test_typo_input_net_without_driver_is_still_caught():
    a4988 = k.mod("U1", "a4988", {"VDD": "3V3", "GND": "GND", "VBB1": "VMOT", "STEP": "STEPP", "DIR": "DIR",
                                  "ENABLE": "GND", "SLEEP": "3V3", "RESET": "3V3", "MS1": "GND", "MS2": "GND",
                                  "MS3": "GND", "ROSC": "GND"})
    rep = run([a4988, R("RX", "DIR", "3V3")], [k.assign("out", 4, "STEP"), k.assign("out", 5, "DIR")],
              {"rails": {"VMOT": 12.0}}, only=(UNC,))
    w = [f for f in failed(rep, UNC) if "STEPP" in f.message]
    assert w and "Typo" in w[0].message


# --- 2 level shifters / I²C buffers as bridges ---------------------------------------------------------------------
def test_pca9306_carries_the_bus_devices_behind_it_land_on_it():
    parts = [pca9306(), R("R_REF", "VREF2", "5V", "200k"), *i2c_side("3V3", "SDA", "SCL", "R"),
             *i2c_side("5V", "SDA5", "SCL5", "R5"), pcf(), C("C1", "5V")]
    rep = run(parts, only=(UNC, ROLE, CONFLICT, SPEED))
    assert failed(rep, UNC) == [] and failed(rep, ROLE) == []
    speed = k.findings(rep, SPEED, "failed")
    assert speed and "U1" in speed[0].refs and "No f_max_hz data for U3" not in speed[0].message
    # a second PCF8574 at the same address behind the bridge collides with one in front of it
    rep = run([*parts, pcf("U4", "SDA", "SCL")], only=(CONFLICT,))
    w = failed(rep, CONFLICT)
    assert len(w) == 1 and set(w[0].refs) == {"U1", "U4"} and w[0].severity == "caution"


def test_txs0108e_and_txb0104_channels_check_no_direction():
    for mod_id in ("txs0108e", "txb0104"):
        conn = {"VCCA": "3V3", "VCCB": "5V", "GND": "GND", "OE": "3V3", "A1": "SDA", "B1": "SDA5", "A2": "SCL",
                "B2": "SCL5", "A3": "GND", "A4": "GND"}
        if mod_id == "txs0108e":
            conn.update({f"A{i}": "GND" for i in range(5, 9)})
        parts = [k.mod("U3", mod_id, conn), pcf(), C("C1", "5V"), C("C2", "3V3")]
        rep = run(parts, only=(UNC, ROLE))
        assert failed(rep, ROLE) == [], mod_id
        assert not [f for f in failed(rep, UNC) if "SDA5" in f.message or "SCL5" in f.message], mod_id


def test_device_behind_a_bridge_keeps_its_role_check():
    # SDA/SCL crossed behind the shifter: pin_role still sees the ESP modes through the bridge
    parts = [pca9306(), R("R_REF", "VREF2", "5V", "200k"), *i2c_side("5V", "SDA5", "SCL5", "R5"),
             *i2c_side("3V3", "SDA", "SCL", "R"), pcf(sda="SCL5", scl="SDA5")]
    w = failed(run(parts, only=(ROLE,)), ROLE)
    assert w and all(f.severity == "caution" and "level shifter" in f.message for f in w)


def test_bss138_and_lvc1t45_pairs_link_the_nets():
    parts = [k.mod("Q1", "bss138", {"G": "3V3", "S": "SDA", "D": "SDA5"}),
             k.mod("Q2", "bss138", {"G": "3V3", "S": "SCL", "D": "SCL5"}),
             *i2c_side("3V3", "SDA", "SCL", "R"), *i2c_side("5V", "SDA5", "SCL5", "R5"), pcf(), C("C1", "5V")]
    rep = run(parts, only=(UNC, ROLE, CONFLICT))
    assert failed(rep, UNC) == [] and failed(rep, ROLE) == []
    assert k.findings(rep, CONFLICT, "passed")  # PCF behind the FETs is on the bus
    lvc = k.mod("U2", "sn74lvc1t45", {"VCCA": "3V3", "VCCB": "5V", "GND": "GND", "A": "LED_3V", "B": "LED_5V",
                                      "DIR": "VCCA_NET"})
    led = k.mod("LED", "ws2812b", {"VDD": "5V", "VSS": "GND", "DIN": "LED_5V"})
    rep = run([lvc, led, R("RD", "VCCA_NET", "3V3", "10k"), C("C1", "5V")], [k.assign("out", 16, "LED_3V")],
              only=(UNC, ROLE))
    assert failed(rep, ROLE) == [] and not [f for f in failed(rep, UNC) if "LED_5V" in f.message]


def test_buffer_is_no_bridge():
    parts = [k.mod("U1", "sn74ahct125", {"VCC": "5V", "GND": "GND", "1OE": "GND", "1A": "SDA", "1Y": "SDA5",
                                         "2OE": "5V", "2A": "GND", "3OE": "5V", "3A": "GND", "4OE": "5V",
                                         "4A": "GND"}), pcf(scl="SCL"), *i2c_side("3V3", "SDA", "SCL", "R")]
    rep = run(parts, only=(UNC,))
    assert [f for f in failed(rep, UNC) if "SDA5" in f.message]  # one-way buffer: SDA cannot pass back


# --- 3 address findings: caution with the way out -----------------------------------------------------------------
def test_address_conflict_is_caution_and_names_the_way_out():
    oled = [k.mod(r, m, {"VDD": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL", "SA0": "GND", "RES": "RST"})
            for r, m in (("U2", "ssd1306"), ("U3", "sh1106"))]
    rep = run([*oled, *i2c_side("3V3", "SDA", "SCL", "R")], [*BUS, k.assign("out", 21, "RST")], only=(CONFLICT,))
    w = failed(rep, CONFLICT)
    assert len(w) == 1 and w[0].severity == "caution"
    assert "address pin" in w[0].message and "second I²C bus" in w[0].message and "mux" in w[0].message
    assert len(w[0].message) <= modcheck.MAX_MESSAGE_CHARS


def test_address_reserved_is_caution():
    parts = [k.mod("U1", "pca9685", {"VDD": "3V3", "VSS": "GND", "SDA": "SDA", "SCL": "SCL", "A0": "GND",
                                     "A1": "GND", "A2": "GND", "A3": "GND", "A4": "GND", "A5": "GND", "OE": "GND"}),
             k.mod("U2", "tca9548a", {"VCC": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL", "A0": "GND",
                                      "A1": "GND", "A2": "GND", "RESET": "3V3"}),
             *i2c_side("3V3", "SDA", "SCL", "R")]
    w = failed(run(parts, only=(RESERVED,)), RESERVED)
    assert len(w) == 1 and w[0].severity == "caution" and "address pin" in w[0].message


# --- 5 project mistakes --------------------------------------------------------------------------------------------
def test_conn_values_that_are_no_text_are_reported():
    bad = k.mod("U1", "bme280")
    bad["conn"] = {"VDD": 3.3, "GND": None, "SDI": ["SDA"], "SCK": {"x": 1}}
    rep = run([bad], only=(UNC,))
    w = [f for f in failed(rep, UNC) if "no net name" in f.message]
    assert len(w) == 1 and w[0].refs == ["U1"] and "VDD = 3.3" in w[0].message
    p = k.mod("U1", "bme280")
    p["conn"] = ["SDA", "SCL"]
    rep = run([p], only=(UNC,))
    assert [f for f in failed(rep, UNC) if "not a map" in f.message]


def test_duplicate_refs_are_reported():
    rep = run([bme("U1"), bme("U1", sdo="3V3"), R("U1", "SDA", "3V3")], only=(UNC,))
    w = [f for f in failed(rep, UNC) if "is used by" in f.message]
    assert len(w) == 1 and w[0].refs == ["U1"] and "3 parts" in w[0].message


# --- mod.net_shared_signals -----------------------------------------------------------------------------------------
def test_sda_and_scl_on_one_net_is_danger_and_covers_pin_role():
    asg = [k.assign("i2c_sda", 8, "i2c0"), k.assign("i2c_scl", 9, "i2c0")]
    rep = run([bme("U1", "i2c0", "i2c0")], asg, only=(SHARED, ROLE, UNC))
    w = failed(rep, SHARED)
    assert len(w) == 1 and w[0].severity == "danger" and set(w[0].refs) == {"GPIO8", "GPIO9", "U1"}
    assert "SDA and SCL share net i2c0" in w[0].message and "I2C0_SDA / I2C0_SCL" in w[0].message
    assert rep is not None and [x["code"] for x in rep.warnings] == ["mod_net_shared_signals"]


def test_spi_lines_on_one_net_and_three_wire():
    spi = [k.assign("spi_sck", 12, "spi0"), k.assign("spi_mosi", 11, "spi0"), k.assign("spi_miso", 13, "spi0")]
    w = failed(run([bme()], spi, only=(SHARED,)), SHARED)
    assert len(w) == 1 and w[0].severity == "danger" and "SCK, MOSI and MISO share net spi0" in w[0].message
    three = [k.assign("spi_sck", 12, "SCK"), k.assign("spi_mosi", 11, "SDIO"), k.assign("spi_miso", 13, "SDIO")]
    w = failed(run([bme()], three, only=(SHARED,)), SHARED)
    assert len(w) == 1 and w[0].severity == "caution" and "3-wire" in w[0].message


def test_module_with_sda_and_scl_on_one_net():
    rep = run([bme("U1", "SDA", "SDA")], only=(SHARED, ROLE))
    w = failed(rep, SHARED)
    assert len(w) == 1 and w[0].severity == "danger" and w[0].refs == ["U1"]
    assert rep is not None and [x["code"] for x in rep.warnings] == ["mod_net_shared_signals"]  # the swap finding is folded in


def test_separate_lines_pass_and_mux_channels_are_fine():
    parts = [k.mod("U2", "tca9548a", {"VCC": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL", "A0": "GND",
                                      "A1": "GND", "A2": "GND", "RESET": "3V3", "SD0": "SDA_0", "SC0": "SCL_0"}),
             bme("U3", "SDA_0", "SCL_0")]
    rep = run(parts, only=(SHARED,))
    assert failed(rep, SHARED) == [] and k.findings(rep, SHARED, "passed")


def test_pins_check_reports_shared_net_through_the_envelope():
    asg = [k.assign("i2c_sda", 8, "i2c0"), k.assign("i2c_scl", 9, "i2c0")]
    env = pins.check("esp32s3", asg, parts=[bme("U1", "i2c0", "i2c0")])
    assert env["ok"] and contracts.validate_envelope(env) == []
    assert ("mod_net_shared_signals", "danger") in {(w["code"], w["severity"]) for w in env["warnings"]}
