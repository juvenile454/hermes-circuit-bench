"""Module family level: level shifter entries, the AN10441 source and the
family rules in bench_core/modrules/level.py. Generic data/excerpt checks live in tests/test_m0_modules_*.

All projects are synthetic.
"""
from __future__ import annotations

import pytest

import excerpts as ex
import modkit as mk
from circuit_bench.bench_core import modules, pins, sources
from circuit_bench.bench_core.modrules import level

LEVEL_IDS = ("sn74ahct125", "sn74lv1t34", "txs0108e", "txb0104", "bss138")
OHM = "\u2126"


def ic(ref, module, conn):
    return {"ref": ref, "kind": "ic", "value": module.upper(), "module": module, "conn": dict(conn)}


def res(ref, value, a, b):
    return {"ref": ref, "kind": "resistor", "value": value, "conn": {"1": a, "2": b}}


def run(assignments=(), parts=(), options=None, rule=None):
    return mk.run(assignments=assignments, parts=parts, options=options, only=(rule,) if rule else None)


def fs(report, rule_id, status=None):
    return mk.findings(report, rule_id, status)


TXB_I2C = [ic("U1", "txb0104", {"VCCA": "3V3", "VCCB": "5V", "GND": "GND", "OE": "3V3", "A1": "SDA0", "A2": "SCL0",
                                 "B1": "SDA5", "B2": "SCL5"})]
TXS = {"VCCA": "3V3", "VCCB": "5V", "GND": "GND", "OE": "3V3"}


# --- catalogue -------------------------------------------------------------------------------------------------
def test_entries_load_as_level_shifters():
    cat = modules.catalog()
    for mid in LEVEL_IDS:
        m = cat.get(mid)
        assert m["category"] == "logic.level_shifter" and m["_wp"] == "level", mid
        # sn74ahct125: the ti.com file through web.archive.org (ti.com re-stamps its PDFs daily)
        assert m["_class"] == ("A1" if mid == "sn74ahct125" else "A"), mid
    assert cat.get("74ahct125")["id"] == "sn74ahct125" and cat.get("txs0108")["id"] == "txs0108e"


def test_an10441_source_is_fixed_id_class_a1_and_cited_by_bss138():
    src = sources.get("mod-level-an10441")
    assert src["class"] == "A1" and src["url"].startswith("https://web.archive.org/web/")
    assert "assets.nexperia.com/documents/application-note/AN10441.pdf" in src["url"]
    bss = modules.catalog().get("bss138")
    assert "mod-level-an10441" in bss["source_ids"]
    cited = {n.get("source_id") for n in bss["notes"]} | {r.get("source_id") for r in bss["requires"]}
    assert "mod-level-an10441" in cited


def test_an10441_excerpt_has_the_circuit_lines():
    (e,) = ex.by_source()["mod-level-an10441"]
    text = "\n".join(e.lines)
    for needle in ("(g) have to be connected to the lowest supply voltage VDD1",
                   "the drains (d) to the bus lines of the ‘higher-voltage’ section",
                   "section has pull-up resistors and devices connected to a 3.3 V supply",
                   "the right ‘high-voltage’ section has pull-up resistors",
                   "VDD2 must be equal to or higher than VDD1", "1. No device is pulling down the bus line."):
        assert needle in text, needle


@pytest.mark.parametrize(("sid", "page", "needle"), [
    ("mod-level-txb0104-ds", 22, f"be kept higher than 50 k{OHM}"),
    ("mod-level-bss138-ds", 2, "VGS(th) Gate Threshold Voltage VDS = VGS, ID = 1 mA 0.8 1.3 1.5 V"),
    ("mod-level-txs0108e-ds", 20, "VOH = VCCx × RPD / (RPD + 4kΩ) (1)"),
])
def test_rule_constants_are_in_the_excerpts(sid, page, needle):
    segs = [ln for e in ex.by_source()[sid] for seg in e.page_segments(page) for ln in seg]
    assert any(needle in ln for ln in segs)
    assert level.TXB_PULL_MIN_OHM == 50e3 and level.BSS138_VGS_TH_MAX_V == 1.5


def test_txs_pullup_comes_from_the_data():
    m = modules.catalog().get("txs0108e")
    pu = next(p for p in m["pins"] if p["name"] == "A1")["internal_pull"]["up"]
    assert pu["value"] == 4000 and pu["page"] == 16


def test_translator_io_is_relative_to_vcca():
    cat = modules.catalog()
    rails = {"VCCA": 3.3}
    assert modules.value(cat.get("txs0108e")["io"]["vih"], rails) == pytest.approx(2.9)
    assert modules.value(cat.get("txb0104")["io"]["vih"], rails) == pytest.approx(2.145)
    assert modules.value(cat.get("txb0104")["io"]["v_in_max"], rails) == pytest.approx(3.8)


@pytest.mark.parametrize(("text", "want"), [(4700, 4700.0), ("4k7", 4700.0), ("4.7k", 4700.0), ("10 kΩ", 1e4),
                                            (f"10 k{OHM}", 1e4), ("220R", 220.0), ("1M", 1e6), ("x", None),
                                            ("0", None), (None, None), (True, None)])
def test_ohms(text, want):
    assert level.ohms(text) == want


# --- no level shifter: no checks ----------------------------------------------------------------------------------
def test_rules_silent_without_level_shifters():
    r = run(mk.i2c(), [ic("U9", "bme280", {"SDI": "SDA0", "SCK": "SCL0", "SDO": "GND", "VDD": "3V3", "GND": "GND"})])
    assert r is not None
    assert not [c for c in r.checks if c["id"].startswith("modules.level.")]


# --- txb_not_i2c ------------------------------------------------------------------------------------------------
def test_txb_on_i2c_is_a_caution_on_both_sides():
    parts = TXB_I2C + [ic("U2", "bme280", {"SDI": "SDA5", "SCK": "SCL5", "SDO": "GND", "VDD": "3V3", "GND": "GND"})]
    r = run(mk.i2c(), parts, rule="mod.level.txb_not_i2c")
    (f,) = fs(r, "mod.level.txb_not_i2c", "failed")
    assert f.severity == "caution" and f.source_ids == ["mod-level-txb0104-ds"]
    assert "A1 on SDA0 (ESP i2c_sda)" in f.message and "B1 on SDA5 (U2 SDI (i2c_sda))" in f.message
    assert "mod_level_txb_not_i2c" in mk.codes(r)


def test_txb_on_i2c_seen_from_the_b_side_only():
    parts = [ic("U1", "txb0104", {"VCCA": "3V3", "VCCB": "5V", "GND": "GND", "OE": "3V3", "A1": "GPIO4",
                                  "B1": "OW5"}),
             ic("U2", "bme280", {"SDI": "OW5", "SCK": "SCL5", "SDO": "GND", "VDD": "3V3", "GND": "GND"})]
    r = run([mk.assign("out", 4)], parts, rule="mod.level.txb_not_i2c")
    assert fs(r, "mod.level.txb_not_i2c", "failed")[0].message.startswith("U1 (txb0104): B1 on OW5")


def test_txb_on_push_pull_passes():
    parts = [ic("U1", "txb0104", {"VCCA": "3V3", "VCCB": "5V", "GND": "GND", "OE": "3V3", "A1": "GPIO4",
                                  "B1": "LED5"})]
    r = run([mk.assign("out", 4)], parts, rule="mod.level.txb_not_i2c")
    assert [f.status for f in fs(r, "mod.level.txb_not_i2c")] == ["passed"]


# --- txb_pull_resistor ------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("value", "status", "sev"), [("10k", "failed", "caution"), ("50k", "failed", "caution"),
                                                     ("100k", "passed", None), ("?", "not_checked", "info")])
def test_txb_pull_resistor(value, status, sev):
    r = run(mk.i2c(), TXB_I2C + [res("R1", value, "SDA5", "5V")], rule="mod.level.txb_pull_resistor")
    (f,) = fs(r, "mod.level.txb_pull_resistor")
    assert (f.status, f.severity) == (status, sev)


def test_txb_series_resistor_is_not_a_pull_resistor():
    r = run(mk.i2c(), TXB_I2C + [res("R1", "100", "SDA5", "LEDX")], rule="mod.level.txb_pull_resistor")
    assert fs(r, "mod.level.txb_pull_resistor") == []


# --- txs_pulldown -----------------------------------------------------------------------------------------------
def test_txs_pulldown_info_with_the_voh_formula():
    parts = [ic("U1", "txs0108e", {**TXS, "A1": "GPIO4", "B1": "X5"}), res("R2", "10k", "X5", "GND")]
    r = run([mk.assign("out", 4)], parts, rule="mod.level.txs_pulldown")
    (f,) = fs(r, "mod.level.txs_pulldown", "failed")
    assert f.severity == "info" and "3.57 V" in f.message and "VCCB 5.00 V" in f.message
    assert f.refs == ["U1", "R2"]


def test_txs_pulldown_below_the_esp_vih_is_a_caution():
    parts = [ic("U1", "txs0108e", {**TXS, "A1": "GPIO4", "B1": "X5"}), res("R2", "4k7", "GPIO4", "GND")]
    r = run([mk.assign("in", 4)], parts, rule="mod.level.txs_pulldown")
    (f,) = fs(r, "mod.level.txs_pulldown", "failed")
    assert f.severity == "caution" and "1.78 V" in f.message and "ESP GPIO4" in f.message


def test_txs_pulldown_below_a_module_vih_is_a_caution():
    parts = [ic("U1", "txs0108e", {**TXS, "VCCB": "3V3", "A1": "GPIO4", "B1": "X3"}), res("R2", "2k", "X3", "GND"),
             ic("U2", "sn74lv1t34", {"A": "X3", "Y": "OUT", "VCC": "5V", "GND": "GND"})]
    r = run([mk.assign("out", 4)], parts, rule="mod.level.txs_pulldown")
    (f,) = fs(r, "mod.level.txs_pulldown", "failed")
    assert f.severity == "caution" and "U2 A" in f.message and "1.10 V" in f.message
    assert set(f.source_ids) == {"mod-level-txs0108e-ds", "mod-level-sn74lv1t34-ds"}


def test_txs_pullup_is_not_a_pulldown():
    parts = [ic("U1", "txs0108e", {**TXS, "A1": "GPIO4", "B1": "X5"}), res("R2", "10k", "X5", "5V")]
    assert fs(run([mk.assign("out", 4)], parts, rule="mod.level.txs_pulldown"), "mod.level.txs_pulldown") == []


# --- ahct_needs_5v ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("rail", "status"), [("3V3", "failed"), ("5V", "passed")])
def test_ahct_supply(rail, status):
    parts = [ic("U1", "sn74ahct125", {"VCC": rail, "GND": "GND", "1OE": "GND", "1A": "GPIO4", "1Y": "LED"})]
    r = run([mk.assign("out", 4)], parts, rule="mod.level.ahct_needs_5v")
    (f,) = fs(r, "mod.level.ahct_needs_5v")
    assert f.status == status
    if status == "failed":
        assert f.severity == "info" and "4.50 V–5.5 V" in f.message


def test_ahct_supply_unknown_rail():
    parts = [ic("U1", "sn74ahct125", {"VCC": "VBUS", "GND": "GND"})]
    (f,) = fs(run((), parts, rule="mod.level.ahct_needs_5v"), "mod.level.ahct_needs_5v")
    assert f.status == "not_checked"


# --- side_supply ------------------------------------------------------------------------------------------------
def test_esp_on_the_b_side_at_5v_is_danger():
    parts = [ic("U1", "txs0108e", {**TXS, "B1": "GPIO4", "A1": "X3"})]
    (f,) = fs(run([mk.assign("out", 4)], parts, rule="mod.level.side_supply"), "mod.level.side_supply")
    assert (f.status, f.severity) == ("failed", "danger") and "VCCB 5.00 V" in f.message


def test_esp_on_the_b_side_at_3v3_passes():
    parts = [ic("U1", "txb0104", {"VCCA": "V18", "VCCB": "3V3", "GND": "GND", "OE": "V18", "B1": "GPIO4",
                                  "A1": "X18"})]
    r = run([mk.assign("out", 4)], parts, options={"rails": {"V18": 1.8}}, rule="mod.level.side_supply")
    assert [f.status for f in fs(r, "mod.level.side_supply")] == ["passed"]


def test_vcca_above_vccb_is_a_caution():
    parts = [ic("U1", "txb0104", {"VCCA": "3V3", "VCCB": "V25", "GND": "GND", "OE": "3V3", "A1": "GPIO4"})]
    r = run([mk.assign("out", 4)], parts, options={"rails": {"V25": 2.5}}, rule="mod.level.side_supply")
    (f,) = fs(r, "mod.level.side_supply", "failed")
    assert f.severity == "caution" and "VCCA ≤ VCCB" in f.message


def test_correct_translator_sides_pass():
    parts = [ic("U1", "txs0108e", {**TXS, "A1": "GPIO4", "B1": "X5"})]
    assert [f.status for f in fs(run([mk.assign("out", 4)], parts, rule="mod.level.side_supply"),
                                 "mod.level.side_supply")] == ["passed"]


# --- oe_disabled ------------------------------------------------------------------------------------------------
def test_translator_oe_on_gnd():
    parts = [ic("U1", "txs0108e", {**TXS, "OE": "GND", "A1": "GPIO4", "B1": "X5"})]
    (f,) = fs(run([mk.assign("out", 4)], parts, rule="mod.level.oe_disabled"), "mod.level.oe_disabled")
    assert (f.status, f.severity) == ("failed", "caution")


@pytest.mark.parametrize(("oe", "status"), [("5V", "failed"), ("GND", "passed"), ("GPIO5", "passed")])
def test_ahct_oe(oe, status):
    parts = [ic("U1", "sn74ahct125", {"VCC": "5V", "GND": "GND", "1OE": oe, "1A": "GPIO4", "1Y": "LED"})]
    r = run([mk.assign("out", 4), mk.assign("out", 5)], parts, rule="mod.level.oe_disabled")
    (f,) = fs(r, "mod.level.oe_disabled")
    assert f.status == status


# --- bss138_wiring ----------------------------------------------------------------------------------------------
BSS_OK = [ic("Q1", "bss138", {"G": "3V3", "S": "SDA0", "D": "SDA5"}), res("R1", "10k", "SDA0", "3V3"),
          res("R2", "10k", "SDA5", "5V")]


def test_bss138_per_an10441_passes():
    (f,) = fs(run(mk.i2c(), BSS_OK, rule="mod.level.bss138_wiring"), "mod.level.bss138_wiring")
    assert f.status == "passed" and "mod-level-an10441" in f.source_ids


def test_bss138_esp_on_the_drain():
    parts = [ic("Q1", "bss138", {"G": "3V3", "S": "SDA3", "D": "SDA0"})]
    (f,) = fs(run(mk.i2c(), parts, rule="mod.level.bss138_wiring"), "mod.level.bss138_wiring")
    assert f.severity == "caution" and "on the drain" in f.message and f.source_ids == ["mod-level-an10441"]


def test_bss138_gate_below_threshold():
    parts = [ic("Q1", "bss138", {"G": "V12", "S": "SDA0", "D": "SDA5"})]
    r = run(mk.i2c(), parts, options={"rails": {"V12": 1.2}}, rule="mod.level.bss138_wiring")
    (f,) = fs(r, "mod.level.bss138_wiring")
    assert f.severity == "caution" and "VGS(th) max 1.50 V" in f.message and "mod-level-bss138-ds" in f.source_ids


def test_bss138_pullup_rails():
    parts = [ic("Q1", "bss138", {"G": "3V3", "S": "SDA0", "D": "SDA5"}), res("R1", "10k", "SDA0", "5V"),
             res("R2", "10k", "SDA5", "V18")]
    r = run(mk.i2c(), parts, options={"rails": {"V18": 1.8}}, rule="mod.level.bss138_wiring")
    (f,) = fs(r, "mod.level.bss138_wiring")
    assert "source pull-up R1" in f.message and "drain pull-up R2" in f.message


def test_bss138_gate_open():
    (f,) = fs(run(mk.i2c(), [ic("Q1", "bss138", {"S": "SDA0", "D": "SDA5"})], rule="mod.level.bss138_wiring"),
              "mod.level.bss138_wiring")
    assert f.status == "not_checked"


# --- end to end through pins.check ------------------------------------------------------------------------------
def test_pins_check_reports_txb_on_i2c():
    env = pins.check("esp32s3", mk.i2c(), parts=TXB_I2C, options={})
    codes = {w["code"] for w in env["warnings"]}
    assert "mod_level_txb_not_i2c" in codes
    assert "mod-level-txb0104-ds" in {s["id"] for s in env["sources"]}


def test_txb_on_i2c_supersedes_pin_role_and_unconnected_on_the_txb():
    parts = TXB_I2C + [ic("U2", "bme280", {"SDI": "SDA5", "SCK": "SCL5", "SDO": "GND", "VDD": "3V3", "GND": "GND"})]
    assigns = [mk.assign("i2c_sda", 8, "SDA0"), mk.assign("i2c_scl", 9, "SCL0")]
    r = run(assigns, parts)
    # the TXB counts as a bridge: pin_role checks no direction on its channel pins at all
    shown = [(w["code"], w["refs"]) for w in r.warnings]
    assert ("mod_level_txb_not_i2c", ["U1"]) in shown
    assert not [c for c, refs in shown if c in ("mod_pin_role", "mod_unconnected") and "U1" in refs]


def test_txb_passing_does_not_lower_other_findings():
    parts = [ic("U1", "txb0104", {"VCCA": "3V3", "VCCB": "5V", "GND": "GND", "OE": "3V3", "A1": "D0", "B1": "D5"})]
    r = run([mk.assign("out", 4, "D0")], parts)
    assert fs(r, "mod.level.txb_not_i2c", "passed")
    assert all(not f.supersedes for f in fs(r, "mod.level.txb_not_i2c"))
