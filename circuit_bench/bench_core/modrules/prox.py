"""Family rules ``prox``: ToF, IR receiver, ultrasonic, Hall and touch parts.

- ``mod.prox.vl53_xshut``: several VL53L0X/VL53L1X that can see each other on one I²C bus segment all start at
  0x29 (ST: 8-bit 0x52, "Programmable I²C address" by software only). Re-addressing them one by one needs each
  sensor's XSHUT on its own net driven by an ESP output. More than one sensor without such a net -> failed: danger
  when the project already gives them distinct addresses (looks fine, cannot work), else caution (the generic
  ``mod.address_conflict`` already reports the clash). Exactly one sensor without XSHUT is a valid sequence (hold the
  others in reset, re-address that one first) -> passed with that hint. The finding supersedes ``mod.address_conflict``
  on the group: failed -> the clash is one warning with the remedy; passed -> the 0x29 start-up clash drops to info,
  but only when no other device on the bus answers at 0x29 (that conflict stays a warning).
- ``mod.prox.tsop_vs_5v``: TSOP38238 OUT is pulled up to VS by an internal 30 kΩ (Vishay block diagram, p. 1). VS
  above the ESP's input maximum with OUT on an ESP input -> caution (the 30 kΩ limits the current, but the pin sees
  more than its rating). The generic level rule cannot see an internal pull-up to the part's own supply.
- ``mod.prox.ttp223_vs_5v``: TTP223 Q is a CMOS push-pull output (Tontek p. 2): high level = VDD. VDD above the ESP
  input maximum with Q on an ESP input -> danger, capped to info by the source class (Tontek publishes only a
  preliminary sheet: class B). Supersedes ``mod.level_out`` on the part (one warning with the remedy).
- ``mod.prox.hcsr04_echo``: HC-SR04 Echo on an ESP input with VCC above the ESP input maximum -> caution, capped
  to info by the source class (class B vendor sheet: "TTL" output, 5 V supply; no manufacturer data). A level shifter
  (``facts.level_shifter``) or another part on the Echo net (divider) -> not_checked with a hint to confirm the
  level. The failed finding supersedes ``mod.level_out`` on the part (one warning: "Echo is 5 V -> use a divider").
Messages English, values via ``fmt``; the severity cap comes from ``ctx.finding``.
"""
from __future__ import annotations

from . import modcheck

Ctx, Finding, Instance, fmt, rule = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule

VL53 = ("vl53l0x", "vl53l1x")
_IN_MODES = ("in", "in_pullup", "in_pulldown")
_EPS = 1e-9
_COVERS_CONFLICT = ("mod.address_conflict",)
_COVERS_LEVEL = ("mod.level_out",)


def _out_gpio(ctx: Ctx, net: str | None) -> bool:
    """The net carries an ESP output (``out`` assignment) and is not a rail."""
    if net is None or ctx.volts(net) is not None:
        return False
    return "out" in (ctx.nets.get(net) or {}).get("modes", [])


def _in_gpios(ctx: Ctx, net: str | None) -> list[int]:
    """GPIOs of ESP input assignments on a signal net (not a rail)."""
    if net is None or ctx.volts(net) is not None:
        return []
    n = ctx.nets.get(net) or {}
    return [g for g, m in zip(n.get("gpios", []), n.get("modes", []), strict=False) if m in _IN_MODES]


def _gpio_text(gpios: list[int]) -> str:
    return ", ".join(f"GPIO{g}" for g in gpios)


def _clusters(ctx: Ctx, insts: list[Instance]) -> list[list[Instance]]:
    """Groups of sensors that can see each other (same bus, visible segments), transitively joined."""
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


@rule("mod.prox.vl53_xshut")
def vl53_xshut(ctx: Ctx) -> list[Finding]:
    rid = "mod.prox.vl53_xshut"
    insts = [i for i in ctx.instances if i.module_id in VL53 and i.ref in ctx.placement]
    out: list[Finding] = []
    for group in _clusters(ctx, insts):
        nets = {i.ref: ctx.net_of(i, "XSHUT") for i in group}
        counts: dict[str, int] = {}
        for n in nets.values():
            if n is not None:
                counts[n] = counts.get(n, 0) + 1
        own = {r: n is not None and counts[n] == 1 and _out_gpio(ctx, n) for r, n in nets.items()}
        lacking = [i for i in group if not own[i.ref]]
        bus = ctx.placement[group[0].ref][0]
        names = ", ".join(f"{i.ref} ({i.module_id})" for i in group)
        if len(lacking) <= 1:
            hint = ("" if not lacking else
                    f" {lacking[0].ref} has no own XSHUT GPIO: keep all others in reset (XSHUT low) and re-address "
                    f"{lacking[0].ref} first.")
            refs = {i.ref for i in group}
            others = [i for i in ctx.instances if i.ref not in refs and i.ref in ctx.placement
                      and i.address == "0x29" and ctx.placement[i.ref][0] == bus
                      and ctx.visible(ctx.placement[i.ref][1], ctx.placement[group[0].ref][1])]
            out.append(Finding(rid, "passed", None,
                               f"{names} on bus {bus}: each sensor can be woken alone to set its address.{hint}",
                               [i.ref for i in group], [ctx.src(i) for i in group if ctx.src(i)],
                               () if others else _COVERS_CONFLICT))
            continue
        addrs = [i.address for i in group]
        distinct = all(addrs) and len(set(addrs)) == len(addrs)
        sev = "danger" if distinct else "caution"
        why = []
        for i in lacking:
            n = nets[i.ref]
            if n is None:
                why.append(f"{i.ref} XSHUT open")
            elif counts[n] > 1:
                why.append(f"{i.ref} XSHUT shares net {n}")
            else:
                why.append(f"{i.ref} XSHUT on {n} (no ESP output)")
        tail = (" The addresses set in the project can only be programmed if each sensor is woken alone."
                if distinct else "")
        out.append(ctx.finding(
            rid, "failed", sev,
            f"{names} on bus {bus} all start at 0x29; {'; '.join(why)}. Give each sensor (all but one at least) its "
            f"own XSHUT net on an ESP output and re-address them one by one at start-up.{tail}",
            group, source_id=[ctx.src(i) for i in group], chip_fact=False))
        out[-1].supersedes = _COVERS_CONFLICT
    return out


def _level_rule(ctx: Ctx, rid: str, module_id: str, supply: str, output: str, sev: str, what: str,
                fix: str, covers: tuple[str, ...] = ()) -> list[Finding]:
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != module_id:
            continue
        gpios = _in_gpios(ctx, ctx.net_of(inst, output))
        if not gpios:
            continue  # output not read by the ESP: nothing to check
        v = ctx.volts(ctx.net_of(inst, supply))
        if ctx.esp is None or ctx.esp.get("v_in_max") is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: no ESP input limit for {ctx.chip}.",
                               [inst.ref]))
            continue
        vmax = float(ctx.esp["v_in_max"])
        esp_src = (ctx.esp.get("source_ids") or [None])[0]
        if v is None:
            out.append(Finding(rid, "not_checked", "info",
                               f"{ctx.label(inst)} {supply} on a net with unknown voltage: {output} level on "
                               f"{_gpio_text(gpios)} not checked.", [inst.ref]))
            continue
        if (inst.facts or {}).get("level_shifter") is True:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: level shifter on {output} (facts).",
                               [inst.ref]))
            continue
        if v <= vmax + _EPS:
            out.append(Finding(rid, "passed", None,
                               f"{ctx.label(inst)} {supply} = {fmt(v, 'V')}: {output} high level stays within the ESP "
                               f"input maximum {fmt(vmax, 'V')}.", [inst.ref], [ctx.src(inst)]))
            continue
        src = [s for s in (ctx.src(inst), esp_src) if s]
        out.append(ctx.finding(
            rid, "failed", sev,
            f"{ctx.label(inst)} {supply} = {fmt(v, 'V')}: {what} so {_gpio_text(gpios)} sees about {fmt(v, 'V')}, "
            f"above the ESP input maximum {fmt(vmax, 'V')}. {fix}",
            inst, source_id=ctx.src(inst), source_ids=src))
        out[-1].supersedes = covers
    return out


@rule("mod.prox.tsop_vs_5v")
def tsop_vs_5v(ctx: Ctx) -> list[Finding]:
    return _level_rule(ctx, "mod.prox.tsop_vs_5v", "tsop38238", "VS", "OUT", "caution",
                       "OUT is pulled up to VS by the internal 30 kΩ,",
                       "Supply the TSOP from 3.3 V (VS 2.0–5.5 V) or divide/clamp OUT.")


@rule("mod.prox.ttp223_vs_5v")
def ttp223_vs_5v(ctx: Ctx) -> list[Finding]:
    return _level_rule(ctx, "mod.prox.ttp223_vs_5v", "ttp223", "VDD", "Q", "danger",
                       "Q is a CMOS push-pull output that drives VDD,",
                       "Power the TTP223 board from 3.3 V (VDD 2.0–5.5 V) or add a level shifter.", _COVERS_LEVEL)


def _other_parts_on(ctx: Ctx, net: str | None) -> list[str]:
    mods = {i.ref for i in ctx.instances}
    return sorted({ref for ref, _ in (ctx.nets.get(net) or {}).get("pins", []) if ref not in mods}) if net else []


@rule("mod.prox.hcsr04_echo")
def hcsr04_echo(ctx: Ctx) -> list[Finding]:
    rid = "mod.prox.hcsr04_echo"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != "hcsr04":
            continue
        net = ctx.net_of(inst, "Echo")
        gpios = _in_gpios(ctx, net)
        if not gpios:
            continue
        v = ctx.volts(ctx.net_of(inst, "VCC"))
        vmax = (ctx.esp or {}).get("v_in_max")
        if v is None or vmax is None:
            out.append(Finding(rid, "not_checked", "info",
                               f"{ctx.label(inst)}: VCC voltage or ESP input limit unknown, Echo level on "
                               f"{_gpio_text(gpios)} not checked.", [inst.ref]))
            continue
        if v <= float(vmax) + _EPS:
            out.append(Finding(rid, "passed", None,
                               f"{ctx.label(inst)} VCC = {fmt(v, 'V')}: Echo stays within {fmt(float(vmax), 'V')} "
                               "(the vendor sheet specifies 5 V; check that the module works at this voltage).",
                               [inst.ref], [ctx.src(inst)]))
            continue
        others = _other_parts_on(ctx, net)
        if (inst.facts or {}).get("level_shifter") is True or others:
            what = "a level shifter (facts)" if not others else f"{', '.join(others)} on the Echo net"
            out.append(Finding(rid, "not_checked", "info",
                               f"{ctx.label(inst)} VCC = {fmt(v, 'V')} with {what}: confirm that {_gpio_text(gpios)} "
                               f"sees at most {fmt(float(vmax), 'V')}.", [inst.ref], [ctx.src(inst)]))
            continue
        out.append(ctx.finding(  # caution as asked; the class B cap lowers it to info and says "Unverified"
            rid, "failed", "caution",
            f"{ctx.label(inst)} VCC = {fmt(v, 'V')}: Echo is {fmt(v, 'V')} high on {_gpio_text(gpios)}, above the ESP "
            f"input maximum {fmt(float(vmax), 'V')}: use a divider (e.g. 1 kΩ / 2 kΩ, calc divider) or a level "
            "shifter.", inst, source_id=ctx.src(inst)))
        out[-1].supersedes = _COVERS_LEVEL
    return out
