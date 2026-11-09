"""Family rules ``ndrive``: TPL7407L, DRV8871, SS14, BAT54. Module data in
circuit_bench/data/modules/ndrive.json; the numbers below carry page and quote of the pinned data sheets (tests check
them against tests/corpus/excerpts/mod-ndrive-*.txt).

- ``mod.ndrive.drv8871_ilim``: the DRV8871 sets its current limit with a resistor from ILIM to GND,
  I_TRIP = V_ILIM / R_ILIM with V_ILIM 64 kV typ (59–69 kV, p. 5; example 32 kΩ -> 2 A, p. 9); the minimum allowed
  R_ILIM is 15 kΩ (p. 9). ILIM open or no resistor to GND -> caution (variant ``board``: info, the board usually
  fits one, unverified); ILIM straight on GND or R < 15 kΩ -> caution; resistor value unreadable -> not_checked;
  otherwise passed with I_TRIP typ and its spread. Several resistors from ILIM to GND count in parallel.
- ``mod.ndrive.tpl7407l_com``: COM is the gate-drive supply and the common cathode of the free-wheeling diodes; it
  must sit on the highest load voltage (p. 12). A load on OUTx (a plain part or another module with a pin on the
  OUTx net) that returns to a known rail above the COM voltage -> caution. COM below the 8.5 V of the module data
  -> info: the part still works with reduced gate drive and higher RDS(on) (p. 13; the range itself is reported by
  mod.supply_range). A load on OUT7 without a diode on that net -> info (external Schottky recommended for inductive
  loads, p. 8). COM open, on GND or above the range: left to mod.unconnected / mod.supply_range.
- ``mod.ndrive.diode_reverse``: SS14 and BAT54 (all variants) with both ends on known rails: reverse voltage
  V(K) − V(A) above VRRM -> danger (the diode breaks down); A above K between two fixed rails -> caution (the diode
  conducts permanently between two supplies); otherwise passed. Ends on GPIO or unknown nets: no check.
"""
from __future__ import annotations

import importlib
from collections.abc import Iterable, Mapping
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = (
    modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule)

_PKG = __name__.rsplit(".", 2)[0]  # bench_core under whatever package name it is loaded
units = importlib.import_module(_PKG + ".units")

ILIM_RULE = "mod.ndrive.drv8871_ilim"
COM_RULE = "mod.ndrive.tpl7407l_com"
DIODE_RULE = "mod.ndrive.diode_reverse"
_EPS = 1e-9

DRV_SRC = "mod-ndrive-drv8871-ds"
TPL_SRC = "mod-ndrive-tpl7407l-ds"

# Cited numbers (value in SI units; evidence = part of one excerpt line, or parts of lines on the page in order).
FACTS: dict[str, dict[str, Any]] = {
    "drv8871.v_ilim": {"value": 64000.0, "min": 59000.0, "max": 69000.0, "unit": "V", "page": 5,
                       "source_id": DRV_SRC,
                       "evidence": ["Constant for calculating", "current regulation (see", "IOUT = 1 A 59 64 69 kV"],
                       "conditions": "I_TRIP = V_ILIM / R_ILIM (kV / kΩ = A); min, typ, max"},
    "drv8871.example": {"value": 2.0, "r_ilim": 32000.0, "unit": "A", "page": 9, "source_id": DRV_SRC,
                        "evidence": "For example, if RILIM = 32 k\u2126, the DRV8871 device limits motor current to 2 A"},
    "drv8871.r_ilim_min": {"value": 15000.0, "unit": "Ω", "page": 9, "source_id": DRV_SRC,
                           "evidence": "The minimum allowed RILIM is 15 k\u2126."},
    "drv8871.no_regulation": {"value": 15000.0, "max": 18000.0, "unit": "Ω", "page": 10, "source_id": DRV_SRC,
                              "evidence": "If current regulation is not needed, a 15-k\u2126 to 18-k\u2126 resistor "
                                          "should be used on pin ILIM."},
    "tpl7407l.highest_load": {"page": 12, "source_id": TPL_SRC,
                              "evidence": "COM must be tied to highest load voltage"},
    "tpl7407l.reduced_drive": {"page": 13, "source_id": TPL_SRC,
                               "evidence": ["Though 8.5 V minimum is recommended for Vcom",
                                            ("reduced COM voltage that has a reduced gate drive voltage and a "
                                             "resulting higher Rdson.")]},
    "tpl7407l.out7_schottky": {"page": 8, "source_id": TPL_SRC,
                               "evidence": ("If the application has an inductive load connected to OUT7, it is "
                                            "recommended to use an external Schottky diode")},
    "ss14.vrrm": {"value": 40.0, "unit": "V", "page": 1, "source_id": "mod-ndrive-ss14-ds",
                  "evidence": ["PARAMETER SYMBOL SS12 SS13 SS14 SS15 SS16 UNIT",
                               "Maximum repetitive peak reverse voltage V RRM 20 30 40 50 60 V"],
                  "conditions": "SS14 column"},
    "bat54.vrrm": {"value": 30.0, "unit": "V", "page": 3, "source_id": "mod-ndrive-bat54-ds",
                   "evidence": "VR reverse voltage - 30 V", "conditions": "per diode, limiting value"},
}

# (module id, variant id or None) -> diode (anode pin, cathode pin) pairs
DIODE_PAIRS: dict[tuple[str, str | None], tuple[tuple[str, str], ...]] = {
    ("ss14", None): (("A", "K"),),
    ("bat54", None): (("A", "K"),),
    ("bat54", "a"): (("A", "K1"), ("A", "K2")),
    ("bat54", "c"): (("A1", "K"), ("A2", "K")),
    ("bat54", "s"): (("A1", "CT"), ("CT", "K2")),
}
VRRM_FACT = {"ss14": "ss14.vrrm", "bat54": "bat54.vrrm"}
TPL_OUTS = tuple(f"OUT{i}" for i in range(1, 8))
_DIODE_KINDS = frozenset({"diode", "rectifier", "schottky", "zener", "flyback"})
_CAP_KINDS = frozenset({"capacitor", "cap"})


# --- helpers ---------------------------------------------------------------------------------------------------------
def _plain(ctx: Ctx) -> Iterable[tuple[str, str, list[str], Mapping[str, Any]]]:
    """(ref, kind, nets, part) of every part without a catalog module."""
    for p in ctx.parts:
        if not isinstance(p, Mapping) or (isinstance(p.get("module"), str) and p["module"].strip()):
            continue
        conn = p.get("conn")
        nets = [v for v in conn.values() if isinstance(v, str) and v] if isinstance(conn, Mapping) else []
        yield str(p.get("ref") or "?"), str(p.get("kind") or "").strip().lower(), nets, p


def _resistance(part: Mapping[str, Any]) -> float | None:
    v = part.get("value")
    if v is None:
        return None
    try:
        r = units.parse_quantity(v, "Ω")
    except Exception:  # noqa: BLE001 - BenchError or anything else: the value is unreadable
        return None
    return float(r) if r is not None and r >= 0 else None


def _f(value: float, unit: str) -> str:
    return fmt(value, unit)


# --- mod.ndrive.drv8871_ilim -----------------------------------------------------------------------------------------
@rule(ILIM_RULE)
def drv8871_ilim(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    v_ilim = FACTS["drv8871.v_ilim"]
    r_min = FACTS["drv8871.r_ilim_min"]["value"]
    for inst in ctx.instances:
        if inst.module_id != "drv8871":
            continue
        label = ctx.label(inst)
        board = inst.variant == "board"
        net = ctx.net_of(inst, "ILIM")
        if net == "GND":
            out.append(ctx.finding(ILIM_RULE, "failed", "caution",
                                   f"{label}: ILIM tied straight to GND (0 Ω); the minimum allowed R_ILIM is "
                                   f"{_f(r_min, 'Ω')}. Fit a resistor from ILIM to GND: I_TRIP = 64 kV / R_ILIM.",
                                   inst, source_id=DRV_SRC))
            continue
        resistors = [] if net is None else [
            (ref, part) for ref, kind, nets, part in _plain(ctx)
            if kind == "resistor" and net in nets and "GND" in nets and len(set(nets)) == 2]
        if not resistors:
            where = "ILIM open" if net is None else f"no resistor from ILIM ({net}) to GND"
            if board:
                out.append(ctx.finding(ILIM_RULE, "failed", "info",
                                       f"{label}: {where}. Breakout boards usually fit R_ILIM (unverified): read it "
                                       "on your board; I_TRIP = 64 kV / R_ILIM.", inst, source_id=DRV_SRC))
            else:
                out.append(ctx.finding(ILIM_RULE, "failed", "caution",
                                       f"{label}: {where}: the current limit is not set. Fit R_ILIM ≥ "
                                       f"{_f(r_min, 'Ω')} from ILIM to GND (I_TRIP = 64 kV / R_ILIM; 15–18 kΩ "
                                       "without current regulation).", inst, source_id=DRV_SRC))
            continue
        values = [(ref, _resistance(part)) for ref, part in resistors]
        bad = [ref for ref, r in values if r is None]
        if bad:
            out.append(Finding(ILIM_RULE, "not_checked", "info",
                               f"{label}: value of {', '.join(bad)} on ILIM unreadable; current limit not checked.",
                               [inst.ref, *bad], [DRV_SRC]))
            continue
        refs = [ref for ref, _ in values]
        rs = [r for _, r in values if r is not None]
        r_tot = 0.0 if any(r <= _EPS for r in rs) else 1.0 / sum(1.0 / r for r in rs)
        if r_tot < r_min - _EPS:
            text = (f"{label}: R_ILIM {_f(r_tot, 'Ω')} ({', '.join(refs)}) is below the minimum allowed "
                    f"{_f(r_min, 'Ω')}.")
            if r_tot > _EPS:
                text += f" It would set I_TRIP ≈ {_f(v_ilim['value'] / r_tot, 'A')}, above the 3.6 A peak rating."
            out.append(ctx.finding(ILIM_RULE, "failed", "caution", text, inst, source_id=DRV_SRC,
                                   refs=[inst.ref, *refs]))
            continue
        typ = v_ilim["value"] / r_tot
        lo, hi = v_ilim["min"] / r_tot, v_ilim["max"] / r_tot
        out.append(Finding(ILIM_RULE, "passed", None,
                           f"{label}: R_ILIM {_f(r_tot, 'Ω')} ({', '.join(refs)}) sets I_TRIP = 64 kV / R_ILIM = "
                           f"{_f(typ, 'A')} typ ({_f(lo, 'A')}–{_f(hi, 'A')} from V_ILIM 59–69 kV, resistor "
                           "tolerance on top).", [inst.ref, *refs], [DRV_SRC]))
    return out


# --- mod.ndrive.tpl7407l_com -----------------------------------------------------------------------------------------
def _loads(ctx: Ctx, inst: Instance, net: str) -> list[tuple[str, str, float | None]]:
    """(ref, other net, its voltage) for every part or other module with a pin on ``net``."""
    found: list[tuple[str, str, float | None]] = []
    for ref, kind, nets, _ in _plain(ctx):
        if net not in nets or kind in _CAP_KINDS:
            continue
        for other in nets:
            if other not in (net, "GND"):
                found.append((ref, other, ctx.volts(other)))
        if all(o in (net, "GND") for o in nets):
            found.append((ref, net, None))
    for other_inst in ctx.instances:
        if other_inst.ref == inst.ref or net not in other_inst.conn.values():
            continue
        for other in set(other_inst.conn.values()):
            if isinstance(other, str) and other not in (net, "GND"):
                found.append((other_inst.ref, other, ctx.volts(other)))
    return found


def _diodes_on(ctx: Ctx, net: str, skip: str) -> list[str]:
    refs = [ref for ref, kind, nets, _ in _plain(ctx) if kind in _DIODE_KINDS and net in nets]
    refs += [i.ref for i in ctx.instances if i.ref != skip and i.module.get("category") == "discrete.diode"
             and net in i.conn.values()]
    return refs


@rule(COM_RULE)
def tpl7407l_com(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != "tpl7407l":
            continue
        label = ctx.label(inst)
        com = ctx.net_of(inst, "COM")
        if com is None or com == "GND":
            continue  # mod.unconnected / mod.supply_range report it
        v_com = ctx.volts(com)
        used = {p: n for p in TPL_OUTS if (n := ctx.net_of(inst, p)) is not None and n != "GND"}
        if v_com is None:
            out.append(Finding(COM_RULE, "not_checked", "info",
                               f"{label}: COM on {com} with unknown voltage; load voltages not checked (COM must sit "
                               "on the highest load voltage; name the rail in options.rails).", [inst.ref]))
            continue
        loads = {p: _loads(ctx, inst, n) for p, n in used.items()}
        higher = sorted({(ref, other, v) for p, ls in loads.items() for ref, other, v in ls
                         if v is not None and v > v_com + _EPS}, key=lambda x: (-x[2], x[0]))
        if higher:
            ref, other, v = higher[0]
            out.append(ctx.finding(COM_RULE, "failed", "caution",
                                   f"{label}: COM on {com} = {_f(v_com, 'V')}, but the load {ref} returns to "
                                   f"{other} = {_f(v, 'V')}. COM must be tied to the highest load voltage, or the "
                                   "free-wheeling diodes conduct from the load supply into COM.",
                                   inst, source_id=TPL_SRC, refs=[inst.ref, *sorted({h[0] for h in higher})]))
        sup = inst.module.get("supplies")
        spec = sup.get("COM") if isinstance(sup, Mapping) else None
        v_min = ctx.fv(spec.get("min"), inst) if isinstance(spec, Mapping) else None
        if v_min is not None and _EPS < v_com < v_min - _EPS:
            out.append(ctx.finding(COM_RULE, "failed", "info",
                                   f"{label}: COM {_f(v_com, 'V')} is below {_f(v_min, 'V')}: the driver still "
                                   "switches, with reduced gate drive and a higher RDS(on); the rated output "
                                   "voltage drop needs COM ≥ 8.5 V.", inst, source_id=TPL_SRC))
        if "OUT7" in used and any(True for _ in loads.get("OUT7", [])) and not _diodes_on(ctx, used["OUT7"],
                                                                                           inst.ref):
            out.append(ctx.finding(COM_RULE, "failed", "info",
                                   f"{label}: OUT7 drives a load without an external diode; if it is inductive "
                                   "(coil, motor, relay) add a Schottky diode on OUT7 against negative "
                                   "transients (recommended by TI).", inst, source_id=TPL_SRC))
        if not higher and not (v_min is not None and v_com < v_min - _EPS):
            out.append(Finding(COM_RULE, "passed", None,
                               f"{label}: COM on {com} = {_f(v_com, 'V')}, no load returns to a higher rail.",
                               [inst.ref], [TPL_SRC]))
    return out


# --- mod.ndrive.diode_reverse ----------------------------------------------------------------------------------------
@rule(DIODE_RULE)
def diode_reverse(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    for inst in ctx.instances:
        pairs = DIODE_PAIRS.get((inst.module_id, inst.variant)) or (
            DIODE_PAIRS.get((inst.module_id, None)) if inst.variant is None else None)
        if not pairs:
            continue
        fact = FACTS[VRRM_FACT[inst.module_id]]
        vrrm, src = fact["value"], fact["source_id"]
        label = ctx.label(inst)
        checked = []
        for a, k in pairs:
            na, nk = ctx.net_of(inst, a), ctx.net_of(inst, k)
            va, vk = ctx.volts(na), ctx.volts(nk)
            if na is None or nk is None or va is None or vk is None:
                continue
            vr = vk - va
            if vr > vrrm + _EPS:
                out.append(ctx.finding(DIODE_RULE, "failed", "danger",
                                       f"{label} {a}→{k}: reverse voltage {_f(vr, 'V')} ({nk} − {na}) exceeds VRRM "
                                       f"{_f(vrrm, 'V')}: the diode breaks down. Use a diode rated above the supply.",
                                       inst, source_id=src))
            elif -vr > _EPS and na != nk:
                out.append(ctx.finding(DIODE_RULE, "failed", "caution",
                                       f"{label} {a}→{k}: anode on {na} = {_f(va, 'V')}, cathode on {nk} = "
                                       f"{_f(vk, 'V')}: the diode conducts permanently between two supplies. Check "
                                       "its orientation (band = cathode).", inst, source_id=src))
            else:
                checked.append((a, k, vr))
        if checked and not any(f.refs and inst.ref in f.refs and f.rule_id == DIODE_RULE and f.status == "failed"
                               for f in out):
            worst = max(vr for *_, vr in checked)
            out.append(Finding(DIODE_RULE, "passed", None,
                               f"{label}: reverse voltage at most {_f(max(worst, 0.0), 'V')}, below VRRM "
                               f"{_f(vrrm, 'V')}.", [inst.ref], [src]))
    return out
