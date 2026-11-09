"""Module family logic: real catalog entries SN74HC595, SN74HC165, CD74HC4067, CD74HC4051, MAX98357A,
PCM5102A, INMP441 and the family rules in bench_core/modrules/logic.py. Every project is synthetic; values come from
data/modules/logic.json. The generic bus and electrical rules (level_out, unconnected, hazard) are checked as
well."""
from __future__ import annotations

import json
from pathlib import Path

import excerpts as ex
import modkit as mk
import pytest

from circuit_bench.bench_core import electrical, modules
from circuit_bench.bench_core.modrules import logic as lg

ROOT = Path(__file__).resolve().parent.parent
LOGIC = {m["id"]: m for m in json.loads((ROOT / "circuit_bench" / "data" / "modules" / "logic.json")
                                        .read_text(encoding="utf-8"))["modules"]}
SOURCES = {s["id"]: s for s in json.loads((ROOT / "circuit_bench" / "data" / "sources" / "mod-logic.json")
                                          .read_text(encoding="utf-8"))}
ESP = electrical.get("esp32s3")
VIH = "mod.logic.hc_vih_5v_not_checked"
MUX = "mod.logic.mux_analog_vcc"
LR = "mod.logic.inmp441_lr"

# ESP GPIOs for the 3-wire shift interfaces and I²S
SHIFT_OUT = [mk.assign("out", 10, "SER"), mk.assign("out", 11, "SRCLK"), mk.assign("out", 12, "RCLK")]
SHIFT_IN = [mk.assign("out", 10, "LOAD"), mk.assign("out", 11, "CLK"), mk.assign("in", 13, "QH")]
MUX_SEL = [mk.assign("out", 4 + i, f"S{i}") for i in range(4)] + [mk.assign("adc", 1, "SIG")]
I2S_TX = [mk.assign("out", 5, "BCLK"), mk.assign("out", 6, "LRCLK"), mk.assign("out", 7, "DOUT")]
I2S_RX = [mk.assign("out", 5, "BCLK"), mk.assign("out", 6, "LRCLK"), mk.assign("in", 7, "SD0")]


def run(*parts, assignments=(), options=None, only=None):
    kw = {"only": only} if only else {}
    return mk.run(electrical=ESP, assignments=list(assignments), parts=list(parts), options=options, **kw)


def one(rep, rule_id, ref=None, status=None):
    fs = [f for f in mk.findings(rep, rule_id, status) if ref is None or ref in f.refs]
    assert len(fs) == 1, fs
    return fs[0]


def hc595(vcc="3V3", **extra):
    return {"VCC": vcc, "GND": "GND", "SER": "SER", "SRCLK": "SRCLK", "RCLK": "RCLK", "SRCLR": vcc, "OE": "GND",
            **extra}


def hc165(vcc="3V3", **extra):
    return {"VCC": vcc, "GND": "GND", "SH/LD": "LOAD", "CLK": "CLK", "QH": "QH", "CLK_INH": "GND", "SER": "GND",
            **{c: vcc for c in "ABCDEFGH"}, **extra}


def mux16(vcc="3V3", **extra):
    return {"VCC": vcc, "GND": "GND", "E": "GND", "COM": "SIG", **{f"S{i}": f"S{i}" for i in range(4)}, **extra}


def mux8(vcc="3V3", **extra):
    return {"VCC": vcc, "GND": "GND", "VEE": "GND", "E": "GND", "COM": "SIG", **{f"S{i}": f"S{i}" for i in range(3)},
            **extra}


def mic(sd="SD0", lr="GND", vdd="3V3", **extra):
    out = {"VDD": vdd, "GND": "GND", "SCK": "BCLK", "WS": "LRCLK", "SD": sd, "CHIPEN": vdd, **extra}
    if lr is not None:
        out["L/R"] = lr
    return out


# --- catalog and sources -----------------------------------------------------------------------------------------
def test_catalog_has_the_seven_parts_without_problems():
    cat = modules.Catalog.from_dir()
    assert cat.problems == []
    rows = {r["id"]: r for r in cat.search(limit=500)["items"]}
    want = {"sn74hc595": ("logic.shift_register", "A"), "sn74hc165": ("logic.shift_register", "A"),
            "cd74hc4067": ("logic.mux", "A"), "cd74hc4051": ("logic.mux", "A"), "max98357a": ("audio.amp", "A1"),
            "pcm5102a": ("audio.dac", "A"), "inmp441": ("audio.mic", "A1")}
    assert {k: (rows[k]["category"], rows[k]["class"]) for k in want} == want
    assert all(LOGIC[k]["kind"] == "ic" for k in want)
    assert cat.get("74hc595")["id"] == "sn74hc595" and cat.get("pcm5102")["id"] == "pcm5102a"


def test_sources_ti_direct_and_wayback_for_analog_and_tdk():
    for sid in ("mod-logic-sn74hc595-ds", "mod-logic-sn74hc165-ds", "mod-logic-cd74hc4067-ds",
                "mod-logic-cd74hc4051-ds", "mod-logic-pcm5102a-ds"):
        assert SOURCES[sid]["class"] == "A" and SOURCES[sid]["url"].startswith("https://www.ti.com/lit/ds/symlink/")
    assert "id_/https://www.analog.com/" in SOURCES["mod-logic-max98357a-ds"]["url"]
    assert "id_/https://invensense.tdk.com/" in SOURCES["mod-logic-inmp441-ds"]["url"]
    assert {SOURCES[s]["class"] for s in ("mod-logic-max98357a-ds", "mod-logic-inmp441-ds")} == {"A1"}


def test_hc_vih_values_are_conditioned_on_4v5_never_5v():
    for mid in ("sn74hc595", "sn74hc165", "cd74hc4067", "cd74hc4051"):
        io = LOGIC[mid]["io"]
        assert io["vih"]["value"] == 3.15 and io["vih"]["conditions"] == "VCC = 4.5 V"
        assert io["vil"]["value"] == 1.35 and "4.5 V" in io["vil"]["conditions"]


def test_i2s_signals_and_power_out():
    pins = lambda mid: {p["name"]: p["signal"] for p in LOGIC[mid]["pins"]}  # noqa: E731
    assert {k: pins("max98357a")[k] for k in ("BCLK", "LRCLK", "DIN", "OUTP", "OUTN")} == {
        "BCLK": "i2s_bclk", "LRCLK": "i2s_ws", "DIN": "i2s_din", "OUTP": "power_out", "OUTN": "power_out"}
    assert {k: pins("pcm5102a")[k] for k in ("BCK", "LRCK", "DIN")} == {
        "BCK": "i2s_bclk", "LRCK": "i2s_ws", "DIN": "i2s_din"}
    assert {k: pins("inmp441")[k] for k in ("SCK", "WS", "SD", "L/R")} == {
        "SCK": "i2s_bclk", "WS": "i2s_ws", "SD": "i2s_dout", "L/R": "mode_select"}
    assert [h["code"] for h in LOGIC["max98357a"]["hazards"]] == ["high_current"]


@pytest.mark.parametrize("table", ["HC_VIH", "MUX", "INMP441"])
def test_rule_limits_quote_the_excerpts(table):
    by_source = ex.by_source("mod-logic-*.txt")
    items = []
    if table == "HC_VIH":
        items = [(s["source"], s["page"], s["evidence"]) for s in lg.HC_VIH.values()]
    elif table == "MUX":
        items = [(s["source"], *s[k]) for s in lg.MUX.values() for k in ("op_ev", "abs_ev")]
    else:
        items = [(lg.INMP441["source"], *lg.INMP441[k]) for k in ("lr_ev", "level_ev", "stereo_ev")]
    for sid, page, parts in items:
        segs = [seg for e in by_source[sid] for seg in e.page_segments(page)]
        assert any(ex.find_parts_in_order(parts, seg) for seg in segs), (sid, page, parts)


# --- SN74HC595 ---------------------------------------------------------------------------------------------------
def test_hc595_at_3v3_vih_not_checked_without_warning():
    rep = run(mk.mod("U1", "sn74hc595", hc595("3V3")), assignments=SHIFT_OUT)
    f = one(rep, VIH)
    assert (f.status, f.severity) == ("not_checked", None)
    assert "not interpolated" in f.message and "3.15 V at VCC 4.50 V" in f.message
    assert one(rep, "mod.supply_range").status == "passed"
    assert "mod_logic_hc_vih_5v_not_checked" not in mk.codes(rep)


def test_hc595_at_5v_is_not_checked_with_the_4v5_reason():
    rep = run(mk.mod("U1", "sn74hc595", hc595("5V")), assignments=SHIFT_OUT)
    f = one(rep, VIH)
    assert (f.status, f.severity) == ("not_checked", "info")
    assert "at 5.00 V it is not given and is not interpolated" in f.message
    assert "VIH 3.15 V lies above the ESP's guaranteed VOH 2.64 V" in f.message
    assert "SER, SRCLK, RCLK" in f.message
    assert f.source_ids[0] == "mod-logic-sn74hc595-ds"
    assert "mod_logic_hc_vih_5v_not_checked" in mk.codes(rep)


def test_hc595_at_exactly_4v5_is_caution_not_guaranteed():
    rep = run(mk.mod("U1", "sn74hc595", hc595("V45")), assignments=SHIFT_OUT, options={"rails": {"V45": 4.5}})
    f = one(rep, VIH)
    assert (f.status, f.severity) == ("failed", "caution")
    assert "VIH is 3.15 V" in f.message and "2.64 V" in f.message and "not guaranteed" in f.message


def test_hc595_at_2v_and_6v_use_the_table_points():
    rep = run(mk.mod("U1", "sn74hc595", hc595("V2")), assignments=SHIFT_OUT, options={"rails": {"V2": 2.0}})
    assert one(rep, VIH).status == "passed"
    rep = run(mk.mod("U1", "sn74hc595", hc595("V6")), assignments=SHIFT_OUT, options={"rails": {"V6": 6.0}})
    f = one(rep, VIH)
    assert f.severity == "caution" and "4.20 V" in f.message


def test_hc595_level_shifter_fact_passes_and_no_gpio_means_no_check():
    rep = run(mk.mod("U1", "sn74hc595", hc595("5V"), facts={"level_shifter": True}), assignments=SHIFT_OUT)
    assert one(rep, VIH).status == "passed"
    rep = run(mk.mod("U1", "sn74hc595", hc595("5V")))  # no ESP pin on the control nets
    assert mk.findings(rep, VIH) == []


def test_hc595_unknown_vcc_is_not_checked():
    rep = run(mk.mod("U1", "sn74hc595", hc595("VX")), assignments=SHIFT_OUT)
    f = one(rep, VIH)
    assert (f.status, f.severity) == ("not_checked", "info") and "VCC unknown" in f.message


def test_hc595_supply_above_abs_max_is_danger():
    rep = run(mk.mod("U1", "sn74hc595", hc595("V8")), assignments=SHIFT_OUT, options={"rails": {"V8": 8.0}})
    f = one(rep, "mod.supply_range")
    assert (f.status, f.severity) == ("failed", "danger") and "7.00 V" in f.message


# --- SN74HC165 ---------------------------------------------------------------------------------------------------
def test_hc165_at_5v_vih_not_checked_and_qh_drives_5v():
    rep = run(mk.mod("U1", "sn74hc165", hc165("5V")), assignments=SHIFT_IN)
    f = one(rep, VIH)
    assert f.status == "not_checked" and "SH/LD, CLK" in f.message and "QH" not in f.message.split(":")[0]


def test_hc165_qh_at_5v_into_the_esp_is_danger_by_level_out():
    rep = run(mk.mod("U1", "sn74hc165", hc165("5V")), assignments=SHIFT_IN)
    f = one(rep, "mod.level_out", "U1")
    assert (f.status, f.severity) == ("failed", "danger") and "5.00 V" in f.message


def test_hc165_qh_at_3v3_is_fine_by_level_out():
    rep = run(mk.mod("U1", "sn74hc165", hc165("3V3")), assignments=SHIFT_IN)
    assert one(rep, "mod.level_out", "U1").status == "passed"


def test_hc165_supply_range():
    assert one(run(mk.mod("U1", "sn74hc165", hc165("3V3"))), "mod.supply_range").status == "passed"
    rep = run(mk.mod("U1", "sn74hc165", hc165("V65")), options={"rails": {"V65": 6.5}})
    assert one(rep, "mod.supply_range").severity == "caution"


# --- CD74HC4067 / CD74HC4051 -------------------------------------------------------------------------------------
def test_mux16_channel_on_5v_rail_at_3v3_is_danger():
    rep = run(mk.mod("U1", "cd74hc4067", mux16("3V3", I3="5V", I0="GND")), assignments=MUX_SEL)
    f = one(rep, MUX)
    assert (f.status, f.severity) == ("failed", "danger")
    assert "I3 on 5V = 5.00 V" in f.message and "3.80 V" in f.message
    assert f.source_ids == ["mod-logic-cd74hc4067-ds"]


def test_mux16_channel_just_above_vcc_is_caution():
    rep = run(mk.mod("U1", "cd74hc4067", mux16("3V3", I7="V34")), assignments=MUX_SEL, options={"rails": {"V34": 3.4}})
    f = one(rep, MUX)
    assert (f.status, f.severity) == ("failed", "caution") and "outside the analog range" in f.message


def test_mux16_rails_within_range_pass_and_signal_nets_are_not_claimed():
    rep = run(mk.mod("U1", "cd74hc4067", mux16("5V", I0="3V3", I1="GND", I2="POT")), assignments=MUX_SEL)
    f = one(rep, MUX)
    assert f.status == "passed" and "I0, I1" in f.message
    rep = run(mk.mod("U1", "cd74hc4067", mux16("3V3", I0="POT")), assignments=MUX_SEL)
    assert mk.findings(rep, MUX) == []


def test_mux16_unknown_vcc_is_not_checked():
    rep = run(mk.mod("U1", "cd74hc4067", mux16("VX", I0="3V3")), assignments=MUX_SEL)
    assert one(rep, MUX).status == "not_checked"


def test_mux16_at_5v_select_lines_not_checked_info():
    rep = run(mk.mod("U1", "cd74hc4067", mux16("5V")), assignments=MUX_SEL)
    f = one(rep, VIH)
    assert (f.status, f.severity) == ("not_checked", "info") and "S0, S1, S2, S3, E" not in f.message
    assert "S0, S1, S2, S3" in f.message


def test_mux8_uses_vee_as_the_lower_limit():
    rep = run(mk.mod("U1", "cd74hc4051", mux8("3V3", A0="5V")), assignments=MUX_SEL[:3] + MUX_SEL[4:])
    f = one(rep, MUX)
    assert f.severity == "danger" and "GND…VCC" not in f.message.split("Keep")[0]
    rep = run(mk.mod("U1", "cd74hc4051", mux8("3V3", A0="3V3", A7="GND")), assignments=MUX_SEL[:3] + MUX_SEL[4:])
    assert one(rep, MUX).status == "passed" and "VEE…VCC" in one(rep, MUX).message
    rep = run(mk.mod("U1", "cd74hc4051", mux8("3V3", VEE="NEG", A0="3V3")), assignments=MUX_SEL[:3] + MUX_SEL[4:])
    f = one(rep, MUX)
    assert f.status == "not_checked" and "VEE voltage unknown" in f.message


def test_mux8_vee_on_gnd_is_a_ground_pin():
    rep = run(mk.mod("U1", "cd74hc4051", mux8("3V3")))
    assert {f.status for f in mk.findings(rep, "mod.supply_range")} == {"passed"}
    assert next(p for p in LOGIC["cd74hc4051"]["pins"] if p["name"] == "VEE")["signal"] == "gnd"


def test_mux16_at_5v_com_on_the_adc_is_caution_by_level_out():
    rep = run(mk.mod("U1", "cd74hc4067", mux16("5V")), assignments=MUX_SEL)
    assert one(rep, "mod.level_out", "U1").severity == "caution"


# --- MAX98357A ---------------------------------------------------------------------------------------------------
def amp(vdd="5V", **extra):
    return {"VDD": vdd, "GND": "GND", "BCLK": "BCLK", "LRCLK": "LRCLK", "DIN": "DOUT", "SD_MODE": "3V3",
            "OUTP": "SPK+", "OUTN": "SPK-", **extra}


def test_max98357a_at_5v_supply_passes_and_hc_rule_ignores_it():
    rep = run(mk.mod("U1", "max98357a", amp("5V")), assignments=I2S_TX)
    assert one(rep, "mod.supply_range").status == "passed"
    assert mk.findings(rep, VIH) == []


def test_max98357a_supply_above_6v_is_danger():
    rep = run(mk.mod("U1", "max98357a", amp("V65")), assignments=I2S_TX, options={"rails": {"V65": 6.5}})
    f = one(rep, "mod.supply_range")
    assert (f.status, f.severity) == ("failed", "danger") and "6.00 V" in f.message


def test_max98357a_data():
    m = LOGIC["max98357a"]
    sd = next(p for p in m["pins"] if p["name"] == "SD_MODE")
    assert sd["internal_pull"]["down"]["value"] == 100e3
    assert m["current"]["peak"]["value"] == 2.8 and m["io"]["vih"]["value"] == 1.3


def test_max98357a_high_current_hazard_is_reported():
    rep = run(mk.mod("U1", "max98357a", amp("5V")), assignments=I2S_TX)
    assert any(f.status == "failed" and "1.6 A" in f.message for f in mk.findings(rep, "mod.hazard"))


# --- PCM5102A ----------------------------------------------------------------------------------------------------
def dac(v="3V3", **extra):
    return {"AVDD": v, "CPVDD": v, "DVDD": v, "AGND": "GND", "CPGND": "GND", "DGND": "GND", "BCK": "BCLK",
            "LRCK": "LRCLK", "DIN": "DOUT", "SCK": "GND", "FMT": "GND", "FLT": "GND", "DEMP": "GND", "XSMT": v, **extra}


def test_pcm5102a_at_3v3_passes_and_at_5v_is_danger():
    rep = run(mk.mod("U1", "pcm5102a", dac("3V3")), assignments=I2S_TX)
    assert {f.status for f in mk.findings(rep, "mod.supply_range")} == {"passed"}
    rep = run(mk.mod("U1", "pcm5102a", dac("5V")), assignments=I2S_TX)
    assert {f.severity for f in mk.findings(rep, "mod.supply_range")} == {"danger"}


def test_pcm5102a_dvdd_1v8_variant():
    v = dict(dac("3V3"), DVDD="V18")
    rep = run(mk.mod("U1", "pcm5102a", v, variant="dvdd-1v8"), options={"rails": {"V18": 1.8}})
    assert {f.status for f in mk.findings(rep, "mod.supply_range")} == {"passed"}
    rep = run(mk.mod("U1", "pcm5102a", v), options={"rails": {"V18": 1.8}})
    assert "failed" in {f.status for f in mk.findings(rep, "mod.supply_range")}


# --- INMP441 -----------------------------------------------------------------------------------------------------
def test_inmp441_left_on_gnd_passes():
    rep = run(mk.mod("M1", "inmp441", mic(lr="GND")), assignments=I2S_RX)
    f = one(rep, LR)
    assert f.status == "passed" and "left channel" in f.message


def test_inmp441_lr_open_is_caution():
    rep = run(mk.mod("M1", "inmp441", mic(lr=None)), assignments=I2S_RX)
    f = one(rep, LR)
    assert (f.status, f.severity) == ("failed", "caution") and "undefined" in f.message
    assert f.source_ids == ["mod-logic-inmp441-ds"]


def test_inmp441_stereo_pair_same_channel_collides_and_left_right_passes():
    rep = run(mk.mod("M1", "inmp441", mic(lr="GND")), mk.mod("M2", "inmp441", mic(lr="GND")), assignments=I2S_RX)
    f = one(rep, LR, status="failed")
    assert set(f.refs) == {"M1", "M2"} and "left channel" in f.message and "collide" in f.message
    rep = run(mk.mod("M1", "inmp441", mic(lr="GND")), mk.mod("M2", "inmp441", mic(lr="3V3")), assignments=I2S_RX)
    assert {f.status for f in mk.findings(rep, LR)} == {"passed"}
    assert "right channel" in one(rep, LR, "M2").message


def test_inmp441_three_on_one_sd_line_is_caution():
    rep = run(*(mk.mod(f"M{i}", "inmp441", mic(lr=lr)) for i, lr in enumerate(("GND", "3V3", "GND"))),
              assignments=I2S_RX)
    f = one(rep, LR, status="failed")
    assert len(f.refs) == 3 and "at most two" in f.message


def test_inmp441_lr_between_thresholds_and_gpio():
    rep = run(mk.mod("M1", "inmp441", mic(lr="V15")), assignments=I2S_RX, options={"rails": {"V15": 1.5}})
    f = one(rep, LR)
    assert f.severity == "caution" and "between VIL 825 mV and VIH 2.31 V" in f.message
    rep = run(mk.mod("M1", "inmp441", mic(lr="LRSEL")), assignments=[*I2S_RX, mk.assign("out", 15, "LRSEL")])
    assert one(rep, LR).status == "passed"


def test_inmp441_at_5v_exceeds_abs_max():
    rep = run(mk.mod("M1", "inmp441", mic(vdd="5V")), assignments=I2S_RX)
    f = one(rep, "mod.supply_range")
    assert (f.status, f.severity) == ("failed", "danger") and "3.63 V" in f.message


def test_inmp441_sd_pulldown_is_required_in_the_data():
    req = {r["code"]: r for r in LOGIC["inmp441"]["requires"]}
    assert req["pulldown"]["pins"] == ["SD"] and req["pulldown"]["value"] == "100k"


def test_inmp441_lr_open_is_also_reported_by_unconnected():
    rep = run(mk.mod("M1", "inmp441", mic(lr=None)), assignments=I2S_RX)
    assert any("L/R" in f.message for f in mk.findings(rep, "mod.unconnected", "failed"))


# --- data corrections and one cause -> one warning ---------------------------------------------------------------
def _quoted(source_id: str, page: int, evidence) -> bool:
    parts = evidence if isinstance(evidence, list) else [evidence]
    return any(ex.find_parts_in_order(parts, seg) for e in ex.by_source("mod-logic-*.txt")[source_id]
               for seg in e.page_segments(page))


def test_pcm5102a_dvdd_1v8_inputs_are_rated_2v25():
    var = next(v for v in LOGIC["pcm5102a"]["variants"] if v["id"] == "dvdd-1v8")
    f = var["overrides"]["io"]["v_in_max"]
    assert (f["value"], f["page"]) == (2.25, 6) and _quoted("mod-logic-pcm5102a-ds", 6, f["evidence"])
    assert LOGIC["pcm5102a"]["io"]["v_in_max"]["value"] == 3.9  # the 3.3 V DVDD row stays
    assert var["overrides"]["supplies"]["DVDD"]["abs_max"]["value"] == 3.9  # supply row "AVDD, CPVDD, DVDD"
    note = var["overrides"]["notes"][1]
    assert note["page"] == 33 and _quoted("mod-logic-pcm5102a-ds", 33, note["evidence"])
    cat = modules.catalog()
    assert cat.get("pcm5102a", "dvdd-1v8")["io"]["v_in_max"]["value"] == 2.25
    assert cat.get("pcm5102a", "dvdd-1v8")["io"]["vih"]["rel"] == 0.7


def test_pcm5102a_dvdd_1v8_driven_by_a_3v3_gpio_exceeds_the_input_rating():
    v = dict(dac("3V3"), DVDD="V18")
    rep = run(mk.mod("U1", "pcm5102a", v, variant="dvdd-1v8"), assignments=I2S_TX, options={"rails": {"V18": 1.8}})
    bad = [f for f in mk.findings(rep, "mod.level_in", "failed") if "2.25 V" in f.message]
    assert bad and {f.severity for f in bad} == {"danger"}
    rep = run(mk.mod("U1", "pcm5102a", dac("3V3")), assignments=I2S_TX)
    assert not [f for f in mk.findings(rep, "mod.level_in", "failed") if f.severity == "danger"]


def test_hc165_fmax_is_the_minimum_over_temperature():
    f = LOGIC["sn74hc165"]["interfaces"][0]["f_max_hz"]
    assert (f["value"], f["page"]) == (25e6, 7) and "−40 to 85 °C" in f["conditions"]
    assert _quoted("mod-logic-sn74hc165-ds", 7, f["evidence"])


def test_max98357a_levels_hold_at_vdd_5v_and_sleep_is_the_maximum():
    m = LOGIC["max98357a"]
    for k in ("vih", "vil"):
        assert "VDD = 5 V" in m["io"][k]["conditions"]
        assert _quoted("mod-logic-max98357a-ds", m["io"][k]["page"], m["io"][k]["evidence"])
    assert m["current"]["sleep"]["value"] == 2e-6 and "max" in m["current"]["sleep"]["conditions"]
    rep = run(mk.mod("U1", "max98357a", amp("5V")), assignments=I2S_TX)
    assert {f.status for f in mk.findings(rep, "mod.level_in")} == {"passed"}
    rep = run(mk.mod("U1", "max98357a", amp("3V3")), assignments=I2S_TX)
    got = mk.findings(rep, "mod.level_in")
    assert {f.status for f in got} == {"not_checked"} and not [f for f in got if f.severity]


@pytest.mark.parametrize("mid, conn", [("sn74hc595", hc595), ("sn74hc165", hc165), ("cd74hc4067", mux16),
                                       ("cd74hc4051", mux8)])
def test_hc_thresholds_at_3v3_give_no_level_finding(mid, conn):
    assigns = SHIFT_OUT if mid == "sn74hc595" else SHIFT_IN if mid == "sn74hc165" else MUX_SEL
    rep = run(mk.mod("U1", mid, conn("3V3")), assignments=assigns)
    for rid in ("mod.level_in", VIH):
        assert {f.status for f in mk.findings(rep, rid)} <= {"not_checked"}
        assert not [f for f in mk.findings(rep, rid) if f.severity]


def test_hc_vih_at_4v5_supersedes_the_generic_level_in():
    rep = run(mk.mod("U1", "sn74hc595", hc595("V45")), assignments=SHIFT_OUT, options={"rails": {"V45": 4.5}})
    assert one(rep, VIH, status="failed").severity == "caution"
    assert one(rep, "mod.level_in", status="failed")  # still computed, but folded into the family warning
    codes = [w["code"] for w in rep.warnings]
    assert "mod_logic_hc_vih_5v_not_checked" in codes and "mod_level_in" not in codes


def test_inmp441_open_lr_supersedes_unconnected_only_when_it_is_the_only_open_pin():
    rep = run(mk.mod("M1", "inmp441", mic(lr=None)), assignments=I2S_RX)
    codes = [w["code"] for w in rep.warnings]
    assert "mod_logic_inmp441_lr" in codes and "mod_unconnected" not in codes
    m = mic(lr=None)
    del m["CHIPEN"]
    rep = run(mk.mod("M1", "inmp441", m), assignments=I2S_RX)
    assert "mod_unconnected" in [w["code"] for w in rep.warnings]  # CHIPEN open stays visible
