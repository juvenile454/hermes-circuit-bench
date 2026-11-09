"""NTC thermistor calculator ``calc.ntc``: Vishay NTCLE100E3 in a voltage
divider read by an ESP32 ADC pin.

- Resistance over temperature with the extended Steinhart-Hart formula of the datasheet (Vishay 29049 p. 4):
  ``R(T) = R25·exp(A + B/T + C/T² + D/T³)`` and ``1/T = A1 + B1·ln(R/R25) + C1·ln²(R/R25) + D1·ln³(R/R25)``, T in K,
  constants per material (data/parts/thermo.json; material I has one set below and one from 25 °C). The plain
  B-equation with B25/85 (p. 2) is shown for comparison.
- Divider: ``position="low"``: NTC from the ADC node to GND, ``V = Vs·R_NTC/(R_NTC + R_fixed)``; ``"high"``: NTC
  from Vs to the node, ``V = Vs·R_fixed/(R_NTC + R_fixed)``. Without ``r_fixed`` the fixed resistor is R25; the
  suggestion ``√(R(t_min)·R(t_max))`` (largest voltage swing between the two ends; arithmetic, no datasheet) is
  rounded to the E-series.
- Checks: the divider output against the ESP input maximum ``v_in_max`` (data/electrical, danger); an ADC range the
  user gives (``adc_range``; the ESP ADC range depends on the attenuation and is not in the data: not_checked
  without it); the temperature range against −40…+125 °C (≤ 150 °C for short periods, p. 1); the voltage on the NTC
  below 50 VDC (p. 2); the measuring power against "zero power" = 1 % of the maximum power 500 mW at 55 °C (p. 1, 2).
- Self-heating ``ΔT = P / δ`` with the dissipation factor δ (7 mW/K, 8.5 mW/K for R25 ≤ 680 Ω; "for information
  only", p. 1); a hint above 0.1 K is a rule of thumb.
"""
from __future__ import annotations

import math
from typing import Any

from .. import calckit as ck
from .. import electrical
from ..calckit import BenchError, assumption, check, envelope, warning

ACTION = "calc.ntc"
KIND = "ntc"
DEFAULT_PART = "NTCLE100E3103"
POSITIONS: tuple[str, ...] = ("low", "high")
T0 = 273.15
T25 = 25.0
SELF_HEAT_HINT_K = 0.1  # rule of thumb for the hint, not a datasheet limit
_EPS = 1e-9


def _f(v: float, unit: str, digits: int = 4) -> str:
    return ck.fmt(v, unit, digits)


def part_data(name: object) -> dict[str, Any]:
    if name is None:
        name = DEFAULT_PART
    rec = ck.parts.find(name, KIND)
    if rec is None:
        known = ", ".join(ck.parts.ids_of(KIND))
        raise BenchError("invalid_args", f"no datasheet data for NTC {name!r}", f"known NTCs: {known}")
    return rec


def _segment(part: dict[str, Any], t: float) -> dict[str, Any]:
    for seg in part["steinhart_hart"]:
        if "t_below" in seg and t >= seg["t_below"]:
            continue
        if "t_from" in seg and t < seg["t_from"]:
            continue
        return seg
    raise ValueError(f"{part['id']}: no Steinhart-Hart range for {t} °C")  # data error, never user input


def r_of_t(part: dict[str, Any], t: float) -> float:
    """Nominal NTC resistance at t °C (Vishay p. 4, formula 1)."""
    c = _segment(part, t)
    tk = t + T0
    return part["r25"]["value"] * math.exp(c["A"] + c["B"] / tk + c["C"] / tk ** 2 + c["D"] / tk ** 3)


def t_of_r(part: dict[str, Any], r: float) -> float:
    """Temperature in °C at resistance r (Vishay p. 4, formula 2); the segment is chosen by the result."""
    x = math.log(r / part["r25"]["value"])
    out = None
    for c in part["steinhart_hart"]:
        inv = c["A1"] + c["B1"] * x + c["C1"] * x * x + c["D1"] * x ** 3
        t = 1 / inv - T0
        out = t if out is None else out
        if ("t_below" in c and t >= c["t_below"]) or ("t_from" in c and t < c["t_from"]):
            continue
        return t
    return float(out)  # type: ignore[arg-type]


def r_beta(part: dict[str, Any], t: float) -> float:
    """B-equation with B25/85 (comparison only)."""
    return part["r25"]["value"] * math.exp(part["b25_85"]["value"] * (1 / (t + T0) - 1 / (T25 + T0)))


def _temp(value: object, name: str) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError
        text = str(value).strip().replace("°C", "").replace("°", "")
        t = float(text[:-1] if text.endswith(("C", "c")) else text)
    except (TypeError, ValueError):
        raise BenchError("invalid_args", f"{name} must be a temperature in °C, got {value!r}", "for example 25") from None
    if not math.isfinite(t) or not -100 <= t <= 300:
        raise BenchError("invalid_args", f"{name} {value!r} is outside −100…300 °C", "for example 25")
    return t


def _adc_range(value: object) -> tuple[float, float]:
    if isinstance(value, dict):
        lo, hi = value.get("min", 0), value.get("max")
    elif isinstance(value, list | tuple) and len(value) == 2:
        lo, hi = value
    else:
        lo, hi = 0, value
    lo_v = ck.num(lo, "V", "adc_range min", allow_zero=True)
    hi_v = ck.num(hi, "V", "adc_range max")
    if lo_v >= hi_v:
        raise BenchError("invalid_args", "adc_range min must be below max", "for example [0.1, 2.9]")
    return lo_v, hi_v


def divider_v(vs: float, r_ntc: float, r_fixed: float, position: str) -> float:
    return vs * (r_ntc if position == "low" else r_fixed) / (r_ntc + r_fixed)


def r_from_v(vs: float, v: float, r_fixed: float, position: str) -> float:
    return r_fixed * v / (vs - v) if position == "low" else r_fixed * (vs - v) / v


def _grid(t_lo: float, t_hi: float) -> list[float]:
    pts = [t_lo]
    t = math.floor(t_lo / 10) * 10 + 10
    while t < t_hi - _EPS:
        pts.append(float(t))
        t += 10
    if t_hi > t_lo:
        pts.append(t_hi)
    return pts


@ck.action(ACTION)
def ntc(part: object = DEFAULT_PART, r_fixed: object = None, v_supply: object = "3.3V", position: object = "low",
        t_min: object = 0, t_max: object = 100, t: object = None, r_ntc: object = None, v_adc: object = None,
        chip: object = "esp32s3", adc_range: object = None, adc_bits: object = None,
        series: object = "E24") -> dict[str, Any]:
    """NTCLE100E3 divider: voltage over the temperature range, ESP input and ADC range, self-heating."""
    p = part_data(part)
    sid = p["source_id"]
    name = p["id"]
    r25 = p["r25"]["value"]
    pos = ck.choice(position, POSITIONS, "position")
    ser = ck.series(series)
    vs = ck.num(v_supply, "V", "v_supply")
    lo_t, hi_t = _temp(t_min, "t_min"), _temp(t_max, "t_max")
    if lo_t >= hi_t:
        raise BenchError("invalid_args", f"t_min {lo_t:g} °C must be below t_max {hi_t:g} °C", "for example 0 and 100")
    given = [n for n, v in (("t", t), ("r_ntc", r_ntc), ("v_adc", v_adc)) if v is not None]
    if len(given) > 1:
        raise BenchError("invalid_args", f"give at most one of t, r_ntc, v_adc (got {', '.join(given)})",
                         "t: temperature -> voltage; r_ntc or v_adc: reading -> temperature")
    inputs: dict[str, Any] = {"part": name, "v_supply": ck.q(vs, "V"), "position": pos,
                              "t_min": ck.q(lo_t, "°C"), "t_max": ck.q(hi_t, "°C")}
    steps: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    assum: list[dict[str, Any]] = [assumption("nominal", f"R25 {_f(r25, 'Ω')}, B25/85 {p['b25_85']['value']:g} K",
                                              "nominal values: R25 tolerance ±2/3/5 % and B tolerance "
                                              f"±{p['b_tol']['value']:g} % are not included (Vishay p. 2, 4)")]

    r_lo, r_hi = r_of_t(p, lo_t), r_of_t(p, hi_t)  # r_lo > r_hi (NTC)
    r_suggest = math.sqrt(r_lo * r_hi)
    r_suggest_e = ck.eseries.nearest(r_suggest, ser)
    steps.append(ck.step("R(t_min)", f"R25·exp(A + B/T + C/T² + D/T³) at {lo_t:g} °C", r_lo, "Ω", 4))
    steps.append(ck.step("R(t_max)", f"R25·exp(A + B/T + C/T² + D/T³) at {hi_t:g} °C", r_hi, "Ω", 4))
    steps.append(ck.step("R_fixed suggestion", f"√({_f(r_lo, 'Ω')} · {_f(r_hi, 'Ω')}) -> {ser}", r_suggest_e, "Ω", 3))
    if r_fixed is None:
        rf = float(r25)
        assum.append(assumption("r_fixed", f"R_fixed = R25 = {_f(rf, 'Ω')}", "r_fixed not given; "
                                f"{_f(r_suggest_e, 'Ω')} ({ser}) gives the largest swing over {lo_t:g}…{hi_t:g} °C"))
    else:
        rf = ck.num(r_fixed, "Ω", "r_fixed")
    inputs["r_fixed"] = ck.q(rf, "Ω")
    assum.append(assumption("position", "NTC to GND" if pos == "low" else "NTC to v_supply",
                            "R_fixed to v_supply, ADC at the node" if pos == "low" else "R_fixed to GND, ADC at the node"))

    # --- temperature range against the datasheet -------------------------------------------------------------------
    op = p["t_op"]
    short = p["t_short_max"]["value"]
    if op["min"] - _EPS <= lo_t and hi_t <= op["max"] + _EPS:
        checks.append(check(f"{ACTION}.t_range", "passed", f"{lo_t:g}…{hi_t:g} °C within {op['min']:g}…{op['max']:g} °C "
                            f"(p. {op['page']})"))
    elif op["min"] - _EPS <= lo_t and hi_t <= short + _EPS:
        checks.append(check(f"{ACTION}.t_range", "failed", f"t_max {hi_t:g} °C above {op['max']:g} °C continuous; "
                            f"≤ {short:g} °C only for short periods (p. 1)"))
        warns.append(warning("ntc_t_short", "caution", f"{name}: above {op['max']:g} °C only for short periods "
                             f"(max {short:g} °C).", [sid]))
    else:
        checks.append(check(f"{ACTION}.t_range", "failed", f"{lo_t:g}…{hi_t:g} °C outside {op['min']:g}…{op['max']:g} °C "
                            f"(short periods ≤ {short:g} °C, p. 1)"))
        warns.append(warning("ntc_t_range", "caution", f"{name} is specified for {op['min']:g}…{op['max']:g} °C; "
                             f"{lo_t:g}…{hi_t:g} °C is outside the datasheet range.", [sid]))
    if vs < p["v_max"]["value"] - _EPS:
        checks.append(check(f"{ACTION}.v_ntc", "passed", f"at most {_f(vs, 'V')} on the NTC, below 50 VDC (p. 2)"))
    else:
        checks.append(check(f"{ACTION}.v_ntc", "failed", f"{_f(vs, 'V')} can reach the NTC: keep it below 50 VDC (p. 2)"))
        warns.append(warning("ntc_v_max", "danger", f"The voltage on the {name} must stay below 50 VDC.", [sid]))

    # --- table over the range ------------------------------------------------------------------------------------
    delta = p["dissipation"]["value"]
    rows = []
    for tt in _grid(lo_t, hi_t):
        r = r_of_t(p, tt)
        v = divider_v(vs, r, rf, pos)
        i = vs / (r + rf)
        pw = i * i * r
        rows.append({"t": ck.q(tt, "°C"), "r_ntc": ck.q(r, "Ω", 4), "v_out": ck.q(v, "V", 4),
                     "p_ntc": ck.q(pw, "W"), "self_heating": ck.q(pw / delta, "K")})
    vals = [r["v_out"]["value"] for r in rows]
    v_lo, v_hi = min(vals), max(vals)
    p_max = max(r["p_ntc"]["value"] for r in rows)
    # largest NTC power over the range: I²R peaks at R = R_fixed when it lies inside [r_hi, r_lo]
    if r_hi <= rf <= r_lo:
        p_max = max(p_max, vs * vs / (4 * rf))
    dt_max = p_max / delta
    v_at = {r["t"]["value"]: r["v_out"]["value"] for r in rows}
    steps.append(ck.step("V_out(t_min)", f"{_f(vs, 'V')} · " + ("R_NTC" if pos == "low" else "R_fixed")
                         + " / (R_NTC + R_fixed)", v_at[lo_t], "V", 4))
    steps.append(ck.step("V_out(t_max)", "same at t_max", v_at[hi_t], "V", 4))
    steps.append(ck.step("P_NTC max", "max of I² · R_NTC over the range (≤ Vs² / (4 · R_fixed))", p_max, "W", 3))
    steps.append(ck.step("self-heating max", f"P / δ = P / {ck.fmt(delta, 'W')}/K", dt_max, "K", 3))

    def sens(tt: float) -> float:
        h = 0.05
        return (divider_v(vs, r_of_t(p, tt + h), rf, pos) - divider_v(vs, r_of_t(p, tt - h), rf, pos)) / (2 * h)

    mid = (lo_t + hi_t) / 2
    s = {"t_min": sens(lo_t + 0.05), "mid": sens(mid), "t_max": sens(hi_t - 0.05)}
    result: dict[str, Any] = {
        "inputs": inputs, "r25": ck.q(r25, "Ω"), "b25_85": ck.q(p["b25_85"]["value"], "K", 4),
        "r_fixed_suggested": ck.q(r_suggest_e, "Ω"), "v_out_min": ck.q(v_lo, "V", 4), "v_out_max": ck.q(v_hi, "V", 4),
        "swing": ck.q(v_hi - v_lo, "V", 3), "p_max": ck.q(p_max, "W"), "self_heating_max": ck.q(dt_max, "K"),
        "dissipation_factor": ck.q(delta, "W/K", 3),
        "sensitivity": {k: ck.q(v, "V", 3) for k, v in s.items()}, "table": rows,
    }

    # --- ESP input and ADC range ---------------------------------------------------------------------------------
    chip_id = str(chip).lower() if isinstance(chip, str) else None
    esp = electrical.get(chip_id) if chip_id else None
    v_in_max = esp.get("v_in_max") if esp else None
    esp_src = list(esp.get("source_ids") or []) if esp else []
    if v_in_max is None:
        checks.append(check(f"{ACTION}.esp_input", "not_checked", f"no input maximum for chip {chip!r} in the data"))
    elif max(v_hi, 0.0) <= v_in_max + _EPS:
        checks.append(check(f"{ACTION}.esp_input", "passed", f"V_out max {_f(v_hi, 'V')} ≤ {chip_id} input max "
                            f"{_f(v_in_max, 'V')}"))
    else:
        checks.append(check(f"{ACTION}.esp_input", "failed", f"V_out max {_f(v_hi, 'V')} > {chip_id} input max "
                            f"{_f(v_in_max, 'V')}"))
        warns.append(warning("ntc_esp_input", "danger", f"The divider reaches {_f(v_hi, 'V')} at the ADC pin, above "
                             f"the {chip_id} input maximum {_f(v_in_max, 'V')}: supply the divider from 3.3 V.", esp_src))
    if adc_range is None:
        checks.append(check(f"{ACTION}.adc_range", "not_checked", "the usable ESP ADC range depends on the "
                            "attenuation and is not in the data: give adc_range [min, max] in V"))
    else:
        a_lo, a_hi = _adc_range(adc_range)
        inputs["adc_range"] = [ck.q(a_lo, "V"), ck.q(a_hi, "V")]
        if a_lo - _EPS <= v_lo and v_hi <= a_hi + _EPS:
            checks.append(check(f"{ACTION}.adc_range", "passed", f"{_f(v_lo, 'V')}…{_f(v_hi, 'V')} within "
                                f"{_f(a_lo, 'V')}…{_f(a_hi, 'V')}"))
        else:
            checks.append(check(f"{ACTION}.adc_range", "failed", f"{_f(v_lo, 'V')}…{_f(v_hi, 'V')} leaves "
                                f"{_f(a_lo, 'V')}…{_f(a_hi, 'V')}"))
            warns.append(warning("ntc_adc_range", "caution", f"The divider output {_f(v_lo, 'V')}…{_f(v_hi, 'V')} "
                                 f"leaves the ADC range {_f(a_lo, 'V')}…{_f(a_hi, 'V')}: readings clip; change "
                                 "r_fixed or the attenuation.", []))
        if adc_bits is not None:
            bits = int(ck.count(adc_bits, "adc_bits"))
            lsb = (a_hi - a_lo) / 2 ** bits
            inputs["adc_bits"] = bits
            result["adc_lsb"] = ck.q(lsb, "V", 3)
            result["resolution"] = {k: ck.q(lsb / abs(v), "K", 3) if v else None for k, v in s.items()}
            steps.append(ck.step("ADC LSB", f"({_f(a_hi, 'V')} − {_f(a_lo, 'V')}) / 2^{bits}", lsb, "V", 3))
    if adc_bits is not None and adc_range is None:
        raise BenchError("invalid_args", "adc_bits needs adc_range", "for example adc_range=[0.1, 2.9], adc_bits=12")

    # --- power: zero-power condition and self-heating ---------------------------------------------------------------
    zp = p["zero_power_fraction"]["value"] * p["p_max"]["value"]
    if p_max <= zp + _EPS:
        checks.append(check(f"{ACTION}.zero_power", "passed", f"P_NTC max {ck.fmt(p_max, 'W')} ≤ 1 % of 500 mW = "
                            f"{ck.fmt(zp, 'W')} (p. 1, 2)"))
    else:
        checks.append(check(f"{ACTION}.zero_power", "failed", f"P_NTC max {ck.fmt(p_max, 'W')} > {ck.fmt(zp, 'W')} "
                            "(1 % of 500 mW): the R/T values assume zero power (p. 2)"))
        warns.append(warning("ntc_power", "caution", f"{name} dissipates up to {ck.fmt(p_max, 'W')}, more than the "
                             f"'zero power' {ck.fmt(zp, 'W')}: it heats itself by up to {dt_max:.2g} K; raise r_fixed.",
                             [sid]))
    assum.append(assumption("max_power", "500 mW at 55 °C", "the datasheet derates above 55 °C (graph only); the "
                            "zero-power limit uses the 55 °C value"))
    assum.append(assumption("dissipation_factor", f"δ = {ck.fmt(delta, 'W')}/K", "for information only "
                            "(Vishay p. 1); in still air, mounting changes it"))
    if dt_max > SELF_HEAT_HINT_K:
        warns.append(warning("ntc_self_heating", "info", f"Self-heating up to {dt_max:.2g} K (P/δ, δ "
                             f"{delta * 1000:g} mW/K) shifts the reading; rule of thumb: keep it below "
                             f"{SELF_HEAT_HINT_K:g} K or power the divider only while sampling.", [sid, ck.RULE]))

    # --- one point: temperature -> voltage, or reading -> temperature -------------------------------------------------
    if t is not None:
        tv = _temp(t, "t")
        r = r_of_t(p, tv)
        v = divider_v(vs, r, rf, pos)
        rb = r_beta(p, tv)
        steps.append(ck.step("R(t)", f"Steinhart-Hart at {tv:g} °C", r, "Ω", 4))
        steps.append(ck.step("R_B(t)", f"R25·exp(B25/85·(1/T − 1/298.15 K)) at {tv:g} °C", rb, "Ω", 4))
        steps.append(ck.step("V_out(t)", "divider", v, "V", 4))
        result["point"] = {"t": ck.q(tv, "°C"), "r_ntc": ck.q(r, "Ω", 4), "r_beta": ck.q(rb, "Ω", 4),
                           "beta_error": ck.q(t_of_r(p, rb) - tv, "K", 2), "v_out": ck.q(v, "V", 4)}
    elif r_ntc is not None or v_adc is not None:
        if v_adc is not None:
            va = ck.num(v_adc, "V", "v_adc")
            if va >= vs - _EPS:
                raise BenchError("invalid_args", f"v_adc {_f(va, 'V')} must be below v_supply {_f(vs, 'V')}",
                                 "an open or shorted NTC reads at a rail")
            r = r_from_v(vs, va, rf, pos)
            steps.append(ck.step("R_NTC", ("R_fixed · V / (Vs − V)" if pos == "low" else "R_fixed · (Vs − V) / V"),
                                 r, "Ω", 4))
            inputs["v_adc"] = ck.q(va, "V", 4)
        else:
            r = ck.num(r_ntc, "Ω", "r_ntc")
            inputs["r_ntc"] = ck.q(r, "Ω", 4)
        tv = t_of_r(p, r)
        steps.append(ck.step("T", "1/T = A1 + B1·ln(R/R25) + C1·ln²(R/R25) + D1·ln³(R/R25)", tv, "°C", 4))
        result["point"] = {"t": ck.q(tv, "°C", 4), "r_ntc": ck.q(r, "Ω", 4)}
        if not op["min"] - 1 <= tv <= short + 1:
            warns.append(warning("ntc_reading_range", "caution", f"{_f(r, 'Ω')} means {tv:.1f} °C, outside the "
                                 f"datasheet range {op['min']:g}…{short:g} °C: check the wiring.", [sid]))

    result["formula"] = ("R(T) = R25·exp(A + B/T + C/T² + D/T³); 1/T = A1 + B1·ln(R/R25) + C1·ln²(R/R25) + "
                         "D1·ln³(R/R25) (T in K); V_out = Vs·R_NTC/(R_NTC + R_fixed) (NTC low) or "
                         "Vs·R_fixed/(R_NTC + R_fixed) (NTC high); ΔT = P/δ")
    result["steps"] = steps
    summary = (f"{name} with {_f(rf, 'Ω')} {'above' if pos == 'low' else 'below'} it at {_f(vs, 'V')}: "
               f"{_f(v_at[lo_t], 'V')} at {lo_t:g} °C … {_f(v_at[hi_t], 'V')} at {hi_t:g} °C, "
               f"self-heating ≤ {dt_max:.2g} K.")
    if "point" in result and "v_out" in result["point"] and t is not None:
        summary += f" At {result['point']['t']['display']}: {result['point']['v_out']['display']}."
    elif "point" in result:
        summary += f" Reading = {result['point']['t']['display']}."
    srcs = [sid, *esp_src] + ([ck.RULE] if dt_max > SELF_HEAT_HINT_K else [])
    return envelope(ACTION, summary, result, checks=checks, warnings=warns, assumptions=assum,
                    sources=ck.sources.resolve(srcs))


NTC_PARAMS = (("part", "str", False, DEFAULT_PART), ("r_fixed", "Ω", False, None), ("v_supply", "V", False, "3.3V"),
              ("position", "str", False, "low"), ("t_min", "°C", False, 0), ("t_max", "°C", False, 100),
              ("t", "°C", False, None), ("r_ntc", "Ω", False, None), ("v_adc", "V", False, None),
              ("chip", "str", False, "esp32s3"), ("adc_range", "range", False, None), ("adc_bits", "int", False, None),
              ("series", "str", False, "E24"))

ck.register("ntc", ntc, NTC_PARAMS, title="NTC thermistor divider (NTCLE100E3)", group="sensing",
            summary="NTCLE100E3 divider voltage over temperature (Steinhart-Hart), ESP input/ADC range, self-heating.")
