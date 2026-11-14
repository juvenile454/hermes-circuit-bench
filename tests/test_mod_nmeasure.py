"""Module family nmeasure: MCP3208, MCP4728, INA228, MAX31856, ADS1220 with the real catalog;
family rule mod.nmeasure.ain_range. Synthetic projects only.

The module entries' evidence is checked by tests/test_m0_modules_data.py; here: the limits that live in code
(modrules/nmeasure.py) against tests/corpus/excerpts/mod-nmeasure-*.txt, plus address, supply and level findings of
the generic rules for each part.
"""
from __future__ import annotations

import excerpts as ex
import modkit as mk
from circuit_bench.bench_core import electrical, modules, pins
from circuit_bench.bench_core.modrules import nmeasure as nm

ESP = electrical.get("esp32s3")
I2C = {"SDA": "SDA0", "SCL": "SCL0"}
RULE = nm.RULE
EXCERPT_OF = {f"mod-nmeasure-{p}-ds": f"mod-nmeasure-{p}.txt"
              for p in ("mcp3208", "mcp4728", "ina228", "max31856", "ads1220")}
SPI = [mk.assign("spi_sck", 12, "SCK"), mk.assign("spi_mosi", 11, "MOSI"), mk.assign("spi_miso", 13, "MISO"),
       mk.assign("spi_cs", 10, "CS0")]


def _cited(source_id: str, page: int, parts: list[str]) -> bool:
    e = ex.parse(ex.EXCERPTS / EXCERPT_OF[source_id])
    assert e.source_id == source_id
    return any(ex.find_parts_in_order(parts, seg) for seg in e.page_segments(page))


def _run(*parts, options=None, assignments=None, only=None):
    return mk.run(electrical=ESP, assignments=mk.i2c() if assignments is None else assignments, parts=list(parts),
                  options=options, only=only)


def _spi(*parts, options=None, only=None):
    return _run(*parts, options=options, assignments=SPI, only=only)


def _addresses(rep):
    return {d["ref"]: d["address"] for b in rep.result["buses"] for s in b["segments"] for d in s["devices"]}


def _found(rep, rule_id, status=None):
    return [(f.status, f.severity) for f in mk.findings(rep, rule_id) if status is None or f.status == status]


def mcp3208(ref="U1", vdd="3V3", **conn):
    return mk.mod(ref, "mcp3208", {"CLK": "SCK", "DIN": "MOSI", "DOUT": "MISO", "CS/SHDN": "CS0", "VDD": vdd, **conn})


def ads1220(ref="U2", vdd="3V3", **conn):
    return mk.mod(ref, "ads1220", {"SCLK": "SCK", "DIN": "MOSI", "DOUT/DRDY": "MISO", "CS": "CS0", "AVDD": vdd,
                                   **conn})


def max31856(ref="U3", vdd="3V3", **conn):
    return mk.mod(ref, "max31856", {"SCK": "SCK", "SDI": "MOSI", "SDO": "MISO", "CS": "CS0", "AVDD": vdd, **conn})


def ina228(ref="U4", a1="GND", a0="GND", vs="3V3", **conn):
    return mk.mod(ref, "ina228", {**I2C, "VS": vs, "GND": "GND", "A1": a1, "A0": a0, **conn})


def mcp4728(ref="U5", vdd="3V3", address=None):
    return mk.mod(ref, "mcp4728", {**I2C, "VDD": vdd}, address=address)


# --- catalog and citations ------------------------------------------------------------------------------------------
def test_all_five_parts_are_in_the_catalog_with_their_class():
    cat = modules.catalog()
    want = {"mcp3208": ("A", "adc"), "mcp4728": ("A", "dac"), "ina228": ("A", "power.monitor"),
            "max31856": ("A1", "sensor.temperature"), "ads1220": ("A", "adc")}
    for mid, (cls, category) in want.items():
        m = cat.get(mid)
        assert m["_wp"] == "nmeasure" and m["_class"] == cls and m["category"] == category, mid
    assert not [p for p in cat.problems if p.startswith("nmeasure.json")]


def test_limits_in_code_quote_the_excerpts():
    for mid, lim in nm.LIMITS.items():
        for key in ("abs_ev", "op_ev"):
            sid, page, parts = lim[key]
            assert sid in modules.catalog().get(mid)["source_ids"], (mid, key)
            assert _cited(sid, page, parts), (mid, key)
        names = {p["name"] for p in modules.catalog().get(mid)["pins"]}
        assert set(lim["pins"]) <= names, mid


def test_ads1220_pins_are_the_sixteen_of_the_datasheet_table():
    """Datasheet p. 4, Table 5-1 (RVA/PW pin numbers; the thermal pad is no signal pin): 16 pins, SCLK among them."""
    pins = {p["name"]: p for p in modules.catalog().get("ads1220")["pins"]}
    assert sorted(pins) == sorted([
        "AIN0/REFP1", "AIN1", "AIN2", "AIN3/REFN1", "AVDD", "AVSS", "CLK", "CS", "DGND", "DIN", "DOUT/DRDY", "DRDY",
        "DVDD", "REFN0", "REFP0", "SCLK"])
    assert pins["SCLK"]["signal"] == "spi_sck" and "p. 4" in pins["SCLK"]["note"]
    assert pins["CLK"]["signal"] == "digital_in"  # the external clock source input, not the SPI clock
    assert _cited("mod-nmeasure-ads1220-ds", 4, ["SCLK 15 1 Digital input Serial clock input"])
    assert _cited("mod-nmeasure-ads1220-ds", 4, ["CLK 1 3 Digital input External clock source pin."])


def test_ads1220_external_clock_pin_is_not_the_spi_clock():
    """Only CLK (external clock source) wired to the SPI clock net leaves SCLK open: reported as a half-wired bus."""
    wired = ads1220(CLK="GND")
    assert wired["conn"]["SCLK"] == "SCK"
    assert not [w for w in mk.run(electrical=ESP, assignments=SPI, parts=[wired]).warnings
                if w["code"] == "mod_unconnected" and "SCLK" in w["message"]]
    conn = {k: v for k, v in wired["conn"].items() if k != "SCLK"}
    conn["CLK"] = "SCK"
    rep = mk.run(electrical=ESP, assignments=SPI, parts=[mk.mod("U2", "ads1220", conn)])
    half = [w for w in rep.warnings if w["code"] == "mod_unconnected" and "SCLK" in w["message"]]
    assert len(half) == 1 and "half wired" in half[0]["message"]


def test_key_numbers_of_the_entries():
    cat = modules.catalog()
    m = cat.get("max31856")
    assert m["supplies"]["AVDD"]["max"]["value"] == 3.6 and m["supplies"]["AVDD"]["abs_max"]["value"] == 4.0
    assert m["interfaces"][0]["mode"] == 1 and m["interfaces"][0]["f_max_hz"]["value"] == 5e6
    assert cat.get("mcp3208")["interfaces"][0]["f_max_hz"]["value"] == 1e6  # the 2.7 V value, never interpolated
    a = cat.get("ads1220")["interfaces"][0]
    assert a["mode"] == 1 and a["f_max_hz"]["value"] <= 1 / 150e-9
    i = cat.get("ina228")
    assert i["interfaces"][0]["select"]["map"]["VS,SDA"] == "0x46" and len(i["interfaces"][0]["addresses"]["value"]) == 16
    assert cat.get("mcp4728")["interfaces"][0]["default"] == "0x60"
    assert "select" not in cat.get("mcp4728")["interfaces"][0]  # EEPROM address, no pin


# --- addresses ------------------------------------------------------------------------------------------------------
def test_mcp4728_default_collides_with_an_mcp4725():
    rep = _run(mcp4728(), mk.mod("U6", "mcp4725", {**I2C, "VDD": "3V3", "A0": "GND"}), only=("mod.address_conflict",))
    assert _addresses(rep) == {"U5": "0x60", "U6": "0x60"}
    assert ("failed", "caution") in _found(rep, "mod.address_conflict")


def test_mcp4728_with_a_programmed_address_is_free():
    rep = _run(mcp4728(address="0x61"), mk.mod("U6", "mcp4725", {**I2C, "VDD": "3V3", "A0": "GND"}),
               only=("mod.address_conflict",))
    assert _addresses(rep) == {"U5": "0x61", "U6": "0x60"}
    assert not _found(rep, "mod.address_conflict", "failed")


def test_ina228_address_pins_and_conflict_with_an_ina226():
    rep = _run(ina228(a1="3V3", a0="SDA0"), ina228("U7"), only=("mod.address_conflict",))  # A1 = VS, A0 = SDA
    assert _addresses(rep) == {"U4": "0x46", "U7": "0x40"}
    assert not _found(rep, "mod.address_conflict", "failed")
    rep = _run(ina228(), mk.mod("U8", "ina226", {**I2C, "VS": "3V3", "GND": "GND", "A1": "GND", "A0": "GND"}),
               only=("mod.address_conflict",))
    assert ("failed", "caution") in _found(rep, "mod.address_conflict")


# --- supply ---------------------------------------------------------------------------------------------------------
def test_max31856_on_5v_is_danger_and_on_3v3_fine():
    rep = _spi(max31856(vdd="5V"), only=("mod.supply_range",))
    assert ("failed", "danger") in _found(rep, "mod.supply_range")
    rep = _spi(max31856(), only=("mod.supply_range",))
    assert not _found(rep, "mod.supply_range", "failed")


def test_supply_ranges_of_the_others():
    for part in (mcp4728(vdd="5V"), ina228(vs="5V")):
        rep = _run(part, only=("mod.supply_range",))
        assert not _found(rep, "mod.supply_range", "failed"), part["module"]
    for part in (mcp3208(vdd="5V"), ads1220(vdd="5V")):
        rep = _spi(part, only=("mod.supply_range",))
        assert not _found(rep, "mod.supply_range", "failed"), part["module"]
    rep = _run(ina228(vs="SIX"), options={"rails": {"SIX": 6.5}}, only=("mod.supply_range",))
    assert ("failed", "danger") in _found(rep, "mod.supply_range")


# --- levels ---------------------------------------------------------------------------------------------------------
def test_spi_adcs_at_5v_drive_miso_above_the_esp_maximum():
    for part in (mcp3208(vdd="5V"), ads1220(vdd="5V")):
        rep = _spi(part, only=("mod.level_out",))
        assert ("failed", "danger") in _found(rep, "mod.level_out"), part["module"]
        rep = _spi({**part, "conn": {**part["conn"], next(k for k in part["conn"] if k in ("VDD", "AVDD")): "3V3"}},
                   only=("mod.level_out",))
        assert not _found(rep, "mod.level_out", "failed"), part["module"]


def test_ina228_logic_levels_are_fixed_and_fit_3v3():
    rep = _run(ina228(vs="5V"), only=("mod.level_in", "mod.level_out"))
    assert not _found(rep, "mod.level_in", "failed") and not _found(rep, "mod.level_out", "failed")


# --- family rule mod.nmeasure.ain_range -----------------------------------------------------------------------------
def test_mcp3208_input_above_vdd_plus_0v6_is_danger():
    rep = _spi(mcp3208(CH0="5V"), only=(RULE,))
    assert _found(rep, RULE) == [("failed", "danger")]


def test_mcp3208_input_above_vref_is_caution_and_within_passes():
    rep = _spi(mcp3208(vdd="5V", VREF="3V3", CH1="5V"), only=(RULE,))
    assert _found(rep, RULE) == [("failed", "caution")]
    rep = _spi(mcp3208(vdd="5V", CH1="3V3"), only=(RULE,))  # VREF tied to VDD by default
    assert _found(rep, RULE) == [("passed", None)]


def test_ads1220_inputs():
    assert _found(_spi(ads1220(**{"AIN0/REFP1": "5V"}), only=(RULE,)), RULE) == [("failed", "danger")]
    assert _found(_spi(ads1220(AIN1="3V3"), only=(RULE,)), RULE) == [("passed", None)]
    rep = _spi(ads1220(AIN2="V36"), options={"rails": {"V36": 3.6}}, only=(RULE,))  # 3.6 V: above +0.1, below +0.3
    assert _found(rep, RULE) == [("failed", "caution")]


def test_max31856_thermocouple_on_a_rail():
    assert _found(_spi(max31856(**{"T-": "GND"}), only=(RULE,)), RULE) == [("failed", "caution")]
    rep = _spi(max31856(**{"T+": "V48"}), options={"rails": {"V48": 48}}, only=(RULE,))
    assert _found(rep, RULE) == [("failed", "danger")]
    rep = _spi(max31856(**{"T-": "VB"}), options={"rails": {"VB": 0.75}}, only=(RULE,))
    assert _found(rep, RULE) == [("passed", None)]


def test_no_claim_without_a_known_voltage_and_not_checked_without_supply():
    assert _found(_spi(mcp3208(CH0="SENSOR"), only=(RULE,)), RULE) == []
    rep = _spi(mcp3208(vdd="VX", CH0="3V3"), only=(RULE,))
    assert _found(rep, RULE) == [("not_checked", "info")]


def test_end_to_end_through_pins_check():
    rep = pins.check("esp32s3", SPI, parts=[{"ref": "U1", "kind": "ic", "value": "MCP3208", "module": "mcp3208",
                                             "conn": {"CLK": "SCK", "DIN": "MOSI", "DOUT": "MISO", "CS/SHDN": "CS0",
                                                      "VDD": "3V3", "AGND": "GND", "DGND": "GND", "CH0": "5V"}}],
                     options={})
    codes = {w["code"] for w in rep["warnings"]}
    assert "mod_nmeasure_ain_range" in codes
