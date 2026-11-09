"""Module family ambient: catalog entries (DS18B20, BH1750FVI, VEML7700, TSL2591, SCD4x, SGP40) and family rules.
Synthetic projects only; the module data is the real catalog (data/modules/ambient.json).
Expectations cover mod.address_conflict, mod.supply_range, the mod.ambient.* rules and the generic bus and
electrical rules.
"""
from __future__ import annotations

import pytest

import excerpts as ex
import modkit as mk
from circuit_bench.bench_core import modules
from circuit_bench.bench_core.modrules import ambient

ALL = ("ds18b20", "bh1750fvi", "veml7700", "tsl2591", "scd4x", "sgp40")
PULL, PARA, PEAK = "mod.ambient.ds18b20_pullup", "mod.ambient.ds18b20_parasite", "mod.ambient.scd4x_peak"
CONFLICT, SUPPLY = "mod.address_conflict", "mod.supply_range"


def only(*rules):
    return tuple(rules)


def one(report, rule_id, status=None):
    fs = mk.findings(report, rule_id, status)
    assert len(fs) == 1, [(f.status, f.message) for f in mk.findings(report, rule_id)]
    return fs[0]


def i2c_mod(ref, module, supply="VDD", rail="3V3", gnd="GND", **conn):
    c = {"SDA": "SDA0", "SCL": "SCL0", supply: rail, gnd: "GND"}
    c.update(conn)
    return mk.mod(ref, module, c)


def ds(ref="U1", dq="OW", vdd="3V3", facts=None):
    return mk.mod(ref, "ds18b20", {"DQ": dq, "VDD": vdd, "GND": "GND"}, facts=facts)


def res(ref, a, b, value="4k7"):
    return {"ref": ref, "kind": "resistor", "value": value, "conn": {"1": a, "2": b}}


OW = [mk.assign("out", 4, "OW")]


# --- catalog -------------------------------------------------------------------------------------------------------
def test_all_parts_are_in_the_catalog_with_class_a_sources():
    cat = modules.catalog()
    for mid in ALL:
        m = cat.get(mid)
        assert m["_wp"] == "ambient"
        assert m["_class"] in ("A", "A1"), mid
    for alias, mid in (("scd40", "scd4x"), ("scd41", "scd4x"), ("bh1750", "bh1750fvi"), ("gy-302", "bh1750fvi"),
                       ("tsl25911", "tsl2591")):
        assert cat.get(alias)["id"] == mid
    assert {cat.get(m)["_class"] for m in ("ds18b20", "bh1750fvi")} == {"A1"}


def test_addresses_and_reserved():
    cat = modules.catalog()
    addr = {m: modules_addresses(cat.get(m)) for m in ALL if m != "ds18b20"}
    assert addr == {"bh1750fvi": ["0x23", "0x5c"], "veml7700": ["0x10"], "tsl2591": ["0x29"], "scd4x": ["0x62"],
                    "sgp40": ["0x59"]}
    tsl = next(i for i in cat.get("tsl2591")["interfaces"] if i["type"] == "i2c")
    assert tsl["reserved"] == ["0x28"]
    assert cat.get("ds18b20")["interfaces"][0]["type"] == "onewire"


def modules_addresses(m):
    it = next(i for i in m["interfaces"] if i["type"] == "i2c")
    return it["addresses"]["value"]


@pytest.mark.parametrize("source_id", sorted(ambient.QUOTES))
def test_values_in_rule_code_are_quoted_in_the_excerpt(source_id):
    excerpt = next(e for e in ex.excerpts("mod-ambient-*.txt") if e.source_id == source_id)
    for page, quotes in ambient.QUOTES[source_id].items():
        lines = [line for seg in excerpt.page_segments(page) for line in seg]
        for q in quotes:
            assert any(q in line for line in lines), (source_id, page, q)


# --- DS18B20: pull-up ----------------------------------------------------------------------------------------------
def test_ds18b20_without_pullup_is_a_caution_with_value_and_page():
    r = mk.run(assignments=OW, parts=[ds()], only=only(PULL))
    f = one(r, PULL, "failed")
    assert f.severity == "caution"
    assert "4k7" in f.message and "p. 7" in f.message and "OW" in f.message
    assert f.source_ids == ["mod-ambient-ds18b20-ds"]
    assert "mod_ambient_ds18b20_pullup" in mk.codes(r)


def test_ds18b20_internal_pullup_does_not_count():
    r = mk.run(assignments=[mk.assign("in_pullup", 4, "OW")], parts=[ds()], only=only(PULL))
    f = one(r, PULL, "failed")
    assert "internal pull-up" in f.message


def test_ds18b20_resistor_to_3v3_passes_and_one_finding_per_bus():
    parts = [ds("U1"), ds("U2"), ds("U3"), res("R1", "OW", "3V3")]
    r = mk.run(assignments=OW, parts=parts, only=only(PULL))
    f = one(r, PULL)
    assert f.status == "passed" and "R1 4k7 to 3V3" in f.message
    assert f.refs == ["U1", "U2", "U3"]


def test_ds18b20_resistor_on_the_gpio_net_name_counts():
    # the resistor names the ESP pin (GPIO4); the engine maps it onto the assignment's net OW
    r = mk.run(assignments=OW, parts=[ds(), res("R1", "GPIO4", "3V3")], only=only(PULL))
    assert one(r, PULL).status == "passed"


def test_ds18b20_pulldown_and_series_resistor_are_not_pullups():
    parts = [ds(dq="DQ1"), res("R1", "DQ1", "GND"), res("R2", "DQ1", "OW", "100")]
    r = mk.run(assignments=OW, parts=parts, only=only(PULL))
    assert one(r, PULL).status == "failed"


def test_ds18b20_board_fact_counts_as_pullup():
    r = mk.run(assignments=OW, parts=[ds(facts={"pullups": "4k7", "pullups_to": "3V3"})], only=only(PULL))
    f = one(r, PULL)
    assert f.status == "passed" and "facts" in f.message
    r = mk.run(assignments=OW, parts=[ds(facts={"pullups": "none"})], only=only(PULL))
    assert one(r, PULL).status == "failed"


def test_ds18b20_pullup_rail_below_vpu_min_or_above_vdd():
    r = mk.run(assignments=OW, parts=[ds(), res("R1", "OW", "1V8")], options={"rails": {"1V8": 1.8}},
               only=only(PULL))
    f = one(r, PULL, "failed")
    assert f.severity == "caution" and "3.00 V" in f.message
    # local power at 3.3 V, pull-up to 5 V: VPU must not exceed VDD
    r = mk.run(assignments=OW, parts=[ds(), res("R1", "OW", "5V")], only=only(PULL))
    f = one(r, PULL, "failed")
    assert "above VDD" in f.message


def test_ds18b20_pullup_to_unknown_rail_and_open_dq_are_not_checked():
    r = mk.run(assignments=OW, parts=[ds(), res("R1", "OW", "VBUS")], only=only(PULL))
    assert one(r, PULL).status == "not_checked"
    r = mk.run(assignments=OW, parts=[mk.mod("U1", "ds18b20", {"VDD": "3V3", "GND": "GND"})], only=only(PULL))
    assert one(r, PULL).status == "not_checked"


def test_two_buses_two_findings():
    parts = [ds("U1", "OW"), ds("U2", "OW2"), res("R1", "OW", "3V3")]
    r = mk.run(assignments=OW + [mk.assign("out", 5, "OW2")], parts=parts, only=only(PULL))
    st = sorted((f.status, tuple(f.refs)) for f in mk.findings(r, PULL))
    assert st == [("failed", ("U2",)), ("passed", ("U1",))]


def test_ds18b20_pullup_covers_required_parts():
    """mod.required_parts reports the same missing pull-up; the family rule supersedes it: one warning."""
    r = mk.run(assignments=OW, parts=[ds()], only=(PULL, "mod.required_parts"))
    f = one(r, PULL, "failed")
    assert f.severity == "caution" and f.supersedes == ("mod.required_parts",)
    assert [g.status for g in mk.findings(r, "mod.required_parts")] == ["failed"]  # kept in the checks
    assert "mod_required_parts" not in mk.codes(r) and "mod_ambient_ds18b20_pullup" in mk.codes(r)


# --- DS18B20: parasite power ---------------------------------------------------------------------------------------
def test_ds18b20_parasite_power_hint():
    r = mk.run(assignments=OW, parts=[ds(vdd="GND"), res("R1", "OW", "3V3")], only=only(PARA, PULL, SUPPLY))
    f = one(r, PARA, "failed")
    assert f.severity == "info"
    assert "parasite power" in f.message and "MOSFET" in f.message and "+100 °C" in f.message
    assert one(r, PULL).status == "passed"
    assert all(x.status == "passed" for x in mk.findings(r, SUPPLY))  # VDD = 0 V is a valid mode


def test_ds18b20_parasite_with_a_mosfet_on_the_bus():
    q = {"ref": "Q1", "kind": "mosfet", "value": "BSS84", "conn": {"D": "OW", "S": "3V3", "G": "GPIO5"}}
    r = mk.run(assignments=OW + [mk.assign("out", 5, "SPU")], parts=[ds(vdd="GND"), res("R1", "OW", "3V3"), q],
               only=only(PARA))
    assert "Q1 on the bus" in one(r, PARA, "failed").message


def test_ds18b20_local_power_passes_and_low_vdd_is_a_caution():
    r = mk.run(assignments=OW, parts=[ds(vdd="5V")], only=only(PARA))
    assert one(r, PARA).status == "passed"
    r = mk.run(assignments=OW, parts=[ds(vdd="1V8")], options={"rails": {"1V8": 1.8}}, only=only(PARA))
    f = one(r, PARA, "failed")
    assert f.severity == "caution" and "below the local-power range" in f.message


def test_ds18b20_vdd_unknown_or_open_is_not_checked():
    r = mk.run(assignments=OW, parts=[ds(vdd="VX")], only=only(PARA))
    assert one(r, PARA).status == "not_checked"
    r = mk.run(assignments=OW, parts=[mk.mod("U1", "ds18b20", {"DQ": "OW", "GND": "GND"})], only=only(PARA))
    assert one(r, PARA).status == "not_checked"


def test_ds18b20_above_6v_is_danger():
    r = mk.run(assignments=OW, parts=[ds(vdd="VBAT")], options={"rails": {"VBAT": 7.4}}, only=only(SUPPLY))
    assert one(r, SUPPLY, "failed").severity == "danger"


# --- SCD4x: peak current -------------------------------------------------------------------------------------------
def test_scd4x_peak_without_limit_is_a_hint_with_ripple():
    r = mk.run(assignments=mk.i2c(), parts=[i2c_mod("U1", "scd41")], only=only(PEAK))
    f = one(r, PEAK, "failed")
    assert f.severity == "info"
    assert "205 mA" in f.message and "30.0 mV" in f.message and "rail_limits" in f.message


def test_scd4x_peak_above_the_rail_limit_is_a_caution():
    r = mk.run(assignments=mk.i2c(), parts=[i2c_mod("U1", "scd40")], options={"rail_limits": {"3V3": 0.15}},
               only=only(PEAK))
    f = one(r, PEAK, "failed")
    assert f.severity == "caution" and "150 mA" in f.message


def test_scd4x_peak_within_limit_passes_and_sums_other_modules():
    parts = [i2c_mod("U1", "scd4x"), i2c_mod("U2", "tsl2591")]
    r = mk.run(assignments=mk.i2c(), parts=parts, options={"rail_limits": {"3V3": 0.5}}, only=only(PEAK))
    f = one(r, PEAK, "passed")
    assert "205 mA" in f.message and "500 mA" in f.message
    # 205 mA + 325 µA (TSL2591 active max) = 205.325 mA -> "205 mA" at 3 digits; the limit decides
    r = mk.run(assignments=mk.i2c(), parts=parts, options={"rail_limits": {"3V3": 0.2052}}, only=only(PEAK))
    assert one(r, PEAK).status == "failed"


def test_scd4x_peak_at_5v_uses_the_5v_value():
    r = mk.run(assignments=mk.i2c(), parts=[i2c_mod("U1", "scd41", rail="5V")],
               options={"rail_limits": {"5V": 0.15}}, only=only(PEAK))
    f = one(r, PEAK, "passed")
    assert "137 mA" in f.message and "at 5 V" in f.message


def test_scd4x_peak_on_other_voltages_says_so():
    r = mk.run(assignments=mk.i2c(), parts=[i2c_mod("U1", "scd41", rail="V3")], options={"rails": {"V3": 3.0}},
               only=only(PEAK))
    assert "3.3 V and 5 V only" in one(r, PEAK, "failed").message


def test_scd4x_two_sensors_on_one_rail():
    parts = [i2c_mod("U1", "scd40"), mk.mod("U2", "scd41", {"SDA": "SDA1", "SCL": "SCL1", "VDD": "3V3",
                                                            "GND": "GND"})]
    r = mk.run(assignments=mk.i2c() + mk.i2c(10, 11, "SDA1"), parts=parts, options={"rail_limits": {"3V3": 0.3}},
               only=only(PEAK, CONFLICT))
    f = one(r, PEAK, "failed")
    assert "410 mA" in f.message and f.refs == ["U1", "U2"]
    assert not mk.findings(r, CONFLICT, "failed")  # different buses


def test_scd4x_unknown_rail_not_checked():
    r = mk.run(assignments=mk.i2c(), parts=[i2c_mod("U1", "scd41", rail="VX")], only=only(PEAK))
    assert one(r, PEAK).status == "not_checked"


def test_no_ambient_parts_no_ambient_findings():
    r = mk.run(assignments=mk.i2c(), parts=[i2c_mod("U1", "veml7700")], only=only(PULL, PARA, PEAK))
    assert mk.findings(r) == []


# --- addresses -----------------------------------------------------------------------------------------------------
def test_scd40_and_scd41_share_0x62():
    r = mk.run(assignments=mk.i2c(), parts=[i2c_mod("U1", "scd40"), i2c_mod("U2", "scd41")], only=only(CONFLICT))
    f = one(r, CONFLICT, "failed")
    assert f.severity == "caution" and "0x62" in f.message


def test_bh1750_addr_pin_selects_0x5c():
    parts = [i2c_mod("U1", "bh1750fvi", supply="VCC", ADDR="GND"), i2c_mod("U2", "bh1750fvi", supply="VCC", ADDR="GND")]
    r = mk.run(assignments=mk.i2c(), parts=parts, only=only(CONFLICT))
    f = one(r, CONFLICT, "failed")
    assert "0x23" in f.message and "0x5c (ADDR to VCC)" in f.message
    parts[1] = i2c_mod("U2", "bh1750fvi", supply="VCC", ADDR="3V3")
    r = mk.run(assignments=mk.i2c(), parts=parts, only=only(CONFLICT))
    assert one(r, CONFLICT).status == "passed"


def test_two_veml7700_collide_without_alternative():
    r = mk.run(assignments=mk.i2c(), parts=[i2c_mod("U1", "veml7700"), i2c_mod("U2", "veml7700")],
               only=only(CONFLICT))
    f = one(r, CONFLICT, "failed")
    assert "0x10" in f.message and "I²C mux" in f.message


def test_ambient_mix_on_one_bus_has_no_conflict():
    parts = [i2c_mod("U1", "bh1750fvi", supply="VCC", ADDR="GND"), i2c_mod("U2", "veml7700"),
             i2c_mod("U3", "tsl2591"), i2c_mod("U4", "scd41"), i2c_mod("U5", "sgp40", gnd="VSS")]
    r = mk.run(assignments=mk.i2c(), parts=parts, only=only(CONFLICT, SUPPLY))
    assert one(r, CONFLICT).status == "passed"
    assert all(f.status == "passed" for f in mk.findings(r, SUPPLY))


def test_tsl2591_answers_on_0x29_explicit_0x28_device_collides():
    # a second device set to 0x29 collides with the TSL2591 (hard, generic engine rule)
    parts = [i2c_mod("U1", "tsl2591"), {**i2c_mod("U2", "bh1750fvi", supply="VCC", ADDR="GND"), "address": "0x29"}]
    r = mk.run(assignments=mk.i2c(), parts=parts, only=only(CONFLICT))
    assert "0x29" in one(r, CONFLICT, "failed").message


def test_tsl2591_secondary_0x28_is_reserved():
    parts = [i2c_mod("U1", "tsl2591"), {**i2c_mod("U2", "bh1750fvi", supply="VCC", ADDR="GND"), "address": "0x28"}]
    r = mk.run(assignments=mk.i2c(), parts=parts)
    assert "mod_address_reserved" in mk.codes(r)


# --- supply range --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("module", "supply", "rail", "severity"), [
    ("bh1750fvi", "VCC", "5V", "danger"),     # abs max 4.5 V
    ("veml7700", "VDD", "5V", "danger"),      # abs max 4 V
    ("tsl2591", "VDD", "5V", "danger"),       # abs max 3.8 V
    ("sgp40", "VDD", "5V", "danger"),         # abs max 3.6 V
    ("scd4x", "VDD", "5V", None),             # 2.4–5.5 V
])
def test_supply_on_5v(module, supply, rail, severity):
    gnd = "VSS" if module == "sgp40" else "GND"
    r = mk.run(assignments=mk.i2c(), parts=[i2c_mod("U1", module, supply=supply, rail=rail, gnd=gnd)],
               only=only(SUPPLY))
    fails = mk.findings(r, SUPPLY, "failed")
    if severity is None:
        assert not fails
    else:
        assert fails and {f.severity for f in fails} == {severity}


def test_tsl2591_below_2v7_is_a_caution():
    r = mk.run(assignments=mk.i2c(), parts=[i2c_mod("U1", "tsl2591", rail="2V5")], options={"rails": {"2V5": 2.5}},
               only=only(SUPPLY))
    assert one(r, SUPPLY, "failed").severity == "caution"


def test_scd4x_at_5v_needs_pullups_and_reads_3v3_pullups():
    # without pull-ups the bus has no high level yet: the missing pull-ups are the finding, not the level
    r = mk.run(assignments=mk.i2c(), parts=[i2c_mod("U1", "scd41", rail="5V")])
    assert one(r, "mod.required_parts", "failed").severity == "caution"
    assert "mod_level_in" not in mk.codes(r)
    # pull-ups to 3V3: VIH 3.25 V of the SCD4x at 5 V is still below the 3.30 V high level
    r = mk.run(assignments=mk.i2c(), parts=[i2c_mod("U1", "scd41", rail="5V"), res("R1", "SDA0", "3V3"),
                                            res("R2", "SCL0", "3V3")])
    level_in = mk.findings(r, "mod.level_in")
    assert len(level_in) == 2 and {(f.status, f.severity) for f in level_in} == {("passed", None)}
    assert all("VIH 3.25 V" in f.message and "3.30 V" in f.message for f in level_in)
    assert "mod_level_in" not in mk.codes(r) and "mod_required_parts" not in mk.codes(r)
