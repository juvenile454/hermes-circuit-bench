"""Findings of a second probe with a real model in the generic electrical and bus rules.

2. mod.pullup_parallel: all pull-ups of an I²C line in parallel against the UM10204 window (calc.i2c_pullup)
3. facts.i_max (user current of the whole part) in mod.power_budget and the project validation
4. the budget text names only real consumers without current data (a peak counts as data)
5. facts.level_shifter in mod.level_out as in mod.level_in (the ESP side is 3.3 V, user-confirmed)
6. the danger text for a too-high pull-up suggests only a level shifter when a module needs VIH > 3.3 V
7. mod.unconnected: open mode_select pins with an internal pull are defined (A4988 MS1–MS3)
(1., the compaction, is tested in tests/test_m0_engine.py.)
Real catalog entries (bme280, ds3231/zs042, pcf8574, ws2812b, rfm95w, a4988) and synthetic ``f2_*`` modules with the
``tst-`` sources of tests/mod_fixtures.py.
"""
from __future__ import annotations

import pytest

import mod_fixtures as fx
import mod_projects40 as P
import modkit as k
from circuit_bench.bench_core import calc, modcheck, project
from circuit_bench.bench_core.contracts import BenchError

I2C = P.i2c()  # GPIO8 SDA, GPIO9 SCL
PROJ = {p["id"]: p for p in P.PROJECTS}


def run(parts, assignments=I2C, options=None, chip="esp32s3") -> modcheck.ModReport:
    rep = modcheck.run(chip=chip, assignments=assignments, parts=parts, options=options or {})
    assert rep is not None
    return rep


def of(rule_id, parts, assignments=I2C, options=None, chip="esp32s3") -> list[modcheck.Finding]:
    return [f for f in run(parts, assignments, options, chip).findings if f.rule_id == rule_id]


def bme(ref="U1", sdo="GND", **facts):
    return P.M(ref, "bme280", {"VDD": "3V3", "GND": "GND", "SDI": "SDA", "SCK": "SCL", "SDO": sdo},
               facts=facts) if facts else P.BME(ref, sdo=sdo)


# --- 2. parallel pull-ups ------------------------------------------------------------------------------------------
def test_parallel_pullups_below_r_min_are_a_caution():
    parts = [bme("U1", pullups="10k", pullups_to="3V3"), bme("U2", "3V3", pullups="10k", pullups_to="3V3"),
             *P.i2c_pullups(value="1k")]
    fs = of("mod.pullup_parallel", parts)
    assert len(fs) == 1  # SDA and SCL share one finding
    f = fs[0]
    assert (f.status, f.severity) == ("failed", "caution")
    assert f.message.startswith("SDA, SCL: parallel 1.00 kΩ ‖ 10.0 kΩ ‖ 10.0 kΩ = 833 Ω is below R_min 967 Ω")
    assert "remove pull-ups" in f.message and "may not reach a valid low" in f.message
    assert set(f.refs) == {"RSDA", "RSCL", "U1", "U2"} and f.source_ids == ["nxp-um10204"]
    r_min = calc.i2c_pullup(3.3)["result"]["r_min"]["display"]  # the one formula: calc.i2c_pullup
    assert f"R_min {r_min}" in f.message
    rep = run(parts)
    w = [w for w in rep.warnings if w["code"] == "mod_pullup_parallel"]
    assert len(w) == 1 and w[0]["severity"] == "caution"


def test_one_set_of_pullups_passes_with_the_window():
    f = of("mod.pullup_parallel", [bme(), *P.i2c_pullups()])
    assert [(x.status, x.severity) for x in f] == [("passed", None)]
    assert "4.70 kΩ within R_min 967 Ω" in f[0].message and "estimated" in f[0].message


def test_fast_mode_window_is_only_a_note():
    p = PROJ["p01_weather_ok"]  # every device allows 400 kHz: 4k7 lies above the Fast-mode R_max at 80 pF
    f = of("mod.pullup_parallel", p["parts"], p["assignments"], p["options"])
    assert [(x.status, x.severity) for x in f] == [("passed", None)]
    assert "for Fast-mode (400 kHz) R_max is 4.43 kΩ: keep 100 kHz or use a lower value" in f[0].message


def test_weak_pullups_above_standard_r_max_are_only_a_hint():
    f = of("mod.pullup_parallel", [bme(), *P.i2c_pullups(value="47k")])
    assert [(x.status, x.severity) for x in f] == [("failed", "info")]
    assert "above R_max" in f[0].message and "Standard-mode" in f[0].message


def test_unknown_board_pullups_leave_the_sum_not_checked():
    zs = P.M("U1", "ds3231", {"VCC": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL"}, variant="zs042")
    f = of("mod.pullup_parallel", [zs, *P.i2c_pullups()])
    assert [(x.status, x.severity) for x in f] == [("not_checked", None)]
    assert "U1 board pull-ups" in f[0].message and "facts.pullups" in f[0].message
    f = of("mod.pullup_parallel", [bme(onboard=["pullups"]), *P.i2c_pullups()])  # onboard without a value
    assert f[0].status == "not_checked" and "known pull-ups 4.70 kΩ" in f[0].message


def test_known_pullups_below_r_min_stay_a_caution_with_unknown_ones():
    zs = P.M("U1", "ds3231", {"VCC": "3V3", "GND": "GND", "SDA": "SDA", "SCL": "SCL"}, variant="zs042")
    f = of("mod.pullup_parallel", [zs, *P.i2c_pullups(value="680")])
    assert (f[0].status, f[0].severity) == ("failed", "caution")  # more in parallel only lowers R_eff
    assert "more unknown: U1 board pull-ups" in f[0].message


def test_pullup_voltage_sets_r_min():
    parts = [P.M("U1", "pcf8574", {**P.PCF_LCD, "SDA": "SDA", "SCL": "SCL"}, address="0x27"),
             P.M("U2", "hd44780", P.LCD_CONN), *P.i2c_pullups("5V", value="1k2")]
    f = of("mod.pullup_parallel", parts)
    assert f[0].severity == "caution" and "R_min 1.53 kΩ (pull-up 5.00 V" in f[0].message


def test_regression_projects_get_no_hard_parallel_finding():
    for p in P.PROJECTS:
        fs = of("mod.pullup_parallel", p["parts"], p["assignments"], p["options"], p["chip"])
        assert not [f for f in fs if f.severity in ("caution", "danger")], p["id"]


# --- 3. facts.i_max ------------------------------------------------------------------------------------------------
def leds(i_max=None, qty=60):
    facts = {} if i_max is None else {"i_max": i_max}
    return [{"ref": "LED1", "kind": "ic", "module": "ws2812b", "qty": qty, "facts": facts,
             "conn": {"VDD": "5V", "VSS": "GND", "DIN": "LED_DIN"}}]


LED_PIN = [{"pin": 4, "mode": "out", "net": "LED_DIN"}]


@pytest.mark.parametrize("i_max", [2.2, "2.2A", "2200 mA"])
def test_user_current_passes_against_a_larger_limit(i_max):
    f = of("mod.power_budget", leds(i_max), LED_PIN, {"rail_limits": {"5V": 4.0}})
    assert [(x.status, x.severity) for x in f] == [("passed", None)]
    assert "max 2.20 A" in f[0].message and "LED1 2.20 A from facts.i_max, user" in f[0].message


def test_user_current_above_the_limit_is_a_caution():
    f = of("mod.power_budget", leds(2.2), LED_PIN, {"rail_limits": {"5V": 2.0}})
    assert [(x.status, x.severity) for x in f] == [("failed", "caution")]
    assert "the maximum current 2.20 A exceeds the rail limit 2.00 A (user)" in f[0].message
    assert "(user)" in f[0].message


def test_without_i_max_the_led_chain_asks_for_it():
    f = of("mod.power_budget", leds(), LED_PIN, {"rail_limits": {"5V": 4.0}})
    assert (f[0].status, f[0].severity) == ("not_checked", "info")
    assert "LED1 (60 × ws2812b) has no current data" in f[0].message and "facts.i_max" in f[0].message


def test_i_max_is_for_the_whole_part_not_per_piece():
    one, many = (of("mod.power_budget", leds(1.0, q), LED_PIN, {"rail_limits": {"5V": 4.0}})[0] for q in (1, 60))
    assert "max 1.00 A" in one.message and "max 1.00 A" in many.message


def test_project_stores_i_max_in_amps():
    for given, stored in ((2.2, 2.2), ("2.2A", 2.2), ("350 mA", 0.35), (1, 1)):
        assert project._facts({"i_max": given}, "facts") == {"i_max": stored}
    for bad in ("abc", "2.2 V", -1, 0, 51, True, None, [1]):
        with pytest.raises(BenchError):
            project._facts({"i_max": bad}, "facts")


# --- 4. budget text -------------------------------------------------------------------------------------------------
def test_a_part_with_a_peak_current_is_not_reported_without_data():
    """p6: the RFM95W lists typ and peak, no max; the budget uses the peak and names nobody as 'no current data'."""
    lora = P.M("U2", "rfm95w", {"3.3V": "3V3", "GND": "GND"})
    f = of("mod.power_budget", [lora], [], {"rail_limits": {"3V3": 0.5}})
    assert [(x.status, x.severity) for x in f] == [("passed", None)] and "peak 120 mA" in f[0].message
    f = of("mod.power_budget", [lora], [], {"rail_limits": {"3V3": 0.1}})
    assert f[0].severity == "caution" and "the peak current 120 mA exceeds" in f[0].message


F2_FEED = {"id": "f2_switch", "title": "F2 load switch", "category": "sensor.light", "manufacturer": "Test",
           "kind": "ic", "source_ids": ["tst-5v-ds"],
           "pins": [{"name": "VIN", "signal": "supply"}, {"name": "VOUT", "signal": "power_out"},
                    {"name": "GND", "signal": "gnd"}],
           "supplies": {"VIN": {"min": fx.F(1.8), "max": fx.F(5.5)}}, "interfaces": [{"type": "digital"}]}
F2_DIODE = {**F2_FEED, "id": "f2_diode", "category": "discrete.diode", "title": "F2 diode",
            "pins": [{"name": "A", "signal": "supply"}, {"name": "K", "signal": "power_out"}],
            "supplies": {"A": {"min": fx.F(0.0), "max": fx.F(30.0)}}}
F2_NODATA = {**F2_FEED, "id": "f2_nodata", "title": "F2 consumer",
             "pins": [{"name": "VIN", "signal": "supply"}, {"name": "GND", "signal": "gnd"}]}
F2_TYP = {**F2_NODATA, "id": "f2_typ", "current": {"supply": "VIN", "typ": fx.F(0.01, "A")}}


def test_feeding_parts_and_discretes_are_no_consumers_without_data():
    parts = [k.mod("U1", "f2_switch", {"VIN": "3V3", "VOUT": "3V3", "GND": "GND"}),
             k.mod("D1", "f2_diode", {"A": "3V3", "K": "3V3"}),
             k.mod("U3", "f2_nodata", {"VIN": "3V3", "GND": "GND"}),
             k.mod("U4", "f2_typ", {"VIN": "3V3", "GND": "GND"})]
    rep = k.run(catalog=fx.catalog(F2_FEED, F2_DIODE, F2_NODATA, F2_TYP), electrical=fx.ESP, assignments=[],
                parts=parts, options={"rail_limits": {"3V3": 0.5}}, only=("mod.power_budget",))
    f = k.findings(rep, "mod.power_budget")[0]
    assert (f.status, f.severity) == ("not_checked", "info")
    assert "U3 has no current data; U4 has only a typical current" in f.message
    assert "U1" not in f.message and "D1" not in f.message


# --- 5. facts.level_shifter in level_out ----------------------------------------------------------------------------
def test_level_shifter_fact_counts_on_both_sides():
    pcf = P.M("U1", "pcf8574", {**P.PCF_LCD, "SDA": "SDA", "SCL": "SCL"}, address="0x27",
              facts={"level_shifter": True})
    rep = run([pcf, P.M("U2", "hd44780", P.LCD_CONN)])
    level = [f for f in rep.findings if f.rule_id in ("mod.level_in", "mod.level_out")]
    assert level and all(f.status == "passed" for f in level), [(f.rule_id, f.message) for f in level]
    out = [f for f in level if f.rule_id == "mod.level_out"]
    assert out and all("user-confirmed" in f.message for f in out)


F2_PP = {"id": "f2_pp", "title": "F2 5 V output", "category": "sensor.light", "manufacturer": "Test", "kind": "module",
         "source_ids": ["tst-5v-ds"],
         "pins": [{"name": "VCC", "signal": "supply"}, {"name": "GND", "signal": "gnd"},
                  {"name": "DOUT", "signal": "digital_out"}],
         "supplies": {"VCC": {"min": fx.F(4.5), "max": fx.F(5.5)}},
         "io": {"domain": "VCC", "outputs": "push_pull"}, "interfaces": [{"type": "digital"}]}


@pytest.mark.parametrize("facts,status", [({"level_shifter": True}, "passed"), ({}, "failed")])
def test_level_shifter_fact_on_a_push_pull_output(facts, status):
    rep = k.run(catalog=fx.catalog(F2_PP), electrical=fx.ESP, assignments=[k.assign("in", 5, "DOUT")],
                parts=[k.mod("U1", "f2_pp", {"VCC": "5V", "GND": "GND", "DOUT": "GPIO5"}, facts=facts)],
                only=("mod.level_out",))
    f = k.findings(rep, "mod.level_out")[0]
    assert f.status == status
    if facts:
        assert "level shifter on the board (facts.level_shifter, user-confirmed)" in f.message


# --- 6. danger text ------------------------------------------------------------------------------------------------
def test_danger_text_does_not_suggest_3v3_when_a_module_needs_more():
    p = PROJ["p14_lcd_pcf_5v_pullups"]
    rep = run(p["parts"], p["assignments"], p["options"])
    w = [w for w in rep.warnings if w["code"] == "mod_level_out" and w["severity"] == "danger"]
    assert w and all("pull up to 3V3" not in x["message"] for x in w)
    assert all("PCA9306" in x["message"] and "U1 (VIH 3.50 V)" in x["message"] for x in w)


def test_danger_text_keeps_3v3_when_every_module_reads_3v3():
    rep = run([bme(), *P.i2c_pullups("5V")])
    w = [w for w in rep.warnings if w["code"] == "mod_level_out" and w["severity"] == "danger"]
    assert w and all("pull up to 3V3 or use a level shifter" in x["message"] for x in w)


# --- 7. mode_select pins with an internal pull ----------------------------------------------------------------------
@pytest.mark.parametrize("variant", [None, "carrier"])
def test_open_mode_pins_with_internal_pull_are_defined(variant):
    p = PROJ["p04_robot_ok"]
    parts = [dict(x) for x in p["parts"]]
    conn = {kk: v for kk, v in parts[0]["conn"].items() if kk not in ("MS1", "MS2", "MS3")}
    parts[0] = {**parts[0], "conn": conn, **({"variant": variant} if variant else {})}
    if not variant:
        parts[0].pop("variant", None)
        parts[0]["conn"] = {**conn, "ROSC": "GND"}
    fs = of("mod.unconnected", parts, p["assignments"], p["options"])
    u1 = [f for f in fs if "U1" in f.refs]
    assert not [f for f in u1 if f.status == "failed" and "MS" in f.message], [f.message for f in u1]
    ok = [f for f in u1 if f.status == "passed" and "MS1, MS2, MS3" in f.message]
    assert ok and "open = internal pull-down → low (full step with all three open)" in ok[0].message


# --- rail sums: max never below typ (seen in a screenshot: "typ ≥ 3.9 mA · max ≥ 1.01 mA") ------------------------
def test_rail_max_counts_typ_of_a_part_without_max():
    from circuit_bench.bench_core.modrules import elec
    assert elec.floored({"typ": 0.0039, "max": None, "peak": None}) == {"typ": 0.0039, "max": 0.0039, "peak": 0.0039}
    assert elec.floored({"typ": 0.001, "max": 0.002, "peak": None})["peak"] == 0.002
    rep = k.run(assignments=k.i2c(), parts=[
        k.mod("U1", "bme280", {"SDI": "SDA0", "SCK": "SCL0", "SDO": "GND", "VDD": "3V3", "GND": "GND"}),
        k.mod("U2", "mpu6050", {"SDA": "SDA0", "SCL": "SCL0", "AD0": "GND", "VDD": "3V3", "GND": "GND"})])
    assert rep is not None
    rail = next(r for r in rep.result["rails"] if r["net"] == "3V3")
    assert rail["i_max"] >= rail["i_typ"] and rail["missing"] == ["U2"]
    assert rail["i_max"] == pytest.approx(0.000714 + 0.0039)
