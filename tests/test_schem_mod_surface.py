"""bench_schematic and POST /schematic with ``part`` (a module part of
a project: module, conn, address, facts; the project's devkit, options.rails and assignment nets), ``params.gpios``
and the derived block vocabulary of the tool schema.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import test_api_support as sup
from test_api_support import *  # noqa: F403
from test_schem_mod_module import S3, net_of, svg_ok, texts

from circuit_bench import schemas, tools
from circuit_bench.bench_core import contracts, project, schematic

pytest.importorskip("schemdraw")


@pytest.fixture
def host():
    return tools.Host(hook_active=True)


def call(host, name, **args):
    out = tools.make_handlers(host)[name](args)
    env = json.loads(out)
    assert contracts.validate_envelope(env) == [], env
    assert len(out.encode()) <= tools.MAX_BYTES
    return env


def _bme_project(host, pid="env-node"):
    env = call(host, "bench_project", action="create", id=pid, title="Env node", chip="esp32s3", variant="n16r8",
               devkit=S3, assignments=[{"role": "SDA", "mode": "i2c_sda", "pin": 8},
                                       {"role": "SCL", "mode": "i2c_scl", "pin": 9}])
    assert env["ok"], env
    env = call(host, "bench_project", action="add_module", id=pid, module="bme280", ref="U1",
               conn={"SDI": "GPIO8", "SCK": "GPIO9", "SDO": "VDDIO"})
    assert env["ok"], env
    env = call(host, "bench_project", action="set_rails", id=pid, rails={"VBAT": 3.7})
    assert env["ok"], env


def test_schema_block_enum_is_derived_and_names_part():
    props = schemas.SCHEMATIC["parameters"]["properties"]
    assert props["block"]["enum"] == list(schematic.BLOCKS) == [
        "led", "npn_low_side", "button_pullup", "divider", "module", "level_shifter"]
    assert props["part"] == {"type": "string"}
    text = schemas.SCHEMATIC["description"]
    for word in ("module", "level_shifter", "params.gpios", "part"):
        assert word in text


def test_tool_draws_a_project_part_and_stores_the_circuit(host):
    _bme_project(host)
    env = call(host, "bench_schematic", action="render", project="env-node", part="U1")
    assert env["ok"], env
    res = env["result"]
    assert "svg" not in res and res["project_update"]["circuit_id"] == "module-u1"
    svg = Path(res["svg_path"]).read_text(encoding="utf-8")
    assert svg == (project.artifacts_dir("env-node") / "module-u1.svg").read_text(encoding="utf-8")
    nets = {n["name"]: set(n["nodes"]) for n in res["nets"]}
    # conn GPIO8/GPIO9 -> the board pins; SDO to VDDIO (0x77) per conn, so it sits on the 3V3 net
    assert {"J1-12", "U1.SDI"} <= nets[next(k for k, v in nets.items() if "U1.SDI" in v)]
    assert "U1.SDO" in nets["3V3"]
    assert {p["ref"] for p in res["parts"]} == {"U1", "R1", "R2", "C1", "C2"}
    circuits = project.get("env-node")["result"]["project"]["circuits"]
    assert circuits == [{"id": "module-u1", "block": "module", "params": {"part": "U1"},
                         "svg": "artifacts/module-u1.svg"}]
    # a redraw from the stored circuit gives the same drawing
    stored = project.get("env-node")["result"]["project"]
    again = schematic.render(circuits[0]["block"], circuits[0]["params"], project=stored)
    assert again["result"]["svg"] == svg


def test_tool_part_with_explicit_block_and_errors(host):
    _bme_project(host)
    env = call(host, "bench_schematic", action="render", block="module", project="env-node", part="u1")
    assert env["ok"] and env["result"]["project_update"]["circuit_id"] == "module-u1"
    assert call(host, "bench_schematic", action="render", project="env-node", part="U9")["error"]["code"] == \
        "invalid_args"
    assert call(host, "bench_schematic", action="render", part="U1")["error"]["code"] == "invalid_args"
    env = call(host, "bench_schematic", action="render", block="led", params={"r_series": 150}, part="U1",
               project="env-node")
    assert env["ok"] is False and "only for block module" in env["error"]["message"]


def test_tool_module_with_gpios_and_level_shifter(host, monkeypatch):
    from circuit_bench.bench_core import sources
    base = sources.all_sources()
    base.setdefault(schematic.LEVEL_SOURCE, {"id": schematic.LEVEL_SOURCE, "title": "AN10441 (test)",
                                             "url": "https://example.invalid", "retrieved": "2026-11-08"})
    monkeypatch.setattr(sources, "_load", lambda: base)
    env = call(host, "bench_schematic", action="render", block="module",
               params={"module": "bme280", "gpios": {"SDA": 4, "SCL": 5}}, devkit=S3)
    assert env["ok"] and Path(env["result"]["svg_path"]).name.startswith("schematic-module-bme280-gpio4")
    env = call(host, "bench_schematic", action="render", block="level_shifter", params={"gpios": {"SDA": 8}},
               devkit=S3)
    assert env["ok"] and "level_shifter-gpio8" in Path(env["result"]["svg_path"]).name


def test_route_with_part_from_the_project(api):
    api.create("bench-m")
    api.apply("bench-m", {"op": "set_board", "devkit": S3},
              {"op": "add_module", "module": "bme280", "ref": "U1", "conn": {"SDI": "GPIO8", "SCK": "GPIO9"}},
              {"op": "set_rails", "rails": {"VMOT": 12}})
    env = api.ok(api.post("/schematic", {"project": "bench-m", "part": "U1"}))
    svg_ok(env)
    assert env["result"]["block"] == "module" and net_of(env, "U1.SDI") == net_of(env, "J1-12")
    same = api.ok(api.post("/schematic", {"block": "module", "project": "bench-m", "params": {"part": "U1"}}))
    assert same["result"]["svg"] == env["result"]["svg"]
    env = api.ok(api.post("/schematic", {"block": "module", "params": {"module": "bme280",
                                                                        "gpios": {"SDA": 8, "SCL": 9}},
                                         "devkit": S3}))
    assert "J1-12 · IO8" in texts(env)
    api.err(api.post("/schematic", {"project": "bench-m", "part": "U7"}), 400, "invalid_args")
    api.err(api.post("/schematic", {"block": "module", "part": "U1"}), 400, "invalid_args")


def test_route_keeps_its_old_errors(api):
    api.err(api.post("/schematic", {"params": {}}), 400, "invalid_args")
    body = api.err(api.post("/schematic", {"params": {}}), 400, "invalid_args")
    assert "module" in body["error"]["hint"] and "level_shifter" in body["error"]["hint"]
    assert sup is not None
