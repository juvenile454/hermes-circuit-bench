"""The demo project laser-trigger (sim.demo): content, idempotence, pin check, firmware copy."""
from __future__ import annotations

import filecmp
import json
from pathlib import Path

import pytest

from circuit_bench.bench_core import calc, contracts, pins, project, sim, solder


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(sim, "TIME_SCALE", 0.0)


@pytest.fixture
def demo():
    env = sim.demo()
    assert contracts.validate_envelope(env) == [], env
    assert env["ok"] is True and env["simulated"] is True, env
    return env


def _project(pid="laser-trigger"):
    return project.get(pid)["result"]["project"]


def test_demo_board_and_assignments(demo):
    p = _project()
    assert p["simulated"] is True and p["title"] == "Laser trigger"
    assert {k: p["board"][k] for k in ("chip", "variant", "devkit", "module")} == {
        "chip": "esp32s3", "variant": "n16r8", "devkit": "esp32-s3-devkitc-1", "module": "wroom-1"}
    assert p["options"]["wifi"] is True
    assert [(a["role"], a["pin"], a["mode"]) for a in p["assignments"]] == [
        ("LASER", 14, "out"), ("BUTTON", 2, "in_pullup"), ("SDA", 8, "i2c_sda"), ("SCL", 9, "i2c_scl"), ("VBAT", 1, "adc")]
    assert all(a["verdict"] == "ok" for a in p["assignments"])  # verdicts come from project.update (pins.check)
    assert demo["result"]["created"] is True and demo["result"]["port"] == sim.PORT
    assert {"id": "sim.demo.pins", "status": "passed", "detail": "5 of 5 assignments ok (pins.check)"} in demo["checks"]


def test_demo_passes_pins_check_without_blocked(demo):
    p = _project()
    b = p["board"]
    env = pins.check(b["chip"], [{"role": a["role"], "mode": a["mode"], "pin": a["pin"]} for a in p["assignments"]],
                     variant=b["variant"], wifi=p["options"]["wifi"], devkit=b["devkit"])
    assert env["ok"] is True
    assert [r["verdict"] for r in env["result"]["pins"]] == ["ok"] * 5
    assert "0 blocked" in env["summary"]


def test_demo_parts_and_calcs_come_from_calc(demo):
    p = _project()
    parts = {x["ref"]: x for x in p["parts"]}
    assert {r: parts[r]["value"] for r in ("R1", "R2", "R3", "R4")} == {"R1": "1 kΩ", "R2": "10 kΩ", "R3": "100 kΩ",
                                                                        "R4": "100 kΩ"}
    assert parts["Q1"] == {"ref": "Q1", "kind": "transistor", "value": "2N2222A", "package": "TO-18", "from_calc": "npn-1"}
    assert parts["C1"]["kind"] == "electrolytic"  # the polarity alarm of the solder station
    calcs = {c["id"]: c for c in p["calcs"]}
    npn = calcs["npn-1"]
    assert npn["type"] == "npn" and npn["inputs"]["part"] == "2N2222A" and npn["inputs"]["load"] == "laser"
    again = calc.npn(**npn["inputs"])
    assert npn["result"]["i_b"] == again["result"]["i_b"] and npn["result"]["summary"] == again["summary"]
    assert npn["result"]["i_b"]["display"] == "2.53 mA" and npn["result"]["forced_beta"]["display"] == "5.1 x"
    assert {c["id"]: c["status"] for c in npn["result"]["checks"]}["calc.npn.saturation"] == "passed"
    assert "onsemi-2n2222a" in npn["sources"]
    div = calcs["div-1"]
    assert div["result"]["v_out_max"]["display"] == "2.10 V"
    codes = [w["code"] for w in demo["warnings"]]
    assert "laser_safety" in codes and "polarity" in codes


def test_demo_schematic_and_solder_plan(demo):
    p = _project()
    (c,) = p["circuits"]
    assert (c["id"], c["block"], c["svg"]) == ("laser", "npn_low_side", "artifacts/laser.svg")
    svg = (project.path("laser-trigger") / c["svg"]).read_text(encoding="utf-8")
    assert svg.startswith("<svg") and "currentColor" in svg
    rows = [{k: x[k] for k in ("ref", "kind", "value", "package") if k in x} for x in p["parts"]]
    assert p["solder"]["steps"] == solder.plan(rows)["result"]["steps"]
    assert p["solder"]["done"] == []
    kinds = [s["kind"] for s in p["solder"]["steps"]]
    assert kinds[0] == "resistor" and "electrolytic" in kinds
    elko = next(s for s in p["solder"]["steps"] if s["kind"] == "electrolytic")
    assert any(h["severity"] == "danger" for h in elko["hints"])


def test_demo_firmware_is_a_copy_in_the_project(demo):
    p = _project()
    fw = Path(p["firmware"]["dir"])
    assert fw == (project.path("laser-trigger") / "firmware").resolve() and p["firmware"]["env"] == "s3"
    assert not fw.is_relative_to(sim.PACKAGE_DIR)
    for rel in ("platformio.ini", "src/main.cpp", "README.md"):
        assert filecmp.cmp(fw / rel, sim.EXAMPLES_DIR / "laser-trigger" / rel, shallow=False), rel
    (fw / "src" / "main.cpp").write_text("// changed\n", encoding="utf-8")
    assert "#define DEMO_CRASH 1" in (sim.EXAMPLES_DIR / "laser-trigger" / "src" / "main.cpp").read_text(encoding="utf-8")
    assert demo["result"]["firmware_dir"] == str(fw)


def test_demo_notes_carry_the_laser_safety(demo):
    notes = [n["text"] for n in _project()["notes"]]
    assert any(n.startswith("Laser safety:") for n in notes)
    assert all(n["by"] == "agent" for n in _project()["notes"])


def test_demo_twice_is_one_project_with_the_same_rev(demo):
    path = project.path("laser-trigger") / "project.json"
    before = path.read_bytes()
    again = sim.demo()
    assert again["ok"] is True and again["simulated"] is True
    assert again["result"]["created"] is False and again["result"]["rev"] == demo["result"]["rev"]
    assert "already exists" in again["summary"]
    assert path.read_bytes() == before
    assert [e["id"] for e in project.list_projects()["result"]["projects"]] == ["laser-trigger"]


def test_demo_keeps_an_edited_project(demo):
    rev = demo["result"]["rev"]
    upd = project.update("laser-trigger", rev, [{"op": "note", "text": "mine"}], by="ui")
    assert upd["ok"] is True
    again = sim.demo()
    assert again["result"]["rev"] == rev + 1 and _project()["notes"][-1]["text"] == "mine"


def test_demo_answer_stays_small(demo):
    assert len(json.dumps(demo, ensure_ascii=False).encode("utf-8")) <= contracts.MAX_RESULT_BYTES
    assert len(json.dumps(sim.demo(), ensure_ascii=False).encode("utf-8")) <= contracts.MAX_RESULT_BYTES
    assert demo["result"]["assignments"][0] == {"role": "LASER", "mode": "out", "pin": 14, "verdict": "ok"}
    assert demo["result"]["parts"][:2] == ["R1 1 kΩ", "R2 10 kΩ"]


def test_demo_with_another_id():
    env = sim.demo("laser-copy", by="ui")
    assert env["ok"] is True and env["result"]["id"] == "laser-copy"
    p = _project("laser-copy")
    assert all(a["updated_by"] == "ui" for a in p["assignments"])
    assert Path(p["firmware"]["dir"]) == (project.path("laser-copy") / "firmware").resolve()


@pytest.mark.parametrize("bad", ["Laser", "../x", "", "a" * 49, None])
def test_demo_bad_id(bad):
    env = sim.demo(bad)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args" and env["action"] == "sim.demo"
    assert env["simulated"] is True


def test_demo_bad_by():
    env = sim.demo(by="cron")
    assert env["ok"] is False and env["error"]["code"] == "invalid_args"


def test_demo_without_schemdraw_still_creates_the_project(monkeypatch):
    from circuit_bench.bench_core import schematic

    def missing(block, params=None, *, devkit=None, gpio=None):
        return contracts.fail("schematic.render", "dependency_missing", "schemdraw is not installed")
    monkeypatch.setattr(schematic, "render", missing)
    env = sim.demo()
    assert env["ok"] is True
    assert _project()["circuits"][0]["svg"] is None
    assert "schematic_missing" in [w["code"] for w in env["warnings"]]


def test_demo_copy_example_refuses_unknown_names():
    with pytest.raises(contracts.BenchError) as e:
        sim.copy_example("../boards", "laser-trigger")
    assert e.value.code == "invalid_args"
