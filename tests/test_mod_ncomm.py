"""Module family ncomm: catalog entries SP3485, THVD1450, TJA1051T/3, MCP2562, SX1262, CC1101,
RFM69HCW (data/modules/ncomm.json) and the family rules in bench_core/modrules/ncomm.py.

Synthetic projects on the real catalog and the real ESP32-S3 values; supply, levels and SPI with the real generic
rules (mod.supply_range, mod.level_out, mod.level_in), the family rules positive, negative and without data.
"""
from __future__ import annotations

import json
from pathlib import Path

import modkit as k
import pytest

from circuit_bench.bench_core import modules, pins
from circuit_bench.bench_core.modrules import ncomm, wired

DATA = Path(__file__).resolve().parent.parent / "circuit_bench" / "data" / "modules" / "ncomm.json"
IDS = ("sp3485", "thvd1450", "tja1051", "mcp2562", "sx1262", "cc1101", "rfm69hcw")

UART = [k.assign("uart_tx", 17, "TX1"), k.assign("uart_rx", 18, "RX1"), k.assign("out", 16, "DIR")]
TWAI = [k.assign("out", 4, "CTX"), k.assign("in", 5, "CRX")]
SPI = [k.assign("spi_sck", 12, "SCK"), k.assign("spi_mosi", 11, "MOSI"), k.assign("spi_miso", 13, "MISO"),
       k.assign("spi_cs", 10, "CS0"), k.assign("in", 14, "IRQ"), k.assign("in", 15, "BUSY")]


def rs485(ref="U1", module="sp3485", vcc="3V3", **extra):
    ro, di = ("RO", "DI") if module in ("sp3485", "max3485", "max485") else ("R", "D")
    return k.mod(ref, module, {ro: "RX1", di: "TX1", "DE": "DIR", "RE": "DIR", "VCC": vcc, "GND": "GND",
                               "A": "BUS_A", "B": "BUS_B", **extra})


def can(ref="U2", module="tja1051", vio="3V3", variant=None, **extra):
    if module == "tja1051":
        conn = {"TXD": "CTX", "RXD": "CRX", "VCC": "5V", "VIO": vio, "GND": "GND", "CANH": "CAN_H", "CANL": "CAN_L"}
        if variant == "t":
            conn.pop("VIO")
    elif module == "mcp2562":
        conn = {"TXD": "CTX", "RXD": "CRX", "VDD": "5V", "VIO": vio, "VSS": "GND", "CANH": "CAN_H", "CANL": "CAN_L",
                "STBY": "GND"}
    else:  # wired.json parts
        rx, tx = ("R", "D") if module == "sn65hvd230" else ("RXD", "TXD")
        conn = {tx: "CTX", rx: "CRX", "VCC": "3V3" if module == "sn65hvd230" else "5V", "GND": "GND",
                "CANH": "CAN_H", "CANL": "CAN_L"}
        if module == "sn65hvd230":
            conn["Rs"] = "GND"
    conn.update(extra)
    return k.mod(ref, module, {c: n for c, n in conn.items() if n is not None}, variant=variant)


def sx1262(ref="U3", vbat="3V3", **extra):
    conn = {"VBAT": vbat, "VBAT_IO": vbat, "GND": "GND", "NSS": "CS0", "SCK": "SCK", "MOSI": "MOSI", "MISO": "MISO",
            "DIO1": "IRQ", "BUSY": "BUSY", **extra}
    return k.mod(ref, "sx1262", {c: n for c, n in conn.items() if n is not None})


def cc1101(ref="U4", dvdd="3V3", avdd="3V3", **extra):
    conn = {"DVDD": dvdd, "AVDD": avdd, "GND": "GND", "CSn": "CS0", "SCLK": "SCK", "SI": "MOSI", "SO": "MISO",
            "GDO0": "IRQ", **extra}
    return k.mod(ref, "cc1101", {c: n for c, n in conn.items() if n is not None})


def rfm69(ref="U5", vdd="3V3", **extra):
    conn = {"3.3V": vdd, "GND": "GND", "NSS": "CS0", "SCK": "SCK", "MOSI": "MOSI", "MISO": "MISO", "DIO0": "IRQ",
            **extra}
    return k.mod(ref, "rfm69hcw", {c: n for c, n in conn.items() if n is not None})


def res(ref, a, b, value="120"):
    return {"ref": ref, "kind": "resistor", "value": value, "conn": {"1": a, "2": b}}


def run(parts, assignments=UART, options=None, only=None):
    return k.run(assignments=assignments, parts=parts, options=options, only=only)


def fs(report, rule_id, status=None):
    return k.findings(report, rule_id, status)


def sev(report, rule_id):
    return sorted({f.severity for f in fs(report, rule_id, "failed")})


# --- data -----------------------------------------------------------------------------------------------------------
def test_catalog_has_all_ncomm_parts():
    cat = modules.catalog()
    for mid in IDS:
        e = cat.get(mid)
        assert e is not None and e["_wp"] == "ncomm", mid
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    assert raw["wp"] == "ncomm" and [m["id"] for m in raw["modules"]] == list(IDS)


def test_aliases_resolve():
    cat = modules.catalog()
    assert cat.get("tja1051t-3")["id"] == "tja1051"
    assert cat.get("SX126x")["id"] == "sx1262"
    assert cat.get("rfm69hw")["id"] == "rfm69hcw"
    assert cat.get("thvd1450dgk")["id"] == "thvd1450"


@pytest.mark.parametrize("mid,pin,vmin,vmax", [
    ("sp3485", "VCC", 3.135, 3.465), ("thvd1450", "VCC", 3.0, 5.5), ("tja1051", "VCC", 4.5, 5.5),
    ("tja1051", "VIO", 2.8, 5.5), ("mcp2562", "VDD", 4.5, 5.5), ("mcp2562", "VIO", 1.8, 5.5),
    ("sx1262", "VBAT", 1.8, 3.7), ("cc1101", "DVDD", 1.8, 3.6), ("rfm69hcw", "3.3V", 1.8, 3.6)])
def test_supply_ranges_from_the_data_sheets(mid, pin, vmin, vmax):
    s = modules.catalog().get(mid)["supplies"][pin]
    assert s["min"]["value"] == vmin and s["max"]["value"] == vmax


def test_tja1051_variant_t_has_no_vio():
    e = modules.catalog().get("tja1051", "t")
    assert "VIO" not in e["supplies"] and e["io"]["domain"] == "VCC"
    assert "VIO" not in {p["name"] for p in e["pins"]}


def test_ncomm_transceivers_are_counted_by_the_wired_rules():
    # the wired tables include the ncomm transceivers, so the ncomm copies of the rules stay silent
    assert set(ncomm.RS485_PINS) <= set(wired.RS485_PINS)
    assert set(ncomm.CAN_PINS) <= set(wired.CAN_PINS)


# --- supply (mod.supply_range) ----------------------------------------------------------------------------------------
SR = ("mod.supply_range",)


@pytest.mark.parametrize("part", [rs485(vcc="5V"), can(module="tja1051", VCC="3V3"), can(module="mcp2562", VDD="3V3"),
                                  sx1262(vbat="5V"), cc1101(dvdd="5V", avdd="5V"), rfm69(vdd="5V")])
def test_wrong_rail_fails_supply_range(part):
    r = run([part], assignments=UART + TWAI + SPI, only=SR)
    assert fs(r, SR[0], "failed"), part["module"]


@pytest.mark.parametrize("part", [rs485(), rs485(module="thvd1450"), can(), can(module="mcp2562"), sx1262(), cc1101(),
                                  rfm69()])
def test_right_rail_passes_supply_range(part):
    r = run([part], assignments=UART + TWAI + SPI, only=SR)
    assert fs(r, SR[0], "failed") == [] and fs(r, SR[0], "passed"), part["module"]


# --- levels (mod.level_out / mod.level_in) ----------------------------------------------------------------------------
LV = ("mod.level_out", "mod.level_in")


def test_thvd1450_at_5v_drives_the_esp_rx_too_high():
    r = run([rs485(module="thvd1450", vcc="5V")], only=LV)
    assert "danger" in sev(r, "mod.level_out")
    r = run([rs485(module="thvd1450")], only=LV)
    assert fs(r, "mod.level_out", "failed") == []


def test_tja1051_vio_on_3v3_is_level_safe_vio_on_5v_is_not():
    ok = run([can()], assignments=TWAI, only=LV)
    assert fs(ok, "mod.level_out", "failed") == [] and fs(ok, "mod.level_in", "failed") == []
    bad = run([can(vio="5V")], assignments=TWAI, only=LV)
    assert "danger" in sev(bad, "mod.level_out")


def test_tja1051_without_vio_variant_drives_5v():
    r = run([can(variant="t")], assignments=TWAI, only=LV)
    assert "danger" in sev(r, "mod.level_out")


def test_mcp2562_vio_3v3_is_level_safe():
    r = run([can(module="mcp2562")], assignments=TWAI, only=LV)
    assert fs(r, "mod.level_out", "failed") == [] and fs(r, "mod.level_in", "failed") == []


@pytest.mark.parametrize("part", [sx1262(), cc1101(), rfm69()])
def test_radios_at_3v3_are_level_safe(part):
    r = run([part], assignments=SPI, only=LV)
    assert fs(r, "mod.level_out", "failed") == [], part["module"]


# --- mod.ncomm.rs485_termination / can_termination ---------------------------------------------------------------------
RT, CT = ("mod.wired.rs485_termination",), ("mod.wired.can_termination",)  # one bus count


def test_rs485_two_terminators_pass():
    parts = [rs485("U1"), rs485("U2", module="thvd1450"), res("R1", "BUS_A", "BUS_B"), res("R2", "BUS_B", "BUS_A")]
    r = run(parts, only=RT)
    assert fs(r, RT[0], "failed") == [] and len(fs(r, RT[0], "passed")) == 1


def test_rs485_without_terminator_is_an_info_hint():
    r = run([rs485()], only=RT)
    (f,) = fs(r, RT[0], "failed")
    assert f.severity == "info" and "120 Ω" in f.message and f.source_ids == ["mod-ncomm-sp3485-ds"]
    assert "mod_wired_rs485_termination" in k.codes(r)


def test_rs485_three_terminators_caution():
    parts = [rs485("U1"), rs485("U2"), res("R1", "BUS_A", "BUS_B"), res("R2", "BUS_A", "BUS_B"),
             res("R3", "BUS_A", "BUS_B")]
    (f,) = fs(run(parts, only=RT), RT[0], "failed")
    assert f.severity == "caution"


def test_mixed_bus_is_left_to_the_wired_rule():
    parts = [rs485("U1"), rs485("U2", module="max3485")]
    r = run(parts, only=RT + ("mod.ncomm.rs485_termination",))
    assert fs(r, "mod.ncomm.rs485_termination") == []
    assert len(fs(r, RT[0], "failed")) == 1


def test_can_termination_counts_resistors():
    r = run([can("U1"), can("U2", module="mcp2562"), res("R1", "CAN_H", "CAN_L")], assignments=TWAI, only=CT)
    (f,) = fs(r, CT[0], "failed")
    assert f.severity == "info" and "CAN bus" in f.message
    r = run([can("U1"), can("U2", module="mcp2562"), res("R1", "CAN_H", "CAN_L"), res("R2", "CAN_H", "CAN_L")],
            assignments=TWAI, only=CT)
    assert fs(r, CT[0], "failed") == [] and fs(r, CT[0], "passed")


def test_can_unconnected_bus_pins_not_checked():
    r = run([can(CANL=None)], assignments=TWAI, only=CT)
    (f,) = fs(r, CT[0], "not_checked")
    assert f.severity == "info"


def test_termination_defers_once_wired_lists_the_ids(monkeypatch):
    monkeypatch.setattr(wired, "RS485_PINS", {**wired.RS485_PINS, **ncomm.RS485_PINS})
    assert ncomm._termination(None, RT[0], ncomm.RS485_PINS, wired.RS485_PINS, "RS-485") == []


# --- mod.ncomm.can_listen_only ---------------------------------------------------------------------------------------
LO = ("mod.ncomm.can_listen_only",)


def test_mcp2562_stby_open_is_standby():
    (f,) = fs(run([can(module="mcp2562", STBY=None)], assignments=TWAI, only=LO), LO[0], "failed")
    assert f.severity == "caution" and "Standby" in f.message and f.source_ids == ["mod-ncomm-mcp2562-ds"]


def test_mcp2562_stby_at_3v3_is_standby_gnd_or_gpio_passes():
    (f,) = fs(run([can(module="mcp2562", STBY="3V3")], assignments=TWAI, only=LO), LO[0], "failed")
    assert f.severity == "caution"
    assert fs(run([can(module="mcp2562")], assignments=TWAI, only=LO), LO[0], "passed")
    tw = TWAI + [k.assign("out", 6, "CSTBY")]
    r = run([can(module="mcp2562", STBY="CSTBY")], assignments=tw, only=LO)
    assert fs(r, LO[0], "failed") == [] and "GPIO6" in fs(r, LO[0], "passed")[0].message


def test_mcp2562_stby_resistor_to_gnd_passes_unknown_net_not_checked():
    r = run([can(module="mcp2562", STBY="NSTBY"), res("R5", "NSTBY", "GND", "10k")], assignments=TWAI, only=LO)
    assert fs(r, LO[0], "passed") and fs(r, LO[0], "failed") == []
    r = run([can(module="mcp2562", STBY="NSTBY")], assignments=TWAI, only=LO)
    assert fs(r, LO[0], "not_checked")


def test_tja1051_s_open_is_normal_s_high_is_silent():
    r = run([can()], assignments=TWAI, only=LO)
    assert fs(r, LO[0], "passed") and fs(r, LO[0], "failed") == []
    (f,) = fs(run([can(S="3V3")], assignments=TWAI, only=LO), LO[0], "failed")
    assert f.severity == "caution" and "Silent" in f.message


# --- mod.ncomm.sx126x_busy -------------------------------------------------------------------------------------------
BU = ("mod.ncomm.sx126x_busy",)


def test_sx1262_busy_on_gpio_passes():
    r = run([sx1262()], assignments=SPI, only=BU)
    assert fs(r, BU[0], "passed") and fs(r, BU[0], "failed") == []


@pytest.mark.parametrize("busy", [None, "NOWHERE"])
def test_sx1262_busy_missing_is_caution(busy):
    (f,) = fs(run([sx1262(BUSY=busy)], assignments=SPI, only=BU), BU[0], "failed")
    assert f.severity == "caution" and "BUSY" in f.message


# --- mod.ncomm.rfm69_reset / rfm69_pa20 ------------------------------------------------------------------------------
RR, PA = ("mod.ncomm.rfm69_reset",), ("mod.ncomm.rfm69_pa20",)


def test_rfm69_reset_high_holds_the_module_in_reset():
    (f,) = fs(run([rfm69(RESET="3V3")], assignments=SPI, only=RR), RR[0], "failed")
    assert f.severity == "caution" and "active high" in f.message


@pytest.mark.parametrize("net", [None, "GND", "IRQ2"])
def test_rfm69_reset_open_gnd_or_gpio_passes(net):
    sp = SPI + [k.assign("out", 21, "IRQ2")]
    r = run([rfm69(RESET=net)], assignments=sp, only=RR)
    assert fs(r, RR[0], "passed") and fs(r, RR[0], "failed") == []


def test_rfm69_pa20_duty_info_and_low_supply_caution():
    (f,) = fs(run([rfm69()], assignments=SPI, only=PA), PA[0], "failed")
    assert f.severity == "info" and "1.00 %" in f.message
    r = run([rfm69(vdd="VLOW")], assignments=SPI, options={"rails": {"VLOW": 2.0}}, only=PA)
    assert "caution" in sev(r, PA[0])


# --- mod.ncomm.cc1101_supply -----------------------------------------------------------------------------------------
CS = ("mod.ncomm.cc1101_supply",)


def test_cc1101_equal_supplies_pass_unequal_caution_unknown_not_checked():
    assert fs(run([cc1101()], assignments=SPI, only=CS), CS[0], "passed")
    r = run([cc1101(avdd="VA")], assignments=SPI, options={"rails": {"VA": 2.5}}, only=CS)
    assert sev(r, CS[0]) == ["caution"]
    assert fs(run([cc1101(avdd="VX")], assignments=SPI, only=CS), CS[0], "not_checked")


# --- end to end -------------------------------------------------------------------------------------------------------
def test_end_to_end_pins_check_with_sx1262():
    parts = [{"ref": "U3", "kind": "ic", "value": "SX1262", "module": "sx1262",
              "conn": {"VBAT": "3V3", "VBAT_IO": "3V3", "GND": "GND", "NSS": "CS0", "SCK": "SCK", "MOSI": "MOSI",
                       "MISO": "MISO", "DIO1": "IRQ"}}]
    out = pins.check("esp32s3", SPI[:5], parts=parts, options={})
    codes = {w["code"] for w in out.get("warnings", [])}
    assert "mod_ncomm_sx126x_busy" in codes


# --- data corrections ------------------------------------------------------------------------------------------------
def test_tja1051_v_in_max_is_the_absolute_rating_with_footnote_5():
    e = modules.catalog().get("tja1051")
    v = e["io"]["v_in_max"]
    assert (v["value"], v["page"]) == (7.0, 7) and "footnote [5]" in v["conditions"]
    assert any(n.get("page") == 10 and "VCC + 0.3 V" in n["text"] for n in e["notes"])
