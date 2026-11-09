"""Routes GET /calc, POST /calc/{kind}, GET /modules, GET /modules/{id},
project PATCH with the module ops, POST /pins/check with a project (parts/options), through the real router."""
from __future__ import annotations

import json

import pytest
import test_api_support as sup
import test_m0_api_support as msup
from test_api_support import *  # noqa: F403

from circuit_bench import tools
from circuit_bench.bench_core import modspec


@pytest.fixture
def catalog(api, monkeypatch):
    cat = msup.FakeCatalog()
    monkeypatch.setattr(api.core("modules"), "catalog", lambda: cat)
    return cat


# --------------------------------------------------------------------------------------------- calculators

def test_get_calc_lists_the_register(api):
    env = api.ok(api.get("/calc"))
    calckit = api.core("calckit")
    assert env["action"] == "calc.list" and env["result"]["calculators"] == calckit.meta()
    assert [c["kind"] for c in env["result"]["calculators"]][:6] == list(modspec.BASIC_CALCS)
    assert env["result"]["groups"] == list(modspec.CALC_GROUPS)
    led = env["result"]["calculators"][0]
    assert led == {"kind": "led", "title": "LED series resistor", "group": "basics", "summary": led["summary"],
                   "params": [{"name": "v_supply", "unit": "V", "required": True, "default": None},
                              {"name": "v_f", "unit": "V", "required": True, "default": None},
                              {"name": "i_f", "unit": "A", "required": True, "default": None},
                              {"name": "series", "unit": "str", "required": False, "default": "E12"}]}


def test_static_calc_routes_per_basic_kind_stay(api):
    paths = {r.path for r in api.mod.router.routes}
    for kind in modspec.BASIC_CALCS:
        assert f"/calc/{kind}" in paths
    assert "/calc" in paths and "/calc/{kind}" in paths
    env = api.ok(api.post("/calc/led", {"v_supply": "3V3", "v_f": "2V", "i_f": "5mA"}))
    assert env["action"] == "calc.led"


def test_a_new_calculator_is_served_by_the_generic_route(api, monkeypatch):
    msup.dummy_calc(api.core("calckit"), api.core("contracts"), monkeypatch)
    env = api.ok(api.post(f"/calc/{msup.DUMMY}", {"v_x": "3V3", "n": 4}))
    assert env["action"] == f"calc.{msup.DUMMY}" and env["result"]["echo"] == {"v_x": "3V3", "n": 4}
    api.err(api.post(f"/calc/{msup.DUMMY}", {"v_x": "3V3", "bogus": 1}), 400, "invalid_args")
    env = api.err(api.post(f"/calc/{msup.DUMMY}", {"v_x": "100V"}), 400, "invalid_args")
    assert [w["code"] for w in env["warnings"]] == ["low_voltage_only"]
    api.err(api.post(f"/calc/{msup.DUMMY}", content=b"{nope", headers={"content-type": "application/json"}), 400,
            "invalid_args")
    assert msup.DUMMY in [c["kind"] for c in api.ok(api.get("/calc"))["result"]["calculators"]]


def test_unknown_calculator_is_404(api):
    resp = api.post("/calc/unknown", {})
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "invalid_args"
    assert resp.json()["action"] == "calc.list"


# --------------------------------------------------------------------------------------------- modules

def test_get_modules_search(api, catalog):
    env = api.ok(api.get("/modules", params={"q": "zz", "interface": "i2c", "limit": "5", "offset": "0"}))
    assert env["action"] == "modules.list" and env["result"]["total"] == 1
    assert env["result"]["items"][0]["id"] == "zz_sensor" and env["result"]["limit"] == 5
    assert catalog.calls[-1] == ("search", {"q": "zz", "category": None, "interface": "i2c", "limit": 5, "offset": 0})
    env = api.ok(api.get("/modules"))
    assert env["result"]["total"] == 2 and env["result"]["limit"] == 40
    for bad in ({"limit": "0"}, {"limit": "201"}, {"limit": "x"}, {"offset": "-1"}, {"q": "x" * 65}):
        api.err(api.get("/modules", params=bad), 400, "invalid_args")


def test_get_module_full_view_matches_the_tool_view(api, catalog, monkeypatch):
    env = api.ok(api.get("/modules/zz-breakout"))
    assert env["action"] == "modules.info"
    m = env["result"]["module"]
    assert m["id"] == "zz_sensor" and m["class"] == "A" and m["variants"] == [{"id": "b", "title": "Variant B"}]
    assert m["supplies"]["VDD"]["min"]["evidence"] == "VDD 1.71 3.6 V"  # the desktop gets the evidence lines
    assert [w["code"] for w in env["warnings"]] == ["mod_hazard_heat"]
    assert [s["id"] for s in env["sources"]] == [msup.SRC]
    # the tool view is the same entry without evidence/page
    from circuit_bench.bench_core import modules
    monkeypatch.setattr(modules, "catalog", lambda: msup.FakeCatalog())
    tool = json.loads(tools.make_handlers(tools.Host())["bench_pins"]({"action": "module", "id": "zz-breakout"}))
    assert tool["result"]["module"] == tools._f_compact(m)
    assert tool["warnings"] == env["warnings"] and tool["summary"] == env["summary"]
    env = api.ok(api.get("/modules/zz_sensor", params={"variant": "b"}))
    assert env["result"]["module"]["variant"] == "b" and env["result"]["module"]["title"].endswith("(B)")


def test_get_module_errors(api, catalog, monkeypatch):
    api.err(api.get("/modules/nope"), 400, "invalid_args")

    def broken():
        raise NotImplementedError
    monkeypatch.setattr(api.core("modules"), "catalog", broken)
    resp = api.get("/modules/zz_sensor")
    assert resp.json()["error"]["code"] == "rule_data_missing" and resp.json()["action"] == "modules.info"
    resp = api.get("/modules")
    assert resp.json()["error"]["code"] == "rule_data_missing" and resp.json()["action"] == "modules.list"


def test_route_and_tool_share_their_constants(api):
    routes = sup.load_plugin_api()  # the route folder is loaded by file location (no tools import there)
    import sys
    catalog = sys.modules["circuit_bench_api_routes.catalog"]
    assert routes is not None and catalog.VIEW_KEYS == tools.MODULE_VIEW_KEYS
    assert catalog.HAZARD_DANGER == tools.HAZARD_DANGER


# --------------------------------------------------------------------------------------------- projects, pins

def test_patch_passes_the_module_ops_to_project_update(api, monkeypatch):
    api.create("mod-r")
    seen = msup.fake_module_update(api.core("project"), monkeypatch)
    ops = [{"op": "add_module", "module": "zz_sensor", "ref": "U1", "conn": {"SDA": "GPIO8"}},
           {"op": "connect", "ref": "U1", "conn": {"SCL": "GPIO9"}}, {"op": "set_rails", "rails": {"VMOT": 12}}]
    env = api.ok(api.patch("/projects/mod-r", {"expected_rev": api.project("mod-r")["rev"], "ops": ops}))
    assert seen[-1] == ops  # no whitelist in the route: the ops reach project.update unchanged
    part = env["result"]["project"]["parts"][-1]
    assert part["conn"] == {"SDA": "GPIO8", "SCL": "GPIO9"} and env["result"]["project"]["options"]["rails"] == {"VMOT": 12}


def test_pins_check_with_a_project_passes_parts_and_options(api, monkeypatch):
    api.create("chk-r")
    api.apply("chk-r", {"op": "assign", "role": "LED", "mode": "out", "pin": 4},
              {"op": "add_parts", "parts": [{"ref": "R1", "kind": "resistor", "value": "1k"}]})
    pins = api.core("pins")
    calls = []
    real = pins.check

    def spy(*a, **kw):
        calls.append(kw)
        return real(*a, **kw)

    monkeypatch.setattr(pins, "check", spy)
    api.ok(api.post("/pins/check", {"project": "chk-r"}))
    assert calls[-1]["parts"][0]["ref"] == "R1" and isinstance(calls[-1]["options"], dict)
    api.ok(api.post("/pins/check", {"chip": "esp32s3", "assignments": [{"role": "LED", "mode": "out", "pin": 4}]}))
    assert "parts" not in calls[-1]
