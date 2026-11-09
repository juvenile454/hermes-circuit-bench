"""Citations: code and data against the committed excerpts; with the corpus, excerpts against the pinned files.

Excerpts: tests/corpus/excerpts/calc-*.txt ('#' metadata lines, '@@' segments of verbatim lines).
Corpus: tests/.corpus/calc/* (scripts/fetch_corpus.py calc), SHA-256 pinned in tests/corpus/calc.json.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from circuit_bench.bench_core import calc, eseries, sources

ROOT = Path(__file__).resolve().parent.parent
EXCERPTS = ROOT / "tests" / "corpus" / "excerpts"
MANIFEST = ROOT / "tests" / "corpus" / "calc.json"
CORPUS = ROOT / "tests" / ".corpus"
PARTS = ROOT / "circuit_bench" / "data" / "parts" / "transistors.json"
CALC_SOURCES = ROOT / "circuit_bench" / "data" / "sources" / "calc.json"

FILES = {
    "nxp-um10204": "calc-nxp-um10204.txt",
    "onsemi-2n2222a": "calc-onsemi-2n2222a.txt",
    "iec-60063": "calc-eseries-wikipedia.txt",
}


def _excerpt(name: str) -> tuple[dict[str, str], list[tuple[str, list[str]]]]:
    meta: dict[str, str] = {}
    segments: list[tuple[str, list[str]]] = []
    for line in (EXCERPTS / name).read_text(encoding="utf-8").split("\n"):
        if line.startswith("# ") and ": " in line and not segments:
            key, _, value = line[2:].partition(": ")
            if re.fullmatch(r"[a-z_0-9]+", key):
                meta[key] = value
        elif line.startswith("@@ "):
            segments.append((line[3:], []))
        elif segments and line:
            segments[-1][1].append(line)
    return meta, segments


def _lines(name: str) -> list[str]:
    return [line for _, seg in _excerpt(name)[1] for line in seg]


def _after(lines: list[str], head: str, n: int = 1) -> list[str]:
    i = lines.index(head)
    return lines[i + 1:i + 1 + n]


def _manifest() -> dict[str, dict]:
    return {f["path"]: f for f in json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]}


# --- excerpts and metadata ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(("source_id", "name"), FILES.items())
def test_excerpt_metadata_matches_sources_and_manifest(source_id, name):
    meta, segments = _excerpt(name)
    src = sources.get(source_id)
    assert meta["source_id"] == source_id
    assert meta["url"].split(" ")[0] == src["url"]
    assert meta["retrieved"] == src["retrieved"]
    path, sha = re.fullmatch(r"(\S+) sha256 ([0-9a-f]{64})", meta["corpus"]).groups()
    entry = _manifest()[path]
    assert entry["sha256"] == sha
    assert source_id in entry["note"]
    if path.endswith(".pdf"):
        assert sha in src["note"]  # the source names the exact file
    assert segments and all(seg for _, seg in segments)


def test_every_calc_source_has_an_excerpt():
    ids = [s["id"] for s in json.loads(CALC_SOURCES.read_text(encoding="utf-8"))]
    assert sorted(ids) == sorted(FILES)
    for path, entry in _manifest().items():
        assert path.startswith("calc/") and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])


def test_code_source_ids_exist():
    sources.resolve([calc.NXP, calc.RULE, eseries.SOURCE_ID])
    for part in json.loads(PARTS.read_text(encoding="utf-8"))["parts"]:
        sources.get(part["source_id"])


# --- NXP UM10204 ↔ calc.py ---------------------------------------------------------------------------------------
def _nums(text: str) -> list[str]:
    return text.split()


def test_i2c_constants_quote_um10204():
    lines = _lines(FILES["nxp-um10204"])
    meta, _ = _excerpt(FILES["nxp-um10204"])
    # UM10204 §7.1: T = t2 - t1 = 0.8473 × RC, Equation 1 and 2
    assert "T = t2 - t1 = 0.8473 × RC" in lines
    assert calc.I2C_RC_FACTOR == 0.8473
    assert meta["eq1"] == "Rp(max) = tr / (0.8473 × Cb)"
    assert meta["eq2"] == "Rp(min) = (VDD − VOL(max)) / IOL"
    assert "R_max = t_r / (0.8473 · C_b)" in calc.I2C_FORMULA
    assert "R_min = (V_DD − V_OL) / I_OL" in calc.I2C_FORMULA
    # Table 10, V_OL1: "0 0.4 0 0.4 0 0.4 V" = Sm min/max, Fm min/max, Fm+ min/max at 3 mA, VDD > 2 V
    assert _after(lines, "VOL1 LOW-level output voltage 1 (open-drain or open-", 3) == [
        "collector) at 3 mA sink", "current; VDD > 2 V", "0 0.4 0 0.4 0 0.4 V"]
    vol = _nums("0 0.4 0 0.4 0 0.4 V")
    assert float(vol[1]) == float(vol[3]) == calc.I2C_V_OL
    assert calc.I2C_V_OL1_VDD_ABOVE == 2.0
    # Table 10, I_OL at V_OL = 0.4 V: Sm min 3 mA, Fm min 3 mA (Fm+ 20 mA)
    line = next(x for x in lines if x.startswith("VOL = 0.4 V "))
    assert line == "VOL = 0.4 V 3 - 3 - 20 - mAIOL LOW-level output current"
    iol = _nums(line)
    assert iol[:4] == ["VOL", "=", "0.4", "V"] and iol[8] == "20"
    assert float(iol[4]) * 1e-3 == float(iol[6]) * 1e-3 == calc.I2C_I_OL
    # Table 11, t_r max: Sm 1000 ns, Fm 300 ns
    assert _after(lines, "tr rise time of both SDA and SCL", 2) == ["signals", "- 1000 20 300 - 120 ns"]
    tr = _nums("- 1000 20 300 - 120 ns")
    assert calc.I2C_MODES["standard"]["t_r"] == pytest.approx(float(tr[1]) * 1e-9, rel=1e-12)
    assert calc.I2C_MODES["fast"]["t_r"] == pytest.approx(float(tr[3]) * 1e-9, rel=1e-12)
    # Table 11, C_b max 400 pF for Sm and Fm
    line = next(x for x in lines if x.startswith("Cb capacitive load for each bus line"))
    assert line == "Cb capacitive load for each bus line[9] - 400 - 400 - 550 pF"
    cb = _nums(line.split("]", 1)[1])
    assert calc.I2C_MODES["standard"]["c_b_max"] == pytest.approx(float(cb[1]) * 1e-12, rel=1e-12)
    assert calc.I2C_MODES["fast"]["c_b_max"] == pytest.approx(float(cb[3]) * 1e-12, rel=1e-12)
    # Table 10, C_i max 10 pF
    assert "Ci capacitance for each I/O pin[10] - 10 - 10 - 10 pF" in lines
    assert calc.I2C_C_PIN_MAX == pytest.approx(10e-12, rel=1e-12)
    # note [4] (fast mode warning) and the advice behind the R_max hint
    assert any("6 mA IOL is required at 0.6 V VOL" in x for x in lines)
    assert "can use a value toward the higher end of the range in order to limit IDD." in lines


def test_i2c_mode_labels():
    assert {m["label"] for m in calc.I2C_MODES.values()} == {"Standard-mode", "Fast-mode"}


# --- onsemi 2N2222A ↔ transistors.json ---------------------------------------------------------------------------
def _hfe_table(lines: list[str]) -> list[dict]:
    i = lines.index("DC Current Gain")
    conds = lines[i + 1:i + 6]
    assert lines[i + 6] == "hFE"
    mins, maxs = lines[i + 7:i + 12], lines[i + 12:i + 17]
    rows = []
    for cond, lo, hi in zip(conds, mins, maxs, strict=True):
        m = re.fullmatch(r"\(IC = ([\d.]+) mAdc, VCE = ([\d.]+) Vdc\)", cond)
        assert m, cond
        rows.append({"i_c": float(m.group(1)) * 1e-3, "v_ce": float(m.group(2)), "min": int(lo),
                     "max": None if hi == "−" else int(hi), "evidence": cond})
    return rows


def test_2n2222a_hfe_rows_quote_the_datasheet():
    lines = _lines(FILES["onsemi-2n2222a"])
    assert "ON CHARACTERISTICS (Note 1)" in lines
    assert "ELECTRICAL CHARACTERISTICS (TA = 25°C unless otherwise noted)" in lines
    want = _hfe_table(lines)
    part = next(p for p in json.loads(PARTS.read_text(encoding="utf-8"))["parts"] if p["id"] == "2N2222A")
    assert part["source_id"] == "onsemi-2n2222a"
    assert part["hfe"]["evidence"] == "DC Current Gain"
    got = part["hfe"]["rows"]
    assert len(got) == len(want) == 5
    for g, w in zip(got, want, strict=True):
        assert g["i_c"] == pytest.approx(w["i_c"], rel=1e-12)
        assert (g["v_ce"], g["min"], g["max"], g["evidence"]) == (w["v_ce"], w["min"], w["max"], w["evidence"])
    assert "T_A = 25 °C" in part["conditions"] and "pulse test" in part["conditions"]


def test_2n2222a_rating_quotes_the_datasheet():
    lines = _lines(FILES["onsemi-2n2222a"])
    part = next(p for p in json.loads(PARTS.read_text(encoding="utf-8"))["parts"] if p["id"] == "2N2222A")
    rating = part["ratings"]["i_c_max"]
    assert rating["evidence"] in lines
    m = re.fullmatch(r"Collector Current − Continuous IC (\d+) mAdc", rating["evidence"])
    assert rating["value"] == pytest.approx(int(m.group(1)) * 1e-3, rel=1e-12) and rating["unit"] == "A"
    assert {"2N2222A", "NPN Silicon", "2N2222A/D", "November, 2013 − Rev. 2"} <= set(lines)


# --- E series ↔ eseries.py ---------------------------------------------------------------------------------------
def test_eseries_tables_quote_the_source():
    lines = _lines(FILES["iec-60063"])
    for name in eseries.SERIES:
        head = f"; {name} values"
        tolerance, values = _after(lines, head, 2)
        assert tolerance.startswith(": (") and values.startswith(": ")
        assert tuple(values[2:].split(", ")) == eseries._TABLES[name], name


# --- corpus: excerpts ↔ pinned files -----------------------------------------------------------------------------
def _corpus_file(source_id: str) -> Path:
    meta, _ = _excerpt(FILES[source_id])
    path, sha = meta["corpus"].split(" sha256 ")
    target = CORPUS / path
    if not target.is_file():
        pytest.skip(f"corpus file missing: {path} (scripts/fetch_corpus.py calc)")
    assert hashlib.sha256(target.read_bytes()).hexdigest() == sha, f"{path}: SHA-256 differs from the manifest"
    return target


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


@pytest.mark.corpus
@pytest.mark.parametrize("source_id", ["nxp-um10204", "onsemi-2n2222a"])
def test_pdf_excerpt_matches_pinned_pdf(source_id):
    pypdf = pytest.importorskip("pypdf")  # dev tool only, never a plugin dependency
    pdf = _corpus_file(source_id)
    import logging
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # font warnings, not relevant for the text layer
    reader = pypdf.PdfReader(str(pdf))
    _, segments = _excerpt(FILES[source_id])
    for label, seg in segments:
        page = int(re.fullmatch(r"page (\d+)", label).group(1))
        text = _squash(reader.pages[page - 1].extract_text())
        pos = 0
        for line in seg:  # every line in order on that page (whitespace-insensitive, robust across pypdf versions)
            found = text.find(_squash(line), pos)
            assert found >= 0, f"{source_id} page {page}: {line!r} not found after offset {pos}"
            pos = found + len(_squash(line))


@pytest.mark.corpus
def test_wiki_excerpt_matches_pinned_revision():
    path = _corpus_file("iec-60063")
    lines = path.read_text(encoding="utf-8").split("\n")
    _, segments = _excerpt(FILES["iec-60063"])
    for label, seg in segments:
        a, b = map(int, re.fullmatch(r"lines (\d+)-(\d+)", label).groups())
        assert lines[a - 1:b] == seg
