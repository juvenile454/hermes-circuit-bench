"""Friction of the agent path found by a second probe with a real model.

1. Project answers (add_module, connect, assign, set_rails, add_parts) carry the sources their checks and warnings
   cite, within 8 kB (source notes go first when it gets tight).
2. add_parts takes conn per part (pin -> net); a plain part connected that way meets a module's requires[].
3. Schema texts: facts types (incl. i_max), connect merges facts per key.
4. bench_pins suggest honours limit (default 3, max 10), counts the free pins (free, more) and says that
   beyond_suggestions picks passed the same checks.
5. Skill lines (level shifting in a project, board current via facts.i_max, parallel pull-ups, add_parts conn).
Uses the real module catalog (no fake), like the agent does.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from circuit_bench import schemas, tools
from circuit_bench.bench_core import contracts, pins

SKILL = Path(__file__).resolve().parent.parent / "circuit_bench" / "skills" / "esp32-bench" / "SKILL.md"
I2C = [{"role": "SDA", "mode": "i2c_sda", "pin": 21, "net": "I2C_SDA"},
       {"role": "SCL", "mode": "i2c_scl", "pin": 22, "net": "I2C_SCL"}]
DS3231 = {"SDA": "I2C_SDA", "SCL": "I2C_SCL", "VCC": "3V3", "GND": "GND"}
MPU = {"SDA": "I2C_SDA", "SCL": "I2C_SCL", "VDD": "3V3", "GND": "GND", "AD0": "GND"}
STEP = [{"role": "STEP", "mode": "out", "pin": 4}, {"role": "DIR", "mode": "out", "pin": 2},
        {"role": "EN", "mode": "out", "pin": 1}]
A4988 = {"STEP": "STEP", "DIR": "DIR", "ENABLE": "EN", "VDD": "3V3", "GND": "GND", "VBB1": "VMOT", "VBB2": "VMOT",
         "SLEEP": "3V3", "RESET": "3V3"}


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


def _create(bench, pid="f2", assignments=None, chip="esp32", variant="wroom-32e", devkit="esp32-devkitc-v4"):
    env = bench("bench_project", action="create", id=pid, chip=chip, variant=variant, devkit=devkit,
                assignments=assignments or I2C)
    assert env["ok"], env
    return env


def _cited(env) -> set[str]:
    return {i for x in [*env["checks"], *env["warnings"]] for i in x.get("source_ids") or []}


def _ids(env) -> list[str]:
    return [s["id"] for s in env["sources"]]


def _check(env, cid):
    return [c for c in env["checks"] if c["id"] == cid]


# --------------------------------------------------------------------------------------------- 1. sources

@pytest.mark.parametrize("action,args", [
    ("connect", {"ref": "U2", "conn": {"AD0": "GND"}}),
    ("set_rails", {"rails": {"VMOT": "12V"}}),
    ("assign", {"assignments": [{"role": "LED", "mode": "out", "pin": 4}]}),
    ("add_parts", {"parts": [{"ref": "R9", "kind": "resistor", "value": "10k"}]}),
])
def test_project_answers_carry_the_cited_sources(bench, action, args):
    _create(bench)
    env = bench("bench_project", action="add_module", id="f2", module="ds3231", conn=DS3231)
    assert env["ok"] and env["sources"], env
    assert _cited(env) <= set(_ids(env)), (_cited(env), _ids(env))
    bench("bench_project", action="add_module", id="f2", module="mpu6050", conn=MPU)
    env = bench("bench_project", action=action, id="f2", **args)
    assert env["ok"], env
    assert _cited(env) and _cited(env) <= set(_ids(env)), (_cited(env), _ids(env))
    assert len(_ids(env)) == len(set(_ids(env)))
    assert all({"id", "title", "url", "retrieved"} <= s.keys() for s in env["sources"])


def test_pin_rule_sources_come_with_assign(bench):
    env = _create(bench)
    ids = _ids(env)
    assert any(i.startswith("idf-") for i in ids), ids  # the pin rules' source, cited by no single item


def test_chip_electrical_source_resolves(bench):
    """elec-ds-esp32s3 (the ESP32-S3 datasheet, cited by modules.level_out) is in data/sources and resolved."""
    _create(bench, chip="esp32s3", variant="n16r8", devkit="esp32-s3-devkitc-1",
            assignments=[{"role": "SDA", "mode": "i2c_sda", "pin": 2, "net": "I2C_SDA"},
                         {"role": "SCL", "mode": "i2c_scl", "pin": 1, "net": "I2C_SCL"}])
    env = bench("bench_project", action="add_module", id="f2", module="bme280",
                conn={"VDD": "3V3", "GND": "GND", "SCK": "I2C_SCL", "SDI": "I2C_SDA", "SDO": "GND", "CSB": "3V3"})
    assert "elec-ds-esp32s3" in _cited(env) and "elec-ds-esp32s3" in _ids(env)
    chk = bench("bench_pins", action="check", project="f2")
    assert "elec-ds-esp32s3" in _ids(chk)
    assert not [w for w in chk["warnings"] if w["code"] == "rule_data_missing"]


def test_sources_only_for_what_is_shown_and_notes_go_when_tight():
    src = [{"id": f"s{i}", "title": "t", "url": "https://example.org", "retrieved": "2026-11-08", "note": "n" * 300}
           for i in range(3)]
    shown = contracts.warning("mod_hazard", "caution", "x", ["s0"])
    dropped = contracts.warning("mod_required_parts", "info", "y", ["s1"])
    env = contracts.envelope("project.update", "x", {"id": "p"}, warnings=[shown])
    out = tools._with_sources(env, {"warnings": [shown, dropped], "checks": [], "sources": src})
    assert _ids(out) == ["s0", "s2"]  # s1: only a dropped warning cites it; s2: cited by nobody (pin rules)
    slim = tools._with_sources(env, {"warnings": [shown], "checks": [], "sources": src}, notes=False)
    assert all("note" not in s for s in slim["sources"])


def test_many_modules_stay_below_8kb_with_sources(bench):
    _create(bench)
    for i in range(6):
        env = bench("bench_project", action="add_module", id="f2", module="ds3231", conn=DS3231, ref=f"U{i + 1}")
        assert env["ok"], env
        assert _cited(env) <= set(_ids(env))


# --------------------------------------------------------------------------------------------- 2. add_parts conn

def test_add_parts_conn_meets_the_bulk_cap(bench):
    _create(bench, chip="esp32s3", variant="n16r8", devkit="esp32-s3-devkitc-1", assignments=STEP)
    assert bench("bench_project", action="set_rails", id="f2", rails={"VMOT": "12V"})["ok"]
    env = bench("bench_project", action="add_module", id="f2", module="a4988", variant="carrier", conn=A4988)
    assert env["ok"], env
    bulk = [c for c in _check(env, "modules.required_parts") if "bulk_cap" in c["detail"]]
    assert not bulk or bulk[0]["status"] != "passed"
    assert any("bulk_cap" in w["message"] for w in env["warnings"] if w["code"] == "mod_required_parts")
    env = bench("bench_project", action="add_parts", id="f2",
                parts=[{"ref": "C1", "kind": "electrolytic", "value": "100uF", "conn": {"+": "VMOT", "-": "GND"}}])
    assert env["ok"], env
    assert env["result"]["added"] == [{"ref": "C1", "kind": "electrolytic", "value": "100uF",
                                       "conn": {"+": "VMOT", "-": "GND"}}]
    bulk = [c for c in _check(env, "modules.required_parts") if "bulk_cap" in c["detail"]]
    assert bulk and bulk[0]["status"] == "passed", env["checks"]
    assert not any("bulk_cap" in w["message"] for w in env["warnings"])
    part = next(p for p in bench("bench_project", action="get", id="f2")["result"]["project"]["parts"]
                if p["ref"] == "C1")
    assert part["conn"] == {"+": "VMOT", "-": "GND"}


def test_add_parts_without_conn_then_connect(bench):
    _create(bench, chip="esp32s3", variant="n16r8", devkit="esp32-s3-devkitc-1", assignments=STEP)
    bench("bench_project", action="set_rails", id="f2", rails={"VMOT": "12V"})
    bench("bench_project", action="add_module", id="f2", module="a4988", variant="carrier", conn=A4988)
    env = bench("bench_project", action="add_parts", id="f2",
                parts=[{"ref": "C1", "kind": "electrolytic", "value": "100uF"}])
    assert env["ok"] and "conn" not in env["result"]["added"][0]
    env = bench("bench_project", action="connect", id="f2", ref="C1", conn={"+": "VMOT", "-": "GND"})
    bulk = [c for c in _check(env, "modules.required_parts") if "bulk_cap" in c["detail"]]
    assert bulk and bulk[0]["status"] == "passed"


def test_add_parts_bad_conn_pin_names_the_convention(bench):
    _create(bench)
    env = bench("bench_project", action="add_parts", id="f2",
                parts=[{"ref": "D1", "kind": "diode", "value": "1N4148", "conn": {"anode pin": "X"}}])
    assert not env["ok"] and env["error"]["code"] == "invalid_args"
    text = env["error"]["message"] + (env["error"].get("hint") or "")
    assert "A, K" in text and "+, -" in text


# --------------------------------------------------------------------------------------------- 3. schema texts

def test_schema_texts():
    props = schemas.PROJECT["parameters"]["properties"]
    facts = props["facts"]["description"]
    for word in ("bool", "level_shifter", "none/unknown/4k7", "pullups_to", "pin/net/V", "none/3V3/unknown",
                 "onboard", "i_max", "incl. qty", "led_strip", "null"):
        assert word in facts, word
    conn = props["parts"]["items"]["properties"]["conn"]["description"]
    for word in ("1,2", "+,-", "A,K"):
        assert word in conn, word
    assert "add_parts with conn, or connect ref later" in schemas.PROJECT["description"]
    assert "max 10" in schemas.PINS["parameters"]["properties"]["limit"]["description"]


# --------------------------------------------------------------------------------------------- 4. suggest

def test_suggest_default_three_and_counts():
    env = pins.suggest("esp32", [{"role": "LED", "mode": "out"}], devkit="esp32-devkitc-v4", variant="wroom-32e")
    r = env["result"]["requests"][0]
    assert len(r["suggestions"]) == 3 and r["free"] > 3 and r["more"] == r["free"] - 3


def test_suggest_limit():
    env = pins.suggest("esp32", [{"role": "LED", "mode": "out"}], devkit="esp32-devkitc-v4", variant="wroom-32e",
                       limit=8)
    r = env["result"]["requests"][0]
    assert len(r["suggestions"]) == 8 and r["more"] == r["free"] - 8
    assert [s["gpio"] for s in r["suggestions"]] == sorted(s["gpio"] for s in r["suggestions"])
    for bad in (0, 11, "5", True):
        env = pins.suggest("esp32", [{"role": "LED", "mode": "out"}], limit=bad)
        assert not env["ok"] and env["error"]["code"] == "invalid_args", bad


def test_suggest_limit_via_tool(bench):
    env = bench("bench_pins", action="suggest", chip="esp32", devkit="esp32-devkitc-v4", variant="wroom-32e",
                requests=[{"role": "LED", "mode": "out"}], limit=6)
    assert len(env["result"]["requests"][0]["suggestions"]) == 6
    assert not bench("bench_pins", action="suggest", chip="esp32", requests=[{"role": "LED", "mode": "out"}],
                     limit=20)["ok"]


def test_beyond_suggestions_explained():
    reqs = [{"role": f"O{i}", "mode": "out"} for i in range(5)]
    env = pins.suggest("esp32", reqs, devkit="esp32-devkitc-v4", variant="wroom-32e")
    beyond = [a for a in env["result"]["allocation"] if a["beyond_suggestions"]]
    assert beyond  # five roles, three suggestions each: the allocation goes past them
    assert "passed the same checks" in env["summary"]
    assert "passed the same checks" in _check(env, "suggest.distinct")[0]["detail"]
    for a in beyond:  # really without findings: pins.check agrees
        chk = pins.check("esp32", [{"role": a["role"], "mode": "out", "pin": a["gpio"]}], devkit="esp32-devkitc-v4",
                         variant="wroom-32e")
        assert chk["result"]["pins"][0]["verdict"] == "ok", a


# --------------------------------------------------------------------------------------------- 5. skill

def test_skill_lines():
    text = SKILL.read_text(encoding="utf-8")
    flat = " ".join(text.split())
    for needle in ("two `bss138` modules or a `pca9306` via `add_module`", "block only draws", "`facts.i_max`",
                   "`bench_calc led_strip`", "in parallel", "`conn` pin->net", "`connect` ref later",
                   "`beyond_suggestions` picks passed the same checks", "`limit`", "`more`"):
        assert needle in flat, needle
    assert len(text.splitlines()) <= 120 and len(text) <= 9200
