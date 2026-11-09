"""The solder plan from a project's parts: the desktop route and the agent tool build the same BOM rows
(solder.rows_from_parts), so a catalog module keeps its variant and its nets (an LED strip gets its wires)."""
from __future__ import annotations

import json
import sys
import types

import pytest
from test_api_support import *  # noqa: F403 - the api fixture (routes through httpx.ASGITransport)

from circuit_bench import tools
from circuit_bench.bench_core import contracts, project, solder

STRIP_CONN = {"VDD": "V5_LED", "VSS": "GND", "DIN": "LED_DATA_5V"}


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = lambda: {"approvals": {"mode": "manual"}}
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)


def call(name, **args):
    out = tools.make_handlers(tools.Host(hook_active=True))[name](args)
    env = json.loads(out)
    assert contracts.validate_envelope(env) == [], env
    assert len(out.encode("utf-8")) <= tools.MAX_BYTES
    return env


def test_rows_carry_exactly_the_bom_keys():
    parts = [{"ref": "U1", "kind": "ic", "value": "WS2812B", "qty": 30, "module": "ws2812b", "variant": None,
              "conn": STRIP_CONN, "address": "0x40", "facts": {"vdd": 5}, "from_calc": "led-1", "package": None},
             {"ref": "R1", "kind": "resistor", "value": "330", "package": "0805"}]
    assert solder.rows_from_parts(parts) == [
        {"ref": "U1", "kind": "ic", "value": "WS2812B", "qty": 30, "module": "ws2812b", "conn": STRIP_CONN},
        {"ref": "R1", "kind": "resistor", "value": "330", "package": "0805"}]
    assert solder.rows_from_parts([]) == [] and solder.rows_from_parts(None) == []
    assert solder.ROW_KEYS == ("ref", "kind", "value", "package", "qty", "module", "variant", "conn")


def _module_project(pid: str) -> None:
    assert call("bench_project", action="create", id=pid, title=pid, chip="esp32s3", variant="n16r8")["ok"]
    assert call("bench_project", action="add_module", id=pid, module="ws2812b", qty=30, conn=STRIP_CONN)["ok"]
    assert call("bench_project", action="add_module", id=pid, module="rfm95w")["ok"]
    assert call("bench_project", action="add_module", id=pid, module="a4988")["ok"]
    kinds = {x["module"]: x["kind"] for x in project.get(pid)["result"]["project"]["parts"]}
    assert kinds == {"ws2812b": "ic", "rfm95w": "module", "a4988": "ic"}


def test_route_and_tool_plan_the_same_steps_from_the_project(api):
    _module_project("rows-a")
    tool = call("bench_solder", action="plan", project="rows-a")
    assert tool["ok"], tool.get("error")
    stored = project.get("rows-a")["result"]["project"]["solder"]["steps"]
    route = api.ok(api.post("/solder/plan", {"project": "rows-a"}))
    assert route["result"]["steps"] == stored
    assert [(s["id"], s["kind"], s["refs"], s["action"]) for s in tool["result"]["steps"]] == \
           [(s["id"], s["kind"], s["refs"], s["action"]) for s in route["result"]["steps"]]


def test_the_strip_step_names_its_nets_and_no_female_headers(api):
    _module_project("rows-b")
    route = api.ok(api.post("/solder/plan", {"project": "rows-b"}))
    tool = call("bench_solder", action="plan", project="rows-b")
    strip_ref = next(x["ref"] for x in project.get("rows-b")["result"]["project"]["parts"] if x["module"] == "ws2812b")
    for steps in (route["result"]["steps"], tool["result"]["steps"]):
        strip = next(s for s in steps if s["refs"] == [strip_ref])
        assert "VDD to V5_LED, VSS to GND, DIN to LED_DATA_5V" in strip["action"]
        assert "female headers" not in json.dumps(strip, ensure_ascii=False)
    ic = next(s for s in route["result"]["steps"] if s["kind"] == "ic")
    assert any(h["code"] == "catalog_module" for h in ic["hints"])
    tool_ic = next(s for s in tool["result"]["steps"] if s["kind"] == "ic")
    assert any("from the module catalog" in h for h in tool_ic["hints"])
