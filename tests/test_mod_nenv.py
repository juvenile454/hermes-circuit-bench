"""Module family nenv: catalog entries BMP388, BMP390, SHTC3, TMP117, ENS160, SEN55 and
the rules of modrules/nenv.py. The generic checks (structure, evidence ⊂ excerpt, excerpt ↔ pinned PDF) are the
generic module data tests; here: one synthetic project per part with the expected address, supply and level findings of the real rules.
"""
from __future__ import annotations

import excerpts as ex
import pytest

import modkit as k
from circuit_bench.bench_core import modcheck, modules
from circuit_bench.bench_core.modrules import nenv

IDS = ("bmp388", "bmp390", "shtc3", "tmp117", "ens160", "sen55")


@pytest.fixture(scope="module")
def cat():
    modules.clear_cache()
    c = modules.catalog()
    assert c.problems == []
    return c


def _bosch(ref, mid, sdo="VSS", vdd="3V3", **kw):
    conn = {"SDI": "SDA0", "SCK": "SCL0", "VDD": vdd, "VSS": "GND"}
    if sdo is not None:
        conn["SDO"] = "GND" if sdo == "VSS" else sdo
    return k.mod(ref, mid, conn, **kw)


def _bme280(ref="U9", sdo="GND"):
    return k.mod(ref, "bme280", {"SDI": "SDA0", "SCK": "SCL0", "SDO": sdo, "VDD": "3V3", "GND": "GND"})


def _shtc3(ref, vdd="3V3"):
    return k.mod(ref, "shtc3", {"SDA": "SDA0", "SCL": "SCL0", "VDD": vdd, "VSS": "GND"})


def _tmp117(ref, add0="GND", vdd="3V3"):
    conn = {"SDA": "SDA0", "SCL": "SCL0", "V+": vdd, "GND": "GND"}
    if add0 is not None:
        conn["ADD0"] = add0
    return k.mod(ref, "tmp117", conn)


def _ens160(ref, vdd="1V8", vio="3V3", addr="GND"):
    return k.mod(ref, "ens160", {"SDA": "SDA0", "SCL": "SCL0", "VDD": vdd, "VDDIO": vio, "VSS": "GND", "ADDR": addr})


def _sen55(ref, vdd="5V", **extra):
    return k.mod(ref, "sen55", {"SDA": "SDA0", "SCL": "SCL0", "VDD": vdd, "GND": "GND", **extra})


def _ctx(*parts, options=None):
    return modcheck.build_ctx(chip="esp32s3", assignments=k.i2c(), parts=list(parts), options=options or {},
                              devkit=None, catalog=None, electrical=None)


def _run(*parts, **kw):
    return k.run(assignments=k.i2c(), parts=list(parts), options=kw.pop("options", {"rails": {"1V8": 1.8}}), **kw)


def _supply(report):
    return [(f.status, f.severity, tuple(f.refs)) for f in k.findings(report, "mod.supply_range")]


def _conflicts(report):
    return [tuple(f.refs) for f in k.findings(report, "mod.address_conflict", "failed")]


# --- catalog ---------------------------------------------------------------------------------------------------------
def test_all_parts_are_in_the_catalog(cat):
    for mid in IDS:
        e = cat.get(mid)
        assert e["_wp"] == "nenv" and e["_class"] == "A", mid
        assert e["source_ids"] == [f"mod-nenv-{mid}-ds"], mid
    assert cat.resolve_id("SEN54") == "sen55" and cat.resolve_id("gy-bmp390") == "bmp390"


@pytest.mark.parametrize("mid,addrs", [("bmp388", ["0x76", "0x77"]), ("bmp390", ["0x76", "0x77"]),
                                       ("shtc3", ["0x70"]), ("tmp117", ["0x48", "0x49", "0x4a", "0x4b"]),
                                       ("ens160", ["0x52", "0x53"]), ("sen55", ["0x69"])])
def test_addresses(cat, mid, addrs):
    assert modcheck.addresses(modcheck.i2c_iface(cat.get(mid))) == addrs


def test_key_datasheet_values(cat):
    assert cat.get("bmp388")["supplies"]["VDD"]["abs_max"]["value"] == pytest.approx(3.8)
    assert cat.get("bmp390")["supplies"]["VDD"]["abs_max"]["value"] == pytest.approx(3.6)  # no headroom above 3.6 V
    assert cat.get("ens160")["supplies"]["VDD"]["max"]["value"] == pytest.approx(1.98)
    assert cat.get("ens160")["current"]["peak"]["value"] == pytest.approx(0.079)
    sen = cat.get("sen55")
    assert (sen["supplies"]["VDD"]["min"]["value"], sen["supplies"]["VDD"]["max"]["value"]) == (4.5, 5.5)
    assert sen["current"]["peak"]["value"] == pytest.approx(0.11)
    assert sen["io"]["vih"]["value"] == pytest.approx(2.31)  # absolute: 3.3 V I²C levels on a 5 V module
    assert modcheck.i2c_iface(sen)["f_max_hz"]["value"] == 100000
    assert cat.get("tmp117")["io"]["v_in_max"]["value"] == pytest.approx(5.5)


# --- one project per part --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mid", ["bmp388", "bmp390"])
def test_bmp3_project(mid):
    assert _conflicts(_run(_bosch("U1", mid), _bme280())) == [("U1", "U9")]  # both at 0x76
    assert _conflicts(_run(_bosch("U1", mid, sdo="VDDIO"), _bme280())) == []
    ctx = _ctx(_bosch("U1", mid, sdo="VDDIO"))
    u1 = ctx.instance("U1")
    assert (u1.address, u1.address_from) == ("0x77", "select")
    assert ctx.level(u1, "vih") == pytest.approx(0.7 * 3.3) and ctx.level(u1, "v_in_max") == pytest.approx(3.6)
    assert set(_supply(_run(_bosch("U1", mid)))) == {("passed", None, ("U1",))}  # VDD and VDDIO
    assert _supply(_run(_bosch("U1", mid, vdd="5V"))) == [("failed", "danger", ("U1",))]
    r = _run(_bosch("U1", mid, sdo=None))
    assert [f.severity for f in k.findings(r, "mod.address_select", "failed")] == ["caution"]


def test_shtc3_project():
    tca = k.mod("U2", "tca9548a", {"SDA": "SDA0", "SCL": "SCL0", "VCC": "3V3", "GND": "GND", "A0": "GND",
                                   "A1": "GND", "A2": "GND"})
    assert _conflicts(_run(_shtc3("U1"), tca)) == [("U1", "U2")]  # 0x70 fixed vs TCA9548A at A2..A0 low
    pca = k.mod("U3", "pca9685", {"SDA": "SDA0", "SCL": "SCL0", "VDD": "3V3", "VSS": "GND"})
    r = _run(_shtc3("U1"), pca)
    assert [f.severity for f in k.findings(r, "mod.address_reserved", "failed")] == ["caution"]  # All-Call 0x70
    ctx = _ctx(_shtc3("U1"))
    assert ctx.level(ctx.instance("U1"), "vil") == pytest.approx(0.42 * 3.3)
    assert _supply(_run(_shtc3("U1", vdd="5V"))) == [("failed", "danger", ("U1",))]  # abs max 4 V


def test_tmp117_project():
    ads = k.mod("U2", "ads1115", {"SDA": "SDA0", "SCL": "SCL0", "VDD": "3V3", "GND": "GND", "ADDR": "GND"})
    assert _conflicts(_run(_tmp117("U1"), ads)) == [("U1", "U2")]  # both 0x48
    for add0, addr in (("3V3", "0x49"), ("SDA0", "0x4a"), ("SCL0", "0x4b")):
        u1 = _ctx(_tmp117("U1", add0=add0)).instance("U1")
        assert (u1.address, u1.address_from) == (addr, "select"), add0
    assert _conflicts(_run(_tmp117("U1", add0="SCL0"), ads)) == []
    r = _run(_tmp117("U1", add0=None))
    assert [f.severity for f in k.findings(r, "mod.address_select", "failed")] == ["caution"]
    # 5 V is in range (1.8–5.5 V); the levels follow V+, so a 5 V TMP117 needs VIH 3.5 V from the 3.3 V ESP32
    assert _supply(_run(_tmp117("U1", vdd="5V"))) == [("passed", None, ("U1",))]
    ctx5 = _ctx(_tmp117("U1", vdd="5V"))
    assert ctx5.level(ctx5.instance("U1"), "vih") == pytest.approx(3.5)


def test_ens160_project():
    assert set(_supply(_run(_ens160("U1")))) == {("passed", None, ("U1",))}  # VDD 1.8 V and VDDIO 3.3 V
    bad = k.findings(_run(_ens160("U1", vdd="3V3")), "mod.supply_range", "failed")
    assert [(f.severity, f.refs) for f in bad] == [("danger", ["U1"])]  # VDD 3.3 V > abs max 1.98 V
    assert "1.98" in bad[0].message
    two = _run(_ens160("U1"), _ens160("U2"))
    assert _conflicts(two) == [("U1", "U2")]
    assert _conflicts(_run(_ens160("U1"), _ens160("U2", addr="3V3"))) == []


def test_ens160_sda_scl_rated_3v6_at_any_vddio(cat):
    """SDA/SCL (VIO1) are rated to 3.6 V, not VDDIO+0.3 V (VIO2: ADDR, INTn, CSn), p. 6."""
    vmax = cat.get("ens160")["io"]["v_in_max"]
    assert (vmax["value"], vmax["page"]) == (3.6, 6) and "rel_offset" not in vmax
    assert any("VDDIO+0.3" in n["text"] and n["verified"] for n in cat.get("ens160")["notes"])
    ens = k.mod("U1", "ens160", {"SDA": "SDA0", "SCL": "SCL0", "VDD": "1V8", "VDDIO": "1V8", "VSS": "GND",
                                 "ADDR": "GND"})
    pulls = [{"ref": f"R{i}", "kind": "resistor", "value": "4k7", "conn": {"1": n, "2": "3V3"}}
             for i, n in ((1, "SDA0"), (2, "SCL0"))]
    r = _run(ens, *pulls)
    assert [w["code"] for w in r.warnings if w["severity"] == "danger"] == []  # 3.3 V pull-ups at VDDIO 1.8 V
    ctx = _ctx(_ens160("U1"), options={"rails": {"1V8": 1.8}})
    u1 = ctx.instance("U1")
    assert ctx.level(u1, "vih") == pytest.approx(0.7 * 3.3)  # levels follow VDDIO, not the 1.8 V core
    rail = next(r for r in ctx.rail_sums if r["net"] == "1V8")
    assert rail["i_peak"] == pytest.approx(0.079)


def test_sen55_project():
    assert _supply(_run(_sen55("U1"))) == [("passed", None, ("U1",))]
    assert _supply(_run(_sen55("U1", vdd="3V3"))) == [("failed", "caution", ("U1",))]  # below 4.5 V
    mpu = k.mod("U2", "mpu6050", {"SDA": "SDA0", "SCL": "SCL0", "VDD": "3V3", "GND": "GND", "AD0": "3V3"})
    assert _conflicts(_run(_sen55("U1"), mpu)) == [("U1", "U2")]  # 0x69
    speed = k.findings(_run(_sen55("U1")), "mod.bus_speed", "failed")
    assert len(speed) == 1 and "100 kHz" in speed[0].message
    ctx = _ctx(_sen55("U1"))
    u1 = ctx.instance("U1")
    assert ctx.level(u1, "vih") == pytest.approx(2.31)  # 3.3 V ESP32 output high is enough
    assert u1.conn["SEL"] == "GND"  # default tie
    rail = next(r for r in ctx.rail_sums if r["net"] == "5V")
    assert rail["i_peak"] == pytest.approx(0.11)


# --- family rules ----------------------------------------------------------------------------------------------------
SEL, WARM = "mod.nenv.sen55_sel_gnd", "mod.nenv.ens160_warmup"


def test_sen55_sel_default_and_gnd_pass():
    for extra in ({}, {"SEL": "GND"}):
        fs = k.findings(_run(_sen55("U1", **extra), only=(SEL,)), SEL)
        assert [(f.status, f.refs) for f in fs] == [("passed", ["U1"])], extra


@pytest.mark.parametrize("sel", ["3V3", "GPIO5", "5V"])
def test_sen55_sel_not_on_gnd_is_a_caution(sel):
    r = _run(_sen55("U1", SEL=sel), only=(SEL,))
    (f,) = k.findings(r, SEL)
    assert (f.status, f.severity) == ("failed", "caution")
    assert f"on {sel}" in f.message and "p. 17" in f.message and f.source_ids == ["mod-nenv-sen55-ds"]
    assert "mod_nenv_sen55_sel_gnd" in k.codes(r)


def test_sen55_sel_without_gnd_is_not_checked():
    part = k.mod("U1", "sen55", {"SDA": "SDA0", "SCL": "SCL0", "VDD": "5V", "SEL": "GND"})
    (f,) = k.findings(_run(part, only=(SEL,)), SEL)
    assert f.status == "not_checked"


def test_ens160_warmup_hint():
    r = _run(_ens160("U1"), _sen55("U2"), only=(WARM,))
    fs = k.findings(r, WARM)
    assert [(f.status, f.severity, f.refs) for f in fs] == [("failed", "info", ["U1"])]
    assert "3 minutes" in fs[0].message and "1 hour" in fs[0].message and "p. 15" in fs[0].message


def test_rules_stay_quiet_without_their_parts():
    r = _run(_bosch("U1", "bmp388"), _shtc3("U2"), _tmp117("U3"), only=(SEL, WARM))
    assert k.findings(r) == []


@pytest.mark.parametrize("source_id", sorted(nenv.QUOTES))
def test_values_in_rule_code_are_quoted_in_the_excerpt(source_id):
    excerpt = next(e for e in ex.excerpts("mod-nenv-*.txt") if e.source_id == source_id)
    for page, quotes in nenv.QUOTES[source_id].items():
        lines = [line for seg in excerpt.page_segments(page) for line in seg]
        for q in quotes:
            assert any(q in line for line in lines), (source_id, page, q)
    assert nenv.SEL_PAGE in nenv.QUOTES["mod-nenv-sen55-ds"]
    assert nenv.WARMUP_PAGE in nenv.QUOTES["mod-nenv-ens160-ds"]
