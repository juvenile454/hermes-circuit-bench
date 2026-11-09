"""Module family env: catalog entries BME280, BMP280, BME680, BME688, SHT31, SHT40,
AHT20, Si7021 and the rules of modrules/env.py. The generic checks (structure, evidence ⊂ excerpt, excerpt ↔ pinned
PDF) are the generic module data tests; here: one synthetic project per part with the expected address, level and supply findings.
"""
from __future__ import annotations

import pytest

import modkit as k
from circuit_bench.bench_core import modcheck, modules

ENV_IDS = ("bme280", "bmp280", "bme680", "bme688", "sht31", "sht40", "aht20", "si7021")
BOSCH = {"bme280": "SDI", "bmp280": "SDI", "bme680": "SDI", "bme688": "SDI"}


@pytest.fixture(scope="module")
def cat():
    modules.clear_cache()
    c = modules.catalog()
    assert c.problems == []
    return c


def _bosch(ref, mid, sdo="GND", vdd="3V3", **kw):
    conn = {"SDI": "SDA0", "SCK": "SCL0", "VDD": vdd, "GND": "GND"}
    if sdo is not None:
        conn["SDO"] = sdo
    return k.mod(ref, mid, conn, **kw)


def _two_wire(ref, mid, vdd="3V3", gnd="GND", extra=None, **kw):
    conn = {"SDA": "SDA0", "SCL": "SCL0", "VDD": vdd, gnd: "GND", **(extra or {})}
    return k.mod(ref, mid, conn, **kw)


def _ctx(*parts, options=None):
    return modcheck.build_ctx(chip="esp32s3", assignments=k.i2c(), parts=list(parts), options=options or {},
                              devkit=None, catalog=None, electrical=None)


def _supply(report):
    return [(f.status, f.severity, tuple(f.refs)) for f in k.findings(report, "mod.supply_range")]


# --- catalog ---------------------------------------------------------------------------------------------------------
def test_all_env_parts_are_in_the_catalog(cat):
    for mid in ENV_IDS:
        e = cat.get(mid)
        assert e["_wp"] == "env" and e["_class"] in ("A", "A1"), mid
        assert e["source_ids"] == [f"mod-env-{mid}-ds"], mid
    assert cat.get("si7021")["_class"] == "A1"  # web.archive.org copy of the silabs.com file
    assert cat.resolve_id("sht30") == "sht31" and cat.resolve_id("SHT45") == "sht40"


def test_pilot_bme280_keeps_the_demo_contract(cat):
    """desktop-src/fixtures and tests/test_api_fixtures.py (MODULES_DEMO) depend on these."""
    e = cat.get("bme280")
    assert [p["name"] for p in e["pins"]] == ["GND", "CSB", "SDI", "SCK", "SDO", "VDDIO", "VDD"]
    it = e["interfaces"][0]
    assert it["addresses"]["value"] == ["0x76", "0x77"] and it["default"] == "0x76"
    assert it["select"] == {"pin": "SDO", "map": {"GND": "0x76", "VDDIO": "0x77"}}


@pytest.mark.parametrize("mid,addrs", [("bmp280", ["0x76", "0x77"]), ("bme680", ["0x76", "0x77"]),
                                       ("bme688", ["0x76", "0x77"]), ("sht31", ["0x44", "0x45"]),
                                       ("aht20", ["0x38"]), ("si7021", ["0x40"])])
def test_addresses(cat, mid, addrs):
    assert modcheck.addresses(modcheck.i2c_iface(cat.get(mid))) == addrs


def test_sht40_variants_fix_the_address(cat):
    assert [v["id"] for v in cat.get("sht40")["variants"]] == ["ad1b", "bd1b", "cd1b"]
    for vid, addr in (("ad1b", "0x44"), ("bd1b", "0x45"), ("cd1b", "0x46")):
        it = modcheck.i2c_iface(cat.get("sht40", vid))
        assert modcheck.addresses(it) == [addr] and it["default"] == addr
    assert cat.get("sht40")["interfaces"][0]["default"] == "0x44"  # without a variant: AD1B, the common one


def test_heater_peaks_are_in_current_peak(cat):
    assert cat.get("bme680")["current"]["peak"]["value"] == pytest.approx(0.018)
    assert cat.get("bme688")["current"]["peak"]["value"] == pytest.approx(0.018)
    assert cat.get("sht40")["current"]["peak"]["value"] == pytest.approx(0.1)
    assert cat.get("si7021")["current"]["peak"]["value"] == pytest.approx(0.0942)


def test_rail_sum_counts_the_heater_peaks():
    ctx = _ctx(_bosch("U1", "bme680"), _two_wire("U2", "sht40", gnd="VSS"))
    rail = next(r for r in ctx.rail_sums if r["net"] == "3V3")
    assert rail["i_peak"] == pytest.approx(0.118)
    assert rail["i_max"] == pytest.approx(0.013 + 0.0005)


# --- one project per part: address, level, supply ---------------------------------------------------------------------
def test_bmp280_project():
    r = k.run(assignments=k.i2c(), parts=[_bosch("U1", "bmp280", sdo="VDDIO"), _bosch("U2", "bme280", sdo="GND")])
    assert k.findings(r, "mod.address_conflict", "failed") == []  # 0x77 next to 0x76
    ctx = _ctx(_bosch("U1", "bmp280", sdo="VDDIO"))
    u1 = ctx.instance("U1")
    assert (u1.address, u1.address_from) == ("0x77", "select")
    assert ctx.level(u1, "vih") == pytest.approx(0.8 * 3.3) and ctx.level(u1, "v_in_max") == pytest.approx(3.6)
    r5 = k.run(assignments=k.i2c(), parts=[_bosch("U1", "bmp280", vdd="5V")])
    assert _supply(r5) == [("failed", "danger", ("U1",))]  # 5 V > abs max 4.25 V


@pytest.mark.parametrize("mid", ["bme680", "bme688"])
def test_bme68x_project(mid):
    r = k.run(assignments=k.i2c(), parts=[_bosch("U1", mid), _bosch("U2", "bme280")])
    assert [tuple(f.refs) for f in k.findings(r, "mod.address_conflict", "failed")] == [("U1", "U2")]
    r = k.run(assignments=k.i2c(), parts=[_bosch("U1", mid, sdo="VDDIO"), _bosch("U2", "bme280")])
    assert k.findings(r, "mod.address_conflict", "failed") == []
    ctx = _ctx(_bosch("U1", mid))
    assert ctx.level(ctx.instance("U1"), "vil") == pytest.approx(0.2 * 3.3)
    assert _supply(k.run(assignments=k.i2c(), parts=[_bosch("U1", mid, vdd="5V")])) == [("failed", "danger", ("U1",))]


def test_sht31_project():
    ctx = _ctx(_two_wire("U1", "sht31", gnd="VSS", extra={"ADDR": "VDD"}))
    u1 = ctx.instance("U1")
    assert (u1.address, u1.address_from) == ("0x45", "select")
    r = k.run(assignments=k.i2c(), parts=[_two_wire("U1", "sht31", gnd="VSS", extra={"ADDR": "GND"}),
                                          _two_wire("U2", "sht40", gnd="VSS")])
    assert [tuple(f.refs) for f in k.findings(r, "mod.address_conflict", "failed")] == [("U1", "U2")]
    # 5 V is in the SHT3x range, but the logic levels follow VDD: VIH 3.5 V is above an ESP32 3.3 V output
    ctx5 = _ctx(_two_wire("U1", "sht31", vdd="5V", gnd="VSS", extra={"ADDR": "GND"}))
    assert ctx5.level(ctx5.instance("U1"), "vih") == pytest.approx(3.5)
    assert _supply(k.run(assignments=k.i2c(), parts=[_two_wire("U1", "sht31", vdd="5V", gnd="VSS",
                                                                extra={"ADDR": "GND"})])) == [("passed", None, ("U1",))]


def test_sht40_project():
    r = k.run(assignments=k.i2c(), parts=[_two_wire("U1", "sht40", gnd="VSS", variant="ad1b"),
                                          _two_wire("U2", "sht40", gnd="VSS", variant="bd1b")])
    assert k.findings(r, "mod.address_conflict", "failed") == []
    r = k.run(assignments=k.i2c(), parts=[_two_wire("U1", "sht40", gnd="VSS"),
                                          _two_wire("U2", "sht40", gnd="VSS", variant="ad1b")])
    assert len(k.findings(r, "mod.address_conflict", "failed")) == 1
    # no abs max in the datasheet: 5 V is only above the operating maximum 3.6 V
    assert _supply(k.run(assignments=k.i2c(), parts=[_two_wire("U1", "sht40", vdd="5V", gnd="VSS")])) == \
        [("failed", "caution", ("U1",))]


def test_aht20_project():
    ctx = _ctx(_two_wire("U1", "aht20", vdd="5V"))
    u1 = ctx.instance("U1")
    assert (u1.address, u1.address_from) == ("0x38", "default")
    assert ctx.level(u1, "vih") == pytest.approx(3.5) and ctx.level(u1, "v_in_max") == pytest.approx(5.3)
    assert _supply(k.run(assignments=k.i2c(), parts=[_two_wire("U1", "aht20", vdd="5V")])) == [("passed", None, ("U1",))]
    r = k.run(assignments=k.i2c(), parts=[_two_wire("U1", "aht20"), _two_wire("U2", "aht20")])
    assert len(k.findings(r, "mod.address_conflict", "failed")) == 1


def test_si7021_project():
    ctx = _ctx(_two_wire("U1", "si7021"))
    assert ctx.instance("U1").address == "0x40"
    assert ctx.level(ctx.instance("U1"), "vil") == pytest.approx(0.99)
    assert _supply(k.run(assignments=k.i2c(), parts=[_two_wire("U1", "si7021", vdd="5V")])) == \
        [("failed", "danger", ("U1",))]  # abs max 4.2 V


# --- family rules ----------------------------------------------------------------------------------------------------
ONLY = ("mod.env.bmp_vs_bme", "mod.env.bme680_sdo_float", "mod.env.sht_addr_float")


def test_bmp_vs_bme_hint():
    r = k.run(assignments=k.i2c(), parts=[_bosch("U1", "bme280"), _bosch("U2", "bmp280", sdo="VDDIO"),
                                          _bosch("U3", "bme680", sdo="VDDIO")], only=ONLY[:1])
    fs = k.findings(r, "mod.env.bmp_vs_bme")
    assert [(f.status, f.severity, f.refs) for f in fs] == [("failed", "info", ["U1"]), ("failed", "info", ["U2"])]
    assert "0x60" in fs[0].message and "0x58" in fs[0].message and "p. 27" in fs[0].message
    assert "p. 24" in fs[1].message
    assert fs[0].source_ids == ["mod-env-bme280-ds"] and fs[1].source_ids == ["mod-env-bmp280-ds"]
    assert k.findings(k.run(assignments=k.i2c(), parts=[_two_wire("U1", "sht31", gnd="VSS")], only=ONLY[:1])) == []


@pytest.mark.parametrize("mid,page", [("bme680", 38), ("bme688", 45), ("bme280", 33), ("bmp280", 28)])
def test_sdo_float(mid, page):
    r = k.run(assignments=k.i2c(), parts=[_bosch("U1", mid, sdo=None)], only=ONLY[1:2])
    (f,) = k.findings(r, "mod.env.bme680_sdo_float")
    assert (f.status, f.severity) == ("failed", "caution") and f"p. {page}" in f.message
    assert "mod_env_bme680_sdo_float" in k.codes(r)
    for sdo in ("GND", "VDDIO", "GPIO4"):
        r = k.run(assignments=k.i2c(), parts=[_bosch("U1", mid, sdo=sdo)], only=ONLY[1:2])
        assert [f.status for f in k.findings(r, "mod.env.bme680_sdo_float")] == ["passed"], sdo


@pytest.mark.parametrize("mid", ["bme680", "bme280"])
def test_sdo_float_covers_address_select(mid):
    """One cause, one warning: the family rule supersedes mod.address_select (SDO open) on the same part."""
    r = k.run(assignments=k.i2c(), parts=[_bosch("U1", mid, sdo=None)],
              only=("mod.env.bme680_sdo_float", "mod.address_select"))
    (f,) = k.findings(r, "mod.env.bme680_sdo_float")
    assert f.supersedes == ("mod.address_select",)
    assert [f.status for f in k.findings(r, "mod.address_select")] == ["failed"]  # still in the checks
    assert "mod_address_select" not in k.codes(r) and "mod_env_bme680_sdo_float" in k.codes(r)


def test_sht_addr_float():
    r = k.run(assignments=k.i2c(), parts=[_two_wire("U1", "sht31", gnd="VSS"),
                                          _two_wire("U2", "sht31", gnd="VSS", extra={"ADDR": "VDD"}),
                                          _two_wire("U3", "sht40", gnd="VSS")], only=ONLY[2:])
    fs = k.findings(r, "mod.env.sht_addr_float")
    assert [(f.status, f.severity, f.refs) for f in fs] == [("failed", "caution", ["U1"]), ("passed", None, ["U2"])]
    assert "must not be left floating" in fs[0].message and "p. 9" in fs[0].message
    assert k.check_of(r, "mod.env.sht_addr_float")["status"] == "failed"


def test_rules_stay_quiet_without_env_parts():
    r = k.run(assignments=k.i2c(), parts=[_two_wire("U1", "aht20"), _two_wire("U2", "si7021")], only=ONLY)
    assert k.findings(r) == []


def test_pins_check_end_to_end():
    from circuit_bench.bench_core import pins
    res = pins.check("esp32s3", [{"role": "SDA", "mode": "i2c_sda", "pin": 8, "net": "SDA0"},
                                 {"role": "SCL", "mode": "i2c_scl", "pin": 9, "net": "SCL0"}],
                     parts=[{"ref": "U1", "kind": "ic", "value": "BME680", "module": "bme680",
                             "conn": {"SDI": "SDA0", "SCK": "SCL0", "VDD": "3V3", "GND": "GND"}}], options={})
    text = repr(res)
    assert "mod_env_bme680_sdo_float" in text and "modules.env.bme680_sdo_float" in text
