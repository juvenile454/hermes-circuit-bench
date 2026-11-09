"""Calculator ``current_sense``: ACS712 Hall current sensor at an ESP32 ADC.

Allegro ACS712 datasheet (ACS712-DS Rev. 22; PDF page index; quoted in ``FACTS``, excerpt
tests/corpus/excerpts/mod-powermon-acs712.txt):
- VIOUT = VIOUT(Q) + Sens · IP with VIOUT(Q) = VCC × 0.5 (p. 5, p. 10); output and sensitivity are ratiometric
  (proportional to VCC, p. 10), so Sens is scaled by VCC / 5 V. That scaling is the datasheet's ratiometric model;
  the sensitivity itself is specified at VCC = 5 V only (p. 6) and the result says so.
- Sensitivity per variant at VCC = 5 V, TA = 25 °C (p. 6): x05B 185 mV/A (±5 A), x20A 100 mV/A (±20 A),
  x30A 66 mV/A (±30 A); VCC 4.5–5.5 V (p. 5); RLOAD ≥ 4.7 kΩ, CLOAD ≤ 10 nF at VIOUT (p. 5).
- ESP input limit: ``v_in_max`` of the chip from data/electrical (electrical.get), passed by the caller as
  ``v_adc_max`` or looked up with ``chip``.
Divider: VIOUT → R1 → ADC pin → R2 → GND. Deterministic, SI units; nothing is interpolated.
"""
from __future__ import annotations

from typing import Any

from .. import calckit, electrical

ACTION = "calc.current_sense"
SRC = "mod-powermon-acs712-ds"
VARIANTS = ("05b", "20a", "30a")
VCC_REF = 5.0  # V: the performance tables hold at VCC = 5 V (p. 6, table headers)


def _f(value: Any, unit: str, page: int, evidence: Any, conditions: str | None = None) -> dict[str, Any]:
    out = {"value": value, "unit": unit, "page": page, "evidence": evidence, "source_id": SRC}
    if conditions:
        out["conditions"] = conditions
    return out


FACTS: dict[str, dict[str, Any]] = {
    "sens_05b": _f(0.185, "V/A", 6, ["x05B PERFORMANCE CHARACTERISTICS", "Optimized Accuracy Range IP –5 – 5 A",
                                      "Sensitivity Sens Over full range of IP, TA = 25°C 180 185 190 mV/A"],
                   "typ, VCC = 5 V, TA = 25 °C"),
    "sens_20a": _f(0.100, "V/A", 6, ["x20A PERFORMANCE CHARACTERISTICS", "Optimized Accuracy Range IP –20 – 20 A",
                                      "Sensitivity Sens Over full range of IP, TA = 25°C 96 100 104 mV/A"],
                   "typ, VCC = 5 V, TA = 25 °C"),
    "sens_30a": _f(0.066, "V/A", 6, ["x30A PERFORMANCE CHARACTERISTICS", "Optimized Accuracy Range IP –30 – 30 A",
                                      "Sensitivity Sens Over full range of IP , TA = 25°C 63 66 69 mV/A"],
                   "typ, VCC = 5 V, TA = 25 °C"),
    "range_05b": _f(5.0, "A", 6, "Optimized Accuracy Range IP –5 – 5 A"),
    "range_20a": _f(20.0, "A", 6, "Optimized Accuracy Range IP –20 – 20 A"),
    "range_30a": _f(30.0, "A", 6, "Optimized Accuracy Range IP –30 – 30 A"),
    "vq_ratio": _f(0.5, "", 5, "Zero Current Output Voltage VIOUT(Q) Bidirectional; IP = 0 A, TA = 25°C – VCC  × 0.5 – V"),
    "ratiometric": _f(1, "", 10, ["VIOUT(Q), (nominally equal to VCC/2) and sensitivity, Sens, are",
                                  "proportional to its supply voltage, VCC ."]),
    "vcc_min": _f(4.5, "V", 5, "Supply Voltage VCC 4.5 5.0 5.5 V"),
    "vcc_max": _f(5.5, "V", 5, "Supply Voltage VCC 4.5 5.0 5.5 V"),
    "r_load_min": _f(4700.0, "Ω", 5, "Output Resistive Load RLOAD VIOUT to GND 4.7 – – kΩ"),
    "c_load_max": _f(1e-08, "F", 5, "Output Capacitance Load CLOAD VIOUT to GND – – 10 nF"),
}
FORMULA = ("VIOUT = VCC/2 + Sens·(VCC/5 V)·IP; V_adc = VIOUT·R2/(R1+R2); "
           "R1+R2 ≥ R_LOAD,min; V_adc,max ≤ v_in_max")


def _v(key: str) -> float:
    return float(FACTS[key]["value"])


def _chip_limit(chip: str) -> tuple[float, float | None, list[str]]:
    """(v_in_max, vdd or None, source ids) of an ESP chip from data/electrical."""
    vals = electrical.get(chip)
    if not vals or vals.get("v_in_max") is None:
        raise calckit.BenchError("invalid_args", f"no ESP input limit for chip {chip!r}",
                                 "give v_adc_max in V or a chip such as esp32s3")
    vdd = vals.get("vdd")
    return float(vals["v_in_max"]), (float(vdd) if vdd is not None else None), list(vals.get("source_ids") or [])


def _suggest(vout_max: float, limit: float, r_min: float) -> dict[str, Any] | None:
    """E12 pair (R1, R2): R2/(R1+R2) ≤ limit/vout_max, R1+R2 ≥ r_min, ratio as high as possible; R2 from 4k7…100k."""
    target = limit / vout_max
    best: tuple[float, float, float] | None = None
    for r2 in calckit.eseries.values_between(4700, 100000, "E12"):
        for r1 in calckit.eseries.values_between(100, 220000, "E12"):
            ratio = r2 / (r1 + r2)
            if ratio <= target * (1 - 1e-12) and r1 + r2 >= r_min and (best is None or ratio > best[2] + 1e-12):
                best = (r1, r2, ratio)
    if best is None:
        return None
    r1, r2, ratio = best
    return {"r1": calckit.q(r1, "Ω"), "r2": calckit.q(r2, "Ω"), "ratio": calckit.sig(ratio),
            "v_adc_max": calckit.q(vout_max * ratio, "V")}


@calckit.action(ACTION)
def current_sense(variant: object, *, i_max: object = None, v_cc: object = 5.0, r1: object = None, r2: object = None,
                  v_adc_max: object = None, chip: object = "esp32s3") -> dict[str, Any]:
    """ACS712 output range at ±i_max and the divider that keeps it inside the ESP ADC input."""
    var = calckit.choice(str(variant).lower().replace("acs712elctr-", "").replace("acs712-", "")
                         if isinstance(variant, str) else variant, VARIANTS, "variant")
    vcc = calckit.num(v_cc, "V", "v_cc")
    rated = _v(f"range_{var}")
    imax = calckit.num(i_max, "A", "i_max") if i_max is not None else rated
    checks: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    assum: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    src_ids = [SRC]
    inputs: dict[str, Any] = {"variant": var, "i_max": calckit.q(imax, "A"), "v_cc": calckit.q(vcc, "V")}
    if i_max is None:
        assum.append(calckit.assumption("i_max", calckit.fmt(rated, "A"), "the variant's optimized accuracy range"))
    target: float | None = None  # design target of the suggested divider (VDD of the chip, else the limit)
    if v_adc_max is not None:
        limit = calckit.num(v_adc_max, "V", "v_adc_max")
        inputs["v_adc_max"] = calckit.q(limit, "V")
        assum.append(calckit.assumption("v_adc_max", calckit.fmt(limit, "V"), "given by you"))
    else:
        chip_name = str(chip).strip().lower()
        limit, vdd, chip_src = _chip_limit(chip_name)
        if vdd is not None and vdd < limit:
            target = vdd
        src_ids += chip_src
        inputs["chip"] = chip_name
        assum.append(calckit.assumption("v_adc_max", calckit.fmt(limit, "V"),
                                        f"maximum high-level input voltage (VIH max) of the {chip_name} pins (data/electrical)"))
    lo, hi = _v("vcc_min"), _v("vcc_max")
    if not lo - 1e-9 <= vcc <= hi + 1e-9:
        checks.append(calckit.check(f"{ACTION}.vcc", "failed",
                                    f"VCC {calckit.fmt(vcc, 'V')} outside {calckit.fmt(lo, 'V')}–{calckit.fmt(hi, 'V')}"))
        warns.append(calckit.warning("vcc_out_of_range", "caution",
                                     f"ACS712 runs from {calckit.fmt(lo, 'V')}–{calckit.fmt(hi, 'V')}; at "
                                     f"{calckit.fmt(vcc, 'V')} it is outside the datasheet range (not 3.3 V).", [SRC]))
    else:
        checks.append(calckit.check(f"{ACTION}.vcc", "passed",
                                    f"VCC {calckit.fmt(vcc, 'V')} within {calckit.fmt(lo, 'V')}–{calckit.fmt(hi, 'V')}"))
    if imax > rated + 1e-9:
        checks.append(calckit.check(f"{ACTION}.current", "failed",
                                    f"±{calckit.fmt(imax, 'A')} beyond the ±{calckit.fmt(rated, 'A')} range of x{var.upper()}"))
        warns.append(calckit.warning("current_over_range", "caution",
                                     f"±{calckit.fmt(imax, 'A')} is beyond the optimized accuracy range ±"
                                     f"{calckit.fmt(rated, 'A')} of the x{var.upper()} variant: pick a larger variant.",
                                     [SRC]))
    else:
        checks.append(calckit.check(f"{ACTION}.current", "passed",
                                    f"±{calckit.fmt(imax, 'A')} within ±{calckit.fmt(rated, 'A')}"))
    sens5 = _v(f"sens_{var}")
    sens = sens5 * vcc / VCC_REF
    vq = _v("vq_ratio") * vcc
    v_hi, v_lo = vq + sens * imax, vq - sens * imax
    steps += [calckit.step("VIOUT(Q)", f"{calckit.fmt(vcc, 'V')} × 0.5", vq, "V"),
              calckit.step("Sens", f"{calckit.fmt(sens5, 'V/A')} · {calckit.fmt(vcc, 'V')} / 5 V", sens, "V/A"),
              calckit.step("VIOUT_max", f"{calckit.fmt(vq, 'V')} + {calckit.fmt(sens, 'V/A')} · "
                                        f"{calckit.fmt(imax, 'A')}", v_hi, "V"),
              calckit.step("VIOUT_min", f"{calckit.fmt(vq, 'V')} − {calckit.fmt(sens, 'V/A')} · "
                                        f"{calckit.fmt(imax, 'A')}", v_lo, "V")]
    if abs(vcc - VCC_REF) > 1e-9:
        assum.append(calckit.assumption("ratiometric", f"Sens × {calckit.sig(vcc / VCC_REF, 4)}",
                                        "sensitivity scaled with VCC (ratiometric, p. 10); the datasheet specifies "
                                        "Sens at VCC = 5 V only"))
    r_min = _v("r_load_min")
    result: dict[str, Any] = {
        "v_out_zero": calckit.q(vq, "V"), "sensitivity": calckit.q(sens, "V/A"),
        "v_out_min": calckit.q(v_lo, "V"), "v_out_max": calckit.q(v_hi, "V"), "v_adc_limit": calckit.q(limit, "V"),
        "r_load_min": calckit.q(r_min, "Ω"), "c_load_max": calckit.q(_v("c_load_max"), "F")}
    if r1 is None and r2 is None:
        direct_ok = v_hi <= limit + 1e-9
        if direct_ok:
            checks.append(calckit.check(f"{ACTION}.adc_input", "passed",
                                        f"VIOUT max {calckit.fmt(v_hi, 'V')} ≤ {calckit.fmt(limit, 'V')} without a divider"))
        else:
            checks.append(calckit.check(f"{ACTION}.adc_input", "failed",
                                        f"VIOUT max {calckit.fmt(v_hi, 'V')} > ESP limit {calckit.fmt(limit, 'V')}"))
            warns.append(calckit.warning("needs_divider", "danger",
                                         f"VIOUT reaches {calckit.fmt(v_hi, 'V')} at +{calckit.fmt(imax, 'A')}, above "
                                         f"the ESP input limit {calckit.fmt(limit, 'V')}: add a divider (suggested "
                                         "below).", src_ids))
        sug = None if direct_ok else _suggest(v_hi, target or limit, r_min)
        result["divider_suggestion"] = sug
        if sug is not None:
            goal = calckit.fmt(target or limit, "V")
            assum.append(calckit.assumption("divider", f"R1 {sug['r1']['display']}, R2 {sug['r2']['display']} (E12)",
                                            f"largest E12 ratio that keeps the pin at or below {goal} (the chip's VDD "
                                            "when known) with R1+R2 ≥ R_LOAD,min; check the ADC attenuation range"))
    else:
        if r1 is None or r2 is None:
            raise calckit.BenchError("invalid_args", "give both r1 and r2 (or neither for a suggestion)",
                                     "r1 from VIOUT to the ADC pin, r2 from the ADC pin to GND")
        ra, rb = calckit.num(r1, "Ω", "r1"), calckit.num(r2, "Ω", "r2")
        inputs.update({"r1": calckit.q(ra, "Ω"), "r2": calckit.q(rb, "Ω")})
        ratio = rb / (ra + rb)
        a_hi, a_lo, a_zero = v_hi * ratio, v_lo * ratio, vq * ratio
        steps += [calckit.step("ratio", f"{calckit.fmt(rb, 'Ω')} / ({calckit.fmt(ra, 'Ω')} + {calckit.fmt(rb, 'Ω')})",
                               ratio, ""),
                  calckit.step("V_adc_max", f"{calckit.fmt(v_hi, 'V')} · {calckit.sig(ratio, 4)}", a_hi, "V")]
        result["divider"] = {"ratio": calckit.sig(ratio), "v_adc_zero": calckit.q(a_zero, "V"),
                             "v_adc_min": calckit.q(a_lo, "V"), "v_adc_max": calckit.q(a_hi, "V"),
                             "r_source": calckit.q(ra * rb / (ra + rb), "Ω"),
                             "sensitivity_at_adc": calckit.q(sens * ratio, "V/A")}
        if a_hi > limit + 1e-9:
            checks.append(calckit.check(f"{ACTION}.adc_input", "failed",
                                        f"V_adc max {calckit.fmt(a_hi, 'V')} > ESP limit {calckit.fmt(limit, 'V')}"))
            warns.append(calckit.warning("adc_over_limit", "danger",
                                         f"With R1 {calckit.fmt(ra, 'Ω')} / R2 {calckit.fmt(rb, 'Ω')} the ADC pin "
                                         f"reaches {calckit.fmt(a_hi, 'V')}, above {calckit.fmt(limit, 'V')}: raise R1 "
                                         "or lower R2.", src_ids))
        else:
            checks.append(calckit.check(f"{ACTION}.adc_input", "passed",
                                        f"V_adc max {calckit.fmt(a_hi, 'V')} ≤ {calckit.fmt(limit, 'V')}"))
        if ra + rb < r_min - 1e-9:
            checks.append(calckit.check(f"{ACTION}.r_load", "failed",
                                        f"R1+R2 {calckit.fmt(ra + rb, 'Ω')} < R_LOAD,min {calckit.fmt(r_min, 'Ω')}"))
            warns.append(calckit.warning("load_too_low", "caution",
                                         f"The divider loads VIOUT with {calckit.fmt(ra + rb, 'Ω')}, below the "
                                         f"minimum {calckit.fmt(r_min, 'Ω')} (ACS712 p. 5).", [SRC]))
        else:
            checks.append(calckit.check(f"{ACTION}.r_load", "passed",
                                        f"R1+R2 {calckit.fmt(ra + rb, 'Ω')} ≥ {calckit.fmt(r_min, 'Ω')}"))
    assum.append(calckit.assumption("adc_range", "check your attenuation",
                                    "the ESP ADC reads only part of 0–v_in_max linearly; the limit here protects the "
                                    "pin, it is not the ADC range"))
    result.update({"inputs": inputs, "formula": FORMULA, "steps": steps})
    summary = (f"ACS712 x{var.upper()} at {calckit.fmt(vcc, 'V')}: VIOUT {calckit.fmt(v_lo, 'V')}–"
               f"{calckit.fmt(v_hi, 'V')} for ±{calckit.fmt(imax, 'A')} (zero at {calckit.fmt(vq, 'V')}).")
    return calckit.envelope(ACTION, summary, result, checks=checks, warnings=warns, assumptions=assum,
                            sources=calckit.sources.resolve(src_ids))


current_sense.choices = {"variant": VARIANTS}  # type: ignore[attr-defined]  # calckit.meta
calckit.register(
    "current_sense", current_sense,
    (("variant", "str", True, None), ("i_max", "A", False, None), ("v_cc", "V", False, 5.0), ("r1", "Ω", False, None),
     ("r2", "Ω", False, None), ("v_adc_max", "V", False, None), ("chip", "str", False, "esp32s3")),
    title="ACS712 current sensor at the ADC", group="sensing",
    summary="ACS712 05B/20A/30A: output range VCC/2 ± Sens·I, divider for the ESP ADC, minimum output load.")
