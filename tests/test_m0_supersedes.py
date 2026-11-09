"""Finding.supersedes: one cause gives one warning. A failed finding folds the
covered rule's failed findings on a shared ref (strongest severity, both sources); a passed finding drops them to
info; findings on other refs stay untouched."""
from __future__ import annotations

import mod_fixtures as fx
import modkit as k
import pytest

from circuit_bench.bench_core import modcheck

BUS = k.i2c()
I2C = {"SDA": "SDA0", "SCL": "SCL0"}
GEN, FAM = "mod.tstgen.thing", "mod.tstfam.thing"


@pytest.fixture
def rules():
    made = {}

    def make(gen, fam):
        modcheck.rule(GEN)(lambda ctx: list(gen))
        modcheck.rule(FAM)(lambda ctx: list(fam))
        made.update({GEN: 1, FAM: 1})

    yield make
    for rid in made:
        modcheck.unregister(rid)


def _run():
    parts = [k.mod("U1", "tst_sensor", {**I2C, "VDD": "3V3", "SDO": "GND"})]
    rep = k.run(catalog=fx.catalog(), electrical=fx.ESP, assignments=BUS, parts=parts, only=(GEN, FAM))
    assert rep is not None
    return rep


def F(rid, status, sev, refs, sup=(), src=()):
    return modcheck.Finding(rid, status, sev, f"{rid} says", list(refs), list(src), tuple(sup))


def test_failed_family_finding_folds_the_generic_one_and_takes_the_stronger_severity(rules):
    rules([F(GEN, "failed", "danger", ["U1"], src=["s-gen"])],
          [F(FAM, "failed", "caution", ["U1", "GPIO8"], sup=[GEN], src=["s-fam"])])
    rep = _run()
    assert [(w["code"], w["severity"]) for w in rep.warnings] == [("mod_tstfam_thing", "danger")]
    assert set(rep.warnings[0]["source_ids"]) == {"s-gen", "s-fam"}
    gen = [c for c in rep.checks if c["id"] == modcheck.check_id(GEN)][0]
    assert gen["status"] == "failed" and gen["detail"] == "covered by mod_tstfam_thing"


def test_passed_finding_drops_the_covered_one_to_info(rules):
    rules([F(GEN, "failed", "danger", ["U1"])], [F(FAM, "passed", None, ["U1"], sup=[GEN])])
    rep = _run()
    assert [(w["code"], w["severity"]) for w in rep.warnings] == [("mod_tstgen_thing", "info")]


def test_other_refs_and_unrelated_rules_stay(rules):
    rules([F(GEN, "failed", "danger", ["U2"]), F(GEN, "failed", "caution", ["U1"])],
          [F(FAM, "failed", "caution", ["U1"], sup=["mod.other"])])
    rep = _run()
    assert sorted((w["code"], w["severity"]) for w in rep.warnings) == [
        ("mod_tstfam_thing", "caution"), ("mod_tstgen_thing", "caution"), ("mod_tstgen_thing", "danger")]


def test_a_rule_cannot_supersede_itself(rules):
    rules([], [F(FAM, "failed", "caution", ["U1"], sup=[FAM]), F(FAM, "failed", "danger", ["U1"])])
    rep = _run()
    assert sorted(w["severity"] for w in rep.warnings) == ["caution", "danger"]


def test_not_checked_folds_the_same_open_question(rules):
    rules([F(GEN, "not_checked", "info", ["U1"])], [F(FAM, "not_checked", "info", ["U1"], sup=[GEN])])
    rep = _run()
    assert [w["code"] for w in rep.warnings] == ["mod_tstfam_thing"]
