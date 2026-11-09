"""calc opto: both optocouplers check their output level against the ESP input maximum; a PC817 pull-up at or
below VCE(sat) is an input error, not an internal lookup failure."""
from __future__ import annotations

import pytest

from circuit_bench.bench_core import calckit, electrical
from circuit_bench.bench_core.calcs import opto


def _calc(**params):
    env = calckit.run("opto", params)
    assert env["ok"], env.get("error")
    return env


def _level(env):
    return [w for w in env["warnings"] if w["code"] == "opto_output_level"]


def test_pc817_pullup_above_the_esp_input_maximum_is_danger():
    env = _calc(part="pc817", v_drive=3.3, v_pullup=5, chip="esp32s3")
    (w,) = _level(env)
    assert w["severity"] == "danger"
    esp_src = list(electrical.get("esp32s3")["source_ids"])
    assert esp_src and set(esp_src) <= set(w["source_ids"])
    assert opto.PC_SRC in w["source_ids"]
    assert "PC817" in w["message"] and "esp32s3" in w["message"]
    listed = {s["id"] for s in env["sources"]}
    assert set(w["source_ids"]) <= listed


def test_pc817_and_6n137_share_the_same_output_check():
    pc = _level(_calc(part="pc817", v_drive=5, v_pullup=5, chip="esp32s3"))[0]
    on = _level(_calc(part="6n137", v_drive=5, v_pullup=5, chip="esp32s3"))[0]
    assert pc["severity"] == on["severity"] == "danger"
    assert [s for s in pc["source_ids"] if s != opto.PC_SRC] == [s for s in on["source_ids"] if s != opto.ON_SRC]


def test_pc817_without_chip_gives_the_info_hint():
    (w,) = _level(_calc(part="pc817", v_drive=3.3, v_pullup=5))
    assert w["severity"] == "info"
    assert "chip=" in w["message"]
    on = _level(_calc(part="6n137", v_drive=5))
    assert on[0]["severity"] == "info"


def test_pc817_pullup_at_3v3_is_fine():
    assert _level(_calc(part="pc817", v_drive=3.3, v_pullup=3.3, chip="esp32s3")) == []


@pytest.mark.parametrize("v_pullup", [0.1, 0.2, "200mV"])
def test_pc817_pullup_at_or_below_vce_sat_is_invalid_args(v_pullup):
    env = calckit.run("opto", {"part": "pc817", "v_drive": 3.3, "v_pullup": v_pullup})
    assert env["ok"] is False
    err = env["error"]
    assert err["code"] == "invalid_args"
    assert err["message"].startswith("v_pullup ") and "must be above the PC817 VCE(sat) 0.2 V" in err["message"]
    assert err["hint"] == "give v_pullup above 0.2 V, e.g. 3.3 V"
    assert "E-series" not in err["message"]


def test_pc817_pullup_below_vce_sat_with_user_resistor_is_invalid_args():
    env = calckit.run("opto", {"part": "pc817", "v_drive": 3.3, "v_pullup": 0.1, "r_pullup": "1k"})
    assert env["ok"] is False and env["error"]["code"] == "invalid_args"


def test_pc817_values_unchanged_with_a_chip():
    env = _calc(part="pc817", v_drive=3.3, chip="esp32s3")
    r = env["result"]
    assert r["r_led"]["value"] == 330.0 and r["r_pullup"]["value"] == 2700.0
    assert r["v_out_high"]["value"] == pytest.approx(3.3)
