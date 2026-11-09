"""Calculator ``current_limit``: current limit of a motor driver from
the sense resistor and VREF, or the VREF to set for a target current.

Formulas and limits come from data/parts/motor.json (kind ``motor_driver``, each value with page and quote):
- A4988 (Allegro, p. 9): ``I_TripMAX = V_REF / (8 · R_S)``; VREF 0–4 V (p. 4), output ±2 A, SENSE ±0.5 V (p. 2).
- DRV8825 (TI, p. 12): ``I_FS = V_xREF / (5 · R_ISENSE)``; VREF 1–3.5 V recommended, 4 V absolute (p. 4),
  2.5 A continuous, ISENSE ±0.8 V (p. 4).
- DRV8833 (TI, p. 10): ``I_LIM = 200 mV / R_ISEN`` (no VREF pin); 1.5 A per bridge recommended (p. 5), OCP from 2 A.
- TMC2209 (Trinamic, p. 53): ``I_RMS = V_FS / (R_SENSE + 20 mΩ) · 1/√2 · V_VREF / 2.5 V`` (standalone, IRUN = 31,
  analog scaling); V_FS 325 mV (vsense 0) or 180 mV (vsense 1) (p. 78); VREF ≥ 2.5 V = 100 %, < 0.5 V not recommended
  (p. 53); 1.4 A RMS design guideline, 2.8 A peak (p. 75).
Directions: ``v_ref`` given -> current; ``i_target`` given -> VREF to set (exactly one of them; DRV8833 takes neither or
``i_target`` to compare). ``r_sense`` is always the user's value: carrier boards fit different resistors.
"""
from __future__ import annotations

import math
from typing import Any

from .. import calckit as ck
from ..calckit import BenchError, assumption, check, envelope, warning

ACTION = "calc.current_limit"
KIND = "motor_driver"
VSENSE = ("0", "1")
_EPS = 1e-9


def _driver(name: object) -> dict[str, Any]:
    ids = ck.parts.ids_of(KIND)
    rec = ck.parts.find(name, KIND) if isinstance(name, str) else None
    if rec is None:
        raise BenchError("invalid_args", f"driver must be one of {', '.join(i.lower() for i in ids)}, got {name!r}",
                         "for example driver='a4988'")
    return rec


def _f(x: float, unit: str) -> str:
    return ck.fmt(x, unit)


def _lim(rec: dict[str, Any], key: str) -> float | None:
    f = rec.get(key)
    return float(f["value"]) if isinstance(f, dict) and "value" in f else None


def _cite(rec: dict[str, Any], key: str) -> str:
    f = rec.get(key) or {}
    return f"{rec['id']} datasheet p. {f.get('page')}" + (f", {f['conditions']}" if f.get("conditions") else "")


class _Out:
    def __init__(self, rec: dict[str, Any]):
        self.rec = rec
        self.sid = rec["source_id"]
        self.checks: list[dict[str, Any]] = []
        self.warns: list[dict[str, Any]] = []

    def limit(self, cid: str, value: float, unit: str, key: str, what: str, sev: str, advice: str, *,
              above: bool = True) -> bool | None:
        """value ≤ limit (above=True) or ≥ limit (above=False); a failed check adds a warning. None = no limit."""
        lim = _lim(self.rec, key)
        if lim is None:
            return None
        ok = value <= lim + _EPS if above else value >= lim - _EPS
        rel = ("≤" if ok else ">") if above else ("≥" if ok else "<")
        self.checks.append(check(f"calc.current_limit.{cid}", "passed" if ok else "failed",
                                 f"{what} {_f(value, unit)} {rel} {_f(lim, unit)} ({_cite(self.rec, key)})"))
        if not ok:
            self.warns.append(warning(f"current_limit_{cid}", sev, f"{what} {_f(value, unit)} "
                                      f"{'exceeds' if above else 'is below'} {_f(lim, unit)} for the {self.rec['id']}. "
                                      f"{advice}", [self.sid]))
        return ok


def _vref_div(rec: dict[str, Any], r: float, v_ref: float | None, i_t: float | None, o: _Out
              ) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    k = float(rec["k"]["value"])
    steps = []
    if v_ref is not None:
        i = v_ref / (k * r)
        steps.append(ck.step("I", f"{_f(v_ref, 'V')} / ({k:g} · {_f(r, 'Ω')})", i, "A"))
        v = v_ref
    else:
        i = float(i_t or 0.0)  # the caller passes exactly one of v_ref / i_target
        v = i * k * r
        steps.append(ck.step("V_REF", f"{_f(i, 'A')} · {k:g} · {_f(r, 'Ω')}", v, "V"))
    v_sense = i * r
    steps.append(ck.step("V_SENSE", f"{_f(i, 'A')} · {_f(r, 'Ω')}", v_sense, "V"))
    v_abs = _lim(rec, "v_ref_abs_max")
    if v_abs is not None and v > v_abs + _EPS:
        o.limit("v_ref_abs_max", v, "V", "v_ref_abs_max", "V_REF", "danger",
                "This damages the REF input: use a larger R_SENSE or a lower current.")
    else:
        o.limit("v_ref_max", v, "V", "v_ref_max", "V_REF", "caution",
                "Outside the specified VREF range: use a larger R_SENSE or a lower current.")
    if _lim(rec, "v_ref_min") is not None:
        o.limit("v_ref_min", v, "V", "v_ref_min", "V_REF", "info",
                "The datasheet specifies the current accuracy from this VREF on; a smaller R_SENSE raises VREF.",
                above=False)
    o.limit("i_max", i, "A", "i_max", "Current", "danger",
            "Above the driver's output current rating: lower VREF.")
    o.limit("v_sense_max", v_sense, "V", "v_sense_max", "Sense voltage", "danger",
            "Above the absolute maximum of the sense pins.")
    res = {"i_limit": ck.q(i, "A"), "v_ref": ck.q(v, "V"), "v_sense": ck.q(v_sense, "V")}
    head = (f"V_REF {_f(v, 'V')} with R_SENSE {_f(r, 'Ω')} → {_f(i, 'A')}" if v_ref is not None
            else f"{_f(i, 'A')} with R_SENSE {_f(r, 'Ω')} needs V_REF {_f(v, 'V')}")
    return res, steps, head


def _fixed(rec: dict[str, Any], r: float, i_t: float | None, o: _Out
           ) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    vt = float(rec["v_trip"]["value"])
    i = vt / r
    steps = [ck.step("I_LIM", f"{_f(vt, 'V')} / {_f(r, 'Ω')}", i, "A")]
    res: dict[str, Any] = {"i_limit": ck.q(i, "A"), "v_ref": None, "v_sense": ck.q(vt, "V")}
    o.limit("i_max", i, "A", "i_max", "Current limit", "caution",
            "Above the recommended continuous current per bridge: use a larger R_ISEN.")
    o.limit("i_ocp", i, "A", "i_ocp_min", "Current limit", "caution",
            "The overcurrent protection may trip before the current limit: use a larger R_ISEN.")
    head = f"R_ISEN {_f(r, 'Ω')} → I_LIM {_f(i, 'A')}"
    if i_t is not None:
        r_need = vt / i_t
        steps.append(ck.step("R_ISEN for I_target", f"{_f(vt, 'V')} / {_f(i_t, 'A')}", r_need, "Ω"))
        res["r_sense_for_target"] = ck.q(r_need, "Ω")
        head += f"; {_f(i_t, 'A')} needs R_ISEN {_f(r_need, 'Ω')}"
    return res, steps, head


def _tmc(rec: dict[str, Any], r: float, v_ref: float | None, i_t: float | None, vs: str, o: _Out
         ) -> tuple[dict[str, Any], list[dict[str, Any]], str, list[dict[str, Any]]]:
    vfs = float(rec["v_fs"][vs]["value"])
    ri = float(rec["r_internal"]["value"])
    full = float(rec["v_ref_full"]["value"])
    i_fs = vfs / (r + ri) / math.sqrt(2)
    steps = [ck.step("I_RMS(100 %)", f"{_f(vfs, 'V')} / ({_f(r, 'Ω')} + {_f(ri, 'Ω')}) · 1/√2", i_fs, "A")]
    assum = [assumption("mode", "standalone, IRUN = 31, analog VREF scaling (i_scale_analog = 1, default)",
                        f"{rec['id']} datasheet p. 53; UART settings (IRUN/IHOLD < 31, internal sense resistors) "
                        "scale the current further"),
             assumption("vsense", f"vsense = {vs}: V_FS {_f(vfs, 'V')}",
                        f"{rec['id']} datasheet p. {rec['v_fs'][vs]['page']}, {rec['v_fs'][vs]['conditions']}")]
    if v_ref is not None:
        scale = min(v_ref, full) / full
        if v_ref > full + _EPS:
            assum.append(assumption("v_ref", f"{_f(v_ref, 'V')} counts as {_f(full, 'V')}",
                                    f"VREF above {_f(full, 'V')} gives 100 % ({_cite(rec, 'v_ref_full')})"))
        i = i_fs * scale
        steps.append(ck.step("I_RMS", f"{_f(i_fs, 'A')} · {_f(min(v_ref, full), 'V')} / {_f(full, 'V')}", i, "A"))
        v = v_ref
        head = f"V_REF {_f(v_ref, 'V')} with R_SENSE {_f(r, 'Ω')} → {_f(i, 'A')} RMS"
    else:
        i_t = float(i_t or 0.0)  # the caller passes exactly one of v_ref / i_target
        i = i_t
        v = i_t / i_fs * full
        steps.append(ck.step("V_REF", f"{_f(i_t, 'A')} / {_f(i_fs, 'A')} · {_f(full, 'V')}", v, "V"))
        head = f"{_f(i_t, 'A')} RMS with R_SENSE {_f(r, 'Ω')} needs V_REF {_f(v, 'V')}"
        if v > full + _EPS:
            o.checks.append(check("calc.current_limit.full_scale", "failed",
                                  f"I_target {_f(i_t, 'A')} > I_RMS at 100 % {_f(i_fs, 'A')} ({_cite(rec, 'v_ref_full')})"))
            o.warns.append(warning("current_limit_full_scale", "caution",
                                   f"{_f(i_t, 'A')} is above what R_SENSE {_f(r, 'Ω')} allows ({_f(i_fs, 'A')} RMS at "
                                   f"VREF ≥ {_f(full, 'V')}). Use a smaller R_SENSE or vsense = 0.", [o.sid]))
        else:
            o.checks.append(check("calc.current_limit.full_scale", "passed",
                                  f"I_target {_f(i_t, 'A')} ≤ I_RMS at 100 % {_f(i_fs, 'A')}"))
    peak = i * math.sqrt(2)
    steps.append(ck.step("I_peak", f"{_f(i, 'A')} · √2", peak, "A"))
    o.limit("v_ref_abs_max", v, "V", "v_ref_abs_max", "V_REF", "danger", "This damages the VREF input.")
    o.limit("v_ref_min", v, "V", "v_ref_min", "V_REF", "caution",
            "The datasheet does not recommend VREF this low: use a larger R_SENSE.", above=False)
    o.limit("i_max", i, "A", "i_max", "RMS current", "caution",
            "Above the RMS design guideline: the driver gets hot; cool it or lower the current.")
    o.limit("i_peak_max", peak, "A", "i_peak_max", "Peak current", "danger", "Above the peak output current rating.")
    res = {"i_limit": ck.q(i, "A"), "i_peak": ck.q(peak, "A"), "i_full_scale": ck.q(i_fs, "A"), "v_ref": ck.q(v, "V"),
           "v_sense": None}
    return res, steps, head, assum


@ck.action(ACTION)
def current_limit(driver: object, r_sense: object, v_ref: object = None, i_target: object = None, *,
                  vsense: object = "0") -> dict[str, Any]:
    """Current limit of a motor driver ↔ VREF (datasheet formula per driver)."""
    rec = _driver(driver)
    r = ck.num(r_sense, "Ω", "r_sense")
    vr = None if v_ref is None else ck.num(v_ref, "V", "v_ref", allow_zero=True)
    it = None if i_target is None else ck.num(i_target, "A", "i_target")
    vs = ck.choice(str(vsense), VSENSE, "vsense")
    method = rec["method"]
    if method == "fixed_ref":
        if vr is not None:
            raise BenchError("invalid_args", f"the {rec['id']} has a fixed 200 mV reference and no VREF pin",
                             "leave v_ref out; give r_sense (and optionally i_target)")
    elif (vr is None) == (it is None):
        raise BenchError("invalid_args", "give exactly one of v_ref (→ current) or i_target (→ VREF to set)",
                         "for example v_ref=0.8 or i_target=1.0")
    elif vr == 0:
        raise BenchError("invalid_args", "v_ref must be positive, got 0 V", "give the voltage measured at the REF pin")
    o = _Out(rec)
    inputs: dict[str, Any] = {"driver": rec["id"], "r_sense": ck.q(r, "Ω")}
    if vr is not None:
        inputs["v_ref"] = ck.q(vr, "V")
    if it is not None:
        inputs["i_target"] = ck.q(it, "A")
    assum: list[dict[str, Any]] = [
        assumption("r_sense", _f(r, "Ω"), "your value: read the sense resistor on your board (R100 = 0.1 Ω); carrier "
                   "boards fit different resistors and the result scales with it")]
    if method == "vref_div":
        res, steps, head = _vref_div(rec, r, vr, it, o)
        assum.append(assumption("i_limit", "peak coil current at 100 % of the step table",
                                f"{rec['id']} datasheet p. {rec['k']['page']}: the chopper limits the winding current "
                                "to this value; microstepping uses fractions of it"))
    elif method == "fixed_ref":
        res, steps, head = _fixed(rec, r, it, o)
        assum.append(assumption("i_limit", "chopping current of one bridge",
                                f"{rec['id']} datasheet p. {rec['v_trip']['page']}: fixed 200 mV reference"))
    else:
        res, steps, head, extra = _tmc(rec, r, vr, it, vs, o)
        assum += extra
    inputs["vsense"] = vs if method == "tmc_rms" else None
    if inputs["vsense"] is None:
        del inputs["vsense"]
    warns = [warning("current_limit_r_sense", "info",
                     "R_SENSE is your board's value: check the resistor marking; a wrong value scales the current.",
                     [ck.RULE]),
             warning("current_limit_motor", "info",
                     "Set the current before you connect the motor, and never plug or unplug the motor while the "
                     "driver is powered.", [ck.RULE])] + o.warns
    result = {"inputs": inputs, "driver": {"id": rec["id"], "title": rec["title"], "method": method,
                                           "source_id": rec["source_id"]},
              **res, "formula": rec["formula"], "steps": steps}
    failed = [c for c in o.checks if c["status"] == "failed"]
    summary = f"{rec['id']}: {head}" + (f" ({len(failed)} limit{'s' if len(failed) != 1 else ''} exceeded)." if failed
                                        else ".")
    return envelope(ACTION, summary, result, checks=o.checks, warnings=warns, assumptions=assum,
                    sources=ck.sources.resolve([rec["source_id"], ck.RULE]))


current_limit.choices = lambda: {  # type: ignore[attr-defined]  # calckit.meta
    "driver": [i.lower() for i in ck.parts.ids_of(KIND)], "vsense": VSENSE}
ck.register("current_limit", current_limit,
            (("driver", "str", True, None), ("r_sense", "Ω", True, None), ("v_ref", "V", False, None),
             ("i_target", "A", False, None), ("vsense", "str", False, "0")),
            title="Stepper/motor driver current limit", group="drive",
            summary="A4988, DRV8825, DRV8833, TMC2209: current limit from R_SENSE and VREF, or the VREF to set.")
