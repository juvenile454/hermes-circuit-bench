"""Block ``module``: a box from the module data (signals left, supplies
right), nets from conn / params.gpios, the required parts of ``requires[]`` as real parts in the drawing and the
wiring table, extra rails from options.rails / params.rails. Real BME280 from the catalog, a synthetic module with
six signals.

Also the shared SVG checks for the multi-GPIO blocks (``svg_ok``), used by the other test_schem_mod_* files.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

import mod_fixtures as mf
import modkit
import pytest

from circuit_bench.bench_core import schematic, sources
from circuit_bench.bench_core.contracts import MAX_RESULT_BYTES, validate_envelope

pytest.importorskip("schemdraw")

NS = "{http://www.w3.org/2000/svg}"
S3 = "esp32-s3-devkitc-1"
C3 = "esp32-c3-devkitm-1"
SVG_MAX = 24 * 1024  # the drawing itself (not sent to the model: the tool writes it to a file)
BAD_SVG = (r"<script", r"<foreignObject", r"\son[a-z]+\s*=", r"javascript:", r"<iframe", r"<image",
           r"\b(?:xlink:)?href\s*=", r"<!ENTITY", r"<style")  # sanitizeSvg in desktop-src/lib/wire.js


# --------------------------------------------------------------------------------------------- shared checks

def svg_ok(env: dict) -> ET.Element:
    """Everything the old blocks guarantee, on a multi-GPIO render: valid envelope, the model's part (no SVG)
    within MAX_RESULT_BYTES, SVG safety and paint rules, roles per element, every net drawn, every part with a
    hover target, labels inside the viewBox, no overlaps and >= 6 px from every line (also with 2 px bodies)."""
    assert env["ok"], env.get("error")
    assert validate_envelope(env) == []
    res = env["result"]
    model = {**env, "result": {k: v for k, v in res.items() if k != "svg"}}
    assert len(json.dumps(model).encode()) <= MAX_RESULT_BYTES
    svg = res["svg"]
    assert len(svg.encode()) <= SVG_MAX
    for bad in BAD_SVG:
        assert not re.search(bad, svg, re.IGNORECASE), bad
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|url\(", svg)
    root = ET.fromstring(svg)  # noqa: S314 - SVG of the code under test
    assert root.get("width") is None and root.get("preserveAspectRatio") == "xMidYMid meet"
    assert {el.tag.removeprefix(NS) for el in root.iter()} <= {"svg", "path", "circle", "rect", "text"}
    status = {c["id"]: c["status"] for c in env["checks"]}
    assert status["schematic.labels_overlap"] == status["schematic.labels_clear"] == "passed", env["checks"]
    assert status["schematic.netlist"] == "passed"
    overlaps, close = schematic.label_problems(svg)
    assert overlaps == [] and close == []
    nets = {n["name"] for n in res["nets"]}
    refs = {p["ref"] for p in res["parts"]}
    for el in root:
        kind = el.get("data-kind")
        assert kind in schematic.KINDS, el.attrib
        if kind in ("wire", "junction", "port"):
            assert el.get("data-net") in nets, el.attrib
        if kind == "body":
            assert el.get("data-ref") in refs, el.attrib
    drawn = {el.get("data-net") for el in root if el.get("data-kind") in ("wire", "port")}
    assert drawn == nets, (drawn, nets)
    hits = {r.get("data-ref") for r in root.iter(f"{NS}rect")}
    assert hits == refs
    x, y, w, h = (float(v) for v in root.get("viewBox").split())
    for _text, x0, y0, x1, y1 in schematic.text_boxes(svg):
        assert x <= x0 and x1 <= x + w and y <= y0 and y1 <= y + h, _text
    # 2 px bodies and ports (desktop stroke widths): still >= 6 px
    for text, gap in schematic.label_clearances(svg):
        assert gap - 0.25 >= schematic.MIN_CLEAR, (text, gap)
    # the wiring table: per net one row less than nodes, every part pin of the net reached once
    by_net = {n["name"]: n["nodes"] for n in res["nets"]}
    for name, nodes in by_net.items():
        got = [r for r in res["wiring"] if r["net"] == name]
        assert len(got) == len(nodes) - 1, name
        pins = {x for r in got for x in (r["from"], r["to"]) if "." in x and " " not in x}
        assert pins == {x for x in nodes if "." in x}, name
    part_pins = {x for nodes in by_net.values() for x in nodes if "." in x}
    assert len(part_pins) == sum(len(v) for v in by_net.values()) - sum(
        1 for nodes in by_net.values() for x in nodes if "." not in x)
    return root


def texts(env: dict) -> list[str]:
    return [t.text for t in ET.fromstring(env["result"]["svg"]).iter(f"{NS}text")]  # noqa: S314


def net_of(env: dict, node: str) -> str:
    return next(n["name"] for n in env["result"]["nets"] if node in n["nodes"])


def rows(env: dict) -> set[tuple[str, str, str]]:
    return {(r["from"], r["to"], r["net"]) for r in env["result"]["wiring"]}


def assumed(env: dict) -> dict[str, str]:
    return {a["key"]: a["value"] for a in env["assumptions"]}


# --------------------------------------------------------------------------------------------- BME280 (catalog)

def test_bme280_with_sda_scl_gpios_on_a_devkit():
    env = schematic.render("module", {"module": "bme280", "gpios": {"SDA": 8, "SCL": 9}}, devkit=S3)
    svg_ok(env)
    assert env["summary"] == "Module with its required parts: U1 BME280 (i2c) on IO8, IO9: 5 parts, 15 wires."
    parts = {p["ref"]: (p["kind"], p["value"]) for p in env["result"]["parts"]}
    # the required parts of requires[]: two 100 nF ceramics (value from the data), two pull-ups without a value
    assert parts == {"U1": ("ic", "BME280"), "C1": ("ceramic", "100 nF"), "C2": ("ceramic", "100 nF"),
                     "R1": ("resistor", "R"), "R2": ("resistor", "R")}
    nets = {n["name"]: set(n["nodes"]) for n in env["result"]["nets"]}
    assert nets["SDA"] == {"J1-12", "U1.SDI", "R1.1"} and nets["SCL"] == {"J1-15", "U1.SCK", "R2.1"}
    # pull-ups to VDDIO (= 3V3), decoupling of VDD and VDDIO to GND, CSB tied to VDDIO (I²C), SDO to GND (0x76)
    assert nets["3V3"] == {"J1-2", "U1.VDD", "U1.VDDIO", "U1.CSB", "R1.2", "R2.2", "C1.1", "C2.1"}
    assert nets["GND"] == {"J1-22", "U1.GND", "U1.SDO", "C1.2", "C2.2"}
    assert {("J1-12 · IO8", "U1.SDI", "SDA"), ("U1.SDI", "R1.1", "SDA"), ("J1-2 · 3V3", "R1.2", "3V3"),
            ("U1.VDD", "C1.1", "3V3"), ("J1-22 · G", "C1.2", "GND")} <= rows(env)
    a = assumed(env)
    assert a["R1"] == a["R2"] == "R" and a["U1.SDO"] == "GND" and a["U1.VDD"] == "3V3"
    reasons = {x["key"]: x["reason"] for x in env["assumptions"]}
    assert "bench_calc i2c_pullup" in reasons["R1"] and "0x76" in reasons["U1.SDO"]
    shown = texts(env)
    for label in ("U1 BME280", "R1 R", "R2 R", "C1 100 nF", "C2 100 nF", "J1-12 · IO8", "J1-15 · IO9", "SDA",
                  "SCL", "+3.3 V", "SDI", "SCK", "CSB", "SDO", "VDDIO", "VDD", "GND"):
        assert label in shown, label
    assert [s["id"] for s in env["sources"]][:2] == ["mod-env-bme280-ds", "devkitc1-s3-v1.1"]
    assert {c["id"] for c in env["checks"]} >= {"schematic.header_pin"}


def test_bme280_pins_left_signals_right_supplies():
    env = schematic.render("module", {"module": "bme280"})
    root = svg_ok(env)
    pins = {t.text: float(t.get("x")) for t in root.iter(f"{NS}text") if t.get("data-kind") == "pin"}
    left = {"SDI", "SCK", "CSB", "SDO"}
    right = {"VDDIO", "VDD", "GND"}
    assert set(pins) == left | right
    assert max(pins[p] for p in left) < min(pins[p] for p in right)
    # no GPIO given: placeholders, said so
    assert "gpio_unassigned" in {w["code"] for w in env["warnings"]}
    assert texts(env).count("GPIO") == 2 and assumed(env)["devkit"] == "none"


def test_bme280_pin_names_address_and_pullup_value():
    env = schematic.render("module", {"module": "bme280", "gpios": {"SDI": 4, "SCK": 5}, "address": "0x77",
                                      "r_pullup": "4k7"}, devkit=C3)
    svg_ok(env)
    assert net_of(env, "U1.SDO") == "3V3"  # SDO to VDDIO selects 0x77
    parts = {p["ref"]: p["value"] for p in env["result"]["parts"]}
    assert parts["R1"] == parts["R2"] == "4.7 kΩ"
    assert "R1 4.7 kΩ" in texts(env) and "J1-" in " ".join(texts(env))


def test_single_gpio_goes_to_the_first_signal_pin():
    env = schematic.render("module", {"module": "bme280"}, gpio=8, devkit=S3)
    svg_ok(env)
    assert net_of(env, "U1.SDI") == net_of(env, "J1-12")


@pytest.mark.parametrize("params,kw,needle", [
    ({"module": "bme280", "gpios": {"VDD": 4}}, {}, "supply pin"),
    ({"module": "bme280", "gpios": {"MISO": 4}}, {}, "no pin or signal"),
    ({"module": "bme280", "gpios": {"SDA": 4, "SCL": 4}}, {}, "different nets"),
    ({"module": "bme280", "gpios": {"SDA": 99}}, {}, "out of range"),
    ({"module": "bme280", "gpios": [8, 9]}, {}, "object"),
    ({"module": "bme280", "gpios": {"SDA": 8}}, {"gpio": 4}, "not in params.gpios"),
    ({"module": "no_such_module"}, {}, "no_such_module"),
    ({"module": "bme280", "variant": "nope"}, {}, "variant"),
    ({"module": "bme280", "rails": {"VMOT": 230}}, {}, "low voltage"),
    ({"module": "bme280", "rails": {"5V": 4.8}}, {}, "fixed"),
    ({"module": "bme280", "colour": "red"}, {}, "unknown parameter"),
    ({"module": "bme 280"}, {}, "id such as"),
    ({"module": "bme280", "part": "U1"}, {}, "needs a project"),
])
def test_bad_module_input_gives_an_error_envelope(params, kw, needle):
    env = schematic.render("module", params, **kw)
    assert env["ok"] is False and validate_envelope(env) == []
    text = env["error"]["message"] + " " + (env["error"].get("hint") or "")
    assert needle in text, env["error"]


def test_unknown_gpio_on_the_devkit_is_unknown_pin():
    env = schematic.render("module", {"module": "bme280", "gpios": {"SDA": 26, "SCL": 9}}, devkit=S3)
    assert env["error"]["code"] == "unknown_pin"


# --------------------------------------------------------------------------------------------- synthetic, 6 signals

SIX = {
    "id": "tst_six", "title": "TST6 six-signal driver", "category": "actuator.motor", "manufacturer": "Test",
    "kind": "module", "source_ids": ["tst-sensor-ds"],
    "supplies": {"VCC": {"min": mf.F(2.7), "max": mf.F(5.5)}, "VM": {"min": mf.F(6.0), "max": mf.F(24.0)}},
    "pins": [{"name": "SCK", "signal": "spi_sck"}, {"name": "SDI", "signal": "spi_sdi"},
             {"name": "SDO", "signal": "spi_sdo"}, {"name": "CS", "signal": "spi_cs"},
             {"name": "FAULT", "signal": "open_drain_out"}, {"name": "EN", "signal": "enable_in"},
             {"name": "VCC", "signal": "supply"}, {"name": "VM", "signal": "supply"},
             {"name": "OUT1", "signal": "power_out"}, {"name": "NC1", "signal": "nc"}, mf.GND],
    "interfaces": [{"type": "spi"}],
    "requires": [
        {"code": "pullup", "kind": "resistor", "value": "10k", "pins": ["FAULT"], "to": "VCC", "page": 1,
         "evidence": "synthetic"},
        {"code": "pulldown", "kind": "resistor", "pins": ["EN"], "page": 1, "evidence": "synthetic"},
        {"code": "decoupling", "kind": "ceramic", "value": "100nF", "pins": ["VCC"], "to": "GND", "page": 1,
         "evidence": "synthetic"},
        {"code": "bulk_cap", "kind": "electrolytic", "value": "47uF", "pins": ["VM"], "to": "GND", "page": 1,
         "evidence": "synthetic"},
        {"code": "flyback", "pins": ["OUT1"], "note": "external diodes", "page": 1, "evidence": "synthetic"},
    ],
    "hazards": [],
}


@pytest.fixture
def six(monkeypatch):
    modkit.patch_runtime(monkeypatch, catalog=mf.catalog(SIX), sources=mf.SOURCES)
    return SIX


def test_six_signal_module_with_rails_and_required_parts(six):
    gpios = {"SCK": 12, "MOSI": 11, "MISO": 13, "CS": 10, "FAULT": 4, "EN": 5}
    env = schematic.render("module", {"module": "tst_six", "gpios": gpios, "conn": {"VM": "VMOT"},
                                      "rails": {"VMOT": 12}}, devkit=S3)
    root = svg_ok(env)
    nets = {n["name"]: set(n["nodes"]) for n in env["result"]["nets"]}
    from circuit_bench.bench_core import boards
    for pin, num in (("SCK", 12), ("SDI", 11), ("SDO", 13), ("CS", 10), ("FAULT", 4), ("EN", 5)):
        assert boards.header_of(S3, num) in nets[net_of(env, f"U1.{pin}")], pin
    assert net_of(env, "U1.SDI") == "MOSI" and net_of(env, "U1.SDO") == "MISO"
    parts = {p["ref"]: (p["kind"], p["value"]) for p in env["result"]["parts"]}
    assert parts == {"U1": ("module", "TST6"), "R1": ("resistor", "10 kΩ"), "R2": ("resistor", "R"),
                     "C1": ("ceramic", "100 nF"), "C2": ("electrolytic", "47 µF")}
    assert nets["VMOT"] == {"VMOT", "U1.VM", "C2.1"}  # off-board rail: its own endpoint
    assert {"R1.2", "U1.VCC"} <= nets["3V3"] and {"R2.2", "C1.2", "C2.2"} <= nets["GND"]
    assert "VMOT +12 V" in texts(env) and "NC1" not in texts(env)
    assert net_of(env, "U1.OUT1") == "U1_OUT1"
    codes = {w["code"]: w for w in env["warnings"]}
    assert "flyback" in codes["module_requires"]["message"] and "external diodes" in codes["module_requires"]["message"]
    assert assumed(env)["nc_pins"] == "NC1"
    pins = {t.text: float(t.get("x")) for t in root.iter(f"{NS}text") if t.get("data-kind") == "pin"}
    plus = [t.get("data-pin") for t in root.iter(f"{NS}text") if t.text == "+"]
    assert plus == ["C2.1"]  # the electrolytic's + on the VMOT side
    left = ("SCK", "SDI", "SDO", "CS", "FAULT", "EN")
    assert max(pins[p] for p in left) < min(pins[p] for p in ("VCC", "VM", "OUT1", "GND"))


def test_six_signal_module_unassigned_and_long_rail(six):
    env = schematic.render("module", {"module": "tst_six", "rails": {"V" * 24: 24}, "conn": {"VM": "V" * 24}})
    svg_ok(env)
    # the unconnected output FAULT is NC, not a GPIO placeholder; the five inputs/bus pins keep theirs
    assert texts(env).count("GPIO") == 5 and texts(env).count("NC") == 1
    assert next(a for a in env["assumptions"] if a["key"] == "nc_outputs")["value"] == "FAULT"


def test_supply_out_of_both_board_rails_is_said(six, monkeypatch):
    env = schematic.render("module", {"module": "tst_six"})
    svg_ok(env)
    codes = {w["code"]: w for w in env["warnings"]}
    assert "U1.VM" in codes["module_supply_open"]["message"] and net_of(env, "U1.VM") == "U1_VM"


def test_pullups_on_the_board_per_facts_are_not_drawn(six):
    proj = {"id": "bench-m", "board": {"chip": "esp32s3", "devkit": S3}, "assignments": [], "options": {},
            "parts": [{"ref": "U3", "kind": "module", "value": "TST6", "module": "tst_six",
                       "facts": {"pullups": "4.7k"}}]}
    env = schematic.render("module", {"part": "U3"}, project=proj)
    svg_ok(env)
    resistors = {p["ref"]: p["value"] for p in env["result"]["parts"] if p["kind"] == "resistor"}
    assert resistors == {"R1": "R"}  # only the EN pull-down; the FAULT pull-up sits on the board
    assert assumed(env)["pullups"] == "4.7k"
    assert env["summary"].startswith("Module with its required parts: U3 TST6 (spi)")


def test_termination_between_two_pins_joins_the_other_net(monkeypatch):
    mod = {**SIX, "id": "tst_term", "requires": [
        {"code": "termination", "kind": "resistor", "value": "120", "pins": ["SDI", "SDO"], "page": 1,
         "evidence": "synthetic"}]}
    modkit.patch_runtime(monkeypatch, catalog=mf.catalog(mod), sources=mf.SOURCES)
    env = schematic.render("module", {"module": "tst_term", "gpios": {"SDI": 11, "SDO": 13}}, devkit=S3)
    svg_ok(env)
    assert {"R1.1"} <= set(next(n["nodes"] for n in env["result"]["nets"] if n["name"] == "MOSI"))
    assert {"R1.2"} <= set(next(n["nodes"] for n in env["result"]["nets"] if n["name"] == "MISO"))
    assert ("U1.SDO", "R1.2", "MISO") in rows(env)


def test_project_rails_and_assignment_nets(six):
    proj = {"id": "bench-m", "board": {"chip": "esp32s3", "devkit": S3}, "options": {"rails": {"VMOT": 12}},
            "assignments": [{"role": "MOT_FAULT", "mode": "in", "pin": 4, "net": "MOT_FAULT"}],
            "parts": [{"ref": "U2", "kind": "module", "value": "TST6", "module": "tst_six",
                       "conn": {"VM": "VMOT", "FAULT": "GPIO4", "EN": "GPIO5"}}]}
    env = schematic.render("module", {"part": "U2"}, project=proj)
    svg_ok(env)
    assert net_of(env, "U2.FAULT") == "MOT_FAULT" and net_of(env, "U2.EN") == "GPIO5"
    assert "VMOT +12 V" in texts(env)
    from circuit_bench.bench_core import boards
    assert boards.header_of(S3, 4) in next(n["nodes"] for n in env["result"]["nets"] if n["name"] == "MOT_FAULT")


def test_source_ids_are_cited(six):
    env = schematic.render("module", {"module": "tst_six"})
    assert env["sources"][0]["id"] == "tst-sensor-ds"
    assert set(sources.all_sources()) >= {s["id"] for s in env["sources"]}


@pytest.mark.parametrize("src,severity", [("tst-sensor-ds", "danger"), ("tst-bsensor-shop", "info")])
def test_hazards_of_the_module_data_are_warnings_capped_by_source_class(monkeypatch, src, severity):
    mod = {**SIX, "id": "tst_haz", "source_ids": [src], "requires": [],
           "hazards": [{"code": "li_ion", "text": "Li-ion cell: never short, charge with a protected charger.",
                        "page": 1, "evidence": "synthetic"}]}
    modkit.patch_runtime(monkeypatch, catalog=mf.catalog(mod), sources=mf.SOURCES)
    env = schematic.render("module", {"module": "tst_haz"})
    svg_ok(env)
    hazard = next(w for w in env["warnings"] if w["code"] == "module_hazard")
    assert hazard["severity"] == severity and "li_ion" in hazard["message"] and hazard["source_ids"] == [src]
