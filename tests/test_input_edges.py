"""Input edges that must end as invalid_args (never tool_failed) or give a clean summary: pin suggest roles,
BOM quantities, plain-number calculator inputs, unknown NTC parts, duplicate pins in the check summary."""
from __future__ import annotations

import json
import math

import pytest

from circuit_bench import tools
from circuit_bench.bench_core import bom, calckit, pins
from circuit_bench.bench_core.contracts import BenchError


def _call(name, **args):
    out = tools.make_handlers(tools.Host(hook_active=True))[name](args)
    return json.loads(out)


# --- bench_pins suggest: role that is not text --------------------------------------------------------------------
@pytest.mark.parametrize("role", [{}, [], {"a": 1}, ["LED"]])
def test_suggest_with_a_non_text_role_is_invalid_args(role):
    env = _call("bench_pins", action="suggest", chip="esp32s3", wifi=False,
                requests=[{"role": role, "mode": "out"}])
    assert env["ok"] is False
    assert env["error"]["code"] == "invalid_args", env["error"]


def test_suggest_with_text_roles_still_works():
    env = _call("bench_pins", action="suggest", chip="esp32s3", wifi=False,
                requests=[{"role": "LED", "mode": "out"}, {"mode": "in"}])
    assert env["ok"] is True, env.get("error")


# --- BOM quantities --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("qty", ["nan", "inf", "-inf", "1e300", "1000", "0", "1.5"])
def test_bom_csv_bad_quantity(qty):
    with pytest.raises(BenchError) as e:
        bom.parse(f"ref,value,qty\nR1,10k,{qty}\n")
    assert e.value.code == "invalid_args"
    assert e.value.message.startswith(f"bad quantity {qty!r}")


@pytest.mark.parametrize("qty", [math.nan, math.inf, 1e300, 1000])
def test_bom_row_list_bad_quantity(qty):
    with pytest.raises(BenchError) as e:
        bom.parse([{"ref": "R1", "value": "10k", "qty": qty}])
    assert e.value.code == "invalid_args"
    assert e.value.message.startswith("bad quantity")


@pytest.mark.parametrize(("qty", "want"), [("1", 1), ("999", 999), ("2.0", 2), ("", None)])
def test_bom_good_quantities_unchanged(qty, want):
    rows = bom.parse(f"ref,value,qty\nR1,10k,{qty}\n")
    assert rows[0]["qty"] == (want if want is not None else 1)


def test_solder_plan_with_nan_quantity_is_invalid_args():
    env = _call("bench_solder", action="plan", bom=[{"ref": "R1", "value": "10k", "qty": math.nan}])
    assert env["ok"] is False
    assert env["error"]["code"] == "invalid_args", env["error"]
    assert "bad quantity" in env["error"]["message"]


# --- plain-number calculator inputs name the parameter ----------------------------------------------------------
@pytest.mark.parametrize("name", ["hfe_min", "forced_beta"])
def test_count_parse_error_names_the_parameter(name):
    env = calckit.run("npn", {"v_drive": 3.3, "i_load": "100mA", name: "abc"})
    assert env["ok"] is False and env["error"]["code"] == "invalid_args"
    assert env["error"]["message"].startswith(f"{name}:")


def test_count_unit_and_sign_errors_unchanged():
    env = calckit.run("npn", {"v_drive": 3.3, "i_load": "100mA", "hfe_min": "5V"})
    assert env["error"]["message"] == "hfe_min is a plain number, got a value in V"
    env = calckit.run("npn", {"v_drive": 3.3, "i_load": "100mA", "hfe_min": -5})
    assert env["error"]["message"].startswith("hfe_min must be positive")


# --- calc ntc: unknown part is an input error --------------------------------------------------------------------
def test_ntc_unknown_part_is_invalid_args_with_the_known_list():
    env = calckit.run("ntc", {"part": "NTC-XYZ"})
    assert env["ok"] is False
    assert env["error"]["code"] == "invalid_args"
    assert env["error"]["hint"].startswith("known NTCs: ") and "NTCLE100E3103" in env["error"]["hint"]


# --- pins.check summary: one entry per pin -------------------------------------------------------------------------
def test_duplicate_pin_named_once_in_the_summary():
    env = pins.check("esp32s3", [{"role": "LED", "mode": "out", "pin": 4}, {"role": "BTN", "mode": "in", "pin": 4}],
                     wifi=False)
    assert env["ok"], env.get("error")
    assert env["summary"].count("GPIO4: duplicate pin") == 1, env["summary"]
    assert env["result"]["counts"]["blocked"] == 2
    assert [p["verdict"] for p in env["result"]["pins"]] == ["blocked", "blocked"]


def test_three_duplicate_pins_fit_in_the_summary_without_ellipsis():
    items = [{"role": f"R{i}", "mode": "out", "pin": p} for i, p in enumerate((4, 4, 5, 5, 6, 6))]
    env = pins.check("esp32s3", items, wifi=False)
    s = env["summary"]
    assert all(s.count(f"GPIO{p}: duplicate pin") == 1 for p in (4, 5, 6)), s
    assert "…" not in s
