"""Family rules ``nmotion``: ICM-20948, BMI270, LSM6DS3TR-C, VL6180X,
MAX30101, DRV5055. Only what the generic rules cannot see; every limit is cited with its source id and
page from data/modules/nmotion.json.

- ``mod.nmotion.cs_high_i2c``: on an I²C bus the chip select must sit at the I/O supply level. BMI270 CSB (a rising
  edge after power-up switches the interface to SPI until the next reset, p. 123), LSM6DS3TR-C CS (low = SPI, I²C
  disabled, p. 38/20), ICM-20948 nCS (power-up with nCS low is not supported, p. 19). CS on the VDDIO net or a rail at
  the VDDIO voltage -> passed; CS on GND or another rail -> caution; CS open -> caution, BMI270 info (internal pull-up
  to VDDIO, "possible, not recommended"); CS on an ESP GPIO -> info (drive it high before the first transfer), BMI270
  caution (any low-high edge after power-up selects SPI); VDDIO voltage unknown -> not_checked.
- ``mod.nmotion.vl6180x_ce``: VL6180X, VL53L0X and VL53L1X all start at 0x29 and are re-addressed by software only
  (VL6180X: I2C_SLAVE__DEVICE_ADDRESS, p. 76). Several of them that see each other on one bus, at least one a
  VL6180X, need their own enable line each (VL6180X GPIO0/CE, VL53 XSHUT) on an ESP output; at most one without ->
  passed (wake it alone, re-address it first). More than one without -> failed: danger when the project already gives
  distinct addresses (cannot be programmed), else caution (``mod.address_conflict`` reports the clash).
  ``mod.prox.vl53_xshut`` covers groups of VL53 only.
- ``mod.nmotion.max30101_vled``: MAX30101 VLED+ has two ranges (p. 2): red/IR 3.1–5.0 V, green 4.5–5.5 V. VLED+ on a
  rail inside 3.1–5.5 V but outside the green range -> info "green LED not specified" (heart-rate mode with the green
  LED); above 5.0 V -> info "red/IR not specified"; both ranges met -> passed; unknown -> not_checked. Outside
  3.1–5.5 V is ``mod.supply_range``.
- ``mod.nmotion.drv5055_vcc``: DRV5055 VCC has two isolated operating ranges, 3–3.63 V and 4.5–5.5 V (p. 4). VCC in
  the gap -> caution; in a range -> passed (with the ratiometric hint); unknown -> not_checked. Outside 3–5.5 V is
  ``mod.supply_range``; OUT above the ESP input at VCC 5 V is ``mod.level_out``.
- ``mod.nmotion.bmi270_aux_gnd``: BMI270 ASDx/ASCx must not be connected to GND (p. 135) -> caution; VDDIO or open ->
  passed.
Messages English, values via ``fmt``; the severity cap comes from ``ctx.finding``.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule

_EPS = 1e-9

# module id -> (CS pin, I/O supply pin, datasheet hint, open CS has an internal pull-up)
CS_PARTS: Mapping[str, tuple[str, str, str, bool]] = {
    "bmi270": ("CSB", "VDDIO", ("hard-wire CSB to VDDIO for I²C; a CSB rising edge after power-up selects SPI "
                                "(datasheet p. 123)"), True),
    "lsm6ds3trc": ("CS", "VDDIO", ("CS must be tied high to Vdd_IO for I²C; CS low selects SPI and disables I²C "
                                   "(datasheet p. 38)"), False),
    "icm20948": ("nCS", "VDDIO", ("keep nCS high (VDDIO) for I²C; power-up with nCS low is not supported "
                                  "(datasheet p. 19)"), False),
}
TOF_ENABLE: Mapping[str, str] = {"vl6180x": "GPIO0", "vl53l0x": "XSHUT", "vl53l1x": "XSHUT"}
# DRV5055 operating VCC ranges (p. 4, "two isolated operating VCC ranges"); the outer limits are in the module data
DRV5055_GAP_V = (3.63, 4.5)
# MAX30101 VLED+ (p. 2): red/IR 3.1–5.0 V, green 4.5–5.5 V
MAX30101_RED_IR_MAX_V = 5.0
MAX30101_GREEN_MIN_V = 4.5


def _passed(rid: str, ctx: Ctx, inst: Instance, msg: str, f: Any = None) -> Finding:
    sid = ctx.src(inst, f)
    return Finding(rid, "passed", None, msg, [inst.ref], [sid] if sid else [])


def _gpio_net(ctx: Ctx, net: str) -> bool:
    return ctx.volts(net) is None and bool((ctx.nets.get(net) or {}).get("gpios"))


def _out_gpio(ctx: Ctx, net: str | None) -> bool:
    if net is None or ctx.volts(net) is not None:
        return False
    return "out" in (ctx.nets.get(net) or {}).get("modes", [])


# --- chip select high for I²C --------------------------------------------------------------------------------------
@rule("mod.nmotion.cs_high_i2c")
def cs_high_i2c(ctx: Ctx) -> list[Finding]:
    rid = "mod.nmotion.cs_high_i2c"
    out: list[Finding] = []
    for inst in ctx.instances:
        spec = CS_PARTS.get(inst.module_id)
        if spec is None or inst.ref not in ctx.placement:
            continue
        cs_pin, io_pin, hint, pulled = spec
        sid = ctx.src(inst)
        cs = ctx.net_of(inst, cs_pin)
        io_net = ctx.net_of(inst, io_pin)
        vio = ctx.volts(io_net)
        who = f"{ctx.label(inst)} {cs_pin}"
        if cs is None:
            if pulled:
                out.append(ctx.finding(rid, "failed", "info",
                                       f"{who} is open: the internal pull-up keeps I²C only while the pin stays above "
                                       f"VIH. Better {hint}.", inst, source_id=sid))
            else:
                out.append(ctx.finding(rid, "failed", "caution", f"{who} is not connected: {hint}.", inst,
                                       source_id=sid))
            continue
        if io_net is not None and cs == io_net:
            out.append(_passed(rid, ctx, inst, f"{who} on {cs} ({io_pin}), I²C mode."))
            continue
        v_cs = ctx.volts(cs)
        if v_cs is None and _gpio_net(ctx, cs):
            if inst.module_id == "bmi270":
                out.append(ctx.finding(rid, "failed", "caution",
                                       f"{who} on GPIO net {cs}: any low-to-high edge after power-up switches the "
                                       f"interface to SPI until the next reset; {hint}.", inst, source_id=sid))
            else:
                out.append(ctx.finding(rid, "failed", "info",
                                       f"{who} on GPIO net {cs}: drive it high before power-up or the first I²C "
                                       f"transfer; {hint}.", inst, source_id=sid))
            continue
        if vio is None:
            out.append(Finding(rid, "not_checked", None, f"{who} on {cs}, {io_pin} voltage unknown.", [inst.ref]))
            continue
        if v_cs is not None and abs(v_cs - vio) < _EPS:
            out.append(_passed(rid, ctx, inst, f"{who} on {cs} = {fmt(v_cs, 'V')} ({io_pin} level), I²C mode."))
            continue
        level = "unknown voltage" if v_cs is None else fmt(v_cs, "V")
        out.append(ctx.finding(rid, "failed", "caution",
                               f"{who} on {cs} ({level}), {io_pin} is {fmt(vio, 'V')}: {hint}.", inst, source_id=sid))
    return out


# --- several 0x29 ToF sensors with a VL6180X -------------------------------------------------------------------------
def _clusters(ctx: Ctx, insts: list[Instance]) -> list[list[Instance]]:
    parent = list(range(len(insts)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(insts):
        for j in range(i + 1, len(insts)):
            pa, pb = ctx.placement[a.ref], ctx.placement[insts[j].ref]
            if pa[0] == pb[0] and ctx.visible(pa[1], pb[1]):
                parent[find(j)] = find(i)
    groups: dict[int, list[Instance]] = {}
    for i, inst in enumerate(insts):
        groups.setdefault(find(i), []).append(inst)
    return [g for g in groups.values() if len(g) > 1]


@rule("mod.nmotion.vl6180x_ce")
def vl6180x_ce(ctx: Ctx) -> list[Finding]:
    rid = "mod.nmotion.vl6180x_ce"
    insts = [i for i in ctx.instances if i.module_id in TOF_ENABLE and i.ref in ctx.placement]
    out: list[Finding] = []
    for group in _clusters(ctx, insts):
        if not any(i.module_id == "vl6180x" for i in group):
            continue
        nets = {i.ref: ctx.net_of(i, TOF_ENABLE[i.module_id]) for i in group}
        counts: dict[str, int] = {}
        for n in nets.values():
            if n is not None:
                counts[n] = counts.get(n, 0) + 1
        own = {r: n is not None and counts[n] == 1 and _out_gpio(ctx, n) for r, n in nets.items()}
        lacking = [i for i in group if not own[i.ref]]
        bus = ctx.placement[group[0].ref][0]
        names = ", ".join(f"{i.ref} ({i.module_id})" for i in group)
        sids = [s for s in (ctx.src(i) for i in group) if s]
        if len(lacking) <= 1:
            hint = ("" if not lacking else
                    f" {lacking[0].ref} has no own {TOF_ENABLE[lacking[0].module_id]} GPIO: keep all others in "
                    f"standby and re-address {lacking[0].ref} first.")
            out.append(Finding(rid, "passed", None,
                               f"{names} on bus {bus}: each sensor can be enabled alone to set its address.{hint}",
                               [i.ref for i in group], sids))
            continue
        addrs = [i.address for i in group]
        distinct = all(addrs) and len(set(addrs)) == len(addrs)
        why = []
        for i in lacking:
            pin, n = TOF_ENABLE[i.module_id], nets[i.ref]
            if n is None:
                why.append(f"{i.ref} {pin} open")
            elif counts[n] > 1:
                why.append(f"{i.ref} {pin} shares net {n}")
            else:
                why.append(f"{i.ref} {pin} on {n} (no ESP output)")
        tail = (" The addresses set in the project can only be programmed if each sensor is enabled alone."
                if distinct else "")
        out.append(ctx.finding(
            rid, "failed", "danger" if distinct else "caution",
            f"{names} on bus {bus} all start at 0x29; {'; '.join(why)}. Give each sensor (all but one at least) its "
            f"own enable line (VL6180X GPIO0/CE, VL53 XSHUT) on an ESP output and re-address them one by one at "
            f"start-up.{tail}", group, source_id=[ctx.src(i) for i in group], chip_fact=False))
    return out


# --- MAX30101 VLED+ ranges -----------------------------------------------------------------------------------------
def _supply(inst: Instance, pin: str) -> Mapping[str, Any]:
    sup = inst.module.get("supplies")
    spec = sup.get(pin) if isinstance(sup, Mapping) else None
    return spec if isinstance(spec, Mapping) else {}


@rule("mod.nmotion.max30101_vled")
def max30101_vled(ctx: Ctx) -> list[Finding]:
    rid = "mod.nmotion.max30101_vled"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != "max30101":
            continue
        spec = _supply(inst, "VLED+")
        lo, hi = ctx.fv(spec.get("min"), inst), ctx.fv(spec.get("max"), inst)
        net = ctx.net_of(inst, "VLED+")
        v = ctx.volts(net)
        if lo is None or hi is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: no VLED+ range in the module data.",
                               [inst.ref]))
            continue
        if v is None:
            where = "is not connected" if net is None else f"is on {net} (voltage unknown)"
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: VLED+ {where}.", [inst.ref]))
            continue
        if v < lo - _EPS or v > hi + _EPS:
            continue  # mod.supply_range reports it
        sid = ctx.src(inst, spec.get("max"))
        if v < MAX30101_GREEN_MIN_V - _EPS:
            out.append(ctx.finding(
                rid, "failed", "info",
                f"{ctx.label(inst)}: VLED+ on {net} = {fmt(v, 'V')} suits the red/IR LEDs ({fmt(lo, 'V')}–"
                f"{fmt(MAX30101_RED_IR_MAX_V, 'V')}); the green LED needs {fmt(MAX30101_GREEN_MIN_V, 'V')}–"
                f"{fmt(hi, 'V')} (datasheet p. 2). Use 5 V for green-LED heart-rate mode.",
                inst, source_id=sid, supply=True))
        elif v > MAX30101_RED_IR_MAX_V + _EPS:
            out.append(ctx.finding(
                rid, "failed", "info",
                f"{ctx.label(inst)}: VLED+ on {net} = {fmt(v, 'V')} is specified for the green LED only; red/IR end at "
                f"{fmt(MAX30101_RED_IR_MAX_V, 'V')} (datasheet p. 2).", inst, source_id=sid, supply=True))
        else:
            out.append(_passed(rid, ctx, inst, f"{ctx.label(inst)}: VLED+ on {net} = {fmt(v, 'V')} suits red, IR "
                                               f"and green LEDs.", spec.get("max")))
    return out


# --- DRV5055 VCC gap -----------------------------------------------------------------------------------------------
@rule("mod.nmotion.drv5055_vcc")
def drv5055_vcc(ctx: Ctx) -> list[Finding]:
    rid = "mod.nmotion.drv5055_vcc"
    out: list[Finding] = []
    lo_gap, hi_gap = DRV5055_GAP_V
    for inst in ctx.instances:
        if inst.module_id != "drv5055":
            continue
        net = ctx.net_of(inst, "VCC")
        v = ctx.volts(net)
        spec = _supply(inst, "VCC")
        if v is None:
            where = "is not connected" if net is None else f"is on {net} (voltage unknown)"
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: VCC {where}.", [inst.ref]))
            continue
        lo, hi = ctx.fv(spec.get("min"), inst), ctx.fv(spec.get("max"), inst)
        if lo is not None and hi is not None and (v < lo - _EPS or v > hi + _EPS):
            continue  # mod.supply_range reports it
        if lo_gap + _EPS < v < hi_gap - _EPS:
            out.append(ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(inst)}: VCC on {net} = {fmt(v, 'V')} lies between the two operating ranges "
                f"{fmt(lo if lo is not None else 3.0, 'V')}–{fmt(lo_gap, 'V')} and {fmt(hi_gap, 'V')}–"
                f"{fmt(hi if hi is not None else 5.5, 'V')} (datasheet p. 4); the sensor is not specified there.",
                inst, source_id=ctx.src(inst, spec.get("min")), supply=True))
            continue
        out.append(_passed(rid, ctx, inst,
                           f"{ctx.label(inst)}: VCC on {net} = {fmt(v, 'V')} within an operating range; OUT is "
                           f"ratiometric (VCC/2 at 0 mT), so measure VCC or use it as the ADC reference.",
                           spec.get("min")))
    return out


# --- BMI270 auxiliary pins -----------------------------------------------------------------------------------------
@rule("mod.nmotion.bmi270_aux_gnd")
def bmi270_aux_gnd(ctx: Ctx) -> list[Finding]:
    rid = "mod.nmotion.bmi270_aux_gnd"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != "bmi270":
            continue
        gnd = [p for p in ("ASDX", "ASCX") if (n := ctx.net_of(inst, p)) is not None and ctx.volts(n) == 0.0]
        if gnd:
            out.append(ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(inst)}: {', '.join(gnd)} on GND. Unused auxiliary pins go to VDDIO or stay open, never "
                f"GND (datasheet p. 135).", inst, source_id=ctx.src(inst)))
        else:
            out.append(_passed(rid, ctx, inst, f"{ctx.label(inst)}: ASDx/ASCx not on GND."))
    return out
