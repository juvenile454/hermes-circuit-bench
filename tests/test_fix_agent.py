"""Friction of the agent path found by a probe with a real model.

1. bench_project add_module/connect/assign/set_rails carry the module warnings (not only "see warning mod_…").
2. Net convention: one net per signal line; a conn value that names a role sits on that assignment's net.
3./5. Schema texts (variant, net, conn, facts values, onboard).
4. connect changes address, facts, variant and qty in place.
6. Skill lines (net convention, level shifter block, breakouts).
Uses the real module catalog (no fake), like the agent does.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from circuit_bench import schemas, tools
from circuit_bench.bench_core import contracts, modcheck, modspec, project

SKILL = Path(__file__).resolve().parent.parent / "circuit_bench" / "skills" / "esp32-bench" / "SKILL.md"
I2C = [{"role": "SDA", "mode": "i2c_sda", "pin": 21, "net": "I2C_SDA"},
       {"role": "SCL", "mode": "i2c_scl", "pin": 22, "net": "I2C_SCL"}]
DS3231 = {"SDA": "I2C_SDA", "SCL": "I2C_SCL", "VCC": "3V3", "GND": "GND"}
MPU = {"SDA": "I2C_SDA", "SCL": "I2C_SCL", "VDD": "3V3", "GND": "GND", "AD0": "GND"}


@pytest.fixture
def bench():
    handlers = tools.make_handlers(tools.Host(cron=lambda: False))

    def call(name: str, **args):
        out = handlers[name](args)
        assert len(out.encode("utf-8")) <= tools.MAX_BYTES
        env = json.loads(out)
        assert contracts.validate_envelope(env) == [], env
        return env
    return call


def _create(bench, pid="fa", assignments=None, chip="esp32", variant="wroom-32e", devkit="esp32-devkitc-v4"):
    env = bench("bench_project", action="create", id=pid, chip=chip, variant=variant, devkit=devkit,
                assignments=assignments or I2C)
    assert env["ok"], env
    return env


def _codes(env):
    return [(w["code"], w["severity"]) for w in env["warnings"]]


def _project(bench, pid="fa"):
    return bench("bench_project", action="get", id=pid)["result"]["project"]


# --------------------------------------------------------------------------------------------- 1. warnings

def test_add_module_answer_carries_the_address_conflict_word_for_word(bench):
    _create(bench)
    assert bench("bench_project", action="add_module", id="fa", module="ds3231", conn=DS3231)["ok"]
    env = bench("bench_project", action="add_module", id="fa", module="mpu6050", conn=MPU)
    assert env["ok"], env
    chk = {c["id"]: c for c in env["checks"]}
    summary = chk.get("modules.address_conflict") or chk["modules"]  # compact answers carry one summary check
    assert summary["status"] == "failed" and ("address_conflict" in summary.get("detail", "") or
                                              "modules.address_conflict" in chk)
    mine = [w for w in env["warnings"] if w["code"] == "mod_address_conflict"]
    # caution (two devices on one address: the bus fails, nothing is damaged)
    assert len(mine) == 1 and mine[0]["severity"] == "caution" and mine[0]["refs"] == ["U1", "U2"]
    ref = bench("bench_pins", action="check", project="fa")  # the same text as bench_pins check
    assert mine == [w for w in ref["warnings"] if w["code"] == "mod_address_conflict"]
    counts = env["result"]["module_counts"]
    assert counts["caution"] >= 1 and counts["modules"] == 2 and counts["shown"] >= 1
    # every "see warning mod_x" check has its warning in the same answer
    seen = {w["code"] for w in env["warnings"]}
    for c in env["checks"]:
        if c.get("detail", "").startswith("see warning "):
            assert c["detail"].split()[2].rstrip(".") in seen, c


@pytest.mark.parametrize("action,args", [
    ("connect", {"ref": "U2", "conn": {"AD0": "GND"}}),
    ("set_rails", {"rails": {"VMOT": "12V"}}),
    ("assign", {"assignments": [{"role": "LED", "mode": "out", "pin": 4}]}),
])
def test_other_project_actions_carry_the_module_warnings(bench, action, args):
    _create(bench)
    bench("bench_project", action="add_module", id="fa", module="ds3231", conn=DS3231)
    bench("bench_project", action="add_module", id="fa", module="mpu6050", conn=MPU)
    env = bench("bench_project", action=action, id="fa", **args)
    assert env["ok"], env
    assert ("mod_address_conflict", "caution") in _codes(env)
    assert "module_counts" in env["result"]


def test_no_modules_no_module_counts(bench):
    env = _create(bench)
    assert "module_counts" not in env["result"]
    assert not [w for w in env["warnings"] if w["code"].startswith("mod_")]


def test_module_warnings_stay_below_8kb_and_keep_dangers():
    big = [contracts.warning("mod_required_parts", "caution", f"U{i} " + "x" * 500, []) for i in range(30)]
    danger = contracts.warning("mod_address_conflict", "danger", "U1, U2 answer at 0x68", [])
    chk = {"warnings": [danger, *big], "result": {"modules": {"counts": {"findings": 31, "shown": 31}}}}
    env = contracts.envelope("project.update", "x", {"id": "p"})
    out = tools._module_warnings(env, chk)
    assert tools._size(out) <= tools.MAX_BYTES
    assert out["warnings"][0]["code"] == "mod_address_conflict"
    c = out["result"]["module_counts"]
    assert c["shown"] == len(out["warnings"]) < 31 and c["hidden"][0].startswith("mod_required_parts")


def test_module_warnings_are_not_repeated():
    w = contracts.warning("mod_hazard", "caution", "laser", [])
    env = {**contracts.envelope("project.update", "x", {"id": "p"}), "warnings": [w]}
    out = tools._module_warnings(env, {"warnings": [w], "result": {"modules": {"counts": {}}}})
    assert out["warnings"] == [w]


# --------------------------------------------------------------------------------------------- 2. nets

def test_role_name_in_conn_is_the_assignment_net(bench):
    _create(bench, "led", [{"role": "LED_DATA", "mode": "out", "pin": 4}], chip="esp32s3", variant="n16r8",
            devkit="esp32-s3-devkitc-1")
    env = bench("bench_project", action="add_module", id="led", module="ws2812b",
                conn={"DIN": "LED_DATA", "VDD": "5V", "VSS": "GND"})
    chk = {c["id"]: c for c in env["checks"]}
    assert chk["modules.unconnected"]["status"] == "passed", chk["modules.unconnected"]
    gpio = bench("bench_project", action="connect", id="led", ref="U1", conn={"DIN": "GPIO4"})
    assert {c["id"]: c["status"] for c in gpio["checks"]}["modules.unconnected"] == "passed"


def test_resolver_roles():
    items = [{"role": "STEP", "mode": "out", "pin": 4, "net": "GPIO4"},
             {"role": "SDA", "mode": "i2c_sda", "pin": 8, "net": "I2C_SDA"},
             {"role": "BUS", "mode": "out", "pin": 9, "net": "GPIO9"},
             {"role": "I2C_SDA", "mode": "out", "pin": 10, "net": "GPIO10"}]  # a role named like a net: the net wins
    roles = modcheck._Resolver.roles(items)
    assert roles == {"STEP": "GPIO4", "SDA": "I2C_SDA", "BUS": "GPIO9"}
    sig = modcheck._Resolver.signal
    assert sig("STEP", {"3V3": 3.3}, {4: "GPIO4"}, roles) == "GPIO4"
    assert sig("I2C_SDA", {}, {}, roles) == "I2C_SDA" and sig("GPIO8", {}, {8: "I2C_SDA"}, roles) == "I2C_SDA"
    assert sig("3V3", {"3V3": 3.3}, {}, {"3V3": "GPIO1"}) == "3V3"  # rails win over roles


def test_role_net_for_plain_parts():
    """A plain part's conn names a role: same net as the module's pin (one resolution for both)."""
    ctx = modcheck.build_ctx(chip="esp32s3", assignments=[{"role": "LED", "mode": "out", "pin": 4}],
                             parts=[{"ref": "U1", "kind": "ic", "value": "WS2812B", "module": "ws2812b",
                                     "conn": {"DIN": "LED", "VDD": "5V", "VSS": "GND"}},
                                    {"ref": "R1", "kind": "resistor", "value": "330", "conn": {"1": "LED"}}],
                             options={}, devkit=None)
    assert ctx is not None
    assert ("R1", "1") in ctx.nets["GPIO4"]["pins"] and ("U1", "DIN") in ctx.nets["GPIO4"]["pins"]


# --------------------------------------------------------------------------------------------- 4. connect

def test_connect_changes_address_facts_qty_in_place(bench):
    _create(bench)
    bench("bench_project", action="add_module", id="fa", module="ds3231", conn=DS3231)
    bench("bench_project", action="add_module", id="fa", module="mpu6050", conn={**MPU, "AD0": "3V3"})
    env = bench("bench_project", action="connect", id="fa", ref="U2", address="0x69",
                facts={"pullups": "4k7", "pullups_to": "VDD", "onboard": ["pullups", "decoupling"]}, qty=2)
    assert env["ok"], env
    assert "mod_address_conflict" not in {w["code"] for w in env["warnings"]}
    u2 = next(p for p in _project(bench)["parts"] if p["ref"] == "U2")
    assert u2["address"] == "0x69" and u2["qty"] == 2 and u2["conn"]["AD0"] == "3V3"
    assert u2["facts"] == {"pullups": "4k7", "pullups_to": "VDD", "onboard": ["decoupling", "pullups"]}
    env = bench("bench_project", action="connect", id="fa", ref="U2", facts={"regulator": "3V3"})
    u2 = next(p for p in _project(bench)["parts"] if p["ref"] == "U2")
    assert list(u2["facts"]) == ["regulator", "pullups", "pullups_to", "onboard"]  # merged, stored order


def test_connect_variant_rechecks_pins_and_address(bench):
    _create(bench)
    bench("bench_project", action="add_module", id="fa", module="sht40", address="0x44",
          conn={"SDA": "I2C_SDA", "SCL": "I2C_SCL"})
    bad = bench("bench_project", action="connect", id="fa", ref="U1", variant="bd1b")
    assert bad["error"]["code"] == "invalid_args" and "0x44" in bad["error"]["message"], bad["error"]
    ok = bench("bench_project", action="connect", id="fa", ref="U1", variant="bd1b", address="0x45")
    assert ok["ok"], ok
    u1 = _project(bench)["parts"][0]
    assert u1["variant"] == "bd1b" and u1["address"] == "0x45"
    bench("bench_project", action="add_module", id="fa", module="ssd1306", conn={"SDA": "I2C_SDA"})
    gone = bench("bench_project", action="connect", id="fa", ref="U2", variant="spi4")
    assert gone["error"]["code"] == "invalid_args" and "SDA" in gone["error"]["message"]


def test_connect_refusals(bench):
    _create(bench)
    bench("bench_project", action="add_module", id="fa", module="mpu6050", conn=MPU)
    bench("bench_project", action="add_parts", id="fa", parts=[{"ref": "R1", "kind": "resistor", "value": "4k7"}])
    nothing = bench("bench_project", action="connect", id="fa", ref="U1")
    assert nothing["error"]["code"] == "invalid_args" and "address" in nothing["error"]["message"]
    for args in ({"variant": "x"}, {"address": "0x50"}, {"facts": {"bogus": 1}}, {"facts": {"onboard": ["heater"]}},
                 {"qty": 0}):
        env = bench("bench_project", action="connect", id="fa", ref="U1", **args)
        assert env["error"]["code"] == "invalid_args", (args, env)
    plain = bench("bench_project", action="connect", id="fa", ref="R1", address="0x40")
    assert plain["error"]["code"] == "invalid_args" and "not a module part" in plain["error"]["message"]
    assert bench("bench_project", action="connect", id="fa", ref="R1", qty=2)["ok"]


def test_connect_null_removes_address_and_facts(tmp_path):
    project.create("nul", "nul", "esp32", "wroom-32e", "esp32-devkitc-v4", by="agent")
    up = project.update("nul", 1, [{"op": "add_module", "module": "mpu6050", "address": "0x69",
                                    "facts": {"pullups": "none", "regulator": "3V3"}}], by="agent")
    assert up["ok"], up
    up = project.update("nul", 2, [{"op": "connect", "ref": "U1", "address": None, "facts": {"pullups": None}}],
                        by="agent")
    assert up["ok"], up
    part = up["result"]["project"]["parts"][0]
    assert "address" not in part and part["facts"] == {"regulator": "3V3"}
    bad = project.update("nul", 3, [{"op": "connect", "ref": "U1", "facts": {"bogus": None}}], by="agent")
    assert bad["error"]["code"] == "invalid_args"


# --------------------------------------------------------------------------------------------- 5. facts

def test_onboard_fact():
    assert modspec.FACT_KEYS["onboard"] == ("decoupling", "pullups", "reset_rc", "protection")
    assert project._facts({"onboard": ["Protection", "decoupling", "decoupling"]}, "f") == {
        "onboard": ["decoupling", "protection"]}
    assert project._facts({"onboard": "reset_rc"}, "f") == {"onboard": ["reset_rc"]}
    assert project._facts({"onboard": []}, "f") == {"onboard": []}
    for bad in (["heater"], 3, {"a": 1}):
        with pytest.raises(contracts.BenchError):
            project._facts({"onboard": bad}, "f")


# --------------------------------------------------------------------------------------------- 3./5. schema texts

def test_schema_texts():
    props = schemas.PROJECT["parameters"]["properties"]
    assert "catalog variant" in props["variant"]["description"] and "set_board" in props["variant"]["description"]
    assert "catalog variant" in schemas.PINS["description"]
    assert "I2C_SDA" in props["assignments"]["items"]["properties"]["net"]["description"]
    assert "role" in props["conn"]["description"] and "GPIO<n>" in props["conn"]["description"]
    facts = props["facts"]["description"]
    for word in ("none", "unknown", "4k7", "pullups_to", "3V3", "bool", *(modspec.FACT_KEYS["onboard"] or ())):
        assert word in facts, word
    for key in modspec.FACT_KEYS:
        assert key in facts or key in SCHEMA_PENDING, key
    for word in ("connect", "address", "facts", "variant", "qty"):
        assert word in schemas.PROJECT["description"], word


# facts keys whose word in schemas.PROJECT is still to come
SCHEMA_PENDING: frozenset[str] = frozenset()  # none: i_max is documented



# --------------------------------------------------------------------------------------------- 6. skill

def test_skill_lines():
    text = SKILL.read_text(encoding="utf-8")
    flat = " ".join(text.split())
    assert "only with the same `net`" not in flat
    for needle in ("each line its own net", "`I2C_SDA`", "`GPIO<n>`", "without it the role name is the net",
                   "BSS138", "AN10441", "not for LED data", "74AHCT125", "`onboard`", "ask what is on board",
                   "`connect` changes it in place"):
        assert needle in flat, needle
    assert len(text.splitlines()) <= 120 and len(text) <= 9200
