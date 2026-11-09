"""Family rules ``wired``: RS-485, CAN and USB-UART parts of data/modules/wired.json.

Rules (warning code; severity before the severity cap):
- ``mod.wired.rs485_termination`` (``mod_wired_rs485_termination``) and ``mod.wired.can_termination``
  (``mod_wired_can_termination``): the transceivers on one bus (same pair of A/B or CANH/CANL nets) and the resistor
  parts across that pair. The data sheets terminate the line at both ends in its characteristic impedance (MAX485
  p. 13, MAX3485 p. 14, SN65HVD230 p. 27: typically 120 Ω). 2 resistors -> passed; none -> info (the bus may leave
  the project, breakout boards often carry the resistor already: declare it as a resistor part); one -> info (the other
  end); more than two -> caution (only the two ends). A resistor value outside 100–150 Ω -> info. A transceiver
  whose bus pins are not both connected -> not_checked (info).
- ``mod.wired.max485_ro_5v`` (``mod_wired_max485_ro_5v``): MAX485 with RO on an ESP net and VCC above the ESP's input
  maximum. The GPIO danger itself is reported by the generic ``mod.level_out`` (push-pull/tristate high = VCC); this
  rule only adds the pin-compatible 3.3 V alternative (MAX3485, same 8-pin pinout) as an info hint, so the danger is
  not reported twice. A level shifter (facts.level_shifter) -> passed.
- ``mod.wired.tja1050_rxd_5v`` (``mod_wired_tja1050_rxd_5v``): the same for the TJA1050's RXD (danger from
  ``mod.level_out``); hint: the SN65HVD230 runs at 3.3 V with the same pinout (pin 8: Rs instead of S).
- ``mod.wired.hvd230_rs_standby`` (``mod_wired_hvd230_rs_standby``): SN65HVD230 Rs at a rail of at least 0.75·VCC
  (or pulled up by a resistor) = standby, the driver is off -> info; Rs above VCC -> caution (recommended range
  0..VCC); a rail between low and the standby level -> caution; GND -> passed (high speed); 10–100 kΩ to GND ->
  passed (slope control), another value -> info; on an ESP net -> passed (firmware selects the mode); open ->
  not_checked (info).
- ``mod.wired.ch340_vcc`` (``mod_wired_ch340_vcc``): CH340C supply wiring (data sheet pp. 3, 5, 8, 9). VCC 3.1–3.6 V:
  V3 must be on the VCC net (else caution); without variant ``3v3`` an info hint (the base entry carries the 5 V
  levels). VCC 4.0–5.3 V: V3 on the VCC net -> caution, V3 on another rail -> caution, V3 open or without a
  capacitor to GND -> info (0.1 µF), with a capacitor -> passed. VCC between the two modes -> caution. VCC unknown ->
  not_checked (info). Outside 3.1–5.3 V: ``mod.supply_range``.

All findings rest on catalog data and go through ``ctx.finding`` (source class cap). Values are compared as given.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule

_EPS = 1e-9
RESISTOR_KINDS = frozenset({"resistor"})
CAPACITOR_KINDS = frozenset({"capacitor", "ceramic", "electrolytic", "film"})
TERM_OHM_RANGE = (100.0, 150.0)  # around the 120 Ω characteristic impedance the data sheets name (typical cable)
# ncomm transceivers join the same bus count (one finding per bus, ncomm's own rules step back)
RS485_PINS: Mapping[str, tuple[str, str]] = {"max485": ("A", "B"), "max3485": ("A", "B"), "sp3485": ("A", "B"),
                                             "thvd1450": ("A", "B")}
CAN_PINS: Mapping[str, tuple[str, str]] = {"sn65hvd230": ("CANH", "CANL"), "tja1050": ("CANH", "CANL"),
                                           "tja1051": ("CANH", "CANL"), "mcp2562": ("CANH", "CANL")}
HVD230_STANDBY_REL = 0.75  # V(Rs) for standby: 0.75 VCC .. VCC (SN65HVD230 p. 6)
HVD230_SLOPE_OHM = (10e3, 100e3)  # 10 kΩ to 100 kΩ to GND = slope control (p. 5)
CH340_3V3 = (3.1, 3.6)  # CH340C, V3 connected to VCC (p. 9)
CH340_5V = (4.0, 5.3)  # V3 only to a capacitor (p. 8)
_GPIO_NET = re.compile(r"^GPIO(\d{1,3})$")
_OHM = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*([kKM]?)\s*(?:\u2126|\u03a9|ohms?|R)?\s*$")
_OHM_MID = re.compile(r"^\s*(\d+)\s*([kKMR])\s*(\d+)\s*$")  # 4k7, 1R5


# --- helpers ------------------------------------------------------------------------------------------------------
def _uniq(items: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    for x in items:
        if x not in out:
            out.append(x)
    return out


def ohms(value: Any) -> float | None:
    """Resistance of a part value: 120, "120", "120R", "120 Ω", "4k7", "10k", "1M"; None if not readable."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value) if value > 0 else None
    if not isinstance(value, str):
        return None
    mult = {"": 1.0, "R": 1.0, "k": 1e3, "K": 1e3, "M": 1e6}
    m = _OHM_MID.match(value)
    if m:
        return float(f"{m.group(1)}.{m.group(3)}") * mult[m.group(2)]
    m = _OHM.match(value)
    if m:
        v = float(m.group(1).replace(",", ".")) * mult[m.group(2)]
        return v if v > 0 else None
    return None


def _pin_net(ctx: Ctx) -> dict[int, str]:
    out: dict[int, str] = {}
    for a in ctx.assignments:
        if isinstance(a.get("pin"), int) and isinstance(a.get("net"), str):
            out.setdefault(a["pin"], a["net"])
    return out


def _plain(ctx: Ctx, kinds: frozenset[str]) -> list[tuple[str, Any, set[str]]]:
    """(ref, value, nets) of the plain parts of these kinds (``GPIO<n>`` = the net of the assignment on n)."""
    pin_net = _pin_net(ctx)
    out = []
    for p in ctx.parts:
        if p.get("module") or str(p.get("kind", "")).lower() not in kinds or not isinstance(p.get("conn"), Mapping):
            continue
        nets = set()
        for v in p["conn"].values():
            if isinstance(v, str) and v.strip():
                m = _GPIO_NET.match(v.strip())
                nets.add(pin_net.get(int(m.group(1)), v.strip()) if m else v.strip())
        out.append((str(p.get("ref") or "?"), p.get("value"), nets))
    return out


def _between(ctx: Ctx, kinds: frozenset[str], a: str, b: str) -> list[tuple[str, Any]]:
    return [(ref, val) for ref, val, nets in _plain(ctx, kinds) if a in nets and b in nets and a != b]


def _esp_net(ctx: Ctx, net: str | None) -> bool:
    return bool(net and (ctx.nets.get(net) or {}).get("gpios"))


def _gpio_text(ctx: Ctx, net: str) -> str:
    gp = (ctx.nets.get(net) or {}).get("gpios") or []
    return ", ".join(f"GPIO{g}" for g in gp) or net


def _esp_vmax(ctx: Ctx) -> float | None:
    v = (ctx.esp or {}).get("v_in_max")
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _of(ctx: Ctx, ids: Iterable[str]) -> list[Instance]:
    want = set(ids)
    return [i for i in ctx.instances if i.module_id in want]


# --- termination --------------------------------------------------------------------------------------------------
def _termination(ctx: Ctx, rid: str, table: Mapping[str, tuple[str, str]], what: str) -> list[Finding]:
    out: list[Finding] = []
    buses: dict[frozenset[str], list[Instance]] = {}
    for inst in _of(ctx, table):
        pa, pb = table[inst.module_id]
        na, nb = inst.conn.get(pa), inst.conn.get(pb)
        if not na or not nb or na == nb:
            out.append(ctx.finding(rid, "not_checked", "info", f"{ctx.label(inst)}: {pa}/{pb} not both connected to "
                                   f"bus nets: the {what} termination is not checked.", inst, source_id=ctx.src(inst)))
            continue
        buses.setdefault(frozenset((na, nb)), []).append(inst)
    for pair, insts in buses.items():
        na, nb = sorted(pair)
        rs = _between(ctx, RESISTOR_KINDS, na, nb)
        nodes = sum(i.qty for i in insts)
        who = ", ".join(i.ref for i in insts)
        refs = _uniq([*(i.ref for i in insts), *(r for r, _ in rs)])
        src = ctx.src(insts[0])
        head = f"{what} bus {na}/{nb} ({nodes} transceiver{'s' if nodes != 1 else ''}: {who})"
        if not rs:
            out.append(ctx.finding(rid, "failed", "info", f"{head}: no termination resistor across {na}/{nb} in the "
                                   "project. Terminate the two bus ends with the cable's characteristic impedance "
                                   "(typically 120 Ω); boards often carry one already: declare it as a resistor part.",
                                   insts, source_id=src, refs=refs))
            continue
        if len(rs) == 1:
            out.append(ctx.finding(rid, "failed", "info", f"{head}: one termination resistor ({rs[0][0]}); the other "
                                   "bus end needs one too (if the bus continues outside this project, terminate "
                                   "there).", insts, source_id=src, refs=refs))
        elif len(rs) > 2:
            out.append(ctx.finding(rid, "failed", "caution", f"{head}: {len(rs)} termination resistors "
                                   f"({', '.join(r for r, _ in rs)}); terminate only the two bus ends: extra resistors "
                                   "load the drivers. Remove those of the middle nodes (often on the breakout board).",
                                   insts, source_id=src, refs=refs))
        odd = [(r, v) for r, v in rs if (o := ohms(v)) is not None
               and not TERM_OHM_RANGE[0] - _EPS <= o <= TERM_OHM_RANGE[1] + _EPS]
        if odd:
            txt = ", ".join(f"{r} {fmt(ohms(v), 'Ω')}" for r, v in odd)
            out.append(ctx.finding(rid, "failed", "info", f"{head}: termination {txt} differs from the cable's "
                                   "characteristic impedance (typically 120 Ω).", insts, source_id=src, refs=refs))
        if len(rs) == 2 and not odd:
            out.append(Finding(rid, "passed", None, f"{head}: terminated at two points "
                               f"({', '.join(r for r, _ in rs)}).", refs, [src] if src else []))
    return out


@rule("mod.wired.rs485_termination")
def rs485_termination(ctx: Ctx) -> list[Finding]:
    return _termination(ctx, "mod.wired.rs485_termination", RS485_PINS, "RS-485")


@rule("mod.wired.can_termination")
def can_termination(ctx: Ctx) -> list[Finding]:
    return _termination(ctx, "mod.wired.can_termination", CAN_PINS, "CAN")


# --- 5 V receiver outputs (hints next to mod.level_out) -----------------------------------------------------------
def _five_v_out(ctx: Ctx, rid: str, module_id: str, out_pin: str, hint: str) -> list[Finding]:
    out: list[Finding] = []
    vmax = _esp_vmax(ctx)
    for inst in _of(ctx, [module_id]):
        net = inst.conn.get(out_pin)
        if not _esp_net(ctx, net):
            continue
        vcc = ctx.supply_volts(inst).get("VCC")
        if vcc is None or vmax is None:
            why = "VCC unknown" if vcc is None else f"no input maximum for chip {ctx.chip}"
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)} {out_pin}: {why}.", [inst.ref]))
            continue
        if vcc <= vmax + _EPS:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)} at {fmt(vcc, 'V')}: {out_pin} stays within "
                               f"the ESP input maximum {fmt(vmax, 'V')}.", [inst.ref], [s for s in [ctx.src(inst)] if s]))
            continue
        if (inst.facts or {}).get("level_shifter") is True:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)} {out_pin}: level shifter on the board (user).",
                               [inst.ref], [s for s in [ctx.src(inst)] if s]))
            continue
        out.append(ctx.finding(rid, "failed", "info", f"{ctx.label(inst)} at {fmt(vcc, 'V')} drives {out_pin} up to "
                               f"VCC on {_gpio_text(ctx, net)} (GPIO risk: mod_level_out). {hint}", inst,
                               source_id=ctx.src(inst)))
    return out


@rule("mod.wired.max485_ro_5v")
def max485_ro_5v(ctx: Ctx) -> list[Finding]:
    return _five_v_out(ctx, "mod.wired.max485_ro_5v", "max485", "RO",
                       "Alternative: the MAX3485 has the same 8-pin pinout and runs at 3.0–3.6 V; or divide RO.")


@rule("mod.wired.tja1050_rxd_5v")
def tja1050_rxd_5v(ctx: Ctx) -> list[Finding]:
    return _five_v_out(ctx, "mod.wired.tja1050_rxd_5v", "tja1050", "RXD",
                       "Alternative: the SN65HVD230 runs at 3.0–3.6 V with the same pinout (pin 8 is Rs: GND = high "
                       "speed); or divide RXD.")


# --- SN65HVD230 Rs ------------------------------------------------------------------------------------------------
def _hvd230_one(ctx: Ctx, inst: Instance, rid: str, out: list[Finding]) -> None:
    lab, src = ctx.label(inst), ctx.src(inst)
    net = inst.conn.get("Rs")
    vcc = ctx.supply_volts(inst).get("VCC")

    def fail(sev: str, msg: str, refs: list[str] | None = None) -> None:
        out.append(ctx.finding(rid, "failed", sev, f"{lab}: {msg}", inst, source_id=src, refs=refs))

    def ok(msg: str, refs: list[str] | None = None) -> None:
        out.append(Finding(rid, "passed", None, f"{lab}: {msg}", refs or [inst.ref], [src] if src else []))

    if net is None:
        out.append(ctx.finding(rid, "not_checked", "info", f"{lab}: Rs not connected; the data sheet defines GND "
                               "(high speed), 10–100 kΩ to GND (slope control) or high (standby). Tie Rs to GND "
                               "for normal operation.", inst, source_id=src))
        return
    if _esp_net(ctx, net):
        ok(f"Rs on {_gpio_text(ctx, net)}: the firmware selects the mode (low = high speed, high = standby).")
        return
    rv = ctx.volts(net)
    if rv is not None:
        if rv <= _EPS:
            ok("Rs at GND: high-speed mode.")
        elif vcc is None:
            out.append(ctx.finding(rid, "not_checked", "info", f"{lab}: Rs at {net} ({fmt(rv, 'V')}) and VCC "
                                   "unknown: standby starts at 0.75·VCC.", inst, source_id=src))
        elif rv > vcc + _EPS:
            fail("caution", f"Rs at {net} ({fmt(rv, 'V')}) is above VCC {fmt(vcc, 'V')} (recommended V(Rs) "
                 "0..VCC); the transceiver is in standby: the driver is off, the node only listens.")
        elif rv >= HVD230_STANDBY_REL * vcc - _EPS:
            fail("info", f"Rs at {net} ({fmt(rv, 'V')} ≥ 0.75·VCC = {fmt(HVD230_STANDBY_REL * vcc, 'V')}): "
                 "standby (listen only), the driver is off. Tie Rs to GND to transmit.")
        else:
            fail("caution", f"Rs at {net} ({fmt(rv, 'V')}) is neither GND nor the standby level "
                 f"(≥ {fmt(HVD230_STANDBY_REL * vcc, 'V')}); tie Rs to GND or through 10–100 kΩ to GND.")
        return
    to_gnd = [(r, v) for r, v, nets in _plain(ctx, RESISTOR_KINDS) if net in nets and "GND" in nets]
    to_rail = [(r, v, n) for r, v, nets in _plain(ctx, RESISTOR_KINDS) if net in nets
               for n in nets if n != net and (ctx.volts(n) or 0) > _EPS]
    if to_rail:
        r, _, n = to_rail[0]
        fail("info", f"Rs pulled up to {n} through {r}: standby (listen only) once V(Rs) ≥ 0.75·VCC; the driver is "
             "off. Tie Rs to GND to transmit.", [inst.ref, r])
    elif to_gnd:
        r, v = to_gnd[0]
        o = ohms(v)
        if o is not None and not HVD230_SLOPE_OHM[0] - _EPS <= o <= HVD230_SLOPE_OHM[1] + _EPS:
            fail("info", f"Rs to GND through {r} {fmt(o, 'Ω')}: slope control is specified for 10–100 kΩ "
                 "(a strong pull-down = high speed).", [inst.ref, r])
        else:
            ok(f"Rs to GND through {r}" + (f" {fmt(o, 'Ω')}" if o is not None else "") + ": slope control.",
               [inst.ref, r])
    else:
        out.append(ctx.finding(rid, "not_checked", "info", f"{lab}: Rs on net {net} without a rail, GPIO or "
                               "resistor: the mode is not known.", inst, source_id=src))


@rule("mod.wired.hvd230_rs_standby")
def hvd230_rs_standby(ctx: Ctx) -> list[Finding]:
    rid = "mod.wired.hvd230_rs_standby"
    out: list[Finding] = []
    for inst in _of(ctx, ["sn65hvd230"]):
        _hvd230_one(ctx, inst, rid, out)
    return out


# --- CH340C VCC / V3 ----------------------------------------------------------------------------------------------
def _ch340_one(ctx: Ctx, inst: Instance, rid: str, out: list[Finding]) -> None:
    lab, src = ctx.label(inst), ctx.src(inst)
    vnet, v3 = inst.conn.get("VCC"), inst.conn.get("V3")
    vcc = ctx.volts(vnet)

    def fail(sev: str, msg: str, refs: list[str] | None = None) -> None:
        out.append(ctx.finding(rid, "failed", sev, f"{lab} at {fmt(vcc, 'V')}: {msg}", inst, source_id=src,
                               refs=refs))

    def ok(msg: str, refs: list[str] | None = None) -> None:
        out.append(Finding(rid, "passed", None, f"{lab} at {fmt(vcc, 'V')}: {msg}", refs or [inst.ref],
                           [src] if src else []))

    if vcc is None:
        out.append(ctx.finding(rid, "not_checked", "info", f"{lab}: VCC unknown: the V3 wiring (3.3 V mode: V3 to "
                               "VCC; 5 V mode: 0.1 µF from V3 to GND) is not checked.", inst, source_id=src))
        return
    if CH340_3V3[0] - _EPS <= vcc <= CH340_3V3[1] + _EPS:
        if v3 != vnet:
            fail("caution", "3.3 V mode needs V3 connected to VCC "
                 + (f"(V3 is on {v3})." if v3 else "(V3 is open)."))
        elif inst.variant != "3v3":
            fail("info", "V3 on VCC (3.3 V mode); choose variant 3v3 so the 3.3 V input/output levels are used.")
        else:
            ok("V3 connected to VCC (3.3 V mode).")
    elif CH340_5V[0] - _EPS <= vcc <= CH340_5V[1] + _EPS:
        if v3 is not None and v3 == vnet:
            fail("caution", "in 5 V mode V3 carries only a 0.1 µF capacitor to GND; do not connect it to VCC.")
        elif v3 is not None and ctx.volts(v3) is not None and v3 != "GND":
            fail("caution", f"V3 is on the rail {v3}; in 5 V mode V3 carries only a 0.1 µF capacitor to GND.")
        elif v3 == "GND":
            fail("caution", "V3 is on GND; in 5 V mode V3 carries a 0.1 µF capacitor to GND, not a short.")
        else:
            caps = _between(ctx, CAPACITOR_KINDS, v3, "GND") if v3 else []
            if caps:
                ok(f"5 V mode, V3 decoupled by {caps[0][0]}.", [inst.ref, caps[0][0]])
            else:
                fail("info", "5 V mode: add a 0.1 µF capacitor from V3 to GND (not found in the project).")
    elif CH340_3V3[1] < vcc < CH340_5V[0]:
        fail("caution", f"between the 3.3 V mode ({fmt(CH340_3V3[0], 'V')}–{fmt(CH340_3V3[1], 'V')}, V3 to VCC) "
             f"and the 5 V mode ({fmt(CH340_5V[0], 'V')}–{fmt(CH340_5V[1], 'V')}): no specified operating point.")


@rule("mod.wired.ch340_vcc")
def ch340_vcc(ctx: Ctx) -> list[Finding]:
    rid = "mod.wired.ch340_vcc"
    out: list[Finding] = []
    for inst in _of(ctx, ["ch340c"]):
        _ch340_one(ctx, inst, rid, out)
    return out
