"""Mains voltage and lithium cells in the solder text rules.

The mains pattern is a product rule (low voltage only), not a sourced fact: an AC marker (VAC, V AC, V~,
AC … V) from 50 V, bare 220–249 V as before, the words mains/Netz/Netzspannung. Bare 250/400 V without an AC marker
is the rated voltage of a capacitor and stays without a hit.
"""
import json
import re
from pathlib import Path

import pytest

from circuit_bench.bench_core import solder

RULES = json.loads((Path(__file__).resolve().parent.parent / "circuit_bench" / "data" / "solder" / "rules.json")
                   .read_text(encoding="utf-8"))
TEXT_RULES = {r["code"]: re.compile(r["pattern"], re.I) for r in RULES["text_rules"]}

MAINS_POSITIVE = ["230VAC", "10A 250VAC", "AC 230V", "230 V~", "120 V AC", "400VAC", "Netzspannung", "mains", "240 v",
                  # old cases and close variants
                  "230 V relay", "Netz", "220V", "110 V AC", "AC230V", "100-240VAC", "250 V AC", "50VAC"]
MAINS_NEGATIVE = ["Netzteil 5 V", "24VAC", "12V", "3V3", "100uF 400V", "230k", "2.30V",
                  # more negatives: capacitor ratings, low AC, values near the limit
                  "470uF 250V", "48VAC", "12 V AC", "AC 24V", "1230V", "2.40 V", "0.230V"]
LITHIUM_NEW = ["21700 cell", "26650", "16340 holder", "10440", "CR123", "CR123A", "LiFePO4 pack", "LiFePO"]


@pytest.mark.parametrize("text", MAINS_POSITIVE)
def test_mains_pattern_hits(text):
    assert TEXT_RULES["low_voltage_only"].search(text), text


@pytest.mark.parametrize("text", MAINS_NEGATIVE)
def test_mains_pattern_misses(text):
    assert not TEXT_RULES["low_voltage_only"].search(text), text


@pytest.mark.parametrize("text", LITHIUM_NEW)
def test_lithium_pattern_new_cells(text):
    assert TEXT_RULES["battery_safety"].search(text), text


def test_lithium_pattern_no_false_hits():
    for text in ("1000uF", "R21700k", "CR1220x", "LiFe", "life support"):
        assert not TEXT_RULES["battery_safety"].search(text), text


def test_mains_rule_stays_policy_without_source():
    rule = next(r for r in RULES["text_rules"] if r["code"] == "low_voltage_only")
    assert rule["severity"] == "danger" and rule["source_ids"] == []


def test_relay_with_250vac_rating_becomes_danger():
    """The relay kind carries low_voltage_only as caution; the AC rating in the value raises it to danger."""
    env = solder.plan("K1 relay 10A 250VAC\nR1 1k")
    assert env["ok"] is True, env
    step = next(s for s in env["result"]["steps"] if s["kind"] == "relay")
    assert [h["severity"] for h in step["hints"] if h["code"] == "low_voltage_only"] == ["danger"]
    w = [w for w in env["warnings"] if w["code"] == "low_voltage_only"]
    assert len(w) == 1 and w[0]["severity"] == "danger" and w[0]["message"].startswith("K1: ")


def test_capacitor_rating_is_no_mains_hint():
    env = solder.plan("C1 100uF 400V\nC2 470uF 250V")
    assert env["ok"] is True, env
    assert not any(w["code"] == "low_voltage_only" for w in env["warnings"])


@pytest.mark.parametrize("bom_text", ["BT1 21700 cell", "BT2 LiFePO4 pack", "J4 holder CR123A"])
def test_new_lithium_cells_warn_danger(bom_text):
    env = solder.plan(bom_text)
    assert any(w["code"] == "battery_safety" and w["severity"] == "danger" for w in env["warnings"]), env["warnings"]
