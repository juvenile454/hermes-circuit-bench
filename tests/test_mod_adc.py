"""Module family adc: ADS1115, ADS1015, MCP3008, MCP4725, PCF8591, HX711 with the real catalog;
family rules mod.adc.ads_ain_vdd / mod.adc.ain_abs_max; calculator calc.adc_ext. Synthetic projects only.

The module entries' evidence is checked by tests/test_m0_modules_data.py; here: the limits that live in code
(modrules/adc.py, calcs/adc_ext.py) against tests/corpus/excerpts/mod-adc-*.txt.
"""
from __future__ import annotations

import json

import pytest

import excerpts as ex
import modkit as mk
from circuit_bench.bench_core import calckit, electrical, modcheck, modules, pins, sources
from circuit_bench.bench_core.calcs import adc_ext
from circuit_bench.bench_core.modrules import adc as adc_rules

ESP = electrical.get("esp32s3")
I2C = {"SDA": "SDA0", "SCL": "SCL0"}
ADS_RULE, AIN_RULE = "mod.adc.ads_ain_vdd", "mod.adc.ain_abs_max"
EXCERPT_OF = {"mod-adc-ads1115-ds": "mod-adc-ads1115.txt", "mod-adc-ads1015-ds": "mod-adc-ads1015.txt",
              "mod-adc-mcp3008-ds": "mod-adc-mcp3008.txt", "mod-adc-mcp4725-ds": "mod-adc-mcp4725.txt",
              "mod-adc-pcf8591-ds": "mod-adc-pcf8591.txt", "mod-adc-hx711-ds": "mod-adc-hx711.txt"}


def _cited(source_id: str, page: int, parts: list[str]) -> bool:
    e = ex.parse(ex.EXCERPTS / EXCERPT_OF[source_id])
    assert e.source_id == source_id
    return any(ex.find_parts_in_order(parts, seg) for seg in e.page_segments(page))


def _run(*parts, options=None, assignments=None, only=None):
    return mk.run(electrical=ESP, assignments=mk.i2c() if assignments is None else assignments, parts=list(parts),
                  options=options, only=only)


def _addresses(rep):
    return {d["ref"]: d["address"] for b in rep.result["buses"] for s in b["segments"] for d in s["devices"]}


def _found(rep, rule_id, status=None):
    return [(f.status, f.severity) for f in mk.findings(rep, rule_id) if status is None or f.status == status]


def ads(ref="U1", part="ads1115", **conn):
    return mk.mod(ref, part, {**I2C, "VDD": "3V3", "GND": "GND", "ADDR": "GND", **conn})


def pcf(ref="U5", a2="GND", a1="GND", a0="GND", **conn):
    return mk.mod(ref, "pcf8591", {**I2C, "VDD": "3V3", "A2": a2, "A1": a1, "A0": a0, **conn})


# --- catalog and citations ------------------------------------------------------------------------------------------
def test_all_six_parts_are_in_the_catalog_with_their_class():
    cat = modules.catalog()
    want = {"ads1115": "A", "ads1015": "A", "mcp3008": "A", "mcp4725": "A", "pcf8591": "A", "hx711": "A2"}
    for mid, cls in want.items():
        m = cat.get(mid)
        assert m["_wp"] == "adc" and m["_class"] == cls, mid
    assert not [p for p in cat.problems if p.startswith("adc.json")]
    assert cat.get("mcp4725")["category"] == "dac"


def test_limits_in_code_quote_the_excerpts():
    for mid, lim in adc_rules.AIN_LIMITS.items():
        for key in ("abs_ev", "op_ev"):
            sid, page, parts = lim[key]
            assert sid in modules.catalog().get(mid)["source_ids"], (mid, key)
            assert _cited(sid, page, parts), (mid, key)
    for pid, lim in adc_ext.LIMITS.items():
        for key, (page, line) in lim["ev"].items():
            assert _cited(lim["source_id"], page, [line]), (pid, key)
    for pid, tab in adc_ext.ADS_PGA.items():
        assert _cited(tab["source_id"], tab["formula_page"], [tab["formula_ev"]]), pid
        for _, _, line in tab["steps"]:
            assert _cited(tab["source_id"], tab["formula_page"], [line]), (pid, line)


def test_lsb_table_matches_the_formula():
    for tab in adc_ext.ADS_PGA.values():
        for fs, lsb, _ in tab["steps"]:
            assert 2 * fs / 2 ** tab["bits"] == pytest.approx(lsb, rel=1e-9)


def test_sources_resolve():
    for sid in EXCERPT_OF:
        assert sources.get(sid)["class"] in ("A", "A2")


# --- ADS1115 / ADS1015: address select with the bus nets, conflicts --------------------------------------------------
@pytest.mark.parametrize("part", ["ads1115", "ads1015"])
def test_ads_addr_pin_selects_all_four_addresses(part):
    rep = _run(ads("U1", part, ADDR="GND"), ads("U2", part, ADDR="3V3"), ads("U3", part, ADDR="SDA0"),
               ads("U4", part, ADDR="SCL0"))
    assert _addresses(rep) == {"U1": "0x48", "U2": "0x49", "U3": "0x4a", "U4": "0x4b"}
    assert "mod_address_conflict" not in mk.codes(rep)


def test_ads_addr_open_falls_back_to_the_default_and_collides():
    rep = _run(ads("U1"), mk.mod("U2", "ads1115", {**I2C, "VDD": "3V3", "GND": "GND"}))
    assert _addresses(rep) == {"U1": "0x48", "U2": "0x48"}
    assert ("failed", "caution") in _found(rep, "mod.address_conflict")


def test_ads1115_and_pcf8591_share_0x48():
    rep = _run(ads("U1"), pcf("U5"))
    assert _addresses(rep) == {"U1": "0x48", "U5": "0x48"}
    assert ("failed", "caution") in _found(rep, "mod.address_conflict")
    rep = _run(ads("U1"), pcf("U5", a0="3V3"))  # PCF8591 moved to 0x49
    assert _addresses(rep)["U5"] == "0x49" and "mod_address_conflict" not in mk.codes(rep)


def test_ads1115_and_an_ina219_share_0x48():
    """INA219 spans 0x40–0x4F; with A1/A0 at GND/SDA… it answers at 0x48 like an ADS1115 at GND."""
    cat = modules.catalog()
    if cat.has("ina219"):
        catalog = cat
        ina = mk.mod("U7", "ina219", {**I2C, "VS": "3V3", "GND": "GND"}, address="0x48")
    else:  # stand-in without the powermon catalog entry: same address range, explicit address
        stand_in = {"id": "tst_ina219", "title": "INA219 stand-in", "category": "power.monitor",
                    "manufacturer": "Test", "kind": "ic", "source_ids": ["mod-adc-ads1115-ds"],
                    "pins": [{"name": "SDA", "signal": "i2c_sda"}, {"name": "SCL", "signal": "i2c_scl"},
                             {"name": "VS", "signal": "supply"}, {"name": "GND", "signal": "gnd"}],
                    "interfaces": [{"type": "i2c", "addresses": {"value": [f"0x{a:02x}" for a in range(0x40, 0x50)],
                                                                 "page": 20, "evidence": "GND 1001000b"}}]}
        raw = json.loads((modules.MODULES_DIR / "adc.json").read_text(encoding="utf-8"))["modules"]
        catalog = modules.Catalog.from_entries([*raw, stand_in])
        assert catalog.problems == []
        ina = mk.mod("U7", "tst_ina219", {**I2C, "VS": "3V3", "GND": "GND"}, address="0x48")
    rep = mk.run(catalog=catalog, electrical=ESP, assignments=mk.i2c(), parts=[ads("U1"), ina])
    assert ("failed", "caution") in _found(rep, "mod.address_conflict")


@pytest.mark.parametrize("part", ["ads1115", "ads1015"])
def test_ads_supply(part):
    rep = _run(ads("U1", part, VDD="5V"))
    assert _found(rep, "mod.supply_range") == [("passed", None)]
    rep = _run(ads("U1", part, VDD="V8"), options={"rails": {"V8": 8.0}})
    assert ("failed", "danger") in _found(rep, "mod.supply_range")  # above 7 V absolute maximum


# --- family rule mod.adc.ads_ain_vdd --------------------------------------------------------------------------------
@pytest.mark.parametrize("part", ["ads1115", "ads1015"])
def test_ads_ain_on_5v_with_vdd_3v3_is_danger(part):
    rep = _run(ads("U1", part, AIN0="5V"))
    assert _found(rep, ADS_RULE) == [("failed", "danger")]
    msg = mk.findings(rep, ADS_RULE)[0].message
    assert "AIN0" in msg and "3.60 V" in msg
    assert mk.by_rule(rep, ADS_RULE)[0]["code"] == "mod_adc_ads_ain_vdd"


def test_ads_ain_between_vdd_and_abs_max_is_caution():
    rep = _run(ads("U1", AIN1="V3"), options={"rails": {"V3": 3.5}})
    assert _found(rep, ADS_RULE) == [("failed", "caution")]


def test_ads_ain_at_vdd_or_unknown_nets_pass_or_stay_silent():
    assert _found(_run(ads("U1", AIN0="3V3", AIN1="GND")), ADS_RULE) == [("passed", None)]
    assert _found(_run(ads("U1", VDD="5V", AIN0="5V")), ADS_RULE) == [("passed", None)]
    assert _found(_run(ads("U1", AIN0="SENSE")), ADS_RULE) == []  # signal net without a voltage: no claim
    assert _found(_run(ads("U1", VDD="VX", AIN0="5V")), ADS_RULE) == [("not_checked", "info")]


# --- MCP3008 ----------------------------------------------------------------------------------------------------------
def mcp3008(**conn):
    spi = {"CLK": "SCK0", "DIN": "MOSI0", "DOUT": "MISO0", "CS/SHDN": "CS0"}
    return mk.mod("U3", "mcp3008", {**spi, "VDD": "3V3", **conn})


SPI = [mk.assign("spi_sck", 12, "SCK0"), mk.assign("spi_mosi", 11, "MOSI0"), mk.assign("spi_miso", 13, "MISO0"),
       mk.assign("spi_cs", 10, "CS0")]


def test_mcp3008_supply_and_inputs():
    rep = _run(mcp3008(), assignments=SPI)
    assert ("passed", None) in _found(rep, "mod.supply_range") and not mk.findings(rep, AIN_RULE)
    rep = _run(mcp3008(CH0="5V"), assignments=SPI)
    assert _found(rep, AIN_RULE) == [("failed", "danger")]  # 5 V > 3.3 V + 0.6 V
    rep = _run(mcp3008(VREF="VR", CH2="3V3"), assignments=SPI, options={"rails": {"VR": 2.5}})
    assert _found(rep, AIN_RULE) == [("failed", "caution")]  # above VREF: clips at 1023
    rep = _run(mcp3008(VREF="VR"), assignments=SPI, options={"rails": {"VR": 0.2}})
    assert ("failed", "caution") in _found(rep, "mod.supply_range")  # VREF below 0.25 V


def test_mcp3008_entry_spi():
    m = modules.catalog().get("mcp3008")
    spi = m["interfaces"][0]
    assert spi["type"] == "spi" and spi["mode"] == 0 and spi["f_max_hz"]["value"] == 1_350_000


# --- MCP4725 ----------------------------------------------------------------------------------------------------------
def dac(ref, a0, variant=None):
    return mk.mod(ref, "mcp4725", {**I2C, "VDD": "3V3", "VSS": "GND", "A0": a0}, variant=variant)


def test_mcp4725_address_pin_and_variants():
    rep = _run(dac("U1", "GND"), dac("U2", "3V3"), dac("U3", "GND", "a1"), dac("U4", "3V3", "a3"))
    assert _addresses(rep) == {"U1": "0x60", "U2": "0x61", "U3": "0x62", "U4": "0x67"}
    assert "mod_address_conflict" not in mk.codes(rep)
    rep = _run(dac("U1", "GND"), dac("U2", "GND"))
    assert ("failed", "caution") in _found(rep, "mod.address_conflict")


def test_mcp4725_supply():
    assert _found(_run(dac("U1", "GND")), "mod.supply_range") == [("passed", None)]
    rep = _run(dac("U1", "GND") | {"conn": {**I2C, "VDD": "V7", "VSS": "GND", "A0": "GND"}},
               options={"rails": {"V7": 7.0}})
    assert ("failed", "danger") in _found(rep, "mod.supply_range")  # 6.5 V absolute maximum


# --- PCF8591 ----------------------------------------------------------------------------------------------------------
def test_pcf8591_three_address_pins():
    rep = _run(pcf("U1"), pcf("U2", a0="3V3"), pcf("U3", a2="3V3", a1="3V3", a0="3V3"), pcf("U4", a1="3V3"))
    assert _addresses(rep) == {"U1": "0x48", "U2": "0x49", "U3": "0x4f", "U4": "0x4a"}


def test_pcf8591_limits_the_bus_to_100k():
    rep = _run(ads("U1", ADDR="3V3"))
    assert rep.result["buses"][0]["f_max_hz"] == 400_000
    rep = _run(ads("U1", ADDR="3V3"), pcf("U5"))
    assert rep.result["buses"][0]["f_max_hz"] == 100_000
    if "mod.bus_speed" in modcheck.RULES:  # generic bus rule: the bus limit shows as a check
        assert mk.check_of(rep, "mod.bus_speed") is not None


def test_pcf8591_inputs_and_vref():
    rep = _run(pcf("U5", AIN0="5V"))
    assert _found(rep, AIN_RULE) == [("failed", "danger")]  # 5 V > 3.3 V + 0.5 V
    rep = _run(pcf("U5", AIN0="V36"), options={"rails": {"V36": 3.6}})
    assert _found(rep, AIN_RULE) == [("failed", "caution")]
    rep = _run(pcf("U5", VREF="VR"), options={"rails": {"VR": 1.2}})
    assert ("failed", "caution") in _found(rep, "mod.supply_range")  # VREF below 1.6 V


# --- HX711 ------------------------------------------------------------------------------------------------------------
def hx(**conn):
    base = {"DVDD": "3V3", "AVDD": "5V", "VSUP": "5V", "PD_SCK": "HX_SCK", "DOUT": "HX_DT"}
    return mk.mod("U6", "hx711", {**base, **conn})


HX_GPIO = [mk.assign("out", 4, "HX_SCK"), mk.assign("in", 5, "HX_DT")]


def test_hx711_supply():
    rep = _run(hx(), assignments=HX_GPIO)
    assert {s for s, _ in _found(rep, "mod.supply_range")} == {"passed"}
    rep = _run(hx(AVDD="V6", VSUP="V6"), assignments=HX_GPIO, options={"rails": {"V6": 6.0}})
    assert ("failed", "caution") in _found(rep, "mod.supply_range")  # above 5.5 V; no absolute maximum given


def test_hx711_is_not_an_i2c_device():
    m = modules.catalog().get("hx711")
    assert [i["type"] for i in m["interfaces"]] == ["digital"]
    assert _run(hx(), assignments=HX_GPIO).result["buses"] == []


# --- through pins.check ---------------------------------------------------------------------------------------------
def test_pins_check_reports_the_ain_danger():
    env = pins.check("esp32s3", mk.i2c(), parts=[ads("U1", AIN0="5V")], options={})
    assert env["ok"]
    w = [w for w in env["warnings"] if w["code"] == "mod_adc_ads_ain_vdd"]
    assert w and w[0]["severity"] == "danger" and "mod-adc-ads1115-ds" in w[0]["source_ids"]


# --- calculator calc.adc_ext ------------------------------------------------------------------------------------------
def _calc(**p):
    return calckit.run("adc_ext", p)


def _status(env):
    return {c["id"].removeprefix("calc.adc_ext."): c["status"] for c in env["checks"]}


def test_calc_is_registered_in_sensing():
    meta = next(m for m in calckit.meta() if m["kind"] == "adc_ext")
    assert meta["group"] == "sensing" and [p["name"] for p in meta["params"]] == ["v_in_max", "vdd", "part", "pga",
                                                                                   "vref"]
    assert calckit.problems() == []


def test_calc_ads1115_picks_the_smallest_fitting_pga():
    env = _calc(part="ads1115", v_in_max=3.0, vdd=3.3)
    r = env["result"]
    assert env["ok"] and r["pga"]["fsr"] == "±4.096 V" and r["lsb"]["value"] == pytest.approx(125e-6)
    assert r["code_at_v_in_max"] == 24000 and r["code_max"] == 32767
    assert set(_status(env).values()) == {"passed"} and env["warnings"] == []
    assert [s["id"] for s in env["sources"]] == ["mod-adc-ads1115-ds"]
    assert "calc.divider" in r["divider_hint"]
    env = _calc(part="ads1115", v_in_max="200m", vdd=3.3)
    assert env["result"]["pga"]["fsr"] == "±0.256 V" and env["result"]["lsb"]["value"] == pytest.approx(7.8125e-6)


def test_calc_ads1115_input_above_vdd_plus_0v3_is_danger():
    env = _calc(part="ads1115", v_in_max=5.0, vdd=3.3)
    assert _status(env)["abs_max"] == "failed"
    assert [(w["code"], w["severity"]) for w in env["warnings"]] == [("adc_input_abs_max", "danger")]
    env = _calc(part="ads1115", v_in_max=3.5, vdd=3.3)  # above VDD, below VDD + 0.3 V
    assert _status(env)["abs_max"] == "passed" and _status(env)["input_range"] == "failed"
    assert [(w["code"], w["severity"]) for w in env["warnings"]] == [("adc_input_range", "caution")]
    assert any(a["key"] == "fsr_above_vdd" for a in env["assumptions"])


def test_calc_ads1015_with_a_given_pga_that_clips():
    env = _calc(part="ads1015", v_in_max=1.5, vdd=3.3, pga="±1.024V")
    r = env["result"]
    assert r["lsb"]["value"] == pytest.approx(0.5e-3) and r["code_at_v_in_max"] == 2047
    assert _status(env)["fsr"] == "failed" and env["warnings"][0]["code"] == "adc_clips"
    assert _calc(part="ads1015", v_in_max=1.0, vdd=3.3, pga=2.048)["result"]["code_at_v_in_max"] == 1000


def test_calc_mcp3008_code():
    env = _calc(part="mcp3008", v_in_max=3.0, vdd=3.3)
    r = env["result"]
    assert r["code_at_v_in_max"] == 930 and r["lsb"]["value"] == pytest.approx(3.3 / 1024, rel=1e-5)
    assert any(a["key"] == "vref" for a in env["assumptions"])
    env = _calc(part="mcp3008", v_in_max=3.5, vdd=3.3, vref=2.5)
    assert env["result"]["code_at_v_in_max"] == 1023 and _status(env)["input_range"] == "failed"
    env = _calc(part="mcp3008", v_in_max=1.0, vdd=3.3, vref=0.2)
    assert _status(env)["vref_range"] == "failed"
    env = _calc(part="mcp3008", v_in_max=4.0, vdd=3.3)
    assert [(w["code"], w["severity"]) for w in env["warnings"]] == [("adc_input_abs_max", "danger")]


def test_calc_pcf8591_code():
    env = _calc(part="pcf8591", v_in_max=2.0, vdd=3.3)
    assert env["result"]["code_at_v_in_max"] == 155 and env["result"]["code_max"] == 255
    assert any(a["key"] == "i2c" for a in env["assumptions"])
    assert _status(_calc(part="pcf8591", v_in_max=1.0, vdd=3.3, vref=1.2))["vref_range"] == "failed"


def test_calc_vdd_range():
    assert _status(_calc(part="ads1115", v_in_max=1.0, vdd=1.8))["vdd_range"] == "failed"
    env = _calc(part="ads1115", v_in_max=1.0, vdd=7.5)
    assert ("adc_vdd_abs_max", "danger") in [(w["code"], w["severity"]) for w in env["warnings"]]


@pytest.mark.parametrize("params,text", [
    ({"part": "ads1115", "v_in_max": 1, "vdd": 3.3, "vref": 2.0}, "internal reference"),
    ({"part": "mcp3008", "v_in_max": 1, "vdd": 3.3, "pga": "2.048"}, "no PGA"),
    ({"part": "ads1115", "v_in_max": 1, "vdd": 3.3, "pga": "3.0"}, "pga must be one of"),
    ({"part": "hx711", "v_in_max": 0.01, "vdd": 5}, "part must be one of"),
    ({"part": "ads1115", "v_in_max": 70, "vdd": 3.3}, "60 V"),
])
def test_calc_bad_inputs(params, text):
    env = _calc(**params)
    assert not env["ok"] and text in env["error"]["message"]
