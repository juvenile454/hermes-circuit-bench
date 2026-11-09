"""Tool actions bench_calc list + register kinds, bench_pins modules/module,
bench_project add_module/connect/set_rails, project parts/options in the pin checks, project_view of module parts."""
from __future__ import annotations

import json

import pytest
import test_m0_api_support as sup

from circuit_bench import schemas, tools
from circuit_bench.bench_core import calckit, contracts, modules, pins, project


@pytest.fixture
def host():
    return tools.Host(hook_active=True)


def call(host, name, **args):
    out = tools.make_handlers(host)[name](args)
    assert len(out.encode()) <= tools.MAX_BYTES
    return json.loads(out)


@pytest.fixture
def catalog(monkeypatch):
    cat = sup.FakeCatalog()
    monkeypatch.setattr(modules, "catalog", lambda: cat)
    return cat


@pytest.fixture
def pin_calls(monkeypatch):
    calls = []
    real = pins.check

    def spy(*a, **kw):
        calls.append(kw)
        return real(*a, **kw)

    monkeypatch.setattr(pins, "check", spy)
    return calls


# --------------------------------------------------------------------------------------------- bench_calc

def test_calc_kinds_are_the_register():
    assert tools.CALC_KINDS == calckit.kinds()
    assert schemas.CALCS == list(calckit.kinds())
    assert schemas.CALC["parameters"]["properties"]["action"]["enum"] == [*calckit.kinds(), "list"]


def test_calc_list_names_every_input(host):
    env = call(host, "bench_calc", action="list")
    assert env["ok"] and env["action"] == "calc.list"
    got = env["result"]["calculators"]
    assert [c["kind"] for c in got] == list(calckit.kinds())
    for c in got:
        for name, *_ in calckit.params(c["kind"]):
            assert name in c["inputs"], (c["kind"], name)
        assert c["title"] and c["summary"] and c["group"]


def test_a_new_calculator_appears_in_tool_list_and_schema_without_other_edits(host, monkeypatch):
    sup.dummy_calc(calckit, contracts, monkeypatch)
    env = call(host, "bench_calc", action=sup.DUMMY, inputs={"v_x": "3V3"})
    assert env["ok"] and env["action"] == f"calc.{sup.DUMMY}" and env["result"]["echo"]["n"] == 2
    env = call(host, "bench_calc", action=sup.DUMMY, v_x="5V", n=3)  # top-level inputs work too
    assert env["result"]["echo"] == {"v_x": "5V", "n": 3}
    env = call(host, "bench_calc", action=sup.DUMMY, inputs={"v_x": "120V"})
    assert env["ok"] is False and [w["code"] for w in env["warnings"]] == ["low_voltage_only"]
    listed = call(host, "bench_calc", action="list")["result"]["calculators"]
    assert listed[-1]["kind"] == sup.DUMMY or sup.DUMMY in [c["kind"] for c in listed]
    assert sup.DUMMY in schemas.calc_schema()["parameters"]["properties"]["action"]["enum"]
    assert tools.CALC_KINDS == calckit.kinds()


def test_calc_stores_new_kinds_in_the_project(host, monkeypatch):
    sup.dummy_calc(calckit, contracts, monkeypatch)
    call(host, "bench_project", action="create", id="calc-p", chip="esp32s3")
    env = call(host, "bench_calc", action=sup.DUMMY, inputs={"v_x": "3V3"}, project="calc-p")
    assert env["result"]["project_update"]["calc_id"] == f"{sup.DUMMY}-1"
    assert project.get("calc-p")["result"]["project"]["calcs"][0]["type"] == sup.DUMMY


def test_calc_unknown_action_lists_list(host):
    env = call(host, "bench_calc", action="nope")
    assert env["ok"] is False and env["error"]["code"] == "invalid_args" and "list" in env["error"]["hint"]


# --------------------------------------------------------------------------------------------- bench_pins modules

def test_modules_search_passes_filters_and_pages(host, catalog):
    env = call(host, "bench_pins", action="modules", q="zz", interface="i2c", limit=5, offset=0)
    assert env["ok"] and env["action"] == "modules.list"
    assert env["result"]["total"] == 1 and [r["id"] for r in env["result"]["items"]] == ["zz_sensor"]
    assert catalog.calls[-1] == ("search", {"q": "zz", "category": None, "interface": "i2c", "limit": 5, "offset": 0})
    env = call(host, "bench_pins", action="modules")
    assert env["result"]["total"] == 2 and env["result"]["limit"] == tools.MODULES_LIMIT_DEFAULT
    assert [r["id"] for r in env["result"]["items"]] == ["zz_display", "zz_sensor"]  # category, then id
    assert "No module matches" in call(host, "bench_pins", action="modules", category="adc")["summary"]


@pytest.mark.parametrize("args", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"q": "x" * 65}, {"q": 7}])
def test_modules_search_rejects_bad_arguments(host, catalog, args):
    env = call(host, "bench_pins", action="modules", **args)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args" and env["action"] == "modules.list"


def test_module_info_is_compact_with_sources_and_hazards(host, catalog):
    env = call(host, "bench_pins", action="module", id="zz-breakout")
    assert env["ok"] and env["action"] == "modules.info"
    m = env["result"]["module"]
    assert m["id"] == "zz_sensor" and m["class"] == "A" and m["family"] == "test" and m["variant"] is None
    assert set(tools.MODULE_VIEW_KEYS) <= set(m) | {"aliases"}
    assert m["variants"] == [{"id": "b", "title": "Variant B"}]
    assert m["supplies"]["VDD"]["min"] == {"value": 1.71, "unit": "V", "source_id": sup.SRC}  # no evidence/page
    assert m["io"]["vih"] == {"rel": 0.7, "of": "VDD", "unit": "V"}
    assert m["interfaces"][0]["addresses"] == {"value": ["0x44", "0x45"]}
    assert "evidence" not in json.dumps(m)
    assert [s["id"] for s in env["sources"]] == [sup.SRC]  # unknown source ids are dropped, not fatal
    assert [(w["code"], w["severity"]) for w in env["warnings"]] == [("mod_hazard_heat", "caution")]
    env = call(host, "bench_pins", action="module", id="zz_sensor", variant="b")
    assert env["result"]["module"]["title"] == "ZZ synthetic I2C sensor (B)" and env["result"]["module"]["variant"] == "b"
    assert catalog.calls[-1] == ("get", {"id": "zz_sensor", "variant": "b"})


def test_module_info_errors(host, catalog):
    env = call(host, "bench_pins", action="module", id="nope")
    assert env["ok"] is False and env["error"]["code"] == "invalid_args" and "action=modules" in env["error"]["hint"]
    assert env["action"] == "modules.info"
    env = call(host, "bench_pins", action="module")
    assert env["error"]["code"] == "invalid_args" and "id is required" in env["error"]["message"]


def test_module_info_danger_hazards(host, monkeypatch):
    entry = {**sup.ENTRY, "id": "zz_charger", "aliases": [], "hazards": [{"code": "li_ion", "text": "Li-ion cell."}]}
    monkeypatch.setattr(modules, "catalog", lambda: sup.FakeCatalog([entry]))
    env = call(host, "bench_pins", action="module", id="zz_charger")
    assert [(w["code"], w["severity"]) for w in env["warnings"]] == [("mod_hazard_li_ion", "danger")]


def test_catalog_missing_in_this_build_is_rule_data_missing(host, monkeypatch):
    def broken():
        raise NotImplementedError
    monkeypatch.setattr(modules, "catalog", broken)
    for action in ("modules", "module"):
        env = call(host, "bench_pins", action=action, id="x")
        assert env["ok"] is False and env["error"]["code"] == "rule_data_missing"


# --------------------------------------------------------------------------------------------- bench_project

def test_module_ops_map_to_project_update_ops(host, monkeypatch, catalog, pin_calls):
    seen = sup.fake_module_update(project, monkeypatch)
    call(host, "bench_project", action="create", id="mod-p", chip="esp32s3",
         assignments=[{"role": "SDA", "mode": "i2c_sda", "pin": 8}, {"role": "SCL", "mode": "i2c_scl", "pin": 9}])
    env = call(host, "bench_project", action="add_module", id="mod-p", module="zz_sensor", variant="b", ref="U1",
               conn={"SDA": "GPIO8", "SCL": "GPIO9"}, address="0x44", facts={"regulator": "3V3"}, qty=1)
    assert env["ok"], env
    assert seen[-1] == [{"op": "add_module", "module": "zz_sensor", "variant": "b", "ref": "U1", "address": "0x44",
                         "conn": {"SDA": "GPIO8", "SCL": "GPIO9"}, "facts": {"regulator": "3V3"}, "qty": 1}]
    mods = env["result"]["modules"]
    assert mods == [{"ref": "U1", "kind": "module", "value": "zz_sensor", "module": "zz_sensor", "variant": "b",
                     "address": "0x44", "conn": {"SDA": "GPIO8", "SCL": "GPIO9"}, "facts": {"regulator": "3V3"}}]
    # the pin checks of the answer get the project's parts and options (module checks)
    assert pin_calls[-1]["parts"][-1]["module"] == "zz_sensor" and "options" in pin_calls[-1]
    assert env["result"]["all_roles"] == ["SDA", "SCL"]

    env = call(host, "bench_project", action="connect", id="mod-p", ref="U1", conn={"VDD": "3V3", "GND": "GND"})
    assert seen[-1] == [{"op": "connect", "ref": "U1", "conn": {"VDD": "3V3", "GND": "GND"}}]
    assert env["result"]["modules"][0]["conn"] == {"SDA": "GPIO8", "SCL": "GPIO9", "VDD": "3V3", "GND": "GND"}

    env = call(host, "bench_project", action="set_rails", id="mod-p", rails={"VMOT": 12}, rail_limits={"VMOT": 2})
    assert seen[-1] == [{"op": "set_rails", "rails": {"VMOT": 12}, "rail_limits": {"VMOT": 2}}]
    assert env["result"]["options"]["rails"] == {"VMOT": 12}
    assert pin_calls[-1]["options"]["rails"] == {"VMOT": 12}

    view = call(host, "bench_project", action="get", id="mod-p")["result"]["project"]
    assert view["parts"] == [mods[0] | {"conn": {"SDA": "GPIO8", "SCL": "GPIO9", "VDD": "3V3", "GND": "GND"}}]


@pytest.mark.parametrize(("args", "needle"), [
    ({"action": "add_module"}, "module"),
    ({"action": "add_module", "module": "zz_sensor", "conn": ["SDA"]}, "conn must be an object"),
    ({"action": "add_module", "module": "zz_sensor", "qty": "two"}, "qty"),
    ({"action": "connect", "ref": "U1"}, "conn"),
    ({"action": "connect", "conn": {"SDA": "GPIO8"}}, "ref"),
    ({"action": "set_rails"}, "rails"),
    ({"action": "set_rails", "rails": 5}, "rails must be an object"),
])
def test_module_op_argument_errors(host, monkeypatch, args, needle):
    seen = sup.fake_module_update(project, monkeypatch)
    env = call(host, "bench_project", id="mod-p", **args)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args" and needle in env["error"]["message"]
    assert seen == []


def test_project_view_shortens_long_conn():
    conn = {f"P{i}": f"N{i}" for i in range(20)}
    v = tools._part_view({"ref": "U1", "kind": "module", "value": "x", "module": "m", "conn": conn, "facts": {}})
    assert len(v["conn"]) == tools.CONN_VIEW_MAX + 1 and v["conn"]["…"] == 20 - tools.CONN_VIEW_MAX
    assert "facts" not in v and "variant" not in v
    assert tools._part_view({"ref": "R1", "kind": "resistor", "value": "1k"}) == {"ref": "R1", "kind": "resistor",
                                                                                   "value": "1k"}


# --------------------------------------------------------------------------------------------- bench_pins check

def test_pins_check_with_a_project_passes_parts_and_options(host, pin_calls):
    call(host, "bench_project", action="create", id="chk-p", chip="esp32s3",
         assignments=[{"role": "LED", "mode": "out", "pin": 4}])
    call(host, "bench_project", action="add_parts", id="chk-p", parts=[{"ref": "R1", "kind": "resistor", "value": "1k"}])
    pin_calls.clear()
    env = call(host, "bench_pins", action="check", project="chk-p")
    assert env["ok"]
    assert pin_calls[-1]["parts"][0]["ref"] == "R1" and isinstance(pin_calls[-1]["options"], dict)
    pin_calls.clear()
    call(host, "bench_pins", action="check", chip="esp32s3", assignments=[{"role": "LED", "mode": "out", "pin": 4}])
    assert "parts" not in pin_calls[-1]  # no project: no module checks
