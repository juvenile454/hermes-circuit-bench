"""Family rules ``level``: level shifters.

Translators have two supply domains (A side = VCCA, B side = VCCB; BSS138: source = low side, drain = high side).
The catalogue ``io`` block describes the A side only; these rules add what the generic level rules cannot see:

- ``mod.level.txb_not_i2c``: a TXB0104 data pin on an I²C / 1-Wire net -> caution (TI SCES650K p. 22). The
  failed finding supersedes ``mod.pin_role`` and ``mod.unconnected`` on the same TXB (one cause, one warning).
- ``mod.level.txb_pull_resistor``: an external resistor below 50 kΩ on a TXB0104 data net -> caution (p. 22).
- ``mod.level.txs_pulldown``: a pull-down on a TXS0108E data net lowers VOH = Vccx × RPD / (RPD + 4 kΩ)
  (TI SCES642L p. 20, eq. 1) -> info; caution when VOH falls below the VIH of a receiver on the same net.
- ``mod.level.ahct_needs_5v``: SN74AHCT125 VCC below 4.5 V -> info (TTL thresholds only at VCC 4.5–5.5 V).
- ``mod.level.side_supply``: VCCA above VCCB -> caution; an ESP GPIO on the B side while VCCB exceeds the ESP input
  maximum -> danger (B-side pull-up to VCCB / VOHB ≥ VCCB − 0.4 V).
- ``mod.level.oe_disabled``: translator OE on GND (TXS/TXB) or AHCT xOE on a high rail -> the channel never passes
  data -> caution.
- ``mod.level.bss138_wiring``: BSS138 per NXP/Nexperia AN10441: gate on a rail above VGS(th) max 1.5 V, ESP on the
  source (low) side, source pull-up to the gate supply, drain pull-up rail ≥ gate supply -> caution otherwise.

Fixed numbers used here (each with its source and page; tests/test_mod_level.py checks them against the excerpts):
TXB_PULL_MIN_OHM (TXB0104 p. 22), BSS138_VGS_TH_MAX_V (BSS138 p. 2). The TXS pull-up (4 kΩ) comes from the module
data (pins[].internal_pull, p. 16).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule

SRC_TXS = "mod-level-txs0108e-ds"
SRC_TXB = "mod-level-txb0104-ds"
SRC_AHCT = "mod-level-sn74ahct125-ds"
SRC_BSS = "mod-level-bss138-ds"
SRC_AN = "mod-level-an10441"

TXB_PULL_MIN_OHM = 50e3  # TXB0104 p. 22: "their values must be kept higher than 50 kΩ"
BSS138_VGS_TH_MAX_V = 1.5  # BSS138/D p. 2: "VGS(th) Gate Threshold Voltage VDS = VGS, ID = 1 mA 0.8 1.3 1.5 V"
TXS_PULLUP_FALLBACK_OHM = 4e3  # used only if the data lacks pins[].internal_pull (TXS0108E p. 16)

TWO_SIDED = {"txs0108e": SRC_TXS, "txb0104": SRC_TXB}
I2C_SIGNALS = ("i2c_sda", "i2c_scl", "onewire")
I2C_MODES = ("i2c_sda", "i2c_scl")
_EPS = 1e-9

_PREFIX = {"": 1.0, "R": 1.0, "r": 1.0, "k": 1e3, "K": 1e3, "M": 1e6}
_OHMS_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kKM]?)\s*(?:\u2126|\u03a9|ohms?|R)?\s*$")
_RKM_RE = re.compile(r"^\s*(\d+)([RrkKM])(\d+)\s*$")


# --- helpers ------------------------------------------------------------------------------------------------------
def ohms(value: Any) -> float | None:
    """Ohms from 4700, '4k7', '4.7k', '10 kΩ', '220R', '1M'; None if not a plain resistance."""
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


def _data_pins(inst: Instance) -> list[str]:
    """A/B data pins of a translator (A1..A8, then B1..B8)."""
    names = [str(p["name"]) for p in inst.module.get("pins") or []
             if isinstance(p, Mapping) and re.fullmatch(r"[AB]\d", str(p.get("name")))]
    return sorted(names, key=lambda n: (n[0], int(n[1:])))


def _side_supply(pin: str) -> str:
    return "VCCA" if pin.startswith("A") else "VCCB"


def _signals_on(ctx: Ctx, net: str, skip_ref: str) -> list[tuple[Instance, str, str]]:
    """(instance, pin, signal) of other module pins on the net."""
    out = []
    for ref, pin in ctx.nets.get(net, {}).get("pins", []):
        if ref == skip_ref:
            continue
        try:
            other = ctx.instance(ref)
        except KeyError:
            continue
        sig = next((p.get("signal") for p in other.module.get("pins") or []
                    if isinstance(p, Mapping) and p.get("name") == pin), None)
        out.append((other, pin, str(sig)))
    return out


def _gpios(ctx: Ctx, net: str | None) -> list[int]:
    return list(ctx.nets.get(net, {}).get("gpios", [])) if net else []


def _gpio_text(ctx: Ctx, net: str) -> str:
    g = _gpios(ctx, net)
    return ", ".join(f"GPIO{n}" for n in g) if g else net


def _resistors(ctx: Ctx, net: str) -> list[tuple[str, float | None, str | None]]:
    """(ref, ohms or None, other net) for every plain resistor part with one pin on ``net``."""
    kinds = {p.get("ref"): p for p in ctx.parts if not p.get("module")}
    pins_by_ref: dict[str, dict[str, str]] = {}
    for n, info in ctx.nets.items():
        for ref, pin in info.get("pins", []):
            if ref in kinds:
                pins_by_ref.setdefault(ref, {})[pin] = n
    out = []
    for ref, pins in pins_by_ref.items():
        part = kinds[ref]
        kind = str(part.get("kind") or "").lower()
        if kind != "resistor" and not (not kind and re.fullmatch(r"R\d+", str(ref))):
            continue
        if net not in pins.values():
            continue
        others = [n for n in pins.values() if n != net]
        out.append((ref, ohms(part.get("value")), others[0] if others else None))
    return out


def _txs_pullup(inst: Instance) -> tuple[float, Any]:
    for p in inst.module.get("pins") or []:
        ip = p.get("internal_pull") if isinstance(p, Mapping) else None
        if isinstance(ip, Mapping) and isinstance(ip.get("up"), Mapping) and isinstance(ip["up"].get("value"), int | float):
            return float(ip["up"]["value"]), ip["up"]
    return TXS_PULLUP_FALLBACK_OHM, None


def _is_i2c_net(ctx: Ctx, net: str, skip_ref: str) -> str | None:
    """Why the net is an I²C / 1-Wire line (text), or None."""
    modes = [m for m in ctx.nets.get(net, {}).get("modes", []) if m in I2C_MODES]
    if modes:
        return f"ESP {modes[0]}"
    for other, pin, sig in _signals_on(ctx, net, skip_ref):
        if sig in I2C_SIGNALS:
            return f"{other.ref} {pin} ({sig})"
    return None


# --- rules --------------------------------------------------------------------------------------------------------
@rule("mod.level.txb_not_i2c")
def txb_not_i2c(ctx: Ctx) -> list[Finding]:
    rid, out = "mod.level.txb_not_i2c", []
    for inst in _instances(ctx, "txb0104"):
        hits, used = [], []
        for pin in _data_pins(inst):
            net = ctx.net_of(inst, pin)
            if net is None or net in ctx.rails:
                continue
            used.append(pin)
            why = _is_i2c_net(ctx, net, inst.ref)
            if why:
                hits.append(f"{pin} on {net} ({why})")
        if not used:
            continue
        if hits:
            f = ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(inst)}: {'; '.join(hits)}. The TXB0104 must not be used for I²C or 1-Wire (open-drain "
                "drivers fight its weak auto-direction outputs); use a TXS0108E or the BSS138 circuit (AN10441).",
                inst, source_id=SRC_TXB)
            # one cause, one warning: the generic pin-role / open-net findings on this TXB come from the I²C use
            # (failed only: a passing TXB check must not lower unrelated findings)
            f.supersedes = ("mod.pin_role", "mod.unconnected")
            out.append(f)
        else:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: no I²C or 1-Wire line on the data pins.",
                               [inst.ref], [SRC_TXB]))
    return out


@rule("mod.level.txb_pull_resistor")
def txb_pull_resistor(ctx: Ctx) -> list[Finding]:
    rid, out = "mod.level.txb_pull_resistor", []
    for inst in _instances(ctx, "txb0104"):
        bad, unknown, ok = [], [], []
        for pin in _data_pins(inst):
            net = ctx.net_of(inst, pin)
            if net is None or net in ctx.rails:
                continue
            for ref, r, other in _resistors(ctx, net):
                if other is None or other not in ctx.rails:
                    continue  # series resistor or unknown far end: not a pull resistor
                if r is None:
                    unknown.append(ref)
                elif r <= TXB_PULL_MIN_OHM + _EPS:
                    bad.append(f"{ref} {fmt(r, 'Ω')} on {pin} to {other}")
                else:
                    ok.append(ref)
        refs = [inst.ref]
        if bad:
            out.append(ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(inst)}: {'; '.join(bad)}. External pull-up/pull-down resistors on TXB0104 data lines "
                f"must be higher than {fmt(TXB_PULL_MIN_OHM, 'Ω')} (weak output drivers).", inst, source_id=SRC_TXB))
        if unknown:
            out.append(Finding(rid, "not_checked", "info",
                               f"{ctx.label(inst)}: resistor value of {', '.join(unknown)} not readable; TXB0104 "
                               f"pull resistors must be higher than {fmt(TXB_PULL_MIN_OHM, 'Ω')}.",
                               refs + unknown, [SRC_TXB]))
        if ok and not bad and not unknown:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: pull resistors {', '.join(ok)} are above "
                               f"{fmt(TXB_PULL_MIN_OHM, 'Ω')}.", refs + ok, [SRC_TXB]))
    return out


@rule("mod.level.txs_pulldown")
def txs_pulldown(ctx: Ctx) -> list[Finding]:
    rid, out = "mod.level.txs_pulldown", []
    for inst in _instances(ctx, "txs0108e"):
        r_pu, _f = _txs_pullup(inst)
        for pin in _data_pins(inst):
            net = ctx.net_of(inst, pin)
            if net is None or net in ctx.rails:
                continue
            for ref, r, other in _resistors(ctx, net):
                if other is None or ctx.volts(other) is None or abs(ctx.volts(other) or 0.0) > _EPS:
                    continue  # only resistors to GND (0 V rails)
                v_side = ctx.volts(ctx.net_of(inst, _side_supply(pin)))
                if r is None or v_side is None:
                    out.append(Finding(rid, "not_checked", "info",
                                       f"{ctx.label(inst)} {pin}: pull-down {ref} on {net}"
                                       + (" has no readable value" if r is None else
                                          f" but {_side_supply(pin)} is on no known rail")
                                       + "; VOH = Vcc × RPD / (RPD + 4 kΩ) not computed.", [inst.ref, ref], [SRC_TXS]))
                    continue
                voh = v_side * r / (r + r_pu)
                receivers = []
                for other_inst, opin, sig in _signals_on(ctx, net, inst.ref):
                    if other_inst.ref == ref or sig in ("supply", "gnd", "nc", "None"):
                        continue
                    vih = ctx.level(other_inst, "vih")
                    if vih is not None:
                        receivers.append((f"{other_inst.ref} {opin}", vih, other_inst))
                if _gpios(ctx, net) and isinstance(ctx.esp, Mapping) and isinstance(ctx.esp.get("vih"), int | float):
                    receivers.append((f"ESP {_gpio_text(ctx, net)}", float(ctx.esp["vih"]), None))
                low = [(who, vih, oi) for who, vih, oi in receivers if voh < vih - _EPS]
                text = (f"{ctx.label(inst)} {pin}: pull-down {ref} {fmt(r, 'Ω')} on {net} lowers the high level to "
                        f"{fmt(voh, 'V')} ({_side_supply(pin)} {fmt(v_side, 'V')} × RPD / (RPD + {fmt(r_pu, 'Ω')}), "
                        "TI eq. 1)")
                if low:
                    who, vih, oi = low[0]
                    insts = [inst] + ([oi] if oi is not None else [])
                    sids = [SRC_TXS] + ([ctx.src(oi)] if oi is not None else [])
                    out.append(ctx.finding(rid, "failed", "caution",
                                           f"{text}: below VIH {fmt(vih, 'V')} of {who}; use a larger pull-down or "
                                           "none.", insts, source_id=sids, refs=[inst.ref, ref]))
                else:
                    out.append(ctx.finding(rid, "failed", "info",
                                           f"{text}; avoid strong pull-downs or loads on TXS0108E lines.", inst,
                                           source_id=SRC_TXS, refs=[inst.ref, ref]))
    return out


@rule("mod.level.ahct_needs_5v")
def ahct_needs_5v(ctx: Ctx) -> list[Finding]:
    rid, out = "mod.level.ahct_needs_5v", []
    for inst in _instances(ctx, "sn74ahct125"):
        spec = (inst.module.get("supplies") or {}).get("VCC") or {}
        vmin = ctx.fv(spec.get("min"), inst)
        v = ctx.supply_volts(inst).get("VCC")
        if v is None or vmin is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: VCC not on a known rail; supply "
                               "domain not checked.", [inst.ref]))
            continue
        if v < vmin - _EPS:
            out.append(ctx.finding(
                rid, "failed", "info",
                f"{ctx.label(inst)}: VCC {fmt(v, 'V')}. The AHCT125 is specified for VCC "
                f"{fmt(vmin, 'V')}–5.5 V only, its TTL input levels (VIH 2 V) included; to lift 3.3 V logic to 5 V, "
                "power it from 5 V (for 3.3 V supplies use an LV/LVC part such as the SN74LV1T34).",
                inst, source_id=ctx.src(inst, spec.get("min")), supply=True))
        else:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: VCC {fmt(v, 'V')}: TTL inputs (VIH 2 V) "
                               "accept 3.3 V logic.", [inst.ref], [SRC_AHCT]))
    return out


@rule("mod.level.side_supply")
def side_supply(ctx: Ctx) -> list[Finding]:
    rid, out = "mod.level.side_supply", []
    esp_max = ctx.esp.get("v_in_max") if isinstance(ctx.esp, Mapping) else None
    for inst in _instances(ctx, *TWO_SIDED):
        src = TWO_SIDED[inst.module_id]
        sv = ctx.supply_volts(inst)
        va, vb = sv.get("VCCA"), sv.get("VCCB")
        found = False
        if va is not None and vb is not None and va > vb + _EPS:
            found = True
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{ctx.label(inst)}: VCCA {fmt(va, 'V')} above VCCB {fmt(vb, 'V')}; the datasheet "
                                   "requires VCCA ≤ VCCB (A side = lower voltage). Swap the sides.", inst,
                                   source_id=src, supply=True))
        b_gpio = [(p, ctx.net_of(inst, p)) for p in _data_pins(inst) if p.startswith("B")
                  and _gpios(ctx, ctx.net_of(inst, p))]
        if b_gpio:
            found = True
            pins_txt = ", ".join(f"{p} ({_gpio_text(ctx, n)})" for p, n in b_gpio if n)
            if vb is None or not isinstance(esp_max, int | float):
                out.append(Finding(rid, "not_checked", "info",
                                   f"{ctx.label(inst)}: ESP on the B side {pins_txt}; VCCB or the ESP input maximum "
                                   "unknown, level not checked.", [inst.ref], [src]))
            elif vb > esp_max + _EPS:
                why = ("its pull-ups pull to VCCB" if inst.module_id == "txs0108e"
                       else "its outputs drive at least VCCB − 0.4 V")
                out.append(ctx.finding(rid, "failed", "danger",
                                       f"{ctx.label(inst)}: ESP on the B side {pins_txt} with VCCB {fmt(vb, 'V')}; "
                                       f"{why}, above the ESP input maximum {fmt(esp_max, 'V')}. Connect the ESP to "
                                       "the A side (VCCA = ESP supply).", inst, source_id=src))
            else:
                out.append(Finding(rid, "passed", None,
                                   f"{ctx.label(inst)}: ESP on the B side {pins_txt} with VCCB {fmt(vb, 'V')} within "
                                   f"the ESP input maximum {fmt(esp_max, 'V')}.", [inst.ref], [src]))
        if not found and (va is not None or vb is not None):
            out.append(Finding(rid, "passed", None,
                               f"{ctx.label(inst)}: supply order and ESP side fit (VCCA "
                               f"{fmt(va, 'V') if va is not None else '?'}, VCCB "
                               f"{fmt(vb, 'V') if vb is not None else '?'}).", [inst.ref], [src]))
    return out


@rule("mod.level.oe_disabled")
def oe_disabled(ctx: Ctx) -> list[Finding]:
    rid, out = "mod.level.oe_disabled", []
    for inst in _instances(ctx, *TWO_SIDED):
        net = ctx.net_of(inst, "OE")
        if net is None:
            continue
        v = ctx.volts(net)
        if v is not None and abs(v) <= _EPS:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{ctx.label(inst)}: OE on {net}: all I/Os stay high-impedance, nothing is "
                                   "translated. Tie OE to VCCA or drive it from a GPIO after both supplies are up.",
                                   inst, source_id=TWO_SIDED[inst.module_id]))
        else:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: OE on {net}.", [inst.ref],
                               [TWO_SIDED[inst.module_id]]))
    for inst in _instances(ctx, "sn74ahct125"):
        vcc_net = ctx.net_of(inst, "VCC")
        off, on = [], []
        for ch in "1234":
            net = ctx.net_of(inst, f"{ch}OE")
            used = any(ctx.net_of(inst, f"{ch}{x}") not in (None, "GND") and ctx.net_of(inst, f"{ch}{x}")
                       not in ctx.rails for x in ("A", "Y"))
            if net is None or not used:
                continue
            v = ctx.volts(net)
            if net == vcc_net or (v is not None and v > _EPS):
                off.append(f"{ch}OE on {net}")
            else:
                on.append(f"{ch}OE")
        if off:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{ctx.label(inst)}: {', '.join(off)}: OE high disables the output "
                                   "(high-impedance). Tie OE to GND or drive it low from a GPIO.", inst,
                                   source_id=SRC_AHCT))
        elif on:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: {', '.join(on)} not tied high.",
                               [inst.ref], [SRC_AHCT]))
    return out


@rule("mod.level.bss138_wiring")
def bss138_wiring(ctx: Ctx) -> list[Finding]:
    rid, out = "mod.level.bss138_wiring", []
    for inst in _instances(ctx, "bss138"):
        g, s, d = (ctx.net_of(inst, p) for p in ("G", "S", "D"))
        vg = ctx.volts(g)
        label = ctx.label(inst)
        if g is None or vg is None:
            out.append(Finding(rid, "not_checked", "info" if g else None,
                               f"{label}: gate " + (f"on {g} with unknown voltage" if g else "not connected")
                               + "; AN10441 wiring not checked (gate to the lowest supply VDD1).", [inst.ref],
                               [SRC_AN]))
            continue
        bad: list[tuple[str, str]] = []  # (text, source id)
        if vg <= BSS138_VGS_TH_MAX_V + _EPS:
            bad.append(((f"gate supply {fmt(vg, 'V')} is not above VGS(th) max {fmt(BSS138_VGS_TH_MAX_V, 'V')}: "
                        "the MOSFET may not turn on"), SRC_BSS))
        if _gpios(ctx, d) and not _gpios(ctx, s):
            bad.append(((f"ESP ({_gpio_text(ctx, d or '')}) on the drain; AN10441 puts the lower-voltage section on "
                        "the source and the higher-voltage section on the drain"), SRC_AN))
        for pin, net in (("S", s), ("D", d)):
            if net is None or net in ctx.rails:
                continue
            for ref, _r, other in _resistors(ctx, net):
                vr = ctx.volts(other)
                if vr is None or abs(vr) <= _EPS:
                    continue
                if pin == "S" and abs(vr - vg) > 0.05:
                    bad.append(((f"source pull-up {ref} to {other} ({fmt(vr, 'V')}) differs from the gate supply "
                                f"{fmt(vg, 'V')}; the low-voltage section is pulled up to VDD1"), SRC_AN))
                if pin == "D" and vr < vg - _EPS:
                    bad.append(((f"drain pull-up {ref} to {other} ({fmt(vr, 'V')}) below the gate supply "
                                f"{fmt(vg, 'V')}; VDD2 must be equal to or higher than VDD1"), SRC_AN))
        if bad:
            sids = list(dict.fromkeys(sid for _t, sid in bad))
            out.append(ctx.finding(rid, "failed", "caution", f"{label}: " + "; ".join(t for t, _s in bad) + ".",
                                   [inst] * len(sids), source_id=sids, refs=[inst.ref]))
        else:
            out.append(Finding(rid, "passed", None, f"{label}: gate on {g} ({fmt(vg, 'V')}), wiring fits AN10441.",
                               [inst.ref], [SRC_AN, SRC_BSS]))
    return out
