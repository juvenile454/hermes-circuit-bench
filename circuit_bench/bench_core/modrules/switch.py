"""Family rules ``switch``: relays (SRD-05VDC-SL-C, G5LE), diodes, optocouplers.

- ``mod.switch.relay_needs_driver``: a relay coil pin (``COIL1``/``COIL2``) on a net an ESP GPIO drives. Coil current
  from the module data (``current.typ``/``max``, datasheet coil table) > ``ctx.esp["ioh"]`` (typical IOH at maximum
  drive strength, data/electrical; ``iol`` when the other coil end is not on GND, i.e. the GPIO sinks) -> danger; ≤ IOH -> caution (a GPIO still is no coil driver: no flyback path);
  no coil current in the data or no ESP values -> not_checked. Coil on non-GPIO nets -> passed.
- ``mod.switch.relay_flyback``: no diode across the coil -> caution (Omron "Safety Precautions for All Relays"
  p. 9: install surge absorbing circuits at both ends of the coil). A diode = a plain part of kind diode (also
  rectifier/schottky) or a module instance of category ``discrete.diode`` whose two pins sit on the two coil nets.
  Polarity known (pins A/K, anode/cathode) and the anode on the coil's supply rail -> caution (the diode conducts
  when the coil is switched on). Coil pins not both connected -> not_checked.
- ``mod.switch.relay_mains``: a contact pin (COM/NO/NC) on a rail above 60 V, on a net whose name says mains
  (230V, 120V, MAINS, AC_L, LINE, NEUTRAL …), or ``facts.mains`` / ``options.mains`` true -> danger, text
  "mains voltage is out of scope: do not build". The low-voltage cap is a product rule (no source cap: the
  finding never comes from module data). Otherwise passed; when a contact sits on a known rail of at most 60 V the
  passed finding supersedes ``mod.hazard`` (the relay's mains notice drops to info), else the notice stays.
- One cause, one warning: a missing coil diode is reported by relay_flyback, which supersedes the generic
  ``mod.required_parts`` finding (requires[flyback]) on the same relay.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from . import modcheck

Ctx, Finding, Instance, rule, fmt = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.rule, modcheck.fmt

DRIVER = "mod.switch.relay_needs_driver"
FLYBACK = "mod.switch.relay_flyback"
MAINS = "mod.switch.relay_mains"
REQUIRED_PARTS = "mod.required_parts"  # generic requires[] rule (relay_flyback supersedes its flyback finding)
HAZARD = "mod.hazard"  # generic hazards[] rule (relay_mains, passed on low-voltage rails, lowers it to info)
RELAY_CATEGORY = "switch.relay"
DIODE_CATEGORY = "discrete.diode"
COIL_PINS = ("COIL1", "COIL2")
CONTACT_PINS = ("COM", "NO", "NC")
PRECAUTIONS_SRC = "mod-switch-relay-precautions"
LOW_VOLTAGE_MAX_V = 60.0  # product rule, as modspec.MAX_RAIL_V: Circuit Bench is low voltage only
MAINS_TEXT = "mains voltage is out of scope: do not build"
_DIODE_KINDS = frozenset({"diode", "rectifier", "schottky", "zener", "flyback"})
_ANODE = frozenset({"a", "anode", "+"})
_CATHODE = frozenset({"k", "c", "cathode", "-"})
_GPIO = re.compile(r"^GPIO\d+$")
_MAINS_NET = re.compile(r"(^|[^0-9.])(100|110|115|120|220|230|240|400)\s*V(AC)?($|[^a-z0-9])|MAINS|NETZ|VAC|"
                        r"^(AC[_-]?)?(L|N|L1|L2|L3|PE|LINE|NEUTRAL|PHASE|LIVE)$", re.I)


# --- helpers ---------------------------------------------------------------------------------------------------------
def _relays(ctx: Ctx) -> list[Instance]:
    return [i for i in ctx.instances if i.module.get("category") == RELAY_CATEGORY]


def _part_nets(ctx: Ctx) -> dict[str, dict[str, str]]:
    """ref -> {pin: net} of every part on a net (module and plain parts, as the engine resolved them)."""
    out: dict[str, dict[str, str]] = {}
    for net, info in ctx.nets.items():
        for ref, pin in info.get("pins", []):
            out.setdefault(ref, {})[pin] = net
    return out


def _gpios(ctx: Ctx, net: str | None) -> list[int]:
    if net is None:
        return []
    info = ctx.nets.get(net) or {}
    pins = [int(g) for g in info.get("gpios") or [] if isinstance(g, int) or str(g).isdigit()]
    if not pins and _GPIO.match(net) and net not in ctx.rails:
        pins = [int(net[4:])]
    return pins


def _coil_current(inst: Instance) -> tuple[float | None, Any]:
    cur = inst.module.get("current")
    if not isinstance(cur, Mapping):
        return None, None
    for key in ("max", "typ"):
        f = cur.get(key)
        if isinstance(f, Mapping) and isinstance(f.get("value"), int | float):
            return float(f["value"]), f
    return None, None


def _truthy(x: Any) -> bool:
    return x is True or (isinstance(x, str) and x.strip().lower() in ("1", "true", "yes", "mains"))


def _is_diode(ctx: Ctx, ref: str, by_ref: Mapping[str, Mapping[str, Any]]) -> bool:
    for inst in ctx.instances:
        if inst.ref == ref:
            return inst.module.get("category") == DIODE_CATEGORY
    p = by_ref.get(ref) or {}
    kind = p.get("kind")
    return isinstance(kind, str) and kind.strip().lower() in _DIODE_KINDS


# --- mod.switch.relay_needs_driver -------------------------------------------------------------------------------------
@rule(DRIVER)
def relay_needs_driver(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    for inst in _relays(ctx):
        nets = [inst.conn.get(p) for p in COIL_PINS]
        on_gpio = [(p, n, g) for p, n in zip(COIL_PINS, nets, strict=True) for g in _gpios(ctx, n)]
        if not on_gpio:
            if any(nets):
                out.append(ctx.finding(DRIVER, "passed", None, f"{ctx.label(inst)}: coil not on a GPIO net.", inst))
            continue
        pin, net, gpio = on_gpio[0]
        i_coil, f = _coil_current(inst)
        if i_coil is None:
            out.append(ctx.finding(DRIVER, "not_checked", None,
                                   f"{ctx.label(inst)}: coil pin {pin} on GPIO{gpio} ({net}); the coil current is not "
                                   "in the module data. A relay coil needs a transistor driver.", inst,
                                   refs=[inst.ref, f"GPIO{gpio}"]))
            continue
        other = nets[1 - COIL_PINS.index(pin)]
        sourcing = ctx.volts(other) == 0.0  # other coil end on GND: the GPIO sources the coil current (IOH)
        key, what = ("ioh", "sources") if sourcing else ("iol", "sinks")
        ioh = (ctx.esp or {}).get(key)
        if not isinstance(ioh, int | float):
            out.append(ctx.finding(DRIVER, "not_checked", None,
                                   f"{ctx.label(inst)}: coil ({fmt(i_coil, 'A')}) on GPIO{gpio}; no ESP drive current "
                                   f"for {ctx.chip}. A relay coil needs a transistor driver.", inst,
                                   refs=[inst.ref, f"GPIO{gpio}"], source_id=ctx.src(inst, f)))
            continue
        cond = f.get("conditions") if isinstance(f, Mapping) else None
        esp_src = ((ctx.esp or {}).get("source_ids") or [None])[0]
        if i_coil > ioh:
            msg = (f"{ctx.label(inst)}: relay coil on GPIO{gpio} draws {fmt(i_coil, 'A')}"
                   f"{f' ({cond})' if cond else ''}, more than the {fmt(float(ioh), 'A')} a {ctx.chip} GPIO {what} "
                   f"(typical {key.upper()}): drive the coil with an NPN/MOSFET or ULN2003 and a flyback diode.")
            sev = "danger"
        else:
            msg = (f"{ctx.label(inst)}: relay coil straight on GPIO{gpio} ({fmt(i_coil, 'A')} ≤ {key.upper()} "
                   f"{fmt(float(ioh), 'A')}); the coil's turn-off spike still reaches the pin: use a driver.")
            sev = "caution"
        out.append(ctx.finding(DRIVER, "failed", sev, msg, inst, source_id=ctx.src(inst, f),
                               refs=[inst.ref, f"GPIO{gpio}"],
                               source_ids=[s for s in (ctx.src(inst, f), esp_src) if s]))
    return out


# --- mod.switch.relay_flyback -----------------------------------------------------------------------------------------
@rule(FLYBACK)
def relay_flyback(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    relays = _relays(ctx)
    if not relays:
        return out
    pn = _part_nets(ctx)
    by_ref: dict[str, Mapping[str, Any]] = {p["ref"]: p for p in ctx.parts if isinstance(p, Mapping) and isinstance(p.get("ref"), str)}
    for inst in relays:
        a, b = (inst.conn.get(p) for p in COIL_PINS)
        if not a or not b:
            out.append(ctx.finding(FLYBACK, "not_checked", None,
                                   f"{ctx.label(inst)}: coil pins not both connected; flyback diode not checked.",
                                   inst, source_id=PRECAUTIONS_SRC))
            continue
        diodes = []
        for ref, pins in pn.items():
            if ref == inst.ref or not _is_diode(ctx, ref, by_ref):
                continue
            if len(pins) >= 2 and {a, b} <= set(pins.values()):
                diodes.append((ref, pins))
        if not diodes:
            f = ctx.finding(FLYBACK, "failed", "caution",
                            f"{ctx.label(inst)}: no diode across the coil ({a} – {b}). Put a flyback diode "
                            f"(e.g. 1N4148/1N4007) across it, cathode to {a}: the coil's turn-off surge "
                            "damages the driver.", inst, source_id=PRECAUTIONS_SRC)
            f.supersedes = (REQUIRED_PARTS,)  # the generic requires[flyback] finding on the relay folds in here
            out.append(f)
            continue
        ref, pins = diodes[0]
        anode = next((n for p, n in pins.items() if p.strip().lower() in _ANODE), None)
        cathode = next((n for p, n in pins.items() if p.strip().lower() in _CATHODE), None)
        va, vb = ctx.volts(a), ctx.volts(b)
        supply = a if (va or 0) >= (vb or 0) and va else (b if vb else None)
        if anode and cathode and supply and anode == supply:
            out.append(ctx.finding(FLYBACK, "failed", "caution",
                                   f"{ctx.label(inst)}: flyback diode {ref} is reversed (anode on the coil supply "
                                   f"{supply}); it conducts when the coil switches on. Turn it: cathode to {supply}.",
                                   inst, source_id=PRECAUTIONS_SRC, refs=[inst.ref, ref]))
        else:
            out.append(ctx.finding(FLYBACK, "passed", None, f"{ctx.label(inst)}: diode {ref} across the coil.",
                                   inst, refs=[inst.ref, ref], source_id=PRECAUTIONS_SRC))
    return out


# --- mod.switch.relay_mains -------------------------------------------------------------------------------------------
@rule(MAINS)
def relay_mains(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    opt = _truthy((ctx.options or {}).get("mains"))
    for inst in _relays(ctx):
        why: list[str] = []
        if opt:
            why.append("options.mains is set")
        if _truthy((inst.facts or {}).get("mains")):
            why.append("facts.mains is set")
        for pin in CONTACT_PINS:
            net = inst.conn.get(pin)
            if not net:
                continue
            v = ctx.volts(net)
            if v is not None and v > LOW_VOLTAGE_MAX_V:
                why.append(f"{pin} on {net} at {fmt(v, 'V')}")
            elif v is None and _MAINS_NET.search(net):
                why.append(f"{pin} on net {net!r}")
        if why:
            out.append(Finding(MAINS, "failed", "danger",
                               f"{ctx.label(inst)}: contact side looks like mains ({'; '.join(why)}): {MAINS_TEXT}. "
                               "Circuit Bench covers low voltage up to 60 V only.", [inst.ref]))
        elif any(inst.conn.get(p) for p in CONTACT_PINS):
            low = sorted({f"{n} = {fmt(v, 'V')}" for n, v in ((inst.conn.get(p), ctx.volts(inst.conn.get(p) or ""))
                                                             for p in CONTACT_PINS if inst.conn.get(p))
                          if v is not None and v <= LOW_VOLTAGE_MAX_V})
            if low:  # a contact sits on a known rail of at most 60 V: the relay's mains notice drops to info
                out.append(Finding(MAINS, "passed", None, f"{ctx.label(inst)}: contacts on low-voltage rails "
                                   f"({', '.join(low)}); keep the contact side at 60 V DC or less.", [inst.ref],
                                   supersedes=(HAZARD,)))
            else:
                out.append(Finding(MAINS, "passed", None, f"{ctx.label(inst)}: contacts on low-voltage nets.",
                                   [inst.ref]))
    return out
