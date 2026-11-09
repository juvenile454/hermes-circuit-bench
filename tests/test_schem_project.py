"""schematic.render with a project and a role takes the net (and pin, DevKit) of the assignment."""
from __future__ import annotations

import pytest

from circuit_bench.bench_core import boards
from circuit_bench.bench_core import project as P
from circuit_bench.bench_core import schematic
from circuit_bench.bench_core.contracts import validate_envelope

pytest.importorskip("schemdraw")

S3 = "esp32-s3-devkitc-1"
NPN = {"r_base": "1k", "load": "laser module"}


def _project(**over) -> dict:
    """Synthetic project object with the assignment fields (role, mode, pin, net, verdict, rule_ids, updated_by)."""
    def a(role, mode, pin, net):
        return {"role": role, "mode": mode, "pin": pin, "net": net, "verdict": "ok", "rule_ids": [], "updated_by": "agent"}
    p = {"id": "bench-x", "board": {"chip": "esp32s3", "module": "wroom-1", "variant": "n16r8", "devkit": S3,
                                    "detected": None},
         "assignments": [a("LASER", "out", 14, "LASER_EN"), a("KEY", "in_pullup", 2, None),
                         a("VBAT", "adc", 1, "VBAT_DIV"), a("FAN", "out", 4, "GND"), a("PUMP", "out", 5, "pump-on"),
                         a("SENSE", "adc", 6, "VIN"), a("2ND", "out", 7, None)]}
    p.update(over)
    return p


def _ok(env: dict) -> dict:
    assert env["ok"], env["error"]
    assert validate_envelope(env) == []
    return env


def _signal_net(env: dict, pin: int) -> str:
    """Name of the net on the GPIO's header pin."""
    node = boards.header_of(S3, pin)
    return next(n["name"] for n in env["result"]["nets"] if node in n["nodes"])


def _assumed(env: dict) -> dict[str, tuple[str, str]]:
    return {a["key"]: (a["value"], a["reason"]) for a in env["assumptions"]}


def test_role_gives_the_net_pin_and_devkit_of_the_assignment():
    """The reported case: npn_low_side with project laser-trigger and role LASER drew LOAD_EN; now LASER_EN."""
    env = _ok(schematic.render("npn_low_side", NPN, project=_project(), role="LASER"))
    assert env["summary"] == "NPN low-side driver (LASER_EN) on IO14 (J1-20): 4 parts, 7 wires."
    assert env["result"]["wiring"][0] == {"from": "J1-20 · IO14", "to": "R1.1", "net": "LASER_EN"}
    nets = {n["name"]: n["nodes"] for n in env["result"]["nets"]}
    assert nets["LASER_EN"] == ["J1-20", "R1.1"] and "LASER_BASE" in nets and "LOAD_EN" not in nets
    assumed = _assumed(env)
    assert assumed["net"] == ("LASER_EN", "net of the assignment LASER (GPIO14)")
    assert "devkit" not in assumed  # from the project board
    assert {c["id"]: c["status"] for c in env["checks"]}["schematic.header_pin"] == "passed"
    assert "LASER_EN" in env["result"]["svg"] and "LOAD_EN" not in env["result"]["svg"]
    assert not [w for w in env["warnings"] if w["code"] in ("gpio_unassigned", "assignment_pin_differs")]


def test_explicit_parameters_win():
    env = _ok(schematic.render("npn_low_side", {**NPN, "net": "trigger"}, project=_project(), role="LASER"))
    assert env["result"]["wiring"][0]["net"] == "TRIGGER" and "net" not in _assumed(env)
    env = _ok(schematic.render("npn_low_side", NPN, project=_project(), role="LASER", gpio=4, devkit=None))
    assert env["result"]["wiring"][0] == {"from": "J1-4 · IO4", "to": "R1.1", "net": "LASER_EN"}
    differs = [w for w in env["warnings"] if w["code"] == "assignment_pin_differs"]
    assert len(differs) == 1 and differs[0]["severity"] == "caution" and "GPIO14" in differs[0]["message"]
    # an explicit DevKit wins over the project board (here: no board data -> chip pin names)
    bare = _project(board={"chip": "esp32s3", "module": None, "variant": None, "devkit": None, "detected": None})
    env = _ok(schematic.render("npn_low_side", NPN, project=bare, role="LASER"))
    assert env["result"]["wiring"][0] == {"from": "GPIO14", "to": "R1.1", "net": "LASER_EN"}
    env = _ok(schematic.render("npn_low_side", NPN, project=bare, role="LASER", devkit=S3))
    assert env["result"]["wiring"][0]["from"] == "J1-20 · IO14"


@pytest.mark.parametrize("block,params,role,net,origin", [
    ("button_pullup", {}, "KEY", "KEY", "role"),  # assignment without net: the role name
    ("divider", {"r1": "100k", "r2": "100k"}, "VBAT", "VBAT_DIV", "net"),  # the GPIO side of the divider
    ("led", {"r_series": 150}, "FAN", "FAN", "role"),  # GND is a supply net, not a signal net
    ("led", {"r_series": 150}, "PUMP", "PUMP", "role"),  # pump-on: valid in the project, not as a schematic net
    ("divider", {"r1": "100k", "r2": "100k"}, "SENSE", "SENSE", "role"),  # VIN is already the divider input
    ("divider", {"r1": "100k", "r2": "100k", "input_net": "VBAT"}, "SENSE", "VIN", "net"),
])
def test_net_from_the_assignment_or_the_role(block, params, role, net, origin):
    env = _ok(schematic.render(block, params, project=_project(), role=role))
    pin = next(a["pin"] for a in _project()["assignments"] if a["role"] == role)
    assert _signal_net(env, pin) == net and f"({net}) on IO{pin} " in env["summary"]
    reason = _assumed(env)["net"][1]
    assert reason.startswith("net of the assignment" if origin == "net" else "no net in the assignment; the role name")
    assert reason.endswith(f"{role} (GPIO{pin})")


def test_no_valid_candidate_keeps_the_block_default():
    env = _ok(schematic.render("npn_low_side", NPN, project=_project(), role="2ND"))  # 2ND: no letter first
    assert env["result"]["wiring"][0]["net"] == "LOAD_EN" and "net" not in _assumed(env)


def test_project_without_role_only_gives_the_devkit():
    env = _ok(schematic.render("npn_low_side", NPN, project=_project(), gpio=14))
    assert env["result"]["wiring"][0] == {"from": "J1-20 · IO14", "to": "R1.1", "net": "LOAD_EN"}
    assert "net" not in _assumed(env)


@pytest.mark.parametrize("kw,needle", [
    ({"role": "LASER"}, "role needs a project"),
    ({"project": _project(), "role": "NOPE"}, "no assignment with role NOPE in project bench-x"),
    ({"project": _project(), "role": "laser"}, "role must be a role name"),
    ({"project": _project(), "role": 14}, "role must be a role name"),
    ({"project": "laser-trigger", "role": "LASER"}, "project must be a bench project object"),
])
def test_role_refusals(kw, needle):
    env = schematic.render("npn_low_side", NPN, **kw)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args", env
    assert needle in env["error"]["message"]
    assert validate_envelope(env) == []


def test_with_a_stored_project():
    """Field names as stored by project.create/update, not only the synthetic dict above."""
    assert P.create("bench-r", "Bench", "esp32s3", "n16r8", S3)["ok"]
    env = P.update("bench-r", 1, [{"op": "assign", "role": "LASER", "mode": "out", "pin": 14, "net": "LASER_EN"},
                                  {"op": "assign", "role": "KEY", "mode": "in_pullup", "pin": 2}], by="agent")
    assert env["ok"], env["error"]
    stored = P.get("bench-r")["result"]["project"]
    laser = _ok(schematic.render("npn_low_side", NPN, project=stored, role="LASER"))
    assert laser["summary"] == "NPN low-side driver (LASER_EN) on IO14 (J1-20): 4 parts, 7 wires."
    key = _ok(schematic.render("button_pullup", {}, project=stored, role="KEY"))
    assert stored["assignments"][1]["net"] is None
    assert _signal_net(key, 2) == "KEY" and {"from": f"{boards.header_of(S3, 2)} · IO2", "to": "R1.2", "net": "KEY"} in \
        key["result"]["wiring"]
