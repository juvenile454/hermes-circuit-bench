"""Module family motor: catalog entries, family rules (modrules/motor.py) and the calculator
current_limit (calcs/current_limit.py). Synthetic projects only."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from circuit_bench.bench_core import calckit as ck
from circuit_bench.bench_core import modules, parts
import excerpts as ex
from modkit import assign, findings, mod, run

ROOT = Path(__file__).resolve().parent.parent
MOTOR_IDS = ("uln2003a", "uln2803a", "uln2803c", "drv8833", "drv8825", "a4988", "tmc2209", "tb6612fng", "l298n")
RAILS = {"VMOT": 12.0, "V24": 24.0, "V40": 40.0, "V15": 15.0, "V55": 55.0}


def report(*parts_, assignments=(), rails=None, only=None):
    opts = {"rails": dict(RAILS if rails is None else rails)}
    return run(assignments=list(assignments), parts=list(parts_), options=opts, only=only)


def one(rep, rule_id, ref=None):
    fs = [f for f in findings(rep, rule_id) if ref is None or ref in f.refs]
    assert len(fs) == 1, [(f.status, f.message) for f in fs]
    return fs[0]


def statuses(rep, rule_id):
    return sorted((f.status, f.severity) for f in findings(rep, rule_id))


# --- data ------------------------------------------------------------------------------------------------------------
def test_catalog_has_every_motor_part_without_problems():
    cat = modules.Catalog.from_dir()
    assert cat.problems == []
    for mid in MOTOR_IDS:
        m = cat.get(mid)
        assert m["_wp"] == "motor"
        assert m["category"].startswith("driver.")


@pytest.mark.parametrize("mid", MOTOR_IDS)
def test_safety_family_hazards_are_present(mid):
    """Leitplanke 10: every motor part carries motor_supply, high_current and heat."""
    codes = {h["code"] for h in modules.catalog().get(mid)["hazards"]}
    assert {"motor_supply", "high_current", "heat"} <= codes


def test_source_classes():
    cat = modules.catalog()
    assert {m: cat.get(m)["_class"] for m in MOTOR_IDS} == {
        "uln2003a": "A", "uln2803a": "A2", "uln2803c": "A", "drv8833": "A", "drv8825": "A1", "a4988": "A",
        "tmc2209": "A1", "tb6612fng": "A1", "l298n": "A1"}


def test_carrier_variants_keep_only_the_bulk_capacitor():
    cat = modules.catalog()
    for mid in ("drv8825", "tmc2209", "a4988"):
        v = cat.get(mid, "carrier")
        assert v["kind"] == "module" and [r["code"] for r in v["requires"]] == ["bulk_cap"]
    assert cat.get("l298n", "board")["kind"] == "module"


def test_a4988_bulk_cap_on_vbb_in_chip_and_carrier():
    cat = modules.catalog()
    for v in (None, "carrier"):
        bulk = [r for r in cat.get("a4988", v)["requires"] if r["code"] == "bulk_cap"]
        assert len(bulk) == 1 and bulk[0]["pins"] == ["VBB1"] and bulk[0]["value"] == "100uF"


def test_a4988_carrier_marks_board_parts_nc_and_ms_pins_pull_down():
    cat = modules.catalog()
    pins = {p["name"]: p for p in cat.get("a4988", "carrier")["pins"]}
    for name in ("ROSC", "CP1", "CP2", "VCP", "VREG", "SENSE1", "SENSE2"):
        assert pins[name]["signal"] == "nc", name
    assert pins["RESET"]["signal"] == "reset_in"  # open RESET stays a finding (p05)
    assert {n: pins[n]["internal_pull"]["down"]["value"] for n in ("MS1", "MS2", "MS3")} == {
        "MS1": 100000.0, "MS2": 50000.0, "MS3": 100000.0}
    unverified = [n for n in cat.get("a4988", "carrier")["notes"] if n["verified"] is False]
    assert any("not on the header" in n["text"] for n in unverified)
    base = {p["name"]: p["signal"] for p in cat.get("a4988")["pins"]}
    assert base["ROSC"] == "mode_select" and base["CP1"] == "power_out"


def test_a4988_carrier_open_rosc_is_no_finding_but_open_reset_is():
    conn = {"VDD": "3V3", "GND": "GND", "VBB1": "VMOT", "STEP": "GPIO4", "DIR": "GPIO5", "ENABLE": "GND",
            "SLEEP": "3V3", "MS1": "GND", "MS2": "GND", "MS3": "GND"}
    rep = report(mod("U1", "a4988", conn, variant="carrier"),
                 assignments=[assign("out", 4, "GPIO4"), assign("out", 5, "GPIO5")], only=("mod.unconnected",))
    msgs = [f.message for f in findings(rep, "mod.unconnected") if f.status == "failed"]
    assert not any("ROSC" in m for m in msgs), msgs
    assert any("RESET" in m for m in msgs), msgs


def test_uln2003a_inputs_are_pulled_down_inside():
    m = modules.catalog().get("uln2003a")
    assert all(p.get("internal_pull") == "down" for p in m["pins"] if p["name"].endswith("B"))
    rep = report(mod("U1", "uln2003a", {"1B": "GPIO4", "COM": "5V", "E": "GND", "1C": "M1"}),
                 assignments=[assign("out", 4, "GPIO4")], only=("mod.unconnected",))
    assert not [f for f in findings(rep, "mod.unconnected") if f.status == "failed"]


def test_l298_flyback_counts_catalog_diodes():
    conn = {"VS": "VMOT", "VSS": "5V", "GND": "GND", "OUT1": "MA", "OUT2": "MB"}
    ds = []
    for i, net in enumerate(("MA", "MB")):
        ds.append(mod(f"DU{i}", "ss14", {"A": net, "K": "VMOT"}))
        ds.append(mod(f"DD{i}", "1n5819", {"A": "GND", "K": net}))
    rep = report(mod("U1", "l298n", conn), *ds, only=("mod.motor.l298_flyback",))
    assert statuses(rep, "mod.motor.l298_flyback") == [("passed", None)]
    rep = report(mod("U1", "l298n", conn), *ds[:3], only=("mod.motor.l298_flyback",))
    f = one(rep, "mod.motor.l298_flyback")
    assert f.status == "failed" and "OUT2 (to GND)" in f.message


def test_motor_v_in_max_is_the_absolute_maximum():
    cat = modules.catalog()
    assert {m: cat.get(m)["io"]["v_in_max"].get("value") for m in ("drv8833", "drv8825", "tb6612fng")} == {
        "drv8833": 7.0, "drv8825": 7.0, "tb6612fng": 6.0}
    t = cat.get("tmc2209")["io"]["v_in_max"]
    assert (t["rel_offset"], t["of"], t["page"]) == (0.5, "VCC_IO", 75)


def _motor_parts_file():
    return json.loads((ROOT / "circuit_bench" / "data" / "parts" / "motor.json").read_text(encoding="utf-8"))


def _cited(obj, where=""):
    if isinstance(obj, dict):
        if "evidence" in obj and "page" in obj:
            yield where, obj
        for k, v in obj.items():
            yield from _cited(v, f"{where}.{k}")


def test_motor_part_data_quotes_the_excerpts():
    by_source = ex.by_source("mod-motor-*.txt")
    for p in _motor_parts_file()["parts"]:
        sid = p["source_id"]
        assert sid in by_source, sid
        for where, item in _cited(p, p["id"]):
            parts_ = modules.evidence_parts(item["evidence"])
            segs = [s for e in by_source[sid] for s in e.page_segments(item["page"])]
            assert segs and any(ex.find_parts_in_order(parts_, s) for s in segs), f"{where}: {item['evidence']!r}"


def test_motor_part_data_loads_as_motor_driver():
    assert parts.ids_of("motor_driver") == ["A4988", "DRV8825", "DRV8833", "TMC2209"]
    assert parts.find("tmc2209", "motor_driver")["v_fs"]["1"]["value"] == 0.18


# --- mod.supply_range per part (generic rule) ------------------------------------------------------------------------
@pytest.mark.parametrize("part, conn, expect", [
    ("drv8825", {"VMA": "5V", "VMB": "5V"}, ("failed", "caution")),        # below 8.2 V
    ("drv8825", {"VMA": "V24", "VMB": "V24"}, ("passed", None)),
    ("a4988", {"VBB1": "V40", "VDD": "3V3"}, ("failed", "danger")),          # VBB above 35 V absolute
    ("drv8833", {"VM": "VMOT"}, ("failed", "danger")),                       # 12 V > 11.8 V absolute
    ("drv8833", {"VM": "5V"}, ("passed", None)),
    ("tmc2209", {"VS": "5V", "VCC_IO": "3V3"}, ("failed", "caution")),       # VS below 5.5 V (internal regulator)
    ("tb6612fng", {"VM1": "V15", "VCC": "3V3"}, ("failed", "caution")),      # above 13.5 V, at the 15 V absolute
    ("l298n", {"VS": "VMOT", "VSS": "3V3"}, ("failed", "caution")),          # VSS below 4.5 V
    ("uln2003a", {"COM": "V55", "E": "GND"}, ("failed", "danger")),          # COM above the 50 V clamp rating
])
def test_supply_range(part, conn, expect):
    rep = report(mod("U1", part, conn), only=("mod.supply_range",))
    got = sorted((f.status, f.severity) for f in findings(rep, "mod.supply_range"))
    assert expect in got, got


def test_tmc2209_vcc_io_at_5v_is_fine_and_vs_at_24v_too():
    rep = report(mod("U1", "tmc2209", {"VS": "V24", "VCC_IO": "5V"}), only=("mod.supply_range",))
    assert {f.status for f in findings(rep, "mod.supply_range")} == {"passed"}


# --- mod.motor.motor_supply ------------------------------------------------------------------------------------------
def test_motor_supply_open_is_caution():
    rep = report(mod("U1", "a4988", {"VDD": "3V3"}), only=("mod.motor.motor_supply",))
    f = one(rep, "mod.motor.motor_supply")
    assert (f.status, f.severity) == ("failed", "caution") and "VBB1, VBB2" in f.message


def test_motor_supply_below_minimum_is_undervoltage_lockout():
    rep = report(mod("U1", "drv8825", {"VMA": "5V", "VMB": "5V"}), only=("mod.motor.motor_supply",))
    f = one(rep, "mod.motor.motor_supply")
    assert (f.status, f.severity) == ("failed", "caution") and "undervoltage lockout" in f.message
    assert "8.20 V" in f.message and f.source_ids == ["mod-motor-drv8825-ds"]


def test_motor_supply_on_the_esp_rail_is_caution_even_in_range():
    rep = report(mod("U1", "drv8833", {"VM": "3V3"}), only=("mod.motor.motor_supply",))
    f = one(rep, "mod.motor.motor_supply")
    assert (f.status, f.severity) == ("failed", "caution") and "3.3 V rail" in f.message
    assert "rule-of-thumb" in f.source_ids


def test_motor_supply_unknown_rail_is_not_checked():
    rep = report(mod("U1", "tmc2209", {"VS": "VBAT"}), only=("mod.motor.motor_supply",))
    f = one(rep, "mod.motor.motor_supply")
    assert f.status == "not_checked"


def test_motor_supply_passes_on_a_separate_rail():
    rep = report(mod("U1", "tb6612fng", {"VM1": "VMOT", "VCC": "3V3"}),
                 mod("U2", "l298n", {"VS": "VMOT", "VSS": "5V"}), only=("mod.motor.motor_supply",))
    assert statuses(rep, "mod.motor.motor_supply") == [("passed", None), ("passed", None)]


def test_drv8825_vm_pins_on_different_nets():
    rep = report(mod("U1", "drv8825", {"VMA": "V24", "VMB": "VMOT"}), only=("mod.motor.motor_supply",))
    fs = findings(rep, "mod.motor.motor_supply", "failed")
    assert len(fs) == 1 and "same motor supply" in fs[0].message


def test_motor_supply_ignores_non_drivers():
    rep = report(mod("U1", "uln2003a", {"COM": "5V"}), only=("mod.motor.motor_supply",))
    assert findings(rep, "mod.motor.motor_supply") == []


# --- mod.motor.uln_com_flyback ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("uln", ["uln2003a", "uln2803a", "uln2803c"])
@pytest.mark.parametrize("com, expect", [
    (None, ("failed", "caution")), ("GND", ("failed", "caution")), ("5V", ("passed", None)),
    ("VCOIL", ("not_checked", "info")),
])
def test_uln_com(uln, com, expect):
    gnd = "E" if uln == "uln2003a" else "GND"
    conn = {gnd: "GND", "1B": "GPIO4"}
    if com:
        conn["COM"] = com
    rep = report(mod("U1", uln, conn), assignments=[assign("out", 4)], only=("mod.motor.uln_com_flyback",))
    f = one(rep, "mod.motor.uln_com_flyback")
    assert (f.status, f.severity) == expect


def test_uln_com_cites_the_part_source():
    rep = report(mod("U1", "uln2803a", {"GND": "GND"}), only=("mod.motor.uln_com_flyback",))
    assert one(rep, "mod.motor.uln_com_flyback").source_ids == ["mod-motor-uln2803a-ds"]


# --- mod.motor.l298_flyback ------------------------------------------------------------------------------------------
L298_CONN = {"VS": "VMOT", "VSS": "5V", "GND": "GND", "OUT1": "MA", "OUT2": "MB"}


def diodes(*nets):
    out = []
    for i, net in enumerate(nets):
        out.append({"ref": f"D{2 * i + 1}", "kind": "diode", "value": "1N5819", "conn": {"A": net, "K": "VMOT"}})
        out.append({"ref": f"D{2 * i + 2}", "kind": "diode", "value": "1N5819", "conn": {"A": "GND", "K": net}})
    return out


def test_l298_without_diodes_is_caution():
    rep = report(mod("U1", "l298n", L298_CONN), only=("mod.motor.l298_flyback",))
    f = one(rep, "mod.motor.l298_flyback")
    assert (f.status, f.severity) == ("failed", "caution")
    assert "OUT1" in f.message and "OUT2" in f.message and "trr ≤ 200 ns" in f.message


def test_l298_with_diodes_to_vs_and_gnd_passes():
    rep = report(mod("U1", "l298n", L298_CONN), *diodes("MA", "MB"), only=("mod.motor.l298_flyback",))
    assert one(rep, "mod.motor.l298_flyback").status == "passed"


def test_l298_with_only_one_diode_per_output_names_the_missing_side():
    ds = [d for d in diodes("MA", "MB") if d["conn"]["K"] == "VMOT"]
    rep = report(mod("U1", "l298n", L298_CONN), *ds, only=("mod.motor.l298_flyback",))
    f = one(rep, "mod.motor.l298_flyback")
    assert f.status == "failed" and "OUT1 (to GND), OUT2 (to GND)" in f.message


def test_l298_board_variant_is_info():
    rep = report(mod("U1", "l298n", L298_CONN, variant="board"), only=("mod.motor.l298_flyback",))
    f = one(rep, "mod.motor.l298_flyback")
    assert (f.status, f.severity) == ("failed", "info") and "unverified" in f.message


def test_l298_outputs_open_is_not_checked():
    rep = report(mod("U1", "l298n", {"VS": "VMOT", "VSS": "5V"}), only=("mod.motor.l298_flyback",))
    assert one(rep, "mod.motor.l298_flyback").status == "not_checked"


# --- mod.motor.a4988_vdd_3v3 -----------------------------------------------------------------------------------------
STEP_DIR = [assign("out", 4, "STEP"), assign("out", 5, "DIR")]


def test_a4988_vdd_3v3_passes():
    rep = report(mod("U1", "a4988", {"VDD": "3V3", "VBB1": "VMOT", "STEP": "STEP", "DIR": "DIR"}),
                 assignments=STEP_DIR, only=("mod.motor.a4988_vdd_3v3",))
    f = one(rep, "mod.motor.a4988_vdd_3v3")
    assert f.status == "passed" and "2.31 V" in f.message


def test_a4988_vdd_5v_is_caution_with_the_3v3_hint():
    rep = report(mod("U1", "a4988", {"VDD": "5V", "VBB1": "VMOT", "STEP": "STEP", "DIR": "DIR"}),
                 assignments=STEP_DIR, only=("mod.motor.a4988_vdd_3v3",))
    f = one(rep, "mod.motor.a4988_vdd_3v3")
    assert (f.status, f.severity) == ("failed", "caution")
    assert "3.50 V" in f.message and "Power VDD from 3V3" in f.message and f.source_ids == ["mod-motor-a4988-ds"]


def test_a4988_vdd_unknown_is_not_checked_and_undriven_inputs_skip():
    rep = report(mod("U1", "a4988", {"VDD": "VLOGIC", "STEP": "STEP"}), assignments=STEP_DIR[:1],
                 only=("mod.motor.a4988_vdd_3v3",))
    assert one(rep, "mod.motor.a4988_vdd_3v3").status == "not_checked"
    rep = report(mod("U1", "a4988", {"VDD": "5V"}), only=("mod.motor.a4988_vdd_3v3",))
    assert findings(rep, "mod.motor.a4988_vdd_3v3") == []


def test_a4988_carrier_variant_still_gets_the_rule():
    rep = report(mod("U1", "a4988", {"VDD": "5V", "STEP": "STEP"}, variant="carrier"), assignments=STEP_DIR[:1],
                 only=("mod.motor.a4988_vdd_3v3",))
    f = one(rep, "mod.motor.a4988_vdd_3v3")
    assert f.status == "failed" and f.severity == "caution"


def test_level_in_flags_the_a4988_at_5v():
    rep = report(mod("U1", "a4988", {"VDD": "5V", "STEP": "STEP"}), assignments=STEP_DIR[:1])
    assert findings(rep, "mod.level_in", "failed")


# --- calculator current_limit ----------------------------------------------------------------------------------------
def calc(**kw):
    return ck.run("current_limit", kw)


def chk(env, name):
    return next(c["status"] for c in env["checks"] if c["id"] == f"calc.current_limit.{name}")


def test_registered_in_group_drive():
    meta = next(m for m in ck.meta() if m["kind"] == "current_limit")
    assert meta["group"] == "drive"
    assert [(p["name"], p["required"]) for p in meta["params"]] == [
        ("driver", True), ("r_sense", True), ("v_ref", False), ("i_target", False), ("vsense", False)]
    assert ck.problems() == []


def test_drv8825_datasheet_example():
    e = calc(driver="drv8825", r_sense=0.25, v_ref=2.5)  # p. 12: 2.5 V / (5 x 0.25 Ω) = 2 A
    assert e["ok"] and e["result"]["i_limit"]["value"] == pytest.approx(2.0)
    assert {c["status"] for c in e["checks"]} == {"passed"}
    assert e["sources"][0]["id"] == "mod-motor-drv8825-ds"


def test_drv8833_datasheet_example():
    e = calc(driver="drv8833", r_sense=1.0)  # p. 10: 200 mV / 1 Ω = 200 mA
    assert e["result"]["i_limit"]["value"] == pytest.approx(0.2) and e["result"]["v_ref"] is None


def test_a4988_formula_and_inverse():
    e = calc(driver="a4988", r_sense="0.1", v_ref="0.8")
    assert e["result"]["i_limit"]["value"] == pytest.approx(0.8 / (8 * 0.1))
    inv = calc(driver="a4988", r_sense=0.1, i_target=1.0)
    assert inv["result"]["v_ref"]["value"] == pytest.approx(0.8)


def test_tmc2209_formula_both_directions():
    r = 0.11
    i_fs = 0.325 / (r + 0.02) / math.sqrt(2)
    e = calc(driver="tmc2209", r_sense=r, v_ref=1.25)
    assert e["result"]["i_limit"]["value"] == pytest.approx(i_fs * 0.5, rel=1e-5)
    assert e["result"]["i_full_scale"]["value"] == pytest.approx(i_fs, rel=1e-5)
    inv = calc(driver="tmc2209", r_sense=r, i_target=e["result"]["i_limit"]["value"])
    assert inv["result"]["v_ref"]["value"] == pytest.approx(1.25, rel=1e-4)
    hi = calc(driver="tmc2209", r_sense=r, v_ref=1.25, vsense="1")
    assert hi["result"]["i_limit"]["value"] == pytest.approx(0.18 / (r + 0.02) / math.sqrt(2) * 0.5, rel=1e-5)


def test_tmc2209_vref_above_full_scale_counts_as_100_percent():
    e = calc(driver="tmc2209", r_sense=0.11, v_ref=3.0)
    assert e["result"]["i_limit"]["value"] == pytest.approx(e["result"]["i_full_scale"]["value"])
    assert any(a["key"] == "v_ref" for a in e["assumptions"])


def test_tmc2209_target_above_full_scale_fails():
    e = calc(driver="tmc2209", r_sense=0.15, i_target=1.5)
    assert chk(e, "full_scale") == "failed"
    assert "current_limit_full_scale" in {w["code"] for w in e["warnings"]}


@pytest.mark.parametrize("kw, check_name, sev", [
    (dict(driver="a4988", r_sense=0.1, v_ref=4.4), "v_ref_max", "caution"),        # VREF range 0–4 V
    (dict(driver="a4988", r_sense=0.1, v_ref=5.6), "v_ref_abs_max", "danger"),     # REF absolute 5.5 V
    (dict(driver="a4988", r_sense=0.05, i_target=2.5), "i_max", "danger"),         # ±2 A
    (dict(driver="drv8825", r_sense=0.1, v_ref=3.8), "v_ref_max", "caution"),      # 3.5 V recommended
    (dict(driver="drv8825", r_sense=0.1, v_ref=0.5), "v_ref_min", "info"),         # accuracy below 1 V
    (dict(driver="drv8825", r_sense=0.1, i_target=3.0), "i_max", "danger"),        # 2.5 A continuous
    (dict(driver="drv8833", r_sense=0.08), "i_ocp", "caution"),                    # 2.5 A: OCP trips from 2 A
    (dict(driver="drv8833", r_sense=0.1), "i_max", "caution"),                     # 2 A > 1.5 A per bridge
    (dict(driver="tmc2209", r_sense=0.1, i_target=1.6), "i_max", "caution"),       # 1.4 A RMS guideline
    (dict(driver="tmc2209", r_sense=0.05, i_target=2.1), "i_peak_max", "danger"),  # 2.97 A peak > 2.8 A
    (dict(driver="tmc2209", r_sense=0.47, v_ref=0.3), "v_ref_min", "caution"),     # < 0.5 V not recommended
])
def test_limits(kw, check_name, sev):
    e = calc(**kw)
    assert e["ok"] and chk(e, check_name) == "failed"
    w = next(w for w in e["warnings"] if w["code"] == f"current_limit_{check_name}")
    assert w["severity"] == sev and w["source_ids"] == [f"mod-motor-{kw['driver']}-ds"]


def test_r_sense_is_a_user_value_and_always_flagged():
    e = calc(driver="a4988", r_sense=0.068, v_ref=0.5)
    assert {"current_limit_r_sense", "current_limit_motor"} <= {w["code"] for w in e["warnings"]}
    assert e["assumptions"][0]["key"] == "r_sense"


@pytest.mark.parametrize("kw", [
    dict(driver="l293d", r_sense=0.1, v_ref=1),                 # unknown driver
    dict(driver="a4988", r_sense=0.1),                          # neither v_ref nor i_target
    dict(driver="a4988", r_sense=0.1, v_ref=1, i_target=1),     # both
    dict(driver="drv8833", r_sense=0.5, v_ref=1),               # no VREF pin
    dict(driver="a4988", r_sense=0, v_ref=1),                   # zero sense resistor
    dict(driver="a4988", r_sense=0.1, v_ref=0),                 # zero VREF
    dict(driver="tmc2209", r_sense=0.1, v_ref=1, vsense="2"),   # bad vsense
    dict(driver="a4988", v_ref=1),                              # r_sense missing
])
def test_bad_inputs(kw):
    e = calc(**kw)
    assert not e["ok"] and e["error"]["code"] == "invalid_args"


def test_low_voltage_rule():
    e = calc(driver="a4988", r_sense=0.1, v_ref=61)
    assert not e["ok"] and "low_voltage_only" in {w["code"] for w in e["warnings"]}
