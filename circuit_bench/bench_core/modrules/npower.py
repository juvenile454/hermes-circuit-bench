"""Family rules ``npower``: what the generic rules and modrules/power.py do not cover for
the TI parts of data/modules/npower.json.

- ``mod.npower.dropout``: an LDO (category ``power.ldo``) whose datasheet names the pins ``IN``/``OUT`` (TLV755P; the
  rule ``mod.power.dropout`` looks for ``VIN``/``VOUT`` and skips it) with IN on a rail of ``options.rails``
  (e.g. VBAT 3.7) and OUT on a known rail: the headroom V_IN − V_OUT against the maximum dropout of the regulator
  record in data/parts/ (``module`` = catalog id) -> caution below it, passed otherwise; no record or OUT unknown ->
  not_checked. Parts with ``VIN``/``VOUT`` pins are left to ``mod.power.dropout`` (no double findings).
- ``mod.npower.power_path_out``: a power-path charger's system output (``OUT_REG``, BQ24074 OUT 4.3–4.5 V regulated,
  datasheet p. 12) on a net with a known voltage outside that window -> failed: danger when the net is lower (the
  charger lifts e.g. the 3V3 rail to 4.4 V, above the ESP's absolute maximum), caution when it is higher (OUT fights
  another source, e.g. tied straight to the 5 V input). OUT on its own net (e.g. VSYS) -> passed.
Rule texts in English; numbers with page in data/parts/power_npower.json and data/modules/npower.json.
"""
from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = (
    modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule)

_PKG = __name__.rsplit(".", 2)[0]  # bench_core under whatever package name it is loaded
parts = importlib.import_module(_PKG + ".parts")

DROPOUT_RULE = "mod.npower.dropout"
PATH_RULE = "mod.npower.power_path_out"
_EPS = 1e-9
# Power-path system output: module id -> (pin, regulation min V, max V, datasheet page). Excerpt line (BQ24074 p. 12):
# "OUT pin voltage regulation (BQ24073, BQ24074) VIN > VOUT + VDO(IN-OUT) 4.3 4.4 4.5".
OUT_REG: dict[str, tuple[str, float, float, int]] = {"bq24074": ("OUT", 4.3, 4.5, 12)}


def _pin_names(inst: Instance) -> set[str]:
    return {str(p.get("name")) for p in inst.module.get("pins") or [] if isinstance(p, Mapping)}


def _ldo_record(inst: Instance) -> dict[str, Any] | None:
    for kind in ("ldo", "ldo_partial"):
        for pid in parts.ids_of(kind):
            rec = parts.find(pid, kind)
            if rec and rec.get("module") == inst.module_id:
                return rec
    return None


@rule(DROPOUT_RULE)
def dropout(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    user_rails = ctx.options.get("rails") if isinstance(ctx.options.get("rails"), Mapping) else {}
    for inst in ctx.instances:
        if inst.module.get("category") != "power.ldo" or not {"IN", "OUT"} <= _pin_names(inst) \
                or "VIN" in _pin_names(inst):
            continue
        vin_net, vout_net = ctx.net_of(inst, "IN"), ctx.net_of(inst, "OUT")
        if vin_net is None or vin_net not in user_rails:
            continue
        vin, vout = ctx.volts(vin_net), ctx.volts(vout_net)
        label = ctx.label(inst)
        rec = _ldo_record(inst)
        if vin is None or vout is None or rec is None or not isinstance(rec.get("dropout"), Mapping):
            why = "no dropout data" if rec is None else "OUT is not on a known rail"
            out.append(Finding(DROPOUT_RULE, "not_checked", None, f"{label}: {why}.", [inst.ref]))
            continue
        drop = rec["dropout"]
        dv = float(drop["value"])
        i_txt = fmt(float(drop["i_out"]), "A") if drop.get("i_out") is not None else "?"
        head = vin - vout
        sid = rec.get("source_id") or ctx.src(inst)
        if head + _EPS < dv:
            out.append(ctx.finding(DROPOUT_RULE, "failed", "caution",
                                   f"{label}: IN {vin_net} {fmt(vin, 'V')} − OUT {fmt(vout, 'V')} = {fmt(head, 'V')} is "
                                   f"below the maximum dropout {fmt(dv, 'V')} at {i_txt} (p. {drop.get('page')}): the "
                                   "output falls below its nominal voltage as the battery discharges.", inst,
                                   source_id=sid))
        else:
            out.append(ctx.finding(DROPOUT_RULE, "passed", None,
                                   f"{label}: headroom {fmt(head, 'V')} ≥ maximum dropout {fmt(dv, 'V')} at {i_txt}.",
                                   inst, source_id=sid))
    return out


@rule(PATH_RULE)
def power_path_out(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    for inst in ctx.instances:
        spec = OUT_REG.get(inst.module_id)
        if spec is None:
            continue
        pin, lo, hi, page = spec
        net = ctx.net_of(inst, pin)
        if net is None:
            continue
        label = ctx.label(inst)
        v = ctx.volts(net)
        win = f"{fmt(lo, 'V')}–{fmt(hi, 'V')}"
        if v is None:
            out.append(ctx.finding(PATH_RULE, "passed", None, f"{label}: {pin} on its own net {net} (regulated "
                                   f"{win}, p. {page}); feed 3.3 V parts through a regulator.", inst))
        elif v + _EPS < lo:
            limit = (ctx.esp or {}).get("vdd_abs_max") if net == "3V3" else None
            lim_txt = f" (ESP absolute maximum {fmt(limit, 'V')})" if limit is not None else ""
            out.append(ctx.finding(PATH_RULE, "failed", "danger",
                                   f"{label}: {pin} is on {net} ({fmt(v, 'V')}) but regulates to {win} (p. {page}): "
                                   f"it lifts the rail above its voltage{lim_txt}. Put a 3.3 V regulator between "
                                   f"{pin} and {net}.", inst))
        elif v > hi + _EPS:
            out.append(ctx.finding(PATH_RULE, "failed", "caution",
                                   f"{label}: {pin} is on {net} ({fmt(v, 'V')}), above its regulation {win} (p. "
                                   f"{page}): OUT is tied to another source and the power path is bypassed. Give "
                                   f"{pin} its own system net.", inst))
        else:
            out.append(ctx.finding(PATH_RULE, "passed", None, f"{label}: {pin} on {net} ({fmt(v, 'V')}) within "
                                   f"{win}.", inst))
    return out
