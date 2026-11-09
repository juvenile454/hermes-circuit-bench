"""Quantities from tool and UI input: '4k7', '4.7 kΩ', '10mA', '3V3' -> SI floats.

Grammar (whitespace around the value is ignored, a decimal point is required for fractions):
- number with optional exponent, optional SI prefix, optional unit: ``10 mA``, ``4.7e3``, ``100nF``, ``2.2 µF``;
- RKM code (IEC 60062 style), the letter stands for the decimal point: ``4k7``, ``1R5``, ``R47``, ``3V3``, ``2u2``.
Prefixes are case-sensitive (``m`` milli, ``M`` mega); ``K`` is accepted as kilo. Units are case-insensitive.
Decimal arithmetic avoids float noise (``4.7k`` is exactly 4700.0).
"""
from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation

from .contracts import BenchError

UNITS: tuple[str, ...] = ("V", "A", "Ω", "F", "s", "W", "Hz")

_PREFIX_EXP = {"p": -12, "n": -9, "u": -6, "µ": -6, "μ": -6, "m": -3, "k": 3, "K": 3, "M": 6, "G": 9}
_UNIT_WORDS = {
    "v": "V", "volt": "V", "volts": "V",
    "a": "A", "amp": "A", "amps": "A",
    "ω": "Ω", "Ω": "Ω", "ohm": "Ω", "ohms": "Ω", "r": "Ω",
    "f": "F",
    "s": "s",
    "w": "W",
    "hz": "Hz",
}
# letters that may stand for the decimal point in an RKM code, with the unit they imply
_RKM_UNIT_MARKS = {"R": "Ω", "r": "Ω", "V": "V", "v": "V", "A": "A", "W": "W"}
_RKM = re.compile(r"^(\d+)([pnuµμmkKMG]|[RrVvAW])(\d+)(.*)$", re.DOTALL)
_RKM_LEADING_R = re.compile(r"^[Rr](\d+)(.*)$", re.DOTALL)
_NUMBER = re.compile(r"^([+\-\u2212]?)((?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?)(.*)$", re.DOTALL)
_WS = re.compile(r"\s+")
_HINT = "examples: 4k7, 4.7 kΩ, 10mA, 3V3, 100nF, 2.2e-6 (decimal point, SI prefixes p n u m k M G)"


def _bad(text: object, why: str = "") -> BenchError:
    msg = f"cannot read {text!r} as a quantity" + (f": {why}" if why else "")
    hint = _HINT
    if isinstance(text, str) and "," in text:
        hint = "use a decimal point, not a comma; " + _HINT
    return BenchError("invalid_args", msg, hint)


def _unit_word(word: str) -> str | None:
    if word in _UNIT_WORDS:
        return _UNIT_WORDS[word]
    return _UNIT_WORDS.get(word.lower())


def _tail(text: str, tail: str) -> tuple[int, str | None]:
    """Prefix exponent and unit from the text after the number ('' -> (0, None))."""
    tail = _WS.sub("", tail)
    if not tail:
        return 0, None
    unit = _unit_word(tail)
    if unit is not None:
        return 0, unit
    if tail[0] in _PREFIX_EXP:
        rest = tail[1:]
        if not rest:
            return _PREFIX_EXP[tail[0]], None
        unit = _unit_word(rest)
        if unit is not None:
            return _PREFIX_EXP[tail[0]], unit
    raise _bad(text, f"unknown unit or prefix {tail!r}")


def _finish(text: str, number: Decimal, exp: int, unit: str | None) -> tuple[float, str | None]:
    try:
        value = float(number.scaleb(exp))
    except (InvalidOperation, OverflowError):
        raise _bad(text, "out of range") from None
    if not math.isfinite(value):
        raise _bad(text, "out of range")
    return value, unit


def _parse_rkm(text: str, s: str) -> tuple[float, str | None] | None:
    m = _RKM.match(s)
    if m:
        whole, mark, frac, rest = m.groups()
        number = Decimal(f"{whole}.{frac}")
        rest_unit = None
        if _WS.sub("", rest):
            rest_unit = _unit_word(_WS.sub("", rest))
            if rest_unit is None:
                raise _bad(text, f"unknown unit {rest.strip()!r} after the code")
        if mark in _RKM_UNIT_MARKS:
            unit = _RKM_UNIT_MARKS[mark]
            if rest_unit is not None and rest_unit != unit:
                raise _bad(text, f"code {whole}{mark}{frac} is in {unit}, not {rest_unit}")
            return _finish(text, number, 0, unit)
        return _finish(text, number, _PREFIX_EXP[mark], rest_unit)
    m = _RKM_LEADING_R.match(s)
    if m:
        frac, rest = m.groups()
        rest_unit = _unit_word(_WS.sub("", rest)) if _WS.sub("", rest) else "Ω"
        if rest_unit != "Ω":
            raise _bad(text, "an R code is in Ω")
        return _finish(text, Decimal(f"0.{frac}"), 0, "Ω")
    return None


def parse(text: object) -> tuple[float, str | None]:
    """``(value_in_SI, unit or None)``. Numbers pass through. Raises BenchError ``invalid_args``."""
    if isinstance(text, bool) or not isinstance(text, int | float | str):
        raise _bad(text, "expected a number or text")
    if not isinstance(text, str):
        value = float(text)
        if not math.isfinite(value):
            raise _bad(text, "not a finite number")
        return value, None
    s = text.strip()
    if not s:
        raise _bad(text, "empty")
    if "," in s:
        raise _bad(text, "decimal comma")
    rkm = _parse_rkm(text, s)
    if rkm is not None:
        return rkm
    m = _NUMBER.match(s)
    if not m:
        raise _bad(text)
    sign, digits, tail = m.groups()
    try:
        number = Decimal(digits)
    except InvalidOperation:
        raise _bad(text) from None
    if sign in ("-", "\u2212"):
        number = -number
    exp, unit = _tail(text, tail)
    return _finish(text, number, exp, unit)


def parse_quantity(text: object, unit: str | None = None) -> float:
    """SI value of ``text`` (``parse_quantity("10 mA") -> 0.01``).

    With ``unit`` (one of UNITS) the text may omit the unit, but a different unit is ``invalid_args``.
    """
    if unit is not None and unit not in UNITS:
        raise ValueError(f"unknown unit {unit!r}")
    value, got = parse(text)
    if unit is not None and got is not None and got != unit:
        raise BenchError("invalid_args", f"expected a value in {unit}, got {got} ({text!r})",
                         f"give the value in {unit}, for example with a prefix: 10 m{unit}")
    return value


def to_si(value: object, unit: str, name: str) -> float:
    """Like parse_quantity, but the error names the parameter (for calculator inputs)."""
    try:
        return parse_quantity(value, unit)
    except BenchError as e:
        raise BenchError("invalid_args", f"{name}: {e.message}", e.hint) from None
