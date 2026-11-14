"""Citations: power.json, calc_power.py and calc-plus.json against the committed excerpts; with the corpus,
the excerpts against the pinned PDFs (text layer and, for the AMS1117, the bold font that marks full-range values).

Excerpts: tests/corpus/excerpts/calc-plus-*.txt ('#' metadata lines, '@@ page N' segments of verbatim lines), found by
glob and parsed by tests/excerpts.py (PDF page text through its cache tests/.corpus/.text/<sha>.json).
Corpus: tests/.corpus/ (scripts/fetch_corpus.py calc pins), SHA-256 pinned in tests/corpus/calc.json and pins.json.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

import excerpts as ex
from circuit_bench.bench_core import calc_power, sources

ROOT = Path(__file__).resolve().parent.parent
EXCERPTS = ex.EXCERPTS
MANIFESTS = ex.MANIFESTS
CORPUS = ex.CORPUS
POWER = ROOT / "circuit_bench" / "data" / "parts" / "power.json"
PLUS_SOURCES = ROOT / "circuit_bench" / "data" / "sources" / "calc-plus.json"

FILES = {e.source_id: e.name for e in ex.excerpts("calc-plus-*.txt")}
GLYPH_DECODED = {"infineon-irlz44n"}  # text layer uses glyph names /G<n> (see the excerpt metadata)


def _excerpt(name: str) -> tuple[dict[str, str], list[tuple[str, list[str]]]]:
    e = ex.parse(EXCERPTS / name)
    return e.meta, e.segments


def _lines(source_id: str) -> list[str]:
    return [line for _, seg in _excerpt(FILES[source_id])[1] for line in seg]


def _after(lines: list[str], head: str, n: int = 1) -> list[str]:
    i = lines.index(head)
    return lines[i + 1:i + 1 + n]


def _manifest_entry(path: str) -> dict:
    entry = ex.entry_for_path(path, MANIFESTS)
    assert entry is not None, f"{path} is in no corpus manifest"
    return entry


def _part(pid: str) -> dict:
    return next(p for p in json.loads(POWER.read_text(encoding="utf-8"))["parts"] if p["id"] == pid)


def _has(lines: list[str], text: str) -> bool:
    return any(text in line for line in lines)


# --- excerpts, metadata, source entries ----------------------------------------------------------------------------
def test_the_plus_excerpts_are_found():
    assert FILES == {
        "aos-ao3400a": "calc-plus-aos-ao3400a.txt",
        "infineon-irlz44n": "calc-plus-infineon-irlz44n.txt",
        "ams-ams1117": "calc-plus-ams-ams1117.txt",
        "ds-esp32-s3-wroom-1-power": "calc-plus-esp32-s3-wroom-1-power.txt",
    }


@pytest.mark.parametrize(("source_id", "name"), FILES.items())
def test_excerpt_metadata_matches_sources_and_manifest(source_id, name):
    meta, segments = _excerpt(name)
    src = sources.get(source_id)
    assert meta["source_id"] == source_id
    assert meta["url"].split(" ")[0] == src["url"]
    assert meta["retrieved"] == src["retrieved"] == "2026-11-06"
    path, sha = re.fullmatch(r"(\S+) sha256 ([0-9a-f]{64})", meta["corpus"]).groups()
    entry = _manifest_entry(path)
    assert entry["sha256"] == sha and entry["url"] == src["url"]
    assert sha in src["note"]  # the source names the exact file
    if path.startswith("calc/"):
        assert source_id in entry["note"]
    assert segments and all(seg for _, seg in segments)
    assert all(re.fullmatch(r"page \d+", label) for label, _ in segments)


def test_every_plus_source_has_an_excerpt_and_every_part_a_source():
    ids = [s["id"] for s in json.loads(PLUS_SOURCES.read_text(encoding="utf-8"))]
    assert len(ids) == len(set(ids)), sorted(i for i in set(ids) if ids.count(i) > 1)  # a source id appears once
    # the planning-current guides have their own excerpts (pixel-planning-*.txt, tests/test_u011_led_strip.py)
    other = [i for i in ids if i not in FILES]
    assert sorted(set(ids) - set(other)) == sorted(FILES)
    assert sorted(other) == ["adafruit-neopixel-uberguide-powering", "sparkfun-apa102-hookup-guide"]
    assert all(ex.by_source("pixel-planning-*.txt").get(i) for i in other)
    for part in json.loads(POWER.read_text(encoding="utf-8"))["parts"]:
        assert part["source_id"] in FILES
    sources.resolve([calc_power.WROOM, calc_power.RULE])


# --- AO3400A ------------------------------------------------------------------------------------------------------
def test_ao3400a_values_quote_the_datasheet():
    lines = _lines("aos-ao3400a")
    meta, _ = _excerpt(FILES["aos-ao3400a"])
    part = _part("AO3400A")
    assert {"AO3400A", "30V N-Channel MOSFET", "Rev 3.1: July 2023 www.aosmd.com Page 1 of 5"} <= set(lines)
    assert "Electrical Characteristics (TJ=25° C unless otherwise noted)" in lines
    # R_DS(on): Product Summary gives V_GS and max ('mW' = mΩ); page 2 gives the test current and typ/max pairs
    pairs = {10.0: "18 26.5", 4.5: "19 32 mW", 2.5: "24 48 mW"}
    for row in part["r_ds_on"]["rows"]:
        assert row["evidence"] in lines
        v_gs, r_max = re.fullmatch(r"RDS\(ON\) \(at VGS ?= ?([\d.]+)V\) < ([\d.]+)mW", row["evidence"]).groups()
        assert row["v_gs"] == float(v_gs) and row["max"] == pytest.approx(float(r_max) * 1e-3, rel=1e-12)
        assert row["test"] in lines
        tv, ti = re.fullmatch(r"VGS=([\d.]+)V, ID=([\d.]+)A", row["test"]).groups()
        assert (float(tv), float(ti)) == (row["v_gs"], row["i_d"])
        assert pairs[row["v_gs"]] in lines
        typ, mx = pairs[row["v_gs"]].split()[:2]
        assert row["typ"] == pytest.approx(float(typ) * 1e-3, rel=1e-12)
        assert row["max"] == pytest.approx(float(mx) * 1e-3, rel=1e-12)
    th = part["v_gs_th"]
    assert th["evidence"] in lines
    assert [float(x) for x in th["evidence"].split()[4:7]] == [th["min"], th["typ"], th["max"]]
    assert "VDS=VGS ID=250mA" in lines  # 'mA' = µA (Symbol font)
    r = part["ratings"]
    assert all(r[k]["evidence"] in lines for k in r)
    assert r["v_ds_max"]["value"] == float(r["v_ds_max"]["evidence"].rsplit(" ", 1)[1])
    assert r["v_gs_max"]["value"] == float(re.match(r"V±([\d.]+)", r["v_gs_max"]["evidence"]).group(1))
    assert r["i_d_max"]["value"] == float(re.search(r"([\d.]+)A$", r["i_d_max"]["evidence"]).group(1))
    assert r["t_j_max"]["value"] == float(re.search(r"to (\d+) °C$", r["t_j_max"]["evidence"]).group(1))
    # R_θJA steady state: the table extracts out of order; the excerpt transcribes it from the rendered page 1
    assert "'125' RθJA max (Steady-State, Notes A, D)" in meta["thermal"]
    assert "125" in _after(lines, r["r_th_ja"]["evidence"], 3) and r["r_th_ja"]["value"] == 125.0
    assert _has(lines, "1in2 FR-4 board with 2oz. Copper, in a still air environment")
    assert {"Figure 4: On-Resistance vs. Junction Temperature", "Figure 5: On-Resistance vs. Gate-Source Voltage"} <= set(lines)


# --- IRLZ44N ------------------------------------------------------------------------------------------------------
def test_irlz44n_values_quote_the_datasheet():
    lines = _lines("infineon-irlz44n")
    part = _part("IRLZ44N")
    assert {"IRLZ44NPbF", "PD - 94831", "11/11/03", "l Logic-Level Gate Drive"} <= set(lines)
    assert "Electrical Characteristics @ TJ = 25°C (unless otherwise specified)" in lines
    for row in part["r_ds_on"]["rows"]:
        assert _has(lines, row["evidence"]) and row["test"] in row["evidence"]
        r_max, v_gs, i_d = re.fullmatch(r"––– ––– ([\d.]+) (?:\u2126 )?V ?GS = ([\d.]+)V, ID = ([\d.]+)A", row["evidence"]).groups()
        assert (row["max"], row["v_gs"], row["i_d"], row["typ"]) == (float(r_max), float(v_gs), float(i_d), None)
    th = part["v_gs_th"]
    assert th["evidence"] in lines
    assert (th["min"], th["max"]) == (1.0, 2.0) and th["evidence"].split()[4:7] == ["1.0", "–––", "2.0"]
    r = part["ratings"]
    assert all(_has(lines, r[k]["evidence"]) for k in r)
    assert r["v_ds_max"]["evidence"] == "VDSS = 55V" and r["v_ds_max"]["value"] == 55.0
    assert r["v_gs_max"]["value"] == float(re.search(r"±(\d+) V", r["v_gs_max"]["evidence"]).group(1))
    assert r["i_d_max"]["value"] == float(r["i_d_max"]["evidence"].rsplit(" ", 1)[1])
    assert "TC = 25°C" in r["i_d_max"]["evidence"] and "T_C = 25 °C" in r["i_d_max"]["conditions"]
    assert r["t_j_max"]["value"] == float(r["t_j_max"]["evidence"].rsplit(" ", 1)[1])
    assert r["r_th_ja"]["value"] == float(r["r_th_ja"]["evidence"].rsplit(" ", 1)[1])


# --- AMS1117 ------------------------------------------------------------------------------------------------------
PACKAGES = {"AMS1117-3.3": "SOT-223", "AMS1117CD-3.3": "TO-252", "AMS1117CS-3.3": "SO-8"}


def test_ams1117_values_quote_the_datasheet():
    lines = _lines("ams-ams1117")
    # ordering information: column order TO-252, SOT-223, 8L SOIC
    assert "TO-252 SOT-223 8L SOIC TEMPERATURE RANGE" in lines
    assert "AMS1117CD-3.3 AMS1117-3.3 AMS1117CS-3.3 -40 to 125 ° C" in lines
    theta = {pkg: float(v) for pkg, v in (re.search(r"(SO-8|TO-252|SOT-223) package ϕ JA = (\d+) °C/W", x).groups()
                                          for x in lines if " package ϕ JA = " in x)}
    assert theta == {"SO-8": 160.0, "TO-252": 80.0, "SOT-223": 90.0}
    assert "46 °C/W to >90 °C/W depending on mounting technique and" in lines
    dropout_vals = _after(lines, "∆VOUT , ∆VREF = 1%, I OUT = 0.8A (Note 4)", 1)[0].split()
    assert dropout_vals == ["1.1", "1.3"]
    assert "Note 4: Dropout voltage is specified up to 0.8A load. For currents over 0.8A dropout will be higher" in lines
    assert _after(lines, "(V IN - VOUT ) = 1.5V", 1) == ["900 1,100 1,500 mA"]
    q_typ, q_max, q_unit = _quiescent(lines)
    assert (q_typ, q_max, q_unit) == ("5", "11", "mA")
    assert _after(lines, "AMS1117-3.3 V IN = 4.8V 3.251", 3)[1:] == ["3.300", "3.300"]
    for pid, pkg in PACKAGES.items():
        part = _part(pid)
        assert part["package"] == pkg and part["source_id"] == "ams-ams1117"
        r = part["ratings"]
        assert r["r_th_ja"]["value"] == theta[pkg] and _has(lines, r["r_th_ja"]["evidence"])
        assert part["dropout"]["value"] == float(dropout_vals[1]) and part["dropout"]["typ"] == float(dropout_vals[0])
        assert part["dropout"]["i_out"] == 0.8 and part["dropout"]["evidence"] in lines
        assert part["i_q"]["value"] == pytest.approx(float(q_max) * 1e-3, rel=1e-12)
        assert part["i_q"]["typ"] == pytest.approx(float(q_typ) * 1e-3, rel=1e-12)
        assert part["i_q"]["evidence"] in lines
        assert r["i_limit_min"]["value"] == pytest.approx(900e-3, rel=1e-12) and r["i_limit_min"]["evidence"] in lines
        assert r["v_in_max"]["value"] == 15.0 and _has(lines, r["v_in_max"]["evidence"])
        assert r["t_j_max"]["value"] == 125.0 and r["t_j_max"]["evidence"] in lines
        assert r["t_shutdown"]["value"] == 165.0 and r["t_shutdown"]["evidence"] in lines
        assert part["v_out"]["value"] == 3.3 and part["v_out"]["evidence"] in lines
    # the regulator formulas of the datasheet (page 5) and the calculator
    assert {"PD = ( V IN - VOUT )( I OUT )", "TJ = T A(MAX) + P D(Thermal Resistance (junction-to-ambient))",
            "Maximum junction temperature must not exceed 125 °C."} <= set(lines)
    assert "(V_in − V_out) · I_load" in calc_power.LDO_FORMULA and "T_J = T_A + P · θ_JA" in calc_power.LDO_FORMULA
    assert "Parameters identified with boldface type apply over the full operating temperature range." in lines


def _quiescent(lines: list[str]) -> tuple[str, str, str]:
    i = lines.index("Quiescent Current AMS1117-1.5/-1.8/-2.5/-")
    assert lines[i + 1:i + 3] == ["2.85/-3.3/-5.0", "(V IN - VOUT ) = 1.5V"]
    return lines[i + 3], lines[i + 4], lines[i + 5]


# --- ESP32-S3-WROOM-1 ---------------------------------------------------------------------------------------------
def test_wroom_values_quote_the_datasheet():
    lines = _lines("ds-esp32-s3-wroom-1-power")
    assert "Symbol Parameter Min T yp Max Unit" in lines
    vdd = "VDD33 Power supply voltage 3.0 3.3 3.6 V".split()
    assert " ".join(vdd) in lines and calc_power.ESP32S3_VDD33 == (float(vdd[4]), float(vdd[6]))
    assert "IV DD Current delivered by external power supply 0.5 — — A" in lines  # Min column
    assert calc_power.ESP32S3_I_VDD_MIN == 0.5
    assert "VOH 2 High-level output voltage 0.8 × VDD1 — — V" in lines and calc_power.ESP32S3_V_OH_FACTOR == 0.8
    assert "2VOH and VOL are measured using high-impedance load." in lines
    assert "802.11b, 1 Mbps, @20.5 dBm 355" in lines and calc_power.ESP32S3_TX_PEAK == pytest.approx(0.355, rel=1e-12)
    assert "T able 6-4. Current Consumption for Wi-Fi (2.4 GHz) in Active Mode" in lines


# --- corpus: excerpts ↔ pinned PDFs --------------------------------------------------------------------------------
def _corpus_file(source_id: str) -> Path:
    meta, _ = _excerpt(FILES[source_id])
    path, sha = meta["corpus"].split(" sha256 ")
    target = CORPUS / path
    if not target.is_file():
        pytest.skip(f"corpus file missing: {path} (scripts/fetch_corpus.py calc pins)")
    assert hashlib.sha256(target.read_bytes()).hexdigest() == sha, f"{path}: SHA-256 differs from the manifest"
    return target


def _glyphs(text: str) -> str:
    def char(m: re.Match) -> str:
        n = int(m.group(1))
        return chr(n) if n < 128 else bytes([n]).decode("cp1252", errors="replace")
    return re.sub(r"/G(\d+)", char, text)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _reader(source_id: str):
    pypdf = pytest.importorskip("pypdf")  # dev tool only, never a plugin dependency
    import logging
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # font warnings, not relevant for the text layer
    return pypdf.PdfReader(str(_corpus_file(source_id)))


@pytest.mark.corpus
@pytest.mark.parametrize("source_id", FILES)
def test_pdf_excerpt_matches_pinned_pdf(source_id):
    pytest.importorskip("pypdf")  # dev tool only, never a plugin dependency
    pdf = ex.PdfText(_corpus_file(source_id))  # page text through the cache tests/.corpus/.text/<sha>.json
    _, segments = _excerpt(FILES[source_id])
    for label, seg in segments:
        page = int(re.fullmatch(r"page (\d+)", label).group(1))
        raw = pdf.text(page)
        text = _squash(_glyphs(raw) if source_id in GLYPH_DECODED else raw)
        pos = 0
        for line in seg:  # every line in order on that page (whitespace-insensitive)
            found = text.find(_squash(line), pos)
            assert found >= 0, f"{source_id} page {page}: {line!r} not found after offset {pos}"
            pos = found + len(_squash(line))


@pytest.mark.corpus
def test_ams1117_full_range_values_are_bold_in_the_pdf():
    reader = _reader("ams-ams1117")
    fonts: dict[str, set[str]] = {}

    def visit(text, _cm, _tm, font, _size):
        if text.strip() and font:
            fonts.setdefault(text.strip(), set()).add(str(font.get("/BaseFont", "")))

    reader.pages[2].extract_text(visitor_text=visit)
    for value in ("1.1", "1.3", "900 1,100 1,500", "11"):  # dropout, current limit, quiescent current
        assert fonts.get(value) and all(f.endswith("Times-Bold") for f in fonts[value]), (value, fonts.get(value))
    assert fonts["15 °C/W"] == {f for f in fonts["15 °C/W"] if f.endswith("Times-Roman")}  # a regular one, for contrast
