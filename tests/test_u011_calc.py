"""Calculator wording and inputs: the pin-current sentence of led and npn, the divider ``target``,
the closest-part hint of an unknown part number. Answers without the new input stay as they were."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from circuit_bench.bench_core import calc, calc_power, calckit, electrical, parts

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "desktop-src" / "fixtures"
OLD_TAIL = "GPIO current limits are not checked here (unverified); see the chip datasheet."


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _warn(env, code):
    return next(w for w in env["warnings"] if w["code"] == code)


def _check(env, cid):
    return next(c for c in env["checks"] if c["id"] == cid)


def _codes(env):
    return [w["code"] for w in env["warnings"]]


# --- the pin-current sentence names the comparison --------------------------------------------------------------------

def _below_text(i_pin: str) -> str:
    ioh = calc._f(electrical.get("esp32s3")["ioh"], "A")
    return (f"The driving pin sources {i_pin}, below the {ioh} high-level source current of an ESP32-S3 pin "
            "(a typical value, not a maximum; chip not given).")


def test_led_below_the_pin_current_names_the_comparison():
    env = calc.led(3.3, 2.0, 0.010)
    w = _warn(env, "gpio_current")
    assert w["severity"] == "info"
    assert w["message"] == _below_text(env["result"]["i_actual"]["display"])
    assert "not checked" not in w["message"]
    assert w["source_ids"] == []  # like before: the answer's source list stays as it was


def test_npn_below_the_pin_current_uses_the_same_sentence():
    env = calc.npn(3.3, 1000, 0.013)
    w = _warn(env, "gpio_current")
    assert w["severity"] == "info"
    assert w["message"] == _below_text(env["result"]["i_rb"]["display"])


def test_pin_current_without_pin_data_keeps_the_old_sentence(monkeypatch):
    monkeypatch.setattr(calc, "_pin_values", lambda chip=calc.PIN_LIMIT_CHIP: None)
    for env, key in ((calc.led(3.3, 2.0, 0.010), "i_actual"), (calc.npn(3.3, 1000, 0.013), "i_rb")):
        w = _warn(env, "gpio_current")
        assert w["severity"] == "info" and w["source_ids"] == []
        assert w["message"] == f"The driving pin sources {env['result'][key]['display']}. {OLD_TAIL}"


def test_pin_current_above_the_limit_stays_a_caution():
    w = _warn(calc.led(5.0, 1.8, 0.050), "gpio_current")
    assert w["severity"] == "caution" and w["message"].startswith("The driving pin would have to source ")


def test_mosfet_gate_peak_sentence_is_not_touched():
    env = calc_power.mosfet("2A", "12V", gate_v="3.3V", part="AO3400A")
    w = _warn(env, "gpio_current")
    assert w["severity"] == "info" and "GPIO current limits are not checked here (unverified)" in w["message"]
    assert "GPIO current limits are not checked here (unverified)" in json.dumps(_fixture("calc.mosfet"))


def test_pin_current_next_to_the_limit_shows_enough_digits():
    """A current just below (or above) the limit must not read '40.0 mA, below the 40.0 mA'."""
    ioh = electrical.get("esp32s3")["ioh"]
    assert ioh == 0.04
    for i_pin, severity, rel in ((0.03999, "info", "below the"), (0.04 - 2e-9, "info", "below the"),
                                 (0.04 + 2e-9, "caution", "above the"), (0.04001, "caution", "above the")):
        w = calc._gpio_current(i_pin)
        assert w["severity"] == severity and f"{rel} 40.0 mA" in w["message"], (i_pin, w["message"])
        shown = re.search(r"sources? ([\d.]+) mA", w["message"]).group(1)
        assert float(shown) != 40.0 and (float(shown) < 40.0) == (i_pin < ioh), (i_pin, w["message"])
    for i_pin in (0.04, 0.04 - 5e-10, 0.04 + 5e-10):  # within the tolerance: at the limit, shown as the limit
        assert "40.0 mA, at the 40.0 mA" in calc._gpio_current(i_pin)["message"]
    for i_pin in (0.01, 0.0399, 0.0401, 0.05):  # ordinary values keep three digits
        assert calc._f(i_pin, "A") in calc._gpio_current(i_pin)["message"]


# --- divider with a target value --------------------------------------------------------------------------------------

def test_divider_target_other_skips_the_pin_limit():
    env = calc.divider("12V", "7k", "5k", target="other")
    assert env["ok"] is True
    chk = _check(env, "calc.divider.pin_max")
    assert chk["status"] == "not_checked"
    assert chk["detail"] == "the output does not feed an ESP pin (target=other)"
    assert "divider_overvoltage" not in _codes(env)
    assert env["result"]["inputs"]["target"] == "other"
    assert not any(a["key"] == "pin_limit" for a in env["assumptions"])
    assert any(a["key"] == "target" and a["value"] == "other" for a in env["assumptions"])
    assert env["result"]["v_out_max"]["value"] == pytest.approx(5.0)  # the numbers do not change


def test_divider_target_other_below_the_limit_still_says_not_checked():
    env = calc.divider("4.2V", "100k", "100k", target="other")
    assert _check(env, "calc.divider.pin_max")["status"] == "not_checked"
    assert "divider_overvoltage" not in _codes(env)


def test_divider_without_target_is_unchanged():
    env = calc.divider("12V", "7k", "5k")
    assert _check(env, "calc.divider.pin_max")["status"] == "failed"
    assert "divider_overvoltage" in _codes(env)
    assert "target" not in env["result"]["inputs"]
    assert not any(a["key"] == "target" for a in env["assumptions"])
    quiet = calc.divider("4.2V", "100k", "100k")
    assert [c["id"] for c in quiet["checks"]] == ["calc.divider.adc_range"]  # no pin_max row below the limit


def test_divider_target_esp_pin_is_the_default():
    plain = calc.divider("12V", "7k", "5k")
    assert calc.divider("12V", "7k", "5k", target="esp_pin") == plain
    assert calc.divider("12V", "7k", "5k", target="ESP_PIN") == plain
    assert calc.divider("12V", "7k", "5k", target=None) == plain


@pytest.mark.parametrize("bad", ["adc", "", 5, ["other"]])
def test_divider_target_rejects_other_values(bad):
    env = calc.divider("12V", "7k", "5k", target=bad)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args"
    assert "esp_pin" in env["error"]["message"] and "other" in env["error"]["message"]


def test_divider_target_through_the_register():
    env = calckit.run("divider", {"v_in_max": "12V", "r1": "7k", "r2": "5k", "target": "other"})
    assert env["ok"] and _check(env, "calc.divider.pin_max")["status"] == "not_checked"
    entry = next(c for c in calckit.meta() if c["kind"] == "divider")
    param = next(p for p in entry["params"] if p["name"] == "target")
    assert param == {"name": "target", "unit": "str", "required": False, "default": "esp_pin",
                     "choices": ["esp_pin", "other"]}


def test_desktop_divider_form_does_not_get_a_target_field():
    """The form's fields are the static CALC_DEFS list; calc.meta only adds choices to fields that exist there."""
    text = (ROOT / "desktop-src" / "lib" / "calc.js").read_text(encoding="utf-8")
    block = text[text.index("type: 'divider'"):text.index("type: 'i2c_pullup'")]
    assert "target" not in block


# --- unknown part names the closest known one, never an alias ---------------------------------------------------------

def test_npn_unknown_part_names_the_closest_type():
    env = calc.npn(3.3, 1000, 0.013, part="2N2222")
    w = _warn(env, "part_unknown")
    assert w["severity"] == "info"
    assert w["message"] == ("no datasheet data for part '2N2222' (closest: 2N2222A, a different type with its own "
                            "ratings; known: 2N2222A); hFE not checked (unverified).")
    assert env["result"]["hfe"] is None
    assert _check(env, "calc.npn.saturation")["status"] == "not_checked"
    assert _check(env, "calc.npn.ic_max")["status"] == "not_checked"
    assert parts.find("2N2222") is None  # no alias was added


def test_npn_unknown_part_without_a_close_name_keeps_the_old_text():
    w = _warn(calc.npn(3.3, 1000, 0.013, part="BC547"), "part_unknown")
    assert w["message"] == "no datasheet data for part 'BC547' (known: 2N2222A); hFE not checked (unverified)."


def test_mosfet_unknown_part_names_the_closest_type():
    env = calc_power.mosfet("1A", "12V", part="AO3400")
    detail = env["checks"][0]["detail"]
    assert "no datasheet data for part 'AO3400' (closest: AO3400A, a different type with its own ratings; known: " in detail
    plain = calc_power.mosfet("1A", "12V", part="BS170")["checks"][0]["detail"]
    assert "closest" not in plain and "no datasheet data for part 'BS170' (known: " in plain


def test_ldo_unknown_part_names_the_closest_type():
    env = calc_power.ldo("5V", "3V3", "100mA", part="AMS1117")
    w = _warn(env, "part_unknown")
    assert "no datasheet data for part 'AMS1117' (closest: AMS1117-3.3, a different type with its own ratings; known: " in w["message"]
    assert "closest" not in _warn(calc_power.ldo("5V", "3V3", "100mA", part="LM1117"), "part_unknown")["message"]


def test_closest_helper():
    assert parts.closest("2N2222", ("npn", "pnp")) == "2N2222A"
    assert parts.closest(" 2n2222 ", ("npn",)) == "2N2222A"
    assert parts.closest("2N2222A", ("npn",)) is None  # a known name has no "closest"
    assert parts.closest("mcp1700", ("ldo",)) is None  # nor has a known alias
    assert parts.closest("BC547", ("npn",)) is None
    assert parts.closest("AO3400", ("ldo",)) is None  # only parts of the asked kinds
    assert parts.closest("", ("npn",)) is None and parts.closest(None, ("npn",)) is None


# --- fixtures: only the four named ones carry the new wording --------------------------------------------------------

@pytest.mark.parametrize("name", ["calc.led", "calc.npn"])
def test_calc_fixtures_carry_the_new_pin_sentence(name):
    w = _warn(_fixture(name), "gpio_current")
    assert re.fullmatch(r"The driving pin sources [0-9.]+ mA, below the 40\.0 mA high-level source current of an "
                        r"ESP32-S3 pin \(a typical value, not a maximum; chip not given\)\.", w["message"]), w["message"]


def test_demo_fixture_carries_the_new_pin_sentence():
    text = json.dumps(_fixture("sim.demo"))
    assert "below the 40.0 mA high-level source current" in text and OLD_TAIL not in text


def test_meta_fixture_lists_the_divider_target():
    entry = next(c for c in _fixture("calc.meta")["result"]["calculators"] if c["kind"] == "divider")
    assert any(p["name"] == "target" and p["choices"] == ["esp_pin", "other"] for p in entry["params"])
