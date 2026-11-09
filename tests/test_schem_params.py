"""Parameter tables, value parsing and error envelopes (no drawing needed)."""
import pytest

from circuit_bench.bench_core import schematic
from circuit_bench.bench_core.contracts import validate_envelope

S3 = "esp32-s3-devkitc-1"


def test_every_block_has_a_parameter_table():
    cat = {b["block"]: b for b in schematic.blocks()}
    assert set(cat) == {"led", "npn_low_side", "button_pullup", "divider", "module", "level_shifter"}
    for b in cat.values():
        assert b["title"]
        for p in b["params"]:
            assert {"name", "type", "default", "required", "doc"} <= set(p)
            assert p["type"] in ("ohm", "volt", "text", "net", "choice", "id", "map")  # id, map: module blocks
            assert not (p["required"] and p["default"] is not None), p
            if p["type"] == "choice":
                assert p["default"] in p["choices"]
    required = {b: [p["name"] for p in cat[b]["params"] if p["required"]] for b in cat}
    assert required == {"led": ["r_series"], "npn_low_side": ["r_base"], "button_pullup": [], "divider": ["r1", "r2"],
                        "module": [], "level_shifter": []}


@pytest.mark.parametrize("text,ohms", [
    (1000, 1000.0), ("1000", 1000.0), ("4k7", 4700.0), ("4.7 kΩ", 4700.0), ("10 kΩ", 10000.0), ("220R", 220.0),
    ("1R5", 1.5), ("470 ohm", 470.0), ("1M", 1e6), ("2k2", 2200.0),
])
def test_parse_ohms(text, ohms):
    assert schematic.parse_ohms(text) == pytest.approx(ohms)


@pytest.mark.parametrize("bad", ["10m", "0", -5, "abc", "", True, None, "1e3", float("nan"), "4k7k"])
def test_parse_ohms_refuses(bad):
    with pytest.raises(ValueError):
        schematic.parse_ohms(bad)


@pytest.mark.parametrize("ohms,text", [(1000, "1 kΩ"), (4700, "4.7 kΩ"), (150, "150 Ω"), (10_000, "10 kΩ"),
                                       (1.5, "1.5 Ω"), (1_234_000, "1.234 MΩ")])
def test_format_ohms(ohms, text):
    assert schematic.format_ohms(ohms) == text


def test_volts():
    assert schematic.parse_volts("3V3") == pytest.approx(3.3)
    assert schematic.parse_volts("12 V") == 12.0 and schematic.parse_volts(5) == 5.0
    assert schematic.format_volts(12.0) == "+12 V" and schematic.format_volts(3.3) == "+3.3 V"
    for bad in ("230 V", 0, "x", True):
        with pytest.raises(ValueError):
            schematic.parse_volts(bad)


@pytest.mark.parametrize("block,params,kw,code", [
    ("relay", {}, {}, "invalid_args"),
    ("led", {}, {}, "invalid_args"),  # r_series required
    ("led", {"r_series": "abc"}, {}, "invalid_args"),
    ("led", {"r_series": 150, "colour": "red"}, {}, "invalid_args"),
    ("led", {"r_series": 150, "active": "sideways"}, {}, "invalid_args"),
    ("led", {"r_series": 150, "net": "GND"}, {}, "invalid_args"),
    ("led", {"r_series": 150, "net": "bad net!"}, {}, "invalid_args"),
    ("led", {"r_series": 150, "led": "x" * 25}, {}, "invalid_args"),
    ("led", {"r_series": 150, "led": "a\nb"}, {}, "invalid_args"),
    ("led", "r_series=150", {}, "invalid_args"),
    ("divider", {"r1": 1, "r2": 1, "net": "VSENSE", "input_net": "VSENSE"}, {}, "invalid_args"),
    ("divider", {"r1": 1, "r2": 1, "v_in": 230}, {}, "invalid_args"),
    ("npn_low_side", {"r_base": 1000, "supply": "12V"}, {}, "invalid_args"),
    ("npn_low_side", {"r_base": 1000}, {"gpio": 99}, "invalid_args"),
    ("npn_low_side", {"r_base": 1000}, {"gpio": "pin 14"}, "invalid_args"),
    ("npn_low_side", {"r_base": 1000}, {"gpio": True}, "invalid_args"),
    ("npn_low_side", {"r_base": 1000}, {"devkit": S3, "gpio": 26}, "unknown_pin"),
    ("npn_low_side", {"r_base": 1000}, {"devkit": "no-such-board", "gpio": 14}, "unknown_board"),
    ("npn_low_side", {"r_base": 1000}, {"devkit": 3, "gpio": 14}, "invalid_args"),
])
def test_bad_input_gives_an_error_envelope(block, params, kw, code):
    env = schematic.render(block, params, **kw)
    assert env["ok"] is False and env["error"]["code"] == code, env["error"]
    assert validate_envelope(env) == []
    assert env["action"] == "schematic.render"


def test_gpio_accepts_names_and_lower_case_nets():
    pytest.importorskip("schemdraw")
    env = schematic.render("npn_low_side", {"r_base": "1k", "net": "laser_en"}, devkit=S3, gpio="GPIO14")
    assert env["ok"], env["error"]
    assert env["result"]["wiring"][0] == {"from": "J1-20 · IO14", "to": "R1.1", "net": "LASER_EN"}
    assert env["summary"] == "NPN low-side driver (LASER_EN) on IO14 (J1-20): 4 parts, 7 wires."
