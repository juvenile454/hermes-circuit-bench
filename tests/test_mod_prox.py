"""Module family prox: catalog entries VL53L0X, VL53L1X, TSOP38238, HC-SR04 (class B), DRV5032,
TTP223 and the family rules mod.prox.* on synthetic projects (real catalog, real ESP32-S3 values)."""
from __future__ import annotations

import pytest

import modkit as mk
from circuit_bench.bench_core import modcheck, modules, pins

XSHUT = "mod.prox.vl53_xshut"
TSOP = "mod.prox.tsop_vs_5v"
TTP = "mod.prox.ttp223_vs_5v"
ECHO = "mod.prox.hcsr04_echo"


@pytest.fixture(autouse=True)
def _fresh_catalog():
    modules.clear_cache()
    yield
    modules.clear_cache()


def one(report, rule_id, status=None):
    fs = mk.findings(report, rule_id, status)
    assert len(fs) == 1, [(f.rule_id, f.status, f.message) for f in mk.findings(report, rule_id)]
    return fs[0]


def tof(ref, mid="vl53l0x", xshut=None, **kw):
    conn = {"SDA": "SDA0", "SCL": "SCL0", "AVDD": "3V3"}
    if xshut:
        conn["XSHUT"] = xshut
    return mk.mod(ref, mid, conn, **kw)


# --- catalog -------------------------------------------------------------------------------------------------------
def test_prox_entries_load_with_their_classes():
    cat = modules.catalog()
    assert cat.problems == []
    want = {"vl53l0x": "A1", "vl53l1x": "A1", "tsop38238": "A", "hcsr04": "B", "drv5032": "A1", "ttp223": "B"}
    for mid, cls in want.items():
        e = cat.get(mid)
        assert e["_wp"] == "prox" and e["_class"] == cls, mid
    assert cat.get("gy-530")["id"] == "vl53l0x" and cat.get("HC-SR04")["id"] == "hcsr04"


def test_vl53_values():
    cat = modules.catalog()
    for mid, i_typ, i_max in (("vl53l0x", 0.019, 0.02), ("vl53l1x", 0.016, 0.018)):
        e = cat.get(mid)
        av = e["supplies"]["AVDD"]
        assert (av["min"]["value"], av["max"]["value"], av["abs_max"]["value"]) == (2.6, 3.5, 3.6)
        assert e["io"]["vih"]["value"] == 1.12 and e["io"]["v_in_max"]["value"] == 3.6
        it = e["interfaces"][0]
        assert it["addresses"]["value"] == ["0x29"] and it["default"] == "0x29"
        assert it["f_max_hz"]["value"] == 400000
        assert (e["current"]["typ"]["value"], e["current"]["max"]["value"], e["current"]["peak"]["value"]) == (
            i_typ, i_max, 0.04)
        assert [h["code"] for h in e["hazards"]] == ["laser"]
        assert {r["code"] for r in e["requires"]} == {"decoupling", "bulk_cap", "pullup"}


def test_hcsr04_is_b_with_notes_only():
    e = modules.catalog().get("hcsr04")
    assert e["kind"] == "module"
    assert "supplies" not in e and "io" not in e and "current" not in e and not e.get("requires")
    assert all(n.get("verified") is False for n in e["notes"])


def test_drv5032_variants():
    cat = modules.catalog()
    base = cat.get("drv5032")
    assert base["io"]["outputs"] == "push_pull" and base["io"]["voh"]["rel_offset"] == -0.35
    od = cat.get("drv5032", "open_drain")
    assert od["io"]["outputs"] == "open_drain"
    assert [p["output"] for p in od["pins"] if p["name"] == "OUT"] == ["open_drain"]
    assert "pullup" in {r["code"] for r in od["requires"]}
    fb = cat.get("drv5032", "fb")
    assert fb["current"]["max"]["value"] == 1.8e-06 and base["current"]["max"]["value"] == 3.5e-06


def test_tsop_and_ttp223_values():
    cat = modules.catalog()
    t = cat.get("tsop38238")
    assert (t["supplies"]["VS"]["min"]["value"], t["supplies"]["VS"]["max"]["value"],
            t["supplies"]["VS"]["abs_max"]["value"]) == (2.0, 5.5, 6.0)
    out = next(p for p in t["pins"] if p["name"] == "OUT")
    assert out["internal_pull"]["up"]["value"] == 30000
    q = cat.get("ttp223")  # preliminary Tontek sheet = class B: no hard values, notes only (verified: false)
    assert "supplies" not in q and "current" not in q and not q.get("requires")
    assert q["io"] == {"domain": "VDD", "outputs": "push_pull"}
    assert all(n.get("verified") is False for n in q["notes"])
    assert any("VDD 2.0–5.5 V" in n["text"] for n in q["notes"])


# --- VL53: addresses, XSHUT, supply ------------------------------------------------------------------------------
def test_two_vl53_without_xshut_clash_and_need_xshut():
    r = mk.run(assignments=mk.i2c(), parts=[tof("U1"), tof("U2", "vl53l1x")])
    assert one(r, "mod.address_conflict", "failed").severity == "caution"
    f = one(r, XSHUT, "failed")
    # supersedes: the address clash is folded into this finding (its danger moves here), one warning
    assert f.severity == "caution" and "0x29" in f.message and f.refs == ["U1", "U2"]
    assert f.supersedes == ("mod.address_conflict",)
    assert [c for c in mk.codes(r) if c.startswith("mod_address")] == [] and "mod_prox_vl53_xshut" in mk.codes(r)
    assert f.source_ids == ["mod-prox-vl53l0x-ds", "mod-prox-vl53l1x-ds"]


def test_distinct_addresses_without_xshut_are_danger():
    r = mk.run(assignments=mk.i2c(), parts=[tof("U1", address="0x30"), tof("U2", address="0x31")])
    assert not mk.findings(r, "mod.address_conflict", "failed")
    f = one(r, XSHUT, "failed")
    assert f.severity == "danger" and "woken alone" in f.message


def test_each_vl53_with_own_xshut_gpio_passes():
    a = [*mk.i2c(), mk.assign("out", 4, "XS1"), mk.assign("out", 5, "XS2")]
    r = mk.run(assignments=a, parts=[tof("U1", xshut="XS1", address="0x30"), tof("U2", xshut="XS2")])
    assert one(r, XSHUT).status == "passed"
    assert mk.check_of(r, XSHUT)["status"] == "passed"


def test_one_vl53_without_xshut_is_allowed_with_hint():
    a = [*mk.i2c(), mk.assign("out", 4, "XS1")]
    r = mk.run(assignments=a, parts=[tof("U1", xshut="XS1"), tof("U2")])
    f = one(r, XSHUT)
    assert f.status == "passed" and "U2 has no own XSHUT GPIO" in f.message
    assert one(r, "mod.address_conflict", "failed").severity == "info"  # the re-addressing sequence resolves it


def test_passed_xshut_keeps_a_conflict_with_another_0x29_device():
    a = [*mk.i2c(), mk.assign("out", 4, "XS1"), mk.assign("out", 5, "XS2")]
    other = mk.mod("U3", "vl6180x", {"SDA": "SDA0", "SCL": "SCL0", "AVDD": "3V3", "AVDD_VCSEL": "3V3"})
    r = mk.run(assignments=a, parts=[tof("U1", xshut="XS1"), tof("U2", xshut="XS2"), other])
    assert one(r, XSHUT).status == "passed"
    assert one(r, "mod.address_conflict", "failed").severity == "caution"


def test_vl53_xshut_must_connect():
    for mid in ("vl53l0x", "vl53l1x"):
        xs = next(p for p in modules.catalog().get(mid)["pins"] if p["name"] == "XSHUT")
        assert xs["must_connect"] is True


def test_shared_xshut_net_or_xshut_on_a_rail_fails():
    a = [*mk.i2c(), mk.assign("out", 4, "XS")]
    r = mk.run(assignments=a, parts=[tof("U1", xshut="XS"), tof("U2", xshut="XS"), tof("U3", xshut="3V3")])
    f = one(r, XSHUT, "failed")
    assert "U1 XSHUT shares net XS" in f.message and "U3 XSHUT on 3V3" in f.message


def test_vl53_on_separate_buses_are_not_a_group():
    a = [*mk.i2c(), *mk.i2c(10, 11, "SDA1")]
    p = [tof("U1"), mk.mod("U2", "vl53l1x", {"SDA": "SDA1", "SCL": "SCL1", "AVDD": "3V3"})]
    r = mk.run(assignments=a, parts=p)
    assert mk.findings(r, XSHUT) == [] and mk.check_of(r, XSHUT) is None


def test_single_vl53_address_and_supply():
    r = mk.run(assignments=mk.i2c(), parts=[tof("U1")])
    assert r.result["buses"][0]["segments"][0]["devices"][0]["address"] == "0x29"
    assert one(r, "mod.supply_range").status == "passed"
    r5 = mk.run(assignments=mk.i2c(), parts=[mk.mod("U1", "vl53l0x", {"SDA": "SDA0", "SCL": "SCL0", "AVDD": "5V"})])
    f = one(r5, "mod.supply_range", "failed")
    assert f.severity == "danger" and "3.60 V" in f.message


# --- TSOP38238 ---------------------------------------------------------------------------------------------------
def _tsop(vs, *, read=True, facts=None):
    a = [mk.assign("in", 7, "IR")] if read else []
    return mk.run(assignments=a, parts=[mk.mod("U1", "tsop38238", {"VS": vs, "GND": "GND", "OUT": "IR"}, facts=facts)])


def test_tsop_at_5v_on_a_gpio_is_caution():
    r = _tsop("5V")
    f = one(r, TSOP, "failed")
    assert f.severity == "caution" and "30 kΩ" in f.message and "GPIO7" in f.message and "3.60 V" in f.message
    assert "mod-prox-tsop382-ds" in f.source_ids
    assert one(r, "mod.supply_range").status == "passed"  # 5 V is inside VS 2.0–5.5 V


def test_tsop_at_3v3_passes_and_unread_output_is_not_checked():
    assert one(_tsop("3V3"), TSOP).status == "passed"
    assert mk.findings(_tsop("5V", read=False), TSOP) == []
    assert one(_tsop("VIR"), TSOP).status == "not_checked"
    assert one(_tsop("5V", facts={"level_shifter": True}), TSOP).status == "passed"


# --- TTP223 ------------------------------------------------------------------------------------------------------
def _ttp(vdd):
    return mk.run(assignments=[mk.assign("in", 6, "TOUCH")],
                  parts=[mk.mod("U1", "ttp223", {"VDD": vdd, "VSS": "GND", "Q": "TOUCH"})])


def test_ttp223_at_5v_is_info_from_the_preliminary_sheet(monkeypatch):
    monkeypatch.delitem(modcheck.RULES, "mod.level_out", raising=False)
    f = one(_ttp("5V"), TTP, "failed")
    assert f.severity == "info" and "push-pull" in f.message and "GPIO6" in f.message and "Unverified" in f.message


def test_ttp223_at_5v_covers_the_generic_level_rule():
    r = _ttp("5V")
    f = one(r, TTP, "failed")
    assert f.severity == "info" and f.supersedes == ("mod.level_out",)
    assert [c for c in mk.codes(r) if c == "mod_level_out"] == []


def test_ttp223_at_3v3_passes():
    assert one(_ttp("3V3"), TTP).status == "passed"
    assert mk.findings(_ttp("3V3"), "mod.supply_range") == []  # no supply values from a class B sheet


# --- HC-SR04 (class B) -------------------------------------------------------------------------------------------
def _sr04(vcc, extra=()):
    a = [mk.assign("out", 12, "TRIG"), mk.assign("in", 13, "ECHO")]
    p = [mk.mod("U1", "hcsr04", {"VCC": vcc, "GND": "GND", "Trig": "TRIG", "Echo": "ECHO"}), *extra]
    return mk.run(assignments=a, parts=p)


def test_hcsr04_echo_at_5v_is_info_only():
    r = _sr04("5V")
    f = one(r, ECHO, "failed")
    assert f.severity == "info" and "GPIO13" in f.message and "Unverified" in f.message
    assert "Echo is 5.00 V" in f.message and "use a divider" in f.message
    assert f.supersedes == ("mod.level_out",) and "mod_level_out" not in mk.codes(r)
    assert mk.check_of(r, ECHO)["status"] == "not_checked"  # failed but capped to info
    assert mk.findings(r, "mod.supply_range") == []  # no supply values from a class B sheet


def test_hcsr04_echo_with_a_divider_part_or_at_3v3():
    div = {"ref": "R1", "kind": "resistor", "value": "1k", "conn": {"1": "ECHO", "2": "ECHO_DIV"}}
    assert one(_sr04("5V", [div]), ECHO).status == "not_checked"
    assert one(_sr04("3V3"), ECHO).status == "passed"


# --- DRV5032 -----------------------------------------------------------------------------------------------------
def _drv(vcc, variant=None, options=None):
    return mk.run(assignments=[mk.assign("in_pullup", 15, "HALL")], options=options,
                  parts=[mk.mod("U1", "drv5032", {"VCC": vcc, "GND": "GND", "OUT": "HALL"}, variant=variant)])


def test_drv5032_supply():
    assert one(_drv("3V3"), "mod.supply_range").status == "passed"
    assert one(_drv("5V", "open_drain"), "mod.supply_range").status == "passed"
    f = one(_drv("VBAT", options={"rails": {"VBAT": 6.0}}), "mod.supply_range", "failed")
    assert f.severity == "danger" and "5.50 V" in f.message


# --- end to end through pins.check ------------------------------------------------------------------------------
def test_pins_check_reports_the_prox_rules():
    parts = [{"ref": "U1", "kind": "ic", "value": "VL53L0X", "module": "vl53l0x",
              "conn": {"SDA": "SDA0", "SCL": "SCL0", "AVDD": "3V3"}},
             {"ref": "U2", "kind": "ic", "value": "VL53L0X", "module": "vl53l0x",
              "conn": {"SDA": "SDA0", "SCL": "SCL0", "AVDD": "3V3"}}]
    a = [{"role": "SDA", "mode": "i2c_sda", "pin": 8, "net": "SDA0"},
         {"role": "SCL", "mode": "i2c_scl", "pin": 9, "net": "SCL0"}]
    res = pins.check("esp32s3", a, parts=parts, options={})
    codes = {w["code"]: w["severity"] for w in res["warnings"]}
    assert codes.get("mod_prox_vl53_xshut") == "caution" and "mod_address_conflict" not in codes  # folded (supersedes)
