"""Family rules ``nmeasure``: analog inputs of MCP3208, ADS1220, MAX31856.

- ``mod.nmeasure.ain_range``: an analog input of one of these parts on a net with a known voltage (rails,
  ``options.rails``). Above the absolute maximum -> ``danger``; outside the measuring / common-mode range -> ``caution``.
  - MCP3208 CH0–CH7: absolute maximum VDD + 0.6 V; single-ended range VSS…VREF (DS21298E p. 2).
  - ADS1220 AIN0–AIN3: absolute maximum AVDD + 0.3 V (SBAS501D p. 5); absolute input range up to AVDD + 0.1 V with
    the PGA disabled (gain 1–4, the widest case; p. 6). With the PGA enabled the range is narrower: not claimed here.
  - MAX31856 T+/T-: absolute maximum ±45 V (19-7534 p. 2); input common-mode range 0.5–1.4 V (p. 3). A thermocouple
    lead on GND or a supply rail is outside that range (T- is biased to 0.735 V internally, p. 11).
- Only nets with a known voltage count; a sensor signal net has no voltage in the project, so nothing is claimed for
  it. The supply ranges themselves (MAX31856 3.0–3.6 V, …) are the generic ``mod.supply_range``.

Every limit below carries source, page and the verbatim excerpt line(s) (tests/test_mod_nmeasure.py checks them
against tests/corpus/excerpts/mod-nmeasure-*.txt).
"""
from __future__ import annotations

from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = (
    modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule)

RULE = "mod.nmeasure.ain_range"
_EPS = 1e-9

# module id -> limits. abs: (supply pin, offset V) relative to a supply, or abs_fixed: |V| limit; op: (pin, offset V)
# = top of the measuring range, or op_range: (low V, high V). *_ev: (source id, page, [excerpt line parts]).
LIMITS: dict[str, dict[str, Any]] = {
    "mcp3208": {
        "pins": tuple(f"CH{i}" for i in range(8)),
        "abs": ("VDD", 0.6), "op": ("VREF", 0.0),
        "abs_ev": ("mod-nmeasure-mcp3208-ds", 2,
                   ["All inputs and outputs w.r.t. VSS ............... -0.6V to VDD +0.6V"]),
        "op_ev": ("mod-nmeasure-mcp3208-ds", 2, ["Input Voltage Range for CH0-", "VSS —V REF V"]),
    },
    "ads1220": {
        "pins": ("AIN0/REFP1", "AIN1", "AIN2", "AIN3/REFN1"),
        "abs": ("AVDD", 0.3), "op": ("AVDD", 0.1),
        "abs_ev": ("mod-nmeasure-ads1220-ds", 5,
                   ["Analog input voltage AIN0/REFP1, AIN1, AIN2, AIN3/REFN1, REFP0, REFN0 AVSS – 0.3 AVDD + 0.3 V"]),
        "op_ev": ("mod-nmeasure-ads1220-ds", 6,
                  ["VAINx Absolute input voltage", "PGA disabled, gain = 1 to 4 AVSS – 0.1 AVDD + 0.1 V"]),
    },
    "max31856": {
        "pins": ("T+", "T-"),
        "abs_fixed": 45.0, "op_range": (0.5, 1.4),
        "abs_ev": ("mod-nmeasure-max31856-ds", 2,
                   ["T+, T-, Bias ..........................................................................±45V"]),
        "op_ev": ("mod-nmeasure-max31856-ds", 3, ["Input Common-Mode Range 0.5 1.4 V"]),
        "hint": " Leave the thermocouple floating: T- is biased to 0.735 V internally (datasheet p. 11).",
    },
}


def _abs_limit(ctx: Ctx, inst: Instance, lim: dict[str, Any]) -> tuple[float | None, str]:
    if "abs_fixed" in lim:
        return float(lim["abs_fixed"]), f"±{fmt(lim['abs_fixed'], 'V')}"
    sup, off = lim["abs"]
    v = ctx.volts(ctx.net_of(inst, sup))
    if v is None:
        return None, sup
    return v + off, f"{sup} + {fmt(off, 'V')} = {fmt(v + off, 'V')}"


def _op_range(ctx: Ctx, inst: Instance, lim: dict[str, Any]) -> tuple[float, float, str] | None:
    if "op_range" in lim:
        lo, hi = lim["op_range"]
        return lo, hi, f"common-mode range {fmt(lo, 'V')}…{fmt(hi, 'V')}"
    pin, off = lim["op"]
    v = ctx.volts(ctx.net_of(inst, pin))
    if v is None:
        return None
    top = v + off
    label = f"≤ {pin} = {fmt(top, 'V')}" if not off else f"≤ {pin} + {fmt(off, 'V')} = {fmt(top, 'V')}"
    return 0.0, top, f"input range ({label})"


@rule(RULE)
def ain_range(ctx: Ctx) -> list[Finding]:
    """MCP3208 / ADS1220 / MAX31856 analog inputs on a known rail: absolute maximum (danger), range (caution)."""
    out: list[Finding] = []
    for inst in ctx.instances:
        lim = LIMITS.get(inst.module_id)
        if lim is None:
            continue
        live = [(pin, net, ctx.volts(net)) for pin in lim["pins"] if (net := ctx.net_of(inst, pin)) is not None]
        live = [(pin, net, v) for pin, net, v in live if v is not None]
        if not live:
            continue  # no analog input on a net with a known voltage: nothing to claim
        v_abs, abs_label = _abs_limit(ctx, inst, lim)
        if v_abs is None:
            out.append(Finding(RULE, "not_checked", "info",
                               f"{ctx.label(inst)}: {abs_label} voltage unknown, analog inputs on known rails not "
                               "checked.", [inst.ref]))
            continue
        rng = _op_range(ctx, inst, lim)
        bad = False
        for pin, net, v in live:
            if abs(v) > v_abs + _EPS:
                bad = True
                out.append(ctx.finding(
                    RULE, "failed", "danger",
                    f"{ctx.label(inst)} {pin} on {net} = {fmt(v, 'V')} exceeds the absolute maximum {abs_label}: "
                    "the input can be damaged. Divide the signal down or change the supply.",
                    inst, source_id=lim["abs_ev"][0]))
            elif rng is not None and not (rng[0] - _EPS <= v <= rng[1] + _EPS):
                bad = True
                out.append(ctx.finding(
                    RULE, "failed", "caution",
                    f"{ctx.label(inst)} {pin} on {net} = {fmt(v, 'V')} is outside the {rng[2]}: the reading is "
                    "wrong or clips (recommended operating conditions)." + lim.get("hint", ""), inst, source_id=lim["op_ev"][0]))
        if not bad:
            pins = ", ".join(p for p, _, _ in live)
            what = rng[2] if rng is not None else f"absolute maximum {abs_label}"
            out.append(Finding(RULE, "passed", None, f"{ctx.label(inst)} {pins}: within the {what}.",
                               [inst.ref], [lim["op_ev"][0] if rng is not None else lim["abs_ev"][0]]))
    return out
