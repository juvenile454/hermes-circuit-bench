"""Family rules ``pixel``: addressable LEDs and SPI TFT controllers.

- ``mod.pixel.ws2812_vih``: the data input of a 5 V-supplied WS2812B / SK6812 / APA102C driven straight from an ESP32
  GPIO (no level shifter). VIH from the pinned datasheet revision: WS2812B V6.1 0.63·VDD (older revisions 0.7·VDD),
  SK6812 3.4 V at VDD 5.0 V, APA102C 0.7·VDD (class B, image-only: hint). VIH above the GPIO's VDD -> caution
  ("no reliable data"); between the ESP's guaranteed VOH and its VDD -> caution ("outside the guarantee"). The
  generic ``mod.level_in`` compares the same levels; this rule adds the LED-specific fix (5 V-supplied
  74AHCT125-type buffer, or a lower LED supply) and names the datasheet revision, so it supersedes ``mod.level_in``
  on the same LED (one cause, one warning). VIH ``conditions`` that name a supply (WS2812B/SK6812: VDD 5 V) are read
  like the generic rule does: at another VDD -> not_checked (never interpolated), ``info`` when the LED supply lies
  above the GPIO high level.
- Hazards: WS2812B and SK6812 (and WS2813 in npixel) carry none: their datasheets give no maximum strip current (the
  LED current is a brightness test condition), so strip totals stay with ``mod.power_budget`` and calc ``led_strip``.
  WS2815 keeps its 12 V-rail hazard (data inputs rated 5.7 V).
- ``mod.pixel.tft_spi_clock``: SPI write clock limit of the TFT controller from the datasheet (1 / minimum write
  cycle) as ``info``; libraries often clock these controllers faster. Supply/logic at 5 V is covered by the generic
  ``mod.supply_range`` (abs_max 4.6 V) and ``mod.level_in``/``level_out``; no extra rule.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import elec, modcheck

Ctx, Finding, Instance, fmt, rule = (
    modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule)

LED_IDS = ("ws2812b", "sk6812", "apa102c")
TFT_IDS = ("st7789v", "ili9341", "gc9a01")
_EPS = 1e-9
_DATA_SIGNALS = ("led_data_in", "spi_sdi", "spi_sck")  # LED inputs a GPIO may drive (APA102C: DI and CI)
_FIX = ("Put a 5 V-supplied buffer with TTL inputs (e.g. 74AHCT125) between GPIO and data input, or supply the "
        "first LED from a lower voltage.")


def _vih_text(inst: Instance) -> str:
    io = inst.module.get("io") if isinstance(inst.module.get("io"), Mapping) else {}
    f = io.get("vih") if isinstance(io, Mapping) else None
    if isinstance(f, Mapping) and "rel" in f:
        return f"{f['rel']:g}·{f.get('of', 'VDD')}"
    return "datasheet value"


def _apa_vih(supplies: Mapping[str, float]) -> float | None:
    """APA102C: no F in the catalog (class B); 0.7·VDD read from the image-only datasheet (unverified)."""
    v = supplies.get("VCC")
    return None if v is None else 0.7 * v


def _input_nets(ctx: Ctx, inst: Instance) -> list[tuple[str, str, list[Any]]]:
    out = []
    for sig in _DATA_SIGNALS:
        for pin in ctx.pins_with(inst, sig):
            net = ctx.net_of(inst, pin)
            gpios = (ctx.nets.get(net) or {}).get("gpios") or [] if net else []
            if net and gpios:
                out.append((pin, net, list(gpios)))
    return out


@rule("mod.pixel.ws2812_vih")
def ws2812_vih(ctx: Ctx) -> list[Finding]:
    rid = "mod.pixel.ws2812_vih"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id not in LED_IDS:
            continue
        driven = _input_nets(ctx, inst)
        if not driven:
            continue  # data input not on an ESP GPIO net (e.g. behind a level shifter) or open (mod.unconnected)
        pins = ", ".join(p for p, _, _ in driven)
        who = f"{ctx.label(inst)} {pins}"
        if (inst.facts or {}).get("level_shifter") is True:
            out.append(Finding(rid, "passed", None, f"{who}: level shifter declared (facts.level_shifter).",
                               [inst.ref], [ctx.src(inst)] if ctx.src(inst) else []))
            continue
        supplies = ctx.supply_volts(inst)
        vdd = next(iter(supplies.values()), None)
        if ctx.esp is None or ctx.esp.get("voh") is None or ctx.esp.get("vdd") is None:
            out.append(Finding(rid, "not_checked", None, f"{who}: no ESP output levels for {ctx.chip}.", [inst.ref]))
            continue
        if vdd is None:
            out.append(Finding(rid, "not_checked", "info", f"{who}: LED supply voltage unknown, data level not "
                               "checked (name the rail voltage in options.rails).", [inst.ref]))
            continue
        vih = _apa_vih(supplies) if inst.module_id == "apa102c" else ctx.level(inst, "vih")
        if vih is None:
            out.append(Finding(rid, "not_checked", None, f"{who}: no VIH in the module data.", [inst.ref]))
            continue
        voh, v_gpio = float(ctx.esp["voh"]), float(ctx.esp["vdd"])
        src = ctx.src(inst)
        f_vih = (inst.module.get("io") or {}).get("vih") if inst.module_id != "apa102c" else None
        cond_ok, why = elec._cond_ok(ctx, inst, f_vih)  # same reading of ``conditions`` as mod.level_in
        if not cond_ok:
            above = vdd > v_gpio + _EPS
            out.append(Finding(rid, "not_checked", "info" if above else None,
                               f"{who}: VIH not checked: {why} (never interpolated)."
                               + (f" The LED supply is above the GPIO high level: {_FIX}" if above else ""),
                               [inst.ref], [src] if src else []))
            continue
        how = f"VIH {fmt(vih, 'V')} ({_vih_text(inst) if inst.module_id != 'apa102c' else '0.7·VDD, unverified'}"
        how += f" at VDD {fmt(vdd, 'V')})"
        if inst.module_id == "ws2812b":
            how += ", datasheet revision V6.1 (older revisions: 0.7·VDD)"
        if vih <= voh + _EPS:
            out.append(Finding(rid, "passed", None, f"{who}: {how} ≤ ESP VOH min {fmt(voh, 'V')}.", [inst.ref],
                               [src] if src else []))
        elif vih <= v_gpio + _EPS:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{who}: {how} is above the guaranteed ESP VOH min {fmt(voh, 'V')}; a "
                                   f"{fmt(v_gpio, 'V')} GPIO reaches it only when unloaded (outside the "
                                   f"guarantee). {_FIX}", inst, source_id=src, chip_fact=False))
        else:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{who}: {how} is above the GPIO high level {fmt(v_gpio, 'V')}: the LEDs will "
                                   f"not see reliable data without a level shifter. {_FIX}", inst, source_id=src,
                                   chip_fact=False))
    for f in out:
        f.supersedes = ("mod.level_in",)  # same VIH on the same LED; this rule adds the LED-specific fix
    return out


@rule("mod.pixel.tft_spi_clock")
def tft_spi_clock(ctx: Ctx) -> list[Finding]:
    rid = "mod.pixel.tft_spi_clock"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id not in TFT_IDS:
            continue
        spi = next((i for i in inst.module.get("interfaces") or [] if isinstance(i, Mapping)
                    and i.get("type") == "spi"), None)
        f = spi.get("f_max_hz") if spi else None
        hz = ctx.fv(f, inst)
        if hz is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: no SPI clock limit in the module data "
                               "(preliminary datasheet).", [inst.ref]))
            continue
        cond = f.get("conditions", "") if isinstance(f, Mapping) else ""
        out.append(ctx.finding(rid, "failed", "info",
                               f"{ctx.label(inst)}: datasheet SPI write clock max {fmt(hz, 'Hz')} "
                               f"({cond}). Display libraries often use a higher SPI clock; above "
                               "this value the display runs outside its specification.", inst,
                               source_id=ctx.src(inst, f), chip_fact=False))
    return out
