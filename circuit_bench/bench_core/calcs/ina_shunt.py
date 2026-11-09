"""Calculator ``ina_shunt``: shunt, calibration and ranges of the TI
INA219, INA226, INA260 and INA3221 current monitors.

Formulas (datasheet page, PDF page index, quoted in ``FACTS``; excerpts tests/corpus/excerpts/mod-powermon-*.txt):
- INA219 (SBOS448G p. 12): Current_LSB_min = I_max / 2^15, Cal = trunc(0.04096 / (Current_LSB · R_shunt)),
  Power_LSB = 20 · Current_LSB. Calibration bits FS15..FS1, FS0 is void (p. 24): an odd Cal is stored as Cal − 1.
  Shunt range by PGA /1../8: ±40/80/160/320 mV (p. 5); shunt LSB 10 µV.
- INA226 (SBOS547C p. 15): Current_LSB_min = I_max / 2^15, CAL = 0.00512 / (Current_LSB · R_shunt),
  Power_LSB = 25 · Current_LSB; CAL bits FS14..FS0 (p. 26), shunt range ±81.92 mV, LSB 2.5 µV (p. 5).
- INA3221 (SBOS576C p. 28): no current register, I = shunt register · 40 µV / R_shunt; range ±163.8 mV (p. 5).
- INA260 (SBOS656C p. 6): integrated shunt, fixed current LSB 1.25 mA and power LSB 10 mW, package resistance
  4.5 mΩ (dissipation), ±15 A continuous.
- Bus / common-mode voltage (also used by modrules/powermon.py through ``BUS``): INA219 and INA3221 at most 26 V
  (absolute maximum), INA226 and INA260 0–36 V operating, 40 V absolute maximum.
Deterministic, SI units; nothing is interpolated.
"""
from __future__ import annotations

import math
from typing import Any

from .. import calckit

ACTION = "calc.ina_shunt"
PARTS = ("ina219", "ina226", "ina260", "ina3221")
SRC = {p: f"mod-powermon-{p}-ds" for p in PARTS}


def _f(part: str, value: Any, unit: str, page: int, evidence: Any, conditions: str | None = None) -> dict[str, Any]:
    out = {"value": value, "unit": unit, "page": page, "evidence": evidence, "source_id": SRC[part]}
    if conditions:
        out["conditions"] = conditions
    return out


# cited numbers of this calculator: every evidence is a line part of the source's excerpt on that page (tested)
FACTS: dict[str, dict[str, dict[str, Any]]] = {
    "ina219": {
        "cal_k": _f("ina219", 0.04096, "", 12, "0.04096 is an internal fixed value used to ensure scaling is maintained properly"),
        "power_ratio": _f("ina219", 20, "", 12, "Power_LSB = 20 Current_LSB"),
        "lsb_bits": _f("ina219", 15, "bit", 12, ["Maximum Expected Current", "15Current_LSB ="],
                       "Current_LSB = Maximum Expected Current / 2^15 (Equation 2)"),
        "range_pga1": _f("ina219", 0.040, "V", 5, "PGA = /1 0 ±40 0 ±40 mV"),
        "range_pga2": _f("ina219", 0.080, "V", 5, "PGA = /2 0 ±80 0 ±80 mV"),
        "range_pga4": _f("ina219", 0.160, "V", 5, "PGA = /4 0 ±160 0 ±160 mV"),
        "range_pga8": _f("ina219", 0.320, "V", 5, "PGA = /8 0 ±320 0 ±320 mV"),
        "v_lsb": _f("ina219", 1e-05, "V", 5, "Shunt voltage, 1 LSB step size 10 10 μV"),
        "cal_fs0": _f("ina219", 65534, "", 24, "FS0 is a void bit and will always be 0.",
                      "largest calibration value: FS15..FS1 set, FS0 always 0"),
        "bus_abs": _f("ina219", 26.0, "V", 4, "IN+, IN– Common-mode(VIN+ + VIN–) / 2 -0.3 26 V", "absolute maximum"),
        "bus_max": _f("ina219", 26.0, "V", 5, "In no event should more than 26 V be applied to this device."),
    },
    "ina226": {
        "cal_k": _f("ina226", 0.00512, "", 15, "0.00512 is an internal fixed value used to verify scaling is maintained properly"),
        "power_ratio": _f("ina226", 25, "", 15, "The Power Register (03h) is internally set to be 25 times the"),
        "lsb_bits": _f("ina226", 15, "bit", 15, ["Current_LSB = Maximum\u00a0Expected\u00a0Current", "215 (2)"],
                       "Current_LSB = Maximum Expected Current / 2^15 (Equation 2)"),
        "range": _f("ina226", 0.08192, "V", 5, "Shunt voltage input range –81.9175 81.92 mV"),
        "v_lsb": _f("ina226", 2.5e-06, "V", 5, "Shunt voltage 2.5 μV"),
        "cal_max": _f("ina226", 32767, "", 26, "NAME — FS14 FS13 FS12 FS11 FS10 FS9 FS8 FS7 FS6 FS5 FS4 FS3 FS2 FS1 FS0",
                      "largest calibration value: FS14..FS0 (D15 unused)"),
        "bus_abs": _f("ina226", 40.0, "V", 4, "VVBUS –0.3 40 V", "absolute maximum"),
        "bus_max": _f("ina226", 36.0, "V", 5, "Bus voltage input range(1) 0 36 V"),
    },
    "ina260": {
        "i_lsb": _f("ina260", 0.00125, "A", 6, "Current 1.25 mA", "1-LSB step size, fixed"),
        "p_lsb": _f("ina260", 0.010, "W", 6, "Power 10 mW", "1-LSB step size, fixed"),
        "r_package": _f("ina260", 0.0045, "Ω", 6, "Package resistance IN+ to IN– 4.5 mΩ"),
        "i_cont": _f("ina260", 15.0, "A", 6, "Maximum continuous current –40°C ≤ TA ≤ 85°C ±15 A", "−40 °C to 85 °C"),
        "bus_abs": _f("ina260", 40.0, "V", 5, "VBUS pin –0.3 40", "absolute maximum"),
        "bus_max": _f("ina260", 36.0, "V", 6, "Bus voltage input range (1) 0 36 V"),
    },
    "ina3221": {
        "v_lsb": _f("ina3221", 4e-05, "V", 28, "Full-scale range = 163.8mV (decimal = 7FF8); LSB (SD0): 40μV."),
        "range": _f("ina3221", 0.1638, "V", 5, "VSHUNT Shunt voltage input –163.84 163.8 mV"),
        "bus_abs": _f("ina3221", 26.0, "V", 4, "VCommon-mode (VIN+) + (VIN–) / 2 –0.3 26", "absolute maximum"),
        "bus_max": _f("ina3221", 26.0, "V", 5, "VBUS Bus voltage input 0 26 V"),
    },
}
EXAMPLES = {  # datasheet examples the tests recompute
    "ina219": _f("ina219", 20480, "", 26, "Equation 1 results in a calibration value of 20480 (5000h)."),
    "ina226": _f("ina226", 2560, "", 15, "of 2560, or A00h."),
}
PGAS = (1, 2, 4, 8)

# bus / common-mode limits per part and the pins they apply to (modrules/powermon.py)
BUS: dict[str, dict[str, Any]] = {
    "ina219": {"pins": ("IN+", "IN-"), "max": FACTS["ina219"]["bus_max"], "abs": FACTS["ina219"]["bus_abs"]},
    "ina226": {"pins": ("IN+", "IN-", "VBUS"), "max": FACTS["ina226"]["bus_max"], "abs": FACTS["ina226"]["bus_abs"]},
    "ina260": {"pins": ("IN+", "IN-", "VBUS"), "max": FACTS["ina260"]["bus_max"], "abs": FACTS["ina260"]["bus_abs"]},
    "ina3221": {"pins": ("IN+1", "IN-1", "IN+2", "IN-2", "IN+3", "IN-3", "VPU"), "max": FACTS["ina3221"]["bus_max"],
                "abs": FACTS["ina3221"]["bus_abs"]},
}

FORMULA = {
    "ina219": "Current_LSB ≥ I_max/2^15; Cal = trunc(0.04096/(Current_LSB·R_shunt)); Power_LSB = 20·Current_LSB",
    "ina226": "Current_LSB ≥ I_max/2^15; CAL = trunc(0.00512/(Current_LSB·R_shunt)); Power_LSB = 25·Current_LSB",
    "ina3221": "I = shunt register · 40 µV / R_shunt",
    "ina260": "integrated shunt: I = current register · 1.25 mA, P = power register · 10 mW",
}


def _v(part: str, key: str) -> float:
    return float(FACTS[part][key]["value"])


def _cite(part: str, key: str) -> str:
    f = FACTS[part][key]
    return f"{part.upper()} datasheet p. {f['page']}"


def round_lsb(x: float) -> float:
    """Smallest 1-2-5 step (× 10^n) ≥ x: the 'round number above the minimum' the datasheets suggest."""
    if x <= 0 or not math.isfinite(x):
        raise ValueError("current LSB must be positive")
    exp = math.floor(math.log10(x))
    for e in (exp, exp + 1):
        for m in (1, 2, 5):
            c = m * 10.0 ** e
            if c >= x * (1 - 1e-12):
                return calckit.sig(c)
    raise AssertionError("unreachable")


def _pga(value: object) -> int | None:
    if value is None or (isinstance(value, str) and value.strip().lower() in ("", "auto")):
        return None
    text = str(value).strip().lower().lstrip("/")
    mv = {"40mv": 1, "80mv": 2, "160mv": 4, "320mv": 8}
    if text in mv:
        return mv[text]
    try:
        n = int(float(text))
    except ValueError:
        n = -1
    if n not in PGAS:
        raise calckit.BenchError("invalid_args", f"pga must be auto, 1, 2, 4 or 8 (or 40mV … 320mV), got {value!r}",
                                 "PGA /8 gives ±320 mV, /1 ±40 mV (INA219 only)")
    return n


def _bus_checks(part: str, v_bus: float | None, checks: list, warns: list, srcs: list) -> dict[str, Any] | None:
    lim, absmax = _v(part, "bus_max"), _v(part, "bus_abs")
    if v_bus is None:
        checks.append(calckit.check(f"{ACTION}.bus_voltage", "not_checked",
                                    f"give v_bus to compare with the bus range 0–{calckit.fmt(lim, 'V')}"))
        return None
    out = {"v_bus": calckit.q(v_bus, "V"), "max": calckit.q(lim, "V"), "abs_max": calckit.q(absmax, "V")}
    if v_bus > absmax + 1e-9:
        checks.append(calckit.check(f"{ACTION}.bus_voltage", "failed",
                                    f"V_bus {calckit.fmt(v_bus, 'V')} > absolute maximum {calckit.fmt(absmax, 'V')} "
                                    f"({_cite(part, 'bus_abs')})"))
        warns.append(calckit.warning("bus_over_abs_max", "danger",
                                     f"{part.upper()}: {calckit.fmt(v_bus, 'V')} on IN+/IN- exceeds the absolute maximum "
                                     f"{calckit.fmt(absmax, 'V')}; the chip can be damaged.", [SRC[part]]))
    elif v_bus > lim + 1e-9:
        checks.append(calckit.check(f"{ACTION}.bus_voltage", "failed",
                                    f"V_bus {calckit.fmt(v_bus, 'V')} > bus range {calckit.fmt(lim, 'V')} "
                                    f"({_cite(part, 'bus_max')})"))
        warns.append(calckit.warning("bus_over_range", "caution",
                                     f"{part.upper()}: {calckit.fmt(v_bus, 'V')} is above the bus range 0–"
                                     f"{calckit.fmt(lim, 'V')} (absolute maximum {calckit.fmt(absmax, 'V')}).",
                                     [SRC[part]]))
    else:
        checks.append(calckit.check(f"{ACTION}.bus_voltage", "passed",
                                    f"V_bus {calckit.fmt(v_bus, 'V')} within 0–{calckit.fmt(lim, 'V')}"))
    srcs.append(SRC[part])
    return out


def _power_check(p: float, p_rating: float | None, what: str, checks: list, warns: list, assum: list) -> None:
    if p_rating is None:
        checks.append(calckit.check(f"{ACTION}.shunt_power", "not_checked",
                                    f"give p_rating to compare {calckit.fmt(p, 'W')} with the {what} rating"))
        assum.append(calckit.assumption("shunt_rating", f"≥ {calckit.fmt(2 * p, 'W')}",
                                        "rule of thumb: rate the shunt for twice its dissipation"))
    elif p > p_rating + 1e-12:
        checks.append(calckit.check(f"{ACTION}.shunt_power", "failed",
                                    f"{calckit.fmt(p, 'W')} > rating {calckit.fmt(p_rating, 'W')}"))
        warns.append(calckit.warning("shunt_overload", "caution",
                                     f"The {what} dissipates {calckit.fmt(p, 'W')} at I_max, more than its rating "
                                     f"{calckit.fmt(p_rating, 'W')}: pick a larger part or a smaller resistance."))
    else:
        checks.append(calckit.check(f"{ACTION}.shunt_power", "passed",
                                    f"{calckit.fmt(p, 'W')} ≤ rating {calckit.fmt(p_rating, 'W')}"))


def _range_check(part: str, v_sh: float, rng: float, label: str, checks: list, warns: list) -> bool:
    ok = v_sh <= rng + 1e-12
    checks.append(calckit.check(f"{ACTION}.shunt_range", "passed" if ok else "failed",
                                f"V_shunt {calckit.fmt(v_sh, 'V')} at I_max {'≤' if ok else '>'} {label} "
                                f"±{calckit.fmt(rng, 'V')}"))
    if not ok:
        warns.append(calckit.warning("shunt_over_range", "caution",
                                     f"{part.upper()}: {calckit.fmt(v_sh, 'V')} across the shunt at I_max exceeds the "
                                     f"input range ±{calckit.fmt(rng, 'V')}; the reading clips. Use a smaller "
                                     "shunt.", [SRC[part]]))
    return ok


def _cal_part(part: str, i_max: float, r: float, current_lsb: float | None, pga: int | None,
              checks: list, warns: list, assum: list, steps: list) -> dict[str, Any]:
    """INA219 / INA226: Current_LSB, CAL, Power_LSB, ranges."""
    bits = int(FACTS[part]["lsb_bits"]["value"])
    lsb_min = i_max / 2 ** bits
    steps.append(calckit.step("Current_LSB_min", f"{calckit.fmt(i_max, 'A')} / 2^{bits}", lsb_min, "A"))
    if current_lsb is None:
        lsb = round_lsb(lsb_min)
        assum.append(calckit.assumption("current_lsb", calckit.fmt(lsb, "A"),
                                        "rounded up to a 1-2-5 step above the minimum (datasheet: a round number "
                                        "above the minimum simplifies the conversion)"))
    else:
        lsb = current_lsb
        if lsb < lsb_min * (1 - 1e-9):
            checks.append(calckit.check(f"{ACTION}.current_lsb", "failed",
                                        f"Current_LSB {calckit.fmt(lsb, 'A')} < minimum {calckit.fmt(lsb_min, 'A')}"))
            warns.append(calckit.warning("current_register_overflow", "caution",
                                         f"With Current_LSB {calckit.fmt(lsb, 'A')} the current register ends at "
                                         f"{calckit.fmt(lsb * (2 ** bits - 1), 'A')}, below I_max "
                                         f"{calckit.fmt(i_max, 'A')}.", [SRC[part]]))
        else:
            checks.append(calckit.check(f"{ACTION}.current_lsb", "passed",
                                        f"Current_LSB {calckit.fmt(lsb, 'A')} ≥ minimum {calckit.fmt(lsb_min, 'A')}"))
    k = _v(part, "cal_k")
    cal_exact = k / (lsb * r)
    cal = math.floor(cal_exact + 1e-9)
    steps.append(calckit.step("CAL", f"trunc({k} / ({calckit.fmt(lsb, 'A')} · {calckit.fmt(r, 'Ω')}))", cal, "", 6))
    cal_max = int(FACTS[part]["cal_fs0" if part == "ina219" else "cal_max"]["value"])
    cal_reg = cal
    if part == "ina219" and cal % 2 == 1:
        cal_reg = cal - 1
        warns.append(calckit.warning("cal_bit0_void", "info",
                                     f"INA219: bit FS0 of the calibration register is void, so {cal} is stored as "
                                     f"{cal_reg}; the current then reads {calckit.sig(100 / max(cal_reg, 1), 3)} % "
                                     "low relative to Current_LSB.", [SRC[part]]))
    if cal < 1 or cal > cal_max:
        checks.append(calckit.check(f"{ACTION}.cal_range", "failed",
                                    f"CAL {cal} outside 1–{cal_max} ({_cite(part, 'cal_fs0' if part == 'ina219' else 'cal_max')})"))
        lsb_ok = k / (cal_max * r)
        warns.append(calckit.warning("cal_out_of_range", "caution",
                                     f"CAL {cal} does not fit the register (1–{cal_max}): "
                                     + (f"raise current_lsb to at least {calckit.fmt(lsb_ok, 'A')}." if cal > cal_max
                                        else "lower current_lsb or use a larger shunt."), [SRC[part]]))
    else:
        checks.append(calckit.check(f"{ACTION}.cal_range", "passed", f"CAL {cal} within 1–{cal_max}"))
    ratio = int(FACTS[part]["power_ratio"]["value"])
    p_lsb = ratio * lsb
    steps.append(calckit.step("Power_LSB", f"{ratio} · {calckit.fmt(lsb, 'A')}", p_lsb, "W"))
    v_sh = i_max * r
    if part == "ina219":
        ranges = {g: _v(part, f"range_pga{g}") for g in PGAS}
        if pga is None:
            pga = next((g for g in PGAS if v_sh <= ranges[g] + 1e-12), 8)
            assum.append(calckit.assumption("pga", f"/{pga}", "smallest PGA range that holds V_shunt at I_max"))
        rng, label = ranges[pga], f"PGA /{pga}"
    else:
        rng, label = _v(part, "range"), "input range"
    _range_check(part, v_sh, rng, label, checks, warns)
    v_lsb = _v(part, "v_lsb")
    adc_step = v_lsb / r
    if lsb < adc_step * (1 - 1e-9):
        warns.append(calckit.warning("lsb_below_adc_step", "info",
                                     f"Current_LSB {calckit.fmt(lsb, 'A')} is finer than the ADC step "
                                     f"{calckit.fmt(v_lsb, 'V')} / R_shunt = {calckit.fmt(adc_step, 'A')}: no extra "
                                     "resolution.", [SRC[part]]))
    out = {"current_lsb_min": calckit.q(lsb_min, "A"), "current_lsb": calckit.q(lsb, "A"), "cal": cal,
           "cal_register": cal_reg, "cal_hex": f"0x{cal_reg & 0xFFFF:04X}", "power_lsb": calckit.q(p_lsb, "W"),
           "v_shunt_max": calckit.q(v_sh, "V"), "shunt_range": calckit.q(rng, "V"), "adc_step": calckit.q(adc_step, "A"),
           "i_full_scale": calckit.q(rng / r, "A")}
    if part == "ina219":
        out["pga"] = pga
    return out


@calckit.action(ACTION)
def ina_shunt(part: object, i_max: object, *, r_shunt: object = None, current_lsb: object = None,
              pga: object = "auto", v_bus: object = None, p_rating: object = None) -> dict[str, Any]:
    """Shunt and register values of an INA219/INA226/INA260/INA3221 for a maximum current."""
    name = calckit.choice(part, PARTS, "part")
    imax = calckit.num(i_max, "A", "i_max")
    vbus = calckit.num(v_bus, "V", "v_bus", allow_zero=True) if v_bus is not None else None
    prat = calckit.num(p_rating, "W", "p_rating") if p_rating is not None else None
    checks: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    assum: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    srcs = [SRC[name]]
    inputs: dict[str, Any] = {"part": name, "i_max": calckit.q(imax, "A")}
    if name == "ina260":
        if r_shunt is not None:
            raise calckit.BenchError("invalid_args", "the INA260 has an integrated 2 mΩ shunt; r_shunt does not apply",
                                     "omit r_shunt for part=ina260")
        if current_lsb is not None or _pga(pga) is not None:
            raise calckit.BenchError("invalid_args", "the INA260 has fixed scaling (no calibration, no PGA)",
                                     "omit current_lsb and pga for part=ina260")
        i_lsb, p_lsb, r_pkg, i_cont = (_v(name, k) for k in ("i_lsb", "p_lsb", "r_package", "i_cont"))
        if imax > i_cont + 1e-9:
            checks.append(calckit.check(f"{ACTION}.current", "failed",
                                        f"I_max {calckit.fmt(imax, 'A')} > ±{calckit.fmt(i_cont, 'A')} continuous"))
            warns.append(calckit.warning("current_over_rating", "danger",
                                         f"INA260: {calckit.fmt(imax, 'A')} exceeds the continuous rating ±"
                                         f"{calckit.fmt(i_cont, 'A')} of the integrated shunt.", [SRC[name]]))
        else:
            checks.append(calckit.check(f"{ACTION}.current", "passed",
                                        f"I_max {calckit.fmt(imax, 'A')} ≤ ±{calckit.fmt(i_cont, 'A')} continuous"))
        p = imax ** 2 * r_pkg
        steps.append(calckit.step("P_package", f"({calckit.fmt(imax, 'A')})² · {calckit.fmt(r_pkg, 'Ω')}", p, "W"))
        _power_check(p, prat, "INA260 package", checks, warns, assum)
        result = {"current_lsb": calckit.q(i_lsb, "A"), "power_lsb": calckit.q(p_lsb, "W"),
                  "r_package": calckit.q(r_pkg, "Ω"), "p_shunt": calckit.q(p, "W"),
                  "counts_at_i_max": int(imax / i_lsb)}
        summary = (f"INA260: fixed {calckit.fmt(i_lsb, 'A')}/bit and {calckit.fmt(p_lsb, 'W')}/bit; "
                   f"{calckit.fmt(p, 'W')} in the package at {calckit.fmt(imax, 'A')}.")
    else:
        if r_shunt is None:
            raise calckit.BenchError("invalid_args", "r_shunt is required for this part",
                                     "give r_shunt, e.g. '0.1' (R100 on most breakouts) or '2m'")
        r = calckit.num(r_shunt, "Ω", "r_shunt")
        inputs["r_shunt"] = calckit.q(r, "Ω")
        p = imax ** 2 * r
        if name == "ina3221":
            if current_lsb is not None or _pga(pga) is not None:
                raise calckit.BenchError("invalid_args", "the INA3221 has no calibration register and no PGA",
                                         "omit current_lsb and pga for part=ina3221")
            v_lsb, rng = _v(name, "v_lsb"), _v(name, "range")
            step = v_lsb / r
            steps.append(calckit.step("I_step", f"{calckit.fmt(v_lsb, 'V')} / {calckit.fmt(r, 'Ω')}", step, "A"))
            v_sh = imax * r
            _range_check(name, v_sh, rng, "input range", checks, warns)
            result = {"current_step": calckit.q(step, "A"), "v_shunt_max": calckit.q(v_sh, "V"),
                      "shunt_range": calckit.q(rng, "V"), "i_full_scale": calckit.q(rng / r, "A"),
                      "counts_at_i_max": int(v_sh / v_lsb)}
            summary = (f"INA3221 with {calckit.fmt(r, 'Ω')}: {calckit.fmt(step, 'A')} per LSB, full scale "
                       f"{calckit.fmt(rng / r, 'A')}; I = register · 40 µV / R_shunt.")
        else:
            lsb = calckit.num(current_lsb, "A", "current_lsb") if current_lsb is not None else None
            result = _cal_part(name, imax, r, lsb, _pga(pga), checks, warns, assum, steps)
            summary = (f"{name.upper()} with {calckit.fmt(r, 'Ω')} for {calckit.fmt(imax, 'A')}: Current_LSB "
                       f"{result['current_lsb']['display']}, CAL {result['cal_register']} ({result['cal_hex']}), "
                       f"Power_LSB {result['power_lsb']['display']}.")
        steps.append(calckit.step("P_shunt", f"({calckit.fmt(imax, 'A')})² · {calckit.fmt(r, 'Ω')}", p, "W"))
        result["p_shunt"] = calckit.q(p, "W")
        _power_check(p, prat, "shunt", checks, warns, assum)
    bus = _bus_checks(name, vbus, checks, warns, srcs)
    if bus:
        result["bus"] = bus
    result.update({"inputs": inputs, "formula": FORMULA[name], "steps": steps})
    if prat is not None:
        inputs["p_rating"] = calckit.q(prat, "W")
    if vbus is not None:
        inputs["v_bus"] = calckit.q(vbus, "V")
    ids = srcs + ([calckit.RULE] if any(a["key"] == "shunt_rating" for a in assum) else [])
    return calckit.envelope(ACTION, summary, result, checks=checks, warnings=warns, assumptions=assum,
                            sources=calckit.sources.resolve(ids))


ina_shunt.choices = {"part": PARTS, "pga": ("auto", *PGAS)}  # type: ignore[attr-defined]  # calckit.meta
calckit.register(
    "ina_shunt", ina_shunt,
    (("part", "str", True, None), ("i_max", "A", True, None), ("r_shunt", "Ω", False, None),
     ("current_lsb", "A", False, None), ("pga", "str", False, "auto"), ("v_bus", "V", False, None),
     ("p_rating", "W", False, None)),
    title="INA219/226/260/3221 shunt and CAL", group="sensing",
    summary="INA current monitors: Current_LSB, CAL, Power_LSB, shunt voltage vs range, shunt loss, bus voltage.")
