"""Citation tests for the board layouts ESP32-DevKitC V4 and ESP32-C3-DevKitM-1 against the pinned
Espressif user guides (tests/corpus/boards.json, esp-dev-kits commit 5c06bf18; marker `corpus`, skip without it).

Every header pin is compared with its row in the guide's header table (No., Name, Type, Function), the header lengths
come from the tables, and every module/button/onboard/USB/note entry has at least one citation whose text (a quote or a
complete table row) is found verbatim in the pinned file of its source. Fetch: `scripts/fetch_corpus.py boards pins`.
"""
import hashlib
import json
import re
from pathlib import Path

import pytest

from circuit_bench.bench_core import boards, sources

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / ".corpus"
MANIFESTS = {n: json.loads((ROOT / "tests" / "corpus" / f"{n}.json").read_text(encoding="utf-8")) for n in ("boards", "pins")}
FILES: dict[str, list[dict]] = {}
for _m in MANIFESTS.values():
    for _e in _m["files"]:
        FILES.setdefault(_e["source_id"], []).append(_e)
COMMIT = "5c06bf1835329d6525f316475f7218aab6acfe79"
NEW = {"esp32-devkitc-v4": "esp32-devkitc", "esp32-c3-devkitm-1": "esp32-c3-devkitm-1"}
_missing = [e["path"] for m in MANIFESTS.values() for e in m["files"] if not (CORPUS / e["path"]).is_file()]
pytestmark = [pytest.mark.corpus,
              pytest.mark.skipif(bool(_missing), reason=f"corpus missing ({len(_missing)} files): "
                                                        "scripts/fetch_corpus.py boards pins")]


def text_of(source_id: str) -> str:
    parts = []
    for e in FILES[source_id]:
        if e.get("excerpt"):
            parts.append((ROOT / "tests" / "corpus" / e["excerpt"]).read_text(encoding="utf-8"))
        elif not e["path"].endswith(".png"):
            parts.append((CORPUS / e["path"]).read_text(encoding="utf-8"))
    return "\n".join(parts)


def guide(board_id: str) -> str:
    return (CORPUS / "esp-dev-kits" / "5c06bf183532" / "docs" / "en" / NEW[board_id] / "user_guide.rst").read_text(
        encoding="utf-8")


# --------------------------------------------------------------------------------------------- RST tables

def _section(text: str, heading: str) -> list[str]:
    """Lines after a `heading` underlined with ^^^ up to the next ^^^/--- heading."""
    lines = text.splitlines()
    for i in range(len(lines) - 1):
        if lines[i].strip() == heading and re.fullmatch(r"\^{3,}", lines[i + 1].strip()):
            out = []
            for j in range(i + 2, len(lines)):
                if j + 1 < len(lines) and re.fullmatch(r"[\^\-=]{3,}", lines[j + 1].strip()) and lines[j].strip() \
                        and not re.fullmatch(r"[=\s]+", lines[j]):
                    break
                out.append(lines[j])
            return out
    raise AssertionError(f"no section {heading!r}")


def list_tables(lines: list[str]) -> list[list[list[str]]]:
    """Every `.. list-table::` in `lines` as rows of cells (header row included)."""
    tables: list[list[list[str]]] = []
    rows: list[list[str]] = []
    inside = False
    for ln in [*lines, ""]:
        s = ln.strip()
        if s.startswith(".. list-table::"):
            if inside:
                tables.append(rows)
            rows, inside = [], True
        elif not inside:
            continue
        elif s.startswith("* - "):
            rows.append([s[4:].strip()])
        elif s.startswith("- ") and rows:
            rows[-1].append(s[2:].strip())
        elif s and not s.startswith(":") and not ln.startswith(" "):
            tables.append(rows)
            rows, inside = [], False
    if inside:
        tables.append(rows)
    return tables


def simple_tables(lines: list[str]) -> list[list[list[str]]]:
    """Every RST simple table (=== rules) in `lines` as rows of cells (header row included)."""
    rule_idx = [i for i, ln in enumerate(lines) if re.fullmatch(r"=+(\s+=+)+\s*", ln)]
    tables = []
    for a, b, c in zip(rule_idx[0::3], rule_idx[1::3], rule_idx[2::3], strict=False):
        starts = [m.start() for m in re.finditer(r"=+", lines[a])]

        def cells(ln, starts=starts):
            return [ln[s:(starts[k + 1] if k + 1 < len(starts) else None)].strip() for k, s in enumerate(starts)]
        tables.append([cells(lines[a + 1])] + [cells(ln) for ln in lines[b + 1:c]])
    return tables


def all_rows(text: str) -> list[list[str]]:
    lines = text.splitlines()
    return [row for t in (*list_tables(lines), *simple_tables(lines)) for row in t]


def header_table(board_id: str, header_id: str) -> list[list[str]]:
    sec = _section(guide(board_id), header_id)
    tables = list_tables(sec) or simple_tables(sec)
    assert tables, header_id
    head, *rows = tables[0]
    assert head[:4] == ["No.", "Name", "Type [1]_", "Function"], head
    return rows


def expected_pin(row: list[str]) -> dict:
    no, name, typ, func = row[:4]
    typ = typ.replace("[1]_", "").strip()
    if typ == "P":
        return {"n": int(no), "label": name, "kind": "power"}
    if typ == "G":
        return {"n": int(no), "label": name, "kind": "ground"}
    if func.split(",")[0].strip() == "CHIP_PU":
        return {"n": int(no), "label": name, "kind": "reset"}
    m = re.match(r"GPIO(\d+)\b", func)
    assert m, row
    return {"n": int(no), "label": name, "kind": "gpio", "gpio": int(m.group(1))}


# --------------------------------------------------------------------------------------------- tests

def test_corpus_hashes_match_manifest():
    for e in MANIFESTS["boards"]["files"]:
        assert hashlib.sha256((CORPUS / e["path"]).read_bytes()).hexdigest() == e["sha256"], e["path"]
        assert f"/{COMMIT}/" in e["url"] and e["path"].startswith("esp-dev-kits/5c06bf183532/")


def test_sources_name_the_pinned_commit_and_hash():
    known = sources.all_sources()
    for e in MANIFESTS["boards"]["files"]:
        src = known[e["source_id"]]
        assert COMMIT in src["url"] and src["retrieved"] == "2026-11-06"
        if not e["path"].endswith(".png"):
            assert e["sha256"] in src["note"], e["source_id"]


@pytest.mark.parametrize(("board_id", "lengths"), [("esp32-devkitc-v4", {"J2": 19, "J3": 19}),
                                                   ("esp32-c3-devkitm-1", {"J1": 15, "J3": 15})])
def test_every_header_pin_matches_its_row_in_the_user_guide(board_id, lengths):
    b = boards.load(board_id)
    assert {h["id"]: len(h["pins"]) for h in b["headers"]} == lengths
    for h in b["headers"]:
        rows = header_table(board_id, h["id"])
        assert len(rows) == lengths[h["id"]], f"{h['id']}: table has {len(rows)} rows"
        assert h["pins"] == [expected_pin(r) for r in rows], h["id"]


@pytest.mark.parametrize("board_id", list(NEW))
def test_every_citation_is_found_in_the_pinned_source(board_id):
    b = boards.load(board_id)
    for c in b["citations"]:
        assert c["source_id"] in FILES, c
        text = text_of(c["source_id"])
        if "quote" in c:
            assert c["quote"] in text, c
        if "row" in c:
            assert c["row"] in all_rows(text), c
        if "table" in c:
            assert c["table"] in [h["id"] for h in b["headers"]]
            header_table(board_id, c["table"])
        if "figure" in c:
            figs = [e for e in FILES[c["source_id"]] if e["path"].endswith("/" + c["figure"])]
            assert len(figs) == 1 and (CORPUS / figs[0]["path"]).is_file(), c
            assert f"figure:: ../../_static/{NEW[board_id]}/{c['figure']}" in guide(board_id)


def _cites(b: dict, about: str) -> list[dict]:
    return [c for c in b["citations"] if c["about"] == about]


def _cite_text(c: dict) -> str:
    return " | ".join([c.get("quote", ""), *c.get("row", [])])


@pytest.mark.parametrize("board_id", list(NEW))
def test_every_entry_of_the_board_is_cited(board_id):
    b = boards.load(board_id)
    abouts = {c["about"] for c in b["citations"]}
    want = {"revision", "module", "headers.side", *(f"headers.{h['id']}" for h in b["headers"])}
    for key in ("buttons", "onboard", "usb", "notes"):
        want |= {f"{key}[{i}]" for i in range(len(b[key]))}
    assert want == abouts
    # onboard: a cited table row or quote names the GPIO and the part
    for i, part in enumerate(b["onboard"]):
        texts = [_cite_text(c) for c in _cites(b, f"onboard[{i}]")]
        assert any(re.search(rf"\bGPIO{part['gpio']}\b", t) and part["what"].split()[0] in t for t in texts), part
    # buttons: the guide's component table has a "<label> Button" row
    for i, label in enumerate(b["buttons"]):
        assert any(f"{label} Button" in c.get("row", []) for c in _cites(b, f"buttons[{i}]")), label
    # USB-to-UART: TX/RX header rows with U0TXD/U0RXD for the two GPIOs, and the bridge row
    for i, u in enumerate(b["usb"]):
        texts = [_cite_text(c) for c in _cites(b, f"usb[{i}]")]
        tx, rx = u["gpios"]
        assert any(f"GPIO{tx}, U0TXD" in t for t in texts) and any(f"GPIO{rx}, U0RXD" in t for t in texts)
        assert any("USB-to-UART Bridge" in t for t in texts)
    # module: the ordering row names the module, the flash size, no PSRAM and the PCB antenna
    m = b["module"]
    rows = [c["row"] for c in _cites(b, "module") if c["source_id"].endswith("ordering")]
    assert rows and {r[0].removesuffix(" (EOL)") for r in rows} == set(m["part_numbers"])
    for r in rows:
        assert r[1:] == [m["name"], f"{m['flash_mb']} MB", "---" if m["psram_mb"] == 0 else f"{m['psram_mb']} MB",
                         "PCB on-board antenna" if m["antenna"] == "pcb" else "External antenna connector"]


def test_header_sides_follow_the_pin_layout_figure_and_the_guide():
    # DevKitC V4: the flash pins sit "on both sides near the USB connector" = the high pin numbers of J2 and J3
    b = boards.load("esp32-devkitc-v4")
    j2, j3 = b["headers"]
    assert [p["label"] for p in j2["pins"][-4:-1]] == ["D2", "D3", "CMD"]
    assert [p["label"] for p in j3["pins"][-3:]] == ["D1", "D0", "CLK"]
    # the side fields rest on the pinned figures (manifest note), read visually: J2 / J1 left, J3 right
    figs = {e["path"].rsplit("/", 1)[1]: e for e in MANIFESTS["boards"]["files"] if e["path"].endswith(".png")}
    assert "left column 3V3, EN, VP" in figs["esp32_devkitC_v4_pinlayout.png"]["figure"]
    assert "left column GND, 3V3, 3V3, IO2" in figs["esp32-c3-devkitm-1-v1-pinout.png"]["figure"]
    assert [h["side"] for h in b["headers"]] == ["left", "right"]
    assert [h["side"] for h in boards.load("esp32-c3-devkitm-1")["headers"]] == ["left", "right"]
