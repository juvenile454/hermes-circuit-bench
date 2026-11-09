"""Project store (create/get/list/update, typed ops, rev conflict, flock, atomic writes)."""
from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

from circuit_bench.bench_core import contracts, modspec, project, solder, storage
from circuit_bench.bench_core.contracts import BenchError

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "desktop-src" / "fixtures"
SHA = "3f9a5c0d21e8b47a6c13f0e2d9b8a7c6e5f4d3c2b1a09f8e7d6c5b4a39281706"
PID = "laser-trigger"


def _new(pid=PID, **kw):
    args = {"title": "Laser trigger", "chip": "esp32s3", "variant": "n16r8", "devkit": "esp32-s3-devkitc-1"} | kw
    res = project.create(pid, args.pop("title"), args.pop("chip"), args.pop("variant"), args.pop("devkit"), **args)
    assert res["ok"], res["error"]
    return res


def _upd(rev, *ops, by="agent", pid=PID, trusted=True):
    """project.update as a server-side producer (trusted: result ops allowed); trusted=False = a client."""
    return project.update(pid, rev, list(ops), by=by, trusted=trusted)


def _ok(res):
    assert res["ok"], res["error"]
    assert contracts.validate_envelope(res) == []
    return res


def _err(res, code):
    assert res["ok"] is False, res["summary"]
    assert res["error"]["code"] == code, res["error"]
    assert contracts.validate_envelope(res) == []
    return res


def _file(pid=PID) -> Path:
    return project.path(pid) / "project.json"


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


@pytest.fixture
def sent(monkeypatch):
    """Fake public Hermes event bridge; records (plugin_id, event, payload)."""
    calls = []
    mod = types.ModuleType("hermes_cli.plugin_events")
    mod.broadcast_plugin_event = lambda plugin_id, event, payload=None: calls.append((plugin_id, event, payload))
    pkg = types.ModuleType("hermes_cli")
    pkg.plugin_events = mod
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_events", mod)
    return calls


# --------------------------------------------------------------------------------------------- create / get / list

def test_create_writes_schema_1_with_private_modes():
    res = _ok(_new())
    p = res["result"]["project"]
    assert res["result"]["rev"] == 1 and p["rev"] == 1 and p["schema"] == 1
    assert p["board"] == {"chip": "esp32s3", "module": "wroom-1", "variant": "n16r8", "devkit": "esp32-s3-devkitc-1",
                          "detected": None}
    assert p["options"] == {"wifi": True, "framework": "arduino", "logic_v": 3.3}
    assert p["solder"] == {"steps": [], "done": []} and p["debug"] == {"last_panic": None} and p["notes"] == []
    assert p["created"] == p["updated"] and p["simulated"] is False
    assert res["summary"] == "Created bench project 'laser-trigger': Laser trigger (ESP32-S3 N16R8): no pins assigned."
    assert [a["key"] for a in res["assumptions"]] == ["wifi"]
    pdir = project.path(PID)
    assert pdir == storage.data_dir() / "projects" / PID
    assert json.loads(_file().read_text(encoding="utf-8")) == p
    assert _mode(_file()) == 0o600 and _mode(pdir / ".lock") == 0o600
    assert _mode(pdir) == 0o700 and _mode(pdir / "artifacts") == 0o700 and _mode(pdir.parent) == 0o700
    assert [x.name for x in pdir.iterdir() if x.name.startswith(".project.")] == []


def test_create_same_shape_as_the_fixture():
    fx = json.loads((FIXTURES / "project.laser-trigger.json").read_text(encoding="utf-8"))["result"]["project"]
    p = _new()["result"]["project"]
    assert sorted(p) == sorted(fx)
    for key in ("board", "options", "solder", "firmware", "debug"):
        assert sorted(p[key]) == sorted(fx[key]), key


def test_create_simulated_and_without_variant():
    res = _ok(project.create("sim-1", "  Sim  ", "ESP32-S3", simulated=True))
    p = res["result"]["project"]
    assert p["title"] == "Sim" and p["simulated"] is True and res["simulated"] is True
    assert p["board"]["variant"] is None and p["board"]["module"] is None and p["board"]["devkit"] is None
    assert [w["code"] for w in res["warnings"]] == ["variant_unknown"]
    c3 = _ok(project.create("c3", "C3", "esp32c3"))
    assert c3["warnings"] == [] and c3["summary"].startswith("Created bench project 'c3': C3 (ESP32-C3)")


@pytest.mark.parametrize("args, code", [
    (("Bad_ID", "t", "esp32s3"), "invalid_args"),
    (("", "t", "esp32s3"), "invalid_args"),
    (("x" * 49, "t", "esp32s3"), "invalid_args"),
    (("../x", "t", "esp32s3"), "invalid_args"),
    (("ok", "", "esp32s3"), "invalid_args"),
    (("ok", "a\nb", "esp32s3"), "invalid_args"),
    (("ok", "t" * 121, "esp32s3"), "invalid_args"),
    (("ok", None, "esp32s3"), "invalid_args"),
    (("ok", "t", "esp8266"), "unknown_chip"),
    (("ok", "t", "esp32s3", "n2"), "invalid_args"),
    (("ok", "t", "esp32c3", "n16r8"), "invalid_args"),
    (("ok", "t", "esp32s3", None, "nope"), "unknown_board"),
    (("ok", "t", "esp32c3", None, "esp32-s3-devkitc-1"), "invalid_args"),
])
def test_create_rejects_bad_input(args, code):
    _err(project.create(*args), code)
    assert not (storage.data_dir() / "projects" / "ok" / "project.json").exists()


def test_create_twice_is_a_conflict():
    _new()
    _err(project.create(PID, "Other", "esp32c3"), "project_conflict")
    assert project.get(PID)["result"]["project"]["title"] == "Laser trigger"


def test_get_and_not_found():
    _new()
    res = _ok(project.get(PID))
    assert res["result"]["rev"] == 1 and res["result"]["project"]["id"] == PID
    _err(project.get("missing"), "project_not_found")
    _err(project.get("Bad"), "invalid_args")


def test_fixture_project_reads_back_with_the_fixture_summary():
    fx = json.loads((FIXTURES / "project.laser-trigger.json").read_text(encoding="utf-8"))
    assert project.validate(fx["result"]["project"]) == []
    pdir = project.path(PID)
    pdir.mkdir()
    _file().write_text(json.dumps(fx["result"]["project"]), encoding="utf-8")
    res = _ok(project.get(PID))
    assert res["summary"] == fx["summary"]
    assert res["result"] == fx["result"] and res["simulated"] is True


@pytest.mark.parametrize("damage", ["{not json", "[]", '{"schema": 2}', "ID"])
def test_damaged_project_is_reported(damage):
    _new()
    if damage == "ID":
        p = json.loads(_file().read_text(encoding="utf-8")) | {"id": "other"}
        damage = json.dumps(p)
    _file().write_text(damage, encoding="utf-8")
    res = _err(project.get(PID), "project_damaged")
    assert "damaged" in res["error"]["message"]
    _err(_upd(1, {"op": "note", "text": "x"}), "project_damaged")


def test_list_sorted_with_fixture_keys_and_damaged_skipped():
    fx = json.loads((FIXTURES / "projects.list.json").read_text(encoding="utf-8"))
    _new("zeta", title="Zeta")
    _new("alpha", title="Alpha", simulated=True)
    _new("broken")
    project.path("broken").joinpath("project.json").write_text("{", encoding="utf-8")
    project.path("lock-only").mkdir()  # a folder without project.json is not a project
    (storage.data_dir() / "projects" / "stray.txt").write_text("x", encoding="utf-8")
    res = _ok(project.list())
    entries = res["result"]["projects"]
    assert [e["id"] for e in entries] == ["alpha", "zeta"]
    assert sorted(entries[0]) == sorted(fx["result"]["projects"][0])
    assert entries[0]["simulated"] is True and entries[0]["rev"] == 1
    assert [w["code"] for w in res["warnings"]] == ["project_damaged"]
    assert res["summary"] == "2 bench projects."


def test_list_empty():
    res = _ok(project.list())
    assert res["result"] == {"projects": []} and res["summary"] == "0 bench projects."


def test_path_and_artifacts_dir():
    with pytest.raises(BenchError) as e:
        project.path("../etc")
    assert e.value.code == "invalid_args"
    with pytest.raises(BenchError) as e:
        project.artifacts_dir("nothing")
    assert e.value.code == "project_not_found"
    _new()
    adir = project.artifacts_dir(PID)
    assert adir == project.path(PID) / "artifacts" and adir.is_dir()
    adir.rmdir()
    assert project.artifacts_dir(PID).is_dir()  # created on demand


# --------------------------------------------------------------------------------------------- update basics

def test_wrong_rev_is_a_conflict_and_changes_nothing():
    _new()
    _ok(_upd(1, {"op": "note", "text": "first"}))
    before = _file().read_bytes()
    res = _err(_upd(1, {"op": "note", "text": "late"}), "project_conflict")
    assert res["result"] == {"rev": 2}
    assert "rev 2" in res["error"]["message"] and "project.get" in res["error"]["hint"]
    _err(_upd(7, {"op": "note", "text": "future"}), "project_conflict")
    assert _file().read_bytes() == before


@pytest.mark.parametrize("rev, ops, by", [
    (0, [{"op": "note", "text": "x"}], "agent"),
    (True, [{"op": "note", "text": "x"}], "agent"),
    ("1", [{"op": "note", "text": "x"}], "agent"),
    (1, [], "agent"),
    (1, {"op": "note", "text": "x"}, "agent"),
    (1, [{"op": "note", "text": "x"}] * 51, "agent"),
    (1, [{"op": "note", "text": "x"}], "user"),
    (1, [{"op": "delete_everything"}], "agent"),
    (1, [{"op": ["note"]}], "agent"),
    (1, ["note"], "agent"),
    (1, [{"op": "note", "text": "x", "extra": 1}], "agent"),
    (1, [{"op": "note"}], "agent"),
    (1, [{"op": "note", "text": "x" * 2001}], "agent"),
    (1, [{"op": "note", "text": "   "}], "agent"),
])
def test_bad_update_requests_are_refused(rev, ops, by):
    _new()
    before = _file().read_bytes()
    _err(project.update(PID, rev, ops, by=by), "invalid_args")
    assert _file().read_bytes() == before


def test_update_unknown_project():
    _err(_upd(1, {"op": "note", "text": "x"}, pid="ghost"), "project_not_found")
    assert not project.path("ghost").exists()


def test_all_or_nothing():
    _new()
    before = _file().read_bytes()
    res = _err(_upd(1, {"op": "note", "text": "kept?"}, {"op": "assign", "role": "LASER", "mode": "out", "pin": 14},
                    {"op": "unassign", "role": "NOPE"}), "invalid_args")
    assert res["error"]["message"].startswith("ops[2] (unassign):")
    assert _file().read_bytes() == before
    assert project.get(PID)["result"]["rev"] == 1


def test_no_change_keeps_rev_and_file(sent):
    _new()
    sent.clear()
    _ok(_upd(1, {"op": "set_board", "wifi": True}))
    before = _file().read_bytes()
    res = _ok(_upd(1, {"op": "set_board", "variant": "n16r8"}))
    assert res["result"]["rev"] == 1 and res["result"]["changed"] == [] and "no changes" in res["summary"]
    assert _file().read_bytes() == before and sent == []


def test_update_emits_project_updated(sent):
    _new()
    assert sent == [("circuit-bench", "project.updated", {"id": PID, "rev": 1, "changed": ["created"], "by": "agent"})]
    sent.clear()
    res = _ok(_upd(1, {"op": "assign", "role": "LASER", "mode": "out", "pin": 14}, {"op": "note", "text": "hi"},
                   by="ui"))
    assert res["result"]["changed"] == ["assignments", "notes"]
    assert sent == [("circuit-bench", "project.updated", {"id": PID, "rev": 2, "changed": ["assignments", "notes"],
                                                         "by": "ui"})]


def test_a_failing_event_never_undoes_the_write(monkeypatch, sent):
    _new()
    mod = sys.modules["hermes_cli.plugin_events"]

    def boom(*a, **kw):
        raise RuntimeError("down")

    monkeypatch.setattr(mod, "broadcast_plugin_event", boom)
    _ok(_upd(1, {"op": "note", "text": "still saved"}))
    monkeypatch.setattr(project.events, "emit", lambda *a, **kw: (_ for _ in ()).throw(ValueError("bad")))
    _ok(_upd(2, {"op": "note", "text": "also saved"}))
    assert project.get(PID)["result"]["rev"] == 3


def test_events_noop_without_hermes(monkeypatch):
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_events", None)
    _new()
    _ok(_upd(1, {"op": "note", "text": "no desktop"}))


# --------------------------------------------------------------------------------------------- pins and verdicts

def test_assign_gpio35_on_n16r8_is_blocked_in_the_project():
    _new()
    res = _ok(_upd(1, {"op": "assign", "role": "LASER", "mode": "out", "pin": "GPIO35", "net": "LASER_EN"}))
    a = res["result"]["project"]["assignments"][0]
    assert a == {"role": "LASER", "mode": "out", "pin": 35, "net": "LASER_EN", "verdict": "blocked",
                 "rule_ids": ["s3.octal_psram"], "updated_by": "agent"}
    stored = json.loads(_file().read_text(encoding="utf-8"))["assignments"][0]
    assert stored["verdict"] == "blocked"
    w = res["warnings"][0]
    assert w["code"] == "pin_blocked" and w["severity"] == "danger" and w["source_ids"]
    assert [s["id"] for s in res["sources"]] == w["source_ids"]
    assert "LASER on GPIO35 is blocked" in res["summary"]


def test_caller_cannot_set_the_verdict():
    _new()
    _err(_upd(1, {"op": "assign", "role": "LASER", "mode": "out", "pin": 35, "verdict": "ok"}), "invalid_args")


def test_verdicts_follow_the_board():
    _new()
    _ok(_upd(1, {"op": "assign", "role": "LASER", "mode": "out", "pin": 35}))
    res = _ok(_upd(2, {"op": "set_board", "variant": "n8"}, by="ui"))  # no octal PSRAM on N8
    p = res["result"]["project"]
    assert p["board"]["variant"] == "n8" and p["assignments"][0]["verdict"] == "ok"
    assert res["result"]["changed"] == ["board", "assignments"]
    assert p["assignments"][0]["updated_by"] == "agent"  # recomputing a verdict is not a user edit
    res = _ok(_upd(3, {"op": "set_board", "variant": "n16r8"}))
    assert res["result"]["project"]["assignments"][0]["verdict"] == "blocked"
    assert [w["code"] for w in res["warnings"]] == ["pin_blocked"]


def test_assign_replaces_by_role_and_detects_duplicates():
    _new()
    _ok(_upd(1, {"op": "assign", "role": "LASER", "mode": "out", "pin": 14},
             {"op": "assign", "role": "BUTTON", "mode": "in_pullup", "pin": 2}))
    res = _ok(_upd(2, {"op": "assign", "role": "LASER", "mode": "pwm", "pin": 2}, by="ui"))
    a = res["result"]["project"]["assignments"]
    assert [(x["role"], x["mode"], x["pin"], x["verdict"]) for x in a] == [
        ("LASER", "pwm", 2, "blocked"), ("BUTTON", "in_pullup", 2, "blocked")]
    assert all("duplicate_pin" in x["rule_ids"] for x in a)
    assert [x["updated_by"] for x in a] == ["ui", "agent"]
    res = _ok(_upd(3, {"op": "unassign", "role": "LASER"}))
    a = res["result"]["project"]["assignments"]
    assert [(x["role"], x["verdict"], x["rule_ids"]) for x in a] == [("BUTTON", "ok", [])]


@pytest.mark.parametrize("op", [
    {"op": "assign", "role": "laser", "mode": "out", "pin": 14},
    {"op": "assign", "role": "LASER", "mode": "fast", "pin": 14},
    {"op": "assign", "role": "LASER", "mode": "out", "pin": "D5"},
    {"op": "assign", "role": "LASER", "mode": "out", "pin": True},
    {"op": "assign", "role": "LASER", "mode": "out", "pin": 14, "net": "bad net"},
    {"op": "assign", "role": "LASER", "mode": "out"},
    {"op": "unassign"},
])
def test_bad_assignments(op):
    _new()
    _err(_upd(1, op), "invalid_args")


def test_unknown_gpio_is_stored_as_blocked():
    _new()
    res = _ok(_upd(1, {"op": "assign", "role": "X", "mode": "out", "pin": 99}))
    assert res["result"]["project"]["assignments"][0]["verdict"] == "blocked"


def test_set_board_chip_change_resets_dependent_fields():
    _new()
    _ok(_upd(1, {"op": "set_detected", "port": "sim://esp32s3-n16r8", "mac": "AA:BB:CC:DD:EE:FF"},
             {"op": "assign", "role": "LED", "mode": "out", "pin": 5}))
    res = _ok(_upd(2, {"op": "set_board", "chip": "ESP32-C3", "wifi": False}))
    p = res["result"]["project"]
    assert p["board"] == {"chip": "esp32c3", "module": None, "variant": None, "devkit": None, "detected": None}
    assert p["options"]["wifi"] is False and p["assignments"][0]["verdict"] in ("ok", "caution", "blocked")
    _err(_upd(3, {"op": "set_board"}), "invalid_args")
    _err(_upd(3, {"op": "set_board", "wifi": "yes"}), "invalid_args")
    _err(_upd(3, {"op": "set_board", "chip": "esp32s3", "devkit": "esp32-s3-devkitc-1", "variant": "n99"}), "invalid_args")


# --------------------------------------------------------------------------------------------- every op once

def _detect_result():
    """Shape of a board.detect result (more fields than the project keeps)."""
    return {"port": "sim://esp32s3-n16r8", "mac": "AA:BB:CC:DD:EE:FF", "chip": "ESP32-S3 (QFN56) (revision v0.2)",
            "description": "Simulated ESP32-S3 N16R8", "features": ["Wi-Fi", "Embedded PSRAM 8MB (AP_3v3)"],
            "flash_size": "16MB", "variant_suggestion": "n16r8", "simulated": True, "chip_id": 9, "crystal_mhz": 40,
            "usb_mode": "USB-Serial/JTAG", "log_tail": ["Connecting...."], "reset_happened": True}


def _crash_result():
    return {"kind": "cpu_exception", "reason": "StoreProhibited", "core": 1, "arch": "xtensa",
            "registers": {"PC": "0x42002a1c"}, "interpretation": [], "reset_reason": None,
            "frames": [{"i": 0, "pc": "0x42002a1c", "function": "write_sensor_buffer", "file": "src/main.cpp",
                        "line": 5, "inlined": False, "source": "backtrace"}],
            "elf_sha256_log": "3f9a5c0d21e8b47a", "elf_match": True}


def _plan_steps():
    res = solder.plan([{"ref": "R1", "kind": "resistor", "value": "1k"}, {"ref": "D1", "kind": "diode", "value": "1N4148"},
                       {"ref": "J1", "kind": "connector", "value": "2x22 header"}])
    assert res["ok"], res["error"]
    return res["result"]["steps"]


def test_every_operation_once(tmp_path, sent):
    _new()
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "platformio.ini").write_text("[env:s3]\n", encoding="utf-8")
    steps = _plan_steps()
    calc = {"id": "npn-1", "type": "npn", "inputs": {"v_drive": 3.3}, "result": {"i_b": {"value": 0.0025, "unit": "A"}},
            "assumptions": [{"key": "v_be", "value": "0.7 V", "reason": "typical"}],
            "sources": [{"id": "rule-of-thumb", "url": None, "retrieved": None}]}
    cases = [
        ({"op": "set_board", "wifi": False}, ["options"]),
        ({"op": "set_detected", **_detect_result()}, ["board"]),
        ({"op": "assign", "role": "LASER", "mode": "out", "pin": 14, "net": "LASER_EN"}, ["assignments"]),
        ({"op": "unassign", "role": "LASER"}, ["assignments"]),
        ({"op": "add_parts", "parts": [{"ref": "r1", "kind": "resistor", "value": "1 kΩ", "from_calc": "npn-1"},
                                       {"ref": "J1", "kind": "connector", "value": "2x22 header", "qty": 2,
                                        "package": "2.54 mm"},
                                       {"ref": "C9", "kind": "capacitor", "value": "100 nF"}]}, ["parts"]),
        ({"op": "remove_parts", "refs": ["c9"]}, ["parts"]),
        ({"op": "add_calc", "calc": calc}, ["calcs"]),
        ({"op": "add_circuit", "circuit": {"id": "laser", "block": "npn_low_side", "params": {"r_base": 1000},
                                           "svg": "artifacts/laser.svg"}}, ["circuits"]),
        ({"op": "set_solder_plan", "steps": steps}, ["solder"]),
        ({"op": "solder_done", "step_id": steps[0]["id"], "done": True}, ["solder"]),
        ({"op": "set_firmware", "dir": str(fw), "env": "s3"}, ["firmware"]),
        ({"op": "set_build", "ok": True, "duration_s": 3.9, "ram_pct": 5.6, "flash_pct": 7.9,
          "elf": ".pio/build/s3/firmware.elf", "elf_sha256": SHA.upper(), "log_ref": "build-20261106-213852.log"},
         ["firmware"]),
        ({"op": "set_flash", "ok": True, "port": "sim://esp32s3-n16r8", "mac": "aa:bb:cc:dd:ee:ff", "elf_sha256": SHA,
          "duration_s": 6.2}, ["firmware"]),
        ({"op": "set_debug", "last_panic": _crash_result()}, ["debug"]),
        ({"op": "note", "text": "  Laser needs 5 V.\nCheck the module.  "}, ["notes"]),
    ]
    # the module ops have their own once-each test: tests/test_m0_project_modules.py
    assert sorted(op["op"] for op, _ in cases) == sorted(set(project.OPS) - set(modspec.MODULE_OPS))
    rev = 1
    for op, changed in cases:
        res = _ok(_upd(rev, op, by="ui" if rev % 2 else "agent"))
        assert res["result"]["changed"] == changed, op["op"]
        rev += 1
        assert res["result"]["rev"] == rev
    assert [c[2]["rev"] for c in sent] == list(range(1, rev + 1))
    p = project.get(PID)["result"]["project"]
    assert project.validate(p) == []
    assert p["rev"] == rev == 1 + len(cases)
    d = p["board"]["detected"]
    assert sorted(d) == sorted(project.DETECTED_FIELDS) and d["mac"] == "aa:bb:cc:dd:ee:ff" and d["simulated"] is True
    assert d["at"]
    assert p["assignments"] == []
    assert p["parts"][0] == {"ref": "R1", "kind": "resistor", "value": "1 kΩ", "from_calc": "npn-1"}
    assert p["parts"][1]["qty"] == 2
    assert p["calcs"][0]["sources"] == ["rule-of-thumb"]
    assert p["circuits"][0]["svg"] == "artifacts/laser.svg"
    assert p["solder"]["done"] == [steps[0]["id"]] and p["solder"]["steps"] == steps
    fwd = p["firmware"]
    assert fwd["dir"] == str(fw.resolve()) and fwd["env"] == "s3"
    assert fwd["last_build"] == {"ok": True, "at": fwd["last_build"]["at"], "ram_pct": 5.6, "flash_pct": 7.9,
                                 "elf": ".pio/build/s3/firmware.elf", "elf_sha256": SHA}
    assert sorted(fwd["last_flash"]) == sorted(project.FLASH_FIELDS) and fwd["last_flash"]["elf_sha256"] == SHA
    lp = p["debug"]["last_panic"]
    assert lp["top_frame"] == "write_sensor_buffer (src/main.cpp:5)" and lp["reason"] == "StoreProhibited"
    assert "frames" not in lp and "registers" not in lp and lp["elf_match"] is True
    assert p["notes"][0]["text"] == "Laser needs 5 V.\nCheck the module." and p["notes"][0]["by"] == ("ui" if len(cases) % 2 else "agent")
    res = _ok(_upd(rev, {"op": "set_debug", "last_panic": None}))
    assert res["result"]["project"]["debug"]["last_panic"] is None


def test_set_debug_accepts_the_whole_envelope_and_short_form():
    _new()
    env = contracts.envelope("crash.decode", "StoreProhibited", _crash_result())
    res = _ok(_upd(1, {"op": "set_debug", "last_panic": env}))
    assert res["result"]["project"]["debug"]["last_panic"]["kind"] == "cpu_exception"
    short = {"kind": "cpu_exception", "reason": "StoreProhibited", "core": 1,
             "top_frame": "write_sensor_buffer (src/main.cpp:5)", "at": "2026-11-06T21:40:02Z"}
    res = _ok(_upd(2, {"op": "set_debug", "last_panic": short}))
    assert res["result"]["project"]["debug"]["last_panic"] == short
    for bad in ({}, {"reason": "x", "at": "yesterday"}, "panic", {"reason": "x", "log_ref": "../etc/passwd"}):
        _err(_upd(3, {"op": "set_debug", "last_panic": bad}), "invalid_args")
    _err(_upd(3, {"op": "set_debug"}), "invalid_args")


def test_last_panic_names_the_crashed_firmware():
    """debug.last_panic keeps the prefix of "ELF file SHA256: ..." (crash.decode
    elf_sha256_log) so the UI knows which firmware crashed; panics without the line and older projects stay valid."""
    _new()
    res = _ok(_upd(1, {"op": "set_debug", "last_panic": _crash_result()}))
    panic = res["result"]["project"]["debug"]["last_panic"]
    assert panic["elf_sha256"] == "3f9a5c0d21e8b47a"
    assert project.validate(res["result"]["project"]) == []
    res = _ok(_upd(2, {"op": "set_debug", "last_panic": {**_crash_result(), "elf_sha256_log": None}}))
    assert "elf_sha256" not in res["result"]["project"]["debug"]["last_panic"]
    res = _ok(_upd(3, {"op": "set_debug", "last_panic": {**panic, "elf_sha256": "ABCDEF0123456789"}}))  # short form
    assert res["result"]["project"]["debug"]["last_panic"]["elf_sha256"] == "abcdef0123456789"
    for bad in ("xyz", "abc", "a" * 65, 12):
        _err(_upd(4, {"op": "set_debug", "last_panic": {**panic, "elf_sha256": bad}}), "invalid_args")


def test_parts_replace_by_ref_and_validate():
    _new()
    _ok(_upd(1, {"op": "add_parts", "parts": [{"ref": "R1", "kind": "resistor", "value": "1 kΩ"}]}))
    res = _ok(_upd(2, {"op": "add_parts", "parts": [{"ref": "R1", "kind": "resistor", "value": "2.2 kΩ"},
                                                     {"ref": "C1", "kind": "ceramic", "value": "100 nF"}]}))
    assert [(x["ref"], x["value"]) for x in res["result"]["project"]["parts"]] == [("R1", "2.2 kΩ"), ("C1", "100 nF")]
    for bad in ([], [{"ref": "R1", "kind": "flux_capacitor", "value": "1"}], [{"ref": "1R", "kind": "resistor", "value": "1"}],
                [{"ref": "R1", "kind": "resistor"}], [{"ref": "R1", "kind": "resistor", "value": "1", "qty": 0}],
                [{"ref": "R2", "kind": "resistor", "value": "1"}, {"ref": "r2", "kind": "resistor", "value": "2"}],
                [{"ref": "R1", "kind": "resistor", "value": "1", "price": 3}]):
        _err(_upd(3, {"op": "add_parts", "parts": bad}), "invalid_args")


def test_calc_and_circuit_replace_by_id_and_validate():
    _new()
    calc = {"id": "led-1", "type": "led", "inputs": {}, "result": {}}
    _ok(_upd(1, {"op": "add_calc", "calc": calc}, {"op": "add_calc", "calc": calc | {"inputs": {"v": 5}}}))
    p = project.get(PID)["result"]["project"]
    assert p["calcs"] == [calc | {"inputs": {"v": 5}, "assumptions": [], "sources": []}]
    for bad in ({"id": "Bad Id", "type": "led", "inputs": {}, "result": {}}, {"id": "a", "type": "led", "inputs": [], "result": {}},
                {"id": "a", "type": "led", "inputs": {"x": float("inf")}, "result": {}},
                {"id": "a", "type": "led", "inputs": {"x": object()}, "result": {}},
                {"id": "a", "type": "led", "inputs": {"x": "y" * 9000}, "result": {}}):
        _err(_upd(2, {"op": "add_calc", "calc": bad}), "invalid_args")
    for bad in ({"id": "a", "block": "led", "svg": "/etc/passwd"}, {"id": "a", "block": "led", "svg": "artifacts/../x.svg"},
                {"id": "a"}):
        _err(_upd(2, {"op": "add_circuit", "circuit": bad}), "invalid_args")


def test_solder_plan_keeps_done_for_the_same_ids():
    _new()
    steps = _plan_steps()
    _ok(_upd(1, {"op": "set_solder_plan", "steps": steps},
             {"op": "solder_done", "step_id": steps[1]["id"], "done": True},
             {"op": "solder_done", "step_id": steps[0]["id"], "done": True}))
    p = project.get(PID)["result"]["project"]
    assert p["solder"]["done"] == [steps[0]["id"], steps[1]["id"]]  # plan order
    fewer = [s for s in steps if s["id"] != steps[0]["id"]]
    res = _ok(_upd(2, {"op": "set_solder_plan", "steps": fewer}))
    assert res["result"]["project"]["solder"]["done"] == [steps[1]["id"]]
    res = _ok(_upd(3, {"op": "solder_done", "step_id": steps[1]["id"], "done": False}))
    assert res["result"]["project"]["solder"]["done"] == []
    forged = dict(steps[0], refs=["R9"])
    for op in ({"op": "set_solder_plan", "steps": [forged]}, {"op": "solder_done", "step_id": steps[0]["id"], "done": True},
               {"op": "solder_done", "step_id": "XYZ", "done": True},
               {"op": "solder_done", "step_id": steps[1]["id"], "done": "yes"},
               {"op": "set_solder_plan", "steps": [steps[1], steps[1]]}):
        _err(_upd(4, op), "invalid_args")
    assert solder.step_id(forged["kind"], forged["refs"]) != forged["id"]


def test_set_firmware_rules(tmp_path):
    _new()
    fw = tmp_path / "fw"
    fw.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    for d in (fw, other):
        (d / "platformio.ini").write_text("[env:s3]\n", encoding="utf-8")
    no_ini = tmp_path / "no-ini"
    no_ini.mkdir()
    _ok(_upd(1, {"op": "set_firmware", "dir": str(fw), "env": "s3"},
             {"op": "set_build", "ok": True, "elf_sha256": SHA}))
    res = _ok(_upd(2, {"op": "set_firmware", "dir": str(fw), "env": "s3"}))
    assert res["result"]["changed"] == []  # same folder and env: the build stays valid
    res = _ok(_upd(2, {"op": "set_firmware", "dir": str(other), "env": "s3"}))
    assert res["result"]["project"]["firmware"]["last_build"] is None  # another folder: build again
    pkg_example = ROOT / "circuit_bench" / "data"
    for op in ({"op": "set_firmware", "dir": "relative/fw", "env": "s3"},
               {"op": "set_firmware", "dir": str(tmp_path / "missing"), "env": "s3"},
               {"op": "set_firmware", "dir": str(pkg_example), "env": "s3"},
               {"op": "set_firmware", "dir": str(ROOT / "circuit_bench"), "env": "s3"},
               {"op": "set_firmware", "dir": str(fw), "env": "s3; rm -rf /"},
               {"op": "set_firmware", "dir": str(fw)},
               # no platformio.ini, the file system root, the home folders
               {"op": "set_firmware", "dir": str(no_ini), "env": "s3"},
               {"op": "set_firmware", "dir": "/", "env": "s3"},
               {"op": "set_firmware", "dir": "/etc", "env": "s3"},
               {"op": "set_firmware", "dir": "~", "env": "s3"},
               {"op": "set_firmware", "dir": "~/", "env": "s3"},
               {"op": "set_firmware", "dir": str(storage.real_home()), "env": "s3"}):
        _err(_upd(3, op), "invalid_args")


def test_set_firmware_refuses_home_even_with_platformio_ini(tmp_path):
    """HOME itself is never a firmware folder, even when it holds a platformio.ini."""
    _new()
    home = Path(os.environ["HOME"])
    (home / "platformio.ini").write_text("[env:s3]\n", encoding="utf-8")
    env = _err(_upd(1, {"op": "set_firmware", "dir": str(home), "env": "s3"}), "invalid_args")
    assert "home folder" in env["error"]["message"]
    sub = home / "fw"
    sub.mkdir()
    (sub / "platformio.ini").write_text("[env:s3]\n", encoding="utf-8")
    _ok(_upd(1, {"op": "set_firmware", "dir": str(sub), "env": "s3"}))


@pytest.mark.parametrize("op", [
    {"op": "set_detected"},
    {"op": "set_detected", "port": "sim://x", "mac": "zz:bb:cc:dd:ee:ff"},
    {"op": "set_detected", "port": "sim://x", "features": "Wi-Fi"},
    {"op": "set_detected", "port": "sim://x", "at": "2026-11-06"},
    {"op": "set_build"},
    {"op": "set_build", "ok": "true"},
    {"op": "set_build", "ok": True, "elf_sha256": "abc"},
    {"op": "set_build", "ok": True, "ram_pct": 101},
    {"op": "set_flash", "ok": True, "mac": "aa:bb"},
])
def test_bad_result_ops(op):
    _new()
    _err(_upd(1, op), "invalid_args")


def test_size_limits(monkeypatch):
    _new()
    monkeypatch.setattr(project, "MAX_NOTES", 2)
    _ok(_upd(1, {"op": "note", "text": "a"}, {"op": "note", "text": "b"}))
    _err(_upd(2, {"op": "note", "text": "c"}), "invalid_args")
    monkeypatch.setattr(project, "MAX_PROJECT_BYTES", 1500)
    _err(_upd(2, {"op": "add_calc", "calc": {"id": "big", "type": "led", "inputs": {"x": "y" * 1500}, "result": {}}}),
         "invalid_args")


# --------------------------------------------------------------------------------------------- atomic, flock, processes

def test_failed_replace_keeps_the_old_file_and_no_temp(monkeypatch):
    _new()
    before = _file().read_bytes()

    def broken_replace(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(project.os, "replace", broken_replace)
    res = _err(_upd(1, {"op": "note", "text": "x"}), "tool_failed")
    assert "OSError" in res["error"]["message"]
    assert _file().read_bytes() == before
    assert [x.name for x in project.path(PID).iterdir() if x.name.startswith(".project.")] == []


def test_lock_held_elsewhere_times_out(monkeypatch):
    _new()
    monkeypatch.setattr(project, "LOCK_TIMEOUT_S", 0.2)
    fd = os.open(project.path(PID) / ".lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)  # another open file description: flock conflicts even in this process
        res = _err(_upd(1, {"op": "note", "text": "x"}), "timeout")
        assert "locked" in res["error"]["message"]
        _err(project.create(PID, "again", "esp32s3"), "timeout")
    finally:
        os.close(fd)
    _ok(_upd(1, {"op": "note", "text": "x"}))


_WRITER = textwrap.dedent("""
    import json, sys, time
    from circuit_bench.bench_core import project
    name, n, go = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    while not __import__("os").path.exists(go):
        time.sleep(0.001)
    conflicts = 0
    for i in range(n):
        while True:
            rev = project.get("race")["result"]["rev"]
            res = project.update("race", rev, [{"op": "note", "text": f"{name}-{i}"},
                                               {"op": "add_parts", "parts": [{"ref": f"R{i + 1}", "kind": "resistor",
                                                                             "value": name}]}], by="agent")
            if res["ok"]:
                break
            if res["error"]["code"] != "project_conflict":
                print(json.dumps(res["error"]), file=sys.stderr)
                sys.exit(3)
            conflicts += 1
    print(conflicts)
""")


def test_two_processes_write_in_parallel(tmp_path):
    _new("race", title="Race")
    data = storage.data_dir()
    go = tmp_path / "go"
    env = dict(os.environ, PYTHONPATH=str(ROOT), CIRCUIT_BENCH_DATA_DIR=str(data))
    procs = [subprocess.Popen([sys.executable, "-c", _WRITER, name, "30", str(go)], env=env, cwd=ROOT,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for name in ("a", "b")]
    go.write_text("go", encoding="utf-8")
    outs = [p.communicate(timeout=120) for p in procs]
    assert [p.returncode for p in procs] == [0, 0], outs
    assert all(o[0].strip().isdigit() for o in outs)  # each writer prints its number of rev conflicts
    p = _ok(project.get("race"))["result"]["project"]
    assert p["rev"] == 61
    texts = [n["text"] for n in p["notes"]]
    assert sorted(texts) == sorted([f"a-{i}" for i in range(30)] + [f"b-{i}" for i in range(30)])
    assert [t for t in texts if t.startswith("a-")] == [f"a-{i}" for i in range(30)]  # each writer in order
    assert len(p["parts"]) == 30
    assert project.validate(p) == []
    assert [x.name for x in project.path("race").iterdir() if x.name.startswith(".project.")] == []


# --------------------------------------------------------------------------------------------- validate

def test_validate_reports_the_first_problem():
    p = _new()["result"]["project"]
    assert project.validate(p) == []
    cases = [
        (lambda q: q.pop("notes"), "missing field 'notes'"),
        (lambda q: q.update(extra=1), "unknown field 'extra'"),
        (lambda q: q.update(rev=0), "rev"),
        (lambda q: q.update(schema=True), "schema"),
        (lambda q: q["board"].update(chip="ESP32-S3"), "board.chip"),
        (lambda q: q["options"].update(logic_v=12), "options.logic_v"),
        (lambda q: q["assignments"].append({"role": "A", "mode": "out", "pin": 1, "net": None, "verdict": "great",
                                            "rule_ids": [], "updated_by": "ui"}), "verdict"),
        (lambda q: q["solder"].update(done=["0123456789"]), "solder.done"),
        (lambda q: q["firmware"].update(env="bad env"), "firmware.env"),
        (lambda q: q["debug"].update(last_panic={}), "debug.last_panic"),
    ]
    for mutate, needle in cases:
        q = json.loads(json.dumps(p))
        mutate(q)
        problems = project.validate(q)
        assert len(problems) == 1 and needle in problems[0], (needle, problems)
    assert project.validate([]) and project.validate(None)


def test_create_by_ui_is_reported_in_the_event(monkeypatch):
    seen = []
    from circuit_bench.bench_core import events
    monkeypatch.setattr(events, "emit", lambda ev, payload: seen.append((ev, payload)))
    assert project.create("ui-made", "From the bench", "esp32s3", by="ui")["ok"]
    assert seen and seen[-1][1]["by"] == "ui" and seen[-1][1]["changed"] == ["created"]
    assert project.create("bad-by", "x", "esp32s3", by="robot")["error"]["code"] == "invalid_args"


@pytest.mark.parametrize("op", [
    {"op": "set_detected", "port": "/dev/ttyACM0", "mac": "aa:bb:cc:dd:ee:ff"},
    {"op": "set_build", "ok": True, "elf_sha256": SHA},
    {"op": "set_flash", "ok": True, "port": "/dev/ttyACM0", "elf_sha256": SHA},
    {"op": "set_debug", "last_panic": None},
])
def test_result_ops_need_a_trusted_producer(op):
    """Only server-side producers (trusted=True) write results; a client cannot fake a detected board."""
    _new()
    for by in ("ui", "agent"):
        env = _err(_upd(1, op, by=by, trusted=False), "invalid_args")
        assert "written by Circuit Bench itself" in env["error"]["message"]
    env = _err(_upd(1, {"op": "note", "text": "x"}, op, trusted=False), "invalid_args")  # all or nothing
    assert project.get(PID)["result"]["rev"] == 1
    assert project.SERVER_OPS == {"set_detected", "set_build", "set_flash", "set_debug"}
    _ok(_upd(1, op))  # trusted
