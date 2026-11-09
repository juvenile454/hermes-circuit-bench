"""Generator parsers on synthetic input (no corpus needed)."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_pins_unit", ROOT / "scripts" / "gen_pins.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TABLE = """\
The ESP32-XX chip features 3 physical GPIO pins.

.. list-table::
    :header-rows: 1
    :widths: 8 12 12 20

    * - GPIO
      - Analog Function
      - RTC GPIO
      - Comments

    * - GPIO0
      - ADC1_CH0
      - RTC_GPIO0
      - Strapping pin

    * - GPIO1
      -
      -
      - GPI; JTAG

    * - GPIO4
      - ADC2_CH3
      -
      -

.. note::

    - Strapping pin: GPIO0 is a strapping pin.
    - GPI: GPIO1 can only be set as input mode
      and has no pulls.

---
"""


def test_parse_gpio_table(gen):
    rows, count = gen.parse_gpio_table(TABLE)
    assert count == 3
    assert [r["num"] for r in rows] == [0, 1, 4]
    assert rows[0]["adc"] == {"unit": 1, "channel": 0} and rows[0]["rtc_gpio"] == 0
    assert rows[1]["tags"] == ["GPI", "JTAG"] and rows[1]["adc"] is None and rows[1]["rtc_gpio"] is None
    assert rows[2]["adc"] == {"unit": 2, "channel": 3}


def test_parse_notes_joins_continuation_lines(gen):
    notes = gen.parse_notes(TABLE)
    assert notes == ["Strapping pin: GPIO0 is a strapping pin.", "GPI: GPIO1 can only be set as input mode and has no pulls."]
    assert [gen.note_key(n) for n in notes] == ["Strapping pin", "GPI"]


def test_table_errors_abort(gen):
    with pytest.raises(gen.GenError, match="unknown column"):
        gen.parse_gpio_table(TABLE.replace("RTC GPIO", "HP GPIO"))  # "LP GPIO" is a known column (ESP32-C6)
    with pytest.raises(gen.GenError, match="bad analog"):
        gen.parse_gpio_table(TABLE.replace("ADC2_CH3", "DAC_1"))
    with pytest.raises(gen.GenError, match="cells"):
        gen.parse_gpio_table(TABLE.replace("      - GPI; JTAG\n", ""))


def test_eval_macro_masks(gen):
    d = gen.parse_defines("""
#define SOC_GPIO_PIN_COUNT 40
#define SOC_GPIO_VALID_GPIO_MASK        (0xFFFFFFFFFFULL & ~(0ULL | BIT24 | BIT28 | BIT29 | BIT30 | BIT31))
#define SOC_GPIO_VALID_OUTPUT_GPIO_MASK (SOC_GPIO_VALID_GPIO_MASK & ~(0ULL | BIT34 | BIT35)) // comment
#define SOC_C3_MASK ((1U<<SOC_GPIO_PIN_COUNT) - 1)
#define SOC_FN(x) (x)
""")
    valid = gen.bits(gen.eval_macro("SOC_GPIO_VALID_GPIO_MASK", d))
    assert valid == set(range(40)) - {24, 28, 29, 30, 31}
    assert gen.bits(gen.eval_macro("SOC_GPIO_VALID_OUTPUT_GPIO_MASK", d)) == valid - {34, 35}
    assert gen.eval_macro("SOC_C3_MASK", d) == (1 << 40) - 1
    assert "SOC_FN" not in d
    with pytest.raises(gen.GenError):
        gen.eval_macro("SOC_MISSING", d)


def test_parse_adc_channels_requires_both_directions(gen):
    ok = "#define ADC1_GPIO36_CHANNEL 0\n#define ADC1_CHANNEL_0_GPIO_NUM 36\n"
    assert gen.parse_adc_channels(ok) == {(1, 0): 36}
    with pytest.raises(gen.GenError, match="disagree"):
        gen.parse_adc_channels(ok.replace("GPIO36_CHANNEL 0", "GPIO37_CHANNEL 0"))


def test_parse_iomux_functions(gen):
    text = """
#define IO_MUX_GPIO1_REG                  PERIPHS_IO_MUX_U0TXD_U
#define PERIPHS_IO_MUX_U0TXD_U            (DR_REG_IO_MUX_BASE +0x88)
#define FUNC_U0TXD_EMAC_RXD2                        5
#define FUNC_U0TXD_GPIO1                            2
#define FUNC_U0TXD_U0TXD                            0
#define IO_MUX_GPIO2_REG                  PERIPHS_IO_MUX_GPIO2_U
#define FUNC_GPIO2_GPIO2                            1
#define FUNC_GPIO2_GPIO2_0                          0
"""
    assert gen.parse_iomux(text) == {1: ["U0TXD", "GPIO1", "EMAC_RXD2"], 2: ["GPIO2"]}


def test_parse_touch_and_variants(gen):
    touch = (".. touch-chan-mapping\n\n.. list-table::\n    :header-rows: 1\n\n    * - Channel\n      - GPIO\n"
             "    * - CH0\n      - Internal\n    * - CH1\n      - IO1\n\n---\n")
    assert gen.parse_touch(touch) == {1: 1}
    ds = ("ESP32-S3-WROOM-1-N8 8 MB (Quad SPI) - –40 ~85\n"
          "ESP32-S3-WROOM-1-N16R8 16 MB (Quad SPI) 8 MB (Octal SPI) –40 ~65\n")
    assert gen.parse_variant_table(ds) == {"ESP32-S3-WROOM-1-N8": (8, None, 0),
                                           "ESP32-S3-WROOM-1-N16R8": (16, "octal", 8)}


def test_rule_table_is_well_formed(gen):
    from circuit_bench.bench_core import sources
    for chip, rules in gen.RULES.items():
        assert chip in gen.CHIPS
        for r in rules:
            assert {"id", "title", "severity", "pins", "modes", "message", "source_id", "evidence"} <= r.keys()
            sources.get(r["source_id"])
            if r.get("unverified"):
                assert r["severity"] == "info"
