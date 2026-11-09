"""Module family ndrive: catalog entries TPL7407L, DRV8871, TMC2208, SS14, BAT54 and the family
rules (modrules/ndrive.py). Synthetic projects only."""
from __future__ import annotations

import pytest

from circuit_bench.bench_core import modules
from circuit_bench.bench_core.modrules import ndrive
import excerpts as ex
from modkit import assign, findings, mod, run

IDS = ("tpl7407l", "drv8871", "tmc2208", "ss14", "bat54")
DRIVERS = ("tpl7407l", "drv8871", "tmc2208")
RAILS = {"VMOT": 12.0, "V12": 12.0, "V24": 24.0, "V36": 36.0, "V40": 40.0, "V45": 45.0, "V55": 55.0}
DRV = {"IN1": "IN1", "IN2": "IN2", "VM": "VMOT", "GND": "GND", "PGND": "GND", "OUT1": "MA", "OUT2": "MB"}


def report(*parts_, assignments=(), rails=None, only=None):
    return run(assignments=list(assignments), parts=list(parts_),
               options={"rails": dict(RAILS if rails is None else rails)}, only=only)


def one(rep, rule_id, ref=None):
    fs = [f for f in findings(rep, rule_id) if ref is None or ref in f.refs]
    assert len(fs) == 1, [(f.status, f.message) for f in fs]
    return fs[0]


def res(ref, value, a, b="GND", kind="resistor"):
    return {"ref": ref, "kind": kind, "value": value, "conn": {"1": a, "2": b}}


# --- data ------------------------------------------------------------------------------------------------------------
def test_catalog_has_every_part_without_problems():
    cat = modules.Catalog.from_dir()
    assert cat.problems == []
    got = {m: (cat.get(m)["_wp"], cat.get(m)["category"], cat.get(m)["_class"]) for m in IDS}
    assert got == {"tpl7407l": ("ndrive", "driver.array", "A"), "drv8871": ("ndrive", "driver.motor", "A"),
                   "tmc2208": ("ndrive", "driver.stepper", "A1"), "ss14": ("ndrive", "discrete.diode", "A"),
                   "bat54": ("ndrive", "discrete.diode", "A1")}


@pytest.mark.parametrize("mid", DRIVERS)
def test_safety_family_hazards_are_present(mid):
    """Leitplanke 10: every motor driver carries motor_supply, high_current and heat."""
    codes = {h["code"] for h in modules.catalog().get(mid)["hazards"]}
    assert {"motor_supply", "high_current", "heat"} <= codes


def test_variants_resolve():
    cat = modules.catalog()
    assert [p["name"] for p in cat.get("bat54", "c")["pins"]] == ["A1", "A2", "K"]
    assert [p["name"] for p in cat.get("bat54", "s")["pins"]] == ["A1", "K2", "CT"]
    assert cat.get("drv8871", "board")["kind"] == "module"
    assert [r["code"] for r in cat.get("tmc2208", "carrier")["requires"]] == ["bulk_cap"]


def test_key_values():
    cat = modules.catalog()
    tpl, drv, tmc = cat.get("tpl7407l"), cat.get("drv8871"), cat.get("tmc2208")
    assert [tpl["supplies"]["COM"][k]["value"] for k in ("min", "max", "abs_max")] == [8.5, 40.0, 42.0]
    assert [drv["supplies"]["VM"][k]["value"] for k in ("min", "max", "abs_max")] == [6.5, 45.0, 50.0]
    assert [tmc["supplies"]["VS"][k]["value"] for k in ("min", "max", "abs_max")] == [5.5, 36.0, 39.0]
    assert tpl["io"]["vih"]["value"] == 1.5 and drv["io"]["vih"]["value"] == 1.5
    assert tmc["io"]["vih"]["rel"] == 0.7
    # TMC2208 standalone formula adds 30 mΩ (the TMC2209 adds 20 mΩ): keep that difference visible
    assert any("+ 30 mΩ" in n["text"] for n in tmc["notes"])


def test_cited_rule_facts_are_in_the_excerpts():
    by = ex.by_source("mod-ndrive-*.txt")
    for name, fact in ndrive.FACTS.items():
        parts = fact["evidence"] if isinstance(fact["evidence"], list) else [fact["evidence"]]
        segs = [seg for e in by[fact["source_id"]] for seg in e.page_segments(fact["page"])]
        assert any(ex.find_parts_in_order(parts, seg) for seg in segs), (name, fact["page"], parts)


def test_drv8871_formula_matches_the_datasheet_example():
    f, e = ndrive.FACTS["drv8871.v_ilim"], ndrive.FACTS["drv8871.example"]
    assert f["value"] / e["r_ilim"] == pytest.approx(e["value"])


# --- generic rules per part: supply and levels ------------------------------------------------------------------------
@pytest.mark.parametrize("part, conn, expect", [
    ("tpl7407l", {"COM": "V12", "GND": "GND"}, ("passed", None)),
    ("tpl7407l", {"COM": "5V", "GND": "GND"}, ("failed", "caution")),     # below 8.5 V (full drive)
    ("tpl7407l", {"COM": "V45", "GND": "GND"}, ("failed", "danger")),     # above 42 V absolute
    ("drv8871", {"VM": "V24"}, ("passed", None)),
    ("drv8871", {"VM": "5V"}, ("failed", "caution")),                     # below 6.5 V
    ("drv8871", {"VM": "V55"}, ("failed", "danger")),                     # above 50 V absolute
    ("tmc2208", {"VS": "V24", "VCC_IO": "3V3"}, ("passed", None)),
    ("tmc2208", {"VS": "V40", "VCC_IO": "3V3"}, ("failed", "danger")),    # above 39 V absolute
    ("tmc2208", {"VS": "5V", "VCC_IO": "3V3"}, ("failed", "caution")),    # below 5.5 V (internal regulator)
])
def test_supply_range(part, conn, expect):
    rep = report(mod("U1", part, conn), only=("mod.supply_range",))
    got = sorted((f.status, f.severity) for f in findings(rep, "mod.supply_range"))
    assert expect in got, got


def test_tpl7407l_and_drv8871_accept_3v3_logic():
    rep = report(mod("U1", "tpl7407l", {"IN1": "GPIO4", "COM": "V12", "GND": "GND", "OUT1": "C1"}),
                 mod("U2", "drv8871", {**DRV, "IN1": "GPIO5", "IN2": "GPIO6"}),
                 assignments=[assign("out", 4), assign("pwm", 5), assign("pwm", 6)], only=("mod.level_in",))
    assert {(f.status, f.severity) for f in findings(rep, "mod.level_in")} == {("passed", None)}


@pytest.mark.parametrize("vio, expect", [("3V3", {("passed", None)}), ("5V", {("failed", "caution")})])
def test_tmc2208_inputs_follow_vcc_io(vio, expect):
    rep = report(mod("U1", "tmc2208", {"STEP": "GPIO4", "DIR": "GPIO5", "VS": "V24", "VCC_IO": vio, "GND": "GND"}),
                 assignments=[assign("out", 4), assign("out", 5)], only=("mod.level_in",))
    assert {(f.status, f.severity) for f in findings(rep, "mod.level_in")} == expect


def test_tmc2208_ms_pins_default_to_the_pull_downs():
    rep = report(mod("U1", "tmc2208", {"STEP": "GPIO4", "DIR": "GPIO5", "ENN": "GND", "VS": "V24",
                                       "VCC_IO": "3V3", "GND": "GND"}),
                 assignments=[assign("out", 4), assign("out", 5)], only=("mod.unconnected",))
    assert not any("MS1" in f.message or "MS2" in f.message for f in findings(rep, "mod.unconnected"))


def test_drv8871_requires_bulk_and_decoupling_on_vm():
    rep = report(mod("U1", "drv8871", DRV), only=("mod.required_parts",))
    fs = findings(rep, "mod.required_parts", "failed")
    assert {f.severity for f in fs} == {"caution"} and len(fs) == 2


# --- mod.ndrive.drv8871_ilim ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("ilim, parts_, expect, text", [
    (None, [], ("failed", "caution"), "ILIM open"),
    ("GND", [], ("failed", "caution"), "0 Ω"),
    ("ILIM", [], ("failed", "caution"), "no resistor from ILIM"),
    ("ILIM", [res("R1", "10k", "ILIM")], ("failed", "caution"), "below the minimum allowed 15.0 kΩ"),
    ("ILIM", [res("R1", "32k", "ILIM")], ("passed", None), "2.00 A typ"),
    ("ILIM", [res("R1", "60k", "ILIM"), res("R2", "60k", "GND", "ILIM")], ("passed", None), "30.0 kΩ"),
    ("ILIM", [res("R1", "15k", "ILIM")], ("passed", None), "4.27 A typ"),
    ("ILIM", [res("R1", "lots", "ILIM")], ("not_checked", "info"), "unreadable"),
])
def test_drv8871_ilim(ilim, parts_, expect, text):
    conn = dict(DRV, **({"ILIM": ilim} if ilim else {}))
    rep = report(mod("U1", "drv8871", conn), *parts_, only=(ndrive.ILIM_RULE,))
    f = one(rep, ndrive.ILIM_RULE)
    assert (f.status, f.severity) == expect and text in f.message, f.message
    assert f.source_ids == ["mod-ndrive-drv8871-ds"]


def test_drv8871_ilim_spread_from_v_ilim():
    rep = report(mod("U1", "drv8871", dict(DRV, ILIM="ILIM")), res("R1", "32k", "ILIM"), only=(ndrive.ILIM_RULE,))
    assert "1.84 A–2.16 A" in one(rep, ndrive.ILIM_RULE).message


def test_drv8871_board_without_resistor_is_info():
    rep = report(mod("U1", "drv8871", DRV, variant="board"), only=(ndrive.ILIM_RULE,))
    f = one(rep, ndrive.ILIM_RULE)
    assert (f.status, f.severity) == ("failed", "info") and "unverified" in f.message


# --- mod.ndrive.tpl7407l_com ------------------------------------------------------------------------------------------
TPL = {"IN1": "GPIO4", "GND": "GND", "OUT1": "C1"}


def tpl_report(com, *parts_, extra=None):
    conn = dict(TPL, COM=com, **(extra or {}))
    return report(mod("U1", "tpl7407l", conn), *parts_, assignments=[assign("out", 4)], only=(ndrive.COM_RULE,))


def test_tpl7407l_com_on_the_load_rail_passes():
    f = one(tpl_report("V12", res("M1", "coil", "C1", "V12", kind="motor")), ndrive.COM_RULE)
    assert f.status == "passed"


def test_tpl7407l_com_below_a_load_rail_is_caution():
    fs = findings(tpl_report("V12", res("M1", "coil", "C1", "V24", kind="motor")), ndrive.COM_RULE)
    assert [(f.status, f.severity) for f in fs] == [("failed", "caution")]
    assert "highest load voltage" in fs[0].message and "M1" in fs[0].refs


def test_tpl7407l_com_at_5v_is_reduced_drive_info():
    fs = findings(tpl_report("5V", res("M1", "coil", "C1", "5V", kind="motor")), ndrive.COM_RULE)
    assert [(f.status, f.severity) for f in fs] == [("failed", "info")]
    assert "reduced gate drive" in fs[0].message


def test_tpl7407l_com_unknown_is_not_checked():
    assert one(tpl_report("VCOIL"), ndrive.COM_RULE).status == "not_checked"


def test_tpl7407l_out7_load_without_diode_is_info():
    load = res("K1", "coil", "C7", "V12", kind="relay")
    fs = findings(tpl_report("V12", load, extra={"OUT7": "C7"}), ndrive.COM_RULE, "failed")
    assert [(f.severity, "OUT7" in f.message) for f in fs] == [("info", True)]
    diode = mod("D1", "ss14", {"A": "C7", "K": "V12"})
    assert findings(tpl_report("V12", load, diode, extra={"OUT7": "C7"}), ndrive.COM_RULE, "failed") == []


def test_tpl7407l_com_open_is_left_to_unconnected():
    rep = report(mod("U1", "tpl7407l", TPL), assignments=[assign("out", 4)],
                 only=(ndrive.COM_RULE, "mod.unconnected"))
    assert findings(rep, ndrive.COM_RULE) == []
    assert any("COM" in f.message for f in findings(rep, "mod.unconnected", "failed"))


# --- mod.ndrive.diode_reverse -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("part, variant, conn, expect", [
    ("bat54", None, {"A": "GND", "K": "V36"}, ("failed", "danger")),       # 36 V > 30 V
    ("bat54", None, {"A": "GND", "K": "V24"}, ("passed", None)),
    ("ss14", None, {"A": "GND", "K": "V36"}, ("passed", None)),            # 36 V < 40 V
    ("ss14", None, {"A": "GND", "K": "V45"}, ("failed", "danger")),
    ("ss14", None, {"A": "5V", "K": "3V3"}, ("failed", "caution")),        # conducts between two rails
    ("bat54", "s", {"A1": "GND", "CT": "V12", "K2": "V36"}, ("passed", None)),
    ("bat54", "c", {"A1": "GND", "A2": "3V3", "K": "V36"}, ("failed", "danger")),
])
def test_diode_reverse(part, variant, conn, expect):
    rep = report(mod("D1", part, conn, variant=variant), only=(ndrive.DIODE_RULE,))
    got = {(f.status, f.severity) for f in findings(rep, ndrive.DIODE_RULE)}
    assert got == {expect}, [f.message for f in findings(rep, ndrive.DIODE_RULE)]


def test_diode_on_signal_nets_is_not_checked_at_all():
    rep = report(mod("D1", "bat54", {"A": "GPIO4", "K": "SIG"}), only=(ndrive.DIODE_RULE,))
    assert findings(rep, ndrive.DIODE_RULE) == []


def test_ss14_counts_as_relay_flyback_diode():
    relay = mod("K1", "srd_05vdc_sl_c", {"COIL1": "5V", "COIL2": "KC"})
    rep = report(relay, mod("D1", "ss14", {"A": "KC", "K": "5V"}), only=("mod.switch.relay_flyback",))
    assert {f.status for f in findings(rep, "mod.switch.relay_flyback")} == {"passed"}


# --- data corrections ------------------------------------------------------------------------------------------------
def test_tmc2208_v_in_max_is_vio_plus_half_a_volt():
    v = modules.catalog().get("tmc2208")["io"]["v_in_max"]
    assert (v["rel_offset"], v["of"], v["page"]) == (0.5, "VCC_IO", 68)
