"""Generic bus rules of the module check engine.

Rules: mod.address_conflict (mux visibility), mod.address_reserved, mod.address_select, mod.bus_speed,
mod.pin_role, mod.spi_cs, mod.unconnected. Per rule: positive, negative, edge case, missing data -> not_checked.
Plus a false-alarm list of correct projects (synthetic and with the real BME280) and runs through pins.check.
Every module below is synthetic (sources tst-…, see tests/mod_fixtures.py); only BME280 comes from the catalog.
"""
from __future__ import annotations

import copy

import mod_fixtures as fx
import modkit as k
import pytest

from circuit_bench.bench_core import contracts, modcheck, modules, pins, sources

F = fx.F
GND = fx.GND
BUS = k.i2c()  # SDA0 on GPIO8, SCL0 on GPIO9
I2C = {"SDA": "SDA0", "SCL": "SCL0"}
MINE = ("mod.address_conflict", "mod.address_reserved", "mod.address_select", "mod.bus_speed", "mod.pin_role",
        "mod.spi_cs", "mod.unconnected", "mod.net_shared_signals")
MY_CODES = {modcheck.warning_code(r) for r in MINE}


def _i2c_pins(*extra):
    return [{"name": "VDD", "signal": "supply"}, GND, {"name": "SDA", "signal": "i2c_sda"},
            {"name": "SCL", "signal": "i2c_scl"}, *extra]


PWM = {  # like a 16-channel PWM driver: two address pins (multi-pin select), an all-call address
    "id": "tst_pwm", "title": "TST PWM driver", "category": "io.pwm", "manufacturer": "Test", "kind": "ic",
    "source_ids": ["tst-sensor-ds"], "supplies": {"VDD": {"min": F(2.3), "max": F(5.5)}},
    "pins": _i2c_pins({"name": "A1", "signal": "addr_select", "must_connect": True},
                      {"name": "A0", "signal": "addr_select", "must_connect": True},
                      {"name": "OE", "signal": "enable_in", "active_low": True, "tie": "GND"}),
    "interfaces": [{"type": "i2c", "addresses": F(["0x40", "0x41", "0x42", "0x43"], "bit"), "default": "0x40",
                    "select": {"pins": ["A1", "A0"], "map": {"GND,GND": "0x40", "GND,VDD": "0x41",
                                                             "VDD,GND": "0x42", "VDD,VDD": "0x43"}},
                    "reserved": ["0x70"], "f_max_hz": F(1e6, "Hz")}],
}
BPWM = {**PWM, "id": "tst_bpwm", "title": "TST PWM board (shop data)", "kind": "module",
        "source_ids": ["tst-bsensor-shop"]}
FIXED70 = {  # a device at a fixed 0x70 (like an LED matrix driver)
    "id": "tst_fixed70", "title": "TST LED matrix driver", "category": "display.led", "manufacturer": "Test",
    "kind": "ic", "source_ids": ["tst-rtc-ds"], "pins": _i2c_pins(),
    "interfaces": [{"type": "i2c", "addresses": F(["0x70"], "bit"), "default": "0x70", "f_max_hz": F(4e5, "Hz")}],
}
SLOW = {  # like an 8-bit ADC/DAC with a 100 kHz bus
    "id": "tst_slow", "title": "TST 8-bit ADC/DAC", "category": "adc", "manufacturer": "Test", "kind": "ic",
    "source_ids": ["tst-sensor-ds"],
    "pins": _i2c_pins({"name": "AIN0", "signal": "analog_in"}, {"name": "AOUT", "signal": "analog_out"}),
    "interfaces": [{"type": "i2c", "addresses": F(["0x48"], "bit"), "default": "0x48",
                    "f_max_hz": F(1e5, "Hz", "tst-sensor-ds")}],
}
NOADDR = {  # I²C interface without address data
    "id": "tst_noaddr", "title": "TST sensor without address data", "category": "sensor.light",
    "manufacturer": "Test", "kind": "ic", "source_ids": ["tst-sensor-ds"], "pins": _i2c_pins(),
    "interfaces": [{"type": "i2c"}],
}
MUX2 = {  # mux with the loader's channel format: [[SDx, SCx], ...]
    "id": "tst_mux2", "title": "TST 2-channel mux", "category": "io.i2c_mux", "manufacturer": "Test", "kind": "ic",
    "source_ids": ["tst-mux-ds"],
    "pins": _i2c_pins({"name": "A0", "signal": "addr_select", "tie": "GND"},
                      *({"name": f"SD{c}", "signal": "i2c_sda"} for c in range(2)),
                      *({"name": f"SC{c}", "signal": "i2c_scl"} for c in range(2))),
    "interfaces": [{"type": "i2c", "addresses": F(["0x74", "0x75"], "bit"), "default": "0x74",
                    "select": {"pin": "A0", "map": {"GND": "0x74", "VDD": "0x75"}},
                    "mux_channels": [["SD0", "SC0"], ["SD1", "SC1"]]}],
}
SPI = {  # SPI ADC: full duplex, CS active low
    "id": "tst_spi", "title": "TST SPI ADC", "category": "adc", "manufacturer": "Test", "kind": "ic",
    "source_ids": ["tst-sensor-ds"], "supplies": {"VCC": {"min": F(2.7), "max": F(5.5)}},
    "pins": [{"name": "VCC", "signal": "supply"}, GND, {"name": "SCK", "signal": "spi_sck"},
             {"name": "SDI", "signal": "spi_sdi"}, {"name": "SDO", "signal": "spi_sdo"},
             {"name": "CS", "signal": "spi_cs", "active_low": True}],
    "interfaces": [{"type": "spi", "mode": 0}],
}
LCD = {  # write-only SPI display: no SDO, RST with an internal pull-up
    "id": "tst_lcd", "title": "TST SPI display", "category": "display.tft", "manufacturer": "Test", "kind": "ic",
    "source_ids": ["tst-oled-ds"],
    "pins": [{"name": "VCC", "signal": "supply"}, GND, {"name": "SCK", "signal": "spi_sck"},
             {"name": "SDI", "signal": "spi_sdi"}, {"name": "CS", "signal": "spi_cs"},
             {"name": "DC", "signal": "digital_in"}, {"name": "RST", "signal": "reset_in", "internal_pull": "up"}],
    "interfaces": [{"type": "spi", "mode": 0}],
}
NOCS = {**SPI, "id": "tst_nocs", "title": "TST SPI device without CS data",
        "pins": [p for p in SPI["pins"] if p["name"] != "CS"]}
GPS = {  # UART module
    "id": "tst_gps", "title": "TST GNSS receiver", "category": "comm.gnss", "manufacturer": "Test", "kind": "module",
    "source_ids": ["tst-breakout-ds"],
    "pins": [{"name": "VCC", "signal": "supply"}, GND, {"name": "TX", "signal": "uart_tx"},
             {"name": "RX", "signal": "uart_rx"}, {"name": "PPS", "signal": "digital_out"}],
    "interfaces": [{"type": "uart", "baud_default": 9600}],
}
SHIFT = {  # shift register: plain digital inputs without pulls, a chain output
    "id": "tst_shift", "title": "TST shift register", "category": "logic.shift_register", "manufacturer": "Test",
    "kind": "ic", "source_ids": ["tst-5v-ds"],
    "pins": [{"name": "VCC", "signal": "supply"}, GND, {"name": "SER", "signal": "digital_in"},
             {"name": "SRCLK", "signal": "digital_in"}, {"name": "RCLK", "signal": "digital_in"},
             {"name": "OE", "signal": "enable_in", "active_low": True},
             {"name": "QH2", "signal": "digital_out", "output": "push_pull"}],
    "interfaces": [{"type": "digital"}],
}
I2CSHIFT = {  # bidirectional I²C level shifter: SDA/SCL on both sides (a bridge, two pins per signal)
    "id": "tst_i2cshift", "title": "TST I2C level shifter", "category": "logic.level_shifter", "manufacturer": "Test",
    "kind": "ic", "source_ids": ["tst-sensor-ds"],
    "pins": [{"name": "VCCA", "signal": "supply"}, {"name": "VCCB", "signal": "supply"}, GND,
             {"name": "SDAA", "signal": "i2c_sda"}, {"name": "SCLA", "signal": "i2c_scl"},
             {"name": "SDAB", "signal": "i2c_sda"}, {"name": "SCLB", "signal": "i2c_scl"}],
    "interfaces": [{"type": "digital"}],
}
NOPINS = {"id": "tst_nopins", "title": "TST part without pin data", "category": "sensor.light",
          "manufacturer": "Test", "kind": "ic", "source_ids": ["tst-sensor-ds"], "pins": []}
ODD = {"id": "tst_odd", "title": "TST part with an unknown signal", "category": "sensor.light",
       "manufacturer": "Test", "kind": "ic", "source_ids": ["tst-sensor-ds"],
       "pins": [{"name": "VCC", "signal": "supply"}, GND, {"name": "X", "signal": "weird"}]}
EXTRA = (PWM, BPWM, FIXED70, SLOW, NOADDR, MUX2, SPI, LCD, NOCS, GPS, SHIFT, I2CSHIFT, NOPINS, ODD)
CAT = fx.catalog(*EXTRA)

SPI_A = [k.assign("spi_sck", 12, "SCK"), k.assign("spi_mosi", 11, "MOSI"), k.assign("spi_miso", 13, "MISO"),
         k.assign("spi_cs", 10, "CS1"), k.assign("spi_cs", 14, "CS2")]
UART_A = [k.assign("uart_tx", 17, "TX1"), k.assign("uart_rx", 18, "RX1")]


def run(parts, assignments=BUS, options=None, catalog=None, only=MINE):
    return k.run(catalog=catalog or CAT, electrical=fx.ESP, assignments=assignments, parts=parts,
                 options=options, only=only)


def warns(rep, rule_id):
    return [w for w in rep.warnings if w["code"] == modcheck.warning_code(rule_id)]


def fs(rep, rule_id, status=None):
    return k.findings(rep, rule_id, status)


def status(rep, rule_id):
    c = k.check_of(rep, rule_id)
    return None if c is None else c["status"]


def sensor(ref="U1", **conn):
    return k.mod(ref, "tst_sensor", {**I2C, "VDD": "3V3", "SDO": "GND", **conn})


def mux(ref="M1", sda="SDA0", scl="SCL0", channels=(0, 1), a0=None, prefix=None):
    p = prefix or ref
    conn = {"SDA": sda, "SCL": scl, "VCC": "3V3"}
    for c in channels:
        conn[f"SD{c}"], conn[f"SC{c}"] = f"{p}D{c}", f"{p}C{c}"
    if a0:
        conn["A0"] = a0
    return k.mod(ref, "tst_mux", conn)


def on(ch_ref, c):
    """conn of an I²C device on channel c of mux ch_ref (see mux())."""
    return {"SDA": f"{ch_ref}D{c}", "SCL": f"{ch_ref}C{c}"}


def pwm(ref="P1", a1="GND", a0="GND", address=None, module="tst_pwm", **conn):
    c = {**I2C, "VDD": "3V3", "GND": "GND", **conn}
    if a1:
        c["A1"] = a1
    if a0:
        c["A0"] = a0
    return k.mod(ref, module, c, address=address)


# --- mod.address_conflict: mux visibility ------------------------------------------------------------------------
def test_conflict_main_against_a_mux_channel():
    rep = run([mux(), sensor("U1"), k.mod("U2", "tst_sensor", {**on("M1", 0), "VDD": "3V3", "SDO": "GND"})])
    w = warns(rep, "mod.address_conflict")
    assert len(w) == 1 and w[0]["severity"] == "caution" and w[0]["refs"] == ["U1", "U2"]
    assert "across segments main, M1.0" in w[0]["message"] and "0x76" in w[0]["message"]
    assert "0x77 (SDO to VDDIO)" in w[0]["message"] and w[0]["source_ids"] == ["tst-sensor-ds"]


def test_sibling_channels_do_not_conflict_but_say_one_channel_at_a_time():
    rep = run([mux(), k.mod("U1", "tst_sensor", {**on("M1", 0), "VDD": "3V3", "SDO": "GND"}),
               k.mod("U2", "tst_sensor", {**on("M1", 1), "VDD": "3V3", "SDO": "GND"})])
    assert warns(rep, "mod.address_conflict") == [] and status(rep, "mod.address_conflict") == "passed"
    hint = [f for f in fs(rep, "mod.address_conflict", "passed") if "share 0x76" in f.message]
    assert hint and "U1 (M1.0), U2 (M1.1)" in hint[0].message and "one of these channels" in hint[0].message


def test_nested_mux_sees_its_ancestors_only():
    parts = [mux(), k.mod("M2", "tst_mux", {**on("M1", 0), "VCC": "3V3", "A0": "3V3", "SD2": "N2", "SC2": "NK2"}),
             k.mod("U4", "tst_oled", {"SDA": "N2", "SCL": "NK2", "VDD": "3V3"}),
             k.mod("U5", "tst_oled", {**on("M1", 0), "VDD": "3V3"}),  # parent segment of M2.2: collides
             k.mod("U6", "tst_oled", {**on("M1", 1), "VDD": "3V3"})]  # sibling channel of the mux: does not
    rep = run(parts)
    w = warns(rep, "mod.address_conflict")
    assert [x["refs"] for x in w] == [["U5", "U4"]]  # segment order: M1.0 before M2.2
    assert "segments M1.0, M2.2" in w[0]["message"]


def test_mux_own_address_downstream_conflicts():
    rep = run([mux(), k.mod("U1", "tst_fixed70", {**on("M1", 1), "VDD": "3V3"})])
    w = warns(rep, "mod.address_conflict")
    assert w and w[0]["refs"] == ["M1", "U1"] and "0x70" in w[0]["message"]
    assert "0x71 (A0 to VCC)" in w[0]["message"]  # the mux can move, U1 cannot


def test_loader_style_mux_channels_open_segments():
    parts = [k.mod("M1", "tst_mux2", {**I2C, "VDD": "3V3", "SD0": "XD0", "SC0": "XC0", "SD1": "XD1", "SC1": "XC1"}),
             k.mod("U1", "tst_rtc", {"SDA": "XD0", "SCL": "XC0", "VCC": "5V"}),
             k.mod("U2", "tst_rtc", {"SDA": "XD1", "SCL": "XC1", "VCC": "5V"})]
    rep = run(parts)
    assert warns(rep, "mod.address_conflict") == []
    assert rep.result["buses"][0]["segments"][1]["id"] == "M1.0"


def test_device_without_address_data_is_not_checked():
    rep = run([sensor(), k.mod("U2", "tst_noaddr", {**I2C, "VDD": "3V3", "GND": "GND"})])
    w = warns(rep, "mod.address_conflict")
    assert len(w) == 1 and w[0]["severity"] == "info" and w[0]["refs"] == ["U2"] and "not checked" in w[0]["message"]
    assert status(rep, "mod.address_conflict") == "not_checked"


# --- mod.address_reserved -----------------------------------------------------------------------------------------
def test_reserved_all_call_hits_the_mux():
    rep = run([pwm(), mux()])
    w = warns(rep, "mod.address_reserved")
    assert len(w) == 1 and w[0]["severity"] == "caution" and w[0]["refs"] == ["P1", "M1"]
    assert "0x70" in w[0]["message"] and "also answers" in w[0]["message"]
    assert w[0]["source_ids"] == ["tst-sensor-ds", "tst-mux-ds"]
    assert status(rep, "mod.address_reserved") == "failed"


def test_reserved_passes_when_the_mux_moves():
    rep = run([pwm(), mux(a0="3V3")])
    assert warns(rep, "mod.address_reserved") == [] and status(rep, "mod.address_reserved") == "passed"


def test_reserved_two_drivers_share_the_all_call_by_design():
    rep = run([pwm("P1"), pwm("P2", a0="3V3")])
    assert warns(rep, "mod.address_reserved") == [] and status(rep, "mod.address_reserved") == "passed"


def test_reserved_behind_a_channel_sees_the_upstream_mux_but_not_a_sibling():
    up = run([mux(), k.mod("P1", "tst_pwm", {**on("M1", 0), "VDD": "3V3", "GND": "GND", "A1": "GND", "A0": "GND"})])
    assert [w["refs"] for w in warns(up, "mod.address_reserved")] == [["P1", "M1"]]
    assert "across segments M1.0, main" in warns(up, "mod.address_reserved")[0]["message"]
    side = run([mux(a0="3V3"),
                k.mod("P1", "tst_pwm", {**on("M1", 0), "VDD": "3V3", "GND": "GND", "A1": "GND", "A0": "GND"}),
                k.mod("U1", "tst_fixed70", {**on("M1", 1), "VDD": "3V3"})])
    assert warns(side, "mod.address_reserved") == [] and status(side, "mod.address_reserved") == "passed"


def test_reserved_unknown_neighbour_address_is_not_checked_without_a_second_warning():
    rep = run([pwm(), k.mod("U2", "tst_noaddr", {**I2C, "VDD": "3V3", "GND": "GND"})])
    assert warns(rep, "mod.address_reserved") == [] and status(rep, "mod.address_reserved") == "not_checked"


def test_reserved_class_b_is_info():
    rep = run([pwm(module="tst_bpwm"), mux()])
    w = warns(rep, "mod.address_reserved")
    assert w and w[0]["severity"] == "info" and "Unverified" in w[0]["message"]


# --- mod.address_select (select.pin and select.pins) ----------------------------------------------------------------
def test_select_must_connect_open_single_and_multi_pin():
    rep = run([k.mod("U1", "tst_sensor", {**I2C, "VDD": "3V3"}), pwm(a0=None)])
    w = {x["refs"][0]: x for x in warns(rep, "mod.address_select")}
    assert w["U1"]["severity"] == "caution" and "SDO must be connected" in w["U1"]["message"]
    assert "GND → 0x76, VDDIO → 0x77" in w["U1"]["message"]
    assert w["P1"]["severity"] == "caution" and "A0 must be connected" in w["P1"]["message"]
    assert "A1=GND A0=VDD → 0x41" in w["P1"]["message"]


def test_select_explicit_address_contradicts_the_pin():
    rep = run([k.mod("U1", "tst_sensor", {**I2C, "VDD": "3V3", "SDO": "GND"}, address="0x77"),
               pwm(a0="3V3", address="0x42")])
    w = {x["refs"][0]: x for x in warns(rep, "mod.address_select")}
    assert "0x77 is set, but SDO on GND selects 0x76" in w["U1"]["message"]
    assert "connect SDO to VDDIO" in w["U1"]["message"] and w["U1"]["source_ids"] == ["tst-sensor-ds"]
    assert "A1 on GND, A0 on 3V3 selects 0x41" in w["P1"]["message"]
    assert "connect A1 to VDD, A0 to GND" in w["P1"]["message"]


def test_select_consistent_passes_also_via_same_voltage_rail():
    rep = run([k.mod("U1", "tst_sensor", {**I2C, "VDD": "3V3", "SDO": "VDDIO"}, address="0x77"),
               pwm(a1="3V3", a0="3V3"),
               k.mod("U3", "tst_sensor", {**I2C, "VDD": "3V3", "SDO": "VB"})], options={"rails": {"VB": 3.3}})
    assert warns(rep, "mod.address_select") == [] and status(rep, "mod.address_select") == "passed"
    assert {f.refs[0]: f.message for f in fs(rep, "mod.address_select")}["P1"].endswith("selects 0x43.")


def test_select_open_pin_without_must_connect_uses_the_default():
    ok = run([k.mod("U1", "tst_breakout", {**I2C, "VIN": "3V3", "GND": "GND"})])
    assert status(ok, "mod.address_select") == "passed" and "default address 0x44" in fs(ok, "mod.address_select")[0].message
    bad = run([k.mod("U1", "tst_breakout", {**I2C, "VIN": "3V3", "GND": "GND"}, address="0x45")])
    w = warns(bad, "mod.address_select")
    assert w and w[0]["severity"] == "caution" and "ADR is open (default 0x44); connect ADR to VIN" in w[0]["message"]


def test_select_explicit_address_outside_the_list():
    rep = run([sensor(), k.mod("U2", "tst_rtc", {**I2C, "VCC": "5V"}, address="0x50")])
    w = warns(rep, "mod.address_select")
    assert w and w[0]["refs"] == ["U2"] and "not one of the module's addresses (0x68)" in w[0]["message"]


def test_select_pin_on_a_net_outside_the_map_is_not_checked():
    rep = run([sensor(SDO="GPIO5")], assignments=[*BUS, k.assign("out", 5)])
    w = warns(rep, "mod.address_select")
    assert w and w[0]["severity"] == "info" and "SDO on GPIO5 is not in the select map" in w[0]["message"]
    assert status(rep, "mod.address_select") == "not_checked"


def test_select_without_address_list_is_not_checked():
    rep = run([k.mod("U1", "tst_noaddr", {**I2C, "VDD": "3V3", "GND": "GND"}, address="0x10")])
    assert status(rep, "mod.address_select") == "not_checked"
    assert k.check_of(run([k.mod("U1", "tst_rtc", {**I2C, "VCC": "5V"})]), "mod.address_select") is None  # fixed


# --- mod.bus_speed ------------------------------------------------------------------------------------------------
def test_bus_speed_slow_device_limits_the_bus():
    rep = run([sensor(), k.mod("U2", "tst_oled", {**I2C, "VDD": "3V3"}),
               k.mod("U3", "tst_slow", {**I2C, "VDD": "3V3", "GND": "GND"})])
    w = warns(rep, "mod.bus_speed")
    assert len(w) == 1 and w[0]["severity"] == "info" and w[0]["refs"] == ["U3"]
    assert "allow at most 100 kHz, limited by U3 (tst_slow)" in w[0]["message"] and "400 kHz" in w[0]["message"]
    assert w[0]["source_ids"] == ["tst-sensor-ds", "nxp-um10204"]
    assert "nxp-um10204" in sources.all_sources()


def test_bus_speed_fast_parts_pass_with_the_limiting_part():
    rep = run([sensor(), sensor("U2", SDO="VDDIO")])
    assert warns(rep, "mod.bus_speed") == [] and status(rep, "mod.bus_speed") == "passed"
    assert "allow at most 3.40 MHz, limited by U1, U2 (tst_sensor)" in fs(rep, "mod.bus_speed")[0].message


def test_bus_speed_exactly_fast_mode_is_no_finding_and_channels_are_named():
    rep = run([sensor(), k.mod("U2", "tst_oled", {**I2C, "VDD": "3V3"})])
    assert status(rep, "mod.bus_speed") == "passed" and "400 kHz" in fs(rep, "mod.bus_speed")[0].message
    ch = run([mux(), k.mod("U3", "tst_slow", {**on("M1", 1), "VDD": "3V3", "GND": "GND"})])
    w = warns(ch, "mod.bus_speed")
    assert w and "on M1.1: applies while that channel is selected" in w[0]["message"]
    assert "No f_max_hz data for M1" in w[0]["message"]


def test_bus_speed_without_data_is_not_checked():
    rep = run([k.mod("U1", "tst_rtc", {**I2C, "VCC": "5V"})])
    assert warns(rep, "mod.bus_speed") == [] and status(rep, "mod.bus_speed") == "not_checked"
    part = run([k.mod("U1", "tst_rtc", {**I2C, "VCC": "5V"}), k.mod("U2", "tst_oled", {**I2C, "VDD": "3V3"})])
    assert status(part, "mod.bus_speed") == "not_checked"
    assert "No f_max_hz data for U1" in fs(part, "mod.bus_speed")[0].message


# --- mod.pin_role -------------------------------------------------------------------------------------------------
def test_uart_not_crossed():
    rep = run([k.mod("G1", "tst_gps", {"VCC": "3V3", "GND": "GND", "TX": "TX1", "RX": "RX1"})], assignments=UART_A)
    w = warns(rep, "mod.pin_role")
    assert len(w) == 2 and all(x["severity"] == "caution" for x in w)
    assert all("UART not crossed" in x["message"] for x in w)
    assert any("output against output" in x["message"] for x in w)  # module TX against ESP TX
    assert all("Breakout board" not in x["message"] for x in w)  # a role fact: no breakout cap (chip_fact=False)


def test_uart_crossed_passes():
    rep = run([k.mod("G1", "tst_gps", {"VCC": "3V3", "GND": "GND", "TX": "RX1", "RX": "TX1"})], assignments=UART_A)
    assert warns(rep, "mod.pin_role") == [] and status(rep, "mod.pin_role") == "passed"


def test_i2c_swapped_and_spi_mosi_miso_swapped():
    rep = run([k.mod("U1", "tst_sensor", {"SDA": "SCL0", "SCL": "SDA0", "VDD": "3V3", "SDO": "GND"})])
    w = warns(rep, "mod.pin_role")
    assert len(w) == 2 and all("SDA and SCL swapped" in x["message"] for x in w)
    spi = run([k.mod("S1", "tst_spi", {"VCC": "3V3", "GND": "GND", "SCK": "SCK", "SDI": "MISO", "SDO": "MOSI",
                                       "CS": "CS1"})], assignments=SPI_A)
    w = warns(spi, "mod.pin_role")
    assert len(w) == 2 and all("MOSI/MISO swapped" in x["message"] for x in w)


def test_push_pull_output_against_esp_output_is_danger_input_mismatch_is_caution():
    rep = run([k.mod("U1", "tst_5v_display", {"VCC": "5V", "GND": "GND", "DIN": "GPIO4", "DOUT": "GPIO5"})],
              assignments=[k.assign("in", 4), k.assign("out", 5)])
    w = {x["message"].split(" ")[2]: x for x in warns(rep, "mod.pin_role")}
    assert w["DOUT"]["severity"] == "danger" and "push-pull output" in w["DOUT"]["message"]
    assert w["DIN"]["severity"] == "caution" and "expected ESP mode out or pwm" in w["DIN"]["message"]
    assert "on GPIO4, ESP mode in" in w["DIN"]["message"]


def test_pin_role_unknown_signal_is_not_checked():
    rep = run([k.mod("U1", "tst_odd", {"VCC": "3V3", "GND": "GND", "X": "GPIO4"})], assignments=[k.assign("out", 4)])
    assert warns(rep, "mod.pin_role") == [] and status(rep, "mod.pin_role") == "not_checked"


# --- mod.spi_cs ---------------------------------------------------------------------------------------------------
def _spi(ref, cs, module="tst_spi", **conn):
    base = {"VCC": "3V3", "GND": "GND", "SCK": "SCK", "SDI": "MOSI", "CS": cs}
    if module == "tst_spi":
        base["SDO"] = "MISO"
    if module == "tst_lcd":
        base["DC"] = "GPIO4"
    return k.mod(ref, module, {**base, **conn})


SPI_AO = [*SPI_A, k.assign("out", 4)]


def test_shared_cs_with_shared_miso_is_danger():
    rep = run([_spi("S1", "CS1"), _spi("S2", "CS1")], assignments=SPI_AO)
    w = warns(rep, "mod.spi_cs")
    assert len(w) == 1 and w[0]["severity"] == "danger" and w[0]["refs"] == ["S1", "S2"]
    assert "share the chip-select net CS1" in w[0]["message"] and "MISO" in w[0]["message"]


def test_shared_cs_write_only_is_caution():
    rep = run([_spi("D1", "CS1", "tst_lcd"), _spi("D2", "CS1", "tst_lcd")], assignments=SPI_AO)
    w = warns(rep, "mod.spi_cs")
    assert len(w) == 1 and w[0]["severity"] == "caution" and "receive every transfer" in w[0]["message"]


def test_own_cs_each_passes():
    rep = run([_spi("S1", "CS1"), _spi("D1", "CS2", "tst_lcd")], assignments=SPI_AO)
    assert warns(rep, "mod.spi_cs") == [] and status(rep, "mod.spi_cs") == "passed"
    assert "S1 on CS1, D1 on CS2" in k.check_of(rep, "mod.spi_cs")["detail"]


def test_cs_tied_to_a_rail():
    alone = run([_spi("S1", "GND")], assignments=SPI_A)
    assert warns(alone, "mod.spi_cs") == [] and status(alone, "mod.spi_cs") == "passed"
    shared = run([_spi("S1", "GND"), _spi("S2", "CS2")], assignments=SPI_A)
    w = warns(shared, "mod.spi_cs")
    assert w and w[0]["refs"] == ["S1"] and "always selected" in w[0]["message"] and "S2" in w[0]["message"]
    never = run([_spi("S1", "3V3")], assignments=SPI_A)
    assert "never selected" in warns(never, "mod.spi_cs")[0]["message"]


def test_cs_open_or_missing_in_data_is_not_checked():
    rep = run([k.mod("S1", "tst_spi", {"VCC": "3V3", "GND": "GND", "SCK": "SCK", "SDI": "MOSI", "SDO": "MISO"})],
              assignments=SPI_A)
    assert warns(rep, "mod.spi_cs") == [] and status(rep, "mod.spi_cs") == "not_checked"
    assert any("CS (spi_cs) is open" in w["message"] for w in warns(rep, "mod.unconnected"))
    nocs = run([k.mod("S1", "tst_nocs", {"VCC": "3V3", "GND": "GND", "SCK": "SCK", "SDI": "MOSI", "SDO": "MISO"})],
               assignments=SPI_A)
    assert status(nocs, "mod.spi_cs") == "not_checked" and "no chip-select pin" in k.check_of(nocs, "mod.spi_cs")[
        "detail"]


# --- mod.unconnected ------------------------------------------------------------------------------------------------
def test_open_supply_and_ground():
    rep = run([k.mod("U1", "tst_slow", {**I2C})])  # GND has a tie in the data, VDD not
    w = warns(rep, "mod.unconnected")
    assert len(w) == 1 and w[0]["severity"] == "caution" and "VDD (supply) is not connected" in w[0]["message"]
    assert w[0]["source_ids"] == ["tst-sensor-ds"]
    tied = run([k.mod("U1", "tst_sensor", {**I2C, "SDO": "GND"})])  # VDDIO and CSB follow VDD: one finding
    assert [x["message"].split(" ")[2] for x in warns(tied, "mod.unconnected")] == ["VDD"]
    rep = run([{"ref": "B1", "kind": "ic", "value": "BME280", "module": "bme280",
                "conn": {"SDI": "SDA0", "SCK": "SCL0", "SDO": "GND", "VDD": "3V3"}}], catalog=_bme_catalog())
    assert [w["message"] for w in warns(rep, "mod.unconnected")] == [
        "B1 (bme280) GND (gnd) is not connected: the module has no ground on this pin."]


def test_half_wired_i2c_and_receive_only_uart():
    rep = run([k.mod("U1", "tst_sensor", {"SDA": "SDA0", "VDD": "3V3", "SDO": "GND"}),
               k.mod("G1", "tst_gps", {"VCC": "3V3", "GND": "GND", "TX": "RX1"})], assignments=[*BUS, *UART_A])
    w = {x["refs"][0]: x for x in warns(rep, "mod.unconnected")}
    assert w["U1"]["severity"] == "caution" and "SCL (i2c_scl) is open" in w["U1"]["message"]
    assert w["G1"]["severity"] == "info" and "receive-only" in w["G1"]["message"]


def test_floating_inputs_none_wired_and_internal_pull():
    rep = run([k.mod("Q1", "tst_shift", {"VCC": "5V", "GND": "GND", "SER": "GPIO4", "SRCLK": "GPIO5",
                                         "RCLK": "GPIO6"}),
               k.mod("Q2", "tst_shift", {"VCC": "5V", "GND": "GND"}),
               _spi("D1", "CS1", "tst_lcd")], assignments=[*SPI_A, *(k.assign("out", n) for n in (4, 5, 6))])
    w = warns(rep, "mod.unconnected")
    assert [(x["refs"], "OE" in x["message"]) for x in w if x["refs"] == ["Q1"]] == [(["Q1"], True)]
    assert "floating input" in [x for x in w if x["refs"] == ["Q1"]][0]["message"]
    q2 = [x for x in w if x["refs"] == ["Q2"]]
    assert len(q2) == 1 and "none of its signal pins" in q2[0]["message"]  # one finding, not five
    assert not [x for x in w if x["refs"] == ["D1"]]  # RST has an internal pull-up


def test_net_without_esp_assignment():
    rep = run([k.mod("U1", "tst_sensor", {"SDA": "SDA1", "SCL": "SCL0", "VDD": "3V3", "SDO": "GND"}),
               k.mod("Q1", "tst_shift", {"VCC": "5V", "GND": "GND", "SER": "GPIO5", "SRCLK": "GPIO4",
                                         "RCLK": "GPIO4", "OE": "GND"})],
              assignments=[*BUS, k.assign("out", 4)])
    w = warns(rep, "mod.unconnected")
    msgs = " | ".join(x["message"] for x in w)
    assert "SDA (i2c_sda) on net SDA1: no ESP pin is assigned" in msgs and "Typo" in msgs
    assert "SER (digital_in) on net GPIO5: GPIO5 has no assignment" in msgs and "out or pwm" in msgs


def test_module_to_module_chain_and_mux_channels_need_no_esp_pin():
    rep = run([k.mod("Q1", "tst_shift", {"VCC": "5V", "GND": "GND", "SER": "GPIO4", "SRCLK": "GPIO5",
                                         "RCLK": "GPIO6", "OE": "GND", "QH2": "CHAIN"}),
               k.mod("Q2", "tst_shift", {"VCC": "5V", "GND": "GND", "SER": "CHAIN", "SRCLK": "GPIO5",
                                         "RCLK": "GPIO6", "OE": "GND"}),
               mux(), k.mod("U1", "tst_sensor", {**on("M1", 0), "VDD": "3V3", "SDO": "GND"})],
              assignments=[*BUS, *(k.assign("out", n) for n in (4, 5, 6))])
    assert warns(rep, "mod.unconnected") == [] and status(rep, "mod.unconnected") == "passed"


def test_i2c_on_a_bridge_net_needs_no_esp_pin_but_a_lone_typo_net_does():
    two = run([sensor(), k.mod("U2", "tst_rtc", {"SDA": "SDAX", "SCL": "SCLX", "VCC": "5V"}),
               k.mod("U3", "tst_rtc", {"SDA": "SDAX", "SCL": "SCLX", "VCC": "5V"})])
    assert {w["refs"][0] for w in warns(two, "mod.unconnected")} == {"U2", "U3"}  # two devices are no bridge


def test_half_wired_mux_channel():
    rep = run([k.mod("M1", "tst_mux", {**I2C, "VCC": "3V3", "SD0": "M1D0"}),
               k.mod("U1", "tst_sensor", {"SDA": "M1D0", "SCL": "M1C0", "VDD": "3V3", "SDO": "GND"})])
    msgs = [w["message"] for w in warns(rep, "mod.unconnected")]
    assert any("channel 0: only SD0 is connected" in m for m in msgs)
    assert any("U1 (tst_sensor) SCL (i2c_scl) on net M1C0" in m for m in msgs)


def test_unconnected_without_pin_list_is_not_checked():
    rep = run([k.mod("U1", "tst_nopins", {})], assignments=BUS)
    assert status(rep, "mod.unconnected") == "not_checked" and warns(rep, "mod.unconnected") == []


# --- false-alarm list: correct projects give no warning and no failed check from these rules -----------------------
def _bme_catalog():
    """The real BME280 entry next to the synthetic parts (its source with the real class)."""
    entry = {kk: v for kk, v in modules.catalog().get("bme280").items() if not kk.startswith("_")}
    srcs = {**fx.SOURCES, "mod-env-bme280-ds": dict(sources.all_sources()["mod-env-bme280-ds"])}
    mods = {m["id"]: m for m in [*fx.MODULES, *EXTRA, entry]}
    return fx.FakeCatalog(list(mods.values()), sources=srcs)


def bme(ref="B1", sdo="GND", sda="SDA0", scl="SCL0"):
    return {"ref": ref, "kind": "ic", "value": "BME280", "module": "bme280",
            "conn": {"SDI": sda, "SCK": scl, "SDO": sdo, "VDD": "3V3", "GND": "GND"}}


GOOD = {
    "one_sensor": ([sensor()], BUS, None),
    "two_sensors_by_select_pin": ([sensor("U1"), sensor("U2", SDO="VDDIO")], BUS, None),
    "mux_two_equal_sensors_and_oled": ([mux(), k.mod("U1", "tst_sensor", {**on("M1", 0), "VDD": "3V3", "SDO": "GND"}),
                                        k.mod("U2", "tst_sensor", {**on("M1", 1), "VDD": "3V3", "SDO": "GND"}),
                                        k.mod("U3", "tst_oled", {**I2C, "VDD": "3V3"})], BUS, None),
    "pwm_drivers_and_moved_mux": ([pwm("P1"), pwm("P2", a1="3V3", address="0x42"), mux(a0="3V3"),
                                   k.mod("U1", "tst_rtc", {**on("M1", 0), "VCC": "5V"})], BUS, None),
    "spi_adc_and_display": ([_spi("S1", "CS1"), _spi("D1", "CS2", "tst_lcd")], SPI_AO, None),
    "uart_gps_with_pps": ([k.mod("G1", "tst_gps", {"VCC": "3V3", "GND": "GND", "TX": "RX1", "RX": "TX1",
                                                   "PPS": "GPIO15"})], [*UART_A, k.assign("in", 15)], None),
    "shift_chain": ([k.mod("Q1", "tst_shift", {"VCC": "3V3", "GND": "GND", "SER": "GPIO4", "SRCLK": "GPIO5",
                                               "RCLK": "GPIO6", "OE": "GND", "QH2": "CHAIN"}),
                     k.mod("Q2", "tst_shift", {"VCC": "3V3", "GND": "GND", "SER": "CHAIN", "SRCLK": "GPIO5",
                                               "RCLK": "GPIO6", "OE": "GND"})],
                    [k.assign("out", n) for n in (4, 5, 6)], None),
    "bme280_pair": ([bme("B1"), bme("B2", sdo="3V3")], BUS, "real"),
    "bme280_with_oled_and_rtc_behind_mux": ([bme("B1", sdo="3V3"), k.mod("U2", "tst_oled", {**I2C, "VDD": "3V3"}),
                                             mux(), bme("B2", sda="M1D1", scl="M1C1"),
                                             bme("B3", sda="M1D0", scl="M1C0"),
                                             k.mod("U3", "tst_rtc", {**on("M1", 0), "VCC": "5V"})], BUS, "mixed"),
    "two_buses_mixed": ([sensor(), k.mod("U2", "tst_sensor", {"SDA": "SDA1", "SCL": "SCL1", "VDD": "3V3",
                                                              "SDO": "GND"}),
                         _spi("S1", "CS1"), k.mod("G1", "tst_gps", {"VCC": "3V3", "GND": "GND", "TX": "RX1",
                                                                     "RX": "TX1"})],
                        [*BUS, *k.i2c(4, 5, "SDA1"), *SPI_A, *UART_A], None),
    "i2c_level_shifter_to_5v_rtc": ([sensor(), k.mod("L1", "tst_i2cshift", {"VCCA": "3V3", "VCCB": "5V", "GND": "GND",
                                                                         "SDAA": "SDA0", "SCLA": "SCL0",
                                                                         "SDAB": "SDA5", "SCLB": "SCL5"}),
                                     k.mod("U2", "tst_rtc", {"SDA": "SDA5", "SCL": "SCL5", "VCC": "5V"})], BUS, None),
    "multi_pin_expander_consistent": ([pwm("P1", a1="3V3", a0="GND", address="0x42")], BUS, None),
}


@pytest.mark.parametrize("name", sorted(GOOD))
def test_false_alarm_list(name):
    parts, assignments, cat = GOOD[name]
    if cat == "real":
        rep = k.run(catalog=None, electrical=None, assignments=assignments, parts=parts, only=MINE)
    else:
        rep = run(parts, assignments, catalog=_bme_catalog() if cat == "mixed" else None)
    assert [w for w in rep.warnings if w["code"] in MY_CODES] == []
    assert [c["id"] for c in rep.checks if c["status"] == "failed"] == []
    assert "modules.unconnected" in {c["id"] for c in rep.checks}


def test_false_alarm_list_has_ten_projects_with_the_real_bme280():
    assert len(GOOD) >= 10 and sum(v[2] in ("real", "mixed") for v in GOOD.values()) >= 2


def test_real_bme280_conflict_and_open_sdo_cite_the_datasheet():
    rep = k.run(catalog=None, electrical=None, assignments=BUS, parts=[bme("B1"), bme("B2")], only=MINE)
    w = warns(rep, "mod.address_conflict")
    assert w and w[0]["severity"] == "caution" and w[0]["source_ids"] == ["mod-env-bme280-ds"]
    assert "0x77 (SDO to VDDIO)" in w[0]["message"]
    p = bme("B1")
    del p["conn"]["SDO"], p["conn"]["GND"]
    rep = k.run(catalog=None, electrical=None, assignments=BUS, parts=[p], only=MINE)
    assert "SDO must be connected" in warns(rep, "mod.address_select")[0]["message"]
    assert any("GND (gnd) is not connected" in x["message"] for x in warns(rep, "mod.unconnected"))


# --- through pins.check ------------------------------------------------------------------------------------------
def test_pins_check_reports_the_bus_rules(monkeypatch):
    k.patch_runtime(monkeypatch, catalog=CAT, electrical=fx.ESP, sources=fx.SOURCES)
    parts = [pwm(), mux(), k.mod("G1", "tst_gps", {"VCC": "3V3", "GND": "GND", "TX": "TX1", "RX": "RX1"})]
    env = pins.check("esp32s3", [*BUS, *UART_A], parts=parts)
    assert env["ok"] and contracts.validate_envelope(env) == []
    got = {w["code"] for w in env["warnings"]}
    assert {"mod_address_reserved", "mod_pin_role"} <= got
    ids = {c["id"] for c in env["checks"]}
    assert {f"modules.{r[4:]}" for r in MINE if r != "mod.spi_cs"} <= ids
    assert {"tst-sensor-ds", "tst-mux-ds"} <= {s["id"] for s in env["sources"]}


def test_pins_check_good_project_has_no_bus_warnings(monkeypatch):
    k.patch_runtime(monkeypatch, catalog=CAT, electrical=fx.ESP, sources=fx.SOURCES)
    parts, assignments, _ = GOOD["two_buses_mixed"]
    env = pins.check("esp32s3", assignments, parts=copy.deepcopy(parts))
    assert env["ok"] and [w for w in env["warnings"] if w["code"] in MY_CODES] == []
    assert all(c["status"] != "failed" for c in env["checks"] if c["id"].startswith("modules."))


def test_pins_check_real_bme280_runtime():
    env = pins.check("esp32s3", BUS, parts=[bme("B1"), bme("B2", sdo="3V3")], options={})
    assert env["ok"] and [w for w in env["warnings"] if w["code"] in MY_CODES] == []
    env = pins.check("esp32s3", BUS, parts=[bme("B1"), bme("B2")], options={})
    w = [x for x in env["warnings"] if x["code"] == "mod_address_conflict"]
    assert w and w[0]["severity"] == "caution"
    assert "mod-env-bme280-ds" in {s["id"] for s in env["sources"]}
