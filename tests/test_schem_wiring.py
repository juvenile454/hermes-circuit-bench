"""Nets and wiring tables (no schemdraw needed)."""
import pytest

from circuit_bench.bench_core import boards, wiring
from circuit_bench.bench_core.contracts import BenchError

S3 = "esp32-s3-devkitc-1"
VALUES = {
    "led": {"r_series": "150 Ω"},
    "npn_low_side": {"r_base": "1 kΩ", "r_pulldown": "10 kΩ"},
    "button_pullup": {"r_pullup": "10 kΩ"},
    "divider": {"r1": "30 kΩ", "r2": "10 kΩ"},
}
PARAMS = {
    "led": {"led": "red", "active": "high", "net": "LED"},
    "npn_low_side": {"transistor": "2N2222A", "load": "laser module", "supply": "5V", "net": "LASER_EN"},
    "button_pullup": {"button": "push button", "net": "BUTTON"},
    "divider": {"source": "battery", "input_net": "VIN", "net": "VSENSE"},
}


def _build(block, devkit: str | None = S3, gpio: int | None = 14, **over):
    return wiring.build(block, {**PARAMS[block], **over}, wiring.Board(devkit, gpio), VALUES[block])


def test_signal_endpoint_uses_header_of():
    assert boards.header_of(S3, 14) == "J1-20"
    ep = wiring.Board(S3, 14).signal()
    assert (ep.node, ep.display, ep.source_id) == ("J1-20", "J1-20 · IO14", "devkitc1-s3-v1.1")
    assert wiring.Board(S3, 43).signal().display == "J3-2 · IO43"


def test_npn_wiring_matches_contract_example():
    res = _build("npn_low_side").as_result()
    assert res["wiring"][0] == {"from": "J1-20 · IO14", "to": "R1.1", "net": "LASER_EN"}
    assert res["parts"] == [
        {"ref": "R1", "kind": "resistor", "value": "1 kΩ"},
        {"ref": "R2", "kind": "resistor", "value": "10 kΩ"},
        {"ref": "Q1", "kind": "transistor", "value": "2N2222A"},
        {"ref": "J2", "kind": "connector", "value": "laser module"},
    ]
    nets = {n["name"]: n["nodes"] for n in res["nets"]}
    assert nets == {
        "LASER_EN": ["J1-20", "R1.1"],
        "LASER_BASE": ["R1.2", "Q1.B", "R2.1"],
        "LASER_LOW": ["Q1.C", "J2.2"],
        "5V": ["J1-21", "J2.1"],
        "GND": ["R2.2", "Q1.E", "J1-22"],
    }
    rows = {(w["from"], w["to"]) for w in res["wiring"]}
    assert ("J1-21 · 5V", "J2.1") in rows and ("Q1.E", "J1-22 · G") in rows


def test_rails_come_from_the_nearest_header_pin():
    # GPIO1 sits on J3-4: ground from J3 (J3-1), 3V3 only exists on J1 (J1-1)
    res = _build("led", gpio=1, active="low").as_result()
    shown = {w["from"] for w in res["wiring"]} | {w["to"] for w in res["wiring"]}
    assert "J1-1 · 3V3" in shown and "J3-4 · IO1" in shown
    res = _build("button_pullup", gpio=1).as_result()
    shown = {w["from"] for w in res["wiring"]} | {w["to"] for w in res["wiring"]}
    assert {"J3-4 · IO1", "J1-1 · 3V3", "J3-1 · G"} <= shown


def test_without_devkit_endpoints_keep_chip_names():
    res = _build("npn_low_side", devkit=None).as_result()
    assert res["wiring"][0]["from"] == "GPIO14"
    nodes = {n for net in res["nets"] for n in net["nodes"]}
    assert {"GPIO14", "5V", "GND"} <= nodes
    assert _build("led", devkit=None, gpio=None).as_result()["wiring"][0]["from"] == "GPIO"


@pytest.mark.parametrize("block", sorted(PARAMS))
@pytest.mark.parametrize("devkit,gpio", [(S3, 14), (S3, 1), (None, 14), (None, None), (S3, None)])
def test_every_netlist_is_consistent(block, devkit, gpio):
    nl = _build(block, devkit=devkit, gpio=gpio)
    assert wiring.check_netlist(nl) == []
    res = nl.as_result()
    assert set(res) == {"nets", "parts", "wiring"}
    assert all(set(w) == {"from", "to", "net"} for w in res["wiring"])
    assert all(set(n) == {"name", "nodes"} for n in res["nets"])
    assert len({p["ref"] for p in res["parts"]}) == len(res["parts"])


def test_led_active_low_sinks_into_the_gpio():
    nets = {n["name"]: n["nodes"] for n in _build("led", active="low").as_result()["nets"]}
    # J1-2 is the 3V3 pin closest to J1-20
    assert nets["3V3"] == ["J1-2", "D1.A"] and nets["LED_K"] == ["D1.K", "R1.2"] and nets["LED"] == ["J1-20", "R1.1"]
    nets = {n["name"]: n["nodes"] for n in _build("led").as_result()["nets"]}
    assert nets["GND"] == ["D1.K", "J1-22"]


def test_check_netlist_finds_problems():
    nl = _build("npn_low_side")
    nl.nets.append(("EXTRA", ["Q1.C", "R9.1"]))
    problems = wiring.check_netlist(nl)
    assert any("Q1.C is on nets" in p for p in problems)
    assert any("unknown part pin R9.1" in p for p in problems)
    nl = _build("led")
    nl.nets = [(n, nodes) for n, nodes in nl.nets if n != "GND"]
    assert "part pin D1.K is not connected" in wiring.check_netlist(nl)


def test_gpio_not_on_a_header_is_refused():
    with pytest.raises(BenchError) as e:
        wiring.Board(S3, 26)  # SPI flash, not broken out
    assert e.value.code == "unknown_pin"


def test_unknown_board():
    with pytest.raises(BenchError) as e:
        wiring.Board("no-such-board", 14)
    assert e.value.code == "unknown_board"


def test_connector_ref_skips_devkit_headers():
    assert wiring.connector_ref(S3) == "J2"
    assert wiring.connector_ref(None) == "J1"
