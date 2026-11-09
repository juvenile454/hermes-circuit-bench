import json
from pathlib import Path

import pytest

from circuit_bench.bench_core import boards, sources
from circuit_bench.bench_core.contracts import BenchError

DATA = Path(__file__).resolve().parent.parent / "circuit_bench" / "data"


def test_base_sources_present():
    ids = sources.all_sources()
    for i in ("idf-v6.1-gpio-esp32", "idf-v6.1-gpio-esp32s3", "idf-v6.1-gpio-esp32c3", "devkitc1-s3-v1.1",
              "idf-v6.1-fatal-errors", "rule-of-thumb"):
        assert i in ids
        assert ids[i]["retrieved"] == "2026-11-05"


def test_resolve_keeps_order_and_dedupes():
    got = sources.resolve(["devkitc1-s3-v1.1", "rule-of-thumb", "devkitc1-s3-v1.1"])
    assert [s["id"] for s in got] == ["devkitc1-s3-v1.1", "rule-of-thumb"]


def test_unknown_source_raises():
    with pytest.raises(BenchError) as e:
        sources.resolve(["nope"])
    assert e.value.code == "rule_data_missing"


def _source_ids(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("source_id",) and isinstance(v, str):
                yield v
            elif k in ("source_ids", "sources") and isinstance(v, list):
                yield from (x for x in v if isinstance(x, str))
            else:
                yield from _source_ids(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _source_ids(v)


def test_every_source_id_used_in_data_exists():
    known = set(sources.all_sources())
    used = {}
    for path in DATA.rglob("*.json"):
        if "sources" in path.parts:
            continue
        for sid in _source_ids(json.loads(path.read_text(encoding="utf-8"))):
            used.setdefault(sid, path.relative_to(DATA).as_posix())
    missing = {sid: where for sid, where in used.items() if sid not in known}
    assert missing == {}


def test_devkitc1_headers_match_user_guide_v11():
    b = boards.load("esp32-s3-devkitc-1")
    assert b["chip"] == "esp32s3" and b["revision"] == "v1.1"
    j1, j3 = b["headers"]
    assert [p["n"] for p in j1["pins"]] == list(range(1, 23)) == [p["n"] for p in j3["pins"]]
    labels = lambda h: [p["label"] for p in h["pins"]]  # noqa: E731
    assert labels(j1) == ["3V3", "3V3", "RST", "4", "5", "6", "7", "15", "16", "17", "18", "8", "3", "46", "9", "10",
                          "11", "12", "13", "14", "5V", "G"]
    assert labels(j3) == ["G", "TX", "RX", "1", "2", "42", "41", "40", "39", "38", "37", "36", "35", "0", "45", "48",
                          "47", "21", "20", "19", "G", "G"]
    assert len(j1["pins"]) + len(j3["pins"]) == 44
    assert all(p["kind"] in boards.PIN_KINDS for h in b["headers"] for p in h["pins"])


def test_header_of_and_broken_out():
    assert boards.header_of("esp32-s3-devkitc-1", 35) == "J3-13"
    assert boards.header_of("esp32-s3-devkitc-1", 14) == "J1-20"
    assert boards.header_of("esp32-s3-devkitc-1", 43) == "J3-2"
    assert boards.header_of("esp32-s3-devkitc-1", 26) is None  # SPI flash, not broken out
    out = boards.broken_out("esp32-s3-devkitc-1")
    assert len(out) == 36 and not ({26, 27, 28, 29, 30, 31, 32} & out)


def test_layout_and_list():
    lay = boards.layout("esp32-s3-devkitc-1")
    assert len(lay["left"]) == 22 and len(lay["right"]) == 22
    assert lay["left"][0] == {"header": "J1", "n": 1, "label": "3V3", "kind": "power"}
    assert lay["onboard"][0]["gpio"] == 38
    # more boards exist; the full list is checked in test_plus_boards_data.py
    assert {"id": "esp32-s3-devkitc-1", "title": "ESP32-S3-DevKitC-1", "revision": "v1.1",
            "chip": "esp32s3"} in boards.list_boards()


@pytest.mark.parametrize("bad", ["nope", "../boards/x", ".hidden", ""])
def test_unknown_board(bad):
    with pytest.raises(BenchError) as e:
        boards.load(bad)
    assert e.value.code == "unknown_board"
