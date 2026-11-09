"""Calculators: LED series resistor, NPN low-side switch, voltage divider, I²C pull-up;
N-channel MOSFET switch and linear regulator in calc_power.py (registered at the end of this module).

Public action functions return the result envelope (contracts.py) and never raise. Inputs are SI numbers or text
with units ("4k7", "10 mA", "3V3"; units.py). Every result carries ``formula`` (text), intermediate ``steps``,
assumptions, warnings and the sources used. Only limits with a source become hard checks; rules of thumb say so.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from . import calckit, eseries, parts, sources
from .contracts import BenchError, assumption, check, envelope, warning

RULE = calckit.RULE
NXP = "nxp-um10204"

# --- low voltage only (product rule: no mains) ---------------------------------------------------------------------
LOW_VOLTAGE_MAX_V = calckit.LOW_VOLTAGE_MAX_V  # product rule, same as schematic.MAX_VOLTS (60 V passes, above fails)
LOW_VOLTAGE_TEXT = calckit.LOW_VOLTAGE_TEXT

# --- I²C (NXP UM10204 Rev. 7.0; quoted in tests/corpus/excerpts/calc-nxp-um10204.txt) ---------------------------
I2C_RC_FACTOR = 0.8473  # §7.1: T = t2 - t1 = 0.8473 × RC (0.3·V_DD -> 0.7·V_DD)
I2C_MODES: dict[str, dict[str, Any]] = {
    "standard": {"label": "Standard-mode", "t_r": 1000e-9, "c_b_max": 400e-12},  # Table 11: t_r max, C_b max
    "fast": {"label": "Fast-mode", "t_r": 300e-9, "c_b_max": 400e-12},
}
I2C_V_OL = 0.4  # Table 10: V_OL1 max at 3 mA sink current, V_DD > 2 V
I2C_I_OL = 0.003  # Table 10: I_OL min at V_OL = 0.4 V (Standard- and Fast-mode)
I2C_V_OL1_VDD_ABOVE = 2.0  # Table 10: V_OL1 holds for V_DD > 2 V
I2C_C_PIN_MAX = 10e-12  # Table 10: C_i max per I/O pin
# c_bus estimate without a measured value: targets + the ESP32 at C_i max, plus a wiring share
I2C_TARGETS_DEFAULT = 1  # assumption: one target device when nothing else is known
I2C_C_WIRES_SHORT = 50e-12  # rule of thumb (source "rule-of-thumb"): short jumper wires and a small board, per line
I2C_FORMULA = "R_min = (V_DD − V_OL) / I_OL; R_max = t_r / (0.8473 · C_b)"

# --- rules of thumb (source "rule-of-thumb") ---------------------------------------------------------------------
LED_P_RATING_FACTOR = 2.0  # resistor power rating >= 2 × dissipation
NPN_V_BE_DEFAULT = 0.7  # typical small-signal silicon BJT
NPN_SATURATION_DIVISOR = 2.0  # saturated if forced beta <= hFE_min / 2
NPN_LOADS: tuple[str, ...] = ("laser", "led", "relay", "motor", "resistive", "other")

# --- R_B sizing without r_base: forced beta I_C / I_B = 10, the ratio of the saturation test
# conditions in onsemi 2N2222A/D Rev. 2, p. 3 (V_CE(sat) max 0.3 V at I_C 150 mA, I_B 15 mA); pinned PDF
# tests/.corpus/calc/onsemi-2n2222a-d-rev2.pdf, retrieved 2026-11-06, quoted in tests/test_agentfix_calc.py.
NPN_FORCED_BETA_DEFAULT = 10
NPN_FORCED_BETA_SOURCE = "onsemi-2n2222a"
NPN_FORCED_BETA_EVIDENCE = ("Collector−Emitter Saturation Voltage", "(IC = 150 mAdc, IB = 15 mAdc)")
NPN_SIZE_SERIES = "E12"

LED_FORMULA = "R = (V_supply − V_f) / I_f; I = (V_supply − V_f) / R_chosen; P_R = I² · R_chosen"
NPN_FORMULA = "I_RB = (V_drive − V_BE) / R_B; I_PD = V_BE / R_PD; I_B = I_RB − I_PD; β_forced = I_load / I_B; P_RB = I_RB² · R_B"
NPN_SIZE_FORMULA = "I_B = I_load / β_forced; R_B = (V_drive − V_BE) / (I_B + V_BE / R_PD), next smaller E12 value"
DIVIDER_FORMULA = "V_out = V_in · R2 / (R1 + R2); I = V_in / (R1 + R2); R_source = R1 · R2 / (R1 + R2)"


# --- helpers: the public calculator kit (calckit.py); the old private names stay for existing callers ----------------
_sig = calckit.sig
_q = calckit.q
_f = calckit.fmt
_AboveLowVoltage = calckit._AboveLowVoltage
_num = calckit.num
_count = calckit.count
_choice = calckit.choice
_series = calckit.series
_step = calckit.step
_action = calckit.action


PIN_LIMIT_CHIP = "esp32s3"  # chip whose values stand in when the calculator is not told the chip
PIN_TOLERANCE = 1e-9  # comparisons with a limit are strict; a value exactly at the limit is fine


def _pin_values(chip: str = PIN_LIMIT_CHIP) -> dict[str, Any] | None:
    """Electrical values of the chip (electrical.get) or None when the data is missing."""
    from . import electrical
    try:
        return electrical.get(chip)
    except Exception:  # noqa: BLE001 - a missing data file must not break a calculator
        return None


def _gpio_current(i_pin: float) -> dict[str, Any]:
    """Note on the pin current (led, npn): a caution above the sourced high-level source current, else an info."""
    esp = _pin_values()
    ioh = None if esp is None else esp.get("ioh")
    if isinstance(ioh, int | float) and i_pin > ioh + PIN_TOLERANCE:
        return warning("gpio_current", "caution",
                       f"The driving pin would have to source {_f(i_pin, 'A')}, above the {_f(ioh, 'A')} high-level "
                       "source current of an ESP32-S3 pin (a typical value; chip not given). Do not drive this from a "
                       "GPIO: use a MOSFET (bench_calc mosfet) or a driver stage.", list(esp.get("source_ids") or []))
    return warning("gpio_current", "info", f"The driving pin sources {_f(i_pin, 'A')}. GPIO current limits are not "
                   "checked here (unverified); see the chip datasheet.")


# --- LED ---------------------------------------------------------------------------------------------------------
@_action("calc.led")
def led(v_supply: object, v_f: object, i_f: object, *, series: str = "E12") -> dict[str, Any]:
    """Series resistor for an LED: exact value, next larger E-series value, actual current and power."""
    vs, vf, i = _num(v_supply, "V", "v_supply"), _num(v_f, "V", "v_f"), _num(i_f, "A", "i_f")
    ser = _series(series)
    inputs = {"v_supply": _q(vs, "V"), "v_f": _q(vf, "V"), "i_f": _q(i, "A")}
    rule_sources = sources.resolve([RULE])
    if vf >= vs:
        result = {"inputs": inputs, "r_exact": None, "r_chosen": None, "series": ser, "i_actual": None, "p_r": None,
                  "p_rating_min": None, "r_deviation": None, "formula": LED_FORMULA, "steps": []}
        return envelope(
            "calc.led", f"LED at {_f(vs, 'V')}: V_f {_f(vf, 'V')} leaves no headroom; no series resistor works.", result,
            checks=[check("calc.led.headroom", "failed", f"V_f {_f(vf, 'V')} ≥ V_supply {_f(vs, 'V')}")],
            warnings=[warning("led_no_headroom", "caution",
                              "The LED forward voltage is not below the supply, so the LED stays dark or dim. "
                              "Use a higher supply or a driver made for this LED.")],
            sources=rule_sources)
    r_exact = (vs - vf) / i
    r_chosen = eseries.nearest(r_exact, ser, "up")
    i_act = (vs - vf) / r_chosen
    p_r = i_act ** 2 * r_chosen
    p_min = LED_P_RATING_FACTOR * p_r
    dev = (r_chosen - r_exact) / r_exact * 100
    result = {
        "inputs": inputs,
        "r_exact": _q(r_exact, "Ω"),
        "r_chosen": _q(r_chosen, "Ω"),
        "series": ser,
        "r_deviation": _q(dev, "%"),
        "i_actual": _q(i_act, "A"),
        "p_r": _q(p_r, "W"),
        "p_rating_min": _q(p_min, "W"),
        "formula": LED_FORMULA,
        "steps": [
            _step("R", f"({_f(vs, 'V')} − {_f(vf, 'V')}) / {_f(i, 'A')}", r_exact, "Ω"),
            _step("R_chosen", f"next {ser} value ≥ {_f(r_exact, 'Ω')}", r_chosen, "Ω"),
            _step("I", f"({_f(vs, 'V')} − {_f(vf, 'V')}) / {_f(r_chosen, 'Ω')}", i_act, "A"),
            _step("P_R", f"({_f(i_act, 'A')})² · {_f(r_chosen, 'Ω')}", p_r, "W"),
            _step("P_rating", f"{LED_P_RATING_FACTOR:g} × {_f(p_r, 'W')} (rule of thumb)", p_min, "W"),
        ],
    }
    summary = (f"LED at {_f(vs, 'V')}: {_f(r_exact, 'Ω')} exact, use {_f(r_chosen, 'Ω')} ({ser}) for {_f(i_act, 'A')}, "
               f"{_f(p_r, 'W')} in the resistor (rate it ≥ {_f(p_min, 'W')}, rule of thumb).")
    return envelope(
        "calc.led", summary, result,
        checks=[check("calc.led.headroom", "passed", f"V_supply {_f(vs, 'V')} > V_f {_f(vf, 'V')}")],
        warnings=[_gpio_current(i_act)],
        assumptions=[
            assumption("r_chosen", f"next larger {ser} value", "keeps the current at or below I_f"),
            assumption("p_rating", "2 × P", "power rating with margin (rule of thumb)"),
            assumption("tolerance", "not included", "resistor tolerance and the V_f spread of the LED shift the current"),
        ],
        sources=sources.resolve([eseries.SOURCE_ID, RULE]))


# --- NPN low-side switch -----------------------------------------------------------------------------------------
def _hfe_from_part(part: str, i_c: float) -> tuple[dict[str, Any] | None, str]:
    """(datasheet hFE record or None, reason when None). Unknown part -> (None, reason)."""
    try:
        rec = parts.hfe_min(part, i_c)
    except BenchError as e:
        if e.code == "rule_data_missing":
            return None, f"no datasheet data for part {part!r} (known: {', '.join(parts.ids())})"
        raise
    if rec is None:
        rng = parts.hfe_range(part)
        span = f"{_f(rng[0], 'A')}–{_f(rng[1], 'A')}" if rng else "no rows with a minimum"
        return None, f"I_load {_f(i_c, 'A')} is outside the hFE table of {parts.get(part)['id']} ({span})"
    return rec, ""


def _hfe_record(rec: dict[str, Any]) -> dict[str, Any]:
    return {"value": rec["hfe_min"], "from": "datasheet", "part": rec["part"], "source_id": rec["source_id"],
            "basis": rec["basis"], "conditions": rec["conditions"],
            "rows": [{"i_c": _q(r["i_c"], "A"), "v_ce": _q(r["v_ce"], "V"), "min": r["min"], "evidence": r["evidence"]}
                     for r in rec["rows"]]}


def _npn_saturation(hfe: dict[str, Any], forced_beta: float, i_load: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    limit = hfe["value"] / NPN_SATURATION_DIVISOR
    ok = forced_beta <= limit
    origin = f"{hfe['part']} datasheet" if hfe["from"] == "datasheet" else "your value"
    chk = check("calc.npn.saturation", "passed" if ok else "failed",
                f"β_forced {_f(forced_beta, 'x', 2)} {'≤' if ok else '>'} hFE_min/2 = {_f(limit, 'x', 2)} "
                f"(hFE_min {hfe['value']:g} from {origin}; rule of thumb)")
    hfe["i_b_needed"] = _q(i_load / limit, "A")
    warns = [] if ok else [warning(
        "npn_not_saturated", "caution",
        f"The transistor may not saturate: give it at least {_f(i_load / limit, 'A')} base current (rule of thumb) "
        "or use a part with higher gain.", [RULE])]
    return chk, warns


@_action("calc.npn")
def npn(v_drive: object, r_base: object = None, i_load: object = None, *, v_be: object = NPN_V_BE_DEFAULT,
        r_pulldown: object = None, hfe_min: object = None, part: object = None, load: object = None,
        forced_beta: object = None) -> dict[str, Any]:
    """NPN transistor as a low-side switch driven from a GPIO through R_B (optional base pull-down R_PD).
    Without ``r_base`` R_B is sized for ``forced_beta`` (default 10, the 2N2222A saturation test ratio) and rounded
    down to E12; then everything is checked as with a given R_B."""
    vd, il = _num(v_drive, "V", "v_drive"), _num(i_load, "A", "i_load")
    vbe = _num(v_be, "V", "v_be")
    rpd = None if r_pulldown is None else _num(r_pulldown, "Ω", "r_pulldown")
    fb_user = None if forced_beta is None else _count(forced_beta, "forced_beta")
    sizing: dict[str, Any] | None = None
    if r_base is None:
        sizing = _npn_size(vd, il, vbe, rpd, fb_user)
        rb = sizing["chosen"]
    else:
        rb = _num(r_base, "Ω", "r_base")
    h_user = None if hfe_min is None else _count(hfe_min, "hfe_min")
    if part is not None and (not isinstance(part, str) or not part.strip()):
        raise BenchError("invalid_args", f"part must be a part number such as 2N2222A, got {part!r}",
                         f"known parts: {', '.join(parts.ids())}; or give hfe_min from your datasheet")
    part_name = part.strip() if isinstance(part, str) else None
    kind = None if load is None else _choice(load, NPN_LOADS, "load")

    inputs: dict[str, Any] = {"v_drive": _q(vd, "V"), "r_base": _q(rb, "Ω"), "i_load": _q(il, "A"), "v_be": _q(vbe, "V")}
    if sizing is not None:
        inputs["forced_beta"] = sizing["beta"]
    if rpd is not None:
        inputs["r_pulldown"] = _q(rpd, "Ω")
    if h_user is not None:
        inputs["hfe_min"] = h_user
    if part_name is not None:
        inputs["part"] = part_name
    if kind is not None:
        inputs["load"] = kind

    checks: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    source_ids: list[str] = [RULE]
    default_vbe = math.isclose(vbe, NPN_V_BE_DEFAULT, rel_tol=1e-12)
    assum = [assumption("v_be", f"{vbe:g} V", "typical small-signal silicon BJT; check the datasheet"
                        if default_vbe else "given by you")]

    i_rb = (vd - vbe) / rb if vd > vbe else 0.0
    i_pd = vbe / rpd if rpd is not None else 0.0
    i_b = i_rb - i_pd
    p_rb = i_rb ** 2 * rb
    forced_beta = il / i_b if i_b > 0 else None

    steps = [] if sizing is None else list(sizing["steps"])
    steps.append(_step("I_RB", f"({_f(vd, 'V')} − {_f(vbe, 'V')}) / {_f(rb, 'Ω')}" if vd > vbe
                       else f"V_drive {_f(vd, 'V')} ≤ V_BE {_f(vbe, 'V')}", i_rb, "A"))
    if rpd is not None:
        steps.append(_step("I_PD", f"{_f(vbe, 'V')} / {_f(rpd, 'Ω')}", i_pd, "A"))
        assum.append(assumption("v_rpd", "V_BE", "while the transistor is on, R_PD sees V_BE"))
    if forced_beta is not None:
        steps.append(_step("I_B", f"{_f(i_rb, 'A')} − {_f(i_pd, 'A')}", i_b, "A"))
        steps.append(_step("β_forced", f"{_f(il, 'A')} / {_f(i_b, 'A')}", forced_beta, "x", 2))
        checks.append(check("calc.npn.base_drive", "passed", f"I_B {_f(i_b, 'A')} > 0"))
    else:
        why = (f"V_drive {_f(vd, 'V')} ≤ V_BE {_f(vbe, 'V')}" if vd <= vbe
               else f"R_PD takes {_f(i_pd, 'A')} of {_f(i_rb, 'A')}")
        checks.append(check("calc.npn.base_drive", "failed", f"no base current: {why}"))
        warns.append(warning("npn_no_base_current", "caution",
                             "The transistor does not turn on. Lower R_B, raise R_PD or use a higher drive voltage."))
    steps.append(_step("P_RB", f"({_f(i_rb, 'A')})² · {_f(rb, 'Ω')}", p_rb, "W"))

    # hFE: your value, else a datasheet row, else nothing (saturation not_checked)
    hfe: dict[str, Any] | None = None
    reason = "give hfe_min or part to check saturation"
    if h_user is not None:
        hfe = {"value": h_user, "from": "user"}
        assum.append(assumption("hfe_min", f"{h_user:g}", "given by you; not checked against a datasheet"))
        if part_name is not None:
            warns.append(warning("hfe_min_given", "info", "hfe_min was given, so the datasheet table of the part is not used."))
    elif part_name is not None:
        rec, reason = _hfe_from_part(part_name, il)
        if rec is not None:
            hfe = _hfe_record(rec)
            source_ids.append(rec["source_id"])
            row = rec["rows"][0]
            if rec["basis"] == "between_rows":
                lo, hi = rec["rows"]
                assum.append(assumption(
                    "hfe_min", f"{rec['hfe_min']:g}",
                    f"the datasheet lists I_C {_f(lo['i_c'], 'A')} (min {lo['min']}) and {_f(hi['i_c'], 'A')} "
                    f"(min {hi['min']}); the smaller minimum is used for I_load {_f(il, 'A')}"))
            else:
                assum.append(assumption("hfe_min", f"{rec['hfe_min']:g}", f"datasheet row I_C {_f(row['i_c'], 'A')}"))
            assum.append(assumption("hfe_conditions", f"V_CE {_f(row['v_ce'], 'V')}, {rec['conditions']}",
                                    f"datasheet hFE of {rec['part']} ({rec['source_id']}); other makers and packages "
                                    "differ, and the gain in saturation is lower"))
        elif "no datasheet data" in reason:
            warns.append(warning("part_unknown", "info", f"{reason}; hFE not checked (unverified)."))

    if hfe is not None and forced_beta is not None:
        chk, more = _npn_saturation(hfe, forced_beta, il)
        checks.append(chk)
        warns += more
        assum.append(assumption("saturation", "β_forced ≤ hFE_min / 2", "rule of thumb, not from a datasheet"))
    else:
        checks.append(check("calc.npn.saturation", "not_checked",
                            "no base current" if hfe is not None else reason))

    # collector current rating, only with sourced part data
    rating = None
    if part_name is not None:
        try:
            rating = parts.rating(part_name, "i_c_max")
        except BenchError as e:
            if e.code != "rule_data_missing":
                raise
    if rating is not None and part_name is not None:
        rec_part = parts.get(part_name)
        if rec_part["source_id"] not in source_ids:
            source_ids.append(rec_part["source_id"])
        ok = il <= rating["value"]
        checks.append(check("calc.npn.ic_max", "passed" if ok else "failed",
                            f"I_load {_f(il, 'A')} {'≤' if ok else '>'} I_C continuous {_f(rating['value'], 'A')} "
                            f"({rec_part['id']} datasheet, maximum ratings)"))
        if not ok:
            warns.append(warning("npn_ic_max", "danger",
                                 f"I_load exceeds the continuous collector current of {rec_part['id']}.",
                                 [rec_part["source_id"]]))
    else:
        checks.append(check("calc.npn.ic_max", "not_checked", "give part to compare with its collector current rating"))

    if i_rb > 0:
        warns.append(_gpio_current(i_rb))
    if sizing is not None:
        assum += sizing["assumptions"]
        source_ids += [s for s in sizing["source_ids"] if s not in source_ids]
    elif fb_user is not None:
        warns.append(warning("forced_beta_ignored", "info", "r_base was given, so forced_beta (only used to size R_B) "
                             "is ignored."))
    if kind == "laser":
        warns.append(warning("laser_safety", "danger",
                             "Laser modules can damage eyes. Never look into the beam; keep the output off during boot "
                             "(pull-down)."))
        if rpd is None:
            warns.append(warning("laser_no_pulldown", "caution",
                                 "No base pull-down: while the pin floats (boot, reset, flashing) the laser may switch "
                                 "on. Add a resistor from base to GND (rule of thumb).", [RULE]))
    elif kind in ("relay", "motor"):
        warns.append(warning("inductive_load", "caution",
                             "Inductive load: put a flyback diode across the coil or motor (rule of thumb). "
                             "Low voltage only; never switch mains (230 V) with this bench.", [RULE]))

    result = {
        "inputs": inputs,
        "i_rb": _q(i_rb, "A"),
        "i_pd": _q(i_pd, "A") if rpd is not None else None,
        "i_b": _q(i_b, "A") if forced_beta is not None else None,
        "forced_beta": _q(forced_beta, "x", 2) if forced_beta is not None else None,
        "p_rb": _q(p_rb, "W"),
        "hfe": hfe,
        "formula": NPN_FORMULA + "; saturated if β_forced ≤ hFE_min / 2 (rule of thumb)",
        "steps": steps,
    }
    if sizing is not None:  # additive fields of the sized form
        result.update({"sized": True, "forced_beta_target": sizing["beta"], "r_base_ideal": _q(sizing["ideal"], "Ω"),
                       "r_base_chosen": _q(rb, "Ω"), "series": NPN_SIZE_SERIES})
        result["formula"] = NPN_SIZE_FORMULA + "; " + result["formula"]
    sat = next(c for c in checks if c["id"] == "calc.npn.saturation")
    if forced_beta is None:
        tail = "the transistor stays off (no base current)"
        head = f"base {_f(i_rb, 'A')} from the pin"
    else:
        head = f"base {_f(i_b, 'A')} net, forced beta {_f(forced_beta, 'x', 2).removesuffix(' x')}"
        if sat["status"] == "not_checked":
            tail = ("saturation not checked (no hFE given)" if h_user is None and part_name is None
                    else f"saturation not checked ({sat['detail']})")
        elif hfe is not None:
            verdict = "saturates" if sat["status"] == "passed" else "may not saturate"
            origin = f"{hfe['part']} datasheet" if hfe["from"] == "datasheet" else "your value"
            tail = f"{verdict} by the hFE_min/2 rule of thumb (hFE_min {hfe['value']:g}, {origin})"
        else:  # pragma: no cover - a saturation verdict always has an hFE
            tail = sat["detail"]
    summary = f"NPN low side at {_f(vd, 'V')} drive: {head}; {tail}."
    if sizing is not None:
        summary = (f"NPN low side at {_f(vd, 'V')} drive: R_B {_f(rb, 'Ω')} ({NPN_SIZE_SERIES}, sized for forced beta "
                   f"{sizing['beta']:g}), {head}; {tail}.")
    return envelope("calc.npn", summary, result, checks=checks, warnings=warns, assumptions=assum,
                    sources=sources.resolve(source_ids))


def _npn_size(vd: float, il: float, vbe: float, rpd: float | None, fb_user: float | None) -> dict[str, Any]:
    """R_B for a target forced beta: I_B = I_load / β, R = (V_drive − V_BE) / (I_B + I_PD), next smaller E12 value
    (a smaller R_B drives the base harder, never weaker than the target)."""
    if vd <= vbe:
        raise BenchError("invalid_args", f"v_drive {_f(vd, 'V')} must be above v_be {_f(vbe, 'V')} to size r_base",
                         "give a higher drive voltage, or r_base to check a given resistor")
    beta = NPN_FORCED_BETA_DEFAULT if fb_user is None else fb_user
    i_b = il / beta
    i_pd = vbe / rpd if rpd is not None else 0.0
    ideal = (vd - vbe) / (i_b + i_pd)
    chosen = eseries.nearest(ideal, NPN_SIZE_SERIES, "down")
    pd = f" + {_f(i_pd, 'A')}" if rpd is not None else ""
    steps = [_step("I_B target", f"{_f(il, 'A')} / {beta:g}", i_b, "A"),
             _step("R_B ideal", f"({_f(vd, 'V')} − {_f(vbe, 'V')}) / ({_f(i_b, 'A')}{pd})", ideal, "Ω"),
             _step(f"R_B ({NPN_SIZE_SERIES})", f"next smaller {NPN_SIZE_SERIES} value of {_f(ideal, 'Ω')}", chosen, "Ω")]
    if fb_user is None:
        why = (f"I_C/I_B of the saturation test conditions in the 2N2222A datasheet ({NPN_FORCED_BETA_EVIDENCE[0]}: "
               "IC = 150 mAdc, IB = 15 mAdc); other transistors: check their datasheet, give forced_beta")
        ids = [NPN_FORCED_BETA_SOURCE, eseries.SOURCE_ID]
    else:
        why, ids = "given by you", [eseries.SOURCE_ID]
    assum = [assumption("forced_beta", f"{beta:g}", why),
             assumption("r_base", f"{NPN_SIZE_SERIES}, next smaller value", "no r_base given: R_B was sized; the "
                        "smaller standard value gives a little more base current than the target")]
    return {"beta": beta, "ideal": ideal, "chosen": chosen, "steps": steps, "assumptions": assum, "source_ids": ids}


# --- voltage divider ---------------------------------------------------------------------------------------------
ADC_RANGE_FORMAT = ('adc_range is the ADC input range in V for your attenuation, read from the chip datasheet (ADC '
                    'characteristics): [0, 2.9], {"min": 0, "max": 2.9}, "0-2.9V" or the max only, "2.9V"')
_ADC_ATTEN = re.compile(r"\bd\s*b\b|\d\s*db\b|atten", re.IGNORECASE)
_ADC_SPAN = re.compile(r"^\s*([0-9][0-9.,]*\s*[a-zµu]?v?)\s*(?:\.\.|-|–|—|\bto\b)\s*([0-9][0-9.,]*\s*[a-zµu]?v?)\s*$",
                       re.IGNORECASE)


def _adc_bad(message: str) -> BenchError:
    return BenchError("invalid_args", message, ADC_RANGE_FORMAT)


def _adc_range(adc_range: object) -> tuple[float, float]:
    """[min, max], {"min", "max"}, "0-2.9V" / "0..2.9 V" or a max only (V). An attenuation ("12dB", chip + atten) is
    refused with the format: the data has no sourced ADC range per attenuation, so it cannot be translated."""
    if isinstance(adc_range, dict):
        extra = set(adc_range) - {"min", "max"}
        if extra & {"chip", "atten", "attenuation", "db"}:
            raise _adc_bad("adc_range takes volts, not a chip or an attenuation (no sourced ADC range per "
                           "attenuation in the data)")
        if extra:
            raise _adc_bad(f"adc_range takes min and max in V, not {', '.join(sorted(map(str, extra)))}")
        if adc_range.get("max") is None:
            raise _adc_bad("adc_range needs max in V")
        lo, hi = adc_range.get("min", 0), adc_range.get("max")
    elif isinstance(adc_range, list | tuple):
        if len(adc_range) != 2:
            raise _adc_bad("adc_range needs two values [min, max] in V")
        lo, hi = adc_range
    elif isinstance(adc_range, str) and _ADC_ATTEN.search(adc_range):
        raise _adc_bad(f"adc_range {adc_range!r} looks like an attenuation; give the input range in V instead "
                       "(no sourced ADC range per attenuation in the data)")
    elif isinstance(adc_range, str) and (m := _ADC_SPAN.match(adc_range)):
        lo, hi = m.group(1), m.group(2)
        if hi.strip()[-1:].lower() == "v" and lo.strip()[-1:].lower() != "v":
            lo = f"{lo.strip()} V" if lo.strip()[-1:].isdigit() else f"{lo.strip()}V"
    else:
        lo, hi = 0, adc_range
    try:
        lo_v = _num(lo, "V", "adc_range min", allow_zero=True)
        hi_v = _num(hi, "V", "adc_range max")
    except _AboveLowVoltage:
        raise  # the low-voltage refusal keeps its own hint and the danger warning
    except BenchError as e:
        raise _adc_bad(e.message) from None
    if lo_v >= hi_v:
        raise _adc_bad(f"adc_range min {_f(lo_v, 'V')} must be below max {_f(hi_v, 'V')}")
    return lo_v, hi_v


@_action("calc.divider")
def divider(v_in_max: object, r1: object, r2: object, *, adc_range: object = None) -> dict[str, Any]:
    """Unloaded voltage divider R1 (top) / R2 (bottom): output, current, power, source impedance.

    ``adc_range`` ([min, max] in V, or max only) is compared, but stays ``not_checked``: there is no sourced ADC
    range in the data yet (ESP-IDF v6.1 ADC docs point to the chip datasheet), so the comparison is a hint only.
    """
    vin, ra, rb = _num(v_in_max, "V", "v_in_max"), _num(r1, "Ω", "r1"), _num(r2, "Ω", "r2")
    total = ra + rb
    ratio = rb / total
    vout = vin * ratio
    i = vin / total
    p1, p2 = i ** 2 * ra, i ** 2 * rb
    r_src = ra * rb / total
    inputs: dict[str, Any] = {"v_in_max": _q(vin, "V"), "r1": _q(ra, "Ω"), "r2": _q(rb, "Ω")}
    warns: list[dict[str, Any]] = []
    assum = [assumption("load", "none", "unloaded divider: the ADC input current is neglected; see r_source"),
             assumption("adc_pin", "add about 100 nF from the ADC pin to GND",
                        "steadies the reading with a high r_source (rule of thumb)")]
    adc: dict[str, Any] | None = None
    checks: list[dict[str, Any]] = []
    div_sources = [RULE]
    esp = _pin_values()
    limit = None if esp is None else esp.get("v_in_max")
    if isinstance(limit, int | float) and vout > limit + PIN_TOLERANCE:
        from .calc_power import S3_DEFAULT_NOTE
        checks.append(check("calc.divider.pin_max", "failed", f"V_out max {_f(vout, 'V')} > {_f(limit, 'V', 3)}"))
        warns.append(warning("divider_overvoltage", "danger",
                             f"V_out can reach {_f(vout, 'V')}. The ESP input limit is {_f(limit, 'V')} (VIH max, the "
                             "maximum high-level input voltage). If this node feeds a GPIO or ADC pin, raise R1 or "
                             "lower R2.",
                             list(esp.get("source_ids") or [])))
        assum.append(assumption("pin_limit", _f(limit, "V"), S3_DEFAULT_NOTE + f"maximum high-level input voltage (VIH max) {_f(limit, 'V')}"))
        div_sources += [s for s in esp.get("source_ids") or [] if s not in div_sources]
    if adc_range is None:
        chk = check("calc.divider.adc_range", "not_checked", "give adc_range ([min, max] in V, e.g. [0, 2.9]) to "
                    "compare with the ADC input range")
    else:
        lo, hi = _adc_range(adc_range)
        inputs["adc_range"] = {"min": _q(lo, "V"), "max": _q(hi, "V")}
        inside = lo <= vout <= hi
        adc = {"min": _q(lo, "V"), "max": _q(hi, "V"), "inside": inside, "headroom": _q(hi - vout, "V")}
        chk = check("calc.divider.adc_range", "not_checked",
                    f"V_out max {_f(vout, 'V')} is {'within' if inside else 'outside'} the range you gave "
                    f"({_f(lo, 'V')}–{_f(hi, 'V')}); no sourced ADC range, so not checked (unverified)")
        assum.append(assumption("adc_range", f"{_f(lo, 'V')}–{_f(hi, 'V')}",
                                "given by you; take it from the chip datasheet (ADC characteristics) for your attenuation"))
        if not inside:
            warns.append(warning("adc_out_of_given_range", "info",
                                 f"V_out max {_f(vout, 'V')} is outside the ADC range you gave ({_f(lo, 'V')}–"
                                 f"{_f(hi, 'V')}; unverified): {'raise R1 or lower R2' if vout > hi else 'lower R1'}."))
    result = {
        "inputs": inputs,
        "v_out_max": _q(vout, "V"),
        "ratio": _sig(ratio),
        "i_div": _q(i, "A"),
        "p_r1": _q(p1, "W"),
        "p_r2": _q(p2, "W"),
        "r_source": _q(r_src, "Ω"),
        "adc": adc,
        "formula": DIVIDER_FORMULA,
        "steps": [
            _step("V_out", f"{_f(vin, 'V')} · {_f(rb, 'Ω')} / ({_f(ra, 'Ω')} + {_f(rb, 'Ω')})", vout, "V"),
            _step("I", f"{_f(vin, 'V')} / {_f(total, 'Ω')}", i, "A"),
            _step("P_R1", f"({_f(i, 'A')})² · {_f(ra, 'Ω')}", p1, "W"),
            _step("P_R2", f"({_f(i, 'A')})² · {_f(rb, 'Ω')}", p2, "W"),
            _step("R_source", f"{_f(ra, 'Ω')} · {_f(rb, 'Ω')} / {_f(total, 'Ω')}", r_src, "Ω"),
        ],
    }
    summary = (f"Divider {_f(ra, 'Ω')} / {_f(rb, 'Ω')}: {_f(vin, 'V')} in gives {_f(vout, 'V')} out, "
               f"{_f(i, 'A')} through the divider.")
    return envelope("calc.divider", summary, result, checks=[*checks, chk], warnings=warns, assumptions=assum,
                    sources=sources.resolve(div_sources))


# --- I²C pull-up -------------------------------------------------------------------------------------------------
def _suggest(r_min: float, r_max: float) -> float | None:
    """E12 value inside [r_min, r_max] closest to the geometric middle (rule of thumb); ties go up."""
    if r_min > r_max:
        return None
    cands = eseries.values_between(r_min, r_max, "E12")
    if not cands:
        return None
    mid = math.sqrt(r_min * r_max)
    return min(cands, key=lambda c: (round(abs(math.log(c / mid)), 12), -c))


def _i2c_targets(project: object) -> tuple[int, list[str]]:
    """(I²C targets, their refs) of a stored project: every part whose catalog module has an i2c interface (× qty)."""
    from . import modules
    from . import project as P
    if not isinstance(project, str) or not project.strip():
        raise BenchError("invalid_args", f"project must be a project id, got {project!r}", "for example project=\"p1\"")
    env = P.get(project.strip())
    if not env.get("ok"):
        err = env.get("error") or {}
        raise BenchError(err.get("code") or "invalid_args", err.get("message") or f"cannot read project {project!r}",
                         err.get("hint") or "give c_bus or devices instead")
    n, refs = 0, []
    for part in env["result"]["project"].get("parts") or []:
        if not isinstance(part, Mapping) or not isinstance(part.get("module"), str):
            continue
        try:
            entry = modules.catalog().get(part["module"], part.get("variant") if isinstance(part.get("variant"), str)
                                          else None)
        except (BenchError, KeyError, ValueError):
            continue  # an unknown module cannot be counted; pins.check reports it
        if any(isinstance(it, Mapping) and it.get("type") == "i2c" for it in entry.get("interfaces") or []):
            qty = part.get("qty") if isinstance(part.get("qty"), int) and part["qty"] >= 1 else 1
            n += qty
            refs.append(str(part.get("ref")))
    return n, refs


def _c_bus_estimate(devices: object, project: object) -> tuple[float, list[dict[str, Any]], str]:
    """C_b per bus line without a measured value: (targets + the ESP) × C_i max (UM10204 Table 10) plus a wiring
    share (rule of thumb). Returns (C_b in F, assumptions, short basis text)."""
    if devices is not None:
        n = _count(devices, "devices")
        if n != int(n):
            raise BenchError("invalid_args", f"devices must be a whole number, got {n}", "for example devices=2")
        n, where = int(n), "devices (given by you)"
    elif project is not None:
        n, refs = _i2c_targets(project)
        where = (f"I²C modules of project {str(project).strip()}: {', '.join(refs)}" if refs else
                 f"project {str(project).strip()} has no I²C module; one target assumed")
        n = n or 1
    else:
        n, where = I2C_TARGETS_DEFAULT, "no c_bus, devices or project given; one target assumed"
    pins = n + 1  # the ESP32 is the controller on the same line
    cb = pins * I2C_C_PIN_MAX + I2C_C_WIRES_SHORT
    assum = [
        assumption("c_bus", f"{_f(cb, 'F')} estimated",
                   f"{pins} I/O pins ({n} target{'s' if n != 1 else ''} + the ESP32) × {_f(I2C_C_PIN_MAX, 'F', 2)} "
                   f"C_i max (UM10204 Table 10) + {_f(I2C_C_WIRES_SHORT, 'F', 2)} for short wires (rule of thumb, "
                   "not a datasheet value); breakout boards and long wires add more"),
        assumption("devices", str(n), where),
    ]
    return cb, assum, f"{pins} pins × {_f(I2C_C_PIN_MAX, 'F', 2)} + {_f(I2C_C_WIRES_SHORT, 'F', 2)} wires"


@_action("calc.i2c_pullup")
def i2c_pullup(v_dd: object, c_bus: object = None, *, mode: str = "standard", v_ol: object = I2C_V_OL,
               i_ol: object = I2C_I_OL, r_pullup: object = None, devices: object = None,
               project: object = None) -> dict[str, Any]:
    """Pull-up window for an I²C bus (NXP UM10204 §7.1): R_min from the sink current, R_max from the rise time.

    Without ``c_bus`` the bus capacitance is estimated: (``devices`` targets, else the I²C modules of ``project``,
    else one target) plus the ESP32, each at C_i max 10 pF (UM10204 Table 10), plus 50 pF for short wires (rule of
    thumb). The estimate is named in ``assumptions`` and an info warning ``c_bus_estimated``."""
    vdd = _num(v_dd, "V", "v_dd")
    est_assum: list[dict[str, Any]] = []
    est_text = ""
    if c_bus is None:
        cb, est_assum, est_text = _c_bus_estimate(devices, project)
    else:
        cb = _num(c_bus, "F", "c_bus")
    m = _choice(mode, tuple(I2C_MODES), "mode")
    vol, iol = _num(v_ol, "V", "v_ol"), _num(i_ol, "A", "i_ol")
    r_given = None if r_pullup is None else _num(r_pullup, "Ω", "r_pullup")
    if vol >= vdd:
        raise BenchError("invalid_args", f"v_ol {_f(vol, 'V')} must be below v_dd {_f(vdd, 'V')}",
                         "v_dd is the pull-up supply, v_ol the low level at the sink current (0.4 V by default)")
    spec = I2C_MODES[m]
    t_r = spec["t_r"]
    r_min = (vdd - vol) / iol
    r_max = t_r / (I2C_RC_FACTOR * cb)
    fits = r_min <= r_max
    inputs: dict[str, Any] = {"v_dd": _q(vdd, "V"), "c_bus": _q(cb, "F"), "mode": m, "v_ol": _q(vol, "V"),
                              "i_ol": _q(iol, "A")}
    if est_assum:
        inputs["c_bus"] = {**inputs["c_bus"], "estimated": True}
    if r_given is not None:
        inputs["r_pullup"] = _q(r_given, "Ω")
    checks = [check("calc.i2c.window", "passed" if fits else "failed",
                    f"R_min {_f(r_min, 'Ω')} {'≤' if fits else '>'} R_max {_f(r_max, 'Ω')}")]
    cb_ok = cb <= spec["c_b_max"]
    checks.append(check("calc.i2c.c_bus_max", "passed" if cb_ok else "failed",
                        f"C_b {_f(cb, 'F')} {'≤' if cb_ok else '>'} {_f(spec['c_b_max'], 'F')} ({spec['label']}, UM10204 Table 11)"))
    warns: list[dict[str, Any]] = []
    if est_assum:
        warns.append(warning("c_bus_estimated", "info",
                             f"c_bus estimated ({_f(cb, 'F')}: {est_text}); measure or give c_bus for long wires.",
                             [NXP, RULE]))
    if not fits:
        warns.append(warning("i2c_no_window", "caution",
                             "No pull-up meets both limits: lower the bus capacitance, use a slower mode or stronger drivers.",
                             [NXP]))
    if not cb_ok:
        warns.append(warning("i2c_c_bus_max", "caution",
                             f"The bus capacitance is above the {spec['label']} limit; split the bus or use a bus buffer.",
                             [NXP]))
    if vdd <= I2C_V_OL1_VDD_ABOVE:
        warns.append(warning("i2c_low_vdd", "caution",
                             "UM10204 gives V_OL 0.4 V at 3 mA only for V_DD > 2 V (Table 10); below that V_OL2 = 0.2·V_DD "
                             "at 2 mA applies. Give v_ol and i_ol for your parts.", [NXP]))
    if m == "fast":
        warns.append(warning("i2c_fast_iol", "info",
                             "UM10204 Table 10 note [4]: full bus load at 400 kHz needs 6 mA I_OL at 0.6 V V_OL; parts "
                             "below that still work, but not at 400 kHz and 400 pF.", [NXP]))
    assum = [
        assumption("v_ol", _f(vol, "V"), "UM10204 Table 10: V_OL1 max at 3 mA sink, V_DD > 2 V"
                   if math.isclose(vol, I2C_V_OL, rel_tol=1e-12) else "given by you"),
        assumption("i_ol", _f(iol, "A"), "UM10204 Table 10: minimum I_OL at V_OL 0.4 V (Standard-/Fast-mode)"
                   if math.isclose(iol, I2C_I_OL, rel_tol=1e-12) else "given by you"),
        assumption("t_r", _f(t_r, "s"), f"UM10204 Table 11: maximum rise time, {spec['label']}"),
    ]
    if est_assum:
        assum += est_assum
    else:
        assum.append(assumption("c_bus", _f(cb, "F"), "given by you: wires, connections and pins (UM10204 §7.1); up "
                                f"to {_f(I2C_C_PIN_MAX, 'F', 2)} per I/O pin (Table 10)"))
    source_ids = [NXP, RULE] if est_assum else [NXP]
    suggested = _suggest(r_min, r_max)
    result: dict[str, Any] = {
        "inputs": inputs,
        "r_min": _q(r_min, "Ω"),
        "r_max": _q(r_max, "Ω"),
        "t_r_max": _q(t_r, "s"),
        "suggested": None,
        "formula": I2C_FORMULA,
        "steps": [
            _step("R_min", f"({_f(vdd, 'V')} − {_f(vol, 'V')}) / {_f(iol, 'A')}", r_min, "Ω"),
            _step("R_max", f"{_f(t_r, 's')} / ({I2C_RC_FACTOR} · {_f(cb, 'F')})", r_max, "Ω"),
        ],
    }
    if suggested is not None:
        source_ids += [eseries.SOURCE_ID, RULE]
        t_rise = I2C_RC_FACTOR * suggested * cb
        result["suggested"] = _q(suggested, "Ω")
        result["suggested_t_r"] = _q(t_rise, "s")
        result["suggested_i_sink"] = _q((vdd - vol) / suggested, "A")
        result["steps"].append(_step("t_r", f"{I2C_RC_FACTOR} · {_f(suggested, 'Ω')} · {_f(cb, 'F')}", t_rise, "s"))
        assum.append(assumption("suggested", "E12 value nearest √(R_min · R_max)",
                                "rule of thumb: margin to both limits; UM10204 §7.1: low-power designs may go toward R_max"))
    if r_given is not None:
        inside = r_min <= r_given <= r_max
        checks.append(check("calc.i2c.r_pullup", "passed" if inside else "failed",
                            f"{_f(r_given, 'Ω')} {'within' if inside else 'outside'} {_f(r_min, 'Ω')}–{_f(r_max, 'Ω')}"))
        result["r_pullup_t_r"] = _q(I2C_RC_FACTOR * r_given * cb, "s")
    head = (f"I²C {spec['label'].removesuffix('-mode').lower()} mode at {_f(vdd, 'V')}, {_f(cb, 'F')}"
            f"{' (estimated)' if est_assum else ''}: ")
    if fits:
        text = f"pull-up between {_f(r_min, 'Ω')} and {_f(r_max, 'Ω')}"
        if suggested is not None:
            text += f"; {_f(suggested, 'Ω')} (E12) suggested"
    else:
        text = f"no pull-up fits (R_min {_f(r_min, 'Ω')} > R_max {_f(r_max, 'Ω')})"
    if r_given is not None:
        text += f"; {_f(r_given, 'Ω')} {'fits' if r_min <= r_given <= r_max else 'does not fit'}"
    return envelope("calc.i2c_pullup", head + text + ".", result, checks=checks, warnings=warns, assumptions=assum,
                    sources=sources.resolve(source_ids))


# --- registration (calckit) and the compatibility views for existing callers ------------------------------------
# name, unit ("V", "A", "Ω", "F", "" = plain number, "°C", "str", "range"), required, default
_PARAMS: dict[str, tuple[tuple[str, str, bool, Any], ...]] = {
    "led": (("v_supply", "V", True, None), ("v_f", "V", True, None), ("i_f", "A", True, None),
            ("series", "str", False, "E12")),
    "npn": (("v_drive", "V", True, None), ("r_base", "Ω", False, None), ("i_load", "A", True, None),
            ("v_be", "V", False, NPN_V_BE_DEFAULT), ("r_pulldown", "Ω", False, None), ("hfe_min", "", False, None),
            ("part", "str", False, None), ("load", "str", False, None), ("forced_beta", "", False, None)),
    "divider": (("v_in_max", "V", True, None), ("r1", "Ω", True, None), ("r2", "Ω", True, None),
                ("adc_range", "range", False, None)),
    "i2c_pullup": (("v_dd", "V", True, None), ("c_bus", "F", False, None), ("mode", "str", False, "standard"),
                   ("v_ol", "V", False, I2C_V_OL), ("i_ol", "A", False, I2C_I_OL), ("r_pullup", "Ω", False, None),
                   ("devices", "int", False, None), ("project", "str", False, None)),
}
calckit.register("led", led, _PARAMS["led"], title="LED series resistor", group="basics",
                 summary="Series resistor for an LED: exact and next E-series value, current and resistor power.")
calckit.register("npn", npn, _PARAMS["npn"], title="NPN low-side switch", group="basics",
                 summary="Base resistor of an NPN switch at a GPIO (sized when r_base is missing), saturation, power.")
calckit.register("divider", divider, _PARAMS["divider"], title="Voltage divider", group="basics",
                 summary="Unloaded divider R1/R2: V_out, current, power, source impedance; adc_range [min, max] in V, "
                         "e.g. [0, 2.9].")
calckit.register("i2c_pullup", i2c_pullup, _PARAMS["i2c_pullup"], title="I²C pull-up resistors", group="basics",
                 summary="Pull-up window of an I²C bus from sink current and rise time (NXP UM10204).")


class _View(Mapping[str, Any]):
    """Read-only dict view of the calculator register (calckit): kind -> one field of its entry, in kinds() order."""

    def __init__(self, field: str):
        self._field = field

    def __getitem__(self, kind: str) -> Any:
        if not isinstance(kind, str) or kind not in calckit.kinds():
            raise KeyError(kind)
        return calckit.REGISTRY[kind][self._field]

    def __iter__(self) -> Iterator[str]:
        return iter(calckit.kinds())

    def __len__(self) -> int:
        return len(calckit.kinds())

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._field!r}: {list(self)})"


CALCULATORS: Mapping[str, Callable[..., dict[str, Any]]] = _View("fn")  # derived from calckit (no literal list)
PARAMS: Mapping[str, tuple[tuple[str, str, bool, Any], ...]] = _View("params")


def run(kind: str, params: object) -> dict[str, Any]:
    """Run calculator ``kind`` with a parameter dict (same as ``calckit.run``; kept for existing callers)."""
    return calckit.run(kind, params)


from . import calc_power  # noqa: E402, F401  (registers mosfet and ldo)
