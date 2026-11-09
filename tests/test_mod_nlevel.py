"""Module family nlevel: PCA9306, SN74LVC1T45, SN74LVC8T245, SN74LVC125A,
SN74HCT595, CD74HCT4067 and the family rules in bench_core/modrules/nlevel.py. Generic data/excerpt checks live in
tests/test_m0_modules_*.

All projects are synthetic.
"""
from __future__ import annotations

import pytest

import excerpts as ex
import modkit as mk
from circuit_bench.bench_core import modules, sources
from circuit_bench.bench_core.modrules import nlevel

IDS = {"pca9306": "logic.level_shifter", "sn74lvc1t45": "logic.level_shifter", "sn74lvc8t245": "logic.level_shifter",
       "sn74lvc125a": "logic.level_shifter", "sn74hct595": "logic.shift_register", "cd74hct4067": "logic.mux"}


def ic(ref, module, conn):
    return {"ref": ref, "kind": "ic", "value": module.upper(), "module": module, "conn": dict(conn)}


def res(ref, value, a, b):
    return {"ref": ref, "kind": "resistor", "value": value, "conn": {"1": a, "2": b}}


def cap(ref, value, a, b="GND"):
    return {"ref": ref, "kind": "ceramic", "value": value, "conn": {"1": a, "2": b}}


def bme(ref, sda, scl, sdo="GND"):
    return ic(ref, "bme280", {"SDI": sda, "SCK": scl, "SDO": sdo, "VDD": "3V3", "GND": "GND"})


def run(assignments=(), parts=(), options=None, rule=None):
    return mk.run(assignments=assignments, parts=parts, options=options, only=(rule,) if rule else None)


def fs(report, rule_id, status=None):
    return mk.findings(report, rule_id, status)


def one(report, rule_id, status=None):
    got = fs(report, rule_id, status)
    assert len(got) == 1, [(f.status, f.message) for f in fs(report, rule_id)]
    return got[0]


def pca(**over):
    conn = {"VREF1": "3V3", "SDA1": "SDA0", "SCL1": "SCL0", "SDA2": "SDA5", "SCL2": "SCL5", "VREF2": "VR2", "EN": "VR2",
            "GND": "GND"}
    conn.update(over)
    return ic("U1", "pca9306", conn)


PCA_OK = [pca(), res("R1", "200k", "VR2", "5V"), cap("C1", "100pF", "VR2"),
          res("R2", "4k7", "SDA0", "3V3"), res("R3", "4k7", "SCL0", "3V3"),
          res("R4", "4k7", "SDA5", "5V"), res("R5", "4k7", "SCL5", "5V")]
SPI3 = [mk.assign("spi_mosi", 11), mk.assign("spi_sck", 12), mk.assign("spi_cs", 10)]
HC595 = {"VCC": "5V", "GND": "GND", "SER": "GPIO11", "SRCLK": "GPIO12", "RCLK": "GPIO10", "OE": "GND",
         "SRCLR": "5V"}
MUX = {"VCC": "5V", "GND": "GND", "S0": "GPIO4", "S1": "GPIO5", "S2": "GPIO6", "S3": "GPIO7", "E": "GND",
       "COM": "GPIO1", "I0": "POT"}
MUX_ESP = [mk.assign("out", g) for g in (4, 5, 6, 7)] + [mk.assign("adc", 1)]


# --- catalogue ---------------------------------------------------------------------------------------------------
def test_entries_load_with_class_a_ti_sources():
    cat = modules.catalog()
    for mid, category in IDS.items():
        m = cat.get(mid)
        assert m["category"] == category and m["_wp"] == "nlevel" and m["_class"] == "A", mid
        (sid,) = m["source_ids"]
        src = sources.get(sid)
        assert src["url"] == f"https://www.ti.com/lit/ds/symlink/{mid}.pdf" and src["class"] == "A"
    assert cat.get("74lvc125a")["id"] == "sn74lvc125a" and cat.get("74hct595")["id"] == "sn74hct595"
    assert cat.get("74lvc8t245")["id"] == "sn74lvc8t245" and cat.get("74hct4067")["id"] == "cd74hct4067"


def test_lvc125a_inputs_are_5v_tolerant_at_3v3():
    m = modules.catalog().get("sn74lvc125a")
    assert m["io"]["five_v_tolerant"] is True
    assert m["io"]["v_in_max"]["value"] == 5.5 and m["io"]["v_in_max"]["page"] == 5
    assert m["supplies"]["VCC"]["max"]["value"] == 3.6
    tol = next(n for n in m["notes"] if n.get("page") == 10 and "up to 5.5 V" in n["text"])
    assert tol["verified"] is True


def test_hct595_ttl_threshold_lets_3v3_drive_5v():
    m = modules.catalog().get("sn74hct595")
    assert m["io"]["vih"]["value"] == 2 and m["io"]["vih"]["page"] == 4
    assert m["supplies"]["VCC"]["min"]["value"] == 4.5


def test_two_supply_io_is_relative_to_the_a_side():
    cat = modules.catalog()
    for mid in ("sn74lvc1t45", "sn74lvc8t245"):
        io = cat.get(mid)["io"]
        assert io["domain"] == "VCCA"
        assert modules.value(io["voh"], {"VCCA": 3.3}) == pytest.approx(3.2)


@pytest.mark.parametrize(("sid", "page", "needle"), [
    ("mod-nlevel-pca9306-ds", 15, "• Vth is approximately 0.6V"),
    ("mod-nlevel-pca9306-ds", 15, "RCC(min) ≥ (VCC2 - Ven)/0.128 : Ven = VREF1 + Vth (6)"),
    ("mod-nlevel-pca9306-ds", 5, "Continuous channel current 128 mA"),
    ("mod-nlevel-pca9306-ds", 5, "VREF1 supports 1.2 V to VREF2 - 0.6 V"),
    ("mod-nlevel-sn74lvc1t45-ds", 14, "H A data to B bus"),
    ("mod-nlevel-sn74lvc8t245-ds", 15, "L H Hi-Z Enabled A data to B bus"),
    ("mod-nlevel-sn74lvc125a-ds", 10, "• Inputs are overvoltage tolerant"),
    ("mod-nlevel-sn74hct595-ds", 12, "X X X X H Outputs QA – QH are disabled"),
    ("mod-nlevel-cd74hct4067-ds", 5, "X X X X 1 None"),
])
def test_rule_facts_are_in_the_excerpts(sid, page, needle):
    segs = [ln for e in ex.by_source()[sid] for seg in e.page_segments(page) for ln in seg]
    assert any(needle in ln for ln in segs), needle
    assert (nlevel.PCA_VTH_V, nlevel.PCA_I_MAX_A, nlevel.PCA_VREF1_MIN_V) == (0.6, 0.128, 1.2)


@pytest.mark.parametrize(("text", "want"), [(200000, 200000.0), ("200k", 2e5), ("4k7", 4700.0), ("10 kΩ", 1e4),
                                            ("220R", 220.0), ("x", None), ("0", None), (None, None), (True, None)])
def test_ohms(text, want):
    assert nlevel.ohms(text) == want


def test_rules_silent_without_family_parts():
    r = run(mk.i2c(), [bme("U9", "SDA0", "SCL0")])
    assert not [c for c in r.checks if c["id"].startswith("modules.nlevel.")]


# --- generic rules with the real entries (supply, levels, address) ------------------------------------------------
def test_lvc125a_on_5v_is_outside_the_supply_range():
    parts = [ic("U1", "sn74lvc125a", {"VCC": "5V", "GND": "GND", "1OE": "GND", "1A": "GPIO4", "1Y": "LED"})]
    f = one(run([mk.assign("out", 4)], parts, rule="mod.supply_range"), "mod.supply_range", "failed")
    assert f.severity == "caution" and "3.60 V" in f.message


def test_lvc125a_at_3v3_passes_supply():
    parts = [ic("U1", "sn74lvc125a", {"VCC": "3V3", "GND": "GND", "1OE": "GND", "1A": "GPIO4", "1Y": "LED"})]
    assert [f.status for f in fs(run([mk.assign("out", 4)], parts, rule="mod.supply_range"),
                                 "mod.supply_range")] == ["passed"]


@pytest.mark.parametrize(("rail", "status"), [("3V3", "failed"), ("5V", "passed")])
def test_hct595_needs_5v(rail, status):
    parts = [ic("U1", "sn74hct595", {**HC595, "VCC": rail, "SRCLR": rail})]
    f = one(run(SPI3, parts, rule="mod.supply_range"), "mod.supply_range")
    assert f.status == status
    if status == "failed":
        assert f.severity == "caution" and "4.50 V–5.50 V" in f.message


def test_hct595_ttl_inputs_accept_the_3v3_esp_at_5v():
    r = run(SPI3, [ic("U1", "sn74hct595", HC595)], rule="mod.level_in")
    assert [f.status for f in fs(r, "mod.level_in")] == ["passed"]


def test_hct595_at_3v3_levels_are_not_interpolated():
    parts = [ic("U1", "sn74hct595", {**HC595, "VCC": "3V3", "SRCLR": "3V3"})]
    f = one(run(SPI3, parts, rule="mod.level_in"), "mod.level_in")
    assert f.status == "not_checked" and "never interpolated" in f.message


def test_hct595_serial_out_to_the_esp_is_a_5v_danger():
    parts = [ic("U1", "sn74hct595", {**HC595, "QH'": "GPIO13"})]
    r = run(SPI3 + [mk.assign("spi_miso", 13)], parts, rule="mod.level_out")
    f = one(r, "mod.level_out", "failed")
    assert f.severity == "danger" and "QH'" in f.message


def test_mux_com_at_5v_on_the_esp_adc_is_a_caution():
    f = one(run(MUX_ESP, [ic("U1", "cd74hct4067", MUX)], rule="mod.level_out"), "mod.level_out", "failed")
    assert f.severity == "caution" and "COM" in f.message and "5.00 V" in f.message


def test_mux_select_lines_pass_the_ttl_level_check_at_the_datasheet_vcc_only():
    # TI SCHS209 p. 8 gives the HCT VIH/VIL only in the VCC = 4.5 V column: at 4.5 V the 2 V TTL threshold passes,
    # at 5 V nothing is interpolated (not_checked, no caution) and at 3.3 V no level finding appears either
    r = run(MUX_ESP, [ic("U1", "cd74hct4067", {**MUX, "VCC": "V45"})], {"rails": {"V45": 4.5}}, rule="mod.level_in")
    assert {f.status for f in fs(r, "mod.level_in")} == {"passed"}
    for vcc in ("5V", "3V3"):
        r = run(MUX_ESP, [ic("U1", "cd74hct4067", {**MUX, "VCC": vcc})], rule="mod.level_in")
        got = fs(r, "mod.level_in")
        assert {f.status for f in got} == {"not_checked"} and all("VCC = 4.5 V" in f.message for f in got)
        assert not [f for f in got if f.severity in ("caution", "danger")]


def test_lvc1t45_supply_above_6v5_is_danger():
    parts = [ic("U1", "sn74lvc1t45", {"VCCA": "3V3", "VCCB": "VB", "GND": "GND", "A": "GPIO4", "B": "LED",
                                      "DIR": "3V3"})]
    r = run([mk.assign("out", 4)], parts, options={"rails": {"VB": 7.0}}, rule="mod.supply_range")
    f = one(r, "mod.supply_range", "failed")
    assert f.severity == "danger" and "VCCB" in f.message


def test_pca9306_has_no_address_and_passes_the_bus_address_check():
    parts = PCA_OK + [bme("U2", "SDA0", "SCL0"), bme("U3", "SDA0", "SCL0", sdo="3V3")]
    r = run(mk.i2c(), parts, rule="mod.address_conflict")
    assert not fs(r, "mod.address_conflict", "failed")
    assert not [f for f in fs(r, "mod.address_conflict") if "U1" in f.refs]


def test_pca9306_low_side_pullups_required():
    parts = [pca(), res("R1", "200k", "VR2", "5V"), cap("C1", "100pF", "VR2")]
    r = run(mk.i2c(), parts, rule="mod.required_parts")
    msgs = [f.message for f in fs(r, "mod.required_parts", "failed") if "U1" in f.refs]
    assert any("pullup" in m and "SDA1" in m for m in msgs)
    r2 = run(mk.i2c(), PCA_OK, rule="mod.required_parts")
    assert not [f for f in fs(r2, "mod.required_parts", "failed") if "U1" in f.refs]


# --- mod.nlevel.pca9306_bias -------------------------------------------------------------------------------------
def test_pca9306_reference_circuit_passes():
    f = one(run(mk.i2c(), PCA_OK, rule="mod.nlevel.pca9306_bias"), "mod.nlevel.pca9306_bias")
    assert f.status == "passed" and "3.30 V" in f.message and "5.00 V" in f.message


def test_pca9306_vref2_straight_on_the_rail_is_a_caution():
    parts = [pca(VREF2="5V", EN="5V")] + PCA_OK[3:]
    f = one(run(mk.i2c(), parts, rule="mod.nlevel.pca9306_bias"), "mod.nlevel.pca9306_bias", "failed")
    assert f.severity == "caution" and "200 kΩ" in f.message and f.source_ids == ["mod-nlevel-pca9306-ds"]
    assert "8.59 Ω" in f.message  # (5 - 3.3 - 0.6) / 0.128
    assert "mod_nlevel_pca9306_bias" in mk.codes(run(mk.i2c(), parts))


def test_pca9306_bias_resistor_below_rcc_min_is_danger():
    parts = [pca(), res("R1", "4", "VR2", "5V")] + PCA_OK[2:]
    f = one(run(mk.i2c(), parts, rule="mod.nlevel.pca9306_bias"), "mod.nlevel.pca9306_bias", "failed")
    assert f.severity == "danger" and "128 mA" in f.message


def test_pca9306_vref1_too_close_to_vref2_is_a_caution():
    parts = [pca(VREF1="3V3"), res("R1", "200k", "VR2", "V35")] + PCA_OK[2:]
    r = run(mk.i2c(), parts, options={"rails": {"V35": 3.6}}, rule="mod.nlevel.pca9306_bias")
    f = one(r, "mod.nlevel.pca9306_bias", "failed")
    assert f.severity == "caution" and "0.6 V" in f.message


def test_pca9306_same_voltage_both_sides_is_a_plain_switch():
    parts = [pca(), res("R1", "200k", "VR2", "3V3")] + PCA_OK[2:]
    f = one(run(mk.i2c(), parts, rule="mod.nlevel.pca9306_bias"), "mod.nlevel.pca9306_bias")
    assert f.status == "passed" and "plain bus switch" in f.message


def test_pca9306_unknown_high_side_is_not_checked():
    parts = [pca(), res("R1", "200k", "VR2", "VX")]
    f = one(run(mk.i2c(), parts, rule="mod.nlevel.pca9306_bias"), "mod.nlevel.pca9306_bias")
    assert f.status == "not_checked"


# --- mod.nlevel.pca9306_shared_bus ------------------------------------------------------------------------------
def test_same_address_on_both_sides_is_danger():
    parts = PCA_OK + [bme("U2", "SDA0", "SCL0"), bme("U3", "SDA5", "SCL5")]
    r = run(mk.i2c(), parts, rule="mod.nlevel.pca9306_shared_bus")
    f = one(r, "mod.nlevel.pca9306_shared_bus", "failed")
    assert f.severity == "danger" and "0x76" in f.message and set(f.refs) == {"U1", "U2", "U3"}


def test_different_addresses_on_both_sides_pass():
    parts = PCA_OK + [bme("U2", "SDA0", "SCL0"), bme("U3", "SDA5", "SCL5", sdo="3V3")]
    f = one(run(mk.i2c(), parts, rule="mod.nlevel.pca9306_shared_bus"), "mod.nlevel.pca9306_shared_bus")
    assert f.status == "passed"


def test_disabled_pca9306_does_not_join_the_buses():
    parts = [pca(EN="GND")] + PCA_OK[1:] + [bme("U2", "SDA0", "SCL0"), bme("U3", "SDA5", "SCL5")]
    r = run(mk.i2c(), parts)
    assert fs(r, "mod.nlevel.pca9306_shared_bus") == []
    f = one(r, "mod.nlevel.oe_disabled", "failed")
    assert f.severity == "caution" and "EN on GND" in f.message


# --- mod.nlevel.dir_contention -----------------------------------------------------------------------------------
def t45(dir_net, a="GPIO4", b="LED"):
    return ic("U1", "sn74lvc1t45", {"VCCA": "3V3", "VCCB": "5V", "GND": "GND", "A": a, "B": b, "DIR": dir_net})


def test_dir_high_with_esp_driving_a_passes():
    f = one(run([mk.assign("out", 4)], [t45("3V3")], rule="mod.nlevel.dir_contention"), "mod.nlevel.dir_contention")
    assert f.status == "passed" and "A to B" in f.message


def test_dir_low_with_esp_driving_a_is_contention():
    f = one(run([mk.assign("out", 4)], [t45("GND")], rule="mod.nlevel.dir_contention"),
            "mod.nlevel.dir_contention", "failed")
    assert f.severity == "danger" and "push-pull" in f.message and f.source_ids == ["mod-nlevel-sn74lvc1t45-ds"]


def test_dir_high_with_esp_reading_a_is_a_caution():
    f = one(run([mk.assign("in", 4)], [t45("3V3", b="SIG5")], rule="mod.nlevel.dir_contention"),
            "mod.nlevel.dir_contention", "failed")
    assert f.severity == "caution" and "nothing drives" in f.message


def test_esp_reading_the_5v_b_side_is_danger():
    f = one(run([mk.assign("in", 4)], [t45("3V3", a="SIG3", b="GPIO4")], rule="mod.nlevel.dir_contention"),
            "mod.nlevel.dir_contention", "failed")
    assert f.severity == "danger" and "VCCB 5.00 V" in f.message


def test_dir_on_a_gpio_passes_and_dir_open_is_not_checked():
    r = run([mk.assign("out", 4), mk.assign("out", 5)], [t45("GPIO5")], rule="mod.nlevel.dir_contention")
    assert one(r, "mod.nlevel.dir_contention").status == "passed"
    part = ic("U1", "sn74lvc1t45", {"VCCA": "3V3", "VCCB": "5V", "GND": "GND", "A": "GPIO4", "B": "LED"})
    r2 = run([mk.assign("out", 4)], [part], rule="mod.nlevel.dir_contention")
    assert one(r2, "mod.nlevel.dir_contention").status == "not_checked"


def test_8t245_dir_low_with_esp_outputs_on_a_is_contention():
    conn = {"VCCA": "3V3", "VCCB": "5V", "GND": "GND", "OE": "GND", "DIR": "GND", "A1": "GPIO4", "A2": "GPIO5",
            "B1": "X1", "B2": "X2"}
    r = run([mk.assign("out", 4), mk.assign("out", 5)], [ic("U1", "sn74lvc8t245", conn)],
            rule="mod.nlevel.dir_contention")
    f = one(r, "mod.nlevel.dir_contention", "failed")
    assert f.severity == "danger" and "A1 on GPIO4" in f.message and "A2 on GPIO5" in f.message


# --- mod.nlevel.oe_disabled --------------------------------------------------------------------------------------
@pytest.mark.parametrize(("module", "conn", "assigns", "status"), [
    ("sn74lvc125a", {"VCC": "3V3", "GND": "GND", "1OE": "3V3", "1A": "GPIO4", "1Y": "LED"}, "out", "failed"),
    ("sn74lvc125a", {"VCC": "3V3", "GND": "GND", "1OE": "GND", "1A": "GPIO4", "1Y": "LED"}, "out", "passed"),
    ("sn74lvc8t245", {"VCCA": "3V3", "VCCB": "5V", "GND": "GND", "OE": "3V3", "DIR": "3V3", "A1": "GPIO4"}, "out",
     "failed"),
    ("sn74hct595", {**HC595, "OE": "5V"}, "spi", "failed"),
    ("sn74hct595", HC595, "spi", "passed"),
    ("cd74hct4067", {**MUX, "E": "5V"}, "mux", "failed"),
])
def test_enable_held_off(module, conn, assigns, status):
    a = {"out": [mk.assign("out", 4)], "spi": SPI3, "mux": MUX_ESP}[assigns]
    f = one(run(a, [ic("U1", module, conn)], rule="mod.nlevel.oe_disabled"), "mod.nlevel.oe_disabled")
    assert f.status == status
    if status == "failed":
        assert f.severity == "caution" and f.source_ids == [f"mod-nlevel-{module}-ds"]


def test_enable_on_a_gpio_is_not_held_off():
    r = run(SPI3 + [mk.assign("out", 14)], [ic("U1", "sn74hct595", {**HC595, "OE": "GPIO14"})],
            rule="mod.nlevel.oe_disabled")
    assert one(r, "mod.nlevel.oe_disabled").status == "passed"


def test_unused_lvc125a_channels_are_ignored_by_oe_rule():
    conn = {"VCC": "3V3", "GND": "GND", "1OE": "GND", "1A": "GPIO4", "1Y": "LED", "2OE": "3V3", "2A": "GND"}
    f = one(run([mk.assign("out", 4)], [ic("U1", "sn74lvc125a", conn)], rule="mod.nlevel.oe_disabled"),
            "mod.nlevel.oe_disabled")
    assert f.status == "passed" and "2OE" not in f.message


# --- data corrections --------------------------------------------------------------------------------------------
def _quoted(sid, page, parts):
    return any(ex.find_parts_in_order(parts, s) for e in ex.by_source("mod-nlevel-*.txt")[sid]
               for s in e.page_segments(page))


def test_pca9306_vref1_range_is_stated_with_footnote_and_feature_range():
    m = modules.catalog().get("pca9306")
    mx = m["supplies"]["VREF1"]["max"]
    assert mx["value"] == 5.5 and "VREF2 − 0.6 V" in mx["conditions"] and "1.2–3.3 V" in mx["conditions"]
    assert _quoted("mod-nlevel-pca9306-ds", 5, mx["evidence"])
    note = next(n for n in m["notes"] if n.get("page") == 1)
    assert note["verified"] is True and _quoted("mod-nlevel-pca9306-ds", 1, note["evidence"])


@pytest.mark.parametrize("v1, v2, status", [("3V3", "5V", "passed"), ("V45", "5V", "failed"), ("5V", "5V", "passed")])
def test_pca9306_vref1_must_stay_0v6_below_the_high_side(v1, v2, status):
    parts = [pca(VREF1=v1), res("R1", "200k", "VR2", v2), cap("C1", "100pF", "VR2")]
    r = run(parts=parts, options={"rails": {"V45": 4.5}}, rule="mod.nlevel.pca9306_bias")
    got = fs(r, "mod.nlevel.pca9306_bias")
    assert {f.status for f in got} == {status}
    if status == "failed":
        assert got[0].severity == "caution" and "0.6 V" in got[0].message


def test_hct4067_levels_name_the_4v5_column():
    m = modules.catalog().get("cd74hct4067")
    for k in ("vih", "vil"):
        assert "VCC = 4.5 V" in m["io"][k]["conditions"]
        assert _quoted("mod-nlevel-cd74hct4067-ds", 8, m["io"][k]["evidence"])
