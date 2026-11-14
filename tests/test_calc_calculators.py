"""Calculators led / npn / divider / i2c_pullup: mandatory cases, envelopes, errors, determinism.

Result values are rounded to 6 significant digits (calc._q), hence rel=1e-5 in the comparisons.
"""
import json
import math

import pytest

from circuit_bench.bench_core import calc
from circuit_bench.bench_core.contracts import MAX_RESULT_BYTES, validate_envelope

SI_UNITS = {"V", "A", "Ω", "F", "s", "W", "x", "%"}


def _qtys(obj):
    """Every qty() dict in a result."""
    if isinstance(obj, dict):
        if set(obj) == {"value", "unit", "display"}:
            yield obj
        else:
            for v in obj.values():
                yield from _qtys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _qtys(v)


def _check(env, check_id):
    return next(c for c in env["checks"] if c["id"] == check_id)


def _source_ids(env):
    return [s["id"] for s in env["sources"]]


def _assumption(env, key):
    return next(a for a in env["assumptions"] if a["key"] == key)


def _ok(env, action):
    assert validate_envelope(env) == [], env
    assert env["ok"] is True and env["error"] is None, env
    assert env["action"] == action
    assert isinstance(env["result"]["formula"], str) and env["result"]["formula"]
    assert len(json.dumps(env, ensure_ascii=False).encode()) <= MAX_RESULT_BYTES
    for q in _qtys(env["result"]):
        assert q["unit"] in SI_UNITS and math.isfinite(q["value"]) and q["display"]
    for step in env["result"]["steps"]:
        assert step["name"] and step["expr"] and set(step["value"]) == {"value", "unit", "display"}
    for w in env["warnings"]:
        assert set(w["source_ids"]) <= set(_source_ids(env)), w
    return env["result"]


def _error(env, action, code="invalid_args"):
    assert validate_envelope(env) == [], env
    assert env["ok"] is False and env["action"] == action
    assert env["error"]["code"] == code, env["error"]
    assert env["error"]["hint"] or code != "invalid_args"
    return env["error"]


# --- LED ---------------------------------------------------------------------------------------------------------
def test_led_mandatory_case():
    env = calc.led(3.3, 2.0, 0.010)
    r = _ok(env, "calc.led")
    assert r["r_exact"]["value"] == pytest.approx(130.0, rel=1e-5)
    assert r["r_exact"]["display"] == "130 Ω"
    assert r["r_chosen"] == {"value": 150.0, "unit": "Ω", "display": "150 Ω"}
    assert r["series"] == "E12"
    assert r["i_actual"]["value"] == pytest.approx(1.3 / 150, rel=1e-5)
    assert r["i_actual"]["display"] == "8.67 mA"
    assert r["p_r"]["value"] == pytest.approx((1.3 / 150) ** 2 * 150, rel=1e-5)
    assert r["p_r"]["display"] == "11.3 mW"
    assert r["p_rating_min"]["value"] == pytest.approx(2 * (1.3 / 150) ** 2 * 150, rel=1e-5)
    assert r["r_deviation"]["display"] == "15.4 %"
    assert _check(env, "calc.led.headroom")["status"] == "passed"
    assert "rule of thumb" in _assumption(env, "p_rating")["reason"]
    assert "rule of thumb" in env["summary"]
    assert _source_ids(env) == ["iec-60063", "rule-of-thumb"]
    assert env["summary"].startswith("LED at 3.30 V: 130 Ω exact, use 150 Ω (E12) for 8.67 mA, 11.3 mW in the resistor")


def test_led_e24_and_text_inputs():
    r = _ok(calc.led("3V3", "2 V", "10mA", series="E24"), "calc.led")
    assert r["r_chosen"]["value"] == 130.0
    assert r["i_actual"]["display"] == "10.0 mA"


def test_led_chosen_value_never_exceeds_the_current():
    for vs, vf, i in [(5.0, 2.0, 0.02), (3.3, 3.0, 0.02), (12.0, 1.8, 0.005), (5.0, 3.2, 0.015)]:
        r = calc.led(vs, vf, i)["result"]
        assert r["r_chosen"]["value"] >= r["r_exact"]["value"] - 1e-9
        assert r["i_actual"]["value"] <= i * (1 + 1e-9)


@pytest.mark.parametrize("vf", [3.3, 3.6])
def test_led_without_headroom_warns(vf):
    env = calc.led(3.3, vf, 0.01)
    assert validate_envelope(env) == [] and env["ok"] is True
    assert _check(env, "calc.led.headroom")["status"] == "failed"
    assert [w["code"] for w in env["warnings"]] == ["led_no_headroom"]
    assert env["result"]["r_exact"] is None and env["result"]["r_chosen"] is None
    assert env["result"]["formula"]


# --- NPN ---------------------------------------------------------------------------------------------------------
def test_npn_laser_driver_mandatory_case():
    env = calc.npn(3.3, 1000, 0.013, r_pulldown=10000)
    r = _ok(env, "calc.npn")
    assert r["i_rb"]["value"] == pytest.approx(0.0026, rel=1e-5) and r["i_rb"]["display"] == "2.60 mA"
    assert r["p_rb"]["value"] == pytest.approx(0.00676, rel=1e-5) and r["p_rb"]["display"] == "6.76 mW"
    assert r["i_pd"]["value"] == pytest.approx(0.00007, rel=1e-5) and r["i_pd"]["display"] == "70.0 µA"
    assert round(r["i_pd"]["value"] * 1e3, 2) == 0.07
    assert r["i_b"]["value"] == pytest.approx(0.00253, rel=1e-5)
    assert r["forced_beta"]["value"] == pytest.approx(0.013 / 0.00253, rel=1e-5)
    assert round(r["forced_beta"]["value"], 1) == 5.1 and r["forced_beta"]["display"] == "5.1 x"
    assert r["hfe"] is None
    sat = _check(env, "calc.npn.saturation")
    assert sat["status"] == "not_checked" and sat["detail"] == "give hfe_min or part to check saturation"
    assert _check(env, "calc.npn.ic_max")["status"] == "not_checked"
    assert _assumption(env, "v_be") == {"key": "v_be", "value": "0.7 V",
                                        "reason": "typical small-signal silicon BJT; check the datasheet"}
    gpio = next(w for w in env["warnings"] if w["code"] == "gpio_current")
    assert gpio["severity"] == "info" and "below the 40.0 mA high-level source current" in gpio["message"]
    assert env["summary"] == ("NPN low side at 3.30 V drive: base 2.53 mA net, forced beta 5.1; "
                              "saturation not checked (no hFE given).")
    assert all(c["status"] != "passed" for c in env["checks"] if c["id"] != "calc.npn.base_drive")


def test_npn_laser_driver_with_2n2222a_datasheet():
    env = calc.npn(3.3, 1000, 0.013, r_pulldown=10000, part="2N2222A")
    r = _ok(env, "calc.npn")
    sat = _check(env, "calc.npn.saturation")
    assert sat["status"] == "passed"
    assert "2N2222A datasheet" in sat["detail"] and "rule of thumb" in sat["detail"]
    hfe = r["hfe"]
    assert hfe["from"] == "datasheet" and hfe["part"] == "2N2222A" and hfe["source_id"] == "onsemi-2n2222a"
    # 13 mA lies between the datasheet rows 10 mA and 150 mA (both min 100)
    assert hfe["basis"] == "between_rows" and hfe["value"] == 100
    assert [row["evidence"] for row in hfe["rows"]] == ["(IC = 10 mAdc, VCE = 10 Vdc)", "(IC = 150 mAdc, VCE = 10 Vdc)"]
    assert hfe["i_b_needed"]["value"] == pytest.approx(0.013 / 50, rel=1e-5)
    assert "onsemi-2n2222a" in _source_ids(env) and "rule-of-thumb" in _source_ids(env)
    src = next(s for s in env["sources"] if s["id"] == "onsemi-2n2222a")
    assert src["url"].startswith("https://www.onsemi.com/") and src["retrieved"] == "2026-11-06"
    assert "smaller minimum" in _assumption(env, "hfe_min")["reason"]
    assert "V_CE 10.0 V" in _assumption(env, "hfe_conditions")["value"]
    assert "rule of thumb" in _assumption(env, "saturation")["reason"]
    assert _check(env, "calc.npn.ic_max")["status"] == "passed"
    assert "saturates by the hFE_min/2 rule of thumb" in env["summary"]


def test_npn_part_on_a_datasheet_row():
    env = calc.npn(5.0, 220, 0.15, part="2n2222a")
    hfe = env["result"]["hfe"]
    assert hfe["basis"] == "row" and hfe["value"] == 100 and hfe["rows"][0]["evidence"] == "(IC = 150 mAdc, VCE = 10 Vdc)"
    assert _assumption(env, "hfe_min")["reason"] == "datasheet row I_C 150 mA"
    # I_B = 4.3 V / 220 Ω = 19.5 mA, forced beta 7.7 <= 50
    assert _check(env, "calc.npn.saturation")["status"] == "passed"


def test_npn_part_saturation_fails_with_weak_drive():
    env = calc.npn(3.3, 47000, 0.1, part="2N2222A")  # I_B 55 µA, forced beta 1.8k
    assert _check(env, "calc.npn.saturation")["status"] == "failed"
    w = next(w for w in env["warnings"] if w["code"] == "npn_not_saturated")
    assert w["severity"] == "caution" and "rule of thumb" in w["message"]
    assert "may not saturate" in env["summary"]


@pytest.mark.parametrize("i_load", [0.00005, 0.6, 1.0])
def test_npn_part_outside_the_table_is_not_checked(i_load):
    env = calc.npn(3.3, 100, i_load, part="2N2222A")
    sat = _check(env, "calc.npn.saturation")
    assert sat["status"] == "not_checked" and "outside the hFE table" in sat["detail"]
    assert env["result"]["hfe"] is None
    assert any(w["code"] == "gpio_current" for w in env["warnings"])
    # the collector current rating still comes from the datasheet
    assert _check(env, "calc.npn.ic_max")["status"] == ("passed" if i_load <= 0.8 else "failed")
    assert "onsemi-2n2222a" in _source_ids(env)


def test_npn_collector_current_rating():
    env = calc.npn(3.3, 100, 1.0, part="2N2222A")
    assert _check(env, "calc.npn.ic_max")["status"] == "failed"
    w = next(w for w in env["warnings"] if w["code"] == "npn_ic_max")
    assert w["severity"] == "danger" and w["source_ids"] == ["onsemi-2n2222a"]


def test_npn_unknown_part_is_not_guessed():
    env = calc.npn(3.3, 1000, 0.013, part="BC547")
    _ok(env, "calc.npn")
    assert _check(env, "calc.npn.saturation")["status"] == "not_checked"
    assert _check(env, "calc.npn.ic_max")["status"] == "not_checked"
    w = next(w for w in env["warnings"] if w["code"] == "part_unknown")
    assert w["severity"] == "info" and "unverified" in w["message"]
    assert env["result"]["hfe"] is None


@pytest.mark.parametrize(("hfe", "status"), [(35, "passed"), (11, "passed"), (10, "failed")])
def test_npn_user_hfe(hfe, status):
    env = calc.npn(3.3, 1000, 0.013, r_pulldown=10000, hfe_min=hfe)
    assert _check(env, "calc.npn.saturation")["status"] == status
    assert env["result"]["hfe"]["from"] == "user"
    assert _assumption(env, "hfe_min")["reason"].startswith("given by you")
    assert "your value" in _check(env, "calc.npn.saturation")["detail"]


def test_npn_user_hfe_wins_over_part():
    env = calc.npn(3.3, 1000, 0.013, hfe_min=20, part="2N2222A")
    assert env["result"]["hfe"]["from"] == "user"
    assert any(w["code"] == "hfe_min_given" for w in env["warnings"])


def test_npn_without_base_current():
    env = calc.npn(0.6, 1000, 0.013, hfe_min=100)
    _ok(env, "calc.npn")
    assert _check(env, "calc.npn.base_drive")["status"] == "failed"
    assert _check(env, "calc.npn.saturation")["status"] == "not_checked"
    assert env["result"]["forced_beta"] is None and env["result"]["i_rb"]["value"] == 0
    env = calc.npn(1.0, 100000, 0.013, r_pulldown=1000)  # pull-down takes more than R_B gives
    assert _check(env, "calc.npn.base_drive")["status"] == "failed"
    assert any(w["code"] == "npn_no_base_current" for w in env["warnings"])
    assert "stays off" in env["summary"]


def test_npn_custom_vbe_is_marked():
    env = calc.npn(3.3, 1000, 0.013, v_be="0.65 V")
    assert _assumption(env, "v_be") == {"key": "v_be", "value": "0.65 V", "reason": "given by you"}
    assert env["result"]["i_rb"]["value"] == pytest.approx(0.00265, rel=1e-5)


def test_npn_load_warnings():
    laser = calc.npn(3.3, 1000, 0.013, load="laser")
    codes = [w["code"] for w in laser["warnings"]]
    assert "laser_safety" in codes and "laser_no_pulldown" in codes
    assert next(w for w in laser["warnings"] if w["code"] == "laser_safety")["severity"] == "danger"
    with_pd = calc.npn(3.3, 1000, 0.013, r_pulldown=10000, load="laser")
    assert "laser_no_pulldown" not in [w["code"] for w in with_pd["warnings"]]
    relay = calc.npn(5.0, 1000, 0.07, load="relay")
    w = next(w for w in relay["warnings"] if w["code"] == "inductive_load")
    assert "230 V" in w["message"] and "rule of thumb" in w["message"]
    assert [w["code"] for w in calc.npn(3.3, 1000, 0.013)["warnings"]] == ["gpio_current"]


# --- divider -----------------------------------------------------------------------------------------------------
def test_divider_mandatory_case():
    env = calc.divider(12, 30000, 10000)
    r = _ok(env, "calc.divider")
    assert r["v_out_max"]["value"] == pytest.approx(3.0, rel=1e-5) and r["v_out_max"]["display"] == "3.00 V"
    assert r["ratio"] == 0.25
    assert r["i_div"]["value"] == pytest.approx(0.0003, rel=1e-5) and r["i_div"]["display"] == "300 µA"
    assert r["r_source"]["value"] == pytest.approx(7500.0, rel=1e-5) and r["r_source"]["display"] == "7.50 kΩ"
    assert r["p_r1"]["value"] == pytest.approx(0.0027, rel=1e-5) and r["p_r2"]["value"] == pytest.approx(0.0009, rel=1e-5)
    assert _check(env, "calc.divider.adc_range")["status"] == "not_checked"
    assert r["adc"] is None
    assert env["summary"] == "Divider 30.0 kΩ / 10.0 kΩ: 12.0 V in gives 3.00 V out, 300 µA through the divider."
    assert "rule of thumb" in _assumption(env, "adc_pin")["reason"]


def test_divider_text_inputs_equal_numbers():
    a, b = calc.divider("12V", "30k", "10 kΩ"), calc.divider(12.0, 30000.0, 10000.0)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


@pytest.mark.parametrize(("adc_range", "inside"), [([0, 3.1], True), ({"min": 0, "max": "2.5 V"}, False), (3.3, True),
                                                   ((3.1, 3.3), False)])
def test_divider_adc_range_is_never_a_hard_check(adc_range, inside):
    env = calc.divider(12, 30000, 10000, adc_range=adc_range)
    _ok(env, "calc.divider")
    chk = _check(env, "calc.divider.adc_range")
    assert chk["status"] == "not_checked" and "unverified" in chk["detail"]
    assert env["result"]["adc"]["inside"] is inside
    assert _assumption(env, "adc_range")["reason"].startswith("given by you")
    warns = [w for w in env["warnings"] if w["code"] == "adc_out_of_given_range"]
    assert len(warns) == (0 if inside else 1)
    assert all(w["severity"] == "info" and "unverified" in w["message"] for w in warns)


# --- I²C ---------------------------------------------------------------------------------------------------------
def test_i2c_mandatory_case_against_hand_calculation():
    env = calc.i2c_pullup(3.3, 200e-12)
    r = _ok(env, "calc.i2c_pullup")
    # hand calculation: R_min = (3.3 V - 0.4 V) / 3 mA; R_max = 1000 ns / (0.8473 * 200 pF)
    assert r["r_min"]["value"] == pytest.approx((3.3 - 0.4) / 0.003, rel=1e-6) == pytest.approx(966.667, rel=1e-6)
    assert r["r_min"]["display"] == "967 Ω"
    assert r["r_max"]["value"] == pytest.approx(1000e-9 / (0.8473 * 200e-12), rel=1e-6) == pytest.approx(5901.10, rel=1e-6)
    assert r["r_max"]["display"] == "5.90 kΩ"
    assert r["t_r_max"]["value"] == pytest.approx(1e-6, rel=1e-5)
    assert r["suggested"]["value"] == 2200.0  # E12 nearest sqrt(967 * 5901) = 2.39 kΩ
    assert r["suggested_t_r"]["value"] == pytest.approx(0.8473 * 2200 * 200e-12, rel=1e-5)
    assert _check(env, "calc.i2c.window")["status"] == "passed"
    assert _check(env, "calc.i2c.c_bus_max")["status"] == "passed"
    assert r["formula"] == "R_min = (V_DD − V_OL) / I_OL; R_max = t_r / (0.8473 · C_b)"
    assert _source_ids(env) == ["nxp-um10204", "iec-60063", "rule-of-thumb"]
    assert "UM10204 Table 11" in _assumption(env, "t_r")["reason"]
    assert "rule of thumb" in _assumption(env, "suggested")["reason"]
    assert env["summary"] == ("I²C standard mode at 3.30 V, 200 pF: pull-up between 967 Ω and 5.90 kΩ; "
                              "2.20 kΩ (E12) suggested.")


def test_i2c_fast_mode():
    env = calc.i2c_pullup("3V3", "100pF", mode="fast", r_pullup="4k7")
    r = _ok(env, "calc.i2c_pullup")
    assert r["r_max"]["value"] == pytest.approx(300e-9 / (0.8473 * 100e-12), rel=1e-5)
    assert _check(env, "calc.i2c.r_pullup")["status"] == "failed"
    assert any(w["code"] == "i2c_fast_iol" for w in env["warnings"])
    assert "4.70 kΩ does not fit" in env["summary"]


def test_i2c_given_resistor_fits():
    env = calc.i2c_pullup(3.3, 100e-12, r_pullup=4700)
    assert _check(env, "calc.i2c.r_pullup")["status"] == "passed"
    assert env["result"]["r_pullup_t_r"]["value"] == pytest.approx(0.8473 * 4700 * 100e-12, rel=1e-5)


def test_i2c_no_window_and_too_much_capacitance():
    env = calc.i2c_pullup(5.0, 500e-12, mode="fast")
    r = _ok(env, "calc.i2c_pullup")
    assert _check(env, "calc.i2c.window")["status"] == "failed"
    assert _check(env, "calc.i2c.c_bus_max")["status"] == "failed"
    assert r["suggested"] is None
    assert {"i2c_no_window", "i2c_c_bus_max"} <= {w["code"] for w in env["warnings"]}
    assert "no pull-up fits" in env["summary"]
    assert _source_ids(env) == ["nxp-um10204"]


def test_i2c_low_vdd_and_custom_sink():
    env = calc.i2c_pullup(1.8, 100e-12, v_ol=0.36, i_ol=0.002)
    assert any(w["code"] == "i2c_low_vdd" for w in env["warnings"])
    assert _assumption(env, "v_ol")["reason"] == "given by you"
    assert env["result"]["r_min"]["value"] == pytest.approx(720.0, rel=1e-5)


# --- errors ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("fn", "args", "kwargs"), [
    (calc.led, ("abc", 2.0, 0.01), {}),
    (calc.led, (3.3, 2.0, 0), {}),
    (calc.led, (3.3, -2.0, 0.01), {}),
    (calc.led, (3.3, 2.0, "10 mV"), {}),
    (calc.led, (3.3, 2.0, 0.01), {"series": "E13"}),
    (calc.led, (3.3, 2.0, float("nan")), {}),
    (calc.led, (3.3, True, 0.01), {}),
    (calc.led, (3.3, 2.0), {}),
    (calc.led, (3.3, 2.0, 0.01), {"colour": "red"}),
    (calc.npn, (3.3, 0, 0.013), {}),
    (calc.npn, (3.3, 1000, 0.013), {"r_pulldown": "-1k"}),
    (calc.npn, (3.3, 1000, 0.013), {"hfe_min": 0}),
    (calc.npn, (3.3, 1000, 0.013), {"hfe_min": "100 V"}),
    (calc.npn, (3.3, 1000, 0.013), {"part": 2222}),
    (calc.npn, (3.3, 1000, 0.013), {"part": "  "}),
    (calc.npn, (3.3, 1000, 0.013), {"load": "toaster"}),
    (calc.npn, (None, 1000, 0.013), {}),
    (calc.divider, (12, 0, 10000), {}),
    (calc.divider, (12, "30k", "ten"), {}),
    (calc.divider, (12, 30000, 10000), {"adc_range": [3, 1]}),
    (calc.divider, (12, 30000, 10000), {"adc_range": [1, 2, 3]}),
    (calc.divider, (12, 30000, 10000), {"adc_range": {"max": 3, "atten": 12}}),
    (calc.i2c_pullup, (3.3, 0), {}),
    (calc.i2c_pullup, (3.3, "200 pA"), {}),
    (calc.i2c_pullup, (3.3, 200e-12), {"mode": "turbo"}),
    (calc.i2c_pullup, (0.3, 200e-12), {}),
    (calc.i2c_pullup, (3.3, 200e-12), {"i_ol": 0}),
])
def test_invalid_input_gives_invalid_args(fn, args, kwargs):
    env = fn(*args, **kwargs)
    action = {calc.led: "calc.led", calc.npn: "calc.npn", calc.divider: "calc.divider",
              calc.i2c_pullup: "calc.i2c_pullup"}[fn]
    err = _error(env, action)
    assert err["message"]


def test_error_names_the_parameter():
    assert calc.led(3.3, "two volts", 0.01)["error"]["message"].startswith("v_f:")


# --- dispatcher --------------------------------------------------------------------------------------------------
def test_run_matches_direct_calls():
    assert calc.run("led", {"v_supply": "3V3", "v_f": "2 V", "i_f": "10mA"}) == calc.led(3.3, 2.0, 0.01)
    assert calc.run("npn", {"v_drive": "3.3", "r_base": "1k", "i_load": "13 mA", "r_pulldown": "10k",
                            "part": "2N2222A", "hfe_min": None}) == calc.npn(3.3, 1000, 0.013, r_pulldown=10000,
                                                                            part="2N2222A")
    assert calc.run("divider", {"v_in_max": 12, "r1": "30k", "r2": "10k"}) == calc.divider(12, 30000, 10000)
    assert calc.run("i2c_pullup", {"v_dd": "3V3", "c_bus": "200p"}) == calc.i2c_pullup(3.3, 200e-12)


def test_run_errors():
    _error(calc.run("led", {"v_supply": 3.3, "v_f": 2.0}), "calc.led")
    assert "missing parameter(s): i_f" in calc.run("led", {"v_supply": 3.3, "v_f": 2.0})["error"]["message"]
    assert "unknown parameter(s): x" in calc.run("led", {"v_supply": 3.3, "v_f": 2, "i_f": 0.01, "x": 1})["error"]["message"]
    _error(calc.run("divider", [12, 1, 1]), "calc.divider")
    from circuit_bench.bench_core.contracts import BenchError
    with pytest.raises(BenchError):
        calc.run("bogus", {})


def test_params_table_matches_signatures():
    import inspect
    for kind, fn in calc.CALCULATORS.items():
        sig = inspect.signature(fn)
        assert [p[0] for p in calc.PARAMS[kind]] == list(sig.parameters), kind
        for name, _unit, required, default in calc.PARAMS[kind]:
            p = sig.parameters[name]
            if (kind, name) == ("npn", "i_load"):  # follows the optional r_base; _num still requires it
                assert required and p.default is None
                continue
            assert (p.default is inspect.Parameter.empty) == required, name
            if not required:
                assert p.default == default, name


# --- determinism -------------------------------------------------------------------------------------------------
CASES = [
    (calc.led, (3.3, 2.0, 0.010), {}),
    (calc.npn, (3.3, 1000, 0.013), {"r_pulldown": 10000, "part": "2N2222A", "load": "laser"}),
    (calc.divider, (12, 30000, 10000), {"adc_range": [0, 3.1]}),
    (calc.i2c_pullup, (3.3, 200e-12), {"mode": "fast", "r_pullup": 1500}),
]


@pytest.mark.parametrize(("fn", "args", "kwargs"), CASES)
def test_deterministic(fn, args, kwargs):
    first = json.dumps(fn(*args, **kwargs), ensure_ascii=False)
    for _ in range(3):
        assert json.dumps(fn(*args, **kwargs), ensure_ascii=False) == first


@pytest.mark.parametrize(("fn", "args", "kwargs"), CASES)
def test_values_are_rounded_and_json_safe(fn, args, kwargs):
    env = fn(*args, **kwargs)
    assert json.loads(json.dumps(env)) == env
    for q in _qtys(env["result"]):
        v = q["value"]
        assert v == 0 or len(repr(abs(v)).replace("0.", "").replace("e", "").replace("-", "").lstrip("0")) <= 12, q


def test_every_check_with_a_verdict_has_a_source():
    """Hard verdicts (passed/failed) only for physics, sourced limits or rules of thumb that say so."""
    rule_checks = {"calc.npn.saturation"}
    for fn, args, kwargs in CASES + [(calc.npn, (3.3, 47000, 0.1), {"part": "2N2222A"})]:
        env = fn(*args, **kwargs)
        for c in env["checks"]:
            if c["status"] in ("passed", "failed") and c["id"] in rule_checks:
                assert "rule of thumb" in c["detail"] and "rule-of-thumb" in _source_ids(env)
            if c["id"] in ("calc.i2c.window", "calc.i2c.c_bus_max", "calc.i2c.r_pullup"):
                assert "nxp-um10204" in _source_ids(env)
            if c["id"] == "calc.npn.ic_max" and c["status"] != "not_checked":
                assert "onsemi-2n2222a" in _source_ids(env)
            if c["id"] == "calc.divider.adc_range":
                assert c["status"] == "not_checked"
