"""Family rules ``ndisplay``: HT16K33, TM1638, IS31FL3731, ST7735S.

Every rule reads the catalog entries of data/modules/ndisplay.json and the project nets only; sources are the
datasheets in data/sources/mod-ndisplay.json (pages in the messages). Addresses (HT16K33 0x70–0x77 against TCA9548A
and the PCA9685 All Call), supply ranges and input levels are left to the generic rules.

- ``mod.ndisplay.tm1638_dio_pullup`` (danger): the DIO pull-up of a TM1638 goes to a rail above the ESP's input
  maximum. DIO is an input for the ESP's data, but the TM1638 answers key data on it as an N-channel open-drain
  output (V2.2 p. 2), so the pull-up voltage reaches the ESP pin. ``mod.level_out`` does not see this (DIO is
  modelled as a module input); a missing pull-up is ``mod.required_parts``.
- ``mod.ndisplay.tm1638_own_lines`` (caution): STB/CLK/DIO of a TM1638 on an I²C or SPI net or on a net shared with
  another module type. The 3-wire interface (V2.2 p. 1–2) has no address and answers on DIO open-drain; it is
  neither I²C nor SPI in the strict sense.
- ``mod.ndisplay.is31_sdb`` (caution): SDB of an IS31FL3731 tied to GND: hardware shutdown, the registers can be
  neither written nor read (Rev. G p. 18). SDB open is ``mod.unconnected``.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule

SRC_TM1638 = "mod-ndisplay-tm1638-ds"
SRC_IS31 = "mod-ndisplay-is31fl3731-ds"

TM1638_LINES = ("STB", "CLK", "DIO")
BUS_MODES = frozenset({"i2c_sda", "i2c_scl", "spi_sck", "spi_mosi", "spi_miso", "spi_cs"})


def _of(ctx: Ctx, module_id: str) -> list[Instance]:
    return [i for i in ctx.instances if i.module_id == module_id]


def _gpios(ctx: Ctx, net: str | None) -> list[int]:
    return list((ctx.nets.get(net) or {}).get("gpios") or []) if net else []


def _gpio_net(ctx: Ctx, value: str) -> str:
    """A plain part's conn value: ``GPIO<n>`` stands for the net of the assignment on pin n."""
    if value.startswith("GPIO") and value[4:].isdigit():
        for a in ctx.assignments:
            if a["pin"] == int(value[4:]):
                return str(a["net"])
    return value


def _resistor_ends(ctx: Ctx, net: str) -> list[tuple[str, str]]:
    """[(ref, other net)] of plain resistors with one end on ``net``."""
    out = []
    for p in ctx.parts:
        if (isinstance(p.get("module"), str) and p["module"].strip()) or str(p.get("kind") or "").lower() != "resistor":
            continue
        conn = p.get("conn")
        nets = [_gpio_net(ctx, v.strip()) for v in (conn.values() if isinstance(conn, Mapping) else [])
                if isinstance(v, str) and v.strip()]
        if net in nets:
            out += [(str(p.get("ref")), n) for n in nets if n != net]
    return out


def _i2c_nets(ctx: Ctx) -> set[str]:
    nets = {n for n, d in ctx.nets.items() if {"i2c_sda", "i2c_scl"} & set(d.get("modes") or [])}
    for bus in ctx.buses:
        nets |= {n for n in (bus.get("nets") or {}).values() if n}
    for inst in ctx.instances:
        for p in ctx.pins_with(inst, "i2c_sda") + ctx.pins_with(inst, "i2c_scl"):
            if inst.conn.get(p):
                nets.add(inst.conn[p])
    return nets


# --- TM1638 DIO pull-up voltage ----------------------------------------------------------------------------------
@rule("mod.ndisplay.tm1638_dio_pullup")
def tm1638_dio_pullup(ctx: Ctx) -> list[Finding]:
    rid = "mod.ndisplay.tm1638_dio_pullup"
    out: list[Finding] = []
    for inst in _of(ctx, "tm1638"):
        net = ctx.net_of(inst, "DIO")
        gp = _gpios(ctx, net)
        if net is None or not gp:
            continue
        ends = [(ref, other, ctx.volts(other)) for ref, other in _resistor_ends(ctx, net)]
        ups = [(ref, other, v) for ref, other, v in ends if v is not None and v > 0]
        if not ups:
            continue  # no pull-up: mod.required_parts reports it
        vmax = (ctx.esp or {}).get("v_in_max")
        if vmax is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: no electrical data for {ctx.chip}; "
                               "the DIO pull-up must not exceed the ESP input maximum.", [inst.ref], [SRC_TM1638]))
            continue
        over = [(ref, other, v) for ref, other, v in ups if v > vmax]
        pins = ", ".join(f"GPIO{g}" for g in sorted(set(gp)))
        if over and not (inst.facts or {}).get("level_shifter"):
            ref, other, v = max(over, key=lambda u: u[2])
            out.append(ctx.finding(
                rid, "failed", "danger",
                f"{ctx.label(inst)}: DIO pull-up {ref} goes to {other} ({fmt(v, 'V')}). The TM1638 sends key data "
                f"on DIO as an N-channel open-drain output (V2.2 p. 2), so {pins} sees {fmt(v, 'V')} (ESP input max "
                f"{fmt(vmax, 'V')}). Pull DIO up to 3V3 instead, or level-shift DIO.", inst, source_id=SRC_TM1638))
        else:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: DIO pull-up within the ESP input maximum "
                               f"{fmt(vmax, 'V')}.", [inst.ref], [SRC_TM1638]))
    return out


# --- TM1638 needs its own lines ----------------------------------------------------------------------------------
@rule("mod.ndisplay.tm1638_own_lines")
def tm1638_own_lines(ctx: Ctx) -> list[Finding]:
    rid = "mod.ndisplay.tm1638_own_lines"
    insts = _of(ctx, "tm1638")
    if not insts:
        return []
    i2c = _i2c_nets(ctx)
    out: list[Finding] = []
    for inst in insts:
        nets = {p: ctx.net_of(inst, p) for p in TM1638_LINES}
        if not any(nets.values()):
            continue
        hits = []
        for pin, net in nets.items():
            if not net:
                continue
            modes = set((ctx.nets.get(net) or {}).get("modes") or [])
            others = sorted({o.module_id for o in ctx.instances if o.module_id != "tm1638"
                             and net in o.conn.values()} - {None})
            if net in i2c:
                hits.append(f"{pin} on I²C net {net}")
            elif modes & BUS_MODES:
                hits.append(f"{pin} on {net} ({', '.join(sorted(modes & BUS_MODES))})")
            elif others:
                hits.append(f"{pin} on {net} shared with {', '.join(str(o) for o in others)}")
        if hits:
            out.append(ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(inst)}: {'; '.join(hits)}. The TM1638 talks over its own 3-wire interface (STB, CLK, "
                "DIO; V2.2 p. 1–2): no slave address, LSB first, and DIO answers key data open-drain, so it is "
                "neither I²C nor a shareable SPI bus. Give STB, CLK and DIO their own GPIOs (a bit-banged driver).",
                inst, source_id=SRC_TM1638, chip_fact=False))
        else:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: STB/CLK/DIO on their own nets.",
                               [inst.ref], [SRC_TM1638]))
    return out


# --- IS31FL3731 SDB ----------------------------------------------------------------------------------------------
@rule("mod.ndisplay.is31_sdb")
def is31_sdb(ctx: Ctx) -> list[Finding]:
    rid = "mod.ndisplay.is31_sdb"
    out: list[Finding] = []
    for inst in _of(ctx, "is31fl3731"):
        net = ctx.net_of(inst, "SDB")
        if net is None:
            continue  # open: mod.unconnected
        v: Any = ctx.volts(net)
        if v is not None and v == 0:
            out.append(ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(inst)}: SDB on {net}: the IS31FL3731 stays in hardware shutdown and its registers can "
                "be neither written nor read (Rev. G p. 18). Tie SDB to VCC or drive it from a GPIO.", inst,
                source_id=SRC_IS31))
        else:
            how = f"on {net} ({fmt(v, 'V')})" if v is not None else f"on {net}"
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: SDB {how}.", [inst.ref], [SRC_IS31]))
    return out
