"""Family rules ``nlevel``: further level shifters and 5 V logic.

Parts: PCA9306 (I²C pass switch), SN74LVC1T45 / SN74LVC8T245 (dual-supply transceivers with DIR), SN74LVC125A,
SN74HCT595, CD74HCT4067. The generic rules see one ``io`` block (the A side); these rules add what they cannot see:

- ``mod.nlevel.pca9306_bias`` (``mod_nlevel_pca9306_bias``): VREF2 straight on a rail (no bias resistor) ->
  caution: the current into VREF1 is limited only by RCC (TI SCPS113O p. 15, eq. 6, RCC(min) = (VCC2 − VREF1 −
  0.6 V) / 128 mA) and the EN/VREF2 regulation of p. 18 is lost; a bias resistor below RCC(min) -> danger; VREF1
  above VREF2 − 0.6 V on known rails -> caution (no translation, p. 5 note 1), VREF1 = VREF2 -> passed (plain switch,
  p. 12); VREF1 below 1.2 V -> caution. Unknown voltages -> not_checked.
- ``mod.nlevel.pca9306_shared_bus`` (``mod_nlevel_pca9306_shared_bus``): with EN not on GND the two sides form one
  electrical bus, so two I²C devices with the same address on the SDA1 side and the SDA2 side collide -> danger.
  (The generic address check stops at the bridge: devices behind it are on no ESP bus.)
- ``mod.nlevel.dir_contention`` (``mod_nlevel_dir_contention``): SN74LVC1T45/8T245 with DIR tied to a rail (high =
  A to B, low = B to A; p. 14 / p. 15): an ESP output on the side that is the output -> danger (two push-pull
  drivers); an ESP input on the side that is the input -> caution (nothing drives it); the ESP receiving on the
  output side while that side's supply exceeds the ESP input maximum -> danger. DIR on a GPIO -> passed (firmware
  sets the direction), DIR open / unknown -> not_checked.
- ``mod.nlevel.oe_disabled`` (``mod_nlevel_oe_disabled``): an enable that keeps the part off: SN74LVC125A xOE,
  SN74LVC8T245 OE, SN74HCT595 OE or CD74HCT4067 E on a rail above 0 V (or on VCC) -> caution; PCA9306 EN on GND ->
  caution (sides disconnected, p. 16).

Fixed numbers (tests/test_mod_nlevel.py checks each against the excerpt): PCA_VTH_V and PCA_I_MAX_A (p. 15 / p. 5),
PCA_VREF1_MIN_V (p. 5).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule

SRC = {m: f"mod-nlevel-{m}-ds" for m in ("pca9306", "sn74lvc1t45", "sn74lvc8t245", "sn74lvc125a", "sn74hct595",
                                         "cd74hct4067")}
PCA_VTH_V = 0.6  # p. 15: "• Vth is approximately 0.6V" (Ven = VREF1 + Vth)
PCA_I_MAX_A = 0.128  # p. 15 eq. 6 "RCC(min) ≥ (VCC2 - Ven)/0.128"; p. 5 "Continuous channel current 128 mA"
PCA_VREF1_MIN_V = 1.2  # p. 5 note 1: "VREF1 supports 1.2 V to VREF2 - 0.6 V"
TRANSCEIVERS = ("sn74lvc1t45", "sn74lvc8t245")
ESP_OUT_MODES = frozenset({"out", "pwm", "uart_tx", "spi_mosi", "spi_sck", "spi_cs"})
ESP_IN_MODES = frozenset({"in", "in_pullup", "in_pulldown", "uart_rx", "spi_miso", "adc"})
_EPS = 1e-9
_PREFIX = {"": 1.0, "R": 1.0, "r": 1.0, "k": 1e3, "K": 1e3, "M": 1e6}
_OHMS_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kKM]?)\s*(?:\u2126|\u03a9|ohms?|R)?\s*$")
_RKM_RE = re.compile(r"^\s*(\d+)([RrkKM])(\d+)\s*$")


# --- helpers ------------------------------------------------------------------------------------------------------
def ohms(value: Any) -> float | None:
    """Ohms from 200000, '200k', '4k7', '10 kΩ', '220R'; None if not a plain resistance."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if value > 0 else None
    if not isinstance(value, str):
        return None
    m = _RKM_RE.match(value)
    if m:
        return float(f"{m.group(1)}.{m.group(3)}") * _PREFIX[m.group(2)]
    m = _OHMS_RE.match(value)
    if m:
        v = float(m.group(1)) * _PREFIX[m.group(2)]
        return v if v > 0 else None
    return None


def _instances(ctx: Ctx, *ids: str) -> list[Instance]:
    return [i for i in ctx.instances if i.module_id in ids]


def _resistors(ctx: Ctx, net: str) -> list[tuple[str, float | None, str | None]]:
    """(ref, ohms or None, other net) for every plain resistor part with one pin on ``net``."""
    out = []
    for part in ctx.parts:
        if part.get("module") or not isinstance(part.get("conn"), Mapping):
            continue
        kind = str(part.get("kind") or "").lower()
        if kind != "resistor" and not (not kind and re.fullmatch(r"R\d+", str(part.get("ref")))):
            continue
        nets = [str(n) for n in part["conn"].values()]
        if net in nets and len(nets) == 2:
            other = nets[1] if nets[0] == net else nets[0]
            out.append((str(part.get("ref")), ohms(part.get("value")), other if other != net else None))
    return out


def _modes(ctx: Ctx, net: str | None) -> list[str]:
    return list(ctx.nets.get(net, {}).get("modes", [])) if net else []


def _gpio_text(ctx: Ctx, net: str) -> str:
    g = list(ctx.nets.get(net, {}).get("gpios", []))
    return ", ".join(f"GPIO{n}" for n in g) if g else net


def _is_rail(ctx: Ctx, net: str | None) -> bool:
    return bool(net) and net in ctx.rails


def _i2c_pin(inst: Instance, sig: str) -> str | None:
    return next((str(p["name"]) for p in inst.module.get("pins") or []
                 if isinstance(p, Mapping) and p.get("signal") == sig), None)


# --- PCA9306 ------------------------------------------------------------------------------------------------------
@rule("mod.nlevel.pca9306_bias")
def pca9306_bias(ctx: Ctx) -> list[Finding]:
    rid, out = "mod.nlevel.pca9306_bias", []
    for inst in _instances(ctx, "pca9306"):
        src = SRC["pca9306"]
        n1, n2 = ctx.net_of(inst, "VREF1"), ctx.net_of(inst, "VREF2")
        v1 = ctx.volts(n1) if n1 else None
        bad = False
        if n2 is None:
            out.append(Finding(rid, "not_checked", "info", f"{ctx.label(inst)}: VREF2 not connected; bias not checked.",
                               [inst.ref], [src]))
            continue
        # high-side supply VCC2: VREF2 straight on a rail, or the rail at the far end of its bias resistor
        if _is_rail(ctx, n2) and (ctx.volts(n2) or 0.0) > _EPS:
            v2 = ctx.volts(n2)
            bad = True
            rmin = (v2 - (v1 or 0.0) - PCA_VTH_V) / PCA_I_MAX_A if v1 is not None else None
            hint = f" (RCC(min) = {fmt(rmin, 'Ω')} at VREF1 {fmt(v1, 'V')})" if rmin and rmin > 0 else ""
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{ctx.label(inst)}: VREF2 sits straight on {n2}. The datasheet ties EN and VREF2 "
                                   f"together and pulls both to the high-side supply through a 200 kΩ resistor; "
                                   f"without it only RCC limits the current from VREF2 into VREF1{hint}. Add the "
                                   "200 kΩ bias resistor (breakouts usually carry it: confirm the board).",
                                   inst, source_id=src))
            vcc2 = v2
        else:
            res = [(r, o, other) for r, o, other in _resistors(ctx, n2) if _is_rail(ctx, other)
                   and (ctx.volts(other) or 0.0) > _EPS]
            vcc2 = max((ctx.volts(o) or 0.0 for _, _, o in res), default=None)
            if res and v1 is not None and vcc2 is not None:
                rmin = (vcc2 - v1 - PCA_VTH_V) / PCA_I_MAX_A
                low = [(r, o) for r, o, _ in res if o is not None and o < rmin - _EPS]
                if low:
                    bad = True
                    out.append(ctx.finding(rid, "failed", "danger",
                                           f"{ctx.label(inst)}: bias resistor {', '.join(r for r, _ in low)} "
                                           f"({', '.join(fmt(o, 'Ω') for _, o in low)}) on VREF2 is below "
                                           f"RCC(min) = (VCC2 − VREF1 − 0.6 V) / 128 mA = {fmt(rmin, 'Ω')}: the "
                                           "current exceeds the 128 mA channel maximum. Use 200 kΩ.",
                                           inst, source_id=src))
        if v1 is not None and vcc2 is not None:
            if abs(v1 - vcc2) <= _EPS:
                out.append(Finding(rid, "passed", None,
                                   f"{ctx.label(inst)}: VREF1 = VREF2 supply = {fmt(v1, 'V')}: the PCA9306 works "
                                   "as a plain bus switch (no translation).", [inst.ref], [src]))
                continue
            if v1 > vcc2 - PCA_VTH_V + _EPS:
                bad = True
                out.append(ctx.finding(rid, "failed", "caution",
                                       f"{ctx.label(inst)}: VREF1 {fmt(v1, 'V')} is not at least 0.6 V below the "
                                       f"high-side supply {fmt(vcc2, 'V')}; translation needs VREF2 ≥ VREF1 + 0.6 V. "
                                       "Put the lower bus voltage on VREF1.", inst, source_id=src))
            if v1 < PCA_VREF1_MIN_V - _EPS:
                bad = True
                out.append(ctx.finding(rid, "failed", "caution",
                                       f"{ctx.label(inst)}: VREF1 {fmt(v1, 'V')} is below the 1.2 V the "
                                       "translation needs.", inst, source_id=src))
            if not bad:
                out.append(Finding(rid, "passed", None,
                                   f"{ctx.label(inst)}: VREF1 {fmt(v1, 'V')}, high side {fmt(vcc2, 'V')}, bias "
                                   "resistor present.", [inst.ref], [src]))
        elif not bad:
            out.append(Finding(rid, "not_checked", "info",
                               f"{ctx.label(inst)}: VREF1 or the high-side supply behind VREF2 is unknown; bias and "
                               "translation range not checked.", [inst.ref], [src]))
    return out


@rule("mod.nlevel.pca9306_shared_bus")
def pca9306_shared_bus(ctx: Ctx) -> list[Finding]:
    rid, out = "mod.nlevel.pca9306_shared_bus", []
    for inst in _instances(ctx, "pca9306"):
        src = SRC["pca9306"]
        en = ctx.net_of(inst, "EN")
        if en == "GND":
            continue  # disconnected sides (mod.nlevel.oe_disabled reports it)
        s1, s2 = ctx.net_of(inst, "SDA1"), ctx.net_of(inst, "SDA2")
        if not s1 or not s2:
            continue

        def side(net: str, me: Instance = inst) -> list[Instance]:
            res = []
            for i in ctx.instances:
                if i.ref == me.ref or not i.address:
                    continue
                pin = _i2c_pin(i, "i2c_sda")
                if pin and i.conn.get(pin) == net:
                    res.append(i)
            return res
        low, high = side(s1), side(s2)
        if not low or not high:
            continue
        hits = [(a, b) for a in low for b in high if a.address == b.address]
        if hits:
            txt = "; ".join(f"{ctx.label(a)} on {s1} and {ctx.label(b)} on {s2} at {a.address}" for a, b in hits)
            out.append(ctx.finding(rid, "failed", "danger",
                                   f"{ctx.label(inst)} joins both sides into one bus while EN is high: {txt}. Change "
                                   "one address, or switch EN from a GPIO so only one side is connected at a time.",
                                   [inst] + [x for ab in hits for x in ab], source_id=src, chip_fact=False))
        else:
            out.append(Finding(rid, "passed", None,
                               f"{ctx.label(inst)}: no address appears on both sides ({s1} / {s2}).", [inst.ref], [src]))
    return out


# --- SN74LVC1T45 / SN74LVC8T245 -------------------------------------------------------------------------------------
def _pairs(inst: Instance) -> list[tuple[str, str]]:
    if inst.module_id == "sn74lvc1t45":
        return [("A", "B")]
    return [(f"A{i}", f"B{i}") for i in range(1, 9)]


@rule("mod.nlevel.dir_contention")
def dir_contention(ctx: Ctx) -> list[Finding]:
    rid, out = "mod.nlevel.dir_contention", []
    esp_max = ctx.esp.get("v_in_max") if isinstance(ctx.esp, Mapping) else None
    for inst in _instances(ctx, *TRANSCEIVERS):
        src = SRC[inst.module_id]
        dnet = ctx.net_of(inst, "DIR")
        esp_pins = [(a, b) for a, b in _pairs(inst)
                    if _modes(ctx, ctx.net_of(inst, a)) or _modes(ctx, ctx.net_of(inst, b))]
        if not esp_pins:
            continue
        if dnet is None:
            out.append(Finding(rid, "not_checked", "info", f"{ctx.label(inst)}: DIR open; direction unknown.",
                               [inst.ref], [src]))
            continue
        if _modes(ctx, dnet):
            out.append(Finding(rid, "passed", None,
                               f"{ctx.label(inst)}: DIR on {_gpio_text(ctx, dnet)}: the firmware sets the direction "
                               "(switch DIR before the other side drives).", [inst.ref], [src]))
            continue
        dv = ctx.volts(dnet)
        if dv is None:
            out.append(Finding(rid, "not_checked", "info",
                               f"{ctx.label(inst)}: DIR on {dnet} with unknown level; direction not checked.",
                               [inst.ref], [src]))
            continue
        a_to_b = dv > _EPS
        out_side, in_side = ("B", "A") if a_to_b else ("A", "B")
        sv = ctx.supply_volts(inst)
        clash, idle, hot = [], [], []
        for a, b in esp_pins:
            pins = {"A": a, "B": b}
            for s in ("A", "B"):
                net = ctx.net_of(inst, pins[s])
                modes = set(_modes(ctx, net))
                if not modes or not net:
                    continue
                where = f"{pins[s]} on {_gpio_text(ctx, net)}"
                if s == out_side and modes & ESP_OUT_MODES:
                    clash.append(where)
                elif s == in_side and modes <= ESP_IN_MODES:
                    idle.append(where)
                elif s == out_side and modes & ESP_IN_MODES:
                    vo = sv.get(f"VCC{s}")
                    if vo is not None and isinstance(esp_max, int | float) and vo > esp_max + _EPS:
                        hot.append((where, vo))
        dir_txt = f"DIR on {dnet} ({'high: A to B' if a_to_b else 'low: B to A'})"
        if clash:
            out.append(ctx.finding(rid, "failed", "danger",
                                   f"{ctx.label(inst)}: {dir_txt} makes the {out_side} side an output, but the ESP "
                                   f"drives {', '.join(clash)}: two push-pull outputs fight. Flip DIR or move the "
                                   "ESP to the other side.", inst, source_id=src))
        if hot:
            out.append(ctx.finding(rid, "failed", "danger",
                                   f"{ctx.label(inst)}: {dir_txt}; the {out_side} side drives "
                                   f"{', '.join(w for w, _ in hot)} at VCC{out_side} {fmt(hot[0][1], 'V')}, above the "
                                   f"ESP input maximum {fmt(esp_max, 'V')}. Put the ESP on the side whose supply is "
                                   "the ESP supply.", inst, source_id=src))
        if idle:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{ctx.label(inst)}: {dir_txt} makes the {in_side} side an input, but the ESP only "
                                   f"reads {', '.join(idle)}: nothing drives that pin. Flip DIR.", inst,
                                   source_id=src))
        if not (clash or hot or idle):
            out.append(Finding(rid, "passed", None,
                               f"{ctx.label(inst)}: {dir_txt} fits the ESP pins.", [inst.ref], [src]))
    return out


# --- enables ------------------------------------------------------------------------------------------------------
_ENABLES: dict[str, tuple[str, ...]] = {"sn74lvc125a": ("1OE", "2OE", "3OE", "4OE"), "sn74lvc8t245": ("OE",),
                                        "sn74hct595": ("OE",), "cd74hct4067": ("E",)}
_OFF_TEXT = {"sn74lvc125a": "the buffer output stays high-impedance", "sn74lvc8t245": "both ports stay Hi-Z (isolation)",
             "sn74hct595": "QA–QH stay high-impedance", "cd74hct4067": "all 16 switches stay off"}


@rule("mod.nlevel.oe_disabled")
def oe_disabled(ctx: Ctx) -> list[Finding]:
    rid, out = "mod.nlevel.oe_disabled", []
    for inst in _instances(ctx, *_ENABLES):
        src = SRC[inst.module_id]
        vcc_nets = {ctx.net_of(inst, p) for p in ("VCC", "VCCA", "VCCB")} - {None}
        off, seen = [], []
        for pin in _ENABLES[inst.module_id]:
            net = ctx.net_of(inst, pin)
            if net is None:
                continue
            if inst.module_id == "sn74lvc125a":
                ch = pin[0]
                used = any(ctx.net_of(inst, f"{ch}{x}") not in (None, "GND") and not _is_rail(
                    ctx, ctx.net_of(inst, f"{ch}{x}")) for x in ("A", "Y"))
                if not used:
                    continue
            seen.append(pin)
            v = ctx.volts(net)
            if not _modes(ctx, net) and (net in vcc_nets or (v is not None and v > _EPS)):
                off.append(f"{pin} on {net}")
        if off:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{ctx.label(inst)}: {', '.join(off)} (active low): {_OFF_TEXT[inst.module_id]}. "
                                   "Tie it to GND or drive it from a GPIO.", inst, source_id=src))
        elif seen:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: {', '.join(seen)} not held high.",
                               [inst.ref], [src]))
    for inst in _instances(ctx, "pca9306"):
        net = ctx.net_of(inst, "EN")
        if net is None:
            continue
        v = ctx.volts(net)
        if v is not None and abs(v) <= _EPS:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{ctx.label(inst)}: EN on {net}: the switch is off and both sides stay "
                                   "disconnected. Tie EN to VREF2 (200 kΩ to the high-side supply).", inst,
                                   source_id=SRC["pca9306"]))
        else:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: EN on {net}.", [inst.ref],
                               [SRC["pca9306"]]))
    return out
