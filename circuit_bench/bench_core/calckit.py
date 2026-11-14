"""Public calculator kit.

New calculators live in ``bench_core/calcs/<kind>.py`` (auto-discovered in sorted order by calcs/__init__.py) and
use only this module, never the private helpers of calc.py. calc.py and calc_power.py register their six basic
calculators through the same ``register`` (order ``modspec.BASIC_CALCS`` first, then new kinds sorted by name).

Helpers (same behaviour as the calc.py originals they wrap):
- ``num(value, unit, name, *, allow_zero=False)``: SI number from number or text ("4k7", "3V3"); > 60 V -> the
  low-voltage error with warning ``low_voltage_only`` (inputs with unit "V" only).
- ``count(value, name)``, ``choice(value, options, name)``, ``series(value)``
- ``q(value, unit, digits=3)``: qty with rounded value; ``fmt(value, unit, digits=3)``: display text
- ``step(name, expr, value, unit, digits=3)``: one intermediate step
- ``action(action_name)``: decorator, turns BenchError/TypeError/ValueError into error envelopes (never raises)
- re-exported: ``BenchError, assumption, check, envelope, fail, warning`` (contracts), ``sources``, ``parts``,
  ``eseries``, ``units``, ``RULE`` ("rule-of-thumb" source id), ``LOW_VOLTAGE_MAX_V``.

``register(kind, fn, params, *, title, group, summary)``:
- ``kind``: ``[a-z0-9_]{2,24}``, action ``calc.<kind>`` must be in contracts.ACTIONS;
- ``params``: ((name, unit, required, default), ...) with unit in "V","A","Ω","F","Hz","W","°C","K","s","",
  "str","range","int";
- ``title``: English, ≤ 40 chars ("INA219/INA226 shunt and calibration"); ``group`` in modspec.CALC_GROUPS;
  ``summary``: one English sentence ≤ 120 chars for ``bench_calc action=list`` and the desktop card.
- duplicate kind -> ValueError.

Registry views (everything else derives from these; no literal lists elsewhere):
- ``kinds()`` -> tuple in order; ``meta()`` -> [{kind, title, group, summary, params: [{name, unit, required,
  default}]}]; ``run(kind, params)`` -> envelope (unknown kind -> BenchError invalid_args as calc.run did).
- also: ``get(kind)`` (entry), ``params(kind)``, ``problems()``, ``listing(compact=False)`` -> envelope
  ``calc.list`` with result {calculators: meta(), groups} (GET /calc); ``compact=True`` (bench_calc action=list)
  replaces each ``params`` list by one ``inputs`` text.

Implementation notes:
- The registry fills itself on first use of a view (``kinds``/``meta``/``run``/``params``/``get``): it imports calc.py
  (which registers the basics and imports calc_power.py) and then every module of ``calcs/`` in sorted order. A
  calcs module that fails to import is skipped and listed in ``problems()`` (a test keeps that list empty), so one
  broken file never takes the other calculators down.
- ``run`` refuses any input with unit "V" above ``LOW_VOLTAGE_MAX_V`` before the calculator runs (generic 60 V rule),
  with the same envelope ``num`` produces.
- ``unregister(kind)`` exists for tests (temporary calculators) only.
"""
from __future__ import annotations

import functools
import importlib
import inspect
import logging
import math
import pkgutil
import re
import threading
from collections.abc import Callable
from typing import Any

from . import contracts, eseries, modspec, parts, sources, units
from .contracts import BenchError, assumption, check, envelope, fail, format_si, qty, warning

__all__ = [
    "LOW_VOLTAGE_MAX_V", "LOW_VOLTAGE_TEXT", "PARAM_UNITS", "REGISTRY", "RULE", "BenchError", "action", "assumption", "listing",
    "check", "choice", "count", "envelope", "eseries", "fail", "fmt", "get", "kinds", "meta", "num", "params", "parts",
    "problems", "q", "register", "run", "series", "sig", "sources", "step", "units", "unregister", "warning",
]

logger = logging.getLogger(__name__)

RULE = "rule-of-thumb"
LOW_VOLTAGE_MAX_V = 60.0  # product rule, same as schematic.MAX_VOLTS (inclusive: 60 V passes, anything above fails)
LOW_VOLTAGE_TEXT = ("Circuit Bench covers low-voltage circuits only, up to 60 V (product rule). Never use these "
                    "calculators for mains or other high voltages.")
PARAM_UNITS: frozenset[str] = frozenset({"V", "A", "Ω", "F", "Hz", "W", "°C", "K", "s", "", "str", "range", "int"})
KIND_RE = re.compile(r"^[a-z0-9_]{2,24}$")
TITLE_MAX = 40
SUMMARY_MAX = 120

REGISTRY: dict[str, dict[str, Any]] = {}
_LOCK = threading.RLock()
_LOADED = False
_PROBLEMS: list[str] = []


# --- helpers (moved here from calc.py; calc.py keeps its old private names as aliases) --------------------------------
def sig(x: float, digits: int = 6) -> float:
    """Round to ``digits`` significant digits (keeps JSON free of float noise such as 0.0025999999999999994)."""
    if x == 0 or not math.isfinite(x):
        return x
    return round(x, digits - 1 - math.floor(math.log10(abs(x))))


def q(value: float, unit: str, digits: int = 3) -> dict[str, Any]:
    out = qty(value, unit, digits)  # display from the unrounded value
    out["value"] = sig(float(value))
    return out


def fmt(value: float, unit: str, digits: int = 3) -> str:
    return format_si(value, unit, digits)


class _AboveLowVoltage(BenchError):
    """invalid_args for a voltage above LOW_VOLTAGE_MAX_V; ``action`` adds the warning ``low_voltage_only``."""


def _above_low_voltage(name: str, v: float) -> _AboveLowVoltage:
    return _AboveLowVoltage("invalid_args", f"{name} {fmt(v, 'V')} is above 60 V: Circuit Bench is for low voltage "
                            "only (product rule)", f"give {name} up to 60 V; mains and high-voltage circuits are "
                            "out of scope")


def _low_voltage_fail(action_name: str, e: BenchError) -> dict[str, Any]:
    return fail(action_name, e.code, e.message, e.hint, warnings=[warning("low_voltage_only", "danger", LOW_VOLTAGE_TEXT)])


def num(value: object, unit: str, name: str, *, allow_zero: bool = False) -> float:
    if value is None:
        raise BenchError("invalid_args", f"{name} is required", f"give {name} in {unit}")
    v = units.to_si(value, unit, name)
    if v < 0 or (v == 0 and not allow_zero):
        raise BenchError("invalid_args", f"{name} must be {'>= 0' if allow_zero else 'positive'}, got {fmt(v, unit)}",
                         f"give {name} as a positive value in {unit}")
    if unit == "V" and v > LOW_VOLTAGE_MAX_V:
        raise _above_low_voltage(name, v)
    return v


def count(value: object, name: str) -> float:
    try:
        v, unit = units.parse(value)
    except BenchError as e:
        raise BenchError("invalid_args", f"{name}: {e.message}", e.hint) from None
    if unit is not None:
        raise BenchError("invalid_args", f"{name} is a plain number, got a value in {unit}", f"give {name} without a unit")
    if v <= 0:
        raise BenchError("invalid_args", f"{name} must be positive, got {v}", f"give {name} from the datasheet")
    return v


def choice(value: object, options: tuple[str, ...], name: str) -> str:
    if not isinstance(value, str) or value.lower() not in options:
        raise BenchError("invalid_args", f"{name} must be one of {', '.join(options)}, got {value!r}",
                         f"for example {name}={options[0]!r}")
    return value.lower()


def series(value: object) -> str:
    if not isinstance(value, str) or value.upper() not in eseries.SERIES:
        raise BenchError("invalid_args", f"series must be one of {', '.join(eseries.SERIES)}, got {value!r}",
                         "E12 is the common resistor range, E24 the finer one")
    return value.upper()


def step(name: str, expr: str, value: float, unit: str, digits: int = 3) -> dict[str, Any]:
    return {"name": name, "expr": expr, "value": q(value, unit, digits)}


def action(action_name: str) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    """Turn every failure into an error envelope (handlers never raise)."""
    def deco(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                return fn(*args, **kwargs)
            except _AboveLowVoltage as e:
                return _low_voltage_fail(action_name, e)
            except BenchError as e:
                return fail(action_name, e.code, e.message, e.hint)
            except TypeError as e:  # wrong or missing parameters
                return fail(action_name, "invalid_args", f"bad parameters: {e}", "see the parameter list of this calculator")
            except (ValueError, ArithmeticError) as e:
                return fail(action_name, "invalid_args", f"calculation failed: {e}",
                            "check the inputs: positive, finite, SI units")
        return wrapper
    return deco


# --- register ------------------------------------------------------------------------------------------------------
def _check_params(kind: str, fn: Callable[..., Any], params: Any) -> tuple[tuple[str, str, bool, Any], ...]:
    if not isinstance(params, tuple | list):
        raise ValueError(f"calc {kind}: params must be a tuple of (name, unit, required, default)")
    out: list[tuple[str, str, bool, Any]] = []
    for p in params:
        if not isinstance(p, tuple | list) or len(p) != 4:
            raise ValueError(f"calc {kind}: bad param {p!r}, expected (name, unit, required, default)")
        name, unit, required, default = p
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name):
            raise ValueError(f"calc {kind}: bad param name {name!r}")
        if unit not in PARAM_UNITS:
            raise ValueError(f"calc {kind}: param {name}: unit {unit!r} not in {sorted(PARAM_UNITS)}")
        if not isinstance(required, bool):
            raise ValueError(f"calc {kind}: param {name}: required must be a bool")
        out.append((name, unit, required, default))
    names = [p[0] for p in out]
    if len(set(names)) != len(names):
        raise ValueError(f"calc {kind}: duplicate param names")
    try:
        sig_params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return tuple(out)
    if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig_params.values()):
        unknown = [n for n in names if n not in sig_params]
        if unknown:
            raise ValueError(f"calc {kind}: params not accepted by the function: {', '.join(unknown)}")
    return tuple(out)


def register(kind: str, fn: Callable[..., dict[str, Any]], params: tuple[tuple[str, str, bool, Any], ...], *,
             title: str, group: str, summary: str) -> None:
    if not isinstance(kind, str) or not KIND_RE.fullmatch(kind):
        raise ValueError(f"calc kind must match {KIND_RE.pattern}, got {kind!r}")
    if f"calc.{kind}" not in contracts.ACTIONS:
        raise ValueError(f"calc {kind}: action calc.{kind} is not in contracts.ACTIONS (add it there first)")
    if not callable(fn):
        raise ValueError(f"calc {kind}: fn must be callable")
    if not isinstance(title, str) or not title.strip() or len(title) > TITLE_MAX:
        raise ValueError(f"calc {kind}: title must be 1..{TITLE_MAX} characters")
    if group not in modspec.CALC_GROUPS:
        raise ValueError(f"calc {kind}: group must be one of {', '.join(modspec.CALC_GROUPS)}")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > SUMMARY_MAX:
        raise ValueError(f"calc {kind}: summary must be 1..{SUMMARY_MAX} characters")
    spec = _check_params(kind, fn, params)
    with _LOCK:
        if kind in REGISTRY:
            raise ValueError(f"calc {kind}: registered twice")
        REGISTRY[kind] = {"kind": kind, "fn": fn, "params": spec, "title": title, "group": group, "summary": summary}


def unregister(kind: str) -> None:
    """Remove a calculator (tests with temporary calculators only)."""
    with _LOCK:
        REGISTRY.pop(kind, None)


# --- discovery -----------------------------------------------------------------------------------------------------
def _ensure() -> None:
    """Import calc.py (the six basics) and every calcs/*.py once (sorted)."""
    global _LOADED
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        _LOADED = True  # first, so a view used while calc.py imports does not recurse
        pkg = __name__.rsplit(".", 1)[0]
        try:
            importlib.import_module(f"{pkg}.calc")
            calcs = importlib.import_module(f"{pkg}.calcs")
        except BaseException:
            _LOADED = False
            raise
        for info in sorted(pkgutil.iter_modules(calcs.__path__), key=lambda m: m.name):
            if info.name.startswith("_"):
                continue
            try:
                importlib.import_module(f"{pkg}.calcs.{info.name}")
            except Exception as e:  # noqa: BLE001 - one broken calculator must not break the others
                _PROBLEMS.append(f"calcs/{info.name}.py: {type(e).__name__}: {e}")
                logger.warning("circuit-bench: calculator module calcs/%s.py not loaded (%s)", info.name, type(e).__name__)


def problems() -> list[str]:
    """Calculator modules that failed to load (empty in a healthy build)."""
    _ensure()
    return list(_PROBLEMS)


def kinds() -> tuple[str, ...]:
    _ensure()
    basics = [k for k in modspec.BASIC_CALCS if k in REGISTRY]
    return (*basics, *sorted(k for k in REGISTRY if k not in modspec.BASIC_CALCS))


def get(kind: str) -> dict[str, Any]:
    """Registry entry {kind, fn, params, title, group, summary}; unknown -> BenchError invalid_args."""
    _ensure()
    entry = REGISTRY.get(kind) if isinstance(kind, str) else None
    if entry is None:
        raise BenchError("invalid_args", f"unknown calculator {kind!r}", f"use one of {', '.join(kinds())}")
    return entry


def params(kind: str) -> tuple[tuple[str, str, bool, Any], ...]:
    return get(kind)["params"]


def _jsonable(value: Any) -> Any:
    return value if value is None or isinstance(value, str | int | float | bool) else str(value)


def meta() -> list[dict[str, Any]]:
    """Calculator list. Optional, from attributes of the calculator function: ``choices`` (dict or
    callable → dict: param → fixed values) adds ``choices`` to a param; ``one_of`` (input sets, at least one set
    complete) adds ``one_of`` to the calculator."""
    out = []
    for kind in kinds():
        e = REGISTRY[kind]
        ch = getattr(e["fn"], "choices", None)
        ch = (ch() if callable(ch) else ch) or {}
        m = {"kind": kind, "title": e["title"], "group": e["group"], "summary": e["summary"],
             "params": [{"name": n, "unit": u, "required": r, "default": _jsonable(d),
                         **({"choices": [str(c) for c in ch[n]]} if n in ch else {})} for n, u, r, d in e["params"]]}
        one = getattr(e["fn"], "one_of", None)
        if one:
            m["one_of"] = [list(s) for s in one]
        out.append(m)
    return out


def _inputs_text(spec: tuple[tuple[str, str, bool, Any], ...]) -> str:
    """'v_supply V, v_f V, i_f A; optional: series=E12' (compact input list for the model)."""
    def one(name: str, unit: str, default: Any) -> str:
        text = name + (f" {unit}" if unit not in ("", "str") else "")
        return text + (f"={default}" if default is not None else "")
    req = [one(n, u, None) for n, u, r, _d in spec if r]
    opt = [one(n, u, d) for n, u, r, d in spec if not r]
    return ", ".join(req) + (f"; optional: {', '.join(opt)}" if opt else "")


def listing(*, compact: bool = False) -> dict[str, Any]:
    """Envelope ``calc.list`` (GET /calc, bench_calc action=list): result {calculators: meta(), groups}.
    ``compact`` (tool): each calculator's ``params`` become one ``inputs`` text, so 16+ calculators stay small."""
    items = meta()
    if compact:
        items = [{**{k: m[k] for k in ("kind", "title", "group", "summary")},
                  "inputs": _inputs_text(REGISTRY[m["kind"]]["params"])} for m in items]
    summary = (f"{len(items)} calculators: {', '.join(m['kind'] for m in items)}. Call bench_calc with "
               "action=<kind> and inputs (text with units or SI).")
    return envelope("calc.list", summary, {"calculators": items, "groups": list(modspec.CALC_GROUPS)})


def run(kind: str, params: object) -> dict[str, Any]:
    """Run calculator ``kind`` with a parameter dict (tool and route input). An unknown kind raises BenchError
    ``invalid_args`` (there is no action name for it); everything else is an envelope."""
    entry = get(kind)
    action_name = f"calc.{kind}"
    if not isinstance(params, dict):
        return fail(action_name, "invalid_args", "parameters must be an object", "for example {\"v_supply\": \"3V3\"}")
    spec = entry["params"]
    names = [p[0] for p in spec]
    unknown = sorted(set(params) - set(names))
    if unknown:
        return fail(action_name, "invalid_args", f"unknown parameter(s): {', '.join(unknown)}", f"parameters: {', '.join(names)}")
    missing = [p[0] for p in spec if p[2] and params.get(p[0]) is None]
    if missing:
        return fail(action_name, "invalid_args", f"missing parameter(s): {', '.join(missing)}", f"parameters: {', '.join(names)}")
    clean = {k: v for k, v in params.items() if v is not None}
    for name, unit, _required, _default in spec:  # generic 60 V rule for every voltage input
        if unit != "V" or name not in clean:
            continue
        try:
            v = units.to_si(clean[name], "V", name)
        except (BenchError, TypeError, ValueError, ArithmeticError):
            continue  # the calculator reports the bad input itself
        if v > LOW_VOLTAGE_MAX_V:
            return _low_voltage_fail(action_name, _above_low_voltage(name, v))
    return entry["fn"](**clean)
