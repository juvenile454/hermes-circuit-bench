"""Breakout labels for module pins (SDA, SCL, VCC, GND, MOSI, CS ...).

A label is derived from the pin's ``signal`` (already cited from the datasheet) and only counts when exactly one pin
of the active variant carries that signal. A real pin name always wins; the project stores the chip pin name; every
mapping is named in the answer as an assumption ``pin_alias``. Runs against the real module catalog.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from test_api_support import api  # noqa: F401 - fixture

from circuit_bench import schemas, tools
from circuit_bench.bench_core import contracts, modspec, modules, project

ROOT = Path(__file__).resolve().parent.parent
PID = "alias-bench"


def _pins(mid, variant=None):
    return modules.catalog().get(mid, variant)["pins"]


@pytest.fixture
def proj():
    res = project.create(PID, "Alias bench", "esp32s3", "n16r8", "esp32-s3-devkitc-1")
    assert res["ok"], res
    return res["result"]["project"]


def _up(*ops):
    rev = project.get(PID)["result"]["rev"]
    return project.update(PID, rev, list(ops), by="agent")


def _ok(*ops):
    res = _up(*ops)
    assert res["ok"], res["error"]
    assert contracts.validate_envelope(res) == []
    assert project.validate(res["result"]["project"]) == []
    return res


def _bad(*ops):
    before = project.get(PID)["result"]["rev"]
    res = _up(*ops)
    assert res["ok"] is False, res["summary"]
    assert res["error"]["code"] == "invalid_args", res["error"]
    assert contracts.validate_envelope(res) == []
    assert project.get(PID)["result"]["rev"] == before  # all or nothing
    return res["error"]["message"] + " | " + (res["error"].get("hint") or "")


def _part(res, ref="U1"):
    return next(x for x in res["result"]["project"]["parts"] if x["ref"] == ref)


def _aliases(res):
    return [a for a in res["assumptions"] if a["key"] == "pin_alias"]


# --------------------------------------------------------------------------------------------- the table

def test_label_table_is_the_agreed_one():
    assert modspec.PIN_LABELS == {
        "i2c_sda": ("SDA",), "i2c_scl": ("SCL",),
        "spi_sck": ("SCK", "SCLK", "CLK"), "spi_sdi": ("MOSI", "SDI", "DIN", "SI"),
        "spi_sdo": ("MISO", "SDO", "DOUT", "SO"), "spi_cs": ("CS", "SS", "NSS", "CSN"),
        "gnd": ("GND", "VSS"), "supply": ("VCC", "VDD"),
    }
    labels = [x for v in modspec.PIN_LABELS.values() for x in v]
    assert len(labels) == len(set(labels))  # each label belongs to one signal
    assert set(modspec.PIN_LABELS) <= set(modspec.SIGNALS)
    for never in ("VIN", "3V3", "5V", "RX", "TX", "RXD", "TXD"):  # regulator inputs and UART names stay out
        assert never not in labels


def test_resolve_pin_bme280():
    pins = _pins("bme280")
    assert modspec.resolve_pin(pins, "SDA") == {"pin": "SDI", "via": "label", "candidates": []}
    assert modspec.resolve_pin(pins, "SCL") == {"pin": "SCK", "via": "label", "candidates": []}
    assert modspec.resolve_pin(pins, "VCC") == {"pin": None, "via": None, "candidates": ["VDD", "VDDIO"]}
    assert modspec.resolve_pin(pins, "GND") == {"pin": "GND", "via": "name", "candidates": []}
    assert modspec.resolve_pin(pins, "sdi") == {"pin": "SDI", "via": "case", "candidates": []}
    # a real name beats a label even when the label alone would be ambiguous (VDD is a supply label)
    assert modspec.resolve_pin(pins, "vdd") == {"pin": "VDD", "via": "case", "candidates": []}
    # SDO is a real pin (address select), not the SPI data-out label
    assert modspec.resolve_pin(pins, "SDO") == {"pin": "SDO", "via": "name", "candidates": []}
    assert modspec.resolve_pin(pins, "MOSI") == {"pin": None, "via": None, "candidates": []}


def test_labels_never_cover_regulator_inputs_or_uart():
    pins = [{"name": "RXD", "signal": "uart_rx"}, {"name": "TXD", "signal": "uart_tx"},
            {"name": "VDD", "signal": "supply"}, {"name": "VOUT", "signal": "power_out"}]
    for name in ("RX", "TX", "VIN", "3V3", "5V"):
        assert modspec.resolve_pin(pins, name)["pin"] is None, name
    assert modspec.resolve_pin(pins, "VCC")["pin"] == "VDD"  # power_out (a regulator output) is never a candidate
    assert modspec.resolve_pin(pins, "GND") == {"pin": None, "via": None, "candidates": []}


def test_pins_hint_names_the_labels():
    assert modspec.pins_hint(_pins("bme280")) == "GND, CSB, SDI (SDA), SCK (SCL), SDO, VDDIO, VDD"


def test_label_table_over_the_whole_catalog():
    """Every catalog entry and variant: a unique answer is a pin of that variant carrying the label's signal (or the
    real pin of that name); an ambiguous one lists at least two such pins (or, for a bus label, pins named like it)."""
    cat = modules.catalog()
    seen = 0
    for mid in cat.ids():
        for vid in [None, *[v["id"] for v in cat.get(mid).get("variants") or []]]:
            pins = cat.get(mid, vid)["pins"]
            sig = {p["name"]: p["signal"] for p in pins}
            for label, res in modspec.label_table(pins).items():
                seen += 1
                if res["via"] == "label":
                    assert sig[res["pin"]] == modspec.LABEL_SIGNAL[label], (mid, vid, label, res)
                elif res["pin"] is not None:
                    assert res["pin"].upper() == label, (mid, vid, label, res)
                else:
                    assert len(res["candidates"]) >= 2, (mid, vid, label, res)
                    assert all(sig[c] == modspec.LABEL_SIGNAL[label] or c.casefold().startswith(label.casefold())
                               for c in res["candidates"]), (mid, vid, label, res)
    assert seen > 1000


# --------------------------------------------------------------------------------------------- supply and ground labels
# A supply or ground label only maps to a pin that itself is named like that row (VCC/VDD, GND/VSS): VCC on a
# regulator input, a motor supply, a relay coil or a gate is not sure, so it is refused as unknown, never guessed.

POWER_ROWS = {"gnd": ("GND", "VSS"), "supply": ("VCC", "VDD")}
REFUSED = [  # (module, variant, label, start of the pins hint)
    ("ap2112k_33", None, "VCC", "VIN, GND, EN, NC, VOUT"),
    ("drv8833", None, "VCC", "AIN1, AIN2, BIN1, BIN2"),
    ("g5le", None, "VCC", "COIL1, COIL2, COM, NO, NC"),
    ("uln2003a", None, "VCC", "1B, 2B, 3B"),
    ("bss138", None, "VCC", "G, S, D"),
    ("sim800l", None, "VCC", "VBAT, GND, RXD, TXD"),
    ("ina219", None, "VCC", "IN+, IN-, GND, VS, SCL, SDA, A0, A1"),
    ("hx711", None, "GND", "VSUP, BASE, AVDD, VFB, AGND, VBG"),
    ("tp4056", "module-dw01", "GND", "IN+, IN-, B+, B-, OUT+, OUT-"),
]


@pytest.mark.parametrize(("mid", "variant", "label", "hint"), REFUSED, ids=[f"{r[0]}-{r[2]}" for r in REFUSED])
def test_power_label_on_an_other_named_pin_is_unknown(mid, variant, label, hint):
    pins = _pins(mid, variant)
    assert modspec.resolve_pin(pins, label) == {"pin": None, "via": None, "candidates": []}
    assert label not in modspec.label_table(pins)
    text = modspec.pins_hint(pins)
    assert text.startswith(hint), text
    for other in POWER_ROWS["gnd" if label == "GND" else "supply"]:  # no such label behind any pin of the hint
        assert not re.search(r"\([^)]*\b" + other + r"\b[^)]*\)", text), text


@pytest.mark.parametrize(("mid", "variant", "label", "hint"), REFUSED, ids=[f"{r[0]}-{r[2]}" for r in REFUSED])
def test_power_label_on_an_other_named_pin_is_refused(proj, mid, variant, label, hint):
    op = {"op": "add_module", "module": mid, "conn": {label: "GND" if label == "GND" else "3V3"}}
    if variant:
        op["variant"] = variant
    msg = _bad(op)
    assert f"module {mid} has no pin {label!r}" in msg
    assert "fits more than one pin" not in msg
    assert f"pins: {hint}" in msg


def test_power_labels_between_each_other_still_map(proj):
    assert modspec.resolve_pin(_pins("ssd1306"), "VCC") == {"pin": "VDD", "via": "label", "candidates": []}
    assert modspec.resolve_pin(_pins("sht31"), "GND") == {"pin": "VSS", "via": "label", "candidates": []}
    assert modspec.resolve_pin(_pins("24lc256"), "VDD") == {"pin": "VCC", "via": "label", "candidates": []}
    assert modspec.resolve_pin(_pins("24lc256"), "gnd") == {"pin": "VSS", "via": "label", "candidates": []}
    res = _ok({"op": "add_module", "module": "24lc256", "conn": {"VDD": "3V3", "GND": "GND"}})
    assert _part(res)["conn"] == {"VCC": "3V3", "VSS": "GND"}
    assert [a["value"] for a in _aliases(res)] == ["VDD → VCC", "GND → VSS"]


def test_bme280_vcc_stays_ambiguous_although_one_pin_is_vdd():
    assert modspec.resolve_pin(_pins("bme280"), "VCC") == {"pin": None, "via": None, "candidates": ["VDD", "VDDIO"]}


def test_power_labels_over_the_whole_catalog():
    """Every catalog entry and variant: each supply or ground label that maps ends on a pin named like its row."""
    cat = modules.catalog()
    mapped = 0
    for mid in cat.ids():
        for vid in [None, *[v["id"] for v in cat.get(mid).get("variants") or []]]:
            pins = cat.get(mid, vid)["pins"]
            for label, res in modspec.label_table(pins).items():
                row = modspec.LABEL_SIGNAL[label]
                if row in POWER_ROWS and res["pin"] is not None:
                    mapped += 1
                    assert res["pin"].upper() in POWER_ROWS[row], (mid, vid, label, res)
            hint = modspec.pins_hint(pins)
            for p in pins:  # the hint never puts a label behind a supply or ground pin named otherwise
                if p.get("signal") in POWER_ROWS and p["name"].upper() not in POWER_ROWS[p["signal"]]:
                    assert not re.search(r"(?:^|, )" + re.escape(p["name"]) + r" \(", hint), (mid, vid, hint)
    assert mapped > 100


# --------------------------------------------------------------------------------------------- bus labels and prefixes
# A bus label (I²C/SPI rows) does not count when another pin of the active variant has a name starting with it (any
# case): CLK on a chip with a clock output CLKOUT may mean either pin, so it is ambiguous, never guessed. The target
# pin itself (CS on CSn, CS on CSX ...) does not count as such another pin.

BUS_ROWS = frozenset(modspec.PIN_LABELS) - modspec.POWER_SIGNALS
PREFIX_REFUSED = {("enc28j60", None, "CLK"), ("mcp2515", None, "CLK")}  # (module, variant, label)


@pytest.mark.parametrize("mid", ["enc28j60", "mcp2515"])
def test_clk_next_to_clkout_is_ambiguous(mid):
    pins = _pins(mid)
    assert modspec.resolve_pin(pins, "CLK") == {"pin": None, "via": None, "candidates": ["CLKOUT", "SCK"]}
    assert modspec.resolve_pin(pins, "clk") == {"pin": None, "via": None, "candidates": ["CLKOUT", "SCK"]}
    assert modspec.label_table(pins)["CLK"]["candidates"] == ["CLKOUT", "SCK"]
    assert modspec.resolve_pin(pins, "SCLK") == {"pin": "SCK", "via": "label", "candidates": []}
    assert modspec.resolve_pin(pins, "SCK") == {"pin": "SCK", "via": "name", "candidates": []}
    assert modspec.resolve_pin(pins, "CLKOUT") == {"pin": "CLKOUT", "via": "name", "candidates": []}
    assert not re.search(r"\([^)]*\bCLK\b[^)]*\)", modspec.pins_hint(pins))


@pytest.mark.parametrize("mid", ["enc28j60", "mcp2515"])
def test_clk_next_to_clkout_is_refused(proj, mid):
    msg = _bad({"op": "add_module", "module": mid, "conn": {"CLK": "GPIO12"}})
    assert f"'CLK' fits more than one pin of {mid} (CLKOUT, SCK): name the pin" in msg
    res = _ok({"op": "add_module", "module": mid, "conn": {"SCLK": "GPIO12", "CS": "GPIO10"}})
    assert _part(res)["conn"] == {"SCK": "GPIO12", "CS": "GPIO10"}
    assert [a["value"] for a in _aliases(res)] == ["SCLK → SCK"]
    res = _ok({"op": "add_module", "module": mid, "conn": {"SCK": "GPIO13"}})
    assert _part(res, "U2")["conn"] == {"SCK": "GPIO13"}
    assert [a["value"] for a in _aliases(res)] == []


def test_the_target_pin_itself_does_not_count(proj):
    pins = _pins("bme280")
    assert modspec.resolve_pin(pins, "SDA") == {"pin": "SDI", "via": "label", "candidates": []}
    assert modspec.resolve_pin(pins, "SCL") == {"pin": "SCK", "via": "label", "candidates": []}
    assert modspec.resolve_pin(pins, "CS") == {"pin": None, "via": None, "candidates": []}  # CSB is mode_select
    assert modspec.resolve_pin(_pins("cc1101"), "CS") == {"pin": "CSn", "via": "label", "candidates": []}
    assert modspec.resolve_pin(_pins("gc9a01"), "CS") == {"pin": "CSX", "via": "label", "candidates": []}
    assert modspec.resolve_pin(_pins("mcp3008"), "CS") == {"pin": "CS/SHDN", "via": "label", "candidates": []}
    res = _ok({"op": "add_module", "module": "cc1101", "conn": {"CS": "GPIO10", "CLK": "GPIO12"}})
    assert _part(res)["conn"] == {"CSn": "GPIO10", "SCLK": "GPIO12"}
    assert [a["value"] for a in _aliases(res)] == ["CS → CSn", "CLK → SCLK"]


def test_power_labels_ignore_prefixes():
    """Only the bus rows look at other pin names; supply and ground labels keep their own rule."""
    pins = [{"name": "VDD", "signal": "supply"}, {"name": "VCCIO_EN", "signal": "digital_in"},
            {"name": "GND", "signal": "gnd"}, {"name": "VSSA_SENSE", "signal": "analog_in"}]
    assert modspec.resolve_pin(pins, "VCC") == {"pin": "VDD", "via": "label", "candidates": []}
    assert modspec.resolve_pin(pins, "VSS") == {"pin": "GND", "via": "label", "candidates": []}
    assert modspec.resolve_pin(_pins("bme280"), "VCC") == {"pin": None, "via": None, "candidates": ["VDD", "VDDIO"]}


def test_bus_labels_and_prefixes_over_the_whole_catalog():
    """Every catalog entry and variant: no bus label maps while another pin's name starts with it, and the pairs this
    refuses (where one pin alone carries the label's signal) are exactly the listed ones."""
    cat = modules.catalog()
    mapped, refused = 0, set()
    for mid in cat.ids():
        for vid in [None, *[v["id"] for v in cat.get(mid).get("variants") or []]]:
            pins = cat.get(mid, vid)["pins"]
            names = [p["name"] for p in pins]
            for label, sig in modspec.LABEL_SIGNAL.items():
                if sig not in BUS_ROWS or any(n.casefold() == label.casefold() for n in names):
                    continue  # a real pin name wins before any label
                fits = [p["name"] for p in pins if p.get("signal") == sig]
                res = modspec.resolve_pin(pins, label)
                if res["via"] == "label":
                    mapped += 1
                    others = [n for n in names if n != res["pin"] and n.casefold().startswith(label.casefold())]
                    assert others == [], (mid, vid, label, res, others)
                elif len(fits) == 1:
                    refused.add((mid, vid, label))
                    others = [n for n in names if n != fits[0] and n.casefold().startswith(label.casefold())]
                    assert others, (mid, vid, label, res)
                    assert res == {"pin": None, "via": None, "candidates": sorted([fits[0], *others])}
    assert refused == PREFIX_REFUSED
    assert mapped > 300


# --------------------------------------------------------------------------------------------- add_module

def test_bme280_breakout_labels(proj):
    res = _ok({"op": "add_module", "module": "bme280",
               "conn": {"SDA": "GPIO8", "SCL": "GPIO9", "GND": "GND", "VDD": "3V3"}})
    assert _part(res)["conn"] == {"SDI": "GPIO8", "SCK": "GPIO9", "GND": "GND", "VDD": "3V3"}  # chip names stored
    al = _aliases(res)
    assert [a["value"] for a in al] == ["SDA → SDI", "SCL → SCK"]
    assert al[0]["reason"].startswith("bme280: I²C data pin, catalog pin SDI")
    assert "SDA in I²C mode" in al[0]["reason"]  # the pin's own note
    stored = json.loads((project.path(PID) / "project.json").read_text(encoding="utf-8"))
    assert "SDA" not in json.dumps(stored["parts"])


def test_bme280_vcc_is_ambiguous(proj):
    msg = _bad({"op": "add_module", "module": "bme280", "conn": {"VCC": "3V3"}})
    assert "'VCC' fits more than one pin of bme280 (VDD, VDDIO): name the pin" in msg


def test_unknown_pin_hint_lists_the_labels(proj):
    msg = _bad({"op": "add_module", "module": "bme280", "conn": {"MISO": "GPIO3"}})
    assert "module bme280 has no pin 'MISO'" in msg
    assert "pins: GND, CSB, SDI (SDA), SCK (SCL), SDO, VDDIO, VDD" in msg


def test_ssd1306_vcc(proj):
    res = _ok({"op": "add_module", "module": "ssd1306", "conn": {"VCC": "3V3", "GND": "GND"}})
    assert _part(res)["conn"] == {"VDD": "3V3", "GND": "GND"}
    assert [a["value"] for a in _aliases(res)] == ["VCC → VDD"]


def test_sht31_gnd(proj):
    res = _ok({"op": "add_module", "module": "sht31", "conn": {"GND": "GND", "VCC": "3V3"}})
    assert _part(res)["conn"] == {"VSS": "GND", "VDD": "3V3"}
    assert [a["value"] for a in _aliases(res)] == ["GND → VSS", "VCC → VDD"]


def test_pca9306_sda_is_ambiguous(proj):
    msg = _bad({"op": "add_module", "module": "pca9306", "conn": {"SDA": "GPIO8"}})
    assert "'SDA' fits more than one pin of pca9306 (SDA1, SDA2): name the pin" in msg


def test_mcp3008_gnd_is_ambiguous(proj):
    msg = _bad({"op": "add_module", "module": "mcp3008", "conn": {"GND": "GND"}})
    assert "'GND' fits more than one pin of mcp3008 (AGND, DGND): name the pin" in msg
    res = _ok({"op": "add_module", "module": "mcp3008", "conn": {"MOSI": "GPIO11", "CS": "GPIO10"}})
    assert _part(res)["conn"] == {"DIN": "GPIO11", "CS/SHDN": "GPIO10"}


def test_st7735s_real_sda_wins(proj):
    res = _ok({"op": "add_module", "module": "st7735s", "conn": {"SDA": "GPIO11", "SCK": "GPIO12"}})
    assert _part(res)["conn"] == {"SDA": "GPIO11", "SCL": "GPIO12"}
    assert [a["value"] for a in _aliases(res)] == ["SCK → SCL"]  # SDA is the real name: no mapping
    msg = _bad({"op": "add_module", "module": "st7735s", "conn": {"MOSI": "GPIO11", "SDA": "GPIO13"}})
    assert "'MOSI' and 'SDA' both name pin SDA of st7735s" in msg


def test_variant_with_its_own_pin_list(proj):
    res = _ok({"op": "add_module", "module": "ssd1306", "variant": "spi4",
               "conn": {"MOSI": "GPIO11", "SCK": "GPIO12", "CS": "GPIO10", "VCC": "3V3"}})
    assert _part(res)["conn"] == {"SDIN": "GPIO11", "SCLK": "GPIO12", "CS": "GPIO10", "VDD": "3V3"}
    msg = _bad({"op": "add_module", "module": "ssd1306", "conn": {"MOSI": "GPIO11"}})  # the I²C base has no MOSI
    assert "module ssd1306 has no pin 'MOSI'" in msg


def test_label_and_its_pin_together_are_refused(proj):
    msg = _bad({"op": "add_module", "module": "bme280", "conn": {"SDA": "GPIO8", "SDI": "GPIO8"}})
    assert "'SDA' and 'SDI' both name pin SDI of bme280" in msg
    _bad({"op": "add_module", "module": "bme280", "conn": {"sdi": "GPIO8", "SDI": "GPIO8"}})


def test_add_parts_with_a_module_maps_too(proj):
    res = _ok({"op": "add_parts", "parts": [{"ref": "U7", "kind": "module", "value": "BME280", "module": "bme280",
                                             "conn": {"SDA": "GPIO8"}}]})
    assert _part(res, "U7")["conn"] == {"SDI": "GPIO8"}
    assert [a["value"] for a in _aliases(res)] == ["SDA → SDI"]


def test_plain_parts_are_untouched(proj):
    res = _ok({"op": "add_parts", "parts": [{"ref": "R1", "kind": "resistor", "value": "10k",
                                             "conn": {"1": "3V3", "2": "SDA"}}]})
    assert _part(res, "R1")["conn"] == {"1": "3V3", "2": "SDA"}
    assert _aliases(res) == []


# --------------------------------------------------------------------------------------------- connect

def test_connect_with_labels_and_null(proj):
    _ok({"op": "add_module", "module": "bme280", "conn": {"SDA": "GPIO8", "SCL": "GPIO9"}})
    res = _ok({"op": "connect", "ref": "U1", "conn": {"GND": "GND", "SCL": "GPIO7"}})
    assert _part(res)["conn"] == {"SDI": "GPIO8", "SCK": "GPIO7", "GND": "GND"}
    assert [a["value"] for a in _aliases(res)] == ["SCL → SCK"]
    res = _ok({"op": "connect", "ref": "U1", "conn": {"SDA": None}})  # null through the label unlinks SDI
    assert _part(res)["conn"] == {"SCK": "GPIO7", "GND": "GND"}
    assert [a["value"] for a in _aliases(res)] == ["SDA → SDI"]
    msg = _bad({"op": "connect", "ref": "U1", "conn": {"VCC": None}})
    assert "'VCC' fits more than one pin of bme280 (VDD, VDDIO)" in msg


def test_connect_null_of_a_stored_pin_always_works(proj, monkeypatch):
    """A stored pin name is unlinked as it is, also when the catalog no longer knows the module."""
    _ok({"op": "add_module", "module": "bme280", "conn": {"SDA": "GPIO8", "SCL": "GPIO9"}})

    class Gone:
        def has(self, key):
            return False

    monkeypatch.setattr(project, "_catalog", lambda: Gone())
    res = _ok({"op": "connect", "ref": "U1", "conn": {"SDI": None}})
    assert _part(res)["conn"] == {"SCK": "GPIO9"}


# --------------------------------------------------------------------------------------------- tool, route, schema

def test_tool_answer_names_the_mapping():
    host = tools.Host(hook_active=True)
    h = tools.make_handlers(host)["bench_project"]
    env = json.loads(h({"action": "create", "id": "alias-tool", "title": "T", "chip": "esp32s3", "variant": "n16r8"}))
    assert env["ok"], env
    env = json.loads(h({"action": "add_module", "id": "alias-tool", "module": "bme280",
                        "conn": {"SDA": "GPIO8", "SCL": "GPIO9", "VDD": "3V3", "GND": "GND"}}))
    assert env["ok"], env
    assert contracts.validate_envelope(env) == []
    assert {"SDA → SDI", "SCL → SCK"} <= {a["value"] for a in env["assumptions"] if a["key"] == "pin_alias"}
    mod = next(x for x in env["result"]["modules"] if x["ref"] == "U1")
    assert set(mod["conn"]) == {"SDI", "SCK", "VDD", "GND"}


def test_route_answer_names_the_mapping(api):  # noqa: F811
    api.create("alias-route")
    body = api.ok(api.patch("/projects/alias-route", {"expected_rev": 1, "ops": [
        {"op": "add_module", "module": "bme280", "conn": {"SDA": "GPIO8", "SCL": "GPIO9"}}]}))
    assert [a["value"] for a in body["assumptions"] if a["key"] == "pin_alias"] == ["SDA → SDI", "SCL → SCK"]
    part = body["result"]["project"]["parts"][0]
    assert part["conn"] == {"SDI": "GPIO8", "SCK": "GPIO9"}
    bad = api.err(api.patch("/projects/alias-route", {"expected_rev": 2, "ops": [
        {"op": "connect", "ref": "U1", "conn": {"VCC": "3V3"}}]}), 400, "invalid_args")
    assert "(VDD, VDDIO): name the pin" in bad["error"]["message"]


def test_conn_schema_mentions_labels():
    desc = schemas.PROJECT["parameters"]["properties"]["conn"]["description"]
    assert "label" in desc and "SDA" in desc and "null" in desc


# --------------------------------------------------------------------------------------------- ads1220 clock input

def test_ads1220_spi_clock_labels_hit_sclk(proj):
    """The ADS1220 has a serial clock input SCLK (datasheet p. 4) next to CLK, the input for an external clock source.
    SCK and SCLK reach SCLK; CLK stays the real pin of the external clock and never becomes an SPI clock label."""
    pins = _pins("ads1220")
    assert next(p for p in pins if p["name"] == "SCLK")["signal"] == "spi_sck"
    assert next(p for p in pins if p["name"] == "CLK")["signal"] != "spi_sck"
    assert modspec.resolve_pin(pins, "SCK") == {"pin": "SCLK", "via": "label", "candidates": []}
    assert modspec.resolve_pin(pins, "SCLK") == {"pin": "SCLK", "via": "name", "candidates": []}
    assert modspec.resolve_pin(pins, "CLK") == {"pin": "CLK", "via": "name", "candidates": []}
    res = _ok({"op": "add_module", "module": "ads1220", "ref": "U1", "conn": {"SCK": "GPIO12", "DIN": "GPIO11"}})
    assert _part(res)["conn"] == {"SCLK": "GPIO12", "DIN": "GPIO11"}
    assert [a["value"] for a in _aliases(res)] == ["SCK → SCLK"]  # a label, so it is named
    res = _ok({"op": "add_module", "module": "ads1220", "ref": "U2", "conn": {"SCLK": "GPIO13"}})
    assert _part(res, "U2")["conn"] == {"SCLK": "GPIO13"}
    assert _aliases(res) == []  # a real pin name needs no mapping
    res = _ok({"op": "connect", "ref": "U1", "conn": {"CLK": "GND"}})
    assert _part(res)["conn"]["CLK"] == "GND" and _part(res)["conn"]["SCLK"] == "GPIO12"
    assert _aliases(res) == []
    assert "SCLK" in modspec.pins_hint(pins) and "CLK" in modspec.pins_hint(pins)


# --------------------------------------------------------------------------------------------- assumption wording

def test_alias_text_names_the_catalog_pin_not_the_datasheet():
    """The pins of a breakout variant are header names and some notes give another datasheet name, so the text says
    ``catalog pin`` and never claims a datasheet name."""
    cat = modules.catalog()
    pins = cat.get("bme280")["pins"]
    res = modspec.resolve_pin(pins, "SDA")
    info = next(p for p in pins if p["name"] == res["pin"])
    text = modspec.alias_text("bme280", info, "SDA", res["via"])
    assert text == f"bme280: I²C data pin, catalog pin SDI ({info['note'].strip()[:120]})"
    bpins = cat.get("w5500", "breakout")["pins"]
    mapped = 0
    for label in ("SCLK", "SDI", "SDO", "VDD"):
        res = modspec.resolve_pin(bpins, label)
        if res["via"] == "label":
            mapped += 1
            info = next(p for p in bpins if p["name"] == res["pin"])
            text = modspec.alias_text("w5500", info, label, "label")
            assert f"catalog pin {info['name']}" in text and "datasheet" not in text.split(" (")[0]
    assert mapped == 4
    case = modspec.alias_text("bme280", {"name": "SDI"}, "sdi", "case")
    assert case == "bme280: the catalog spells the pin SDI"


def test_alias_assumption_says_catalog_pin(proj):
    res = _ok({"op": "add_module", "module": "ads1220", "conn": {"SCK": "GPIO12"}})
    assert [a["reason"] for a in _aliases(res)] == ["ads1220: SPI clock pin, catalog pin SCLK (serial clock input (p. 4))"]
    res = _ok({"op": "add_module", "module": "bme280", "ref": "U2", "conn": {"sdi": "GPIO8"}})
    assert [a["reason"] for a in _aliases(res)][0].startswith("bme280: the catalog spells the pin SDI")
    assert all("datasheet" not in a["reason"].split(" (")[0] for a in _aliases(res))
