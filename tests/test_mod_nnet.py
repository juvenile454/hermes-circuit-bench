"""Module family nnet: catalog entries LAN8720A, ENC28J60, MAX-M10S, FT232RL, CP2104, CH9102F and
PN5180 (data/modules/nnet.json) and the family rule mod.nnet.rmii_pins (bench_core/modrules/nnet.py).

Synthetic projects on the real catalog and the real ESP values (electrical.get); the generic engine rules (supply,
levels, addresses, required parts) are in place, so their findings are expected hard.
"""
from __future__ import annotations

import json
from pathlib import Path

import modkit as k
import pytest

from circuit_bench.bench_core import modules, pins
from circuit_bench.bench_core.modrules import nnet

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "circuit_bench" / "data" / "modules" / "nnet.json"
IDS = ("lan8720a", "enc28j60", "max_m10s", "ft232rl", "cp2104", "ch9102f", "pn5180")

SPI = [k.assign("spi_sck", 12, "SCK"), k.assign("spi_mosi", 11, "MOSI"), k.assign("spi_miso", 13, "MISO"),
       k.assign("spi_cs", 10, "CS0"), k.assign("in", 14, "INT")]
UART = [k.assign("uart_tx", 17, "TX1"), k.assign("uart_rx", 18, "RX1")]
# ESP32 EMAC: ESP-IDF v6.1 esp_eth.rst lines 5-12
RMII = [k.assign("out", 21, "TXEN"), k.assign("out", 19, "TXD0"), k.assign("out", 22, "TXD1"),
        k.assign("in", 25, "RXD0"), k.assign("in", 26, "RXD1"), k.assign("in", 27, "CRSDV"),
        k.assign("out", 23, "MDC"), k.assign("in", 18, "MDIO")]
LAN = {"VDDIO": "3V3", "VDD1A": "3V3", "VDD2A": "3V3", "VSS": "GND", "TXEN": "TXEN", "TXD0": "TXD0",
       "TXD1": "TXD1", "RXD0": "RXD0", "RXD1": "RXD1", "CRS_DV": "CRSDV", "MDC": "MDC", "MDIO": "MDIO",
       "nRST": "3V3"}


def run(parts, assignments=UART, chip="esp32s3", options=None, only=None):
    return k.run(chip=chip, assignments=assignments, parts=parts, options=options, only=only)


def fs(report, rule_id, status=None):
    return k.findings(report, rule_id, status)


def sev(report, rule_id):
    return sorted({f.severity for f in fs(report, rule_id, "failed")})


def cap(ref, a, b="GND", value="100nF"):
    return {"ref": ref, "kind": "capacitor", "value": value, "conn": {"1": a, "2": b}}


def enc(ref="U1", vdd="3V3", **extra):
    return k.mod(ref, "enc28j60", {"VDD": vdd, "VSS": "GND", "SCK": "SCK", "SI": "MOSI", "SO": "MISO", "CS": "CS0",
                                   "INT": "INT", "VCAP": "VCAP", **extra})


def gnss(ref="U5", vcc="3V3", **extra):
    return k.mod(ref, "max_m10s", {"VCC": vcc, "V_IO": vcc, "V_BCKP": "3V3", "GND": "GND", "TXD": "RX1",
                                   "RXD": "TX1", **extra})


def pn(ref="U6", **extra):
    return k.mod(ref, "pn5180", {"VBAT": "3V3", "PVDD": "3V3", "TVDD": "5V", "VSS": "GND", "SCK": "SCK",
                                 "MOSI": "MOSI", "MISO": "MISO", "NSS": "CS0", "BUSY": "INT", "RESET_N": "RST",
                                 **extra})


# --- catalog ------------------------------------------------------------------------------------------------------
def test_catalog_loads_every_nnet_part_without_problems():
    cat = modules.Catalog.from_dir()
    assert [p for p in cat.problems if "nnet" in p] == []
    for mid in IDS:
        entry = cat.get(mid)
        assert entry["_wp"] == "nnet" and entry["_class"] in ("A", "A1") and entry["kind"] == "ic"
    data = json.loads(DATA.read_text())
    assert data["wp"] == "nnet" and sorted(m["id"] for m in data["modules"]) == sorted(IDS)
    cats = {m["id"]: m["category"] for m in data["modules"]}
    assert cats["lan8720a"] == cats["enc28j60"] == "comm.ethernet"
    assert cats["ft232rl"] == cats["cp2104"] == cats["ch9102f"] == "comm.usb_uart"
    assert cats["max_m10s"] == "comm.gnss" and cats["pn5180"] == "comm.rfid"
    assert cat.get("cp2104")["_class"] == cat.get("ft232rl")["_class"] == "A1"  # web.archive.org snapshots


def test_uart_pins_are_module_view():
    cat = modules.Catalog.from_dir()
    for mid in ("max_m10s", "ft232rl", "cp2104", "ch9102f"):
        sig = {p["name"]: p["signal"] for p in cat.get(mid)["pins"]}
        assert sig["TXD"] == "uart_tx" and sig["RXD"] == "uart_rx", mid


def test_key_values_match_the_data_sheets():
    cat = modules.Catalog.from_dir()
    v = modules.value
    s = cat.get("lan8720a")["supplies"]
    assert (v(s["VDDIO"]["min"], {}), v(s["VDD2A"]["min"], {}), v(s["VDD2A"]["abs_max"], {})) == (1.62, 3.0, 3.6)
    m = cat.get("enc28j60")
    assert (v(m["supplies"]["VDD"]["min"], {}), v(m["supplies"]["VDD"]["max"], {})) == (3.1, 3.6)
    assert v(m["io"]["vih"], {}) == 2.25 and v(m["io"]["v_in_max"], {}) == 6.0 and m["io"]["five_v_tolerant"]
    assert v(m["interfaces"][0]["f_max_hz"], {}) == 20e6 and m["interfaces"][0]["mode"] == 0
    m = cat.get("max_m10s")
    i2c = [i for i in m["interfaces"] if i["type"] == "i2c"][0]
    assert i2c["addresses"]["value"] == ["0x42"] and v(i2c["f_max_hz"], {}) == 400000
    assert v(m["io"]["vih"], {"V_IO": 3.3}) == pytest.approx(0.68 * 3.3)
    assert v(m["io"]["v_in_max"], {"V_IO": 3.3}) == pytest.approx(3.6)
    m = cat.get("ft232rl")["supplies"]
    assert (v(m["VCC"]["min"], {}), v(m["VCC"]["max"], {}), v(m["VCC"]["abs_max"], {})) == (4.0, 5.25, 6.0)
    m = cat.get("cp2104")
    assert v(m["supplies"]["VDD"]["abs_max"], {}) == 4.2 and v(m["supplies"]["REGIN"]["max"], {}) == 5.25
    base, low = cat.get("ch9102f"), cat.get("ch9102f", "3v3")
    assert v(base["supplies"]["VDD5"]["min"], {}) == 4.0 and v(low["supplies"]["VDD5"]["max"], {}) == 3.6
    assert v(base["io"]["v_in_max"], {"VIO": 3.3}) == pytest.approx(3.8)
    m = cat.get("pn5180")
    assert v(m["supplies"]["PVDD"]["max"], {}) == 3.6 and v(m["supplies"]["TVDD"]["max"], {}) == 5.5
    assert v(m["interfaces"][0]["f_max_hz"], {}) == 7e6


# --- supply range -------------------------------------------------------------------------------------------------
def test_enc28j60_on_5v_is_above_abs_max():
    r = run([enc(vdd="5V")], assignments=SPI, only=("mod.supply_range",))
    assert sev(r, "mod.supply_range") == ["danger"]  # 5 V > 3.6 V absolute maximum
    r = run([enc()], assignments=SPI, only=("mod.supply_range",))
    assert fs(r, "mod.supply_range", "failed") == []


def test_max_m10s_on_5v_is_danger():
    r = run([gnss(vcc="5V")], only=("mod.supply_range",))
    assert "danger" in sev(r, "mod.supply_range")
    assert fs(run([gnss()], only=("mod.supply_range",)), "mod.supply_range", "failed") == []


def test_ft232rl_needs_vcc_4v_with_the_internal_oscillator():
    p = k.mod("U2", "ft232rl", {"VCC": "3V3", "VCCIO": "3V3", "GND": "GND", "AGND": "GND", "TEST": "GND",
                                "TXD": "RX1", "RXD": "TX1"})
    r = run([p], only=("mod.supply_range",))
    assert sev(r, "mod.supply_range") == ["caution"]  # 3.3 V < 4.0 V minimum, below abs max


def test_cp2104_vdd_on_5v_is_danger():
    p = k.mod("U4", "cp2104", {"VDD": "5V", "VIO": "5V", "REGIN": "5V", "GND": "GND", "TXD": "RX1", "RXD": "TX1"})
    assert "danger" in sev(run([p], only=("mod.supply_range",)), "mod.supply_range")  # 5 V > 4.2 V


def test_ch9102f_at_3v3_needs_the_variant():
    conn = {"VDD5": "3V3", "V3": "3V3", "VIO": "3V3", "GND": "GND", "TXD": "RX1", "RXD": "TX1"}
    base = run([k.mod("U3", "ch9102f", conn)], only=("mod.supply_range",))
    assert sev(base, "mod.supply_range") == ["caution"]  # 3.3 V below the 4.0 V of the 5 V mode
    low = run([k.mod("U3", "ch9102f", conn, variant="3v3")], only=("mod.supply_range",))
    assert fs(low, "mod.supply_range", "failed") == []


def test_pn5180_pvdd_on_5v_is_danger():
    r = run([pn(PVDD="5V")], assignments=SPI + [k.assign("out", 15, "RST")], only=("mod.supply_range",))
    assert "danger" in sev(r, "mod.supply_range")  # PVDD 5 V > 3.6 V limiting value


# --- levels -------------------------------------------------------------------------------------------------------
def test_ft232rl_with_vccio_5v_drives_the_esp_at_5v():
    conn = {"VCC": "5V", "GND": "GND", "AGND": "GND", "TEST": "GND", "TXD": "RX1", "RXD": "TX1"}
    hi = run([k.mod("U2", "ft232rl", {**conn, "VCCIO": "5V"})], only=("mod.level_out",))
    assert sev(hi, "mod.level_out") == ["danger"]
    lo = run([k.mod("U2", "ft232rl", {**conn, "VCCIO": "3V3"})], only=("mod.level_out",))
    assert "danger" not in sev(lo, "mod.level_out")


def test_ch9102f_vio_5v_drives_the_esp_at_5v():
    conn = {"VDD5": "5V", "V3": "V3", "GND": "GND", "TXD": "RX1", "RXD": "TX1"}
    hi = run([k.mod("U3", "ch9102f", {**conn, "VIO": "5V"})], only=("mod.level_out",))
    assert sev(hi, "mod.level_out") == ["danger"]
    lo = run([k.mod("U3", "ch9102f", {**conn, "VIO": "3V3"})], only=("mod.level_out",))
    assert fs(lo, "mod.level_out", "failed") == []


def test_enc28j60_outputs_stay_at_3v3():
    r = run([enc()], assignments=SPI, only=("mod.level_out", "mod.level_in"))
    assert [f for f in fs(r, "mod.level_out", "failed") if f.severity == "danger"] == []


# --- address ------------------------------------------------------------------------------------------------------
def test_max_m10s_address_conflict_with_a_second_receiver():
    a = gnss("U5", SDA="SDA0", SCL="SCL0")
    b = gnss("U8", SDA="SDA0", SCL="SCL0")
    r = run([a, b], assignments=UART + k.i2c(), only=("mod.address_conflict",))
    failed = fs(r, "mod.address_conflict", "failed")
    assert failed and "0x42" in failed[0].message
    one = run([a], assignments=UART + k.i2c(), only=("mod.address_conflict",))
    assert fs(one, "mod.address_conflict", "failed") == []


# --- required parts -----------------------------------------------------------------------------------------------
def test_enc28j60_vcap_capacitor():
    bare = run([enc()], assignments=SPI, only=("mod.required_parts",))
    assert any("VCAP" in f.message for f in fs(bare, "mod.required_parts", "failed"))
    ok = run([enc(), cap("C1", "VCAP", value="10uF"), cap("C2", "3V3")], assignments=SPI,
             only=("mod.required_parts",))
    assert fs(ok, "mod.required_parts", "failed") == []


# --- end to end through pins.check --------------------------------------------------------------------------------
def test_end_to_end_pins_check_reports_the_enc28j60_on_5v():
    parts = [{"ref": "U1", "kind": "ic", "value": "ENC28J60", "module": "enc28j60",
              "conn": {"VDD": "5V", "VSS": "GND", "SCK": "SCK", "SI": "MOSI", "SO": "MISO", "CS": "CS0"}}]
    res = pins.check("esp32s3", SPI, parts=parts, options={})
    codes = {w["code"] for w in res["warnings"]}
    assert "mod_supply_range" in codes


# --- family rule: mod.nnet.rmii_pins -------------------------------------------------------------------------------
def test_rmii_on_the_esp32_emac_pins_passes():
    r = run([k.mod("U7", "lan8720a", LAN)], assignments=RMII, chip="esp32", only=("mod.nnet.rmii_pins",))
    assert [f.status for f in fs(r, "mod.nnet.rmii_pins")] == ["passed"]


def test_rmii_on_a_wrong_gpio_is_caution():
    wrong = [a for a in RMII if a["net"] != "TXD0"] + [k.assign("out", 4, "TXD0")]
    r = run([k.mod("U7", "lan8720a", LAN)], assignments=wrong, chip="esp32", only=("mod.nnet.rmii_pins",))
    failed = fs(r, "mod.nnet.rmii_pins", "failed")
    assert [f.severity for f in failed] == ["caution"]
    assert "TXD0 on GPIO4" in failed[0].message and "GPIO19" in failed[0].message


def test_rmii_ref_clk_on_gpio0_is_a_strapping_hint():
    conn = {**LAN, "XTAL1": "REFCLK"}
    r = run([k.mod("U7", "lan8720a", conn)], assignments=RMII + [k.assign("in", 0, "REFCLK")], chip="esp32",
            only=("mod.nnet.rmii_pins",))
    failed = fs(r, "mod.nnet.rmii_pins", "failed")
    assert [f.severity for f in failed] == ["info"] and "GPIO0" in failed[0].message
    assert [f.status for f in fs(r, "mod.nnet.rmii_pins", "passed")] == ["passed"]
    bad = run([k.mod("U7", "lan8720a", conn)], assignments=RMII + [k.assign("in", 5, "REFCLK")], chip="esp32",
              only=("mod.nnet.rmii_pins",))
    assert any("REF_CLK" in f.message and f.severity == "caution" for f in fs(bad, "mod.nnet.rmii_pins", "failed"))


@pytest.mark.parametrize("chip", ["esp32s3", "esp32c3", "esp32c6"])
def test_rmii_phy_on_a_chip_without_emac_is_caution(chip):
    r = run([k.mod("U7", "lan8720a", LAN)], assignments=[k.assign("out", 4, "TXEN")], chip=chip,
            only=("mod.nnet.rmii_pins",))
    failed = fs(r, "mod.nnet.rmii_pins", "failed")
    assert [f.severity for f in failed] == ["caution"] and "ENC28J60" in failed[0].message
    assert nnet.IDF_ETH in failed[0].source_ids


def test_rmii_without_esp_wiring_is_not_checked():
    r = run([k.mod("U7", "lan8720a", {"VDDIO": "3V3", "VDD1A": "3V3", "VDD2A": "3V3", "VSS": "GND"})],
            assignments=[], chip="esp32", only=("mod.nnet.rmii_pins",))
    assert [f.status for f in fs(r, "mod.nnet.rmii_pins")] == ["not_checked"]


def test_rmii_rule_ignores_other_parts():
    r = run([enc()], assignments=SPI, chip="esp32", only=("mod.nnet.rmii_pins",))
    assert fs(r, "mod.nnet.rmii_pins") == []


def test_rmii_tables_match_the_pinned_esp_idf_doc():
    doc = ROOT / "tests" / ".corpus" / "esp-idf" / "v6.1" / "docs" / "en" / "api-reference" / "network" / "esp_eth.rst"
    if not doc.is_file():
        main = Path(modules.__file__).resolve().parents[2]
        doc = main / "tests" / ".corpus" / "esp-idf" / "v6.1" / "docs" / "en" / "api-reference" / "network" / "esp_eth.rst"
    if not doc.is_file():
        pytest.skip("corpus file missing: esp-idf/v6.1/.../esp_eth.rst (scripts/fetch_corpus.py wt32)")
    lines = doc.read_text(encoding="utf-8").splitlines()[:12]
    names = {"TXEN": "RMII_TX_EN", "TXD0": "RMII_TXD0", "TXD1": "RMII_TXD1", "CRS_DV": "RMII_CRS_DV",
             "RXD0": "RMII_RXD0", "RXD1": "RMII_RXD1"}

    def gpios(key, chip):
        line = next(x for x in lines if f"IDF_TARGET_SOC_{key}:" in x)
        val = line.split(f'{chip}="', 1)[1].split('"', 1)[0]
        return tuple(int(t) for t in val.replace("GPIO", " ").replace(",", " ").replace("and", " ").split())

    for chip in ("esp32", "esp32p4"):
        for pin, key in names.items():
            assert nnet.RMII_PINS[chip][pin] == gpios(key, chip), (chip, pin)
        assert nnet.REF_CLK_IN[chip] == gpios("REF_CLK_IN_GPIO", chip)
        assert nnet.REF_CLK_OUT[chip] == gpios("REF_CLK_OUT_GPIO", chip)


# --- data corrections ------------------------------------------------------------------------------------------------
def test_lan8720a_input_levels_from_table_5_5():
    e = modules.catalog().get("lan8720a")
    io = e["io"]
    assert (io["vih"]["value"], io["vil"]["value"], io["v_in_max"]["value"]) == (1.90, 0.64, 3.6)
    assert {io[k]["page"] for k in ("vih", "vil", "v_in_max")} == {56}
    assert e["notes"][4]["verified"] is True and "1.90 V" in e["notes"][4]["text"]
    ch = modules.catalog().get("ch9102f")["io"]
    assert ch["vih"]["conditions"] == "VIO = 3.3 V" and ch["vil"]["conditions"] == "VIO = 3.3 V"
