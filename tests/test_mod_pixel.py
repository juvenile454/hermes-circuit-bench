"""Module family pixel: catalog entries (ST7789V, ILI9341, GC9A01, WS2812B, SK6812, APA102C), family rules
mod.pixel.ws2812_vih / mod.pixel.tft_spi_clock and the calculator calc.led_strip.

The generic tests (test_m0_modules_data/corpus) check the module evidence against the excerpts and the PDFs; this file
checks data/parts/pixel.json (calculator data) against the committed excerpts and the behaviour of rules and calc.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import excerpts as ex
import modkit as mk
from circuit_bench.bench_core import calckit, modules

ROOT = Path(__file__).resolve().parent.parent
PARTS = ROOT / "circuit_bench" / "data" / "parts" / "pixel.json"
SOURCES = ROOT / "circuit_bench" / "data" / "sources" / "mod-pixel.json"
EXCERPT = {"mod-pixel-ws2812b-ds": "mod-pixel-ws2812b.txt", "mod-pixel-sk6812-ds": "mod-pixel-sk6812.txt"}
SPI = [mk.assign("spi_sck", 12, "SCK"), mk.assign("spi_mosi", 11, "MOSI"), mk.assign("spi_cs", 10, "CS")]
TFT_CONN = {"SCL": "SCK", "SDA": "MOSI", "CSX": "CS", "GND": "GND"}


def _parts() -> list[dict]:
    return json.loads(PARTS.read_text(encoding="utf-8"))["parts"]


def _cited(part: dict) -> list[tuple[str, dict]]:
    out = []
    for key, f in part.items():
        if isinstance(f, dict) and "evidence" in f:
            out.append((key, f))
        elif isinstance(f, dict):
            out += [(f"{key}.{k}", g) for k, g in f.items() if isinstance(g, dict) and "evidence" in g]
    return out


# --- data ----------------------------------------------------------------------------------------------------------
def test_catalog_has_the_six_parts_with_their_source_class():
    modules.clear_cache()
    cat = modules.catalog()
    want = {"st7789v": "A2", "ili9341": "A2", "gc9a01": "B", "ws2812b": "A", "sk6812": "A2", "apa102c": "B"}
    assert {m: cat.get(m)["_class"] for m in want} == want
    assert cat.problems == []


@pytest.mark.parametrize("pid", ["WS2812B", "SK6812"])
def test_calculator_values_quote_the_excerpt(pid):
    part = next(p for p in _parts() if p["id"] == pid)
    xp = ex.parse(EXCERPT[part["source_id"]])
    assert xp.source_id == part["source_id"]
    cited = _cited(part)
    assert {k.split(".")[0] for k, _ in cited} >= {"i_channel", "i_quiescent", "vdd", "vih"}
    for key, f in cited:
        lines = [ln for seg in xp.page_segments(f["page"]) for ln in seg]
        assert any(f["evidence"] in ln for ln in lines), (pid, key, f["evidence"])


def test_calculator_numbers_match_their_quotes():
    ws, sk, _apa = _parts()
    assert ws["i_channel"]["value"] == 0.012 and "12mA" in ws["i_channel"]["evidence"]
    assert ws["i_quiescent"]["value"] == 0.0006 and "0.6mA" in ws["i_quiescent"]["evidence"]
    assert ws["vih"]["rel"] == 0.63 and "0.63VDD" in ws["vih"]["evidence"]
    assert re.search(r"\+3\.7~\+5\.3", ws["vdd"]["min"]["evidence"]) and (ws["vdd"]["min"]["value"], ws["vdd"]["max"]["value"]) == (3.7, 5.3)
    assert sk["i_channel"]["value"] == 0.013 and "IOUT=13mA" in sk["i_channel"]["evidence"]
    assert sk["i_quiescent"]["value"] == 0.001 and "IDD --- 1 ---" in sk["i_quiescent"]["evidence"]
    assert sk["vih"]["value"] == 3.4 and sk["vih"]["evidence"].startswith("VIH 3.4")
    assert (sk["vdd"]["min"]["value"], sk["vdd"]["max"]["value"]) == (4.5, 5.5) and "VDD=4.5 ~ 5.5V" in sk["vdd"]["min"]["evidence"]
    for p in (ws, sk):
        assert p["i_channel"]["basis"] == "test_condition" and p["verified"] is True
    # the module entries carry the same numbers as the calculator data
    cat = modules.catalog()
    assert cat.get("ws2812b")["io"]["vih"]["rel"] == ws["vih"]["rel"]
    assert cat.get("sk6812")["io"]["vih"]["value"] == sk["vih"]["value"]
    assert cat.get("ws2812b")["current"]["sleep"]["value"] == ws["i_quiescent"]["value"]
    assert cat.get("sk6812")["current"]["sleep"]["value"] == sk["i_quiescent"]["value"]


def test_class_b_parts_carry_no_evidence():
    apa = next(p for p in _parts() if p["id"] == "APA102C")
    assert apa["class"] == "B" and apa["verified"] is False and _cited(apa) == []
    srcs = {s["id"]: s for s in json.loads(SOURCES.read_text(encoding="utf-8"))}
    assert srcs[apa["source_id"]]["class"] == "B"
    for mid in ("gc9a01", "apa102c"):
        e = modules.catalog().get(mid)
        assert "supplies" not in e and "io" not in e and "current" not in e
        assert all(n.get("verified") is False for n in e["notes"])


# --- family rules --------------------------------------------------------------------------------------------------
def _pixel(parts, assigns, rule):
    modules.clear_cache()
    return mk.findings(mk.run(parts=parts, assignments=assigns), rule)


def _led(mid, rail="5V", facts=None, din="LED"):
    conn = {"VCC": rail, "GND": "GND", "DI": din, "CI": "CLK"} if mid == "apa102c" else \
        {"VDD": rail, "VSS": "GND", "DIN": din}
    return mk.mod("D1", mid, conn, facts=facts)


def test_ws2812b_at_5v_on_a_gpio_is_outside_the_guarantee():
    [f] = _pixel([_led("ws2812b")], [mk.assign("output", 4, "LED")], "mod.pixel.ws2812_vih")
    assert (f.status, f.severity) == ("failed", "caution")
    assert "3.15 V" in f.message and "V6.1" in f.message and "74AHCT125" in f.message
    # the generic mod.level_in on the same LED is folded in (supersedes): its ESP source moves here
    assert f.source_ids == ["mod-pixel-ws2812b-ds", "elec-ds-esp32s3"]
    rep = mk.run(assignments=[mk.assign("output", 4, "LED")], parts=[_led("ws2812b")])
    assert [w["code"] for w in rep.warnings if w["code"] in ("mod_level_in", "mod_pixel_ws2812_vih")] == [
        "mod_pixel_ws2812_vih"]


def test_sk6812_at_5v_needs_a_level_shifter():
    [f] = _pixel([_led("sk6812")], [mk.assign("output", 4, "LED")], "mod.pixel.ws2812_vih")
    assert (f.status, f.severity) == ("failed", "caution") and "3.40 V" in f.message and "GPIO high level 3.30 V" in f.message


def test_apa102c_is_only_a_hint():
    [f] = _pixel([_led("apa102c")], [mk.assign("spi_mosi", 11, "LED"), mk.assign("spi_sck", 12, "CLK")],
                 "mod.pixel.ws2812_vih")
    assert (f.status, f.severity) == ("failed", "info") and "unverified" in f.message and "DI, CI" in f.message


def test_level_shifter_fact_or_a_non_gpio_net_passes():
    [f] = _pixel([_led("ws2812b", facts={"level_shifter": True})], [mk.assign("output", 4, "LED")],
                 "mod.pixel.ws2812_vih")
    assert f.status == "passed"
    # data input on a net no GPIO drives (the output side of a buffer): nothing to say
    assert _pixel([_led("ws2812b", din="LED5V")], [mk.assign("output", 4, "LED")], "mod.pixel.ws2812_vih") == []


def test_ws2812b_at_3v3_is_not_level_checked_and_fails_the_supply_range():
    # VIH 0.63·VDD is given at VDD 5 V (table condition): at 3.3 V nothing is interpolated, like mod.level_in
    parts, assigns = [_led("ws2812b", rail="3V3")], [mk.assign("output", 4, "LED")]
    [f] = _pixel(parts, assigns, "mod.pixel.ws2812_vih")
    assert (f.status, f.severity) == ("not_checked", None) and "VDD 5 V" in f.message
    [s] = _pixel(parts, assigns, "mod.supply_range")
    assert (s.status, s.severity) == ("failed", "caution") and "3.70 V" in s.message


@pytest.mark.parametrize("mid, supply, mhz", [("st7789v", {"VDD": "3V3", "VDDI": "3V3"}, "15.2 MHz"),
                                              ("ili9341", {"VCI": "3V3", "VDDI": "3V3"}, "10.0 MHz")])
def test_tft_spi_clock_is_info(mid, supply, mhz):
    [f] = _pixel([mk.mod("U1", mid, {**TFT_CONN, **supply})], SPI, "mod.pixel.tft_spi_clock")
    assert (f.status, f.severity) == ("failed", "info") and mhz in f.message
    assert f.source_ids == [f"mod-pixel-{mid}-ds"]


def test_gc9a01_has_no_clock_limit():
    [f] = _pixel([mk.mod("U1", "gc9a01", {**TFT_CONN, "VCI": "3V3"})], SPI, "mod.pixel.tft_spi_clock")
    assert (f.status, f.severity) == ("not_checked", None)


def test_tft_at_5v_is_danger_from_the_generic_supply_rule():
    [f] = _pixel([mk.mod("U1", "st7789v", {**TFT_CONN, "VDD": "5V", "VDDI": "5V"})], SPI, "mod.supply_range")
    assert (f.status, f.severity) == ("failed", "danger") and "4.60 V" in f.message


def test_ili9341_vci_tied_to_vddi_at_5v_is_danger():
    [f] = _pixel([mk.mod("U1", "ili9341", {**TFT_CONN, "VCI": "5V"})], SPI, "mod.supply_range")
    assert (f.status, f.severity) == ("failed", "danger") and "VCI, VDDI" in f.message


def test_sk6812_on_3v3_is_below_its_range():
    [f] = _pixel([_led("sk6812", rail="3V3")], [mk.assign("output", 4, "LED")], "mod.supply_range")
    assert (f.status, f.severity) == ("failed", "caution") and "4.50 V" in f.message


def test_class_b_parts_have_no_supply_check():
    parts = [mk.mod("U1", "gc9a01", {**TFT_CONN, "VCI": "5V"}), _led("apa102c")]
    assigns = [*SPI, mk.assign("output", 4, "LED")]
    assert [f for f in _pixel(parts, assigns, "mod.supply_range") if f.status == "failed"] == []


def test_esp_values_missing_is_not_checked():
    modules.clear_cache()
    rep = mk.run(parts=[_led("ws2812b")], assignments=[mk.assign("output", 4, "LED")], electrical=SimpleNamespace(get=lambda chip: None, boards=dict))
    [f] = mk.findings(rep, "mod.pixel.ws2812_vih")
    assert f.status == "not_checked"


# --- calculator ----------------------------------------------------------------------------------------------------
def _calc(**p):
    return calckit.run("led_strip", p)


def test_led_strip_is_registered_in_group_light():
    m = next(m for m in calckit.meta() if m["kind"] == "led_strip")
    assert m["group"] == "light" and [p["name"] for p in m["params"]] == [
        "count", "part", "brightness", "v_supply", "chip"]


def test_ws2812b_strip_current_from_the_test_condition():
    e = _calc(count=60)
    r = e["result"]
    assert e["ok"] and r["i_led"]["value"] == pytest.approx(3 * 0.012 + 0.0006)
    assert r["i_total"]["value"] == pytest.approx(60 * 0.0366) and r["p_total"]["value"] == pytest.approx(5 * 2.196)
    assert r["i_dark"]["value"] == pytest.approx(0.036) and r["part"]["i_channel"]["basis"] == "test_condition"
    assert r["level_shifter"] == "recommended" and r["vih"]["value"] == pytest.approx(3.15)
    assert r["t_frame"]["value"] == pytest.approx(60 * 24 / 800e3 + 280e-6)
    st = {c["id"]: c["status"] for c in e["checks"]}
    assert st == {"calc.led_strip.supply": "passed", "calc.led_strip.level": "failed"}
    w = {x["code"]: x["severity"] for x in e["warnings"]}
    assert w == {"led_strip_level": "caution", "high_current": "info"}
    assert any("test condition" in a["reason"] for a in e["assumptions"])
    assert {s["id"] for s in e["sources"]} >= {"mod-pixel-ws2812b-ds", "elec-ds-esp32s3", "rule-of-thumb"}


def test_sk6812_needs_a_shifter_and_matches_its_power_rating():
    r = _calc(count=10, part="SK6812", brightness=0.5)["result"]
    assert r["i_led"]["value"] == pytest.approx(3 * 0.013 * 0.5 + 0.001) and r["level_shifter"] == "needed"
    full = _calc(count=1, part="sk6812")["result"]
    p_led = next(s for s in full["steps"] if s["name"] == "P_LED")["value"]["value"]
    assert p_led == pytest.approx(0.2)  # 5 V · (3 · 13 mA + 1 mA) = the 0.2 W rating of p. 1


def test_small_strip_has_no_high_current_hint_and_3v3_supply_needs_no_shifter():
    e = _calc(count=10, v_supply=3.3)
    assert "high_current" not in {w["code"] for w in e["warnings"]}
    assert e["result"]["level_shifter"] == "not_needed"
    assert {w["code"]: w["severity"] for w in e["warnings"]} == {"led_strip_supply": "caution"}


def test_supply_above_the_absolute_maximum_is_danger():
    e = _calc(count=10, v_supply="5.5V")
    assert {w["code"]: w["severity"] for w in e["warnings"]}["led_strip_supply"] == "danger"


def test_apa102c_is_unverified_and_never_hard():
    e = _calc(count=144, part="apa102c", brightness=0.5)
    assert e["ok"] and e["result"]["part"]["verified"] is False and "(unverified)" in e["summary"]
    assert {c["status"] for c in e["checks"]} == {"not_checked"}
    assert {w["severity"] for w in e["warnings"]} == {"info"}


@pytest.mark.parametrize("params", [{"count": 1.5}, {"count": 0}, {"count": 10, "brightness": 2},
                                    {"count": 10, "part": "ws2811"}, {"count": 10, "chip": "esp8266"},
                                    {"count": 10, "v_supply": 61}])
def test_bad_inputs_are_errors(params):
    e = _calc(**params)
    assert e["ok"] is False and e["error"]["code"] == "invalid_args"


# --- data corrections --------------------------------------------------------------------------------------------
def test_sk6812_vih_holds_at_vdd_5v_only():
    for rail, sev in (("3V3", None), ("V45", "info")):
        rep = mk.run(assignments=[mk.assign("output", 4, "LED")], parts=[_led("sk6812", rail=rail)],
                     options={"rails": {"V45": 4.5}})
        [f] = mk.findings(rep, "mod.pixel.ws2812_vih")
        assert (f.status, f.severity) == ("not_checked", sev) and "VDD = 5.0 V" in f.message
        assert not [x for x in mk.findings(rep, "mod.level_in") if x.severity in ("caution", "danger")]


def test_addressable_leds_carry_hazards_uniformly():
    cat = modules.catalog()
    # no maximum strip current in the WS2812B / WS2813 / SK6812 datasheets (LED current is only a test condition):
    # strip totals come from mod.power_budget and calc led_strip, not from a per-LED hazard
    for mid in ("ws2812b", "sk6812", "ws2813"):
        assert cat.get(mid)["hazards"] == [], mid
    [h] = cat.get("ws2815")["hazards"]  # the 12 V rail next to 5.7 V data inputs (VI abs max, p. 2)
    assert h["code"] == "high_current" and "12 V" in h["text"]
