"""Family rules ``motion``: motion and position sensors.

Every limit comes from the module data (data/modules/motion.json) and is cited with its source id and page; the
rules only read the project.

- ``mod.motion.max30102_vdd_1v8``: MAX30102 VDD is a 1.8 V supply (1.7–2.0 V, absolute maximum 2.2 V). VDD on a rail
  above the absolute maximum (e.g. 3V3) → danger; above the operating range → caution; VDD and VLED+ on the same rail
  → caution (they need different supplies); within the range → passed; VDD open or on an unknown net → not_checked.
  A failed finding supersedes ``mod.supply_range`` on the same part (one cause, one warning, with the remedy).
- ``mod.motion.adxl345_cs_high_i2c``: ADXL345 on an I²C bus needs CS tied high to VDD I/O (no default mode when CS
  floats). CS on the VDDIO net or a rail at the VDDIO voltage → passed; CS open → caution; CS on GND/another rail →
  caution (SPI mode or wrong level); CS on a GPIO net → info (firmware must hold it high); VDDIO unknown →
  not_checked.
- ``mod.motion.bno055_clock_stretch``: a BNO055 on an I²C bus → info that it stretches SCL, only if the module data
  carries the verified datasheet note on clock stretching (else no finding).

The MPU-6050 address clash with RTCs at 0x68 is the generic ``mod.address_conflict`` (tests/test_mod_motion.py).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule

_EPS = 1e-9
_COVERS_SUPPLY = ("mod.supply_range",)


def _covers(f: Finding, rids: tuple[str, ...]) -> Finding:
    """Mark a failed finding as covering the generic rules ``rids`` on its refs (modcheck.Finding.supersedes)."""
    f.supersedes = rids
    return f


def _spec(inst: Instance, pin: str) -> Mapping[str, Any]:
    sup = inst.module.get("supplies")
    spec = sup.get(pin) if isinstance(sup, Mapping) else None
    return spec if isinstance(spec, Mapping) else {}


def _page(f: Any) -> str:
    return f" (datasheet p. {f['page']})" if isinstance(f, Mapping) and isinstance(f.get("page"), int) else ""


def _on_i2c(ctx: Ctx, inst: Instance) -> bool:
    return inst.ref in ctx.placement


# --- MAX30102 ------------------------------------------------------------------------------------------------------
@rule("mod.motion.max30102_vdd_1v8")
def max30102_vdd_1v8(ctx: Ctx) -> list[Finding]:
    rid = "mod.motion.max30102_vdd_1v8"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id not in ("max30102", "max30101"):  # same VDD/VLED+ data
            continue
        spec = _spec(inst, "VDD")
        lo, hi, absmax = (ctx.fv(spec.get(k), inst) for k in ("min", "max", "abs_max"))
        net = ctx.net_of(inst, "VDD")
        v = ctx.volts(net)
        sid = ctx.src(inst, spec.get("abs_max"))
        if lo is None or hi is None or absmax is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: no VDD range in the module data.",
                               [inst.ref]))
            continue
        rng = f"{fmt(lo, 'V')}–{fmt(hi, 'V')}"
        if v is None:
            where = "is not connected" if net is None else f"is on {net} (voltage unknown)"
            out.append(Finding(rid, "not_checked", None,
                               f"{ctx.label(inst)}: VDD {where}; it needs a 1.8 V supply ({rng}).", [inst.ref]))
            continue
        led_net = ctx.net_of(inst, "VLED+")
        led = _spec(inst, "VLED+")
        led_lo, led_hi = ctx.fv(led.get("min"), inst), ctx.fv(led.get("max"), inst)
        led_rng = f"{fmt(led_lo, 'V')}–{fmt(led_hi, 'V')}" if led_lo is not None and led_hi is not None else None
        led_txt = f"; only VLED+ takes {led_rng}" if led_rng else ""
        if v > absmax + _EPS:
            out.append(_covers(ctx.finding(
                rid, "failed", "danger",
                f"{ctx.label(inst)}: VDD on {net} = {fmt(v, 'V')} exceeds the absolute maximum {fmt(absmax, 'V')}"
                f"{_page(spec.get('abs_max'))}. VDD needs its own 1.8 V supply ({rng}){led_txt}.",
                inst, source_id=sid, supply=True), _COVERS_SUPPLY))
        elif v > hi + _EPS or v < lo - _EPS:
            out.append(_covers(ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(inst)}: VDD on {net} = {fmt(v, 'V')} is outside {rng}{_page(spec.get('max'))}.",
                inst, source_id=ctx.src(inst, spec.get("max")), supply=True), _COVERS_SUPPLY))
        elif led_net is not None and led_net == net:
            out.append(_covers(ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(inst)}: VDD and VLED+ share {net} = {fmt(v, 'V')}; VDD needs {rng}"
                f"{f', VLED+ {led_rng}' if led_rng else ''}.",
                inst, source_id=sid, supply=True), _COVERS_SUPPLY))
        else:
            out.append(Finding(rid, "passed", None,
                               f"{ctx.label(inst)}: VDD on {net} = {fmt(v, 'V')} within {rng}.", [inst.ref],
                               [sid] if sid else []))
    return out


# --- ADXL345 -------------------------------------------------------------------------------------------------------
@rule("mod.motion.adxl345_cs_high_i2c")
def adxl345_cs_high_i2c(ctx: Ctx) -> list[Finding]:
    rid = "mod.motion.adxl345_cs_high_i2c"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != "adxl345" or not _on_i2c(ctx, inst):
            continue
        sid = ctx.src(inst)
        cs = ctx.net_of(inst, "CS")
        vio_net = ctx.net_of(inst, "VDDIO")
        vio = ctx.volts(vio_net)
        cite = "CS must be tied high to VDD I/O for I²C (datasheet p. 14)"
        if cs is None:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{ctx.label(inst)}: CS is not connected. {cite}; with CS floating there is no "
                                   f"default mode and the part may not answer.", inst, source_id=sid))
            continue
        if vio_net is not None and cs == vio_net:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: CS on {cs} (VDD I/O), I²C mode.",
                               [inst.ref], [sid] if sid else []))
            continue
        v_cs = ctx.volts(cs)
        net = ctx.nets.get(cs) or {}
        if v_cs is None and net.get("gpios"):
            out.append(ctx.finding(rid, "failed", "info",
                                   f"{ctx.label(inst)}: CS on GPIO net {cs}. {cite}: drive it high before the "
                                   f"first I²C transfer.", inst, source_id=sid))
            continue
        if vio is None:
            out.append(Finding(rid, "not_checked", None,
                               f"{ctx.label(inst)}: CS on {cs}, VDD I/O voltage unknown.", [inst.ref]))
            continue
        if v_cs is not None and abs(v_cs - vio) < _EPS:
            out.append(Finding(rid, "passed", None,
                               f"{ctx.label(inst)}: CS on {cs} = {fmt(v_cs, 'V')} (VDD I/O level), I²C mode.",
                               [inst.ref], [sid] if sid else []))
            continue
        level = "unknown voltage" if v_cs is None else fmt(v_cs, "V")
        out.append(ctx.finding(rid, "failed", "caution",
                               f"{ctx.label(inst)}: CS on {cs} ({level}), VDD I/O is {fmt(vio, 'V')}. {cite}; "
                               f"CS low selects SPI.", inst, source_id=sid))
    return out


# --- BNO055 --------------------------------------------------------------------------------------------------------
def _stretch_note(inst: Instance) -> Mapping[str, Any] | None:
    for n in inst.module.get("notes") or []:
        if isinstance(n, Mapping) and n.get("verified") is True and "clock stretching" in str(n.get("text", "")):
            return n
    return None


@rule("mod.motion.bno055_clock_stretch")
def bno055_clock_stretch(ctx: Ctx) -> list[Finding]:
    rid = "mod.motion.bno055_clock_stretch"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != "bno055" or not _on_i2c(ctx, inst):
            continue
        note = _stretch_note(inst)
        if note is None:
            continue
        bus = ctx.placement[inst.ref][0]
        out.append(ctx.finding(
            rid, "failed", "info",
            f"{ctx.label(inst)} on {bus}: the BNO055 stretches SCL{_page(note)}. Give the {ctx.chip} I²C driver a "
            f"timeout long enough for clock stretching, or use the UART interface (PS1 high).",
            inst, source_id=ctx.src(inst, note), chip_fact=False))
    return out
