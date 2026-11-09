"""ESP32 chip DC characteristics: data/electrical/<chip>.json.

``get(chip)`` -> None when no file exists, else a dict with values resolved to volts/amps at the nominal
VDD 3.3 V (relative datasheet values such as 0.75 × VDD multiplied out):
    {"chip", "vdd": 3.3, "vih": V|None, "vil": V|None, "voh": V|None, "vol": V|None, "v_in_max": V|None,
     "vdd_abs_max": V|None, "ioh": A|None, "iol": A|None, "source_ids": [...], "conditions": str}
None per value = not in the datasheet text (rules then report not_checked, never a guess).
Additional keys (additive): "vdd_min", "vdd_max" (recommended supply range, V|None) and
"i_out_total_max" (absolute maximum of the cumulative IO output current of all pins, A|None).
``raw(chip)`` -> the file content (cited numbers F as in data/modules, for tests and citations).
``boards()`` -> {devkit id: {"rail_3v3_limit": F | None, ...}} from data/electrical/boards.json (optional file).

Resolution: ``{"value": x}`` -> x; ``{"rel": k, "of": "VDD"}`` -> k × 3.3 V; ``{"rel_offset": d, "of": "VDD"}`` ->
3.3 V + d. In the Espressif DC tables VDD is the I/O voltage of the pin's power domain; 3.3 V is the table
condition ("DC Characteristics (3.3 V, 25 °C)"). Results are rounded to 1e-9 (no float noise like 2.4749…).
Meaning: vih = VIH min, vil = VIL max, voh = VOH min, vol = VOL max, v_in_max = VIH max; ioh/iol are the
datasheets' typical source/sink currents at maximum drive strength (the datasheets give no min/max for them).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ELECTRICAL_DIR = Path(__file__).resolve().parent.parent / "data" / "electrical"

VDD_NOMINAL = 3.3
SUPPLY_NAMES = ("VDD",)  # 'of' values resolved at VDD_NOMINAL (the Espressif DC tables only use VDD)
UNITS = {"V", "A"}
IO_KEYS = ("vih", "vil", "voh", "vol", "v_in_max", "ioh", "iol")
_KINDS = ("value", "rel", "rel_offset")


def _check_f(where: str, f: Any) -> None:
    if not isinstance(f, dict):
        raise ValueError(f"{where}: expected a cited number, got {f!r}")
    kinds = [k for k in _KINDS if k in f]
    if len(kinds) != 1 or isinstance(f[kinds[0]], bool) or not isinstance(f[kinds[0]], (int, float)):
        raise ValueError(f"{where}: needs exactly one numeric value/rel/rel_offset")
    if kinds[0] != "value" and f.get("of") not in SUPPLY_NAMES:
        raise ValueError(f"{where}: relative value needs 'of' in {SUPPLY_NAMES}")
    if f.get("unit") not in UNITS:
        raise ValueError(f"{where}: unit {f.get('unit')!r} not in {sorted(UNITS)}")
    if isinstance(f.get("page"), bool) or not isinstance(f.get("page"), int) or f["page"] < 1:
        raise ValueError(f"{where}: page must be a positive int")
    ev = f.get("evidence")
    ok_list = isinstance(ev, list) and bool(ev) and all(isinstance(x, str) and x for x in ev)
    if not (isinstance(ev, str) and ev) and not ok_list:
        raise ValueError(f"{where}: evidence must be a string or a non-empty list of strings")


def _validate(chip: str, doc: Any) -> dict[str, Any]:
    name = f"electrical/{chip}.json"
    if not isinstance(doc, dict) or doc.get("schema") != 1 or doc.get("chip") != chip:
        raise ValueError(f"{name}: schema 1 and chip {chip!r} required")
    if not isinstance(doc.get("source_ids"), list) or not doc["source_ids"]:
        raise ValueError(f"{name}: source_ids required")
    for group in ("vdd", "io"):
        for key, f in (doc.get(group) or {}).items():
            _check_f(f"{name} {group}.{key}", f)
            if "source_id" in f and f["source_id"] not in doc["source_ids"]:
                raise ValueError(f"{name} {group}.{key}: source_id not in source_ids")
    return doc


@lru_cache(maxsize=32)
def _load(chip: str) -> dict[str, Any] | None:
    if not isinstance(chip, str) or not chip.isidentifier() or chip == "boards":
        return None
    path = ELECTRICAL_DIR / f"{chip}.json"
    if not path.is_file():
        return None
    return _validate(chip, json.loads(path.read_text(encoding="utf-8")))


def resolve(f: dict[str, Any] | None, vdd: float = VDD_NOMINAL) -> float | None:
    """Volts/amps of one cited number at supply ``vdd`` (None stays None)."""
    if f is None:
        return None
    if "value" in f:
        x = float(f["value"])
    elif "rel" in f:
        x = float(f["rel"]) * vdd
    else:
        x = vdd + float(f["rel_offset"])
    return round(x, 9)


def get(chip: str) -> dict[str, Any] | None:
    doc = _load(chip)
    if doc is None:
        return None
    vdd, io = doc.get("vdd") or {}, doc.get("io") or {}
    out: dict[str, Any] = {"chip": chip, "vdd": VDD_NOMINAL}
    for key in IO_KEYS:
        out[key] = resolve(io.get(key))
    out["vdd_abs_max"] = resolve(vdd.get("abs_max"))
    out["vdd_min"] = resolve(vdd.get("min"))
    out["vdd_max"] = resolve(vdd.get("max"))
    out["i_out_total_max"] = resolve(io.get("i_out_total_max"))
    out["source_ids"] = list(doc["source_ids"])
    out["conditions"] = str(doc.get("conditions", ""))
    return out


def raw(chip: str) -> dict[str, Any] | None:
    doc = _load(chip)
    return None if doc is None else json.loads(json.dumps(doc))  # deep copy: callers must not mutate the cache


@lru_cache(maxsize=1)
def _boards() -> dict[str, dict[str, Any]]:
    path = ELECTRICAL_DIR / "boards.json"
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = doc.get("boards") if isinstance(doc, dict) else None
    if not isinstance(entries, dict):
        raise ValueError("electrical/boards.json: expected {'boards': {id: {...}}}")
    for bid, b in entries.items():
        if b.get("rail_3v3_limit") is not None:
            _check_f(f"electrical/boards.json {bid}.rail_3v3_limit", b["rail_3v3_limit"])
    return entries


def boards() -> dict[str, dict[str, Any]]:
    return json.loads(json.dumps(_boards()))


def clear_cache() -> None:
    _load.cache_clear()
    _boards.cache_clear()
