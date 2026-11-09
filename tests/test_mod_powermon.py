"""Module family powermon: INA219, INA226, INA260, INA3221, ACS712; family rules
mod.powermon.*; calculators ina_shunt and current_sense.

Synthetic projects only. Expected values are recomputed by hand in the comments from the datasheet numbers
(TI SBOS448G/SBOS547C/SBOS656C/SBOS576C, Allegro ACS712-DS Rev. 22; quoted in tests/corpus/excerpts/mod-powermon-*).
"""
from __future__ import annotations

import pytest

import excerpts as ex
import modkit as mk
from circuit_bench.bench_core import calckit, modules
from circuit_bench.bench_core.calcs import current_sense as cs
from circuit_bench.bench_core.calcs import ina_shunt as ina

BUS_RULE = "mod.powermon.ina_bus_voltage"
DIV_RULE = "mod.powermon.acs712_needs_5v_divider"


def _calc(kind, **params):
    env = calckit.run(kind, params)
    assert env["ok"], env.get("error")
    return env


def _status(env, check):
    return next(c["status"] for c in env["checks"] if c["id"] == f"calc.{env['action'].split('.', 1)[1]}.{check}")


def _codes(env):
    return {w["code"]: w["severity"] for w in env["warnings"]}


def _devices(rep):
    return {d["ref"]: d["address"] for b in rep.result["buses"] for s in b["segments"] for d in s["devices"]}


def _ina(a1="GND", a0="GND", vs="3V3", **extra):
    conn = {"VS": vs, "GND": "GND", "SDA": "SDA0", "SCL": "SCL0", "A1": a1, "A0": a0}
    conn.update(extra)
    return conn


# --- catalog ---------------------------------------------------------------------------------------------------------
def test_entries_load_without_problems():
    cat = modules.catalog()
    assert cat.problems == []
    for mid in ("ina219", "ina226", "ina260", "ina3221", "acs712"):
        m = cat.get(mid)
        assert m["_wp"] == "powermon" and m["_class"] == "A"
    assert cat.get("ina219")["category"] == "power.monitor"
    assert cat.get("acs712")["category"] == "sensor.current"


def test_ina_select_maps_cover_the_16_addresses():
    cat = modules.catalog()
    for mid in ("ina219", "ina226", "ina260"):
        it = cat.get(mid)["interfaces"][0]
        assert it["select"]["pins"] == ["A1", "A0"]
        assert sorted(it["select"]["map"].values()) == [f"0x{a:02x}" for a in range(0x40, 0x50)]
        # Table 1 / 6-2 / 2: A1 = SDA, A0 = VS -> 1001001 = 0x49; A1 = SCL, A0 = SCL -> 1001111 = 0x4F
        assert it["select"]["map"]["SDA,VS"] == "0x49" and it["select"]["map"]["SCL,SCL"] == "0x4f"
    assert cat.get("ina3221")["interfaces"][0]["select"] == {
        "pin": "A0", "map": {"GND": "0x40", "VS": "0x41", "SDA": "0x42", "SCL": "0x43"}}


def test_acs712_variants_carry_the_sensitivity():
    cat = modules.catalog()
    for vid, mv in (("05b", "185"), ("20a", "100"), ("30a", "66")):
        notes = cat.get("acs712", vid)["notes"]
        assert any(f"{mv} mV/A" in n["text"] and n["verified"] for n in notes), vid


# --- projects: address, supply, level-relevant wiring ---------------------------------------------------------------
def test_ina219_addresses_from_a1_a0():
    rep = mk.run(assignments=mk.i2c(), parts=[mk.mod("U1", "ina219", _ina("GND", "GND")),
                                              mk.mod("U2", "ina219", _ina("GND", "3V3")),
                                              mk.mod("U3", "ina219", _ina("SDA0", "SCL0"))])
    # A1/A0 = GND/GND 0x40, GND/VS 0x41 (VS is on 3V3), SDA/SCL 1001011 = 0x4B
    assert _devices(rep) == {"U1": "0x40", "U2": "0x41", "U3": "0x4b"}
    assert "mod_address_conflict" not in mk.codes(rep)
    assert {f.status for f in mk.findings(rep, "mod.supply_range")} == {"passed"}


def test_ina219_and_ina226_both_at_0x40_collide():
    rep = mk.run(assignments=mk.i2c(), parts=[mk.mod("U1", "ina219", _ina()), mk.mod("U2", "ina226", _ina())])
    assert _devices(rep) == {"U1": "0x40", "U2": "0x40"}
    assert "mod_address_conflict" in mk.codes(rep)


def test_ina226_supply_5v_passes_and_6v_is_danger():
    ok = mk.run(assignments=mk.i2c(), parts=[mk.mod("U1", "ina226", _ina("SCL0", "SDA0", vs="5V"))])
    assert _devices(ok) == {"U1": "0x4e"}  # SCL/SDA -> 1001110
    assert {f.status for f in mk.findings(ok, "mod.supply_range")} == {"passed"}
    bad = mk.run(assignments=mk.i2c(), parts=[mk.mod("U1", "ina226", _ina(vs="V6"))], options={"rails": {"V6": 6.5}})
    f = mk.findings(bad, "mod.supply_range", "failed")
    assert f and f[0].severity == "danger"  # 6.5 V > abs max 6 V (p. 4)


def test_ina260_address_and_supply():
    rep = mk.run(assignments=mk.i2c(), parts=[mk.mod("U1", "ina260", _ina("SCL0", "SCL0"))])
    assert _devices(rep) == {"U1": "0x4f"}
    assert {f.status for f in mk.findings(rep, "mod.supply_range")} == {"passed"}


def test_ina3221_single_address_pin():
    rep = mk.run(assignments=mk.i2c(), parts=[mk.mod("U1", "ina3221", {"VS": "3V3", "GND": "GND", "SDA": "SDA0",
                                                                       "SCL": "SCL0", "A0": "SDA0"})])
    assert _devices(rep) == {"U1": "0x42"}


def test_acs712_at_3v3_is_below_its_supply_range():
    rep = mk.run(parts=[mk.mod("U1", "acs712", {"VCC": "3V3", "GND": "GND"}, variant="05b")])
    f = mk.findings(rep, "mod.supply_range", "failed")
    assert f and f[0].severity == "caution"  # 3.3 V < VCC min 4.5 V (p. 5)


# --- family rule: ACS712 output at a GPIO -----------------------------------------------------------------------------
def _acs(variant=None, vout="ADC1", vcc="5V"):
    return mk.mod("U1", "acs712", {"VCC": vcc, "GND": "GND", "VIOUT": vout}, variant=variant)


def test_acs712_20a_straight_at_gpio_is_danger():
    # 2.5 V + 0.100 V/A · 20 A = 4.5 V > ESP32-S3 v_in_max 3.6 V
    rep = mk.run(assignments=[mk.assign("adc", 4, "ADC1")], parts=[_acs("20a")])
    f = mk.findings(rep, DIV_RULE, "failed")
    assert len(f) == 1 and f[0].severity == "danger"
    assert "4.50 V" in f[0].message and "3.60 V" in f[0].message
    assert "mod_powermon_acs712_needs_5v_divider" in mk.codes(rep)


def test_acs712_without_variant_takes_the_worst_case():
    rep = mk.run(assignments=[mk.assign("adc", 4, "ADC1")], parts=[_acs(None)])
    f = mk.findings(rep, DIV_RULE, "failed")
    assert f and "worst case" in f[0].message and "x20A" in f[0].message


def test_acs712_05b_stays_below_the_limit_at_its_range():
    # 2.5 V + 0.185 V/A · 5 A = 3.425 V <= 3.6 V; the limit is crossed at (3.6 − 2.5) / 0.185 = 5.95 A
    rep = mk.run(assignments=[mk.assign("adc", 4, "ADC1")], parts=[_acs("05b")])
    f = mk.findings(rep, DIV_RULE)
    assert [x.status for x in f] == ["passed"] and "3.42 V" in f[0].message and "5.95 A" in f[0].message


def test_acs712_via_divider_net_is_not_checked():
    rep = mk.run(assignments=[mk.assign("adc", 4, "ADC1")], parts=[_acs("30a", vout="ACS_OUT")])
    f = mk.findings(rep, DIV_RULE)
    assert [x.status for x in f] == ["not_checked"] and "current_sense" in f[0].message


def test_acs712_unknown_vcc_is_not_checked():
    rep = mk.run(assignments=[mk.assign("adc", 4, "ADC1")], parts=[_acs("20a", vcc="VX")])
    assert [x.status for x in mk.findings(rep, DIV_RULE)] == ["not_checked"]


# --- family rule: INA bus voltage -----------------------------------------------------------------------------------
@pytest.mark.parametrize("mid,volts,status,severity", [
    ("ina219", 24.0, "passed", None), ("ina219", 30.0, "failed", "danger"),   # 26 V is max and absolute maximum
    ("ina226", 36.0, "passed", None), ("ina226", 38.0, "failed", "caution"), ("ina226", 41.0, "failed", "danger"),
    ("ina260", 39.0, "failed", "caution"),
])
def test_ina_bus_voltage_against_rails(mid, volts, status, severity):
    conn = _ina(**{"IN+": "VLOAD", "IN-": "VLOAD_OUT"})
    rep = mk.run(assignments=mk.i2c(), parts=[mk.mod("U1", mid, conn)], options={"rails": {"VLOAD": volts}})
    f = mk.findings(rep, BUS_RULE)
    assert [(x.status, x.severity) for x in f] == [(status, severity)]


def test_ina3221_channel_on_a_high_rail_is_danger():
    conn = {"VS": "3V3", "GND": "GND", "SDA": "SDA0", "SCL": "SCL0", "A0": "GND", "IN+2": "V28", "IN-2": "LOAD2"}
    rep = mk.run(assignments=mk.i2c(), parts=[mk.mod("U1", "ina3221", conn)], options={"rails": {"V28": 28.0}})
    f = mk.findings(rep, BUS_RULE, "failed")
    assert f and f[0].severity == "danger" and "IN+2" in f[0].message


def test_ina_bus_without_rail_voltage_is_not_checked():
    rep = mk.run(assignments=mk.i2c(), parts=[mk.mod("U1", "ina226", _ina(**{"IN+": "BATT", "VBUS": "BATT"}))])
    assert [x.status for x in mk.findings(rep, BUS_RULE)] == ["not_checked"]


# --- calculator ina_shunt -------------------------------------------------------------------------------------------
def test_ina219_datasheet_example():
    # SBOS448G p. 26: 15 A max, 2 mΩ, Current_LSB 1 mA -> Cal = trunc(0.04096 / (1e-3 · 2e-3)) = 20480 (5000h)
    env = _calc("ina_shunt", part="ina219", i_max=15, r_shunt="2m", current_lsb="1m")
    r = env["result"]
    assert r["cal"] == ina.EXAMPLES["ina219"]["value"] == 20480 and r["cal_hex"] == "0x5000"
    assert r["current_lsb_min"]["value"] == pytest.approx(15 / 32768, rel=1e-5)  # 457.78 µA (p. 26)
    assert r["power_lsb"]["value"] == pytest.approx(0.020)  # 20 · 1 mA
    assert r["pga"] == 1 and r["v_shunt_max"]["value"] == pytest.approx(0.030)  # 30 mV ≤ ±40 mV
    assert r["p_shunt"]["value"] == pytest.approx(0.45)  # 15² · 2 mΩ
    assert _status(env, "shunt_range") == "passed"


def test_ina226_datasheet_example():
    # SBOS547C p. 15: Current_LSB 1 mA, 2 mΩ -> CAL = 0.00512 / (1e-3 · 2e-3) = 2560 (A00h); Power_LSB 25 mW
    r = _calc("ina_shunt", part="ina226", i_max=15, r_shunt="2m", current_lsb="1m")["result"]
    assert r["cal"] == ina.EXAMPLES["ina226"]["value"] == 2560 and r["cal_hex"] == "0x0A00"
    assert r["power_lsb"]["value"] == pytest.approx(0.025)


def test_ina219_breakout_auto_lsb_and_pga():
    # 0.1 Ω, 3.2 A: LSB_min = 3.2 / 32768 = 97.7 µA -> 100 µA; Cal = 0.04096 / (1e-4 · 0.1) = 4096; 320 mV -> PGA /8
    env = _calc("ina_shunt", part="ina219", i_max=3.2, r_shunt=0.1)
    r = env["result"]
    assert (r["current_lsb"]["value"], r["cal"], r["pga"]) == (0.0001, 4096, 8)
    assert any(a["key"] == "current_lsb" for a in env["assumptions"])


def test_ina219_shunt_over_range_and_bus_danger():
    env = _calc("ina_shunt", part="ina219", i_max=5, r_shunt=0.1, v_bus=30)
    # 5 A · 0.1 Ω = 500 mV > ±320 mV (PGA /8); 30 V > 26 V
    assert _status(env, "shunt_range") == "failed" and _status(env, "bus_voltage") == "failed"
    assert _codes(env) == {"shunt_over_range": "caution", "bus_over_abs_max": "danger"}


def test_ina219_odd_cal_loses_bit0():
    # Cal = trunc(0.04096 / (1e-4 · 0.0327)) = trunc(12525.99) = 12525 (odd) -> stored 12524 (FS0 void, p. 24)
    env = _calc("ina_shunt", part="ina219", i_max=3, r_shunt="32.7m", current_lsb="100u")
    assert (env["result"]["cal"], env["result"]["cal_register"]) == (12525, 12524)
    assert "cal_bit0_void" in _codes(env)


def test_ina226_cal_out_of_range():
    # 0.00512 / (1e-6 · 0.1) = 51200 > 32767 (FS14..FS0)
    env = _calc("ina_shunt", part="ina226", i_max=0.02, r_shunt=0.1, current_lsb="1u")
    assert _status(env, "cal_range") == "failed" and _codes(env)["cal_out_of_range"] == "caution"


def test_ina226_shunt_power_against_rating():
    env = _calc("ina_shunt", part="ina226", i_max=2, r_shunt=0.1, p_rating=0.25)
    # 2² · 0.1 = 0.4 W > 0.25 W; 200 mV > 81.92 mV
    assert _status(env, "shunt_power") == "failed" and _status(env, "shunt_range") == "failed"


def test_ina3221_step_and_range():
    # 40 µV / 0.1 Ω = 400 µA per LSB; 163.8 mV / 0.1 Ω = 1.638 A full scale
    r = _calc("ina_shunt", part="ina3221", i_max=1.5, r_shunt=0.1)["result"]
    assert r["current_step"]["value"] == pytest.approx(4e-4) and r["i_full_scale"]["value"] == pytest.approx(1.638)


def test_ina260_fixed_scaling_and_rating():
    env = _calc("ina_shunt", part="ina260", i_max=16, v_bus=24)
    # 16 A > ±15 A continuous; 16² · 4.5 mΩ = 1.152 W in the package
    assert _codes(env)["current_over_rating"] == "danger"
    assert env["result"]["p_shunt"]["value"] == pytest.approx(1.152)
    assert env["result"]["current_lsb"]["value"] == pytest.approx(0.00125)


@pytest.mark.parametrize("params", [
    {"part": "ina260", "i_max": 1, "r_shunt": 1}, {"part": "ina219", "i_max": 1}, {"part": "ina999", "i_max": 1},
    {"part": "ina3221", "i_max": 1, "r_shunt": 0.1, "current_lsb": "1m"}, {"part": "ina219", "i_max": 1,
                                                                          "r_shunt": 0.1, "pga": 3},
])
def test_ina_shunt_bad_input(params):
    env = calckit.run("ina_shunt", params)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args"


def test_round_lsb():
    assert [ina.round_lsb(x) for x in (457.78e-6, 97.7e-6, 1e-3, 2.1e-3, 6e-3)] == [5e-4, 1e-4, 1e-3, 5e-3, 1e-2]


# --- calculator current_sense ---------------------------------------------------------------------------------------
def test_acs712_20a_needs_a_divider():
    env = _calc("current_sense", variant="20a")
    r = env["result"]
    # VIOUT(Q) = 2.5 V; 2.5 ± 0.1 · 20 = 0.5 … 4.5 V > 3.6 V
    assert (r["v_out_zero"]["value"], r["v_out_min"]["value"], r["v_out_max"]["value"]) == (2.5, 0.5, 4.5)
    assert _codes(env)["needs_divider"] == "danger"
    sug = r["divider_suggestion"]
    v = 4.5 * sug["r2"]["value"] / (sug["r1"]["value"] + sug["r2"]["value"])
    assert v <= 3.3 + 1e-9 and sug["r1"]["value"] + sug["r2"]["value"] >= 4700  # VDD 3.3 V target, RLOAD ≥ 4.7 kΩ


def test_acs712_divider_given_and_load():
    ok = _calc("current_sense", variant="05b", r1="10k", r2="20k")
    # 3.425 V · 2/3 = 2.283 V
    assert ok["result"]["divider"]["v_adc_max"]["value"] == pytest.approx(3.425 * 2 / 3, rel=1e-5)
    assert _status(ok, "adc_input") == "passed" and _status(ok, "r_load") == "passed"
    low = _calc("current_sense", variant="30a", r1="1k", r2="2k")
    assert _codes(low)["load_too_low"] == "caution"  # 3 kΩ < 4.7 kΩ (p. 5)
    hot = _calc("current_sense", variant="20a", r1="1k", r2="10k")
    assert _codes(hot)["adc_over_limit"] == "danger"  # 4.5 · 10/11 = 4.09 V


def test_acs712_ratiometric_and_chip_limit():
    env = _calc("current_sense", variant="05b", v_cc=4.5, chip="esp32c3")
    # Sens = 0.185 · 4.5 / 5 = 0.1665 V/A; VIOUT(Q) 2.25 V
    assert env["result"]["sensitivity"]["value"] == pytest.approx(0.1665)
    assert env["result"]["v_out_zero"]["value"] == pytest.approx(2.25)
    assert any(a["key"] == "ratiometric" for a in env["assumptions"])
    assert "elec-ds-esp32c3" in {s["id"] for s in env["sources"]}
    assert _calc("current_sense", variant="05b", v_cc=3.3)["warnings"][0]["code"] == "vcc_out_of_range"


def test_current_sense_bad_input():
    for params in ({"variant": "10a"}, {"variant": "20a", "r1": "10k"}, {"variant": "20a", "chip": "esp8266"}):
        env = calckit.run("current_sense", params)
        assert env["ok"] is False and env["error"]["code"] == "invalid_args", params


def test_calculators_are_registered_in_group_sensing():
    meta = {m["kind"]: m for m in calckit.meta()}
    assert meta["ina_shunt"]["group"] == meta["current_sense"]["group"] == "sensing"
    assert calckit.problems() == []


# --- every calculator fact is quoted in the pinned excerpt ---------------------------------------------------------
def _calc_facts():
    for part, facts in ina.FACTS.items():
        for key, f in facts.items():
            yield f"{part}.{key}", f
    for key, f in ina.EXAMPLES.items():
        yield f"example.{key}", f
    for key, f in cs.FACTS.items():
        yield f"acs712.{key}", f


@pytest.mark.parametrize("name,fact", list(_calc_facts()), ids=lambda x: x if isinstance(x, str) else "")
def test_calculator_fact_is_in_the_excerpt(name, fact):
    by = ex.by_source("mod-powermon-*.txt")
    assert fact["source_id"] in by, name
    parts = fact["evidence"] if isinstance(fact["evidence"], list) else [fact["evidence"]]
    segs = [seg for e in by[fact["source_id"]] for seg in e.page_segments(fact["page"])]
    assert any(ex.find_parts_in_order(parts, seg) for seg in segs), (name, fact["page"], parts)
