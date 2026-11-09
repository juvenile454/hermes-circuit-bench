"""Family rules ``thermo``: MAX31855, MAX6675, MAX31865, NTCLE100E3.

- ``mod.thermo.max31855_tminus``: MAX31855 pin T- "Do not connect to GND" (data sheet p. 7); the chip references T-
  to ground internally and its fault detection tests T+/T- for shorts to GND and VCC (p. 9). T- on GND or on any
  supply rail -> failed/caution; T- on a signal net (the thermocouple lead) -> passed; T- open -> not_checked.
- ``mod.thermo.max6675_tminus``: the opposite for the MAX6675: "T- must be grounded" for the open-thermocouple
  detection (p. 5; pin table p. 4: "Should be connected to ground externally"). T- on another rail or a floating
  signal net -> failed/caution. The catalog ties T- to GND when the project does not name it.
- ``mod.thermo.max6675_vcc``: the remedy the generic rules lack. VCC above the ESP input maximum (5 V boards): SO
  then drives up to VCC (``mod.level_out``, danger) and VIH = 0.7 × VCC (``mod.level_in``); the MAX6675 runs from
  3.0 V (VCC 3.0–5.5 V, p. 2), so this rule adds one ``info`` finding "power it from 3.3 V". ``facts.level_shifter``
  -> passed; supply range violations stay with ``mod.supply_range``.
All limits come from the catalog entry (data/modules/thermo.json), never from constants in this file.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule

_EPS = 1e-9


def _supply_spec(inst: Instance, pin: str) -> Mapping[str, Any]:
    spec = (inst.module.get("supplies") or {}).get(pin)
    return spec if isinstance(spec, Mapping) else {}


def _on_gnd(ctx: Ctx, net: str) -> bool:
    return net == "GND" or ctx.volts(net) == 0


@rule("mod.thermo.max31855_tminus")
def max31855_tminus(ctx: Ctx) -> list[Finding]:
    rid = "mod.thermo.max31855_tminus"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != "max31855":
            continue
        net = ctx.net_of(inst, "T-")
        src = ctx.src(inst)
        if net is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: T- not connected in the project, "
                               "grounding not checked.", [inst.ref]))
            continue
        if _on_gnd(ctx, net):
            out.append(ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(inst)} T- is on {net}: the datasheet says 'Do not connect to GND'. The MAX31855 biases T- "
                "internally and reports a grounded input as a short to GND (fault bit SCG). Wire T- only to the "
                "thermocouple and use an ungrounded junction.", inst, source_id=src))
        elif ctx.volts(net) is not None:
            out.append(ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(inst)} T- is on the rail {net} ({fmt(ctx.volts(net), 'V')}): the fault detection reads "
                "this as a short to VCC. Wire T- only to the thermocouple.", inst, source_id=src))
        else:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)} T- on {net}, not grounded.", [inst.ref],
                               [src] if src else []))
    return out


@rule("mod.thermo.max6675_tminus")
def max6675_tminus(ctx: Ctx) -> list[Finding]:
    rid = "mod.thermo.max6675_tminus"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != "max6675":
            continue
        net = ctx.net_of(inst, "T-")
        src = ctx.src(inst)
        if net is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: T- not connected, grounding not checked.",
                               [inst.ref]))
        elif _on_gnd(ctx, net):
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)} T- on {net} (grounded, as the open-thermocouple "
                               "detection needs).", [inst.ref], [src] if src else []))
        else:
            where = f"the rail {net} ({fmt(ctx.volts(net), 'V')})" if ctx.volts(net) is not None else f"net {net}"
            out.append(ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(inst)} T- is on {where}: the MAX6675 needs T- grounded for its open-thermocouple "
                "detection (bit D2). Connect T- to GND close to the GND pin.", inst, source_id=src))
    return out


@rule("mod.thermo.max6675_vcc")
def max6675_vcc(ctx: Ctx) -> list[Finding]:
    rid = "mod.thermo.max6675_vcc"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != "max6675":
            continue
        v = ctx.supply_volts(inst).get("VCC")
        v_in_max = (ctx.esp or {}).get("v_in_max")
        spec = _supply_spec(inst, "VCC")
        lo, hi = ctx.fv(spec.get("min"), inst), ctx.fv(spec.get("max"), inst)
        src = ctx.src(inst, spec.get("min"))
        if v is None or not isinstance(v_in_max, int | float) or lo is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: VCC or the ESP input maximum unknown, "
                               "supply level not checked.", [inst.ref]))
            continue
        if v <= v_in_max + _EPS:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)} on VCC = {fmt(v, 'V')}: SO stays within the "
                               f"ESP input maximum {fmt(v_in_max, 'V')}.", [inst.ref], [src] if src else []))
            continue
        if (inst.facts or {}).get("level_shifter"):
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)} on VCC = {fmt(v, 'V')} behind a level shifter "
                               "(facts.level_shifter, user).", [inst.ref], [src] if src else []))
            continue
        rng = f"{fmt(lo, 'V')}–{fmt(hi, 'V')}" if hi is not None else f"from {fmt(lo, 'V')}"
        vih = ctx.level(inst, "vih")
        need = f" and the inputs need VIH {fmt(vih, 'V')}" if vih is not None else ""
        fix = ("power it from 3.3 V and wire SO, SCK and CS directly to the ESP32" if lo <= v_in_max + _EPS
               else "shift the SO level down")
        out.append(ctx.finding(
            rid, "failed", "info",
            f"{ctx.label(inst)} on VCC = {fmt(v, 'V')}: SO drives up to VCC{need}. The MAX6675 runs from {rng}: "
            f"{fix}.", inst, source_id=src, supply=True))
    return out
