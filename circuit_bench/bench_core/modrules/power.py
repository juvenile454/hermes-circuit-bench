"""Family rules ``power``: LDOs, buck converters and Li-Ion chargers.

- ``mod.power.ldo_esr``: an LDO (category ``power.ldo``) whose datasheet requires an output capacitor (``requires[]``
  with code ``decoupling`` on VOUT) needs a capacitor part between its VOUT net and GND. Missing -> caution; a value
  below the required one -> caution; a given ``esr`` outside the datasheet ESR range (``ESR`` below, MCP1700 0–2 Ω)
  -> caution. No output capacitor value in the datasheet (HT7333) -> not_checked.
- ``mod.power.li_ion``: every Li-Ion charger (category ``power.charger``) in the project gets the safety danger
  (product rule: Li batteries get warnings) exactly once: from ``mod.hazard`` when the entry has ``hazards[li_ion]``
  (this rule then passes), otherwise from here; the charger's battery pin on the 3V3 rail
  -> danger (the cell is charged to V_REG 4.2 V, above the ESP32's absolute maximum supply voltage).
- ``mod.power.dropout``: an LDO with VIN on a rail of ``options.rails`` (e.g. VBAT 3.7) and VOUT on a known rail: the
  headroom V_IN − V_OUT against the dropout of data/parts/power2.json (maximum at its test current; typical-only
  values give info). Without options.rails on VIN nothing is reported (the board's own 5 V is not a battery).
Rule texts in English; numbers with page in power2.json / data/modules/power.json.
"""
from __future__ import annotations

import importlib
import re
from collections.abc import Mapping
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = (
    modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule)

_PKG = __name__.rsplit(".", 2)[0]  # bench_core under whatever package name it is loaded
parts = importlib.import_module(_PKG + ".parts")

ESR_RULE = "mod.power.ldo_esr"
LI_ION_RULE = "mod.power.li_ion"
DROPOUT_RULE = "mod.power.dropout"
_EPS = 1e-9
# Output capacitor ESR range where the datasheet gives one (module id -> (min Ω, max Ω, page)); text in the entry's
# requires note and the excerpt line "ESR range on the output capacitor can range from 0" / "to 2.0Ω." (MCP1700 p. 13).
ESR: dict[str, tuple[float, float, int]] = {"mcp1700": (0.0, 2.0, 13)}
_CAP = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([pnuµμm]?)\s*F?\b", re.IGNORECASE)
_PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "": 1.0}
_GND = "GND"


def farads(value: Any) -> float | None:
    """Capacitance from '1µF', '4.7 uF', '470uF 16V', '100n', 1e-6; None if not readable."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value) if value > 0 else None
    if not isinstance(value, str):
        return None
    m = _CAP.match(value)
    if not m:
        return None
    prefix = m.group(2)
    return float(m.group(1)) * _PREFIX[prefix if prefix in _PREFIX else prefix.lower()]


def ohms(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(m)?\s*(?:Ω|ohm|R)?\s*$", value, re.IGNORECASE)
        if m:
            return float(m.group(1)) * (1e-3 if m.group(2) else 1.0)
    return None


def _is_cap(p: Mapping[str, Any]) -> bool:
    kind = str(p.get("kind") or "").lower()
    return kind in ("capacitor", "cap") or (not kind and str(p.get("ref") or "").upper().startswith("C"))


def _caps_between(ctx: Ctx, net_a: str, net_b: str) -> list[dict[str, Any]]:
    out = []
    for p in ctx.parts:
        conn = p.get("conn")
        if not _is_cap(p) or not isinstance(conn, Mapping):
            continue
        nets = {v for v in conn.values() if isinstance(v, str)}
        if net_a in nets and net_b in nets:
            out.append(p)
    return out


def _out_requirement(inst: Instance) -> dict[str, Any] | None:
    for r in inst.module.get("requires") or []:
        if isinstance(r, Mapping) and r.get("code") == "decoupling" and any(
                pin in (r.get("pins") or []) for pin in ("VOUT",)):
            return dict(r)
    return None


@rule(ESR_RULE)
def ldo_esr(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module.get("category") != "power.ldo":
            continue
        vout = ctx.net_of(inst, "VOUT")
        if vout is None:
            continue
        label = ctx.label(inst)
        req = _out_requirement(inst)
        if req is None:
            out.append(Finding(ESR_RULE, "not_checked", None, f"{label}: the datasheet gives no output capacitor "
                               "value; use the application circuit of the datasheet.", [inst.ref]))
            continue
        sid = req.get("source_id") or ctx.src(inst)
        gnd = ctx.net_of(inst, str(req.get("to") or _GND)) or _GND
        need = farads(req.get("value"))
        need_txt = f" of at least {fmt(need, 'F')}" if need else ""
        caps = _caps_between(ctx, vout, gnd)
        page = req.get("page")
        if not caps:
            out.append(ctx.finding(ESR_RULE, "failed", "caution",
                                   f"{label}: no output capacitor{need_txt} between VOUT ({vout}) and {gnd}; the LDO "
                                   f"can oscillate without it (datasheet p. {page}).", inst, source_id=sid))
            continue
        refs = [inst.ref, *(str(c.get("ref")) for c in caps)]
        values = [farads(c.get("value")) for c in caps]
        problems: list[str] = []
        if need is not None and all(v is not None for v in values):
            total = sum(v for v in values if v is not None)
            if total < need * (1 - 1e-6):
                problems.append(f"{fmt(total, 'F')} on VOUT is below the required {fmt(need, 'F')}")
        rng = ESR.get(inst.module_id)
        if rng is not None:
            for c in caps:
                esr = ohms(c.get("esr"))
                if esr is not None and not (rng[0] - _EPS <= esr <= rng[1] + _EPS):
                    problems.append(f"{c.get('ref')} ESR {fmt(esr, 'Ω')} is outside {fmt(rng[0], 'Ω')}–"
                                    f"{fmt(rng[1], 'Ω')} (p. {rng[2]})")
        if problems:
            out.append(ctx.finding(ESR_RULE, "failed", "caution", f"{label}: " + "; ".join(problems) + ".", inst,
                                   source_id=sid, refs=refs))
        else:
            unknown = " (value not readable)" if any(v is None for v in values) else ""
            out.append(ctx.finding(ESR_RULE, "passed", None, f"{label}: output capacitor on VOUT{unknown}.", inst,
                                   source_id=sid, refs=refs))
    return out


def _bat_pin(inst: Instance) -> str | None:
    for p in inst.module.get("pins") or []:
        if isinstance(p, Mapping) and p.get("signal") == "power_out":
            return str(p.get("name"))
    return None


@rule(LI_ION_RULE)
def li_ion(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module.get("category") != "power.charger":
            continue
        hz = next((h for h in inst.module.get("hazards") or [] if isinstance(h, Mapping) and h.get("code") == "li_ion"),
                  None)
        sid = (hz or {}).get("source_id") or ctx.src(inst)
        if hz:  # the entry's hazards[li_ion] already gives this danger through mod.hazard: one notice, not two
            out.append(Finding(LI_ION_RULE, "passed", None, f"{ctx.label(inst)}: Li-Ion safety notice given by "
                               "mod.hazard (hazards[li_ion]).", [inst.ref], [sid] if sid else []))
        else:
            out.append(ctx.finding(LI_ION_RULE, "failed", "danger", f"{ctx.label(inst)}: Li-Ion charger: fire risk "
                                   "on overcharge or short circuit.", inst, source_id=sid))
        pin = _bat_pin(inst)
        net = ctx.net_of(inst, pin) if pin else None
        if net == "3V3":
            limit = (ctx.esp or {}).get("vdd_abs_max")
            lim_txt = f" (ESP absolute maximum {fmt(limit, 'V')})" if limit is not None else ""
            out.append(ctx.finding(LI_ION_RULE, "failed", "danger",
                                   f"{ctx.label(inst)}: {pin} is on the 3V3 rail: a Li-Ion cell is charged to 4.2 V"
                                   f"{lim_txt}. Feed the ESP through a regulator from the battery net.", inst,
                                   source_id=sid))
    return out


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
        if inst.module.get("category") != "power.ldo":
            continue
        vin_net, vout_net = ctx.net_of(inst, "VIN"), ctx.net_of(inst, "VOUT")
        if vin_net is None or vin_net not in user_rails:
            continue
        vin, vout = ctx.volts(vin_net), ctx.volts(vout_net)
        label = ctx.label(inst)
        rec = _ldo_record(inst)
        if vin is None or vout is None or rec is None or not isinstance(rec.get("dropout"), Mapping):
            why = "no dropout data" if rec is None else "VOUT is not on a known rail"
            out.append(Finding(DROPOUT_RULE, "not_checked", None, f"{label}: {why}.", [inst.ref]))
            continue
        drop = rec["dropout"]
        dv = float(drop["value"])
        i_txt = fmt(float(drop["i_out"]), "A") if drop.get("i_out") is not None else "?"
        head = vin - vout
        sid = rec.get("source_id") or ctx.src(inst)
        typ_only = bool(drop.get("typical_only"))
        kind = "typical" if typ_only else "maximum"
        if head + _EPS < dv:
            sev = "info" if typ_only else "caution"
            out.append(ctx.finding(DROPOUT_RULE, "failed", sev,
                                   f"{label}: VIN {vin_net} {fmt(vin, 'V')} − VOUT {fmt(vout, 'V')} = {fmt(head, 'V')} "
                                   f"is below the {kind} dropout {fmt(dv, 'V')} at {i_txt} (p. {drop.get('page')}): "
                                   "the output falls below its nominal voltage as the battery discharges.", inst,
                                   source_id=sid))
        else:
            out.append(ctx.finding(DROPOUT_RULE, "passed", None,
                                   f"{label}: headroom {fmt(head, 'V')} ≥ {kind} dropout {fmt(dv, 'V')} at {i_txt}.",
                                   inst, source_id=sid))
    return out
