"""Family rules ``powermon``: INA219/INA226/INA260/INA3221 and ACS712.

- ``mod.powermon.acs712_needs_5v_divider``: ACS712 VIOUT straight on an ESP GPIO. VIOUT = VCC/2 + Sens · IP
  (ratiometric, Allegro ACS712 datasheet p. 5, p. 6, p. 10); at VCC = 5 V the x20A/x30A output reaches 4.5 V at the
  rated current, above the ESP ``v_in_max`` (data/electrical) -> danger (capped by the source class).
  Without a variant the worst variant counts. VIOUT on a net without a GPIO (a divider in between) -> not_checked
  with a pointer to ``bench_calc current_sense``.
- ``mod.powermon.ina_bus_voltage``: the rail voltage on the INA's IN+/IN-/VBUS (INA3221: IN±1..3, VPU) against the
  bus range (INA219/INA3221 26 V, INA226/INA260 36 V operating, 40 V absolute maximum) from the datasheets; rails
  come from options.rails (``set_rails``). The numbers live in calcs/ina_shunt.py (``BUS``) with page and quote.
"""
from __future__ import annotations

import importlib
import re
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = (
    modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule)

_PKG = __name__.rsplit(".", 2)[0]  # bench_core under whatever package name it is loaded
ina = importlib.import_module(_PKG + ".calcs.ina_shunt")
acs = importlib.import_module(_PKG + ".calcs.current_sense")

_EPS = 1e-9
_GPIO = re.compile(r"^GPIO\d+$")
DIVIDER_RULE = "mod.powermon.acs712_needs_5v_divider"
BUS_RULE = "mod.powermon.ina_bus_voltage"


def _gpio_net(ctx: Ctx, net: str) -> bool:
    return bool((ctx.nets.get(net) or {}).get("gpios")) or bool(_GPIO.match(net))


def _vout_max(variant: str, vcc: float) -> float:
    """VIOUT at +rated current of a variant (ratiometric: Sens × VCC/5 V)."""
    sens = float(acs.FACTS[f"sens_{variant}"]["value"]) * vcc / acs.VCC_REF
    return float(acs.FACTS["vq_ratio"]["value"]) * vcc + sens * float(acs.FACTS[f"range_{variant}"]["value"])


@rule(DIVIDER_RULE)
def acs712_needs_5v_divider(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != "acs712":
            continue
        net = ctx.net_of(inst, "VIOUT")
        if net is None:
            continue
        sid = ctx.src(inst)
        if not _gpio_net(ctx, net):
            out.append(ctx.finding(DIVIDER_RULE, "not_checked", "info",
                                   f"{ctx.label(inst)} VIOUT on {net} (no GPIO): a divider is assumed, not verified; "
                                   "size it with bench_calc current_sense.", inst, source_id=sid))
            continue
        vcc = ctx.volts(ctx.net_of(inst, "VCC"))
        limit = (ctx.esp or {}).get("v_in_max")
        if vcc is None or limit is None:
            why = "VCC is not on a known rail" if vcc is None else f"no ESP input limit for {ctx.chip}"
            out.append(ctx.finding(DIVIDER_RULE, "not_checked", "info",
                                   f"{ctx.label(inst)} VIOUT on {net}: {why}.", inst, source_id=sid))
            continue
        variants = [inst.variant] if inst.variant in acs.VARIANTS else list(acs.VARIANTS)
        worst = max(variants, key=lambda v: _vout_max(v, vcc))
        v_hi = _vout_max(worst, vcc)
        which = f"x{worst.upper()}" if inst.variant in acs.VARIANTS else f"x{worst.upper()} (no variant given: worst case)"
        rated = float(acs.FACTS[f"range_{worst}"]["value"])
        esp_src = (ctx.esp or {}).get("source_ids") or []
        srcs = [s for s in [sid, *esp_src] if s]
        if v_hi > limit + _EPS:
            out.append(ctx.finding(
                DIVIDER_RULE, "failed", "danger",
                f"{ctx.label(inst)} {which} at VCC {fmt(vcc, 'V')}: VIOUT reaches {fmt(v_hi, 'V')} at +{fmt(rated, 'A')}"
                f" on {net}, above the {ctx.chip} input limit {fmt(limit, 'V')}. Add a divider (bench_calc "
                "current_sense).", inst, source_id=sid, source_ids=srcs))
        else:
            sens = float(acs.FACTS[f"sens_{worst}"]["value"]) * vcc / acs.VCC_REF
            i_lim = (limit - float(acs.FACTS["vq_ratio"]["value"]) * vcc) / sens
            out.append(ctx.finding(
                DIVIDER_RULE, "passed", None,
                f"{ctx.label(inst)} {which} at VCC {fmt(vcc, 'V')}: VIOUT max {fmt(v_hi, 'V')} at +{fmt(rated, 'A')} "
                f"≤ {fmt(limit, 'V')}; above +{fmt(i_lim, 'A')} it would exceed the limit.", inst, source_id=sid,
                source_ids=srcs))
    return out


@rule(BUS_RULE)
def ina_bus_voltage(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    for inst in ctx.instances:
        spec: dict[str, Any] | None = ina.BUS.get(inst.module_id)
        if spec is None:
            continue
        lim, absmax = float(spec["max"]["value"]), float(spec["abs"]["value"])
        sid = spec["max"]["source_id"]
        known = [(pin, net, ctx.volts(net)) for pin in spec["pins"] if (net := ctx.net_of(inst, pin)) is not None]
        rails = [(pin, net, v) for pin, net, v in known if v is not None]
        if not rails:
            if known:
                out.append(ctx.finding(BUS_RULE, "not_checked", "info",
                                       f"{ctx.label(inst)}: {', '.join(p for p, _, _ in known)} not on a rail with a "
                                       f"voltage; set it with set_rails to check the bus range 0–{fmt(lim, 'V')}.",
                                       inst, source_id=sid))
            continue
        _pin, net, v = max(rails, key=lambda r: r[2])
        pins = ", ".join(p for p, n, _ in rails if n == net)
        if v > absmax + _EPS:
            out.append(ctx.finding(BUS_RULE, "failed", "danger",
                                   f"{ctx.label(inst)} {pins} on {net} = {fmt(v, 'V')} exceeds the absolute maximum "
                                   f"{fmt(absmax, 'V')} (bus range 0–{fmt(lim, 'V')}): the chip can be damaged.",
                                   inst, source_id=sid))
        elif v > lim + _EPS:
            out.append(ctx.finding(BUS_RULE, "failed", "caution",
                                   f"{ctx.label(inst)} {pins} on {net} = {fmt(v, 'V')} is above the bus range "
                                   f"0–{fmt(lim, 'V')} (absolute maximum {fmt(absmax, 'V')}).", inst, source_id=sid))
        else:
            out.append(ctx.finding(BUS_RULE, "passed", None,
                                   f"{ctx.label(inst)} {pins} on {net} = {fmt(v, 'V')} within 0–{fmt(lim, 'V')}.",
                                   inst, source_id=sid))
    return out
