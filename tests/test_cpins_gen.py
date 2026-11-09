"""Generator extensions on synthetic input (no corpus needed): LP GPIO column, full-width semicolon,
tab-indented footnotes, WROOM-1U rows, C6 module datasheet excerpt."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_pins_cpins_unit", ROOT / "scripts" / "gen_pins.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LP_TABLE = """\
The ESP32-XX chip features 3 physical GPIO pins (GPIO0 ~ GPIO2).

.. list-table::
    :header-rows: 1
    :widths: 8 12 12 20

    * - GPIO
      - Analog Function
      - LP GPIO
      - Comments

    * - GPIO0
      - ADC1_CH0
      - LP_GPIO0
      -

    * - GPIO1
      -
      -
      - GPI；Strapping pin

    * - GPIO2
      -
      -
      - USB-JTAG

.. note::

    - Strapping pin: GPIO1 is a strapping pin.
\t  - USB-JTAG: GPIO2 is used by USB-JTAG by default.
    - For chip variants with an SiP flash built in, GPIO2 is not led out.

---
"""


def test_lp_gpio_column_and_full_width_semicolon(gen):
    rows, count = gen.parse_gpio_table(LP_TABLE)
    assert count == 3 and [r["num"] for r in rows] == [0, 1, 2]
    assert (rows[0]["rtc_gpio"], rows[0]["rtc_name"]) == (0, "LP_GPIO0")
    assert rows[1]["rtc_gpio"] is None and rows[1]["tags"] == ["GPI", "Strapping pin"]


def test_bad_lp_cell_aborts(gen):
    with pytest.raises(gen.GenError, match="bad RTC cell"):
        gen.parse_gpio_table(LP_TABLE.replace("LP_GPIO0", "LPGPIO0"))


def test_notes_with_tab_indented_bullets(gen):
    notes = gen.parse_notes(LP_TABLE)
    assert len(notes) == 3
    assert [gen.note_key(n) for n in notes] == ["Strapping pin", "USB-JTAG", None]


def test_variant_table_reads_wroom_1u_rows(gen):
    ds = ("ESP32-S3-WROOM-1-N4R8 4 MB (Quad SPI) 8 MB (Octal SPI) –40 ~65\n"
          "ESP32-S3-WROOM-1U-N4R8 4 MB (Quad SPI) 8 MB (Octal SPI) –40 ~65\n")
    assert gen.parse_variant_table(ds) == {"ESP32-S3-WROOM-1-N4R8": (4, "octal", 8),
                                           "ESP32-S3-WROOM-1U-N4R8": (4, "octal", 8)}


MODULE = """\
@@ page 4
T able 1-1. ESP32-C6-MINI-1 (ANT) Series Comparison1
3The flash is integrated in the chip’s package. For specifications, refer to Section
At the core of the modules is ESP32-C6FH4/ESP32-C6FH8, a 32-bit RISC-V single-core processor. For more
@@ page 11
IO13 18 I/O/T GPIO13, USB_D+
IO14 19 I/O/T GPIO14
IO15 20 I/O/T GPIO15
RXD0 30 I/O/T U0RXD, GPIO17, FSPICS1
"""


def test_parse_module_excerpt(gen):
    m = gen.parse_module_excerpt(MODULE)
    assert m == {"module": "ESP32-C6-MINI-1", "chips": ["ESP32-C6FH4", "ESP32-C6FH8"], "in_package_flash": True,
                 "ios": {13, 14, 15}}
    plain = (MODULE.replace("MINI-1", "WROOM-1").replace("ESP32-C6FH4/ESP32-C6FH8", "ESP32-C6")
             .replace("3The flash is integrated in the chip’s package. For specifications, refer to Section\n", ""))
    m = gen.parse_module_excerpt(plain)
    assert (m["module"], m["chips"], m["in_package_flash"]) == ("ESP32-C6-WROOM-1", ["ESP32-C6"], False)


def test_parse_module_excerpt_aborts_on_inconsistent_text(gen):
    with pytest.raises(gen.GenError, match="in-package flash footnote"):  # FH chip without the footnote
        gen.parse_module_excerpt(MODULE.replace("The flash is integrated", "The flash is attached"))
    with pytest.raises(gen.GenError, match="in-package flash footnote"):  # plain chip with the footnote
        gen.parse_module_excerpt(MODULE.replace("ESP32-C6FH4/ESP32-C6FH8", "ESP32-C6"))
    with pytest.raises(gen.GenError, match="Table 1-1 title or chip sentence"):
        gen.parse_module_excerpt(MODULE.replace("At the core of the modules is", "Inside is"))


def test_rule_table_covers_every_registered_chip(gen):
    from circuit_bench.bench_core import chips, sources
    assert list(gen.CHIPS) == chips.ids()
    for chip, rules in gen.RULES.items():
        assert chip in gen.CHIPS
        for r in rules:
            sources.get(r["source_id"])
            for sid, quote in r.get("_also", []):
                sources.get(sid)
                assert quote.strip()
    for chip, variants in gen.VARIANTS.items():
        assert chip in gen.CHIPS and len({v["id"] for v in variants}) == len(variants)
