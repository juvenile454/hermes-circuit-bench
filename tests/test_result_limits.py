"""Results that used to read too positive: divider above the pin limit, pin current above the drive current,
wired discrete parts in a pin check. Answers without a violation stay unchanged."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from circuit_bench.bench_core import calc, electrical, pins, schematic

ROOT = Path(__file__).resolve().parents[1]


def statuses(env):
    return [(c["id"], c["status"]) for c in env["checks"]]


def warnings(env):
    return [(w["code"], w["severity"]) for w in env["warnings"]]


# --- divider ---------------------------------------------------------------------------------------------------

def test_divider_above_the_pin_limit_is_a_danger():
    env = calc.divider("12V", "1k", "10k")
    assert ("calc.divider.pin_max", "failed") in statuses(env)
    assert ("divider_overvoltage", "danger") in warnings(env)
    w = next(w for w in env["warnings"] if w["code"] == "divider_overvoltage")
    limit = electrical.get("esp32s3")
    assert w["source_ids"] == limit["source_ids"] and "10.9 V" in w["message"] and "3.60 V" in w["message"]
    assert next(c for c in env["checks"] if c["id"] == "calc.divider.pin_max")["detail"] == "V_out max 10.9 V > 3.60 V"
    assert any(a["key"] == "pin_limit" for a in env["assumptions"])


@pytest.mark.parametrize("v_in,r1,r2", [("4.2V", "100k", "100k"), ("7.2V", "10k", "10k")])  # 2.1 V and exactly 3.6 V
def test_divider_at_or_below_the_limit_is_unchanged(v_in, r1, r2):
    env = calc.divider(v_in, r1, r2)
    assert [c["id"] for c in env["checks"]] == ["calc.divider.adc_range"] and env["warnings"] == []
    assert all(a["key"] != "pin_limit" for a in env["assumptions"])


def test_divider_schematic_on_a_gpio_fails_the_check():
    env = schematic.render("divider", {"r1": "1k", "r2": "10k", "v_in": "12V"}, gpio=34, devkit="esp32-devkitc-v4")
    assert env["ok"] and ("schematic.divider_vout", "failed") in statuses(env)
    assert ("divider_overvoltage", "danger") in warnings(env)
    w = next(w for w in env["warnings"] if w["code"] == "divider_overvoltage")
    assert "GPIO34" in w["message"] and "10.9 V" in w["message"] and "3.60 V" in w["message"]
    assert ("schematic.netlist", "passed") in statuses(env)


def test_divider_schematic_without_v_in_or_without_gpio_adds_nothing():
    no_vin = schematic.render("divider", {"r1": "1k", "r2": "10k"}, gpio=34, devkit="esp32-devkitc-v4")
    no_gpio = schematic.render("divider", {"r1": "1k", "r2": "10k", "v_in": "12V"})
    ok = schematic.render("divider", {"r1": "10k", "r2": "10k", "v_in": "7.2V"}, gpio=34, devkit="esp32-devkitc-v4")
    for env in (no_vin, no_gpio, ok):
        assert env["ok"]
        assert all(c["id"] != "schematic.divider_vout" for c in env["checks"])
        assert all(w["code"] != "divider_overvoltage" for w in env["warnings"])


# --- pin current -----------------------------------------------------------------------------------------------

def test_pin_current_above_ioh_is_a_caution():
    env = calc.npn("3V3", None, "500mA", part="2N2222A")  # about 55 mA base current
    w = next(w for w in env["warnings"] if w["code"] == "gpio_current")
    assert w["severity"] == "caution" and "40.0 mA" in w["message"] and "mosfet" in w["message"]
    assert w["source_ids"] == electrical.get("esp32s3")["source_ids"]
    assert [c["status"] for c in env["checks"]] == ["passed"] * 3  # the checks themselves stay


def test_pin_current_above_ioh_from_a_led_is_a_caution():
    env = calc.led("3V3", "1.8V", "50mA")
    assert ("gpio_current", "caution") in warnings(env)


def test_pin_current_up_to_ioh_stays_info():
    led = calc.led("3V3", "1.8V", "20mA")
    w = next(w for w in led["warnings"] if w["code"] == "gpio_current")
    assert w["severity"] == "info" and w["message"].startswith("The driving pin sources ")
    assert "below the 40.0 mA high-level source current of an ESP32-S3 pin" in w["message"]
    assert "not checked" not in w["message"]
    assert w["source_ids"] == []
    # exactly 40 mA through the pin: no new line (strict comparison)
    assert calc._gpio_current(0.04)["severity"] == "info"
    assert ", at the 40.0 mA high-level" in calc._gpio_current(0.04)["message"]  # equal is not "below"
    assert calc._gpio_current(0.0400001)["severity"] == "caution"


# --- discrete parts ----------------------------------------------------------------------------------------------

ASSIGN = [{"role": "LED", "mode": "out", "pin": 26, "net": "LA"}, {"role": "SENSE", "mode": "in", "pin": 27, "net": "V12S"}]
WIRED = [{"ref": "D1", "kind": "led", "value": "red", "conn": {"A": "LA", "K": "GND"}},
         {"ref": "R1", "kind": "resistor", "value": "1k", "conn": {"1": "V12S", "2": "V12"}}]


def _check(parts):
    return pins.check("esp32", ASSIGN, wifi=True, parts=parts, options={"rails": {"V12": 12}})


def test_wired_discrete_parts_are_named_as_not_analysed():
    env = _check(WIRED)
    a = next(a for a in env["assumptions"] if a["key"] == "discrete_parts")
    assert a["value"] == "2" and "D1" in a["reason"] and "R1" in a["reason"]
    assert "no electrical check of their own" in a["reason"]
    assert env["summary"].endswith("2 ok, 0 caution, 0 blocked.")
    base = pins.check("esp32", ASSIGN, wifi=True)
    assert [x for x in env["assumptions"] if x["key"] != "discrete_parts"] == base["assumptions"]
    assert env["checks"] == base["checks"] and env["warnings"] == base["warnings"]


def test_many_discrete_parts_list_at_most_six_refs():
    parts = [{"ref": f"R{i}", "kind": "resistor", "value": "1k", "conn": {"1": "A", "2": "B"}} for i in range(1, 9)]
    a = next(a for a in _check(parts)["assumptions"] if a["key"] == "discrete_parts")
    assert a["value"] == "8" and "R6, …:" in a["reason"] and "R7" not in a["reason"]


def test_parts_without_conn_and_module_only_projects_add_nothing():
    demo = json.loads((ROOT / "circuit_bench" / "data" / "demo" / "laser-trigger.project.json").read_text("utf-8"))
    assert demo["parts"] and not any(p.get("conn") for p in demo["parts"])
    env = pins.check(demo["chip"], demo["assignments"], variant=demo.get("variant"), wifi=bool(demo.get("wifi")),
                     parts=demo["parts"], options=None)
    assert env["ok"] and all(a["key"] != "discrete_parts" for a in env["assumptions"])
    bare = pins.check(demo["chip"], demo["assignments"], variant=demo.get("variant"), wifi=bool(demo.get("wifi")))
    assert env["assumptions"] == bare["assumptions"]
