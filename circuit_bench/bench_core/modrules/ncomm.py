"""Family rules ``ncomm``: RS-485, CAN and sub-GHz radio parts of
data/modules/ncomm.json (SP3485, THVD1450, TJA1051T/3, MCP2562, SX1262, CC1101, RFM69HCW).

Supply ranges, logic levels (VIO / VBAT_IO domains), SPI clock and the current budget are covered by the generic
rules; these rules add what the data sheets demand beyond them (warning code; severity before the severity cap):

- ``mod.ncomm.rs485_termination`` / ``mod.ncomm.can_termination``: the bus termination check of wired.py
  (``mod.wired.rs485_termination`` / ``can_termination``, same logic and messages) for buses whose transceivers are
  all ncomm parts. A bus that also carries a wired.json transceiver is left to the wired rule (it counts the
  resistors on the pair the same way), so no bus is reported twice. Once the wired tables list the ncomm ids
  (proposed contract change), these rules return nothing.
- ``mod.ncomm.can_listen_only``: the mode pin of the CAN transceivers. MCP2562 STBY has an internal pull-up to VIO
  (DS20005167C p. 5): open or at a rail above 0 V = Standby, transmitter off -> caution; GND, a resistor to GND or an
  ESP net -> passed. TJA1051 S has an internal pull-down (p. 6): open, GND or an ESP net -> passed; at a rail above
  0 V = Silent mode, transmitter off (p. 5) -> caution.
- ``mod.ncomm.sx126x_busy``: SX1262 BUSY must be read by the host before every command (data sheet Rev. 1.1 p. 49):
  BUSY on an ESP net -> passed; open or on another net -> caution.
- ``mod.ncomm.rfm69_reset``: RFM69HCW RESET is active high (p. 76: pulled high = reset). At a rail above 0 V ->
  caution (the module stays in reset); open, GND or an ESP net -> passed.
- ``mod.ncomm.rfm69_pa20``: RFM69HCW +20 dBm on PA_BOOST: transmit duty cycle at most 1 % and VSWR at most 3:1
  (p. 11) -> info; supply below 2.4 V -> caution (+20 dBm needs 2.4–3.6 V, p. 11). Supply unknown -> the info only.
- ``mod.ncomm.cc1101_supply``: CC1101 "All supply pins must have the same voltage" (SWRS061I p. 8): AVDD and DVDD on
  rails of different voltage -> caution; equal -> passed; one unknown -> not_checked (info).

All findings rest on catalog data and go through ``ctx.finding`` (source class cap). Values are compared as given.
"""
from __future__ import annotations

from collections.abc import Mapping

from . import modcheck, wired

Ctx, Finding, Instance, fmt, rule = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule

_EPS = 1e-9
RS485_PINS: Mapping[str, tuple[str, str]] = {"sp3485": ("A", "B"), "thvd1450": ("A", "B")}
CAN_PINS: Mapping[str, tuple[str, str]] = {"tja1051": ("CANH", "CANL"), "mcp2562": ("CANH", "CANL")}
# mode pin, internal pull, what a high level does (data sheet pages in the docstring)
CAN_MODE_PIN: Mapping[str, tuple[str, str, str]] = {
    "mcp2562": ("STBY", "up", "Standby: transmitter and high-speed receiver off, the node cannot send"),
    "tja1051": ("S", "down", "Silent mode: transmitter off, the node only listens"),
}
RFM69_PA20_MIN_V = 2.4  # RFM69HCW +20 dBm: 2.4–3.6 V (p. 11)
RFM69_DUTY_PCT = 1.0  # +20 dBm duty cycle limit (p. 11)


def _of(ctx: Ctx, ids) -> list[Instance]:
    want = set(ids)
    return [i for i in ctx.instances if i.module_id in want]


def _pair(inst: Instance, pins: tuple[str, str]) -> frozenset[str] | None:
    a, b = inst.conn.get(pins[0]), inst.conn.get(pins[1])
    return frozenset((a, b)) if a and b and a != b else None


def _termination(ctx: Ctx, rid: str, mine: Mapping[str, tuple[str, str]], theirs: Mapping[str, tuple[str, str]],
                 what: str) -> list[Finding]:
    if set(mine) <= set(theirs):  # the wired rule covers our parts already
        return []
    taken = {p for i in _of(ctx, theirs) if (p := _pair(i, theirs[i.module_id]))}
    skip = {i.ref for i in _of(ctx, mine) if _pair(i, mine[i.module_id]) in taken}
    return [f for f in wired._termination(ctx, rid, mine, what) if not skip.intersection(f.refs)]


@rule("mod.ncomm.rs485_termination")
def rs485_termination(ctx: Ctx) -> list[Finding]:
    return _termination(ctx, "mod.ncomm.rs485_termination", RS485_PINS, wired.RS485_PINS, "RS-485")


@rule("mod.ncomm.can_termination")
def can_termination(ctx: Ctx) -> list[Finding]:
    return _termination(ctx, "mod.ncomm.can_termination", CAN_PINS, wired.CAN_PINS, "CAN")


def _ok(rid: str, inst: Instance, msg: str, src: str | None, refs: list[str] | None = None) -> Finding:
    return Finding(rid, "passed", None, msg, refs or [inst.ref], [src] if src else [])


def _gpio(ctx: Ctx, net: str | None) -> bool:
    return bool(net and (ctx.nets.get(net) or {}).get("gpios"))


@rule("mod.ncomm.can_listen_only")
def can_listen_only(ctx: Ctx) -> list[Finding]:
    rid = "mod.ncomm.can_listen_only"
    out: list[Finding] = []
    for inst in _of(ctx, CAN_MODE_PIN):
        pin, pull, high = CAN_MODE_PIN[inst.module_id]
        lab, src, net = ctx.label(inst), ctx.src(inst), inst.conn.get(pin)
        if net is None:
            if pull == "up":
                out.append(ctx.finding(rid, "failed", "caution", f"{lab}: {pin} open; the internal pull-up selects "
                                       f"{high}. Tie {pin} to GND or drive it low from a GPIO.", inst, source_id=src))
            else:
                out.append(_ok(rid, inst, f"{lab}: {pin} open: internal pull-down, Normal mode.", src))
            continue
        if _gpio(ctx, net):
            out.append(_ok(rid, inst, f"{lab}: {pin} on {wired._gpio_text(ctx, net)}: the firmware selects the mode "
                           f"(low = Normal).", src))
            continue
        v = ctx.volts(net)
        if v is not None:
            if v <= _EPS:
                out.append(_ok(rid, inst, f"{lab}: {pin} at GND: Normal mode.", src))
            else:
                out.append(ctx.finding(rid, "failed", "caution", f"{lab}: {pin} at {net} ({fmt(v, 'V')}) selects "
                                       f"{high}. Tie {pin} to GND to transmit.", inst, source_id=src))
            continue
        down = [r for r, _, nets in wired._plain(ctx, wired.RESISTOR_KINDS) if net in nets and "GND" in nets]
        if down:
            out.append(_ok(rid, inst, f"{lab}: {pin} to GND through {down[0]}: Normal mode.", src, [inst.ref, down[0]]))
        else:
            out.append(ctx.finding(rid, "not_checked", "info", f"{lab}: {pin} on net {net} without a rail, GPIO or "
                                   "resistor to GND: the mode is not known.", inst, source_id=src))
    return out


@rule("mod.ncomm.sx126x_busy")
def sx126x_busy(ctx: Ctx) -> list[Finding]:
    rid = "mod.ncomm.sx126x_busy"
    out: list[Finding] = []
    for inst in _of(ctx, ["sx1262"]):
        lab, src, net = ctx.label(inst), ctx.src(inst), inst.conn.get("BUSY")
        if _gpio(ctx, net):
            out.append(_ok(rid, inst, f"{lab}: BUSY on {wired._gpio_text(ctx, net)}.", src))
            continue
        where = "not connected" if net is None else f"on {net}, not on an ESP input"
        out.append(ctx.finding(rid, "failed", "caution", f"{lab}: BUSY {where}. The host must wait for BUSY low "
                               "before every SPI command (commands sent while BUSY is high are lost); wire BUSY to a "
                               "GPIO input.", inst, source_id=src))
    return out


@rule("mod.ncomm.rfm69_reset")
def rfm69_reset(ctx: Ctx) -> list[Finding]:
    rid = "mod.ncomm.rfm69_reset"
    out: list[Finding] = []
    for inst in _of(ctx, ["rfm69hcw"]):
        lab, src, net = ctx.label(inst), ctx.src(inst), inst.conn.get("RESET")
        if net is None:
            out.append(_ok(rid, inst, f"{lab}: RESET open (power-on reset only).", src))
        elif _gpio(ctx, net):
            out.append(_ok(rid, inst, f"{lab}: RESET on {wired._gpio_text(ctx, net)}: keep it low, a 100 µs high "
                           "pulse resets (then wait 5 ms).", src))
        elif (v := ctx.volts(net)) is not None and v > _EPS:
            out.append(ctx.finding(rid, "failed", "caution", f"{lab}: RESET at {net} ({fmt(v, 'V')}). RESET is active "
                                   "high: the module stays in reset. Leave RESET open, tie it to GND or drive it from "
                                   "a GPIO.", inst, source_id=src))
        else:
            out.append(_ok(rid, inst, f"{lab}: RESET on {net}: not held high.", src))
    return out


@rule("mod.ncomm.rfm69_pa20")
def rfm69_pa20(ctx: Ctx) -> list[Finding]:
    rid = "mod.ncomm.rfm69_pa20"
    out: list[Finding] = []
    for inst in _of(ctx, ["rfm69hcw"]):
        lab, src = ctx.label(inst), ctx.src(inst)
        v = ctx.supply_volts(inst).get("3.3V")
        if v is not None and v < RFM69_PA20_MIN_V - _EPS:
            out.append(ctx.finding(rid, "failed", "caution", f"{lab} at {fmt(v, 'V')}: +20 dBm on PA_BOOST needs "
                                   f"{fmt(RFM69_PA20_MIN_V, 'V')}–3.6 V; below that only +17 dBm.", inst,
                                   source_id=src, supply=True))
        out.append(ctx.finding(rid, "failed", "info", f"{lab}: at +20 dBm (PA_BOOST) keep the transmit duty cycle at "
                               f"most {fmt(RFM69_DUTY_PCT, '%')} and the antenna VSWR at most 3:1.", inst,
                               source_id=src))
    return out


@rule("mod.ncomm.cc1101_supply")
def cc1101_supply(ctx: Ctx) -> list[Finding]:
    rid = "mod.ncomm.cc1101_supply"
    out: list[Finding] = []
    for inst in _of(ctx, ["cc1101"]):
        lab, src = ctx.label(inst), ctx.src(inst)
        sv = ctx.supply_volts(inst)
        a, d = sv.get("AVDD"), sv.get("DVDD")
        if a is None or d is None:
            out.append(ctx.finding(rid, "not_checked", "info", f"{lab}: AVDD or DVDD not on a known rail: the equal "
                                   "supply voltage is not checked.", inst, source_id=src))
        elif abs(a - d) > 1e-6:
            out.append(ctx.finding(rid, "failed", "caution", f"{lab}: AVDD {fmt(a, 'V')} and DVDD {fmt(d, 'V')} "
                                   "differ; all supply pins must have the same voltage.", inst, source_id=src,
                                   supply=True))
        else:
            out.append(_ok(rid, inst, f"{lab}: AVDD and DVDD both {fmt(a, 'V')}.", src))
    return out
