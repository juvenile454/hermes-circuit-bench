"""Module family rtc: real catalog entries DS3231, DS1307, PCF8563, AT24C32, AT24C256 and the family
rules in bench_core/modrules/rtc.py. Every project is synthetic; values come from data/modules/rtc.json."""
from __future__ import annotations

import json
from pathlib import Path

import modkit as mk
import mod_fixtures as fx
import pytest

from circuit_bench.bench_core import modcheck, electrical, modules, pins

ROOT = Path(__file__).resolve().parent.parent
RTC = json.loads((ROOT / "circuit_bench" / "data" / "modules" / "rtc.json").read_text(encoding="utf-8"))["modules"]
RTC_SOURCES = {s["id"]: s for s in json.loads((ROOT / "circuit_bench" / "data" / "sources" / "mod-rtc.json")
                                               .read_text(encoding="utf-8"))}
ESP = electrical.get("esp32s3")
BUS = {"SDA": "SDA0", "SCL": "SCL0", "GND": "GND"}


def conn(vcc="3V3", pin="VCC", **extra):
    return {**BUS, pin: vcc, **extra}


def run(*parts, catalog=None, options=None, only=None):
    kw = {"only": only} if only else {}
    return mk.run(catalog=catalog, electrical=ESP, assignments=mk.i2c(), parts=list(parts), options=options, **kw)


def addresses(rep):
    return {d["ref"]: d["address"] for b in rep.result["buses"] for s in b["segments"] for d in s["devices"]}


def one(rep, rule_id, ref=None, status=None):
    fs = [f for f in mk.findings(rep, rule_id, status) if ref is None or ref in f.refs]
    assert len(fs) == 1, fs
    return fs[0]


# --- catalog -----------------------------------------------------------------------------------------------------
def test_catalog_has_the_five_parts_without_problems():
    cat = modules.Catalog.from_dir()
    assert cat.problems == []
    rows = {r["id"]: r for r in cat.search(limit=200)["items"]}
    assert {k: (rows[k]["category"], rows[k]["class"]) for k in ("ds3231", "ds1307", "pcf8563", "at24c32", "at24c256")} == {
        "ds3231": ("rtc", "A1"), "ds1307": ("rtc", "A1"), "pcf8563": ("rtc", "A"),
        "at24c32": ("memory", "A"), "at24c256": ("memory", "A")}
    assert rows["ds1307"]["supply"] == "4.5–5.5 V"
    assert rows["at24c32"]["addresses"] == [f"0x{a:02x}" for a in range(0x50, 0x58)]
    zs = cat.get("ds3231", "zs042")
    assert zs["kind"] == "module" and all(n["verified"] is False for n in zs["notes"][:3])


def test_a1_sources_point_at_wayback_copies_of_analog_com():
    for sid in ("mod-rtc-ds3231-ds", "mod-rtc-ds1307-ds"):
        s = RTC_SOURCES[sid]
        assert s["class"] == "A1"
        assert s["url"].startswith("https://web.archive.org/web/") and "id_/https://www.analog.com/" in s["url"]
    assert RTC_SOURCES["mod-rtc-pcf8563-ds"]["url"].startswith("https://cache.nxp.com/")


# --- DS3231 ------------------------------------------------------------------------------------------------------
def test_ds3231_at_3v3_is_clean():
    rep = run(mk.mod("U1", "ds3231", conn("3V3")))
    assert addresses(rep) == {"U1": "0x68"}
    assert one(rep, "mod.supply_range").status == "passed"
    assert one(rep, "mod.rtc.ds3231_vih").status == "passed"
    assert mk.findings(rep, "mod.rtc.rtc_module_charger") == []
    assert rep.result["buses"][0]["f_max_hz"] == 400000


def test_ds3231_at_5v_misses_vih_on_a_3v3_bus():
    rep = run(mk.mod("U1", "ds3231", conn("5V")))
    f = one(rep, "mod.rtc.ds3231_vih")
    assert (f.status, f.severity) == ("failed", "caution")
    assert "3.50 V" in f.message and "3.30 V" in f.message
    assert f.source_ids == ["mod-rtc-ds3231-ds"]
    assert "mod_rtc_ds3231_vih" in mk.codes(rep)


def test_ds3231_vih_passes_with_5v_pullups_or_a_level_shifter():
    rep = run(mk.mod("U1", "ds3231", conn("5V"), facts={"pullups_to": "5V"}),
              mk.mod("U2", "ds3231", {"SDA": "SDA1", "SCL": "SCL1", "GND": "GND", "VCC": "5V"},
                     facts={"level_shifter": True}))
    assert one(rep, "mod.rtc.ds3231_vih", "U1").status == "passed"
    assert one(rep, "mod.rtc.ds3231_vih", "U2").status == "passed"


def test_ds3231_vcc_above_abs_max_is_danger():
    rep = run(mk.mod("U1", "ds3231", conn("V7")), options={"rails": {"V7": 7.0}})
    f = one(rep, "mod.supply_range")
    assert (f.status, f.severity) == ("failed", "danger") and "6.00 V" in f.message


def test_zs042_variant_gets_the_charger_hint_as_info():
    rep = run(mk.mod("U1", "ds3231", conn("3V3"), variant="zs042"))
    f = one(rep, "mod.rtc.rtc_module_charger")
    assert (f.status, f.severity) == ("failed", "info")
    assert "unverified" in f.message.lower() and f.source_ids == ["mod-rtc-ds3231-ds"]
    assert mk.check_of(rep, "mod.rtc.rtc_module_charger")["status"] == "not_checked"  # info only, never a failure


def test_zs042_at_5v_with_unknown_board_pullups_leaves_the_voltage_to_level_out():
    # ZS-042 boards carry pull-ups to VCC (unconfirmed): the bus is not "3.3 V", the rule must not claim it (p03)
    rep = run(mk.mod("U1", "ds3231", conn("5V"), variant="zs042"))
    f = one(rep, "mod.rtc.ds3231_vih")
    assert (f.status, f.severity) == ("not_checked", None)
    assert "board pull-ups" in f.message and "3.30 V" not in f.message
    assert "mod_rtc_ds3231_vih" not in mk.codes(rep)
    assert {g.severity for g in mk.findings(rep, "mod.level_out", "failed")} == {"caution"}


def test_zs042_at_5v_on_a_declared_3v3_bus_is_caution_with_breakout_text():
    rep = run(mk.mod("U1", "ds3231", conn("5V"), variant="zs042", facts={"pullups_to": "3V3"}))
    f = one(rep, "mod.rtc.ds3231_vih")
    assert (f.status, f.severity) == ("failed", "caution") and "Breakout board" in f.message
    assert "3.30 V" in f.message and f.supersedes == ("mod.level_out",)


def _pullups(to, sda="SDA0", scl="SCL0"):
    return [{"ref": "RSDA", "kind": "resistor", "value": "4k7", "conn": {"1": sda, "2": to}},
            {"ref": "RSCL", "kind": "resistor", "value": "4k7", "conn": {"1": scl, "2": to}}]


def test_ds3231_vih_uses_the_real_pullup_resistors():
    rep = run(mk.mod("U1", "ds3231", conn("5V")), *_pullups("3V3"))
    f = one(rep, "mod.rtc.ds3231_vih")
    assert (f.status, f.severity) == ("failed", "caution")
    assert "3.30 V" in f.message and "RSDA to 3V3" in f.message
    # 5 V pull-ups meet VIH; the 5 V on the ESP pins stays a danger of mod.level_out (a pass never lowers it)
    rep = run(mk.mod("U1", "ds3231", conn("5V")), *_pullups("5V"))
    assert one(rep, "mod.rtc.ds3231_vih").status == "passed"
    assert {g.severity for g in mk.findings(rep, "mod.level_out", "failed")} == {"danger"}
    assert "mod_level_out" in mk.codes(rep)


# --- data corrections ---------------------------------------------------------------------------------------------
def _entry(mid):
    return next(m for m in RTC if m["id"] == mid)


def test_ds3231_current_is_the_worst_case_at_5v5():
    cur = _entry("ds3231")["current"]
    assert (cur["max"]["value"], cur["peak"]["value"], cur["sleep"]["value"]) == (0.0003, 0.00065, 0.00017)
    assert all("VCC 5.5 V" in cur[k]["conditions"] for k in ("max", "peak", "sleep"))


@pytest.mark.parametrize(("mid", "vmax", "page"), [("ds3231", 6.0, 2), ("ds1307", 7.0, 2), ("pcf8563", 6.5, 30),
                                                   ("at24c32", 7.0, 9), ("at24c256", 7.0, 2)])
def test_v_in_max_is_the_absolute_maximum_rating(mid, vmax, page):
    f = _entry(mid)["io"]["v_in_max"]
    assert (f["value"], f["page"]) == (vmax, page)
    assert "absolute maximum" in f["conditions"] or "limiting value" in f["conditions"]


def test_crystal_pins_of_the_bare_rtc_chips():
    pins = {m: {p["name"]: p for p in _entry(m)["pins"]} for m in ("ds1307", "pcf8563")}
    assert {"X1", "X2"} <= set(pins["ds1307"]) and {"OSCI", "OSCO"} <= set(pins["pcf8563"])
    assert "32.768 kHz crystal" in pins["ds1307"]["X1"]["note"]
    note = next(n for n in _entry("pcf8563")["notes"] if "OSCI/OSCO" in n["text"])
    assert note["verified"] is True and note["page"] == 3
    # an unwired crystal pin is not reported as a floating input
    rep = run(mk.mod("U1", "ds1307", conn("5V")))
    assert not [f for f in mk.findings(rep, "mod.unconnected", "failed") if "X1" in f.message or "X2" in f.message]


def test_at24c256_clock_condition_names_the_datasheet_columns():
    f = _entry("at24c256")["interfaces"][0]["f_max_hz"]
    assert f["conditions"].startswith("1 MHz in the VCC 2.5 V, 5.0 V column") and "2.7" not in f["conditions"]


# --- DS1307 ------------------------------------------------------------------------------------------------------
def test_ds1307_at_3v3_fails_with_source():
    rep = run(mk.mod("U1", "ds1307", conn("3V3")))
    f = one(rep, "mod.rtc.ds1307_vcc_5v")
    assert (f.status, f.severity) == ("failed", "caution")
    assert "4.50 V–5.50 V" in f.message and "1.25 × VBAT" in f.message
    assert f.source_ids == ["mod-rtc-ds1307-ds"]
    assert one(rep, "mod.supply_range").severity == "caution"


def test_ds1307_at_5v_passes_and_limits_the_bus_to_100k():
    rep = run(mk.mod("U1", "ds1307", conn("5V")))
    assert one(rep, "mod.rtc.ds1307_vcc_5v").status == "passed"
    assert one(rep, "mod.supply_range").status == "passed"
    assert rep.result["buses"][0]["f_max_hz"] == 100000
    assert addresses(rep) == {"U1": "0x68"}


def test_ds1307_unknown_vcc_is_not_checked():
    rep = run(mk.mod("U1", "ds1307", conn("VX")))
    assert one(rep, "mod.rtc.ds1307_vcc_5v").status == "not_checked"


def test_ds3231_and_ds1307_collide_at_0x68():
    rep = run(mk.mod("U1", "ds3231", conn("3V3")), mk.mod("U2", "ds1307", conn("5V")))
    f = one(rep, "mod.address_conflict")
    assert f.status == "failed" and "0x68" in f.message and set(f.refs) == {"U1", "U2"}


def test_ds3231_collides_with_a_0x68_imu():
    imu = next(m for m in fx.MODULES if m["id"] == "tst_imu")
    cat = fx.FakeCatalog(RTC + [imu], sources={**RTC_SOURCES, **fx.SOURCES}, wp="rtc")
    rep = run(mk.mod("U1", "ds3231", conn("3V3")), mk.mod("U2", "tst_imu", {**BUS, "VDD": "3V3"}), catalog=cat)
    assert "0x68" in one(rep, "mod.address_conflict").message
    rep = run(mk.mod("U1", "ds3231", conn("3V3")), mk.mod("U2", "tst_imu", {**BUS, "VDD": "3V3", "AD0": "VDD"}),
              catalog=cat)
    assert addresses(rep) == {"U1": "0x68", "U2": "0x69"}
    assert [f for f in mk.findings(rep, "mod.address_conflict") if f.status == "failed"] == []


# --- PCF8563 -----------------------------------------------------------------------------------------------------
def test_pcf8563_address_and_supply():
    rep = run(mk.mod("U1", "pcf8563", conn("3V3", pin="VDD")))
    assert addresses(rep) == {"U1": "0x51"}
    assert one(rep, "mod.supply_range").status == "passed"
    rep = run(mk.mod("U1", "pcf8563", {**BUS, "VSS": "GND", "VDD": "V7"}), options={"rails": {"V7": 7.0}})
    f = one(rep, "mod.supply_range")
    assert f.severity == "danger" and "6.50 V" in f.message


# --- AT24C32 / AT24C256 ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("part", ["at24c32", "at24c256"])
@pytest.mark.parametrize("a2,a1,a0,addr", [
    (None, None, None, "0x50"),  # open: internal pull-down, tie GND
    ("GND", "GND", "GND", "0x50"),
    ("GND", "GND", "VCC", "0x51"),
    ("VCC", "GND", "GND", "0x54"),
    ("3V3", "3V3", "3V3", "0x57"),  # rail with VCC's voltage
])
def test_eeprom_address_from_a2_a1_a0(part, a2, a1, a0, addr):
    c = conn("3V3", **{k: v for k, v in (("A2", a2), ("A1", a1), ("A0", a0)) if v})
    assert addresses(run(mk.mod("U1", part, c))) == {"U1": addr}


def test_two_eeproms_on_default_address_collide_and_select_pins_fix_it():
    rep = run(mk.mod("U1", "at24c32", conn("3V3")), mk.mod("U2", "at24c256", conn("3V3")))
    assert "0x50" in one(rep, "mod.address_conflict").message
    rep = run(mk.mod("U1", "at24c32", conn("3V3")), mk.mod("U2", "at24c256", conn("3V3", A2="VCC")))
    assert [f for f in mk.findings(rep, "mod.address_conflict") if f.status == "failed"] == []


def test_eeprom_with_a0_high_collides_with_pcf8563():
    rep = run(mk.mod("U1", "pcf8563", conn("3V3", pin="VDD")), mk.mod("U2", "at24c256", conn("3V3", A0="VCC")))
    assert "0x51" in one(rep, "mod.address_conflict").message


def test_zs042_eeprom_at_0x57_sits_next_to_the_ds3231():
    rep = run(mk.mod("U1", "ds3231", conn("3V3"), variant="zs042"),
              mk.mod("U2", "at24c32", conn("3V3", A0="VCC", A1="VCC", A2="VCC")))
    assert addresses(rep) == {"U1": "0x68", "U2": "0x57"}
    assert [f for f in mk.findings(rep, "mod.address_conflict") if f.status == "failed"] == []


def test_eeprom_supply_abs_max():
    rep = run(mk.mod("U1", "at24c32", conn("V65")), options={"rails": {"V65": 6.5}})
    f = one(rep, "mod.supply_range")
    assert f.severity == "danger" and "6.25 V" in f.message


# --- end to end through pins.check -------------------------------------------------------------------------------
def test_pins_check_reports_rtc_warnings():
    parts = [{"ref": "U1", "kind": "module", "value": "ZS-042", "module": "ds3231", "variant": "zs042",
              "conn": {"SDA": "SDA0", "SCL": "SCL0", "VCC": "5V", "GND": "GND"}},
             {"ref": "U2", "kind": "ic", "value": "DS1307", "module": "ds1307",
              "conn": {"SDA": "SDA0", "SCL": "SCL0", "VCC": "3V3", "GND": "GND"}}]
    res = pins.check("esp32s3", mk.i2c(), parts=parts, options={})
    codes = {w["code"] for w in res["warnings"]}
    # the answer stays below 8 KB: the info hint may be cut there (counts.findings keeps it), the engine report has it
    # the ZS-042 at 5 V: its board pull-ups are the one cause on SDA/SCL -> mod.level_out, not a 3.3 V VIH claim
    assert {"mod_rtc_ds1307_vcc_5v", "mod_level_out", "mod_address_conflict"} <= codes
    assert "mod_rtc_ds3231_vih" not in codes
    full = modcheck.run(chip="esp32s3", assignments=mk.i2c(), parts=parts, options={})
    assert "mod_rtc_rtc_module_charger" in {w["code"] for w in full.warnings}
    assert {"mod-rtc-ds1307-ds", "mod-rtc-ds3231-ds"} <= {src["id"] for src in res["sources"]}
