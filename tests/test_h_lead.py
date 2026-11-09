"""Seams between board, serial, rules and UI hardening (cross-module checks)."""
import json

import pytest

from circuit_bench import tools
from circuit_bench.bench_core import project as P


@pytest.fixture
def handlers():
    return tools.make_handlers(tools.Host(hook_active=True))


def _call(handlers, tool, args):
    return json.loads(handlers[tool](args))


def _project(handlers, pid, chip, variant):
    env = _call(handlers, "bench_project", {"action": "create", "id": pid, "title": pid, "chip": chip, "variant": variant})
    assert env["ok"], env


def _last_inputs(handlers, pid):
    inputs = P.get(pid)["result"]["project"]["calcs"][-1]["inputs"]  # the tool's get is a short view
    return json.loads(inputs) if isinstance(inputs, str) else inputs


def _src_ids(env):
    return [s["id"] for s in env["sources"]]


def test_calc_with_a_project_takes_the_project_chip(handlers):
    _project(handlers, "c3-calc", "esp32c3", None)
    env = _call(handlers, "bench_calc", {"action": "mosfet", "project": "c3-calc",
                                         "inputs": {"i_load": "1A", "v_supply": "12V", "part": "AO3400A"}})
    assert env["ok"], env
    plain = _call(handlers, "bench_calc", {"action": "mosfet",
                                           "inputs": {"i_load": "1A", "v_supply": "12V", "part": "AO3400A"}})
    s3 = _call(handlers, "bench_calc", {"action": "mosfet",
                                        "inputs": {"i_load": "1A", "v_supply": "12V", "part": "AO3400A", "chip": "esp32s3"}})
    assert set(_src_ids(env)) != set(_src_ids(s3)), "the C3 project must not cite the S3 datasheet"
    assert set(_src_ids(plain)) == set(_src_ids(s3))
    assert _last_inputs(handlers, "c3-calc")["chip"] == "esp32c3"


def test_explicit_chip_wins_over_the_project(handlers):
    _project(handlers, "c3-calc2", "esp32c3", None)
    env = _call(handlers, "bench_calc", {"action": "ldo", "project": "c3-calc2",
                                         "inputs": {"v_in": 5, "v_out": 3.3, "i_load": 0.5, "part": "AMS1117-3.3",
                                                    "chip": "esp32s3"}})
    assert env["ok"], env
    assert _last_inputs(handlers, "c3-calc2")["chip"] == "esp32s3"


def test_calc_without_chip_parameter_ignores_the_project_chip(handlers):
    _project(handlers, "c3-led", "esp32c3", None)
    env = _call(handlers, "bench_calc", {"action": "led", "project": "c3-led",
                                         "inputs": {"v_supply": "3V3", "v_f": 2.0, "i_f": "10mA"}})
    assert env["ok"], env
    assert "chip" not in _last_inputs(handlers, "c3-led")


def test_calc_with_unknown_project_is_project_not_found(handlers):
    env = _call(handlers, "bench_calc", {"action": "led", "project": "nope",
                                         "inputs": {"v_supply": "3V3", "v_f": 2.0, "i_f": "10mA"}})
    assert env["ok"] is False and env["error"]["code"] == "project_not_found"
