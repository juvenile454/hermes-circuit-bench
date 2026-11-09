"""Family rules ``rtc``: DS3231, DS1307, PCF8563, AT24C32, AT24C256.

- ``mod.rtc.ds1307_vcc_5v``: the DS1307 runs only from VCC 4.5–5.5 V (data sheet p. 2); below 1.25 × VBAT it ends I²C
  access and runs from the backup cell (p. 6). At 3.3 V -> failed/caution. The SDA/SCL pull-up level at 5 V is
  ``mod.level_out``'s job (generic), not this rule's.
- ``mod.rtc.ds3231_vih``: SDA/SCL VIH = 0.7 × VCC (data sheet p. 2). A DS3231 at VCC 5 V needs 3.5 V high, more than
  a bus pulled up to 3.3 V -> failed/caution. Pull-up level: ``facts.pullups_to`` (a rail), else the real pull-ups
  on SDA/SCL (``elec._pullups``: resistors, user facts); unconfirmed board pull-ups (e.g. ZS-042 at 5 V) -> not_checked
  without severity (``mod.level_out`` asks for the voltage); no pull-up at all -> the ESP's internal pull-ups (its
  supply). ``facts.level_shifter`` -> passed. A failed finding supersedes ``mod.level_out`` (same bus, one cause).
- ``mod.rtc.rtc_module_charger``: hint only (unverified, no manufacturer document for the board): ZS-042 boards are
  reported to charge the coin cell from VCC. The DS3231's own fact (VBAT designed for a primary lithium cell, UL
  reverse-charge protection, p. 9) is cited.
All limits come from the catalog entry (data/modules/rtc.json), never from constants in this file.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import elec, modcheck

Ctx, Finding, Instance, fmt, rule = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule

_EPS = 1e-9
# (module id, variant id) of boards that are reported to charge the backup cell; texts stay unverified (class B).
CHARGER_BOARDS: dict[tuple[str, str], str] = {
    ("ds3231", "zs042"): "ZS-042",
}


def _supply_spec(inst: Instance, pin: str) -> Mapping[str, Any]:
    spec = (inst.module.get("supplies") or {}).get(pin)
    return spec if isinstance(spec, Mapping) else {}


@rule("mod.rtc.ds1307_vcc_5v")
def ds1307_vcc_5v(ctx: Ctx) -> list[Finding]:
    rid = "mod.rtc.ds1307_vcc_5v"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != "ds1307":
            continue
        spec = _supply_spec(inst, "VCC")
        lo, hi = ctx.fv(spec.get("min"), inst), ctx.fv(spec.get("max"), inst)
        v = ctx.supply_volts(inst).get("VCC")
        if v is None or lo is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: VCC voltage unknown, 5 V supply not checked.",
                               [inst.ref]))
            continue
        src = ctx.src(inst, spec.get("min"))
        rng = f"{fmt(lo, 'V')}–{fmt(hi, 'V')}" if hi is not None else f"min {fmt(lo, 'V')}"
        if v < lo - _EPS:
            out.append(ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(inst)} on VCC = {fmt(v, 'V')}: the DS1307 needs {rng}. Below 1.25 × VBAT it stops I²C "
                "access and runs from the backup cell, so it will not answer. Power it from 5 V and keep the SDA/SCL "
                f"pull-ups at 3.3 V (VIH {fmt(ctx.level(inst, 'vih'), 'V')}).",
                inst, source_id=src, supply=True))
        else:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)} on VCC = {fmt(v, 'V')}: within the 5 V range {rng}.",
                               [inst.ref], [src] if src else []))
    return out


def _pullup_volts(ctx: Ctx, inst: Instance) -> tuple[float | None, str]:
    """(bus high level, where it comes from); level None when the pull-up voltage is not known for sure.

    Order: ``facts.pullups_to`` of this part; else the real pull-ups on the SDA/SCL nets (``elec._pullups``:
    resistors to a rail, other parts' facts, possible board pull-ups of breakouts); a net with only unconfirmed
    board pull-ups or with pull-ups that disagree -> None (the rule stays silent, mod.level_out asks for the
    voltage). No pull-up at all -> the ESP32's internal pull-ups (its supply); the missing resistor itself is
    mod.required_parts' job."""
    facts = inst.facts or {}
    net = facts.get("pullups_to")
    if isinstance(net, str) and net.strip():
        v = ctx.volts(ctx.net_of(inst, net) or net)
        return v, f"pull-ups on {net}"
    nets = [n for n in (inst.conn.get("SDA"), inst.conn.get("SCL")) if n]
    if not nets:
        return None, "SDA/SCL not connected"
    highs: list[tuple[float, str]] = []
    unknown: list[str] = []
    for n in nets:
        pus = elec._pullups(ctx, n)
        if not pus:
            continue
        v = elec._pullup_volts(ctx, n)
        if v is None:
            unknown += [p["how"] for p in pus]
        else:
            highs.append((v, "; ".join(p["how"] for p in pus)))
    if unknown:
        return None, "; ".join(dict.fromkeys(unknown))
    if highs:
        low = min(v for v, _ in highs)
        return low, "; ".join(dict.fromkeys(h for v, h in highs if v == low))
    vdd = (ctx.esp or {}).get("vdd")
    return (float(vdd) if isinstance(vdd, int | float) else None), "no pull-up part found: the ESP32's internal pull-ups"


@rule("mod.rtc.ds3231_vih")
def ds3231_vih(ctx: Ctx) -> list[Finding]:
    rid = "mod.rtc.ds3231_vih"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != "ds3231":
            continue
        io = inst.module.get("io") if isinstance(inst.module.get("io"), Mapping) else {}
        vcc = ctx.supply_volts(inst).get("VCC")
        vih = ctx.level(inst, "vih")
        if (inst.facts or {}).get("level_shifter") is True:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: level shifter declared (facts.level_shifter).",
                               [inst.ref]))
            continue
        high, origin = _pullup_volts(ctx, inst)
        if vcc is None or vih is None or high is None:
            why = f"pull-up voltage unknown ({origin})" if vcc is not None and vih is not None else \
                "VCC or the I²C pull-up level unknown"
            out.append(Finding(rid, "not_checked", None,
                               f"{ctx.label(inst)}: {why}, SDA/SCL VIH not checked (set facts.pullups_to).",
                               [inst.ref]))
            continue
        src = ctx.src(inst, io.get("vih"))
        if vih > high + _EPS:
            f = ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(inst)} at VCC = {fmt(vcc, 'V')} needs SDA/SCL high ≥ {fmt(vih, 'V')} (0.7 × VCC), but the bus "
                f"is pulled up to {fmt(high, 'V')} ({origin}): reads and writes can fail. Power the DS3231 from 3.3 V "
                "(VCC 2.3–5.5 V) or use a level shifter.",
                inst, source_id=src)
            f.supersedes = ("mod.level_out",)  # one cause on this bus: the pull-up level
            out.append(f)
        else:
            out.append(Finding(rid, "passed", None,
                               f"{ctx.label(inst)}: VIH {fmt(vih, 'V')} at VCC = {fmt(vcc, 'V')} ≤ bus high {fmt(high, 'V')}.",
                               [inst.ref], [src] if src else []))
    return out


@rule("mod.rtc.rtc_module_charger")
def rtc_module_charger(ctx: Ctx) -> list[Finding]:
    rid = "mod.rtc.rtc_module_charger"
    out: list[Finding] = []
    for inst in ctx.instances:
        board = CHARGER_BOARDS.get((inst.module_id, inst.variant or ""))
        if board is None:
            continue
        out.append(ctx.finding(
            rid, "failed", "info",
            f"{ctx.label(inst)}: unverified: {board} boards are reported to charge the coin cell from VCC through a "
            "resistor and diode. The DS3231 VBAT input is meant for a primary lithium cell (UL reverse-charge "
            "protection). With a non-rechargeable CR2032 remove that charge path or fit a rechargeable cell.",
            inst, source_id=ctx.src(inst), chip_fact=False))
    return out
