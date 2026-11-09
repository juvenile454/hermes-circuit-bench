"""Module family npixel: catalog entries WS2813, WS2815, LTV-817, EL817 and the family rules mod.npixel.data_in_rail,
mod.npixel.opto_led_resistor and mod.npixel.opto_vceo.

The generic tests (test_m0_modules_data/corpus) check the module evidence against the excerpts and the PDFs; this file
checks the rule constants (modrules/npixel.FACTS) against the committed excerpts and the behaviour of the rules together
with the generic supply/level rules on synthetic projects.
"""
from __future__ import annotations

import pytest

import excerpts as ex
import modkit as mk
from circuit_bench.bench_core import modules
from circuit_bench.bench_core.modrules import npixel as npx

RAIL = "mod.npixel.data_in_rail"
LEDR = "mod.npixel.opto_led_resistor"
VCEO = "mod.npixel.opto_vceo"
EXCERPT = {"mod-npixel-ltv817-ds": "mod-npixel-ltv817.txt", "mod-npixel-el817-ds": "mod-npixel-el817.txt"}


def _run(parts, assignments=(), rails=None, only=None):
    opts = {"rails": rails} if rails else None
    return mk.run(parts=parts, assignments=list(assignments), options=opts, only=only)


def _one(rep, rule_id, status=None):
    fs = mk.findings(rep, rule_id, status)
    assert len(fs) == 1, [(f.status, f.message) for f in mk.findings(rep, rule_id)]
    return fs[0]


def _res(ref, a, b, value="1k"):
    return {"ref": ref, "kind": "resistor", "value": value, "conn": {"1": a, "2": b}}


# --- data ----------------------------------------------------------------------------------------------------------
def test_catalog_has_the_four_parts_with_their_source_class():
    modules.clear_cache()
    cat = modules.catalog()
    assert not [p for p in cat.problems if "npixel" in str(p)]
    want = {"ws2813": "A", "ws2815": "A", "ltv817": "A1", "el817": "A"}
    for mid, cls in want.items():
        m = cat.get(mid)
        assert m is not None, mid
        assert m["_class"] == cls
    assert cat.get("ltv-817")["id"] == "ltv817"
    assert cat.get("ws2815b")["id"] == "ws2815"
    assert cat.get("ltv817")["category"] == cat.get("el817")["category"] == "isolation.opto"


def test_ws2815_levels_and_supply_are_as_in_the_datasheet():
    m = modules.catalog().get("ws2815")
    sup = m["supplies"]["VDD"]
    assert (sup["min"]["value"], sup["abs_max"]["value"]) == (9.5, 13.5)
    assert m["io"]["vih"]["value"] == 2.7 and m["io"]["v_in_max"]["value"] == 5.7
    ws13 = modules.catalog().get("ws2813")
    assert ws13["io"]["vih"]["rel"] == 0.7 and ws13["io"]["v_in_max"]["rel_offset"] == 0.7


@pytest.mark.parametrize("part", sorted(npx.FACTS))
def test_rule_facts_are_quoted_in_the_excerpts(part):
    for key, f in npx.FACTS[part].items():
        exc = ex.parse(EXCERPT[f["source_id"]])
        assert exc.source_id == f["source_id"]
        lines = [line for seg in exc.page_segments(f["page"]) for line in seg]
        assert any(f["evidence"] in line for line in lines), (part, key, f["evidence"])
        shown = f["value"] if f["unit"] == "V" else f["value"] * 1000  # A values are quoted in mA
        assert f"{shown:g}" in f["evidence"], (part, key)


# --- WS2813 / WS2815 with the generic rules -------------------------------------------------------------------------
def test_ws2813_on_5v_from_a_3v3_gpio_needs_a_level_shifter():
    rep = _run([mk.mod("D1", "ws2813", {"VCC": "5V", "GND": "GND", "DIN": "LED", "BIN": "GND"})],
               [mk.assign("out", 4, "LED")], only=("mod.level_in", "mod.supply_range", RAIL))
    f = _one(rep, "mod.level_in", "failed")
    assert f.severity == "caution" and "3.50 V" in f.message
    assert _one(rep, "mod.supply_range").status == "passed"
    assert _one(rep, RAIL).status == "passed"


def test_ws2813_on_12v_is_danger():
    rep = _run([mk.mod("D1", "ws2813", {"VCC": "12V", "GND": "GND", "DIN": "LED", "BIN": "GND"})],
               [mk.assign("out", 4, "LED")], rails={"12V": 12.0}, only=("mod.supply_range",))
    f = _one(rep, "mod.supply_range", "failed")
    assert f.severity == "danger" and "5.30 V" in f.message


def test_ws2815_on_12v_from_3v3_is_outside_the_guaranteed_levels_only():
    rep = _run([mk.mod("D1", "ws2815", {"VDD": "12V", "GND": "GND", "DIN1": "LED", "DIN2": "GND"})],
               [mk.assign("out", 4, "LED")], rails={"12V": 12.0},
               only=("mod.level_in", "mod.supply_range", "mod.hazard", RAIL))
    assert _one(rep, "mod.supply_range").status == "passed"
    f = _one(rep, "mod.level_in", "failed")
    assert f.severity == "caution" and "2.70 V" in f.message and "guaranteed" in f.message
    hz = _one(rep, "mod.hazard", "failed")
    assert hz.severity == "caution" and "12 V" in hz.message


def test_ws2815_on_5v_is_below_its_range():
    rep = _run([mk.mod("D1", "ws2815", {"VDD": "5V", "GND": "GND", "DIN1": "LED", "DIN2": "GND"})],
               [mk.assign("out", 4, "LED")], only=("mod.supply_range",))
    f = _one(rep, "mod.supply_range", "failed")
    assert f.severity == "caution" and "9.50 V" in f.message


# --- mod.npixel.data_in_rail ------------------------------------------------------------------------------------
def test_ws2815_backup_input_on_its_12v_rail_is_danger():
    rep = _run([mk.mod("D1", "ws2815", {"VDD": "12V", "GND": "GND", "DIN1": "LED", "DIN2": "12V"})],
               [mk.assign("out", 4, "LED")], rails={"12V": 12.0}, only=(RAIL,))
    f = _one(rep, RAIL, "failed")
    assert f.severity == "danger" and "5.70 V" in f.message and "DIN2" in f.message
    assert f.source_ids == ["mod-npixel-ws2815-ds"]


def test_ws2813_backup_input_on_5v_is_only_info():
    rep = _run([mk.mod("D1", "ws2813", {"VCC": "5V", "GND": "GND", "DIN": "LED", "BIN": "5V"})],
               [mk.assign("out", 4, "LED")], only=(RAIL,))
    f = _one(rep, RAIL, "failed")
    assert f.severity == "info"  # 5 V < VCC + 0.7 V


def test_ws2813_backup_input_on_12v_with_led_on_5v_is_danger():
    rep = _run([mk.mod("D1", "ws2813", {"VCC": "5V", "GND": "GND", "DIN": "LED", "BIN": "12V"})],
               [mk.assign("out", 4, "LED")], rails={"12V": 12.0}, only=(RAIL,))
    f = _one(rep, RAIL, "failed")
    assert f.severity == "danger" and "5.70 V" in f.message  # VCC 5 V + 0.7 V


def test_data_in_rail_without_supply_is_not_checked_and_ignores_signal_nets():
    rep = _run([mk.mod("D1", "ws2813", {"GND": "GND", "DIN": "LED", "BIN": "5V"})],
               [mk.assign("out", 4, "LED")], only=(RAIL,))
    f = _one(rep, RAIL)
    assert f.status == "not_checked"
    rep = _run([mk.mod("D1", "ws2813", {"VCC": "5V", "GND": "GND", "DIN": "LED", "BIN": "LED"})],
               [mk.assign("out", 4, "LED")], only=(RAIL,))
    assert mk.findings(rep, RAIL) == []


# --- mod.npixel.opto_led_resistor -------------------------------------------------------------------------------
@pytest.mark.parametrize("mid", ["ltv817", "el817"])
def test_opto_led_on_a_rail_without_resistor_is_danger(mid):
    rep = _run([mk.mod("U1", mid, {"ANODE": "5V", "CATHODE": "GND", "COLLECTOR": "GPIO5", "EMITTER": "GND"})],
               [mk.assign("in_pullup", 5)], only=(LEDR,))
    f = _one(rep, LEDR, "failed")
    want = "50.0 mA" if mid == "ltv817" else "60.0 mA"
    assert f.severity == "danger" and want in f.message


def test_opto_led_straight_from_a_gpio_is_caution():
    rep = _run([mk.mod("U1", "ltv817", {"ANODE": "GPIO4", "CATHODE": "GND", "COLLECTOR": "GPIO5", "EMITTER": "GND"})],
               [mk.assign("out", 4), mk.assign("in_pullup", 5)], only=(LEDR,))
    f = _one(rep, LEDR, "failed")
    assert f.severity == "caution" and "GPIO" in f.message


@pytest.mark.parametrize("where", ["anode", "cathode"])
def test_opto_led_with_series_resistor_passes(where):
    if where == "anode":
        parts = [mk.mod("U1", "el817", {"ANODE": "LEDA", "CATHODE": "GND", "COLLECTOR": "GPIO5", "EMITTER": "GND"}),
                 _res("R1", "GPIO4", "LEDA", "330")]
    else:
        parts = [mk.mod("U1", "el817", {"ANODE": "3V3", "CATHODE": "LEDK", "COLLECTOR": "GPIO5", "EMITTER": "GND"}),
                 _res("R1", "LEDK", "GPIO4", "330")]
    rep = _run(parts, [mk.assign("out", 4), mk.assign("in_pullup", 5)], only=(LEDR,))
    f = _one(rep, LEDR)
    assert f.status == "passed" and "R1" in f.message


def test_opto_led_on_unknown_nets_is_not_checked():
    rep = _run([mk.mod("U1", "el817", {"ANODE": "X1", "CATHODE": "X2", "COLLECTOR": "GPIO5", "EMITTER": "GND"})],
               [mk.assign("in_pullup", 5)], only=(LEDR,))
    assert _one(rep, LEDR).status == "not_checked"


# --- mod.npixel.opto_vceo ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("mid", ["ltv817", "el817"])
def test_opto_collector_pulled_to_48v_exceeds_vceo(mid):
    parts = [mk.mod("U1", mid, {"ANODE": "LEDA", "CATHODE": "GND", "COLLECTOR": "OUT", "EMITTER": "GND"}),
             _res("R1", "GPIO4", "LEDA", "330"), _res("R2", "OUT", "48V", "47k")]
    rep = _run(parts, [mk.assign("out", 4)], rails={"48V": 48.0}, only=(VCEO,))
    f = _one(rep, VCEO, "failed")
    assert f.severity == "danger" and "35.0 V" in f.message and "PC817" in f.message


def test_opto_collector_pulled_to_24v_passes():
    parts = [mk.mod("U1", "ltv817", {"ANODE": "LEDA", "CATHODE": "GND", "COLLECTOR": "OUT", "EMITTER": "GND"}),
             _res("R1", "GPIO4", "LEDA", "330"), _res("R2", "OUT", "24V", "10k")]
    rep = _run(parts, [mk.assign("out", 4)], rails={"24V": 24.0}, only=(VCEO,))
    assert _one(rep, VCEO).status == "passed"


def test_opto_collector_on_esp_internal_pullup_is_not_checked():
    rep = _run([mk.mod("U1", "el817", {"ANODE": "LEDA", "CATHODE": "GND", "COLLECTOR": "GPIO5", "EMITTER": "GND"})],
               [mk.assign("in_pullup", 5)], only=(VCEO,))
    assert _one(rep, VCEO).status == "not_checked"


def test_opto_collector_to_esp_with_5v_pullup_is_danger_by_the_generic_rule():
    parts = [mk.mod("U1", "ltv817", {"ANODE": "LEDA", "CATHODE": "GND", "COLLECTOR": "GPIO5", "EMITTER": "GND"}),
             _res("R1", "GPIO4", "LEDA", "330"), _res("R2", "GPIO5", "5V", "10k")]
    rep = _run(parts, [mk.assign("out", 4), mk.assign("in", 5)], only=("mod.level_out", VCEO))
    assert _one(rep, "mod.level_out", "failed").severity == "danger"
    assert _one(rep, VCEO).status == "passed"


def test_no_npixel_parts_no_findings():
    rep = _run([mk.mod("U1", "pc817", {"ANODE": "5V", "CATHODE": "GND", "COLLECTOR": "GPIO5", "EMITTER": "GND"})],
               [mk.assign("in_pullup", 5)], only=(RAIL, LEDR, VCEO))
    assert mk.findings(rep) == []
