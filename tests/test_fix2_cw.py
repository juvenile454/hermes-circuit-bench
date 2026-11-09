"""Schematic and solder findings of a second probe with a real model (synthetic data only).

1. a single gpio/role never lands on a module output or a pin the part's conn already wires; a GPIO that drives
   a net with a push-pull module output fails schematic.netlist (net_short, danger)
2. facts.onboard (user-confirmed): decoupling, pull-ups and the reset RC are not drawn, but named "on the board"
3. pull-ups once per bus (project resistors, boards with pull-ups, the schematic stored first); refs of drawn parts
   never collide with project parts, and are numbered per sheet with two or more module parts
4. a breakout variant (kind module) of a bare chip does not draw the chip's supply/battery tie (ZS-042 VBAT)
5. solder plan: LED strips get a wiring step, catalog modules without header data no female-header advice, cells
   without a BT ref still get the battery step
6. divider: the project's resistors on the ADC net give the input net, the values and the refs
"""
from __future__ import annotations

import copy

import pytest

from circuit_bench.bench_core import bom, schematic, solder, wiring

pytest.importorskip("schemdraw")

DEVKIT_S3 = {"chip": "esp32s3", "devkit": "esp32-s3-devkitc-1"}


def _nets(env: dict) -> dict[str, list[str]]:
    return {n["name"]: n["nodes"] for n in env["result"]["nets"]}


def _assumed(env: dict) -> dict[str, dict]:
    return {a["key"]: a for a in env["assumptions"]}


def _netlist(env: dict) -> dict:
    return next(c for c in env["checks"] if c["id"] == "schematic.netlist")


# --------------------------------------------------------------------------- 1. output against GPIO

def _buffer_project(conn_extra: dict | None = None) -> dict:
    """The probe case: 74AHCT125 channel 1 shifts LED_DATA, channels 2-4 have A and OE at GND (outputs drive low)."""
    conn = {"VCC": "V5_LED", "GND": "GND", "1A": "LED_DATA_3V3", "1Y": "LED_DATA_5V", "1OE": "GND",
            "2A": "GND", "2OE": "GND", "3A": "GND", "3OE": "GND", "4A": "GND", "4OE": "GND", **(conn_extra or {})}
    return {"id": "syn-buf", "board": DEVKIT_S3, "options": {"rails": {"V5_LED": 5.0}},
            "assignments": [{"role": "LED_DATA", "mode": "out", "pin": 4, "net": "LED_DATA_3V3"}],
            "parts": [{"ref": "U1", "kind": "ic", "value": "SN74AHCT125", "module": "sn74ahct125", "conn": conn}]}


def test_role_is_not_mapped_onto_a_free_output():
    env = schematic.render("module", {}, project=_buffer_project(), part="U1", role="LED_DATA")
    assert env["ok"], env
    nets = _nets(env)
    assert nets["LED_DATA_3V3"] == ["J1-4", "U1.1A"]  # 2Y (driving low) is not put on the GPIO net
    assert _netlist(env)["status"] == "passed"
    assert "2Y" in _assumed(env)["nc_outputs"]["value"]
    assert "already puts LED_DATA_3V3 on its pin" in _assumed(env)["gpio"]["reason"]


def test_single_gpio_takes_the_first_free_input_not_an_output():
    env = schematic.render("module", {"module": "ds3231"}, gpio=5)  # pins: 32KHZ, VCC, INT/SQW, RST, …, SDA
    assert env["ok"], env
    nodes = {node for ns in _nets(env).values() for node in ns}
    assert "U1.SDA" in next(ns for name, ns in _nets(env).items() if "GPIO5" in ns)
    assert "U1.32KHZ" not in nodes or not any("GPIO5" in ns and "U1.32KHZ" in ns for ns in _nets(env).values())


def test_no_free_input_names_params_gpios():
    conn = {f"{i}{q}": "GND" for i in range(1, 5) for q in ("A", "OE")}
    env = schematic.render("module", {"module": "sn74ahct125", "conn": conn}, gpio=4)
    assert not env["ok"] and "no free input pin" in env["error"]["message"]
    assert "params.gpios" in env["error"]["hint"]


def test_gpio_driving_a_push_pull_output_fails_the_netlist():
    env = schematic.render("module", {}, project=_buffer_project({"2Y": "LED_DATA_3V3"}), part="U1",
                           role="LED_DATA")
    assert env["ok"], env
    chk = _netlist(env)
    assert chk["status"] == "failed" and "GPIO4, U1.2Y on one net (LED_DATA_3V3)" in chk["detail"]
    w = next(w for w in env["warnings"] if w["code"] == "net_short")
    assert w["severity"] == "danger" and "U1.2Y" in w["message"]


def test_push_pull_reads_io_outputs_like_the_rules():
    assert wiring.push_pull({"signal": "digital_out"}, {"outputs": "push_pull"})
    assert not wiring.push_pull({"signal": "digital_out", "output": "tristate"}, {"outputs": "push_pull"})
    assert not wiring.push_pull({"signal": "open_drain_out"}, {"outputs": "push_pull"})
    assert not wiring.push_pull({"signal": "digital_in"}, {"outputs": "push_pull"})
    assert not wiring.push_pull({"signal": "digital_out"}, None)


def test_driven_net_of_another_part_counts_io_outputs():
    proj = _buffer_project()
    proj["parts"].append({"ref": "U2", "kind": "ic", "value": "SN74AHCT125", "module": "sn74ahct125",
                          "conn": {"VCC": "V5_LED", "GND": "GND", "1A": "X", "1Y": "LED_DATA_3V3"}})
    assert schematic._driven(proj, "U1")["LED_DATA_3V3"] == ("U2.1Y", True)


# --------------------------------------------------------------------------- 2. facts.onboard

def _onboard_project(onboard: list[str], pullups: str = "unknown") -> dict:
    return {"id": "syn-onb", "board": DEVKIT_S3,
            "assignments": [{"role": "I2C_SDA", "mode": "i2c_sda", "pin": 2, "net": "I2C_SDA"},
                            {"role": "I2C_SCL", "mode": "i2c_scl", "pin": 1, "net": "I2C_SCL"}],
            "parts": [{"ref": "U1", "kind": "module", "value": "BME280", "module": "bme280",
                       "conn": {"VDD": "3V3", "VDDIO": "3V3", "GND": "GND", "SCK": "I2C_SCL", "SDI": "I2C_SDA",
                                "CSB": "3V3", "SDO": "GND"},
                       "facts": {"pullups": pullups, "onboard": onboard}}]}


def test_onboard_decoupling_and_pullups_are_not_drawn():
    bare = schematic.render("module", {}, project=_onboard_project([]), part="U1")
    assert {p["kind"] for p in bare["result"]["parts"]} >= {"resistor", "capacitor"} or \
        any(p["ref"].startswith("C") for p in bare["result"]["parts"])
    env = schematic.render("module", {}, project=_onboard_project(["decoupling", "pullups"]), part="U1")
    assert env["ok"], env
    assert [p["ref"] for p in env["result"]["parts"]] == ["U1"]
    a = _assumed(env)
    assert a["U1.decoupling"]["value"] == "on the board (user-confirmed)"
    assert a["pullups"]["value"] == "on the board (user-confirmed)"
    assert _netlist(env)["status"] == "passed"


def test_pullups_value_in_facts_is_kept_as_value():
    env = schematic.render("module", {}, project=_onboard_project([], pullups="10k"), part="U1")
    a = _assumed(env)
    assert a["pullups"]["value"] == "10k" and "user-confirmed" in a["pullups"]["reason"]
    assert not [p for p in env["result"]["parts"] if p["kind"] == "resistor"]


def test_unknown_board_pullups_say_measure_first():
    env = schematic.render("module", {}, project=_onboard_project([]), part="U1")
    assert "measure" in _assumed(env)["pullups"]["reason"]


def _oled_project(onboard: list[str]) -> dict:
    return {"id": "syn-oled", "board": DEVKIT_S3,
            "assignments": [{"role": "I2C_SDA", "mode": "i2c_sda", "pin": 2, "net": "I2C_SDA"},
                            {"role": "I2C_SCL", "mode": "i2c_scl", "pin": 1, "net": "I2C_SCL"}],
            "parts": [{"ref": "U1", "kind": "module", "value": "SSD1306", "module": "ssd1306",
                       "conn": {"VDD": "3V3", "GND": "GND", "SCL": "I2C_SCL", "SDA": "I2C_SDA", "SA0": "GND"},
                       "facts": {"pullups": "10k", "onboard": onboard}}]}


def test_onboard_reset_rc_is_no_gpio_placeholder():
    without = schematic.render("module", {}, project=_oled_project([]), part="U1")
    assert any("U1.RES" in ns for ns in _nets(without).values())
    env = schematic.render("module", {}, project=_oled_project(["reset_rc"]), part="U1")
    assert env["ok"], env
    assert not any("U1.RES" in ns for ns in _nets(env).values())
    assert not any(w["code"] == "gpio_unassigned" for w in env["warnings"])
    a = _assumed(env)["U1.RES"]
    assert a["value"] == "on the board (user-confirmed)" and "reset_rc" in a["reason"]


def test_reset_in_conn_still_wins_over_reset_rc():
    proj = _oled_project(["reset_rc"])
    proj["parts"][0]["conn"]["RES"] = "OLED_RST"
    env = schematic.render("module", {}, project=proj, part="U1")
    assert any("U1.RES" in ns for ns in _nets(env).values())


# --------------------------------------------------------------------------- 3. pull-ups per bus, unique refs

def _bus_project(circuits: list[str], u2_facts: dict | None = None) -> dict:
    proj = _onboard_project([])
    proj["parts"].append({"ref": "U2", "kind": "module", "value": "SSD1306", "module": "ssd1306",
                          "conn": {"VDD": "3V3", "GND": "GND", "SCL": "I2C_SCL", "SDA": "I2C_SDA", "SA0": "GND",
                                   "RES": "3V3"},
                          "facts": u2_facts or {"pullups": "unknown"}})
    proj["parts"].append({"ref": "C1", "kind": "ceramic", "value": "10uF"})
    proj["circuits"] = [{"id": f"module-{r.lower()}", "block": "module", "params": {"part": r},
                         "svg": f"artifacts/module-{r.lower()}.svg"} for r in circuits]
    return proj


def test_pullups_are_drawn_once_per_bus():
    proj = _bus_project(["U1"])
    u1 = schematic.render("module", {}, project=proj, part="U1")
    u2 = schematic.render("module", {}, project=proj, part="U2")
    assert u1["ok"] and u2["ok"], (u1, u2)
    r1 = [p["ref"] for p in u1["result"]["parts"] if p["kind"] == "resistor"]
    r2 = [p["ref"] for p in u2["result"]["parts"] if p["kind"] == "resistor"]
    assert len(r1) == 2 and r2 == []
    a = _assumed(u2)
    assert a["pullup.I2C_SDA"]["value"] == "present" and "schematic of U1" in a["pullup.I2C_SDA"]["reason"]


def test_without_stored_schematics_each_draws_and_the_first_stored_keeps_them():
    proj = _bus_project([])
    assert [p for p in schematic.render("module", {}, project=proj, part="U2")["result"]["parts"]
            if p["kind"] == "resistor"]
    proj = _bus_project(["U2", "U1"])  # U2 stored first: U2 keeps the pull-ups, U1 leaves them out
    u1 = schematic.render("module", {}, project=proj, part="U1")
    u2 = schematic.render("module", {}, project=proj, part="U2")
    assert not [p for p in u1["result"]["parts"] if p["kind"] == "resistor"]
    assert len([p for p in u2["result"]["parts"] if p["kind"] == "resistor"]) == 2


def test_board_pullups_of_another_part_count():
    proj = _bus_project([], u2_facts={"pullups": "4k7"})
    env = schematic.render("module", {}, project=proj, part="U1")
    assert not [p for p in env["result"]["parts"] if p["kind"] == "resistor"]
    assert "on the board of U2" in _assumed(env)["pullup.I2C_SCL"]["reason"]


def test_refs_are_unique_across_sheets_and_project_parts():
    proj = _bus_project([])
    refs = {}
    for part in ("U1", "U2"):
        env = schematic.render("module", {}, project=proj, part=part)
        refs[part] = [p["ref"] for p in env["result"]["parts"] if p["ref"] != part]
        assert "proposed refs" in _assumed(env)["refs"]["reason"]
    assert all(r[1] == "1" for r in refs["U1"]) and all(r[1] == "2" for r in refs["U2"]), refs
    assert not set(refs["U1"]) & set(refs["U2"])
    assert not {"C1"} & (set(refs["U1"]) | set(refs["U2"]))


def test_single_module_skips_taken_project_refs():
    proj = _onboard_project([])
    proj["parts"].append({"ref": "C1", "kind": "ceramic", "value": "100nF"})
    env = schematic.render("module", {}, project=proj, part="U1")
    caps = [p["ref"] for p in env["result"]["parts"] if p["ref"].startswith("C")]
    assert caps and "C1" not in caps and caps[0] == "C2"


def test_standalone_refs_unchanged():
    env = schematic.render("module", {"module": "bme280"})
    assert {p["ref"] for p in env["result"]["parts"]} >= {"U1", "R1", "C1"}
    assert "refs" not in _assumed(env)


# --------------------------------------------------------------------------- 4. variant ties

def _rtc_project(variant: str | None) -> dict:
    part = {"ref": "U1", "kind": "module", "value": "DS3231", "module": "ds3231",
            "conn": {"VCC": "3V3", "GND": "GND", "SDA": "I2C_SDA", "SCL": "I2C_SCL"}}
    if variant:
        part["variant"] = variant
    return {"id": "syn-rtc", "board": {"chip": "esp32", "devkit": "esp32-devkitc-v4"},
            "assignments": [{"role": "I2C_SDA", "mode": "i2c_sda", "pin": 21, "net": "I2C_SDA"},
                            {"role": "I2C_SCL", "mode": "i2c_scl", "pin": 22, "net": "I2C_SCL"}],
            "parts": [part]}


def test_zs042_does_not_tie_vbat_to_gnd():
    env = schematic.render("module", {}, project=_rtc_project("zs042"), part="U1")
    assert env["ok"], env
    assert not any("U1.VBAT" in ns for ns in _nets(env).values())
    a = _assumed(env)["U1.VBAT"]
    assert a["value"] == "on the board" and "coin-cell holder" in a["reason"] and "zs042" in a["reason"]


def test_bare_chip_keeps_its_vbat_tie():
    env = schematic.render("module", {}, project=_rtc_project(None), part="U1")
    assert "U1.VBAT" in _nets(env)["GND"]


def test_explicit_vbat_conn_wins_on_the_variant():
    proj = _rtc_project("zs042")
    proj["parts"][0]["conn"]["VBAT"] = "VBACKUP"
    env = schematic.render("module", {}, project=proj, part="U1")
    assert "U1.VBAT" in _nets(env)["VBACKUP"]


def test_variant_with_own_pins_decides_itself():
    from circuit_bench.bench_core import modules
    e = modules.catalog().get("tp4056", "module-dw01")
    assert schematic._variant_board_pins(e, "tp4056", "module-dw01") == {}


# --------------------------------------------------------------------------- 5. solder plan

def _strip_rows() -> list[dict]:
    return [{"ref": "U1", "kind": "ic", "value": "SN74AHCT125", "module": "sn74ahct125"},
            {"ref": "LED1", "kind": "ic", "value": "WS2812B", "qty": 60, "module": "ws2812b"},
            {"ref": "C1", "kind": "ceramic", "value": "100nF"}]


def test_led_strip_gets_a_wiring_step():
    env = solder.plan(_strip_rows())
    assert env["ok"], env
    steps = env["result"]["steps"]
    strip = next(s for s in steps if s["refs"] == ["LED1"])
    assert strip["kind"] == "led"
    assert strip["action"] == "Wire the LED strip LED1 (WS2812B, 60 LEDs) at its input end: 3 wires (VDD, VSS, DIN)."
    assert {h["code"] for h in strip["hints"]} == {"data_direction", "strip_supply"}
    ic = next(s for s in steps if s["kind"] == "ic")
    assert ic["refs"] == ["U1"]
    assert all(h["source_ids"] for h in strip["hints"])


def test_single_addressable_led_stays_a_part():
    rows = _strip_rows()
    rows[1]["qty"] = 1
    steps = solder.plan(rows)["result"]["steps"]
    assert next(s for s in steps if s["kind"] == "ic")["refs"] == ["LED1", "U1"]


def test_strip_wires_use_the_conn_when_rows_carry_it():
    rows = _strip_rows()
    rows[1]["conn"] = {"VDD": "V5_LED", "VSS": "GND", "DIN": "LED_DATA_5V"}
    strip = next(s for s in solder.plan(rows)["result"]["steps"] if s["refs"] == ["LED1"])
    assert "(VDD to V5_LED, VSS to GND, DIN to LED_DATA_5V)" in strip["action"]


def test_catalog_module_without_header_data_gets_neutral_text():
    env = solder.plan([{"ref": "U2", "kind": "module", "value": "RFM95W", "module": "rfm95w"},
                       {"ref": "U3", "kind": "module", "value": "TP4056", "module": "tp4056"}])
    step = next(s for s in env["result"]["steps"] if s["kind"] == "module")
    assert "female headers" not in step["action"] and "pin headers or solder pads" in step["action"]
    codes = {h["code"]: h for h in step["hints"]}
    assert codes["mount_unknown"]["text"].startswith("U2:")
    assert codes["mechanical"]["text"].startswith("U3:")  # tp4056 data names its header
    only = solder.plan([{"ref": "U2", "kind": "module", "value": "RFM95W", "module": "rfm95w"}])
    step = only["result"]["steps"][0]
    assert not any(h["code"] == "mechanical" for h in step["hints"])


@pytest.mark.parametrize("row", [{"ref": "B1", "value": "18650 Li-Ion cell"},
                                 {"ref": "X9", "kind": "cell", "value": "LiPo 1S"},
                                 {"ref": "BT1", "value": "CR2032"}])
def test_cells_get_their_own_polarity_step(row):
    env = solder.plan([row, {"ref": "R1", "value": "10k"}])
    step = next(s for s in env["result"]["steps"] if s["refs"] == [row["ref"]])
    assert step["kind"] == "battery"
    assert {"polarity", "battery_safety"} <= {h["code"] for h in step["hints"]}
    assert env["result"]["steps"][-1] is step or env["result"]["steps"][-1]["refs"] == [row["ref"]]


def test_bom_parse_shape_unchanged_for_cells():
    assert bom.parse([{"ref": "B1", "value": "18650 cell"}]) == [
        {"ref": "B1", "value": "18650 cell", "kind": "battery", "package": None, "qty": 1}]


# --------------------------------------------------------------------------- 6. divider from the project

def _divider_project() -> dict:
    return {"id": "syn-div", "board": {"chip": "esp32c3", "devkit": "esp32-c3-devkitm-1"},
            "options": {"rails": {"VBAT": 4.2}},
            "assignments": [{"role": "VBAT_SENSE", "mode": "adc", "pin": 0, "net": "VBAT_SENSE"}],
            "parts": [{"ref": "R5", "kind": "resistor", "value": "100k", "conn": {"1": "VBAT", "2": "VBAT_SENSE"}},
                      {"ref": "R6", "kind": "resistor", "value": "47k", "conn": {"1": "VBAT_SENSE", "2": "GND"}}]}


def test_divider_uses_the_project_nets_values_and_refs():
    env = schematic.render("divider", {}, project=_divider_project(), role="VBAT_SENSE")
    assert env["ok"], env
    nets = _nets(env)
    assert "VIN" not in nets and nets["VBAT"][1] == "R5.1" and "R6.1" in nets["VBAT_SENSE"]
    assert {p["ref"]: p["value"] for p in env["result"]["parts"] if p["kind"] == "resistor"} == \
        {"R5": "100 kΩ", "R6": "47 kΩ"}
    a = _assumed(env)
    assert a["input_net"]["value"] == "VBAT" and "R5" in a["input_net"]["reason"]


def test_divider_params_still_win():
    env = schematic.render("divider", {"r1": "220k", "input_net": "VIN"}, project=_divider_project(),
                           role="VBAT_SENSE")
    assert env["ok"], env
    refs = {p["ref"] for p in env["result"]["parts"] if p["kind"] == "resistor"}
    assert refs == {"R1", "R2"} and "VIN" in _nets(env)


def test_divider_without_project_unchanged():
    env = schematic.render("divider", {"r1": "100k", "r2": "47k"})
    assert {p["ref"] for p in env["result"]["parts"] if p["kind"] == "resistor"} == {"R1", "R2"}
    assert "VIN" in _nets(env)


def test_inputs_are_not_mutated():
    proj = _bus_project(["U1"])
    before = copy.deepcopy(proj)
    schematic.render("module", {}, project=proj, part="U2")
    assert proj == before
