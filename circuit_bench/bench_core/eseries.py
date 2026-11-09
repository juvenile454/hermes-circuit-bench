"""E series of preferred values (IEC 60063; values from the secondary source ``iec-60063``) and nearest()."""
from __future__ import annotations

import math
from decimal import Decimal

from .contracts import BenchError

SOURCE_ID = "iec-60063"
SERIES: tuple[str, ...] = ("E6", "E12", "E24")
MODES: tuple[str, ...] = ("up", "down", "near")

# one decade, mantissa 1.0 <= m < 10, as text so results are exact decimal values
_TABLES: dict[str, tuple[str, ...]] = {
    "E6": ("1.0", "1.5", "2.2", "3.3", "4.7", "6.8"),
    "E12": ("1.0", "1.2", "1.5", "1.8", "2.2", "2.7", "3.3", "3.9", "4.7", "5.6", "6.8", "8.2"),
    "E24": ("1.0", "1.1", "1.2", "1.3", "1.5", "1.6", "1.8", "2.0", "2.2", "2.4", "2.7", "3.0", "3.3", "3.6", "3.9",
            "4.3", "4.7", "5.1", "5.6", "6.2", "6.8", "7.5", "8.2", "9.1"),
}
_REL_TOL = 1e-9  # float noise around a table value counts as that value


def _series(series: object) -> str:
    name = series.upper() if isinstance(series, str) else None
    if name not in _TABLES:
        raise BenchError("invalid_args", f"unknown E series {series!r}", f"use one of {', '.join(SERIES)}")
    return name


def values(series: str) -> list[float]:
    """Mantissas of one decade (1.0 … 9.1)."""
    return [float(v) for v in _TABLES[_series(series)]]


def _value(mantissa: str, decade: int) -> float:
    return float(Decimal(mantissa).scaleb(decade))


def _candidates(value: float, series: str) -> list[float]:
    """Table values from one decade below to one decade above ``value``, ascending."""
    decade = math.floor(math.log10(value))
    table = _TABLES[series]
    return [_value(m, d) for d in (decade - 1, decade, decade + 1) for m in table] + [_value(table[0], decade + 2)]


def _check_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value <= 0:
        raise BenchError("invalid_args", f"E-series lookup needs a positive finite number, got {value!r}",
                         "give the exact value in SI units, for example 130.0 for 130 Ω")
    return float(value)


def _same(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=_REL_TOL)


def nearest(value: float, series: str = "E12", mode: str = "near") -> float:
    """E-series value for ``value``: ``up`` = smallest >= value, ``down`` = largest <= value,
    ``near`` = closest on a log scale (a tie goes up). Values within 1e-9 relative count as equal."""
    value = _check_value(value)
    name = _series(series)
    if mode not in MODES:
        raise BenchError("invalid_args", f"unknown mode {mode!r}", f"use one of {', '.join(MODES)}")
    cands = _candidates(value, name)
    for c in cands:
        if _same(c, value):
            return c
    if mode == "up":
        return next(c for c in cands if c > value)
    if mode == "down":
        return next(c for c in reversed(cands) if c < value)
    up = next(c for c in cands if c > value)
    down = next(c for c in reversed(cands) if c < value)
    d_up, d_down = math.log(up / value), math.log(value / down)
    return up if d_up <= d_down or math.isclose(d_up, d_down, rel_tol=1e-12) else down


def values_between(lo: float, hi: float, series: str = "E12") -> list[float]:
    """All E-series values in [lo, hi] (ascending; ends within 1e-9 relative count as inside)."""
    lo, hi = _check_value(lo), _check_value(hi)
    name = _series(series)
    if hi < lo:
        return []
    out: list[float] = []
    for decade in range(math.floor(math.log10(lo)) - 1, math.floor(math.log10(hi)) + 2):
        for m in _TABLES[name]:
            v = _value(m, decade)
            if (v >= lo or _same(v, lo)) and (v <= hi or _same(v, hi)):
                out.append(v)
    return out
