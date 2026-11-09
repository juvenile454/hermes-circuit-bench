"""Module family wired: catalog entries MAX485, MAX3485, SN65HVD230, TJA1050, MCP2515, CP2102N,
CH340C (data/modules/wired.json) and the family rules in bench_core/modrules/wired.py.

Synthetic projects on the real catalog and the real ESP32-S3 values (electrical.get). Expectations cover
mod.supply_range, the wired rules and the generic level rules (mod.level_out / mod.level_in), which report the 5 V
receiver outputs as danger.
"""
from __future__ import annotations

import json
from pathlib import Path

import modkit as k
import pytest

from circuit_bench.bench_core import modcheck, modules, pins
from circuit_bench.bench_core.modrules import wired

DATA = Path(__file__).resolve().parent.parent / "circuit_bench" / "data" / "modules" / "wired.json"
IDS = ("max485", "max3485", "sn65hvd230", "tja1050", "mcp2515", "cp2102n", "ch340c")

UART = [k.assign("uart_tx", 17, "TX1"), k.assign("uart_rx", 18, "RX1"), k.assign("out", 16, "DIR")]
TWAI = [k.assign("out", 4, "CTX"), k.assign("in", 5, "CRX")]
SPI = [k.assign("spi_sck", 12, "SCK"), k.assign("spi_mosi", 11, "MOSI"), k.assign("spi_miso", 13, "MISO"),
       k.assign("spi_cs", 10, "CS0"), k.assign("in", 14, "CANINT")]


def rs485(ref="U1", module="max485", vcc="5V", **extra):
    return k.mod(ref, module, {"RO": "RX1", "DI": "TX1", "DE": "DIR", "RE": "DIR", "VCC": vcc, "GND": "GND",
                               "A": "BUS_A", "B": "BUS_B", **extra})


def can(ref="U2", module="sn65hvd230", vcc="3V3", **extra):
    rx, tx = ("R", "D") if module == "sn65hvd230" else ("RXD", "TXD")
    conn = {tx: "CTX", rx: "CRX", "VCC": vcc, "GND": "GND", "CANH": "CAN_H", "CANL": "CAN_L"}
    if module == "sn65hvd230":
        conn["Rs"] = "GND"
    return k.mod(ref, module, {**conn, **extra})


def res(ref, a, b, value="120"):
    return {"ref": ref, "kind": "resistor", "value": value, "conn": {"1": a, "2": b}}


def cap(ref, a, b="GND", value="100nF"):
    return {"ref": ref, "kind": "capacitor", "value": value, "conn": {"1": a, "2": b}}


def run(parts, assignments=UART, options=None, only=None):
    return k.run(assignments=assignments, parts=parts, options=options, only=only)


def fs(report, rule_id, status=None):
    return k.findings(report, rule_id, status)


def sev(report, rule_id):
    return sorted({f.severity for f in fs(report, rule_id, "failed")})


# --- catalog ------------------------------------------------------------------------------------------------------
def test_catalog_loads_every_wired_part_without_problems():
    cat = modules.Catalog.from_dir()
    assert [p for p in cat.problems if "wired" in p] == []
    for mid in IDS:
        entry = cat.get(mid)
        assert entry["_wp"] == "wired" and entry["_class"] in ("A", "A1")
    data = json.loads(DATA.read_text())
    assert data["wp"] == "wired" and sorted(m["id"] for m in data["modules"]) == sorted(IDS)
    cats = {m["id"]: m["category"] for m in data["modules"]}
    assert cats["max485"] == cats["max3485"] == "comm.rs485"
    assert cats["sn65hvd230"] == cats["tja1050"] == cats["mcp2515"] == "comm.can"
    assert cats["cp2102n"] == cats["ch340c"] == "comm.usb_uart"


def test_uart_pins_are_module_view():
    cat = modules.Catalog.from_dir()
    sig = {mid: {p["name"]: p["signal"] for p in cat.get(mid)["pins"]} for mid in IDS}
    assert sig["max485"]["DI"] == sig["max3485"]["DI"] == "uart_rx"  # the module receives from the ESP's TX
    assert sig["max485"]["RO"] == sig["max3485"]["RO"] == "uart_tx"
    assert sig["cp2102n"]["RXD"] == sig["ch340c"]["RXD"] == "uart_rx"
    assert sig["cp2102n"]["TXD"] == sig["ch340c"]["TXD"] == "uart_tx"


def test_key_values_match_the_data_sheets():
    cat = modules.Catalog.from_dir()
    v = modules.value
    m = cat.get("max485")["supplies"]["VCC"]
    assert (v(m["min"], {}), v(m["max"], {}), v(m["abs_max"], {})) == (4.75, 5.25, 12.0)
    m = cat.get("max3485")["supplies"]["VCC"]
    assert (v(m["min"], {}), v(m["max"], {}), v(m["abs_max"], {})) == (3.0, 3.6, 7.0)
    m = cat.get("sn65hvd230")["supplies"]["VCC"]
    assert (v(m["min"], {}), v(m["max"], {}), v(m["abs_max"], {})) == (3.0, 3.6, 6.0)
    m = cat.get("tja1050")["supplies"]["VCC"]
    assert (v(m["min"], {}), v(m["max"], {}), v(m["abs_max"], {})) == (4.75, 5.25, 6.0)
    m = cat.get("mcp2515")
    assert v(m["supplies"]["VDD"]["min"], {}) == 2.7 and v(m["supplies"]["VDD"]["max"], {}) == 5.5
    assert v(m["io"]["vih"], {"VDD": 5.0}) == pytest.approx(3.5)
    assert v(m["interfaces"][0]["f_max_hz"], {}) == 10e6
    m = cat.get("cp2102n")["supplies"]
    assert v(m["VREGIN"]["max"], {}) == 5.25 and v(m["VDD"]["abs_max"], {}) == 4.2
    base, low = cat.get("ch340c"), cat.get("ch340c", "3v3")
    assert v(base["io"]["vih"], {}) == 2.3 and v(low["io"]["vih"], {}) == 1.9
    assert v(low["supplies"]["VCC"]["max"], {}) == 3.6 and v(base["supplies"]["VCC"]["max"], {}) == 5.3


# --- supply range (hard) ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("module,rail,bad", [
    ("max485", "5V", False), ("max485", "3V3", True),  # MAX485 below 4.75 V
    ("max3485", "3V3", False), ("max3485", "5V", True),  # MAX3485 above 3.6 V (abs max 7 V: caution)
])
def test_rs485_supply_range(module, rail, bad):
    r = run([rs485(module=module, vcc=rail)], only=("mod.supply_range",))
    failed = fs(r, "mod.supply_range", "failed")
    assert bool(failed) is bad
    if bad:
        assert {f.severity for f in failed} == {"caution"}


@pytest.mark.parametrize("module,rail,bad", [
    ("sn65hvd230", "3V3", False), ("sn65hvd230", "5V", True), ("tja1050", "5V", False), ("tja1050", "3V3", True),
])
def test_can_transceiver_supply_range(module, rail, bad):
    r = run([can(module=module, vcc=rail)], assignments=TWAI, only=("mod.supply_range",))
    assert bool(fs(r, "mod.supply_range", "failed")) is bad


def test_cp2102n_vdd_above_abs_max_is_danger():
    p = k.mod("U3", "cp2102n", {"VDD": "5V", "VREGIN": "5V", "GND": "GND", "RXD": "TX1", "TXD": "RX1"})
    r = run([p], only=("mod.supply_range",))
    assert "danger" in sev(r, "mod.supply_range")  # VDD 5 V > 4.2 V absolute maximum


def test_mcp2515_supply_range():
    ok = k.mod("U4", "mcp2515", {"VDD": "3V3", "VSS": "GND", "SCK": "SCK", "SI": "MOSI", "SO": "MISO", "CS": "CS0"})
    r = run([ok], assignments=SPI, only=("mod.supply_range",))
    assert fs(r, "mod.supply_range", "failed") == []
    hi = k.mod("U4", "mcp2515", {"VDD": "VBAT", "VSS": "GND"})
    r = run([hi], assignments=SPI, options={"rails": {"VBAT": 7.4}}, only=("mod.supply_range",))
    assert "danger" in sev(r, "mod.supply_range")  # 7.4 V > 7.0 V absolute maximum


# --- generic levels: expected, not enforced here ------------------------------------------------------------------
@pytest.mark.parametrize("part,assignments", [
    (rs485(), UART), (can(module="tja1050", vcc="5V"), TWAI),
    (k.mod("U5", "ch340c", {"VCC": "5V", "GND": "GND", "TXD": "RX1", "RXD": "TX1"}), UART),
])
def test_level_out_reports_5v_outputs_as_danger(part, assignments):
    assert "danger" in sev(run([part], assignments=assignments), "mod.level_out")


def test_level_in_mcp2515_at_5v_needs_3v5():
    p = k.mod("U4", "mcp2515", {"VDD": "5V", "VSS": "GND", "SCK": "SCK", "SI": "MOSI", "SO": "MISO", "CS": "CS0"})
    assert "caution" in sev(run([p], assignments=SPI), "mod.level_in")


def test_level_out_passes_3v3_parts():
    r = run([rs485(module="max3485", vcc="3V3")])
    assert fs(r, "mod.level_out", "failed") == [] and fs(r, "mod.level_out", "passed")


# --- mod.wired.rs485_termination / can_termination ---------------------------------------------------------------
RT = ("mod.wired.rs485_termination",)


def test_rs485_two_terminators_pass():
    parts = [rs485("U1"), rs485("U2", module="max3485", vcc="3V3"), res("R1", "BUS_A", "BUS_B"),
             res("R2", "BUS_B", "BUS_A", "120Ω")]
    r = run(parts, only=RT)
    assert fs(r, RT[0], "failed") == [] and len(fs(r, RT[0], "passed")) == 1
    assert "mod_wired_rs485_termination" not in k.codes(r)


def test_rs485_without_terminator_is_an_info_hint():
    r = run([rs485()], only=RT)
    (f,) = fs(r, RT[0], "failed")
    assert f.severity == "info" and "120 Ω" in f.message and f.source_ids == ["mod-wired-max485-ds"]
    assert "mod_wired_rs485_termination" in k.codes(r)


def test_rs485_one_terminator_asks_for_the_other_end():
    (f,) = fs(run([rs485(), res("R1", "BUS_A", "BUS_B")], only=RT), RT[0], "failed")
    assert f.severity == "info" and "other bus end" in f.message


def test_rs485_three_terminators_caution():
    parts = [rs485("U1"), rs485("U2"), rs485("U3"), res("R1", "BUS_A", "BUS_B"), res("R2", "BUS_A", "BUS_B"),
             res("R3", "BUS_A", "BUS_B")]
    (f,) = fs(run(parts, only=RT), RT[0], "failed")
    assert f.severity == "caution" and "only the two bus ends" in f.message
    assert {"U1", "U2", "U3", "R1", "R2", "R3"} <= set(f.refs)


def test_rs485_odd_terminator_value():
    parts = [rs485(), res("R1", "BUS_A", "BUS_B", "1k"), res("R2", "BUS_A", "BUS_B")]
    (f,) = fs(run(parts, only=RT), RT[0], "failed")
    assert f.severity == "info" and "R1" in f.message and "1.00 kΩ" in f.message


def test_rs485_separate_buses_are_counted_separately():
    parts = [rs485("U1"), rs485("U2", A="BUS2_A", B="BUS2_B"), res("R1", "BUS_A", "BUS_B"),
             res("R2", "BUS_A", "BUS_B")]
    r = run(parts, only=RT)
    assert len(fs(r, RT[0], "passed")) == 1
    (f,) = fs(r, RT[0], "failed")
    assert "BUS2_A" in f.message and f.refs == ["U2"]


def test_rs485_unconnected_bus_pins_not_checked():
    p = k.mod("U1", "max485", {"VCC": "5V", "GND": "GND", "RO": "RX1", "DI": "TX1"})
    (f,) = fs(run([p], only=RT), RT[0], "not_checked")
    assert f.severity == "info"


def test_can_termination_counts_resistors_across_canh_canl():
    ct = ("mod.wired.can_termination",)
    r = run([can("U1"), can("U2", module="tja1050", vcc="5V"), res("R1", "CAN_H", "CAN_L")], assignments=TWAI,
            only=ct)
    (f,) = fs(r, ct[0], "failed")
    assert f.severity == "info" and "CAN bus" in f.message
    r = run([can("U1"), can("U2"), res("R1", "CAN_H", "CAN_L"), res("R2", "CAN_H", "CAN_L")], assignments=TWAI,
            only=ct)
    assert fs(r, ct[0], "failed") == [] and fs(r, ct[0], "passed")


# --- mod.wired.max485_ro_5v / tja1050_rxd_5v (hints next to mod.level_out) ---------------------------------------
def test_max485_ro_5v_hint_names_the_max3485():
    rid = "mod.wired.max485_ro_5v"
    (f,) = fs(run([rs485()], only=(rid,)), rid, "failed")
    assert f.severity == "info" and "MAX3485" in f.message and "GPIO18" in f.message


def test_max485_ro_hint_silent_on_3v3_divider_and_shifter():
    rid = "mod.wired.max485_ro_5v"
    assert fs(run([rs485(vcc="3V3")], only=(rid,)), rid, "failed") == []  # supply_range reports 3.3 V
    assert fs(run([rs485(RO="RO_5V")], only=(rid,)), rid) == []  # RO not on a GPIO net (divider)
    p = rs485()
    p["facts"] = {"level_shifter": True}
    r = run([p], only=(rid,))
    assert fs(r, rid, "failed") == [] and fs(r, rid, "passed")
    assert fs(run([rs485(module="max3485", vcc="3V3")], only=(rid,)), rid) == []  # only the MAX485


def test_max485_ro_hint_not_checked_without_vcc():
    rid = "mod.wired.max485_ro_5v"
    p = k.mod("U1", "max485", {"RO": "RX1", "DI": "TX1", "GND": "GND"})
    assert [f.status for f in fs(run([p], only=(rid,)), rid)] == ["not_checked"]


def test_tja1050_rxd_5v_hint_names_the_sn65hvd230():
    rid = "mod.wired.tja1050_rxd_5v"
    (f,) = fs(run([can(module="tja1050", vcc="5V")], assignments=TWAI, only=(rid,)), rid, "failed")
    assert f.severity == "info" and "SN65HVD230" in f.message and "GPIO5" in f.message
    assert fs(run([can(module="tja1050", vcc="3V3")], assignments=TWAI, only=(rid,)), rid, "failed") == []


# --- mod.wired.hvd230_rs_standby ----------------------------------------------------------------------------------
RS = ("mod.wired.hvd230_rs_standby",)


@pytest.mark.parametrize("rs,status,severity", [
    ("GND", "passed", None),
    ("3V3", "failed", "info"),  # 3.3 V ≥ 0.75 · 3.3 V: standby
    ("5V", "failed", "caution"),  # above VCC
    ("V1V2", "failed", "caution"),  # neither low nor standby
    ("CTRL", "passed", None),  # GPIO net
])
def test_hvd230_rs_levels(rs, status, severity):
    assignments = [*TWAI, k.assign("out", 6, "CTRL")]
    r = run([can(Rs=rs)], assignments=assignments, options={"rails": {"V1V2": 1.2}}, only=RS)
    (f,) = fs(r, RS[0])
    assert (f.status, f.severity) == (status, severity)
    if severity == "info":
        assert "standby" in f.message and f.source_ids == ["mod-wired-sn65hvd230-ds"]


def test_hvd230_rs_resistors():
    slope = run([can(Rs="RS_NET"), res("R5", "RS_NET", "GND", "47k")], assignments=TWAI, only=RS)
    assert [f.status for f in fs(slope, RS[0])] == ["passed"] and "slope control" in fs(slope, RS[0])[0].message
    low = run([can(Rs="RS_NET"), res("R5", "RS_NET", "GND", "1k")], assignments=TWAI, only=RS)
    assert [f.severity for f in fs(low, RS[0], "failed")] == ["info"]
    up = run([can(Rs="RS_NET"), res("R5", "RS_NET", "3V3", "10k")], assignments=TWAI, only=RS)
    (f,) = fs(up, RS[0], "failed")
    assert f.severity == "info" and "standby" in f.message and "R5" in f.refs


def test_hvd230_rs_open_not_checked():
    p = k.mod("U2", "sn65hvd230", {"D": "CTX", "R": "CRX", "VCC": "3V3", "GND": "GND"})
    (f,) = fs(run([p], assignments=TWAI, only=RS), RS[0])
    assert (f.status, f.severity) == ("not_checked", "info")


# --- mod.wired.ch340_vcc ------------------------------------------------------------------------------------------
CH = ("mod.wired.ch340_vcc",)


def ch340(vcc="5V", v3=None, variant=None):
    conn = {"VCC": vcc, "GND": "GND", "TXD": "RX1", "RXD": "TX1"}
    if v3 is not None:
        conn["V3"] = v3
    return k.mod("U5", "ch340c", conn, variant=variant)


@pytest.mark.parametrize("part,extra,status,severity", [
    (ch340("3V3", "3V3", "3v3"), [], "passed", None),
    (ch340("3V3", "VCC", "3v3"), [], "passed", None),  # tie by pin name: V3 on the net of VCC
    (ch340("3V3", "3V3"), [], "failed", "info"),  # base entry: choose variant 3v3
    (ch340("3V3", None, "3v3"), [], "failed", "caution"),  # V3 open at 3.3 V
    (ch340("5V", "V3NET"), [cap("C1", "V3NET")], "passed", None),
    (ch340("5V", "V3NET"), [], "failed", "info"),  # no capacitor
    (ch340("5V"), [], "failed", "info"),  # V3 open
    (ch340("5V", "5V"), [], "failed", "caution"),  # V3 on VCC at 5 V
    (ch340("5V", "3V3"), [], "failed", "caution"),  # V3 on another rail
    (ch340("V3V8", "V3V8"), [], "failed", "caution"),  # between the modes
])
def test_ch340_vcc(part, extra, status, severity):
    r = run([part, *extra], options={"rails": {"V3V8": 3.8}}, only=CH)
    (f,) = fs(r, CH[0])
    assert (f.status, f.severity) == (status, severity), f.message
    if status == "failed":
        assert f.source_ids == ["mod-wired-ch340c-ds"]


def test_ch340_vcc_unknown_not_checked():
    p = k.mod("U5", "ch340c", {"GND": "GND", "TXD": "RX1", "RXD": "TX1"})
    assert [(f.status, f.severity) for f in fs(run([p], only=CH), CH[0])] == [("not_checked", "info")]


def test_ch340_3v3_variant_at_5v_is_a_supply_range_finding():
    r = run([ch340("5V", "5V", "3v3")], only=("mod.supply_range",))
    assert fs(r, "mod.supply_range", "failed")


# --- helpers and integration --------------------------------------------------------------------------------------
@pytest.mark.parametrize("value,ohm", [(120, 120.0), ("120", 120.0), ("120R", 120.0), ("120 \u2126", 120.0),
                                       ("120\u03a9", 120.0), ("4k7", 4700.0), ("10k", 10e3), ("1M", 1e6),
                                       ("x", None), (None, None), ("0", None), (True, None)])
def test_ohms(value, ohm):
    assert wired.ohms(value) == ohm


def test_rules_are_registered_and_produce_checks():
    ids = {"mod.wired.rs485_termination", "mod.wired.can_termination", "mod.wired.max485_ro_5v",
           "mod.wired.tja1050_rxd_5v", "mod.wired.hvd230_rs_standby", "mod.wired.ch340_vcc"}
    assert ids <= set(modcheck.RULES)
    r = run([rs485(), can(module="tja1050", vcc="5V"), ch340("3V3", "3V3", "3v3")], assignments=[*UART, *TWAI])
    have = {c["id"] for c in r.checks}
    assert {modcheck.check_id(i) for i in ids - {"mod.wired.hvd230_rs_standby"}} <= have


def test_pins_check_end_to_end():
    parts = [{"ref": "U1", "kind": "ic", "value": "MAX485", "module": "max485",
              "conn": {"RO": "RX1", "DI": "TX1", "DE": "DIR", "RE": "DIR", "VCC": "5V", "GND": "GND",
                       "A": "BUS_A", "B": "BUS_B"}}]
    env = pins.check("esp32s3", UART, parts=parts, options={})
    assert env["ok"] is True
    codes = {w["code"] for w in env.get("warnings") or []}
    assert "mod_wired_rs485_termination" in codes and "mod_wired_max485_ro_5v" in codes


# --- data corrections ------------------------------------------------------------------------------------------------
def test_mcp2515_output_levels_hold_for_vdd_4v5_only_and_cp2102n_cap():
    m = modules.catalog().get("mcp2515")["io"]
    assert "VDD = 4.5 V" in m["voh"]["conditions"] and "VDD = 4.5 V" in m["vol"]["conditions"]
    c = modules.catalog().get("cp2102n")["io"]["v_in_max"]
    assert "min(VIO + 2.5 V, 5.8 V)" in c["conditions"]
