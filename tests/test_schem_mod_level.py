"""Block ``level_shifter``: one BSS138 channel per signal after NXP AN10441
(gate on the lower supply VDD1, source on the low-voltage side, drain on the high-voltage side, pull-ups on both
sides; VDD2 >= VDD1). 1 to 4 channels; the source id ``mod-level-an10441`` is pinned in
data/sources/mod-level.json; without that entry the tests feed it in (monkeypatch) and check the honest fallback.
"""
from __future__ import annotations

import json

import pytest
from test_schem_mod_module import S3, assumed, net_of, rows, svg_ok, texts

from circuit_bench.bench_core import boards, schematic, sources

pytest.importorskip("schemdraw")

LEVEL = schematic.LEVEL_SOURCE
SOURCES_DIR = sources.SOURCES_DIR


@pytest.fixture
def an10441(monkeypatch):
    """The AN10441 source as data/sources/mod-level.json pins it (the real entry when that file has it)."""
    base = sources.all_sources()
    base.setdefault(LEVEL, {"id": LEVEL, "title": "AN10441 Level shifting techniques in I2C-bus design (test stand-in)",
                            "url": "https://example.invalid/AN10441.pdf", "retrieved": "2026-11-08"})
    monkeypatch.setattr(sources, "_load", lambda: base)
    return base[LEVEL]


def _channel(env: dict, n: int, lv: str, hv: str, low: str = "3V3", high: str = "5V") -> None:
    """AN10441 Fig. 1 topology of channel n: Q<n>.G on VDD1, S on the low side, D on the high side, a pull-up per
    side to its supply."""
    q, r_lv, r_hv = f"Q{n}", f"R{2 * n - 1}", f"R{2 * n}"
    assert net_of(env, f"{q}.G") == low
    assert net_of(env, f"{q}.S") == lv and net_of(env, f"{r_lv}.1") == lv and net_of(env, f"{r_lv}.2") == low
    assert net_of(env, f"{q}.D") == hv and net_of(env, f"{r_hv}.1") == hv and net_of(env, f"{r_hv}.2") == high


@pytest.mark.parametrize("channels", [1, 2, 3, 4])
def test_channels_follow_an10441(an10441, channels):
    gpios = {str(n): 3 + n for n in range(1, channels + 1)}
    env = schematic.render("level_shifter", {"channels": channels, "gpios": gpios, "r_pullup": "10k"}, devkit=S3)
    svg_ok(env)
    parts = env["result"]["parts"]
    assert [p["ref"] for p in parts] == [x for n in range(1, channels + 1) for x in (f"Q{n}", f"R{2*n-1}", f"R{2*n}")]
    assert {(p["kind"], p["value"]) for p in parts} == {("transistor", "BSS138"), ("resistor", "10 kΩ")}
    for n in range(1, channels + 1):
        _channel(env, n, f"LV{n}", f"HV{n}")
        assert boards.header_of(S3, 3 + n) in next(x["nodes"] for x in env["result"]["nets"] if x["name"] == f"LV{n}")
    assert env["sources"][0]["id"] == LEVEL
    assert "source_pending" not in {w["code"] for w in env["warnings"]}
    shown = texts(env)
    assert shown.count("+3.3 V") == shown.count("+5 V") == channels
    assert {"G", "S", "D", "Q1 BSS138", "R1 10 kΩ", "HV1"} <= set(shown)
    assert len(env["result"]["wiring"]) == 7 * channels


def test_signal_names_name_both_sides(an10441):
    env = schematic.render("level_shifter", {"gpios": {"SDA": 8, "SCL": 9}}, devkit=S3)
    svg_ok(env)
    assert env["summary"] == ("BSS138 level shifter (AN10441): 2 channels 3V3 to 5V on IO8, IO9: 6 parts, 14 wires.")
    _channel(env, 1, "SDA", "SDA_5V")
    _channel(env, 2, "SCL", "SCL_5V")
    assert ("J1-12 · IO8", "Q1.S", "SDA") in rows(env) and ("J1-21 · 5V", "R2.2", "5V") in rows(env)
    assert ("J1-2 · 3V3", "Q1.G", "3V3") in rows(env)
    assert assumed(env)["r_pullup"] == "R"  # no value: drawn as R, sized with bench_calc
    assert "i2c_pullup" in next(a["reason"] for a in env["assumptions"] if a["key"] == "r_pullup")
    assert {"mosfet_pinout"} <= {w["code"] for w in env["warnings"]}


def test_one_gpio_is_channel_one_and_others_are_placeholders(an10441):
    env = schematic.render("level_shifter", {"channels": 3}, gpio=8, devkit=S3)
    svg_ok(env)
    assert net_of(env, "J1-12") == "LV1" and texts(env).count("GPIO") == 2
    assert "gpio_unassigned" in {w["code"] for w in env["warnings"]}


def test_other_supplies_and_project_rails(an10441):
    proj = {"id": "bench-l", "board": {"chip": "esp32s3", "devkit": S3}, "options": {"rails": {"VBUS": 12.0}},
            "assignments": [{"role": "DATA", "mode": "out", "pin": 8, "net": "DATA"}], "parts": []}
    env = schematic.render("level_shifter", {"channels": 1, "high_v": 12, "gpios": {"1": 8}}, project=proj)
    svg_ok(env)
    _channel(env, 1, "DATA", "DATA_VBUS", high="VBUS")
    assert "VBUS +12 V" in texts(env)
    env = schematic.render("level_shifter", {"channels": 1, "low_v": "1.8", "high_v": "3V3"})
    svg_ok(env)
    _channel(env, 1, "LV1", "HV1", low="1V8", high="3V3")
    assert "1V8 +1.8 V" in texts(env)


def test_equal_supplies_need_no_shift(an10441):
    env = schematic.render("level_shifter", {"channels": 1, "low_v": 3.3, "high_v": 3.3})
    assert env["ok"] and "level_shift_none" in {w["code"] for w in env["warnings"]}


@pytest.mark.parametrize("params,needle", [
    ({"low_v": 5, "high_v": 3.3}, "VDD2"),
    ({"channels": 5}, "one of 1, 2, 3, 4"),
    ({"channels": 2, "gpios": {"3": 8}}, "channels is 2"),
    ({"gpios": {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}}, "at most 4"),
    ({"gpios": {"GND": 1}}, "channel name"),
    ({"high_v": 230}, "voltage"),
    ({"r_pullup": "abc"}, "resistance"),
    ({"gpios": {"1": 8, "2": 8}}, "two channels"),
    ({"gpios": {"SDA": 8, "1": 9}}, "SDA"),
])
def test_bad_level_input(an10441, params, needle):
    env = schematic.render("level_shifter", params, devkit=S3)
    if needle == "SDA":  # a named channel takes the first free number: SDA -> 2, channel 1 = GPIO9
        svg_ok(env)
        assert net_of(env, "Q2.S") == "SDA" and net_of(env, "J1-15") == "LV1"
        return
    assert env["ok"] is False and needle in env["error"]["message"] + (env["error"].get("hint") or ""), env["error"]


def test_channels_grow_with_named_gpios_when_not_given(an10441):
    env = schematic.render("level_shifter", {"gpios": {"SDA": 8, "SCL": 9, "INT": 10}}, devkit=S3)
    svg_ok(env)
    assert len([p for p in env["result"]["parts"] if p["kind"] == "transistor"]) == 3


def test_without_the_pinned_source_the_render_says_so(monkeypatch):
    base = {k: v for k, v in sources.all_sources().items() if k != LEVEL}
    monkeypatch.setattr(sources, "_load", lambda: base)
    env = schematic.render("level_shifter", {"channels": 1})
    assert env["ok"] and LEVEL not in {s["id"] for s in env["sources"]}
    pending = next(w for w in env["warnings"] if w["code"] == "source_pending")
    assert pending["severity"] == "caution" and LEVEL in pending["message"]


def test_f_level_pins_the_cited_id():
    """When data/sources/mod-level.json is in the tree, it holds the id this block cites."""
    path = SOURCES_DIR / "mod-level.json"
    if not path.is_file():
        pytest.skip("data/sources/mod-level.json is missing")
    ids = {e["id"] for e in json.loads(path.read_text(encoding="utf-8"))}
    assert LEVEL in ids
    env = schematic.render("level_shifter", {"channels": 1})
    assert env["sources"][0]["id"] == LEVEL and "source_pending" not in {w["code"] for w in env["warnings"]}
