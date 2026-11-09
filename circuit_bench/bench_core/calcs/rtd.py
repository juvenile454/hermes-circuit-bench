"""RTD calculator ``calc.rtd``: MAX31865 reference resistor, code, RTD
resistance and temperature for platinum RTDs (PT100 … PT1000).

- ``RRTD = ADC code · RREF / 2^15`` (Maxim p. 19); the code is the 15-bit ratio RRTD/RREF (p. 15), so the LSB is
  ``RREF / 2^15``. An input above the reference voltage reads full scale (p. 11): RRTD must stay below RREF.
- ``RREF = 4 · R0`` is optimum for a platinum RTD (400 Ω for a PT100, 4 kΩ for a PT1000; p. 10); the recommended
  operating range of RREF is 350 Ω…10 kΩ (p. 2) -> outside: caution.
- Temperature from resistance with the Callendar-Van Dusen equation the datasheet gives (IEC 751, p. 10):
  ``R(T) = R0·(1 + a·T + b·T² + c·(T − 100)·T³)``, c only below 0 °C, valid −200 °C…+850 °C. Above 0 °C the
  quadratic is solved exactly, below 0 °C Newton's method refines it.
- The datasheet's straight line ``T ≈ code/32 − 256`` (p. 11; RREF = 4·R0, −100…+100 °C) is shown for comparison.
- Bias current through RREF and the RTD from VBIAS 2.0 V typ (p. 3) against the bias output current 0.2…5.75 mA
  (p. 3); cable resistance up to 50 Ω per lead (p. 2); 2-wire error ≈ 2·r_lead / (R0·a) (p. 10: 0.4 Ω ≈ 1 °C).

Every number below carries page and the verbatim excerpt line (tests/test_mod_thermo.py checks them).
"""
from __future__ import annotations

import math
from typing import Any

from .. import calckit as ck
from ..calckit import BenchError, assumption, check, envelope, warning

ACTION = "calc.rtd"
SOURCE = "mod-thermo-max31865-ds"
BITS = 15
CODE_MAX = 2 ** BITS - 1
_EPS = 1e-9

# Callendar-Van Dusen (IEC 751) and MAX31865 limits: value, page, excerpt line
CVD: dict[str, tuple[float, int, str]] = {
    "a": (3.90830e-3, 10, "a = 3.90830 x 10-3"),
    "b": (-5.77500e-7, 10, "b = -5.77500 x 10-7"),
    "c": (-4.18301e-12, 10, "c = -4.18301 x 10 -12 for -200 NC P T P 0NC, 0 for 0 NC P T"),
}
T_MIN, T_MAX = -200.0, 850.0  # CVD validity (p. 10, the line of c and "P +850NC")
T_SLACK = 0.5  # °C: a code one LSB beyond the range (Table 9: code 1517 for −200 °C) still converts
LIMITS: dict[str, tuple[float, int, str]] = {
    "rref_min": (350.0, 2, "Reference Resistor RREF 350 10k I"),
    "rref_max": (10000.0, 2, "Reference Resistor RREF 350 10k I"),
    "r_cable_max": (50.0, 2, "Cable Resistance RCABLE Per lead 0 50 I"),
    "bits": (15.0, 2, "ADC Resolution No missing codes 15 Bits"),
    "v_bias": (2.0, 3, "Bias Voltage VBIAS 1.95 2.00 2.06 V"),
    "i_bias_min": (0.2e-3, 3, "Bias Voltage Output Current IOUT 0.2 5.75 mA"),
    "i_bias_max": (5.75e-3, 3, "Bias Voltage Output Current IOUT 0.2 5.75 mA"),
    "rref_ratio": (4.0, 10, "resistor equal to four times the RTD’s 0 NC resistance is"),
}
FORMULA_EV: dict[str, tuple[int, str]] = {
    "rrtd": (19, "RRTD = (ADC Code x R REF)/215"),
    "ratio": (15, "Table 4. The data format is simply the 15-bit ratio of RTD"),
    "cvd": (10, "R(T) = R0(1 + aT + bT2 + c(T - 100)T3)"),
    "linear": (11, "Temperature (NC) ≈ (ADC code/32) – 256"),
    "full_scale": (11, "produces a full-scale output."),
    "pt100": (10, "a 400 I reference resistor, and a PT1000 uses a 4k I"),
    "two_wire": (10, "resistance of 0.4I causes an error of approximately 1 NC."),
}
A, B, C = CVD["a"][0], CVD["b"][0], CVD["c"][0]
FORMULA = ("RRTD = code · RREF / 2^15; R(T) = R0·(1 + a·T + b·T² + c·(T − 100)·T³) with a = 3.9083e-3, "
           "b = −5.775e-7, c = −4.18301e-12 below 0 °C (else 0)")


def _f(v: float, unit: str = "Ω", digits: int = 4) -> str:
    return ck.fmt(v, unit, digits)


def r_of_t(t: float, r0: float) -> float:
    """RTD resistance at t °C (Callendar-Van Dusen, IEC 751)."""
    c = C if t < 0 else 0.0
    return r0 * (1 + A * t + B * t * t + c * (t - 100) * t ** 3)


def dr_dt(t: float, r0: float) -> float:
    c = C if t < 0 else 0.0
    return r0 * (A + 2 * B * t + c * (4 * t ** 3 - 300 * t * t))


def t_of_r(r: float, r0: float) -> float | None:
    """Temperature in °C for resistance r (inverse Callendar-Van Dusen); None when r is beyond the equation's range
    (more than ``T_SLACK`` outside −200…+850 °C)."""
    ratio = r / r0
    disc = A * A - 4 * B * (1 - ratio)
    if disc < 0:
        return None
    t = (-A + math.sqrt(disc)) / (2 * B)
    if ratio < 1:  # below 0 °C the c term counts: Newton from the quadratic solution
        for _ in range(50):
            step = (r_of_t(t, r0) - r) / dr_dt(t, r0)
            t -= step
            if abs(step) < 1e-10:
                break
    if not T_MIN - T_SLACK <= t <= T_MAX + T_SLACK:
        return None
    return t


def _temp(value: object, name: str) -> float:
    try:
        text = str(value).strip().replace("°C", "").replace("°", "")
        t = float(text[:-1] if text.endswith(("C", "c")) else text)
    except (TypeError, ValueError):
        raise BenchError("invalid_args", f"{name} must be a temperature in °C, got {value!r}", "for example 100") from None
    if not math.isfinite(t):
        raise BenchError("invalid_args", f"{name} must be finite", "for example 100")
    if not T_MIN <= t <= T_MAX:
        raise BenchError("invalid_args", f"{name} {t:g} °C is outside −200…+850 °C (Callendar-Van Dusen range, "
                         f"MAX31865 p. {CVD['c'][1]})", "give a temperature from −200 to 850 °C")
    return t


def _code(value: object) -> int:
    try:
        if isinstance(value, bool):
            raise ValueError
        text = str(value).strip().lower()
        f = float(int(text, 16)) if text.startswith("0x") else float(text)
    except (TypeError, ValueError):
        raise BenchError("invalid_args", f"code must be the 15-bit ADC code 0…{CODE_MAX}, got {value!r}",
                         "for example 8192 (PT100 at 0 °C with RREF 400 Ω)") from None
    if f != int(f) or not 0 <= f <= CODE_MAX:
        raise BenchError("invalid_args", f"code must be an integer 0…{CODE_MAX} (15 bits), got {value!r}",
                         "the RTD register pair holds the code in D15…D1; shift the 16-bit value right by one")
    return int(f)


@ck.action(ACTION)
def rtd(r0: object = 100, r_ref: object = None, code: object = None, t: object = None, r_rtd: object = None,
        r_lead: object = None, wires: object = None) -> dict[str, Any]:
    """MAX31865: RREF choice, LSB and resolution; code -> resistance -> temperature, or temperature -> code."""
    given = [n for n, v in (("code", code), ("t", t), ("r_rtd", r_rtd)) if v is not None]
    if len(given) > 1:
        raise BenchError("invalid_args", f"give at most one of code, t, r_rtd (got {', '.join(given)})",
                         "code: reading -> temperature; t: temperature -> code; r_rtd: resistance -> both")
    r0_v = ck.num(r0, "Ω", "r0")
    inputs: dict[str, Any] = {"r0": ck.q(r0_v, "Ω", 4)}
    steps: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    assum: list[dict[str, Any]] = []
    ratio = LIMITS["rref_ratio"][0]
    if r_ref is None:
        rref = ratio * r0_v
        assum.append(assumption("r_ref", f"RREF = 4 · R0 = {_f(rref)}", "optimum for a platinum RTD (Maxim p. 10); "
                                "breakouts may fit another value: read yours and give r_ref"))
        steps.append(ck.step("RREF", f"4 · {_f(r0_v)}", rref, "Ω", 4))
    else:
        rref = ck.num(r_ref, "Ω", "r_ref")
    inputs["r_ref"] = ck.q(rref, "Ω", 4)
    lo, hi = LIMITS["rref_min"][0], LIMITS["rref_max"][0]
    if lo - _EPS <= rref <= hi + _EPS:
        checks.append(check(f"{ACTION}.r_ref_range", "passed", f"RREF {_f(rref)} within 350 Ω…10 kΩ (p. 2)"))
    else:
        checks.append(check(f"{ACTION}.r_ref_range", "failed", f"RREF {_f(rref)} outside 350 Ω…10 kΩ (p. 2)"))
        warns.append(warning("rtd_rref_range", "caution", f"MAX31865 RREF {_f(rref)} is outside the recommended "
                             "350 Ω…10 kΩ.", [SOURCE]))
    r_fs = rref * CODE_MAX / 2 ** BITS
    t_top: float | None = T_MAX  # RREF above R(850 °C): the whole equation range fits below full scale
    if rref < r_of_t(T_MAX, r0_v) - _EPS:
        t_top = t_of_r(r_fs, r0_v)
        top = "below −200 °C" if t_top is None else f"≈ {t_top:.1f} °C"
        assum.append(assumption("full_scale", f"code {CODE_MAX} = {_f(r_fs)} {top}",
                                "above RREF the reading is full scale (p. 11)"))
    lsb = rref / 2 ** BITS
    steps.append(ck.step("LSB", f"{_f(rref)} / 2^15", lsb, "Ω", 4))
    res0 = lsb / dr_dt(0.0, r0_v)
    steps.append(ck.step("resolution at 0 °C", f"LSB / (R0 · a) = {_f(lsb)} / ({_f(r0_v)} · {A:g})", res0, "°C", 3))
    result: dict[str, Any] = {
        "inputs": inputs, "lsb": ck.q(lsb, "Ω", 4), "resolution_0c": ck.q(res0, "°C", 3),
        "full_scale_r": ck.q(r_fs, "Ω", 5),
        "t_full_scale": None if t_top is None else ck.q(t_top, "°C", 4),
        "rref_recommended": ck.q(ratio * r0_v, "Ω", 4),
    }
    if abs(rref - ratio * r0_v) > 1e-6 * rref:
        assum.append(assumption("r_ref_ratio", f"RREF / R0 = {rref / r0_v:.3g}", "the datasheet recommends 4 · R0 "
                                "(p. 10); the straight-line approximation code/32 − 256 needs exactly that"))
    summary = f"MAX31865, R0 {_f(r0_v)}, RREF {_f(rref)}: LSB {_f(lsb)}, ≈ {res0:.3g} °C per code at 0 °C."

    r_meas: float | None = None
    if code is not None:
        c = _code(code)
        r_meas = c * rref / 2 ** BITS
        inputs["code"] = c
        steps.append(ck.step("RRTD", f"{c} · {_f(rref)} / 2^15", r_meas, "Ω", 5))
        result["code"] = c
    elif r_rtd is not None:
        r_meas = ck.num(r_rtd, "Ω", "r_rtd")
        inputs["r_rtd"] = ck.q(r_meas, "Ω", 5)
    elif t is not None:
        tv = _temp(t, "t")
        inputs["t"] = ck.q(tv, "°C", 4)
        r_meas = r_of_t(tv, r0_v)
        steps.append(ck.step("R(T)", f"{_f(r0_v)} · (1 + a·{tv:g} + b·{tv:g}²" + (" + c·(T − 100)·T³)" if tv < 0 else ")"),
                             r_meas, "Ω", 5))
    if r_meas is not None:
        if r_meas >= rref - _EPS or result.get("code") == CODE_MAX:
            checks.append(check(f"{ACTION}.full_scale", "failed", f"RRTD {_f(r_meas)} ≥ RREF {_f(rref)}: the reading "
                                "is full scale (p. 11)"))
            warns.append(warning("rtd_full_scale", "caution", f"RRTD {_f(r_meas)} is at or above RREF {_f(rref)}: "
                                 "the MAX31865 reads full scale; use a larger RREF.", [SOURCE]))
        else:
            checks.append(check(f"{ACTION}.full_scale", "passed", f"RRTD {_f(r_meas)} < RREF {_f(rref)}"))
        c_calc = min(CODE_MAX, int(math.floor(r_meas * 2 ** BITS / rref + 0.5)))
        if code is None:
            steps.append(ck.step("code", f"round({_f(r_meas)} · 2^15 / {_f(rref)})", c_calc, "", 6))
            result["code"] = c_calc
            result["register"] = f"0x{c_calc << 1:04X}"
        result["r_rtd"] = ck.q(r_meas, "Ω", 5)
        tt = float(inputs["t"]["value"]) if t is not None else t_of_r(r_meas, r0_v)
        if tt is None:
            checks.append(check(f"{ACTION}.cvd_range", "failed", f"RRTD {_f(r_meas)} is outside the Callendar-Van "
                                f"Dusen range for R0 {_f(r0_v)} ({_f(r_of_t(T_MIN, r0_v))}…{_f(r_of_t(T_MAX, r0_v))}, "
                                "−200…+850 °C, p. 10): no temperature"))
            warns.append(warning("rtd_out_of_range", "caution", f"{_f(r_meas)} is no PT{r0_v:g} reading between "
                                 "−200 and +850 °C: check r0, RREF and the wiring (open/shorted RTD).", [SOURCE]))
        else:
            if t is None:
                steps.append(ck.step("T", "inverse Callendar-Van Dusen", tt, "°C", 4))
            checks.append(check(f"{ACTION}.cvd_range", "passed", "within −200…+850 °C (p. 10)"))
            result["t"] = ck.q(tt, "°C", 4)
            result["resolution_at_t"] = ck.q(lsb / dr_dt(tt, r0_v), "°C", 3)
        if abs(rref - ratio * r0_v) <= 1e-6 * rref:
            code_now = result["code"]
            lin = code_now / 32 - 256
            result["t_linear"] = ck.q(lin, "°C", 4)
            steps.append(ck.step("T (straight line)", f"{code_now} / 32 − 256", lin, "°C", 4))
            if tt is None or not -100.5 <= tt <= 100.5:
                assum.append(assumption("t_linear", "outside −100…+100 °C", "the straight line is only a good "
                                        "approximation from −100 to +100 °C (p. 11)"))
        bias_r = rref + r_meas
    else:
        bias_r = rref + r0_v
    i_bias = LIMITS["v_bias"][0] / bias_r
    steps.append(ck.step("I_bias", f"VBIAS 2.0 V / ({_f(rref)} + {_f(bias_r - rref)})", i_bias, "A", 3))
    result["i_bias"] = ck.q(i_bias, "A", 3)
    result["p_rtd"] = ck.q(i_bias ** 2 * (bias_r - rref), "W", 3)
    assum.append(assumption("v_bias", "VBIAS = 2.0 V typ (1.95…2.06 V)", "MAX31865 p. 3; RREF and the RTD in series"))
    if LIMITS["i_bias_min"][0] - _EPS <= i_bias <= LIMITS["i_bias_max"][0] + _EPS:
        checks.append(check(f"{ACTION}.bias_current", "passed", f"I_bias {ck.fmt(i_bias, 'A')} within 0.2…5.75 mA (p. 3)"))
    else:
        checks.append(check(f"{ACTION}.bias_current", "failed", f"I_bias {ck.fmt(i_bias, 'A')} outside 0.2…5.75 mA (p. 3)"))
        warns.append(warning("rtd_bias_current", "caution", f"Bias current {ck.fmt(i_bias, 'A')} is outside the "
                             "MAX31865 bias output range 0.2…5.75 mA.", [SOURCE]))
    if r_lead is not None:
        rl = ck.num(r_lead, "Ω", "r_lead", allow_zero=True)
        inputs["r_lead"] = ck.q(rl, "Ω", 3)
        nw = 2 if wires is None else wires
        if str(nw) not in ("2", "3", "4"):
            raise BenchError("invalid_args", f"wires must be 2, 3 or 4, got {wires!r}", "for example wires=3")
        nw = int(str(nw))
        inputs["wires"] = nw
        if wires is None:
            assum.append(assumption("wires", "2-wire", "wires not given; 3- and 4-wire connections cancel the leads"))
        if rl <= LIMITS["r_cable_max"][0] + _EPS:
            checks.append(check(f"{ACTION}.cable", "passed", f"r_lead {_f(rl)} ≤ 50 Ω per lead (p. 2)"))
        else:
            checks.append(check(f"{ACTION}.cable", "failed", f"r_lead {_f(rl)} > 50 Ω per lead (p. 2)"))
            warns.append(warning("rtd_cable", "caution", f"Lead resistance {_f(rl)} exceeds 50 Ω per lead.", [SOURCE]))
        if nw == 2:
            err = 2 * rl / dr_dt(0.0, r0_v)
            steps.append(ck.step("2-wire error", f"two leads in series: 2 · {_f(rl)} / (R0 · a)", err, "°C", 3))
            result["lead_error"] = ck.q(err, "°C", 3)
    elif wires is not None:
        raise BenchError("invalid_args", "wires needs r_lead (Ω per lead)", "for example r_lead=0.2, wires=2")
    if "t" in result:
        summary += f" {result['r_rtd']['display']} ≙ {result['t']['display']} (code {result['code']})."
    result["formula"] = FORMULA
    result["steps"] = steps
    return envelope(ACTION, summary, result, checks=checks, warnings=warns, assumptions=assum,
                    sources=ck.sources.resolve([SOURCE]))


RTD_PARAMS = (("r0", "Ω", False, 100), ("r_ref", "Ω", False, None), ("code", "int", False, None),
              ("t", "°C", False, None), ("r_rtd", "Ω", False, None), ("r_lead", "Ω", False, None),
              ("wires", "int", False, None))

ck.register("rtd", rtd, RTD_PARAMS, title="MAX31865 RTD reference and temperature", group="sensing",
            summary="PT100/PT1000 on a MAX31865: RREF = 4·R0, LSB, code ↔ resistance ↔ temperature (Callendar-Van Dusen).")
