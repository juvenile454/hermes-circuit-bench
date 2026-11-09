"""External ADC calculator ``calc.adc_ext``: ADS1115 / ADS1015 PGA choice and
LSB, MCP3008 and PCF8591 code and LSB, input checks against the datasheet limits.

- ADS1115: ``LSB = FSR / 2^16``, ADS1015: ``LSB = FSR / 2^12`` (FSR = the full span 2·FS of ±FS; TI Table 7-1 lists
  the LSB per PGA step). Single-ended inputs use the positive half (TI p. 29): code = floor(V_in / LSB), at most
  2^(n−1) − 1. The PGA choice is the smallest ±FS with FS ≥ v_in_max (best resolution without clipping).
- MCP3008: ``Code = 1024 · V_in / V_REF`` (Microchip p. 17), at most 1023; VREF 0.25 V…VDD.
- PCF8591: ``V_LSB = (V_REF − V_AGND) / 256`` (NXP p. 9) with AGND = 0 V, code at most 255; VREF ≥ 1.6 V.
- Hard checks (from the absolute maximum ratings): input ≤ VDD + 0.3 V (ADS1x15), VDD + 0.6 V (MCP3008), VDD + 0.5 V
  (PCF8591) -> ``danger``. Recommended ranges (input ≤ VDD or VREF, VDD range, VREF range) -> ``caution``.
- calc.divider keeps its ``not_checked`` ADC-range check (no sourced ESP ADC range); this result only gives the
  usable input range of the external ADC as a hint for its ``adc_range``.

Every number below carries source id, page and the verbatim excerpt line (tests/test_mod_adc.py checks them).
"""
from __future__ import annotations

import math
import re
from typing import Any

from .. import calckit as ck
from ..calckit import BenchError, assumption, check, envelope, warning

ACTION = "calc.adc_ext"
PARTS: tuple[str, ...] = ("ads1115", "ads1015", "mcp3008", "pcf8591")
_EPS = 1e-12

# ±FS of the PGA steps with the datasheet LSB (V) and its excerpt line (page 15 / 11)
ADS_PGA: dict[str, dict[str, Any]] = {
    "ads1115": {
        "bits": 16, "source_id": "mod-adc-ads1115-ds", "formula_page": 15, "formula_ev": "LSB = FSR / 216 (4)",
        "steps": [(6.144, 187.5e-6, "±6.144V(1) 187.5μV"), (4.096, 125e-6, "±4.096V(1) 125μV"),
                  (2.048, 62.5e-6, "±2.048V 62.5μV"), (1.024, 31.25e-6, "±1.024V 31.25μV"),
                  (0.512, 15.625e-6, "±0.512V 15.625μV"), (0.256, 7.8125e-6, "±0.256V 7.8125μV")],
    },
    "ads1015": {
        "bits": 12, "source_id": "mod-adc-ads1015-ds", "formula_page": 11, "formula_ev": "LSB = FSR / 212 (2)",
        "steps": [(6.144, 3e-3, "±6.144V(1) 3mV"), (4.096, 2e-3, "±4.096V(1) 2mV"), (2.048, 1e-3, "±2.048V 1mV"),
                  (1.024, 0.5e-3, "±1.024V 0.5mV"), (0.512, 0.25e-3, "±0.512V 0.25mV"),
                  (0.256, 0.125e-3, "±0.256V 0.125mV")],
    },
}

# per part: VDD range, abs-max offset of the inputs, (page, evidence) of each limit
LIMITS: dict[str, dict[str, Any]] = {
    "ads1115": {"vdd": (2.0, 5.5), "vdd_abs": 7.0, "in_off": 0.3, "source_id": "mod-adc-ads1115-ds",
                "ev": {"vdd": (4, "Power supply (VDD to GND) 2 5.5 V"),
                       "vdd_abs": (4, "Power-supply voltage VDD to GND –0.3 7 V"),
                       "in_abs": (4, "Analog input voltage AIN0, AIN1, AIN2, AIN3 GND – 0.3 VDD + 0.3 V"),
                       "in_op": (4, "V(AINx) Absolute input voltage GND VDD V"),
                       "half": (29, "Single-ended configurations use only one-half"),
                       "no_vref": (15, "An external reference cannot be used with these devices.")}},
    "ads1015": {"vdd": (2.0, 5.5), "vdd_abs": 7.0, "in_off": 0.3, "source_id": "mod-adc-ads1015-ds",
                "ev": {"vdd": (4, "Power supply (VDD to GND) 2 5.5 V"),
                       "vdd_abs": (4, "Power-supply voltage VDD to GND –0.3 7 V"),
                       "in_abs": (4, "Analog input voltage AIN0, AIN1, AIN2, AIN3 GND – 0.3 VDD + 0.3 V"),
                       "in_op": (4, "V(AINx) Absolute input voltage GND VDD V"),
                       "no_vref": (11, "An external reference cannot be used with these devices.")}},
    "mcp3008": {"vdd": (2.7, 5.5), "vdd_abs": 7.0, "in_off": 0.6, "vref_min": 0.25, "bits": 10,
                "source_id": "mod-adc-mcp3008-ds",
                "ev": {"vdd": (5, "Operating Voltage V DD 2.7 — 5.5 V"),
                       "vdd_abs": (3, "VDD ..................................................................................7.0V"),
                       "in_abs": (3, "All Inputs and Outputs w.r.t. VSS ............ - 0.6V to VDD +0 . 6 V"),
                       "in_op": (4, "VIN VSS —V REF V"),
                       "vref": (3, "Voltage Range 0.25 — V DD V Note 2"),
                       "code": (17, "1024 V IN")}},
    "pcf8591": {"vdd": (2.5, 6.0), "vdd_abs": 8.0, "in_off": 0.5, "vref_min": 1.6, "bits": 8,
                "source_id": "mod-adc-pcf8591-ds",
                "ev": {"vdd": (17, "VDD supply voltage 2.5 - 6.0 V"),
                       "vdd_abs": (16, "VDD supply voltage \uf02d0.5 +8.0 V"),
                       "in_abs": (16, "VI input voltage any input \uf02d0.5 V DD + 0.5 V"),
                       "in_op": (18, "measuring range V AGND -V REF V"),
                       "vref": (17, "Vref reference voltage V ref > VAGND [2] VSS +1 . 6 - V DD V"),
                       "code": (9, "VREF − VAGND")}},
}

FORMULA = {
    "ads1115": "LSB = FSR / 2^16 with FSR = 2·FS (±FS of the PGA); single-ended code = floor(V_in / LSB), max 32767",
    "ads1015": "LSB = FSR / 2^12 with FSR = 2·FS (±FS of the PGA); single-ended code = floor(V_in / LSB), max 2047",
    "mcp3008": "Code = floor(1024 · V_in / V_REF), max 1023; LSB = V_REF / 1024",
    "pcf8591": "V_LSB = (V_REF − V_AGND) / 256 with V_AGND = 0 V; code = floor(V_in / V_LSB), max 255",
}
_NUM = re.compile(r"^\s*±?\s*([0-9]*\.?[0-9]+)\s*(m?)V?\s*$", re.IGNORECASE)


def _pga(value: object, part: str) -> float:
    """±FS in V from 2.048, '2.048', '±2.048V', '256mV'; must be one of the PGA steps."""
    steps = [s[0] for s in ADS_PGA[part]["steps"]]
    fs: float | None = None
    if isinstance(value, int | float) and not isinstance(value, bool):
        fs = float(value)
    elif isinstance(value, str) and (m := _NUM.match(value)):
        fs = float(m.group(1)) / (1000.0 if m.group(2) else 1.0)
    for s in steps:
        if fs is not None and abs(fs - s) < 1e-6:
            return s
    raise BenchError("invalid_args", f"pga must be one of the full-scale ranges {', '.join(f'±{s:g} V' for s in steps)}"
                     f", got {value!r}", "for example pga='2.048' (±2.048 V); leave it out to pick the best range")


def _code(v: float, lsb: float, top: int) -> int:
    return max(0, min(top, math.floor(v / lsb + 1e-9)))


def _f(v: float, unit: str = "V") -> str:
    return ck.fmt(v, unit, 4)


@ck.action(ACTION)
def adc_ext(v_in_max: object, vdd: object, *, part: object = "ads1115", pga: object = None,
            vref: object = None) -> dict[str, Any]:
    """Input range, PGA choice, LSB and code of an external ADC (single-ended input 0…v_in_max)."""
    pid = ck.choice(part, PARTS, "part")
    vin = ck.num(v_in_max, "V", "v_in_max")
    vd = ck.num(vdd, "V", "vdd")
    lim = LIMITS[pid]
    sid = lim["source_id"]
    ev = lim["ev"]
    is_ads = pid in ADS_PGA
    if is_ads and vref is not None:
        raise BenchError("invalid_args", f"{pid.upper()} has an internal reference only; vref does not apply "
                         f"(datasheet p. {ev['no_vref'][0]})", "leave vref out; choose the range with pga")
    if not is_ads and pga is not None:
        raise BenchError("invalid_args", f"{pid.upper()} has no PGA; its range is set by VREF",
                         "give vref (default: vdd) instead of pga")
    inputs: dict[str, Any] = {"part": pid, "v_in_max": ck.q(vin, "V"), "vdd": ck.q(vd, "V")}
    checks: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    assum: list[dict[str, Any]] = [
        assumption("input", "single-ended, 0 V…v_in_max against GND", "differential inputs and negative voltages are "
                   "not part of this calculator")]
    steps: list[dict[str, Any]] = []
    name = pid.upper()

    # --- supply -------------------------------------------------------------------------------------------------
    lo, hi = lim["vdd"]
    if vd > lim["vdd_abs"] + _EPS:
        checks.append(check(f"{ACTION}.vdd_range", "failed", f"VDD {_f(vd)} exceeds the absolute maximum "
                            f"{_f(lim['vdd_abs'])} (p. {ev['vdd_abs'][0]})"))
        warns.append(warning("adc_vdd_abs_max", "danger", f"{name} VDD {_f(vd)} exceeds the absolute maximum "
                             f"{_f(lim['vdd_abs'])}: the chip can be damaged.", [sid]))
    elif not lo - _EPS <= vd <= hi + _EPS:
        checks.append(check(f"{ACTION}.vdd_range", "failed", f"VDD {_f(vd)} outside the operating range "
                            f"{_f(lo)}–{_f(hi)} (p. {ev['vdd'][0]})"))
        warns.append(warning("adc_vdd_range", "caution", f"{name} VDD {_f(vd)} is outside {_f(lo)}–{_f(hi)}.", [sid]))
    else:
        checks.append(check(f"{ACTION}.vdd_range", "passed", f"VDD {_f(vd)} within {_f(lo)}–{_f(hi)}"))

    # --- input against the absolute maximum (hard) ----------------------------------------------------------------
    v_abs = vd + lim["in_off"]
    steps.append(ck.step("V_in,abs max", f"{_f(vd)} + {_f(lim['in_off'])}", v_abs, "V", 4))
    if vin > v_abs + _EPS:
        checks.append(check(f"{ACTION}.abs_max", "failed", f"v_in_max {_f(vin)} > VDD + {_f(lim['in_off'])} = "
                            f"{_f(v_abs)} (absolute maximum, p. {ev['in_abs'][0]})"))
        warns.append(warning("adc_input_abs_max", "danger", f"{name} input {_f(vin)} exceeds VDD + "
                             f"{_f(lim['in_off'])} = {_f(v_abs)}: the input can be damaged. Divide the signal "
                             "down (calc.divider) or raise VDD.", [sid]))
    else:
        checks.append(check(f"{ACTION}.abs_max", "passed", f"v_in_max {_f(vin)} ≤ VDD + {_f(lim['in_off'])} = "
                            f"{_f(v_abs)}"))

    # --- part-specific scaling --------------------------------------------------------------------------------------
    result: dict[str, Any] = {"inputs": inputs}
    if is_ads:
        tab = ADS_PGA[pid]
        bits = tab["bits"]
        top = 2 ** (bits - 1) - 1
        options = []
        for fs, lsb_ds, _ in tab["steps"]:
            options.append({"fsr": f"±{fs:g} V", "fs": ck.q(fs, "V", 4), "lsb": ck.q(lsb_ds, "V", 5),
                            "fits": vin <= fs + _EPS})
        if pga is not None:
            fs = _pga(pga, pid)
            inputs["pga"] = f"±{fs:g} V"
            why = "given"
        else:
            fitting = [s[0] for s in tab["steps"] if vin <= s[0] + _EPS]
            fs = min(fitting) if fitting else tab["steps"][0][0]
            why = "smallest range with FS ≥ v_in_max" if fitting else "largest range (v_in_max is above every FS)"
        lsb_ds = next(s[1] for s in tab["steps"] if s[0] == fs)
        lsb = 2 * fs / 2 ** bits
        steps.append(ck.step("LSB", f"2 · {fs:g} V / 2^{bits}", lsb, "V", 5))
        code = _code(vin, lsb, top)
        steps.append(ck.step("code", f"floor({_f(vin)} / {_f(lsb)})" + (f", max {top}" if vin / lsb > top else ""),
                             code, "", 6))
        usable = min(fs, vd)
        if vin > fs + _EPS:
            checks.append(check(f"{ACTION}.fsr", "failed", f"v_in_max {_f(vin)} > FS ±{fs:g} V: the code clips at {top}"))
            warns.append(warning("adc_clips", "caution", f"{name} at ±{fs:g} V clips above {fs:g} V (code {top}); "
                                 "choose a larger range or divide the signal.", [sid]))
        else:
            checks.append(check(f"{ACTION}.fsr", "passed", f"v_in_max {_f(vin)} ≤ FS ±{fs:g} V"))
        if fs > vd + _EPS:
            assum.append(assumption("fsr_above_vdd", f"±{fs:g} V > VDD {_f(vd)}", "the range is scaling only; codes "
                                    f"above VDD are never reached (TI p. 15), usable 0…{_f(vd)}"))
        assum.append(assumption("single_ended", f"{bits - 1} bits effective", "single-ended inputs use only the "
                                f"positive half of ±FS (TI p. {ev['half'][0] if 'half' in ev else 29})"))
        result.update({
            "pga": {"fsr": f"±{fs:g} V", "fs": ck.q(fs, "V", 4), "why": why},
            "lsb": ck.q(lsb, "V", 5), "lsb_datasheet": ck.q(lsb_ds, "V", 5),
            "code_at_v_in_max": code, "code_max": top, "bits": bits,
            "usable_max": ck.q(usable, "V", 4), "pga_options": options,
        })
        summary = (f"{name} at VDD {_f(vd)}: PGA ±{fs:g} V, LSB {_f(lsb)}, {_f(vin)} reads code {code} "
                   f"(of {top}).")
    else:
        bits = lim["bits"]
        n = 2 ** bits
        top = n - 1
        vr = ck.num(vref, "V", "vref") if vref is not None else vd
        if vref is None:
            assum.append(assumption("vref", f"VREF = VDD = {_f(vd)}", "vref not given: VREF tied to VDD"))
        inputs["vref"] = ck.q(vr, "V")
        vref_page = ev["vref"][0]
        if vr > v_abs + _EPS:
            checks.append(check(f"{ACTION}.vref_range", "failed", f"VREF {_f(vr)} > VDD + {_f(lim['in_off'])} "
                                f"(absolute maximum, p. {ev['in_abs'][0]})"))
            warns.append(warning("adc_vref_abs_max", "danger", f"{name} VREF {_f(vr)} exceeds VDD + "
                                 f"{_f(lim['in_off'])} = {_f(v_abs)}.", [sid]))
        elif not lim["vref_min"] - _EPS <= vr <= vd + _EPS:
            checks.append(check(f"{ACTION}.vref_range", "failed", f"VREF {_f(vr)} outside {_f(lim['vref_min'])}–VDD "
                                f"(p. {vref_page})"))
            warns.append(warning("adc_vref_range", "caution", f"{name} VREF {_f(vr)} is outside "
                                 f"{_f(lim['vref_min'])}–{_f(vd)}.", [sid]))
        else:
            checks.append(check(f"{ACTION}.vref_range", "passed", f"VREF {_f(vr)} within {_f(lim['vref_min'])}–VDD"))
        lsb = vr / n
        steps.append(ck.step("LSB", f"{_f(vr)} / {n}", lsb, "V", 5))
        code = _code(vin, lsb, top)
        steps.append(ck.step("code", f"floor({n} · {_f(vin)} / {_f(vr)})" + (f", max {top}" if vin / lsb > top else ""),
                             code, "", 6))
        if pid == "pcf8591":
            assum.append(assumption("agnd", "V_AGND = 0 V", "AGND tied to VSS"))
            assum.append(assumption("i2c", "100 kHz", "the PCF8591 limits its I²C bus to 100 kHz (NXP p. 20)"))
        usable = min(vr, vd)
        result.update({"lsb": ck.q(lsb, "V", 5), "code_at_v_in_max": code, "code_max": top, "bits": bits,
                       "usable_max": ck.q(usable, "V", 4)})
        summary = f"{name} with VREF {_f(vr)}: LSB {_f(lsb)}, {_f(vin)} reads code {code} (of {top})."

    # --- input against the recommended range (VDD for ADS1x15, VREF/VDD for the others) ---------------------------
    v_op = vd if is_ads else min(result["usable_max"]["value"], vd)
    if vin <= v_abs + _EPS and vin > v_op + _EPS:
        checks.append(check(f"{ACTION}.input_range", "failed", f"v_in_max {_f(vin)} > {_f(v_op)} "
                            f"(input range, p. {ev['in_op'][0]})"))
        warns.append(warning("adc_input_range", "caution", f"{name} input {_f(vin)} is above the input range "
                             f"0…{_f(v_op)}: the reading clips.", [sid]))
    elif vin <= v_op + _EPS:
        checks.append(check(f"{ACTION}.input_range", "passed", f"v_in_max {_f(vin)} within 0…{_f(v_op)}"))
    else:
        checks.append(check(f"{ACTION}.input_range", "failed", f"v_in_max {_f(vin)} > {_f(v_op)}"))

    result["formula"] = FORMULA[pid]
    result["steps"] = steps
    result["divider_hint"] = (f"to scale a larger signal, run calc.divider with adc_range=[0, {result['usable_max']['value']:g}]"
                              " (its ADC range check stays not_checked: it knows only the ESP32 ADC)")
    return envelope(ACTION, summary, result, checks=checks, warnings=warns, assumptions=assum,
                    sources=ck.sources.resolve([sid]))


ADC_EXT_PARAMS = (("v_in_max", "V", True, None), ("vdd", "V", True, None), ("part", "str", False, "ads1115"),
                  ("pga", "str", False, None), ("vref", "V", False, None))

ck.register("adc_ext", adc_ext, ADC_EXT_PARAMS, title="External ADC range, PGA and LSB", group="sensing",
            summary="ADS1115/ADS1015 PGA and LSB, MCP3008/PCF8591 code; input checked against VDD + 0.3 V and similar.")
