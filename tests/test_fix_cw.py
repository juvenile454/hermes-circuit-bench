"""Friction points from a probe with a real model in calculators, schematic and solder plan (synthetic data only).

1. i2c_pullup without c_bus: estimate from devices/project (C_i 10 pF, UM10204 Table 10) + 50 pF wires (rule of thumb)
2. ldo part: catalog module ids are aliases of the part records; partial parts and unknown names give a clear hint
3. divider adc_range: "0-2.9V" works, an attenuation is refused with the format in the hint
4. schematic netlist: several GPIOs / drivers / bus signals on one net fail schematic.netlist with a warning
5. schematic: gpios as a list -> hint with example; module outputs are a net label or NC, never a GPIO placeholder;
   pull-up values from the project (resistor parts, stored i2c_pullup calculation)
6. solder plan: kind ceramic given -> no "type guessed"; catalog modules stored as ic get a breakout hint
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

from circuit_bench.bench_core import calc, calc_power, calckit, parts, schematic, solder, wiring

pytest.importorskip("schemdraw")

EXCERPT = Path(__file__).parent / "corpus" / "excerpts" / "calc-nxp-um10204.txt"


# --------------------------------------------------------------------------- 1. i2c_pullup without c_bus

def test_c_i_value_is_in_the_pinned_excerpt():
    text = EXCERPT.read_text(encoding="utf-8")
    assert re.search(r"Ci capacitance for each I/O pin\[10\] - 10 - 10 - 10 pF", text)
    assert calc.I2C_C_PIN_MAX == 10e-12


def test_i2c_without_c_bus_estimates_with_assumption_and_info():
    env = calc.i2c_pullup("3V3", mode="fast")
    assert env["ok"], env
    cb = env["result"]["inputs"]["c_bus"]
    assert cb["estimated"] is True and cb["value"] == pytest.approx(2 * 10e-12 + 50e-12)
    a = {x["key"]: x for x in env["assumptions"]}
    assert "estimated" in a["c_bus"]["value"]
    assert "UM10204 Table 10" in a["c_bus"]["reason"] and "rule of thumb" in a["c_bus"]["reason"]
    assert "not a datasheet value" in a["c_bus"]["reason"]
    assert a["devices"]["value"] == "1"
    w = next(w for w in env["warnings"] if w["code"] == "c_bus_estimated")
    assert w["severity"] == "info" and "measure or give c_bus for long wires" in w["message"]
    assert {s["id"] for s in env["sources"]} >= {"nxp-um10204", "rule-of-thumb"}
    assert "(estimated)" in env["summary"]


def test_i2c_devices_count_and_given_c_bus_unchanged():
    env = calc.i2c_pullup("3V3", devices=3)
    assert env["result"]["inputs"]["c_bus"]["value"] == pytest.approx(4 * 10e-12 + 50e-12)
    given = calc.i2c_pullup("3V3", "100p")
    assert given["ok"] and "estimated" not in given["result"]["inputs"]["c_bus"]
    assert not any(w["code"] == "c_bus_estimated" for w in given["warnings"])
    bad = calc.i2c_pullup("3V3", devices="2.5")
    assert not bad["ok"] and bad["error"]["code"] == "invalid_args"


def test_i2c_from_project_counts_i2c_modules(monkeypatch):
    from circuit_bench.bench_core import project as P
    proj = {"parts": [{"ref": "U1", "kind": "ic", "value": "SSD1306", "module": "ssd1306"},
                      {"ref": "U2", "kind": "ic", "value": "BME280", "module": "bme280"},
                      {"ref": "R1", "kind": "resistor", "value": "4k7"}]}
    monkeypatch.setattr(P, "get", lambda pid: {"ok": True, "result": {"project": proj, "rev": 1}})
    env = calc.i2c_pullup("3V3", project="p1")
    assert env["ok"], env
    assert env["result"]["inputs"]["c_bus"]["value"] == pytest.approx(3 * 10e-12 + 50e-12)
    dev = next(a for a in env["assumptions"] if a["key"] == "devices")
    assert dev["value"] == "2" and "U1, U2" in dev["reason"]


def test_i2c_c_bus_is_optional_in_the_registry():
    spec = {name: req for name, _u, req, _d in calckit.params("i2c_pullup")}
    assert spec["c_bus"] is False and "devices" in spec and "project" in spec
    env = calckit.run("i2c_pullup", {"v_dd": "3.3V"})
    assert env["ok"]


# --------------------------------------------------------------------------- 2. ldo part aliases

@pytest.mark.parametrize("alias, pid", [("mcp1700", "MCP1700-3302E/TT"), ("ap2112k_33", "AP2112K-3.3"),
                                        ("tlv75533p", "TLV75533PDBVR")])
def test_ldo_catalog_ids_are_aliases(alias, pid):
    env = calc_power.ldo("5V", "3V3", "100mA", part=alias)
    assert env["ok"] and env["result"]["part"]["id"] == pid
    assert not any(w["code"] == "part_unknown" for w in env["warnings"])


@pytest.mark.parametrize("alias, pid", [("xc6206", "XC6206P332MR"), ("me6211", "ME6211C33M5G-N"), ("ht7333", "HT7333-A")])
def test_ldo_partial_parts_say_what_is_missing(alias, pid):
    rec = parts.find(alias)
    assert rec is not None and rec["id"] == pid  # the alias resolves (record kind ldo_partial)
    env = calc_power.ldo("5V", "3V3", "100mA", part=alias)
    w = next(w for w in env["warnings"] if w["code"] == "part_unknown")
    assert pid in w["message"] and "partial" in w["message"] and "mcp1700" in w["message"]


def test_ldo_unknown_part_lists_valid_values():
    env = calc_power.ldo("5V", "3V3", "100mA", part="LM1117")
    w = next(w for w in env["warnings"] if w["code"] == "part_unknown")
    assert "known:" in w["message"] and "MCP1700-3302E/TT (mcp1700)" in w["message"]


# --------------------------------------------------------------------------- 3. divider adc_range

@pytest.mark.parametrize("rng, hi", [("0-2.45V", 2.45), ("0..3.1 V", 3.1), ("0 to 2500mV", 2.5), ([0, 2.9], 2.9),
                                     ("2.9V", 2.9), ({"min": 0.1, "max": 2.9}, 2.9)])
def test_divider_adc_range_forms(rng, hi):
    env = calc.divider("4.2V", "100k", "100k", adc_range=rng)
    assert env["ok"], env
    assert env["result"]["adc"]["max"]["value"] == pytest.approx(hi)


@pytest.mark.parametrize("rng", ["12dB", "ADC_ATTEN_DB_12", {"chip": "esp32c3", "atten": "12dB"}, "abc"])
def test_divider_adc_range_errors_show_the_format(rng):
    env = calc.divider("4.2V", "100k", "100k", adc_range=rng)
    assert not env["ok"] and env["error"]["code"] == "invalid_args"
    assert "[0, 2.9]" in env["error"]["hint"] and "0-2.9V" in env["error"]["hint"]


def test_divider_list_names_the_format():
    entry = next(c for c in calckit.listing(compact=True)["result"]["calculators"] if c["kind"] == "divider")
    assert "[min, max] in V" in entry["summary"]
    env = calc.divider("4.2V", "100k", "100k")
    assert "[min, max] in V" in env["checks"][0]["detail"]


# --------------------------------------------------------------------------- 4. netlist: shorts

def _lora_project(net_per_signal: bool) -> dict:
    roles = [("LORA_NSS", "spi_cs", 5), ("LORA_SCK", "spi_sck", 10), ("LORA_MOSI", "spi_mosi", 7),
             ("LORA_MISO", "spi_miso", 6)]
    conn = {"GND": "GND", "3.3V": "3V3", "NSS": "GPIO5", "SCK": "GPIO10", "MOSI": "GPIO7", "MISO": "GPIO6",
            "RESET": "GPIO4", "DIO0": "GPIO3"}
    return {"id": "syn-lora", "board": {"chip": "esp32c3", "devkit": "esp32-c3-devkitm-1"},
            "assignments": [{"role": r, "mode": m, "pin": n, "net": (r if net_per_signal else "spi_lora")}
                            for r, m, n in roles],
            "parts": [{"ref": "U2", "kind": "module", "value": "RFM95W", "module": "rfm95w", "conn": conn}]}


def test_spi_lines_on_one_net_fail_the_netlist_check():
    env = schematic.render("module", {}, project=_lora_project(False), part="U2",
                           devkit="esp32-c3-devkitm-1")
    assert env["ok"], env
    chk = next(c for c in env["checks"] if c["id"] == "schematic.netlist")
    assert chk["status"] == "failed" and "GPIO5, GPIO6, GPIO7, GPIO10 on one net (spi_lora)" in chk["detail"]
    w = next(w for w in env["warnings"] if w["code"] == "net_short")
    assert w["severity"] == "danger" and "GPIO5" in w["message"] and "GPIO10" in w["message"]


def test_spi_lines_on_own_nets_pass():
    env = schematic.render("module", {}, project=_lora_project(True), part="U2", devkit="esp32-c3-devkitm-1")
    chk = next(c for c in env["checks"] if c["id"] == "schematic.netlist")
    assert chk["status"] == "passed" and not any(w["code"] == "net_short" for w in env["warnings"])


def test_two_bus_signals_on_one_net_without_gpio():
    env = schematic.render("module", {"module": "bme280", "conn": {"SDI": "BUS", "SCK": "BUS"}})
    chk = next(c for c in env["checks"] if c["id"] == "schematic.netlist")
    assert chk["status"] == "failed" and "U1.SDI" in chk["detail"] and "U1.SCK" in chk["detail"]
    assert next(w for w in env["warnings"] if w["code"] == "net_short")["severity"] == "caution"


def test_two_push_pull_outputs_on_one_net():
    # a synthetic push-pull output on a net that another project part (U1.1Y, push-pull) drives as well
    plan = wiring.module_plan(
        {"id": "syn", "source_ids": ["s"], "pins": [
            {"name": "Y", "signal": "digital_out", "output": "push_pull"},
            {"name": "VCC", "signal": "supply"}, {"name": "GND", "signal": "gnd"}],
         "supplies": {"VCC": {"min": 3.0, "max": 5.5}}},
        devkit=None, ref="U5", conn={"Y": "LED_DIN"}, driven={"LED_DIN": ("U1.1Y", True)})
    assert plan.shorts == [("LED_DIN", ["U5.Y", "U1.1Y"], "danger")]


# --------------------------------------------------------------------------- 5. schematic details

def test_gpios_as_list_gives_example():
    env = schematic.render("level_shifter", {"gpios": [2, 1]})
    assert not env["ok"] and '{"LV1": 2, "LV2": 1}' in env["error"]["hint"]
    env = schematic.render("module", {"module": "bme280", "gpios": [8, 9]})
    assert not env["ok"] and '{"SDA": 8, "SCL": 9}' in env["error"]["hint"]


def _strip_project() -> dict:
    return {"id": "syn-strip", "board": {"chip": "esp32s3", "devkit": "esp32-s3-devkitc-1"},
            "options": {"rails": {"VLED": 5}},
            "assignments": [{"role": "LED_DATA", "mode": "out", "pin": 4, "net": "LED_DATA"}],
            "parts": [{"ref": "U1", "kind": "ic", "value": "SN74AHCT125", "module": "sn74ahct125",
                       "conn": {"VCC": "VLED", "GND": "GND", "1OE": "GND", "1A": "GPIO4", "1Y": "LED_DIN",
                                "2OE": "GND", "2A": "GND", "3OE": "GND", "3A": "GND", "4OE": "GND", "4A": "GND"}},
                      {"ref": "LED1", "kind": "ic", "value": "WS2812B", "module": "ws2812b",
                       "conn": {"VDD": "VLED", "VSS": "GND", "DIN": "LED_DIN"}}]}


def test_module_outputs_are_nets_or_nc_never_gpio():
    env = schematic.render("module", {}, project=_strip_project(), part="U1")
    assert env["ok"], env
    nets = {n["name"]: n["nodes"] for n in env["result"]["nets"]}
    assert nets["LED_DIN"] == ["LED_DIN", "U1.1Y"]  # a net label, no GPIO_ placeholder
    assert not any(node.startswith("GPIO_") for nodes in nets.values() for node in nodes)
    assert not any(w["code"] == "gpio_unassigned" for w in env["warnings"])
    nc = next(a for a in env["assumptions"] if a["key"] == "nc_outputs")
    assert nc["value"] == "2Y, 3Y, 4Y"
    assert env["result"]["labels"].count("NC") == 3
    assert next(c for c in env["checks"] if c["id"] == "schematic.netlist")["status"] == "passed"
    assert all(c["status"] == "passed" for c in env["checks"])


def test_input_fed_by_a_module_output_is_no_gpio_placeholder():
    env = schematic.render("module", {}, project=_strip_project(), part="LED1")
    assert env["ok"], env
    assert not any(w["code"] == "gpio_unassigned" for w in env["warnings"])
    a = next(a for a in env["assumptions"] if a["key"] == "LED1.DIN")
    assert "U1.1Y" in a["reason"]


def _i2c_project(with_resistors: bool) -> dict:
    proj = {"id": "syn-i2c", "board": {"chip": "esp32s3", "devkit": "esp32-s3-devkitc-1"},
            "assignments": [{"role": "I2C_SDA", "mode": "i2c_sda", "pin": 2, "net": "I2C_SDA"},
                            {"role": "I2C_SCL", "mode": "i2c_scl", "pin": 1, "net": "I2C_SCL"}],
            "parts": [{"ref": "U1", "kind": "ic", "value": "SSD1306", "module": "ssd1306",
                       "conn": {"VDD": "3V3", "GND": "GND", "SCL": "I2C_SCL", "SDA": "I2C_SDA", "SA0": "GND"}}],
            "calcs": [{"id": "i2c_pullup-1", "type": "i2c_pullup", "inputs": {},
                       "result": {"suggested": {"value": 2200.0, "unit": "Ω", "display": "2.20 kΩ"}}}]}
    if with_resistors:
        proj["parts"] += [{"ref": "R1", "kind": "resistor", "value": "1k8", "conn": {"1": "I2C_SDA", "2": "3V3"}},
                          {"ref": "R2", "kind": "resistor", "value": "1k8", "conn": {"1": "I2C_SCL", "2": "3V3"}}]
    return proj


def test_pullups_take_the_stored_calculation():
    env = schematic.render("module", {}, project=_i2c_project(False), part="U1")
    vals = {p["ref"]: p["value"] for p in env["result"]["parts"] if p["kind"] == "resistor"}
    assert vals and set(vals.values()) == {"2.2 kΩ"}
    a = next(a for a in env["assumptions"] if a["key"] == "R1")
    assert "i2c_pullup-1" in a["reason"]


def test_pullups_of_the_project_resistors_are_not_drawn_again():
    # one set of pull-ups per bus; the project's R1/R2 already pull SDA/SCL up
    env = schematic.render("module", {}, project=_i2c_project(True), part="U1")
    assert not [p for p in env["result"]["parts"] if p["kind"] == "resistor"]
    a = {x["key"]: x for x in env["assumptions"]}
    assert a["pullup.I2C_SDA"]["value"] == "present" and "project part R1 (1k8)" in a["pullup.I2C_SDA"]["reason"]
    assert "project part R2" in a["pullup.I2C_SCL"]["reason"]


def test_r_pullup_param_still_wins():
    env = schematic.render("module", {"r_pullup": "4k7"}, project=_i2c_project(False), part="U1")
    vals = {p["value"] for p in env["result"]["parts"] if p["kind"] == "resistor"}
    assert vals == {"4.7 kΩ"}


# --------------------------------------------------------------------------- 6. solder plan

def test_given_ceramic_is_not_guessed():
    env = solder.plan([{"ref": "C1", "kind": "ceramic", "value": "100nF"}, {"ref": "C2", "value": "100nF"}])
    step = next(s for s in env["result"]["steps"] if s["kind"] == "ceramic")
    hint = next(h for h in step["hints"] if h["code"] == "kind_by_value")
    assert hint["text"].startswith("C2:")
    a = next(a for a in env["assumptions"] if a["key"] == "capacitor_type")
    assert a["value"] == "C2: ceramic"
    only = solder.plan([{"ref": "C1", "kind": "ceramic", "value": "100nF"}])
    assert not any(h["code"] == "kind_by_value" for s in only["result"]["steps"] for h in s["hints"])
    assert "capacitor_type" not in {a["key"] for a in only["assumptions"]}


def test_module_parts_solder_last_on_headers():
    env = solder.plan([{"ref": "U2", "kind": "module", "value": "DevKit"},
                       {"ref": "R1", "kind": "resistor", "value": "10k"}])
    steps = env["result"]["steps"]
    assert steps[-1]["kind"] == "module" and "headers" in steps[-1]["action"]
    assert not any(h["code"] == "socket" for h in steps[-1]["hints"])


def test_catalog_ic_gets_breakout_hint():
    env = solder.plan([{"ref": "U1", "kind": "ic", "value": "A4988", "module": "a4988"},
                       {"ref": "U3", "kind": "ic", "value": "NE555"}])
    step = next(s for s in env["result"]["steps"] if s["kind"] == "ic")
    h = next(h for h in step["hints"] if h["code"] == "catalog_module")
    assert h["severity"] == "info" and "U1 (a4988)" in h["text"] and "U3" not in h["text"]
    assert "on headers" in h["text"]


def test_bom_parse_unchanged_shape():
    from circuit_bench.bench_core import bom
    rows = [{"ref": "C1", "kind": "ceramic", "value": "100nF", "module": "x"}]
    assert bom.parse(rows) == [{"ref": "C1", "value": "100nF", "kind": "ceramic", "package": None, "qty": 1}]
    parts_, basis, mods = bom.parse_detail(rows)
    assert basis == {"C1": "given"} and mods == {"C1": "x"}
    assert copy.deepcopy(parts_) == bom.parse(rows)


def test_module_conn_role_names_resolve_like_the_checks():
    """A conn value that names a role sits on that assignment's net (modcheck._Resolver.roles)."""
    from circuit_bench.bench_core import schematic
    proj = {"assignments": [{"role": "STEP", "mode": "out", "pin": 4}, {"role": "DIR", "mode": "out", "pin": 2,
                                                                       "net": "DIR_NET"},
                            {"role": "SDA", "mode": "i2c_sda", "pin": 8, "net": "SDA"}]}
    assert schematic._role_nets(proj) == {"STEP": "GPIO4", "DIR": "DIR_NET"}  # SDA is a net name: stays a net
