"""MOSFET low-side switch and linear regulator (bench_core/calc_power.py).

Mandatory values are recomputed by hand in the comments (datasheet values from data/parts/power.json, quoted in
tests/corpus/excerpts/calc-plus-*.txt). Results are rounded to 6 significant digits (calc._q), hence rel=1e-5.
"""
import inspect
import json

import pytest

from circuit_bench import tools
from circuit_bench.bench_core import calc, calc_power, contracts, parts

REL = 1e-5


def _ok(env, action):
    assert contracts.validate_envelope(env) == [], env
    assert env["ok"] is True and env["action"] == action, env.get("error")
    return env


def _checks(env):
    return {c["id"].removeprefix(env["action"] + "."): c["status"] for c in env["checks"]}


def _codes(env):
    return [w["code"] for w in env["warnings"]]


def _v(env, key):
    return env["result"][key]["value"]


# --- MOSFET: mandatory values ---------------------------------------------------------------------------------------
def test_mosfet_ao3400a_at_esp32_gpio():
    # V_GS = 3.3 V · 100 kΩ / (100 Ω + 100 kΩ) = 3.2967033 V  → highest datasheet row ≤ V_GS: V_GS 2.5 V, 48 mΩ max
    # P = (2 A)² · 0.048 Ω = 0.192 W; V_DS = 2 A · 0.048 Ω = 0.096 V
    # T_J = 25 °C + 0.192 W · 125 °C/W = 49.0 °C ≤ 150 °C; V_DS 12 V ≤ 30 V; I_D 2 A ≤ 5.7 A
    # I_G,peak = 3.3 V / 100 Ω = 33 mA; I_PD = 3.2967 V / 100 kΩ = 32.967 µA
    env = _ok(calc_power.mosfet(2.0, 12.0, part="AO3400A"), "calc.mosfet")
    assert _v(env, "v_gs") == pytest.approx(3.3 * 100_000 / 100_100, rel=REL)
    assert _v(env, "r_ds_on") == pytest.approx(0.048, rel=REL)
    assert _v(env, "p_loss") == pytest.approx(0.192, rel=REL)
    assert _v(env, "v_ds_on") == pytest.approx(0.096, rel=REL)
    assert _v(env, "t_j") == pytest.approx(49.0, rel=REL)
    assert _v(env, "i_gate_peak") == pytest.approx(0.033, rel=REL)
    assert _v(env, "i_pulldown") == pytest.approx(32.967033e-6, rel=REL)
    assert env["result"]["p_loss"]["display"] == "192 mW" and env["result"]["t_j"]["display"] == "49.0 °C"
    assert _checks(env) == {"logic_level": "passed", "v_ds_max": "passed", "i_d_max": "passed", "t_j": "passed",
                            "gate_network": "passed"}
    basis = env["result"]["r_ds_on_basis"]
    assert basis["from"] == "datasheet" and basis["v_gs"]["value"] == 2.5 and basis["i_d"]["value"] == 3.0
    assert basis["evidence"] == "RDS(ON) (at VGS = 2.5V) < 48mW"
    assert [s["id"] for s in env["sources"]] == ["rule-of-thumb", "ds-esp32-s3-wroom-1-power", "aos-ao3400a"]
    keys = [a["key"] for a in env["assumptions"]]
    assert {"gate_v", "v_gs", "r_ds_on", "r_th_ja", "gate_network", "t_ambient"} <= set(keys)
    gate = next(a for a in env["assumptions"] if a["key"] == "gate_v")
    assert "2.64 V" in gate["reason"] and "Table 6-3" in gate["reason"]  # 0.8 × 3.3 V, WROOM-1 datasheet
    assert "rule of thumb" in next(c for c in env["checks"] if c["id"].endswith("gate_network"))["detail"]
    assert "192 mW" in env["summary"] and "49.0 °C" in env["summary"]
    assert [s["name"] for s in env["result"]["steps"]] == ["V_GS", "R_DS(on)", "P", "V_DS", "T_J", "I_G,peak", "I_PD"]
    assert "P = I_load² · R_DS(on)" in env["result"]["formula"]


def test_mosfet_irlz44n_is_not_logic_level_at_3v3():
    # IRLZ44N R_DS(on) rows start at V_GS 4.0 V; V_GS 3.2967 V < 4.0 V → not specified, no power, T_J not checked.
    # V_DS 12 V ≤ 55 V and I_D 5 A ≤ 47 A (T_C 25 °C) still pass; V_GS(th) max 2.0 V < 3.2967 V → no threshold warning.
    env = _ok(calc_power.mosfet(5.0, 12.0, part="IRLZ44N"), "calc.mosfet")
    assert _checks(env) == {"logic_level": "failed", "v_ds_max": "passed", "i_d_max": "passed", "t_j": "not_checked",
                            "gate_network": "passed"}
    assert env["result"]["r_ds_on"] is None and env["result"]["p_loss"] is None and env["result"]["t_j"] is None
    logic = env["checks"][0]
    assert "4.00 V" in logic["detail"] and "3.30 V" in logic["detail"]
    warn = next(w for w in env["warnings"] if w["code"] == "mosfet_not_logic_level")
    assert "AO3400A" in warn["message"] and warn["source_ids"] == ["infineon-irlz44n"]
    assert "mosfet_below_threshold" not in _codes(env)
    assert "not specified" in env["summary"]


def test_mosfet_irlz44n_at_5v_uses_the_row_below_the_divided_gate_voltage():
    # V_GS = 5 V · 100 kΩ / 100.1 kΩ = 4.995005 V < 5.0 V → row V_GS 4.0 V, 35 mΩ (not the 5.0 V row with 25 mΩ)
    # P = (5 A)² · 0.035 Ω = 0.875 W; V_DS = 0.175 V; T_J = 25 °C + 0.875 W · 62 °C/W = 79.25 °C ≤ 175 °C
    env = _ok(calc_power.mosfet("5A", "12V", gate_v="5V", part="irlz44npbf"), "calc.mosfet")  # alias, any case
    assert _v(env, "v_gs") == pytest.approx(4.995005, rel=REL)
    assert env["result"]["r_ds_on_basis"]["v_gs"]["value"] == 4.0
    assert _v(env, "r_ds_on") == pytest.approx(0.035, rel=REL)
    assert _v(env, "p_loss") == pytest.approx(0.875, rel=REL)
    assert _v(env, "v_ds_on") == pytest.approx(0.175, rel=REL)
    assert _v(env, "t_j") == pytest.approx(79.25, rel=REL)
    assert _checks(env)["logic_level"] == "passed" and _checks(env)["t_j"] == "passed"
    gate = next(a for a in env["assumptions"] if a["key"] == "gate_v")
    assert gate["reason"].startswith("given by you")
    assert "ds-esp32-s3-wroom-1-power" not in [s["id"] for s in env["sources"]]
    # with a stronger pull-down ratio the 5.0 V row applies: R_G 10 Ω, R_PD 100 kΩ → V_GS 4.9995 V, still < 5.0 V;
    # exactly 5.0 V needs no divider loss, which the formula never gives, so the lower row stays the conservative one
    assert calc_power.mosfet(5.0, 12.0, gate_v=5.0, r_gate=10, part="IRLZ44N")["result"]["r_ds_on"]["value"] == 0.035


def test_mosfet_hot_ao3400a_fails_t_j_although_i_d_passes():
    # P = (5 A)² · 0.048 Ω = 1.2 W; T_J = 40 °C + 1.2 W · 125 °C/W = 190 °C > 150 °C → failed, danger warning.
    # I_D 5 A ≤ 5.7 A passes: the drain current rating alone does not protect the part.
    env = _ok(calc_power.mosfet(5.0, 5.0, part="AO3400A", t_ambient="40 °C"), "calc.mosfet")
    assert _v(env, "p_loss") == pytest.approx(1.2, rel=REL)
    assert _v(env, "t_j") == pytest.approx(190.0, rel=REL)
    assert _checks(env)["t_j"] == "failed" and _checks(env)["i_d_max"] == "passed"
    assert "mosfet_overheat" in _codes(env)
    assert "above T_J max 150 °C" in env["summary"]


def test_mosfet_ratings_fail_with_danger_warnings():
    # V_supply 40 V > V_DS max 30 V; I_load 6 A > I_D 5.7 A
    env = _ok(calc_power.mosfet(6.0, 40.0, part="AO3400A"), "calc.mosfet")
    assert _checks(env)["v_ds_max"] == "failed" and _checks(env)["i_d_max"] == "failed"
    sev = {w["code"]: w["severity"] for w in env["warnings"]}
    assert sev["mosfet_v_ds_max"] == sev["mosfet_i_d_max"] == "danger"
    assert len(json.dumps(env, ensure_ascii=False).encode()) <= tools.MAX_BYTES  # no truncation by the tool


def test_mosfet_without_part_is_not_checked():
    env = _ok(calc_power.mosfet(1.0, 12.0), "calc.mosfet")
    assert _checks(env) == {"logic_level": "not_checked", "v_ds_max": "not_checked", "i_d_max": "not_checked",
                            "t_j": "not_checked", "gate_network": "passed"}
    assert "AO3400A" in env["checks"][0]["detail"] and "IRLZ44N" in env["checks"][0]["detail"]
    assert env["result"]["p_loss"] is None and env["result"]["part"] is None
    assert "logic level not checked" in env["summary"]
    # your R_DS(on): P = (1 A)² · 0.05 Ω = 0.05 W, V_DS 0.05 V; logic level still not checked, no T_J without a part
    env = _ok(calc_power.mosfet(1.0, 12.0, r_ds_on="50m"), "calc.mosfet")
    assert _v(env, "p_loss") == pytest.approx(0.05, rel=REL) and _v(env, "v_ds_on") == pytest.approx(0.05, rel=REL)
    assert _checks(env)["logic_level"] == "not_checked" and _checks(env)["t_j"] == "not_checked"
    assert env["result"]["r_ds_on_basis"] == {"from": "user"}


def test_mosfet_unknown_part_and_user_value_with_part():
    env = _ok(calc_power.mosfet(1.0, 12.0, part="BS170"), "calc.mosfet")
    assert _checks(env)["logic_level"] == "not_checked" and "part_unknown" in _codes(env)
    assert "no datasheet data" in env["checks"][0]["detail"]
    # r_ds_on with a part: your value for P (0.02 Ω → (2 A)² · 0.02 = 0.08 W; T_J = 25 + 0.08 · 125 = 35 °C)
    env = _ok(calc_power.mosfet(2.0, 12.0, part="AO3400A", r_ds_on=0.02), "calc.mosfet")
    assert _v(env, "p_loss") == pytest.approx(0.08, rel=REL) and _v(env, "t_j") == pytest.approx(35.0, rel=REL)
    assert "r_ds_on_given" in _codes(env) and _checks(env)["logic_level"] == "passed"


def test_mosfet_threshold_gate_limits_and_rule_of_thumb():
    # gate 1.2 V: V_GS 1.1988 V ≤ V_GS(th) max 1.45 V → caution; no row ≤ 1.1988 V → logic level failed
    env = _ok(calc_power.mosfet(1.0, 5.0, gate_v=1.2, part="AO3400A"), "calc.mosfet")
    assert "mosfet_below_threshold" in _codes(env) and _checks(env)["logic_level"] == "failed"
    # 15 V gate > V_GS max ±12 V → danger
    assert "mosfet_v_gs_max" in _codes(calc_power.mosfet(1.0, 5.0, gate_v=15, part="AO3400A"))
    # rule of thumb ranges R_G 10 Ω–1 kΩ, R_PD 10 kΩ–100 kΩ
    env = _ok(calc_power.mosfet(1.0, 5.0, r_gate="2k", r_pulldown="1M"), "calc.mosfet")
    gate = next(c for c in env["checks"] if c["id"] == "calc.mosfet.gate_network")
    assert gate["status"] == "failed" and "R_G 2.00 kΩ" in gate["detail"] and "R_PD 1.00 MΩ" in gate["detail"]
    assert gate["detail"].endswith("(rule of thumb)")


# --- LDO: mandatory values ----------------------------------------------------------------------------------------
def test_ldo_ams1117_from_usb_at_esp32_s3_supply_current():
    # I_load 0.5 A = minimum supply current for an ESP32-S3-WROOM-1 (datasheet Table 6-2)
    # ΔV = 5 − 3.3 = 1.7 V; P_load = 1.7 V · 0.5 A = 0.85 W; P_q = 5 V · 11 mA = 0.055 W; P = 0.905 W
    # T_J = 25 °C + 0.905 W · 90 °C/W = 106.45 °C ≤ 125 °C; η = 3.3 · 0.5 / (5 · 0.511) = 64.579 %
    # dropout 1.7 V ≥ 1.3 V (I_load ≤ 0.8 A); current limit 0.5 A ≤ 0.9 A; V_in 5 V ≤ 15 V
    env = _ok(calc_power.ldo("5V", "3V3", "500mA", part="AMS1117-3.3"), "calc.ldo")
    assert _v(env, "v_headroom") == pytest.approx(1.7, rel=REL)
    assert _v(env, "p_load") == pytest.approx(0.85, rel=REL)
    assert _v(env, "p_q") == pytest.approx(0.055, rel=REL)
    assert _v(env, "p_total") == pytest.approx(0.905, rel=REL)
    assert _v(env, "t_j") == pytest.approx(106.45, rel=REL)
    assert _v(env, "efficiency") == pytest.approx(3.3 * 0.5 / (5 * 0.511) * 100, rel=REL)
    assert _checks(env) == {"headroom": "passed", "dropout": "passed", "current_limit": "passed", "v_in_max": "passed",
                            "t_j": "passed"}
    info = next(w for w in env["warnings"] if w["code"] == "esp32s3_supply")
    assert info["severity"] == "info" and "500 mA" in info["message"] and "355 mA" in info["message"]
    assert "at or above" in info["message"]
    assert [s["id"] for s in env["sources"]] == ["ams-ams1117", "rule-of-thumb", "ds-esp32-s3-wroom-1-power"]
    part = env["result"]["part"]
    assert part["package"] == "SOT-223" and part["r_th_ja"]["value"] == 90.0 and part["dropout"]["value"] == 1.3
    assert {"i_q", "dropout", "theta_ja", "t_ambient", "i_load"} <= {a["key"] for a in env["assumptions"]}
    assert "905 mW" in env["summary"] and "106 °C" in env["summary"] and "dropout ok" in env["summary"]


def test_ldo_ams1117_from_lithium_cell_fails_the_dropout():
    # 4.2 V (full Li-ion cell) → 3.3 V at the Wi-Fi TX peak 355 mA (WROOM-1 Table 6-4):
    # ΔV = 0.9 V < 1.3 V → dropout failed; P = 0.9 · 0.355 + 4.2 · 0.011 = 0.3195 + 0.0462 = 0.3657 W
    # T_J = 25 + 0.3657 · 90 = 57.913 °C
    env = _ok(calc_power.ldo(4.2, 3.3, 0.355, part="AMS1117-3.3"), "calc.ldo")
    assert _checks(env)["dropout"] == "failed" and "ldo_dropout" in _codes(env)
    assert _v(env, "p_total") == pytest.approx(0.3657, rel=REL)
    assert _v(env, "t_j") == pytest.approx(57.913, rel=REL)
    assert "below" in next(w for w in env["warnings"] if w["code"] == "esp32s3_supply")["message"]
    assert "dropout too low" in env["summary"]
    # exactly at the dropout: 4.6 − 3.3 = 1.3 V counts as enough (float noise 1.2999999999999998)
    assert _checks(calc_power.ldo(4.6, 3.3, 0.5, part="AMS1117-3.3"))["dropout"] == "passed"


def test_ldo_ams1117_at_12v_overheats():
    # P = 8.7 V · 0.5 A + 12 V · 0.011 A = 4.35 + 0.132 = 4.482 W; T_J = 25 + 4.482 · 90 = 428.38 °C > 125 °C
    env = _ok(calc_power.ldo(12, 3.3, 0.5, part="AMS1117-3.3"), "calc.ldo")
    assert _v(env, "p_total") == pytest.approx(4.482, rel=REL)
    assert _v(env, "t_j") == pytest.approx(428.38, rel=REL)
    assert _checks(env)["t_j"] == "failed"
    warn = next(w for w in env["warnings"] if w["code"] == "ldo_overheat")
    assert warn["severity"] == "danger" and "165 °C" in warn["message"]
    assert "above T_J max 125 °C" in env["summary"]


def test_ldo_package_sets_theta_ja():
    # SO-8: 160 °C/W. P = 1.7 · 0.3 + 5 · 0.011 = 0.565 W; T_J = 25 + 0.565 · 160 = 115.4 °C
    # TO-252: 80 °C/W → T_J = 25 + 0.565 · 80 = 70.2 °C
    so8 = _ok(calc_power.ldo(5, 3.3, 0.3, part="AMS1117CS-3.3"), "calc.ldo")
    dpak = _ok(calc_power.ldo(5, 3.3, 0.3, part="AMS1117CD-3.3"), "calc.ldo")
    assert _v(so8, "t_j") == pytest.approx(115.4, rel=REL) and _v(dpak, "t_j") == pytest.approx(70.2, rel=REL)
    assert so8["result"]["part"]["package"] == "SO-8" and dpak["result"]["part"]["package"] == "TO-252"


def test_ldo_above_the_specified_dropout_current_and_current_limit():
    # 1.0 A > 0.8 A: dropout not specified (Note 4) → not_checked; 1.0 A > current limit min 0.9 A → failed
    env = _ok(calc_power.ldo(5, 3.3, 1.0, part="AMS1117-3.3"), "calc.ldo")
    assert _checks(env)["dropout"] == "not_checked" and _checks(env)["current_limit"] == "failed"
    assert "ldo_current_limit" in _codes(env)
    # V_in 16 V > absolute maximum 15 V
    assert _checks(calc_power.ldo(16, 3.3, 0.01, part="AMS1117-3.3"))["v_in_max"] == "failed"


def test_ldo_without_part_is_not_checked():
    # P = (5 − 3.3) · 0.2 = 0.34 W (no quiescent current without a datasheet); η = 3.3 · 0.2 / (5 · 0.2) = 66 %
    env = _ok(calc_power.ldo(5, 3.3, 0.2), "calc.ldo")
    assert _v(env, "p_total") == pytest.approx(0.34, rel=REL) and _v(env, "efficiency") == pytest.approx(66.0, rel=REL)
    assert env["result"]["p_q"] is None and env["result"]["t_j"] is None and env["result"]["part"] is None
    assert _checks(env) == {"headroom": "passed", "dropout": "not_checked", "current_limit": "not_checked",
                            "v_in_max": "not_checked", "t_j": "not_checked"}
    assert all("give part (AMS1117-3.3" in c["detail"] for c in env["checks"][1:])
    assert "not checked (no part)" in env["summary"]
    env = _ok(calc_power.ldo(5, 3.3, 0.2, part="LM1117"), "calc.ldo")
    assert "part_unknown" in _codes(env) and _checks(env)["t_j"] == "not_checked"


def test_ldo_no_headroom_and_output_mismatch():
    env = _ok(calc_power.ldo(3.3, 3.3, 0.2, part="AMS1117-3.3"), "calc.ldo")
    assert _checks(env) == {"headroom": "failed"} and "ldo_no_headroom" in _codes(env)
    assert env["result"]["p_total"] is None
    env = _ok(calc_power.ldo(12, 5, 0.1, part="AMS1117-3.3"), "calc.ldo")
    assert "ldo_v_out_mismatch" in _codes(env) and "esp32s3_supply" not in _codes(env)


# --- inputs, dispatcher, tool --------------------------------------------------------------------------------------
@pytest.mark.parametrize(("kind", "params", "needle"), [
    ("mosfet", {"i_load": "2A"}, "missing parameter(s): v_supply"),
    ("mosfet", {"i_load": "2A", "v_supply": "12V", "gate": 3}, "unknown parameter(s): gate"),
    ("mosfet", {"i_load": "2V", "v_supply": "12V"}, "i_load"),
    ("mosfet", {"i_load": "-1A", "v_supply": "12V"}, "positive"),
    ("mosfet", {"i_load": "1A", "v_supply": "12V", "t_ambient": "300"}, "between"),
    ("mosfet", {"i_load": "1A", "v_supply": "12V", "t_ambient": "25 V"}, "t_ambient"),
    ("mosfet", {"i_load": "1A", "v_supply": "12V", "part": 7}, "part"),
    ("ldo", {"v_in": "5V", "v_out": "3V3"}, "missing parameter(s): i_load"),
    ("ldo", {"v_in": "5V", "v_out": "3V3", "i_load": "0"}, "positive"),
])
def test_invalid_inputs(kind, params, needle):
    env = calc.run(kind, params)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args" and env["action"] == f"calc.{kind}"
    assert needle in env["error"]["message"], env["error"]


def test_temperature_input_forms():
    for t in (40, "40", "40 °C", "40°C", "40C", "40 degC"):
        assert calc_power.ldo(5, 3.3, 0.1, t_ambient=t)["result"]["inputs"]["t_ambient"]["value"] == 40.0, t
    assert calc_power.ldo(5, 3.3, 0.1, t_ambient="-10")["result"]["inputs"]["t_ambient"]["display"] == "-10.0 °C"


def test_run_parses_text_inputs_like_direct_calls():
    assert calc.run("mosfet", {"i_load": "2 A", "v_supply": "12", "part": "AO3400A", "gate_v": "3V3"}) == \
        calc_power.mosfet(2.0, 12.0, part="AO3400A")
    assert calc.run("ldo", {"v_in": "5", "v_out": "3V3", "i_load": "500mA", "part": "AMS1117-3.3", "t_ambient": None}) == \
        calc_power.ldo(5.0, 3.3, 0.5, part="AMS1117-3.3")


def test_registered_in_calculators_params_and_contracts():
    # the six basics come first in a fixed order (modspec.BASIC_CALCS), new calculators follow (calcs/*.py)
    assert list(calc.CALCULATORS)[4:6] == ["mosfet", "ldo"]
    assert calc.CALCULATORS["mosfet"] is calc_power.mosfet and calc.CALCULATORS["ldo"] is calc_power.ldo
    assert {"calc.mosfet", "calc.ldo"} <= contracts.ACTIONS
    assert tools.CALC_KINDS == tuple(calc.CALCULATORS)
    # the backend routes derive their list from the register (core.calckit.kinds()), no literal list
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "circuit_bench" / "dashboard" / "routes" / "workshop.py").read_text(
        encoding="utf-8")
    assert not any(isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "CALCULATORS"
                   for n in ast.parse(src).body)
    assert "core.calckit.kinds()" in src
    for kind in ("mosfet", "ldo"):
        sig = inspect.signature(calc.CALCULATORS[kind])
        assert [p[0] for p in calc.PARAMS[kind]] == list(sig.parameters)
        for name, _unit, required, default in calc.PARAMS[kind]:
            p = sig.parameters[name]
            assert (p.default is inspect.Parameter.empty) == required, name
            if not required:
                assert p.default == default, name


CASES = [
    (calc_power.mosfet, (2.0, 12.0), {"part": "AO3400A"}),
    (calc_power.mosfet, (5.0, 40.0), {"part": "AO3400A", "t_ambient": 60, "r_gate": "2k"}),
    (calc_power.mosfet, (5.0, 12.0), {"part": "IRLZ44N", "gate_v": 5}),
    # largest answer seen in a sweep over parts, ratings and gate voltages (every warning at once)
    (calc_power.mosfet, ("6A", "60V"), {"part": "AO3400A", "gate_v": 15, "r_ds_on": "0.1", "r_gate": "2k",
                                         "r_pulldown": "1M", "t_ambient": "60 °C"}),
    (calc_power.ldo, (5.0, 3.3, 0.5), {"part": "AMS1117-3.3"}),
    (calc_power.ldo, (12.0, 3.3, 1.0), {"part": "AMS1117CS-3.3", "t_ambient": 50}),
]


@pytest.mark.parametrize(("fn", "args", "kwargs"), CASES)
def test_deterministic_and_small(fn, args, kwargs):
    first = json.dumps(fn(*args, **kwargs), ensure_ascii=False)
    assert all(json.dumps(fn(*args, **kwargs), ensure_ascii=False) == first for _ in range(3))
    assert len(first.encode()) <= tools.MAX_BYTES  # the tool passes it on without shortening


def test_tool_runs_and_stores_both_calculators(tmp_path):
    host = tools.Host(hook_active=True)
    handlers = tools.make_handlers(host)
    env = json.loads(handlers["bench_calc"]({"action": "mosfet", "inputs": {"i_load": "2A", "v_supply": "12V",
                                                                             "part": "AO3400A"}}))
    assert env["ok"] and env["result"]["p_loss"]["display"] == "192 mW"
    env = json.loads(handlers["bench_calc"]({"action": "ldo", "v_in": "5V", "v_out": "3V3", "i_load": "0.5A"}))
    assert env["ok"] and env["result"]["p_total"]["display"] == "850 mW"
    assert json.loads(handlers["bench_calc"]({"action": "ldo", "inputs": {"v_in": "5V"}}))["error"]["code"] == "invalid_args"
    created = json.loads(handlers["bench_project"]({"action": "create", "id": "power-test", "title": "Power",
                                                    "chip": "esp32s3", "variant": "n16r8"}))
    assert created["ok"], created
    env = json.loads(handlers["bench_calc"]({"action": "ldo", "inputs": {"v_in": "5V", "v_out": "3V3", "i_load": "0.5A",
                                                                          "part": "AMS1117-3.3"}, "project": "power-test"}))
    assert env["result"]["project_update"]["calc_id"] == "ldo-1"
    env = json.loads(handlers["bench_calc"]({"action": "mosfet", "inputs": {"i_load": "2A", "v_supply": "12V"},
                                             "project": "power-test"}))
    assert env["result"]["project_update"]["calc_id"] == "mosfet-1"


# --- parts.py power data ------------------------------------------------------------------------------------------
def test_power_parts_lookup():
    # the original parts stay first; module families add regulators in data/parts/<family>.json (parts.py globs)
    assert parts.power_ids("nmos")[:2] == ["AO3400A", "IRLZ44N"]
    assert parts.power_ids("ldo")[:3] == ["AMS1117-3.3", "AMS1117CD-3.3", "AMS1117CS-3.3"]
    assert parts.power_part(" ams1117-3.3 ", "ldo")["package"] == "SOT-223"
    with pytest.raises(contracts.BenchError) as e:
        parts.power_part("AO3400A", "ldo")  # a MOSFET is not a regulator
    assert e.value.code == "rule_data_missing"
    with pytest.raises(contracts.BenchError) as e:
        parts.power_part("", "nmos")
    assert e.value.code == "invalid_args"
    # rows: the highest V_GS not above the given one; exactly on a row uses it
    assert parts.r_ds_on_at("AO3400A", 2.4999) is None
    assert parts.r_ds_on_at("AO3400A", 2.5)["max"] == 0.048
    assert parts.r_ds_on_at("AO3400A", 4.5)["max"] == 0.032
    assert parts.r_ds_on_at("AO3400A", 12)["max"] == 0.0265
    assert parts.r_ds_on_at("IRLZ44N", 3.3) is None
    assert parts.power_part("AO3400A", "nmos") is not parts.power_part("AO3400A", "nmos")  # copies
    # the bipolar table is separate: an NPN lookup does not see the MOSFETs
    with pytest.raises(contracts.BenchError):
        parts.get("AO3400A")
