"""Family rules ``motor``: motor supply, ULN COM wiring, L298 flyback diodes,
A4988 logic supply. Data from circuit_bench/data/modules/motor.json; every number comes from the module entry.

- ``mod.motor.motor_supply``: the motor supply pins of a driver (``MOTOR_PINS``) must sit on a rail: open -> caution,
  unknown voltage -> not_checked, below the operating minimum -> caution (undervoltage lockout: the motor does not
  turn), on the ESP's 3V3 rail -> caution (rule of thumb), DRV8825 VMA/VMB on different nets -> caution. Above the
  maximum is left to ``mod.supply_range`` (no duplicate warning).
- ``mod.motor.uln_com_flyback``: ULN2003A/ULN2803A/ULN2803C COM is the common cathode of the clamp diodes; it must sit
  on the load (coil) supply for motors and relays. Open -> caution, on GND -> caution, unknown -> not_checked.
- ``mod.motor.l298_flyback``: the L298 has no internal flyback diodes; every connected OUTx net needs a diode to VS
  and one to GND (plain parts of kind ``diode``/``schottky``/``rectifier``/``flyback`` or catalog diodes of category
  ``discrete.diode`` such as ss14, 1n5819, 1n4007, bat54, per junction). Missing -> caution; variant ``board`` (red L298N boards, diodes
  usually fitted, unverified) -> info.
- ``mod.motor.a4988_vdd_3v3``: the A4988 inputs switch at 0.7 · VDD. With VDD on a known rail and inputs driven by
  the ESP: 0.7 · VDD ≤ ESP VOH -> passed; above -> caution with the hint to power VDD from 3V3 (3.0–5.5 V allowed).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = (
    modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule)

RULE_SOURCE = "rule-of-thumb"
_EPS = 1e-9

# module id -> motor supply pins (names as in motor.json)
MOTOR_PINS: dict[str, tuple[str, ...]] = {
    "a4988": ("VBB1", "VBB2"),
    "drv8825": ("VMA", "VMB"),
    "drv8833": ("VM",),
    "l298n": ("VS",),
    "tb6612fng": ("VM1", "VM2", "VM3"),
    "tmc2209": ("VS",),
}
SAME_NET_REQUIRED = frozenset({"drv8825"})  # datasheet p. 4: "All VM pins must be connected to the same supply voltage."
ULN_IDS = frozenset({"uln2003a", "uln2803a", "uln2803c"})
ESP_RAIL = "3V3"
A4988_INPUTS = ("STEP", "DIR", "ENABLE", "RESET", "SLEEP", "MS1", "MS2", "MS3")


def _supplies(inst: Instance) -> Mapping[str, Any]:
    sup = inst.module.get("supplies")
    return sup if isinstance(sup, Mapping) else {}


def _min_of(ctx: Ctx, inst: Instance, pins: tuple[str, ...]) -> tuple[float | None, Any]:
    for pin in pins:
        spec = _supplies(inst).get(pin)
        if isinstance(spec, Mapping) and spec.get("min") is not None:
            return ctx.fv(spec["min"], inst), spec["min"]
    return None, None


@rule("mod.motor.motor_supply")
def motor_supply(ctx: Ctx) -> list[Finding]:
    rid = "mod.motor.motor_supply"
    out: list[Finding] = []
    for inst in ctx.instances:
        pins = MOTOR_PINS.get(inst.module_id)
        if not pins:
            continue
        nets = {p: ctx.net_of(inst, p) for p in pins}
        connected = {p: n for p, n in nets.items() if n is not None}
        names = ", ".join(pins)
        src = ctx.src(inst)
        if not connected:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{ctx.label(inst)}: motor supply {names} not connected: the driver cannot turn the "
                                   "motor. Connect a separate motor supply.", inst, source_id=src, supply=True))
            continue
        distinct = sorted(set(connected.values()))
        if inst.module_id in SAME_NET_REQUIRED and (len(distinct) > 1 or len(connected) < len(pins)):
            found = ", ".join(f"{p}={n or 'open'}" for p, n in nets.items())
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{ctx.label(inst)}: {names} must all sit on the same motor supply "
                                   f"(found {found}).", inst,
                                   source_id=src, supply=True))
        lo, f_lo = _min_of(ctx, inst, pins)
        for net in distinct:
            on = ", ".join(p for p, n in connected.items() if n == net)
            v = ctx.volts(net)
            who = f"{ctx.label(inst)} {on} on {net}"
            if v is None:
                out.append(Finding(rid, "not_checked", "info",
                                   f"{who} with unknown voltage: motor supply not checked (name the rail voltage in "
                                   "options.rails).", [inst.ref]))
                continue
            if net == ESP_RAIL:
                out.append(ctx.finding(rid, "failed", "caution",
                                       f"{who} = {fmt(v, 'V')}: the motor shares the ESP's 3.3 V rail. Motor current "
                                       "and switching noise can reset the ESP; use a separate motor supply.", inst,
                                       source_id=RULE_SOURCE, source_ids=[RULE_SOURCE, src] if src else [RULE_SOURCE],
                                       supply=True))
                continue
            if lo is not None and v < lo - _EPS:
                out.append(ctx.finding(rid, "failed", "caution",
                                       f"{who} = {fmt(v, 'V')} is below the minimum motor supply {fmt(lo, 'V')}: the "
                                       "driver stays in undervoltage lockout and the motor does not turn.", inst,
                                       source_id=ctx.src(inst, f_lo), supply=True))
                continue
            out.append(Finding(rid, "passed", None, f"{who} = {fmt(v, 'V')}: separate motor supply"
                               + (f" at or above the minimum {fmt(lo, 'V')}." if lo is not None else "."),
                               [inst.ref], [src] if src else []))
    return out


@rule("mod.motor.uln_com_flyback")
def uln_com_flyback(ctx: Ctx) -> list[Finding]:
    rid = "mod.motor.uln_com_flyback"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id not in ULN_IDS:
            continue
        net = ctx.net_of(inst, "COM")
        src = ctx.src(inst)
        if net is None:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{ctx.label(inst)}: COM is not connected, so the internal clamp diodes do nothing. "
                                   "With a motor, relay or solenoid tie COM to the coil supply (COM may float only for "
                                   "resistive loads).", inst, source_id=src, chip_fact=False))
        elif net == "GND":
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{ctx.label(inst)}: COM is on GND. COM is the common cathode of the clamp diodes: on "
                                   "GND they conduct whenever an output is off and the load stays on. Tie COM to the "
                                   "coil supply.", inst, source_id=src, chip_fact=False))
        elif ctx.volts(net) is None:
            out.append(Finding(rid, "not_checked", "info",
                               f"{ctx.label(inst)}: COM on net {net} with unknown voltage; it must be the coil supply "
                               "(name the rail voltage in options.rails).", [inst.ref]))
        else:
            out.append(Finding(rid, "passed", None,
                               f"{ctx.label(inst)}: COM on {net} = {fmt(ctx.volts(net), 'V')}; this must be the supply "
                               "of the coils it drives.", [inst.ref], [src] if src else []))
    return out


_DIODE_KINDS = frozenset({"diode", "schottky", "rectifier", "flyback"})
DIODE_CATEGORY = "discrete.diode"


def _module_diode_pairs(inst: Instance) -> list[set[str]]:
    """Net pairs of each junction of a catalog diode (1N4007, SS14, BAT54 …): A–K, or A*/K* through a common CT."""
    names = [str(p.get("name")) for p in inst.module.get("pins") or [] if isinstance(p, Mapping)]
    anodes = [n for n in names if n.upper().startswith("A")]
    cathodes = [n for n in names if n.upper().startswith("K")]
    if "CT" in names:  # series pair: A1–CT and CT–K2
        pairs = [(a, "CT") for a in anodes] + [("CT", k) for k in cathodes]
    else:
        pairs = [(a, k) for a in anodes for k in cathodes]
    out = []
    for a, k in pairs:
        na, nk = inst.conn.get(a), inst.conn.get(k)
        if isinstance(na, str) and isinstance(nk, str) and na != nk:
            out.append({na, nk})
    return out


def _diode_nets(ctx: Ctx) -> list[set[str]]:
    """Nets of every diode: plain parts of kind diode (schottky, rectifier, flyback) and catalog diodes (category
    discrete.diode, e.g. ss14, 1n5819), which count like plain diodes."""
    out = []
    for p in ctx.parts:
        if not isinstance(p, Mapping) or p.get("module") or str(p.get("kind", "")).lower() not in _DIODE_KINDS:
            continue
        conn = p.get("conn")
        if isinstance(conn, Mapping):
            nets = {v for v in conn.values() if isinstance(v, str)}
            if nets:
                out.append(nets)
    for inst in ctx.instances:
        if inst.module.get("category") == DIODE_CATEGORY:
            out.extend(_module_diode_pairs(inst))
    return out


@rule("mod.motor.l298_flyback")
def l298_flyback(ctx: Ctx) -> list[Finding]:
    rid = "mod.motor.l298_flyback"
    out: list[Finding] = []
    diodes = _diode_nets(ctx)
    for inst in ctx.instances:
        if inst.module_id != "l298n":
            continue
        src = ctx.src(inst)
        outs = {p: ctx.net_of(inst, p) for p in ("OUT1", "OUT2", "OUT3", "OUT4")}
        used = {p: n for p, n in outs.items() if n is not None}
        if not used:
            out.append(Finding(rid, "not_checked", "info",
                               f"{ctx.label(inst)}: outputs not connected, flyback diodes not checked. The L298 needs "
                               "external diodes from every output to VS and to GND for motors.", [inst.ref],
                               [src] if src else []))
            continue
        vs = ctx.net_of(inst, "VS")
        gnd = ctx.net_of(inst, "GND") or "GND"
        missing = []
        for pin, net in sorted(used.items()):
            others = [d - {net} for d in diodes if net in d]
            up = vs is not None and any(vs in o for o in others)
            down = any(gnd in o for o in others)
            if not (up and down):
                missing.append(f"{pin} ({'to VS' if not up else ''}{' and ' if not up and not down else ''}"
                               f"{'to GND' if not down else ''})")
        if not missing:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: every used output has a diode to VS and to GND.",
                               [inst.ref], [src] if src else []))
            continue
        board = inst.variant == "board"
        text = (f"{ctx.label(inst)}: flyback diodes missing at {', '.join(missing)}. The L298 has no internal diodes; "
                "fit fast-recovery (trr ≤ 200 ns) or Schottky diodes from each output to VS and to GND.")
        if board:
            text += " L298N boards usually carry these eight diodes (unverified): add them as parts to confirm."
        out.append(ctx.finding(rid, "failed", "info" if board else "caution", text, inst, source_id=src,
                               chip_fact=False))
    return out


@rule("mod.motor.a4988_vdd_3v3")
def a4988_vdd_3v3(ctx: Ctx) -> list[Finding]:
    rid = "mod.motor.a4988_vdd_3v3"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != "a4988":
            continue
        driven = [p for p in A4988_INPUTS if (n := ctx.net_of(inst, p)) and ctx.nets.get(n, {}).get("gpios")]
        if not driven:
            continue
        src = ctx.src(inst)
        v = ctx.supply_volts(inst).get("VDD")
        if v is None:
            out.append(Finding(rid, "not_checked", "info",
                               f"{ctx.label(inst)}: VDD not on a known rail; input levels not checked (VDD 3.0–5.5 V, "
                               "inputs switch at 0.7 · VDD).", [inst.ref]))
            continue
        esp_voh = (ctx.esp or {}).get("voh")
        vih = ctx.level(inst, "vih")
        if esp_voh is None or vih is None:
            out.append(Finding(rid, "not_checked", "info",
                               f"{ctx.label(inst)}: ESP output level unknown for {ctx.chip}; input levels not checked.",
                               [inst.ref]))
            continue
        lo, hi = (ctx.fv(_supplies(inst).get("VDD", {}).get(k), inst) for k in ("min", "max"))
        if vih <= esp_voh + _EPS:
            out.append(Finding(rid, "passed", None,
                               f"{ctx.label(inst)}: VDD {fmt(v, 'V')}, inputs high from {fmt(vih, 'V')} (0.7 · VDD); "
                               f"the ESP drives at least {fmt(esp_voh, 'V')} ({', '.join(driven)}).", [inst.ref],
                               [src] if src else []))
            continue
        hint = ""
        if lo is not None and hi is not None and lo - _EPS <= 3.3 <= hi + _EPS:
            hint = f" Power VDD from 3V3 instead: the A4988 logic runs from {fmt(lo, 'V')} to {fmt(hi, 'V')}."
        out.append(ctx.finding(rid, "failed", "caution",
                               f"{ctx.label(inst)}: VDD {fmt(v, 'V')} makes the inputs need {fmt(vih, 'V')} "
                               f"(0.7 · VDD), more than the ESP's {fmt(esp_voh, 'V')} ({', '.join(driven)}).{hint}",
                               inst, source_id=src))
    return out
