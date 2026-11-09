"""Module family switch: PC817, 6N137, SRD-05VDC-SL-C, G5LE, 1N4148, 1N4007, 1N5819; family rules
mod.switch.*; calculator opto.

Synthetic projects only. Expected values are recomputed by hand in the comments from the datasheet numbers (Sharp
OP18002EN, Vishay 84732/81857/88503/88525, Songle SRD, Omron G5LE and relay precautions; quoted in
tests/corpus/excerpts/mod-switch-*).
"""
from __future__ import annotations

import pytest

import excerpts as ex
import mod_fixtures as mf
import modkit as mk
from circuit_bench.bench_core import calckit, electrical, modules, pins
from circuit_bench.bench_core.calcs import opto
from circuit_bench.bench_core.modrules import switch as sw

PARTS = ("pc817", "6n137", "srd_05vdc_sl_c", "g5le", "1n4148", "1n4007", "1n5819")
ESP = electrical.get("esp32s3")  # ioh 40 mA, iol 28 mA (typical, Table 5-4)


def _relay(ref="K1", module="srd_05vdc_sl_c", variant=None, **conn):
    base = {"COIL1": "5V", "COIL2": "RLY_DRV", "COM": "LOAD", "NO": "LOAD_SW"}
    base.update(conn)
    return mk.mod(ref, module, {k: v for k, v in base.items() if v is not None}, variant=variant)


def _diode(ref="D1", a="RLY_DRV", k="5V", kind="diode"):
    return {"ref": ref, "kind": kind, "value": "1N4148", "conn": {"A": a, "K": k}}


def _run(parts, assignments=(), only=None, **kw):
    return mk.run(assignments=assignments, parts=parts, only=only, **kw)


def _one(rep, rule):
    fs = mk.findings(rep, rule)
    assert len(fs) == 1, fs
    return fs[0]


def _calc(**params):
    env = calckit.run("opto", params)
    assert env["ok"], env.get("error")
    return env


def _status(env, name):
    return next(c["status"] for c in env["checks"] if c["id"] == f"calc.opto.{name}")


def _codes(env):
    return {w["code"]: w["severity"] for w in env["warnings"]}


# --- catalog ---------------------------------------------------------------------------------------------------------
def test_entries_load_without_problems():
    modules.clear_cache()
    cat = modules.catalog()
    assert cat.problems == []
    assert "switch" in cat.families()
    for mid in PARTS:
        e = cat.get(mid)
        assert e["_wp"] == "switch" and e["_class"] in ("A", "A1"), mid
    assert {cat.get(m)["category"] for m in PARTS} == {"isolation.opto", "switch.relay", "discrete.diode"}
    assert cat.resolve_id("srd-05vdc-sl-c") == "srd_05vdc_sl_c"


@pytest.mark.parametrize("mid,amps", [("srd_05vdc_sl_c", 0.0714), ("g5le", 0.0794)])
def test_relays_carry_mains_hazard_flyback_and_coil_current(mid, amps):
    e = modules.catalog().get(mid)
    assert [h["code"] for h in e["hazards"]] == ["mains"]
    assert e["hazards"][0]["text"] == ("Keep the contact side at 60 V DC or less (Circuit Bench is low voltage "
                                       "only); never switch mains.")
    assert [r["code"] for r in e["requires"]] == ["flyback"]
    assert e["current"]["typ"]["value"] == amps


def test_g5le_variants_carry_their_coil_current():
    cat = modules.catalog()
    assert cat.get("g5le", "dc12")["current"]["typ"]["value"] == 0.0333  # 33.3 mA at 12 VDC
    assert cat.get("g5le", "dc24")["current"]["typ"]["value"] == 0.0167  # 16.7 mA at 24 VDC


def test_6n137_requires_decoupling_and_pullup():
    e = modules.catalog().get("6n137")
    assert {r["code"] for r in e["requires"]} == {"decoupling", "pullup"}
    assert e["io"]["outputs"] == "open_drain"


# --- generic rules on the real entries -------------------------------------------------------------------------------
def _6n137(vcc):
    return mk.mod("U2", "6n137", {"VCC": vcc, "GND": "GND", "VO": "GPIO4", "ANODE": "LED_A", "CATHODE": "GND"})


def test_6n137_on_5v_is_in_range():
    rep = _run([_6n137("5V")], [mk.assign("in", 4)], only=("mod.supply_range",))
    assert _one(rep, "mod.supply_range").status == "passed"


def test_6n137_on_3v3_is_below_its_supply_range():
    f = _one(_run([_6n137("3V3")], [mk.assign("in", 4)], only=("mod.supply_range",)), "mod.supply_range")
    assert (f.status, f.severity) == ("failed", "caution")  # 3.3 V < VCC min 4.5 V (p. 3)


def test_6n137_above_abs_max_is_danger():
    rep = _run([_6n137("V8")], [mk.assign("in", 4)], only=("mod.supply_range",), options={"rails": {"V8": 8.0}})
    f = _one(rep, "mod.supply_range")
    assert (f.status, f.severity) == ("failed", "danger")  # 8 V > 7 V abs max (p. 2)


# --- mod.switch.relay_needs_driver ---------------------------------------------------------------------------------
def test_srd_coil_sunk_by_a_gpio_is_danger():
    # 71.4 mA coil current (Songle coil table, 05 row) > 28 mA typical IOL of the ESP32-S3
    rep = _run([_relay(COIL2="GPIO5")], [mk.assign("out", 5)], only=(sw.DRIVER,))
    f = _one(rep, sw.DRIVER)
    assert (f.status, f.severity) == ("failed", "danger")
    assert "71.4 mA" in f.message and "IOL" in f.message
    assert "GPIO5" in f.refs and "mod-switch-srd-ds" in f.source_ids
    assert "mod_switch_relay_needs_driver" in mk.codes(rep)


def test_g5le_coil_sourced_by_a_gpio_is_danger():
    # coil between GPIO and GND: the pin sources 79.4 mA > IOH 40 mA
    rep = _run([_relay(module="g5le", COIL1="GPIO6", COIL2="GND")], [mk.assign("out", 6)], only=(sw.DRIVER,))
    f = _one(rep, sw.DRIVER)
    assert (f.status, f.severity) == ("failed", "danger") and "IOH" in f.message


def test_small_coil_on_a_gpio_is_still_caution():
    # G5LE DC24: 16.7 mA ≤ 40 mA IOH, but the coil spike still hits the pin
    rep = _run([_relay(module="g5le", variant="dc24", COIL1="GPIO6", COIL2="GND")], [mk.assign("out", 6)],
               only=(sw.DRIVER,))
    f = _one(rep, sw.DRIVER)
    assert (f.status, f.severity) == ("failed", "caution")


def test_coil_behind_a_driver_passes():
    rep = _run([_relay()], [mk.assign("out", 5, net="RLY_BASE")], only=(sw.DRIVER,))
    assert _one(rep, sw.DRIVER).status == "passed"


def test_coil_without_current_data_is_not_checked():
    relay = {"id": "tst_relay", "title": "TST relay", "category": "switch.relay", "manufacturer": "TST", "kind": "ic",
             "source_ids": ["tst-sensor-ds"], "pins": [{"name": n, "signal": "power_out"} for n in sw.COIL_PINS]}
    rep = mk.run(catalog=mf.catalog(relay), electrical=mf.ESP, parts=[mk.mod("K9", "tst_relay", {"COIL1": "5V", "COIL2": "GPIO5"})],
                 assignments=[mk.assign("out", 5)], only=(sw.DRIVER,))
    assert _one(rep, sw.DRIVER).status == "not_checked"


def test_coil_without_esp_values_is_not_checked():
    esp = {k: v for k, v in mf.ESP.items() if k not in ("ioh", "iol")}
    rep = mk.run(electrical=esp, parts=[_relay(COIL2="GPIO5")], assignments=[mk.assign("out", 5)], only=(sw.DRIVER,))
    assert _one(rep, sw.DRIVER).status == "not_checked"


# --- mod.switch.relay_flyback ----------------------------------------------------------------------------------------
def test_relay_without_diode_is_caution():
    f = _one(_run([_relay()], only=(sw.FLYBACK,)), sw.FLYBACK)
    assert (f.status, f.severity) == ("failed", "caution")
    assert f.source_ids == [sw.PRECAUTIONS_SRC]


@pytest.mark.parametrize("kind", ["diode", "schottky", "rectifier"])
def test_plain_diode_across_the_coil_passes(kind):
    rep = _run([_relay(), _diode(kind=kind)], only=(sw.FLYBACK,))
    f = _one(rep, sw.FLYBACK)
    assert f.status == "passed" and "D1" in f.refs


@pytest.mark.parametrize("mid", ["1n4148", "1n4007", "1n5819"])
def test_catalog_diode_across_the_coil_passes(mid):
    rep = _run([_relay(), mk.mod("D2", mid, {"A": "RLY_DRV", "K": "5V"})], only=(sw.FLYBACK,))
    assert _one(rep, sw.FLYBACK).status == "passed"


def test_reversed_diode_is_caution():
    f = _one(_run([_relay(), _diode(a="5V", k="RLY_DRV")], only=(sw.FLYBACK,)), sw.FLYBACK)
    assert (f.status, f.severity) == ("failed", "caution") and "reversed" in f.message


def test_diode_on_one_coil_net_only_does_not_count():
    f = _one(_run([_relay(), _diode(a="RLY_DRV", k="12V")], only=(sw.FLYBACK,)), sw.FLYBACK)
    assert f.status == "failed"


def test_resistor_across_the_coil_is_no_diode():
    r = {"ref": "R1", "kind": "resistor", "value": "1k", "conn": {"1": "RLY_DRV", "2": "5V"}}
    assert _one(_run([_relay(), r], only=(sw.FLYBACK,)), sw.FLYBACK).status == "failed"


def test_open_coil_is_not_checked():
    f = _one(_run([_relay(COIL2=None)], only=(sw.FLYBACK,)), sw.FLYBACK)
    assert f.status == "not_checked"


# --- mod.switch.relay_mains -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("net", ["230VAC_L", "MAINS_L", "L", "AC_N", "120V", "LINE"])
def test_contacts_on_a_mains_net_are_danger(net):
    f = _one(_run([_relay(COM=net)], only=(sw.MAINS,)), sw.MAINS)
    assert (f.status, f.severity) == ("failed", "danger")
    assert sw.MAINS_TEXT in f.message


def test_mains_option_is_danger():
    f = _one(_run([_relay()], only=(sw.MAINS,), options={"mains": True}), sw.MAINS)
    assert (f.status, f.severity) == ("failed", "danger") and "options.mains" in f.message


def test_mains_fact_is_danger():
    part = _relay()
    part["facts"] = {"mains": True}
    f = _one(_run([part], only=(sw.MAINS,)), sw.MAINS)
    assert (f.status, f.severity) == ("failed", "danger")


@pytest.mark.parametrize("net", ["LOAD", "12V", "LED_STRIP", "V24", "LEVEL", "LAMP"])
def test_low_voltage_contacts_pass(net):
    f = _one(_run([_relay(COM=net)], only=(sw.MAINS,), options={"rails": {"12V": 12.0, "V24": 24.0}}), sw.MAINS)
    assert f.status == "passed"


def test_mains_finding_is_never_capped_by_the_source_class():
    # B-class relay entry: data findings would be capped to info, the mains finding is not
    relay = {"id": "tst_brelay", "title": "TST relay board", "category": "switch.relay", "manufacturer": "TST",
             "kind": "module", "source_ids": ["tst-bsensor-shop"],
             "pins": [{"name": n, "signal": "power_out"} for n in ("COIL1", "COIL2", "COM", "NO")]}
    rep = mk.run(catalog=mf.catalog(relay), electrical=mf.ESP, only=(sw.MAINS,),
                 parts=[mk.mod("K5", "tst_brelay", {"COIL1": "5V", "COIL2": "X", "COM": "230V_L"})])
    assert _one(rep, sw.MAINS).severity == "danger"


def test_no_relay_no_findings():
    rep = _run([mk.mod("U1", "pc817", {"ANODE": "GPIO4", "CATHODE": "GND", "COLLECTOR": "GPIO5", "EMITTER": "GND"})],
               [mk.assign("out", 4), mk.assign("in_pullup", 5)], only=(sw.DRIVER, sw.FLYBACK, sw.MAINS))
    assert mk.findings(rep) == []


def test_pins_check_end_to_end():
    parts = [{"ref": "K1", "kind": "relay", "value": "SRD-05VDC-SL-C", "module": "srd_05vdc_sl_c",
              "conn": {"COIL1": "5V", "COIL2": "GPIO5", "COM": "230V_L", "NO": "LAMP"}}]
    env = pins.check("esp32s3", [{"role": "RELAY", "mode": "out", "pin": 5}], parts=parts, options={})
    assert env["ok"], env.get("error")
    codes = {w["code"]: w["severity"] for w in env["warnings"]}
    assert codes.get("mod_switch_relay_needs_driver") == "danger"
    assert codes.get("mod_switch_relay_mains") == "danger"
    assert codes.get("mod_switch_relay_flyback") == "caution"


# --- calculator opto ----------------------------------------------------------------------------------------------
def test_pc817_from_3v3_datasheet_values():
    env = _calc(part="pc817", v_drive=3.3)
    r = env["result"]
    # R = (3.3 − 1.4 VF_max) / 5 mA = 380 Ω -> E12 down 330 Ω; I_F,min = 1.9/330 = 5.76 mA; I_F,high = 2.1/330 = 6.36 mA
    assert r["r_exact"]["value"] == pytest.approx(380.0)
    assert r["r_led"]["value"] == 330.0
    assert r["i_f_min"]["value"] == pytest.approx(1.9 / 330, rel=1e-5)
    assert r["i_f_high"]["value"] == pytest.approx(2.1 / 330, rel=1e-5)
    # pull-up: (3.3 − 0.2) / (2.5 mA / 2) = 2.48 kΩ -> 2.7 kΩ; I_pu = 3.1/2700 = 1.15 mA ≤ 2.5 mA
    assert r["r_pullup"]["value"] == 2700.0
    assert r["i_pullup"]["value"] == pytest.approx(3.1 / 2700, rel=1e-5)
    assert _status(env, "output_low") == "passed" and _status(env, "if_abs_max") == "passed"
    assert {s["id"] for s in env["sources"]} >= {opto.PC_SRC, "rule-of-thumb"}


def test_pc817_strong_pullup_does_not_pull_low():
    env = _calc(part="pc817", v_drive=5, v_pullup=5, r_pullup=1000)  # 4.8 mA > 2.5 mA I_C,min
    assert _status(env, "output_low") == "failed"
    assert _codes(env)["opto_output_not_low"] == "caution"


def test_pc817_below_the_ctr_test_current_is_not_checked():
    env = _calc(part="pc817", v_drive=5, i_f="2mA")
    assert _status(env, "output_low") == "not_checked"
    assert _codes(env)["opto_ctr_not_guaranteed"] == "info"


def test_pc817_small_resistor_exceeds_abs_max():
    env = _calc(part="pc817", v_drive=5, r_led=22)  # (5 − 1.2)/22 = 173 mA > 50 mA
    assert _status(env, "if_abs_max") == "failed"
    assert _codes(env)["opto_if_over_abs_max"] == "danger"


def test_pc817_gpio_current_against_ioh():
    env = _calc(part="pc817", v_drive=3.3, r_led=39, chip="esp32s3")  # (3.3 − 1.2)/39 = 53.8 mA > 40 mA (and > 50 mA)
    assert _codes(env)["gpio_current"] == "caution"


def test_pc817_no_headroom():
    env = _calc(part="pc817", v_drive=1.3)
    assert _status(env, "headroom") == "failed" and env["result"]["r_led"] is None


def test_6n137_from_5v_datasheet_values():
    env = _calc(part="6n137", v_drive=5, chip="esp32s3")
    r = env["result"]
    # R = (5 − 1.7) / 7.5 mA = 440 Ω -> 390 Ω; I_F 3.3/390 = 8.46 mA … (5 − 1.1)/390 = 10.0 mA, inside IFH 5–15 mA
    assert r["r_led"]["value"] == 390.0
    assert r["i_f_min"]["value"] == pytest.approx(3.3 / 390, rel=1e-5)
    assert r["i_f_high"]["value"] == pytest.approx(3.9 / 390, rel=1e-5)
    # RL ≥ max(330 Ω, (5 − 0.6)/13 mA = 338 Ω) -> 390 Ω (E12)
    assert r["r_pullup"]["value"] == 390.0
    assert all(_status(env, c) == "passed" for c in ("vcc", "ifh", "rl_range", "output_low"))
    assert _codes(env)["opto_output_level"] == "danger"  # 5 V output > 3.6 V ESP32-S3 input max


def test_6n137_at_3v3_is_outside_vcc():
    env = _calc(part="6n137", v_drive=3.3, v_pullup=3.3)
    assert _status(env, "vcc") == "failed" and _codes(env)["opto_vcc_range"] == "caution"


def test_6n137_rl_outside_the_recommended_range():
    env = _calc(part="6n137", v_drive=5, r_pullup="10k")
    assert _status(env, "rl_range") == "failed"


def test_6n137_led_current_outside_ifh():
    env = _calc(part="6n137", v_drive=5, r_led="1k")  # 3.3 mA … 3.9 mA < 5 mA IFH min
    assert _status(env, "ifh") == "failed"


@pytest.mark.parametrize("params", [
    {"part": "pc123", "v_drive": 3.3},
    {"part": "pc817", "v_drive": 0},
    {"part": "pc817", "v_drive": 3.3, "series": "E7"},
    {"part": "pc817", "v_drive": 3.3, "chip": "nochip"},
    {"part": "pc817"},
])
def test_opto_bad_input(params):
    env = calckit.run("opto", params)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args", params


def test_opto_refuses_high_voltage():
    env = calckit.run("opto", {"part": "pc817", "v_drive": 5, "v_pullup": 230})
    assert env["ok"] is False and "low_voltage_only" in {w["code"] for w in env["warnings"]}


def test_opto_is_registered_in_group_drive():
    meta = {m["kind"]: m for m in calckit.meta()}
    assert meta["opto"]["group"] == "drive"
    assert calckit.problems() == []


# --- every calculator fact is quoted in the pinned excerpt ----------------------------------------------------------
def _calc_facts():
    for part, facts in opto.FACTS.items():
        for key, f in facts.items():
            yield f"{part}.{key}", f


@pytest.mark.parametrize("name,fact", list(_calc_facts()), ids=lambda x: x if isinstance(x, str) else "")
def test_calculator_fact_is_in_the_excerpt(name, fact):
    by = ex.by_source("mod-switch-*.txt")
    assert fact["source_id"] in by, name
    parts = fact["evidence"] if isinstance(fact["evidence"], list) else [fact["evidence"]]
    segs = [seg for e in by[fact["source_id"]] for seg in e.page_segments(fact["page"])]
    assert any(ex.find_parts_in_order(parts, seg) for seg in segs), (name, fact["page"], parts)


def test_rule_flyback_quote_is_in_the_excerpt():
    by = ex.by_source("mod-switch-*.txt")
    segs = [seg for e in by[sw.PRECAUTIONS_SRC] for seg in e.page_segments(9)]
    assert any(ex.find_parts_in_order(["install surge absorbing circuits at both ends of", "the coil"], s) for s in segs)


# --- one cause, one warning -------------------------------------------------------------------------------------------
def _srd(conn, ref="K1"):
    return {"ref": ref, "kind": "relay", "value": "SRD-05VDC-SL-C", "module": "srd_05vdc_sl_c", "conn": conn}


def test_relay_flyback_covers_the_generic_required_parts_finding():
    parts = [_srd({"COIL1": "RLY", "COIL2": "GND"})]
    rep = _run(parts, assignments=[mk.assign("out", 15, "RLY")], only=(sw.FLYBACK, sw.REQUIRED_PARTS))
    f = _one(rep, sw.FLYBACK)
    assert f.status == "failed" and f.supersedes == (sw.REQUIRED_PARTS,)
    hard = [w["code"] for w in rep.warnings if w["severity"] in ("caution", "danger")]
    assert hard == ["mod_switch_relay_flyback"]


def test_contacts_on_a_12v_rail_drop_the_mains_notice_to_info():
    parts = [_srd({"COIL1": "5V", "COIL2": "RLY_DRV", "COM": "12V", "NO": "LOAD"})]
    rep = _run(parts, only=(sw.MAINS, sw.HAZARD), options={"rails": {"12V": 12.0}})
    f = _one(rep, sw.MAINS)
    assert f.status == "passed" and f.supersedes == (sw.HAZARD,) and "12V = 12.0 V" in f.message
    assert [(w["code"], w["severity"]) for w in rep.warnings] == [("mod_hazard", "info")]


def test_contacts_on_unknown_nets_keep_the_mains_notice():
    parts = [_srd({"COIL1": "5V", "COIL2": "RLY_DRV", "COM": "LOADP", "NO": "LOAD"})]
    rep = _run(parts, only=(sw.MAINS, sw.HAZARD))
    assert _one(rep, sw.MAINS).supersedes == ()
    assert [(w["code"], w["severity"]) for w in rep.warnings] == [("mod_hazard", "danger")]  # safety notice stays
