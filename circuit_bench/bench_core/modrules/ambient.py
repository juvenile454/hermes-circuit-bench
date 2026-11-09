"""Family rules ``ambient``: 1-Wire and ambient sensors.

- ``mod.ambient.ds18b20_pullup``: every 1-Wire net with a DS18B20 needs one external pull-up (Figure 6/7 show
  4.7 kΩ, p. 10 "approximately 5 kΩ") to a pull-up supply VPU of 3.0–5.5 V (local power: VPU ≤ VDD). A resistor
  part between the DQ net and a rail, or ``facts.pullups`` on a DS18B20 of that net, counts. A failed finding
  supersedes ``mod.required_parts`` on the same parts (the generic pull-up requirement; one cause, one warning).
- ``mod.ambient.ds18b20_parasite``: VDD on GND = parasite power (p. 4/7): hint on the strong pull-up the datasheet
  requires during conversions and EEPROM copies (MOSFET to the rail, Figure 6) and the +100 °C limit. VDD on a rail
  between 0 V and 3.0 V is below the local-power range (``mod.supply_range`` cannot check that minimum, because
  VDD = 0 V is a valid mode).
- ``mod.ambient.scd4x_peak``: the SCD4x peak supply current (205 mA at 3.3 V, 137 mA at 5 V) against the rail
  limit (options.rail_limits or the board value); without a limit a hint with the ripple limit (30 mV p-p).

Datasheet values used in code (quotes are lines of tests/corpus/excerpts/mod-ambient-*.txt; tests/test_mod_ambient.py
checks that they are there): see ``_DS18B20_*`` and ``_SCD4X_*``.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule

_EPS = 1e-9
_RESISTOR_KINDS = frozenset({"resistor", "res", "r"})
_SWITCH_KINDS = frozenset({"mosfet", "pmos", "nmos", "transistor", "pnp", "npn"})
_NO_FACT = frozenset({"none", "unknown", ""})
_COVERS_REQUIRED = ("mod.required_parts",)


def _covers(f: Finding, rids: tuple[str, ...]) -> Finding:
    """Mark a failed finding as covering the generic rules ``rids`` on its refs (modcheck.Finding.supersedes)."""
    f.supersedes = rids
    return f

# DS18B20, mod-ambient-ds18b20-ds (19-7487 Rev 6)
_DS18B20_SRC = "mod-ambient-ds18b20-ds"
_DS18B20_VPU_MIN = 3.0  # p. 2 "Pullup Supply Voltage VPU" / "+3.0 +5.5" (parasite) / "Local power +3.0 VDD"
_DS18B20_VPU_MAX = 5.5  # p. 2, same rows (parasite power)
_DS18B20_VDD_MIN = 3.0  # p. 2 "Supply Voltage VDD Local power (Note 1) +3.0 +5.5 V"
_DS18B20_VDD_MAX = 5.5  # same row
_DS18B20_QUOTES = {
    2: ("Pullup Supply Voltage VPU", "+3.0 +5.5", "Local power +3.0 VDD",
        "Supply Voltage VDD Local power (Note 1) +3.0 +5.5 V"),
    3: ("12-bit resolution 750",),
    7: ("VDD pin must be connected to ground.", "current can be as high as 1.5mA. This current can cause", "current, it is necessary to provide a strong pullup on the",
        "EEPROM. This can be accomplished by using a MOSFET", "10µs (max) after a Convert T [44h] or Copy Scratchpad",
        "peratures above +100°C since the DS18B20 may not be"),
    10: ("The 1-Wire bus requires an external pullup resistor of",),
}

# SCD4x, mod-ambient-scd4x-ds (Version 1.3)
_SCD4X_SRC = "mod-ambient-scd4x-ds"
_SCD4X_PEAK_5V = 0.137  # p. 4 "Peak supply current7 Ipeak VDD = 3.3 V  175 205 mA VDD = 5 V  115 137 mA"
_SCD4X_RIPPLE = 0.030  # p. 4 "Voltage ripple peak to peak VRPP    30  mV"
_SCD4X_QUOTES = {
    4: ("Peak supply current7 Ipeak VDD = 3.3 V  175 205 mA VDD = 5 V  115 137 mA",
        "Voltage ripple peak to peak VRPP    30  mV", "7 Power supply should be designed with respect to peak current."),
    5: ("(preferably a low-dropout regulator, LDO, with output ripple of less than 30 mV p-p)",),
}
QUOTES = {_DS18B20_SRC: _DS18B20_QUOTES, _SCD4X_SRC: _SCD4X_QUOTES}  # for the tests


def _part_nets(ctx: Ctx) -> dict[str, dict[str, str]]:
    """ref -> {pin: net} of every part on a net (module and plain parts, as the engine resolved them)."""
    out: dict[str, dict[str, str]] = {}
    for net, info in ctx.nets.items():
        for ref, pin in info.get("pins", []):
            out.setdefault(ref, {})[pin] = net
    return out


def _kind(part: Mapping[str, Any]) -> str:
    k = part.get("kind")
    return k.strip().lower() if isinstance(k, str) else ""


def _req(inst: Instance, code: str, pin: str) -> Mapping[str, Any] | None:
    for r in inst.module.get("requires") or []:
        if isinstance(r, Mapping) and r.get("code") == code and pin in (r.get("pins") or []):
            return r
    return None


def _ds18b20s(ctx: Ctx) -> list[Instance]:
    return [i for i in ctx.instances if i.module_id == "ds18b20"]


def _dq_groups(ctx: Ctx, insts: list[Instance]) -> tuple[dict[str, list[Instance]], list[Instance]]:
    """{DQ net: instances} and the instances with an open DQ."""
    groups: dict[str, list[Instance]] = {}
    open_dq = []
    for inst in insts:
        dq = ctx.pins_with(inst, "onewire")
        net = ctx.net_of(inst, dq[0]) if dq else None
        if net is None:
            open_dq.append(inst)
        else:
            groups.setdefault(net, []).append(inst)
    return groups, open_dq


def _local_vdd(ctx: Ctx, insts: list[Instance]) -> float | None:
    """Lowest VDD rail of the locally powered DS18B20 of one net (None: none is locally powered or unknown)."""
    vs = [v for i in insts if (v := ctx.volts(ctx.net_of(i, "VDD"))) is not None and v > _EPS]
    return min(vs) if vs else None


def _labels(insts: list[Instance]) -> str:
    return ", ".join(i.ref for i in insts) + f" ({insts[0].module_id})"


@rule("mod.ambient.ds18b20_pullup")
def ds18b20_pullup(ctx: Ctx) -> list[Finding]:
    rid = "mod.ambient.ds18b20_pullup"
    insts = _ds18b20s(ctx)
    if not insts:
        return []
    groups, open_dq = _dq_groups(ctx, insts)
    out = [Finding(rid, "not_checked", None, f"{_labels([i])}: DQ is not connected, pull-up not checked.", [i.ref])
           for i in open_dq]
    nets_of = _part_nets(ctx)
    for net, members in groups.items():
        req = _req(members[0], "pullup", "DQ") or {}
        value = req.get("value", "4k7")
        page = req.get("page", 7)
        # resistor parts between the DQ net and a rail above 0 V
        pulls: list[tuple[str, str, float | None, str]] = []  # (ref, value, rail volts, rail net)
        for p in ctx.parts:
            ref = p.get("ref")
            if _kind(p) not in _RESISTOR_KINDS or not isinstance(ref, str):
                continue
            pins = nets_of.get(ref, {})
            if net not in pins.values():
                continue
            others = [n for n in pins.values() if n != net]
            for other in others:
                if ctx.nets.get(other, {}).get("gpios"):
                    continue  # a resistor to an ESP pin is a series resistor, not a pull-up
                v = ctx.volts(other)
                if v is None or v > _EPS:  # GND would be a pull-down; unknown nets: report as unknown rail
                    pulls.append((ref, str(p.get("value") or "?"), v, other))
                    break
        fact_insts = [i for i in members if str((i.facts or {}).get("pullups", "")).strip().lower() not in _NO_FACT]
        for i in fact_insts:
            to = (i.facts or {}).get("pullups_to")
            to_net = to if isinstance(to, str) and to else None
            pulls.append((f"{i.ref} (facts)", str(i.facts["pullups"]), ctx.volts(to_net), to_net or "unknown"))
        who = f"{_labels(members)} DQ on net {net}"
        if not pulls:
            modes = set(ctx.nets.get(net, {}).get("modes", []))
            extra = (" The ESP's internal pull-up (in_pullup) is not that resistor." if "in_pullup" in modes else "")
            out.append(_covers(ctx.finding(
                rid, "failed", "caution",
                f"{who} has no pull-up: the 1-Wire bus needs one external {value} pull-up to VPU "
                f"({fmt(_DS18B20_VPU_MIN, 'V')}–{fmt(_DS18B20_VPU_MAX, 'V')}, datasheet p. {page}; p. 10: about "
                f"5 kΩ). Add a resistor from {net} to the 3V3 rail, or set facts.pullups if the probe board has "
                f"one.{extra}", members, source_id=_DS18B20_SRC, chip_fact=False), _COVERS_REQUIRED))
            continue
        txt = "; ".join(f"{ref} {val} to {rail}" for ref, val, _, rail in pulls)
        lows = [(ref, v) for ref, _, v, _ in pulls if v is not None and v < _DS18B20_VPU_MIN - _EPS]
        vdd = _local_vdd(ctx, members)
        highs = [(ref, v) for ref, _, v, _ in pulls if v is not None and vdd is not None and v > vdd + _EPS]
        unknown = [ref for ref, _, v, _ in pulls if v is None]
        if lows:
            out.append(_covers(ctx.finding(
                rid, "failed", "caution",
                f"{who}: pull-up ({txt}) to {fmt(lows[0][1], 'V')} is below the pull-up supply minimum VPU "
                f"{fmt(_DS18B20_VPU_MIN, 'V')} (datasheet p. 2).", members, source_id=_DS18B20_SRC,
                chip_fact=False), _COVERS_REQUIRED))
        elif highs:
            out.append(_covers(ctx.finding(
                rid, "failed", "caution",
                f"{who}: pull-up ({txt}) to {fmt(highs[0][1], 'V')} is above VDD {fmt(vdd, 'V')}; with local power "
                f"VPU must be {fmt(_DS18B20_VPU_MIN, 'V')} to VDD (datasheet p. 2).", members,
                source_id=_DS18B20_SRC, chip_fact=False), _COVERS_REQUIRED))
        elif unknown:
            out.append(Finding(rid, "not_checked", "info",
                               f"{who}: pull-up found ({txt}), but the voltage of its rail is unknown (name it in "
                               "options.rails).", [i.ref for i in members], [_DS18B20_SRC]))
        else:
            n = len(pulls)
            more = f" {n} pull-ups in parallel: the datasheet shows one per bus." if n > 1 else ""
            out.append(Finding(rid, "passed", None, f"{who}: pull-up {txt} (datasheet: {value}).{more}",
                               [i.ref for i in members], [_DS18B20_SRC]))
    return out


@rule("mod.ambient.ds18b20_parasite")
def ds18b20_parasite(ctx: Ctx) -> list[Finding]:
    rid = "mod.ambient.ds18b20_parasite"
    out: list[Finding] = []
    nets_of = _part_nets(ctx)
    for inst in _ds18b20s(ctx):
        net = ctx.net_of(inst, "VDD")
        if net is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: VDD is not connected (GND for "
                               "parasite power, 3.0–5.5 V for local power).", [inst.ref]))
            continue
        v = ctx.volts(net)
        if v is None:
            out.append(Finding(rid, "not_checked", "info", f"{ctx.label(inst)} VDD on net {net} with unknown "
                               "voltage: power mode not checked.", [inst.ref]))
            continue
        if v <= _EPS:
            dq = ctx.net_of(inst, "DQ")
            switch = sorted(ref for ref, pins in nets_of.items() if dq and dq in pins.values()
                            and any(_kind(p) in _SWITCH_KINDS for p in ctx.parts if p.get("ref") == ref))
            how = (f"{', '.join(switch)} on the bus can be that strong pull-up" if switch else
                   "use a MOSFET to the rail (datasheet Figure 6) or let the firmware drive DQ high (push-pull) "
                   "during the conversion")
            out.append(ctx.finding(
                rid, "failed", "info",
                f"{ctx.label(inst)}: VDD on GND = parasite power. During temperature conversions and EEPROM copies "
                f"(up to 1.5 mA) the bus needs a strong pull-up within 10 µs of Convert T, held for the conversion "
                f"(750 ms at 12 bit); the resistor alone is not enough: {how}. Pull-up supply "
                f"{fmt(_DS18B20_VPU_MIN, 'V')}–{fmt(_DS18B20_VPU_MAX, 'V')}; not recommended above +100 °C "
                f"(datasheet p. 2, 7).", inst, source_id=_DS18B20_SRC, chip_fact=False))
        elif v < _DS18B20_VDD_MIN - _EPS:
            out.append(ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(inst)} VDD on {net} = {fmt(v, 'V')} is below the local-power range "
                f"{fmt(_DS18B20_VDD_MIN, 'V')}–{fmt(_DS18B20_VDD_MAX, 'V')}; tie VDD to GND for parasite power or use 3.3 V "
                f"(datasheet p. 2).", inst, source_id=_DS18B20_SRC, supply=True))
        else:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: local power, VDD on {net} = "
                               f"{fmt(v, 'V')}.", [inst.ref], [_DS18B20_SRC]))
    return out


def _scd4x_peak(ctx: Ctx, inst: Instance, v: float) -> tuple[float | None, str]:
    """(peak current per device, condition text) for a VDD rail voltage; values only at 3.3 V and 5 V."""
    f = (inst.module.get("current") or {}).get("peak")
    p33 = ctx.fv(f, inst)
    if abs(v - 5.0) < _EPS:
        return _SCD4X_PEAK_5V, "at 5 V"
    if abs(v - 3.3) < _EPS:
        return p33, "at 3.3 V"
    return p33, f"the 3.3 V value; the datasheet gives peaks at 3.3 V and 5 V only, not at {fmt(v, 'V')}"


@rule("mod.ambient.scd4x_peak")
def scd4x_peak(ctx: Ctx) -> list[Finding]:
    rid = "mod.ambient.scd4x_peak"
    out: list[Finding] = []
    insts = [i for i in ctx.instances if i.module_id == "scd4x"]
    by_net: dict[str, list[Instance]] = {}
    for inst in insts:
        net = ctx.net_of(inst, "VDD")
        if net is None or ctx.volts(net) is None:
            out.append(Finding(rid, "not_checked", None if net is None else "info",
                               f"{ctx.label(inst)}: VDD " + ("not connected" if net is None else
                                                             f"on net {net} with unknown voltage")
                               + ", peak current not checked.", [inst.ref]))
            continue
        by_net.setdefault(net, []).append(inst)
    sums = {e["net"]: e for e in ctx.rail_sums}
    for net, members in by_net.items():
        v = ctx.volts(net) or 0.0
        peak, cond = _scd4x_peak(ctx, members[0], v)
        if peak is None:
            out.append(Finding(rid, "not_checked", None, f"{_labels(members)}: no peak current in the data.",
                               [i.ref for i in members]))
            continue
        qty = sum(i.qty for i in members)
        own = peak * qty
        e = sums.get(net, {})
        f33 = ctx.fv((members[0].module.get("current") or {}).get("peak"), members[0]) or 0.0
        rail_peak = (e.get("i_peak") or 0.0) - f33 * qty + own  # the engine sums the 3.3 V value; use ours
        limit = e.get("limit")
        who = f"{_labels(members)} on {net} = {fmt(v, 'V')}"
        tail = (f" Keep the ripple below {fmt(_SCD4X_RIPPLE, 'V')} p-p (a low-noise LDO sized for the peaks; "
                "datasheet p. 4, 5).")
        head = f"{who}: peak supply current up to {fmt(own, 'A')} ({cond})"
        if limit is None:
            out.append(ctx.finding(
                rid, "failed", "info",
                f"{head}; module peaks on {net} sum to {fmt(rail_peak, 'A')}. No current limit is known for "
                f"{net} (set options.rail_limits).{tail}", members, source_id=_SCD4X_SRC, supply=True))
        elif rail_peak > limit + _EPS:
            src = e.get("limit_source")
            out.append(ctx.finding(
                rid, "failed", "caution",
                f"{head}; module peaks on {net} sum to {fmt(rail_peak, 'A')}, above the rail limit {fmt(limit, 'A')}"
                f" ({'user' if src == 'user' else 'board'}): the rail can sag and reset the sensor or the ESP.{tail}",
                members, source_id=_SCD4X_SRC, supply=True))
        else:
            out.append(Finding(rid, "passed", None,
                               f"{head}; module peaks on {net} sum to {fmt(rail_peak, 'A')} within the limit "
                               f"{fmt(limit, 'A')}.{tail}", [i.ref for i in members], [_SCD4X_SRC]))
    return out
