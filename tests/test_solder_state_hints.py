"""The agent learns when a project's solder plan is missing or outdated: bench_project get/add_parts/remove_parts
(and add_module/connect when parts change) add one summary sentence (solder.plan_state, the same rule as the
desktop's solderStale). The routes keep the bench_core summary."""
from __future__ import annotations

import copy
import json
import sys
import types
from pathlib import Path

import pytest
from test_api_support import *  # noqa: F403 - the api fixture (routes through httpx.ASGITransport)

from circuit_bench import tools
from circuit_bench.bench_core import contracts, project, solder

ROOT = Path(__file__).resolve().parents[1]
PID = "state-p"


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
    return env


def _create(pid: str = PID) -> None:
    assert call("bench_project", action="create", id=pid, title="State", chip="esp32s3", variant="n16r8")["ok"]


def _add(pid: str, *parts: tuple[str, str, str]) -> dict:
    env = call("bench_project", action="add_parts", id=pid,
               parts=[{"ref": r, "kind": k, "value": v} for r, k, v in parts])
    assert env["ok"], env.get("error")
    return env


def test_no_plan_yet_is_named_with_the_part_count():
    _create()
    env = _add(PID, ("R1", "resistor", "1k"), ("D1", "led", "red"))
    tail = f"Solder plan: none yet for 2 parts; run bench_solder plan with project {PID}."
    assert env["summary"].endswith(" " + tail)
    got = call("bench_project", action="get", id=PID)
    assert got["summary"].endswith(" " + tail)
    assert got["summary"] == f"{project.get(PID)['summary']} {tail}"


def test_parts_added_after_planning_make_the_plan_outdated():
    _create()
    _add(PID, ("R1", "resistor", "1k"), ("D1", "led", "red"))
    assert call("bench_solder", action="plan", project=PID)["ok"]
    env = _add(PID, ("C1", "ceramic", "100nF"))
    tail = f"Solder plan outdated (not in it: C1); run bench_solder plan with project {PID} again."
    assert env["summary"].endswith(" " + tail)
    assert call("bench_project", action="get", id=PID)["summary"].endswith(" " + tail)


def test_removed_planned_parts_and_both_kinds_of_change():
    _create()
    _add(PID, ("R1", "resistor", "1k"), ("R2", "resistor", "1k"), ("R3", "resistor", "1k"), ("D9", "led", "red"),
         ("Q1", "transistor", "2N2222A"))
    assert call("bench_solder", action="plan", project=PID)["ok"]
    env = call("bench_project", action="remove_parts", id=PID, refs=["D9"])
    assert env["ok"] and env["summary"].endswith(
        f" Solder plan outdated (removed: D9); run bench_solder plan with project {PID} again.")
    env = call("bench_project", action="remove_parts", id=PID, refs=["R1", "R2", "R3"])
    assert env["summary"].endswith(
        f" Solder plan outdated (removed: D9, R1-R3); run bench_solder plan with project {PID} again.")
    _add(PID, ("C1", "ceramic", "100nF"), ("C2", "ceramic", "100nF"))
    assert call("bench_project", action="get", id=PID)["summary"].endswith(
        f" Solder plan outdated (not in it: C1, C2; removed: D9, R1-R3); run bench_solder plan with project {PID} again.")


def test_a_current_plan_and_a_project_without_parts_add_nothing():
    _create()
    assert call("bench_project", action="get", id=PID)["summary"] == project.get(PID)["summary"]
    _add(PID, ("R1", "resistor", "1k"))
    assert call("bench_solder", action="plan", project=PID)["ok"]
    assert call("bench_project", action="get", id=PID)["summary"] == project.get(PID)["summary"]
    assert "Solder plan" not in _add(PID, ("R1", "resistor", "2k2"))["summary"]  # same ref: still covered


def test_add_module_reports_the_missing_plan():
    _create()
    env = call("bench_project", action="add_module", id=PID, module="rfm95w")
    assert env["ok"] and env["summary"].endswith(
        f" Solder plan: none yet for 1 part; run bench_solder plan with project {PID}.")


def test_the_route_keeps_the_bench_core_summary(api):
    _create()
    _add(PID, ("R1", "resistor", "1k"), ("D1", "led", "red"))
    body = api.ok(api.get(f"/projects/{PID}"))
    assert body["summary"] == project.get(PID)["summary"]
    assert "Solder plan" not in body["summary"]


# the cases of the desktop's solderStale (desktop-src/lib/stages.js), on the same demo fixture

def _fixture_project() -> dict:
    fx = json.loads((ROOT / "desktop-src" / "fixtures" / "project.laser-trigger.json").read_text(encoding="utf-8"))
    return fx["result"]["project"]


def test_plan_state_judges_like_the_desktop():
    proj = _fixture_project()
    assert solder.plan_state(proj) == {"state": "current", "missing": [], "gone": []}
    p = copy.deepcopy(proj)
    p["parts"] += [{"ref": "R5", "kind": "resistor", "value": "82 Ω", "from_calc": "led-1"},
                   {"ref": "LED1", "kind": "led", "value": "LED", "from_calc": "led-1"}]
    st = solder.plan_state(p)
    assert st["state"] == "stale" and st["missing"] == ["R5", "LED1"] and st["gone"] == []
    gone = copy.deepcopy(proj)
    gone["parts"] = [x for x in gone["parts"] if x["ref"] != "SW1"]
    assert solder.plan_state(gone) == {"state": "stale", "missing": [], "gone": ["SW1"]}
    empty = {**proj, "solder": {"steps": [], "done": []}}
    assert solder.plan_state(empty)["state"] == "none"  # the desktop: not stale (nothing to be outdated)
    assert solder.plan_state({**proj, "parts": []})["state"] == "no_parts"
    assert solder.plan_state({})["state"] == "no_parts"
