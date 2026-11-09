"""bench_calc npn sizes R_B when r_base is missing (forced beta from the 2N2222A saturation test
conditions, next smaller E12 value); with r_base everything stays as before."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from circuit_bench.bench_core import calc, contracts, eseries

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "tests" / ".corpus" / "calc" / "onsemi-2n2222a-d-rev2.pdf"


def _ok(env):
    assert contracts.validate_envelope(env) == [], env
    assert env["ok"] is True, env
    return env


def test_r_base_is_optional_in_the_parameter_table():
    table = {p[0]: p for p in calc.PARAMS["npn"]}
    assert table["r_base"][2] is False
    assert table["forced_beta"][1:] == ("", False, None)


def test_sizing_without_r_base_rounds_down_to_e12():
    env = _ok(calc.run("npn", {"v_drive": "3V3", "i_load": "100mA", "r_pulldown": "10k", "part": "2N2222A"}))
    r = env["result"]
    assert r["sized"] is True and r["forced_beta_target"] == 10
    # I_B = 100 mA / 10 = 10 mA; I_RB = I_B + 0.7 V / 10 kΩ = 10.07 mA; R = 2.6 V / 10.07 mA = 258.2 Ω -> 220 Ω
    assert math.isclose(r["r_base_ideal"]["value"], 2.6 / 0.01007, rel_tol=1e-5)
    assert r["r_base_chosen"]["value"] == 220.0 == eseries.nearest(2.6 / 0.01007, "E12", "down")
    assert r["inputs"]["r_base"]["value"] == 220.0  # the value the checks ran with (like the default v_be)
    assert math.isclose(r["i_rb"]["value"], 2.6 / 220, rel_tol=1e-5)
    assert r["forced_beta"]["value"] < 10  # the smaller resistor drives the base harder than the target
    checks = {c["id"]: c["status"] for c in env["checks"]}
    assert checks == {"calc.npn.base_drive": "passed", "calc.npn.saturation": "passed", "calc.npn.ic_max": "passed"}
    names = [s["name"] for s in r["steps"]]
    assert names[:3] == ["I_B target", "R_B ideal", "R_B (E12)"]
    a = {x["key"]: x for x in env["assumptions"]}
    assert a["forced_beta"]["value"] == "10" and "IC = 150 mAdc, IB = 15 mAdc" in a["forced_beta"]["reason"]
    assert a["r_base"]["value"] == "E12, next smaller value"
    ids = {s["id"] for s in env["sources"]}
    assert {"onsemi-2n2222a", eseries.SOURCE_ID} <= ids
    assert "gpio_current" in {w["code"] for w in env["warnings"]}  # the GPIO note stays as before
    assert "220 Ω" in env["summary"]


def test_sizing_with_a_given_forced_beta():
    env = _ok(calc.run("npn", {"v_drive": "3V3", "i_load": "13mA", "forced_beta": 20}))
    r = env["result"]
    # I_B = 0.65 mA; R = 2.6 V / 0.65 mA = 4 kΩ -> 3.9 kΩ
    assert r["forced_beta_target"] == 20 and r["r_base_chosen"]["value"] == 3900.0
    assert {x["key"]: x for x in env["assumptions"]}["forced_beta"]["reason"] == "given by you"


def test_given_r_base_is_unchanged_and_ignores_forced_beta():
    params = {"v_drive": "3.3V", "r_base": "1k", "i_load": "13mA", "v_be": "0.7V", "r_pulldown": "10k",
              "part": "2N2222A", "load": "laser"}
    before = _ok(calc.run("npn", params))
    assert "sized" not in before["result"] and "r_base_chosen" not in before["result"]
    after = _ok(calc.run("npn", {**params, "forced_beta": 10}))
    assert after["result"] == before["result"] and after["checks"] == before["checks"]
    assert "forced_beta_ignored" in {w["code"] for w in after["warnings"]}


@pytest.mark.parametrize(("params", "needle"), [
    ({"v_drive": "0.5V", "i_load": "10mA"}, "v_drive"),
    ({"v_drive": "3V3", "i_load": "10mA", "forced_beta": "10mA"}, "forced_beta"),
    ({"v_drive": "3V3", "i_load": "10mA", "forced_beta": 0}, "forced_beta"),
])
def test_sizing_refuses_bad_inputs(params, needle):
    env = calc.run("npn", params)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args"
    assert needle in env["error"]["message"]


def test_forced_beta_default_quotes_the_datasheet():
    assert calc.NPN_FORCED_BETA_DEFAULT == 10
    assert calc.NPN_FORCED_BETA_SOURCE == "onsemi-2n2222a"
    head, cond = calc.NPN_FORCED_BETA_EVIDENCE
    ic, ib = (float(x) for x in __import__("re").findall(r"= (\d+) mAdc", cond))
    assert ic / ib == calc.NPN_FORCED_BETA_DEFAULT
    if not PDF.is_file():
        pytest.skip("corpus not present (scripts/fetch_corpus.py calc)")
    pypdf = pytest.importorskip("pypdf")
    import logging
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    text = pypdf.PdfReader(str(PDF)).pages[2].extract_text()
    # whitespace differs between pypdf versions (lowest-direct extracts "I B"): compare without whitespace
    import re
    hay = re.sub(r"\s+", "", text)
    needle = re.sub(r"\s+", "", head + cond)
    i = hay.find(needle)
    assert i >= 0, (head, cond)
    assert "VCE(sat)" in hay[i + len(needle):i + len(needle) + 40]
