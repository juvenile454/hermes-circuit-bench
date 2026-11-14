"""Calculators: 60 V low-voltage limit (product rule, inclusive like
schematic.MAX_VOLTS), gpio_current in led, chip-dependent ESP32-S3 assumptions in mosfet/ldo."""
import json

import pytest

from circuit_bench import tools
from circuit_bench.bench_core import calc, calc_power
from circuit_bench.bench_core.contracts import validate_envelope
from test_api_support import *  # noqa: F403  (api fixture)

WROOM = "ds-esp32-s3-wroom-1-power"

# (kind, the voltage input that is raised, the other inputs)
CASES = [
    ("led", "v_supply", {"v_f": "2V", "i_f": "10mA"}),
    ("npn", "v_drive", {"r_base": "10k", "i_load": "13mA"}),
    ("divider", "v_in_max", {"r1": "100k", "r2": "100k"}),
    ("i2c_pullup", "v_dd", {"c_bus": "100pF"}),
    ("mosfet", "v_supply", {"i_load": "2A", "part": "AO3400A"}),
    ("ldo", "v_in", {"v_out": "3.3V", "i_load": "100mA"}),
]
IDS = [c[0] for c in CASES]


def _codes(env):
    return [w["code"] for w in env["warnings"]]


def _high_voltage_refusal(env, action):
    assert validate_envelope(env) == [], env
    assert env["ok"] is False and env["action"] == action
    assert env["error"]["code"] == "invalid_args" and env["error"]["hint"]
    assert "60 V" in env["error"]["message"]
    w = [w for w in env["warnings"] if w["code"] == "low_voltage_only"]
    assert len(w) == 1 and w[0]["severity"] == "danger" and w[0]["source_ids"] == []
    assert "product rule" in w[0]["message"]


@pytest.mark.parametrize(("kind", "volt", "rest"), CASES, ids=IDS)
def test_60v_is_allowed(kind, volt, rest):
    env = calc.run(kind, {**rest, volt: "60V"})
    assert env["ok"] is True, env
    assert "low_voltage_only" not in _codes(env)


@pytest.mark.parametrize(("kind", "volt", "rest"), CASES, ids=IDS)
@pytest.mark.parametrize("value", ["60.1V", 60.1, "60100mV", "230V"])
def test_above_60v_is_refused(kind, volt, rest, value):
    _high_voltage_refusal(calc.run(kind, {**rest, volt: value}), f"calc.{kind}")


@pytest.mark.parametrize(("kind", "volt", "rest"), CASES, ids=IDS)
def test_direct_call_is_refused_too(kind, volt, rest):
    fn = calc.CALCULATORS[kind]
    _high_voltage_refusal(fn(**{**rest, volt: "61V"}), f"calc.{kind}")


@pytest.mark.parametrize(("kind", "params"), [
    ("led", {"v_supply": "5V", "v_f": "61V", "i_f": "10mA"}),
    ("npn", {"v_drive": "3.3V", "i_load": "10mA", "v_be": "61V"}),
    ("divider", {"v_in_max": "12V", "r1": "1k", "r2": "1k", "adc_range": [0, "61V"]}),
    ("i2c_pullup", {"v_dd": "3.3V", "c_bus": "100pF", "v_ol": "61V"}),
    ("mosfet", {"i_load": "1A", "v_supply": "12V", "gate_v": "61V"}),
    ("ldo", {"v_in": "12V", "v_out": "61V", "i_load": "0.1A"}),
], ids=IDS)
def test_every_voltage_input_is_limited(kind, params):
    _high_voltage_refusal(calc.run(kind, params), f"calc.{kind}")


def test_mosfet_60v_case_of_the_power_tests_still_runs():
    # tests/test_plus_calc_power.py: the largest answer (every warning at once) at "60V"
    env = calc_power.mosfet("6A", "60V", part="AO3400A", gate_v=15, r_ds_on="0.1", r_gate="2k", r_pulldown="1M",
                            t_ambient="60 °C")
    assert env["ok"] is True and "low_voltage_only" not in _codes(env)


def test_tool_refuses_above_60v():
    handlers = tools.make_handlers(tools.Host(hook_active=True))
    env = json.loads(handlers["bench_calc"]({"action": "led", "inputs": {"v_supply": "61V", "v_f": "2V", "i_f": "10mA"}}))
    _high_voltage_refusal(env, "calc.led")
    env = json.loads(handlers["bench_calc"]({"action": "ldo", "v_in": "100V", "v_out": "5V", "i_load": "0.1A"}))
    _high_voltage_refusal(env, "calc.ldo")


@pytest.mark.parametrize(("kind", "volt", "rest"), CASES, ids=IDS)
def test_route_refuses_above_60v_with_400(api, kind, volt, rest):
    body = api.err(api.post(f"/calc/{kind}", {**rest, volt: "60.1V"}), 400, "invalid_args")
    assert [w["severity"] for w in body["warnings"] if w["code"] == "low_voltage_only"] == ["danger"]
    api.ok(api.post(f"/calc/{kind}", {**rest, volt: "60V"}))


# --- led: gpio_current -----------------------------------------------------------------------------------------------
def test_led_reports_gpio_current_like_npn():
    env = calc.led(3.3, 2.0, 0.010)
    w = [w for w in env["warnings"] if w["code"] == "gpio_current"]
    assert len(w) == 1 and w[0]["severity"] == "info"
    i_act = env["result"]["i_actual"]["display"]
    assert w[0]["message"] == (f"The driving pin sources {i_act}, below the 40.0 mA high-level source current of an "
                               "ESP32-S3 pin (a typical value, not a maximum; chip not given).")
    npn = next(w for w in calc.npn(3.3, 1000, 0.013)["warnings"] if w["code"] == "gpio_current")
    assert npn["message"].split(", ", 1)[1] == w[0]["message"].split(", ", 1)[1]  # same text after the current


def test_led_without_headroom_has_no_gpio_current():
    assert _codes(calc.led(2.0, 2.0, 0.01)) == ["led_no_headroom"]


# --- mosfet / ldo: chip ----------------------------------------------------------------------------------------------
def _gate(env):
    return next(a for a in env["assumptions"] if a["key"] == "gate_v")


def _src(env):
    return [s["id"] for s in env["sources"]]


def test_mosfet_chip_esp32s3_as_before():
    env = calc_power.mosfet(2.0, 12.0, part="AO3400A", chip="esp32s3")
    assert env["ok"] is True, env
    assert WROOM in _src(env) and "2.64 V" in _gate(env)["reason"] and "Table 6-3" in _gate(env)["reason"]
    assert "chip not given" not in _gate(env)["reason"]
    assert env["result"]["inputs"]["chip"] == "esp32s3"
    assert env["result"]["p_loss"]["display"] == "192 mW"


def test_mosfet_chip_esp32c3_has_no_s3_source():
    env = calc_power.mosfet(2.0, 12.0, part="AO3400A", chip="ESP32-C3")
    assert env["ok"] is True, env
    assert WROOM not in _src(env)
    reason = _gate(env)["reason"]
    assert "ESP32-C3" in reason and "S3" not in reason and "Table 6-3" not in reason
    assert env["result"]["inputs"]["chip"] == "esp32c3"
    # the calculation itself does not change (no source for a worst-case V_GS)
    assert env["result"]["p_loss"] == calc_power.mosfet(2.0, 12.0, part="AO3400A")["result"]["p_loss"]


def test_mosfet_without_chip_names_the_s3_default():
    env = calc_power.mosfet(2.0, 12.0, part="AO3400A")
    assert WROOM in _src(env)
    assert "chip not given; ESP32-S3-WROOM-1 values" in _gate(env)["reason"] and "2.64 V" in _gate(env)["reason"]
    assert "chip" not in env["result"]["inputs"]


def test_ldo_chip_esp32s3_as_before():
    env = calc_power.ldo(5, 3.3, 0.5, part="AMS1117-3.3", chip="esp32s3")
    info = next(w for w in env["warnings"] if w["code"] == "esp32s3_supply")
    assert "500 mA" in info["message"] and "chip not given" not in info["message"]
    assert _src(env) == ["ams-ams1117", "rule-of-thumb", WROOM]


def test_ldo_chip_esp32c3_has_no_s3_warning_or_source():
    env = calc_power.ldo(5, 3.3, 0.5, part="AMS1117-3.3", chip="esp32c3")
    assert env["ok"] is True, env
    assert "esp32s3_supply" not in _codes(env) and WROOM not in _src(env)
    a = next(a for a in env["assumptions"] if a["key"] == "chip_supply")
    assert "ESP32-C3" in a["value"] + a["reason"] and "S3" not in a["value"] + a["reason"]
    assert env["result"]["p_total"] == calc_power.ldo(5, 3.3, 0.5, part="AMS1117-3.3")["result"]["p_total"]


def test_ldo_without_chip_names_the_s3_default():
    env = calc_power.ldo(5, 3.3, 0.5, part="AMS1117-3.3")
    info = next(w for w in env["warnings"] if w["code"] == "esp32s3_supply")
    assert info["message"].startswith("chip not given; ESP32-S3-WROOM-1 values")
    assert "500 mA" in info["message"] and "at or above" in info["message"]


@pytest.mark.parametrize("kind", ["mosfet", "ldo"])
def test_unknown_chip_is_invalid_args(kind):
    params = {"mosfet": {"i_load": "1A", "v_supply": "12V"}, "ldo": {"v_in": "5V", "v_out": "3.3V", "i_load": "0.1A"}}
    env = calc.run(kind, {**params[kind], "chip": "esp8266"})
    assert env["ok"] is False and env["error"]["code"] == "invalid_args" and "esp32s3" in env["error"]["hint"]


def test_chip_is_a_parameter_of_tool_and_route(api):
    assert ("chip", "str", False, None) in calc.PARAMS["mosfet"] and ("chip", "str", False, None) in calc.PARAMS["ldo"]
    handlers = tools.make_handlers(tools.Host(hook_active=True))
    env = json.loads(handlers["bench_calc"]({"action": "ldo", "inputs": {"v_in": "5V", "v_out": "3V3", "i_load": "0.5A",
                                                                         "chip": "esp32c6"}}))
    assert env["ok"] is True and "esp32s3_supply" not in _codes(env)
    body = api.ok(api.post("/calc/mosfet", {"i_load": "2A", "v_supply": "12V", "chip": "esp32c3"}))
    assert WROOM not in _src(body)
