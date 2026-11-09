"""Module instances in the project model.

Optional part fields module/variant/conn/address/facts, options.rails/rail_limits, the ops add_module, connect,
set_rails; backward compatibility of old projects (byte-identical load/save) and loading a project whose module
left the catalog. The catalog is a fake behind ``project._catalog``.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from circuit_bench.bench_core import contracts, modspec, pins, project, sim
from circuit_bench.bench_core.contracts import BenchError

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "desktop-src" / "fixtures"
PID = "mod-bench"

BME280 = {
    "id": "bme280", "aliases": ["gy-bme280"], "kind": "module",
    "title": "BME280 humidity, pressure and temperature sensor",
    "pins": [{"name": n, "signal": s} for n, s in (("SDA", "i2c_sda"), ("SCL", "i2c_scl"), ("SDO", "addr_select"),
                                                    ("CSB", "mode_select"), ("VDD", "supply"), ("VDDIO", "supply"),
                                                    ("GND", "gnd"))],
    "interfaces": [{"type": "i2c", "addresses": {"value": ["0x76", "0x77"], "page": 32, "evidence": "x",
                                                 "source_id": "mod-env-bme280-ds"}, "default": "0x76"}],
    "variants": [],
}
SHT40 = {
    "id": "sht40", "aliases": [], "kind": "ic", "title": "SHT40 humidity and temperature sensor",
    "pins": [{"name": n, "signal": s} for n, s in (("SDA", "i2c_sda"), ("SCL", "i2c_scl"), ("VDD", "supply"),
                                                    ("VSS", "gnd"))],
    "interfaces": [{"type": "i2c", "addresses": ["0x44"], "default": "0x44"}],
    "variants": [{"id": "bd1b", "title": "SHT40-BD1B",
                  "overrides": {"interfaces": [{"type": "i2c", "addresses": ["0x45"], "default": "0x45"}]}}],
}
DRV8833 = {
    "id": "drv8833", "aliases": ["drv8833-board"], "kind": "module", "title": "DRV8833, dual H-bridge motor driver",
    "pins": [{"name": n, "signal": "digital_in"} for n in ("AIN1", "AIN2", "BIN1", "BIN2")]
    + [{"name": "VM", "signal": "supply"}, {"name": "GND", "signal": "gnd"}],
    "interfaces": [{"type": "pwm"}],
}


class FakeCatalog:
    """has/resolve_id/get like modules.Catalog (variant overrides flat per top-level key)."""

    def __init__(self, *entries):
        self.entries = {e["id"]: e for e in entries}
        self.alias = {a: e["id"] for e in entries for a in e.get("aliases", [])}
        self.calls = 0

    def has(self, key):
        self.calls += 1
        return key in self.entries or key in self.alias

    def resolve_id(self, key):
        if not self.has(key):
            raise BenchError("invalid_args", f"unknown module {key!r}", project.MODULE_HINT)
        return self.alias.get(key, key)

    def get(self, key, variant=None):
        entry = copy.deepcopy(self.entries[self.resolve_id(key)])
        if variant is not None:
            v = next(v for v in entry["variants"] if v["id"] == variant)
            entry.update(copy.deepcopy(v["overrides"]))
        return entry


@pytest.fixture
def cat(monkeypatch):
    fake = FakeCatalog(BME280, SHT40, DRV8833)
    monkeypatch.setattr(project, "_catalog", lambda: fake)
    return fake


@pytest.fixture
def proj(cat):
    res = project.create(PID, "Module bench", "esp32s3", "n16r8", "esp32-s3-devkitc-1")
    assert res["ok"], res
    return res["result"]["project"]


def _rev():
    return project.get(PID)["result"]["rev"]


def _up(*ops, trusted=False, rev=None):
    """An update as a client (PATCH /projects: trusted=False) at the current rev."""
    return project.update(PID, _rev() if rev is None else rev, list(ops), by="ui", trusted=trusted)


def _ok(*ops, **kw):
    res = _up(*ops, **kw)
    assert res["ok"], res["error"]
    assert contracts.validate_envelope(res) == []
    assert project.validate(res["result"]["project"]) == []
    return res["result"]["project"]


def _bad(*ops, code="invalid_args", contains=None):
    before = _rev()
    res = _up(*ops)
    assert res["ok"] is False, res["summary"]
    assert res["error"]["code"] == code, res["error"]
    assert contracts.validate_envelope(res) == []
    if contains:
        assert contains in res["error"]["message"] + " " + (res["error"].get("hint") or ""), res["error"]
    assert _rev() == before  # all or nothing
    return res["error"]


def _part(p, ref):
    return next(x for x in p["parts"] if x["ref"] == ref)


def _file(pid=PID):
    return project.path(pid) / "project.json"


# --------------------------------------------------------------------------------------------- contract

def test_ops_contract():
    assert set(modspec.MODULE_OPS) <= set(project.OPS)
    assert project.OPS["add_module"] == ("module", "variant", "ref", "conn", "address", "facts", "qty")
    assert project.OPS["connect"] == ("ref", "conn", "address", "facts", "variant", "qty")  # connect edits in place
    assert project.OPS["set_rails"] == ("rails", "rail_limits")
    assert not set(modspec.MODULE_OPS) & project.SERVER_OPS  # a client may send them
    assert set(modspec.MODULE_OPS) <= project._VERDICT_OPS
    assert project.SCHEMA == 1 and "rails" not in project.TOP_KEYS
    assert project.PART_ALL_FIELDS == project.PART_FIELDS + modspec.PART_MODULE_FIELDS


def test_every_module_op_once(proj):
    rev = proj["rev"]
    for op, changed in [
        ({"op": "add_module", "module": "gy-bme280", "conn": {"SDA": "SDA0"}}, ["parts"]),
        ({"op": "connect", "ref": "u1", "conn": {"SCL": "SCL0"}}, ["parts"]),
        ({"op": "set_rails", "rails": {"VMOT": 12}}, ["options"]),
    ]:
        res = project.update(PID, rev, [op], by="ui")
        assert res["ok"], res["error"]
        assert res["result"]["changed"] == changed and res["result"]["rev"] == rev + 1
        rev += 1
    p = project.get(PID)["result"]["project"]
    assert _part(p, "U1")["conn"] == {"SDA": "SDA0", "SCL": "SCL0"} and p["options"]["rails"] == {"VMOT": 12}


# --------------------------------------------------------------------------------------------- add_module

def test_add_module_alias_ref_kind_value(proj, cat):
    p = _ok({"op": "add_module", "module": "GY-BME280"})
    assert p["parts"] == [{"ref": "U1", "kind": "module", "value": "BME280", "module": "bme280"}]
    p = _ok({"op": "add_module", "module": "sht40", "qty": 2}, {"op": "add_module", "module": "drv8833-board"})
    assert [(x["ref"], x["kind"], x["value"], x["module"]) for x in p["parts"]] == [
        ("U1", "module", "BME280", "bme280"), ("U2", "ic", "SHT40", "sht40"), ("U3", "module", "DRV8833", "drv8833")]
    assert _part(p, "U2")["qty"] == 2 and "package" not in _part(p, "U2")
    stored = json.loads(_file().read_text(encoding="utf-8"))
    assert stored["parts"][0] == {"ref": "U1", "kind": "module", "value": "BME280", "module": "bme280"}


def test_add_module_ref_rules(proj):
    p = _ok({"op": "add_parts", "parts": [{"ref": "U7", "kind": "ic", "value": "NE555"},
                                         {"ref": "U3A", "kind": "ic", "value": "LM358"}]})
    p = _ok({"op": "add_module", "module": "bme280"})
    assert p["parts"][-1]["ref"] == "U8"  # one above the highest U<n>; U3A is not a U<n>
    p = _ok({"op": "add_module", "module": "bme280", "ref": " ic1 "})
    assert p["parts"][-1]["ref"] == "IC1"
    _bad({"op": "add_module", "module": "bme280", "ref": "U7"}, contains="already used")
    _bad({"op": "add_module", "module": "bme280", "ref": "IC1"}, contains="already used")
    _bad({"op": "add_module", "module": "bme280", "ref": "7U"}, contains="bad reference")
    _bad({"op": "add_module", "module": "bme280", "ref": 5})
    # two in one update: the second sees the first
    p = _ok({"op": "add_module", "module": "sht40"}, {"op": "add_module", "module": "sht40"})
    assert [x["ref"] for x in p["parts"][-2:]] == ["U9", "U10"]


def test_add_module_unknown_and_bad_fields(proj):
    err = _bad({"op": "add_module", "module": "bmx999"}, contains="unknown module")
    assert err["hint"] == "list modules with bench_pins action=modules"
    for module in (None, "", "  ", 5, "x" * 65):
        _bad({"op": "add_module", "module": module})
    _bad({"op": "add_module", "module": "bme280", "package": "LGA"}, contains="unknown field")
    _bad({"op": "add_module", "module": "bme280", "qty": 0})
    _bad({"op": "add_module", "module": "bme280", "qty": True})


def test_add_module_variant(proj):
    p = _ok({"op": "add_module", "module": "sht40", "variant": "BD1B", "address": "0x45"})
    assert p["parts"][0] == {"ref": "U1", "kind": "ic", "value": "SHT40", "module": "sht40", "variant": "bd1b",
                             "address": "0x45"}
    _bad({"op": "add_module", "module": "sht40", "variant": "bd1b", "address": "0x44"}, contains="addresses: 0x45")
    _bad({"op": "add_module", "module": "sht40", "variant": "ad9z"}, contains="variants: bd1b")
    _bad({"op": "add_module", "module": "bme280", "variant": "x"}, contains="has no variants")
    _bad({"op": "add_module", "module": "sht40", "variant": 3})
    p = _ok({"op": "add_module", "module": "sht40", "variant": None})  # null = no variant
    assert "variant" not in p["parts"][-1]


def test_conn_validation(proj):
    p = _ok({"op": "add_module", "module": "bme280",
             "conn": {"SDA": "SDA0", "SCL": "SCL0", "SDO": "GND", "VDD": "3V3", "GND": "GND", "CSB": "GPIO10"}})
    assert p["parts"][0]["conn"] == {"SDA": "SDA0", "SCL": "SCL0", "SDO": "GND", "VDD": "3V3", "GND": "GND",
                                     "CSB": "GPIO10"}
    _bad({"op": "add_module", "module": "bme280", "conn": {"MISO": "X"}}, contains="has no pin 'MISO'")
    _bad({"op": "add_module", "module": "bme280", "conn": {"sda": "X"}}, contains="pins: SDA, SCL")  # exact names
    _bad({"op": "add_module", "module": "bme280", "conn": {"SDA": "bad net"}}, contains="net:")
    _bad({"op": "add_module", "module": "bme280", "conn": {"SDA": "N" * 33}})
    _bad({"op": "add_module", "module": "bme280", "conn": {"SDA": None}})  # null only in connect
    _bad({"op": "add_module", "module": "bme280", "conn": ["SDA"]})
    p = _ok({"op": "add_module", "module": "bme280", "conn": {}})  # empty: left out
    assert "conn" not in p["parts"][-1]


def test_conn_limit_and_plain_parts(proj):
    many = {f"P{i}": f"N{i}" for i in range(modspec.MAX_CONN)}
    p = _ok({"op": "add_parts", "parts": [{"ref": "J1", "kind": "connector", "value": "2x24 header", "conn": many}]})
    assert len(p["parts"][0]["conn"]) == modspec.MAX_CONN
    _bad({"op": "add_parts", "parts": [{"ref": "J2", "kind": "connector", "value": "x",
                                        "conn": {**many, "X": "Y"}}]}, contains=f"at most {modspec.MAX_CONN}")
    _bad({"op": "connect", "ref": "J1", "conn": {"EXTRA": "Y"}}, contains=f"more than {modspec.MAX_CONN}")
    p = _ok({"op": "add_parts", "parts": [{"ref": "R3", "kind": "resistor", "value": "4.7 kΩ",
                                           "conn": {"1": "SDA0", "2": "3V3"}}]})
    assert _part(p, "R3") == {"ref": "R3", "kind": "resistor", "value": "4.7 kΩ", "conn": {"1": "SDA0", "2": "3V3"}}
    for pin in ("pin 1", "", "P" * 17, "a/b"):
        _bad({"op": "add_parts", "parts": [{"ref": "R4", "kind": "resistor", "value": "1k", "conn": {pin: "X"}}]})
    for field, value in (("variant", "x"), ("address", "0x76"), ("facts", {"regulator": "none"})):
        _bad({"op": "add_parts", "parts": [{"ref": "R5", "kind": "resistor", "value": "1k", field: value}]},
             contains="give module too")


def test_add_parts_with_module_fields_goes_through_the_catalog(proj):
    p = _ok({"op": "add_parts", "parts": [{"ref": "U4", "kind": "module", "value": "BME280 board",
                                           "module": "gy-bme280", "conn": {"SDA": "SDA0"}, "address": "0x77"}]})
    assert p["parts"][0] == {"ref": "U4", "kind": "module", "value": "BME280 board", "module": "bme280",
                             "conn": {"SDA": "SDA0"}, "address": "0x77"}
    _bad({"op": "add_parts", "parts": [{"ref": "U5", "kind": "module", "value": "x", "module": "nope"}]},
         contains="unknown module")


def test_address(proj):
    for given, stored in (("0x77", "0x77"), ("0X76", "0x76"), (" 0x77 ", "0x77"), (0x76, "0x76")):
        p = _ok({"op": "add_module", "module": "bme280", "address": given})
        assert p["parts"][-1]["address"] == stored
    for bad in ("0x78", "0x1ff", "77", "", True, 300, -1):
        _bad({"op": "add_module", "module": "bme280", "address": bad})
    _bad({"op": "add_module", "module": "drv8833", "address": "0x40"}, contains="has no I²C address")


def test_facts(proj):
    facts = {"onboard": ["pullups", "decoupling"], "mains": False, "level_shifter": False, "pullups_to": "3V3",
             "pullups": "4.7 kΩ", "regulator": "3v3", "i_max": "2.2A"}
    p = _ok({"op": "add_module", "module": "bme280", "facts": facts})
    assert p["parts"][-1]["facts"] == {"regulator": "3V3", "pullups": "4.7 kΩ", "pullups_to": "3V3",
                                       "level_shifter": False, "mains": False, "onboard": ["decoupling", "pullups"],
                                       "i_max": 2.2}
    assert list(p["parts"][-1]["facts"]) == list(modspec.FACT_KEYS)  # stored order
    for pullups, stored in (("10k", "10k"), (" 4k7 ", "4k7"), ("NONE", "none"), ("Unknown", "unknown"),
                            ("10 kohm", "10 kohm"), ("1M", "1M")):
        p = _ok({"op": "add_module", "module": "bme280", "facts": {"pullups": pullups}})
        assert p["parts"][-1]["facts"] == {"pullups": stored}
    for bad in ({"pullup": "10k"}, {"regulator": "5V"}, {"regulator": None}, {"pullups": "3V3"}, {"pullups": "0"},
                {"pullups": "abc"}, {"pullups": "20M"}, {"pullups": 10000}, {"pullups_to": "bad net"},
                {"level_shifter": "yes"}, ["regulator"]):
        _bad({"op": "add_module", "module": "bme280", "facts": bad})
    p = _ok({"op": "add_module", "module": "bme280", "facts": {}})
    assert "facts" not in p["parts"][-1]


# --------------------------------------------------------------------------------------------- connect

def test_connect_merge_delete(proj):
    _ok({"op": "add_module", "module": "bme280", "conn": {"SDA": "SDA0", "VDD": "3V3"}, "address": "0x76"})
    p = _ok({"op": "connect", "ref": " u1 ", "conn": {"SCL": "SCL0", "VDD": "5V"}})
    assert _part(p, "U1")["conn"] == {"SDA": "SDA0", "VDD": "5V", "SCL": "SCL0"}
    p = _ok({"op": "connect", "ref": "U1", "conn": {"VDD": None, "SDO": None}})  # SDO not connected: no change
    assert _part(p, "U1")["conn"] == {"SDA": "SDA0", "SCL": "SCL0"}
    p = _ok({"op": "connect", "ref": "U1", "conn": {"SDA": None, "SCL": None}})
    assert _part(p, "U1") == {"ref": "U1", "kind": "module", "value": "BME280", "module": "bme280",
                              "address": "0x76"}  # no empty conn left behind
    p = _ok({"op": "connect", "ref": "U1", "conn": {"SDA": "SDA1"}})
    assert list(_part(p, "U1")) == ["ref", "kind", "value", "module", "conn", "address"]  # stored key order
    rev = _rev()
    res = _up({"op": "connect", "ref": "U1", "conn": {"SDA": "SDA1"}})  # same again: nothing written
    assert res["ok"] and res["result"]["changed"] == [] and res["result"]["rev"] == rev


def test_connect_errors(proj):
    _ok({"op": "add_module", "module": "bme280"})
    _bad({"op": "connect", "ref": "U9", "conn": {"SDA": "X"}}, contains="no part U9")
    _bad({"op": "connect", "ref": "U1", "conn": {}})
    _bad({"op": "connect", "ref": "U1", "conn": None})
    _bad({"op": "connect", "ref": "U1"})
    _bad({"op": "connect", "ref": "U1", "conn": {"XYZ": "X"}}, contains="has no pin")
    _bad({"op": "connect", "ref": "U1", "conn": {"SDA": "a b"}})
    _bad({"op": "connect", "ref": "U1", "conn": {"SDA": "X"}, "module": "bme280"}, contains="unknown field")
    p = _ok({"op": "connect", "ref": "U1", "conn": {"SDA": "X"}, "address": "0x77"})  # in place
    assert _part(p, "U1")["address"] == "0x77"


def test_connect_plain_part(proj):
    _ok({"op": "add_parts", "parts": [{"ref": "R3", "kind": "resistor", "value": "4.7 kΩ"}]})
    p = _ok({"op": "connect", "ref": "r3", "conn": {"1": "SDA0", "2": "3V3"}})
    assert _part(p, "R3") == {"ref": "R3", "kind": "resistor", "value": "4.7 kΩ", "conn": {"1": "SDA0", "2": "3V3"}}
    _bad({"op": "connect", "ref": "R3", "conn": {"a b": "X"}}, contains="pin names")


def test_set_part_by_replace_and_remove(proj):
    """address/facts change by remove_parts + add_module with the same ref in one update."""
    _ok({"op": "add_module", "module": "bme280", "address": "0x76", "conn": {"SDA": "SDA0"}})
    p = _ok({"op": "remove_parts", "refs": ["U1"]},
            {"op": "add_module", "module": "bme280", "ref": "U1", "address": "0x77", "facts": {"regulator": "none"}})
    assert p["parts"] == [{"ref": "U1", "kind": "module", "value": "BME280", "module": "bme280", "address": "0x77",
                           "facts": {"regulator": "none"}}]


# --------------------------------------------------------------------------------------------- set_rails

def test_set_rails(proj):
    p = _ok({"op": "set_rails", "rails": {"VMOT": 12, "VBAT": "3.7 V", "1V8": 1.8}, "rail_limits": {"3V3": 0.5}})
    assert p["options"] == {"wifi": True, "framework": "arduino", "logic_v": 3.3,
                            "rails": {"VMOT": 12, "VBAT": 3.7, "1V8": 1.8}, "rail_limits": {"3V3": 0.5}}
    p = _ok({"op": "set_rails", "rail_limits": {"VMOT": "2 A", "5V": 1}})  # rails stay
    assert p["options"]["rails"] == {"VMOT": 12, "VBAT": 3.7, "1V8": 1.8}
    assert p["options"]["rail_limits"] == {"VMOT": 2.0, "5V": 1}
    p = _ok({"op": "set_rails", "rails": {"VBAT": 4.2, "VMOT": None}})  # replaced; the VMOT limit goes with it
    assert p["options"]["rails"] == {"VBAT": 4.2} and p["options"]["rail_limits"] == {"5V": 1}
    p = _ok({"op": "set_board", "wifi": False})  # other ops keep them
    assert p["options"]["rails"] == {"VBAT": 4.2} and p["options"]["wifi"] is False
    p = _ok({"op": "set_rails", "rails": None, "rail_limits": {}})
    assert p["options"] == {"wifi": False, "framework": "arduino", "logic_v": 3.3}
    assert json.loads(_file().read_text(encoding="utf-8"))["options"] == p["options"]


@pytest.mark.parametrize("op, contains", [
    ({}, "give rails"),
    ({"rails": {"GND": 0.1}}, "fixed rail"),
    ({"rails": {"3v3": 3.3}}, "fixed rail"),
    ({"rails": {"5V": 5}}, "fixed rail"),
    ({"rails": {"VMOT": 0}}, "above 0"),
    ({"rails": {"VMOT": -5}}, "expected"),
    ({"rails": {"VMOT": 60.5}}, "expected"),
    ({"rails": {"VMOT": "230 V"}}, "expected"),
    ({"rails": {"VMOT": "2 A"}}, "expected a value in V"),
    ({"rails": {"VMOT": True}}, "expected"),
    ({"rails": {"bad net": 5}}, "net:"),
    ({"rails": {f"R{i}": 1 for i in range(17)}}, "at most 16"),
    ({"rails": [12]}, "expected an object"),
    ({"rail_limits": {"VMOT": 1}}, "not a rail"),
    ({"rail_limits": {"GND": 1}}, "not a rail"),
    ({"rail_limits": {"3V3": 10.5}}, "expected"),
    ({"rail_limits": {"3V3": 0}}, "above 0"),
    ({"rail_limits": {"3V3": "500 mV"}}, "expected a value in A"),
    ({"other": 1}, "unknown field"),
])
def test_set_rails_errors(proj, op, contains):
    _bad({"op": "set_rails", **op}, contains=contains)


def test_rail_bounds(proj):
    p = _ok({"op": "set_rails", "rails": {"VMAX": modspec.MAX_RAIL_V}, "rail_limits": {"VMAX": project.MAX_RAIL_A}})
    assert p["options"]["rails"] == {"VMAX": 60.0} and p["options"]["rail_limits"] == {"VMAX": 10.0}


# --------------------------------------------------------------------------------------------- rev, verdicts

def test_conflict_and_all_or_nothing(proj):
    rev = _rev()
    res = project.update(PID, rev + 3, [{"op": "add_module", "module": "bme280"}], by="ui")
    assert res["error"]["code"] == "project_conflict" and res["result"] == {"rev": rev}
    _bad({"op": "add_module", "module": "bme280"}, {"op": "set_rails", "rails": {"VMOT": 99}})
    assert project.get(PID)["result"]["project"]["parts"] == []


def test_module_ops_recompute_verdicts_without_storing_module_findings(proj, monkeypatch):
    _ok({"op": "assign", "role": "SDA", "mode": "i2c_sda", "pin": 8, "net": "SDA0"})
    calls = []
    real = pins.check

    def spy(*args, **kw):
        calls.append(kw)
        return real(*args, **kw)

    monkeypatch.setattr(pins, "check", spy)
    before = project.get(PID)["result"]["project"]["assignments"]
    for op in ({"op": "add_module", "module": "bme280", "conn": {"SDA": "SDA0"}},
               {"op": "connect", "ref": "U1", "conn": {"SCL": "SCL0"}},
               {"op": "set_rails", "rails": {"VBAT": 3.7}}):
        n = len(calls)
        p = _ok(op)
        assert len(calls) == n + 1, op  # the server recomputed the verdicts
        assert "parts" not in calls[-1]  # pin verdicts only; module findings are computed on read, never stored
        assert p["assignments"] == before
    _ok({"op": "note", "text": "x"})
    assert len(calls) == 3  # other ops do not


def test_catalog_unavailable_is_a_server_fault(proj, monkeypatch):
    def broken():
        raise NotImplementedError

    monkeypatch.setattr(project, "_catalog", broken)
    _bad({"op": "add_module", "module": "bme280"}, code="tool_failed", contains="module catalog unavailable")
    p = _ok({"op": "add_parts", "parts": [{"ref": "R1", "kind": "resistor", "value": "1k", "conn": {"1": "A"}}]})
    assert p["parts"][0]["conn"] == {"1": "A"}  # plain parts need no catalog
    p = _ok({"op": "set_rails", "rails": {"VMOT": 12}})
    assert p["options"]["rails"] == {"VMOT": 12}


def test_max_parts(proj):
    _ok({"op": "add_parts", "parts": [{"ref": f"R{i}", "kind": "resistor", "value": "1k"}
                                      for i in range(1, project.MAX_PARTS + 1)]})
    _bad({"op": "add_module", "module": "bme280"}, contains=f"at most {project.MAX_PARTS} parts")


def test_size_of_a_full_module_project(proj):
    conn = {p["name"]: f"NET_{p['name']}_LONGER_NAME" for p in BME280["pins"]}
    ops = [{"op": "add_parts", "parts": [{"ref": f"J{i}", "kind": "connector", "value": "x" * 60,
                                          "conn": {f"P{k}": "N" * 32 for k in range(modspec.MAX_CONN)}}
                                         for i in range(1, 150)]}]
    ops += [{"op": "add_module", "module": "bme280", "conn": conn, "address": "0x77",
             "facts": {"regulator": "unknown", "pullups": "10k", "pullups_to": "3V3", "level_shifter": True}}] * 40
    p = _ok(*ops)
    assert len(p["parts"]) == 189
    assert len(_file().read_bytes()) < project.MAX_PROJECT_BYTES


# --------------------------------------------------------------------------------------------- loading

def _store(p, pid=None):
    """Write a project object as the store does (the same bytes _write produces)."""
    pdir = project.path(pid or p["id"])
    pdir.mkdir(mode=0o700, exist_ok=True)
    text = json.dumps(p, ensure_ascii=False, indent=1) + "\n"
    (pdir / "project.json").write_text(text, encoding="utf-8")
    return text


def test_unknown_module_at_load_does_not_damage(proj, monkeypatch):
    _ok({"op": "add_module", "module": "bme280", "variant": None, "conn": {"SDA": "SDA0"}, "address": "0x77",
         "facts": {"pullups": "10k"}})
    monkeypatch.setattr(project, "_catalog", lambda: FakeCatalog(SHT40))  # bme280 left the catalog
    got = project.get(PID)
    assert got["ok"], got["error"]
    assert got["result"]["project"]["parts"][0]["module"] == "bme280"
    assert [e["id"] for e in project.list()["result"]["projects"]] == [PID]
    p = _ok({"op": "note", "text": "still writable"})
    assert p["parts"][0]["module"] == "bme280"
    p = _ok({"op": "connect", "ref": "U1", "conn": {"SDA": None}})  # removing needs no catalog
    assert "conn" not in p["parts"][0]
    _bad({"op": "connect", "ref": "U1", "conn": {"SCL": "SCL0"}}, contains="unknown module")

    def broken():
        raise RuntimeError("no catalog")

    monkeypatch.setattr(project, "_catalog", broken)
    assert project.get(PID)["ok"]  # reading never touches the catalog


def test_stored_form_of_module_fields(proj):
    base = copy.deepcopy(project.get(PID)["result"]["project"])
    good = {"ref": "U1", "kind": "module", "value": "BME280", "module": "some_future_mod", "variant": "v2",
            "conn": {"VIN+": "VBAT", "SDA": "SDA0"}, "address": "0x29",
            "facts": {"regulator": "none", "level_shifter": True}}
    p = copy.deepcopy(base)
    p["parts"] = [good]
    p["options"] = {**p["options"], "rails": {"VBAT": 3.7}, "rail_limits": {"VBAT": 0.5}}
    assert project.validate(p) == []
    bad_parts = [
        {**good, "module": "BME 280"}, {**good, "module": None}, {**good, "conn": {}}, {**good, "conn": {"SDA": None}},
        {**good, "address": "0x80"}, {**good, "address": "0X29"}, {**good, "facts": {}},
        {**good, "facts": {"regulator": "maybe"}}, {**good, "variant": None},
        {k: v for k, v in good.items() if k != "module"}, {**good, "unknown": 1},
        {"ref": "R1", "kind": "resistor", "value": "1k", "conn": {"pin 1": "X"}},
    ]
    for part in bad_parts:
        q = copy.deepcopy(base)
        q["parts"] = [part]
        assert project.validate(q) != [], part
    bad_options = [{"rails": {}}, {"rails": None}, {"rails": {"GND": 1}}, {"rails": {"V": "12 V"}},
                   {"rail_limits": {"VX": 1}}, {"rails": {"VX": 1}, "rail_limits": {"VX": 11}}, {"extra": 1}]
    for extra in bad_options:
        q = copy.deepcopy(base)
        q["options"] = {**q["options"], **extra}
        assert project.validate(q) != [], extra
    # a damaged file is project_damaged, not a crash
    q = copy.deepcopy(base)
    q["parts"] = [{**good, "conn": {}}]
    _store(q)
    assert project.get(PID)["error"]["code"] == "project_damaged"


# --------------------------------------------------------------------------------------------- backward compatibility

def _fixture_project():
    return json.loads((FIXTURES / "project.laser-trigger.json").read_text(encoding="utf-8"))["result"]["project"]


def test_old_fixture_project_loads_and_saves_byte_identical(monkeypatch):
    def broken():
        raise AssertionError("an old project must not need the catalog")

    monkeypatch.setattr(project, "_catalog", broken)
    fx = _fixture_project()
    assert project.validate(fx) == []
    for i, part in enumerate(fx["parts"]):
        assert project._part(part, f"parts[{i}]") == part  # no fields added, no null fields
    text = _store(fx)
    got = project.get(fx["id"])
    assert got["ok"], got["error"]
    assert got["result"]["project"] == fx
    project._write(project.path(fx["id"]), got["result"]["project"])
    assert _file(fx["id"]).read_text(encoding="utf-8") == text
    # an update that changes nothing writes nothing
    res = project.update(fx["id"], fx["rev"], [{"op": "connect", "ref": fx["parts"][0]["ref"],
                                                "conn": {"1": None}}], by="ui")
    assert res["ok"] and res["result"]["changed"] == [] and _file(fx["id"]).read_text(encoding="utf-8") == text
    # a real update keeps every other section byte-identical
    res = project.update(fx["id"], fx["rev"], [{"op": "note", "text": "x"}], by="ui")
    assert res["ok"] and res["result"]["changed"] == ["notes"]
    new = json.loads(_file(fx["id"]).read_text(encoding="utf-8"))
    for key in ("board", "options", "assignments", "parts", "calcs", "circuits", "solder", "firmware", "debug"):
        assert json.dumps(new[key], ensure_ascii=False) == json.dumps(fx[key], ensure_ascii=False), key


def test_demo_project_round_trip(monkeypatch):
    monkeypatch.setattr(project, "_catalog", lambda: (_ for _ in ()).throw(AssertionError("no catalog needed")))
    env = sim.demo()
    assert env["ok"], env.get("error")
    pid = env["result"]["project"]["id"] if "project" in env["result"] else "laser-trigger"
    text = _file(pid).read_text(encoding="utf-8")
    p = project.get(pid)["result"]["project"]
    assert p["options"] == project.DEFAULT_OPTIONS | {"wifi": p["options"]["wifi"]}
    assert all(set(x) <= set(project.PART_FIELDS) for x in p["parts"])
    project._write(project.path(pid), p)
    assert _file(pid).read_text(encoding="utf-8") == text
