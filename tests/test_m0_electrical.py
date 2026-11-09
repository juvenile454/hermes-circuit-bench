"""ESP32 chip DC characteristics.

* loader: get/raw/boards, resolution of relative values at VDD 3.3 V, validation of bad data;
* data: every cited number F quotes lines of tests/corpus/excerpts/esp-<chip>-dc.txt on its page, and the
  number in the quote equals the stored value (mA -> A, factor × VDD, VDD + offset);
* excerpt header <-> manifest tests/corpus/electrical.json <-> source in data/sources/electrical.json;
* with the corpus (scripts/fetch_corpus.py electrical): every excerpt line in order on the pinned PDF page.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from circuit_bench.bench_core import chips, electrical, sources

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / ".corpus"
MANIFEST = ROOT / "tests" / "corpus" / "electrical.json"
EXCERPTS = ROOT / "tests" / "corpus" / "excerpts"
DATA = ROOT / "circuit_bench" / "data" / "electrical"
SOURCES = ROOT / "circuit_bench" / "data" / "sources" / "electrical.json"
CHIPS = ["esp32", "esp32s2", "esp32s3", "esp32c3", "esp32c6"]
UNIT_SCALE = {"mA": 1e-3, "A": 1.0, "V": 1.0}


def excerpt(chip: str) -> tuple[dict[str, str], list[tuple[int, list[str]]]]:
    meta: dict[str, str] = {}
    segs: list[tuple[int, list[str]]] = []
    for line in (EXCERPTS / f"esp-{chip}-dc.txt").read_text(encoding="utf-8").split("\n"):
        if line.startswith("# ") and not segs:
            k, _, v = line[2:].partition(": ")
            if v and k in {"source_id", "document", "url", "corpus", "retrieved", "extracted"}:
                meta[k] = v
        elif line.startswith("@@ "):
            m = re.fullmatch(r"@@ page (\d+)", line)
            assert m, line
            segs.append((int(m.group(1)), []))
        elif line and segs:
            segs[-1][1].append(line)
    return meta, segs


def page_lines(chip: str, page: int) -> list[str]:
    return [ln for p, seg in excerpt(chip)[1] if p == page for ln in seg]


def manifest() -> dict[str, dict]:
    return {e["source_id"]: e for e in json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]}


def cited(doc: dict) -> list[tuple[str, dict]]:
    return [(f"{g}.{k}", f) for g in ("vdd", "io") for k, f in doc.get(g, {}).items()]


def evidence_list(f: dict) -> list[str]:
    return [f["evidence"]] if isinstance(f["evidence"], str) else list(f["evidence"])


def quoted_in_order(parts: list[str], lines: list[str]) -> bool:
    """Each part is a substring of an excerpt line of the page; lines in order (a line may hold several parts)."""
    i = 0
    for part in parts:
        while i < len(lines) and part not in lines[i]:
            i += 1
        if i == len(lines):
            return False
    return True


@pytest.fixture(autouse=True)
def _fresh_cache():
    electrical.clear_cache()
    yield
    electrical.clear_cache()


# --- loader --------------------------------------------------------------------------------------------------------
def test_files_cover_every_chip_with_pin_data():
    assert sorted(p.stem for p in DATA.glob("*.json") if p.stem != "boards") == sorted(CHIPS)
    assert sorted(CHIPS) == sorted(chips.ids())
    assert sorted(CHIPS) == sorted(p.stem for p in (ROOT / "circuit_bench" / "data" / "pins").glob("*.json"))


@pytest.mark.parametrize("chip", CHIPS)
def test_get_resolves_relative_values_at_3v3(chip):
    e = electrical.get(chip)
    assert e["chip"] == chip and e["vdd"] == 3.3
    # all five datasheets: VIH 0.75 × VDD, VIL 0.25 × VDD, VOH 0.8 × VDD, VOL 0.1 × VDD, VIH max VDD + 0.3 V
    assert (e["vih"], e["vil"], e["voh"], e["vol"], e["v_in_max"]) == (2.475, 0.825, 2.64, 0.33, 3.6)
    assert e["vdd_abs_max"] == 3.6 and e["vdd_max"] == 3.6 and e["vdd_min"] == 3.0
    assert (e["ioh"], e["iol"]) == (0.04, 0.028)
    assert e["i_out_total_max"] == {"esp32": 1.2, "esp32s2": 1.8, "esp32s3": 1.5, "esp32c3": 1.0, "esp32c6": 1.0}[chip]
    assert e["source_ids"] == [f"elec-ds-{chip}"]
    assert "3.3 V, 25 °C" in e["conditions"] and "typical" in e["conditions"]
    sources.resolve(e["source_ids"])
    # contract keys are always present
    assert {"chip", "vdd", "vih", "vil", "voh", "vol", "v_in_max", "vdd_abs_max", "ioh", "iol", "source_ids",
            "conditions"} <= e.keys()


def test_voh_matches_the_wroom_value_used_by_calc_power():
    from circuit_bench.bench_core import calc_power
    assert electrical.get("esp32s3")["voh"] == pytest.approx(calc_power.ESP32S3_V_OH_FACTOR * 3.3)


def test_unknown_chip_and_boards():
    assert electrical.get("esp32h2") is None and electrical.raw("esp32h2") is None
    assert electrical.get("../sources/electrical") is None and electrical.get("boards") is None
    assert electrical.boards() == {}  # no Espressif document names a rated 3V3 current


def test_raw_is_a_copy():
    r = electrical.raw("esp32")
    r["io"]["vih"]["rel"] = 9
    assert electrical.raw("esp32")["io"]["vih"]["rel"] == 0.75


def test_resolve_kinds():
    assert electrical.resolve({"value": 0.04}) == 0.04
    assert electrical.resolve({"rel": 0.75, "of": "VDD"}) == 2.475
    assert electrical.resolve({"rel": 0.75, "of": "VDD"}, vdd=3.0) == 2.25
    assert electrical.resolve({"rel_offset": 0.3, "of": "VDD"}) == 3.6
    assert electrical.resolve(None) is None


def test_missing_value_gives_none(tmp_path, monkeypatch):
    doc = electrical.raw("esp32c3")
    del doc["io"]["iol"]
    (tmp_path / "esp32c3.json").write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(electrical, "ELECTRICAL_DIR", tmp_path)
    electrical.clear_cache()
    e = electrical.get("esp32c3")
    assert e["iol"] is None and e["ioh"] == 0.04


@pytest.mark.parametrize("patch", [
    {"schema": 2},
    {"chip": "esp32"},
    {"source_ids": []},
    {"io": {"vih": {"rel": 0.75, "unit": "V", "page": 1, "evidence": "x"}}},  # rel without 'of'
    {"io": {"vih": {"value": 1, "rel": 0.75, "of": "VDD", "unit": "V", "page": 1, "evidence": "x"}}},
    {"io": {"ioh": {"value": 40, "unit": "mA", "page": 1, "evidence": "x"}}},  # not SI
    {"io": {"ioh": {"value": 0.04, "unit": "A", "page": 0, "evidence": "x"}}},
    {"io": {"ioh": {"value": 0.04, "unit": "A", "page": 1, "evidence": []}}},
    {"io": {"ioh": {"value": 0.04, "unit": "A", "page": 1, "evidence": "x", "source_id": "other"}}},
])
def test_bad_files_are_rejected(tmp_path, monkeypatch, patch):
    doc = electrical.raw("esp32c3")
    doc.update(patch)
    (tmp_path / "esp32c3.json").write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(electrical, "ELECTRICAL_DIR", tmp_path)
    electrical.clear_cache()
    with pytest.raises(ValueError):
        electrical.get("esp32c3")


def test_boards_file_is_validated(tmp_path, monkeypatch):
    monkeypatch.setattr(electrical, "ELECTRICAL_DIR", tmp_path)
    (tmp_path / "boards.json").write_text(json.dumps({"boards": {"x": {"rail_3v3_limit": None}}}), encoding="utf-8")
    electrical.clear_cache()
    assert electrical.boards() == {"x": {"rail_3v3_limit": None}}
    (tmp_path / "boards.json").write_text(json.dumps({"boards": {"x": {"rail_3v3_limit": {"value": 1}}}}),
                                          encoding="utf-8")
    electrical.clear_cache()
    with pytest.raises(ValueError):
        electrical.boards()


# --- data <-> excerpt -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("chip", CHIPS)
def test_every_number_quotes_its_excerpt_page(chip):
    doc = electrical.raw(chip)
    pages = {p for p, _ in excerpt(chip)[1]}
    assert doc["source_ids"] == [f"elec-ds-{chip}"]
    for where, f in cited(doc):
        assert f["page"] in pages, where
        assert quoted_in_order(evidence_list(f), page_lines(chip, f["page"])), f"{chip} {where}: {f['evidence']!r}"
        assert f.get("source_id", doc["source_ids"][0]) in doc["source_ids"]


def _number(chip: str, where: str, f: dict) -> None:
    """The stored number is the one printed in the quoted row (no rounding, no interpolation)."""
    text = " ".join(evidence_list(f))
    if "rel" in f:
        assert re.search(rf"(?<![\d.]){re.escape(str(f['rel']))} × VDD", text), (chip, where, text)
    elif "rel_offset" in f:
        assert re.search(rf"VDD ?1? \+ {re.escape(str(f['rel_offset']))} V", text), (chip, where, text)
    elif f["unit"] == "A":
        m = re.search(r"— (\d+) (?:— )?mA$", text)
        assert m, (chip, where, text)
        assert f["value"] == pytest.approx(float(m.group(1)) * 1e-3, rel=1e-12), (chip, where)
    else:
        nums = re.findall(r"(?<![\d.])(\d+\.\d+)(?![\d.])", text)
        assert str(f["value"]) in nums or f"{f['value']:.1f}" in nums, (chip, where, text)


@pytest.mark.parametrize("chip", CHIPS)
def test_numbers_equal_the_quoted_rows(chip):
    doc = electrical.raw(chip)
    for where, f in cited(doc):
        _number(chip, where, f)
    io = doc["io"]
    # the datasheet columns: VIH Min / Max sit in the same row, VIL Max, VOH Min, VOL Max
    assert io["vih"]["evidence"] == io["v_in_max"]["evidence"]
    assert evidence_list(doc["vdd"]["max"])[-1].endswith(" 3.3 3.6 V")
    assert evidence_list(doc["vdd"]["abs_max"])[-1].endswith("0.3 3.6 V")
    assert "Cumulative IO output current" in io["i_out_total_max"]["evidence"]
    for key in ("ioh", "iol"):
        assert "Typ column" in io[key]["conditions"]


def test_esp32_specials():
    doc = electrical.raw("esp32")
    # VDD min '2.3/3.0': the stored 3.0 V is the in-package flash/PSRAM case of note 2
    assert any("this minimum voltage is 3.0 V" in x for x in evidence_list(doc["vdd"]["min"]))
    assert "2.3 V" in doc["vdd"]["min"]["conditions"]
    # VDD_SDIO domain sources less (20 mA typ); loader keeps 'ioh' for VDD3P3_CPU/RTC
    assert doc["io"]["ioh_vdd_sdio"]["value"] == 0.02
    assert "high-impedance" not in json.dumps(doc)  # the ESP32 table has no such note (S2/S3/C3/C6 have)


# --- excerpt <-> manifest <-> source ------------------------------------------------------------------------------
@pytest.mark.parametrize("chip", CHIPS)
def test_excerpt_header_matches_manifest_and_source(chip):
    sid = f"elec-ds-{chip}"
    meta, segs = excerpt(chip)
    e = manifest()[sid]
    src = sources.get(sid)
    assert meta["source_id"] == sid and meta["retrieved"] == src["retrieved"] == "2026-11-08"
    assert meta["url"] == e["url"] == src["url"]
    assert meta["url"].startswith("https://www.espressif.com/sites/default/files/documentation/")
    assert meta["corpus"] == f"{e['path']} sha256 {e['sha256']}"
    assert e["path"].startswith("electrical/") and e["excerpt"] == f"excerpts/esp-{chip}-dc.txt"
    assert f"sha256 {e['sha256']}" in src["note"]
    assert meta["extracted"].startswith("pypdf 6.21.4")
    assert src.get("class", "A") == "A"  # manufacturer document (field added by sources.py)
    assert segs and all(lines for _, lines in segs)
    version = re.search(r"Datasheet v(\d+\.\d+)", src["title"]).group(1)
    assert any(ln.endswith(f"Series Datasheet v{version}") for _, seg in segs for ln in seg)


def test_sources_file_lists_exactly_the_manifest():
    ids = [s["id"] for s in json.loads(SOURCES.read_text(encoding="utf-8"))]
    assert sorted(ids) == sorted(manifest()) == sorted(f"elec-ds-{c}" for c in CHIPS)
    assert all(i.startswith("elec-") for i in ids)


# --- corpus: excerpt lines on the pinned PDF page -----------------------------------------------------------------
def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


@pytest.mark.corpus
@pytest.mark.parametrize("chip", CHIPS)
def test_excerpt_lines_are_on_the_pinned_pdf_page(chip):
    meta, segs = excerpt(chip)
    path, sha = meta["corpus"].split(" sha256 ")
    target = CORPUS / path
    if not target.is_file():
        pytest.skip(f"corpus file missing: {path} (scripts/fetch_corpus.py electrical)")
    assert hashlib.sha256(target.read_bytes()).hexdigest() == sha
    pypdf = pytest.importorskip("pypdf")  # dev tool only
    import logging
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = pypdf.PdfReader(str(target))
    for page, lines in segs:
        raw = reader.pages[page - 1].extract_text()
        hay = _squash(raw)
        pos = 0
        for line in lines:
            found = hay.find(_squash(line), pos)
            assert found >= 0, f"{chip} page {page}: {line!r} not found after offset {pos}"
            pos = found + len(_squash(line))
        # whole lines: each excerpt line is a line of pypdf's text (whitespace runs collapsed)
        page_set = {re.sub(r"\s+", " ", ln).strip() for ln in raw.split("\n")}
        assert set(lines) <= page_set, f"{chip} page {page}: {sorted(set(lines) - page_set)}"
