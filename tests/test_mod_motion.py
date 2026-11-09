"""Module family motion: MPU-6050, ADXL345, LIS3DH, BNO055, QMC5883L, MAX30102, APDS-9960 against
the real catalog entries (data/modules/motion.json) plus the family rules in bench_core/modrules/motion.py.

Hard expectations only for mod.address_conflict, mod.supply_range and the mod.motion.* rules; the
synthetic 0x68 RTC comes from tests/mod_fixtures.py (tst_rtc).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from mod_fixtures import ESP, MODULES, SOURCES, FakeCatalog
from modkit import findings, i2c, mod, run

from circuit_bench.bench_core import modules, pins

ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((ROOT / "circuit_bench/data/modules/motion.json").read_text(encoding="utf-8"))
SRC = {s["id"]: s for s in json.loads((ROOT / "circuit_bench/data/sources/mod-motion.json").read_text(encoding="utf-8"))}
IDS = ["mpu6050", "adxl345", "lis3dh", "bno055", "qmc5883l", "max30102", "apds9960"]
RAILS = {"rails": {"1V8": 1.8, "2V5": 2.5}}
AC, SR = "mod.address_conflict", "mod.supply_range"
MAXR, ADXR, BNOR = "mod.motion.max30102_vdd_1v8", "mod.motion.adxl345_cs_high_i2c", "mod.motion.bno055_clock_stretch"


def cat() -> FakeCatalog:
    """Synthetic fixtures + the real motion entries, with their source classes."""
    return FakeCatalog(list(MODULES) + DATA["modules"], sources={**SOURCES, **SRC}, wp="motion")


def go(parts, *, catalog=None, options=RAILS, only=None, assignments=None):
    return run(catalog=catalog if catalog is not None else cat(), electrical=ESP,
               assignments=assignments if assignments is not None else i2c(), parts=parts, options=options,
               only=only)


def one(report, rule_id, status=None):
    fs = findings(report, rule_id, status)
    assert len(fs) == 1, [f.message for f in findings(report, rule_id)]
    return fs[0]


def worst(report, rule_id):
    """(status, severity) of the most severe finding of a rule; supply_range reports one finding per supply pin."""
    rank = {None: 0, "info": 1, "caution": 2, "danger": 3}
    fs = findings(report, rule_id)
    assert fs
    bad = [f for f in fs if f.status == "failed"]
    if not bad:
        return "passed", None
    f = max(bad, key=lambda x: rank[x.severity])
    return f.status, f.severity, " ".join(x.message for x in bad)


BUS = {"SDA": "SDA0", "SCL": "SCL0", "GND": "GND"}
BNO_BUS = {"COM0": "SDA0", "COM1": "SCL0", "GND": "GND"}


# --- data -----------------------------------------------------------------------------------------------------
def test_all_seven_parts_in_the_runtime_catalog_without_problems():
    c = modules.Catalog.from_dir()
    assert not [p for p in c.problems if "motion" in p]
    for mid in IDS:
        assert c.has(mid)
        e = c.get(mid)
        assert e["source_ids"] == [f"mod-motion-{mid}-ds"]
    assert c.resolve_id("gy-521") == "mpu6050"
    assert c.resolve_id("gy-271") == "qmc5883l"


def test_source_classes_and_hashes():
    manifest = json.loads((ROOT / "tests/corpus/mod-motion.json").read_text(encoding="utf-8"))
    by_sid = {f["source_id"]: f for f in manifest["files"]}
    assert set(by_sid) == set(SRC) == {f"mod-motion-{m}-ds" for m in IDS}
    for sid, s in SRC.items():
        assert s["class"] in ("A", "A1")  # MPU-6050: TDK copy via web.archive.org instead of a distributor copy
        assert by_sid[sid]["sha256"] in s["note"]
        if s["class"] == "A1":
            assert s["url"].startswith("https://web.archive.org/web/")
    assert "invensense.tdk.com" in SRC["mod-motion-mpu6050-ds"]["url"]


@pytest.mark.parametrize("mid, addrs", [("mpu6050", ["0x68", "0x69"]), ("adxl345", ["0x1d", "0x53"]),
                                        ("lis3dh", ["0x18", "0x19"]), ("bno055", ["0x28", "0x29"]),
                                        ("qmc5883l", ["0x0d"]), ("max30102", ["0x57"]), ("apds9960", ["0x39"])])
def test_addresses(mid, addrs):
    assert modules.addresses(modules.catalog().get(mid)) == addrs


# --- MPU-6050: address 0x68 against a synthetic RTC (DS3231-like) ---------------------------------------------------
def test_mpu6050_default_address_collides_with_a_0x68_rtc():
    r = go([mod("U1", "mpu6050", {**BUS, "VDD": "3V3", "AD0": "GND"}),
            mod("U2", "tst_rtc", {**BUS, "VCC": "5V"})], only=(AC,))
    f = one(r, AC, "failed")
    assert f.severity == "caution" and "0x68" in f.message
    assert "0x69 (AD0 to VLOGIC)" in f.message
    assert "mod-motion-mpu6050-ds" in f.source_ids


def test_mpu6050_ad0_high_resolves_the_conflict():
    r = go([mod("U1", "mpu6050", {**BUS, "VDD": "3V3", "AD0": "3V3"}),
            mod("U2", "tst_rtc", {**BUS, "VCC": "5V"})], only=(AC,))
    assert one(r, AC, "passed")
    inst = next(i for i in r.result["buses"][0]["segments"][0]["devices"] if i["ref"] == "U1")
    assert inst["address"] == "0x69"


def test_two_mpu6050_need_different_ad0():
    same = go([mod("U1", "mpu6050", {**BUS, "VDD": "3V3", "AD0": "GND"}),
               mod("U2", "mpu6050", {**BUS, "VDD": "3V3", "AD0": "GND"})], only=(AC,))
    assert one(same, AC, "failed").severity == "caution"
    split = go([mod("U1", "mpu6050", {**BUS, "VDD": "3V3", "AD0": "GND"}),
                mod("U2", "mpu6050", {**BUS, "VDD": "3V3", "AD0": "3V3"})], only=(AC,))
    assert one(split, AC, "passed")


def test_mpu6050_supply_5v_is_within_abs_max_but_above_range():
    _, sev, msg = worst(go([mod("U1", "mpu6050", {**BUS, "VDD": "5V", "AD0": "GND"})], only=(SR,)), SR)
    assert sev == "caution" and "3.46" in msg
    assert worst(go([mod("U1", "mpu6050", {**BUS, "VDD": "3V3", "AD0": "GND"})], only=(SR,)), SR) == ("passed", None)


# --- ADXL345 ----------------------------------------------------------------------------------------------------
def test_adxl345_supply_5v_exceeds_abs_max():
    _, sev, msg = worst(go([mod("U1", "adxl345", {**BUS, "VS": "5V", "CS": "5V", "SDO": "GND"})], only=(SR,)), SR)
    assert sev == "danger" and "3.9" in msg


def test_adxl345_alt_address_and_conflict_with_lis3dh_free():
    r = go([mod("U1", "adxl345", {**BUS, "VS": "3V3", "CS": "3V3", "SDO": "GND"}),
            mod("U2", "lis3dh", {**BUS, "VDD": "3V3", "CS": "3V3"})], only=(AC,))
    assert one(r, AC, "passed")
    addrs = {d["ref"]: d["address"] for d in r.result["buses"][0]["segments"][0]["devices"]}
    assert addrs == {"U1": "0x53", "U2": "0x19"}


def test_adxl345_cs_tied_to_vddio_passes():
    assert one(go([mod("U1", "adxl345", {**BUS, "VS": "3V3", "CS": "3V3", "SDO": "3V3"})], only=(ADXR,)),
               ADXR, "passed")
    # CS on the VDDIO pin's own net (VDDIO tied to VS = 3V3 by the data)
    assert one(go([mod("U1", "adxl345", {**BUS, "VS": "3V3", "CS": "VDDIO", "SDO": "GND"})], only=(ADXR,)),
               ADXR, "passed")


def test_adxl345_cs_open_or_low_is_a_caution():
    f = one(go([mod("U1", "adxl345", {**BUS, "VS": "3V3", "SDO": "GND"})], only=(ADXR,)), ADXR, "failed")
    assert f.severity == "caution" and "not connected" in f.message and "p. 14" in f.message
    f = one(go([mod("U1", "adxl345", {**BUS, "VS": "3V3", "CS": "GND", "SDO": "GND"})], only=(ADXR,)), ADXR,
            "failed")
    assert f.severity == "caution" and "SPI" in f.message
    assert f.source_ids == ["mod-motion-adxl345-ds"]


def test_adxl345_cs_on_a_gpio_is_info():
    asg = i2c() + [{"mode": "out", "pin": 10, "net": "ACC_CS"}]
    f = one(go([mod("U1", "adxl345", {**BUS, "VS": "3V3", "CS": "ACC_CS", "SDO": "GND"})], assignments=asg,
               only=(ADXR,)), ADXR, "failed")
    assert f.severity == "info" and "ACC_CS" in f.message


def test_adxl345_cs_on_a_signal_net_with_unknown_vddio_is_not_checked():
    f = one(go([mod("U1", "adxl345", {**BUS, "VS": "VBUS_X", "CS": "STRAP", "SDO": "GND"})], only=(ADXR,)),
            ADXR, "not_checked")
    assert "unknown" in f.message


def test_adxl345_rule_ignores_parts_off_the_i2c_bus():
    r = go([mod("U1", "adxl345", {"VS": "3V3", "GND": "GND"})], only=(ADXR,), assignments=[])
    assert findings(r, ADXR) == []


# --- LIS3DH -----------------------------------------------------------------------------------------------------
def test_lis3dh_sa0_open_uses_the_internal_pullup_default_and_clashes_with_a_synthetic_0x19():
    other = {"id": "tst_0x19", "title": "TST 0x19 device", "category": "sensor.motion", "manufacturer": "Test",
             "kind": "ic", "source_ids": ["tst-sensor-ds"],
             "pins": [{"name": "VCC", "signal": "supply"}, {"name": "GND", "signal": "gnd"},
                      {"name": "SDA", "signal": "i2c_sda"}, {"name": "SCL", "signal": "i2c_scl"}],
             "interfaces": [{"type": "i2c", "addresses": {"value": ["0x19"], "unit": "bit", "page": 1,
                                                          "evidence": "x"}, "default": "0x19"}]}
    c = FakeCatalog(list(MODULES) + DATA["modules"] + [other], sources={**SOURCES, **SRC})
    r = go([mod("U1", "lis3dh", {**BUS, "VDD": "3V3", "CS": "3V3"}), mod("U2", "tst_0x19", {**BUS, "VCC": "3V3"})],
           catalog=c, only=(AC,))
    f = one(r, AC, "failed")
    assert "0x19" in f.message and "0x18 (SDO to GND)" in f.message


def test_lis3dh_supply_5v_exceeds_abs_max_and_2v5_is_fine():
    _, sev, msg = worst(go([mod("U1", "lis3dh", {**BUS, "VDD": "5V", "CS": "5V"})], only=(SR,)), SR)
    assert sev == "danger" and "4.8" in msg
    assert worst(go([mod("U1", "lis3dh", {**BUS, "VDD": "2V5", "CS": "2V5"})], only=(SR,)), SR) == ("passed", None)


# --- BNO055 -----------------------------------------------------------------------------------------------------
def test_bno055_clock_stretch_hint_on_i2c():
    r = go([mod("U1", "bno055", {**BNO_BUS, "VDD": "3V3", "PS0": "GND", "PS1": "GND", "COM3": "GND"})],
           only=(BNOR,))
    f = one(r, BNOR, "failed")
    assert f.severity == "info" and "stretches SCL" in f.message and "p. 100" in f.message
    assert f.source_ids == ["mod-motion-bno055-ds"]


def test_bno055_no_hint_off_the_bus_or_without_the_datasheet_note():
    assert findings(go([mod("U1", "bno055", {"VDD": "3V3", "GND": "GND"})], assignments=[], only=(BNOR,)),
                    BNOR) == []
    stripped = [dict(m, notes=[n for n in m["notes"] if "clock stretching" not in n["text"]])
                if m["id"] == "bno055" else m for m in DATA["modules"]]
    c = FakeCatalog(list(MODULES) + stripped, sources={**SOURCES, **SRC})
    assert findings(go([mod("U1", "bno055", {**BNO_BUS, "VDD": "3V3"})], catalog=c, only=(BNOR,)), BNOR) == []


def test_bno055_address_select_and_5v_supply():
    r = go([mod("U1", "bno055", {**BNO_BUS, "VDD": "3V3", "COM3": "GND"}),
            mod("U2", "bno055", {**BNO_BUS, "VDD": "3V3", "COM3": "3V3"})], only=(AC,))
    assert one(r, AC, "passed")
    # COM3 open: internal pull-up -> default 0x29, clashes with a second one strapped high
    r = go([mod("U1", "bno055", {**BNO_BUS, "VDD": "3V3"}),
            mod("U2", "bno055", {**BNO_BUS, "VDD": "3V3", "COM3": "3V3"})], only=(AC,))
    assert "0x29" in one(r, AC, "failed").message
    _, sev, _ = worst(go([mod("U1", "bno055", {**BNO_BUS, "VDD": "5V"})], only=(SR,)), SR)
    assert sev == "danger"  # VDDIO tied to VDD: 5 V > 4.2 V (VDD) and > 3.6 V (VDDIO)


# --- QMC5883L ---------------------------------------------------------------------------------------------------
def test_qmc5883l_fixed_address_conflict_and_supply():
    r = go([mod("U1", "qmc5883l", {**BUS, "VDD": "3V3"}), mod("U2", "qmc5883l", {**BUS, "VDD": "3V3"})],
           only=(AC,))
    f = one(r, AC, "failed")
    assert "0x0d" in f.message and "mux" in f.message.lower()
    assert worst(go([mod("U1", "qmc5883l", {**BUS, "VDD": "5V"})], only=(SR,)), SR)[1] == "caution"  # abs max 5.4 V


# --- MAX30102 ---------------------------------------------------------------------------------------------------
def test_max30102_vdd_on_3v3_is_danger():
    r = go([mod("U1", "max30102", {**BUS, "VDD": "3V3", "VLED+": "3V3"})], only=(MAXR, SR))
    f = one(r, MAXR, "failed")
    assert f.severity == "danger" and "2.2" in f.message and "1.8 V" in f.message and "p. 2" in f.message
    assert f.source_ids == ["mod-motion-max30102-ds"]
    assert worst(r, SR)[1] == "danger"
    # one cause, one warning: the family rule supersedes mod.supply_range on the part
    assert f.supersedes == (SR,)
    assert [(w["code"], w["severity"]) for w in r.warnings] == [("mod_motion_max30102_vdd_1v8", "danger")]


def test_max30102_vdd_1v8_with_vled_3v3_passes():
    r = go([mod("U1", "max30102", {**BUS, "VDD": "1V8", "VLED+": "3V3"})], only=(MAXR, SR))
    assert one(r, MAXR, "passed")
    assert worst(r, SR) == ("passed", None)


def test_max30102_shared_vdd_and_vled_and_out_of_range():
    r = go([mod("U1", "max30102", {**BUS, "VDD": "1V8", "VLED+": "1V8"})], only=(MAXR,))
    assert one(r, MAXR, "failed").severity == "caution"
    r = go([mod("U1", "max30102", {**BUS, "VDD": "2V1", "VLED+": "3V3"})], options={"rails": {"2V1": 2.1}},
           only=(MAXR,))
    f = one(r, MAXR, "failed")
    assert f.severity == "caution" and "outside" in f.message


def test_max30102_vdd_unknown_is_not_checked():
    assert "not connected" in one(go([mod("U1", "max30102", BUS)], only=(MAXR,)), MAXR, "not_checked").message
    assert "unknown" in one(go([mod("U1", "max30102", {**BUS, "VDD": "VREG"})], only=(MAXR,)), MAXR,
                            "not_checked").message


def test_max30102_without_range_data_is_not_checked():
    stripped = [dict(m, supplies={"VLED+": m["supplies"]["VLED+"]}) if m["id"] == "max30102" else m
                for m in DATA["modules"]]
    c = FakeCatalog(list(MODULES) + stripped, sources={**SOURCES, **SRC})
    assert one(go([mod("U1", "max30102", {**BUS, "VDD": "3V3"})], catalog=c, only=(MAXR,)), MAXR, "not_checked")


# --- APDS-9960 --------------------------------------------------------------------------------------------------
def test_apds9960_on_5v_is_danger_and_fixed_address():
    _, sev, msg = worst(go([mod("U1", "apds9960", {**BUS, "VDD": "5V", "LEDA": "5V"})], only=(SR,)), SR)
    assert sev == "danger" and "3.8" in msg
    r = go([mod("U1", "apds9960", {**BUS, "VDD": "3V3", "LEDA": "3V3"}),
            mod("U2", "max30102", {**BUS, "VDD": "1V8", "VLED+": "3V3"}),
            mod("U3", "qmc5883l", {**BUS, "VDD": "3V3"}),
            mod("U4", "mpu6050", {**BUS, "VDD": "3V3", "AD0": "GND"}),
            mod("U5", "bno055", {**BNO_BUS, "VDD": "3V3", "COM3": "GND"}),
            mod("U6", "lis3dh", {**BUS, "VDD": "3V3", "CS": "3V3", "SDO": "GND"}),
            mod("U7", "adxl345", {**BUS, "VS": "3V3", "CS": "3V3", "SDO": "3V3"})], only=(AC,))
    p = one(r, AC, "passed")
    assert "7 device(s)" in p.message and "0x39" in p.message


# --- end to end through pins.check with the runtime catalog -------------------------------------------------------
def test_pins_check_end_to_end_max30102_on_3v3():
    res = pins.check("esp32s3", [{"role": "SDA", "mode": "i2c_sda", "pin": 8, "net": "SDA0"},
                                 {"role": "SCL", "mode": "i2c_scl", "pin": 9, "net": "SCL0"}],
                     parts=[{"ref": "U1", "kind": "ic", "value": "MAX30102", "module": "max30102",
                             "conn": {"SDA": "SDA0", "SCL": "SCL0", "VDD": "3V3", "VLED+": "3V3", "GND": "GND"}}],
                     options={})
    warns = res["result"]["warnings"] if "warnings" in res.get("result", {}) else res.get("warnings", [])
    codes = {w["code"]: w for w in warns}
    assert "mod_motion_max30102_vdd_1v8" in codes
    assert codes["mod_motion_max30102_vdd_1v8"]["severity"] == "danger"


def test_corrected_values():
    c = modules.catalog()
    apds = c.get("apds9960")["current"]
    assert apds["typ"]["value"] == 0.00079 and "max" not in apds  # proximity/gesture typ; no maximum for them
    qmc = c.get("qmc5883l")["current"]
    assert qmc["typ"]["value"] == 0.00085 and "max" not in qmc
    io = c.get("bno055")["io"]
    assert io["vih"]["conditions"] == io["vil"]["conditions"] == "VDDIO 2.7–3.6 V"


def test_bno055_levels_only_for_vddio_2v7_to_3v6():
    from circuit_bench.bench_core import modcheck
    from circuit_bench.bench_core.modrules import elec  # the level rules apply F.conditions (never interpolated)
    for vio, ok in (("3V3", True), ("1V8", False)):
        part = mod("U1", "bno055", {**BNO_BUS, "VDD": "3V3", "VDDIO": vio, "PS0": "GND", "PS1": "GND"})
        ctx = modcheck.build_ctx(chip="esp32s3", assignments=i2c(), parts=[part], options=RAILS, devkit=None,
                                 catalog=None, electrical=None)
        v, _, why = elec._level(ctx, ctx.instance("U1"), "vih")
        assert (v is not None) is ok, (vio, why)
