"""Text and schema budgets of the seven tools, measured once and kept as a ratchet. The ceilings are fixed limits;
the ratchet values are the measurement plus a small reserve.

First measurement (08.11.2026), six registered calculators:
- descriptions: bench_project 456, bench_pins 423, bench_calc 316, bench_schematic 316, bench_solder 252,
  bench_board 488, bench_crash 316; sum 2567
- schema cost ``len(json.dumps(schemas.ALL))`` 9722; with the ten planned calculators of modspec.NEW_CALCS in the
  bench_calc enum (each costs len(kind) + 4) 9834.
"""
from __future__ import annotations

import json

import pytest

from circuit_bench import schemas
from circuit_bench.bench_core import calckit, modspec

CEIL_DESCRIPTION = 500  # Hermes tool_search clips here
CEIL_DESCRIPTIONS_SUM = 2800
CEIL_COST = 10000
RATCHET_DESCRIPTIONS_SUM = 2600  # measured 2434 (was 2449)
RATCHET_COST_ALL_CALCS = 9950  # measured 9941 (facts types, parts conn, suggest limit paid by shorter texts)


def _enum_cost(kinds) -> int:
    return len(json.dumps(list(kinds))) - 2


@pytest.mark.parametrize("schema", schemas.ALL, ids=lambda s: s["name"])
def test_description_per_tool(schema):
    assert len(schema["description"]) <= CEIL_DESCRIPTION, len(schema["description"])


def test_descriptions_sum():
    total = sum(len(s["description"]) for s in schemas.ALL)
    assert total <= RATCHET_DESCRIPTIONS_SUM <= CEIL_DESCRIPTIONS_SUM, total


def test_schema_cost_leaves_room_for_every_planned_calculator():
    cost = len(json.dumps(list(schemas.ALL)))
    missing = [k for k in modspec.NEW_CALCS if k not in calckit.kinds()]
    with_all = cost + (_enum_cost([*calckit.kinds(), *missing]) - _enum_cost(calckit.kinds()))
    assert cost <= with_all <= RATCHET_COST_ALL_CALCS <= CEIL_COST, (cost, with_all)


def test_calc_description_does_not_grow_with_new_calculators():
    """The description names only the six basics; new calculators show up in the enum and in action=list."""
    text = schemas.CALC["description"]
    assert ", ".join(modspec.BASIC_CALCS) in text
    for kind in modspec.NEW_CALCS:
        assert kind not in text, kind
    assert schemas.calc_schema()["description"] == text
