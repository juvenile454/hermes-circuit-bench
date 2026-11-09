"""Follow-ups across modules: the schematic net comes from the assignment through the tool and the route,
and the build answer for the model carries no top-level ``*_total`` keys (Hermes Desktop shows them as counters)."""
import json
import sys
import types

import pytest

from circuit_bench import tools
from circuit_bench.bench_core import contracts, project, runtime, sim

pytest.importorskip("schemdraw")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = dict
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    monkeypatch.setattr(sim, "TIME_SCALE", 0.0)
    yield
    b = runtime.peek("broker")
    if b is not None:
        b.shutdown()


def call(name, **args):
    out = tools.make_handlers(tools.Host(hook_active=False))[name](args)
    env = json.loads(out)
    assert contracts.validate_envelope(env) == [], env
    return env


def test_schematic_tool_takes_the_net_of_the_assignment_and_stores_it():
    assert call("bench_project", action="demo")["ok"]
    env = call("bench_schematic", action="render", block="npn_low_side", project="laser-trigger", role="LASER",
               params={"r_base": "1k", "r_pulldown": "10k"})
    assert env["ok"], env
    assert "LASER_EN" in env["summary"] and "IO14" in env["summary"]
    stored = [c for c in project.get("laser-trigger")["result"]["project"]["circuits"] if c["id"].endswith("gpio14")]
    assert stored and stored[-1]["params"]["net"] == "LASER_EN"


def test_build_answer_has_size_objects_instead_of_total_keys():
    assert call("bench_project", action="demo")["ok"]
    env = call("bench_board", action="build", project="laser-trigger")
    assert env["ok"], env
    res = env["result"]
    assert not [k for k in res if k.endswith("_total")], sorted(res)
    assert set(res["ram"]) == {"used", "total"} and set(res["flash"]) == {"used", "total"}
    assert project.get("laser-trigger")["result"]["project"]["firmware"]["last_build"]["ok"] is True


def test_sizes_as_objects_leaves_other_results_alone():
    env = {"ok": True, "result": {"ok": True, "ram_used": 1, "ram_total": 2, "env": "s3"}}
    assert tools._sizes_as_objects(env)["result"] == {"ok": True, "env": "s3", "ram": {"used": 1, "total": 2}}
    assert tools._sizes_as_objects({"ok": False, "result": None}) == {"ok": False, "result": None}
