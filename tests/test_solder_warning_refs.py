"""Solder plan warnings name each part once: a hint that already starts with its parts gets no second ref prefix,
in the plan warnings, in the "danger at" summary and in the step warnings (solder.step on the stored plan)."""
from __future__ import annotations

import json
import re

import pytest

from circuit_bench.bench_core import bom, solder

LASER_ROWS = [
    {"ref": "R1", "kind": "resistor", "value": "1k"},
    {"ref": "R2", "kind": "resistor", "value": "10k"},
    {"ref": "Q1", "kind": "transistor", "value": "2N2222A"},
    {"ref": "S1", "kind": "switch", "value": "trigger push button"},
    {"ref": "S2", "kind": "switch", "value": "laser power switch"},
    {"ref": "J2", "kind": "connector", "value": "5 V line laser CHT1230"},
]
STRIP_ROWS = [
    {"ref": "D1", "kind": "module", "value": "WS2812B strip", "module": "ws2812b", "qty": 30,
     "conn": {"DIN": "LED", "VDD": "5V", "GND": "GND"}},
    {"ref": "R1", "kind": "resistor", "value": "330"},
]
CAP_ROWS = [
    STRIP_ROWS[0],
    {"ref": "C1", "kind": "capacitor", "value": "100n"},
    {"ref": "C2", "kind": "capacitor", "value": "100n ceramic 0805"},
    {"ref": "U1", "kind": "ic", "value": "ATmega328P"},
]
MODULE_ROWS = [
    {"ref": "R1", "kind": "resistor", "value": "10k"},
    {"ref": "U2", "kind": "module", "value": "RFM95W", "module": "rfm95w"},
    {"ref": "U3", "kind": "module", "value": "TP4056", "module": "tp4056"},
    {"ref": "U4", "kind": "module", "value": "TP4056", "module": "tp4056"},
    {"ref": "U5", "kind": "module", "value": "TP4056", "module": "tp4056"},
]
SAME_REF_TWICE = re.compile(r"^(\S+): \1:")
DOUBLED = re.compile(r"^[^:]*\b[A-Z]{1,3}\d+\b[^:]*: [A-Z]{1,3}\d+\b")  # "C1, C2: C1: ..." or "J2: J2: ..."


def _laser_text() -> str:
    rule = next(r for r in bom.rules()["text_rules"] if r["code"] == "laser_safety")
    assert rule["text"].startswith("{refs}: ")
    return rule["text"][len("{refs}: "):]


def test_laser_warnings_name_only_the_part_that_matched():
    env = solder.plan(LASER_ROWS)
    assert env["ok"], env.get("error")
    laser = [w["message"] for w in env["warnings"] if w["code"] == "laser_safety"]
    assert laser == [f"S2: {_laser_text()}", f"J2: {_laser_text()}"]
    assert not any(re.search(r"\bS1\b", w["message"]) for w in env["warnings"])
    assert "danger at S2, J2" in env["summary"]
    assert "S1" not in env["summary"].split("danger at", 1)[1]


def test_the_private_refs_never_leave_the_plan():
    for rows in (LASER_ROWS, STRIP_ROWS, CAP_ROWS, MODULE_ROWS):
        env = solder.plan(rows)
        assert "_refs" not in json.dumps(env, ensure_ascii=False)
        assert all(set(h) == {"code", "severity", "text", "source_ids"}
                   for s in env["result"]["steps"] for h in s["hints"])


def _walk(rows) -> list[str]:
    """The step warnings of every step of the plan (as the project stores it): ticking the steps in turn, and each
    step once as the next one (the steps before it done, the step itself unticked)."""
    env = solder.plan(rows)
    steps = json.loads(json.dumps(env["result"]["steps"]))
    ids = [s["id"] for s in steps]
    messages = []
    plan = {"steps": steps, "done": []}
    for sid in ids:
        out = solder.step(plan, sid, True)
        assert out["ok"], out.get("error")
        plan["done"] = out["result"]["done"]
        messages += [w["message"] for w in out["warnings"]]
    for i, sid in enumerate(ids):
        out = solder.step({"steps": steps, "done": ids[:i]}, sid, False)
        assert out["ok"] and out["result"]["next_step"]["id"] == sid
        messages += [w["message"] for w in out["warnings"]]
    return messages


@pytest.mark.parametrize("rows", [LASER_ROWS, STRIP_ROWS, CAP_ROWS, MODULE_ROWS],
                         ids=["laser", "strip", "capacitors", "modules"])
def test_step_warnings_carry_one_ref_prefix(rows):
    messages = _walk(rows)
    assert messages
    assert [m for m in messages if SAME_REF_TWICE.match(m)] == []
    assert [m for m in messages if DOUBLED.match(m)] == []


def test_step_warnings_keep_the_refs_the_hint_names():
    laser = _walk(LASER_ROWS)
    assert f"S2: {_laser_text()}" in laser and f"J2: {_laser_text()}" in laser
    strip = _walk(STRIP_ROWS)
    assert any(m.startswith("D1: solder the wires at the input end") for m in strip)
    caps = _walk(CAP_ROWS)
    guessed = [m for m in caps if "type guessed from the value only" in m]
    assert guessed and all(m.startswith("C1: type guessed") for m in guessed)


def test_hints_without_own_refs_still_get_the_step_refs():
    env = solder.plan(MODULE_ROWS)
    shorts = next(h for s in env["result"]["steps"] for h in s["hints"] if h["code"] == "check_shorts")
    steps = env["result"]["steps"]
    assert [s["kind"] for s in steps] == ["resistor", "module"]
    out = solder.step({"steps": steps, "done": []}, steps[0]["id"], True)  # the module step is next
    msgs = [w["message"] for w in out["warnings"] if w["code"] == "check_shorts"]
    assert msgs == [f"U2-U5: {shorts['text']}"]


def test_has_ref_prefix():
    assert solder._has_ref_prefix("J2: laser.", ["J2"])
    assert solder._has_ref_prefix("C1, C2: type guessed", ["C1", "C2"])
    assert solder._has_ref_prefix("U3 (a4988): from the module catalog", ["U3"])
    assert solder._has_ref_prefix("U3-U5: Plug the module", ["U3", "U4", "U5"])
    assert solder._has_ref_prefix("U3–U5: Plug the module", ["U3", "U4", "U5"])
    assert not solder._has_ref_prefix("Polarised: the band marks the cathode", ["D1"])
    assert not solder._has_ref_prefix("R10: x", ["R1"])
    assert not solder._has_ref_prefix("J2 is a laser", ["J2"])
