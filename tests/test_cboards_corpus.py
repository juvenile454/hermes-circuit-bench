"""Citation tests for the board layouts ESP32-S2-DevKitC-1, ESP32-C6-DevKitC-1 v1.2, ESP32-C6-DevKitM-1
(esp-dev-kits 5c06bf18, tests/corpus/boards.json) and WT32-ETH01 V1.4 (Wireless-Tag datasheet, schematic and wiki
excerpts, ESP-IDF v6.1 esp_eth.rst; tests/corpus/wt32.json). Marker `corpus`, skip without the pinned files.

* DevKits: every header pin equals its row (No., Name, Type, Function) of the user guide's J1/J3 table; footnote
  markup in the name (``18 [#]_``) is dropped from the label.
* WT32: every header pin equals its row of datasheet table 1 (PROG) / table 2 (IO) in the committed excerpt; the
  label is the raw name normalized only by the documented map (note digits, the ``I014`` typo), and the wiki lists the
  same names in the same order.
* Every module/button/onboard/USB/connector/warning/ethernet/flash_hint/note entry has at least one citation whose
  text is found verbatim: RST/inc files of the corpus as pinned, PDFs and wiki pages in the excerpt's segment lines
  (after '@@'), sources without a corpus file (board-esptool-boot-mode) in the note of their source entry.
Fetch: `scripts/fetch_corpus.py boards pins wt32`.
"""
import json
import re
from pathlib import Path

import pytest
from test_plus_boards_corpus import _section, list_tables, simple_tables

from circuit_bench.bench_core import boards, sources

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / ".corpus"
MANIFESTS = {n: json.loads((ROOT / "tests" / "corpus" / f"{n}.json").read_text(encoding="utf-8"))
             for n in ("boards", "pins", "wt32")}
FILES: dict[str, list[dict]] = {}
for _m in MANIFESTS.values():
    for _e in _m["files"]:
        if _e not in FILES.setdefault(_e["source_id"], []):
            FILES[_e["source_id"]].append(_e)
DEVKITS = {"esp32-s2-devkitc-1": "esp32-s2-devkitc-1", "esp32-c6-devkitc-1": "esp32-c6-devkitc-1",
           "esp32-c6-devkitm-1": "esp32-c6-devkitm-1"}
WT32 = "wt32-eth01"
NEW = (*DEVKITS, WT32)
_missing = sorted({e["path"] for m in MANIFESTS.values() for e in m["files"] if not (CORPUS / e["path"]).is_file()})
pytestmark = [pytest.mark.corpus,
              pytest.mark.skipif(bool(_missing), reason=f"corpus missing ({len(_missing)} files): "
                                                        "scripts/fetch_corpus.py boards pins wt32")]

# raw datasheet names -> label: trailing note digit, or the printed typo I014
WT32_LABELS = {"EN1": "EN", "3V32": "3V3", "5V2": "5V", "IO393": "IO39", "IO363": "IO36", "I014": "IO14"}
WT32_NOTES = {"EN1": "注 1", "3V32": "注 2", "5V2": "注 2", "IO393": "注 3", "IO363": "注 3"}


# --------------------------------------------------------------------------------------------- texts

def excerpt_lines(entry: dict) -> list[str]:
    """Segment lines of a committed excerpt ('#' metadata and '@@' markers dropped)."""
    out, inside = [], False
    for line in (ROOT / "tests" / "corpus" / entry["excerpt"]).read_text(encoding="utf-8").split("\n"):
        if line.startswith("@@ "):
            inside = True
        elif inside and line:
            out.append(line)
    return out


def excerpt_meta(entry: dict) -> str:
    text = (ROOT / "tests" / "corpus" / entry["excerpt"]).read_text(encoding="utf-8")
    return " ".join(ln[2:] for ln in text.split("\n@@ ", 1)[0].split("\n") if ln.startswith("# "))


def text_of(source_id: str) -> str:
    parts = []
    for e in FILES[source_id]:
        if e.get("excerpt"):
            parts.append("\n".join(excerpt_lines(e)))
        elif not e["path"].endswith((".png", ".pdf", ".html")):
            parts.append((CORPUS / e["path"]).read_text(encoding="utf-8"))
    return "\n".join(parts)


def guide(board_id: str) -> str:
    return (CORPUS / "esp-dev-kits" / "5c06bf183532" / "docs" / "en" / DEVKITS[board_id] / "user_guide.rst").read_text(
        encoding="utf-8")


def all_rows(text: str) -> list[list[str]]:
    lines = text.splitlines()
    return [row for t in (*list_tables(lines), *simple_tables(lines)) for row in t]


def ds_entry() -> dict:
    return FILES["ds-wt32-eth01-v1.4"][0]


# --------------------------------------------------------------------------------------------- DevKit header tables

def _clean(cell: str) -> str:
    return re.sub(r"\s*\[(#|\d+)\]_", "", cell).strip()


def header_table(board_id: str, header_id: str) -> list[list[str]]:
    sec = _section(guide(board_id), header_id)
    tables = list_tables(sec) or simple_tables(sec)
    assert tables, header_id
    head, *rows = tables[0]
    assert [_clean(c) for c in head[:4]] == ["No.", "Name", "Type", "Function"], head
    return rows


def expected_devkit_pin(row: list[str]) -> dict:
    no, name, typ, func = row[:4]
    n, label, typ = int(no), _clean(name), _clean(typ)
    if typ == "P":
        return {"n": n, "label": label, "kind": "power"}
    if typ == "G":
        return {"n": n, "label": label, "kind": "ground"}
    if label == "NC":
        assert typ == "–" and func == "No connection", row
        return {"n": n, "label": label, "kind": "nc"}
    if label == "RST":
        assert typ == "I" and (func == "CHIP_PU" or func.startswith("High:")), row
        return {"n": n, "label": label, "kind": "reset"}
    m = re.search(r"\bGPIO(\d+)\b", func)
    assert m, row
    return {"n": n, "label": label, "kind": "gpio", "gpio": int(m.group(1))}


# --------------------------------------------------------------------------------------------- WT32 datasheet tables

def wt32_table(title: str) -> list[tuple[str, str, str, list[str]]]:
    """(n, raw name, description, raw lines) per row of datasheet table 1/2 in the excerpt."""
    lines = excerpt_lines(ds_entry())
    start = lines.index(title)
    assert lines[start + 1] == "引脚 名称 描述"
    rows: list[tuple[str, str, str, list[str]]] = []
    pending: list[str] = []
    for ln in lines[start + 2:]:
        if ln.startswith(("表-", "注 1")):
            break
        if re.fullmatch(r"\d+", ln):  # pypdf split a row: number, note digit, then 'name description'
            pending.append(ln)
            continue
        if pending:
            no, *note = pending
            name, desc = ln.split(" ", 1)
            rows.append((no, name + "".join(note), desc, [*pending, ln]))
            pending = []
            continue
        no, name, desc = ln.split(" ", 2)
        rows.append((no, name, desc, [ln]))
    return rows


def expected_wt32_pin(no: str, raw: str, desc: str) -> dict:
    n, label = int(no), WT32_LABELS.get(raw, raw)
    body = desc.split("；")[-1]
    if body == "GND":
        return {"n": n, "label": label, "kind": "ground"}
    if "电源供电" in body or body == "3V3":
        return {"n": n, "label": label, "kind": "power"}
    if body.startswith("使能"):
        return {"n": n, "label": label, "kind": "reset"}
    m = re.match(r"IO(\d+)\b", body)
    if m:
        return {"n": n, "label": label, "kind": "gpio", "gpio": int(m.group(1))}
    assert label == "LINK" and body == "网络连接指示灯引脚", (no, raw, desc)
    return {"n": n, "label": label, "kind": "signal"}


def wt32_pins(header_id: str) -> list[dict]:
    b = boards.load(WT32)
    return sorted((p for h in b["headers"] if h["id"] == header_id for p in h["pins"]), key=lambda p: p["n"])


# --------------------------------------------------------------------------------------------- tests

def test_manifest_and_sources_name_the_pinned_files():
    known = sources.all_sources()
    used = {c["source_id"] for b in NEW for c in boards.load(b)["citations"]}
    for e in [*MANIFESTS["boards"]["files"], *MANIFESTS["wt32"]["files"]]:
        if e["source_id"] in used:
            src = known[e["source_id"]]
            assert src["retrieved"] == "2026-11-06" and e["sha256"] in src["note"], e["source_id"]
    for sid in ("devkitc1-s2", "devkitc1-s2-ordering", "devkitc1-c6-v1.2", "devkitc1-c6-ordering", "devkitm1-c6",
                "devkitm1-c6-ordering", "devkits-eol"):
        assert sid in used and "5c06bf1835329d6525f316475f7218aab6acfe79" in known[sid]["url"], sid


@pytest.mark.parametrize(("board_id", "lengths"), [("esp32-s2-devkitc-1", {"J1": 22, "J3": 22}),
                                                   ("esp32-c6-devkitc-1", {"J1": 16, "J3": 16}),
                                                   ("esp32-c6-devkitm-1", {"J1": 15, "J3": 15})])
def test_every_devkit_header_pin_matches_its_row_in_the_user_guide(board_id, lengths):
    b = boards.load(board_id)
    assert {h["id"]: len(h["pins"]) for h in b["headers"]} == lengths
    for h in b["headers"]:
        rows = header_table(board_id, h["id"])
        assert len(rows) == lengths[h["id"]], f"{h['id']}: table has {len(rows)} rows"
        assert h["pins"] == [expected_devkit_pin(r) for r in rows], h["id"]


def test_c6_devkitc_1_nc_pins_and_s2_footnote_label():
    rows = header_table("esp32-c6-devkitc-1", "J1")
    assert rows[15][:4] == ["16", "NC", "–", "No connection"]
    assert [p["kind"] for h in boards.load("esp32-c6-devkitc-1")["headers"] for p in h["pins"] if p["n"] == 16] == \
        ["nc", "nc"]
    assert header_table("esp32-s2-devkitc-1", "J1")[10][1] == "18 [#]_"
    assert boards.header_of("esp32-s2-devkitc-1", 18) == "J1-11"


@pytest.mark.parametrize(("header_id", "title", "length"), [("PROG", "表-1 调试烧录接口", 6),
                                                            ("IO", "表-2 模块 IO 描述", 20)])
def test_every_wt32_header_pin_matches_its_row_in_the_datasheet(header_id, title, length):
    rows = wt32_table(title)
    assert [int(r[0]) for r in rows] == list(range(1, length + 1))
    assert wt32_pins(header_id) == [expected_wt32_pin(no, raw, desc) for no, raw, desc, _ in rows]
    # every normalization rests on the raw row (cited) and, for note digits, on the note itself
    cited = {tuple(c["quote"].split("\n")) for c in boards.load(WT32)["citations"] if "quote" in c}
    for _no, raw, _desc, raw_lines in rows:
        if raw in WT32_LABELS:
            assert tuple(raw_lines) in cited or len(raw_lines) > 1, raw
            if raw in WT32_NOTES:
                assert any(ln.startswith(WT32_NOTES[raw] + "：") for ln in excerpt_lines(ds_entry())), raw
    # pin 7 is split by pypdf into '7', '2', '3V3 3V3 电源供电' (3V3 + note 2)
    if header_id == "IO":
        assert rows[6][1:] == ("3V32", "3V3 电源供电", ["7", "2", "3V3 3V3 电源供电"])


def test_wt32_wiki_lists_the_same_names_in_the_same_order():
    lines = excerpt_lines(FILES["wiki-wt32-eth01-features"][0])

    def names(heading, end):
        block = lines[lines.index(heading) + 3:lines.index(end)]
        return block[0::2]
    assert names("2.1 Programming/Debugging Pins", "2.2 O Pin Description") == [p["label"] for p in wt32_pins("PROG")]
    io = names("2.2 O Pin Description", "!! When powering, you must choose either the 3V3 power supply OR the 5V power "
                                        "supply!!!")
    assert io == [p["label"] for p in wt32_pins("IO")]


def test_wt32_sides_rest_on_the_reading_of_the_datasheet_photo():
    b = boards.load(WT32)
    side = [c for c in b["citations"] if c["about"] == "headers.side"]
    assert len(side) == 1 and side[0]["source_id"] == "ds-wt32-eth01-v1.4"
    assert side[0]["note"] == "read by eye from the manufacturer photo, datasheet V1.4 p.7; not machine-checkable"
    meta = excerpt_meta(ds_entry())
    row = "TX0, RX0, IO0, GND, IO39, IO36, IO15, IO14, IO12, IO35, IO4, IO2, GND"
    assert row in meta and "page 7" in meta
    right = [p["label"] for h in b["headers"] if h["side"] == "right" for p in h["pins"]]
    assert [{"TX0": "TXD", "RX0": "RXD"}.get(x, x) for x in row.split(", ")] == right
    left = [(h["id"], p["n"]) for h in b["headers"] if h["side"] == "left" for p in h["pins"]]
    assert left == [("PROG", n) for n in (1, 2, 3)] + [("IO", n) for n in range(1, 11)]
    assert any("not machine-checkable" in n.lower() for n in b["notes"])


@pytest.mark.parametrize("board_id", NEW)
def test_every_citation_is_found_in_its_source(board_id):
    b = boards.load(board_id)
    known = sources.all_sources()
    for c in b["citations"]:
        assert c["source_id"] in known, c
        pinned = c["source_id"] in FILES
        text = text_of(c["source_id"]) if pinned else (known[c["source_id"]].get("note") or "")
        if "quote" in c:
            assert c["quote"] in text, c
        if "row" in c:
            assert pinned and c["row"] in all_rows(text), c
        if "table" in c:
            if board_id == WT32:
                assert c["table"] in excerpt_lines(ds_entry()) and wt32_table(c["table"])
            else:
                assert c["table"] in [h["id"] for h in b["headers"]]
                header_table(board_id, c["table"])
        if "document" in c:
            assert any(c["document"] in e["path"] or c["document"] in e["url"] for e in FILES[c["source_id"]]), c
        if "figure" in c:
            assert board_id == WT32 and "not machine-checkable" in c.get("note", ""), c
        assert {"quote", "row", "table", "document", "figure"} & c.keys(), c


def _cites(b: dict, about: str) -> list[dict]:
    return [c for c in b["citations"] if c["about"] == about]


def _texts(b: dict, about: str) -> list[str]:
    return [" | ".join([c.get("quote", ""), *c.get("row", [])]) for c in _cites(b, about)]


@pytest.mark.parametrize("board_id", NEW)
def test_every_entry_of_the_board_is_cited(board_id):
    b = boards.load(board_id)
    abouts = {c["about"] for c in b["citations"]}
    want = {"revision", "module", "headers.side", *(f"headers.{h['id']}" for h in b["headers"])}
    for key in ("buttons", "onboard", "usb", "notes", "connectors", "warnings"):
        want |= {f"{key}[{i}]" for i in range(len(b.get(key, [])))}
    want |= {f"ethernet.{k}" for k in b.get("ethernet", {}) if k != "source_ids"}
    if "flash_hint" in b:
        want.add("flash_hint")
    assert want == abouts
    # onboard: a cited text names the GPIO (GPIOn / IOn) and the part
    words = {0: "REF_CLK", 5: "LED3", 17: "LED4", 32: "CFG", 33: "485_EN"} if board_id == WT32 else {}
    for i, part in enumerate(b["onboard"]):
        texts = _texts(b, f"onboard[{i}]")
        word = words.get(part["gpio"], part["what"])
        assert word in part["what"]
        assert any(re.search(rf"\b(GPIO|IO){part['gpio']}\b", t) for t in texts) and any(word in t for t in texts), part
    for i, label in enumerate(b["buttons"]):
        assert any(f"{label} Button" in c.get("row", []) for c in _cites(b, f"buttons[{i}]")), label
    # USB: the header rows name the GPIOs with their function, plus a component row of the guide
    func = {"usb_uart_bridge": ("U0TXD", "U0RXD"), "usb_serial_jtag": ("USB_D-", "USB_D+"), "usb_otg": ("USB_D-", "USB_D+")}
    for i, u in enumerate(b["usb"]):
        texts = _texts(b, f"usb[{i}]")
        for gpio, f in zip(u["gpios"], func[u["kind"]], strict=True):
            assert any(re.search(rf"\bGPIO{gpio}\b", t) and f in t for t in texts), (u, f)
        component = {"usb_uart_bridge": "USB-to-UART Bridge", "usb_serial_jtag": "USB Type-C Port",
                     "usb_otg": "USB OTG"}[u["kind"]]
        assert any(component in t for t in texts), u


@pytest.mark.parametrize("board_id", list(DEVKITS))
def test_devkit_module_matches_its_ordering_row(board_id):
    b = boards.load(board_id)
    m = b["module"]
    rows = [c["row"] for c in _cites(b, "module") if c["source_id"].endswith("ordering")]
    assert rows and {r[0] for r in rows} == set(m["part_numbers"])
    for r in rows:
        assert r[1:] == [m["name"], f"{m['flash_mb']} MB", "---" if m["psram_mb"] == 0 else f"{m['psram_mb']} MB",
                         "PCB on-board antenna" if m["antenna"] == "pcb" else "External antenna connector"]
    # the ordering table has exactly these current (non-EOL) rows with this module
    table = all_rows(text_of(m["source_id"]))
    assert [r for r in table if r[1] == m["name"] and "(EOL)" not in r[0]] == rows


def test_devkit_header_sides_are_marked_unverified():
    # the pin layout figures of the three new guides are not pinned: J1 left / J3 right like the other DevKits, noted
    for board_id in DEVKITS:
        b = boards.load(board_id)
        assert [(h["id"], h["side"]) for h in b["headers"]] == [("J1", "left"), ("J3", "right")]
        assert any("unverified" in n and "pin layout figure" in n for n in b["notes"]), board_id
        figs = [c["quote"] for c in b["citations"] if c.get("quote", "").startswith("figure:: ")]
        assert figs and all(f in guide(board_id) for f in figs)
        assert not any(e["path"].endswith(f.rsplit("/", 1)[1]) for f in figs for e in MANIFESTS["boards"]["files"])


def test_wt32_module_warnings_ethernet_and_flash_hint_rest_on_the_quotes():
    b = boards.load(WT32)
    m = b["module"]
    mod = _texts(b, "module")
    assert any(m["name"] in t for t in mod) and any("Flash 32Mbit" in t for t in mod) and m["flash_mb"] == 4
    assert m["variant"] is None and m["psram_mb"] is None  # no manufacturer source on the WT32-S1 PSRAM
    w = {x["id"]: x for x in b["warnings"]}
    assert w["wt32.power_exclusive"]["severity"] == "danger"
    i = [x["id"] for x in b["warnings"]].index("wt32.power_exclusive")
    assert any("3V3" in t and "5V" in t for t in _texts(b, f"warnings[{i}]"))
    j = [x["id"] for x in b["warnings"]].index("wt32.supply_current")
    assert w["wt32.supply_current"]["severity"] == "caution" and "500 mA" in w["wt32.supply_current"]["message"]
    assert any("最小：500 mA" in t for t in _texts(b, f"warnings[{j}]"))
    eth = b["ethernet"]
    assert any(eth["phy"] in t for t in _texts(b, "ethernet.phy"))
    for key, net in (("mdc", "RMII_MDC"), ("mdio", "RMII_MDIO"), ("power_gpio", "OSC_EN")):
        assert any(f"IO{eth[key]}_{net}" in t for t in _texts(b, f"ethernet.{key}")), key
    ref = _texts(b, "ethernet.ref_clk")
    assert any(f"IO{eth['ref_clk']['gpio']}_RMII_EMAC_REF_CLK" in t for t in ref)
    assert eth["ref_clk"]["mode"] == "ext_in" and any("EMAC_CLK_EXT_IN" in t for t in ref)
    hint = _texts(b, "flash_hint")
    assert any("GPIO0 is held low on reset" in t for t in hint)
    assert all(any(t.startswith(f"{n} ") and "预留调试烧录接口" in t for t in hint) for n in (1, 4, 5, 6))
    assert {c["source_id"] for c in _cites(b, "flash_hint")} >= {"board-esptool-boot-mode", "ds-wt32-eth01-v1.4"}
    # the schematic/datasheet conflict is a note with both sides cited
    k = next(i for i, n in enumerate(b["notes"]) if n.startswith("Conflict"))
    assert {c["source_id"] for c in _cites(b, f"notes[{k}]")} >= {"sch-wt32-eth01-v1.4", "ds-wt32-eth01-v1.4",
                                                                  "wiki-wt32-eth01-features"}
    assert any("IO35_RXD2" in t for t in _texts(b, f"notes[{k}]"))
