"""Multi-pin address select: select.pins + comma-separated map keys."""
from __future__ import annotations

import modkit as mk
import mod_fixtures as fx

from circuit_bench.bench_core import modules

EXPANDER = {
    "id": "tst_expander", "title": "TST I/O expander", "category": "io.expander", "manufacturer": "Test", "kind": "ic",
    "source_ids": ["tst-sensor-ds"],
    "supplies": {"VDD": {"min": fx.F(1.8), "max": fx.F(5.5)}},
    "pins": [{"name": "SDA", "signal": "i2c_sda"}, {"name": "SCL", "signal": "i2c_scl"},
             {"name": "A1", "signal": "addr_select", "must_connect": True},
             {"name": "A0", "signal": "addr_select", "must_connect": True},
             {"name": "VDD", "signal": "supply"}, fx.GND],
    "interfaces": [{"type": "i2c", "addresses": fx.F(["0x20", "0x21", "0x22", "0x23"], "bit"), "default": "0x20",
                    "select": {"pins": ["A1", "A0"], "map": {"GND,GND": "0x20", "GND,VDD": "0x21",
                                                             "VDD,GND": "0x22", "VDD,VDD": "0x23"}}}],
}


def _report(*parts):
    return mk.run(catalog=fx.catalog(EXPANDER), electrical=fx.ESP, assignments=mk.i2c(), parts=list(parts))


def _conn(a1, a0):
    return {"SDA": "SDA0", "SCL": "SCL0", "A1": a1, "A0": a0, "VDD": "3V3", "GND": "GND"}


def test_multi_pin_select_resolves_the_address():
    rep = _report(mk.mod("U1", "tst_expander", _conn("GND", "3V3")), mk.mod("U2", "tst_expander", _conn("3V3", "GND")))
    devs = {d["ref"]: d["address"] for b in rep.result["buses"] for s in b["segments"] for d in s["devices"]}
    assert devs == {"U1": "0x21", "U2": "0x22"}
    assert "mod_address_conflict" not in mk.codes(rep)


def test_multi_pin_select_conflict_and_open_pin_default():
    rep = _report(mk.mod("U1", "tst_expander", _conn("GND", "GND")),
                  mk.mod("U2", "tst_expander", {"SDA": "SDA0", "SCL": "SCL0", "VDD": "3V3", "GND": "GND", "A1": "GND"}))
    devs = {d["ref"]: d["address"] for b in rep.result["buses"] for s in b["segments"] for d in s["devices"]}
    assert devs == {"U1": "0x20", "U2": "0x20"}  # U2: A0 open -> default
    assert "mod_address_conflict" in mk.codes(rep)


def test_validator_accepts_multi_pin_select():
    cat = modules.Catalog.from_entries([EXPANDER], sources=fx.SOURCES)
    assert [p for p in cat.problems if "select" in p] == []
