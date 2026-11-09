"""Solder plan and progress (bench_core/solder.py)."""
import hashlib
import json

import pytest

from circuit_bench.bench_core import solder
from circuit_bench.bench_core.contracts import MAX_RESULT_BYTES, validate_envelope
from test_solder_bom import KICAD_SEMICOLON, SPIKE_LIST

SPIKE_ORDER = ["wire_jumper", "resistor", "ceramic", "transistor", "led", "electrolytic", "header", "terminal", "module"]


def _steps(env):
    assert env["ok"] is True, env["error"]
    assert validate_envelope(env) == []
    return env["result"]["steps"]


def _step(env, kind):
    return next(s for s in _steps(env) if s["kind"] == kind)


def test_spike_bom_order():
    env = solder.plan(SPIKE_LIST)
    steps = _steps(env)
    assert [s["kind"] for s in steps] == SPIKE_ORDER
    assert [s["refs"] for s in steps] == [["W1"], ["R1", "R2"], ["C1"], ["Q1"], ["D1"], ["C2"], ["J1", "J2"], ["X1"], ["U1"]]
    assert [s["n"] for s in steps] == list(range(1, 10))
    assert env["action"] == "solder.plan"
    assert env["result"]["parts_total"] == 11
    assert env["result"]["unknown_parts"] == [] and env["result"]["unclear_parts"] == []
    assert env["summary"].startswith("9 solder steps for 11 parts: wire jumper, resistors, ceramic capacitor")


def test_steps_have_exactly_the_contract_shape():
    for s in _steps(solder.plan(SPIKE_LIST)):
        assert set(s) == {"id", "n", "refs", "kind", "action", "hints"}
        assert all(set(h) == {"code", "severity", "text", "source_ids"} for h in s["hints"])
        assert all(isinstance(h["source_ids"], list) for h in s["hints"])
        assert all(h["severity"] in ("info", "caution", "danger") for h in s["hints"])


def test_electrolytic_polarity_hint_is_danger_with_sources():
    env = solder.plan(SPIKE_LIST)
    elko = _step(env, "electrolytic")
    pol = [h for h in elko["hints"] if h["code"] == "polarity"]
    assert len(pol) == 1 and pol[0]["severity"] == "danger"
    assert elko["hints"][0] == pol[0]  # danger first, the UI shows it on top
    w = next(w for w in env["warnings"] if w["code"] == "polarity" and w["severity"] == "danger")
    assert w["message"].startswith("C2: ")
    assert set(w["source_ids"]) == {"solder-nichicon-al-guidelines", "solder-nichicon-al-technical-notes", "solder-rubycon-zlj-spec"}
    assert {"solder-nichicon-al-guidelines", "solder-rubycon-zlj-spec"} <= {s["id"] for s in env["sources"]}
    assert "danger at C2" in env["summary"]


def test_polarity_heat_and_pinout_hints():
    env = solder.plan(SPIKE_LIST)
    led = {h["code"]: h for h in _step(env, "led")["hints"]}
    assert led["polarity"]["severity"] == "caution" and "cathode" in led["polarity"]["text"]
    assert "lens" in led["heat_sensitive"]["text"]
    q = {h["code"]: h for h in _step(env, "transistor")["hints"]}
    assert q["pinout"]["text"].startswith("Pinout from the datasheet, do not guess")
    assert "heat_sensitive" in q
    diode = _step(solder.plan("D1 1N4148"), "diode")
    assert any(h["code"] == "polarity" and "band marks the cathode" in h["text"] for h in diode["hints"])
    ic = _step(solder.plan("U1 NE555 (DIP-8)"), "ic")
    assert any(h["code"] == "orientation" and "notch" in h["text"] for h in ic["hints"])
    caution = next(w for w in env["warnings"] if w["code"] == "polarity" and w["severity"] == "caution")
    assert "Q1 (transistor)" in caution["message"] and "D1 (LED)" in caution["message"]


def test_mechanical_parts_last_and_alignment_hint():
    steps = _steps(solder.plan(SPIKE_LIST))
    mech = [s["n"] for s in steps if s["kind"] in ("header", "terminal", "module")]
    assert mech == [7, 8, 9]
    header = next(s for s in steps if s["kind"] == "header")
    assert any(h["code"] == "mechanical" and "Solder one pin" in h["text"] for h in header["hints"])


def test_step_ids_are_stable_for_reordered_input():
    lines = [ln for ln in SPIKE_LIST.splitlines() if ln and not ln.startswith("#")]
    base = {s["kind"]: s["id"] for s in _steps(solder.plan("\n".join(lines)))}
    orders = [lines[::-1], lines[3:] + lines[:3], lines[7:] + lines[:7], sorted(lines), sorted(lines, key=len)]
    for shuffled in orders:
        assert shuffled != lines
        steps = _steps(solder.plan("\n".join(shuffled)))
        assert {s["kind"]: s["id"] for s in steps} == base
        assert [s["kind"] for s in steps] == SPIKE_ORDER


def test_step_id_formula():
    canon = "resistor:R1,R10,R2"  # sha1(kind + sorted refs)[:10], lexicographic sort, comma-separated
    want = hashlib.sha1(canon.encode(), usedforsecurity=False).hexdigest()[:10]
    assert solder.step_id("resistor", ["R2", "R10", "R1"]) == want
    assert solder.step_id("resistor", ["r1", "R2", "R10"]) == want
    assert len(want) == 10
    assert solder.step_id("resistor", ["R1", "R2"]) != solder.step_id("resistor", ["R1"])
    assert solder.step_id("resistor", ["R1"]) != solder.step_id("diode", ["R1"])
    env = solder.plan("R10 1k\nR2 1k\nR1 1k")
    step = _steps(env)[0]
    assert step["refs"] == ["R1", "R2", "R10"]  # natural order for display
    assert step["id"] == want


def test_unknown_kind_gets_own_check_manually_step():
    env = solder.plan("R1 1k\nZ1 mystery part\nZ2 another mystery\nJ1 Pin header 1x4")
    steps = _steps(env)
    unknown = [s for s in steps if s["kind"] == "unknown"]
    assert [s["refs"] for s in unknown] == [["Z1"], ["Z2"]]  # one step per unknown part
    for s in unknown:
        assert s["action"].startswith("Check manually:")
        assert any(h["code"] == "check_manually" for h in s["hints"])
    assert steps[-1]["kind"] == "header"  # mechanical parts still last
    assert env["result"]["unknown_parts"] == ["Z1", "Z2"]
    assert "check manually: Z1, Z2" in env["summary"]
    assert any(w["code"] == "check_manually" for w in env["warnings"])


def test_unclear_capacitor_asks_back():
    env = solder.plan("C1 4u7\nC2 100nF")
    unclear = _step(env, "capacitor")
    assert unclear["refs"] == ["C1"]
    assert any(h["code"] == "kind_uncertain" and h["severity"] == "caution" for h in unclear["hints"])
    assert env["result"]["unclear_parts"] == ["C1"]
    assert any(w["code"] == "kind_uncertain" for w in env["warnings"])
    ceramic = _step(env, "ceramic")
    assert any(h["code"] == "kind_by_value" for h in ceramic["hints"])
    a = {x["key"]: x for x in env["assumptions"]}
    assert a["capacitor_type"]["value"] == "C2: ceramic" and "rule-of-thumb" in a["capacitor_type"]["reason"]


def test_ceramic_with_package_has_no_guess_hint():
    env = solder.plan("C1 100nF [C_Disc_D5.0mm]")
    assert all(h["code"] != "kind_by_value" for h in _step(env, "ceramic")["hints"])
    assert "capacitor_type" not in {x["key"] for x in env["assumptions"]}


def test_same_kinds_are_grouped():
    env = solder.plan(KICAD_SEMICOLON)
    steps = _steps(env)
    kinds = [s["kind"] for s in steps]
    assert len(kinds) == len(set(kinds))
    assert next(s for s in steps if s["kind"] == "ceramic")["refs"] == ["C1", "C3"]
    assert kinds == ["resistor", "ceramic", "transistor", "led", "electrolytic", "header"]


@pytest.mark.parametrize(("bom_text", "code", "ref"), [
    ("J5 Laser module KY-008", "laser_safety", "J5"),
    ("BT1 LiPo 1S", "battery_safety", "BT1"),
    ("J3 JST-PH for 18650 cell", "battery_safety", "J3"),
    ("K1 relay for 230 V lamp", "low_voltage_only", "K1"),
])
def test_safety_warnings_are_danger(bom_text, code, ref):
    env = solder.plan(bom_text)
    w = [w for w in env["warnings"] if w["code"] == code and w["severity"] == "danger"]
    assert len(w) == 1 and w[0]["message"].startswith(f"{ref}: ")
    step = _steps(env)[0]
    assert [h["severity"] for h in step["hints"] if h["code"] == code] == ["danger"]
    assert len([w for w in env["warnings"] if w["code"] == code]) == 1


def test_battery_step_has_no_duplicate_battery_hint():
    step = _steps(solder.plan("BT1 LiPo 1S"))[0]
    assert [h["code"] for h in step["hints"]].count("battery_safety") == 1
    assert step["hints"][0]["code"] == "battery_safety"


def test_assumptions_name_order_rule_and_no_temperature():
    env = solder.plan(SPIKE_LIST)
    a = {x["key"]: x for x in env["assumptions"]}
    assert "rule-of-thumb" in a["order"]["reason"]
    assert a["soldering_temperature"]["value"] == "not given"
    assert env["sources"][0]["id"] == "rule-of-thumb"


def test_no_temperature_or_time_numbers_in_output():
    text = json.dumps(solder.plan(SPIKE_LIST + "BT1 LiPo\nJ9 laser\nK1 relay\nZ1 x\nY1 16MHz\nU2 NE555\n"), ensure_ascii=False)
    assert "°" not in text and "℃" not in text
    for unit in (" s ", " sec", "seconds", " W ", "watt"):
        assert unit not in text.lower()


def test_spike_answer_stays_small():
    env = solder.plan(SPIKE_LIST)
    assert len(json.dumps(env, ensure_ascii=False).encode()) <= MAX_RESULT_BYTES


def test_hint_source_ids_are_known_sources():
    from circuit_bench.bench_core import sources
    known = set(sources.all_sources())
    for s in _steps(solder.plan(SPIKE_LIST)):
        for h in s["hints"]:
            assert set(h["source_ids"]) <= known, h


def test_plan_is_deterministic():
    assert json.dumps(solder.plan(SPIKE_LIST)) == json.dumps(solder.plan(SPIKE_LIST))


def test_plan_accepts_project_parts():
    parts = [
        {"ref": "R1", "kind": "resistor", "value": "1 kΩ", "from_calc": "npn-1"},
        {"ref": "Q1", "kind": "transistor", "value": "2N2222A", "package": "TO-92", "qty": 1},
        {"ref": "C1", "kind": "electrolytic", "value": "100 µF", "package": None},
    ]
    assert [s["kind"] for s in _steps(solder.plan(parts))] == ["resistor", "transistor", "electrolytic"]


@pytest.mark.parametrize("bad", ["", None, 42, [], "R1 1k\nR1 2k", [{"ref": "R1", "value": {"x": 1}}]])
def test_plan_bad_input_is_invalid_args(bad):
    env = solder.plan(bad)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args"
    assert validate_envelope(env) == []
    assert env["action"] == "solder.plan"


def test_compress_refs():
    assert solder.compress_refs(["R3", "R1", "R2", "R4", "R7", "C1", "R9"]) == "C1, R1-R4, R7, R9"
    assert solder.compress_refs(["R1", "R2"]) == "R1, R2"
    assert solder.compress_refs(["Q1A", "Q1B"]) == "Q1A, Q1B"


# --- solder.step -------------------------------------------------------------------------------------------------

def _plan():
    return solder.plan(SPIKE_LIST)


def test_step_marks_done_and_names_next():
    plan = _plan()
    steps = plan["result"]["steps"]
    env = solder.step(plan, steps[0]["id"], True)
    assert env["ok"] is True and validate_envelope(env) == []
    assert env["action"] == "solder.step"
    r = env["result"]
    assert r["done"] == [steps[0]["id"]]
    assert r["progress"] == {"done": 1, "total": 9}
    assert r["next_step"]["id"] == steps[1]["id"]
    assert r["complete"] is False
    assert env["summary"] == "Step 1, wire jumper W1 marked done; 1/9 done, next: step 2, resistors R1, R2."


def test_step_on_project_solder_object_and_undo():
    steps = _plan()["result"]["steps"]
    project_solder = {"steps": steps, "done": [steps[0]["id"], steps[1]["id"], "stale-id"]}
    env = solder.step(project_solder, steps[1]["id"], False)
    assert env["result"]["done"] == [steps[0]["id"]]  # stale ids from an older plan are dropped
    assert env["result"]["progress"] == {"done": 1, "total": 9}
    env = solder.step(project_solder, steps[4]["id"], True)
    assert env["result"]["done"] == [steps[0]["id"], steps[1]["id"], steps[4]["id"]]  # plan order
    assert env["result"]["next_step"]["n"] == 3


def test_step_warns_about_the_elko_before_it_is_soldered():
    steps = _plan()["result"]["steps"]
    done = [s["id"] for s in steps[:4]]
    env = solder.step({"steps": steps, "done": done}, steps[4]["id"], True)
    assert env["result"]["next_step"]["kind"] == "electrolytic"
    w = env["warnings"][0]
    assert w["code"] == "polarity" and w["severity"] == "danger" and w["message"].startswith("C2: ")
    assert "solder-rubycon-zlj-spec" in w["source_ids"]
    assert "solder-rubycon-zlj-spec" in {s["id"] for s in env["sources"]}


def test_step_complete():
    steps = _plan()["result"]["steps"]
    done = [s["id"] for s in steps[:-1]]
    env = solder.step({"steps": steps, "done": done}, steps[-1]["id"], True)
    assert env["result"]["complete"] is True and env["result"]["next_step"] is None
    assert env["summary"] == "All 9 solder steps done."


def test_step_does_not_mutate_the_plan():
    plan = _plan()
    before = json.dumps(plan)
    solder.step(plan, plan["result"]["steps"][0]["id"], True)
    assert json.dumps(plan) == before


@pytest.mark.parametrize(("plan", "step_id", "done", "fragment"), [
    ("nope", "x", True, "plan must be an object"),
    ({"steps": []}, "x", True, "no steps"),
    ({"steps": [{"n": 1}]}, "x", True, "bad step"),
    (None, "x", True, "plan must be an object"),
    ("PLAN", "0000000000", True, "unknown step id"),
    ("PLAN", 7, True, "step_id must be"),
    ("PLAN", "FIRST", "yes", "done must be true or false"),
    ({"steps": "PLAN", "done": "abc"}, "FIRST", True, "plan.done must be a list"),
])
def test_step_bad_input_is_invalid_args(plan, step_id, done, fragment):
    good = _plan()
    first = good["result"]["steps"][0]["id"]
    if plan == "PLAN":
        plan = good
    elif isinstance(plan, dict) and plan.get("steps") == "PLAN":
        plan = {**plan, "steps": good["result"]["steps"]}
    step_id = first if step_id == "FIRST" else step_id
    env = solder.step(plan, step_id, done)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args"
    assert fragment in env["error"]["message"]
    assert validate_envelope(env) == []
