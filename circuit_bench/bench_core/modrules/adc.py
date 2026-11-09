"""Family rules ``adc``: analog inputs of ADS1115/ADS1015, MCP3008, PCF8591.

- ``mod.adc.ads_ain_vdd``: an AINx of an ADS1115/ADS1015 on a net with a known voltage. Above VDD + 0.3 V (absolute
  maximum) -> ``danger``; above VDD (recommended range "V(AINx) Absolute input voltage GND VDD") -> ``caution``.
  The full-scale ranges ±6.144 V / ±4.096 V do not lift that limit (TI p. 4 note 2, p. 15).
- ``mod.adc.ain_abs_max``: the same check for the other ADCs of the family, with their own limits: MCP3008 CHx above
  VDD + 0.6 V -> ``danger``, above VREF (input range VSS…VREF) -> ``caution``; PCF8591 AINx above VDD + 0.5 V
  -> ``danger``, above VDD -> ``caution``.
- Only nets with a known voltage count (rails, ``options.rails``); a sensor signal net has no voltage in the project,
  so nothing is claimed for it. Rule of the bus speed (PCF8591: 100 kHz) is the generic ``mod.bus_speed``: the
  entry carries ``f_max_hz``; the bus summary shows the 100 kHz limit.

Every limit below carries source, page and the verbatim excerpt line(s) (tests/test_mod_adc.py checks them against
tests/corpus/excerpts/mod-adc-*.txt).
"""
from __future__ import annotations

from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = (
    modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule)

_EPS = 1e-9

# module id -> analog input limits. abs: (supply pin, offset in V) = absolute maximum; op: the pin whose voltage is the
# top of the measuring range (operating limit, caution). evidence: (source id, page, [lines]) for abs and op.
AIN_LIMITS: dict[str, dict[str, Any]] = {
    "ads1115": {
        "rule": "mod.adc.ads_ain_vdd", "pins": ("AIN0", "AIN1", "AIN2", "AIN3"),
        "abs": ("VDD", 0.3), "op": "VDD",
        "abs_ev": ("mod-adc-ads1115-ds", 4, ["Analog input voltage AIN0, AIN1, AIN2, AIN3 GND – 0.3 VDD + 0.3 V"]),
        "op_ev": ("mod-adc-ads1115-ds", 4, ["V(AINx) Absolute input voltage GND VDD V"]),
    },
    "ads1015": {
        "rule": "mod.adc.ads_ain_vdd", "pins": ("AIN0", "AIN1", "AIN2", "AIN3"),
        "abs": ("VDD", 0.3), "op": "VDD",
        "abs_ev": ("mod-adc-ads1015-ds", 4, ["Analog input voltage AIN0, AIN1, AIN2, AIN3 GND – 0.3 VDD + 0.3 V"]),
        "op_ev": ("mod-adc-ads1015-ds", 4, ["V(AINx) Absolute input voltage GND VDD V"]),
    },
    "mcp3008": {
        "rule": "mod.adc.ain_abs_max", "pins": tuple(f"CH{i}" for i in range(8)),
        "abs": ("VDD", 0.6), "op": "VREF",
        "abs_ev": ("mod-adc-mcp3008-ds", 3, ["All Inputs and Outputs w.r.t. VSS ............ - 0.6V to VDD +0 . 6 V"]),
        "op_ev": ("mod-adc-mcp3008-ds", 4, ["VIN VSS —V REF V"]),
    },
    "pcf8591": {
        "rule": "mod.adc.ain_abs_max", "pins": ("AIN0", "AIN1", "AIN2", "AIN3"),
        "abs": ("VDD", 0.5), "op": "VDD",
        "abs_ev": ("mod-adc-pcf8591-ds", 16, ["VI input voltage any input \uf02d0.5 V DD + 0.5 V"]),
        "op_ev": ("mod-adc-pcf8591-ds", 18, ["Via analog input voltage VSS -V DD V"]),
    },
}


def _check(ctx: Ctx, rule_id: str) -> list[Finding]:
    out: list[Finding] = []
    for inst in ctx.instances:
        lim = AIN_LIMITS.get(inst.module_id)
        if lim is None or lim["rule"] != rule_id:
            continue
        live = [(pin, net, ctx.volts(net)) for pin in lim["pins"] if (net := ctx.net_of(inst, pin)) is not None]
        live = [(pin, net, v) for pin, net, v in live if v is not None]
        if not live:
            continue  # no analog input on a net with a known voltage: nothing to claim
        sup, off = lim["abs"]
        vdd = ctx.volts(ctx.net_of(inst, sup))
        if vdd is None:
            out.append(Finding(rule_id, "not_checked", "info",
                               f"{ctx.label(inst)}: {sup} voltage unknown, analog inputs on known rails not checked.",
                               [inst.ref]))
            continue
        v_abs = vdd + off
        v_op = ctx.volts(ctx.net_of(inst, lim["op"])) if lim["op"] != sup else vdd
        bad = False
        for pin, net, v in live:
            if v > v_abs + _EPS:
                bad = True
                out.append(ctx.finding(
                    rule_id, "failed", "danger",
                    f"{ctx.label(inst)} {pin} on {net} = {fmt(v, 'V')} exceeds the absolute maximum {sup} + "
                    f"{fmt(off, 'V')} = {fmt(v_abs, 'V')}: the input can be damaged. Divide the signal down or "
                    f"raise {sup}.", inst, source_id=lim["abs_ev"][0]))
            elif v_op is not None and v > v_op + _EPS:
                bad = True
                out.append(ctx.finding(
                    rule_id, "failed", "caution",
                    f"{ctx.label(inst)} {pin} on {net} = {fmt(v, 'V')} is above the input range (≤ {lim['op']} = "
                    f"{fmt(v_op, 'V')}): the reading clips and the input is outside the recommended operating "
                    "conditions.", inst, source_id=lim["op_ev"][0]))
        if not bad:
            pins = ", ".join(p for p, _, _ in live)
            out.append(Finding(rule_id, "passed", None,
                               f"{ctx.label(inst)} {pins}: within the input range (≤ {fmt(v_op or vdd, 'V')}).",
                               [inst.ref], [lim["op_ev"][0]]))
    return out


@rule("mod.adc.ads_ain_vdd")
def ads_ain_vdd(ctx: Ctx) -> list[Finding]:
    """ADS1115/ADS1015: AINx on a known rail above VDD + 0.3 V (danger) or above VDD (caution)."""
    return _check(ctx, "mod.adc.ads_ain_vdd")


@rule("mod.adc.ain_abs_max")
def ain_abs_max(ctx: Ctx) -> list[Finding]:
    """MCP3008 (VDD + 0.6 V / VREF) and PCF8591 (VDD + 0.5 V / VDD): analog input on a known rail."""
    return _check(ctx, "mod.adc.ain_abs_max")
