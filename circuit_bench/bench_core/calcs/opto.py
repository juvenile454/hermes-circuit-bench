"""Calculator ``opto``: LED series resistor and output pull-up of an
optocoupler driven from a logic pin. Parts: Sharp PC817 (phototransistor) and Vishay 6N137 (10 MBd, open drain).

Data (PDF page index; quoted in ``FACTS``, excerpts tests/corpus/excerpts/mod-switch-pc817.txt and -6n137.txt):
- PC817 (Sharp OP18002EN): VF 1.2 V typ / 1.4 V max at IF = 20 mA, IF ≤ 50 mA (abs. max), CTR ≥ 50 % = IC ≥ 2.5 mA at
  IF = 5 mA, VCE = 5 V (p. 1, p. 4), VCE(sat) ≤ 0.2 V at IF = 20 mA, IC = 1 mA, VCEO 80 V (p. 4).
- 6N137 (Vishay 84732 Rev. 2.2): VCC 4.5–5.5 V, IFH 5–15 mA, RL 330 Ω–4 kΩ (recommended, p. 3), VF 1.1/1.4/1.7 V at
  IF = 10 mA, ITH ≤ 5 mA, VOL ≤ 0.6 V at IOL = 13 mA (p. 4), IF ≤ 20 mA, VCC ≤ 7 V (abs. max, p. 2).

Method (deterministic, SI units, nothing interpolated):
- R_LED = (V_drive − VF_max) / I_F, rounded DOWN to the E-series: with VF ≤ VF_max the LED gets at least I_F. The
  highest current uses VF_typ (PC817: no VF min) or VF_min (6N137). Both VF values are specified at one current only
  (PC817 20 mA, 6N137 10 mA); the result says so.
- PC817 output: V_pullup must be above VCE(sat) (else ``invalid_args``). The low level holds while the pull-up
  current (V_pullup − VCE(sat)) / R_pu ≤ I_C,min. I_C,min is only guaranteed at IF = 5 mA (2.5 mA); at another I_F the
  transfer check is not a datasheet guarantee (info). The suggested R_pu takes half of I_C,min (factor 2 = rule of
  thumb for CTR ageing and temperature), next E value up. The output swings to V_pullup.
- 6N137 output: RL in 330 Ω–4 kΩ and (V_CC − VOL) / RL ≤ 13 mA (the VOL test current). Suggested RL = smallest E
  value ≥ max(330 Ω, (V_CC − 0.6 V) / 13 mA). The output swings to V_CC.
- Both outputs: a high level above the ESP input maximum (``chip``, data/electrical) is ``opto_output_level``
  danger and needs a level shifter; without ``chip`` the same code is an info hint.
"""
from __future__ import annotations

from typing import Any

from .. import calckit as ck
from .. import electrical

ACTION = "calc.opto"
PC_SRC = "mod-switch-pc817-ds"
ON_SRC = "mod-switch-6n137-ds"
PARTS = ("pc817", "6n137")


def _f(value: float, unit: str, page: int, evidence: Any, src: str, conditions: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "page": page, "evidence": evidence, "source_id": src, "conditions": conditions}


FACTS: dict[str, dict[str, dict[str, Any]]] = {
    "pc817": {
        "vf_typ": _f(1.2, "V", 4, ["Forward voltage VF IF", "20mA", "1.2 1.4 V"], PC_SRC, "typ at IF = 20 mA, Ta = 25 °C"),
        "vf_max": _f(1.4, "V", 4, ["Forward voltage VF IF", "20mA", "1.2 1.4 V"], PC_SRC, "max at IF = 20 mA, Ta = 25 °C"),
        "if_abs_max": _f(0.05, "A", 4, "Forward current IF 50 mA", PC_SRC, "absolute maximum, Ta = 25 °C"),
        "if_ctr": _f(0.005, "A", 1, "CTR is 50% to 400% (at IF=5mA,VCE=5V,Ta=25", PC_SRC, "CTR test current"),
        "ctr_min": _f(50.0, "%", 1, "CTR is 50% to 400% (at IF=5mA,VCE=5V,Ta=25", PC_SRC, "at IF = 5 mA, VCE = 5 V, Ta = 25 °C"),
        "ic_min": _f(0.0025, "A", 4, ["Collector current IC IF", "5mA, VCE", "5V 2.5", "30 mA"], PC_SRC,
                     "min at IF = 5 mA, VCE = 5 V, Ta = 25 °C"),
        "vce_sat": _f(0.2, "V", 4, ["Collector-emitter saturation voltage VCE(sat) IF", "20mA, IC", "1mA", "0.1 0.2 V"], PC_SRC,
                      "max at IF = 20 mA, IC = 1 mA"),
        "vceo": _f(80.0, "V", 4, "Collector-emitter voltage VCEO 80 V", PC_SRC, "absolute maximum"),
    },
    "6n137": {
        "vf_min": _f(1.1, "V", 4, "Input forward voltage I F = 10 mA V F 1.1 1.4 1.7 V", ON_SRC, "min at IF = 10 mA"),
        "vf_typ": _f(1.4, "V", 4, "Input forward voltage I F = 10 mA V F 1.1 1.4 1.7 V", ON_SRC, "typ at IF = 10 mA"),
        "vf_max": _f(1.7, "V", 4, "Input forward voltage I F = 10 mA V F 1.1 1.4 1.7 V", ON_SRC, "max at IF = 10 mA"),
        "ifh_min": _f(0.005, "A", 3, "Input current  high level I FH 51 5 m A", ON_SRC,
                      "recommended IFH min (text layer '51 5 m A' = 5 / 15 mA)"),
        "ifh_max": _f(0.015, "A", 3, "Input current  high level I FH 51 5 m A", ON_SRC,
                      "recommended IFH max (text layer '51 5 m A' = 5 / 15 mA)"),
        "if_test": _f(0.0075, "A", 4, "VCC = 5 V, IF = 7.5 mA unless otherwise specified", ON_SRC,
                      "test current of the electrical characteristics"),
        "ith_max": _f(0.005, "A", 4, "Input threshold current VE = 2 V, VCC = 5.5 V,IOL (sinking) = 13 mA ITH -2 . 45m A", ON_SRC,
                      "max (text layer '2 . 45m A' = 2.4 typ, 5 max)"),
        "if_abs_max": _f(0.02, "A", 2, "Average forward current (single channel) I F 20 mA", ON_SRC, "absolute maximum, average"),
        "vcc_min": _f(4.5, "V", 3, "Supply voltage V CC 4.5 5.5 V", ON_SRC, "recommended operating conditions"),
        "vcc_max": _f(5.5, "V", 3, "Supply voltage V CC 4.5 5.5 V", ON_SRC, "recommended operating conditions"),
        "vcc_abs_max": _f(7.0, "V", 2, "Supply voltage 1 min maximum V CC 7V", ON_SRC, "absolute maximum, 1 min"),
        "rl_min": _f(330.0, "Ω", 3, "Output pull up resistor R L 330 4K", ON_SRC, "recommended operating conditions"),
        "rl_max": _f(4000.0, "Ω", 3, "Output pull up resistor R L 330 4K", ON_SRC, "recommended operating conditions"),
        "vol_max": _f(0.6, "V", 4, "Low level output voltage VE = 2 V, IF = 5 mA,IOL (sinking) = 13 mA VOL -0 . 2 0 . 6V", ON_SRC,
                      "max at IF = 5 mA, IOL = 13 mA (text layer '0 . 6V')"),
        "iol_test": _f(0.013, "A", 4, "Low level output voltage VE = 2 V, IF = 5 mA,IOL (sinking) = 13 mA VOL -0 . 2 0 . 6V",
                       ON_SRC, "sink current of the VOL test"),
    },
}
PC_PULLUP_MARGIN = 2.0  # rule of thumb: pull-up current ≤ I_C,min / 2 (CTR ageing and temperature)
FORMULA = {
    "pc817": "R_LED = (V_drive − VF_max)/I_F (E down); I_pu = (V_pullup − VCE(sat))/R_pu ≤ I_C,min (= CTR_min·I_F at 5 mA)",
    "6n137": "R_LED = (V_drive − VF_max)/I_F (E down); 330 Ω ≤ RL ≤ 4 kΩ; (V_CC − VOL)/RL ≤ 13 mA",
}


def _v(part: str, key: str) -> float:
    return float(FACTS[part][key]["value"])


def _src(part: str) -> str:
    return PC_SRC if part == "pc817" else ON_SRC


def _esp(chip: object) -> dict[str, Any] | None:
    if chip is None:
        return None
    if not isinstance(chip, str) or not chip.strip():
        raise ck.BenchError("invalid_args", f"chip must be a chip id, got {chip!r}", "for example chip='esp32s3'")
    values = electrical.get(chip.strip().lower())
    if not values:
        raise ck.BenchError("invalid_args", f"no electrical data for chip {chip!r}", "for example chip='esp32s3'")
    return values


def _led(part: str, vd: float, i_f: float, ser: str, r_user: float | None, steps: list, checks: list, warns: list,
         esp: dict[str, Any] | None) -> dict[str, Any] | None:
    """Series resistor; returns the LED result or None (no headroom, a failed check is added)."""
    src = _src(part)
    vf_max = _v(part, "vf_max")
    vf_lo = _v(part, "vf_min") if "vf_min" in FACTS[part] else _v(part, "vf_typ")
    lo_name = "VF_min" if "vf_min" in FACTS[part] else "VF_typ"
    if vd <= vf_max:
        checks.append(ck.check(f"{ACTION}.headroom", "failed",
                               f"V_drive {ck.fmt(vd, 'V')} ≤ VF_max {ck.fmt(vf_max, 'V')}"))
        warns.append(ck.warning("opto_no_headroom", "caution",
                                f"{ck.fmt(vd, 'V')} does not reliably light the {part.upper()} LED (VF up to "
                                f"{ck.fmt(vf_max, 'V')}). Drive it from a higher voltage or with a transistor.", [src]))
        return None
    checks.append(ck.check(f"{ACTION}.headroom", "passed", f"V_drive {ck.fmt(vd, 'V')} > VF_max {ck.fmt(vf_max, 'V')}"))
    r_exact = (vd - vf_max) / i_f
    if r_user is None:
        r = ck.eseries.nearest(r_exact, ser, "down")
        steps.append(ck.step("R_LED", f"({ck.fmt(vd, 'V')} − {ck.fmt(vf_max, 'V')}) / {ck.fmt(i_f, 'A')}", r_exact, "Ω"))
        steps.append(ck.step("R_LED_chosen", f"next {ser} value ≤ {ck.fmt(r_exact, 'Ω')}", r, "Ω"))
    else:
        r = r_user
    i_min = (vd - vf_max) / r
    i_hi = (vd - vf_lo) / r
    steps.append(ck.step("I_F_min", f"({ck.fmt(vd, 'V')} − {ck.fmt(vf_max, 'V')}) / {ck.fmt(r, 'Ω')}", i_min, "A"))
    steps.append(ck.step("I_F_high", f"({ck.fmt(vd, 'V')} − {ck.fmt(vf_lo, 'V')}) / {ck.fmt(r, 'Ω')} ({lo_name})",
                         i_hi, "A"))
    abs_max = _v(part, "if_abs_max")
    ok = i_hi <= abs_max
    checks.append(ck.check(f"{ACTION}.if_abs_max", "passed" if ok else "failed",
                           f"I_F up to {ck.fmt(i_hi, 'A')} {'≤' if ok else '>'} {ck.fmt(abs_max, 'A')} "
                           f"(absolute maximum, {part.upper()} datasheet)"))
    if not ok:
        warns.append(ck.warning("opto_if_over_abs_max", "danger",
                                f"The LED current reaches {ck.fmt(i_hi, 'A')}, above the absolute maximum "
                                f"{ck.fmt(abs_max, 'A')}: use a larger series resistor.", [src]))
    if esp and isinstance(esp.get("ioh"), int | float) and vd <= float(esp.get("vdd") or 3.3) + 1e-9 and i_hi > esp["ioh"]:
        warns.append(ck.warning("gpio_current", "caution",
                                f"A GPIO driving the LED sources up to {ck.fmt(i_hi, 'A')}, more than the typical "
                                f"{ck.fmt(esp['ioh'], 'A')} IOH of {esp.get('chip', 'the chip')} (a typical value, "
                                "not a limit): use a transistor or a larger resistor.", list(esp.get("source_ids") or [])))
    return {"r_exact": ck.q(r_exact, "Ω"), "r_led": ck.q(r, "Ω"), "r_from": "user" if r_user is not None else ser,
            "i_f_min": ck.q(i_min, "A"), "i_f_high": ck.q(i_hi, "A"), "_i_min": i_min, "_i_hi": i_hi}


def _output_level(part: str, v_high: float, rail: str, esp: dict[str, Any] | None, warns: list) -> None:
    """The output high level (``rail`` = V_CC or V_pullup) against the ESP input maximum ``v_in_max``."""
    limit = esp.get("v_in_max") if esp is not None else None
    if esp is not None and isinstance(limit, int | float) and v_high > limit + 1e-9:
        warns.append(ck.warning("opto_output_level", "danger",
                                f"The {part.upper()} output rises to {rail} {ck.fmt(v_high, 'V')}, above the "
                                f"{esp.get('chip')} input maximum {ck.fmt(limit, 'V')}: add a level shifter or a "
                                "divider before the GPIO.", list(esp.get("source_ids") or []) + [_src(part)]))
    elif limit is None:
        warns.append(ck.warning("opto_output_level", "info",
                                f"The output rises to {rail} {ck.fmt(v_high, 'V')}; give chip=… to check it against the "
                                "ESP input maximum.", [_src(part)]))


def _pc817_out(vp: float, i_f_min: float, ser: str, r_user: float | None, steps: list, checks: list, warns: list,
               assum: list, esp: dict[str, Any] | None) -> dict[str, Any]:
    vsat, ic_min, if_ctr = _v("pc817", "vce_sat"), _v("pc817", "ic_min"), _v("pc817", "if_ctr")
    at_test = abs(i_f_min - if_ctr) <= 0.05 * if_ctr or i_f_min >= if_ctr
    if vp > _v("pc817", "vceo"):  # cannot happen below 60 V; kept for clarity
        raise ck.BenchError("invalid_args", "v_pullup above VCEO", "keep the output side at low voltage")
    if vp <= vsat + 1e-12:
        raise ck.BenchError("invalid_args", f"v_pullup {vp:g} V must be above the PC817 VCE(sat) {vsat:g} V",
                            f"give v_pullup above {vsat:g} V, e.g. 3.3 V")
    if r_user is None:
        r_min = (vp - vsat) / (ic_min / PC_PULLUP_MARGIN)
        r = ck.eseries.nearest(r_min, ser, "up")
        steps.append(ck.step("R_pu", f"({ck.fmt(vp, 'V')} − {ck.fmt(vsat, 'V')}) / ({ck.fmt(ic_min, 'A')} / "
                                     f"{PC_PULLUP_MARGIN:g}) (rule of thumb)", r_min, "Ω"))
        steps.append(ck.step("R_pu_chosen", f"next {ser} value ≥ {ck.fmt(r_min, 'Ω')}", r, "Ω"))
    else:
        r = r_user
    i_pu = (vp - vsat) / r
    steps.append(ck.step("I_pu", f"({ck.fmt(vp, 'V')} − {ck.fmt(vsat, 'V')}) / {ck.fmt(r, 'Ω')}", i_pu, "A"))
    ok = i_pu <= ic_min
    if at_test:
        status = "passed" if ok else "failed"
        detail = (f"I_pu {ck.fmt(i_pu, 'A')} {'≤' if ok else '>'} I_C,min {ck.fmt(ic_min, 'A')} "
                  f"(CTR ≥ 50 % at IF = 5 mA; I_F ≥ {ck.fmt(i_f_min, 'A')})")
    else:
        status = "not_checked"
        detail = (f"I_F,min {ck.fmt(i_f_min, 'A')} is below the CTR test current 5 mA: no guaranteed I_C "
                  f"(I_pu {ck.fmt(i_pu, 'A')})")
        warns.append(ck.warning("opto_ctr_not_guaranteed", "info",
                                "The PC817 transfer ratio is guaranteed only at IF = 5 mA; at less current the "
                                "output may not pull low. Give i_f ≥ 5 mA.", [PC_SRC]))
    checks.append(ck.check(f"{ACTION}.output_low", status, detail))
    if at_test and not ok:
        warns.append(ck.warning("opto_output_not_low", "caution",
                                f"The pull-up draws {ck.fmt(i_pu, 'A')}, more than the guaranteed "
                                f"{ck.fmt(ic_min, 'A')} collector current: the output may not reach a low level. "
                                "Use a larger pull-up.", [PC_SRC]))
    warns.append(ck.warning("opto_slow", "info",
                            "PC817 rise/fall times are up to 18 µs at RL = 100 Ω and grow with the pull-up: use it for "
                            "slow signals (buttons, mains-free status lines), not for UART or PWM.", [PC_SRC]))
    _output_level("pc817", vp, "V_pullup", esp, warns)
    if at_test:
        assum.append(ck.assumption("ctr", "I_C,min 2.5 mA for I_F ≥ 5 mA", "CTR_min is tested at IF = 5 mA only; the "
                                   "collector current rises with I_F (typical curve, Fig. 7), so more I_F keeps it"))
    assum.append(ck.assumption("vce_sat", "0.2 V", "VCE(sat) max at IF = 20 mA, IC = 1 mA (the only test point)"))
    assum.append(ck.assumption("pullup_margin", "I_C,min / 2", "half the guaranteed collector current (rule of thumb)"))
    return {"r_pullup": ck.q(r, "Ω"), "r_pullup_from": "user" if r_user is not None else ser, "i_pullup": ck.q(i_pu, "A"),
            "i_c_min": ck.q(ic_min, "A"), "v_out_high": ck.q(vp, "V")}


def _6n137_out(vcc: float, i_f_min: float, i_hi: float, ser: str, r_user: float | None, steps: list, checks: list,
               warns: list, esp: dict[str, Any] | None) -> dict[str, Any]:
    vcc_min, vcc_max, vcc_abs = _v("6n137", "vcc_min"), _v("6n137", "vcc_max"), _v("6n137", "vcc_abs_max")
    if vcc > vcc_abs:
        checks.append(ck.check(f"{ACTION}.vcc", "failed", f"V_CC {ck.fmt(vcc, 'V')} > {ck.fmt(vcc_abs, 'V')} (absolute maximum)"))
        warns.append(ck.warning("opto_vcc_over_abs_max", "danger",
                                f"V_CC {ck.fmt(vcc, 'V')} is above the 6N137 absolute maximum {ck.fmt(vcc_abs, 'V')}.",
                                [ON_SRC]))
    elif not vcc_min <= vcc <= vcc_max:
        checks.append(ck.check(f"{ACTION}.vcc", "failed",
                               f"V_CC {ck.fmt(vcc, 'V')} outside {ck.fmt(vcc_min, 'V')}–{ck.fmt(vcc_max, 'V')} (recommended)"))
        warns.append(ck.warning("opto_vcc_range", "caution",
                                f"The 6N137 is specified for V_CC {ck.fmt(vcc_min, 'V')}–{ck.fmt(vcc_max, 'V')} only; "
                                f"at {ck.fmt(vcc, 'V')} its timing and output are not guaranteed.", [ON_SRC]))
    else:
        checks.append(ck.check(f"{ACTION}.vcc", "passed",
                               f"V_CC {ck.fmt(vcc, 'V')} in {ck.fmt(vcc_min, 'V')}–{ck.fmt(vcc_max, 'V')}"))
    lo, hi = _v("6n137", "ifh_min"), _v("6n137", "ifh_max")
    ok = i_f_min >= lo - 1e-12 and i_hi <= hi + 1e-12
    checks.append(ck.check(f"{ACTION}.ifh", "passed" if ok else "failed",
                           f"I_F {ck.fmt(i_f_min, 'A')}–{ck.fmt(i_hi, 'A')} {'in' if ok else 'outside'} IFH "
                           f"{ck.fmt(lo, 'A')}–{ck.fmt(hi, 'A')} (recommended)"))
    if not ok:
        warns.append(ck.warning("opto_ifh_range", "caution",
                                f"The LED current {ck.fmt(i_f_min, 'A')}–{ck.fmt(i_hi, 'A')} leaves the recommended "
                                f"input range {ck.fmt(lo, 'A')}–{ck.fmt(hi, 'A')}.", [ON_SRC]))
    rl_min, rl_max = _v("6n137", "rl_min"), _v("6n137", "rl_max")
    vol, iol = _v("6n137", "vol_max"), _v("6n137", "iol_test")
    if r_user is None:
        need = max(rl_min, (vcc - vol) / iol)
        r = ck.eseries.nearest(need, ser, "up")
        steps.append(ck.step("RL_min", f"max({ck.fmt(rl_min, 'Ω')}, ({ck.fmt(vcc, 'V')} − {ck.fmt(vol, 'V')}) / "
                                       f"{ck.fmt(iol, 'A')})", need, "Ω"))
        steps.append(ck.step("RL_chosen", f"next {ser} value ≥ {ck.fmt(need, 'Ω')}", r, "Ω"))
    else:
        r = r_user
    i_sink = (vcc - vol) / r
    steps.append(ck.step("I_sink", f"({ck.fmt(vcc, 'V')} − {ck.fmt(vol, 'V')}) / {ck.fmt(r, 'Ω')}", i_sink, "A"))
    ok_rl = rl_min - 1e-9 <= r <= rl_max + 1e-9
    checks.append(ck.check(f"{ACTION}.rl_range", "passed" if ok_rl else "failed",
                           f"RL {ck.fmt(r, 'Ω')} {'in' if ok_rl else 'outside'} {ck.fmt(rl_min, 'Ω')}–{ck.fmt(rl_max, 'Ω')}"))
    if not ok_rl:
        warns.append(ck.warning("opto_rl_range", "caution",
                                f"RL {ck.fmt(r, 'Ω')} is outside the recommended {ck.fmt(rl_min, 'Ω')}–"
                                f"{ck.fmt(rl_max, 'Ω')} of the 6N137.", [ON_SRC]))
    ok_vol = i_sink <= iol + 1e-12
    checks.append(ck.check(f"{ACTION}.output_low", "passed" if ok_vol else "failed",
                           f"I_sink {ck.fmt(i_sink, 'A')} {'≤' if ok_vol else '>'} {ck.fmt(iol, 'A')} "
                           f"(VOL ≤ {ck.fmt(vol, 'V')} test current)"))
    _output_level("6n137", vcc, "V_CC", esp, warns)
    return {"r_pullup": ck.q(r, "Ω"), "r_pullup_from": "user" if r_user is not None else ser,
            "i_sink": ck.q(i_sink, "A"), "v_out_high": ck.q(vcc, "V")}


@ck.action(ACTION)
def opto(part: object, v_drive: object, *, v_pullup: object = None, i_f: object = None, r_led: object = None,
         r_pullup: object = None, series: object = "E12", chip: object = None) -> dict[str, Any]:
    """PC817 / 6N137 driven from ``v_drive`` through R_LED; output pulled up to ``v_pullup`` (6N137: V_CC)."""
    p = ck.choice(part, PARTS, "part")
    vd = ck.num(v_drive, "V", "v_drive")
    default_vp = 3.3 if p == "pc817" else 5.0
    vp = ck.num(default_vp if v_pullup is None else v_pullup, "V", "v_pullup")
    default_if = _v(p, "if_ctr") if p == "pc817" else _v(p, "if_test")
    i_f_target = ck.num(default_if if i_f is None else i_f, "A", "i_f")
    r_l = None if r_led is None else ck.num(r_led, "Ω", "r_led")
    r_p = None if r_pullup is None else ck.num(r_pullup, "Ω", "r_pullup")
    ser = ck.series(series)
    esp = _esp(chip)
    src = _src(p)
    inputs = {"part": p, "v_drive": ck.q(vd, "V"), "v_pullup": ck.q(vp, "V"), "i_f": ck.q(i_f_target, "A"),
              "series": ser}
    steps: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    assum = [ck.assumption("vf", f"VF at {'20' if p == 'pc817' else '10'} mA",
                           "the datasheet gives VF at one current only; at a lower current VF is lower, so I_F is "
                           "at least the minimum shown"),
             ck.assumption("r_led", "next lower E value", "keeps I_F at or above the target")]
    facts = {k: dict(v) for k, v in FACTS[p].items()}
    vf_at = 0.02 if p == "pc817" else 0.01  # A: the one current VF is specified at (PC817 p. 4, 6N137 p. 4)
    if i_f_target > vf_at + 1e-12:
        warns.append(ck.warning("opto_vf_above_test", "info",
                                f"I_F {ck.fmt(i_f_target, 'A')} is above the VF test current {ck.fmt(vf_at, 'A')}: VF "
                                "may exceed VF_max here, so the LED current can be a little lower than shown.", [src]))
    led = _led(p, vd, i_f_target, ser, r_l, steps, checks, warns, esp)
    result: dict[str, Any] = {"inputs": inputs, "formula": FORMULA[p], "facts": facts}
    if led is None:
        result.update({"steps": steps, "r_led": None, "r_pullup": None})
        return ck.envelope(ACTION, f"{p.upper()} at {ck.fmt(vd, 'V')}: no headroom for the LED.", result,
                           checks=checks, warnings=warns, assumptions=assum, sources=ck.sources.resolve([src]))
    i_min, i_hi = led.pop("_i_min"), led.pop("_i_hi")
    result.update(led)
    if p == "pc817":
        out = _pc817_out(vp, i_min, ser, r_p, steps, checks, warns, assum, esp)
        summary = (f"PC817 from {ck.fmt(vd, 'V')}: R_LED {ck.fmt(out_r(led), 'Ω')} (I_F ≥ {ck.fmt(i_min, 'A')}), "
                   f"pull-up {out['r_pullup']['display']} to {ck.fmt(vp, 'V')}.")
    else:
        out = _6n137_out(vp, i_min, i_hi, ser, r_p, steps, checks, warns, esp)
        summary = (f"6N137 from {ck.fmt(vd, 'V')}: R_LED {ck.fmt(out_r(led), 'Ω')} (I_F {ck.fmt(i_min, 'A')}–"
                   f"{ck.fmt(i_hi, 'A')}), RL {out['r_pullup']['display']} to V_CC {ck.fmt(vp, 'V')}.")
    result.update(out)
    result["steps"] = steps
    ids = [src, ck.eseries.SOURCE_ID] + ([ck.RULE] if p == "pc817" else [])
    ids += [s for s in (esp or {}).get("source_ids") or [] if s not in ids]
    return ck.envelope(ACTION, summary, result, checks=checks, warnings=warns, assumptions=assum,
                       sources=ck.sources.resolve(ids))


def out_r(led: dict[str, Any]) -> float:
    return float(led["r_led"]["value"])


ck.register(
    "opto", opto,
    (("part", "str", True, None), ("v_drive", "V", True, None), ("v_pullup", "V", False, None),
     ("i_f", "A", False, None), ("r_led", "Ω", False, None), ("r_pullup", "Ω", False, None),
     ("series", "str", False, "E12"), ("chip", "str", False, None)),
    title="Optocoupler LED and pull-up resistors", group="drive",
    summary="PC817/6N137: LED series resistor from VF and I_F, CTR-checked or datasheet-range output pull-up.")
