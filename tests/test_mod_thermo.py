"""Module family thermo: MAX31855, MAX6675, MAX31865, NTCLE100E3 with the real catalog; family rules
mod.thermo.max31855_tminus / max6675_tminus / max6675_vcc; calculators calc.rtd and calc.ntc. Synthetic projects only.

The module entries' evidence is checked by tests/test_m0_modules_data.py; here: the numbers that live in code or in
data/parts/thermo.json (calcs/rtd.py, calcs/ntc.py) against tests/corpus/excerpts/mod-thermo-*.txt, and the formulas
against the datasheet tables (MAX31865 Table 9, Vishay R/T tables).
"""
from __future__ import annotations

import json
import re

import pytest

import excerpts as ex
import modkit as mk
from circuit_bench.bench_core import calckit, electrical, modules, parts, sources
from circuit_bench.bench_core.calcs import ntc as ntc_calc
from circuit_bench.bench_core.calcs import rtd as rtd_calc

ESP = electrical.get("esp32s3")
EXCERPT_OF = {"mod-thermo-max31855-ds": "mod-thermo-max31855.txt", "mod-thermo-max6675-ds": "mod-thermo-max6675.txt",
              "mod-thermo-max31865-ds": "mod-thermo-max31865.txt",
              "mod-thermo-ntcle100e3-ds": "mod-thermo-ntcle100e3.txt"}
TMINUS_55, TMINUS_75, VCC_75 = "mod.thermo.max31855_tminus", "mod.thermo.max6675_tminus", "mod.thermo.max6675_vcc"
SPI = {"SCK": "SCK0", "SO": "MISO0", "CS": "CS0", "GND": "GND"}


def _cited(source_id: str, page: int, evidence) -> bool:
    want = [evidence] if isinstance(evidence, str) else list(evidence)
    e = ex.parse(ex.EXCERPTS / EXCERPT_OF[source_id])
    assert e.source_id == source_id
    return any(ex.find_parts_in_order(want, seg) for seg in e.page_segments(page))


def _run(*prts, options=None, only=None):
    return mk.run(electrical=ESP, assignments=[], parts=list(prts), options=options, only=only)


def _found(rep, rule_id, status=None):
    return [(f.status, f.severity) for f in mk.findings(rep, rule_id) if status is None or f.status == status]


def tc55(ref="U1", **conn):
    return mk.mod(ref, "max31855", {**SPI, "VCC": "3V3", "T+": "TC_P", "T-": "TC_N", **conn})


def tc75(ref="U2", facts=None, **conn):
    return mk.mod(ref, "max6675", {**SPI, "VCC": "3V3", "T+": "TC_P", **conn}, facts=facts)


def rtd65(ref="U3", **conn):
    c = {"SCLK": "SCK0", "SDI": "MOSI0", "SDO": "MISO0", "CS": "CS1", "VDD": "3V3", "DVDD": "3V3", "GND1": "GND",
         "GND2": "GND", "DGND": "GND", **conn}
    return mk.mod(ref, "max31865", c)


def _ok(env):
    assert env["ok"], env.get("error")
    return env["result"]


def _checks(env):
    return {c["id"].rsplit(".", 1)[1]: c["status"] for c in env["checks"]}


def _warn(env):
    return {w["code"]: w["severity"] for w in env["warnings"]}


# --- catalog, sources, citations -------------------------------------------------------------------------------------
def test_all_four_parts_are_in_the_catalog_with_their_class():
    cat = modules.catalog()
    want = {"max31855": "A1", "max6675": "A2", "max31865": "A1", "ntcle100e3": "A"}
    for mid, cls in want.items():
        m = cat.get(mid)
        assert m["_wp"] == "thermo" and m["_class"] == cls and m["category"] == "sensor.temperature", mid
        assert m["kind"] == "ic", mid
    assert not [p for p in cat.problems if p.startswith("thermo.json")]
    assert cat.get("ntcle100e3103")["id"] == "ntcle100e3"
    assert cat.get("max31855k")["id"] == "max31855"


def test_sources_resolve_with_class_and_hash():
    raw = json.loads((sources.SOURCES_DIR / "mod-thermo.json").read_text(encoding="utf-8")) \
        if hasattr(sources, "SOURCES_DIR") else None
    for sid in EXCERPT_OF:
        s = sources.get(sid)
        assert s["class"] in ("A", "A1", "A2")
    if raw is not None:
        for s in raw:
            assert re.search(r"sha256 [0-9a-f]{64}", s["note"]), s["id"]
            if s["class"] == "A1":
                assert s["url"].startswith("https://web.archive.org/web/") and "id_/https://www.analog.com/" in s["url"]
            if s["class"] == "A2":
                assert s["title"].endswith("copy hosted by Adafruit")


def test_spi_facts():
    cat = modules.catalog()
    it65 = cat.get("max31865")["interfaces"][0]
    assert it65["mode"] == 1 and it65["f_max_hz"]["value"] == 5e6
    assert _cited("mod-thermo-max31865-ds", 16, "The MAX31865 supports SPI modes 1 and 3.")
    assert _cited("mod-thermo-max31865-ds", 17, "Note: CPHA bit polarity must be set to 1.")
    it55 = cat.get("max31855")["interfaces"][0]
    assert "mode" not in it55 and it55["f_max_hz"]["value"] == 5e6  # no mode number in the datasheet
    assert _cited("mod-thermo-max31855-ds", 9, ["are presented to the SO pin within t D0 of the falling edge", "of SCK."])
    it75 = cat.get("max6675")["interfaces"][0]
    assert "mode" not in it75 and it75["f_max_hz"]["value"] == 4.3e6


def test_rtd_constants_quote_the_excerpt():
    for key, (_value, page, line) in {**rtd_calc.CVD, **rtd_calc.LIMITS}.items():
        assert _cited(rtd_calc.SOURCE, page, line), key
    for key, (page, line) in rtd_calc.FORMULA_EV.items():
        assert _cited(rtd_calc.SOURCE, page, line), key
    assert _cited(rtd_calc.SOURCE, 10, "P +850NC")  # CVD range end


def _nums(line: str) -> list[float]:
    """Numbers of a Vishay parameter line: '- 14.6337' is −14.6337 (pypdf puts a space after the minus)."""
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:E[+-]\d+)?", re.sub(r"- (?=\d)", "-", line))]


def test_ntc_part_data_quotes_the_excerpt():
    ids = parts.ids_of("ntc")
    assert len(ids) == 25 and "NTCLE100E3103" in ids
    e = ex.parse(ex.EXCERPTS / EXCERPT_OF["mod-thermo-ntcle100e3-ds"])
    p4 = [line for seg in e.page_segments(4) for line in seg]
    for pid in ids:
        p = parts.find(pid, "ntc")
        sid = p["source_id"]
        for key in ("r25", "b25_85", "b_tol", "dissipation", "p_max", "zero_power_fraction", "v_max", "t_op",
                    "t_short_max"):
            assert _cited(sid, p[key]["page"], p[key]["evidence"]), (pid, key)
        head = re.match(r"^([\d ]+?) (?:2, 3, 5|5) ", p["r25"]["evidence"])
        assert head and float(head.group(1).replace(" ", "")) == p["r25"]["value"], pid
        assert str(p["b25_85"]["value"]) in p["b25_85"]["evidence"].split()
        for seg in p["steinhart_hart"]:
            assert _cited(sid, 4, seg["evidence"]), pid
            # the 8 constants are the last 8 numbers of the cited parameter line (A … D1)
            first = seg["evidence"][-1] if len(seg["evidence"]) > 1 else seg["evidence"][0]
            line = next(x for x in p4 if first in x)
            assert _nums(line)[-8:] == pytest.approx([seg[k] for k in ("A", "B", "C", "D", "A1", "B1", "C1", "D1")]), pid
        for row in p.get("rt_table", []):
            assert _cited(sid, row["page"], row["evidence"]), (pid, row)


def test_dissipation_factor_by_r25():
    assert parts.find("NTCLE100E3103", "ntc")["dissipation"]["value"] == 0.007
    assert parts.find("NTCLE100E3681", "ntc")["dissipation"]["value"] == 0.0085
    assert parts.find("ntcle100e3103jb0", "ntc")["id"] == "NTCLE100E3103"


# --- MAX31855: T- must not be grounded --------------------------------------------------------------------------
def test_max31855_tminus_on_the_thermocouple_passes():
    rep = _run(tc55(), only=(TMINUS_55,))
    assert _found(rep, TMINUS_55) == [("passed", None)]


@pytest.mark.parametrize("net", ["GND", "3V3"])
def test_max31855_tminus_on_a_rail_fails(net):
    rep = _run(tc55(**{"T-": net}), only=(TMINUS_55,))
    assert _found(rep, TMINUS_55) == [("failed", "caution")]
    f = mk.findings(rep, TMINUS_55)[0]
    assert f.source_ids == ["mod-thermo-max31855-ds"]
    if net == "GND":
        assert "Do not connect to GND" in f.message


def test_max31855_tminus_open_is_not_checked():
    p = tc55()
    del p["conn"]["T-"]
    rep = _run(p, only=(TMINUS_55,))
    assert _found(rep, TMINUS_55) == [("not_checked", None)]


def test_max31855_supply():
    assert _found(_run(tc55(), only=("mod.supply_range",)), "mod.supply_range") == [("passed", None)]
    rep = _run(tc55(VCC="5V"), only=("mod.supply_range",))
    assert ("failed", "danger") in _found(rep, "mod.supply_range")  # 5 V > 4.0 V absolute maximum


# --- MAX6675: T- grounded, VCC remedy ---------------------------------------------------------------------------
def test_max6675_tminus_defaults_to_gnd_and_passes():
    rep = _run(tc75(), only=(TMINUS_75,))
    assert _found(rep, TMINUS_75) == [("passed", None)]


@pytest.mark.parametrize("net", ["TC_N", "3V3"])
def test_max6675_tminus_not_grounded_fails(net):
    rep = _run(tc75(**{"T-": net}), only=(TMINUS_75,))
    assert _found(rep, TMINUS_75) == [("failed", "caution")]


def test_max6675_vcc_3v3_passes_and_5v_gives_the_remedy():
    assert _found(_run(tc75(), only=(VCC_75,)), VCC_75) == [("passed", None)]
    rep = _run(tc75(VCC="5V"), only=(VCC_75, "mod.supply_range"))
    assert _found(rep, VCC_75) == [("failed", "info")]
    msg = mk.findings(rep, VCC_75)[0].message
    assert "3.0" in msg and "3.3 V" in msg and "3.5" in msg  # range from the data, VIH 0.7 × 5 V
    assert _found(rep, "mod.supply_range") == [("passed", None)]  # 5 V is inside 3.0–5.5 V
    rep = _run(tc75(VCC="5V", facts={"level_shifter": True}), only=(VCC_75,))
    assert _found(rep, VCC_75) == [("passed", None)]


def test_max6675_vcc_without_esp_data_is_not_checked():
    no_esp = {"esp32s3": {**ESP, "v_in_max": None}}
    rep = mk.run(electrical=no_esp, assignments=[], parts=[tc75(VCC="5V")], only=(VCC_75,))
    assert _found(rep, VCC_75) == [("not_checked", None)]


def test_max6675_supply_above_abs_max():
    rep = _run(tc75(VCC="V7"), options={"rails": {"V7": 7.0}}, only=("mod.supply_range",))
    assert ("failed", "danger") in _found(rep, "mod.supply_range")  # > 6 V absolute maximum


def test_max6675_at_5v_drives_the_esp_above_its_input_maximum():
    # the level rules need the bus lines on ESP pins
    spi = [mk.assign("spi_sck", 12, "SCK0"), mk.assign("spi_miso", 13, "MISO0"), mk.assign("spi_cs", 10, "CS0")]
    rep = mk.run(electrical=ESP, assignments=spi, parts=[tc75(VCC="5V")], only=("mod.level_out", "mod.level_in"))
    assert _found(rep, "mod.level_out") == [("failed", "danger")]  # SO high = 5 V > 3.6 V input maximum
    assert _found(rep, "mod.level_in") == [("failed", "caution")]  # SCK, CS: VIH 3.5 V above the 3.3 V high


# --- MAX31865 ----------------------------------------------------------------------------------------------------
def test_max31865_supply():
    rep = _run(rtd65(), only=("mod.supply_range",))
    assert set(_found(rep, "mod.supply_range")) == {("passed", None)}
    rep = _run(rtd65(VDD="5V", DVDD="5V"), only=("mod.supply_range",))
    assert ("failed", "danger") in _found(rep, "mod.supply_range")


def test_max31865_and_max31855_on_one_bus_have_no_address_conflict():
    rep = _run(tc55(), rtd65(), only=("mod.address_conflict",))
    assert "mod_address_conflict" not in mk.codes(rep)  # SPI parts carry no I²C address


# --- NTCLE100E3 in a project ----------------------------------------------------------------------------------------
def test_ntc_is_a_two_pin_analog_part():
    m = modules.catalog().get("ntcle100e3")
    assert [p["name"] for p in m["pins"]] == ["1", "2"] and m["interfaces"][0]["type"] == "analog"
    rep = _run(mk.mod("RT1", "ntcle100e3", {"1": "NTC_ADC", "2": "GND"}), only=("mod.supply_range",))
    assert _found(rep, "mod.supply_range") == []  # no supply pin


# --- calc.rtd -----------------------------------------------------------------------------------------------------
TABLE9 = [(-200, 18.52, 0x0BDA, 1517), (-100, 60.26, 0x2690, 4936), (0, 100.00, 0x4000, 8192),
          (100, 138.51, 0x58A4, 11346), (200, 175.86, 0x708C, 14406), (400, 247.09, 0x9E24, 20242),
          (550, 297.49, 0xBE64, 24370)]


def test_rtd_constants_reproduce_table_9():
    for t, r, reg, code in TABLE9:
        res = _ok(calckit.run("rtd", {"t": t}))
        assert res["r_rtd"]["value"] == pytest.approx(r, abs=0.006), t
        assert res["code"] == code and res["register"] == f"0x{reg:04X}", t
        back = _ok(calckit.run("rtd", {"code": code}))
        assert back["t"]["value"] == pytest.approx(t, abs=0.05), t
        assert back["r_rtd"]["value"] == pytest.approx(code * 400 / 2 ** 15, rel=1e-5)


def test_rtd_linear_approximation_matches_table_9():
    for t, line_t in ((-100, -101.75), (0, 0.0), (100, 98.56)):
        res = _ok(calckit.run("rtd", {"t": t}))
        assert res["t_linear"]["value"] == pytest.approx(line_t, abs=0.01)


def test_rtd_rref_default_and_resolution():
    env = calckit.run("rtd", {})
    res = _ok(env)
    assert res["inputs"]["r_ref"]["value"] == 400 and res["lsb"]["value"] == pytest.approx(400 / 32768, rel=1e-5)
    assert res["resolution_0c"]["value"] == pytest.approx(0.03125, abs=1e-4)  # datasheet: nominal 0.03125 °C
    assert _checks(env) == {"r_ref_range": "passed", "bias_current": "passed"}
    res = _ok(calckit.run("rtd", {"r0": "1k"}))
    assert res["inputs"]["r_ref"]["value"] == 4000
    assert "r_ref" in {a["key"] for a in calckit.run("rtd", {})["assumptions"]}


def test_rtd_rref_range_and_full_scale():
    env = calckit.run("rtd", {"r_ref": 300, "t": 30})
    assert _checks(env)["r_ref_range"] == "failed" and _warn(env)["rtd_rref_range"] == "caution"
    env = calckit.run("rtd", {"r_ref": "12k", "r0": "1k"})
    assert _checks(env)["r_ref_range"] == "failed"
    env = calckit.run("rtd", {"r_ref": 430, "r_rtd": 440})
    assert _checks(env)["full_scale"] == "failed" and "rtd_full_scale" in _warn(env)
    env = calckit.run("rtd", {"r0": 1000, "r_ref": 1000, "code": 32767})
    assert _checks(env)["full_scale"] == "failed"
    res = _ok(calckit.run("rtd", {"r0": 1000, "r_ref": 1000}))
    assert res["t_full_scale"]["value"] == pytest.approx(0.0, abs=0.01)


def test_rtd_out_of_range_reading():
    env = calckit.run("rtd", {"code": 0})
    assert _checks(env)["cvd_range"] == "failed" and "rtd_out_of_range" in _warn(env)
    assert "t" not in env["result"]


def test_rtd_bias_current_and_leads():
    res = _ok(calckit.run("rtd", {"t": 0}))
    assert res["i_bias"]["value"] == pytest.approx(2.0 / 500, rel=1e-6)
    env = calckit.run("rtd", {"r0": 1000, "r_ref": "10k", "t": 0})
    assert _checks(env)["bias_current"] == "failed"  # 2 V / 11 kΩ = 0.18 mA < 0.2 mA
    res = _ok(calckit.run("rtd", {"r_lead": 0.2}))
    assert res["lead_error"]["value"] == pytest.approx(1.02, abs=0.01)  # 0.4 Ω series ≈ 1 °C (p. 10)
    env = calckit.run("rtd", {"r_lead": 60, "wires": 4})
    assert _checks(env)["cable"] == "failed" and "lead_error" not in env["result"]


@pytest.mark.parametrize("params", [{"code": 40000}, {"code": 1.5}, {"code": "abc"}, {"t": 900}, {"t": "warm"},
                                    {"t": 20, "code": 100}, {"wires": 3}, {"r_lead": 1, "wires": 5}, {"r0": -100}])
def test_rtd_bad_inputs(params):
    env = calckit.run("rtd", params)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args"


def test_rtd_hex_code_and_sources():
    env = calckit.run("rtd", {"code": "0x4000"})
    assert _ok(env)["r_rtd"]["value"] == pytest.approx(200.0)
    assert [s["id"] for s in env["sources"]] == ["mod-thermo-max31865-ds"]


# --- calc.ntc ------------------------------------------------------------------------------------------------------
def test_ntc_formula_reproduces_the_vishay_tables():
    for pid in parts.ids_of("ntc"):
        p = parts.find(pid, "ntc")
        assert ntc_calc.r_of_t(p, 25.0) == pytest.approx(p["r25"]["value"], rel=1e-4), pid
        for row in p.get("rt_table", []):
            assert ntc_calc.r_of_t(p, row["t"]) == pytest.approx(row["r"], rel=5e-4), (pid, row["t"])
            assert ntc_calc.t_of_r(p, row["r"]) == pytest.approx(row["t"], abs=0.05), (pid, row["t"])  # table: 4 digits


def test_ntc_default_divider_10k():
    env = calckit.run("ntc", {})
    res = _ok(env)
    assert res["inputs"]["r_fixed"]["value"] == 10000 and res["r25"]["value"] == 10000
    assert res["b25_85"]["value"] == 3977
    v0 = 3.3 * 32554 / (32554 + 10000)
    assert res["table"][0]["v_out"]["value"] == pytest.approx(v0, rel=1e-3)
    assert res["v_out_max"]["value"] == pytest.approx(v0, rel=1e-3)
    assert res["v_out_min"]["value"] == pytest.approx(3.3 * 677.3 / (677.3 + 10000), rel=1e-3)
    assert res["dissipation_factor"]["value"] == 0.007
    # largest NTC power at R_NTC = R_fixed (25 °C is in the range): Vs² / (4 R)
    assert res["p_max"]["value"] == pytest.approx(3.3 ** 2 / 40000, rel=1e-3)
    assert res["self_heating_max"]["value"] == pytest.approx(3.3 ** 2 / 40000 / 0.007, rel=1e-3)
    assert _checks(env) == {"t_range": "passed", "v_ntc": "passed", "esp_input": "passed", "adc_range": "not_checked",
                            "zero_power": "passed"}
    assert res["r_fixed_suggested"]["value"] == 4700  # √(32.55 k · 677 Ω) = 4.70 k


def test_ntc_point_and_readings():
    res = _ok(calckit.run("ntc", {"t": 25}))
    assert res["point"]["v_out"]["value"] == pytest.approx(1.65, abs=1e-3)
    assert res["point"]["r_beta"]["value"] == pytest.approx(10000, rel=1e-6)
    res = _ok(calckit.run("ntc", {"v_adc": 1.65}))
    assert res["point"]["t"]["value"] == pytest.approx(25.0, abs=0.01)
    res = _ok(calckit.run("ntc", {"r_ntc": "32.554k"}))
    assert res["point"]["t"]["value"] == pytest.approx(0.0, abs=0.02)
    res = _ok(calckit.run("ntc", {"position": "high", "v_adc": 1.65}))
    assert res["point"]["t"]["value"] == pytest.approx(25.0, abs=0.01)
    res = _ok(calckit.run("ntc", {"part": "NTCLE100E3102", "t": 10}))
    assert abs(res["point"]["beta_error"]["value"]) > 0.1  # the B-equation is off below 25 °C


def test_ntc_material_i_uses_both_ranges():
    p = parts.find("NTCLE100E3102", "ntc")
    assert len(p["steinhart_hart"]) == 2
    assert ntc_calc.r_of_t(p, 24.999) == pytest.approx(ntc_calc.r_of_t(p, 25.0), rel=1e-3)


def test_ntc_divider_at_5v_exceeds_the_esp_input():
    env = calckit.run("ntc", {"v_supply": "5V"})
    assert _checks(env)["esp_input"] == "failed" and _warn(env)["ntc_esp_input"] == "danger"
    assert "elec-ds-esp32s3" in [s["id"] for s in env["sources"]]
    env = calckit.run("ntc", {"v_supply": "5V", "chip": "nochip"})
    assert _checks(env)["esp_input"] == "not_checked"


def test_ntc_adc_range_and_resolution():
    env = calckit.run("ntc", {"adc_range": [0.1, 2.9], "adc_bits": 12})
    res = _ok(env)
    assert _checks(env)["adc_range"] == "passed"
    assert res["adc_lsb"]["value"] == pytest.approx(2.8 / 4096, rel=1e-3)
    assert 0 < res["resolution"]["mid"]["value"] < res["resolution"]["t_max"]["value"]
    env = calckit.run("ntc", {"adc_range": [0.3, 2.5]})
    assert _checks(env)["adc_range"] == "failed" and "ntc_adc_range" in _warn(env)
    env = calckit.run("ntc", {"adc_bits": 12})
    assert env["ok"] is False


def test_ntc_self_heating_and_zero_power():
    env = calckit.run("ntc", {"part": "NTCLE100E3331", "r_fixed": 330})
    res = _ok(env)
    assert res["dissipation_factor"]["value"] == 0.0085  # R25 ≤ 680 Ω
    assert _checks(env)["zero_power"] == "failed" and _warn(env)["ntc_power"] == "caution"
    assert _warn(env)["ntc_self_heating"] == "info"
    assert "rule-of-thumb" in [s["id"] for s in env["sources"]]


def test_ntc_temperature_range():
    env = calckit.run("ntc", {"t_max": 140})
    assert _checks(env)["t_range"] == "failed" and _warn(env)["ntc_t_short"] == "caution"
    env = calckit.run("ntc", {"t_min": -55})
    assert _warn(env)["ntc_t_range"] == "caution"


@pytest.mark.parametrize("params", [{"t_min": 50, "t_max": 20}, {"position": "middle"}, {"t": 10, "v_adc": 1},
                                    {"v_adc": 3.3}, {"t_min": "cold"}])
def test_ntc_bad_inputs(params):
    env = calckit.run("ntc", params)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args"


def test_ntc_unknown_part():
    env = calckit.run("ntc", {"part": "NTC-XYZ"})
    assert env["ok"] is False and env["error"]["code"] == "invalid_args"


def test_ntc_v_supply_above_50v_on_the_ntc():
    env = calckit.run("ntc", {"v_supply": "55V"})
    assert _checks(env)["v_ntc"] == "failed" and _warn(env)["ntc_v_max"] == "danger"


def test_both_calculators_are_registered_in_sensing():
    meta = {m["kind"]: m for m in calckit.meta()}
    assert meta["rtd"]["group"] == "sensing" and meta["ntc"]["group"] == "sensing"
    assert calckit.problems() == []
