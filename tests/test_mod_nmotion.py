"""Module family nmotion: catalog entries ICM-20948, BMI270, LSM6DS3TR-C, VL6180X, MAX30101, DRV5055
and the family rules mod.nmotion.* on synthetic projects (real catalog, real ESP32-S3 values)."""
from __future__ import annotations

import pytest

import modkit as mk
from circuit_bench.bench_core import modules, pins

CS = "mod.nmotion.cs_high_i2c"
CE = "mod.nmotion.vl6180x_ce"
VLED = "mod.nmotion.max30101_vled"
VCC = "mod.nmotion.drv5055_vcc"
AUX = "mod.nmotion.bmi270_aux_gnd"
R18 = {"rails": {"1V8": 1.8}}


@pytest.fixture(autouse=True)
def _fresh_catalog():
    modules.clear_cache()
    yield
    modules.clear_cache()


def one(report, rule_id, status=None):
    fs = mk.findings(report, rule_id, status)
    assert len(fs) == 1, [(f.rule_id, f.status, f.message) for f in mk.findings(report, rule_id)]
    return fs[0]


def icm(ref="U1", vddio="1V8", ad0: str | None = "GND", ncs: str | None = "1V8", **kw):
    conn = {"VDD": "3V3", "VDDIO": vddio, "GND": "GND", "SDA": "SDA0", "SCL": "SCL0", "FSYNC": "GND"}
    if ad0:
        conn["AD0"] = ad0
    if ncs:
        conn["nCS"] = ncs
    return mk.mod(ref, "icm20948", conn, **kw)


def bmi(ref="U1", sdo="GND", csb: str | None = "3V3", **extra):
    conn = {"VDD": "3V3", "VDDIO": "3V3", "GND": "GND", "GNDIO": "GND", "SDX": "SDA0", "SCX": "SCL0", "SDO": sdo}
    if csb:
        conn["CSB"] = csb
    conn.update(extra)
    return mk.mod(ref, "bmi270", conn)


def lsm(ref="U1", sa0="GND", cs: str | None = "3V3"):
    conn = {"VDD": "3V3", "GND": "GND", "SDA": "SDA0", "SCL": "SCL0", "SA0": sa0}
    if cs:
        conn["CS"] = cs
    return mk.mod(ref, "lsm6ds3trc", conn)


def vl6(ref="U1", ce=None, avdd="3V3", **kw):
    conn = {"AVDD": avdd, "AVSS": "GND", "SDA": "SDA0", "SCL": "SCL0"}
    if ce:
        conn["GPIO0"] = ce
    return mk.mod(ref, "vl6180x", conn, **kw)


def max101(vdd="1V8", vled="5V"):
    return mk.mod("U1", "max30101", {"VDD": vdd, "VLED+": vled, "GND": "GND", "SDA": "SDA0", "SCL": "SCL0"})


def drv(vcc="3V3"):
    return mk.mod("U1", "drv5055", {"VCC": vcc, "GND": "GND", "OUT": "HALL"})


# --- catalog -------------------------------------------------------------------------------------------------------
def test_nmotion_entries_load_with_their_classes():
    cat = modules.catalog()
    assert cat.problems == []
    want = {"icm20948": "A1", "bmi270": "A", "lsm6ds3trc": "A1", "vl6180x": "A1", "max30101": "A1", "drv5055": "A"}
    for mid, cls in want.items():
        e = cat.get(mid)
        assert e["_wp"] == "nmotion" and e["_class"] == cls and e["kind"] == "ic", mid
    assert cat.get("ICM-20948")["id"] == "icm20948" and cat.get("lsm6ds3tr-c")["id"] == "lsm6ds3trc"


def test_nmotion_values():
    cat = modules.catalog()
    i = cat.get("icm20948")
    assert i["supplies"]["VDDIO"]["max"]["value"] == 1.95 and i["supplies"]["VDDIO"]["abs_max"]["value"] == 2.5
    assert i["supplies"]["VDD"]["max"]["value"] == 3.6 and i["interfaces"][0]["addresses"]["value"] == ["0x68", "0x69"]
    b = cat.get("bmi270")
    assert b["supplies"]["VDDIO"]["min"]["value"] == 1.2 and b["interfaces"][0]["f_max_hz"]["value"] == 1_000_000
    assert b["interfaces"][0]["select"]["map"] == {"GND": "0x68", "VDDIO": "0x69"}
    s = cat.get("lsm6ds3trc")
    assert s["interfaces"][0]["addresses"]["value"] == ["0x6a", "0x6b"] and s["io"]["voh"]["rel_offset"] == -0.2
    v = cat.get("vl6180x")
    assert v["supplies"]["AVDD"]["max"]["value"] == 3.0 and v["interfaces"][0]["default"] == "0x29"
    assert [h["code"] for h in v["hazards"]] == ["laser"]
    m = cat.get("max30101")
    assert m["supplies"]["VDD"]["abs_max"]["value"] == 2.2 and m["interfaces"][0]["default"] == "0x57"
    d = cat.get("drv5055")
    assert d["supplies"]["VCC"]["abs_max"]["value"] == 7.0 and d["pins"][1]["signal"] == "analog_out"


# --- addresses -----------------------------------------------------------------------------------------------------
def test_icm20948_clashes_with_ds3231_at_0x68():
    parts = [icm(), mk.mod("U2", "ds3231", {"VCC": "3V3", "GND": "GND", "SDA": "SDA0", "SCL": "SCL0"})]
    f = one(mk.run(assignments=mk.i2c(), parts=parts, options=R18), "mod.address_conflict", "failed")
    assert f.severity == "caution" and "0x68" in f.message and "0x69" in f.message


def test_bmi270_clashes_with_mpu6050_unless_sdo_high():
    mpu = mk.mod("U2", "mpu6050", {"VDD": "3V3", "GND": "GND", "SDA": "SDA0", "SCL": "SCL0", "AD0": "GND"})
    r = mk.run(assignments=mk.i2c(), parts=[bmi(), mpu])
    assert one(r, "mod.address_conflict", "failed").severity == "caution"
    r = mk.run(assignments=mk.i2c(), parts=[bmi(sdo="3V3"), mpu])
    assert not mk.findings(r, "mod.address_conflict", "failed")


def test_two_lsm6ds3trc_need_different_sa0():
    r = mk.run(assignments=mk.i2c(), parts=[lsm("U1"), lsm("U2")])
    assert "0x6a" in one(r, "mod.address_conflict", "failed").message
    r = mk.run(assignments=mk.i2c(), parts=[lsm("U1"), lsm("U2", sa0="3V3")])
    assert not mk.findings(r, "mod.address_conflict", "failed")


def test_max30101_and_max30102_share_0x57():
    m2 = mk.mod("U2", "max30102", {"VDD": "1V8", "VLED+": "5V", "GND": "GND", "SDA": "SDA0", "SCL": "SCL0"})
    r = mk.run(assignments=mk.i2c(), parts=[max101(), m2], options=R18)
    assert "0x57" in one(r, "mod.address_conflict", "failed").message


# --- supply and levels ---------------------------------------------------------------------------------------------
def test_icm20948_vddio_on_3v3_is_danger():
    f = one(mk.run(assignments=mk.i2c(), parts=[icm(vddio="3V3", ncs="3V3")]), "mod.supply_range", "failed")
    assert f.severity == "danger" and "VDDIO" in f.message and "2.50 V" in f.message


def test_icm20948_on_1v8_io_with_3v3_pullups_is_danger():
    pull = [{"ref": "R1", "kind": "resistor", "value": "4.7k", "conn": {"1": "SDA0", "2": "3V3"}},
            {"ref": "R2", "kind": "resistor", "value": "4.7k", "conn": {"1": "SCL0", "2": "3V3"}}]
    r = mk.run(assignments=mk.i2c(), parts=[icm(), *pull], options=R18)
    assert not mk.findings(r, "mod.supply_range", "failed")
    assert any(f.severity == "danger" for f in mk.findings(r, "mod.level_in", "failed"))


def test_vl6180x_on_3v3_is_outside_the_operating_range():
    f = one(mk.run(assignments=mk.i2c(), parts=[vl6()]), "mod.supply_range", "failed")
    assert f.severity == "caution" and "3.00 V" in f.message
    r = mk.run(assignments=mk.i2c(), parts=[vl6(avdd="2V8")], options={"rails": {"2V8": 2.8}})
    assert not mk.findings(r, "mod.supply_range", "failed")


def test_vl6180x_laser_hazard():
    f = one(mk.run(assignments=mk.i2c(), parts=[vl6(avdd="2V8")], options={"rails": {"2V8": 2.8}}), "mod.hazard")
    assert f.severity == "danger" and "laser" in f.message


def test_max30101_vdd_on_3v3_is_danger():
    f = one(mk.run(assignments=mk.i2c(), parts=[max101(vdd="3V3")]), "mod.supply_range", "failed")
    assert f.severity == "danger" and "2.20 V" in f.message


def test_drv5055_on_5v_into_the_adc_is_flagged():
    r = mk.run(assignments=[mk.assign("adc", 4, "HALL")], parts=[drv("5V")])
    assert one(r, "mod.level_out", "failed").severity == "caution"
    r = mk.run(assignments=[mk.assign("adc", 4, "HALL")], parts=[drv("3V3")])
    assert not mk.findings(r, "mod.level_out", "failed")


# --- mod.nmotion.cs_high_i2c ---------------------------------------------------------------------------------------
def test_cs_on_vddio_passes():
    r = mk.run(assignments=mk.i2c(), parts=[bmi(), lsm("U2", sa0="3V3"), icm("U3", ad0="1V8")], options=R18)
    assert {f.status for f in mk.findings(r, CS)} == {"passed"} and len(mk.findings(r, CS)) == 3


def test_lsm6_cs_on_gnd_is_caution():
    f = one(mk.run(assignments=mk.i2c(), parts=[lsm(cs="GND")]), CS, "failed")
    assert f.severity == "caution" and "SPI" in f.message and f.source_ids == ["mod-nmotion-lsm6ds3trc-ds"]


def test_cs_open_bmi270_info_icm_caution():
    r = mk.run(assignments=mk.i2c(), parts=[bmi(csb=None), icm("U2", ad0="1V8", ncs=None)], options=R18)
    sev = {f.refs[0]: f.severity for f in mk.findings(r, CS, "failed")}
    assert sev == {"U1": "info", "U2": "caution"}


def test_cs_on_gpio_bmi270_caution_lsm6_info():
    a = [*mk.i2c(), mk.assign("out", 4, "CS1"), mk.assign("out", 5, "CS2")]
    r = mk.run(assignments=a, parts=[bmi(csb="CS1"), lsm("U2", cs="CS2")])
    fs = {f.refs[0]: f for f in mk.findings(r, CS, "failed")}
    assert fs["U1"].severity == "caution" and "SPI" in fs["U1"].message
    assert fs["U2"].severity == "info"


def test_cs_rule_skips_parts_off_the_i2c_bus_and_unknown_io():
    assert not mk.findings(mk.run(parts=[lsm()]), CS)
    f = one(mk.run(assignments=mk.i2c(), parts=[icm(vddio="VIO", ncs="NETX")]), CS)
    assert f.status == "not_checked"


# --- mod.nmotion.vl6180x_ce ----------------------------------------------------------------------------------------
def test_vl6180x_and_vl53_without_enable_lines_fail():
    v53 = mk.mod("U2", "vl53l0x", {"AVDD": "3V3", "GND": "GND", "SDA": "SDA0", "SCL": "SCL0"})
    r = mk.run(assignments=mk.i2c(), parts=[vl6(ce="3V3"), v53])
    f = one(r, CE, "failed")
    assert f.severity == "caution" and "0x29" in f.message and "U1 GPIO0 on 3V3" in f.message
    assert f.source_ids == ["mod-nmotion-vl6180x-ds", "mod-prox-vl53l0x-ds"]
    assert not mk.findings(r, "mod.prox.vl53_xshut")  # only one VL53: the prox rule has no group


def test_vl6180x_distinct_addresses_without_enable_lines_are_danger():
    r = mk.run(assignments=mk.i2c(), parts=[vl6("U1", address="0x30"), vl6("U2", address="0x31")])
    assert one(r, CE, "failed").severity == "danger"


def test_vl6180x_with_own_ce_gpios_passes_and_one_without_is_allowed():
    a = [*mk.i2c(), mk.assign("out", 4, "CE1"), mk.assign("out", 5, "CE2")]
    r = mk.run(assignments=a, parts=[vl6("U1", ce="CE1", address="0x30"), vl6("U2", ce="CE2")])
    assert one(r, CE).status == "passed"
    r = mk.run(assignments=a[:3], parts=[vl6("U1", ce="CE1"), vl6("U2")])
    f = one(r, CE)
    assert f.status == "passed" and "U2 has no own GPIO0 GPIO" in f.message


def test_single_vl6180x_or_only_vl53_gives_no_ce_finding():
    assert not mk.findings(mk.run(assignments=mk.i2c(), parts=[vl6()]), CE)
    v = [mk.mod(r, "vl53l0x", {"AVDD": "3V3", "GND": "GND", "SDA": "SDA0", "SCL": "SCL0"}) for r in ("U1", "U2")]
    assert not mk.findings(mk.run(assignments=mk.i2c(), parts=v), CE)


# --- mod.nmotion.max30101_vled -------------------------------------------------------------------------------------
def test_max30101_vled_ranges():
    f = one(mk.run(assignments=mk.i2c(), parts=[max101(vled="3V3")], options=R18), VLED, "failed")
    assert f.severity == "info" and "green" in f.message
    assert one(mk.run(assignments=mk.i2c(), parts=[max101()], options=R18), VLED).status == "passed"
    r = mk.run(assignments=mk.i2c(), parts=[max101(vled="V52")], options={"rails": {"1V8": 1.8, "V52": 5.2}})
    assert "green LED only" in one(r, VLED, "failed").message


def test_max30101_vled_unknown_or_outside_range():
    assert one(mk.run(assignments=mk.i2c(), parts=[max101(vled="VX")], options=R18), VLED).status == "not_checked"
    r = mk.run(assignments=mk.i2c(), parts=[max101(vled="V6")], options={"rails": {"1V8": 1.8, "V6": 5.8}})
    assert not mk.findings(r, VLED) and mk.findings(r, "mod.supply_range", "failed")


# --- mod.nmotion.drv5055_vcc ---------------------------------------------------------------------------------------
def test_drv5055_vcc_gap_and_ranges():
    a = [mk.assign("adc", 4, "HALL")]
    f = one(mk.run(assignments=a, parts=[drv("V4")], options={"rails": {"V4": 4.0}}), VCC, "failed")
    assert f.severity == "caution" and "3.63 V" in f.message and "4.50 V" in f.message
    assert one(mk.run(assignments=a, parts=[drv("3V3")]), VCC).status == "passed"
    assert one(mk.run(assignments=a, parts=[drv("5V")]), VCC).status == "passed"
    assert one(mk.run(assignments=a, parts=[drv("VX")]), VCC).status == "not_checked"
    r = mk.run(assignments=a, parts=[drv("V25")], options={"rails": {"V25": 2.5}})
    assert not mk.findings(r, VCC) and mk.findings(r, "mod.supply_range", "failed")


# --- mod.nmotion.bmi270_aux_gnd ------------------------------------------------------------------------------------
def test_bmi270_aux_pins_on_gnd():
    f = one(mk.run(assignments=mk.i2c(), parts=[bmi(ASDX="GND", ASCX="GND")]), AUX, "failed")
    assert f.severity == "caution" and "ASDX, ASCX" in f.message
    assert one(mk.run(assignments=mk.i2c(), parts=[bmi(ASDX="3V3")]), AUX).status == "passed"


# --- end to end ----------------------------------------------------------------------------------------------------
def test_pins_check_end_to_end_reports_icm_vddio():
    r = pins.check("esp32s3", mk.i2c(), parts=[icm(vddio="3V3", ncs="3V3")], options={})
    codes = {w["code"] for w in r["warnings"]}
    assert "mod_supply_range" in codes


def test_corrected_current_values():
    cat = modules.catalog()
    vl = cat.get("vl6180x")["current"]["peak"]
    assert (vl["value"], vl["page"]) == (0.038, 36)  # AVDD + AVDD_VCSEL from one source (Table 15, note 1)
    drv = cat.get("drv5055")["current"]
    assert (drv["typ"]["value"], drv["max"]["value"]) == (0.003, 0.005) and "5.0 V" in drv["max"]["conditions"]
    for mid, typ in (("bmi270", 0.00097), ("lsm6ds3trc", 0.0009)):
        cur = cat.get(mid)["current"]
        assert "max" not in cur and cur["typ"]["value"] == typ, mid  # typical values only: no invented maximum
