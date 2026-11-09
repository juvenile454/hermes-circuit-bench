"""Findings of a probe with a real model, fixed in the tool layer (add_parts kinds, assign checks, overlap-free
suggestions, electrolytic rated voltage, decode hint)."""
from __future__ import annotations

import json
import sys
import types

import pytest

from circuit_bench import schemas, tools
from circuit_bench.bench_core import bom, contracts, pins, runtime, solder


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = lambda: {"approvals": {"mode": "manual"}}
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    yield
    b = runtime.peek("broker")
    if b is not None:
        b.shutdown()


@pytest.fixture
def host():
    return tools.Host(hook_active=True)


def call(host, name, **args):
    out = tools.make_handlers(host)[name](args)
    env = json.loads(out)
    assert contracts.validate_envelope(env) == [], env
    assert len(out.encode("utf-8")) <= tools.MAX_BYTES
    return env


def _project(host, pid="af-p", **extra):
    env = call(host, "bench_project", action="create", id=pid, title="P", chip="esp32s3", variant="n16r8",
               devkit="esp32-s3-devkitc-1", **extra)
    assert env["ok"], env
    return pid


# --- 5 add_parts -------------------------------------------------------------------------------------------------
def test_part_kind_is_an_enum_from_the_solder_rules():
    kind = schemas.PROJECT["parameters"]["properties"]["parts"]["items"]["properties"]["kind"]
    assert kind["enum"] == bom.kinds()


def test_add_parts_error_has_no_internal_ops_prefix(host):
    pid = _project(host)
    env = call(host, "bench_project", action="add_parts", id=pid, parts=[{"ref": "R1", "kind": "resistr", "value": "1k"}])
    assert env["ok"] is False and env["error"]["code"] == "invalid_args"
    assert not env["error"]["message"].startswith("ops[")
    assert env["error"]["message"].startswith("parts[0].kind: unknown part kind")


def test_assign_error_names_the_assignment_not_the_op(host):
    pid = _project(host)
    env = call(host, "bench_project", action="assign", id=pid,
               assignments=[{"role": "LED", "mode": "out", "pin": 4}, {"role": "BTN", "mode": "nope", "pin": 5}])
    assert env["ok"] is False
    assert env["error"]["message"].startswith("assignments[1]"), env["error"]
    assert "ops[" not in env["error"]["message"] and "assign." not in env["error"]["message"]


# --- 6 assign checks ---------------------------------------------------------------------------------------------
def test_assign_returns_the_pin_checks_of_all_assignments(host):
    pid = _project(host)
    first = call(host, "bench_project", action="assign", id=pid, assignments=[{"role": "LED", "mode": "out", "pin": 4}])
    assert first["ok"] and first["checks"]
    env = call(host, "bench_project", action="assign", id=pid, assignments=[{"role": "BTN", "mode": "in_pullup", "pin": 4}])
    assert env["ok"]
    ids = {c["id"]: c for c in env["checks"]}
    expected = pins.check("esp32s3", [{"role": "LED", "mode": "out", "pin": 4}, {"role": "BTN", "mode": "in_pullup", "pin": 4}],
                          variant="n16r8", wifi=True, devkit="esp32-s3-devkitc-1")
    assert [c["id"] for c in env["checks"]] == [c["id"] for c in expected["checks"]]
    assert ids["pins.duplicates"]["status"] == "failed"  # LED and BTN share GPIO4: checked over all assignments
    assert env["result"]["all_roles"] == ["LED", "BTN"]


def test_create_with_assignments_returns_pin_checks(host):
    env = call(host, "bench_project", action="create", id="af-c", title="C", chip="esp32s3", variant="n16r8",
               assignments=[{"role": "LED", "mode": "out", "pin": 35}])
    assert env["ok"]
    assert {c["id"]: c["status"] for c in env["checks"]}["pins.exists"] == "passed"
    assert any(c["status"] == "failed" for c in env["checks"])  # GPIO35: octal PSRAM on the N16R8


# --- 7 suggest without overlap -----------------------------------------------------------------------------------
def test_suggest_allocates_distinct_pins_for_several_requests():
    req = [{"role": "LED", "mode": "out"}, {"role": "BUZZER", "mode": "out"}, {"role": "BTN", "mode": "in_pullup"}]
    env = pins.suggest("esp32s3", req, variant="n16r8", wifi=True, devkit="esp32-s3-devkitc-1")
    assert env["ok"]
    alloc = env["result"]["allocation"]
    assert [a["role"] for a in alloc] == ["LED", "BUZZER", "BTN"]
    gpios = [a["gpio"] for a in alloc]
    assert None not in gpios and len(set(gpios)) == 3
    for a, r in zip(alloc, env["result"]["requests"], strict=True):
        assert a["gpio"] in [s["gpio"] for s in r["suggestions"]] or a["beyond_suggestions"]
    assert {c["id"]: c["status"] for c in env["checks"]}["suggest.distinct"] == "passed"
    assert "without overlap" in env["summary"]
    assert env == pins.suggest("esp32s3", req, variant="n16r8", wifi=True, devkit="esp32-s3-devkitc-1")


def test_suggest_allocation_finds_a_matching_greedy_would_miss(monkeypatch):
    """Request 1 could use A or B, request 2 only A: a matching gives 1 -> B, 2 -> A."""
    pool = {"out": [10, 11], "adc": [10]}
    monkeypatch.setattr(pins, "_all_candidates", lambda ctx, mode, taken, requested: list(pool[mode]))
    out = pins._allocate(None, [{"role": "A", "mode": "out", "requested": None},
                                {"role": "B", "mode": "adc", "requested": None}], set())
    assert [a["gpio"] for a in out] == [11, 10]


def test_single_request_answer_is_unchanged():
    env = pins.suggest("esp32s3", [{"role": "BUTTON", "mode": "in_pullup", "pin": 35}], variant="n16r8", wifi=False,
                       devkit="esp32-s3-devkitc-1")
    assert "allocation" not in env["result"]
    assert "suggest.distinct" not in {c["id"] for c in env["checks"]}


# --- 8 electrolytic rated voltage ---------------------------------------------------------------------------------
def test_solder_plan_notes_the_rated_voltage_of_electrolytics():
    env = solder.plan("R1 1k\nC1 100uF electrolytic\nC2 100nF ceramic")
    a = {x["key"]: x for x in env["assumptions"]}["rated_voltage"]
    assert a["value"].startswith("C1:") and "rule of thumb" in a["reason"] and "over-voltage" in a["reason"]
    assert not any(ch.isdigit() for ch in a["value"].removeprefix("C1:"))  # no number without a source
    without = solder.plan("R1 1k\nC2 100nF ceramic")
    assert "rated_voltage" not in {x["key"] for x in without["assumptions"]}


# --- 9 decode without a log ----------------------------------------------------------------------------------------
def test_decode_without_log_says_where_the_log_comes_from(host):
    env = call(host, "bench_crash", action="decode")
    assert env["ok"] is False and env["error"]["code"] == "invalid_args"
    hint = env["error"]["hint"] or ""
    assert "bench_board monitor" in hint and "log_ref" in hint and "log" in hint
