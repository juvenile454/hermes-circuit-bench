"""Unit parser: SI values from tool/UI input with units, prefixes and RKM codes (IEC 60062 style)."""
import pytest

from circuit_bench.bench_core import units
from circuit_bench.bench_core.contracts import BenchError


@pytest.mark.parametrize(("text", "value"), [
    # the four mandatory cases
    ("4k7", 4700.0),
    ("4.7 kΩ", 4700.0),
    ("10mA", 0.01),
    ("3V3", 3.3),
    # plain numbers and exponents
    ("10 mA", 0.01),
    ("0.01", 0.01),
    ("1e-3", 0.001),
    ("4.7e3", 4700.0),
    (".5", 0.5),
    ("-12.5 mA", -0.0125),
    ("+5 V", 5.0),
    ("−5 V", -5.0),  # U+2212 minus sign
    # prefixes (case-sensitive m/M; K is accepted as kilo)
    ("100n", 1e-7),
    ("100 nF", 1e-7),
    ("100nf", 1e-7),
    ("2.2 µF", 2.2e-6),
    ("2.2 μF", 2.2e-6),  # Greek mu U+03BC
    ("2.2uF", 2.2e-6),
    ("100 pF", 1e-10),
    ("1M", 1e6),
    ("1 MΩ", 1e6),
    ("1 mΩ", 1e-3),
    ("10K", 1e4),
    ("10 kohm", 1e4),
    ("4.7 kOhm", 4700.0),
    ("1 GHz", 1e9),
    ("300 ns", 3e-7),
    ("1 µs", 1e-6),
    ("12.5 mW", 0.0125),
    ("3.3v", 3.3),
    # ohm spellings
    ("470R", 470.0),
    ("470 Ω", 470.0),  # U+2126 ohm sign
    ("470 ohms", 470.0),
    # RKM codes
    ("1R5", 1.5),
    ("0R1", 0.1),
    ("R47", 0.47),
    ("2u2", 2.2e-6),
    ("4n7", 4.7e-9),
    ("1m5", 1.5e-3),
    ("4M7", 4.7e6),
    ("4k7Ω", 4700.0),
    ("4k7 ohm", 4700.0),
    ("1A5", 1.5),
    ("12V", 12.0),
    # whitespace variants
    (" 10 mA ", 0.01),
    ("4.7\u00a0kΩ", 4700.0),
    ("4.7\u202fk Ω", 4700.0),
])
def test_parse_quantity(text, value):
    assert units.parse_quantity(text) == pytest.approx(value, rel=1e-12)


def test_decimal_parsing_is_exact():
    # Decimal arithmetic: no 4700.000000000001 from 4.7 * 1000
    assert units.parse_quantity("4.7k") == 4700.0
    assert units.parse_quantity("10 mA") == 0.01
    assert units.parse_quantity("2.2 µF") == 2.2e-6


@pytest.mark.parametrize(("text", "value", "unit"), [
    ("4k7", 4700.0, None),
    ("4.7 kΩ", 4700.0, "Ω"),
    ("10mA", 0.01, "A"),
    ("3V3", 3.3, "V"),
    ("470R", 470.0, "Ω"),
    ("100 nF", 1e-7, "F"),
    ("1 kHz", 1e3, "Hz"),
    ("5", 5.0, None),
])
def test_parse_returns_unit(text, value, unit):
    got_value, got_unit = units.parse(text)
    assert got_value == pytest.approx(value, rel=1e-12)
    assert got_unit == unit


@pytest.mark.parametrize(("text", "unit", "value"), [
    ("10 mA", "A", 0.01),
    ("10m", "A", 0.01),
    ("4k7", "Ω", 4700.0),
    ("3V3", "V", 3.3),
    (3.3, "V", 3.3),
    (1000, "Ω", 1000.0),
])
def test_expected_unit(text, unit, value):
    assert units.parse_quantity(text, unit) == pytest.approx(value, rel=1e-12)


@pytest.mark.parametrize("bad", [
    "", "   ", "abc", "kΩ", "mA", "4k7k", "1..2", "1.2.3", "4,7k", "10 mA A", "10 xV", "1e", "e3",
    "3V3A", "1R5V", "R", "4 k 7", "4k7mA", "1e400", "nan", "inf", "--5", "5-", None, True, False, float("nan"),
    float("inf"), [1], {"v": 1},
])
def test_invalid_input_raises_invalid_args(bad):
    with pytest.raises(BenchError) as e:
        units.parse_quantity(bad)
    assert e.value.code == "invalid_args"
    assert e.value.hint


def test_decimal_comma_has_a_hint():
    with pytest.raises(BenchError) as e:
        units.parse_quantity("4,7 kΩ")
    assert "decimal point" in e.value.hint


@pytest.mark.parametrize(("text", "unit"), [("10 mA", "V"), ("3V3", "Ω"), ("4.7 kΩ", "A"), ("100 nF", "s")])
def test_unit_mismatch_is_invalid_args(text, unit):
    with pytest.raises(BenchError) as e:
        units.parse_quantity(text, unit)
    assert e.value.code == "invalid_args"
    assert unit in e.value.message


def test_unknown_expected_unit_is_a_programming_error():
    with pytest.raises(ValueError):
        units.parse_quantity("1", "furlong")


def test_to_si_names_the_parameter():
    with pytest.raises(BenchError) as e:
        units.to_si("ten", "A", "i_f")
    assert "i_f" in e.value.message
    assert units.to_si("10 mA", "A", "i_f") == 0.01
