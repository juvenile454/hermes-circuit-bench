"""Module family radio: catalog entries nRF24L01+, SX1276, RFM95W, MFRC522, PN532
(variants spi/i2c/hsu) and the rules of modrules/radio.py. The generic checks (structure, evidence ⊂ excerpt, excerpt ↔
pinned PDF) are the generic module data tests; here: one synthetic project per part with the expected supply, address and family
findings, and the rule constants tied to the quoted lines in the entries.
"""
from __future__ import annotations

import pytest

import modkit as k
from circuit_bench.bench_core import modcheck, modules
from circuit_bench.bench_core.modrules import radio

RADIO_IDS = ("nrf24l01p", "sx1276", "rfm95w", "mfrc522", "pn532")


@pytest.fixture(scope="module")
def cat():
    modules.clear_cache()
    c = modules.catalog()
    assert c.problems == []
    return c


def _spi(cs=10, cs_net="CS0", sck=12, mosi=11, miso=13):
    return [k.assign("spi_sck", sck, "SCK0"), k.assign("spi_mosi", mosi, "MOSI0"), k.assign("spi_miso", miso, "MISO0"),
            k.assign("spi_cs", cs, cs_net)]


def _supply(report):
    return [(f.status, f.severity, tuple(f.refs)) for f in k.findings(report, "mod.supply_range")]


def _one(report, rule_id, status=None):
    fs = k.findings(report, rule_id, status)
    assert len(fs) == 1, [f.message for f in k.findings(report, rule_id)]
    return fs[0]


NRF = {"VCC": "3V3", "GND": "GND", "CE": "GPIO9", "CSN": "CS0", "SCK": "SCK0", "MOSI": "MOSI0", "MISO": "MISO0",
       "IRQ": "GPIO8"}
SX = {"VBAT_DIG": "3V3", "GND": "GND", "NSS": "CS0", "SCK": "SCK0", "MOSI": "MOSI0", "MISO": "MISO0",
      "NRESET": "GPIO9", "DIO0": "GPIO8"}
RFM = {"3.3V": "3V3", "GND": "GND", "NSS": "CS0", "SCK": "SCK0", "MOSI": "MOSI0", "MISO": "MISO0", "RESET": "GPIO9",
       "DIO0": "GPIO8"}
MF = {"3.3V": "3V3", "GND": "GND", "SDA": "CS0", "SCK": "SCK0", "MOSI": "MOSI0", "MISO": "MISO0", "RST": "GPIO9"}
PN_SPI = {"VBAT": "3V3", "PVDD": "3V3", "GND": "GND", "NSS": "CS0", "SCK": "SCK0", "MOSI": "MOSI0", "MISO": "MISO0"}
PN_I2C = {"VBAT": "5V", "PVDD": "3V3", "GND": "GND", "SDA": "SDA0", "SCL": "SCL0"}
RAILS = {"rails": {"3V3": 3.3, "5V": 5.0}}


# --- catalog ---------------------------------------------------------------------------------------------------------
def test_all_radio_parts_are_in_the_catalog(cat):
    classes = {mid: cat.get(mid)["_class"] for mid in RADIO_IDS}
    assert classes == {"nrf24l01p": "A2", "sx1276": "A2", "rfm95w": "A", "mfrc522": "A", "pn532": "A"}
    assert {cat.get(m)["category"] for m in ("nrf24l01p", "sx1276", "rfm95w")} == {"comm.radio"}
    assert {cat.get(m)["category"] for m in ("mfrc522", "pn532")} == {"comm.rfid"}
    assert cat.resolve_id("rc522") == "mfrc522" and cat.resolve_id("nrf24l01+") == "nrf24l01p"
    assert cat.resolve_id("sx1278") == "sx1276" and cat.resolve_id("rfm96w") == "rfm95w"
    assert cat.get("rfm95w")["source_ids"] == ["mod-radio-rfm95w-ds", "mod-radio-rfm95w-sf"]


def test_spi_interfaces_carry_mode_speed_and_bit_order(cat):
    def spi(mid, variant=None):
        return next(it for it in cat.get(mid, variant)["interfaces"] if it["type"] == "spi")
    assert {m: (spi(m).get("mode"), spi(m)["f_max_hz"]["value"], spi(m)["lsb_first"]) for m in RADIO_IDS} == {
        "nrf24l01p": (0, 10e6, False), "sx1276": (0, 10e6, False), "rfm95w": (0, 10e6, False),
        "mfrc522": (None, 10e6, False), "pn532": (0, 5e6, True)}


def test_pn532_interfaces_are_separate_variants(cat):
    i2c = cat.get("pn532", "i2c")
    assert [it["type"] for it in i2c["interfaces"]] == ["i2c"]
    assert i2c["interfaces"][0]["addresses"]["value"] == ["0x24"] and i2c["interfaces"][0]["default"] == "0x24"
    assert i2c["interfaces"][0]["f_max_hz"]["value"] == 400e3 and i2c["io"]["outputs"] == "open_drain"
    assert {p["name"]: p["signal"] for p in i2c["pins"]}["SDA"] == "i2c_sda"
    hsu = cat.get("pn532", "hsu")
    assert hsu["interfaces"] == [{"type": "uart", "baud_default": 115200,
                                  "note": "8 data bits, no parity, 1 stop bit, LSB first (UM0701-02 p. 26)"}]
    assert {p["name"]: p["signal"] for p in hsu["pins"]}["HSU_TX"] == "uart_tx"
    assert [it["type"] for it in cat.get("pn532")["interfaces"]] == ["spi"]


def test_tx_peaks_are_in_current_peak(cat):
    peaks = {m: cat.get(m)["current"]["peak"]["value"] for m in RADIO_IDS}
    assert peaks == {"nrf24l01p": 0.0135, "sx1276": 0.12, "rfm95w": 0.12, "mfrc522": 0.1, "pn532": 0.15}
    assert cat.get("rfm95w")["current"]["peak"]["source_id"] == "mod-radio-rfm95w-sf"


def _evidence(cat, mid):
    e = cat.get(mid)
    items = [*(e.get("requires") or []), *(e.get("notes") or [])]
    return [(it.get("source_id") or e["source_ids"][0], it.get("page"), str(it.get("evidence")))
            for it in items if "evidence" in it]


def test_rule_constants_match_the_quoted_lines(cat):
    """The numbers in modrules/radio.py are the ones quoted (and checked against the PDFs) in radio.json."""
    nrf = _evidence(cat, "nrf24l01p")
    assert (radio.NRF_BULK["source_id"], radio.NRF_BULK["page"]) in {(s, p) for s, p, ev in nrf if "4.7µF" in ev}
    for mid, (sid, page, duty, vmin) in radio.PA20.items():
        texts = [t for s, p, t in _evidence(cat, mid) if (s, p) == (sid, page)]
        assert any(f"- {duty:g} %" in t for t in texts), mid
        assert any(f"{vmin:g} 3.7 V" in t for t in texts), mid
    pn = _evidence(cat, "pn532")
    assert (radio.PN532_SPI["source_id"], radio.PN532_SPI["page"], "The data order used is LSB first.") in pn


def test_capacitance_parser():
    assert radio.capacitance("4.7uF") == pytest.approx(4.7e-6)
    assert radio.capacitance("4u7") == pytest.approx(4.7e-6)
    assert radio.capacitance("10 µF 16V") == pytest.approx(10e-6)
    assert radio.capacitance("100nF") == pytest.approx(100e-9)
    assert radio.capacitance("big") is None and radio.capacitance(None) is None


# --- nRF24L01+ -------------------------------------------------------------------------------------------------------
def test_nrf24_supply_and_bulk_cap():
    ok = k.run(assignments=_spi(), parts=[k.mod("U1", "nrf24l01p", NRF)], options=RAILS)
    assert _supply(ok) == [("passed", None, ("U1",))]
    f = _one(ok, "mod.radio.nrf24_bulk_cap")
    assert (f.status, f.severity) == ("failed", "info") and "no capacitor between 3V3 and GND" in f.message
    assert "p. 65" in f.message and f.source_ids == ["mod-radio-nrf24l01p-ps"]

    five = k.run(assignments=_spi(), parts=[k.mod("U1", "nrf24l01p", {**NRF, "VCC": "5V"})], options=RAILS)
    assert _supply(five) == [("failed", "caution", ("U1",))]  # A2 module, breakout cap without facts
    hard = k.run(assignments=_spi(), parts=[k.mod("U1", "nrf24l01p", {**NRF, "VCC": "5V"},
                                                  facts={"regulator": "none"})], options=RAILS)
    assert _supply(hard) == [("failed", "danger", ("U1",))]  # A2 with manufacturer header may be hard


def test_nrf24_bulk_cap_passes_with_a_large_capacitor_and_flags_a_small_one():
    big = {"ref": "C1", "kind": "capacitor", "value": "10uF", "conn": {"1": "3V3", "2": "GND"}}
    small = {"ref": "C2", "kind": "capacitor", "value": "100nF", "conn": {"1": "3V3", "2": "GND"}}
    r = k.run(assignments=_spi(), parts=[k.mod("U1", "nrf24l01p", NRF), big, small], options=RAILS)
    assert _one(r, "mod.radio.nrf24_bulk_cap").status == "passed"
    r = k.run(assignments=_spi(), parts=[k.mod("U1", "nrf24l01p", NRF), small], options=RAILS)
    f = _one(r, "mod.radio.nrf24_bulk_cap")
    assert f.status == "failed" and "largest capacitor on 3V3–GND is 100 nF" in f.message
    r = k.run(assignments=_spi(), parts=[k.mod("U1", "nrf24l01p", {k_: v for k_, v in NRF.items() if k_ != "VCC"})])
    assert _one(r, "mod.radio.nrf24_bulk_cap").status == "not_checked"


# --- SX1276 / RFM95W -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mid,conn,page", [("sx1276", SX, 84), ("rfm95w", RFM, 80)])
def test_lora_supply_and_duty_cycle(mid, conn, page):
    r = k.run(assignments=_spi(), parts=[k.mod("U1", mid, conn)], options=RAILS)
    sup = _supply(r)
    assert sup and all(s == ("passed", None, ("U1",)) for s in sup)
    f = _one(r, "mod.radio.sx1276_duty_20dbm")
    assert (f.status, f.severity) == ("failed", "info") and "1 %" in f.message and "2.4–3.7 V" in f.message and f"p. {page}" in f.message

    low_conn = {pin: ("VLOW" if net == "3V3" else net) for pin, net in conn.items()}
    low = k.run(assignments=_spi(), parts=[k.mod("U1", mid, low_conn)], options={"rails": {"VLOW": 2.0}})
    f = _one(low, "mod.radio.sx1276_duty_20dbm")
    assert (f.status, f.severity) == ("failed", "caution") and "not available" in f.message

    five = k.run(assignments=_spi(), parts=[k.mod("U1", mid, {**conn, next(iter(conn)): "5V"})], options=RAILS)
    worst = {s[1] for s in _supply(five) if s[0] == "failed"}
    assert worst == {"danger"}  # bare chip, and the RFM95W module documented by its maker (module_datasheet)


# --- MFRC522 ---------------------------------------------------------------------------------------------------------
def test_mfrc522_sda_as_chip_select_passes():
    r = k.run(assignments=_spi(), parts=[k.mod("U1", "mfrc522", MF)], options=RAILS)
    assert _supply(r) == [("passed", None, ("U1",))]
    assert _one(r, "mod.radio.mfrc522_sda_is_cs").status == "passed"


def test_mfrc522_sda_on_the_i2c_bus_is_a_caution():
    parts = [k.mod("U1", "mfrc522", {**MF, "SDA": "SDA0"}),
             k.mod("U2", "bme280", {"SDI": "SDA0", "SCK": "SCL0", "SDO": "GND", "VDD": "3V3", "GND": "GND"})]
    r = k.run(assignments=[*_spi(), *k.i2c()], parts=parts, options=RAILS)
    f = _one(r, "mod.radio.mfrc522_sda_is_cs")
    assert (f.status, f.severity) == ("failed", "caution") and "SPI chip select (NSS)" in f.message
    assert "mod_radio_mfrc522_sda_is_cs" in k.codes(r)
    # a module's I²C SDA on the net without an ESP i2c pin
    r = k.run(assignments=_spi(), parts=parts, options=RAILS)
    f = _one(r, "mod.radio.mfrc522_sda_is_cs")
    assert f.status == "failed" and "I²C SDA of U2" in f.message


def test_mfrc522_on_5v_is_flagged():
    r = k.run(assignments=_spi(), parts=[k.mod("U1", "mfrc522", {**MF, "3.3V": "5V"}, facts={"regulator": "none"})],
              options=RAILS)
    assert _supply(r) == [("failed", "danger", ("U1",))]  # 5 V > abs max 4.0 V


# --- PN532 -----------------------------------------------------------------------------------------------------------
def test_pn532_spi_is_lsb_first():
    r = k.run(assignments=_spi(), parts=[k.mod("U1", "pn532", PN_SPI)], options=RAILS)
    assert {s[0] for s in _supply(r)} == {"passed"}
    f = _one(r, "mod.radio.pn532_lsb_first")
    assert (f.status, f.severity) == ("failed", "info") and "LSB first" in f.message and "p. 25" in f.message


def test_pn532_i2c_address_and_supplies():
    ctx = modcheck.build_ctx(chip="esp32s3", assignments=k.i2c(), parts=[k.mod("U1", "pn532", PN_I2C, variant="i2c")],
                             options=RAILS, devkit=None, catalog=None, electrical=None)
    assert ctx is not None
    inst = ctx.instance("U1")
    assert (inst.address, inst.address_from) == ("0x24", "default")
    assert [d["address"] for d in ctx.buses[0]["segments"][0]["devices"]] == ["0x24"]
    r = k.run(assignments=k.i2c(), parts=[k.mod("U1", "pn532", PN_I2C, variant="i2c")], options=RAILS)
    assert {s[0] for s in _supply(r)} == {"passed"}  # VBAT 5 V is in range (2.7–5.5 V)
    assert k.findings(r, "mod.radio.pn532_lsb_first") == []
    bad = k.run(assignments=k.i2c(), parts=[k.mod("U1", "pn532", {**PN_I2C, "PVDD": "5V"}, variant="i2c")],
                options=RAILS)
    assert ("failed", "danger", ("U1",)) in _supply(bad)  # PVDD abs max 4 V


def test_pn532_hsu_variant_has_no_spi_hint():
    conn = {"VBAT": "3V3", "PVDD": "3V3", "GND": "GND", "HSU_RX": "TX1", "HSU_TX": "RX1"}
    r = k.run(assignments=[k.assign("uart_tx", 17, "TX1"), k.assign("uart_rx", 18, "RX1")],
              parts=[k.mod("U1", "pn532", conn, variant="hsu")], options=RAILS)
    assert k.findings(r, "mod.radio.pn532_lsb_first") == []
    assert {s[0] for s in _supply(r)} == {"passed"}


# --- data corrections ------------------------------------------------------------------------------------------------
def test_pn532_decoupling_sits_on_dvdd(cat):
    for v in (None, "i2c", "hsu"):
        e = cat.get("pn532", v)
        dec = [r for r in e["requires"] if r["code"] == "decoupling"]
        assert dec and all(r["pins"] == ["DVDD"] for r in dec), v
        assert {p["name"]: p["signal"] for p in e["pins"]}["DVDD"] == "power_out"
