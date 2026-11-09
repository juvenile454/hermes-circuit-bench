"""parts.py reads every data/parts/*.json; a part name twice is an error."""
from __future__ import annotations

import json

import pytest

from circuit_bench.bench_core import parts

NMOS = {"id": "ZZ-NMOS", "aliases": ["ZZN"], "kind": "nmos", "title": "t", "source_id": "nxp-um10204",
        "r_ds_on": {"rows": [{"v_gs": 4.5, "max": 0.05}]}}
LDO = {"id": "ZZ-LDO", "kind": "ldo", "title": "t", "source_id": "nxp-um10204"}


@pytest.fixture
def parts_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(parts, "PARTS_DIR", tmp_path)
    parts.clear_cache()
    yield tmp_path
    parts.clear_cache()


def _write(folder, name, items):
    (folder / name).write_text(json.dumps({"schema": 1, "parts": items}), encoding="utf-8")


def test_every_file_is_read_in_name_order(parts_dir):
    _write(parts_dir, "b.json", [LDO])
    _write(parts_dir, "a.json", [NMOS])
    assert parts.ids_of("nmos") == ["ZZ-NMOS"] and parts.power_ids("ldo") == ["ZZ-LDO"]
    assert parts.power_part(" zzn ", "nmos")["id"] == "ZZ-NMOS"
    assert parts.find("zz-ldo", "ldo")["id"] == "ZZ-LDO" and parts.find("zz-ldo", "nmos") is None
    assert parts.find(None) is None and parts.ids() == []


@pytest.mark.parametrize("dup", [{**LDO, "id": "ZZ-NMOS"}, {**LDO, "aliases": ["zzn"]}])
def test_a_part_name_twice_is_an_error(parts_dir, dup):
    _write(parts_dir, "a.json", [NMOS])
    _write(parts_dir, "b.json", [dup])
    with pytest.raises(ValueError, match="duplicate part name"):
        parts.ids_of("ldo")


def test_bad_files_are_errors(parts_dir):
    (parts_dir / "a.json").write_text(json.dumps({"schema": 2, "parts": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown schema"):
        parts.ids()
    parts.clear_cache()
    _write(parts_dir, "a.json", [{"id": "X", "kind": "ldo"}])
    with pytest.raises(ValueError, match="source_id"):
        parts.ids()


def test_the_shipped_files_load_without_duplicates():
    parts.clear_cache()
    assert parts.ids() == ["2N2222A"] and "AO3400A" in parts.power_ids("nmos")
    assert {"power.json", "transistors.json"} <= {p.name for p in parts.PARTS_DIR.glob("*.json")}
