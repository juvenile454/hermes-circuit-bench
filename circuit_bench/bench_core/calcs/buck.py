"""Buck converter feedback divider ``calc.buck``: LM2596-ADJ and MP1584.

- LM2596 (TI SNVS124G p. 28, Equation 5): ``VOUT = VREF · (1 + R2/R1)`` with VREF = 1.23 V; R1 (FEEDBACK to GND)
  between 240 Ω and 1.5 kΩ, 1 kΩ in the example; R2 from VOUT to FEEDBACK.
- MP1584 (MPS Rev. 1.0 p. 10): ``VOUT = VFB · (R1 + R2) / R2`` with VFB = 0.8 V; R1 from VOUT to FB, R2 (FB to GND)
  under 40 kΩ, typically 40.2 kΩ.
- Here ``r_top`` = the resistor from VOUT to the feedback pin (LM2596 R2, MP1584 R1), ``r_bottom`` = feedback pin to
  GND (LM2596 R1, MP1584 R2). With ``v_out`` the calculator picks ``r_top`` from the E series for the given (or the
  datasheet's typical) ``r_bottom``; with ``r_top`` and ``r_bottom`` it computes VOUT. Both: the deviation.
- VOUT spread from the feedback voltage tolerance (min/max of VFB, datasheet), resistor tolerance not included.
- Hard checks only with datasheet limits: VIN against the operating range and the absolute maximum, VOUT against the
  adjustable range, I_OUT against the rated load current; the headroom V_IN − V_OUT against the LM2596 switch
  saturation voltage is a rule of thumb (100 % duty cycle, inductor and diode drops not included).
Every number below carries source id, page and the verbatim excerpt line (tests/test_mod_power.py checks them).
"""
from __future__ import annotations

import math
from typing import Any

from .. import calckit as ck
from ..calckit import BenchError, assumption, check, envelope, warning

ACTION = "calc.buck"
CHIPS: tuple[str, ...] = ("lm2596", "mp1584")
_EPS = 1e-9


def _ev(value: float, page: int, evidence: str | list[str]) -> dict[str, Any]:
    return {"value": value, "page": page, "evidence": evidence}


DATA: dict[str, dict[str, Any]] = {
    "lm2596": {
        "title": "LM2596-ADJ", "source_id": "mod-power-lm2596-ds",
        "formula": "V_OUT = V_REF · (1 + R2/R1), V_REF = 1.23 V (R2 = r_top: V_OUT→FEEDBACK, R1 = r_bottom: FEEDBACK→GND)",
        "formula_ev": _ev(1.23, 28, ["VOUT = VREF 1 +", "R2", "R1 \xa0where\xa0VREF\xa0 = 1.23\xa0V (5)"]),
        "v_fb": _ev(1.23, 6, "4.5 V ≤ VIN ≤ 40 V, 0.2 A ≤ ILOAD ≤ 3 A 1.23"),
        "v_fb_min": _ev(1.18, 6, "–40°C ≤ TJ ≤ 125°C 1.18 1.28"),
        "v_fb_max": _ev(1.28, 6, "–40°C ≤ TJ ≤ 125°C 1.18 1.28"),
        "r_bottom_typ": _ev(1000.0, 28, "Select R1 to be 1 kΩ, 1%"),
        "r_bottom_min": _ev(240.0, 28, "Select a value for R 1 between 240 Ω and 1.5 k Ω"),
        "r_bottom_max": _ev(1500.0, 28, "Select a value for R 1 between 240 Ω and 1.5 k Ω"),
        "v_in_min": _ev(4.5, 5, "Supply voltage 4.5 40 V"),
        "v_in_max": _ev(40.0, 5, "Supply voltage 4.5 40 V"),
        "v_in_abs": _ev(45.0, 5, "Maximum supply voltage (VIN) 45 V"),
        "v_out_min": _ev(1.2, 1, "Adjustable version output voltage range: 1.2-V to"),
        "v_out_max": _ev(37.0, 1, "37-V ±4% maximum over line and load conditions"),
        "i_out_max": _ev(3.0, 1, "3-A output load current"),
        "v_sat_max": _ev(1.4, 7, "VSAT Saturation voltage(4) (5) IOUT = 3 A TJ = 25°C 1.16 1.4 V"),
        "example": _ev(15.4e3, 28, "R2 = 1 k (16.26 − 1) = 15.26 k, closest 1% value is 15.4 kΩ."),
    },
    "mp1584": {
        "title": "MP1584", "source_id": "mod-power-mp1584-ds",
        "formula": "V_OUT = V_FB · (R1 + R2) / R2, V_FB = 0.8 V (R1 = r_top: V_OUT→FB, R2 = r_bottom: FB→GND)",
        "formula_ev": _ev(0.8, 10, "Thus the output voltage is:"),
        "v_fb": _ev(0.8, 3, "Feedback Voltage  VFB 4.5V < V IN < 28V 0.776 0.8 0.824 V"),
        "v_fb_min": _ev(0.776, 3, "Feedback Voltage  VFB 4.5V < V IN < 28V 0.776 0.8 0.824 V"),
        "v_fb_max": _ev(0.824, 3, "Feedback Voltage  VFB 4.5V < V IN < 28V 0.776 0.8 0.824 V"),
        "r_bottom_typ": _ev(40.2e3, 10, "value for R2 can be 40.2k \u2126."),
        "r_bottom_max": _ev(40e3, 10, "of current, keep R2 under 40K \u2126."),
        "v_in_min": _ev(4.5, 2, "Supply Voltage VIN ........................... 4.5V to 28V"),
        "v_in_max": _ev(28.0, 2, "Supply Voltage VIN ........................... 4.5V to 28V"),
        "v_in_abs": _ev(30.0, 2, "Supply Voltage (VIN) ..................... –0.3V to +30V"),
        "v_out_min": _ev(0.8, 2, "Output Voltage VOUT ......................... 0.8V to 25V"),
        "v_out_max": _ev(25.0, 2, "Output Voltage VOUT ......................... 0.8V to 25V"),
        "i_out_max": _ev(3.0, 1, "provides 3A output with current mode control for"),
        "example": _ev(127e3, 10, ["For example, for a 3.3V output voltage, R2 is", "40.2k\u2126, and R1 is 127k\u2126."]),
    },
}


def v_out_of(chip: str, r_top: float, r_bottom: float, v_fb: float | None = None) -> float:
    """Output voltage of the divider (both datasheet forms reduce to V_FB · (1 + r_top / r_bottom))."""
    vfb = DATA[chip]["v_fb"]["value"] if v_fb is None else v_fb
    return vfb * (1.0 + r_top / r_bottom)


def r_top_for(chip: str, v_out: float, r_bottom: float) -> float:
    return r_bottom * (v_out / DATA[chip]["v_fb"]["value"] - 1.0)


def _rb_min(chip: str) -> float:
    d = DATA[chip]
    return d["r_bottom_min"]["value"] if "r_bottom_min" in d else d["r_bottom_typ"]["value"] / 10.0


def _best_pair(chip: str, v_out: float, series: str) -> tuple[float, float]:
    """(r_bottom, r_top) from the E series with the smallest |V_OUT error|; ties: r_bottom closest to the typical."""
    d = DATA[chip]
    typ = d["r_bottom_typ"]["value"]
    best: tuple[float, float, float, float] | None = None
    for rb in ck.eseries.values_between(_rb_min(chip), d["r_bottom_max"]["value"], series):
        ideal = r_top_for(chip, v_out, rb)
        if ideal <= 0:
            continue
        rt = ck.eseries.nearest(ideal, series, "near")
        key = (round(abs(v_out_of(chip, rt, rb) - v_out), 12), abs(math.log(rb / typ)))
        if best is None or key < best[:2]:
            best = (*key, rb, rt)
    if best is None:
        raise BenchError("invalid_args", f"no {series} divider found for V_OUT {_f(v_out, 'V')}",
                         "give r_bottom or r_top yourself")
    return best[2], best[3]


def _f(v: float, unit: str) -> str:
    return ck.fmt(v, unit, 4)


@ck.action(ACTION)
def buck(v_out: object = None, *, chip: object = "lm2596", r_top: object = None, r_bottom: object = None,
         v_in: object = None, i_out: object = None, series: object = "E24") -> dict[str, Any]:
    """Feedback divider of an adjustable buck converter, plus input/output/current checks."""
    cid = ck.choice(chip, CHIPS, "chip")
    d = DATA[cid]
    sid = d["source_id"]
    ser = ck.series(series)
    vo_target = None if v_out is None else ck.num(v_out, "V", "v_out")
    rt = None if r_top is None else ck.num(r_top, "Ω", "r_top")
    rb = None if r_bottom is None else ck.num(r_bottom, "Ω", "r_bottom")
    vi = None if v_in is None else ck.num(v_in, "V", "v_in")
    io = None if i_out is None else ck.num(i_out, "A", "i_out")
    if vo_target is None and (rt is None or rb is None):
        raise BenchError("invalid_args", "give v_out (pick the divider) or r_top and r_bottom (compute V_OUT)",
                         "for example v_out=3.3, or r_top=15.4k r_bottom=1k")
    vfb = d["v_fb"]["value"]
    inputs: dict[str, Any] = {"chip": cid, "series": ser}
    checks: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    assum: list[dict[str, Any]] = [
        assumption("v_fb", f"{_f(vfb, 'V')} typical", f"{d['title']} datasheet p. {d['v_fb']['page']}; "
                   f"{_f(d['v_fb_min']['value'], 'V')}–{_f(d['v_fb_max']['value'], 'V')} sets the V_OUT spread"),
        assumption("resistors", "ideal values", "resistor tolerance and the feedback bias current are not included "
                   "(1 % parts recommended by the datasheet)")]
    name = d["title"]

    if vo_target is not None:
        inputs["v_out"] = ck.q(vo_target, "V")
        lo, hi = d["v_out_min"]["value"], d["v_out_max"]["value"]
        if vo_target < lo - _EPS or vo_target > hi + _EPS:
            raise BenchError("invalid_args", f"{name} adjusts V_OUT from {_f(lo, 'V')} to {_f(hi, 'V')}, got "
                             f"{_f(vo_target, 'V')} (datasheet p. {d['v_out_max']['page']})",
                             "choose a V_OUT inside the adjustable range")
        if vo_target <= vfb * (1 + 1e-9) and rt is None:
            raise BenchError("invalid_args", f"V_OUT {_f(vo_target, 'V')} needs no divider or cannot be set: "
                             f"V_OUT = V_FB = {_f(vfb, 'V')} with the feedback pin on the output",
                             "choose a V_OUT above the feedback voltage")
        if rb is None and rt is None:
            rb, rt = _best_pair(cid, vo_target, ser)
            lo_txt = _f(_rb_min(cid), "Ω")
            assum.append(assumption("r_bottom", f"{ser} values {lo_txt}–{_f(d['r_bottom_max']['value'], 'Ω')}",
                                    f"pair with the smallest V_OUT error; range from the datasheet (p. "
                                    f"{d['r_bottom_max']['page']})" + ("" if "r_bottom_min" in d else
                                                                       ", lower end a rule of thumb (1/10 of the "
                                                                       "typical value)")))
            steps.append(ck.step("r_bottom", f"{ser} pair search", rb, "Ω"))
            steps.append(ck.step("r_top", f"nearest {ser} value to r_bottom · (V_OUT / V_FB − 1)", rt, "Ω"))
        if rb is None:
            rb = d["r_bottom_typ"]["value"]
            assum.append(assumption("r_bottom", _f(rb, "Ω"), f"{name} datasheet typical value "
                                    f"(p. {d['r_bottom_typ']['page']})"))
        if rt is None:
            ideal = r_top_for(cid, vo_target, rb)
            if ideal <= 0:
                raise BenchError("invalid_args", f"V_OUT {_f(vo_target, 'V')} needs no divider "
                                 f"(V_OUT = V_FB = {_f(vfb, 'V')}): connect the feedback pin to the output",
                                 "choose a V_OUT above the feedback voltage")
            steps.append(ck.step("r_top ideal", f"{_f(rb, 'Ω')} · ({_f(vo_target, 'V')} / {_f(vfb, 'V')} − 1)",
                                 ideal, "Ω"))
            rt = ck.eseries.nearest(ideal, ser, "near")
            steps.append(ck.step("r_top", f"nearest {ser} value", rt, "Ω"))
    if rt is None or rb is None:  # unreachable: v_out given -> both filled above; else both required
        raise BenchError("invalid_args", "give r_top and r_bottom", "or give v_out")
    inputs["r_top"], inputs["r_bottom"] = ck.q(rt, "Ω"), ck.q(rb, "Ω")
    vo = v_out_of(cid, rt, rb)
    vo_lo, vo_hi = v_out_of(cid, rt, rb, d["v_fb_min"]["value"]), v_out_of(cid, rt, rb, d["v_fb_max"]["value"])
    steps.append(ck.step("V_OUT", f"{_f(vfb, 'V')} · (1 + {_f(rt, 'Ω')} / {_f(rb, 'Ω')})", vo, "V"))
    result: dict[str, Any] = {"inputs": inputs, "formula": d["formula"], "r_top": ck.q(rt, "Ω"),
                              "r_bottom": ck.q(rb, "Ω"), "v_out": ck.q(vo, "V"),
                              "v_out_range": {"min": ck.q(vo_lo, "V"), "max": ck.q(vo_hi, "V"),
                                              "basis": "feedback voltage min/max from the datasheet"},
                              "deviation": None, "steps": steps}
    if vo_target is not None:
        dev = (vo - vo_target) / vo_target * 100.0
        result["deviation"] = ck.q(dev, "%")
        steps.append(ck.step("deviation", f"({_f(vo, 'V')} − {_f(vo_target, 'V')}) / {_f(vo_target, 'V')}", dev, "%"))

    lo, hi = d["v_out_min"]["value"], d["v_out_max"]["value"]
    ok = lo - _EPS <= vo <= hi + _EPS
    checks.append(check(f"{ACTION}.v_out_range", "passed" if ok else "failed",
                        f"V_OUT {_f(vo, 'V')} {'within' if ok else 'outside'} {_f(lo, 'V')}–{_f(hi, 'V')} "
                        f"({name}, p. {d['v_out_max']['page']})"))
    if not ok:
        warns.append(warning("buck_v_out_range", "caution", f"{name} cannot regulate {_f(vo, 'V')}: its adjustable "
                             f"range is {_f(lo, 'V')}–{_f(hi, 'V')}.", [sid]))
    rb_max = d["r_bottom_max"]["value"]
    rb_min = d.get("r_bottom_min", {}).get("value")
    if rb > rb_max * 1.01 + _EPS or (rb_min is not None and rb < rb_min - _EPS):
        span = f"{_f(rb_min, 'Ω')}–{_f(rb_max, 'Ω')}" if rb_min is not None else f"under {_f(rb_max, 'Ω')}"
        checks.append(check(f"{ACTION}.r_bottom", "failed", f"r_bottom {_f(rb, 'Ω')} outside the datasheet "
                            f"recommendation {span} (p. {d['r_bottom_max']['page']})"))
        warns.append(warning("buck_r_bottom", "info", f"{name}: the datasheet recommends r_bottom {span} "
                             "(noise pickup / leakage at no load); the formula still holds.", [sid]))
    else:
        checks.append(check(f"{ACTION}.r_bottom", "passed", f"r_bottom {_f(rb, 'Ω')} as recommended"))

    if vi is None:
        checks.append(check(f"{ACTION}.v_in", "not_checked", "give v_in to check the input range and headroom"))
    else:
        inputs["v_in"] = ck.q(vi, "V")
        vmin, vmax, vabs = d["v_in_min"]["value"], d["v_in_max"]["value"], d["v_in_abs"]["value"]
        if vi > vabs + _EPS:
            checks.append(check(f"{ACTION}.v_in", "failed", f"V_IN {_f(vi, 'V')} > absolute maximum {_f(vabs, 'V')}"))
            warns.append(warning("buck_v_in_abs_max", "danger", f"V_IN {_f(vi, 'V')} exceeds the absolute maximum "
                                 f"{_f(vabs, 'V')} of the {name}: the chip can be destroyed.", [sid]))
        elif vi > vmax + _EPS or vi < vmin - _EPS:
            checks.append(check(f"{ACTION}.v_in", "failed", f"V_IN {_f(vi, 'V')} outside {_f(vmin, 'V')}–"
                                f"{_f(vmax, 'V')}"))
            warns.append(warning("buck_v_in_range", "caution", f"V_IN {_f(vi, 'V')} is outside the operating range "
                                 f"{_f(vmin, 'V')}–{_f(vmax, 'V')} of the {name}.", [sid]))
        else:
            checks.append(check(f"{ACTION}.v_in", "passed", f"V_IN {_f(vi, 'V')} within {_f(vmin, 'V')}–"
                                f"{_f(vmax, 'V')}"))
        need = vo + (d["v_sat_max"]["value"] if "v_sat_max" in d else 0.0)
        ok = vi > need + _EPS
        what = (f"V_OUT + V_SAT max {_f(d['v_sat_max']['value'], 'V')}" if "v_sat_max" in d else "V_OUT")
        checks.append(check(f"{ACTION}.headroom", "passed" if ok else "failed",
                            f"V_IN {_f(vi, 'V')} {'>' if ok else '≤'} {what} = {_f(need, 'V')}"))
        if "v_sat_max" in d:
            assum.append(assumption("headroom", f"V_IN > V_OUT + {_f(d['v_sat_max']['value'], 'V')}",
                                    "rule of thumb: switch saturation at 3 A (25 °C, datasheet); inductor and "
                                    "diode drops add to it"))
        if not ok:
            warns.append(warning("buck_headroom", "caution", f"V_IN {_f(vi, 'V')} is too close to V_OUT "
                                 f"{_f(vo, 'V')}: a buck converter only steps down; the output drops out.", [sid]))
    if io is None:
        checks.append(check(f"{ACTION}.i_out", "not_checked", "give i_out to check the rated load current"))
    else:
        inputs["i_out"] = ck.q(io, "A")
        imax = d["i_out_max"]["value"]
        ok = io <= imax + _EPS
        checks.append(check(f"{ACTION}.i_out", "passed" if ok else "failed",
                            f"I_OUT {_f(io, 'A')} {'≤' if ok else '>'} rated {_f(imax, 'A')} ({name})"))
        if not ok:
            warns.append(warning("buck_i_out", "caution", f"I_OUT {_f(io, 'A')} is above the rated {_f(imax, 'A')} "
                                 f"of the {name}.", [sid]))
        elif vi is not None and io > 0.5 * imax:
            warns.append(warning("buck_heat", "info", f"{_f(io, 'A')} from a {name}: the chip and the diode get hot; "
                                 "use the copper area of the datasheet layout (rule of thumb: above half the rated "
                                 "current).", [sid, ck.RULE]))
    if vo_target is not None and 3.0 <= vo_target <= 3.6:
        warns.append(warning("buck_set_before_connect", "info", "Set and measure V_OUT before connecting the ESP32: "
                             "an adjustable module can leave the factory at a higher voltage.", [ck.RULE]))
    dev_txt = f", {result['deviation']['value']:+.2f} % from {_f(vo_target, 'V')}" if vo_target is not None else ""
    summary = (f"{name}: r_top {_f(rt, 'Ω')}, r_bottom {_f(rb, 'Ω')} → V_OUT {_f(vo, 'V')}{dev_txt} "
               f"(spread {_f(vo_lo, 'V')}–{_f(vo_hi, 'V')} from V_FB).")
    return envelope(ACTION, summary, result, checks=checks, warnings=warns, assumptions=assum,
                    sources=ck.sources.resolve([sid, ck.RULE]))


BUCK_PARAMS = (("v_out", "V", False, None), ("chip", "str", False, "lm2596"), ("r_top", "Ω", False, None),
               ("r_bottom", "Ω", False, None), ("v_in", "V", False, None), ("i_out", "A", False, None),
               ("series", "str", False, "E24"))

buck.choices = {"chip": tuple(DATA)}  # type: ignore[attr-defined]  # calckit.meta
buck.one_of = (("v_out",), ("r_top", "r_bottom"))  # type: ignore[attr-defined]
ck.register("buck", buck, BUCK_PARAMS, title="Buck converter feedback divider", group="power",
            summary="LM2596-ADJ / MP1584 divider for a target V_OUT (E series) or V_OUT of a divider; V_IN and I_OUT checked.")
