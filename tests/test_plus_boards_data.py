"""Board layouts ESP32-DevKitC V4 and ESP32-C3-DevKitM-1 (schema, consistency with the pin data, pin rules
on the board, route answer). The citation tests against the pinned user guides are in test_plus_boards_corpus.py.
"""
import json
import re
from pathlib import Path

import pytest
import test_api_support as sup
from test_api_support import api  # noqa: F401 - fixture

from circuit_bench.bench_core import boards, pins, sources

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "circuit_bench" / "data"
NEW = ("esp32-devkitc-v4", "esp32-c3-devkitm-1")
ALL = ("esp32-c3-devkitm-1", "esp32-devkitc-v4", "esp32-s3-devkitc-1")
TOP_KEYS = {"schema", "id", "title", "revision", "chip", "source_id", "module", "buttons", "headers", "onboard", "usb",
            "notes", "citations", "drawing"}  # drawing: optional board drawing hints
MODULE_KEYS = {"name", "part_numbers", "variant", "flash_mb", "psram_mb", "antenna", "source_id"}
USB_KINDS = {"usb_serial_jtag", "usb_uart_bridge"}
_ = sup  # the api fixture lives there


def pin_data(chip):
    return json.loads((DATA / "pins" / f"{chip}.json").read_text(encoding="utf-8"))


def pin_rule(chip, rule_id):
    return next(r for r in pin_data(chip)["rules"] if r["id"] == rule_id)


def labels(board, header_id):
    return [p["label"] for h in board["headers"] if h["id"] == header_id for p in h["pins"]]


# --------------------------------------------------------------------------------------------- schema / consistency

def test_board_list_has_all_three_layouts_and_one_default_per_chip():
    assert boards.list is boards.list_boards  # contract name
    assert set(ALL) <= set(boards.ids())  # S2/C6/WT32 boards: tests/test_cboards_data.py
    listed = {b["id"]: b for b in boards.list_boards()}
    assert [listed[i] for i in ALL] == [
        {"id": "esp32-c3-devkitm-1", "title": "ESP32-C3-DevKitM-1", "revision": "v1", "chip": "esp32c3"},
        {"id": "esp32-devkitc-v4", "title": "ESP32-DevKitC", "revision": "V4", "chip": "esp32"},
        {"id": "esp32-s3-devkitc-1", "title": "ESP32-S3-DevKitC-1", "revision": "v1.1", "chip": "esp32s3"}]
    by_chip = {}
    for b in boards.list_boards():
        by_chip.setdefault(b["chip"], []).append(b["id"])
    chips = sorted(p.stem for p in (DATA / "pins").glob("*.json"))
    # every chip has at least one DevKit; the PLAN default per chip is desktop-src/lib/pins.js CHIPS[].devkit
    assert sorted(by_chip) == chips and all(v for v in by_chip.values())


@pytest.mark.parametrize("board_id", ALL)
def test_every_board_is_consistent_with_the_pin_data_of_its_chip(board_id):
    b = boards.load(board_id)
    assert b["schema"] == 1 and b["id"] == board_id
    assert set(b) <= TOP_KEYS
    known = set(sources.all_sources())
    assert b["source_id"] in known
    gpios = {g["num"]: g for g in pin_data(b["chip"])["gpios"]}
    assert [h["side"] for h in b["headers"]] == ["left", "right"]
    seen = []
    for h in b["headers"]:
        assert re.fullmatch(r"J\d+", h["id"])
        assert [p["n"] for p in h["pins"]] == list(range(1, len(h["pins"]) + 1)), h["id"]
        for p in h["pins"]:
            assert p["kind"] in boards.PIN_KINDS
            if p["kind"] == "gpio":
                assert set(p) == {"n", "label", "kind", "gpio"}
                assert p["gpio"] in gpios, f"{h['id']}-{p['n']}: GPIO{p['gpio']} not in {b['chip']} pin data"
                seen.append(p["gpio"])
            else:
                assert set(p) == {"n", "label", "kind"}
    assert len(seen) == len(set(seen)), "a GPIO appears twice on the headers"
    assert boards.broken_out(board_id) == set(seen)
    for part in b.get("onboard", []):
        assert part["gpio"] in set(seen) and part["severity"] in ("info", "caution", "blocked")
        assert part["source_id"] in known
    for u in b.get("usb", []):
        assert u["kind"] in USB_KINDS and u["source_id"] in known
        assert all(g in gpios for g in u["gpios"])
    assert all(isinstance(n, str) and n for n in b.get("notes", []))


@pytest.mark.parametrize("board_id", NEW)
def test_module_is_the_standard_variant_known_to_the_pin_data(board_id):
    b = boards.load(board_id)
    m = b["module"]
    assert set(m) == MODULE_KEYS and m["source_id"] in sources.all_sources()
    variants = {v["id"]: v for v in pin_data(b["chip"])["variants"]}
    # module variants only when the pin data knows them (ESP32); then the board's module is exactly
    # that variant (name, flash, PSRAM) and the desktop default (last variant). C3 pin data has none.
    if variants:
        v = variants[m["variant"]]
        assert (m["name"], m["flash_mb"], m["psram_mb"]) == (v["module"], v["flash_mb"], v["psram_mb"])
        assert pin_data(b["chip"])["variants"][-1]["id"] == m["variant"]
    else:
        assert m["variant"] is None and m["psram_mb"] == 0
    assert b["buttons"] and all(isinstance(x, str) for x in b["buttons"])


def test_devkitc_v4_headers_j2_j3_as_in_the_user_guide():
    b = boards.load("esp32-devkitc-v4")
    assert b["chip"] == "esp32" and b["revision"] == "V4"
    assert [h["id"] for h in b["headers"]] == ["J2", "J3"]
    assert [len(h["pins"]) for h in b["headers"]] == [19, 19]
    assert labels(b, "J2") == ["3V3", "EN", "VP", "VN", "IO34", "IO35", "IO32", "IO33", "IO25", "IO26", "IO27", "IO14",
                               "IO12", "GND", "IO13", "D2", "D3", "CMD", "5V"]
    assert labels(b, "J3") == ["GND", "IO23", "IO22", "TX", "RX", "IO21", "GND", "IO19", "IO18", "IO5", "IO17", "IO16",
                               "IO4", "IO0", "IO2", "IO15", "D1", "D0", "CLK"]
    gp = {f"{h['id']}-{p['n']}": p.get("gpio") for h in b["headers"] for p in h["pins"]}
    assert [gp[f"J2-{n}"] for n in range(3, 19) if n != 14] == [36, 39, 34, 35, 32, 33, 25, 26, 27, 14, 12, 13, 9, 10, 11]
    assert [gp[f"J3-{n}"] for n in range(2, 20) if n != 7] == [23, 22, 1, 3, 21, 19, 18, 5, 17, 16, 4, 0, 2, 15, 8, 7, 6]
    assert boards.layout("esp32-devkitc-v4")["left"][1] == {"header": "J2", "n": 2, "label": "EN", "kind": "reset"}
    # ESP32 GPIOs that do not reach a header: 37, 38 (20, 24, 28-31 do not exist)
    assert {g["num"] for g in pin_data("esp32")["gpios"]} - boards.broken_out("esp32-devkitc-v4") == {37, 38}
    assert b["onboard"] == [{"gpio": 0, "what": "Boot button", "severity": "caution", "source_id": "devkitc-esp32-v4"}]
    assert b["usb"] == [{"label": "UART", "kind": "usb_uart_bridge", "gpios": [1, 3], "source_id": "devkitc-esp32-v4"}]
    assert b["buttons"] == ["EN", "Boot"]
    assert b["module"]["name"] == "ESP32-WROOM-32E" and b["module"]["flash_mb"] == 4
    assert b["module"]["variant"] == "wroom-32e"


def test_c3_devkitm_1_headers_j1_j3_as_in_the_user_guide():
    b = boards.load("esp32-c3-devkitm-1")
    assert b["chip"] == "esp32c3"
    assert [h["id"] for h in b["headers"]] == ["J1", "J3"]
    assert [len(h["pins"]) for h in b["headers"]] == [15, 15]
    assert labels(b, "J1") == ["GND", "3V3", "3V3", "IO2", "IO3", "GND", "RST", "GND", "IO0", "IO1", "IO10", "GND", "5V",
                               "5V", "GND"]
    assert labels(b, "J3") == ["GND", "TX", "RX", "GND", "IO9", "IO8", "GND", "IO7", "IO6", "IO5", "IO4", "GND", "IO18",
                               "IO19", "GND"]
    assert [boards.header_of("esp32-c3-devkitm-1", g) for g in (2, 3, 0, 1, 10)] == ["J1-4", "J1-5", "J1-9", "J1-10", "J1-11"]
    assert [boards.header_of("esp32-c3-devkitm-1", g) for g in (21, 20, 9, 8, 7, 6, 5, 4, 18, 19)] == [
        "J3-2", "J3-3", "J3-5", "J3-6", "J3-8", "J3-9", "J3-10", "J3-11", "J3-13", "J3-14"]
    assert {g["num"] for g in pin_data("esp32c3")["gpios"]} - boards.broken_out("esp32-c3-devkitm-1") == {
        11, 12, 13, 14, 15, 16, 17}
    assert b["onboard"] == [{"gpio": 8, "what": "RGB LED", "severity": "caution", "source_id": "devkitm1-c3-v1"}]
    assert b["usb"] == [{"label": "UART", "kind": "usb_uart_bridge", "gpios": [21, 20], "source_id": "devkitm1-c3-v1"}]
    assert b["buttons"] == ["Boot", "Reset"]
    assert b["module"]["name"] == "ESP32-C3-MINI-1"


def test_layout_adds_module_and_buttons_only_where_the_board_has_them():
    s3 = boards.layout("esp32-s3-devkitc-1")
    # drawing is optional on every board
    assert set(s3) - {"drawing"} == {"id", "title", "revision", "chip", "source_id", "left", "right", "onboard", "usb"}
    for board_id in NEW:
        lay = boards.layout(board_id)
        assert set(lay) - {"drawing"} == set(s3) - {"drawing"} | {"module", "buttons"}
        lay["module"]["name"] = "changed"
        assert boards.load(board_id)["module"]["name"] != "changed"  # a copy, not the cache


# --------------------------------------------------------------------------------------------- pin rules on the boards

def _by_pin(env):
    assert env["ok"], env
    return {p["pin"]: p for p in env["result"]["pins"]}


def test_devkitc_v4_pin_rules():
    a = [{"role": "A", "mode": "adc", "pin": 25}, {"role": "F", "mode": "out", "pin": 6},
         {"role": "N", "mode": "in", "pin": 37}, {"role": "B", "mode": "in", "pin": 0},
         {"role": "I", "mode": "out", "pin": 34}, {"role": "L", "mode": "out", "pin": 16}]
    got = _by_pin(pins.check("esp32", a, wifi=True, devkit="esp32-devkitc-v4"))
    rule_ids = {n: [r["rule_id"] for r in p["reasons"]] for n, p in got.items()}
    assert got[25]["verdict"] == "blocked" and "esp32.adc2_wifi" in rule_ids[25] and got[25]["header"] == "J2-9"
    # GPIO6-11 are on the headers but wired to the flash: still blocked by the chip rule
    assert got[6]["verdict"] == "blocked" and "esp32.spi_flash" in rule_ids[6] and got[6]["header"] == "J3-19"
    assert got[37]["verdict"] == "blocked" and rule_ids[37][0] == "not_broken_out"
    assert got[0]["verdict"] == "caution" and rule_ids[0] == ["esp32.strapping", "onboard"]
    assert got[34]["verdict"] == "blocked" and "esp32.input_only" in rule_ids[34]
    # GPIO16/17 depend on the module (guide footnote [3]): unknown variant -> caution, not_checked
    assert got[16]["verdict"] == "caution" and rule_ids[16] == ["esp32.psram_16_17"] and got[16]["header"] == "J3-12"
    assert got[25]["alternatives"] == [32, 33, 35]  # ADC1 on J2; GPIO34 is taken by role I
    for variant, verdict in (("wroom-32e", "ok"), ("wrover-e", "blocked")):
        env = pins.check("esp32", a, variant=variant, wifi=True, devkit="esp32-devkitc-v4")
        by = _by_pin(env)
        assert by[16]["verdict"] == verdict, variant
        assert [by[n]["verdict"] for n in (25, 6, 37, 0, 34)] == ["blocked", "blocked", "blocked", "caution", "blocked"]
        assert env["summary"].startswith(f"ESP32 {variant.upper()}, Wi-Fi on:")


def test_c3_devkitm_1_pin_rules():
    a = [{"role": "L", "mode": "out", "pin": 8}, {"role": "F", "mode": "out", "pin": 12},
         {"role": "U", "mode": "in", "pin": 19}, {"role": "S", "mode": "in", "pin": 9}]
    got = _by_pin(pins.check("esp32c3", a, wifi=True, devkit="esp32-c3-devkitm-1"))
    rule_ids = {n: [r["rule_id"] for r in p["reasons"]] for n, p in got.items()}
    assert got[8]["verdict"] == "caution" and rule_ids[8] == ["c3.strapping", "onboard"] and got[8]["header"] == "J3-6"
    assert got[12]["verdict"] == "blocked" and rule_ids[12][:2] == ["not_broken_out", "c3.spi_flash"]
    assert got[19]["verdict"] == "caution" and rule_ids[19] == ["c3.usb_jtag"] and got[19]["header"] == "J3-14"
    assert got[9]["verdict"] == "caution" and rule_ids[9] == ["c3.strapping"]
    # TX/RX = U0TXD/U0RXD on the USB-to-UART bridge (analogous to s3.uart0)
    uart = _by_pin(pins.check("esp32c3", [{"role": "T", "mode": "uart_tx", "pin": 21}, {"role": "R", "mode": "uart_rx",
                                                                                         "pin": 20}],
                              wifi=True, devkit="esp32-c3-devkitm-1"))
    assert [(uart[n]["verdict"], uart[n]["rule_ids"], uart[n]["header"]) for n in (21, 20)] == [
        ("caution", ["c3.uart0"], "J3-2"), ("caution", ["c3.uart0"], "J3-3")]
    assert set(boards.load("esp32-c3-devkitm-1")["usb"][0]["gpios"]) == set(pin_rule("esp32c3", "c3.uart0")["pins"])


@pytest.mark.parametrize(("chip", "devkit", "want"), [("esp32", "esp32-devkitc-v4", [4, 18, 19]),
                                                      ("esp32c3", "esp32-c3-devkitm-1", [0, 1, 3])])
def test_suggest_on_the_new_boards_is_deterministic(chip, devkit, want):
    req = [{"role": "LED", "mode": "out"}]
    one = pins.suggest(chip, req, wifi=True, devkit=devkit)
    assert one == pins.suggest(chip, req, wifi=True, devkit=devkit)
    assert [s["gpio"] for s in one["result"]["requests"][0]["suggestions"]] == want
    assert all(s["header"] for s in one["result"]["requests"][0]["suggestions"])


def test_chip_and_board_must_match():
    env = pins.check("esp32s3", [{"role": "A", "mode": "out", "pin": 4}], devkit="esp32-devkitc-v4")
    assert not env["ok"] and env["error"]["code"] == "invalid_args"


# --------------------------------------------------------------------------------------------- route

@pytest.mark.parametrize(("board_id", "summary"), [
    ("esp32-devkitc-v4", "ESP32-DevKitC V4: 38 header pins, 1 onboard part, 1 USB port."),
    ("esp32-c3-devkitm-1", "ESP32-C3-DevKitM-1 v1: 30 header pins, 1 onboard part, 1 USB port.")])
def test_route_answers_the_new_layouts(api, board_id, summary):  # noqa: F811
    env = api.ok(api.get(f"/boards/{board_id}"))
    assert env["action"] == "board.layout" and env["summary"] == summary
    assert env["result"] == boards.layout(board_id)
    # the layout's source, then the module's (ordering information: module name, flash, PSRAM)
    assert [s["id"] for s in env["sources"]] == [env["result"]["source_id"], env["result"]["module"]["source_id"]]
