"""Family rules ``logic``: 74HC logic and muxes, I²S audio parts.

- ``mod.logic.hc_vih_5v_not_checked``: SN74HC595, SN74HC165, CD74HC4067, CD74HC4051 inputs driven by an ESP GPIO.
  TI gives VIH only at VCC = 2 V, 4.5 V and 6 V (1.5 / 3.15 / 4.2 V). At exactly one of those points VIH is compared
  with the ESP's guaranteed VOH (above it -> ``caution``: the high level is not guaranteed). At any other VCC
  (3.3 V, 5 V …) nothing is interpolated: ``not_checked`` with the reason; above the ESP's VDD (a 5 V supply) with
  severity ``info`` and the bracketing datasheet values, at or below it without a severity (no warning).
  ``facts.level_shifter`` true -> ``passed``.
- ``mod.logic.mux_analog_vcc``: CD74HC4067 / CD74HC4051 channel and COM pins on a net with a known voltage (rails,
  ``options.rails``). The analog range is 0…VCC (4067) / VEE…VCC (4051, recommended operating conditions); beyond
  VCC + 0.5 V or below VEE/GND − 0.5 V the clamp diodes conduct (absolute maximum ±20 mA, a stiff rail does not limit
  that current) -> ``danger``; between the range limit and that 0.5 V -> ``caution``. Nets without a known voltage
  (sensor signals) are not claimed.
- ``mod.logic.inmp441_lr``: INMP441 L/R selects the channel, low = left, high = right (p. 8). L/R open -> ``caution``
  (the channel is undefined); a known voltage between VIL (0.25·VDD) and VIH (0.7·VDD) -> ``caution``; two
  microphones on one SD net with the same channel -> ``caution`` (both drive the same half-frame), more than two on one
  SD net -> ``caution`` (one I²S frame has two channels, p. 11).

One cause, one warning (``Finding.supersedes``): ``hc_vih_5v_not_checked`` covers the generic ``mod.level_in`` on the
same chip (same VIH, the family rule names the datasheet points and the fix); an open L/R covers ``mod.unconnected``
on the microphone when L/R is its only open pin (otherwise the other open pins stay visible).

Not a rule of its own: ``hc165_qh_5v`` (QH of an SN74HC165 at 5 V driving an ESP input) is the generic
``mod.level_out`` (push-pull output, I/O domain VCC 5 V > ESP input maximum -> danger); tests/test_mod_logic.py
covers it. The MAX98357A speaker outputs are ``power_out`` with a ``high_current`` hazard in the data (generic
``mod.hazard``).

Every limit below carries source, page and the verbatim excerpt line(s) (tests/test_mod_logic.py checks them against
tests/corpus/excerpts/mod-logic-*.txt).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = (
    modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule)

_EPS = 1e-6  # volts: a supply "is" a datasheet point only when it equals it

# module id -> VIH table {VCC: VIH} exactly as in the datasheet (no other points exist) with evidence
# (source id, page, [lines]) for every value.
HC_VIH: dict[str, dict[str, Any]] = {
    "sn74hc595": {
        "source": "mod-logic-sn74hc595-ds", "page": 4,
        "table": {2.0: 1.5, 4.5: 3.15, 6.0: 4.2},
        "evidence": ["VIH High-level input voltage", "VCC = 2 V 1.5 1.5", "VVCC = 4.5 V 3.15 3.15", "VCC = 6 V 4.2 4.2"],
    },
    "sn74hc165": {
        "source": "mod-logic-sn74hc165-ds", "page": 4,
        "table": {2.0: 1.5, 4.5: 3.15, 6.0: 4.2},
        "evidence": ["VCC = 2 V 1.5", "VIH High-level input voltage VCC = 4.5 V 3.15 V", "VCC = 6 V 4.2"],
    },
    "cd74hc4067": {
        "source": "mod-logic-cd74hc4067-ds", "page": 7,
        "table": {2.0: 1.5, 4.5: 3.15, 6.0: 4.2},
        "evidence": ["High Level Input Voltage VIH", "2", "–40°C to +85°C 1.5", "4.5", "–40°C to +85°C 3.15", "6",
                     "–40°C to +85°C 4.2"],
    },
    "cd74hc4051": {
        "source": "mod-logic-cd74hc4051-ds", "page": 8,
        "table": {2.0: 1.5, 4.5: 3.15, 6.0: 4.2},
        "evidence": ["Input High Voltage, VIH, Min", "2", "25°C 1.5", "4.5", "25°C 3.15", "6", "25°C 4.2"],
    },
}

# mux id -> analog pins, range limits and evidence
MUX: dict[str, dict[str, Any]] = {
    "cd74hc4067": {
        "source": "mod-logic-cd74hc4067-ds",
        "pins": ("COM", *(f"I{i}" for i in range(16))), "low": None,  # GND
        "op_ev": (6, ["VIS Analog switch I/O voltage 0 VCC V"]),
        "abs_ev": (5, ["IIK DC input diode current For VI < -0.5V or VI > VCC + 0.5V –20 20 mA"]),
    },
    "cd74hc4051": {
        "source": "mod-logic-cd74hc4051-ds",
        "pins": ("COM", *(f"A{i}" for i in range(8))), "low": "VEE",
        "op_ev": (7, ["VIS Analog switch I/O voltage VEE VCC V"]),
        "abs_ev": (6, ["DC switch diode current VI < VEE – 0.5V or VI > VCC + 0.5V –20 20 mA"]),
    },
}
CLAMP_V = 0.5  # VCC + 0.5 V / VEE − 0.5 V, the clamp-diode limits quoted above

INMP441 = {
    "source": "mod-logic-inmp441-ds",
    "lr_ev": (8, ["4 L/R Left/Right Channel Select. When set low, the microphone outputs its signal in the left channel"]),
    "vih_rel": 0.7, "vil_rel": 0.25,
    "level_ev": (5, ["Input Voltage High (VIH) L/R, WS, SCK 0.7 x VDD", "Input Voltage Low (VIL) L/R, WS, SCK 0  0.25 x VDD"]),
    "stereo_ev": (11, ["application, the SD pins of the left and right INMP441 microphones should be tied together"]),
}


def _esp_v(ctx: Ctx, key: str) -> float | None:
    v = (ctx.esp or {}).get(key)
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _esp_src(ctx: Ctx) -> list[str]:
    return [s for s in (ctx.esp or {}).get("source_ids") or [] if isinstance(s, str)]


def _sids(*groups: Any) -> list[str]:
    out: list[str] = []
    for g in groups:
        for s in ([g] if isinstance(g, str) or g is None else g):
            if isinstance(s, str) and s and s not in out:
                out.append(s)
    return out


def _driven_inputs(ctx: Ctx, inst: Instance) -> list[str]:
    """Input pins of the instance (SIGNAL_DIRECTION "in") on a net with an ESP GPIO."""
    out = []
    for p in inst.module.get("pins") or []:
        if not isinstance(p, Mapping) or modcheck.modspec.SIGNAL_DIRECTION.get(str(p.get("signal"))) != "in":
            continue
        net = inst.conn.get(p["name"])
        if net is not None and (ctx.nets.get(net) or {}).get("gpios"):
            out.append(p["name"])
    return out


# --- mod.logic.hc_vih_5v_not_checked -----------------------------------------------------------------------------
@rule("mod.logic.hc_vih_5v_not_checked")
def hc_vih_5v_not_checked(ctx: Ctx) -> list[Finding]:
    rid = "mod.logic.hc_vih_5v_not_checked"
    out: list[Finding] = []
    for inst in ctx.instances:
        spec = HC_VIH.get(inst.module_id)
        if spec is None:
            continue
        pins = _driven_inputs(ctx, inst)
        if not pins:
            continue
        src = spec["source"]
        who = f"{ctx.label(inst)} {', '.join(pins)}"
        if (inst.facts or {}).get("level_shifter") is True:
            out.append(Finding(rid, "passed", None, f"{who}: level shifter on the board (facts.level_shifter, user).",
                               [inst.ref], [src]))
            continue
        vcc = ctx.supply_volts(inst).get("VCC")
        voh, vdd = _esp_v(ctx, "voh"), _esp_v(ctx, "vdd")
        if vcc is None:
            out.append(Finding(rid, "not_checked", "info", f"{who}: VCC unknown, input high level not checked.",
                               [inst.ref], [src]))
            continue
        if voh is None or vdd is None:
            out.append(Finding(rid, "not_checked", "info", f"{who}: no VOH for chip {ctx.chip}, input high level not "
                               "checked.", [inst.ref], [src]))
            continue
        sids = _sids(src, _esp_src(ctx))
        point = next((k for k in spec["table"] if abs(k - vcc) < _EPS), None)
        if point is not None:
            vih = spec["table"][point]
            if vih > voh + 1e-9:
                out.append(ctx.finding(
                    rid, "failed", "caution",
                    f"{who}: at VCC {fmt(vcc, 'V')} the datasheet VIH is {fmt(vih, 'V')}, above the ESP's guaranteed "
                    f"VOH {fmt(voh, 'V')} (high up to {fmt(vdd, 'V')}): the high level is not guaranteed. Run the "
                    "chip at 3.3 V, use the 74HCT type or a level shifter.", inst, source_id=src, source_ids=sids))
            else:
                out.append(Finding(rid, "passed", None, f"{who}: VIH {fmt(vih, 'V')} at VCC {fmt(vcc, 'V')} ≤ the "
                                   f"ESP's VOH {fmt(voh, 'V')}.", [inst.ref], sids))
            continue
        known = ", ".join(f"{fmt(v, 'V')} at VCC {fmt(k, 'V')}" for k, v in sorted(spec["table"].items()))
        why = (f"{who}: the datasheet gives VIH only at three supply voltages ({known}); at {fmt(vcc, 'V')} it is "
               "not given and is not interpolated")
        if vcc > vdd + 1e-9:
            at45 = spec["table"].get(4.5)
            extra = (f" Already at VCC 4.5 V, VIH {fmt(at45, 'V')} lies above the ESP's guaranteed VOH "
                     f"{fmt(voh, 'V')}: a 3.3 V GPIO high is not guaranteed. Run the chip at 3.3 V, use the 74HCT "
                     "type or a level shifter.") if at45 is not None and at45 > voh else ""
            out.append(Finding(rid, "not_checked", "info", why + "." + extra, [inst.ref], sids))
        else:
            out.append(Finding(rid, "not_checked", None, why + ".", [inst.ref], sids))
    for f in out:
        f.supersedes = ("mod.level_in",)  # same VIH on the same chip: this rule names the datasheet points and the fix
    return out


# --- mod.logic.mux_analog_vcc ------------------------------------------------------------------------------------
@rule("mod.logic.mux_analog_vcc")
def mux_analog_vcc(ctx: Ctx) -> list[Finding]:
    rid = "mod.logic.mux_analog_vcc"
    out: list[Finding] = []
    for inst in ctx.instances:
        spec = MUX.get(inst.module_id)
        if spec is None:
            continue
        live = [(pin, net, ctx.volts(net)) for pin in spec["pins"] if (net := ctx.net_of(inst, pin)) is not None]
        live = [(pin, net, v) for pin, net, v in live if v is not None]
        if not live:
            continue  # no analog pin on a net with a known voltage: nothing to claim
        src = spec["source"]
        sv = ctx.supply_volts(inst)
        vcc = sv.get("VCC")
        low_pin = spec["low"]
        lo = ctx.volts(ctx.net_of(inst, low_pin)) if low_pin else 0.0  # VEE is a gnd-signal pin, not in supplies
        lo_name = low_pin or "GND"
        if vcc is None or lo is None:
            miss = "VCC" if vcc is None else low_pin
            out.append(Finding(rid, "not_checked", "info", f"{ctx.label(inst)}: {miss} voltage unknown, analog pins "
                               "on known rails not checked.", [inst.ref], [src]))
            continue
        bad = False
        for pin, net, v in live:
            if v > vcc + CLAMP_V + 1e-9 or v < lo - CLAMP_V - 1e-9:
                bad = True
                lim = f"VCC + 0.5 V = {fmt(vcc + CLAMP_V, 'V')}" if v > vcc else \
                    f"{lo_name} − 0.5 V = {fmt(lo - CLAMP_V, 'V')}"
                out.append(ctx.finding(
                    rid, "failed", "danger",
                    f"{ctx.label(inst)} {pin} on {net} = {fmt(v, 'V')} is beyond {lim}: the clamp diodes conduct "
                    "(absolute maximum ±20 mA) and a rail does not limit that current. Keep the signal within "
                    f"{lo_name}…VCC or raise VCC.", inst, source_id=src))
            elif v > vcc + 1e-9 or v < lo - 1e-9:
                bad = True
                out.append(ctx.finding(
                    rid, "failed", "caution",
                    f"{ctx.label(inst)} {pin} on {net} = {fmt(v, 'V')} is outside the analog range "
                    f"{lo_name}…VCC ({fmt(lo, 'V')}…{fmt(vcc, 'V')}): the switch does not pass it and the pin is outside "
                    "the recommended operating conditions.", inst, source_id=src))
        if not bad:
            pins = ", ".join(p for p, _, _ in live)
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)} {pins}: within {lo_name}…VCC "
                               f"({fmt(lo, 'V')}…{fmt(vcc, 'V')}).", [inst.ref], [src]))
    return out


# --- mod.logic.inmp441_lr ----------------------------------------------------------------------------------------
def _channel(ctx: Ctx, inst: Instance) -> tuple[str, str]:
    """(channel, text): channel "left" | "right" | "gpio" | "open" | "between" | "unknown"."""
    net = ctx.net_of(inst, "L/R")
    if net is None:
        return "open", "L/R is not connected"
    if (ctx.nets.get(net) or {}).get("gpios"):
        return "gpio", f"L/R on {net}, set by the firmware"
    v = ctx.volts(net)
    vdd = ctx.supply_volts(inst).get("VDD")
    if v is None:
        return "unknown", f"L/R on {net} (voltage unknown)"
    if vdd is None:
        if abs(v) < 1e-9:
            return "left", f"L/R on {net} (low)"
        return "unknown", f"L/R on {net} = {fmt(v, 'V')}, VDD unknown"
    if v <= INMP441["vil_rel"] * vdd + 1e-9:
        return "left", f"L/R on {net} (low)"
    if v >= INMP441["vih_rel"] * vdd - 1e-9:
        return "right", f"L/R on {net} (high)"
    return "between", (f"L/R on {net} = {fmt(v, 'V')}, between VIL {fmt(INMP441['vil_rel'] * vdd, 'V')} and VIH "
                       f"{fmt(INMP441['vih_rel'] * vdd, 'V')}")


def _only_open_pin(inst: Instance, name: str) -> bool:
    """Is ``name`` the only pin of the instance without a net?"""
    pins = [p.get("name") for p in inst.module.get("pins") or [] if isinstance(p, Mapping)]
    return all(inst.conn.get(p) for p in pins if p != name)


@rule("mod.logic.inmp441_lr")
def inmp441_lr(ctx: Ctx) -> list[Finding]:
    rid = "mod.logic.inmp441_lr"
    src = INMP441["source"]
    mics = [i for i in ctx.instances if i.module_id == "inmp441"]
    out: list[Finding] = []
    chans: dict[str, tuple[str, str]] = {}
    for inst in mics:
        ch, text = _channel(ctx, inst)
        chans[inst.ref] = (ch, text)
        if ch == "open":
            f = ctx.finding(rid, "failed", "caution",
                            f"{ctx.label(inst)}: L/R is open; the datasheet defines only low (left channel) and "
                            "high (right channel), so the channel is undefined. Tie L/R to GND or VDD.",
                            inst, source_id=src)
            if _only_open_pin(inst, "L/R"):
                f.supersedes = ("mod.unconnected",)  # the generic open-pin finding names the same pin
            out.append(f)
        elif ch == "between":
            out.append(ctx.finding(rid, "failed", "caution", f"{ctx.label(inst)}: {text}: the channel is undefined.",
                                   inst, source_id=src))
    by_sd: dict[str, list[Instance]] = {}
    for inst in mics:
        net = ctx.net_of(inst, "SD")
        if net is not None:
            by_sd.setdefault(net, []).append(inst)
    flagged: set[str] = set()
    for net, group in by_sd.items():
        if len(group) < 2:
            continue
        if len(group) > 2:
            flagged.update(i.ref for i in group)
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{', '.join(ctx.label(i) for i in group)} share SD net {net}: one I²S frame has "
                                   "two channels, so at most two microphones (one left, one right) can share a data "
                                   "line.", group, source_id=[src] * len(group)))
            continue
        a, b = group
        ca, cb = chans[a.ref][0], chans[b.ref][0]
        if ca == cb and ca in ("left", "right"):
            flagged.update((a.ref, b.ref))
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{ctx.label(a)} and {ctx.label(b)} share SD net {net} and both use the {ca} channel: "
                                   "both drive the same half-frame and the data collide. Set one L/R low and the other "
                                   "high.", group, source_id=[src, src]))
    for inst in mics:
        ch, text = chans[inst.ref]
        if inst.ref in flagged or ch in ("open", "between"):
            continue
        if ch in ("left", "right", "gpio"):
            what = f"{ch} channel" if ch != "gpio" else "channel set by a GPIO"
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: {text}: {what}.", [inst.ref], [src]))
        else:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: {text}; channel not determined.",
                               [inst.ref], [src]))
    return out
