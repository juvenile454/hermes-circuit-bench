"""Family rules ``npixel``: WS2813 / WS2815 addressable LEDs and the PC817-type
optocouplers LTV-817 (Lite-On) and EL817 (Everlight).

- ``mod.npixel.data_in_rail``: a WS2813 / WS2815 data input (DIN, BIN, DIN1, DIN2) wired straight to a supply rail.
  Above the input's absolute maximum (WS2813: VDD + 0.7 V, p. 2; WS2815: 5.7 V, p. 2 — so a WS2815 input on its own
  12 V rail) -> danger. GND -> passed (the usual tie of an unused backup input). A rail within the rating -> info
  (a data input held high receives no data). The generic ``mod.level_in`` only looks at ESP-driven nets.
- ``mod.npixel.opto_led_resistor``: the LED of an LTV-817 / EL817 (ANODE, CATHODE) between an ESP GPIO or a rail and
  GND/a GPIO without a resistor in series. The LED's VF is 1.2 V typ (both datasheets, p. 10 / p. 3): from a rail the
  current is limited by nothing -> danger (IF abs. max 50 mA / 60 mA); straight from a GPIO the GPIO's drive limits
  it -> caution. A resistor part on the ANODE or the CATHODE net (other than GND) -> passed. Size it with
  ``calc opto`` (part ``pc817``: same VF 1.2/1.4 V at 20 mA and CTR ≥ 50 % at 5 mA as both clones).
- ``mod.npixel.opto_vceo``: the collector pull-up voltage of an LTV-817 / EL817 above its VCEO of 35 V (both
  datasheets; Sharp's PC817 has 80 V) -> danger: a PC817 design above 35 V does not carry over to these clones.
  Pull-up = a resistor between COLLECTOR and a rail with a known voltage. No pull-up resistor -> not_checked.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = (
    modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule)

LED_IDS = ("ws2813", "ws2815")
OPTO_IDS = ("ltv817", "el817")
DATA_IN_PINS = {"ws2813": ("DIN", "BIN"), "ws2815": ("DIN1", "DIN2")}
RESISTOR_KINDS = frozenset({"resistor"})
_EPS = 1e-9
_GND = "GND"


def _f(value: float, unit: str, page: int, evidence: Any, src: str, conditions: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "page": page, "evidence": evidence, "source_id": src, "conditions": conditions}


# Datasheet values of the rules (quoted in tests/corpus/excerpts/mod-npixel-<part>.txt; checked by the tests).
LT_SRC, EL_SRC = "mod-npixel-ltv817-ds", "mod-npixel-el817-ds"
FACTS: dict[str, dict[str, dict[str, Any]]] = {
    "ltv817": {
        "if_abs_max": _f(0.050, "A", 9, "Forward Current I F 50 mA", LT_SRC, "absolute maximum rating, Ta = 25 °C"),
        "vceo": _f(35.0, "V", 9, "Collector - Emitter Voltage  V CEO  35 V", LT_SRC, "absolute maximum rating"),
        "vf_typ": _f(1.2, "V", 10, "Forward Voltage V F — 1.2 1.4  V I F=20mA", LT_SRC, "typ at IF = 20 mA"),
    },
    "el817": {
        "if_abs_max": _f(0.060, "A", 2, "Forward current IF 60 mA", EL_SRC, "absolute maximum rating, Ta = 25 °C"),
        "vceo": _f(35.0, "V", 2, "Collector-Emitter voltage VCEO 35 V", EL_SRC, "absolute maximum rating"),
        "vf_typ": _f(1.2, "V", 3, "Forward Voltage VF - 1.2 1.4 V IF = 20mA", EL_SRC, "typ at IF = 20 mA"),
    },
}


def _gpio_nets(ctx: Ctx) -> set[str]:
    return {n for n, d in ctx.nets.items() if d.get("gpios")}


def _resolve(ctx: Ctx, net: Any) -> str | None:
    """A plain part's conn value as a net (``GPIO<n>`` -> the net of the assignment on n)."""
    if not isinstance(net, str) or not net.strip():
        return None
    net = net.strip()
    if net.startswith("GPIO") and net[4:].isdigit():
        pin = int(net[4:])
        for a in ctx.assignments:
            if a.get("pin") == pin:
                return str(a.get("net") or net)
    return net


def _resistors(ctx: Ctx) -> list[tuple[str, list[str]]]:
    out = []
    for p in ctx.parts:
        if isinstance(p.get("module"), str) and p["module"].strip():
            continue
        if str(p.get("kind") or "").lower() in RESISTOR_KINDS and isinstance(p.get("ref"), str):
            conn = p.get("conn")
            nets = [_resolve(ctx, v) for v in (conn.values() if isinstance(conn, Mapping) else [])]
            out.append((p["ref"], [n for n in nets if n]))
    return out


# --- mod.npixel.data_in_rail ------------------------------------------------------------------------------------
@rule("mod.npixel.data_in_rail")
def data_in_rail(ctx: Ctx) -> list[Finding]:
    rid = "mod.npixel.data_in_rail"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id not in LED_IDS:
            continue
        label = ctx.label(inst)
        io = inst.module.get("io") or {}
        f_max = io.get("v_in_max")
        vmax = ctx.level(inst, "v_in_max")
        src = ctx.src(inst, f_max)
        page = f_max.get("page") if isinstance(f_max, Mapping) else None
        for name in DATA_IN_PINS[inst.module_id]:
            net = inst.conn.get(name)
            if net is None:
                continue
            if net == _GND:
                out.append(ctx.finding(rid, "passed", None, f"{label} {name} tied to GND.", inst, source_id=src))
                continue
            v = ctx.volts(net)
            if v is None:
                continue  # a signal net: mod.level_in / mod.unconnected
            if vmax is None:
                out.append(ctx.finding(rid, "not_checked", "info", f"{label} {name} on rail {net} ({fmt(v, 'V')}): the "
                                       "input maximum is not known for this supply.", inst, source_id=src))
            elif v > vmax + _EPS:
                out.append(ctx.finding(
                    rid, "failed", "danger",
                    f"{label} {name} on rail {net} = {fmt(v, 'V')} exceeds the data input maximum {fmt(vmax, 'V')} "
                    f"(datasheet p. {page}): the LED can be damaged. Tie an unused backup input to GND "
                    "(or to the data line), never to the LED supply.", inst, source_id=src))
            else:
                out.append(ctx.finding(
                    rid, "failed", "info",
                    f"{label} {name} held at {net} ({fmt(v, 'V')}): within the input rating, but a data input "
                    "fixed high receives no data. Tie an unused backup input to GND.", inst, source_id=src))
    return out


# --- optocoupler rules ------------------------------------------------------------------------------------------
def _opto(ctx: Ctx) -> list[Instance]:
    return [i for i in ctx.instances if i.module_id in OPTO_IDS]


@rule("mod.npixel.opto_led_resistor")
def opto_led_resistor(ctx: Ctx) -> list[Finding]:
    rid = "mod.npixel.opto_led_resistor"
    out: list[Finding] = []
    gpio = _gpio_nets(ctx)
    res = _resistors(ctx)
    for inst in _opto(ctx):
        label, facts = ctx.label(inst), FACTS[inst.module_id]
        a, k = inst.conn.get("ANODE"), inst.conn.get("CATHODE")
        if a is None or k is None:
            continue  # mod.unconnected
        series = [ref for ref, nets in res if (a in nets and a != _GND) or (k in nets and k != _GND)]
        if series:
            out.append(ctx.finding(rid, "passed", None, f"{label}: LED current set by {', '.join(series)}.", inst,
                                   source_id=facts["if_abs_max"]["source_id"]))
            continue
        va = ctx.volts(a)
        ifm, vf = facts["if_abs_max"], facts["vf_typ"]
        cite = (f"IF max {fmt(ifm['value'] * 1000, 'mA')} (absolute, p. {ifm['page']}), VF {fmt(vf['value'], 'V')} "
                f"typ (p. {vf['page']})")
        if va is not None and va > 0 and (k == _GND or k in gpio):
            out.append(ctx.finding(rid, "failed", "danger",
                                   f"{label}: LED between {a} ({fmt(va, 'V')}) and {k} without a series resistor; "
                                   f"nothing limits the current ({cite}). Add a resistor (calc opto).", inst,
                                   source_id=ifm["source_id"]))
        elif a in gpio or k in gpio:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{label}: LED driven straight from a GPIO ({a if a in gpio else k}) without a "
                                   f"series resistor; only the GPIO's drive limits the current ({cite}). Add a "
                                   "resistor (calc opto).", inst, source_id=ifm["source_id"]))
        else:
            out.append(Finding(rid, "not_checked", None, f"{label}: no resistor on the LED nets {a}/{k}; the drive "
                               "of these nets is not known.", [inst.ref], [ifm["source_id"]]))
    return out


@rule("mod.npixel.opto_vceo")
def opto_vceo(ctx: Ctx) -> list[Finding]:
    rid = "mod.npixel.opto_vceo"
    out: list[Finding] = []
    res = _resistors(ctx)
    for inst in _opto(ctx):
        label, f = ctx.label(inst), FACTS[inst.module_id]["vceo"]
        c = inst.conn.get("COLLECTOR")
        if c is None:
            continue
        ups = [(ref, o, ctx.volts(o)) for ref, nets in res if c in nets for o in nets
               if o != c and (ctx.volts(o) or 0) > 0]
        if ctx.volts(c):
            ups.append(("-", c, ctx.volts(c)))
        if not ups:
            out.append(Finding(rid, "not_checked", None, f"{label}: no pull-up resistor from COLLECTOR ({c}) to a "
                               "known rail; VCEO not checked.", [inst.ref], [f["source_id"]]))
            continue
        ref, rail, v = max(ups, key=lambda t: t[2] or 0)
        how = f"pulled up by {ref} to {rail}" if ref != "-" else f"on rail {rail}"
        if v is not None and v > f["value"] + _EPS:
            out.append(ctx.finding(rid, "failed", "danger",
                                   f"{label} COLLECTOR {how} = {fmt(v, 'V')} exceeds VCEO {fmt(f['value'], 'V')} "
                                   f"(absolute maximum, p. {f['page']}). A Sharp PC817 has 80 V; this part does "
                                   "not. Lower the pull-up voltage or use a part with a higher VCEO.", inst,
                                   source_id=f["source_id"]))
        else:
            out.append(ctx.finding(rid, "passed", None, f"{label} COLLECTOR {how} = {fmt(v, 'V')} ≤ VCEO "
                                   f"{fmt(f['value'], 'V')}.", inst, source_id=f["source_id"]))
    return out
