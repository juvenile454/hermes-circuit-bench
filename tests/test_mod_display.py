"""Module family display: catalog entries of data/modules/display.json and the
rules in bench_core/modrules/display.py, on synthetic projects (tests/modkit.py) with the real catalog and the real
ESP32-S3 values (VDD 3.3 V, VOH 2.64 V, input max 3.6 V)."""
from __future__ import annotations

import pytest

import modkit as mk
from circuit_bench.bench_core import modules

OLED_I2C = {"VDD": "3V3", "GND": "GND", "SCL": "SCL0", "SDA": "SDA0", "RES": "3V3"}


def oled(ref, module="ssd1306", sa0="GND", supply="VDD", **kw):
    conn = {**OLED_I2C, "SA0": sa0}
    if supply != "VDD":
        conn[supply] = conn.pop("VDD")
    return mk.mod(ref, module, conn, **kw)


def run(parts, assignments=None, **kw):
    return mk.run(assignments=mk.i2c() if assignments is None else assignments, parts=parts, **kw)


def one(report, rule_id, status=None):
    fs = mk.findings(report, rule_id, status)
    assert len(fs) == 1, fs
    return fs[0]


# --- catalog ------------------------------------------------------------------------------------------------------
def test_display_entries_load_with_their_classes():
    cat = modules.catalog()
    assert [p for p in cat.problems if "display" in p] == []
    want = {"ssd1306": "A2", "sh1106": "A2", "ssd1309": "A2", "hd44780": "A2", "max7219": "A1", "tm1637": "A1"}
    for mid, cls in want.items():
        m = cat.get(mid)
        assert m["_wp"] == "display" and m["_class"] == cls and m["kind"] == "ic"
    assert cat.get("lcd1602")["id"] == "hd44780"
    assert {r["id"] for r in cat.search(category="display.oled")["items"]} == {"ssd1306", "sh1106", "ssd1309"}


def test_oled_variants_switch_to_spi():
    cat = modules.catalog()
    for mid, hz in (("ssd1306", 1e7), ("sh1106", 4e6), ("ssd1309", 1e7)):
        base, spi = cat.get(mid), cat.get(mid, "spi4")
        assert base["interfaces"][0]["type"] == "i2c" and base["interfaces"][0]["f_max_hz"]["value"] == 4e5
        assert spi["interfaces"][0]["type"] == "spi" and spi["interfaces"][0]["f_max_hz"]["value"] == hz
        assert {p["signal"] for p in spi["pins"]} >= {"spi_sck", "spi_sdi", "spi_cs"}
        assert spi["requires"] == [] and "outputs" not in spi["io"]


def test_tm1637_has_no_i2c_interface():
    m = modules.catalog().get("tm1637")
    assert [it["type"] for it in m["interfaces"]] == ["digital"]
    assert not any(p["signal"].startswith("i2c") for p in m["pins"])


# --- addresses (generic mod.address_conflict) -----------------------------------------------------------------------
def test_two_oleds_same_sa0_conflict_and_sa0_high_resolves():
    r = run([oled("U1"), oled("U2", "sh1106", supply="VDD1")])
    f = one(r, "mod.address_conflict", "failed")
    assert set(f.refs) == {"U1", "U2"} and "0x3c" in f.message.lower()
    r = run([oled("U1"), oled("U2", "sh1106", sa0="3V3", supply="VDD1")])
    assert mk.findings(r, "mod.address_conflict", "failed") == []


def test_ssd1309_shares_the_address_family():
    r = run([oled("U1"), oled("U2", "ssd1309")])
    assert set(one(r, "mod.address_conflict", "failed").refs) == {"U1", "U2"}


# --- supply (generic mod.supply_range) ----------------------------------------------------------------------------
@pytest.mark.parametrize("mid,supply", [("ssd1306", "VDD"), ("ssd1309", "VDD"), ("sh1106", "VDD1")])
def test_oled_chip_on_5v_exceeds_abs_max(mid, supply):
    p = oled("U1", mid, supply=supply)
    p["conn"][supply] = "5V"
    f = one(run([p]), "mod.supply_range", "failed")
    assert f.severity == "danger" and "absolute maximum" in f.message  # class A2 source may be hard: danger stands


def test_oled_on_3v3_passes_supply():
    assert mk.findings(run([oled("U1")]), "mod.supply_range")[0].status == "passed"


def test_hd44780_default_is_the_5v_table_and_3v3_variant():
    base = {"VCC": "5V", "GND": "GND", "RW": "GND"}
    assert one(mk.run(parts=[mk.mod("U1", "hd44780", base)]), "mod.supply_range").status == "passed"
    f = one(mk.run(parts=[mk.mod("U1", "hd44780", {**base, "VCC": "3V3"})]), "mod.supply_range", "failed")
    assert f.severity == "caution" and "below the operating range" in f.message
    ok = mk.run(parts=[mk.mod("U1", "hd44780", {**base, "VCC": "3V3"}, variant="3v3")])
    assert one(ok, "mod.supply_range").status == "passed"


def test_max7219_and_tm1637_on_3v3_are_below_range():
    for mid, sup in (("max7219", "V+"), ("tm1637", "VDD")):
        f = one(mk.run(parts=[mk.mod("U1", mid, {sup: "3V3", "GND": "GND"})]), "mod.supply_range", "failed")
        assert f.severity == "caution", mid


# --- mod.display.sh1106_vs_ssd1306 --------------------------------------------------------------------------------
def test_sh1106_hint_only_for_ssd1306():
    f = one(run([oled("U1")]), "mod.display.sh1106_vs_ssd1306")
    assert f.status == "failed" and f.severity == "info" and "SH1106" in f.message
    assert f.source_ids == ["mod-display-sh1106-ds"]
    assert mk.findings(run([oled("U1", "sh1106", supply="VDD1")]), "mod.display.sh1106_vs_ssd1306") == []
    assert "mod_display_sh1106_vs_ssd1306" in mk.codes(run([oled("U1")]))


# --- mod.display.oled_two_per_bus ---------------------------------------------------------------------------------
def test_three_oleds_on_one_bus():
    r = run([oled("U1"), oled("U2", sa0="3V3"), oled("U3", "ssd1309")])
    f = one(r, "mod.display.oled_two_per_bus", "failed")
    assert f.severity == "caution" and set(f.refs) == {"U1", "U2", "U3"} and "mux" in f.message


def test_two_oleds_pass_and_qty_counts():
    r = run([oled("U1"), oled("U2", sa0="3V3")])
    assert one(r, "mod.display.oled_two_per_bus").status == "passed"
    r = run([oled("U1", qty=3)])
    assert one(r, "mod.display.oled_two_per_bus", "failed").refs == ["U1"]


def test_oleds_on_two_buses_pass():
    a = mk.i2c(8, 9) + mk.i2c(10, 11, net="SDA1")
    b = {**OLED_I2C, "SA0": "GND", "SCL": "SCL1", "SDA": "SDA1"}
    r = run([oled("U1"), oled("U2", sa0="3V3"), mk.mod("U3", "ssd1306", b)], assignments=a)
    assert one(r, "mod.display.oled_two_per_bus").status == "passed"


def test_no_oled_no_check():
    r = mk.run(parts=[mk.mod("U1", "tm1637", {"VDD": "5V", "GND": "GND"})])
    assert mk.check_of(r, "mod.display.oled_two_per_bus") is None


# --- mod.display.hd44780_rw_gnd -----------------------------------------------------------------------------------
def hd(rw, vcc="5V", variant=None, facts=None):
    conn = {"VCC": vcc, "GND": "GND", "RS": "GPIO1", "E": "GPIO2", "DB4": "GPIO4", "DB5": "GPIO5", "DB6": "GPIO6",
            "DB7": "GPIO7"}
    if rw is not None:
        conn["RW"] = rw
    return mk.mod("U1", "hd44780", conn, variant=variant, facts=facts)


HD_GPIO = [mk.assign("out", p) for p in (1, 2, 3, 4, 5, 6, 7)]


def hd_run(*a, **kw):
    return mk.run(assignments=HD_GPIO, parts=[hd(*a, **kw)], only=("mod.display.hd44780_rw_gnd",))


def test_hd44780_rw_on_gpio_at_5v_is_danger():
    f = one(hd_run("GPIO3"), "mod.display.hd44780_rw_gnd")
    assert f.status == "failed" and f.severity == "danger"
    assert "GPIO3" in f.message and "GPIO4" in f.message and "5" in f.message


def test_hd44780_rw_open_or_high_at_5v_is_danger():
    for rw in (None, "5V"):
        f = one(hd_run(rw), "mod.display.hd44780_rw_gnd")
        assert (f.status, f.severity) == ("failed", "danger"), rw
    assert "pull-up" in one(hd_run(None), "mod.display.hd44780_rw_gnd").message


def test_hd44780_rw_gnd_passes():
    assert one(hd_run("GND"), "mod.display.hd44780_rw_gnd").status == "passed"


def test_hd44780_at_3v3_rw_on_gpio_passes_and_open_rw_is_caution():
    assert one(hd_run("GPIO3", vcc="3V3", variant="3v3"), "mod.display.hd44780_rw_gnd").status == "passed"
    f = one(hd_run(None, vcc="3V3", variant="3v3"), "mod.display.hd44780_rw_gnd")
    assert (f.status, f.severity) == ("failed", "caution")


def test_hd44780_level_shifter_fact_passes():
    assert one(hd_run("GPIO3", facts={"level_shifter": True}), "mod.display.hd44780_rw_gnd").status == "passed"


def test_hd44780_unknown_vcc_or_esp_not_checked():
    f = one(hd_run("GPIO3", vcc="VLCD"), "mod.display.hd44780_rw_gnd")
    assert f.status == "not_checked" and "VCC unknown" in f.message
    r = mk.run(chip="nochip", assignments=HD_GPIO, parts=[hd("GPIO3")], only=("mod.display.hd44780_rw_gnd",))
    assert one(r, "mod.display.hd44780_rw_gnd").status == "not_checked"


# --- mod.display.max7219_vih --------------------------------------------------------------------------------------
def mx(vplus="5V", facts=None):
    return mk.mod("U1", "max7219", {"V+": vplus, "GND": "GND", "DIN": "GPIO11", "CLK": "GPIO12", "LOAD": "GPIO10"},
                  facts=facts)


MX_GPIO = [mk.assign("spi_mosi", 11), mk.assign("spi_sck", 12), mk.assign("spi_cs", 10)]


def mx_run(part, **kw):
    return mk.run(assignments=MX_GPIO, parts=[part], only=("mod.display.max7219_vih",), **kw)


def test_max7219_vih_at_5v_against_3v3_logic():
    f = one(mx_run(mx()), "mod.display.max7219_vih")
    assert (f.status, f.severity) == ("failed", "caution")
    assert "VIH 3.50 V" in f.message and "74AHCT125" in f.message and "GPIO11" in f.message


def test_max7219_vih_not_checked_outside_5v_10pct():
    r = mk.run(assignments=MX_GPIO, parts=[mx("VP4")], options={"rails": {"VP4": 4.2}},
               only=("mod.display.max7219_vih",))
    f = one(r, "mod.display.max7219_vih")
    assert f.status == "not_checked" and "±10 %" in f.message
    assert one(mx_run(mx("VX")), "mod.display.max7219_vih").status == "not_checked"  # V+ unknown


def test_max7219_vih_level_shifter_and_no_gpio():
    assert one(mx_run(mx(facts={"level_shifter": True})), "mod.display.max7219_vih").status == "passed"
    p = mk.mod("U1", "max7219", {"V+": "5V", "GND": "GND"})
    assert mk.findings(mk.run(parts=[p], only=("mod.display.max7219_vih",)), "mod.display.max7219_vih") == []


def test_max7219_vih_without_esp_values_not_checked():
    r = mk.run(chip="nochip", assignments=MX_GPIO, parts=[mx()], only=("mod.display.max7219_vih",))
    assert one(r, "mod.display.max7219_vih").status == "not_checked"


# --- mod.display.tm1637_not_i2c -----------------------------------------------------------------------------------
def test_tm1637_on_the_i2c_bus_is_flagged():
    p = mk.mod("U2", "tm1637", {"VDD": "5V", "GND": "GND", "CLK": "SCL0", "DIO": "SDA0"})
    f = one(run([oled("U1"), p]), "mod.display.tm1637_not_i2c")
    assert (f.status, f.severity) == ("failed", "caution") and "not I²C" in f.message
    assert f.source_ids == ["mod-display-tm1637-en"]
    # also without any I²C device: the assignment modes mark the nets
    assert one(run([p]), "mod.display.tm1637_not_i2c").status == "failed"


def test_tm1637_on_own_gpios_passes_and_open_is_skipped():
    p = mk.mod("U2", "tm1637", {"VDD": "5V", "GND": "GND", "CLK": "GPIO4", "DIO": "GPIO5"})
    a = mk.i2c() + [mk.assign("out", 4), mk.assign("out", 5)]
    assert one(run([oled("U1"), p], assignments=a), "mod.display.tm1637_not_i2c").status == "passed"
    q = mk.mod("U2", "tm1637", {"VDD": "5V", "GND": "GND"})
    assert mk.findings(run([q]), "mod.display.tm1637_not_i2c") == []


def test_tm1637_never_joins_an_i2c_bus():
    p = mk.mod("U2", "tm1637", {"VDD": "5V", "GND": "GND", "CLK": "SCL0", "DIO": "SDA0"})
    r = run([oled("U1"), p])
    assert r is not None
    devices = [d["ref"] for b in r.result["buses"] for s in b["segments"] for d in s["devices"]]
    assert devices == ["U1"]


# --- data corrections --------------------------------------------------------------------------------------------
def test_max7219_vih_supersedes_level_in_and_the_condition_is_read():
    rep = mk.run(assignments=MX_GPIO, parts=[mx()])
    codes = [w["code"] for w in rep.warnings]
    assert "mod_display_max7219_vih" in codes and "mod_level_in" not in codes
    assert [f.status for f in mk.findings(rep, "mod.level_in")] == ["failed"]  # computed, folded in
    rep = mk.run(assignments=MX_GPIO, parts=[mx("3V3")])
    got = mk.findings(rep, "mod.level_in")
    assert {f.status for f in got} == {"not_checked"} and "never interpolated" in got[0].message


def test_tm1637_pullup_quotes_the_10k_of_the_reference_circuit():
    import excerpts as ex

    m = modules.catalog().get("tm1637")
    req = next(r for r in m["requires"] if r["code"] == "pullup")
    assert req["value"] == "10k" and "10K" in req["evidence"] and req["page"] == 8
    segs = [s for e in ex.by_source("mod-display-tm1637*.txt")["mod-display-tm1637-en"] for s in e.page_segments(8)]
    assert any(ex.find_parts_in_order(req["evidence"], s) for s in segs)
