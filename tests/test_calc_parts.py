"""Part data (data/parts/transistors.json) and lookups in parts.py."""
import json
from pathlib import Path

import pytest

from circuit_bench.bench_core import parts, sources
from circuit_bench.bench_core.contracts import BenchError

DATA = Path(parts.__file__).resolve().parent.parent / "data" / "parts" / "transistors.json"


def test_data_shape_and_sources():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    known = sources.all_sources()
    for part in data["parts"]:
        assert part["source_id"] in known
        assert known[part["source_id"]]["url"].startswith("https://")
        for row in part["hfe"]["rows"]:
            assert set(row) == {"i_c", "v_ce", "min", "max", "evidence"}
            assert row["evidence"].startswith("(IC = ")
        for rating in part.get("ratings", {}).values():
            assert set(rating) == {"value", "unit", "evidence"}


def test_ids_and_lookup():
    assert parts.ids() == ["2N2222A"]
    assert parts.get(" 2n2222a ")["id"] == "2N2222A"
    p = parts.get("2N2222A")
    p["hfe"]["rows"].clear()  # callers get a copy
    assert parts.get("2N2222A")["hfe"]["rows"]


@pytest.mark.parametrize(("i_c", "hfe", "basis"), [
    (0.0001, 50, "row"), (0.001, 75, "row"), (0.01, 100, "row"), (0.15, 100, "row"), (0.5, 30, "row"),
    (0.0005, 50, "between_rows"), (0.005, 75, "between_rows"), (0.013, 100, "between_rows"),
    (0.3, 30, "between_rows"), (0.0100000001, 100, "row"),
])
def test_hfe_min(i_c, hfe, basis):
    rec = parts.hfe_min("2N2222A", i_c)
    assert rec["hfe_min"] == hfe and rec["basis"] == basis
    assert rec["source_id"] == "onsemi-2n2222a"
    assert len(rec["rows"]) == (1 if basis == "row" else 2)


@pytest.mark.parametrize("i_c", [0.00005, 0.50001, 0.8, 2.0])
def test_hfe_min_outside_the_table_is_none(i_c):
    assert parts.hfe_min("2N2222A", i_c) is None


def test_range_and_rating():
    assert parts.hfe_range("2N2222A") == (0.0001, 0.5)
    assert parts.rating("2N2222A", "i_c_max") == {"value": 0.8, "unit": "A",
                                                   "evidence": "Collector Current − Continuous IC 800 mAdc"}
    assert parts.rating("2N2222A", "v_ceo") is None


def test_unknown_part():
    with pytest.raises(BenchError) as e:
        parts.get("BC547")
    assert e.value.code == "rule_data_missing" and "2N2222A" in e.value.hint
    for bad in (None, 7, "", "  "):
        with pytest.raises(BenchError) as e:
            parts.get(bad)
        assert e.value.code == "invalid_args"


@pytest.mark.parametrize("i_c", [0, -0.01, float("nan"), True, "10 mA"])
def test_bad_current(i_c):
    with pytest.raises(BenchError) as e:
        parts.hfe_min("2N2222A", i_c)
    assert e.value.code == "invalid_args"
