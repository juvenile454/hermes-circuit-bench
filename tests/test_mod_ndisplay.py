"""Module family ndisplay: catalog entries of data/modules/ndisplay.json (HT16K33,
TM1638, IS31FL3731, ST7735S) and the rules in bench_core/modrules/ndisplay.py, on synthetic projects
(tests/modkit.py) with the real catalog and the real ESP32-S3 values (VDD 3.3 V, VOH 2.64 V, input max 3.6 V)."""
from __future__ import annotations

import pytest

import modkit as mk
from circuit_bench.bench_core import modules

I2C = {"SDA": "SDA0", "SCL": "SCL0", "GND": "GND"}
PULLUPS = [{"ref": "RP1", "kind": "resistor", "value": "4k7", "conn": {"1": "SDA0", "2": "3V3"}},
           {"ref": "RP2", "kind": "resistor", "value": "4k7", "conn": {"1": "SCL0", "2": "3V3"}}]
TM_GPIO = [mk.assign("out", 4, "STB"), mk.assign("out", 5, "CLK"), mk.assign("out", 6, "DIO")]
SPI = [mk.assign("spi_sck", 12, "SCK"), mk.assign("spi_mosi", 11, "MOSI"), mk.assign("spi_cs", 10, "CS"),
       mk.assign("out", 9, "DC"), mk.assign("out", 14, "RST")]
ST = {"CSX": "CS", "SCL": "SCK", "SDA": "MOSI", "D/CX": "DC", "RESX": "RST", "VDD": "3V3", "GND": "GND"}


def ht(ref, vdd="3V3", **kw):
    return mk.mod(ref, "ht16k33", {**I2C, "VDD": vdd}, **kw)


def tm(ref, vdd="3V3", **conn):
    return mk.mod(ref, "tm1638", {"VDD": vdd, "GND": "GND", "STB": "STB", "CLK": "CLK", "DIO": "DIO", **conn})


def is31(ref, ad="GND", sdb: str | None = "3V3", vcc="3V3"):
    conn = {**I2C, "VCC": vcc, "AD": ad}
    if sdb is not None:
        conn["SDB"] = sdb
    return mk.mod(ref, "is31fl3731", conn)


def res(ref, a, b, value="10k"):
    return {"ref": ref, "kind": "resistor", "value": value, "conn": {"1": a, "2": b}}


def i2c_run(parts, **kw):
    return mk.run(assignments=mk.i2c(), parts=[*parts, *PULLUPS], **kw)


def one(report, rule_id, status=None):
    fs = mk.findings(report, rule_id, status)
    assert len(fs) == 1, fs
    return fs[0]


# --- catalog ------------------------------------------------------------------------------------------------------
def test_ndisplay_entries_load_with_their_classes():
    cat = modules.catalog()
    assert [p for p in cat.problems if "ndisplay" in p] == []
    want = {"ht16k33": ("A1", "display.led"), "tm1638": ("A1", "display.led"),
            "is31fl3731": ("A", "display.led"), "st7735s": ("A2", "display.tft")}
    for mid, (cls, category) in want.items():
        m = cat.get(mid)
        assert m["_wp"] == "ndisplay" and m["_class"] == cls and m["kind"] == "ic" and m["category"] == category
    assert cat.get("st7735")["id"] == "st7735s" and cat.get("ht16k33-backpack")["id"] == "ht16k33"


def test_interfaces_and_addresses():
    cat = modules.catalog()
    h = cat.get("ht16k33")["interfaces"][0]
    assert h["type"] == "i2c" and h["addresses"]["value"] == [f"0x7{i}" for i in range(8)] and h["default"] == "0x70"
    assert h["f_max_hz"]["value"] == 400000
    i = cat.get("is31fl3731")["interfaces"][0]
    assert i["addresses"]["value"] == ["0x74", "0x75", "0x76", "0x77"]
    assert i["select"] == {"pin": "AD", "map": {"GND": "0x74", "SCL": "0x75", "SDA": "0x76", "VCC": "0x77"}}
    t = cat.get("tm1638")
    assert [it["type"] for it in t["interfaces"]] == ["digital"] and t["interfaces"][0]["f_max_hz"]["value"] == 1e6
    assert not any(p["signal"].startswith(("i2c", "spi")) for p in t["pins"])
    s = cat.get("st7735s")
    assert s["interfaces"][0]["type"] == "spi" and round(s["interfaces"][0]["f_max_hz"]["value"]) == 15151515
    assert {p["signal"] for p in s["pins"]} >= {"spi_sck", "spi_sdi", "spi_cs", "reset_in"}


# --- HT16K33: 0x70–0x77 against TCA9548A and the PCA9685 All Call --------------------------------------------------
def tca(ref="U2", a=("GND", "GND", "GND")):
    return mk.mod(ref, "tca9548a", {**I2C, "VCC": "3V3", "A2": a[0], "A1": a[1], "A0": a[2], "RESET": "3V3"})


def pca(ref="U3"):
    conn = {**I2C, "VDD": "3V3", "VSS": "GND", "OE": "GND", "A5": "VDD"}
    conn.update({f"A{i}": "GND" for i in range(5)})
    return mk.mod(ref, "pca9685", conn)


def test_ht16k33_default_0x70_conflicts_with_tca9548a():
    f = one(i2c_run([ht("U1"), tca()]), "mod.address_conflict", "failed")
    assert set(f.refs) == {"U1", "U2"} and "0x70" in f.message and f.severity == "caution"


def test_ht16k33_jumpered_address_resolves_the_tca_conflict():
    r = i2c_run([ht("U1", address="0x71"), tca()])
    assert mk.findings(r, "mod.address_conflict", "failed") == []


def test_ht16k33_at_0x70_hits_the_pca9685_all_call():
    r = i2c_run([ht("U1"), pca()])
    f = [x for x in mk.findings(r, "mod.address_reserved", "failed") if "U1" in x.refs]
    assert len(f) == 1 and "0x70" in f[0].message
    r = i2c_run([ht("U1", address="0x72"), pca()])
    assert [x for x in mk.findings(r, "mod.address_reserved", "failed") if "U1" in x.refs] == []


def test_ht16k33_at_0x74_conflicts_with_is31fl3731_default():
    f = one(i2c_run([ht("U1", address="0x74"), is31("U2")]), "mod.address_conflict", "failed")
    assert set(f.refs) == {"U1", "U2"} and "0x74" in f.message


def test_ht16k33_supply_3v3_below_range_5v_passes():
    f = one(i2c_run([ht("U1")]), "mod.supply_range", "failed")
    assert f.severity == "caution" and "4.50 V" in f.message
    assert one(i2c_run([ht("U1", vdd="5V")]), "mod.supply_range").status == "passed"


def test_ht16k33_on_5v_with_3v3_bus_is_below_vih():
    fs = mk.findings(i2c_run([ht("U1", vdd="5V")]), "mod.level_in", "failed")
    assert fs and all(f.severity == "caution" for f in fs) and any("3.50 V" in f.message for f in fs)


# --- TM1638 --------------------------------------------------------------------------------------------------------
def tm_run(parts, assignments=TM_GPIO, **kw):
    return mk.run(assignments=assignments, parts=parts, **kw)


def test_tm1638_supply_3v3_inside_the_3_to_6_v_range():
    assert one(tm_run([tm("U1")]), "mod.supply_range").status == "passed"
    assert one(tm_run([tm("U1", vdd="5V")]), "mod.supply_range").status == "passed"


def test_tm1638_at_5v_needs_more_than_the_esp_high():
    fs = mk.findings(tm_run([tm("U1", vdd="5V")]), "mod.level_in", "failed")
    assert fs and "3.50 V" in fs[0].message


def test_tm1638_dio_pullup_to_5v_is_danger():
    r = tm_run([tm("U1", vdd="5V"), res("R1", "DIO", "5V")])
    f = one(r, "mod.ndisplay.tm1638_dio_pullup", "failed")
    assert f.severity == "danger" and "GPIO6" in f.message and "5.00 V" in f.message
    assert f.source_ids == ["mod-ndisplay-tm1638-ds"]


def test_tm1638_dio_pullup_to_3v3_passes_and_level_shifter_clears():
    assert one(tm_run([tm("U1"), res("R1", "DIO", "3V3")]), "mod.ndisplay.tm1638_dio_pullup").status == "passed"
    p = tm("U1", vdd="5V")
    p["facts"] = {"level_shifter": True}
    assert one(tm_run([p, res("R1", "DIO", "5V")]), "mod.ndisplay.tm1638_dio_pullup").status == "passed"


def test_tm1638_without_pullup_is_left_to_required_parts():
    r = tm_run([tm("U1")])
    assert mk.findings(r, "mod.ndisplay.tm1638_dio_pullup") == []
    req = [f for f in mk.findings(r, "mod.required_parts", "failed") if "DIO" in f.message]
    assert req and req[0].severity == "info"  # only needed for reading keys ("recommended 10K")


def test_tm1638_dio_pullup_without_esp_data_is_not_checked():
    r = tm_run([tm("U1"), res("R1", "DIO", "3V3")], electrical={})
    assert one(r, "mod.ndisplay.tm1638_dio_pullup").status == "not_checked"


def test_tm1638_on_i2c_nets_is_flagged():
    r = mk.run(assignments=[*mk.i2c(), mk.assign("out", 4, "STB")], parts=[tm("U1", CLK="SCL0", DIO="SDA0")])
    f = one(r, "mod.ndisplay.tm1638_own_lines", "failed")
    assert f.severity == "caution" and "SCL0" in f.message and "SDA0" in f.message


def test_tm1638_on_spi_nets_shared_with_st7735s_is_flagged():
    a = [*SPI, mk.assign("out", 4, "STB")]
    r = mk.run(assignments=a, parts=[mk.mod("U2", "st7735s", ST), tm("U1", CLK="SCK", DIO="MOSI")])
    f = one(r, "mod.ndisplay.tm1638_own_lines", "failed")
    assert "spi_sck" in f.message and "spi_mosi" in f.message
    r = mk.run(assignments=a, parts=[mk.mod("U2", "st7735s", ST), tm("U1", DIO="DC")])
    assert "shared with st7735s" in one(r, "mod.ndisplay.tm1638_own_lines", "failed").message


def test_tm1638_on_own_gpios_passes():
    assert one(tm_run([tm("U1")]), "mod.ndisplay.tm1638_own_lines").status == "passed"


# --- IS31FL3731 ----------------------------------------------------------------------------------------------------
def test_is31_ad_selects_four_addresses():
    parts = [is31("U1", "GND"), is31("U2", "SCL0"), is31("U3", "SDA0"), is31("U4", "3V3")]
    assert mk.findings(i2c_run(parts), "mod.address_conflict", "failed") == []


def test_is31_same_ad_conflicts_and_lists_alternatives():
    f = one(i2c_run([is31("U1"), is31("U2")]), "mod.address_conflict", "failed")
    assert "0x74" in f.message and "0x75 (AD to SCL)" in f.message


def test_is31_ad_scl_conflicts_with_a_jumpered_ht16k33():
    f = one(i2c_run([is31("U1", "SCL0"), ht("U2", address="0x75")]), "mod.address_conflict", "failed")
    assert set(f.refs) == {"U1", "U2"}


def test_is31_sdb_to_gnd_is_hardware_shutdown():
    f = one(i2c_run([is31("U1", sdb="GND")]), "mod.ndisplay.is31_sdb", "failed")
    assert f.severity == "caution" and "p. 18" in f.message


def test_is31_sdb_high_or_gpio_passes_open_is_unconnected():
    assert one(i2c_run([is31("U1")]), "mod.ndisplay.is31_sdb").status == "passed"
    r = mk.run(assignments=[*mk.i2c(), mk.assign("out", 7, "SDB")], parts=[is31("U1", sdb="SDB"), *PULLUPS])
    assert one(r, "mod.ndisplay.is31_sdb").status == "passed"
    r = i2c_run([is31("U1", sdb=None)])
    assert mk.findings(r, "mod.ndisplay.is31_sdb") == []
    assert any("SDB" in f.message for f in mk.findings(r, "mod.unconnected", "failed"))


def test_is31_supply_range():
    assert one(i2c_run([is31("U1")]), "mod.supply_range").status == "passed"
    assert one(i2c_run([is31("U1", vcc="5V")]), "mod.supply_range").status == "passed"
    f = one(i2c_run([is31("U1", vcc="V7")], options={"rails": {"V7": 7.0}}), "mod.supply_range", "failed")
    assert f.severity == "danger"


def test_is31_vih_only_at_5v5_is_never_interpolated():
    assert mk.findings(i2c_run([is31("U1")]), "mod.level_in", "failed") == []


# --- ST7735S -------------------------------------------------------------------------------------------------------
def test_st7735s_on_3v3_passes_supply_and_levels():
    r = mk.run(assignments=SPI, parts=[mk.mod("U1", "st7735s", ST)])
    sup = mk.findings(r, "mod.supply_range")
    assert sup and all(f.status == "passed" for f in sup)  # VDDI follows VDD via its tie
    assert mk.findings(r, "mod.level_in", "failed") == []


@pytest.mark.parametrize("pin,limit", [("VDD", "4.80 V"), ("VDDI", "4.60 V")])
def test_st7735s_on_5v_exceeds_abs_max(pin, limit):
    r = mk.run(assignments=SPI, parts=[mk.mod("U1", "st7735s", {**ST, "VDD": "5V"})])
    fs = [f for f in mk.findings(r, "mod.supply_range", "failed") if f"{pin} on" in f.message]
    assert len(fs) == 1 and fs[0].severity == "danger" and limit in fs[0].message


def test_st7735s_vddi_on_3v3_with_vdd_on_5v_still_flags_vdd():
    r = mk.run(assignments=SPI, parts=[mk.mod("U1", "st7735s", {**ST, "VDD": "5V", "VDDI": "3V3"})])
    fs = mk.findings(r, "mod.supply_range", "failed")
    assert [f.message.split(" on ")[0].split()[-1] for f in fs] == ["VDD"]
