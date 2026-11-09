"""Board layouts ESP32-S2-DevKitC-1, ESP32-C6-DevKitC-1 v1.2, ESP32-C6-DevKitM-1 and WT32-ETH01 V1.4
(board schema, consistency with the pin data, rails, split headers, layout and route
answers, pin rules on the WT32). Citation tests against the pinned sources: test_cboards_corpus.py.

Checks against the S2/C6 pin data (data/pins/esp32s2.json / esp32c6.json) run when those files exist and are
skipped with a reason otherwise.
"""
import json
import re
from pathlib import Path

import pytest
import test_api_support as sup
from test_api_support import api  # noqa: F401 - fixture

from circuit_bench.bench_core import boards, pins, sources, wiring

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "circuit_bench" / "data"
NEW = ("esp32-s2-devkitc-1", "esp32-c6-devkitc-1", "esp32-c6-devkitm-1", "wt32-eth01")
CHIP = {"esp32-s2-devkitc-1": "esp32s2", "esp32-c6-devkitc-1": "esp32c6", "esp32-c6-devkitm-1": "esp32c6",
        "wt32-eth01": "esp32"}
TOP_KEYS = {"schema", "id", "title", "revision", "chip", "source_id", "module", "buttons", "headers", "onboard", "usb",
            "notes", "citations", "warnings", "connectors", "ethernet", "flash_hint",
            "drawing"}  # drawing: optional board drawing hints
MODULE_KEYS = {"name", "part_numbers", "variant", "flash_mb", "psram_mb", "antenna", "source_id"}
USB_KINDS = {"usb_serial_jtag", "usb_uart_bridge", "usb_otg"}  # usb_otg is drawn only
ETH_KEYS = {"phy", "mdc", "mdio", "power_gpio", "ref_clk", "phy_addr", "source_ids"}
_ = sup  # the api fixture lives there


def pin_file(chip: str) -> Path:
    return DATA / "pins" / f"{chip}.json"


def pin_data(chip: str) -> dict:
    if not pin_file(chip).is_file():
        pytest.skip(f"data/pins/{chip}.json is missing")
    return json.loads(pin_file(chip).read_text(encoding="utf-8"))


def all_pins(b: dict) -> list[tuple[str, dict]]:
    return [(h["id"], p) for h in b["headers"] for p in h["pins"]]


def labels(b: dict, side: str) -> list[str]:
    return [p["label"] for h in b["headers"] if h["side"] == side for p in h["pins"]]


# --------------------------------------------------------------------------------------------- schema / consistency

def test_the_four_layouts_are_listed():
    assert set(NEW) <= set(boards.ids())
    listed = {b["id"]: b for b in boards.list_boards()}
    assert [(listed[i]["title"], listed[i]["revision"], listed[i]["chip"]) for i in NEW] == [
        ("ESP32-S2-DevKitC-1", "v1", "esp32s2"), ("ESP32-C6-DevKitC-1", "v1.2", "esp32c6"),
        ("ESP32-C6-DevKitM-1", "v1", "esp32c6"), ("WT32-ETH01", "V1.4", "esp32")]


@pytest.mark.parametrize("board_id", NEW)
def test_schema_kinds_and_unique_positions(board_id):
    b = boards.load(board_id)
    assert b["schema"] == 1 and b["id"] == board_id and b["chip"] == CHIP[board_id]
    assert set(b) <= TOP_KEYS
    known = set(sources.all_sources())
    assert b["source_id"] in known
    positions, gpios = [], []
    for h in b["headers"]:
        assert re.fullmatch(r"J\d+|PROG|IO", h["id"]) and h["side"] in ("left", "right")
        for p in h["pins"]:
            assert p["kind"] in boards.PIN_KINDS
            assert set(p) == ({"n", "label", "kind", "gpio"} if p["kind"] == "gpio" else {"n", "label", "kind"}), p
            assert isinstance(p["label"], str) and p["label"]
            positions.append((h["id"], p["n"]))
            if p["kind"] == "gpio":
                gpios.append(p["gpio"])
    assert len(positions) == len(set(positions)), "(header id, n) is not unique"
    # each header id (also when split over both sides) numbers its pins 1..N without gaps
    for hid in {h["id"] for h in b["headers"]}:
        assert sorted(n for i, n in positions if i == hid) == list(range(1, 1 + sum(i == hid for i, _ in positions)))
    assert len(gpios) == len(set(gpios)), "a GPIO appears twice on the headers"
    assert boards.broken_out(board_id) == set(gpios)
    for part in b["onboard"]:
        assert part["gpio"] in gpios and part["severity"] in ("info", "caution", "blocked") and part["source_id"] in known
    for u in b["usb"]:
        assert u["kind"] in USB_KINDS and u["source_id"] in known and set(u["gpios"]) <= set(gpios)
    for c in b.get("connectors", []):
        assert c["kind"] == "rj45" and c["label"] and c["source_id"] in known
    ids = [w["id"] for w in b.get("warnings", [])]
    assert len(ids) == len(set(ids))
    for w in b.get("warnings", []):
        assert set(w) == {"id", "severity", "message", "source_id"} and w["severity"] in ("danger", "caution", "info")
        assert w["source_id"] in known and w["message"]
    assert all(isinstance(n, str) and n for n in b["notes"])
    assert isinstance(b["buttons"], list) and all(isinstance(x, str) for x in b["buttons"])
    assert all(c["source_id"] in known for c in b["citations"])


@pytest.mark.parametrize("board_id", NEW)
def test_header_gpios_exist_in_the_pin_data_of_the_chip(board_id):
    b = boards.load(board_id)
    known = {g["num"] for g in pin_data(b["chip"])["gpios"]}
    on = boards.broken_out(board_id)
    assert on <= known
    gone = {"esp32-s2-devkitc-1": set(range(26, 33)), "esp32-c6-devkitc-1": {14, *range(24, 31)},
            "esp32-c6-devkitm-1": {10, 11, *range(24, 31)},
            "wt32-eth01": {6, 7, 8, 9, 10, 11, 13, 16, 18, 19, 21, 22, 23, 25, 26, 27, 34, 37, 38}}[board_id]
    assert known - on == gone


@pytest.mark.parametrize("board_id", NEW)
def test_module(board_id):
    b = boards.load(board_id)
    m = b["module"]
    assert set(m) == MODULE_KEYS and m["source_id"] in sources.all_sources()
    want = {"esp32-s2-devkitc-1": ("ESP32-S2-SOLO-2", None, 8, 2), "esp32-c6-devkitc-1": ("ESP32-C6-WROOM-1", "wroom-1", 8, 0),
            "esp32-c6-devkitm-1": ("ESP32-C6-MINI-1", "mini-1", 4, 0), "wt32-eth01": ("WT32-S1", None, 4, None)}
    assert (m["name"], m["variant"], m["flash_mb"], m["psram_mb"]) == want[board_id]
    if m["variant"] is not None:  # a variant id of data/pins/<chip>.json
        variants = {v["id"]: v for v in pin_data(b["chip"])["variants"]}
        assert m["variant"] in variants
        assert variants[m["variant"]].get("module", m["name"]) == m["name"]


def test_s2_has_no_variants_and_wt32_no_wt32_s1():
    # no S2 variants; no variant wt32-s1 (no manufacturer source on its PSRAM)
    assert boards.load("esp32-s2-devkitc-1")["module"]["variant"] is None
    assert "wt32-s1" not in {v["id"] for v in pin_data("esp32")["variants"]}


@pytest.mark.parametrize("board_id", NEW)
def test_rails_3v3_and_5v_are_power_pins_and_wiring_finds_them(board_id):
    b = boards.load(board_id)
    for rail in ("3V3", "5V"):
        hits = [(hid, p) for hid, p in all_pins(b) if p["label"] == rail]
        assert hits, rail  # every new board has both rails
        assert all(p["kind"] == "power" for _, p in hits), rail
    assert all(p["label"] in ("3V3", "5V") for _, p in all_pins(b) if p["kind"] == "power")
    gpio = sorted(boards.broken_out(board_id))[0]
    board = wiring.Board(board_id, gpio)
    for rail in ("3V3", "5V", "GND"):
        ep = board.rail(rail)
        hid, n = ep.node.rsplit("-", 1)
        pin = next(p for h, p in all_pins(b) if h == hid and p["n"] == int(n))
        assert (pin["kind"], pin["label"] if rail != "GND" else "GND") == ("power" if rail != "GND" else "ground", rail)


# --------------------------------------------------------------------------------------------- the boards

def test_s2_devkitc_1():
    b = boards.load("esp32-s2-devkitc-1")
    assert [(h["id"], h["side"], len(h["pins"])) for h in b["headers"]] == [("J1", "left", 22), ("J3", "right", 22)]
    assert labels(b, "left")[:4] == ["3V3", "3V3", "RST", "4"] and labels(b, "left")[-2:] == ["5V", "G"]
    assert labels(b, "right")[:3] == ["G", "TX", "RX"]
    assert [boards.header_of("esp32-s2-devkitc-1", g) for g in (43, 44, 46, 18, 0, 19, 20)] == [
        "J3-2", "J3-3", "J1-14", "J1-11", "J3-14", "J3-20", "J3-19"]
    assert b["onboard"] == [{"gpio": 18, "what": "RGB LED", "severity": "caution", "source_id": "devkitc1-s2"}]
    assert [(u["kind"], u["gpios"]) for u in b["usb"]] == [("usb_otg", [19, 20]), ("usb_uart_bridge", [43, 44])]
    assert b["buttons"] == ["Reset", "Boot"]
    assert not {"warnings", "connectors", "ethernet", "flash_hint"} & b.keys()


@pytest.mark.parametrize(("board_id", "length", "j1_8"), [("esp32-c6-devkitc-1", 16, "J1-9"),
                                                          ("esp32-c6-devkitm-1", 15, "J1-9")])
def test_c6_devkits(board_id, length, j1_8):
    b = boards.load(board_id)
    assert [(h["id"], h["side"], len(h["pins"])) for h in b["headers"]] == [("J1", "left", length),
                                                                          ("J3", "right", length)]
    assert boards.header_of(board_id, 8) == j1_8
    assert [boards.header_of(board_id, g) for g in (16, 17)] == ["J3-2", "J3-3"]
    assert b["onboard"] == [{"gpio": 8, "what": "RGB LED", "severity": "caution", "source_id": b["source_id"]}]
    assert [(u["kind"], u["gpios"]) for u in b["usb"]] == [("usb_serial_jtag", [12, 13]), ("usb_uart_bridge", [16, 17])]
    assert b["buttons"] == ["Boot", "Reset"]


def test_c6_devkitc_1_nc_and_gpio14():
    b = boards.load("esp32-c6-devkitc-1")
    assert [(hid, p["n"]) for hid, p in all_pins(b) if p["kind"] == "nc"] == [("J1", 16), ("J3", 16)]
    assert boards.header_of("esp32-c6-devkitc-1", 14) is None and boards.header_of("esp32-c6-devkitm-1", 14) == "J1-12"
    assert boards.header_of("esp32-c6-devkitm-1", 10) is None and boards.header_of("esp32-c6-devkitc-1", 10) == "J1-10"
    assert any("GPIO14" in n for n in b["notes"])


def test_wt32_headers_split_over_both_sides():
    b = boards.load("wt32-eth01")
    assert [(h["id"], h["side"]) for h in b["headers"]] == [("PROG", "left"), ("IO", "left"), ("PROG", "right"),
                                                            ("IO", "right")]
    assert labels(b, "left") == ["EN", "GND", "3V3", "EN", "CFG", "485_EN", "RXD", "TXD", "GND", "3V3", "GND", "5V",
                                 "LINK"]
    assert labels(b, "right") == ["TXD", "RXD", "IO0", "GND", "IO39", "IO36", "IO15", "IO14", "IO12", "IO35", "IO4",
                                  "IO2", "GND"]
    assert boards.header_of("wt32-eth01", 0) == "PROG-6"
    assert boards.header_of("wt32-eth01", 39) == "IO-12"
    assert [boards.header_of("wt32-eth01", g) for g in (1, 3, 32, 33, 5, 17, 35)] == [
        "PROG-4", "PROG-5", "IO-2", "IO-3", "IO-4", "IO-5", "IO-17"]
    kinds = {f"{hid}-{p['n']}": p["kind"] for hid, p in all_pins(b)}
    assert kinds["IO-10"] == "signal" and kinds["PROG-1"] == kinds["IO-1"] == "reset"
    assert sum(len(h["pins"]) for h in b["headers"]) == 26


def test_wt32_layout_has_the_danger_warning_and_no_buttons():
    lay = boards.layout("wt32-eth01")
    assert lay["buttons"] == [] and lay["usb"] == []
    assert any(w["severity"] == "danger" and w["id"] == "wt32.power_exclusive" for w in lay["warnings"])
    assert [w["id"] for w in boards.warnings_of("wt32-eth01")] == ["wt32.power_exclusive", "wt32.supply_current"]
    assert lay["connectors"] == [{"kind": "rj45", "label": "LAN", "source_id": "ds-wt32-eth01-v1.4"}]
    assert lay["flash_hint"].startswith("No USB port and no buttons") and "IO0" in lay["flash_hint"]
    assert "never both" in lay["flash_hint"]
    # left side starts with PROG 1-3, then IO 1-10 (header ids kept per pin)
    assert [(p["header"], p["n"]) for p in lay["left"][:4]] == [("PROG", 1), ("PROG", 2), ("PROG", 3), ("IO", 1)]
    lay["warnings"][0]["message"] = "changed"
    assert boards.warnings_of("wt32-eth01")[0]["message"] != "changed"  # a copy, not the cache


def test_wt32_ethernet_and_onboard():
    b = boards.load("wt32-eth01")
    eth = b["ethernet"]
    assert set(eth) <= ETH_KEYS and "phy_addr" not in eth  # PHYAD0 strapping not shown unambiguously
    assert eth == {"phy": "LAN8720A", "mdc": 23, "mdio": 18, "power_gpio": 16, "ref_clk": {"gpio": 0, "mode": "ext_in"},
                   "source_ids": ["sch-wt32-eth01-v1.4", "idf-v6.1-esp-eth"]}
    assert set(eth["source_ids"]) <= set(sources.all_sources())
    on = boards.broken_out("wt32-eth01")
    assert not {eth["mdc"], eth["mdio"], eth["power_gpio"]} & on and eth["ref_clk"]["gpio"] in on
    sev = {p["gpio"]: p["severity"] for p in b["onboard"]}
    assert sev == {0: "blocked", 5: "caution", 17: "caution", 32: "info", 33: "info"}


@pytest.mark.parametrize("board_id", NEW[:3])
def test_devkits_have_no_board_warnings(board_id):
    lay = boards.layout(board_id)
    assert {"module", "buttons"} <= lay.keys() and not {"warnings", "connectors", "ethernet", "flash_hint"} & lay.keys()
    assert boards.warnings_of(board_id) == []


# --------------------------------------------------------------------------------------------- pin rules (WT32: chip esp32)

def _by_pin(env):
    assert env["ok"], env
    return {p["pin"]: p for p in env["result"]["pins"]}


def test_wt32_pin_rules():
    a = [{"role": "C", "mode": "in", "pin": 0}, {"role": "T", "mode": "uart_tx", "pin": 17},
         {"role": "M", "mode": "out", "pin": 23}, {"role": "A", "mode": "adc", "pin": 39},
         {"role": "F", "mode": "in", "pin": 32}, {"role": "O", "mode": "out", "pin": 35}]
    got = _by_pin(pins.check("esp32", a, wifi=True, devkit="wt32-eth01"))
    ids = {n: [r["rule_id"] for r in p["reasons"]] for n, p in got.items()}
    assert got[0]["verdict"] == "blocked" and "onboard" in ids[0] and got[0]["header"] == "PROG-6"
    # GPIO17: module variant unknown (no wt32-s1) -> esp32.psram_16_17 caution, plus the LED4 on TXD2
    assert got[17]["verdict"] == "caution" and ids[17][0] == "esp32.psram_16_17" and "onboard" in ids[17]
    assert got[17]["header"] == "IO-5"
    assert got[23]["verdict"] == "blocked" and ids[23][0] == "not_broken_out"
    assert got[39]["verdict"] == "ok" and got[39]["header"] == "IO-12"
    assert got[32]["verdict"] == "ok" and ids[32] == ["onboard"]  # info only
    assert got[35]["verdict"] == "blocked" and "esp32.input_only" in ids[35]


def test_wt32_suggest_never_offers_gpio0_and_stays_on_the_headers():
    req = [{"role": "LED", "mode": "out"}]
    one = pins.suggest("esp32", req, wifi=True, devkit="wt32-eth01")
    assert one == pins.suggest("esp32", req, wifi=True, devkit="wt32-eth01")
    sugg = one["result"]["requests"][0]["suggestions"]
    assert sugg and all(s["header"] for s in sugg) and 0 not in [s["gpio"] for s in sugg]
    assert {s["gpio"] for s in sugg} <= boards.broken_out("wt32-eth01")


# --------------------------------------------------------------------------------------------- route

@pytest.mark.parametrize(("board_id", "summary"), [
    ("esp32-s2-devkitc-1", "ESP32-S2-DevKitC-1 v1: 44 header pins, 1 onboard part, 2 USB ports."),
    ("esp32-c6-devkitc-1", "ESP32-C6-DevKitC-1 v1.2: 32 header pins, 1 onboard part, 2 USB ports."),
    ("esp32-c6-devkitm-1", "ESP32-C6-DevKitM-1 v1: 30 header pins, 1 onboard part, 2 USB ports."),
    ("wt32-eth01", "WT32-ETH01 V1.4: 26 header pins, 5 onboard parts, 0 USB ports.")])
def test_route_answers_the_new_layouts(api, board_id, summary):  # noqa: F811
    env = api.ok(api.get(f"/boards/{board_id}"))
    assert env["action"] == "board.layout" and env["summary"] == summary
    assert env["result"] == boards.layout(board_id)
    want = list(dict.fromkeys([env["result"]["source_id"], env["result"]["module"]["source_id"]]))
    assert [s["id"] for s in env["sources"]] == want


@pytest.mark.parametrize("board_id", NEW)
def test_desktop_fixture_matches_the_layout(board_id):
    fx = json.loads((ROOT / "desktop-src" / "fixtures" / f"board.{board_id}.json").read_text(encoding="utf-8"))
    assert fx["action"] == "board.layout" and fx["ok"] is True
    assert fx["result"] == boards.layout(board_id)
