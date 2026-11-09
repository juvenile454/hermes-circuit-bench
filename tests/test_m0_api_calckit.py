"""Calckit register, auto-discovery, compatibility views, generic 60 V rule."""
from __future__ import annotations

import inspect
import sys

import pytest
import test_m0_api_support as sup

from circuit_bench.bench_core import calc, calc_power, calckit, calcs, contracts, modspec


def test_basics_first_in_the_fixed_order_then_new_kinds_sorted(monkeypatch):
    assert calckit.kinds()[:6] == modspec.BASIC_CALCS
    assert set(calckit.kinds()[6:]) <= set(modspec.NEW_CALCS)
    assert list(calckit.kinds()[6:]) == sorted(calckit.kinds()[6:])
    assert calckit.problems() == []  # every calcs/*.py imported
    sup.dummy_calc(calckit, contracts, monkeypatch)
    assert calckit.kinds()[-1] == sup.DUMMY or sup.DUMMY in calckit.kinds()[6:]
    assert calckit.kinds()[:6] == modspec.BASIC_CALCS


def test_every_kind_has_its_action_and_valid_metadata():
    for m in calckit.meta():
        assert f"calc.{m['kind']}" in contracts.ACTIONS
        assert m["group"] in modspec.CALC_GROUPS and 0 < len(m["title"]) <= 40 and 0 < len(m["summary"]) <= 120
        assert {"kind", "title", "group", "summary", "params"} <= set(m) <= {"kind", "title", "group", "summary",
                                                                              "params", "one_of"}
        names = [p["name"] for p in m["params"]]
        assert all(s and set(s) <= set(names) for s in m.get("one_of", []))
        for p in m["params"]:
            assert {"name", "unit", "required", "default"} <= set(p) <= {"name", "unit", "required", "default", "choices"}
            assert p["unit"] in calckit.PARAM_UNITS
            # fixed values only for text params; the default is one of them
            assert "choices" not in p or (p["unit"] == "str" and p["choices"] and all(isinstance(c, str) for c in
                                          p["choices"]) and p["default"] in (None, *p["choices"]))
    assert all(m["group"] == "basics" for m in calckit.meta()[:6])


def test_compat_views_follow_the_register(monkeypatch):
    assert tuple(calc.CALCULATORS) == calckit.kinds() and len(calc.CALCULATORS) == len(calckit.kinds())
    assert calc.CALCULATORS["mosfet"] is calc_power.mosfet and calc.PARAMS["led"] == calckit.params("led")
    assert "nope" not in calc.CALCULATORS
    with pytest.raises(KeyError):
        calc.CALCULATORS["nope"]
    sup.dummy_calc(calckit, contracts, monkeypatch)
    assert sup.DUMMY in calc.CALCULATORS and calc.PARAMS[sup.DUMMY][0][0] == "v_x"
    for kind in calckit.kinds():  # params match the function signature (as test_calc_calculators does for all)
        sig = inspect.signature(calc.CALCULATORS[kind])
        assert [p[0] for p in calc.PARAMS[kind]] == list(sig.parameters), kind


def test_run_is_calc_run():
    params = {"v_supply": "3V3", "v_f": "2V", "i_f": "5mA"}
    assert calckit.run("led", params) == calc.run("led", params) == calc.led("3V3", "2V", "5mA")
    with pytest.raises(contracts.BenchError) as e:
        calckit.run("nope", {})
    assert e.value.code == "invalid_args" and "led" in e.value.hint
    for bad, needle in (([1], "must be an object"), ({"bogus": 1}, "unknown parameter"), ({}, "missing parameter")):
        env = calckit.run("led", bad)
        assert env["ok"] is False and needle in env["error"]["message"] and env["action"] == "calc.led"


def test_generic_low_voltage_rule_for_every_volt_input(monkeypatch):
    sup.dummy_calc(calckit, contracts, monkeypatch)  # zz_dummy never calls num(): the register refuses anyway
    env = calckit.run(sup.DUMMY, {"v_x": "61V"})
    assert env["ok"] is False and env["error"]["code"] == "invalid_args" and "above 60 V" in env["error"]["message"]
    assert [w["code"] for w in env["warnings"]] == ["low_voltage_only"] and env["warnings"][0]["severity"] == "danger"
    assert calckit.run(sup.DUMMY, {"v_x": "60V"})["ok"] is True  # inclusive limit
    assert calckit.run(sup.DUMMY, {"v_x": 230})["error"]["code"] == "invalid_args"
    # every basic calculator with a V input: same refusal and warning as before
    for kind in modspec.BASIC_CALCS:
        volts = [n for n, u, _r, _d in calckit.params(kind) if u == "V"]
        assert volts, kind
        params = {n: "1V" for n, u, r, _d in calckit.params(kind) if r}
        params.update({n: "1A" for n, u, r, _d in calckit.params(kind) if r and u == "A"})
        params.update({n: "100pF" for n, u, r, _d in calckit.params(kind) if r and u == "F"})
        params.update({n: "1k" for n, u, r, _d in calckit.params(kind) if r and u == "Ω"})
        params[volts[0]] = "230V"
        env = calckit.run(kind, params)
        assert env["ok"] is False and [w["code"] for w in env["warnings"]] == ["low_voltage_only"], kind


def test_register_checks_its_arguments(monkeypatch):
    monkeypatch.setattr(contracts, "ACTIONS", contracts.ACTIONS | {"calc.zz_x"})

    def fn(v):
        return {}

    ok = {"title": "X", "group": "basics", "summary": "S."}
    params = (("v", "V", True, None),)
    for kind, kw, p in [("A", ok, params), ("zz_y", ok, params), ("zz_x", {**ok, "group": "misc"}, params),
                        ("zz_x", {**ok, "title": "t" * 41}, params), ("zz_x", {**ok, "summary": ""}, params),
                        ("zz_x", ok, (("v", "mV", True, None),)), ("zz_x", ok, (("w", "V", True, None),)),
                        ("zz_x", ok, (("v", "V", "yes", None),)), ("zz_x", ok, (("v", "V", True),))]:
        with pytest.raises(ValueError):
            calckit.register(kind, fn, p, **kw)
    with pytest.raises(ValueError, match="registered twice"):
        calckit.register("led", calc.led, calckit.params("led"), **ok)
    assert "zz_x" not in calckit.REGISTRY


def test_auto_discovery_imports_calcs_modules_sorted_and_isolates_broken_ones(tmp_path, monkeypatch):
    (tmp_path / "zz_b.py").write_text(
        "from circuit_bench.bench_core import calckit\n"
        "ORDER = calckit.__dict__.setdefault('_test_order', [])\nORDER.append('zz_b')\n"
        "def zz_b(v_x):\n    return calckit.envelope('calc.zz_b', 'b', {})\n"
        "calckit.register('zz_b', zz_b, (('v_x', 'V', True, None),), title='B', group='power', summary='B.')\n",
        encoding="utf-8")
    (tmp_path / "zz_a.py").write_text(
        "from circuit_bench.bench_core import calckit\n"
        "calckit.__dict__.setdefault('_test_order', []).append('zz_a')\nraise RuntimeError('broken on purpose')\n",
        encoding="utf-8")
    (tmp_path / "_helper.py").write_text("raise AssertionError('private modules are not calculators')\n",
                                         encoding="utf-8")
    monkeypatch.setattr(contracts, "ACTIONS", contracts.ACTIONS | {"calc.zz_b"})
    monkeypatch.setattr(calcs, "__path__", [*calcs.__path__, str(tmp_path)])
    monkeypatch.setattr(calckit, "_LOADED", False)
    monkeypatch.setattr(calckit, "_PROBLEMS", [])
    monkeypatch.setattr(calckit, "REGISTRY", dict(calckit.REGISTRY))  # discovery adds zz_b to this copy only
    for name in ("zz_a", "zz_b", "_helper"):
        monkeypatch.delitem(sys.modules, f"circuit_bench.bench_core.calcs.{name}", raising=False)
    try:
        assert calckit.kinds()[-1] == "zz_b" and calckit.kinds()[:6] == modspec.BASIC_CALCS
        assert calckit.__dict__["_test_order"] == ["zz_a", "zz_b"]  # sorted by file name
        assert len(calckit.problems()) == 1 and "zz_a.py: RuntimeError: broken on purpose" in calckit.problems()[0]
        assert calckit.run("zz_b", {"v_x": "3V3"})["ok"] is True
    finally:
        calckit.__dict__.pop("_test_order", None)
        for name in ("zz_a", "zz_b"):
            sys.modules.pop(f"circuit_bench.bench_core.calcs.{name}", None)
    # monkeypatch puts the real REGISTRY back afterwards (zz_b lived only in the copy)


def test_public_helpers_behave_like_the_old_private_ones():
    assert calc._num is calckit.num and calc._q is calckit.q and calc._action is calckit.action
    assert calckit.num("4k7", "Ω", "r") == pytest.approx(4700.0)
    assert calckit.q(0.0025999999999999994, "A")["value"] == 0.0026
    assert calckit.fmt(4700, "Ω") == "4.70 kΩ"
    assert calckit.step("I", "U/R", 0.001, "A")["value"]["display"] == "1.00 mA"
    assert calckit.series("e24") == "E24" and calckit.choice("Fast", ("standard", "fast"), "mode") == "fast"
    assert calckit.LOW_VOLTAGE_MAX_V == calc.LOW_VOLTAGE_MAX_V == modspec.MAX_RAIL_V == 60.0
    assert calckit.RULE == calc.RULE == "rule-of-thumb"
    for name in ("BenchError", "assumption", "check", "envelope", "fail", "warning", "sources", "parts", "eseries",
                 "units"):
        assert hasattr(calckit, name), name


def test_listing_names_every_input(monkeypatch):
    sup.dummy_calc(calckit, contracts, monkeypatch)
    full = calckit.listing()
    assert full["ok"] and full["action"] == "calc.list" and full["result"]["groups"] == list(modspec.CALC_GROUPS)
    assert full["result"]["calculators"] == calckit.meta()
    compact = calckit.listing(compact=True)["result"]["calculators"]
    assert [c["kind"] for c in compact] == list(calckit.kinds())
    for c in compact:
        for name, *_ in calckit.params(c["kind"]):
            assert name in c["inputs"], (c["kind"], name)
    led = next(c for c in compact if c["kind"] == "led")
    assert led["inputs"] == "v_supply V, v_f V, i_f A; optional: series=E12"


def test_meta_choices_and_one_of():
    """Fixed text values and alternative input sets reach the desktop through GET /calc."""
    meta = {m["kind"]: m for m in calckit.meta()}
    ch = {k: {p["name"]: p["choices"] for p in m["params"] if "choices" in p} for k, m in meta.items()}
    assert ch["current_sense"]["variant"] == ["05b", "20a", "30a"] and "a4988" in ch["current_limit"]["driver"]
    assert "AMS1117-3.3" in ch["ldo"]["part"] and ch["ina_shunt"]["pga"] == ["auto", "1", "2", "4", "8"]
    assert meta["buck"]["one_of"] == [["v_out"], ["r_top", "r_bottom"]]
    assert meta["charger"]["one_of"] == [["r_prog"], ["i_charge"]]
    # a listed value is accepted by the calculator (no invalid_args for it)
    assert calckit.run("current_sense", {"variant": "20a"})["ok"]
    assert calckit.run("ina_shunt", {"part": "ina219", "i_max": "2A", "r_shunt": "0.1", "pga": "8"})["error"] is None
    assert calckit.run("current_limit", {"driver": ch["current_limit"]["driver"][0], "r_sense": "0.1",
                                         "v_ref": "0.5V"})["error"] is None
