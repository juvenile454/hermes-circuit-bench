"""Part data from manufacturer datasheets (data/parts/*.json): hFE minimums of a transistor, MOSFET and
regulator values (power.json), and every further file (e.g. power2.json).

Every ``data/parts/*.json`` (sorted by file name) is read once: ``{"schema": 1, "note"?, "parts": [...]}``; each part
has ``id``, ``kind`` and ``source_id``, optional ``aliases``. A part name (id or alias, normalised) may appear only
once across all files, else loading fails (ValueError). Kind-specific shape checks: ``npn``/``pnp`` hFE rows,
``nmos`` R_DS(on) rows. ``find(name, kind)`` and ``ids_of(kind)`` serve new calculators (bench_core/calcs/*.py).
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from .contracts import BenchError

PARTS_DIR = Path(__file__).resolve().parent.parent / "data" / "parts"
_REL_TOL = 1e-6  # a collector current this close to a table row uses that row
BJT_KINDS: tuple[str, ...] = ("npn", "pnp")  # the transistors behind get()/ids()/hfe_min()


def normalize(name: str) -> str:
    return "".join(name.split()).upper()


def _check_part(part: Any, file: str) -> None:
    if not isinstance(part, dict) or not isinstance(part.get("id"), str) or not part["id"].strip():
        raise ValueError(f"{file}: every part needs an id")
    pid = part["id"]
    if not isinstance(part.get("kind"), str) or not part["kind"]:
        raise ValueError(f"{file}: {pid}: kind missing")
    if not part.get("source_id"):
        raise ValueError(f"{pid}: source_id missing")
    if part["kind"] in BJT_KINDS:
        rows = part.get("hfe", {}).get("rows", [])
        currents = [r["i_c"] for r in rows]
        if currents != sorted(currents) or len(set(currents)) != len(currents):
            raise ValueError(f"{pid}: hFE rows must be sorted by i_c without duplicates")
    if part["kind"] == "nmos":
        rows = part["r_ds_on"]["rows"]
        v_gs = [r["v_gs"] for r in rows]
        if not rows or v_gs != sorted(v_gs) or len(set(v_gs)) != len(v_gs) or any(r.get("max") is None for r in rows):
            raise ValueError(f"{pid}: R_DS(on) rows need a maximum, sorted by v_gs without duplicates")


@lru_cache(maxsize=1)
def _load_all() -> dict[str, dict[str, Any]]:
    """Every part of every data/parts/*.json by normalised id and alias (data order: files sorted by name)."""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(PARTS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != 1:
            raise ValueError(f"{path.name}: unknown schema")
        for part in data.get("parts") or []:
            _check_part(part, path.name)
            for name in (part["id"], *part.get("aliases", ())):
                key = normalize(name)
                if key in out:
                    raise ValueError(f"{path.name}: duplicate part name {name!r}")
                out[key] = part
    return out


def _of_kinds(kinds: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    return {k: p for k, p in _load_all().items() if p["kind"] in kinds}


def _load() -> dict[str, dict[str, Any]]:
    """Transistors (BJT_KINDS) by normalised name."""
    return _of_kinds(BJT_KINDS)


def _copy(rec: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(rec))  # a copy callers may change


def ids_of(kind: str) -> list[str]:
    """Part numbers of one kind in data order."""
    out: list[str] = []
    for p in _load_all().values():
        if p["kind"] == kind and p["id"] not in out:
            out.append(p["id"])
    return out


def find(name: object, kind: str | None = None) -> dict[str, Any] | None:
    """Record of a part by id or alias (a copy), optionally only of ``kind``; None if unknown."""
    if not isinstance(name, str) or not name.strip():
        return None
    rec = _load_all().get(normalize(name))
    if rec is None or (kind is not None and rec["kind"] != kind):
        return None
    return _copy(rec)


def ids() -> list[str]:
    """Transistor part numbers (the parts calc.npn knows)."""
    out: list[str] = []
    for p in _load().values():
        if p["id"] not in out:
            out.append(p["id"])
    return out


def get(name: object) -> dict[str, Any]:
    """Part record. Unknown name -> BenchError ``rule_data_missing`` (no sourced data, nothing is guessed)."""
    if not isinstance(name, str) or not name.strip():
        raise BenchError("invalid_args", f"part must be a part number, got {name!r}", f"known parts: {', '.join(ids())}")
    try:
        return _copy(_load()[normalize(name)])
    except KeyError:
        raise BenchError("rule_data_missing", f"no datasheet data for part {name!r}",
                         f"known parts: {', '.join(ids())}; or give hfe_min from your datasheet") from None


def hfe_min(name: object, i_c: float) -> dict[str, Any] | None:
    """Minimum DC current gain for collector current ``i_c`` (A) from the datasheet table.

    - ``i_c`` on a table row: that row's minimum (``basis: "row"``);
    - between two rows: the smaller of the two minimums (``basis: "between_rows"``; the datasheet gives no value
      in between, so this is an assumption the caller must show);
    - outside the table or no minimum on the rows: ``None`` (no sourced value).
    """
    part = get(name)
    if isinstance(i_c, bool) or not isinstance(i_c, int | float) or not math.isfinite(i_c) or i_c <= 0:
        raise BenchError("invalid_args", f"collector current must be positive, got {i_c!r}", "give I_C in A, for example 0.013")
    rows = [r for r in part.get("hfe", {}).get("rows", []) if r.get("min") is not None]
    base = {"part": part["id"], "source_id": part["source_id"], "conditions": part.get("conditions", "")}
    for r in rows:
        if math.isclose(r["i_c"], i_c, rel_tol=_REL_TOL):
            return {**base, "hfe_min": float(r["min"]), "basis": "row", "rows": [r]}
    for lo, hi in zip(rows, rows[1:], strict=False):
        if lo["i_c"] < i_c < hi["i_c"]:
            return {**base, "hfe_min": float(min(lo["min"], hi["min"])), "basis": "between_rows", "rows": [lo, hi]}
    return None


def hfe_range(name: object) -> tuple[float, float] | None:
    """Collector current range (A) covered by rows with a minimum, or None."""
    rows = [r for r in get(name).get("hfe", {}).get("rows", []) if r.get("min") is not None]
    return (rows[0]["i_c"], rows[-1]["i_c"]) if rows else None


def rating(name: object, key: str) -> dict[str, Any] | None:
    """A maximum rating such as ``i_c_max`` (``{"value", "unit", "evidence"}``) or None."""
    r = get(name).get("ratings", {}).get(key)
    return dict(r) if r else None


# --- power parts (power.json and later files): N-channel MOSFETs and linear regulators -----------------------------
POWER_KINDS: dict[str, str] = {"nmos": "N-channel MOSFET", "ldo": "linear regulator"}


def _load_power() -> dict[str, dict[str, Any]]:
    return _of_kinds(tuple(POWER_KINDS))


def power_ids(kind: str) -> list[str]:
    """Part numbers of one power kind (``nmos`` or ``ldo``) in data order."""
    return ids_of(kind)


def power_part(name: object, kind: str) -> dict[str, Any]:
    """Record of a MOSFET (``kind="nmos"``) or regulator (``"ldo"``). Unknown name -> ``rule_data_missing``."""
    label = POWER_KINDS[kind]
    if not isinstance(name, str) or not name.strip():
        raise BenchError("invalid_args", f"part must be a part number, got {name!r}", f"known {label}s: {', '.join(power_ids(kind))}")
    rec = _load_power().get(normalize(name))
    if rec is None or rec["kind"] != kind:
        raise BenchError("rule_data_missing", f"no datasheet data for {label} {name!r}",
                         f"known {label}s: {', '.join(power_ids(kind))}")
    return _copy(rec)


def r_ds_on_at(name: object, v_gs: float) -> dict[str, Any] | None:
    """Datasheet R_DS(on) row for a gate-source voltage ``v_gs`` (V): the row with the highest V_GS ≤ ``v_gs``.

    R_DS(on) falls as V_GS rises (datasheet curves), so that row's maximum bounds R_DS(on) at ``v_gs`` from above.
    ``None`` if every row needs a higher V_GS: then the datasheet does not specify the part at this gate voltage.
    """
    part = power_part(name, "nmos")
    if isinstance(v_gs, bool) or not isinstance(v_gs, int | float) or not math.isfinite(v_gs) or v_gs <= 0:
        raise BenchError("invalid_args", f"gate-source voltage must be positive, got {v_gs!r}", "give V_GS in V, for example 3.3")
    rows = [r for r in part["r_ds_on"]["rows"] if r["v_gs"] <= v_gs or math.isclose(r["v_gs"], v_gs, rel_tol=_REL_TOL)]
    if not rows:
        return None
    return {**rows[-1], "part": part["id"], "source_id": part["source_id"], "conditions": part["r_ds_on"].get("conditions", "")}


def clear_cache() -> None:
    _load_all.cache_clear()
