"""facts.onboard: user-confirmed board parts satisfy requires[] and silence an open RC reset."""
from __future__ import annotations

import modkit as k

from circuit_bench.bench_core import modcheck

BUS = k.i2c()


def _run(facts):
    parts = [k.mod("U1", "ssd1306", {"SDA": "SDA0", "SCL": "SCL0", "VDD": "3V3", "GND": "GND", "SA0": "GND"},
                   facts=facts)]
    rep = modcheck.run(**k.project(assignments=BUS, parts=parts))
    assert rep is not None
    return rep


def _hard(rep, rid):
    return [f for f in rep.findings if f.rule_id == rid and f.status == "failed" and f.severity != "info"]


def test_without_facts_pullups_and_reset_are_reported():
    rep = _run({})
    assert _hard(rep, "mod.required_parts")
    assert [f for f in _hard(rep, "mod.unconnected") if "RES" in f.message]


def test_onboard_pullups_decoupling_and_reset_rc_count_as_present():
    rep = _run({"onboard": ["decoupling", "pullups", "reset_rc"]})
    assert not _hard(rep, "mod.required_parts")
    assert not [f for f in _hard(rep, "mod.unconnected") if "RES" in f.message]
