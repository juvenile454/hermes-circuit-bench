"""Power calculators: N-channel MOSFET as a low-side switch at a GPIO, linear regulator (LDO) dissipation.

Same contract as calc.py: the action functions return the result envelope and never raise; inputs are SI numbers
or text with units. Datasheet values come from data/parts/power.json (parts.py, quoted in
tests/corpus/excerpts/calc-plus-*.txt). Without a part the sourced checks stay ``not_checked``; rules of thumb say so.
calc.py imports this module at its end; it registers ``mosfet`` and ``ldo`` with calckit.register.

``chip`` (optional, ids from bench_core.chips): the ESP32-S3-WROOM-1 datasheet values (gate high level, supply
current) are used only for ``esp32s3`` or when no chip is given (then the texts say so); another chip gets a general
assumption without the S3 source. The calculation itself does not depend on the chip.
"""
from __future__ import annotations

import math
import re
from typing import Any

from . import calckit, chips, parts, sources, units
from .calckit import RULE
from .calckit import action as _action
from .calckit import fmt as _f
from .calckit import num as _num
from .calckit import q as _q
from .calckit import step as _step
from .contracts import BenchError, assumption, check, envelope, warning

# --- ESP32-S3-WROOM-1 datasheet v1.8 (excerpt calc-plus-esp32-s3-wroom-1-power.txt) ------------------------------
WROOM = "ds-esp32-s3-wroom-1-power"
S3_CHIP = "esp32s3"
S3_DEFAULT_NOTE = "chip not given; ESP32-S3-WROOM-1 values: "
ESP32S3_V_OH_FACTOR = 0.8  # Table 6-3: V_OH min 0.8 × VDD (measured with a high-impedance load)
ESP32S3_VDD33 = (3.0, 3.6)  # Table 6-2: VDD33 min, max
ESP32S3_I_VDD_MIN = 0.5  # Table 6-2: current delivered by the external power supply, min
ESP32S3_TX_PEAK = 0.355  # Table 6-4: Wi-Fi TX peak, 802.11b 1 Mbps @ 20.5 dBm

# --- defaults and rules of thumb (source "rule-of-thumb") ---------------------------------------------------------
GATE_V_DEFAULT = 3.3  # ESP32 GPIO high level at a 3.3 V supply
R_GATE_DEFAULT = 100.0
R_PULLDOWN_DEFAULT = 100_000.0
R_GATE_RANGE = (10.0, 1000.0)  # series gate resistor from a GPIO
R_PULLDOWN_RANGE = (10_000.0, 100_000.0)  # gate pull-down
T_AMBIENT_DEFAULT = 25.0
T_AMBIENT_RANGE = (-60.0, 150.0)  # plausible ambient input in °C (input check, not a part limit)
LDO_V_OUT_REL_TOL = 0.03  # v_out this far from a fixed regulator's nominal output -> warning

MOSFET_FORMULA = ("V_GS = V_gate · R_PD / (R_G + R_PD); R_DS(on) = datasheet maximum at the highest V_GS row ≤ V_GS; "
                  "P = I_load² · R_DS(on); V_DS = I_load · R_DS(on); T_J = T_A + P · R_θJA; I_G,peak = V_gate / R_G")
LDO_FORMULA = ("P = (V_in − V_out) · I_load + V_in · I_q; T_J = T_A + P · θ_JA; "
               "η = V_out · I_load / (V_in · (I_load + I_q))")

_DEG_SUFFIX = re.compile(r"\s*(?:°\s*C|deg\s*C|C)\s*$", re.IGNORECASE)


def _le(a: float, b: float) -> bool:
    """a ≤ b, tolerant of float noise (4.6 − 3.3 = 1.2999999999999998 still counts as 1.3)."""
    return a <= b or math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


def _temp(value: object, name: str) -> float:
    """Temperature in °C from 25, '25', '25 °C', '25C'."""
    text = _DEG_SUFFIX.sub("", value) if isinstance(value, str) else value
    try:
        v, unit = units.parse(text)
    except BenchError as e:
        raise BenchError("invalid_args", f"{name}: {e.message}", "give the temperature in °C, for example 25") from None
    if unit is not None:
        raise BenchError("invalid_args", f"{name} is in °C, got a value in {unit}", "for example 25 or '40 °C'")
    lo, hi = T_AMBIENT_RANGE
    if not lo <= v <= hi:
        raise BenchError("invalid_args", f"{name} must be between {lo:g} and {hi:g} °C, got {v:g}",
                         "give the ambient temperature in °C, for example 25")
    return v


def _part_name(part: object, kind: str) -> str | None:
    if part is None:
        return None
    if not isinstance(part, str) or not part.strip():
        raise BenchError("invalid_args", f"part must be a part number, got {part!r}",
                         f"known: {', '.join(parts.power_ids(kind))}")
    return part.strip()


def _known(kind: str) -> str:
    """Part numbers of ``kind``, with the catalog module ids that alias them (``mcp1700`` -> MCP1700-3302E/TT)."""
    out = []
    for pid in parts.power_ids(kind):
        rec = parts.find(pid, kind) or {}
        mid = rec.get("module")
        out.append(f"{pid} ({mid})" if isinstance(mid, str) and mid else pid)
    return ", ".join(out)


def _lookup(name: str | None, kind: str) -> tuple[dict[str, Any] | None, str]:
    """(datasheet record or None, reason when None). ``name`` is a part number, an alias or a catalog module id."""
    known = _known(kind)
    if name is None:
        return None, f"give part ({known}) to check against a datasheet"
    try:
        return parts.power_part(name, kind), ""
    except BenchError as e:
        if e.code != "rule_data_missing":
            raise
        partial = parts.find(name, f"{kind}_partial")
        if partial is not None:
            missing = partial.get("missing")
            what = ", ".join(missing) if isinstance(missing, list) and missing else "a value this calculator needs"
            return None, (f"{partial['id']} has only partial datasheet data (missing: {what}); "
                          f"complete parts: {known}")
        return None, parts.unknown_text(name, (kind,), known)


def _chip(chip: object) -> str | None:
    """Chip id from 'ESP32-C3', 'esp32_c3', 'esp32c3'; None stays None (S3 values with a note)."""
    if chip is None:
        return None
    known = chips.ids()
    cid = re.sub(r"[\s_-]", "", chip.lower()) if isinstance(chip, str) else None
    if cid not in known:
        raise BenchError("invalid_args", f"unknown chip {chip!r}", f"known chips: {', '.join(known)}")
    return cid


def _uses_s3_values(chip: str | None) -> bool:
    return chip is None or chip == S3_CHIP


def _rating_q(rating: dict[str, Any], *, conditions: bool = False) -> dict[str, Any]:
    q = _q(rating["value"], rating["unit"])
    return {**q, "conditions": rating.get("conditions", "")} if conditions else q


def _t_ambient_assumption(ta: float) -> dict[str, Any]:
    default = math.isclose(ta, T_AMBIENT_DEFAULT, rel_tol=1e-12)
    return assumption("t_ambient", _f(ta, "°C"), "room temperature; inside a case it is warmer" if default else "given by you")


# --- N-channel MOSFET low-side switch ------------------------------------------------------------------------------
@_action("calc.mosfet")
def mosfet(i_load: object, v_supply: object, *, gate_v: object = GATE_V_DEFAULT, part: object = None,
           r_gate: object = R_GATE_DEFAULT, r_pulldown: object = R_PULLDOWN_DEFAULT, r_ds_on: object = None,
           t_ambient: object = T_AMBIENT_DEFAULT, chip: object = None) -> dict[str, Any]:
    """N-channel MOSFET as a low-side switch, gate driven from a GPIO through R_G with a gate pull-down R_PD."""
    il, vs = _num(i_load, "A", "i_load"), _num(v_supply, "V", "v_supply")
    vg = _num(gate_v, "V", "gate_v")
    rg, rpd = _num(r_gate, "Ω", "r_gate"), _num(r_pulldown, "Ω", "r_pulldown")
    r_user = None if r_ds_on is None else _num(r_ds_on, "Ω", "r_ds_on")
    ta = _temp(t_ambient, "t_ambient")
    chip_id = _chip(chip)
    name = _part_name(part, "nmos")
    rec, reason = _lookup(name, "nmos")

    inputs: dict[str, Any] = {"i_load": _q(il, "A"), "v_supply": _q(vs, "V"), "gate_v": _q(vg, "V"),
                              "r_gate": _q(rg, "Ω"), "r_pulldown": _q(rpd, "Ω"), "t_ambient": _q(ta, "°C")}
    if name is not None:
        inputs["part"] = name
    if r_user is not None:
        inputs["r_ds_on"] = _q(r_user, "Ω")
    if chip_id is not None:
        inputs["chip"] = chip_id

    source_ids: list[str] = [RULE]
    checks: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    assum: list[dict[str, Any]] = []

    v_gs = vg * rpd / (rg + rpd)
    i_g_peak = vg / rg
    i_pd = v_gs / rpd
    steps = [_step("V_GS", f"{_f(vg, 'V')} · {_f(rpd, 'Ω')} / ({_f(rg, 'Ω')} + {_f(rpd, 'Ω')})", v_gs, "V", 4)]

    if math.isclose(vg, GATE_V_DEFAULT, rel_tol=1e-12) and _uses_s3_values(chip_id):
        source_ids.append(WROOM)
        assum.append(assumption(
            "gate_v", _f(vg, "V"),
            ("" if chip_id else S3_DEFAULT_NOTE)
            + f"GPIO high at 3.3 V; the ESP32-S3 guarantees V_OH ≥ {ESP32S3_V_OH_FACTOR:g} × VDD = "
            f"{_f(ESP32S3_V_OH_FACTOR * vg, 'V')} (WROOM-1 datasheet Table 6-3, no load): gate_v "
            f"{ESP32S3_V_OH_FACTOR * vg:g} is the worst case"))
    elif math.isclose(vg, GATE_V_DEFAULT, rel_tol=1e-12) and chip_id is not None:
        assum.append(assumption(
            "gate_v", _f(vg, "V"),
            f"GPIO high at 3.3 V; the guaranteed high level (V_OH) of the {chips.title(chip_id)} is in its datasheet and "
            "is not checked here: give gate_v for the worst case"))
    else:
        assum.append(assumption("gate_v", _f(vg, "V"), "given by you: the high level of the driving pin"))
    assum.append(assumption("v_gs", _f(v_gs, "V", 4), "steady state, R_G and R_PD divide the pin voltage; selects the "
                            "datasheet row"))

    # R_DS(on): your value, else the datasheet row at the highest V_GS not above v_gs
    row = parts.r_ds_on_at(rec["id"], v_gs) if rec is not None else None
    r_on: float | None = None
    basis: dict[str, Any] | None = None
    if rec is not None:
        source_ids.append(rec["source_id"])
        rows = rec["r_ds_on"]["rows"]
        if row is not None:
            checks.append(check("calc.mosfet.logic_level", "passed",
                                f"R_DS(on) max {_f(row['max'], 'Ω')} specified at V_GS {_f(row['v_gs'], 'V')} ≤ "
                                f"{_f(v_gs, 'V')} ({rec['id']} datasheet)"))
        else:
            checks.append(check("calc.mosfet.logic_level", "failed",
                                f"{rec['id']} specifies R_DS(on) only from V_GS {_f(rows[0]['v_gs'], 'V')}; at "
                                f"{_f(v_gs, 'V')} it is not specified"))
            better = [p for p in parts.power_ids("nmos")
                      if p != rec["id"] and parts.r_ds_on_at(p, v_gs) is not None]
            warns.append(warning(
                "mosfet_not_logic_level", "caution",
                f"{rec['id']} is not specified at {_f(v_gs, 'V')} gate drive and may only half turn on. Use a MOSFET "
                f"with R_DS(on) specified at V_GS ≤ {_f(v_gs, 'V')}"
                + (f" (for example {better[0]})" if better else "") + " or a gate driver.", [rec["source_id"]]))
    elif r_user is not None:
        checks.append(check("calc.mosfet.logic_level", "not_checked",
                            "R_DS(on) given by you; give part to check it against a datasheet"))
    else:
        checks.append(check("calc.mosfet.logic_level", "not_checked", reason))
        if name is not None:
            warns.append(warning("part_unknown", "info", f"{reason}; nothing checked against a datasheet (unverified)."))

    if r_user is not None:
        r_on = r_user
        basis = {"from": "user"}
        assum.append(assumption("r_ds_on", _f(r_user, "Ω"), "given by you; take R_DS(on) max at your V_GS from the "
                                "datasheet"))
        if rec is not None:
            warns.append(warning("r_ds_on_given", "info",
                                 "r_ds_on was given, so the datasheet R_DS(on) of the part is not used for P."))
    elif row is not None and rec is not None:
        r_on = float(row["max"])
        basis = {"from": "datasheet", "part": rec["id"], "source_id": rec["source_id"], "v_gs": _q(row["v_gs"], "V"),
                 "i_d": _q(row["i_d"], "A"), "evidence": row["evidence"], "conditions": row["conditions"]}
        assum.append(assumption(
            "r_ds_on", f"{_f(r_on, 'Ω')} max at V_GS {_f(row['v_gs'], 'V')}, I_D {_f(row['i_d'], 'A')}",
            f"{rec['id']} datasheet, {row['conditions']}: highest row ≤ V_GS {_f(v_gs, 'V')} (R_DS(on) falls with "
            "V_GS, so an upper bound at 25 °C); it rises with T_J (datasheet curve), not included in P"))

    p_loss = v_ds = t_j = None
    if r_on is not None:
        p_loss = il ** 2 * r_on
        v_ds = il * r_on
        origin = f"{rec['id']} max at V_GS {_f(row['v_gs'], 'V')} (datasheet)" if rec and row and r_user is None \
            else "your value"
        steps.append(_step("R_DS(on)", origin, r_on, "Ω"))
        steps.append(_step("P", f"({_f(il, 'A')})² · {_f(r_on, 'Ω')}", p_loss, "W"))
        steps.append(_step("V_DS", f"{_f(il, 'A')} · {_f(r_on, 'Ω')}", v_ds, "V"))
    part_info: dict[str, Any] | None = None
    if rec is not None:
        rt = rec["ratings"]
        th = rec["v_gs_th"]
        part_info = {"id": rec["id"], "package": rec["package"], "source_id": rec["source_id"],
                     "v_gs_th": {k: _q(th[k], "V") if th.get(k) is not None else None for k in ("min", "typ", "max")},
                     **{k: _rating_q(rt[k], conditions=k in ("i_d_max", "r_th_ja"))
                        for k in ("v_ds_max", "i_d_max", "v_gs_max", "t_j_max", "r_th_ja")}}
        ok = _le(vs, rt["v_ds_max"]["value"])
        checks.append(check("calc.mosfet.v_ds_max", "passed" if ok else "failed",
                            f"V_supply {_f(vs, 'V')} {'≤' if ok else '>'} V_DS max {_f(rt['v_ds_max']['value'], 'V')} "
                            f"({rec['id']} datasheet)"))
        if not ok:
            warns.append(warning("mosfet_v_ds_max", "danger", f"The supply exceeds the drain-source voltage rating of "
                                 f"{rec['id']}; inductive spikes add to it.", [rec["source_id"]]))
        ok = _le(il, rt["i_d_max"]["value"])
        checks.append(check("calc.mosfet.i_d_max", "passed" if ok else "failed",
                            f"I_load {_f(il, 'A')} {'≤' if ok else '>'} I_D {_f(rt['i_d_max']['value'], 'A')} "
                            f"({rec['id']} datasheet, {rt['i_d_max']['conditions']}); the T_J check is the limit at your "
                            "gate voltage"))
        if not ok:
            warns.append(warning("mosfet_i_d_max", "danger", f"I_load exceeds the continuous drain current of {rec['id']}.",
                                 [rec["source_id"]]))
        if p_loss is not None:
            r_th, t_max = rt["r_th_ja"]["value"], rt["t_j_max"]["value"]
            t_j = ta + p_loss * r_th
            steps.append(_step("T_J", f"{_f(ta, '°C')} + {_f(p_loss, 'W')} · {_f(r_th, '°C/W')}", t_j, "°C"))
            ok = _le(t_j, t_max)
            checks.append(check("calc.mosfet.t_j", "passed" if ok else "failed",
                                f"T_J {_f(t_j, '°C')} {'≤' if ok else '>'} T_J max {_f(t_max, '°C')} "
                                f"(R_θJA {_f(r_th, '°C/W')}, {rec['id']} datasheet)"))
            assum.append(assumption("r_th_ja", _f(r_th, "°C/W"),
                                    f"{rec['id']} datasheet, {rt['r_th_ja']['conditions']}; your board decides"))
            if not ok:
                warns.append(warning("mosfet_overheat", "danger",
                                     f"The MOSFET gets too hot: lower the current, add copper or a heat sink, or use a "
                                     f"part with lower R_DS(on) at {_f(v_gs, 'V')}.", [rec["source_id"]]))
        else:
            checks.append(check("calc.mosfet.t_j", "not_checked", "no R_DS(on) at this gate voltage, so no power"))
        if th.get("max") is not None and v_gs <= th["max"]:
            warns.append(warning("mosfet_below_threshold", "caution",
                                 f"V_GS {_f(v_gs, 'V')} is not above V_GS(th) max {_f(th['max'], 'V')}: the MOSFET may "
                                 "not turn on at all.", [rec["source_id"]]))
        if vg > rt["v_gs_max"]["value"]:
            warns.append(warning("mosfet_v_gs_max", "danger",
                                 f"The gate voltage exceeds V_GS max ±{_f(rt['v_gs_max']['value'], 'V')} of {rec['id']}.",
                                 [rec["source_id"]]))
    else:
        for cid, what in (("v_ds_max", "the drain-source voltage rating"), ("i_d_max", "the drain current rating"),
                          ("t_j", "the junction temperature")):
            checks.append(check(f"calc.mosfet.{cid}", "not_checked", f"give part to compare with {what}"))

    steps.append(_step("I_G,peak", f"{_f(vg, 'V')} / {_f(rg, 'Ω')}", i_g_peak, "A"))
    steps.append(_step("I_PD", f"{_f(v_gs, 'V', 4)} / {_f(rpd, 'Ω')}", i_pd, "A"))

    # gate network: rule of thumb
    g_ok = R_GATE_RANGE[0] <= rg <= R_GATE_RANGE[1]
    pd_ok = R_PULLDOWN_RANGE[0] <= rpd <= R_PULLDOWN_RANGE[1]
    g_range = f"{_f(R_GATE_RANGE[0], 'Ω')}–{_f(R_GATE_RANGE[1], 'Ω')}"
    pd_range = f"{_f(R_PULLDOWN_RANGE[0], 'Ω')}–{_f(R_PULLDOWN_RANGE[1], 'Ω')}"
    bad = [txt for good, txt in ((g_ok, f"R_G {_f(rg, 'Ω')} outside {g_range}"),
                                 (pd_ok, f"R_PD {_f(rpd, 'Ω')} outside {pd_range}")) if not good]
    checks.append(check("calc.mosfet.gate_network", "failed" if bad else "passed",
                        ("; ".join(bad) if bad else f"R_G {_f(rg, 'Ω')} and R_PD {_f(rpd, 'Ω')} in the usual ranges")
                        + " (rule of thumb)"))
    assum.append(assumption("gate_network", f"R_G {g_range}, R_PD {pd_range}",
                            "rule of thumb: R_G limits the pin current into the gate and damps ringing; R_PD keeps the "
                            "MOSFET off while the pin floats (boot, reset, flashing)"))
    assum.append(assumption("load", "DC on/off (no PWM)", "PWM adds switching losses (not included); coils and motors "
                            "need a flyback diode (rule of thumb); low voltage only, never mains"))
    assum.append(_t_ambient_assumption(ta))
    warns.append(warning("gpio_current", "info",
                         f"The gate draws up to {_f(i_g_peak, 'A')} (V_gate / R_G) from the pin for a moment at each "
                         "switching edge. GPIO current limits are not checked here (unverified); see the chip datasheet."))

    result = {
        "inputs": inputs,
        "v_gs": _q(v_gs, "V", 4),
        "r_ds_on": _q(r_on, "Ω") if r_on is not None else None,
        "r_ds_on_basis": basis,
        "p_loss": _q(p_loss, "W") if p_loss is not None else None,
        "v_ds_on": _q(v_ds, "V") if v_ds is not None else None,
        "t_j": _q(t_j, "°C") if t_j is not None else None,
        "i_gate_peak": _q(i_g_peak, "A"),
        "i_pulldown": _q(i_pd, "A"),
        "part": part_info,
        "formula": MOSFET_FORMULA,
        "steps": steps,
    }
    label = f"N-MOSFET {rec['id']}" if rec else "N-MOSFET"
    head = f"{label} low side, {_f(vg, 'V')} gate, {_f(il, 'A')}"
    logic = checks[0]
    if p_loss is not None and v_ds is not None and r_on is not None:
        where = f"at V_GS {_f(row['v_gs'], 'V')}, datasheet" if rec and row and r_user is None else "your value"
        text = f"R_DS(on) {_f(r_on, 'Ω')} ({where}) gives {_f(p_loss, 'W')} loss and {_f(v_ds, 'V')} drop"
        if t_j is not None and rec is not None:
            t_max = rec["ratings"]["t_j_max"]["value"]
            text += f", T_J ≈ {_f(t_j, '°C')} ({'within' if _le(t_j, t_max) else 'above'} T_J max {_f(t_max, '°C')})"
    elif logic["status"] == "failed":
        text = f"not specified at this gate voltage ({logic['detail']})"
    else:
        text = "R_DS(on) unknown (give part or r_ds_on); logic level not checked"
    return envelope("calc.mosfet", f"{head}: {text}.", result, checks=checks, warnings=warns, assumptions=assum,
                    sources=sources.resolve(source_ids))


# --- linear regulator (LDO) ------------------------------------------------------------------------------------------
@_action("calc.ldo")
def ldo(v_in: object, v_out: object, i_load: object, *, part: object = None,
        t_ambient: object = T_AMBIENT_DEFAULT, chip: object = None) -> dict[str, Any]:
    """Linear regulator: dissipation, efficiency, dropout and junction temperature (datasheet values with ``part``)."""
    vi, vo, il = _num(v_in, "V", "v_in"), _num(v_out, "V", "v_out"), _num(i_load, "A", "i_load")
    ta = _temp(t_ambient, "t_ambient")
    chip_id = _chip(chip)
    name = _part_name(part, "ldo")
    rec, reason = _lookup(name, "ldo")
    inputs: dict[str, Any] = {"v_in": _q(vi, "V"), "v_out": _q(vo, "V"), "i_load": _q(il, "A"), "t_ambient": _q(ta, "°C")}
    if name is not None:
        inputs["part"] = name
    if chip_id is not None:
        inputs["chip"] = chip_id
    source_ids: list[str] = [] if rec is None else [rec["source_id"]]
    warns: list[dict[str, Any]] = []
    if name is not None and rec is None:
        warns.append(warning("part_unknown", "info", f"{reason}; nothing checked against a datasheet (unverified)."))
    head = f"LDO {rec['id'] + ' ' if rec else ''}{_f(vi, 'V')} → {_f(vo, 'V')} at {_f(il, 'A')}"
    empty = {"inputs": inputs, "v_headroom": _q(vi - vo, "V"), "p_load": None, "p_q": None, "p_total": None,
             "efficiency": None, "t_j": None, "part": None, "formula": LDO_FORMULA, "steps": []}
    if vi <= vo:
        warns.append(warning("ldo_no_headroom", "caution", "A linear regulator cannot raise the voltage: V_in must be "
                             "above V_out plus the dropout. Use a higher input or a boost converter."))
        return envelope("calc.ldo", f"{head}: V_in is not above V_out, so no linear regulator works.", empty,
                        checks=[check("calc.ldo.headroom", "failed", f"V_in {_f(vi, 'V')} ≤ V_out {_f(vo, 'V')}")],
                        warnings=warns, sources=sources.resolve(source_ids))

    checks = [check("calc.ldo.headroom", "passed", f"V_in {_f(vi, 'V')} > V_out {_f(vo, 'V')}")]
    dv = vi - vo
    iq = float(rec["i_q"]["value"]) if rec else 0.0
    p_load = dv * il
    p_q = vi * iq
    p = p_load + p_q
    eta = vo * il / (vi * (il + iq)) * 100
    steps = [_step("ΔV", f"{_f(vi, 'V')} − {_f(vo, 'V')}", dv, "V"),
             _step("P_load", f"{_f(dv, 'V')} · {_f(il, 'A')}", p_load, "W")]
    assum = [assumption("i_load", "steady (average) current",
                        "T_J follows the average power; check the dropout and the current limit with the peak current "
                        "(rule of thumb)"),
             _t_ambient_assumption(ta)]
    source_ids.append(RULE)
    part_info: dict[str, Any] | None = None
    t_j = None
    if rec is not None:
        rt, do = rec["ratings"], rec["dropout"]
        steps.append(_step("P_q", f"{_f(vi, 'V')} · {_f(iq, 'A')}", p_q, "W"))
        steps.append(_step("P", f"{_f(p_load, 'W')} + {_f(p_q, 'W')}", p, "W"))
        assum.append(assumption("i_q", f"{_f(iq, 'A')} max", f"{rec['id']} datasheet quiescent current "
                                f"({rec['i_q']['conditions']}), used at your V_in as the worst case; it flows from V_in "
                                "to GND"))
        part_info = {"id": rec["id"], "package": rec["package"], "source_id": rec["source_id"],
                     "v_out": _q(rec["v_out"]["value"], "V"), "i_q": _q(iq, "A"),
                     "dropout": {**_q(do["value"], "V"), "i_out": _q(do["i_out"], "A"), "conditions": do["conditions"],
                                 "evidence": do["evidence"]},
                     **{k: _rating_q(rt[k], conditions=k == "r_th_ja")
                        for k in ("v_in_max", "i_limit_min", "t_j_max", "r_th_ja", "t_shutdown")}}
        # dropout: one datasheet point (max at I_OUT 0.8 A, lower at lower currents)
        if _le(il, do["i_out"]):
            ok = _le(do["value"], dv)
            checks.append(check("calc.ldo.dropout", "passed" if ok else "failed",
                                f"V_in − V_out {_f(dv, 'V')} {'≥' if ok else '<'} dropout max {_f(do['value'], 'V')} "
                                f"at {_f(do['i_out'], 'A')} ({rec['id']} datasheet)"))
            assum.append(assumption("dropout", f"{_f(do['value'], 'V')} max at {_f(do['i_out'], 'A')}",
                                    f"{rec['id']} datasheet: the dropout decreases at lower load currents, so this "
                                    "value is used for every I_load up to it (conservative)"))
            if not ok:
                warns.append(warning("ldo_dropout", "caution",
                                     f"V_in − V_out is below the dropout of {rec['id']}: the output may sag below "
                                     f"{_f(vo, 'V')}. Raise V_in or use a regulator with a lower dropout.",
                                     [rec["source_id"]]))
        else:
            checks.append(check("calc.ldo.dropout", "not_checked",
                                f"the datasheet specifies the dropout up to {_f(do['i_out'], 'A')}; above it is higher"))
        lim = rt["i_limit_min"]["value"]
        ok = _le(il, lim)
        checks.append(check("calc.ldo.current_limit", "passed" if ok else "failed",
                            f"I_load {_f(il, 'A')} {'≤' if ok else '>'} current limit min {_f(lim, 'A')} "
                            f"({rec['id']} datasheet)"))
        if not ok:
            warns.append(warning("ldo_current_limit", "danger", f"I_load is above the guaranteed current limit of "
                                 f"{rec['id']}: the output may collapse.", [rec["source_id"]]))
        vmax = rt["v_in_max"]["value"]
        ok = _le(vi, vmax)
        checks.append(check("calc.ldo.v_in_max", "passed" if ok else "failed",
                            f"V_in {_f(vi, 'V')} {'≤' if ok else '>'} {_f(vmax, 'V')} ({rec['id']} absolute maximum)"))
        if not ok:
            warns.append(warning("ldo_v_in_max", "danger", f"V_in exceeds the absolute maximum input of {rec['id']}.",
                                 [rec["source_id"]]))
        r_th, t_max = rt["r_th_ja"]["value"], rt["t_j_max"]["value"]
        t_j = ta + p * r_th
        steps.append(_step("T_J", f"{_f(ta, '°C')} + {_f(p, 'W')} · {_f(r_th, '°C/W')}", t_j, "°C"))
        ok = _le(t_j, t_max)
        checks.append(check("calc.ldo.t_j", "passed" if ok else "failed",
                            f"T_J {_f(t_j, '°C')} {'≤' if ok else '>'} T_J max {_f(t_max, '°C')} "
                            f"(θ_JA {_f(r_th, '°C/W')}, {rec['package']}, {rec['id']} datasheet)"))
        assum.append(assumption("theta_ja", _f(r_th, "°C/W"),
                                f"{rec['id']} datasheet, {rt['r_th_ja']['conditions']}; your board decides"))
        if not ok:
            warns.append(warning("ldo_overheat", "danger",
                                 f"The regulator gets too hot (thermal shutdown above about "
                                 f"{_f(rt['t_shutdown']['value'], '°C')}): lower V_in or the current, add copper, or "
                                 "use a switching regulator.", [rec["source_id"]]))
        nominal = rec["v_out"]["value"]
        if not math.isclose(vo, nominal, rel_tol=LDO_V_OUT_REL_TOL):
            warns.append(warning("ldo_v_out_mismatch", "caution",
                                 f"{rec['id']} is a fixed {_f(nominal, 'V')} regulator; v_out {_f(vo, 'V')} does not "
                                 "match. The results use your v_out.", [rec["source_id"]]))
    else:
        assum.append(assumption("i_q", "not included", "give part for the quiescent current; P counts the load "
                                "current only"))
        for cid, what in (("dropout", "the dropout"), ("current_limit", "the current limit"),
                          ("v_in_max", "the input voltage rating"), ("t_j", "the junction temperature")):
            checks.append(check(f"calc.ldo.{cid}", "not_checked", f"{what} not checked: {reason}"))
    steps.append(_step("η", f"{_f(vo, 'V')} · {_f(il, 'A')} / ({_f(vi, 'V')} · {_f(il + iq, 'A')})", eta, "%"))
    lo, hi = ESP32S3_VDD33
    if chip_id is not None and not _uses_s3_values(chip_id):
        assum.append(assumption("chip_supply", f"{chips.title(chip_id)}: not checked",
                                "the supply current the module needs is in its datasheet; Wi-Fi transmit peaks add to "
                                "I_load"))
    elif lo <= vo <= hi:
        source_ids.append(WROOM)
        below = il < ESP32S3_I_VDD_MIN
        warns.append(warning(
            "esp32s3_supply", "info",
            ("" if chip_id else S3_DEFAULT_NOTE)
            + f"For an ESP32-S3-WROOM-1 module the datasheet asks for a supply that delivers at least "
            f"{_f(ESP32S3_I_VDD_MIN, 'A')} (Table 6-2); Wi-Fi TX peaks at {_f(ESP32S3_TX_PEAK, 'A')} (Table 6-4). "
            f"I_load {_f(il, 'A')} is {'below' if below else 'at or above'} that.", [WROOM]))

    result = {**empty, "p_load": _q(p_load, "W"), "p_q": _q(p_q, "W") if rec else None, "p_total": _q(p, "W"),
              "efficiency": _q(eta, "%"), "t_j": _q(t_j, "°C") if t_j is not None else None, "part": part_info,
              "steps": steps}
    text = f"{_f(p, 'W')} in the regulator, efficiency {_f(eta, '%')}"
    if rec is not None and t_j is not None:
        drop = next(c for c in checks if c["id"] == "calc.ldo.dropout")["status"]
        t_max = rec["ratings"]["t_j_max"]["value"]
        verdict = {"passed": "ok", "failed": "too low",
                   "not_checked": f"not checked above {_f(rec['dropout']['i_out'], 'A')}"}[drop]
        text += (f", T_J ≈ {_f(t_j, '°C')} ({'within' if _le(t_j, t_max) else 'above'} T_J max {_f(t_max, '°C')}); "
                 f"dropout {verdict}")
    else:
        text += " (load current only); dropout and temperature not checked (no part)"
    return envelope("calc.ldo", f"{head}: {text}.", result, checks=checks, warnings=warns, assumptions=assum,
                    sources=sources.resolve(source_ids))


# --- registration (calckit; name, unit, required, default; "°C" = temperature) -------------------------------------
MOSFET_PARAMS: tuple[tuple[str, str, bool, Any], ...] = (
    ("i_load", "A", True, None), ("v_supply", "V", True, None), ("gate_v", "V", False, GATE_V_DEFAULT),
    ("part", "str", False, None), ("r_gate", "Ω", False, R_GATE_DEFAULT), ("r_pulldown", "Ω", False, R_PULLDOWN_DEFAULT),
    ("r_ds_on", "Ω", False, None), ("t_ambient", "°C", False, T_AMBIENT_DEFAULT), ("chip", "str", False, None))
LDO_PARAMS: tuple[tuple[str, str, bool, Any], ...] = (
    ("v_in", "V", True, None), ("v_out", "V", True, None), ("i_load", "A", True, None), ("part", "str", False, None),
    ("t_ambient", "°C", False, T_AMBIENT_DEFAULT), ("chip", "str", False, None))
calckit.register("mosfet", mosfet, MOSFET_PARAMS, title="N-MOSFET low-side switch", group="basics",
                 summary="N-channel MOSFET at a GPIO: gate voltage, R_DS(on) from the datasheet, loss, junction temperature.")
ldo.choices = lambda: {"part": parts.ids_of("ldo")}  # type: ignore[attr-defined]  # calckit.meta
calckit.register("ldo", ldo, LDO_PARAMS, title="Linear regulator (LDO)", group="basics",
                 summary="Linear regulator: dissipation, efficiency, dropout and junction temperature from the datasheet.")
