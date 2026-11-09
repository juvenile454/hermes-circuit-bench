"""Module engine: net model, buses and segments, address selection, rails,
rule register with auto-discovery, severity caps, reference rules, pins.check hook, compactness.
Synthetic data only (tests/mod_fixtures.py)."""
from __future__ import annotations

import json
import sys

import mod_fixtures as fx
import modkit as k
import pytest

from circuit_bench.bench_core import contracts, modcheck, modrules, modspec, pins

BUS = k.i2c()  # SDA0 on GPIO8, SCL0 on GPIO9
I2C = {"SDA": "SDA0", "SCL": "SCL0"}


def ctx(parts, assignments=BUS, options=None, catalog=None, electrical=fx.ESP, devkit=None):
    return modcheck.build_ctx(chip="esp32s3", assignments=assignments, parts=parts, options=options,
                              devkit=devkit, catalog=catalog or fx.catalog(), electrical=electrical)


def run(parts, assignments=BUS, options=None, catalog=None, electrical=fx.ESP, **kw):
    return k.run(catalog=catalog or fx.catalog(), electrical=electrical, assignments=assignments, parts=parts,
                 options=options, **kw)


def sensor(ref="U1", **conn):
    return k.mod(ref, "tst_sensor", {**I2C, "VDD": "3V3", "SDO": "GND", **conn})


# --- net model --------------------------------------------------------------------------------------------------------
def test_conn_and_ties_resolve_to_nets():
    c = ctx([k.mod("U1", "tst_sensor", {"SDA": "GPIO8", "SCL": "GPIO9", "VDD": "3V3", "SDO": "VDDIO"}),
             k.mod("U2", "tst_oled", {"SDA": "GPIO21", "SCL": "SCLX", "VDD": "VAUX"})],
            options={"rails": {"VAUX": 3.0}})
    u1 = c.instance("U1")
    assert u1.conn["SDA"] == "SDA0" and u1.conn["SCL"] == "SCL0"  # GPIO<n> = net of the assignment on n
    assert u1.conn["VDDIO"] == "3V3"  # tie "VDD" = the net of the own VDD pin
    assert u1.conn["CSB"] == "3V3"  # tie "VDDIO" -> VDDIO -> VDD
    assert u1.conn["SDO"] == "3V3" and u1.conn["GND"] == "GND"
    u2 = c.instance("U2")
    assert u2.conn["SDA"] == "GPIO21"  # no assignment on 21: the net keeps the name
    assert u2.conn["SA0"] == "GND" and u2.conn["SCL"] == "SCLX"
    assert c.volts("VAUX") == 3.0 and c.volts("3V3") == 3.3 and c.volts("SDA0") is None
    assert c.supply_volts(u2) == {"VDD": 3.0}
    assert c.nets["SDA0"]["gpios"] == [8] and c.nets["SDA0"]["modes"] == ["i2c_sda"]
    assert ("U1", "SDA") in c.nets["SDA0"]["pins"]
    assert c.rails == {"GND": 0.0, "3V3": 3.3, "5V": 5.0, "VAUX": 3.0}


def test_supply_without_conn_or_tie_is_open_and_vddio_follows():
    c = ctx([k.mod("U1", "tst_sensor", {**I2C})])
    u = c.instance("U1")
    assert "VDD" not in u.conn and "VDDIO" not in u.conn and "CSB" not in u.conn
    assert c.supply_volts(u) == {}


def test_assignment_without_net_sits_on_gpio_net_and_plain_parts_join_nets():
    parts = [k.mod("U1", "tst_5v_display", {"VCC": "5V", "DIN": "GPIO4"}),
             {"ref": "R1", "kind": "resistor", "value": "10k", "conn": {"1": "GPIO4", "2": "3V3"}}]
    c = ctx(parts, assignments=[k.assign("out", 4)])
    assert c.assignments == [{"role": None, "mode": "out", "pin": 4, "net": "GPIO4"}]
    assert c.instance("U1").conn["DIN"] == "GPIO4"
    assert ("R1", "1") in c.nets["GPIO4"]["pins"] and ("R1", "2") in c.nets["3V3"]["pins"]
    assert [i.ref for i in c.instances] == ["U1"]


def test_options_rails_cannot_override_fixed_rails_or_exceed_low_voltage():
    c = ctx([sensor()], options={"rails": {"3V3": 3.0, "HV": 230, "VBAT": 3.7, "BAD": "x"}})
    assert c.rails == {"GND": 0.0, "3V3": 3.3, "5V": 5.0, "VBAT": 3.7}


def test_no_module_instance_means_no_ctx_and_no_report():
    assert ctx([{"ref": "R1", "kind": "resistor", "value": "1k"}]) is None
    assert run([]) is None
    assert run([{"ref": "R1", "kind": "resistor", "value": "1k", "conn": {"1": "3V3"}}]) is None


# --- buses and segments -----------------------------------------------------------------------------------------------
def test_bus_from_assignments_with_devices_and_gpios():
    c = ctx([sensor(), k.mod("U2", "tst_oled", {**I2C, "VDD": "3V3"}),
             k.mod("U3", "tst_rtc", {"SDA": "OTHER", "SCL": "SCL0", "VCC": "5V"})])
    assert len(c.buses) == 1
    b = c.buses[0]
    assert b["id"] == "i2c:SDA0" and b["type"] == "i2c"
    assert b["gpios"] == {"SDA": 8, "SCL": 9} and b["nets"] == {"SDA": "SDA0", "SCL": "SCL0"}
    assert b["segments"] == [{"id": "main", "devices": [{"ref": "U1", "module": "tst_sensor", "address": "0x76"},
                                                        {"ref": "U2", "module": "tst_oled", "address": "0x3c"}]}]
    assert b["f_max_hz"] == 400000  # the slowest device with data
    assert "U3" not in c.placement and c.placement["U1"] == ("i2c:SDA0", "main")


def test_two_buses_pair_sda_with_scl():
    a = [*k.i2c(8, 9, "SDA0"), *k.i2c(4, 5, "SDA1")]
    c = ctx([sensor(), k.mod("U2", "tst_sensor", {"SDA": "SDA1", "SCL": "SCL1", "VDD": "3V3", "SDO": "GND"})],
            assignments=a)
    assert [(b["id"], b["gpios"]["SCL"], b["nets"]["SCL"]) for b in c.buses] == [("i2c:SDA0", 9, "SCL0"),
                                                                                 ("i2c:SDA1", 5, "SCL1")]
    assert c.placement["U2"] == ("i2c:SDA1", "main")


def _mux_project(extra=()):
    return [k.mod("M1", "tst_mux", {**I2C, "VCC": "3V3", "SD0": "CH0", "SC0": "CK0", "SD1": "CH1", "SC1": "CK1"}),
            k.mod("U1", "tst_sensor", {"SDA": "CH0", "SCL": "CK0", "VDD": "3V3", "SDO": "GND"}),
            k.mod("U2", "tst_sensor", {"SDA": "CH1", "SCL": "CK1", "VDD": "3V3", "SDO": "GND"}),
            *extra]


def test_mux_channels_open_segments_and_visibility():
    c = ctx(_mux_project([sensor("U3", SDO="VDDIO")]))
    segs = {s["id"]: s for s in c.buses[0]["segments"]}
    assert list(segs) == ["main", "M1.0", "M1.1"]
    assert [d["ref"] for d in segs["main"]["devices"]] == ["M1", "U3"]
    assert segs["M1.0"]["parent"] == "main" and [d["ref"] for d in segs["M1.0"]["devices"]] == ["U1"]
    assert c.placement["U2"] == ("i2c:SDA0", "M1.1")
    assert c.visible("main", "M1.0") and c.visible("M1.1", "main") and c.visible("M1.0", "M1.0")
    assert not c.visible("M1.0", "M1.1")


def test_nested_mux_segments_see_their_ancestors_only():
    parts = _mux_project([k.mod("M2", "tst_mux", {"SDA": "CH0", "SCL": "CK0", "VCC": "3V3", "A0": "3V3",
                                                    "SD2": "N2", "SC2": "NK2"}),
                          k.mod("U4", "tst_oled", {"SDA": "N2", "SCL": "NK2", "VDD": "3V3"})])
    c = ctx(parts)
    assert c.placement["U4"] == ("i2c:SDA0", "M2.2") and c.parents["M2.2"] == "M1.0"
    seg = "M2.2"
    assert c.visible(seg, "M1.0") and c.visible(seg, "main") and not c.visible(seg, "M1.1")
    assert c.instance("M2").address == "0x71"  # A0 to VCC's net


def test_address_conflict_across_mux_channels_is_none_but_same_channel_is_one():
    rep = run(_mux_project())
    assert "mod_address_conflict" not in k.codes(rep)  # U1/U2 both 0x76, on different channels
    rep = run(_mux_project([k.mod("U5", "tst_sensor", {"SDA": "CH1", "SCL": "CK1", "VDD": "3V3", "SDO": "GND"})]))
    w = k.by_rule(rep, "mod.address_conflict")[0]
    assert w["severity"] == "caution" and w["refs"] == ["U2", "U5"] and "segment M1.1" in w["message"]


# --- addresses ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("sdo", "options", "want", "origin"), [
    ("GND", None, "0x76", "select"),
    ("VDDIO", None, "0x77", "select"),  # map key = a pin name of the module -> that pin's net
    ("3V3", None, "0x77", "select"),  # the same net as VDDIO
    ("VB", {"rails": {"VB": 3.3}}, "0x77", "select"),  # another rail with the same voltage
    ("VB", {"rails": {"VB": 1.8}}, "0x76", "default"),  # no match: default
    ("SDA0", None, "0x76", "default"),  # select pin on a bus net, not in the map: default
    (None, None, "0x76", "default"),  # open
])
def test_address_from_select_pin(sdo, options, want, origin):
    conn = {**I2C, "VDD": "3V3"}
    if sdo:
        conn["SDO"] = sdo
    inst = ctx([k.mod("U1", "tst_sensor", conn)], options=options).instance("U1")
    assert (inst.address, inst.address_from) == (want, origin)


def test_select_map_key_naming_a_bus_pin():
    extra = {**fx.MODULES[2], "id": "tst_busaddr", "interfaces": [
        {"type": "i2c", "addresses": fx.F(["0x48", "0x49", "0x4a", "0x4b"], "bit"), "default": "0x48",
         "select": {"pin": "SA0", "map": {"GND": "0x48", "VDD": "0x49", "SDA": "0x4a", "SCL": "0x4b"}}}]}
    c = ctx([k.mod("U1", "tst_busaddr", {**I2C, "VDD": "3V3", "SA0": "SDA0"})], catalog=fx.catalog(extra))
    assert c.instance("U1").address == "0x4a"


def test_explicit_address_beats_select_and_none_without_i2c():
    c = ctx([k.mod("U1", "tst_sensor", {**I2C, "VDD": "3V3", "SDO": "GND"}, address="0x77"),
             k.mod("U2", "tst_5v_display", {"VCC": "5V"})])
    assert (c.instance("U1").address, c.instance("U1").address_from) == ("0x77", "explicit")
    assert (c.instance("U2").address, c.instance("U2").address_from) == (None, None)


# --- rule mod.address_conflict ------------------------------------------------------------------------------------
def test_address_conflict_found_with_sources_and_alternatives():
    rep = run([k.mod("U1", "tst_imu", {**I2C, "VDD": "3V3"}), k.mod("U2", "tst_rtc", {**I2C, "VCC": "5V"})])
    w = k.by_rule(rep, "mod.address_conflict")[0]
    assert w["severity"] == "caution" and w["refs"] == ["U1", "U2"]
    assert "0x68" in w["message"] and "bus i2c:SDA0" in w["message"]
    assert "U1: 0x69 (AD0 to VDD)" in w["message"]
    assert w["source_ids"] == ["tst-imu-ds", "tst-rtc-ds"]
    assert k.check_of(rep, "mod.address_conflict")["status"] == "failed"
    assert {"tst-imu-ds", "tst-rtc-ds"} <= set(rep.source_ids)


def test_no_conflict_when_select_pin_moves_one_device():
    rep = run([sensor("U1"), sensor("U2", SDO="VDDIO")])
    assert "mod_address_conflict" not in k.codes(rep)
    c = k.check_of(rep, "mod.address_conflict")
    assert c["status"] == "passed" and "0x76, 0x77" in c["detail"]


def test_address_conflict_without_alternatives_suggests_mux():
    rep = run([k.mod("U1", "tst_rtc", {**I2C, "VCC": "5V"}), k.mod("U2", "tst_rtc", {**I2C, "VCC": "5V"})])
    assert "behind an I²C mux" in k.by_rule(rep, "mod.address_conflict")[0]["message"]


def test_address_conflict_class_b_is_info():
    rep = run([k.mod("U1", "tst_bsensor", {**I2C, "VCC": "3V3"}), k.mod("U2", "tst_bsensor", {**I2C, "VCC": "3V3"})])
    w = k.by_rule(rep, "mod.address_conflict")[0]
    assert w["severity"] == "info" and "unverified" in w["message"].lower()
    assert k.check_of(rep, "mod.address_conflict")["status"] == "not_checked"


def test_no_bus_no_address_check():
    rep = run([k.mod("U1", "tst_5v_display", {"VCC": "5V"})], assignments=[k.assign("out", 4)])
    assert k.check_of(rep, "mod.address_conflict") is None


# --- severity caps ----------------------------------------------------------------------------------------------------
def _cap_ctx(kind, facts, cls):
    src = {"id": "tst-x", "title": "x", "url": "https://example.invalid/x", "retrieved": "2026-11-08", "class": cls}
    m = {**fx.MODULES[6], "id": "tst_x", "kind": kind, "source_ids": ["tst-x"]}
    cat = fx.FakeCatalog([m], sources={"tst-x": src})
    c = ctx([k.mod("U1", "tst_x", {**I2C, "VCC": "5V"}, facts=facts)], catalog=cat)
    return c, c.instance("U1")


@pytest.mark.parametrize("cls", ["A", "A1", "A2", "B"])
@pytest.mark.parametrize("kind", ["ic", "module"])
@pytest.mark.parametrize("regulator", [None, "none", "3V3", "unknown"])
def test_cap_matrix(cls, kind, regulator):
    c, inst = _cap_ctx(kind, {"regulator": regulator} if regulator else None, cls)
    if cls == "B":
        want_chip = want_supply = want_board = "info"
    elif kind == "ic" or regulator == "none":
        want_chip = want_supply = want_board = "danger"
    else:
        want_chip, want_supply, want_board = "caution", "info" if regulator == "3V3" else "caution", "danger"
    assert c.cap("danger", inst, "tst-x") == want_chip
    assert c.cap("danger", inst, "tst-x", supply=True) == want_supply
    assert c.cap("danger", inst, "tst-x", chip_fact=False) == want_board
    assert c.cap("info", inst, "tst-x") == "info"
    assert c.cap("caution", inst, "tst-x") == ("info" if cls == "B" else "caution")


def test_cap_uses_entry_class_without_source_id_and_unknown_class_is_b():
    c, inst = _cap_ctx("ic", None, "A2")
    assert c.cap("danger", inst) == "danger"
    c, inst = _cap_ctx("ic", None, "Z")
    assert c.cap("danger", inst, "tst-x") == "info"
    assert c.cap("danger", None) == "danger"  # engine findings without module data


def test_finding_helper_caps_with_the_weakest_instance_and_explains():
    c = ctx([k.mod("U1", "tst_rtc", {**I2C, "VCC": "5V"}), k.mod("U2", "tst_bsensor", {**I2C, "VCC": "3V3"})])
    f = c.finding("mod.x", "failed", "danger", "text.", [c.instance("U1"), c.instance("U2")],
                  source_id=["tst-rtc-ds", "tst-bsensor-shop"])
    assert f.severity == "info" and f.refs == ["U1", "U2"] and "class B" in f.message
    assert f.source_ids == ["tst-rtc-ds", "tst-bsensor-shop"]


# --- rule mod.supply_range ----------------------------------------------------------------------------------------
def _supply(parts, options=None):
    rep = run(parts, options=options, only=("mod.supply_range",))
    return rep, k.findings(rep, "mod.supply_range")


def test_supply_within_range_passes_with_source():
    rep, fs = _supply([sensor()])
    assert [f.status for f in fs] == ["passed", "passed"]  # VDD and VDDIO have different ranges
    assert fs[0].message.startswith("U1 (tst_sensor) VDD on 3V3 = 3.30 V") and fs[0].source_ids == ["tst-sensor-ds"]
    assert "1.71 V–3.60 V" in fs[0].message and "1.20 V–3.60 V" in fs[1].message
    assert k.check_of(rep, "mod.supply_range")["status"] == "passed" and rep.warnings == []


def test_supply_above_abs_max_is_danger():
    rep, fs = _supply([sensor(VDD="5V")])
    assert [(f.status, f.severity) for f in fs] == [("failed", "danger")]  # VDD and VDDIO tied: one finding
    assert "5.00 V exceeds the absolute maximum 4.25 V" in fs[0].message and fs[0].source_ids == ["tst-sensor-ds"]
    assert k.codes(rep) == {"mod_supply_range"}


def test_supply_outside_operating_range_is_caution():
    _, fs = _supply([k.mod("U1", "tst_rtc", {**I2C, "VCC": "3V3"})])
    assert (fs[0].severity, "below the operating range 4.50 V–5.50 V" in fs[0].message) == ("caution", True)
    _, fs = _supply([k.mod("U1", "tst_oled", {**I2C, "VDD": "VX"})], {"rails": {"VX": 3.6}})
    assert fs[0].severity == "caution" and "above" in fs[0].message


def test_supply_boundary_values_pass():
    _, fs = _supply([k.mod("U1", "tst_oled", {**I2C, "VDD": "VX"})], {"rails": {"VX": 3.3}})
    assert fs[0].status == "passed"


def test_supply_unknown_voltage_or_open_is_not_checked():
    rep, fs = _supply([sensor(VDD="VBAT"), k.mod("U2", "tst_rtc", {**I2C})])
    by_ref = {f.refs[0]: f for f in fs}
    assert by_ref["U1"].status == "not_checked" and by_ref["U1"].severity == "info"
    assert "unknown voltage" in by_ref["U1"].message
    assert by_ref["U2"].status == "not_checked" and by_ref["U2"].severity is None
    assert k.check_of(rep, "mod.supply_range")["status"] == "not_checked"


def test_breakout_at_5v_without_facts_is_capped_with_hint():
    _, fs = _supply([k.mod("U1", "tst_breakout", {**I2C, "VIN": "5V"})])
    assert fs[0].severity == "caution" and "confirm the breakout's regulator" in fs[0].message
    _, fs = _supply([k.mod("U1", "tst_breakout", {**I2C, "VIN": "5V"}, facts={"regulator": "none"})])
    assert fs[0].severity == "danger" and "regulator" not in fs[0].message
    _, fs = _supply([k.mod("U1", "tst_breakout", {**I2C, "VIN": "5V"}, facts={"regulator": "3V3"})])
    assert fs[0].severity == "info" and "3.3 V regulator" in fs[0].message


def test_supply_class_b_never_hard_and_variant_applies():
    _, fs = _supply([k.mod("U1", "tst_bsensor", {**I2C, "VCC": "5V"}, facts={"regulator": "none"})])
    assert fs[0].severity == "info" and "unverified" in fs[0].message.lower()
    _, fs = _supply([k.mod("U1", "tst_imu", {**I2C, "VDD": "3V3"}, variant="lv")])
    assert fs[0].severity == "danger" and "2.50 V" in fs[0].message  # a class A2 source may back a hard rule


# --- rails ----------------------------------------------------------------------------------------------------------
def test_rail_sums_with_qty_peak_limits_and_missing():
    parts = [sensor(), k.mod("U2", "tst_oled", {**I2C, "VDD": "3V3"}, qty=2),
             k.mod("U3", "tst_bsensor", {**I2C, "VCC": "3V3"}), k.mod("U4", "tst_rtc", {**I2C, "VCC": "5V"})]
    c = ctx(parts, options={"rail_limits": {"5V": 0.5, "VMOT": 2.0}})
    rails = {r["net"]: r for r in c.rail_sums}
    assert list(rails) == ["5V", "3V3", "VMOT"]
    r = rails["3V3"]
    assert r["i_typ"] == pytest.approx(0.00035 + 2 * 0.008)
    assert r["i_max"] == pytest.approx(0.000714 + 2 * 0.02)
    assert r["i_peak"] == pytest.approx(0.000714 + 2 * 0.03)  # peak, else max
    assert r["missing"] == ["U3"] and r["limit"] is None
    assert rails["5V"]["limit"] == 0.5 and rails["5V"]["limit_source"] == "user"
    assert rails["VMOT"]["volts"] is None and rails["VMOT"]["i_max"] is None


def test_board_limit_for_3v3_from_electrical_boards():
    class El:
        def get(self, chip):
            return dict(fx.ESP)

        def boards(self):
            return {"tst_kit": {"rail_3v3_limit": fx.F(0.6, "A", "tst-esp-ds")}}

    c = ctx([sensor()], electrical=El(), devkit="tst_kit")
    r = next(r for r in c.rail_sums if r["net"] == "3V3")
    assert (r["limit"], r["limit_source"]) == (0.6, "tst-esp-ds") and c.esp["vih"] == 2.475


def test_electrical_failure_means_no_esp_values(monkeypatch):
    from circuit_bench.bench_core import electrical

    def boom(chip):
        raise NotImplementedError

    monkeypatch.setattr(electrical, "get", boom)
    monkeypatch.setattr(electrical, "boards", boom)
    c = ctx([sensor()], electrical=None, devkit="tst_kit")
    assert c.esp is None
    assert ctx([sensor()], electrical={"esp32s3": fx.ESP}).esp["voh"] == 2.64


def test_catalog_failure_means_unknown_modules(monkeypatch):
    from circuit_bench.bench_core import modules

    def boom():
        raise NotImplementedError

    monkeypatch.setattr(modules, "catalog", boom)
    rep = modcheck.run(chip="esp32s3", assignments=BUS, parts=[sensor()], electrical=fx.ESP)
    w = k.by_rule(rep, "mod.unknown")[0]
    assert w["severity"] == "caution" and "module tst_sensor is not in the catalog" in w["message"]
    assert rep.result["counts"]["modules"] == 1


def test_unknown_module_and_unknown_variant():
    rep = run([sensor(), k.mod("U2", "no_such"), k.mod("U3", "tst_imu", variant="zz")])
    ws = k.by_rule(rep, "mod.unknown")
    assert [w["refs"] for w in ws[:2]] == [["U2"], ["U3"]] and "variant zz" in ws[1]["message"]
    assert k.check_of(rep, "mod.unknown")["status"] == "failed"
    assert k.check_of(run([sensor()]), "mod.unknown") is None


def test_alias_resolves_to_the_id():
    c = ctx([k.mod("U1", "tst-sensor", {**I2C, "VDD": "3V3"})])
    assert c.instance("U1").module_id == "tst_sensor" and c.instance("U1").module["_class"] == "A"


# --- register, discovery, robustness --------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["address_conflict", "mod.", "mod.Bad", "mod.x", "mod.env.", "mod.a.b.c",
                                 "mod.toolongwpname.rule", "mod.en-v.rule", 3])
def test_rule_id_form(bad):
    with pytest.raises(ValueError):
        modcheck.rule(bad)


def test_duplicate_rule_id_raises_and_family_ids_register():
    modrules.load()
    with pytest.raises(ValueError):
        modcheck.rule("mod.address_conflict")
    with k.temp_rule("mod.env.tst_rule", lambda c: []):
        assert "mod.env.tst_rule" in modcheck.RULES
        with pytest.raises(ValueError):
            modcheck.rule("mod.env.tst_rule")
    assert "mod.env.tst_rule" not in modcheck.RULES
    with k.temp_rule("mod.nenv.tst_rule", lambda c: []):
        pass


def test_auto_discovery_is_sorted_and_idempotent(tmp_path, monkeypatch):
    assert {"bus", "elec"} <= set(modrules.names()) and modrules.names() == sorted(modrules.names())
    modrules.load()
    before = dict(modcheck.RULES)
    modrules.load()
    assert modcheck.RULES == before
    assert {"mod.address_conflict", "mod.supply_range", "mod.unknown"} <= set(modcheck.RULES)
    (tmp_path / "zz_tstfamily.py").write_text(
        "from circuit_bench.bench_core.modcheck import Finding, rule\n"
        "@rule('mod.tst.hello')\n"
        "def hello(ctx):\n"
        "    return [Finding('mod.tst.hello', 'failed', 'info', f'{len(ctx.instances)} modules')]\n")
    (tmp_path / "zz_tstbroken.py").write_text("raise RuntimeError('broken family file')\n")
    monkeypatch.setattr(modrules, "__path__", [*modrules.__path__, str(tmp_path)])
    monkeypatch.setattr(modrules, "LOAD_ERRORS", {})
    try:
        rep = run([sensor()])
        assert k.by_rule(rep, "mod.tst.hello")[0]["message"] == "1 modules"
        assert k.by_rule(rep, "mod.tst.hello")[0]["code"] == "mod_tst_hello"
        broken = [c for c in rep.checks if c["id"] == "modules.rules"]
        assert broken and broken[0]["status"] == "not_checked" and "zz_tstbroken" in broken[0]["detail"]
        assert "mod.supply_range" in {f.rule_id for f in rep.findings}
    finally:
        modcheck.unregister("mod.tst.hello")
        for name in ("zz_tstfamily", "zz_tstbroken"):
            sys.modules.pop(f"circuit_bench.bench_core.modrules.{name}", None)


def test_rule_exception_becomes_not_checked():
    def broken(c):
        raise KeyError("VDD")

    with k.temp_rule("mod.tst_broken", broken), k.temp_rule("mod.tst_badtype", lambda c: [{"x": 1}]):
        rep = run([sensor()])
    c = k.check_of(rep, "mod.tst_broken")
    assert c["status"] == "not_checked" and c["detail"].startswith("rule error: KeyError")
    assert k.check_of(rep, "mod.tst_badtype")["detail"].startswith("rule error: TypeError")
    assert k.check_of(rep, "mod.supply_range")["status"] == "passed"


def test_only_runs_the_named_rules():
    rep = run([sensor()], only=("mod.supply_range",))
    assert [c["id"] for c in rep.checks] == ["modules.supply_range"]


def test_warnings_sorted_limited_and_counted():
    def many(c):
        sev = ("info", "caution", "danger")
        return [modcheck.Finding("mod.tst_many", "failed", sev[i % 3], f"finding {i}", [f"U{i}"]) for i in range(20)]

    with k.temp_rule("mod.tst_many", many):
        rep = run([sensor()])
    assert len(rep.warnings) == modspec.MAX_FINDINGS_SHOWN
    counts = rep.result["counts"]
    assert counts["findings"] == 20 and counts["shown"] == 12 and counts["danger"] == 6 and counts["info"] == 7
    sevs = [w["severity"] for w in rep.warnings]
    assert sevs == sorted(sevs, key=lambda s: -modspec.SEVERITY_RANK[s])
    assert all(w["code"] == "mod_tst_many" for w in rep.warnings)
    assert [w["refs"] for w in rep.warnings[:2]] == [["U11"], ["U14"]]  # danger, then by refs


def test_checks_and_warnings_are_valid_contract_objects():
    rep = run([sensor(VDD="5V"), k.mod("U2", "tst_rtc", {**I2C, "VCC": "3V3"}), k.mod("U3", "nope")])
    env = contracts.envelope("pins.check", "x", {}, checks=rep.checks, warnings=rep.warnings)
    assert contracts.validate_envelope(env) == []
    assert all(c["id"].startswith("modules.") for c in rep.checks)


# --- pins.check hook ------------------------------------------------------------------------------------------------
def _dump(env):
    return json.dumps(env, ensure_ascii=False, sort_keys=True)


def test_pins_check_without_modules_is_byte_identical():
    base = pins.check("esp32s3", BUS, devkit=None)
    for parts, options in ((None, None), ([], None)):
        assert _dump(pins.check("esp32s3", BUS, parts=parts, options=options)) == _dump(base)
    # a wired discrete part adds only the assumption that it is not analysed
    wired = [{"ref": "R1", "kind": "resistor", "value": "4k7", "conn": {"1": "SDA0", "2": "3V3"}}]
    env = pins.check("esp32s3", BUS, parts=wired, options={"rails": {"V": 1}})
    assert [a["key"] for a in env["assumptions"]][-1] == "discrete_parts"
    env["assumptions"] = env["assumptions"][:-1]
    assert _dump(env) == _dump(base)


def test_pins_check_with_modules_merges_the_report(monkeypatch):
    k.patch_runtime(monkeypatch, catalog=fx.catalog(), electrical=fx.ESP, sources=fx.SOURCES)
    parts = [sensor("U1", VDD="5V"), k.mod("U2", "tst_imu", {**I2C, "VDD": "3V3"}),
             k.mod("U3", "tst_rtc", {**I2C, "VCC": "5V"})]
    base = pins.check("esp32s3", BUS)
    env = pins.check("esp32s3", BUS, parts=parts)
    assert env["ok"] and contracts.validate_envelope(env) == []
    mods = env["result"]["modules"]
    assert mods["counts"] == {"modules": 3, "findings": 2, "shown": 2, "danger": 1, "caution": 1, "info": 0}
    assert env["summary"] == base["summary"] + " Modules: 2 findings (1 danger, 1 caution)."
    assert {"mod_address_conflict", "mod_supply_range"} <= {w["code"] for w in env["warnings"]}
    ids = [s["id"] for s in env["sources"]]
    assert {"tst-sensor-ds", "tst-imu-ds", "tst-rtc-ds"} <= set(ids) and len(ids) == len(set(ids))
    assert env["checks"][: len(base["checks"])] == base["checks"]


def test_pins_check_unknown_sources_become_a_hint(monkeypatch):
    k.patch_runtime(monkeypatch, catalog=fx.catalog(), electrical=fx.ESP)
    env = pins.check("esp32s3", BUS, parts=[sensor(VDD="5V")])
    assert env["ok"]
    hint = [w for w in env["warnings"] if w["code"] == "rule_data_missing"]
    assert hint and "tst-sensor-ds" in hint[0]["message"]


def test_pins_check_error_envelope_skips_modules(monkeypatch):
    k.patch_runtime(monkeypatch, catalog=fx.catalog(), electrical=fx.ESP)
    env = pins.check("esp32s3", [], parts=[sensor()])
    assert env["ok"] is False and "modules" not in (env["result"] or {})


def test_thirty_modules_stay_below_the_byte_limit(monkeypatch):
    k.patch_runtime(monkeypatch, catalog=fx.catalog(), electrical=fx.ESP, sources=fx.SOURCES)
    kinds = [("tst_sensor", {"VDD": "5V", "SDO": "GND"}), ("tst_oled", {"VDD": "5V"}), ("tst_imu", {"VDD": "5V"}),
             ("tst_rtc", {"VCC": "3V3"}), ("tst_breakout", {"VIN": "5V"}), ("tst_bsensor", {"VCC": "5V"}),
             ("tst_5v_display", {"VCC": "3V3"}), ("tst_mux", {"VCC": "VB"})]
    parts = [k.mod(f"U{i + 1}", m, {**I2C, **conn}) for i, (m, conn) in
             ((i, kinds[i % len(kinds)]) for i in range(29))] + [k.mod("U30", "unknown_part")]
    env = pins.check("esp32s3", [*BUS, k.assign("out", 4, role="LED"), k.assign("adc", 1, role="POT")],
                     devkit="esp32-s3-devkitc-1", parts=parts, options={"rails": {"VB": 3.3}})
    assert env["ok"]
    assert env["result"]["modules"]["counts"]["modules"] == 30
    assert env["result"]["modules"]["counts"]["findings"] > modspec.MAX_FINDINGS_SHOWN
    raw = len(json.dumps(env, ensure_ascii=False).encode("utf-8"))
    ascii_ = len(json.dumps(env).encode())
    assert max(raw, ascii_) <= contracts.MAX_RESULT_BYTES, (raw, ascii_)


def test_shrink_levels_keep_order_counts_and_mark_left_out_devices():
    parts = [sensor(f"U{i}", VDD="5V") for i in range(1, 21)]
    rep = run(parts)
    assert modcheck.shrink(rep, 0) is rep and "compact" not in rep.result
    last = len(modcheck.SHRINK_LEVELS) - 2  # the level before the last resort still lists devices per segment
    small = modcheck.shrink(rep, last)
    dangers = sum(w["severity"] == "danger" for w in rep.warnings)
    n = max(modcheck.SHRINK_LEVELS[last][0], dangers)  # dangers stay visible
    assert all(len(w["message"]) <= modcheck.SHRINK_LEVELS[last][1] for w in small.warnings)
    assert [w["code"] for w in small.warnings] == [w["code"] for w in rep.warnings[:n]]
    assert small.result["counts"]["shown"] == n and small.result["counts"]["findings"] == rep.result["counts"]["findings"]
    assert len(small.result["counts"].get("hidden", [])) == min(len(rep.warnings) - n, modcheck.MAX_HIDDEN_LISTED)
    assert small.result["compact"] == last
    final = modcheck.shrink(rep, last + 1)  # last resort: dangers only, buses without device lists
    assert final.result["buses"][0]["segments"] == [] and final.result["buses"][0]["more"] == 20
    assert len(final.warnings) == max(1, dangers)  # every danger, texts cut; the rest only in counts.hidden
    seg = small.result["buses"][0]["segments"][0]
    assert seg["more"] == 20 - len(seg["devices"])
    assert set(small.source_ids) <= set(rep.source_ids)
    assert all(set(c.get("source_ids", ())) <= set(small.source_ids) for c in small.checks)
    # passed (and on this level not_checked) checks fold into one summary check; a failed one keeps its reason,
    # either as its own check or as a shown warning
    mod_ids = [c["id"] for c in small.checks if c["id"].startswith("modules")]
    assert mod_ids[-1] == "modules" and mod_ids.count("modules") == 1
    _reasons_kept(rep, small, ("failed",))
    assert [c["id"] for c in final.checks if c["id"].startswith("modules")] == ["modules"]  # last resort: one line
    assert rep.result["buses"][0]["segments"][0]["devices"][19]["ref"] == "U20"  # the original is untouched


def test_ten_modules_fit_and_keep_the_worst_first(monkeypatch):
    k.patch_runtime(monkeypatch, catalog=fx.catalog(), electrical=fx.ESP, sources=fx.SOURCES)
    parts = [sensor(f"U{i}", VDD="5V") for i in range(1, 6)] + [
        k.mod(f"U{i}", "tst_rtc", {**I2C, "VCC": "3V3"}) for i in range(6, 11)]
    env = pins.check("esp32s3", BUS, parts=parts)
    assert len(json.dumps(env).encode()) <= contracts.MAX_RESULT_BYTES
    mw = [w for w in env["warnings"] if w["code"].startswith("mod_")]
    assert mw[0]["severity"] == "danger" and len(mw) == env["result"]["modules"]["counts"]["shown"]
    assert {s["id"] for s in env["sources"]} >= {sid for w in mw for sid in w["source_ids"]}


# --- compaction keeps the reasons -----------------------------------------------------------------------------------
def _mod_checks(rep):
    return {c["id"]: c for c in rep.checks if c["id"].startswith("modules")}


def _reasons_kept(rep, small, statuses=("failed", "not_checked")):
    """Every failed / not_checked module check of ``rep`` keeps its reason in ``small``: its own check with a detail,
    or a shown warning of the same code (the folded check then sits in the summary line)."""
    mine, shown = _mod_checks(small), {w["code"] for w in small.warnings}
    for cid, c in _mod_checks(rep).items():
        if c["status"] not in statuses or cid == "modules":
            continue
        code = modcheck.warning_code("mod." + cid[len("modules."):])
        if cid in mine:
            assert mine[cid]["detail"], cid
        else:
            assert code in shown and cid[len("modules."):] in mine["modules"]["detail"], cid


def test_shrink_drops_passed_details_first_and_keeps_open_reasons():
    parts = [sensor(f"U{i}", VDD="5V") for i in range(1, 21)]
    rep = run(parts)
    full = _mod_checks(rep)
    assert {c["status"] for c in full.values()} >= {"passed", "failed"}
    one = _mod_checks(modcheck.shrink(rep, 1))
    for cid, c in full.items():  # level 1: passed checks lose their detail, the others keep it word for word
        if c["status"] == "passed":
            assert one[cid]["detail"] == ""
        elif not one[cid]["detail"].startswith("see warning "):
            assert one[cid]["detail"] == c["detail"]
    two = modcheck.shrink(rep, 2)  # level 2: passed checks (and those a shown warning explains) fold into one line
    passed = sorted(cid[len("modules."):] for cid, c in full.items() if c["status"] == "passed")
    assert _mod_checks(two)["modules"]["detail"].endswith("passed: " + ", ".join(passed))
    assert not any(c["status"] == "passed" for cid, c in _mod_checks(two).items() if cid != "modules")
    for level in range(1, len(modcheck.SHRINK_LEVELS) - 2):  # open checks keep their reason down to the last levels
        _reasons_kept(rep, modcheck.shrink(rep, level))


def test_shrink_order_passed_before_open_before_failed():
    for lv in modcheck.SHRINK_LEVELS:
        assert lv.detail <= modcheck.MAX_DETAIL_CHARS and lv.passed in ("detail", "bare", "fold")
    folds = [("passed" if lv.passed == "fold" else None, *lv.fold) for lv in modcheck.SHRINK_LEVELS]
    first = {st: next(i for i, f in enumerate(folds) if st in f) for st in ("passed", "not_checked", "failed")}
    assert first["passed"] < first["not_checked"] < first["failed"] == len(modcheck.SHRINK_LEVELS) - 1
    assert all(a.detail >= b.detail for a, b in zip(modcheck.SHRINK_LEVELS, modcheck.SHRINK_LEVELS[1:], strict=False))


def test_shrink_keeps_a_not_checked_reason_without_a_warning():
    rep = run([sensor(f"U{i}", VDD="5V") for i in range(1, 21)])
    nc = modcheck.mk_check("modules.tst_open", "not_checked", "x" * 150)
    rep = modcheck.ModReport(result=rep.result, checks=[*rep.checks, nc], warnings=rep.warnings,
                             source_ids=rep.source_ids, findings=rep.findings)
    for level in range(1, 4):
        assert _mod_checks(modcheck.shrink(rep, level))["modules.tst_open"]["detail"] == "x" * 150
    assert len(_mod_checks(modcheck.shrink(rep, 7))["modules.tst_open"]["detail"]) == modcheck.SHRINK_LEVELS[7].detail


def test_thirty_modules_keep_failed_checks_with_details(monkeypatch):
    k.patch_runtime(monkeypatch, catalog=fx.catalog(), electrical=fx.ESP, sources=fx.SOURCES)
    parts = [k.mod(f"U{i + 1}", "tst_sensor", {**I2C, "VDD": "5V", "SDO": "GND"}) for i in range(30)]
    env = pins.check("esp32s3", BUS, parts=parts)
    assert env["ok"] and len(json.dumps(env).encode()) <= contracts.MAX_RESULT_BYTES
    assert env["result"]["modules"].get("compact", 0) >= 1
    failed = [c for c in env["checks"] if c["id"].startswith("modules.") and c["status"] == "failed"]
    assert failed and all(c["detail"] for c in failed)
    shown = {w["code"] for w in env["warnings"]}
    for c in failed:
        assert not c["detail"].startswith("see warning ") or c["detail"].split()[2] in shown
